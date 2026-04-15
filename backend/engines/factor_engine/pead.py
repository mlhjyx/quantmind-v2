"""Factor engine — PEAD (Post-Earnings Announcement Drift) pure function.

Phase C C2 (2026-04-16) 从原 `calc_pead_q1(trade_date, conn=None)` 拆出的纯计算部分.
DB 读取部分搬到 `backend/app/services/factor_repository.py::load_pead_announcements`.

Pure function — 输入 DataFrame (公告行), 输出 pd.Series. 无 IO, 可单测.

设计:
    原 `calc_pead_q1` 同时做 DB 查询 + 同股去重聚合. 这违反 铁律 31 (Engine 纯计算).
    C2 拆分: DB 查询归 Repository, 去重聚合归本模块 pure 函数, 两者通过 __init__.py
    的兼容层 wrapper 组合成原有的 `calc_pead_q1(trade_date, conn=None)` API.

见: docs/audit/PHASE_C_F31_PREP.md §Milestones C2
"""

from __future__ import annotations

import pandas as pd


def calc_pead_q1_from_announcements(ann_df: pd.DataFrame) -> pd.Series:
    """PEAD Q1 因子的纯计算部分 — 从公告 DataFrame 构建 factor Series.

    输入 DataFrame 要求:
        - 列: ['ts_code', 'eps_surprise_pct', 'ann_td']
        - 同一 ts_code 可能有多行, **必须按 (ts_code, ann_td DESC) 排序**
          (factor_repository.load_pead_announcements 保证此顺序)
        - 空 DataFrame 返回空 Series

    计算逻辑:
        1. 同一股票取最近一条公告 (DataFrame 已排序, 取 first)
        2. surprise 转 float 构成 Series
        3. 命名 "pead_q1"

    Args:
        ann_df: PEAD 公告 DataFrame (见 factor_repository.load_pead_announcements)

    Returns:
        pd.Series: index=code (ts_code), values=eps_surprise_pct (float), name='pead_q1'
    """
    if ann_df.empty:
        return pd.Series(dtype=float, name="pead_q1")

    # 同一股票取最近一条 (输入已按 (ts_code, ann_td DESC) 排序)
    seen: set[str] = set()
    data: dict[str, float] = {}
    for ts_code, surprise, _ann_td in ann_df[["ts_code", "eps_surprise_pct", "ann_td"]].itertuples(
        index=False, name=None
    ):
        code = ts_code  # 统一带后缀格式
        if code not in seen:
            data[code] = float(surprise)
            seen.add(code)

    return pd.Series(data, name="pead_q1")
