"""MVP 2.3 Sub1 PR B · PlatformBacktestRunner 单测 (不依赖 DB, 不跑 engine).

覆盖:
  - config_hash: 稳定性 (same config → same hash) + 敏感性 (diff config → diff hash)
  - _apply_mode: QUICK_1Y/FULL_5Y/FULL_12Y 基于 config.end 倒推; WF_5FOLD/LIVE_PT 原样
  - cache hit: registry.get_by_hash 命中 → 直接返, 不调 engine
  - cache miss + LIVE_PT: get_by_hash None → 真跑 (mock engine)
  - _factor_directions: placeholder +1 统一
  - _build_engine_config: cost_model 映射 historical_stamp_tax
  - _build_lineage: inputs + code + params 字段正确
  - data_loader None → raise NotImplementedError
  - run() 端到端 mock (DAL + engine + registry 全 mock)

铁律: 15 (config_hash 复现) / 17 (DataPipeline 入库 via registry) / 38.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from backend.platform._types import BacktestMode
from backend.platform.backtest.interface import BacktestConfig, BacktestResult
from backend.platform.backtest.runner import PlatformBacktestRunner

# ─── Fixtures ──────────────────────────────────────────────


def _make_config(**overrides) -> BacktestConfig:
    """默认 BacktestConfig, 可 override 任何字段."""
    base = {
        "start": date(2020, 1, 1),
        "end": date(2025, 12, 31),
        "universe": "csi300",
        "factor_pool": ("bp_ratio", "dv_ttm"),
        "rebalance_freq": "monthly",
        "top_n": 20,
        "industry_cap": 1.0,
        "size_neutral_beta": 0.50,
        "cost_model": "full",
        "capital": "1000000.0",
        "benchmark": "csi300",
        "extra": {},
    }
    base.update(overrides)
    return BacktestConfig(**base)


def _fake_perf() -> SimpleNamespace:
    """Fake PerformanceReport — 仅暴露 Runner 用到的字段 + to_dict()."""
    return SimpleNamespace(
        sharpe_ratio=1.2,
        annual_return=0.15,
        max_drawdown=-0.08,
        total_return=0.92,
        total_trades=123,
        calmar_ratio=1.875,
        sortino_ratio=1.5,
        information_ratio=0.5,
        beta=0.9,
        win_rate=0.55,
        profit_loss_ratio=1.3,
        annual_turnover=3.5,
        max_consecutive_loss_days=7,
        bootstrap_sharpe_ci=(1.2, 0.9, 1.5),
        avg_open_gap=0.002,
        mean_position_deviation=0.01,
        to_dict=lambda: {"sharpe": 1.2, "annual_return": 0.15, "max_drawdown": -0.08},
    )


def _fake_engine_result() -> SimpleNamespace:
    """Fake Engine BacktestResult — `.metrics()` 返 fake perf."""
    return SimpleNamespace(metrics=_fake_perf)


# ─── config_hash stability + sensitivity (4 tests) ─────────


def test_config_hash_stability_same_config_same_hash():
    """同 config 两次 → 必同 hash (铁律 15 复现)."""
    cfg = _make_config()
    h1 = PlatformBacktestRunner._compute_config_hash(cfg)
    h2 = PlatformBacktestRunner._compute_config_hash(cfg)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_config_hash_sensitivity_factor_pool():
    """factor_pool 变 → hash 变."""
    cfg_a = _make_config(factor_pool=("bp_ratio", "dv_ttm"))
    cfg_b = _make_config(factor_pool=("bp_ratio", "volatility_20"))
    assert PlatformBacktestRunner._compute_config_hash(
        cfg_a
    ) != PlatformBacktestRunner._compute_config_hash(cfg_b)


def test_config_hash_sensitivity_top_n():
    """top_n 变 → hash 变."""
    cfg_a = _make_config(top_n=20)
    cfg_b = _make_config(top_n=30)
    assert PlatformBacktestRunner._compute_config_hash(
        cfg_a
    ) != PlatformBacktestRunner._compute_config_hash(cfg_b)


def test_config_hash_default_str_handles_date():
    """date 字段 json 不可直接序列化, default=str 必处理, 不 raise."""
    cfg = _make_config()
    # 不 raise 即通过
    h = PlatformBacktestRunner._compute_config_hash(cfg)
    assert isinstance(h, str)


# ─── _apply_mode (5 tests) ─────────────────────────────────


def test_apply_mode_quick_1y():
    """QUICK_1Y: end 倒推 1 年."""
    cfg = _make_config(end=date(2025, 12, 31))
    start, end = PlatformBacktestRunner._apply_mode(cfg, BacktestMode.QUICK_1Y)
    assert end == date(2025, 12, 31)
    assert start.year == 2024 and start.month == 12


def test_apply_mode_full_5y():
    """FULL_5Y: end 倒推 5 年."""
    cfg = _make_config(end=date(2025, 12, 31))
    start, _ = PlatformBacktestRunner._apply_mode(cfg, BacktestMode.FULL_5Y)
    assert start.year == 2020 and start.month == 12


def test_apply_mode_full_12y():
    """FULL_12Y: end 倒推 12 年."""
    cfg = _make_config(end=date(2025, 12, 31))
    start, _ = PlatformBacktestRunner._apply_mode(cfg, BacktestMode.FULL_12Y)
    assert start.year == 2013 and start.month == 12


def test_apply_mode_wf_5fold_preserves_config_range():
    """WF_5FOLD: 沿用 config.start/end 原样."""
    cfg = _make_config(start=date(2014, 1, 1), end=date(2025, 12, 31))
    start, end = PlatformBacktestRunner._apply_mode(cfg, BacktestMode.WF_5FOLD)
    assert start == date(2014, 1, 1)
    assert end == date(2025, 12, 31)


def test_apply_mode_live_pt_preserves_config_range():
    """LIVE_PT: 沿用 config.start/end 原样 (不 override)."""
    cfg = _make_config(start=date(2026, 1, 1), end=date(2026, 4, 19))
    start, end = PlatformBacktestRunner._apply_mode(cfg, BacktestMode.LIVE_PT)
    assert start == date(2026, 1, 1)
    assert end == date(2026, 4, 19)


# ─── Cache 语义 (3 tests) ───────────────────────────────────


def test_cache_hit_skips_engine():
    """registry.get_by_hash 命中 → 直接返 cached, 不调 data_loader / engine."""
    cached = BacktestResult(
        run_id=uuid4(),
        config_hash="cached_hash",
        git_commit="abc123",
        sharpe=1.0,
        annual_return=0.1,
        max_drawdown=-0.05,
        total_return=0.5,
        trades_count=10,
        metrics={},
    )
    registry = MagicMock()
    registry.get_by_hash.return_value = cached

    data_loader = MagicMock()  # 应该不被调用
    runner = PlatformBacktestRunner(registry=registry, data_loader=data_loader)

    result = runner.run(BacktestMode.QUICK_1Y, _make_config())

    assert result is cached
    registry.get_by_hash.assert_called_once()
    data_loader.assert_not_called()
    registry.log_run.assert_not_called()


def test_cache_miss_runs_engine():
    """get_by_hash None → 真跑 (mock engine + data_loader)."""
    registry = MagicMock()
    registry.get_by_hash.return_value = None
    registry.log_run.return_value = uuid4()  # lineage_id

    data_loader = MagicMock(return_value=(MagicMock(), MagicMock(), None))
    runner = PlatformBacktestRunner(
        registry=registry,
        data_loader=data_loader,
        direction_provider=lambda pool: dict.fromkeys(pool, 1),  # PR C1: 避免 fallback warn
    )

    with patch(
        "backend.platform.backtest.runner.run_hybrid_backtest", return_value=_fake_engine_result()
    ):
        result = runner.run(BacktestMode.QUICK_1Y, _make_config())

    assert result.sharpe == 1.2
    assert result.lineage_id is not None
    data_loader.assert_called_once()
    registry.log_run.assert_called_once()


def test_live_pt_does_not_check_cache():
    """LIVE_PT 每次强制 re-run, 不调 get_by_hash."""
    registry = MagicMock()
    data_loader = MagicMock(return_value=(MagicMock(), MagicMock(), None))
    runner = PlatformBacktestRunner(
        registry=registry,
        data_loader=data_loader,
        direction_provider=lambda pool: dict.fromkeys(pool, 1),
    )

    registry.log_run.return_value = uuid4()
    with patch(
        "backend.platform.backtest.runner.run_hybrid_backtest", return_value=_fake_engine_result()
    ):
        runner.run(BacktestMode.LIVE_PT, _make_config())

    registry.get_by_hash.assert_not_called()  # LIVE_PT 跳过 cache 查
    data_loader.assert_called_once()


# ─── 其他 helpers (3 tests) ─────────────────────────────────


def test_factor_directions_placeholder_all_positive():
    """PR B placeholder staticmethod: 所有因子统一 +1 direction (不安全 fallback)."""
    dirs = PlatformBacktestRunner._factor_directions(("a", "b", "c"))
    assert dirs == {"a": 1, "b": 1, "c": 1}


def test_resolve_directions_uses_provider_when_given():
    """PR C1: direction_provider 注入时优先走 provider (生产路径)."""
    provider_calls: list[tuple[str, ...]] = []

    def _fake_provider(pool):
        provider_calls.append(pool)
        return {"turnover_mean_20": -1, "bp_ratio": 1}

    runner = PlatformBacktestRunner(registry=MagicMock(), direction_provider=_fake_provider)
    dirs = runner._resolve_directions(("turnover_mean_20", "bp_ratio"))

    assert dirs == {"turnover_mean_20": -1, "bp_ratio": 1}
    assert provider_calls == [("turnover_mean_20", "bp_ratio")]


def test_resolve_directions_none_provider_emits_userwarning():
    """PR C1: direction_provider=None 走 placeholder + UserWarning (显式 warn, 非 silent)."""
    import warnings as _w

    runner = PlatformBacktestRunner(registry=MagicMock(), direction_provider=None)
    with _w.catch_warnings(record=True) as captured:
        _w.simplefilter("always")
        dirs = runner._resolve_directions(("turnover_mean_20", "bp_ratio"))

    assert dirs == {"turnover_mean_20": 1, "bp_ratio": 1}
    assert any(
        issubclass(w.category, UserWarning) and "direction_provider=None" in str(w.message)
        for w in captured
    ), "必须 emit UserWarning 提示 placeholder 风险"


def test_build_engine_config_maps_cost_model_full():
    """cost_model='full' → historical_stamp_tax=True."""
    cfg = _make_config(cost_model="full", capital="2000000.0", benchmark="csi300", top_n=25)
    engine_cfg = PlatformBacktestRunner._build_engine_config(cfg)
    assert engine_cfg.historical_stamp_tax is True
    assert engine_cfg.initial_capital == 2_000_000.0
    assert engine_cfg.benchmark_code == "000300.SH"
    assert engine_cfg.top_n == 25


def test_build_engine_config_maps_cost_model_simplified():
    """cost_model='simplified' → historical_stamp_tax=False."""
    cfg = _make_config(cost_model="simplified", benchmark="none")
    engine_cfg = PlatformBacktestRunner._build_engine_config(cfg)
    assert engine_cfg.historical_stamp_tax is False
    assert engine_cfg.benchmark_code == ""


def test_data_loader_none_raises_not_implemented():
    """PR B 默认 data_loader=None, run() 走到该步 raise."""
    registry = MagicMock()
    registry.get_by_hash.return_value = None
    runner = PlatformBacktestRunner(registry=registry, data_loader=None)

    with pytest.raises(NotImplementedError, match="data_loader"):
        runner.run(BacktestMode.QUICK_1Y, _make_config())


# ─── _build_lineage 结构验证 (1 test) ──────────────────────


def test_build_lineage_structure():
    """Lineage inputs + code + params 字段正确."""
    cfg = _make_config(factor_pool=("bp_ratio", "dv_ttm"), benchmark="csi300")
    runner = PlatformBacktestRunner(registry=MagicMock())
    lineage = runner._build_lineage(
        cfg,
        git_commit="abc1234",
        mode=BacktestMode.FULL_5Y,
        config_hash="h" * 64,
        start_date=date(2020, 1, 1),
        end_date=date(2025, 12, 31),
    )

    # inputs 含 factor_values + klines_daily + index_daily (benchmark='csi300')
    input_tables = [i.table for i in lineage.inputs]
    assert "factor_values" in input_tables
    assert "klines_daily" in input_tables
    assert "index_daily" in input_tables

    # code 正确
    assert lineage.code.git_commit == "abc1234"
    assert lineage.code.module == "backend.platform.backtest.runner"

    # params 含核心信息
    assert lineage.params["mode"] == "full_5y"
    assert lineage.params["config_hash"] == "h" * 64
    assert lineage.params["universe"] == "csi300"
    assert lineage.params["top_n"] == 20


def test_build_lineage_no_benchmark_skips_index_daily():
    """benchmark='none' → 不加 index_daily LineageRef."""
    cfg = _make_config(benchmark="none")
    runner = PlatformBacktestRunner(registry=MagicMock())
    lineage = runner._build_lineage(
        cfg,
        git_commit=None,
        mode=BacktestMode.QUICK_1Y,
        config_hash="x",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
    )
    input_tables = [i.table for i in lineage.inputs]
    assert "index_daily" not in input_tables


# ─── run() 端到端 mock (1 integration test) ────────────────


def test_run_end_to_end_mock_integration():
    """run() 端到端: data_loader + engine + registry 全 mock, 验证调用顺序 + lineage_id 回填."""
    registry = MagicMock()
    registry.get_by_hash.return_value = None
    expected_lineage_id = uuid4()
    registry.log_run.return_value = expected_lineage_id

    data_loader = MagicMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
    runner = PlatformBacktestRunner(
        registry=registry,
        data_loader=data_loader,
        conn="fake_conn",
        direction_provider=lambda pool: dict.fromkeys(pool, 1),
    )

    with patch(
        "backend.platform.backtest.runner.run_hybrid_backtest",
        return_value=_fake_engine_result(),
    ) as mock_engine:
        result = runner.run(BacktestMode.FULL_5Y, _make_config())

    # Engine 调用 (包而不改 verify)
    mock_engine.assert_called_once()
    kwargs = mock_engine.call_args.kwargs
    assert kwargs["conn"] == "fake_conn"  # conn 正确传递

    # registry.log_run 调用含 mode/elapsed_sec/lineage/perf
    log_kwargs = registry.log_run.call_args.kwargs
    assert log_kwargs["mode"] == BacktestMode.FULL_5Y
    assert log_kwargs["lineage"] is not None
    assert log_kwargs["perf"] is not None
    assert log_kwargs["elapsed_sec"] >= 0

    # lineage_id 回填 BacktestResult
    assert result.lineage_id == expected_lineage_id
    assert result.sharpe == 1.2  # 来自 fake perf


# ─── engine_artifacts 传递 (PR C2, 3 tests) ───────────────


def test_result_default_engine_artifacts_is_none():
    """BacktestResult 默认 engine_artifacts=None (向后兼容 18 调用方)."""
    r = BacktestResult(
        run_id=uuid4(),
        config_hash="h",
        git_commit="g",
        sharpe=1.0,
        annual_return=0.1,
        max_drawdown=-0.05,
        total_return=0.5,
        trades_count=10,
        metrics={},
    )
    assert r.engine_artifacts is None
    assert r.lineage_id is None


def test_run_cache_miss_populates_engine_artifacts():
    """PR C2: cache-miss 真跑 → result.engine_artifacts 含 engine_result + price_data.

    PR C2 review P2 fix: 同时断言 lineage_id 回填成功, 验证 ``replace(platform_result,
    lineage_id=...)`` 不破坏 engine_artifacts 字段 (frozen dataclass replace 应保所有字段).
    """
    registry = MagicMock()
    registry.get_by_hash.return_value = None
    expected_lineage_id = uuid4()
    registry.log_run.return_value = expected_lineage_id

    fake_price_data = MagicMock(name="price_data")
    fake_factor_df = MagicMock(name="factor_df")
    data_loader = MagicMock(return_value=(fake_factor_df, fake_price_data, None))
    runner = PlatformBacktestRunner(
        registry=registry,
        data_loader=data_loader,
        direction_provider=lambda pool: dict.fromkeys(pool, 1),
    )

    fake_engine_result_obj = _fake_engine_result()
    with patch(
        "backend.platform.backtest.runner.run_hybrid_backtest",
        return_value=fake_engine_result_obj,
    ):
        result = runner.run(BacktestMode.QUICK_1Y, _make_config())

    # engine_artifacts 必含 engine_result + price_data (消费者取 daily_nav)
    # identity (`is`) 断言: runner 不得 copy/wrap engine_result 或 price_data,
    # 消费者走 generate_report(result, price_data) 依赖对象身份.
    # BacktestResult.__post_init__ 浅拷贝外层 dict (防消费者污染), 但 values
    # 仍是同对象引用 (review P1 契约: 外 dict 隔离 + 内对象共享只读).
    assert result.engine_artifacts is not None
    assert result.engine_artifacts["engine_result"] is fake_engine_result_obj
    assert result.engine_artifacts["price_data"] is fake_price_data

    # replace(lineage_id=...) 必保 engine_artifacts 字段 (PR C2 review P2)
    assert result.lineage_id == expected_lineage_id


def test_engine_artifacts_shallow_copied_in_post_init():
    """PR C2 review P1 fix: __post_init__ 浅拷贝外层 dict 隔离消费者 mutation.

    场景: Runner 内部持 artifacts_dict 引用, result 构造时浅拷贝. 消费者
    ``result.engine_artifacts["engine_result"] = None`` 不应污染 Runner 原引用.
    (frozen=True 只防 ``result.engine_artifacts = ...`` 重新赋值.)
    """
    src = {"engine_result": "A", "price_data": "B"}
    r = BacktestResult(
        run_id=uuid4(),
        config_hash="h",
        git_commit="g",
        sharpe=1.0,
        annual_return=0.1,
        max_drawdown=-0.05,
        total_return=0.5,
        trades_count=10,
        metrics={},
        engine_artifacts=src,
    )
    # 消费者污染外层 dict
    r.engine_artifacts["engine_result"] = "POISONED"
    # 源 dict 不受影响 (浅拷贝隔离)
    assert src["engine_result"] == "A"
    assert src["price_data"] == "B"


def test_cache_hit_no_engine_artifacts():
    """Cache-hit 走 DB round-trip, engine_artifacts 恒 None (DBBacktestRegistry 不落 Series).

    这是本 PR C2 架构的关键契约 — DB 不持久化 pandas Series, 消费者必须知情.
    """
    cached = BacktestResult(
        run_id=uuid4(),
        config_hash="cached_hash",
        git_commit="abc123",
        sharpe=1.0,
        annual_return=0.1,
        max_drawdown=-0.05,
        total_return=0.5,
        trades_count=10,
        metrics={},
        # engine_artifacts 默认 None 不显式传
    )
    registry = MagicMock()
    registry.get_by_hash.return_value = cached

    runner = PlatformBacktestRunner(registry=registry, data_loader=MagicMock())
    result = runner.run(BacktestMode.FULL_5Y, _make_config())

    assert result is cached
    assert result.engine_artifacts is None
