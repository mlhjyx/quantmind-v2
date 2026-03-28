# T10前置研究: LLM Prompt模板 + DAG剪枝策略（深度版）

> Sprint 1.17 Task 10 产出（深度研读后更新）
> 来源: AlphaPROBE (arxiv 2602.11917, 20页) + AlphaAgent (KDD 2025, 10页) + AlphaForge (AAAI 2025)
> 目的: 为DeepSeek Idea Agent和GP Engine提供可落地的策略
> 全文PDF提取验证: pymupdf逐页读取

---

## 1. AlphaPROBE（20页全文精读）

### 1.1 核心创新: DAG导航范式

**两种现有范式的问题:**
- DFG(Decoupled Factor Generation): 因子独立生成，不利用因子间关系
- IFE(Iterative Factor Evolution): 只看父→子局部链，缺少全局拓扑视角

**AlphaPROBE方案**: 将因子池建模为DAG，节点=因子，边=进化关系，利用全局拓扑导航

### 1.2 Bayesian Factor Retriever（精确公式）

**目标**: 选择最有潜力产出优质后代的父因子

**贝叶斯框架**:
```
arg max_{F ∈ F} E[Qual(F_new) | parent(F_new) = F, D]
∝ P(F_new) × P(D | F_new)
```

**Prior P(F_new)** — 因子固有潜力:
- 对叶因子(无子代):
  ```
  P(F_new) ∝ Qual(F) × exp(-γ × R(F)) × exp(-ω × Depth(F))
  ```
  - Qual(F): 因子质量(|ICIR|)
  - R(F): 被选次数(惩罚过度利用)
  - Depth(F): DAG深度(惩罚过深的进化链)
  - γ=0.1, ω=0.1 最优(论文Fig.4 敏感性分析)

- 对非叶因子(有子代): 额外利用子代历史
  ```
  P(F_new) ∝ Qual(F) × PG(C(F)) × Spar(C(F))
  ```
  - PG: 子代vs父代的平均质量增益百分比
  - Spar: 子代多样性(子代间平均编辑距离)

**Likelihood P(D|F_new)** — 对因子池的贡献:
- 对叶因子: 三维多样性评估
  ```
  P(D|F_new) ∝ ValDiv(F) × SemDiv(F) × SynDiv(F)
  ```
  - ValDiv: 数值多样性 = 1 - avg(|Corr(F, f)|) for f in pool
  - SemDiv: 语义多样性 = σ(1 - CosSim(embed(F), embed(pool))) 用LLM解释的嵌入
  - SynDiv: 语法多样性 = avg(EditDistance(F,f)/(len(F)+len(f)))

**对QuantMind的落地**:
- 当前GP用锦标赛选择(随机3选最优)，可替换为Bayesian Retriever
- ValDiv对应我们的corr<0.7检查(Gate G2)
- SemDiv需要嵌入模型(Qwen3 Embedding-4B，本地可跑)
- 深度惩罚防止GP过度进化同一条路径

### 1.3 DAG-aware Factor Generator（3-Agent架构）

**三阶段工作流**:
1. **Analyst Agent**: 分析父因子的完整进化路径T(F_p)，产出m个修改策略{S}
   ```
   {S1, ..., Sm} = G_strategy(F_p, T(F_p))
   ```
2. **Execution Agent**: 将每个策略翻译为具体因子表达式
   ```
   F'_{c,i} = G_synth(F_p, S_i)
   ```
3. **Validator Agent**: 语法检查+约束验证，过滤非法表达式

**关键: 进化路径T(F_p)注入prompt**
- 不只给当前因子，给出从root到当前的完整祖先链
- 每步包含: 表达式+质量指标+变异操作类型
- LLM基于"进化历史学习"产出非冗余改进

**算子集（论文完整定义，20页附录）**:

时序算子(22个):
```
TsMean, TsSum, TsStd, TsMin, TsMax, TsMinMaxDiff, TsMaxDiff, TsMinDiff,
TsIr, TsVar, TsSkew, TsKurt, TsMed, TsMad, TsRank, TsCorr, TsCov,
TsDelta, TsDecayLinear, TsArgmax, TsArgmin, Ref
```

截面算子(1个): Rank

数学算子(12个):
```
Abs, Log, SLog1p, Sign, Add, Sub, Mul, Div, Pow,
Greater, Less, GetGreater, GetLess
```

数据字段: $open, $high, $low, $close, $vwap, $volume
常数: 整数(%d用于滚动窗口), 浮点(0.0001, 0.01, 0.0, 1.0, 2.0)

**对QuantMind的落地**:
- 我们的FactorDSL有28个算子，AlphaPROBE有35个 — 差距在TsMinMaxDiff/TsMaxDiff/TsMinDiff/TsArgmax/TsArgmin/SLog1p/Greater/Less等
- Sprint 1.18可补齐缺失算子
- 3-Agent架构可简化: 我们的Idea Agent=Analyst+Execution，FactorDSL.validate()=Validator

### 1.4 实验结果（CSI300/500/1000）

| 方法 | CSI300 IC | CSI300 ICIR | CSI500 IC | CSI500 SR | CSI300 MDD |
|------|-----------|-------------|-----------|-----------|------------|
| Alpha158 | 3.91% | 25.80% | 5.24% | 0.5682 | 25.29% |
| GP | 1.36% | 9.97% | 2.83% | 0.3421 | 39.06% |
| AlphaForge | 4.56% | 29.16% | 5.17% | 0.4257 | 35.34% |
| AlphaAgent | 4.27% | 25.66% | 5.50% | 0.3588 | 31.74% |
| R&D-Agent | 4.88% | 29.39% | 5.81% | 0.5165 | 31.38% |
| **AlphaPROBE** | **5.84%** | **39.02%** | **6.26%** | **0.8262** | **22.25%** |

**关键发现**:
- AlphaPROBE在所有指标上全面领先（IC/ICIR/SR/MDD）
- GP baseline最差(IC 1.36%)，说明纯GP不够，需要LLM辅助
- Bayesian Retriever比Random/Heuristic/MCTS Retriever都好（消融实验Table 2）
- DAG-aware Generator比CoT Generator好（5.84 vs 5.11 IC）

### 1.5 消融实验关键结论

- 去掉Prior(w/o Prior): IC从5.84→4.13（-29%），说明质量+深度惩罚很重要
- 去掉Likelihood(w/o Likelihood): IC从5.84→4.09（-30%），说明多样性评估很重要
- 去掉Topology penalty(w/o Topology): IC从5.84→5.06（-13%），拓扑惩罚有效但不是最关键
- 去掉NLF(非叶因子特殊处理): IC从5.84→5.15（-12%），利用子代历史有帮助

---

## 2. AlphaAgent（KDD 2025, 10页全文精读）

### 2.1 核心创新: 正则化探索对抗Alpha衰减

**问题**: GP/RL产出的因子容易过拟合→实盘快速衰减(alpha decay)
**方案**: 3-Agent架构 + 探索正则化 + AST去重

### 2.2 三Agent架构

1. **Hypothesis Agent**: 生成市场假设（经济学叙事）
   - 输入: 市场特征描述 + 已有因子历史 + 失败经验
   - 输出: 半结构化假设（如"三角形态突破+成交量确认"）

2. **Factor Agent**: 将假设翻译为因子表达式
   - Operator Library: 预定义算子库（类似我们的FactorDSL）
   - 解析流程: H(假设) × X(数据字段) → F(表达式树)
   - 多候选生成 + 复杂度/对齐度过滤
   - **知识库**: 维护成功+失败案例，失败按模式分类
   - 一致性评分: C(h,d,f) = α×c1(h,d) + (1-α)×c2(d,f)
     - c1: 假设→描述对齐度
     - c2: 描述→表达式对齐度

3. **Eval Agent**: 多维评估
   - 预测能力(IC/ICIR)
   - 回测表现(Sharpe/MDD)
   - 稳定性(年度IC方差)
   - AST去重(编辑距离<阈值视为重复)

### 2.3 探索正则化（核心公式）

```
ER(f, h) = β1 × S(f) + β2 × C(h,d,f) + β3 × log(1 + |F_f|)
```
- S(f): 原创性分数（与已有因子的差异度）
- C(h,d,f): 假设一致性分数
- |F_f|: 因子家族大小（鼓励从小家族探索）

**对QuantMind的关键启示**: β3项log(1+|F_f|)鼓励探索不同家族的因子，避免在同一方向过度挖掘

### 2.4 实验结果

| 方法 | CSI500 IC | CSI500 AR | CSI500 MDD | S&P500 AR | S&P500 MDD |
|------|-----------|-----------|------------|-----------|------------|
| LightGBM | 0.0120 | -1.18% | -18.97% | -2.64% | -21.17% |
| AlphaForge | 0.0146 | 3.45% | -17.67% | 2.45% | -10.91% |
| DeepSeek-R1 best-of-10 | 0.0132 | 1.58% | -14.95% | 2.75% | -15.34% |
| **AlphaAgent** | **0.0212** | **11.00%** | **-9.36%** | **8.74%** | **-9.10%** |

**关键发现**:
- AlphaAgent CSI500 AR=11%，远超所有baseline（第二名Alpha158仅4.96%）
- DeepSeek-R1作为AlphaAgent base LLM效果最好（ICIR 0.0615 > GPT-3.5 0.0410 > Qwen-Plus 0.0523）
- Alpha decay验证: GP因子年度IC从2020到2024持续下降，AlphaAgent保持稳定
- **重要**: 纯DeepSeek-R1 best-of-10只有IC=0.0132，但AlphaAgent用同模型达到0.0212 → 3-Agent+正则化的框架增益巨大

### 2.5 LLM模型对比（Fig.7）

| Base LLM | IC_single | ICIR | AR | MDD |
|----------|-----------|------|-----|-----|
| GPT-3.5-turbo | 中 | 0.0410 | 5.2% | -12.5% |
| Qwen-Plus | 中高 | 0.0523 | 7.1% | -10.2% |
| **DeepSeek-R1** | **最高** | **0.0615** | **9.19%** | **-6.50%** |

**验证了我们R7的选型**: DeepSeek-R1是最佳Idea Agent LLM

---

## 3. AlphaForge（AAAI 2025）核心补充

### 3.1 动态因子组合（关键细节）

- Generator-Predictor神经网络: Predictor学习因子适应度(代理模型)，Generator最大化Predictor输出+多样性损失
- 逆波兰表示法(RPN)编码因子为one-hot矩阵
- **因子池最优~10个**: 非单调关系，超过10个因子后性能下降
- 因子入池门槛: IC>3%, ICIR>0.1
- 动态日度权重: 每日线性回归重新确定Top-N因子的最优权重

**对QuantMind**: 当前等权Top15可能偏多，验证Top10 vs Top15效果

---

## 4. 升级版LLM Prompt模板（基于全文精读）

### 4.1 Idea Agent Prompt（融合AlphaPROBE 3-Agent + AlphaAgent知识库）

```
[System] 你是A股量化因子研究专家。你将基于市场假设生成因子表达式。

[Context]
## 市场特征
A股散户占比>60%，T+1交易，涨跌停10%/ST 5%，北向资金影响显著

## 算子库（FactorDSL可用算子）
时序: {ts_operators}
截面: {cs_operators}
数学: {math_operators}
数据: open, high, low, close, volume, amount, returns

## 已有Active因子（避免重复）
{active_factors_with_ic_and_corr_matrix}

## 失败经验库（避免重蹈覆辙）
{failed_factors_categorized_by_failure_mode}
- IC不足(<0.02): {list}
- 相关性过高(>0.7): {list}
- 中性化后衰减>50%: {list}
- 经济学假设不成立: {list}

## 进化历史（DAG祖先链，如有）
{evolution_trace_from_root_to_current}

[Task]
生成{n}个新因子假设。每个必须：
1. 有明确的经济学假设（市场现象→投资者行为→定价偏差→可预测性）
2. 使用上述算子库中的算子，表达式必须语法合法
3. 与已有因子相关性预期<0.7
4. 避免失败经验库中的已知失败模式
5. 优先探索未充分挖掘的因子家族（流动性/资金流/行为金融）

[Output Format] 严格JSON，不要其他内容:
[{
  "name": "factor_name",
  "expression": "cs_rank(ts_corr(close, volume, 20))",
  "hypothesis": "价量相关性反映知情交易者行为...",
  "expected_ic_direction": "negative",
  "expected_ic_range": [0.02, 0.05],
  "category": "价量/流动性/资金流/基本面/行为",
  "novelty_explanation": "与已有因子xxx的区别在于..."
}]
```

### 4.2 DAG-aware Evolution Prompt（AlphaPROBE Analyst+Execution合并）

```
[System] 你是量化因子进化专家。基于因子的进化历史提出改进方案。

[Evolution Trace]
Generation 0 (Root): {expr_0} | IC={ic_0} | ICIR={icir_0}
  ↓ 变异类型: {mutation_0}
Generation 1: {expr_1} | IC={ic_1} | ICIR={icir_1}
  ↓ 变异类型: {mutation_1}
Generation 2 (Current): {expr_2} | IC={ic_2} | ICIR={icir_2}

[Quality Trend] IC: {ic_0}→{ic_1}→{ic_2} ({trend})
[Bottleneck] {bottleneck_analysis}
[Siblings Performance] 同代其他分支: {sibling_exprs_with_ic}

[Task] 提出3个改进方向，按优先级排序:
1. 结构改进（增加/替换算子节点）
2. 参数调优（窗口期/阈值变化）
3. 跨家族嫁接（与其他高IC因子的子树组合）

每个方向给出具体的DSL表达式和预期改进理由。

[Output] JSON格式:
[{
  "strategy": "结构改进",
  "expression": "...",
  "rationale": "...",
  "expected_ic_improvement": "+0.5%"
}]
```

### 4.3 Factor Evaluation Prompt（AlphaAgent Eval Agent风格）

```
[System] 你是量化因子评估专家，严格评分。

[Factor]
表达式: {expression}
经济学假设: {hypothesis}

[Statistics]
IC={ic}, ICIR={icir}, t={t_stat}, 半衰期={half_life}天
中性化后IC={neutralized_ic}, 衰减率={decay_rate}%
与Active因子最高相关性: {max_corr} (with {corr_factor_name})

[Gate Status]
G1(|IC|>0.02): {g1} | G2(corr<0.7): {g2} | G3(t>2.0): {g3}
G4(中性化衰减<50%): {g4} | G5(方向一致): {g5}

[Evaluation Dimensions] (1-5分)
1. 经济学可解释性: 假设是否有理论支撑？A股特有吗？
2. 统计显著性: t值是否可靠？BH-FDR校正后呢？
3. 互补性: 与已有因子提供新信息吗？
4. 衰减风险: 半衰期合理吗？Alpha decay预期？
5. 实盘可执行性: 流动性/换手成本/数据可得性

[Output] JSON:
{
  "scores": {"explainability": X, "significance": X, "complementarity": X, "decay_risk": X, "executability": X},
  "total_score": X,
  "verdict": "APPROVE/REJECT/HOLD",
  "reasoning": "...",
  "improvement_suggestions": ["..."]
}
```

---

## 5. DAG剪枝策略（升级版，基于AlphaPROBE公式）

### 5.1 因子DAG图数据结构

```python
@dataclass
class FactorDAGNode:
    expr: str
    ast_hash: str
    parent_hash: str | None
    mutation_type: str          # crossover/mutate_window/mutate_operator/wrap/graft
    generation: int
    quality: float              # |ICIR|
    retrieval_count: int        # 被选为父节点的次数
    depth: int                  # DAG中从root的深度
    children_hashes: list[str]  # 子因子hash列表

class FactorDAG:
    nodes: dict[str, FactorDAGNode]  # hash → node

    def get_trace(self, hash: str) -> list[FactorDAGNode]:
        """获取从root到当前节点的完整祖先链"""

    def get_retrieval_score(self, hash: str) -> float:
        """Bayesian Retriever得分"""
        node = self.nodes[hash]
        if not node.children_hashes:  # 叶因子
            prior = node.quality * exp(-0.1 * node.retrieval_count) * exp(-0.1 * node.depth)
            likelihood = self._val_div(hash) * self._syn_div(hash)
        else:  # 非叶因子
            children = [self.nodes[h] for h in node.children_hashes]
            pg = mean([(c.quality - node.quality) / max(node.quality, 0.01) for c in children])
            spar = mean_pairwise_edit_distance(children)
            prior = node.quality * pg * spar
            likelihood = prior  # 非叶因子prior已包含子代信息
        return prior * likelihood

    def prune_subtree(self, hash: str, quality_threshold: float):
        """剪除低质量子树"""
        node = self.nodes[hash]
        if node.quality < quality_threshold and all(
            self.nodes[c].quality < quality_threshold for c in node.children_hashes
        ):
            # 整个子树质量都低于阈值，剪除
            self._remove_subtree(hash)
```

### 5.2 子树级黑名单（升级AlphaPROBE版）

```python
# 当前QuantMind: 单因子AST hash黑名单
blacklist = {hash1, hash2, ...}

# 升级: 基于DAG的子树模式黑名单
subtree_patterns = [
    {
        "pattern_hash": "ts_corr(close, volume, *)",
        "reason": "价量相关系列5个变体全部G1 FAIL",
        "affected_nodes": 5,
        "banned_since": "run_2026_03_28"
    }
]

# 判断逻辑: 不只检查精确hash，还检查子树模式匹配
def is_blacklisted(expr: ExprNode, blacklist: set, subtree_patterns: list) -> bool:
    if expr.to_ast_hash() in blacklist:
        return True
    for pattern in subtree_patterns:
        if expr.contains_subtree_pattern(pattern["pattern_hash"]):
            return True
    return False
```

---

## 6. 落地优先级（更新版）

| 项目 | 优先级 | 落地Sprint | 复杂度 | 依据 |
|------|--------|-----------|--------|------|
| Idea Agent 3个升级prompt模板 | P0 | 1.17(本Sprint) | 低 | AlphaAgent验证3-Agent有效 |
| 失败经验库注入prompt | P0 | 1.17 | 低 | AlphaAgent知识库是核心差异化 |
| 子树级黑名单 | P1 | 1.18 | 中 | AlphaPROBE DAG剪枝 |
| DSL算子补齐(+7个AlphaPROBE算子) | P1 | 1.18 | 低 | TsMinMaxDiff/TsArgmax等 |
| 因子DAG图数据结构 | P1 | 1.18 | 中 | AlphaPROBE核心 |
| Bayesian Retriever(替代锦标赛选择) | P1 | 1.18-1.19 | 中 | 消融实验证明+29% IC提升 |
| 探索正则化ER(f,h) | P2 | 1.19 | 中 | AlphaAgent对抗alpha decay |
| 语义多样性SemDiv(Qwen3嵌入) | P2 | 1.19 | 中 | 需要本地嵌入模型 |
| 动态因子权重(AlphaForge) | P2 | 1.20+ | 高 | 日度重组合替代等权 |
| Predictor代理模型(AlphaForge) | P3 | 1.20+ | 高 | 替代QuickBacktester |
