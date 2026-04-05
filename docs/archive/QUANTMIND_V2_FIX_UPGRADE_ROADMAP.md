# QuantMind V2 — 修复+升级落地文档（全项目版）

> **版本**: 1.0 | **日期**: 2026-03-30
> **基于**: 20,000+行设计文档逐行审查 + 6批审计结果 + 36条经验教训 + 74条因子测试 + 用户10项决策确认
> **约束**: PT v1.1运行中(Day 3/60)，绝对不可中断
> **优先级原则**: 正确性 > 工程基础 > 策略能力 > AI闭环 > 前端 > 生产加固
> **Phase内并行、Phase间串行**（用户确认G8）

---

## 0. 决策确认摘要

| # | 决策 | 确认结果 | 影响范围 |
|---|------|---------|---------|
| G1 | 中性化方法 | **WLS（直接用，不量化OLS差异）** | Phase A正确性修复 |
| G2 | GP引擎 | **EvoGP替换DEAP（RTX 5070 GPU）** | Phase D AI闭环 |
| G3 | 图表库 | **TradingView Lightweight Charts + ECharts（替换Recharts）** | Phase E前端 |
| G4 | 回测架构 | **实现Hybrid（Phase A向量化 + Phase B事件驱动分离）** | Phase C策略层 |
| G5 | async/sync | **保持混合** | 不变，文档化 |
| G6 | 日志 | **structlog全栈统一** | Phase B工程基础 |
| G7 | Service注入 | **FastAPI Depends全栈统一** | Phase B工程基础 |
| G8 | Phase顺序 | **Phase内并行、Phase间串行** | 全局 |
| G9 | PT保护 | **严格不触碰v1.1链路** | 全局约束 |
| G10 | React版本 | **React 19延后** | 不变 |

---

## 1. Phase A — 正确性修复（必须首先完成）

> **原则**: 所有修复在独立脚本/独立分支验证，不触碰run_paper_trading.py核心链路（G9）。
> 验证通过后，PT毕业时统一合并。

### A1. 中性化统一为WLS

| 属性 | 值 |
|------|------|
| **任务** | factor_engine.py和neutralizer.py统一使用WLS(√market_cap加权)回归 |
| **来源** | DESIGN_V5 §4.4 + 审计批次3/6 + G1确认 |
| **改动文件** | `backend/engines/factor_engine.py`, `backend/engines/neutralizer.py` |
| **验证标准** | ① 两条链路中性化结果完全一致(diff=0) ② MAD统一为5σ ③ 5因子IC变化<5% ④ 回测Sharpe变化<3% |
| **依赖** | 无 |
| **估时** | 1天 |
| **风险** | WLS可能微调IC值，需与当前基线对比确认无显著恶化 |
| **回滚** | 保留OLS旧函数，配置开关切换 |

### A2. 涨跌停板块差异

| 属性 | 值 |
|------|------|
| **任务** | can_trade()第3级fallback按板块区分: 主板±10%, 创业板/科创±20%, ST±5%, 北交所±30% |
| **来源** | DESIGN_V5 §5.3 + DEV_BACKTEST_ENGINE P2 + 审计批次6 |
| **改动文件** | `backend/engines/backtest_engine.py` (SimBroker.can_trade), `backend/engines/paper_broker.py` |
| **验证标准** | ① 创业板300xxx涨20%不被误拒 ② 科创688xxx跌20%正确识别 ③ ST股±5%正确 ④ 北交所±30%正确 ⑤ 回测拒单率变化合理(<2%) |
| **依赖** | symbols表board字段已填充（或用代码前缀推断） |
| **估时** | 0.5天 |

### A3. turnover_rate空值修复

| 属性 | 值 |
|------|------|
| **任务** | can_trade()中turnover_rate为NULL时从daily_basic补填，仍缺则fallback=True(不误拒) |
| **来源** | 补充扫描 |
| **改动文件** | `backend/engines/backtest_engine.py`, 数据拉取脚本 |
| **验证标准** | ① 茅台(600519)不再因turnover=NULL被误拒 ② 全市场NULL率<1% |
| **估时** | 0.5天 |

### A4. 数据单位注释审计

| 属性 | 值 |
|------|------|
| **任务** | 审计slippage_model/FactorDSL/factor_engine中所有amount/volume使用，确认单位转换正确。DDL COMMENT已标注但代码侧需grep确认 |
| **来源** | TUSHARE_CHECKLIST §三 + 补充扫描 |
| **改动文件** | 视审计结果定 |
| **验证标准** | ① grep所有`amount`使用点，每处标注单位 ② VWAP = amount×1000 / (volume×100)验证正确 ③ amihud中|ret|/(amount_元)单位一致 |
| **估时** | 0.5天 |

### A5. 成交量约束实现

| 属性 | 值 |
|------|------|
| **任务** | SimBroker增加单笔交易≤日成交额10%检查（volume_cap_pct配置项） |
| **来源** | DEV_BACKTEST_ENGINE §4.9 + CostConfig.volume_cap_pct=0.10 |
| **改动文件** | `backend/engines/backtest_engine.py` |
| **验证标准** | ① 小盘股大额买入被正确拦截 ② 正常交易不受影响 ③ 回测拒单记录含拒因="volume_cap" |
| **估时** | 0.5天 |

### A6. API 500错误修复（6个）

| 属性 | 值 |
|------|------|
| **任务** | 修复/api/risk/state, /api/risk/history, /api/factors/correlation, /api/backtest/{id}/nav, /api/backtest/{id}/trades, /api/strategies/{id}/versions |
| **来源** | 审计批次1-4 |
| **改动文件** | 对应Router和Service文件 |
| **验证标准** | ① 6个端点全部返回200/正确数据 ② 无表→返回空数组不是500 |
| **估时** | 1.5天 |

### A7. holdings pnl_pct补充

| 属性 | 值 |
|------|------|
| **任务** | position_snapshot表pnl_pct字段补充计算逻辑 |
| **来源** | 审计批次1 |
| **改动文件** | `backend/engines/paper_broker.py` |
| **验证标准** | ① pnl_pct = (market_value - cost_basis) / cost_basis ② 无NULL |
| **估时** | 0.5天 |

### A8. z-score后再截断±3 ⭐(I-1.1升级)

| 属性 | 值 |
|------|------|
| **任务** | preprocess流程Step 4(zscore)后增加Step 5: clip(z, -3, +3) |
| **来源** | DESIGN_V5 §4.4 Step5 |
| **改动文件** | `backend/engines/factor_engine.py` (preprocess函数) |
| **验证标准** | ① zscore后max(abs(z))≤3.0 ② 5因子IC变化<2%(截断影响极端值不大) |
| **估时** | 0.5天 |

### A9. IC forward return用超额收益 ⭐(I-1.4升级)

| 属性 | 值 |
|------|------|
| **任务** | 确认factor_analyzer.py中IC计算的forward_return定义是否使用vs CSI300超额收益。如不是，修改为excess_return = stock_return - hs300_return |
| **来源** | DEV_BACKTEST_ENGINE P8 + DEV_FACTOR_MINING P2 |
| **改动文件** | `backend/engines/factor_analyzer.py` |
| **验证标准** | ① grep确认forward_return计算公式 ② 修改后IC值与历史对比（超额IC通常低于绝对IC） ③ 停牌期间用行业指数代替 |
| **估时** | 1天（含验证） |

### A10. 确定性排序mergesort ⭐(I-2.5升级)

| 属性 | 值 |
|------|------|
| **任务** | grep全项目sort_values调用，确保关键路径都使用kind='mergesort'保证稳定排序 |
| **来源** | DEV_BACKTEST_ENGINE P5 |
| **改动文件** | `backend/engines/signal_engine.py`, `backend/engines/backtest_engine.py` 等 |
| **验证标准** | ① 同一输入运行3次结果hash完全一致 ② grep -rn "sort_values" 无遗漏 |
| **估时** | 0.5天 |

### Phase A 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 10 |
| 总估时 | ~7天 |
| 并行可能 | A1-A5可并行, A6独立, A7-A10可并行 |
| PT影响 | ❌ 零影响（全部在独立分支验证） |

---

## 2. Phase B — 工程基础

> **前置**: Phase A全部完成
> **原则**: 为Phase C-F提供基础设施

### B1. structlog全栈统一

| 属性 | 值 |
|------|------|
| **任务** | 替换所有logging/loguru调用为structlog。dev(ConsoleRenderer)/prod(JSONRenderer)自动切换 |
| **来源** | G6确认 + R6 + IMPLEMENTATION_MASTER §4.5.2 |
| **改动文件** | 新建`backend/app/logging_config.py`, 修改所有含`import logging`的文件 |
| **验证标准** | ① grep -rn "import logging" 结果为0 ② JSON日志可被ELK/jq解析 ③ RotatingFileHandler 10MB×7 |
| **估时** | 1.5天 |

### B2. FastAPI Depends全栈统一

| 属性 | 值 |
|------|------|
| **任务** | 所有Service统一用Depends链注入。消除手动new Service()的写法 |
| **来源** | G7确认 + DEV_BACKEND Review P1 |
| **改动文件** | 所有`backend/app/services/*.py`, `backend/app/api/*.py` |
| **验证标准** | ① grep "= NotificationService()" 结果为0（应全部通过Depends） ② 现有测试全通过 |
| **估时** | 1天 |

### B3. TimescaleDB hypertable确认

| 属性 | 值 |
|------|------|
| **任务** | 确认klines_daily和factor_values已创建为hypertable，chunk_time_interval=1month |
| **来源** | DDL_FINAL.sql + DESIGN_V5 §10 |
| **验证标准** | ① `SELECT * FROM timescaledb_information.hypertables` 含两表 ② chunk interval=1 month |
| **估时** | 0.5天 |

### B4. DDL vs DB对齐

| 属性 | 值 |
|------|------|
| **任务** | 对比DDL_FINAL.sql(45张表)与实际DB，补建缺失表。配置Alembic迁移 |
| **来源** | ARCHITECTURE_AUDIT §三 + 审计批次5 |
| **改动文件** | `alembic/`, 数据库 |
| **验证标准** | ① `\dt` 表数=45 ② Alembic `alembic upgrade head` 可执行 ③ 所有FK约束正确 |
| **估时** | 2天 |

### B5. 备份自动化

| 属性 | 值 |
|------|------|
| **任务** | pg_dump每日02:00自动执行(7天滚动+月永久)。关键表额外Parquet快照 |
| **来源** | DEV_SCHEDULER P3 + SOP §6 + R6 |
| **改动文件** | `scripts/pg_backup.py`, Task Scheduler配置 |
| **验证标准** | ① 连续3天备份文件存在 ② verify_backup.py PASS ③ 恢复到测试DB成功 |
| **估时** | 1天 |

### B6. 健康预检持久化

| 属性 | 值 |
|------|------|
| **任务** | health_checks表写入每日T0预检结果。all_pass=false暂停后续链路 |
| **来源** | DESIGN_V5 Review P4 + DEV_SCHEDULER P2 |
| **改动文件** | `scripts/health_check.py`, 调度脚本 |
| **验证标准** | ① 预检结果写入DB ② PG断连时链路被阻断 ③ 钉钉P0告警触发 |
| **估时** | 1天 |

### Phase B 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 6 |
| 总估时 | ~7天 |
| 并行可能 | B1-B2可并行, B3-B4可并行, B5-B6可并行 |

---

## 3. Phase C — 策略层

> **前置**: Phase A+B完成
> **原则**: 增强策略能力，为AI闭环提供回测基础

### C1. Hybrid回测架构实现

| 属性 | 值 |
|------|------|
| **任务** | 将回测引擎重构为Phase A(向量化信号层) + Phase B(事件驱动执行层)分离架构 |
| **来源** | G4确认 + DESIGN_V5 §11.1 + DEV_BACKTEST_ENGINE §3.1 |
| **改动文件** | `backend/engines/backtest_engine.py`重构, 新建`backend/engines/vectorized_signal.py` |
| **验证标准** | ① Phase A: 全numpy/pandas批量计算因子→合成→排序→目标持仓 ② Phase B: 逐日循环T+1/涨跌停/停牌/成交量/滑点 ③ 结果与当前SimpleBacktester一致(hash相同) ④ 性能提升>2x |
| **估时** | 3天 |
| **风险** | 重构大，需确保与SimpleBacktester结果完全一致后才切换 |

### C2. DataFeed多源支持

| 属性 | 值 |
|------|------|
| **任务** | DataFeed支持from_database/from_parquet/from_dataframe三种输入 |
| **来源** | DEV_BACKTEST_ENGINE P10 |
| **改动文件** | 新建`backend/engines/datafeed.py` |
| **验证标准** | ① Parquet快照确定性测试PASS ② from_dataframe可注入合成数据 ③ 三种来源产出相同结果 |
| **估时** | 1.5天 |

### C3. 因子衰减3级自动处置

| 属性 | 值 |
|------|------|
| **任务** | 实现DESIGN_V5 §4.5的3级因子衰减处置：L1告警/L2自动降权/L3退役 |
| **来源** | DESIGN_V5 §4.5 + I-1.2 |
| **改动文件** | `scripts/factor_health_daily.py`, `backend/engines/factor_analyzer.py` |
| **验证标准** | ① IC_MA20<IC_MA60×0.8触发P2告警 ② IC_MA20<IC_MA60×0.5触发自动降权至0.5x ③ IC<0.01连续60天退为candidate ④ 全部写入factor_ic_history |
| **估时** | 2天 |

### C4. 因子择时[0.5x, 1.5x]

| 属性 | 值 |
|------|------|
| **任务** | 实现DESIGN_V5 §4.6的因子权重动态调整机制 |
| **来源** | DESIGN_V5 §4.6 + I-1.3 |
| **改动文件** | `backend/engines/signal_engine.py` |
| **验证标准** | ① 权重范围clip在[0.5x, 1.5x] ② 基于滚动IC调整方向正确 ③ 回测含因子择时vs不含对比 |
| **估时** | 1.5天 |

### C5. 回测报告12项指标补全

| 属性 | 值 |
|------|------|
| **任务** | 自动输出Calmar/Sortino/连续亏损天数/胜率/盈亏比/Beta/IR/年换手/Bootstrap CI/跳空统计/仓位偏差/成本敏感性 |
| **来源** | DEV_BACKTEST_ENGINE P6-P7-P9 + I-2.1/I-2.2/I-2.3 |
| **改动文件** | `backend/engines/metrics.py`, backtest结果输出 |
| **验证标准** | ① 12项指标全部出现在回测报告JSON中 ② Bootstrap CI 1000次采样 ③ 成本敏感性0.5x/1x/1.5x/2x自动对比 ④ 2x成本Sharpe<0.5标红 |
| **估时** | 2天 |

### C6. CompositeStrategy + RegimeModifier

| 属性 | 值 |
|------|------|
| **任务** | 实现核心策略+Modifier叠加框架。RegimeModifier：高波(>1.5x中位数)降仓至0.7x |
| **来源** | IMPLEMENTATION_MASTER §5.2-5.3 + R3 |
| **改动文件** | `backend/engines/strategies/composite.py`, `backend/engines/modifiers/regime_modifier.py` |
| **验证标准** | ① 无Modifier时=核心策略(仅差cash_buffer) ② 高波时总仓位降至~70% ③ scale_factor clip在[0.3, 1.5] ④ MDD改善>5% |
| **估时** | 2.5天 |

### C7. FactorClassifier

| 属性 | 值 |
|------|------|
| **任务** | 基于ic_decay半衰期+信号分布形态自动分类因子→策略类型(Ranking/FastRanking/Event/Modifier) |
| **来源** | IMPLEMENTATION_MASTER §5.1 + R1 |
| **改动文件** | 新建`backend/engines/factor_classifier.py` |
| **验证标准** | ① 5个Active因子全部分类为RANKING(月度) ② 半衰期<5天→FastRanking ③ 峰度>5→Event |
| **估时** | 2天 |

### Phase C 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 7 |
| 总估时 | ~14.5天 |
| 并行可能 | C1-C2可并行, C3-C4可并行, C5独立, C6-C7可并行 |

---

## 4. Phase D — AI闭环

> **前置**: Phase C完成（Gate Pipeline + SimBroker + FactorClassifier就绪）
> **原则**: GP-first，不上LLM直到GP验证可行

### D1. EvoGP引擎（替换DEAP）

| 属性 | 值 |
|------|------|
| **任务** | 用EvoGP替代DEAP，利用RTX 5070 GPU加速。岛屿模型+Warm Start+逻辑参数分离 |
| **来源** | G2确认 + GP_CLOSED_LOOP_DESIGN |
| **改动文件** | `backend/engines/mining/gp_engine.py`重写 |
| **验证标准** | ① 2小时内50代×4岛×200个体 ② 产出≥10个通过快速Gate(G1-G4) ③ 适应度=SimBroker Sharpe×(1-complexity)+novelty ④ GPU利用率>50% |
| **估时** | 4天 |

### D2. FactorDSL + 量纲约束

| 属性 | 值 |
|------|------|
| **任务** | 28算子+终端节点+表达式树+量纲约束+AST去重 |
| **来源** | GP_CLOSED_LOOP_DESIGN §2 + DEV_FACTOR_MINING |
| **改动文件** | `backend/engines/mining/factor_dsl.py` |
| **验证标准** | ① 28算子全部可执行 ② 无意义组合被量纲约束拒绝 ③ AST hash去重有效 |
| **估时** | 2天 |

### D3. Factor Gate Pipeline G1-G8

| 属性 | 值 |
|------|------|
| **任务** | 8层Gate自动化：Success/Coverage/IC/t-stat/Neutral/Dedup/Stability/Turnover |
| **来源** | IMPLEMENTATION_MASTER §5.4 + DEV_FACTOR_MINING |
| **改动文件** | `backend/engines/factor_gate.py` |
| **验证标准** | ① mf_divergence(IC=9.1%)通过8/8 ② 随机噪声G3拦截 ③ big_small_consensus G5拦截 ④ 短路模式正确 |
| **估时** | 2.5天 |

### D4. GP Pipeline自动化

| 属性 | 值 |
|------|------|
| **任务** | Task Scheduler每周触发GP Pipeline。结果写入pipeline_runs+gp_approval_queue。钉钉通知 |
| **来源** | GP_CLOSED_LOOP_DESIGN §6-7 |
| **改动文件** | `scripts/run_gp_pipeline.py`, Task Scheduler配置 |
| **验证标准** | ① 每周自动运行无人工干预 ② 结果写入DB ③ 钉钉推送候选因子 ④ 第2轮包含第1轮Top因子 |
| **估时** | 2天 |

### D5. LLM 3-Agent基础

| 属性 | 值 |
|------|------|
| **任务** | DeepSeek API客户端 + ModelRouter + Idea Agent + Factor Agent + Eval Agent |
| **来源** | DEV_FACTOR_MINING §2 + IMPLEMENTATION_MASTER §5.6 + R7 |
| **改动文件** | `backend/engines/mining/agents/` 目录 |
| **验证标准** | ① DeepSeek API连通 ② Idea Agent生成3个假设 ③ Factor Agent生成可执行代码 ④ Eval Agent正确评估 |
| **估时** | 4天 |

### D6. Pipeline Orchestrator 8节点

| 属性 | 值 |
|------|------|
| **任务** | 8节点状态机编排三引擎(BruteForce/GP/LLM)。Thompson Sampling选引擎 |
| **来源** | IMPLEMENTATION_MASTER §4.3-4.4 + DEV_AI_EVOLUTION |
| **改动文件** | `backend/engines/mining/pipeline_orchestrator.py` |
| **验证标准** | ① SELECT_ENGINE→GENERATE→SANDBOX→GATE→CLASSIFY→BACKTEST→APPROVAL→ACTIVATE全链路 ② Thompson Sampling ~30次后偏好稳定 |
| **估时** | 3天 |

### Phase D 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 6 |
| 总估时 | ~17.5天 |
| 并行可能 | D1-D2可并行, D3独立, D4依赖D1, D5-D6可并行 |

---

## 5. Phase E — 前端

> **前置**: Phase B完成（WebSocket/API基础就绪）
> **可与Phase C/D部分并行**（前端用mock数据先行开发UI骨架）

### E1. 图表库替换

| 属性 | 值 |
|------|------|
| **任务** | Recharts→TradingView Lightweight Charts(K线/净值) + ECharts(热力图/相关性/IC时序) |
| **来源** | G3确认 |
| **改动文件** | 前端chart组件全部 |
| **验证标准** | ① K线图交互流畅(zoom/pan/crosshair) ② 月度热力图正常 ③ Bundle size增量<500KB |
| **估时** | 3天 |

### E2. 12页面补全

| 属性 | 值 |
|------|------|
| **任务** | 按DEV_FRONTEND_UI规格补全所有页面。当前17个页面文件存在但多数依赖mock数据 |
| **来源** | DEV_FRONTEND_UI全文 + FRONTEND_INVENTORY |
| **验证标准** | ① 所有页面从mock切换到真实API ② 核心交互(回测配置→运行→结果)端到端可用 |
| **估时** | 8天（分Sprint） |

### E3. WebSocket集成

| 属性 | 值 |
|------|------|
| **任务** | python-socketio服务端 + socket.io-client前端。5通道：backtest/factor-mine/pipeline/notifications/forex |
| **来源** | IMPLEMENTATION_MASTER §5.7 + DEV_FRONTEND_UI §11 |
| **验证标准** | ① 回测进度实时推送 ② 通知铃铛实时更新 ③ 断连自动重连(指数退避) |
| **估时** | 3天 |

### E4. 15项Figma改进

| 属性 | 值 |
|------|------|
| **任务** | IC颜色逻辑修正/因子方向标签/选中状态增强/回测8Tab补全等 |
| **来源** | DEV_FRONTEND_UI §14 |
| **验证标准** | ① IC>+0.02绿色, IC<-0.02橙色, |IC|<0.02灰色 ② 因子方向tag(↑正向/↓反向) |
| **估时** | 3天 |

### Phase E 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 4 |
| 总估时 | ~17天 |
| 并行可能 | E1独立, E2-E3有依赖, E4独立 |

---

## 6. Phase F — 生产加固

> **前置**: Phase A-E核心完成
> **可与Phase D/E后期并行**

### F1. NSSM服务化（或Servy）

| 属性 | 值 |
|------|------|
| **任务** | FastAPI/Celery/Frontend注册为Windows服务，崩溃自动重启 |
| **来源** | IMPLEMENTATION_MASTER §4.5.1 + R6 |
| **验证标准** | ① kill进程后3秒自动重启 ② 重启后服务正常 |
| **估时** | 1天 |

### F2. 220+参数全量注册

| 属性 | 值 |
|------|------|
| **任务** | DEV_PARAM_CONFIG中11个模块220+参数分批注册到param_defaults |
| **来源** | DEV_PARAM_CONFIG §3 + I-7.1 |
| **验证标准** | ① 参数总数≥200 ② 前端参数面板完整显示 ③ 参数变更写入param_change_log |
| **估时** | 2天 |

### F3. 文档同步

| 属性 | 值 |
|------|------|
| **任务** | 所有DEV文档与代码实际状态对齐。运行doc_drift_check.py |
| **来源** | TEAM_CHARTER §5.1 + IMPLEMENTATION_MASTER §10 |
| **验证标准** | ① doc_drift_check.py漂移项=0 ② 废弃的设计(如Rust回测)标记为SUPERSEDED |
| **估时** | 2天 |

### F4. 灾备演练自动化

| 属性 | 值 |
|------|------|
| **任务** | 每月第一个周日自动运行灾备恢复验证。每周快速验证备份完整性 |
| **来源** | SOP_DISASTER_RECOVERY §6 |
| **验证标准** | ① 月度演练Task Scheduler配置 ② 恢复到测试DB<30分钟 ③ 10项验证清单全通过 |
| **估时** | 1天 |

### Phase F 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 4 |
| 总估时 | ~6天 |

---

## 7. H节遗漏项分配

> 以下来自设计要求清单H节，全部纳入正式路线图。

| # | 遗漏项 | 分配Phase | 任务ID |
|---|--------|----------|--------|
| H1 | Data Contract YAML机制 | Phase B | B7(新) |
| H2 | Celery 8队列(当前1个default) | Phase B | B8(新) |
| H3 | AKShare备用源 | Phase B | B9(新) |
| H4 | 32通知模板补全 | Phase F | F5(新) |
| H5 | 盘前09:25跳空预检 | Phase C | C8(新) |
| H6 | Pre-Trade 5项检查确认 | Phase A | 已在A5覆盖 |
| H7 | Canary Check形式化 | Phase C | C9(新) |
| H8 | 参数变更冷却期前端 | Phase E | E5(新) |
| H9 | FDR多重检验显示 | Phase E | E6(新) |
| H10 | AI诊断事件驱动触发 | Phase D | D7(新) |
| H11 | AI变更三步验证 | Phase D | D8(新) |

---

## 8. I节剩余项分配

> I-1.1/I-1.4/I-2.5已升级到Phase A(A8/A9/A10)。以下为剩余项。

| # | 项目 | 分配Phase | 估时 |
|---|------|----------|------|
| I-1.2 | 因子衰减3级自动处置 | Phase C | 已在C3 |
| I-1.3 | 因子择时[0.5x,1.5x] | Phase C | 已在C4 |
| I-2.1 | Bootstrap Sharpe CI | Phase C | 已在C5 |
| I-2.2 | 成本敏感性分析 | Phase C | 已在C5 |
| I-2.3 | 12项指标补全 | Phase C | 已在C5 |
| I-2.4 | DataFeed多源 | Phase C | 已在C2 |
| I-3.1 | Data Contract YAML | Phase B | H1 |
| I-3.2 | 时区UTC统一 | Phase F | F6(新, Phase 2外汇前) |
| I-3.3 | board字段替代前缀 | Phase A | 已在A2 |
| I-4.1 | 盘前跳空预检 | Phase C | H5 |
| I-4.2 | Pre-Trade确认 | Phase A | 已覆盖 |
| I-4.3 | Canary Check | Phase C | H7 |
| I-5.1 | 15项Figma改进 | Phase E | 已在E4 |
| I-5.2 | 参数冷却期 | Phase E | H8 |
| I-5.3 | FDR显示 | Phase E | H9 |
| I-5.4 | 前端架构更新 | Phase E | 已在E2 |
| I-6.1 | AI诊断事件触发 | Phase D | H10 |
| I-6.2 | AI变更三步验证 | Phase D | H11 |
| I-6.3 | 因子拥挤度监控 | Phase D | D9(新, 架构预留) |
| I-7.1 | 220+参数注册 | Phase F | 已在F2 |
| I-7.2 | param_change_log | Phase F | 已在F2 |

---

## 9. 跨Phase依赖关系

```
Phase A (正确性, ~7天)
    │ 全部完成后
    ▼
Phase B (工程基础, ~7天)
    │ 全部完成后
    ├───────────────────────┐
    ▼                       ▼
Phase C (策略层, ~14.5天)   Phase E (前端, ~17天, 可与C并行用mock)
    │ 完成后                     │
    ▼                            │
Phase D (AI闭环, ~17.5天)        │
    │                            │
    ├────────────────────────────┘
    ▼
Phase F (生产加固, ~6天)
```

**总工时**: ~69天（约14周，Phase内并行可压缩到~10周）

---

## 10. PT保护规则（G9贯穿全程）

1. **不修改文件**: `run_paper_trading.py`, `signal_engine.py`, `paper_broker.py` 的核心逻辑
2. **不修改配置**: v1.1策略配置(5因子/等权/Top15/月度)
3. **不修改表结构**: performance_series, trade_log, position_snapshot 的现有列
4. **验证方式**: 所有Phase A修复在独立脚本中验证，结果与v1.1对比
5. **合并时机**: PT毕业(Day 60)后，统一review所有修复项，一次性合并到主链路
6. **config_guard**: 每日PT执行前检查配置一致性，不一致=P0告警+暂停

---

## 11. 风险登记簿

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| 1 | PT中断 | 低 | 极高 | G9严格执行，所有修改在独立分支 |
| 2 | WLS改IC偏差>5% | 中 | 中 | A1验证标准含IC变化<5%，超过则回退配置开关 |
| 3 | Hybrid回测结果不一致 | 中 | 高 | C1要求hash完全一致后才切换 |
| 4 | EvoGP GPU兼容性 | 中 | 中 | 保留DEAP作为CPU fallback |
| 5 | 前端工作量超估 | 高 | 中 | 12页面分Sprint交付，核心页面优先 |
| 6 | 文档同步工作量 | 中 | 低 | doc_drift_check.py自动化检测 |

---

*本文档是QuantMind V2修复+升级的唯一操作文档。每个Phase开始前应review依赖项完成状态。*
*PT v1.1链路在任何情况下不可中断。所有修改遵循"独立验证→对比确认→PT毕业后合并"流程。*
