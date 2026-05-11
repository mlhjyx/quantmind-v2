"""LimitDownDetection + NearLimitDown — 跌停 / 接近跌停 detection (S5 L1 实时化).

设计动机 (4-29 688121.SH 卓然新能 跌停教训):
  - 跌停板无法卖出 (无买盘), alert_only, 不挂 sell 单
  - NearLimitDown 在跌停前预警, 准备尾盘限价卖单

阈值配置 (RT_* 环境变量, config_guard 启动时校验):
  - RT_LIMIT_DOWN_THRESHOLD_MAIN=0.099   主板 9.9%
  - RT_LIMIT_DOWN_THRESHOLD_STAR=0.198  科创/创业 19.8%
  - RT_NEAR_LIMIT_DOWN_THRESHOLD=0.095  跌停前预警 9.5%

关联铁律: 24 (单一职责) / 31 (纯计算无 IO) / 33 (fail-loud)
"""

from __future__ import annotations

import logging
from typing import Final, Literal

from backend.qm_platform._types import Severity

from ...interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)

# 默认阈值常量 (可被 .env 覆盖)
_DEFAULT_LIMIT_DOWN_MAIN: Final[float] = 0.099
_DEFAULT_LIMIT_DOWN_STAR: Final[float] = 0.198
_DEFAULT_NEAR_LIMIT_DOWN: Final[float] = 0.095


def _is_star_or_kcb(code: str) -> bool:
    """判断是否科创/创业 (30x/68x)."""
    prefix = code[:3]
    return prefix in ("300", "301", "688")


class LimitDownDetection(RiskRule):
    """跌停检测 — 股价触及涨跌停限制 ±0.01%.

    触发: 跌幅 >= 对应板块涨跌停限制 (主板 9.9%, 科创/创业 19.8%)
    Action: alert_only (跌停板无买盘, 不挂 sell, 沿用 4-29 688121 教训)
    Severity: P0 (立即处理)

    evaluate 通过 RiskContext.realtime 读取每只持仓股的 prev_close.
    若 realtime 缺失对某股的数据, 该股 silent skip.
    """

    rule_id: str = "limit_down_detection"
    severity: Severity = Severity.P0
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self,
        threshold_main: float = _DEFAULT_LIMIT_DOWN_MAIN,
        threshold_star: float = _DEFAULT_LIMIT_DOWN_STAR,
    ) -> None:
        self._threshold_main = threshold_main
        self._threshold_star = threshold_star

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.realtime is None:
            return []

        results: list[RuleResult] = []
        for pos in context.positions:
            if pos.current_price <= 0 or pos.shares <= 0:
                continue

            tick = context.realtime.get(pos.code)
            if tick is None:
                continue

            prev_close = tick.get("prev_close")
            if prev_close is None or prev_close <= 0:
                continue

            drop_pct = (pos.current_price - prev_close) / prev_close
            if drop_pct > 0:
                continue  # 上涨不触发

            threshold = self._threshold_star if _is_star_or_kcb(pos.code) else self._threshold_main
            if drop_pct > -threshold:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"LimitDownDetection: {pos.code} 触发跌停 "
                        f"(跌幅={drop_pct:.2%} <= -{threshold:.1%}, "
                        f"price={pos.current_price:.2f}, prev_close={prev_close:.2f})"
                    ),
                    metrics={
                        "drop_pct": round(drop_pct, 6),
                        "current_price": pos.current_price,
                        "prev_close": prev_close,
                        "threshold": threshold,
                        "is_star_or_kcb": _is_star_or_kcb(pos.code),
                        "shares": float(pos.shares),
                    },
                )
            )
        return results


class NearLimitDown(RiskRule):
    """接近跌停预警 — 跌幅超过 9.5% (主板) / 19.5% (科创/创业).

    触发: 跌幅 >= near_limit_down_threshold (默认 9.5%)
    Action: alert_only (准备尾盘限价卖单, 非立即 sell)
    Severity: P0 (critical window 内 actionable 信息)

    LimitDownDetection 与 NearLimitDown 互斥: 若已触发跌停, 本规则不重复告警.
    实现: 若跌停已触发 (当前价 <= 跌停阈值 * prev_close), 本规则 skip.
    """

    rule_id: str = "near_limit_down"
    severity: Severity = Severity.P0
    action: Literal["sell", "alert_only", "bypass"] = "alert_only"

    def __init__(
        self,
        threshold_near: float = _DEFAULT_NEAR_LIMIT_DOWN,
        threshold_main: float = _DEFAULT_LIMIT_DOWN_MAIN,
        threshold_star: float = _DEFAULT_LIMIT_DOWN_STAR,
    ) -> None:
        self._threshold_near = threshold_near
        self._threshold_main = threshold_main
        self._threshold_star = threshold_star

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.realtime is None:
            return []

        results: list[RuleResult] = []
        for pos in context.positions:
            if pos.current_price <= 0 or pos.shares <= 0:
                continue

            tick = context.realtime.get(pos.code)
            if tick is None:
                continue

            prev_close = tick.get("prev_close")
            if prev_close is None or prev_close <= 0:
                continue

            drop_pct = (pos.current_price - prev_close) / prev_close
            if drop_pct > 0:
                continue  # 上涨不触发

            # 判断是否已触发跌停 (互斥)
            limit_down_threshold = (
                self._threshold_star if _is_star_or_kcb(pos.code) else self._threshold_main
            )
            if drop_pct <= -limit_down_threshold:
                continue  # 已跌停, 由 LimitDownDetection 处理

            if drop_pct > -self._threshold_near:
                continue

            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    code=pos.code,
                    shares=0,
                    reason=(
                        f"NearLimitDown: {pos.code} 接近跌停 "
                        f"(跌幅={drop_pct:.2%} <= -{self._threshold_near:.2%}, "
                        f"price={pos.current_price:.2f}, prev_close={prev_close:.2f})"
                    ),
                    metrics={
                        "drop_pct": round(drop_pct, 6),
                        "current_price": pos.current_price,
                        "prev_close": prev_close,
                        "threshold_near": self._threshold_near,
                        "limit_down_threshold": limit_down_threshold,
                        "is_star_or_kcb": _is_star_or_kcb(pos.code),
                        "shares": float(pos.shares),
                    },
                )
            )
        return results
