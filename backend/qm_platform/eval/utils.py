"""Framework #4 Eval — 共享 helper.

paired_bootstrap_pvalue: 单边 paired bootstrap p 值, MVP 3.5 G3 / Strategy G1' 共用.

实施时机:
  - MVP 3.5 batch 1: 新建 (替原研究脚本散落实现)
  - 后续 Strategy Eval Gate (批 3) 复用
"""
from __future__ import annotations

import numpy as np

DEFAULT_BOOTSTRAP_ITER = 1000
"""默认 bootstrap 重抽样次数. 1000 足够 p<0.05 显著性区分."""

MIN_SAMPLE_SIZE = 30
"""最少样本数. 低于此返 None (样本不足判 p)."""


def paired_bootstrap_pvalue(
    candidate: np.ndarray,
    baseline: np.ndarray,
    n_iter: int = DEFAULT_BOOTSTRAP_ITER,
    rng_seed: int | None = None,
) -> float | None:
    """单边 paired bootstrap p 值 — 检验 candidate.mean() > baseline.mean().

    实现:
      1. 计算 diff = candidate - baseline (对齐, 同长度必须)
      2. 从 diff 中有放回抽样 n_iter 次, 每次 mean 得 boot_means
      3. p = (boot_means <= 0).mean()  # 单边: 反证 H0 candidate ≤ baseline

    Args:
      candidate: 候选样本 (e.g. 因子 IC 序列 / 策略 daily return).
      baseline: 基线样本 (同长度对齐).
      n_iter: 重抽样次数, 默认 1000.
      rng_seed: 随机种子, 用于复现.

    Returns:
      float [0, 1] 单边 p 值, candidate 越优 p 越小.
      None 若样本不足或长度不匹配 (调用方应 fail-soft).

    Raises:
      ValueError: n_iter < 100 (统计不稳).

    References:
      Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns"
      Politis, Romano (1994) "The stationary bootstrap"
    """
    if n_iter < 100:
        raise ValueError(f"n_iter 必须 ≥ 100 (得 {n_iter}), 否则 p 值不稳")

    cand = np.asarray(candidate, dtype=np.float64)
    base = np.asarray(baseline, dtype=np.float64)

    if cand.shape != base.shape:
        return None
    if cand.size < MIN_SAMPLE_SIZE:
        return None

    diff = cand - base
    finite_mask = np.isfinite(diff)
    if finite_mask.sum() < MIN_SAMPLE_SIZE:
        return None
    diff = diff[finite_mask]

    # 向量化 bootstrap (PR #123 reviewer P2): rng.integers 一次抽 (n_iter, n) 矩阵,
    # diff[idx].mean(axis=1) 一次得 n_iter 个 boot 均值, ~50-100x 快于 Python loop.
    rng = np.random.default_rng(rng_seed)
    n = diff.size
    idx = rng.integers(0, n, size=(n_iter, n))
    boot_means = diff[idx].mean(axis=1)

    return float((boot_means <= 0.0).mean())


_T_STAT_STD_EPSILON: float = 1e-12
"""std 小于此值视为常数序列, t 统计量未定义返 None.

注意: numpy `arr.std(ddof=1)` 对常数序列返回 ~6.97e-19 (浮点噪声),
而非精确 0, 因此 `std <= 0.0` 不足以拦截. 用 epsilon 裕量.
"""


def t_statistic(values: np.ndarray) -> float | None:
    """单样本 t 统计量 — H0: mean = 0.

    Returns:
      t = mean / (std / sqrt(n)), None 若样本不足 / std 近 0 / 非 finite.
    """
    arr = np.asarray(values, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    n = finite.size
    if n < MIN_SAMPLE_SIZE:
        return None
    std = finite.std(ddof=1)
    if std < _T_STAT_STD_EPSILON or not np.isfinite(std):
        return None
    return float(finite.mean() / (std / np.sqrt(n)))


def benjamini_hochberg_threshold(
    p_value: float,
    rank: int,
    m: int,
    fdr: float = 0.05,
) -> bool:
    """Benjamini-Hochberg FDR 校正判定单个 p 值是否通过.

    Rejection condition: p ≤ rank/m × fdr.

    Args:
      p_value: 待检验 p.
      rank: 在 m 个测试中的升序排名 (1-indexed, 最小 p 排 1).
      m: 累积测试总数 (从 FACTOR_TEST_REGISTRY 读).
      fdr: False Discovery Rate, 默认 0.05.

    Returns:
      True 若 p 通过 BH-FDR (通常 reject H0, 即因子有效).

    Raises:
      ValueError: rank > m or rank < 1.
    """
    if rank < 1 or rank > m:
        raise ValueError(f"rank 必须在 [1, m={m}], 得 {rank}")
    if not (0.0 < fdr < 1.0):
        raise ValueError(f"fdr 必须在 (0, 1), 得 {fdr}")
    threshold = (rank / m) * fdr
    return p_value <= threshold
