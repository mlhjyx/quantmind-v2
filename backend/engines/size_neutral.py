"""Partial Size-Neutral 调整模块。

Step 6-H: 将 Step 6-G 验证通过的 outer wrapper 提升为 inner 实现。
公式: adj_score = score - beta * zscore(ln_mcap)
beta=0.0 时为 no-op（完全向后兼容）。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


def load_ln_mcap_pivot(
    start_date: date,
    end_date: date,
    conn=None,
) -> pd.DataFrame:
    """从 factor_values 加载 ln_market_cap，返回 pivot 宽表。

    Args:
        start_date: 起始日期。
        end_date: 结束日期。
        conn: psycopg2 连接。为 None 时自动创建并关闭。

    Returns:
        DataFrame, index=trade_date, columns=code, values=neutral_value(ln_mcap)。
    """
    own_conn = False
    if conn is None:
        from app.services.db import get_sync_conn

        conn = get_sync_conn()
        own_conn = True

    try:
        df = pd.read_sql(
            """SELECT code, trade_date, neutral_value AS ln_mcap
               FROM factor_values
               WHERE factor_name = 'ln_market_cap'
                 AND neutral_value IS NOT NULL
                 AND trade_date >= %(start)s
                 AND trade_date <= %(end)s""",
            conn,
            params={"start": start_date, "end": end_date},
        )
    finally:
        if own_conn:
            conn.close()

    if df.empty:
        logger.warning("load_ln_mcap_pivot: 无数据", start=start_date, end=end_date)
        return pd.DataFrame()

    pivot = df.pivot_table(
        index="trade_date", columns="code", values="ln_mcap", aggfunc="first"
    ).sort_index()
    logger.info(
        "load_ln_mcap_pivot: %d dates x %d codes", pivot.shape[0], pivot.shape[1]
    )
    return pivot


def load_ln_mcap_for_date(trade_date: date, conn) -> pd.Series | None:
    """加载单日 ln_market_cap（PT 信号生成轻量路径）。

    Args:
        trade_date: 目标日期。
        conn: psycopg2 连接。

    Returns:
        Series (code -> ln_mcap)，无数据时返回 None。
    """
    import psycopg2.extras

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT code, neutral_value AS ln_mcap
           FROM factor_values
           WHERE factor_name = 'ln_market_cap'
             AND neutral_value IS NOT NULL
             AND trade_date = %(td)s""",
        {"td": trade_date},
    )
    rows = cur.fetchall()
    cur.close()
    if not rows:
        return None
    return pd.Series(
        {r["code"]: r["ln_mcap"] for r in rows}, dtype=np.float64, name="ln_mcap"
    )


def apply_size_neutral(
    scores: pd.Series,
    ln_mcap_row: pd.Series,
    beta: float,
) -> pd.Series:
    """对 composite scores 施加 partial size-neutral 调整。

    公式: adj_score = score - beta * zscore(ln_mcap)

    Args:
        scores: SignalComposer.compose() 输出 (code -> score, 降序)。
        ln_mcap_row: 同日 ln_market_cap (code -> ln_mcap)。
        beta: 中性化强度 (0.0=关闭, 0.50=Step 6-G 最优)。

    Returns:
        调整后的 scores，降序排列（与 compose() 输出格式一致）。
    """
    if beta <= 0.0:
        return scores

    df = pd.DataFrame(
        {
            "score": scores,
            "ln_mcap": ln_mcap_row.reindex(scores.index),
        }
    ).dropna()

    if df.empty:
        return scores

    mv_std = df["ln_mcap"].std()
    if mv_std > 0:
        df["ln_mcap_z"] = (df["ln_mcap"] - df["ln_mcap"].mean()) / mv_std
    else:
        df["ln_mcap_z"] = 0.0

    df["adj_score"] = df["score"] - beta * df["ln_mcap_z"]
    return df["adj_score"].sort_values(ascending=False, kind="mergesort")
