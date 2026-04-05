"""QMT对账服务 — 执行后验证QMT持仓与DB一致性。

在live模式执行调仓后调用，对比:
1. QMT实时持仓 vs DB position_snapshot
2. QMT现金余额 vs 预期现金

差异超阈值时触发DingTalk告警。
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 对账阈值
POSITION_MISMATCH_THRESHOLD = 0  # 股数差异容忍（0=精确匹配）
CASH_MISMATCH_RATIO = 0.02       # 现金差异容忍2%


@dataclass
class ReconciliationResult:
    """对账结果。"""
    is_matched: bool = True
    position_mismatches: list[dict[str, Any]] = field(default_factory=list)
    cash_mismatch: dict[str, Any] | None = None
    qmt_positions: dict[str, int] = field(default_factory=dict)
    db_positions: dict[str, int] = field(default_factory=dict)
    qmt_cash: float = 0.0
    summary: str = ""


class QMTReconciliationService:
    """QMT对账服务。"""

    def reconcile(
        self,
        conn,
        strategy_id: str,
        trade_date: date,
    ) -> ReconciliationResult:
        """执行对账: QMT持仓 vs DB position_snapshot。

        Args:
            conn: psycopg2连接。
            strategy_id: 策略ID。
            trade_date: 对账日期。

        Returns:
            ReconciliationResult。
        """
        from app.services.qmt_connection_manager import qmt_manager

        result = ReconciliationResult()

        # 1. 从QMT查询实时持仓和资产
        try:
            qmt_manager.ensure_connected()
            broker = qmt_manager.broker
            qmt_positions = broker.get_positions()  # {code: shares}
            qmt_asset = broker.query_asset()
            qmt_cash = float(qmt_asset.get("cash", 0))
        except Exception as e:
            result.is_matched = False
            result.summary = f"QMT查询失败: {e}"
            logger.error(f"[Reconciliation] {result.summary}")
            return result

        result.qmt_positions = qmt_positions
        result.qmt_cash = qmt_cash

        # 2. 从DB查询最新position_snapshot
        cur = conn.cursor()
        cur.execute(
            """SELECT code, quantity FROM position_snapshot
               WHERE strategy_id = %s AND trade_date = %s
                 AND execution_mode = 'live' AND quantity > 0""",
            (strategy_id, trade_date),
        )
        db_positions: dict[str, int] = {}
        for row in cur.fetchall():
            db_positions[row[0]] = int(row[1])
        result.db_positions = db_positions

        # 3. 对比持仓
        all_codes = set(qmt_positions.keys()) | set(db_positions.keys())
        for code in sorted(all_codes):
            qmt_shares = qmt_positions.get(code, 0)
            db_shares = db_positions.get(code, 0)
            diff = abs(qmt_shares - db_shares)
            if diff > POSITION_MISMATCH_THRESHOLD:
                mismatch = {
                    "code": code,
                    "qmt_shares": qmt_shares,
                    "db_shares": db_shares,
                    "diff": qmt_shares - db_shares,
                }
                result.position_mismatches.append(mismatch)
                result.is_matched = False
                logger.warning(
                    f"[Reconciliation] 持仓差异: {code} "
                    f"QMT={qmt_shares} DB={db_shares} diff={qmt_shares - db_shares}"
                )

        # 4. 现金余额对比（从performance_series读DB端现金）
        cur.execute(
            """SELECT cash FROM performance_series
               WHERE strategy_id = %s AND trade_date = %s
                 AND execution_mode = 'live'""",
            (strategy_id, trade_date),
        )
        perf_row = cur.fetchone()
        if perf_row and perf_row[0] is not None:
            db_cash = float(perf_row[0])
            if db_cash > 0:
                cash_ratio = abs(qmt_cash - db_cash) / db_cash
                if cash_ratio > CASH_MISMATCH_RATIO:
                    result.cash_mismatch = {
                        "qmt_cash": qmt_cash,
                        "db_cash": db_cash,
                        "diff": qmt_cash - db_cash,
                        "ratio": cash_ratio,
                    }
                    result.is_matched = False
                    logger.warning(
                        f"[Reconciliation] 现金差异: "
                        f"QMT={qmt_cash:.0f} DB={db_cash:.0f} "
                        f"ratio={cash_ratio:.2%}"
                    )

        # 5. 生成摘要
        if result.is_matched:
            result.summary = (
                f"对账通过: {len(qmt_positions)}只持仓一致, "
                f"现金={qmt_cash:.0f}"
            )
            logger.info(f"[Reconciliation] {result.summary}")
        else:
            parts = []
            if result.position_mismatches:
                parts.append(f"{len(result.position_mismatches)}只持仓差异")
            if result.cash_mismatch:
                parts.append("现金差异")
            result.summary = f"对账异常: {', '.join(parts)}"
            logger.error(f"[Reconciliation] {result.summary}")

        return result

    def reconcile_and_alert(
        self,
        conn,
        strategy_id: str,
        trade_date: date,
    ) -> ReconciliationResult:
        """对账并在异常时发送DingTalk告警。

        Args:
            conn: psycopg2连接。
            strategy_id: 策略ID。
            trade_date: 对账日期。

        Returns:
            ReconciliationResult。
        """
        result = self.reconcile(conn, strategy_id, trade_date)

        if not result.is_matched:
            self._send_alert(result, trade_date)

        return result

    def _send_alert(self, result: ReconciliationResult, trade_date: date) -> None:
        """发送对账异常告警。"""
        try:
            from app.services.notification_service import send_alert

            msg_parts = [result.summary]

            for m in result.position_mismatches:
                msg_parts.append(
                    f"  {m['code']}: QMT={m['qmt_shares']} "
                    f"DB={m['db_shares']} diff={m['diff']}"
                )

            if result.cash_mismatch:
                cm = result.cash_mismatch
                msg_parts.append(
                    f"  现金: QMT={cm['qmt_cash']:.0f} "
                    f"DB={cm['db_cash']:.0f} diff={cm['diff']:.0f}"
                )

            send_alert(
                level="P1",
                title=f"QMT对账异常 {trade_date}",
                content="\n".join(msg_parts),
            )
        except Exception:
            logger.exception("[Reconciliation] 发送告警失败")
