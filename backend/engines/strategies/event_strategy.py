"""EventStrategy — 事件驱动策略基类。

事件型策略与排序型策略的核心区别:
- 排序型(EqualWeight/FastRanking): 定期调仓，全量重排
- 事件型(EventStrategy): 事件触发时才交易，持仓保持到下个事件/止损

支持事件类型（DESIGN_V5 §6 扩展）:
- RSRS_BREAKOUT: RSRS指标突破信号
- PEAD: 盈余公告后漂移(Post-Earnings Announcement Drift)
- ST_REMOVAL: ST摘帽（风险解除）
- BLOCK_TRADE: 大股东增减持公告

核心接口:
- on_event(event, context) -> StrategyDecision  当事件触发时的处理
- event_filter(event, context) -> bool          过滤不符合条件的事件
- position_sizing(event, context) -> float      个股仓位sizing

与BaseStrategy的关系:
- 继承BaseStrategy，共享StrategyContext/StrategyDecision接口
- generate_signals()检查pending events，按序调用on_event()
- should_rebalance()由事件决定，不看日历

设计文档对照:
- docs/research/R3_multi_strategy_framework.md §7.2（Modifier/事件型）
- backend/engines/base_strategy.py（BaseStrategy接口）
- DESIGN_V5.md §6 信号类型定义
"""

import logging
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from engines.base_strategy import (
    BaseStrategy,
    RebalanceFreq,
    SignalType,
    StrategyContext,
    StrategyDecision,
    StrategyMeta,
    WeightMethod,
)

logger = logging.getLogger(__name__)


class EventType(StrEnum):
    """事件类型枚举。"""

    RSRS_BREAKOUT = "rsrs_breakout"  # RSRS指标突破
    PEAD = "pead"  # 盈余公告后漂移
    ST_REMOVAL = "st_removal"  # ST摘帽
    BLOCK_TRADE = "block_trade"  # 大股东增减持
    CUSTOM = "custom"  # 自定义事件


@dataclass
class TradingEvent:
    """交易事件。

    Attributes:
        event_type: 事件类型
        code: 触发事件的股票代码
        event_date: 事件发生日期
        signal_value: 信号强度（-1到1，正数看多，负数看空）
        meta: 附加元数据（事件相关的其他信息）
    """

    event_type: EventType
    code: str
    event_date: date
    signal_value: float  # [-1, 1]，正=看多，负=看空
    meta: dict[str, Any] = field(default_factory=dict)


class EventStrategy(BaseStrategy):
    """事件驱动策略基类。

    子类必须实现:
    - on_event: 处理单个事件，返回目标权重调整
    - event_filter: 过滤不符合条件的事件（返回True=通过）
    - position_sizing: 根据事件强度计算个股仓位

    可选覆盖:
    - load_events: 从数据库/内存加载当天待处理事件
    - aggregate_events: 同一股票多个事件时的聚合逻辑

    config必须包含:
        factor_names: list[str]     用于评估股票质量的因子（可为空列表）
        top_n: int                  最大同时持仓数（事件型通常较少，5-15）
        weight_method: str          equal | score_weighted
        max_position_size: float    单股最大仓位，默认0.15
        min_signal_strength: float  最低信号强度阈值，默认0.3
        stop_loss_pct: float        止损比例，默认0.08（8%）
    """

    signal_type = SignalType.EVENT

    @classmethod
    def get_meta(cls) -> StrategyMeta:
        """策略元信息。"""
        return StrategyMeta(
            name="event_strategy",
            signal_type=SignalType.EVENT,
            supported_freqs=[
                RebalanceFreq.DAILY,  # 事件型每日检查
            ],
            supported_weights=[WeightMethod.EQUAL, WeightMethod.SCORE_WEIGHTED],
            description="事件驱动策略基类（RSRS突破/PEAD/ST摘帽/大股东增减持）",
        )

    @abstractmethod
    def on_event(
        self,
        event: TradingEvent,
        context: StrategyContext,
    ) -> dict[str, float] | None:
        """处理单个事件，返回目标权重调整。

        Args:
            event: 触发的交易事件
            context: 运行时上下文

        Returns:
            {code: target_weight} 或 None（表示忽略此事件）
            weight > 0 = 买入/增仓，weight = 0 = 清仓
        """

    @abstractmethod
    def event_filter(
        self,
        event: TradingEvent,
        context: StrategyContext,
    ) -> bool:
        """过滤事件。

        Args:
            event: 待过滤的事件
            context: 运行时上下文

        Returns:
            True = 事件通过（应处理），False = 过滤掉
        """

    @abstractmethod
    def position_sizing(
        self,
        event: TradingEvent,
        context: StrategyContext,
    ) -> float:
        """根据事件强度计算个股目标仓位。

        Args:
            event: 触发的事件（含signal_value强度）
            context: 运行时上下文

        Returns:
            目标仓位权重 [0, max_position_size]
        """

    def load_events(self, context: StrategyContext) -> list[TradingEvent]:
        """从上下文加载当天待处理事件。

        默认从context.conn查询event_signals表。
        子类可覆盖以从不同数据源加载事件。

        Args:
            context: 运行时上下文

        Returns:
            当天的事件列表
        """
        if context.conn is None:
            return []

        try:
            cur = context.conn.cursor()
            cur.execute(
                """
                SELECT es.ts_code, es.event_type, es.signal_value,
                       es.event_date, es.meta
                FROM event_signals es
                JOIN symbols s ON es.symbol_id = s.id
                WHERE es.event_date = %s
                  AND es.processed = FALSE
                ORDER BY ABS(es.signal_value) DESC
                """,
                (context.trade_date,),
            )
            rows = cur.fetchall()
            cur.close()

            events = []
            for code, etype, sval, edate, meta in rows:
                try:
                    events.append(
                        TradingEvent(
                            event_type=EventType(etype),
                            code=code,
                            event_date=edate,
                            signal_value=float(sval),
                            meta=meta or {},
                        )
                    )
                except ValueError:
                    # 未知event_type，用CUSTOM
                    events.append(
                        TradingEvent(
                            event_type=EventType.CUSTOM,
                            code=code,
                            event_date=edate,
                            signal_value=float(sval),
                            meta={"original_type": etype, **(meta or {})},
                        )
                    )
            return events

        except Exception as exc:
            logger.warning(f"[EventStrategy] load_events失败: {exc}")
            return []

    def aggregate_events(self, events: list[TradingEvent]) -> list[TradingEvent]:
        """同一股票多个事件时聚合为单一事件。

        默认策略: 取signal_value绝对值最大的事件。
        子类可覆盖实现加权平均或其他聚合逻辑。

        Args:
            events: 事件列表（可含同一股票的多个事件）

        Returns:
            聚合后的事件列表（每只股票最多一个事件）
        """
        by_code: dict[str, TradingEvent] = {}
        for event in events:
            if event.code not in by_code:
                by_code[event.code] = event
            else:
                existing = by_code[event.code]
                if abs(event.signal_value) > abs(existing.signal_value):
                    by_code[event.code] = event
        return list(by_code.values())

    def generate_signals(self, context: StrategyContext) -> StrategyDecision:
        """事件驱动信号生成主流程。

        流程:
        1. load_events: 加载当天事件
        2. event_filter: 过滤不符合条件的事件
        3. aggregate_events: 同一股票多事件聚合
        4. on_event: 处理每个通过的事件
        5. 合并所有权重调整，归一化

        Args:
            context: 运行时上下文

        Returns:
            StrategyDecision: 目标权重 + 是否触发调仓 + 告警
        """
        warnings: list[str] = []

        # ── Step 1: 加载事件 ──
        raw_events = self.load_events(context)
        if not raw_events:
            logger.debug(f"[EventStrategy] {context.trade_date} 无事件，保持当前持仓")
            return StrategyDecision(
                target_weights=context.prev_holdings or {},
                is_rebalance=False,
                reasoning="无事件触发，保持当前持仓",
                warnings=warnings,
                signal_type=SignalType.EVENT,
            )

        # ── Step 2: 过滤 ──
        filtered = [e for e in raw_events if self.event_filter(e, context)]
        filtered_out = len(raw_events) - len(filtered)
        if filtered_out > 0:
            logger.debug(f"[EventStrategy] 过滤掉{filtered_out}个事件，剩余{len(filtered)}个")

        if not filtered:
            return StrategyDecision(
                target_weights=context.prev_holdings or {},
                is_rebalance=False,
                reasoning="所有事件被过滤，保持当前持仓",
                warnings=warnings,
                signal_type=SignalType.EVENT,
            )

        # ── Step 3: 聚合（同一股票多事件）──
        events = self.aggregate_events(filtered)

        # ── Step 4: 处理每个事件 ──
        target: dict[str, float] = dict(context.prev_holdings or {})
        triggered_count = 0

        for event in events:
            result = self.on_event(event, context)
            if result is None:
                continue
            triggered_count += 1
            target.update(result)

        if triggered_count == 0:
            return StrategyDecision(
                target_weights=context.prev_holdings or {},
                is_rebalance=False,
                reasoning="事件处理后无权重变化",
                warnings=warnings,
                signal_type=SignalType.EVENT,
            )

        # ── Step 5: top_n约束+归一化 ──
        target = self._apply_top_n_constraint(target)
        total = sum(v for v in target.values() if v > 0)
        cash_buffer = self.config.get("cash_buffer", 0.03)
        if total > 1e-9:
            scale = (1.0 - cash_buffer) / total
            target = {c: w * scale for c, w in target.items() if w > 0}

        logger.info(f"[EventStrategy] 处理{triggered_count}个事件, 最终持仓{len(target)}只")

        return StrategyDecision(
            target_weights=target,
            is_rebalance=True,
            reasoning=(f"事件触发: {triggered_count}个事件处理, 持仓{len(target)}只"),
            warnings=warnings,
            signal_type=SignalType.EVENT,
        )

    def should_rebalance(self, trade_date: date, conn: Any) -> bool:
        """事件型策略: 每日检查（由generate_signals内部判断是否实际调仓）。"""
        return True

    def _apply_top_n_constraint(self, weights: dict[str, float]) -> dict[str, float]:
        """限制最大持仓数量为top_n。

        超出top_n时，保留权重最大的top_n只。

        Args:
            weights: 原始权重字典

        Returns:
            截断到top_n的权重字典
        """
        top_n = self.config.get("top_n", 10)
        positive = {c: w for c, w in weights.items() if w > 0}
        if len(positive) <= top_n:
            return positive

        # 按权重排序，保留top_n
        sorted_items = sorted(positive.items(), key=lambda x: x[1], reverse=True)
        kept = dict(sorted_items[:top_n])
        dropped = len(positive) - top_n
        if dropped > 0:
            logger.debug(f"[EventStrategy] top_n={top_n}约束: 丢弃{dropped}只小仓位")
        return kept

    def _validate_config(self) -> None:
        """验证EventStrategy配置。"""
        # factor_names可以为空（事件型策略不一定需要因子）
        if "factor_names" not in self.config:
            self.config["factor_names"] = []
        if "top_n" not in self.config:
            raise ValueError("EventStrategy config必须包含top_n")
        if "weight_method" not in self.config:
            self.config["weight_method"] = "equal"

        max_pos = self.config.get("max_position_size", 0.15)
        if not (0.01 <= max_pos <= 0.50):
            raise ValueError(f"max_position_size必须在[0.01, 0.50]，当前: {max_pos}")
