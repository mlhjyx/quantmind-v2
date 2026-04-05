"""HMM市场状态检测器 — 2状态Hidden Markov Model识别risk-on/risk-off。

根据quant-reviewer + risk-guardian交叉审查结果修正：
- 2-state替代3-state（参数6个 vs 33个，730样本/6参数=122>50阈值）
- 单特征(对数收益率)避免多重共线性（quant C2要求）
- Rolling fit(252天窗口)防look-ahead（quant C1强制要求）
- 去抖动：最小持续5天 + 概率阈值0.7（quant §4.3要求）
- 连续scale：scale = 1.0 - spread × (bear_prob - 0.5)（quant §7建议）
- 不入PT链路，仅回测+影子模式（risk §5一票否决PT替换）

铁律7: ML实验必须OOS验证——rolling fit每次只用T-1前数据。
"""

import structlog
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = structlog.get_logger(__name__)

# ── 参数 ──────────────────────────────────────────────────────────────────────
N_STATES: int = 2  # risk-on / risk-off（quant审查：2-state参数更稳定）
MIN_TRAIN_SAMPLES: int = 252  # 至少1年训练数据（quant C2: 样本/参数>=50）
ROLLING_WINDOW: int = 252  # rolling fit窗口（1年，quant §2.3最短504可选）

# 去抖动参数（quant §4.3要求）
MIN_REGIME_DURATION: int = 5  # 最小持续交易日
SWITCH_PROB_THRESHOLD: float = 0.7  # 切换概率阈值

# 仓位缩放参数
SCALE_SPREAD: float = 0.4  # scale在[0.6, 1.4]之间变化
REGIME_CLIP_LOW: float = 0.5
REGIME_CLIP_HIGH: float = 2.0


@dataclass
class RegimeResult:
    """HMM状态检测结果。

    Attributes:
        state: 当前市场状态（risk_on / risk_off）
        scale: 仓位缩放系数 [0.5, 2.0]
        bear_prob: risk-off状态的后验概率（0~1）
        state_probs: 两个状态的后验概率数组
        source: 数据来源标识（hmm / fallback_vol_regime / fallback_constant）
    """

    state: str  # "risk_on" | "risk_off"
    scale: float  # 仓位缩放系数 [0.5, 2.0]
    bear_prob: float  # risk-off后验概率
    state_probs: np.ndarray  # shape (2,)
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
    """按均值排序状态：高收益=risk_on, 低收益=risk_off。

    quant §1.5要求：强制排序防label switching。

    Args:
        model: 已训练的GaussianHMM实例

    Returns:
        {state_id: "risk_on" | "risk_off"}
    """
    means = model.means_.flatten()  # shape (2,)
    if means[0] >= means[1]:
        return {0: "risk_on", 1: "risk_off"}
    else:
        return {0: "risk_off", 1: "risk_on"}


def _bear_prob_to_scale(bear_prob: float) -> float:
    """连续映射：bear_prob → 仓位缩放系数。

    quant §7建议：连续信号比离散分类更有价值。
    scale = 1.0 - SCALE_SPREAD × (bear_prob - 0.5)
    - bear_prob=0.0 → scale=1.2（满仓偏多）
    - bear_prob=0.5 → scale=1.0（不调整）
    - bear_prob=1.0 → scale=0.6（降仓保护）

    Args:
        bear_prob: risk-off状态后验概率 [0, 1]

    Returns:
        仓位缩放系数，clip到[REGIME_CLIP_LOW, REGIME_CLIP_HIGH]
    """
    raw = 1.0 - SCALE_SPREAD * (bear_prob - 0.5) * 2.0
    return float(np.clip(raw, REGIME_CLIP_LOW, REGIME_CLIP_HIGH))


class HMMRegimeDetector:
    """2状态HMM市场状态检测器（risk-on / risk-off）。

    设计原则（quant+risk审查后）：
    - 2-state单特征：6参数/252+样本，比值>42（接近50阈值）
    - Rolling fit：每次调仓日用过去252天数据refit，无look-ahead
    - 去抖动：状态切换需概率>0.7且持续>=5天
    - 连续scale：不用离散3档，用bear_prob连续映射

    用法（回测）：
        detector = HMMRegimeDetector()
        for rebal_date in rebal_dates:
            train_data = closes[:rebal_date]  # 严格T-1前
            result = detector.fit_predict(train_data)
            scale = result.scale

    用法（影子模式PT）：
        result = detector.fit_predict(csi300_closes_to_yesterday)
        save_shadow_regime(trade_date, result)  # 只记录不使用
    """

    def __init__(
        self,
        n_states: int = N_STATES,
        min_train: int = MIN_TRAIN_SAMPLES,
        rolling_window: int = ROLLING_WINDOW,
        min_duration: int = MIN_REGIME_DURATION,
        switch_threshold: float = SWITCH_PROB_THRESHOLD,
        random_state: int = 42,
    ) -> None:
        self.n_states = n_states
        self.min_train = min_train
        self.rolling_window = rolling_window
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

        # 取rolling窗口
        if len(closes) > self.rolling_window:
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
            current_probs = posteriors[-1]  # shape (2,)

            # 找到risk_off状态的概率
            bear_state_id = next(
                (k for k, v in self._state_mapping.items() if v == "risk_off"),
                0,
            )
            bear_prob = float(current_probs[bear_state_id])

            # 原始状态判断（argmax）
            raw_state = self._state_mapping.get(int(np.argmax(current_probs)), "risk_on")

            # 去抖动（quant §4.3）
            state = self._debounce(raw_state, bear_prob)
            scale = _bear_prob_to_scale(bear_prob)

            logger.info(
                f"[HMMRegime] state={state}, bear_prob={bear_prob:.3f}, "
                f"scale={scale:.3f}, raw={raw_state}"
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
            state = "risk_off" if scale < 0.95 else "risk_on"
            return RegimeResult(
                state=state,
                scale=scale,
                bear_prob=0.5,
                state_probs=np.array([0.5, 0.5]),
                source="fallback_vol_regime",
            )
        except Exception:
            return RegimeResult(
                state="risk_on",
                scale=1.0,
                bear_prob=0.5,
                state_probs=np.array([0.5, 0.5]),
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
