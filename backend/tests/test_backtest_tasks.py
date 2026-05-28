from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from app.tasks import backtest_tasks
from backend.qm_platform._types import BacktestMode
from backend.qm_platform.backtest import runner as platform_runner_mod


def test_api_worker_runs_backtest_through_platform_runner(monkeypatch):
    """API worker should delegate engine execution to PlatformBacktestRunner."""

    engine_result = SimpleNamespace(daily_nav=pd.Series([1.0, 1.1]))

    class FakePlatformRunner:
        instance = None

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.mode = None
            self.config = None
            self.loaded = None
            self.directions = None
            self.engine_config = None
            self.signal_config = None
            FakePlatformRunner.instance = self

        def run(self, mode, config):
            self.mode = mode
            self.config = config
            self.loaded = self.kwargs["data_loader"](config, config.start, config.end)
            self.directions = self.kwargs["direction_provider"](config.factor_pool)
            self.engine_config = self.kwargs["engine_config_builder"](config)
            self.signal_config = self.kwargs["signal_config_builder"](config)
            return SimpleNamespace(engine_artifacts={"engine_result": engine_result})

    monkeypatch.setattr(platform_runner_mod, "PlatformBacktestRunner", FakePlatformRunner)

    factor_df = pd.DataFrame({"factor_name": ["factor_a"], "raw_value": [1.0]})
    price_df = pd.DataFrame({"code": ["000001.SZ"], "close": [10.0]})
    bench_df = pd.DataFrame({"trade_date": [date(2026, 1, 2)], "close": [100.0]})

    result, elapsed = backtest_tasks._run_platform_backtest(
        cfg={
            "initial_capital": 2_000_000,
            "holding_count": 7,
            "rebalance_freq": "weekly",
            "benchmark": "000300.SH",
            "slippage_model": "fixed",
            "size_neutral_beta": 0.25,
        },
        start_dt=date(2026, 1, 1),
        end_dt=date(2026, 3, 31),
        factors=["factor_a", "missing_direction_factor"],
        factor_df=factor_df,
        price_df=price_df,
        bench_df=bench_df,
        directions={"factor_a": -1},
    )

    fake_runner = FakePlatformRunner.instance
    assert result is engine_result
    assert elapsed >= 0
    assert fake_runner.mode == BacktestMode.AD_HOC
    assert fake_runner.config.factor_pool == ("factor_a",)
    assert fake_runner.config.top_n == 7
    assert fake_runner.config.benchmark == "csi300"
    assert fake_runner.loaded == (factor_df, price_df, bench_df)
    assert fake_runner.directions == {"factor_a": -1}
    assert fake_runner.engine_config.initial_capital == 2_000_000
    assert fake_runner.engine_config.top_n == 7
    assert fake_runner.engine_config.rebalance_freq == "weekly"
    assert fake_runner.engine_config.slippage_mode == "fixed"
    assert fake_runner.engine_config.benchmark_code == "000300.SH"
    assert fake_runner.signal_config.size_neutral_beta == 0.25


def test_api_worker_fails_loud_when_no_factor_direction():
    """Empty direction maps should fail before invoking a misleading all-+1 run."""

    with pytest.raises(ValueError, match="factor_registry"):
        backtest_tasks._run_platform_backtest(
            cfg={},
            start_dt=date(2026, 1, 1),
            end_dt=date(2026, 1, 31),
            factors=["factor_a"],
            factor_df=pd.DataFrame(),
            price_df=pd.DataFrame(),
            bench_df=None,
            directions={},
        )
