"""QuantStats统一接口 -- CLAUDE.md规则5: 一个工具一个wrapper。

CLAUDE.md规则4(绩效分析双轨):
  QuantStats生成HTML报告（给人看）。
  核心指标（Sharpe/MDD/CI）仍然自己算（给程序用、写入DB）。
  两者互为验证——不一致说明有bug。
"""

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def generate_html_report(
    returns: pd.Series,
    benchmark: Optional[pd.Series] = None,
    title: str = "QuantMind V2",
    output_path: Optional[str] = None,
) -> str:
    """生成HTML绩效报告。

    Args:
        returns: 日收益率序列 (DatetimeIndex, float)
        benchmark: 基准日收益率序列（可选，默认沪深300）
        title: 报告标题
        output_path: 输出文件路径。None则自动生成到reports/目录

    Returns:
        str: 生成的HTML文件绝对路径

    Raises:
        RuntimeError: quantstats未安装
        ValueError: returns为空
    """
    try:
        import quantstats as qs
    except ImportError:
        raise RuntimeError("quantstats未安装: pip install quantstats")

    if returns.empty:
        raise ValueError("returns序列为空，无法生成报告")

    if output_path is None:
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)
        output_path = str(reports_dir / f"report_{title.replace(' ', '_')}.html")

    qs.reports.html(
        returns,
        benchmark=benchmark,
        output=output_path,
        title=title,
    )
    logger.info("QuantStats HTML报告已生成: %s", output_path)
    return str(Path(output_path).resolve())


def get_metrics(
    returns: pd.Series,
    benchmark: Optional[pd.Series] = None,
) -> dict:
    """获取核心绩效指标（双轨验证：与自写metrics互为校验）。

    Args:
        returns: 日收益率序列
        benchmark: 基准日收益率序列（可选）

    Returns:
        dict: 包含以下键:
            - sharpe: Sharpe比率
            - sortino: Sortino比率
            - max_drawdown: 最大回撤（负数）
            - cagr: 年化收益率
            - calmar: Calmar比率
            - volatility: 年化波动率
            - win_rate: 胜率
            - avg_win: 平均盈利
            - avg_loss: 平均亏损
            - profit_factor: 盈亏比

    Raises:
        RuntimeError: quantstats未安装
    """
    try:
        import quantstats as qs
    except ImportError:
        raise RuntimeError("quantstats未安装: pip install quantstats")

    if returns.empty:
        return {}

    # 确保index是DatetimeIndex
    if not isinstance(returns.index, pd.DatetimeIndex):
        returns = returns.copy()
        returns.index = pd.to_datetime(returns.index)

    def _safe_float(val) -> float:
        """将QuantStats返回值安全转为float。

        QuantStats某些版本/输入组合下可能返回Series而非标量，
        用pd.isna/None检查替代 `or 0` 避免Series真值歧义。
        """
        if val is None:
            return 0.0
        if isinstance(val, pd.Series):
            val = val.iloc[0] if len(val) > 0 else 0.0
        result = float(val)
        if pd.isna(result):
            return 0.0
        return result

    metrics = {
        "sharpe": _safe_float(qs.stats.sharpe(returns)),
        "sortino": _safe_float(qs.stats.sortino(returns)),
        "max_drawdown": _safe_float(qs.stats.max_drawdown(returns)),
        "cagr": _safe_float(qs.stats.cagr(returns)),
        "calmar": _safe_float(qs.stats.calmar(returns)),
        "volatility": _safe_float(qs.stats.volatility(returns)),
        "win_rate": _safe_float(qs.stats.win_rate(returns)),
        "avg_win": _safe_float(qs.stats.avg_win(returns)),
        "avg_loss": _safe_float(qs.stats.avg_loss(returns)),
        "profit_factor": _safe_float(qs.stats.profit_factor(returns)),
    }

    if benchmark is not None:
        if not isinstance(benchmark.index, pd.DatetimeIndex):
            benchmark = benchmark.copy()
            benchmark.index = pd.to_datetime(benchmark.index)
        metrics["information_ratio"] = _safe_float(
            qs.stats.information_ratio(returns, benchmark)
        )

    return metrics
