#!/usr/bin/env python3
"""Sprint 1.3b: Alpha158 KBAR Factor IC Analysis (20 factors) + close_to_high Residual IC
=========================================================================================

Task 1: 从Qlib Alpha158中提取20个KBAR因子公式，纯OHLC计算，跑月度IC验证。
Task 2: close_to_high_ratio_20 残差IC验证（回归掉vol_20后的独立alpha检验）。

KBAR因子经济学逻辑:
- 实体比率(body ratio): 价格决定性强度，高=单方向压力=过度反应→反转
- 振幅(range): 日内波动=分歧度，高分歧=不确定性=风险溢价
- 收盘位置(close position): 收盘接近最高价=买方主导=短期动量
- 上影线(upper shadow): 盘中冲高回落=抛压=短期见顶信号
- 下影线(lower shadow): 盘中下探回升=承接力=短期支撑信号
- 量价交叉: 价格形态+成交量变化=智能资金行为

A股适用性:
- T+1结算放大OHLC模式的预测力（被迫持仓隔夜）
- 散户主导使K线形态信号更持久（机构套利不充分）
- 涨跌停制度创造独特的影线模式（封板≈zero shadow）

数据源: klines_daily (2020-2025), 无需新数据
IC计算: 月度截面Spearman IC, 20日超额收益(vs CSI300), 2021-2025
相关性预筛: vs vol_20/reversal_20/turnover_mean_20, corr>0.6标记冗余

DB: postgresql://xin:quantmind@localhost:5432/quantmind_v2
"""

import sys
import time
import warnings
from datetime import date as dt_date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from engines.config_guard import print_config_header

warnings.filterwarnings("ignore")

DB_URI = "postgresql://xin:quantmind@localhost:5432/quantmind_v2"

IC_START = dt_date(2021, 1, 1)
IC_END = dt_date(2025, 12, 31)
DATA_START = "2020-01-01"

# 已入池因子(v1.1基线 + 常见参考因子)
CORR_CHECK_FACTORS = [
    "volatility_20", "reversal_20", "turnover_mean_20",
    "momentum_20", "ln_market_cap", "bp_ratio",
    "high_low_range_20", "amihud_20",
]


# ════════════════════════════════════════════════════════════════════
# FACTOR DEFINITIONS: 20 KBAR因子
# ════════════════════════════════════════════════════════════════════

def define_kbar_factors() -> list[dict]:
    """定义20个KBAR因子的公式、经济学解释和计算函数。

    因子1-10: 基础KBAR因子(实体/振幅/收盘位置/上影/下影, 5d/20d)
    因子11-20: 高级KBAR/量价交叉因子(Alpha158 + 行为金融)
    """
    return [
        # ─── 基础KBAR因子 (5d/20d pairs) ───
        {
            "name": "kbar_open_close_5",
            "formula": "mean(abs(close-open)/open, 5d)",
            "econ": "5日实体比率: 价格决定性。高实体=单方向压力过大=短期过度反应→反转",
            "window": 5,
            "calc": lambda o, h, l, c, v: _rolling_mean(np.abs(c - o) / (o + 1e-8), 5),
            "default_dir": -1,
        },
        {
            "name": "kbar_open_close_20",
            "formula": "mean(abs(close-open)/open, 20d)",
            "econ": "20日实体比率: 持续的高实体=趋势过热信号，均值回归概率上升",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(np.abs(c - o) / (o + 1e-8), 20),
            "default_dir": -1,
        },
        {
            "name": "kbar_high_low_5",
            "formula": "mean((high-low)/close, 5d)",
            "econ": "5日振幅: 近期分歧度。高分歧=不确定性=风险溢价(低波异象的反面)",
            "window": 5,
            "calc": lambda o, h, l, c, v: _rolling_mean((h - l) / (c + 1e-8), 5),
            "default_dir": -1,
        },
        {
            "name": "kbar_high_low_20",
            "formula": "mean((high-low)/close, 20d)",
            "econ": "20日振幅: 中期波动率代理，与volatility_20相关但用日内极值而非收盘价",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean((h - l) / (c + 1e-8), 20),
            "default_dir": -1,
        },
        {
            "name": "kbar_close_low_5",
            "formula": "mean((close-low)/(high-low+eps), 5d)",
            "econ": "5日收盘位置: 收盘越接近最高价=买方越强=短期动量延续",
            "window": 5,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (c - l) / (h - l + 1e-8), 5
            ),
            "default_dir": +1,
        },
        {
            "name": "kbar_close_low_20",
            "formula": "mean((close-low)/(high-low+eps), 20d)",
            "econ": "20日收盘位置: 中期买方主导度，持续高位=机构吸筹模式",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (c - l) / (h - l + 1e-8), 20
            ),
            "default_dir": +1,
        },
        {
            "name": "kbar_upper_shadow_5",
            "formula": "mean((high-max(open,close))/(high-low+eps), 5d)",
            "econ": "5日上影线: 冲高回落=抛压。高上影=短期见顶信号→看空",
            "window": 5,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (h - np.maximum(o, c)) / (h - l + 1e-8), 5
            ),
            "default_dir": -1,
        },
        {
            "name": "kbar_upper_shadow_20",
            "formula": "mean((high-max(open,close))/(high-low+eps), 20d)",
            "econ": "20日上影线: 持续抛压=流动性提供者在上方卖出=中期阻力",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (h - np.maximum(o, c)) / (h - l + 1e-8), 20
            ),
            "default_dir": -1,
        },
        {
            "name": "kbar_lower_shadow_5",
            "formula": "mean((min(open,close)-low)/(high-low+eps), 5d)",
            "econ": "5日下影线: 下探回升=承接力。高下影=有买方支撑→看多",
            "window": 5,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (np.minimum(o, c) - l) / (h - l + 1e-8), 5
            ),
            "default_dir": +1,
        },
        {
            "name": "kbar_lower_shadow_20",
            "formula": "mean((min(open,close)-low)/(high-low+eps), 20d)",
            "econ": "20日下影线: 持续的底部支撑=中期筑底信号",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (np.minimum(o, c) - l) / (h - l + 1e-8), 20
            ),
            "default_dir": +1,
        },
        # ─── 高级KBAR因子 (Alpha158 + 行为金融) ───
        {
            "name": "kbar_body_direction_20",
            "formula": "mean(sign(close-open)*abs(close-open)/open, 20d)",
            "econ": "20日带方向实体: 正=近期上涨K线主导，负=下跌主导。捕获K线偏向性",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                np.sign(c - o) * np.abs(c - o) / (o + 1e-8), 20
            ),
            "default_dir": -1,  # 反转: 上涨K线过多→后续下跌
        },
        {
            "name": "kbar_open_position_20",
            "formula": "mean((open-low)/(high-low+eps), 20d)",
            "econ": "20日开盘位置: 开盘接近最高价=隔夜利好跳高开盘→日内回落(隔夜跳空效应)",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (o - l) / (h - l + 1e-8), 20
            ),
            "default_dir": -1,
        },
        {
            "name": "kbar_close_vs_open_range_20",
            "formula": "mean((close-open)/(high-low+eps), 20d)",
            "econ": "20日收盘vs开盘相对范围: 正=K线阳线为主，负=阴线为主。量化K线方向信号",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (c - o) / (h - l + 1e-8), 20
            ),
            "default_dir": -1,  # 反转: 阳线过多→后续调整
        },
        {
            "name": "kbar_gap_ratio_20",
            "formula": "mean(abs(open_t - close_{t-1})/close_{t-1}, 20d)",
            "econ": "20日跳空幅度: 频繁跳空=受消息/情绪驱动，衡量隔夜信息冲击强度",
            "window": 20,
            "calc": "special_gap",  # 需要特殊处理shift
            "default_dir": -1,  # 高跳空=不稳定→后续均值回归
        },
        {
            "name": "kbar_range_volatility_ratio_20",
            "formula": "mean((high-low)/close, 20d) / std(close/close_{-1}-1, 20d)",
            "econ": "振幅/收盘波动率比: >1说明日内波动大于隔夜(日内交易者活跃)。Parkinson修正",
            "window": 20,
            "calc": "special_range_vol_ratio",
            "default_dir": -1,
        },
        {
            "name": "kbar_high_breakout_freq_20",
            "formula": "mean(close > high_{rolling_5d_max}, 20d)",
            "econ": "20日突破频率: 收盘价频繁创5日新高=趋势强度(类似Donchian Channel突破)",
            "window": 20,
            "calc": "special_high_breakout",
            "default_dir": +1,
        },
        {
            "name": "kbar_low_breakdown_freq_20",
            "formula": "mean(close < low_{rolling_5d_min}, 20d)",
            "econ": "20日破位频率: 收盘价频繁创5日新低=下行趋势=负动量",
            "window": 20,
            "calc": "special_low_breakdown",
            "default_dir": -1,
        },
        {
            "name": "kbar_upper_to_lower_ratio_20",
            "formula": "mean(upper_shadow/lower_shadow, 20d)",
            "econ": "上影/下影比: >1=上方压力大于下方支撑→看空；<1=下方支撑强→看多",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (h - np.maximum(o, c) + 1e-8) / (np.minimum(o, c) - l + 1e-8), 20
            ),
            "default_dir": -1,
        },
        {
            "name": "kbar_vol_range_corr_20",
            "formula": "corr(volume, (high-low)/close, 20d)",
            "econ": "量价振幅相关: 高=放量必伴随振幅扩大(正常)，低=缩量却大振幅(异常信号)",
            "window": 20,
            "calc": "special_vol_range_corr",
            "default_dir": -1,
        },
        {
            "name": "kbar_intraday_momentum_20",
            "formula": "mean((close-open)/(open+eps), 20d)",
            "econ": "日内动量: 平均日内涨跌幅。正=盘中趋于上涨，Alpha158核心KBAR因子",
            "window": 20,
            "calc": lambda o, h, l, c, v: _rolling_mean(
                (c - o) / (o + 1e-8), 20
            ),
            "default_dir": -1,  # 日内过度上涨→反转
        },
    ]


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """滚动均值(纯numpy，适用于逐股计算)。"""
    result = np.full_like(arr, np.nan, dtype=np.float64)
    min_periods = max(window // 2, 3)
    for i in range(min_periods - 1, len(arr)):
        start = max(0, i - window + 1)
        chunk = arr[start:i + 1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) >= min_periods:
            result[i] = np.mean(valid)
    return result


def _rolling_std(arr: np.ndarray, window: int) -> np.ndarray:
    """滚动标准差。"""
    result = np.full_like(arr, np.nan, dtype=np.float64)
    min_periods = max(window // 2, 3)
    for i in range(min_periods - 1, len(arr)):
        start = max(0, i - window + 1)
        chunk = arr[start:i + 1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) >= min_periods:
            result[i] = np.std(valid, ddof=1)
    return result


def _rolling_corr(a: np.ndarray, b: np.ndarray, window: int) -> np.ndarray:
    """滚动相关系数。"""
    result = np.full(len(a), np.nan, dtype=np.float64)
    min_periods = max(window // 2, 5)
    for i in range(min_periods - 1, len(a)):
        start = max(0, i - window + 1)
        av = a[start:i + 1]
        bv = b[start:i + 1]
        mask = ~(np.isnan(av) | np.isnan(bv))
        if mask.sum() >= min_periods:
            r = np.corrcoef(av[mask], bv[mask])[0, 1]
            result[i] = r if np.isfinite(r) else np.nan
    return result


def _rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    """滚动最大值。"""
    result = np.full_like(arr, np.nan, dtype=np.float64)
    for i in range(window - 1, len(arr)):
        chunk = arr[i - window + 1:i + 1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) > 0:
            result[i] = np.max(valid)
    return result


def _rolling_min(arr: np.ndarray, window: int) -> np.ndarray:
    """滚动最小值。"""
    result = np.full_like(arr, np.nan, dtype=np.float64)
    for i in range(window - 1, len(arr)):
        chunk = arr[i - window + 1:i + 1]
        valid = chunk[~np.isnan(chunk)]
        if len(valid) > 0:
            result[i] = np.min(valid)
    return result


# ════════════════════════════════════════════════════════════════════
# IC HELPERS (同 compute_talib_factors_ic.py 模式)
# ════════════════════════════════════════════════════════════════════

def compute_monthly_ic(
    factor_wide: pd.DataFrame,
    excess_fwd: pd.DataFrame,
    month_ends: list,
    direction: int = 1,
) -> pd.DataFrame:
    """月度截面Spearman IC。"""
    fac = factor_wide.copy()
    fac.index = fac.index.astype(str)
    efwd = excess_fwd.copy()
    efwd.index = efwd.index.astype(str)

    records = []
    for d in month_ends:
        d_str = str(d)
        d_date = pd.Timestamp(d_str).date()
        if d_date < IC_START or d_date > IC_END:
            continue
        if d_str not in fac.index or d_str not in efwd.index:
            continue
        fac_cross = fac.loc[d_str].dropna()
        fwd_cross = efwd.loc[d_str].dropna()
        common = fac_cross.index.intersection(fwd_cross.index)
        if len(common) < 100:
            continue
        vals = direction * fac_cross[common].values
        ic, pval = stats.spearmanr(vals, fwd_cross[common].values)
        records.append({"date": d_str, "ic": ic, "pval": pval, "n_stocks": len(common)})
    return pd.DataFrame(records)


def ic_summary(ic_df: pd.DataFrame) -> dict:
    """IC统计量汇总。"""
    if len(ic_df) == 0:
        return {"ic_mean": np.nan, "ic_std": np.nan, "ic_ir": np.nan,
                "t_stat": np.nan, "pct_pos": np.nan, "n_months": 0}
    ic_mean = ic_df["ic"].mean()
    ic_std = ic_df["ic"].std()
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
    t_stat = ic_mean / (ic_std / np.sqrt(len(ic_df))) if ic_std > 0 else 0
    pct_pos = (ic_df["ic"] > 0).mean() * 100
    return {"ic_mean": ic_mean, "ic_std": ic_std, "ic_ir": ic_ir,
            "t_stat": t_stat, "pct_pos": pct_pos, "n_months": len(ic_df)}


def print_ic_report(name: str, formula: str, ic_df: pd.DataFrame, direction: int) -> dict | None:
    """打印完整IC报告(含年度分解)。"""
    s = ic_summary(ic_df)
    if s["n_months"] == 0:
        print(f"\n  {name}: NO DATA")
        return None

    ic_df = ic_df.copy()
    ic_df["date"] = pd.to_datetime(ic_df["date"])
    ic_df["year"] = ic_df["date"].dt.year

    sig = (
        "***" if abs(s["t_stat"]) > 2.58
        else "**" if abs(s["t_stat"]) > 1.96
        else "*" if abs(s["t_stat"]) > 1.64
        else "ns"
    )

    print(f"\n{'='*75}")
    print(f"  {name} (direction={direction:+d})")
    print(f"  Formula: {formula}")
    print(f"{'='*75}")
    print(f"  IC Mean:   {s['ic_mean']:+.4f} ({abs(s['ic_mean'])*100:.2f}%)")
    print(f"  IC Std:    {s['ic_std']:.4f}")
    print(f"  IC_IR:     {s['ic_ir']:.4f}")
    print(f"  t-stat:    {s['t_stat']:.2f} {sig}")
    print(f"  IC > 0:    {s['pct_pos']:.1f}%")
    print(f"  Months:    {s['n_months']}")

    # Annual breakdown
    print(f"\n  {'Year':<6} {'IC_Mean':>8} {'IC_Std':>8} {'IC_IR':>8} {'t':>6} {'IC>0%':>6} {'N':>3}")
    print(f"  {'-'*46}")
    for year, grp in ic_df.groupby("year"):
        ym = grp["ic"].mean()
        ys = grp["ic"].std()
        yir = ym / ys if ys > 0 else 0
        yt = ym / (ys / np.sqrt(len(grp))) if ys > 0 else 0
        yp = (grp["ic"] > 0).mean() * 100
        print(f"  {year:<6} {ym:>+8.4f} {ys:>8.4f} {yir:>8.4f} {yt:>6.2f} {yp:>5.1f}% {len(grp):>3}")

    verdict = (
        "PASS" if abs(s["t_stat"]) > 1.96 and abs(s["ic_mean"]) > 0.02
        else "MARGINAL" if abs(s["t_stat"]) > 1.64 and abs(s["ic_mean"]) > 0.015
        else "FAIL"
    )
    print(f"\n  VERDICT: {verdict} (t={s['t_stat']:.2f}, IC={s['ic_mean']:.4f})")

    return {
        "name": name, "direction": direction, "formula": formula,
        **s, "verdict": verdict,
    }


# ════════════════════════════════════════════════════════════════════
# PER-STOCK FACTOR COMPUTATION
# ════════════════════════════════════════════════════════════════════

def compute_factor_wide(
    factor_def: dict,
    klines_grouped: dict,
    codes: list,
    dates_all: np.ndarray,
) -> pd.DataFrame:
    """逐股计算KBAR因子，返回wide格式。"""
    name = factor_def["name"]
    calc = factor_def["calc"]
    result = {}
    n_ok = 0
    n_fail = 0

    for code in codes:
        if code not in klines_grouped:
            continue
        gdf = klines_grouped[code]
        if len(gdf) < 30:
            continue
        try:
            o = gdf["open_price"].values.astype(np.float64)
            h = gdf["high_price"].values.astype(np.float64)
            l = gdf["low_price"].values.astype(np.float64)
            c = gdf["close_price"].values.astype(np.float64)
            v = gdf["volume"].values.astype(np.float64)
            dates_code = gdf["trade_date"].values

            if callable(calc):
                vals = calc(o, h, l, c, v)
            elif calc == "special_gap":
                # abs(open_t - close_{t-1}) / close_{t-1}
                prev_close = np.roll(c, 1)
                prev_close[0] = np.nan
                gap = np.abs(o - prev_close) / (prev_close + 1e-8)
                gap[0] = np.nan
                vals = _rolling_mean(gap, 20)
            elif calc == "special_range_vol_ratio":
                # range/volatility ratio
                day_range = (h - l) / (c + 1e-8)
                range_mean = _rolling_mean(day_range, 20)
                ret = np.diff(c) / c[:-1]
                ret = np.insert(ret, 0, np.nan)
                ret_std = _rolling_std(ret, 20)
                vals = range_mean / (ret_std + 1e-8)
            elif calc == "special_high_breakout":
                # close > rolling_5d_max of high (shifted by 1 to avoid lookahead)
                high_max = _rolling_max(h, 5)
                # compare close_t with max(high_{t-5..t-1})
                prev_high_max = np.roll(high_max, 1)
                prev_high_max[0] = np.nan
                breakout = np.where(
                    ~np.isnan(prev_high_max),
                    (c > prev_high_max).astype(float),
                    np.nan,
                )
                vals = _rolling_mean(breakout, 20)
            elif calc == "special_low_breakdown":
                low_min = _rolling_min(l, 5)
                prev_low_min = np.roll(low_min, 1)
                prev_low_min[0] = np.nan
                breakdown = np.where(
                    ~np.isnan(prev_low_min),
                    (c < prev_low_min).astype(float),
                    np.nan,
                )
                vals = _rolling_mean(breakdown, 20)
            elif calc == "special_vol_range_corr":
                day_range = (h - l) / (c + 1e-8)
                vals = _rolling_corr(v, day_range, 20)
            else:
                raise ValueError(f"Unknown calc type: {calc}")

            s = pd.Series(vals, index=dates_code, name=code)
            result[code] = s
            n_ok += 1
        except Exception:
            n_fail += 1
            continue

    if n_ok % 500 == 0 or n_fail > 0:
        pass  # silent
    print(f"  [{name}] OK: {n_ok}, fail: {n_fail}")
    wide = pd.DataFrame(result)
    wide = wide.reindex(dates_all)
    return wide


# ════════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════════

def main():
    print_config_header()
    t0 = time.time()

    # ════════════════════════════════════════════════════════════════
    # DATA LOADING
    # ════════════════════════════════════════════════════════════════
    conn = psycopg2.connect(DB_URI)

    print("[DATA] Loading klines_daily (OHLCV + adj)...")
    klines = pd.read_sql(
        """
        SELECT code, trade_date,
               open::float  AS open_price,
               high::float  AS high_price,
               low::float   AS low_price,
               close::float AS close_price,
               close::float * adj_factor::float AS adj_close,
               volume::float AS volume
        FROM klines_daily
        WHERE trade_date >= %s AND volume > 0
        ORDER BY code, trade_date
        """,
        conn,
        params=(DATA_START,),
    )
    print(f"  Rows: {len(klines):,}, codes: {klines['code'].nunique()}")

    print("[DATA] Loading CSI300 benchmark...")
    bench = pd.read_sql(
        """
        SELECT trade_date, close::float
        FROM index_daily WHERE index_code='000300.SH' AND trade_date >= %s
        ORDER BY trade_date
        """,
        conn,
        params=(DATA_START,),
    )

    # Existing factors for correlation pre-screen
    print("[DATA] Loading existing factors for correlation pre-screen...")
    existing_factors = pd.read_sql(
        """
        SELECT code, trade_date, factor_name, zscore::float AS value
        FROM factor_values
        WHERE factor_name IN (%s)
          AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
        """ % ",".join(f"'{f}'" for f in CORR_CHECK_FACTORS),
        conn,
    )
    print(f"  Existing factor rows: {len(existing_factors):,}")

    # Load volatility_20 zscore separately for Task 2 residual
    print("[DATA] Loading volatility_20 zscore for residual regression...")
    vol20_raw = pd.read_sql(
        """
        SELECT code, trade_date, zscore::float AS vol20_zscore
        FROM factor_values
        WHERE factor_name = 'volatility_20' AND trade_date >= '2021-01-01'
        ORDER BY trade_date, code
        """,
        conn,
    )

    conn.close()

    # ── Pivot adj_close for forward returns ──
    print("[DATA] Pivoting adj_close...")
    adj_close_wide = klines.pivot(index="trade_date", columns="code", values="adj_close")
    close_raw_wide = klines.pivot(index="trade_date", columns="code", values="close_price")
    high_wide = klines.pivot(index="trade_date", columns="code", values="high_price")
    dates_all = adj_close_wide.index.sort_values()

    bench_close = bench.set_index("trade_date")["close"].reindex(dates_all)

    # ── 20-day forward excess return ──
    print("[DATA] Computing 20-day forward excess return...")
    fwd_ret_20 = adj_close_wide.shift(-20) / adj_close_wide - 1
    bench_fwd_20 = bench_close.shift(-20) / bench_close - 1
    excess_fwd_20 = fwd_ret_20.sub(bench_fwd_20, axis=0)

    # ── Month-end dates ──
    dates_series = pd.Series(dates_all)
    dates_dt = pd.to_datetime(dates_series)
    month_ends = dates_series.groupby(dates_dt.dt.to_period("M")).last().values
    month_ends = [str(d) for d in month_ends]

    print(f"[DATA] {len(dates_all)} trading days, {len(month_ends)} month-ends")

    # ── Group klines by code ──
    print("[DATA] Grouping klines by code...")
    klines_grouped = {code: gdf for code, gdf in klines.groupby("code")}
    codes = sorted(klines_grouped.keys())
    print(f"  {len(codes)} codes grouped")

    # Existing factor pivots for correlation
    existing_pivots = {}
    for fname, fgrp in existing_factors.groupby("factor_name"):
        fp = fgrp.pivot(index="trade_date", columns="code", values="value")
        fp.index = fp.index.astype(str)
        existing_pivots[fname] = fp

    # vol_20 wide for Task 2
    vol20_wide = vol20_raw.pivot(index="trade_date", columns="code", values="vol20_zscore")
    vol20_wide.index = vol20_wide.index.astype(str)

    t_load = time.time() - t0
    print(f"[DATA] Total load time: {t_load:.1f}s\n")

    # ════════════════════════════════════════════════════════════════
    # TASK 1: 20 KBAR FACTORS IC ANALYSIS
    # ════════════════════════════════════════════════════════════════
    print("#" * 80)
    print("# TASK 1: ALPHA158 KBAR FACTORS IC ANALYSIS (20 factors)")
    print("#" * 80)

    factor_defs = define_kbar_factors()
    results = []
    factor_wides = {}

    for i, fdef in enumerate(factor_defs, 1):
        print(f"\n{'─'*70}")
        print(f"  [{i}/{len(factor_defs)}] {fdef['name']}")
        print(f"  Econ: {fdef['econ']}")
        print(f"{'─'*70}")

        fwide = compute_factor_wide(fdef, klines_grouped, codes, dates_all)
        factor_wides[fdef["name"]] = fwide

        # Test both directions, pick best
        ic_pos = compute_monthly_ic(fwide, excess_fwd_20, month_ends, direction=+1)
        ic_neg = compute_monthly_ic(fwide, excess_fwd_20, month_ends, direction=-1)

        mean_pos = ic_pos["ic"].mean() if len(ic_pos) > 0 else 0
        mean_neg = ic_neg["ic"].mean() if len(ic_neg) > 0 else 0

        if abs(mean_neg) >= abs(mean_pos):
            ic_best = ic_neg
            best_dir = -1
        else:
            ic_best = ic_pos
            best_dir = +1

        r = print_ic_report(
            fdef["name"],
            fdef["formula"],
            ic_best,
            best_dir,
        )
        if r:
            r["econ"] = fdef["econ"]
            r["default_dir"] = fdef["default_dir"]
            results.append(r)

    # ════════════════════════════════════════════════════════════════
    # CORRELATION PRE-SCREEN (vs vol_20 / reversal_20 / turnover_mean_20)
    # ════════════════════════════════════════════════════════════════
    print(f"\n\n{'#'*80}")
    print("# CORRELATION PRE-SCREEN: KBAR vs Existing Factors")
    print(f"{'#'*80}")

    # Sample dates for correlation (every 3rd month-end from 2021-2025)
    sample_dates_corr = [
        d for d in month_ends
        if "2021-01" <= d <= "2025-12-31"
    ][::3][:20]

    key_check = ["volatility_20", "reversal_20", "turnover_mean_20"]
    new_names = [r["name"] for r in results]

    print(f"\n  {'KBAR Factor':<32}", end="")
    for kf in key_check:
        print(f" {kf[:18]:>18}", end="")
    print(f" {'Redundancy':>12}")
    print(f"  {'-'*92}")

    for nn in new_names:
        if nn not in factor_wides:
            continue
        nf = factor_wides[nn].copy()
        nf.index = nf.index.astype(str)

        print(f"  {nn:<32}", end="")
        max_corr = 0
        for kf in key_check:
            if kf not in existing_pivots:
                print(f" {'N/A':>18}", end="")
                continue
            corrs = []
            for d in sample_dates_corr:
                if d in nf.index and d in existing_pivots[kf].index:
                    f1 = nf.loc[d].dropna()
                    f2 = existing_pivots[kf].loc[d].dropna()
                    common = f1.index.intersection(f2.index)
                    if len(common) > 100:
                        c, _ = stats.spearmanr(f1[common].values, f2[common].values)
                        corrs.append(c)
            avg_c = np.mean(corrs) if corrs else np.nan
            if not np.isnan(avg_c) and abs(avg_c) > max_corr:
                max_corr = abs(avg_c)
            flag = " !" if not np.isnan(avg_c) and abs(avg_c) > 0.5 else ""
            print(f" {avg_c:>17.4f}{flag}", end="")

        # Mark redundancy risk
        if max_corr > 0.6:
            print(f" {'HIGH RISK':>12}", end="")
        elif max_corr > 0.4:
            print(f" {'MODERATE':>12}", end="")
        else:
            print(f" {'LOW':>12}", end="")
        print()

    # ════════════════════════════════════════════════════════════════
    # TASK 1 SUMMARY TABLE
    # ════════════════════════════════════════════════════════════════
    print(f"\n\n{'='*95}")
    print("TASK 1 SUMMARY: 20 KBAR FACTORS IC (20d fwd excess return, 2021-2025)")
    print(f"{'='*95}")
    print(
        f"  {'#':<3} {'Factor':<32} {'Dir':>4} {'IC_Mean':>8} {'t-stat':>8} "
        f"{'IC_IR':>8} {'IC>0%':>6} {'N':>4} {'Verdict':>10}"
    )
    print(f"  {'-'*88}")

    n_pass = 0
    n_marginal = 0
    for i, r in enumerate(results, 1):
        print(
            f"  {i:<3} {r['name']:<32} {r['direction']:>+4d} {r['ic_mean']:>+8.4f} "
            f"{r['t_stat']:>8.2f} {r['ic_ir']:>8.4f} {r['pct_pos']:>5.1f}% "
            f"{r['n_months']:>4} {r['verdict']:>10}"
        )
        if r["verdict"] == "PASS":
            n_pass += 1
        elif r["verdict"] == "MARGINAL":
            n_marginal += 1

    print(f"\n  Results: {n_pass} PASS, {n_marginal} MARGINAL, "
          f"{len(results) - n_pass - n_marginal} FAIL out of {len(results)} factors")

    # ════════════════════════════════════════════════════════════════
    # TASK 2: CLOSE_TO_HIGH RESIDUAL IC
    # ════════════════════════════════════════════════════════════════
    print(f"\n\n{'#'*80}")
    print("# TASK 2: CLOSE_TO_HIGH_RATIO_20 RESIDUAL IC (regress out vol_20)")
    print(f"{'#'*80}")
    print("Background: close_to_high_ratio_20 corr with vol_20 = -0.65")
    print("Method: OLS residual per cross-section date, then IC of residual")
    print("Pass: residual |IC| > 3% and t > 2.0")
    print("Fail: residual |IC| < 2% => redundant with vol_20")

    # Compute close_to_high_ratio_20
    cl = close_raw_wide.reindex(dates_all)
    hi = high_wide.reindex(dates_all)
    close_to_high = cl / hi.replace(0, np.nan)
    close_to_high_20 = close_to_high.rolling(window=20, min_periods=15).mean()
    close_to_high_20.index = close_to_high_20.index.astype(str)

    # 2a. Raw IC
    print("\n--- 2a. Raw close_to_high_ratio_20 IC ---")
    ic_c2h_pos = compute_monthly_ic(close_to_high_20, excess_fwd_20, month_ends, direction=+1)
    ic_c2h_neg = compute_monthly_ic(close_to_high_20, excess_fwd_20, month_ends, direction=-1)

    if len(ic_c2h_neg) > 0 and len(ic_c2h_pos) > 0:
        if abs(ic_c2h_neg["ic"].mean()) > abs(ic_c2h_pos["ic"].mean()):
            c2h_dir = -1
            ic_c2h_raw = ic_c2h_neg
            print("  Best direction: -1 (close near high => reversal)")
        else:
            c2h_dir = +1
            ic_c2h_raw = ic_c2h_pos
            print("  Best direction: +1 (close near high => continuation)")
    else:
        c2h_dir = -1
        ic_c2h_raw = ic_c2h_neg if len(ic_c2h_neg) > 0 else ic_c2h_pos

    s_raw = ic_summary(ic_c2h_raw)
    print(f"  Raw IC Mean: {s_raw['ic_mean']:+.4f}, t={s_raw['t_stat']:.2f}, "
          f"IR={s_raw['ic_ir']:.4f}, months={s_raw['n_months']}")

    # 2b. Correlation verification
    print("\n--- 2b. Cross-sectional correlation with vol_20 ---")
    corr_samples = []
    sample_dates_c2h = [d for d in month_ends if "2021-01" <= d <= "2025-12-31"][::3]
    for d in sample_dates_c2h:
        if d in close_to_high_20.index and d in vol20_wide.index:
            c2h = close_to_high_20.loc[d].dropna()
            v20 = vol20_wide.loc[d].dropna()
            common = c2h.index.intersection(v20.index)
            if len(common) > 100:
                c, _ = stats.spearmanr(c2h[common].values, v20[common].values)
                corr_samples.append(c)
    if corr_samples:
        avg_corr = np.mean(corr_samples)
        print(f"  Avg Spearman corr(close_to_high, vol_20): {avg_corr:.4f} "
              f"(N={len(corr_samples)} sample dates)")
    else:
        avg_corr = np.nan
        print("  WARNING: Could not compute correlation")

    # 2c. Residual IC: regress out vol_20 per cross-section
    print("\n--- 2c. Residual IC (after regressing out vol_20) ---")
    residual_wide_rows = {}
    n_dates_ok = 0
    for d in close_to_high_20.index:
        if d not in vol20_wide.index:
            continue
        c2h = close_to_high_20.loc[d].dropna()
        v20 = vol20_wide.loc[d].dropna()
        common = c2h.index.intersection(v20.index)
        if len(common) < 100:
            continue
        # OLS: c2h = alpha + beta * vol20 + residual
        x = v20[common].values
        y = c2h[common].values
        X = np.column_stack([np.ones(len(x)), x])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            residuals = y - X @ beta
            residual_wide_rows[d] = pd.Series(residuals, index=common)
            n_dates_ok += 1
        except Exception:
            continue

    residual_wide = pd.DataFrame(residual_wide_rows).T
    residual_wide.index.name = "trade_date"
    print(f"  Residual computed for {n_dates_ok} dates")

    # IC of residual
    ic_resid_pos = compute_monthly_ic(residual_wide, excess_fwd_20, month_ends, direction=+1)
    ic_resid_neg = compute_monthly_ic(residual_wide, excess_fwd_20, month_ends, direction=-1)

    if len(ic_resid_pos) > 0 and len(ic_resid_neg) > 0:
        if abs(ic_resid_neg["ic"].mean()) > abs(ic_resid_pos["ic"].mean()):
            resid_dir = -1
            ic_resid = ic_resid_neg
        else:
            resid_dir = +1
            ic_resid = ic_resid_pos
    else:
        resid_dir = +1
        ic_resid = ic_resid_pos if len(ic_resid_pos) > 0 else ic_resid_neg

    r_resid = print_ic_report(
        "close_to_high RESIDUAL (vol_20 removed)",
        "OLS residual: close_to_high_20 ~ vol_20",
        ic_resid,
        resid_dir,
    )

    # 2d. Verdict
    s_resid = ic_summary(ic_resid)
    resid_ic = abs(s_resid["ic_mean"]) if s_resid["n_months"] > 0 else 0
    resid_t = abs(s_resid["t_stat"]) if s_resid["n_months"] > 0 else 0

    print(f"\n{'='*75}")
    print("TASK 2 VERDICT: close_to_high_ratio_20 RESIDUAL IC")
    print(f"{'='*75}")
    print(f"  Raw IC:       {s_raw['ic_mean']:+.4f} (t={s_raw['t_stat']:.2f})")
    print(f"  Corr(c2h, vol_20): {avg_corr:.4f}")
    print(f"  Residual |IC|: {resid_ic*100:.2f}%")
    print(f"  Residual |t|:  {resid_t:.2f}")

    if resid_ic > 0.03 and resid_t > 2.0:
        print(f"\n  >>> PASS: Residual IC={resid_ic*100:.2f}% > 3%, t={resid_t:.2f} > 2.0")
        print("      INDEPENDENT ALPHA confirmed. Worth adding to factor pool.")
    elif resid_ic > 0.02 and resid_t > 1.64:
        print(f"\n  >>> MARGINAL: Residual IC={resid_ic*100:.2f}%, t={resid_t:.2f}")
        print("      Weak independent signal. Monitor but don't add yet.")
    else:
        print(f"\n  >>> FAIL: Residual IC={resid_ic*100:.2f}% < 2% or t={resid_t:.2f} < 2.0")
        print("      REDUNDANT with vol_20. Drop from candidate pool.")

    # ════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ════════════════════════════════════════════════════════════════
    total_time = time.time() - t0
    print(f"\n\n{'#'*80}")
    print("# FINAL SUMMARY")
    print(f"{'#'*80}")
    print(f"\nTask 1: {n_pass} PASS + {n_marginal} MARGINAL out of {len(results)} KBAR factors")

    if n_pass > 0:
        print("\n  PASS factors (recommend for factor审查):")
        for r in results:
            if r["verdict"] == "PASS":
                print(f"    - {r['name']}: IC={r['ic_mean']:+.4f}, t={r['t_stat']:.2f}, "
                      f"dir={r['direction']:+d}")
                print(f"      Econ: {r['econ']}")

    if n_marginal > 0:
        print("\n  MARGINAL factors (monitor, may add with lower weight):")
        for r in results:
            if r["verdict"] == "MARGINAL":
                print(f"    - {r['name']}: IC={r['ic_mean']:+.4f}, t={r['t_stat']:.2f}")

    c2h_verdict_str = (
        "INDEPENDENT ALPHA" if resid_ic > 0.03 and resid_t > 2.0
        else "MARGINAL" if resid_ic > 0.02
        else "REDUNDANT"
    )
    print(f"\nTask 2: close_to_high residual => {c2h_verdict_str}")

    print(f"\nTotal execution time: {total_time:.1f}s")


if __name__ == "__main__":
    main()
