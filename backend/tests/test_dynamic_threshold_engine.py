"""Unit tests for DynamicThresholdEngine + caches (S7 L3 动态阈值).

覆盖:
  - MarketState: Calm/Stress/Crisis 评估边界
  - Stock multiplier: ATR/beta/liquidity 组合
  - Industry adjustment: CorrelatedDrop min_count
  - Full evaluate: thresholds_cache 输出
  - ThresholdCache: InMemory + Redis (stub)
  - Stress 模拟 (V3 §6 acceptance)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.qm_platform.risk.dynamic_threshold.cache import (
    InMemoryThresholdCache,
    RedisThresholdCache,
)
from backend.qm_platform.risk.dynamic_threshold.engine import (
    DynamicThresholdEngine,
    MarketIndicators,
    MarketState,
    StockMetrics,
)

# ── MarketState assessment (V3 §6.1) ──


class TestMarketState:
    def test_calm_default(self):
        engine = DynamicThresholdEngine()
        assert engine.assess_market_state(MarketIndicators()) == MarketState.CALM

    def test_calm_normal_range(self):
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(index_return=-0.01, limit_down_count=30))
            == MarketState.CALM
        )

    def test_stress_index(self):
        """大盘 -2% → Stress."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(index_return=-0.03)) == MarketState.STRESS
        )

    def test_stress_index_boundary(self):
        """大盘 -2% 刚好 → Stress."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(index_return=-0.02)) == MarketState.STRESS
        )

    def test_stress_limit_down(self):
        """跌停 51 > 50 → Stress."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(limit_down_count=51)) == MarketState.STRESS
        )

    def test_stress_limit_down_boundary(self):
        """跌停 51 > 50 → Stress, 50 不触发."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(limit_down_count=51)) == MarketState.STRESS
        )
        assert engine.assess_market_state(MarketIndicators(limit_down_count=50)) == MarketState.CALM

    def test_stress_bear_regime(self):
        """regime=Bear → Stress (case-insensitive)."""
        engine = DynamicThresholdEngine()
        assert engine.assess_market_state(MarketIndicators(regime="Bear")) == MarketState.STRESS
        assert engine.assess_market_state(MarketIndicators(regime="BEAR")) == MarketState.STRESS

    def test_crisis_index(self):
        """大盘 -5% → Crisis."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(index_return=-0.06)) == MarketState.CRISIS
        )

    def test_crisis_index_boundary(self):
        """大盘 -5% 刚好 → Crisis."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(index_return=-0.05)) == MarketState.CRISIS
        )

    def test_crisis_limit_down(self):
        """跌停 201 > 200 → Crisis."""
        engine = DynamicThresholdEngine()
        assert (
            engine.assess_market_state(MarketIndicators(limit_down_count=201)) == MarketState.CRISIS
        )

    def test_crisis_overrides_stress(self):
        """Crisis 条件优先于 Stress."""
        engine = DynamicThresholdEngine()
        # Both Stress (-2%) and Crisis (201 跌停) conditions
        assert (
            engine.assess_market_state(MarketIndicators(index_return=-0.03, limit_down_count=201))
            == MarketState.CRISIS
        )

    def test_market_multiplier_values(self):
        engine = DynamicThresholdEngine()
        mult = engine.market_multiplier
        assert mult[MarketState.CALM] == 1.0
        assert mult[MarketState.STRESS] == 0.8
        assert mult[MarketState.CRISIS] == 0.5


# ── Stock multiplier (V3 §6.2) ──


class TestStockMultiplier:
    def test_default(self):
        engine = DynamicThresholdEngine()
        assert engine.compute_stock_multiplier(StockMetrics(code="test")) == 1.0

    def test_high_beta(self):
        """β > 1.5 → ×1.2."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(StockMetrics(code="test", beta=1.6))
        assert mult == 1.2

    def test_beta_boundary(self):
        """β = 1.5 不触发."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(StockMetrics(code="test", beta=1.5))
        assert mult == 1.0

    def test_low_liquidity(self):
        """vol 分位 < 20% → ×1.5."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(StockMetrics(code="test", liquidity_percentile=0.15))
        assert mult == 1.5

    def test_liquidity_boundary(self):
        """vol 分位 = 0.20 不触发."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(StockMetrics(code="test", liquidity_percentile=0.20))
        assert mult == 1.0

    def test_high_atr(self):
        """ATR/price > 5% → ×1.5."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(StockMetrics(code="test", atr_ratio=0.06))
        assert mult == 1.5

    def test_atr_boundary(self):
        """ATR/price = 0.05 不触发."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(StockMetrics(code="test", atr_ratio=0.05))
        assert mult == 1.0

    def test_combined_multipliers(self):
        """高 beta + 低 liquidity → 1.2 × 1.5 = 1.8."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(
            StockMetrics(code="test", beta=1.8, liquidity_percentile=0.10)
        )
        assert mult == 1.8

    def test_all_three(self):
        """高 beta + 低 liquidity + 高 ATR → 1.2 × 1.5 × 1.5 = 2.7."""
        engine = DynamicThresholdEngine()
        mult = engine.compute_stock_multiplier(
            StockMetrics(
                code="test",
                beta=2.0,
                liquidity_percentile=0.05,
                atr_ratio=0.08,
            )
        )
        assert mult == 2.7


# ── Industry adjustment (V3 §6.3) ──


class TestIndustryAdjustment:
    def test_default_min_count(self):
        engine = DynamicThresholdEngine()
        assert engine.compute_industry_adjustment([], {}) == 3

    def test_no_industry_data_no_adjust(self):
        engine = DynamicThresholdEngine()
        sm = {"600519.SH": StockMetrics(code="600519.SH")}
        assert engine.compute_industry_adjustment(["600519.SH"], sm) == 3

    def test_industry_down_adjusts(self):
        """同行业 3 股 + day -4% → min_count 3→2."""
        engine = DynamicThresholdEngine()
        sm = {
            "A": StockMetrics(code="A", industry="银行"),
            "B": StockMetrics(code="B", industry="银行"),
            "C": StockMetrics(code="C", industry="银行"),
        }
        industry_ret = {"银行": -0.04}
        assert engine.compute_industry_adjustment(["A", "B", "C"], sm, industry_ret) == 2

    def test_industry_down_boundary(self):
        """行业 day -3% 刚好 → 调整."""
        engine = DynamicThresholdEngine()
        sm = {
            "A": StockMetrics(code="A", industry="电子"),
            "B": StockMetrics(code="B", industry="电子"),
        }
        industry_ret = {"电子": -0.03}
        assert engine.compute_industry_adjustment(["A", "B"], sm, industry_ret) == 2

    def test_industry_down_insufficient_count(self):
        """仅 1 股同行业, 不调整."""
        engine = DynamicThresholdEngine()
        sm = {
            "A": StockMetrics(code="A", industry="银行"),
        }
        industry_ret = {"银行": -0.05}
        assert engine.compute_industry_adjustment(["A"], sm, industry_ret) == 3

    def test_industry_not_down_no_adjust(self):
        """行业 day -1%, 不调整."""
        engine = DynamicThresholdEngine()
        sm = {
            "A": StockMetrics(code="A", industry="银行"),
            "B": StockMetrics(code="B", industry="银行"),
            "C": StockMetrics(code="C", industry="银行"),
        }
        industry_ret = {"银行": -0.01}
        assert engine.compute_industry_adjustment(["A", "B", "C"], sm, industry_ret) == 3


# ── Full evaluate (V3 §6.4) ──


class TestFullEvaluate:
    def test_calm_no_stocks(self):
        """Calm 状态, 无个股数据 → market-level multipliers."""
        engine = DynamicThresholdEngine()
        cache = engine.evaluate(MarketIndicators())
        assert "rapid_drop_5min" in cache
        # Calm → 1.0x, default 0.05
        assert cache["rapid_drop_5min"][""] == pytest.approx(0.05)

    def test_stress_no_stocks(self):
        """Stress → 0.8x market multiplier."""
        engine = DynamicThresholdEngine()
        cache = engine.evaluate(MarketIndicators(index_return=-0.03))
        # rapid_drop_5min: market-sensitive, 0.05 * 0.8 = 0.04
        assert cache["rapid_drop_5min"][""] == pytest.approx(0.04)
        # volume_spike: NOT market-sensitive, stays 3.0
        assert cache["volume_spike"][""] == pytest.approx(3.0)

    def test_crisis_no_stocks(self):
        """Crisis → 0.5x."""
        engine = DynamicThresholdEngine()
        cache = engine.evaluate(MarketIndicators(index_return=-0.06))
        assert cache["rapid_drop_5min"][""] == pytest.approx(0.025)

    def test_with_stock_metrics(self):
        """Calm + 2 股 (1 normal, 1 high beta)."""
        engine = DynamicThresholdEngine()
        sm = {
            "600519.SH": StockMetrics(code="600519.SH"),
            "000001.SZ": StockMetrics(code="000001.SZ", beta=2.0),
        }
        cache = engine.evaluate(MarketIndicators(), stock_metrics=sm)

        # 600519: normal, rapid_drop_5min = 0.05
        assert cache["rapid_drop_5min"]["600519.SH"] == pytest.approx(0.05)
        # 000001: high beta ×1.2, rapid_drop_5min = 0.05 * 1.2 = 0.06
        assert cache["rapid_drop_5min"]["000001.SZ"] == pytest.approx(0.06)

    def test_stress_with_high_beta(self):
        """Stress (0.8x) + high beta (1.2x) = 0.96x."""
        engine = DynamicThresholdEngine()
        sm = {"600519.SH": StockMetrics(code="600519.SH", beta=2.0)}
        cache = engine.evaluate(MarketIndicators(index_return=-0.03), stock_metrics=sm)
        # 0.05 * 0.8 * 1.2 = 0.048
        assert cache["rapid_drop_5min"]["600519.SH"] == pytest.approx(0.048)

    def test_correlated_drop_min_count_in_cache(self):
        """CorrelatedDrop cache 存 min_count (非 multiplier)."""
        engine = DynamicThresholdEngine()
        sm = {
            "A": StockMetrics(code="A", industry="银行"),
            "B": StockMetrics(code="B", industry="银行"),
        }
        industry_ret = {"银行": -0.04}
        cache = engine.evaluate(
            MarketIndicators(),
            stock_metrics=sm,
            industry_day_return=industry_ret,
        )
        assert cache["correlated_drop"]["A"] == 2.0
        assert cache["correlated_drop"]["B"] == 2.0

    def test_market_insensitive_rules(self):
        """volume_spike / liquidity_collapse 不受 market state 影响."""
        engine = DynamicThresholdEngine()
        cache = engine.evaluate(
            MarketIndicators(index_return=-0.06)  # Crisis
        )
        assert cache["volume_spike"][""] == pytest.approx(3.0)
        assert cache["liquidity_collapse"][""] == pytest.approx(0.3)

    def test_custom_defaults(self):
        """自定义 defaults 替换内置值."""
        engine = DynamicThresholdEngine(defaults={"rapid_drop_5min": 0.07})
        cache = engine.evaluate(MarketIndicators())
        assert cache["rapid_drop_5min"][""] == pytest.approx(0.07)


# ── InMemoryThresholdCache ──


class TestInMemoryCache:
    def test_set_and_get(self):
        cache = InMemoryThresholdCache()
        cache.set_batch({"rapid_drop_5min": {"600519.SH": 0.04}})
        assert cache.get("rapid_drop_5min", "600519.SH") == 0.04

    def test_get_missing_rule(self):
        cache = InMemoryThresholdCache()
        assert cache.get("nonexistent", "600519.SH") is None

    def test_get_missing_code(self):
        cache = InMemoryThresholdCache()
        cache.set_batch({"rapid_drop_5min": {"600519.SH": 0.04}})
        assert cache.get("rapid_drop_5min", "000001.SZ") is None

    def test_set_batch_replaces(self):
        """全量替换, 非增量 merge."""
        cache = InMemoryThresholdCache()
        cache.set_batch({"rapid_drop_5min": {"600519.SH": 0.04}})
        cache.set_batch({"volume_spike": {"000001.SZ": 3.0}})
        # 旧数据被清
        assert cache.get("rapid_drop_5min", "600519.SH") is None
        assert cache.get("volume_spike", "000001.SZ") == 3.0

    def test_flush(self):
        cache = InMemoryThresholdCache()
        cache.set_batch({"rapid_drop_5min": {"600519.SH": 0.04}})
        cache.flush()
        assert cache.get("rapid_drop_5min", "600519.SH") is None

    def test_len(self):
        cache = InMemoryThresholdCache()
        assert len(cache) == 0
        cache.set_batch(
            {
                "rapid_drop_5min": {"A": 1.0, "B": 2.0},
                "volume_spike": {"A": 3.0},
            }
        )
        assert len(cache) == 3


# ── RedisThresholdCache (stub — no real Redis required) ──


class TestRedisCache:
    def test_set_and_get_with_mock(self):
        """用 MagicMock 模拟 Redis client."""
        mock_redis = MagicMock()
        mock_redis.pipeline.return_value = MagicMock()

        cache = RedisThresholdCache(redis_client=mock_redis)
        cache.set_batch({"rapid_drop_5min": {"600519.SH": 0.04}})

        # Verify Redis SETEX calls
        pipe = mock_redis.pipeline.return_value
        assert pipe.setex.call_count == 1

    def test_get_returns_none_on_disconnect(self):
        """Redis 不可用 → get 返 None."""
        cache = RedisThresholdCache()  # no client
        # 尝试连接会失败 (no Redis running in CI), 返 None
        result = cache.get("rapid_drop_5min", "600519.SH")
        # 可能 None (连接失败) 或 float (Redis 可用)
        assert result is None or isinstance(result, float)

    def test_set_batch_noop_on_disconnect(self):
        """Redis 不可用 → set_batch 不抛异常."""
        cache = RedisThresholdCache()
        cache.set_batch({"rapid_drop_5min": {"600519.SH": 0.04}})
        # 不抛异常 = pass


# ── Stress simulation (acceptance: Stress 模拟) ──


class TestStressSimulation:
    """V3 §6 acceptance: Stress 模拟 — 端到端动态阈值调整验证."""

    def test_stress_scenario_calm_to_crisis(self):
        """模拟市场从 Calm → Stress → Crisis 的阈值变化."""
        engine = DynamicThresholdEngine()
        sm = {"600519.SH": StockMetrics(code="600519.SH", beta=1.0)}

        # Calm
        calm = engine.evaluate(MarketIndicators(), stock_metrics=sm)
        assert calm["rapid_drop_5min"]["600519.SH"] == pytest.approx(0.05)

        # Stress (大盘 -3%)
        stress = engine.evaluate(
            MarketIndicators(index_return=-0.03),
            stock_metrics=sm,
        )
        assert stress["rapid_drop_5min"]["600519.SH"] == pytest.approx(0.04)

        # Crisis (大盘 -6%)
        crisis = engine.evaluate(
            MarketIndicators(index_return=-0.06),
            stock_metrics=sm,
        )
        assert crisis["rapid_drop_5min"]["600519.SH"] == pytest.approx(0.025)

    def test_stress_scenario_with_concentration(self):
        """模拟 Stress + 行业集中 → CorrelatedDrop min_count 降低."""
        engine = DynamicThresholdEngine()
        sm = {
            "A": StockMetrics(code="A", industry="银行"),
            "B": StockMetrics(code="B", industry="银行"),
            "C": StockMetrics(code="C", industry="电子"),
        }
        # Stress + 行业银行 day -5%
        cache = engine.evaluate(
            MarketIndicators(index_return=-0.03),
            stock_metrics=sm,
            industry_day_return={"银行": -0.05},
        )
        # CorrelatedDrop min_count 从 3→2 (industry) + rapid_drop_5min 收紧
        assert cache["correlated_drop"]["A"] == 2.0
        assert cache["rapid_drop_5min"]["A"] == pytest.approx(0.04)  # 0.05 * 0.8

    def test_multi_stock_different_beta(self):
        """不同 beta 股票在 Stress 下阈值不同."""
        engine = DynamicThresholdEngine()
        sm = {
            "normal": StockMetrics(code="normal", beta=1.0),
            "high_beta": StockMetrics(code="high_beta", beta=2.0),
            "low_liq": StockMetrics(code="low_liq", liquidity_percentile=0.10),
        }
        cache = engine.evaluate(
            MarketIndicators(index_return=-0.03),
            stock_metrics=sm,
        )
        # normal: 0.05 * 0.8 = 0.04
        assert cache["rapid_drop_5min"]["normal"] == pytest.approx(0.04)
        # high_beta: 0.05 * 0.8 * 1.2 = 0.048
        assert cache["rapid_drop_5min"]["high_beta"] == pytest.approx(0.048)
        # low_liq: 0.05 * 0.8 * 1.5 = 0.06
        assert cache["rapid_drop_5min"]["low_liq"] == pytest.approx(0.06)
