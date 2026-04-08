"""HMM市场状态检测器 — 3状态Hidden Markov Model识别bull/sideways/bear。

Phase 2改进(2026-04-08):
- 3-state: bull/sideways/bear（12参数/3000+样本=250x，充足）
- 扩展窗口(expanding): 用所有历史数据fit，随时间推移越稳定
- 连续缩放: P(bull)*1.0 + P(sideways)*0.7 + P(bear)*0.3
- 去抖动20天: 与月度调仓对齐
- 单特征(对数收益率): 避免多重共线性

铁律7: ML实验必须OOS验证——rolling/expanding fit每次只用T-1前数据。
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# ── 参数 ──────────────────────────────────────────────────────────────────────
N_STATES: int = 3  # bull / sideways / bear (12参数, 3000样本/12=250x)
MIN_TRAIN_SAMPLES: int = 200  # ~10个月训练数据
USE_EXPANDING: bool = True  # True=扩展窗口(用所有历史), False=固定rolling
ROLLING_WINDOW: int = 504  # rolling模式下的窗口(2年), expanding模式下为最大cap

# 去抖动参数
MIN_REGIME_DURATION: int = 20  # 最小持续交易日(与月度调仓对齐)
SWITCH_PROB_THRESHOLD: float = 0.6  # 切换概率阈值(3-state下降低)

# 3-state连续缩放权重
SCALE_BULL: float = 1.0   # 牛市满仓
SCALE_SIDEWAYS: float = 0.7  # 震荡7成
SCALE_BEAR: float = 0.3   # 熊市3成
REGIME_CLIP_LOW: float = 0.3
REGIME_CLIP_HIGH: float = 1.0


@dataclass
class RegimeResult:
    """HMM状态检测结果。

    Attributes:
        state: 当前市场状态（bull / sideways / bear）
        scale: 仓位缩放系数 [0.3, 1.0]
        bear_prob: bear状态后验概率（0~1）
        state_probs: 各状态后验概率数组
        source: 数据来源标识（hmm / fallback_vol_regime / fallback_constant）
    """

    state: str  # "bull" | "sideways" | "bear"
    scale: float  # 仓位缩放系数 [0.3, 1.0]
    bear_prob: float  # bear后验概率
    state_probs: np.ndarray  # shape (N_STATES,)
    source: str  # 计算来源


def _compute_features(closes: pd.Series) -> np.ndarray | None:
    """从CSI300收盘价计算HMM输入特征（单特征：对数收益率）。

    quant审查要求：单特征避免多重共线性（波动率与收益率高度相关）。

    Args:
        closes: CSI300收盘价序列（时间升序）

    Returns:
        特征矩阵 shape (T, 1)，或None（数据不足）
    """
    if len(closes) < 2:
        return None

    log_returns = np.log(closes / closes.shift(1)).dropna()
    if len(log_returns) == 0:
        return None

    return log_returns.values.reshape(-1, 1).astype(np.float64)


def _map_states(model) -> dict[int, str]:
    """按均值排序3状态：最高收益=bull, 中间=sideways, 最低=bear。

    强制排序防label switching。

    Args:
        model: 已训练的GaussianHMM实例(2或3状态)

    Returns:
        {state_id: "bull" | "sideways" | "bear"}
    """
    means = model.means_.flatten()
    n = len(means)
    sorted_indices = np.argsort(means)  # 从小到大

    if n == 3:
        return {
            int(sorted_indices[0]): "bear",
            int(sorted_indices[1]): "sideways",
            int(sorted_indices[2]): "bull",
        }
    elif n == 2:
        return {
            int(sorted_indices[0]): "bear",
            int(sorted_indices[1]): "bull",
        }
    else:
        return {0: "bull"}


def _probs_to_scale(state_probs: np.ndarray, state_mapping: dict[int, str]) -> float:
    """3-state后验概率 → 连续缩放系数。

    scale = P(bull)*SCALE_BULL + P(sideways)*SCALE_SIDEWAYS + P(bear)*SCALE_BEAR
    输出范围[SCALE_BEAR, SCALE_BULL] = [0.3, 1.0]

    Args:
        state_probs: 各状态后验概率 shape (N,)
        state_mapping: {state_id: state_name}

    Returns:
        仓位缩放系数，clip到[REGIME_CLIP_LOW, REGIME_CLIP_HIGH]
    """
    scale_map = {"bull": SCALE_BULL, "sideways": SCALE_SIDEWAYS, "bear": SCALE_BEAR}
    raw = sum(
        float(state_probs[sid]) * scale_map.get(name, SCALE_SIDEWAYS)
        for sid, name in state_mapping.items()
    )
    return float(np.clip(raw, REGIME_CLIP_LOW, REGIME_CLIP_HIGH))


class HMMRegimeDetector:
    """3状态HMM市场状态检测器（bull / sideways / bear）。

    Phase 2改进:
    - 3-state: bull/sideways/bear, 12参数, 需200+天数据
    - 扩展窗口: 默认用所有历史数据fit(expanding), 可选固定rolling
    - 连续缩放: P(bull)*1.0 + P(sideways)*0.7 + P(bear)*0.3
    - 去抖动20天: 与月度调仓对齐

    用法（回测）:
        detector = HMMRegimeDetector()
        result = detector.fit_predict(csi300_closes)
        scale = result.scale  # [0.3, 1.0]
    """

    def __init__(
        self,
        n_states: int = N_STATES,
        min_train: int = MIN_TRAIN_SAMPLES,
        rolling_window: int = ROLLING_WINDOW,
        use_expanding: bool = USE_EXPANDING,
        min_duration: int = MIN_REGIME_DURATION,
        switch_threshold: float = SWITCH_PROB_THRESHOLD,
        random_state: int = 42,
    ) -> None:
        self.n_states = n_states
        self.min_train = min_train
        self.rolling_window = rolling_window
        self.use_expanding = use_expanding
        self.min_duration = min_duration
        self.switch_threshold = switch_threshold
        self.random_state = random_state

        self._model = None
        self._state_mapping: dict[int, str] = {}
        self._is_fitted = False
        # 去抖动状态跟踪
        self._prev_state: str | None = None
        self._state_duration: int = 0

    def fit(self, closes: pd.Series, n_iter: int = 200) -> "HMMRegimeDetector":
        """训练HMM模型。

        铁律7合规：调用方必须只传入T-1前数据。
        assert放在fit_predict()中。

        Args:
            closes: CSI300收盘价（时间升序，建议>=252天）
            n_iter: EM算法迭代次数

        Returns:
            self

        Raises:
            ValueError: 数据不足
        """
        from hmmlearn.hmm import GaussianHMM

        # expanding模式用所有数据, rolling模式取固定窗口
        if self.use_expanding:
            train_closes = closes
        elif len(closes) > self.rolling_window:
            train_closes = closes.iloc[-self.rolling_window :]
        else:
            train_closes = closes

        features = _compute_features(train_closes)
        if features is None or len(features) < self.min_train:
            n = len(features) if features is not None else 0
            raise ValueError(f"[HMMRegime] 训练数据不足: {n} < {self.min_train}")

        model = GaussianHMM(
            n_components=self.n_states,
            covariance_type="full",
            n_iter=n_iter,
            random_state=self.random_state,
            verbose=False,
        )
        model.fit(features)

        self._model = model
        self._state_mapping = _map_states(model)
        self._is_fitted = True

        # 参数快照（quant §6.2: 每次fit后记录参数）
        means = model.means_.flatten()
        logger.info(
            f"[HMMRegime] fit完成: samples={len(features)}, "
            f"means={np.round(means, 6)}, mapping={self._state_mapping}"
        )
        return self

    def predict(self, closes: pd.Series) -> RegimeResult:
        """预测当前regime（序列末端）。

        Args:
            closes: CSI300收盘价序列（时间升序）

        Returns:
            RegimeResult
        """
        if not self._is_fitted or self._model is None:
            logger.warning("[HMMRegime] 模型未训练，fallback")
            return self._fallback(closes)

        features = _compute_features(closes)
        if features is None or len(features) < 20:
            return self._fallback(closes)

        try:
            # 后验概率
            posteriors = self._model.predict_proba(features)
            current_probs = posteriors[-1]  # shape (N_STATES,)

            # bear概率
            bear_state_id = next(
                (k for k, v in self._state_mapping.items() if v == "bear"),
                0,
            )
            bear_prob = float(current_probs[bear_state_id])

            # 原始状态判断（argmax）
            raw_state = self._state_mapping.get(int(np.argmax(current_probs)), "sideways")

            # 去抖动
            state = self._debounce(raw_state, bear_prob)

            # 3-state连续缩放: P(bull)*1.0 + P(sideways)*0.7 + P(bear)*0.3
            scale = _probs_to_scale(current_probs, self._state_mapping)

            logger.info(
                "[HMMRegime] state=%s, bear_prob=%.3f, scale=%.3f, raw=%s, probs=%s",
                state, bear_prob, scale, raw_state,
                {v: round(float(current_probs[k]), 3) for k, v in self._state_mapping.items()},
            )
            return RegimeResult(
                state=state,
                scale=scale,
                bear_prob=bear_prob,
                state_probs=current_probs,
                source="hmm",
            )
        except Exception as e:
            logger.error(f"[HMMRegime] predict异常: {e}")
            return self._fallback(closes)

    def fit_predict(
        self,
        closes: pd.Series,
        predict_date: pd.Timestamp | None = None,
    ) -> RegimeResult:
        """Rolling fit + predict（回测主入口）。

        铁律7: 严格用predict_date之前的数据fit。

        Args:
            closes: CSI300收盘价完整序列
            predict_date: 预测日期。None时用closes最后一天。
                          fit只用此日期之前的数据。

        Returns:
            RegimeResult
        """
        train_closes = closes[closes.index < predict_date] if predict_date is not None else closes

        if len(train_closes) < self.min_train + 1:
            return self._fallback(train_closes)

        try:
            self.fit(train_closes)
            return self.predict(train_closes)
        except (ValueError, Exception) as e:
            logger.warning(f"[HMMRegime] fit_predict失败: {e}")
            return self._fallback(train_closes)

    def _debounce(self, raw_state: str, bear_prob: float) -> str:
        """去抖动：防止震荡市频繁切换状态。

        quant §4.3要求：
        1. 概率阈值：只在某状态概率>0.7时切换
        2. 最小持续期：切换后需持续>=5天

        Args:
            raw_state: HMM原始判断
            bear_prob: risk_off概率

        Returns:
            去抖后的state
        """
        # 初始化
        if self._prev_state is None:
            self._prev_state = raw_state
            self._state_duration = 1
            return raw_state

        # 概率阈值检查：不够确定就维持原状态
        max_prob = max(bear_prob, 1.0 - bear_prob)
        if max_prob < self.switch_threshold:
            self._state_duration += 1
            return self._prev_state

        # 状态变化检查
        if raw_state != self._prev_state:
            # 最小持续期检查：当前状态持续不够久，不切换
            if self._state_duration < self.min_duration:
                self._state_duration += 1
                return self._prev_state
            # 切换
            self._prev_state = raw_state
            self._state_duration = 1
            return raw_state
        else:
            self._state_duration += 1
            return raw_state

    def reset_debounce(self) -> None:
        """重置去抖动状态（新回测周期开始时调用）。"""
        self._prev_state = None
        self._state_duration = 0

    def _fallback(self, closes: pd.Series) -> RegimeResult:
        """Fallback到vol_regime启发式或常数。"""
        try:
            from engines.vol_regime import calc_vol_regime

            scale = calc_vol_regime(closes)
            if scale < 0.7:
                state = "bear"
            elif scale < 0.95:
                state = "sideways"
            else:
                state = "bull"
            return RegimeResult(
                state=state,
                scale=float(np.clip(scale, REGIME_CLIP_LOW, REGIME_CLIP_HIGH)),
                bear_prob=max(0.0, 1.0 - scale),
                state_probs=np.array([0.33, 0.34, 0.33]),
                source="fallback_vol_regime",
            )
        except Exception:
            return RegimeResult(
                state="bull",
                scale=1.0,
                bear_prob=0.0,
                state_probs=np.array([0.33, 0.34, 0.33]),
                source="fallback_constant",
            )


# ── 回测辅助函数 ─────────────────────────────────────────────────────────────


def generate_regime_series(
    closes: pd.Series,
    rolling_window: int = ROLLING_WINDOW,
    min_train: int = MIN_TRAIN_SAMPLES,
    refit_freq: str = "ME",
) -> pd.DataFrame:
    """生成全期regime时间序列（回测用，rolling fit无look-ahead）。

    每个调仓日(月末)用之前的数据fit HMM，预测当月regime。
    两个调仓日之间的regime保持不变。

    Args:
        closes: CSI300收盘价完整序列（DatetimeIndex）
        rolling_window: rolling fit窗口天数
        min_train: 最小训练样本数
        refit_freq: refit频率，"M"=月度，与v1.1调仓频率对齐

    Returns:
        DataFrame(index=date, columns=[state, scale, bear_prob, source])
    """
    detector = HMMRegimeDetector(
        rolling_window=rolling_window,
        min_train=min_train,
    )

    # 月末调仓日列表
    rebal_dates = closes.resample(refit_freq).last().index

    results: list[dict] = []
    prev_result = RegimeResult(
        state="risk_on",
        scale=1.0,
        bear_prob=0.5,
        state_probs=np.array([0.5, 0.5]),
        source="fallback_constant",
    )

    for rebal_date in rebal_dates:
        train_data = closes[closes.index <= rebal_date]
        if len(train_data) < min_train + 1:
            result = prev_result
        else:
            result = detector.fit_predict(train_data)

        results.append(
            {
                "date": rebal_date,
                "state": result.state,
                "scale": result.scale,
                "bear_prob": result.bear_prob,
                "source": result.source,
            }
        )
        prev_result = result

    regime_df = pd.DataFrame(results).set_index("date")

    # 前向填充到日频（调仓日之间的日期用上个调仓日的regime）
    daily_index = closes.index
    regime_daily = regime_df.reindex(daily_index).ffill().bfill()

    logger.info(
        f"[HMMRegime] 生成regime序列: {len(regime_daily)}天, "
        f"risk_on={int((regime_daily['state'] == 'risk_on').sum())}天, "
        f"risk_off={int((regime_daily['state'] == 'risk_off').sum())}天"
    )
    return regime_daily
