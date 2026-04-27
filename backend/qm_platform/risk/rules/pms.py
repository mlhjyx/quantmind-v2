"""PMSRule — 阶梯利润保护 L1/L2/L3 (迁自 app.services.pms_engine.check_protection).

决策: 单 PMSRule 类替代 3 类 (PMSLevel1/2/3Rule), 内部按阈值高低顺序命中.
原因 (MVP_3_1_batch_1_plan.md §5):
  - pms_engine.check_protection for-loop L1→L2→L3 早退已是该语义
  - 3 类分开每个 .evaluate 都要 loop positions, 冗余 3 次
  - rule_id 按 trigger level 动态生成 ("pms_l1" / "pms_l2" / "pms_l3")

纯计算 (铁律 31): 不 IO, context.positions 已含 entry/peak/current, 规则只做数学.

阈值来源: app.config.settings.PMS_LEVEL{1,2,3}_{GAIN,DRAWDOWN}.
本模块不 import settings, 通过 constructor 注入 (Platform 不跨 App 边界, 铁律 34 SSOT).

关联铁律: 24 / 31 / 33 / 34
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Literal

from backend.qm_platform._types import Severity

from ..interface import RiskContext, RiskRule, RuleResult

logger = logging.getLogger(__name__)

# LL-081 zombie 防御 (2026-04-27 真生产首日教训):
# 当持仓数 > MIN_POSITIONS 且 skip_ratio > THRESHOLD 时, log P1 warning 触发监控.
# 单股 skip (entry_price=0 等数据问题) OK, 但 19/19 全 skip 是系统性故障 (QMT 数据失联).
SKIP_RATIO_ALERT_THRESHOLD: Final[float] = 0.6  # 60% 严格大于触发 (>0.6, 即 ≥ 61%)
SKIP_RATIO_MIN_POSITIONS: Final[int] = 5  # 持仓数门槛: 持仓 ≤ 5 时 skip 视为噪声不告警 (避免 data quality 单股噪声)


@dataclass(frozen=True)
class PMSThreshold:
    """单层保护阈值 (frozen, 不可变)."""

    level: int
    min_gain: float         # 最低浮盈触发阈 (e.g. 0.30 = +30%)
    max_drawdown: float     # 最低回撤触发阈 (e.g. 0.15 = -15% from peak)


# 默认阈值 (对齐 CLAUDE.md §PMS 规则 + .env PMS_LEVEL{1,2,3}_*)
_DEFAULT_LEVELS: tuple[PMSThreshold, ...] = (
    PMSThreshold(level=1, min_gain=0.30, max_drawdown=0.15),
    PMSThreshold(level=2, min_gain=0.20, max_drawdown=0.12),
    PMSThreshold(level=3, min_gain=0.10, max_drawdown=0.10),
)


class PMSRule(RiskRule):
    """阶梯利润保护规则 (Level 1 最严格, Level 3 最宽松).

    单 position 按 L1→L2→L3 顺序 check, 首次命中即 append 停止 (保留 pms_engine 原语义).

    Args:
        levels: 阈值配置, None 则用 _DEFAULT_LEVELS. 支持 .env 驱动注入 (daily_pipeline wire 时从 settings 读).

    Invariants:
        rule_id = "pms" (基础), RuleResult.rule_id 动态改为 "pms_l{N}" 根据触发级别
        severity = P1 (对齐 ADR-010 D3: PMS 触发通常 P1 告警)
        action = "sell" (主动卖出, 不是 alert_only)
    """

    rule_id: str = "pms"
    severity: Severity = Severity.P1
    action: Literal["sell", "alert_only", "bypass"] = "sell"

    def __init__(self, levels: tuple[PMSThreshold, ...] | None = None) -> None:
        self._levels = levels if levels is not None else _DEFAULT_LEVELS
        # Precondition: levels 按 min_gain 降序 (L1 最严, L3 最宽); 防配置错误导致 L1 被 L3 早退吞掉
        if not all(
            self._levels[i].min_gain >= self._levels[i + 1].min_gain
            for i in range(len(self._levels) - 1)
        ):
            raise ValueError(
                f"PMSRule levels must be sorted by min_gain DESC, got {self._levels!r}"
            )
        # reviewer P2-4 采纳: max_drawdown 同向单调 (L1 >= L2 >= L3).
        # 配错如 L1(dd=0.05) L2(dd=0.15) → L2 更难触发 (要求更大回撤), 语义颠倒.
        if not all(
            self._levels[i].max_drawdown >= self._levels[i + 1].max_drawdown
            for i in range(len(self._levels) - 1)
        ):
            raise ValueError(
                f"PMSRule levels must be sorted by max_drawdown DESC, got {self._levels!r}"
            )

    def root_rule_id_for(self, triggered_rule_id: str) -> str:
        """reviewer P1-3 配套: PMSRule 触发 RuleResult.rule_id='pms_l{N}', 反查 root='pms'.

        非 pms_l{N} pattern 走 passthrough (不声明拥有此 triggered_id), 对齐 interface.py
        新语义 (v2) — 避免 PMSRule 被误判为所有 unknown 触发 id 的 owner.
        """
        if triggered_rule_id.startswith("pms_l") and triggered_rule_id[5:].isdigit():
            return "pms"
        return triggered_rule_id

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        """检查每个 position 是否触发阶梯保护.

        跳过条件 (对齐 pms_engine.check_protection L108-110):
            - entry_price <= 0 (未建仓 / 老 paper 命名空间 avg_cost=0)
            - peak_price <= 0 (异常数据)
            - current_price <= 0 (Redis 无价)

        LL-081 fail-loud (2026-04-27 真生产首日教训):
            大比例 skip (>60% with > 5 持仓) → logger.warning P1, 防 zombie 期间
            19/19 silent skip 误报"健康 0 触发". 单股 skip 仍 silent (数据质量问题).
        """
        results: list[RuleResult] = []
        skipped_invalid_data: int = 0  # reviewer python P3 采纳: 显式 type annot 提示 mypy
        for pos in context.positions:
            if pos.entry_price <= 0 or pos.peak_price <= 0 or pos.current_price <= 0:
                skipped_invalid_data += 1
                continue

            # peak 纳入 current 扩展 (当前价可能更高, 同 pms_engine.check_all_positions L268)
            effective_peak = max(pos.peak_price, pos.current_price)

            unrealized_pnl = (pos.current_price - pos.entry_price) / pos.entry_price
            drawdown = (effective_peak - pos.current_price) / effective_peak

            triggered_level: PMSThreshold | None = None
            for lvl in self._levels:
                if unrealized_pnl >= lvl.min_gain and drawdown >= lvl.max_drawdown:
                    triggered_level = lvl
                    break

            if triggered_level is None:
                continue

            results.append(
                RuleResult(
                    rule_id=f"pms_l{triggered_level.level}",
                    code=pos.code,
                    shares=pos.shares,
                    reason=(
                        f"PMS L{triggered_level.level} triggered: "
                        f"gain={unrealized_pnl:.2%} >= {triggered_level.min_gain:.0%} "
                        f"and drawdown={drawdown:.2%} >= {triggered_level.max_drawdown:.0%} "
                        f"(entry={pos.entry_price:.4f}, peak={effective_peak:.4f}, "
                        f"current={pos.current_price:.4f})"
                    ),
                    metrics={
                        "level": float(triggered_level.level),
                        "entry_price": pos.entry_price,
                        "peak_price": effective_peak,
                        "current_price": pos.current_price,
                        "unrealized_pnl_pct": round(unrealized_pnl, 6),
                        "drawdown_from_peak_pct": round(drawdown, 6),
                        "min_gain_threshold": triggered_level.min_gain,
                        "max_drawdown_threshold": triggered_level.max_drawdown,
                    },
                )
            )

        # LL-081 fail-loud: 大比例 skip 必告警 (zombie 期 19/19 silent skip 教训).
        # 单股 / 少股 skip OK (data quality 噪声), 但 > MIN_POSITIONS 持仓且 ratio > THRESHOLD
        # 是系统性故障 — QMT 数据失联 / paper-live 命名空间漂移 / Redis market:latest:* 全过期.
        # logger.warning 触发钉钉监控 + 后续 PR-X3 ServicesHealthCheck 也会兜底捕获.
        # 与 PR-X1 (qmt_data_service SETEX heartbeat) 协同: PR-X1 修 root cause (TTL),
        # 本告警保留 defense-in-depth — 即便 TTL 修好, 其他 zombie 通道 (命名空间漂移 /
        # broker hang on query_positions) 仍可触发本 alert. 不要因 PR-X1 修好就删除本段.
        total_positions = len(context.positions)
        # reviewer python P2 + code P2-1 采纳: 显式 ZeroDivisionError 防御 (隐式短路求值
        # 依赖常量语义脆弱, 未来若 SKIP_RATIO_MIN_POSITIONS 改为 0 即 div by 0).
        if total_positions == 0:
            return results
        if (
            total_positions > SKIP_RATIO_MIN_POSITIONS
            and skipped_invalid_data / total_positions > SKIP_RATIO_ALERT_THRESHOLD
        ):
            logger.warning(
                "PMSRule skip 大比例 %d/%d (%.0f%%) — 疑 QMT 数据失联 / Redis market:latest:* "
                "全过期 / paper-live 命名空间漂移. (LL-081 zombie 模式 fail-loud).",
                skipped_invalid_data,
                total_positions,
                100 * skipped_invalid_data / total_positions,
            )

        return results
