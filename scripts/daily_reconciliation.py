#!/usr/bin/env python3
"""收盘对账 — QMT实际持仓 vs DB记录对比。

每个交易日15:40运行，比较QMT模拟盘持仓与position_snapshot。
差异超过阈值时发送钉钉告警。同时计算fill_rate毕业指标。

用法:
    python scripts/daily_reconciliation.py
    python scripts/daily_reconciliation.py --date 2026-04-02
"""

import functools
import json
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2.extras

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# Canonical sys.path order: PROJECT_ROOT first, then BACKEND_DIR (LL-175 lesson 2).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

import structlog

# Platform SDK 顶层 import (batch 3.x pattern, 防 import-in-try NameError).
from qm_platform.observability import AlertDispatchError  # noqa: E402

# 铁律 35: DB 连接走 app.services.db canonical get_sync_conn (从 settings.DATABASE_URL
# 派生, 0 hardcoded 密码 + 连接泄漏跟踪). re-export 保持本模块 get_sync_conn 名称稳定
# (test_recon_health_observability.py 的 patch 目标不变).
from app.config import settings
from app.services.db import get_sync_conn

logger = structlog.get_logger("daily_reconciliation")

# 告警阈值
STOCK_DIFF_THRESHOLD = 0.01  # 单股差异>1% → P1
TOTAL_MV_DIFF_THRESHOLD = 0.05  # 总市值差异>5% → P0


def is_trading_day(conn, d: date) -> bool:
    """检查是否交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT is_trading_day FROM trading_calendar
           WHERE market = 'astock' AND trade_date = %s""",
        (d,),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def query_qmt_positions() -> dict[str, int] | None:
    """通过QMT查询当前持仓。返回 {code: shares} 或 None。"""
    try:
        qmt_path = settings.QMT_PATH
        account_id = settings.QMT_ACCOUNT_ID
        if not qmt_path or not account_id:
            logger.error("QMT_PATH或QMT_ACCOUNT_ID未配置")
            return None

        # xtquant双层嵌套路径修复（CLAUDE.md规则）
        _xt = (
            Path(__file__).resolve().parent.parent
            / ".venv"
            / "Lib"
            / "site-packages"
            / "Lib"
            / "site-packages"
        )
        if _xt.exists() and str(_xt) not in sys.path:
            sys.path.append(str(_xt))

        # Plan v8 Wave 3 security fix H-2 (5-20): removed silent SSOT override,
        # fail-loud per 铁律 34
        # Plan v8 critic review fix (5-20): graceful paper-mode exit (exit 0)
        # to avoid polluting schtask LastResult during Phase B-1 paper-mode dry-run.
        # Pure FATAL retained only on EXECUTION_MODE undefined (bad config).
        # PR #384 refinement: normalize case + strip whitespace ('Paper'/'paper ').
        # iter 165 MVP 4.6 Chunk 1 (2026-05-26): SSOT via settings.EXECUTION_MODE
        # (pydantic-settings auto-loads backend/.env regardless of process env). Pre-fix:
        # os.environ.get returned "" when schtask launched python.exe without sourcing
        # .env → fell through paper guard → FATAL exit code 1 (observed 2026-05-26 15:40
        # schtask Last Result). Post-fix: settings reads .env canonically, schtask exit 0.
        expected_mode = (settings.EXECUTION_MODE or "").strip().lower()
        if expected_mode == "paper":
            logger.info(
                "[daily_reconciliation] EXECUTION_MODE=paper detected — graceful skip "
                "(Phase B-1 paper-mode dry-run, requires live for QMT reconciliation). "
                "Exit 0 to keep schtask LastResult clean."
            )
            sys.exit(0)
        if expected_mode != "live":
            sys.exit(
                f"[FATAL] daily_reconciliation.py requires EXECUTION_MODE=live in .env, "
                f"got {expected_mode!r}. Refusing to silently override SSOT (铁律 34). "
                "Set in .env explicitly OR run via cutover gate."
            )
        from engines.broker_qmt import MiniQMTBroker

        broker = MiniQMTBroker(qmt_path, account_id)
        broker.connect()
        positions = broker.get_positions()  # {code: shares}
        broker.disconnect()
        return positions

    except Exception as e:
        logger.error(f"QMT查询失败: {e}")
        return None


def query_db_positions(conn, d: date) -> dict[str, int]:
    """从DB position_snapshot查询live模式持仓。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT code, quantity FROM position_snapshot
           WHERE trade_date = %s AND strategy_id = %s
             AND execution_mode = 'live'""",
        (d, settings.PAPER_STRATEGY_ID),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def _strip_suffix(code: str) -> str:
    """统一后DB和QMT均为带后缀格式，直接返回。"""
    return code


def write_live_snapshot(conn, d: date, qmt_positions: dict[str, int]) -> int:
    """将QMT实际持仓写入position_snapshot (execution_mode='live')。

    在对账时调用，确保DB有live模式的持仓记录。
    价格数据从klines_daily读取，QMT资产查询获取总资产用于weight计算。

    Args:
        conn: DB 连接 (app.services.db.get_sync_conn 提供)。
        d: 日期。
        qmt_positions: {code_with_suffix: shares} QMT持仓（可能含.SH/.SZ后缀）。

    Returns:
        写入行数。
    """
    if not qmt_positions:
        return 0

    # 统一转为6位代码
    qmt_positions = {_strip_suffix(k): v for k, v in qmt_positions.items()}

    cur = conn.cursor()
    strategy_id = settings.PAPER_STRATEGY_ID

    # 清除旧的live snapshot（同一天可能重跑）
    cur.execute(
        """DELETE FROM position_snapshot
           WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'live'""",
        (d, strategy_id),
    )

    # 获取收盘价（用于市值计算）
    codes = list(qmt_positions.keys())
    placeholders = ",".join(["%s"] * len(codes))
    cur.execute(
        f"""SELECT code, close FROM klines_daily
            WHERE trade_date = (SELECT MAX(trade_date) FROM klines_daily WHERE trade_date <= %s)
              AND code IN ({placeholders})""",
        [d, *codes],
    )
    prices = {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}

    # 获取QMT总资产（用于weight计算）
    total_mv = sum(qmt_positions.get(c, 0) * prices.get(c, 0) for c in codes)

    # 获取成本（从trade_log live买入记录计算加权均价）
    cur.execute(
        f"""SELECT code, SUM(fill_price * quantity) / NULLIF(SUM(quantity), 0) as avg_cost
            FROM trade_log
            WHERE strategy_id = %s AND execution_mode = 'live'
              AND direction = 'buy' AND code IN ({placeholders})
            GROUP BY code""",
        [strategy_id, *codes],
    )
    avg_costs = {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}

    # 写入
    written = 0
    for code, shares in qmt_positions.items():
        if shares <= 0:
            continue
        price = prices.get(code, 0)
        mv = shares * price
        weight = mv / total_mv if total_mv > 0 else 0
        avg_cost = avg_costs.get(code)
        unrealized_pnl = (mv - avg_cost * shares) if avg_cost else None

        cur.execute(
            """INSERT INTO position_snapshot
               (code, trade_date, strategy_id, quantity, market_value,
                weight, avg_cost, unrealized_pnl, execution_mode)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'live')""",
            (code, d, strategy_id, shares, mv, weight, avg_cost, unrealized_pnl),
        )
        written += 1

    conn.commit()
    logger.info(f"[Reconciliation] live持仓快照已写入: {written}只, total_mv={total_mv:.0f}")
    return total_mv


def write_live_performance(conn, d: date, nav_total: float, cash: float) -> None:
    """将QMT当日净值写入performance_series (execution_mode='live')。

    Args:
        conn: DB 连接 (app.services.db.get_sync_conn 提供)。
        d: 日期。
        nav_total: 当日总资产（QMT total_asset，已含持仓+现金+冻结）。
        cash: 当日可用现金（用于cash_ratio计算）。
    """
    cur = conn.cursor()
    strategy_id = settings.PAPER_STRATEGY_ID
    nav = nav_total
    if nav <= 0:
        logger.warning(f"[Reconciliation] NAV={nav}无效，跳过performance_series写入")
        return

    # 清除旧记录（同一天可能重跑）
    cur.execute(
        """DELETE FROM performance_series
           WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'live'""",
        (d, strategy_id),
    )

    # 读取前一日NAV
    cur.execute(
        """SELECT nav FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'live'
             AND trade_date < %s
           ORDER BY trade_date DESC LIMIT 1""",
        (strategy_id, d),
    )
    prev_row = cur.fetchone()
    initial_capital = settings.PAPER_INITIAL_CAPITAL
    prev_nav = float(prev_row[0]) if prev_row else initial_capital

    daily_return = (nav / prev_nav - 1) if prev_nav > 0 else 0.0
    cumulative_return = (nav / initial_capital - 1) if initial_capital > 0 else 0.0

    # 计算最大回撤（从所有live记录中找历史最高NAV）
    cur.execute(
        """SELECT MAX(nav) FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'live'""",
        (strategy_id,),
    )
    peak_row = cur.fetchone()
    peak_nav = float(peak_row[0]) if peak_row and peak_row[0] else initial_capital
    peak_nav = max(peak_nav, nav)  # 包含当天
    drawdown = (nav / peak_nav - 1) if peak_nav > 0 else 0.0

    cash_ratio = cash / nav if nav > 0 else 0.0
    position_count = 0
    cur.execute(
        """SELECT COUNT(*) FROM position_snapshot
           WHERE trade_date = %s AND strategy_id = %s
             AND execution_mode = 'live' AND quantity > 0""",
        (d, strategy_id),
    )
    pc_row = cur.fetchone()
    if pc_row:
        position_count = pc_row[0]

    cur.execute(
        """INSERT INTO performance_series
           (trade_date, strategy_id, nav, daily_return, cumulative_return,
            drawdown, cash_ratio, position_count, execution_mode)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'live')""",
        (
            d,
            strategy_id,
            nav,
            daily_return,
            cumulative_return,
            drawdown,
            cash_ratio,
            position_count,
        ),
    )
    conn.commit()
    logger.info(
        f"[Reconciliation] live performance已写入: nav={nav:.0f} "
        f"ret={daily_return:.4f} cum={cumulative_return:.4f} dd={drawdown:.4f}"
    )


def calc_fill_rate(conn, d: date) -> dict:
    """计算当日fill_rate = SUM(quantity) / SUM(order_qty)。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT
               COUNT(*) as total_orders,
               SUM(quantity) as total_filled,
               SUM(order_qty) as total_ordered,
               COUNT(*) FILTER (WHERE order_qty IS NOT NULL AND quantity < order_qty) as partial_fills,
               COUNT(*) FILTER (WHERE reject_reason IS NOT NULL) as rejects
           FROM trade_log
           WHERE trade_date = %s AND strategy_id = %s
             AND execution_mode = 'live'""",
        (d, settings.PAPER_STRATEGY_ID),
    )
    row = cur.fetchone()
    if not row or row[0] == 0:
        return {"total_orders": 0, "fill_rate": None, "partial_fills": 0, "rejects": 0}

    total_filled = row[1] or 0
    total_ordered = row[2] or total_filled  # order_qty未填时用quantity
    fill_rate = total_filled / total_ordered if total_ordered > 0 else 1.0

    return {
        "total_orders": row[0],
        "total_filled": total_filled,
        "total_ordered": total_ordered,
        "fill_rate": round(fill_rate, 4),
        "partial_fills": row[3] or 0,
        "rejects": row[4] or 0,
    }


@functools.lru_cache(maxsize=1)
def _get_rules_engine():
    """Cached AlertRulesEngine load (batch 3.x pattern)."""
    from qm_platform.observability import AlertRulesEngine

    project_root = Path(__file__).resolve().parent.parent
    try:
        return AlertRulesEngine.from_yaml(project_root / "configs" / "alert_rules.yaml")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Observability] AlertRulesEngine load failed: %s, fallback", e)
        return None


def _send_alert_via_platform_sdk(level: str, title: str, content: str) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.5)."""
    from datetime import UTC, datetime

    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    # P2.1 reviewer 采纳: 与 factor_health_daily 一致防 unknown level (e.g. 'WARN')
    # 触发 ValueError → schtask FATAL. 显式 fallback 'p1' 安全.
    severity_value = level.lower() if level.lower() in {"p0", "p1", "p2", "info"} else "p1"
    severity = Severity(severity_value)
    today_str = str(date.today())

    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="daily_reconciliation",
        details={"trade_date": today_str, "content": content},
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    engine = _get_rules_engine()
    rule = engine.match(alert) if engine else None
    if rule:
        dedup_key = rule.format_dedup_key(alert)
        suppress_minutes = rule.suppress_minutes
    else:
        dedup_key = f"daily_reconciliation:summary:{today_str}"
        suppress_minutes = None

    router = get_alert_router()
    try:
        result = router.fire(
            alert,
            dedup_key=dedup_key,
            suppress_minutes=suppress_minutes,
        )
        logger.info(
            "[Observability] AlertRouter.fire result=%s key=%s severity=%s",
            result,
            dedup_key,
            severity_value,
        )
    except AlertDispatchError as e:
        logger.error("[Observability] AlertRouter sink_failed: %s", e)
        raise


def _send_alert_via_legacy_dingtalk(level: str, title: str, content: str) -> None:
    """旧 path: httpx.post 直调 (fallback, settings flag=False 时走)."""
    import httpx

    webhook = settings.DINGTALK_WEBHOOK_URL
    if not webhook:
        logger.warning("DINGTALK_WEBHOOK_URL未配置，跳过告警")
        return
    try:
        text = f"[{level}] {title}\n{content}"
        httpx.post(webhook, json={"msgtype": "text", "text": {"content": text}}, timeout=10)
        logger.info(f"[DingTalk legacy] {level} 告警已发送")
    except Exception as e:
        logger.error(f"告警发送失败 (legacy): {e}")


def send_alert(conn, level: str, title: str, content: str) -> None:
    """发送钉钉告警 (MVP 4.1 batch 3.5 dispatch).

    默认走 PlatformAlertRouter, 旧 httpx 直调路径保留作 fallback.
    AlertDispatchError 必传播 (caller catch). conn 参数保留向后兼容 (旧 path 未用,
    但调用方签名不变).
    """
    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        _send_alert_via_platform_sdk(level, title, content)
    else:
        _send_alert_via_legacy_dingtalk(level, title, content)


def _persist_mismatch_audit(
    *,
    conn,
    recon_date: date,
    severity: str,
    significant_mismatches: list[dict],
    total_diff_pct: float,
    fill_stats: dict,
    alert_outcome: str,
    alert_error: str | None = None,
) -> str | None:
    """Insert risk_event_log audit row when QMT vs DB mismatch detected.

    iter 166 MVP 4.6 Chunk 2 — Phase J §1.3 audit trail wire. One row per
    reconciliation call WITH mismatches (no insert when fully matched).

    Sibling canonical: backend/app/services/risk/execution_plan_persistence.py:102-127
    (MVP 4.5 Chunk 5, 12-column INSERT shape sustained).

    Args:
        conn: psycopg2 connection (caller owns commit/rollback per 铁律 32)
        recon_date: reconciliation trade date
        severity: 'p0' (total_mv breach > 5%) or 'p1' (significant single-stock > 1%)
        significant_mismatches: filtered list (diff_pct > STOCK_DIFF_THRESHOLD)
        total_diff_pct: total股数 diff ratio (0.0-1.0)
        fill_stats: dict from calc_fill_rate (total_orders / fill_rate / etc)
        alert_outcome: 'ALERT_FIRED' (DingTalk sent) or 'AUDIT_ONLY' (dispatch error)
        alert_error: str when alert_outcome='AUDIT_ONLY', else None

    Returns:
        event_id (UUID str) on success, None when RETURNING row missing.

    Raises:
        psycopg2.Error: caller decides rollback/retry (helper does not commit).
    """
    strategy_id = settings.PAPER_STRATEGY_ID

    # Representative code = largest-diff mismatch (indexed lookup convenience).
    rep = max(significant_mismatches, key=lambda m: m["diff_pct"], default=None)
    code = rep["code"] if rep else ""
    diff_shares = (rep["qmt"] - rep["db"]) if rep else 0

    context_snapshot = {
        "trade_date": recon_date.isoformat(),
        "mismatches": significant_mismatches[:10],  # cap防 JSON 巨大
        "total_diff_pct": round(total_diff_pct, 4),
        "fill_stats": fill_stats,
        "alert_error": alert_error,
    }
    action_result = {
        "alert_outcome": alert_outcome,
        "mismatch_count": len(significant_mismatches),
    }
    reason = (
        f"QMT vs DB mismatch (severity={severity.upper()}): "
        f"{len(significant_mismatches)} significant + total_diff={total_diff_pct:.1%}"
    )

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO risk_event_log (
            strategy_id, execution_mode, rule_id, severity, code, shares,
            reason, context_snapshot, action_taken, action_result, cadence,
            priority
        ) VALUES (
            CAST(%s AS uuid), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            strategy_id,
            settings.EXECUTION_MODE,
            "daily_reconciliation"[:50],
            severity[:10],
            (code or "")[:12],
            int(diff_shares),
            reason[:500],
            psycopg2.extras.Json(context_snapshot),
            alert_outcome[:50],
            psycopg2.extras.Json(action_result),
            "daily"[
                :10
            ],  # canonical per migrations/2026_05_11_risk_event_log_realtime.sql:6 (tick/5min/15min/daily)
            severity.upper()[:4],
        ),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


def run_reconciliation(recon_date: date) -> None:
    """执行一次对账。"""
    conn = get_sync_conn()

    try:
        if not is_trading_day(conn, recon_date):
            logger.info(f"{recon_date} 非交易日，跳过对账")
            return

        logger.info(f"[Reconciliation] 开始对账 {recon_date}")

        # 1. QMT持仓（统一转6位代码）
        qmt_pos_raw = query_qmt_positions()
        if qmt_pos_raw is None:
            # batch 3.5 (P1.1 模式): AlertDispatchError 单 catch
            try:
                send_alert(conn, "P0", f"对账失败 {recon_date}", "无法连接QMT获取持仓")
            except AlertDispatchError as e:
                logger.error(
                    "[Observability] AlertDispatchError — 告警未送达, 主流程退出仍 reflect QMT 失败: %s",
                    e,
                )
            return
        qmt_pos = {_strip_suffix(k): v for k, v in qmt_pos_raw.items()}

        # 1.5. 将QMT持仓写入position_snapshot (execution_mode='live')
        snapshot_mv = write_live_snapshot(conn, recon_date, qmt_pos)

        # 1.6. 获取QMT资产并写入performance_series (execution_mode='live')
        # 以QMT total_asset为准（包含冻结/结算差额等）
        qmt_total_asset = 0.0
        qmt_cash = 0.0
        try:
            _xt = (
                Path(__file__).resolve().parent.parent
                / ".venv"
                / "Lib"
                / "site-packages"
                / "Lib"
                / "site-packages"
            )
            if _xt.exists() and str(_xt) not in sys.path:
                sys.path.append(str(_xt))
            from engines.broker_qmt import MiniQMTBroker

            broker = MiniQMTBroker(settings.QMT_PATH, settings.QMT_ACCOUNT_ID)
            broker.connect()
            asset = broker.query_asset()
            qmt_total_asset = float(asset.get("total_asset", 0))
            qmt_cash = float(asset.get("cash", 0))
            broker.disconnect()
            logger.info(
                f"[Reconciliation] QMT资产: total={qmt_total_asset:.0f}, cash={qmt_cash:.0f}, mv={float(asset.get('market_value', 0)):.0f}"
            )
        except Exception as e:
            logger.warning(f"QMT资产查询失败，使用持仓市值+估算现金: {e}")
            qmt_total_asset = 0  # fallback below

        # 如果QMT查询成功，用total_asset; 否则fallback到 snapshot_mv + 估算现金
        if qmt_total_asset > 0:
            write_live_performance(conn, recon_date, qmt_total_asset, qmt_cash)
        else:
            cur = conn.cursor()
            cur.execute(
                """SELECT COALESCE(SUM(fill_price * quantity), 0) FROM trade_log
                   WHERE strategy_id = %s AND execution_mode = 'live' AND direction = 'buy'""",
                (settings.PAPER_STRATEGY_ID,),
            )
            total_bought = float(cur.fetchone()[0])
            est_cash = max(0, settings.PAPER_INITIAL_CAPITAL - total_bought)
            write_live_performance(conn, recon_date, snapshot_mv + est_cash, est_cash)

        # 2. DB持仓 (live模式) — 现在有数据了
        db_pos = query_db_positions(conn, recon_date)

        # 3. 逐股对比
        all_codes = set(qmt_pos.keys()) | set(db_pos.keys())
        mismatches = []
        for code in sorted(all_codes):
            qmt_shares = qmt_pos.get(code, 0)
            db_shares = db_pos.get(code, 0)
            if qmt_shares != db_shares:
                diff_pct = abs(qmt_shares - db_shares) / max(qmt_shares, db_shares, 1)
                mismatches.append(
                    {
                        "code": code,
                        "qmt": qmt_shares,
                        "db": db_shares,
                        "diff_pct": round(diff_pct, 4),
                    }
                )

        # 4. 总市值对比（简化：用股数差异代替）
        qmt_total = sum(qmt_pos.values())
        db_total = sum(db_pos.values())
        total_diff = abs(qmt_total - db_total) / max(qmt_total, 1) if qmt_total > 0 else 0

        # 5. fill_rate计算
        fill_stats = calc_fill_rate(conn, recon_date)

        # 6. 日志
        logger.info(
            f"[Reconciliation] QMT={len(qmt_pos)}只/{qmt_total}股, "
            f"DB={len(db_pos)}只/{db_total}股, "
            f"差异={len(mismatches)}只, fill_rate={fill_stats.get('fill_rate')}"
        )

        # 7. 告警 (batch 3.5 P1.1 模式: AlertDispatchError 单 catch, 不阻断对账主流程)
        significant = [m for m in mismatches if m["diff_pct"] > STOCK_DIFF_THRESHOLD]
        # iter 166 MVP 4.6 Chunk 2: track audit metadata across try/except/else
        audit_severity: str | None = None
        audit_outcome = "ALERT_FIRED"
        audit_error: str | None = None
        try:
            if total_diff > TOTAL_MV_DIFF_THRESHOLD:
                audit_severity = "p0"
                send_alert(
                    conn,
                    "P0",
                    f"对账严重差异 {recon_date}",
                    f"QMT={qmt_total}股 vs DB={db_total}股, 差异={total_diff:.1%}\n"
                    f"差异股票: {json.dumps(significant[:5], ensure_ascii=False)}",
                )
            elif significant:
                audit_severity = "p1"
                send_alert(
                    conn,
                    "P1",
                    f"对账差异 {recon_date}",
                    f"{len(significant)}只股票持仓不一致\n"
                    f"{json.dumps(significant[:5], ensure_ascii=False)}",
                )
        except AlertDispatchError as e:
            audit_outcome = "AUDIT_ONLY"
            audit_error = str(e)[:200]
            logger.error("[Observability] AlertDispatchError — 对账告警未送达: %s", e)
        else:
            if audit_severity is None:
                logger.info("[Reconciliation] 对账一致 ✓")

        # 7b. iter 166 MVP 4.6 Chunk 2: risk_event_log audit row (Phase J §1.3 wire).
        # One row per call WITH mismatches; matched runs have no audit row.
        # Failure of this INSERT does not abort scheduler_task_log bookkeeping —
        # alert was already dispatched (if ALERT_FIRED), audit is supplementary.
        if audit_severity is not None:
            try:
                event_id = _persist_mismatch_audit(
                    conn=conn,
                    recon_date=recon_date,
                    severity=audit_severity,
                    significant_mismatches=significant,
                    total_diff_pct=total_diff,
                    fill_stats=fill_stats,
                    alert_outcome=audit_outcome,
                    alert_error=audit_error,
                )
                logger.info(
                    "[Reconciliation] risk_event_log audit inserted: event_id=%s severity=%s outcome=%s",
                    event_id,
                    audit_severity,
                    audit_outcome,
                )
            except Exception as audit_err:  # noqa: BLE001
                # silent_ok (铁律 33): audit INSERT failure does NOT block
                # scheduler_task_log main bookkeeping. Mismatch was already
                # alerted via DingTalk (if ALERT_FIRED). Audit row is
                # supplementary; logged for ops follow-up.
                logger.error(
                    "[Reconciliation] risk_event_log INSERT failed (audit supplementary, main flow continues): %s",
                    audit_err,
                )

        # 8. 写入scheduler_task_log
        cur = conn.cursor()
        result = {
            "qmt_stocks": len(qmt_pos),
            "db_stocks": len(db_pos),
            "mismatches": len(mismatches),
            "significant_mismatches": len(significant),
            "fill_rate": fill_stats.get("fill_rate"),
            "partial_fills": fill_stats.get("partial_fills", 0),
            "rejects": fill_stats.get("rejects", 0),
        }
        cur.execute(
            """INSERT INTO scheduler_task_log
               (task_name, market, schedule_time, start_time, status,
                error_message, result_json)
               VALUES ('reconciliation', 'astock', NOW(), NOW(), 'success', NULL, %s)""",
            (json.dumps(result),),
        )
        conn.commit()

    except Exception as e:
        logger.error(f"[Reconciliation] 异常: {e}")
        import traceback

        traceback.print_exc()
        # 铁律 43 fail-loud: 写 failed scheduler_task_log row (供 schtask 监控
        # 可见) 并 re-raise —— 反 swallow → exit 0 把对账失败伪装成成功
        # (旧行为: except 吞异常, 脚本仍 exit 0, schtask LastResult 误报 success).
        # paper-mode 优雅退出走 SystemExit (BaseException, 不被本 except 捕获),
        # 因此 Phase B-1 paper-mode exit 0 路径不受影响.
        try:
            # Code-review M1 (PR #392): 若原异常来自失败的 SQL, conn 处于
            # aborted-transaction 状态, 直接 execute 抛 InFailedSqlTransaction →
            # failed-row 静默丢失. 先 rollback 清状态再写 failed row.
            conn.rollback()
            fail_cur = conn.cursor()
            fail_cur.execute(
                """INSERT INTO scheduler_task_log
                   (task_name, market, schedule_time, start_time, status,
                    error_message, result_json)
                   VALUES ('reconciliation', 'astock', NOW(), NOW(), 'failed',
                           %s, NULL)""",
                (str(e)[:500],),
            )
            conn.commit()
        except Exception as log_err:  # noqa: BLE001
            # silent_ok: failed-row 写入失败不掩盖原异常 — 下方 raise 仍 fail-loud.
            logger.error(f"[Reconciliation] failed-row 写入失败: {log_err}")
        raise
    finally:
        conn.close()


def main() -> None:
    """CLI入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="收盘对账: QMT vs DB")
    parser.add_argument("--date", type=str, default=None, help="对账日期 YYYY-MM-DD (默认今天)")
    args = parser.parse_args()

    recon_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    run_reconciliation(recon_date)


if __name__ == "__main__":
    main()
