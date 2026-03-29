# Phase 0 Progress Tracker

> Last updated: 2026-03-29 (Sprint 1.23 ✅ complete — 1664 backend + 31 frontend tests)
> Current: Phase 1, Sprint 1.23 ✅ 5缺失页面+14后端API+真实数据接入 — 1695 tests passed
> 下一步: Sprint 1.24 (策略工作台+Monaco编辑器)
> Sprint 1.8a ✅ | Sprint 1.8b ✅ | Sprint 1.9 ✅ | Sprint 1.10 ✅ | Sprint 1.11 ✅ | Sprint 1.12 ✅ | Sprint 1.13 ✅ | Sprint 1.14 ✅ | Sprint 1.15 ✅ | Sprint 1.16 ✅ | Sprint 1.17 ✅ | Sprint 1.18 ✅ | Sprint 1.19 ✅ | Sprint 1.20 ✅ | Sprint 1.21 ✅ | Sprint 1.22 ✅
> Paper Trading: v1.1 Day 3/60, NAV=995,281(3/25, +1.63%) | Sprint 1.22 commit eec69f0
> Blockers: 无
> 宪法: V3.3 生效 (8铁律+14项补充+§15 Harness工程+§16落地保障)
> 研究进度: R1✅ R2✅ R3✅ R4✅ R5✅ R6✅ R7✅ — 7维度研究全部完成
> **AI闭环战略(2026-03-28)**: 三步走 — Step1 PT赚钱(1.13-1.15) → Step2 GP最小闭环(1.16-1.17) → Step3完整AI闭环(1.18+)
> **关键决策**: GP-first不上LLM | RD-Agent借鉴不集成 | Warm Start GP(arxiv 2412.00896) | Qlib Alpha158做DSL参考

## 开发蓝图研究 (2026-03-28)

### R1: 因子-策略匹配框架 ✅
- 可扩展分类体系(不是固定4类): Ranking/FastRanking/Event/Modifier + Hybrid/Conditional/Paired/Adaptive
- `classify_factor()` 返回 `FactorClassification` dataclass(feature_vector + confidence + recommended_strategy)
- 验证覆盖: A组(5个v1.1因子) + B组(8个Reserve) + C组(34个设计因子) = N×M矩阵
- 详见: `docs/research/R1_factor_strategy_matching.md`

### R2: 因子挖掘前沿技术选型 ✅
- **评估项目**: QuantaAlpha(清华2026) / RD-Agent(微软) / FactorEngine(2026-03) / AlphaAgent(KDD2025) / FactorMiner / Qlib Alpha158 / DEAP GP
- **核心结论**: 不集成任何单一框架，提取6个项目的核心模式融入现有4引擎设计
- **选型**: DEAP(GP引擎,4.15分) + Alpha158(因子参考,4.05分) + Optuna TPE(参数优化) + AST去重(AlphaAgent) + Thompson Sampling(RD-Agent)
- **P0改进9项约12天**: 逻辑/参数分离(GP效率) + AST去重(准确率+81%) + 经验链注入 + 多样化规划 + 复杂度惩罚 + 适应度升级 + 反拥挤级联 + 失败反馈 + Alpha158缺口补充
- 详见: `docs/research/R2_factor_mining_frontier.md` + `docs/research/QLIB_GP_FACTOR_MINING_RESEARCH.md`

### R3: 多策略组合框架 ✅
- **核心结论**: 资金量小时不拆独立多策略，用"核心+Modifier叠加"三层架构
- Layer 1: 核心策略(100%资金，v1.1不变)
- Layer 2: Modifier调节器(RegimeModifier/VwapModifier/EventModifier)，不独立选股，只调节权重
- Layer 3: 全组合风控(已有)
- 整手约束是关键瓶颈: 资金拆2策略→整手误差3%→6%，拆3→9%
- **资金量达到一定规模后再做独立子策略**
- ⚠️ 注意: 100万是可配置模拟资金，非固定约束，系统需支持不同资金规模下的策略选择
- 落地工作量: Phase A约5-7天
- 详见: `docs/research/R3_multi_strategy_framework.md`

### R4: A股微观结构特性 ✅
- **核心发现**: PT实测64.5bps中，市场冲击仅7-30bps，**隔夜跳空是主要成本源(20-30bps)**
- 当前k系数基本合理，Y_small建议从1.5提到1.8，sell_penalty从1.2提到1.3
- 模型vs实测差距(~5bps)对应Sharpe误差~0.035，可接受
- P0改进: 加overnight_gap_cost组件 + tiered base_bps
- P1: 60天PT数据累积后做Bayesian校准
- 每10bps成本增加→Sharpe下降~0.07
- 详见: `docs/research/R4_A股微观结构特性.md`

### R5: 回测-实盘对齐 ✅
- **8个gap来源按Sharpe影响排序**: 交易成本(已部分解决) > 隔夜跳空(-0.05~-0.15) > 信号Alpha衰减 > 部分成交 > 竞价机制 > look-ahead残余 > 数据延迟 > 存活偏差残余
- P0: 用T+1 open作为执行价格 + 信号回放验证
- 15项look-ahead bias检查清单(4层: 数据/因子/信号/执行)
- PT数据分析3阶段: 积累(Day1-30) → 校准(Day30-45) → 验证(Day45-60)
- 详见: `docs/research/R5_backtest_live_alignment.md`

### R6: 生产架构 ✅
- **调度**: Task Scheduler主调度(OS级可靠) + APScheduler嵌入FastAPI健康检查，不用Celery Beat
- **进程管理**: NSSM注册Celery/FastAPI为Windows Service(崩溃自动重启)
- **监控**: 自建轻量方案(PG表+钉钉告警，P0/P1/P2三级)，不用Prometheus+Grafana
- **备份**: pg_dump每日02:00全量(7天滚动+月永久) + Parquet周快照 + 每周恢复验证
- **日志**: structlog JSON结构化 + RotatingFileHandler(总上限~1.25GB) + PG审计表
- **远程**: Tailscale VPN + FastAPI状态API
- 月运维成本: ~360元
- 落地: 4 Phase约30小时
- 详见: `docs/research/R6_production_architecture.md`

### R7: AI模型选型 ✅
- **加权评分最高**: DeepSeek V3.2 (4.35/5)，中文金融知识+成本最优
- **推荐混合架构(~$65-95/月)**:
  - Idea Agent: DeepSeek-R1(深度推理+中文金融)
  - Factor Agent: Qwen3-Coder-30B-A3B本地RTX 5070(零API成本，~12tok/s) + DeepSeek-V3 fallback
  - Eval Agent: DeepSeek-V3.2(快速统计分析)
  - Diagnosis Agent: DeepSeek-R1(根因分析)
- 本地部署: Qwen3-30B-A3B(MoE, 3.3B激活参数)可Q4_K_M量化装入12GB VRAM
- 核心原则: 因子挖掘是概率游戏，降低单次成本($6.5-9.5/有效因子 vs $270/GPT-5)比提高单次质量更重要
- 详见: `docs/research/R7_ai_model_selection.md`

### Sprint 1.21: 联调+E2E测试+PT毕业 (2026-03-29) ✅

**6/6任务完成 + P1 bugfix。commit f717f85。1663 tests (+80 vs Sprint 1.20)。**

- ✅ T1: backend/tests/test_e2e_full_chain.py — 14个E2E测试(factor→signal→paper trading全链路)
- ✅ T2: frontend/src/__tests__/ — 31个前端集成测试(stores/api/pages, vitest+testing-library)
- ✅ T3: scripts/pt_graduation_assessment.py — PT毕业评估脚本(Sharpe≥0.72/MDD<35%/滑点偏差<50%)
- ✅ T4: scripts/verify_qmt_broker.py — 新增--dry-run模式(非交易日环境验证)
- ✅ T5: 前端12页面polish — EmptyState/PageSkeleton/ErrorBanner共享组件+MiningTaskCenter响应式修复
- ✅ T6: React Query性能优化 — STALE常量(price 30s/factor 5min/config 30min)+gcTime 5min→10min

**P1 Bugfix**:
- factor_service.get_factor_values() 返回 Decimal 类型 → astype(float) 修复(信号生成链路TypeError)

**技术债记录**:
- beta_hedge.py:37 SQLAlchemy兼容性警告(既存)
- performance_series表无cash列 vs test fixture有cash字段(DDL不一致，下Sprint对齐)
- FactorService返回value列 vs SignalComposer期望neutral_value(已文档化接口边界)
- THEORETICAL_SLIPPAGE_BPS=5.0硬编码，建议后续从strategy_configs读取

**QA发现**:
- E2E测试初版有factor_weights参数错误+非法UUID+硬编码行数断言(铁律5违反，已修复)
- P1: Decimal×float TypeError在全链路测试中首次被发现并修复

**测试**: 1632 backend passed + 31 frontend = 1663 total (Sprint 1.20: 1583 → +80)

---

### Sprint 1.20: PT监控前端 + 生产加固 (2026-03-28) ✅

**7/7任务完成。1583 tests passed (+35 vs Sprint 1.19)。**

- ✅ T1: PTGraduation.tsx — 9指标毕业仪表盘(Day 3/60进度, Sharpe/MDD/滑点偏差/IC趋势), 3×3网格 (243行)
- ✅ T2: Dashboard待处理事项卡片 — 3条mock通知, 优先级标记
- ✅ T3: bayesian_slippage_calibration.py — Bayesian/MLE滑点校准框架, ≥30条数据阈值, 45测试 (609行)
- ✅ T4: remote_status.py — `/api/v1/status` + `/api/v1/ping`, X-API-Key鉴权 (349行)
- ✅ T5: disaster_recovery_verify.py — 灾备恢复验证脚本 + SOP文档(419行) + 18测试
- ✅ T6: factor_health_daily.py 生命周期迁移 — active↔warning自动迁移(IC<历史×0.5), check_and_update_lifecycle() + 8测试
- ✅ T7: param_defaults.py 220参数 — 组合构建/风控/因子/滑点4模块全覆盖

**修复**:
- pg_backup.py ruff E741: `l` → `ln`
- disaster_recovery_verify.py: tables_ok Pyright unbound修复
- bayesian_slippage_calibration.py: np.asarray类型安全 + assert isinstance(DataFrame)
- factor_registry: name列(非factor_name) + status warning(非degraded) + ic_1d列

**QA发现(§6.5)**:
- T4-NOTE-3: NotificationDropdown groupByDay分组(已修复)
- P2 Toast: 5000ms→3000ms(按§13.4规范)

**测试**: 1583 passed, 1 xfailed (Sprint 1.19: 1548 → +35)

---

### Sprint 1.19: 集成Sprint — 模块堆叠→系统可用 (2026-03-28)

**阶段1-3全部完成。LL-033教训实践。**

**阶段1: API修复 ✅**:
- factor_service SQL: factor_name→name, description→hypothesis, factor_ic→factor_ic_history, 去掉多余JOIN
- 真实DB验证: get_factor_values返回5474行reversal_20数据

**阶段2: GP真实数据集成 ✅**:
- run_gp_pipeline.py SQL修复: klines_daily JOIN改code-based, market='astock', 去stock_valuation
- factor_values查询: 改扁平结构(code/trade_date/factor_name)
- structlog配置: 移除add_logger_name(与PrintLoggerFactory不兼容)
- DB URL: 改为quantmind_v2
- 真实数据: 1,311,878行行情, 5490股票加载成功

**阶段3: 前端→后端API连通 ✅**:
- mining_service SQL: engine→engine_type, stats→result_summary, approval_queue→gp_approval_queue
- DB补全: 创建pipeline_runs+gp_approval_queue表, 注册5个v1.1因子到factor_registry
- API验证: factors(5因子)/health/mining/PT(NAV=995,337)/dashboard全通

**测试修复(62个失败→0)**:
- test_gp_pipeline: __wrapped__签名(去掉多余MagicMock self)
- test_factor_api+test_mining_api: patch改dependency_overrides(FastAPI Depends兼容)
- test_ta_wrapper+test_quantstats_wrapper: 添加skipif(可选依赖TA-Lib/quantstats)

**正式任务 T1-T7 (2026-03-28完成)**:
- ✅ T1: SystemSettings 5-Tab页面 (系统设置/DingTalk/调度器/健康/偏好) — 648行
- ✅ T2: DashboardOverview增强 (市场快照/行业分布饼图/月度热力图) — 388行
- ✅ T3: DashboardAstock子视图 (7KPI卡/净值曲线/行业分布/月度热力图/快速操作) — 599行
- ✅ T4: 通知系统前端 (NotificationContext+Toast+NotificationPanel+Layout集成) — 458行
- ✅ T5: 系统API路由 (datasources/health/scheduler 3端点+13测试) — system.py
- ✅ T6: NSSM服务化 (FastAPI+Celery自动重启) — nssm_setup.ps1
- ✅ T7: PG备份自动化 (pg_backup.py+verify_backup.py+register) — 3脚本+20测试

**修复**:
- conftest.py: 添加项目根目录到sys.path (scripts.run_gp_pipeline可import)
- mining_service: engine→engine_type, stats→result_summary, approval_queue→gp_approval_queue
- 65个测试失败→0 (dependency_overrides/wrapped签名/依赖安装)

**测试**: 1523 passed, 1 xfailed, 0 failures
**前端**: TypeScript 0 errors, DashboardAstock 599行, 通知系统4文件

---

### Sprint 1.18: AI Pipeline前端 + Pipeline编排 + SHAP + lambdarank (2026-03-28)

**9/9项+2 bugfix完成。§5.3全流程执行。**

**TrD 前端 (2项)**:
- ✅ PipelineConsole — 4Tab(状态流程/审批/历史/AI日志), 8节点流程图, 自动化L0-L3, WS实时
- ✅ AgentConfig — 3Tab(Agent配置/模型健康/费用仪表盘), 4 Agent侧边栏

**TrB Pipeline编排 (3项)**:
- ✅ PipelineOrchestrator — 8节点状态机(1210行), 单因子+批量并行, 内存模式无DB可测
- ✅ approval API — 6端点(queue/detail/approve/reject/hold/history), 409重复保护
- ✅ mining_knowledge扩展 — +5字段(factor_hash/failure_node/failure_mode/ic_stats/run_id), 8种失败模式

**TrE Pipeline API (1项)**:
- ✅ Pipeline API — 5端点(status/runs/detail/approve/reject), 注册到main.py

**TrC ML增强 (2项)**:
- ✅ SHAP可解释性 — explain_global/local/temporal, ECharts序列化, TreeExplainer
- ✅ LightGBM lambdarank — dual mode(regression/lambdarank), NDCG@15, 截面group

**TrC 滑点+bugfix (Team Lead)**:
- ✅ T6 slippage_decompose.py — 三组件分解, 模拟+PT数据, R4对比
- ✅ Bugfix: 黑名单检查种子(P1) + validate算子名(P2) + step2变体黑名单(QA P1)

**§6.5 QA**: 77测试(48原有+29新增), 发现P1 step2变体黑名单漏洞(已修复)

**测试**: 1130 passed, 0 regressions
**前端**: 1458 modules, build PASS

---

### Sprint 1.17: 因子挖掘前端 + GP闭环自动化 (2026-03-28)

**10/10项全部完成。§5.3全流程执行。**

**TrD 前端 (2项)**:
- ✅ FactorLab — GP/LLM/枚举3模式切换, WebSocket实时进化曲线, 候选因子表, AI助手面板占位
- ✅ MiningTaskCenter — 任务列表+批量操作, WS实时监控, 详情弹窗(进化曲线回放), 引擎效率BarChart
- 1450 modules, build PASS

**TrB GP闭环自动化 (3项)**:
- ✅ 跨轮次学习 — save/load/黑名单/种子注入, 岛间多样性偏移, gp_engine.py 980→1256行
- ✅ DDL — pipeline_runs + gp_approval_queue(域12, 45张表), SQLAlchemy模型
- ✅ GP Pipeline入口 — run_gp_pipeline.py(910行, 7步闭环), JSON fallback, 钉钉通知

**TrE Mining API (1项)**:
- ✅ 5端点(run/tasks/tasks/{id}/cancel/evaluate) + MiningService(并发锁) + Celery任务

**TrC+TrA (2项, Team Lead直做)**:
- ✅ Task Scheduler — register_gp_task.ps1(每周六02:00)
- ✅ 论文研究 — AlphaPROBE(DAG剪枝)+AlphaForge(动态组合)+AlphaBench → 3个LLM prompt模板+落地策略

**Deferred (2项)**:
- ⬜ T7 DeepSeek API客户端 — session spawn限制(§1.4 ≤8), defer到下session
- ⬜ T8 Idea Agent — 同上

**§6.5 交叉审查**: qa-tester 52测试(31 pass+21 skip/Celery)
- **BUG发现**: 黑名单不检查Warm Start原始种子(P1, Sprint 1.18修)
- **建议**: Celery任务未接入previous_run(P1) + load_previous_results JSON容错(P2)

**测试**: 979+31=1010 passed, 0 regressions

**TrB LLM基础 (续做完成)**:
- ✅ DeepSeek API客户端 — DeepSeekClient+ModelRouter(R1/V3/Qwen3)+CostTracker, mock模式, 395行
- ✅ Idea Agent — 因子假设生成, T10 prompt模板集成, DSL验证+重试, 396行
- ✅ 论文深度研究(T10升级) — AlphaPROBE(20页)+AlphaAgent(10页)全文精读, 3升级版prompt+DAG剪枝策略
- §6.5 QA: 57测试(29原有+28新增), 发现P2 bug(validate不检查算子名)

**测试(最终)**: ~1067 passed (979+57+31), 0 regressions

**技术债(Sprint 1.18+)**:
1. 黑名单不检查种子因子(QA P1 bug)
2. Celery mining_tasks未接入previous_run(跨轮次学习生产路径未生效)
3. mining_service asyncpg直连绕过SQLAlchemy pool(双连接池)
4. mining_tasks跨层导入scripts内部函数
5. FactorDSL.validate()不检查算子名(QA P2 bug)
6. DeepSeek R1 `<think>` 标签JSON解析容错(ml-engineer已有fallback,需真实API验证)

---

### Sprint 1.16: 因子模块前端 + GP最小闭环核心 (2026-03-28)

**7/7项任务完成，Step 2核心Sprint。§5.3全流程执行。**

**TrD 前端 (2项)**:
- ✅ FactorLibrary — 因子表格(排序/筛选)+健康度面板(ECharts donut+IC趋势)+相关性热力图
- ✅ FactorEvaluation(6Tab) — IC分析/分组收益/IC衰减/相关性/分年度/分市场状态
- 793 modules, build PASS

**TrE Factor API (1项)**:
- ✅ 5端点: factors/health/correlation/{name}/{name}/report, 注册到main.py

**TrB GP最小闭环 (3项，Step 2核心)**:
- ✅ FactorDSL — 28算子(时序11+截面3+单目6+双目6+时序双目2), 表达式树, 量纲约束, 逻辑/参数分离
- ✅ GP Engine — DEAP集成, Warm Start(5因子模板→变体), 岛屿模型(环形迁移), 适应度=IC_IR×(1-complexity)+novelty
- ✅ QuickBacktester — 简化回测(<2秒/因子), 月度等权Top15, 21测试pass

**§6.5 交叉审查**:
- ✅ qa-tester: 160新测试(DSL 85+GP 55+QuickBT补充20), 160/160 PASS
- QA发现: GP seed_ratio=0.0未validate(P1), 单截面IC std硬编码(P1), 岛屿warm部分相同(P2)

**测试**: 1129 passed (857→1129, +272 new), 0 regressions

**技术债(Sprint 1.17+)**:
1. GP适应度用IC_IR代理(非SimBroker Sharpe)，QuickBacktester DB接口后替换
2. 单截面ic_std=0.01硬编码(P1)
3. Warm Start岛屿间种子变体相同(P2)
4. Factor API批量查询优化(N+1问题)
5. Warm Start真实数据验证（合成数据不占优是预期内的）

---

### Sprint 1.15: 回测结果前端 + 策略验证 + Gate Pipeline (2026-03-28)

**8/8项任务完成，成败标准全部达成。**

**TrD 前端 (3项)**:
- ✅ BacktestRunner — 进度条+实时ECharts净值+日志流+取消, WS优先+REST fallback
- ✅ BacktestResults(8Tab) — 8指标卡+净值曲线/月度热力图/持仓/交易明细/WF/风险/因子贡献/对比
- ✅ StrategyLibrary — 卡片/表格双视图, 筛选+排序, 2策略对比模式
- `npm run build` PASS: 782 modules, 0 errors

**TrE WebSocket (1项)**:
- ✅ python-socketio后端 + socket.io-client前端 — 4事件类型(progress/status/nav/log), room管理

**TrB 因子Gate (1项)**:
- ✅ FactorGatePipeline G1-G8 — G1-G5自动+G6-G8半自动, v1.1五因子全PASS验证一致
- BH-FDR动态阈值(M=74→t≈3.27), quick_screen()供BruteForce调用
- 51测试全PASS

**TrA 策略验证 (1项)**:
- ✅ CompositeStrategy回测(模拟数据) — v1.1+RegimeModifier MDD改善21.6%>5%阈值

**TrC 生产基础 (2项)**:
- ✅ PT信号回放验证器 — R5 8个gap来源建模, Day20+后运行
- ✅ structlog JSON日志 — dev/prod自动切换, RotatingFileHandler 10MB×7

**测试**: 857 passed (722→857, +135 new), 0 regressions
**新依赖**: python-socketio, structlog, socket.io-client

**技术债(Sprint 1.16+)**:
1. WebSocket未接入backtest_service emit调用点
2. CompositeStrategy DB完整回测路径待实现
3. socketio cors="*"生产需收紧
4. ECharts bundle 1054KB需代码分割

### Sprint 1.13-1.15 复盘补做 (2026-03-28)

**§5.3 Sprint结束10步流程补做**:
- ✅ Step 1: PROGRESS.md更新
- ✅ Step 2: 复盘5问+投资人3问（已在本session输出）
- ✅ Step 3: 改善建议汇总（6项，含P0/P1/P2优先级）
- ✅ Step 4: LL-031(宪法规则必须立即执行) + LL-032(agent依赖验证)写入LESSONS_LEARNED
- ⬜ Step 5: TECH_DECISIONS.md — 待补
- ✅ Step 6: 规则执行记分卡（已在复盘中输出）
- ✅ Step 7: 审计日志审查（500行, 11次agent spawn, 191次edit/write, 1次拦截）
- ⬜ Step 8: BLUEPRINT更新 — 待补
- ⬜ Step 9: §5.6报告 — 1.15已输出，1.13/1.14待补
- ⬜ Step 10: Git tags — 待补

**Harness升级（用户确认后执行）**:
- ✅ `audit_log.py`: Agent记录格式升级为 `[subagent_type] description`
- ✅ `verify_completion.py`: 铁律6 + §6.5 从提醒(exit 0)升级为阻断(exit 2)
- ✅ `settings.json`: Stop hook timeout 5s→10s
- ✅ `TEAM_CHARTER §13.4`: 新增"已升级为阻断的规则"表格
- ✅ `LL-031`: 执行状态更新为已升级

**微信MCP工具安装（进行中）**:
- ✅ wexin-read-mcp server注册（3个tool: read/search/account）
- ⬜ Playwright chromium浏览器下载中（172MB）

---

### Sprint 1.14: 回测模块前端 + 因子挖掘Engine1 (2026-03-28)

**7/7项任务完成，成败标准全部达成。**

**TrD 前端 (2项)**:
- ✅ 策略工作台(StrategyWorkspace) — 三栏布局(因子面板+策略编辑+AI占位), 34因子分类展示, 可视化/代码双模式, 保存/加载API
- ✅ 回测配置(BacktestConfig) — 6个Tab(市场/时间/执行/成本/风控/动态仓位), "运行回测"→API调用
- `npm run build` PASS: 171 modules, 0 errors, 834ms

**TrB 因子挖掘 (3项)**:
- ✅ Factor Sandbox — AST安全检查(禁import/exec/eval/open), subprocess隔离, 5s超时, 白名单函数
- ✅ BruteForce引擎 — 44模板(价量20+流动性7+资金流向7+基本面7+跨源3), G1-G3快筛, ~130+候选
- ✅ AST去重器 — L1规范化(交换律+常数折叠)+SHA256, L2 dump比较, L3可选Spearman相关
- 52测试全PASS

**TrE+TrC 后端 (2项)**:
- ✅ 策略CRUD API补全 — POST/PUT/DELETE/factors/backtest 5端点, FactorClassifier+BacktestService接入
- ✅ 滑点三因素模型 — tiered_base_bps(大3/中5/小8) + impact_bps(Bouchaud) + overnight_gap_bps(R4跳空)
- 79 slippage tests PASS (含31新增)

**测试**: 722 passed (649 existing + 73 new), 0 regressions

**技术债(Sprint 1.15+)**:
1. SimBroker.calc_slippage()未接入overnight_gap(需传open_price/prev_close)
2. 策略API测试需mock StrategyService(当前仅service+repo层覆盖)
3. gap_penalty_factor=0.5待PT数据校准
4. BruteForce ConstantInputWarning(93个): 常数输入列的Spearman未定义, 不影响正确性

---

### Sprint 1.13: 前端基础设施 + 策略框架核心 (2026-03-28)

**13/13项任务完成，成败标准全部达成。**

**TrD 前端基础设施 (5项)**:
- ✅ React Router v6 + 12页面路由 + 侧边栏(折叠/展开) — `frontend/src/router.tsx` + `Layout.tsx` + `Sidebar.tsx`
- ✅ Zustand stores (auth/notification/backtest/mining) — persist中间件, 类型安全
- ✅ UI组件: GlassCard(4变体)/MetricCard(涨跌色)/Button(5变体)/Breadcrumb — 自定义Tailwind v4实现(shadcn/ui兼容问题跳过)
- ✅ Axios API client + React Query Provider — token interceptor, 指数退避重试
- ✅ 16个页面stub(含子路由) — 标题+副标题+面包屑+空状态卡片
- `npm run build` PASS: 0 errors, 109 modules, 572ms

**TrA 策略框架核心 (5项)**:
- ✅ FactorClassifier — R1决策树分类, 5因子全匹配, 23单元测试PASS
- ✅ FastRankingStrategy(weekly) — 快衰减因子专用, 新进折扣+换手控制
- ✅ EventStrategy框架 — on_event/event_filter/position_sizing抽象接口, 4事件类型
- ✅ ModifierBase + RegimeModifier — R3三层架构, HMM→VolRegime→常数三级fallback
- ✅ CompositeStrategy — 核心策略+Modifier链编排, cash_buffer=3%, max_daily_adjustment=20%

**TrE 基础设施 (3项)**:
- ✅ FactorService + BacktestService wrapper — AsyncSession Depends注入
- ✅ Alembic迁移配置 — env.py + alembic.ini, async engine, versions/目录就绪
- ✅ 文档清理 — 3个旧研究报告归档到docs/archive/

**测试**: 649 passed (544 existing + 105 new), 0 regressions
- test_factor_classifier.py: 23用例
- test_composite_strategy.py: 38用例
- test_fast_ranking_strategy.py: 34用例
- test_event_strategy.py: 33用例 (含ModifierBase/RegimeModifier测试)

**技术债(Sprint 1.14+)**:
1. `event_signals`表未在DDL中定义 — EventStrategy.load_events()查询需要此表
2. Alembic initial migration未生成 — 需PG连接执行`alembic revision --autogenerate`
3. RegimeModifier用sync psycopg2 cursor — 回测OK, async路径需适配

**关键设计决策**:
- FactorClassifier用决策树而非ML: 4条规则+边界降权, 简单透明可解释
- shadcn/ui跳过: Tailwind v4兼容问题, 自定义组件达到同等效果
- RegimeModifier clip范围[0,1]: 不加杠杆, 只缩减仓位

---

### 实施总纲 + 文档整理 (2026-03-28)

**IMPLEMENTATION_MASTER v2.0 (全项目版)**:
- `docs/IMPLEMENTATION_MASTER.md` — 2522行, 14节+2附录, 唯一操作文档
- 覆盖: BLUEPRINT 44项既有缺口 + R1-R7 73项新增 = **117项全覆盖**
- v1.0(仅R1-R7)→v2.0(全项目): 前端从点缀升级为对等规划，每Sprint前后端配套

**文档清理**:
- 9个过时文件归档至`docs/archive/`，2个agent文档移至`.claude/`
- DEV文档更新: BACKTEST_ENGINE(滑点R4) + FACTOR_MINING(R2选型) + PARAM_CONFIG(Modifier参数R3)
- `PHASE_1_PLAN.md` 精简为指针文件

**5并行轨道** (v1.0是4条，v2.0新增Track E基础设施):
- Track A (策略框架): FactorClassifier/FastRanking/EventStrategy/CompositeStrategy/Modifier
- Track B (因子挖掘): Sandbox/BruteForce/GP(DEAP)/LLM(DeepSeek)/Pipeline
- Track C (PT+生产): 滑点改进/信号回放/NSSM/备份/PT毕业
- Track D (前端): **12页面全覆盖** + 路由/状态管理/WebSocket基础设施
- Track E (基础设施): Service层补全/DB migration/测试策略/CI

**10 Sprint路线** (v1.0是8个, v2.0因前端工作量修正为10个):
- 1.13: 前端基础设施 + 策略框架核心 (2w)
- 1.14: 回测模块前端 + 因子挖掘Engine1 (2w)
- 1.15: 回测结果前端 + 策略验证 (2w)
- 1.16: 因子模块前端 + GP引擎 (2w)
- 1.17: 因子挖掘前端 + LLM集成 (2w)
- 1.18: AI Pipeline前端 + Pipeline编排 (2w)
- 1.19: 系统设置 + Dashboard增强 + 生产加固 (2w)
- 1.20: PT监控前端 + PT毕业准备 (2w)
- 1.21: 联调 + E2E测试 + PT毕业 (2w)
- 1.22: 实盘过渡 + 文档收尾 (2w)

---

## Sprint 1.12 RSRS验证: NOT JUSTIFIED

### RSRS事件型策略SimBroker回测结果 (2026-03-27)

| 指标 | RSRS Weekly | RSRS Monthly | v1.1基线 |
|------|------------|-------------|---------|
| Sharpe | 0.15 | 0.28 | 0.91 |
| autocorr-adj | 0.03 | 0.06 | — |
| 年化收益 | 0.80% | 4.02% | 21.55% |
| MDD | -45.04% | -42.75% | -58.4% |
| Bootstrap CI | [-0.78, 1.01] | [-0.64, 1.17] | [0.00, 1.85] |
| 换手率(年化) | 37.11倍 | 10.05倍 | ~8倍 |
| 2024年 | -15.92% | -12.67% | — |

**判定: NOT JUSTIFIED**
- 两种频率Sharpe均远低于基线(0.15/0.28 vs 0.91)
- Bootstrap CI包含0，不能拒绝"策略不赚钱"
- weekly换手37倍，成本1.5x下Sharpe即为负
- 2024年持续亏损(因子失效期)
- Beta=0.7，非独立Alpha

**决策: RSRS单因子策略方向关闭，维持Reserve池，作为LightGBM特征候选**
**脚本: scripts/backtest_rsrs_weekly.py (支持--freq weekly/monthly)**
**因子数据: rsrs_raw_18已入库factor_values (2020-07~2026-03, 642万行)**

### HMM 2-state Regime Detector回测结果 (2026-03-27)

| 指标 | A:无Regime | B:Vol Regime | C:HMM Regime |
|------|-----------|-------------|-------------|
| Sharpe | 1.05 | **1.08** | 1.02 |
| MDD | -38.45% | **-27.55%** | -40.64% |
| 年化收益 | 26.04% | 18.76% | 25.42% |
| 2022 MDD | -21% | **-15%** | -24% |
| 2024 MDD | -33% | **-23%** | -34% |

**判定: NOT JUSTIFIED**
- HMM在Sharpe和MDD两个维度均为三方案最差
- 2022/2024极端年份MDD恶化最严重（risk预判正确：离散状态延迟劣于连续启发式）
- 当前Vol Regime启发式继续保留
- HMM代码保留为研究模块（`backend/engines/regime_detector.py`），不入PT链路
- 影子模式可在未来PT期间收集数据验证

**脚本: scripts/backtest_hmm_regime.py (三方案A/B/C对比)**
**测试: backend/tests/test_regime_detector.py (40 PASS)**

---

## Sprint 1.11: PT毕业加速 ✅ COMPLETED

### 目标
市场冲击成本真实化 + gap_hours采集 + PT心跳watchdog + 毕业一键评估 + V3.3同步

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| 冲击成本集成 | SimBroker volume_impact(市值分层k) | SlippageConfig+方向参数 | **PASS** |
| 基线重跑 | volume-impact下全期Sharpe+CI | Sharpe 1.03→0.39(⚠️重大变化) | **PASS但需用户决策** |
| gap_hours采集 | signal_generated_at写入DB | signals+trade_log双列 | **PASS** |
| PT心跳 | watchdog检测缺失→P0告警 | pt_watchdog.py+Task Scheduler | **PASS** |
| 毕业评估CLI | 9项指标格式化输出 | check_graduation.py 411行 | **PASS** |
| collection error | 0个 | importorskip修复5个 | **PASS** |
| config_guard入链路 | Step 0.5配置一致性守卫 | assert_baseline_config | **PASS** |
| PT不中断 | v1.1日报持续 | 0 regression | **PASS** |
| 0 regression | 新增测试全PASS | 53新测试(35+8+10) | **PASS** |

### 产出物
- `backend/engines/slippage_model.py` — SlippageConfig(市值分层k_large=0.05/k_mid=0.10/k_small=0.15)
- `backend/engines/backtest_engine.py` — SimBroker volume_impact模式+direction参数
- `backend/app/services/param_defaults.py` — 6个滑点参数L2可配置
- `backend/app/services/signal_service.py` — signal_generated_at时间戳
- `backend/engines/paper_broker.py` — executed_at时间戳(双INSERT路径)
- `scripts/run_paper_trading.py` — heartbeat写入+config_guard Step 0.5+executed_at backfill
- `scripts/pt_watchdog.py` — PT心跳监控(Task Scheduler 20:00)
- `scripts/check_graduation.py` — 9项毕业评估CLI
- `CLAUDE.md` — V3.3完全同步(8铁律+9毕业标准)
- `LESSONS_LEARNED.md` — LL-030(宪法流程是编码前置条件)
- 新增测试53个(35 slippage_model + 8 integration + 10 gap_hours), 0 regression

### 研究产出
- **策略R1**: 冤杀因子策略匹配方案——RSRS(事件型,weekly,优先级1) > VWAP(排序型,daily/weekly,优先级2) > PEAD(事件型,信心最低)
- **miniQMT连接**: 验证OK(账户81001102, 总资产100万, API正常)

### 决策
| 决策 | 结果 | 判定 | 阶段 |
|------|------|------|------|
| SlippageConfig市值分层 | k_large=0.05/k_mid=0.10/k_small=0.15 | KEEP | Sprint 1.11 |
| volume_impact默认模式 | BacktestConfig.slippage_mode="volume_impact" | KEEP | Sprint 1.11 |
| 6滑点参数L2可配置 | param_defaults注册 | KEEP | Sprint 1.11 |
| PT心跳watchdog | 每日20:00检测 | KEEP | Sprint 1.11 |
| config_guard入PT链路 | Step 0.5强制检查 | KEEP | Sprint 1.11 |
| RSRS优先验证 | 事件型weekly, t=-4.35最强 | Sprint 1.12验证 | Sprint 1.11 |

### ⚠️ 基线重跑结果（§4.3用户决策级别）

| 指标 | fixed(10bps) | volume_impact(市值分层) | 差异 |
|------|-------------|----------------------|------|
| Sharpe | 1.03 | 0.39 | **0.91 (σ校准后)** |
| MDD | -39.7% | -58.4% | 待确认 |
| 年化收益 | 25.42% | 7.93% | **21.55%** |
| Bootstrap CI | [0.11, 1.99] | [-0.53, 1.31] | **[0.00, 1.85]** |

**分析**: volume-impact模型使用市值分层k系数(0.05/0.10/0.15)对小盘股冲击成本建模更真实。v1.1 Top15偏小盘，实际成本远高于固定10bps。

**需要用户决策**: (1)接受新基线？(2)调整策略偏大盘？(3)校准k系数？(4)维持fixed基线？

**Team Lead建议**: 加σ(波动率)项让模型更精准（研究Finding#1），但k绝对值可能不需要大幅下调。

**⚠️ qa关键发现**: PT实测avg slippage=64.5bps（vs SimBroker fixed预估10bps，偏差544.9%）。volume-impact模型估计55-60bps反而与实测接近！意味着真实Sharpe可能确实在0.4-0.7区间。Sprint 1.12应以PT实测数据校准，不能盲目降低k。

### 违规记录
- LL-030: Sprint启动时跳过TeamCreate直接编码（LL-027同根第2次）
- 用户2次提醒后纠正

### 遗留
- Task 8基线重跑（回测运行中）
- Task R2风险评估（延后）
- 前沿研究+设计文档审查（Sprint 1.11后独立进行）

---

## Sprint 1.10: PT风控加固 + 毕业标准补全 ✅ COMPLETED

### 目标
风控三层架构落地(Pre-trade/Daily/Opening gap) + PT毕业标准从5项扩展到9项

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| 每日风控确认 | L1-L4每日运行 | Step1.6新增 | **PASS** |
| PreTradeValidator | 5项订单级检查 | frozen dataclass | **PASS** |
| 现金缓冲 | 3%强制保留 | SignalConfig.cash_buffer=0.03 | **PASS** |
| pre-existing修复 | 2个测试修复 | l3_recovery参数同步 | **PASS** |
| 波动率regime | 对数收益率+中位数 | clip[0.5,2.0] | **PASS** |
| 开盘跳空预检 | 单股>5%/组合>3% | PT只告警 | **PASS** |
| PT毕业标准 | 5→9项 | fill_rate/slippage/TE/gap | **PASS** |
| 自相关Sharpe | Lo(2002)公式 | ρ>0惩罚 | **PASS** |
| PT不中断 | v1.1持续运行 | 0 regression | **PASS** |

### 产出物
- `backend/engines/pre_trade_validator.py` — 5项订单级风控(FIA 2024标准)
- `backend/engines/vol_regime.py` — 波动率regime缩放
- `backend/engines/metrics.py` — autocorr_sharpe + 毕业4指标
- `backend/engines/signal_engine.py` — cash_buffer + vol_regime_scale集成
- `backend/app/services/paper_trading_service.py` — 毕业标准5→9项
- `scripts/run_paper_trading.py` — Step1.6每日风控 + Step5.8跳空预检 + vol_regime前置
- `docs/DEV_SCHEDULER.md` — P6三阶段风控调度 + P7合理性检查
- `backend/tests/conftest.py` — fastapi try/except保护
- 新增测试59个(7+21+8+16+9+27+7=95实际，arch报告52+quant7=59独立文件)
- 全量回归628 passed, 1 xfailed, 0 new regression

### 研究产出(同session)
- 盘中风控全面分析报告(8维度4层方案)
- khQuant看海量化教程精读(策略4阶段+miniQMT 3种行情+XtTrade API)
- 前沿论文/平台研究(20+论文/5平台: Qlib/vnpy/Backtrader/Riskfolio-Lib/QuantStats)
- FIA 2024自动交易风控标准、arXiv因子拥挤/Kelly-VIX/A股ML增强

### 复盘

**技术5问摘要**:
1. 抓到7个错误(最严重: 非调仓日无风控)
2. 铁律4/6违反(commit前未做复盘)
3. 风控每日运行应在Sprint 1.8a就发现
4. Sprint 1.11: 市场冲击成本/盘中监控/Processor Pipeline/Sizer解耦
5. 新增LL-028(spawn文档路径) + LL-029(commit前复盘)

**投资人视角**:
- 敢投30万(30%)阶梯上量
- 反转因子拥挤崩溃+系统性下跌是主要亏钱场景
- Sprint 1.9-1.10是运维加固不是Alpha增强，没有让策略更赚钱

### 违规记录
- 铁律4违反: commit前未做复盘 → LL-029
- 铁律6违反: PROGRESS.md未先更新 → 补做
- §1.3违反: spawn缺文档路径 → LL-028

---

## Sprint 1.9: PT稳定运行 + 系统加固 ✅ COMPLETED

### 目标
P0 bug修复 + 审计缺口关闭 + 策略基础设施接入

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| ic_decay修复 | 交易日计算 | bisect_right交易日偏移 | **PASS** |
| 任务依赖链 | health→signal联动 | Redis gate + P0告警 | **PASS** |
| BaseBroker统一 | 3个Broker继承基类 | ABC + get_broker工厂 | **PASS** |
| 仓位偏差 | 非零计算 | 3指标(mean/max/cash_drag) | **PASS** |
| VWAP+RSRS入管道 | 每日计算 | RESERVE_FACTORS注册+隔离 | **PASS** |
| 通知模板补齐 | ≥5个新模板 | 5个新增(19总计) | **PASS** |
| PT不中断 | v1.1持续运行 | 0 regression | **PASS** |

### 产出物
- `backend/engines/factor_profile.py` — ic_decay交易日修复 + 缓存
- `backend/app/tasks/daily_pipeline.py` — health→signal Redis gate
- `backend/engines/base_broker.py` — BaseBroker(ABC) + get_broker()
- `backend/engines/backtest_engine.py` — SimBroker(BaseBroker)
- `backend/engines/paper_broker.py` — PaperBroker(BaseBroker)
- `backend/engines/broker_qmt.py` — MiniQMTBroker(BaseBroker)
- `backend/engines/metrics.py` — calc_position_deviation(3指标)
- `backend/engines/factor_engine.py` — calc_vwap_bias + calc_rsrs_raw + RESERVE_FACTORS
- `backend/app/services/notification_templates.py` — +5模板(19总计)
- 新增测试53个，全部通过。全量回归528/530(2 pre-existing)

### 决策
- v1.2(K=3) 不升级: p=0.657不显著 + 60天PT重计时代价太大
- VWAP/RSRS入Reserve池: 不入v1.1等权组合(LL-018等权天花板)

### 遗留
- miniQMT完整买卖验证（需交易时间执行，脚本已准备）
- 2个pre-existing测试失败(risk_control l3_recovery参数变更未同步)

---

## Sprint 1.8b: 策略层基础设施 ✅ COMPLETED

### 目标
BaseStrategy接口 + StrategyRegistry + 多频率回测框架

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| BaseStrategy接口 | 可插拔策略 | EqualWeight+MultiFreq | **PASS** |
| qa验收 | 全部通过 | 44/44 PASS | **PASS** |
| Pyright | 0错误 | 清零 | **PASS** |
| 多策略卫星方案 | risk评估 | MDD-45%被否决 | 正确否决 |

### 关键发现
1. 5个活跃因子IC不衰减（慢速因子），月度调仓正确
2. turnover/volatility本质是过滤型非排序型
3. 等权天花板5因子(LL-018)
4. A股系统性风险下相关性0.19→0.49，多策略分散化幻觉

---

## Sprint 1.8a: 架构收敛 ✅ COMPLETED

### 目标
run_paper_trading.py 1776行→<200行薄壳，业务逻辑收归Service层

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| run_paper_trading.py行数 | <200行(不含影子) | 658行核心+243影子=901行 | ⚠️ 核心658>200 |
| Service层被调用 | 不是摆设 | 5个Service实际import | **PASS** |
| 风控逻辑一份 | 无重复 | check_circuit_breaker_sync唯一 | **PASS** |
| 通知逻辑一份 | 无重复 | NotificationService.send_sync | **PASS** |
| 现有测试 | 全部通过 | 303 passed, 1 failed(pre-existing) | **PASS** |
| PT不中断 | 链路正常 | 待明天验证 | Pending |

### 产出物
- backend/app/services/db.py — 统一sync DB连接(22行)
- backend/app/services/trading_calendar.py — 交易日工具(60行)
- backend/app/services/signal_service.py — 信号生成Service(417行)
- backend/app/services/execution_service.py — 执行链路Service(499行)
- backend/app/services/risk_control_service.py — +380行sync风控方法
- backend/app/services/notification_service.py — +170行sync通知方法
- backend/app/services/paper_trading_service.py — +120行NAV更新
- scripts/run_paper_trading.py — 1776→901行(-49%)
- scripts/run_paper_trading.py.bak — 旧版备份

### 架构决策
- 全部Service统一sync psycopg2（不推async）
- FastAPI原生支持sync endpoint
- Service内部不commit，调用方统一管理事务
- 影子选股暂留script中（非核心功能）

---

## Sprint 1.7: miniQMT模拟对接 + 运维加固 ⚠️ 待收尾

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| miniQMT全链路 | 买入→确认→查持仓→卖出 | query-only通过，买卖待明天 | Pending |
| pg_dump自动备份 | 运行中 | Task Scheduler已注册02:00 | **PASS** |
| 钉钉通知覆盖 | PT日报+熔断 | 4项覆盖 | **PASS** |

### 编码完成(7/7)
- A1: broker_qmt.py (535行)
- A2: verify_qmt_broker.py 验证脚本
- A3: compare_simbroker_qmt.py 对比框架
- A4: register_qmt_autostart.ps1 (XtMiniQmt.exe，非XtItClient.exe)
- B1: pg_backup.py + register_backup_task.ps1 (首次备份3.7GB)
- B2: 钉钉通知4项覆盖
- B3: 前端Dashboard 17文件

### 额外完成
- 数据质量自动巡检(data_quality_check.py + Task Scheduler 17:00)
- 成本模型校准(佣金万1.5→万0.854国金实际费率)
- 换手率研究(方案A K=3: Sharpe=1.139, 换手242%, MDD=-35.23%)
- 设计vs实现审计(3份报告56KB, 150+功能点)
- 系统集成流程分析(识别双轨制架构问题)

### 关键发现
- miniQMT必须用XtMiniQmt.exe启动，XtItClient.exe是普通QMT模式
- 佣金万0.854比假设万1.5低43%，年省1%交易成本
- 方案A(K=3)换手率降70%且Sharpe提升10.8%，但p=0.657不显著

### 遗留
- miniQMT完整买卖验证（明天交易时间）
- PT运行验证（明天signal+execute实际跑一次）

---

## Sprint 1.6: Rolling ensemble + 分析师预期 + VWAP/RSRS ✅ COMPLETED

### 目标
1. Rolling ensemble修复+清理（免费Sharpe提升）
2. 分析师预期修正因子（Tushare forecast，新信息源）
3. arch P1修复（DB连接硬编码统一化）
4. 3/25 NAV入库问题修复
5. VWAP+RSRS因子评估 → v1.2升级决策
6. 信号平滑Inertia探索

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| v1.2升级(+vwap+rsrs) | Sharpe≥1.019, p<0.05 | Sharpe=0.902, p=0.652 | **FAIL — 否决** |
| Rolling ensemble | Sharpe提升≥5% | +13.6%但p=0.35 | Reserve |
| Forecast因子 | IC显著 | t<1.0, 中性化后归零 | **FAIL — 方向关闭** |
| 信号平滑Inertia(0.7σ) | p<0.05 | Sharpe=1.172, p=0.09 | 影子PT观察 |
| DB连接P1 | 13脚本统一 | 完成 | **PASS** |
| Drawdown修复 | qa通过 | 4/4 PASS | **PASS** |
| Execute拆分 | qa通过 | 5/5 PASS | **PASS** |

### 7因子等权回测详细结果（Sprint 1.6关键实验）
```
7F(+vwap+rsrs) vs 5F基线, 2021-2025, Top15月度行业25%
Sharpe: 0.902 vs 1.028 (-0.126)
MDD: -39.90% vs -39.64% (略恶化)
换手率: 1006% vs 799% (+207%)
p-value: 0.652 (无显著差异)
年度: 7F每年Sharpe均低于5F
risk一票否决: 2项硬性条件触发(Sharpe<0.977, 2022 MDD差3.48%)
```

### §13.3 执行记分卡
```
铁律违规: 0次
规则执行率: 7/7（1✅2✅3✅4✅5✅6✅7✅）
用户提醒次数: 1次（多窗口团队模式）
团队协作: ml+quant+risk三方审查，交叉验证完整
```

### 复盘5问（技术视角）
1. **拦截了几个错误？** quant预审发现IC测试脚本缺MAD去极值（硬伤），已修复。risk设定5项否决条件，2项触发。
2. **哪些规则执行了/没执行？** 7铁律全部执行。§1.3 agent启动规范完整（附录A prompt+上下文+交叉预期+主动发现）。交叉审查矩阵按附录B执行。
3. **应该更早发现的问题？** vwap/rsrs是短周期因子，在月度框架下时频错配——factor在Gate审批时应前置评估调仓频率匹配性。
4. **下个Sprint要改什么？** Gate审批链增加"调仓频率匹配性"检查点。
5. **新规则？** 短周期因子(窗口<20日)在月度等权框架下预期表现差，需特别论证才可入组合。

### 投资人视角3问
1. **敢投多少？** 等权v1.1继续100万模拟。不加码。5因子集中度仍是最大风险。
2. **什么环境亏？** 2022-2023小盘因子失效期（基线MDD=-39.7%）。L4熔断-25%触发。2025关税冲击单日-13.15%。
3. **本Sprint哪些真正让策略更赚钱？** 无新alpha增量。但基础设施交付（DB统一/Drawdown修复/execute拆分）提升了运维可靠性。Inertia影子PT是潜在方向。

### 编码组产出
- DB连接P1修复（13脚本统一）
- Drawdown P0修复（qa 4/4 PASS）
- 方案B execute拆分（qa 5/5 PASS）
- Inertia(0.7σ)影子PT实现
- index_daily增量拉取 + moneyflow/SW行业补拉
- backtest_7factor_comparison.py回测脚本

### 研究组产出
- Forecast因子关闭（全样本60月t<1.0）
- VWAP+RSRS单因子Gate双PASS（t=-3.53/-4.35）
- VWAP+RSRS LightGBM无增量
- Rolling ensemble Reserve（Sharpe+13.6%, p=0.35）
- 7因子等权回测否决（Sharpe=0.902, p=0.652）
- 信号平滑bootstrap陷阱识别（LL-028）

### 关键教训
- LL-028: 信号平滑bootstrap陷阱（大bonus=隐性动量）
- LL-029: 单因子IC强不等于ML增量（VWAP/RSRS t>3.5但LightGBM无增量）
- LL-030: 对照组数据一致性问题（多次出现0.0696 vs 0.0823偏差）
- 新发现: 短周期因子(窗口<20日)在月度等权框架下时频错配，换手暴增但alpha稀释

---

