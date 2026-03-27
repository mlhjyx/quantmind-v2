"""RegimeModifier — 基于市场状态的仓位缩放调节器。

R3 §6.2 Layer 3: 市场regime仓位缩放（Risk Overlay）。

调节逻辑:
- risk_off (熊市): 全部持仓 × 0.3（缩减到30%仓位）
- 震荡/中性: 全部持仓 × 0.7
- risk_on (牛市): 全部持仓 × 1.0（满仓，不放大）

状态来源优先级:
1. HMMRegimeDetector（regime_detector.py）— 需要历史数据 ≥ 252日
2. VolRegime fallback（vol_regime.py）— 数据不足时
3. 常数1.0 fallback — 完全无数据时

设计文档对照:
- docs/research/R3_multi_strategy_framework.md §6.2 / §7.2
- backend/engines/regime_detector.py（HMM 2-state）
- backend/engines/vol_regime.py（波动率缩放）
- DESIGN_V5.md §9.5 MA120牛熊判定（规则版fallback）
"""

import logging

import pandas as pd

from engines.base_strategy import StrategyContext
from engines.modifiers.base import ModifierBase, ModifierResult

logger = logging.getLogger(__name__)

# 各状态的仓位缩放系数（R3 §6.2 Layer 3设计值）
_SCALE_RISK_ON: float = 1.0  # 牛市/risk-on: 满仓
_SCALE_NEUTRAL: float = 0.7  # 震荡: 70%仓位
_SCALE_RISK_OFF: float = 0.3  # 熊市/risk-off: 30%仓位


class RegimeModifier(ModifierBase):
    """基于HMM市场状态的全仓位缩放调节器。

    与VolRegime的关键区别:
    - Vol Regime: 基于波动率水平连续缩放 [0.5, 2.0]
    - Regime Modifier: 基于HMM状态离散缩放（risk_on/neutral/risk_off）
    - 本类封装了HMM→Vol→常数的三级fallback逻辑

    config可选字段:
        scale_risk_on: float      牛市缩放系数，默认1.0
        scale_neutral: float      震荡缩放系数，默认0.7
        scale_risk_off: float     熊市缩放系数，默认0.3
        min_hmm_samples: int      HMM最少训练样本数，默认252
        use_hmm: bool             是否启用HMM，默认True（False=只用VolRegime）
        benchmark_code: str       基准指数代码，默认'000300.SH'
    """

    def __init__(self, config: dict) -> None:
        super().__init__(
            name="regime_modifier",
            config=config,
            clip_range=(0.0, 1.0),  # 仓位缩放不超过1.0（不加杠杆）
        )
        self._scale_risk_on = config.get("scale_risk_on", _SCALE_RISK_ON)
        self._scale_neutral = config.get("scale_neutral", _SCALE_NEUTRAL)
        self._scale_risk_off = config.get("scale_risk_off", _SCALE_RISK_OFF)
        self._min_hmm_samples = config.get("min_hmm_samples", 252)
        self._use_hmm = config.get("use_hmm", True)
        self._benchmark_code = config.get("benchmark_code", "000300.SH")

    def should_trigger(self, context: StrategyContext) -> bool:
        """Regime调节每个调仓日都触发（状态持续有效）。"""
        return True

    def compute_adjustments(
        self,
        base_weights: dict[str, float],
        context: StrategyContext,
    ) -> ModifierResult:
        """计算仓位缩放系数，对所有持仓个股均匀应用。

        Args:
            base_weights: 核心策略目标权重 {code: weight}
            context: 运行时上下文（需conn访问CSI300历史数据）

        Returns:
            ModifierResult: 所有持仓code的调节因子均为同一缩放系数
        """
        warnings: list[str] = []

        scale, state, source = self._get_regime_scale(context, warnings)

        # 对所有持仓个股统一应用同一缩放系数
        adjustment_factors = {code: scale for code in base_weights}

        reasoning = f"市场状态={state}, 缩放系数={scale:.2f}, 来源={source}"
        logger.info(f"[RegimeModifier] {reasoning}")

        return ModifierResult(
            adjustment_factors=adjustment_factors,
            triggered=True,
            reasoning=reasoning,
            warnings=warnings,
        )

    def _get_regime_scale(
        self,
        context: StrategyContext,
        warnings: list[str],
    ) -> tuple[float, str, str]:
        """获取当前市场状态和缩放系数（三级fallback）。

        Returns:
            (scale, state_name, source_name)
        """
        # ── Level 1: HMM检测 ──
        if self._use_hmm:
            try:
                closes = self._fetch_benchmark_closes(context)
                if closes is not None and len(closes) >= self._min_hmm_samples:
                    from engines.regime_detector import HMMRegimeDetector

                    detector = HMMRegimeDetector()
                    result = detector.fit_predict(closes)
                    if result is not None:
                        scale = self._regime_to_scale(result.state)
                        return scale, result.state, "hmm"
            except Exception as exc:
                msg = f"HMM检测失败: {exc}，降级到VolRegime"
                logger.warning(f"[RegimeModifier] {msg}")
                warnings.append(msg)

        # ── Level 2: VolRegime fallback ──
        try:
            closes = self._fetch_benchmark_closes(context)
            if closes is not None and len(closes) >= 21:
                from engines.vol_regime import calc_vol_regime

                vol_scale = calc_vol_regime(closes)
                # VolRegime输出[0.5, 2.0]，映射到三状态
                state, scale = self._vol_scale_to_regime(vol_scale)
                return scale, state, "vol_regime"
        except Exception as exc:
            msg = f"VolRegime计算失败: {exc}，使用常数1.0"
            logger.warning(f"[RegimeModifier] {msg}")
            warnings.append(msg)

        # ── Level 3: 常数fallback ──
        warnings.append("所有Regime检测均失败，仓位缩放=1.0（不调节）")
        return 1.0, "unknown", "fallback_constant"

    def _fetch_benchmark_closes(self, context: StrategyContext) -> pd.Series | None:
        """从数据库拉取基准指数收盘价历史。

        Args:
            context: 含conn（psycopg2连接）和trade_date

        Returns:
            pd.Series: 收盘价序列（升序），失败返回None
        """
        if context.conn is None:
            return None

        try:
            cur = context.conn.cursor()
            # 取trade_date前300个交易日的收盘价（足够HMM训练）
            cur.execute(
                """
                SELECT trade_date, close
                FROM klines_daily k
                JOIN symbols s ON k.symbol_id = s.id
                WHERE s.ts_code = %s
                  AND k.trade_date <= %s
                ORDER BY k.trade_date ASC
                LIMIT 300
                """,
                (self._benchmark_code, context.trade_date),
            )
            rows = cur.fetchall()
            cur.close()
            if not rows:
                return None
            dates, closes = zip(*rows, strict=False)
            return pd.Series(
                [float(c) for c in closes],
                index=pd.to_datetime(dates),
                name="close",
            )
        except Exception as exc:
            logger.warning(f"[RegimeModifier] 拉取基准数据失败: {exc}")
            return None

    def _regime_to_scale(self, state: str) -> float:
        """HMM状态名映射到仓位缩放系数。"""
        if state == "risk_on":
            return self._scale_risk_on
        elif state == "risk_off":
            return self._scale_risk_off
        else:
            return self._scale_neutral

    def _vol_scale_to_regime(self, vol_scale: float) -> tuple[str, float]:
        """将VolRegime输出[0.5, 2.0]映射到三状态+对应缩放系数。

        VolRegime > 1.1 → risk_on（低波动）
        VolRegime 0.9~1.1 → neutral
        VolRegime < 0.9 → risk_off（高波动）
        """
        if vol_scale > 1.1:
            return "risk_on", self._scale_risk_on
        elif vol_scale < 0.9:
            return "risk_off", self._scale_risk_off
        else:
            return "neutral", self._scale_neutral
