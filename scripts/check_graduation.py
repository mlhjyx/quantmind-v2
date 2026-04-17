#!/usr/bin/env python3
"""Paper Trading 毕业评估CLI — 一键输出9项毕业标准评估。

用法:
    python scripts/check_graduation.py
    python scripts/check_graduation.py --strategy-name v1.1_equal_weight
    python scripts/check_graduation.py --verbose

毕业标准（CLAUDE.md + Sprint 1.10）:
    1. 运行时长 ≥ 60天
    2. Sharpe ≥ 回测Sharpe × 70%（基线1.03, 阈值0.72）
    3. MDD ≤ 回测MDD × 1.5（基线-39.7%, 阈值-59.6%）
    4. 滑点偏差 < 50%
    5. 链路完整性 — 无中断
    6. fill_rate ≥ 95%
    7. avg_slippage ≤ 30bps
    8. tracking_error ≤ 2%
    9. gap_hours 12-20h
"""

import argparse
import math
import sys
from pathlib import Path

# ── 路径设置 ──
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.db import get_sync_conn

# ── 毕业标准常量 ──
BACKTEST_SHARPE = 1.03
BACKTEST_MDD = -39.7  # %
SHARPE_THRESHOLD = BACKTEST_SHARPE * 0.70  # 0.721
MDD_THRESHOLD = BACKTEST_MDD * 1.5  # -59.55%
MIN_DAYS = 60
FILL_RATE_MIN = 95.0  # %
AVG_SLIPPAGE_MAX = 30.0  # bps
TRACKING_ERROR_MAX = 2.0  # %
GAP_HOURS_MIN = 12.0
GAP_HOURS_MAX = 20.0
SLIPPAGE_DEVIATION_MAX = 50.0  # %

# ── ANSI颜色 ──
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _status_str(passed: bool | None) -> str:
    if passed is None:
        return f"{_YELLOW}PENDING{_RESET}"
    return f"{_GREEN}PASS{_RESET}" if passed else f"{_RED}FAIL{_RESET}"


def get_strategy_id(conn, name: str = "v1.1_equal_weight") -> str | None:
    """从strategy表查找策略ID。"""
    cur = conn.cursor()
    cur.execute("SELECT id FROM strategy WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return str(row[0])
    # fallback: 尝试从.env读取
    from app.config import settings
    if settings.PAPER_STRATEGY_ID:
        return settings.PAPER_STRATEGY_ID
    return None


def assess_graduation(conn, strategy_id: str, verbose: bool = False) -> dict:
    """计算9项毕业指标。"""
    cur = conn.cursor()

    # ── 1. 运行时长 ──
    cur.execute(
        """SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'""",
        (strategy_id,),
    )
    row = cur.fetchone()
    start_date, end_date, num_days = row if row else (None, None, 0)
    num_days = num_days or 0

    # ── 2. Sharpe (年化) ──
    cur.execute(
        """SELECT daily_return FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date""",
        (strategy_id,),
    )
    returns = [float(r[0]) for r in cur.fetchall() if r[0] is not None]

    sharpe = None
    if len(returns) >= 5:
        mean_r = sum(returns) / len(returns)
        var_r = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0
        std_r = math.sqrt(var_r) if var_r > 0 else 0
        sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0

    # ── 3. MDD ──
    mdd_pct = None
    if returns:
        cur.execute(
            """SELECT MIN(drawdown) FROM performance_series
               WHERE strategy_id = %s AND execution_mode = 'paper'""",
            (strategy_id,),
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            mdd_pct = float(row[0]) * 100  # decimal → %

    # ── 4. 滑点偏差 ──
    # 模型预估滑点 vs 实际滑点
    cur.execute(
        """SELECT AVG(ABS(slippage_bps)) FROM trade_log
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND slippage_bps IS NOT NULL AND direction IN ('buy', 'sell')""",
        (strategy_id,),
    )
    row = cur.fetchone()
    actual_avg_slippage = float(row[0]) if row and row[0] is not None else None
    # 模型预估: 买10bps, 卖10bps (SimBroker默认)
    model_slippage = 10.0
    slippage_deviation = None
    if actual_avg_slippage is not None and model_slippage > 0:
        slippage_deviation = abs(actual_avg_slippage - model_slippage) / model_slippage * 100

    # ── 5. 链路完整性 ──
    cur.execute(
        """SELECT COUNT(*) FROM scheduler_task_log
           WHERE status = 'failed'
             AND task_name IN ('signal_phase', 'execute_phase', 'factor_calc', 'signal_gen')
             AND created_at >= (SELECT MIN(trade_date) FROM performance_series
                                WHERE strategy_id = %s AND execution_mode = 'paper')""",
        (strategy_id,),
    )
    row = cur.fetchone()
    chain_failures = row[0] if row else 0

    # ── 6. fill_rate ──
    cur.execute(
        """SELECT
               COUNT(*) FILTER (WHERE reject_reason IS NULL) AS filled,
               COUNT(*) AS total
           FROM trade_log
           WHERE strategy_id = %s AND execution_mode = 'paper'""",
        (strategy_id,),
    )
    row = cur.fetchone()
    filled, total_orders = (row[0], row[1]) if row else (0, 0)
    fill_rate = (filled / total_orders * 100) if total_orders > 0 else None

    # ── 7. avg_slippage (已算) ──

    # ── 8. tracking_error ──
    cur.execute(
        """SELECT daily_return, excess_return FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND excess_return IS NOT NULL
           ORDER BY trade_date""",
        (strategy_id,),
    )
    excess_rows = cur.fetchall()
    tracking_error = None
    if len(excess_rows) >= 5:
        excess_returns = [float(r[1]) for r in excess_rows]
        mean_ex = sum(excess_returns) / len(excess_returns)
        var_ex = sum((e - mean_ex) ** 2 for e in excess_returns) / (len(excess_returns) - 1)
        tracking_error = math.sqrt(var_ex) * math.sqrt(252) * 100  # 年化 %

    # ── 9. gap_hours ──
    cur.execute(
        """SELECT task_name, start_time, end_time
           FROM scheduler_task_log
           WHERE task_name IN ('signal_phase', 'execute_phase')
             AND status = 'success'
           ORDER BY start_time DESC
           LIMIT 20""",
        (),
    )
    gap_rows = cur.fetchall()
    avg_gap_hours = None
    if gap_rows:
        # 查找signal→execute对, 计算gap
        signals = [(r[1], r[2]) for r in gap_rows if r[0] == 'signal_phase']
        executes = [(r[1], r[2]) for r in gap_rows if r[0] == 'execute_phase']
        gaps = []
        for _sig_start, sig_end in signals:
            if sig_end is None:
                continue
            for exe_start, _exe_end in executes:
                if exe_start is None:
                    continue
                if exe_start > sig_end:
                    gap_h = (exe_start - sig_end).total_seconds() / 3600
                    if 5 < gap_h < 30:  # 合理范围
                        gaps.append(gap_h)
                    break
        if gaps:
            avg_gap_hours = sum(gaps) / len(gaps)

    # ── 近7天趋势 ──
    recent_sharpe = None
    if len(returns) >= 7:
        recent = returns[-7:]
        mean_r7 = sum(recent) / len(recent)
        var_r7 = sum((r - mean_r7) ** 2 for r in recent) / (len(recent) - 1) if len(recent) > 1 else 0
        std_r7 = math.sqrt(var_r7) if var_r7 > 0 else 0
        recent_sharpe = (mean_r7 / std_r7 * math.sqrt(252)) if std_r7 > 0 else 0

    # ── 汇总 ──
    results = {
        "start_date": start_date,
        "end_date": end_date,
        "num_days": num_days,
        "sharpe": sharpe,
        "mdd_pct": mdd_pct,
        "slippage_deviation": slippage_deviation,
        "chain_failures": chain_failures,
        "fill_rate": fill_rate,
        "avg_slippage": actual_avg_slippage,
        "tracking_error": tracking_error,
        "avg_gap_hours": avg_gap_hours,
        "recent_sharpe": recent_sharpe,
        "total_orders": total_orders,
        "filled_orders": filled,
    }

    # ── 最新NAV ──
    cur.execute(
        """SELECT nav FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date DESC LIMIT 1""",
        (strategy_id,),
    )
    row = cur.fetchone()
    results["latest_nav"] = float(row[0]) if row and row[0] is not None else None

    return results


def print_report(results: dict, strategy_id: str) -> None:
    """格式化输出毕业评估报告。"""
    r = results

    print(f"\n{_BOLD}{'=' * 65}{_RESET}")
    print(f"{_BOLD}{_CYAN}  Paper Trading 毕业评估报告{_RESET}")
    print(f"{'=' * 65}")
    print(f"  策略ID:    {strategy_id}")
    if r["start_date"]:
        print(f"  运行区间:  {r['start_date']} ~ {r['end_date']}  ({r['num_days']}天)")
    if r["latest_nav"] is not None:
        print(f"  最新NAV:   {r['latest_nav']:,.2f}")
    print(f"{'=' * 65}\n")

    # 9项标准
    items = []

    # 1. 运行时长
    days_pass = r["num_days"] >= MIN_DAYS if r["num_days"] else None
    val = f"{r['num_days']} / {MIN_DAYS}天"
    items.append(("运行时长", val, days_pass))

    # 2. Sharpe
    if r["sharpe"] is not None:
        sharpe_pass = r["sharpe"] >= SHARPE_THRESHOLD
        val = f"{r['sharpe']:.3f} / ≥{SHARPE_THRESHOLD:.3f}  (基线{BACKTEST_SHARPE}×70%)"
    else:
        sharpe_pass = None
        val = "数据不足"
    items.append(("Sharpe", val, sharpe_pass))

    # 3. MDD
    if r["mdd_pct"] is not None:
        mdd_pass = r["mdd_pct"] >= MDD_THRESHOLD  # MDD是负数, -20 >= -59.6 是PASS
        val = f"{r['mdd_pct']:.2f}% / ≥{MDD_THRESHOLD:.1f}%  (基线{BACKTEST_MDD}%×1.5)"
    else:
        mdd_pass = None
        val = "数据不足"
    items.append(("最大回撤", val, mdd_pass))

    # 4. 滑点偏差
    if r["slippage_deviation"] is not None:
        slip_dev_pass = r["slippage_deviation"] < SLIPPAGE_DEVIATION_MAX
        val = f"{r['slippage_deviation']:.1f}% / <{SLIPPAGE_DEVIATION_MAX}%"
    else:
        slip_dev_pass = None
        val = "无交易数据"
    items.append(("滑点偏差", val, slip_dev_pass))

    # 5. 链路完整性
    chain_pass = r["chain_failures"] == 0
    val = f"失败{r['chain_failures']}次" if r["chain_failures"] > 0 else "无中断"
    items.append(("链路完整性", val, chain_pass))

    # 6. fill_rate
    if r["fill_rate"] is not None:
        fill_pass = r["fill_rate"] >= FILL_RATE_MIN
        val = f"{r['fill_rate']:.1f}% / ≥{FILL_RATE_MIN}%  ({r['filled_orders']}/{r['total_orders']})"
    else:
        fill_pass = None
        val = "无交易数据"
    items.append(("成交率", val, fill_pass))

    # 7. avg_slippage
    if r["avg_slippage"] is not None:
        slip_pass = r["avg_slippage"] <= AVG_SLIPPAGE_MAX
        val = f"{r['avg_slippage']:.1f}bps / ≤{AVG_SLIPPAGE_MAX}bps"
    else:
        slip_pass = None
        val = "无交易数据"
    items.append(("平均滑点", val, slip_pass))

    # 8. tracking_error
    if r["tracking_error"] is not None:
        te_pass = r["tracking_error"] <= TRACKING_ERROR_MAX
        val = f"{r['tracking_error']:.2f}% / ≤{TRACKING_ERROR_MAX}%"
    else:
        te_pass = None
        val = "数据不足"
    items.append(("跟踪误差", val, te_pass))

    # 9. gap_hours
    if r["avg_gap_hours"] is not None:
        gap_pass = GAP_HOURS_MIN <= r["avg_gap_hours"] <= GAP_HOURS_MAX
        val = f"{r['avg_gap_hours']:.1f}h / {GAP_HOURS_MIN}-{GAP_HOURS_MAX}h"
    else:
        gap_pass = None
        val = "数据不足"
    items.append(("信号-执行间隔", val, gap_pass))

    # 输出表格
    print(f"  {'#':<3} {'指标':<14} {'结果':<45} {'状态'}")
    print(f"  {'─' * 3} {'─' * 14} {'─' * 45} {'─' * 8}")
    for i, (name, val, passed) in enumerate(items, 1):
        print(f"  {i:<3} {name:<14} {val:<45} {_status_str(passed)}")

    # 汇总
    all_results = [p for _, _, p in items]
    passed_count = sum(1 for p in all_results if p is not None and bool(p))
    failed_count = sum(1 for p in all_results if p is not None and not bool(p))
    pending_count = sum(1 for p in all_results if p is None)

    print(f"\n  {'─' * 70}")
    print(f"  {_BOLD}汇总: {_GREEN}{passed_count} PASS{_RESET}  "
          f"{_RED}{failed_count} FAIL{_RESET}  "
          f"{_YELLOW}{pending_count} PENDING{_RESET}")

    if failed_count == 0 and pending_count == 0:
        print(f"\n  {_BOLD}{_GREEN}>>> 全部达标，可以转实盘！ <<<{_RESET}")
    elif failed_count > 0:
        print(f"\n  {_BOLD}{_RED}>>> 未达标，继续Paper Trading{_RESET}")
    else:
        print(f"\n  {_BOLD}{_YELLOW}>>> 部分指标待数据积累{_RESET}")

    # 趋势分析
    if r["recent_sharpe"] is not None:
        trend = "↑" if r["recent_sharpe"] > (r["sharpe"] or 0) else "↓"
        print(f"\n  {_DIM}近7天Sharpe: {r['recent_sharpe']:.3f} {trend}{_RESET}")

    print(f"\n{'=' * 65}\n")


def main():
    parser = argparse.ArgumentParser(description="Paper Trading毕业评估CLI")
    parser.add_argument(
        "--strategy-name", default="v1.1_equal_weight",
        help="策略名称 (default: v1.1_equal_weight)",
    )
    parser.add_argument(
        "--strategy-id", default=None,
        help="直接指定策略UUID (优先于--strategy-name)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    conn = get_sync_conn()
    try:
        strategy_id = args.strategy_id or get_strategy_id(conn, args.strategy_name)

        if not strategy_id:
            print(f"{_RED}错误: 未找到策略 '{args.strategy_name}'{_RESET}")
            print("可用策略:")
            cur = conn.cursor()
            cur.execute("SELECT id, name, status FROM strategy ORDER BY name")
            for row in cur.fetchall():
                print(f"  {row[0]}  {row[1]}  ({row[2]})")
            sys.exit(1)

        if args.verbose:
            print(f"策略ID: {strategy_id}")

        results = assess_graduation(conn, strategy_id, verbose=args.verbose)
        print_report(results, strategy_id)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
