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

import numpy as np
import pandas as pd

from app.services.db import get_sync_conn
from app.services.industry_utils import apply_sw2_to_sw1

logger = logging.getLogger(__name__)


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


def _update_db_neutral_values(
    conn,
    results: list[tuple],
    batch_size: int = 5000,
) -> int:
    """将中性化结果批量写入factor_values.neutral_value。

    使用COPY写入临时表 + UPDATE JOIN实现高效批量更新。
    比execute_values快10-50x（避免重复解析VALUES子句）。

    Args:
        conn: psycopg2连接
        results: [(code, trade_date, factor_name, neutral_value), ...]
        batch_size: 未使用，保留兼容性

    Returns:
        更新的总行数
    """
    import io

    cur = conn.cursor()
    total_updated = 0

    # 按年分批处理，减少单次事务大小和锁持有时间
    result_df = pd.DataFrame(results, columns=["code", "trade_date", "factor_name", "neutral_value"])
    result_df["year"] = pd.to_datetime(result_df["trade_date"]).dt.year

    for year, year_df in result_df.groupby("year"):
        t1 = time.time()
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"

        # Step 1: 创建临时表
        cur.execute("DROP TABLE IF EXISTS _tmp_neutral_update")
        cur.execute("""
            CREATE TEMP TABLE _tmp_neutral_update (
                code VARCHAR(20),
                trade_date DATE,
                factor_name VARCHAR(60),
                neutral_value NUMERIC
            )
        """)

        # Step 2: COPY写入临时表（比INSERT快100x）
        buf = io.StringIO()
        for _, row in year_df.iterrows():
            buf.write(f"{row['code']}\t{row['trade_date']}\t{row['factor_name']}\t{row['neutral_value']}\n")
        buf.seek(0)
        cur.copy_from(buf, "_tmp_neutral_update", columns=("code", "trade_date", "factor_name", "neutral_value"))

        # Step 2b: 临时表加索引加速JOIN
        cur.execute("CREATE INDEX ON _tmp_neutral_update (code, trade_date, factor_name)")

        # Step 3: UPDATE JOIN + trade_date范围约束（触发TimescaleDB chunk exclusion）
        # 没有trade_date BETWEEN → PG扫描全部119GB; 有了 → 只扫描该年的chunk (~10GB)
        cur.execute("""
            UPDATE factor_values AS fv
            SET neutral_value = tmp.neutral_value
            FROM _tmp_neutral_update AS tmp
            WHERE fv.code = tmp.code
              AND fv.trade_date = tmp.trade_date
              AND fv.factor_name = tmp.factor_name
              AND fv.trade_date BETWEEN %s AND %s
        """, (year_start, year_end))
        year_updated = cur.rowcount

        cur.execute("DROP TABLE IF EXISTS _tmp_neutral_update")
        conn.commit()
        total_updated += year_updated
        logger.info("  DB写入 %d年: %d行 (%.1fs)", year, year_updated, time.time() - t1)

    return total_updated


def fast_neutralize_batch(
    factor_names: list[str],
    start_date: str = "2021-01-01",
    end_date: str = "2025-12-31",
    conn=None,
    update_db: bool = True,
    write_parquet: bool = True,
) -> int:
    """对指定因子做批量中性化，写入factor_values.neutral_value。

    预处理流程（不可变）: 去极值(MAD 5σ) → WLS中性化(行业+市值) → z-score clip ±3

    Args:
        factor_names: 需要中性化的因子名列表
        start_date: 起始日期
        end_date: 结束日期
        conn: psycopg2连接（None则自动创建）
        update_db: 是否将结果UPDATE到factor_values.neutral_value（默认True）
        write_parquet: 是否写入cache/neutral_values.parquet（默认True）

    Returns:
        写入的总行数
    """
    own_conn = conn is None
    if own_conn:
        conn = get_sync_conn()

    t_start = time.time()

    # Step 1: 一次性加载因子值
    logger.info("加载%d个因子的raw_value (%s ~ %s)...", len(factor_names), start_date, end_date)
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

    # Step 2: 行业映射(SW2→SW1一级29组) + 市值
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    ind_dict_sw2 = {r[0]: r[1] if r[1] and r[1] != "nan" else "其他" for r in cur.fetchall()}
    ind_dict = apply_sw2_to_sw1(ind_dict_sw2, conn)

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

    # Step 4a: 写入DB（默认开启）
    if update_db:
        t_db = time.time()
        db_rows = _update_db_neutral_values(conn, results)
        logger.info("  DB更新: %d行 (%.1fs)", db_rows, time.time() - t_db)

    # Step 4b: 写入Parquet（可选）
    if write_parquet:
        import os

        cache_dir = os.path.join(os.path.dirname(__file__), "..", "..", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        output_path = os.path.join(cache_dir, "neutral_values.parquet")

        t2 = time.time()
        result_df = pd.DataFrame(results, columns=["code", "trade_date", "factor_name", "neutral_value"])
        result_df["trade_date"] = pd.to_datetime(result_df["trade_date"])

        # 增量合并：保留已有因子，更新/追加本次计算的因子
        if os.path.exists(output_path):
            existing = pd.read_parquet(output_path)
            existing = existing[~existing["factor_name"].isin(factor_names)]
            result_df = pd.concat([existing, result_df], ignore_index=True)

        result_df.to_parquet(output_path, index=False)
        logger.info("  Parquet写入: %s (%d行, %.1fs)", output_path, len(result_df), time.time() - t2)

    total_time = time.time() - t_start
    logger.info("中性化完成: %d行, %.1f分钟", len(results), total_time / 60)

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
