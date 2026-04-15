# ruff: noqa: F401
# F401 disabled file-level: this __init__.py intentionally re-exports symbols from
# sub-modules (_constants / calculators / alpha158 / preprocess) to preserve the
# public API for 25 downstream import sites. Ruff can't distinguish intent-to-reexport
# from genuine unused imports in a package __init__, so we suppress the check.
"""因子计算引擎 — Phase 0 规则版因子管道。

流程: 读取行情 → 计算原始因子值 → 预处理(MAD→fill→neutralize→zscore) → 批量写入

严格遵守 CLAUDE.md 因子计算规则:
1. 预处理顺序不可调换: MAD去极值 → 缺失值填充 → 中性化 → 标准化
2. 按日期批量写入(单事务)
3. IC使用超额收益(vs CSI300)

Phase C C1 (2026-04-16) 纯计算拆分:
    原 backend/engines/factor_engine.py (2049 行) 按 铁律 31 拆分为 package:
    - `_constants.py`  — direction 字典 / 元数据 (pure data)
    - `calculators.py` — 30 个 calc_* 纯函数 (无 IO)
    - `alpha158.py`    — Alpha158 helpers (_alpha158_rolling + 3 wide-format)
    - `preprocess.py`  — preprocess_mad/fill/neutralize/zscore/pipeline + calc_ic
    - `__init__.py`    — 本文件, 兼容层 re-export + 未拆分的 IO/编排/lambda 注册表

Phase C C2 (2026-04-16) 数据加载拆分:
    load_* 全部搬家到 `backend/app/services/factor_repository.py`,
    __init__.py 通过 re-export 保留公共 API. calc_pead_q1 拆为:
    - `factor_repository.load_pead_announcements(conn, trade_date)` — DB 读取
    - `engines.factor_engine.pead.calc_pead_q1_from_announcements(df)` — 纯计算
    - 兼容层 wrapper `calc_pead_q1(trade_date, conn=None)` 组合上述两步.

    C3 (未执行) 将搬家 save_daily_factors/compute_daily_factors/compute_batch_factors
    → factor_compute_service + F86 known_debt 关闭

见: docs/audit/PHASE_C_F31_PREP.md
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import structlog

# Phase C C2 (2026-04-16): Data loaders re-exported from factor_repository.
# `calc_pead_q1` 保留本文件下方 wrapper, 内部走 repository + pead.py pure 函数.
from app.services.factor_repository import (
    load_bulk_data,
    load_bulk_data_with_extras,
    load_bulk_moneyflow,
    load_daily_data,
    load_forward_returns,
    load_fundamental_pit_data,
    load_index_returns,
    load_pead_announcements,
)

# ============================================================
# Re-export from sub-modules (C1 移出部分)
# ============================================================
from engines.factor_engine._constants import (
    ALPHA158_FACTOR_DIRECTION,
    FUNDAMENTAL_ALL_FEATURES,
    FUNDAMENTAL_DELTA_FEATURES,
    FUNDAMENTAL_DELTA_META,
    FUNDAMENTAL_FACTOR_DIRECTION,
    FUNDAMENTAL_TIME_FEATURES,
    FUNDAMENTAL_TIME_META,
    LGBM_V2_BASELINE_FACTORS,
    PEAD_FACTOR_DIRECTION,
    PHASE21_FACTOR_DIRECTION,
    RESERVE_FACTOR_DIRECTION,
)
from engines.factor_engine.alpha158 import (
    _alpha158_rolling,
    calc_alpha158_rsqr_resi,
    calc_alpha158_simple_four,
    calc_high_vol_price_ratio_wide,
)
from engines.factor_engine.calculators import (
    calc_amihud,
    calc_beta_market,
    calc_bp_ratio,
    calc_chmom,
    calc_ep_ratio,
    calc_gain_loss_ratio,
    calc_hl_range,
    calc_kbar_kmid,
    calc_kbar_ksft,
    calc_kbar_kup,
    calc_large_order_ratio,
    calc_ln_mcap,
    calc_maxret,
    calc_mf_divergence,
    calc_momentum,
    calc_money_flow_strength,
    calc_price_level,
    calc_pv_corr,
    calc_relative_volume,
    calc_reversal,
    calc_rsrs_raw,
    calc_stoch_rsv,
    calc_turnover_mean,
    calc_turnover_stability,
    calc_turnover_std,
    calc_turnover_surge_ratio,
    calc_up_days_ratio,
    calc_volatility,
    calc_volume_std,
    calc_vwap_bias,
)
from engines.factor_engine.pead import calc_pead_q1_from_announcements
from engines.factor_engine.preprocess import (
    calc_ic,
    preprocess_fill,
    preprocess_mad,
    preprocess_neutralize,
    preprocess_pipeline,
    preprocess_zscore,
)

logger = structlog.get_logger(__name__)


# ============================================================
# 因子注册表 (lambda 封装 calc_*, 未迁移到 submodule 以避免循环导入)
# ============================================================

# Phase 0 Week 3: 5 core factors (momentum_20 deprecated per factor评级报告)
PHASE0_CORE_FACTORS = {
    "volatility_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 20)
    ),
    "turnover_mean_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_mean(x, 20)
    ),
    "amihud_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_amihud(g["adj_close"], g["volume"], g["amount"], 20)
    ),
    "ln_market_cap": lambda df: calc_ln_mcap(df["total_mv"]),
    "bp_ratio": lambda df: calc_bp_ratio(df["pb"]),
}

# Phase 0 Week 6: 扩展因子 (不含deprecated)
PHASE0_FULL_FACTORS = {
    **PHASE0_CORE_FACTORS,
    # momentum_5/10 已移至DEPRECATED (与reversal_5/10数学等价, corr=-1.0)
    "reversal_5": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 5)
    ),
    "reversal_10": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 10)
    ),
    "reversal_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_reversal(x, 20)
    ),
    "ep_ratio": lambda df: calc_ep_ratio(df["pe_ttm"]),
    "price_volume_corr_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_pv_corr(g["adj_close"], g["volume"].astype(float), 20)
    ),
    # northbound_pct: Phase 1 (需要额外数据源 AKShare)
    # ---- v1.2 新增因子 ----
    "price_level_factor": lambda df: df.groupby("code")["close"].transform(
        lambda x: calc_price_level(x)
    ),
    "relative_volume_20": lambda df: df.groupby("code")["volume"].transform(
        lambda x: calc_relative_volume(x.astype(float), 60)
    ),
    "dv_ttm": lambda df: df["dv_ttm"].fillna(df.get("dv_ratio", 0)),  # fallback到dv_ratio
    "turnover_surge_ratio": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_surge_ratio(x)
    ),
}

# Deprecated因子 (factor评级报告确认, 从日常计算中移除)
# 原因: IC衰减/正交性不足/被更优因子替代
DEPRECATED_FACTORS = {
    "momentum_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 20)
    ),
    # momentum_5 = -reversal_5 (数学等价, corr=-1.000), 保留reversal_5在FULL
    "momentum_5": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 5)
    ),
    # momentum_10 = -reversal_10 (数学等价, corr=-1.000), 保留reversal_10在FULL
    "momentum_10": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_momentum(x, 10)
    ),
    "volatility_60": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_volatility(x, 60)
    ),
    "volume_std_20": lambda df: df.groupby("code")["volume"].transform(
        lambda x: calc_volume_std(x, 20)
    ),
    "turnover_std_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_std(x, 20)
    ),
    "high_low_range_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_hl_range(g["adj_high"], g["adj_low"], 20)
    ),
    # turnover_stability_20: corr(turnover_mean_20)=0.904, 高度冗余
    "turnover_stability_20": lambda df: df.groupby("code")["turnover_rate"].transform(
        lambda x: calc_turnover_stability(x, 20)
    ),
}

# 全量因子(含deprecated): 用于回测对比、历史分析
PHASE0_ALL_FACTORS = {**PHASE0_FULL_FACTORS, **DEPRECATED_FACTORS}

# Reserve池因子 (Sprint 1.6 Gate通过, 不入v1.1等权组合)
# 日常计算+写入factor_values, 用于监控IC/未来组合升级评估
RESERVE_FACTORS = {
    "vwap_bias_1d": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_vwap_bias(g["close"], g["amount"], g["volume"], 1)
    ),
    "rsrs_raw_18": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_rsrs_raw(g["high"], g["low"], 18)
    ),
    # turnover_stability_20 移至DEPRECATED (corr(turnover_mean_20)=0.904)
}

# ============================================================
# Alpha158因子注册表 (lambda 封装, 移植自原文件 550-605 行)
# 计算逻辑在 engines/alpha158_factors.py, 这里用lambda封装
# ============================================================

# 4个RANKING因子（月度调仓）
ALPHA158_RANKING = {
    "a158_std60": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["close"].rolling(60, min_periods=60).std() / g["close"]
    ),
    "a158_vsump60": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["volume"] - g["volume"].shift(1)).clip(lower=0).rolling(60, min_periods=60).sum()
            / ((g["volume"] - g["volume"].shift(1)).abs().rolling(60, min_periods=60).sum() + 1e-12)
        )
    ),
    "a158_cord30": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["close"] / g["close"].shift(1) - 1)
            .rolling(30, min_periods=30)
            .corr(np.log(g["volume"] / g["volume"].shift(1).replace(0, np.nan) + 1))
        )
    ),
    "a158_vstd30": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["volume"].rolling(30, min_periods=30).std() / (g["volume"] + 1e-12)
    ),
}

# 4个FAST_RANKING因子（周度/双周调仓）
ALPHA158_FAST_RANKING = {
    "a158_rank5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["close"] - g["close"].rolling(5, min_periods=5).min())
            / (
                g["close"].rolling(5, min_periods=5).max()
                - g["close"].rolling(5, min_periods=5).min()
                + 1e-12
            )
        )
    ),
    "a158_corr5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["close"].rolling(5, min_periods=5).corr(np.log(g["volume"] + 1))
    ),
    "a158_vsump5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: (
            (g["volume"] - g["volume"].shift(1)).clip(lower=0).rolling(5, min_periods=5).sum()
            / ((g["volume"] - g["volume"].shift(1)).abs().rolling(5, min_periods=5).sum() + 1e-12)
        )
    ),
    "a158_vma5": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: g["volume"].rolling(5, min_periods=5).mean() / (g["volume"] + 1e-12)
    ),
}

ALPHA158_FACTORS = {**ALPHA158_RANKING, **ALPHA158_FAST_RANKING}


# ============================================================
# PEAD因子 (Post-Earnings Announcement Drift, Q1季报限定)
# EVENT类型: 公告后7天内有效，非日频rolling
# 验证: Q1季报 spread=+1.19%, t=8.42, 最优窗口+7天
# H1/Q3/Y方向反转，禁止使用
# ============================================================
# Phase C C2 (2026-04-16): calc_pead_q1 兼容层 wrapper
# DB 读取走 factor_repository.load_pead_announcements
# 纯计算走 engines.factor_engine.pead.calc_pead_q1_from_announcements
# 保留原 (trade_date, conn=None) 签名, 25 个调用方无需修改


def calc_pead_q1(trade_date, conn=None) -> pd.Series:
    """PEAD Q1季报因子 — 公告后7天内的eps_surprise_pct。

    只使用report_type='Q1'的公告。同一股票取最近一条。
    超过7天的记录返回NaN（信号衰减）。

    Phase C C2 (2026-04-16): 内部已拆分为 (DB 读取 → repository) + (聚合 → pure 函数).
    本函数保留旧签名, 25 个历史调用方无需修改.

    Args:
        trade_date: 计算日期 (date或str)
        conn: psycopg2连接（None则自建, 调用方管理生命周期更好)

    Returns:
        pd.Series: index=code, values=eps_surprise_pct (正=超预期)
    """
    close_conn = conn is None
    if conn is None:
        from app.services.db import get_sync_conn

        conn = get_sync_conn()

    try:
        ann_df = load_pead_announcements(conn, trade_date, lookback_days=7)
    finally:
        if close_conn:
            conn.close()

    return calc_pead_q1_from_announcements(ann_df)


# ============================================================
# ML特征注册表 (Sprint 1.4b LightGBM 50+特征池)
# ============================================================
# 注意: 资金流因子和beta_market需要额外数据(moneyflow_daily / index_daily),
# 使用 load_bulk_data_with_extras 加载。普通因子只依赖 klines_daily + daily_basic。

# --- 仅依赖klines_daily + daily_basic的ML特征 ---
ML_FEATURES_KLINE = {
    # KBAR系列 (纯element-wise, 无需groupby)
    "kbar_kmid": lambda df: calc_kbar_kmid(df["open"], df["close"]),
    "kbar_ksft": lambda df: calc_kbar_ksft(df["open"], df["high"], df["low"], df["close"]),
    "kbar_kup": lambda df: calc_kbar_kup(df["open"], df["high"], df["close"]),
    # 动量衍生
    "maxret_20": lambda df: df.groupby("code")["adj_close"].transform(lambda x: calc_maxret(x, 20)),
    "chmom_60_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_chmom(x, 60, 20)
    ),
    "up_days_ratio_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_up_days_ratio(x, 20)
    ),
    # 技术指标 (不含beta, 不需要index数据)
    "stoch_rsv_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_stoch_rsv(g["adj_close"], g["adj_high"], g["adj_low"], 20)
    ),
    "gain_loss_ratio_20": lambda df: df.groupby("code")["adj_close"].transform(
        lambda x: calc_gain_loss_ratio(x, 20)
    ),
}

# --- 需要moneyflow_daily数据的ML特征 ---
ML_FEATURES_MONEYFLOW = {
    "mf_divergence": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_mf_divergence(g["adj_close"], g["net_mf_amount"].astype(float), 20)
    ),
    "large_order_ratio": lambda df: calc_large_order_ratio(
        df["buy_lg_amount"].astype(float),
        df["buy_elg_amount"].astype(float),
        df["buy_md_amount"].astype(float),
        df["buy_sm_amount"].astype(float),
    ),
    "money_flow_strength": lambda df: calc_money_flow_strength(
        df["net_mf_amount"].astype(float),
        df["total_mv"],
    ),
}

# --- 需要index_daily数据的ML特征 ---
ML_FEATURES_INDEX = {
    "beta_market_20": lambda df: df.groupby("code", group_keys=False).apply(
        lambda g: calc_beta_market(g["adj_close"].pct_change(1), g["index_ret"], 20)
    ),
}

# 全部ML特征 (合并三组)
ML_FEATURES = {**ML_FEATURES_KLINE, **ML_FEATURES_MONEYFLOW, **ML_FEATURES_INDEX}

# LightGBM完整特征集 = Phase0全量 + ML新特征 + Alpha158独立因子
LIGHTGBM_FEATURE_SET = {**PHASE0_FULL_FACTORS, **ML_FEATURES, **ALPHA158_FACTORS}


# ============================================================
# 数据加载 — Phase C C2 (2026-04-16) 全部搬家到 factor_repository
# 本文件通过上面的 re-export 保留公共 API.
# 历史符号:
#   load_fundamental_pit_data    — PIT 基本面 delta
#   load_daily_data              — 单日 klines+basic+symbols
#   load_forward_returns         — T+1→T+horizon 前瞻超额收益 (legacy)
#   load_bulk_data               — 区间 klines+basic+symbols
#   load_bulk_moneyflow          — 区间 moneyflow
#   load_index_returns           — 区间指数收益
#   load_bulk_data_with_extras   — bulk + moneyflow + index 合并
# ============================================================


# ============================================================
# 因子写入
# ============================================================


def save_daily_factors(
    trade_date: date,
    factor_df: pd.DataFrame,
    conn=None,
) -> int:
    """按日期批量写入因子值(通过DataPipeline，单事务)。

    CLAUDE.md强制要求: 一次事务写入当日全部股票×全部因子。
    Pipeline自动处理: inf/NaN→None + 验证 + upsert。
    factor_values跳过单位转换(skip_unit_conversion=True)。

    Args:
        trade_date: 交易日期
        factor_df: DataFrame with columns [code, factor_name, raw_value, neutral_value, zscore]
        conn: psycopg2连接

    Returns:
        写入行数
    """
    from app.data_fetcher.contracts import FACTOR_VALUES
    from app.data_fetcher.pipeline import DataPipeline
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 确保trade_date列存在
        df = factor_df.copy()
        if "trade_date" not in df.columns:
            df["trade_date"] = trade_date

        pipeline = DataPipeline(conn)
        result = pipeline.ingest(df, FACTOR_VALUES)

        if result.rejected_rows > 0:
            logger.warning(
                "[%s] factor_values: %d/%d rejected: %s",
                trade_date,
                result.rejected_rows,
                result.total_rows,
                result.reject_reasons,
            )

        logger.info("[%s] 写入因子 %d 行", trade_date, result.upserted_rows)
        return result.upserted_rows
    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


# ============================================================
# 主流程: 单日因子计算
# ============================================================


def compute_daily_factors(
    trade_date: date,
    factor_set: str = "core",
    conn=None,
    include_reserve: bool = True,
) -> pd.DataFrame:
    """计算单日全部因子。

    Args:
        trade_date: 交易日期
        factor_set: 'core'(5因子) / 'full'(不含deprecated) / 'all'(含deprecated,向后兼容)
        conn: 可选连接
        include_reserve: 是否包含Reserve池因子(默认True, 日常管道计算)

    Returns:
        DataFrame [code, factor_name, raw_value, neutral_value, zscore]
    """
    if factor_set == "core":
        factors = dict(PHASE0_CORE_FACTORS)
    elif factor_set == "all":
        logger.warning("factor_set='all' 包含deprecated因子，仅用于历史分析/对比")
        factors = dict(PHASE0_ALL_FACTORS)
    else:
        factors = dict(PHASE0_FULL_FACTORS)

    # Reserve池因子随日常管道一起计算(不入v1.1等权组合, 仅写入factor_values供监控)
    if include_reserve:
        factors.update(RESERVE_FACTORS)
        factors.update(ALPHA158_FACTORS)

    # 1. 加载数据
    logger.info(f"[{trade_date}] 加载行情数据...")
    df = load_daily_data(trade_date, lookback_days=120, conn=conn)

    if df.empty:
        logger.warning(f"[{trade_date}] 无数据，跳过")
        return pd.DataFrame()

    # 取当日截面
    today_mask = df["trade_date"] == trade_date
    if today_mask.sum() == 0:
        logger.warning(f"[{trade_date}] 当日无数据，跳过")
        return pd.DataFrame()

    today_codes = df.loc[today_mask, "code"].values
    today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
    today_industry.index = today_codes
    today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
    today_ln_mcap.index = today_codes

    # 2. 计算每个因子
    all_results = []

    for factor_name, calc_fn in factors.items():
        try:
            logger.debug(f"[{trade_date}] 计算因子: {factor_name}")

            # 计算原始值
            raw_series = calc_fn(df)

            # 取当日截面
            raw_today = raw_series[today_mask].copy()
            raw_today.index = today_codes

            # 预处理
            raw_val, neutral_val = preprocess_pipeline(raw_today, today_ln_mcap, today_industry)

            # 组装结果
            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                all_results.append(
                    {
                        "code": code,
                        "factor_name": factor_name,
                        "raw_value": rv,
                        "neutral_value": nv,
                        "zscore": nv,  # neutral_value已经是zscore
                    }
                )
        except Exception as e:
            logger.error(f"[{trade_date}] 因子 {factor_name} 计算失败: {e}")
            continue

    result_df = pd.DataFrame(all_results)
    logger.info(
        f"[{trade_date}] 计算完成: {len(factors)}因子 × {len(today_codes)}股 = {len(result_df)}行"
    )
    return result_df


# ============================================================
# 批量计算: 一次加载全量数据, 逐日计算+写入
# ============================================================


def compute_batch_factors(
    start_date: date,
    end_date: date,
    factor_set: str = "core",
    conn=None,
    write: bool = True,
    factor_names: list[str] | None = None,
) -> dict:
    """[DEPRECATED S2 F52] 批量计算因子并逐日写入.

    ⚠️ 此函数内部 (line ~2001) 直接 INSERT INTO factor_values, 绕过 DataPipeline,
    违反铁律 17. 仅被 `scripts/archive/calc_factors.py` 调用 (dead code).

    请使用 `compute_daily_factors()` + `save_daily_factors()` 组合 (走 DataPipeline).
    见 docs/audit/S2_consistency.md F52.

    高效模式: 一次加载全量数据 → 计算滚动因子 → 逐日预处理+写入。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        factor_set: 'core'/'full'/'all'/'ml'/'lgbm'/'fundamental'(8个PIT因子)/'lgbm_v2'(5基线+8基本面=13个)
        conn: 可选连接
        write: 是否写入数据库
        factor_names: 可选，只计算指定因子列表。None=计算全部。

    Returns:
        dict with stats (total_rows, elapsed, etc.)
    """
    import time
    import warnings

    from psycopg2.extras import execute_values

    warnings.warn(
        "compute_batch_factors is DEPRECATED (S2 F52, 2026-04-15). "
        "Direct INSERT bypasses DataPipeline (violates Iron Law 17). "
        "Use compute_daily_factors() + save_daily_factors() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    from app.services.price_utils import _get_sync_conn

    use_extras = False  # 是否需要加载moneyflow+index数据
    use_fundamental = False  # 是否需要加载PIT财务数据
    include_reserve = False  # Reserve池因子是否加入
    if factor_set == "core":
        factors = dict(PHASE0_CORE_FACTORS)
        include_reserve = True
    elif factor_set == "all":
        logger.warning("factor_set='all' 包含deprecated因子，仅用于历史分析/对比")
        factors = dict(PHASE0_ALL_FACTORS)
        include_reserve = True
    elif factor_set == "ml":
        factors = dict(ML_FEATURES)
        use_extras = True
    elif factor_set == "lgbm":
        factors = dict(LIGHTGBM_FEATURE_SET)
        use_extras = True
    elif factor_set == "fundamental":
        # 仅计算8个基本面+时间因子(不需要kline滚动因子)
        factors = {}
        use_fundamental = True
    elif factor_set == "lgbm_v2":
        # 5基线 + 6delta + 2时间 = 13个
        factors = {k: v for k, v in PHASE0_CORE_FACTORS.items() if k in LGBM_V2_BASELINE_FACTORS}
        # reversal_20 在 PHASE0_FULL_FACTORS 中
        if "reversal_20" not in factors:
            factors["reversal_20"] = PHASE0_FULL_FACTORS.get("reversal_20")
        use_fundamental = True
    else:
        factors = dict(PHASE0_FULL_FACTORS)
        include_reserve = True

    # Reserve池因子随日常管道一起计算(不入v1.1等权组合)
    if include_reserve:
        factors.update(RESERVE_FACTORS)
    if factor_names:
        factors = {k: v for k, v in factors.items() if k in factor_names}
        if not factors:
            logger.warning(f"指定的因子名 {factor_names} 在 {factor_set} 集中均未找到")
            return {
                "total_rows": 0,
                "elapsed": 0,
                "dates": 0,
                "load_time": 0,
                "calc_time": 0,
                "total_time": 0,
            }
        # 仅当实际需要moneyflow/index因子时才加载额外数据
        _mf_and_idx = set(ML_FEATURES_MONEYFLOW) | set(ML_FEATURES_INDEX)
        use_extras = use_extras and bool(set(factors) & _mf_and_idx)

    # 字符串→date转换（命令行调用时传入str）
    if isinstance(start_date, str):
        from datetime import datetime as _dt

        start_date = _dt.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        from datetime import datetime as _dt

        end_date = _dt.strptime(end_date, "%Y-%m-%d").date()

    if conn is None:
        conn = _get_sync_conn()

    t0 = time.time()

    # 1. 一次性加载全量数据 (kline因子需要)
    if factors:
        if use_extras:
            df = load_bulk_data_with_extras(start_date, end_date, conn=conn)
        else:
            df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return {
                "total_rows": 0,
                "elapsed": 0,
                "dates": 0,
                "load_time": 0,
                "calc_time": 0,
                "total_time": 0,
            }
    else:
        # fundamental-only模式: 仍需kline数据获取交易日列表和截面信息
        df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return {
                "total_rows": 0,
                "elapsed": 0,
                "dates": 0,
                "load_time": 0,
                "calc_time": 0,
                "total_time": 0,
            }

    t_load = time.time() - t0

    # 2. 一次性计算所有kline因子的滚动值
    logger.info(f"计算 {len(factors)} 个kline因子的滚动值...")
    factor_raw = {}
    for fname, calc_fn in factors.items():
        try:
            factor_raw[fname] = calc_fn(df)
        except Exception as e:
            logger.error(f"因子 {fname} 计算失败: {e}")

    t_calc = time.time() - t0 - t_load

    # 3. 获取计算范围内的交易日
    all_dates = sorted(
        df.loc[
            (df["trade_date"] >= start_date) & (df["trade_date"] <= end_date), "trade_date"
        ].unique()
    )

    n_fund = len(FUNDAMENTAL_ALL_FEATURES) if use_fundamental else 0
    logger.info(
        f"逐日预处理+写入: {len(all_dates)}个交易日"
        f"{f' (含{n_fund}个基本面因子)' if use_fundamental else ''}"
    )

    total_rows = 0
    for i, td in enumerate(all_dates):
        td_date = td.date() if hasattr(td, "date") else td

        # 取当日截面
        today_mask = df["trade_date"] == td
        if today_mask.sum() == 0:
            continue

        today_codes = df.loc[today_mask, "code"].values
        today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
        today_industry.index = today_codes
        today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
        today_ln_mcap.index = today_codes

        def _safe(v):
            """将NaN/inf转为None。"""
            if pd.isna(v):
                return None
            fv = float(v)
            return None if not np.isfinite(fv) else fv

        # 逐因子预处理 (kline因子)
        day_rows = []
        for fname in factor_raw:
            raw_today = factor_raw[fname][today_mask].copy()
            raw_today.index = today_codes

            raw_val, neutral_val = preprocess_pipeline(raw_today, today_ln_mcap, today_industry)

            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                day_rows.append(
                    (
                        code,
                        td_date,
                        fname,
                        _safe(rv),
                        _safe(nv),
                        _safe(nv),
                    )
                )

        # 基本面delta因子 (PIT加载, 逐日计算)
        if use_fundamental:
            try:
                fund_data = load_fundamental_pit_data(td_date, conn)
                for fname, raw_series in fund_data.items():
                    if raw_series.empty:
                        continue
                    # 对齐到当日截面的code集合
                    raw_aligned = raw_series.reindex(today_codes)

                    raw_val, neutral_val = preprocess_pipeline(
                        raw_aligned, today_ln_mcap, today_industry
                    )

                    for code in today_codes:
                        rv = raw_val.get(code, np.nan)
                        nv = neutral_val.get(code, np.nan)
                        day_rows.append(
                            (
                                code,
                                td_date,
                                fname,
                                _safe(rv),
                                _safe(nv),
                                _safe(nv),
                            )
                        )
            except Exception as e:
                logger.error(f"[{td_date}] 基本面因子计算失败: {e}")

        # 写入当日所有因子(单事务)
        if write and day_rows:
            with conn.cursor() as cur:
                execute_values(
                    cur,
                    """INSERT INTO factor_values
                       (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                       VALUES %s
                       ON CONFLICT (code, trade_date, factor_name)
                       DO UPDATE SET raw_value = EXCLUDED.raw_value,
                                     neutral_value = EXCLUDED.neutral_value,
                                     zscore = EXCLUDED.zscore""",
                    day_rows,
                    page_size=5000,
                )
            conn.commit()

        total_rows += len(day_rows)
        if (i + 1) % 50 == 0 or i == 0 or i == len(all_dates) - 1:
            elapsed = time.time() - t0
            logger.info(
                f"  [{i + 1}/{len(all_dates)}] {td_date} | "
                f"{len(day_rows)}行 | 累计{total_rows}行 | "
                f"{elapsed:.0f}s"
            )

    elapsed = time.time() - t0
    stats = {
        "total_rows": total_rows,
        "dates": len(all_dates),
        "load_time": round(t_load, 1),
        "calc_time": round(t_calc, 1),
        "total_time": round(elapsed, 1),
    }
    logger.info(
        f"批量因子计算完成: {stats['dates']}天, {total_rows}行, "
        f"加载{t_load:.0f}s + 计算{t_calc:.0f}s + 总计{elapsed:.0f}s"
    )
    return stats
