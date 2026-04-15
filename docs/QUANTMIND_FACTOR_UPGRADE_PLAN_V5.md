# QuantMind V2 因子体系升级方案 V5

**基于Phase 2全系列实验结论 + 因子扩展研究 + 新范式探索**
**日期**: 2026-04-12 | **版本**: v5.0 | **前版**: v4.0 (2026-04-10)

---

## 第一部分：V4方案执行总结

### 1.1 V2→V4 完整验证链回顾

| 轮次 | 假设 | 结果 |
|------|------|------|
| 6-D | 策略可能过拟合 | 有真alpha(t=2.90)但regime不稳定(std=1.52) |
| 6-E | 因子IC在衰减 | IC没衰减(retention 0.84-1.04)，问题在持仓层 |
| 6-F | 因子层优化可行 | 替换不显著(p=0.92)，完全SN损11% |
| 6-G | Modifier层干预 | Partial SN(b=0.50)唯一有效，Vol/DD/组合全失败 |
| 6-H | 实盘化+ML验证 | SN inner OK，LightGBM 17因子Sharpe≈0 |

### 1.2 Phase 2 全系列实验结论（V4→V5新增）

| Phase | 内容 | 结果 |
|-------|------|------|
| 2.1 E2E融合 | A.8完美预测+LightGBM WF+PN v1 | A.8 Sharpe=3.02(巨大空间)；LightGBM CORE5 IC=0.0912；PN v1 FAIL(tensor=1.81 实盘=-0.99, sim-to-real gap) |
| 2.2 Gate验证 | 6种portfolio方法 | 全败：LambdaRank=0.56, LightGBM=0.44, IC加权=0.27, MVO=0.26, IC+MVO=0.21 |
| 2.3 市值诊断 | 策略真实画像 | 无SN=91.5%微盘；SN=barbell(58%大盘+42%微盘+0%中盘)；因子跨市值有效但IC衰减58-79%；amihud中盘IC≈0 |
| 2.4 探索实验 | 36个实验+9Q审计 | dv_ttm关键增量(+30%)；季度调仓(+25%)；Top-25+(+29%)；RSQR修复后有害；Alpha 100%微盘 |
| P0修复 | 数据完整性 | 7因子NaN修复(68.8M行)；DB/Parquet统一；因子入库体系(铁律29-30)；磁盘66→28GB |
| WF验证 | CORE3+dv_ttm | **PASS: OOS Sharpe=0.8659(+33%) MDD=-13.91%(改善54%) Overfit=0.84 5fold全正STABLE** |

### 1.3 V4方案的原则（继续沿用）

1. **目标驱动而非功能驱动** — 不问"系统应该有什么"，问"要让Sharpe从0.87到1.5需要什么"
2. **每个任务独立可执行** — 不依赖其他未实现模块
3. **先实验后设计** — 每个方向先做2天实验验证可行，再写实现计划
4. **站在巨人肩膀上** — 能用开源的就不自己写(Alpha158/Kronos/DSL/KunQuant)
5. **文档跟随代码** — 只维护"当前系统实际状态"和"下一步计划"

### 1.4 Phase 2 根本性发现（指导Phase 3方向）

1. **因子池太窄是根本问题**：63个因子里~50个是量价同质因子。dv_ttm(股息率)加入带来+33% Sharpe——证明新维度因子有巨大增量空间。基本面/资金流/事件维度几乎空白
2. **等权5因子是局部最优**：因子太少→ML学不到交互→等权最优。这不是"等权比ML好"，是"因子太少ML没法发挥"。100+因子时ML可能有优势
3. **Alpha 100%来自微盘**：收窄universe到任何非微盘区间→Sharpe≈0。SN barbell是当前最优结构
4. **Portfolio构建层是瓶颈**：6种方法全败，等权不可超越。但DSL(ACM 2025)可能解决sim-to-real gap
5. **交易成本吞噬大量alpha**：月度成本损耗0.34 Sharpe(1/3的零成本alpha)。季度调仓信号几乎不衰减(IC retention 0.84-1.04)
6. **IC正≠能赚钱的问题仍存在**：中盘IC=0.095(t=6.61高度显著)但Sharpe=0.07——因子在非微盘区间统计显著但经济不显著

---

## 第二部分：当前系统真实状态（4/12更新）

### 2.1 实际在运行的东西

```
数据层：
  PostgreSQL 16.8 + TimescaleDB 2.26.0
  - factor_values ~590M行 hypertable (~119GB)
  - klines_daily 11.7M行 (1.98GB)
  - stock_status_daily 12M行
  - minute_bars 139M行 (25GB, 覆盖率46%)
  - earnings_announcements 207K行
  Parquet缓存 cache/backtest/ (已重建，含CORE3+dv_ttm)
  Redis 5.0.14.1 + StreamBus
  DB总大小 ~159GB (factor_values 119GB)

信号层：
  4因子等权: turnover_mean_20(-1), volatility_20(-1), bp_ratio(+1), dv_ttm(+1)
  SignalComposer → PortfolioBuilder → Top-20
  Size-neutral beta=0.50 (已激活, .env已配置)
  月度调仓
  因子入库体系: 铁律29(禁NaN) + 铁律30(中性化后重建Parquet)
  factor_health_check.py: 7项自动验证

回测层：
  SimpleBacktester (事件驱动, 12yr 12.6s)
  Walk-Forward 5-fold (已验证CORE3+dv PASS)
  ic_calculator.py (铁律19标准)
  generate_report 2.4s

执行层：
  QMT Paper Trading (Servy管理4服务, 已重启4/12)
  Task Scheduler: DailySignal(16:30) + DailyExecute(09:31) + 4个辅助任务
  PMS v1.0

ML层：
  ml_engine.py (LightGBM, GPU RTX 5070, 60月WF pipeline)
  结论: 5因子ML不如等权; 100+因子待验证

硬件：
  GPU PyTorch cu128 RTX 5070 12GB
  RAM 32GB (串行执行铁律, OOM教训)
  磁盘 ~28GB项目 + 159GB DB
```

### 2.2 已验证的关键数字

| 指标 | V4值 | V5值(4/12) | 变化 |
|------|------|-----------|------|
| 信号层因子 | 5因子CORE5 | **4因子CORE3+dv_ttm** | 去amihud/reversal,加dv_ttm |
| Full-sample Sharpe | 0.68 | **1.03** | +51% |
| WF OOS Sharpe | 0.6521 | **0.8659** | +33% |
| OOS MDD | -39.35% | **-13.91%** | 改善54% |
| WF Overfit Ratio | — | **0.84** | 低过拟合风险 |
| WF Stability | — | **STABLE (5fold全正)** | — |
| Composite IC | — | **0.113 (IR=1.15)** | — |
| FF3 Alpha t-stat | 2.90 | 2.90 | 未变 |
| SMB beta | ~1.09 | ~1.09 | 未变 |
| IC retention | 0.84-1.04 | 0.84-1.04 | 未变 |
| PASS因子数 | 17/53 | 17/53 (+dv_ttm可用) | — |
| factor_values行数 | 501M | **~590M** | +89M |
| 回测速度 | 14.6s | **12.6s** | — |

### 2.3 已关闭的路径（不再重试）

**Phase 1-2（V4已列）：**
- 因子替换(p=0.92) / 完全Size-neutral(损11%) / Vol-Targeting(3方案全败)
- Drawdown-Aware(MDD更差) / Regime线性检测(5指标全p>0.05)
- Regime动态beta / LightGBM 5因子 / LightGBM 17因子(Sharpe≈0)
- PMS v2.0(p=0.655) / 风险平价G2 / 动态仓位G2.5 / 双周调仓
- mf_divergence(IC=-2.27%) / LLM自由生成因子 / 同因子换ML模型

**Phase 2新增关闭：**
- Universe filter替代SN — Alpha 100%微盘，收窄到任何非微盘区间Sharpe≈0
- LambdaRank作为等权合成因子 — 信号冲突，Sharpe从0.67降到0.48
- RSQR_20在CORE3+dv组合中 — 修复NaN后验证有害(Sharpe -0.089)
- IC加权合成(全A截面) — Sharpe=0.27，大幅失败
- MVO/Risk Parity — Sharpe=0.26，协方差不稳定
- PortfolioNetwork v1(可微Sharpe) — sim-to-real gap，softmax分散到5000只→佣金地板吃掉
- 风格分散混合(alpha+defensive blend) — Sharpe=0.06-0.16，防御组稀释alpha
- RSQR_20/QTLU_20单独加入CORE5 — 零增量(中性化后信息被消除)

---

## 第三部分：从0.87到1.5+的差距分析

### 3.1 当前位置

WF OOS Sharpe=0.8659。全样本Sharpe=1.03。
目标：OOS Sharpe ≥ 1.0，全样本 ≥ 1.5。

### 3.2 收益增量的可能来源（V5修订）

**来源1：因子维度扩展（最确定，预期+20-50%）**
dv_ttm加入带来+33%——只加了1个新维度因子就有这么大增量。
当前63个因子里~50个量价同质，基本面/资金流/事件维度几乎空白。
扩展到300+多维度因子后，等权组合和ML合成都有巨大提升空间。
- 基本面：ROE/ROA/毛利率/资产负债率（Tushare fina_indicator）
- 资金流：主力净流入/融资融券/股东户数变化（Tushare/AKShare）
- 事件：盈利惊喜/解禁/回购/龙虎榜（已有+待拉取）
- 技术：MACD/KDJ/RSI/BOLL（Tushare stk_factor，已算好）
- 量价扩展：Alpha158剩余130+因子（Qlib开源代码可算）

**来源2：ML合成（因子够多时有优势，预期+10-30%）**
Phase 2证明5因子ML不如等权。但100+因子时ML可以捕捉跨维度交互效应。
论文证据：A股500-1000因子+ML框架，OOS Sharpe>2.0。

**来源3：时序信号维度（正交信号，预期+10-20%）**
Kronos（AAAI 2026）：K线时序pattern → 预测收益。
与CORE截面因子信息维度正交。零样本验证后可作为新因子加入。

**来源4：Portfolio构建升级（解决6方法全败，预期+10-30%）**
DSL（ACM 2025）：cross-entropy学习离线最优权重，Deep Ensemble降方差。
完美解决PN v1的sim-to-real gap——离线优化器用精确成本模型(含¥5佣金地板)。

**来源5：股票间关联（全新信息维度，预期+5-15%）**
GNN捕捉板块联动/行业关系——CORE完全不考虑股票间关系。

### 3.3 波动率降低的可能来源

1. **多维度因子分散化** — 不同维度因子在不同regime有效→组合波动率自然下降
2. **dv_ttm防御效应已验证** — MDD从-30%降到-14%，在2022-2023弱市大幅改善
3. **Top-N增加** — Top-25~40分散化降低单股风险(Sharpe+29-38%)
4. **交易成本优化** — 季度调仓成本损耗仅0.16 vs 月度0.34

---

## 第四部分：升级路线

### Phase 0: 技术调研 ✅ 已完成
路线C（混合）：自建核心 + Alpha158因子借鉴 + riskfolio-lib

### Phase 1: 基础设施 ✅ 已完成
- 1.1 回测优化：841s → 12.6s ✅
- 1.2 新信号维度：SW1迁移+Alpha158六因子+PEAD+北向+高低位放量 ✅

### Phase 2: 信号框架升级 ✅ 已完成
- 2.1 E2E融合：A.8完美预测PASS + LightGBM WF + PN v1 FAIL ✅
- 2.2 Gate验证：6方法全败 ✅
- 2.3 市值诊断：barbell结构确认 ✅
- 2.4 探索实验：dv_ttm关键增量 + 9Q审计 ✅
- P0修复：NaN/Parquet/入库体系 ✅
- WF验证：CORE3+dv_ttm PASS (OOS Sharpe=0.8659) ✅
- PT重启：CORE3+dv_ttm配置，4/12重启 ✅

### Phase 3: 因子扩展 + ML合成 + 新范式（当前阶段）

详见附录C完整Phase 3 Roadmap。核心结构：

| 子阶段 | 内容 | 预计耗时 | 依赖 |
|--------|------|---------|------|
| 3.0 | PT监控+稳定性确认 | 1周(被动) | PT已重启 |
| 3A | 零成本因子扩展(Alpha158+daily_basic+stk_factor+earnings) | 1-2天 | 无 |
| 3B | 新数据入库(Tushare+AKShare+BaoStock, 后台并行) | 2-3天 | 与3A并行 |
| 3C | 因子分类+组间正交组合 | 1-2天 | 3A+3B |
| 3D | ML合成(100+因子→LightGBM/XGBoost WF) | 2-3天 | 3C |
| 3E | 新范式(Kronos/DSL/GNN/FactorVAE) | 1-2周 | 3D或并行 |
| 3F | PEAD Q1 2026数据(4/20-4/25可用) | 1天 | 数据可用 |
| 3G | 自动化(Rolling WF/IC监控/因子生命周期) | 1周 | 3D |

### Phase 4: PT持续优化

PT已于4/12重启(CORE3+dv_ttm配置)。Phase 4不再是"重启"而是"持续优化"：
- Phase 3发现更优配置 → 更新PT
- 毕业窗口：从重启日起算60交易日
- 监控：日志/PnL/持仓分布/因子数据完整性

---

## 第五部分：设计文档处置（V5更新）

### 5.1 核心文档（持续更新）

| 文档 | 状态 | 说明 |
|------|------|------|
| CLAUDE.md | ✅ 活跃 | 铁律1-30 + 编码规范 |
| SYSTEM_STATUS.md | ✅ 活跃 | PT状态+配置 |
| 本文档(V5) | ✅ 活跃 | 升级方案+Phase 3路线 |
| Phase 3 Roadmap | ✅ 新建 | 详细执行计划 |
| FACTOR_ONBOARDING_SYSTEM.md | ✅ 新建(4/12) | 因子入库体系(310行) |
| DEV_BACKTEST_ENGINE.md | ✅ 对齐V5 | 回测引擎文档 |
| ML_WALKFORWARD_DESIGN.md | ✅ 对齐V5 | WF设计+E2E章节 |

### 5.2 Archived（设计有参考价值但不再作为实现指南）

| 文档 | 原因 |
|------|------|
| DESIGN_V5.md | 理想架构与现实差距太大 |
| DEV_AI_EVOLUTION.md | RD-Agent不适用；Phase 3E的Kronos/FactorVAE替代 |
| DEV_FRONTEND_UI.md | 后端优先 |
| DEV_FOREX.md | A股未成熟前不启动 |
| DEV_NOTIFICATIONS.md | 钉钉Webhook够用 |
| DEV_SCHEDULER.md | 大部分定时任务的功能不存在 |

---

## 第六部分：成功指标（V5更新）

| 指标 | V4值 | V5当前值(4/12) | 短期(4月底) | 中期(5月底) | 长期(年底) |
|------|------|---------------|------------|------------|-----------|
| 回测速度 | 14.6s | **12.6s** ✅ | — | — | — |
| OOS Sharpe | 0.6521 | **0.8659** ✅ | ≥0.90(因子扩展) | ≥1.0(ML合成) | ≥1.2 |
| OOS MDD | -39.35% | **-13.91%** ✅ | ≤-15% | ≤-15% | ≤-12% |
| Active因子数 | 5 | **4** | 10-15(跨组) | 50+(ML输入) | 100+ |
| 因子池总数 | 63 | 63(+7修复) | **200+**(3A) | **300+**(3B) | 500+ |
| 因子维度覆盖 | 1(量价) | **2(量价+价值)** | **5+** | **6+** | 8+ |
| 信号框架 | 等权CORE5 | **等权CORE3+dv** | 跨组等权 | ML合成 | ML+DSL |
| PT状态 | 暂停 | **运行中** ✅ | 运行中 | 运行中 | 运行中 |
| 数据源 | Tushare | Tushare | +AKShare+BaoStock | +minute_bars 100% | 全覆盖 |

---

## 第七部分：关键教训汇总（V5扩展）

### V4教训（1-18，保留）

| # | 教训 | 来源 |
|---|------|------|
| 1 | 先诊断再治疗——FF3归因应该最先做 | Step 6-D |
| 2 | 线性方法失败要快速接受 | Step 6-E/G |
| 3 | IC正≠能赚钱——全截面IC和Top-N收益是不同的事 | LightGBM G1/6-H |
| 4 | 训练目标跟交易目标不对齐是根本问题 | 两阶段方法 |
| 5 | 同维度因子替换/堆叠效果有限 | Step 6-F |
| 6 | 部分>完全——部分中性化+16% vs 完全中性化-11% | Step 6-F/G |
| 7 | 新信号维度比优化旧信号更有价值 | 全系列收束 |
| 8 | 设计500页文档不如跑2天实验 | 11份文档未实现 |
| 9 | 自建不如站在巨人肩膀上 | 架构调研 |
| 10 | 因子和模型必须联合优化而非串行 | RD-Agent(Q) |
| 11-18 | (保持V4原文) | — |

### V5新增教训（19-30）

| # | 教训 | 来源 |
|---|------|------|
| 19 | **因子池宽度比深度更重要**——50个同质量价因子不如6个跨维度因子 | dv_ttm加入+33% |
| 20 | **5因子ML不如等权不代表ML无用**——因子太少ML学不到交互，100+因子时才有发挥空间 | Phase 2.1 LightGBM IC=0.09 < 等权0.113 |
| 21 | **SN barbell是特征不是bug**——58%大盘+42%微盘的结构在WF验证中稳定有效 | Phase 2.3诊断 |
| 22 | **交易成本是隐形杀手**——月度成本损耗0.34 Sharpe，吃掉1/3零成本alpha | Phase 2.4 Q6 |
| 23 | **IC统计显著≠经济显著**——中盘IC=0.095(t=6.61)但Sharpe=0.07 | Phase 2.4 Q4 |
| 24 | **float NaN vs SQL NULL必须体系层面解决**——RSQR_20 NaN导致整个因子替换方向无效 | Phase 2.4审计Q8 |
| 25 | **Parquet缓存不自动重建=定时炸弹**——中性化迁移后2天未重建→40%NAV偏差 | P0-2诊断 |
| 26 | **数据完整性检查必须嵌入pipeline**——factor_health_check.py+铁律29-30 | P0-4 |
| 27 | **Top-N越大Sharpe越高不是分散效应，是更多微盘暴露**——Top-40微盘占比59% vs Top-10的35% | Phase 2.4 Q5 |
| 28 | **审计追问比直接执行更有价值**——9Q审计发现RSQR NaN+基线偏差+成本归因等关键问题 | Phase 2.4 9Q |
| 29 | **每个因子类型需要不同的中性化策略**——事件因子仅行业中性化，估值因子行业+市值 | P0-4规则表 |
| 30 | **不要在同一个小因子池里反复优化**——跳出5因子框架，先扩展因子维度再考虑模型 | Phase 3方向决策 |

---

## 附录A：E2E Portfolio Network 详细设计（保留+更新）

### A.1-A.7 (保留V4原文)

详见V4文档原文。核心架构：LightGBM预测层 + PortfolioMLP/Attention权重层。

### A.8 完美预测上界 — ✅ 已完成

| 方法 | Sharpe | MDD |
|------|--------|-----|
| 基线 EW CORE5+SN | 0.68 | -39.35% |
| 完美预测+EW Top-20 | **3.02** | -49.23% |
| 完美预测+EW+SN | **2.68** | -40.15% |
| 完美预测+MVO | **3.02** | -49.23% |

**结论：** MVO=EW在完美预测下(3.02=3.02)。巨大的gap(0.68→3.02)=瓶颈100%在预测层。

### A.9 PN v1实验结果（V5新增）

- tensor val_sharpe=1.26(训练收敛)
- 实盘SimpleBacktester Sharpe=-0.99
- 根因：softmax over 5000只→微小权重(¥328/position)→¥5佣金地板=152%成本
- **结论：可微Sharpe在A股当前成本结构下不可行。DSL(cross-entropy+离线最优)是替代方案**

### A.10 Phase 2.2 方法对比（V5新增）

| # | 方法 | Sharpe | vs 基线 |
|---|------|--------|--------|
| 0 | EW CORE5+SN(基线) | 0.6211 | — |
| 1 | LambdaRank+SN | 0.5573 | -10.3% |
| 0b | LightGBM reg+SN | 0.4421 | -28.8% |
| 3a | IC_IR weighted+SN | 0.2694 | -56.6% |
| 3b | MVO(Top-40) | 0.2598 | -58.2% |
| 3b | IC+MVO | 0.2087 | -66.4% |

**结论：** 6种方法全败。等权在当前因子集上不可超越。

---

## 附录B：V2方案任务最终完成状态

### 审计10个问题（V4保留）

| # | 问题 | 状态 |
|---|------|------|
| 1 | IC口径不统一 | ✅ ic_calculator.py + 铁律19 |
| 2 | 未做OOS | ✅ WF 5折 + 逐年度 |
| 3 | FF3不可追溯 | ✅ ff3_attribution.py |
| 4 | factor_evaluation=0行 | ✅ batch_gate_v2: 17 PASS |
| 5 | factor_health停了 | ✅ 恢复+新health_check.py |
| 6 | Profiler缓存缺失 | ✅ 重建完成 |
| 7 | 3个漏网因子 | ✅ G2 FAIL+替换不显著 |
| 8-10 | 低优先级 | ❌ 保持低优先级 |

### Git里程碑（V5扩展）

| Tag/Commit | 内容 |
|------------|------|
| pre-refactor-baseline | 重构前基线 |
| refactor-complete | Step 0-6C重构完成 |
| wf-oos-v1 | Step 6-D WF OOS + FF3归因 |
| (eed4182) | Step 6-E IC基础设施修复 |
| (cb89a2b) | Step 6-E Alpha衰减归因 |
| (f84eda7) | Step 6-F 因子替换/SN/噪声/画像 |
| (715411a) | Step 6-G Modifier层+batch_gate_v2 |
| (5953211) | Step 6-H SN inner |
| (f8d13fb) | Step 6-H Regime+LightGBM |
| (c5b8181) | 阶段0调研完成 |
| (df7d63d+9c03b4f) | Phase 1.2收官 |
| (f47349b) | Phase 2.1 E2E融合 |
| (51b1409) | **Phase 2 收官 + PT重启(CORE3+dv_ttm)** |

---

## 附录C：Phase 3 详细Roadmap

### C.1 Phase 3A: 零成本因子扩展（1-2天）

不需要拉取新数据，用现有klines_daily/daily_basic/earnings_announcements计算。

| 任务 | 新因子数 | 来源 |
|------|---------|------|
| Alpha158剩余 | ~130 | klines_daily + 开源代码(Qlib/KunQuant) |
| daily_basic基本面 | ~8 | pe_ttm/ps_ttm/volume_ratio等 |
| Tushare stk_factor | ~15 | MACD/KDJ/RSI/BOLL/CCI(已算好) |
| earnings因子 | ~5 | SUE/盈利增速(数据已入库) |
| **小计** | **~160** | |

### C.2 Phase 3B: 新数据入库（后台并行，2-3天）

| 数据源 | 接口 | 因子类型 | 优先级 |
|--------|------|---------|--------|
| Tushare | fina_indicator | 基本面(ROE/ROA/毛利率) | 高 |
| Tushare | moneyflow | 资金流(主力净流入) | 高 |
| Tushare | margin_detail | 资金流(融资融券) | 高 |
| Tushare | stk_holdernumber | 资金流(股东户数) | 中 |
| Tushare | forecast/express | 事件(业绩预告) | 中 |
| Tushare | top_list/top_inst | 资金流(龙虎榜) | 中 |
| AKShare | 东财主力资金流 | 资金流(分钟级) | 中 |
| AKShare | 机构调研 | 情绪 | 低 |
| BaoStock | 季频财务因子 | 基本面(已算好) | 中 |
| — | minute_bars续拉 | 微结构(46%→100%) | 高 |

### C.3 Phase 3C: 因子分类+组间正交组合（1-2天）

把300+因子按经济逻辑分8组，每组选1-3个代表，跨组正交组合测试。

| 组 | 因子类型 | 预期数量 | 经济逻辑 |
|----|---------|---------|---------|
| 1 | 流动性/换手 | ~30 | 低流动性溢价 |
| 2 | 波动率/风险 | ~30 | 低波动溢价 |
| 3 | 价值/估值 | ~15 | 便宜股被低估 |
| 4 | 动量/反转 | ~40 | 趋势延续/均值回归 |
| 5 | 资金流向 | ~30 | 聪明钱跟踪 |
| 6 | 基本面/质量 | ~20 | 盈利质量筛选 |
| 7 | 技术形态 | ~100 | K线pattern |
| 8 | 事件驱动 | ~15 | 信息冲击 |

### C.4 Phase 3D: ML合成（2-3天）

100+因子→LightGBM/XGBoost WF验证。
Phase 2结论"ML不如等权"是5因子下的结论，100+因子时ML可能有优势。

### C.5 Phase 3E: 新范式探索（1-2周）

| 方向 | 解决什么问题 | 优先级 | 开源代码 |
|------|------------|--------|---------|
| **Kronos** | 时序信号(正交于截面因子) | P1 | HuggingFace NeoQuasar/Kronos-base |
| **DSL** | Portfolio构建(6方法全败的瓶颈) | P1 | github.com/DSLwDE/DSLwDE |
| **GNN** | 股票间关联(板块联动) | P2 | 多个实现 |
| **FactorVAE** | 自动因子发现 | P2 | AAAI 2022代码 |

### C.6 Phase 3F: PEAD Q1 2026（4/20-4/25）

Q1财报数据可用后拉取计算。Phase 1.2结论：Q1×7天×direction=-1，IC=-0.098。

### C.7 Phase 3G: 自动化（V4 Phase 3内容融入）

| 任务 | 内容 | 依赖 |
|------|------|------|
| 3G-1 | Rolling WF自动化(每月重训练) | 3D ML配置确定后 |
| 3G-2 | IC监控告警(factor_health扩展为daily) | 3A因子扩展后 |
| 3G-3 | 因子生命周期闭环(active→warning→retired) | 3C分类后 |
| 3G-4 | Parquet缓存自动重建(hooks集成) | P0-4 TODO |

### C.8 并行执行计划

```
Week 1 (4/13-4/18):
  前台CC: Phase 3A（零成本因子扩展）
  后台: Phase 3B数据拉取 + minute_bars续拉
  被动: Phase 3.0 PT监控

Week 2 (4/20-4/25):
  前台CC: Phase 3C因子分类+组合 + 3F PEAD数据
  后台: Phase 3B续拉
  可选: 3E-1 Kronos评估

Week 3 (4/27-5/2):
  前台CC: Phase 3D ML合成(100+因子WF)
  可选: 3E-2 DSL

Week 4+:
  3E-3 GNN / 3E-4 FactorVAE / 3G自动化
  PT配置更新（如果发现更优配置）
```

### C.9 成功标准

| 阶段 | 成功标准 |
|------|---------|
| 3A+3B | 因子池从63扩展到200+ |
| 3C | 跨组正交组合Sharpe > 当前1.03 |
| 3D | ML合成(100+因子) Sharpe > 等权 |
| 3E-1 | Kronos与CORE corr < 0.3 |
| 3E-2 | DSL Sharpe > 等权 |
| 整体 | WF验证后OOS Sharpe > 1.0 |
