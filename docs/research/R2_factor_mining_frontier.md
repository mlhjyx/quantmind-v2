# R2: 因子挖掘前沿技术选型报告

> **报告编号**: R2
> **日期**: 2026-03-28
> **状态**: ✅ 完成
> **交叉审查**: 待 quant-reviewer + alpha-miner + arch challenge

---

## 0. 摘要

本报告系统评估2024-2026年因子挖掘前沿技术，对比5个核心项目（QuantaAlpha、RD-Agent、FactorEngine、AlphaAgent、FactorMiner）和2个基础工具（Qlib Alpha158、GP遗传编程），结合QuantMind V2的现有设计（4引擎架构：暴力枚举/开源导入/LLM三Agent/GP进化）和约束条件（100万资金、DeepSeek API、Windows 11、个人开发），给出技术选型建议和改进方案。

**核心结论**: 不直接集成任何单一框架，而是提取6个前沿项目的核心模式融入现有4引擎设计。具体选型: **DEAP**作为GP引擎(加权4.15分最高)、**Alpha158**作为因子参考库(4.05分)、**Optuna TPE**做参数优化(FactorEngine逻辑/参数分离模式)、**AST去重**作为Gate第0层(AlphaAgent模式)、**Thompson Sampling**做搜索调度(RD-Agent模式)。P0改进项共9项约12天工作量，最大收益项是逻辑/参数分离(GP效率)和AST去重(准确率+81%)。

---

## 1. 评估维度与方法论

### 1.1 评估框架

每个项目/技术按以下7个维度打分(1-5分)：

| 维度 | 权重 | 说明 |
|------|------|------|
| **A股适用性** | 25% | 是否在A股验证？T+1/涨跌停/散户结构适配？ |
| **实现复杂度** | 20% | 个人开发者多少天能实现核心功能？ |
| **LLM成本** | 15% | 月成本估算（用DeepSeek替代GPT） |
| **与现有设计兼容** | 15% | 与DEV_FACTOR_MINING.md 4引擎架构的兼容程度 |
| **因子质量** | 10% | 论文/实验报告的IC/Sharpe指标 |
| **抗过拟合** | 10% | 去重/正则化/样本外验证机制 |
| **可维护性** | 5% | 代码质量/文档/社区活跃度 |

### 1.2 我们的约束条件

| 约束 | 值 | 影响 |
|------|---|------|
| 资金规模 | 100万RMB | 不需要考虑因子容量/市场冲击 |
| LLM预算 | 弹性（根据实际调整） | DeepSeek优先（成本低10-50倍于GPT-4） |
| 硬件 | R9-9900X3D + RTX 5070 12GB | GP训练可GPU加速，LightGBM本地 |
| 开发人力 | 1人 | 必须选最小可行方案，不堆复杂框架 |
| 现有基础 | factor_engine.py + factor_profile.py + factor_analyzer.py + 8项Gate Pipeline设计 | 不从零开始 |
| 市场 | A股全市场 | 需要T+1/涨跌停/行业中性化 |
| 调仓频率 | **多频率可选** | R1确定: 日度/周度/月度/事件触发，按因子ic_decay匹配 |

### 1.3 当前因子挖掘设计状态

| 引擎 | 设计状态 | 实现状态 | 说明 |
|------|---------|---------|------|
| Engine 1: 暴力枚举 | ✅完整设计（50模板） | ❌未实现 | 最简单，优先级最高 |
| Engine 2: 开源导入 | ⚠️部分设计 | ❌未实现 | Alpha158/Alpha101/TA-Lib |
| Engine 3: LLM三Agent | ✅完整设计（Prompt/Gate/知识库） | ❌未实现 | Idea+Factor+Eval Agent |
| Engine 4: GP进化 | ✅完整设计（岛屿模型/适应度） | ❌未实现 | 参数已注册到param_defaults |

---

## 2. 前沿项目深度分析

### 2.1 QuantaAlpha — LLM+进化策略

> 来源: arXiv 2602.07085 (2026-02), 清华/北大/CMU/HKUST/Stanford联合
> 代码: **开源MIT** — github.com/QuantaAlpha/QuantaAlpha (556 stars)
> 数据: HuggingFace提供A股HDF5数据(2016-2025)

**架构**: 4组件流水线
1. **多样化规划(Diversified Planning)**: 给定研究方向 → LLM生成10个结构性不同的假设方向(按信号源/时间尺度/机制类型变异)
2. **因子实现(Factor Realization)**: 假设 → 语义描述 → AST符号表达式 → 可执行代码。约束Gate: 符号长度≤250字符, 基础特征≤6个, 自由参数比<50%。LLM验证语义一致性。
3. **自进化(Self-Evolution)**: **轨迹级mutation** — 诊断次优决策节点k，只重写该段保留已验证前缀。**轨迹级crossover** — 识别不同父轨迹的高奖励段，重组互补片段。
4. **因子池(Factor Pool)**: 贪心RankIC筛选 + 相关性去冗(阈值0.7)

**核心创新**:
- **轨迹级进化**: 不是在单个因子上mutation，而是在整个"假设→设计→代码→评估"轨迹上操作。保留验证过的好的前缀，只修改弱环节。
- **复杂度控制**: C(f) = α1×SymbolLength + α2×FreeParams + α3×log(1+|RawFeatures|)。去掉此项ARR下降8.44%。
- **语义一致性验证**: LLM检查假设↔描述↔符号↔代码四层一致性，不一致则重写。

**性能指标(CSI300, OOS 2022-2025, 日频调仓TopkDropout)**:

| 模型 | IC | 年化收益(%) | MDD(%) |
|------|-----|-----------|--------|
| GPT-5.2 + QuantaAlpha | 0.1501 | 27.75 | 7.98 |
| DeepSeek-V3.2 + QuantaAlpha | 0.1338 | 23.77 | 9.14 |
| Claude-4.5-Sonnet + QuantaAlpha | 0.1111 | 22.70 | 6.96 |
| GPT-5.2 + AlphaAgent | 0.0966 | 15.54 | 12.89 |
| GPT-5.2 + RD-Agent | 0.0531 | 9.91 | 14.82 |

**⚠️ 频率注意**: IC=0.1501是**日频IC+日频调仓+CSI300大盘股**。v1.1基线是月频，但R1研究已确定多策略多频率架构（日频/周频/月度/事件触发可选）。日频IC数据适用于**日频子策略场景**（如FastRankingStrategy日度版或EventDrivenStrategy）。月频子策略需要单独跑ic_decay确认月度IC水平（预期0.03-0.06）。

**A股适用性**: ✅ 原生A股设计(CSI300/500), HuggingFace提供数据。但:
- 日频→月频迁移是最大风险(无月频实验数据)
- 无交易成本建模(我们的volume_impact会严重惩罚高换手)
- 无bootstrap统计显著性(违反我们的回测规则4)
- 无整手约束

**成本分析**:
- 每轮~150-200次LLM调用
- DeepSeek-V3.2: **$0.10-0.15/轮** (极低)
- 100轮系统探索(建立因子库): **$10-15**
- GPT-5.2: ~$1.30-2.10/轮, 100轮~$130-210

**与我们设计的差距**:
1. 我们的Engine 3是串行3-Agent(Idea→Factor→Eval)，缺少**轨迹级进化**
2. 我们的去重用Spearman相关性>0.7，QuantaAlpha用**AST+相关性双重**
3. 我们缺少**语义一致性验证**层(假设↔代码一致性)
4. 我们缺少**复杂度惩罚**机制

**⭐ 可采纳的核心思想(按优先级)**:
1. **P0: 多样化规划** — 不是每次生成1个假设，而是10个方向并行(与UCB1调度器兼容)。1天。
2. **P0: 复杂度惩罚** — 加入适应度: fitness -= α×complexity。0.5天。
3. **P1: 语义一致性检查** — Factor Agent生成代码后，Eval Agent加一步LLM验证。1天。
4. **P1: 轨迹级进化** — mining_knowledge表存完整轨迹，mutation/crossover在轨迹上操作而非单因子。3-5天。
5. **P2: 直接集成QuantaAlpha** — 作为Engine 5并行运行，输出喂入我们的Gate Pipeline。9-15天完整集成。

**不采纳**: 日频TopkDropout回测(与我们月度框架不兼容)、无成本假设(我们已有volume_impact)。

**建议**: 提取核心思想(多样化规划+复杂度控制+语义验证)融入Engine 3，不做完整集成。直接集成的9-15天投入产出比不如改进现有设计。

---

### 2.2 RD-Agent-Quant — 微软多Agent联合优化

> 来源: arXiv 2505.15155, Microsoft Research, NeurIPS 2025 Poster
> 代码: **开源MIT** — github.com/microsoft/RD-Agent (v0.8.0)
> ⚠️ Windows 11已知不兼容(Issue #1064)

**架构**: 5阶段迭代循环(Research + Development)

1. **Specification**: 编码优化目标 S=(B,D,F,M) — 背景知识/数据接口/输出格式/执行环境
2. **Synthesis(假设生成)**: 从知识森林检索历史实验，生成新因子/模型假设。"R"阶段。
3. **Implementation(Co-STEER代码生成)**: 4子组件 —
   - Scheduler: DAG任务依赖+拓扑排序，失败任务降优先级
   - Knowledge Retrieval: 相似历史方案检索(置信度加权)
   - Chain-of-Thought推理: 结构化推理减少代码幻觉
   - Iterative Refinement: 执行→捕获反馈→更新知识库→重试
4. **Validation**: 去重(IC相关>0.99=重复) + Qlib回测
5. **Analysis(反馈+Bandit调度)**: 8维评估(IC/ICIR/RankIC/RankICIR/ARR/IR/MDD/Sharpe)。**Contextual Thompson Sampling** — 两臂{factor, model}，贝叶斯线性回归采样奖励，选择边际收益更高的方向。

**核心创新: 因子-模型联合优化**:
- **R&D-Factor**: 固定模型(LightGBM)，只优化因子
- **R&D-Model**: 固定因子(Alpha20)，只优化模型
- **R&D-Agent(Q)**: Bandit动态分配计算到边际收益更高的方向 → 优于随机调度和LLM调度

**性能指标(CSI300, OOS 2017-2020)**:

| 指标 | RD-Agent(Q) o3-mini | Alpha158 | TRA(深度模型) |
|------|---------------------|----------|--------------|
| IC | 0.0532 | 0.0341 | 0.0404 |
| ICIR | 0.4278 | 0.2952 | 0.3197 |
| ARR | 14.21% | 5.70% | 6.49% |
| Sharpe | 1.74 | 0.85 | 1.01 |
| MDD | -7.42% | -7.71% | -8.60% |

注: QuantaAlpha(2026-02)在CSI300上IC=0.1501，已显著超越RD-Agent IC=0.0531。

**成本**: GPT-4o $10/轮(30-44迭代)，DeepSeek-V3.2估计**$0.50-1.00/轮**。

**A股适用性**: ✅ CSI300/500原生测试。但:
- **Windows 11不兼容** — Docker挂载路径失败(Issue #1064)，需WSL2
- **Qlib强耦合** — 数据格式/回测引擎/因子表达式全依赖Qlib
- **无交易成本建模**
- 测试期2017-2020，2021-2025 regime shift验证不足

**⭐ 可采纳的核心思想(不集成代码，只采纳架构模式)**:
1. **P0: Thompson Sampling Bandit调度** — 动态决定"本轮挖因子还是调模型"。2天。替代我们的UCB1做方向选择。
2. **P0: Co-STEER知识检索** — 新任务检索相似历史方案作为参考。与经验链(FactorEngine)互补。1天。
3. **P1: 5阶段循环架构** — 作为Engine 3的重构框架: Specification→Synthesis→Implementation→Validation→Analysis。3天。
4. **P1: 8维评估向量** — 扩展我们的因子评估从IC/ICIR到8维。1天。

**不采纳**: 直接集成RD-Agent(Windows不兼容+Qlib耦合)、Docker沙箱(我们用multiprocessing+AST检查更轻量)。

**结论**: RD-Agent的智力贡献(5阶段循环+Bandit调度+知识检索)有价值，但作为依赖引入的运维成本太高。提取模式，自己实现。

---

### 2.3 FactorEngine — 程序级因子+宏微协同进化

> 来源: arXiv 2603.16365 (Qinhong Lin et al., 2026-03)
> 代码: **未开源**

**架构**: 三模块设计
1. **知识注入引导(Knowledge-Infused Bootstrapping)**: LLM从研报PDF中提取因子逻辑→JSON+LaTeX伪代码→可执行Python。解决冷启动问题。
2. **宏微协同进化(Macro-Micro Co-Evolution)**:
   - **宏观层(LLM驱动)**: LLM Agent提议因子程序的结构性突变——改信号组合、归一化方法、条件分支、计算流。基于"经验链(Chains of Experience)"引导搜索方向。
   - **微观层(Bayesian优化)**: TPE/GP本地优化数值参数——窗口长度、衰减因子、阈值。**不调用LLM**，多进程并行。
3. **整合层**: 精英因子筛选(FS = 1/4 × (IC×10 + ICIR + RankIC×10 + RankICIR))，每个种子节点保留Top-5(FS>0.4)，LightGBM多因子模型回测。

**核心创新: 逻辑vs参数分离**:
- **关键洞察**: LLM擅长语义推理（改变因子逻辑结构），不擅长数值优化（找最佳窗口参数）。反之Bayesian擅长数值但不懂语义。把两者分开各做擅长的事。
- **我们GP的问题**: 进化过程中大量迭代浪费在优化窗口参数(5→10→20→30)，而不是探索新的因子结构。
- **实际效率**: FE 200次迭代仅0.5小时/$12 API成本 vs RD-Agent 48小时/$17 vs AlphaAgent 9.7小时/$12。可执行率99%(vs AlphaAgent 93%)。

**程序级 vs 表达式树**:
- 表达式树(我们的GP): `ts_mean(close, 20) / ts_std(close, 20)`，max depth 6, max nodes 30。无法表达条件逻辑/循环/多步pipeline。
- 程序级(FE): 完整Python程序，可实现`if高波动: 用短窗口 else: 用长窗口`。图灵完备但搜索空间更大。
- **我们的折中**: 不采用完整程序级进化(维护负担太重)，但引入"程序模板"——LLM生成带参数化槽位的代码骨架，Bayesian填充数值参数。

**性能指标(CSI300, OOS 2017-2024)**:

| 指标 | FactorEngine | Alpha158基线 | 提升 |
|------|-------------|-------------|------|
| IC | 0.0474 | 0.0299 | +58% |
| ICIR | 0.3185 | 0.2008 | +59% |
| 年化收益 | 18.99% | 8.40% | +126% |
| Sharpe | 1.0093 | 0.4196 | +140% |
| MDD | 12.61% | 17.49% | 更优 |

**成本(DeepSeek估算)**: Gemini-2.5-Pro $12/200迭代 → DeepSeek-V3约$1-3/200迭代，非常可承受。

**⭐ 可采纳的核心思想(按优先级)**:
1. **P0: 逻辑/参数分离** — GP只进化结构，Optuna/TPE优化参数。2-3天工作量，最大收益。
2. **P0: 适应度公式升级** — FS = 1/4×(IC×10+ICIR+RankIC×10+RankICIR)替代当前IC+IR-crowding。0.5天。
3. **P0: 经验知识库** — 扩展mining_knowledge表，存储结构化轨迹(尝试→变更→IC变化→原因)。1天。
4. **P1: 数据缓存** — GP评估瓶颈是数据加载(30s→<1s)。Parquet缓存。1天。
5. **P1: 知识注入种子** — 用LLM从我们的34+已测因子+研报中提取seed programs。3-5天。
6. **P2: 程序模板(中间路线)** — LLM生成代码骨架+参数化槽位，不做完整程序级进化。5-7天。

**不采纳**: 完整程序级进化(1人维护负担过重)、PDF研报摄取pipeline(我们已有结构化因子测试记录)。

---

### 2.4 AlphaAgent — 正则化探索抗Alpha衰减

> 来源: arXiv 2502.16789, KDD 2025 (Toronto), 中山大学
> 代码: **开源MIT** — github.com/RndmVariableQ/AlphaAgent (基于RD-Agent fork)
> LLM: GPT-3.5-turbo(最低成本)，DeepSeek-R1兼容

**架构**: 三Agent迭代框架
1. **Idea Agent**: Chain-of-thought生成假设(观察→金融知识→逻辑证明→实现规格)
2. **Factor Agent**: 假设→算子库+AST→因子表达式，应用三重正则化
3. **Eval Agent**: Qlib回测+去重检查+反馈循环回Idea Agent

**三重正则化(核心创新)**:
```
f* = argmax { L(f(X), y) - λ × Rg(f, h) }

Rg(f,h) = α1×SL(f) + α2×PC(f) + α3×ER(f,h)
  SL(f) = AST节点数(惩罚复杂度)
  PC(f) = 自由参数数(惩罚过拟合)
  ER(f,h) = β1×原创性S(f) + β2×假设对齐C(h,d,f) + β3×log(1+|特征数|)
```
- **原创性S(f)**: AST最大公共子树 vs Alpha Zoo(101/158)
- **假设对齐C(h,d,f)**: LLM打分 假设↔描述一致性(c1) + 描述↔表达式一致性(c2)

**AST去重 vs 我们的去重方案对比**:

| 方法 | 速度 | 捕获结构克隆 | 捕获值重复 | 成本 | 我们的计划 |
|------|------|------------|-----------|------|-----------|
| **AST子树同构** | 极快(无需数据) | ✅核心优势 | ❌ | 0 | ❌未计划 |
| **Embedding相似度** | 快(一次embed) | 部分 | ❌ | 低 | ✅计划(>0.8) |
| **Spearman相关性** | 慢(需全量计算) | ❌ | ✅核心优势 | 中 | ✅计划(>0.7) |

**⭐推荐三级级联去重**:
1. AST结构检查(瞬时，免费) — 捕获`rank(close/open)`变体
2. Embedding语义检查(快速) — 捕获语义相似描述
3. Spearman相关性(最终确认) — 捕获不同逻辑但意外高相关

**性能(CSI500, OOS 2021-2025)**:

| 指标 | AlphaAgent | 对比 |
|------|-----------|------|
| IC | 0.0212 | 维持4年稳定(Alpha158衰减到~0) |
| ICIR | 0.1938 | — |
| 年化收益 | 11.00% | 击败LSTM/Transformer/LightGBM/TRA/RD-Agent |
| MDD | -9.36% | — |
| IR | 1.488 | — |

AST约束效果: 命中率0.29(有AST) vs 0.16(无AST)，提升81%。Token效率提升23%。

**华泰证券GPT因子工厂2.0(2024-09)** — 相关券商研报:
- 基本面因子30个: IC均值=0.011, 低因子间相关(|ρ|均值=0.10)
- 高频因子23个: IC均值=0.020, |t|均值=4.588
- CSI1000增强: **年化超额31.32%, IR=4.20**
- 架构: FactorGPT(表达式) + CodeGPT(代码) + EvalGPT(评估优化)

**⭐ 可采纳的核心思想**:
1. **P0: AST去重作为Gate第0层** — 在IC计算前先过AST检查。200行代码，1-2天。
2. **P0: 假设对齐评分** — DeepSeek评分假设↔表达式一致性。直接实现"因子审批中t 2.0-2.5需经济学解释"。1天。
3. **P0: 复杂度正则化** — 适应度 -= α×AST_depth + β×param_count。与FactorEngine的FS公式互补。0.5天。
4. **P1: 禁止区域追踪(来自FactorMiner)** — 记录已耗尽的算子家族("VWAP变体全部与已有因子corr>0.5")。2天。
5. **P1: 替换机制** — 新因子IC≥阈值 且 1.3×优于最相关已有因子时允许替换。1天。

**不采纳**: Qlib集成(我们有自己的回测)、o3-mini推理模型(成本过高，DeepSeek-V3够用)。

---

### 2.5 FactorMiner — 自进化Agent+经验记忆

> 来源: arXiv 2602.14670

**架构**: 三大系统协同
1. **模块化技能架构**: 60+ GPU加速金融算子，多阶段验证管道
2. **经验记忆**: 挖掘状态+结构化经验(推荐/禁止方向)+战略洞察
3. **Ralph Loop**: Retrieve记忆 → Generate候选 → Evaluate评估 → Distill蒸馏回记忆

**LLM**: Gemini 3.0 Flash

**核心创新: 跨轮次经验积累**:
- **技能记忆(Skills)**: 成功的因子生成"配方"被提炼为可复用技能
- **经验记忆(Experience)**: 失败的尝试也被结构化记录，避免重复踩坑
- **禁止区域追踪**: 记录已耗尽的高相关家族，避免冗余探索
- **替换机制**: IC≥0.10 且 1.3×优于相关peer时允许替换
- 去重用**Spearman相关性**(阈值0.5, A股), 不是AST

**性能(CSI500, OOS 2025, Top-40因子)**:

| 市场 | IC(%) | ICIR |
|------|-------|------|
| CSI500 | 8.25 | 0.77 |
| CSI1000 | 7.78 | 0.76 |
| HS300 | 7.46 | 0.38 |
| IC加权Top-40组合(CSI500) | **15.11** | **1.31** |

**⚠️ 频率注意**: FactorMiner使用**10分钟K线**，预测下一个10分钟收益。当前我们无分钟数据，但如果未来引入日内高频子策略（如日度FastRanking或日内事件驱动），其方法论有参考价值。当前阶段不适用。

**与我们设计的对比**:
- 我们的`mining_knowledge`表已有`hypothesis`/`failure_reason`/`failure_detail`字段
- 缺少的是**蒸馏层**——把"第N轮turnover类因子IC=1.2%失败"总结为"换手率类因子在当前市场可能饱和"这种高阶经验
- 蒸馏可以用LLM完成：每10轮挖掘后，把成功/失败记录喂给DeepSeek总结模式

**⭐ 可采纳的核心思想**:
1. **P1: 经验蒸馏** — 每N轮用LLM对mining_knowledge做总结，提炼高阶规律。2天。
2. **P1: 禁止区域追踪** — 结构化记录"VWAP变体全部与turnover corr>0.5"等已耗尽方向。2天。
3. **P2: 技能库** — 成功因子的生成pattern提炼为模板，加速后续生成。3天。
4. **P2: 替换机制** — IC显著优于最相关因子时可替换(不只append)。1天。

**不采纳**: 10分钟高频(数据/策略框架不兼容)、Gemini LLM(用DeepSeek)、60+ GPU算子(过度工程)。

---

### 2.6 Qlib Alpha158 + GP工具链

> 来源: Microsoft Qlib (github.com/microsoft/qlib, 16k+ stars)
> 详细研究: docs/research/QLIB_GP_FACTOR_MINING_RESEARCH.md

**Alpha158因子体系(158个纯量价因子)**:
- **Group A: KBAR(9个)** — 单根K线形态(KMID/KLEN/KUP/KLOW/KSFT等)，IC<2%单独弱，ensemble有用
- **Group B: Price(4个)** — OPEN/HIGH/LOW/VWAP相对close的比率
- **Group C: Rolling(29指标×5窗口=145个)** — Trend(ROC/MA/BETA/RSQR/RESI)、Volatility(STD/QTLU/QTLD/RSV)、Timing(IMAX/IMIN/IMXD)、Price-Volume相关(CORR/CORD/CNTP/CNTN/CNTD)、Volume趋势(VMA/VSTD/WVMA)

**Alpha158与我们34因子的重叠分析**:

| 重叠类型 | 因子 | 说明 |
|---------|------|------|
| 直接重叠(~60%) | volatility_20↔STD(20), reversal_20↔ROC(20), momentum系列↔ROC系列 | 实现方式几乎相同 |
| 部分重叠 | turnover_mean_20↔VMA(20), IVOL↔RESI | 归一化方式不同 |
| **我们独有** | **amihud_20, bp_ratio, mf_divergence, vwap_bias, rsrs_score** | Alpha158无基本面/资金流/微结构 |
| **Alpha158独有** | BETA, RSV, CORD, CNTP/CNTD, QTLU/QTLD | 我们的GAP，建议补充 |

**关键发现**: Alpha158是纯量价技术因子库。我们的差异化优势在于基本面(bp_ratio/ep_ratio)、资金流(mf_divergence)、微结构(amihud/vwap/rsrs)三个Alpha158完全不覆盖的维度。

**Alpha158 A股社区表现**:
- LightGBM + Alpha158 CSI300: ~24%年化, ~10%回撤(可能过拟合)
- 单因子中STD/CORR/SUMP/SUMN系列IC最强
- 量相关因子(VMA/VSTD/WVMA)在A股比美股更强
- T+2 label设计已适配A股T+1结算

**GP工具链对比**:

| 特性 | gplearn | DEAP | PySR |
|------|---------|------|------|
| 速度 | 慢 | 中等 | 快(10-100x, Julia) |
| 金融算子 | ❌无 | ✅自定义 | ⚠️需Julia侧实现 |
| 面板数据(3D) | ❌仅2D | ✅自定义 | ❌仅2D |
| 岛屿模型 | ❌ | ✅migRing原生 | ✅原生 |
| 多目标(NSGA-II) | ❌ | ✅ | ❌ |
| A股券商研报 | 常见(入门级) | 华泰/申万均用 | 罕见 |
| **结论** | **不推荐**(2D限制) | **首选** | 备选(Julia依赖) |

**DEAP岛屿模型设计(推荐)**:
- 4岛×200-500个体, 异构适应度(IC/ICIR/IC+新颖度/IC衰减抗性)
- Ring拓扑, 每50代迁移Top-5精英
- 预计300-500代, 8核并行~2-3小时(数据预计算+缓存后)
- 金融算子集: 13个时序(ts_mean/ts_std/ts_corr等) + 4个截面(cs_rank/cs_zscore等) + 12个算术

**反拥挤4层方案**:
1. **L1(瞬时)**: 语义哈希去重 — 因子输出向量binned hash
2. **L2(快速)**: Spearman相关 < 0.6(比CLAUDE.md设计的0.5-0.6一致)
3. **L3(进化中)**: 新颖度作为NSGA-II二维适应度
4. **L4(事后)**: 全部GP因子聚类+多样性代表选择

**Alpha158缺口(建议补充5个族×5窗口=25因子)**:
- BETA: 价格趋势斜率(线性回归)
- RSV: (close-min)/(max-min) Williams %R
- CORD: 收盘价与成交量的Rank相关
- CNTP/CNTD: 上涨/下跌天数占比(方向性情绪)

**⭐ 可采纳的核心思想**:
1. **P0: DEAP作为GP引擎** — 岛屿模型+NSGA-II+自定义金融算子。核心工作量2-3周。
2. **P0: Alpha158因子目录作为参考** — 补充BETA/RSV/CORD/CNTP/CNTD 5个新族。2-3天。
3. **P1: 反拥挤4层级联** — 与AST去重(§2.4)组合为完整去重方案。2天。
4. **P1: 表达式解析器** — GP输出Qlib风格表达式字符串，解析为pandas操作。3天。
5. **P2: PySR快速预筛** — 简单表达式用PySR加速探索，复杂结构用DEAP精炼。Phase 3。

**不采纳**: Qlib完整依赖(数据格式耦合)、Qlib Expression Engine(20+包依赖)、gplearn(2D限制)。

---

## 3. 横向对比矩阵

> 评分标准: 1-5分(5=最优)。分数越高越适合我们的场景。

| 项目 | A股适用(25%) | 实现复杂度(20%) | LLM成本(15%) | 兼容性(15%) | 因子质量(10%) | 抗过拟合(10%) | 可维护(5%) | **加权总分** |
|------|:-----------:|:--------------:|:-----------:|:-----------:|:-----------:|:-----------:|:---------:|:----------:|
| **QuantaAlpha** | 4 | 2 | 5 | 3 | 5 | 4 | 4 | **3.55** |
| **RD-Agent** | 3 | 1 | 3 | 2 | 4 | 3 | 3 | **2.55** |
| **FactorEngine** | 4 | 3 | 5 | 4 | 4 | 4 | 2 | **3.75** |
| **AlphaAgent** | 4 | 3 | 5 | 3 | 3 | 5 | 3 | **3.60** |
| **FactorMiner** | 2 | 2 | 4 | 2 | 4 | 4 | 2 | **2.70** |
| **Qlib Alpha158** | 4 | 5 | 5 | 4 | 3 | 2 | 5 | **4.05** |
| **传统GP(DEAP)** | 4 | 4 | 5 | 5 | 3 | 3 | 4 | **4.15** |

### 评分理由

**A股适用性(25%)**:
- QuantaAlpha(4): CSI300/500原生，HuggingFace数据，但无交易成本建模
- RD-Agent(3): CSI300测试，但Windows不兼容+Qlib强耦合
- FactorEngine(4): CSI300 OOS 2017-2024验证，最长回测期
- AlphaAgent(4): CSI500 4年OOS稳定，KDD 2025学术认可
- FactorMiner(2): 10分钟K线高频，当前数据不兼容
- Qlib Alpha158(4): A股社区广泛使用，但纯量价无基本面
- DEAP(4): 华泰/申万研报均用，A股GP因子挖掘标准工具

**实现复杂度(20%, 高分=容易实现)**:
- QuantaAlpha(2): 轨迹级进化+语义验证复杂，完整集成9-15天
- RD-Agent(1): 5阶段+Qlib耦合+Docker+Windows不兼容
- FactorEngine(3): 核心逻辑/参数分离清晰，但程序级进化复杂
- AlphaAgent(3): 三Agent+AST去重相对模块化
- FactorMiner(2): 经验记忆+蒸馏+技能库复杂度高
- Qlib Alpha158(5): 只需参考公式自己实现，零依赖
- DEAP(4): 成熟库，文档完善，中文社区资源丰富

**LLM成本(15%, 高分=成本低)**:
- QuantaAlpha(5): DeepSeek $0.10-0.15/轮
- RD-Agent(3): GPT-4o $10/轮，DeepSeek ~$0.50-1.00
- FactorEngine(5): DeepSeek $1-3/200迭代
- AlphaAgent(5): GPT-3.5级LLM即可，成本极低
- FactorMiner(4): Gemini Flash，成本低但轮次多
- Qlib Alpha158(5): 无LLM调用
- DEAP(5): 无LLM调用

**与现有设计兼容(15%)**:
- QuantaAlpha(3): 轨迹进化需重构Engine 3架构
- RD-Agent(2): Qlib耦合严重，Windows不兼容
- FactorEngine(4): 逻辑/参数分离与GP引擎天然互补
- AlphaAgent(3): AST去重可独立集成，但整体依赖Qlib
- FactorMiner(2): 高频数据+GPU算子与当前栈不兼容
- Qlib Alpha158(4): 因子公式可直接移植到factor_engine.py
- DEAP(5): 完全兼容，GP引擎参数已在param_defaults注册

**因子质量(10%)**:
- QuantaAlpha(5): IC=0.1501最高(日频)，CSI300/500/S&P500跨市场
- RD-Agent(4): IC=0.0532, Sharpe=1.74
- FactorEngine(4): IC=0.0474, Sharpe=1.01
- AlphaAgent(3): IC=0.0212(低)但4年不衰减
- FactorMiner(4): CSI500 IC=8.25%(高频)
- Qlib Alpha158(3): 基线水平，LightGBM增强后~24%年化
- DEAP(3): 取决于算子集设计和适应度函数

**抗过拟合(10%)**:
- QuantaAlpha(4): 复杂度惩罚+语义一致性，但无bootstrap CI
- RD-Agent(3): IC去重(>0.99)阈值过松
- FactorEngine(4): 逻辑/参数分离天然抗过拟合+FS公式
- AlphaAgent(5): 三重正则化(AST+参数+原创性)最系统
- FactorMiner(4): 经验记忆避免重复，但Spearman阈值0.5偏严
- Qlib Alpha158(2): 无特殊抗过拟合，固定因子集
- DEAP(3): 需自己实现反拥挤和复杂度控制

---

## 4. 技术选型建议

### 4.1 核心结论: 提取模式，不引入依赖

**不推荐直接集成任何一个框架**。原因:
1. 每个项目都有硬伤(Windows不兼容/Qlib耦合/高频数据/未开源)
2. 1人团队维护外部框架的运维成本超过收益
3. 我们的4引擎架构(暴力枚举/开源导入/LLM三Agent/GP进化)本身是正确的
4. 前沿项目的核心创新可以作为**模式**融入现有设计，不需要代码依赖

**推荐方案: "站在巨人肩膀上改进自有设计"**

| 层级 | 选型 | 来源 |
|------|------|------|
| GP引擎 | **DEAP**(加权总分4.15最高) | 直接依赖 |
| 因子参考库 | **Alpha158公式**(参考实现，不依赖Qlib) | 设计参考 |
| 参数优化 | **Optuna TPE**(逻辑/参数分离) | FactorEngine模式 |
| LLM Agent | **DeepSeek V3**(三Agent架构) | 自有Engine 3 |
| 去重引擎 | **AST+Spearman级联**(3层) | AlphaAgent模式 |
| 搜索调度 | **Thompson Sampling Bandit** | RD-Agent模式 |
| 经验管理 | **经验链+蒸馏** | FactorEngine+FactorMiner模式 |
| 复杂度控制 | **三重正则化** | AlphaAgent+QuantaAlpha模式 |

### 4.2 对现有4引擎设计的改进总结

**Engine 1(暴力枚举)**: 无需改动，保持50模板最简设计。

**Engine 2(开源导入)**: 补充Alpha158缺口因子(BETA/RSV/CORD/CNTP/CNTD 5族×5窗口=25个)。

**Engine 3(LLM三Agent)**:
| 改进 | 来源 | 优先级 | 工作量 |
|------|------|--------|--------|
| 经验链(CoE)注入Prompt | FactorEngine | P0 | 1天 |
| AST去重替代embedding | AlphaAgent | P0 | 2天 |
| 结构化失败反馈 | FactorMiner | P0 | 1天 |
| 多样化规划(10方向并行) | QuantaAlpha | P0 | 1天 |
| 复杂度惩罚 | QuantaAlpha+AlphaAgent | P0 | 0.5天 |
| 假设对齐检查 | AlphaAgent | P1 | 1天 |
| 自动debug循环(3轮) | FactorEngine | P1 | 2天 |
| 经验蒸馏(每10轮) | FactorMiner | P1 | 2天 |
| Thompson Sampling方向调度 | RD-Agent | P1 | 2天 |
| 语义一致性验证 | QuantaAlpha | P2 | 1天 |
| 轨迹级进化 | QuantaAlpha | P2 | 3-5天 |
| 程序模板(LLM骨架+Bayesian参数) | FactorEngine | P2 | 5-7天 |

**Engine 4(GP进化)**:
| 改进 | 来源 | 优先级 | 工作量 |
|------|------|--------|--------|
| 逻辑/参数分离(GP结构+Optuna参数) | FactorEngine | P0 | 2-3天 |
| 适应度公式升级(FS=IC+ICIR+RankIC+RankICIR) | FactorEngine | P0 | 0.5天 |
| 反拥挤4层级联 | DEAP+AlphaAgent | P0 | 2天 |
| 数据预计算+Parquet缓存 | FactorEngine | P1 | 1天 |
| 种子初始化(从34+已测因子) | FactorEngine | P1 | 1天 |
| 异构适应度岛屿(IC/ICIR/Novelty/Decay) | 研究综合 | P1 | 已设计 |

### 4.3 P0改进项汇总(立即可执行)

**总工作量**: ~12天(2周Sprint)

| # | 改进 | 引擎 | 天数 | 预期收益 |
|---|------|------|------|---------|
| 1 | AST去重引擎 | 全引擎共享 | 2 | 去重准确率+81%(AlphaAgent数据) |
| 2 | 逻辑/参数分离 | Engine 4 | 2.5 | GP迭代效率提升(不浪费在参数优化上) |
| 3 | 经验链注入Prompt | Engine 3 | 1 | LLM因子产出率提升(FE: 99%可执行率) |
| 4 | 结构化失败反馈 | Engine 3 | 1 | 避免重复失败尝试 |
| 5 | 多样化规划 | Engine 3 | 1 | 10方向并行vs串行，搜索效率×10 |
| 6 | 复杂度惩罚 | Engine 3+4 | 0.5 | ARR+8.44%(QuantaAlpha消融) |
| 7 | 适应度公式升级 | Engine 4 | 0.5 | 综合IC+ICIR+RankIC+RankICIR |
| 8 | 反拥挤级联 | Engine 4 | 2 | 避免GP收敛到同族因子 |
| 9 | Alpha158缺口补充 | Engine 2 | 2.5 | +25因子，覆盖率60%→85% |

---

## 5. 对DEV_FACTOR_MINING.md的修改建议

### 5.1 Engine 3 LLM Agent改进

**当前设计**: Idea Agent(R1) → Factor Agent(V3) → Eval Agent(自动)，串行3步。

**基于前沿研究的改进**:

| # | 改进项 | 来源 | 优先级 | 工作量 |
|---|--------|------|--------|--------|
| 1 | **经验链(CoE)注入Prompt** | FactorEngine | P0 | 1天 |
| 2 | **AST去重替代embedding相似度** | AlphaAgent | P0 | 2天 |
| 3 | **结构化失败反馈** | FactorMiner | P0 | 1天 |
| 4 | **假设对齐检查** | AlphaAgent | P1 | 1天 |
| 5 | **自动debug循环(最多3轮)** | FactorEngine | P1 | 2天 |
| 6 | **经验蒸馏(每10轮)** | FactorMiner | P1 | 2天 |
| 7 | **搜索方向UCB1+自适应** | 我们已有设计 | P1 | 已设计 |

**Prompt改进建议**:
- Idea Agent System Prompt增加: 最近5轮的经验链摘要(不是原始记录)
- Factor Agent增加: auto-debug循环，出错后注入错误信息重试(当前设计已有，但需要结构化)
- 反馈Prompt增加: 蒸馏后的高阶规律("该类别因子饱和"/"该数据源已充分探索")

### 5.2 Engine 4 GP引擎改进

**当前设计**: 标准GP(表达式树, 岛屿模型, 反拥挤)。

**基于前沿研究的改进**:

| # | 改进项 | 来源 | 优先级 | 工作量 |
|---|--------|------|--------|--------|
| 1 | **逻辑/参数分离** | FactorEngine | P0 | 2-3天 |
| 2 | **适应度公式升级** | FactorEngine | P0 | 0.5天 |
| 3 | **数据缓存层** | FactorEngine | P1 | 1天 |
| 4 | **种子初始化(从已有因子)** | FactorEngine | P1 | 1天 |

**逻辑/参数分离的具体实现**:
```
当前: GP进化整棵表达式树，包括窗口参数节点
     ts_mean($close, 20) / ts_std($close, 20)
     ↑ 结构和参数混在一起进化

改进: GP只进化结构骨架(终端参数为占位符)
     ts_mean($close, ?w1) / ts_std($close, ?w2)
     → Optuna/TPE搜索最优 w1, w2

     每个GP个体的评估:
     1. 从表达式树提取参数占位符
     2. Optuna TPE优化参数(10-50次trial，本地CPU)
     3. 用最优参数计算IC作为适应度
```

### 5.3 新增机制

**基于前沿研究新增**:

| # | 机制 | 来源 | 与现有架构的集成点 |
|---|------|------|-----------------|
| 1 | **AST去重引擎** | AlphaAgent | 替代当前计划的embedding相似度(mining_knowledge.originality_score) |
| 2 | **经验知识库扩展** | FactorEngine+FactorMiner | 扩展mining_knowledge表schema |
| 3 | **因子蒸馏器** | FactorMiner | 新Celery task: 每10轮触发LLM总结 |
| 4 | **程序模板引擎(Phase1+)** | FactorEngine | Engine 3的增强版: LLM生成骨架+Bayesian填参数 |

**mining_knowledge表Schema扩展**:
```sql
-- 新增列
ALTER TABLE mining_knowledge ADD COLUMN
    experience_chain JSONB,        -- 经验链: [{round, change, ic_delta, reason}]
    ast_hash VARCHAR(64),          -- AST结构哈希(用于去重)
    param_slots JSONB,             -- 参数化槽位: {"w1": 20, "w2": 10}
    distilled_insight TEXT,        -- 蒸馏后的高阶洞见
    parent_factor_id INT;          -- 父因子(进化来源)
```

---

## 6. 落地计划

### 6.1 当前因子挖掘状态总结

**已完成**:
- `factor_engine.py`: 18个手工因子计算函数
- `factor_profile.py`: IC衰减分析+半衰期拟合+调仓频率推荐
- `factor_analyzer.py`: 单因子完整分析(IC时序/分组收益/IC衰减/相关矩阵/覆盖率)
- `param_defaults.py`: GP引擎参数已注册(5个参数: population/generations/crossover/mutation/threshold)
- FACTOR_TEST_REGISTRY: 74个因子已测试(24 PASS / 32 FAIL / 6 CONDITIONAL / 12 其他)
- 8项Factor Gate Pipeline: 完整设计(G1-G8)
- mining_knowledge表: Schema已设计

**未实现**:
- Engine 1: 暴力枚举(50模板)
- Engine 2: 开源导入(Alpha158/Alpha101/TA-Lib)
- Engine 3: LLM三Agent闭环(Idea/Factor/Eval)
- Engine 4: GP遗传编程(岛屿模型)
- MiningScheduler: UCB1方向选择
- FactorSandbox: 沙箱执行
- 知识库管理: mining_knowledge CRUD
- 因子生命周期状态机: candidate→active→degraded→retired

### 6.2 推荐实施顺序

```
Phase 1a: 基础设施 (1 Sprint, ~2周)
  ├── Engine 1: 暴力枚举 (最简单, 50模板, 0成本)
  ├── 沙箱执行器 (FactorSandbox)
  ├── mining_knowledge表创建+CRUD
  ├── 因子生命周期状态机
  └── 验收: 50模板枚举跑通，≥5个新因子通过Gate

Phase 1b: GP引擎 (1 Sprint, ~2周)
  ├── Engine 4: GP表达式树 (DEAP库)
  ├── ⭐ 逻辑/参数分离 (Optuna TPE)
  ├── ⭐ 适应度公式升级 (FactorEngine FS)
  ├── 岛屿模型(3-4子群)
  ├── 数据缓存层
  └── 验收: GP跑100代，≥3个因子通过Gate且与暴力枚举无重叠

Phase 1c: LLM Agent (1 Sprint, ~2周)
  ├── Engine 3: Idea Agent + Factor Agent + Eval Agent
  ├── DeepSeek API集成
  ├── ⭐ 经验链(CoE)注入Prompt
  ├── ⭐ AST去重引擎
  ├── ⭐ 自动debug循环(3轮)
  ├── MiningScheduler (UCB1)
  └── 验收: LLM生成10轮，≥2个因子通过Gate，成本<$5

Phase 1d: 高级功能 (1 Sprint, ~2周)
  ├── Engine 2: Alpha158/Alpha101导入
  ├── ⭐ 经验蒸馏 (每10轮LLM总结)
  ├── ⭐ 知识注入种子 (从34+已测因子)
  ├── ⭐ 程序模板引擎 (LLM骨架+Bayesian参数)
  ├── 前端: 因子实验室页面(最小版)
  └── 验收: 4引擎全部运行，因子产出率>10%/轮
```

**⭐标记 = 基于本次前沿研究的改进项**

### 6.3 验收标准

| 阶段 | 指标 | 标准 |
|------|------|------|
| Phase 1a | 暴力枚举产出率 | ≥10%(50模板中≥5个通过Gate) |
| Phase 1b | GP vs 暴力枚举增量 | GP找到≥3个暴力枚举未覆盖的因子 |
| Phase 1c | LLM产出率 | ≥20%(10轮中≥2个通过Gate) |
| Phase 1c | LLM成本 | <$5/10轮(DeepSeek) |
| Phase 1d | 4引擎总产出 | ≥10个新candidate因子 |
| Phase 1d | 因子质量 | 至少1个新因子IC>5%且corr<0.5与v1.1 |

### 6.4 成本预算

| 项目 | 月成本估算 | 说明 |
|------|-----------|------|
| DeepSeek API (Engine 3) | ¥30-100 | ~200迭代/周, $1-3/200迭代 |
| GPU电费 (GP+LightGBM) | ¥50 | RTX 5070本地训练 |
| 无额外依赖 | ¥0 | DEAP/Optuna/scipy均免费开源 |
| **月总计** | **¥80-150** | 远低于预算上限 |

---

## 7. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LLM生成因子全部不通过Gate | 中 | 浪费API成本 | 先用暴力枚举验证Gate Pipeline正常 |
| GP收敛到已有因子附近 | 高 | 无新发现 | AST去重+反拥挤阈值 |
| 沙箱执行安全问题 | 低 | 系统被恶意代码攻击 | AST静态检查+子进程隔离+内存限制 |
| DeepSeek API不稳定 | 中 | 中断挖掘流程 | 离线缓存+GP引擎不依赖API |
| 过拟合(IC高但OOS差) | 高 | 虚假因子 | 8项Gate+OOS验证+FDR校正(Harvey 2016) |

---

## 8. 参考文献

1. Lin, Q. et al. (2026). "FactorEngine: A Program-level Knowledge-Infused Factor Mining Framework." arXiv:2603.16365.
2. QuantaAlpha Team (2026). "QuantaAlpha: An Evolutionary Framework for LLM-Driven Alpha Mining." arXiv:2602.07085.
3. Microsoft Research (2025). "RD-Agent: Multi-Agent System for Research & Development." GitHub: microsoft/RD-Agent.
4. AlphaAgent Team (2025). "AlphaAgent: Regularized Exploration for Alpha Factor Mining." KDD 2025.
5. FactorMiner Team (2026). "FactorMiner: Self-Evolving Agent with Skills and Experience Memory." arXiv:2602.14670.
6. Microsoft Research (2022). "Qlib: An AI-oriented Quantitative Investment Platform." GitHub: microsoft/qlib.
7. AlphaLogics Team (2026). "Market Logic-Driven Multi-Agent System for Formulaic Alpha Generation." arXiv:2603.20247.
8. AlphaForge Team (2025). "Mine and Dynamically Combine Formulaic Alpha Factors." AAAI 2025. arXiv:2406.18394.
9. Harvey, C., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." Review of Financial Studies, 29(1).
10. gplearn documentation. https://gplearn.readthedocs.io/
11. DEAP documentation. https://deap.readthedocs.io/
12. PySR documentation. https://astroautomata.com/PySR/
（更多参考文献待研究完成后补充）
