"""FundamentalContextService — V3 §3.3 fundamental_context 8 维 orchestrator (sub-PR 14 sediment per ADR-053).

scope (sub-PR 14, S4 (minimal) implementation 闭环 Layer 2.2 完整闭环 sediment, sustained sub-PR 11b
AnnouncementProcessor + sub-PR 13 AkshareCninfoFetcher precedent):
- AkshareValuationFetcher fetch latest ValuationContext (sub-PR 14 minimal 1 source 1 维)
- UPSERT fundamental_context_daily (composite PK (symbol_id, date)) — valuation JSONB only,
  其余 7 维 NULL by design (sub-PR 15+ minimal→完整 expansion per LL-115 capacity expansion 体例)
- 0 conn.commit (铁律 32 sustained, caller 真值 事务边界管理者)

caller 真值 唯一 sanctioned 入口 (沿用 sub-PR 7c bootstrap 体例 sustained):

    from backend.app.services.fundamental_context_service import FundamentalContextService
    from backend.qm_platform.data.fundamental import AkshareValuationFetcher
    from backend.app.services.db import get_sync_conn

    fetcher = AkshareValuationFetcher()
    service = FundamentalContextService(fetcher=fetcher)

    with get_sync_conn() as conn:
        stats = service.ingest(symbol_id="600519", conn=conn)
        conn.commit()  # caller 真值 事务边界 (铁律 32)
        # stats: FundamentalIngestStats(symbol_id='600519', date=date(2026,5,8), valuation_filled=True)

关联铁律:
- 17 (DataPipeline 入库 — UPSERT fundamental_context_daily 走本 service orchestrator)
- 22 (文档跟随代码 — ADR-053 §1 Phase 1 sub-PR 14 implementation 真值落地)
- 25 (改什么读什么 — Phase 0/1 fresh verify sustained sub-PR 13 sediment)
- 31 (Engine 层纯计算 sustained — AkshareValuationFetcher 0 DB IO, service 真**orchestrator** 走 conn)
- 32 (Service 不 commit, 事务边界由 Router/Celery 管 — caller 真值 commit/rollback)
- 33 (fail-loud — FundamentalFetchError / DB error 真 raise)
- 41 (timezone — date 真 Asia/Shanghai trade date, fetched_at 真 UTC tz-aware)
- 45 (4 doc fresh read SOP enforcement)

关联文档:
- V3 §3.3 line 395-426 (fundamental_context 8 维 schema)
- ADR-053 (V3 §S4 (minimal) architecture + AKShare 1 source decision)
- backend/migrations/2026_05_10_fundamental_context_daily.sql (sub-PR 14 DDL)
- backend/qm_platform/data/fundamental/akshare_valuation.py (sub-PR 14 fetcher)
- backend/app/services/news/announcement_processor.py (sub-PR 11b orchestrator precedent)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import (
    date as DateType,  # noqa: N812 — alias preserves dataclass field name `date` without shadowing builtin
)
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.qm_platform.data.fundamental.akshare_valuation import (
        AkshareValuationFetcher,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FundamentalIngestStats:
    """FundamentalContextService.ingest 真值 stats (sub-PR 14 sediment).

    Fields:
        symbol_id: ingested stock code.
        date: trade date (Asia/Shanghai).
        valuation_filled: True if AKShare valuation 维 fetched + UPSERT (sub-PR 14 minimal scope).
        fetch_latency_ms: AkshareValuationFetcher elapsed ms (audit + SLA).
    """

    symbol_id: str
    date: DateType
    valuation_filled: bool
    fetch_latency_ms: int


class FundamentalContextService:
    """V3 §3.3 fundamental_context 8 维 orchestrator (sub-PR 14 (minimal) 1 source baseline).

    DI 体例 (沿用 sub-PR 7c NewsIngestionService + sub-PR 11b AnnouncementProcessor precedent):
        fetcher = AkshareValuationFetcher()
        service = FundamentalContextService(fetcher=fetcher)

    architecture (沿用 ADR-053 §1 Decision 1 + 铁律 31 sustained):
        - AkshareValuationFetcher (qm_platform/data/fundamental/, 0 DB IO 铁律 31) → ValuationContext
        - 本 service (app/services/, orchestrator 真值 入库点) → conn → UPSERT fundamental_context_daily
        - 0 conn.commit (铁律 32, caller 真值 事务边界)
        - sub-PR 14 minimal: valuation JSONB only, 7 其他维 NULL by design (sub-PR 15+ expansion per LL-115)
    """

    def __init__(self, *, fetcher: AkshareValuationFetcher) -> None:
        """Initialize FundamentalContextService.

        Args:
            fetcher: AkshareValuationFetcher (sub-PR 14 minimal 1 source).
                sub-PR 15+ candidate (LL-115): replace with multi-source ensemble pattern
                (Tushare daily_basic + fina_indicator + AKShare 龙虎榜 etc).

        Note:
            keyword-only — 反 positional swap silent bug (沿用 sub-PR 11b contract).
        """
        self._fetcher = fetcher

    def ingest(
        self,
        *,
        symbol_id: str,
        conn: Any,
    ) -> FundamentalIngestStats:
        """Orchestrate fundamental_context valuation 维 ingestion: AKShare fetch → UPSERT.

        Args:
            symbol_id: stock code 6-digit string (e.g. "600519").
            conn: psycopg2 connection — caller 真值 事务边界管理者 (铁律 32 sustained).

        Returns:
            FundamentalIngestStats — symbol_id / date / valuation_filled / fetch_latency_ms.

        Raises:
            FundamentalFetchError: AKShare API failure / schema drift (沿用铁律 33 fail-loud).
            psycopg2 errors: DB-level UPSERT failure (caller 真**接 rollback**).

        Note (UPSERT semantics, sub-PR 14 sediment):
            ON CONFLICT (symbol_id, date) DO UPDATE SET valuation = EXCLUDED.valuation,
            fetched_at = NOW(). 7 其他维 (growth/earnings/...) preserved on conflict (反 silent
            overwrite to NULL, sustained ADR-022 + sub-PR 15+ expansion 体例).

        Note (0 conn.commit, 铁律 32 sustained):
            本 service 0 conn.commit / 0 conn.rollback. caller 真值 事务边界管理者
            (沿用 sub-PR 7c NewsIngestionService + sub-PR 11b AnnouncementProcessor 体例 sustained).
        """
        ctx = self._fetcher.fetch(symbol_id=symbol_id)

        # UPSERT — preserve 7 other dimensions on conflict (反 silent NULL overwrite per ADR-022)
        sql = """
            INSERT INTO fundamental_context_daily (
                symbol_id, date, valuation, fetch_cost, fetch_latency_ms
            ) VALUES (
                %s, %s, %s::jsonb, %s, %s
            )
            ON CONFLICT (symbol_id, date) DO UPDATE SET
                valuation = EXCLUDED.valuation,
                fetch_cost = EXCLUDED.fetch_cost,
                fetch_latency_ms = EXCLUDED.fetch_latency_ms,
                fetched_at = NOW()
        """

        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    ctx.symbol_id,
                    ctx.date,
                    json.dumps(ctx.valuation),
                    ctx.fetch_cost,
                    ctx.fetch_latency_ms,
                ),
            )

        logger.info(
            "FundamentalContext UPSERT symbol=%s date=%s valuation_pe_ttm=%s elapsed_ms=%d",
            ctx.symbol_id,
            ctx.date,
            ctx.valuation.get("pe_ttm"),
            ctx.fetch_latency_ms,
        )

        return FundamentalIngestStats(
            symbol_id=ctx.symbol_id,
            date=ctx.date,
            valuation_filled=True,
            fetch_latency_ms=ctx.fetch_latency_ms,
        )
