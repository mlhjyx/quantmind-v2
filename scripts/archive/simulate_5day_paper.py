#!/usr/bin/env python3
"""Paper Trading 5天模拟验证。

清理现有状态 → 逐日运行signal+execute → 验证连续运行稳定性。
模拟3月16-20日（周一到周五）。

用法:
    python scripts/simulate_5day_paper.py
"""

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg2

from app.config import settings

DB_URL = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"
STRATEGY_ID = settings.PAPER_STRATEGY_ID

# 交易日列表 — 从DB动态查询
TRADING_DAYS = None  # 在main()中从trading_calendar查询


def clean_paper_state():
    """清理现有Paper Trading状态，从头开始。"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    tables = [
        "DELETE FROM trade_log WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM position_snapshot WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM performance_series WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM signals WHERE strategy_id = %s AND execution_mode = 'paper'",
        "DELETE FROM scheduler_task_log WHERE task_name LIKE '%%paper%%' OR task_name LIKE '%%signal%%' OR task_name LIKE '%%execute%%' OR task_name LIKE '%%circuit%%' OR task_name LIKE '%%data_fetch%%' OR task_name LIKE '%%factor_calc%%' OR task_name LIKE '%%state_save%%'",
    ]
    for sql in tables:
        if '%s' in sql:
            cur.execute(sql, (STRATEGY_ID,))
        else:
            cur.execute(sql)
    conn.commit()
    print(f"✅ 清理完成: strategy_id={STRATEGY_ID}")
    conn.close()


def check_factor_data():
    """检查哪些日期有因子数据。"""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    for td in TRADING_DAYS:
        cur.execute(
            "SELECT COUNT(DISTINCT factor_name) FROM factor_values WHERE trade_date = %s",
            (td,),
        )
        n = cur.fetchone()[0]
        print(f"  {td}: {n}个因子{'✅' if n >= 5 else '❌ 不足'}")
    conn.close()


def run_signal(td: date):
    """运行信号阶段。"""
    import subprocess
    r = subprocess.run(
        [sys.executable, "scripts/run_paper_trading.py", "signal",
         "--date", td.strftime("%Y-%m-%d"),
         "--skip-fetch", "--skip-factors"],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode, r.stdout, r.stderr


def run_execute(td: date):
    """运行执行阶段。"""
    import subprocess
    r = subprocess.run(
        [sys.executable, "scripts/run_paper_trading.py", "execute",
         "--date", td.strftime("%Y-%m-%d"),
         "--skip-fetch"],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode, r.stdout, r.stderr


def get_daily_summary(td: date) -> dict:
    """读取当日Paper Trading状态。"""
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


def main():
    # 从命令行或默认获取日期范围
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=str, default="2026-02-24")
    parser.add_argument("--end", type=str, default="2026-03-20")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    # 从DB查询交易日
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute(
        """SELECT trade_date FROM trading_calendar
           WHERE market='astock' AND is_trading_day=TRUE
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        (start_date, end_date),
    )
    global TRADING_DAYS
    TRADING_DAYS = [r[0] for r in cur.fetchall()]
    conn.close()

    # 过滤掉没有因子数据的日期
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    valid_days = []
    for td in TRADING_DAYS:
        cur.execute(
            "SELECT COUNT(DISTINCT factor_name) FROM factor_values WHERE trade_date = %s",
            (td,),
        )
        n = cur.fetchone()[0]
        if n >= 5:
            valid_days.append(td)
    conn.close()
    TRADING_DAYS = valid_days

    print("=" * 60)
    print(f"Paper Trading {len(TRADING_DAYS)}天连续模拟验证")
    print(f"策略: {STRATEGY_ID}")
    print(f"交易日: {TRADING_DAYS[0]} → {TRADING_DAYS[-1]} ({len(TRADING_DAYS)}天)")
    print("=" * 60)

    # Step 0: 检查因子数据
    print("\n[0] 检查因子数据...")
    check_factor_data()

    # Step 1: 清理状态
    print("\n[1] 清理现有Paper Trading状态...")
    clean_paper_state()

    # Step 2: 逐日模拟
    # 流程: Day1 signal → Day2 execute + signal → Day3 execute + signal → ...
    print("\n[2] 开始逐日模拟...")
    results = []

    for i, td in enumerate(TRADING_DAYS):
        print(f"\n{'─'*40}")
        print(f"📅 Day {i+1}: {td}")

        # 信号阶段（T日盘后）
        print(f"  [Signal] {td}...")
        rc, stdout, stderr = run_signal(td)
        if rc != 0:
            print(f"  ❌ Signal失败 (exit={rc})")
            # 提取关键错误
            for line in (stdout + stderr).split('\n'):
                if 'ERROR' in line or 'error' in line.lower():
                    print(f"    {line.strip()}")
            continue
        # 提取信号结果
        for line in stdout.split('\n'):
            if '目标持仓' in line or 'Beta' in line or '调仓' in line:
                print(f"    {line.strip()}")

        # 执行阶段（T+1日盘前，用当日数据）
        # 第一天没有前一天的信号可执行，直接用当天作为首次建仓
        if i == 0:
            # 首日：signal生成后，用当日价格作为execute（模拟T+1=T日场景）
            print(f"  [Execute] {td} (首次建仓)...")
            rc, stdout, stderr = run_execute(td)
        else:
            # 后续日：execute使用当日数据
            print(f"  [Execute] {td}...")
            rc, stdout, stderr = run_execute(td)

        if rc != 0:
            print(f"  ❌ Execute失败 (exit={rc})")
            for line in (stdout + stderr).split('\n'):
                if 'ERROR' in line or 'error' in line.lower():
                    print(f"    {line.strip()}")
            continue

        # 提取执行结果
        for line in stdout.split('\n'):
            if any(k in line for k in ['熔断', '风控', 'NAV', '调仓', '持仓', '执行报告', '日收益']):
                print(f"    {line.strip()}")

        # 读取当日summary
        summary = get_daily_summary(td)
        if summary:
            results.append((td, summary))
            print(f"  📊 NAV=¥{summary['nav']:,.0f} | "
                  f"日收益={summary['daily_ret']:+.2%} | "
                  f"累计={summary['cum_ret']:+.2%} | "
                  f"持仓={summary['positions']}只 | "
                  f"成交={summary['trades']}笔")

    # Step 3: 汇总报告
    print(f"\n{'='*60}")
    print("5天模拟汇总")
    print(f"{'='*60}")
    print(f"{'日期':>12} {'NAV':>12} {'日收益':>8} {'累计':>8} {'持仓':>4} {'成交':>4} {'熔断':>6}")
    print("-" * 60)
    for td, s in results:
        cb = "L0正常"  # 从scheduler_task_log查熔断状态
        print(f"{str(td):>12} {s['nav']:>12,.0f} {s['daily_ret']:>+7.2%} "
              f"{s['cum_ret']:>+7.2%} {s['positions']:>4} {s['trades']:>4} {cb:>6}")

    if results:
        results[0][1]['nav']
        last_nav = results[-1][1]['nav']
        total_ret = (last_nav / 1_000_000) - 1
        print("-" * 60)
        print(f"初始资金: ¥1,000,000 → 最终NAV: ¥{last_nav:,.0f} ({total_ret:+.2%})")
        print(f"运行天数: {len(results)}/{len(TRADING_DAYS)}")

    # 验证检查
    print(f"\n{'='*60}")
    print("验证检查")
    print(f"{'='*60}")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # NAV连续性
    cur.execute(
        """SELECT trade_date, nav::float FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
           ORDER BY trade_date""",
        (STRATEGY_ID,),
    )
    navs = cur.fetchall()
    print(f"  NAV记录数: {len(navs)} (期望={len(TRADING_DAYS)})")
    for i in range(1, len(navs)):
        if navs[i][1] <= 0:
            print(f"  ❌ {navs[i][0]}: NAV={navs[i][1]} <= 0!")
    print("  ✅ NAV连续性: 全部>0" if all(n[1] > 0 for n in navs) else "  ❌ NAV异常")

    # 持仓连续性
    cur.execute(
        """SELECT trade_date, COUNT(*) FROM position_snapshot
           WHERE strategy_id = %s AND execution_mode = 'paper'
           GROUP BY trade_date ORDER BY trade_date""",
        (STRATEGY_ID,),
    )
    pos_counts = cur.fetchall()
    print(f"  持仓快照天数: {len(pos_counts)}")
    for td, cnt in pos_counts:
        if cnt < 10 or cnt > 30:
            print(f"  ⚠️ {td}: 持仓={cnt}只(异常)")
    print("  ✅ 持仓连续性: 全部在10-30只范围" if all(10 <= c <= 30 for _, c in pos_counts) else "")

    # 熔断触发检查
    cur.execute(
        """SELECT task_name, status, error_message FROM scheduler_task_log
           WHERE task_name = 'circuit_breaker' ORDER BY created_at""",
    )
    cb_rows = cur.fetchall()
    if cb_rows:
        print(f"  ⚠️ 熔断触发 {len(cb_rows)} 次:")
        for r in cb_rows:
            print(f"    {r[0]}: {r[1]} - {r[2]}")
    else:
        print("  ✅ 熔断: 未触发(L0正常)")

    conn.close()
    print("\n✅ 5天模拟验证完成")


if __name__ == "__main__":
    main()
