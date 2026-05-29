"""MiningService contract tests.

These tests cover the real service layer behind /api/mining/evaluate. Router
tests use a mocked service, so they cannot catch FactorGate contract drift.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services import mining_service as mining_service_mod
from app.services.mining_service import MiningService


def _gate(status: str, metric_value: float | None = None, data: dict | None = None):
    return SimpleNamespace(status=status, metric_value=metric_value, data=data or {})


def test_summarize_gate_report_uses_current_gate_report_contract() -> None:
    report = SimpleNamespace(
        gates={
            "G1": _gate("PASS", 0.031),
            "G2": _gate("PASS"),
            "G3": _gate("PASS", 2.7),
            "G6": _gate("PENDING", data={"raw_t_stat": 2.7}),
        },
        overall_status="PARTIAL",
    )

    summary = mining_service_mod._summarize_gate_report(report)

    assert summary == {"G1": "PASS", "G2": "PASS", "G3": "PASS", "G6": "PENDING"}
    assert mining_service_mod._gate_report_passed(report, summary) is True
    assert mining_service_mod._gate_report_metric(report, "ic_mean") == pytest.approx(0.031)
    assert mining_service_mod._gate_report_metric(report, "t_stat") == pytest.approx(2.7)


def test_quick_only_summary_filters_to_automatic_gates() -> None:
    report = SimpleNamespace(
        gates={
            "G1": _gate("PASS"),
            "G2": _gate("PASS"),
            "G3": _gate("PASS"),
            "G4": _gate("PASS"),
            "G5": _gate("PASS"),
            "G6": _gate("PENDING"),
            "G7": _gate("PENDING"),
            "G8": _gate("PENDING"),
        },
        overall_status="PARTIAL",
    )

    summary = mining_service_mod._summarize_gate_report(report, quick_only=True)

    assert set(summary) == {"G1", "G2", "G3", "G4", "G5"}
    assert mining_service_mod._gate_report_passed(report, summary, quick_only=True) is True


@pytest.mark.asyncio()
async def test_evaluate_factor_gate_calls_run_gates_contract(monkeypatch) -> None:
    rows = []
    start = date(2026, 1, 1)
    for i in range(32):
        trade_date = start + timedelta(days=i)
        for j, code in enumerate(("000001.SZ", "000002.SZ", "600000.SH")):
            close = 10.0 + i * (0.2 + j * 0.03) + j
            rows.append(
                (
                    trade_date,
                    code,
                    close - 0.1,
                    close + 0.2,
                    close - 0.3,
                    close,
                    1000 + i + j,
                    10000 + i + j,
                    0.5,
                    12.0,
                    1.2,
                )
            )

    class FakeConn:
        async def fetch(self, *_args, **_kwargs):
            return rows

        async def close(self):
            return None

    async def fake_connect(_db_url):
        return FakeConn()

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=fake_connect))

    class FakeGatePipeline:
        last_instance = None

        def __init__(self):
            self.run_gates_calls = []
            FakeGatePipeline.last_instance = self

        def run_gates(self, **kwargs):
            self.run_gates_calls.append(kwargs)
            return SimpleNamespace(
                gates={
                    "G1": _gate("PASS", 0.031),
                    "G2": _gate("PASS"),
                    "G3": _gate("PASS", 2.8),
                    "G4": _gate("PASS"),
                    "G5": _gate("PASS"),
                    "G6": _gate("PENDING", data={"raw_t_stat": 2.8}),
                    "G7": _gate("PENDING"),
                    "G8": _gate("PENDING"),
                },
                overall_status="PARTIAL",
            )

    import engines.factor_gate as factor_gate_mod

    monkeypatch.setattr(factor_gate_mod, "FactorGatePipeline", FakeGatePipeline)

    service = MiningService(session=SimpleNamespace())

    result = await service.evaluate_factor_gate("returns", factor_name="eval_returns")

    fake_gate = FakeGatePipeline.last_instance
    assert fake_gate is not None
    assert len(fake_gate.run_gates_calls) == 1
    assert fake_gate.run_gates_calls[0]["factor_name"] == "eval_returns"
    assert "ic_series" in fake_gate.run_gates_calls[0]
    assert result["overall_passed"] is True
    assert result["overall_status"] == "PARTIAL"
    assert result["gate_result"]["G6"] == "PENDING"
