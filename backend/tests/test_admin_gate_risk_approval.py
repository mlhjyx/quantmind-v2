"""Admin gate unit tests — risk.py + approval.py 6 endpoints (Finding E P1).

2026-04-30 治理债清理 (batch 1.7): 验证 X-Admin-Token header 真守门生效.

覆盖范围:
- risk.py:
  - POST /api/risk/l4-recovery/{strategy_id}  (request_l4_recovery)
  - POST /api/risk/l4-approve/{approval_id}   (approve_l4_recovery)
  - POST /api/risk/force-reset/{strategy_id}  (force_reset)
- approval.py:
  - POST /api/approval/queue/{id}/approve     (approve_queue_item)
  - POST /api/approval/queue/{id}/reject      (reject_queue_item)
  - POST /api/approval/queue/{id}/hold        (hold_queue_item)

测试矩阵:
- 6 endpoints × (no token + wrong token + correct token) = 18
- + 4 ADMIN_TOKEN 未配置 500 (1 risk + 3 approval)
- 总 22 unit tests

Note:
- 沿用 plain `!=` compare (D2.2 Finding 标 P2 timing attack), 留批 2 P2 单独修
- 2026-04-30 reviewer 采纳: shared `verify_admin_token` 在 app.core.auth (DRY P1)
- reviewer 采纳: uuid fixture per-test (P2) + _override_approval_db_with_mock 改 fixture (P2)
- reviewer 采纳: MagicMock for mock_result (sync result chain, P2)
- reviewer 采纳: approval 加对称 unconfigured 500 测试 (P2)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

# ────────────────────────────────────────────────────────────────────────────
# Helpers / Fixtures
# ────────────────────────────────────────────────────────────────────────────

VALID_TOKEN = "test-admin-token-for-unit-tests"
DUMMY_QUEUE_ITEM_ID = 1  # 整数, fixture 不必要


@pytest.fixture
def dummy_strategy_id() -> str:
    """每测试 fresh UUID, 防 module-level 跨测试相同 (reviewer P2 采纳)."""
    return str(uuid4())


@pytest.fixture
def dummy_approval_id() -> str:
    """每测试 fresh UUID."""
    return str(uuid4())


@pytest.fixture
def client_with_token(monkeypatch):
    """TestClient with settings.ADMIN_TOKEN configured to VALID_TOKEN."""
    monkeypatch.setattr(settings, "ADMIN_TOKEN", VALID_TOKEN)
    return TestClient(app)


@pytest.fixture
def client_no_token(monkeypatch):
    """TestClient with settings.ADMIN_TOKEN = '' (未配置)."""
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "")
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    """每个测试结束后清 dependency_overrides 防污染."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_approval_db():
    """Patch approval._get_db 返 mock session, 让 _get_queue_item.scalar_one_or_none() 返 None
    → endpoint raise HTTPException 404. auth 通过的真实证据 = 不返 401, 业务返 404 OK.

    防 reject/hold/approve 测试真打 PG (sync TestClient + async asyncpg event loop bleed).

    reviewer P2 采纳:
    - 改成 fixture (原 helper function 模式 fragile)
    - mock_result 用 MagicMock (CursorResult 是 sync, 非 awaitable; AsyncMock 是 mock_session)
    """
    from app.api.approval import _get_db

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[_get_db] = lambda: mock_session
    yield  # cleanup handled by autouse _cleanup_overrides


# ────────────────────────────────────────────────────────────────────────────
# risk.py: l4-recovery
# ────────────────────────────────────────────────────────────────────────────


class TestRiskL4RecoveryAdminGate:
    """POST /api/risk/l4-recovery/{strategy_id} admin gate."""

    def test_no_token_returns_401(self, client_with_token, dummy_strategy_id):
        """无 X-Admin-Token header → 401."""
        resp = client_with_token.post(
            f"/api/risk/l4-recovery/{dummy_strategy_id}?execution_mode=paper",
            json={"reviewer_note": "test"},
        )
        assert resp.status_code == 401
        assert "无效的Admin Token" in resp.json()["detail"]

    def test_wrong_token_returns_401(self, client_with_token, dummy_strategy_id):
        """错 X-Admin-Token → 401."""
        resp = client_with_token.post(
            f"/api/risk/l4-recovery/{dummy_strategy_id}?execution_mode=paper",
            json={"reviewer_note": "test"},
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token, dummy_strategy_id):
        """对 X-Admin-Token + bypass business → auth 通过 (业务返 200)."""
        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.request_l4_recovery = AsyncMock(return_value=uuid4())
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        resp = client_with_token.post(
            f"/api/risk/l4-recovery/{dummy_strategy_id}?execution_mode=paper",
            json={"reviewer_note": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code == 200, f"auth 应通过 但返 {resp.status_code}: {resp.text}"

    def test_admin_token_unconfigured_returns_500(self, client_no_token, dummy_strategy_id):
        """settings.ADMIN_TOKEN='' 未配置 → 500."""
        resp = client_no_token.post(
            f"/api/risk/l4-recovery/{dummy_strategy_id}?execution_mode=paper",
            json={"reviewer_note": "test"},
            headers={"X-Admin-Token": "any-token"},
        )
        assert resp.status_code == 500
        assert "ADMIN_TOKEN未配置" in resp.json()["detail"]


# ────────────────────────────────────────────────────────────────────────────
# risk.py: l4-approve
# ────────────────────────────────────────────────────────────────────────────


class TestRiskL4ApproveAdminGate:
    """POST /api/risk/l4-approve/{approval_id} admin gate."""

    def test_no_token_returns_401(self, client_with_token, dummy_approval_id):
        resp = client_with_token.post(
            f"/api/risk/l4-approve/{dummy_approval_id}",
            json={"approved": True, "reviewer_note": "ok"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token, dummy_approval_id):
        resp = client_with_token.post(
            f"/api/risk/l4-approve/{dummy_approval_id}",
            json={"approved": True, "reviewer_note": "ok"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token, dummy_approval_id):
        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.approve_l4_recovery = AsyncMock(return_value=None)
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        resp = client_with_token.post(
            f"/api/risk/l4-approve/{dummy_approval_id}",
            json={"approved": False, "reviewer_note": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code == 200, f"auth 应通过: {resp.status_code} {resp.text}"


# ────────────────────────────────────────────────────────────────────────────
# risk.py: force-reset
# ────────────────────────────────────────────────────────────────────────────


class TestRiskForceResetAdminGate:
    """POST /api/risk/force-reset/{strategy_id} admin gate."""

    def test_no_token_returns_401(self, client_with_token, dummy_strategy_id):
        resp = client_with_token.post(
            f"/api/risk/force-reset/{dummy_strategy_id}?execution_mode=paper",
            json={"reason": "test"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token, dummy_strategy_id):
        resp = client_with_token.post(
            f"/api/risk/force-reset/{dummy_strategy_id}?execution_mode=paper",
            json={"reason": "test"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token, dummy_strategy_id):
        from app.api.risk import _get_risk_service

        mock_state = type(
            "MockState",
            (),
            {
                "level": type("L", (), {"value": 0, "name": "NORMAL"}),
                "trigger_reason": "test",
                "position_multiplier": 1.0,
            },
        )()

        mock_svc = AsyncMock()
        mock_svc.force_reset = AsyncMock(return_value=mock_state)
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        resp = client_with_token.post(
            f"/api/risk/force-reset/{dummy_strategy_id}?execution_mode=paper",
            json={"reason": "紧急运维"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code == 200, f"auth 应通过: {resp.status_code} {resp.text}"


# ────────────────────────────────────────────────────────────────────────────
# approval.py: queue/{id}/approve
# ────────────────────────────────────────────────────────────────────────────


class TestApprovalApproveAdminGate:
    """POST /api/approval/queue/{id}/approve admin gate."""

    def test_no_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/approve",
            json={"reviewer_notes": "ok"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/approve",
            json={"reviewer_notes": "ok"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token, mock_approval_db):
        """对 token → auth 通过, mock session.scalar_one_or_none()=None → 业务 raise 404."""
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/approve",
            json={"reviewer_notes": "ok"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        # auth 通过 (≠401); business 因 mock scalar_one_or_none()=None → _get_queue_item 404
        assert resp.status_code != 401, f"auth 应通过 但返 401: {resp.text}"

    def test_admin_token_unconfigured_returns_500(self, client_no_token):
        resp = client_no_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/approve",
            json={"reviewer_notes": "ok"},
            headers={"X-Admin-Token": "any-token"},
        )
        assert resp.status_code == 500
        assert "ADMIN_TOKEN未配置" in resp.json()["detail"]


# ────────────────────────────────────────────────────────────────────────────
# approval.py: queue/{id}/reject
# ────────────────────────────────────────────────────────────────────────────


class TestApprovalRejectAdminGate:
    """POST /api/approval/queue/{id}/reject admin gate."""

    def test_no_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/reject",
            json={"rejection_reason": "test"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/reject",
            json={"rejection_reason": "test"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token, mock_approval_db):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/reject",
            json={"rejection_reason": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code != 401, f"auth 应通过 但返 401: {resp.text}"

    def test_admin_token_unconfigured_returns_500(self, client_no_token):
        resp = client_no_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/reject",
            json={"rejection_reason": "test"},
            headers={"X-Admin-Token": "any-token"},
        )
        assert resp.status_code == 500
        assert "ADMIN_TOKEN未配置" in resp.json()["detail"]


# ────────────────────────────────────────────────────────────────────────────
# approval.py: queue/{id}/hold
# ────────────────────────────────────────────────────────────────────────────


class TestApprovalHoldAdminGate:
    """POST /api/approval/queue/{id}/hold admin gate."""

    def test_no_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/hold",
            json={"reviewer_notes": "test"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/hold",
            json={"reviewer_notes": "test"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token, mock_approval_db):
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/hold",
            json={"reviewer_notes": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code != 401, f"auth 应通过 但返 401: {resp.text}"

    def test_admin_token_unconfigured_returns_500(self, client_no_token):
        resp = client_no_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/hold",
            json={"reviewer_notes": "test"},
            headers={"X-Admin-Token": "any-token"},
        )
        assert resp.status_code == 500
        assert "ADMIN_TOKEN未配置" in resp.json()["detail"]
