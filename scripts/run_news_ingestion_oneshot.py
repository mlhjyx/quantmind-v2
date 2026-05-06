"""Sprint 2 sub-PR 8a — News ingestion e2e standalone oneshot (5-07 sediment).

用法: python scripts/run_news_ingestion_oneshot.py [query] [limit_per_source]
默认: query="贵州茅台" limit_per_source=2

真核 task:
- 同 backend/app/api/news.py POST /api/news/ingest 真生产 caller wire 完全一致 path
- 反 FastAPI restart 风险 (sub-PR 8a e2e verify pre-restart 沿用)
- 5 News 源 fetch (Zhipu/Tavily/Anspire/GDELT/Marketaux) — RSSHub 不含 (sub-PR 8b 真预约)
- DataPipeline 6 源并行 + 早返回 + dedup (沿用 sub-PR 7a)
- NewsClassifierService.classify + persist (沿用 sub-PR 7b.2 + 7b.3 v2)
- LiteLLMRouter cost monitor + audit (沿用 Sprint 1 sub-PR #221-#226)

真生产 cost 估算 (limit_per_source=2):
- Tavily/Anspire: free tier 内
- Marketaux: free tier 内
- Zhipu GLM-4.7-Flash News: 永久免费 (ADR-035)
- GDELT/RSSHub: 0 cost
- DeepSeek V4-Flash classify: 6 源 × 2 = 12 article × ~$0.001 ≈ $0.012/run

红线 sustained:
- 0 broker call / 0 真发单 (LIVE_TRADING_DISABLED + EXECUTION_MODE=paper)
- News 数据 only / 0 portfolio mutation

关联:
- backend/app/api/news.py (sub-PR 8a, 真生产 production wire path)
- backend/app/services/news/news_ingestion_service.py (sub-PR 7c orchestrator)
- 铁律 25/32/33/41
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目路径 (沿用 _verify_account_oneshot.py:28-30 体例 + _project_root for backend.qm_platform)
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root / "backend"))
sys.path.append(str(_project_root))  # backend.qm_platform.* 真消费 _project_root


def main() -> int:
    """e2e oneshot run, 沿用 backend/app/api/news.py:ingest_news 完全一致 logic."""
    query = sys.argv[1] if len(sys.argv) > 1 else "贵州茅台"
    limit_per_source = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    print(f"[sub-PR 8a] query={query!r} limit_per_source={limit_per_source}")
    print("[sub-PR 8a] 5 sources: Zhipu/Tavily/Anspire/GDELT/Marketaux (RSSHub deferred)")

    from app.config import settings
    from app.services.db import get_sync_conn
    from app.services.news import NewsIngestionService, get_news_classifier
    from backend.qm_platform.news import (
        AnspireNewsFetcher,
        DataPipeline,
        GdeltNewsFetcher,
        MarketauxNewsFetcher,
        TavilyNewsFetcher,
        ZhipuNewsFetcher,
    )

    # 红线 verify (.env 3 项 sustained)
    print(f"[sub-PR 8a] EXECUTION_MODE={settings.EXECUTION_MODE}")
    print(f"[sub-PR 8a] LIVE_TRADING_DISABLED={settings.LIVE_TRADING_DISABLED}")
    if settings.EXECUTION_MODE != "paper" or not settings.LIVE_TRADING_DISABLED:
        print("[sub-PR 8a STOP] 红线漂移 — EXECUTION_MODE != paper 或 LIVE_TRADING_DISABLED != true")
        return 1

    # 5 fetcher init (沿用 backend/app/api/news.py:_build_pipeline_5_sources)
    fetchers = [
        ZhipuNewsFetcher(api_key=settings.ZHIPU_API_KEY, base_url=settings.ZHIPU_BASE_URL),
        TavilyNewsFetcher(api_key=settings.TAVILY_API_KEY, base_url=settings.TAVILY_BASE_URL),
        AnspireNewsFetcher(api_key=settings.ANSPIRE_API_KEY, base_url=settings.ANSPIRE_BASE_URL),
        GdeltNewsFetcher(base_url=settings.GDELT_BASE_URL),
        MarketauxNewsFetcher(api_key=settings.MARKETAUX_API_KEY, base_url=settings.MARKETAUX_BASE_URL),
    ]
    pipeline = DataPipeline(fetchers)
    classifier = get_news_classifier(conn_factory=get_sync_conn)
    service = NewsIngestionService(pipeline=pipeline, classifier=classifier)

    conn = get_sync_conn()
    try:
        stats = service.ingest(
            query=query,
            conn=conn,
            limit_per_source=limit_per_source,
        )
        conn.commit()
        print("[sub-PR 8a] ✅ commit OK")
    except Exception as exc:
        conn.rollback()
        print(f"[sub-PR 8a STOP] ingest failed: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 2
    finally:
        conn.close()

    print("[sub-PR 8a] stats:")
    print(f"  fetched          = {stats.fetched}")
    print(f"  ingested         = {stats.ingested}")
    print(f"  classified       = {stats.classified}")
    print(f"  classify_failed  = {stats.classify_failed}")

    # acceptance gate verify (production-level)
    if stats.fetched == 0:
        print("[sub-PR 8a WARN] fetched=0 — 全 5 源 fail-soft (sub-PR 7a contract), 检查网络 / API key / 配额")
        return 3
    if stats.ingested == 0:
        print("[sub-PR 8a STOP] ingested=0 — INSERT news_raw 0 row, 严重")
        return 4

    print("[sub-PR 8a] e2e ingestion ✅ — DB writes verified (caller wire 真生效)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
