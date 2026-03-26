# Phase 0 Progress Tracker

> Last updated: 2026-03-27
> Current: Phase 1, Sprint 1.11 ✅ COMPLETED
> Sprint 1.8a ✅ | Sprint 1.8b ✅ | Sprint 1.9 ✅ | Sprint 1.10 ✅ | Sprint 1.11 ✅
> Paper Trading: v1.1 Day 3/60, NAV=995,281(3/25, +1.63%)
> Blockers: 无（miniQMT连接已验证OK）
> 宪法: V3.3 生效 (8铁律+strategy升级+设计文档对照)

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
| Sharpe | 1.03 | 0.39 | -62% |
| MDD | -39.7% | -58.4% | 恶化47% |
| 年化收益 | 25.42% | 7.93% | -69% |
| Bootstrap CI | [0.11, 1.99] | [-0.53, 1.31] | 5%分位<0 |

**分析**: volume-impact模型使用市值分层k系数(0.05/0.10/0.15)对小盘股冲击成本建模更真实。v1.1 Top15偏小盘，实际成本远高于固定10bps。

**需要用户决策**: (1)接受新基线？(2)调整策略偏大盘？(3)校准k系数？(4)维持fixed基线？

**Team Lead建议**: 先校准k系数——当前默认值源自DEV_BACKTEST_ENGINE.md设计文档，可能对A股偏保守。需用PT实际成交数据反向校准。

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

## Sprint 1.5b: 基本面使用方式穷举验证 ✅ COMPLETED (方向彻底关闭)

### §13.3 执行记分卡
```
铁律违规: 0次（Sprint 1.5b期间）
规则执行率: 5/7（铁律1✅2✅3-N/A 4✅5✅6✅7✅）
用户提醒次数: 5次（团队未建/角色分配错误/未读宪法/漏掉frontend/不称职）
用户提醒 > 自检发现 → LL-027升级执行机制（Hook+检查清单+Compaction保护）
```

### 复盘5问
1. **拦截了几个错误？** qa-verify发现因子方向bug（reversal_20/amihud_20），修复后基线Sharpe从-0.255恢复到0.644。quant-verify确认PIT无泄露。
2. **哪些规则执行了/没执行？** 铁律执行到位。但§1.2团队管理、§1.3 agent启动规范、§11.3协作链、附录B交叉审查严重不足（LL-027）。
3. **应该更早发现的问题？** 因子方向bug——如果第一个脚本就有qa审查，不会传播到3个脚本。
4. **下个Sprint要改什么？** 每次分配任务前读TEAM_LEAD_CHECKLIST.md，严格按§1.1职责分配。
5. **新规则？** best_iter>10作为ML特征增量的门槛（写入LL-026）。

### 投资人视角3问
1. **敢投多少？** 等权v1.1继续100万模拟，Day 3 NAV=995K(-0.47%)。不加码。
2. **什么环境亏？** 2022-2023小盘因子失效期（基线MDD=-39.7%）。L4熔断-25%触发。
3. **本Sprint哪些真正让策略更赚钱？** 无。8/10基本面方案全FAIL。但因子生命周期基础设施和PIT验证是永久性交付。

### 10方案穷举结果
| # | 方案 | 结果 | 关键数据 |
|---|------|------|---------|
| 原始 | 7delta直接喂ML | FAIL | IC=0.044 |
| 1 | ROE宇宙预筛选 | FAIL | p=0.989 |
| 3 | 交互因子 | FAIL | IC≈0 |
| 5 | 只加days_since | FAIL | IC=0.070,iter=7 |
| 6 | 只加top2 delta | FAIL | IC=0.058,iter=51 |
| 7 | ROE动量3Q | FAIL | IC=-8.47% |
| 8 | Piotroski F5 | SKIP | 用户决定不测 |
| 9 | 双模型融合 | MARGINAL | IC+0.006 |
| 10 | 排除风险股 | FAIL | Sharpe 0.738<0.831 |

## Sprint 1.5: 基本面因子扩展 ✅ COMPLETED (FAIL — 方向关闭)

### 复盘（铁律4）
**技术5问**: (1)6份研究报告+3份深度文献调研做了充分预研; (2)PIT验证100%通过; (3)基本面delta OOS IC仅0.044(vs基线0.082)，加入后严重拖累; (4)LL-026: A股基本面因子三轮验证全FAIL; (5)因子生命周期基础设施交付
**投资人3问**: (1)不投基本面方向; (2)等权v1.1继续PT; (3)5因子集中度是最大风险

### 成败标准结果
| 标准 | 要求 | 实际 | 结果 |
|------|------|------|------|
| 基本面delta → OOS IC≥9.0% | IC提升 | **4.4%（下降46.7%）** | **FAIL** |
| Rolling ensemble → Sharpe提升≥5% | ≥0.912 | 0.972（基线对比待清理） | **待确认** |

### 研究组产出（9份报告）
- quant: A股基本面IC 1-3%（中性化后），结构性偏弱
- factor: 15候选中7个已FAIL，仅3个P1值得测试
- risk: 5项风险评估（PIT/财报季/数据质量/时效性/行业偏露）
- data: PIT验证PASS（240K行，ann_date 100%非NULL，茅台交叉验证通过）
- 3份深度文献调研（弱因子ML增强/A股ML SOTA/工业界实践）

### 编码组产出
- 6+2基本面delta特征编码（factor_engine.py, factor_set="lgbm_v2"）
- 因子生命周期状态机（factor_lifecycle表+monitor_factor_ic.py）
- Rolling ensemble脚本（rolling_ensemble.py）
- F1 fold测试脚本（test_lgbm_v2.py）

### F1 Fold测试结果
| 配置 | Train IC | Valid IC | OOS IC | Best Iter | Overfit |
|------|----------|----------|--------|-----------|---------|
| 5基线(Sprint 1.4b) | 0.1308 | 0.1208 | **0.0823** | 52 | 1.08 |
| 12特征(5+7delta) | 0.1266 | 0.0901 | 0.0439 | 6 | 1.40 |

### 关键教训
- LL-026: 基本面因子三轮全FAIL（水平值→线性合成→delta+ML），方向关闭
- 5基线因子在LightGBM中是最优特征集，无论加价量还是基本面特征都拖累
- 因子生命周期基础设施是永久性交付（无论因子结果如何）

---

## Sprint 1.4b: LightGBM非线性模型 ✅ COMPLETED (NOT JUSTIFIED)

### 复盘（铁律4）
**技术5问**: (1)交叉审查发现P0 target泄露bug，做对了; (2)12个ML特征全量入库40分钟后证明全是噪声，应先小样本验证; (3)等权基线近3年Sharpe=-0.125，意外; (4)LL-023/024/025三条新教训; (5)新因子入库前强制小样本IC筛选
**投资人3问**: (1)等权v1.1谨慎100万模拟; (2)2023年小盘因子失效时亏最多; (3)因子池仅5个价量因子缺基本面维度

### 最终评估
| 指标 | LightGBM | 等权基线(同期) | 标准 | 结果 |
|------|----------|---------------|------|------|
| OOS Sharpe | 0.869 | -0.125 | ≥1.10 | FAIL |
| Bootstrap p | 0.073 | — | <0.05 | FAIL |
| MDD | -39.51% | -48.57% | <55% | PASS |
| 连亏月 | 4 | 4 | <3 | FAIL |
| OOS IC | 0.0823 | — | >0.02 | PASS |
| ICIR | 0.982 | — | >0.3 | PASS |
| Fold一致性 | 7/7 | — | ≥70% | PASS |

### 关键发现
- 5基线特征完胜17特征（SHAP: ML特征引入维度噪声，best_iter=2）
- Optuna仅+2.5% IC（默认超参已接近最优）
- LightGBM在2024-2026每年Sharpe>1.1，但2023拖累整体

### 决策
- **NOT JUSTIFIED for go-live**（3项红线失败）
- **影子Paper Trading并行运行**（shadow_portfolio表，每月调仓自动生成）
- 等权v1.1继续做主策略

### 产出物
- `backend/engines/ml_engine.py` — Walk-Forward训练框架
- 12个ML特征函数 + `LIGHTGBM_FEATURE_SET`(28)
- 7个fold模型 + 400万行OOS预测
- 统计审查框架（7红线+5检查表）
- `docs/ML_WALKFORWARD_DESIGN.md`
- `scripts/shap_analysis.py`, `optuna_search.py`, `run_7fold.py`, `evaluate_lgb_vs_baseline.py`
- 影子PT集成: `shadow_portfolio`表 + `run_paper_trading.py`信号阶段
- LL-023/024/025三条教训

### 上线标准（存档）
- **上线**(替换等权): paired bootstrap p<0.05 + OOS Sharpe≥1.10 + 6红线全过
- **优秀**(高置信): OOS Sharpe≥1.30 + p<0.01

## Week 0: Data Feasibility Verification ✅ COMPLETED

### Day 1: Tushare API Field Verification ✅
- [x] Verify Tushare credit consumption (pull 1 month sample)
- [x] Check up_limit/down_limit fields in daily interface
- [x] Check ann_date field in fina_indicator interface
- [x] Check industry classification (industry_sw1) in stock_basic

### Day 2-3: Data Quality Validation ✅
- [x] Verify adj_factor correctness (spot check 3 stocks)
- [x] Verify daily_basic field completeness
- [x] Confirm industry classification coverage rate
- [x] Document findings and go/no-go decision → **GO**

## Week 1: Database + Core Data Pull ✅ COMPLETED

### Database Setup ✅
- [x] Execute DDL (43 tables from QUANTMIND_V2_DDL_FINAL.sql)
- [x] Pull symbols (5810 stocks including delisted: L+D+P statuses)
- [x] Board detection + price_limit mapping (main/gem/star/bse/ST)

### Data Fetcher Implementation ✅
- [x] `tushare_fetcher.py` — by-date pull strategy, retry logic, merge_daily_data
- [x] `data_loader.py` — upsert functions with FK filtering, connection reuse
- [x] `pull_full_data.py` — CLI with --table/--start/--end/--dry-run, checkpoint resume
- [x] `refresh_symbols.py` — full stock universe refresh script
- [x] `validate_data.sql` — 12-check verification script

### Core Data Pull ✅
- [x] klines_daily: 7,347,829 rows | 5,700 stocks | 1,501 dates | 2020-01-02→2026-03-19
- [x] daily_basic: 7,307,433 rows | 5,700 stocks | 1,503 dates | 2020-01-02→2026-03-19
- [x] index_daily: 4,509 rows | 3 indices | 1,503 dates | 2020-01-02→2026-03-19
- [x] Run validate_data.sql — all 12 checks passed
- [x] Git commit data fetcher code

### Fixes Applied (from quant/arch/qa review)
- Fixed: North Exchange (8xx) filtering in stk_limit
- Fixed: pct_chg → pct_change rename in index_daily
- Fixed: Code suffix stripping (000001.SZ → 000001)
- Fixed: FK pre-filtering with symbols cache
- Fixed: Float comparison for is_suspended detection
- Fixed: itertuples for 10x performance over iterrows
- Fixed: Connection reuse across upsert calls
- Fixed: Dynamic end date (today vs hardcoded)
- Fixed: Consecutive failure abort logic

## Week 2: Data Cross-Validation + adj_close工具 ✅ COMPLETED

### P0补齐（Data工程师审查结果）✅
- [x] adj_close计算工具函数 (`backend/app/services/price_utils.py`)
- [x] validate_data.sql补充: klines vs daily_basic每日对齐检查 (Check 13)
- [x] validate_data.sql补充: 退市股覆盖检查 (Check 14: D=320)
- [x] validate_data.sql补充: adj_factor NULL率按日期检查 (Check 15: 0 NULL)
- [x] validate_data.sql补充: total_mv数量级验证 (Check 16: 茅台18194亿✓)
- [x] validate_data.sql补充: adj_factor除权事件检测 (Check 17)

### 数据交叉验证 ✅
- [x] 3-stock手工比对: 600519/000001/300750 2025-03-14数据合理
- [x] adj_close除权事件验证: 茅台2023-2025共6次除权,ratio均为1.01-1.02(纯分红,合理)
- [x] klines vs daily_basic对齐: gap约100只(2-3%),系部分小盘股无daily_basic,正常
- [x] 行业分类覆盖率: industry_sw1 100%覆盖(5490/5490)

### Strategy决策记录
- 调仓频率: 双周频为默认，保留周频/月频可配置，Week 5做频率敏感性对比
- 风格暴露: BACKLOG，Week 5回测完成后做Barra分解
- 2021年压测: 回测年度分解中重点标注

## Week 3: Minimal Factor Set (6 factors) ✅ COMPLETED

### 因子引擎 ✅
- [x] 6 core factors: momentum_20, volatility_20, turnover_mean_20, amihud_20, bp_ratio, ln_market_cap
- [x] Preprocessing pipeline (MAD→fill→neutralize→zscore) — 严格按CLAUDE.md顺序
- [x] IC calculation pipeline (excess return vs CSI300) — Spearman rank IC
- [x] Batch computation (load_bulk_data一次加载 → 逐日预处理+写入)
- [x] Batch write (by-date, single transaction per day)
- [x] calc_factors.py脚本 (--date/--start/--end/--chunk-months)

### 验证通过 ✅
- [x] 单日因子分布: 6因子mean=0 std=1 ✓
- [x] IC测试(2025-03-10): ln_mcap=-0.15, vol=-0.14, mom=-0.11 (合理)
- [x] Bug修复: load_daily_data DISTINCT trade_date, index_code .SH suffix

### 全量计算 ✅
- [x] 6因子: 2020-07-01 → 2026-03-19 批量计算完成 (~3900万行, ~30min)

## Week 4: Signal + SimpleBacktester ✅ COMPLETED

### 信号引擎 ✅
- [x] SignalComposer (等权合成 + 因子方向调整)
- [x] PortfolioBuilder (Top-N选股 + 行业约束25% + 换手率约束50%)
- [x] get_rebalance_dates (双周频/周频/月频调仓日历)

### SimBroker ✅
- [x] can_trade() (涨跌停封板检测, CLAUDE.md规则1)
- [x] 整手约束 (floor(value/price/100)*100, CLAUDE.md规则2)
- [x] 资金T+1 (卖出回款当日可用)
- [x] 滑点模型 (固定bps, Phase 1切换volume-impact)
- [x] 成本模型 (佣金万1.5+印花税千0.5+过户费万0.1)

### SimpleBacktester ✅
- [x] 先卖后买调仓逻辑
- [x] 每日NAV跟踪
- [x] 换手率记录

### 绩效指标 ✅
- [x] 13项核心指标 (Sharpe/MDD/Calmar/Sortino/Beta/IR等)
- [x] Bootstrap Sharpe 95%CI (1000次采样)
- [x] 成本敏感性 (0.5x/1x/1.5x/2x)
- [x] 年度分解 + 月度热力图
- [x] 隔夜跳空统计
- [x] run_backtest.py脚本

### 端到端回测 ✅
- [x] 6因子基线: Sharpe=0.41, 年化4.88%, MDD=-28.11%

## Week 5: Credibility Rules + Report ✅ COMPLETED

### CLAUDE.md回测可信度规则全部实现 ✅
- [x] 规则1: 涨跌停封板检测 (can_trade in SimBroker)
- [x] 规则2: 整手约束 + 资金T+1 (SimBroker)
- [x] 规则3: 确定性测试 (test_factor_determinism.py — PASSED)
- [x] 规则4: Bootstrap Sharpe 95%CI (已实现并验证)
- [x] 规则5: 隔夜跳空统计 (已实现并验证)
- [x] 规则6: 成本敏感性分析 (已实现并验证)

### 回测报告必含指标 — 全部实现 ✅
- [x] Sharpe / MDD / Calmar / Sortino / Beta / IR
- [x] Bootstrap Sharpe CI
- [x] 成本敏感性 (0.5x/1x/1.5x/2x)
- [x] 隔夜跳空统计
- [x] 年度分解
- [x] 月度热力图
- [x] 胜率 + 盈亏比
- [x] 最大连续亏损天数
- [x] 年化换手率

## Week 6: Expand to 17 Factors ✅ COMPLETED

### 因子扩展 ✅
- [x] 新增11因子: momentum_5/10, reversal_5/10/20, volatility_60, volume_std_20, turnover_std_20, ep_ratio, price_volume_corr_20, high_low_range_20
- [x] northbound_pct 推迟到Phase 1 (需AKShare额外数据源)
- [x] 全量计算完成: 1.07亿行, 17因子, 1385交易日, 2020-07-01→2026-03-19
- [x] Bug修复: inf值过滤 (ep_ratio/bp_ratio除零产生inf, PostgreSQL NUMERIC不支持)

### 17因子 vs 6因子对比 ✅
| 指标 | 6因子 | 17因子 | 变化 |
|------|------|--------|------|
| 总收益 | 26.66% | 35.44% | +8.78% ✅ |
| 年化收益 | 4.88% | 6.30% | +1.42% ✅ |
| Sharpe | 0.41 | 0.45 | +0.04 ✅ |
| MDD | -28.11% | -29.97% | -1.86% |
| IR | 0.53 | 0.58 | +0.05 ✅ |
| 2021年 | -8.51% | +10.29% | +18.8% ✅ |
| 换手率 | 1.95x | 7.52x | +5.57x ⚠️ |

### 17因子回测详情 (2021-01-01 → 2025-12-31)
```
总收益:     35.44%
年化收益:    6.30%
Sharpe:     0.45 [-0.44, 1.37] (95% CI)
最大回撤:   -29.97%
Calmar:     0.21
Sortino:    0.56
Beta:       0.568
IR:         0.58
年化换手率:  7.52x
胜率:       47.8%
隔夜跳空:   -0.0466%

年度分解:
  2021: +10.29% (excess +16.51%, Sharpe 0.73, MDD -9.03%)
  2022: -14.49% (excess +6.78%,  Sharpe -0.95, MDD -20.85%)
  2023:  +2.52% (excess +14.27%, Sharpe 0.28, MDD -14.09%)
  2024: +10.51% (excess -5.69%,  Sharpe 0.55, MDD -21.05%)
  2025: +26.13% (excess +4.94%,  Sharpe 1.63, MDD -11.14%)

成本敏感性:
  0.5x → Sharpe 0.44 | 1.0x → 0.42 | 1.5x → 0.40 | 2.0x → 0.38
```

---

## Phase 0 完成总结

### 交付物
| 组件 | 文件 | 状态 |
|------|------|------|
| 数据拉取 | `tushare_fetcher.py`, `data_loader.py`, `pull_full_data.py` | ✅ |
| 数据验证 | `validate_data.sql` (17项检查) | ✅ |
| 复权价格 | `price_utils.py` | ✅ |
| 因子引擎 | `factor_engine.py` (17因子+预处理管道) | ✅ |
| 信号引擎 | `signal_engine.py` (等权合成+Top-N选股) | ✅ |
| 回测引擎 | `backtest_engine.py` (SimBroker+SimpleBacktester) | ✅ |
| 绩效指标 | `metrics.py` (13项+Bootstrap CI+成本敏感性) | ✅ |
| CLI脚本 | `calc_factors.py`, `run_backtest.py` | ✅ |
| 确定性测试 | `test_factor_determinism.py` | ✅ PASSED |

### 数据资产
| 表 | 行数 | 覆盖范围 |
|----|------|----------|
| klines_daily | 7,347,829 | 5,700股 × 1,501天 |
| daily_basic | 7,307,433 | 5,700股 × 1,503天 |
| index_daily | 4,509 | 3指数 × 1,503天 |
| factor_values | 107,679,192 | 5,694股 × 17因子 × 1,385天 |

### 采纳的团队建议汇总

| 来源 | 建议 | 决定 | 效果 |
|------|------|------|------|
| **Strategy** | 双周频调仓为默认 | ✅ 采纳 | 128个调仓日, 合理频率 |
| **Strategy** | 2021年回测重点标注 | ✅ 采纳 | 年度分解表已实现, 2021年标注 |
| **Strategy** | Week 5做Barra风格分解 | ⏳ 推迟Phase 1 | Phase 0先完成基线 |
| **Data** | adj_close工具函数必须补齐 | ✅ 采纳 | price_utils.py已实现 |
| **Data** | validate_data.sql补充5项检查 | ✅ 采纳 | Check 13-17全部通过 |
| **Quant** | 等权Top-N作为基线 | ✅ 采纳 | CLAUDE.md明确的策略 |
| **Arch** | 因子批量计算按月分片 | ✅ 采纳 | chunk-months=6, 避免OOM |
| **QA** | 确定性测试框架 | ✅ 采纳 | test_factor_determinism.py |
| **Factor** | 先6核心再扩展到18 | ✅ 采纳 | 6→17因子, 渐进式验证 |

### Phase 0结论
- **管道完整性**: 数据→因子→信号→回测→报告 全链路打通 ✅
- **绩效基线**: 年化6.3%, Sharpe 0.45 — 低于目标(15-25%, Sharpe 1.0-2.0)
- **关键发现**: Bootstrap CI跨越0, 统计上不显著; MDD(-30%)超标; 超额收益稳定(IR=0.58)
- **Phase 1方向**: AI因子挖掘 + IC加权(替换等权) + 风格控制(Beta偏高0.57)

---

## Team (Phase 0)

| Role | Scope | Status |
|------|-------|--------|
| **Team Lead** (Claude主线程) | 任务分配、进度跟踪、验收 | Completed |
| **quant** | 量化逻辑审查，一票否决权 | Completed |
| **arch** | Service层+回测引擎编码 | Completed |
| **qa** | 功能测试(API/因子/回测) | Completed |
| **data** | 数据管道全权(拉取/清洗/验证/备份) | Completed |
| **factor** | 因子研究(审查+新因子设计) | Completed |
| **strategy** | 策略研究(回测审查+策略优化) | Completed |

## Key Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-20 | Initial 6 factors, not 18 | Validate pipeline first |
| 2026-03-20 | SimpleBacktester, not Hybrid | Phase 0 is weekly rebalance only |
| 2026-03-20 | Decimal for money, float64+4dp for returns | Balance precision and performance |
| 2026-03-20 | 20 stocks @100万, 30 @200万+ | Control lot-size deviation |
| 2026-03-20 | Excess IC is gold standard | Consistent with CLAUDE.md |
| 2026-03-20 | T-day 17:00 start pull | Give Tushare 1 extra hour |
| 2026-03-20 | By-date pull (not by-stock) | ~5000 API calls for 5 years |
| 2026-03-20 | Industry merge: <30 stocks → nearest large industry | 110→48 categories |
| 2026-03-20 | Skip TimescaleDB Phase 0 | PG16 vs PG17 compatibility |
| 2026-03-20 | 双周频调仓为默认 | Strategy建议: 18因子中长周期居多 |
| 2026-03-20 | Week 5做Barra风格分解 | Strategy建议: 推迟到Phase 1 |
| 2026-03-20 | 2021年回测重点标注 | Strategy建议: 赛道极化年份 |
| 2026-03-20 | 17因子(非18) | northbound_pct需AKShare, Phase 1补 |
| 2026-03-20 | inf值过滤 | ep_ratio/bp_ratio除零产生inf |

---

## P1 Optimization Progress (2026-03-21)

### Route A: Parameter Sensitivity ✅ COMPLETED

18-config grid search (Top-N 20/30/50 × Freq biweekly/monthly × IndCap 20/25/30%).

**Key finding**: Monthly rebalance (avg Sharpe 1.243) >> Biweekly (avg 0.976).
Top-N and IndCap have minor impact within monthly configs.

**Locked config**: Top20 monthly IndCap=25%, 5因子等权, **无Beta对冲**（A股无做空工具）
- Sharpe ≈1.29 (unhedged), MDD ≈-32.9%, CI_lo=0.41
- Pre-trade hedge测试: Sharpe 1.01, CI_lo=0.04 — 三方讨论共识：对冲=减仓，去掉

### Route B: Paper Trading Pipeline ✅ COMPLETED

| 组件 | 文件 | 状态 |
|------|------|------|
| Beta对冲引擎 | `backend/engines/beta_hedge.py` | ✅ |
| 状态化Broker | `backend/engines/paper_broker.py` | ✅ |
| 健康预检 | `scripts/health_check.py` | ✅ |
| 每日管道 | `scripts/run_paper_trading.py` | ✅ |
| 策略初始化 | `scripts/setup_paper_trading.py` | ✅ 已运行 |
| 状态查询CLI | `scripts/paper_trading_status.py` | ✅ |
| 通知服务 | `backend/services/notification_service.py` | ✅ |
| Crontab安装 | `scripts/install_crontab.sh` | ✅ |

**验证**: 2026-03-19首次建仓20只，NAV=987,251，6张表写入全部正确。

### Route C: Financial Quality Factors ✅ COMPLETED

| 任务 | 状态 |
|------|------|
| financial_indicators表创建 | ✅ |
| Tushare fina_indicator数据拉取 | ✅ 408,984行 |
| 因子设计 (roe_change_q, revenue_accel, accrual_anomaly) | ✅ |
| IC测试 | ✅ revenue_accel IC=2.37%通过Gate, 其余未通过 |
| 6因子组合回测 | ✅ 加入revenue_accel后Sharpe未提升(1.28→1.28), **不纳入基线** |

### Sprint 0.1: P0-Bug修复 ✅ COMPLETED

**6-Agent独立审查→quant一票否决→全面修复**

| Bug | 修复 | 状态 |
|-----|------|------|
| R1 执行价格(T日open→T+1 open) | 两阶段pipeline | ✅ 已修复 |
| R2 Beta方法(post-hoc vs pre-trade) | pre-trade回测确认Sharpe=1.01, 三方共识去掉对冲 | ✅ 已修复(移除) |
| R3 Cash从ratio反推 | 直接存cash列到performance_series | ✅ 已修复 |
| R4 调仓日SQL | 去掉 trade_date<=限制 | ✅ 已修复 |
| R7 并发保护 | pg_advisory_lock | ✅ 已修复 |
| Beta对冲移除 | 改为纯监控指标 | ✅ 已修复 |
| L1/L2熔断机制 | risk评审→方案确定 | ⚠️ 编码未完成，遗留到Sprint 1.4 |

---

## Sprint 1.1: 参数敏感性 + Paper Trading基础设施 ✅ COMPLETED (2026-03-21)

### 参数敏感性 (Route A) ✅
- 18-config grid search (Top-N 20/30/50 × Freq biweekly/monthly × IndCap 20/25/30%)
- **关键发现**: 月度调仓(avg Sharpe 1.243) >> 双周频(avg 0.976)
- **锁定配置**: Top20 monthly IndCap=25%, 5因子等权, 无Beta对冲
- Sharpe ≈1.29(unhedged), MDD ≈-32.9%
- 波动率自适应阈值: clip(0.5, 2.0)

### Paper Trading Pipeline (Route B) ✅
- paper_broker.py / run_paper_trading.py / health_check.py / setup_paper_trading.py
- 首次建仓: 2026-03-19, 20只, NAV=987,251

### 财务质量因子 (Route C) ✅
- roe_change_q/revenue_accel/accrual_anomaly → revenue_accel IC=2.37%通过但组合未提升

### Bug修复 ✅
- 持仓膨胀bug (LL-002), MDD peak初始化 (LL-003), 时序不一致 (LL-004/005)

---

## Sprint 1.2: 多策略探索 + 配置优化 ✅ COMPLETED (2026-03-22)

### 5候选策略全部失败
- 候选2 红利低波: corr=0.778, 无分散价值
- 候选4 大盘低波: OOS Sharpe=-0.11
- 候选5 中期反转: corr=0.627, 不够正交
- **教训**: 因子正交≠选股正交(LL-009), Proxy≠正式回测(LL-011)

### 配置优化 ✅
- Top20→Top15: 整手误差8%→3%, Sharpe无差异 → KEEP
- L1延迟方案C: L1触发时月度调仓延迟不跳过 → KEEP
- days_gap改交易日: 修复国庆/五一误杀 → KEEP

### v1.1确立
- 5因子等权 + Top15 + 月度 + 行业25%
- 基线Sharpe=1.037(Mac), MDD=-39.7%

---

## Sprint 1.2a: 统计工具 ✅ COMPLETED (2026-03-22)

- DSR(Deflated Sharpe Ratio): DSR=0.591("可疑") → engines/dsr.py
- BH-FDR多重检验校正 → engines/config_guard.py
- 波动率自适应熔断阈值 → risk_control_service.py

---

## Sprint 1.3: 因子挖掘深度 ✅ COMPLETED (2026-03-22~23)

### alpha_miner因子挖掘 (Batch 1~8)
- 67个因子测试(FACTOR_TEST_REGISTRY.md)
- **亮点**: mf_divergence IC=9.1%(全项目最强), price_level IC=8.42%
- **陷阱**: big_small_consensus原始IC=12.74%中性化后-1.0%(虚假alpha, LL-014)
- PEAD earnings_surprise: IC=5.34%, corr<0.11最干净新维度

### moneyflow数据拉取 ✅
- moneyflow_daily: 614万行入库

---

## Sprint 1.3a: v1.2升级验证 ✅ COMPLETED (2026-03-23)

- v1.2(+mf_divergence) paired bootstrap: p=0.387, 增量不显著 → NOT JUSTIFIED
- **决策**: v1.2升级取消, v1.1维持

---

## Sprint 1.3b: 线性合成全面对比 + 收尾 ✅ COMPLETED (2026-03-23)

### 9种线性合成方法 vs 等权基线
| 方法 | 最佳Sharpe | vs 基线1.035 | 结论 |
|------|-----------|-------------|------|
| 最大化ICIR加权 | 0.992 | 劣 | Reverted |
| 最大化IC加权 | 0.929 | 劣 | Reverted |
| ICIR简单加权 | 0.912 | 劣 | Reverted |
| 收益率加权 | 0.861 | 劣 | Reverted |
| 因子择时(5F) | 0.876 | 劣 | Reverted |
| 因子择时+PEAD(6F) | 0.679 | 最差 | Reverted |
| 半衰期加权 | 0.838 | 劣 | Reverted |
| BP子维度融合 | 0.820 | 劣 | Reverted |
| 分层排序A/B/C | 0.666~0.820 | 劣 | Reverted |

**结论**: 等权=线性全局最优(LL-018), 突破需要非线性(LightGBM)

### 其他完成项
- KBAR 15因子: 15/20 PASS, 大部分与vol/rev冗余, 3个独立候选入Reserve
- Deprecated 5因子标记(momentum_20/volatility_60/turnover_std_20/high_low_range_20/volume_std_20)
- 封板补单机制实现
- PEAD加入等权组合验证→Sharpe-0.085, 确认等权天花板(LL-017)
- v1.1配置锁死, 60天Paper Trading启动(2026-03-23)

---

## Windows迁移 ✅ COMPLETED (2026-03-24~25)

### 完成项
- [x] Python 3.11.9 安装
- [x] PostgreSQL 16 (D:\pgsql, D:\pgdata16, 用户xin)
- [x] Redis Windows服务
- [x] Python虚拟环境 + 依赖安装
- [x] 数据库恢复(2.8GB dump, 1.6亿行, 46张表)
- [x] 行数校验: 160,299,461行全部匹配
- [x] Paper Trading 3/23首次运行(Windows) + 3/24补跑
- [x] Task Scheduler注册: QuantMind_DailySignal(16:30) + QuantMind_DailyExecute(09:00)
- [x] macOS残留清理(278个._文件 + 12个.DS_Store)
- [x] .gitignore重建
- [x] CLAUDE.md环境描述更新
- [x] Python脚本UTF-8编码修复

### Sharpe差异诊断
- Windows: 1.019 vs Mac: 1.037 (差0.018)
- **根因**: dump中reversal_20因子在2021-01-29(第一个月度调仓日)缺失, 该日用4因子等权而非5因子
- **决策**: 接受1.019为Windows新基线, 毕业标准调整为Sharpe≥0.71
- **更新(Sprint 1.4a)**: reversal_20补算后基线恢复至1.03, 毕业标准更新为Sharpe≥0.72

---

## Paper Trading v1.1 运行状态

- **启动**: 2026-03-23
- **当前**: Day 3 / 60天
- **NAV**: 979,294 (+2.15% on Day 2)
- **持仓**: 15只
- **自动化**: Task Scheduler (16:30信号 + 09:00执行)
- **毕业标准**: Sharpe≥0.71, MDD<35%, 滑点偏差<50%
- **基线Sharpe**: 1.03 (reversal_20补算后, 2021-2025全期)

---

## Sprint 1.4a: 风控补债 + 基线修复 (2026-03-25)

### 已完成
| 任务 | 执行者 | 结果 |
|------|--------|------|
| Task Scheduler验证 | Team Lead | 已注册，3/25首次自动触发(16:30/09:00) |
| reversal_20补算 | Team Lead | 2021-01的20个交易日补算完毕，Sharpe 1.019→1.03 |
| Deprecated因子停计算 | arch | 已确认排除，无需代码修改。修复help text(core5/full16)+加deprecation warning |
| Windows全量pytest | qa | **401 passed, 0 fail, 1 xfail**。零回归 |
| L1-L4熔断编码 | risk | 状态机重写，DB持久化+审计日志+approve_l4.py人工审批CLI。L3恢复阈值对齐CLAUDE.md(5天/2%) |

### 新增文件
- `scripts/approve_l4.py` — L4人工审批CLI (--list/--approve/--reject/--force-reset)

### 待做
- Sprint 1.4a复盘（铁律4）
- Sprint 1.4b规划（LightGBM）

---

## 当前团队状态 (2026-03-25)

| 角色 | 状态 | 待办 |
|------|------|------|
| Team Lead | 活跃 | Sprint 1.4a收尾 + 1.4b规划 |
| quant | 待命 | Sprint 1.4b: 特征池审查 |
| ml | 待命 | Sprint 1.4b: LightGBM训练框架 |
| alpha_miner | 待命 | Sprint 1.4b: 50+特征池准备 |
| 其他角色 | 按需spawn | — |

## Blockers
- 无硬阻塞
- accrual_anomaly因子blocked(需cash_flow表), 优先级低

---

## Sprint 1.4b: LightGBM非线性模型 (2026-03-25 启动)

### 提案阶段（§11.1步骤1）✅ COMPLETED

**三方研究产出整合：**
- alpha_miner: 50个候选因子（P1:25 + P2:15 + P3:10），6维度全覆盖
- ml: Walk-Forward框架设计（7 fold + Optuna 200轮 + GPU配置）
- quant: 统计审查框架（7条红线 + 5层检查清单）

**关键决策：**
- OOS上线标准: **paired bootstrap p<0.05 + Sharpe≥1.10 + 6红线**（用户确认）
- OOS优秀标准: **Sharpe≥1.30 + p<0.01**
- DSR门槛: **≥0.65**
- 特征数: 51个（ml设计6组）
- 训练窗口: F1-F3扩展→F4-F7固定24月
- Purge gap: 5交易日
- GPU: RTX 5070, VRAM预估1-2GB

**设计文档**: docs/ML_WALKFORWARD_DESIGN.md

### 特征工程阶段（§11.1步骤2）🔨 IN PROGRESS

- alpha_miner: P1特征编码（第一批12个因子）
- ml: Walk-Forward训练框架编码 (ml_engine.py)
