"""iter 165 MVP 4.6 Chunk 1 — daily_reconciliation EXECUTION_MODE SSOT regression guards.

Tests that settings.EXECUTION_MODE (pydantic-settings auto-loaded from
backend/.env) replaces direct os.environ.get read so schtask launches
without sourced .env still resolve correctly.

Pre-fix root cause: `python.exe scripts/daily_reconciliation.py` schtask
launches with empty Windows process env → os.environ.get("EXECUTION_MODE")
returns "" → falls through paper-mode graceful skip guard → FATAL sys.exit
(exit code 1, observed 2026-05-26 15:40:01 schtask Last Result via
schtasks /Query /TN QuantMind_DailyReconciliation /V).

Post-fix: settings.EXECUTION_MODE reads via pydantic-settings BaseSettings
which auto-loads backend/.env regardless of process env (铁律 34 SSOT).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import daily_reconciliation as dr_mod  # noqa: E402


@pytest.fixture
def mock_qmt_config():
    """Ensure query_qmt_positions reaches EXECUTION_MODE guard (past L60-64 None-return)."""
    from app.config import settings

    with (
        patch.object(settings, "QMT_PATH", "C:/fake/qmt/path"),
        patch.object(settings, "QMT_ACCOUNT_ID", "test_account_iter_165"),
    ):
        yield


def test_paper_mode_triggers_exit_0(mock_qmt_config):
    """settings.EXECUTION_MODE='paper' → sys.exit(0) graceful skip."""
    from app.config import settings

    with (
        patch.object(settings, "EXECUTION_MODE", "paper"),
        pytest.raises(SystemExit) as exc_info,
    ):
        dr_mod.query_qmt_positions()

    assert exc_info.value.code == 0, (
        f"Expected SystemExit(0) for paper mode, got code={exc_info.value.code!r}"
    )


def test_empty_mode_triggers_fatal_exit_with_message(mock_qmt_config):
    """settings.EXECUTION_MODE='' (unconfigured) → FATAL sys.exit with explanatory message.

    Pre-iter-165 reality: schtask launched without sourced .env meant
    os.environ.get returned "" → this same FATAL path. Post-fix, settings
    auto-loads .env so this empty case requires explicit override (test only).
    """
    from app.config import settings

    with (
        patch.object(settings, "EXECUTION_MODE", ""),
        pytest.raises(SystemExit) as exc_info,
    ):
        dr_mod.query_qmt_positions()

    code = exc_info.value.code
    assert isinstance(code, str), f"Expected string exit code (FATAL message), got {code!r}"
    assert "[FATAL]" in code
    assert "EXECUTION_MODE=live" in code


def test_ssot_uses_settings_not_os_environ(mock_qmt_config):
    """Regression guard: prove settings.EXECUTION_MODE (NOT os.environ) is the source.

    Sets os.environ['EXECUTION_MODE']='live' but patches settings to 'paper'.
    Settings-based read must yield exit 0 (paper graceful skip). If the SSOT
    fix regressed and os.environ became the source again, the function would
    proceed past the guard (live path) and likely fail later — exit code
    would NOT be 0.
    """
    from app.config import settings

    original_env = os.environ.get("EXECUTION_MODE")
    os.environ["EXECUTION_MODE"] = "live"  # would falsely allow if os.environ was source
    try:
        with (
            patch.object(settings, "EXECUTION_MODE", "paper"),
            pytest.raises(SystemExit) as exc_info,
        ):
            dr_mod.query_qmt_positions()
        assert exc_info.value.code == 0, (
            f"Expected exit 0 (settings='paper' wins), got code={exc_info.value.code!r}. "
            "This indicates os.environ['EXECUTION_MODE']='live' leaked into the check, "
            "meaning the iter 165 SSOT fix has regressed."
        )
    finally:
        if original_env is None:
            os.environ.pop("EXECUTION_MODE", None)
        else:
            os.environ["EXECUTION_MODE"] = original_env
