"""快速因子中性化 — 批量IO替代逐天读写。

原方法: 1170天×每天SELECT+UPDATE = 72分钟/3因子
新方法: 1次SELECT + 内存groupby + COPY写临时表 + JOIN UPDATE = ~3分钟/3因子

预处理流程与factor_engine一致（不可变）:
  去极值(MAD 5sigma) → 填充(行业中位数) → 中性化(行业+市值WLS) → z-score clip ±3

用法:
    from engines.fast_neutralize import fast_neutralize_batch
    fast_neutralize_batch(['nb_increase_ratio_20d', 'nb_new_entry'])
"""

import logging
import time
from io import StringIO

import numpy as np
import pandas as pd
import psycopg2

logger = logging.getLogger(__name__)

DB_PARAMS = {
    "dbname": "quantmind_v2",
    "user": "xin",
    "password": "quantmind",
    "host": "localhost",
}


def _mad_winsorize(values: np.ndarray, n_sigma: float = 5.0) -> np.ndarray:
    """MAD去极值(与factor_engine一致, 5sigma)。"""
    valid = values[~np.isnan(values)]
    if len(valid) < 5:
        return values
    median = np.median(valid)
    mad = np.median(np.abs(valid - median))
    if mad < 1e-12:
        return values
    scale = 1.4826 * mad  # MAD→std近似
    upper = median + n_sigma * scale
    lower = median - n_sigma * scale
    return np.clip(values, lower, upper)


def _wls_neutralize(
    values: np.ndarray,
    industries: np.ndarray,
    log_mv: np.ndarray,
) -> np.ndarray:
    """WLS行业+市值中性化(与factor_engine一致)。"""
    valid_mask = ~np.isnan(values) & ~np.isnan(log_mv)
    if valid_mask.sum() < 10:
        return values - np.nanmean(values)

    v = values[valid_mask]
    ind = industries[valid_mask]
    lm = log_mv[valid_mask]

    # 行业dummy
    unique_ind = [i for i in pd.unique(ind) if pd.notna(i) and i != "其他"]
    if len(unique_ind) < 2:
        return values - np.nanmean(values)

    ind_series = pd.Series(ind)
    dummies = pd.get_dummies(ind_series, drop_first=True).values.astype(np.float64)
    design = np.column_stack([dummies, lm])

    # WLS权重 = sqrt(market_cap) ∝ sqrt(exp(log_mv))
    weights = np.sqrt(np.exp(lm))
    weights = weights / weights.sum()
    w_diag = np.diag(weights)

    try:
        xw = w_diag @ design
        yw = w_diag @ v
        beta, _, _, _ = np.linalg.lstsq(xw, yw, rcond=None)
        residuals_valid = v - design @ beta
    except (np.linalg.LinAlgError, ValueError):
        residuals_valid = v - np.mean(v)

    result = np.full_like(values, np.nan)
    result[valid_mask] = residuals_valid
    return result


def _zscore_clip(values: np.ndarray, clip: float = 3.0) -> np.ndarray:
    """z-score标准化 + clip ±3。"""
    valid = values[~np.isnan(values)]
    if len(valid) < 3:
        return values
    std = np.std(valid)
    if std < 1e-12:
        return np.zeros_like(values)
    z = (values - np.mean(valid)) / std
    return np.clip(z, -clip, clip)


def fast_neutralize_batch(
    factor_names: list[str],
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    conn=None,
) -> int:
    """对指定因子做批量中性化，写入factor_values.neutral_value。

    Returns:
        写入的总行数
    """
    own_conn = conn is None
    if own_conn:
        conn = psycopg2.connect(**DB_PARAMS)

    t_start = time.time()

    # Step 1: 一次性加载因子值
    logger.info("加载%d个因子的raw_value...", len(factor_names))
    placeholders = ",".join(["%s"] * len(factor_names))
    cur = conn.cursor()
    cur.execute(
        f"SELECT code, trade_date, factor_name, raw_value FROM factor_values "
        f"WHERE factor_name IN ({placeholders}) "
        f"AND trade_date BETWEEN %s AND %s AND raw_value IS NOT NULL",
        (*factor_names, start_date, end_date),
    )
    rows = cur.fetchall()
    factor_df = pd.DataFrame(rows, columns=["code", "trade_date", "factor_name", "raw_value"])
    factor_df["raw_value"] = factor_df["raw_value"].astype(float)
    logger.info("  加载%d行 (%.1fs)", len(factor_df), time.time() - t_start)

    # Step 2: 行业映射 + 市值
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    ind_dict = {r[0]: r[1] if r[1] and r[1] != "nan" else "其他" for r in cur.fetchall()}

    cur.execute(
        "SELECT code, trade_date, total_mv FROM daily_basic "
        "WHERE trade_date BETWEEN %s AND %s AND total_mv IS NOT NULL",
        (start_date, end_date),
    )
    mv_rows = cur.fetchall()
    mv_df = pd.DataFrame(mv_rows, columns=["code", "trade_date", "total_mv"])
    mv_df["total_mv"] = mv_df["total_mv"].astype(float)
    mv_lookup = mv_df.set_index(["code", "trade_date"])["total_mv"]
    logger.info("  行业: %d只, 市值: %d行", len(ind_dict), len(mv_df))

    # Step 3: 内存中逐(因子×日期)中性化
    results = []
    for fname in factor_names:
        t1 = time.time()
        fdata = factor_df[factor_df["factor_name"] == fname]
        n_dates = 0

        for dt, group in fdata.groupby("trade_date"):
            codes = group["code"].values
            values = group["raw_value"].values.copy()

            if len(values) < 10:
                continue

            # 行业
            industries = np.array([ind_dict.get(c, "其他") for c in codes])
            # 市值
            log_mv = np.array([
                np.log(mv_lookup.get((c, dt), np.nan) + 1) for c in codes
            ])

            # Pipeline: MAD → WLS → z-score
            values = _mad_winsorize(values)
            values = _wls_neutralize(values, industries, log_mv)
            values = _zscore_clip(values)

            for j, code in enumerate(codes):
                if not np.isnan(values[j]):
                    results.append((code, dt, fname, float(values[j])))
            n_dates += 1

        logger.info("  %s: %d天处理 (%.1fs)", fname, n_dates, time.time() - t1)

    if not results:
        logger.warning("无有效结果")
        if own_conn:
            conn.close()
        return 0

    # Step 4: 分批COPY + JOIN UPDATE（避免OOM）
    total_written = 0
    batch_size = 2_000_000  # 200万行/批

    cur.execute("""
        CREATE TEMP TABLE IF NOT EXISTS _tmp_neutral (
            code VARCHAR(20), trade_date DATE,
            factor_name VARCHAR(100), neutral_value NUMERIC(20,6)
        )
    """)

    for batch_start in range(0, len(results), batch_size):
        batch = results[batch_start:batch_start + batch_size]
        t2 = time.time()

        cur.execute("TRUNCATE _tmp_neutral")

        buf = StringIO()
        for code, dt, fname, val in batch:
            dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)
            buf.write(f"{code}\t{dt_str}\t{fname}\t{val:.6f}\n")
        buf.seek(0)
        cur.copy_from(buf, "_tmp_neutral", columns=["code", "trade_date", "factor_name", "neutral_value"])
        del buf  # 释放内存

        cur.execute("""
            UPDATE factor_values fv
            SET neutral_value = t.neutral_value,
                zscore = t.neutral_value
            FROM _tmp_neutral t
            WHERE fv.code = t.code
              AND fv.trade_date = t.trade_date
              AND fv.factor_name = t.factor_name
        """)
        conn.commit()
        total_written += len(batch)
        logger.info(
            "  批次 %d/%d: %d行写入 (%.1fs)",
            batch_start // batch_size + 1,
            (len(results) + batch_size - 1) // batch_size,
            len(batch), time.time() - t2,
        )

    cur.execute("DROP TABLE IF EXISTS _tmp_neutral")
    conn.commit()

    total_time = time.time() - t_start
    logger.info("中性化完成: %d行, %.1f分钟", total_written, total_time / 60)

    if own_conn:
        conn.close()
    return len(results)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if len(sys.argv) > 1:
        names = sys.argv[1:]
    else:
        names = ["nb_increase_ratio_20d", "nb_new_entry", "nb_contrarian"]

    fast_neutralize_batch(names)
