"""dingtalk_alert helper unit tests (mock conn + mock httpx).

批 2 P0 修 (2026-04-30) Commit 3.

Coverage:
- send_with_dedup happy path (DINGTALK_ALERTS_ENABLED=True, no dedup, sent)
- DINGTALK_ALERTS_ENABLED=False default-off (双锁)
- alert_dedup hit (suppress_until > NOW)
- severity-driven default suppress_minutes
- input validation (empty dedup_key / source / invalid severity)
- httpx retry 1 time on failure
- _upsert_dedup INSERT vs UPDATE branches
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.dingtalk_alert import (
    SEVERITY_DEFAULT_SUPPRESS_MIN,
    _post_to_dingtalk,
    _upsert_dedup,
    send_with_dedup,
)

# ── Input validation ──


def test_send_validates_dedup_key_empty():
    with pytest.raises(ValueError, match="dedup_key 必填"):
        send_with_dedup(dedup_key="", severity="p1", source="s", title="t", conn=MagicMock())


def test_send_validates_source_empty():
    with pytest.raises(ValueError, match="source 必填"):
        send_with_dedup(dedup_key="k", severity="p1", source="  ", title="t", conn=MagicMock())


def test_send_validates_severity_enum():
    with pytest.raises(ValueError, match="不在 enum"):
        send_with_dedup(
            dedup_key="k", severity="bogus", source="s", title="t", conn=MagicMock()
        )


# ── Severity-driven defaults ──


def test_severity_default_suppress_min_p0_5():
    assert SEVERITY_DEFAULT_SUPPRESS_MIN["p0"] == 5


def test_severity_default_suppress_min_p1_30():
    assert SEVERITY_DEFAULT_SUPPRESS_MIN["p1"] == 30


def test_severity_default_suppress_min_p2_info_60():
    assert SEVERITY_DEFAULT_SUPPRESS_MIN["p2"] == 60
    assert SEVERITY_DEFAULT_SUPPRESS_MIN["info"] == 60


# ── _upsert_dedup INSERT vs UPDATE ──


def test_upsert_dedup_insert_new_row():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.side_effect = [None, (1,)]  # 1st: SELECT none / 2nd: RETURNING fire_count

    hit, count = _upsert_dedup(
        conn=conn, dedup_key="k1", severity="p1", source="s",
        title="t", suppress_minutes=30,
    )
    assert hit is False
    assert count == 1


def test_upsert_dedup_hit_suppress_active():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    # SELECT returns existing row with suppress_until > NOW
    future = datetime.now(UTC) + timedelta(minutes=30)
    cur.fetchone.return_value = (future, 5)  # suppress_until, fire_count

    hit, count = _upsert_dedup(
        conn=conn, dedup_key="k1", severity="p1", source="s",
        title="t", suppress_minutes=30,
    )
    assert hit is True
    assert count == 6  # was 5, +1 累加


def test_upsert_dedup_expired_suppress_reupsert():
    """suppress_until 过期 → 重新 UPSERT (新窗口, fire_count 累计)."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    past = datetime.now(UTC) - timedelta(minutes=10)
    cur.fetchone.side_effect = [(past, 3), (4,)]  # SELECT expired / RETURNING累+1

    hit, count = _upsert_dedup(
        conn=conn, dedup_key="k1", severity="p1", source="s",
        title="t", suppress_minutes=30,
    )
    assert hit is False
    assert count == 4


# ── send_with_dedup integration paths ──


@patch("app.services.dingtalk_alert.settings")
@patch("app.services.dingtalk_alert._post_to_dingtalk")
@patch("app.services.dingtalk_alert._upsert_dedup")
def test_send_alerts_disabled_audit_only(mock_upsert, mock_post, mock_settings):
    """DINGTALK_ALERTS_ENABLED=False default-off path."""
    mock_settings.DINGTALK_ALERTS_ENABLED = False
    mock_settings.DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/webhook/x"
    mock_upsert.return_value = (False, 1)  # not hit

    result = send_with_dedup(
        dedup_key="k", severity="p1", source="s", title="t",
        conn=MagicMock(),
    )

    assert result["sent"] is False
    assert result["reason"] == "alerts_disabled"
    assert result["dedup_hit"] is False
    mock_post.assert_not_called()


@patch("app.services.dingtalk_alert.settings")
@patch("app.services.dingtalk_alert._post_to_dingtalk")
@patch("app.services.dingtalk_alert._upsert_dedup")
def test_send_dedup_hit_no_post(mock_upsert, mock_post, mock_settings):
    mock_settings.DINGTALK_ALERTS_ENABLED = True
    mock_settings.DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/webhook/x"
    mock_upsert.return_value = (True, 5)  # dedup hit

    result = send_with_dedup(
        dedup_key="k", severity="p1", source="s", title="t",
        conn=MagicMock(),
    )

    assert result["sent"] is False
    assert result["dedup_hit"] is True
    assert result["reason"] == "dedup_suppressed"
    assert result["fire_count"] == 5
    mock_post.assert_not_called()


@patch("app.services.dingtalk_alert.settings")
@patch("app.services.dingtalk_alert._post_to_dingtalk")
@patch("app.services.dingtalk_alert._upsert_dedup")
def test_send_happy_path_real_post(mock_upsert, mock_post, mock_settings):
    mock_settings.DINGTALK_ALERTS_ENABLED = True
    mock_settings.DINGTALK_WEBHOOK_URL = "https://oapi.dingtalk.com/webhook/x"
    mock_upsert.return_value = (False, 1)

    result = send_with_dedup(
        dedup_key="k", severity="p0", source="s", title="t", body="b",
        conn=MagicMock(),
    )

    assert result["sent"] is True
    assert result["reason"] == "sent"
    assert result["dedup_hit"] is False
    mock_post.assert_called_once()


@patch("app.services.dingtalk_alert.settings")
@patch("app.services.dingtalk_alert._post_to_dingtalk")
@patch("app.services.dingtalk_alert._upsert_dedup")
def test_send_no_webhook_url(mock_upsert, mock_post, mock_settings):
    mock_settings.DINGTALK_ALERTS_ENABLED = True
    mock_settings.DINGTALK_WEBHOOK_URL = ""
    mock_upsert.return_value = (False, 1)

    result = send_with_dedup(
        dedup_key="k", severity="p1", source="s", title="t",
        conn=MagicMock(),
    )

    assert result["sent"] is False
    assert result["reason"] == "no_webhook"
    mock_post.assert_not_called()


# ── _post_to_dingtalk retry logic ──


def test_post_retries_once_on_failure():
    with patch("app.services.dingtalk_alert.httpx.post") as mock_httpx_post:
        # First call fails, second succeeds
        mock_resp_ok = MagicMock()
        mock_resp_ok.raise_for_status.return_value = None
        mock_httpx_post.side_effect = [
            httpx.RequestError("first fail"),
            mock_resp_ok,
        ]

        _post_to_dingtalk(
            webhook_url="https://x.test", title="t", body="b", severity="p1"
        )

        assert mock_httpx_post.call_count == 2


def test_post_raises_after_3_failures():
    with patch("app.services.dingtalk_alert.httpx.post") as mock_httpx_post:
        mock_httpx_post.side_effect = [
            httpx.RequestError("first fail"),
            httpx.RequestError("second fail"),
            httpx.RequestError("third fail"),
        ]

        with pytest.raises(httpx.HTTPError):
            _post_to_dingtalk(
                webhook_url="https://x.test", title="t", body="b", severity="p1"
            )

        assert mock_httpx_post.call_count == 3
