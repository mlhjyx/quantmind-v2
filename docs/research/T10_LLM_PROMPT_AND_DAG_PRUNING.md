# T10前置研究: LLM Prompt模板 + DAG剪枝策略

> Sprint 1.17 Task 10 产出
> 来源: AlphaPROBE (arxiv 2602.11917) + AlphaBench (ICLR 2026) + AlphaForge (AAAI 2025)
> 目的: 为Sprint 1.17 DeepSeek Idea Agent和GP Engine提供可落地的策略

---

## 1. AlphaPROBE核心思想（DAG剪枝）

**核心创新**: 将因子挖掘重构为DAG(有向无环图)导航问题。
- 节点=因子表达式, 边=进化关系(父→子变异/交叉)
- 因子不再是孤立的，每个因子有"祖先链"(ancestral trace)

**三组件架构**:
1. **Bayesian Factor Retriever**: 贝叶斯后验概率选择探索/利用平衡点
   - 不是随机选种子，而是基于历史表现的后验概率挑选最有潜力的父节点
   - **可落地**: GP Engine的`select_parent()`可用Thompson Sampling替代锦标赛选择
2. **DAG-aware Factor Generator**: 利用因子的完整祖先链生成上下文感知的非冗余优化
   - LLM看到的不只是"生成一个好因子"，而是"基于这个因子家族的进化历史，生成下一代"
   - **可落地**: Idea Agent的prompt注入因子族谱(parent→child变异历史)
3. **DAG Pruning**: 剪掉低价值子图，防止搜索空间爆炸
   - 以ICIR为质量度量，低于阈值的子树整体剪除
   - **可落地**: GP Engine的黑名单机制升级为子树级剪枝(不只是单因子黑名单)

**关键参数(论文设置)**:
- 因子池容量: 50
- 每轮生成因子数: 5
- 因子长度阈值: 40(算子节点数)
- 质量度量: |ICIR|在训练期
- LLM: DeepSeek V3.1 + Qwen3 Embedding-4B

**对QuantMind的启示**:
- 当前GP Engine的跨轮次学习(Sprint 1.17 T6)已实现种子注入+黑名单，但缺少DAG结构
- Sprint 1.18可升级: 维护因子DAG图，记录每个因子的父节点和变异操作
- Bayesian Retriever可替代Thompson Sampling用于引擎选择(Step 3)

---

## 2. AlphaForge核心思想（动态组合）

**核心创新**: 因子权重不固定，每日动态重组合。

**两阶段架构**:
1. **Mining Stage**: Generator-Predictor网络
   - Predictor: 代理模型学习因子适应度(类似QuickBacktester的角色)
   - Generator: 深度学习网络最大化Predictor输出+多样性损失
   - 因子用逆波兰表示法(RPN)编码为one-hot矩阵
2. **Combination Stage**: 动态权重
   - 每日评估因子近期IC/ICIR/RankIC
   - 选Top-N满足阈值的因子
   - 线性回归确定当日最优权重 → "Mega-Alpha"
   - 因子池最优约10个(非越多越好)

**关键参数**: IC>3%, ICIR>0.1作为因子入池门槛

**对QuantMind的启示**:
- 当前CompositeStrategy用固定等权，可升级为AlphaForge的动态权重(Sprint 1.19+)
- Predictor-Generator范式可启发GP适应度函数: 训练一个轻量代理模型预测因子质量，替代每次都跑QuickBacktester
- 因子池最优10个 → 我们的Top15可能偏多，验证时对比Top10/Top15

---

## 3. AlphaBench基准发现（LLM Prompt设计）

**三个核心任务基准**:
1. Factor Generation: LLM直接生成因子表达式
2. Factor Evaluation: LLM判断因子质量(IC/方向/稳定性)
3. Factor Searching: LLM在搜索空间中导航找最优因子

**关键发现**: LLM在Factor Generation上表现最好，在Searching上最差(需要结合搜索算法如GP)

---

## 4. 可落地产出: LLM Prompt模板

### 4.1 Idea Agent Prompt模板（因子假设生成）

```
你是A股量化因子研究专家。基于以下上下文生成{n}个新因子假设：

**市场特征**: A股散户占比高(>60%)，T+1交易，涨跌停10%，ST 5%
**已有因子**: {active_factors_with_ic}
**失败因子历史**: {failed_factors_with_reasons}
**因子家族树**: {parent_child_evolution_history}

要求:
1. 每个因子必须有经济学解释（市场现象→投资者行为→定价偏差→可预测性）
2. 使用FactorDSL算子集: {available_operators}
3. 与已有因子相关性<0.7
4. 避免已知失败模式: {blacklist_patterns}

输出格式（JSON）:
[{
  "name": "factor_name",
  "expression": "cs_rank(ts_corr(close, volume, 20))",
  "hypothesis": "经济学解释...",
  "expected_ic_direction": "positive/negative",
  "expected_ic_range": [0.02, 0.05],
  "category": "价量/流动性/资金流/基本面/行为",
  "novelty_vs_existing": "与xxx因子的区别..."
}]
```

### 4.2 DAG-aware Evolution Prompt（基于祖先链的进化）

```
基于以下因子进化历史，生成改进版本：

**当前因子**: {factor_expr} (IC={ic}, ICIR={icir})
**祖先链**:
  Gen 0: {ancestor_0} (IC={ic_0})
  Gen 1: {ancestor_1} (IC={ic_1}, 变异: {mutation_type})
  Gen 2: {current} (IC={ic_2})

**进化趋势**: IC从{ic_0}→{ic_2}，{trend_description}
**瓶颈分析**: {bottleneck}（如: 窗口期过短/算子过于简单/缺少截面标准化）

请提出3个改进方向，每个用FactorDSL表达式:
1. 结构改进（增加/替换算子）
2. 参数调优（改变窗口期/阈值）
3. 组合创新（与其他高IC因子子树嫁接）
```

### 4.3 Factor Evaluation Prompt（因子质量判断）

```
评估以下因子的投资价值：

**表达式**: {expression}
**统计指标**: IC={ic}, ICIR={icir}, t={t_stat}, 半衰期={half_life}天
**Gate状态**: G1={g1} G2={g2} G3={g3} G4={g4} G5={g5}

请从以下维度评估（1-5分）:
1. 经济学可解释性
2. 统计显著性
3. 与现有因子的互补性
4. 预期生命周期
5. 实盘可执行性（流动性/换手成本）

总体建议: APPROVE / REJECT / HOLD（需更多数据）
理由: ...
```

---

## 5. 可落地产出: DAG剪枝策略

### 5.1 子树级黑名单（升级当前单因子黑名单）

```python
# 当前: 只黑名单单个因子的AST hash
blacklist = {ast_hash_1, ast_hash_2, ...}

# 升级: 黑名单包含失败因子的关键子树
# 如果 cs_rank(ts_corr(close, volume, N)) 系列全部FAIL
# 则黑名单 ts_corr(close, volume, *) 子树模式
subtree_blacklist = [
    {"pattern": "ts_corr(close, volume, *)", "reason": "价量相关系列全部IC<0.02"},
    {"pattern": "ts_mean(amount, *)/ts_mean(amount, *)", "reason": "自身比值恒=1"},
]
```

### 5.2 Bayesian Retriever（替代均匀随机选种子）

```python
# 当前: GP随机选父节点做交叉/变异
parent = random.choice(population)

# 升级: Thompson Sampling选父节点
# 每个因子维护Beta(alpha, beta)分布
# alpha = 产出优质后代次数, beta = 产出低质后代次数
parent = max(population, key=lambda f: np.random.beta(f.alpha, f.beta))
```

### 5.3 因子DAG图维护

```python
@dataclass
class FactorDAGNode:
    expr: str
    ast_hash: str
    parent_hash: str | None  # 父因子hash
    mutation_type: str        # crossover/mutate_window/mutate_operator/...
    generation: int
    fitness: float
    gate_status: str          # PASS/FAIL/PENDING

# DAG可用于:
# 1. 祖先链查询 → LLM prompt注入
# 2. 子树剪枝 → 整个失败家族移除
# 3. 成功模式挖掘 → 哪些变异操作产出最多PASS因子
```

---

## 6. Sprint落地优先级

| 项目 | 优先级 | 落地Sprint | 复杂度 |
|------|--------|-----------|--------|
| Idea Agent 3个prompt模板 | P0 | 1.17(本Sprint) | 低 |
| 子树级黑名单 | P1 | 1.17(T6跨轮次学习) | 中 |
| Thompson Sampling选父节点 | P1 | 1.18 | 中 |
| 因子DAG图维护 | P2 | 1.18-1.19 | 高 |
| 动态因子权重(AlphaForge) | P2 | 1.19+ | 高 |
| Predictor代理模型 | P3 | 1.20+ | 高 |
