"""Smoke test for realtime_risk_tick Beat task (iter 163 Phase J §1.1 Chunk 6).

MVP 4.5 §3 Chunk 6 — Calendar gate + smoke test marker.

Marked `@pytest.mark.smoke` for pre-push hook coverage (`pytest -m smoke`).
Sibling pattern: backend/tests/test_*_smoke.py (sustained smoke coverage).

E2E light verification (no DB / no Beat fire):
- Task module loads + registers with celery_app
- Engine singleton bootstraps with 10 rules
- AlertDispatcher singleton wires send_fn
- L4ExecutionPlanner singleton constructs
- Calendar gate import resolves
"""

from __future__ import annotations

import pytest


@pytest.mark.smoke
class TestRealtimeRiskBeatSmoke:
    """Smoke test — module-level imports + singletons construct OK."""

    def test_task_module_imports_clean(self):
        """All imports resolve without error (catches missing deps + circular imports)."""
        from app.tasks import realtime_risk_tasks  # noqa: F401, PLC0415

        # Sanity assert task is registered
        assert hasattr(realtime_risk_tasks, "realtime_risk_tick")

    def test_engine_singleton_constructs(self):
        """_get_engine() runs without error (10 rules + threshold cache wired)."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        # Reset for clean test
        task_mod._engine = None
        try:
            engine = task_mod._get_engine()
            assert engine is not None
            # Re-call should return same instance
            assert task_mod._get_engine() is engine
        finally:
            task_mod._engine = None

    def test_dispatcher_singleton_constructs(self):
        """_get_dispatcher() runs without error (send_fn wired)."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        task_mod._dispatcher = None
        try:
            dispatcher = task_mod._get_dispatcher()
            assert dispatcher is not None
            assert task_mod._get_dispatcher() is dispatcher
        finally:
            task_mod._dispatcher = None

    def test_planner_singleton_constructs(self):
        """_get_planner() runs without error (default STAGED_ENABLED=false)."""
        from app.tasks import realtime_risk_tasks as task_mod  # noqa: PLC0415

        task_mod._planner = None
        try:
            planner = task_mod._get_planner()
            assert planner is not None
            assert task_mod._get_planner() is planner
        finally:
            task_mod._planner = None

    def test_calendar_gate_imported(self):
        """is_trading_day_today_or_skip resolves (Calendar gate H4 pattern)."""
        from app.tasks.realtime_risk_tasks import is_trading_day_today_or_skip  # noqa: PLC0415

        assert callable(is_trading_day_today_or_skip)

    def test_beat_schedule_entry_present(self):
        """realtime-risk-tick entry registered in CELERY_BEAT_SCHEDULE."""
        from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE  # noqa: PLC0415

        assert "realtime-risk-tick" in CELERY_BEAT_SCHEDULE
        entry = CELERY_BEAT_SCHEDULE["realtime-risk-tick"]
        assert entry["task"] == "app.tasks.realtime_risk_tasks.realtime_risk_tick"

    def test_task_discoverable_by_worker(self):
        """celery_app.tasks contains realtime_risk_tick (worker bootstrap discovery)."""
        from app.tasks.celery_app import celery_app  # noqa: PLC0415

        assert "app.tasks.realtime_risk_tasks.realtime_risk_tick" in celery_app.tasks
