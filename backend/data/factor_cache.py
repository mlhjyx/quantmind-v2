"""P0-2: FactorCache — Parquet 读缓存 for factor_values.

参考: docs/DATA_SYSTEM_V1.md §4.3
职责: 统一读取 raw_value / neutral_value, 自动增量刷新 + Parquet 持久化.

存储结构:
    cache/factor_values/
    ├── {factor_name}/
    │   ├── raw_{year}.parquet
    │   ├── neutral_{year}.parquet
    │   └── _meta.json       # {column: {year: {row_count, last_date, ...}}}
    └── _global_meta.json    # {factors: [...], updated_at: ...}

并发保护: Windows msvcrt.locking (bytes-level lock on sidecar .lock file).
缓存一致性: load() 入口检查 DB MAX(trade_date) 与 _meta.json 最大日期差值.

铁律对齐:
- 铁律17 入库: 本模块只读, 写入通过 DataPipeline
- 铁律31 Engine 纯计算: 本模块在 backend/data/, 职责为 L3 cache, 允许 IO
- 铁律9 并发: 单因子文件锁, 避免两个 session 同时 refresh 同一因子
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Windows-only 文件锁
try:
    import msvcrt

    _WINDOWS = True
except ImportError:
    _WINDOWS = False
    import fcntl  # POSIX fallback

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "cache" / "factor_values"

# 允许的 column 类型
VALID_COLUMNS = ("raw_value", "neutral_value", "zscore")
COLUMN_TO_PREFIX = {"raw_value": "raw", "neutral_value": "neutral", "zscore": "zscore"}


class FactorCacheError(Exception):
    """FactorCache 内部错误."""


class FactorCache:
    """Parquet 读缓存层.

    典型用法:
        cache = FactorCache()
        df = cache.load("turnover_mean_20", column="neutral_value",
                        start=date(2021,1,1), end=date(2025,12,31), conn=conn)

    DataFrame schema:
        columns: [code, trade_date, value]
        dtype:   [str,  datetime64, float64]
    """

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        max_total_size_gb: float = 20.0,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_total_size_gb = max_total_size_gb
        self._global_meta_path = self.cache_dir / "_global_meta.json"

    # ================================================================
    # Public API (docs §4.3)
    # ================================================================

    def load(
        self,
        factor_name: str,
        column: str = "raw_value",
        start: date | None = None,
        end: date | None = None,
        conn=None,
        auto_refresh: bool = True,
    ) -> pd.DataFrame:
        """读取因子值 (主入口).

        流程:
          1. 确定需要的年份
          2. 检查每年 Parquet 是否存在 + row_count 一致
          3. 缺失/过期 → 从 DB 加载 + 写 Parquet (如 auto_refresh=True)
          4. 返回合并 DataFrame

        Args:
            factor_name: 因子名
            column: "raw_value" | "neutral_value" | "zscore"
            start/end: 日期范围 (None = 不限)
            conn: psycopg2 连接 (miss 时必需)
            auto_refresh: 缺数据时自动从 DB 拉取

        Returns:
            DataFrame (code, trade_date, value)
        """
        self._validate_column(column)
        self._factor_dir(factor_name)

        # 确定年份范围
        years = self._determine_years(start, end, factor_name, column, conn)

        # 检查每年 Parquet + 增量刷新
        missing_years = []
        for year in years:
            path = self._parquet_path(factor_name, column, year)
            if not path.exists():
                missing_years.append(year)
            elif not self._verify_parquet(path, factor_name, column, year):
                # 损坏 → 删除触发重建
                logger.warning(f"Parquet corrupted, removing: {path}")
                path.unlink(missing_ok=True)
                missing_years.append(year)

        # DB fallback: 缺失时从 DB 构建
        if missing_years and auto_refresh:
            if conn is None:
                raise FactorCacheError(
                    f"Cache miss for {factor_name}/{column} years={missing_years}, "
                    "但未提供 conn. 传 conn 或先调 build()"
                )
            self.build([factor_name], missing_years, conn, columns=[column])

        # 增量检查: 如 auto_refresh, 检查最新日期是否需要 refresh
        if auto_refresh and conn is not None:
            self.refresh(factor_name, column, conn, silent=True)

        # 读取所有可用年份
        dfs = []
        for year in years:
            path = self._parquet_path(factor_name, column, year)
            if path.exists():
                dfs.append(pd.read_parquet(path))

        if not dfs:
            # 完全没数据
            return pd.DataFrame(columns=["code", "trade_date", "value"])

        df = pd.concat(dfs, ignore_index=True)

        # 过滤日期范围
        if start is not None:
            df = df[df["trade_date"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["trade_date"] <= pd.Timestamp(end)]

        return df.reset_index(drop=True)

    def refresh(
        self,
        factor_name: str,
        column: str,
        conn,
        silent: bool = False,
    ) -> int:
        """增量刷新: 对比 DB 最新日期 vs Parquet 最新日期, 追加缺失日期.

        Returns:
            追加的行数
        """
        self._validate_column(column)

        # 获取当前缓存的最大日期
        cache_max = self._get_cache_max_date(factor_name, column)

        # 查 DB 最新日期
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT MAX(trade_date), COUNT(*)
            FROM factor_values
            WHERE factor_name = %s AND {column} IS NOT NULL
            """,
            (factor_name,),
        )
        row = cur.fetchone()
        cur.close()

        if row is None or row[0] is None:
            return 0

        db_max = row[0]
        row[1]

        if cache_max is not None and db_max <= cache_max:
            # 无需增量
            return 0

        # 增量加载: cache_max+1 → db_max
        start_date = cache_max + pd.Timedelta(days=1) if cache_max else date(2014, 1, 1)
        if hasattr(start_date, "date"):
            start_date = start_date.date() if callable(getattr(start_date, "date", None)) else start_date

        # 用 build 的内部逻辑构建需要的年份
        if isinstance(start_date, (date, datetime)):
            start_year = start_date.year
        else:
            start_year = pd.Timestamp(start_date).year
        end_year = db_max.year

        years_to_refresh = list(range(start_year, end_year + 1))

        if not silent:
            logger.info(
                f"[refresh] {factor_name}/{column}: cache_max={cache_max} db_max={db_max} "
                f"years={years_to_refresh}"
            )

        n_added = 0
        for year in years_to_refresh:
            # 增量写某年的 Parquet (全量重写该年)
            n = self._build_year(factor_name, column, year, conn)
            n_added += n

        return n_added

    def invalidate(self, factor_name: str, column: str | None = None) -> int:
        """删除 Parquet 触发下次重建.

        Args:
            factor_name: 因子名
            column: 指定 column (默认 None = 删所有 column)

        Returns:
            删除的文件数
        """
        factor_dir = self._factor_dir(factor_name)
        if not factor_dir.exists():
            return 0

        if column is not None:
            self._validate_column(column)
            prefix = COLUMN_TO_PREFIX[column]
            patterns = [f"{prefix}_*.parquet"]
        else:
            patterns = ["raw_*.parquet", "neutral_*.parquet", "zscore_*.parquet"]

        n_removed = 0
        for pattern in patterns:
            for path in factor_dir.glob(pattern):
                path.unlink()
                n_removed += 1

        # 如果删了所有 column, 连 _meta.json 也删
        if column is None:
            meta = factor_dir / "_meta.json"
            meta.unlink(missing_ok=True)
            # 空目录清理 (非空则保留)
            with contextlib.suppress(OSError):
                factor_dir.rmdir()
        else:
            # 只更新 meta
            meta_data = self._load_meta(factor_name)
            meta_data.pop(column, None)
            self._save_meta(factor_name, meta_data)

        logger.info(f"[invalidate] {factor_name}/{column or 'ALL'}: removed {n_removed} files")
        return n_removed

    def build(
        self,
        factor_names: Iterable[str],
        years: Iterable[int],
        conn,
        columns: Iterable[str] = ("raw_value", "neutral_value"),
    ) -> dict[str, dict]:
        """批量从 DB 构建 Parquet.

        Returns:
            {factor_name: {year: row_count, ...}}
        """
        results: dict[str, dict] = {}
        for factor_name in factor_names:
            results[factor_name] = {}
            for column in columns:
                self._validate_column(column)
                for year in years:
                    n = self._build_year(factor_name, column, year, conn)
                    results[factor_name][f"{COLUMN_TO_PREFIX[column]}_{year}"] = n

        self._update_global_meta(results.keys())
        return results

    def stats(self) -> dict[str, Any]:
        """返回所有缓存的统计信息."""
        factors = []
        total_size = 0
        total_rows = 0

        for factor_dir in sorted(self.cache_dir.iterdir()):
            if not factor_dir.is_dir() or factor_dir.name.startswith("_"):
                continue
            factor_name = factor_dir.name
            meta = self._load_meta(factor_name)

            factor_size = 0
            factor_rows = 0
            for pq_file in factor_dir.glob("*.parquet"):
                size = pq_file.stat().st_size
                factor_size += size
                total_size += size

            for col_data in meta.values():
                for year_data in col_data.values():
                    factor_rows += year_data.get("row_count", 0)
                    total_rows += year_data.get("row_count", 0)

            factors.append(
                {
                    "name": factor_name,
                    "size_mb": factor_size / (1024 * 1024),
                    "rows": factor_rows,
                    "columns": list(meta.keys()),
                }
            )

        return {
            "cache_dir": str(self.cache_dir),
            "n_factors": len(factors),
            "total_size_gb": total_size / (1024**3),
            "total_rows": total_rows,
            "max_size_gb": self.max_total_size_gb,
            "factors": factors,
        }

    # ================================================================
    # Internals
    # ================================================================

    def _validate_column(self, column: str):
        if column not in VALID_COLUMNS:
            raise FactorCacheError(f"column 必须是 {VALID_COLUMNS}, 得到 {column!r}")

    def _factor_dir(self, factor_name: str) -> Path:
        d = self.cache_dir / factor_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _parquet_path(self, factor_name: str, column: str, year: int) -> Path:
        prefix = COLUMN_TO_PREFIX[column]
        return self._factor_dir(factor_name) / f"{prefix}_{year}.parquet"

    def _meta_path(self, factor_name: str) -> Path:
        return self._factor_dir(factor_name) / "_meta.json"

    def _load_meta(self, factor_name: str) -> dict:
        p = self._meta_path(factor_name)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_meta(self, factor_name: str, meta: dict):
        p = self._meta_path(factor_name)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        # 原子替换 (Windows 下需先 unlink 目标)
        if p.exists():
            p.unlink()
        tmp.rename(p)

    def _determine_years(
        self,
        start: date | None,
        end: date | None,
        factor_name: str,
        column: str,
        conn,
    ) -> list[int]:
        """确定要读取的年份列表.

        策略: 若 start/end 给出用它们; 否则查 meta / DB.
        """
        if start is not None and end is not None:
            return list(range(start.year, end.year + 1))

        # 从 meta 推断
        meta = self._load_meta(factor_name)
        col_meta = meta.get(column, {})
        if col_meta:
            years_str = list(col_meta.keys())
            years = sorted(int(y) for y in years_str)
            if start is not None:
                years = [y for y in years if y >= start.year]
            if end is not None:
                years = [y for y in years if y <= end.year]
            return years

        # 最后从 DB 推断 (昂贵)
        if conn is not None:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT MIN(trade_date), MAX(trade_date)
                FROM factor_values WHERE factor_name = %s AND {column} IS NOT NULL
                """,
                (factor_name,),
            )
            row = cur.fetchone()
            cur.close()
            if row and row[0]:
                s_year = (start or row[0]).year
                e_year = (end or row[1]).year
                return list(range(s_year, e_year + 1))

        return []

    def _build_year(
        self,
        factor_name: str,
        column: str,
        year: int,
        conn,
    ) -> int:
        """全量重写某年的 Parquet. 带文件锁."""
        self._validate_column(column)
        path = self._parquet_path(factor_name, column, year)

        with self._lock(path):
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT code, trade_date, {column}
                FROM factor_values
                WHERE factor_name = %s
                  AND {column} IS NOT NULL
                  AND EXTRACT(YEAR FROM trade_date) = %s
                ORDER BY trade_date, code
                """,
                (factor_name, year),
            )
            rows = cur.fetchall()
            cur.close()

            if not rows:
                # 空年 → 不写文件, 清掉旧文件
                path.unlink(missing_ok=True)
                self._record_year_meta(factor_name, column, year, 0, None)
                return 0

            df = pd.DataFrame(rows, columns=["code", "trade_date", "value"])
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df["value"] = df["value"].astype("float64")

            # 原子写
            tmp = path.with_suffix(".parquet.tmp")
            df.to_parquet(tmp, compression="snappy", index=False)
            if path.exists():
                path.unlink()
            tmp.rename(path)

            last_date = df["trade_date"].max()
            self._record_year_meta(factor_name, column, year, len(df), last_date)

            return len(df)

    def _record_year_meta(
        self,
        factor_name: str,
        column: str,
        year: int,
        row_count: int,
        last_date: pd.Timestamp | None,
    ):
        meta = self._load_meta(factor_name)
        col_meta = meta.setdefault(column, {})
        col_meta[str(year)] = {
            "row_count": row_count,
            "last_date": str(last_date.date()) if last_date is not None else None,
            "built_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        self._save_meta(factor_name, meta)

    def _verify_parquet(
        self,
        path: Path,
        factor_name: str,
        column: str,
        year: int,
    ) -> bool:
        """检查 Parquet 文件是否完好 (与 _meta 记录对比)."""
        try:
            import pyarrow.parquet as pq

            pq_meta = pq.read_metadata(path)
            n_rows = pq_meta.num_rows
        except Exception as e:
            logger.warning(f"[verify] read_metadata failed {path}: {e}")
            return False

        meta = self._load_meta(factor_name)
        expected = meta.get(column, {}).get(str(year), {}).get("row_count")
        if expected is None:
            # meta 缺失: 信任文件本身 (可能是手工拷贝)
            return True
        return n_rows == expected

    def _get_cache_max_date(self, factor_name: str, column: str) -> date | None:
        meta = self._load_meta(factor_name)
        col_meta = meta.get(column, {})
        if not col_meta:
            return None
        dates = []
        for year_data in col_meta.values():
            ld = year_data.get("last_date")
            if ld:
                dates.append(pd.Timestamp(ld).date())
        return max(dates) if dates else None

    def _update_global_meta(self, factor_names: Iterable[str]):
        try:
            current = json.loads(self._global_meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            current = {"factors": [], "updated_at": None}

        existing = set(current.get("factors", []))
        existing.update(factor_names)
        current["factors"] = sorted(existing)
        current["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        tmp = self._global_meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        if self._global_meta_path.exists():
            self._global_meta_path.unlink()
        tmp.rename(self._global_meta_path)

    @contextmanager
    def _lock(self, path: Path, timeout_sec: float = 120.0):
        """文件锁 (Windows msvcrt / POSIX fcntl)."""
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        # noqa: SIM115 — 生产者 context manager 必须跨 yield 持有文件句柄, 不能用 with
        f = open(lock_path, "wb")  # noqa: SIM115
        start = time.time()
        try:
            while True:
                try:
                    if _WINDOWS:
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as err:
                    if time.time() - start > timeout_sec:
                        raise FactorCacheError(
                            f"锁超时 {timeout_sec}s: {lock_path}, 可能其他进程死锁"
                        ) from err
                    time.sleep(0.1)
            yield
        finally:
            try:
                if _WINDOWS:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            f.close()
            # 锁文件保留 (避免竞态), 偶尔手工清理即可


__all__ = ["FactorCache", "FactorCacheError", "VALID_COLUMNS"]
