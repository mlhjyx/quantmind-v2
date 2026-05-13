"""S8 8b DingTalk webhook parser tests — pure module (signature + command parser).

Coverage:
- HMAC-SHA256 signature verify: happy path, mismatch, stale timestamp
- Timestamp normalization (ms vs seconds)
- Command parse: confirm/cancel/确认/取消 + plan_id_prefix normalization
- Error codes: INVALID_SIGNATURE / STALE_TIMESTAMP / MALFORMED_BODY /
  UNKNOWN_COMMAND / INVALID_PLAN_ID

关联铁律: 31 (pure module) / 33 (fail-loud parse errors)
关联 ADR: ADR-057 §S8 8b webhook receiver
关联 LL: LL-151 §S8 8b sediment
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from qm_platform.risk.execution.webhook_parser import (
    SIGNATURE_REPLAY_WINDOW_SECONDS,
    ParsedWebhook,
    WebhookCommand,
    WebhookParseError,
    WebhookParseErrorCode,
    parse_command,
    verify_signature,
)

# ── Test helpers ──


def _make_sign(secret: str, timestamp: str, body: str) -> str:
    """Compute the expected HMAC-SHA256 base64 signature (parser's algorithm)."""
    payload = f"{timestamp}\n{body}".encode()
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


# §1 verify_signature happy paths


class TestVerifySignatureHappy:
    def test_seconds_timestamp_valid_sign(self) -> None:
        secret = "shhh-it-is-a-secret"
        ts = "1715600000"
        body = '{"text": "confirm abc12345"}'
        sign = _make_sign(secret, ts, body)
        # Should not raise
        verify_signature(
            secret=secret,
            timestamp=ts,
            body=body,
            received_sign=sign,
            now_unix=float(ts),
        )

    def test_milliseconds_timestamp_normalized(self) -> None:
        """DingTalk historically sends ms-resolution; verify normalization."""
        secret = "s"
        ts_ms = "1715600000123"  # ms
        body = '{"text": "cancel deadbeef00000000"}'
        sign = _make_sign(secret, ts_ms, body)
        verify_signature(
            secret=secret,
            timestamp=ts_ms,
            body=body,
            received_sign=sign,
            now_unix=1715600000.5,  # within window after ms→s normalization
        )

    def test_timestamp_at_window_edge_passes(self) -> None:
        secret = "s"
        ts = "1715600000"
        body = "x"
        sign = _make_sign(secret, ts, body)
        # Exactly at window edge (≤ 300s)
        verify_signature(
            secret=secret,
            timestamp=ts,
            body=body,
            received_sign=sign,
            now_unix=float(ts) + float(SIGNATURE_REPLAY_WINDOW_SECONDS),
        )


# §2 verify_signature failures


class TestVerifySignatureFailures:
    def test_stale_timestamp_outside_window(self) -> None:
        secret = "s"
        ts = "1715600000"
        body = "x"
        sign = _make_sign(secret, ts, body)
        with pytest.raises(WebhookParseError) as exc:
            verify_signature(
                secret=secret,
                timestamp=ts,
                body=body,
                received_sign=sign,
                now_unix=float(ts) + float(SIGNATURE_REPLAY_WINDOW_SECONDS) + 1.0,
            )
        assert exc.value.code == WebhookParseErrorCode.STALE_TIMESTAMP

    def test_malformed_timestamp(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            verify_signature(
                secret="s",
                timestamp="not-a-number",
                body="x",
                received_sign="abc",
                now_unix=1715600000.0,
            )
        assert exc.value.code == WebhookParseErrorCode.STALE_TIMESTAMP

    def test_sign_mismatch_raises_invalid_signature(self) -> None:
        secret = "s"
        ts = "1715600000"
        body = '{"text": "confirm abcd1234"}'
        wrong_sign = _make_sign(secret, ts, body + "tampered")
        with pytest.raises(WebhookParseError) as exc:
            verify_signature(
                secret=secret,
                timestamp=ts,
                body=body,
                received_sign=wrong_sign,
                now_unix=float(ts),
            )
        assert exc.value.code == WebhookParseErrorCode.INVALID_SIGNATURE

    def test_wrong_secret_raises_invalid_signature(self) -> None:
        ts = "1715600000"
        body = "x"
        sign_with_wrong_secret = _make_sign("wrong-secret", ts, body)
        with pytest.raises(WebhookParseError) as exc:
            verify_signature(
                secret="correct-secret",
                timestamp=ts,
                body=body,
                received_sign=sign_with_wrong_secret,
                now_unix=float(ts),
            )
        assert exc.value.code == WebhookParseErrorCode.INVALID_SIGNATURE


# §3 parse_command happy paths


class TestParseCommandHappy:
    def test_confirm_english(self) -> None:
        result = parse_command("confirm abcd1234deadbeef00000000")
        assert result.command == WebhookCommand.CONFIRM
        assert result.plan_id_prefix == "abcd1234deadbeef00000000"

    def test_cancel_english(self) -> None:
        result = parse_command("cancel deadbeef00")
        assert result.command == WebhookCommand.CANCEL
        assert result.plan_id_prefix == "deadbeef00"

    def test_confirm_chinese(self) -> None:
        result = parse_command("确认 12345678")
        assert result.command == WebhookCommand.CONFIRM
        assert result.plan_id_prefix == "12345678"

    def test_cancel_chinese(self) -> None:
        result = parse_command("取消 abcd1234")
        assert result.command == WebhookCommand.CANCEL
        assert result.plan_id_prefix == "abcd1234"

    def test_case_insensitive_verb(self) -> None:
        result = parse_command("CONFIRM abcd1234")
        assert result.command == WebhookCommand.CONFIRM

    def test_plan_id_with_dashes_normalized(self) -> None:
        """UUID with dashes should normalize (strip + lowercase)."""
        result = parse_command("confirm abcd1234-dead-beef-0000-000000000000")
        assert result.plan_id_prefix == "abcd1234deadbeef0000000000000000"

    def test_mixed_case_plan_id_lowercased(self) -> None:
        result = parse_command("confirm AbCd1234")
        assert result.plan_id_prefix == "abcd1234"

    def test_leading_trailing_whitespace_tolerated(self) -> None:
        result = parse_command("  confirm abcd1234  ")
        assert result.command == WebhookCommand.CONFIRM
        assert result.plan_id_prefix == "abcd1234"

    def test_result_is_frozen(self) -> None:
        result = parse_command("confirm abcd1234")
        with pytest.raises(Exception):  # noqa: B017
            result.command = WebhookCommand.CANCEL  # type: ignore[misc]


# §4 parse_command failures


class TestParseCommandFailures:
    def test_empty_text_raises_malformed(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_command("")
        assert exc.value.code == WebhookParseErrorCode.MALFORMED_BODY

    def test_whitespace_only_raises_malformed(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_command("   \t\n   ")
        assert exc.value.code == WebhookParseErrorCode.MALFORMED_BODY

    def test_unknown_verb_raises_unknown_command(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_command("approve abcd1234")
        assert exc.value.code == WebhookParseErrorCode.UNKNOWN_COMMAND

    def test_short_plan_id_raises_malformed(self) -> None:
        """plan_id <8 hex chars fails the regex → MALFORMED_BODY (regex didn't match)."""
        with pytest.raises(WebhookParseError) as exc:
            parse_command("confirm abc")
        # Regex requires {8,36}; 'abc' is <8 so regex won't match → MALFORMED
        assert exc.value.code in {
            WebhookParseErrorCode.MALFORMED_BODY,
            WebhookParseErrorCode.INVALID_PLAN_ID,
        }

    def test_non_hex_plan_id_raises_malformed(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_command("confirm xyz-not-hex")
        # 'xyz' not hex → regex won't match
        assert exc.value.code in {
            WebhookParseErrorCode.MALFORMED_BODY,
            WebhookParseErrorCode.INVALID_PLAN_ID,
        }

    def test_no_plan_id_raises_malformed(self) -> None:
        with pytest.raises(WebhookParseError) as exc:
            parse_command("confirm")
        assert exc.value.code == WebhookParseErrorCode.MALFORMED_BODY


# §5 Defense-in-depth (defensive code paths)


def test_parsed_webhook_dataclass_fields() -> None:
    """ParsedWebhook holds command + plan_id_prefix only."""
    p = ParsedWebhook(command=WebhookCommand.CONFIRM, plan_id_prefix="abcd1234")
    assert p.command == WebhookCommand.CONFIRM
    assert p.plan_id_prefix == "abcd1234"


def test_error_code_enum_values() -> None:
    """Verify enum value strings (反 silent rename in future refactor)."""
    assert WebhookParseErrorCode.INVALID_SIGNATURE == "invalid_signature"
    assert WebhookParseErrorCode.STALE_TIMESTAMP == "stale_timestamp"
    assert WebhookParseErrorCode.MALFORMED_BODY == "malformed_body"
    assert WebhookParseErrorCode.UNKNOWN_COMMAND == "unknown_command"
    assert WebhookParseErrorCode.INVALID_PLAN_ID == "invalid_plan_id"
