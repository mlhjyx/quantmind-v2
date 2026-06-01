"""Route-level tests for manual news ops endpoints.

These tests keep API coverage taxonomy grounded without calling external news
sources, LLM providers, or the live database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_ingest_news_manual_endpoint_success() -> None:
    """POST /api/news/ingest commits mocked ingestion stats."""
    from app.main import app
    from app.services.news.news_ingestion_service import IngestionStats

    mock_stats = IngestionStats(fetched=4, ingested=3, classified=2, classify_failed=1)
    mock_service = MagicMock()
    mock_service.ingest.return_value = mock_stats
    mock_conn = MagicMock()

    with (
        patch("app.api.news._build_pipeline_5_sources", return_value=MagicMock()),
        patch("app.services.news.NewsIngestionService", return_value=mock_service),
        patch("app.services.news.get_news_classifier", return_value=MagicMock()),
        patch("app.services.db.get_sync_conn", return_value=mock_conn),
    ):
        response = TestClient(app).post(
            "/api/news/ingest",
            json={"query": "risk alert", "limit_per_source": 2},
        )

    assert response.status_code == 200
    assert response.json() == {
        "fetched": 4,
        "ingested": 3,
        "classified": 2,
        "classify_failed": 1,
        "query": "risk alert",
        "limit_per_source": 2,
    }
    mock_service.ingest.assert_called_once_with(
        query="risk alert",
        conn=mock_conn,
        limit_per_source=2,
        decision_id_prefix=None,
    )
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_ingest_news_manual_endpoint_sanitizes_failures() -> None:
    """POST /api/news/ingest rolls back and hides raw internal messages."""
    from app.main import app

    mock_service = MagicMock()
    mock_service.ingest.side_effect = RuntimeError("dsn password leak")
    mock_conn = MagicMock()

    with (
        patch("app.api.news._build_pipeline_5_sources", return_value=MagicMock()),
        patch("app.services.news.NewsIngestionService", return_value=mock_service),
        patch("app.services.news.get_news_classifier", return_value=MagicMock()),
        patch("app.services.db.get_sync_conn", return_value=mock_conn),
    ):
        response = TestClient(app).post(
            "/api/news/ingest",
            json={"query": "risk alert", "limit_per_source": 2},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "ingestion failed: RuntimeError"
    assert "password" not in response.text
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


def test_ingest_announcement_endpoint_success() -> None:
    """POST /api/news/ingest_announcement commits mocked announcement stats."""
    from app.main import app
    from app.services.news.announcement_processor import AnnouncementStats

    mock_stats = AnnouncementStats(
        fetched=5,
        ingested=2,
        skipped_earnings=2,
        skipped_unknown=1,
    )
    mock_processor = MagicMock()
    mock_processor.ingest.return_value = mock_stats
    mock_conn = MagicMock()

    with (
        patch("app.api.news._build_pipeline_announcement_akshare", return_value=MagicMock()),
        patch("app.services.news.AnnouncementProcessor", return_value=mock_processor),
        patch("app.services.db.get_sync_conn", return_value=mock_conn),
    ):
        response = TestClient(app).post(
            "/api/news/ingest_announcement",
            json={"symbol_id": "600519", "source": "cninfo", "limit": 5},
        )

    assert response.status_code == 200
    assert response.json() == {
        "fetched": 5,
        "ingested": 2,
        "skipped_earnings": 2,
        "skipped_unknown": 1,
        "symbol_id": "600519",
        "source": "cninfo",
        "limit": 5,
    }
    mock_processor.ingest.assert_called_once_with(
        symbol_id="600519",
        source="cninfo",
        conn=mock_conn,
        limit=5,
    )
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_news_stats_endpoint_returns_counts_and_samples() -> None:
    """GET /api/news/stats maps DB rows to the public diagnostics shape."""
    from app.main import app

    now = datetime(2026, 6, 1, 10, 30, tzinfo=UTC)
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [(2,), (1,)]
    mock_cursor.fetchall.side_effect = [
        [(42, "rsshub", "A title longer than usual", now, now)],
        [(42, Decimal("0.75"), "macro", "high", "bull", "deepseek-v4", now)],
    ]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("app.services.db.get_sync_conn", return_value=mock_conn):
        response = TestClient(app).get("/api/news/stats")

    assert response.status_code == 200
    assert response.json() == {
        "news_raw_24h_count": 2,
        "news_classified_24h_count": 1,
        "last_5_news_raw": [
            {
                "news_id": 42,
                "source": "rsshub",
                "title": "A title longer than usual",
                "timestamp": now.isoformat(),
                "fetched_at": now.isoformat(),
            }
        ],
        "last_5_news_classified": [
            {
                "news_id": 42,
                "sentiment_score": 0.75,
                "category": "macro",
                "urgency": "high",
                "profile": "bull",
                "classifier_model": "deepseek-v4",
                "classified_at": now.isoformat(),
            }
        ],
    }
    assert mock_cursor.execute.call_count == 4
    mock_conn.close.assert_called_once()
