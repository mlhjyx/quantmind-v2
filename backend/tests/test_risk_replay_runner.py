"""V3 Tier B ReplayRunner + counterfactual tests — TB-1b sediment.

Plan v0.2 §A TB-1 row chunked 3 sub-PR (TB-1a + TB-1b + TB-1c) sub-PR TB-1b.

Tests cover:
- ReplayWindow definitions (2 关键窗口 per ADR-064 D3=b)
- summarize_events (empty / single / multi-rule / multi-code)
- EventSummary.to_markdown
- ReplayRunner.build_context (Position + market_data → RiskContext)
- ReplayRunner.run_window (pre-loaded bars / loader injection / 0 bars edge)
- 铁律 41 timezone normalization (Asia/Shanghai)
- pure-function contract audit (sustained TB-1a contract via run_window post-check)

关联:
- V3 §11.4 (RiskBacktestAdapter pure function)
- V3 §15.5 (历史回放 sim-to-real gap)
- ADR-064 D3=b (2 关键窗口 sustained)
- ADR-066 候选 (TB-1 closure)
- LL-159 (4-step preflight SOP)
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.qm_platform.risk.backtest_adapter import RiskBacktestAdapter
from backend.qm_platform.risk.interface import RuleResult
from backend.qm_platform.risk.realtime.engine import RealtimeRiskEngine
from backend.qm_platform.risk.replay import (
    ReplayRunner,
    summarize_events,
)
from backend.qm_platform.risk.replay.runner import (
    ALL_WINDOWS,
    SHANGHAI_TZ,
    WINDOW_2024Q1_QUANT_CRASH,
    WINDOW_2025_04_07_TARIFF_SHOCK,
)


class _StubRule:
    """Stub RiskRule for ReplayRunner tests."""

    def __init__(self, rule_id: str, *, results: list[RuleResult] | None = None):
        self.rule_id = rule_id
        self._results = results or []
        self.evaluate_count = 0

    def evaluate(self, context):
        self.evaluate_count += 1
        return list(self._results)


# ---------- Window definitions (per ADR-064 D3=b) ----------


class TestReplayWindowDefinitions:
    """2 关键窗口 per ADR-064 D3=b 2 关键窗口 lock."""

    def test_window_2024q1_quant_crash(self):
        w = WINDOW_2024Q1_QUANT_CRASH
        assert w.name == "2024Q1_quant_crash"
        assert w.start_date == date(2024, 1, 2)
        assert w.end_date == date(2024, 2, 9)
        assert "雪球" in w.description or "量化" in w.description

    def test_window_2025_04_07_tariff_shock(self):
        w = WINDOW_2025_04_07_TARIFF_SHOCK
        assert w.name == "2025_04_07_tariff_shock"
        assert w.start_date == date(2025, 4, 1)
        assert w.end_date == date(2025, 4, 11)
        assert "关税" in w.description

    def test_all_windows_tuple_has_2_entries_per_d3b_lock(self):
        """D3=b 决议 lock: 2 关键窗口 (NOT 5y full)."""
        assert len(ALL_WINDOWS) == 2
        assert WINDOW_2024Q1_QUANT_CRASH in ALL_WINDOWS
        assert WINDOW_2025_04_07_TARIFF_SHOCK in ALL_WINDOWS


# ---------- summarize_events ----------


class TestSummarizeEvents:
    """counterfactual.summarize_events aggregate logic."""

    def test_empty_events(self):
        s = summarize_events([])
        assert s.total_events == 0
        assert s.by_rule_id == {}
        assert s.by_code == {}
        assert s.unique_codes == 0
        assert s.unique_rule_ids == 0

    def test_single_event(self):
        ev = RuleResult(rule_id="r1", code="600519.SH", shares=100, reason="x", metrics={})
        s = summarize_events([ev])
        assert s.total_events == 1
        assert s.by_rule_id == {"r1": 1}
        assert s.by_code == {"600519.SH": 1}
        assert s.unique_codes == 1
        assert s.unique_rule_ids == 1

    def test_multi_rule_multi_code(self):
        events = [
            RuleResult(rule_id="r1", code="A", shares=0, reason="", metrics={}),
            RuleResult(rule_id="r1", code="B", shares=0, reason="", metrics={}),
            RuleResult(rule_id="r2", code="A", shares=0, reason="", metrics={}),
            RuleResult(rule_id="r1", code="A", shares=0, reason="", metrics={}),
        ]
        s = summarize_events(events)
        assert s.total_events == 4
        assert s.by_rule_id == {"r1": 3, "r2": 1}
        assert s.by_code == {"A": 3, "B": 1}
        assert s.unique_codes == 2
        assert s.unique_rule_ids == 2

    def test_top_codes_limit(self):
        # 30 codes, each appearing once
        events = [
            RuleResult(rule_id="r1", code=f"code_{i}", shares=0, reason="", metrics={})
            for i in range(30)
        ]
        s = summarize_events(events, top_codes_limit=10)
        # by_code should only have top 10 (since all tied at 1, order is insertion / Counter most_common)
        assert len(s.by_code) == 10
        assert s.unique_codes == 30  # all 30 unique codes counted

    def test_summary_window_metadata_preserved(self):
        start = datetime(2024, 1, 2, tzinfo=UTC)
        end = datetime(2024, 2, 9, tzinfo=UTC)
        s = summarize_events([], window_start=start, window_end=end)
        assert s.window_start == start
        assert s.window_end == end


class TestEventSummaryMarkdown:
    """EventSummary.to_markdown formatting."""

    def test_markdown_includes_window_metadata(self):
        events = [
            RuleResult(rule_id="limit_down", code="600519.SH", shares=0, reason="", metrics={}),
        ]
        s = summarize_events(
            events,
            window_start=datetime(2024, 2, 5, tzinfo=UTC),
            window_end=datetime(2024, 2, 5, tzinfo=UTC),
        )
        md = s.to_markdown()
        assert "Replay Window Event Summary" in md
        assert "Total events: 1" in md
        assert "`limit_down`" in md
        assert "`600519.SH`" in md
        assert "Unique codes: 1" in md

    def test_markdown_empty_events(self):
        s = summarize_events([])
        md = s.to_markdown()
        assert "Total events: 0" in md
        assert "Unique codes: 0" in md


# ---------- ReplayRunner core ----------


class TestReplayRunner:
    """ReplayRunner orchestration tests."""

    def _make_adapter_engine(self):
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        return adapter, engine

    def _make_bar(
        self,
        code: str = "600519.SH",
        trade_time: datetime | None = None,
        close: float = 100.0,
        prev_close: float = 100.0,
    ) -> dict:
        return {
            "code": code,
            "trade_time": trade_time or datetime(2024, 2, 5, 9, 35),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "prev_close": prev_close,
            "volume": 10000,
            "amount": close * 10000,
        }

    def test_build_context_populates_realtime(self):
        adapter, engine = self._make_adapter_engine()
        runner = ReplayRunner(adapter, engine)
        bar = self._make_bar(code="600519.SH", close=90.0, prev_close=100.0)
        ts = datetime(2024, 2, 5, 9, 35, tzinfo=SHANGHAI_TZ)
        ctx = runner.build_context(ts, (), bar)
        assert ctx.strategy_id == "tb_1b_replay"
        assert ctx.execution_mode == "paper"
        assert ctx.timestamp == ts
        assert ctx.realtime is not None
        assert "600519.SH" in ctx.realtime
        rt = ctx.realtime["600519.SH"]
        assert rt["current_price"] == 90.0
        assert rt["prev_close"] == 100.0

    def test_run_window_with_pre_loaded_bars(self):
        adapter, engine = self._make_adapter_engine()
        # Register stub tick rule that always returns 1 event per evaluate
        rule = _StubRule(
            "stub_rule",
            results=[RuleResult(rule_id="stub_rule", code="600519.SH", shares=0, reason="x", metrics={})],
        )
        engine.register(rule, cadence="tick")

        bars = [
            self._make_bar(trade_time=datetime(2024, 2, 5, 9, 30)),
            self._make_bar(trade_time=datetime(2024, 2, 5, 9, 31)),
            self._make_bar(trade_time=datetime(2024, 2, 5, 9, 32)),
        ]
        runner = ReplayRunner(adapter, engine)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH, bars=bars)

        assert result.total_minute_bars == 3
        assert result.total_timestamps == 3
        assert len(result.events) == 3  # 1 per ts (rule fires once each)
        assert result.pure_function_contract_verified is True
        assert result.summary is not None
        assert result.summary.total_events == 3

    def test_run_window_dedup_across_replay(self):
        """Same (timestamp, code, rule_id) deduped even if bar appears twice."""
        adapter, engine = self._make_adapter_engine()
        rule = _StubRule(
            "dedup_rule",
            results=[RuleResult(rule_id="dedup_rule", code="600519.SH", shares=0, reason="", metrics={})],
        )
        engine.register(rule, cadence="tick")

        # Two bars at SAME timestamp + SAME code (dedup contract verify)
        ts = datetime(2024, 2, 5, 9, 30)
        bars = [
            self._make_bar(code="600519.SH", trade_time=ts),
            self._make_bar(code="600519.SH", trade_time=ts),
        ]
        runner = ReplayRunner(adapter, engine)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH, bars=bars)

        # 1 event (dedup), not 2
        assert len(result.events) == 1
        assert result.total_minute_bars == 2  # but 2 bars input
        assert result.total_timestamps == 1  # 1 unique ts

    def test_run_window_no_loader_no_bars_raises(self):
        """No loader injected + no bars passed → fail-loud per 铁律 33."""
        adapter, engine = self._make_adapter_engine()
        runner = ReplayRunner(adapter, engine, minute_bars_loader=None)
        with pytest.raises(ValueError, match="minute_bars_loader"):
            runner.run_window(WINDOW_2024Q1_QUANT_CRASH)

    def test_run_window_empty_bars_no_events(self):
        adapter, engine = self._make_adapter_engine()
        runner = ReplayRunner(adapter, engine)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH, bars=[])
        assert result.total_minute_bars == 0
        assert result.total_timestamps == 0
        assert result.events == []
        assert result.summary.total_events == 0
        assert result.pure_function_contract_verified is True

    def test_run_window_naive_timestamp_normalized_to_shanghai(self):
        """Naive bar timestamps are tz-normalized to Asia/Shanghai per 铁律 41."""
        adapter, engine = self._make_adapter_engine()
        rule = _StubRule(
            "tz_rule",
            results=[RuleResult(rule_id="tz_rule", code="600519.SH", shares=0, reason="", metrics={})],
        )
        engine.register(rule, cadence="tick")

        # Naive timestamp (no tzinfo) — runner._normalize_ts should attach Asia/Shanghai
        naive_ts = datetime(2024, 2, 5, 9, 30)
        bars = [self._make_bar(trade_time=naive_ts)]
        runner = ReplayRunner(adapter, engine)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH, bars=bars)
        # Should NOT raise (evaluate_at would raise on naive, so normalization must occur)
        assert len(result.events) == 1

    def test_run_window_pure_function_contract_verified(self):
        """Replay run should result in 0 broker/alert via adapter contract."""
        adapter, engine = self._make_adapter_engine()
        rule = _StubRule(
            "pure_rule",
            results=[RuleResult(rule_id="pure_rule", code="A", shares=0, reason="", metrics={})],
        )
        engine.register(rule, cadence="tick")
        bars = [self._make_bar(trade_time=datetime(2024, 2, 5, 9, 30))]
        runner = ReplayRunner(adapter, engine)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH, bars=bars)
        assert result.pure_function_contract_verified is True
        # No sell or alert called during replay
        assert len(adapter.sell_calls) == 0
        assert len(adapter.alerts) == 0

    def test_run_window_loader_injection(self):
        """minute_bars_loader callable injection."""
        adapter, engine = self._make_adapter_engine()
        # rule that fires once per bar
        rule = _StubRule(
            "loader_rule",
            results=[RuleResult(rule_id="loader_rule", code="LOADER.SH", shares=0, reason="", metrics={})],
        )
        engine.register(rule, cadence="tick")

        def fake_loader(start, end):
            return [
                self._make_bar(code="LOADER.SH", trade_time=datetime(2024, 1, 5, 10, 0))
            ]

        runner = ReplayRunner(adapter, engine, minute_bars_loader=fake_loader)
        result = runner.run_window(WINDOW_2024Q1_QUANT_CRASH)
        assert result.total_minute_bars == 1
        assert len(result.events) == 1


# ---------- Timezone normalization ----------


class TestTimezoneNormalization:
    """铁律 41 enforcement via _normalize_ts."""

    def test_naive_timestamp_attached_to_shanghai_tz(self):
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        runner = ReplayRunner(adapter, engine)
        naive = datetime(2024, 2, 5, 9, 35)
        normalized = runner._normalize_ts(naive)
        assert normalized.tzinfo is not None
        assert normalized.tzinfo == SHANGHAI_TZ

    def test_utc_timestamp_converted_to_shanghai(self):
        adapter = RiskBacktestAdapter()
        engine = RealtimeRiskEngine()
        runner = ReplayRunner(adapter, engine)
        utc_ts = datetime(2024, 2, 5, 9, 35, tzinfo=UTC)
        normalized = runner._normalize_ts(utc_ts)
        assert normalized.tzinfo == SHANGHAI_TZ
        # 9:35 UTC = 17:35 Asia/Shanghai
        assert normalized.hour == 17 and normalized.minute == 35
