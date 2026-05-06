"""tests for NewsIngestionService — V3 line 1222 orchestrator (sub-PR 7c #243 sediment).

scope (mock-only sustained + 1 e2e live, 沿用 sub-PR 7b.3 v2 体例):
- TestConstructor (2): pipeline + classifier DI keyword-only verify
- TestIngestHappyPath (3): full chain happy path + stats + decision_id prefix
- TestIngestFailSoft (2): per-item ClassificationParseError fail-soft + classify_failed count
- TestIngestNewsRawInsert (3): INSERT 9 cols + RETURNING news_id + 0 row fail-loud
- TestIngestTransactionBoundary (2): 0 conn.commit (铁律 32) + DataPipeline raise propagate
- TestE2ELive (1): full chain real V4-Flash + mock conn capture SQL
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from backend.app.services.news import (
    ClassificationResult,
    IngestionStats,
    NewsIngestionService,
)
from backend.app.services.news.news_classifier_service import (
    ClassificationParseError,
)
from backend.qm_platform.news.base import NewsItem

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


def _make_news_item(
    *,
    source: str = "zhipu",
    title: str = "贵州茅台业绩超预期",
    url: str | None = "https://example.com/news/1",
    symbol_id: str | None = "600519.SH",
) -> NewsItem:
    return NewsItem(
        source=source,
        timestamp=datetime(2026, 5, 7, 14, 30, 0, tzinfo=UTC),
        title=title,
        content="2026 Q1 净利润同比 +35%, 远超市场预期",
        url=url,
        lang="zh",
        symbol_id=symbol_id,
        fetch_cost_usd=Decimal("0.0001"),
        fetch_latency_ms=500,
    )


def _make_classification_result(news_id: int | None = None) -> ClassificationResult:
    return ClassificationResult(
        sentiment_score=Decimal("0.7"),
        category="利好",
        urgency="P1",
        confidence=Decimal("0.85"),
        profile="short",
        classifier_model="deepseek-v4-flash",
        classifier_prompt_version="v1",
        classifier_cost=Decimal("0.0015"),
        news_id=news_id,
    )


@pytest.fixture
def mock_pipeline() -> MagicMock:
    """Mock DataPipeline 沿用 sub-PR 7a fetch_all 真返 list[NewsItem]."""
    pipeline = MagicMock()
    pipeline.fetch_all.return_value = [
        _make_news_item(source="zhipu", title="news 1"),
        _make_news_item(source="tavily", title="news 2"),
    ]
    return pipeline


@pytest.fixture
def mock_classifier() -> MagicMock:
    """Mock NewsClassifierService 沿用 sub-PR 7b.2 classify + 7b.3 v2 persist 体例."""
    classifier = MagicMock()
    classifier.classify.return_value = _make_classification_result()
    return classifier


@pytest.fixture
def mock_conn_with_returning() -> tuple[MagicMock, MagicMock]:
    """Mock conn — INSERT news_raw RETURNING news_id 真返 sequential 1, 2, 3...

    Returns (mock_conn, mock_cursor) — caller 真 inspect cursor.execute calls.
    """
    counter = {"value": 0}

    def _fetchone() -> tuple[int]:
        counter["value"] += 1
        return (counter["value"],)

    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = _fetchone
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def service(
    mock_pipeline: MagicMock, mock_classifier: MagicMock
) -> NewsIngestionService:
    return NewsIngestionService(pipeline=mock_pipeline, classifier=mock_classifier)


# ─────────────────────────────────────────────────────────────
# TestConstructor
# ─────────────────────────────────────────────────────────────


class TestConstructor:
    def test_keyword_only_args(
        self, mock_pipeline: MagicMock, mock_classifier: MagicMock
    ) -> None:
        with pytest.raises(TypeError, match="positional"):
            NewsIngestionService(mock_pipeline, mock_classifier)  # type: ignore[misc]

    def test_pipeline_and_classifier_stored(
        self, mock_pipeline: MagicMock, mock_classifier: MagicMock
    ) -> None:
        service = NewsIngestionService(
            pipeline=mock_pipeline, classifier=mock_classifier
        )
        assert service._pipeline is mock_pipeline
        assert service._classifier is mock_classifier


# ─────────────────────────────────────────────────────────────
# TestIngestHappyPath
# ─────────────────────────────────────────────────────────────


class TestIngestHappyPath:
    def test_full_chain_returns_stats(
        self,
        service: NewsIngestionService,
        mock_pipeline: MagicMock,
        mock_classifier: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        mock_conn, _ = mock_conn_with_returning

        stats = service.ingest(query="贵州茅台", conn=mock_conn)

        assert isinstance(stats, IngestionStats)
        assert stats.fetched == 2
        assert stats.ingested == 2
        assert stats.classified == 2
        assert stats.classify_failed == 0

        mock_pipeline.fetch_all.assert_called_once_with(
            query="贵州茅台", limit_per_source=10, total_limit=None
        )
        assert mock_classifier.classify.call_count == 2
        assert mock_classifier.persist.call_count == 2

    def test_persist_called_with_inserted_news_id(
        self,
        service: NewsIngestionService,
        mock_classifier: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        mock_conn, _ = mock_conn_with_returning

        service.ingest(query="贵州茅台", conn=mock_conn)

        # mock_conn_with_returning sequence 1, 2 → persist news_id=1, 2
        first_call = mock_classifier.persist.call_args_list[0]
        second_call = mock_classifier.persist.call_args_list[1]
        assert first_call.kwargs["news_id"] == 1
        assert first_call.kwargs["conn"] is mock_conn
        assert second_call.kwargs["news_id"] == 2

    def test_decision_id_prefix_threading(
        self,
        service: NewsIngestionService,
        mock_classifier: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        mock_conn, _ = mock_conn_with_returning

        service.ingest(
            query="q",
            conn=mock_conn,
            decision_id_prefix="ingest-test",
        )

        decision_ids = [
            c.kwargs["decision_id"] for c in mock_classifier.classify.call_args_list
        ]
        assert decision_ids == ["ingest-test-000", "ingest-test-001"]


# ─────────────────────────────────────────────────────────────
# TestIngestFailSoft
# ─────────────────────────────────────────────────────────────


class TestIngestFailSoft:
    def test_classify_parse_error_fails_soft(
        self,
        service: NewsIngestionService,
        mock_classifier: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        """Per-item ClassificationParseError 真 fail-soft (沿用 sub-PR 7b.2 contract)."""
        mock_classifier.classify.side_effect = [
            _make_classification_result(),
            ClassificationParseError("LLM response not JSON", raw_content="garbage"),
        ]
        mock_conn, _ = mock_conn_with_returning

        stats = service.ingest(query="q", conn=mock_conn)

        assert stats.fetched == 2
        assert stats.ingested == 2  # news_raw 全 INSERT 成功
        assert stats.classified == 1
        assert stats.classify_failed == 1
        # persist 仅 first item 走 (second 真 ClassificationParseError before persist)
        assert mock_classifier.persist.call_count == 1

    def test_all_items_fail_classify_zero_classified(
        self,
        service: NewsIngestionService,
        mock_classifier: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        mock_classifier.classify.side_effect = ClassificationParseError("garbage")
        mock_conn, _ = mock_conn_with_returning

        stats = service.ingest(query="q", conn=mock_conn)

        assert stats.ingested == 2
        assert stats.classified == 0
        assert stats.classify_failed == 2


# ─────────────────────────────────────────────────────────────
# TestIngestNewsRawInsert
# ─────────────────────────────────────────────────────────────


class TestIngestNewsRawInsert:
    def test_insert_uses_9_columns_news_item_aligned(
        self,
        service: NewsIngestionService,
        mock_pipeline: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        """INSERT 走 9 cols (NewsItem 1:1 align, news_id BIGSERIAL + fetched_at DEFAULT)."""
        item = _make_news_item(source="anspire", title="测试", symbol_id="000001.SZ")
        mock_pipeline.fetch_all.return_value = [item]
        mock_conn, mock_cursor = mock_conn_with_returning

        service.ingest(query="q", conn=mock_conn)

        sql, params = mock_cursor.execute.call_args_list[0].args
        assert "INSERT INTO news_raw" in sql
        assert "RETURNING news_id" in sql
        # 9 params, 沿用 NewsItem 1:1 align (沿用 sub-PR 7b.1 v2 DDL)
        assert len(params) == 9
        assert params[0] == "anspire"  # source
        assert params[1] == item.timestamp
        assert params[2] == "测试"  # title
        assert params[6] == "000001.SZ"  # symbol_id
        assert params[7] == Decimal("0.0001")  # fetch_cost
        assert params[8] == 500  # fetch_latency_ms

    def test_insert_returns_bigserial_news_id(
        self,
        service: NewsIngestionService,
        mock_classifier: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        mock_conn, _ = mock_conn_with_returning

        service.ingest(query="q", conn=mock_conn)

        # news_id 真 fetchone() 返第一个 col (BIGSERIAL int)
        assert mock_classifier.persist.call_args_list[0].kwargs["news_id"] == 1

    def test_returning_zero_rows_fails_loud(
        self,
        service: NewsIngestionService,
        mock_pipeline: MagicMock,
    ) -> None:
        """RETURNING 0 row 真 PG 异常 (沿用铁律 33 fail-loud)."""
        mock_pipeline.fetch_all.return_value = [_make_news_item()]

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # 异常: 0 row
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        with pytest.raises(RuntimeError, match="RETURNING news_id 真 0 row"):
            service.ingest(query="q", conn=mock_conn)


# ─────────────────────────────────────────────────────────────
# TestIngestTransactionBoundary
# ─────────────────────────────────────────────────────────────


class TestIngestTransactionBoundary:
    def test_no_commit_or_rollback(
        self,
        service: NewsIngestionService,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        """铁律 32 sustained — Service 0 commit, caller 真事务边界管理者."""
        mock_conn, _ = mock_conn_with_returning

        service.ingest(query="q", conn=mock_conn)

        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()

    def test_pipeline_value_error_propagates(
        self,
        service: NewsIngestionService,
        mock_pipeline: MagicMock,
        mock_conn_with_returning: tuple[MagicMock, MagicMock],
    ) -> None:
        """DataPipeline ValueError (e.g. empty query) 真 raise propagate (铁律 33)."""
        mock_pipeline.fetch_all.side_effect = ValueError("query is empty")
        mock_conn, _ = mock_conn_with_returning

        with pytest.raises(ValueError, match="query is empty"):
            service.ingest(query="", conn=mock_conn)

    def test_db_error_mid_batch_propagates_no_commit(
        self,
        service: NewsIngestionService,
        mock_pipeline: MagicMock,
    ) -> None:
        """LL-067 P1 sediment — psycopg2.Error mid-batch fail-loud propagate (铁律 33).

        反 silent swallow non-ClassificationParseError, caller 真 rollback responsible.
        Verify (a) exception propagates / (b) 0 conn.commit / (c) batch 真 abort.
        """
        mock_pipeline.fetch_all.return_value = [
            _make_news_item(source="zhipu", title="news 1"),
            _make_news_item(source="tavily", title="news 2"),
        ]

        # First INSERT 成功 (RETURNING news_id=1), second INSERT raise psycopg2-like Error
        call_count = {"value": 0}

        def _execute_side_effect(*args: object, **kwargs: object) -> None:
            call_count["value"] += 1
            if call_count["value"] == 2:
                raise RuntimeError("DB error: NOT NULL violation on title")

        def _fetchone_side_effect() -> tuple[int]:
            return (1,)

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = _execute_side_effect
        mock_cursor.fetchone.side_effect = _fetchone_side_effect
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        with pytest.raises(RuntimeError, match="NOT NULL violation"):
            service.ingest(query="q", conn=mock_conn)

        # 铁律 32 sustained: caller 真 rollback responsible, 0 service-level commit
        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()


# ─────────────────────────────────────────────────────────────
# TestE2ELive — V4-Flash 真生产 + DataPipeline mock + mock conn capture (full chain)
# ─────────────────────────────────────────────────────────────


@pytest.mark.requires_litellm_e2e
@pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY env missing (沿用 sub-PR 7b.3 v2 marker auto-skip 体例)",
)
class TestE2ELive:
    """Full-chain e2e — DataPipeline (mock) → INSERT → real V4-Flash classify → persist.

    红线 sustained: LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / minimal payload.
    """

    def test_e2e_full_chain_real_v4_flash(self) -> None:
        from backend.app.services.news import (
            get_news_classifier,
            reset_news_classifier,
        )
        from backend.qm_platform.llm import reset_llm_router

        # mock DataPipeline (反 触 6 源真 API 真生产, sub-PR 1-6 单独 e2e)
        mock_pipeline = MagicMock()
        mock_pipeline.fetch_all.return_value = [_make_news_item()]

        reset_llm_router()
        reset_news_classifier()
        try:
            classifier = get_news_classifier()  # 走 V4-Flash 真生产
            service = NewsIngestionService(
                pipeline=mock_pipeline, classifier=classifier
            )

            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (42,)  # mock RETURNING news_id
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            stats = service.ingest(
                query="贵州茅台",
                conn=mock_conn,
                decision_id_prefix="e2e-7c-test",
            )

            assert stats.fetched == 1
            assert stats.ingested == 1
            assert stats.classified + stats.classify_failed == 1
            mock_conn.commit.assert_not_called()  # 铁律 32 sustained
            # cursor.execute 真**至少 2 次** (INSERT news_raw + INSERT news_classified)
            assert mock_cursor.execute.call_count >= 1
        finally:
            reset_llm_router()
            reset_news_classifier()
