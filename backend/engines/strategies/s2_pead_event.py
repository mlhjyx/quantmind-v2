"""MVP 3.2 批 3 — S2 PEAD Event-driven Strategy (DRY_RUN 状态).

PEAD = Post-Earnings Announcement Drift. 经典事件驱动异常: 盈余意外公布后 30 日内
价格持续 drift (EPS surprise 正/负方向).

## 架构决策 (铁律 39 显式)

- **纯计算 (铁律 31)**: 本模块不做 DB IO, earnings_announcements + current_positions
  数据由调用方 (daily_pipeline 批 4) 预加载注入 `ctx.metadata`. 本类
  `generate_signals(ctx)` 是纯函数 (同 metadata in → 同 signals out).
- **绕开 DEPRECATED pead_q1 因子**: Session 33 precondition 实测 `pead_q1` +
  `earnings_surprise_car` 因子 DEPRECATED (Phase 3D ML NO-GO 事件), `sue_pead`
  warning. S2 直接消费 `earnings_announcements.eps_surprise_pct` 原始数据,
  不依赖 factor_registry PEAD 变体, 避免因子重激活阻塞 (独立路径 铁律 23).
- **DRY_RUN 默认**: 启动时 status=DRY_RUN, 只生成 signals 不走 OrderRouter. 7 日
  观察 + 3yr 回测后 manual update_status() 升 LIVE. 保护真金.
- **铁律 16 保持**: S2 不入 SignalComposer (CORE4 等权路径), 是**平行 signal 路径**
  独立评估. 未来 MVP 3.3 OrderRouter 级合并 S1+S2.

## Signal 逻辑 (简)

1. **触发日**: `ctx.metadata['pead_candidates']` 预加载 = 今日应建仓的 (code,
   eps_surprise_pct, trigger_date) 列表, 来自 `earnings_announcements WHERE
   trade_date = ctx.trade_date AND eps_surprise_pct IS NOT NULL AND ts_code IN
   ctx.universe`.
2. **过滤 & 排序**: 过 `eps_surprise_pct >= EPS_SURPRISE_THRESHOLD` (默认 0.30,
   Session 33 Q80 实测 ~0.486, 0.30 稍宽适配 Q60-Q70), clip `EPS_SURPRISE_CAP`
   (默认 3.0 防 outlier, 实测 max=458).
3. **Top-N 选股**: eps_surprise_pct 降序 Top-`TOP_N_PER_TRIGGER_DAY` (默认 5).
4. **持仓过期检查**: `ctx.metadata['current_positions']` 预加载 {code: holding_days},
   holding_days >= HOLDING_DAYS (默认 30) 的持仓生成 sell signal (target_weight=0).
5. **新建仓权重**: target_weight = 1 / MAX_CONCURRENT_POSITIONS (默认 20), 保底
   新建仓不超过 MAX_CONCURRENT - current_active 可容纳额度.

## 历史数据验证

- `earnings_announcements` 实测 207K rows, f_ann_date 2015-04-07 → 2026-04-04.
- 2024: 22K rows / 2025: 23K rows, Q80 eps_surprise_pct = 0.486.
- 预期回测: 3yr (2023-2026) OOS Sharpe TBD, 本批只交付策略实现, 回测见批 3 后续.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from backend.platform._types import Signal
from backend.platform.strategy.interface import (
    RebalanceFreq,
    Strategy,
    StrategyContext,
    StrategyStatus,
)

_logger = logging.getLogger(__name__)


# ─── Fixed UUID for S2 (consistent across boots / deterministic for DB seed) ────
# Generated once (2026-04-24 Session 33), 永久复用.
# S1 UUID = 28fc37e5-2d32-4ada-92e0-41c11a5103d0 (复用当前 live position_snapshot)
# S2 UUID = 下面这个 (全新, 无历史 position_snapshot 冲突)
_S2_STRATEGY_UUID = UUID("a5b27c3f-8e94-4d1a-b0c7-e6f2a9b45d10")


@dataclass(frozen=True)
class S2PEADConfig:
    """S2 策略超参数 (batch 3 default, 可经 strategy_registry.config JSONB 覆盖).

    Attrs:
      eps_surprise_threshold: 最低 EPS surprise 百分比触发 (默认 0.30, i.e. 30%).
        实测 Q80 (top 20%) = 0.486, Q60 ≈ 0.20. 0.30 介于 Q60-Q80 稍偏严.
      eps_surprise_cap: 极端 outlier clip (默认 3.0). 实测 max=458 (除零 edge case).
      top_n_per_trigger_day: 每触发日最多新建仓数 (默认 5). 实测每日 ~17 候选 at Q80,
        Top-5 可控仓位敞口.
      max_concurrent_positions: 同一时刻最大并发持仓 (默认 20). 以 30 日持仓 × 每日新
        5 个估算, 峰值可达 150, 需硬限. 20 是初始保守值, 批 3 实测调优.
      holding_days: 持仓天数 (默认 30, PEAD 标准窗口).
    """

    eps_surprise_threshold: float = 0.30
    eps_surprise_cap: float = 3.0
    top_n_per_trigger_day: int = 5
    max_concurrent_positions: int = 20
    holding_days: int = 30


class S2PEADEvent(Strategy):
    """MVP 3.2 批 3 — PEAD Event-driven Strategy (DRY_RUN default).

    纯计算. DB 数据由 daily_pipeline 批 4 预加载注入 ctx.metadata:
      - ctx.metadata['pead_candidates']: list[dict]
          [{'code': str, 'eps_surprise_pct': float, 'trigger_date': date}, ...]
        来自 earnings_announcements WHERE trade_date = ctx.trade_date AND
        eps_surprise_pct IS NOT NULL AND ts_code IN universe
      - ctx.metadata['current_positions']: dict[str, dict]
          {code: {'holding_days': int, 'weight': float, 'entry_date': date}, ...}
        只含 S2 策略自己的持仓 (per-strategy position_snapshot 按 strategy_id filter).

    Usage:
      >>> s2 = S2PEADEvent()
      >>> ctx = StrategyContext(trade_date=date(2026, 4, 28), capital=Decimal("500000"),
      ...                       universe=["600519.SH", ...], regime="neutral",
      ...                       metadata={"pead_candidates": [...], "current_positions": {...}})
      >>> signals = s2.generate_signals(ctx)
    """

    # ─── Class attrs (required by Strategy ABC) ─────────────────
    # reviewer LOW (PR #70): ClassVar 显式声明防子类/instance shadow, 避免 class-level
    # mutable default 陷阱 (若未来 append 会污染所有 instance).
    strategy_id: ClassVar[str] = str(_S2_STRATEGY_UUID)
    name: ClassVar[str] = "s2_pead_event"
    # 用 tuple (immutable) 而非 list 防误改; register() 时转 list 兼容 JSONB
    factor_pool: ClassVar[list[str]] = []  # 不依赖 factor_registry 因子, 直接消费 announcements
    rebalance_freq: ClassVar[RebalanceFreq] = RebalanceFreq.EVENT
    status: ClassVar[StrategyStatus] = StrategyStatus.DRY_RUN
    description: ClassVar[str] = (
        "PEAD Event-driven Strategy — f_ann_date+1 买入 Top-5 eps_surprise_pct>=Q threshold, "
        "持仓 30 日 sell. DRY_RUN 默认, 7 日观察后手工 update_status 升 LIVE."
    )
    # 重命名为 default_config 避免与 __init__ 形参 config 混淆 (reviewer LOW)
    default_config: ClassVar[dict[str, Any]] = {}

    def __init__(self, config: S2PEADConfig | None = None) -> None:
        self._config = config or S2PEADConfig()

    # ─── Strategy ABC impl ──────────────────────────────────────

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        """生成当日 S2 PEAD 信号 (buy 新 Q80 surprise Top-5 + sell 持仓 >= 30 日).

        Returns:
          Signal 列表, 包含 buy (target_weight>0) + sell (target_weight=0).
          空列表合法 (无 PEAD trigger 也无 expired 持仓).

        Raises:
          KeyError: ctx.metadata 缺 'pead_candidates' / 'current_positions' key
            (调用方负责预加载, fail-loud 铁律 33)
        """
        # Validate metadata pre-conditions (调用方必须预加载)
        if "pead_candidates" not in ctx.metadata:
            raise KeyError(
                "S2PEADEvent.generate_signals: ctx.metadata 缺 'pead_candidates' key. "
                "daily_pipeline 批 4 调用前必须预加载 earnings_announcements (铁律 31 pure-calc)."
            )
        if "current_positions" not in ctx.metadata:
            raise KeyError(
                "S2PEADEvent.generate_signals: ctx.metadata 缺 'current_positions' key. "
                "daily_pipeline 批 4 调用前必须查 per-strategy position_snapshot."
            )

        candidates: list[dict[str, Any]] = ctx.metadata["pead_candidates"]
        current_positions: dict[str, dict[str, Any]] = ctx.metadata["current_positions"]

        signals: list[Signal] = []

        # Step 1: 关闭过期持仓 (holding_days >= HOLDING_DAYS)
        expired_codes = self._find_expired_positions(current_positions)
        for code in expired_codes:
            signals.append(
                Signal(
                    strategy_id=self.strategy_id,
                    code=code,
                    target_weight=0.0,  # sell
                    score=0.0,
                    trade_date=ctx.trade_date,
                    metadata={
                        "action": "sell_expired",
                        "holding_days": current_positions[code].get("holding_days", 0),
                    },
                )
            )

        # Step 2: 计算可容纳新仓数 (max_concurrent - (current - expired))
        active_after_expiry = len(current_positions) - len(expired_codes)
        available_slots = max(0, self._config.max_concurrent_positions - active_after_expiry)
        new_buy_slots = min(self._config.top_n_per_trigger_day, available_slots)

        if new_buy_slots <= 0 or not candidates:
            # 持仓满或无候选, 只有 sell signals
            _logger.info(
                "S2 generate_signals: trade_date=%s expired=%d active_after=%d "
                "available_slots=%d candidates=%d -> no new buys",
                ctx.trade_date,
                len(expired_codes),
                active_after_expiry,
                available_slots,
                len(candidates),
            )
            return signals

        # Step 3: Filter + clip + sort candidates
        # reviewer LOW (PR #70): universe → set for O(1) lookup (scale-safe)
        universe_set = set(ctx.universe)

        # reviewer MEDIUM (PR #70): 不修改 caller 的 dict, 用新 list of tuples
        # (code, raw_pct, clipped_pct, trigger_date). float() 失败 per-candidate skip
        # 避免整 generate_signals crash (铁律 33 fail-safe per candidate).
        enriched: list[tuple[str, float, float, Any]] = []
        for c in candidates:
            code = c.get("code")
            if code is None or code not in universe_set or code in current_positions:
                continue
            raw_val = c.get("eps_surprise_pct")
            if raw_val is None:
                continue
            try:
                raw_pct = float(raw_val)
            except (ValueError, TypeError):
                _logger.warning(
                    "S2 skip candidate code=%s: eps_surprise_pct non-numeric (%r)",
                    code,
                    raw_val,
                )
                continue
            if raw_pct < self._config.eps_surprise_threshold:
                continue
            clipped = min(raw_pct, self._config.eps_surprise_cap)
            enriched.append((code, raw_pct, clipped, c.get("trigger_date", ctx.trade_date)))

        # Sort desc by clipped score (stable sort preserves input order for ties)
        enriched.sort(key=lambda t: t[2], reverse=True)

        # Step 4: Top-N 取新建仓 (受 available_slots 限制)
        picks = enriched[:new_buy_slots]

        # Step 5: 等权分配 target_weight = 1 / max_concurrent_positions (稳定每股敞口)
        weight_per_position = 1.0 / self._config.max_concurrent_positions
        for code, raw_pct, clipped, trigger_date in picks:
            signals.append(
                Signal(
                    strategy_id=self.strategy_id,
                    code=code,
                    target_weight=weight_per_position,
                    score=clipped,
                    trade_date=ctx.trade_date,
                    metadata={
                        "action": "buy_pead",
                        "eps_surprise_pct_raw": raw_pct,
                        "eps_surprise_pct_clipped": clipped,
                        "trigger_date": str(trigger_date),
                    },
                )
            )

        _logger.info(
            "S2 generate_signals: trade_date=%s expired=%d new_buys=%d total_signals=%d",
            ctx.trade_date,
            len(expired_codes),
            len(picks),
            len(signals),
        )
        return signals

    def validate_signals(
        self, signals: list[Signal], ctx: StrategyContext
    ) -> list[Signal]:
        """Pass-through validation — 批 3 简化, 靠 ctx.universe 已过滤 BJ/ST/停牌.

        后续批次可接入 Platform 公共 validator (流动性 / 涨跌停).
        """
        validated: list[Signal] = []
        for sig in signals:
            # 只过: sell signal (target_weight=0) 不需 universe 验 (已持仓必须能 sell)
            # buy signal 必须 code ∈ universe
            if sig.target_weight == 0.0:
                validated.append(sig)
                continue
            if sig.code not in ctx.universe:
                _logger.warning(
                    "S2 validate_signals: skip buy signal code=%s not in universe",
                    sig.code,
                )
                continue
            validated.append(sig)
        return validated

    # ─── Internal helpers ───────────────────────────────────────

    def _find_expired_positions(
        self, current_positions: dict[str, dict[str, Any]]
    ) -> list[str]:
        """Return codes with holding_days >= HOLDING_DAYS."""
        return [
            code
            for code, meta in current_positions.items()
            if meta.get("holding_days", 0) >= self._config.holding_days
        ]
