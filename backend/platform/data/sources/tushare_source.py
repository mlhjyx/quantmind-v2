"""MVP 2.1b Sub-commit 3 — TushareDataSource: Tushare Platform fetcher (最高风险, dual-write).

继承 `BaseDataSource` (MVP 2.1a) Template, contract.name dispatch 3 路径:
  - `klines_daily`: ts.daily() 每日 K 线 (仅 base, 不含 adj_factor / stk_limit)
  - `daily_basic`: ts.daily_basic() 每日基本面
  - `moneyflow`: ts.moneyflow() 资金流

**单位策略**: `_fetch_raw` 返 **RAW Tushare 数据** (无单位归一).
  - Tushare `daily.vol` = 手, `daily.amount` = 千元 (原样返回)
  - 下游 `DataPipeline.ingest(df, KLINES_DAILY)` (contracts.py TableContract) 负责:
      rename (ts_code→code / vol→volume / pct_chg→pct_change)
      + unit 转换 (amount 千元→元, mv 万元→元) + FK 过滤 + upsert
  - 这与 MVP 2.1a base_source.py docstring "单位已归一" 略有偏差 — 为 MVP 2.1b dual-write
    与老 `BaseDataFetcher` 输出对齐, MVP 2.1c 删老后再收敛口径

**MVP 2.1b 限制**:
  - `klines_daily` 仅 base daily, **不合并** adj_factor / stk_limit (老 fetcher 合并 3 API)
  - 真要换到生产需补 adj_factor / stk_limit DataSource 或留 MVP 2.1c orchestrator
  - 本 MVP 交付 **契约合规能力** (走 DataSource 接口 + validate), 不切流生产
  - dual-write 退出前提: MVP 2.1c 扩 orchestrator + regression max_diff=0 × 3 次

与老 `backend/app/data_fetcher/fetch_base_data.py` dual-write:
  - 本类: fetch_raw + validate
  - 老脚本: Celery daily_pipeline 继续走 `BaseDataFetcher.run_all` async path
  - MVP 2.1c 后删老脚本

Usage:
    api = TushareAPI()  # 或 mock client
    source = TushareDataSource(client=api, end=date.today())
    df = source.fetch(KLINES_DAILY_DATA_CONTRACT, since=date(2026, 4, 10))
    # DataFrame schema 对齐 contract.schema (ts_code/trade_date/open/.../vol/amount)
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
    version="v1",
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
        api_name, fields = _CONTRACT_API_MAP[name]
        return self._fetch_daily_range(api_name, fields, since, contract)

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
            # pct_chg 合理范围 (A 股主板 ±10%, ST ±5%, 创业板 ±20%, 北交所 ±30% — 宽松 ±30.5)
            if "pct_chg" in df.columns:
                bad = df["pct_chg"].notna() & (df["pct_chg"].abs() > 30.5)
                n = int(bad.sum())
                if n > 0:
                    issues.append(f"[range] pct_chg 列 {n} 行 |%| > 30.5 (超出涨跌停合理幅度)")
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
