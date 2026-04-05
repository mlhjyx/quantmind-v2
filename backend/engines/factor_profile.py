"""因子画像 -- IC衰减分析、半衰期拟合、调仓频率推荐。

为多频率调仓优化提供数据基础:
- 每个因子的IC衰减曲线 (1/5/10/20日)
- 指数衰减半衰期拟合
- 基于半衰期的调仓频率推荐

遵循CLAUDE.md: IC使用沪深300超额收益、Spearman rank IC。

FactorProfilePipeline提供编程式API，可从Service层调用:
    pipeline = FactorProfilePipeline(conn)
    profiles = pipeline.analyze_factors(["turnover_mean_20", "volatility_20"])
    pipeline.save_to_db(profiles)
"""

import bisect
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import structlog
from scipy import stats

logger = structlog.get_logger(__name__)


@dataclass
class FactorProfile:
    """因子画像——每个因子的衰减特性、推荐频率、标签。"""

    name: str
    tags: list[str] = field(default_factory=list)
    ic_decay: dict[int, float] = field(default_factory=dict)  # {1: 0.08, 5: 0.06, ...}
    half_life_days: float = 0.0
    recommended_freq: str = "monthly"
    category: str = ""  # price_volume / liquidity / fundamental / ...
    direction: int = 1  # 1 or -1
    status: str = "active"  # active / reserve / retired

    @classmethod
    def from_ic_decay(
        cls, name: str, ic_decay: dict[int, float], **kwargs: object
    ) -> "FactorProfile":
        """从ic_decay自动计算half_life和推荐频率。

        Args:
            name: 因子名称。
            ic_decay: {horizon_days: mean_ic} 映射。
            **kwargs: 传递给FactorProfile构造函数的其他参数。

        Returns:
            填充了half_life_days和recommended_freq的FactorProfile实例。
        """
        half_life = fit_exponential_decay(ic_decay)
        freq = recommend_freq(half_life)
        return cls(
            name=name,
            ic_decay=ic_decay,
            half_life_days=half_life,
            recommended_freq=freq,
            **kwargs,  # type: ignore[arg-type]
        )


def fit_exponential_decay(ic_decay: dict[int, float]) -> float:
    """拟合IC衰减的指数半衰期。

    模型: |IC(t)| = |IC(0)| * exp(-lambda * t)
    半衰期 = ln(2) / lambda

    用对数线性回归拟合。如果拟合失败或数据不足，返回默认值30天。

    Args:
        ic_decay: {horizon_days: mean_ic} 映射。

    Returns:
        半衰期(天)。拟合失败返回30.0。
    """
    if len(ic_decay) < 2:
        return 30.0

    # 按horizon排序，取绝对值IC
    horizons = sorted(ic_decay.keys())
    abs_ics = [abs(ic_decay[h]) for h in horizons]

    # 过滤掉IC<=0的点（无法取log）
    valid_h = []
    valid_log_ic = []
    for h, ic in zip(horizons, abs_ics, strict=False):
        if ic > 1e-8:
            valid_h.append(h)
            valid_log_ic.append(np.log(ic))

    if len(valid_h) < 2:
        return 30.0

    # 线性回归: log(|IC|) = log(|IC(0)|) - lambda * t
    x = np.array(valid_h, dtype=float)
    y = np.array(valid_log_ic, dtype=float)

    len(x)
    x_mean = x.mean()
    y_mean = y.mean()
    ss_xx = ((x - x_mean) ** 2).sum()

    if ss_xx < 1e-12:
        return 30.0

    slope = ((x - x_mean) * (y - y_mean)).sum() / ss_xx  # -lambda

    # lambda必须为正（IC应该随时间衰减）
    lam = -slope
    if lam <= 1e-8:
        # IC不衰减或上升——返回大的半衰期（120天，推荐monthly）
        logger.debug("IC不单调衰减，slope=%.4f，返回默认半衰期120天", slope)
        return 120.0

    half_life = np.log(2) / lam

    # 限制合理范围
    half_life = float(np.clip(half_life, 0.5, 120.0))
    return round(half_life, 1)


def recommend_freq(half_life_days: float) -> str:
    """基于半衰期推荐调仓频率。

    Args:
        half_life_days: IC半衰期(天)。

    Returns:
        推荐频率字符串: daily / weekly / biweekly / monthly。
    """
    if half_life_days < 3:
        return "daily"
    elif half_life_days < 7:
        return "weekly"
    elif half_life_days < 15:
        return "biweekly"
    else:
        return "monthly"


# ============================================================
# FactorProfilePipeline — 编程式IC衰减分析管道
# ============================================================

# 默认IC衰减分析参数
DEFAULT_HORIZONS = [1, 5, 10, 20]
DEFAULT_START = date(2021, 1, 1)
DEFAULT_END = date(2025, 12, 31)


class FactorProfilePipeline:
    """因子画像分析管道。

    编程式API，可从Service层或脚本调用。
    封装了DB读取、IC衰减计算、半衰期拟合、结果写入的完整流程。

    用法:
        pipeline = FactorProfilePipeline(conn)
        profiles = pipeline.analyze_factors(["turnover_mean_20"])
        pipeline.save_to_db(profiles)
    """

    def __init__(
        self,
        conn: Any,
        start_date: date | None = None,
        end_date: date | None = None,
        horizons: list[int] | None = None,
        sample_step: int = 5,
    ):
        """初始化管道。

        Args:
            conn: psycopg2数据库连接。
            start_date: IC计算起始日期。
            end_date: IC计算截止日期。
            horizons: 前向收益天数列表。
            sample_step: 截面采样步长(每N个交易日取1个)。
        """
        self.conn = conn
        self.start_date = start_date or DEFAULT_START
        self.end_date = end_date or DEFAULT_END
        self.horizons = horizons or DEFAULT_HORIZONS
        self.sample_step = sample_step
        self._excess_returns: pd.DataFrame | None = None
        self._trading_days: list[date] | None = None

    def analyze_factors(
        self,
        factor_names: list[str],
        factor_meta: dict[str, dict] | None = None,
    ) -> list[FactorProfile]:
        """分析多个因子的IC衰减画像。

        Args:
            factor_names: 因子名称列表。
            factor_meta: 因子元数据 {name: {category, direction, tags}}。

        Returns:
            FactorProfile列表。
        """
        if factor_meta is None:
            factor_meta = {}

        # 懒加载超额收益（全局共用）
        if self._excess_returns is None:
            self._excess_returns = self._load_excess_returns()
            if self._excess_returns.empty:
                logger.error("超额收益数据为空，无法计算IC衰减")
                return []

        profiles: list[FactorProfile] = []
        for fname in factor_names:
            factor_df = self._load_factor_data(fname)
            if factor_df.empty:
                logger.warning("因子 %s 无数据，跳过", fname)
                continue

            ic_decay = self._calc_ic_decay(factor_df)
            meta = factor_meta.get(fname, {})
            profile = FactorProfile.from_ic_decay(
                name=fname,
                ic_decay=ic_decay,
                category=meta.get("category", ""),
                direction=meta.get("direction", 1),
                tags=meta.get("tags", []),
                status=meta.get("status", "active"),
            )
            profiles.append(profile)
            logger.info(
                "因子 %s: half_life=%.1f天, freq=%s, IC(1d)=%.4f",
                fname, profile.half_life_days, profile.recommended_freq,
                ic_decay.get(1, 0.0),
            )

        return profiles

    def analyze_active_factors(
        self,
        factor_meta: dict[str, dict] | None = None,
    ) -> list[FactorProfile]:
        """分析所有Active因子。

        Args:
            factor_meta: 因子元数据。

        Returns:
            FactorProfile列表。
        """
        factor_names = self._load_active_factor_names()
        if not factor_names:
            logger.warning("无Active因子")
            return []
        return self.analyze_factors(factor_names, factor_meta)

    def save_to_db(self, profiles: list[FactorProfile]) -> int:
        """将画像写入factor_lifecycle表。

        Args:
            profiles: FactorProfile列表。

        Returns:
            写入的记录数。
        """
        import json

        self._ensure_db_columns()

        cur = self.conn.cursor()
        count = 0
        for p in profiles:
            cur.execute(
                """UPDATE factor_lifecycle
                   SET tags = %s,
                       ic_decay = %s,
                       half_life_days = %s,
                       recommended_freq = %s,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE factor_name = %s""",
                (
                    json.dumps(p.tags),
                    json.dumps({str(k): round(v, 6) for k, v in p.ic_decay.items()}),
                    round(p.half_life_days, 2),
                    p.recommended_freq,
                    p.name,
                ),
            )
            if cur.rowcount > 0:
                count += 1
        self.conn.commit()
        cur.close()
        logger.info("写入 %d/%d 个因子画像到DB", count, len(profiles))
        return count

    def get_recommended_freq(self, factor_names: list[str]) -> str:
        """获取因子组合的综合推荐频率。

        取所有因子半衰期的中位数来推荐。

        Args:
            factor_names: 因子名称列表。

        Returns:
            推荐频率字符串。
        """
        profiles = self.analyze_factors(factor_names)
        if not profiles:
            return "monthly"

        half_lives = [p.half_life_days for p in profiles]
        median_hl = float(np.median(half_lives))
        return recommend_freq(median_hl)

    # ── 私有方法 ──

    def _load_factor_data(self, factor_name: str) -> pd.DataFrame:
        """加载因子值（中性化后）。"""
        result = pd.read_sql(
            """SELECT code, trade_date, neutral_value
               FROM factor_values
               WHERE factor_name = %s AND trade_date BETWEEN %s AND %s""",
            self.conn,
            params=(factor_name, self.start_date, self.end_date),
        )
        assert isinstance(result, pd.DataFrame)
        return result

    def _load_excess_returns(self) -> pd.DataFrame:
        """加载超额收益（vs沪深300）。"""
        stock_ret_raw = pd.read_sql(
            """SELECT code, trade_date,
                      (close * adj_factor) /
                      LAG(close * adj_factor) OVER (PARTITION BY code ORDER BY trade_date) - 1
                      AS ret
               FROM klines_daily
               WHERE trade_date BETWEEN %s AND %s AND volume > 0
               ORDER BY trade_date, code""",
            self.conn,
            params=(self.start_date, self.end_date),
        )
        assert isinstance(stock_ret_raw, pd.DataFrame)
        stock_ret = stock_ret_raw

        # index_daily的close无需复权——指数行情已含分红再投资，
        # 直接用close/LAG(close)-1即为全收益率
        bench_ret_raw = pd.read_sql(
            """SELECT trade_date,
                      close / LAG(close) OVER (ORDER BY trade_date) - 1 AS bench_ret
               FROM index_daily
               WHERE index_code = '000300.SH'
                 AND trade_date BETWEEN %s AND %s
               ORDER BY trade_date""",
            self.conn,
            params=(self.start_date, self.end_date),
        )
        assert isinstance(bench_ret_raw, pd.DataFrame)
        bench_ret = bench_ret_raw

        if stock_ret.empty or bench_ret.empty:
            return pd.DataFrame()

        merged = stock_ret.merge(bench_ret, on="trade_date", how="left")
        merged["excess_ret"] = merged["ret"] - merged["bench_ret"].fillna(0)
        result_df: pd.DataFrame = merged[["code", "trade_date", "excess_ret"]].dropna()  # type: ignore[assignment]
        return result_df

    def _load_active_factor_names(self) -> list[str]:
        """从factor_lifecycle表获取Active因子列表。"""
        result = pd.read_sql(
            "SELECT factor_name FROM factor_lifecycle WHERE status = 'active' ORDER BY factor_name",
            self.conn,
        )
        assert isinstance(result, pd.DataFrame)
        return result["factor_name"].tolist()

    def _get_trading_days(self) -> list[date]:
        """从trading_calendar表加载交易日列表（带缓存）。

        Returns:
            按日期排序的交易日列表。
        """
        if self._trading_days is not None:
            return self._trading_days

        # 加载范围稍宽，确保forward horizon不会越界
        buffer_end = self.end_date + timedelta(days=60)
        result = pd.read_sql(
            """SELECT cal_date FROM trading_calendar
               WHERE exchange = 'SSE' AND is_open = 1
                 AND cal_date BETWEEN %s AND %s
               ORDER BY cal_date""",
            self.conn,
            params=(self.start_date, buffer_end),
        )
        assert isinstance(result, pd.DataFrame)
        self._trading_days = [
            d.date() if hasattr(d, "date") else d
            for d in result["cal_date"].tolist()
        ]
        logger.info("加载交易日历: %d个交易日", len(self._trading_days))
        return self._trading_days

    def _offset_trading_day(self, dt: date, offset: int) -> date | None:
        """从给定日期向前偏移N个交易日。

        Args:
            dt: 起始日期。
            offset: 向前偏移的交易日数。

        Returns:
            偏移后的交易日，超出范围返回None。
        """
        trading_days = self._get_trading_days()
        idx = bisect.bisect_right(trading_days, dt)
        target_idx = idx + offset - 1
        if target_idx < 0 or target_idx >= len(trading_days):
            return None
        return trading_days[target_idx]

    def _calc_ic_decay(self, factor_df: pd.DataFrame) -> dict[int, float]:
        """计算IC衰减（使用交易日偏移）。"""
        assert self._excess_returns is not None

        decay: dict[int, float] = {}
        dates = sorted(factor_df["trade_date"].unique())
        sampled_dates = dates[:: self.sample_step]

        for h in self.horizons:
            ic_values: list[float] = []

            for dt in sampled_dates:
                cross_section = factor_df[factor_df["trade_date"] == dt]
                future_end = self._offset_trading_day(dt, h)
                if future_end is None:
                    continue
                future_rets = self._excess_returns[
                    (self._excess_returns["trade_date"] > dt)
                    & (self._excess_returns["trade_date"] <= future_end)
                ]
                if future_rets.empty:
                    continue

                cum_ret = pd.Series(future_rets.groupby("code")["excess_ret"].sum())
                fwd_ret = cum_ret.rename("fwd_ret")
                merged = cross_section.set_index("code")["neutral_value"].to_frame()
                merged = merged.join(fwd_ret, how="inner").dropna()

                if len(merged) < 30:
                    continue

                result = stats.spearmanr(merged["neutral_value"], merged["fwd_ret"])
                ic_val = float(result.statistic)  # type: ignore[union-attr]
                if not np.isnan(ic_val):
                    ic_values.append(ic_val)

            decay[h] = float(np.mean(ic_values)) if ic_values else 0.0

        return decay

    def _ensure_db_columns(self) -> None:
        """确保factor_lifecycle表有扩展字段。"""
        cur = self.conn.cursor()
        alters = [
            "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]'",
            "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS ic_decay JSONB",
            "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS half_life_days DECIMAL(8,2)",
            "ALTER TABLE factor_lifecycle ADD COLUMN IF NOT EXISTS recommended_freq VARCHAR(20)",
        ]
        for sql in alters:
            try:
                cur.execute(sql)
            except Exception as e:
                logger.warning("ALTER TABLE跳过: %s", e)
        self.conn.commit()
        cur.close()
