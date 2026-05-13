"""V3 §5.3 market_regime_log — TB-2a unit tests.

Coverage:
  - RegimeLabel Enum + str subclass behavior
  - RegimeArgument frozen + __post_init__ validation (empty arg / weight range)
  - MarketIndicators frozen + tz-aware enforce + breadth non-negative
  - MarketRegime frozen + confidence range + cost_usd non-negative + jsonable serialize
  - persist_market_regime SQL contract (smoke via real PG connection — sustained
    PR #320 schema-aware smoke test pattern, LL-157 SAVEPOINT-insert anti-pattern fix)

关联铁律: 31 (Engine PURE) / 33 (fail-loud) / 40 (test debt sustained) / 41 (timezone)
关联 V3: §5.3 / §11.2 / ADR-029/036/064/066
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import psycopg2
import pytest

from backend.qm_platform.risk.regime import (
    MarketIndicators,
    MarketRegime,
    RegimeArgument,
    RegimeLabel,
    persist_market_regime,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


# ---------- RegimeLabel ----------


def test_regime_label_str_values() -> None:
    """RegimeLabel.value matches DDL CHECK constraint values exactly."""
    assert RegimeLabel.BULL.value == "Bull"
    assert RegimeLabel.BEAR.value == "Bear"
    assert RegimeLabel.NEUTRAL.value == "Neutral"
    assert RegimeLabel.TRANSITIONING.value == "Transitioning"


def test_regime_label_is_str_subclass() -> None:
    """str subclass enables natural JSON / SQL serialization without .value."""
    assert isinstance(RegimeLabel.BULL, str)
    assert RegimeLabel.BULL == "Bull"


# ---------- RegimeArgument ----------


def test_regime_argument_valid() -> None:
    arg = RegimeArgument(
        argument="北向资金 5 日净流入 ¥120 亿创近月新高",
        evidence="Wind 2026-05-14 close",
        weight=0.75,
    )
    assert arg.argument == "北向资金 5 日净流入 ¥120 亿创近月新高"
    assert arg.weight == 0.75


def test_regime_argument_empty_raises() -> None:
    """铁律 33 fail-loud: 空 argument 反 silent degraded debate."""
    with pytest.raises(ValueError, match="non-empty"):
        RegimeArgument(argument="")
    with pytest.raises(ValueError, match="non-empty"):
        RegimeArgument(argument="   ")  # whitespace-only


def test_regime_argument_weight_out_of_range() -> None:
    """weight ∈ [0, 1] sustained (反 LLM 输出 1.5 / -0.3 silent drift)."""
    with pytest.raises(ValueError, match=r"weight must be in \[0, 1\]"):
        RegimeArgument(argument="test", weight=1.5)
    with pytest.raises(ValueError, match=r"weight must be in \[0, 1\]"):
        RegimeArgument(argument="test", weight=-0.1)


def test_regime_argument_weight_boundaries() -> None:
    """Inclusive boundaries [0.0, 1.0] both accepted."""
    RegimeArgument(argument="a", weight=0.0)
    RegimeArgument(argument="a", weight=1.0)


# ---------- MarketIndicators ----------


def test_market_indicators_minimal() -> None:
    """All optional numeric fields → only timestamp required."""
    ts = datetime(2026, 5, 14, 9, 0, 0, tzinfo=SHANGHAI_TZ)
    ind = MarketIndicators(timestamp=ts)
    assert ind.timestamp == ts
    assert ind.sse_return is None


def test_market_indicators_full() -> None:
    ts = datetime(2026, 5, 14, 14, 30, 0, tzinfo=SHANGHAI_TZ)
    ind = MarketIndicators(
        timestamp=ts,
        sse_return=-0.0315,
        hs300_return=-0.0287,
        breadth_up=420,
        breadth_down=4128,
        north_flow_cny=-87.5,
        iv_50etf=0.298,
    )
    assert ind.sse_return == -0.0315
    assert ind.breadth_down == 4128


def test_market_indicators_naive_ts_raises() -> None:
    """铁律 41 sustained: naive datetime fail-loud."""
    naive = datetime(2026, 5, 14, 9, 0, 0)
    with pytest.raises(ValueError, match="tz-aware"):
        MarketIndicators(timestamp=naive)


def test_market_indicators_negative_breadth_raises() -> None:
    ts = datetime(2026, 5, 14, 9, 0, 0, tzinfo=SHANGHAI_TZ)
    with pytest.raises(ValueError, match="breadth_up must be ≥ 0"):
        MarketIndicators(timestamp=ts, breadth_up=-1)
    with pytest.raises(ValueError, match="breadth_down must be ≥ 0"):
        MarketIndicators(timestamp=ts, breadth_down=-5)


def test_market_indicators_to_jsonable() -> None:
    """Serialization preserves None as null + uses ISO timestamp."""
    ts = datetime(2026, 5, 14, 14, 30, 0, tzinfo=SHANGHAI_TZ)
    ind = MarketIndicators(
        timestamp=ts,
        sse_return=-0.03,
        breadth_down=4128,
    )
    j = ind.to_jsonable()
    assert j["timestamp"] == ts.isoformat()
    assert j["sse_return"] == -0.03
    assert j["hs300_return"] is None
    assert j["breadth_down"] == 4128
    # Round-trip through json.dumps must succeed (no exotic types).
    json.dumps(j)


# ---------- MarketRegime ----------


def _make_regime(
    *,
    regime: RegimeLabel = RegimeLabel.NEUTRAL,
    confidence: float = 0.6,
    cost_usd: float = 0.013,
    indicators: MarketIndicators | None = None,
) -> MarketRegime:
    ts = datetime(2026, 5, 14, 9, 0, 0, tzinfo=SHANGHAI_TZ)
    if indicators is None:
        indicators = MarketIndicators(timestamp=ts, sse_return=-0.02)
    return MarketRegime(
        timestamp=ts,
        regime=regime,
        confidence=confidence,
        bull_arguments=(
            RegimeArgument(argument="bull-1", weight=0.3),
            RegimeArgument(argument="bull-2", weight=0.3),
            RegimeArgument(argument="bull-3", weight=0.4),
        ),
        bear_arguments=(
            RegimeArgument(argument="bear-1", weight=0.5),
            RegimeArgument(argument="bear-2", weight=0.3),
            RegimeArgument(argument="bear-3", weight=0.2),
        ),
        judge_reasoning="Bull arguments outweighed by Bear due to ...",
        indicators=indicators,
        cost_usd=cost_usd,
    )


def test_market_regime_valid() -> None:
    r = _make_regime(regime=RegimeLabel.BEAR, confidence=0.78)
    assert r.regime == RegimeLabel.BEAR
    assert r.confidence == 0.78
    assert len(r.bull_arguments) == 3
    assert len(r.bear_arguments) == 3


def test_market_regime_naive_ts_raises() -> None:
    naive = datetime(2026, 5, 14, 9, 0, 0)
    ind = MarketIndicators(timestamp=datetime(2026, 5, 14, 9, 0, 0, tzinfo=SHANGHAI_TZ))
    with pytest.raises(ValueError, match="tz-aware"):
        MarketRegime(
            timestamp=naive,
            regime=RegimeLabel.BULL,
            confidence=0.5,
            indicators=ind,
        )


def test_market_regime_confidence_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match=r"confidence must be in \[0, 1\]"):
        _make_regime(confidence=1.5)
    with pytest.raises(ValueError, match=r"confidence must be in \[0, 1\]"):
        _make_regime(confidence=-0.01)


def test_market_regime_negative_cost_raises() -> None:
    """LiteLLM router 反向报负成本 = audit drift fail-loud (铁律 33)."""
    with pytest.raises(ValueError, match="cost_usd must be ≥ 0"):
        _make_regime(cost_usd=-0.001)


def test_market_regime_arguments_jsonable() -> None:
    r = _make_regime()
    bull_j = r.bull_arguments_jsonable()
    bear_j = r.bear_arguments_jsonable()
    assert len(bull_j) == 3
    assert bull_j[0]["argument"] == "bull-1"
    assert bull_j[0]["weight"] == 0.3
    assert "evidence" in bull_j[0]
    assert len(bear_j) == 3
    # Round-trip JSON-safe.
    json.dumps(bull_j)
    json.dumps(bear_j)


# ---------- repository.persist_market_regime (real PG smoke) ----------


def _connect_test_db() -> psycopg2.extensions.connection | None:
    """Try real PG connect; skip if unavailable (sustained mock-conn anti-pattern reject)."""
    try:
        from app.services.db import _get_dsn  # noqa: PLC0415
    except Exception:
        return None
    try:
        dsn = _get_dsn()
        return psycopg2.connect(dsn)
    except Exception:
        return None


@pytest.fixture
def pg_conn():
    """Real PG conn — SAVEPOINT pattern per PR #320 / LL-157 sustained.

    反 mock-conn schema-drift anti-pattern (column-name + case-mismatch silent
    swallow). Only real PG can detect CHECK constraint + regime CHECK values.

    Each test wraps its INSERT in a SAVEPOINT then ROLLBACK TO SAVEPOINT to
    avoid persisting test rows + isolate from sibling tests in same conn.
    """
    conn = _connect_test_db()
    if conn is None:
        pytest.skip("PG not available — skip repository smoke (sustained 反 mock-conn)")
    yield conn
    conn.rollback()
    conn.close()


def test_persist_market_regime_inserts_and_returns_id(pg_conn) -> None:
    """SAVEPOINT-insert smoke: schema correctness + RETURNING regime_id contract."""
    r = _make_regime(regime=RegimeLabel.BULL, confidence=0.82)
    cur = pg_conn.cursor()
    cur.execute("SAVEPOINT test_insert")
    try:
        regime_id = persist_market_regime(pg_conn, r)
        assert regime_id > 0
        # Verify row landed with correct columns + CHECK constraint passed.
        cur.execute(
            "SELECT regime, confidence, cost_usd, market_indicators::text "
            "FROM market_regime_log WHERE regime_id = %s",
            (regime_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Bull"
        assert float(row[1]) == pytest.approx(0.82, abs=1e-4)
        assert float(row[2]) == pytest.approx(0.013, abs=1e-4)
        # JSONB market_indicators must contain timestamp + sse_return.
        ind_dict = json.loads(row[3])
        assert "timestamp" in ind_dict
        assert ind_dict["sse_return"] == -0.02
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT test_insert")
        cur.close()


def test_persist_market_regime_check_constraint_bad_regime_blocked(pg_conn) -> None:
    """DDL CHECK chk_regime_label rejects out-of-vocab regime (反 silent drift).

    Note: 模型层 RegimeLabel Enum 不允许构造 'Bullish' 等 invalid 值, 故本测试
    走 raw SQL bypass model layer 直插, 验证 DDL CHECK 守门 (defense in depth).
    """
    cur = pg_conn.cursor()
    cur.execute("SAVEPOINT test_bad_regime")
    try:
        ts = datetime(2026, 5, 14, 9, 0, 0, tzinfo=UTC)
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO market_regime_log (timestamp, regime, confidence) VALUES (%s, %s, %s)",
                (ts, "Bullish", 0.5),  # invalid label
            )
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT test_bad_regime")
        cur.close()


def test_persist_market_regime_check_constraint_bad_confidence_blocked(pg_conn) -> None:
    """DDL CHECK chk_confidence_range rejects confidence > 1 (defense in depth)."""
    cur = pg_conn.cursor()
    cur.execute("SAVEPOINT test_bad_conf")
    try:
        ts = datetime(2026, 5, 14, 9, 0, 0, tzinfo=UTC)
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "INSERT INTO market_regime_log (timestamp, regime, confidence) VALUES (%s, %s, %s)",
                (ts, "Bull", 1.5),  # out of [0, 1]
            )
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT test_bad_conf")
        cur.close()
