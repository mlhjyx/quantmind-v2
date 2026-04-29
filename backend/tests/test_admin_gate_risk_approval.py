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

测试矩阵 (each endpoint × 3 cases = 18 unit tests):
1. 无 X-Admin-Token header → 401
2. 错 X-Admin-Token (不匹配 settings.ADMIN_TOKEN) → 401
3. 对 X-Admin-Token + dependency_overrides bypass business → 200/4xx (auth 通过, business 决定)

Note:
- _verify_admin_token settings.ADMIN_TOKEN=None 路径返 500, 用 monkeypatch 验证
- 沿用 plain `!=` compare (D2.2 Finding 标 P2 timing attack), 留批 2 P2 单独修
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

VALID_TOKEN = "test-admin-token-for-unit-tests"

# Test fixtures: dummy IDs (不真打 DB, dependency_overrides 拦截 service)
DUMMY_STRATEGY_ID = str(uuid4())
DUMMY_APPROVAL_ID = str(uuid4())
DUMMY_QUEUE_ITEM_ID = 1


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


# ────────────────────────────────────────────────────────────────────────────
# risk.py: l4-recovery
# ────────────────────────────────────────────────────────────────────────────


class TestRiskL4RecoveryAdminGate:
    """POST /api/risk/l4-recovery/{strategy_id} admin gate."""

    def test_no_token_returns_401(self, client_with_token):
        """无 X-Admin-Token header → 401."""
        resp = client_with_token.post(
            f"/api/risk/l4-recovery/{DUMMY_STRATEGY_ID}?execution_mode=paper",
            json={"reviewer_note": "test"},
        )
        assert resp.status_code == 401
        assert "无效的Admin Token" in resp.json()["detail"]

    def test_wrong_token_returns_401(self, client_with_token):
        """错 X-Admin-Token → 401."""
        resp = client_with_token.post(
            f"/api/risk/l4-recovery/{DUMMY_STRATEGY_ID}?execution_mode=paper",
            json={"reviewer_note": "test"},
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token):
        """对 X-Admin-Token + bypass business → auth 通过 (业务返 200)."""
        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.request_l4_recovery = AsyncMock(return_value=uuid4())
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        resp = client_with_token.post(
            f"/api/risk/l4-recovery/{DUMMY_STRATEGY_ID}?execution_mode=paper",
            json={"reviewer_note": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        # auth 通过 (非 401)
        assert resp.status_code == 200, f"auth 应通过 但返 {resp.status_code}: {resp.text}"

    def test_admin_token_unconfigured_returns_500(self, client_no_token):
        """settings.ADMIN_TOKEN='' 未配置 → 500."""
        resp = client_no_token.post(
            f"/api/risk/l4-recovery/{DUMMY_STRATEGY_ID}?execution_mode=paper",
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

    def test_no_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/risk/l4-approve/{DUMMY_APPROVAL_ID}",
            json={"approved": True, "reviewer_note": "ok"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/risk/l4-approve/{DUMMY_APPROVAL_ID}",
            json={"approved": True, "reviewer_note": "ok"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token):
        from app.api.risk import _get_risk_service

        mock_svc = AsyncMock()
        mock_svc.approve_l4_recovery = AsyncMock(return_value=None)  # rejected path
        app.dependency_overrides[_get_risk_service] = lambda: mock_svc

        resp = client_with_token.post(
            f"/api/risk/l4-approve/{DUMMY_APPROVAL_ID}",
            json={"approved": False, "reviewer_note": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code == 200, f"auth 应通过: {resp.status_code} {resp.text}"


# ────────────────────────────────────────────────────────────────────────────
# risk.py: force-reset
# ────────────────────────────────────────────────────────────────────────────


class TestRiskForceResetAdminGate:
    """POST /api/risk/force-reset/{strategy_id} admin gate."""

    def test_no_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/risk/force-reset/{DUMMY_STRATEGY_ID}?execution_mode=paper",
            json={"reason": "test"},
        )
        assert resp.status_code == 401

    def test_wrong_token_returns_401(self, client_with_token):
        resp = client_with_token.post(
            f"/api/risk/force-reset/{DUMMY_STRATEGY_ID}?execution_mode=paper",
            json={"reason": "test"},
            headers={"X-Admin-Token": "wrong"},
        )
        assert resp.status_code == 401

    def test_correct_token_passes_auth(self, client_with_token):
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
            f"/api/risk/force-reset/{DUMMY_STRATEGY_ID}?execution_mode=paper",
            json={"reason": "紧急运维"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code == 200, f"auth 应通过: {resp.status_code} {resp.text}"


# ────────────────────────────────────────────────────────────────────────────
# approval.py: queue/{id}/approve
# ────────────────────────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────────────────────────
# Helper: approval `test_correct_token_passes_auth` 共享 mock session bypass
# 避免真打 DB 触发 sync TestClient + async asyncpg event loop bleed (跨测试 flake).
# auth 通过的真实证据 = 不返 401 (business 因 mock session 失败返 5xx 均算 auth pass).
# ────────────────────────────────────────────────────────────────────────────


def _override_approval_db_with_mock():
    """Patch _get_db 返 mock session, 让 _get_queue_item.scalar_one_or_none() 返 None
    → endpoint raise HTTPException 404. auth 通过的真实证据 = 不返 401, 业务返 404 OK.
    防 reject/hold/approve 测试真打 PG (sync TestClient + async asyncpg event loop bleed).
    """
    from app.api.approval import _get_db

    # Mock result chain: session.execute() → result; result.scalar_one_or_none() → None
    mock_result = AsyncMock()
    mock_result.scalar_one_or_none = lambda: None  # 同步 method 不能 AsyncMock

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    app.dependency_overrides[_get_db] = lambda: mock_session


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

    def test_correct_token_passes_auth(self, client_with_token):
        """对 token → auth 通过 (mock session bypass 防 PG event loop bleed)."""
        _override_approval_db_with_mock()
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/approve",
            json={"reviewer_notes": "ok"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        # auth 通过 (≠401); business 因 mock session.execute raise → 500
        assert resp.status_code != 401, f"auth 应通过 但返 401: {resp.text}"


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

    def test_correct_token_passes_auth(self, client_with_token):
        _override_approval_db_with_mock()
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/reject",
            json={"rejection_reason": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code != 401, f"auth 应通过 但返 401: {resp.text}"


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

    def test_correct_token_passes_auth(self, client_with_token):
        _override_approval_db_with_mock()
        resp = client_with_token.post(
            f"/api/approval/queue/{DUMMY_QUEUE_ITEM_ID}/hold",
            json={"reviewer_notes": "test"},
            headers={"X-Admin-Token": VALID_TOKEN},
        )
        assert resp.status_code != 401, f"auth 应通过 但返 401: {resp.text}"
