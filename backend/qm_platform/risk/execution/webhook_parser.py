"""DingTalk webhook inbound parser — pure compute (S8 8b).

V3 §S8 8b scope (Plan §A): DingTalkWebhookReceiver inbound 路径 for STAGED
反向决策权. User in DingTalk group taps button or replies command → DingTalk
POSTs to our webhook endpoint → this parser:

  1. Verifies request signature (HMAC-SHA256 of timestamp + body, ±5min window)
  2. Parses command (CONFIRM / CANCEL / unknown)
  3. Extracts plan_id (UUID prefix matching, ≥8 chars to disambiguate)

Pure module (铁律 31): NO IO, NO DB. Verification + parsing only.
Caller (service layer) handles DB read of execution_plans + state transition
+ DB write — sustained 铁律 32 (Service 不 commit).

Supported command forms (case-insensitive):
  - "confirm <plan_id_prefix>"
  - "cancel <plan_id_prefix>"
  - "确认 <plan_id_prefix>"
  - "取消 <plan_id_prefix>"

Signature protocol (MVP simple HMAC):
  expected = base64(HMAC-SHA256(secret, f"{timestamp}\\n{body}"))
  Verify: secrets.compare_digest(expected, received_sign)
  Window: abs(now - timestamp) <= 300s (5min replay protection)

NOTE: full DingTalk card-callback AES-CBC protocol deferred — current scheme
covers custom bot HTTP POST with `timestamp` + `sign` headers. Production
activation of real DingTalk card-callback requires follow-up sub-PR per
DingTalk SDK encryption spec.

关联铁律: 1 (外部 API 必读官方文档 — 当前 HMAC scheme custom; DingTalk card
  AES protocol verify deferred) / 31 / 33 (fail-loud on invalid sig)
关联 ADR: ADR-057 (S8 8b webhook receiver, NEW sediment cycle)
关联 LL: LL-151 (S8 8b sediment, NEW sediment cycle)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

# ── Constants ──

# Replay window: reject requests where |now - timestamp| > 300s
SIGNATURE_REPLAY_WINDOW_SECONDS: Final[int] = 300

# Minimum plan_id prefix length to accept (反 collision risk; 8 hex chars ≈ 4B uniqueness)
MIN_PLAN_ID_PREFIX_LEN: Final[int] = 8

# Plan_id full UUID length (8-4-4-4-12 = 36 chars with dashes; we accept either with or without dashes)
PLAN_ID_FULL_LEN_WITH_DASHES: Final[int] = 36
PLAN_ID_FULL_LEN_NO_DASHES: Final[int] = 32

# Command regex — case-insensitive, captures plan_id-prefix
_COMMAND_PATTERN = re.compile(
    r"^\s*(confirm|cancel|确认|取消)\s+([0-9a-fA-F\-]{8,36})\s*$",
    re.IGNORECASE,
)

# UUID-ish characters validity (反 SQL-injection vector even though we use parametrized query downstream)
_PLAN_ID_VALIDATOR = re.compile(r"^[0-9a-fA-F\-]{8,36}$")


# ── Result types ──


class WebhookCommand(StrEnum):
    """Inbound webhook command after parsing."""

    CONFIRM = "confirm"
    CANCEL = "cancel"


class WebhookParseErrorCode(StrEnum):
    """Parse failure modes."""

    INVALID_SIGNATURE = "invalid_signature"
    STALE_TIMESTAMP = "stale_timestamp"
    MALFORMED_BODY = "malformed_body"
    UNKNOWN_COMMAND = "unknown_command"
    INVALID_PLAN_ID = "invalid_plan_id"


@dataclass(frozen=True)
class ParsedWebhook:
    """Parsed result — caller passes to service layer for DB transition."""

    command: WebhookCommand
    plan_id_prefix: str  # may be partial (≥8 hex), caller resolves to full UUID


class WebhookParseError(Exception):
    """Raised when signature or command parsing fails. Caller maps to HTTP 401/400."""

    def __init__(self, code: WebhookParseErrorCode, message: str = ""):
        super().__init__(message or code.value)
        self.code = code


# ── Signature verification ──


def verify_signature(
    *,
    secret: str,
    timestamp: str,
    body: str,
    received_sign: str,
    now_unix: float | None = None,
) -> None:
    """Verify HMAC-SHA256 signature with timestamp replay window.

    Args:
        secret: shared secret from settings.DINGTALK_WEBHOOK_SECRET
        timestamp: header value as string (unix seconds, may have ms suffix)
        body: raw request body (bytes decoded as UTF-8 str)
        received_sign: header value (base64-encoded HMAC digest)
        now_unix: injectable clock for testing (default = time.time())

    Raises:
        WebhookParseError(STALE_TIMESTAMP) if outside replay window.
        WebhookParseError(INVALID_SIGNATURE) if HMAC mismatch.
    """
    # Step 1: timestamp window check (反 replay attack)
    try:
        ts_float = float(timestamp)
        # DingTalk sends ms-resolution timestamps — normalize to seconds
        if ts_float > 1e12:
            ts_float = ts_float / 1000.0
    except (ValueError, TypeError) as e:
        raise WebhookParseError(
            WebhookParseErrorCode.STALE_TIMESTAMP,
            f"timestamp not parseable as float: {timestamp!r}",
        ) from e

    now = now_unix if now_unix is not None else time.time()
    if abs(now - ts_float) > SIGNATURE_REPLAY_WINDOW_SECONDS:
        raise WebhookParseError(
            WebhookParseErrorCode.STALE_TIMESTAMP,
            f"timestamp drift {abs(now - ts_float):.1f}s exceeds "
            f"{SIGNATURE_REPLAY_WINDOW_SECONDS}s replay window",
        )

    # Step 2: HMAC-SHA256 compute + constant-time compare
    secret_bytes = secret.encode("utf-8")
    payload = f"{timestamp}\n{body}".encode()
    expected_digest = hmac.new(secret_bytes, payload, hashlib.sha256).digest()
    expected_b64 = base64.b64encode(expected_digest).decode("utf-8")

    # Use compare_digest to defeat timing side-channels (反 signature byte-by-byte leak)
    if not hmac.compare_digest(expected_b64, received_sign):
        raise WebhookParseError(
            WebhookParseErrorCode.INVALID_SIGNATURE,
            "HMAC-SHA256 mismatch",
        )


# ── Command parsing ──


def parse_command(text: str) -> ParsedWebhook:
    """Parse inbound webhook text payload into (command, plan_id_prefix).

    Accepts:
        "confirm <plan_id_prefix>" / "cancel <plan_id_prefix>"
        "确认 <plan_id_prefix>" / "取消 <plan_id_prefix>"
        Case-insensitive verb. plan_id_prefix is 8-36 hex chars with optional dashes.

    Raises:
        WebhookParseError(MALFORMED_BODY): empty / whitespace-only
        WebhookParseError(UNKNOWN_COMMAND): verb not in {confirm/cancel/确认/取消}
        WebhookParseError(INVALID_PLAN_ID): prefix too short / non-hex chars

    Returns:
        ParsedWebhook with normalized command + plan_id_prefix (lowercased, dashes stripped).
    """
    if not text or not text.strip():
        raise WebhookParseError(
            WebhookParseErrorCode.MALFORMED_BODY,
            "empty or whitespace-only text",
        )

    match = _COMMAND_PATTERN.match(text)
    if match is None:
        # Determine specific error: unknown verb vs invalid plan_id
        verb_only = re.match(r"^\s*(\S+)", text)
        if verb_only and verb_only.group(1).lower() not in {"confirm", "cancel", "确认", "取消"}:
            raise WebhookParseError(
                WebhookParseErrorCode.UNKNOWN_COMMAND,
                f"verb {verb_only.group(1)!r} not in {{confirm, cancel, 确认, 取消}}",
            )
        raise WebhookParseError(
            WebhookParseErrorCode.MALFORMED_BODY,
            "expected '<verb> <plan_id_prefix>' format",
        )

    verb_raw = match.group(1).lower()
    plan_id_raw = match.group(2)

    # Normalize verb (Chinese → English)
    if verb_raw in {"confirm", "确认"}:
        command = WebhookCommand.CONFIRM
    elif verb_raw in {"cancel", "取消"}:
        command = WebhookCommand.CANCEL
    else:
        # Defensive — should be unreachable since regex matched
        raise WebhookParseError(
            WebhookParseErrorCode.UNKNOWN_COMMAND,
            f"verb {verb_raw!r} not handled",
        )

    # Normalize plan_id: strip dashes, lowercase
    plan_id_norm = plan_id_raw.replace("-", "").lower()

    if not _PLAN_ID_VALIDATOR.match(plan_id_raw):
        raise WebhookParseError(
            WebhookParseErrorCode.INVALID_PLAN_ID,
            f"plan_id {plan_id_raw!r} not [0-9a-fA-F\\-]{{8,36}}",
        )

    if len(plan_id_norm) < MIN_PLAN_ID_PREFIX_LEN:
        raise WebhookParseError(
            WebhookParseErrorCode.INVALID_PLAN_ID,
            f"plan_id prefix length {len(plan_id_norm)} < {MIN_PLAN_ID_PREFIX_LEN}",
        )

    return ParsedWebhook(command=command, plan_id_prefix=plan_id_norm)
