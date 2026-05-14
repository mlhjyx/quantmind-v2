"""Email alert helper — HC-1b2 元告警 channel fallback chain 备用通道 (V3 §13.3).

元告警 channel fallback chain: 主 DingTalk → 备 email → 极端 log-P0. 本 helper = 备
email 段. 仅 meta_monitor_service._push_via_channel_chain 在主 DingTalk 不可用时调用
(DingTalk attempt 已写 alert_dedup audit row — email 是同一 alert 的 backup channel,
故本 helper 0 dedup, 区别于 dingtalk_alert.send_with_dedup).

设计原则 (沿用 dingtalk_alert.py 体例):
  - 双锁守门: EMAIL_ALERTS_ENABLED=False default-off + SMTP config (HOST/FROM/TO)
    必须全配齐才真发. 任一空 → 返回 disabled/no_config dict (channel chain
    fall-through to log-P0, 反 silent skip — logged + reason 显式).
  - sync smtplib STARTTLS, 单次 attempt — channel chain 已是主 DingTalk 失败后的
    backup, email 再失败 → escalate log-P0, email 内部无需 retry.
  - 铁律 33 fail-loud: smtplib 真发失败 raise (caller channel chain catch → log-P0).
  - 铁律 35: SMTP_PASSWORD env-var only (.env .gitignore'd, 0 fallback 默认值).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# smtplib timeout (sync, single attempt — channel chain backup segment).
_SMTP_TIMEOUT_SEC = 10.0


def send_email_alert(*, subject: str, body: str, source: str) -> dict[str, Any]:
    """发 email 告警 (双锁 + STARTTLS, 单次 attempt).

    Args:
        subject: email subject line.
        body: email body (plain text).
        source: 发源模块名 (e.g. "meta_monitor") — 写 log audit.

    Returns:
        {"sent": bool, "reason": str}
          reason ∈ "sent" / "email_alerts_disabled" / "no_smtp_config"

    Raises:
        ValueError: subject / source 空.
        smtplib.SMTPException / OSError: 真发失败 (铁律 33 fail-loud — caller
            channel chain catch → escalate to 极端 log-P0).
    """
    if not subject or not subject.strip():
        raise ValueError("subject 必填非空")
    if not source or not source.strip():
        raise ValueError("source 必填非空")

    # Step 1: 双锁 — EMAIL_ALERTS_ENABLED gate (default-off, sustained DingTalk 体例)
    if not settings.EMAIL_ALERTS_ENABLED:
        logger.warning(
            "[email_alert] email_alerts_disabled (EMAIL_ALERTS_ENABLED=False) source=%s",
            source,
        )
        return {"sent": False, "reason": "email_alerts_disabled"}

    # Step 2: SMTP config 必填 (HOST + FROM + 至少 1 recipient)
    recipients = [r.strip() for r in settings.ALERT_EMAIL_TO.split(",") if r.strip()]
    if not (settings.SMTP_HOST and settings.SMTP_FROM and recipients):
        logger.warning(
            "[email_alert] no_smtp_config (SMTP_HOST/SMTP_FROM/ALERT_EMAIL_TO incomplete) "
            "source=%s",
            source,
        )
        return {"sent": False, "reason": "no_smtp_config"}

    # Step 3: build + send (铁律 33 fail-loud — SMTP error propagates to channel chain)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    # Port 465 = implicit TLS (SMTP_SSL, connection already encrypted, no STARTTLS).
    # Other ports (587 submission default) = plaintext connect + STARTTLS upgrade.
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=_SMTP_TIMEOUT_SEC
        ) as smtp:
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=_SMTP_TIMEOUT_SEC
        ) as smtp:
            smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)

    logger.info(
        "[email_alert] sent source=%s subject=%r recipients=%d",
        source,
        subject,
        len(recipients),
    )
    return {"sent": True, "reason": "sent"}


__all__ = ["send_email_alert"]
