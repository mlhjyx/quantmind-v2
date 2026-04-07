# Phase 0 Progress Tracker

> Last updated: 2026-04-07 (Phase 1加固完成+5层验证+QMT切换)
> Current: Phase 1, Sprint 1.35 完成 → PT v1.2 QMT live Day 5/60
> 本会话(4/7 PM): Phase 1加固6项修复→Sharpe 1.24→0.94 + 5层严谨性验证 + 归档破损修复 + PT全面切QMT数据
> 本会话(4/7 AM): 因子候选研究(vwap_bias_1d FAIL) + 回测引擎全面审计(17项问题) + 战略决策(加固自建+Qlib ML层)
> 前会话(4/5 PM): 性能优化8项 + 北向MODIFIER/RANKING研究 + ARIS安装 + 研究知识库19条目 + ECC配置
> Sprint 1.8a ✅ | Sprint 1.8b ✅ | Sprint 1.9 ✅ | Sprint 1.10 ✅ | Sprint 1.11 ✅ | Sprint 1.12 ✅ | Sprint 1.13 ✅ | Sprint 1.14 ✅ | Sprint 1.15 ✅ | Sprint 1.16 ✅ | Sprint 1.17 ✅ | Sprint 1.18 ✅ | Sprint 1.19 ✅ | Sprint 1.20 ✅ | Sprint 1.21 ✅ | Sprint 1.22 ✅ | Sprint 1.25 ✅ | Sprint 1.26 ✅ | Sprint 1.27 ✅ | Sprint 1.28 ✅ | Sprint 1.29 ✅ | Sprint 1.30 ✅ | Sprint 1.30B ✅ | Sprint 1.32 ✅ | Sprint 1.33 ✅ | Sprint 1.34 ✅ | Sprint 1.35 ✅
> Paper Trading: v1.2 QMT live Day 2/60 (Day 0=2026-04-02), NAV=¥989,391, 基线Sharpe=0.91(5年volume_impact), 毕业阈值≥0.315
> G2研究结论: 权重/仓位优化无效(15组), PMS阶梯利润保护有效(Sharpe+0.06~0.24), Top-20>Top-15, 行业约束损害alpha
> 新基线(Phase 1加固后): Sharpe=0.94, 年化22.57%, MDD=-40.77%, Calmar=0.55 (旧1.24虚高, 缺印花税历史税率+overnight_gap)
> FF3归因: Alpha=21.1%/年(t=2.45)✅, SMB beta=0.83⚠️, 保守Sharpe=0.70-0.85
> 数据审计: 0❌9⚠️, 数据地基稳固, 新增margin_data(95K行)+index_components(11K行)+3个P0因子(ATR/IVOL/gap, 冗余)
> 下一步: PMS v1.0实时架构(清明) → PT v1.3切换(Top-20+去行业约束+PMS) → G1 LightGBM
> Blockers: PMS same_close需要盘中实时监控架构
> 宪法: V3.3 生效 (8铁律+14项补充+§15 Harness工程+§16落地保障)
> 研究进度: R1✅ R2✅ R3✅ R4✅ R5✅ R6✅ R7✅ — 7维度研究全部完成
> **AI闭环战略(2026-03-28)**: 三步走 — Step1 PT赚钱(1.13-1.15) → Step2 GP最小闭环(1.16-1.17) → Step3完整AI闭环(1.18+)
> **关键决策**: GP-first不上LLM | RD-Agent借鉴不集成 | Warm Start GP(arxiv 2412.00896) | Qlib Alpha158做DSL参考

## 回测引擎加固 (2026-04-07)

### 审计触发
- `backtest_vwap_bias_weekly.py`因SQL遗漏`pre_close`字段导致0成交bug，SimBroker静默返回False无报错
- 三路并行审计: 代码审计(architect) + Qlib源码研究 + RQAlpha/QUANTAXIS/vectorbt研究

### 战略决策: 加固自建引擎 + 选择性集成Qlib
- **不迁移到Qlib原因**: Qlib的A股规则(T+1/涨跌停/整手)实际不如我们完善，迁移ROI低
- **Qlib集成方式**: StaticDataLoader喂数据→Qlib ML模型出分数→我们引擎回测
- **详细计划**: `docs/BACKTEST_ENGINE_HARDENING_PLAN.md`

### 审计发现17项问题(P1-P17)
- 🔴准确性(8): 缺分红除权/缺送股拆股/缺历史印花税率/缺最低佣金5元/overnight_gap死代码/pre_close静默失败/Fill.slippage(验证非bug)/Phase A无z-score clip
- 🟡分析(6): 无内置metrics/无benchmark相对指标/无DSR/无子期间分析/换手率不完整/无退市处理
- 🟠架构(3): iterrows性能瓶颈/magic number单位转换/can_trade不可追溯

### Phase 1 ✅ 完成 (2026-04-07)
- **代码修复**: P3印花税历史税率 + P5 overnight_gap三因素 + P8 z-score clip + P6 DataFeed校验 + P1/P2分红框架
- **新基线**: Sharpe=0.94, 年化22.57%, MDD=-40.77% (旧1.24虚高0.30, 96%来自P5)
- **隔离验证**: P3=-0.011, P5=-0.374, 交互=0.000, 加法性成立
- **5层严谨性验证**: L1解析解5/5 + L2不变性7/7 + L3随机信号mean=-0.336 + L5交叉验证<0.05%
- **归档破损修复**: 6个脚本恢复, 131个文件全量审计无其他破损
- **PT切QMT**: NAV/持仓/绩效全面切到QMT实际数据, PaperBroker降级对比工具

### Phase 2 ✅ 完成 (2026-04-08)
- **BacktestResult.metrics()**: 一行调用生成完整报告(20+指标)
- **DSR**: deflated_sharpe_ratio(M=69)=0.375 ⚠️ Sharpe=0.94在69次测试中不显著
- **新指标**: tracking_error=22.72%, excess_mdd=-35.70%, max_dd_duration=803天
- **子期间**: Bull Sharpe=2.93 / Bear=0.85, 年度+牛熊自动拆分
- **P13换手率**: 每日记录(含PMS/补单), 年化9.25(之前7.46)

### Phase 3 ✅ 完成 (2026-04-08)
- **P17**: 单位转换集中到DataFeed.standardize_units(), 移除SimBroker 3处magic number
- **P14**: 退市检测+自动清算(连续20日无数据→按最后价格清算)
- **ValidatorChain**: 可组合验证器(Suspension/DataCompleteness/PriceLimit), 拒绝原因可追溯
- **P15+P16**: iterrows→MultiIndex + pivot daily_close(上session完成)

### Phase 4 ✅ 完成 (2026-04-08)
- **4.1 run_composite_backtest()**: Phase A核心信号 + Modifier链调节 → Phase B执行
- **4.3 BaseExecutor + SimpleExecutor**: 统一执行接口, NestedExecutor预留
- **4.4 QuantMindQlibAdapter**: factor_values → StaticDataLoader, 不需qlib.init()
- **4.2 H0校准**: ⏳ 待QMT实际成交数据入库(当前trade_log仅SimBroker数据)

### 回测引擎加固总结
- **17项审计问题**: Phase 1-3全部完成(P1-P17), Phase 4核心3项完成
- **Sharpe基线**: 1.24 → 0.94(真实值, 5层验证), DSR=0.375(M=69)
- **新增能力**: metrics()/DSR/子期间/ValidatorChain/退市/MultiIndex/Composite回测/Qlib适配

### 因子研究 + 北向MODIFIER (2026-04-08)
- **因子独立性筛选**: 43候选→17个独立因子通过(与Active |corr|<0.7)
  - Top: price_volume_corr_20(ICIR=1.02), large_order_ratio(0.87), a158_corr5(0.91)
- **NorthboundModifier**: 8个V2行为因子→综合z-score→3级缩放(恐慌50%/消极70%/中性100%)
  - 8/60月触发(2022/2023熊市+2024恐慌), 从hold_vol差分计算净买入
- **Composite回测**: Sharpe 0.840→0.890(+0.05), MDD -52%→-50%(+2pp), Sortino 1.11→1.20

### 待执行
- H0成本模型校准(待QMT实盘数据)
- 独立因子paired bootstrap回测(17个候选 vs 基线)
- 盈利公告因子H1季报扩展 + 分钟聚合因子

### 因子候选研究 (2026-04-07)
- 5个PASS因子paired bootstrap: 仅vwap_bias_1d边际(p=0.046), 其余4个不显著
- vwap_bias_1d独立回测: weekly Sharpe=-1.26, monthly=-0.44 → **单因子FAIL**
- 结论: vwap_bias_1d保留在LGBM特征池(63因子之一), 不入Active池

---

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

### Sprint 1.32: 行业中性化 + GP全链路验证 + Onboarding测试 + 重构 (2026-03-29) ✅

**铁律2合规(行业中性化) + GP端到端验证通过 + 62新测试 + 私有函数重构。**

- ✅ neutralizer.py: 行业+截面双重中性化共享模块(Winsorize+行业内zscore+截面zscore)
- ✅ factor_onboarding.py: 调用Neutralizer替代截面zscore近似（铁律2合规）
- ✅ GP全链路验证: 手动触发成功(240 individuals, 5 generations, 43.9s, pipeline_runs完整)
- ✅ pipeline_utils.py: 5个GP管道公开函数（从scripts私有函数提取，消除QA F2）
- ✅ mining_tasks.py: import路径改pipeline_utils + DB URL修复(quantmind→xin)
- ✅ test_factor_onboarding.py: 5个测试用例, 62 passed
- ⚠️ GP产出0因子（5代×20 population太小+缺pb/circ_mv等字段），需加大参数+补充market data

---

### G2研究: 回撤控制 + 因子扩展 + 数据审计 + 风格归因 (2026-04-02~04-03, 4个session) ✅

**25+组回测实验 + 全面数据审计 + FF3归因 + 因子池盘点 + PMS集成。**

#### 关键结论
- ⚠️ 权重/仓位优化全部无效: risk_parity/min_variance/vol_regime/动态仓位(15组), Sharpe不变
- ✅ PMS阶梯利润保护有效: T+1执行Sharpe+0.06, 当日close执行Sharpe+0.24, MDD改善3-8pct
- ✅ Top-20 > Top-15: Sharpe+0.08, MDD-4.6pct (分散化甜蜜点)
- ⚠️ 行业约束(ind_cap=0.25)损害alpha: 去掉后Sharpe+0.09 (因子选股的行业分布本身合理)
- ❌ 止损砍alpha: 被止损股票卖后1月+7.8%反弹, 66%概率反弹
- ❌ Target Vol无效: 跟动态仓位一样降仓=砍alpha
- ✅ FF3归因: Alpha=21.1%/年(t=2.45), SMB beta=0.83, R²=49%
- ✅ 分市值: Alpha在小盘最强(0.95), 大盘无效(0.36)
- ✅ 数据地基: 0❌9⚠️, 复权/PIT/调仓/成本全✅

#### 新最优配置 X-D
- **Top-20 + 无行业约束 + PMS阶梯利润保护(same_close)**
- Sharpe=1.15, MDD=-35.1%, CAGR=29.3%, Calmar=0.83
- vs基线(Top-15/ind0.25/无PMS): Sharpe+26%, MDD+7.9pct, Calmar+54%

#### 代码改动
- ✅ `backtest_engine.py`: 新增PMSConfig + 日频利润保护检查 + T+1/same_close执行模式
- ✅ `signal_engine.py`: 新增risk_parity/min_variance权重方法 + _calc_risk_parity_weights()
- ✅ `run_backtest.py`: 新增--pms/--weight-method/--vol-regime/--vol-factor参数
- ✅ 3个P0因子(atr_norm_20/gap_frequency_20/ivol_20)计算并写入factor_values (~1650万行)
- ✅ margin_data拉取: 95,398行, 3,961股票, 2021-01~2026-03
- ✅ index_components拉取: 11,100行, CSI300历史成分
- ✅ Baostock安装验证: 5m历史数据2021年起可用

#### 研究脚本
- `scripts/research_g2_risk_parity.py` — G2权重优化7组实验
- `scripts/research_g25_dynamic_position.py` — 动态仓位4组实验
- `scripts/research_pms_stoploss.py` — PMS止损7组实验
- `scripts/research_ml_factor_ic.py` — 32因子批量IC测试
- `scripts/research_market_cap_layers.py` — 分市值层5组回测
- `scripts/research_mdd_layers.py` — MDD三层叠加25组实验
- `scripts/research_mdd_supplement.py` — 补充X-A~X-E叠加实验
- `scripts/research_ff3_attribution.py` — FF3风格归因
- `scripts/research_p0_factors_fast.py` — P0因子快速计算

#### 审计报告
- `COMPREHENSIVE_AUDIT_REPORT.md` — 全面审计(5部分)
- `FACTOR_ASSET_INVENTORY.md` — 37因子资产清单
- `DATA_QUALITY_AUDIT.md` — 数据质量巡检

#### PG OOM修复 (2026-04-03)
- ⚠️ 3个并行Python进程(各3.5GB)+PG(2.5GB)超过32GB → PG OOM崩溃
- ✅ postgresql.conf: logging_collector=on, work_mem 64→32MB
- ✅ CLAUDE.md: 新增并发限制规则(最多2个重数据进程)

---

### 性能优化 + 北向因子 + ARIS + 知识库 (2026-04-05 PM) ✅

**8项性能优化 + 北向30因子研究 + 研究基础设施建设。**

#### 性能优化
- ✅ TimescaleDB 2.26.0: 手动DLL复制安装成功(之前"不兼容"记忆纠正)
- ✅ factor_values hypertable: 352M行→71月chunks/53GB
- ✅ klines_daily hypertable: 7.4M行→27季chunks/1.3GB
- ✅ Parquet缓存: `_load_shared_data` **30min→1.6s** (1000x加速)
- ✅ `fast_neutralize_batch()`: 批量IO替代逐天读写, 测试通过
- ✅ 行业L1映射: 5490/5810只(94.5%), `sw_industry_mapping`表110行
- 🔨 分钟数据: 4分片后台拉取(1867/5194, 35.9%)

#### 北向因子研究
- ✅ MODIFIER V1(4因子): 信号方向反向(corr=-0.093), 不推荐择时
- ✅ MODIFIER V2(15因子): 8个OOS通过, nb_size_shift_20d corr=-0.304
- ✅ RANKING(15因子): 3个Active — nb_increase_ratio_20d(t=-2.82), nb_new_entry(t=-2.43), nb_contrarian(t=-2.11)
- ✅ 关键发现: 北向反向指标(外资增持→跑输), 与5核心因子corr<0.17(独立新维度)
- ✅ 3因子中性化+画像: nb_increase_ratio_20d→模板11, nb_new_entry→模板1

#### 研究基础设施
- ✅ ARIS 8个研究skills安装(arxiv/idea-discovery/research-pipeline等)
- ✅ 6个QuantMind自定义skills(factor-research/db-safety/performance/discovery/overnight/research-kb)
- ✅ 研究知识库: 19条目(8 failed + 6 findings + 5 decisions)
- ✅ ECC深度配置: Continuous Learning hooks + quantmind-overrides规则
- ✅ `/check-ic`命令创建
- ✅ GitHub push: mlhjyx/quantmind-v2 (private)

---

### GA1-A: Factor Profiler V2 — 7项推荐逻辑修正 (2026-04-05) ✅

**因子画像系统全面升级：regime修正+120d IC+单调性+成本可行性+冗余标记+FMP聚类+多模板评分。**

#### 7项修正
1. ✅ **Regime切换修正**: `regime_sensitivity>0.03` 改为 `sign(ic_bull)≠sign(ic_bear)` 方向反转判定 → 模板12从33个降至5个
2. ✅ **120d IC + 天花板检测**: 新增120d horizon，60d IC仍在上升的因子标记"ceiling_not_reached"
3. ✅ **单调性影响选股方式**: mono≥0.6推荐Top-N, 0.3-0.6建议缩小N, <0.3不适合ranking
4. ✅ **成本可行性检查**: `annual_cost = turnover×rebalances×2×0.1%`, cost>alpha×0.5标记不可行 → 11个因子标记cost_infeasible
5. ✅ **冗余标记**: |corr|>0.85标记redundant, |corr|<-0.85标记mirror_pair → 11对冗余关系
6. ✅ **FMP独立组合候选**: Union-Find聚类(|corr|>0.7), 聚类代表间|corr|<0.3才是FMP候选 → 32聚类, 2个FMP候选
7. ✅ **多模板Top-2评分**: 模板1/2/11/12加权打分, 推荐主/备两个模板

#### 模板分布(修正后)
- 模板1(月度RANKING): 33个 | 模板2(周度): 4个 | 模板11(Modifier): 6个 | 模板12(Regime): 5个

#### 代码改动
- ✅ `backend/engines/factor_profiler.py`: ~900行重写, HORIZONS新增120d, 15个新字段, 报告12章节
- ✅ `factor_profile`表: ALTER TABLE新增15列, 48行全量更新
- ✅ `docs/FACTOR_PROFILE_REPORT.md`: V2报告12章节(23K字符)

#### CLAUDE.md更新
- ✅ 新增"因子画像评估协议"5条规则(regime方向反转/成本一票否决/冗余不可绕过/FMP聚类验证)

#### 数据拉取(并行)
- 🔨 5分钟K线(Baostock): 5194只全量A股, 2021-2025, 进行中

---

### Sprint 1.35: 实时数据层 + 前端重构 + 后端审计 + 运维自动化 (2026-04-02 PM) ✅

**实时数据服务 + 交易执行API + 前端组件拆分 + 3份审计报告 + 冒烟测试自动化。**

#### 后端新建
- ✅ `api/execution_ops.py`: QMT交易操作17个API端点(drift/cancel/fix-drift/trigger-rebalance/emergency等)
- ✅ `api/realtime.py`: 实时数据API(portfolio/market), sync def防止event loop阻塞
- ✅ `services/realtime_data_service.py`: QMT持仓+xtdata行情+信号目标聚合, 5s/10s TTL缓存
- ✅ `scripts/smoke_test.py`: 62端点自动发现冒烟测试, DingTalk P0告警, --auto-restart NSSM
- ✅ `scripts/pull_moneyflow.py`: Moneyflow拉取+5次×2min重试+P0告警

#### 后端修改
- ✅ `qmt_connection_manager.py`: QMT_ALWAYS_CONNECT机制+xtquant路径自动添加
- ✅ `daily_reconciliation.py`: live持仓快照(position_snapshot)+live NAV(performance_series), 使用QMT total_asset
- ✅ `execution_ops.py`: drift修复(signal_mode=paper, position_mode=live, QMT代码strip后缀, 8s trades超时)
- ✅ `config.py`: 新增QMT_ALWAYS_CONNECT配置项
- ✅ `.env`: QMT_ALWAYS_CONNECT=true
- ✅ Task Scheduler: moneyflow→17:00, signal→17:15, 新增QM-SmokeTest每小时

#### 前端
- ✅ Dashboard拆分: 923行→10个组件文件(KPIGrid/EquityCurve/AlertsPanel等)
- ✅ Execution拆分: 885行→3个文件(index/modals/ActionBtn)
- ✅ usePortfolio/useMarketOverview hooks + queryKeys统一
- ✅ Error Toast全局拦截(client.ts interceptor: 403/422/429/503/500+/网络断开)
- ✅ execution_mode=live统一(Dashboard/Portfolio/PT/Risk全部切换)
- ✅ QMTStatusBadge中文化("QMT 实盘"/"模拟盘")
- ✅ EquityCurve Y轴格式修复(989K而非989391.00)
- ✅ Sharpe/MDD数据不足时显示"—"+"数据积累中"
- ⚠️ 前端暂停进一步修复 — 等后端API契约统一后重建

#### 审计报告(3份)
- ✅ `FRONTEND_BACKEND_INTEGRATION_AUDIT.md`: 19维度32问题
- ✅ `BACKEND_FULL_AUDIT.md`: 16维度52问题(5 CRITICAL/12 HIGH)
- ✅ `BACKEND_FUNCTIONALITY_AUDIT.md`: 86项功能73%完成(核心交易链路97%)

#### CLAUDE.md更新
- ✅ xtquant/miniQMT路径规则(必须append不insert)
- ✅ 部署规则(NSSM restart/dev模式/端口冲突)

---

### Sprint 1.34: QMT Live切换 + 8层安全架构 + 前端修复 + 因子审计 (2026-04-02 AM) ✅

**SimBroker→QMT live全面切换 + 执行层8层安全 + 前端深度修复 + 因子全量重算。**

- ✅ QMT live切换: SimBroker禁用, 09:31执行, xtdata实时行情, 3轮重试
- ✅ 执行层8层安全: OrderTracker + 撤单确认 + 资金预扣 + 状态码映射 + 残留清理 + 硬限制 + audit_log
- ✅ 前端修复: 因子评估6项指标 + 回测字段映射 + 4个API 500修复 + 侧边栏
- ✅ 因子全量重算: 122M行/19.5min + 冗余清理(FULL 16→14) + ML clip修复
- ✅ 基线回测: Sharpe=0.45(5年), 毕业阈值=0.315
- ✅ 数据拉取修复: hardcoded日期→dynamic + Task Scheduler 13任务
- ✅ TradingDayChecker: 4层fallback + 自动UPSERT
- ✅ 盘中监控+收盘对账: intraday_monitor + daily_reconciliation
- ✅ QMT持仓偏差: 9/15只, drift fix待4/3-4/7自动修复

### Sprint 1.33: PT v1.2迁移 + structlog + 参数补全 (2026-04-01) ✅

- ✅ v1.2 config_guard + mergesort + 因子重算2024-2026
- ✅ structlog迁移76文件 + 参数106→220 + doc_drift_check

---

### Sprint 1.31: GP闭环生产化 + 审批→入库流程 (2026-03-29) ✅

**GP引擎从"可用"升级到"全链路可运行"。1814 tests passed, 0 regressions。**

- ✅ risk.py VaR小样本修复（data_sufficient标志 + data_days字段）
- ✅ backtest.py Decimal序列化修复（float()转换4个数值字段）
- ✅ GP周期调度（beat_schedule.py 每周日22:00自动触发，population=100/generations=50）
- ✅ mining_tasks.py 状态同步（pipeline_runs完整记录 running→completed/failed）
- ✅ 审批API（pipeline.py approve/reject端点 + celery入库触发）
- ✅ factor_onboarding.py 6步入库服务（registry+values+IC+gate，幂等upsert）
- ✅ onboarding_tasks.py Celery封装（max_retries=2, soft_time_limit=600s）
- ✅ PipelineConsole审批按钮（Approve/Reject + pipeline.ts API）

---

### Sprint 1.30B: 全系统健康修复 + 因子IC计算 (2026-03-29) ✅

**25+文件修改，6大类底层问题修复。全22页面可用，因子IC有真实数据。**

- ✅ Celery health check修复（-A app.tasks → app.tasks.celery_app）
- ✅ 因子IC批量计算脚本（5因子×538天=2632行，bp_ratio t=20.8, turnover_mean_20 t=-24.2）
- ✅ UUID cast修复（17处 :sid::uuid → CAST(:sid AS uuid)，Portfolio返回15持仓）
- ✅ 3个crash页面修复（Pipeline FlowChart/MiningTaskCenter/BacktestHistory）
- ✅ 5个因子评估Tab null-safe（TabAnnual/Correlation/GroupReturns/ICDecay/RegimeStats）
- ✅ API响应适配（factors.ts/mining.ts/backtest.ts/strategies.ts 响应格式转换）

---

### Sprint 1.30: 硬编码值替换 — Portfolio/Dashboard (2026-03-29) ✅

**Portfolio 3个硬编码值→真实API计算。DashboardOverview StrategiesPanel接入真实API。**

- ✅ Portfolio 总持仓市值 — `holdings.market_value` 求和(替换¥1,285,430)
- ✅ Portfolio 现金 — `latestNav - totalMarketValue`(替换¥192,085)
- ✅ Portfolio 仓位% — `totalMarketValue / latestNav`(替换85.1%)
- ✅ Portfolio DailyPnl接口字段名修复 — `date→trade_date`, `pnl→daily_return`(今日盈亏之前始终为0)
- ✅ DashboardOverview StrategiesPanel — `useQuery({queryFn: fetchDashboardStrategies})`替换3条静态JSX
- ✅ `dashboard.ts` 新增 `fetchDashboardStrategies()` + `StrategyOverview` 类型
- ✅ PageErrorBoundary — class组件包裹<Outlet>，22页面crash→恢复UI(不再白屏)
- ✅ DashboardOverview系统状态面板 — PG/Redis/Celery/数据新鲜度接入/system/health(30s轮询)
- ✅ 合并至main

**结果**: 0 new TS errors。前端无已知硬编码金融数据。全部crash受ErrorBoundary保护。

---

### Sprint 1.29: 剩余页面mock清除+null-safe防御 (2026-03-29) ✅

**5页面mock清除 + null-safe修复 + 内联硬编码修复。0 new TS errors。**

**Phase 1: 页面mock清除 (5页面)**:
- ✅ MarketData — 删除MOCK_INDICES/SECTORS/GAINERS/LOSERS(4常量), useQuery默认[], loading/error/empty状态
- ✅ ReportCenter — 删除MOCK_REPORTS/QUICK_STATS(2常量), 添加loading/error/empty状态
- ✅ RiskManagement — 删除5个MOCK_*常量, useState(null)+useEffect真API, 全组件?.防御
- ✅ FactorEvaluation — 删除MOCK_FACTOR_REPORTS/LIBRARY导入, 去掉placeholderData
- ✅ DashboardOverview — KPI网格内联硬编码(18.4%/62.3%/VaR 2.8%等)替换为"—"

**Phase 2: null-safe防御 (Sprint 1.28期间发现)**:
- ✅ FactorTable fmtNum — `v === undefined` → `v == null` (API返回null)
- ✅ SystemSettings HealthTab — health.postgres/redis/celery/disk/memory/data_freshness全部?.防御
- ✅ SystemSettings SchedulerTab — Array.isArray防御, 去掉MOCK_*fallback
- ✅ HealthPanel — icTrends Array.isArray防御
- ✅ CorrelationHeatmap — data.factors/matrix ?.防御

**结果**: 0 MOCK_*常量在任何页面文件中。11/22页面完全接入真数据。

**复盘（技术5问）**:
1. 什么做对了？→ API路径修复和mock清除是低风险高收益的工作，backend无需改动
2. 什么该改进？→ Agent spawn应指定worktree路径，2个agent编辑了main repo而非worktree
3. 学到什么？→ 前端组件对null/undefined防御严重不足，API返回null时大面积崩溃
4. 技术债？→ api/mock.ts + api/mockFactors.ts定义文件仍存在(无引用), /pipeline/status 500, Portfolio summary端点缺失
5. 下次怎么做？→ 新建组件时强制?.防御模式，API层加统一的null→default转换

---

### Sprint 1.31: GP闭环生产化 + 审批→入库流程 (2026-03-29) 🔨

**目标**: GP引擎从"可用"到"可运行"。QA P1修复 + 调度集成 + 审批→入库全链路。

- ✅ risk.py VaR小样本修复（data_sufficient标志）
- ✅ backtest.py Decimal序列化修复
- 🔨 GP周期调度（beat_schedule.py 每周日22:00自动触发）
- 🔨 审批API（approve/reject端点 + factor_onboarding入库服务）
- 🔨 前端审批界面（PipelineConsole待审批Tab Approve/Reject按钮）

---

### Sprint 1.30B: 全系统健康修复 + 因子IC计算 (2026-03-29) ✅

**25+文件修改，6大类底层问题修复。全22页面可用，因子IC有真实数据。**

- ✅ Celery health check修复（-A app.tasks → app.tasks.celery_app）
- ✅ 因子IC批量计算脚本（5因子×538天=2632行，bp_ratio t=20.8, turnover_mean_20 t=-24.2）
- ✅ UUID cast修复（17处 :sid::uuid → CAST(:sid AS uuid)，Portfolio返回15持仓）
- ✅ 3个crash页面修复（Pipeline FlowChart/MiningTaskCenter/BacktestHistory）
- ✅ 5个因子评估Tab null-safe（TabAnnual/Correlation/GroupReturns/ICDecay/RegimeStats）
- ✅ API响应适配（factors.ts/mining.ts/backtest.ts/strategies.ts 响应格式转换）
- ✅ QA交叉审查通过（2个P0已修，P1本Sprint修）

**复盘5问**:
1. 完成了什么？→ 全系统从"页面能看"升级到"数据真实+底层可用"
2. 什么做得好？→ 系统性测试22页面找出所有问题，因子IC一次性跑通
3. 学到什么？→ SQLAlchemy text()的::uuid语法陷阱；前后端API响应格式必须在适配层转换
4. 技术债？→ 前端API层大量any类型；Settings数据源端点未实现；AgentConfig 404
5. 下次怎么做？→ 新端点开发时同步写API适配层+null guard，不等集成时再补

---

### Sprint 1.28: 前端6核心页面真数据接入 (2026-03-29) ✅

**Phase 1-4全部完成。1814 backend tests passed (+37 vs Sprint 1.27)。0 new TS errors。**

**Phase 1: API路径对齐 (3文件)**:
- ✅ `frontend/src/api/factors.ts` — `/factor/library`→`/factors`, `/factor/library/stats`→`/factors/stats`, `/factor/library/correlation`→`/factors/correlation`, `/factor/library/ic-trends`→`/factors/health`, `/factor/{id}/report`→`/factors/{name}/report`
- ✅ `frontend/src/api/mining.ts` — `/factor/mine/gp|llm|brute`→`/mining/run`+engine参数, `/factor/tasks`→`/mining/tasks`, `/factor/evaluate/batch`→`/mining/evaluate`
- ✅ `frontend/src/api/strategies.ts` — `/strategy`→`/strategies`, `/strategy/{id}`→`/strategies/{id}`

**Phase 2: Mock数据清除 (6页面)**:
- ✅ DashboardOverview (887行) — 删除8个MOCK_*常量, 接入`/dashboard/alerts|strategies|monthly-returns|industry-distribution`+`/factors`+`/pipeline/status`, 添加ErrorBanner错误处理
- ✅ DashboardAstock (617行) — 删除5个MOCK_*常量+`@/api/mock`导入, 去掉静默fallback改为错误展示, null初始化+skeleton加载态
- ✅ PTGraduation (414行) — 删除MOCK_GRADUATION(~95行), 9个指标全部从`/paper-trading/graduation-status` API获取(之前只用3个真+6个mock), PageSkeleton/ErrorBanner
- ✅ Portfolio (265行) — 删除MOCK_HOLDINGS/MOCK_SECTOR/MOCK_DAILY_PNL, Promise.allSettled改为错误收集+ErrorBanner, EmptyState空态
- ✅ TradeExecution (280行) — 删除MOCK_PENDING/MOCK_LOG/MOCK_ALGO, React Query去掉initialData, 添加loading/error/empty三态
- ✅ FactorLibrary (186行) — 无需修改(已正确使用React Query, EMPTY_STATS/EMPTY_CORR是合法空态默认值)

**Phase 3: 共享UI组件验证**:
- PageSkeleton/EmptyState/ErrorBanner已存在且被6页面正确使用

**Phase 4: 验证**:
- `npm run build` — 0 new TS errors (pre-existing: test files + QMTStatusBadge)
- `pytest backend/tests/` — 1814 passed, 1 xfailed, 0 failures

**已知遗留(非本Sprint引入)**:
- P2: DashboardOverview KPI网格有内联fallback值(??1.2854等), StrategiesPanel仍为静态JSX
- P2: Portfolio总持仓市值/现金头寸仍为硬编码(需portfolio summary端点)
- P3: 其余9个页面(ReportCenter/MarketData/SystemSettings/RiskManagement等)仍有mock数据

---

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

### Sprint 1.25: 架构对齐专项 (2026-03-29) ✅

**目标**: 全面审计设计文档vs实际实现，修复架构偏离，补全基础设施。不加新功能。

**9/9任务完成。commits 2397998+6967e14。1760 tests (+72 vs Sprint 1.24)。**

**审计发现（P0-P2共14项）**:
- P0: 无Pydantic schemas层、ORM models仅3文件、涨跌颜色弄反、Celery Beat未激活
- P1: 6个设计外页面分散精力、shadcn/ui未安装、Monaco未安装、WebSocket未集成、factor_engine无测试
- P2: 目录结构偏离、死代码、Service层薄、文档不同步

**已完成(9/9)**:
- ✅ T1: 涨跌颜色修复为A股惯例（涨红跌绿）— tokens.ts一处改动全局生效
- ✅ T2: 删除死代码Dashboard.tsx(-268行) + 修复测试引用指向DashboardOverview
- ✅ T3: 创建schemas/目录(8文件) — dashboard/factor/strategy/backtest/pipeline/notification/common
- ✅ T4: 补全ORM models(7文件) — 15张核心表: symbols/klines/daily_basic/trading_calendar/index_daily/factor_registry/factor_values/factor_ic_history/signals/universe_daily/trade_log/position_snapshot/performance_series/backtest_run/backtest_trades
- ✅ T5: 创建utils/目录(4文件) — date_utils(交易日历re-export+周期转换)/math_utils(Sharpe/MDD/IC/年化收益)/validation(K线/因子值质量检查)
- ✅ T6: 重组前端导航 — 按生产使用频率分6组11项(交易高频→策略中频→因子/AI低频→系统)
- ✅ T7: PT心跳监控重写 — 修复SQL列名bug(cal_date→trade_date) + 3维度DB级检查(heartbeat/perf/signals) + 钉钉P0告警 + 注册Task Scheduler(周一-五20:00)
- ✅ T8: 清理mock fallback — FactorLibrary/StrategyWorkspace从MOCK默认值改为空数组+ErrorBanner
- ✅ T9: factor_engine.py补72个单元测试 — 8类: 价量(12)/基本面(6)/技术(7)/KBar(6)/资金流(5)/高级(12)/预处理(11)/IC(5)/边界(8)

**PT链路验证（铁律5——验代码不信文档）**:
- Task Scheduler已注册: DailySignal(16:30) + DailyExecute(09:00) + PTWatchdog(20:00新增)
- performance_series连续5天数据(3/23-3/27), NAV=995,338(-0.47%)
- pt_watchdog实测: 3/3 checks passed
- TushareFetcher旧bug(Mac环境)已在Windows版修复，当前代码正确

**新增文件清单(19文件+3746行)**:
```
backend/app/schemas/{__init__,common,dashboard,factor,strategy,backtest,pipeline,notification}.py
backend/app/models/{base,astock,factor,signal,trade,backtest}.py + __init__.py重写
backend/app/utils/{__init__,date_utils,math_utils,validation}.py
backend/tests/test_factor_engine_unit.py
```

**未完成/遗留(纳入后续Sprint)**:
- shadcn/ui安装（前端组件库升级，需要较大重构）
- Monaco Editor安装（策略工作台代码模式）
- WebSocket集成到backtest_engine（基础设施就绪但引擎端未emit）
- Celery Beat激活（当前PT用Task Scheduler稳定运行，不急切换）
- 设计文档反向更新（DEV_BACKEND.md/DEV_FRONTEND_UI.md需反映实际架构）

**测试**: 1760 passed, 0 failed, 1 xfailed

---

### Sprint 1.25 复盘

**计划vs实际**:
- 计划9项任务，实际完成9项+额外PT链路诊断+Task Scheduler注册
- 预期中等工作量，实际偏重（全面审计+3个并行agent+大量文件创建）

**关键指标**:
- 代码变更: +3746行, -377行 (净+3369行)
- 测试: 1688→1760 (+72)
- 架构覆盖: schemas 0→8文件, models 3→10文件, utils 0→4文件

**质量与风险**:
- ruff: 全部通过（auto-fix 9处import排序）
- TypeScript: 19个既有错误, 0个新增
- PT链路: 连续运行无中断, watchdog已部署

**经验教训**:
- LL-031: 不要机械照搬设计文档——导航从7项精简后发现生产必需的页面（持仓/风控/执行）被删了，应从实际使用出发
- LL-032: PT链路日志在Mac→Windows迁移后变空(0字节)——环境迁移后必须验证日志输出路径
- LL-033: 设计文档和实现互相偏离时，不是单方面改代码回设计，也不是放弃设计——应该双向对齐，好的实现决策反向更新文档
- LL-034: QMT模拟盘应作为PT主执行引擎（而非自写PaperBroker），可获得真实撮合+无缝切实盘

**下一步(Sprint 1.26建议): QMT全面集成**
- QMT连接管理服务（生命周期/心跳/重连）
- QMT数据服务（实时行情→前端/账户查询→持仓页）
- PT执行切换（PaperBroker→MiniQMTBroker模拟盘）
- 前端数据源切换（Market/Portfolio/Execution页面从mock切到QMT真实数据）
- WebSocket推送（QMT实时行情→Dashboard）
- 依赖: QMT客户端持续运行，需确认miniQMT进程管理方案

---

