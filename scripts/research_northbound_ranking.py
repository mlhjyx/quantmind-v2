"""北向资金个股RANKING因子深度挖掘。

从northbound_holdings表构建15个个股截面因子，
计算IC并跑factor_profiler画像，筛选有效因子。

数据: northbound_holdings(hold_vol) + klines_daily(close/adj_factor) + daily_basic(float_share/circ_mv)
范围: 2021-01-01 ~ 2025-12-31, 2020年做rolling warmup

用法:
    python scripts/research_northbound_ranking.py             # 全量计算+画像
    python scripts/research_northbound_ranking.py --calc-only # 只计算因子
    python scripts/research_northbound_ranking.py --profile-only # 只跑画像
"""

import argparse
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────
DATA_START = date(2020, 1, 1)  # warmup
CALC_START = date(2021, 1, 1)
CALC_END = date(2025, 12, 31)

# 15个因子定义: (name, direction, mechanism)
FACTOR_DEFS = [
    # 第一组: 持仓比例变化类
    ("nb_ratio_change_5d", 1,
     "外资5日增持→正面信息尚未反映→预测上涨"),
    ("nb_ratio_change_20d", 1,
     "外资20日持续增持→中期趋势性看好→预测上涨"),
    ("nb_change_rate_20d", 1,
     "外资持仓相对变化率→小基数翻倍比大基数微增信息量大→预测上涨"),
    # 第二组: 持续性信号类
    ("nb_consecutive_increase", 1,
     "外资连续增持天数→持续性买入=conviction强→预测上涨"),
    ("nb_increase_ratio_20d", 1,
     "20日中增持天数占比→一致性增持信号→预测上涨"),
    ("nb_trend_20d", 1,
     "持仓线性趋势斜率→趋势性增持=机构持续建仓→预测上涨"),
    # 第三组: 相对市场类
    ("nb_change_excess", 1,
     "个股增持超额(去市场中位数)→被外资偏爱→预测上涨"),
    ("nb_rank_change_20d", 1,
     "持仓比例排名变化→相对其他股票被增持更多→预测上涨"),
    # 第四组: 金额口径类
    ("nb_net_buy_ratio", 1,
     "日均净买入额/流通市值→资金流入强度→预测上涨"),
    ("nb_net_buy_5d_ratio", 1,
     "5日累计净买入额/流通市值→短期资金涌入→预测上涨"),
    ("nb_net_buy_20d_ratio", 1,
     "20日累计净买入额/流通市值→中期资金流入→预测上涨"),
    # 第五组: 交互/条件类
    ("nb_contrarian", 1,
     "北向增持×股价下跌→外资逆势买入=信息优势→预测反弹"),
    ("nb_acceleration", 1,
     "持仓变化加速度→增持在加速=信心增强→预测上涨"),
    ("nb_new_entry", 1,
     "外资从0→有持仓→首次关注=新信息→预测上涨(EVENT类)"),
    ("nb_concentration_signal", 1,
     "持仓比例从低于中位数升到高于→集中买入→预测上涨"),
]

FACTOR_NAMES = [f[0] for f in FACTOR_DEFS]


def get_db_conn():
    return psycopg2.connect(
        dbname="quantmind_v2", user="xin", password="quantmind", host="localhost"
    )


# ── 数据加载 ─────────────────────────────────────────────────
def load_data(conn) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """加载北向持股 + 价格 + 基本面数据。"""
    cur = conn.cursor()

    # 1. 北向持股(日频)
    logger.info("加载北向持股数据...")
    cur.execute("""
        SELECT code, trade_date, hold_vol
        FROM northbound_holdings
        WHERE trade_date >= %s AND trade_date <= %s AND hold_vol IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, CALC_END))
    nb_rows = cur.fetchall()
    nb_df = pd.DataFrame(nb_rows, columns=["code", "trade_date", "hold_vol"])
    nb_df["trade_date"] = pd.to_datetime(nb_df["trade_date"])
    nb_df["hold_vol"] = nb_df["hold_vol"].astype(float)
    logger.info("  北向: %d行, %d只股票", len(nb_df), nb_df["code"].nunique())

    # 2. 价格(close + adj_factor)
    logger.info("加载价格数据...")
    cur.execute("""
        SELECT code, trade_date, close, adj_factor
        FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s
          AND close IS NOT NULL AND adj_factor IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, CALC_END))
    price_rows = cur.fetchall()
    price_df = pd.DataFrame(price_rows, columns=["code", "trade_date", "close", "adj_factor"])
    price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])
    price_df["close"] = price_df["close"].astype(float)
    price_df["adj_factor"] = price_df["adj_factor"].astype(float)
    price_df["adj_close"] = price_df["close"] * price_df["adj_factor"]
    logger.info("  价格: %d行, %d只股票", len(price_df), price_df["code"].nunique())

    # 3. daily_basic(float_share + circ_mv)
    logger.info("加载基本面数据...")
    cur.execute("""
        SELECT code, trade_date, float_share, circ_mv
        FROM daily_basic
        WHERE trade_date >= %s AND trade_date <= %s
          AND float_share IS NOT NULL AND circ_mv IS NOT NULL
        ORDER BY code, trade_date
    """, (DATA_START, CALC_END))
    basic_rows = cur.fetchall()
    basic_df = pd.DataFrame(basic_rows, columns=["code", "trade_date", "float_share", "circ_mv"])
    basic_df["trade_date"] = pd.to_datetime(basic_df["trade_date"])
    basic_df["float_share"] = basic_df["float_share"].astype(float)
    basic_df["circ_mv"] = basic_df["circ_mv"].astype(float)
    logger.info("  基本面: %d行, %d只股票", len(basic_df), basic_df["code"].nunique())

    return nb_df, price_df, basic_df


def build_panel(
    nb_df: pd.DataFrame,
    price_df: pd.DataFrame,
    basic_df: pd.DataFrame,
) -> pd.DataFrame:
    """合并为 (code, trade_date) 索引的面板，前值填充缺失日期。"""
    logger.info("构建合并面板...")

    # 北向pivot
    nb_pivot = nb_df.pivot(index="trade_date", columns="code", values="hold_vol")
    # 前值填充(缺失≠清仓)
    nb_pivot = nb_pivot.ffill()

    # 价格pivot
    price_pivot = price_df.pivot(index="trade_date", columns="code", values="adj_close")

    # float_share pivot
    fs_pivot = basic_df.pivot(index="trade_date", columns="code", values="float_share")
    fs_pivot = fs_pivot.ffill()

    # circ_mv pivot
    mv_pivot = basic_df.pivot(index="trade_date", columns="code", values="circ_mv")
    mv_pivot = mv_pivot.ffill()

    # 对齐交易日和股票（取北向和价格的交集）
    common_dates = nb_pivot.index.intersection(price_pivot.index)
    common_codes = nb_pivot.columns.intersection(price_pivot.columns)
    common_codes = common_codes.intersection(fs_pivot.columns)

    logger.info(
        "  交集: %d天 × %d只股票",
        len(common_dates), len(common_codes),
    )

    panel = pd.DataFrame(index=common_dates)
    panel.attrs["codes"] = common_codes
    panel.attrs["nb"] = nb_pivot.loc[common_dates, common_codes]
    panel.attrs["price"] = price_pivot.reindex(index=common_dates, columns=common_codes)
    panel.attrs["fs"] = fs_pivot.reindex(index=common_dates, columns=common_codes).ffill()
    panel.attrs["mv"] = mv_pivot.reindex(index=common_dates, columns=common_codes).ffill()

    return panel


# ── 因子计算 ─────────────────────────────────────────────────
def calc_all_factors(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """计算15个因子，每个返回 (trade_date × code) 的DataFrame。"""
    nb = panel.attrs["nb"]  # hold_vol pivot
    price = panel.attrs["price"]  # adj_close pivot
    fs = panel.attrs["fs"]  # float_share pivot (万股)
    mv = panel.attrs["mv"]  # circ_mv pivot (万元)
    codes = panel.attrs["codes"]

    # float_share单位是万股，hold_vol是股 → 统一为股
    fs_shares = fs * 10000  # 万股→股

    # 持仓比例 = hold_vol / float_share (转为股)
    holding_ratio = nb / fs_shares

    # 持仓变化(股数口径)
    hold_diff_1 = nb.diff(1)
    hold_diff_20 = nb.diff(20)

    # 净买入金额 = 持仓变化(股) × adj_close
    net_buy_amount = hold_diff_1 * price

    # circ_mv单位是万元 → 转为元
    mv_yuan = mv * 10000

    factors = {}
    logger.info("计算15个因子...")

    # 1. nb_ratio_change_5d
    factors["nb_ratio_change_5d"] = holding_ratio.diff(5)
    logger.info("  [1/15] nb_ratio_change_5d")

    # 2. nb_ratio_change_20d
    factors["nb_ratio_change_20d"] = holding_ratio.diff(20)
    logger.info("  [2/15] nb_ratio_change_20d")

    # 3. nb_change_rate_20d (相对变化率)
    nb_20ago = nb.shift(20)
    factors["nb_change_rate_20d"] = hold_diff_20 / nb_20ago.replace(0, np.nan)
    logger.info("  [3/15] nb_change_rate_20d")

    # 4. nb_consecutive_increase (连续增持天数)
    increasing = (hold_diff_1 > 0).astype(int)
    consec = pd.DataFrame(0, index=nb.index, columns=codes)
    for i in range(1, len(consec)):
        prev = consec.iloc[i - 1]
        curr_inc = increasing.iloc[i]
        consec.iloc[i] = (prev + 1) * curr_inc  # 增持+1, 否则归0
    factors["nb_consecutive_increase"] = consec.astype(float)
    logger.info("  [4/15] nb_consecutive_increase")

    # 5. nb_increase_ratio_20d (20日中增持天数占比)
    factors["nb_increase_ratio_20d"] = increasing.rolling(20).mean()
    logger.info("  [5/15] nb_increase_ratio_20d")

    # 6. nb_trend_20d (20日线性回归斜率/均值)
    def rolling_slope(series, window=20):
        """滚动线性回归斜率。"""
        x = np.arange(window, dtype=float)
        x_mean = x.mean()
        x_var = ((x - x_mean) ** 2).sum()
        result = series.rolling(window).apply(
            lambda y: np.sum((x - x_mean) * (y - y.mean())) / x_var if y.std() > 0 else 0,
            raw=True,
        )
        return result

    # 对每只股票计算slope，然后标准化
    slope_frames = []
    for col in codes:
        s = nb[col].dropna()
        if len(s) < 25:
            continue
        slope = rolling_slope(s)
        mean20 = s.rolling(20).mean().replace(0, np.nan)
        slope_frames.append((slope / mean20).rename(col))

    if slope_frames:
        factors["nb_trend_20d"] = pd.concat(slope_frames, axis=1).reindex(
            index=nb.index, columns=codes
        )
    else:
        factors["nb_trend_20d"] = pd.DataFrame(np.nan, index=nb.index, columns=codes)
    logger.info("  [6/15] nb_trend_20d")

    # 7. nb_change_excess (去市场中位数)
    ratio_change_20d = factors["nb_ratio_change_20d"]
    market_median = ratio_change_20d.median(axis=1)
    factors["nb_change_excess"] = ratio_change_20d.sub(market_median, axis=0)
    logger.info("  [7/15] nb_change_excess")

    # 8. nb_rank_change_20d (截面排名变化)
    rank_today = holding_ratio.rank(axis=1, pct=True)
    rank_20ago = holding_ratio.shift(20).rank(axis=1, pct=True)
    factors["nb_rank_change_20d"] = rank_today - rank_20ago
    logger.info("  [8/15] nb_rank_change_20d")

    # 9. nb_net_buy_ratio (日净买入额/流通市值)
    factors["nb_net_buy_ratio"] = net_buy_amount / mv_yuan.replace(0, np.nan)
    logger.info("  [9/15] nb_net_buy_ratio")

    # 10. nb_net_buy_5d_ratio (5日累计)
    factors["nb_net_buy_5d_ratio"] = (
        net_buy_amount.rolling(5).sum() / mv_yuan.replace(0, np.nan)
    )
    logger.info("  [10/15] nb_net_buy_5d_ratio")

    # 11. nb_net_buy_20d_ratio (20日累计)
    factors["nb_net_buy_20d_ratio"] = (
        net_buy_amount.rolling(20).sum() / mv_yuan.replace(0, np.nan)
    )
    logger.info("  [11/15] nb_net_buy_20d_ratio")

    # 12. nb_contrarian (北向增持 × -momentum_20)
    momentum_20 = price.pct_change(20)
    factors["nb_contrarian"] = ratio_change_20d * (-momentum_20)
    logger.info("  [12/15] nb_contrarian")

    # 13. nb_acceleration (持仓变化加速度)
    ratio_change_5d = factors["nb_ratio_change_5d"]
    factors["nb_acceleration"] = ratio_change_5d - ratio_change_5d.shift(5)
    logger.info("  [13/15] nb_acceleration")

    # 14. nb_new_entry (新进信号: 从0→有持仓)
    has_holding = nb > 0
    no_holding_20ago = nb.shift(20).fillna(0) == 0
    factors["nb_new_entry"] = (has_holding & no_holding_20ago).astype(float)
    logger.info("  [14/15] nb_new_entry")

    # 15. nb_concentration_signal
    median_ratio = holding_ratio.median(axis=1)
    above_median = holding_ratio.gt(median_ratio, axis=0)
    below_median_20ago = holding_ratio.shift(20).lt(median_ratio.shift(20), axis=0)
    factors["nb_concentration_signal"] = (above_median & below_median_20ago).astype(float)
    logger.info("  [15/15] nb_concentration_signal")

    # 统计
    for name, df in factors.items():
        mask = (df.index >= pd.Timestamp(CALC_START)) & (df.index <= pd.Timestamp(CALC_END))
        valid = df.loc[mask].notna().sum().sum()
        logger.info("    %s: %d有效值 (calc期间)", name, valid)

    return factors


# ── 写入DB ───────────────────────────────────────────────────
def save_factors_to_db(conn, factors: dict[str, pd.DataFrame], batch_size: int = 5000):
    """写入factor_values表。"""
    cur = conn.cursor()

    for fname, df in factors.items():
        # 只写calc期间
        mask = (df.index >= pd.Timestamp(CALC_START)) & (df.index <= pd.Timestamp(CALC_END))
        df_calc = df.loc[mask]

        # 先删除该因子的旧数据
        cur.execute(
            "DELETE FROM factor_values WHERE factor_name = %s AND trade_date >= %s AND trade_date <= %s",
            (fname, CALC_START, CALC_END),
        )

        # melt为长表
        df_long = df_calc.stack().reset_index()
        df_long.columns = ["trade_date", "code", "raw_value"]
        df_long = df_long.dropna(subset=["raw_value"])
        df_long["factor_name"] = fname

        if len(df_long) == 0:
            logger.warning("  %s: 无有效数据，跳过", fname)
            continue

        # 批量写入
        rows = [
            (r["code"], r["trade_date"].date(), fname, float(r["raw_value"]), None, None)
            for _, r in df_long.iterrows()
        ]

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO factor_values (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                   VALUES %s ON CONFLICT (code, trade_date, factor_name) DO UPDATE SET
                     raw_value = EXCLUDED.raw_value""",
                batch, page_size=batch_size,
            )

        conn.commit()
        logger.info("  %s: 写入%d行", fname, len(rows))

    logger.info("全部因子写入完成")


# ── IC计算 ───────────────────────────────────────────────────
def calc_factor_ic(conn, factor_name: str, horizon: int = 20) -> pd.Series:
    """计算因子的截面IC(Spearman rank correlation)。"""
    from scipy import stats

    cur = conn.cursor()

    # 因子值
    cur.execute("""
        SELECT code, trade_date, raw_value FROM factor_values
        WHERE factor_name = %s AND trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date, code
    """, (factor_name, CALC_START, CALC_END))
    fv = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "value"])
    fv["trade_date"] = pd.to_datetime(fv["trade_date"])
    fv["value"] = fv["value"].astype(float)

    # 未来收益
    cur.execute("""
        SELECT code, trade_date, close * adj_factor as adj_close
        FROM klines_daily
        WHERE trade_date >= %s AND trade_date <= %s AND close IS NOT NULL
        ORDER BY code, trade_date
    """, (CALC_START, date(2026, 6, 30)))  # 多加半年做forward return
    prices = pd.DataFrame(cur.fetchall(), columns=["code", "trade_date", "adj_close"])
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices["adj_close"] = prices["adj_close"].astype(float)

    price_pivot = prices.pivot(index="trade_date", columns="code", values="adj_close")
    fwd_ret = price_pivot.pct_change(horizon).shift(-horizon)

    # 按月计算IC
    fv_pivot = fv.pivot(index="trade_date", columns="code", values="value")
    # 取月末日期
    monthly_dates = fv_pivot.resample("ME").last().index

    ic_series = {}
    for dt in monthly_dates:
        # 找最近的交易日
        valid_dates = fv_pivot.index[fv_pivot.index <= dt]
        if len(valid_dates) == 0:
            continue
        actual_dt = valid_dates[-1]

        fv_row = fv_pivot.loc[actual_dt].dropna()
        if actual_dt not in fwd_ret.index:
            continue
        ret_row = fwd_ret.loc[actual_dt].dropna()

        common = fv_row.index.intersection(ret_row.index)
        if len(common) < 30:
            continue

        corr, _ = stats.spearmanr(fv_row[common], ret_row[common])
        if not np.isnan(corr):
            ic_series[dt] = corr

    return pd.Series(ic_series)


# ── IC写入(铁律11) ────────────────────────────────────────────
def save_ic_history(conn, ic_results: dict):
    """将IC计算结果写入factor_ic_history表（铁律11合规）。"""
    cur = conn.cursor()
    today = date.today()

    for fname, r in ic_results.items():
        mean_ic = r["mean_ic"]
        # 写一条汇总记录，trade_date=today表示本次计算的结果
        cur.execute("""
            INSERT INTO factor_ic_history
                (factor_name, trade_date, ic_20d, ic_ma20, decay_level)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (factor_name, trade_date) DO UPDATE SET
                ic_20d = EXCLUDED.ic_20d,
                ic_ma20 = EXCLUDED.ic_ma20,
                decay_level = EXCLUDED.decay_level
        """, (
            fname, today, float(mean_ic), float(mean_ic),
            "unknown",  # 单horizon计算，decay未知
        ))

    conn.commit()
    logger.info("  factor_ic_history写入%d条", len(ic_results))


# ── 主流程 ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="北向资金个股RANKING因子")
    parser.add_argument("--calc-only", action="store_true", help="只计算因子，不跑画像")
    parser.add_argument("--profile-only", action="store_true", help="只跑画像")
    parser.add_argument("--ic-only", action="store_true", help="只算IC")
    args = parser.parse_args()

    conn = get_db_conn()

    if not args.profile_only and not args.ic_only:
        # ── Step 1: 数据加载 ──
        nb_df, price_df, basic_df = load_data(conn)

        # ── Step 2: 构建面板 ──
        panel = build_panel(nb_df, price_df, basic_df)

        # ── Step 3: 计算因子 ──
        factors = calc_all_factors(panel)

        # ── Step 4: 写入DB ──
        logger.info("=== 写入factor_values ===")
        save_factors_to_db(conn, factors)

    if args.calc_only:
        conn.close()
        logger.info("计算完成(--calc-only)")
        return

    # ── Step 5: IC计算 ──
    logger.info("=== IC计算(20日horizon) ===")
    ic_results = {}
    for fname, direction, mechanism in FACTOR_DEFS:
        ic_s = calc_factor_ic(conn, fname, horizon=20)
        if len(ic_s) == 0:
            logger.warning("  %s: 无IC数据", fname)
            continue

        mean_ic = ic_s.mean()
        std_ic = ic_s.std()
        t_stat = mean_ic / (std_ic / np.sqrt(len(ic_s))) if std_ic > 0 else 0
        ic_results[fname] = {
            "mean_ic": mean_ic,
            "std_ic": std_ic,
            "t_stat": t_stat,
            "n_months": len(ic_s),
            "direction": direction,
            "mechanism": mechanism,
            "ic_positive_ratio": (ic_s > 0).mean(),
        }
        status = "Active" if abs(t_stat) >= 2.0 else ("Weak" if abs(t_stat) >= 1.0 else "Rejected")
        logger.info(
            "  %-28s IC=%+.4f t=%.2f pct_pos=%.0f%% → %s",
            fname, mean_ic, t_stat, (ic_s > 0).mean() * 100, status,
        )

    # ── Step 5b: IC写入factor_ic_history（铁律11） ──
    logger.info("=== 写入factor_ic_history ===")
    save_ic_history(conn, ic_results)

    # ── Step 6: 汇总报告 ──
    report_path = Path(__file__).resolve().parent.parent / "docs" / "NORTHBOUND_RANKING_FACTORS_REPORT.md"
    generate_report(ic_results, report_path)

    # ── Step 7: factor_profiler画像(如果可用) ──
    if not args.ic_only:
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
            from engines.factor_profiler import profile_factor

            active_factors = [
                f for f, r in ic_results.items() if abs(r["t_stat"]) >= 1.5
            ]
            if active_factors:
                logger.info("=== 跑factor_profiler画像(%d个因子) ===", len(active_factors))
                for fname in active_factors:
                    try:
                        profile_factor(fname, conn=conn)
                        logger.info("  %s 画像完成", fname)
                    except Exception as e:
                        logger.warning("  %s 画像失败: %s", fname, str(e)[:80])
            else:
                logger.info("无Active/Weak因子，跳过画像")
        except ImportError:
            logger.warning("factor_profiler导入失败，跳过画像")

    conn.close()
    logger.info("=== 完成 ===")


def generate_report(ic_results: dict, output_path: Path):
    """生成因子研究报告。"""
    lines = [
        "# 北向资金个股RANKING因子研究报告",
        "",
        f"> 生成时间: {date.today()}",
        f"> 数据范围: {CALC_START} ~ {CALC_END}",
        f"> 因子数量: {len(FACTOR_DEFS)}个候选",
        "",
        "## 1. 因子IC汇总",
        "",
        "| 因子 | IC均值 | t统计量 | 正IC占比 | 月数 | 状态 |",
        "|------|--------|---------|----------|------|------|",
    ]

    active = []
    weak = []
    rejected = []

    sorted_results = sorted(ic_results.items(), key=lambda x: abs(x[1]["t_stat"]), reverse=True)
    for fname, r in sorted_results:
        t = r["t_stat"]
        if abs(t) >= 2.0:
            status = "**Active**"
            active.append(fname)
        elif abs(t) >= 1.0:
            status = "Weak"
            weak.append(fname)
        else:
            status = "Rejected"
            rejected.append(fname)

        lines.append(
            f"| {fname} | {r['mean_ic']:+.4f} | {t:.2f} | "
            f"{r['ic_positive_ratio']*100:.0f}% | {r['n_months']} | {status} |"
        )

    lines.extend([
        "",
        "## 2. 筛选结果",
        "",
        f"- **Active** (|t|>=2.0): {len(active)}个 — {', '.join(active) if active else '无'}",
        f"- **Weak** (1.0<=|t|<2.0): {len(weak)}个 — {', '.join(weak) if weak else '无'}",
        f"- **Rejected** (|t|<1.0): {len(rejected)}个",
        "",
        "## 3. 因子经济机制",
        "",
        "| 因子 | 方向 | 经济机制 |",
        "|------|------|----------|",
    ])

    for fname, direction, mechanism in FACTOR_DEFS:
        dir_str = "+" if direction == 1 else "-"
        lines.append(f"| {fname} | {dir_str} | {mechanism} |")

    lines.extend([
        "",
        "## 4. 结论",
        "",
    ])

    if active:
        lines.extend([
            f"发现{len(active)}个IC显著的北向RANKING因子。",
            "这些因子基于外资机构的个股选择行为，可能与量价因子低相关，",
            "值得进一步验证与现有5核心因子的增量贡献。",
        ])
    else:
        lines.extend([
            "15个北向RANKING因子均未达到Active标准(|t|>=2.0)。",
            "可能原因: 1)北向持股数据的信息已被price-in; ",
            "2)持仓变化是价格的滞后反应而非领先指标; ",
            "3)因子构造方式仍需改进。",
        ])

    report = "\n".join(lines)
    output_path.write_text(report, encoding="utf-8")
    logger.info("报告已生成: %s (%d字符)", output_path, len(report))


if __name__ == "__main__":
    main()
