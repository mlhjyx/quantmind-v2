"""AKShare valuation fetcher (sub-PR 14 sediment per ADR-053 V3 §S4 (minimal) architecture).

V3 §3.3 line 395-426 fundamental_context 8 维 schema — sub-PR 14 (minimal) 1 source baseline:
**valuation 维** via `ak.stock_value_em(symbol)`. 7 其他维 (growth/earnings/institution/capital_flow/
dragon_tiger/boards/announcements) 留 sub-PR 15+ minimal→完整 expansion (LL-115 capacity expansion 体例
sustained sub-PR 13 AKShare fetcher precedent 第 7 case → sub-PR 14 第 8 case 实证累积扩).

AKShare API signature (verified Phase 0 fresh probe 2026-05-09):
    ak.stock_value_em(symbol: str = '300766') -> pandas.DataFrame
    Returns columns: 数据日期 / 当日收盘价 / 当日涨跌幅 / 总市值 / 流通市值 / 总股本 / 流通股本 /
                     PE(TTM) / PE(静) / 市净率 / PEG值 / 市现率 / 市销率

Real-data 真测 (2026-05-09, sub-PR 14 Phase 0 verify, 600519=贵州茅台):
- 2022 historical rows (entire price history)
- Latest 2026-05-08: PE(TTM)=20.79, PE(静)=20.89, PB=6.35, PEG=-5.02, PCF=21.59, PS=9.81, 总市值=1.72T

设计原则 (沿用 sub-PR 13 AkshareCninfoFetcher precedent + 反 V3 §3.3 strict spec slight enrichment):
- AkshareValuationFetcher.fetch(symbol_id) → latest ValuationContext (1 row)
- V3 §3.3 spec valuation = {pe, pb, ps, ev_ebitda, industry_pctile} but AKShare provides richer set
- ev_ebitda + industry_pctile NOT in stock_value_em — defer sub-PR 15+ enrich (LL-115)
- date 真值 trade date (Asia/Shanghai, sustained klines_daily 体例)
- fail-loud: AKShare exceptions raised as `FundamentalFetchError` (沿用铁律 33)
- 0 DB IO (铁律 31, FundamentalContextService 真**orchestrator** 走 conn)

关联铁律: 17 (DataPipeline 入库) / 31 (Engine 纯计算) / 33 (fail-loud) / 41 (timezone date) / 45 (4 doc fresh read SOP)
关联 ADR: ADR-053 (V3 §S4 (minimal) architecture + AKShare 1 source decision)
关联 LL: LL-144 (S4 minimal scope sub-PR 14 sediment + capacity expansion 体例 sub-PR 15+ deferral)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import (
    date as DateType,  # noqa: N812 — alias preserves dataclass field name `date` without shadowing builtin
)
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


SOURCE_NAME = "akshare_valuation"
ASIA_SHANGHAI = ZoneInfo("Asia/Shanghai")


class FundamentalFetchError(RuntimeError):
    """Fundamental fetcher 调用层 failure (反 silent skip, 沿用铁律 33).

    caller 接住 → audit log + 走下一源 (sub-PR 15+ multi-source ensemble pattern, LL-115 sustained).

    Args:
        source: fetcher 源标识 (e.g. "akshare_valuation")
        message: 真因 cite (e.g. "AKShare 5xx / network timeout / DataFrame schema drift")
        cause: 原始 Exception (retry exhausted 后 raise)
    """

    def __init__(self, source: str, message: str, cause: Exception | None = None) -> None:
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.cause = cause


@dataclass(frozen=True, slots=True)
class ValuationContext:
    """V3 §3.3 valuation 维 dataclass (sub-PR 14 minimal sediment, 8 metrics from AKShare stock_value_em).

    Fields aligned to fundamental_context_daily.valuation JSONB schema:
        date: trade date (Asia/Shanghai, composite PK with symbol_id)
        symbol_id: stock code (composite PK)
        valuation: dict[str, float|None] — 8 keys:
            - pe_ttm: PE TTM ratio
            - pe_static: PE static ratio
            - pb: 市净率 price-to-book
            - peg: PEG值
            - pcf: 市现率 price-to-cashflow
            - ps: 市销率 price-to-sales
            - market_cap_total: 总市值 (CNY)
            - market_cap_float: 流通市值 (CNY)
        fetch_cost: AKShare free $0 sub-PR 14 minimal
        fetch_latency_ms: per-fetch elapsed ms (audit + SLA)
    """

    date: DateType
    symbol_id: str
    valuation: dict[str, Any]
    fetch_cost: Decimal = Decimal("0")
    fetch_latency_ms: int = 0


class AkshareValuationFetcher:
    """V3 §3.3 valuation 维 fetcher via AKShare stock_value_em (sub-PR 14 sediment per ADR-053).

    Note:
        fetch(symbol_id="<6 digit>") returns latest valuation row (反 over-fetch 2022 historical
        rows, sub-PR 15+ candidate to add date_range arg for backfill).

    Example:
        >>> fetcher = AkshareValuationFetcher()
        >>> ctx = fetcher.fetch(symbol_id="600519")
        >>> print(ctx.date, ctx.valuation['pe_ttm'])
        2026-05-08 20.79
    """

    source_name = SOURCE_NAME

    def fetch(self, *, symbol_id: str) -> ValuationContext:
        """Fetch latest valuation row for stock symbol via AKShare stock_value_em.

        Args:
            symbol_id: stock code 6-digit string (e.g. "600519" 贵州茅台).

        Returns:
            ValuationContext (latest trade date, valuation dict 8 keys, fetch_cost=0, fetch_latency_ms).

        Raises:
            FundamentalFetchError: AKShare API failure / DataFrame empty / schema drift / column missing.
        """
        try:
            import akshare as ak
        except ImportError as e:
            raise FundamentalFetchError(
                source=SOURCE_NAME,
                message="akshare package not installed in .venv",
                cause=e,
            ) from e

        t0 = time.monotonic()
        try:
            df = ak.stock_value_em(symbol=symbol_id)
        except Exception as e:
            raise FundamentalFetchError(
                source=SOURCE_NAME,
                message=(
                    f"AKShare stock_value_em failed for symbol={symbol_id!r}: "
                    f"{type(e).__name__}: {e}"
                ),
                cause=e,
            ) from e

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if df is None or len(df) == 0:
            raise FundamentalFetchError(
                source=SOURCE_NAME,
                message=f"AKShare stock_value_em returned 0 rows for symbol={symbol_id!r} (data condition? symbol invalid?)",
            )

        # Schema verify (反 silent column drift per LL-141/142 reverse case 体例 sustained)
        required_cols = {
            "数据日期",
            "总市值",
            "流通市值",
            "PE(TTM)",
            "PE(静)",
            "市净率",
            "PEG值",
            "市现率",
            "市销率",
        }
        missing = required_cols - set(df.columns)
        if missing:
            raise FundamentalFetchError(
                source=SOURCE_NAME,
                message=(
                    f"AKShare DataFrame schema drift — missing columns {missing} "
                    f"for symbol={symbol_id!r} (got: {list(df.columns)})"
                ),
            )

        # Sort by 数据日期 desc + take latest row
        df_sorted = df.sort_values("数据日期", ascending=False)
        latest = df_sorted.iloc[0]

        trade_date = self._parse_date(latest["数据日期"])
        valuation = {
            "pe_ttm": _safe_float(latest["PE(TTM)"]),
            "pe_static": _safe_float(latest["PE(静)"]),
            "pb": _safe_float(latest["市净率"]),
            "peg": _safe_float(latest["PEG值"]),
            "pcf": _safe_float(latest["市现率"]),
            "ps": _safe_float(latest["市销率"]),
            "market_cap_total": _safe_float(latest["总市值"]),
            "market_cap_float": _safe_float(latest["流通市值"]),
        }

        logger.info(
            "AKShare valuation symbol=%s date=%s pe_ttm=%s pb=%s elapsed_ms=%d",
            symbol_id,
            trade_date,
            valuation["pe_ttm"],
            valuation["pb"],
            elapsed_ms,
        )

        return ValuationContext(
            date=trade_date,
            symbol_id=symbol_id,
            valuation=valuation,
            fetch_cost=Decimal("0"),
            fetch_latency_ms=elapsed_ms,
        )

    @staticmethod
    def _parse_date(raw: object) -> DateType:
        """Parse AKShare 数据日期 column to date (Asia/Shanghai trade date, sustained klines_daily 体例).

        Branch ordering rationale (sub-PR 14 reviewer HIGH clarification):
        1. `hasattr(raw, "date")` matches pandas.Timestamp + datetime — both have `.date()` method.
        2. `isinstance(raw, str)` matches AKShare str format '2026-05-08'.
        3. `isinstance(raw, DateType)` matches **bare datetime.date** — verified empirically that
           `date(...)` does NOT have `.date` attribute (AttributeError on access), so falls through
           branches 1+2 and reaches this branch. NOT dead code (反 reviewer misread of date class API).
        """
        if hasattr(raw, "date"):
            # pandas Timestamp.date() returns datetime.date; datetime.date() returns its date portion
            return raw.date()
        if isinstance(raw, str):
            return datetime.strptime(raw, "%Y-%m-%d").date()
        if isinstance(raw, DateType):
            # Bare datetime.date (e.g. test fixture date(2026,5,8)) — date class has NO .date attr
            return raw
        raise FundamentalFetchError(
            source=SOURCE_NAME,
            message=f"AKShare 数据日期 type unexpected: {type(raw).__name__} value={raw!r}",
        )


def _safe_float(value: object) -> float | None:
    """Convert pandas value to float, NaN/None → None (反 NaN 入库 per 铁律 29 sustained)."""
    if value is None:
        return None
    try:
        f = float(value)
        # NaN check (NaN != NaN per IEEE 754)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None
