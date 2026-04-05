# QuantMind V2 — 修复+升级+架构演进 落地文档

> **版本**: 3.1 | **日期**: 2026-04-02
> **基于**: v3.0 + 前沿研究对标(FactorMiner/AlphaForge/Alpha-GPT/QuantaAlpha 2025-2026) + Arnott-Harvey-Markowitz回测协议
> **当前状态**: QMT模拟盘live模式, 4/2首次建仓, 初始资金≈¥1,000,752
> **核心基线**: Sharpe=0.91, MDD=-43%, autocorr-adj Sharpe=0.19, Bootstrap CI [0.09, 1.81]
> **v3→v3.1新增**: 前沿AI因子挖掘技术对标, Experience Memory机制, 动态因子组合权重, DSR回测校正, FactorDSL算子扩展, Alpha101/158批量导入, 实盘反馈闭环, 落地实施方案

---

## 第一部分: Phase A-F 执行记录（已完成 ✅）

### Phase A — 正确性修复 ✅

| # | 任务 | 状态 | 新测试 |
|---|------|------|--------|
| A1 | WLS中性化(OLS→WLS √market_cap加权) | ✅ | 16 |
| A2 | 涨跌停板块差异(创业板/科创±20%, 北交所±30%, ST±5%) | ✅ | 30 |
| A3 | turnover空值(NULL→999 fallback) | ✅ | 18 |
| A4 | 数据单位审计(0错误, 注释补全) | ✅ | 5 |
| A5 | 成交量约束(≤10%日成交额) | ✅ | 18 |
| A6 | API 500修复(6个端点) | ✅ | 10 |
| A7 | pnl_pct补充(avg_cost/unrealized_pnl) | ✅ | 18 |
| A8 | zscore截断±3(preprocess_pipeline Step5) | ✅ | 16 |
| A9 | IC超额收益确认(已正确使用vs CSI300) | ✅ 无需改动 | 0 |
| A10 | mergesort确定性(关键sort_values加kind='mergesort') | ✅ | 18 |

### Phase B — 工程基础 ✅

| # | 任务 | 状态 |
|---|------|------|
| B1 | structlog全栈统一(76文件迁移) | ✅ |
| B2 | FastAPI Depends(18个API文件已100%使用) | ✅ 已到位 |
| B3 | TimescaleDB | ⚠️ 方案B跳过(EDB PG16不兼容) |
| B4 | DDL对齐(45张表全在, mining_knowledge补6列) | ✅ |
| B5 | 备份自动化(pg_backup.py + verify_backup.py) | ✅ |
| B6 | 健康预检(Redis/Celery真实检查) | ✅ |

### Phase C — 策略层 ✅

| # | 任务 | 状态 |
|---|------|------|
| C1 | Hybrid回测架构(vectorized_signal.py + run_hybrid_backtest) | ✅ |
| C2 | DataFeed多源(from_database/from_parquet/from_dataframe) | ✅ |
| C3 | 因子衰减3级处置(L1告警/L2降权/L3退役) | ✅ |
| C4 | 因子择时[0.5x, 1.5x] | ✅ |
| C5 | 回测报告12项指标 | ✅ |
| C6 | CompositeStrategy + RegimeModifier | ✅ 已有实现 |
| C7 | FactorClassifier(8种因子类型) | ✅ 已有实现 |

### Phase D — AI闭环 ✅

| # | 任务 | 状态 |
|---|------|------|
| D1 | GP引擎(DEAP, Warm Start/岛屿/反拥挤, EvoGP延后) | ✅ |
| D2 | FactorDSL(28算子+量纲+AST去重) | ✅ |
| D3 | Gate G1-G8(8层+BH-FDR) | ✅ |
| D4 | GP Pipeline(7步闭环+Celery) | ✅ |
| D5 | LLM 3-Agent(+FactorAgent+EvalAgent补全) | ✅ |
| D6 | Orchestrator(+Thompson Sampling补全) | ✅ |

### Phase E — 前端 ✅

| 状态 | 说明 |
|------|------|
| ✅ | 22页面(超设计目标83%), 14页接真实API, 47个API端点全部200 |
| ⚠️ | 前端问题多(数据不加载/格式错误/Recharts警告), 决定后端全部稳定后再重建 |

### Phase F — 生产加固 ✅

| # | 任务 | 状态 |
|---|------|------|
| F1 | NSSM服务化(nssm_setup.ps1就绪) | ✅ |
| F2 | 220参数全量注册(106→220) | ✅ |
| F3 | 文档同步(doc_drift_check.py, 6 PASS 0 WARN) | ✅ |
| F4 | 灾备演练(disaster_recovery_verify.py就绪) | ✅ |

**Phase A-F 累计: 185个新测试, 904全量通过, 0回归**

---

## 第二部分: 已完成的研究与决策记录

### G2 风险平价研究 — 已完成，结论：无效

> **日期**: 2026-04-02 | **报告**: G2_RISK_PARITY_REPORT.md

7组实验全部完成，等权是当前策略的最优权重方案。

| # | 实验 | Sharpe | MDD | 结论 |
|---|------|--------|-----|------|
| 1 | **equal (基线)** | **0.91** | **-43.0%** | **最优** |
| 2 | risk_parity (vol20) | 0.83 | -46.8% | Sharpe↓ MDD↑ |
| 3 | min_variance (vol20) | 0.73 | -50.4% | 更差 |
| 4b | risk_parity (vol60) | 0.83 | -45.7% | 无改善 |
| 5 | equal + vol_regime | 0.80 | -45.6% | vol_regime无效 |
| 6 | rp + vol_regime | 0.65 | -50.7% | 最差 |

**根因**: 持仓96%是小盘股(<100亿), Alpha来源(amihud/reversal→高波动小盘)与风险暴露深度绑定, 降风险=降Alpha。权重优化这条路走不通。

**关键洞察**: vol_regime(波动率缩放)也无效，因为Alpha在高波动期最强(2021/2025)。但vol_regime≠动态仓位(20d momentum)，后者看的是收益方向不是波动率水平，需要单独验证(G2.5)。

**产出物**: signal_engine.py新增risk_parity/min_variance权重, run_backtest.py新增--weight-method/--vol-regime参数。均不影响PT。

### 质量审计记录

| 审计 | 发现 | 状态 |
|------|------|------|
| 后端质量审计 | 52个问题(5 CRITICAL/12 HIGH/20 MED/15 LOW) | 最大问题: async/sync两套DB共存 + 70% API返回untyped dict |
| 功能审计 | 86项73%完成, 核心交易链路97% | 缺失集中在AI闭环(33%)和策略管理(35%) |
| 前端审计 | 22页面, 多数有数据不加载/格式错误 | 决定后端稳定后再重建 |
| 前后端集成审计 | 18维度32问题 | 调度链路已优化, 冒烟测试62端点每小时自动跑 |

### 因子研究历史决策

| 结论 | 来源 | 影响 |
|------|------|------|
| 等权线性组合有天花板(~5-6因子) | Sprint 1.3b | 超过后边际收益为负, ML非线性是突破方向 |
| 基本面因子在等权框架完全无效 | Sprint 1.5, 10种方式8 FAIL | 方向关闭, 但LightGBM可能发现交互效应 |
| 量价因子IC天花板0.05-0.06 | 暴力枚举Layer 1-2 | 继续量价维度边际收益极低 |
| amount类因子IC=0.09是市值效应(假信号) | 暴力枚举分析 | 排除, 不入库 |
| mf_divergence(IC=9.1%)被月度框架冤杀 | LL-027 | 需EVENT框架重测 |
| PEAD(IC=5.34%)被月度框架冤杀 | LL-027 | 需EVENT框架重测 |
| LLM自由生成因子失败(IC=0.006-0.008) | W7b 5次测试 | 需数据驱动prompt, 不是盲猜 |
| 动态仓位(20d momentum): Sharpe 0.32→1.76, MDD -28%→-11.4% | 旧代码验证 | 效果极好但需在新基线上重新验证(G2.5) |
| QMT真实滑点47.6bps, SimBroker预估176.7bps(高估3.7x) | 实盘数据 | 5000万流动性过滤不必要 |

---

## 第三部分: 当前系统全面状态

### 运行状态

| 维度 | 值 |
|------|------|
| 执行模式 | QMT模拟盘live模式, 4/2首次建仓 |
| 账户 | 初始≈¥1,000,752(非精确100万, 有历史测试交易), NAV≈¥989,391 |
| 持仓 | 9只(QMT live), SimBroker paper已归档 |
| PT天数 | 从QMT建仓日(4/2)重新计算, Day 0 |
| PT毕业阈值 | Sharpe ≥ 0.91 × 0.7 = 0.637, MDD ≤ -43% × 1.5 = -64.5% |
| NAV数据源 | QMT query_asset()["total_asset"], 不自行计算 |

### 调度链路

| 时间 | 任务 | 说明 |
|------|------|------|
| 02:00 | QM-DailyBackup | 备份 |
| 16:15 | QuantMind_DailyPull | 拉daily行情 |
| 16:25 | QM-HealthCheck | 预检 |
| 16:30 | QuantMind_DailySignal | 因子+信号生成 |
| 17:00 | QuantMind_DailyMoneyflow | moneyflow补拉 |
| 17:15 | QuantMind_DataQualityCheck | 数据巡检 |
| 17:30 | QuantMind_FactorHealthDaily | 因子衰减检测 |
| T+1 09:31 | QuantMind_DailyExecute | QMT live执行 |
| T+1 15:10 | QuantMind_DailyReconciliation | QMT对账 |

### 因子池状态

| 池 | 数量 | 说明 |
|------|------|------|
| CORE (Active, PT在用) | 5 | turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio |
| FULL | 14 | 含CORE+扩展(momentum_20等) |
| RESERVE | 2 | vwap_bias, rsrs_raw(被月度框架冤杀, 待正确框架重测) |
| DEPRECATED | 8 | momentum_5/10, turnover_stability_20等(冗余或IC衰减) |
| ML特征 | 12 | zscore clip ±3已修复 |
| LGBM特征集 | 26 | G1 Walk-Forward设计中的特征集 |
| factor_values有数据 | 37 | DB中实际有数据的因子 |

### 代码规模

| 维度 | 值 |
|------|------|
| 后端Python | ~138K行, 166个文件 |
| 前端React | 22个页面, 44个组件 |
| DB | 43张表 |
| 测试 | 904通过, 0回归 |
| 设计文档 | 20+份, 20,000+行 |

---

## 第四部分: 架构演进路线图（Phase G-L, 更新版）

> **核心基线**: Sharpe=0.91, MDD=-43%, autocorr-adj Sharpe=0.19
> **核心目标**: MDD从-43%降到-15%以内, Sharpe维持0.8+, 年化收益15-25%
> **核心洞察**: Sharpe=0.91主要来自小盘风格beta(2021+99%, 2025+68%), 不是纯选股alpha。autocorr-adj仅0.19。MDD=-43%是生存问题。

### 优先级原则（v3更新）

```
生存(MDD控制) > Alpha来源多元化 > 策略自动化闭环 > 执行优化 > 研究效率 > 基础设施
```

---

### Phase G — 组合升级 + ML（最高优先级）

#### G1. LightGBM Walk-Forward v1.3

| 属性 | 值 |
|------|------|
| **任务** | 实现ML_WALKFORWARD_DESIGN.md中905行的完整设计：7-fold Walk-Forward + Optuna超参搜索 + GPU训练 |
| **核心改变** | 5因子等权(线性) → LightGBM预测(非线性)。ML能捕捉因子交互(如高换手+低波动的组合效应) |
| **特征** | 51个(5基线+12多尺度+8资金流+10价格行为+8基本面+8市场状态), 其中13就绪/31缺代码有数据/3缺数据源 |
| **目标** | OOS Sharpe ≥ 0.8, paired bootstrap p < 0.05 vs 等权基线 |
| **上线标准** | OOS Sharpe ≥ 基线×1.2 + p < 0.05 + 6红线全过 → 影子PT → v1.3升级 |
| **估时** | 10天(Optuna 5h + 7fold训练70min + 回测分析) |
| **GPU** | RTX 5070, device_type=gpu, max_bin=63 |

#### G2. 风险平价替代等权 ✅ 已完成 — 结论：无效

> 见第二部分研究记录。权重优化走不通，回撤控制应靠总仓位管理。

#### G2.5 动态仓位验证（进行中）

| 属性 | 值 |
|------|------|
| **任务** | 在当前基线(Sharpe=0.91)上验证动态仓位(20d momentum, 100/50/0三档) |
| **机制** | 20d全市场等权平均收益: >0满仓, <0半仓, <-10%空仓 |
| **与vol_regime的区别** | vol_regime看波动率水平(高波降仓→但Alpha在高波动期最强→无效)。动态仓位看收益方向(下跌期降仓, 上涨期满仓, 无论波动率高低) |
| **旧代码结果** | Sharpe 0.32→1.76, MDD -28%→-11.4%(不同基线, 需重新验证) |
| **预期** | Sharpe 1.2-1.5, MDD -15%~-25% |
| **估时** | 1天 |
| **状态** | ⏳ 正在运行 |

#### G3. 风格归因分析（v3新增, P0）

| 属性 | 值 |
|------|------|
| **任务** | 把每年收益拆解为: 市场beta + 规模因子(SMB) + 价值因子(HML) + 动量 + 残差alpha |
| **目的** | 确定Sharpe=0.91是真实选股alpha还是小盘风格beta暴露 |
| **方法** | Barra风格因子回归 或 Fama-French三因子回归(用A股因子数据) |
| **影响** | 如果残差alpha≈0 → 所有"找更多因子"的努力方向都是错的, 应转向风格择时。如果残差alpha显著为正 → 继续优化因子和模型 |
| **估时** | 1-2天 |
| **优先级** | 极高 — 这个分析决定整个项目的方向 |

#### G4. 因子正交化分析（v3新增）

| 属性 | 值 |
|------|------|
| **任务** | 5个Active因子做Gram-Schmidt正交化, 测每个因子的独立贡献 |
| **目的** | 确认5个因子是否真的提供5个独立信号维度(还是只有2-3个, 其他是冗余) |
| **影响** | 决定因子池扩展策略: 如果只有2个独立维度, 增加同维度因子再多也没用 |
| **估时** | 1天 |

#### G5. 分市值层策略分析（v3新增）

| 属性 | 值 |
|------|------|
| **任务** | 持仓按市值分层(<30亿/30-100亿/100-500亿/>500亿), 分析每层的收益贡献 |
| **目的** | 确认alpha是否只存在于微盘股(如果是, 策略容量极有限) |
| **实验** | 剔除<50亿持仓后Sharpe变多少? 只在100-500亿中盘选股Sharpe变多少? |
| **估时** | 1天 |

#### G6. 因子+模型联合迭代框架

| 属性 | 值 |
|------|------|
| **任务** | 参考RD-Agent(Q): 因子搜索和模型训练交替进行, 新因子反馈给模型重训, 模型效果反馈给因子搜索方向 |
| **与现有集成** | GP Pipeline(D4) + LLM Agent(D5) + Gate(D3) + LightGBM(G1) 串联 |
| **估时** | 7天 |
| **依赖** | G1完成后 |

#### G7. 动态因子组合权重（v3.1新增, 参考AlphaForge AAAI 2025）

| 属性 | 值 |
|------|------|
| **任务** | 每个调仓日根据因子近期IC表现动态重新计算权重, 替代固定等权 |
| **与C4区别** | C4因子择时是简单的[0.5x, 1.5x]clip。G7是每个调仓日用滚动12个月IC_IR重新计算权重, 自动降低衰减因子的权重, 提升改善因子的权重 |
| **参考** | AlphaForge: 在每个时间步重新评估Factor Zoo中每个因子的近期表现, 动态筛选和整合因子形成Mega-Alpha信号 |
| **实现** | `signal_engine.py`中新增`dynamic_ic_weight`模式: weight_i(t) = IC_IR_i(t-12m:t) / Σ IC_IR_j(t-12m:t), clip to [0.05, 0.40], 归一化 |
| **验证** | 5年回测对比: 固定等权 vs C4择时 vs G7动态IC权重。年度分解看因子衰减年(2024)是否自动降权 |
| **估时** | 3天 |
| **依赖** | G1完成后(先确认ML方向, 再优化线性基线) |

#### G8. DSR回测校正（v3.1新增, 参考Arnott-Harvey-Markowitz 2019）

| 属性 | 值 |
|------|------|
| **任务** | 对Sharpe=0.91做Deflated Sharpe Ratio校正, 确认策略是否真的有效 |
| **为什么重要** | 0.91是从多种配置中选出最优的结果(等权/IC加权/风险平价/各种滑点模型), 存在选择偏差膨胀 |
| **实现** | 1) 盘点历史上总共测试了多少种配置(估计N); 2) 计算策略间相关性矩阵, 估计effective N; 3) 用ML_WALKFORWARD_DESIGN.md §4.12的DSR公式计算; 4) 输出"原始Sharpe 0.91, DSR校正后 X.XX" |
| **解读标准** | DSR>0.95=统计显著, 0.5-0.95=可疑, <0.5=大概率过拟合 |
| **注意** | DSR假设试验独立, 但我们的多种配置共享因子和选股, effective N可能只有5-8个。需先估计effective N再算DSR, 避免过度惩罚 |
| **估时** | 1天 |

#### Phase G 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 9 (G1/G2✅/G2.5⏳/G3-G8) |
| 总估时 | ~25天(扣除已完成的G2) |
| 预期收益 | MDD -43% → -15%~-25%(动态仓位), Sharpe维持0.8+, DSR校正确认策略有效性 |

---

### Phase GA — AI闭环自动管道（v3新增, 高优先级）

> **核心洞察**: D1-D6的零件全部就绪(GP/FactorDSL/Gate/Pipeline/LLM Agent/Orchestrator),
> 但没有串成端到端的自动管道。因子从挖掘→分类→匹配策略→回测→上线应该自动化。
> 当前每次都是人工判断"这个因子应该用什么框架测", 系统跑起来后不可持续。

#### GA1. StrategyMatcher（因子分类→回测配置映射）

| 属性 | 值 |
|------|------|
| **任务** | 建立FactorClassifier输出类型到回测配置的自动映射表 |
| **映射** | RANKING→月度Top-N, FAST_RANKING→周度Top-N, EVENT→事件触发, MODIFIER→叠加测试, CONDITIONAL→送入ML特征池 |
| **接口** | `strategy_matcher.match(factor_class) → BacktestConfig` |
| **估时** | 2天 |

#### GA2. EVENT回测器（关键缺失模块）

| 属性 | 值 |
|------|------|
| **任务** | 实现事件触发式回测: 信号出现→买入, 持有N日→卖出 |
| **为什么缺失** | 当前只有月度Top-N一种回测方式, EVENT型因子(mf_divergence/PEAD)被强制塞入月度框架导致"冤杀" |
| **接口** | `run_event_backtest.py --trigger-threshold 0.8 --hold-days 20 --max-positions 10` |
| **验证** | mf_divergence(IC=9.1%)用EVENT框架重测, 对比月度框架下p=0.387的旧结果 |
| **估时** | 5天 |
| **优先级** | 极高 — 这是释放已有高IC因子价值的关键 |

#### GA3. 诊断Agent + Experience Memory（反馈环, v3.1升级参考FactorMiner）

| 属性 | 值 |
|------|------|
| **任务** | 分析挖掘失败原因+维度饱和度+IC衰减趋势 → 自动调整搜索方向 → 反馈给Orchestrator |
| **输入** | mining_knowledge最近50个失败因子, Active因子IC趋势, 因子相关性矩阵, 市场regime |
| **输出** | 搜索方向建议(如"量价维度饱和, 转向资金流×北向跨源搜索") + LLM Agent的数据驱动prompt自动生成 |
| **v3.1新增: Experience Memory** | 参考FactorMiner(清华,2026-02)的Ralph Loop机制。每轮搜索结束后自动提炼两类知识: |
| | **成功模式**: 哪些算子组合+数据源组合倾向于产出高IC因子(如"moneyflow×量价跨源组合IC普遍>0.05") |
| | **禁区(Forbidden Regions)**: 哪些因子族已经饱和不值得继续搜索(如"量价单表因子corr>0.7概率>80%") |
| **实现** | mining_knowledge表新增字段: `pattern_type`(success_pattern/forbidden_region), `pattern_rule`(JSON规则), `confidence`(基于历史命中率)。诊断Agent每轮提炼后写入, 下一轮搜索前读取作为先验 |
| **与D6集成** | 诊断结果→更新Thompson Sampling先验→GP/LLM/暴力枚举资源分配自动调整 |
| **估时** | 7天(含Experience Memory实现) |
| **依赖** | GA1/GA2完成后 |

#### GA4. AutoBacktestRouter（自动路由）

| 属性 | 值 |
|------|------|
| **任务** | 候选因子自动经过: FactorClassifier → StrategyMatcher → 对应回测器 → Gate评估 → 审批队列 |
| **端到端流程** | 无需人工判断用什么框架, 系统自动路由 |
| **人工节点** | 只在gp_approval_queue审批时需要人工 |
| **估时** | 3天 |
| **依赖** | GA1/GA2/GA3完成后 |

#### GA5. LLM数据驱动Prompt生成器 + 分层RAG（v3.1升级参考Alpha-GPT）

| 属性 | 值 |
|------|------|
| **任务** | 诊断Agent的分析结果自动转化为LLM Agent的prompt |
| **改变** | LLM从"盲猜因子"(IC=0.006)变为"基于数据分析搜索"(目标IC>0.03) |
| **prompt内容** | 自动包含: 数据表schema, 已有因子IC排序, 相关性矩阵, 分年度IC热力图, 维度饱和度分析, 搜索方向建议 |
| **v3.1新增: 分层RAG** | 参考Alpha-GPT(HKUST,2025)的分层检索增强生成。不是手动构造prompt, 而是: 1) 从因子库中自动检索与当前搜索方向相关的成功因子作为few-shot示例; 2) 从Experience Memory中检索相关的成功模式和禁区; 3) 从mining_knowledge中检索同类别失败因子的失败原因。三层信息自动组装成prompt |
| **实现** | 因子库+Experience Memory+mining_knowledge用向量化存储(ChromaDB或简单的TF-IDF), 每次搜索前自动检索Top-5相关条目注入prompt |
| **估时** | 5天(含RAG实现) |
| **依赖** | GA3完成后 |

#### GA6. FactorDSL算子扩展 28→60+（v3.1新增）

| 属性 | 值 |
|------|------|
| **任务** | 扩展FactorDSL算子库, 从当前28个增加到60+个 |
| **新增算子** | IfElse(条件选择), TsRank(时序排名), Rsquare(R²), Correlation(相关性), GroupRank(分组排名), WMA(加权移动平均), EMA(指数移动平均), HighDay/LowDay(最高/最低价位置), Regress(回归残差)等 |
| **来源** | FactorMiner(60+算子) + PandaFactor(RSI/MACD/KDJ/ATR/OBV/BOLL等技术指标) + Alpha101算子集 |
| **为什么重要** | 之前暴力枚举只用了6个字段×4个算子, 搜索空间太小。扩展算子后GP搜索空间指数级增长, 且能表达更复杂的金融逻辑(如条件因子) |
| **实现** | 在factor_dsl.py中注册新算子, 每个算子需包含: 计算函数、量纲约束(防止无意义组合)、复杂度权重 |
| **估时** | 5天 |

#### GA7. Alpha101/158因子公式批量导入（v3.1新增）

| 属性 | 值 |
|------|------|
| **任务** | 从Qlib Alpha158公式集中提取因子, 翻译成我们的管道格式, 批量跑IC筛选 |
| **为什么到现在没做** | 讨论了至少3次(Sprint 1.3/K扩展/V3路线图), 但每次被更高优先级任务挤掉 |
| **实现** | 1) 下载Alpha158因子定义(不安装Qlib框架); 2) 翻译成FactorDSL表达式或pandas函数; 3) 批量计算5年IC; 4) 与现有37个因子做相关性矩阵; 5) IC>0.02且corr<0.7的入候选池 |
| **预计产出** | 158个公式去掉与现有因子重叠的, 预计60-80个新候选, 其中10-20个通过Gate |
| **零成本** | 不需要API/LLM, 纯数学公式翻译+计算 |
| **估时** | 3天 |

#### Phase GA 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 7 (GA1-GA7) |
| 总估时 | ~30天 |
| 预期收益 | 因子挖掘从手动变自动, 被冤杀因子释放, LLM成功率提升, 因子池从37扩展到80+, 搜索空间从28算子扩展到60+ |

**完整AI闭环流程图:**

```
感知层: factor_lifecycle监控IC衰减 + 市场regime检测
    ↓
诊断层: 诊断Agent(GA3)分析失败原因 + 维度饱和度 + 搜索方向
    ↓
决策层: Orchestrator(D6) Thompson Sampling分配资源
    ↓
搜索层: GP(D1) / LLM(D5+GA5数据驱动) / 暴力枚举 并行搜索
    ↓
评估层: FactorClassifier(C7) → StrategyMatcher(GA1) → AutoBacktestRouter(GA4)
           ├─ RANKING → 月度Top-N回测
           ├─ EVENT → 事件触发回测(GA2)
           ├─ MODIFIER → 叠加测试
           └─ CONDITIONAL → 送入ML特征池
    ↓
筛选层: Gate G1-G8(D3) 自动评估
    ↓
部署层: gp_approval_queue → 人工审批 → CompositeStrategy(C6)自动编排
    ↓
监控层: factor_lifecycle持续监控 → IC衰减触发新一轮搜索 → 回到感知层
```

---

### Phase K — Alpha来源多元化（v3升级, 高优先级）

> **v3核心变化**: 不再是"锦上添花"的因子扩展, 而是解决"一条腿走路"的生存问题。
> 当前Alpha全部来自小盘价值反转, 风格不利时(2022/2024)大幅亏损。
> 多元化不同Alpha来源比优化单一策略更重要。

#### K0. 因子资产全面盘点（v3新增, P0）

| 属性 | 值 |
|------|------|
| **任务** | 查出系统中所有因子的完整状态: 代码注册表 + factor_values DB + mining_knowledge + factor_lifecycle + TECH_DECISIONS.md |
| **输出** | 因子资产清单(因子名/类别/IC/FactorClassifier分类/当前状态/所在池/推荐动作) |
| **重点** | 哪些IC>0.03但不在Active池? 哪些通过Gate但组合回测失败(用了什么框架)? 孤儿因子? |
| **估时** | 1天 |

#### K1. 行业轮动因子

| 属性 | 值 |
|------|------|
| **任务** | 申万一级行业动量/反转因子。个股Alpha叠加行业Alpha |
| **因子** | industry_momentum_20(行业20日收益率), industry_reversal_60(行业60日反转) |
| **价值** | 与个股截面选股低相关 — 个股选小盘, 行业选强势板块, 两个维度独立 |
| **估时** | 3天 |

#### K2. PEAD事件驱动重测

| 属性 | 值 |
|------|------|
| **任务** | 用EVENT框架(GA2)重新评估PEAD(盈利公告后漂移) |
| **策略** | 公告后5日窗口买入超预期股, 持有20日 |
| **历史** | IC=5.34%但被月度框架"冤杀"(LL-027) |
| **依赖** | GA2(EVENT回测器)完成后 |
| **估时** | 3天 |

#### K3. RSRS/VWAP/mf_divergence正确框架重测

| 属性 | 值 |
|------|------|
| **任务** | RSRS用EVENT触发框架, VWAP用FAST_RANKING(周度), mf_divergence(IC=9.1%)用EVENT框架 |
| **历史** | 全部通过单因子Gate但在月度等权框架下失败 |
| **依赖** | GA1(StrategyMatcher) + GA2(EVENT回测器) |
| **估时** | 3天 |

#### K4. 多策略叠加回测

| 属性 | 值 |
|------|------|
| **任务** | CompositeStrategy(C6)框架下实现真正的多层策略 |
| **架构** | 核心层(60-70%, RANKING月度Top-N) + 增强层(20-30%, EVENT触发mf_divergence/PEAD) + 防御层(MODIFIER, 动态仓位调总仓位) |
| **验证** | 三层叠加 vs 单一核心层: Sharpe对比 + MDD对比 + 相关性分析 |
| **依赖** | K2/K3完成后 |
| **估时** | 7天 |

#### K5. 暴力枚举Layer 3-4

| 属性 | 值 |
|------|------|
| **任务** | Layer 3跨表二元组合(676个) + Layer 4三元组合(~2000个) |
| **价值** | Layer 1-2发现turnover系列(corr<0.35)是真正独立信号, 跨表组合可能发现更多 |
| **零成本** | 不需要LLM/API, 纯计算, 30分钟跑完 |
| **估时** | 2天 |

#### K6. 另类数据因子（v3新增）

| 属性 | 值 |
|------|------|
| **任务** | 利用A股独特数据源: 大宗交易折价(机构信号), 股东人数变化(筹码集中度), 限售股解禁日历, 龙虎榜(游资行为) |
| **数据** | Tushare部分可用, 需查TUSHARE_DATA_SOURCE_CHECKLIST.md确认 |
| **估时** | 5-7天 |

#### K7. 跨市场信号（v3新增）

| 属性 | 值 |
|------|------|
| **任务** | VIX→A股次日情绪, 商品价格→周期行业择时, 国债收益率曲线→股债轮动, 人民币汇率→北向资金预测 |
| **类型** | MODIFIER型信号, 不选股, 调仓位/行业配置 |
| **估时** | 5天 |

#### K8. 情感数据接入

| 属性 | 值 |
|------|------|
| **任务** | 东方财富/同花顺股吧情感分析, DeepSeek V3本地推理 |
| **因子** | sentiment_score_3d, sentiment_divergence(情感vs价格背离) |
| **估时** | 7-10天 |
| **依赖** | G1完成后(先有ML框架再加特征) |

#### K9. GP三目标适应度函数（v3.1新增）

| 属性 | 值 |
|------|------|
| **任务** | GP适应度函数从单一IC升级为三目标: maximize(Sharpe) + maximize(年化收益) + minimize(MDD) |
| **参考** | 2026年Computational Economics论文: CSI 300上用GP+三目标+LightGBM集成, 实现年化47.75%, Sharpe 1.59 |
| **当前问题** | GP只用IC做适应度, 可能产出IC高但MDD大或换手率极高的因子 |
| **实现** | gp_engine.py中fitness函数改为: fitness = w1×Sharpe + w2×CAGR - w3×MDD - w4×turnover, 权重可配置 |
| **估时** | 2天 |

#### Phase K 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 10 |
| 总估时 | ~40天 |

---

### Phase H — 执行优化 + 交易成本控制

#### H1. TWAP拆单执行

| 属性 | 值 |
|------|------|
| **任务** | 大额订单拆成3-5个小单, 每隔2分钟下一个 |
| **适用** | 单笔交易>日成交额1%时触发 |
| **预期** | 滑点降低50-70% |
| **估时** | 3天 |

#### H2. TCA交易成本归因

| 属性 | 值 |
|------|------|
| **任务** | 每笔交易拆解: 信号价→决策价→到达价→成交价, 量化每层损耗 |
| **估时** | 2天 |

#### H3. 智能执行路由

| 属性 | 值 |
|------|------|
| **任务** | 根据流动性自动选执行策略: 大盘→市价, 小盘→TWAP, 超小盘→限价挂单 |
| **估时** | 3天 |

---

### Phase I — 风险管理升级

#### I1. 宏观择时信号

| 属性 | 值 |
|------|------|
| **任务** | 信用利差/M2/PMI/均线/VIX proxy → 宏观恶化时降仓 |
| **估时** | 5天 |

#### I2. 因子正交化时序监控

| 属性 | 值 |
|------|------|
| **任务** | 每日监控5个Active因子间截面Spearman相关性变化趋势, 任意两因子>0.5告警 |
| **估时** | 1天 |

#### I3. 动态Universe

| 属性 | 值 |
|------|------|
| **任务** | 牛市→全市场, 熊市→仅沪深300成分股(防御性) |
| **估时** | 5天 |

#### I4. 组合压力测试

| 属性 | 值 |
|------|------|
| **任务** | 用历史极端场景(2015股灾/2018贸易战/2022系统性下跌)对当前持仓压力测试 |
| **估时** | 3天 |

#### I5. 对抗过拟合系统（v3新增）

| 属性 | 值 |
|------|------|
| **任务** | CPCV(Combinatorially Purged CV) + DSR(Deflated Sharpe Ratio) + Strategy Hierarchy Testing |
| **目的** | 校正多重检验偏差后的真实Sharpe, 避免回测过拟合 |
| **估时** | 5天 |
| **依赖** | G1完成后 |

---

### Phase J — 研究效率提升

| # | 任务 | 估时 |
|---|------|------|
| J1 | 实验追踪自动化(experiments表) | 2天 |
| J2 | 策略配置YAML化 | 2天 |
| J3 | Point-in-Time数据管理(available_at字段) | 3天 |
| J4 | 回测缓存层(Parquet快照) | 3天 |
| J5 | 因子资产盘点工具(一键输出清单) | 1天 |

---

### Phase L — 基础设施升级

| # | 任务 | 估时 | 触发条件 |
|---|------|------|---------|
| L1 | 模型滚动重训自动化(月度LightGBM重训) | 5天 | G1完成后 |
| L2 | 异常检测与自愈(NaN保护/API重试/数据断更补拉) | 3天 | 随时 |
| L3 | 配置即代码(Strategy as Config, YAML生产化) | 3天 | J2后 |
| L4 | EvoGP GPU加速(DEAP→EvoGP) | 4天 | GP瓶颈时 |
| L5 | RL执行优化(PPO/SAC动态仓位) | 10天 | K4后 |
| L6 | 分钟数据管道(日内监控/TCA) | 5天 | Phase 2 |
| L7 | 实盘反馈循环(v3新增) | 3天 | QMT积累2周数据后 |

#### L7说明: 实盘反馈循环（v3.1扩展）

| 属性 | 值 |
|------|------|
| **任务** | 建立"真实交易数据→校准回测参数→改进模型"的系统闭环 |
| **三层反馈** | |
| **① 滑点校准** | 按市值/行业/成交额分层统计真实滑点分布, 用真实数据替代SimBroker的volume_impact参数(当前高估3.7x)。每月重算一次cost_model参数 |
| **② 执行质量分析** | 真实成交时间分布(集合竞价vs盘中), 部分成交率, 废单率, 按时段/市值的滑点差异。输出为每月TCA报告 |
| **③ 信号vs实际偏差** | 比较信号生成时的target_weight与实际执行后的actual_weight, 量化tracking_error来源(滑点/部分成交/涨跌停未成交) |
| **实现** | 新建`scripts/analyze_live_performance.py`, 每周日自动运行, 输出JSON报告写入experiments表。当真实滑点与SimBroker偏差>50%时触发钉钉告警 |
| **落地标准** | QMT积累10个交易日后首次运行; 积累30个交易日后校准SimBroker参数; 积累60个交易日后SimBroker应与QMT真实结果差异<10% |
| **依赖** | QMT积累至少10个交易日数据 |

---

## 第五部分: 多策略架构设计

> **v3核心新增**: 不是在单一策略上越挖越深, 而是建立多个低相关策略共同工作。

### 目标架构

```
┌────────────────────────────────────────────────────┐
│              多策略资金管理（总控）                    │
│     Thompson Sampling动态分配资金到各策略              │
│                                                      │
│  策略A: 小盘价值反转    策略B: 事件驱动                │
│  (当前, RANKING月度)   (mf_divergence/PEAD)          │
│  Sharpe~0.91           待EVENT框架验证                │
│  核心层 60-70%         增强层 20-30%                  │
│                                                      │
│  策略C: 行业轮动       策略D: ML非线性                 │
│  (行业动量/反转)       (LightGBM 51特征)              │
│  独立维度alpha          因子交互效应                   │
│  待K1实现               待G1实现                      │
│                                                      │
│  防御层: 动态仓位(20d momentum)                       │
│  调整所有策略的总仓位, 不参与选股                      │
│                                                      │
│  ML联合层: CONDITIONAL型因子                          │
│  LightGBM发现因子交互效应, 叠加在策略A/B/C之上         │
└────────────────────────────────────────────────────┘
```

### 因子→策略映射（FactorClassifier + StrategyMatcher）

| 因子类型 | 调仓频率 | 选股方法 | 代表因子 | 策略归属 |
|---------|---------|---------|---------|---------|
| RANKING | 月度 | Top-N截面排序 | amihud, turnover, reversal, volatility, bp_ratio | 策略A(核心) |
| FAST_RANKING | 周度 | Top-N截面排序 | VWAP, 短周期反转 | 策略A增强 |
| EVENT | 触发式 | 阈值触发+固定持有期 | mf_divergence, PEAD, RSRS | 策略B(增强) |
| MODIFIER | 每日 | 不选股, 调仓位 | 动态仓位(20d), RegimeModifier, 宏观择时 | 防御层 |
| CONDITIONAL | 月度 | ML特征 | 基本面×波动率交互, 非线性组合 | 策略D(ML) |

### 因子挖掘→策略的自动化路径

| 挖掘路径 | 主要产出类型 | 工具 |
|---------|------------|------|
| GP遗传编程+暴力枚举 | RANKING(长半衰期, 高IC稳定性) | D1+D2, 零成本 |
| LLM Agent(数据驱动) | EVENT(财报/政策/资金流异动, 短期IC>3%) | D5+GA5 |
| 市场微观结构分析 | MODIFIER(波动率regime/流动性/宏观) | 手动+研究 |
| 学术因子复刻 | RANKING/EVENT(Alpha101/158/论文) | LLM翻译 |
| 跨市场数据 | MODIFIER(VIX/商品/汇率) | 手动+K7 |

---

## 第六部分: 全局路线图

### 依赖关系（v3更新）

```
Phase A-F (已完成) + G2 (已完成-无效)
    │
    ├──→ G2.5 动态仓位验证 (⏳ 正在运行)
    │       ↓ 如果有效
    │       部署到QMT PT
    │
    ├──→ G3 风格归因 (P0, 决定项目方向)
    │    G4 因子正交化
    │    G5 分市值层分析
    │       ↓ 确认alpha来源后
    │
    ├──→ K0 因子资产盘点 → GA1+GA2 (EVENT回测器+StrategyMatcher)
    │       ↓
    │    K2+K3 被冤杀因子正确框架重测
    │       ↓
    │    K4 多策略叠加回测
    │
    ├──→ G1 LightGBM Walk-Forward (与上面并行)
    │       ↓
    │    GA3+GA4+GA5 (诊断Agent+AutoRouter+LLM数据驱动)
    │       ↓
    │    G6 因子+模型联合迭代
    │
    ├──→ Phase H (执行优化, QMT积累数据后)
    │
    ├──→ Phase I (风险升级, 与K并行)
    │
    ├──→ Phase J (研究效率, 随时可做)
    │
    └──→ Phase L (基础设施, 长期持续)
```

### 执行优先级排序（v3更新）

| 优先级 | 任务 | 预期收益 | 工作量 | 建议时间 |
|--------|------|---------|--------|---------|
| ⭐1 | G2.5 动态仓位验证 | MDD -43%→-15%~-25% | 1天 | 正在运行 |
| ⭐2 | G3 风格归因分析 | 决定项目方向 | 1-2天 | 本周 |
| ⭐3 | K0 因子资产盘点 | 摸清家底 | 1天 | 本周 |
| ⭐4 | GA2 EVENT回测器 | 释放mf_divergence/PEAD | 5天 | 本周 |
| ⭐5 | G1 LightGBM v1.3 | 非线性选股 | 10天 | 本周启动 |
| 6 | GA1 StrategyMatcher | 自动化管道 | 2天 | GA2后 |
| 7 | K2+K3 被冤杀因子重测 | 新alpha来源 | 6天 | GA2后 |
| 8 | G4+G5 因子分析 | 深入理解策略 | 2天 | G3后 |
| 9 | K1 行业轮动 | 独立维度alpha | 3天 | G3后 |
| 10 | K4 多策略叠加 | 真正多策略 | 7天 | K2/K3后 |
| 11 | GA3 诊断Agent | AI闭环反馈 | 5天 | GA2后 |
| 12 | I2 因子正交化监控 | 预警因子趋同 | 1天 | 随时 |
| 13 | K5 暴力枚举Layer 3-4 | 零成本因子扩展 | 2天 | 随时 |
| 14 | H1 TWAP拆单 | 滑点降50%+ | 3天 | QMT稳定后 |
| 15 | GA4+GA5 AutoRouter+LLM | 完整AI闭环 | 6天 | GA3后 |
| 16 | J1 实验追踪 | 研究效率 | 2天 | 随时 |
| 17 | I1 宏观择时 | 系统性风险 | 5天 | G1后 |
| 18 | H2 TCA归因 | 理解真实盈利 | 2天 | QMT积累数据后 |
| 19 | G6 联合迭代 | 因子+模型协同 | 7天 | G1后 |
| 20 | I5 对抗过拟合 | DSR/CPCV | 5天 | G1后 |
| 21 | L7 实盘反馈循环 | 校准SimBroker | 3天 | QMT 2周后 |
| 22 | K6 另类数据 | 新信号维度 | 5-7天 | K4后 |
| 23 | K7 跨市场信号 | MODIFIER信号 | 5天 | K4后 |
| 24 | L1 模型重训自动化 | 适应市场变化 | 5天 | G1后 |
| 25+ | 其他I/J/K/L项 | 长期持续 | 各项 | 按需 |

### 总工时估算（v3.1更新）

| Phase | 工时 | 状态 |
|-------|------|------|
| A-F | ~69天 | ✅ 已完成 |
| G 组合升级+ML+DSR | ~25天 | G2✅ G2.5⏳ 其他⬜ (v3.1: +G7动态权重+G8 DSR) |
| GA AI闭环管道 | ~30天 | ⬜ (v3.1: +Experience Memory+RAG+算子扩展+Alpha158) |
| H 执行优化 | ~8天 | ⬜ |
| I 风险升级 | ~19天 | ⬜ (含I5对抗过拟合) |
| J 研究效率 | ~11天 | ⬜ |
| K Alpha多元化 | ~40天 | ⬜ (v3.1: +K9 GP三目标) |
| L 基础设施 | ~33天 | ⬜ (含L7实盘反馈闭环) |
| **总计** | **~235天** | 并行可压缩到~5个月 |

---

## 第七部分: 行业对标参考（v3更新）

| 能力 | Qlib | RD-Agent | vnpy 4.0 | FinRL | QuantMind V2 |
|------|------|---------|----------|-------|-------------|
| 因子研究 | ⭐⭐⭐ Alpha158 | ⭐⭐⭐ 自动挖掘 | ⭐ Alpha模块 | ✗ | ⭐⭐⭐ 37因子+GP+LLM+暴力枚举 |
| ML模型 | ⭐⭐⭐ 15+模型 | ⭐⭐⭐ 联合优化 | ⭐⭐ LightGBM | ⭐⭐ PPO/SAC | ⭐ LightGBM(未上线,G1) |
| 回测引擎 | ⭐⭐ 简化版 | 用Qlib | ⭐⭐⭐ 完整 | ⭐⭐ Gym | ⭐⭐⭐ Hybrid+A股特化 |
| 多策略 | ⭐ 单策略 | ⭐ 单策略 | ⭐⭐⭐ 多策略 | ⭐ | ⭐⭐ 框架就绪未启用(K4) |
| 事件驱动 | ✗ | ✗ | ⭐⭐⭐ | ✗ | ✗ (GA2补全) |
| 实盘执行 | ✗ | ✗ | ⭐⭐⭐ 多broker | ✗ | ⭐⭐ miniQMT(刚切换) |
| 风控 | ⭐ 基础 | ✗ | ⭐⭐ 完整 | ⭐ | ⭐⭐⭐ L1-L4+盘中 |
| AI闭环 | ⭐ | ⭐⭐⭐ RD循环 | ✗ | ✗ | ⭐⭐ 零件就绪未串联(GA) |
| A股特化 | ⭐⭐ CN数据 | ⭐⭐ CSI500 | ⭐⭐⭐ 本土 | ✗ | ⭐⭐⭐ 涨跌停/T+1/整手 |

---

## 第八部分: 关键工作原则

1. **不靠猜测做技术判断** — 外部API/数据接口必须先读官方文档确认
2. **数据源接入前过checklist** — 读TUSHARE_DATA_SOURCE_CHECKLIST.md
3. **做上层设计前验底层假设** — 一行SQL能验证的不要假设
4. **每个模块完成后自动化验证** — 回测确定性/数据一致性/单元测试
5. **不要在一个方向上越挖越深** — 先多元化alpha来源, 再深耕每个方向
6. **PT保护** — 生产执行链路代码不改, 所有研究在离线环境
7. **NAV数据源** — QMT query_asset()["total_asset"], 不自行计算
8. **因子预处理顺序** — winsorize → fill → neutralize → z-score
9. **回测可信度硬规则** — can_trade()涨跌停, floor()整手, T+1资金, Bootstrap CI, 成本敏感性
10. **论文建议不盲目套用** — 每条学术建议需批判性分析是否适用于我们的数据量/策略类型/市场环境(v3.1新增)
11. **代码级利用开源项目** — 参考设计理念不够, 必须有代码级集成才算"利用"(v3.1新增)

---

## 第九部分: 回测协议（v3.1新增, 基于Arnott-Harvey-Markowitz 2019）

> **论文**: "A Backtesting Protocol in the Era of Machine Learning"
> **作者**: Rob Arnott, Campbell R. Harvey, Harry Markowitz
> **期刊**: Journal of Financial Data Science, 2019, 1(1), 64-74
> **核心观点**: ML工具强大但在金融中极易过拟合。金融数据量远少于ML早期成功领域(物理/生物), 需要严格的回测协议避免投资于假阳性策略。

### 论文7条建议 vs QuantMind执行状态

| # | 论文建议 | 我们的状态 | 落地方案 |
|---|---------|-----------|---------|
| 1 | 投资想法需先验经济学基础 | ✅ 5因子都有经济学逻辑 | Gate G1要求每个因子必须有hypothesis字段 |
| 2 | 多重检验必须校正 | ⚠️ Gate有BH-FDR, 但Sharpe未做DSR | G8: 对0.91做DSR校正 |
| 3 | 样本选择需记录合理化 | ❌ 2021-2026区间无正式理由 | 在CLAUDE.md中记录: 选2021起因为WLS中性化从此日期生效 |
| 4 | 避免选择偏差(从多策略中挑最优) | ❌ Sharpe=0.91未做DSR | G8: 估计effective N后计算DSR |
| 5 | 参数变更后需观察期 | ⚠️ PT 60天覆盖, 但中途改因子无冷却期 | 新增规则: 因子池变更后最少30天不动 |
| 6 | ML复杂度要严格限制 | ✅ LightGBM max_depth≤3 | G1设计中已规定 |
| 7 | 大部分实验会失败是正常的 | ✅ Sprint 1.5 8/10 FAIL | 继续保持 |

### 批判性分析（不盲目套用）

| 方法 | 论文建议 | 我们的批判 | 结论 |
|------|---------|-----------|------|
| DSR | 直接套公式 | 假设试验独立, 但我们的配置间高度相关。effective N可能只有5-8而不是15-20 | 做DSR但先估effective N, 避免过度惩罚 |
| CPCV | 替代Walk-Forward | 60个月分6段每段10个月, Sharpe标准误差≈0.32, CPCV不比WF更可靠 | 数据积累到100+月再做, 当前用WF足够 |
| Bonferroni | 严格t-stat>3.0 | 太保守, 会踢掉有经济学逻辑的因子(turnover/reversal) | 用BH-FDR(已在Gate G3), 不用Bonferroni |
| HRP | 替代简单风险平价 | 需要协方差矩阵, 20只股票×60天估计不稳定 | G2已证明权重优化走不通, 不做HRP |
| Meta-Labeling | 预测信号置信度 | "置信度"标签定义不清晰, 实操复杂 | Phase 4再考虑, 当前不做 |

---

## 第十部分: 前沿研究对标（v3.1新增）

### 2025-2026年AI量化前沿论文

| 论文 | 机构 | 会议/期刊 | 核心贡献 | 对QuantMind的价值 | 对应Phase |
|------|------|---------|---------|-----------------|----------|
| **FactorMiner** | 清华 | Preprint 2026-02 | Ralph Loop(retrieve→generate→evaluate→distill) + Experience Memory(成功模式+禁区) + 60+算子 | GA3诊断Agent参考Experience Memory, GA6算子扩展 | GA3/GA6 |
| **AlphaForge** | AAAI 2025 | AAAI | 生成式神经网络挖因子 + 动态因子组合权重(每日重新评估Factor Zoo) | G7动态因子权重参考 | G7 |
| **Alpha-GPT** | HKUST 2025 | EMNLP Demo | 人机交互Alpha挖掘 + 分层RAG从因子库检索构建prompt | GA5分层RAG参考 | GA5 |
| **QuantaAlpha** | SUFE 2026-02 | Preprint | LLM自进化因子挖掘框架, 开源可复现 | 可直接参考代码实现 | GA |
| **AlphaAgent** | KDD 2025 | KDD | 正则化探索对抗Alpha衰减, CSI500上IC稳定0.02-0.025持续4年 | Alpha衰减管理参考 | C3/GA3 |
| **RD-Agent(Q)** | CMU/MSRA NeurIPS 2025 | NeurIPS | 因子+模型联合优化(Co-STEER), 5单元自动化 | G6联合迭代框架参考(已在设计中) | G6 |
| **Dynamic GP+LightGBM** | Comp. Economics 2026 | 期刊 | GP三目标适应度 + 滚动窗口 + LightGBM, CSI300 Sharpe 1.59 | K9 GP三目标适应度, G1 LightGBM集成 | K9/G1 |
| **AI in Quant Survey** | HKUST 2025-03 | Survey | Alpha策略三阶段演进: 手动→DL→LLM Agent | 确认我们处于DL→Agent过渡期方向正确 | 全局 |

### 已讨论但0个代码级利用的开源项目

| 项目 | 可利用部分 | 落地方案 | 对应Phase |
|------|-----------|---------|----------|
| **Qlib Alpha158** | 158个因子公式 | GA7: 批量翻译→IC筛选→入候选池 | GA7 |
| **PandaFactor算子库** | RSI/MACD/KDJ/ATR等30+技术指标 | GA6: 移植到FactorDSL | GA6 |
| **RD-Agent Co-STEER** | Research→Dev→Feedback循环 | G6: 联合迭代框架参考实现 | G6 |
| **QuantaAlpha** | 完整LLM因子挖掘框架(开源) | GA3/GA5: 参考其Agent实现 | GA |
| **Alphalens** | 因子分析tearsheet | 替代自建FactorAnalyzer(减少维护) | J5 |
| **QuantStats** | 策略绩效HTML报告 | 替代自建performance指标(减少维护) | J1 |

---

## 第十一部分: 实盘反馈闭环详细设计（v3.1新增, 扩展L7）

> QMT模拟盘4/2首次建仓, 需要系统性利用真实交易数据, 不能只看NAV。

### 数据收集（自动, 每日对账时写入）

| 数据 | 来源 | 用途 |
|------|------|------|
| fill_price vs signal_price | trade_log | 真实滑点 = \|fill_price - signal_price\| / signal_price |
| fill_time | QMT回调 | 成交时间分布(集合竞价 vs 连续交易) |
| partial_fill_rate | QMT回调 | 部分成交率(小盘股可能只成交一部分) |
| 持仓期日内波动 | QMT盘中监控 | max_intraday_drawdown(止损策略依据) |
| QMT NAV vs SimBroker NAV | 对比 | SimBroker参数校准 |

### 分析（每周自动生成报告）

| 分析项 | 方法 | 落地影响 |
|------|------|---------|
| 真实滑点分布 | 按市值/行业/成交额分层统计 | 更新volume_impact模型参数(当前k_small=0.15可能过高) |
| 920北交所股票滑点 | 单独统计(之前发现200-400bps) | 如果持续>100bps → 在universe中过滤 |
| SimBroker vs QMT偏差 | 每日NAV对比, 累积偏差趋势 | 如果偏差<5% → SimBroker可信; 偏差>10% → 必须校准 |
| 因子选股质量 | 买入股票的实际N日收益 vs 全市场 | 确认因子在实盘中真的有选股能力 |
| 执行时机 | 09:31买入 vs 当日收盘价 | 如果开盘买入系统性亏损 → 考虑改到盘中TWAP |

### 校准（月度）

1. 用累积2-4周的真实滑点数据, 重新拟合volume_impact模型的k_large/k_mid/k_small参数
2. 用校准后的参数重跑5年回测, 看Sharpe是否显著变化
3. 如果校准后Sharpe与0.91差异>10% → 更新基线

**实现**: `scripts/weekly_trading_analysis.py`, 每周末自动运行, 输出Markdown报告到docs/trading_reports/

---

## 第十二部分: 第一周落地行动计划（v3.1新增）

> 把路线图从"纸上谈兵"变成"这周做什么"。

### 本周（4/2 - 4/6, 含清明假期4/4-6）

| 日期 | 任务 | 产出 | 工作量 |
|------|------|------|--------|
| 4/2(今天) | G2.5动态仓位验证(正在跑) | Sharpe/MDD数字 | 等结果 |
| 4/3 | 验证QMT调度链路(09:31执行/15:10对账/17:00 moneyflow) | 链路确认 | 观察 |
| 4/3 | G8 DSR校正(对0.91做DSR) | "原始0.91, DSR校正后X.XX" | 2小时 |
| 4/3 | G3风格归因(Fama-French回归) | alpha是真选股还是小盘beta | 半天 |
| 4/4-6 | 清明假期: 验证交易日历检查(所有脚本跳过) | 确认假期无误触发 | 观察 |
| 4/4-6 | K0因子资产盘点(离线跑) | 完整因子清单表 | 半天 |

### 下周（4/7 - 4/11）

| 日期 | 任务 | 产出 |
|------|------|------|
| 4/7 | G2.5结果分析+部署决策 | 如果有效→部署到PT |
| 4/7-8 | GA7 Alpha158批量导入+IC筛选 | 60-80个新候选因子 |
| 4/8-9 | G4因子正交化+G5分市值层分析 | 深入理解策略alpha来源 |
| 4/9-11 | GA2 EVENT回测器开始编码 | EVENT框架骨架 |
| 4/11 | 第一周QMT交易分析 | 真实滑点/fill率报告 |

### 第三周（4/14 - 4/18）

| 任务 | 产出 |
|------|------|
| GA2 EVENT回测器完成 | mf_divergence/PEAD用EVENT框架重测 |
| G1 LightGBM启动 | Optuna超参搜索开始 |
| GA1 StrategyMatcher | 因子分类→回测配置自动映射 |

---

## 第八部分(续): 关键工作原则（完整版）

*(保留原有9条, 新增10-11条见上方)*

---

*本文档是QuantMind V2的完整技术路线图v3.1。*
*Phase A-F已完成, G2已完成(无效), G2.5进行中。*
*v3.1核心新增: 前沿AI研究对标(FactorMiner/AlphaForge/Alpha-GPT), Experience Memory, 动态因子权重, DSR回测校正, FactorDSL算子扩展, Alpha101/158导入, 实盘反馈闭环, 第一周落地行动计划。*
*v3核心变化: 基线修正(0.91/-43%), AI闭环管道(Phase GA), 多策略架构, 风格归因, Alpha多元化优先。*
*QMT模拟盘4/2首次建仓, PT天数从此日重新计算。*
*回测协议参考: Arnott, Harvey, Markowitz (2019) "A Backtesting Protocol in the Era of Machine Learning", JFDS 1(1), 64-74.*
