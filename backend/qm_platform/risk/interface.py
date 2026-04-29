"""Framework Risk — 纯接口契约 (MVP 3.1 批 1).

本模块 0 IO, 0 DB, 0 Redis, 0 xtquant (铁律 31 Platform Engine 纯计算/纯契约).
所有 IO 由 concrete 实现 (engine.py / sources/ / rules/) + Application 层 (daily_pipeline) 承担.

对齐 MVP_3_1_batch_1_plan.md §3 和 ADR-010 D3.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from backend.qm_platform._types import Severity

# ---------- Value Objects (frozen, 不可变) ----------


@dataclass(frozen=True)
class Position:
    """单股持仓快照 (含 entry / peak / current 合并对象).

    Args:
      code: DB 代码带后缀 (e.g. "600519.SH"). 不接受裸 6 位.
      shares: 整手股数 (>= 0, 0 表示已平仓待清理).
      entry_price: 加权平均买入成本 (0 表示未能计算, rule 应 skip).
      peak_price: 持仓期间历史最高收盘价. 若 < entry_price, 视为异常 (无亏损 peak), rule 应 skip.
      current_price: Redis `market:latest:{code}` 实时价 (60s 刷新).
      entry_date: 持仓首日 = MIN(buy.trade_date) since last sell (Phase 1.5a, Session 44).
        None 表示无 trade_log 记录 (旧持仓 backfill 缺数据 / 未建仓), 依赖 entry_date 的 rule
        应 skip. 用于 future PositionHoldingTimeRule (持仓 ≥ 30 天 P2 警示) +
        NewPositionVolatilityRule (新仓 < 7 天高波动 P1).
    """

    code: str
    shares: int
    entry_price: float
    peak_price: float
    current_price: float
    entry_date: date | None = None


@dataclass(frozen=True)
class RiskContext:
    """RiskRule.evaluate 输入, 纯数据容器.

    Args:
      strategy_id: 唯一策略标识 (UUID 字符串).
      execution_mode: "paper" | "live", 从 settings.EXECUTION_MODE 注入 (ADR-008).
      timestamp: tz-aware UTC datetime (铁律 41).
      positions: 持仓 tuple (frozen 保不可变, 非 list). 空 tuple = 空仓.
      portfolio_nav: 组合总资产 (cash + 持仓市值).
      prev_close_nav: 昨日收盘 NAV, intraday 组合级规则用 (批 2), 批 1 可 None.
    """

    strategy_id: str
    execution_mode: Literal["paper", "live"]  # reviewer P3-2 采纳: mypy 提前捕错值
    timestamp: datetime
    positions: tuple[Position, ...]
    portfolio_nav: float
    prev_close_nav: float | None = None


@dataclass(frozen=True)
class RuleResult:
    """RiskRule.evaluate 输出的单个触发事件.

    Args:
      rule_id: 规则唯一标识 (e.g. "pms_l1", "intraday_portfolio_drop_5pct"). 对齐 risk_event_log.rule_id.
      code: 触发股票代码. 组合级规则用 "" (对齐 risk_event_log DEFAULT).
      shares: action=sell 时的股数 (>= 0); alert_only / bypass 时 0.
      reason: 人类可读触发原因 (写入 risk_event_log.reason).
      metrics: 数值指标 JSON (pnl_pct / dd_pct / peak_price / ...), 写入 context_snapshot.
    """

    rule_id: str
    code: str
    shares: int
    reason: str
    metrics: dict[str, float]


# ---------- 错误类型 ----------


class PositionSourceError(RuntimeError):
    """PositionSource.load 失败 (Redis 断连 / 解析异常 / DB 超时 / ...).

    Engine 捕此类异常做 primary → fallback 切换 (铁律 33 fail-loud, 非 return []).
    """


# ---------- Protocol: PositionSource ----------


class PositionSource(Protocol):
    """持仓数据源抽象 (duck-typing Protocol, 非 ABC).

    实现 (见 sources/):
      - QMTPositionSource: Redis portfolio:current (primary, 60s 刷新)
      - DBPositionSource: position_snapshot + trade_log + klines_daily (fallback)

    失败必 raise PositionSourceError (非 return [], 铁律 33). Engine._load_positions
    捕后切 fallback + P1 钉钉告警.
    """

    def load(self, strategy_id: str, execution_mode: str) -> list[Position]:
        """加载当前持仓. 失败 raise PositionSourceError."""
        ...


# ---------- ABC: RiskRule ----------


class RiskRule(ABC):
    """风险规则基类 — 所有 PMS / intraday / CB 规则的父类.

    子类必设 3 个类属性 (__init_subclass__ 启动时 fail-loud 检查):
      - rule_id: str        unique, 对齐 risk_event_log.rule_id CHECK 值域
      - severity: Severity  P0 / P1 / P2 / INFO (复用 platform._types.Severity)
      - action: Literal["sell", "alert_only", "bypass"]
          - "sell": Engine 直调 broker.sell() + log + 通知
          - "alert_only": Engine 仅 log + 通知 (不下单, intraday_monitor + emergency 用)
          - "bypass": Engine 仅 log (调试/演练用)

    关联铁律:
      - 24: 单一职责, 一规则一文件一类 (rules/pms.py 特例合 3 规则, 因 L1/L2/L3 共算)
      - 31: rule.evaluate 纯函数, 不 IO (Position 已含 current_price)
      - 33: 触发 return [RuleResult], 不触发 return [] (不 raise)
    """

    rule_id: str
    severity: Severity
    action: Literal["sell", "alert_only", "bypass"]

    def root_rule_id_for(self, triggered_rule_id: str) -> str:
        """Declare ownership of a triggered_rule_id.

        reviewer P1-3 采纳: 原实现把 "pms_l1→pms" 映射硬编码在 engine._root_rule_id
        函数, 批 2/3 每加新规则都需改中心函数. 改用方法可被子类覆盖, 扩展点属于
        Rule 本身而非 Engine.

        Semantic (v2, fixes reviewer fix edge case):
          - Return `self.rule_id` if this rule owns (produces) the triggered_rule_id.
          - Return `triggered_rule_id` unchanged (passthrough) if NOT owned.
        _root_rule_id_via_rules looks for `transformed != triggered_id AND
        transformed == rule.rule_id` to identify ownership (not just equality,
        which would match every rule due to default passthrough).

        默认实现 passthrough (rule 不声明拥有 triggered_id). 子类 PMSRule 覆盖
        返 "pms" 当 triggered_id 符合 pms_l{N} pattern, 否则 passthrough.
        """
        return triggered_rule_id

    @abstractmethod
    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查规则, 返触发事件列表. 未触发返 [].

        输入:
          context: RiskContext (不可变)

        输出:
          - 未触发: []
          - 触发 N 个 position/组合级事件: [RuleResult(...)] × N

        禁忌:
          - 不 raise (内部异常必被子类捕并降为 log + return [])
          - 不 IO (不连 DB / Redis / HTTP)
          - 不修改 context (frozen dataclass 已保)
        """

    def __init_subclass__(cls, **kwargs: object) -> None:
        """子类注册时强制检查 3 个类属性齐全 (铁律 33 启动时 fail-loud).

        Raises:
          TypeError: 子类缺 rule_id / severity / action
        """
        super().__init_subclass__(**kwargs)

        # 允许中间抽象基类 (如未来 PortfolioLevelRule(RiskRule))
        # 通过 `__abstractmethods__` 非空判断是否是最终 concrete class.
        # 注: ABCMeta 在 __init_subclass__ 完成后才填 __abstractmethods__, 此处用
        # getattr + 默认 frozenset() 处理属性未就绪的 edge case.
        if getattr(cls, "__abstractmethods__", frozenset()):
            return

        required = {
            "rule_id": (str,),
            "severity": (Severity,),
            "action": (str,),  # Literal 运行时是 str
        }
        for attr, types in required.items():
            if not hasattr(cls, attr):
                raise TypeError(
                    f"RiskRule subclass {cls.__name__} missing required class attr '{attr}'"
                )
            val = getattr(cls, attr)
            if not isinstance(val, types):
                raise TypeError(
                    f"RiskRule subclass {cls.__name__}.{attr} must be {types}, got {type(val)}"
                )
        # action 必在 {sell, alert_only, bypass}
        if cls.action not in ("sell", "alert_only", "bypass"):
            raise TypeError(
                f"RiskRule subclass {cls.__name__}.action must be "
                f"'sell' | 'alert_only' | 'bypass', got {cls.action!r}"
            )
