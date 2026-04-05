"""财务质量因子计算 — Route C。

三个候选因子:
1. roe_change_q: ROE季度环比变化（盈利改善信号）
2. revenue_accel: 营收增速加速度（增长拐点信号）
3. accrual_anomaly: 应计异常（盈利质量信号）

⚠️ CLAUDE.md强制规则:
  - 必须用actual_ann_date做PIT时间对齐（不用report_date）
  - 因子值在ann_date之后才可用，回测中不得提前使用
  - 百分比字段已×100（roe=15.23表示15.23%）
"""

from datetime import date

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


def load_financial_pit(
    trade_date: date,
    conn,
) -> pd.DataFrame:
    """加载截至trade_date的PIT财务数据。

    Point-In-Time: 只取actual_ann_date <= trade_date的记录。
    同一(code, report_date)取ann_date最新（最终版）。

    Returns:
        DataFrame [code, report_date, actual_ann_date, roe, roe_dt, roa,
                   revenue_yoy, net_profit_yoy, gross_profit_margin, ...]
        每个code保留最近4个季度的数据。
    """
    df = pd.read_sql(
        """WITH ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY code, report_date
                       ORDER BY actual_ann_date DESC
                   ) AS rn
            FROM financial_indicators
            WHERE actual_ann_date <= %s
        )
        SELECT code, report_date, actual_ann_date,
               roe, roe_dt, roa,
               gross_profit_margin, net_profit_margin,
               revenue_yoy, net_profit_yoy, basic_eps_yoy,
               eps, bps, current_ratio, quick_ratio, debt_to_asset
        FROM ranked
        WHERE rn = 1
        ORDER BY code, report_date DESC""",
        conn,
        params=(trade_date,),
    )
    return df


def calc_roe_change_q(fina_df: pd.DataFrame) -> pd.Series:
    """因子1: ROE季度环比变化。

    定义: roe_change_q = ROE(最新季) - ROE(上一季)
    经济逻辑: 正值=盈利改善，反映基本面拐点。
    方向: +1（越大越好）

    使用roe_dt（扣非ROE）更真实。
    """
    if fina_df.empty:
        return pd.Series(dtype=float)

    # 每个code取最近2个季度
    results = {}
    for code, grp in fina_df.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False).head(2)
        if len(grp) < 2:
            continue

        # 优先用roe_dt（扣非），fallback到roe
        roe_col = "roe_dt" if grp["roe_dt"].notna().all() else "roe"
        roe_latest = grp.iloc[0][roe_col]
        roe_prev = grp.iloc[1][roe_col]

        if pd.notna(roe_latest) and pd.notna(roe_prev):
            results[code] = float(roe_latest) - float(roe_prev)

    return pd.Series(results, name="roe_change_q")


def calc_revenue_accel(fina_df: pd.DataFrame) -> pd.Series:
    """因子2: 营收增速加速度。

    定义: revenue_accel = revenue_yoy(最新季) - revenue_yoy(上一季)
    经济逻辑: 正值=增速在加速，负值=增速在放缓。
    方向: +1（加速增长更好）
    """
    if fina_df.empty:
        return pd.Series(dtype=float)

    results = {}
    for code, grp in fina_df.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False).head(2)
        if len(grp) < 2:
            continue

        rev_latest = grp.iloc[0]["revenue_yoy"]
        rev_prev = grp.iloc[1]["revenue_yoy"]

        if pd.notna(rev_latest) and pd.notna(rev_prev):
            results[code] = float(rev_latest) - float(rev_prev)

    return pd.Series(results, name="revenue_accel")


def calc_accrual_anomaly(fina_df: pd.DataFrame) -> pd.Series:
    """因子3: 应计异常（简化版）。

    定义: accrual = net_profit_margin - (经营现金流/营收)
    简化近似: accrual ≈ net_profit_margin - roa × (总资产/营收)
    更简单的proxy: accrual ≈ net_profit_yoy - revenue_yoy
    （盈利增长>营收增长 → 应计部分大 → 盈利质量差）

    经济逻辑: 高应计=盈利中"纸面利润"占比大，未来容易回吐。
    方向: -1（越低越好，低应计=高质量盈利）

    注: 完整版需要income_statement + cashflow数据。
    Phase 1简化版用 net_profit_yoy - revenue_yoy 作为proxy。
    """
    if fina_df.empty:
        return pd.Series(dtype=float)

    results = {}
    for code, grp in fina_df.groupby("code"):
        latest = grp.sort_values("report_date", ascending=False).iloc[0]

        np_yoy = latest.get("net_profit_yoy")
        rev_yoy = latest.get("revenue_yoy")

        if pd.notna(np_yoy) and pd.notna(rev_yoy):
            # 利润增速 - 营收增速 = 应计贡献
            results[code] = float(np_yoy) - float(rev_yoy)

    return pd.Series(results, name="accrual_anomaly")


def compute_financial_factors(
    trade_date: date,
    conn,
) -> pd.DataFrame:
    """计算单日全部财务质量因子。

    Args:
        trade_date: 交易日
        conn: psycopg2连接

    Returns:
        DataFrame [code, factor_name, raw_value]
    """
    fina_df = load_financial_pit(trade_date, conn)
    if fina_df.empty:
        logger.warning(f"[FinaFactor] {trade_date} 无PIT财务数据")
        return pd.DataFrame()

    n_stocks = fina_df["code"].nunique()
    logger.info(f"[FinaFactor] {trade_date}: 加载{n_stocks}只股票财务数据")

    # 计算3个因子
    factors = {
        "roe_change_q": calc_roe_change_q(fina_df),
        "revenue_accel": calc_revenue_accel(fina_df),
        "accrual_anomaly": calc_accrual_anomaly(fina_df),
    }

    # 合并为长表
    rows = []
    for fname, series in factors.items():
        for code, val in series.items():
            if np.isfinite(val):
                rows.append({"code": code, "factor_name": fname, "raw_value": val})

    result = pd.DataFrame(rows)
    if not result.empty:
        for fname in factors:
            n = len(result[result["factor_name"] == fname])
            logger.info(f"  {fname}: {n}只")

    return result


# 因子方向映射（用于信号合成）
FINANCIAL_FACTOR_DIRECTION = {
    "roe_change_q": 1,       # 越大越好（盈利改善）
    "revenue_accel": 1,      # 越大越好（增速加速）
    "accrual_anomaly": -1,   # 越小越好（低应计=高质量）
    "roe_momentum_3q": 1,    # 越大越好（3Q平滑ROE改善）
}


def calc_roe_momentum_3q(fina_df: pd.DataFrame) -> pd.Series:
    """基本面动量因子: 3季度移动平均ROE变化。

    海通研报方案: 单季度ROE环比噪声大，用3季度移动平均平滑。
    定义: MA3_curr = mean(ROE_Q0, ROE_Q1, ROE_Q2)
          MA3_prev = mean(ROE_Q1, ROE_Q2, ROE_Q3)
          roe_momentum_3q = MA3_curr - MA3_prev
    方向: +1 (越大越好，盈利趋势改善)

    需要至少4个季度数据。使用roe_dt(扣非ROE)，fallback到roe。

    Args:
        fina_df: load_financial_pit返回的DataFrame，每个code有最近4季数据

    Returns:
        pd.Series: index=code, value=roe_momentum_3q
    """
    if fina_df.empty:
        return pd.Series(dtype=float, name="roe_momentum_3q")

    results: dict[str, float] = {}
    for code, grp in fina_df.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False).head(4)
        if len(grp) < 4:
            continue

        # 优先用roe_dt（扣非），fallback到roe
        roe_col = "roe_dt" if grp["roe_dt"].notna().sum() >= 4 else "roe"
        roe_vals = grp[roe_col].values  # Q0(最新), Q1, Q2, Q3(最旧)

        if np.any(pd.isna(roe_vals)):
            continue

        roe_vals = roe_vals.astype(float)
        ma3_curr = np.mean(roe_vals[0:3])  # Q0, Q1, Q2
        ma3_prev = np.mean(roe_vals[1:4])  # Q1, Q2, Q3
        results[code] = ma3_curr - ma3_prev

    return pd.Series(results, dtype=float, name="roe_momentum_3q")
