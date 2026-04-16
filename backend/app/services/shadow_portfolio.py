"""Shadow LightGBM Portfolio — 影子选股系统(实验用)。

从run_paper_trading.py提取(Step 6-A)。
运行在主策略旁边，失败不影响主流程。

用法:
    generate_shadow_lgbm_signals(trade_date, conn, dry_run=False)
    generate_shadow_lgbm_inertia(trade_date, conn, dry_run=False)
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from app.services.trading_calendar import get_next_trading_day

logger = logging.getLogger("paper_trading")


def _ensure_shadow_portfolio_table(conn) -> None:
    """确保shadow_portfolio表存在（幂等）。

    .. note:: **铁律 32 Class C 例外** (Phase D D2 audited 2026-04-16)

       本函数内部 ``conn.commit()`` 是 idempotent DDL bootstrap 例外:
       ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS`` 必须 commit
       才能让后续 SELECT/INSERT 看到表/索引. DDL 语句天然事务隔离, 与业务事务解耦.

       详见 ``docs/audit/F16_service_commit_audit.md`` §Class C exceptions.
    """
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS shadow_portfolio (
            id SERIAL PRIMARY KEY,
            strategy_name VARCHAR(50) NOT NULL,
            trade_date DATE NOT NULL,
            rebalance_date DATE NOT NULL,
            symbol_code VARCHAR(10) NOT NULL,
            predicted_score FLOAT,
            weight FLOAT NOT NULL,
            rank_in_portfolio INT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(strategy_name, trade_date, symbol_code)
        );
        CREATE INDEX IF NOT EXISTS idx_shadow_portfolio_date
            ON shadow_portfolio(trade_date);
    """)
    conn.commit()  # F16-classC — idempotent DDL bootstrap, see docstring


def _select_fold_model(trade_date: date) -> str:
    """根据trade_date选择对应的fold模型文件。"""
    model_dir = Path(__file__).resolve().parent.parent.parent.parent / "models" / "lgbm_walkforward"
    y, m = trade_date.year, trade_date.month

    if y <= 2022 or (y == 2023 and m <= 6):
        fold_id = 1
    elif y == 2023 and m >= 7:
        fold_id = 2
    elif y == 2024 and m <= 6:
        fold_id = 3
    elif y == 2024 and m >= 7:
        fold_id = 4
    elif y == 2025 and m <= 6:
        fold_id = 5
    elif y == 2025 and m >= 7:
        fold_id = 6
    else:
        fold_id = 7

    return str(model_dir / f"fold_{fold_id}.txt")


def _get_lgbm_scored_universe(
    trade_date: date,
    conn,
) -> tuple[pd.DataFrame | None, int]:
    """LightGBM预测+Universe过滤。"""
    import lightgbm as lgb

    SHADOW_TOP_N = 15
    FEATURE_NAMES = [
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
    ]

    model_path = _select_fold_model(trade_date)
    if not Path(model_path).exists():
        logger.warning("[SHADOW] 模型文件不存在: %s，跳过", model_path)
        return None, SHADOW_TOP_N

    model = lgb.Booster(model_file=model_path)
    logger.info("[SHADOW] 加载模型: %s", model_path)

    placeholders = ",".join(["%s"] * len(FEATURE_NAMES))
    df_factors = pd.read_sql(
        f"""SELECT code, factor_name, neutral_value
            FROM factor_values
            WHERE trade_date = %s
              AND factor_name IN ({placeholders})
              AND neutral_value IS NOT NULL""",
        conn,
        params=[trade_date, *FEATURE_NAMES],
    )

    if df_factors.empty:
        logger.warning("[SHADOW] %s 无因子数据，跳过", trade_date)
        return None, SHADOW_TOP_N

    df_wide = df_factors.pivot_table(
        index="code",
        columns="factor_name",
        values="neutral_value",
        aggfunc="first",
    ).reset_index()
    df_wide.columns.name = None

    missing = [f for f in FEATURE_NAMES if f not in df_wide.columns]
    if missing:
        logger.warning("[SHADOW] 缺少因子列: %s，跳过", missing)
        return None, SHADOW_TOP_N

    from engines.ml_engine import FeaturePreprocessor

    preprocessor = FeaturePreprocessor()
    preprocessor.fit(df_wide, FEATURE_NAMES)
    df_processed = preprocessor.transform(df_wide)

    X = df_processed[FEATURE_NAMES].values.astype("float32")
    scores = model.predict(X)
    df_processed["predicted_score"] = scores

    universe_df = pd.read_sql(
        """SELECT k.code FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           WHERE k.trade_date = %s AND k.volume > 0
             AND s.list_status = 'L' AND s.name NOT LIKE '%%ST%%'""",
        conn,
        params=(trade_date,),
    )
    universe_codes = set(universe_df["code"])
    df_eligible = df_processed[df_processed["code"].isin(universe_codes)].copy()

    if len(df_eligible) < SHADOW_TOP_N:
        logger.warning("[SHADOW] 可选股票不足: %d < %d，跳过", len(df_eligible), SHADOW_TOP_N)
        return None, SHADOW_TOP_N

    return df_eligible, SHADOW_TOP_N


def _write_shadow_portfolio(
    df_top: pd.DataFrame,
    strategy_name: str,
    trade_date: date,
    top_n: int,
    conn,
    dry_run: bool,
) -> None:
    """将Top-N写入shadow_portfolio表。

    铁律 32: 不在 Service 内 commit, 由调用方 (`generate_shadow_lgbm_*` ←
    `scripts/run_paper_trading.py`) 管理事务. Phase D D2b-2 (2026-04-16) 删除原
    line 183 的 ``conn.commit()``.
    """
    top_codes = df_top["code"].tolist()
    logger.info("[SHADOW] %s Top-%d: %s", strategy_name, top_n, ",".join(top_codes))

    if not dry_run:
        _ensure_shadow_portfolio_table(conn)
        next_td = get_next_trading_day(conn, trade_date)
        rebalance_date = next_td if next_td else trade_date

        cur = conn.cursor()
        for _, row in df_top.iterrows():
            cur.execute(
                """INSERT INTO shadow_portfolio
                       (strategy_name, trade_date, rebalance_date,
                        symbol_code, predicted_score, weight, rank_in_portfolio)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (strategy_name, trade_date, symbol_code)
                   DO UPDATE SET
                       predicted_score = EXCLUDED.predicted_score,
                       weight = EXCLUDED.weight,
                       rank_in_portfolio = EXCLUDED.rank_in_portfolio,
                       rebalance_date = EXCLUDED.rebalance_date,
                       created_at = NOW()""",
                (
                    strategy_name,
                    trade_date,
                    rebalance_date,
                    row["code"],
                    float(row["predicted_score"]),
                    float(row["weight"]),
                    int(row["rank_in_portfolio"]),
                ),
            )
        # 铁律 32 (Phase D D2b-2): commit 由调用方管理 (run_paper_trading.py 顶层)
        logger.info("[SHADOW] 写入shadow_portfolio(%s): %d行", strategy_name, len(df_top))


def generate_shadow_lgbm_signals(trade_date: date, conn, dry_run: bool = False) -> None:
    """影子LightGBM选股（Raw）。"""
    SHADOW_STRATEGY = "lgbm_5feat_default"
    logger.info("[SHADOW] 开始Raw LightGBM影子选股 %s", trade_date)

    df_eligible, top_n = _get_lgbm_scored_universe(trade_date, conn)
    if df_eligible is None:
        return

    df_top = df_eligible.nlargest(top_n, "predicted_score").copy()
    df_top["rank_in_portfolio"] = range(1, top_n + 1)
    df_top["weight"] = 1.0 / top_n

    _write_shadow_portfolio(df_top, SHADOW_STRATEGY, trade_date, top_n, conn, dry_run)


def generate_shadow_lgbm_inertia(trade_date: date, conn, dry_run: bool = False) -> None:
    """影子LightGBM+Inertia(0.7σ)选股。"""
    import numpy as np

    SHADOW_STRATEGY = "lgbm_inertia_07"
    BONUS_STD = 0.7
    logger.info("[SHADOW] 开始Inertia(0.7σ)影子选股 %s", trade_date)

    df_eligible, top_n = _get_lgbm_scored_universe(trade_date, conn)
    if df_eligible is None:
        return

    prev_holdings_df = pd.read_sql(
        """SELECT symbol_code FROM shadow_portfolio
           WHERE strategy_name = %s AND trade_date < %s
           ORDER BY trade_date DESC LIMIT %s""",
        conn,
        params=(SHADOW_STRATEGY, trade_date, top_n),
    )
    prev_holdings = set(prev_holdings_df["symbol_code"]) if not prev_holdings_df.empty else set()

    scores = df_eligible["predicted_score"].values.copy()
    cs_std = np.std(scores) if len(scores) > 1 else 1.0
    codes = df_eligible["code"].values
    for i, code in enumerate(codes):
        if code in prev_holdings:
            scores[i] += BONUS_STD * cs_std
    df_eligible = df_eligible.copy()
    df_eligible["predicted_score"] = scores

    df_top = df_eligible.nlargest(top_n, "predicted_score").copy()
    df_top["rank_in_portfolio"] = range(1, top_n + 1)
    df_top["weight"] = 1.0 / top_n

    _write_shadow_portfolio(df_top, SHADOW_STRATEGY, trade_date, top_n, conn, dry_run)
