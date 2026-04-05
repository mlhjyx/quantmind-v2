"""Probability of Backtest Overfitting (PBO) — CSCV方法。

Bailey, Borwein, Lopez de Prado & Zhu (2017) 提出的CSCV
(Combinatorially Symmetric Cross-Validation) 方法,
用于检测回测过拟合概率。

核心思想:
  将收益矩阵的时间维度分成S个等长子集,
  穷举所有C(S, S/2)种train/test分割(组合对称),
  对每种分割:
    1. 在train集上找表现最优的策略/配置
    2. 计算该策略在test集上的表现排名
    3. 用logit变换度量OOS排名的相对位置
  PBO = P(logit <= 0), 即IS最优策略在OOS表现低于中位数的概率。

解读:
  PBO < 0.3: 低过拟合风险
  PBO 0.3-0.6: 中等风险
  PBO > 0.6: 高过拟合风险

参考: DEV_BACKTEST_ENGINE.md §4.12.2, Bailey et al. (2017)
遵循CLAUDE.md: 类型注解 + Google style docstring(中文)
"""

from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray,
    n_partitions: int = 16,
) -> dict:
    """计算回测过拟合概率(PBO)。

    CSCV方法: 将时间序列分成S个子集,
    穷举所有C(S, S/2)种train/test分割,
    统计IS最优策略在OOS表现排名的分布。

    算法步骤:
      1. 将T个时间点均匀分成S个子集(block)
      2. 穷举所有C(S, S/2)种方式选S/2个block作为train, 剩余为test
      3. 对每种分割:
         a. 计算每个策略在train集的Sharpe(或累计收益)
         b. 找到train集表现最优的策略 n*
         c. 计算n*在test集的表现排名 rank_n*
         d. 计算logit: log(rank_n* / (N - rank_n*))
            其中rank从0开始, N为策略总数
      4. PBO = 在所有组合中logit <= 0的比例

    Args:
        returns_matrix: 收益矩阵, shape=(N, T)。
            N=策略/配置数量, T=时间点数量。
            每行是一个策略的时间序列收益率。
        n_partitions: CSCV分区数S, 必须是偶数且>=4。
            S越大精度越高但组合数C(S,S/2)指数增长。
            推荐: 8-16, 最大不超过20(C(20,10)=184756)。

    Returns:
        字典包含:
          - "pbo": float, 过拟合概率, 范围[0,1], >0.5说明过拟合。
          - "logit_distribution": list[float], 每种组合的logit值。
          - "n_combinations": int, 总组合数。
          - "n_partitions": int, 实际使用的分区数。
          - "n_strategies": int, 策略数量。
          - "n_timepoints": int, 时间点数量。

    Raises:
        ValueError: 输入参数不合法。

    Examples:
        >>> rng = np.random.default_rng(42)
        >>> returns = rng.normal(0, 0.01, size=(10, 500))
        >>> result = probability_of_backtest_overfitting(returns, n_partitions=8)
        >>> 0 <= result["pbo"] <= 1
        True
    """
    # ── 参数校验 ──
    if returns_matrix.ndim != 2:
        raise ValueError(
            f"returns_matrix必须是2D数组(N策略×T时间), 收到{returns_matrix.ndim}D"
        )

    n_strategies, n_timepoints = returns_matrix.shape

    if n_strategies < 2:
        raise ValueError(
            f"至少需要2个策略/配置才能计算PBO, 收到{n_strategies}"
        )
    if n_timepoints < n_partitions:
        raise ValueError(
            f"时间点数({n_timepoints})必须>=分区数({n_partitions})"
        )
    if n_partitions < 4:
        raise ValueError(f"n_partitions必须>=4, 收到{n_partitions}")
    if n_partitions % 2 != 0:
        raise ValueError(f"n_partitions必须是偶数, 收到{n_partitions}")

    # 组合数上限保护: C(20,10)=184756
    max_partitions = 20
    if n_partitions > max_partitions:
        logger.warning(
            "n_partitions=%d 超过上限%d, 已截断",
            n_partitions, max_partitions,
        )
        n_partitions = max_partitions

    total_combos = math.comb(n_partitions, n_partitions // 2)
    logger.debug(
        "PBO计算: %d策略 × %d时间点, %d分区, C(%d,%d)=%d种组合",
        n_strategies, n_timepoints, n_partitions,
        n_partitions, n_partitions // 2, total_combos,
    )

    # ── 1. 将时间点分成S个block ──
    # 截断尾部使得能被S整除
    block_size = n_timepoints // n_partitions
    usable_timepoints = block_size * n_partitions
    trimmed_matrix = returns_matrix[:, :usable_timepoints]

    # blocks[s] shape = (N, block_size)
    blocks = np.array_split(trimmed_matrix, n_partitions, axis=1)

    # 预计算每个策略在每个block的性能指标(Sharpe ratio)
    # block_perf[s, n] = 策略n在block s的Sharpe
    block_perf = np.zeros((n_partitions, n_strategies))
    for s in range(n_partitions):
        block_data = blocks[s]  # shape (N, block_size)
        means = block_data.mean(axis=1)
        stds = block_data.std(axis=1, ddof=1)
        # 避免除零: std=0时Sharpe=0
        safe_stds = np.where(stds > 1e-15, stds, 1.0)
        block_perf[s] = np.where(stds > 1e-15, means / safe_stds, 0.0)

    # ── 2. 穷举所有C(S, S/2)种train/test分割 ──
    half = n_partitions // 2
    all_indices = list(range(n_partitions))
    logit_values: list[float] = []

    for train_indices in combinations(all_indices, half):
        test_indices = tuple(
            i for i in all_indices if i not in train_indices
        )

        # 3a. 计算每个策略在train集的综合Sharpe
        train_perf = block_perf[list(train_indices), :].mean(axis=0)

        # 3b. 找train集最优策略
        best_strategy = int(np.argmax(train_perf))

        # 3c. 计算该策略在test集的表现
        test_perf = block_perf[list(test_indices), :].mean(axis=0)

        # 3d. 计算OOS排名 (0-based, 越小越好)
        # argsort返回从小到大的索引, 我们需要从大到小的排名
        sorted_indices = np.argsort(-test_perf)  # 降序
        rank = int(np.where(sorted_indices == best_strategy)[0][0])

        # 3e. 计算logit: log(rank / (N - rank))
        # rank=0(最优) → logit=-inf, rank=N-1(最差) → logit=+inf
        # rank=N/2(中位) → logit~0
        # 为避免log(0), 使用(rank + 0.5) / (N - rank - 0.5)
        logit = math.log(
            (rank + 0.5) / (n_strategies - rank - 0.5)
        )
        logit_values.append(logit)

    # ── 4. PBO = P(logit > 0) ──
    # logit > 0 意味着IS最优策略在OOS排名低于中位数(表现差),
    # 即选出的"最优"策略在样本外不行 → 过拟合。
    logit_array = np.array(logit_values)
    pbo = float(np.mean(logit_array > 0))

    logger.info(
        "PBO计算完成: pbo=%.4f, %d种组合, logit均值=%.4f",
        pbo, total_combos, float(logit_array.mean()),
    )

    return {
        "pbo": pbo,
        "logit_distribution": logit_values,
        "n_combinations": total_combos,
        "n_partitions": n_partitions,
        "n_strategies": n_strategies,
        "n_timepoints": n_timepoints,
    }


def interpret_pbo(pbo: float) -> str:
    """解读PBO值, 返回中文说明。

    Args:
        pbo: 过拟合概率值。负值表示无法计算(数据不足)。

    Returns:
        中文解读文本。
    """
    if pbo < 0:
        return "数据不足, 无法计算过拟合概率"
    elif pbo < 0.3:
        return "低过拟合风险: 策略在样本外大概率有效"
    elif pbo < 0.6:
        return "中等过拟合风险: 策略可能部分依赖样本内噪声"
    else:
        return "高过拟合风险: 策略大概率是过拟合产物, 不建议实盘"
