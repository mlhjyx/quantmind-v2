#!/usr/bin/env python3
"""L3风控阈值扫描工具 — 可复用脚本。

Sprint 1.3a中对L3日频方案做了5阈值对比(-5%/-6%/-7%/-10%/-15%)，
但分析逻辑散落在一次性脚本中。本脚本将其脚本化为通用CLI工具。

功能:
  1. 从DB读取CSI500(60%)+CSI1000(40%)日收益率作为策略代理
  2. 对每个阈值模拟L3触发:
     - 触发次数 / 年均触发
     - 平均L3停留天数
     - 误触发率(触发后N天内反弹>M%的比例)
     - 漏报率(未触发但后续20天跌>15%的比例)
  3. 输出格式化表格 + 自动推荐最优阈值

CLI用法:
  python scripts/risk_threshold_scan.py \\
      --metric rolling_5d_return \\
      --thresholds -0.03,-0.05,-0.07,-0.10 \\
      --recovery-days 3 \\
      --recovery-return 0.015

遵循CLAUDE.md: 类型注解 + Google style docstring(中文)。
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# 默认参数
# ============================================================

DEFAULT_DB_URL = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

# CSI500(60%) + CSI1000(40%) 混合代理权重，与Sprint 1.3a L3分析一致
PROXY_WEIGHTS: dict[str, float] = {
    "000905.SH": 0.6,  # CSI500
    "000852.SH": 0.4,  # CSI1000
}

# 误触发判定: 触发后 REBOUND_WINDOW 天内反弹超 REBOUND_THRESHOLD
REBOUND_WINDOW = 5
REBOUND_THRESHOLD = 0.03

# 漏报判定: 未触发但后续 MISS_WINDOW 天跌超 MISS_THRESHOLD
MISS_WINDOW = 20
MISS_THRESHOLD = -0.15


# ============================================================
# 数据结构
# ============================================================


@dataclass
class ThresholdResult:
    """单个阈值的扫描结果。"""

    threshold: float
    total_triggers: int
    triggers_per_year: float
    avg_stay_days: float
    false_trigger_rate: float  # 误触发率(0~1)
    miss_rate: float  # 漏报率(0~1)


@dataclass
class ScanReport:
    """完整扫描报告。"""

    metric_name: str
    recovery_days: int
    recovery_return: float
    date_range: tuple[date, date]
    total_trading_days: int
    results: list[ThresholdResult] = field(default_factory=list)
    recommended_threshold: float | None = None
    recommendation_reason: str = ""


# ============================================================
# 数据加载
# ============================================================


def load_proxy_returns(
    db_url: str = DEFAULT_DB_URL,
    proxy_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """从DB加载CSI500+CSI1000日收益率，合成策略代理收益序列。

    Args:
        db_url: PostgreSQL连接字符串。
        proxy_weights: 指数代码→权重映射，默认CSI500(60%)+CSI1000(40%)。

    Returns:
        DataFrame，columns=['trade_date', 'daily_return']，按日期排序。
    """
    if proxy_weights is None:
        proxy_weights = PROXY_WEIGHTS

    index_codes = list(proxy_weights.keys())
    placeholders = ",".join(["%s"] * len(index_codes))

    sql = f"""
        SELECT index_code, trade_date, pct_change
        FROM index_daily
        WHERE index_code IN ({placeholders})
        ORDER BY trade_date
    """

    conn = psycopg2.connect(db_url)
    try:
        df = pd.read_sql(sql, conn, params=index_codes)
    finally:
        conn.close()

    if df.empty:
        raise RuntimeError(f"index_daily表中未找到指数数据: {index_codes}。请确认数据已拉取。")

    # pct_change在DB中是百分比(如1.5表示1.5%)，转为小数
    df["daily_return"] = df["pct_change"].astype(float) / 100.0

    # 透视表: 每个指数一列
    pivot = df.pivot(index="trade_date", columns="index_code", values="daily_return")

    # 加权合成
    proxy_return = pd.Series(0.0, index=pivot.index, dtype=float)
    for code, weight in proxy_weights.items():
        if code not in pivot.columns:
            logger.warning("指数 %s 在数据中不存在，跳过", code)
            continue
        proxy_return += pivot[code].fillna(0.0) * weight

    result = pd.DataFrame(
        {
            "trade_date": pivot.index,
            "daily_return": proxy_return.values,
        }
    ).reset_index(drop=True)

    result["trade_date"] = pd.to_datetime(result["trade_date"]).dt.date

    logger.info(
        "加载代理收益: %s ~ %s, %d个交易日",
        result["trade_date"].iloc[0],
        result["trade_date"].iloc[-1],
        len(result),
    )
    return result


# ============================================================
# 指标计算
# ============================================================


def compute_rolling_metric(
    daily_returns: pd.Series,
    metric_name: str,
) -> pd.Series:
    """根据指标名计算滚动指标序列。

    支持的指标:
      - rolling_Xd_return: 滚动X日累计收益率(如rolling_5d_return, rolling_20d_return)

    Args:
        daily_returns: 日收益率序列(小数形式)。
        metric_name: 指标名。

    Returns:
        与daily_returns等长的Series，前window-1个值为NaN。

    Raises:
        ValueError: 指标名不支持时。
    """
    if metric_name.startswith("rolling_") and metric_name.endswith("d_return"):
        # 解析窗口: rolling_5d_return → 5
        try:
            window = int(metric_name.replace("rolling_", "").replace("d_return", ""))
        except ValueError as err:
            raise ValueError(f"无法解析滚动窗口: {metric_name}") from err

        # 滚动累计收益 = (1+r1)(1+r2)...(1+rN) - 1
        cumulative = (
            (1 + daily_returns).rolling(window=window).apply(lambda x: x.prod() - 1, raw=True)
        )
        return cumulative

    raise ValueError(
        f"不支持的指标: {metric_name}。"
        "目前支持: rolling_Xd_return (如 rolling_5d_return, rolling_20d_return)"
    )


# ============================================================
# 核心扫描逻辑
# ============================================================


def simulate_threshold(
    metric_series: pd.Series,
    daily_returns: pd.Series,
    threshold: float,
    recovery_days: int,
    recovery_return: float,
    rebound_window: int = REBOUND_WINDOW,
    rebound_threshold: float = REBOUND_THRESHOLD,
    miss_window: int = MISS_WINDOW,
    miss_threshold: float = MISS_THRESHOLD,
) -> ThresholdResult:
    """对单个阈值模拟L3触发，计算各项统计指标。

    模拟状态机:
      NORMAL → metric <= threshold → L3_TRIGGERED
      L3_TRIGGERED → 连续recovery_days天日收益>0 且 累计>recovery_return → NORMAL

    Args:
        metric_series: 滚动指标序列(与daily_returns等长)。
        daily_returns: 日收益率序列。
        threshold: 触发阈值(负数，如-0.05)。
        recovery_days: 恢复所需连续盈利天数。
        recovery_return: 恢复所需累计收益(小数)。
        rebound_window: 误触发判定窗口(天)。
        rebound_threshold: 误触发反弹阈值(小数)。
        miss_window: 漏报判定窗口(天)。
        miss_threshold: 漏报跌幅阈值(负数小数)。

    Returns:
        ThresholdResult: 该阈值的完整统计结果。
    """
    n = len(metric_series)
    valid_mask = ~np.isnan(metric_series.values)

    # --- 模拟状态机 ---
    in_l3 = False
    streak_days = 0
    streak_return = 0.0

    trigger_indices: list[int] = []  # 每次触发时的index
    stay_durations: list[int] = []  # 每次L3停留天数
    current_trigger_start: int = -1

    for i in range(n):
        if not valid_mask[i]:
            continue

        metric_val = metric_series.values[i]
        daily_ret = daily_returns.values[i]

        if not in_l3:
            # NORMAL状态: 检查是否触发
            if metric_val <= threshold:
                in_l3 = True
                current_trigger_start = i
                trigger_indices.append(i)
                streak_days = 0
                streak_return = 0.0
        else:
            # L3状态: 检查恢复条件
            if daily_ret > 0:
                streak_days += 1
                streak_return += daily_ret
            else:
                # 中断连续盈利，重置streak
                streak_days = 0
                streak_return = 0.0

            if streak_days >= recovery_days and streak_return >= recovery_return:
                # 恢复到NORMAL
                duration = i - current_trigger_start
                stay_durations.append(duration)
                in_l3 = False
                streak_days = 0
                streak_return = 0.0

    # 如果最后仍在L3，记录到末尾的停留天数
    if in_l3 and current_trigger_start >= 0:
        stay_durations.append(n - 1 - current_trigger_start)

    total_triggers = len(trigger_indices)

    # --- 年化触发频率 ---
    total_valid = int(valid_mask.sum())
    years = total_valid / 242.0  # A股年交易日约242天
    triggers_per_year = total_triggers / years if years > 0 else 0.0

    # --- 平均停留天数 ---
    avg_stay = float(np.mean(stay_durations)) if stay_durations else 0.0

    # --- 误触发率: 触发后rebound_window天内反弹>rebound_threshold ---
    false_triggers = 0
    for idx in trigger_indices:
        end = min(idx + rebound_window, n)
        if end > idx:
            forward_cum = (1 + daily_returns.iloc[idx:end]).prod() - 1
            if forward_cum > rebound_threshold:
                false_triggers += 1
    false_trigger_rate = false_triggers / total_triggers if total_triggers > 0 else 0.0

    # --- 漏报率: 应触发未触发，但后续miss_window天跌超miss_threshold ---
    # 定义"应触发未触发": 在NORMAL状态下，后续miss_window天累计跌幅超miss_threshold
    # 构建触发覆盖期(在L3中的交易日不算漏报)
    l3_mask = np.zeros(n, dtype=bool)
    for t_idx, duration in zip(trigger_indices, stay_durations, strict=False):
        l3_mask[t_idx : min(t_idx + duration + 1, n)] = True
    # 如果最后仍在L3且trigger_indices比stay_durations多一个
    if len(trigger_indices) > len(stay_durations) and trigger_indices:
        l3_mask[trigger_indices[-1] :] = True

    # 计算每天的forward miss_window天累计收益
    miss_events = 0
    normal_days = 0
    for i in range(n - miss_window):
        if not valid_mask[i]:
            continue
        if l3_mask[i]:
            continue  # 已在L3中，不算漏报
        normal_days += 1
        forward_cum = (1 + daily_returns.iloc[i : i + miss_window]).prod() - 1
        if forward_cum <= miss_threshold:
            miss_events += 1

    miss_rate = miss_events / normal_days if normal_days > 0 else 0.0

    return ThresholdResult(
        threshold=threshold,
        total_triggers=total_triggers,
        triggers_per_year=triggers_per_year,
        avg_stay_days=avg_stay,
        false_trigger_rate=false_trigger_rate,
        miss_rate=miss_rate,
    )


def run_scan(
    daily_returns_df: pd.DataFrame,
    metric_name: str,
    thresholds: Sequence[float],
    recovery_days: int,
    recovery_return: float,
    rebound_window: int = REBOUND_WINDOW,
    rebound_threshold: float = REBOUND_THRESHOLD,
    miss_window: int = MISS_WINDOW,
    miss_threshold: float = MISS_THRESHOLD,
) -> ScanReport:
    """执行完整阈值扫描。

    Args:
        daily_returns_df: DataFrame，需含columns=['trade_date', 'daily_return']。
        metric_name: 滚动指标名(如rolling_5d_return)。
        thresholds: 阈值列表(负数)。
        recovery_days: 恢复所需连续盈利天数。
        recovery_return: 恢复所需累计收益(小数)。
        rebound_window: 误触发判定窗口。
        rebound_threshold: 误触发反弹阈值。
        miss_window: 漏报判定窗口。
        miss_threshold: 漏报跌幅阈值。

    Returns:
        ScanReport: 完整扫描报告。
    """
    daily_ret_series = daily_returns_df["daily_return"].astype(float)
    metric_series = compute_rolling_metric(daily_ret_series, metric_name)

    report = ScanReport(
        metric_name=metric_name,
        recovery_days=recovery_days,
        recovery_return=recovery_return,
        date_range=(
            daily_returns_df["trade_date"].iloc[0],
            daily_returns_df["trade_date"].iloc[-1],
        ),
        total_trading_days=len(daily_returns_df),
    )

    for thresh in sorted(thresholds):
        result = simulate_threshold(
            metric_series=metric_series,
            daily_returns=daily_ret_series,
            threshold=thresh,
            recovery_days=recovery_days,
            recovery_return=recovery_return,
            rebound_window=rebound_window,
            rebound_threshold=rebound_threshold,
            miss_window=miss_window,
            miss_threshold=miss_threshold,
        )
        report.results.append(result)

    # --- 自动推荐 ---
    # 规则: 误杀率<20% 且 漏报率<10% 的最窄(最接近0)阈值
    candidates = [r for r in report.results if r.false_trigger_rate < 0.20 and r.miss_rate < 0.10]
    if candidates:
        # 最窄 = 绝对值最小 = 最接近0
        best = max(candidates, key=lambda r: r.threshold)
        report.recommended_threshold = best.threshold
        report.recommendation_reason = (
            f"误杀率{best.false_trigger_rate:.1%}<20% 且 漏报率{best.miss_rate:.1%}<10% 中最窄阈值"
        )
    else:
        report.recommendation_reason = (
            "无阈值同时满足误杀率<20%且漏报率<10%，建议扩大阈值扫描范围或调整推荐标准"
        )

    return report


# ============================================================
# 输出格式化
# ============================================================


def format_report(report: ScanReport) -> str:
    """将扫描报告格式化为可读表格。

    Args:
        report: ScanReport扫描结果。

    Returns:
        格式化的多行字符串。
    """
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("L3 风控阈值扫描报告")
    lines.append("=" * 80)
    lines.append(f"指标:       {report.metric_name}")
    lines.append(f"数据范围:   {report.date_range[0]} ~ {report.date_range[1]}")
    lines.append(f"交易日数:   {report.total_trading_days}")
    lines.append(
        f"恢复条件:   连续{report.recovery_days}天盈利 且 累计>{report.recovery_return:.1%}"
    )
    lines.append("-" * 80)

    # 表头
    header = (
        f"{'阈值':>8s}  "
        f"{'触发次数':>8s}  "
        f"{'年均触发':>8s}  "
        f"{'平均停留天':>10s}  "
        f"{'误杀率':>8s}  "
        f"{'漏报率':>8s}  "
        f"{'推荐':>4s}"
    )
    lines.append(header)
    lines.append("-" * 80)

    for r in report.results:
        is_recommended = (
            "*"
            if report.recommended_threshold is not None
            and abs(r.threshold - report.recommended_threshold) < 1e-9
            else ""
        )

        # 误杀率/漏报率超标时标记
        ft_mark = " !" if r.false_trigger_rate >= 0.20 else ""
        mr_mark = " !" if r.miss_rate >= 0.10 else ""

        row = (
            f"{r.threshold:>8.1%}  "
            f"{r.total_triggers:>8d}  "
            f"{r.triggers_per_year:>8.1f}  "
            f"{r.avg_stay_days:>10.1f}  "
            f"{r.false_trigger_rate:>7.1%}{ft_mark}  "
            f"{r.miss_rate:>7.1%}{mr_mark}  "
            f"{'  <<' if is_recommended else '':>4s}"
        )
        lines.append(row)

    lines.append("-" * 80)

    if report.recommended_threshold is not None:
        lines.append(
            f"推荐阈值: {report.recommended_threshold:.1%}  ({report.recommendation_reason})"
        )
    else:
        lines.append(f"推荐: {report.recommendation_reason}")

    lines.append("")
    lines.append("注: '!' 表示该指标超过推荐标准(误杀率>=20%或漏报率>=10%)")
    lines.append("    '<<' 表示推荐阈值")
    lines.append("=" * 80)

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="L3风控阈值扫描工具 — 对指定指标的多个阈值做触发模拟分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 扫描滚动5日收益率的4个阈值
  python scripts/risk_threshold_scan.py \\
      --metric rolling_5d_return \\
      --thresholds -0.03,-0.05,-0.07,-0.10

  # 自定义恢复条件
  python scripts/risk_threshold_scan.py \\
      --metric rolling_20d_return \\
      --thresholds -0.05,-0.07,-0.10,-0.15 \\
      --recovery-days 5 --recovery-return 0.02

  # 自定义误触发/漏报判定参数
  python scripts/risk_threshold_scan.py \\
      --metric rolling_5d_return \\
      --thresholds -0.03,-0.05,-0.07 \\
      --rebound-window 5 --rebound-threshold 0.03 \\
      --miss-window 20 --miss-threshold -0.15
        """,
    )
    parser.add_argument(
        "--metric",
        type=str,
        default="rolling_5d_return",
        help="滚动指标名(默认: rolling_5d_return)。支持rolling_Xd_return格式(如rolling_20d_return)",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default="-0.03,-0.05,-0.07,-0.10",
        help="逗号分隔的阈值列表(默认: -0.03,-0.05,-0.07,-0.10)",
    )
    parser.add_argument(
        "--recovery-days",
        type=int,
        default=3,
        help="恢复所需连续盈利天数(默认: 3)",
    )
    parser.add_argument(
        "--recovery-return",
        type=float,
        default=0.015,
        help="恢复所需累计收益率(默认: 0.015即1.5%%)",
    )
    parser.add_argument(
        "--rebound-window",
        type=int,
        default=REBOUND_WINDOW,
        help=f"误触发判定窗口天数(默认: {REBOUND_WINDOW})",
    )
    parser.add_argument(
        "--rebound-threshold",
        type=float,
        default=REBOUND_THRESHOLD,
        help=f"误触发反弹阈值(默认: {REBOUND_THRESHOLD})",
    )
    parser.add_argument(
        "--miss-window",
        type=int,
        default=MISS_WINDOW,
        help=f"漏报判定窗口天数(默认: {MISS_WINDOW})",
    )
    parser.add_argument(
        "--miss-threshold",
        type=float,
        default=MISS_THRESHOLD,
        help=f"漏报跌幅阈值(默认: {MISS_THRESHOLD})",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=DEFAULT_DB_URL,
        help="PostgreSQL连接字符串",
    )
    parser.add_argument(
        "--csv",
        type=str,
        default=None,
        help="可选: 输出结果到CSV文件路径",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI入口。"""
    args = parse_args(argv)

    thresholds = [float(t.strip()) for t in args.thresholds.split(",")]
    logger.info("阈值列表: %s", thresholds)
    logger.info("指标: %s", args.metric)
    logger.info(
        "恢复条件: %d天连续盈利 且 累计>%.2f%%", args.recovery_days, args.recovery_return * 100
    )

    # 1. 加载数据
    daily_df = load_proxy_returns(db_url=args.db_url)

    # 2. 执行扫描
    report = run_scan(
        daily_returns_df=daily_df,
        metric_name=args.metric,
        thresholds=thresholds,
        recovery_days=args.recovery_days,
        recovery_return=args.recovery_return,
        rebound_window=args.rebound_window,
        rebound_threshold=args.rebound_threshold,
        miss_window=args.miss_window,
        miss_threshold=args.miss_threshold,
    )

    # 3. 输出报告
    print(format_report(report))

    # 4. 可选CSV导出
    if args.csv:
        rows = []
        for r in report.results:
            rows.append(
                {
                    "threshold": r.threshold,
                    "total_triggers": r.total_triggers,
                    "triggers_per_year": round(r.triggers_per_year, 2),
                    "avg_stay_days": round(r.avg_stay_days, 1),
                    "false_trigger_rate": round(r.false_trigger_rate, 4),
                    "miss_rate": round(r.miss_rate, 4),
                    "recommended": (
                        report.recommended_threshold is not None
                        and abs(r.threshold - report.recommended_threshold) < 1e-9
                    ),
                }
            )
        csv_df = pd.DataFrame(rows)
        csv_df.to_csv(args.csv, index=False)
        logger.info("结果已导出到: %s", args.csv)


if __name__ == "__main__":
    main()
