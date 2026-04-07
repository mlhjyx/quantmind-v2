"""对3个北向Active因子跑标准中性化pipeline + factor_profiler画像。

流程:
  1. 加载raw_value(已在factor_values中)
  2. 加载ln_mcap(daily_basic.circ_mv→ln)和行业(symbols.industry_sw1)
  3. 逐日跑preprocess_pipeline(MAD→fill→WLS→zscore→clip±3)
  4. 写入neutral_value/zscore
  5. 调用profile_factor()跑画像

用法:
    python scripts/neutralize_nb_factors.py
"""

import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

# 把backend加入path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.factor_engine import preprocess_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FACTORS = ["nb_increase_ratio_20d", "nb_new_entry", "nb_contrarian"]
CALC_START = date(2021, 1, 1)
CALC_END = date(2025, 12, 31)


def get_db_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


def load_industry_map(conn) -> pd.Series:
    """加载行业映射 {code: industry_sw1}。"""
    cur = conn.cursor()
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    rows = cur.fetchall()
    return pd.Series({r[0]: r[1] for r in rows if r[1]})


def load_ln_mcap(conn) -> pd.DataFrame:
    """加载 (trade_date, code) → ln(circ_mv) 面板。"""
    logger.info("加载市值数据...")
    cur = conn.cursor()
    cur.execute("""
        SELECT code, trade_date, circ_mv FROM daily_basic
        WHERE trade_date >= %s AND trade_date <= %s AND circ_mv IS NOT NULL AND circ_mv > 0
    """, (CALC_START, CALC_END))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["code", "trade_date", "circ_mv"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["circ_mv"] = df["circ_mv"].astype(float)
    df["ln_mcap"] = np.log(df["circ_mv"])
    pivot = df.pivot(index="trade_date", columns="code", values="ln_mcap")
    logger.info("  市值面板: %d天 × %d只", pivot.shape[0], pivot.shape[1])
    return pivot


def neutralize_factor(
    factor_name: str,
    conn,
    industry_map: pd.Series,
    ln_mcap_pivot: pd.DataFrame,
):
    """对单个因子逐日做标准预处理。"""
    logger.info("=== 中性化 %s ===", factor_name)
    cur = conn.cursor()

    # 加载raw_value
    cur.execute("""
        SELECT code, trade_date, raw_value FROM factor_values
        WHERE factor_name = %s AND trade_date >= %s AND trade_date <= %s
        AND raw_value IS NOT NULL
    """, (factor_name, CALC_START, CALC_END))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["code", "trade_date", "raw_value"])
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["raw_value"] = df["raw_value"].astype(float)

    # pivot
    fv_pivot = df.pivot(index="trade_date", columns="code", values="raw_value")
    logger.info("  raw面板: %d天 × %d只", fv_pivot.shape[0], fv_pivot.shape[1])

    # 逐月末日期中性化（跟画像对齐，月末截面）
    # 但为了完整性和画像计算，对所有日期都做中性化
    # 为效率，只对有足够数据的交易日做
    trade_dates = sorted(fv_pivot.index)
    batch_updates = []
    processed = 0
    skipped = 0

    for dt in trade_dates:
        raw_series = fv_pivot.loc[dt].dropna()
        if len(raw_series) < 50:
            skipped += 1
            continue

        # ln_mcap for this date
        if dt not in ln_mcap_pivot.index:
            skipped += 1
            continue
        mcap_series = ln_mcap_pivot.loc[dt].dropna()

        # 取交集
        common = raw_series.index.intersection(mcap_series.index).intersection(industry_map.index)
        if len(common) < 50:
            skipped += 1
            continue

        raw_aligned = raw_series[common]
        mcap_aligned = mcap_series[common]
        ind_aligned = industry_map[common]

        try:
            _, neutral = preprocess_pipeline(raw_aligned, mcap_aligned, ind_aligned)
        except Exception as e:
            if processed == 0:
                logger.warning("  %s preprocess失败: %s", dt.date(), str(e)[:60])
            skipped += 1
            continue

        # 收集更新
        for code in neutral.index:
            if not np.isnan(neutral[code]):
                batch_updates.append((
                    float(neutral[code]),  # neutral_value
                    float(neutral[code]),  # zscore (same as neutral after pipeline)
                    factor_name,
                    code,
                    dt.date(),
                ))

        processed += 1

        # 每100天批量写入
        if len(batch_updates) >= 50000:
            _flush_updates(conn, batch_updates)
            batch_updates = []

    # 写入剩余
    if batch_updates:
        _flush_updates(conn, batch_updates)

    logger.info(
        "  %s: 中性化完成, %d天处理, %d天跳过",
        factor_name, processed, skipped,
    )


def _flush_updates(conn, batch_updates):
    cur = conn.cursor()
    psycopg2.extras.execute_batch(
        cur,
        """UPDATE factor_values SET neutral_value = %s, zscore = %s
           WHERE factor_name = %s AND code = %s AND trade_date = %s""",
        batch_updates,
        page_size=1000,
    )
    conn.commit()
    logger.info("    写入%d条neutral_value", len(batch_updates))


def run_profiler(conn):
    """对3个因子跑factor_profiler画像。"""
    from engines.factor_profiler import _load_shared_data, profile_factor

    logger.info("=== 加载画像共享数据 ===")
    shared = _load_shared_data(conn)
    close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates = shared

    # 所有因子名（用于相关性计算）
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
    all_factors = [r[0] for r in cur.fetchall()]

    for fname in FACTORS:
        logger.info("--- 画像: %s ---", fname)
        try:
            p = profile_factor(
                fname,
                close_pivot,
                fwd_excess,
                csi_monthly,
                industry_map,
                trading_dates,
                conn=conn,
                all_factor_names=all_factors,
            )
            if "error" in p:
                logger.warning("  %s 画像失败: %s", fname, p["error"])
            else:
                logger.info(
                    "  %s: IC_20d=%.4f t=%.2f mono=%.3f regime_sens=%.3f template=%d",
                    fname,
                    p.get("ic_20d", 0),
                    p.get("ic_20d_tstat", 0),
                    p.get("monotonicity", 0),
                    p.get("regime_sensitivity", 0),
                    p.get("recommended_template", 0),
                )
                # 重点关注的6个指标
                logger.info(
                    "    optimal_horizon=%s mono_note=%s",
                    p.get("optimal_horizon_note", ""),
                    p.get("monotonicity_note", ""),
                )
                logger.info(
                    "    ic_bull=%.4f ic_bear=%.4f turnover=%.2f",
                    p.get("ic_bull", 0),
                    p.get("ic_bear", 0),
                    p.get("top_q_turnover", 0),
                )
                logger.info(
                    "    industry_neutral_ic=%.4f trigger=%s cost_feasible=%s",
                    p.get("ic_neutral_industry", 0),
                    p.get("trigger_type", ""),
                    p.get("cost_feasible", ""),
                )
        except Exception as e:
            logger.error("  %s 画像异常: %s", fname, str(e)[:120])


def main():
    conn = get_db_conn()

    # Step 1: 加载共享数据
    industry_map = load_industry_map(conn)
    ln_mcap_pivot = load_ln_mcap(conn)
    logger.info("行业映射: %d只, 市值面板: %d天", len(industry_map), len(ln_mcap_pivot))

    # Step 2: 逐因子中性化
    for fname in FACTORS:
        neutralize_factor(fname, conn, industry_map, ln_mcap_pivot)

    # Step 3: 跑画像
    run_profiler(conn)

    conn.close()
    logger.info("=== 全部完成 ===")


if __name__ == "__main__":
    main()
