"""Agent API LLM observability read models.

Regression guards for the 2026-05-28 governance closure: AgentConfig cost and
log panels must read llm_call_log truth instead of returning hardcoded stubs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.api import agent


class _FakeCursor:
    def __init__(
        self, fetchone_rows: list[tuple[Any, ...]], fetchall_rows: list[list[tuple[Any, ...]]]
    ):
        self._fetchone_rows = fetchone_rows
        self._fetchall_rows = fetchall_rows
        self.calls: list[tuple[str, Any]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> tuple[Any, ...]:
        return self._fetchone_rows.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._fetchall_rows.pop(0)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self.cursor_obj = cursor
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def test_cost_summary_reads_llm_call_log(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor(
        fetchone_rows=[(100, 50, Decimal("0.1234"))],
        fetchall_rows=[
            [
                ("news_classify", 30, Decimal("0.0200")),
                ("risk_reflector", 120, Decimal("0.1034")),
            ],
            [
                ("deepseek/deepseek-v4-flash", "news_classify", 30, Decimal("0.0200")),
                ("deepseek/deepseek-v4-pro", "risk_reflector", 120, Decimal("0.1034")),
            ],
            [
                (
                    date(2026, 5, 2),
                    "news_classify",
                    "deepseek/deepseek-v4-flash",
                    "news_classify",
                    20,
                    10,
                    Decimal("0.0200"),
                ),
            ],
        ],
    )
    conn = _FakeConn(cur)
    monkeypatch.setattr(agent, "_get_db_conn", lambda: conn)

    summary = asyncio.run(agent.get_cost_summary(month="2026-05", _=None))

    assert conn.closed is True
    assert summary["currency"] == "USD"
    assert summary["total_cost_usd"] == 0.1234
    assert summary["total_input_tokens"] == 100
    assert summary["total_output_tokens"] == 50
    assert summary["by_agent"]["idea"] == {"cost_usd": 0.02, "tokens": 30}
    assert summary["by_agent"]["diagnosis"] == {"cost_usd": 0.1034, "tokens": 120}
    assert summary["by_model"]["deepseek-v4-flash"] == {"cost_usd": 0.02, "tokens": 30}
    assert summary["by_model"]["deepseek-v4-pro"] == {"cost_usd": 0.1034, "tokens": 120}
    assert summary["daily_usage"] == [
        {
            "date": "2026-05-02",
            "agent": "idea",
            "model": "deepseek-v4-flash",
            "input_tokens": 20,
            "output_tokens": 10,
            "cost_usd": 0.02,
        }
    ]


def test_cost_summary_rejects_invalid_month() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent.get_cost_summary(month="2026-13", _=None))

    assert exc.value.status_code == 400


def test_agent_logs_read_llm_call_log(monkeypatch: pytest.MonkeyPatch) -> None:
    triggered_at = datetime(2026, 5, 28, 9, 30, tzinfo=UTC)
    cur = _FakeCursor(
        fetchone_rows=[],
        fetchall_rows=[
            [
                (
                    "11111111-1111-1111-1111-111111111111",
                    triggered_at,
                    "risk_reflector",
                    "risk_reflector",
                    "deepseek/deepseek-v4-pro",
                    False,
                    "normal",
                    50,
                    25,
                    Decimal("0.0456"),
                    1234,
                    "reflect-1",
                    None,
                )
            ]
        ],
    )
    conn = _FakeConn(cur)
    monkeypatch.setattr(agent, "_get_db_conn", lambda: conn)

    rows = asyncio.run(agent.get_agent_logs("diagnosis", limit=5, _=None))

    assert conn.closed is True
    assert rows == [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "timestamp": "2026-05-28T09:30:00+00:00",
            "agent": "diagnosis",
            "level": "decision",
            "content": "risk_reflector via deepseek-v4-pro: tokens=75, cost_usd=0.045600, latency_ms=1234",
            "run_id": "reflect-1",
        }
    ]
    assert cur.calls[0][1] == (["risk_reflector"], 5)
