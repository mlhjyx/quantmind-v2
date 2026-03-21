"""Beta对冲引擎 — Rolling Beta计算 + 组合权重调整。

Phase 0 Paper Trading: 通过缩放持仓权重模拟对冲（无实际做空）。
Phase 1 实盘: 替换为指数期货/ETF融券真实对冲。
"""

import logging
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calc_portfolio_beta(
    trade_date: date,
    strategy_id: str,
    lookback_days: int = 60,
    conn=None,
) -> float:
    """计算组合相对沪深300的Rolling Beta。

    从performance_series读取Paper Trading历史NAV，
    从index_daily读取CSI300收盘价，计算OLS Beta。

    Args:
        trade_date: 当前交易日
        strategy_id: 策略UUID
        lookback_days: 回看窗口（默认60交易日）
        conn: psycopg2连接

    Returns:
        beta值。历史不足20天返回0.0。
    """
    # 读取策略NAV历史
    perf_df = pd.read_sql(
        """SELECT trade_date, nav
           FROM performance_series
           WHERE strategy_id = %s AND execution_mode = 'paper'
             AND trade_date <= %s
           ORDER BY trade_date DESC
           LIMIT %s""",
        conn,
        params=(strategy_id, trade_date, lookback_days + 1),
    )

    if len(perf_df) < 20:
        logger.info(
            f"[Beta] 历史数据不足({len(perf_df)}<20天), beta=0.0"
        )
        return 0.0

    perf_df = perf_df.sort_values("trade_date")
    strat_ret = perf_df["nav"].pct_change().dropna().values

    # 读取CSI300同期数据
    min_date = perf_df["trade_date"].min()
    bench_df = pd.read_sql(
        """SELECT trade_date, close
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date >= %s AND trade_date <= %s
           ORDER BY trade_date""",
        conn,
        params=(min_date, trade_date),
    )

    if len(bench_df) < 20:
        logger.warning("[Beta] 基准数据不足, beta=0.0")
        return 0.0

    bench_ret = bench_df["close"].pct_change().dropna().values

    # 对齐长度
    n = min(len(strat_ret), len(bench_ret))
    sr = strat_ret[-n:]
    br = bench_ret[-n:]

    # OLS: beta = cov(s,b) / var(b)
    cov_matrix = np.cov(sr, br)
    var_b = cov_matrix[1, 1]
    if var_b < 1e-10:
        return 0.0

    beta = float(cov_matrix[0, 1] / var_b)
    beta = np.clip(beta, -2.0, 2.0)

    logger.info(f"[Beta] {trade_date}: beta={beta:.3f} (n={n}天)")
    return beta


def apply_beta_hedge(
    target_weights: dict[str, float],
    beta: float,
) -> dict[str, float]:
    """对组合权重应用Beta对冲缩放。

    Phase 0简化方案: 当beta>0.3时，等比缩小所有持仓权重，
    将"多余"市场暴露转为现金。
    缩放因子 = max(0.5, 1.0 - max(0.0, beta - 0.3))

    例: beta=0.57 → scale=max(0.5, 1.0-0.27)=0.73 → 全部权重×0.73

    Args:
        target_weights: {code: weight} 原始目标权重
        beta: 组合beta值

    Returns:
        调整后的 {code: weight}
    """
    if not target_weights or beta <= 0.3:
        return dict(target_weights)

    scale = max(0.5, 1.0 - max(0.0, beta - 0.3))
    hedged = {code: w * scale for code, w in target_weights.items()}

    logger.info(
        f"[BetaHedge] beta={beta:.3f}, scale={scale:.3f}, "
        f"总权重 {sum(target_weights.values()):.3f} → {sum(hedged.values()):.3f}"
    )
    return hedged


def hedge_returns(
    strat_returns: pd.Series,
    bench_returns: pd.Series,
    window: int = 60,
) -> pd.Series:
    """对已有的日收益率序列做事后Beta对冲。

    用于回测分析，非Paper Trading实时使用。
    hedged_r[t] = strat_r[t] - beta[t] * bench_r[t]

    Args:
        strat_returns: 策略日收益率
        bench_returns: 基准日收益率
        window: rolling窗口

    Returns:
        对冲后日收益率
    """
    ci = strat_returns.index.intersection(bench_returns.index)
    sr = strat_returns.reindex(ci).values
    br = bench_returns.reindex(ci).values

    hedged = np.empty(len(sr))
    for i in range(len(sr)):
        s = max(0, i - window)
        _s = sr[s : i + 1]
        _b = br[s : i + 1]
        if len(_s) > 5:
            cov = np.cov(_s, _b)
            beta = cov[0, 1] / max(cov[1, 1], 1e-10)
            beta = np.clip(beta, -2.0, 2.0)
        else:
            beta = 0.0
        hedged[i] = sr[i] - beta * br[i]

    return pd.Series(hedged, index=ci)
