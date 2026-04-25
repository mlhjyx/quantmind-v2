"""MVP 2.1b Sub-commit 1 — BaostockDataSource: 5 分钟 K 线 Platform fetcher.

继承 `BaseDataSource` (MVP 2.1a) Template method, 只实现 `_fetch_raw`.
validation + fail-loud (铁律 33) 由 Template 自动处理.

与老 `scripts/fetch_minute_bars.py` 的分工 (dual-write 期):
  - 本类: 纯 Baostock 查询 + code 格式转换 + DataFrame 组装 + validate
  - 老脚本: CLI 入口 + 股票列表文件加载 + 分片 + 断点续传 + retry + DataPipeline.ingest

调用方 (Celery daily / research CLI) 拿 validated DataFrame 后走
`DataPipeline.ingest(df, MINUTE_BARS)` 完成入库 (铁律 17 + 31).

Baostock 原生单位: price=元, volume=股, amount=元 (与 DB MINUTE_BARS TableContract 一致,
无需单位转换, `MINUTE_BARS.skip_unit_conversion=False` 但 source/db unit 相同).

Usage:
    source = BaostockDataSource(codes=["600519", "000001"])
    df = source.fetch(MINUTE_BARS_DATA_CONTRACT, since=date(2026, 4, 15))
    # df schema/PK/NaN/value_range 已 validate, 可直接 DataPipeline.ingest
"""
from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd

from ..base_source import BaseDataSource
from ..interface import DataContract

logger = logging.getLogger(__name__)


# ---------- DataContract instance (MVP 2.1b, 避免动 contracts.py MVP 1.1 锁) ----------

MINUTE_BARS_DATA_CONTRACT = DataContract(
    name="minute_bars",
    version="v1",
    schema={
        "code": "str",
        "trade_date": "date",
        "trade_time": "datetime",
        "open": "float64 元",
        "high": "float64 元",
        "low": "float64 元",
        "close": "float64 元",
        "volume": "int64 股",
        "amount": "float64 元",
        "adjustflag": "str",
    },
    primary_key=("code", "trade_time"),
    source="baostock",
    unit_convention={
        "open": "元",
        "high": "元",
        "low": "元",
        "close": "元",
        "volume": "股",
        "amount": "元",
    },
)


# ---------- Code format helpers (与 scripts/fetch_minute_bars.py 对齐) ----------


def _to_bs_code(code6: str) -> str:
    """6 位编码 → Baostock code ("sh.600519" / "sz.000001" / "bj.430047")."""
    if code6.startswith(("6", "9")):
        return f"sh.{code6}"
    if code6.startswith(("4", "8")):
        return f"bj.{code6}"
    return f"sz.{code6}"


def _to_db_code(code6: str) -> str:
    """6 位编码 → DB code (带后缀 ".SH" / ".SZ" / ".BJ")."""
    if code6.startswith(("6", "9")):
        return f"{code6}.SH"
    if code6.startswith(("4", "8")):
        return f"{code6}.BJ"
    return f"{code6}.SZ"


# ---------- DataSource ----------


class BaostockDataSource(BaseDataSource):
    """Baostock 5 分钟 K 线 DataSource (MVP 2.1b).

    Args:
      codes: 6 位股票编码列表 (e.g. ["600519", "000001"]).
      nan_ratio_threshold: 非 PK 列 NaN 比例阈值 (默认 0.1).
      end: 拉取终止日期 (inclusive), None 用 `date.today()`.
    """

    def __init__(
        self,
        codes: list[str],
        nan_ratio_threshold: float = 0.1,
        end: date | None = None,
    ) -> None:
        super().__init__(nan_ratio_threshold=nan_ratio_threshold)
        if not codes:
            raise ValueError("codes 不可为空 — BaostockDataSource 需至少 1 个股票编码")
        for c in codes:
            if not (len(c) == 6 and c.isdigit()):
                raise ValueError(f"code 格式错误: {c!r}, 期望 6 位数字")
        self._codes = list(codes)
        self._end = end

    # ---------- Template method override (唯一 abstract) ----------

    def _fetch_raw(self, contract: DataContract, since: date) -> pd.DataFrame:
        """拉 [since, end] 范围 5 分钟 K 线, 多 code 汇总 DataFrame.

        Raises:
          RuntimeError: Baostock 登录失败 (铁律 33 fail-loud).
        """
        del contract  # 本 fetcher 只服务 minute_bars contract, dispatch 按需留 Sub-commit 3
        import baostock as bs  # lazy, 测试 monkeypatch sys.modules

        end = self._end or date.today()
        start_str = since.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(
                f"Baostock 登录失败: code={lg.error_code}, msg={lg.error_msg}"
            )

        try:
            all_rows: list[dict] = []
            for code6 in self._codes:
                bs_code = _to_bs_code(code6)
                db_code = _to_db_code(code6)
                rows = self._query_code(bs, bs_code, start_str, end_str)
                for r in rows:
                    r["code"] = db_code
                    r["adjustflag"] = "3"
                all_rows.extend(rows)
        finally:
            bs.logout()

        cols = [
            "code",
            "trade_date",
            "trade_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adjustflag",
        ]
        if not all_rows:
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(all_rows)
        return df[[c for c in cols if c in df.columns]]

    # ---------- 内部: 单 code 查询 (抽自 scripts/fetch_minute_bars.py::_query_baostock) ----------

    @staticmethod
    def _query_code(
        bs_module, bs_code: str, start: str, end: str
    ) -> list[dict]:
        """单 code Baostock 5min 查询, 静态方法便于 mock.

        Args:
          bs_module: baostock 模块 (或 mock).
          bs_code: "sh.600519" 风格.
          start / end: "YYYY-MM-DD".
        """
        rs = bs_module.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,volume,amount",
            start_date=start,
            end_date=end,
            frequency="5",
            adjustflag="3",  # 不复权
        )
        if rs.error_code != "0":
            logger.warning(
                "Baostock %s 查询失败: %s %s", bs_code, rs.error_code, rs.error_msg
            )
            return []

        rows: list[dict] = []
        while rs.error_code == "0" and rs.next():
            data = rs.get_row_data()
            if len(data) < 8 or not data[0]:
                continue
            trade_date_str = data[0]  # "YYYY-MM-DD"
            trade_time_str = data[1]  # "YYYYMMDDHHMMSSmmm"
            try:
                trade_time = datetime.strptime(trade_time_str[:14], "%Y%m%d%H%M%S")
            except (ValueError, IndexError):
                continue
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "trade_time": trade_time,
                    "open": float(data[2]) if data[2] else None,
                    "high": float(data[3]) if data[3] else None,
                    "low": float(data[4]) if data[4] else None,
                    "close": float(data[5]) if data[5] else None,
                    "volume": int(data[6]) if data[6] else 0,
                    "amount": float(data[7]) if data[7] else 0.0,
                }
            )
        return rows

    # ---------- _check_value_ranges override (业务约束) ----------

    def _check_value_ranges(
        self, df: pd.DataFrame, contract: DataContract
    ) -> list[str]:
        """业务约束: close > 0, high >= low, volume >= 0."""
        del contract
        issues: list[str] = []
        if df.empty:
            return issues

        if "close" in df.columns:
            bad = df["close"].notna() & (df["close"] <= 0)
            n = int(bad.sum())
            if n > 0:
                issues.append(f"[range] close 列 {n} 行 ≤ 0 (价格必须正)")

        if "high" in df.columns and "low" in df.columns:
            both_valid = df["high"].notna() & df["low"].notna()
            bad = both_valid & (df["high"] < df["low"])
            n = int(bad.sum())
            if n > 0:
                issues.append(f"[range] high<low 行数 {n} (high 必须 ≥ low)")

        if "volume" in df.columns:
            bad = df["volume"].notna() & (df["volume"] < 0)
            n = int(bad.sum())
            if n > 0:
                issues.append(f"[range] volume 列 {n} 行 < 0")

        return issues


__all__ = [
    "BaostockDataSource",
    "MINUTE_BARS_DATA_CONTRACT",
    "_to_bs_code",
    "_to_db_code",
]
