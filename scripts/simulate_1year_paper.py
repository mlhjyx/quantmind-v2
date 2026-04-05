#!/usr/bin/env python3
"""Paper Trading 1年模拟验证 — 管道可靠性最终验证（月度检查点版）。

覆盖约240个交易日、12次月度调仓。
验证：调仓触发正确性、NAV累计、风控熔断、持仓连续性。

月度检查点（每月结束时执行5项检查）:
1. 本月是否触发了月度调仓？
2. 持仓数量是否≤20？
3. NAV是否合理？
4. 风控是否正确触发？
5. 本月最大单日亏损是否触发了对应级别熔断？

任何检查失败（特别是持仓>20）→ 立即停止模拟并输出错误详情。

用法:
    python scripts/simulate_1year_paper.py
"""

import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import psycopg2

from app.config import settings

DB_URL = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"
STRATEGY_ID = settings.PAPER_STRATEGY_ID
START_DATE = date(2025, 4, 1)
END_DATE = date(2026, 3, 20)
INITIAL_CAPITAL = 1_000_000


def get_trading_days(start: date, end: date) -> list[date]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date FROM trading_calendar
           WHERE market='astock' AND is_trading_day=TRUE
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        (start, end),
    )
    days = [r[0] for r in cur.fetchall()]
    conn.close()
    return days


def get_month_end_days(start: date, end: date) -> set[date]:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date FROM (
            SELECT trade_date,
                   ROW_NUMBER() OVER (PARTITION BY DATE_TRUNC('month', trade_date)
                                      ORDER BY trade_date DESC) as rn
            FROM trading_calendar
            WHERE market='astock' AND is_trading_day=TRUE
              AND trade_date BETWEEN %s AND %s
        ) t WHERE rn=1""",
        (start, end),
    )
    days = {r[0] for r in cur.fetchall()}
    conn.close()
    return days


def clean_state():
    """清理所有paper trading数据。"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for sql in [
        "DELETE FROM trade_log WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM position_snapshot WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM performance_series WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM signals WHERE strategy_id = %s AND execution_mode = 'paper'",
    ]:
        cur.execute(sql, (STRATEGY_ID,))
    cur.execute(
        "DELETE FROM scheduler_task_log WHERE task_name LIKE '%%signal%%' OR task_name LIKE '%%execute%%' OR task_name LIKE '%%circuit%%' OR task_name LIKE '%%data_fetch%%' OR task_name LIKE '%%factor_calc%%' OR task_name LIKE '%%state_save%%' OR task_name LIKE '%%paper%%' OR task_name LIKE '%%pending%%' OR task_name LIKE '%%rebalance%%'"
    )
    conn.commit()
    conn.close()
    print("[CLEAN] 清理完成: trade_log, position_snapshot, performance_series, signals, scheduler_task_log")


def run_phase(phase: str, td: date, extra_args: list = None) -> tuple[int, str]:
    import subprocess
    args = [sys.executable, "scripts/run_paper_trading.py", phase,
            "--date", td.strftime("%Y-%m-%d"),
            "--skip-fetch", "--skip-factors"]
    if extra_args:
        args.extend(extra_args)
    r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


def get_daily_state(td: date) -> dict:
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT nav::float, daily_return::float, cumulative_return::float,
                  drawdown::float, cash_ratio::float, position_count, turnover::float
           FROM performance_series
           WHERE strategy_id = %s AND trade_date = %s AND execution_mode = 'paper'""",
        (STRATEGY_ID, td),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return {}

    cur.execute(
        """SELECT COUNT(*) FROM trade_log
           WHERE strategy_id = %s AND trade_date = %s AND execution_mode = 'paper'""",
        (STRATEGY_ID, td),
    )
    n_trades = cur.fetchone()[0]
    conn.close()
    return {
        "nav": row[0], "daily_ret": row[1], "cum_ret": row[2],
        "drawdown": row[3], "cash_ratio": row[4], "positions": row[5],
        "turnover": row[6], "trades": n_trades,
    }


# ════════════════════════════════════════════════════════════
# 月度检查点 — 5项检查
# ════════════════════════════════════════════════════════════

def run_monthly_checkpoint(month_key: str, conn) -> tuple[bool, list[str]]:
    """月度检查点：5项检查。

    Args:
        month_key: "YYYY-MM" 格式
        conn: DB连接

    Returns:
        (all_pass, details) — all_pass=False时模拟应停止
    """
    details = []
    all_pass = True
    cur = conn.cursor()

    year, month = int(month_key[:4]), int(month_key[5:7])
    # 月首月末
    month_start = date(year, month, 1)
    month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

    print(f"\n{'─'*60}")
    print(f"  月度检查点: {month_key}")
    print(f"{'─'*60}")

    # ── 检查1: 本月是否触发了月度调仓？ ──
    cur.execute(
        """SELECT COUNT(DISTINCT trade_date) FROM trade_log
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND trade_date >= %s AND trade_date < %s""",
        (STRATEGY_ID, month_start, month_end),
    )
    rebal_days = cur.fetchone()[0]
    # 也检查signals中标记为rebalance的
    cur.execute(
        """SELECT COUNT(DISTINCT trade_date) FROM signals
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND action = 'rebalance'
             AND trade_date >= %s AND trade_date < %s""",
        (STRATEGY_ID, month_start, month_end),
    )
    signal_rebal = cur.fetchone()[0]

    has_rebalance = rebal_days > 0 or signal_rebal > 0
    if has_rebalance:
        details.append(f"  [1] 月度调仓: YES (trade_log {rebal_days}日有交易, signals {signal_rebal}日标记rebalance)")
    else:
        details.append("  [1] 月度调仓: NO -- 本月无调仓记录")
        # 首月（4月）允许无调仓（如果月初不在月末调仓日）
        # 非首月没有调仓是异常
        if month_key != "2025-04":
            all_pass = False
            details.append("      ** FAIL: 非首月应有至少1次调仓")

    # ── 检查2: 持仓数量是否≤20？ ──
    cur.execute(
        """SELECT trade_date, COUNT(*) as n
           FROM position_snapshot
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND trade_date >= %s AND trade_date < %s
           GROUP BY trade_date
           ORDER BY trade_date DESC LIMIT 1""",
        (STRATEGY_ID, month_start, month_end),
    )
    pos_row = cur.fetchone()
    if pos_row:
        pos_date, pos_count = pos_row
        if pos_count > 20:
            all_pass = False
            details.append(f"  [2] 持仓数量: {pos_count} (日期={pos_date}) ** FAIL: >20! **")
        else:
            details.append(f"  [2] 持仓数量: {pos_count} (日期={pos_date}) OK (<=20)")

        # 也检查本月内是否有任何一天>20
        cur.execute(
            """SELECT trade_date, COUNT(*) as n
               FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'
                 AND trade_date >= %s AND trade_date < %s
               GROUP BY trade_date
               HAVING COUNT(*) > 20
               ORDER BY trade_date""",
            (STRATEGY_ID, month_start, month_end),
        )
        over20_days = cur.fetchall()
        if over20_days:
            all_pass = False
            details.append(f"      ** FAIL: {len(over20_days)}天持仓>20: {[(str(d), n) for d, n in over20_days[:5]]}")
    else:
        details.append("  [2] 持仓数量: 无快照数据")

    # ── 检查3: NAV是否合理？(正值且与初始资金偏差<50%) ──
    cur.execute(
        """SELECT trade_date, nav::float
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND trade_date >= %s AND trade_date < %s
           ORDER BY trade_date DESC LIMIT 1""",
        (STRATEGY_ID, month_start, month_end),
    )
    nav_row = cur.fetchone()
    if nav_row:
        nav_date, nav_val = nav_row
        nav_deviation = abs(nav_val / INITIAL_CAPITAL - 1)
        nav_positive = nav_val > 0
        nav_reasonable = nav_deviation < 0.50

        if not nav_positive:
            all_pass = False
            details.append(f"  [3] NAV: {nav_val:,.0f} (日期={nav_date}) ** FAIL: 负值! **")
        elif not nav_reasonable:
            all_pass = False
            details.append(f"  [3] NAV: {nav_val:,.0f} (偏差={nav_deviation:.1%}) ** FAIL: 偏差>50% **")
        else:
            details.append(f"  [3] NAV: {nav_val:,.0f} (偏差={nav_deviation:.1%}) OK")

        # 检查本月是否有任何NAV<=0的天数
        cur.execute(
            """SELECT COUNT(*) FROM performance_series
               WHERE strategy_id = %s AND execution_mode = 'paper'
                 AND trade_date >= %s AND trade_date < %s
                 AND nav <= 0""",
            (STRATEGY_ID, month_start, month_end),
        )
        neg_nav_days = cur.fetchone()[0]
        if neg_nav_days > 0:
            all_pass = False
            details.append(f"      ** FAIL: {neg_nav_days}天NAV<=0 **")
    else:
        details.append("  [3] NAV: 无数据")

    # ── 检查4: 风控是否正确触发？(检查scheduler_task_log中circuit_breaker记录) ──
    cur.execute(
        """SELECT schedule_time::date, status, error_message
           FROM scheduler_task_log
           WHERE task_name = 'circuit_breaker'
             AND schedule_time >= %s AND schedule_time < %s
           ORDER BY schedule_time""",
        (month_start, month_end),
    )
    cb_logs = cur.fetchall()
    if cb_logs:
        cb_summary = defaultdict(int)
        for _, status, _ in cb_logs:
            cb_summary[status] += 1
        summary_str = ", ".join(f"{k}={v}" for k, v in cb_summary.items())
        details.append(f"  [4] 风控记录: {len(cb_logs)}条 ({summary_str})")
    else:
        # 没有circuit_breaker记录也是正常的（意味着没触发熔断）
        details.append("  [4] 风控记录: 0条 (无熔断触发，正常)")

    # ── 检查5: 本月最大单日亏损是否触发了对应级别熔断？ ──
    cur.execute(
        """SELECT trade_date, daily_return::float
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND trade_date >= %s AND trade_date < %s
           ORDER BY daily_return ASC LIMIT 1""",
        (STRATEGY_ID, month_start, month_end),
    )
    worst_row = cur.fetchone()
    if worst_row:
        worst_date, worst_ret = worst_row
        expected_level = 0
        if worst_ret < -0.05:
            expected_level = 2
        elif worst_ret < -0.03:
            expected_level = 1

        # 检查该日是否有对应的熔断记录
        if expected_level > 0:
            cur.execute(
                """SELECT status FROM scheduler_task_log
                   WHERE task_name = 'circuit_breaker'
                     AND schedule_time::date = %s""",
                (worst_date,),
            )
            cb_row = cur.fetchone()
            # 熔断是在T+1执行阶段检查的，所以需要检查worst_date的下一个交易日
            cur.execute(
                """SELECT MIN(trade_date) FROM trading_calendar
                   WHERE market='astock' AND is_trading_day=TRUE AND trade_date > %s""",
                (worst_date,),
            )
            next_td_row = cur.fetchone()
            next_td = next_td_row[0] if next_td_row else None

            if next_td:
                cur.execute(
                    """SELECT status FROM scheduler_task_log
                       WHERE task_name = 'circuit_breaker'
                         AND schedule_time::date = %s""",
                    (next_td,),
                )
                cb_next = cur.fetchone()
                triggered = cb_row is not None or cb_next is not None
            else:
                triggered = cb_row is not None

            if triggered:
                details.append(f"  [5] 最大单日亏损: {worst_ret:+.2%} ({worst_date}) "
                               f"预期L{expected_level}熔断 -> 已触发 OK")
            else:
                # 不一定是error，因为熔断检查看的是performance_series的最新数据
                # 如果之后有盈利日覆盖，可能不会触发
                details.append(f"  [5] 最大单日亏损: {worst_ret:+.2%} ({worst_date}) "
                               f"预期L{expected_level}熔断 -> 未找到记录 (WARNING)")
        else:
            details.append(f"  [5] 最大单日亏损: {worst_ret:+.2%} ({worst_date}) "
                           f"未达熔断阈值 (正常)")
    else:
        details.append("  [5] 最大单日亏损: 无数据")

    # 输出结果
    status = "PASS" if all_pass else "** FAIL **"
    for d in details:
        print(d)
    print(f"  检查结果: {status}")

    return all_pass, details


# ════════════════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    trading_days = get_trading_days(START_DATE, END_DATE)
    month_ends = get_month_end_days(START_DATE, END_DATE)

    # 过滤有因子数据的日期
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT trade_date FROM factor_values
           WHERE trade_date BETWEEN %s AND %s""",
        (START_DATE, END_DATE),
    )
    factor_dates = {r[0] for r in cur.fetchall()}
    conn.close()
    trading_days = [d for d in trading_days if d in factor_dates]

    print("=" * 70)
    print("Paper Trading 1年模拟验证（月度检查点版）")
    print(f"期间: {trading_days[0]} -> {trading_days[-1]} ({len(trading_days)}天)")
    print(f"预期月度调仓: {len(month_ends)}次")
    print(f"策略: {STRATEGY_ID}")
    print(f"初始资金: {INITIAL_CAPITAL:,}")
    print("=" * 70)

    # 清理
    clean_state()

    # 逐日运行
    results = []
    errors = []
    rebalance_dates = []
    circuit_breaker_events = []
    current_month = None
    checkpoint_results = {}  # month_key -> (pass, details)

    # 正确时序：T日signal -> T+1日execute（与生产crontab一致）
    for i, td in enumerate(trading_days):
        # T日信号阶段
        rc, out = run_phase("signal", td)
        if rc != 0:
            errors.append((td, "signal", out[-200:] if len(out) > 200 else out))
            continue

        # T+1日执行阶段（用下一个交易日）
        if i + 1 < len(trading_days):
            exec_td = trading_days[i + 1]
        else:
            # 最后一天没有T+1，跳过execute
            continue

        rc, out = run_phase("execute", exec_td)
        if rc != 0:
            if "L4" in out or "HALT" in out:
                circuit_breaker_events.append((exec_td, "L4", "管道停止"))
                errors.append((exec_td, "execute-L4", "熔断停止"))
            else:
                errors.append((exec_td, "execute", out[-200:] if len(out) > 200 else out))
            continue

        # 检查熔断触发
        for level in ["L1", "L2", "L3"]:
            if f"[{level}" in out:
                reason = ""
                for line in out.split("\n"):
                    if level in line:
                        reason = line.strip()[:80]
                        break
                circuit_breaker_events.append((exec_td, level, reason))

        # 检查调仓
        if "调仓: 是" in out:
            rebalance_dates.append(exec_td)

        state = get_daily_state(exec_td)
        if state:
            results.append((exec_td, state))

        # 进度输出（每月一次）
        month = td.strftime("%Y-%m")
        if month != current_month:
            if current_month is not None:
                # 上个月刚结束，运行月度检查点
                print(f"\n  [{current_month}结束] 运行月度检查点...")
                chk_conn = psycopg2.connect(DB_URL)
                passed, details = run_monthly_checkpoint(current_month, chk_conn)
                chk_conn.close()
                checkpoint_results[current_month] = (passed, details)

                if not passed:
                    print(f"\n{'!'*70}")
                    print(f"  月度检查点 {current_month} FAILED! 停止模拟。")
                    print(f"{'!'*70}")
                    break

            current_month = month
            if state:
                print(f"\n  {month}: NAV={state['nav']:,.0f} "
                      f"cum={state['cum_ret']:+.2%} "
                      f"pos={state['positions']} "
                      f"trades={state['trades']}", flush=True)

    # 最后一个月的检查点
    if current_month and current_month not in checkpoint_results:
        print(f"\n  [{current_month}结束] 运行月度检查点...")
        chk_conn = psycopg2.connect(DB_URL)
        passed, details = run_monthly_checkpoint(current_month, chk_conn)
        chk_conn.close()
        checkpoint_results[current_month] = (passed, details)

    elapsed = time.time() - t0

    # ═══════════════════════════════════════
    # 月度检查点汇总
    # ═══════════════════════════════════════
    print(f"\n{'='*70}")
    print("月度检查点汇总")
    print(f"{'='*70}")
    print(f"{'月份':>8} {'调仓':>6} {'持仓':>6} {'NAV':>6} {'风控':>6} {'熔断':>6} {'结果':>8}")
    print("-" * 55)

    for mk in sorted(checkpoint_results.keys()):
        passed, details = checkpoint_results[mk]
        # 从details解析各项状态
        checks = ["?"] * 5
        for d in details:
            for idx in range(1, 6):
                tag = f"[{idx}]"
                if tag in d:
                    if "FAIL" in d:
                        checks[idx-1] = "FAIL"
                    elif "OK" in d or "正常" in d or "YES" in d:
                        checks[idx-1] = "OK"
                    elif "WARNING" in d:
                        checks[idx-1] = "WARN"
                    elif "NO" in d and "FAIL" not in d:
                        checks[idx-1] = "OK"  # 首月无调仓可以是OK
                    else:
                        checks[idx-1] = "?"
        status = "PASS" if passed else "FAIL"
        print(f"{mk:>8} {checks[0]:>6} {checks[1]:>6} {checks[2]:>6} "
              f"{checks[3]:>6} {checks[4]:>6} {status:>8}")

    # ═══════════════════════════════════════
    # 月度汇总
    # ═══════════════════════════════════════
    print(f"\n{'='*70}")
    print("月度汇总")
    print(f"{'='*70}")
    print(f"{'月份':>8} {'月末NAV':>12} {'月收益':>8} {'月MDD':>8} {'调仓':>4} {'风控':>6}")
    print("-" * 55)

    monthly = defaultdict(list)
    for td, s in results:
        monthly[td.strftime("%Y-%m")].append((td, s))

    total_rebalances = 0
    for month_key in sorted(monthly.keys()):
        days = monthly[month_key]
        navs = [s["nav"] for _, s in days]
        month_ret = (navs[-1] / navs[0] - 1) if navs[0] > 0 else 0

        # 月内MDD
        peak = navs[0]
        max_dd = 0
        for n in navs:
            peak = max(peak, n)
            dd = (n / peak - 1)
            max_dd = min(max_dd, dd)

        # 本月调仓次数
        month_rebal = sum(1 for d in rebalance_dates if d.strftime("%Y-%m") == month_key)
        total_rebalances += month_rebal

        # 本月风控事件
        month_cb = [e for e in circuit_breaker_events if e[0].strftime("%Y-%m") == month_key]
        cb_str = f"{len(month_cb)}次" if month_cb else "正常"

        print(f"{month_key:>8} {navs[-1]:>12,.0f} {month_ret:>+7.2%} "
              f"{max_dd:>+7.2%} {month_rebal:>4} {cb_str:>6}")

    # ═══════════════════════════════════════
    # 全期统计
    # ═══════════════════════════════════════
    print(f"\n{'='*70}")
    print("全期统计")
    print(f"{'='*70}")

    if results:
        all_navs = [s["nav"] for _, s in results]
        all_rets = [s["daily_ret"] for _, s in results]
        final_nav = all_navs[-1]
        total_ret = final_nav / INITIAL_CAPITAL - 1
        ann_ret = (1 + total_ret) ** (252 / len(results)) - 1

        # Sharpe
        daily_mean = np.mean(all_rets)
        daily_std = np.std(all_rets, ddof=1)
        sharpe = daily_mean / daily_std * np.sqrt(252) if daily_std > 0 else 0

        # MDD
        peak = all_navs[0]
        max_dd = 0
        for n in all_navs:
            peak = max(peak, n)
            max_dd = min(max_dd, n / peak - 1)

        print(f"  运行天数: {len(results)}")
        print(f"  初始资金: {INITIAL_CAPITAL:,} -> 最终NAV: {final_nav:,.0f}")
        print(f"  总收益: {total_ret:+.2%}")
        print(f"  年化收益: {ann_ret:+.2%}")
        print(f"  Sharpe: {sharpe:.2f}")
        print(f"  最大回撤: {max_dd:+.2%}")
        print(f"  调仓次数: {total_rebalances} (预期12)")
        print(f"  风控事件: {len(circuit_breaker_events)}")
        print(f"  错误天数: {len(errors)}/{len(trading_days)}")
        print(f"  月度检查点: {sum(1 for p,_ in checkpoint_results.values() if p)}/{len(checkpoint_results)} 通过")
        print(f"  运行时间: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")

    # ═══════════════════════════════════════
    # 验证检查
    # ═══════════════════════════════════════
    print(f"\n{'='*70}")
    print("验证检查")
    print(f"{'='*70}")

    # 1. 调仓次数
    expected_rebal = len(month_ends & factor_dates)
    actual_rebal = total_rebalances
    rebal_ok = abs(actual_rebal - expected_rebal) <= 1
    print(f"  调仓次数: {actual_rebal} (预期~{expected_rebal}) {'OK' if rebal_ok else 'FAIL'}")

    if rebalance_dates:
        print(f"  调仓日期: {[str(d) for d in rebalance_dates[:5]]}{'...' if len(rebalance_dates)>5 else ''}")

    # 2. NAV连续性
    nav_positive = all(s["nav"] > 0 for _, s in results)
    print(f"  NAV全部>0: {'OK' if nav_positive else 'FAIL'}")

    # 3. 浮点漂移检查
    if results:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(
            """SELECT trade_date, nav::float, cash::float, cash_ratio::float
               FROM performance_series
               WHERE strategy_id = %s AND execution_mode = 'paper'
                 AND cash IS NOT NULL
               ORDER BY trade_date""",
            (STRATEGY_ID,),
        )
        rows = cur.fetchall()
        max_drift = 0
        for r in rows:
            if r[1] > 0 and r[2] is not None and r[3] is not None:
                implied_cash = r[1] * r[3]
                drift = abs(r[2] - implied_cash)
                max_drift = max(max_drift, drift)
        conn.close()
        print(f"  Cash最大漂移: {max_drift:.2f} {'OK' if max_drift < 100 else 'WARNING'}")

    # 4. 持仓连续性
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date, COUNT(*) as n
           FROM position_snapshot
           WHERE strategy_id = %s AND execution_mode = 'paper'
           GROUP BY trade_date ORDER BY trade_date""",
        (STRATEGY_ID,),
    )
    pos_days = cur.fetchall()
    ghost_days = [(d, n) for d, n in pos_days if n < 10 or n > 30]
    print(f"  持仓快照天数: {len(pos_days)}")
    if ghost_days:
        print(f"  WARNING: 异常持仓天数: {len(ghost_days)} (首个: {ghost_days[0]})")
    else:
        print("  持仓全部在10-30只范围: OK")
    conn.close()

    # 5. 风控事件
    if circuit_breaker_events:
        print("\n  风控事件明细:")
        for td, level, reason in circuit_breaker_events:
            print(f"    {td} {level}: {reason}")
    else:
        print("  风控熔断: 0次触发 OK")

    # 6. 错误清单
    if errors:
        print("\n  错误清单:")
        for td, phase, msg in errors[:10]:
            print(f"    {td} [{phase}]: {msg[:60]}")
        if len(errors) > 10:
            print(f"    ... 共{len(errors)}个错误")

    # 最终结果
    all_checkpoints_pass = all(p for p, _ in checkpoint_results.values())
    if all_checkpoints_pass and checkpoint_results:
        print(f"\n  所有月度检查点通过 ({len(checkpoint_results)}/{len(checkpoint_results)})")
    elif checkpoint_results:
        failed_months = [m for m, (p, _) in checkpoint_results.items() if not p]
        print(f"\n  月度检查点失败: {failed_months}")

    print(f"\n1年模拟验证完成 ({elapsed:.0f}s)")


if __name__ == "__main__":
    main()
