"""Live Trading Guard — 真金硬开关 (T1 sprint link-pause, 2026-04-29).

在 ``MiniQMTBroker.place_order`` / ``cancel_order`` 前置, 默认 fail-secure 阻断真实
xtquant 调用. 双因素 OVERRIDE 才允许 bypass + 审计 + DingTalk P0.

设计:
  - 单源: ``settings.LIVE_TRADING_DISABLED`` (默认 True, 铁律 34)
  - 双因素 OVERRIDE 加固 1: ``LIVE_TRADING_FORCE_OVERRIDE=1`` + ``LIVE_TRADING_OVERRIDE_REASON``
    (非空, strip 后非空), 缺一拒绝
  - 审计加固 2: bypass 时同步 (a) ``logger.warning`` 含 audit dict / (b) DingTalk P0
    推送 / (c) sys.argv[0] 调用脚本记录
  - 物理隔离: paper_broker.py 不 import 本模块, paper 路径不受影响

铁律: 33 (fail-loud) / 34 (single source) / X2 候选 (真金硬开关, ADR-022 归属待写)

调用方:
    from app.security.live_trading_guard import assert_live_trading_allowed

    def place_order(self, code, ...):
        self._ensure_connected()
        assert_live_trading_allowed(operation="place_order", code=code)
        # ... 真实调 xtquant.order_stock ...

OVERRIDE 用法 (紧急 manual):
    set LIVE_TRADING_FORCE_OVERRIDE=1
    set LIVE_TRADING_OVERRIDE_REASON="Emergency close 600519.SH after gap-down"
    .venv/Scripts/python.exe scripts/emergency_close_all_positions.py --code 600519.SH

撤销: docs/audit/link_paused_2026_04_29.md
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime

from app.config import settings
from app.exceptions import LiveTradingDisabledError
from app.services.notification_service import send_alert

logger = logging.getLogger(__name__)

_OVERRIDE_FLAG_ENV = "LIVE_TRADING_FORCE_OVERRIDE"
_OVERRIDE_REASON_ENV = "LIVE_TRADING_OVERRIDE_REASON"


def assert_live_trading_allowed(
    operation: str,
    code: str | None = None,
) -> None:
    """Block real broker call unless LIVE_TRADING_DISABLED=False or 双因素 OVERRIDE.

    Args:
        operation: e.g. "place_order" / "cancel_order" — for audit trail.
        code: stock code if applicable — for audit trail.

    Raises:
        LiveTradingDisabledError:
          - settings.LIVE_TRADING_DISABLED=True 且 OVERRIDE 缺失/不全设
          - OVERRIDE FLAG=1 但 REASON 空 (加固 1 双因素拒绝)

    Side effects (bypass active):
        - logger.warning with structured audit dict (含 timestamp / script /
          reason / operation / code / EXECUTION_MODE)
        - DingTalk P0 alert via notification_service.send_alert (失败 silent_ok)
    """
    if not settings.LIVE_TRADING_DISABLED:
        return  # guard 关闭, 直接放行

    override_flag = os.environ.get(_OVERRIDE_FLAG_ENV, "").strip()
    override_reason = os.environ.get(_OVERRIDE_REASON_ENV, "").strip()

    op_str = operation + (f" code={code}" if code else "")

    if override_flag != "1":
        raise LiveTradingDisabledError(
            f"LIVE_TRADING_DISABLED=true, blocking {op_str}. "
            f"To bypass, set both {_OVERRIDE_FLAG_ENV}=1 and "
            f"{_OVERRIDE_REASON_ENV}='<explicit reason>' in env. "
            "撤销: docs/audit/link_paused_2026_04_29.md"
        )

    if not override_reason:
        # 加固 1: 双因素 — flag 设了但 reason 空 → 拒绝
        raise LiveTradingDisabledError(
            f"{_OVERRIDE_FLAG_ENV}=1 set but {_OVERRIDE_REASON_ENV} is empty. "
            f"Override requires explicit non-empty reason for {op_str}. "
            "Audit trail demands accountability."
        )

    # OVERRIDE bypass active — 加固 2: 审计
    timestamp = datetime.now(UTC).isoformat()
    script = sys.argv[0] if sys.argv else "<unknown>"
    audit_payload = {
        "event": "live_trading_override_bypass",
        "operation": operation,
        "code": code,
        "reason": override_reason,
        "timestamp_utc": timestamp,
        "script": script,
        "execution_mode": settings.EXECUTION_MODE,
        "live_trading_disabled": settings.LIVE_TRADING_DISABLED,
    }
    logger.warning(
        "[live-trading-guard] OVERRIDE bypass active: %s",
        audit_payload,
        extra={"audit": audit_payload},
    )

    # DingTalk P0 推送
    # reviewer P2 (oh-my-claudecode:security-reviewer) 采纳: override_reason / script
    # 来自 env / sys.argv, 直接嵌 DingTalk markdown 的 backtick 内有 backtick 注入风险
    # (` 折断 code span → 误导性告警内容). sanitize backtick → 单引号 + 限长.
    safe_reason = override_reason.replace("`", "'")[:200]
    safe_script = script.replace("`", "'")[:100]
    try:
        title = f"⚠️ LIVE_TRADING_FORCE_OVERRIDE active ({operation})"
        content = (
            f"**真金保护 OVERRIDE 触发**\n\n"
            f"- 操作: `{operation}`\n"
            f"- 股票: `{code or 'N/A'}`\n"
            f"- 原因: `{safe_reason}`\n"
            f"- 时间(UTC): `{timestamp}`\n"
            f"- 脚本: `{safe_script}`\n"
            f"- EXECUTION_MODE: `{settings.EXECUTION_MODE}`\n"
            f"- LIVE_TRADING_DISABLED: `{settings.LIVE_TRADING_DISABLED}`\n"
        )
        send_alert(
            level="P0",
            title=title,
            content=content,
            webhook_url=settings.DINGTALK_WEBHOOK_URL,
            secret=settings.DINGTALK_SECRET,
        )
    except (OSError, RuntimeError, ValueError, TimeoutError):
        # silent_ok: 钉钉发送失败不阻断 OVERRIDE bypass.
        # reviewer P2 采纳: narrow exception types (网络/格式/超时) 而非裸 Exception,
        # 让 AttributeError 等真 config bug 浮出. 防 DingTalk 不可达时连紧急清仓也卡死.
        # audit log 已写, DingTalk fail 是次要 channel. 沿用铁律 33-d silent_ok.
        logger.exception(
            "[live-trading-guard] DingTalk P0 推送失败 (不阻断 bypass, audit 已写)"
        )
