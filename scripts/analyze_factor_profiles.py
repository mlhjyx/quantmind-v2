#!/usr/bin/env python3
"""因子画像分析 -- IC衰减、半衰期、推荐频率。

从DB读取Active因子，计算1/5/10/20日IC衰减曲线，
拟合半衰期并推荐调仓频率。

用法:
    python scripts/analyze_factor_profiles.py                    # 所有Active因子
    python scripts/analyze_factor_profiles.py --factors turnover_mean_20 volatility_20
    python scripts/analyze_factor_profiles.py --dry-run          # 只打印不写DB
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import numpy as np
import pandas as pd
from engines.factor_profile import FactorProfile
from scipy import stats

from app.services.price_utils import _get_sync_conn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# v1.1 因子元数据
FACTOR_META: dict[str, dict] = {
    "turnover_mean_20": {"category": "liquidity", "direction": -1, "tags": ["liquidity", "volume"]},
    "volatility_20": {"category": "price_volume", "direction": -1, "tags": ["volatility", "risk"]},
    "reversal_20": {"category": "price_volume", "direction": 1, "tags": ["reversal", "mean_reversion"]},
    "amihud_20": {"category": "liquidity", "direction": 1, "tags": ["illiquidity", "microstructure"]},
    "bp_ratio": {"category": "fundamental", "direction": 1, "tags": ["value", "fundamental"]},
}

HORIZONS = [1, 5, 10, 20]
START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)


def load_active_factors(conn) -> list[str]:
    """从factor_lifecycle表获取Active因子列表。"""
    df = pd.read_sql(
        "SELECT factor_name FROM factor_lifecycle WHERE status = 'active' ORDER BY factor_name",
        conn,
    )
    return df["factor_name"].tolist()


def load_factor_data(conn, factor_name: str) -> pd.DataFrame:
    """加载因子值（中性化后）。"""
    return pd.read_sql(
        """SELECT code, trade_date, neutral_value
           FROM factor_values
           WHERE factor_name = %s AND trade_date BETWEEN %s AND %s""",
        conn,
        params=(factor_name, START_DATE, END_DATE),
    )


def load_excess_returns(conn) -> pd.DataFrame:
    """加载超额收益（vs沪深300）。复用FactorAnalyzer的逻辑。"""
    stock_ret = pd.read_sql(
        """SELECT code, trade_date,
                  (close * adj_factor) /
                  LAG(close * adj_factor) OVER (PARTITION BY code ORDER BY trade_date) - 1
                  AS ret
           FROM klines_daily
           WHERE trade_date BETWEEN %s AND %s AND volume > 0
           ORDER BY trade_date, code""",
        conn,
        params=(START_DATE, END_DATE),
    )

    bench_ret = pd.read_sql(
        """SELECT trade_date,
                  close / LAG(close) OVER (ORDER BY trade_date) - 1 AS bench_ret
           FROM index_daily
           WHERE index_code = '000300.SH'
             AND trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        conn,
        params=(START_DATE, END_DATE),
    )

    if stock_ret.empty or bench_ret.empty:
        logger.error("行情或基准数据为空")
        return pd.DataFrame()

    merged = stock_ret.merge(bench_ret, on="trade_date", how="left")
    merged["excess_ret"] = merged["ret"] - merged["bench_ret"].fillna(0)
    return merged[["code", "trade_date", "excess_ret"]].dropna()


def calc_ic_decay(
    factor_df: pd.DataFrame,
    returns_df: pd.DataFrame,
    horizons: list[int],
) -> dict[int, float]:
    """计算IC衰减（不同持仓周期的IC均值）。

    复用FactorAnalyzer._calc_ic_decay的逻辑，采样以加速。

    Args:
        factor_df: 因子值DataFrame (code, trade_date, neutral_value)。
        returns_df: 超额收益DataFrame (code, trade_date, excess_ret)。
        horizons: 前向收益天数列表。

    Returns:
        {horizon: mean_ic} 映射。
    """
    from datetime import timedelta

    decay: dict[int, float] = {}
    dates = sorted(factor_df["trade_date"].unique())

    # 采样: 每5个交易日取1个截面，降低计算量
    sampled_dates = dates[::5]
    logger.info("IC衰减计算: %d个截面 (从%d个交易日采样)", len(sampled_dates), len(dates))

    for h in horizons:
        ic_values: list[float] = []

        for dt in sampled_dates:
            cross_section = factor_df[factor_df["trade_date"] == dt]
            future_end = dt + timedelta(days=int(h * 1.5))
            future_rets = returns_df[
                (returns_df["trade_date"] > dt) & (returns_df["trade_date"] <= future_end)
            ]
            if future_rets.empty:
                continue

            cum_ret = future_rets.groupby("code")["excess_ret"].sum()
            merged = cross_section.set_index("code")["neutral_value"].to_frame()
            merged = merged.join(cum_ret.rename("fwd_ret"), how="inner").dropna()

            if len(merged) < 30:
                continue

            ic, _ = stats.spearmanr(merged["neutral_value"], merged["fwd_ret"])
            if not np.isnan(ic):
                ic_values.append(float(ic))

        decay[h] = float(np.mean(ic_values)) if ic_values else 0.0

    return decay


def ensure_db_columns(conn) -> None:
    """确保factor_lifecycle表有扩展字段。"""
    cur = conn.cursor()
    alters = [
        "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'",
        "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS ic_decay JSONB",
        "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS half_life_days DECIMAL(8,2)",
        "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS recommended_freq VARCHAR(20)",
    ]
    for sql in alters:
        try:
            cur.execute(sql)
        except Exception as e:
            logger.warning("ALTER TABLE跳过: %s", e)
    conn.commit()
    cur.close()
    logger.info("DB字段检查完成")


def save_profiles(conn, profiles: list[FactorProfile]) -> None:
    """将画像写入factor_lifecycle表。"""
    cur = conn.cursor()
    for p in profiles:
        cur.execute(
            """UPDATE factor_lifecycle
               SET tags = %s,
                   ic_decay = %s,
                   half_life_days = %s,
                   recommended_freq = %s,
                   updated_at = CURRENT_TIMESTAMP
               WHERE factor_name = %s""",
            (
                json.dumps(p.tags),
                json.dumps({str(k): round(v, 6) for k, v in p.ic_decay.items()}),
                round(p.half_life_days, 2),
                p.recommended_freq,
                p.name,
            ),
        )
    conn.commit()
    cur.close()
    logger.info("写入 %d 个因子画像到DB", len(profiles))


def print_profiles(profiles: list[FactorProfile]) -> None:
    """打印因子画像表格。"""
    header = f"{'因子':<20s} | {'IC(1d)':>8s} | {'IC(5d)':>8s} | {'IC(10d)':>8s} | {'IC(20d)':>8s} | {'半衰期':>8s} | {'推荐频率':<10s}"
    sep = "-" * len(header)
    print()
    print(header)
    print(sep)
    for p in profiles:
        ic1 = p.ic_decay.get(1, 0.0)
        ic5 = p.ic_decay.get(5, 0.0)
        ic10 = p.ic_decay.get(10, 0.0)
        ic20 = p.ic_decay.get(20, 0.0)
        hl_str = f"{p.half_life_days:.1f}天"
        print(
            f"{p.name:<20s} | {ic1:>+8.4f} | {ic5:>+8.4f} | {ic10:>+8.4f} | {ic20:>+8.4f} | {hl_str:>8s} | {p.recommended_freq:<10s}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="因子画像分析")
    parser.add_argument("--factors", nargs="+", help="指定因子名称（默认所有Active）")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写DB")
    args = parser.parse_args()

    conn = _get_sync_conn()

    # 获取因子列表
    factor_names = args.factors or load_active_factors(conn)

    if not factor_names:
        logger.error("无Active因子")
        conn.close()
        return

    logger.info("分析因子: %s", factor_names)

    # 加载超额收益（全局共用）
    logger.info("加载超额收益数据 [%s, %s]...", START_DATE, END_DATE)
    returns_df = load_excess_returns(conn)
    if returns_df.empty:
        logger.error("超额收益数据为空，退出")
        conn.close()
        return
    logger.info("超额收益: %d行", len(returns_df))

    # 逐因子分析
    profiles: list[FactorProfile] = []
    for fname in factor_names:
        logger.info("分析因子: %s", fname)
        factor_df = load_factor_data(conn, fname)
        if factor_df.empty:
            logger.warning("因子 %s 无数据，跳过", fname)
            continue

        logger.info("  %s: %d行因子数据", fname, len(factor_df))

        ic_decay = calc_ic_decay(factor_df, returns_df, HORIZONS)

        meta = FACTOR_META.get(fname, {})
        profile = FactorProfile.from_ic_decay(
            name=fname,
            ic_decay=ic_decay,
            category=meta.get("category", ""),
            direction=meta.get("direction", 1),
            tags=meta.get("tags", []),
            status="active",
        )
        profiles.append(profile)

    if not profiles:
        logger.error("无因子画像生成")
        conn.close()
        return

    # 输出
    print_profiles(profiles)

    # 写入DB
    if not args.dry_run:
        ensure_db_columns(conn)
        save_profiles(conn, profiles)
        logger.info("画像已写入DB")
    else:
        logger.info("[DRY-RUN] 不写入DB")

    conn.close()
    logger.info("完成")


if __name__ == "__main__":
    main()
