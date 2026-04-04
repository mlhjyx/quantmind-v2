"""因子画像系统 (Factor Profiler) — 严谨版 GA1-A。

对每个因子计算标准化特征画像：多周期IC(含t-stat)、分位收益单调性、
排名自相关、换手率、行业中性IC、regime敏感性、trigger_type判定。

Forward return方法: close[T+1] → close[T+h]（T+1入场，A股T+1制度）
超额收益基准: CSI300同期收益

用法:
    from engines.factor_profiler import profile_all_factors
    profiles = profile_all_factors()
"""

import logging
import time
from datetime import date

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from scipy import stats as sp_stats

logger = logging.getLogger(__name__)

HORIZONS = [1, 5, 10, 20, 60]
START_DATE = date(2021, 1, 1)
END_DATE = date(2025, 12, 31)
FWD_METHOD = "close_t1_to_close_th"
MIN_STOCKS = 30


def _get_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


def _f(v):
    """numpy/decimal → Python float, None-safe."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def _load_shared_data(conn):
    """预加载共享数据（一次加载，所有因子复用）。"""
    logger.info("加载共享数据...")
    t0 = time.time()

    # 复权价（T和T+1入场价）
    close_df = pd.read_sql(
        "SELECT code, trade_date, close * adj_factor as adj_close "
        "FROM klines_daily WHERE trade_date BETWEEN %s AND %s AND volume > 0",
        conn,
        params=(START_DATE, date(2026, 3, 31)),
    )
    close_pivot = close_df.pivot(
        index="trade_date", columns="code", values="adj_close"
    ).sort_index()
    trading_dates = sorted(close_pivot.index)

    # CSI300
    csi = pd.read_sql(
        "SELECT trade_date, close FROM index_daily "
        "WHERE index_code='000300.SH' AND trade_date BETWEEN %s AND %s",
        conn,
        params=(START_DATE, date(2026, 3, 31)),
    )
    csi_close = csi.set_index("trade_date")["close"].sort_index()

    # Forward excess returns: close[T+1] → close[T+h] - CSI300同期
    fwd_excess = {}
    for h in HORIZONS:
        entry = close_pivot.shift(-1)  # T+1 close作为入场价
        exit_p = close_pivot.shift(-h)  # T+h close作为出场价
        stock_ret = exit_p / entry - 1
        csi_entry = csi_close.shift(-1)
        csi_exit = csi_close.shift(-h)
        idx_ret = csi_exit / csi_entry - 1
        fwd_excess[h] = stock_ret.sub(idx_ret, axis=0)

    # CSI300月收益（regime分类）
    csi_dt = csi_close.copy()
    csi_dt.index = pd.to_datetime(csi_dt.index)
    csi_monthly = csi_dt.resample("ME").last().pct_change().dropna()

    # 行业分类
    industry = pd.read_sql("SELECT code, industry_sw1 FROM symbols WHERE market='astock'", conn)
    industry_map = industry.set_index("code")["industry_sw1"].fillna("其他")

    logger.info("共享数据加载完成: %.1fs", time.time() - t0)
    return close_pivot, fwd_excess, csi_monthly, industry_map, trading_dates


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

    # pivot: trade_date × code
    fv_pivot = fv.pivot_table(index="trade_date", columns="code", values="neutral_value")
    fv_dates = sorted(fv_pivot.index)

    # 覆盖度
    avg_coverage = fv_pivot.notna().sum(axis=1).mean() / 5000
    len(fv_dates)

    # === 1. 多周期IC + t-stat ===
    ic_results = {}
    for h in HORIZONS:
        fwd = fwd_excess.get(h)
        if fwd is None:
            continue
        monthly_ics = []
        months = {}
        for td in fv_dates:
            ym = (td.year, td.month)
            months.setdefault(ym, []).append(td)

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

    # 最优horizon
    abs_ics = {h: abs(r["mean"]) for h, r in ic_results.items() if r["mean"] != 0}
    optimal_h = max(abs_ics, key=abs_ics.get) if abs_ics else 20

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
        # 用最近12个月月末截面
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
        sample_dates = fv_dates[:: max(lag, 1)][:100]  # 抽样避免太慢
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
    top_turnover_m, _top_turnover_w = 0, 0
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
    # ranking票
    ranking_score = min(1.0, abs(monotonicity) * (abs(ic_results.get(20, {}).get("t", 0)) / 3.0))
    if monotonicity < 0.6 or abs(ic_results.get(20, {}).get("t", 0)) < 2.0:
        ranking_score *= 0.5

    # modifier票
    modifier_score = 0
    if abs(raw_ic_20) < 0.02:
        modifier_score = 0.5

    # event票（简化：基于IC衰减速度）
    event_score = 0
    if ic_halflife and ic_halflife <= 5:
        event_score = 0.6

    scores = {"ranking": ranking_score, "event": event_score, "modifier": modifier_score}
    trigger_type = max(scores, key=scores.get)
    sorted_scores = sorted(scores.values(), reverse=True)
    confidence = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]

    # === 9. 策略模板推荐 ===
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
    if regime_sens > 0.03:
        reason_parts.append("regime_sensitive")
        tmpl = 12
    if is_industry_bet:
        reason_parts.append("industry_bet")
    if ic_trend == "decaying":
        reason_parts.append("IC_DECAYING")
    if top_turnover_m > 0.6:
        reason_parts.append(f"high_turnover({top_turnover_m:.0%})")
    reason = "; ".join(reason_parts)

    # === 10. 相关性 ===
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

    elapsed = time.time() - t0
    logger.info(
        "%s: IC_20d=%+.4f(t=%.1f) opt=%dd type=%s mono=%.2f ac5d=%.2f (%.1fs)",
        factor_name,
        raw_ic_20,
        ic_results.get(20, {}).get("t", 0),
        optimal_h,
        trigger_type,
        monotonicity,
        rank_ac.get(5, 0),
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
        "optimal_horizon": optimal_h,
        "ic_ir": ic_ir,
        "ic_positive_ratio": ic_pos_ratio,
        "ic_trend": ic_trend,
        "rank_autocorr_1d": rank_ac.get(1, 0),
        "rank_autocorr_5d": rank_ac.get(5, 0),
        "rank_autocorr_20d": rank_ac.get(20, 0),
        "quintile_spread": quintile_spread,
        "monotonicity": monotonicity,
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
        "recommended_template": tmpl,
        "recommended_rebalance": rebal,
        "recommendation_reason": reason,
    }

    if close_conn:
        conn.close()
    return result


def _save_profile(conn, p: dict):
    """写入factor_profile表。"""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO factor_profile (factor_name, ic_1d, ic_1d_tstat, ic_5d, ic_5d_tstat,
            ic_10d, ic_10d_tstat, ic_20d, ic_20d_tstat, ic_60d, ic_60d_tstat,
            optimal_horizon, ic_ir, ic_positive_ratio, ic_trend,
            rank_autocorr_1d, rank_autocorr_5d, rank_autocorr_20d,
            quintile_spread, monotonicity,
            top_q_turnover_monthly, top_q_turnover_weekly,
            industry_neutral_ic_20d, is_industry_bet,
            trigger_type, trigger_type_confidence,
            ic_bull, ic_bear, ic_sideways, regime_sensitivity, regime_sample_sufficient,
            max_corr_factor, max_corr_value, avg_daily_coverage,
            recommended_template, recommended_rebalance, recommendation_reason,
            forward_return_method, profile_date, sample_start, sample_end)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (factor_name) DO UPDATE SET
            ic_1d=EXCLUDED.ic_1d, ic_1d_tstat=EXCLUDED.ic_1d_tstat,
            ic_5d=EXCLUDED.ic_5d, ic_5d_tstat=EXCLUDED.ic_5d_tstat,
            ic_10d=EXCLUDED.ic_10d, ic_10d_tstat=EXCLUDED.ic_10d_tstat,
            ic_20d=EXCLUDED.ic_20d, ic_20d_tstat=EXCLUDED.ic_20d_tstat,
            ic_60d=EXCLUDED.ic_60d, ic_60d_tstat=EXCLUDED.ic_60d_tstat,
            optimal_horizon=EXCLUDED.optimal_horizon,
            ic_ir=EXCLUDED.ic_ir, ic_positive_ratio=EXCLUDED.ic_positive_ratio,
            ic_trend=EXCLUDED.ic_trend,
            rank_autocorr_1d=EXCLUDED.rank_autocorr_1d,
            rank_autocorr_5d=EXCLUDED.rank_autocorr_5d,
            rank_autocorr_20d=EXCLUDED.rank_autocorr_20d,
            quintile_spread=EXCLUDED.quintile_spread, monotonicity=EXCLUDED.monotonicity,
            trigger_type=EXCLUDED.trigger_type,
            trigger_type_confidence=EXCLUDED.trigger_type_confidence,
            ic_bull=EXCLUDED.ic_bull, ic_bear=EXCLUDED.ic_bear,
            ic_sideways=EXCLUDED.ic_sideways,
            regime_sensitivity=EXCLUDED.regime_sensitivity,
            max_corr_factor=EXCLUDED.max_corr_factor,
            max_corr_value=EXCLUDED.max_corr_value,
            recommended_template=EXCLUDED.recommended_template,
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
            int(p["optimal_horizon"]),
            _f(p["ic_ir"]),
            _f(p["ic_positive_ratio"]),
            str(p["ic_trend"]),
            _f(p["rank_autocorr_1d"]),
            _f(p["rank_autocorr_5d"]),
            _f(p["rank_autocorr_20d"]),
            _f(p["quintile_spread"]),
            _f(p["monotonicity"]),
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
            int(p["recommended_template"]),
            str(p["recommended_rebalance"]),
            str(p.get("recommendation_reason", "")),
            FWD_METHOD,
            date.today(),
            START_DATE,
            END_DATE,
        ),
    )
    conn.commit()


def profile_all_factors() -> list[dict]:
    """对全部因子跑画像。串行处理，共享forward return。"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
    all_factors = [r[0] for r in cur.fetchall()]
    logger.info("因子画像: %d个因子", len(all_factors))

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
        if "error" not in p:
            _save_profile(conn, p)
        profiles.append(p)

    conn.close()
    return profiles


def generate_profile_report(profiles: list[dict]) -> str:
    """生成Markdown格式画像报告。"""
    lines = [
        f"# 因子画像汇总报告 ({date.today()})",
        "",
        "- Forward return方法: close[T+1] → close[T+h]",
        f"- 数据范围: {START_DATE} ~ {END_DATE}",
        "- Universe: 排除ST/停牌, 与load_universe()对齐",
        "- 超额基准: CSI300同期收益",
        "",
    ]

    valid = [p for p in profiles if "error" not in p]

    # 一、多周期IC
    lines += [
        "## 一、多周期IC（按|IC_20d|降序，t<2.0标⚠️）",
        "",
        f"{'因子':<22s} {'IC_1d(t)':>10s} {'IC_5d(t)':>10s} {'IC_10d(t)':>10s} {'IC_20d(t)':>10s} {'IC_60d(t)':>10s} {'最优':>4s} {'IR':>5s} {'胜率':>4s} {'趋势':>8s}",
        "-" * 110,
    ]
    for p in sorted(valid, key=lambda x: abs(x["ic_20d"]), reverse=True):

        def _ic_fmt(ic, t):
            w = "⚠️" if abs(t) < 2.0 else ""
            return f"{ic:+.3f}({t:.1f}){w}"

        lines.append(
            f"{p['factor_name']:<22s} {_ic_fmt(p['ic_1d'], p['ic_1d_tstat']):>10s} "
            f"{_ic_fmt(p['ic_5d'], p['ic_5d_tstat']):>10s} {_ic_fmt(p['ic_10d'], p['ic_10d_tstat']):>10s} "
            f"{_ic_fmt(p['ic_20d'], p['ic_20d_tstat']):>10s} {_ic_fmt(p['ic_60d'], p['ic_60d_tstat']):>10s} "
            f"{p['optimal_horizon']:>3d}d {p['ic_ir']:>+5.2f} {p['ic_positive_ratio']:>4.0%} {p['ic_trend']:>8s}"
        )

    # 二、排名自相关+换手率
    lines += [
        "",
        "## 二、排名自相关+换手率",
        "",
        f"{'因子':<22s} {'ac_1d':>6s} {'ac_5d':>6s} {'ac_20d':>6s} {'月换手':>6s} {'推荐':>8s}",
    ]
    for p in sorted(valid, key=lambda x: x["rank_autocorr_5d"]):
        lines.append(
            f"{p['factor_name']:<22s} {p['rank_autocorr_1d']:>6.3f} {p['rank_autocorr_5d']:>6.3f} "
            f"{p['rank_autocorr_20d']:>6.3f} {p['top_q_turnover_monthly']:>5.0%} {p['recommended_rebalance']:>8s}"
        )

    # 三、行业中性IC
    lines += ["", "## 三、行业中性IC", ""]
    for p in sorted(valid, key=lambda x: abs(x["ic_20d"]), reverse=True):
        if abs(p["ic_20d"]) < 0.01:
            continue
        flag = "⚠️行业暴露" if p["is_industry_bet"] else "✅"
        lines.append(
            f"- {p['factor_name']}: raw={p['ic_20d']:+.4f} neutral={p['industry_neutral_ic_20d']:+.4f} {flag}"
        )

    # 四、分位收益单调性
    lines += ["", "## 四、分位收益单调性（<0.6标⚠️）", ""]
    for p in sorted(valid, key=lambda x: x["monotonicity"]):
        if abs(p["ic_20d"]) < 0.01:
            continue
        flag = "⚠️" if abs(p["monotonicity"]) < 0.6 else ""
        qm = p.get("quintile_means", [0] * 5)
        lines.append(
            f"- {p['factor_name']}: mono={p['monotonicity']:+.2f}{flag} "
            f"Q1={qm[0] * 100:+.1f}% Q5={qm[4] * 100:+.1f}% spread={p['quintile_spread'] * 100:+.2f}%"
        )

    # 五、被月度冤杀
    fast = [p for p in valid if p["optimal_horizon"] < 15 and abs(p["ic_5d"]) > abs(p["ic_20d"])]
    lines += ["", "## 五、被月度框架可能冤杀的因子", ""]
    for p in fast:
        lines.append(
            f"- **{p['factor_name']}**: 最优{p['optimal_horizon']}d, IC_5d={p['ic_5d']:+.4f} > IC_20d={p['ic_20d']:+.4f}"
        )
    if not fast:
        lines.append("（无）")

    # 六、Regime敏感
    regime = [p for p in valid if p["regime_sensitivity"] > 0.03]
    lines += ["", "## 六、Regime敏感（sensitivity>0.03）", ""]
    for p in sorted(regime, key=lambda x: x["regime_sensitivity"], reverse=True):
        suf = "" if p["regime_sample_sufficient"] else " ⚠️样本不足"
        lines.append(
            f"- **{p['factor_name']}**: bull={p['ic_bull']:+.4f} bear={p['ic_bear']:+.4f} "
            f"side={p['ic_sideways']:+.4f} sens={p['regime_sensitivity']:.4f}{suf}"
        )

    # 七、策略模板汇总
    tmpl_map = {}
    for p in valid:
        tmpl_map.setdefault(p["recommended_template"], []).append(p["factor_name"])
    tmpl_names = {1: "月度", 2: "周度", 7: "事件", 11: "仓位", 12: "regime切换"}
    lines += ["", "## 七、策略模板推荐汇总", ""]
    for t in sorted(tmpl_map.keys()):
        name = tmpl_names.get(t, f"模板{t}")
        lines.append(f"- **模板{t}({name})**: {', '.join(tmpl_map[t])}")

    # 八、偏差率
    non_m = [p for p in valid if p["recommended_template"] != 1]
    lines += [
        "",
        "## 八、框架匹配度",
        "",
        f"当前全部用月度等权(模板1)。推荐非月度: **{len(non_m)}个** ({len(non_m) / max(len(valid), 1) * 100:.0f}%)",
        "这些因子在当前框架下alpha被低估或误用。",
    ]

    return "\n".join(lines)
