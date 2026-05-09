"""Announcement source config + enum validation (sub-PR 13 sediment per ADR-052 reverse ADR-049 §1 Decision 3).

⚠️ **V3 §S2.5 architecture reverse** (ADR-052 sediment, sub-PR 13 真值 落地):

ADR-049 §1 Decision 3 cite "RSSHub route reuse" 真值**verified broken** via sub-PR 13 Phase 0 active
discovery (LL-142 sediment):
- Local RSSHub instance `/cninfo/announcement/*` HTTP 404 (5 variants probed)
- Upstream `rsshub.app` HTTP 403 production block (RSSHub policy 2025-10+ enforcement)
- Local instance lacks cninfo namespace plugin (eastmoney/jin10 routes work, cninfo missing)

**Reverse decision (ADR-052)**: switch to **AKShare direct API** (`AkshareCninfoFetcher` NEW per
ADR-052 §1) — sustained `akshare 1.18.55` already installed + `stock_zh_a_disclosure_report_cninfo`
returns real disclosure data with announcementId/orgId in URL (cninfo.com.cn canonical detail link).

**Backward compat retention** (this module):
- `build_announcement_route` 真**deprecated** (DeprecationWarning) — kept for test backward compat
  + cite trail. New caller `AnnouncementProcessor.ingest()` 走 `validate_source` + pass symbol_id
  directly to `AkshareCninfoFetcher.fetch(query=symbol_id)` (反 route_path semantic sub-PR 11b 体例).
- `DEFAULT_CNINFO_ROUTE_TEMPLATE` etc 真**legacy reference** (反 active routing, kept for ADR-049
  cite trail + 反 silent overwrite per ADR-022).

Architecture (post-ADR-052 reverse, sustained ADR-049 §1 Decision 2 hybrid module boundary):
- AKShare fetcher in `qm_platform/news/akshare_cninfo.py` (Engine layer 0 DB IO 铁律 31)
- AnnouncementProcessor (service layer) calls `pipeline.fetch_all(query=symbol_id)` 直接 pass symbol_id
- 0 conn.commit (铁律 32, caller 真值 事务边界 sustained)

关联铁律: 25 (改什么读什么) / 33 (fail-loud source enum validation) / 38 (Blueprint SSOT) / 45 (4 doc fresh read SOP)
关联 ADR: ADR-049 §1 Decision 3 amendment (RSSHub route reuse 真值 verified broken) /
          ADR-052 (AKShare reverse decision NEW)
关联 LL: LL-142 (RSSHub spec gap silent miss 第 2 case + LL-141 reverse case 第 1 实证)
"""

from __future__ import annotations

import warnings

# Allowed source enum (sub-PR 14 ride-next P2.1 reviewer fix per ADR-053)
# cninfo: AKShare-fed real production (ADR-052 §1 Decision 3 reverse)
# sse/szse: REMOVED from ALLOWED_SOURCES sub-PR 14 P2.1 fix — 反 silent data provenance lie
#   (sub-PR 13 reviewer P2.1: validate_source allowed sse/szse but no fetcher routing →
#    AKShare fetcher would store data with source="sse" while真值 fetched from cninfo).
#   sub-PR 15+ candidate: re-add sse/szse when separate fetchers exist (sustained ADR-049 §2 Finding #1).
ALLOWED_SOURCES = frozenset({"cninfo"})

# Legacy route templates (deprecated per ADR-052, kept for cite trail + ADR-049 backward compat)
DEFAULT_CNINFO_ROUTE_TEMPLATE = "/cninfo/announcement/{stockCode}"
RESERVED_SSE_ROUTE_TEMPLATE = "/sse/disclosure/{stockCode}"
RESERVED_SZSE_ROUTE_TEMPLATE = "/szse/disclosure/{stockCode}"

# Active routes baseline (legacy — post-ADR-052 reverse, AKShare 直接 API replaces RSSHub routes)
ACTIVE_ANNOUNCEMENT_ROUTES = [DEFAULT_CNINFO_ROUTE_TEMPLATE]


def validate_source(source: str) -> None:
    """Validate announcement source enum (sustained 铁律 33 fail-loud).

    Args:
        source: announcement source enum string (must be in ALLOWED_SOURCES).

    Raises:
        ValueError: unknown source (反 silent default fallback).
    """
    if source not in ALLOWED_SOURCES:
        raise ValueError(
            f"Unknown announcement source: {source!r} (expected: {sorted(ALLOWED_SOURCES)})"
        )


def build_announcement_route(*, source: str, symbol_id: str) -> str:
    """⚠️ DEPRECATED (sub-PR 13 ADR-052 reverse) — RSSHub route_path no longer used.

    Sustained for cite trail + test backward compat (反 silent overwrite ADR-022). New caller
    走 `validate_source` + AKShare fetcher directly with symbol_id query.

    Args:
        source: announcement source enum (cninfo / sse / szse).
        symbol_id: stock code (e.g. "600519" for 贵州茅台).

    Returns:
        Legacy substituted route_path string (反 actually fetched against RSSHub post-ADR-052).

    Raises:
        ValueError: unknown source enum (sustained 铁律 33 fail-loud).
    """
    warnings.warn(
        "build_announcement_route is deprecated (sub-PR 13 ADR-052 reverse): "
        "RSSHub route reuse 真值 verified broken; use validate_source + AkshareCninfoFetcher",
        DeprecationWarning,
        stacklevel=2,
    )
    validate_source(source)
    if source == "cninfo":
        return DEFAULT_CNINFO_ROUTE_TEMPLATE.format(stockCode=symbol_id)
    elif source == "sse":
        return RESERVED_SSE_ROUTE_TEMPLATE.format(stockCode=symbol_id)
    else:  # szse (validated above)
        return RESERVED_SZSE_ROUTE_TEMPLATE.format(stockCode=symbol_id)
