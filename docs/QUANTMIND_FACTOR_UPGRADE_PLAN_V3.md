# QuantMind V2 因子体系升级方案 V3

**基于Step 6系列实验结论 + Qlib/RD-Agent研究 + 设计-实现差距反思**
**日期**: 2026-04-10 | **版本**: v3.0

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

### 1.3 V3方案的原则

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
  SimpleBacktester (事件驱动, 12yr 841s)
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

### 3.3 波动率降低的可能来源

**来源1：Size-neutral已贡献（MDD从-56%到-39%）**
进一步降低SMB暴露的边际收益递减（b=0.75 OOS衰减39%）。

**来源2：多信号维度分散化**
不同维度的因子在不同regime有效→组合波动率自然下降。

**来源3：Portfolio优化约束**
行业集中度限制、相关性约束可以结构性降低组合波动率。

---

## 第四部分：升级路线

### 阶段0：技术调研（2天）

**目标：评估Qlib + RD-Agent是否适合QuantMind**

| 任务 | 内容 | 时间 |
|------|------|------|
| 0.1 | 安装Qlib，跑A股Alpha158+LightGBM demo | 半天 |
| 0.2 | 评估Qlib数据格式与现有PG/Parquet的兼容性 | 半天 |
| 0.3 | 安装RD-Agent，跑一次自动因子挖掘demo | 半天 |
| 0.4 | 评估RD-Agent与现有factor_engine的集成可行性 | 半天 |

**决策点：**
- 如果Qlib A股demo可用且Sharpe>现有→走路线A（Qlib集成）
- 如果Qlib不适用（数据不兼容/Windows问题）→走路线B（自建升级）
- RD-Agent评估独立于Qlib决策

### 阶段1：收尾 + 新信号维度（1-2周）

无论走哪条路线，这些都要先做：

**1.1 Step 6-H成果落地**
- git push两个commit
- CLAUDE.md更新（失败方向+下一步+基线数字）
- PT激活SN b=0.50（取消注释pt_live.yaml）
- PT冒烟测试

**1.2 新信号维度探索（4个方向并行）**

| 方向 | 数据状态 | 工作量 | 预期IC |
|------|---------|--------|--------|
| 行业动量(SW1 20d/60d) | DB里有 | 50行代码 | 待测 |
| 基本面12yr重评(ROE/营收增速) | Tushare可拉 | 中等 | 待测 |
| 北向MODIFIER V2八因子 | 3.88M行已入库 | 中等 | OOS已通过 |
| PEAD盈利公告 | 207K行已入库 | 中等 | Q1 4/20-4/25 |

每个方向：算因子→IC评估→跟CORE 5的IC时序相关性→如果负相关就有regime分散价值

**1.3 清理遗留**
- 根目录临时文件清理
- DSR三份实现统一
- PBO首次运行
- precompute_cache 2014重跑

### 阶段2：框架升级（取决于阶段0调研结果）

**路线A：Qlib集成（如果调研可行）**

| 任务 | 内容 | 依赖 |
|------|------|------|
| 2A.1 | 数据迁移：PG→Qlib二进制格式 | 阶段0.2确认可行 |
| 2A.2 | 回测迁移：SimpleBacktester→Qlib BacktestEngine | 2A.1 |
| 2A.3 | ML迁移：ml_engine.py→Qlib Model Zoo | 2A.1 |
| 2A.4 | Portfolio升级：等权Top-N→Qlib TopkDropout+MV | 2A.2 |
| 2A.5 | RD-Agent集成：自动因子-模型联合优化 | 2A.1+2A.3 |

**路线B：自建升级（如果Qlib不适用）**

| 任务 | 内容 | 依赖 |
|------|------|------|
| 2B.1 | 向量化回测：用numpy重写SimpleBacktester核心循环 | 无 |
| 2B.2 | Portfolio Optimization：引入riskfolio-lib做MV优化 | 无 |
| 2B.3 | 因子-模型联合评估：每加一个因子重跑全模型 | 2B.1 |
| 2B.4 | End-to-end实验：直接用Sharpe作loss训练 | 2B.1 |
| 2B.5 | 简版AI闭环：DeepSeek生成假设→代码→IC评估→反馈 | 无 |

### 阶段3：自动化与持续进化

| 任务 | 内容 | 依赖 |
|------|------|------|
| 3.1 | 因子生命周期闭环(active→warning→retired) | 阶段2 |
| 3.2 | Rolling WF自动化(每月自动重训练+评估) | 阶段2 |
| 3.3 | 因子IC监控告警(factor_health_daily扩展) | 阶段1 |
| 3.4 | 实盘vs回测对比自动化 | 阶段1 |

---

## 第五部分：设计文档处置

### 5.1 保留并更新

| 文档 | 处置 | 理由 |
|------|------|------|
| CLAUDE.md | ✅ 持续更新 | 编码规范+铁律，实际在用 |
| SYSTEM_RUNBOOK.md | ✅ 需要对齐代码 | 操作手册，但准确度~70% |
| Roadmap V3 | ✅ 更新为V4 | 纳入Step 6系列成果 |

### 5.2 标记为Archived（设计有价值但不再作为实现指南）

| 文档 | 原因 |
|------|------|
| DESIGN_V5.md | 理想架构与现实差距太大。如果走Qlib路线则大部分设计被替代 |
| DEV_BACKEND.md | 17个Service设计中只实现了~5个。如果走Qlib路线则数据/回测Service被替代 |
| DEV_BACKTEST_ENGINE.md | Step 2/3未实现。如果用Qlib/VectorBT则整个文档被替代 |
| DEV_AI_EVOLUTION.md | 0行代码。如果用RD-Agent则整个设计被替代 |
| DEV_FRONTEND_UI.md | 12页面设计，但后端优先级更高 |
| DEV_FOREX.md | Phase 2+，A股未成熟前不启动 |
| DEV_NOTIFICATIONS.md | 钉钉Webhook够用 |
| DEV_SCHEDULER.md | 大部分定时任务的功能不存在 |

### 5.3 保留但降低权重

| 文档 | 处置 |
|------|------|
| DEV_FACTOR_MINING.md | 因子评估部分有价值(Gate/Profiler)。因子挖掘部分如果用RD-Agent则被替代 |
| DEV_PARAM_CONFIG.md | 已实现的参数配置保留。未实现的参数删除 |
| ML_WALKFORWARD_DESIGN.md | WF部分已实现。ML模型部分如果用Qlib Model Zoo则被替代 |

---

## 第六部分：成功指标

### 短期（4月底）

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| PT SN b=0.50激活 | 未激活 | 已激活+冒烟通过 |
| Qlib/RD-Agent调研 | 未开始 | 调研完成+路线决策 |
| 新信号维度IC评估 | 0个 | ≥2个完成(行业动量+北向) |
| 遗留cleanup | 未做 | git push+CLAUDE.md+临时文件 |

### 中期（5月底）

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 12yr OOS Sharpe | 0.6521 | ≥0.75(新信号维度+PO升级) |
| MDD | -39.35% | ≤-30%(Portfolio Optimization) |
| Active因子数 | 5 | 8-12(含非量价维度) |
| 回测速度 | 841s | <60s(向量化或Qlib) |
| 因子-模型联合评估 | 串行手动 | 至少半自动化 |

### 长期（年底）

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| Sharpe(OOS) | 0.6521 | ≥1.0 |
| MDD | -39.35% | ≤-25% |
| 失效年份 | 2/12(SN后) | ≤1/12 |
| 自动化因子挖掘 | 手动 | RD-Agent式自动(每周一轮) |
| 信号维度 | 1(量价) | ≥3(量价+基本面+事件) |

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

---

## 附录：V2方案任务最终完成状态

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
