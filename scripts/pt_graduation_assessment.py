"""PT毕业正式评估脚本。

从 trade_log / performance_series 表读取 Paper Trading 数据，计算：
- 实际 Sharpe（年化）
- 实际 MDD
- 滑点偏差（实际 vs 理论 slippage_bps）
- 毕业判断：Sharpe ≥ 0.72, MDD < 35%, 滑点偏差 < 50%

用法:
    python scripts/pt_graduation_assessment.py
    python scripts/pt_graduation_assessment.py --strategy-id <uuid>
    python scripts/pt_graduation_assessment.py --min-trades 20

前置条件:
    - PostgreSQL 正常运行
    - 环境变量 DATABASE_URL 已配置（或 backend/.env 存在）
"""

import argparse
import asyncio
import math
import os
import sys
from pathlib import Path

# 项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import asyncpg  # noqa: E402

# ─────────────────────────────────────────────
# 毕业阈值（CLAUDE.md §策略版本化纪律）
# ─────────────────────────────────────────────
SHARPE_THRESHOLD = 0.72
MDD_THRESHOLD = 0.35          # 绝对值，35%
SLIPPAGE_DEV_THRESHOLD = 0.50  # 50% 偏差
MIN_TRADE_RECORDS = 20        # 数据不足判断线
TRADING_DAYS_PER_YEAR = 244   # A股交易日

# 理论滑点基点（v1.1 基线，双边各 5bps）
THEORETICAL_SLIPPAGE_BPS = 5.0


# ─────────────────────────────────────────────
# 数据库工具
# ─────────────────────────────────────────────

def _get_dsn() -> str:
    """从环境变量或 backend/.env 读取 DATABASE_URL。"""
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn
    env_path = PROJECT_ROOT / "backend" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(
        "DATABASE_URL 未设置。请在环境变量或 backend/.env 中配置。"
    )


# ─────────────────────────────────────────────
# 核心计算函数（纯函数，便于单元测试）
# ─────────────────────────────────────────────

def calc_sharpe(daily_returns: list[float]) -> float:
    """计算年化 Sharpe（无风险利率=0，A股常见做法）。

    Args:
        daily_returns: 每日收益率列表（小数，如 0.01 代表 1%）。

    Returns:
        年化 Sharpe，数据不足时返回 0.0。
    """
    n = len(daily_returns)
    if n < 2:
        return 0.0
    mean = sum(daily_returns) / n
    variance = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def calc_mdd(nav_series: list[float]) -> float:
    """计算最大回撤（绝对值，如 0.20 代表 20%）。

    Args:
        nav_series: NAV 时间序列（升序）。

    Returns:
        最大回撤绝对值，数据不足时返回 0.0。
    """
    if len(nav_series) < 2:
        return 0.0
    peak = nav_series[0]
    max_dd = 0.0
    for nav in nav_series:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def calc_slippage_deviation(
    actual_bps_list: list[float],
    theoretical_bps: float,
) -> float:
    """计算滑点偏差率（实际均值 vs 理论值的相对偏差）。

    Args:
        actual_bps_list: 每笔成交的实际滑点（基点）列表。
        theoretical_bps: 理论滑点基点（v1.1 基线）。

    Returns:
        偏差率绝对值，如 0.30 代表 30%。数据为空时返回 0.0。
    """
    if not actual_bps_list or theoretical_bps == 0.0:
        return 0.0
    actual_mean = sum(actual_bps_list) / len(actual_bps_list)
    return abs(actual_mean - theoretical_bps) / theoretical_bps


def calc_running_days(trade_dates: list) -> int:
    """计算 PT 运行天数（首末交易日之差，含首日）。

    Args:
        trade_dates: 交易日列表（date 对象）。

    Returns:
        日历天数。
    """
    if not trade_dates:
        return 0
    sorted_dates = sorted(trade_dates)
    return (sorted_dates[-1] - sorted_dates[0]).days + 1


# ─────────────────────────────────────────────
# 数据库查询
# ─────────────────────────────────────────────

async def fetch_trade_log(
    conn: asyncpg.Connection,
    strategy_id: str | None,
) -> list[asyncpg.Record]:
    """从 trade_log 拉取 paper 模式成交记录。"""
    if strategy_id:
        rows = await conn.fetch(
            """
            SELECT trade_date, slippage_bps
            FROM trade_log
            WHERE execution_mode = 'paper'
              AND strategy_id = $1::uuid
            ORDER BY trade_date
            """,
            strategy_id,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT trade_date, slippage_bps
            FROM trade_log
            WHERE execution_mode = 'paper'
            ORDER BY trade_date
            """
        )
    return rows


async def fetch_performance_series(
    conn: asyncpg.Connection,
    strategy_id: str | None,
) -> list[asyncpg.Record]:
    """从 performance_series 拉取 paper 模式绩效序列。"""
    if strategy_id:
        rows = await conn.fetch(
            """
            SELECT trade_date, nav, daily_return
            FROM performance_series
            WHERE execution_mode = 'paper'
              AND strategy_id = $1::uuid
            ORDER BY trade_date
            """,
            strategy_id,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT trade_date, nav, daily_return
            FROM performance_series
            WHERE execution_mode = 'paper'
            ORDER BY trade_date
            """
        )
    return rows


# ─────────────────────────────────────────────
# 报告输出
# ─────────────────────────────────────────────

def _fmt_pass(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


def print_report(
    running_days: int,
    sharpe: float,
    mdd: float,
    slippage_dev: float,
    trade_count: int,
    insufficient: bool,
) -> None:
    """打印毕业评估报告。"""
    print()
    print("=" * 45)
    print("       PT毕业评估报告")
    print("=" * 45)

    if insufficient:
        print(f"交易记录数: {trade_count} 条")
        print()
        print("数据不足，建议Day 30+后评估")
        print("=" * 45)
        return

    sharpe_pass = sharpe >= SHARPE_THRESHOLD
    mdd_pass = mdd < MDD_THRESHOLD
    slippage_pass = slippage_dev < SLIPPAGE_DEV_THRESHOLD
    all_pass = sharpe_pass and mdd_pass and slippage_pass

    print(f"运行天数:    {running_days}天")
    print(f"交易记录数:  {trade_count}条")
    print()
    print(
        f"Sharpe:      {sharpe:>6.2f}  "
        f"[{_fmt_pass(sharpe_pass)}]  阈值: ≥{SHARPE_THRESHOLD}"
    )
    print(
        f"MDD:         {-mdd * 100:>5.1f}%  "
        f"[{_fmt_pass(mdd_pass)}]  阈值: <{MDD_THRESHOLD * 100:.0f}%"
    )
    print(
        f"滑点偏差:    {slippage_dev * 100:>5.1f}%  "
        f"[{_fmt_pass(slippage_pass)}]  阈值: <{SLIPPAGE_DEV_THRESHOLD * 100:.0f}%"
    )
    print()
    print(f"总结: {'GRADUATE' if all_pass else 'NOT_READY'}")
    print("=" * 45)
    print()


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

async def run_assessment(
    strategy_id: str | None,
    min_trades: int,
) -> None:
    """执行 PT 毕业评估。

    Args:
        strategy_id: 策略 UUID（可选，None 则查全部 paper 记录）。
        min_trades: 数据不足判断阈值。
    """
    dsn = _get_dsn()
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        trade_rows = await fetch_trade_log(conn, strategy_id)
        perf_rows = await fetch_performance_series(conn, strategy_id)

        trade_count = len(trade_rows)
        if trade_count < min_trades:
            print_report(
                running_days=0,
                sharpe=0.0,
                mdd=0.0,
                slippage_dev=0.0,
                trade_count=trade_count,
                insufficient=True,
            )
            return

        # 滑点偏差
        slippage_bps_list: list[float] = [
            float(r["slippage_bps"])
            for r in trade_rows
            if r["slippage_bps"] is not None
        ]
        slippage_dev = calc_slippage_deviation(slippage_bps_list, THEORETICAL_SLIPPAGE_BPS)

        # Sharpe + MDD — 来自 performance_series
        daily_returns: list[float] = [
            float(r["daily_return"])
            for r in perf_rows
            if r["daily_return"] is not None
        ]
        nav_series: list[float] = [
            float(r["nav"])
            for r in perf_rows
            if r["nav"] is not None
        ]
        sharpe = calc_sharpe(daily_returns)
        mdd = calc_mdd(nav_series)

        # 运行天数取 performance_series 的首末日期
        perf_dates = [r["trade_date"] for r in perf_rows]
        running_days = calc_running_days(perf_dates)

        print_report(
            running_days=running_days,
            sharpe=sharpe,
            mdd=mdd,
            slippage_dev=slippage_dev,
            trade_count=trade_count,
            insufficient=False,
        )
    finally:
        await conn.close()


def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="PT毕业正式评估")
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="策略 UUID（不填则汇总全部 paper 记录）",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=MIN_TRADE_RECORDS,
        help=f"数据不足阈值（默认: {MIN_TRADE_RECORDS}）",
    )
    args = parser.parse_args()

    asyncio.run(run_assessment(args.strategy_id, args.min_trades))


if __name__ == "__main__":
    main()
