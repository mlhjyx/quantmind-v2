"""Shared market-indicator DB queries — V3 §14 mode 9 千股跌停极端 regime feed (HC-2b3 G4).

本 module = Application-layer query helper (铁律 34 single source of truth). 两 caller
共用本 module 的查询, 反 limit_down_count / index_return 跨模块 SQL 重复 → 阈值/口径漂移:
  - app/tasks/dynamic_threshold_tasks._build_market_indicators (L3 阈值评估 feed)
  - app/services/risk/meta_monitor_service._collect_market_crisis (元告警 Crisis 检测)

查询 fail-loud — psycopg2.Error propagate, caller 决定 fail-soft 策略 (铁律 33):
  - meta_monitor collector: 让 psycopg2.Error propagate (沿用 _collect_litellm 体例)
  - dynamic_threshold task: caller 自行 try/except fail-soft to None (沿用
    _fetch_latest_regime 体例 — defaults to CALM)

"无数据" (index_daily 无 000300.SH row / klines_daily 空) → 返回 None (NOT error)
— None 是合法 runtime state (no signal), 区别于 query 失败 (fail-loud propagate).

注: query_index_return 与 query_limit_down_count 各自独立锚定 MAX(trade_date)
(index_daily vs klines_daily) — index feed 落后 stock feed 一天时, 同一
MarketCrisisSnapshot 的两 leg 可能跨交易日边界. 5min cadence + rule OR 语义下
影响可忽略 (任一 leg 命中即触发), 不强制对齐 (反 over-engineering).

铁律 31 sustained: 本 module 仅 DB read (无 commit, caller owns transaction).
"""

from __future__ import annotations

from typing import Any

# 沪深 300 — 大盘 proxy (沿用 dynamic_threshold_tasks._build_market_indicators docstring
# line 98 + DefaultIndicatorsProvider 体例).
_INDEX_CODE_CSI300: str = "000300.SH"

# 跌停 pct_change 阈值: A 股主板 -10% 跌停; klines_daily.pct_change 单位为 % (已乘100,
# DDL comment "5.06=涨5.06%"). <= -9.9 容忍 ST / 科创 / 创业板不同涨跌幅 + 浮点边界
# (沿用 dynamic_threshold_tasks docstring line 100).
_LIMIT_DOWN_PCT_CHANGE: float = -9.9


def query_limit_down_count(conn: Any) -> int | None:
    """全市场最新交易日跌停家数 (V3 §14 mode 9 leg — klines_daily).

    跌停家数 = 最新交易日 非停牌 且 pct_change <= -9.9 的股票数.
    - `is_suspended = FALSE`: 停牌股 pct_change 可能 stale / carried-over, 不可信
      (沿用 scripts/validate_data.sql pct_change 极值判定 convention).
    - `HAVING COUNT(*) > 0`: 空表 (klines_daily 无任何 row → MAX(trade_date) NULL
      → WHERE 0 match) → 0 行返回 → None (无信号), 区别于真实交易日的 "0 跌停"
      (与 query_index_return 的 None-on-no-data 语义对齐, 反 空表/calm-day 混淆).

    Args:
        conn: psycopg2 connection (read-only; caller owns transaction).

    Returns:
        跌停家数 (int >= 0). None when klines_daily 空 (无信号).

    Raises:
        psycopg2.Error: query failure — fail-loud propagate (铁律 33).
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE pct_change <= %s)
            FROM klines_daily
            WHERE trade_date = (SELECT MAX(trade_date) FROM klines_daily)
              AND is_suspended = FALSE
            HAVING COUNT(*) > 0
            """,
            (_LIMIT_DOWN_PCT_CHANGE,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    return int(row[0]) if row and row[0] is not None else None


def query_index_return(conn: Any) -> float | None:
    """沪深 300 最新交易日 return as fraction (V3 §14 mode 9 leg — index_daily).

    SELECT pct_change FROM index_daily WHERE index_code='000300.SH' ORDER BY
    trade_date DESC LIMIT 1 → /100 (index_daily.pct_change 单位 % per DDL comment;
    转 fraction 对齐 MarketIndicators.index_return / assess_market_state 约定,
    e.g. pct_change -7.0 → index_return -0.07).

    Args:
        conn: psycopg2 connection (read-only; caller owns transaction).

    Returns:
        大盘当日 return as fraction (e.g. -0.07). None when index_daily 无
        000300.SH row OR 该 row 的 pct_change IS NULL (无信号, 非 error).

    Raises:
        psycopg2.Error: query failure — fail-loud propagate (铁律 33).
    """
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT pct_change
            FROM index_daily
            WHERE index_code = %s
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (_INDEX_CODE_CSI300,),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if row is None or row[0] is None:
        return None
    return float(row[0]) / 100.0


__all__ = ["query_index_return", "query_limit_down_count"]
