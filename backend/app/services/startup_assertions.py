"""Startup assertions — Risk Framework P0 批 1 Fix 2 (2026-04-29).

防 ADR-008 命名空间漂移再发: 启动时若 .env EXECUTION_MODE 与 DB position_snapshot
最近 7 天命名空间不一致, 直接 RAISE refuse to start.

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

关联铁律: 33 fail-loud / 34 SSOT / 36 precondition / 41 timezone (无 mode 字段不涉时区)
关联文档: docs/audit/write_path_namespace_audit_2026_04_29.md
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class NamespaceMismatchError(RuntimeError):
    """启动断言: .env EXECUTION_MODE 与 DB position_snapshot 命名空间漂移.

    fail-loud 拒绝启动 (铁律 33). 修法:
      - 选项 A: 修改 .env EXECUTION_MODE 对齐 DB 实际数据
      - 选项 B: 迁移 DB 数据到目标命名空间 (UPDATE position_snapshot SET execution_mode=...)
      - 选项 C: 批 2 修写路径漂移源头 (pt_qmt_state hardcoded 'live')
    """


def fetch_recent_position_modes(conn: Any) -> dict[str, int]:
    """从 position_snapshot 最近 7 天读 execution_mode 分布.

    Args:
        conn: psycopg2 connection (调用方管理生命周期).

    Returns:
        {execution_mode: count}, e.g. {"live": 295, "paper": 50} or {} 空.
    """
    with conn.cursor() as cur:
        cur.execute(
            """SELECT execution_mode, COUNT(*) FROM position_snapshot
               WHERE trade_date >= CURRENT_DATE - INTERVAL '7 days'
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
            "[startup-assert] position_snapshot last 7d empty (env_mode=%s). "
            "Skip mode consistency assertion (fresh deploy / PT paused).",
            env_mode,
        )
        return

    if env_mode in db_modes:
        logger.info(
            "[startup-assert] EXECUTION_MODE=%s aligns with DB position_snapshot "
            "last 7d modes=%s ✓",
            env_mode, db_modes,
        )
        return

    # 漂移: fail-loud refuse to start
    raise NamespaceMismatchError(
        f"EXECUTION_MODE drift detected: .env={env_mode} but DB position_snapshot "
        f"recent 7d has {db_modes} (no rows for {env_mode!r}). "
        f"Refusing to start. Fix options: "
        f"(A) Edit backend/.env to set EXECUTION_MODE={list(db_modes.keys())[0]!r}; "
        f"(B) Migrate DB data: UPDATE position_snapshot SET execution_mode={env_mode!r} "
        f"WHERE strategy_id=...; "
        f"(C) Wait for batch 2 fix (pt_qmt_state.save_qmt_state hardcoded 'live'). "
        f"详见 docs/audit/write_path_namespace_audit_2026_04_29.md (命名空间漂移审计)."
    )


def run_startup_assertions(conn_factory) -> None:
    """生产入口: lifespan startup hook 调用.

    Args:
        conn_factory: callable () → psycopg2 conn (调用方管理 close).

    Raises:
        NamespaceMismatchError: 命名空间漂移, 启动失败.
    """
    from app.config import settings

    env_mode = settings.EXECUTION_MODE
    conn = conn_factory()
    try:
        db_modes = fetch_recent_position_modes(conn)
    finally:
        conn.close()
    assert_execution_mode_consistency(env_mode, db_modes)
