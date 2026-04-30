"""T0-16 qmt_data_service fail-loud unit tests (mocked instance, no real QMT).

批 2 P0 修 (2026-04-30) Commit 5.

Coverage:
- _CONSECUTIVE_FAILURE_THRESHOLD constant
- consecutive failure counter increments on _sync_positions failure
- counter reset on success
- escalation triggered at threshold (calls dingtalk_alert)
- escalation suppressed second time (alerted flag, prevents spam)
- escalation reset after success (next failure episode triggers again)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts/ to path for direct import
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


@pytest.fixture
def qmt_service():
    """Construct QMTDataService with mocked broker + redis (no real QMT IO)."""
    # Avoid bus/stream/redis import at module load time
    with patch("qmt_data_service.get_stream_bus", return_value=MagicMock()):
        from qmt_data_service import QMTDataService
        svc = QMTDataService()
    svc._broker = MagicMock()
    svc._redis = MagicMock()
    return svc


def test_threshold_constant_5():
    """5 consecutive failures × 60s = 5 min."""
    with patch("qmt_data_service.get_stream_bus", return_value=MagicMock()):
        from qmt_data_service import QMTDataService
        assert QMTDataService._CONSECUTIVE_FAILURE_THRESHOLD == 5


def test_initial_counter_zero(qmt_service):
    assert qmt_service._consecutive_sync_failures == 0
    assert qmt_service._fail_loud_alerted is False


def test_consecutive_failures_increment(qmt_service):
    """Failure path: 4 consecutive failures still under threshold, 5th triggers."""
    qmt_service._broker.get_positions.side_effect = RuntimeError("QMT 未连接")

    # 4 failures — under threshold, no escalation
    with patch.object(qmt_service, "_escalate_consecutive_sync_failures") as mock_escalate:
        for _ in range(4):
            qmt_service._sync_positions()
        assert qmt_service._consecutive_sync_failures == 4
        assert mock_escalate.call_count == 0

    # 5th — triggers escalation
    with patch.object(qmt_service, "_escalate_consecutive_sync_failures") as mock_escalate:
        qmt_service._sync_positions()
        assert qmt_service._consecutive_sync_failures == 5
        assert mock_escalate.call_count == 1
        assert qmt_service._fail_loud_alerted is True


def test_escalation_suppressed_after_first_alert(qmt_service):
    """6th, 7th... failures don't re-escalate (avoid DingTalk spam)."""
    qmt_service._broker.get_positions.side_effect = RuntimeError("QMT 未连接")

    # Simulate 5 failures + flag set
    qmt_service._consecutive_sync_failures = 5
    qmt_service._fail_loud_alerted = True

    with patch.object(qmt_service, "_escalate_consecutive_sync_failures") as mock_escalate:
        for _ in range(3):  # 6th, 7th, 8th
            qmt_service._sync_positions()
        # Counter still increments
        assert qmt_service._consecutive_sync_failures == 8
        # But escalation NOT re-called
        assert mock_escalate.call_count == 0


def test_counter_reset_on_success(qmt_service):
    """Successful sync resets counter + alert flag."""
    # Simulate prior failures
    qmt_service._consecutive_sync_failures = 7
    qmt_service._fail_loud_alerted = True

    # Mock get_positions success (returns dict[code → shares])
    qmt_service._broker.get_positions.return_value = {}
    qmt_service._broker.query_asset.return_value = {"cash": 100, "total_asset": 100}

    qmt_service._sync_positions()

    assert qmt_service._consecutive_sync_failures == 0
    assert qmt_service._fail_loud_alerted is False


def test_escalate_calls_dingtalk_alert(qmt_service):
    """_escalate_consecutive_sync_failures invokes dingtalk_alert.send_with_dedup."""
    qmt_service._consecutive_sync_failures = 5

    with patch("app.services.dingtalk_alert.send_with_dedup") as mock_send:
        qmt_service._escalate_consecutive_sync_failures()
        mock_send.assert_called_once()
        kwargs = mock_send.call_args.kwargs
        assert kwargs["dedup_key"] == "qmt_data_service:consecutive_sync_failures"
        assert kwargs["severity"] == "p0"
        assert kwargs["source"] == "qmt_data_service"


def test_escalate_dingtalk_failure_does_not_raise(qmt_service):
    """dingtalk_alert raise — _escalate 不 cascade fail (沿用铁律 33-d silent_ok)."""
    qmt_service._consecutive_sync_failures = 5

    with patch(
        "app.services.dingtalk_alert.send_with_dedup",
        side_effect=RuntimeError("dingtalk down"),
    ):
        # Should not raise (escalation graceful failure)
        qmt_service._escalate_consecutive_sync_failures()
