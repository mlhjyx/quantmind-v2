"""PaperBroker — consolidated behavioral unit tests (Plan 2, DEV_PAPER_BROKER §3/§7).

Closes the DEV_PAPER_BROKER §7.1 gap: the doc claimed `test_paper_broker.py` exists —
it did not. PaperBroker had only scattered coverage (BaseBroker interface in
test_base_broker.py, load_state mode-isolation in test_execution_mode_isolation.py,
return-tuple shape in test_pending_orders.py) and nothing asserted the core rebalance
behavior or the A股 T+1 invariant.

T+1 (DEV_PAPER_BROKER §3): A 当日买入的股票当日不可卖. PaperBroker satisfies this
*structurally* — it is a monthly-rebalance engine and `_do_rebalance` does 先卖后买
within one call (sells operate on holdings from the prior month's snapshot; buys run
after), so a same-day buy-then-sell cannot occur. `test_t1_*` below locks that
invariant in CI. The explicit fail-loud guard is a Phase J §8.2 item (real-time fill).

关联铁律: 10b (生产入口验证) / 40 (no test debt) / 15 (回测可复现).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pandas as pd
from engines.backtest_engine import BacktestConfig, Fill, PendingOrder, SimBroker
from engines.paper_broker import PaperBroker, PaperState

_BASE_PRICE = 10.0


def _make_price_data(
    codes: list[str],
    dates: list[date],
    base_price: float = _BASE_PRICE,
    limit_up_codes: dict[date, list[str]] | None = None,
) -> pd.DataFrame:
    """Synthetic price DataFrame — the columns SimBroker + ValidatorChain read.

    Mirrors test_pending_orders.py::_make_price_data. limit_up_codes marks a code as
    涨停封板 on a date (close == up_limit, turnover < 1% → can_trade rejects a buy).
    """
    rows = []
    limit_up_codes = limit_up_codes or {}
    for td in dates:
        for code in codes:
            pre_close = base_price
            if code in limit_up_codes.get(td, []):
                up_limit = round(pre_close * 1.10, 2)
                rows.append(
                    {
                        "code": code,
                        "trade_date": td,
                        "open": up_limit,
                        "high": up_limit,
                        "low": pre_close * 1.05,
                        "close": up_limit,
                        "pre_close": pre_close,
                        "volume": 100_000,
                        "amount": up_limit * 100_000,
                        "up_limit": up_limit,
                        "down_limit": round(pre_close * 0.90, 2),
                        "turnover_rate": 0.3,
                    }
                )
            else:
                rows.append(
                    {
                        "code": code,
                        "trade_date": td,
                        "open": base_price * 1.005,
                        "high": base_price * 1.02,
                        "low": base_price * 0.99,
                        "close": base_price * 1.01,
                        "pre_close": pre_close,
                        "volume": 5_000_000,
                        "amount": base_price * 5_000_000,
                        "up_limit": round(pre_close * 1.10, 2),
                        "down_limit": round(pre_close * 0.90, 2),
                        "turnover_rate": 5.0,
                    }
                )
    return pd.DataFrame(rows)


def _make_broker(
    holdings: dict[str, int], cash: float, initial: float = 1_000_000.0
) -> PaperBroker:
    """PaperBroker with SimBroker state initialised in-memory (no DB load)."""
    broker = PaperBroker(strategy_id="test", execution_mode="paper", initial_capital=initial)
    broker.broker = SimBroker(BacktestConfig(initial_capital=initial))
    broker.broker.cash = cash
    broker.broker.holdings = dict(holdings)
    nav = cash + sum(holdings.values()) * _BASE_PRICE
    broker.state = PaperState(cash=cash, holdings=dict(holdings), nav=nav)
    return broker


# ─────────────────────────────────────────────────────────────
# load_state — cold start
# ─────────────────────────────────────────────────────────────


class TestLoadStateColdStart:
    def test_first_run_initialises_all_cash(self) -> None:
        """No prior position_snapshot → all-cash PaperState + SimBroker initialised."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (None,)  # MAX(trade_date) → no history
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        broker = PaperBroker(strategy_id="t", execution_mode="paper", initial_capital=1_000_000)
        state = broker.load_state(mock_conn)

        assert state.cash == 1_000_000
        assert state.holdings == {}
        assert state.nav == 1_000_000
        assert state.last_trade_date is None
        # SimBroker must be initialised so execute_rebalance can run.
        assert broker.broker is not None
        assert broker.broker.cash == 1_000_000


# ─────────────────────────────────────────────────────────────
# needs_rebalance — month-end logic
# ─────────────────────────────────────────────────────────────


class TestNeedsRebalance:
    def test_no_holdings_forces_rebalance(self) -> None:
        """无持仓 → 必须建仓 (returns True without touching the DB)."""
        broker = _make_broker(holdings={}, cash=1_000_000)
        # state.holdings empty → short-circuits before any conn use.
        assert broker.needs_rebalance(date(2024, 3, 15), MagicMock()) is True

    def test_rebalances_only_on_last_trading_day_of_month(self) -> None:
        """With holdings: rebalance iff today == 本月最后交易日."""
        broker = _make_broker(holdings={"X": 5000}, cash=500_000)
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (date(2024, 3, 29),)  # month-end
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        assert broker.needs_rebalance(date(2024, 3, 29), mock_conn) is True
        assert broker.needs_rebalance(date(2024, 3, 15), mock_conn) is False


# ─────────────────────────────────────────────────────────────
# execute_rebalance — 先卖后买
# ─────────────────────────────────────────────────────────────


class TestExecuteRebalance:
    def test_sell_then_buy_transitions_holdings(self) -> None:
        """Exit an old position, enter a new one — fills + holdings reflect both."""
        td = date(2024, 3, 29)
        price_data = _make_price_data(["OLD", "NEW"], [td])
        broker = _make_broker(holdings={"OLD": 20_000}, cash=100_000)

        fills, pending = broker.execute_rebalance({"NEW": 0.60}, td, price_data, signal_date=td)

        directions = {f.code: f.direction for f in fills}
        assert directions.get("OLD") == "sell", "OLD dropped from target → sold"
        assert directions.get("NEW") == "buy", "NEW in target → bought"
        assert "OLD" not in broker.broker.holdings, "OLD fully exited"
        assert broker.broker.holdings.get("NEW", 0) > 0, "NEW position opened"
        assert pending == [], "no 封板 → no pending orders"

    def test_limit_up_buy_becomes_pending(self) -> None:
        """A 涨停封板 buy target cannot fill → recorded as a PendingOrder."""
        td = date(2024, 3, 29)
        price_data = _make_price_data(["A", "B"], [td], limit_up_codes={td: ["A"]})
        broker = _make_broker(holdings={}, cash=1_000_000)

        fills, pending = broker.execute_rebalance(
            {"A": 0.50, "B": 0.50}, td, price_data, signal_date=td
        )
        assert any(f.code == "B" and f.direction == "buy" for f in fills), "B fills normally"
        assert any(po.code == "A" and po.status == "pending" for po in pending), (
            "A 封板 → PendingOrder"
        )

    def test_portfolio_value_conserved_minus_costs(self) -> None:
        """Rebalance conserves NAV up to transaction costs (no value leak)."""
        td = date(2024, 3, 29)
        price_data = _make_price_data(["OLD", "NEW"], [td])
        broker = _make_broker(holdings={"OLD": 20_000}, cash=100_000)
        today_close = {"OLD": _BASE_PRICE * 1.01, "NEW": _BASE_PRICE * 1.01}

        pre = broker.broker.get_portfolio_value(today_close)
        broker.execute_rebalance({"NEW": 0.60}, td, price_data, signal_date=td)
        post = broker.broker.get_portfolio_value(today_close)

        # Costs are small (commission + slippage + tax) — post within 5% below pre.
        assert 0.95 * pre <= post <= pre + 1.0


# ─────────────────────────────────────────────────────────────
# T+1 invariant — 先卖后买 prevents a same-day round-trip
# ─────────────────────────────────────────────────────────────


class TestT1Invariant:
    def test_no_code_is_both_bought_and_sold_same_day(self) -> None:
        """A股 T+1 (DEV_PAPER_BROKER §3): within one rebalance, no code may be both a
        buy fill and a sell fill on the same trade_date — `_do_rebalance` computes a
        single per-code target delta, so each code is trimmed XOR added XOR untouched.

        KEEP is in both current holdings AND the target — a buggy engine could
        round-trip it; the structural invariant forbids that.
        """
        td = date(2024, 3, 29)
        price_data = _make_price_data(["KEEP", "EXIT", "NEW"], [td])
        broker = _make_broker(holdings={"KEEP": 5_000, "EXIT": 8_000}, cash=200_000)

        fills, _ = broker.execute_rebalance(
            {"KEEP": 0.50, "NEW": 0.30}, td, price_data, signal_date=td
        )
        buy_codes = {f.code for f in fills if f.direction == "buy"}
        sell_codes = {f.code for f in fills if f.direction == "sell"}

        assert buy_codes & sell_codes == set(), (
            f"T+1 violation — code(s) bought AND sold same day: {buy_codes & sell_codes}"
        )
        # All fills are on the rebalance trade_date (no cross-day leakage).
        assert all(f.trade_date == td for f in fills)

    def test_pending_order_retry_only_buys(self) -> None:
        """process_pending_orders (T+1 补单) only ever buys — never sells a same-day
        position, so it cannot create a T+1 violation.
        """
        td = date(2024, 4, 1)
        price_data = _make_price_data(["A"], [td])
        broker = _make_broker(holdings={}, cash=500_000)
        pending = [
            PendingOrder(
                code="A",
                signal_date=date(2024, 3, 29),
                exec_date=date(2024, 3, 29),
                target_weight=0.05,
                original_score=50_000,
            )
        ]
        fills, _ = broker.process_pending_orders(pending, td, price_data)
        assert all(f.direction == "buy" for f in fills), "补单 must only buy"


# ─────────────────────────────────────────────────────────────
# process_pending_orders — return contract
# ─────────────────────────────────────────────────────────────


class TestProcessPendingOrders:
    def test_returns_fills_and_updated_pending_tuple(self) -> None:
        td = date(2024, 4, 1)
        price_data = _make_price_data(["A"], [td])
        broker = _make_broker(holdings={}, cash=500_000)
        pending = [
            PendingOrder(
                code="A",
                signal_date=date(2024, 3, 29),
                exec_date=date(2024, 3, 29),
                target_weight=0.05,
                original_score=50_000,
            )
        ]
        result = broker.process_pending_orders(pending, td, price_data)
        assert isinstance(result, tuple) and len(result) == 2
        fills, updated = result
        assert isinstance(fills, list)
        assert all(isinstance(f, Fill) for f in fills)
        assert isinstance(updated, list)
