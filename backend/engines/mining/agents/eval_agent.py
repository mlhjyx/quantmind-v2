"""EvalAgent — 因子统计评估智能体

设计来源:
  - docs/research/R7_ai_model_selection.md §4.1 (DeepSeek-V3为Eval Agent)
  - docs/GP_CLOSED_LOOP_DESIGN.md (Step 5 评估)

功能:
  1. 接收GeneratedFactorCode(来自FactorAgent) → 在沙箱中执行
  2. 调用factor_engine预处理(去极值→填充→中性化→z-score)
  3. 计算IC时序(Rank IC, Spearman相关)
  4. 输出EvalResult: IC统计 + Gate快筛结果 + 推荐/拒绝

Engine层规范: 纯计算逻辑，数据通过参数传入（不直接访问DB）。

Sprint 1.18 ml-engineer (D5补全)
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import structlog
from scipy import stats

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    """EvalAgent的输出 — 因子评估结果。"""
    factor_name: str
    is_valid: bool = False         # 代码执行成功且有有效IC
    ic_mean: float = 0.0           # IC均值
    ic_std: float = 0.0            # IC标准差
    ir: float = 0.0                # IC信息比率 (ic_mean / ic_std)
    t_stat: float = 0.0            # t统计量
    ic_series: list[float] = field(default_factory=list)  # 日频IC时序
    n_dates: int = 0               # 有效截面日数
    coverage: float = 0.0          # 平均截面覆盖率
    recommendation: str = "reject"  # "accept" / "review" / "reject"
    rejection_reason: str = ""
    execution_error: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 快筛阈值 (与factor_gate.py G1一致)
# ---------------------------------------------------------------------------

IC_THRESHOLD_ACCEPT = 0.03   # |IC| > 0.03 → 推荐进入Gate Pipeline
IC_THRESHOLD_REVIEW = 0.02   # |IC| > 0.02 → 半自动审查
T_STAT_THRESHOLD = 2.0       # t > 2.0 → 统计显著
MIN_DATES = 20               # 至少20个截面日


# ---------------------------------------------------------------------------
# EvalAgent
# ---------------------------------------------------------------------------


class EvalAgent:
    """因子统计评估Agent — 在沙箱中执行代码并计算IC。

    纯计算，不访问数据库。数据通过参数传入。

    用法:
        agent = EvalAgent()
        result = agent.evaluate(
            factor_code="def compute_factor(df): ...",
            price_data=df_prices,          # 行情数据
            forward_returns=df_fwd_ret,    # 前瞻收益
        )
    """

    def evaluate(
        self,
        factor_code: str,
        price_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        factor_name: str = "unnamed",
    ) -> EvalResult:
        """执行因子代码并评估IC。

        Args:
            factor_code: Python代码字符串，必须定义compute_factor(df) -> pd.Series。
            price_data: 行情数据 (code, trade_date, open, high, low, close, volume,
                        amount, turnover_rate, total_mv)。
            forward_returns: 前瞻收益 (code, trade_date, fwd_ret_5d)。
            factor_name: 因子名称（日志用）。

        Returns:
            EvalResult。
        """
        result = EvalResult(factor_name=factor_name)

        # Step 1: 在沙箱中执行代码
        factor_values = self._execute_code(factor_code, price_data, result)
        if factor_values is None:
            return result

        # Step 2: 计算IC时序
        self._compute_ic(factor_values, forward_returns, result)

        # Step 3: 判断推荐等级
        self._evaluate_recommendation(result)

        return result

    def _execute_code(
        self,
        code: str,
        price_data: pd.DataFrame,
        result: EvalResult,
    ) -> pd.DataFrame | None:
        """在受限命名空间中执行因子代码。

        Returns:
            DataFrame (code, trade_date, factor_value) 或 None（失败）。
        """
        # 安全检查
        forbidden = ["import os", "import sys", "eval(", "exec(", "__import__"]
        for f in forbidden:
            if f in code:
                result.execution_error = f"禁止操作: {f}"
                return None

        try:
            # 受限命名空间
            namespace: dict = {"pd": pd, "np": np}
            exec(code, namespace)  # noqa: S102

            compute_fn = namespace.get("compute_factor")
            if compute_fn is None:
                result.execution_error = "代码中未定义compute_factor函数"
                return None

            # 按日期分组执行
            rows = []
            for trade_date, group in price_data.groupby("trade_date"):
                try:
                    values = compute_fn(group)
                    if isinstance(values, pd.Series):
                        for code_str, val in zip(group["code"], values, strict=False):
                            if pd.notna(val) and np.isfinite(val):
                                rows.append({
                                    "code": code_str,
                                    "trade_date": trade_date,
                                    "factor_value": float(val),
                                })
                except Exception:
                    continue

            if not rows:
                result.execution_error = "compute_factor未产生任何有效值"
                return None

            df = pd.DataFrame(rows)
            logger.info(
                "[EvalAgent] %s: 计算成功, %d行, %d个日期",
                result.factor_name, len(df), df["trade_date"].nunique(),
            )
            return df

        except Exception as exc:
            result.execution_error = f"执行异常: {exc}\n{traceback.format_exc()}"
            logger.warning("[EvalAgent] %s: %s", result.factor_name, exc)
            return None

    def _compute_ic(
        self,
        factor_df: pd.DataFrame,
        forward_returns: pd.DataFrame,
        result: EvalResult,
    ) -> None:
        """计算Rank IC时序（Spearman相关）。"""
        # 合并因子值和前瞻收益
        merged = factor_df.merge(
            forward_returns,
            on=["code", "trade_date"],
            how="inner",
        )

        if merged.empty:
            result.execution_error = "因子值与前瞻收益无法对齐"
            return

        dates = sorted(merged["trade_date"].unique())
        ic_list: list[float] = []
        coverage_list: list[float] = []

        total_stocks: dict = (
            forward_returns.groupby("trade_date")["code"].nunique().to_dict()
        )

        for dt in dates:
            cross = merged[merged["trade_date"] == dt]
            if len(cross) < 30:
                continue

            ic, _ = stats.spearmanr(cross["factor_value"], cross["fwd_ret_5d"])
            if not np.isnan(float(ic)):
                ic_list.append(float(ic))

                n_total = int(total_stocks.get(dt, len(cross)))
                coverage_list.append(len(cross) / max(n_total, 1))

        if len(ic_list) < MIN_DATES:
            result.execution_error = f"有效截面日数不足: {len(ic_list)} < {MIN_DATES}"
            result.n_dates = len(ic_list)
            return

        ic_arr = np.array(ic_list)
        result.is_valid = True
        result.ic_mean = float(np.mean(ic_arr))
        result.ic_std = float(np.std(ic_arr, ddof=1))
        result.ir = result.ic_mean / result.ic_std if result.ic_std > 1e-12 else 0.0
        result.t_stat = (
            result.ic_mean / (result.ic_std / np.sqrt(len(ic_arr)))
            if result.ic_std > 1e-12
            else 0.0
        )
        result.ic_series = ic_list
        result.n_dates = len(ic_list)
        result.coverage = float(np.mean(coverage_list)) if coverage_list else 0.0

        logger.info(
            "[EvalAgent] %s: IC=%.4f, IR=%.2f, t=%.2f, n=%d",
            result.factor_name, result.ic_mean, result.ir, result.t_stat, result.n_dates,
        )

    @staticmethod
    def _evaluate_recommendation(result: EvalResult) -> None:
        """基于IC统计判断推荐等级。"""
        if not result.is_valid:
            result.recommendation = "reject"
            result.rejection_reason = result.execution_error or "评估失败"
            return

        abs_ic = abs(result.ic_mean)

        if abs_ic >= IC_THRESHOLD_ACCEPT and abs(result.t_stat) >= T_STAT_THRESHOLD:
            result.recommendation = "accept"
        elif abs_ic >= IC_THRESHOLD_REVIEW:
            result.recommendation = "review"
            result.warnings.append(
                f"|IC|={abs_ic:.4f} >= {IC_THRESHOLD_REVIEW} 但 < {IC_THRESHOLD_ACCEPT}，需人工审查"
            )
        else:
            result.recommendation = "reject"
            result.rejection_reason = f"|IC|={abs_ic:.4f} < {IC_THRESHOLD_REVIEW}，因子无效"
