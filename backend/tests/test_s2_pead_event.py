"""MVP 3.2 批 3 — S2PEADEvent unit tests.

覆盖 generate_signals 的 5 场景 + validate_signals + _find_expired_positions + config 覆盖.
纯 metadata-injection 测试 (不触 DB, 铁律 31 S2 纯计算原则).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.engines.strategies.s2_pead_event import S2PEADConfig, S2PEADEvent
from backend.platform.strategy.interface import (
    RebalanceFreq,
    StrategyContext,
    StrategyStatus,
)

# ─── Test helpers ─────────────────────────────────────────────────────

def _mk_ctx(
    trade_date: date = date(2026, 4, 28),
    universe: list[str] | None = None,
    pead_candidates: list[dict] | None = None,
    current_positions: dict[str, dict] | None = None,
) -> StrategyContext:
    return StrategyContext(
        trade_date=trade_date,
        capital=Decimal("500000"),
        universe=universe or [],
        regime="neutral",
        metadata={
            "pead_candidates": pead_candidates or [],
            "current_positions": current_positions or {},
        },
    )


# ─── Class attrs tests ────────────────────────────────────────────────

def test_s2_class_attrs():
    assert S2PEADEvent.name == "s2_pead_event"
    assert S2PEADEvent.rebalance_freq == RebalanceFreq.EVENT
    assert S2PEADEvent.status == StrategyStatus.DRY_RUN  # Safety: not LIVE by default
    assert S2PEADEvent.factor_pool == []  # 绕开 DEPRECATED pead_q1
    # Stable UUID (deterministic for DB seed / per-session reproduce)
    from uuid import UUID
    UUID(S2PEADEvent.strategy_id)  # raises if invalid


# ─── generate_signals: empty cases ────────────────────────────────────

def test_empty_candidates_no_positions_returns_empty():
    s2 = S2PEADEvent()
    ctx = _mk_ctx()
    assert s2.generate_signals(ctx) == []


def test_missing_pead_candidates_key_raises():
    s2 = S2PEADEvent()
    ctx = StrategyContext(
        trade_date=date(2026, 4, 28),
        capital=Decimal("500000"),
        universe=[],
        regime="neutral",
        metadata={"current_positions": {}},  # 缺 pead_candidates
    )
    with pytest.raises(KeyError, match="pead_candidates"):
        s2.generate_signals(ctx)


def test_missing_current_positions_key_raises():
    s2 = S2PEADEvent()
    ctx = StrategyContext(
        trade_date=date(2026, 4, 28),
        capital=Decimal("500000"),
        universe=[],
        regime="neutral",
        metadata={"pead_candidates": []},  # 缺 current_positions
    )
    with pytest.raises(KeyError, match="current_positions"):
        s2.generate_signals(ctx)


# ─── generate_signals: buy-only cases ─────────────────────────────────

def test_single_candidate_above_threshold_generates_buy():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(
        universe=["600519.SH"],
        pead_candidates=[
            {"code": "600519.SH", "eps_surprise_pct": 0.5, "trigger_date": date(2026, 4, 28)},
        ],
    )
    signals = s2.generate_signals(ctx)
    assert len(signals) == 1
    assert signals[0].code == "600519.SH"
    assert signals[0].target_weight == 1 / 20  # 1 / MAX_CONCURRENT_POSITIONS
    assert signals[0].metadata["action"] == "buy_pead"
    assert signals[0].score == 0.5


def test_candidate_below_threshold_skipped():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(
        universe=["600519.SH"],
        pead_candidates=[
            {"code": "600519.SH", "eps_surprise_pct": 0.15, "trigger_date": date(2026, 4, 28)},
        ],
    )
    # Default threshold 0.30, 0.15 过低
    assert s2.generate_signals(ctx) == []


def test_candidate_not_in_universe_skipped():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(
        universe=["000001.SZ"],  # 不含 600519
        pead_candidates=[
            {"code": "600519.SH", "eps_surprise_pct": 0.5, "trigger_date": date(2026, 4, 28)},
        ],
    )
    assert s2.generate_signals(ctx) == []


def test_eps_surprise_cap_clips_outlier():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(
        universe=["600519.SH"],
        pead_candidates=[
            {"code": "600519.SH", "eps_surprise_pct": 458.0, "trigger_date": date(2026, 4, 28)},
        ],
    )
    signals = s2.generate_signals(ctx)
    assert len(signals) == 1
    # Raw 458 clipped to default cap 3.0
    assert signals[0].metadata["eps_surprise_pct_raw"] == 458.0
    assert signals[0].metadata["eps_surprise_pct_clipped"] == 3.0
    assert signals[0].score == 3.0


def test_top_n_per_day_limits_candidates():
    s2 = S2PEADEvent()
    candidates = [
        {"code": f"60000{i}.SH", "eps_surprise_pct": 0.5 + i * 0.1, "trigger_date": date(2026, 4, 28)}
        for i in range(10)  # 10 candidates all above threshold
    ]
    ctx = _mk_ctx(
        universe=[c["code"] for c in candidates],
        pead_candidates=candidates,
    )
    signals = s2.generate_signals(ctx)
    # Default top_n_per_trigger_day=5
    assert len(signals) == 5
    # Top 5 by eps_surprise_pct desc (1.4, 1.3, 1.2, 1.1, 1.0 clipped to 3.0 — but these all < 3.0 cap)
    scores = [s.score for s in signals]
    assert scores == sorted(scores, reverse=True)  # sorted desc
    # Verify top score == 1.4 (i=9) but clipped to 3.0 cap? No, 1.4 < 3.0 so no clip
    assert signals[0].score == pytest.approx(1.4, abs=1e-9)


def test_ties_sorted_deterministic():
    s2 = S2PEADEvent()
    # 3 candidates same surprise pct
    candidates = [
        {"code": "600001.SH", "eps_surprise_pct": 0.5},
        {"code": "600002.SH", "eps_surprise_pct": 0.5},
        {"code": "600003.SH", "eps_surprise_pct": 0.5},
    ]
    ctx = _mk_ctx(
        universe=[c["code"] for c in candidates],
        pead_candidates=candidates,
    )
    signals = s2.generate_signals(ctx)
    assert len(signals) == 3
    # All same score (stable sort preserves input order)
    assert all(s.score == 0.5 for s in signals)


# ─── generate_signals: sell-only cases ────────────────────────────────

def test_expired_position_generates_sell():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(
        current_positions={
            "600519.SH": {"holding_days": 30, "weight": 0.05},  # exactly 30, expired
        },
    )
    signals = s2.generate_signals(ctx)
    assert len(signals) == 1
    assert signals[0].code == "600519.SH"
    assert signals[0].target_weight == 0.0  # sell
    assert signals[0].metadata["action"] == "sell_expired"
    assert signals[0].metadata["holding_days"] == 30


def test_position_under_holding_days_not_sold():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(
        current_positions={
            "600519.SH": {"holding_days": 29, "weight": 0.05},  # 1 day short
        },
    )
    assert s2.generate_signals(ctx) == []


# ─── generate_signals: concurrent limit + mixed cases ─────────────────

def test_max_concurrent_positions_blocks_new_buys():
    s2 = S2PEADEvent()
    # 20 positions all active (max_concurrent=20), no expiries, new candidates all rejected
    current_positions = {
        f"60000{i}.SH": {"holding_days": 10, "weight": 0.05} for i in range(20)
    }
    candidates = [
        {"code": "600099.SH", "eps_surprise_pct": 0.5, "trigger_date": date(2026, 4, 28)},
    ]
    ctx = _mk_ctx(
        universe=["600099.SH"] + list(current_positions.keys()),
        pead_candidates=candidates,
        current_positions=current_positions,
    )
    signals = s2.generate_signals(ctx)
    # 0 sells (none expired) + 0 buys (slots full)
    assert signals == []


def test_expiry_frees_slot_for_new_buy():
    s2 = S2PEADEvent()
    # 20 positions, 5 expired → 15 active → 5 new slots free
    current_positions = {
        f"60000{i}.SH": {"holding_days": 30 if i < 5 else 10, "weight": 0.05}
        for i in range(20)
    }
    candidates = [
        {"code": f"60010{i}.SH", "eps_surprise_pct": 0.5 + i * 0.1}
        for i in range(10)  # 10 new candidates
    ]
    ctx = _mk_ctx(
        universe=[c["code"] for c in candidates] + list(current_positions.keys()),
        pead_candidates=candidates,
        current_positions=current_positions,
    )
    signals = s2.generate_signals(ctx)
    sells = [s for s in signals if s.target_weight == 0.0]
    buys = [s for s in signals if s.target_weight > 0.0]
    assert len(sells) == 5  # i<5 expired
    assert len(buys) == 5  # top_n_per_day capped at 5, 15 slots available


def test_already_held_candidate_skipped_avoid_duplicate_buy():
    s2 = S2PEADEvent()
    # Candidate is already held, should not generate new buy (avoid increasing weight)
    current_positions = {"600519.SH": {"holding_days": 5, "weight": 0.05}}
    candidates = [
        {"code": "600519.SH", "eps_surprise_pct": 0.5, "trigger_date": date(2026, 4, 28)},
    ]
    ctx = _mk_ctx(
        universe=["600519.SH"],
        pead_candidates=candidates,
        current_positions=current_positions,
    )
    signals = s2.generate_signals(ctx)
    # No sell (holding_days=5 < 30), no duplicate buy (already held)
    assert signals == []


# ─── Config override ──────────────────────────────────────────────────

def test_config_threshold_override():
    cfg = S2PEADConfig(eps_surprise_threshold=0.1)  # lower threshold
    s2 = S2PEADEvent(config=cfg)
    ctx = _mk_ctx(
        universe=["600519.SH"],
        pead_candidates=[
            {"code": "600519.SH", "eps_surprise_pct": 0.15, "trigger_date": date(2026, 4, 28)},
        ],
    )
    signals = s2.generate_signals(ctx)
    assert len(signals) == 1  # 0.15 > 0.1 threshold


def test_config_holding_days_override():
    cfg = S2PEADConfig(holding_days=7)  # shorter window for testing
    s2 = S2PEADEvent(config=cfg)
    ctx = _mk_ctx(
        current_positions={"600519.SH": {"holding_days": 7, "weight": 0.05}},
    )
    signals = s2.generate_signals(ctx)
    assert len(signals) == 1
    assert signals[0].target_weight == 0.0  # sell at day 7


def test_config_max_concurrent_override():
    cfg = S2PEADConfig(max_concurrent_positions=5)
    s2 = S2PEADEvent(config=cfg)
    # 5 positions, max=5, no slot for new
    current = {f"600{i:03d}.SH": {"holding_days": 10, "weight": 0.2} for i in range(5)}
    candidates = [{"code": "600500.SH", "eps_surprise_pct": 0.5}]
    ctx = _mk_ctx(
        universe=["600500.SH"] + list(current.keys()),
        pead_candidates=candidates,
        current_positions=current,
    )
    assert s2.generate_signals(ctx) == []


# ─── validate_signals ─────────────────────────────────────────────────

def test_validate_signals_passes_sell_regardless_of_universe():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(universe=[])  # empty universe (已退市不在今日 universe)
    from backend.platform._types import Signal
    sell = Signal(
        strategy_id=s2.strategy_id,
        code="600519.SH",
        target_weight=0.0,
        score=0.0,
        trade_date=date(2026, 4, 28),
        metadata={"action": "sell_expired"},
    )
    validated = s2.validate_signals([sell], ctx)
    assert validated == [sell]  # sell 通过 (已持仓必须能 sell)


def test_validate_signals_filters_buy_not_in_universe():
    s2 = S2PEADEvent()
    ctx = _mk_ctx(universe=["600519.SH"])  # only 600519 valid
    from backend.platform._types import Signal
    buy_valid = Signal(
        strategy_id=s2.strategy_id,
        code="600519.SH",
        target_weight=0.05,
        score=0.5,
        trade_date=date(2026, 4, 28),
        metadata={"action": "buy_pead"},
    )
    buy_invalid = Signal(
        strategy_id=s2.strategy_id,
        code="000001.SZ",
        target_weight=0.05,
        score=0.5,
        trade_date=date(2026, 4, 28),
        metadata={"action": "buy_pead"},
    )
    validated = s2.validate_signals([buy_valid, buy_invalid], ctx)
    assert validated == [buy_valid]


# ─── Fail-safe per candidate: non-numeric eps_surprise_pct ───────────

def test_non_numeric_eps_surprise_pct_skipped_per_candidate():
    """reviewer MEDIUM (PR #70) fix: 坏数据不 crash 整个 generate_signals."""
    s2 = S2PEADEvent()
    candidates = [
        {"code": "600001.SH", "eps_surprise_pct": "not-a-number"},  # 坏数据
        {"code": "600002.SH", "eps_surprise_pct": 0.5},  # 正常
    ]
    ctx = _mk_ctx(
        universe=["600001.SH", "600002.SH"],
        pead_candidates=candidates,
    )
    signals = s2.generate_signals(ctx)
    # 只有 1 个 signal (坏数据 silent skip + log warning, 好数据正常产出)
    assert len(signals) == 1
    assert signals[0].code == "600002.SH"


def test_candidate_dict_not_mutated_by_generate_signals():
    """reviewer MEDIUM (PR #70) fix: caller's dict 不被 side-effect 塞 key."""
    s2 = S2PEADEvent()
    candidates = [
        {"code": "600519.SH", "eps_surprise_pct": 458.0},
    ]
    # Snapshot 原 keys
    original_keys = set(candidates[0].keys())
    ctx = _mk_ctx(universe=["600519.SH"], pead_candidates=candidates)
    s2.generate_signals(ctx)
    # 原 dict 不应被塞 'eps_surprise_pct_clipped' 或其他 new key
    assert set(candidates[0].keys()) == original_keys


# ─── _find_expired_positions edge cases ───────────────────────────────

def test_find_expired_missing_holding_days_treats_as_zero():
    s2 = S2PEADEvent()
    positions = {"600519.SH": {"weight": 0.05}}  # 缺 holding_days
    expired = s2._find_expired_positions(positions)
    assert expired == []  # holding_days 默认 0, 未过期
