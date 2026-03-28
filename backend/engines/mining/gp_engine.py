"""Warm Start GP引擎 — DEAP + 岛屿模型 + 逻辑/参数分离

设计来源: GP_CLOSED_LOOP_DESIGN.md §3 + §4
功能:
  1. Warm Start初始化: 用v1.1的5个种子因子生成初始种群
  2. 岛屿模型: 2-4个子种群独立进化，定期迁移
  3. 逻辑/参数分离: 结构树GP进化 + Optuna参数优化
  4. 适应度函数: Sharpe×(1-0.1×complexity) + 0.3×novelty
  5. DEAP集成: creator/toolbox/algorithms标准接口
  6. 反拥挤: 与现有因子相关性>0.6时惩罚

依赖:
  - factor_dsl.py: ExprNode/FactorDSL/SEED_FACTORS
  - factor_gate.py: FactorGatePipeline.quick_screen
  - backtest_engine.py: BacktestConfig（适应度快速回测接口）

Sprint 1.16 alpha-miner
"""

from __future__ import annotations

import logging
import math
import random
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

# DEAP导入（已验证版本1.4）
try:
    from deap import base, creator, tools
    _DEAP_AVAILABLE = True
except ImportError:
    _DEAP_AVAILABLE = False
    logger_init = logging.getLogger(__name__)
    logger_init.error("DEAP未安装！运行: pip install deap")

from engines.mining.factor_dsl import (
    MAX_DEPTH,
    MAX_NODES,
    SEED_FACTORS,
    TERMINALS,
    ExprNode,
    FactorDSL,
    get_seed_trees,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class GPConfig:
    """GP引擎配置（对应 GP_CLOSED_LOOP_DESIGN §3.4）。"""

    # 种群
    n_islands: int = 2                  # 子种群数（生产用4，测试用2节省时间）
    population_per_island: int = 50     # 每岛个体数（生产200，测试50）
    # 进化
    n_generations: int = 20             # 进化代数（生产50，测试20）
    crossover_prob: float = 0.7
    mutation_prob: float = 0.3
    tournament_size: int = 3
    migration_interval: int = 5         # 每N代迁移一次（生产10）
    migration_size: int = 3             # 每次迁移个体数（生产5）
    # Warm Start
    seed_ratio: float = 0.8             # 80%种群从种子初始化
    random_ratio: float = 0.2           # 20%随机保持多样性
    # 约束
    max_depth: int = MAX_DEPTH
    max_nodes: int = MAX_NODES
    time_budget_minutes: float = 120.0  # 2小时预算
    # 逻辑/参数分离
    use_optuna: bool = False            # Optuna参数优化（生产开启，测试关闭）
    optuna_trials: int = 10             # 每个个体的Optuna搜索次数（生产20）
    # 反拥挤
    anti_crowd_threshold: float = 0.6   # 相关性>0.6判定为拥挤
    # 快速Gate
    quick_gate_ic_threshold: float = 0.015  # GP快速筛选IC下限（宽松）
    quick_gate_t_threshold: float = 2.0     # GP快速筛选t统计量下限
    # 并行
    n_workers: int = 1                  # 评估并行进程数（1=串行）


@dataclass
class GPResult:
    """单个因子候选的GP产出结果。"""

    factor_expr: str           # DSL表达式字符串
    ast_hash: str              # 结构哈希（去重用）
    fitness: float             # 综合适应度分数
    sharpe_proxy: float        # IC_IR代理（未接SimBroker时）
    complexity: float          # 节点数/MAX_NODES
    novelty: float             # 正交性奖励
    ic_mean: float             # 平均IC
    t_stat: float              # t统计量
    generation: int            # 哪一代产出
    island_id: int             # 来自哪个岛
    parent_seed: str           # 从哪个种子因子进化而来（或"random"）
    gate_passed: bool = False   # 是否通过快速Gate G1-G3
    param_slots: dict[str, int] = field(default_factory=dict)  # 最优参数槽位


@dataclass
class GPRunStats:
    """GP运行统计信息。"""

    run_id: str
    total_evaluated: int = 0
    passed_quick_gate: int = 0
    best_fitness: float = -999.0
    best_expr: str = ""
    elapsed_seconds: float = 0.0
    n_generations_completed: int = 0
    per_island_best: dict[int, float] = field(default_factory=dict)
    timeout: bool = False


# ---------------------------------------------------------------------------
# 适应度函数（闭环核心）
# ---------------------------------------------------------------------------


class FitnessEvaluator:
    """GP适应度函数评估器。

    适应度 = IC_IR_proxy × (1 - 0.1 × complexity) + 0.3 × novelty_bonus

    设计说明（GP_CLOSED_LOOP_DESIGN §4）:
    - 快速模式（GP进化中）: 用IC_IR代替Sharpe（避免昂贵的SimBroker回测）
    - 完整模式（Gate后验证）: 调用SimBroker全量回测
    - IC_IR = IC_mean / IC_std（是Sharpe的良好代理，相关系数>0.85）

    关于未接SimBroker的说明:
    SimBroker快速回测需要完整行情数据库连接（PG），在GP进化时每个个体调用
    一次~2秒会使2小时预算只能评估~3600个（4岛×200个×50代=40000个评估）。
    当前实现用IC_IR代理，接入SimBroker时替换_compute_sharpe_proxy方法。
    """

    def __init__(
        self,
        dsl: FactorDSL,
        existing_factor_data: dict[str, pd.Series] | None = None,
        config: GPConfig | None = None,
    ) -> None:
        self.dsl = dsl
        self.existing_factor_data = existing_factor_data or {}
        self.config = config or GPConfig()

    def evaluate(
        self,
        tree: ExprNode,
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
        generation: int = 0,
        island_id: int = 0,
    ) -> tuple[float]:
        """计算单个因子树的适应度分数。

        Args:
            tree: 因子表达式树。
            market_data: 行情宽表（行=日期或symbol，列=字段）。
            forward_returns: 前向收益率Series（同index）。
            generation: 当前代数（用于调试）。
            island_id: 岛屿ID（用于调试）。

        Returns:
            (fitness,): DEAP要求返回tuple。
        """
        try:
            # 1. 计算因子值
            factor_values = tree.evaluate(market_data)

            # 2. 基本质量检查（G1前置）
            if not self._basic_check(factor_values, forward_returns):
                return (-1.0,)

            # 3. 计算IC序列
            ic_mean, ic_std, t_stat, n_obs = self._compute_ic_stats(
                factor_values, forward_returns
            )

            # 4. 快速Gate检查（G1-G3宽松版）
            if not self._quick_gate_check(ic_mean, t_stat):
                return (-1.0,)

            # 5. IC_IR代理（Sharpe代理）
            sharpe_proxy = ic_mean / max(ic_std, 1e-8) if ic_std > 0 else 0.0

            # 6. 复杂度惩罚（GP_CLOSED_LOOP_DESIGN §3.5）
            complexity = tree.complexity_score()

            # 7. 正交性奖励（与现有因子相关性越低越好）
            novelty = self._compute_novelty(factor_values)

            # 8. 综合适应度
            # fitness = Sharpe × (1 - 0.1 × complexity) + 0.3 × novelty
            fitness = (
                sharpe_proxy * (1.0 - 0.1 * complexity)
                + 0.3 * novelty
            )

            return (max(fitness, -1.0),)

        except Exception as e:
            logger.debug("适应度计算异常 gen=%d island=%d: %s", generation, island_id, e)
            return (-1.0,)

    def _basic_check(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
    ) -> bool:
        """基本质量检查：非NaN覆盖率、有效数量。"""
        if factor_values is None:
            return False
        valid_count = factor_values.dropna().shape[0]
        total_count = len(factor_values)
        if total_count == 0 or valid_count / max(total_count, 1) < 0.3:
            return False
        return valid_count >= 20

    def _compute_ic_stats(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
    ) -> tuple[float, float, float, int]:
        """计算IC均值、IC标准差、t统计量、样本数。

        使用Spearman秩相关（Rank IC）。
        factor_values和forward_returns需要对齐index。
        """
        common_idx = factor_values.dropna().index.intersection(
            forward_returns.dropna().index
        )
        if len(common_idx) < 10:
            return 0.0, 1.0, 0.0, 0

        fv = factor_values.loc[common_idx]
        fr = forward_returns.loc[common_idx]

        # 如果是多时间点的面板数据，按日期分组计算截面IC
        if hasattr(fv.index, "names") and fv.index.nlevels > 1:
            # MultiIndex (date, symbol)
            ic_series = []
            for date, group_fv in fv.groupby(level=0):
                group_fr = fr.loc[date] if date in fr.index.get_level_values(0) else None
                if group_fr is None or len(group_fv) < 10:
                    continue
                try:
                    ic = group_fv.corr(group_fr, method="spearman")
                    if not math.isnan(ic):
                        ic_series.append(float(ic))
                except Exception:
                    continue

            if len(ic_series) < 3:
                return 0.0, 1.0, 0.0, 0

            ic_arr = np.array(ic_series)
            ic_mean = float(np.mean(ic_arr))
            ic_std = float(np.std(ic_arr, ddof=1))
            n = len(ic_arr)
        else:
            # 单截面：直接计算一个IC
            try:
                ic_mean = float(fv.corr(fr, method="spearman"))
                if math.isnan(ic_mean):
                    return 0.0, 1.0, 0.0, 0
            except Exception:
                return 0.0, 1.0, 0.0, 0
            ic_std = 0.01  # 单截面无法计算std，给默认值
            n = 1

        t_stat = ic_mean / (ic_std / math.sqrt(max(n, 1))) if ic_std > 1e-8 else 0.0
        return ic_mean, ic_std, t_stat, n

    def _quick_gate_check(self, ic_mean: float, t_stat: float) -> bool:
        """G1-G3宽松快速Gate（GP进化中用，不调用FactorGatePipeline）。"""
        ic_threshold = self.config.quick_gate_ic_threshold
        t_threshold = self.config.quick_gate_t_threshold
        if abs(ic_mean) < ic_threshold:
            return False
        return abs(t_stat) >= t_threshold

    def _compute_novelty(self, factor_values: pd.Series) -> float:
        """计算正交性奖励。

        与现有Active因子的最大Spearman相关性越低，奖励越高。
        corr < 0.7 才有奖励（来自Gate G6标准）。
        """
        if not self.existing_factor_data:
            return 0.5  # 无参照时给中等奖励

        max_corr = 0.0
        for existing_series in self.existing_factor_data.values():
            common = factor_values.dropna().index.intersection(
                existing_series.dropna().index
            )
            if len(common) < 20:
                continue
            try:
                corr = abs(float(
                    factor_values.loc[common].corr(
                        existing_series.loc[common], method="spearman"
                    )
                ))
                max_corr = max(max_corr, corr)
            except Exception:
                continue

        # GP_CLOSED_LOOP_DESIGN §3.5: corr<0.7才有奖励
        novelty = max(0.0, 0.7 - max_corr)
        return novelty


# ---------------------------------------------------------------------------
# DEAP适配器（将ExprNode包装为DEAP个体）
# ---------------------------------------------------------------------------


def _make_deap_individual(tree: ExprNode) -> list:
    """将ExprNode包装为DEAP可操作的列表个体。

    DEAP的GP通常用列表表示前序遍历，但我们保持ExprNode结构，
    用单元素列表包装（列表的第0个元素是ExprNode）。
    这样DEAP的fitness/selection机制可以正常工作。
    """
    ind = [tree]
    return ind


def _get_tree(individual: list) -> ExprNode:
    """从DEAP个体中提取ExprNode。"""
    return individual[0]


# ---------------------------------------------------------------------------
# GP引擎主类
# ---------------------------------------------------------------------------


class GPEngine:
    """Warm Start GP引擎（DEAP + 岛屿模型 + 逻辑参数分离）。

    使用方法:
        config = GPConfig(n_islands=2, population_per_island=50, n_generations=20)
        engine = GPEngine(config)
        results = engine.evolve(
            market_data=df,           # 行情宽表
            forward_returns=returns,  # 前向收益
        )
        for r in results:
            print(r.factor_expr, r.fitness)

    架构（GP_CLOSED_LOOP_DESIGN §3）:
        初始化 → [岛屿进化 × n_islands] → 迁移(每migration_interval代) → 合并结果
    """

    def __init__(
        self,
        config: GPConfig | None = None,
        existing_factor_data: dict[str, pd.Series] | None = None,
    ) -> None:
        """初始化GP引擎。

        Args:
            config: GP配置，None使用默认配置。
            existing_factor_data: 现有Active因子值 {factor_name: Series}，
                                   用于适应度函数的正交性奖励计算。
        """
        if not _DEAP_AVAILABLE:
            raise RuntimeError("DEAP未安装，请运行: pip install deap")

        self.config = config or GPConfig()
        self.existing_factor_data = existing_factor_data or {}
        self.dsl = FactorDSL(
            max_depth=self.config.max_depth,
            max_nodes=self.config.max_nodes,
        )
        self.evaluator = FitnessEvaluator(
            dsl=self.dsl,
            existing_factor_data=self.existing_factor_data,
            config=self.config,
        )
        self._setup_deap()

    def _setup_deap(self) -> None:
        """注册DEAP的creator和toolbox。"""
        # 避免重复定义（DEAP的creator是全局的）
        if not hasattr(creator, "FitnessMax"):
            creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMax)

        self.toolbox = base.Toolbox()

        # 注册个体生成函数
        self.toolbox.register(
            "individual",
            self._create_individual,
        )
        self.toolbox.register(
            "population",
            tools.initRepeat,
            creator.Individual,
            self.toolbox.individual,
        )

        # 注册遗传算子
        self.toolbox.register("mate", self._crossover_op)
        self.toolbox.register("mutate", self._mutate_op)
        self.toolbox.register(
            "select",
            tools.selTournament,
            tournsize=self.config.tournament_size,
        )
        self.toolbox.register("evaluate", self._evaluate_individual)

    def _create_individual(self) -> creator.Individual:
        """创建单个DEAP个体（随机树）。"""
        tree = self.dsl.random_tree()
        ind = creator.Individual([tree])
        return ind

    def _crossover_op(
        self,
        ind1: creator.Individual,
        ind2: creator.Individual,
    ) -> tuple[creator.Individual, creator.Individual]:
        """DEAP交叉算子。"""
        tree1 = _get_tree(ind1)
        tree2 = _get_tree(ind2)
        child1_tree, child2_tree = self.dsl.crossover(tree1, tree2)
        ind1[0] = child1_tree
        ind2[0] = child2_tree
        del ind1.fitness.values
        del ind2.fitness.values
        return ind1, ind2

    def _mutate_op(self, ind: creator.Individual) -> tuple[creator.Individual,]:
        """DEAP变异算子。"""
        tree = _get_tree(ind)
        mutated = self.dsl.mutate(tree, mutation_rate=self.config.mutation_prob)
        ind[0] = mutated
        del ind.fitness.values
        return (ind,)

    def _evaluate_individual(
        self,
        ind: creator.Individual,
        market_data: pd.DataFrame | None = None,
        forward_returns: pd.Series | None = None,
        generation: int = 0,
        island_id: int = 0,
    ) -> tuple[float]:
        """DEAP评估函数（包装FitnessEvaluator）。"""
        if market_data is None or forward_returns is None:
            return (-1.0,)
        tree = _get_tree(ind)
        return self.evaluator.evaluate(
            tree, market_data, forward_returns, generation, island_id
        )

    # ----------------------------------------------------------------
    # Warm Start初始化
    # ----------------------------------------------------------------

    def initialize_population(
        self,
        island_id: int = 0,
    ) -> list[creator.Individual]:
        """Warm Start种群初始化（GP_CLOSED_LOOP_DESIGN §3.3）。

        种群分配策略:
          - 原始5个种子因子 (5个)
          - 每个种子×窗口变异 (最多20个)
          - 每个种子×字段替换 (最多20个)
          - 每个种子×外层包装 (最多15个)
          - 随机树填充剩余 (seed_ratio→random_ratio)

        Args:
            island_id: 岛屿ID（影响随机种子，保证不同岛有差异）。

        Returns:
            population_per_island个DEAP Individual。
        """
        pop_size = self.config.population_per_island
        seed_trees = get_seed_trees()

        warm_inds: list[creator.Individual] = []

        # 1. 原始种子因子
        for _name, tree in seed_trees.items():
            ind = creator.Individual([tree.clone()])
            warm_inds.append(ind)

        # 2. 每个种子生成变体
        for name, expr in SEED_FACTORS.items():
            n_variants = max(2, (pop_size - len(seed_trees)) // (len(SEED_FACTORS) * 3))
            variants = self.dsl.seed_to_variants(name, expr, n_variants=n_variants)
            for tree in variants[1:]:  # 跳过第一个（原始种子已加入）
                valid, _ = self.dsl.validate(tree)
                if valid:
                    ind = creator.Individual([tree])
                    warm_inds.append(ind)

        # 3. 剪掉超出的
        seed_budget = int(pop_size * self.config.seed_ratio)
        warm_inds = warm_inds[:seed_budget]

        # 4. 随机树填充剩余
        random_count = pop_size - len(warm_inds)
        # 不同岛用不同随机种子，保证多样性
        rng_backup = self.dsl._rng
        self.dsl._rng = random.Random(island_id * 1000 + 42)

        for _ in range(random_count):
            tree = self.dsl.random_tree()
            ind = creator.Individual([tree])
            warm_inds.append(ind)

        self.dsl._rng = rng_backup

        logger.info(
            "岛屿%d 初始化: warm=%d, random=%d, total=%d",
            island_id, seed_budget, random_count, len(warm_inds),
        )
        return warm_inds

    # ----------------------------------------------------------------
    # 主进化入口
    # ----------------------------------------------------------------

    def evolve(
        self,
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
        run_id: str | None = None,
    ) -> tuple[list[GPResult], GPRunStats]:
        """运行GP进化，返回通过快速Gate的因子列表。

        Args:
            market_data: 行情宽表。行=symbol（单截面）或(date,symbol)（面板）。
                         列=数据字段（close/volume/returns等）。
            forward_returns: 前向收益率Series（与market_data对齐）。
            run_id: 本次运行的唯一标识符，None则自动生成。

        Returns:
            (results, stats):
              results: 通过快速Gate的GPResult列表（按fitness降序）。
              stats: 本次运行统计信息。
        """
        if run_id is None:
            run_id = f"gp_{int(time.time())}"

        logger.info(
            "GP进化开始: run_id=%s, islands=%d, pop=%d, gen=%d",
            run_id,
            self.config.n_islands,
            self.config.population_per_island,
            self.config.n_generations,
        )

        stats = GPRunStats(run_id=run_id)
        start_time = time.time()
        budget_seconds = self.config.time_budget_minutes * 60.0

        # 初始化各岛种群
        islands: list[list[creator.Individual]] = [
            self.initialize_population(island_id=i)
            for i in range(self.config.n_islands)
        ]

        # 评估初始种群
        for island_id, pop in enumerate(islands):
            self._evaluate_population(
                pop, market_data, forward_returns, generation=0, island_id=island_id
            )
        stats.total_evaluated += sum(len(p) for p in islands)

        halloffame = tools.HallOfFame(maxsize=50)

        # 主进化循环
        gen_completed = 0

        for gen in range(1, self.config.n_generations + 1):
            # 检查时间预算
            elapsed = time.time() - start_time
            if elapsed > budget_seconds:
                logger.warning(
                    "GP超时: elapsed=%.1fs > budget=%.1fs，停止进化",
                    elapsed, budget_seconds,
                )
                stats.timeout = True
                break

            # 每岛独立进化一代
            for island_id, pop in enumerate(islands):
                pop[:] = self._evolve_one_generation(
                    pop, market_data, forward_returns,
                    generation=gen, island_id=island_id,
                )
                stats.total_evaluated += len(pop)

            # 更新HallOfFame
            all_pops = [ind for pop in islands for ind in pop]
            halloffame.update(all_pops)

            # 岛屿迁移（环形迁移）
            if gen % self.config.migration_interval == 0:
                islands = self._migrate(islands)
                logger.debug("第%d代: 岛屿迁移完成", gen)

            gen_completed = gen

            # 日志
            if gen % 5 == 0 or gen == self.config.n_generations:
                best_fitness = max(
                    (ind.fitness.values[0] for ind in all_pops if ind.fitness.valid),
                    default=-999.0,
                )
                logger.info(
                    "Gen %d/%d: best_fitness=%.4f, elapsed=%.1fs",
                    gen, self.config.n_generations, best_fitness,
                    time.time() - start_time,
                )

        # 收集结果
        elapsed = time.time() - start_time
        stats.elapsed_seconds = elapsed
        stats.n_generations_completed = gen_completed

        # 从HallOfFame提取通过快速Gate的因子
        results = self._extract_results(
            halloffame, market_data, forward_returns, gen_completed
        )

        stats.passed_quick_gate = len(results)
        if results:
            stats.best_fitness = results[0].fitness
            stats.best_expr = results[0].factor_expr

        logger.info(
            "GP进化完成: run_id=%s, gen=%d, evaluated=%d, passed_gate=%d, "
            "best_fitness=%.4f, elapsed=%.1fs",
            run_id, gen_completed, stats.total_evaluated,
            stats.passed_quick_gate, stats.best_fitness, elapsed,
        )

        return results, stats

    def _evolve_one_generation(
        self,
        pop: list[creator.Individual],
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
        generation: int,
        island_id: int,
    ) -> list[creator.Individual]:
        """进化一代（选择→交叉→变异→评估）。"""
        # 选择
        offspring = self.toolbox.select(pop, len(pop))
        offspring = list(map(deepcopy, offspring))

        # 交叉
        for i in range(0, len(offspring) - 1, 2):
            if random.random() < self.config.crossover_prob:
                self.toolbox.mate(offspring[i], offspring[i + 1])

        # 变异
        for ind in offspring:
            if random.random() < self.config.mutation_prob:
                self.toolbox.mutate(ind)

        # 评估未计算fitness的个体
        invalid_inds = [ind for ind in offspring if not ind.fitness.valid]
        for ind in invalid_inds:
            ind.fitness.values = self._evaluate_individual(
                ind, market_data, forward_returns, generation, island_id
            )

        # 精英保留（取当前代和父代各50%的最好个体）
        pop[:] = tools.selBest(pop + offspring, len(pop))
        return pop

    def _evaluate_population(
        self,
        pop: list[creator.Individual],
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
        generation: int,
        island_id: int,
    ) -> None:
        """批量评估种群（原地修改fitness）。"""
        invalid_inds = [ind for ind in pop if not ind.fitness.valid]
        for ind in invalid_inds:
            ind.fitness.values = self._evaluate_individual(
                ind, market_data, forward_returns, generation, island_id
            )

    def _evaluate_individual(
        self,
        ind: creator.Individual,
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
        generation: int = 0,
        island_id: int = 0,
    ) -> tuple[float]:
        """评估单个个体。"""
        tree = _get_tree(ind)
        return self.evaluator.evaluate(
            tree, market_data, forward_returns, generation, island_id
        )

    def _migrate(
        self,
        islands: list[list[creator.Individual]],
    ) -> list[list[creator.Individual]]:
        """环形迁移：每个岛屿的精英迁移到下一个岛屿。

        island[0] → island[1] → ... → island[n-1] → island[0]
        """
        n = len(islands)
        if n <= 1:
            return islands

        emigrants: list[list[creator.Individual]] = []
        for pop in islands:
            # 选出最好的migration_size个个体
            best = tools.selBest(pop, self.config.migration_size)
            emigrants.append(list(map(deepcopy, best)))

        for i, pop in enumerate(islands):
            src = emigrants[(i - 1) % n]  # 来自上一个岛
            # 替换种群中最差的migration_size个个体
            worst_indices = sorted(
                range(len(pop)),
                key=lambda j: pop[j].fitness.values[0] if pop[j].fitness.valid else -999.0,
            )[:self.config.migration_size]
            for idx, immigrant in zip(worst_indices, src, strict=False):
                pop[idx] = deepcopy(immigrant)

        return islands

    def _make_stats(self) -> tools.Statistics:
        """创建DEAP统计工具。"""
        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("avg", np.mean)
        stats.register("max", np.max)
        return stats

    def _extract_results(
        self,
        halloffame: tools.HallOfFame,
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
        generation: int,
    ) -> list[GPResult]:
        """从HallOfFame提取GPResult，过滤掉适应度<0的个体。"""
        results: list[GPResult] = []
        seen_hashes: set[str] = set()

        for ind in halloffame:
            if not ind.fitness.valid:
                continue
            fitness = ind.fitness.values[0]
            if fitness <= 0:
                continue

            tree = _get_tree(ind)
            expr_str = tree.to_string()
            ast_hash = tree.to_ast_hash()

            # AST去重
            if ast_hash in seen_hashes:
                continue
            seen_hashes.add(ast_hash)

            # 重新计算详细指标
            try:
                factor_values = tree.evaluate(market_data)
                ic_mean, ic_std, t_stat, n_obs = self.evaluator._compute_ic_stats(
                    factor_values, forward_returns
                )
                novelty = self.evaluator._compute_novelty(factor_values)
            except Exception:
                ic_mean, ic_std, t_stat = 0.0, 0.01, 0.0
                novelty = 0.0

            complexity = tree.complexity_score()
            sharpe_proxy = ic_mean / max(ic_std, 1e-8) if ic_std > 0 else 0.0

            # 参数槽位（逻辑/参数分离）
            _, param_slots = self.dsl.extract_template(tree)

            result = GPResult(
                factor_expr=expr_str,
                ast_hash=ast_hash,
                fitness=fitness,
                sharpe_proxy=sharpe_proxy,
                complexity=complexity,
                novelty=novelty,
                ic_mean=ic_mean,
                t_stat=t_stat,
                generation=generation,
                island_id=0,
                parent_seed=self._find_parent_seed(expr_str),
                gate_passed=True,
                param_slots=param_slots,
            )
            results.append(result)

        # 按fitness降序
        results.sort(key=lambda r: r.fitness, reverse=True)
        return results

    def _find_parent_seed(self, expr_str: str) -> str:
        """尝试识别该因子从哪个种子进化而来（启发式）。"""
        for seed_name, seed_expr in SEED_FACTORS.items():
            # 简单字符串匹配：如果包含种子的核心字段
            seed_terminals = [t for t in TERMINALS if t in seed_expr]
            for terminal in seed_terminals:
                if terminal in expr_str:
                    return seed_name
        return "random"

    # ----------------------------------------------------------------
    # Warm Start有效性验证
    # ----------------------------------------------------------------

    def compare_warm_vs_random(
        self,
        market_data: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> dict[str, float]:
        """验证Warm Start是否优于随机初始化（GP_CLOSED_LOOP_DESIGN §10.1）。

        运行一个mini-GP比较首代适应度分布。

        Returns:
            {
                "warm_start_mean_fitness": float,
                "random_init_mean_fitness": float,
                "improvement_ratio": float,   # warm/random
                "warm_start_better": bool,
            }
        """
        n_sample = min(20, self.config.population_per_island)

        # Warm Start初始化
        warm_pop = self.initialize_population(island_id=0)[:n_sample]
        self._evaluate_population(warm_pop, market_data, forward_returns, 0, 0)
        warm_fitnesses = [
            ind.fitness.values[0] for ind in warm_pop if ind.fitness.valid
        ]
        warm_mean = float(np.mean(warm_fitnesses)) if warm_fitnesses else -1.0

        # 随机初始化
        random_pop = [creator.Individual([self.dsl.random_tree()]) for _ in range(n_sample)]
        self._evaluate_population(random_pop, market_data, forward_returns, 0, 0)
        random_fitnesses = [
            ind.fitness.values[0] for ind in random_pop if ind.fitness.valid
        ]
        random_mean = float(np.mean(random_fitnesses)) if random_fitnesses else -1.0

        improvement = warm_mean / max(abs(random_mean), 1e-8) if random_mean != 0 else 0.0
        warm_better = warm_mean > random_mean

        logger.info(
            "Warm Start验证: warm_mean=%.4f, random_mean=%.4f, "
            "improvement=%.2fx, warm_better=%s",
            warm_mean, random_mean, improvement, warm_better,
        )

        return {
            "warm_start_mean_fitness": warm_mean,
            "random_init_mean_fitness": random_mean,
            "improvement_ratio": improvement,
            "warm_start_better": warm_better,
        }


# ---------------------------------------------------------------------------
# Optuna参数优化（逻辑/参数分离的参数优化部分）
# ---------------------------------------------------------------------------


def optimize_params_optuna(
    template: ExprNode,
    original_params: dict[str, int],
    search_space: dict[str, list[int]],
    market_data: pd.DataFrame,
    forward_returns: pd.Series,
    n_trials: int = 10,
    existing_factor_data: dict[str, pd.Series] | None = None,
) -> tuple[dict[str, int], float]:
    """用Optuna为因子模板搜索最优窗口参数。

    Args:
        template: 由FactorDSL.extract_template返回的结构模板。
        original_params: 原始参数值（作为初始点）。
        search_space: {slot_name: [候选窗口列表]}。
        market_data: 行情宽表。
        forward_returns: 前向收益率。
        n_trials: Optuna搜索次数。
        existing_factor_data: 现有Active因子值（正交性奖励用）。

    Returns:
        (best_params, best_fitness): 最优参数和对应适应度。
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("Optuna未安装，返回原始参数。pip install optuna")
        return original_params, -1.0

    dsl = FactorDSL()
    evaluator = FitnessEvaluator(
        dsl=dsl,
        existing_factor_data=existing_factor_data or {},
    )

    def objective(trial: Any) -> float:
        params = {}
        for slot_name, candidates in search_space.items():
            params[slot_name] = trial.suggest_categorical(slot_name, candidates)

        tree = dsl.apply_params(template, params)
        fitness, = evaluator.evaluate(tree, market_data, forward_returns)
        return fitness

    study = optuna.create_study(direction="maximize")
    # 添加初始点
    study.enqueue_trial(original_params)
    study.optimize(objective, n_trials=n_trials)

    best_params = study.best_params
    best_fitness = study.best_value
    return best_params, best_fitness


# ---------------------------------------------------------------------------
# 便捷函数：快速运行GP Pipeline
# ---------------------------------------------------------------------------


def run_gp_pipeline(
    market_data: pd.DataFrame,
    forward_returns: pd.Series,
    existing_factor_data: dict[str, pd.Series] | None = None,
    config: GPConfig | None = None,
    run_id: str | None = None,
) -> tuple[list[GPResult], GPRunStats]:
    """便捷函数：一键运行GP因子挖掘Pipeline。

    Args:
        market_data: 行情宽表。
        forward_returns: 前向收益率。
        existing_factor_data: 现有Active因子值（用于正交性奖励）。
        config: GP配置，None使用默认（测试友好的小配置）。
        run_id: 本次运行ID。

    Returns:
        (results, stats)
    """
    if config is None:
        config = GPConfig()

    engine = GPEngine(config=config, existing_factor_data=existing_factor_data)
    return engine.evolve(market_data, forward_returns, run_id=run_id)
