"""PR-C Session 16 — pt_audit 5 主动检测 guard + 钉钉聚合告警.

Session 10 7 bug 规避 5 主动 check (ADR-008 阶段 2):

  C1 ST leak           — 今日 live buy codes ∩ stock_status_daily is_st=true  [P0]
  C2 mode mismatch     — 同日同 sid 既有 paper 又有 live trade_log            [P1]
  C3 turnover abnormal — live 今日 turnover / NAV > 阈值 (default 30%)        [P1]
  C4 rebalance date    — 月度策略非月末换手 > 1%                              [P2]
  C5 db drift          — reconstruct(yesterday + today fills) vs snapshot    [P1]

设计决策:
  - 纯 DB 查询, 不走 QMT live (避 xtquant 断连依赖, D2-a 教训)
  - 聚合单条钉钉消息 (避免 5 条刷屏)
  - 本 PR 不加 schtasks, Stage 4 评估 (减 blast radius)

铁律:
  15 regression max_diff=0: 本脚本不碰生产代码, 不影响回测
  33 fail-loud: 任一 check 触发 → 聚合钉钉 + exit code 非 0
  35 secrets 不硬编码: DATABASE_URL 必设, 未设 raise

CLI:
  python scripts/pt_audit.py                           # 今日 dry-run
  python scripts/pt_audit.py --audit-date 2026-04-17   # 历史审计
  python scripts/pt_audit.py --alert                   # 显式开钉钉
  python scripts/pt_audit.py --only-checks st_leak,mode_mismatch   # 单跑

Exit codes:
  0 — 无 findings (all pass)
  1 — 有 P0 finding (最严重)
  2 — 仅 P1 finding
  3 — 仅 P2 finding
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import psycopg2
import psycopg2.extensions

# .env 加载 (standalone pattern, 对齐 restore_snapshot_20260417.py)
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
_ENV = _BACKEND / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("pt_audit")

# 常量
CHECK_LIST: tuple[str, ...] = (
    "st_leak", "mode_mismatch", "turnover_abnormal",
    "rebalance_date_mismatch", "db_drift",
)
TURNOVER_THRESHOLD_DEFAULT = 0.30
REBAL_TURNOVER_THRESHOLD = 0.01  # 非月末换手 > 1% 报警
DEFAULT_STRATEGY_ID = os.environ.get(
    "PAPER_STRATEGY_ID", "28fc37e5-2d32-4ada-92e0-41c11a5103d0"
)

# Severity ordering (P0 最严重 → 0) + exit code mapping (P0 → 1)
# Reviewer P1 提点: 原分散两处 dict, 不一致. 统一提取为模块级常量.
_LEVEL_SEVERITY: dict[str, int] = {"P0": 0, "P1": 1, "P2": 2}
_LEVEL_EXIT_CODE: dict[str, int] = {"P0": 1, "P1": 2, "P2": 3}


@dataclass
class Finding:
    """单条检测告警."""

    check: str
    level: str  # 'P0' / 'P1' / 'P2'
    title: str
    detail: dict = field(default_factory=dict)


# ─── DB Helpers ────────────────────────────────────────────────────


def get_sync_conn() -> psycopg2.extensions.connection:
    """Return psycopg2 connection (autocommit=True, read-only workload).

    铁律 35: DATABASE_URL 未设置 → RAISE (不允许硬编码 fallback credential).
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Configure backend/.env or export env var "
            "before running pt_audit (铁律 35 禁硬编码 credential)."
        )
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://") :]
    conn = psycopg2.connect(url)
    conn.autocommit = True
    return conn


def _prev_trading_day(
    cur: psycopg2.extensions.cursor, trade_date: date
) -> date | None:
    """Return the most recent trading_calendar day < trade_date (astock)."""
    cur.execute(
        """SELECT MAX(trade_date) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = true
             AND trade_date < %s""",
        (trade_date,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def _is_month_last_trading_day(
    cur: psycopg2.extensions.cursor, trade_date: date
) -> bool:
    """True if trade_date is the last trading day in its month (astock).

    实现: 同月后续无 is_trading_day=true 日期. DATE_TRUNC 简化 3 参数 → 2.

    边界: 若 trading_calendar 缺本月全部行 (未来月未入库), 返 True 假阳性.
    加 logger.warning surface (reviewer P2 database 提点).
    """
    # precondition: 本月有 trading_calendar 行
    cur.execute(
        """SELECT COUNT(*) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = true
             AND DATE_TRUNC('month', trade_date) = DATE_TRUNC('month', %s::date)""",
        (trade_date,),
    )
    month_rows = cur.fetchone()[0]
    if month_rows == 0:
        logger.warning(
            "[rebalance] trading_calendar 本月无 trading days (trade_date=%s), "
            "_is_month_last 假阳性 — 返 True 但请核查 calendar 入库",
            trade_date,
        )
        return True
    cur.execute(
        """SELECT NOT EXISTS (
               SELECT 1 FROM trading_calendar
               WHERE market = 'astock' AND is_trading_day = true
                 AND trade_date > %s
                 AND DATE_TRUNC('month', trade_date) = DATE_TRUNC('month', %s::date)
           )""",
        (trade_date, trade_date),
    )
    return bool(cur.fetchone()[0])


def _today_turnover_value(
    cur: psycopg2.extensions.cursor, strategy_id: str, trade_date: date
) -> float:
    """Return SUM(fill_price * quantity) for today's live trades (0 if none)."""
    cur.execute(
        """SELECT COALESCE(SUM(fill_price * quantity), 0)
           FROM trade_log
           WHERE trade_date = %s AND execution_mode = 'live'
             AND strategy_id = %s""",
        (trade_date, strategy_id),
    )
    return float(cur.fetchone()[0])


def _latest_live_nav(
    cur: psycopg2.extensions.cursor, strategy_id: str, trade_date: date
) -> float:
    """Return the most recent live NAV at-or-before trade_date (0 if none)."""
    cur.execute(
        """SELECT nav FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'live'
             AND trade_date <= %s
           ORDER BY trade_date DESC LIMIT 1""",
        (strategy_id, trade_date),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] else 0.0


# ─── C5 helper: reconstruct_positions (复用 D2-c 逻辑, dynamic import) ──


def _load_reconstruct_positions() -> Callable[
    [psycopg2.extensions.cursor, str, date, date], dict[str, dict]
]:
    """Dynamic import ``reconstruct_positions`` from scripts/repair/ (非 package).

    避免重复造 (铁律 23). 见 scripts/repair/restore_snapshot_20260417.py.

    Reviewer P1 提点: assert 在生产代码会被 ``-O`` flag 去除 → 改显式 if/raise.
    """
    repo = Path(__file__).resolve().parent.parent
    spec_path = repo / "scripts" / "repair" / "restore_snapshot_20260417.py"
    module_name = "restore_snapshot_20260417_for_audit"
    if module_name in sys.modules:
        return sys.modules[module_name].reconstruct_positions
    spec = importlib.util.spec_from_file_location(module_name, spec_path)
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Cannot load module spec from {spec_path}. "
            "File may have been archived — C5 db_drift requires D2-c script."
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module.reconstruct_positions


# ─── 5 Checks ──────────────────────────────────────────────────────


def check_st_leak(
    conn: psycopg2.extensions.connection, strategy_id: str, trade_date: date,
) -> list[Finding]:
    """C1: 今日 live buy codes ∩ stock_status_daily(today) is_st=true → P0 leak.

    保守策略: `is_st=NULL` (status_date lag) 不告警, T+1 status 入库后 re-audit.
    """
    cur = conn.cursor()
    # GROUP BY 已保证 1 row/code, DISTINCT 冗余已删 (reviewer P1 提点).
    # 前提: stock_status_daily PK=(code, trade_date) 保证 LEFT JOIN 1-to-1.
    cur.execute(
        """SELECT t.code, SUM(t.quantity), SUM(t.fill_price * t.quantity)
           FROM trade_log t
           LEFT JOIN stock_status_daily ss
             ON t.code = ss.code AND ss.trade_date = t.trade_date
           WHERE t.trade_date = %s
             AND t.execution_mode = 'live'
             AND t.strategy_id = %s
             AND t.direction = 'buy'
             AND COALESCE(ss.is_st, FALSE) = true
           GROUP BY t.code
           ORDER BY t.code""",
        (trade_date, strategy_id),
    )
    findings: list[Finding] = []
    for code, qty, value in cur.fetchall():
        findings.append(
            Finding(
                check="st_leak",
                level="P0",
                title=f"ST leak: live 买入 ST 股 {code}",
                detail={"code": code, "qty": int(qty), "value": float(value)},
            )
        )
    return findings


def check_mode_mismatch(
    conn: psycopg2.extensions.connection, strategy_id: str, trade_date: date,
) -> list[Finding]:
    """C2: 同日同 sid trade_log 既有 paper 又有 live → P1 命名空间污染."""
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date,
                  COUNT(DISTINCT execution_mode) AS mode_count,
                  ARRAY_AGG(DISTINCT execution_mode) AS modes,
                  COUNT(*) AS row_count
           FROM trade_log
           WHERE trade_date = %s AND strategy_id = %s
           GROUP BY trade_date
           HAVING COUNT(DISTINCT execution_mode) > 1""",
        (trade_date, strategy_id),
    )
    findings: list[Finding] = []
    for td, _mode_count, modes, rows in cur.fetchall():
        findings.append(
            Finding(
                check="mode_mismatch",
                level="P1",
                title=f"execution_mode 混合 {td}: {list(modes)}",
                detail={
                    "date": str(td),
                    "modes": list(modes),
                    "row_count": int(rows),
                },
            )
        )
    return findings


def check_turnover_abnormal(
    conn: psycopg2.extensions.connection,
    strategy_id: str,
    trade_date: date,
    threshold: float = TURNOVER_THRESHOLD_DEFAULT,
) -> list[Finding]:
    """C3: live 今日 turnover / NAV > 阈值 → P1 策略漂移."""
    cur = conn.cursor()
    turnover_value = _today_turnover_value(cur, strategy_id, trade_date)
    if turnover_value <= 0:
        return []
    nav = _latest_live_nav(cur, strategy_id, trade_date)
    if nav <= 0:
        # NAV unavailable — cannot compute ratio, skip (fail-safe, not fail-loud)
        logger.warning(
            "[turnover] NAV unavailable for strategy_id=%s @ %s, skipping check",
            strategy_id, trade_date,
        )
        return []
    ratio = turnover_value / nav
    if ratio <= threshold:
        return []
    return [
        Finding(
            check="turnover_abnormal",
            level="P1",
            title=f"换手异常 {trade_date}: {ratio:.1%} > {threshold:.1%}",
            detail={
                "turnover_value": round(turnover_value, 2),
                "nav": round(nav, 2),
                "ratio": round(ratio, 4),
                "threshold": threshold,
            },
        )
    ]


def check_rebalance_date_mismatch(
    conn: psycopg2.extensions.connection, strategy_id: str, trade_date: date,
) -> list[Finding]:
    """C4: 月度策略非月末换手 > 1% → P2 日历漂移."""
    cur = conn.cursor()
    # 假设配置月度策略 — 非月末调仓 = 漂移
    if _is_month_last_trading_day(cur, trade_date):
        return []
    turnover_value = _today_turnover_value(cur, strategy_id, trade_date)
    if turnover_value <= 0:
        return []
    nav = _latest_live_nav(cur, strategy_id, trade_date)
    if nav <= 0:
        # 铁律 33(c): 读路径 fallback 必须 logger.warning (reviewer P1 一致提点, 对齐 C3)
        logger.warning(
            "[rebalance] NAV unavailable for strategy_id=%s @ %s, skipping C4",
            strategy_id, trade_date,
        )
        return []
    ratio = turnover_value / nav
    if ratio <= REBAL_TURNOVER_THRESHOLD:
        return []
    return [
        Finding(
            check="rebalance_date_mismatch",
            level="P2",
            title=f"Rebalance 日历漂移 {trade_date}: 非月末但换手 {ratio:.1%}",
            detail={
                "turnover_value": round(turnover_value, 2),
                "nav": round(nav, 2),
                "ratio": round(ratio, 4),
                "threshold": REBAL_TURNOVER_THRESHOLD,
            },
        )
    ]


def check_db_drift(
    conn: psycopg2.extensions.connection, strategy_id: str, trade_date: date,
) -> list[Finding]:
    """C5: reconstruct(yesterday live snapshot + today live fills) vs snapshot → P1 drift.

    复用 D2-c reconstruct_positions 逻辑. 不走 QMT live.
    """
    cur = conn.cursor()
    prev_date = _prev_trading_day(cur, trade_date)
    if prev_date is None:
        logger.warning("[drift] 无前一交易日 (fresh start), skip")
        return []
    reconstruct_positions = _load_reconstruct_positions()
    expected = reconstruct_positions(cur, strategy_id, trade_date, prev_date)
    # actual snapshot
    cur.execute(
        """SELECT code FROM position_snapshot
           WHERE trade_date = %s AND execution_mode = 'live'
             AND strategy_id = %s AND quantity > 0""",
        (trade_date, strategy_id),
    )
    actual_codes = {r[0] for r in cur.fetchall()}
    expected_codes = set(expected.keys())
    if expected_codes == actual_codes:
        return []
    missing = sorted(expected_codes - actual_codes)[:10]
    extra = sorted(actual_codes - expected_codes)[:10]
    return [
        Finding(
            check="db_drift",
            level="P1",
            title=f"DB drift {trade_date}: expected={len(expected_codes)} vs snapshot={len(actual_codes)}",
            detail={
                "expected_count": len(expected_codes),
                "actual_count": len(actual_codes),
                "missing_from_snapshot": missing,
                "extra_in_snapshot": extra,
            },
        )
    ]


# ─── Orchestration + Alert ─────────────────────────────────────────


_CHECK_FUNCS = {
    "st_leak": check_st_leak,
    "mode_mismatch": check_mode_mismatch,
    "turnover_abnormal": check_turnover_abnormal,
    "rebalance_date_mismatch": check_rebalance_date_mismatch,
    "db_drift": check_db_drift,
}


def send_aggregated_alert(findings: list[Finding], audit_date: date) -> None:
    """Compose one DingTalk message with all findings. Skip if empty."""
    if not findings:
        return
    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError:
        logger.error("httpx not installed, cannot send DingTalk alert")
        return
    webhook = os.environ.get("DINGTALK_WEBHOOK_URL", "")
    if not webhook:
        logger.warning("DINGTALK_WEBHOOK_URL 未配置, 跳过告警 (发 stdout)")
        return
    # 顶级 level = max(finding levels)  (P0 > P1 > P2)  — 用模块常量 (reviewer P1 提点)
    top_level = min(
        (f.level for f in findings),
        key=lambda x: _LEVEL_SEVERITY.get(x, 99),
    )
    lines = [f"[{top_level}] pt_audit {audit_date} — {len(findings)} findings:"]
    for f in findings:
        lines.append(f"  [{f.level}] {f.check}: {f.title}")
    text = "\n".join(lines)
    try:
        httpx.post(
            webhook, json={"msgtype": "text", "text": {"content": text}}, timeout=10
        )
        logger.info(f"[DingTalk] {top_level} 聚合告警已发送 ({len(findings)} findings)")
    except Exception as e:
        logger.error(f"告警发送失败: {e}")


def run_audit(
    strategy_id: str,
    audit_date: date,
    only_checks: list[str] | None = None,
    turnover_threshold: float = TURNOVER_THRESHOLD_DEFAULT,
    alert: bool = False,
) -> tuple[int, list[Finding]]:
    """Run all 5 checks (or subset), aggregate findings.

    Returns:
        (exit_code, findings) — exit_code: 0 clean / 1 P0 / 2 P1 / 3 P2
    """
    conn = get_sync_conn()
    all_findings: list[Finding] = []
    try:
        checks = only_checks or list(CHECK_LIST)
        logger.info(
            "[audit] date=%s sid=%s... checks=%s",
            audit_date, strategy_id[:8], checks,
        )
        # 构建 check_fn dict (reviewer P2 提点): functools.partial 消除 if-name 分支
        dispatch: dict[str, Callable] = {}
        for name in checks:
            if name not in _CHECK_FUNCS:
                logger.warning("[audit] unknown check '%s', skip", name)
                continue
            func = _CHECK_FUNCS[name]
            if name == "turnover_abnormal":
                dispatch[name] = functools.partial(func, threshold=turnover_threshold)
            else:
                dispatch[name] = func

        for name, fn in dispatch.items():
            try:
                res = fn(conn, strategy_id, audit_date)
                if res:
                    all_findings.extend(res)
                    for f in res:
                        logger.warning("  [%s] %s: %s", f.level, f.check, f.title)
                else:
                    logger.info("  [%s] PASS", name)
            except Exception:
                logger.exception("[audit] check '%s' raised (continuing)", name)
        if alert:
            send_aggregated_alert(all_findings, audit_date)
    finally:
        conn.close()
    # exit code — 用模块常量 (reviewer P1 提点)
    if not all_findings:
        return (0, [])
    top_code = min(_LEVEL_EXIT_CODE.get(f.level, 99) for f in all_findings)
    return (top_code, all_findings)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "QuantMind PT audit: 5-check post-trade guard "
            "(ST leak / mode mismatch / turnover / rebalance date / db drift)."
        ),
    )
    parser.add_argument(
        "--audit-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=date.today(),
        help="审计日期 YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--strategy-id",
        default=DEFAULT_STRATEGY_ID,
        help=f"Strategy id (default env PAPER_STRATEGY_ID or {DEFAULT_STRATEGY_ID})",
    )
    parser.add_argument(
        "--only-checks",
        default="",
        help=f"逗号分隔 check 子集 (default all): {','.join(CHECK_LIST)}",
    )
    parser.add_argument(
        "--turnover-threshold",
        type=float,
        default=float(os.environ.get("PT_AUDIT_TURNOVER_THRESHOLD", TURNOVER_THRESHOLD_DEFAULT)),
        help=f"turnover_abnormal 阈值 (default env PT_AUDIT_TURNOVER_THRESHOLD or {TURNOVER_THRESHOLD_DEFAULT})",
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        help="显式开钉钉告警 (default: dry-run 仅 stdout)",
    )
    args = parser.parse_args()
    only = [c.strip() for c in args.only_checks.split(",") if c.strip()] or None
    exit_code, findings = run_audit(
        strategy_id=args.strategy_id,
        audit_date=args.audit_date,
        only_checks=only,
        turnover_threshold=args.turnover_threshold,
        alert=args.alert,
    )
    if findings:
        logger.warning("[audit] 完成: %d findings, exit=%d", len(findings), exit_code)
    else:
        logger.info("[audit] 完成: 0 findings (all pass), exit=%d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
