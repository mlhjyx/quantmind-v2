# Qlib + RD-Agent 技术调研

**日期**: 2026-04-10 | **来源**: V3升级方案 + Step 6-H反思

---

## 1. Qlib vs QuantMind 7维组件对比

| 组件 | QuantMind (当前) | Qlib | 差距 |
|------|-----------------|------|------|
| **数据格式** | PostgreSQL + Parquet缓存 | 自定义bin格式(极快) | Qlib更快但需迁移 |
| **因子库** | 5 CORE + 53 DB因子 | Alpha158(158因子, 即开即用) | Qlib覆盖更广 |
| **ML Pipeline** | LightGBM(验证无效) | Model Zoo(LightGBM/XGBoost/NN/Transformer) | Qlib集成更完整 |
| **回测引擎** | 事件驱动(841s/12yr) | 向量化(<10s/12yr) | Qlib快100x |
| **Portfolio优化** | 等权Top-N | TopkDropout + MV优化 | Qlib更先进 |
| **信号生成** | SignalComposer等权 | IC加权 + Alpha组合 | Qlib更灵活 |
| **因子评估** | ic_calculator + profiler | alphalens集成 | 各有特色 |

### Qlib 优势
- A股Alpha158开箱即用
- 向量化回测极快
- Model Zoo丰富
- 社区活跃(18K stars)

### Qlib 风险
- 数据格式迁移成本高(PG→bin)
- Windows兼容性不确定
- 自定义策略的灵活度
- 与现有DataPipeline的集成

---

## 2. RD-Agent(Q) vs DEV_AI_EVOLUTION.md 7维架构对比

| 维度 | DEV_AI_EVOLUTION (设计) | RD-Agent(Q) (已实现) | 对比 |
|------|----------------------|---------------------|------|
| **因子挖掘** | GP(DEAP) + LLM生成 | LLM生成 + 自动验证 | RD-Agent更成熟 |
| **模型选择** | 手动A/B测试 | 自动因子-模型联合优化 | RD-Agent2倍优于分开优化 |
| **评估Pipeline** | Gate G1-G8 | 自动IC/Sharpe/回撤评估 | 类似 |
| **反馈循环** | 4 Agent(设计未实现) | LLM自动分析失败原因 | RD-Agent已实现 |
| **知识积累** | 无 | 自动记录经验(experience pool) | RD-Agent优势 |
| **人工干预** | 需要 | 最小化(半自动) | RD-Agent更自动 |
| **实现状态** | 0行代码 | 开源可用(Microsoft) | RD-Agent完胜 |

### 关键发现
RD-Agent(Q) 在A股的实验中证明:
- 因子-模型联合优化比分开优化好2倍
- 自动生成的因子IC有意义(非随机)
- 减少人工因子工程时间90%+

---

## 3. 三个升级选择

### 选择A：Qlib集成（推荐评估）
**适用条件**: Qlib A股demo可用 + 数据迁移可行 + Windows兼容
**工作量**: 2-3周(数据迁移+回测迁移+ML迁移)
**收益**: 回测100x加速 + Model Zoo + Portfolio优化
**风险**: 数据格式迁移成本 + 自定义策略灵活度受限

### 选择B：自建升级
**适用条件**: Qlib不适用(数据不兼容/Windows问题)
**工作量**: 3-4周(向量化回测+riskfolio-lib+End-to-End实验)
**收益**: 完全可控 + 渐进式升级
**风险**: 重复造轮子 + 开发时间长

### 选择C：混合方案（最可能）
**适用条件**: Qlib部分可用
**方案**: 
- 数据层保持PG+Parquet（成熟稳定）
- 回测层引入VectorBT或向量化重写（中间路线）
- ML层引入RD-Agent做因子挖掘（独立模块）
- Portfolio层引入riskfolio-lib（独立模块）
**工作量**: 2周(RD-Agent) + 1周(riskfolio) + 1周(向量化)
**收益**: 每个组件独立评估，渐进式升级
**风险**: 集成复杂度

---

## 4. 阶段0技术调研计划（2天）

| 任务 | 内容 | 时间 | 决策点 |
|------|------|------|--------|
| 0.1 | 安装Qlib, 跑A股Alpha158+LightGBM demo | 半天 | 能否在Windows运行 |
| 0.2 | 评估Qlib数据格式与PG/Parquet兼容性 | 半天 | 迁移成本是否可接受 |
| 0.3 | 安装RD-Agent, 跑一次自动因子挖掘demo | 半天 | 生成的因子IC是否有意义 |
| 0.4 | 评估RD-Agent与factor_engine集成可行性 | 半天 | 能否对接现有Gate评估 |

**决策矩阵**:
- Qlib可用 + RD-Agent可用 → 选择A或C
- Qlib不可用 + RD-Agent可用 → 选择C(RD-Agent + 自建升级)
- 都不可用 → 选择B
