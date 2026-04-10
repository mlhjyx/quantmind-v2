# QuantMind V2 因子体系升级方案 V4

**基于Step 6系列实验结论 + Qlib/RD-Agent研究 + 设计-实现差距反思**
**日期**: 2026-04-10 | **版本**: v4.0

---

## 第一部分：V2方案回顾与反思

### 1.1 V2方案执行总结

V2方案（v1.0→v2.0）覆盖了32篇论文研究和10个审计问题。
第一阶段（验证线）和第二阶段（因子体系建设）的核心任务已完成。

**Step 6系列（D/E/F/G/H）四轮验证链的收束结论：**

| 轮次 | 假设 | 结果 |
|------|------|------|
| 6-D | 策略可能过拟合 | 有真alpha(t=2.90)但regime不稳定(std=1.52) |
| 6-E | 因子IC在衰减 | IC没衰减(retention 0.84-1.04)，问题在持仓层 |
| 6-F | 因子层优化可行 | 替换不显著(p=0.92)，完全SN损11%，0/21 fragile |
| 6-G | Modifier层干预 | Partial SN(b=0.50)唯一有效，Vol/DD/组合全失败 |
| 6-H | 实盘化+ML验证 | SN inner OK，LightGBM 17因子Sharpe=0.09(IC正但选股无效) |

**当前最优基线：** SN b=0.50, Sharpe=0.68, MDD=-39.35%, WF OOS=0.6521

### 1.2 11份设计文档为什么没实现

| 文档 | 设计了什么 | 实现了多少 | 未实现原因 |
|------|----------|----------|----------|
| DESIGN_V5.md | 完整系统架构(500+页) | ~20% | 过度设计，范围太大 |
| DEV_BACKEND.md | 17个Service+57端点 | ~30% | 依赖前端/AI/外汇模块 |
| DEV_BACKTEST_ENGINE.md | 3-Step引擎+Rust | Step 1 only | Step 2/3/Rust未启动 |
| DEV_FACTOR_MINING.md | GP+LLM+暴力枚举 | GP部分 | AI闭环未实现 |
| DEV_FRONTEND_UI.md | 12页面+53组件 | 未确认 | 优先级低于后端 |
| DEV_AI_EVOLUTION.md | 4 Agent+Pipeline | 0行代码 | 依赖所有其他模块 |
| DEV_PARAM_CONFIG.md | 220个可配置参数 | ~50个 | 很多参数的功能未实现 |
| DEV_SCHEDULER.md | 28个定时任务 | ~5个 | 功能不存在则调度无意义 |
| DEV_FOREX.md | 完整外汇系统 | mt5_adapter only | Phase 2+计划 |
| DEV_NOTIFICATIONS.md | 多渠道通知 | 钉钉Webhook | 简单通知够用 |
| ML_WALKFORWARD_DESIGN.md | 完整ML WF | 部分实现 | OOM问题阻塞 |

**根因分析：**
1. 先写500页设计再动手→设计与现实脱节
2. 模块间互相依赖形成死锁→没有一个能独立启动
3. 没有MVP定义→不知道何时算"完成"
4. 实验发现的问题没有反馈回设计文档→文档越来越过时
5. 自建一切而非利用现有方案→Qlib/RD-Agent已经实现了大部分设计

### 1.3 V4方案的原则

**原则1：目标驱动而非功能驱动**
不问"系统应该有什么"，问"要让Sharpe从0.68到1.0需要什么"。

**原则2：每个任务独立可执行**
不依赖其他未实现模块。每个任务有明确的输入、输出、验收标准。

**原则3：先实验后设计**
每个方向先做2天实验验证可行，再写实现计划。不预设结论。

**原则4：站在巨人肩膀上**
能用Qlib/RD-Agent/VectorBT的就不自己写。DESIGN_V5.md原则5（最小复杂度）的升级版。

**原则5：文档跟随代码**
不维护"理想架构设计"——只维护"当前系统实际状态"和"下一步计划"。

### 1.4 V3方案执行总结（2026-04-10）

**阶段0：技术调研 ✅ 完成**
- Qlib: ⚠️部分可用 — pyqlib 0.9.7 Windows pip安装OK，Alpha158提取6个新因子类别(RSQR/RESI/IMAX/IMIN/QTLU/CORD)，数据层(.bin格式需双份维护)/回测引擎(无PMS/涨跌停/历史税率)不迁移
- RD-Agent: ❌不适用 — Docker硬依赖+Windows Issue #1064+Claude API未验证，三重阻断
- riskfolio-lib 7.2.1 + vectorbt 0.28.5 已装入主.venv
- **决策：路线C（混合）** — 自建核心 + Alpha158因子借鉴 + riskfolio-lib Portfolio优化
- 详见 `docs/research-kb/findings/qlib-rdagent-research.md`

**阶段1.1 Step 6-H成果落地 ✅**
- SN b=0.50 PT激活（pt_live.yaml）
- CLAUDE.md全面刷新（失败方向+基线数字+铁律25-28）
- 冒烟测试8/8通过

**阶段1.3 清理遗留 ✅** (commit fe5efcb)
- P0 SN config修复、IC验证、凭证统一、DDL注释、审计

**PT暂停+清仓 (2026-04-10)**
- 原因：P0 SN config需.env手动验证 + 框架升级中 + 等权Top-N天花板已确认
- 重启条件：Phase 1+2核心完成 + OOS Sharpe > 0.6521

---

## 第二部分：当前系统真实状态

### 2.1 实际在运行的东西

```
数据层：
  PostgreSQL 16.8 + TimescaleDB 2.26.0
  - factor_values 501M行 hypertable (73GB)
  - klines_daily 11.7M行 (1.98GB)
  - stock_status_daily 12M行
  - minute_bars 139M行 (25GB, 数据~36%完成)
  Parquet缓存 cache/backtest/ (936MB)
  Redis 5.0.14.1 + StreamBus (10 streams)

信号层：
  5因子等权(turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio)
  SignalComposer → PortfolioBuilder → Top-20
  Size-neutral beta=0.50 (inner实现, 待激活)
  月度调仓

回测层：
  SimpleBacktester (事件驱动, Phase 1.1优化后12yr 14.6s, 原841s)
  Walk-Forward 5-fold (已修复, 可用)
  ic_calculator.py (铁律19标准)

执行层：
  QMT Paper Trading (Servy管理4服务)
  PMS v1.0 (position-level利润保护)

ML层：
  ml_engine.py (LightGBM, GPU支持, Parquet路径已通)
  但: 17因子LightGBM Sharpe=0.09 (IC正但选股无效)

AI层：
  0行代码。设计完整但未实现。

前端层：
  设计完整(12页面)。实现状态未确认。
```

### 2.2 已验证的关键数字

| 指标 | 值 | 来源 |
|------|-----|------|
| 12yr Sharpe (base) | 0.5309 | Step 6-D |
| 12yr Sharpe (SN b=0.50) | 0.68 | Step 6-H |
| 12yr MDD (SN b=0.50) | -39.35% | Step 6-H |
| WF OOS Sharpe (SN b=0.50) | 0.6521 | Step 6-H |
| FF3 Alpha t-stat | 2.90 | Step 6-D |
| SMB beta | ~1.09 (定性) | Step 6-D |
| IC retention | 0.84-1.04 | Step 6-E |
| PASS因子数 (batch_gate_v2) | 17/53 | Step 6-G |
| 噪声鲁棒性 fragile数 | 0/21 | Step 6-F |

### 2.3 已关闭的路径（不再重试）

- 因子替换 (p=0.92不显著)
- 完全Size-neutral (损11% Sharpe)
- Vol-Targeting (全部损alpha)
- Drawdown-Aware sizing (MDD反而更差)
- Regime线性检测 (5指标全p>0.05)
- Regime动态beta (static全面优于dynamic)
- LightGBM 5因子 (Sharpe=0.68 < 等权0.83)
- LightGBM 17因子 (Sharpe=0.09, IC正但选股无效)
- PMS v2.0 portfolio-level (p=0.655验证无效)
- 风险平价G2 / 动态仓位G2.5 / 双周调仓
- mf_divergence (IC=-2.27%)
- LLM自由生成因子 / 同因子换ML模型

---

## 第三部分：从0.68到1.0的差距分析

### 3.1 Sharpe 0.68 → 1.0 需要什么

当前Sharpe=0.68意味着年化收益~16%、波动率~23%。
目标Sharpe=1.0意味着：
- 保持波动率23%→年化收益需要23%（+7pp）
- 或保持收益16%→波动率需要降到16%（-7pp）
- 或两者兼顾

### 3.2 收益增量的可能来源

**来源1：新信号维度（+3-5pp年化收益）**
当前5因子全是量价因子，IC时序高度同步。加入正交信号维度可以：
- 在量价因子失效的regime里提供额外alpha
- 降低整体组合的regime sensitivity

候选：行业动量、基本面重评、北向MODIFIER V2、PEAD盈利公告

**来源2：因子-模型联合优化（+3-8pp年化收益）**
RD-Agent(Q)证明联合优化比分开优化好2倍。当前系统的"先选因子再试模型"是次优的。

**来源3：Portfolio Optimization（+2-4pp年化收益）**
从等权Top-N升级到MV优化/风险预算，可以在相同信号下提取更多收益。

**来源4：E2E Portfolio Learning（+5-15pp年化收益）**
当前两阶段方法（predict excess return → rank → Top-N）有根本性缺陷：
- IC衡量全截面5000股排名相关性，Top-20只取前0.5%极端分位
- 训练目标(MSE on excess return)跟交易目标(portfolio Sharpe)不对齐
- LightGBM两次验证：G1 IC=0.082正 Sharpe=0.68<等权0.83；6-H IC=0.067正 Sharpe=0.09≈0

E2E方法：因子特征 → 神经网络 → portfolio权重 → loss = -Sharpe ratio
直接优化交易目标，跳过predict→rank→select中间步骤。
论文证据：Springer 2023 E2E Sharpe=1.16 vs 两阶段0.83；Attention E2E 2025 Sharpe=1.69 vs 等权0.54

### 3.3 波动率降低的可能来源

**来源1：Size-neutral已贡献（MDD从-56%到-39%）**
进一步降低SMB暴露的边际收益递减（b=0.75 OOS衰减39%）。

**来源2：多信号维度分散化**
不同维度的因子在不同regime有效→组合波动率自然下降。

**来源3：Portfolio优化约束**
行业集中度限制、相关性约束可以结构性降低组合波动率。

---

## 第四部分：升级路线（V4 — 路线C确认后）

### 阶段0：技术调研 ✅ 已完成 (2026-04-10)

**结论：路线C（混合）— 自建核心 + Alpha158因子借鉴 + riskfolio-lib**
- Qlib: ⚠️部分可用，Alpha158提取6个新因子类别(RSQR/RESI/IMAX/IMIN/QTLU/CORD)，数据层/回测不迁移
- RD-Agent: ❌不适用，Docker硬依赖+Windows bug+Claude不支持（三重阻断）
- riskfolio-lib 7.2.1 + vectorbt 0.28.5 已装入主.venv
- 详见 `docs/research-kb/findings/qlib-rdagent-research.md`

### Phase 1: 基础设施（解锁后续所有工作）

#### 1.1 回测Phase A优化 ✅ 已完成（2026-04-10）

- **结果：** 12yr回测 841s → 14.6s（57.6x加速）
- **实际瓶颈：** cProfile揭示91%时间在Phase A信号生成（OBJECT dtype O(N×M)全表扫描），非Phase B事件循环
- **修复：** `_build_factor_date_index()` groupby预索引 + `bisect_right` O(logN)查找，替代56.8M行×144调仓日=8.2B次Python比较
- **验证：** 5yr Sharpe=0.6100 vs baseline 0.6095（diff=0.0005 < 0.001 ✅）
- **归档：** VectorizedBacktester设计（Phase B仅占9%，无需重写）

#### 1.2 新信号维度实现（E2E输入特征扩充）

E2E网络需要足够多正交特征。当前17个PASS因子全是量价维度，IC时序高度同步——喂给神经网络也只能学到等权近似。

| 方向 | 数据状态 | 与量价正交性 | 工作量 |
|------|---------|------------|--------|
| 行业动量(SW1 20d/60d) | DB里有 | 高（行业维度） | 50行 |
| 北向MODIFIER V2八因子 | 3.88M行已入库，OOS通过 | 高（外资行为） | 中 |
| Alpha158六因子(RSQR/RESI/IMAX/IMIN/QTLU/CORD) | 公式已提取 | 中（新量价类别） | 50行 |
| 基本面(ROE/营收增速) | Tushare可拉 | 高（基本面） | 中 |
| PEAD盈利公告 | 207K行已入库，Q1数据4/20-4/25 | 极高（事件） | 中 |

每个方向：算因子→IC评估→跟CORE 5 IC时序相关性→作为E2E输入特征。
**依赖：** 无（但评估效率依赖1.1）

### Phase 2: 信号框架升级（核心——直接决定Sharpe）

#### 2.1 融合E2E Portfolio Network（主攻方向）

- **架构：** LightGBM预测层(已有) + Portfolio Network权重层(新增)
- **层1输入：** 30+因子特征（17 PASS + Phase 1.2新因子）
- **层2输入：** LightGBM得分 + 原始因子特征 + 可选股票间关系
- **输出：** N个stock权重（连续值，sum=1，long-only，max单股10%）
- **Loss：** -Sharpe ratio + 换手率惩罚 + L2正则
- **训练模式：** 模式1(冻结LightGBM训练层2) → 模式2(联合微调) → 模式3(LambdaRank增强)
- **Walk-Forward：** 复用ML_WALKFORWARD fold结构F1-F7
- **防过拟合：** Purge gap + Dropout + L2 + 早停 + 因子噪声增强
- **硬件：** RTX 5070 12GB, PyTorch cu128
- **依赖：** Phase 1.1（训练内循环需快速Sharpe评估）+ Phase 1.2（特征）
- **前置验证：** A.8完美预测上界实验（50行代码，1天，决定融合架构优先级）
- **设计文档：** ML_WALKFORWARD_DESIGN §12 + 本文档附录A

#### 2.2 IC加权 SignalComposer（baseline对比）

- DEV_BACKTEST_ENGINE §4.7已设计ic_weight方法
- rolling 12月IC_IR加权，50行代码
- **依赖：** 无

#### 2.3 riskfolio-lib Portfolio Optimization（baseline对比）

- MVO/Risk Parity/Black-Litterman
- riskfolio-lib 7.2.1已装好
- 接入PortfolioBuilder weight_method
- **依赖：** 无
- **已知风险：** 20只股票协方差矩阵估计不稳定，需shrinkage estimator

**对比验证矩阵：**

| # | 方法 | 预测层 | 组合构建 | 对比基准 |
|---|------|-------|---------|---------|
| 0 | 当前基线 | 5因子等权 | Top-20等权+SN | Sharpe=0.68 |
| 1 | IC加权 | 5因子IC_IR | Top-20等权+SN | vs #0 |
| 2 | MVO | 5因子等权 | riskfolio MVO | vs #0 |
| 3 | IC+MVO | 5因子IC_IR | riskfolio MVO | vs #0 |
| 4 | **融合MLP** | **LightGBM** | **PortfolioMLP** | **vs #0-3** |
| 5 | **融合Attention** | **LightGBM** | **PortfolioAttention** | **vs #4** |
| 6 | 纯E2E MLP | MLP直接 | 连续权重 | vs #4（验证LightGBM层是否必要） |

\#6的作用：验证LightGBM预测层是否真的比MLP直接学更好。如果#4>#6，证明融合有价值。

### Phase 3: 自动化

| 任务 | 内容 | 依赖 |
|------|------|------|
| 3.1 | 因子生命周期闭环(active→warning→retired) | Phase 2 |
| 3.2 | Rolling WF自动化(每月重训练) | Phase 2 |
| 3.3 | IC监控告警(factor_health_daily扩展) | Phase 1 |
| 3.4 | 简版AI闭环(DeepSeek假设→代码→IC评估→反馈，替代不可用的RD-Agent) | Phase 2 |

### Phase 4: PT重启

**前提：** Phase 1+2核心完成

**重启checklist：**
- [ ] P0 SN config验证(.env PT_SIZE_NEUTRAL_BETA=0.50)
- [ ] CeleryBeat运行 + PMS链路验证
- [ ] 冒烟测试8项PASS
- [ ] E2E或IC加权+MVO的OOS Sharpe > 当前基线(0.6521)
- [ ] 毕业窗口从重启日起算60交易日

---

## 第五部分：设计文档处置（路线C确认后）

### 5.1 保留并更新

| 文档 | 处置 | 理由 |
|------|------|------|
| CLAUDE.md | ✅ 持续更新 | 编码规范+铁律，实际在用 |
| SYSTEM_RUNBOOK.md | ✅ 需要对齐代码 | 操作手册，但准确度~70% |
| 本文档(V4) | ✅ V3→V4已完成 | 纳入路线C+E2E设计 |
| DEV_BACKTEST_ENGINE.md | ✅ 保留并更新 | Step 2向量化是Phase 1.1核心，§4.7扩展riskfolio-lib |
| ML_WALKFORWARD_DESIGN.md | ✅ 保留并大幅更新 | 新增E2E章节，WF fold结构(F1-F7)被E2E复用 |

### 5.2 标记为Archived（设计有价值但不再作为实现指南）

| 文档 | 原因 |
|------|------|
| DESIGN_V5.md | 理想架构与现实差距太大，路线C保持自建核心 |
| DEV_AI_EVOLUTION.md | RD-Agent不适用(Docker三重阻断)。简版AI闭环(Phase 3.4)替代 |
| DEV_FRONTEND_UI.md | 12页面设计，但后端优先级更高 |
| DEV_FOREX.md | Phase 2+，A股未成熟前不启动 |
| DEV_NOTIFICATIONS.md | 钉钉Webhook够用 |
| DEV_SCHEDULER.md | 大部分定时任务的功能不存在 |

### 5.3 保留但降低权重

| 文档 | 处置 |
|------|------|
| DEV_BACKEND.md | 17个Service设计中只实现了~5个。保留已实现部分的参考价值 |
| DEV_FACTOR_MINING.md | 因子评估部分有价值(Gate/Profiler)。GP挖掘部分降低优先级 |
| DEV_PARAM_CONFIG.md | 已实现的参数配置保留。未实现的参数删除 |

---

## 第六部分：成功指标

| 指标 | 当前值 | 短期(4月底) | 中期(5月底) | 长期(年底) |
|------|--------|------------|------------|-----------|
| 回测速度 | ~~841s~~ **14.6s** ✅ | ~~<60s~~ 已达成 | - | - |
| 新信号维度 | 0 | ≥2个IC完成 | ≥4个 | ≥5个 |
| OOS Sharpe | 0.6521 | - | ≥0.75(E2E原型) | ≥1.0 |
| MDD | -39.35% | - | ≤-30% | ≤-25% |
| Active因子数 | 5 | 8-12 | 15+ | 20+ |
| 信号框架 | 等权Top-N | - | E2E原型 | E2E生产 |

---

## 第七部分：关键教训汇总（Step 6系列 + 设计反思）

| # | 教训 | 来源 |
|---|------|------|
| 1 | 先诊断再治疗——FF3归因应该最先做 | Step 6-D顺序 |
| 2 | 线性方法失败要快速接受 | Step 6-E/G重复验证 |
| 3 | IC正≠能赚钱——全截面IC和Top-N收益是不同的事 | LightGBM G1/6-H |
| 4 | 训练目标跟交易目标不对齐是根本问题 | 两阶段方法缺陷 |
| 5 | 同维度因子替换/堆叠效果有限 | Step 6-F |
| 6 | 部分>完全——部分中性化+16% vs 完全中性化-11% | Step 6-F vs 6-G |
| 7 | 新信号维度比优化旧信号更有价值 | 全系列收束结论 |
| 8 | 设计500页文档不如跑2天实验 | 11份文档未实现 |
| 9 | 自建不如站在巨人肩膀上(Qlib/RD-Agent) | 架构调研 |
| 10 | 因子和模型必须联合优化而非串行 | RD-Agent(Q) NeurIPS 2025 |
| 11 | 回测引擎的O(n²)循环是架构问题不是调参问题 | 3次OOM |
| 12 | 32GB RAM对研究+生产并行严重不足 | 持续OOM |
| 13 | 不要在回测结果不一致时选"更可信的"继续 | 铁律13/14 |
| 14 | 文档跟代码脱节比没有文档更危险 | 0.6095错标为12年 |
| 15 | 每次CC结果必须完整通读不跳读 | CC审阅铁律 |
| 16 | predict-then-optimize两阶段方法有天花板——IC正不代表Top-N能赚钱 | LightGBM G1(Sharpe=0.68<等权0.83) + 6-H(IC=0.067 Sharpe=0.09) |
| 17 | 训练目标跟交易目标必须对齐——MSE训练出的模型不会优化Sharpe | E2E Portfolio Learning论证 |
| 18 | 设计文档不更新=没有设计——V3阶段排序过时导致执行反复 | 11份文档80%未实现的根因 |

---

## 附录B：V2方案任务最终完成状态

### 审计10个问题

| # | 问题 | 状态 |
|---|------|------|
| 1 | IC口径不统一 | ✅ ic_calculator.py + 铁律19 |
| 2 | 未做OOS | ✅ WF 5折 + 逐年度 |
| 3 | FF3不可追溯 | ✅ ff3_attribution.py |
| 4 | factor_evaluation=0行 | ✅ batch_gate_v2: 17 PASS |
| 5 | factor_health停了 | ✅ 恢复+Decimal bug修复 |
| 6 | Profiler缓存缺失 | ⚠️ 5.5yr(START_DATE=2014已改待重跑) |
| 7 | 3个漏网因子 | ✅ G2 FAIL+替换不显著 |
| 8 | 29因子只有5年 | ❌ 低优先级 |
| 9 | DSR三份实现 | ❌ 低优先级 |
| 10 | PBO死代码 | ❌ 低优先级 |

### Git里程碑

| Tag | 内容 |
|-----|------|
| pre-refactor-baseline | 重构前基线 |
| refactor-complete | Step 0-6C重构完成 |
| wf-oos-v1 | Step 6-D WF OOS + FF3归因 |
| (commit eed4182) | Step 6-E IC基础设施修复 |
| (commit cb89a2b) | Step 6-E Alpha衰减归因 |
| (commit f84eda7) | Step 6-F 因子替换/SN/噪声/画像 |
| (commit 715411a) | Step 6-G Modifier层+batch_gate_v2 |
| (commit 5953211) | Step 6-H Part 1 SN inner实现 |
| (commit f8d13fb) | Step 6-H Part 2+3 Regime+LightGBM |
| (commit c5b8181) | 阶段0调研完成 — 路线C(混合)决策 |

---

## 附录A：E2E Portfolio Network 详细设计

### A.1 可微分Sharpe Loss

```python
def sharpe_loss(weights_sequence, returns_matrix, cost_rate=0.003):
    """
    weights_sequence: List[(N,)] 每个调仓日的portfolio权重
    returns_matrix: (T, N) 每天每只股票的收益率
    cost_rate: 单边交易成本估算

    1. 根据weights和returns计算每日portfolio收益
    2. 扣除调仓日的换手成本
    3. 计算Sharpe ratio
    4. 返回-Sharpe作为loss
    """
    portfolio_returns = compute_portfolio_returns(
        weights_sequence, returns_matrix, cost_rate
    )
    sharpe = portfolio_returns.mean() / (portfolio_returns.std() + 1e-8)
    return -sharpe
```

**已知的坑：**
- `std()`在收益接近常数时梯度爆炸 → 加eps=1e-8
- 短窗口Sharpe不稳定 → 训练窗口至少6个月(~120交易日)
- 年化(`*sqrt(252)`)不影响梯度方向，可加可不加
- 替代loss候选：Sortino ratio（只惩罚下行波动）、Calmar ratio（考虑MDD）

### A.2 Portfolio约束层

```python
class PortfolioLayer(nn.Module):
    """将网络原始输出转为合法portfolio权重"""

    def __init__(self, max_weight=0.10):
        super().__init__()
        self.max_weight = max_weight

    def forward(self, raw_scores):
        # 1. Long-only: ReLU
        positive = F.relu(raw_scores)
        # 2. Sum=1: Softmax
        weights = F.softmax(positive, dim=-1)
        # 3. Max单股上限: clamp + 重归一化
        weights = torch.clamp(weights, max=self.max_weight)
        weights = weights / weights.sum()
        return weights
```

**设计选择：**
- softmax vs simplex projection：softmax更简单且可微，先用softmax
- max_weight=0.10（20只等权=0.05，留2倍空间）
- 行业约束：第一版不加（复杂度高），用换手率惩罚替代
- 持仓数量：不硬约束Top-N，让网络自己学稀疏性（L1正则可选）

### A.3 融合架构（LightGBM预测层 + Portfolio Network权重层）

**核心洞察**：LightGBM的IC=0.067是有价值的信号，问题不在预测层而在
"预测→排名→Top-N等权"这一步丢失alpha。融合架构保留LightGBM的预测能力，
用Portfolio Network学习如何把预测转化为赚钱的持仓。

融合比纯MLP更好的4个理由：
1. LightGBM处理tabular数据比MLP强（ML界共识）
2. IC正但Sharpe零 → 问题在portfolio构建层不在预测层，小网络专门解决更高效
3. Portfolio Network参数少，12年≈144个调仓点小样本上更不容易过拟合
4. LightGBM WF pipeline已跑通，复用不重写

**层1: LightGBM预测层（已有，复用ml_engine.py）**
- 输入：30+因子特征（17 PASS + Phase 1.2新因子）
- 输出：每只股票的预测得分 score_i
- 训练：MSE on excess return（现有pipeline，不改）
- 价值：处理tabular数据比MLP强，非线性特征交互

**层2: Portfolio Network权重层（新增）**
- 输入：LightGBM得分 + 原始因子特征 + 可选的股票间关系
- 输出：portfolio权重 w_i（连续值，sum=1，long-only）
- 训练：loss = -Sharpe + λ_turnover × turnover
- 参数量：远少于纯E2E（只学权重分配，不学预测）

**训练模式（三种，按顺序尝试）**

模式1: 两阶段训练（先做，更稳定）
  Step 1: 训练LightGBM（现有WF pipeline，MSE loss）
  Step 2: 冻结LightGBM，训练Portfolio Network（Sharpe loss）
  优势：各层目标明确，不互相干扰，小样本更稳定

模式2: 联合微调（模式1有效后尝试）
  在模式1基础上，解冻LightGBM最后几层，用Sharpe loss联合微调
  优势：让预测层也学习"什么预测对portfolio有用"
  风险：过拟合风险更高，需要更强正则化

模式3: LambdaRank预训练（可选，模式1/2的增强）
  用LambdaRank替代MSE训练LightGBM层1，优化排序而非预测精度。
  LightGBM原生支持LambdaRank（objective='lambdarank'）。
  优势：让预测层也对齐"排序正确"目标，与portfolio构建更协调
  与模式1/2的关系：可组合——LambdaRank训练层1 + 冻结 + Sharpe训练层2
  待验证：LambdaRank的IC vs MSE的IC，哪个对Top-20更有用

**方案A: Portfolio MLP（先做）**

```python
class PortfolioMLP(nn.Module):
    """层2：将LightGBM得分转化为portfolio权重"""
    def __init__(self, n_features, hidden=64):
        super().__init__()
        # 输入 = LightGBM得分(1) + 原始因子特征(F)
        self.net = nn.Sequential(
            nn.Linear(n_features + 1, hidden),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )
        self.portfolio_layer = PortfolioLayer()

    def forward(self, lgbm_scores, factor_features):
        # lgbm_scores: (N,) LightGBM预测得分
        # factor_features: (N, F) 原始因子特征
        x = torch.cat([lgbm_scores.unsqueeze(-1), factor_features], dim=-1)
        raw_scores = self.net(x).squeeze(-1)  # (N,)
        weights = self.portfolio_layer(raw_scores)  # (N,)
        return weights
```

**方案B: Portfolio Attention（方案A有效后升级）**

```python
class PortfolioAttention(nn.Module):
    """层2 + 股票间attention：隐式学习分散化"""
    def __init__(self, n_features, n_heads=4):
        super().__init__()
        self.embed = nn.Linear(n_features + 1, 64)
        self.attention = nn.MultiheadAttention(64, n_heads, dropout=0.1)
        self.score_head = nn.Linear(64, 1)
        self.portfolio_layer = PortfolioLayer()

    def forward(self, lgbm_scores, factor_features):
        x = torch.cat([lgbm_scores.unsqueeze(-1), factor_features], dim=-1)
        embeddings = self.embed(x)  # (N, 64)
        attended, _ = self.attention(
            embeddings.unsqueeze(0), embeddings.unsqueeze(0), embeddings.unsqueeze(0)
        )
        raw_scores = self.score_head(attended.squeeze(0)).squeeze(-1)
        weights = self.portfolio_layer(raw_scores)
        return weights
```

Attention的额外价值：如果两只股票LightGBM得分都高但因子特征相似，
attention会降低其中一只权重——隐式做分散化和去相关。

**决策：先方案A(PortfolioMLP)验证融合架构可行性，有效后升级方案B(PortfolioAttention)。**

### A.4 训练Pipeline（融合架构版本）

```python
def train_fusion(lgbm_model, portfolio_net, train_data, valid_data, config):
    """
    融合训练模式1：冻结LightGBM，只训练Portfolio Network
    
    lgbm_model: 已训练的LightGBM模型（来自ml_engine.py WF pipeline）
    portfolio_net: PortfolioMLP或PortfolioAttention
    """
    # Step 1: LightGBM推理（不训练，冻结）
    with torch.no_grad():
        lgbm_scores = {}
        for t in train_data['rebalance_indices']:
            features_t = train_data['factor_features'][t]  # (N, F)
            lgbm_scores[t] = lgbm_model.predict(features_t)  # (N,)
    
    # Step 2: 训练Portfolio Network
    optimizer = torch.optim.Adam(portfolio_net.parameters(), lr=1e-3, weight_decay=0.01)
    best_val_sharpe = -float('inf')
    patience_counter = 0

    for epoch in range(500):
        portfolio_net.train()
        all_weights = []

        for t in train_data['rebalance_indices']:
            scores_t = torch.tensor(lgbm_scores[t])
            features_t = train_data['factor_features'][t]
            weights_t = portfolio_net(scores_t, features_t)
            all_weights.append(weights_t)

        portfolio_returns = compute_portfolio_returns(
            all_weights, train_data['returns'],
            train_data['rebalance_indices'], cost_rate=0.003
        )

        sharpe = portfolio_returns.mean() / (portfolio_returns.std() + 1e-8)
        turnover = compute_turnover(all_weights)
        loss = -sharpe + config.lambda_turnover * turnover

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(portfolio_net.parameters(), max_norm=1.0)
        optimizer.step()

        if epoch % 10 == 0:
            val_sharpe = evaluate_fusion(lgbm_model, portfolio_net, valid_data)
            if val_sharpe > best_val_sharpe:
                best_val_sharpe = val_sharpe
                patience_counter = 0
                torch.save(portfolio_net.state_dict(), 'best_portfolio_net.pt')
            else:
                patience_counter += 1
                if patience_counter >= 20:
                    break

    portfolio_net.load_state_dict(torch.load('best_portfolio_net.pt'))
    return portfolio_net
```

**关键设计决策：**
- LightGBM层冻结，只训练Portfolio Network → 参数少，小样本更稳定
- 月度调仓：跟当前策略一致
- 交易成本在训练中：cost_rate=0.003纳入portfolio return，模型自动学低换手
- `compute_portfolio_returns`必须纯PyTorch tensor操作（可微分）
- 梯度裁剪(max_norm=1.0)防爆炸
- 早停patience=20 epochs，监控validation Sharpe
- LightGBM推理只需做一次（冻结），不参与反向传播

### A.5 Walk-Forward集成

复用ML_WALKFORWARD_DESIGN §1.3的7个fold：

```
F1-F7, 每个fold:
  train(24月) → purge(5日) → valid(6月) → test(6月)
```

每个fold独立训练一个模型，test集预测拼接成连续OOS序列，计算chain-link OOS Sharpe。

与LightGBM WF的区别：每个fold内部先训练LightGBM(MSE loss)，再冻结LightGBM训练Portfolio Network(Sharpe loss)。fold结构、数据切分、Purge gap完全复用。LightGBM WF pipeline（ML_WALKFORWARD_DESIGN §1-§8）继续作为层1训练框架使用。

**预估训练时间：**
- 向量化回测<60s/评估 x ~50次评估(500 epoch/10) = ~50min/fold
- 7个fold = ~6小时（可在不同GPU stream上并行）

### A.6 与现有系统的接口

**E2E模型产出:** `Dict[str, float]` = `{stock_code: weight}`

**接入BacktestEngine:**
- 当前executor接受 `Dict[str, float]`（权重=1/N均匀）
- E2E输出同类型 `Dict[str, float]`（权重=模型输出，非均匀）
- 接口不变，权重分布从均匀→非均匀

**接入PT(Phase 4):**
- `signal_service.py`新增E2E信号路径，与现有等权路径并行
- config选择: `pt_live.yaml signal_method: 'e2e' | 'equal_weight'`

### A.7 风险和已知问题

| 风险 | 严重性 | 缓解措施 |
|------|--------|---------|
| Sharpe loss梯度不稳定 | 高 | eps=1e-8 + 梯度裁剪 + 考虑Sortino替代 |
| 股票universe变化 | 中 | 固定输出维度覆盖全A股，不可交易的mask为0后重归一化 |
| 过拟合（12年仅~144个月度决策点） | 高 | 强正则+简单MLP+WF验证+因子噪声增强(复用铁律20) |
| 训练数据量小（每fold 24月=~24个调仓点） | 高 | 数据增强(因子加噪声+随机dropout特征+滑窗子序列) |
| 简化回测vs精确回测diff | 中 | E2E训练用纯tensor，最终评估用SimpleBacktester。diff>5% Sharpe需调整 |
| max_weight约束不可微 | 低 | clamp梯度为0。替代：soft clamp(sigmoid缩放)或barrier方法 |

### A.8 前置验证：完美预测上界

在实现融合架构之前，先回答一个根本问题：
**如果预测完美（用未来真实收益做输入），portfolio优化能达到多少Sharpe？**

实验：用T+20真实超额收益替代LightGBM预测得分，
跑riskfolio-lib MVO和简单Top-20等权，对比Sharpe。

- 如果完美预测+MVO Sharpe > 1.5 → portfolio优化有巨大空间，融合架构值得做
- 如果完美预测+MVO Sharpe < 1.0 → 瓶颈不在portfolio构建，需要更好的预测
- 如果完美预测+等权Top-20 Sharpe > 1.5 → 问题纯粹在预测层，融合架构不解决根因

这个实验只需要50行代码+一次回测，应在Phase 2.1开始前完成。
结果决定融合架构的优先级和预期。

### A.9 Regime感知机制

12年数据包含3-4个独立regime（2014-15牛市、2018熊市、2021小盘牛、2022-23失效）。
144个月度调仓点在每个regime内只有~36个样本。
模型可能学到"历史平均最优"而非"regime适配最优"。

三个缓解方案（按实现难度排序）：

1. **近期数据加权**（最简单）
   loss中对近期数据upweight：weight_t = decay^(T-t)，让模型偏向当前regime

2. **Regime indicator作为额外输入**（中等）
   加入市场宽度(涨跌比)、波动率(CSI300 20日std)、动量(CSI300 60日return)
   作为Portfolio Network的额外输入特征，让模型学到"牛市选什么、熊市选什么"

3. **Regime条件训练**（最复杂）
   按regime分组训练多个Portfolio Network，推理时根据当前regime选择对应模型
   类似Mixture of Experts

决策：Phase 2.1先用方案1+2，方案3留到Phase 3评估。
