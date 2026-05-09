"""Framework Fundamental — V3 §3.3 fundamental_context 8 维 ingestion (L0.3 主体).

归属: Framework #Data #Fundamental 子模块 (V3 §3.3 line 395-426 真预约 path).
位置: backend/qm_platform/data/fundamental/ (沿用 ADR-022 separate fetcher classes 反 abstraction premature
post-真值-evidence + sub-PR 13 AkshareCninfoFetcher precedent 第 7 case 实证累积扩 + sub-PR 14 NEW
AkshareValuationFetcher 第 8 case 实证累积扩).

scope (sub-PR 14 sediment per ADR-053 (minimal) 决议):
- AkshareValuationFetcher (V3 §3.3 valuation 维 fetcher, sub-PR 14 minimal 1 source baseline)
- ValuationContext (dataclass for AKShare stock_value_em 7 metrics row → JSONB schema)

公共 API 真**唯一 sanctioned 入口**:

    from backend.qm_platform.data.fundamental import AkshareValuationFetcher, ValuationContext

    fetcher = AkshareValuationFetcher()
    ctx = fetcher.fetch(symbol_id="600519")  # latest AKShare valuation row
    print(ctx.date, ctx.valuation)  # ValuationContext(date=date(2026,5,8), valuation={pe_ttm: 20.78, pb: 6.35, ...})

架构 (沿用 sub-PR 1-7c plugin precedent + sub-PR 13 AkshareCninfoFetcher 第 7 case + ADR-053 §1):
- 1 fetcher per data source (反 base abc 抽象 premature, sub-PR 14 (minimal) 1 source baseline)
- sub-PR 15+ candidate (LL-115 capacity expansion 体例): expand to growth/earnings/institution/capital_flow
  via separate fetchers (Tushare daily_basic + fina_indicator + top10_holders + moneyflow + AKShare 龙虎榜)
- 0 DB IO at fetcher layer (铁律 31, FundamentalContextService 真**入库点** orchestrator)

关联铁律:
- 31 (Engine 层纯计算 — fetcher 0 DB IO)
- 33 (fail-loud — FundamentalFetchError 显式 raise, 反 silent fallback)
- 41 (timezone — date 真 Asia/Shanghai trade date, fetched_at 真 UTC tz-aware)

关联文档:
- V3 §3.3 line 395-426 (fundamental_context 8 维 schema)
- ADR-053 (V3 §S4 (minimal) architecture + AKShare 1 source decision)
- backend/qm_platform/news/akshare_cninfo.py (sub-PR 13 AKShare fetcher precedent 第 7 case)
"""

from .akshare_valuation import (
    AkshareValuationFetcher,
    FundamentalFetchError,
    ValuationContext,
)

__all__ = [
    "AkshareValuationFetcher",
    "FundamentalFetchError",
    "ValuationContext",
]
