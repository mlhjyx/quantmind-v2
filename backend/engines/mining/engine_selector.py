"""Thompson Sampling 引擎选择器 — 自适应选择BruteForce/GP/LLM引擎。

设计来源:
  - docs/research/R2_factor_mining_frontier.md §7: Thompson Sampling (RD-Agent模式)
  - docs/DEV_AI_EVOLUTION.md §4: 三引擎编排

功能:
  1. 维护每个引擎的Beta分布参数 (alpha, beta)
  2. 每次挖掘前采样选引擎（exploration-exploitation平衡）
  3. 根据Gate通过率更新分布参数
  4. 支持持久化到JSON文件（跨session保持学习状态）

三个引擎:
  - bruteforce: Alpha158暴力枚举 (快速，成功率稳定)
  - gp: DEAP GP进化 (慢但创新性强)
  - llm: IdeaAgent→FactorAgent→EvalAgent (依赖API，成功率待验证)

Engine层规范: 纯计算无IO（除load/save持久化）。

Sprint 1.18 (D6补全)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 引擎名称常量
# ---------------------------------------------------------------------------

ENGINE_BRUTEFORCE = "bruteforce"
ENGINE_GP = "gp"
ENGINE_LLM = "llm"

ALL_ENGINES = [ENGINE_BRUTEFORCE, ENGINE_GP, ENGINE_LLM]

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class EngineStats:
    """单引擎的Beta分布参数和统计。"""
    name: str
    alpha: float = 1.0       # Beta分布成功参数（先验=1）
    beta: float = 1.0        # Beta分布失败参数（先验=1）
    total_runs: int = 0
    total_successes: int = 0  # Gate通过次数

    @property
    def success_rate(self) -> float:
        """历史成功率。"""
        if self.total_runs == 0:
            return 0.0
        return self.total_successes / self.total_runs

    @property
    def mean(self) -> float:
        """Beta分布均值 = alpha / (alpha + beta)。"""
        return self.alpha / (self.alpha + self.beta)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "alpha": self.alpha,
            "beta": self.beta,
            "total_runs": self.total_runs,
            "total_successes": self.total_successes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EngineStats:
        return cls(
            name=d["name"],
            alpha=d.get("alpha", 1.0),
            beta=d.get("beta", 1.0),
            total_runs=d.get("total_runs", 0),
            total_successes=d.get("total_successes", 0),
        )


@dataclass
class SelectionResult:
    """引擎选择结果。"""
    selected_engine: str
    sampled_scores: dict[str, float]  # {engine: sampled_value}
    reason: str


# ---------------------------------------------------------------------------
# Thompson Sampling引擎选择器
# ---------------------------------------------------------------------------


class ThompsonSamplingSelector:
    """基于Thompson Sampling的引擎自适应选择器。

    每次挖掘前:
    1. 对每个引擎的Beta(alpha, beta)分布采样一个值
    2. 选择采样值最大的引擎
    3. 运行后根据结果更新分布

    RD-Agent(微软)研究表明:
    - 初期随机探索 → 中期收敛到最优引擎 → 后期偶尔探索保持多样性
    - Beta(1,1)先验 = 均匀分布（无偏起步）

    用法:
        selector = ThompsonSamplingSelector()
        result = selector.select()
        # ... 运行 result.selected_engine ...
        selector.update(result.selected_engine, success=True)
    """

    def __init__(
        self,
        engines: list[str] | None = None,
        seed: int | None = None,
    ) -> None:
        self._engines: dict[str, EngineStats] = {}
        for name in (engines or ALL_ENGINES):
            self._engines[name] = EngineStats(name=name)
        self._rng = np.random.RandomState(seed)

    def select(self) -> SelectionResult:
        """Thompson Sampling选择引擎。

        Returns:
            SelectionResult: 被选引擎和采样分数。
        """
        sampled: dict[str, float] = {}

        for name, stats in self._engines.items():
            # 从Beta(alpha, beta)分布采样
            sampled[name] = float(
                self._rng.beta(stats.alpha, stats.beta)
            )

        # 选最大值
        selected = max(sampled, key=sampled.get)  # type: ignore[arg-type]

        # 构建reason
        stats = self._engines[selected]
        reason = (
            f"Thompson采样选择 {selected} "
            f"(score={sampled[selected]:.3f}, "
            f"历史成功率={stats.success_rate:.1%}, "
            f"runs={stats.total_runs})"
        )

        logger.info("[EngineSelector] %s", reason)

        return SelectionResult(
            selected_engine=selected,
            sampled_scores=sampled,
            reason=reason,
        )

    def update(self, engine: str, success: bool) -> None:
        """根据运行结果更新Beta分布参数。

        Args:
            engine: 引擎名称。
            success: Gate是否通过（True=至少1个因子通过G1-G5）。
        """
        if engine not in self._engines:
            logger.warning("[EngineSelector] 未知引擎: %s", engine)
            return

        stats = self._engines[engine]
        stats.total_runs += 1

        if success:
            stats.alpha += 1
            stats.total_successes += 1
        else:
            stats.beta += 1

        logger.info(
            f"[EngineSelector] 更新 {engine}: success={success}, alpha={stats.alpha:.1f}, beta={stats.beta:.1f}, runs={stats.total_runs}",
        )

    def get_stats(self) -> dict[str, dict]:
        """返回所有引擎的统计信息。"""
        return {name: s.to_dict() for name, s in self._engines.items()}

    def save(self, path: str | Path) -> None:
        """持久化到JSON文件。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: s.to_dict() for name, s in self._engines.items()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("[EngineSelector] 保存到 %s", path)

    def load(self, path: str | Path) -> None:
        """从JSON文件恢复状态。"""
        path = Path(path)
        if not path.exists():
            logger.warning("[EngineSelector] 文件不存在: %s，使用默认先验", path)
            return

        data = json.loads(path.read_text(encoding="utf-8"))
        for name, d in data.items():
            if name in self._engines:
                self._engines[name] = EngineStats.from_dict(d)
            else:
                self._engines[name] = EngineStats.from_dict(d)

        logger.info(
            "[EngineSelector] 从 %s 恢复: %s",
            path,
            {n: f"α={s.alpha:.0f},β={s.beta:.0f}" for n, s in self._engines.items()},
        )
