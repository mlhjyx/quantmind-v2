"""Factor repository — 所有因子计算所需的 DB 读取操作集中地。

Phase C C2 (2026-04-16) 从 `backend/engines/factor_engine/__init__.py` 搬家到此,
用于强化铁律 31 (Engine 层纯计算) — Engine 不再读写 DB, 数据加载改走 Repository.

搬家原则 (prep 文档 §拆分方案):
    1. **SQL 字符串 100% 原样保留** — 任何 SQL 改动都可能引入 max_diff 漂移
    2. **signature 保留** — 保留 `conn=None` 自动建连, 避免强迫 25 个调用方改签名
    3. **无计算逻辑** — 仅做 read_sql + 轻量 DataFrame 整形, 不做 calc/preprocess

函数清单:
    * load_daily_data           — 单日 klines+basic+symbols (120d lookback)
    * load_forward_returns      — T+1→T+horizon 前瞻**超额**收益 (legacy, 铁律 19 应走 ic_calculator)
    * load_bulk_data            — 区间 klines+basic+symbols
    * load_bulk_moneyflow       — 区间 moneyflow_daily
    * load_index_returns        — 区间指数日收益率
    * load_bulk_data_with_extras— load_bulk_data + moneyflow + index 合并
    * load_fundamental_pit_data — PIT 基本面 delta 计算 (含计算, 是唯一的例外, C3 可能进一步纯化)
    * load_pead_announcements   — PEAD Q1 季报查询 (C2 新增, 从 calc_pead_q1 拆出)

未搬家 (C3 范围):
    * save_daily_factors        — DataPipeline 写入 (已合规, C3 搬到 factor_compute_service)
    * compute_daily_factors     — orchestrator (C3)
    * compute_batch_factors     — orchestrator + INSERT 违规 (C3 改走 DataPipeline)

注意事项:
    - `load_fundamental_pit_data` 内部调 `engines.financial_factors.load_financial_pit`
      该函数本身也是 DB 读取, 暂时保留跨层依赖. C2 只搬家, 不跨 package 整理.
    - 本模块的 logger name 是 "app.services.factor_repository", 不是原来的
      "engines.factor_engine.__init__", 在 structlog 上游分析时需要注意.

见: docs/audit/PHASE_C_F31_PREP.md §Milestones C2
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ============================================================
# 单日加载 (PT 因子计算主入口)
# ============================================================


def load_daily_data(
    trade_date: date,
    lookback_days: int = 120,
    conn=None,
) -> pd.DataFrame:
    """加载因子计算所需的每日数据。

    合并 klines_daily + daily_basic, 计算前复权价格。

    Args:
        trade_date: 计算日期
        lookback_days: 回看天数(用于滚动计算)
        conn: psycopg2连接

    Returns:
        DataFrame with columns: code, trade_date, open, high, low, close,
        volume, amount, adj_factor, adj_close, adj_high, adj_low,
        turnover_rate, total_mv, pb, pe_ttm, industry_sw1
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        )
        SELECT
            k.code,
            k.trade_date,
            k.open, k.high, k.low, k.close,
            k.volume, k.amount,
            k.adj_factor,
            k.close * k.adj_factor / la.latest_adj_factor AS adj_close,
            k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
            k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
            db.turnover_rate,
            db.total_mv,
            db.pb,
            db.pe_ttm,
            db.dv_ttm,
            s.industry_sw1
        FROM klines_daily k
        JOIN latest_adj la ON k.code = la.code
        LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        LEFT JOIN symbols s ON k.code = s.code
        WHERE k.trade_date BETWEEN
            (SELECT DISTINCT trade_date FROM klines_daily
             WHERE trade_date <= %s
             ORDER BY trade_date DESC
             OFFSET %s LIMIT 1)
            AND %s
          AND k.adj_factor IS NOT NULL
          AND k.volume > 0
        ORDER BY k.code, k.trade_date
        """
        df = pd.read_sql(sql, conn, params=(trade_date, lookback_days, trade_date))
        return df
    finally:
        if close_conn:
            conn.close()


def load_forward_returns(
    trade_date: date,
    horizon: int = 5,
    conn=None,
) -> pd.Series:
    """加载前向超额收益(vs CSI300)。

    [Legacy] 铁律 19 要求新路径走 engines/ic_calculator.compute_forward_excess_returns.
    本函数仅保留向后兼容, 未来 session 可能 DEPRECATED.

    Args:
        trade_date: 基准日期
        horizon: 前看天数(1/5/10/20)
        conn: psycopg2连接

    Returns:
        pd.Series indexed by code, values = excess return
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 先找到N个交易日后的日期
        future_date_df = pd.read_sql(
            """SELECT DISTINCT trade_date FROM klines_daily
               WHERE trade_date > %s ORDER BY trade_date LIMIT %s""",
            conn,
            params=(trade_date, horizon),
        )
        if future_date_df.empty:
            return pd.Series(dtype=float)
        future_date = future_date_df.iloc[-1]["trade_date"]

        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        ),
        base AS (
            SELECT k.code,
                   k.close * k.adj_factor / la.latest_adj_factor AS adj_close
            FROM klines_daily k
            JOIN latest_adj la ON k.code = la.code
            WHERE k.trade_date = %s AND k.adj_factor IS NOT NULL
        ),
        future AS (
            SELECT k.code,
                   k.close * k.adj_factor / la.latest_adj_factor AS adj_close
            FROM klines_daily k
            JOIN latest_adj la ON k.code = la.code
            WHERE k.trade_date = %s AND k.adj_factor IS NOT NULL
        )
        SELECT
            b.code,
            (f.adj_close / NULLIF(b.adj_close, 0) - 1)
            - (
                (SELECT close FROM index_daily
                 WHERE index_code = '000300.SH' AND trade_date = %s)
                / NULLIF(
                    (SELECT close FROM index_daily
                     WHERE index_code = '000300.SH' AND trade_date = %s), 0)
                - 1
              ) AS excess_return
        FROM base b
        JOIN future f ON b.code = f.code
        """
        df = pd.read_sql(
            sql,
            conn,
            params=(trade_date, future_date, future_date, trade_date),
        )
        return df.set_index("code")["excess_return"]
    finally:
        if close_conn:
            conn.close()


# ============================================================
# 批量加载 (回测/研究/GP 主入口)
# ============================================================


def load_bulk_data(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载行情数据(含前复权价格)。

    一次性加载 [start_date-120天, end_date] 的全部数据，
    避免逐日加载的重复IO。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame sorted by (code, trade_date)
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH latest_adj AS (
            SELECT DISTINCT ON (code)
                code, adj_factor AS latest_adj_factor
            FROM klines_daily
            ORDER BY code, trade_date DESC
        ),
        lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT
            k.code,
            k.trade_date,
            k.open, k.high, k.low, k.close,
            k.volume, k.amount,
            k.adj_factor,
            k.close * k.adj_factor / la.latest_adj_factor AS adj_close,
            k.high  * k.adj_factor / la.latest_adj_factor AS adj_high,
            k.low   * k.adj_factor / la.latest_adj_factor AS adj_low,
            db.turnover_rate,
            db.total_mv,
            db.pb,
            db.pe_ttm,
            db.dv_ttm,
            s.industry_sw1
        FROM klines_daily k
        JOIN latest_adj la ON k.code = la.code
        LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
        LEFT JOIN symbols s ON k.code = s.code
        WHERE k.trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
          AND k.adj_factor IS NOT NULL
          AND k.volume > 0
        ORDER BY k.code, k.trade_date
        """
        logger.info(f"批量加载数据: {start_date} → {end_date} (+120天回看)")
        df = pd.read_sql(sql, conn, params=(start_date, end_date))
        logger.info(
            f"数据加载完成: {len(df)}行, {df['code'].nunique()}股, {df['trade_date'].nunique()}天"
        )
        return df
    finally:
        if close_conn:
            conn.close()


# ============================================================
# ML特征数据加载 (moneyflow + index)
# ============================================================


def load_bulk_moneyflow(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载资金流数据。

    加载 [start_date-120天, end_date] 的 moneyflow_daily 数据。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame with moneyflow columns, sorted by (code, trade_date)
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT
            mf.code,
            mf.trade_date,
            mf.buy_sm_amount,
            mf.buy_md_amount,
            mf.buy_lg_amount,
            mf.buy_elg_amount,
            mf.net_mf_amount
        FROM moneyflow_daily mf
        WHERE mf.trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
        ORDER BY mf.code, mf.trade_date
        """
        logger.info(f"批量加载资金流数据: {start_date} → {end_date} (+120天回看)")
        df = pd.read_sql(sql, conn, params=(start_date, end_date))
        logger.info(f"资金流数据加载完成: {len(df)}行, {df['code'].nunique()}股")
        return df
    finally:
        if close_conn:
            conn.close()


def load_index_returns(
    start_date: date,
    end_date: date,
    index_code: str = "000300.SH",
    conn=None,
) -> pd.Series:
    """加载指数日收益率序列。

    用于计算个股beta。返回以trade_date为index的收益率Series。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        index_code: 指数代码, 默认沪深300
        conn: psycopg2连接

    Returns:
        pd.Series: 指数日收益率, index=trade_date
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        sql = """
        WITH lookback_start AS (
            SELECT COALESCE(
                (SELECT DISTINCT trade_date FROM klines_daily
                 WHERE trade_date <= %s
                 ORDER BY trade_date DESC
                 OFFSET 120 LIMIT 1),
                (SELECT MIN(trade_date) FROM klines_daily)
            ) AS trade_date
        )
        SELECT trade_date, close
        FROM index_daily
        WHERE index_code = %s
          AND trade_date BETWEEN (SELECT trade_date FROM lookback_start) AND %s
        ORDER BY trade_date
        """
        logger.info(f"加载指数 {index_code} 收益率: {start_date} → {end_date}")
        df = pd.read_sql(sql, conn, params=(start_date, index_code, end_date))
        if df.empty:
            logger.warning(f"指数 {index_code} 无数据")
            return pd.Series(dtype=float)
        ret = df.set_index("trade_date")["close"].pct_change(1)
        ret.name = "index_ret"
        return ret
    finally:
        if close_conn:
            conn.close()


def load_bulk_data_with_extras(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """批量加载行情+资金流+指数收益率数据(ML特征专用)。

    在 load_bulk_data 基础上, 左连接 moneyflow_daily 的资金流字段,
    并合并沪深300日收益率(按trade_date对齐)。

    Args:
        start_date: 计算开始日期
        end_date: 计算结束日期
        conn: psycopg2连接

    Returns:
        DataFrame with all columns needed for ML features
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 1. 基础行情数据
        df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return df

        # 2. 资金流数据
        mf = load_bulk_moneyflow(start_date, end_date, conn=conn)
        if not mf.empty:
            df = df.merge(mf, on=["code", "trade_date"], how="left")
            logger.info(f"合并资金流数据: moneyflow匹配率 {df['net_mf_amount'].notna().mean():.1%}")
        else:
            logger.warning("资金流数据为空, moneyflow因子将全为NaN")
            for col in [
                "buy_sm_amount",
                "buy_md_amount",
                "buy_lg_amount",
                "buy_elg_amount",
                "net_mf_amount",
            ]:
                df[col] = np.nan

        # 3. 指数收益率
        idx_ret = load_index_returns(start_date, end_date, conn=conn)
        if not idx_ret.empty:
            idx_ret_df = idx_ret.reset_index()
            idx_ret_df.columns = ["trade_date", "index_ret"]
            df = df.merge(idx_ret_df, on="trade_date", how="left")
            logger.info(f"合并指数收益率: index_ret匹配率 {df['index_ret'].notna().mean():.1%}")
        else:
            logger.warning("指数收益率为空, beta因子将全为NaN")
            df["index_ret"] = np.nan

        return df
    finally:
        if close_conn:
            conn.close()


# ============================================================
# PEAD Q1 季报公告加载 (Phase C C2 新增, 从 calc_pead_q1 拆出)
# ============================================================


def load_pead_announcements(
    conn,
    trade_date: date,
    lookback_days: int = 7,
) -> pd.DataFrame:
    """加载 trade_date 附近 N 天窗口内的 Q1 财报公告 (供 PEAD 因子使用).

    只使用 report_type='Q1' 的公告. 同一股票可能有多条 (返回全部, 由 pure 函数去重).
    eps_surprise_pct 字段: 绝对值 < 10 (过滤异常).

    Phase C C2 (2026-04-16): 从原 `calc_pead_q1(trade_date, conn)` 拆出的 DB 读取部分.
    配套 `engines.factor_engine.pead.calc_pead_q1_from_announcements` 为纯函数部分.

    Args:
        conn: psycopg2 连接 (调用方负责生命周期)
        trade_date: 基准日 (date 或 str)
        lookback_days: 回看窗口 (默认 7 天, 公告后信号衰减)

    Returns:
        DataFrame with columns ['ts_code', 'eps_surprise_pct', 'ann_td'],
        按 (ts_code, ann_td DESC) 排序. 无数据时返回空 DataFrame 保留列名.
    """
    if isinstance(trade_date, str):
        from datetime import datetime as _dt

        trade_date = _dt.strptime(trade_date, "%Y-%m-%d").date()

    cur = conn.cursor()
    cur.execute(
        """SELECT ea.ts_code, ea.eps_surprise_pct, ea.trade_date AS ann_td
        FROM earnings_announcements ea
        WHERE ea.report_type = 'Q1'
          AND ea.trade_date <= %s
          AND ea.trade_date >= %s - INTERVAL '1 day' * %s
          AND ea.eps_surprise_pct IS NOT NULL
          AND ABS(ea.eps_surprise_pct) < 10
        ORDER BY ea.ts_code, ea.trade_date DESC""",
        (trade_date, trade_date, lookback_days),
    )

    rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["ts_code", "eps_surprise_pct", "ann_td"])

    return pd.DataFrame(rows, columns=["ts_code", "eps_surprise_pct", "ann_td"])


# ============================================================
# 基本面 PIT 数据加载 (Sprint 1.5)
# 注: 本函数既包含 DB 读取 (load_financial_pit) 又包含 delta 计算逻辑.
# 为保持最小风险, C2 整体搬家不做计算/IO 分离. C3 或未来 session 可进一步纯化.
# ============================================================


def load_fundamental_pit_data(
    trade_date: date,
    conn,
) -> dict[str, pd.Series]:
    """加载并计算基本面delta特征(PIT对齐)。

    对每个trade_date:
    - 调用 load_financial_pit 获取每只股票可见的最近4季财报
    - 取"当期"(最新) 和"上期"(次新) 两行计算delta

    Args:
        trade_date: 交易日
        conn: psycopg2连接

    Returns:
        dict[factor_name -> pd.Series(index=code, value=raw)]
        包含6个delta因子 + 2个时间因子
    """
    from engines.factor_engine._constants import FUNDAMENTAL_ALL_FEATURES
    from engines.financial_factors import load_financial_pit

    fina_df = load_financial_pit(trade_date, conn)
    if fina_df.empty:
        logger.warning(f"[FundDelta] {trade_date} 无PIT财务数据")
        return {name: pd.Series(dtype=float) for name in FUNDAMENTAL_ALL_FEATURES}

    n_stocks = fina_df["code"].nunique()
    logger.debug(f"[FundDelta] {trade_date}: {n_stocks}只股票")

    # --- 计算6个delta因子 ---
    roe_delta: dict[str, float] = {}
    revenue_growth_yoy: dict[str, float] = {}
    gross_margin_delta: dict[str, float] = {}
    eps_acceleration: dict[str, float] = {}
    debt_change: dict[str, float] = {}
    net_margin_delta: dict[str, float] = {}

    # --- 时间因子 ---
    days_since_ann: dict[str, float] = {}

    for code, grp in fina_df.groupby("code"):
        grp = grp.sort_values("report_date", ascending=False, kind="mergesort")
        latest = grp.iloc[0]
        prev = grp.iloc[1] if len(grp) >= 2 else None

        # 1. roe_delta: (当期ROE - 上期ROE) / abs(上期ROE + 1e-8)
        if prev is not None:
            roe_col = (
                "roe_dt"
                if pd.notna(latest.get("roe_dt")) and pd.notna(prev.get("roe_dt"))
                else "roe"
            )
            roe_curr = latest.get(roe_col)
            roe_prev = prev.get(roe_col)
            if pd.notna(roe_curr) and pd.notna(roe_prev):
                roe_delta[code] = float(roe_curr - roe_prev) / (abs(float(roe_prev)) + 1e-8)

        # 2. revenue_growth_yoy: 直接取字段
        rev_yoy = latest.get("revenue_yoy")
        if pd.notna(rev_yoy):
            revenue_growth_yoy[code] = float(rev_yoy) / 100.0  # 百分比→小数

        # 3. gross_margin_delta: 当期 - 上期 (百分点差值)
        if prev is not None:
            gm_curr = latest.get("gross_profit_margin")
            gm_prev = prev.get("gross_profit_margin")
            if pd.notna(gm_curr) and pd.notna(gm_prev):
                gross_margin_delta[code] = float(gm_curr) - float(gm_prev)

        # 4. eps_acceleration: 当期basic_eps_yoy - 上期basic_eps_yoy
        if prev is not None:
            eps_yoy_curr = latest.get("basic_eps_yoy")
            eps_yoy_prev = prev.get("basic_eps_yoy")
            if pd.notna(eps_yoy_curr) and pd.notna(eps_yoy_prev):
                eps_acceleration[code] = (float(eps_yoy_curr) - float(eps_yoy_prev)) / 100.0

        # 5. debt_change: 当期debt_to_asset - 上期debt_to_asset
        if prev is not None:
            d_curr = latest.get("debt_to_asset")
            d_prev = prev.get("debt_to_asset")
            if pd.notna(d_curr) and pd.notna(d_prev):
                debt_change[code] = float(d_curr) - float(d_prev)

        # 6. net_margin_delta: 当期net_profit_margin - 上期net_profit_margin
        if prev is not None:
            nm_curr = latest.get("net_profit_margin")
            nm_prev = prev.get("net_profit_margin")
            if pd.notna(nm_curr) and pd.notna(nm_prev):
                net_margin_delta[code] = float(nm_curr) - float(nm_prev)

        # 7. days_since_announcement
        ann_date = latest.get("actual_ann_date")
        if pd.notna(ann_date):
            if isinstance(ann_date, str):
                from datetime import datetime as _dt

                ann_date = _dt.strptime(ann_date, "%Y-%m-%d").date()
            elif hasattr(ann_date, "date"):
                ann_date = ann_date.date()
            days_since_ann[code] = float((trade_date - ann_date).days)

    # 8. reporting_season_flag (不依赖个股, 取trade_date月份)
    month = trade_date.month
    season_flag = 1.0 if month in (4, 8, 10) else 0.0

    # --- clip极端值 ---
    def _clip_series(d: dict, lo: float, hi: float) -> pd.Series:
        """将dict转为Series并clip。"""
        s = pd.Series(d, dtype=float)
        return s.clip(lower=lo, upper=hi)

    results: dict[str, pd.Series] = {
        "roe_delta": _clip_series(roe_delta, -2.0, 5.0),
        "revenue_growth_yoy": _clip_series(revenue_growth_yoy, -2.0, 5.0),
        "gross_margin_delta": _clip_series(gross_margin_delta, -100, 100),
        "eps_acceleration": _clip_series(eps_acceleration, -2.0, 5.0),
        "debt_change": _clip_series(debt_change, -100, 100),
        "net_margin_delta": _clip_series(net_margin_delta, -100, 100),
        "days_since_announcement": _clip_series(days_since_ann, 0, 365),
        "reporting_season_flag": pd.Series(
            {code: season_flag for code in fina_df["code"].unique()},
            dtype=float,
        ),
    }

    for name, s in results.items():
        if not s.empty:
            logger.debug(f"  {name}: {len(s)}只, mean={s.mean():.4f}")

    return results
