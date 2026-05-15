"""Tests for `app.services.v3_cutover_adapter` — IC-1a facade adapter.

Plan v0.4 §A IC-1a — surgical replace of legacy `check_circuit_breaker_sync`
in `scripts/run_paper_trading.py`. IC-1a behavior is intentionally minimal
(facade only, no V3 engine.run() to avoid double-call of `_check_cb_sync`),
so tests validate:

  1. Happy path — args passed through correctly to `_legacy_cb_sync`
  2. Return dict shape 1:1 with legacy contract
  3. Observability log line emitted
  4. Exception propagation (fail-loud, sustained legacy behavior — V3 engine
     additions in future sub-PRs will wrap in try/except → fail-open + P0)

关联铁律: 31 / 33 / 40 (test debt 不增, baseline 2864 pass / 24 fail)
关联 ADR: ADR-076 / Plan v0.4 §A IC-1a
"""

from __future__ import annotations

import inspect
import logging
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.risk_control_service import (
    check_circuit_breaker_sync as _legacy_for_sig_check,
)
from app.services.v3_cutover_adapter import check_v3_circuit_breaker

_FAKE_CB_DICT = {
    "level": 2,
    "action": "暂停1天",
    "reason": "L2 总组合日亏 5.2% > 5%",
    "position_multiplier": 1.0,
    "recovery_info": "次日自动恢复",
}


# Patch target = the alias name in the adapter's module namespace, NOT the source
# module. Because the adapter does `from ... import check_circuit_breaker_sync as
# _legacy_cb_sync`, the name `_legacy_cb_sync` is bound in `v3_cutover_adapter`'s
# namespace at import time, and `check_v3_circuit_breaker` looks it up there. If
# someone later drops the `as _legacy_cb_sync` alias, this patch path will silently
# stop intercepting — update the patch target accordingly.


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_passes_args_through(mock_legacy: MagicMock) -> None:
    """Args 1:1 forwarded to legacy `_check_cb_sync` (drop-in replacement contract)."""
    mock_legacy.return_value = _FAKE_CB_DICT
    fake_conn = MagicMock()
    exec_d = date(2026, 5, 15)

    result = check_v3_circuit_breaker(
        conn=fake_conn,
        strategy_id="paper-strategy-uuid",
        exec_date=exec_d,
        initial_capital=1_000_000.0,
    )

    mock_legacy.assert_called_once_with(
        conn=fake_conn,
        strategy_id="paper-strategy-uuid",
        exec_date=exec_d,
        initial_capital=1_000_000.0,
    )
    assert result == _FAKE_CB_DICT


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_returns_dict_shape_compatible(
    mock_legacy: MagicMock,
) -> None:
    """Return dict has all 5 legacy keys with correct types."""
    mock_legacy.return_value = _FAKE_CB_DICT

    result = check_v3_circuit_breaker(
        conn=MagicMock(),
        strategy_id="x",
        exec_date=date(2026, 5, 15),
        initial_capital=1_000_000.0,
    )

    assert set(result.keys()) >= {
        "level",
        "action",
        "reason",
        "position_multiplier",
        "recovery_info",
    }
    assert isinstance(result["level"], int)
    assert isinstance(result["position_multiplier"], float)
    assert 0 <= result["level"] <= 4


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_handles_l0_safe_default(
    mock_legacy: MagicMock,
) -> None:
    """L0 safe-default dict (no CB triggered) passes through unchanged."""
    l0_dict = {
        "level": 0,
        "action": "normal",
        "reason": "ok",
        "position_multiplier": 1.0,
        "recovery_info": "",
    }
    mock_legacy.return_value = l0_dict

    result = check_v3_circuit_breaker(
        conn=MagicMock(),
        strategy_id="x",
        exec_date=date(2026, 5, 15),
        initial_capital=1_000_000.0,
    )
    assert result == l0_dict
    assert result["level"] == 0
    assert result["position_multiplier"] == 1.0


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_handles_l4_position_multiplier_zero(
    mock_legacy: MagicMock,
) -> None:
    """L4 (停止所有交易) returns position_multiplier=0.0 — must propagate exactly."""
    l4_dict = {
        "level": 4,
        "action": "停止所有交易",
        "reason": "L4 累计亏损 28% > 25%",
        "position_multiplier": 0.0,
        "recovery_info": "需人工脚本approve后重置",
    }
    mock_legacy.return_value = l4_dict

    result = check_v3_circuit_breaker(
        conn=MagicMock(),
        strategy_id="x",
        exec_date=date(2026, 5, 15),
        initial_capital=1_000_000.0,
    )
    assert result["level"] == 4
    assert result["position_multiplier"] == 0.0


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_emits_observability_log(
    mock_legacy: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """[v3-cutover] observability log emitted with level + action + multiplier."""
    mock_legacy.return_value = _FAKE_CB_DICT

    with caplog.at_level(logging.INFO, logger="app.services.v3_cutover_adapter"):
        check_v3_circuit_breaker(
            conn=MagicMock(),
            strategy_id="x",
            exec_date=date(2026, 5, 15),
            initial_capital=1_000_000.0,
        )

    log_text = caplog.text
    assert "[v3-cutover]" in log_text
    assert "level=2" in log_text
    assert "暂停1天" in log_text
    assert "position_multiplier=1.0" in log_text
    assert "IC-1a facade" in log_text


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_propagates_legacy_exception(
    mock_legacy: MagicMock,
) -> None:
    """Legacy exception propagates fail-loud (IC-1a no V3 engine wrap yet).

    Future IC sub-PRs will wrap V3 engine.run() additions in try/except →
    fail-open + P0 alert (V3 §0.5 design pattern). Until then, adapter
    behavior is identical to legacy: exceptions propagate (sustained 铁律 33).
    """
    mock_legacy.side_effect = RuntimeError("simulated DB connection lost")

    with pytest.raises(RuntimeError, match="simulated DB connection lost"):
        check_v3_circuit_breaker(
            conn=MagicMock(),
            strategy_id="x",
            exec_date=date(2026, 5, 15),
            initial_capital=1_000_000.0,
        )


def test_check_v3_circuit_breaker_signature_matches_legacy() -> None:
    """Sig 4 keyword args (conn, strategy_id, exec_date, initial_capital) — drop-in contract."""
    legacy_sig = inspect.signature(_legacy_for_sig_check)
    v3_sig = inspect.signature(check_v3_circuit_breaker)

    legacy_params = set(legacy_sig.parameters.keys())
    v3_params = set(v3_sig.parameters.keys())
    assert legacy_params == v3_params, (
        f"v3 adapter sig must match legacy 1:1 (drop-in contract); "
        f"legacy={legacy_params}, v3={v3_params}"
    )


@patch("app.services.v3_cutover_adapter._legacy_cb_sync")
def test_check_v3_circuit_breaker_handles_malformed_legacy_return(
    mock_legacy: MagicMock,
) -> None:
    """Adapter returns malformed dict as-is + log line doesn't crash on missing keys.

    Defends against pre-existing legacy contract drift — if `_legacy_cb_sync`
    returns a partial dict (missing `level`/`action`/`position_multiplier`),
    adapter must still pass it through without raising. Downstream
    `cb.get(key, default)` callers absorb the missing-key risk per their own
    defaults (`run_paper_trading.py` uses `cb.get("level", 0)` etc).
    """
    malformed = {"level": 0}  # missing action/reason/position_multiplier/recovery_info
    mock_legacy.return_value = malformed

    result = check_v3_circuit_breaker(
        conn=MagicMock(),
        strategy_id="x",
        exec_date=date(2026, 5, 15),
        initial_capital=1_000_000.0,
    )
    assert result is malformed  # same object, no copy/mutation
    assert result.get("level") == 0
    assert result.get("position_multiplier") is None  # absent, .get() defaults None
