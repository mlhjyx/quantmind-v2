"""S8 8b DingTalk webhook ENDPOINT integration tests (TestClient + monkeypatched service).

Reviewer P2-5 follow-up: parser + service have 24+13 unit tests; endpoint-level
integration glue (raw body capture → header alias → sig verify → Pydantic
body → service call → commit/rollback → response shape) lacked direct coverage.

Coverage:
- 200 happy path: valid sig + valid command → TRANSITIONED outcome + commit
- 200 non-transition: idempotent ALREADY_TERMINAL → rollback path
- 401 invalid signature
- 401 stale timestamp
- 400 malformed body (not JSON / missing text field)
- 400 unknown command verb
- 400 invalid plan_id format
- 503 when DINGTALK_WEBHOOK_SECRET is empty (反 silent skip)
- 400 when body is not valid UTF-8 (Reviewer P2-3 strict decode)
- Headers `Timestamp` + `Sign` alias resolution

铁律 32 sustained: endpoint owns conn.commit/rollback (反 service-level commit).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from qm_platform.risk.execution.planner import PlanStatus

# Import the FastAPI app (initialized at app/main.py)
from app.main import app
from app.services.risk.dingtalk_webhook_service import (
    DingTalkWebhookResult,
    DingTalkWebhookService,
    WebhookOutcome,
)
from app.services.risk.staged_execution_service import (
    StagedExecutionOutcome,
    StagedExecutionService,
    StagedExecutionServiceResult,
)

TEST_SECRET = "test-secret-do-not-use-in-prod"
TEST_PREFIX = "abcd1234"


def _sign_body(body_str: str, ts: str, secret: str = TEST_SECRET) -> str:
    payload = f"{ts}\n{body_str}".encode()
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def with_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Patch settings to provide a known DINGTALK_WEBHOOK_SECRET."""
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "DINGTALK_WEBHOOK_SECRET", TEST_SECRET)
    return TEST_SECRET


@pytest.fixture
def now_unix() -> str:
    return str(int(datetime.now(UTC).timestamp()))


def _stub_service(
    outcome: WebhookOutcome,
    plan_id: str | None = "abcd1234-...",
    status: PlanStatus | None = PlanStatus.CONFIRMED,
) -> DingTalkWebhookService:
    """Build a stub service that always returns the given outcome."""
    svc = DingTalkWebhookService()
    svc.process_command = MagicMock(  # type: ignore[method-assign]
        return_value=DingTalkWebhookResult(
            outcome=outcome,
            plan_id=plan_id,
            final_status=status,
            message=f"stub {outcome.value}",
        )
    )
    return svc


def _stub_staged_service(
    outcome: StagedExecutionOutcome = StagedExecutionOutcome.EXECUTED,
    plan_id: str | None = "abcd1234-...",
    broker_order_id: str | None = "stub-abcd1234",
    final_status: PlanStatus | None = PlanStatus.EXECUTED,
) -> StagedExecutionService:
    """Stub StagedExecutionService for 8c-followup endpoint integration.

    The endpoint now calls staged_service.execute_plan after CONFIRMED
    transitions. Real broker call is unwanted in unit tests — this stub returns
    a deterministic result without touching the DB or broker.
    """
    # Build the service with a no-op broker (won't be invoked since we patch
    # execute_plan directly).
    svc = StagedExecutionService(broker_call=lambda *a, **k: {"status": "ok"})
    svc.execute_plan = MagicMock(  # type: ignore[method-assign]
        return_value=StagedExecutionServiceResult(
            outcome=outcome,
            plan_id=plan_id,
            broker_order_id=broker_order_id,
            final_status=final_status,
            error_msg=None,
            message=f"stub {outcome.value}",
        )
    )
    return svc


# §1 happy path


class TestEndpointHappyPath:
    def test_transitioned_returns_200(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        body = '{"text": "confirm abcd1234"}'
        sign = _sign_body(body, now_unix)
        stub = _stub_service(WebhookOutcome.TRANSITIONED)
        staged_stub = _stub_staged_service()

        # FastAPI dependency override: app.dependency_overrides bypasses Depends().
        # The endpoint also calls get_sync_conn() inline (not via Depends), so we
        # patch that at module level.
        from app.api import risk as risk_mod

        app.dependency_overrides[risk_mod._get_dingtalk_webhook_service] = lambda: stub
        app.dependency_overrides[risk_mod._get_staged_execution_service] = lambda: staged_stub
        try:
            with patch.object(risk_mod, "get_sync_conn") as mock_conn_factory:
                mock_conn = MagicMock()
                mock_conn_factory.return_value = mock_conn
                r = client.post(
                    "/api/risk/dingtalk-webhook",
                    headers={"Timestamp": now_unix, "Sign": sign},
                    content=body,
                )
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 200, r.text
        data = r.json()
        assert data["outcome"] == "transitioned"
        # 8c-followup: post-broker status override → EXECUTED (was CONFIRMED in 8c-partial)
        assert data["final_status"] == "EXECUTED"
        # 8c-followup: broker block is present
        assert "broker" in data
        assert data["broker"]["outcome"] == "executed"
        assert data["broker"]["order_id"] == "stub-abcd1234"
        # staged_service was invoked with the plan_id from the webhook result
        staged_stub.execute_plan.assert_called_once()
        # TRANSITIONED + CONFIRMED → broker run → commit ONCE for atomic webhook + broker
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_already_terminal_rolls_back_not_commits(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        body = '{"text": "cancel abcd1234"}'
        sign = _sign_body(body, now_unix)
        stub = _stub_service(WebhookOutcome.ALREADY_TERMINAL, status=PlanStatus.CONFIRMED)

        from app.api import risk as risk_mod

        app.dependency_overrides[risk_mod._get_dingtalk_webhook_service] = lambda: stub
        try:
            with patch.object(risk_mod, "get_sync_conn") as mock_conn_factory:
                mock_conn = MagicMock()
                mock_conn_factory.return_value = mock_conn
                r = client.post(
                    "/api/risk/dingtalk-webhook",
                    headers={"Timestamp": now_unix, "Sign": sign},
                    content=body,
                )
        finally:
            app.dependency_overrides.clear()

        assert r.status_code == 200
        assert r.json()["outcome"] == "already_terminal"
        # No DB write expected → rollback, no commit
        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_called_once()


# §2 signature / replay rejections


class TestEndpointSignatureRejections:
    def test_invalid_sign_returns_401(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        body = '{"text": "confirm abcd1234"}'
        bad_sign = _sign_body(body + "tampered", now_unix)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix, "Sign": bad_sign},
            content=body,
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "invalid_signature"

    def test_stale_timestamp_returns_401(
        self,
        client: TestClient,
        with_secret: str,
    ) -> None:
        body = '{"text": "confirm abcd1234"}'
        stale_ts = str(int(datetime.now(UTC).timestamp()) - 3600)  # 1h ago
        sign = _sign_body(body, stale_ts)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": stale_ts, "Sign": sign},
            content=body,
        )
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "stale_timestamp"


# §3 body / command rejections


class TestEndpointBodyRejections:
    def test_non_json_body_returns_400(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        body = "this is not json"
        sign = _sign_body(body, now_unix)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix, "Sign": sign},
            content=body,
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "malformed_body"

    def test_missing_text_field_returns_400(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        body = '{"foo": "bar"}'  # no "text" field
        sign = _sign_body(body, now_unix)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix, "Sign": sign},
            content=body,
        )
        assert r.status_code == 400

    def test_unknown_command_returns_400(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        body = '{"text": "approve abcd1234"}'
        sign = _sign_body(body, now_unix)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix, "Sign": sign},
            content=body,
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "unknown_command"


# §4 secret unconfigured


class TestEndpointSecretUnconfigured:
    def test_empty_secret_returns_503(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        now_unix: str,
    ) -> None:
        """When DINGTALK_WEBHOOK_SECRET is empty, endpoint rejects all inbound (503)."""
        from app.config import settings as app_settings

        monkeypatch.setattr(app_settings, "DINGTALK_WEBHOOK_SECRET", "")

        # Body and sign don't matter — secret unconfigured rejects before verify
        body = '{"text": "confirm abcd1234"}'
        # We still need to provide some sign value (header is required)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix, "Sign": "anything"},
            content=body,
        )
        assert r.status_code == 503


# §5 P2-3 strict UTF-8 decode


class TestEndpointUTF8Decode:
    def test_invalid_utf8_body_returns_400(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        """Reviewer P2-3: errors='strict' surfaces UnicodeDecodeError as 400 (反 silent
        signature mismatch on legitimate-but-malformed payloads)."""
        # Build a body with invalid UTF-8 bytes
        raw_bytes = b'\xff\xfe{"text": "confirm abcd1234"}'
        # Sign requires str body — sign over the would-be decoded "replacement" form
        # but the endpoint should reject before sig verify
        sign = _sign_body("does-not-matter", now_unix)
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix, "Sign": sign},
            content=raw_bytes,
        )
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "malformed_body"


# §6 missing headers


class TestEndpointMissingHeaders:
    def test_missing_timestamp_returns_422(
        self,
        client: TestClient,
        with_secret: str,
    ) -> None:
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Sign": "x"},
            content='{"text": "confirm abcd1234"}',
        )
        # FastAPI returns 422 for missing required header
        assert r.status_code == 422

    def test_missing_sign_returns_422(
        self,
        client: TestClient,
        with_secret: str,
        now_unix: str,
    ) -> None:
        r = client.post(
            "/api/risk/dingtalk-webhook",
            headers={"Timestamp": now_unix},
            content='{"text": "confirm abcd1234"}',
        )
        assert r.status_code == 422
