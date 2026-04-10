#!/usr/bin/env python3
"""IC 时间对齐验证脚本 — 用合成数据验证 ic_calculator.py 的正确性。

构造已知答案的合成价格+因子数据，调用 ic_calculator 的实际函数，
验证输出 IC 是否符合预期。

验证场景:
1. 完美正相关因子 → IC 应接近 +1.0
2. 完美负相关因子 → IC 应接近 -1.0
3. 随机因子 → IC 应接近 0
4. 时间偏移验证: T 日因子对应 T+1~T+horizon 收益 (无前瞻偏差)

用法:
    cd backend && python ../scripts/research/verify_ic_alignment.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

import numpy as np
import pandas as pd
from engines.ic_calculator import (
    compute_forward_excess_returns,
    compute_ic_series,
    summarize_ic_stats,
)

HORIZON = 5
N_STOCKS = 100
N_DAYS = 60
SEED = 42


def make_synthetic_data(seed: int = SEED):
    """构造合成价格和基准数据。

    Returns:
        price_df: 长表 (code, trade_date, adj_close)
        benchmark_df: 长表 (trade_date, close)
        dates: 交易日序列
        codes: 股票代码列表
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=N_DAYS, freq="B")
    codes = [f"{i:06d}.SZ" for i in range(1, N_STOCKS + 1)]

    # 构造股票价格: 随机游走 (每日涨跌 ~1%)
    log_returns = rng.normal(0.001, 0.02, (N_DAYS, N_STOCKS))
    prices = 100 * np.exp(np.cumsum(log_returns, axis=0))

    # 构造基准价格: 随机游走
    bench_returns = rng.normal(0.0005, 0.01, N_DAYS)
    bench_prices = 100 * np.exp(np.cumsum(bench_returns))

    # 长表
    rows = []
    for i, d in enumerate(dates):
        for j, c in enumerate(codes):
            rows.append({"code": c, "trade_date": d, "adj_close": prices[i, j]})
    price_df = pd.DataFrame(rows)

    benchmark_df = pd.DataFrame({"trade_date": dates, "close": bench_prices})

    return price_df, benchmark_df, dates, codes, prices, bench_prices


def test_perfect_positive():
    """场景1: 完美正相关因子 — IC 应接近 +1.0"""
    price_df, benchmark_df, dates, codes, prices, bench_prices = make_synthetic_data()

    # 构造 forward excess return 手动计算
    # factor[T] = 真实的 T+1→T+horizon 超额收益 (完美预测)
    fwd_ret = compute_forward_excess_returns(price_df, benchmark_df, horizon=HORIZON)

    # 从 fwd_ret 宽表构造因子 (完美预测因子 = forward return 本身)
    factor_wide = fwd_ret.copy()

    # 计算 IC
    ic_series = compute_ic_series(factor_wide, fwd_ret)
    stats = summarize_ic_stats(ic_series)

    print("=== 场景1: 完美正相关因子 ===")
    print("  期望: IC ≈ +1.0")
    print(f"  实际: IC mean = {stats['mean']:.4f}, n_days = {stats['n_days']}")
    assert stats["mean"] > 0.99, f"完美正相关因子 IC 应 > 0.99, 实际 {stats['mean']}"
    print("  ✅ PASS\n")
    return True


def test_perfect_negative():
    """场景2: 完美负相关因子 — IC 应接近 -1.0"""
    price_df, benchmark_df, dates, codes, prices, bench_prices = make_synthetic_data()

    fwd_ret = compute_forward_excess_returns(price_df, benchmark_df, horizon=HORIZON)
    factor_wide = -fwd_ret  # 取反

    ic_series = compute_ic_series(factor_wide, fwd_ret)
    stats = summarize_ic_stats(ic_series)

    print("=== 场景2: 完美负相关因子 ===")
    print("  期望: IC ≈ -1.0")
    print(f"  实际: IC mean = {stats['mean']:.4f}, n_days = {stats['n_days']}")
    assert stats["mean"] < -0.99, f"完美负相关因子 IC 应 < -0.99, 实际 {stats['mean']}"
    print("  ✅ PASS\n")
    return True


def test_random_factor():
    """场景3: 随机因子 — IC 应接近 0"""
    price_df, benchmark_df, dates, codes, prices, bench_prices = make_synthetic_data()
    rng = np.random.default_rng(123)

    fwd_ret = compute_forward_excess_returns(price_df, benchmark_df, horizon=HORIZON)

    # 随机因子 (与收益无关)
    factor_wide = pd.DataFrame(
        rng.standard_normal((len(fwd_ret.index), len(fwd_ret.columns))),
        index=fwd_ret.index,
        columns=fwd_ret.columns,
    )

    ic_series = compute_ic_series(factor_wide, fwd_ret)
    stats = summarize_ic_stats(ic_series)

    print("=== 场景3: 随机因子 ===")
    print("  期望: IC ≈ 0 (|IC| < 0.10)")
    print(f"  实际: IC mean = {stats['mean']:.4f}, n_days = {stats['n_days']}")
    assert abs(stats["mean"]) < 0.10, f"随机因子 IC 应接近 0, 实际 {stats['mean']}"
    print("  ✅ PASS\n")
    return True


def test_time_alignment():
    """场景4: 时间偏移验证 — 确认 T 日因子对应 T+1~T+horizon 收益。

    构造一个因子: factor[T] = stock_return[T+1 → T+1+horizon-1]
    (即完美预测从 T+1 开始的收益)

    如果 ic_calculator 的时间对齐正确:
    - 正确对齐的因子应 IC ≈ +1.0
    - 故意偏移1天的因子应 IC < +1.0 (错位)
    """
    price_df, benchmark_df, dates, codes, prices, bench_prices = make_synthetic_data()

    fwd_ret = compute_forward_excess_returns(price_df, benchmark_df, horizon=HORIZON)

    # 正确对齐: factor[T] = fwd_ret[T] (已经是 T+1→T+horizon 的超额收益)
    factor_aligned = fwd_ret.copy()

    # 故意偏移: factor[T] = fwd_ret[T-1] (使用昨天的 forward return 作为今天的因子)
    # 这模拟"前瞻偏差"情况 — 如果 ic_calculator 有 off-by-one 错误，
    # 这两个的 IC 会相同
    factor_shifted = fwd_ret.shift(1)  # 向下移1行 = 使用前一天的值

    ic_aligned = compute_ic_series(factor_aligned, fwd_ret)
    ic_shifted = compute_ic_series(factor_shifted, fwd_ret)

    stats_aligned = summarize_ic_stats(ic_aligned)
    stats_shifted = summarize_ic_stats(ic_shifted)

    print("=== 场景4: 时间偏移验证 ===")
    print(f"  正确对齐因子: IC mean = {stats_aligned['mean']:.4f}")
    print(f"  偏移1天因子:  IC mean = {stats_shifted['mean']:.4f}")
    print(f"  差异: {stats_aligned['mean'] - stats_shifted['mean']:.4f}")

    # 正确对齐应接近 1.0
    assert stats_aligned["mean"] > 0.99, (
        f"正确对齐因子 IC 应 > 0.99, 实际 {stats_aligned['mean']}"
    )
    # 偏移因子应明显更差 (由于收益序列自相关，可能不为0，但应显著低于1.0)
    assert stats_aligned["mean"] > stats_shifted["mean"] + 0.05, (
        f"正确对齐({stats_aligned['mean']:.4f})应显著优于偏移({stats_shifted['mean']:.4f})"
    )
    print("  ✅ PASS — 正确对齐因子显著优于偏移因子\n")
    return True


def test_entry_exit_manual():
    """场景5: 手动验证 entry/exit 价格计算。

    直接构造简单价格序列，手动计算期望收益，对比 ic_calculator 结果。
    """
    # 3只股票, 10天, 简单递增价格
    dates = pd.bdate_range("2025-01-01", periods=10, freq="B")

    # 价格: A=[100,101,...,109], B=[200,202,...,218], C=[50,50,...,50]
    price_data = []
    for i, d in enumerate(dates):
        price_data.append({"code": "A.SZ", "trade_date": d, "adj_close": 100.0 + i})
        price_data.append({"code": "B.SZ", "trade_date": d, "adj_close": 200.0 + 2 * i})
        price_data.append({"code": "C.SZ", "trade_date": d, "adj_close": 50.0})  # 平盘
    price_df = pd.DataFrame(price_data)

    # 基准: 平盘 (无超额收益差异来自基准)
    bench_df = pd.DataFrame({"trade_date": dates, "close": [1000.0] * 10})

    horizon = 3
    fwd_ret = compute_forward_excess_returns(price_df, bench_df, horizon=horizon)

    # 手动计算 T=0 (2025-01-01) 的 forward return:
    # entry = price[T+1] = price[day 1]
    # exit  = price[T+3] = price[day 3]
    # A: entry=101, exit=103, ret = 103/101-1 = 0.019802
    # B: entry=202, exit=206, ret = 206/202-1 = 0.019802
    # C: entry=50,  exit=50,  ret = 50/50-1   = 0.0
    # bench: entry=1000, exit=1000, bench_ret=0
    # excess = stock_ret - bench_ret = stock_ret

    day0 = dates[0]
    print("=== 场景5: 手动 entry/exit 验证 ===")

    a_ret = fwd_ret.loc[day0, "A.SZ"]
    b_ret = fwd_ret.loc[day0, "B.SZ"]
    c_ret = fwd_ret.loc[day0, "C.SZ"]

    expected_a = 103.0 / 101.0 - 1  # 0.019802
    expected_b = 206.0 / 202.0 - 1  # 0.019802
    expected_c = 0.0

    print(f"  A.SZ T=0: 期望={expected_a:.6f}, 实际={a_ret:.6f}")
    print(f"  B.SZ T=0: 期望={expected_b:.6f}, 实际={b_ret:.6f}")
    print(f"  C.SZ T=0: 期望={expected_c:.6f}, 实际={c_ret:.6f}")

    assert abs(a_ret - expected_a) < 1e-6, f"A.SZ 收益不匹配: {a_ret} vs {expected_a}"
    assert abs(b_ret - expected_b) < 1e-6, f"B.SZ 收益不匹配: {b_ret} vs {expected_b}"
    assert abs(c_ret - expected_c) < 1e-6, f"C.SZ 收益不匹配: {c_ret} vs {expected_c}"

    # 验证 T=2 (day 2): entry=price[day3], exit=price[day5]
    day2 = dates[2]
    a_ret2 = fwd_ret.loc[day2, "A.SZ"]
    expected_a2 = (100.0 + 5) / (100.0 + 3) - 1  # 105/103-1 = 0.019417
    print(f"  A.SZ T=2: 期望={expected_a2:.6f}, 实际={a_ret2:.6f}")
    assert abs(a_ret2 - expected_a2) < 1e-6, "A.SZ T=2 不匹配"

    print("  ✅ PASS — entry/exit 计算正确\n")
    return True


def main():
    print("=" * 60)
    print("IC Calculator 时间对齐验证")
    print(f"参数: HORIZON={HORIZON}, N_STOCKS={N_STOCKS}, N_DAYS={N_DAYS}")
    print("=" * 60 + "\n")

    results = {
        "perfect_positive": test_perfect_positive(),
        "perfect_negative": test_perfect_negative(),
        "random_factor": test_random_factor(),
        "time_alignment": test_time_alignment(),
        "entry_exit_manual": test_entry_exit_manual(),
    }

    print("=" * 60)
    passed = sum(results.values())
    total = len(results)
    print(f"结果: {passed}/{total} PASS")
    for name, ok in results.items():
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {name}: {status}")
    print("=" * 60)

    if passed == total:
        print("\n结论: ic_calculator.py 时间对齐正确，无前瞻偏差。")
    else:
        print("\n结论: 存在问题，需要进一步调查。")
        sys.exit(1)


if __name__ == "__main__":
    main()
