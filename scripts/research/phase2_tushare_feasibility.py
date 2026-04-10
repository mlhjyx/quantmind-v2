#!/usr/bin/env python3
"""Phase 2 前置调研: Tushare API 可行性测试 (2.2/2.8/2.9/2.10/2.11)。

只做API可用性探测，不改任何生产代码/表。
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import tushare as ts
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / "backend" / ".env")
token = os.environ.get("TUSHARE_TOKEN", "")
ts.set_token(token)
pro = ts.pro_api()

SLEEP = 0.3
TEST_STOCKS = [
    ("600519.SH", "贵州茅台", "大盘"),
    ("002415.SZ", "海康威视", "中盘"),
    ("300750.SZ", "宁德时代", "大盘"),
    ("002049.SZ", "紫光国微", "中盘"),
    ("300782.SZ", "卓胜微", "小盘"),
]


def safe_call(func, **kwargs):
    """安全调用Tushare API。"""
    try:
        time.sleep(SLEEP)
        df = func(**kwargs)
        return df
    except Exception as e:
        return f"ERROR: {e}"


def test_22_analyst():
    """2.2 分析师预期"""
    print("=" * 60)
    print("=== 2.2 分析师预期 ===")
    print("=" * 60)

    # report_rc 研报评级
    print("\n--- report_rc (研报评级) ---")
    for code, name, cap in TEST_STOCKS:
        df = safe_call(pro.report_rc, ts_code=code)
        if isinstance(df, str):
            print(f"  {code} {name}({cap}): {df}")
        else:
            print(
                f"  {code} {name}({cap}): {len(df)} rows, "
                f"date range: {df['report_date'].min() if len(df) > 0 else 'N/A'}~"
                f"{df['report_date'].max() if len(df) > 0 else 'N/A'}"
            )
            if len(df) > 0 and hasattr(df, "columns"):
                print(f"    columns: {list(df.columns)}")

    # forecast 业绩预告
    print("\n--- forecast (业绩预告) ---")
    for code, name, cap in TEST_STOCKS[:3]:
        df = safe_call(pro.forecast, ts_code=code)
        if isinstance(df, str):
            print(f"  {code} {name}({cap}): {df}")
        else:
            print(f"  {code} {name}({cap}): {len(df)} rows")
            if len(df) > 0:
                print(f"    columns: {list(df.columns)}")
                print(f"    date range: {df['ann_date'].min()}~{df['ann_date'].max()}")

    # express 业绩快报
    print("\n--- express (业绩快报) ---")
    for code, name, cap in TEST_STOCKS[:3]:
        df = safe_call(pro.express, ts_code=code)
        if isinstance(df, str):
            print(f"  {code} {name}({cap}): {df}")
        else:
            print(f"  {code} {name}({cap}): {len(df)} rows")
            if len(df) > 0:
                print(f"    columns: {list(df.columns)}")


def test_28_dragon_tiger():
    """2.8 龙虎榜"""
    print("\n" + "=" * 60)
    print("=== 2.8 龙虎榜 ===")
    print("=" * 60)

    # top_list
    print("\n--- top_list ---")
    for dt in ["20250630", "20250627", "20250625"]:
        df = safe_call(pro.top_list, trade_date=dt)
        if isinstance(df, str):
            print(f"  {dt}: {df}")
        else:
            print(
                f"  {dt}: {len(df)} rows, unique stocks: "
                f"{df['ts_code'].nunique() if len(df) > 0 else 0}"
            )
            if len(df) > 0:
                print(f"    columns: {list(df.columns)}")

    # top_inst
    print("\n--- top_inst (机构明细) ---")
    df = safe_call(pro.top_inst, trade_date="20250627")
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}")
        if len(df) > 0:
            print(f"  columns: {list(df.columns)}")
            if "side" in df.columns:
                print(f"  side distribution: {df['side'].value_counts().to_dict()}")
            if "exalter" in df.columns:
                print(f"  sample seats: {df['exalter'].head(5).tolist()}")


def test_29_events():
    """2.9 解禁/增减持/质押/回购"""
    print("\n" + "=" * 60)
    print("=== 2.9 解禁/增减持/质押/回购 ===")
    print("=" * 60)

    # share_float 解禁
    print("\n--- share_float (限售解禁) ---")
    df = safe_call(pro.share_float, ts_code="600519.SH")
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}, columns: {list(df.columns)}")
        if len(df) > 0:
            date_cols = [c for c in df.columns if "date" in c.lower()]
            print(f"  date columns: {date_cols}")
            print(f"  sample:\n{df.head(3).to_string()}")

    # stk_holdertrade 增减持
    print("\n--- stk_holdertrade (股东增减持) ---")
    df = safe_call(pro.stk_holdertrade, ts_code="600519.SH")
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}, columns: {list(df.columns)}")
        if len(df) > 0:
            date_cols = [c for c in df.columns if "date" in c.lower()]
            print(f"  date columns (PIT check): {date_cols}")

    # pledge_stat 质押
    print("\n--- pledge_stat (股权质押) ---")
    df = safe_call(pro.pledge_stat, ts_code="600519.SH")
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}, columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"  sample:\n{df.head(3).to_string()}")

    # repurchase 回购
    print("\n--- repurchase (股票回购) ---")
    df = safe_call(pro.repurchase, ann_date="20250627")
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}, columns: {list(df.columns)}")
        if len(df) > 0:
            print(f"  sample:\n{df.head(3).to_string()}")


def test_210_broker():
    """2.10 券商金股"""
    print("\n" + "=" * 60)
    print("=== 2.10 券商金股 ===")
    print("=" * 60)

    for month in ["202506", "202505", "202504"]:
        df = safe_call(pro.broker_recommend, month=month)
        if isinstance(df, str):
            print(f"  {month}: {df}")
        else:
            print(
                f"  {month}: {len(df)} rows, unique stocks: "
                f"{df['ts_code'].nunique() if len(df) > 0 and 'ts_code' in df.columns else 'N/A'}"
            )
            if len(df) > 0:
                print(f"    columns: {list(df.columns)}")


def test_211_factors():
    """2.11 Tushare预计算量化因子"""
    print("\n" + "=" * 60)
    print("=== 2.11 Tushare量化因子 ===")
    print("=" * 60)

    # stk_factor
    print("\n--- stk_factor ---")
    df = safe_call(pro.stk_factor, ts_code="600519.SH", start_date="20250101", end_date="20250630")
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}")
        if len(df) > 0:
            print(f"  ALL columns ({len(df.columns)}): {list(df.columns)}")

    # stk_factor_pro
    print("\n--- stk_factor_pro ---")
    df = safe_call(
        pro.stk_factor_pro, ts_code="600519.SH", start_date="20250101", end_date="20250630"
    )
    if isinstance(df, str):
        print(f"  {df}")
    else:
        print(f"  rows: {len(df)}")
        if len(df) > 0:
            print(f"  ALL columns ({len(df.columns)}): {list(df.columns)}")

    # Compare with QuantMind
    qm_factors = [
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
        "momentum_5",
        "momentum_10",
        "momentum_20",
        "kbar_kmid",
        "kbar_ksft",
        "ivol_20",
        "beta_market_20",
        "maxret_20",
        "stoch_rsv_20",
        "ln_market_cap",
        "ep_ratio",
        "dv_ttm",
    ]
    print(f"\n  QuantMind existing factors: {len(qm_factors)}")
    if not isinstance(df, str) and len(df) > 0:
        ts_cols = set(df.columns) - {"ts_code", "trade_date"}
        print(f"  Tushare factor columns: {len(ts_cols)}")
        # Potential overlaps by keyword
        overlap_hints = []
        for tc in sorted(ts_cols):
            for qf in qm_factors:
                if any(
                    kw in tc.lower()
                    for kw in [
                        "macd",
                        "kdj",
                        "rsi",
                        "cci",
                        "boll",
                        "bias",
                        "wr",
                        "psy",
                        "dma",
                        "trix",
                        "vr",
                    ]
                ):
                    overlap_hints.append(tc)
                    break
        print(f"  Technical indicator columns (MACD/KDJ/RSI etc.): {sorted(set(overlap_hints))}")
        new_cols = sorted(ts_cols - set(overlap_hints))
        print(f"  Potentially new/useful columns: {new_cols}")


if __name__ == "__main__":
    print("Phase 2 Tushare API Feasibility Study")
    print(f"Token: ...{token[-8:]}")
    print()

    test_22_analyst()
    test_28_dragon_tiger()
    test_29_events()
    test_210_broker()
    test_211_factors()

    print("\n" + "=" * 60)
    print("=== DONE ===")
