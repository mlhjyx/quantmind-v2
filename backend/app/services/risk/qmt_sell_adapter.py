"""QMTSellAdapter — wraps MiniQMTBroker.place_order as BrokerProtocol.sell (S8 8c-followup).

Single point where production broker (engines/broker_qmt.py) crosses into the
STAGED execution path. 5/5 红线 关键点 — LiveTradingGuard sustained at the
MiniQMTBroker.place_order layer; this adapter does NOT bypass any guard.

Layered architecture:
  - Adapter (this file) — translates BrokerProtocol shape ↔ MiniQMTBroker
  - Service (staged_execution_service.py) — orchestrates SELECT + sell + UPDATE
  - Engine (qm_platform/risk/execution/broker_executor.py) — pure interpret

BrokerProtocol contract (matching RiskBacktestAdapter.sell signature):
    sell(code: str, shares: int, reason: str, timeout: float) -> dict[str, Any]
    Returns dict with keys: status, code, shares, filled_shares, price,
        order_id (str|None), error (str|None).

Failure modes handled:
  - LiveTradingDisabledError (paper-mode 红线 guard) → status='rejected',
    error='live_trading_disabled' (NOT raised — caller can mark plan FAILED
    with stable reason rather than special-casing this exception class).
  - MiniQMTBroker.place_order returns -1 → status='rejected', error='broker_returned_-1'
  - Connect errors / xtquant exceptions → status='error', error=<type:msg>
  - place_order success (order_id ≥ 0) → status='ok', order_id=str(id),
    filled_shares=0 (fill comes via async broker callback; this method
    returns at order-submit time, not at fill confirmation time).

铁律 31 NOT directly invoked (service layer, not engine).
铁律 33 sustained: errors converted to FAILURE result dict (not silent skip);
  caller (broker_executor + StagedExecutionService) records FAILED state.
铁律 35 sustained: account_id / qmt_path read from settings (single env source).
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.exceptions import LiveTradingDisabledError

logger = logging.getLogger(__name__)


class QMTSellAdapter:
    """Adapter that exposes MiniQMTBroker.place_order via BrokerProtocol.sell.

    Stateless wrapper — broker is injected at construction time (or lazily
    constructed via from_settings factory). Production wire: paper-mode and
    live-mode share the same code path; LiveTradingGuard inside
    MiniQMTBroker.place_order enforces the 真金 boundary.

    Usage:
        broker = MiniQMTBroker(qmt_path=settings.QMT_PATH,
                               account_id=settings.QMT_ACCOUNT_ID)
        broker.connect()
        adapter = QMTSellAdapter(broker=broker)
        result = adapter.sell("000001.SZ", 100, "l4_abc12345", timeout=5.0)
        # result['status'] in {'ok', 'rejected', 'error'}
    """

    def __init__(self, broker: Any) -> None:
        """Inject MiniQMTBroker (or compatible — duck-typed).

        Args:
            broker: object with place_order(code, direction, volume, price,
                price_type, remark) → int signature. Production:
                engines.broker_qmt.MiniQMTBroker. Tests can inject a mock.
        """
        self._broker = broker

    def sell(
        self,
        code: str,
        shares: int,
        reason: str,
        timeout: float = 5.0,  # noqa: ARG002 — kept for BrokerProtocol parity
    ) -> dict[str, Any]:
        """Submit sell order via MiniQMTBroker; translate result to BrokerProtocol shape.

        Args:
            code: stock code, e.g. "000001.SZ".
            shares: integer share count (>0).
            reason: audit string, truncated to 24 chars for xtquant remark.
            timeout: kept for protocol parity; MiniQMTBroker.place_order is
                synchronous + relies on xtquant's own timeout semantics. Not
                currently passed through. Documented for future wiring.

        Returns:
            dict with keys: status, code, shares, filled_shares, price,
            order_id, error.

            Success: status='ok', order_id=str(broker_order_id), filled_shares=0,
                price=0.0 (fill confirmation arrives asynchronously via broker
                callback; this method returns at order-submit time only).
            Rejection: status='rejected', order_id=None, error='broker_returned_-1'.
            Live-trading blocked: status='rejected', error='live_trading_disabled'.
            Other exception: status='error', error='<ExceptionType>: <msg>'.

        Raises:
            ValueError: shares ≤ 0 (defensive, BrokerProtocol caller should validate).
            (No other exceptions propagate — all wrapped in result dict per 反 silent.)
        """
        if shares <= 0:
            raise ValueError(f"shares must be > 0, got {shares}")

        # Truncate reason to 24 chars (xtquant order_remark limit, sustained from
        # MiniQMTBroker.place_order's own safe_remark = remark[:24] guard).
        safe_reason = (reason or "")[:24]

        try:
            order_id = self._broker.place_order(
                code=code,
                direction="sell",
                volume=shares,
                price=None,  # market order — let MiniQMTBroker pick MARKET_SH/SZ_CONVERT_5
                price_type="market",
                remark=safe_reason,
            )
        except LiveTradingDisabledError as e:
            # 红线 guard fired — paper-mode default behavior. Convert to
            # rejection dict so caller marks plan FAILED with stable reason.
            logger.warning(
                "[qmt-sell-adapter] live_trading_disabled blocked sell code=%s shares=%d: %s",
                code,
                shares,
                e,
            )
            return {
                "status": "rejected",
                "code": code,
                "shares": shares,
                "filled_shares": 0,
                "price": 0.0,
                "order_id": None,
                "error": "live_trading_disabled",
            }
        except Exception as e:
            # Any other exception (connect error / xtquant import / etc) — record
            # as error result so caller logs FAILED. Do NOT raise (反 silent
            # broker outage → STAGED queue starvation; caller still gets FAILED
            # via execute_plan_sell return path).
            #
            # Reviewer P2 (security-reviewer): cap message length so stack-trace
            # details don't leak verbatim into API response bodies.
            logger.exception(
                "[qmt-sell-adapter] place_order raised for code=%s shares=%d",
                code,
                shares,
            )
            return {
                "status": "error",
                "code": code,
                "shares": shares,
                "filled_shares": 0,
                "price": 0.0,
                "order_id": None,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            }

        if order_id is None or order_id < 0:
            # MiniQMTBroker.place_order documented return: -1 on failure
            logger.warning(
                "[qmt-sell-adapter] place_order returned %s for code=%s shares=%d",
                order_id,
                code,
                shares,
            )
            return {
                "status": "rejected",
                "code": code,
                "shares": shares,
                "filled_shares": 0,
                "price": 0.0,
                "order_id": None,
                "error": f"broker_returned_{order_id}",
            }

        logger.info(
            "[qmt-sell-adapter] sell submitted code=%s shares=%d order_id=%d reason=%s",
            code,
            shares,
            order_id,
            safe_reason,
        )
        return {
            "status": "ok",
            "code": code,
            "shares": shares,
            "filled_shares": 0,  # fill confirmation arrives async via broker callback
            "price": 0.0,
            "order_id": str(order_id),
            "error": None,
        }


def is_paper_mode_or_disabled() -> bool:
    """Returns True iff paper-mode or LIVE_TRADING_DISABLED — factory routing helper.

    Centralizes the boolean used by the staged-execution factory to decide
    between RiskBacktestAdapter (paper / disabled) vs QMTSellAdapter (live).

    True iff:
        - settings.EXECUTION_MODE == "paper", OR
        - settings.LIVE_TRADING_DISABLED is True

    Returns:
        bool — True → use RiskBacktestAdapter (0 broker call).
    """
    execution_mode = getattr(settings, "EXECUTION_MODE", "paper")
    live_disabled = getattr(settings, "LIVE_TRADING_DISABLED", True)
    return execution_mode == "paper" or live_disabled


__all__ = [
    "QMTSellAdapter",
    "is_paper_mode_or_disabled",
]
