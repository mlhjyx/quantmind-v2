"""Strategy signal production boundary regression tests."""

from __future__ import annotations

import inspect


def test_signal_service_uses_platform_pipeline_for_live_s1_path() -> None:
    """Current PT signal generation is SDK-backed, not raw SignalComposer-only."""
    from app.services.signal_service import SignalService

    source = inspect.getsource(SignalService.generate_signals)

    assert "PlatformSignalPipeline" in source
    assert "S1MonthlyRanking" in source
    assert ".generate(_strategy, _ctx)" in source


def test_daily_signal_task_keeps_registry_loop_out_of_production_boundary() -> None:
    """Daily signal task remains the legacy PT orchestrator boundary by design."""
    from app.tasks import daily_pipeline

    source = inspect.getsource(daily_pipeline._async_signal)

    assert "run_signal_phase" in source
    assert "get_live_strategies_for_risk_check" not in source
    assert "DBStrategyRegistry" not in source
