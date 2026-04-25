"""MVP 2.1b Sub3 + 2.1c Sub3-prep — TushareDataSource: Tushare Platform fetcher.

继承 `BaseDataSource` (MVP 2.1a) Template, contract.name dispatch 3 路径:
  - `klines_daily`: ts.daily() + ts.adj_factor() + ts.stk_limit() 3 API 合并 (MVP 2.1c Sub3-prep)
  - `daily_basic`: ts.daily_basic() 每日基本面
  - `moneyflow`: ts.moneyflow() 资金流

**单位策略**: `_fetch_raw` 返 **RAW Tushare 数据** (无单位归一).
  - Tushare `daily.vol` = 手, `daily.amount` = 千元 (原样返回)
  - 下游 `DataPipeline.ingest(df, KLINES_DAILY)` (contracts.py TableContract) 负责:
      rename (ts_code→code / vol→volume / pct_chg→pct_change)
      + unit 转换 (amount 千元→元, mv 万元→元) + FK 过滤 + upsert
  - 这与 MVP 2.1a base_source.py docstring "单位已归一" 略有偏差 — 为 MVP 2.1b dual-write
    与老 `BaseDataFetcher` 输出对齐, MVP 2.1c 删老后再收敛口径

**MVP 2.1c Sub3-prep (2026-04-19) 解除限制**:
  - `klines_daily` 扩 3 字段 (adj_factor / up_limit / down_limit), 合并 3 API 与老 fetcher pattern
    对齐 (fetch_base_data.py::fetch_klines_daily L251-290)
  - Fallback 语义 (与老 fetcher 严格一致):
    - adj_factor API 当日空 → 默认 1.0 (不复权)
    - stk_limit API 当日空 → up_limit/down_limit = None
  - 为下周一 (2026-04-20) dual-write 窗口 5 交易日新老 100% md5 对齐提供 precondition
  - Sub3 main (删老 fetcher) 仍等窗口 2026-04-25 验收后做

与老 `backend/app/data_fetcher/fetch_base_data.py` dual-write:
  - 本类: fetch_raw (3 API 合并) + validate
  - 老脚本: Celery daily_pipeline 继续走 `BaseDataFetcher.run_all` async path
  - MVP 2.1c Sub3 main 后删老脚本

Usage:
    api = TushareAPI()  # 或 mock client
    source = TushareDataSource(client=api, end=date.today())
    df = source.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 10))
    # DataFrame schema 对齐 contract.schema (14 列: ts_code/trade_date/open/.../vol/amount
    # + adj_factor/up_limit/down_limit)
    # 走 DataPipeline.ingest(df, KLINES_DAILY TableContract) 完成归一+入库
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd

from ..base_source import BaseDataSource
from ..interface import DataContract

logger = logging.getLogger(__name__)


# ---------- DataContract 实例 (MVP 2.1b, 与 contracts.py TableContract 对齐但独立) ----------

KLINES_DAILY_DATA_CONTRACT = DataContract(
    name="klines_daily",
    version="v2",  # MVP 2.1c Sub3-prep (2026-04-19): +3 字段 (adj_factor/up_limit/down_limit)
    schema={
        # RAW Tushare 字段 (ts_code/vol/pct_chg 由 DataPipeline rename)
        "ts_code": "str",
        "trade_date": "date",
        "open": "float64 元",
        "high": "float64 元",
        "low": "float64 元",
        "close": "float64 元",
        "pre_close": "float64 元",
        "change": "float64",
        "pct_chg": "float64 %×100",
        "vol": "int64 手",
        "amount": "float64 千元",
        # MVP 2.1c Sub3-prep: 合 ts.adj_factor + ts.stk_limit 3 API
        "adj_factor": "float64",
        "up_limit": "float64 元",
        "down_limit": "float64 元",
    },
    primary_key=("ts_code", "trade_date"),
    source="tushare",
    unit_convention={
        "open": "元",
        "high": "元",
        "low": "元",
        "close": "元",
        "vol": "手",
        "amount": "千元",  # RAW, DataPipeline 转 元
        "adj_factor": "无量纲",
        "up_limit": "元",
        "down_limit": "元",
    },
)

DAILY_BASIC_DATA_CONTRACT = DataContract(
    name="daily_basic",
    version="v1",
    schema={
        "ts_code": "str",
        "trade_date": "date",
        "close": "float64 元",
        "turnover_rate": "float64 %",
        "turnover_rate_f": "float64 %",
        "volume_ratio": "float64",
        "pe": "float64",
        "pe_ttm": "float64",
        "pb": "float64",
        "ps": "float64",
        "ps_ttm": "float64",
        "dv_ratio": "float64 %",
        "dv_ttm": "float64 %",
        "total_share": "float64 万股",
        "float_share": "float64 万股",
        "free_share": "float64 万股",
        "total_mv": "float64 万元",
        "circ_mv": "float64 万元",
    },
    primary_key=("ts_code", "trade_date"),
    source="tushare",
    unit_convention={
        "total_mv": "万元",
        "circ_mv": "万元",
        "total_share": "万股",
    },
)

MONEYFLOW_DATA_CONTRACT = DataContract(
    name="moneyflow",
    version="v1",
    schema={
        "ts_code": "str",
        "trade_date": "date",
        "buy_sm_vol": "int64 手",
        "buy_sm_amount": "float64 万元",
        "sell_sm_vol": "int64 手",
        "sell_sm_amount": "float64 万元",
        "buy_md_vol": "int64 手",
        "buy_md_amount": "float64 万元",
        "sell_md_vol": "int64 手",
        "sell_md_amount": "float64 万元",
        "buy_lg_vol": "int64 手",
        "buy_lg_amount": "float64 万元",
        "sell_lg_vol": "int64 手",
        "sell_lg_amount": "float64 万元",
        "buy_elg_vol": "int64 手",
        "buy_elg_amount": "float64 万元",
        "sell_elg_vol": "int64 手",
        "sell_elg_amount": "float64 万元",
        "net_mf_vol": "int64 手",
        "net_mf_amount": "float64 万元",
    },
    primary_key=("ts_code", "trade_date"),
    source="tushare",
    unit_convention={
        "buy_sm_amount": "万元",
        "net_mf_amount": "万元",
    },
)

_CONTRACT_API_MAP = {
    "klines_daily": ("daily", "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"),
    "daily_basic": (
        "daily_basic",
        "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,"
        "pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
        "total_share,float_share,free_share,total_mv,circ_mv",
    ),
    "moneyflow": (
        "moneyflow",
        "ts_code,trade_date,buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount,"
        "buy_md_vol,buy_md_amount,sell_md_vol,sell_md_amount,"
        "buy_lg_vol,buy_lg_amount,sell_lg_vol,sell_lg_amount,"
        "buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,"
        "net_mf_vol,net_mf_amount",
    ),
}


# ---------- Board 识别 (与 fetch_base_data.py::_board_from_ts_code 对齐) ----------


def _board_from_ts_code(ts_code: str) -> str:
    """ts_code 后缀 → 板块 (main / star / gem / bse)."""
    if ts_code.startswith("68"):
        return "star"
    if ts_code.startswith("30"):
        return "gem"
    if ts_code.startswith(("8", "4")):
        return "bse"
    return "main"


# ---------- DataSource ----------


class TushareDataSource(BaseDataSource):
    """Tushare DataSource (MVP 2.1b Sub-commit 3).

    Args:
      client: 带 `.query(api_name, **kwargs) -> pd.DataFrame` 方法的 Tushare client.
        生产用 `app.data_fetcher.tushare_api.TushareAPI`. 测试传 mock.
      end: 拉取终止日期 (inclusive), None 用 `date.today()`.
      nan_ratio_threshold: 0.1 (Tushare 停牌日 daily_basic 字段会缺, 10% 容忍).
    """

    def __init__(
        self,
        client: Any,
        end: date | None = None,
        nan_ratio_threshold: float = 0.1,
    ) -> None:
        super().__init__(nan_ratio_threshold=nan_ratio_threshold)
        if client is None:
            raise ValueError("client 不可为 None — TushareDataSource 需 TushareAPI 实例")
        if not hasattr(client, "query"):
            raise TypeError(
                f"client 缺少 query 方法 (期望 TushareAPI 接口), 实际: {type(client).__name__}"
            )
        self._client = client
        self._end = end

    # ---------- Template method override ----------

    def _fetch_raw(self, contract: DataContract, since: date) -> pd.DataFrame:
        """按 contract.name dispatch 到 Tushare 对应 endpoint, 多日聚合.

        Raises:
          ValueError: contract 不支持.
          RuntimeError: Tushare client 异常 (铁律 33 fail-loud).
        """
        name = contract.name
        if name not in _CONTRACT_API_MAP:
            raise ValueError(
                f"TushareDataSource 不支持 contract={name!r}, "
                f"支持: {sorted(_CONTRACT_API_MAP)}"
            )
        # MVP 2.1c Sub3-prep: klines_daily 特殊走 3 API 合并路径
        if name == "klines_daily":
            return self._fetch_klines_merged(since, contract)
        api_name, fields = _CONTRACT_API_MAP[name]
        return self._fetch_daily_range(api_name, fields, since, contract)

    # ---------- klines_daily 3 API merge (MVP 2.1c Sub3-prep) ----------

    def _fetch_klines_merged(
        self, since: date, contract: DataContract
    ) -> pd.DataFrame:
        """合并 ts.daily + ts.adj_factor + ts.stk_limit 3 API, 与老 fetcher pattern 对齐.

        老 fetcher 参考: backend/app/data_fetcher/fetch_base_data.py::fetch_klines_daily
          L251-290 (按日迭代 + 3 API + left merge + fallback).

        Fallback 规则 (严格复制老逻辑):
          - df_adj 空 → df["adj_factor"] = 1.0 (不复权)
          - df_limit 空 → df["up_limit"] = None, df["down_limit"] = None
          - df_daily 空 (当日无交易) → 整日跳过, 不产任何行
        """
        end = self._end or date.today()
        if since > end:
            raise ValueError(f"since={since} > end={end}")

        daily_fields = _CONTRACT_API_MAP["klines_daily"][1]
        adj_fields = "ts_code,trade_date,adj_factor"
        lim_fields = "ts_code,trade_date,up_limit,down_limit"

        frames: list[pd.DataFrame] = []
        d = since
        day_count = 0
        while d <= end:
            td_str = d.strftime("%Y%m%d")

            # 1. base daily (必有, 空则跳过本日)
            try:
                df_d = self._client.query("daily", trade_date=td_str, fields=daily_fields)
            except Exception as e:
                raise RuntimeError(
                    f"Tushare daily 查询 trade_date={td_str} 失败: {e}"
                ) from e

            if df_d is None or df_d.empty:
                d += timedelta(days=1)
                day_count += 1
                continue

            # 2. adj_factor (可空 → fallback 1.0)
            try:
                df_adj = self._client.query(
                    "adj_factor", trade_date=td_str, fields=adj_fields
                )
            except Exception as e:
                raise RuntimeError(
                    f"Tushare adj_factor 查询 trade_date={td_str} 失败: {e}"
                ) from e

            if df_adj is not None and not df_adj.empty:
                df_d = df_d.merge(
                    df_adj[["ts_code", "adj_factor"]], on="ts_code", how="left"
                )
                # left merge 个别 ts_code 缺 adj_factor → fallna 1.0
                df_d["adj_factor"] = df_d["adj_factor"].fillna(1.0)
            else:
                df_d["adj_factor"] = 1.0

            # 3. stk_limit (可空 → fallback None)
            try:
                df_lim = self._client.query(
                    "stk_limit", trade_date=td_str, fields=lim_fields
                )
            except Exception as e:
                raise RuntimeError(
                    f"Tushare stk_limit 查询 trade_date={td_str} 失败: {e}"
                ) from e

            if df_lim is not None and not df_lim.empty:
                df_d = df_d.merge(
                    df_lim[["ts_code", "up_limit", "down_limit"]],
                    on="ts_code",
                    how="left",
                )
            else:
                df_d["up_limit"] = None
                df_d["down_limit"] = None

            frames.append(df_d)
            d += timedelta(days=1)
            day_count += 1

        logger.info(
            "TushareDataSource.klines_daily 合 3 API 拉取 %d 日, %d 帧 (since=%s, end=%s)",
            day_count,
            len(frames),
            since,
            end,
        )

        if not frames:
            return pd.DataFrame(columns=list(contract.schema.keys()))

        df = pd.concat(frames, ignore_index=True)
        cols = list(contract.schema.keys())
        for c in cols:
            if c not in df.columns:
                df[c] = None
        return df[cols]

    # ---------- 内部: 日期范围迭代 ----------

    def _fetch_daily_range(
        self, api_name: str, fields: str, since: date, contract: DataContract
    ) -> pd.DataFrame:
        """Tushare 按日 endpoint 的多日聚合拉取 (daily / daily_basic / moneyflow)."""
        end = self._end or date.today()
        if since > end:
            raise ValueError(f"since={since} > end={end}")

        all_frames: list[pd.DataFrame] = []
        d = since
        day_count = 0
        while d <= end:
            td_str = d.strftime("%Y%m%d")
            try:
                df = self._client.query(api_name, trade_date=td_str, fields=fields)
            except Exception as e:
                raise RuntimeError(
                    f"Tushare {api_name} 查询 trade_date={td_str} 失败: {e}"
                ) from e
            if df is not None and not df.empty:
                all_frames.append(df)
            d += timedelta(days=1)
            day_count += 1

        logger.info(
            "TushareDataSource.%s 拉取 %d 日, %d 帧 (since=%s, end=%s)",
            api_name,
            day_count,
            len(all_frames),
            since,
            end,
        )

        if not all_frames:
            return pd.DataFrame(columns=list(contract.schema.keys()))

        df = pd.concat(all_frames, ignore_index=True)
        # 列对齐 contract.schema (缺的 DataFrame 列 → None)
        cols = list(contract.schema.keys())
        for c in cols:
            if c not in df.columns:
                df[c] = None
        return df[cols]

    # ---------- _check_nan_ratio override (MVP 2.1c Sub3-prep) ----------

    _NAN_TOLERANT_COLS: dict[str, frozenset[str]] = {
        # up_limit/down_limit fallback 为 None (stk_limit API 当日空时), 100% NaN 合法
        "klines_daily": frozenset({"up_limit", "down_limit"}),
    }

    def _check_nan_ratio(
        self, df: pd.DataFrame, contract: DataContract
    ) -> list[str]:
        """Override: 跳过 fallback 允许高 NaN 的列 (e.g. klines_daily up/down_limit)."""
        tolerant = self._NAN_TOLERANT_COLS.get(contract.name, frozenset())
        if not tolerant:
            return super()._check_nan_ratio(df, contract)

        # 复用父类逻辑, 但跳过 tolerant cols
        issues: list[str] = []
        if df.empty:
            return issues
        pk_cols = set(contract.primary_key)
        total = len(df)
        for col in contract.schema:
            if col not in df.columns:
                continue
            if col in tolerant:
                continue  # fallback 允许高 NaN
            n_nan = int(df[col].isna().sum())
            if col in pk_cols and n_nan > 0:
                issues.append(f"[nan] PK column {col!r} has {n_nan} NaN values (not allowed)")
            else:
                ratio = n_nan / total
                if ratio > self._nan_ratio_threshold:
                    issues.append(
                        f"[nan] column {col!r} NaN ratio {ratio:.2%} > "
                        f"threshold {self._nan_ratio_threshold:.2%}"
                    )
        return issues

    # ---------- _check_value_ranges override ----------

    def _check_value_ranges(
        self, df: pd.DataFrame, contract: DataContract
    ) -> list[str]:
        """业务约束 (与 contracts.py TableContract value_ranges 对齐)."""
        issues: list[str] = []
        if df.empty:
            return issues

        name = contract.name
        if name == "klines_daily":
            # 价格非负 (停牌日允许 None, 但不允许负)
            for col in ("open", "high", "low", "close", "pre_close"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0 (价格不可负)")
            # vol/amount 非负
            for col in ("vol", "amount"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0")
            # pct_chg 合理范围 (A 股主板 ±10%, ST ±5%, 创业板 ±20%, 北交所 ±30%,
            # 新股首日无涨跌停限制, 历史最大 +1000%+; 宽松 ±1100 覆盖极端新股 + 过滤真 bug)
            if "pct_chg" in df.columns:
                bad = df["pct_chg"].notna() & (df["pct_chg"].abs() > 1100)
                n = int(bad.sum())
                if n > 0:
                    issues.append(
                        f"[range] pct_chg 列 {n} 行 |%| > 1100 (超 10x 新股极限, 疑 bug)"
                    )
            # MVP 2.1c Sub3-prep: 3 新字段值域
            if "adj_factor" in df.columns:
                bad = df["adj_factor"].notna() & (df["adj_factor"] <= 0)
                n = int(bad.sum())
                if n > 0:
                    issues.append(
                        f"[range] adj_factor 列 {n} 行 <= 0 (复权因子必须正)"
                    )
            for col in ("up_limit", "down_limit"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0 (价格不可负)")
        elif name == "daily_basic":
            if "close" in df.columns:
                bad = df["close"].notna() & (df["close"] < 0)
                n = int(bad.sum())
                if n > 0:
                    issues.append(f"[range] close 列 {n} 行 < 0")
            for col in ("total_mv", "circ_mv", "total_share", "float_share"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0")
        elif name == "moneyflow":
            # 资金流 vol 非负, amount 可为负 (净流出)
            for col in df.columns:
                if col.endswith("_vol") and col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0 and not col.startswith("net_"):  # net_mf_vol 允许负
                        issues.append(f"[range] {col} 列 {n} 行 < 0 (vol 不可负)")
        return issues


__all__ = [
    "TushareDataSource",
    "KLINES_DAILY_DATA_CONTRACT",
    "DAILY_BASIC_DATA_CONTRACT",
    "MONEYFLOW_DATA_CONTRACT",
    "_board_from_ts_code",
]
