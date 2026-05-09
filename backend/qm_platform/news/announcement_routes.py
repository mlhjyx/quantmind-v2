"""Announcement RSSHub route config (sub-PR 11b sediment per ADR-049 §1 Decision 3 RSSHub route reuse).

V3 §11.1 row 5 AnnouncementProcessor 公告流 ingest 走 RSSHub route reuse pattern (反 separate fetcher
classes, sustained sub-PR 6 RsshubNewsFetcher precedent + ADR-022 反 abstraction premature).

Exposed routes (sub-PR 11b baseline, sustained sub-PR 6 chunk C-RSSHub Path A 4 working routes precedent):
- `/cninfo/announcement/{stockCode}` — 巨潮 cninfo.com.cn 公告 (per-stock route, V3 §11.1 row 5 cite)

Reserved route slots (待 sub-PR 11b S5 paper-mode 5d period real RSS endpoint structure verify per
ADR-049 §2 Finding #1 + ADR-048 §2 4/4 RSSHub capacity expansion architecture decision sediment):
- `/sse/disclosure/{stockCode}` — 上交所 (placeholder, unverified)
- `/szse/disclosure/{stockCode}` — 深交所 (placeholder, unverified)

Architecture sustained (ADR-049 §1 Decision 3):
- AnnouncementProcessor (service layer) consumes these routes via RsshubNewsFetcher.fetch(query=route_path)
- 0 separate AnnouncementFetcher class (sustained ADR-022 反 abstraction premature)
- route_path semantic 沿用 sub-PR 6 RsshubNewsFetcher contract sustained

关联铁律: 25 (改什么读什么) / 38 (Blueprint SSOT) / 45 (4 doc fresh read SOP)
关联 ADR: ADR-049 (V3 §S2.5 architecture sediment + RSSHub route reuse decision)
"""
from __future__ import annotations

# Default route template — caller substitutes {stockCode} via route_path.format(stockCode=symbol_id)
DEFAULT_CNINFO_ROUTE_TEMPLATE = "/cninfo/announcement/{stockCode}"

# Reserved slots — placeholder for sub-PR 11b S5 paper-mode 5d period verify (ADR-049 §2 Finding #1)
RESERVED_SSE_ROUTE_TEMPLATE = "/sse/disclosure/{stockCode}"
RESERVED_SZSE_ROUTE_TEMPLATE = "/szse/disclosure/{stockCode}"

# Active routes baseline (sub-PR 11b 1/3 working — sustained LL-115 capacity expansion 真值 sediment 体例
# from sub-PR 6 RSSHub 1/4 working precedent. SSE/SZSE expansion deferred to S5 paper-mode 5d period
# real verify architecture decision per ADR-048 §2 + ADR-049 §2 Finding #1).
ACTIVE_ANNOUNCEMENT_ROUTES = [DEFAULT_CNINFO_ROUTE_TEMPLATE]


def build_announcement_route(*, source: str, symbol_id: str) -> str:
    """Build announcement route_path from source enum + symbol_id substitution.

    Args:
        source: announcement source enum (cninfo / sse / szse).
        symbol_id: stock code (e.g. "600519" for 贵州茅台).

    Returns:
        Substituted route_path string for RsshubNewsFetcher.fetch(query=...).

    Raises:
        ValueError: unknown source enum (反 silent default fallback, 沿用铁律 33 fail-loud).

    Example:
        >>> build_announcement_route(source="cninfo", symbol_id="600519")
        '/cninfo/announcement/600519'
    """
    if source == "cninfo":
        return DEFAULT_CNINFO_ROUTE_TEMPLATE.format(stockCode=symbol_id)
    elif source == "sse":
        return RESERVED_SSE_ROUTE_TEMPLATE.format(stockCode=symbol_id)
    elif source == "szse":
        return RESERVED_SZSE_ROUTE_TEMPLATE.format(stockCode=symbol_id)
    else:
        raise ValueError(
            f"Unknown announcement source: {source!r} (expected: cninfo/sse/szse)"
        )
