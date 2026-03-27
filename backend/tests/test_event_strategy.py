"""EventStrategy 单元测试。

验证清单:
- TradingEvent dataclass完整性（字段/默认值）
- event_filter抽象方法必须被子类实现
- position_sizing边界（max_positions, stop_loss）
- should_rebalance()总是返回True（事件型每日检查）
- 空事件列表 → 不调仓，保持原持仓
- 所有事件被过滤 → 不调仓
- 事件处理 → 生成新持仓
- aggregate_events同一股票多事件取最大绝对值
- top_n约束：超过top_n时按权重截断
- EventStrategy config验证（top_n必填，factor_names可选）
- EventType枚举完整性
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.base_strategy import SignalType, StrategyContext
from engines.strategies.event_strategy import (
    EventStrategy,
    EventType,
    TradingEvent,
)

# ============================================================
# 测试用子类实现
# ============================================================


class _SimpleEventStrategy(EventStrategy):
    """最简单的EventStrategy实现，用于测试。

    event_filter: 过滤signal_value < 0的事件（只处理看多）
    position_sizing: min(max_position_size, |signal_value| * 0.1)
    on_event: 直接用position_sizing结果设置仓位
    """

    def event_filter(self, event: TradingEvent, context: StrategyContext) -> bool:
        """过滤：只接受signal_value > 0的看多事件。"""
        return event.signal_value > 0

    def position_sizing(self, event: TradingEvent, context: StrategyContext) -> float:
        """仓位大小 = min(max_position_size, |signal_value| * 0.1)。"""
        max_pos = self.config.get("max_position_size", 0.15)
        return min(max_pos, abs(event.signal_value) * 0.1)

    def on_event(
        self, event: TradingEvent, context: StrategyContext
    ) -> dict[str, float] | None:
        """处理事件，返回{code: target_weight}。"""
        size = self.position_sizing(event, context)
        if size <= 0:
            return None
        return {event.code: size}


def _make_event_config(**overrides) -> dict:
    """生成EventStrategy标准配置。"""
    config = {
        "top_n": 10,
        "weight_method": "equal",
        "max_position_size": 0.15,
        "min_signal_strength": 0.3,
        "stop_loss_pct": 0.08,
    }
    config.update(overrides)
    return config


def _make_context(prev_holdings: dict[str, float] | None = None) -> StrategyContext:
    """构建最小化StrategyContext。"""
    import pandas as pd

    return StrategyContext(
        strategy_id="test_event",
        trade_date=date(2024, 1, 31),
        factor_df=pd.DataFrame(columns=["code", "factor_name", "neutral_value"]),
        universe=set(),
        industry_map={},
        prev_holdings=prev_holdings,
        conn=None,
        total_capital=1_000_000.0,
    )


def _make_event(
    code: str = "600519.SH",
    signal_value: float = 0.8,
    event_type: EventType = EventType.RSRS_BREAKOUT,
    event_date: date | None = None,
) -> TradingEvent:
    """构建TradingEvent。"""
    return TradingEvent(
        event_type=event_type,
        code=code,
        event_date=event_date or date(2024, 1, 31),
        signal_value=signal_value,
        meta={},
    )


# ============================================================
# 1. TradingEvent dataclass测试
# ============================================================


class TestTradingEvent:
    """TradingEvent dataclass完整性验证。"""

    def test_basic_creation(self) -> None:
        """TradingEvent基本创建，字段正确。"""
        ev = TradingEvent(
            event_type=EventType.PEAD,
            code="000001.SZ",
            event_date=date(2024, 1, 31),
            signal_value=0.7,
        )
        assert ev.event_type == EventType.PEAD
        assert ev.code == "000001.SZ"
        assert ev.event_date == date(2024, 1, 31)
        assert ev.signal_value == 0.7
        assert ev.meta == {}  # 默认空dict

    def test_meta_field_optional(self) -> None:
        """meta字段可选，默认为空dict。"""
        ev = _make_event()
        assert isinstance(ev.meta, dict)

    def test_meta_with_data(self) -> None:
        """meta可存储任意附加数据。"""
        ev = TradingEvent(
            event_type=EventType.BLOCK_TRADE,
            code="300750.SZ",
            event_date=date(2024, 1, 31),
            signal_value=0.5,
            meta={"volume": 1000000, "holder": "大股东A"},
        )
        assert ev.meta["volume"] == 1000000
        assert ev.meta["holder"] == "大股东A"

    def test_negative_signal_value(self) -> None:
        """signal_value可以为负（看空信号）。"""
        ev = _make_event(signal_value=-0.5)
        assert ev.signal_value == -0.5

    def test_all_event_types(self) -> None:
        """EventType包含所有预期类型。"""
        assert EventType.RSRS_BREAKOUT == "rsrs_breakout"
        assert EventType.PEAD == "pead"
        assert EventType.ST_REMOVAL == "st_removal"
        assert EventType.BLOCK_TRADE == "block_trade"
        assert EventType.CUSTOM == "custom"


# ============================================================
# 2. EventStrategy抽象方法验证
# ============================================================


class TestEventStrategyAbstract:
    """event_filter/on_event/position_sizing抽象方法验证。"""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """EventStrategy本身不能实例化（含抽象方法）。"""
        with pytest.raises(TypeError):
            EventStrategy(config=_make_event_config(), strategy_id="bad")  # type: ignore

    def test_concrete_subclass_instantiates(self) -> None:
        """实现了所有抽象方法的子类可以实例化。"""
        config = _make_event_config()
        strategy = _SimpleEventStrategy(config=config, strategy_id="simple")
        assert strategy.strategy_id == "simple"

    def test_signal_type_is_event(self) -> None:
        """EventStrategy.signal_type=EVENT。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        assert strategy.signal_type == SignalType.EVENT

    def test_meta_info(self) -> None:
        """get_meta返回EVENT信号类型。"""
        from engines.base_strategy import RebalanceFreq, WeightMethod

        meta = EventStrategy.get_meta()
        assert meta.signal_type == SignalType.EVENT
        assert RebalanceFreq.DAILY in meta.supported_freqs
        assert WeightMethod.EQUAL in meta.supported_weights


# ============================================================
# 3. should_rebalance总是True
# ============================================================


class TestEventStrategyShouldRebalance:
    """should_rebalance()总是返回True。"""

    def test_always_returns_true(self) -> None:
        """事件型策略每日检查，should_rebalance总是True。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        mock_conn = MagicMock()
        for d in [date(2024, 1, 1), date(2024, 6, 15), date(2024, 12, 31)]:
            assert strategy.should_rebalance(d, mock_conn) is True


# ============================================================
# 4. 空事件列表 → 不调仓
# ============================================================


class TestEventStrategyEmptyEvents:
    """空事件列表和全过滤场景验证。"""

    def test_no_events_keeps_prev_holdings(self) -> None:
        """无事件时保持原持仓，is_rebalance=False。"""
        prev = {"600519.SH": 0.5, "000001.SZ": 0.5}
        context = _make_context(prev_holdings=prev)
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        # load_events返回空列表
        strategy.load_events = MagicMock(return_value=[])

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is False
        assert decision.target_weights == prev

    def test_no_events_no_prev_holdings_empty_weights(self) -> None:
        """无事件且无prev_holdings时，target_weights为空。"""
        context = _make_context(prev_holdings=None)
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        strategy.load_events = MagicMock(return_value=[])

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is False
        assert decision.target_weights == {}

    def test_all_events_filtered_keeps_prev_holdings(self) -> None:
        """所有事件被event_filter过滤时，保持原持仓。"""
        prev = {"600519.SH": 1.0}
        context = _make_context(prev_holdings=prev)
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        # 所有事件signal_value<0（_SimpleEventStrategy只接受>0）
        bad_events = [
            _make_event("A.SH", signal_value=-0.9),
            _make_event("B.SH", signal_value=-0.5),
        ]
        strategy.load_events = MagicMock(return_value=bad_events)

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is False
        assert decision.target_weights == prev

    def test_on_event_returns_none_no_rebalance(self) -> None:
        """on_event返回None时，不改变持仓。"""

        class _IgnoreEventStrategy(_SimpleEventStrategy):
            def on_event(self, event, context):
                return None  # 忽略所有事件

        strategy = _IgnoreEventStrategy(config=_make_event_config(), strategy_id="t")
        prev = {"A.SH": 1.0}
        context = _make_context(prev_holdings=prev)

        positive_events = [_make_event("A.SH", signal_value=0.9)]
        strategy.load_events = MagicMock(return_value=positive_events)

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is False
        assert decision.target_weights == prev


# ============================================================
# 5. 事件处理 → 生成新持仓
# ============================================================


class TestEventStrategyProcessing:
    """事件处理逻辑验证。"""

    def test_single_event_generates_position(self) -> None:
        """单个有效事件生成目标持仓，is_rebalance=True。"""
        context = _make_context(prev_holdings={})
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        events = [_make_event("600519.SH", signal_value=0.8)]
        strategy.load_events = MagicMock(return_value=events)

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is True
        assert "600519.SH" in decision.target_weights
        assert decision.target_weights["600519.SH"] > 0

    def test_multiple_events_multiple_positions(self) -> None:
        """多个有效事件生成多只持仓。"""
        context = _make_context(prev_holdings={})
        strategy = _SimpleEventStrategy(config=_make_event_config(top_n=10), strategy_id="t")

        events = [
            _make_event("A.SH", signal_value=0.8),
            _make_event("B.SH", signal_value=0.6),
            _make_event("C.SH", signal_value=0.5),
        ]
        strategy.load_events = MagicMock(return_value=events)

        decision = strategy.generate_signals(context)
        assert decision.is_rebalance is True
        assert len(decision.target_weights) == 3

    def test_mixed_events_only_positive_processed(self) -> None:
        """混合正负信号事件，只有正信号通过event_filter。"""
        context = _make_context(prev_holdings={})
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        events = [
            _make_event("GOOD.SH", signal_value=0.9),  # 通过
            _make_event("BAD.SH", signal_value=-0.7),  # 被过滤
        ]
        strategy.load_events = MagicMock(return_value=events)

        decision = strategy.generate_signals(context)
        assert "GOOD.SH" in decision.target_weights
        assert "BAD.SH" not in decision.target_weights

    def test_weights_sum_to_1_minus_cash_buffer(self) -> None:
        """事件触发后权重总和=1-cash_buffer(3%)。"""
        context = _make_context(prev_holdings={})
        config = _make_event_config(top_n=5)
        strategy = _SimpleEventStrategy(config=config, strategy_id="t")

        events = [
            _make_event("A.SH", signal_value=0.9),
            _make_event("B.SH", signal_value=0.8),
            _make_event("C.SH", signal_value=0.7),
        ]
        strategy.load_events = MagicMock(return_value=events)

        decision = strategy.generate_signals(context)
        total = sum(decision.target_weights.values())
        # cash_buffer默认0.03
        assert abs(total - 0.97) < 1e-6

    def test_signal_type_is_event(self) -> None:
        """generate_signals返回的signal_type=EVENT。"""
        context = _make_context()
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        strategy.load_events = MagicMock(return_value=[])

        decision = strategy.generate_signals(context)
        assert decision.signal_type == SignalType.EVENT


# ============================================================
# 6. aggregate_events验证
# ============================================================


class TestAggregateEvents:
    """aggregate_events同一股票多事件聚合验证。"""

    def test_same_code_keeps_highest_abs_signal(self) -> None:
        """同一股票两个事件取绝对值最大的保留。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        events = [
            _make_event("A.SH", signal_value=0.9),
            _make_event("A.SH", signal_value=0.3),  # 较小，应被丢弃
        ]
        aggregated = strategy.aggregate_events(events)
        assert len(aggregated) == 1
        assert aggregated[0].signal_value == 0.9

    def test_different_codes_all_kept(self) -> None:
        """不同股票的事件都保留。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        events = [
            _make_event("A.SH", signal_value=0.5),
            _make_event("B.SH", signal_value=0.7),
            _make_event("C.SH", signal_value=0.3),
        ]
        aggregated = strategy.aggregate_events(events)
        assert len(aggregated) == 3

    def test_negative_larger_abs_wins(self) -> None:
        """负信号绝对值更大时，保留负信号。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        events = [
            _make_event("A.SH", signal_value=0.3),
            _make_event("A.SH", signal_value=-0.9),  # 绝对值更大
        ]
        aggregated = strategy.aggregate_events(events)
        assert len(aggregated) == 1
        assert aggregated[0].signal_value == -0.9

    def test_empty_events_returns_empty(self) -> None:
        """空事件列表聚合后仍为空。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        assert strategy.aggregate_events([]) == []


# ============================================================
# 7. top_n约束
# ============================================================


class TestEventStrategyTopN:
    """_apply_top_n_constraint验证。"""

    def test_within_top_n_all_kept(self) -> None:
        """持仓数≤top_n时全部保留。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(top_n=10), strategy_id="t")
        weights = {f"code{i}.SH": 0.1 for i in range(5)}
        result = strategy._apply_top_n_constraint(weights)
        assert len(result) == 5

    def test_exceeds_top_n_trimmed(self) -> None:
        """持仓数>top_n时按权重排序截断到top_n。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(top_n=3), strategy_id="t")
        weights = {f"code{i}.SH": float(i) * 0.1 for i in range(1, 7)}
        result = strategy._apply_top_n_constraint(weights)
        assert len(result) == 3

    def test_top_n_keeps_highest_weights(self) -> None:
        """截断时保留权重最大的top_n只。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(top_n=2), strategy_id="t")
        weights = {"high.SH": 0.5, "mid.SH": 0.3, "low.SH": 0.1}
        result = strategy._apply_top_n_constraint(weights)
        assert "high.SH" in result
        assert "mid.SH" in result
        assert "low.SH" not in result

    def test_zero_and_negative_weights_excluded(self) -> None:
        """零和负权重不参与top_n计数。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(top_n=5), strategy_id="t")
        weights = {"A.SH": 0.5, "B.SH": 0.0, "C.SH": -0.1, "D.SH": 0.3}
        result = strategy._apply_top_n_constraint(weights)
        assert "B.SH" not in result
        assert "C.SH" not in result
        assert "A.SH" in result
        assert "D.SH" in result


# ============================================================
# 8. config验证
# ============================================================


class TestEventStrategyConfig:
    """EventStrategy config验证。"""

    def test_missing_top_n_raises(self) -> None:
        """config缺少top_n应抛ValueError。"""
        config = _make_event_config()
        del config["top_n"]
        with pytest.raises(ValueError, match="top_n"):
            _SimpleEventStrategy(config=config, strategy_id="bad")

    def test_factor_names_optional(self) -> None:
        """factor_names可以不提供（事件型不强制需要因子）。"""
        config = _make_event_config()
        config.pop("factor_names", None)
        # 不应抛错，_validate_config会补默认[]
        strategy = _SimpleEventStrategy(config=config, strategy_id="ok")
        assert strategy.config["factor_names"] == []

    def test_invalid_max_position_size_raises(self) -> None:
        """max_position_size超界应抛ValueError。"""
        config = _make_event_config(max_position_size=0.60)
        with pytest.raises(ValueError, match="max_position_size"):
            _SimpleEventStrategy(config=config, strategy_id="bad")

    def test_invalid_max_position_size_too_small(self) -> None:
        """max_position_size过小应抛ValueError。"""
        config = _make_event_config(max_position_size=0.005)
        with pytest.raises(ValueError, match="max_position_size"):
            _SimpleEventStrategy(config=config, strategy_id="bad")

    def test_valid_boundary_max_position_size(self) -> None:
        """max_position_size=0.50（上界）合法。"""
        config = _make_event_config(max_position_size=0.50)
        strategy = _SimpleEventStrategy(config=config, strategy_id="ok")
        assert strategy is not None

    def test_custom_cash_buffer(self) -> None:
        """自定义cash_buffer在事件触发时生效。"""
        config = _make_event_config(cash_buffer=0.05)
        strategy = _SimpleEventStrategy(config=config, strategy_id="t")
        context = _make_context()
        strategy.load_events = MagicMock(return_value=[_make_event("A.SH", signal_value=0.9)])

        decision = strategy.generate_signals(context)
        total = sum(decision.target_weights.values())
        assert abs(total - 0.95) < 1e-6


# ============================================================
# 9. load_events默认行为（DB mock）
# ============================================================


class TestLoadEvents:
    """load_events默认实现验证（DB mock）。"""

    def test_no_conn_returns_empty(self) -> None:
        """conn=None时load_events返回空列表。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")
        context = _make_context()
        result = strategy.load_events(context)
        assert result == []

    def test_db_returns_events(self) -> None:
        """DB返回数据时正确构建TradingEvent列表。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("600519.SH", "rsrs_breakout", 0.8, date(2024, 1, 31), {}),
            ("000001.SZ", "pead", 0.5, date(2024, 1, 31), {"eps_surprise": 0.15}),
        ]
        mock_conn.cursor.return_value = mock_cur

        context = _make_context()
        context.conn = mock_conn

        events = strategy.load_events(context)
        assert len(events) == 2
        assert events[0].code == "600519.SH"
        assert events[0].event_type == EventType.RSRS_BREAKOUT
        assert events[1].event_type == EventType.PEAD

    def test_db_unknown_event_type_uses_custom(self) -> None:
        """DB返回未知event_type时使用CUSTOM类型。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("A.SH", "unknown_future_type", 0.5, date(2024, 1, 31), {}),
        ]
        mock_conn.cursor.return_value = mock_cur

        context = _make_context()
        context.conn = mock_conn

        events = strategy.load_events(context)
        assert len(events) == 1
        assert events[0].event_type == EventType.CUSTOM
        assert events[0].meta.get("original_type") == "unknown_future_type"

    def test_db_failure_returns_empty(self) -> None:
        """DB查询失败时返回空列表（不抛错）。"""
        strategy = _SimpleEventStrategy(config=_make_event_config(), strategy_id="t")

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("DB连接断开")

        context = _make_context()
        context.conn = mock_conn

        events = strategy.load_events(context)
        assert events == []
