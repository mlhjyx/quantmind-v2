"""Minute-bars Parquet cache — 分钟级数据高效加载模块。

191M行minute_bars按年分区存储:
  cache/minute_bars/minute_bars_2019.parquet
  cache/minute_bars/minute_bars_2020.parquet
  ...
  cache/minute_bars/cache_meta.json

用法:
    from minute_data_loader import MinuteDataCache
    cache = MinuteDataCache()

    # 首次: 从DB构建Parquet缓存 (~10min)
    cache.build()

    # 后续: 直接加载 (~30s/年)
    df = cache.load_year(2025)           # 加载单年
    df = cache.load_range(2023, 2025)    # 加载多年

Phase 3E微结构因子研究专用。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# 设置backend路径以使用get_sync_conn
sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

CACHE_DIR = Path("cache/minute_bars")

# minute_bars表的列 (drop id, adjustflag)
_COLUMNS = [
    "code", "trade_date", "trade_time",
    "open", "high", "low", "close",
    "volume", "amount",
]

# A股交易时段: 9:30-11:30 (24 bars) + 13:00-15:00 (24 bars) = 48 bars/day
# 5分钟bar的trade_time范围: 09:35:00 ~ 15:00:00
BARS_PER_DAY = 48

# 分块读取大小
CHUNK_SIZE = 1_000_000


class MinuteDataCache:
    """分钟级K线Parquet缓存管理。"""

    def __init__(self, cache_dir: Path | str = CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        start_year: int = 2019,
        end_year: int = 2026,
        *,
        force: bool = False,
    ) -> dict:
        """从DB导出minute_bars到Parquet（按年分区）。

        Args:
            start_year: 起始年份
            end_year: 结束年份（含）
            force: True时覆盖已有缓存

        Returns:
            dict: year → {rows, stocks, days, elapsed_sec, file_mb}
        """
        from app.services.db import get_sync_conn

        stats = {}
        conn = get_sync_conn()
        try:
            cur = conn.cursor()
            for year in range(start_year, end_year + 1):
                out_path = self.cache_dir / f"minute_bars_{year}.parquet"
                if out_path.exists() and not force:
                    # 已有缓存，读meta检查
                    file_mb = out_path.stat().st_size / 1024**2
                    print(f"  {year}: cached ({file_mb:.0f}MB), skip (use --force to rebuild)")
                    stats[year] = {"cached": True, "file_mb": round(file_mb, 1)}
                    continue

                t0 = time.time()
                yr_start = f"{year}-01-01"
                yr_end = f"{year}-12-31"

                # 分块读取避免内存爆炸
                sql = f"""
                    SELECT code, trade_date, trade_time,
                           open, high, low, close, volume, amount
                    FROM minute_bars
                    WHERE trade_date BETWEEN '{yr_start}' AND '{yr_end}'
                    ORDER BY trade_date, code, trade_time
                """
                print(f"  {year}: loading from DB...", end="", flush=True)

                chunks = []
                cur.execute(sql)
                while True:
                    rows = cur.fetchmany(CHUNK_SIZE)
                    if not rows:
                        break
                    chunk = pd.DataFrame(rows, columns=_COLUMNS)
                    # 立即转类型避免Decimal object列OOM
                    for col in ["open", "high", "low", "close", "amount"]:
                        chunk[col] = pd.to_numeric(chunk[col], errors="coerce").astype(np.float32)
                    chunk["volume"] = pd.to_numeric(chunk["volume"], errors="coerce").astype(np.int64)
                    chunks.append(chunk)
                    print(".", end="", flush=True)

                if not chunks:
                    print(" empty (0 rows)")
                    stats[year] = {"rows": 0}
                    continue

                df = pd.concat(chunks, ignore_index=True)
                del chunks

                # 类型优化 (日期类)
                df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
                df["trade_time"] = pd.to_datetime(df["trade_time"])

                # 添加minute_of_day (0-47)
                df["minute_of_day"] = _compute_minute_index(df["trade_time"])

                # 写Parquet
                df.to_parquet(out_path, index=False, engine="pyarrow")
                file_mb = out_path.stat().st_size / 1024**2
                elapsed = time.time() - t0

                n_stocks = df["code"].nunique()
                n_days = df["trade_date"].nunique()
                stats[year] = {
                    "rows": len(df),
                    "stocks": n_stocks,
                    "days": n_days,
                    "elapsed_sec": round(elapsed, 1),
                    "file_mb": round(file_mb, 1),
                }
                print(f" {len(df):,} rows, {n_stocks} stocks, {n_days} days, "
                      f"{file_mb:.0f}MB, {elapsed:.1f}s")
                del df
        finally:
            conn.close()

        # 写meta
        meta = {
            "build_date": datetime.now().isoformat(),
            "start_year": start_year,
            "end_year": end_year,
            "stats": {str(k): v for k, v in stats.items()},
        }
        with open(self.cache_dir / "cache_meta.json", "w") as f:
            json.dump(meta, f, indent=2)

        total_rows = sum(s.get("rows", 0) for s in stats.values())
        print(f"\nCache built: {len(stats)} years, {total_rows:,} total rows")
        return stats

    def load_year(self, year: int) -> pd.DataFrame:
        """加载单年分钟数据。

        Returns:
            DataFrame with columns: code, trade_date, trade_time,
            open, high, low, close, volume, amount, minute_of_day
        """
        path = self.cache_dir / f"minute_bars_{year}.parquet"
        if not path.exists():
            raise FileNotFoundError(
                f"No cache for {year}. Run: python minute_data_loader.py --build"
            )
        t0 = time.time()
        df = pd.read_parquet(path)
        # 确保date类型
        if hasattr(df["trade_date"].dtype, "tz") or df["trade_date"].dtype == "datetime64[ns]":
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        elapsed = time.time() - t0
        mem_mb = df.memory_usage(deep=True).sum() / 1024**2
        print(f"  Loaded {year}: {len(df):,} rows, {mem_mb:.0f}MB, {elapsed:.1f}s")
        return df

    def load_range(self, start_year: int, end_year: int) -> pd.DataFrame:
        """加载多年分钟数据（逐年拼接）。

        警告: 多年数据可能超过内存限制。建议逐年处理。
        """
        parts = []
        for year in range(start_year, end_year + 1):
            path = self.cache_dir / f"minute_bars_{year}.parquet"
            if path.exists():
                parts.append(self.load_year(year))
        if not parts:
            raise FileNotFoundError(f"No cache for {start_year}-{end_year}")
        return pd.concat(parts, ignore_index=True)

    def years_available(self) -> list[int]:
        """返回已缓存的年份列表。"""
        years = []
        for f in sorted(self.cache_dir.glob("minute_bars_*.parquet")):
            try:
                yr = int(f.stem.split("_")[-1])
                years.append(yr)
            except ValueError:
                pass
        return years

    def verify(self, year: int) -> dict:
        """验证缓存数据质量。"""
        df = self.load_year(year)
        n_stocks = df["code"].nunique()
        n_days = df["trade_date"].nunique()

        # 检查每天每股是否有48 bars
        bars_per_stock_day = df.groupby(["code", "trade_date"]).size()
        full_bars = (bars_per_stock_day == BARS_PER_DAY).mean()
        short_bars = bars_per_stock_day[bars_per_stock_day < BARS_PER_DAY]

        # 检查空值
        null_counts = df[["open", "high", "low", "close", "volume", "amount"]].isnull().sum()

        # 检查minute_of_day范围
        mod_range = (df["minute_of_day"].min(), df["minute_of_day"].max())

        result = {
            "year": year,
            "total_rows": len(df),
            "stocks": n_stocks,
            "days": n_days,
            "bars_48_pct": round(full_bars * 100, 2),
            "short_bars_count": len(short_bars),
            "null_counts": null_counts.to_dict(),
            "minute_of_day_range": mod_range,
            "mem_mb": round(df.memory_usage(deep=True).sum() / 1024**2, 0),
        }

        print(f"\n=== Verify {year} ===")
        print(f"  Rows: {len(df):,}")
        print(f"  Stocks: {n_stocks}, Days: {n_days}")
        print(f"  48-bar completeness: {full_bars*100:.1f}%")
        if len(short_bars) > 0:
            print(f"  Short bars: {len(short_bars)} stock-days (mean={short_bars.mean():.0f} bars)")
        print(f"  Nulls: {null_counts.to_dict()}")
        print(f"  minute_of_day: [{mod_range[0]}, {mod_range[1]}]")
        print(f"  Memory: {result['mem_mb']:.0f}MB")

        del df
        return result


def _compute_minute_index(trade_time: pd.Series) -> pd.Series:
    """将trade_time转换为minute_of_day索引 (0-47)。

    A股交易时段:
    - 上午: 09:35, 09:40, ..., 11:30 → index 0-23 (24 bars)
    - 下午: 13:05, 13:10, ..., 15:00 → index 24-47 (24 bars)
    """
    dt = pd.to_datetime(trade_time)
    hour = dt.dt.hour
    minute = dt.dt.minute

    # 上午: 从09:35开始，每5分钟一个bar
    # 09:35=0, 09:40=1, ..., 11:30=23
    morning_start_min = 9 * 60 + 35  # 575
    # 下午: 从13:05开始
    # 13:05=24, 13:10=25, ..., 15:00=47
    afternoon_start_min = 13 * 60 + 5  # 785

    total_min = hour * 60 + minute
    idx = pd.Series(np.full(len(trade_time), -1, dtype=np.int8), index=trade_time.index)

    # 上午
    morning_mask = (total_min >= morning_start_min) & (total_min <= 11 * 60 + 30)
    idx.loc[morning_mask] = ((total_min[morning_mask] - morning_start_min) // 5).astype(np.int8)

    # 下午
    afternoon_mask = (total_min >= afternoon_start_min) & (total_min <= 15 * 60)
    idx.loc[afternoon_mask] = (24 + (total_min[afternoon_mask] - afternoon_start_min) // 5).astype(np.int8)

    return idx


# ============================================================
# CLI
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Minute bars Parquet cache builder")
    parser.add_argument("--build", action="store_true", help="Build cache from DB")
    parser.add_argument("--verify", type=int, metavar="YEAR", help="Verify cache for year")
    parser.add_argument("--force", action="store_true", help="Overwrite existing cache")
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--info", action="store_true", help="Show cache info")
    args = parser.parse_args()

    cache = MinuteDataCache()

    if args.build:
        cache.build(args.start_year, args.end_year, force=args.force)
    elif args.verify is not None:
        cache.verify(args.verify)
    elif args.info:
        years = cache.years_available()
        if not years:
            print("No cache found. Run --build first.")
        else:
            print(f"Cached years: {years}")
            meta_path = cache.cache_dir / "cache_meta.json"
            if meta_path.exists():
                with open(meta_path) as f:
                    meta = json.load(f)
                print(f"Build date: {meta.get('build_date', '?')}")
                for yr, st in meta.get("stats", {}).items():
                    print(f"  {yr}: {st}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
