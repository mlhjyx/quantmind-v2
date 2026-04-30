"""Application-level custom exceptions.

集中放置 application 层 typed exceptions, 便于 catch / log / monitoring.

铁律 33 (fail-loud): 类型化 exception 让上游能精确判定原因, 区别于裸 RuntimeError.
"""
from __future__ import annotations


class LiveTradingDisabledError(RuntimeError):
    """Live trading is disabled — real broker calls (xtquant.order_stock /
    xtquant.cancel_order_stock) are blocked.

    Raised by ``app.security.live_trading_guard.assert_live_trading_allowed``
    when ``settings.LIVE_TRADING_DISABLED=True`` and OVERRIDE 双因素 不全设.

    Bypass requires both:
        LIVE_TRADING_FORCE_OVERRIDE=1
        LIVE_TRADING_OVERRIDE_REASON='<explicit non-empty reason>'

    历史: T1 sprint 链路停止 PR (2026-04-29) 沉淀, 防真金风险 + 防钉钉刷屏.
    撤销: docs/audit/link_paused_2026_04_29.md.

    Application 层而非 Engine 层: paper_broker 物理隔离 (不 import guard).
    """


class T0_19_AlreadyBackfilledError(RuntimeError):  # noqa: N801
    """T0-19 audit hook 重入检测命中: trade_log 已含 reject_reason 'T0_19_backfill_*'
    或 hook flag 文件已存在.

    防止 emergency_close_all_positions.py 重跑导致 trade_log / risk_event_log /
    performance_series / position_snapshot 重复 INSERT.

    Raised by ``app.services.t0_19_audit._check_idempotency``.

    沿用 LL-066 subset-column UPSERT 例外的反向 — backfill 的 INSERT 不可重入,
    必先 SELECT count 检测 + flag 文件双保险.

    复用规则 (Phase 1 design §2.3):
        (a) trade_log SELECT count WHERE reject_reason LIKE 'T0_19_backfill_%'
            + trade_date=<date> + execution_mode='live' > 0 → 重入
        (b) Hook flag file LOG_DIR/emergency_close_<ts>.DONE.flag exists → 重入
    """


class T0_19_AuditCheckError(RuntimeError):  # noqa: N801
    """T0-19 audit hook DB CHECK constraint 违反.

    Raised by ``app.services.t0_19_audit.write_post_close_audit`` 系列 INSERT.

    沿用 LL-094 复用规则 — risk_event_log CHECK enum =
    ('sell', 'alert_only', 'bypass'), execution_mode CHECK = ('paper', 'live'),
    severity CHECK = ('p0', 'p1', 'p2', 'info'), shares CHECK >= 0.

    任何 CHECK 拒 → wrap psycopg2.errors.CheckViolation → raise this.
    """


class T0_19_LogParseError(RuntimeError):  # noqa: N801
    """T0-19 audit hook 解析 logs/emergency_close_*.log 失败.

    Raised by ``app.services.t0_19_audit._parse_emergency_close_log``.

    场景:
        - log 文件不存在 / size 0
        - 0 fill events 解析出 (regex 不匹配)
        - 解析后总 sell count 与 sells_summary['submitted_count'] 不一致
        - timestamps 格式不可解析

    沿用铁律 27 (不 fabricate): 解析失败必 raise, 不 silently 用 fallback 数据.
    """
