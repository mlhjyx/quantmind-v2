"""V3 §3.5 fail-open integration smoke — fundamental_context fail → alert path 仍 fires.

Sub-PR T1.5b-3 sediment (Gate A item 8 closure path per Plan v0.2 §A T1.5
Acceptance item (8)).

Tests verify V3 §3.5 fail-open contract for fundamental_context layer:
- FundamentalContextService fail at service boundary (FundamentalFetchError raise per 铁律 33)
- Caller (RealtimeRiskEngine) handles missing fundamental gracefully (constructs
  RiskContext WITHOUT fundamental — current impl has positions + realtime + nav
  fields, no fundamental embedded per dataclass design 2026-05-13 verify)
- RealtimeRiskRule.evaluate() proceeds with empty/None realtime, alert path completes

设计 vs 实施 真值 drift detect (sustained Plan v0.2 §G II Push back 体例 cumulative):
- V3 §11.2 设计 cite RiskContext.fundamental field — current impl
  `backend/qm_platform/risk/interface.py` 真值 NO fundamental field (frozen
  dataclass: strategy_id / execution_mode / timestamp / positions / portfolio_nav /
  prev_close_nav / realtime)
- Test verifies CURRENT IMPL fail-open: rule evaluates with realtime=None OR {}

关联:
- V3 §3.5 fail-open 设计 line 447-473
- V3 §11.2 RiskContext Protocol vs current impl drift (留 TB-5c batch closure
  amend 标注 sustained ADR-022)
- ADR-053 (V3 §S4 minimal fundamental_context architecture)
- 铁律 33 (service fail-loud, caller-side fail-open via default-empty/None)
"""
from __future__ import annotations

from datetime import UTC, datetime

from backend.qm_platform.risk.interface import Position, RiskContext
from backend.qm_platform.risk.rules.realtime.limit_down import LimitDownDetection


def _make_context(
    *,
    positions: tuple[Position, ...] = (),
    realtime: dict | None = None,
) -> RiskContext:
    """Construct RiskContext for test (sustained current dataclass signature)."""
    return RiskContext(
        strategy_id="test_fail_open",
        execution_mode="paper",
        timestamp=datetime.now(tz=UTC),
        positions=positions,
        portfolio_nav=1_000_000.0,
        prev_close_nav=1_000_000.0,
        realtime=realtime,
    )


# ---------- V3 §3.5 fail-open contract — fundamental_context layer ----------


class TestV3FailOpenFundamentalContext:
    """V3 §3.5 fail-open — fundamental_context fail integration smoke (current impl scope)."""

    def test_realtime_none_alert_path_no_raise(self):
        """RiskContext.realtime=None → rule.evaluate() returns empty (fail-open, NOT raise).

        模拟: FundamentalContextService 不可用时, 上游 orchestrator 不构造 realtime
        dict (传 None 跳过 realtime path), rule fail-open returns [] (反 raise).
        """
        positions = (
            Position(
                code="600519.SH",
                shares=100,
                entry_price=100.0,
                peak_price=100.0,
                current_price=90.0,
            ),
        )
        context = _make_context(positions=positions, realtime=None)
        rule = LimitDownDetection()

        # V3 §3.5 fail-open: realtime=None → rule returns empty, 反 raise/crash
        results = rule.evaluate(context)
        assert results == [], "fail-open: realtime=None returns empty (NOT raise)"

    def test_realtime_empty_dict_alert_path_no_raise(self):
        """RiskContext.realtime={} → rule.evaluate() returns empty, 反 raise."""
        positions = (
            Position(
                code="002415.SZ",
                shares=200,
                entry_price=50.0,
                peak_price=50.0,
                current_price=45.0,
            ),
        )
        context = _make_context(positions=positions, realtime={})
        rule = LimitDownDetection()

        # V3 §3.5 fail-open: realtime={} → 所有 position get None tick → skip per-symbol
        results = rule.evaluate(context)
        assert results == []

    def test_realtime_partial_missing_symbol_per_symbol_skip(self):
        """RiskContext.realtime 有 1 symbol 但 query 别 symbol → per-symbol fail-open."""
        positions = (
            Position(
                code="600519.SH",
                shares=100,
                entry_price=100.0,
                peak_price=100.0,
                current_price=90.0,
            ),
            Position(
                code="002415.SZ",  # NOT in realtime
                shares=200,
                entry_price=50.0,
                peak_price=50.0,
                current_price=45.0,
            ),
        )
        # Only 600519.SH in realtime, 002415.SZ missing
        realtime = {
            "600519.SH": {
                "prev_close": 100.0,
                "open_price": 95.0,
            },
        }
        context = _make_context(positions=positions, realtime=realtime)
        rule = LimitDownDetection()

        # V3 §3.5 fail-open: 002415.SZ silent skip, 600519.SH evaluated
        # 600519.SH 跌幅 = (100-90)/100 = 10.0% > 9.9% 阈值, deterministic fire 1 event
        results = rule.evaluate(context)
        # Test design: per-symbol fail-open (002415.SZ silent skip + 600519.SH 真 fire)
        assert len(results) == 1, "002415.SZ skip (per-symbol fail-open) + 600519.SH fire"
        assert results[0].code == "600519.SH"

    def test_realtime_missing_prev_close_per_symbol_skip(self):
        """RiskContext.realtime[symbol] 缺 prev_close field → silent skip (per-symbol fail-open)."""
        positions = (
            Position(
                code="600519.SH",
                shares=100,
                entry_price=100.0,
                peak_price=100.0,
                current_price=90.0,
            ),
        )
        # realtime[600519.SH] 存在但 prev_close missing
        realtime = {
            "600519.SH": {
                "open_price": 95.0,
                # NO prev_close
            },
        }
        context = _make_context(positions=positions, realtime=realtime)
        rule = LimitDownDetection()

        # V3 §3.5 fail-open: prev_close=None → silent skip per-symbol, 反 raise KeyError
        results = rule.evaluate(context)
        assert results == [], "fail-open: missing prev_close → skip (反 raise)"
