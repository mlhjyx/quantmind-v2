"""北向资金市场级MODIFIER因子V2 — 15个高级行为模式因子。

V1只试了4个简单因子(流入量/百分位/连续流出)，结论"北向是滞后指标"。
V2尝试5组15个因子，从行为模式/相对市场/极端事件/跨板块/反向利用等维度挖掘。

评估方法: 因子值 vs 未来N日沪深300/中证500收益的Spearman相关性，
分5组单调性检验，2021-2023训练/2024-2025 OOS分割。

用法:
    python scripts/research_northbound_modifier_v2.py
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats as sp_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_START = date(2020, 1, 1)
FULL_START = date(2021, 1, 1)
FULL_END = date(2025, 12, 31)
TRAIN_END = date(2023, 12, 31)
OOS_START = date(2024, 1, 1)
HORIZONS = [1, 5, 10, 20, 60]

FACTOR_DEFS = [
    # 第一组: 行为模式类
    ("nb_breadth_ratio", "买入股票数/卖出股票数 — 广度而非金额"),
    ("nb_buy_concentration", "净买入HHI — 集中少数股=有观点,分散=被动"),
    ("nb_asymmetry", "买入力度/卖出力度 — >1积极做多,<1积极出逃"),
    ("nb_turnover", "北向换仓率 — 净流入为0但活跃调仓也有信息"),
    # 第二组: 与市场关系类
    ("nb_contrarian_market_5d", "5日逆势买入强度 — 市场跌+北向买=可能反弹"),
    ("nb_size_shift_20d", "北向市值偏好变化 — 大盘→小盘或小盘→大盘"),
    # 第三组: 极端行为类
    ("nb_extreme_outflow", "极端流出(P5) — 恐慌底部信号"),
    ("nb_extreme_inflow", "极端流入(P95) — 过热顶部信号"),
    ("nb_vol_change", "北向波动率突变 — 不确定性指标"),
    ("nb_streak_reversal", "连续流入/流出后反转 — 直接利用'反向指标'发现"),
    # 第四组: 跨板块类
    ("nb_sh_sz_divergence", "沪股通vs深股通分歧 — 大盘蓝筹vs中小创分歧"),
    ("nb_industry_rotation", "行业轮动强度 — 行业间调仓活跃度"),
    ("nb_active_share", "北向vs CSI300偏离度 — 主动选股vs被动配置"),
    # 第五组: 利用反向指标
    ("nb_reverse_percentile", "反向百分位 — 直接翻转V1的百分位因子"),
    ("nb_momentum_divergence", "北向流入vs市场动量背离 — 同向减弱/反向增强"),
]
FACTOR_NAMES = [f[0] for f in FACTOR_DEFS]


def get_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


# ── 数据加载 ─────────────────────────────────────────────────
def load_all_data(conn) -> dict:
    """加载所有需要的数据。"""
    cur = conn.cursor()
    logger.info("加载数据...")

    # 1. 北向个股持仓(日频)
    cur.execute("""
        SELECT code, trade_date, hold_vol FROM northbound_holdings
        WHERE trade_date >= %s AND trade_date <= %s AND hold_vol IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, FULL_END))
    nb_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "hold_vol"])
    nb_df["trade_date"] = pd.to_datetime(nb_df["trade_date"])
    nb_df["hold_vol"] = nb_df["hold_vol"].astype(float)
    logger.info("  北向: %d行, %d只", len(nb_df), nb_df["code"].nunique())

    # 2. 价格(adj_close)
    cur.execute("""
        SELECT code, trade_date, close * adj_factor as adj_close
        FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s
          AND close IS NOT NULL AND adj_factor IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, FULL_END))
    price_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "adj_close"])
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    price_df["adj_close"] = price_df["adj_close"].astype(float)
    logger.info("  价格: %d行", len(price_df))

    # 3. 流通市值
    cur.execute("""
        SELECT code, trade_date, circ_mv FROM daily_basic
        WHERE trade_date >= %s AND trade_date <= %s AND circ_mv IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, FULL_END))
    mv_df = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "circ_mv"])
    mv_df["trade_date"] = pd.to_datetime(mv_df["trade_date"])
    mv_df["circ_mv"] = mv_df["circ_mv"].astype(float)  # 万元
    logger.info("  市值: %d行", len(mv_df))

    # 4. 沪深300日收益
    cur.execute("""
        SELECT trade_date, pct_change FROM index_daily
        WHERE index_code = '000300.SH' AND trade_date >= %s ORDER BY trade_date
    """, (DATA_START,))
    idx = pd.DataFrame(cur.fetchall(), columns=["trade_date", "pct_change"])
    idx["trade_date"] = pd.to_datetime(idx["trade_date"])
    idx["ret"] = idx["pct_change"].astype(float) / 100
    csi300_ret = idx.set_index("trade_date")["ret"]
    logger.info("  CSI300: %d天", len(csi300_ret))

    # 5. 行业映射
    cur.execute("SELECT code, industry_sw_l1 FROM symbols WHERE market='astock' AND industry_sw_l1 IS NOT NULL")
    ind_map = dict(cur.fetchall())
    logger.info("  行业映射: %d只", len(ind_map))

    # 6. CSI300权重(最新一期)
    cur.execute("""
        SELECT code, weight FROM index_components
        WHERE index_code = '000300.SH'
        AND trade_date = (SELECT MAX(trade_date) FROM index_components WHERE index_code='000300.SH')
    """)
    csi_weights = {}
    for code_full, w in cur.fetchall():
        # 去掉.SH/.SZ后缀
        code_short = code_full.split(".")[0]
        csi_weights[code_short] = float(w) / 100  # 百分比→小数
    logger.info("  CSI300权重: %d只", len(csi_weights))

    return {
        "nb_df": nb_df,
        "price_df": price_df,
        "mv_df": mv_df,
        "csi300_ret": csi300_ret,
        "ind_map": ind_map,
        "csi_weights": csi_weights,
    }


def build_market_panel(data: dict) -> pd.DataFrame:
    """构建市场级面板: 每天一行，含北向汇总指标。"""
    nb_df = data["nb_df"]
    price_df = data["price_df"]
    mv_df = data["mv_df"]
    csi300_ret = data["csi300_ret"]
    ind_map = data["ind_map"]
    csi_weights = data["csi_weights"]

    # 北向pivot
    nb_pivot = nb_df.pivot(index="trade_date", columns="code", values="hold_vol")
    nb_pivot = nb_pivot.ffill()  # 缺失=前值

    price_pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")
    mv_pivot = mv_df.pivot(index="trade_date", columns="code", values="circ_mv")
    mv_pivot = mv_pivot.ffill()

    # 对齐
    common_dates = nb_pivot.index.intersection(price_pivot.index)
    common_codes = nb_pivot.columns.intersection(price_pivot.columns)
    nb = nb_pivot.loc[common_dates, common_codes]
    price = price_pivot.reindex(index=common_dates, columns=common_codes)
    mv = mv_pivot.reindex(index=common_dates, columns=common_codes).ffill()

    # 持仓变化(股)
    hold_diff = nb.diff(1)
    # 净买入金额 = 持仓变化 × adj_close
    net_buy_amount = hold_diff * price

    logger.info("面板: %d天 × %d只", len(common_dates), len(common_codes))

    # ── 逐天计算15个因子 ──
    records = []
    for i, dt in enumerate(common_dates):
        if i == 0:
            continue  # 需要diff

        diff_row = hold_diff.loc[dt]
        nb_row = nb.loc[dt]
        nba_row = net_buy_amount.loc[dt]
        valid = diff_row.dropna()
        if len(valid) < 50:
            continue

        increasing = valid[valid > 0]
        decreasing = valid[valid < 0]

        rec = {"trade_date": dt}

        # ── 第一组: 行为模式 ──
        # 1. nb_breadth_ratio
        n_up = len(increasing)
        n_down = len(decreasing)
        rec["nb_breadth_ratio"] = n_up / max(n_down, 1)

        # 2. nb_buy_concentration (HHI)
        pos_amounts = nba_row[nba_row > 0].dropna()
        if len(pos_amounts) > 0 and pos_amounts.sum() > 0:
            shares = pos_amounts / pos_amounts.sum()
            rec["nb_buy_concentration"] = float((shares ** 2).sum())
        else:
            rec["nb_buy_concentration"] = np.nan

        # 3. nb_asymmetry
        if len(increasing) > 0 and len(decreasing) > 0:
            nb_prev = nb.iloc[i - 1].reindex(valid.index)
            inc_pct = (increasing / nb_prev.reindex(increasing.index).replace(0, np.nan)).dropna()
            dec_pct = (decreasing.abs() / nb_prev.reindex(decreasing.index).replace(0, np.nan)).dropna()
            if len(inc_pct) > 0 and len(dec_pct) > 0:
                mean_inc = inc_pct.mean()
                mean_dec = dec_pct.mean()
                rec["nb_asymmetry"] = mean_inc / max(mean_dec, 1e-10)
            else:
                rec["nb_asymmetry"] = np.nan
        else:
            rec["nb_asymmetry"] = np.nan

        # 4. nb_turnover
        total_abs_diff = valid.abs().sum()
        net_diff = abs(valid.sum())
        prev_total = nb.iloc[i - 1].sum()
        if prev_total > 0:
            rec["nb_turnover"] = (total_abs_diff - net_diff) / 2 / prev_total
        else:
            rec["nb_turnover"] = np.nan

        # ── 简单汇总供后续rolling ──
        rec["daily_net_flow"] = valid.sum()  # 全市场净买入(股)
        rec["daily_net_amount"] = nba_row.dropna().sum()  # 全市场净买入(元)

        # 沪深股通拆分
        sh_codes = [c for c in valid.index if c.startswith("6")]
        sz_codes = [c for c in valid.index if c.startswith("0") or c.startswith("3")]
        sh_net = nba_row.reindex(sh_codes).dropna().sum()
        sz_net = nba_row.reindex(sz_codes).dropna().sum()
        rec["sh_net"] = sh_net
        rec["sz_net"] = sz_net

        # 行业分布
        ind_amounts = {}
        for code in nba_row.dropna().index:
            ind = ind_map.get(code, "其他")
            ind_amounts[ind] = ind_amounts.get(ind, 0) + nba_row[code]
        rec["_ind_amounts"] = ind_amounts

        # CSI300 Active Share
        # 北向持仓权重
        nb_total_mv = 0
        nb_stock_mv = {}
        for code in nb_row.dropna().index:
            if nb_row[code] > 0 and code in price.columns:
                p = price.loc[dt, code]
                if not np.isnan(p):
                    stock_mv = nb_row[code] * p
                    nb_stock_mv[code] = stock_mv
                    nb_total_mv += stock_mv
        if nb_total_mv > 0:
            active_share = 0
            all_codes = set(list(nb_stock_mv.keys()) + list(csi_weights.keys()))
            for code in all_codes:
                nb_w = nb_stock_mv.get(code, 0) / nb_total_mv
                csi_w = csi_weights.get(code, 0)
                active_share += abs(nb_w - csi_w)
            rec["nb_active_share_raw"] = active_share / 2
        else:
            rec["nb_active_share_raw"] = np.nan

        # 市值加权中位数(size preference)
        wm_values = []
        for code in increasing.index:
            if code in mv.columns:
                m = mv.loc[dt, code]
                if not np.isnan(m):
                    wm_values.append(m)
        rec["nb_size_median"] = np.median(wm_values) if wm_values else np.nan

        records.append(rec)

    panel = pd.DataFrame(records).set_index("trade_date").sort_index()
    logger.info("市场面板: %d天", len(panel))

    # ── Rolling因子 ──
    net = panel["daily_net_flow"]
    # 5. nb_contrarian_market_5d
    csi_aligned = csi300_ret.reindex(panel.index)
    contrarian_daily = net * (-csi_aligned)
    panel["nb_contrarian_market_5d"] = contrarian_daily.rolling(5).sum()

    # 6. nb_size_shift_20d
    sm = panel["nb_size_median"]
    panel["nb_size_shift_20d"] = sm / sm.shift(20).replace(0, np.nan) - 1

    # 7. nb_extreme_outflow (过去252天P5)
    def rolling_extreme(s, window=252, pct=0.05, direction="low"):
        result = pd.Series(np.nan, index=s.index)
        vals = s.values
        for j in range(60, len(vals)):
            start = max(0, j - window)
            hist = vals[start:j]
            if direction == "low":
                thresh = np.nanpercentile(hist, pct * 100)
                result.iloc[j] = 1.0 if vals[j] < thresh else 0.0
            else:
                thresh = np.nanpercentile(hist, (1 - pct) * 100)
                result.iloc[j] = 1.0 if vals[j] > thresh else 0.0
        return result

    panel["nb_extreme_outflow"] = rolling_extreme(net, direction="low")

    # 8. nb_extreme_inflow
    panel["nb_extreme_inflow"] = rolling_extreme(net, direction="high")

    # 9. nb_vol_change
    vol_5 = net.rolling(5).std()
    vol_60 = net.rolling(60).std().replace(0, np.nan)
    panel["nb_vol_change"] = vol_5 / vol_60

    # 10. nb_streak_reversal
    outflow = (net < 0).astype(int)
    inflow = (net > 0).astype(int)
    streak = pd.Series(0.0, index=panel.index)
    count = 0
    for j in range(len(net)):
        if inflow.iloc[j]:
            count = count + 1 if count > 0 else 1
        elif outflow.iloc[j]:
            count = count - 1 if count < 0 else -1
        else:
            count = 0
        streak.iloc[j] = count
    # 反转信号: 连续流入越久→值越负(预示反转下跌)
    panel["nb_streak_reversal"] = -streak / 10

    # 11. nb_sh_sz_divergence
    sh = panel["sh_net"]
    sz = panel["sz_net"]
    denom = sh.abs() + sz.abs() + 1e-10
    panel["nb_sh_sz_divergence"] = ((sh - sz) / denom).rolling(5).mean()

    # 12. nb_industry_rotation
    # 需要从_ind_amounts列提取行业占比变化的std
    ind_history = []
    for _idx_val, row in panel.iterrows():
        ia = row.get("_ind_amounts", {})
        if isinstance(ia, dict) and ia:
            total = sum(abs(v) for v in ia.values()) + 1e-10
            shares = {k: v / total for k, v in ia.items()}
            ind_history.append(shares)
        else:
            ind_history.append({})
    ind_df = pd.DataFrame(ind_history, index=panel.index).fillna(0)
    # 行业占比的20日变化标准差
    ind_change = ind_df.diff(20)
    panel["nb_industry_rotation"] = ind_change.std(axis=1).rolling(5).mean()

    # 13. nb_active_share (已在逐天计算中作为raw)
    panel["nb_active_share"] = panel["nb_active_share_raw"].rolling(5).mean()

    # 14. nb_reverse_percentile
    def rolling_percentile(s, window=252, min_periods=60):
        result = pd.Series(np.nan, index=s.index)
        vals = s.values
        for j in range(min_periods, len(vals)):
            start = max(0, j - window)
            hist = vals[start:j]
            if len(hist) < min_periods:
                continue
            result.iloc[j] = np.sum(hist < vals[j]) / len(hist)
        return result

    pct = rolling_percentile(net)
    panel["nb_reverse_percentile"] = 1.0 - pct  # 直接反转

    # 15. nb_momentum_divergence
    # 北向5日流入方向 vs 市场5日动量方向的背离
    nb_5d_dir = net.rolling(5).sum()
    mkt_5d_dir = csi_aligned.rolling(5).sum()
    # 标准化后相乘: 同向为正，反向为负
    nb_z = (nb_5d_dir - nb_5d_dir.rolling(60).mean()) / nb_5d_dir.rolling(60).std().replace(0, np.nan)
    mkt_z = (mkt_5d_dir - mkt_5d_dir.rolling(60).mean()) / mkt_5d_dir.rolling(60).std().replace(0, np.nan)
    panel["nb_momentum_divergence"] = -(nb_z * mkt_z)  # 负=背离=信号

    # 清理临时列
    panel = panel.drop(columns=["daily_net_flow", "daily_net_amount", "sh_net", "sz_net",
                                 "nb_size_median", "nb_active_share_raw", "_ind_amounts"],
                        errors="ignore")

    logger.info("因子计算完成: %d列", len(panel.columns))
    for col in FACTOR_NAMES:
        if col in panel.columns:
            valid = panel[col].dropna()
            logger.info("  %-30s: %d有效值, mean=%.4f", col, len(valid), valid.mean())

    return panel


# ── 信号评估 ─────────────────────────────────────────────────
def evaluate_factor(
    factor: pd.Series,
    market_ret: pd.Series,
    start: date,
    end: date,
    horizons: list[int] | None = None,
) -> dict:
    """评估市场级因子的预测能力。"""
    if horizons is None:
        horizons = HORIZONS

    mask = (factor.index >= pd.Timestamp(start)) & (factor.index <= pd.Timestamp(end))
    f = factor[mask].dropna()
    r = market_ret.reindex(f.index)

    result = {"n_days": len(f)}

    # 1. 各horizon相关性
    best_corr = 0
    best_h = 0
    for h in horizons:
        fwd = r.rolling(h).sum().shift(-h)
        valid = ~(f.isna() | fwd.isna())
        if valid.sum() < 30:
            continue
        corr, pval = sp_stats.spearmanr(f[valid], fwd[valid])
        if np.isnan(corr):
            continue
        t_stat = corr * np.sqrt((valid.sum() - 2) / (1 - corr ** 2 + 1e-10))
        result[f"corr_{h}d"] = round(corr, 4)
        result[f"pval_{h}d"] = round(pval, 4)
        result[f"tstat_{h}d"] = round(t_stat, 2)
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_h = h

    result["best_horizon"] = best_h
    result["best_corr"] = round(best_corr, 4)

    # 2. 分5组单调性(20日horizon)
    fwd_20 = r.rolling(20).sum().shift(-20)
    df = pd.DataFrame({"f": f, "fwd": fwd_20}).dropna()
    if len(df) > 50:
        try:
            df["group"] = pd.qcut(df["f"], 5, labels=["Q1", "Q2", "Q3", "Q4", "Q5"])
            group_means = df.groupby("group", observed=False)["fwd"].mean()
            result["q1_ret"] = round(group_means.get("Q1", np.nan) * 100, 2)
            result["q5_ret"] = round(group_means.get("Q5", np.nan) * 100, 2)
            # 单调性: Q1-Q5递增为正
            vals = [group_means.get(f"Q{i}", np.nan) for i in range(1, 6)]
            diffs = [vals[i + 1] - vals[i] for i in range(4) if not np.isnan(vals[i]) and not np.isnan(vals[i + 1])]
            if diffs:
                result["monotonicity"] = round(sum(1 for d in diffs if d > 0) / len(diffs), 2)
        except (ValueError, KeyError):
            pass

    # 3. 滚动稳定性(60天窗口)
    if best_h > 0:
        fwd_best = r.rolling(best_h).sum().shift(-best_h)
        rolling_corr = f.rolling(60).corr(fwd_best)
        pos_ratio = (rolling_corr > 0).mean()
        result["stability_pos_ratio"] = round(pos_ratio, 2)

    return result


# ── 回测 ─────────────────────────────────────────────────────
def backtest_modifier_factor(
    factor: pd.Series,
    market_ret: pd.Series,
    start: date,
    end: date,
    direction: int = 1,
    label: str = "",
) -> dict:
    """基于因子值做仓位调节回测。"""
    mask = (factor.index >= pd.Timestamp(start)) & (factor.index <= pd.Timestamp(end))
    f = factor[mask].dropna()
    r = market_ret.reindex(f.index).dropna()
    common = f.index.intersection(r.index)
    f = f[common]
    r = r[common]

    if len(r) < 30:
        return {"label": label, "sharpe": 0, "mdd": 0, "cagr": 0}

    # 因子值→百分位→仓位系数
    pct = f.rolling(252, min_periods=60).apply(
        lambda x: np.sum(x[:-1] < x[-1]) / max(len(x) - 1, 1), raw=True
    )
    if direction == -1:
        pct = 1 - pct

    # 映射到仓位: P>0.7→1.0, P0.3-0.7→0.8, P0.1-0.3→0.5, P<0.1→0.3
    coeff = pd.Series(0.8, index=pct.index)
    coeff[pct > 0.7] = 1.0
    coeff[(pct > 0.1) & (pct <= 0.3)] = 0.5
    coeff[pct <= 0.1] = 0.3
    coeff = coeff.rolling(5, min_periods=1).mean().clip(0.2, 1.0)

    adj_ret = r * coeff.reindex(r.index).ffill().fillna(1.0)
    nav = (1 + adj_ret).cumprod()

    n_years = len(r) / 252
    total_ret = nav.iloc[-1] - 1
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    sharpe = adj_ret.mean() / adj_ret.std() * np.sqrt(252) if adj_ret.std() > 0 else 0
    mdd = ((nav - nav.cummax()) / nav.cummax()).min()

    return {
        "label": label,
        "sharpe": round(sharpe, 3),
        "mdd": round(float(mdd) * 100, 2),
        "cagr": round(cagr * 100, 2),
        "avg_coeff": round(coeff.mean(), 3),
        "n_reduced": int((coeff < 0.8).sum()),
    }


# ── 报告 ─────────────────────────────────────────────────────
def generate_report(
    eval_results: dict,
    oos_results: dict,
    bt_results: list,
    output_path: Path,
):
    """生成研究报告。"""
    lines = [
        "# 北向资金市场级MODIFIER因子V2研究报告",
        "",
        f"> 生成时间: {date.today()}",
        f"> 训练期: {FULL_START}~{TRAIN_END} | OOS: {OOS_START}~{FULL_END}",
        f"> 因子数: {len(FACTOR_DEFS)}个",
        "",
        "## 1. 因子定义",
        "",
        "| # | 因子 | 含义 |",
        "|---|------|------|",
    ]
    for i, (name, desc) in enumerate(FACTOR_DEFS, 1):
        lines.append(f"| {i} | {name} | {desc} |")

    # 训练期结果
    lines.extend(["", "## 2. 训练期信号质量 (2021-2023)", "",
                   "| 因子 | 最优horizon | 最优corr | t_stat | Q1收益% | Q5收益% | 单调性 | 稳定性 |",
                   "|------|-----------|---------|--------|---------|---------|--------|--------|"])

    sorted_train = sorted(eval_results.items(), key=lambda x: abs(x[1].get("best_corr", 0)), reverse=True)
    for fname, r in sorted_train:
        bh = r.get("best_horizon", "?")
        bc = r.get("best_corr", 0)
        t = r.get(f"tstat_{bh}d", "?")
        q1 = r.get("q1_ret", "?")
        q5 = r.get("q5_ret", "?")
        mono = r.get("monotonicity", "?")
        stab = r.get("stability_pos_ratio", "?")
        lines.append(f"| {fname} | {bh}d | {bc:+.4f} | {t} | {q1} | {q5} | {mono} | {stab} |")

    # OOS验证
    lines.extend(["", "## 3. OOS验证 (2024-2025)", "",
                   "| 因子 | 最优horizon | OOS corr | OOS t | 训练corr | 方向一致 |",
                   "|------|-----------|---------|-------|---------|---------|"])
    for fname, oos_r in sorted(oos_results.items(), key=lambda x: abs(x[1].get("best_corr", 0)), reverse=True):
        train_r = eval_results.get(fname, {})
        bh = oos_r.get("best_horizon", "?")
        oos_c = oos_r.get("best_corr", 0)
        oos_t = oos_r.get(f"tstat_{bh}d", "?")
        train_c = train_r.get("best_corr", 0)
        same_dir = "Yes" if (oos_c * train_c > 0 and abs(oos_c) > 0.03) else "No"
        lines.append(f"| {fname} | {bh}d | {oos_c:+.4f} | {oos_t} | {train_c:+.4f} | {same_dir} |")

    # 回测对比
    if bt_results:
        lines.extend(["", "## 4. 仓位调节回测 (有效因子, 全期)", "",
                       "| 策略 | Sharpe | MDD% | CAGR% | 平均仓位 | 减仓天数 |",
                       "|------|--------|------|-------|---------|---------|"])
        for r in bt_results:
            lines.append(
                f"| {r['label']} | {r['sharpe']} | {r['mdd']} | {r['cagr']} | "
                f"{r.get('avg_coeff', '?')} | {r.get('n_reduced', '?')} |"
            )

    # 结论
    effective = [f for f, r in oos_results.items()
                 if abs(r.get("best_corr", 0)) > 0.03
                 and eval_results.get(f, {}).get("best_corr", 0) * r.get("best_corr", 0) > 0]

    lines.extend([
        "", "## 5. 结论", "",
        f"- 训练期+OOS双验证通过(方向一致且|corr|>0.03): **{len(effective)}个因子**",
        f"- 有效因子: {', '.join(effective) if effective else '无'}",
        "",
        "### vs V1对比",
        "- V1(4因子): 信号方向反向(corr=-0.093), 无法做择时",
        f"- V2(15因子): 从行为模式/极端事件/跨板块等维度挖掘, {len(effective)}个因子通过OOS验证",
    ])

    report = "\n".join(lines)
    output_path.write_text(report, encoding="utf-8")
    logger.info("报告: %s (%d字符)", output_path, len(report))


# ── 主流程 ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="只算前5个因子(调试)")
    args = parser.parse_args()

    conn = get_conn()
    data = load_all_data(conn)
    panel = build_market_panel(data)
    csi300_ret = data["csi300_ret"]

    # 训练期评估
    logger.info("=== 训练期评估 ===")
    eval_results = {}
    for fname, _desc in FACTOR_DEFS:
        if fname not in panel.columns:
            logger.warning("  %s: 不在面板中", fname)
            continue
        if args.quick and len(eval_results) >= 5:
            break
        r = evaluate_factor(panel[fname], csi300_ret, FULL_START, TRAIN_END)
        eval_results[fname] = r
        bc = r.get("best_corr", 0)
        bh = r.get("best_horizon", 0)
        logger.info("  %-30s corr=%+.4f @%dd, Q1=%.2f%%, Q5=%.2f%%",
                     fname, bc, bh,
                     r.get("q1_ret", 0), r.get("q5_ret", 0))

    # OOS评估
    logger.info("=== OOS评估 ===")
    oos_results = {}
    for fname in eval_results:
        r = evaluate_factor(panel[fname], csi300_ret, OOS_START, FULL_END)
        oos_results[fname] = r
        bc = r.get("best_corr", 0)
        train_bc = eval_results[fname].get("best_corr", 0)
        same = "Yes" if bc * train_bc > 0 and abs(bc) > 0.03 else "No"
        logger.info("  %-30s OOS_corr=%+.4f (train=%+.4f) → %s",
                     fname, bc, train_bc, same)

    # 有效因子回测
    logger.info("=== 有效因子回测 ===")
    effective = [f for f, r in oos_results.items()
                 if abs(r.get("best_corr", 0)) > 0.03
                 and eval_results.get(f, {}).get("best_corr", 0) * r.get("best_corr", 0) > 0]

    # 基准(inline计算，不依赖外部模块)
    mask_b = (csi300_ret.index >= pd.Timestamp(FULL_START)) & (csi300_ret.index <= pd.Timestamp(FULL_END))
    base_ret = csi300_ret[mask_b]
    base_nav = (1 + base_ret).cumprod()
    n_yr = len(base_ret) / 252
    b_total = float(base_nav.iloc[-1]) - 1
    b_cagr = (1 + b_total) ** (1 / n_yr) - 1 if n_yr > 0 else 0
    b_sharpe = float(base_ret.mean() / base_ret.std() * np.sqrt(252)) if base_ret.std() > 0 else 0
    b_mdd = float(((base_nav - base_nav.cummax()) / base_nav.cummax()).min())
    base = {
        "label": "满仓CSI300", "sharpe": round(b_sharpe, 3),
        "mdd": round(b_mdd * 100, 2), "cagr": round(b_cagr * 100, 2),
        "avg_coeff": 1.0, "n_reduced": 0,
    }

    bt_results = [base]
    for fname in effective:
        # 确定方向
        direction = 1 if eval_results[fname]["best_corr"] > 0 else -1
        r = backtest_modifier_factor(
            panel[fname], csi300_ret, FULL_START, FULL_END,
            direction=direction, label=f"MODIFIER({fname})",
        )
        bt_results.append(r)
        logger.info("  %s: Sharpe=%.3f MDD=%.2f%% CAGR=%.2f%%",
                     fname, r["sharpe"], r["mdd"], r["cagr"])

    # IC写入factor_ic_history (铁律11)
    cur = conn.cursor()
    today = date.today()
    for fname, r in eval_results.items():
        bc = r.get("best_corr", 0)
        cur.execute("""
            INSERT INTO factor_ic_history (factor_name, trade_date, ic_20d, ic_ma20, decay_level)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (factor_name, trade_date) DO UPDATE SET
                ic_20d = EXCLUDED.ic_20d, ic_ma20 = EXCLUDED.ic_ma20
        """, (f"mkt_{fname}", today, float(r.get("corr_20d", 0)), float(bc), "mkt"))
    conn.commit()
    logger.info("factor_ic_history写入%d条", len(eval_results))

    # 报告
    report_path = Path(__file__).resolve().parent.parent / "docs" / "NORTHBOUND_MARKET_FACTORS_REPORT.md"
    generate_report(eval_results, oos_results, bt_results, report_path)

    # 写入modifier_signals (有效因子)
    if effective:
        best_fname = effective[0]
        direction = 1 if eval_results[best_fname]["best_corr"] > 0 else -1
        f = panel[best_fname]
        pct = f.rolling(252, min_periods=60).apply(
            lambda x: np.sum(x[:-1] < x[-1]) / max(len(x) - 1, 1), raw=True
        )
        if direction == -1:
            pct = 1 - pct
        coeff = pd.Series(0.8, index=pct.index)
        coeff[pct > 0.7] = 1.0
        coeff[(pct > 0.1) & (pct <= 0.3)] = 0.5
        coeff[pct <= 0.1] = 0.3
        coeff = coeff.rolling(5, min_periods=1).mean().clip(0.2, 1.0)

        mask = (coeff.index >= pd.Timestamp(FULL_START)) & (coeff.index <= pd.Timestamp(FULL_END))
        coeff_save = coeff[mask].dropna()

        import psycopg2.extras
        params = {"factor": best_fname, "direction": direction}
        rows = [(dt.date(), f"nb_modifier_v2_{best_fname}", float(c),
                 None, None, None, None, json.dumps(params))
                for dt, c in coeff_save.items()]
        if rows:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO modifier_signals
                   (trade_date, modifier_name, coefficient, nb_flow_5d_change,
                    nb_flow_20d_avg, nb_flow_percentile, nb_consecutive_outflow, params_json)
                   VALUES %s ON CONFLICT (trade_date, modifier_name) DO UPDATE SET
                     coefficient = EXCLUDED.coefficient, params_json = EXCLUDED.params_json""",
                rows, page_size=500,
            )
            conn.commit()
            logger.info("modifier_signals写入%d行(%s)", len(rows), best_fname)

    conn.close()
    logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
