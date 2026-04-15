"""因子画像系统 (Factor Profiler) — V2 严谨版。

对每个因子计算标准化特征画像：多周期IC(含t-stat+120d天花板检测)、
分位收益单调性(含选股建议)、排名自相关、换手率、行业中性IC、
regime敏感性(方向反转判定)、trigger_type判定、成本可行性校验、
冗余因子标注、FMP候选识别、多模板评分。

Forward return方法: close[T+1] → close[T+h]（T+1入场，A股T+1制度）
超额收益基准: CSI300同期收益

V2变更 (2026-04-05):
  - Fix1: regime切换仅在bull/bear IC方向反转时推荐模板12
  - Fix2: 补测120d IC + 60d天花板检测
  - Fix3: monotonicity影响选股方式建议
  - Fix4: 成本可行性校验(周度/日频)
  - Fix5: 冗余因子标注(corr>0.85择一, corr<-0.85 mirror pair)
  - Fix6: FMP独立组合候选识别(聚类代表+低相关)
  - Fix7: 多模板Top-2推荐+评分

用法:
    from engines.factor_profiler import profile_all_factors
    profiles = profile_all_factors()
"""

import logging
import time
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

HORIZONS = [1, 5, 10, 20, 60, 120]  # V2: 加120d天花板检测
START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)
FWD_METHOD = "close_t1_to_close_th"
MIN_STOCKS = 30
COST_PER_TRADE = 0.001  # 0.1% 单边(佣万0.854+印花税万5+过户费万0.1+微量滑点)
REBAL_FREQ = {
    "monthly": 12,
    "biweekly": 26,
    "weekly": 52,
    "daily_signal": 252,
    "event_trigger": 4,
    "regime_switch": 6,
}
TMPL_NAMES = {1: "月度", 2: "周度", 7: "事件", 11: "仓位", 12: "regime切换"}


def _get_conn():
    from app.services.db import get_sync_conn
    return get_sync_conn()


def _f(v):
    """numpy/decimal -> Python float, None-safe."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def _load_shared_data(conn):
    """预加载共享数据（一次加载，所有因子复用）。

    优先读Parquet缓存（cache/），回退到DB查询。
    缓存由 scripts/precompute_cache.py --quick 生成。
    """
    import os

    cache_dir = os.path.join(os.path.dirname(__file__), "..", "..", "cache")
    use_cache = os.path.exists(os.path.join(cache_dir, "close_pivot.parquet"))

    if use_cache:
        logger.info("加载共享数据(Parquet缓存)...")
        t0 = time.time()

        close_pivot = pd.read_parquet(os.path.join(cache_dir, "close_pivot.parquet"))
        trading_dates = sorted(close_pivot.index)

        fwd_excess = {}
        for h in HORIZONS:
            fwd_excess[h] = pd.read_parquet(os.path.join(cache_dir, f"fwd_excess_{h}d.parquet"))

        csi_monthly_df = pd.read_parquet(os.path.join(cache_dir, "csi_monthly.parquet"))
        csi_monthly = csi_monthly_df.iloc[:, 0]

        industry_df = pd.read_parquet(os.path.join(cache_dir, "industry_map.parquet"))
        industry_map = industry_df.set_index("code")["industry_sw1"].fillna("其他")

        logger.info("共享数据加载完成(缓存): %.1fs", time.time() - t0)
        return close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates

    # 回退: 从DB加载（原逻辑）
    logger.info("加载共享数据(DB回退)...")
    t0 = time.time()

    close_df = pd.read_sql(
        "SELECT code, trade_date, close * adj_factor as adj_close "
        "FROM klines_daily WHERE trade_date BETWEEN %s AND %s AND volume > 0",
        conn,
        params=(START_DATE, date(2026, 6, 30)),
    )
    close_pivot = close_df.pivot(
        index="trade_date", columns="code", values="adj_close"
    ).sort_index()
    trading_dates = sorted(close_pivot.index)

    csi = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code='000300.SH' AND trade_date BETWEEN %s AND %s",
        conn,
        params=(START_DATE, date(2026, 6, 30)),
    )
    csi_close = csi.set_index("trade_date")["close"].sort_index()

    fwd_excess = {}
    for h in HORIZONS:
        entry = close_pivot.shift(-1)          # Buy at T+1 close
        exit_p = close_pivot.shift(-(1 + h))   # Sell at T+1+h close (hold h days)
        stock_ret = exit_p / entry - 1
        csi_entry = csi_close.shift(-1)
        csi_exit = csi_close.shift(-(1 + h))
        idx_ret = csi_exit / csi_entry - 1
        fwd_excess[h] = stock_ret.sub(idx_ret, axis=0)

    csi_dt = csi_close.copy()
    csi_dt.index = pd.to_datetime(csi_dt.index)
    csi_monthly = csi_dt.resample("ME").last().pct_change().dropna()

    industry = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market='astock'", conn)
    # SW2→SW1映射: 110组→29组, 避免小组WLS不稳定
    from app.services.industry_utils import apply_sw2_to_sw1
    sw2_series = industry.set_index("code")["industry_sw1"].fillna("其他")
    industry_map = apply_sw2_to_sw1(sw2_series, conn)

    logger.info("共享数据加载完成(DB): %.1fs", time.time() - t0)
    return close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates


def _score_templates(p: dict) -> list[tuple[int, float]]:
    """多模板评分，返回[(template_id, score), ...]降序排列。"""
    scores = {}
    opt_h = p.get("optimal_horizon", 20)
    ac5 = p.get("rank_autocorr_5d", 0.9)
    ac1 = p.get("rank_autocorr_1d", 0.9)
    mono = abs(p.get("monotonicity", 0))
    trig = p.get("trigger_type", "ranking")
    cost_ok = p.get("cost_feasible", True)
    turnover_m = p.get("top_q_turnover_monthly", 0)
    ic_bull = p.get("ic_bull", 0)
    ic_bear = p.get("ic_bear", 0)
    regime_s = p.get("regime_sensitivity", 0)

    # 模板1: 月度RANKING
    s = 0.0
    s += 0.3 * min(1.0, ac5 / 0.95)
    s += 0.3 * min(1.0, max(0, opt_h - 10) / 50)
    s += 0.2 * min(1.0, mono)
    s += 0.2 * (1.0 if trig == "ranking" else 0.3)
    scores[1] = min(1.0, s)

    # 模板2: 周度RANKING
    s = 0.0
    s += 0.3 * max(0, 1.0 - ac5)
    s += 0.3 * (max(0, 1.0 - opt_h / 15) if opt_h < 20 else 0)
    s += 0.2 * min(1.0, mono)
    s += 0.2 * (0.8 if cost_ok else 0.2)
    scores[2] = min(1.0, s)

    # 模板11: 仓位调节/Modifier
    s = 0.0
    s += 0.4 * (1.0 if trig == "modifier" else 0.2)
    s += 0.3 * max(0, 1.0 - ac1)
    s += 0.3 * min(1.0, turnover_m / 0.8)
    scores[11] = min(1.0, s)

    # 模板12: regime切换 — 仅方向反转时高分
    s = 0.0
    opposite = (ic_bull > 0 and ic_bear < 0) or (ic_bull < 0 and ic_bear > 0)
    if opposite:
        s += 0.5
        s += 0.25 * min(1.0, min(abs(ic_bull), abs(ic_bear)) / 0.03)
        s += 0.25 * min(1.0, regime_s / 0.05)
    else:
        s = 0.05
    scores[12] = min(1.0, s)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def profile_factor(
    factor_name: str,
    close_pivot: pd.DataFrame,
    fwd_excess: dict,
    csi_monthly: pd.Series,
    industry_map: pd.Series,
    trading_dates: list,
    conn=None,
    all_factor_names: list | None = None,
) -> dict:
    """计算单因子严谨画像。"""
    close_conn = conn is None
    if conn is None:
        conn = _get_conn()
    t0 = time.time()

    # 加载因子值（中性化后，含universe过滤）
    fv = pd.read_sql(
        "SELECT f.code, f.trade_date, f.neutral_value "
        "FROM factor_values f JOIN symbols s ON f.code = s.code "
        "WHERE f.factor_name=%s AND f.trade_date BETWEEN %s AND %s "
        "AND f.neutral_value IS NOT NULL AND s.list_status='L' "
        "AND s.name NOT LIKE '%%ST%%'",
        conn,
        params=(factor_name, START_DATE, END_DATE),
    )
    if fv.empty:
        logger.warning("%s: 无数据", factor_name)
        if close_conn:
            conn.close()
        return {"factor_name": factor_name, "error": "no data"}

    # pivot: trade_date x code
    fv_pivot = fv.pivot_table(index="trade_date", columns="code", values="neutral_value")
    fv_dates = sorted(fv_pivot.index)

    # 覆盖度
    avg_coverage = fv_pivot.notna().sum(axis=1).mean() / 5000

    # === 1. 多周期IC + t-stat (含120d) ===
    ic_results = {}
    months = {}
    for td in fv_dates:
        ym = (td.year, td.month)
        months.setdefault(ym, []).append(td)

    for h in HORIZONS:
        fwd = fwd_excess.get(h)
        if fwd is None:
            continue
        monthly_ics = []
        for _ym, dates in months.items():
            last_d = max(dates)
            if last_d not in fv_pivot.index or last_d not in fwd.index:
                continue
            f_vals = fv_pivot.loc[last_d].dropna()
            r_vals = fwd.loc[last_d]
            merged = pd.DataFrame({"f": f_vals, "r": r_vals}).dropna()
            if len(merged) < MIN_STOCKS:
                continue
            ic, _ = sp_stats.spearmanr(merged["f"], merged["r"])
            if not np.isnan(ic):
                monthly_ics.append(ic)

        if monthly_ics:
            ic_mean = float(np.mean(monthly_ics))
            ic_std = float(np.std(monthly_ics))
            n = len(monthly_ics)
            t_stat = ic_mean / (ic_std / np.sqrt(n)) if ic_std > 1e-12 else 0
            ic_results[h] = {
                "mean": ic_mean,
                "std": ic_std,
                "t": float(t_stat),
                "n": n,
                "ics": monthly_ics,
            }
        else:
            ic_results[h] = {"mean": 0, "std": 0, "t": 0, "n": 0, "ics": []}

    # 最优horizon + 120d天花板检测
    abs_ics = {h: abs(r["mean"]) for h, r in ic_results.items() if r["mean"] != 0}
    optimal_h = max(abs_ics, key=abs_ics.get) if abs_ics else 20

    ic_120 = ic_results.get(120, {}).get("mean", 0)
    ic_120_t = ic_results.get(120, {}).get("t", 0)
    ic_60_abs = abs(ic_results.get(60, {}).get("mean", 0))
    ic_120_abs = abs(ic_120)

    horizon_note = ""
    if optimal_h >= 60 and ic_120_abs > ic_60_abs * 1.02:
        horizon_note = f">=120d（IC仍在上升, 120d={ic_120:+.4f} > 60d, 未达峰值）"
    elif optimal_h >= 60 and ic_120_abs > 0:
        horizon_note = f"60d确认峰值（120d IC={ic_120:+.4f}衰减）"

    # IC IR和胜率（用20d）
    ics_20 = ic_results.get(20, {}).get("ics", [])
    ic_ir = float(np.mean(ics_20) / (np.std(ics_20) + 1e-12)) if ics_20 else 0
    ic_pos_ratio = float(np.mean([1 for x in ics_20 if x > 0])) if ics_20 else 0

    # IC趋势（最近12月 vs 前面）
    ic_trend = "stable"
    if len(ics_20) >= 24:
        recent = np.mean(ics_20[-12:])
        earlier = np.mean(ics_20[:-12])
        if abs(recent) < abs(earlier) * 0.5:
            ic_trend = "decaying"
        elif abs(recent) > abs(earlier) * 1.5:
            ic_trend = "improving"

    # === 2. IC半衰期 ===
    ic_halflife = None
    if abs_ics:
        peak_h = max(abs_ics, key=abs_ics.get)
        peak_v = abs_ics[peak_h]
        for h in sorted(abs_ics.keys()):
            if h > peak_h and abs_ics[h] < peak_v * 0.5:
                ic_halflife = h - peak_h
                break

    # === 3. 分位收益 + 单调性 ===
    fwd20 = fwd_excess.get(20)
    if fwd20 is not None:
        recent_months = sorted(months.keys())[-12:] if months else []
        all_q_rets = {q: [] for q in range(1, 6)}
        for ym in recent_months:
            last_d = max(months[ym])
            if last_d not in fv_pivot.index or last_d not in fwd20.index:
                continue
            f_vals = fv_pivot.loc[last_d].dropna()
            r_vals = fwd20.loc[last_d]
            merged = pd.DataFrame({"f": f_vals, "r": r_vals}).dropna()
            if len(merged) < 100:
                continue
            try:
                merged["q"] = pd.qcut(merged["f"], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
            except ValueError:
                continue
            for q in range(1, 6):
                qr = merged[merged["q"] == q]["r"].mean()
                all_q_rets[q].append(qr)

        quintile_means = [np.mean(all_q_rets[q]) if all_q_rets[q] else 0 for q in range(1, 6)]
        quintile_spread = quintile_means[4] - quintile_means[0]
        mono, _ = sp_stats.spearmanr([1, 2, 3, 4, 5], quintile_means)
        monotonicity = float(mono) if not np.isnan(mono) else 0
    else:
        quintile_spread = 0
        monotonicity = 0
        quintile_means = [0] * 5

    # === 4. 排名自相关 ===
    rank_ac = {}
    for lag in [1, 5, 20]:
        acs = []
        sample_dates = fv_dates[:: max(lag, 1)][:100]
        for i in range(len(sample_dates) - 1):
            d1, d2 = sample_dates[i], sample_dates[min(i + 1, len(sample_dates) - 1)]
            if d1 not in fv_pivot.index or d2 not in fv_pivot.index:
                continue
            r1 = fv_pivot.loc[d1].rank()
            r2 = fv_pivot.loc[d2].rank()
            merged = pd.DataFrame({"a": r1, "b": r2}).dropna()
            if len(merged) < 100:
                continue
            c, _ = sp_stats.spearmanr(merged["a"], merged["b"])
            if not np.isnan(c):
                acs.append(c)
        rank_ac[lag] = float(np.mean(acs)) if acs else 0.99

    # === 5. 换手率（Top quintile） ===
    top_turnover_m = 0
    prev_top = set()
    monthly_turnovers = []
    for ym in sorted(months.keys()):
        last_d = max(months[ym])
        if last_d not in fv_pivot.index:
            continue
        vals = fv_pivot.loc[last_d].dropna()
        if len(vals) < 50:
            continue
        top_q = set(vals.nlargest(len(vals) // 5).index)
        if prev_top:
            turnover = len(top_q - prev_top) / max(len(top_q), 1)
            monthly_turnovers.append(turnover)
        prev_top = top_q
    top_turnover_m = float(np.mean(monthly_turnovers)) if monthly_turnovers else 0

    # === 6. 行业中性IC ===
    industry_neutral_ic = 0
    if fwd20 is not None:
        ind_ics = []
        for ym in sorted(months.keys())[-12:]:
            last_d = max(months[ym])
            if last_d not in fv_pivot.index or last_d not in fwd20.index:
                continue
            f_vals = fv_pivot.loc[last_d].dropna()
            r_vals = fwd20.loc[last_d]
            merged = pd.DataFrame({"f": f_vals, "r": r_vals}).dropna()
            merged["ind"] = industry_map.reindex(merged.index).fillna("其他")
            for _ind, gdf in merged.groupby("ind"):
                if len(gdf) < 10:
                    continue
                ic, _ = sp_stats.spearmanr(gdf["f"], gdf["r"])
                if not np.isnan(ic):
                    ind_ics.append(ic)
        industry_neutral_ic = float(np.mean(ind_ics)) if ind_ics else 0

    raw_ic_20 = ic_results.get(20, {}).get("mean", 0)
    is_industry_bet = abs(raw_ic_20) > 0.03 and abs(industry_neutral_ic) < 0.01

    # === 7. Regime IC ===
    bull_m = set((d.year, d.month) for d, r in csi_monthly.items() if r > 0.03)
    bear_m = set((d.year, d.month) for d, r in csi_monthly.items() if r < -0.03)
    side_m = set((d.year, d.month) for d, r in csi_monthly.items() if -0.03 <= r <= 0.03)

    def _regime_ic(regime_months):
        ics = []
        for ym in regime_months:
            if ym not in months:
                continue
            last_d = max(months[ym])
            if last_d not in fv_pivot.index or fwd20 is None or last_d not in fwd20.index:
                continue
            f_v = fv_pivot.loc[last_d].dropna()
            r_v = fwd20.loc[last_d]
            m = pd.DataFrame({"f": f_v, "r": r_v}).dropna()
            if len(m) < MIN_STOCKS:
                continue
            ic, _ = sp_stats.spearmanr(m["f"], m["r"])
            if not np.isnan(ic):
                ics.append(ic)
        return float(np.mean(ics)) if ics else 0

    ic_bull = _regime_ic(bull_m)
    ic_bear = _regime_ic(bear_m)
    ic_side = _regime_ic(side_m)
    regime_sens = max(ic_bull, ic_bear, ic_side) - min(ic_bull, ic_bear, ic_side)
    regime_sufficient = len(bull_m) >= 12 and len(bear_m) >= 12 and len(side_m) >= 12

    # === 8. trigger_type判定 ===
    ranking_score = min(1.0, abs(monotonicity) * (abs(ic_results.get(20, {}).get("t", 0)) / 3.0))
    if monotonicity < 0.6 or abs(ic_results.get(20, {}).get("t", 0)) < 2.0:
        ranking_score *= 0.5

    modifier_score = 0
    if abs(raw_ic_20) < 0.02:
        modifier_score = 0.5

    event_score = 0
    if ic_halflife and ic_halflife <= 5:
        event_score = 0.6

    scores = {"ranking": ranking_score, "event": event_score, "modifier": modifier_score}
    trigger_type = max(scores, key=scores.get)
    sorted_scores = sorted(scores.values(), reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]

    # === 9. 策略模板推荐 (V2: 方向反转+单调性+成本) ===

    # 基础模板: 由trigger_type + optimal_horizon决定
    if trigger_type == "event":
        tmpl, rebal = 7, "event_trigger"
    elif trigger_type == "modifier":
        tmpl, rebal = 11, "daily_signal"
    elif optimal_h < 15 and rank_ac.get(5, 1) < 0.90:
        tmpl, rebal = 2, "weekly"
    elif optimal_h < 15 and rank_ac.get(5, 1) >= 0.90:
        tmpl, rebal = 2, "biweekly"
    else:
        tmpl, rebal = 1, "monthly"

    reason_parts = [f"optimal_horizon={optimal_h}d"]
    if rank_ac.get(5):
        reason_parts.append(f"rank_ac5d={rank_ac[5]:.2f}")
    reason_parts.append(f"trigger={trigger_type}")

    # Fix1: regime切换仅在bull/bear IC方向反转时推荐
    bull_bear_opposite = (ic_bull > 0 and ic_bear < 0) or (ic_bull < 0 and ic_bear > 0)
    if bull_bear_opposite:
        reason_parts.append("regime_opposite_direction")
        tmpl = 12
        rebal = "regime_switch"
    elif regime_sens > 0.03:
        reason_parts.append("regime_sensitive_same_dir")
        # 不覆盖模板，保持原有1/2/11

    # Fix2: 120d天花板标注
    if horizon_note:
        reason_parts.append(
            "120d_check:" + ("ceiling" if "未达峰值" in horizon_note else "confirmed")
        )

    # Fix3: 单调性影响选股建议
    abs_mono = abs(monotonicity)
    if abs_mono >= 0.6:
        mono_note = "排名选股Top-N有效"
    elif abs_mono >= 0.3:
        mono_note = "排名选股但建议缩小N(Top-10而非Top-20)"
        reason_parts.append(f"medium_mono({monotonicity:.2f})")
    else:
        mono_note = f"不适合排名选股(单调性{monotonicity:.2f})，建议极端分位触发或仅作ML特征"
        reason_parts.append(f"low_mono({monotonicity:.2f})")

    # Fix4: 成本可行性校验
    n_rebal = REBAL_FREQ.get(rebal, 12)
    if rebal == "monthly":
        est_turnover = top_turnover_m
    elif rebal in ("weekly", "biweekly"):
        est_turnover = max(0.05, 1 - rank_ac.get(5, 0.9))
    elif rebal == "daily_signal":
        est_turnover = max(0.05, 1 - rank_ac.get(1, 0.9))
    else:
        est_turnover = top_turnover_m

    annual_cost = est_turnover * n_rebal * 2 * COST_PER_TRADE
    est_annual_alpha = abs(quintile_spread) * 12
    cost_feasible = annual_cost < est_annual_alpha if est_annual_alpha > 0 else True
    cost_note = ""
    if not cost_feasible and rebal in ("weekly", "biweekly", "daily_signal"):
        cost_note = (
            f"成本侵蚀: {rebal}换手{est_turnover:.0%}, "
            f"年化成本{annual_cost:.1%}, 预估alpha{est_annual_alpha:.1%}, "
            f"建议降频至月度或仅作ML特征"
        )
        reason_parts.append("cost_infeasible")

    # 其余标注
    if is_industry_bet:
        reason_parts.append("industry_bet")
    if ic_trend == "decaying":
        reason_parts.append("IC_DECAYING")
    if top_turnover_m > 0.6:
        reason_parts.append(f"high_turnover({top_turnover_m:.0%})")
    reason = "; ".join(reason_parts)

    # === 10. 相关性 + Fix5冗余标注 ===
    max_corr_f, max_corr_v = "", 0
    if all_factor_names:
        last_d = fv_dates[-1]
        my_vals = (
            fv_pivot.loc[last_d].dropna() if last_d in fv_pivot.index else pd.Series(dtype=float)
        )
        for other in all_factor_names:
            if other == factor_name or my_vals.empty:
                continue
            other_fv = pd.read_sql(
                "SELECT code, neutral_value FROM factor_values "
                "WHERE factor_name=%s AND trade_date=%s AND neutral_value IS NOT NULL",
                conn,
                params=(other, last_d),
            )
            if other_fv.empty:
                continue
            ov = other_fv.set_index("code")["neutral_value"]
            m = pd.DataFrame({"a": my_vals, "b": ov}).dropna()
            if len(m) < 100:
                continue
            c, _ = sp_stats.spearmanr(m["a"], m["b"])
            if not np.isnan(c) and abs(c) > abs(max_corr_v):
                max_corr_v, max_corr_f = float(c), other

    # Fix5: 冗余标注（基础版，keep_recommendation在后处理中确定）
    redundant_with = ""
    redundancy_note = ""
    if max_corr_v > 0.85:
        redundant_with = max_corr_f
        redundancy_note = f"与{max_corr_f}冗余(corr={max_corr_v:.2f})"
    elif max_corr_v < -0.85:
        redundancy_note = (
            f"与{max_corr_f}为mirror pair(corr={max_corr_v:.2f})，同时使用注意方向对齐"
        )

    # Fix7: 多模板评分
    tmpl_scores_input = {
        "optimal_horizon": optimal_h,
        "rank_autocorr_5d": rank_ac.get(5, 0.9),
        "rank_autocorr_1d": rank_ac.get(1, 0.9),
        "monotonicity": monotonicity,
        "trigger_type": trigger_type,
        "cost_feasible": cost_feasible,
        "top_q_turnover_monthly": top_turnover_m,
        "ic_bull": ic_bull,
        "ic_bear": ic_bear,
        "regime_sensitivity": regime_sens,
    }
    template_ranking = _score_templates(tmpl_scores_input)
    tmpl_score_1 = template_ranking[0][1] if template_ranking else 0
    tmpl_2 = template_ranking[1][0] if len(template_ranking) > 1 else 1
    tmpl_score_2 = template_ranking[1][1] if len(template_ranking) > 1 else 0

    elapsed = time.time() - t0
    logger.info(
        "%s: IC_20d=%+.4f(t=%.1f) IC_120d=%+.4f opt=%dd tmpl=%d mono=%.2f (%.1fs)",
        factor_name,
        raw_ic_20,
        ic_results.get(20, {}).get("t", 0),
        ic_120,
        optimal_h,
        tmpl,
        monotonicity,
        elapsed,
    )

    result = {
        "factor_name": factor_name,
        "ic_1d": ic_results.get(1, {}).get("mean", 0),
        "ic_1d_tstat": ic_results.get(1, {}).get("t", 0),
        "ic_5d": ic_results.get(5, {}).get("mean", 0),
        "ic_5d_tstat": ic_results.get(5, {}).get("t", 0),
        "ic_10d": ic_results.get(10, {}).get("mean", 0),
        "ic_10d_tstat": ic_results.get(10, {}).get("t", 0),
        "ic_20d": raw_ic_20,
        "ic_20d_tstat": ic_results.get(20, {}).get("t", 0),
        "ic_60d": ic_results.get(60, {}).get("mean", 0),
        "ic_60d_tstat": ic_results.get(60, {}).get("t", 0),
        "ic_120d": ic_120,
        "ic_120d_tstat": ic_120_t,
        "optimal_horizon": optimal_h,
        "optimal_horizon_note": horizon_note,
        "ic_ir": ic_ir,
        "ic_positive_ratio": ic_pos_ratio,
        "ic_trend": ic_trend,
        "rank_autocorr_1d": rank_ac.get(1, 0),
        "rank_autocorr_5d": rank_ac.get(5, 0),
        "rank_autocorr_20d": rank_ac.get(20, 0),
        "quintile_spread": quintile_spread,
        "monotonicity": monotonicity,
        "monotonicity_note": mono_note,
        "quintile_means": quintile_means,
        "top_q_turnover_monthly": top_turnover_m,
        "top_q_turnover_weekly": 0,
        "industry_neutral_ic_20d": industry_neutral_ic,
        "is_industry_bet": is_industry_bet,
        "trigger_type": trigger_type,
        "trigger_type_confidence": confidence,
        "ic_bull": ic_bull,
        "ic_bear": ic_bear,
        "ic_sideways": ic_side,
        "regime_sensitivity": regime_sens,
        "regime_sample_sufficient": regime_sufficient,
        "max_corr_factor": max_corr_f,
        "max_corr_value": max_corr_v,
        "avg_daily_coverage": avg_coverage,
        "estimated_annual_cost": annual_cost,
        "cost_feasible": cost_feasible,
        "cost_note": cost_note,
        "redundant_with": redundant_with,
        "keep_recommendation": True,  # 后处理中确定
        "redundancy_note": redundancy_note,
        "fmp_candidate": False,  # 后处理中确定
        "fmp_cluster_representative": False,  # 后处理中确定
        "recommended_template": tmpl,
        "recommended_template_2": tmpl_2,
        "template_score_1": tmpl_score_1,
        "template_score_2": tmpl_score_2,
        "recommended_rebalance": rebal,
        "recommendation_reason": reason,
    }

    if close_conn:
        conn.close()
    return result


def _save_profile(conn, p: dict):
    """写入factor_profile表（V2: 含15个新字段）。"""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO factor_profile (factor_name,
            ic_1d, ic_1d_tstat, ic_5d, ic_5d_tstat,
            ic_10d, ic_10d_tstat, ic_20d, ic_20d_tstat,
            ic_60d, ic_60d_tstat, ic_120d, ic_120d_tstat,
            optimal_horizon, optimal_horizon_note,
            ic_ir, ic_positive_ratio, ic_trend,
            rank_autocorr_1d, rank_autocorr_5d, rank_autocorr_20d,
            quintile_spread, monotonicity, monotonicity_note,
            top_q_turnover_monthly, top_q_turnover_weekly,
            industry_neutral_ic_20d, is_industry_bet,
            trigger_type, trigger_type_confidence,
            ic_bull, ic_bear, ic_sideways, regime_sensitivity, regime_sample_sufficient,
            max_corr_factor, max_corr_value, avg_daily_coverage,
            estimated_annual_cost, cost_feasible, cost_note,
            redundant_with, keep_recommendation, redundancy_note,
            fmp_candidate, fmp_cluster_representative,
            recommended_template, recommended_template_2,
            template_score_1, template_score_2,
            recommended_rebalance, recommendation_reason,
            forward_return_method, profile_date, sample_start, sample_end)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (factor_name) DO UPDATE SET
            ic_1d=EXCLUDED.ic_1d, ic_1d_tstat=EXCLUDED.ic_1d_tstat,
            ic_5d=EXCLUDED.ic_5d, ic_5d_tstat=EXCLUDED.ic_5d_tstat,
            ic_10d=EXCLUDED.ic_10d, ic_10d_tstat=EXCLUDED.ic_10d_tstat,
            ic_20d=EXCLUDED.ic_20d, ic_20d_tstat=EXCLUDED.ic_20d_tstat,
            ic_60d=EXCLUDED.ic_60d, ic_60d_tstat=EXCLUDED.ic_60d_tstat,
            ic_120d=EXCLUDED.ic_120d, ic_120d_tstat=EXCLUDED.ic_120d_tstat,
            optimal_horizon=EXCLUDED.optimal_horizon,
            optimal_horizon_note=EXCLUDED.optimal_horizon_note,
            ic_ir=EXCLUDED.ic_ir, ic_positive_ratio=EXCLUDED.ic_positive_ratio,
            ic_trend=EXCLUDED.ic_trend,
            rank_autocorr_1d=EXCLUDED.rank_autocorr_1d,
            rank_autocorr_5d=EXCLUDED.rank_autocorr_5d,
            rank_autocorr_20d=EXCLUDED.rank_autocorr_20d,
            quintile_spread=EXCLUDED.quintile_spread,
            monotonicity=EXCLUDED.monotonicity,
            monotonicity_note=EXCLUDED.monotonicity_note,
            trigger_type=EXCLUDED.trigger_type,
            trigger_type_confidence=EXCLUDED.trigger_type_confidence,
            ic_bull=EXCLUDED.ic_bull, ic_bear=EXCLUDED.ic_bear,
            ic_sideways=EXCLUDED.ic_sideways,
            regime_sensitivity=EXCLUDED.regime_sensitivity,
            regime_sample_sufficient=EXCLUDED.regime_sample_sufficient,
            max_corr_factor=EXCLUDED.max_corr_factor,
            max_corr_value=EXCLUDED.max_corr_value,
            avg_daily_coverage=EXCLUDED.avg_daily_coverage,
            estimated_annual_cost=EXCLUDED.estimated_annual_cost,
            cost_feasible=EXCLUDED.cost_feasible,
            cost_note=EXCLUDED.cost_note,
            redundant_with=EXCLUDED.redundant_with,
            keep_recommendation=EXCLUDED.keep_recommendation,
            redundancy_note=EXCLUDED.redundancy_note,
            fmp_candidate=EXCLUDED.fmp_candidate,
            fmp_cluster_representative=EXCLUDED.fmp_cluster_representative,
            recommended_template=EXCLUDED.recommended_template,
            recommended_template_2=EXCLUDED.recommended_template_2,
            template_score_1=EXCLUDED.template_score_1,
            template_score_2=EXCLUDED.template_score_2,
            recommended_rebalance=EXCLUDED.recommended_rebalance,
            recommendation_reason=EXCLUDED.recommendation_reason,
            profile_date=EXCLUDED.profile_date""",
        (
            str(p["factor_name"]),
            _f(p["ic_1d"]),
            _f(p["ic_1d_tstat"]),
            _f(p["ic_5d"]),
            _f(p["ic_5d_tstat"]),
            _f(p["ic_10d"]),
            _f(p["ic_10d_tstat"]),
            _f(p["ic_20d"]),
            _f(p["ic_20d_tstat"]),
            _f(p["ic_60d"]),
            _f(p["ic_60d_tstat"]),
            _f(p["ic_120d"]),
            _f(p["ic_120d_tstat"]),
            int(p["optimal_horizon"]),
            str(p.get("optimal_horizon_note", "") or ""),
            _f(p["ic_ir"]),
            _f(p["ic_positive_ratio"]),
            str(p["ic_trend"]),
            _f(p["rank_autocorr_1d"]),
            _f(p["rank_autocorr_5d"]),
            _f(p["rank_autocorr_20d"]),
            _f(p["quintile_spread"]),
            _f(p["monotonicity"]),
            str(p.get("monotonicity_note", "") or ""),
            _f(p["top_q_turnover_monthly"]),
            _f(p["top_q_turnover_weekly"]),
            _f(p["industry_neutral_ic_20d"]),
            bool(p["is_industry_bet"]),
            str(p["trigger_type"]),
            _f(p["trigger_type_confidence"]),
            _f(p["ic_bull"]),
            _f(p["ic_bear"]),
            _f(p["ic_sideways"]),
            _f(p["regime_sensitivity"]),
            bool(p.get("regime_sample_sufficient", True)),
            str(p["max_corr_factor"]),
            _f(p["max_corr_value"]),
            _f(p["avg_daily_coverage"]),
            _f(p["estimated_annual_cost"]),
            bool(p.get("cost_feasible", True)),
            str(p.get("cost_note", "") or ""),
            str(p.get("redundant_with", "") or ""),
            bool(p.get("keep_recommendation", True)),
            str(p.get("redundancy_note", "") or ""),
            bool(p.get("fmp_candidate", False)),
            bool(p.get("fmp_cluster_representative", False)),
            int(p["recommended_template"]),
            int(p.get("recommended_template_2", 1)),
            _f(p.get("template_score_1", 0)),
            _f(p.get("template_score_2", 0)),
            str(p["recommended_rebalance"]),
            str(p.get("recommendation_reason", "")),
            FWD_METHOD,
            date.today(),
            START_DATE,
            END_DATE,
        ),
    )
    conn.commit()


def _build_clusters(profiles: list[dict]) -> list[list[str]]:
    """Union-Find聚类: |corr| > 0.7 的因子归入同一簇。"""
    names = [p["factor_name"] for p in profiles]
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for p in profiles:
        if (
            p["max_corr_factor"]
            and abs(p["max_corr_value"]) > 0.7
            and p["max_corr_factor"] in parent
        ):
            union(p["factor_name"], p["max_corr_factor"])

    clusters = {}
    for n in names:
        r = find(n)
        clusters.setdefault(r, []).append(n)

    return list(clusters.values())


def profile_all_factors() -> list[dict]:
    """对全部因子跑画像。串行处理，共享forward return + 后处理。"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
    all_factors = [r[0] for r in cur.fetchall()]
    logger.info("因子画像V2: %d个因子", len(all_factors))

    shared = _load_shared_data(conn)
    close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates = shared

    profiles = []
    for i, fname in enumerate(all_factors):
        logger.info("[%d/%d] %s", i + 1, len(all_factors), fname)
        p = profile_factor(
            fname,
            close_pivot,
            fwd_excess,
            csi_monthly,
            industry_map,
            trading_dates,
            conn=conn,
            all_factor_names=all_factors,
        )
        profiles.append(p)

    valid = [p for p in profiles if "error" not in p]

    # === 后处理1: Fix5 冗余keep_recommendation ===
    ir_map = {p["factor_name"]: abs(p["ic_ir"]) for p in valid}
    for p in valid:
        if p["redundant_with"]:
            other_ir = ir_map.get(p["redundant_with"], 0)
            my_ir = abs(p["ic_ir"])
            p["keep_recommendation"] = my_ir >= other_ir
            if p["keep_recommendation"]:
                p["redundancy_note"] += "，推荐保留(IR更高)"
            else:
                p["redundancy_note"] += f"，建议用{p['redundant_with']}替代(IR更低)"

    # === 后处理2: Fix6 FMP聚类+候选识别 ===
    clusters = _build_clusters(valid)
    logger.info("因子聚类: %d个簇 from %d因子", len(clusters), len(valid))
    for cl in clusters:
        logger.info("  簇: %s", cl)

    # 每个簇选IR最高的代表
    reps = []
    for cluster in clusters:
        best = max(cluster, key=lambda f: abs(ir_map.get(f, 0)))
        reps.append(best)
        for p in valid:
            if p["factor_name"] == best:
                p["fmp_cluster_representative"] = True

    # 代表之间加载最后日期的因子值，计算两两相关性
    if len(reps) > 1:
        # 加载所有代表因子的最后日期值
        # 取共同最后日期
        sample_date = None
        for p in valid:
            if p["factor_name"] == reps[0]:
                break
        cur.execute(
            "SELECT MAX(trade_date) FROM factor_values WHERE factor_name=%s",
            (reps[0],),
        )
        row = cur.fetchone()
        sample_date = row[0] if row else None

        if sample_date:
            rep_vals = {}
            for rep_name in reps:
                df = pd.read_sql(
                    "SELECT code, neutral_value FROM factor_values "
                    "WHERE factor_name=%s AND trade_date=%s AND neutral_value IS NOT NULL",
                    conn,
                    params=(rep_name, sample_date),
                )
                if not df.empty:
                    rep_vals[rep_name] = df.set_index("code")["neutral_value"]

            # 标记FMP候选: 与其他所有代表corr<0.3的因子
            for rep_name in reps:
                if rep_name not in rep_vals:
                    continue
                is_fmp = True
                for other_rep in reps:
                    if other_rep == rep_name or other_rep not in rep_vals:
                        continue
                    merged = pd.DataFrame(
                        {"a": rep_vals[rep_name], "b": rep_vals[other_rep]}
                    ).dropna()
                    if len(merged) < 100:
                        continue
                    c, _ = sp_stats.spearmanr(merged["a"], merged["b"])
                    if not np.isnan(c) and abs(c) >= 0.3:
                        is_fmp = False
                        break
                for p in valid:
                    if p["factor_name"] == rep_name:
                        p["fmp_candidate"] = is_fmp

    # 保存全部
    for p in valid:
        _save_profile(conn, p)

    conn.close()
    return profiles


def generate_profile_report(profiles: list[dict]) -> str:
    """生成Markdown格式画像报告 (V2)。"""
    lines = [
        f"# 因子画像汇总报告 ({date.today()}) — V2",
        "",
        "- Forward return方法: close[T+1] -> close[T+h]",
        f"- 数据范围: {START_DATE} ~ {END_DATE}",
        "- Universe: 排除ST/停牌, 与load_universe()对齐",
        "- 超额基准: CSI300同期收益",
        "- 120d IC: 有效范围约2021-07~2025-06（两端各缺~120交易日）",
        "",
    ]

    valid = [p for p in profiles if "error" not in p]

    # 一、多周期IC（含120d）
    lines += [
        "## 一、多周期IC（按|IC_20d|降序，t<2.0标W）",
        "",
        f"{'因子':<22s} {'IC_5d(t)':>12s} {'IC_10d(t)':>12s} {'IC_20d(t)':>12s} "
        f"{'IC_60d(t)':>12s} {'IC_120d(t)':>12s} {'最优':>5s} {'IR':>5s} {'趋势':>8s} {'天花板':>8s}",
        "-" * 130,
    ]
    for p in sorted(valid, key=lambda x: abs(x["ic_20d"]), reverse=True):

        def _ic_fmt(ic, t):
            w = "W" if abs(t) < 2.0 else ""
            return f"{ic:+.3f}({t:.1f}){w}"

        ceiling = ""
        if p.get("optimal_horizon_note"):
            ceiling = "^" if "未达峰值" in p["optimal_horizon_note"] else "v"
        lines.append(
            f"{p['factor_name']:<22s} "
            f"{_ic_fmt(p['ic_5d'], p['ic_5d_tstat']):>12s} "
            f"{_ic_fmt(p['ic_10d'], p['ic_10d_tstat']):>12s} "
            f"{_ic_fmt(p['ic_20d'], p['ic_20d_tstat']):>12s} "
            f"{_ic_fmt(p['ic_60d'], p['ic_60d_tstat']):>12s} "
            f"{_ic_fmt(p['ic_120d'], p['ic_120d_tstat']):>12s} "
            f"{p['optimal_horizon']:>3d}d{ceiling} {p['ic_ir']:>+5.2f} {p['ic_trend']:>8s}"
        )

    # 二、排名自相关+换手率+成本
    lines += [
        "",
        "## 二、排名自相关+换手率+成本",
        "",
        f"{'因子':<22s} {'ac_1d':>6s} {'ac_5d':>6s} {'ac_20d':>6s} {'月换手':>6s} "
        f"{'推荐':>12s} {'年成本':>6s} {'可行':>4s}",
    ]
    for p in sorted(valid, key=lambda x: x["rank_autocorr_5d"]):
        cost_flag = "Y" if p.get("cost_feasible", True) else "N"
        lines.append(
            f"{p['factor_name']:<22s} {p['rank_autocorr_1d']:>6.3f} {p['rank_autocorr_5d']:>6.3f} "
            f"{p['rank_autocorr_20d']:>6.3f} {p['top_q_turnover_monthly']:>5.0%} "
            f"{p['recommended_rebalance']:>12s} "
            f"{p.get('estimated_annual_cost', 0):>5.1%} {cost_flag:>4s}"
        )

    # 三、行业中性IC
    lines += ["", "## 三、行业中性IC", ""]
    for p in sorted(valid, key=lambda x: abs(x["ic_20d"]), reverse=True):
        if abs(p["ic_20d"]) < 0.01:
            continue
        flag = "W行业暴露" if p["is_industry_bet"] else "OK"
        lines.append(
            f"- {p['factor_name']}: raw={p['ic_20d']:+.4f} neutral={p['industry_neutral_ic_20d']:+.4f} {flag}"
        )

    # 四、分位收益单调性 + 选股建议
    lines += ["", "## 四、分位收益单调性+选股建议", ""]
    for p in sorted(valid, key=lambda x: abs(x["monotonicity"])):
        if abs(p["ic_20d"]) < 0.01:
            continue
        flag = "W" if abs(p["monotonicity"]) < 0.6 else ""
        qm = p.get("quintile_means", [0] * 5)
        mono_n = p.get("monotonicity_note", "")
        lines.append(
            f"- {p['factor_name']}: mono={p['monotonicity']:+.2f}{flag} "
            f"Q1={qm[0] * 100:+.1f}% Q5={qm[4] * 100:+.1f}% "
            f"spread={p['quintile_spread'] * 100:+.2f}% — {mono_n}"
        )

    # 五、被月度冤杀
    fast = [p for p in valid if p["optimal_horizon"] < 15 and abs(p["ic_5d"]) > abs(p["ic_20d"])]
    lines += ["", "## 五、被月度框架可能冤杀的因子", ""]
    for p in fast:
        lines.append(
            f"- **{p['factor_name']}**: 最优{p['optimal_horizon']}d, "
            f"IC_5d={p['ic_5d']:+.4f} > IC_20d={p['ic_20d']:+.4f}"
        )
    if not fast:
        lines.append("（无）")

    # 六、Regime分析（V2: 方向反转 vs 幅度差异）
    opposite = [
        p
        for p in valid
        if (p["ic_bull"] > 0 and p["ic_bear"] < 0) or (p["ic_bull"] < 0 and p["ic_bear"] > 0)
    ]
    same_dir = [p for p in valid if p["regime_sensitivity"] > 0.03 and p not in opposite]

    lines += ["", "## 六、Regime分析", ""]
    lines += [f"### 6A. Bull/Bear方向反转（{len(opposite)}个，推荐模板12）", ""]
    for p in sorted(opposite, key=lambda x: x["regime_sensitivity"], reverse=True):
        suf = "" if p["regime_sample_sufficient"] else " W样本不足"
        lines.append(
            f"- **{p['factor_name']}**: bull={p['ic_bull']:+.4f} bear={p['ic_bear']:+.4f} "
            f"side={p['ic_sideways']:+.4f} sens={p['regime_sensitivity']:.4f}{suf}"
        )
    if not opposite:
        lines.append("（无）")

    lines += ["", f"### 6B. 同向不同幅度（{len(same_dir)}个，保持原模板）", ""]
    for p in sorted(same_dir, key=lambda x: x["regime_sensitivity"], reverse=True):
        lines.append(
            f"- {p['factor_name']}: bull={p['ic_bull']:+.4f} bear={p['ic_bear']:+.4f} "
            f"side={p['ic_sideways']:+.4f} sens={p['regime_sensitivity']:.4f}"
        )

    # 七、成本可行性
    infeasible = [p for p in valid if not p.get("cost_feasible", True)]
    lines += ["", "## 七、成本可行性校验", ""]
    if infeasible:
        for p in infeasible:
            lines.append(f"- **{p['factor_name']}**: {p.get('cost_note', '')}")
    else:
        lines.append("所有推荐频率的成本均可行。")

    # 八、冗余因子
    redundant = [p for p in valid if p.get("redundant_with")]
    mirror = [p for p in valid if p.get("max_corr_value", 0) < -0.85]
    lines += ["", "## 八、冗余因子标注", ""]
    lines += ["### 8A. 冗余对（corr>0.85，择一）", ""]
    seen = set()
    for p in redundant:
        pair = tuple(sorted([p["factor_name"], p["redundant_with"]]))
        if pair in seen:
            continue
        seen.add(pair)
        keep_flag = "保留" if p.get("keep_recommendation") else "替代"
        lines.append(
            f"- {p['factor_name']} <-> {p['redundant_with']} "
            f"(corr={p['max_corr_value']:.2f}) — {p['factor_name']}: {keep_flag}"
        )
    if not redundant:
        lines.append("（无）")

    lines += ["", "### 8B. Mirror Pairs（corr<-0.85，注意方向对齐）", ""]
    seen_m = set()
    for p in mirror:
        pair = tuple(sorted([p["factor_name"], p["max_corr_factor"]]))
        if pair in seen_m:
            continue
        seen_m.add(pair)
        lines.append(
            f"- {p['factor_name']} <-> {p['max_corr_factor']} (corr={p['max_corr_value']:.2f})"
        )
    if not mirror:
        lines.append("（无）")

    # 九、FMP候选
    fmp_reps = [p for p in valid if p.get("fmp_cluster_representative")]
    fmp_cands = [p for p in valid if p.get("fmp_candidate")]
    lines += ["", "## 九、FMP独立组合候选", ""]
    lines += [f"聚类代表: {len(fmp_reps)}个, FMP候选(两两corr<0.3): {len(fmp_cands)}个", ""]
    if fmp_cands:
        for p in sorted(fmp_cands, key=lambda x: abs(x["ic_ir"]), reverse=True):
            lines.append(
                f"- **{p['factor_name']}**: IC_20d={p['ic_20d']:+.4f} IR={p['ic_ir']:+.2f} "
                f"tmpl={p['recommended_template']}"
            )

    # 十、策略模板推荐汇总
    tmpl_map = {}
    for p in valid:
        tmpl_map.setdefault(p["recommended_template"], []).append(p["factor_name"])
    lines += ["", "## 十、策略模板推荐汇总（V2修正后）", ""]
    for t in sorted(tmpl_map.keys()):
        name = TMPL_NAMES.get(t, f"模板{t}")
        lines.append(f"- **模板{t}({name})** [{len(tmpl_map[t])}个]: {', '.join(tmpl_map[t])}")

    # 十一、框架匹配度
    non_m = [p for p in valid if p["recommended_template"] != 1]
    lines += [
        "",
        "## 十一、框架匹配度",
        "",
        f"当前全部用月度等权(模板1)。推荐非月度: **{len(non_m)}个** "
        f"({len(non_m) / max(len(valid), 1) * 100:.0f}%)",
        f"推荐月度(模板1): **{len(valid) - len(non_m)}个** "
        f"({(len(valid) - len(non_m)) / max(len(valid), 1) * 100:.0f}%)",
    ]

    # 十二、Top-2模板评分
    lines += ["", "## 十二、多模板评分（Top-2）", ""]
    lines += [
        f"{'因子':<22s} {'主模板':>6s} {'分数':>5s} {'备选':>6s} {'分数':>5s}",
        "-" * 50,
    ]
    for p in sorted(valid, key=lambda x: abs(x["ic_20d"]), reverse=True):
        t1 = p.get("recommended_template", 1)
        s1 = p.get("template_score_1", 0)
        t2 = p.get("recommended_template_2", 1)
        s2 = p.get("template_score_2", 0)
        lines.append(f"{p['factor_name']:<22s} {t1:>6d} {s1:>5.2f} {t2:>6d} {s2:>5.2f}")

    return "\n".join(lines)
