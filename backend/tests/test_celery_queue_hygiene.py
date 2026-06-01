from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.ops import celery_queue_hygiene as hygiene

SH_TZ = ZoneInfo("Asia/Shanghai")


def _message(task: str, expires: str | None) -> bytes:
    return json.dumps({"headers": {"task": task, "expires": expires}}).encode()


def test_split_expired_messages_keeps_unparseable_and_missing_expiry() -> None:
    now = datetime(2026, 5, 29, 20, 0, tzinfo=SH_TZ)
    messages = [
        _message("expired.tick", "2026-05-29T19:59:00+08:00"),
        _message("future.tick", "2026-05-29T20:01:00+08:00"),
        _message("missing.expiry", None),
        b"not-json",
    ]

    kept, expired, expired_by_task, kept_by_task = hygiene._split_expired_messages(
        messages,
        now=now,
    )

    assert expired == [messages[0]]
    assert kept == messages[1:]
    assert expired_by_task == {"expired.tick": 1}
    assert kept_by_task["future.tick"] == 1
    assert kept_by_task["missing.expiry"] == 1
    assert kept_by_task["<unparseable>"] == 1


def test_parse_expires_handles_z_suffix() -> None:
    parsed = hygiene._parse_expires("2026-05-29T12:00:00Z")

    assert parsed is not None
    assert parsed.utcoffset().total_seconds() == 0
