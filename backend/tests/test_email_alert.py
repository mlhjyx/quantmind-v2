"""Unit tests for email_alert.send_email_alert — HC-1b2 元告警 channel 备用通道 (V3 §13.3).

覆盖:
  - 双锁 gate 1: EMAIL_ALERTS_ENABLED=False → email_alerts_disabled (not sent)
  - 双锁 gate 2: SMTP config 不全 (HOST/FROM/TO 任一空) → no_smtp_config
  - happy path: config 全 + enabled → smtplib send_message called → sent
  - STARTTLS + optional login (SMTP_USER 空 → skip login)
  - 铁律 33 fail-loud: smtplib error propagates
  - input validation: empty subject / source → ValueError
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import email_alert
from app.services.email_alert import send_email_alert


def _set_smtp(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    """Set SMTP-related settings to a fully-configured baseline, then apply overrides."""
    base: dict[str, object] = {
        "EMAIL_ALERTS_ENABLED": True,
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": 587,
        "SMTP_USER": "alerts@example.com",
        "SMTP_PASSWORD": "secret",
        "SMTP_FROM": "alerts@example.com",
        "ALERT_EMAIL_TO": "ops@example.com",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setattr(email_alert.settings, key, value)


# ── 双锁 gates ──


def test_email_alerts_disabled_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch, EMAIL_ALERTS_ENABLED=False)
    result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result == {"sent": False, "reason": "email_alerts_disabled"}


def test_no_smtp_config_missing_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch, SMTP_HOST="")
    result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result == {"sent": False, "reason": "no_smtp_config"}


def test_no_smtp_config_missing_from(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch, SMTP_FROM="")
    result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result == {"sent": False, "reason": "no_smtp_config"}


def test_no_smtp_config_missing_recipients(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch, ALERT_EMAIL_TO="   ")  # whitespace-only → 0 recipients
    result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result == {"sent": False, "reason": "no_smtp_config"}


# ── happy path ──


def test_send_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch)
    mock_smtp = MagicMock()
    with patch("app.services.email_alert.smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = mock_smtp
        result = send_email_alert(subject="元告警 X", body="detail", source="meta_monitor")
    assert result == {"sent": True, "reason": "sent"}
    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=10.0)
    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("alerts@example.com", "secret")
    mock_smtp.send_message.assert_called_once()


def test_send_skips_login_when_no_user(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch, SMTP_USER="")  # no auth user → open relay, skip login
    mock_smtp = MagicMock()
    with patch("app.services.email_alert.smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = mock_smtp
        result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result["sent"] is True
    mock_smtp.login.assert_not_called()
    mock_smtp.send_message.assert_called_once()


def test_send_port_465_uses_smtp_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    # port 465 = implicit TLS → SMTP_SSL (no starttls; connection already encrypted)
    _set_smtp(monkeypatch, SMTP_PORT=465)
    mock_smtp = MagicMock()
    with patch("app.services.email_alert.smtplib.SMTP_SSL") as smtp_ssl_cls:
        smtp_ssl_cls.return_value.__enter__.return_value = mock_smtp
        result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result["sent"] is True
    smtp_ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=10.0)
    mock_smtp.starttls.assert_not_called()  # SMTP_SSL = no STARTTLS upgrade
    mock_smtp.login.assert_called_once()
    mock_smtp.send_message.assert_called_once()


def test_send_multi_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_smtp(monkeypatch, ALERT_EMAIL_TO="a@x.com, b@x.com ,c@x.com")
    mock_smtp = MagicMock()
    with patch("app.services.email_alert.smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = mock_smtp
        result = send_email_alert(subject="s", body="b", source="meta_monitor")
    assert result["sent"] is True
    sent_msg = mock_smtp.send_message.call_args.args[0]
    assert sent_msg["To"] == "a@x.com, b@x.com, c@x.com"


# ── 铁律 33 fail-loud ──


def test_smtp_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    import smtplib

    _set_smtp(monkeypatch)
    with patch("app.services.email_alert.smtplib.SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value.send_message.side_effect = (
            smtplib.SMTPException("connection refused")
        )
        with pytest.raises(smtplib.SMTPException, match="connection refused"):
            send_email_alert(subject="s", body="b", source="meta_monitor")


# ── input validation ──


def test_empty_subject_raises() -> None:
    with pytest.raises(ValueError, match="subject"):
        send_email_alert(subject="  ", body="b", source="meta_monitor")


def test_empty_source_raises() -> None:
    with pytest.raises(ValueError, match="source"):
        send_email_alert(subject="s", body="b", source="")
