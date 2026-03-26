"""ExecutionService — 交易执行Service。

从scripts/run_paper_trading.py L1351-1713迁移。
完整执行: 熔断检查 -> CB调整 -> PaperBroker执行 -> 封板补单 -> 写trade_log。

复用现有engines(PaperBroker)，不重新实现。
Service内部不commit，由调用方统一管理事务。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd

from engines.backtest_engine import Fill, PendingOrder
from engines.paper_broker import PaperBroker
from app.config import settings
from app.services.notification_service import send_alert
from app.services.trading_calendar import get_prev_trading_day

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果。"""

    fills: list[Fill] = field(default_factory=list)
    nav: float = 0.0
    daily_return: float = 0.0
    position_count: int = 0
    pending_orders: list[PendingOrder] = field(default_factory=list)
    is_rebalance: bool = False
    cb_level: int = 0


class ExecutionService:
    """交易执行Service。

    职责:
    1. 读取信号 + 验证信号时效性
    2. 熔断检查 + 权重调整（L1延迟/L2暂停/L3降仓/L4停止）
    3. 延迟调仓恢复（L1恢复后执行pending月度调仓）
    4. 封板补单处理
    5. PaperBroker执行调仓
    6. 写trade_log（save_fills_only）
    """

    def execute_rebalance(
        self,
        conn,
        strategy_id: str,
        exec_date: date,
        target_weights: dict[str, float],
        cb_level: int,
        position_multiplier: float,
        price_data: pd.DataFrame,
        initial_capital: float,
        signal_date: Optional[date] = None,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """完整执行: CB调整 -> PaperBroker执行 -> 写trade_log。

        对应 script L1461-1679。

        Args:
            conn: psycopg2连接（调用方管理事务）。
            strategy_id: 策略ID。
            exec_date: 执行日期（T+1日）。
            target_weights: 目标权重 {code: weight}。
            cb_level: 熔断级别（0-4）。
            position_multiplier: 仓位乘数（L3=0.5）。
            price_data: 当日价格数据。
            initial_capital: 初始资金。
            signal_date: 信号日期（T日）。
            dry_run: 不写DB。

        Returns:
            ExecutionResult。
        """
        result = ExecutionResult()

        # ── 熔断权重调整 ──
        # 对应 script L1461-1508
        hedged_target = dict(target_weights)
        is_rebalance = True

        if cb_level >= 4:
            # L4 HALT: 清空调仓目标
            # 对应 script L1468-1477
            logger.error(f"[ExecutionService] L4 HALT, 不执行任何交易")
            hedged_target = {}
            is_rebalance = False
            result.cb_level = cb_level
            result.is_rebalance = False
            return result

        elif cb_level == 3:
            # L3 REDUCE: 降仓
            # 对应 script L1479-1484
            logger.warning(
                f"[ExecutionService] L3 REDUCE, 仓位乘数={position_multiplier}"
            )
            hedged_target = {
                k: v * position_multiplier for k, v in hedged_target.items()
            }
            is_rebalance = True

        elif cb_level == 2:
            # L2 PAUSE: 暂停交易
            # 对应 script L1486-1490
            logger.warning("[ExecutionService] L2 PAUSE, 暂停交易")
            is_rebalance = False

        elif cb_level == 1:
            # L1 DELAY: 月度调仓延迟
            # 对应 script L1492-1508
            logger.info("[ExecutionService] L1 DELAY, 月度调仓延迟")
            is_rebalance = False
            if not dry_run:
                self._save_pending_rebalance(
                    conn, signal_date or exec_date, hedged_target,
                )

        # ── 加载Broker状态 ──
        paper_broker = PaperBroker(
            strategy_id=strategy_id,
            initial_capital=initial_capital,
        )
        paper_broker.load_state(conn)

        fills: list[Fill] = []
        new_pending: list[PendingOrder] = []

        # ── 执行调仓 ──
        # 对应 script L1630-1658
        if is_rebalance and hedged_target:
            logger.info("[ExecutionService] 执行调仓 (T+1 open价格)...")
            rebal_fills, new_pending = paper_broker.execute_rebalance(
                hedged_target, exec_date, price_data,
                signal_date=signal_date,
            )
            fills.extend(rebal_fills)
            logger.info(
                f"[ExecutionService] 调仓完成: {len(rebal_fills)}笔成交, "
                f"{len(new_pending)}只封板"
            )

            # 保存封板补单记录
            # 对应 script L1640-1658
            if new_pending and not dry_run:
                self._save_pending_buy_orders(conn, new_pending)
        else:
            logger.info("[ExecutionService] 非调仓/暂停，无订单执行")

        # ── 写trade_log ──
        # 对应 script L1676-1679
        if not dry_run:
            paper_broker.save_fills_only(fills, conn)

        # 计算结果
        day_data = price_data[price_data["trade_date"] == exec_date]
        today_close = {}
        if not day_data.empty:
            for _, row in day_data.iterrows():
                today_close[row["code"]] = row["close"]

        result.fills = fills
        result.nav = paper_broker.get_current_nav(today_close) if today_close else 0.0
        result.position_count = len(paper_broker.broker.holdings) if paper_broker.broker else 0
        result.pending_orders = new_pending
        result.is_rebalance = is_rebalance
        result.cb_level = cb_level

        return result

    def process_pending_orders(
        self,
        conn,
        strategy_id: str,
        exec_date: date,
        price_data: pd.DataFrame,
        initial_capital: float,
        cb_level: int = 0,
        dry_run: bool = False,
    ) -> list[Fill]:
        """处理封板待补单。

        对应 script L1550-1628。

        Args:
            conn: psycopg2连接。
            strategy_id: 策略ID。
            exec_date: 当日日期。
            price_data: 当日价格数据。
            initial_capital: 初始资金。
            cb_level: 当前熔断级别。
            dry_run: 不写DB。

        Returns:
            成交记录列表。
        """
        # L4/L2暂停时不处理补单
        # 对应 script L1585-1587
        if cb_level >= 4:
            logger.warning(
                f"[ExecutionService] L{cb_level}熔断中，跳过补单"
            )
            return []

        # 读取pending_orders
        # 对应 script L1552-1570
        cur = conn.cursor()
        cur.execute(
            """SELECT result_json FROM scheduler_task_log
               WHERE task_name = 'pending_buy_orders' AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
        )
        pending_row = cur.fetchone()
        if not pending_row or not pending_row[0]:
            return []

        pending_data = (
            json.loads(pending_row[0])
            if isinstance(pending_row[0], str)
            else pending_row[0]
        )
        saved_pending: list[PendingOrder] = []
        for po_dict in pending_data.get("orders", []):
            saved_pending.append(PendingOrder(
                code=po_dict["code"],
                signal_date=datetime.strptime(
                    po_dict["signal_date"], "%Y-%m-%d"
                ).date(),
                exec_date=datetime.strptime(
                    po_dict["exec_date"], "%Y-%m-%d"
                ).date(),
                target_weight=po_dict["target_weight"],
                original_score=po_dict.get("original_score", 0),
            ))

        if not saved_pending:
            return []

        logger.info(
            f"[ExecutionService] 发现{len(saved_pending)}只封板待补单"
        )

        # 获取下次调仓日
        # 对应 script L1590-1606
        next_rebal_date = self._get_next_rebalance_date(conn, exec_date)

        # 加载Broker并处理补单
        paper_broker = PaperBroker(
            strategy_id=strategy_id,
            initial_capital=initial_capital,
        )
        paper_broker.load_state(conn)

        retry_fills, updated_pending = paper_broker.process_pending_orders(
            saved_pending, exec_date, price_data,
            next_rebal_date=next_rebal_date, conn=conn,
        )

        filled = [po for po in updated_pending if po.status == "filled"]
        cancelled = [po for po in updated_pending if po.status == "cancelled"]
        logger.info(
            f"[ExecutionService] 补单结果: "
            f"{len(filled)}成功, {len(cancelled)}取消"
        )
        for po in cancelled:
            logger.info(f"  取消: {po.code} 原因={po.cancel_reason}")

        # 更新pending状态
        # 对应 script L1623-1628
        if not dry_run:
            cur.execute(
                """UPDATE scheduler_task_log SET status='executed'
                   WHERE task_name='pending_buy_orders' AND status='pending'""",
            )

        # 写trade_log
        if not dry_run and retry_fills:
            paper_broker.save_fills_only(retry_fills, conn)

        return retry_fills

    def resume_pending_rebalance(
        self,
        conn,
        strategy_id: str,
        exec_date: date,
        cb_level: int = 0,
        dry_run: bool = False,
    ) -> tuple[bool, dict[str, float]]:
        """恢复延迟的月度调仓（L1恢复后执行）。

        对应 script L1510-1548。

        Args:
            conn: psycopg2连接。
            strategy_id: 策略ID。
            exec_date: 当日日期。
            cb_level: 当前熔断级别。
            dry_run: 不写DB。

        Returns:
            (should_rebalance, target_weights):
            是否应执行延迟调仓及目标权重。
        """
        # 只在NORMAL状态且非调仓日时检查
        if cb_level != 0:
            return False, {}

        cur = conn.cursor()
        cur.execute(
            """SELECT result_json FROM scheduler_task_log
               WHERE task_name = 'pending_monthly_rebalance' AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
        )
        pending = cur.fetchone()
        if not pending or not pending[0]:
            return False, {}

        pending_data = (
            json.loads(pending[0])
            if isinstance(pending[0], str)
            else pending[0]
        )
        pending_signal_date = pending_data.get("signal_date")
        pending_target = pending_data.get("target", {})

        if not pending_signal_date or not pending_target:
            return False, {}

        p_date = datetime.strptime(pending_signal_date, "%Y-%m-%d").date()

        # 检查交易日间隔（risk附加条件: 2个交易日内有效）
        # 对应 script L1525-1530
        cur.execute(
            """SELECT COUNT(*) FROM trading_calendar
               WHERE market='astock' AND is_trading_day=TRUE
               AND trade_date > %s AND trade_date < %s""",
            (p_date, exec_date),
        )
        gap = cur.fetchone()[0]

        if gap <= 2:
            logger.info(
                f"[ExecutionService] L1已恢复，执行延迟月度调仓"
                f"(signal={pending_signal_date})"
            )
            target = {k: float(v) for k, v in pending_target.items()}
            if not dry_run:
                cur.execute(
                    """UPDATE scheduler_task_log SET status='executed'
                       WHERE task_name='pending_monthly_rebalance'
                       AND status='pending'""",
                )
            return True, target
        else:
            logger.info(
                f"[ExecutionService] 延迟调仓过期(gap={gap}交易日), 放弃"
            )
            if not dry_run:
                cur.execute(
                    """UPDATE scheduler_task_log SET status='expired'
                       WHERE task_name='pending_monthly_rebalance'
                       AND status='pending'""",
                )
            return False, {}

    # ──────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────

    def _save_pending_rebalance(
        self,
        conn,
        signal_date: date,
        target: dict[str, float],
    ) -> None:
        """保存延迟月度调仓记录。对应 script L1498-1503。

        不commit，由调用方管理事务。
        """
        cur = conn.cursor()
        result = {
            "signal_date": str(signal_date),
            "target": {k: round(v, 6) for k, v in target.items()},
        }
        cur.execute(
            """INSERT INTO scheduler_task_log
               (task_name, market, schedule_time, start_time, status,
                error_message, result_json)
               VALUES ('pending_monthly_rebalance', 'astock', NOW(), NOW(),
                       'pending', %s, %s)""",
            (
                f"L1触发延迟月度调仓 signal_date={signal_date}",
                json.dumps(result),
            ),
        )

    def _save_pending_buy_orders(
        self,
        conn,
        pending_orders: list[PendingOrder],
    ) -> None:
        """保存封板补单记录。对应 script L1640-1658。

        不commit，由调用方管理事务。
        """
        cur = conn.cursor()
        pending_data = {
            "orders": [
                {
                    "code": po.code,
                    "signal_date": po.signal_date.isoformat(),
                    "exec_date": po.exec_date.isoformat(),
                    "target_weight": po.target_weight,
                    "original_score": po.original_score,
                }
                for po in pending_orders
            ]
        }
        cur.execute(
            """INSERT INTO scheduler_task_log
               (task_name, market, schedule_time, start_time, status,
                result_json)
               VALUES ('pending_buy_orders', 'astock', NOW(), NOW(),
                       'pending', %s)""",
            (json.dumps(pending_data),),
        )
        logger.info(
            f"[ExecutionService] 封板补单已保存: "
            f"{', '.join(po.code for po in pending_orders)}"
        )

    def _get_next_rebalance_date(
        self,
        conn,
        exec_date: date,
    ) -> Optional[date]:
        """获取下次月度调仓日。对应 script L1590-1606。"""
        cur = conn.cursor()
        cur.execute(
            """SELECT MIN(trade_date) FROM trading_calendar
               WHERE market = 'astock' AND is_trading_day = TRUE
                 AND trade_date > %s
                 AND trade_date = (
                     SELECT MAX(trade_date) FROM trading_calendar
                     WHERE market = 'astock' AND is_trading_day = TRUE
                       AND DATE_TRUNC('month', trade_date) = DATE_TRUNC('month',
                           (SELECT MIN(trade_date) FROM trading_calendar
                            WHERE market='astock' AND is_trading_day=TRUE
                            AND trade_date > %s))
                 )""",
            (exec_date, exec_date),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def validate_signal_freshness(
        self,
        conn,
        signal_date: date,
        exec_date: date,
    ) -> tuple[bool, str]:
        """验证信号时效性。对应 script L1412-1431。

        Args:
            conn: psycopg2连接。
            signal_date: 信号日期。
            exec_date: 执行日期。

        Returns:
            (is_valid, reason): 信号是否有效及原因。
        """
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM trading_calendar
               WHERE market='astock' AND is_trading_day=TRUE
                 AND trade_date > %s AND trade_date < %s""",
            (signal_date, exec_date),
        )
        trading_days_between = cur.fetchone()[0]

        if trading_days_between > 2:
            reason = (
                f"信号日{signal_date}距执行日{exec_date}"
                f"中间有{trading_days_between}个交易日，信号过时"
            )
            logger.warning(f"[ExecutionService] {reason}")
            return False, reason

        return True, f"信号有效(间隔{trading_days_between}交易日)"
