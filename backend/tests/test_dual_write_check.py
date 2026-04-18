"""Unit tests for scripts/dual_write_check.py compare() + tolerance.

2026-04-18 Session 6 新增: backfill 诊断发现 3 类 drift 后, 加
- per-col tolerance (volume ±100 股 / amount ±10 元 / 价格列 1e-6)
- historical_gap_filled (老 NaN 新有值, feature 非 bug — e.g. BJ 股 up/down_limit 304 行)
- codes_only_in_new ≤ 50 accepted (MVP 2.1b L173 FK 过滤噪音)
- only_new_nan (新路径丢值) 保持 FAIL

铁律 10b 生产入口守门 + 铁律 40 测试债不增长.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest  # noqa: F401

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dual_write_check as dw  # noqa: E402


def _make_frame(
    codes: list[str],
    trade_date: date = date(2026, 4, 16),
    overrides: dict | None = None,
) -> pd.DataFrame:
    """Build minimal klines DataFrame with _COMPARE_COLS baseline values."""
    n = len(codes)
    base = {
        "code": codes,
        "trade_date": [trade_date] * n,
        "open": [10.0] * n,
        "high": [11.0] * n,
        "low": [9.5] * n,
        "close": [10.5] * n,
        "pre_close": [10.0] * n,
        "change": [0.5] * n,
        "pct_change": [5.0] * n,
        "volume": [100000] * n,
        "amount": [1050000.0] * n,
        "adj_factor": [1.0] * n,
        "up_limit": [11.0] * n,
        "down_limit": [9.0] * n,
    }
    df = pd.DataFrame(base)
    if overrides:
        for k, v in overrides.items():
            df[k] = v
    return df


def test_compare_all_match_returns_pass():
    codes = [f"00000{i}.SZ" for i in range(10)]
    old = _make_frame(codes)
    new = _make_frame(codes)
    r = dw.compare(old, new)
    assert r["status"] == "PASS"
    assert r["codes_only_in_new"] == 0
    assert r["codes_only_in_old"] == 0
    assert r["all_columns_match"] is True


def test_compare_historical_gap_filled_is_feature_not_bug():
    """老 DB NaN, 新路径有值 (e.g. BJ 股 up/down_limit) → PASS."""
    codes = [f"00000{i}.SZ" for i in range(10)]
    old = _make_frame(codes)
    old.loc[:5, "up_limit"] = None
    old.loc[:5, "down_limit"] = None
    new = _make_frame(codes)
    r = dw.compare(old, new)
    assert r["status"] == "PASS", "historical_gap_filled 应接受"
    assert r["columns"]["up_limit"]["historical_gap_filled"] == 6
    assert r["columns"]["up_limit"]["only_new_nan"] == 0
    assert r["columns"]["up_limit"]["match"] is True


def test_compare_only_new_nan_is_real_bug():
    """新路径丢值 (老有, 新 NaN) → FAIL."""
    codes = [f"00000{i}.SZ" for i in range(10)]
    old = _make_frame(codes)
    new = _make_frame(codes)
    new.loc[:5, "close"] = None  # 新路径丢 close
    r = dw.compare(old, new)
    assert r["status"] == "FAIL"
    assert r["columns"]["close"]["only_new_nan"] == 6
    assert r["columns"]["close"]["match"] is False


def test_compare_codes_only_in_new_within_tolerance_pass():
    """新路径多 ≤ 50 code (MVP 2.1b L173 FK 过滤噪音) → PASS."""
    common = [f"00000{i}.SZ" for i in range(100)]
    extra = [f"99999{i}.SZ" for i in range(30)]  # 30 ≤ 50
    old = _make_frame(common)
    new = _make_frame(common + extra)
    r = dw.compare(old, new)
    assert r["status"] == "PASS"
    assert r["codes_only_in_new"] == 30
    assert r["row_count_acceptable"] is True


def test_compare_codes_only_in_new_exceeds_tolerance_fail():
    """新路径多 > 50 code → FAIL (真 drift)."""
    common = [f"00000{i}.SZ" for i in range(100)]
    extra = [f"99999{i}.SZ" for i in range(60)]  # 60 > 50
    old = _make_frame(common)
    new = _make_frame(common + extra)
    r = dw.compare(old, new)
    assert r["status"] == "FAIL"
    assert r["row_count_acceptable"] is False


def test_compare_volume_within_tolerance_100_shares_pass():
    """Volume ±100 股 = ±1 手 (Tushare API 历史微调) → PASS."""
    codes = [f"00000{i}.SZ" for i in range(200)]
    old = _make_frame(codes)
    new = _make_frame(codes)
    # 1 行 volume 差 1 (整数差 Tushare 微调)
    new.loc[0, "volume"] = old.loc[0, "volume"] - 1
    r = dw.compare(old, new)
    assert r["status"] == "PASS"
    assert r["columns"]["volume"]["match"] is True
    assert r["columns"]["volume"]["max_diff"] == 1.0


def test_compare_volume_diff_exceeds_tolerance_fail():
    """Volume 差 > 100 股 (1 手) → FAIL."""
    codes = [f"00000{i}.SZ" for i in range(200)]
    old = _make_frame(codes)
    new = _make_frame(codes)
    new.loc[0, "volume"] = old.loc[0, "volume"] - 200  # > 100
    r = dw.compare(old, new)
    assert r["status"] == "FAIL"
    assert r["columns"]["volume"]["match"] is False


def test_compare_amount_within_tolerance_10_yuan_pass():
    """Amount ±10 元 (Tushare 精度遗留 2026-04-08 前) → PASS."""
    codes = [f"00000{i}.SZ" for i in range(200)]
    old = _make_frame(codes)
    new = _make_frame(codes)
    # 多数行 amount 差 5 元 (老 Tushare 精度历史差)
    new.loc[:30, "amount"] = old.loc[:30, "amount"] - 5.0
    r = dw.compare(old, new)
    assert r["status"] == "PASS"
    assert r["columns"]["amount"]["match"] is True


def test_compare_close_zero_tolerance_fail():
    """Close 价格列 0 容忍, 任何 diff → FAIL."""
    codes = [f"00000{i}.SZ" for i in range(100)]
    old = _make_frame(codes)
    new = _make_frame(codes)
    new.loc[0, "close"] = old.loc[0, "close"] + 0.01  # 1 分差, 超 1e-6
    r = dw.compare(old, new)
    assert r["status"] == "FAIL", "价格列不允许 drift"


def test_compare_empty_returns_error():
    """双方一侧空 → ERROR (非交易日 pattern)."""
    empty = _make_frame([])
    one = _make_frame(["000001.SZ"])
    r = dw.compare(empty, one)
    assert r["status"] == "ERROR"
    assert r["error"] == "one_side_empty"


def test_tolerance_constants_sane_values():
    """per-col tolerance + noise tolerance 设计值不漂."""
    assert dw.MAX_NEW_EXTRA_CODES == 50
    assert dw._COL_TOLERANCE["close"] == 1e-6
    assert dw._COL_TOLERANCE["volume"] == 100.0
    assert dw._COL_TOLERANCE["amount"] == 10.0
    assert dw._MISMATCH_RATIO_LIMIT == 0.01
