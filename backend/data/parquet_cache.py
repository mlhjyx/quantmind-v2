"""回测数据Parquet缓存 — 替代pd.read_sql加载，10x提速。

按年分目录存储:
  cache/backtest/2014/price_data.parquet
  cache/backtest/2014/factor_data.parquet
  cache/backtest/2014/benchmark.parquet
  ...
  cache/backtest/cache_meta.json

用法:
    cache = BacktestDataCache()
    cache.build("2014-01-01", "2025-12-31", conn)  # 一次性构建
    data = cache.load("2021-01-01", "2025-12-31")   # 秒级加载
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import structlog
from engines.signal_engine import PAPER_TRADING_CONFIG

logger = structlog.get_logger(__name__)

CACHE_DIR = Path("cache/backtest")

# F71 fix (Phase E 2026-04-16): 从 PAPER_TRADING_CONFIG 读取, 不再硬编码.
# 铁律 34: 配置 single source of truth — pt_live.yaml → signal_engine.PAPER_TRADING_CONFIG.
CORE_FACTORS = tuple(PAPER_TRADING_CONFIG.factor_names)

# price_data SQL — 与run_backtest.py load_price_data()完全一致
PRICE_SQL = """
    WITH latest_af AS (
        SELECT DISTINCT ON (code) code, adj_factor AS latest_adj_factor
        FROM klines_daily WHERE adj_factor IS NOT NULL AND adj_factor > 0
        ORDER BY code, trade_date DESC
    )
    SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close,
           k.pre_close, k.volume, k.amount, k.up_limit, k.down_limit,
           COALESCE(k.adj_factor, 1.0) AS adj_factor,
           CASE WHEN laf.latest_adj_factor > 0
                THEN k.close * COALESCE(k.adj_factor, 1.0) / laf.latest_adj_factor
                ELSE k.close END AS adj_close,
           db.turnover_rate,
           COALESCE(ss.is_st, FALSE) AS is_st,
           COALESCE(ss.is_suspended, FALSE) AS is_suspended,
           COALESCE(ss.is_new_stock, FALSE) AS is_new_stock,
           ss.board
    FROM klines_daily k
    LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
    LEFT JOIN latest_af laf ON k.code = laf.code
    LEFT JOIN stock_status_daily ss ON k.code = ss.code AND k.trade_date = ss.trade_date
    WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
    ORDER BY k.trade_date, k.code
"""

# NOTE (Step 6-D, Fix 1): "raw_value" 列名是历史遗留 —
# 实际内容是 COALESCE(neutral_value, raw_value), 即 **WLS 中性化后的值**
# (中性化列 NULL 时才回退到真正的原始值)。run_hybrid_backtest() 在 runner.py
# 里靠 `df.rename(columns={"raw_value": "neutral_value"})` 兼容这一命名。
# 直接读 Parquet 的代码请参考 cache/backtest/SCHEMA.md 避免误解。
# 不改列名是为了保持 regression_test 基线 Parquet 的 hash 稳定。
FACTOR_SQL = """
    SELECT code, trade_date, factor_name,
           COALESCE(neutral_value, raw_value) as raw_value
    FROM factor_values
    WHERE factor_name IN %s AND trade_date BETWEEN %s AND %s
"""

BENCHMARK_SQL = """
    SELECT trade_date, close FROM index_daily
    WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
    ORDER BY trade_date
"""


class BacktestDataCache:
    """回测数据Parquet缓存管理。"""

    def __init__(self, cache_dir: Path | str = CACHE_DIR):
        self.cache_dir = Path(cache_dir)

    def build(
        self,
        start_date: str | date,
        end_date: str | date,
        conn,
        factors: tuple[str, ...] = CORE_FACTORS,
    ) -> dict:
        """从DB导出回测数据到Parquet（按年分目录）。

        Returns:
            dict with year → {price_rows, factor_rows, benchmark_rows}
        """
        start = _to_date(start_date)
        end = _to_date(end_date)
        stats = {}

        for year in range(start.year, end.year + 1):
            yr_start = max(start, date(year, 1, 1))
            yr_end = min(end, date(year, 12, 31))
            yr_dir = self.cache_dir / str(year)
            yr_dir.mkdir(parents=True, exist_ok=True)

            t0 = time.time()

            # Price data
            price_df = pd.read_sql(PRICE_SQL, conn, params=(yr_start, yr_end))
            if not price_df.empty and "trade_date" in price_df.columns:
                price_df["trade_date"] = pd.to_datetime(price_df["trade_date"]).dt.date
            price_df.to_parquet(yr_dir / "price_data.parquet", index=False)

            # Factor data
            factor_df = pd.read_sql(FACTOR_SQL, conn, params=(factors, yr_start, yr_end))
            if not factor_df.empty and "trade_date" in factor_df.columns:
                factor_df["trade_date"] = pd.to_datetime(factor_df["trade_date"]).dt.date
            factor_df.to_parquet(yr_dir / "factor_data.parquet", index=False)

            # Benchmark
            bench_df = pd.read_sql(BENCHMARK_SQL, conn, params=(yr_start, yr_end))
            if not bench_df.empty and "trade_date" in bench_df.columns:
                bench_df["trade_date"] = pd.to_datetime(bench_df["trade_date"]).dt.date
            bench_df.to_parquet(yr_dir / "benchmark.parquet", index=False)

            elapsed = time.time() - t0
            stats[year] = {
                "price_rows": len(price_df),
                "factor_rows": len(factor_df),
                "benchmark_rows": len(bench_df),
                "elapsed_sec": round(elapsed, 1),
            }
            logger.info(
                "%d: price=%d, factor=%d, bench=%d (%.1fs)",
                year,
                len(price_df),
                len(factor_df),
                len(bench_df),
                elapsed,
            )

        # Write meta
        meta = {
            "build_date": datetime.now().isoformat(),
            "start_date": str(start),
            "end_date": str(end),
            "factors": list(factors),
            "stats": stats,
        }
        with open(self.cache_dir / "cache_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        logger.info("Cache built: %d years, %s ~ %s", len(stats), start, end)
        return stats

    def load(
        self,
        start_date: str | date,
        end_date: str | date,
    ) -> dict[str, pd.DataFrame]:
        """从Parquet加载回测数据。

        Returns:
            {"price_data": df, "factor_data": df, "benchmark": df}
        """
        start = _to_date(start_date)
        end = _to_date(end_date)

        price_parts = []
        factor_parts = []
        bench_parts = []

        for year in range(start.year, end.year + 1):
            yr_dir = self.cache_dir / str(year)
            if not yr_dir.exists():
                raise FileNotFoundError(f"缓存不存在: {yr_dir}。请先运行 build_backtest_cache.py")

            price_parts.append(pd.read_parquet(yr_dir / "price_data.parquet"))
            factor_parts.append(pd.read_parquet(yr_dir / "factor_data.parquet"))
            bench_parts.append(pd.read_parquet(yr_dir / "benchmark.parquet"))

        price = pd.concat(price_parts, ignore_index=True)
        factor = pd.concat(factor_parts, ignore_index=True)
        bench = pd.concat(bench_parts, ignore_index=True)

        # 过滤到精确日期范围
        price = price[(price["trade_date"] >= start) & (price["trade_date"] <= end)]
        factor = factor[(factor["trade_date"] >= start) & (factor["trade_date"] <= end)]
        bench = bench[(bench["trade_date"] >= start) & (bench["trade_date"] <= end)]

        # 确保排序(与DB加载一致)
        price = price.sort_values(["trade_date", "code"]).reset_index(drop=True)
        factor = factor.sort_values(["trade_date", "code", "factor_name"]).reset_index(drop=True)
        bench = bench.sort_values("trade_date").reset_index(drop=True)

        logger.info(
            "Cache loaded: price=%d, factor=%d, bench=%d (%d years)",
            len(price),
            len(factor),
            len(bench),
            end.year - start.year + 1,
        )

        return {"price_data": price, "factor_data": factor, "benchmark": bench}

    def is_valid(self, start_date: str | date, end_date: str | date) -> bool:
        """检查缓存是否存在且覆盖请求的日期范围。"""
        start = _to_date(start_date)
        end = _to_date(end_date)

        meta_path = self.cache_dir / "cache_meta.json"
        if not meta_path.exists():
            return False

        for year in range(start.year, end.year + 1):
            if not (self.cache_dir / str(year) / "price_data.parquet").exists():
                return False

        return True

    def invalidate(self) -> None:
        """清除全部缓存。"""
        import shutil

        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Cache invalidated: %s", self.cache_dir)


def _to_date(d: str | date) -> date:
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d").date()
    return d
