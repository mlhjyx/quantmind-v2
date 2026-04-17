"""P0-6: 记录 10 minute 因子 neutral_value 的 IC 到 factor_ic_history.

铁律对齐:
- 铁律 17: 写入走 DataPipeline.ingest(FACTOR_IC_HISTORY)
- 铁律 19: IC 计算走 ic_calculator.compute_forward_excess_returns (统一口径)

因子 IC 以 T+1 买入 T+horizon 卖出的超额收益 (相对 CSI300) 为目标.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import pandas as pd  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("p0_record_ic")

MINUTE_FACTORS = [
    "high_freq_volatility_20", "volume_concentration_20", "volume_autocorr_20",
    "smart_money_ratio_20", "opening_volume_share_20", "closing_trend_strength_20",
    "vwap_deviation_20", "order_flow_imbalance_20", "intraday_momentum_20",
    "volume_price_divergence_20",
]
HORIZONS = [1, 5, 10, 20]
START_DATE = "2021-01-01"
END_DATE = "2025-12-31"


def build_ic_record(factor_name: str, ic_by_h: dict[int, pd.Series]) -> list[dict]:
    """将 per-horizon IC series 对齐到 trade_date 并生成 factor_ic_history 行."""
    # 取所有 horizon 的并集日期
    all_dates = sorted(set().union(*[s.index for s in ic_by_h.values()]))
    rows = []
    for d in all_dates:
        record = {
            "factor_name": factor_name,
            "trade_date": d.date() if hasattr(d, "date") else d,
            "ic_1d": ic_by_h.get(1, pd.Series()).get(d, None),
            "ic_5d": ic_by_h.get(5, pd.Series()).get(d, None),
            "ic_10d": ic_by_h.get(10, pd.Series()).get(d, None),
            "ic_20d": ic_by_h.get(20, pd.Series()).get(d, None),
        }
        # Pandas NaN → None
        for k, v in list(record.items()):
            if isinstance(v, float) and pd.isna(v):
                record[k] = None
        rows.append(record)
    return rows


def main():
    from engines.ic_calculator import (
        compute_forward_excess_returns,
        compute_ic_series,
        summarize_ic_stats,
    )

    from app.data_fetcher.contracts import FACTOR_IC_HISTORY
    from app.data_fetcher.pipeline import DataPipeline
    from app.services.data_orchestrator import DataOrchestrator

    t_all = time.time()
    logger.info(f"[P0-6] 10 minute factor IC  {START_DATE}..{END_DATE}")

    orch = DataOrchestrator(START_DATE, END_DATE)
    ctx = orch.shared_pool._ensure_loaded()
    benchmark_df = ctx.get("benchmark_df")
    if benchmark_df is None or benchmark_df.empty:
        raise RuntimeError("benchmark_df 为空, 检查 load_shared_context include_benchmark=True")
    # 避免 Decimal 类型参与算术
    for col in ("close", "open", "high", "low"):
        if col in benchmark_df.columns:
            benchmark_df[col] = benchmark_df[col].astype("float64")

    # 单次加载 price_df (adj_close)
    logger.info("[load] 加载 price_df (adj_close) ...")
    cur = orch._conn.cursor()
    # 复权价格: close * adj_factor (klines_daily 无 adj_close 列)
    cur.execute(
        """
        SELECT code, trade_date, close * COALESCE(adj_factor, 1.0) AS adj_close
        FROM klines_daily
        WHERE trade_date BETWEEN %s AND %s
          AND close IS NOT NULL
        """,
        (START_DATE, END_DATE),
    )
    price_rows = cur.fetchall()
    cur.close()
    price_df = pd.DataFrame(price_rows, columns=["code", "trade_date", "adj_close"])
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    price_df["adj_close"] = price_df["adj_close"].astype("float64")
    logger.info(f"  price_df: {len(price_df):,} rows")

    # forward returns 每个 horizon 算一次
    fwd_by_h = {}
    for h in HORIZONS:
        logger.info(f"[fwd] horizon={h}d ...")
        fwd_by_h[h] = compute_forward_excess_returns(
            price_df, benchmark_df, horizon=h,
            price_col="adj_close", benchmark_price_col="close",
        )

    # 对每因子计算 IC, 生成 factor_ic_history 行
    all_rows: list[dict] = []
    ic_summary: dict = {}
    for fn in MINUTE_FACTORS:
        t0 = time.time()
        logger.info(f"[ic] {fn} ...")
        nv = orch.get_neutral_values(fn)
        if nv.empty:
            logger.warning(f"  {fn}: 无 neutral_value, 跳过")
            continue
        nv["trade_date"] = pd.to_datetime(nv["trade_date"])
        factor_wide = nv.pivot_table(
            index="trade_date", columns="code", values="value", aggfunc="last",
        )

        ic_by_h: dict[int, pd.Series] = {}
        stats_by_h: dict[int, dict] = {}
        for h in HORIZONS:
            ic = compute_ic_series(factor_wide, fwd_by_h[h])
            ic_by_h[h] = ic
            stats_by_h[h] = summarize_ic_stats(ic)

        ic_summary[fn] = {
            f"ic_{h}d_mean": stats_by_h[h].get("mean") for h in HORIZONS
        }
        ic_summary[fn].update({
            f"ic_{h}d_ir": stats_by_h[h].get("ir") for h in HORIZONS
        })
        rows = build_ic_record(fn, ic_by_h)
        all_rows.extend(rows)
        logger.info(
            f"  {fn}: 20d IC mean={stats_by_h[20].get('mean',0):.4f} "
            f"IR={stats_by_h[20].get('ir',0):.3f} ({time.time()-t0:.1f}s)"
        )

    if not all_rows:
        logger.error("[FAIL] 无 IC 行可写入")
        sys.exit(1)

    # 写入 factor_ic_history (铁律 17)
    logger.info(f"[ingest] {len(all_rows):,} 行 → factor_ic_history via DataPipeline")
    df_ic = pd.DataFrame(all_rows)
    # trade_date 转 python date
    df_ic["trade_date"] = pd.to_datetime(df_ic["trade_date"]).dt.date
    pipeline = DataPipeline(orch._conn)
    ingest_result = pipeline.ingest(df_ic, FACTOR_IC_HISTORY)
    orch._conn.commit()
    logger.info(
        f"  ingest: valid={ingest_result.valid_rows} rejected={ingest_result.rejected_rows} "
        f"upserted={ingest_result.upserted_rows}"
    )

    # 存报告
    report = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "horizons": HORIZONS,
        "factors": MINUTE_FACTORS,
        "ic_summary": ic_summary,
        "ingest": {
            "total": ingest_result.total_rows,
            "valid": ingest_result.valid_rows,
            "rejected": ingest_result.rejected_rows,
            "upserted": ingest_result.upserted_rows,
            "reasons": ingest_result.reject_reasons,
        },
        "elapsed_sec": round(time.time() - t_all, 1),
    }
    out = REPO_ROOT / "reports" / f"p0_minute_neutral_ic_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info(f"[report] {out}")

    logger.info(f"[P0-6] done in {(time.time()-t_all)/60:.2f} min")


if __name__ == "__main__":
    main()
