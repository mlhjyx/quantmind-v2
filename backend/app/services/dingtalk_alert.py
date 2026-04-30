"""DingTalk alert helper with cross-process alert_dedup (1h default TTL).

批 2 P0 修 (2026-04-30) 共用 helper for T0-15 (LL-081 guard v2) + T0-16
(qmt_data_service fail-loud) + 未来 risk_event_log audit alert paths.

设计原则:
    - 双锁守门: settings.DINGTALK_ALERTS_ENABLED=False default-off, 即使 webhook
      URL 配置仍不真发. True 时配合 alert_dedup TTL 去重才真发.
    - 跨进程去重: 写 alert_dedup 表 (跨 schtask + Servy 进程持久, 不依赖内存
      throttler). dedup_key caller 显式传, e.g. "qmt_data_service:disconnect".
    - sync httpx (简单 + retry 1 次, 沿用 Q8 决议).
    - 铁律 33 fail-loud: helper 失败 raise 让 caller 决议 (非 silent).
    - 1h TTL 默认 (settings.DINGTALK_DEDUP_TTL_MIN=60), severity 驱动 caller 可 override.

依赖:
    backend/migrations/alert_dedup.sql (PR feat/batch-2-p0-fixes commit 1 已 apply)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from app.config import settings
from app.services.db import get_sync_conn

logger = logging.getLogger(__name__)

Severity = Literal["p0", "p1", "p2", "info"]

# 默认 suppress_minutes 由 severity 驱动 (alert_dedup.sql L38-40 沿用)
SEVERITY_DEFAULT_SUPPRESS_MIN: dict[str, int] = {
    "p0": 5,
    "p1": 30,
    "p2": 60,
    "info": 60,
}

# httpx timeout (sync, single attempt)
HTTPX_TIMEOUT_SEC = 5.0


def send_with_dedup(
    *,
    dedup_key: str,
    severity: Severity,
    source: str,
    title: str,
    body: str = "",
    suppress_minutes: int | None = None,
    conn: Any = None,
) -> dict[str, Any]:
    """发钉钉告警 (双锁 + alert_dedup 去重).

    Args:
        dedup_key: caller 显式去重键, e.g. "qmt_data_service:disconnect_5min".
        severity: 'p0' / 'p1' / 'p2' / 'info'.
        source: 发源模块名, e.g. "qmt_data_service" / "ll081_guard_v2".
        title: 告警标题 (写 alert_dedup.last_title 审计用).
        body: markdown body.
        suppress_minutes: 抑制窗口分钟. None 时 severity 驱动 default
            (p0=5min/p1=30min/p2=60min/info=60min). Caller 显式传 override.
        conn: psycopg2 connection (None → app.services.db.get_conn).

    Returns:
        {
            "sent": bool,           # 是否真 POST 钉钉
            "dedup_hit": bool,      # 是否被 alert_dedup 抑制
            "reason": str,          # "sent" / "dedup_suppressed" / "alerts_disabled" / "no_webhook"
            "dedup_key": str,
            "fire_count": int,      # alert_dedup 累计触发数
        }

    Raises:
        ValueError: dedup_key/source 空 / severity 不在 enum
        psycopg2.errors.*: DB 写 alert_dedup 失败
        httpx.HTTPError: 真 POST 失败 (DINGTALK_ALERTS_ENABLED=True 时)
    """
    if not dedup_key or not dedup_key.strip():
        raise ValueError("dedup_key 必填非空")
    if not source or not source.strip():
        raise ValueError("source 必填非空")
    if severity not in SEVERITY_DEFAULT_SUPPRESS_MIN:
        raise ValueError(f"severity={severity} 不在 enum (p0/p1/p2/info)")

    if suppress_minutes is None:
        suppress_minutes = SEVERITY_DEFAULT_SUPPRESS_MIN[severity]

    own_conn = False
    if conn is None:
        conn = get_sync_conn()
        own_conn = True

    try:
        # Step 1: dedup 检查 + UPSERT alert_dedup row
        dedup_hit, fire_count = _upsert_dedup(
            conn=conn,
            dedup_key=dedup_key,
            severity=severity,
            source=source,
            title=title,
            suppress_minutes=suppress_minutes,
        )

        if dedup_hit:
            logger.info(
                "[dingtalk_alert] dedup_hit dedup_key=%s severity=%s fire_count=%d",
                dedup_key, severity, fire_count,
            )
            return {
                "sent": False,
                "dedup_hit": True,
                "reason": "dedup_suppressed",
                "dedup_key": dedup_key,
                "fire_count": fire_count,
            }

        # Step 2: 双锁 — DINGTALK_ALERTS_ENABLED gate
        if not settings.DINGTALK_ALERTS_ENABLED:
            logger.warning(
                "[dingtalk_alert] alerts_disabled (DINGTALK_ALERTS_ENABLED=False), "
                "audit-only dedup_key=%s severity=%s",
                dedup_key, severity,
            )
            return {
                "sent": False,
                "dedup_hit": False,
                "reason": "alerts_disabled",
                "dedup_key": dedup_key,
                "fire_count": fire_count,
            }

        # Step 3: webhook URL 必填
        if not settings.DINGTALK_WEBHOOK_URL:
            logger.warning("[dingtalk_alert] DINGTALK_WEBHOOK_URL empty, skip POST")
            return {
                "sent": False,
                "dedup_hit": False,
                "reason": "no_webhook",
                "dedup_key": dedup_key,
                "fire_count": fire_count,
            }

        # Step 4: 真 POST (sync httpx + retry 1 次)
        _post_to_dingtalk(
            webhook_url=settings.DINGTALK_WEBHOOK_URL,
            title=title,
            body=body,
            severity=severity,
        )

        logger.info(
            "[dingtalk_alert] sent dedup_key=%s severity=%s source=%s",
            dedup_key, severity, source,
        )
        return {
            "sent": True,
            "dedup_hit": False,
            "reason": "sent",
            "dedup_key": dedup_key,
            "fire_count": fire_count,
        }
    finally:
        if own_conn and conn is not None:
            conn.commit()
            conn.close()


def _upsert_dedup(
    *,
    conn: Any,
    dedup_key: str,
    severity: str,
    source: str,
    title: str,
    suppress_minutes: int,
) -> tuple[bool, int]:
    """alert_dedup UPSERT — 返 (dedup_hit, new_fire_count).

    Logic:
      - SELECT existing row (suppress_until > NOW() → dedup_hit=True)
      - 否则 UPSERT (last_fired_at=NOW(), suppress_until=NOW()+suppress_min, fire_count++)
    """
    cur = conn.cursor()

    # 检查 existing row
    cur.execute(
        """
        SELECT suppress_until, fire_count FROM alert_dedup WHERE dedup_key = %s
        """,
        (dedup_key,),
    )
    row = cur.fetchone()
    now = datetime.now(timezone.utc)

    if row is not None and row[0] > now:
        # dedup_hit — 抑制中, 但 fire_count 仍累加 (审计 / 风暴检测)
        cur.execute(
            "UPDATE alert_dedup SET fire_count = fire_count + 1 WHERE dedup_key = %s",
            (dedup_key,),
        )
        new_count = (row[1] or 0) + 1
        cur.close()
        return True, new_count

    # 非 dedup_hit — UPSERT 新窗口
    suppress_until = now + timedelta(minutes=suppress_minutes)
    cur.execute(
        """
        INSERT INTO alert_dedup (
            dedup_key, severity, source, last_fired_at, suppress_until,
            fire_count, last_title
        ) VALUES (%s, %s, %s, %s, %s, 1, %s)
        ON CONFLICT (dedup_key) DO UPDATE SET
            severity = EXCLUDED.severity,
            source = EXCLUDED.source,
            last_fired_at = EXCLUDED.last_fired_at,
            suppress_until = EXCLUDED.suppress_until,
            fire_count = alert_dedup.fire_count + 1,
            last_title = EXCLUDED.last_title
        RETURNING fire_count
        """,
        (dedup_key, severity, source, now, suppress_until, title),
    )
    fire_count = cur.fetchone()[0]
    cur.close()
    return False, fire_count


def _post_to_dingtalk(
    *,
    webhook_url: str,
    title: str,
    body: str,
    severity: str,
) -> None:
    """sync httpx POST + retry 1 次. 失败 raise httpx.HTTPError."""
    severity_emoji = {"p0": "🔴", "p1": "🟠", "p2": "🟡", "info": "ℹ️"}.get(severity, "")
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"{severity_emoji} {title}",
            "text": f"{severity_emoji} **{title}**\n\n{body}\n\n_severity={severity}_",
        },
    }

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = httpx.post(webhook_url, json=payload, timeout=HTTPX_TIMEOUT_SEC)
            resp.raise_for_status()
            return
        except httpx.HTTPError as e:
            last_err = e
            logger.warning(
                "[dingtalk_alert] POST attempt %d/2 failed: %s", attempt, e
            )

    # 2 attempts 全失败 — fail-loud raise (铁律 33)
    raise last_err or httpx.HTTPError("DingTalk POST 双 attempt 全失败")
