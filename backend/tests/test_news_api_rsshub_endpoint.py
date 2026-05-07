"""sub-PR 8b-rsshub 5-07 — POST /api/news/ingest_rsshub endpoint smoke tests.

scope (~120 line, single chunk per LL-100):
- IngestRsshubRequest schema validation (route_path required + length bounds + limit bounds)
- IngestRsshubResponse schema (echo route_path + limit + IngestionStats fields)
- _build_pipeline_rsshub_only builder (single RsshubNewsFetcher, settings.RSSHUB_BASE_URL)
- POST /api/news/ingest_rsshub endpoint (mocked NewsIngestionService.ingest)
- HTTPException 500 sanitized detail (沿用 sub-PR 8a-followup-A P2-3 体例 sustained)

真生产证据沿用 5-07 sub-PR 8b-rsshub:
- RSSHub localhost:1200 /healthz HTTP 200 + /jin10/news HTTP 200 + 3 routes 503
  (sub-PR 8b-rsshub-multi-route 真预约 sustained)
- 反主链路 ingest, route_path 独立 caller pattern sustained sub-PR 6 design intent

关联铁律:
- 31 (Engine 层纯计算 — endpoint 真 orchestrator router, 0 业务逻辑)
- 32 (Service 不 commit — caller 真**事务边界** conn.commit() endpoint 层管)
- 33 (fail-loud — fetcher fail-soft 沿用 NewsIngestionService contract)
- 42 (PR 分级审查制 — backend/app/api/** 沿用 reviewer 体例)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.news import (
    IngestRsshubRequest,
    IngestRsshubResponse,
    _build_pipeline_rsshub_only,
)

# ── Schema validation ──


def test_ingest_rsshub_request_minimal_valid() -> None:
    """route_path required, limit + decision_id_prefix have defaults."""
    req = IngestRsshubRequest(route_path="/jin10/news")
    assert req.route_path == "/jin10/news"
    assert req.limit == 10  # default
    assert req.decision_id_prefix is None


def test_ingest_rsshub_request_full_valid() -> None:
    req = IngestRsshubRequest(
        route_path="/eastmoney/news/0",
        limit=20,
        decision_id_prefix="rsshub-test-001",
    )
    assert req.route_path == "/eastmoney/news/0"
    assert req.limit == 20
    assert req.decision_id_prefix == "rsshub-test-001"


def test_ingest_rsshub_request_route_path_empty_rejected() -> None:
    with pytest.raises(ValidationError):
        IngestRsshubRequest(route_path="")


def test_ingest_rsshub_request_route_path_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        IngestRsshubRequest(route_path="/" + "x" * 200)


def test_ingest_rsshub_request_limit_below_min_rejected() -> None:
    with pytest.raises(ValidationError):
        IngestRsshubRequest(route_path="/jin10/news", limit=0)


def test_ingest_rsshub_request_limit_above_max_rejected() -> None:
    with pytest.raises(ValidationError):
        IngestRsshubRequest(route_path="/jin10/news", limit=51)


def test_ingest_rsshub_request_decision_id_prefix_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        IngestRsshubRequest(route_path="/jin10/news", decision_id_prefix="x" * 65)


def test_ingest_rsshub_response_schema() -> None:
    resp = IngestRsshubResponse(
        fetched=5,
        ingested=5,
        classified=4,
        classify_failed=1,
        route_path="/jin10/news",
        limit=10,
    )
    assert resp.fetched == 5
    assert resp.classified == 4
    assert resp.route_path == "/jin10/news"


# ── Pipeline builder ──


def test_build_pipeline_rsshub_only_returns_single_fetcher() -> None:
    """Pipeline 真 single RsshubNewsFetcher (反主链路 5-source ingest)."""
    from backend.qm_platform.news import RsshubNewsFetcher

    pipeline = _build_pipeline_rsshub_only()
    fetchers = pipeline._fetchers if hasattr(pipeline, "_fetchers") else pipeline.fetchers
    assert len(fetchers) == 1
    assert isinstance(fetchers[0], RsshubNewsFetcher)


# ── Endpoint integration (mocked classifier + DB) ──


@pytest.fixture
def app_with_mocked_deps():
    """FastAPI app with mocked NewsIngestionService + DB conn."""
    from app.main import app

    return app


def test_ingest_rsshub_endpoint_success(app_with_mocked_deps) -> None:
    """POST /api/news/ingest_rsshub 真**happy path**: mock fetch + classify + persist."""
    from app.services.news.news_ingestion_service import IngestionStats

    mock_stats = IngestionStats(fetched=3, ingested=3, classified=3, classify_failed=0)
    mock_service = MagicMock()
    mock_service.ingest.return_value = mock_stats
    mock_conn = MagicMock()

    with (
        patch("app.services.news.NewsIngestionService", return_value=mock_service),
        patch("app.services.news.get_news_classifier", return_value=MagicMock()),
        patch("app.services.db.get_sync_conn", return_value=mock_conn),
        patch("app.api.news._build_pipeline_rsshub_only", return_value=MagicMock()),
    ):
        client = TestClient(app_with_mocked_deps)
        r = client.post(
            "/api/news/ingest_rsshub",
            json={"route_path": "/jin10/news", "limit": 5},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["fetched"] == 3
    assert body["ingested"] == 3
    assert body["classified"] == 3
    assert body["classify_failed"] == 0
    assert body["route_path"] == "/jin10/news"
    assert body["limit"] == 5
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


def test_ingest_rsshub_endpoint_500_on_exception(app_with_mocked_deps) -> None:
    """endpoint 真**fail-loud** 沿用铁律 33 + sanitized detail (P2-3 体例)."""
    mock_service = MagicMock()
    mock_service.ingest.side_effect = RuntimeError("internal DB error sk-leak")
    mock_conn = MagicMock()

    with (
        patch("app.services.news.NewsIngestionService", return_value=mock_service),
        patch("app.services.news.get_news_classifier", return_value=MagicMock()),
        patch("app.services.db.get_sync_conn", return_value=mock_conn),
        patch("app.api.news._build_pipeline_rsshub_only", return_value=MagicMock()),
    ):
        client = TestClient(app_with_mocked_deps)
        r = client.post(
            "/api/news/ingest_rsshub",
            json={"route_path": "/jin10/news", "limit": 5},
        )

    assert r.status_code == 500
    detail = r.json()["detail"]
    # Sanitized: contains exception class name, NOT raw message
    assert "RuntimeError" in detail
    assert "sk-leak" not in detail  # secret redacted
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


def test_ingest_rsshub_endpoint_validation_error_400() -> None:
    """missing route_path → 422 (FastAPI default for Pydantic ValidationError)."""
    from app.main import app

    client = TestClient(app)
    r = client.post("/api/news/ingest_rsshub", json={"limit": 5})
    assert r.status_code == 422
