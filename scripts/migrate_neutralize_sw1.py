#!/usr/bin/env python3
"""一次性迁移脚本: 使用SW1(29组)重新计算所有factor_values.neutral_value。

DEPRECATED (P2-1 DATA_SYSTEM_V1 2026-04-17): SW1 迁移已完成 (2026-04-11).
本脚本为历史一次性工具, 不再 active. 新中性化统一走:
    orch = DataOrchestrator(start, end)
    orch.neutralize_factors(factor_list, incremental=True, validate=True)


背景: 原中性化使用industry_sw1(实际存SW2二级行业, 110组), 其中22组<10只导致WLS不稳定。
迁移到SW1一级行业(29组), 所有组≥11只。

方法: 逐因子 → 逐日批量重算 → COPY到temp表 → JOIN UPDATE回factor_values。
预计耗时: ~1-2小时(53因子, 442M行)。

用法:
    python scripts/migrate_neutralize_sw1.py                  # 全量
    python scripts/migrate_neutralize_sw1.py --factors turnover_mean_20 volatility_20  # 指定因子
    python scripts/migrate_neutralize_sw1.py --dry-run        # 只计算不写DB
"""

import argparse
import io
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from engines.fast_neutralize import _mad_winsorize, _wls_neutralize, _zscore_clip  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402
from app.services.industry_utils import apply_sw2_to_sw1  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_all_neutralized_factors(conn) -> list[str]:
    """获取所有有neutral_value的因子列表。"""
    cur = conn.cursor()
    cur.execute("""
        SELECT factor_name, COUNT(*) as n
        FROM factor_values
        WHERE neutral_value IS NOT NULL
        GROUP BY factor_name
        ORDER BY factor_name
    """)
    return [r[0] for r in cur.fetchall()]


def load_industry_sw1(conn) -> dict[str, str]:
    """加载SW1映射后的行业dict。"""
    cur = conn.cursor()
    cur.execute("SELECT code, industry_sw1 FROM symbols WHERE market = 'astock'")
    ind_sw2 = {r[0]: r[1] if r[1] and r[1] != "nan" else "其他" for r in cur.fetchall()}
    return apply_sw2_to_sw1(ind_sw2, conn)


def load_market_cap(conn, start_date: str, end_date: str) -> pd.DataFrame:
    """加载市值数据。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT code, trade_date, total_mv FROM daily_basic "
        "WHERE trade_date BETWEEN %s AND %s AND total_mv IS NOT NULL",
        (start_date, end_date),
    )
    df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "total_mv"])
    df["total_mv"] = df["total_mv"].astype(float)
    return df


def recalc_factor(
    conn,
    factor_name: str,
    ind_dict: dict[str, str],
    mv_lookup: pd.Series,
    dry_run: bool = False,
) -> int:
    """重算单个因子的neutral_value并UPDATE回DB。"""
    t0 = time.time()
    cur = conn.cursor()

    # 加载该因子的raw_value
    cur.execute(
        "SELECT code, trade_date, raw_value FROM factor_values "
        "WHERE factor_name = %s AND raw_value IS NOT NULL",
        (factor_name,),
    )
    rows = cur.fetchall()
    if not rows:
        logger.warning("  %s: 无数据", factor_name)
        return 0

    fdata = pd.DataFrame(rows, columns=["code", "trade_date", "raw_value"])
    fdata["raw_value"] = fdata["raw_value"].astype(float)
    logger.info("  %s: 加载 %d 行 (%.1fs)", factor_name, len(fdata), time.time() - t0)

    # 逐日计算neutral_value
    results = []
    n_dates = 0
    for dt, group in fdata.groupby("trade_date"):
        codes = group["code"].values
        values = group["raw_value"].values.copy()

        if len(values) < 10:
            continue

        industries = np.array([ind_dict.get(c, "其他") for c in codes])
        log_mv = np.array([np.log(mv_lookup.get((c, dt), np.nan) + 1) for c in codes])

        # Pipeline: MAD → WLS(SW1) → z-score
        values = _mad_winsorize(values)
        values = _wls_neutralize(values, industries, log_mv)
        values = _zscore_clip(values)

        for j, code in enumerate(codes):
            if not np.isnan(values[j]):
                results.append((code, dt, float(values[j])))
        n_dates += 1

    t_calc = time.time() - t0
    logger.info("  %s: %d天 → %d行 (%.1fs)", factor_name, n_dates, len(results), t_calc)

    if not results or dry_run:
        return len(results)

    # COPY到temp表 → JOIN UPDATE
    t_write = time.time()
    cur.execute("""
        CREATE TEMP TABLE _neutral_update (
            code VARCHAR(20),
            trade_date DATE,
            neutral_value DOUBLE PRECISION
        ) ON COMMIT DROP
    """)

    # 使用COPY批量写入temp表
    buf = io.StringIO()
    for code, dt, nv in results:
        buf.write(f"{code}\t{dt}\t{nv}\n")
    buf.seek(0)
    cur.copy_from(buf, "_neutral_update", columns=("code", "trade_date", "neutral_value"))

    # JOIN UPDATE
    cur.execute(
        """
        UPDATE factor_values fv
        SET neutral_value = nu.neutral_value
        FROM _neutral_update nu
        WHERE fv.code = nu.code
          AND fv.trade_date = nu.trade_date
          AND fv.factor_name = %s
    """,
        (factor_name,),
    )
    updated = cur.rowcount

    conn.commit()
    t_db = time.time() - t_write
    logger.info(
        "  %s: DB UPDATE %d行 (%.1fs), 总%.1fs", factor_name, updated, t_db, time.time() - t0
    )
    return updated


def main():
    parser = argparse.ArgumentParser(description="SW2→SW1中性化迁移")
    parser.add_argument("--factors", nargs="*", help="指定因子(默认全部)")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写DB")
    args = parser.parse_args()

    conn = get_sync_conn()
    t_start = time.time()

    # 获取因子列表
    if args.factors:
        factor_names = args.factors
    else:
        factor_names = get_all_neutralized_factors(conn)
    logger.info("待重算因子: %d个%s", len(factor_names), " (dry-run)" if args.dry_run else "")

    # 一次性加载共享数据
    logger.info("加载行业映射(SW1)...")
    ind_dict = load_industry_sw1(conn)
    logger.info("  SW1行业: %d只股票 → %d个组", len(ind_dict), len(set(ind_dict.values())))

    logger.info("加载市值数据...")
    mv_df = load_market_cap(conn, "2014-01-01", "2026-12-31")
    mv_lookup = mv_df.set_index(["code", "trade_date"])["total_mv"]
    logger.info("  市值: %d行", len(mv_df))
    del mv_df  # 释放内存

    # 逐因子重算
    total_updated = 0
    for i, fname in enumerate(factor_names):
        logger.info("[%d/%d] 处理 %s...", i + 1, len(factor_names), fname)
        try:
            n = recalc_factor(conn, fname, ind_dict, mv_lookup, dry_run=args.dry_run)
            total_updated += n
        except Exception as e:
            logger.error("  %s 失败: %s", fname, e)
            conn.rollback()

        # 进度报告
        elapsed = time.time() - t_start
        avg = elapsed / (i + 1)
        remaining = avg * (len(factor_names) - i - 1)
        logger.info(
            "  进度: %d/%d, 累计更新%d行, 已用%.0fs, 预计剩余%.0fs",
            i + 1,
            len(factor_names),
            total_updated,
            elapsed,
            remaining,
        )

    total_time = time.time() - t_start
    logger.info("=" * 60)
    logger.info(
        "迁移完成: %d因子, %d行更新, %.1f分钟", len(factor_names), total_updated, total_time / 60
    )

    conn.close()


if __name__ == "__main__":
    main()
