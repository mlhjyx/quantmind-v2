"""IntradayRules — 盘中组合级风险规则 (MVP 3.1 批 2).

4 规则迁自 ADR-010 D5 迁移表:
  - IntradayPortfolioDrop{3,5,8}PctRule: 组合级盘中跌幅 (alert_only)
  - QMTDisconnectRule: QMT Data Service 断连告警 (alert_only)

调度: 盘中 5min cron (09:35-15:00 MoFr, 54 次/日, 批 2 PR 2 新 Celery Beat entry).

决策 (MVP_3_1_batch_2_plan.md §5):
  - Portfolio drop 基类抽象 threshold + rule_id + severity, 3 子类差异化阈值
  - QMTDisconnect 独立类 (非 portfolio 派生, 语义正交)
  - action='alert_only' (批 2 不下单, 批 3 升真 broker 统一)
  - 纯计算 (铁律 31): rule 不 IO, QMT 状态由 Protocol 注入

关联铁律: 24 / 31 / 33 / 34 / 41
"""
from __future__ import annotations

import math
from abc import abstractmethod
from typing import Literal, Protocol

from backend.platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult

# ---------- Protocol: QMTConnectionReader (DI, 批 2 新增) ----------


class QMTConnectionReader(Protocol):
    """QMT Data Service 连接状态读取契约 (duck-typing 适配 app.core.qmt_client.QMTClient).

    实现必须从 Redis `qm:qmt:status` event stream 读 (批 1 PriceReader 同实例复用),
    避免 5min × 54 次直连 QMT Data Service 放大 API quota 压力 (plan §9).

    Note: 非 `@runtime_checkable` — 避免 isinstance 检查触发 TypeError 被 silent swallow.
    单测用 `MagicMock(spec=QMTConnectionReader)`, 生产用 duck-typing.
    (reviewer P2 采纳 python: 文档化避免未来 isinstance guard footgun)
    """

    def is_connected(self) -> bool:
        """QMT Data Service 连接状态. False = 断连 (触发 QMTDisconnectRule)."""
        ...


# ---------- Base: IntradayPortfolioDropRule (抽象) ----------


class IntradayPortfolioDropRule(RiskRule):
    """组合级盘中跌幅规则基类 (抽象).

    触发逻辑:
        drop_pct = (current_nav - prev_close_nav) / prev_close_nav
        if drop_pct <= -threshold: return [RuleResult(...)]

    跳过条件 (silent skip, return []):
        - context.prev_close_nav is None (T+1 首日 / 数据缺失)
        - context.prev_close_nav <= 0 (异常数据, fail-loud 在数据层已 guard)
        - context.portfolio_nav <= 0 (异常数据)

    子类必覆盖: rule_id / severity / threshold (`@property`)

    Invariants:
        action = "alert_only" (批 2 不实盘卖, 批 3 升级)
        code = "" (组合级规则, 非单股)

    关联铁律: 31 (纯计算, 无 IO, prev_close_nav 由 engine 注入).

    Note: `threshold` 采用 `@property @abstractmethod` 确保子类必覆盖 (ABCMeta
    阻止直接实例化 `IntradayPortfolioDropRule()`). `rule_id` / `severity` 本类设
    sentinel 占位值 (子类 override) 以通过 `interface.py::RiskRule.__init_subclass__`
    的 fail-loud 检查 (该检查有 ABCMeta ordering bug, `__abstractmethods__` 填充
    时机晚于 `__init_subclass__` 致无法跳过中间抽象类, 后续 framework-level 修).
    sentinel rule_id 以 `_` 开头标识内部/非注册用途.
    """

    # Sentinel 占位 (子类覆盖, 本类 abstract via @abstractmethod threshold)
    # Safe: ABCMeta blocks instantiation of base (未实现 threshold), 此 sentinel
    # 永不到达 engine.register() (reviewer P3 采纳 code: 明示安全依据)
    rule_id: str = "_intraday_portfolio_drop_abstract_base"
    severity: Severity = Severity.P2  # 占位, 子类覆盖
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    @property
    @abstractmethod
    def threshold(self) -> float:
        """子类必覆盖, 返 [0, 1] 跌幅阈值 (e.g. 0.03 = 3%).

        reviewer P2 驳回 python: `@property @abstractmethod` (property 外 abstractmethod 内)
        是 Python 官方 docs/abc.html 推荐顺序. `@abstractmethod @property` 反向会报
        AttributeError: attribute '__isabstractmethod__' of 'property' objects is not writable
        (property descriptor 无此 slot). 本顺序正确, reviewer 建议失误.
        """

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查组合级 NAV 跌幅, 触发返 1 RuleResult, 未触发 / 数据缺失返 []."""
        # reviewer P1 采纳 code: NaN guard 防 float('nan') 跳过 <=0 检查
        # (NaN <= 0 = False 且 NaN > -threshold = False → 会 spurious trigger + 无效 JSON)
        if (
            context.prev_close_nav is None
            or not math.isfinite(context.prev_close_nav)
            or context.prev_close_nav <= 0
        ):
            return []
        if not math.isfinite(context.portfolio_nav) or context.portfolio_nav <= 0:
            return []

        drop_pct = (context.portfolio_nav - context.prev_close_nav) / context.prev_close_nav
        if drop_pct > -self.threshold:
            # 跌幅未达阈值 (drop_pct > -0.03 表示跌幅不到 3%)
            return []

        return [
            RuleResult(
                rule_id=self.rule_id,
                code="",  # 组合级 (对齐 risk_event_log.code DEFAULT '')
                shares=0,  # alert_only 不下单
                reason=(
                    # reviewer P3 采纳 code: threshold format 统一 :.2% 对齐 drop_pct
                    f"Intraday portfolio drop {drop_pct:.2%} <= -{self.threshold:.2%} "
                    f"(nav={context.portfolio_nav:.2f}, prev_close={context.prev_close_nav:.2f}, "
                    f"positions={len(context.positions)})"
                ),
                metrics={
                    "drop_pct": round(drop_pct, 6),
                    "portfolio_nav": context.portfolio_nav,
                    "prev_close_nav": context.prev_close_nav,
                    "threshold": self.threshold,
                    # reviewer P2 采纳 python: len() 返 int, 不 cast float (metrics dict
                    # 允许混类型; JSON 序列化层处理)
                    "positions_count": len(context.positions),
                },
            )
        ]


# ---------- 3 Concrete Portfolio Drop Rules ----------


class IntradayPortfolioDrop3PctRule(IntradayPortfolioDropRule):
    """组合级盘中跌 3% 告警 (P2 - 信息记录)."""

    rule_id: str = "intraday_portfolio_drop_3pct"
    severity: Severity = Severity.P2

    @property
    def threshold(self) -> float:
        return 0.03


class IntradayPortfolioDrop5PctRule(IntradayPortfolioDropRule):
    """组合级盘中跌 5% 告警 (P1 - 当日响应)."""

    rule_id: str = "intraday_portfolio_drop_5pct"
    severity: Severity = Severity.P1

    @property
    def threshold(self) -> float:
        return 0.05


class IntradayPortfolioDrop8PctRule(IntradayPortfolioDropRule):
    """组合级盘中跌 8% 告警 (P0 - 立即处理, 对齐 scripts/intraday_monitor.py 个股 -8% 阈值的组合级对应)."""

    rule_id: str = "intraday_portfolio_drop_8pct"
    severity: Severity = Severity.P0

    @property
    def threshold(self) -> float:
        return 0.08


# ---------- QMTDisconnectRule ----------


class QMTDisconnectRule(RiskRule):
    """QMT Data Service 断连告警 (盘中每 5min check).

    触发: QMTConnectionReader.is_connected() == False
    Action: alert_only (断连无法下单, 仅能人工介入重连)
    Severity: P0 (关键基础设施失效, 盘中断连意味着 PT 无法执行)

    防泛滥 (plan §5):
        - Rule 本身不做 dedup (纯计算保持)
        - 由 engine.execute 或 wiring 层 Redis 24h TTL dedup (批 2 PR 2 实施)

    关联铁律: 31 (纯规则 delegate Protocol) / 33 (断连 fail-loud alert, 不 silent skip).
    """

    rule_id: str = "qmt_disconnect"
    severity: Severity = Severity.P0
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(self, qmt_reader: QMTConnectionReader) -> None:
        """注入 QMTConnectionReader (Protocol), 单测可 mock.

        Args:
            qmt_reader: 实现 is_connected() 的 reader (e.g. app.core.qmt_client.QMTClient).
        """
        self._reader = qmt_reader

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查 QMT 连接, 断连返 1 RuleResult, 连接正常返 []."""
        if self._reader.is_connected():
            return []

        return [
            RuleResult(
                rule_id=self.rule_id,
                code="",  # 基础设施级, 非单股
                shares=0,  # alert_only
                reason=(
                    "QMT Data Service disconnected (is_connected=False) — "
                    "盘中风控基础设施失效, PT 无法执行调仓, 需人工重启 QMT 连接"
                ),
                metrics={
                    "checked_at_timestamp": context.timestamp.timestamp(),
                    # reviewer P2 采纳 python: len() → int, 不 cast float
                    "positions_count_at_disconnect": len(context.positions),
                    "portfolio_nav_at_disconnect": context.portfolio_nav,
                },
            )
        ]
