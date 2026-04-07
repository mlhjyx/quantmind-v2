"""NorthboundModifier — 基于北向资金行为模式的仓位调节器。

V2研究(2026-04-05): 15因子中8个OOS通过, 核心发现"看怎么买比买多少有效"。
市场级信号(每天一个值) → 综合评分 → 全仓位缩放。

信号解读:
- 分数>0: 北向行为偏积极(breadth扩张/集中买入/逆势加仓) → 维持满仓
- 分数<0: 北向行为偏消极(breadth收缩/分散/顺势出逃) → 缩减仓位
- 极端负值: 恐慌信号(极端流出+波动突变) → 大幅缩减

依赖: northbound_holdings表(390万行, 2020-01-02~)
设计文档: docs/research-kb/findings/northbound-behavior-patterns.md
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import structlog

from engines.base_strategy import StrategyContext
from engines.modifiers.base import ModifierBase, ModifierResult

logger = structlog.get_logger(__name__)

# 默认缩放: 中性=1.0, 积极=1.0(不加杠杆), 消极=0.7, 恐慌=0.5
_SCALE_POSITIVE = 1.0
_SCALE_NEUTRAL = 1.0
_SCALE_NEGATIVE = 0.7
_SCALE_PANIC = 0.5


class NorthboundModifier(ModifierBase):
    """基于北向资金行为模式的全仓位缩放调节器。

    8个OOS验证通过的V2因子综合为单一评分:
    - breadth_ratio: 买入广度
    - buy_concentration: 买入集中度(HHI)
    - asymmetry: 买入/卖出力度不对称性
    - turnover: 换仓活跃度
    - contrarian_market_5d: 5日逆势买入强度
    - extreme_outflow: 极端流出(恐慌底部)
    - vol_change: 波动率突变
    - streak_reversal: 连续流入后反转信号

    config可选字段:
        lookback_days: int      回溯天数(默认252, 用于百分位归一化)
        scale_positive: float   积极信号缩放(默认1.0)
        scale_negative: float   消极信号缩放(默认0.7)
        scale_panic: float      恐慌信号缩放(默认0.5)
        panic_threshold: float  恐慌阈值(z-score, 默认-2.0)
        negative_threshold: float  消极阈值(z-score, 默认-0.5)
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        super().__init__(
            name="northbound_modifier",
            config=cfg,
            clip_range=(0.3, 1.0),  # 最少保留30%仓位, 不加杠杆
        )
        self._lookback = cfg.get("lookback_days", 252)
        self._scale_positive = cfg.get("scale_positive", _SCALE_POSITIVE)
        self._scale_negative = cfg.get("scale_negative", _SCALE_NEGATIVE)
        self._scale_panic = cfg.get("scale_panic", _SCALE_PANIC)
        self._panic_threshold = cfg.get("panic_threshold", -2.0)
        self._negative_threshold = cfg.get("negative_threshold", -0.5)
        # 缓存: 避免每个调仓日重新查询全量数据
        self._cache_date: date | None = None
        self._cache_panel: pd.DataFrame | None = None

    def should_trigger(self, context: StrategyContext) -> bool:
        """始终触发(每个调仓日检查北向信号)。"""
        return True

    def compute_adjustments(
        self,
        base_weights: dict[str, float],
        context: StrategyContext,
    ) -> ModifierResult:
        """计算北向行为综合评分 → 全仓位缩放因子。"""
        trade_date = context.trade_date
        conn = context.conn

        if conn is None:
            return ModifierResult(
                adjustment_factors={},
                triggered=False,
                reasoning="无DB连接, 跳过北向信号",
            )

        # 构建/更新市场面板
        try:
            panel = self._get_market_panel(trade_date, conn)
        except Exception as e:
            logger.warning("北向面板构建失败: %s", e)
            return ModifierResult(
                adjustment_factors={},
                triggered=False,
                reasoning=f"数据异常: {e}",
            )

        if panel is None or panel.empty or trade_date not in panel.index:
            return ModifierResult(
                adjustment_factors={},
                triggered=False,
                reasoning="无北向数据",
            )

        # 计算综合评分
        score = self._compute_composite_score(panel, trade_date)

        # 评分 → 缩放因子
        if score <= self._panic_threshold:
            scale = self._scale_panic
            reasoning = f"北向恐慌(score={score:.2f}≤{self._panic_threshold})"
        elif score <= self._negative_threshold:
            scale = self._scale_negative
            reasoning = f"北向消极(score={score:.2f})"
        else:
            scale = self._scale_positive
            reasoning = f"北向中性/积极(score={score:.2f})"

        # 全仓位统一缩放
        if abs(scale - 1.0) < 0.01:
            return ModifierResult(
                adjustment_factors={},
                triggered=False,
                reasoning=reasoning + " → 不调节",
            )

        adjustments = {code: scale for code in base_weights}
        return ModifierResult(
            adjustment_factors=adjustments,
            triggered=True,
            reasoning=reasoning + f" → scale={scale:.2f}",
        )

    def _compute_composite_score(self, panel: pd.DataFrame, td: date) -> float:
        """8个因子→z-score归一化→等权平均→综合评分。"""
        factor_cols = [
            "nb_breadth_ratio",
            "nb_buy_concentration",
            "nb_asymmetry",
            "nb_turnover",
            "nb_contrarian_market_5d",
            "nb_extreme_outflow",
            "nb_vol_change",
            "nb_streak_reversal",
        ]

        # 各因子的预期方向(正=看多, 负=看空)
        directions = {
            "nb_breadth_ratio": 1,  # 广度扩张=积极
            "nb_buy_concentration": 1,  # 集中买入=有观点
            "nb_asymmetry": 1,  # 买>卖=积极
            "nb_turnover": 1,  # 活跃调仓=有信息
            "nb_contrarian_market_5d": 1,  # 逆势买入=底部信号
            "nb_extreme_outflow": -1,  # 极端流出=恐慌(反向)
            "nb_vol_change": -1,  # 波动突变=不确定性(反向)
            "nb_streak_reversal": -1,  # 连续流入后反转=见顶
        }

        available = [c for c in factor_cols if c in panel.columns]
        if not available:
            return 0.0

        # 取到当前日期的历史数据做z-score
        hist = panel.loc[:td, available].iloc[-self._lookback :]
        if len(hist) < 30:
            return 0.0

        current = hist.iloc[-1]
        z_scores = []
        for col in available:
            series = hist[col].dropna()
            if len(series) < 20:
                continue
            mean = series.mean()
            std = series.std()
            if std < 1e-10:
                continue
            z = (current[col] - mean) / std * directions.get(col, 1)
            z_scores.append(np.clip(z, -3, 3))

        return float(np.mean(z_scores)) if z_scores else 0.0

    def _get_market_panel(self, trade_date: date, conn) -> pd.DataFrame | None:
        """构建北向市场面板(带缓存)。"""
        # 缓存: 同一天不重复查询
        if self._cache_date == trade_date and self._cache_panel is not None:
            return self._cache_panel

        start = trade_date - timedelta(days=self._lookback * 2)
        cur = conn.cursor()

        # net_buy_vol在DB中为NULL, 用hold_vol日间差分计算净买入
        # 子查询: 每只股票的hold_vol与前一日差值 = 当日净买入量
        cur.execute(
            """WITH daily_diff AS (
                SELECT trade_date, code, hold_vol, hold_mv,
                       hold_vol - LAG(hold_vol) OVER (PARTITION BY code ORDER BY trade_date) as net_chg
                FROM northbound_holdings
                WHERE trade_date BETWEEN %s AND %s
                  AND hold_vol IS NOT NULL
            )
            SELECT trade_date,
                   COUNT(*) FILTER (WHERE net_chg > 0) as n_buy,
                   COUNT(*) FILTER (WHERE net_chg < 0) as n_sell,
                   SUM(CASE WHEN net_chg > 0 THEN net_chg * hold_mv / NULLIF(hold_vol, 0) ELSE 0 END) as buy_amount,
                   SUM(CASE WHEN net_chg < 0 THEN ABS(net_chg) * hold_mv / NULLIF(hold_vol, 0) ELSE 0 END) as sell_amount,
                   SUM(net_chg) as net_flow,
                   SUM(ABS(net_chg)) as abs_flow
            FROM daily_diff
            WHERE net_chg IS NOT NULL
            GROUP BY trade_date
            ORDER BY trade_date""",
            (start - timedelta(days=5), trade_date),  # 额外5天用于LAG计算
        )

        rows = cur.fetchall()
        if not rows:
            return None

        df = pd.DataFrame(
            rows,
            columns=[
                "trade_date",
                "n_buy",
                "n_sell",
                "buy_amount",
                "sell_amount",
                "net_flow",
                "abs_flow",
            ],
        )
        df = df.set_index("trade_date").sort_index()
        # DB返回Decimal, 统一转float
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 计算8个行为因子
        df["nb_breadth_ratio"] = df["n_buy"] / df["n_sell"].replace(0, 1)
        df["nb_asymmetry"] = df["buy_amount"] / df["sell_amount"].replace(0, 1e-10)
        df["nb_turnover"] = (
            (df["abs_flow"] - df["net_flow"].abs()) / 2 / df["abs_flow"].replace(0, 1)
        )

        # HHI需要个股数据, 简化用buy_amount占比的变异系数近似
        df["nb_buy_concentration"] = df["buy_amount"] / df["buy_amount"].rolling(20).mean().replace(
            0, 1
        )

        # 逆势买入: 需要CSI300收益
        cur.execute(
            """SELECT trade_date, pct_change / 100.0 as ret
               FROM index_daily
               WHERE index_code = '000300.SH' AND trade_date BETWEEN %s AND %s
               ORDER BY trade_date""",
            (start, trade_date),
        )
        idx_rows = cur.fetchall()
        if idx_rows:
            idx_df = pd.DataFrame(idx_rows, columns=["trade_date", "ret"]).set_index("trade_date")
            idx_df["ret"] = pd.to_numeric(idx_df["ret"], errors="coerce")
            csi_ret = idx_df["ret"].reindex(df.index).fillna(0)
            df["nb_contrarian_market_5d"] = (df["net_flow"] * (-csi_ret)).rolling(5).sum()
        else:
            df["nb_contrarian_market_5d"] = 0

        # 极端流出(P5)
        net = df["net_flow"]
        p5 = net.rolling(252, min_periods=60).quantile(0.05)
        df["nb_extreme_outflow"] = (net < p5).astype(float)

        # 波动率突变
        vol_5 = net.rolling(5).std()
        vol_60 = net.rolling(60).std().replace(0, np.nan)
        df["nb_vol_change"] = vol_5 / vol_60

        # 连续流入反转
        streak = pd.Series(0.0, index=df.index)
        count = 0
        for j in range(len(net)):
            v = net.iloc[j]
            if v > 0:
                count = count + 1 if count > 0 else 1
            elif v < 0:
                count = count - 1 if count < 0 else -1
            else:
                count = 0
            streak.iloc[j] = count
        df["nb_streak_reversal"] = -streak / 10

        self._cache_date = trade_date
        self._cache_panel = df
        return df
