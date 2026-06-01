"""Inspect and purge expired Celery Redis queue messages.

Default mode is dry-run. `--apply` only removes messages whose Celery header
contains an absolute `expires` timestamp in the past; unparseable messages are
kept. This is intended for stale Beat tick backlogs after a worker outage.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import redis

SH_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class QueueHygieneResult:
    queue: str
    total: int
    expired: int
    kept: int
    expired_by_task: dict[str, int]
    kept_by_task: dict[str, int]


def _parse_expires(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=SH_TZ)
    return dt


def _message_task_and_expiry(raw: bytes) -> tuple[str, datetime | None]:
    try:
        msg = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return "<unparseable>", None
    headers = msg.get("headers") or {}
    return str(headers.get("task") or "<missing-task>"), _parse_expires(headers.get("expires"))


def _split_expired_messages(
    messages: list[bytes],
    *,
    now: datetime,
) -> tuple[list[bytes], list[bytes], Counter[str], Counter[str]]:
    kept: list[bytes] = []
    expired: list[bytes] = []
    kept_by_task: Counter[str] = Counter()
    expired_by_task: Counter[str] = Counter()
    for raw in messages:
        task, expires_at = _message_task_and_expiry(raw)
        if expires_at is not None and expires_at <= now:
            expired.append(raw)
            expired_by_task[task] += 1
        else:
            kept.append(raw)
            kept_by_task[task] += 1
    return kept, expired, expired_by_task, kept_by_task


def inspect_or_purge_queue(
    client: redis.Redis,
    queue: str,
    *,
    apply: bool,
    now: datetime | None = None,
) -> QueueHygieneResult:
    now = now or datetime.now(SH_TZ)
    with client.pipeline() as pipe:
        while True:
            try:
                pipe.watch(queue)
                messages = pipe.lrange(queue, 0, -1)
                kept, expired, expired_by_task, kept_by_task = _split_expired_messages(
                    messages,
                    now=now,
                )
                if apply and expired:
                    pipe.multi()
                    pipe.delete(queue)
                    if kept:
                        pipe.rpush(queue, *kept)
                    pipe.execute()
                else:
                    pipe.unwatch()
                return QueueHygieneResult(
                    queue=queue,
                    total=len(messages),
                    expired=len(expired),
                    kept=len(kept),
                    expired_by_task=dict(expired_by_task),
                    kept_by_task=dict(kept_by_task),
                )
            except redis.WatchError:
                continue


def _print_result(result: QueueHygieneResult, *, apply: bool) -> None:
    action = "APPLIED" if apply else "DRY_RUN"
    print(
        f"[{action}] queue={result.queue} total={result.total} "
        f"expired={result.expired} kept={result.kept}"
    )
    print("[expired_by_task]")
    for task, count in sorted(result.expired_by_task.items(), key=lambda item: (-item[1], item[0])):
        print(f"{count}\t{task}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="default")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=6379)
    parser.add_argument("--db", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    client = redis.Redis(host=args.host, port=args.port, db=args.db, socket_timeout=10)
    result = inspect_or_purge_queue(client, args.queue, apply=args.apply)
    _print_result(result, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
