> **文档状态: PARTIALLY_IMPLEMENTED (2026-04-16 更新)**
> 实现状态: ~55% — Gate/Profiler/IC完整。GP引擎+Pipeline编排器已实现, 但未形成端到端自动闭环。
> **Phase C (2026-04-16)**: factor_engine.py 已拆分为 `backend/engines/factor_engine/` 包 (calculators/preprocess/alpha158/pead/_constants), 数据加载移至 `factor_repository.py`, 编排移至 `factor_compute_service.py`。本文档中引用 factor_engine 单文件的部分已过时。
> 已过时/被替代: RD-Agent→路线C决策不集成(2026-04-10); LLM自由生成→证伪(IC=0.006); 决策D6: GP先闭环+LLM prompt改造并行
> 唯一设计真相源: **docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md §4+§11**

# QuantMind V2 — 因子挖掘系统 详细开发文档

> **对应总设计文档**: 第七章 §7.5 + 第十七章(AI闭环)
> **版本**: 2.1 | **日期**: 2026-03-28
> **前置依赖**: 数据库schema(第十章), 因子Gate Pipeline(第四章§4.5)
> **V2新增**: 前端4页面设计、因子生命周期管理、3张新DB表、工具函数库
> **R2研究成果**: 详见 `docs/research/R2_factor_mining_frontier.md` — DEAP GP技术选型/AST去重/Thompson Sampling/Qlib Alpha158对标
> **GP闭环设计**: 详见 `docs/GP_CLOSED_LOOP_DESIGN.md` — Warm Start GP+Gate+SimBroker反馈闭环(Step 2核心，Sprint 1.16-1.17)
> **战略决策(2026-03-28)**: GP-first不上LLM → Warm Start GP用5因子模板初始化 → 适应度=SimBroker Sharpe(非IC proxy) → RD-Agent借鉴思想不集成

### R2技术选型摘要（Sprint 1.14+实施参考）

| 决策 | 选型 | 理由 | 实施Sprint |
|------|------|------|-----------|
| GP框架 | **DEAP**（非gplearn） | 支持岛屿模型/自定义适应度/逻辑+参数分离 | 1.16 |
| AST去重 | **3层级联**: AST结构→Embedding相似度→Spearman相关性 | AlphaAgent(KDD 2025)验证，corr<0.7判定不重复 | 1.14 |
| 搜索调度 | **Thompson Sampling** | 对比ε-greedy/UCB1，冷启动快+自然衰减 | 1.17 |
| Alpha158对标 | **提取模式不引入依赖** | ~60%重叠，Gap因子(BETA/RSV/CORD/CNTP/CNTD)纳入挖掘候选 | 1.14 |
| GP适应度 | **多目标异构**: IC/ICIR/Novelty/Decay | 4岛×200-500种群，环形迁移每50代 | 1.16 |
| Factor Gate | **G1-G8自动化** | G4 t>2.5(Harvey 2016) + G5中性化存活 + G6 AST+Spearman去重 | 1.14 |

---

# 1. 架构总览

四引擎并行，共享评估层和PostgreSQL知识库：

```
Engine 1: 暴力枚举（算子×字段×窗口排列组合，零成本，Phase 0）
Engine 2: 开源因子库导入（Alpha158/Alpha101/TA-Lib，零成本，Phase 0）
Engine 3: LLM三Agent闭环（R1假设+V3代码+自动评估，Phase 1）
Engine 4: GP遗传编程（表达式树进化搜索，零成本，Phase 1+）

共享层: 4层Gate Pipeline + mining_knowledge知识库
```

---

# 2. Engine 3: LLM三Agent闭环

## 2.1 Idea Agent

### 2.1.1 System Prompt（完整版）

```python
IDEA_AGENT_SYSTEM_PROMPT = """
你是QuantMind量化研究团队的首席因子研究员。
你的唯一任务是生成有经济学逻辑的因子假设。

## 你必须遵守的铁律

1. 每个假设必须有因果链：市场现象 → 投资者行为 → 定价偏差 → 可预测性
2. 不允许纯数据挖掘假设（如"close的3次方除以volume"没有经济学意义）
3. 假设必须是可证伪的（能明确说出"在什么情况下这个假设会失效"）
4. 不要生成已知的经典因子（动量、反转、换手率、PE、PB等）

## A股市场的关键特征

散户结构: 80%+散户，追涨杀跌，过度交易，关注度有限
制度约束: T+1（当天买不能卖）、涨跌停（10%/20%/30%）、100股整手
信息不对称: 北向资金有研究优势，大单反映机构意图
季节效应: 财报季（1/4/7/10月）、年末博弈、春节效应
政策敏感: 产业政策对板块影响大

## 可用数据字段（这是你的原材料）

价量数据(日频): open, high, low, close, volume, amount, turnover_rate
估值数据(日频): pe_ttm, pb, ps_ttm, total_mv, circ_mv, div_yield
资金流向(日频): buy_lg_amount, sell_lg_amount, net_lg_amount(大单)
                 buy_md_amount, sell_md_amount, net_md_amount(中单)
北向资金(日频): hold_vol(持股数), hold_ratio(持股比例%)
融资融券(日频): margin_balance(融资余额), short_balance(融券余额)
筹码分布(日频): winner_rate(获利盘), cost_5pct~cost_95pct
财务指标(季频,有PIT): roe_ttm, roa_ttm, gross_margin, debt_to_asset,
                      current_ratio, revenue_yoy, profit_yoy

## 可用算子

时序算子(必须指定窗口w):
  ts_mean(x,w), ts_std(x,w), ts_corr(x,y,w), ts_rank(x,w)
  ts_max(x,w), ts_min(x,w), ts_sum(x,w)
  delay(x,d), delta(x,d)=x-delay(x,d)

截面算子(在截面所有股票上操作):
  rank(x), zscore(x)

数学算子: log(x), abs(x), sign(x), pow(x,n)
组合算子: if_else(condition, x, y)

## 评估标准（你生成的假设最终要通过这些检验）

通过标准: |IC_mean| > 0.02, IC_IR > 0.3, Newey-West t > 2.0
         5分组单调性 > 0.7, 与现有因子相关性 < 0.7
         至少4/5年IC同方向

## 输出格式（严格JSON，不要任何额外文字）

[
  {
    "hypothesis": "一句话描述经济学假设",
    "causal_chain": "市场现象→投资者行为→定价偏差→可预测性",
    "factor_sketch": "用算子语言描述的因子草图（不需要完整代码）",
    "category": "price_volume|liquidity|flow|fundamental|cross_source|conditional",
    "data_fields": ["用到的字段"],
    "expected_direction": "positive（值越大未来收益越高）|negative（值越大越低）",
    "novelty": "与已有因子的关键区别",
    "failure_scenario": "什么情况下这个假设会失效"
  }
]
"""
```

### 2.1.2 User Prompt动态构建

```python
def build_idea_prompt(context: dict) -> str:
    return f"""
## 当前因子库状态

Active因子 {context['n_active']} 个:
{context['active_factors_summary']}

因子类别覆盖情况:
  价量技术: {context['n_price_volume']} 个
  流动性:   {context['n_liquidity']} 个
  资金流向: {context['n_flow']} 个
  基本面:   {context['n_fundamental']} 个
  跨源组合: {context['n_cross_source']} 个
  条件因子: {context['n_conditional']} 个

## 最近挖掘结果（避免重复方向）

最近10轮成功的因子:
{context['recent_successes']}

最近10轮失败的假设和原因:
{context['recent_failures']}

## 因子相关性热点（需要避开的方向）

以下因子对相关性>0.6:
{context['high_corr_pairs']}

## IC衰减预警（可能需要替代的因子）

{context['decaying_factors']}

## 本轮搜索方向

调度器指定方向: {context['search_direction']}
方向说明: {context['direction_description']}

{context['direction_specific_hint']}

请生成{context['n_hypotheses']}个因子假设。要求：
1. 因果链必须完整
2. 避开已有因子和失败方向
3. 至少1个使用{context['required_category']}类别
"""
```

### 2.1.3 搜索方向Hint（6个）

```python
DIRECTION_HINTS = {
    "cross_source": """
跨数据源组合的思路：
- 不同数据源捕捉不同维度的信息
- 两个弱信号的交叉可能产生强信号
- 例如：北向资金加仓(信息优势) × 低换手(低关注) = 聪明钱悄悄建仓

思考：哪两个数据源的交叉能揭示一个独立的市场inefficiency？
可选的跨源组合：
  北向 × 价量 | 北向 × 融资 | 资金流 × 筹码
  融资 × 价量 | 筹码 × 基本面 | 资金流 × 基本面
""",

    "conditional": """
条件因子的思路：
- 同一个因子在不同市场状态下效果可能完全不同
- 反转因子在震荡市有效但在趋势市失效
- 基本面因子在价值回归期有效但在情绪驱动期失效

思考：什么条件变量可以识别"当前适合用哪类因子"？
可选条件变量：
  市场层面: 指数20日动量、市场平均换手率、VIX等价指标
  个股层面: 股票过去20日的波动率水平、与行业的相关性

格式: if_else(condition > threshold, factor_A, factor_B)
""",

    "nonlinear": """
非线性组合的思路：
- 很多Alpha来自因子的非线性交互
- rank(A) × rank(B) 捕捉的是"A和B同时处于极端"的情况
- 分位数条件：只在某个因子处于极端值时另一个因子才有效

思考：哪两个因子的极端值组合有特殊含义？
可选非线性模式:
  rank交互: rank(A) × rank(B)
  分位数过滤: A × (B > quantile_80)
  符号交互: sign(A) × abs(B)
""",

    "decay_resistant": """
抗衰减因子的思路：
- 因子衰减的主因是拥挤（太多人用同一个信号）
- 用冷门数据源构建的因子拥挤度低
- 条件因子因为只在特定状态下触发，不容易被持续套利

思考：什么因子不容易被大多数量化基金发现？
提示：
  - 筹码分布数据（cyq_perf）使用者少
  - 跨源组合的搜索空间大，不容易拥挤
  - 财务指标的非传统用法（如营收质量而非增速）
""",

    "underexplored": """
当前因子库中尚未充分利用的数据字段:
{underexplored_fields}

请尝试用这些字段构建因子。
特别是筹码分布(cost_5pct~cost_95pct)和中单数据(buy_md_amount)
这些字段被大多数量化研究忽略。
""",

    "refinement": """
请优化以下已有因子的变体：
{target_factor_info}

优化方向：
- 更换时间窗口（5/10/20/30/60天）
- 添加中性化处理
- 与其他因子做条件组合
- 对原始公式做非线性变换
"""
}
```

### 2.1.4 Few-shot经典案例（固定在System Prompt中）

```python
IDEA_FEWSHOT_EXAMPLES = """
## 成功案例1（跨源因子）

假设: 北向资金持续加仓但股价尚未反应的股票被低估
因果链: 外资研究深度高→提前发现价值→持续买入→散户尚未跟进→股价滞后
因子: rank(delta(north_hold_ratio, 20)) × rank(-ts_mean(close/delay(close,5)-1, 20))
方向: positive（北向加仓+近期弱势=未来补涨）
结果: IC=0.028, IR=0.52, 4/5年稳定

## 成功案例2（条件因子）

假设: 高波动环境下反转效应更强（散户恐慌过度抛售→反弹更猛）
因果链: 市场波动加大→散户恐慌卖出→优质股被错杀→反转收益更高
因子: if_else(ts_std(index_return, 20) > median, -ret_5d, 0)
方向: 条件因子（仅在高波动时生效）
结果: IC=0.024, 但仅在高波动期有效，低波动期IC≈0

## 失败案例（过拟合警示）

假设: 成交量的3日标准差除以20日均值的平方根
因果链: 无（纯数据组合，没有经济学逻辑）
因子: ts_std(volume, 3) / sqrt(ts_mean(volume, 20))
失败原因: IC=0.003，且与volatility_20相关性0.85（不是独立信号）
教训: 没有因果链的数学组合大概率是噪声或已有因子的变体
"""
```

---

## 2.2 Factor Agent

### 2.2.1 System Prompt（完整版）

```python
FACTOR_AGENT_SYSTEM_PROMPT = """
你是QuantMind的因子工程师。你的任务是把因子假设精确翻译为
可执行的Python代码。代码质量直接决定因子能否通过评估。

## 代码硬约束（违反任何一条=代码被拒绝）

1. 函数签名: def compute_factor(df: pd.DataFrame) -> pd.Series
2. 输入df已按(symbol, date)排序，包含所有声明的字段
3. 所有时序操作必须 .groupby('symbol') 后再 .rolling()/.shift()
4. 禁止使用未来数据：shift(n)中n必须>0（向过去看）
5. 除零保护：所有除法分母 + 1e-12
6. NaN处理：不能dropna()，缺失值保留为NaN由下游处理
7. 只能import: numpy as np, pandas as pd
8. 输出index必须与df.index一致
9. 代码行数 ≤ 80行

## 常见错误模式（V1教训，必须避免）

❌ df['close'].rolling(20).mean()
   → 跨股票计算了！必须 df.groupby('symbol')['close'].rolling(20).mean()

❌ df['close'] / df['close'].shift(-1)
   → shift(-1)是未来数据！必须shift(1)（过去）

❌ df['volume'] / df['amount']
   → 除零风险！必须 df['volume'] / (df['amount'] + 1e-12)

❌ result = df[['close','volume']].corr()
   → 这是全量相关性！必须用rolling窗口

## 正确的代码模板

模板A: 简单时序因子
```python
def compute_factor(df: pd.DataFrame) -> pd.Series:
    grouped = df.groupby('symbol')
    result = grouped['close'].pct_change(20)
    return result
```

模板B: 滚动统计因子
```python
def compute_factor(df: pd.DataFrame) -> pd.Series:
    grouped = df.groupby('symbol')
    ma20 = grouped['close'].transform(lambda x: x.rolling(20).mean())
    std20 = grouped['close'].transform(lambda x: x.rolling(20).std())
    result = (df['close'] - ma20) / (std20 + 1e-12)
    return result
```

模板C: 跨字段组合因子
```python
def compute_factor(df: pd.DataFrame) -> pd.Series:
    df = df.copy()
    df['ret'] = df.groupby('symbol')['close'].pct_change(1)
    df['vol_chg'] = df.groupby('symbol')['volume'].pct_change(1)
    result = df.groupby('symbol').apply(
        lambda g: g['ret'].rolling(20).corr(g['vol_chg'])
    ).droplevel(0)
    return result
```

模板D: 条件因子
```python
def compute_factor(df: pd.DataFrame) -> pd.Series:
    grouped = df.groupby('symbol')
    momentum = grouped['close'].pct_change(20)
    vol = grouped['close'].transform(lambda x: x.rolling(20).std())
    vol_rank = vol.groupby(df['date']).rank(pct=True)
    result = np.where(vol_rank > 0.7, -momentum, momentum)
    return pd.Series(result, index=df.index)
```

## 输出格式（严格JSON）

{
  "factor_name": "snake_case_name_with_window",
  "code": "完整的Python函数代码字符串",
  "data_fields_used": ["close", "volume"],
  "lookback_days": 20,
  "complexity_score": 3,
  "potential_issues": ["高相关性风险: 可能与turnover_20类似"]
}

如果假设需要多个窗口版本，生成多个factor，命名加后缀如 _5d, _20d, _60d。
"""
```

### 2.2.2 User Prompt构建

```python
def build_factor_prompt(hypothesis: dict, similar_factors: list) -> str:
    return f"""
请为以下假设生成因子代码:

假设: {hypothesis['hypothesis']}
因果链: {hypothesis['causal_chain']}
因子草图: {hypothesis['factor_sketch']}
预期方向: {hypothesis['expected_direction']}
使用字段: {hypothesis['data_fields']}

参考（知识库中相似的已成功因子代码）:
{format_similar_factors(similar_factors)}

请生成代码。如果因子涉及窗口参数，请生成3个版本:
短窗口(5-10天)、中窗口(20天)、长窗口(60天)。

注意:
- 严格遵守groupby('symbol')规则
- 如果使用多个数据表的字段，假设它们已经merge到df中
- 财务指标是季频数据，已经forward fill到日频
"""
```

### 2.2.3 代码重试时的反馈Prompt

```python
def build_retry_prompt(original_code: str, error_info: str) -> str:
    return f"""
你上一次生成的代码执行出错，请修复。

原代码:
```python
{original_code}
```

错误信息:
{error_info}

请只返回修复后的完整代码（JSON格式），不要解释。
常见修复:
- 如果是groupby相关错误，检查是否漏了.groupby('symbol')
- 如果是KeyError，检查字段名拼写
- 如果是除零错误，检查分母是否加了1e-12
- 如果是index不匹配，检查.droplevel(0)或.reset_index
"""
```

---

## 2.3 Eval Agent（自动化管道）

```python
class EvalAgent:
    """Eval Agent — 完全自动化，不用LLM"""

    def evaluate(self, factor_code: str, hypothesis: dict) -> dict:
        """完整评估流程，返回评估结果"""

        # Step 1: 代码安全检查
        safety = self.check_code_safety(factor_code)
        if not safety['passed']:
            return {'status': 'failed', 'reason': f'safety: {safety["issue"]}'}

        # Step 2: 沙箱执行
        result = self.sandbox_execute(factor_code, timeout=60, max_memory_gb=2)
        if not result['success']:
            return {'status': 'failed', 'reason': f'execution: {result["error"]}'}

        factor_values = result['output']

        # Step 3: 基础质量检查
        coverage = factor_values.notna().mean()
        if coverage < 0.7:
            return {'status': 'failed', 'reason': f'low_coverage: {coverage:.2%}'}

        # Step 4: IC快速筛选
        ic_mean = self.calc_spearman_ic(factor_values)
        if abs(ic_mean) < 0.015:
            return {'status': 'failed', 'reason': f'low_ic: {ic_mean:.4f}'}

        # Step 5: 4层Gate Pipeline
        gate_results = self.run_gate_pipeline(factor_values)
        if not gate_results['all_pass']:
            failed_gates = [g for g, v in gate_results.items() if not v and g != 'all_pass']
            return {'status': 'failed', 'reason': f'gate_failed: {failed_gates}'}

        # Step 6: 正则化检查（AlphaAgent三重正则化）
        originality = self.check_originality(factor_code)  # AST相似度
        alignment = self.check_hypothesis_alignment(factor_values, hypothesis)
        complexity = self.check_complexity(factor_code)  # AST节点数

        if originality['score'] > 0.8:
            return {'status': 'failed', 'reason': 'not_original'}
        if not alignment['aligned']:
            return {'status': 'failed', 'reason': 'hypothesis_misaligned'}
        if complexity['nodes'] > 50:
            return {'status': 'failed', 'reason': 'too_complex'}

        # 全部通过
        return {
            'status': 'success',
            'ic_mean': ic_mean,
            'gate_results': gate_results,
            'originality': originality['score'],
            'complexity': complexity['nodes'],
        }
```

---

## 2.4 反馈Prompt

```python
FEEDBACK_PROMPT_TEMPLATE = """
上一轮挖掘结果反馈:

假设: {hypothesis}
因子名: {factor_name}
结果: 未通过Gate

详细诊断:
  IC_mean = {ic_mean} (阈值: >0.02, {'通过' if passed_ic else '未通过'})
  IC_IR = {ic_ir}
  t-stat = {t_stat} (阈值: >2.0, {'通过' if passed_t else '未通过'})
  单调性 = {monotonicity} (阈值: >0.7, {'通过' if passed_mono else '未通过'})
  与最相似Active因子的相关性 = {max_corr} (阈值: <0.7, {'通过' if passed_corr else '未通过'})
  最相似因子: {most_similar_factor}
  分年IC: {yearly_ic}

失败主因分析:
{failure_analysis}

请在下一轮生成假设时:
1. 避免与"{most_similar_factor}"高度相关的方向
2. 针对"{failure_reason}"做调整
3. 如果IC接近但不够，考虑对公式做非线性变换或条件化处理
"""
```

---

## 2.5 输出格式校验

```python
def parse_llm_output(raw_output: str, expected_format: str) -> dict:
    """三层防护解析LLM输出"""

    # Layer 1: 直接JSON解析
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        pass

    # Layer 2: 正则提取JSON块
    json_match = re.search(r'```json?\s*([\s\S]*?)\s*```', raw_output)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找到第一个 [ 或 { 到最后一个 ] 或 }
    for start_char, end_char in [('[', ']'), ('{', '}')]:
        start = raw_output.find(start_char)
        end = raw_output.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw_output[start:end+1])
            except json.JSONDecodeError:
                pass

    # Layer 3: 全部失败，返回None（调用方决定重试或跳过）
    return None
```

---

# 3. Engine 4: GP遗传编程引擎

## 3.1 配置（全部前端可调）

```python
GP_DEFAULT_CONFIG = {
    "population_size": 500,       # 前端滑块 [100, 2000]
    "generations": 100,           # 前端滑块 [20, 500]
    "crossover_rate": 0.7,        # 前端滑块 [0.1, 0.95]
    "mutation_rate": 0.1,         # 前端滑块 [0.01, 0.5]
    "tournament_size": 5,         # 前端滑块 [2, 10]
    "max_tree_depth": 6,          # 前端滑块 [3, 10]
    "max_nodes": 30,              # 前端滑块 [10, 80]
    "anti_crowding_threshold": 0.8,  # 前端滑块 [0.5, 0.95]
    "fitness_ic_weight": 1.0,     # 前端滑块
    "fitness_ir_weight": 1.0,     # 前端滑块
    "fitness_novelty_weight": 1.0,# 前端滑块

    "terminal_nodes": [           # 前端多选框
        "$close", "$open", "$high", "$low",
        "$volume", "$amount", "$turnover",
        "1", "2", "5", "10", "20", "60"
    ],
    "function_nodes": [           # 前端多选框
        "add", "sub", "mul", "div",
        "ts_mean", "ts_std", "ts_rank", "ts_corr",
        "ts_max", "ts_min", "delay",
        "rank", "abs", "log", "sign"
    ],
}
```

## 3.2 适应度函数

```python
def fitness(individual, existing_factors, config):
    factor_values = evaluate_expression_tree(individual)
    ic_mean = calc_spearman_ic(factor_values)
    ic_ir = ic_mean / (calc_ic_std(factor_values) + 1e-12)
    max_corr = max_correlation_with(factor_values, existing_factors)

    return (
        config['fitness_ic_weight'] * abs(ic_mean)
        + config['fitness_ir_weight'] * abs(ic_ir)
        - config['fitness_novelty_weight'] * max_corr
    )
```

---

# 4. 调度器（UCB1 Multi-Armed Bandit）

```python
class MiningScheduler:
    DIRECTIONS = [
        "cross_source", "conditional", "nonlinear",
        "decay_resistant", "underexplored", "refinement"
    ]

    def select_direction(self) -> str:
        total_rounds = sum(self.direction_rounds.values()) + 1
        scores = {}
        for d in self.DIRECTIONS:
            n = self.direction_rounds.get(d, 0) + 1
            avg_reward = self.direction_rewards.get(d, 0) / n
            exploration = math.sqrt(2 * math.log(total_rounds) / n)
            scores[d] = avg_reward + exploration
        return max(scores, key=scores.get)

    def update_reward(self, direction: str, n_success: int, n_total: int):
        self.direction_rounds[direction] = self.direction_rounds.get(direction, 0) + n_total
        self.direction_rewards[direction] = self.direction_rewards.get(direction, 0) + n_success
```

---

# 5. 一轮完整挖掘流程

```
1. 调度器选择搜索方向（UCB1）

2. 构建上下文（从知识库+DB拉取）
   → Active因子列表、最近5轮成功/失败、该方向历史表现

3. 并行启动两条搜索线

   搜索线A: LLM三Agent
     3a. Idea Agent(R1) 生成N个假设 (~30秒, ~¥0.1)
     3b. Factor Agent(V3) 为每个假设生成代码 (~20秒, ~¥0.05)
         代码执行失败 → 重试最多3次，每次注入报错信息
         格式校验失败 → 正则提取→重试1次→跳过
     3c. Eval Agent 沙箱执行+IC筛选+Gate (~3分钟)

   搜索线B: GP进化
     3d. 初始化种群（基于方向约束终端节点）
     3e. 进化N代
     3f. Top-10个体进入Gate

4. 汇总结果
   → 通过Gate: 注册为candidate → 等待人工确认(L2)
   → 未通过: 记录失败原因到mining_knowledge表
   → 构建反馈Prompt供下轮Idea Agent使用

5. 更新调度器
   → 该方向reward更新
   → 连续3轮无产出 → 自动切换方向

6. 人工检查点（candidate → active需L2确认）
   确认内容: 假设合理性、IC可信度、无数据偷窥
```

---

# 6. 知识库Schema

```sql
CREATE TABLE mining_knowledge (
    id SERIAL PRIMARY KEY,
    source VARCHAR(16),           -- 'llm_agent'|'gp'|'brute_force'|'import'
    round_id INT,
    search_direction VARCHAR(32),
    hypothesis TEXT,
    hypothesis_model VARCHAR(32),
    factor_name VARCHAR(64),
    factor_code TEXT,
    expression TEXT,
    category VARCHAR(32),
    direction VARCHAR(8),
    complexity_score INT,
    ast_node_count INT,
    ic_mean DECIMAL(8,6),
    ic_ir DECIMAL(8,6),
    t_stat DECIMAL(8,4),
    monotonicity DECIMAL(8,4),
    max_corr_existing DECIMAL(8,4),
    yearly_ic JSONB,
    gate_1_pass BOOLEAN, gate_2_pass BOOLEAN,
    gate_3_pass BOOLEAN, gate_4_pass BOOLEAN,
    all_gates_pass BOOLEAN,
    originality_score DECIMAL(8,4),
    hypothesis_alignment BOOLEAN,
    failure_reason VARCHAR(128),
    failure_detail TEXT,
    status VARCHAR(16),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

# 7. LLM调用参数

```python
LLM_CALL_DEFAULTS = {
    "idea_agent": {
        "model": "deepseek-r1",        # 前端下拉选择
        "temperature": 0.8,             # 前端滑块 [0, 1.5]
        "max_tokens": 4096,             # 前端滑块 [512, 8192]
        "top_p": 0.95,                  # 前端滑块 [0.1, 1.0]
    },
    "factor_agent": {
        "model": "deepseek-v3",
        "temperature": 0.2,
        "max_tokens": 4096,
        "top_p": 0.9,
    },
}
```

---

# 8. Prompt版本管理

```python
PROMPT_VERSIONS = {
    "idea_agent_system": "v1.0",
    "idea_agent_user": "v1.0",
    "factor_agent_system": "v1.0",
    "factor_agent_user": "v1.0",
    "feedback": "v1.0",
    "direction_hints": "v1.0",
}

# Prompt变更时更新版本号+记录变更原因
# 支持A/B测试：同时运行两个版本的Prompt，对比产出质量
```

---

# 9. 前端页面设计

> 因子挖掘相关的 4 个前端页面（因子实验室/任务中心/评估报告/因子库）的完整设计已移至 DEV_FRONTEND_UI.md 第三章。

---

# 10. 因子生命周期管理（V2新增）

```
新发现 → 评估 → 入库(🆕new) → 验证通过(✅active)
                                      ↓
                                 定期体检(每两周)
                                      ↓
                              IC衰退(⚠️degraded) → 复查
                                      ↓
                              确认失效(❌archived)
```

状态转移规则：
- new → active：首次评估通过所有Gate + 人工确认(L1)或自动(L2+)
- active → degraded：近3个月IC < 历史IC × 0.5
- degraded → active：重新评估IC恢复
- degraded → archived：连续2次体检仍不达标
- archived：保留记录但不参与策略，可手动恢复

---

# 11. 工具函数库（V2新增）

用户在因子实验室编写因子时可直接调用的预置函数，实现在 `factors/tools.py`。

```python
# 时序函数(沿时间轴，每只股票独立)
ts_mean(x, window)          # 滚动均值
ts_std(x, window)           # 滚动标准差
ts_rank(x, window)          # 时序排名百分位
ts_max(x, window)           # 滚动最大值
ts_min(x, window)           # 滚动最小值
ts_delta(x, period)         # 差分: x - x.shift(period)
ts_return(x, period)        # 收益率: x / x.shift(period) - 1
ts_corr(x, y, window)       # 滚动相关性
ts_decay_linear(x, window)  # 线性衰减加权均值

# 截面函数(沿股票轴，每日独立)
cs_rank(x)                  # 横截面排名百分位
cs_zscore(x)                # 横截面标准化
```

---

# 12. 数据库表与 API

> 因子挖掘相关的 3 张新表(factor_registry/factor_evaluation/factor_mining_task)DDL 详见 DEV_AI_EVOLUTION.md §11.1-11.3。
> 因子挖掘相关的 15 个 API 端点详见 DEV_FRONTEND_UI.md §7.2 和 DEV_AI_EVOLUTION.md §10.1。

---

# 13. 补充设计（V5.1）

## 13.1 Factor Gate 8项检验完整定义（F1）

A股因子必须通过全部8项硬性检验才能入库(status='active')。

| # | 检验项 | 阈值 | 计算方式 | 不通过→ |
|---|--------|------|---------|--------|
| G1 | IC均值 | \|IC_mean\| > 0.02 | 滚动60日Rank IC均值 | rejected |
| G2 | IC_IR | IC_IR > 0.3 | IC_mean / IC_std | rejected |
| G3 | IC胜率 | IC_win_rate > 55% | IC>0的比例 | rejected |
| G4 | 单调性 | monotonicity > 0.7 | 5分组收益严格递增比例 | rejected |
| G5 | 半衰期 | half_life > 5天 | IC自相关衰减到50%的天数 | candidate(不rejected) |
| G6 | 相关性 | max_corr < 0.7 | 与所有active因子的最大\|corr\| | rejected |
| G7 | 覆盖率 | coverage > 80% | 非NaN股票占Universe比例 | rejected |
| G8 | 综合评分 | score ≥ 70 | 加权: IC×30+IR×20+胜率×15+单调×15+半衰×10+覆盖×10 | <70 rejected, 50-70 candidate |

FDR多重检验校正（F5补充）:
```
当total_tested_count > 20时，G1和G2的阈值动态调整:

  adjusted_t_threshold = base_t + log(N) × 0.3
  其中N = total_tested_count（累计测试过的因子总数）
  
  示例:
    测试了20个因子: t_threshold = 2.0 + log(20)×0.3 = 2.0 + 0.9 = 2.9
    测试了100个因子: t_threshold = 2.0 + log(100)×0.3 = 2.0 + 1.38 = 3.38
    
  Harvey et al. (2016): 金融领域t>3.0作为新基准
  
  前端显示: 
    "IC t-stat: 2.8 (原始) → FDR校正: 3.1需要 → ❌ 未通过"
    "IC t-stat: 3.5 (原始) → FDR校正: 3.1需要 → ✅ 通过"
  
  Newey-West调整:
    IC的t值用Newey-West HAC估计(考虑IC的自相关)
    lag = int(4 × (T/100)^(2/9))  # Andrews(1991)自动lag选择
```

## 13.2 A股暴力枚举模板（F2）

```python
ASTOCK_BRUTE_FORCE_TEMPLATES = {
    'momentum_variants': {
        'description': '动量因子参数网格',
        'template': 'ts_delta(close_adj, {period}) / close_adj.shift({period})',
        'params': {'period': [5, 10, 20, 40, 60, 120]},
        'total': 6,
    },
    'volatility_variants': {
        'description': '波动率因子参数网格',
        'template': 'ts_std(close_adj.pct_change(), {period})',
        'params': {'period': [5, 10, 20, 40, 60]},
        'total': 5,
    },
    'turnover_variants': {
        'description': '换手率变体',
        'template': '{func}(turnover_rate, {period})',
        'params': {
            'func': ['ts_mean', 'ts_std', 'ts_rank', 'ts_delta'],
            'period': [5, 10, 20, 40],
        },
        'total': 16,
    },
    'volume_price_cross': {
        'description': '量价交叉因子',
        'template': 'ts_corr(close_adj.pct_change(), volume.pct_change(), {period})',
        'params': {'period': [5, 10, 20, 40]},
        'total': 4,
    },
    'ma_deviation': {
        'description': '均线偏离度',
        'template': '(close_adj - ts_mean(close_adj, {period})) / ts_std(close_adj, {period})',
        'params': {'period': [5, 10, 20, 60, 120]},
        'total': 5,
    },
    'northbound_variants': {
        'description': '北向资金变体',
        'template': '{func}(northbound_net_buy, {period}) / market_cap',
        'params': {
            'func': ['ts_sum', 'ts_mean', 'ts_delta'],
            'period': [5, 10, 20],
        },
        'total': 9,
    },
    'financial_momentum': {
        'description': '财务指标动量',
        'template': 'ts_delta({indicator}, 1)',
        'params': {
            'indicator': ['roe', 'roa', 'gross_profit_margin', 'revenue_growth', 'net_profit_growth'],
        },
        'total': 5,
        'note': '季频数据,需要PIT处理',
    },
}
# 总枚举量: 50个候选因子
# 预计耗时: ~50因子 × 简化IC评估 ≈ 10-15分钟
```

## 13.3 沙箱执行详细设计（F3）

```python
import multiprocessing
import psutil
import signal as sig

class FactorSandbox:
    """因子代码沙箱执行"""

    ALLOWED_MODULES = {
        'numpy', 'pandas', 'math',
        # 禁止: os, sys, subprocess, socket, requests, urllib
    }

    MAX_MEMORY_GB = 2
    MAX_TIME_SEC = 60

    def execute(self, code: str, data: pd.DataFrame) -> dict:
        """
        在子进程中执行因子代码

        安全机制:
          1. AST静态检查: 禁止import非白名单模块
          2. multiprocessing子进程隔离
          3. psutil内存监控(超2GB杀掉)
          4. signal.alarm超时(60秒)
          5. 子进程不继承主进程的DB连接/网络

        返回:
          成功: {'status': 'ok', 'result': pd.Series, 'time_sec': 2.3, 'memory_mb': 450}
          失败: {'status': 'error', 'error': 'TimeoutError', 'time_sec': 60}
        """
        # Step 1: AST安全检查
        if not self._check_ast_safety(code):
            return {'status': 'error', 'error': 'unsafe_import'}

        # Step 2: 子进程执行
        result_queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target=self._run_in_subprocess,
            args=(code, data, result_queue)
        )
        proc.start()
        proc.join(timeout=self.MAX_TIME_SEC)

        if proc.is_alive():
            proc.kill()
            return {'status': 'error', 'error': 'TimeoutError'}

        if result_queue.empty():
            return {'status': 'error', 'error': 'process_crashed'}

        return result_queue.get()

    def _check_ast_safety(self, code: str) -> bool:
        """AST静态检查: 禁止危险import"""
        import ast
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split('.')[0] not in self.ALLOWED_MODULES:
                        return False
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split('.')[0] not in self.ALLOWED_MODULES:
                    return False
        return True

    def _run_in_subprocess(self, code, data, result_queue):
        """子进程内执行"""
        try:
            # 内存限制
            import resource
            resource.setrlimit(resource.RLIMIT_AS,
                (self.MAX_MEMORY_GB * 1024**3, self.MAX_MEMORY_GB * 1024**3))

            namespace = {'pd': pd, 'np': np, 'data': data}
            exec(code, namespace)
            result = namespace.get('result', None)
            result_queue.put({'status': 'ok', 'result': result})
        except Exception as e:
            result_queue.put({'status': 'error', 'error': str(e)})
```

## 13.4 因子生命周期状态机（F4）

```
状态转换图:

  [新建] ──评估──→ [candidate] ──Gate通过+审批──→ [active]
                      │                              │
                      │ Gate未通过                    │ IC衰退>40%
                      ↓                              ↓
                  [rejected]                    [degraded]
                                                    │
                                        ┌───────────┼───────────┐
                                        │           │           │
                                   60天恢复    继续衰退    手动淘汰
                                        ↓           ↓           ↓
                                    [active]   [retired]   [retired]

状态定义:
  candidate: 通过基础IC筛选但未过完整Gate或待审批
  active:    生产使用中（参与因子合成和信号生成）
  degraded:  IC衰退预警（仍在使用但降低权重，60天观察期）
  retired:   已淘汰（不再使用，保留历史记录）
  rejected:  Gate未通过（保留记录供分析）

触发条件:
  candidate→active:  8项Gate全部通过 + 人工审批(L0/L1) 或 自动(L2+)
  candidate→rejected: 任一Gate硬性项未通过
  active→degraded:   近3月IC下降>40% 或 IC_IR<0.15(原IR>0.3)
  degraded→active:   60天观察期后IC恢复到历史均值的70%以上
  degraded→retired:  60天内未恢复 或 再次衰退
  active→retired:    手动淘汰 或 AI闭环诊断Agent建议淘汰+审批

数据库:
  factor_registry表的status字段: 'candidate'|'active'|'degraded'|'retired'|'rejected'
  状态变更记录: factor_evaluation表(含变更时间和原因)
```

## 13.5 V2因子→代码函数映射表（V2补充）

34个因子中前18个Phase 0实现，其余Phase 1：

| # | 因子名 | 函数名 | 输入字段 | Phase |
|---|--------|--------|---------|-------|
| 1 | momentum_5 | calc_momentum(df, 5) | close_adj | 0 |
| 2 | momentum_10 | calc_momentum(df, 10) | close_adj | 0 |
| 3 | momentum_20 | calc_momentum(df, 20) | close_adj | 0 |
| 4 | reversal_5 | calc_reversal(df, 5) | close_adj | 0 |
| 5 | reversal_10 | calc_reversal(df, 10) | close_adj | 0 |
| 6 | reversal_20 | calc_reversal(df, 20) | close_adj | 0 |
| 7 | volatility_20 | calc_volatility(df, 20) | close_adj | 0 |
| 8 | volatility_60 | calc_volatility(df, 60) | close_adj | 0 |
| 9 | volume_std_20 | calc_volume_std(df, 20) | volume | 0 |
| 10 | turnover_mean_20 | calc_turnover_mean(df, 20) | turnover_rate | 0 |
| 11 | turnover_std_20 | calc_turnover_std(df, 20) | turnover_rate | 0 |
| 12 | amihud_20 | calc_amihud(df, 20) | close_adj, volume, amount | 0 |
| 13 | ln_market_cap | calc_ln_mcap(df) | total_mv | 0 |
| 14 | bp_ratio | calc_bp(df) | pb | 0 |
| 15 | ep_ratio | calc_ep(df) | pe | 0 |
| 16 | northbound_pct | calc_north_pct(df) | north_net_buy, market_cap | 0 |
| 17 | price_volume_corr_20 | calc_pv_corr(df, 20) | close_adj, volume | 0 |
| 18 | high_low_range_20 | calc_hl_range(df, 20) | high_adj, low_adj | 0 |
| 19-34 | (资金流/融资/ROE/营收增速等) | Phase 1实现 | 各自数据源 | 1 |

所有函数位于: backend/engines/factor_engine.py
输入: 复权价格(close_adj = close × adj_factor), 不复权量(volume)
输出: pd.Series, index=stock_code, 截面标准化后

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. 因子预处理顺序修正

**正确顺序（不可调换）**:
```
1. MAD 去极值（中位数 ± 5 × MAD）
2. 缺失值填充（行业中位数填充，仍缺则0）
3. 市值+行业中性化（回归取残差）  ← 先中性化
4. zscore 标准化                   ← 再标准化
```
原因: 先zscore再中性化会导致中性化回归残差分布不对，所有因子IC都不准。

### P2. IC计算的forward return定义修正

- forward return使用**相对沪深300的超额收益**（不是绝对收益）
  `excess_return = stock_return - hs300_return`
- 必须用**复权价格**计算: `adj_close = close × adj_factor / latest_adj_factor`
- 停牌期间的return用**所属行业指数**代替
- 因子评估报告同时展示"绝对IC"和"超额IC"

### P3. GP引擎优化（覆盖GP相关章节）

- **反拥挤阈值**: 从0.8降到0.5-0.6（0.79相关性本质是同一因子变体）
- **适应度函数加复杂度惩罚**:
  `fitness = IC×w1 + IR×w2 + 原创性×w3 - 节点数×w4`
  节点越多扣分越重，防止过度拟合的超长表达式
- **岛屿模型**: 种群分3-4个子群独立进化，每N代交换少量个体（对抗局部最优）
- **样本外测试**: GP只在训练集上跑，最终评估在完全隔离的测试集上

### P4. 暴力枚举剪枝（覆盖Engine 1相关章节）

- **量纲过滤**: 不匹配的组合直接跳过（如 `ts_corr(volume, pe_ttm, 20)` 无经济学意义）
- **分批优先级**: 先算单算子单字段（~150个），过IC快筛后再做二元组合
- **时间预算**: 最多跑2小时，超时按已算IC排序取Top

### P5. LLM三Agent质量控制

- **去重检测**: 新因子与已有因子embedding相似度>0.8直接拒绝
- **快速验证**: Factor Agent生成代码后先跑100只股票×1年（~5秒），通过再跑全量
- **有效率监控**: 统计每轮通过Gate的比例，连续5轮<5%自动暂停并触发诊断
- **LLM因子门槛降低**: IC > 0.015即可入候选池（原0.02过严），重点看正交性（与现有因子相关性<0.5）

### P6. 知识库去重改进（覆盖mining_knowledge相关章节）

- 去重应基于**因子值的Spearman相关性>0.7判定重复**（不是表达式embedding相似度）
  两个表达式写法完全不同但产出高度相关 = 同一个因子
- `failure_reason`字段结构化: `{"gate": "ic", "ic_mean": 0.008, "threshold": 0.02}`
- 给Idea Agent的上下文注入: "以下方向已尝试N次都失败: [列表]"

### P7. 因子生命周期状态机

```
candidate → active → warning → critical → retired
                ↑                              │
                └──── 新因子替补 ←─── 触发挖掘 ←┘
```
- candidate: 新发现，进入观察期（计算IC但不参与信号）
- active: 观察期通过（IC稳定>阈值），参与信号合成
- warning: 双周体检发现IC衰退（近60日IC < 历史均值50%）
- critical: 连续2周warning → 自动降权到0（保留计算用于监控恢复）
- retired: critical持续4周 → 退休，进入冷宫
- 冷宫6个月后自动检查一次（市场风格可能轮回）
- **活跃因子数<12 → P1告警 + 触发紧急因子挖掘**

### P8. 因子拥挤度监控（Phase 1，架构预留）

- 公式: `crowding = corr(factor_rank, abnormal_volume, cross_section)`
  因子值排名靠前的股票，如果成交量异常放大+波动率飙升，说明因子拥挤
- 拥挤度>阈值时自动降低该因子权重
- 作为元因子(meta-factor)，Phase 0在FactorRegistry中预留拥挤度因子接口

---

## 因子计算规则（强制执行，从CLAUDE.md迁入）

### 因子预处理顺序（严格按此顺序，不可调换）

```
1. 去极值（MAD）
2. 缺失值填充
3. 中性化（回归掉市值+行业）  ← 先中性化
4. 标准化（zscore）            ← 再标准化
```
**如果先zscore再中性化，中性化回归的残差分布会不对，所有因子IC都不准。**

### IC计算的forward return定义

- forward return使用**相对沪深300的超额收益**（不是绝对收益）
- 必须用**复权价格**（close × adj_factor / latest_adj_factor）计算
- 停牌期间的return用**行业指数**代替
- 同时计算1/5/10/20日IC，因子评估报告展示"绝对IC"和"超额IC"
