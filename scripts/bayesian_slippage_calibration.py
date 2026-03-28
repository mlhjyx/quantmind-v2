"""Bayesian滑点参数校准脚本。

用途:
  Day 30+后，从paper_trading执行记录（trade_log表）中校准
  slippage_model.py的核心参数，提升模型对实际成本的拟合精度。

校准参数（来自SlippageConfig + overnight_gap_cost）:
  - base_bps_small: 小盘基础滑点(bps)，先验 Normal(8, 3)
  - Y_small: 小盘冲击系数，先验 Normal(1.5, 0.3)，R4建议→1.8
  - Y_mid: 中盘冲击系数，先验 Normal(1.0, 0.2)
  - sell_penalty: 卖出惩罚倍数，先验 Normal(1.2, 0.2)，R4建议→1.3
  - overnight_gap_cost_bps: 隔夜跳空均值(bps)，先验 Normal(25, 10)

校准方法:
  主路径: scipy.optimize MLE (PyMC未安装)
  似然函数: 实测滑点 ~ Normal(模型预测滑点(params), sigma)

数据来源: trade_log表 (execution_mode='paper', slippage_bps非NULL)

铁律7: OOS验证 — 本脚本本身不做策略OOS，但校准参数必须在验证集
上检查拟合优度后才建议更新。

用法:
  python scripts/bayesian_slippage_calibration.py [--min-records N] [--dry-run] [--output-params]
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sys
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import optimize

# 确保能import backend模块
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bayesian_slippage_cal")

# ──────────────────────────────────────────────────────────────
# 先验定义（R4研究建议值 + 统计先验）
# ──────────────────────────────────────────────────────────────

PRIORS: dict[str, tuple[float, float]] = {
    # 参数名: (均值, 标准差)
    "base_bps": (8.0, 3.0),          # 小盘基础滑点，R4: 8bps
    "k_coef": (0.5, 0.2),            # 旧路径冲击系数（保留兼容性）
    "y_small": (1.5, 0.3),           # 小盘Y，R4建议1.8
    "y_large": (2.5, 0.5),           # 大单惩罚（此处用于overnight sigma）
    "sell_penalty": (1.2, 0.2),      # 卖出惩罚，R4建议1.3
    "overnight_gap_cost_bps": (25.0, 10.0),  # 隔夜跳空均值
}

# R4研究建议的手动校准值（数据不足时输出）
R4_MANUAL_RECOMMENDATIONS: dict[str, float] = {
    "y_small": 1.8,
    "sell_penalty": 1.3,
    "overnight_gap_cost_bps": 25.0,
    "base_bps_small": 8.0,
}

# 参数合理性范围（用于先验检查）
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "base_bps": (1.0, 50.0),
    "k_coef": (0.05, 5.0),
    "y_small": (0.5, 5.0),
    "y_large": (0.5, 10.0),
    "sell_penalty": (1.0, 3.0),
    "overnight_gap_cost_bps": (5.0, 100.0),
}


# ──────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────


def load_pt_execution_data(min_records: int = 30) -> pd.DataFrame:
    """从DB读取Paper Trading执行记录。

    数据来源: trade_log表，execution_mode='paper'，slippage_bps非NULL。
    当记录数 < min_records 时返回空DataFrame。

    Args:
        min_records: 最少需要的记录数，不足时返回空DataFrame。

    Returns:
        DataFrame，列: [direction, quantity, fill_price, target_price,
                        slippage_bps, trade_date]。
        不足时返回空DataFrame（列结构相同）。
    """
    required_cols = [
        "direction", "quantity", "fill_price", "target_price",
        "slippage_bps", "trade_date",
    ]
    empty = pd.DataFrame(columns=required_cols)

    try:
        import asyncio

        import asyncpg

        async def _fetch() -> list[dict]:
            db_url = os.environ.get(
                "DATABASE_URL",
                "postgresql://xin@localhost:5432/quantmind_v2",
            )
            conn = await asyncpg.connect(db_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT direction, quantity, fill_price, target_price,
                           slippage_bps, trade_date
                    FROM trade_log
                    WHERE execution_mode = 'paper'
                      AND slippage_bps IS NOT NULL
                      AND fill_price IS NOT NULL
                      AND target_price IS NOT NULL
                    ORDER BY trade_date
                    """
                )
                return [dict(r) for r in rows]
            finally:
                await conn.close()

        rows = asyncio.run(_fetch())
    except Exception as exc:
        logger.warning("DB连接失败: %s", exc)
        return empty

    if not rows:
        logger.info("trade_log中无paper trading执行记录")
        return empty

    df = pd.DataFrame(rows)
    for col in required_cols:
        if col not in df.columns:
            df[col] = None

    # 转换数值类型
    for col in ["fill_price", "target_price", "slippage_bps", "quantity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["slippage_bps", "fill_price", "target_price"])

    n = len(df)
    logger.info("从DB读取到 %d 条paper trading执行记录", n)

    if n < min_records:
        logger.info(
            "数据不足（当前%d条，需要>=%d条），返回空DataFrame",
            n, min_records,
        )
        return empty

    result = df[required_cols]
    assert isinstance(result, pd.DataFrame)
    return result


# ──────────────────────────────────────────────────────────────
# 模型预测
# ──────────────────────────────────────────────────────────────


def compute_model_slippage(
    params: dict[str, float],
    executions: pd.DataFrame,
) -> np.ndarray:
    """用给定参数计算每笔交易的模型预测滑点(bps)。

    简化模型（校准目的，无需完整市值分层）:
      predicted = base_bps + y_small * sigma_default * sqrt(participation) + overnight
    其中:
      participation = 估算参与率（quantity * fill_price / 日成交额代理值）
      sigma_default = 0.02（日波动率默认值，无实时数据时使用）
      overnight = overnight_gap_cost_bps * sell_penalty_factor

    Args:
        params: 参数字典，键与PRIORS一致。
        executions: 执行记录DataFrame，至少含 slippage_bps/direction/quantity/fill_price。

    Returns:
        模型预测滑点数组(bps)，shape=(len(executions),)。

    Raises:
        ValueError: 参数超出合理范围时。
    """
    # 参数范围校验
    for key, (lo, hi) in PARAM_BOUNDS.items():
        if key in params:
            val = params[key]
            if not (lo <= val <= hi):
                raise ValueError(
                    f"参数 {key}={val:.4f} 超出合理范围 [{lo}, {hi}]"
                )

    base_bps = params.get("base_bps", PRIORS["base_bps"][0])
    y_small = params.get("y_small", PRIORS["y_small"][0])
    sell_penalty = params.get("sell_penalty", PRIORS["sell_penalty"][0])
    overnight = params.get("overnight_gap_cost_bps", PRIORS["overnight_gap_cost_bps"][0])

    n = len(executions)
    if n == 0:
        return np.array([])

    sigma_default = 0.02  # 约30%年化，A股小盘股典型值

    # 估算参与率: 小额交易参与率通常0.1-2%
    # 无日成交额数据时，用trade_amount / 代理日成交额(50万元)
    qty = np.asarray(executions["quantity"], dtype=float)
    price = np.asarray(executions["fill_price"], dtype=float)
    trade_amounts = qty * price
    proxy_daily_amount = 5_000_000.0  # 500万元代理，保守估计小盘股
    participation = np.clip(trade_amounts / proxy_daily_amount, 1e-6, 0.5)

    impact_bps = y_small * sigma_default * np.sqrt(participation) * 10000

    # 卖出方向额外惩罚（仅对impact部分）
    is_sell = (executions["direction"].values == "sell").astype(float)
    impact_bps = impact_bps * (1 + (sell_penalty - 1.0) * is_sell)

    predicted = base_bps + impact_bps + overnight
    return predicted.astype(float)


# ──────────────────────────────────────────────────────────────
# MLE校准（主路径，PyMC fallback）
# ──────────────────────────────────────────────────────────────


@dataclass
class CalibrationResult:
    """校准结果。

    Attributes:
        params: 后验/MLE参数估计值字典。
        ci_lower: 95% CI下界（MLE时为±1.96*SE，Bayesian时为2.5%分位数）。
        ci_upper: 95% CI上界。
        log_likelihood: 最终对数似然值。
        rmse: 训练集预测RMSE(bps)。
        method: 'mle' 或 'bayesian'。
        n_records: 用于校准的记录数。
    """

    params: dict[str, float]
    ci_lower: dict[str, float]
    ci_upper: dict[str, float]
    log_likelihood: float
    rmse: float
    method: str
    n_records: int


def mle_calibrate(executions: pd.DataFrame) -> CalibrationResult:
    """MLE校准——PyMC不可用时的标准路径。

    最大化对数似然:
      log L = sum_i log N(obs_i | predicted_i(params), sigma)
    同时加入对数先验（MAP估计）:
      log prior = sum_k log N(params_k | mu_k, sigma_k)

    Args:
        executions: 执行记录DataFrame（不能为空）。

    Returns:
        CalibrationResult，含MAP参数估计 + 95%近似CI。

    Raises:
        ValueError: executions为空。
    """
    if len(executions) == 0:
        raise ValueError("执行记录为空，无法校准")

    observed = executions["slippage_bps"].values.astype(float)

    # 待优化参数: [base_bps, y_small, sell_penalty, overnight_gap_cost_bps, log_sigma]
    param_names = ["base_bps", "y_small", "sell_penalty", "overnight_gap_cost_bps"]
    x0 = [PRIORS[k][0] for k in param_names] + [math.log(10.0)]  # log_sigma初始值

    bounds = [PARAM_BOUNDS[k] for k in param_names] + [(math.log(0.5), math.log(200.0))]

    def neg_log_posterior(x: list[float]) -> float:
        params = dict(zip(param_names, x[:-1], strict=False))
        log_sigma = x[-1]
        sigma = math.exp(log_sigma)

        try:
            predicted = compute_model_slippage(params, executions)
        except ValueError:
            return 1e10

        # 对数似然
        residuals = observed - predicted
        log_lik = -0.5 * np.sum((residuals / sigma) ** 2) - len(observed) * log_sigma

        # 对数先验（MAP）
        log_prior = 0.0
        for k, val in params.items():
            mu, sigma_p = PRIORS[k]
            log_prior += -0.5 * ((val - mu) / sigma_p) ** 2

        return -(log_lik + log_prior)

    result = optimize.minimize(
        neg_log_posterior,
        x0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 1000, "ftol": 1e-10},
    )

    if not result.success:
        warnings.warn(f"MLE优化未完全收敛: {result.message}", stacklevel=2)

    opt_params = dict(zip(param_names, result.x[:-1], strict=False))

    # 近似95% CI via Hessian（数值二阶导）
    ci_lower: dict[str, float] = {}
    ci_upper: dict[str, float] = {}
    try:
        hess = result.hess_inv
        hess_mat = np.array(hess.todense()) if hasattr(hess, "todense") else np.array(hess)

        se = np.sqrt(np.maximum(np.diag(hess_mat), 0))
        for i, k in enumerate(param_names):
            ci_lower[k] = opt_params[k] - 1.96 * se[i]
            ci_upper[k] = opt_params[k] + 1.96 * se[i]
    except Exception:
        # Hessian不可用时用先验sigma作为近似不确定度
        for k in param_names:
            ci_lower[k] = opt_params[k] - 1.96 * PRIORS[k][1]
            ci_upper[k] = opt_params[k] + 1.96 * PRIORS[k][1]

    # 计算RMSE
    predicted = compute_model_slippage(opt_params, executions)
    rmse = float(np.sqrt(np.mean((observed - predicted) ** 2)))
    log_lik_final = float(-result.fun + sum(
        -0.5 * ((opt_params[k] - PRIORS[k][0]) / PRIORS[k][1]) ** 2
        for k in param_names
    ))

    return CalibrationResult(
        params=opt_params,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        log_likelihood=log_lik_final,
        rmse=rmse,
        method="mle_map",
        n_records=len(executions),
    )


def bayesian_calibrate(executions: pd.DataFrame) -> CalibrationResult:
    """Bayesian校准，优先尝试PyMC，不可用时fallback到MLE。

    Args:
        executions: 执行记录DataFrame。

    Returns:
        CalibrationResult，method字段标注实际使用的方法。
    """
    try:
        import pymc as pm  # type: ignore
        import pytensor.tensor as pt  # type: ignore

        logger.info("PyMC可用，使用完整Bayesian MCMC校准")
        return _pymc_calibrate(executions, pm, pt)
    except ImportError:
        logger.info("PyMC未安装，使用MLE MAP校准（scipy fallback）")
        return mle_calibrate(executions)


def _pymc_calibrate(executions: pd.DataFrame, pm, pt) -> CalibrationResult:
    """PyMC MCMC校准实现（内部函数）。"""
    observed = executions["slippage_bps"].values.astype(float)

    with pm.Model():
        base_bps = pm.Normal("base_bps", mu=8.0, sigma=3.0)
        y_small = pm.Normal("y_small", mu=1.5, sigma=0.3)
        sell_penalty = pm.Normal("sell_penalty", mu=1.2, sigma=0.2)
        overnight = pm.Normal("overnight_gap_cost_bps", mu=25.0, sigma=10.0)
        sigma = pm.HalfNormal("sigma", sigma=10.0)

        # 简化预测（PyMC tensor路径）
        trade_amounts = (
            np.asarray(executions["quantity"], dtype=float)
            * np.asarray(executions["fill_price"], dtype=float)
        )
        participation = np.clip(trade_amounts / 5_000_000.0, 1e-6, 0.5)
        is_sell = (executions["direction"].values == "sell").astype(float)

        impact = y_small * 0.02 * pt.sqrt(participation) * 10000
        impact_adj = impact * (1 + (sell_penalty - 1.0) * is_sell)
        mu_pred = base_bps + impact_adj + overnight

        pm.Normal("obs", mu=mu_pred, sigma=sigma, observed=observed)
        trace = pm.sample(1000, tune=500, cores=1, progressbar=False, return_inferencedata=True)

    import arviz as az  # type: ignore
    summary = az.summary(trace, hdi_prob=0.95)

    param_names = ["base_bps", "y_small", "sell_penalty", "overnight_gap_cost_bps"]
    opt_params = {k: float(summary.loc[k, "mean"]) for k in param_names}
    ci_lower = {k: float(summary.loc[k, "hdi_2.5%"]) for k in param_names}
    ci_upper = {k: float(summary.loc[k, "hdi_97.5%"]) for k in param_names}

    predicted = compute_model_slippage(opt_params, executions)
    rmse = float(np.sqrt(np.mean((observed - predicted) ** 2)))

    return CalibrationResult(
        params=opt_params,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        log_likelihood=float("nan"),
        rmse=rmse,
        method="bayesian_mcmc",
        n_records=len(executions),
    )


# ──────────────────────────────────────────────────────────────
# 报告生成
# ──────────────────────────────────────────────────────────────


def generate_calibration_report(
    original: dict[str, float],
    calibrated: CalibrationResult,
    data: pd.DataFrame,
) -> str:
    """生成校准报告（文本格式）。

    Args:
        original: 校准前的原始参数字典。
        calibrated: 校准结果。
        data: 用于校准的执行记录。

    Returns:
        格式化的校准报告字符串。
    """
    lines = [
        "=" * 60,
        "  Bayesian滑点校准报告",
        f"  方法: {calibrated.method}",
        f"  记录数: {calibrated.n_records}",
        f"  训练RMSE: {calibrated.rmse:.2f} bps",
        f"  Log-Likelihood: {calibrated.log_likelihood:.4f}",
        "=" * 60,
        "",
        "参数对比（原始 → 校准 [95% CI]）:",
        "-" * 60,
    ]

    for k in calibrated.params:
        orig_val = original.get(k, float("nan"))
        cal_val = calibrated.params[k]
        lo = calibrated.ci_lower.get(k, float("nan"))
        hi = calibrated.ci_upper.get(k, float("nan"))
        change = cal_val - orig_val
        sign = "+" if change >= 0 else ""
        lines.append(
            f"  {k:<28} {orig_val:>7.3f} → {cal_val:>7.3f} ({sign}{change:.3f})"
            f"  [{lo:.3f}, {hi:.3f}]"
        )

    lines += [
        "",
        "观测滑点统计:",
        f"  均值:   {data['slippage_bps'].mean():.2f} bps",
        f"  中位数: {data['slippage_bps'].median():.2f} bps",
        f"  标准差: {data['slippage_bps'].std():.2f} bps",
        f"  最大值: {data['slippage_bps'].max():.2f} bps",
        "",
        "注意: 校准参数需在验证集上确认拟合优度后才建议更新（铁律7）",
        "=" * 60,
    ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────────────────────

DEFAULT_PARAMS: dict[str, float] = {
    "base_bps": PRIORS["base_bps"][0],
    "y_small": PRIORS["y_small"][0],
    "sell_penalty": PRIORS["sell_penalty"][0],
    "overnight_gap_cost_bps": PRIORS["overnight_gap_cost_bps"][0],
}


def main() -> None:
    """命令行入口。

    参数:
        --min-records N: 最少需要N条记录才执行校准（默认30）
        --dry-run: 只检查数据量，不实际校准
        --output-params: 输出可直接粘贴到.env的参数行
    """
    parser = argparse.ArgumentParser(description="Bayesian滑点参数校准")
    parser.add_argument(
        "--min-records", type=int, default=30,
        help="最少需要N条记录才执行校准（默认30）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只检查数据量，不实际校准",
    )
    parser.add_argument(
        "--output-params", action="store_true",
        help="输出可直接粘贴到.env的参数行",
    )
    args = parser.parse_args()

    logger.info("=== Bayesian滑点校准开始 ===")
    logger.info("最小记录数要求: %d", args.min_records)

    # 加载数据
    df = load_pt_execution_data(min_records=args.min_records)

    if df.empty:
        n_actual = _count_actual_records()
        print(
            f"\n数据不足（当前{n_actual}条，需要>={args.min_records}条）\n"
            "建议在Day 30+后重新运行此脚本。\n"
        )
        print("基于R4研究的手动校准建议（当前数据不足时使用）:")
        print("-" * 50)
        for k, v in R4_MANUAL_RECOMMENDATIONS.items():
            orig = DEFAULT_PARAMS.get(k, float("nan"))
            print(f"  {k:<28}: {orig:.3f} → {v:.3f}")

        if args.output_params:
            print("\n# 可粘贴到.env的R4手动推荐参数:")
            print(f"SLIPPAGE_Y_SMALL={R4_MANUAL_RECOMMENDATIONS['y_small']}")
            print(f"SLIPPAGE_SELL_PENALTY={R4_MANUAL_RECOMMENDATIONS['sell_penalty']}")
            print(f"SLIPPAGE_OVERNIGHT_GAP_BPS={R4_MANUAL_RECOMMENDATIONS['overnight_gap_cost_bps']}")
        return

    print(f"\n读取到 {len(df)} 条PT执行记录")
    print(f"滑点统计: 均值={df['slippage_bps'].mean():.1f}bps, "
          f"中位数={df['slippage_bps'].median():.1f}bps, "
          f"标准差={df['slippage_bps'].std():.1f}bps")

    if args.dry_run:
        print("\n[--dry-run] 数据检查完成，跳过校准。")
        return

    # 执行校准
    logger.info("开始MLE/Bayesian校准...")
    result = bayesian_calibrate(df)

    # 生成报告
    report = generate_calibration_report(DEFAULT_PARAMS, result, df)
    print("\n" + report)

    if args.output_params:
        print("\n# 可粘贴到.env的校准参数（请先在验证集确认后再使用）:")
        for k, v in result.params.items():
            env_key = f"SLIPPAGE_{k.upper()}"
            print(f"{env_key}={v:.4f}")


def _count_actual_records() -> int:
    """尝试查询实际记录数，失败返回0。"""
    try:
        import asyncio

        import asyncpg

        async def _count() -> int:
            db_url = os.environ.get(
                "DATABASE_URL",
                "postgresql://xin@localhost:5432/quantmind_v2",
            )
            conn = await asyncpg.connect(db_url)
            try:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) as n FROM trade_log "
                    "WHERE execution_mode='paper' AND slippage_bps IS NOT NULL"
                )
                return int(row["n"])
            finally:
                await conn.close()

        return asyncio.run(_count())
    except Exception:
        return 0


if __name__ == "__main__":
    main()
