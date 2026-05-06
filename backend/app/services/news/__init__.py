"""News services 子包 — V3 §3.2 NewsClassifierService L0.2 sediment.

scope (sub-PR 7b.2):
- NewsClassifierService: V4-Flash 分类服务 (RiskTaskType.NEWS_CLASSIFY)
- ClassificationResult: V3§3.2 line 365-376 输出 schema dataclass

defer sub-PR 7b.3:
- application bootstrap 真 wire conn_factory + DataPipeline persist hook
- e2e live tests (requires_litellm_e2e marker)

defer Sprint 3+:
- NewsIngestionService (V3 line 1222) — 6 源 News 接入 + DataPipeline + news_raw 入库
- AnnouncementProcessor (V3 line 1225) — 公告流 (巨潮/交易所 RSS)

关联:
- V3 line 1222-1225 (services/news/ 子包 真预约 path)
- V3 §3.2 line 359-393 (NewsClassifier V4-Flash 完整 schema)
- ADR-031 §6 line 133 "Sprint 后续" (NewsClassifier wire defer 真预约)
- ADR-035 §2 (V4 路由层 0 智谱 alias, NewsClassifier 走 deepseek-v4-flash)
- ADR-036 (BULL/BEAR V4-Pro mapping 沿用)
- sub-PR 7b.1 v2 (#240, news_raw + news_classified DDL 双表 sediment)
"""
from __future__ import annotations

from .bootstrap import get_news_classifier, reset_news_classifier
from .news_classifier_service import ClassificationResult, NewsClassifierService
from .news_ingestion_service import IngestionStats, NewsIngestionService

__all__ = [
    "ClassificationResult",
    "IngestionStats",
    "NewsClassifierService",
    "NewsIngestionService",
    "get_news_classifier",
    "reset_news_classifier",
]
