"""Tests for GP engine upgrade — dimensional types, new operators,
correlated mutation, catastrophe algorithm.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.mining.factor_dsl import (
    ALL_OPS,
    DIM_GROUPS,
    TERMINAL_DIM,
    DimType,
    ExprNode,
    FactorDSL,
    OpType,
    check_dimensional_validity,
    infer_dimension,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def dsl():
    return FactorDSL(seed=42)


@pytest.fixture
def market_data():
    np.random.seed(42)
    n = 100
    return pd.DataFrame({
        "close": np.random.randn(n).cumsum() + 50,
        "open": np.random.randn(n).cumsum() + 50,
        "high": np.random.randn(n).cumsum() + 52,
        "low": np.random.randn(n).cumsum() + 48,
        "volume": np.random.randint(100, 10000, n).astype(float),
        "amount": np.random.randint(100000, 1000000, n).astype(float),
        "returns": np.random.randn(n) * 0.02,
        "turnover_rate": np.random.uniform(0.01, 0.1, n),
        "pe_ttm": np.random.uniform(5, 50, n),
        "pb": np.random.uniform(0.5, 5, n),
    }, index=range(n))


# ============================================================
# 1. Dimensional Type System
# ============================================================

class TestDimType:
    def test_all_terminals_mapped(self):
        from engines.mining.factor_dsl import TERMINALS
        for t in TERMINALS:
            assert t in TERMINAL_DIM, f"{t} missing from TERMINAL_DIM"

    def test_dim_groups_complete(self):
        for dim in [DimType.PRICE, DimType.RATIO, DimType.AMOUNT]:
            assert dim in DIM_GROUPS
            assert len(DIM_GROUPS[dim]) >= 1


class TestInferDimension:
    def test_terminal_price(self, dsl):
        tree = dsl.from_string("close")
        assert infer_dimension(tree) == DimType.PRICE

    def test_terminal_ratio(self, dsl):
        tree = dsl.from_string("returns")
        assert infer_dimension(tree) == DimType.RATIO

    def test_ts_mean_preserves_dim(self, dsl):
        tree = dsl.from_string("ts_mean(close, 20)")
        assert infer_dimension(tree) == DimType.PRICE

    def test_cs_rank_produces_ratio(self, dsl):
        tree = dsl.from_string("cs_rank(close)")
        assert infer_dimension(tree) == DimType.RATIO

    def test_div_same_dim_produces_ratio(self, dsl):
        tree = dsl.from_string("div(close, high)")
        assert infer_dimension(tree) == DimType.RATIO

    def test_add_same_dim_preserves(self, dsl):
        tree = dsl.from_string("add(close, high)")
        assert infer_dimension(tree) == DimType.PRICE

    def test_log_produces_ratio(self, dsl):
        tree = dsl.from_string("log(returns)")
        assert infer_dimension(tree) == DimType.RATIO

    def test_ts_corr_produces_ratio(self, dsl):
        tree = dsl.from_string("ts_corr(close, volume, 20)")
        assert infer_dimension(tree) == DimType.RATIO

    def test_ts_slope_produces_ratio(self, dsl):
        tree = dsl.from_string("ts_slope(close, 20)")
        assert infer_dimension(tree) == DimType.RATIO

    def test_ts_argmax_produces_ratio(self, dsl):
        tree = dsl.from_string("ts_argmax(close, 20)")
        assert infer_dimension(tree) == DimType.RATIO


class TestDimensionalValidity:
    """10 valid + 10 invalid expressions."""

    # ---- VALID ----
    def test_valid_add_same_dim(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("add(close, high)"))
        assert ok

    def test_valid_sub_same_dim(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("sub(close, low)"))
        assert ok

    def test_valid_div_same_dim(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("div(close, open)"))
        assert ok

    def test_valid_log_ratio(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("log(returns)"))
        assert ok

    def test_valid_sqrt_ratio(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("sqrt(turnover_rate)"))
        assert ok

    def test_valid_ts_mean_any(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("ts_mean(close, 20)"))
        assert ok

    def test_valid_cs_rank_any(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("cs_rank(volume)"))
        assert ok

    def test_valid_mul_different_dims(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("mul(close, volume)"))
        assert ok

    def test_valid_nested_complex(self, dsl):
        ok, _ = check_dimensional_validity(
            dsl.from_string("ts_mean(div(close, open), 20)")
        )
        assert ok

    def test_valid_ifelse(self, dsl):
        ok, _ = check_dimensional_validity(
            dsl.from_string("ifelse(returns, close, high)")
        )
        assert ok

    # ---- INVALID ----
    def test_invalid_add_price_volume(self, dsl):
        ok, reason = check_dimensional_validity(dsl.from_string("add(close, volume)"))
        assert not ok
        assert "量纲" in reason

    def test_invalid_sub_price_ratio(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("sub(close, returns)"))
        assert not ok

    def test_invalid_add_amount_volume(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("add(amount, volume)"))
        assert not ok

    def test_invalid_log_price(self, dsl):
        ok, reason = check_dimensional_validity(dsl.from_string("log(close)"))
        assert not ok
        assert "log" in reason

    def test_invalid_sqrt_price(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("sqrt(close)"))
        assert not ok

    def test_invalid_mul_price_price(self, dsl):
        ok, reason = check_dimensional_validity(dsl.from_string("mul(close, high)"))
        assert not ok
        assert "同类型相乘" in reason

    def test_invalid_mul_volume_volume(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("mul(volume, volume)"))
        assert not ok

    def test_invalid_add_mcap_price(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("add(total_mv, close)"))
        assert not ok

    def test_invalid_nested_add_mixed(self, dsl):
        ok, _ = check_dimensional_validity(
            dsl.from_string("ts_mean(add(close, returns), 20)")
        )
        assert not ok

    def test_invalid_sub_amount_ratio(self, dsl):
        ok, _ = check_dimensional_validity(dsl.from_string("sub(amount, returns)"))
        assert not ok


class TestValidateIntegration:
    def test_validate_catches_dim_error(self, dsl):
        tree = dsl.from_string("add(close, volume)")
        ok, msg = dsl.validate(tree)
        assert not ok
        assert "量纲" in msg

    def test_validate_passes_valid(self, dsl):
        tree = dsl.from_string("ts_mean(div(close, open), 20)")
        ok, msg = dsl.validate(tree)
        assert ok


# ============================================================
# 2. New Operators
# ============================================================

class TestNewOperatorRegistration:
    @pytest.mark.parametrize("op", [
        "ts_slope", "ts_rsquare", "ts_decay_linear",
        "ts_argmax", "ts_argmin", "power", "ifelse",
    ])
    def test_operator_in_registry(self, op):
        assert op in ALL_OPS

    def test_ifelse_is_ternary(self):
        assert ALL_OPS["ifelse"]["type"] == OpType.TERNARY
        assert ALL_OPS["ifelse"]["args"] == 3

    def test_power_is_binary(self):
        assert ALL_OPS["power"]["type"] == OpType.BINARY

    def test_total_operator_count(self):
        assert len(ALL_OPS) == 35


class TestNewOperatorEvaluation:
    def test_ts_slope(self, dsl, market_data):
        tree = dsl.from_string("ts_slope(close, 20)")
        result = tree.evaluate(market_data)
        assert result.dropna().shape[0] > 50

    def test_ts_rsquare(self, dsl, market_data):
        tree = dsl.from_string("ts_rsquare(close, 20)")
        result = tree.evaluate(market_data)
        valid = result.dropna()
        assert valid.shape[0] > 50
        # R² should be in [0, 1]
        assert valid.min() >= -0.01
        assert valid.max() <= 1.01

    def test_ts_decay_linear(self, dsl, market_data):
        tree = dsl.from_string("ts_decay_linear(close, 20)")
        result = tree.evaluate(market_data)
        assert result.dropna().shape[0] > 50

    def test_ts_decay_linear_weights_recent(self, dsl):
        # Recent values should have more weight
        data = pd.DataFrame({"close": [1.0] * 19 + [100.0]}, index=range(20))
        tree = dsl.from_string("ts_decay_linear(close, 20)")
        result = tree.evaluate(data)
        last_val = result.iloc[-1]
        simple_mean = data["close"].mean()  # 5.95
        assert last_val > simple_mean  # decay gives more weight to recent 100.0

    def test_ts_argmax(self, dsl, market_data):
        tree = dsl.from_string("ts_argmax(close, 20)")
        result = tree.evaluate(market_data)
        valid = result.dropna()
        assert valid.shape[0] > 50
        # Normalized to [0, 1]
        assert valid.min() >= 0.0
        assert valid.max() <= 1.0

    def test_ts_argmin(self, dsl, market_data):
        tree = dsl.from_string("ts_argmin(close, 20)")
        result = tree.evaluate(market_data)
        valid = result.dropna()
        assert valid.shape[0] > 50
        assert valid.min() >= 0.0
        assert valid.max() <= 1.0

    def test_power(self, dsl, market_data):
        tree = dsl.from_string("power(close, returns)")
        result = tree.evaluate(market_data)
        assert result.dropna().shape[0] > 50

    def test_ifelse(self, dsl, market_data):
        tree = dsl.from_string("ifelse(returns, close, volume)")
        result = tree.evaluate(market_data)
        assert result.dropna().shape[0] > 50
        # When returns > 0, should get close; when <= 0, volume
        for i in range(20, 80):
            if market_data["returns"].iloc[i] > 0:
                assert result.iloc[i] == pytest.approx(market_data["close"].iloc[i])
            else:
                assert result.iloc[i] == pytest.approx(market_data["volume"].iloc[i])


class TestNewOperatorSerialization:
    @pytest.mark.parametrize("expr", [
        "ts_slope(close, 20)",
        "ts_rsquare(returns, 10)",
        "ts_decay_linear(close, 60)",
        "ts_argmax(close, 5)",
        "ts_argmin(volume, 20)",
        "power(close, returns)",
        "ifelse(returns, close, volume)",
    ])
    def test_roundtrip(self, dsl, expr):
        tree = dsl.from_string(expr)
        serialized = tree.to_string()
        tree2 = dsl.from_string(serialized)
        assert tree2.to_string() == serialized


# ============================================================
# 3. Correlated Mutation
# ============================================================

class TestCorrelatedMutation:
    def test_always_produces_valid(self, dsl):
        tree = dsl.from_string("ts_mean(close, 20)")
        for _ in range(30):
            mutated = dsl.correlated_mutate(tree)
            ok, msg = dsl.validate(mutated)
            assert ok, f"Invalid mutation: {msg} -> {mutated.to_string()}"

    def test_produces_different_trees(self, dsl):
        tree = dsl.from_string("ts_mean(div(close, open), 20)")
        exprs = set()
        for _ in range(20):
            mutated = dsl.correlated_mutate(tree)
            exprs.add(mutated.to_string())
        assert len(exprs) >= 3, f"Too few unique mutations: {len(exprs)}"

    def test_preserves_structure_partially(self, dsl):
        tree = dsl.from_string("ts_corr(close, volume, 20)")
        # At least some mutations should preserve the outer operator
        preserved_outer = 0
        for _ in range(20):
            mutated = dsl.correlated_mutate(tree)
            if mutated.op == "ts_corr":
                preserved_outer += 1
        # Window/field mutations preserve outer
        assert preserved_outer > 0

    def test_dimensional_validity_maintained(self, dsl):
        trees = [
            dsl.from_string("add(close, high)"),
            dsl.from_string("ts_mean(cs_rank(close), 20)"),
            dsl.from_string("div(close, open)"),
        ]
        for tree in trees:
            for _ in range(10):
                mutated = dsl.correlated_mutate(tree)
                ok, msg = check_dimensional_validity(mutated)
                assert ok, f"Dim invalid: {msg} -> {mutated.to_string()}"


# ============================================================
# 4. Catastrophe Algorithm
# ============================================================

class TestCatastrophe:
    def test_config_defaults(self):
        from engines.mining.gp_engine import GPConfig
        cfg = GPConfig()
        assert cfg.catastrophe_interval == 10
        assert cfg.catastrophe_diversity_threshold == 0.3
        assert cfg.catastrophe_survival_ratio == 0.2

    def test_stats_fields(self):
        from engines.mining.gp_engine import GPRunStats
        stats = GPRunStats(run_id="test")
        assert stats.catastrophe_count == 0
        assert stats.catastrophe_generations == []

    def _make_pop(self, engine, exprs):
        """Helper: create DEAP population from expression strings."""
        from deap import creator
        pop = []
        for expr in exprs:
            tree = engine.dsl.from_string(expr)
            ind = creator.Individual([tree])
            ind.fitness.values = (0.5,)
            pop.append(ind)
        return pop

    def test_catastrophe_detection(self):
        """Low diversity population should trigger catastrophe."""
        from engines.mining.gp_engine import GPConfig, GPEngine, GPRunStats

        cfg = GPConfig(
            catastrophe_diversity_threshold=0.5,
            catastrophe_survival_ratio=0.2,
            population_per_island=10,
            n_islands=1,
            n_generations=1,
        )
        try:
            engine = GPEngine(config=cfg)
        except RuntimeError:
            pytest.skip("DEAP not available")

        stats = GPRunStats(run_id="test")

        # All same tree → diversity = 1/10 = 0.1 < 0.5
        pop = self._make_pop(engine, ["ts_mean(close, 20)"] * 10)

        triggered = engine._check_and_apply_catastrophe(pop, 10, 0, stats)
        assert triggered, "Catastrophe should trigger on low-diversity pop"
        assert stats.catastrophe_count == 1
        assert 10 in stats.catastrophe_generations

    def test_no_catastrophe_on_diverse_pop(self):
        """Diverse population should NOT trigger catastrophe."""
        from engines.mining.gp_engine import GPConfig, GPEngine, GPRunStats

        cfg = GPConfig(
            catastrophe_diversity_threshold=0.3,
            population_per_island=10,
            n_islands=1,
            n_generations=1,
        )
        try:
            engine = GPEngine(config=cfg)
        except RuntimeError:
            pytest.skip("DEAP not available")

        stats = GPRunStats(run_id="test")

        # All different trees → diversity = 10/10 = 1.0 > 0.3
        exprs = [
            "ts_mean(close, 20)", "ts_std(returns, 10)",
            "cs_rank(volume)", "div(close, open)",
            "ts_max(close, 60)", "neg(returns)",
            "ts_min(close, 5)", "abs(returns)",
            "ts_sum(volume, 20)", "inv(pb)",
        ]
        pop = self._make_pop(engine, exprs)

        triggered = engine._check_and_apply_catastrophe(pop, 10, 0, stats)
        assert not triggered, "Catastrophe should NOT trigger on diverse pop"
        assert stats.catastrophe_count == 0
