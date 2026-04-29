"""Startup assertions — Risk Framework P0 批 1 Fix 2 (2026-04-29).

防 ADR-008 命名空间漂移再发: 启动时若 .env EXECUTION_MODE 与 DB position_snapshot
最近 30 天命名空间不一致, 直接 RAISE refuse to start.

reviewer P1 采纳 (everything-claude-code/code-reviewer): window 7d → 30d.
4-29 真生产事件 PT 暂停 9 天 (4-20 → 4-29), 7d 窗口正好命中数据空洞 → guard 误
silent skip. 改 30d 覆盖月度调仓周期 + 国庆/春节超长假期.

历史触发场景:
  - 2026-04-20 17:47 Session 20 cutover live (`.env: EXECUTION_MODE=live`)
  - 2026-04-29 10:58 .env 改回 `paper` (用户决策停 PT)
  - 但 PT 写路径 (pt_qmt_state.save_qmt_state 5 处 hardcoded 'live') 继续按 live
    命名空间写持仓 / 净值 / 资金流水
  - 14:30 risk_daily_check 调 build_context('paper') → trade_log WHERE 0 行
    → entry_price=0.0 → PMSRule + SingleStockStopLossRule + HoldingTime + NewPos
    全部 silent skip → 卓然 -29% / 南玻 -10% 7 天 risk_event_log 0 行

本启动断言无法替代写路径漂移修复 (留批 2 修 pt_qmt_state + execution_service),
但能在新一轮漂移发生时 fail-loud 拒绝启动, 让漂移立即可见 + 强制运维决策.

调用入口: backend/app/main.py lifespan startup phase.
非阻塞 case (DB 空 / strategy fresh deploy) 走 logger.warning 不 raise.

紧急 bypass: 设环境变量 `SKIP_NAMESPACE_ASSERT=1` 跳过断言 (reviewer P1 采纳: Servy
重启 loop 应急通道, 仅在写路径漂移修复期或主动维护期使用, 用完必撤).

关联铁律: 33 fail-loud / 34 SSOT / 36 precondition / 41 timezone (无 mode 字段不涉时区)
关联文档: docs/audit/write_path_namespace_audit_2026_04_29.md
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# reviewer P1 采纳 (everything-claude-code/code-reviewer): 应急 bypass 防 Servy
# QuantMind-FastAPI MaxRestartAttempts=5 重启循环. 用法: 终端 `setx SKIP_NAMESPACE_ASSERT 1`
# (Windows User env, schtask/Servy spawn 自动继承), 漂移修完后撤 (`setx SKIP_NAMESPACE_ASSERT ""`).
_BYPASS_ENV_VAR = "SKIP_NAMESPACE_ASSERT"


class NamespaceMismatchError(RuntimeError):
    """启动断言: .env EXECUTION_MODE 与 DB position_snapshot 命名空间漂移.

    fail-loud 拒绝启动 (铁律 33). 修法:
      - 选项 A: 修改 .env EXECUTION_MODE 对齐 DB 实际数据
      - 选项 B: 迁移 DB 数据到目标命名空间 (UPDATE position_snapshot SET execution_mode=...)
      - 选项 C: 批 2 修写路径漂移源头 (pt_qmt_state hardcoded 'live')
    """


def fetch_recent_position_modes(conn: Any) -> dict[str, int]:
    """从 position_snapshot 最近 30 天读 execution_mode 分布.

    reviewer P1 采纳: window 7d → 30d, 防 PT 暂停 8+ 天导致漂移检测失效.
    psycopg2 cursor context manager 在 __exit__ 调 cur.close() 但不 rollback;
    SELECT-only 查询失败时 (e.g. 表不存在 fresh deploy), 调用方 conn.close()
    隐式 rollback 处理 (run_startup_assertions 的 finally block).

    Args:
        conn: psycopg2 connection (调用方管理生命周期).

    Returns:
        {execution_mode: count}, e.g. {"live": 295, "paper": 50} or {} 空.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT execution_mode, COUNT(*) FROM position_snapshot
               WHERE trade_date >= CURRENT_DATE - INTERVAL '30 days'
               GROUP BY 1"""
        )
        rows = cur.fetchall()
    return {mode: count for mode, count in rows}


def assert_execution_mode_consistency(
    env_mode: str,
    db_modes: dict[str, int],
) -> None:
    """启动时核 .env EXECUTION_MODE 与 DB 7 天命名空间分布一致.

    Logic:
      - DB 空 (新 deploy / PT 暂停 7+ 天) → logger.warning + return (不阻断启动)
      - env_mode 在 db_modes keys → 通过 (即便 DB 多模式过渡期, env 在内即合规)
      - env_mode 不在 db_modes keys → raise NamespaceMismatchError (拒绝启动)

    Args:
        env_mode: settings.EXECUTION_MODE ("paper" | "live")
        db_modes: position_snapshot 最近 7 天 execution_mode 分布

    Raises:
        NamespaceMismatchError: env_mode 与 DB 不一致.
    """
    if not db_modes:
        logger.warning(
            "[startup-assert] position_snapshot last 30d empty (env_mode=%s). "
            "Skip mode consistency assertion (fresh deploy / PT paused 30+ days).",
            env_mode,
        )
        return

    if env_mode in db_modes:
        logger.info(
            "[startup-assert] EXECUTION_MODE=%s aligns with DB position_snapshot "
            "last 30d modes=%s ✓",
            env_mode, db_modes,
        )
        return

    # 漂移: fail-loud refuse to start
    # reviewer P2-1 采纳 (oh-my-claudecode): list(...)[0] 非确定性 (multi-mode dict
    # 时 SQL GROUP BY 序不稳定), 改 max(by count) 给操作员明确推荐 (count 多的 mode
    # 是迁移过渡期主流, 优先对齐).
    suggested_env = max(db_modes, key=db_modes.get)
    # reviewer P1 采纳 (everything-claude-code): logger.critical 前置告警, 让 Servy
    # 重启 loop 期间运维能从日志立即看到根因, 不必逐字解 RuntimeError trace.
    logger.critical(
        "[startup-assert] BLOCKING STARTUP — EXECUTION_MODE=%s drift vs DB modes=%s. "
        "Emergency bypass: set %s=1 in env (Windows User env via setx) and restart.",
        env_mode, db_modes, _BYPASS_ENV_VAR,
    )
    raise NamespaceMismatchError(
        f"EXECUTION_MODE drift detected: .env={env_mode} but DB position_snapshot "
        f"recent 30d has {db_modes} (no rows for {env_mode!r}). "
        f"Refusing to start. Fix options: "
        f"(A) Edit backend/.env to set EXECUTION_MODE={suggested_env!r}; "
        f"(B) Migrate DB data: UPDATE position_snapshot SET execution_mode={env_mode!r} "
        f"WHERE strategy_id=...; "
        f"(C) Wait for batch 2 fix (pt_qmt_state.save_qmt_state hardcoded 'live'); "
        f"(D) Emergency bypass: setx {_BYPASS_ENV_VAR} 1 (撤回前必须修源头). "
        f"详见 docs/audit/write_path_namespace_audit_2026_04_29.md (命名空间漂移审计)."
    )


def run_startup_assertions(conn_factory) -> None:
    """生产入口: lifespan startup hook 调用.

    reviewer P1 采纳 (everything-claude-code): SKIP_NAMESPACE_ASSERT=1 应急
    bypass — 仅在写路径漂移修复期或主动维护期使用 (避免 Servy 重启 loop 拖
    全 35 个 API endpoint). 撤回 bypass 必须先修源头.

    Args:
        conn_factory: callable () → psycopg2 conn (调用方管理 close).

    Raises:
        NamespaceMismatchError: 命名空间漂移, 启动失败.
    """
    if os.environ.get(_BYPASS_ENV_VAR) == "1":
        logger.warning(
            "[startup-assert] BYPASSED via %s=1. Drift detection disabled — "
            "must be reverted after write-path fix (batch 2). 真金风险自担.",
            _BYPASS_ENV_VAR,
        )
        return

    from app.config import settings

    env_mode = settings.EXECUTION_MODE
    conn = conn_factory()
    try:
        db_modes = fetch_recent_position_modes(conn)
    finally:
        conn.close()
    assert_execution_mode_consistency(env_mode, db_modes)
