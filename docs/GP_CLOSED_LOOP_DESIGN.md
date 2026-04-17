# GP最小闭环设计文档

> **版本**: 1.1 | **日期**: 2026-03-28 (创建) / 2026-04-16 (状态更新)
> **状态**: 🔧 PARTIAL (~40%) — GP引擎+FactorDSL+WarmStart已实现, Pipeline编排器8节点状态机已实现(超本文档4组件设计), 但端到端自动闭环未打通
> **代码实现**: `backend/engines/mining/` — gp_engine.py(DEAP+岛屿模型) / factor_dsl.py(算子集) / pipeline_orchestrator.py(8节点: GENERATE→SANDBOX→GATE→CLASSIFY→STRATEGY_MATCH→BACKTEST→RISK_CHECK→APPROVAL) / pipeline_utils.py
> **决策D6 (2026-04-16)**: GP先完善闭环(DSL→IC自动评估→Gate自动→入库) → LLM prompt改造(AlphaAgent范式) → 轨迹进化融合
> 唯一设计真相源: **docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md §11**

---

## 1. 为什么是GP最小闭环

### 1.1 问题

当前因子挖掘100%手动：人写因子代码→人跑IC→人判断→人决策。
AI闭环设计400+行（DEV_AI_EVOLUTION.md），但实现0%。

### 1.2 最小闭环定义

**4个组件形成一个自动循环**：

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  FactorDSL   │──→──│  GP Engine   │──→──│ Factor Gate  │──→──│  SimBroker   │
│ (算子集定义)  │      │ (Warm Start) │      │  (G1-G8)    │      │ (适应度回测)  │
└──────────────┘      └──────────────┘      └──────────────┘      └──────────────┘
                              ↑                                          │
                              │          适应度分数反馈                    │
                              └────────────────────────────────────────←─┘
```

**闭环 = GP产出因子 → Gate筛选 → SimBroker回测 → 回测结果反馈给GP适应度函数 → 下一代进化**

### 1.3 与完整AI闭环的关系

```
Step 2 (本设计):  GP ──→ Gate ──→ SimBroker ──→ 反馈 ──→ GP
                  │                                        │
                  └── 人工审批 approve/reject ──────────────┘

Step 3 (未来):    引擎选择(Thompson) ──→ [GP|BruteForce|LLM] ──→ Gate ──→
                  分类(FactorClassifier) ──→ 策略匹配回测 ──→ 风控检查 ──→
                  诊断优化 ──→ 知识森林更新 ──→ 下一轮
```

Step 2验证了核心循环可行后，Step 3只是在外层加编排器和更多引擎。

---

## 2. 组件1: FactorDSL（因子表达式语言）

### 2.1 设计目标

定义一套**安全、可序列化、Qlib兼容**的因子表达式语言，GP在此语言空间内进化。

### 2.2 算子集（参考Qlib Alpha158 + DEV_FACTOR_MINING §2.1）

```python
# 文件: backend/engines/mining/factor_dsl.py

from enum import Enum
from dataclasses import dataclass
from typing import Union

class OpType(Enum):
    """算子类型"""
    UNARY = "unary"           # 单目: f(x) → y
    BINARY = "binary"         # 双目: f(x, y) → z
    TS = "ts"                 # 时序: f(x, window) → y
    TS_BINARY = "ts_binary"   # 时序双目: f(x, y, window) → z
    CS = "cs"                 # 截面: f(x) → rank/zscore

# === 时序算子 (必须指定窗口w) ===
TS_OPS = {
    "ts_mean":  {"args": 1, "windows": [5, 10, 20, 60]},
    "ts_std":   {"args": 1, "windows": [5, 10, 20, 60]},
    "ts_max":   {"args": 1, "windows": [5, 10, 20, 60]},
    "ts_min":   {"args": 1, "windows": [5, 10, 20, 60]},
    "ts_sum":   {"args": 1, "windows": [5, 10, 20, 60]},
    "ts_rank":  {"args": 1, "windows": [5, 10, 20]},
    "ts_skew":  {"args": 1, "windows": [20, 60]},
    "ts_kurt":  {"args": 1, "windows": [20, 60]},
    "delay":    {"args": 1, "windows": [1, 5, 10, 20]},
    "delta":    {"args": 1, "windows": [1, 5, 10, 20]},
    "ts_pct":   {"args": 1, "windows": [1, 5, 10, 20]},  # pct_change
}

TS_BINARY_OPS = {
    "ts_corr":  {"args": 2, "windows": [10, 20, 60]},
    "ts_cov":   {"args": 2, "windows": [10, 20, 60]},
}

# === 截面算子 ===
CS_OPS = {
    "cs_rank":  {"args": 1},     # 截面百分位排名 [0,1]
    "cs_zscore": {"args": 1},    # 截面标准化
}

# === 数学算子 ===
UNARY_OPS = {
    "log":  {"args": 1},         # log(abs(x)+1)
    "abs":  {"args": 1},
    "sign": {"args": 1},
    "neg":  {"args": 1},         # -x
    "inv":  {"args": 1},         # 1/x (安全除法)
}

BINARY_OPS = {
    "add": {"args": 2},
    "sub": {"args": 2},
    "mul": {"args": 2},
    "div": {"args": 2},          # 安全除法, div/0 → NaN
    "max": {"args": 2},
    "min": {"args": 2},
}

# === 终端节点（数据字段）===
TERMINALS = [
    # 价量 (日频)
    "open", "high", "low", "close", "volume", "amount", "turnover_rate",
    # 估值 (日频)
    "pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv",
    # 资金流向 (日频)
    "buy_lg_amount", "sell_lg_amount", "net_lg_amount",
    "buy_md_amount", "sell_md_amount", "net_md_amount",
    # 派生 (预计算)
    "returns",     # close/delay(close,1) - 1
    "vwap",        # amount/volume
    "high_low",    # (high-low)/close
    "close_open",  # (close-open)/open
]

# === 表达式树最大深度 ===
MAX_DEPTH = 4         # 防止过度复杂
MAX_NODES = 20        # QuantaAlpha: 符号长度<=250字符
```

### 2.3 表达式树表示

```python
@dataclass
class ExprNode:
    """因子表达式树节点"""
    op: str                           # 算子名称或终端字段名
    children: list['ExprNode'] = None # 子节点
    window: int = None                # 时序算子窗口参数

    def to_string(self) -> str:
        """序列化为可读字符串: ts_mean(cs_rank(close), 20)"""
        ...

    def to_ast_hash(self) -> str:
        """结构哈希(参数归一化后)，用于AST去重"""
        ...

    def evaluate(self, data: pd.DataFrame) -> pd.Series:
        """安全执行，返回因子值"""
        ...

    def node_count(self) -> int:
        """节点数(复杂度度量)"""
        ...

class FactorDSL:
    """因子表达式语言——GP的搜索空间定义"""

    def random_tree(self, max_depth: int = 3) -> ExprNode:
        """随机生成合法表达式树"""
        ...

    def from_string(self, expr: str) -> ExprNode:
        """从字符串解析表达式树"""
        ...

    def validate(self, tree: ExprNode) -> tuple[bool, str]:
        """验证表达式合法性(量纲/深度/节点数)"""
        ...

    def extract_template(self, tree: ExprNode) -> tuple[ExprNode, dict]:
        """提取结构模板+参数槽位(逻辑/参数分离)

        输入: ts_mean(cs_rank(close), 20)
        输出: template=ts_mean(cs_rank(close), ?w1), params={w1: 20}
        """
        ...
```

### 2.4 量纲约束（剪枝无意义表达式）

```python
DIMENSION_RULES = {
    # 价格类字段不能直接做截面排序(量纲不同)
    # 但 returns/turnover_rate 已经是无量纲的
    "dimensionless": ["returns", "turnover_rate", "high_low", "close_open"],

    # 以下组合无经济学意义，GP直接跳过
    "forbidden_combos": [
        ("ts_corr", "volume", "pe_ttm"),   # 成交量和PE的时序相关无意义
        ("div", "close", "volume"),          # 价格/成交量无量纲意义
    ],
}
```

---

## 3. 组件2: Warm Start GP Engine

### 3.1 设计目标

**不是从随机表达式开始进化，而是从已验证的5个好因子的表达式结构出发。**

核心思想来自 arxiv 2412.00896（Warm Start GP）:
- 用已知有效因子做模板初始化种群
- 结构约束进化：所有个体共享相似的树结构
- 更高效地搜索"好因子附近"的空间

### 3.2 5个种子因子的表达式

```python
SEED_FACTORS = {
    "turnover_mean_20": "ts_mean(turnover_rate, 20)",
    "volatility_20":    "ts_std(returns, 20)",
    "reversal_20":      "neg(ts_pct(close, 20))",
    "amihud_20":        "ts_mean(div(abs(returns), amount), 20)",
    "bp_ratio":         "inv(pb)",
}
```

### 3.3 Warm Start初始化策略

```python
class WarmStartGP:
    """Warm Start GP引擎

    初始化策略(每个种子因子产出 population_size/5 个变体):
    1. 原始种子(不变)
    2. 窗口变异: 20→[5,10,40,60]
    3. 字段替换: close→[open, high, low, vwap]
    4. 外层算子包装: cs_rank(seed), log(seed), delta(seed, 5)
    5. 双因子组合: add(seed_A, seed_B), sub(seed_A, seed_B)
    6. 随机树(占20%种群，保持多样性)

    约束: 所有变体的树深度 <= MAX_DEPTH(4)
    """

    def __init__(self, config: GPConfig):
        self.config = config
        self.dsl = FactorDSL()

    def initialize_population(self) -> list[ExprNode]:
        """Warm Start种群初始化

        种群分配:
        - 5个种子原始因子 (5个)
        - 每个种子×4种窗口变异 (20个)
        - 每个种子×4种字段替换 (20个)
        - 每个种子×3种外层包装 (15个)
        - 双因子组合C(5,2)×2种 (20个)
        - 随机树 (剩余填充到population_size)

        Returns: population_size个初始个体
        """
        ...
```

### 3.4 岛屿模型 + 逻辑/参数分离

```python
@dataclass
class GPConfig:
    """GP引擎配置(param_defaults已注册)"""
    # 种群
    n_islands: int = 4              # 4个子群(岛屿)
    population_per_island: int = 200  # 每岛200个体
    # 进化
    n_generations: int = 50
    crossover_prob: float = 0.7
    mutation_prob: float = 0.2
    migration_interval: int = 10    # 每10代迁移
    migration_size: int = 5         # 每次迁移5个
    # Warm Start
    seed_ratio: float = 0.8         # 80%种群从种子初始化
    random_ratio: float = 0.2       # 20%随机(保持多样性)
    # 约束
    max_depth: int = 4
    max_nodes: int = 20
    time_budget_minutes: int = 120  # 2小时预算
    # 逻辑/参数分离
    param_optuna_trials: int = 20   # 每个个体的Optuna参数搜索次数
    # 反拥挤
    anti_crowd_threshold: float = 0.6  # 相关性>0.6判定为拥挤

class GPEngine:
    """DEAP GP引擎（Warm Start + 岛屿模型 + 逻辑参数分离）

    进化循环:
    for generation in range(n_generations):
        for island in islands:
            1. 选择(tournament, size=3)
            2. 交叉(结构约束: 仅同层子树交换)
            3. 变异(窗口变异/字段替换/子树替换)
            4. 逻辑/参数分离评估:
               a. 提取结构模板(参数→占位符)
               b. Optuna TPE搜索最优参数(20次trial)
               c. 用最优参数计算适应度
            5. 反拥挤检查: 与已评估Top个体corr>0.6→惩罚
        if generation % migration_interval == 0:
            环形迁移: island[i]最优5个→island[(i+1)%4]
    """

    def __init__(self, config: GPConfig, dsl: FactorDSL,
                 gate: FactorGatePipeline, broker: SimBroker):
        self.config = config
        self.dsl = dsl
        self.gate = gate
        self.broker = broker  # 用于适应度回测

    def evolve(self, market_data: pd.DataFrame,
               existing_factors: dict[str, pd.DataFrame]) -> list[GPResult]:
        """运行GP进化，返回通过Gate的因子列表。

        这是闭环的核心——适应度函数调用SimBroker回测：

        def fitness(individual: ExprNode) -> float:
            # 1. 计算因子值
            factor_values = individual.evaluate(market_data)

            # 2. 快速Gate检查(G1-G4, 不做完整G1-G8)
            quick_check = gate.run_quick(factor_values)
            if not quick_check.passed:
                return -1.0  # 淘汰

            # 3. SimBroker快速回测(最近1年，月度等权Top15)
            sharpe = broker.quick_backtest(factor_values, period='1Y')

            # 4. 复杂度惩罚
            complexity = individual.node_count() / MAX_NODES

            # 5. 正交性奖励(与现有因子低相关 → 加分)
            max_corr = max_correlation(factor_values, existing_factors)
            novelty_bonus = max(0, 0.7 - max_corr)  # corr<0.7才有奖励

            # 适应度 = Sharpe × (1 - 0.1×complexity) + 0.3×novelty
            return sharpe * (1 - 0.1 * complexity) + 0.3 * novelty_bonus
        """
        ...

    def _quick_backtest(self, factor_values: pd.DataFrame) -> float:
        """快速回测: 最近1年，月度调仓，等权Top15

        为什么用SimBroker而不是IC:
        - IC是proxy，Sharpe是最终目标
        - 我们已有完整的SimBroker(含涨跌停/整手/滑点)
        - 避免"IC高但Sharpe差"的陷阱(LL-017教训)

        为什么只用1年:
        - 5年全量回测太慢(~10秒/因子)，GP需要评估数千次
        - 1年回测~2秒/因子，2小时可评估~3600个
        - 通过Gate后再做全量5年验证
        """
        ...
```

### 3.5 适应度函数设计（闭环核心）

```
适应度 = SimBroker_Sharpe × (1 - 0.1 × 复杂度) + 0.3 × 正交性奖励

其中:
- SimBroker_Sharpe: 最近1年，月度等权Top15回测的Sharpe Ratio
  - 含涨跌停检查、整手约束、volume_impact滑点
  - 这是最终目标的直接度量，不是IC proxy

- 复杂度: node_count / MAX_NODES ∈ [0, 1]
  - 节点越多越复杂，适度惩罚(0.1权重)
  - 来源: QuantaAlpha复杂度控制(去掉后ARR下降8.44%)

- 正交性奖励: max(0, 0.7 - max_corr_with_existing)
  - 与现有5个因子的Spearman相关性越低越好
  - corr < 0.7才有奖励，corr > 0.7直接归零
  - 来源: 我们的Gate G6标准
```

---

## 4. 组件3: Factor Gate Pipeline（G1-G8）

### 4.1 在闭环中的两个角色

1. **快速Gate（GP适应度中使用）**: 只跑G1-G4，<1秒/因子
2. **完整Gate（GP结束后候选因子使用）**: 跑G1-G8，~5秒/因子

```python
class FactorGatePipeline:
    """Factor Gate Pipeline（详见IMPLEMENTATION_MASTER §5.4）

    本闭环中有两种模式:
    """

    def run_quick(self, factor_values, forward_returns) -> GateResult:
        """快速模式(G1-G4): GP适应度中调用
        G1: 计算成功(无error)
        G2: 覆盖率>1000只
        G3: IC>0.015
        G4: t>2.0(宽松，完整Gate再用2.5)
        """
        ...

    def run_full(self, factor_name, factor_values, forward_returns,
                 existing_factors=None) -> GateResult:
        """完整模式(G1-G8): GP结束后候选因子验证
        G1-G4: 同上(G4用t>2.5)
        G5: 中性化后IC不归零
        G6: AST+Spearman去重(corr<0.7)
        G7: 滚动12月IC稳定性(CV<2.0)
        G8: 隐含换手率<200%年化
        """
        ...
```

---

## 5. 组件4: SimBroker反馈循环

### 5.1 快速回测（适应度函数用）

```python
class QuickBacktester:
    """GP适应度专用的快速回测器

    简化版SimBroker:
    - 期间: 最近1年(~250个交易日)
    - 策略: 月度等权Top15(与v1.1一致)
    - 滑点: volume_impact(与生产一致)
    - 涨跌停: 检查(与生产一致)
    - 整手约束: 检查(与生产一致)
    - 初始资金: 100万(与v1.1一致)

    优化:
    - 行情数据预加载到内存(~500MB)
    - 调仓日预计算(~12个)
    - 单次回测目标: <2秒
    """

    def backtest(self, factor_values: pd.DataFrame) -> float:
        """返回Sharpe Ratio。异常返回-999。"""
        ...
```

### 5.2 完整回测（候选因子验证用）

通过完整Gate G1-G8的因子，进行5年全量回测：
- 期间: 2021-01 ~ 2025-12
- 报告: 含年度分解/成本敏感性/Bootstrap CI
- 标准: Sharpe≥基线0.39(volume_impact基线)，CI下界>0
- 通过后进入 approval_queue 等待人工审批

---

## 6. 完整闭环流程

### 6.1 单次GP运行（每周一次，Task Scheduler触发）

```
T日 22:00 Task Scheduler触发 GP Pipeline
│
├── Step 1: 加载数据
│   ├── 行情数据(最近5年，从PG读取，缓存到内存)
│   ├── 现有因子值(5个Active因子，从factor_values读取)
│   └── 前向收益(计算好的forward_return)
│
├── Step 2: Warm Start初始化
│   ├── 从SEED_FACTORS生成80%种群变体
│   ├── 20%随机树填充
│   └── 分配到4个岛屿(每岛200个)
│
├── Step 3: GP进化 (2小时预算)
│   ├── 每代每岛: 选择→交叉→变异→评估
│   ├── 评估 = Optuna参数优化 → 快速Gate(G1-G4) → SimBroker 1年回测
│   ├── 适应度 = Sharpe×(1-0.1×complexity) + 0.3×novelty
│   ├── 每10代: 岛间环形迁移(5个精英)
│   └── 超时 → 停止进化但继续处理已有Top候选
│
├── Step 4: 完整Gate (G1-G8)
│   ├── 取Top 20因子(按适应度排序)
│   ├── 逐个跑完整Gate G1-G8
│   ├── 通过的因子数: 预期3-5个
│   └── 未通过原因写入mining_knowledge(失败经验)
│
├── Step 5: 全量回测验证
│   ├── 通过Gate的因子 → 5年全量SimBroker回测
│   ├── 生成完整回测报告(年度分解+CI+成本敏感性)
│   └── 标准: Sharpe≥基线, CI下界>0
│
├── Step 6: 写入结果
│   ├── 所有因子表达式 → mining_knowledge表(含AST hash)
│   ├── 通过因子 → approval_queue(等待人工审批)
│   └── 进化统计 → pipeline_runs表(成功率/最优适应度/耗时)
│
└── Step 7: 通知
    ├── 钉钉推送: "GP本周产出X个候选因子，最优Sharpe=Y"
    └── 前端Pipeline控制台更新
```

### 6.2 人工审批后的处理

```
人工审批 approve:
  1. 因子代码写入 factor_engine.py (新计算函数)
  2. 全历史因子值回填 → factor_values表
  3. 因子状态 → factor_lifecycle: candidate → active
  4. FACTOR_TEST_REGISTRY.md 更新
  5. 下次PT信号生成时纳入(如果决定扩展组合)

人工审批 reject:
  1. mining_knowledge记录rejection_reason
  2. GP下一轮进化时，注入reject原因到约束条件
  3. AST hash加入黑名单(避免进化出同样的因子)
```

### 6.3 跨轮次学习（知识积累）

```python
# mining_knowledge表记录每轮GP运行的关键信息
{
    "run_id": "gp_2026w14",
    "factor_expr": "ts_mean(cs_rank(div(amount, volume)), 20)",
    "ast_hash": "a3f8c2...",
    "fitness": 0.85,
    "gate_result": {"G1": "PASS", ..., "G8": "PASS"},
    "sharpe_1y": 0.62,
    "sharpe_5y": 0.48,
    "status": "approved" | "rejected" | "pending",
    "rejection_reason": null,
    "parent_seed": "amihud_20",     # 从哪个种子因子进化而来
    "generation": 35,                # 第几代产出
    "param_slots": {"w1": 20},       # 最优参数
}

# 下一轮GP初始化时:
# 1. 读取上轮Top因子作为新种子(扩展SEED_FACTORS)
# 2. 读取reject因子的AST hash作为黑名单
# 3. 读取失败原因，调整搜索方向(如"资金流因子覆盖率不足"→减少资金流算子权重)
```

---

## 7. 调度与运维

### 7.1 Task Scheduler注册

```
任务名: QuantMind-GP-Weekly
触发器: 每周日 22:00（市场休市，不影响PT）
动作: python D:\quantmind-v2\scripts\run_gp_pipeline.py
超时: 180分钟（GP 120分钟 + Gate/回测 60分钟）
失败策略: 重试1次(30分钟后)，仍失败→钉钉P1告警
日志: logs/gp_pipeline.log (structlog JSON)
```

### 7.2 资源限制

```
CPU: GP进化用multiprocessing, 限制8核(留4核给OS+PG)
内存: 行情数据缓存~500MB + GP种群~200MB + 回测~300MB = 总计<1.5GB
GPU: 不使用(GP是CPU计算)
磁盘: mining_knowledge每轮~1MB，年~52MB
PG: pipeline_runs表 + approval_queue表 + mining_knowledge表
```

### 7.3 监控指标

```
每周GP运行后记录:
- 因子产出率: 通过Gate / 总评估 (预期 0.1-1%)
- 最优适应度趋势: 如果连续4周无改善→告警
- 进化收敛性: 末代vs首代适应度提升幅度
- 新颖性: 通过因子与现有因子的平均相关性
- 时间效率: 实际耗时 / 预算2小时
```

---

## 8. 数据库表设计

### 8.1 新增表（DDL_FINAL.sql追加）

```sql
-- GP Pipeline运行记录
CREATE TABLE pipeline_runs (
    run_id VARCHAR(32) PRIMARY KEY,       -- 格式: gp_2026w14
    engine VARCHAR(20) NOT NULL,           -- 'gp' | 'bruteforce' | 'llm'
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'running',  -- running/completed/failed/timeout
    config JSONB NOT NULL,                 -- GPConfig序列化
    stats JSONB,                           -- {total_evaluated, passed_gate, best_fitness, ...}
    error_message TEXT
);

-- 审批队列
CREATE TABLE approval_queue (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(32) REFERENCES pipeline_runs(run_id),
    factor_name VARCHAR(100) NOT NULL,
    factor_expr TEXT NOT NULL,              -- DSL表达式字符串
    ast_hash VARCHAR(64) NOT NULL,
    gate_result JSONB NOT NULL,            -- G1-G8详细结果
    sharpe_1y DECIMAL(6,4),
    sharpe_5y DECIMAL(6,4),
    backtest_report JSONB,                 -- 完整回测报告
    status VARCHAR(20) DEFAULT 'pending',  -- pending/approved/rejected
    decision_by VARCHAR(50),               -- 'user' | 'auto'
    decision_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ
);

-- mining_knowledge已在DDL_FINAL.sql中设计，需追加列:
-- parent_seed, generation, param_slots (见§6.3)
```

---

## 9. 文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `backend/engines/mining/factor_dsl.py` | 新建 | 因子表达式语言(§2) |
| `backend/engines/mining/gp_engine.py` | 新建 | Warm Start GP引擎(§3) |
| `backend/engines/mining/quick_backtester.py` | 新建 | GP适应度快速回测(§5) |
| `backend/engines/factor_gate.py` | 新建 | Gate Pipeline G1-G8(§4, IMPL §5.4已设计) |
| `scripts/run_gp_pipeline.py` | 新建 | GP Pipeline入口脚本(§6) |
| `backend/app/models/pipeline_runs.py` | 新建 | DB模型 |
| `backend/app/models/approval_queue.py` | 新建 | DB模型 |
| `docs/QUANTMIND_V2_DDL_FINAL.sql` | 修改 | 追加2张表 |

---

## 10. 成败标准

### 10.1 技术标准（Sprint 1.16结束时验证）

- [ ] GP引擎2小时内完成50代×4岛×200个体的进化
- [ ] 产出 >= 10个通过快速Gate(G1-G4)的因子候选
- [ ] 其中 >= 3个通过完整Gate(G1-G8)
- [ ] 通过因子的5年全量Sharpe >= 基线0.39
- [ ] DSL支持 >= 20个算子
- [ ] Warm Start种群首代适应度 > 随机初始化首代适应度(验证Warm Start有效)

### 10.2 闭环标准（Sprint 1.17结束时验证）

- [ ] GP每周自动运行(Task Scheduler)，无人工干预
- [ ] 运行结果写入pipeline_runs + approval_queue
- [ ] 钉钉自动通知候选因子
- [ ] 下一轮GP自动加载上轮结果(种子扩展+黑名单)
- [ ] 连续2轮GP，第2轮的种群初始化包含第1轮的Top因子

### 10.3 业务标准（持续观察）

- [ ] 4周内GP产出至少1个被人工审批approve的新因子
- [ ] approve的因子IC > 0.02且与现有5因子corr < 0.7
- [ ] 如果4周0产出→需要调整GP参数或扩大DSL算子集
