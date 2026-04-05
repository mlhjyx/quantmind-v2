# QuantMind V2 — 修复+升级+架构演进 落地文档

> **版本**: 3.4 | **日期**: 2026-04-04
> **基于**: v3.3 + GA2 EVENT回测完成 + mf_divergence IC证伪 + 评估范式转移 + 前沿论文全面对标
> **当前状态**: QMT模拟盘live模式, 4/2首次建仓, 初始≈¥1,000,752, 当前15只持仓NAV≈¥958,684, PT Day 2
> **核心基线**: Sharpe=0.91 (保守估计0.70-0.85), MDD=-43%, Alpha=21.1%/年(t=2.45), SMB beta=0.83
> **新最优配置(已部署)**: Top-20+无行业约束+PMS阶梯利润保护 → Sharpe=1.15, MDD=-35.1%, Calmar=0.83
> **v3.3→v3.4核心变化**: 评估范式转移(单因子IC→模型OOS驱动, G1升⭐5), GA2完成(引擎✅但mf_divergence IC=9.1%证伪为-2.27%), GA6降优先级(28→40非55+, code-based并行), GP启动条件+1(G1完成), 铁律11(IC可追溯性), 原则15(结论传播标注), 前沿论文8→15篇分三层对标

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
| mf_divergence(IC=9.1%)被月度框架冤杀 | ~~LL-027~~ **GA2证伪(v3.4)** | ⚠️ **IC=9.1%是幽灵数据, 实际IC=-2.27%。不是被冤杀, 本来就没什么alpha。详见GA2完成记录** |
| PEAD(IC=5.34%)被月度框架冤杀 | LL-027 | 需先用铁律11验证IC真实性, 再决定是否EVENT回测(v3.4更新) |
| LLM自由生成因子失败(IC=0.006-0.008) | W7b 5次测试 | 需数据驱动prompt, 不是盲猜 |
| 动态仓位(20d momentum): Sharpe 0.32→1.76, MDD -28%→-11.4% | 旧代码验证 | 效果极好但需在新基线上重新验证(G2.5) |
| QMT真实滑点47.6bps, SimBroker预估176.7bps(高估3.7x) | 实盘数据 | 5000万流动性过滤不必要 |
| **mf_divergence IC=9.1%是幽灵数据, 实际-2.27%** | **GA2验证(v3.4)** | **从未入库factor_ic_history, 错误数字驱动GA2⭐2优先级数月。铁律11由此诞生** |
| **Alpha158集成回测: 7因子Sharpe+0.11但p=0.24不显著** | **GA7集成回测(v3.4)** | **等权天花板第3次独立验证(Sprint1.5+PEAD+Alpha158)** |
| **所有2025-2026论文用ML模型评估因子, 非单因子IC** | **15篇前沿论文对标(v3.4)** | **评估范式转移: G1 LightGBM是正确评估一切的前提** |

### GA2 EVENT回测器 — 已完成 ✅（v3.4）

> **日期**: 2026-04-04 | **commit**: `147b345` | **tag**: `ga2-event-backtest`

**交付物:**
| 组件 | 文件 | 状态 |
|------|------|------|
| EVENT回测引擎 | `backend/engines/event_backtest_engine.py` (357行) | ✅ |
| 单元测试 | `backend/tests/test_event_backtest.py` (9/9通过) | ✅ |

**引擎能力:** 事件触发(因子超阈值→T+1买入→持有N天→自动卖出), A股处理(T+1/涨跌停/停牌顺延/整手), 成本模型(佣金万0.854+印花税0.05%+过户费万0.1)

**mf_divergence验证结论:**

| 项目 | 声称的 | 实际的 |
|------|--------|--------|
| IC值 | 9.1% | **-2.27%** (20d, 中性化后) |
| IC方向 | 未知(默认above) | **below** (高因子值→低收益) |
| IC来源 | factor_ic_history | **不存在，从未入库** |
| IR | 未知 | -0.76 (t=-5.68, 显著) |

**回测结果(14组, 实际独立4组):** above全负Sharpe(-1.67/-1.00), below全负Sharpe(-0.57/-0.06)。阈值不影响结果(max_positions每天饱和)。

**决策:**
- mf_divergence不适合独立策略, 保留在G1 LightGBM特征池
- "LL-027被冤杀"叙事推翻——mf_divergence本来就没alpha, 两种框架给出一致答案
- GA2引擎功能验证通过, 后续PEAD/RSRS可用
- PEAD需先验证IC(铁律11)再决定是否回测

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
| RESERVE | 1 | vwap_bias(rsrs_raw待EVENT重测) |
| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非此前声称的9.1%, v3.4确认) |
| DEPRECATED | 8 | momentum_5/10, turnover_stability_20等(冗余或IC衰减) |
| ML特征 | 12 | zscore clip ±3已修复 |
| LGBM特征集(v3.4) | **48+** | 全部factor_values有数据的因子(37历史+8 Alpha158+数据质量修复), 替代v3.3的26个设计 |
| factor_values有数据 | **48** | DB中实际有数据的因子(v3.3从37扩展到48) |

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
| **v3.4优先级** | **⭐5 最高** — 评估范式转移的核心。所有2025-2026论文(QuantaAlpha/AlphaAgent/RD-Agent/FactorMAD/Chain-of-Alpha)无一例外用ML模型做最终因子评估。没有G1, 新因子无法被正确评估——等权天花板已到(Sprint 1.5 + PEAD + Alpha158三次独立验证) |
| **v3.4特征池** | 48+因子就绪(37历史+8 Alpha158+数据质量修复后), 比Sprint 1.3b(26特征)多85% |
| **v3.4 fail-fast** | OOS Sharpe<基线×1.2且p>0.05→ML在当前数据上没有增量, 需重新审视方向 |

#### G1.1 预测目标升级 — 回归→LambdaRank（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | 将LightGBM目标从回归(MSE)改为LambdaRank排名优化(NDCG) |
| **理由** | 我们关心的是"哪只股票排名更高"而非"绝对收益预测多准"。回归模型MSE小但排名不一定好，LambdaRank直接优化排名质量 |
| **验证** | 对比回归目标vs排名目标的OOS选股Sharpe |
| **估时** | 1天 |
| **依赖** | G1完成 |

#### G1.2 时序特征增强（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | 当前模型只用当月因子截面值，增加时序维度特征 |
| **新增特征** | 因子变化率(delta_factor_1m)、因子加速度(delta2_factor_1m)、最近3个月因子值堆叠、因子自身动量(因子均值回归/趋势信号) |
| **理由** | 当前模型只看"这个月turnover=0.8"，看不到"连续3个月turnover加速上升"这个趋势信号。一个股票因子在变好还是变差，比当前绝对值更有信息量 |
| **估时** | 1天 |
| **依赖** | G1完成 |

#### G1.3 XGBoost + CatBoost同架构训练（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | 用G1相同的特征集和Walk-Forward框架训练XGBoost和CatBoost |
| **理由** | 三种GBDT实现细节不同(正则化/分裂算法/类别特征处理)，同数据下产出不同预测，集成减少方差 |
| **CatBoost优势** | 原生支持类别特征(行业编码)，不需要one-hot编码 |
| **估时** | 1-2天 |
| **依赖** | G1完成 |

#### G1.4 三模型Ensemble（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | LightGBM + XGBoost + CatBoost集成：简单平均 → OOS表现加权平均 |
| **预期** | Sharpe +0.05-0.10(减少单模型方差，ML界最确定的结论之一) |
| **验证** | Ensemble vs 单LightGBM的OOS Sharpe + paired bootstrap |
| **确定性** | 高——GBDT Ensemble是行业标准做法 |
| **估时** | 半天 |
| **依赖** | G1.3完成 |

#### G1.5 分位数回归 — 预测不确定性（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | LightGBM quantile regression输出收益分布(10%/50%/90%分位)，用预测不确定性调整仓位权重 |
| **理由** | 等权分配忽略了模型信心差异。高信心股票应给更多权重，低信心的给更少 |
| **备选方案** | NGBoost(直接输出分布参数)、Conformal Prediction(模型无关的校准区间)、多模型离散度(3个GBDT预测值标准差作为不确定性代理) |
| **估时** | 2天 |
| **依赖** | G1.4完成 |

#### G1.6 MLP基线 + 四模型Stacking（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | 2-3层MLP(dropout 0.3, batch norm)作为第四个base模型，然后用线性模型做Stacking |
| **理由** | MLP是连续平滑函数，与GBDT的分段常数函数互补。Stacking让不同模型长处融合 |
| **风险** | 60个月独立截面可能不够训练NN，需严格正则化。tabular数据上MLP常不如GBDT |
| **触发条件** | 特征池80+且G1.4 Ensemble确认有效后才做 |
| **估时** | 5天 |

#### G1.7 Regime感知模型切换（v3.3新增）

| 属性 | 值 |
|------|------|
| **任务** | 多个模型+regime检测器动态切换权重 |
| **理由** | 2021/2025小盘牛市和2022/2024熊市的最优模型参数不同，一个模型覆盖所有环境是妥协 |
| **实现** | regime指标(市场宽度/波动率水平/动量) → 根据当前regime选择近期类似regime下OOS最好的模型权重 |
| **风险** | regime分类本身可能过拟合，需Walk-Forward验证regime切换收益 |
| **估时** | 5-7天 |
| **依赖** | G1.4完成，且回测证明不同regime下最优模型确实不同 |

#### G2. 风险平价替代等权 ✅ 已完成 — 结论：无效

> 见第二部分研究记录。权重优化走不通，回撤控制应靠总仓位管理。

#### G2.5 动态仓位验证 ✅ 已完成 — 结论：无效

| 属性 | 值 |
|------|------|
| **任务** | 在当前基线(Sharpe=0.91)上验证动态仓位(20d momentum, 100/50/0三档) |
| **机制** | 20d全市场等权平均收益: >0满仓, <0半仓, <-10%空仓 |
| **与vol_regime的区别** | vol_regime看波动率水平(高波降仓→但Alpha在高波动期最强→无效)。动态仓位看收益方向(下跌期降仓, 上涨期满仓, 无论波动率高低) |
| **旧代码结果** | Sharpe 0.32→1.76, MDD -28%→-11.4%(不同基线, 需重新验证) |
| **预期** | Sharpe 1.2-1.5, MDD -15%~-25% |
| **估时** | 1天 |
| **状态** | ✅ 已完成 — Sharpe不变CAGR大降, 无效 |

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
| 任务数 | 16 (G1+G1.1~G1.7+G2✅+G2.5✅+G3✅+G4-G8) |
| 总估时 | ~45天(含G1.1-G1.7新增~17天, 扣除已完成的G2/G2.5/G3/G8) |
| 预期收益 | ML从单LightGBM→三GBDT Ensemble→Stacking, 预期Sharpe +0.1-0.2。Regime感知解决2022/2024熊市适应性问题 |

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

#### GA2. EVENT回测器 ✅ 已完成（v3.4, 引擎验证通过, mf_divergence无效）

| 属性 | 值 |
|------|------|
| **状态** | ✅ 引擎功能验证通过(357行+9/9测试), mf_divergence验证: IC=9.1%证伪为-2.27%, 全配置负Sharpe |
| **v3.4认知修正** | v3.3升为⭐2的依据是"mf_divergence IC=9.1%被冤杀"——该依据已被证伪。引擎本身有价值但紧迫性回归正常, 当前无高IC的EVENT因子等待释放 |
| **后续** | PEAD待验证(先用铁律11确认IC真实性), RSRS同理 |
| **commit** | `147b345` tag: `ga2-event-backtest` |

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
| **v3.4优先级调整** | **⭐1 降低** — FactorMAD(ICAIF 2025)证明code-based因子生成可绕过DSL算子限制。Alpha158已走这条路(158个pandas函数不走FactorDSL)。范围缩小: 28→40(非55+), 同时新增并行实验: GA5扩展LLM code-based因子生成 |

#### GA7. Alpha101/158因子公式批量导入 ✅ 已完成（v3.3）

| 属性 | 值 |
|------|------|
| **任务** | 从Qlib Alpha158公式集中提取因子, 翻译成pandas函数, 批量IC筛选 |
| **结果** | 158公式 → 128实际计算(13分钟) → 102通过IC → 23内部去重 → 8个独立新因子入池 |
| **入池因子** | STD60, VSUMP60, CORD30, RANK5, CORR5, VSTD30, VSUMP5, VMA5 |
| **分类** | 4个RANKING(月度) + 4个FAST_RANKING(待GA2正确框架评估) |
| **代码** | `alpha158_factors.py`(158个pandas实现), `compute_alpha158_ic.py` |
| **commit** | `a5ea6f6` tag: `alpha158-import` |

#### Phase GA 汇总

| 指标 | 值 |
|------|------|
| 任务数 | 7 (GA1⬜, GA2✅, GA3-GA6⬜, GA7✅) |
| 总估时 | ~22天(扣除GA2+GA7已完成) |
| 预期收益 | 因子挖掘从手动变自动, LLM从盲猜变数据驱动, 搜索空间扩展 |
| **v3.4关键修正** | GA2完成但mf_divergence无效, 推翻了"冤杀"叙事。评估层瓶颈的真正解决方案不是GA2(EVENT回测器)而是G1(ML模型评估)——所有2025-2026论文都用ML模型而非单因子IC做最终评估。GA6降为⭐1, 范围缩小28→40(非55+) |

#### GP零产出根因分析（v3.3新增）

> GP管道D1-D4代码全部建好（标记✅）但从未产出一个生产因子，根因分析：

| # | 根因 | 说明 |
|---|------|------|
| 1 | **搜索空间太小** | FactorDSL仅28算子, 暴力枚举9秒就能覆盖, GP无用武之地 |
| 2 | **适应度太简单** | 单一IC目标, 高IC因子可能与现有因子高相关或MDD大 |
| 3 | **缺少Warm Start** | 随机种群效率极低, Ren et al. 2024证明Warm Start效果远超随机(>50%年化, Sharpe>1.0) |
| 4 | **评估层偏差** | 即使GP搜到EVENT型因子, 也被塞进月度框架→失败→GP学到错误方向(GA2不建此问题无解) |
| 5 | **从未真正运行** | 每个Sprint都有更紧急的事, GP始终排在最后被挤掉 |

**GP启动条件（全部满足后再跑）**:
1. ✅ GA7 Alpha158完成 → 提供算子实现基础
2. ⬜ GA6 算子扩展28→55+ → 搜索空间从~2万→~900万
3. ⬜ 三目标适应度: 0.5×RankIC + 0.3×ICIR − 0.15×max_corr_existing − 0.05×complexity
4. ⬜ Warm Start: 20%现有因子结构变体 + 20%Alpha158变体 + 60%随机half-and-half
5. ⬜ GA2 EVENT回测器就绪 → GP产出不再被错误评估
6. ⬜ GA1 StrategyMatcher就绪 → 自动路由到正确回测框架
7. ⬜ G1 LightGBM完成 → 新因子用ML模型OOS评估, 不再依赖等权IC天花板(v3.4新增, 所有2025-2026论文共识)

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
| **任务** | RSRS用EVENT触发框架, VWAP用FAST_RANKING(周度), mf_divergence已确认无效(v3.4, IC=-2.27%非9.1%) |
| **历史** | 全部通过单因子Gate但在月度等权框架下失败 |
| **依赖** | GA1(StrategyMatcher) + GA2(EVENT回测器) |
| **估时** | 3天 |

#### K4. 多策略叠加回测

| 属性 | 值 |
|------|------|
| **任务** | CompositeStrategy(C6)框架下实现真正的多层策略 |
| **架构** | 核心层(60-70%, RANKING月度Top-N) + 增强层(20-30%, EVENT触发PEAD/RSRS, 待IC验证) + 防御层(MODIFIER, 动态仓位调总仓位) |
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

#### I6. PMS持仓管理系统（v3.2新增, 高优先级）

> **核心洞察**: 月度调仓只管"选什么股"，不管"持仓期间出了意外怎么办"。
> MDD=-43%的一部分原因是持仓期间个股暴跌20-30%但系统等到月底才处理。
> PMS不是独立项目，是QuantMind前端一级菜单页面+后端功能模块。

**分阶段实现:**

| 版本 | 内容 | 工作量 | 前提 |
|------|------|--------|------|
| **v1.0** | 硬止损(-20%固定阈值) + 钉钉告警 + 前端基础页面 | 2-3天 | 实时架构(L8)就绪 |
| **v2.0** | 阶梯式利润保护(盈利>30%→回撤保护15%, >20%→12%, >10%→10%) + 组合级回撤保护(连续3日>10%→半仓) | 3-5天 | v1.0回测验证有效 |
| **v3.0** | 观察名单+条件回补 + 异常事件分类(个股利空/行业联动/大盘系统性/流动性冲击) + 按策略配置不同规则集 | 5-7天 | v2.0 + 积累足够数据 |

**PMS架构（嵌入现有系统，不独立）:**
```
前端: 一级菜单"Position Manager"页面
  ├─ 实时持仓利润看板(买入价/最高价/当前利润/保护线位置)
  ├─ 观察名单(止损卖出后的候选股+状态+回补条件)
  ├─ 规则配置(3个预设模式:保守/平衡/激进，高级自定义)
  ├─ 触发记录(今日哪些规则被触发+执行了什么)
  └─ 历史统计(止损次数/回补成功率/利润保护效果)

后端:
  backend/services/pms_engine.py    ← 核心逻辑(从Redis读行情)
  backend/routers/pms.py            ← API端点
  不新建独立服务，从Redis Streams读取行情数据

数据流: QMT → Redis Streams → PMS引擎 → 止损指令 → Redis → QMT执行
```

**回测验证（v1.0前必须做）:**

| 实验 | 止损阈值 | 预期验证 |
|------|---------|---------|
| A | 不止损(基线) | Sharpe=0.91, MDD=-43% |
| B | -15% | 频繁止损，可能Sharpe下降 |
| C | -20% | 平衡点 |
| D | -25% | 只防极端事件 |
| E | 利润保护(阶梯式) | v2.0预验证 |

**关键风险: "处置效应"** — 利润保护可能系统性卖掉波动大但因子打分高的强势股，留下温吞的中间股。需验证止损后持仓平均因子打分是否下降。

| **估时** | v1.0: 2-3天, v2.0: 3-5天, v3.0: 5-7天 |
| **依赖** | L8实时架构完成 |

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
| L8 | **实时架构: Redis Streams + QMT数据服务(v3.2新增)** | **3天** | **清明假期4/4-6** |
| L9 | **NSSM→Servy迁移(v3.2新增)** | **含在L8中** | **清明假期4/4** |
| L10 | **分钟数据聚合因子(v3.2新增)** | **3-5天** | **QMT xtdata验证后** |

#### L8. 实时架构: Redis Streams统一数据总线（v3.2新增, 极高优先级）

> **核心问题**: 当前系统碎片化——QMT/FastAPI/Celery/6+定时脚本各自为政，
> 没有统一的实时数据层。每个脚本各自import xtquant连QMT，各自建DB连接。
> PMS需要实时行情但现有架构不支持主动推送。

**统一架构:**
```
┌──────────────────────────────────────────────────────┐
│              Redis Streams 实时数据总线                │
│                                                      │
│  Streams:                                            │
│    market:ticks        ← QMT数据服务推送实时行情        │
│    trade:commands      ← PMS/信号引擎发交易指令         │
│    trade:results       ← QMT回报执行结果               │
│    pms:events          ← 止损/利润保护触发事件          │
│                                                      │
│  Key-Value缓存:                                      │
│    market:latest:{code} ← 最新价格(TTL=60s)           │
│    portfolio:current    ← 当前持仓                    │
│    portfolio:nav        ← 最新NAV                    │
│    pms:watchlist        ← 观察名单                    │
│    system:status        ← 系统状态                    │
└────────┬─────────┬──────────┬──────────┬─────────────┘
         │         │          │          │
  QMT数据服务  FastAPI后端   PMS引擎    前端WebSocket
  (唯一QMT    (API+WS推送) (风控逻辑)  (实时展示)
   连接点)
```

**QMT数据服务(qmt_data_service.py, 独立常驻进程):**
- 唯一的QMT连接点，所有其他组件不再直连QMT
- 订阅持仓股票实时行情 → 写入Redis Streams
- 监听Redis交易指令 → 转发给QMT执行 → 回报写回Redis
- 每分钟同步: query_stock_positions() + query_asset() → Redis缓存

**其他组件改造:**
- run_paper_trading.py: 交易指令写Redis，不直连QMT
- daily_reconciliation.py: 从Redis读持仓/NAV
- intraday_monitor.py: 合并到PMS引擎（不再独立运行）
- FastAPI: 订阅Redis事件 → WebSocket推送前端（实时，不再30秒轮询）
- 所有脚本删除import xtquant（只有qmt_data_service使用）

**fallback机制:** PMS读Redis超时2秒时，fallback到直连xtquant查价格

**为什么用Redis Streams而非其他方案:**

| 方案 | 适合度 | 原因 |
|------|--------|------|
| **Redis Streams** | ⭐⭐⭐⭐⭐ | 已在系统中(Celery broker), Streams持久化解决消息丢失, 同时提供缓存 |
| Redis Pub/Sub | ⭐⭐⭐⭐ | 消息不持久，离线消费者丢消息 |
| ZeroMQ | ⭐⭐⭐ | 性能过剩(6x Redis)但无缓存能力，需自建状态管理 |
| NATS | ⭐⭐⭐ | 优秀但引入新依赖不值得(每分钟15条tick不需要高性能) |
| shared_memory | ⭐⭐ | 太底层，Windows上multiprocessing有坑 |
| PostgreSQL NOTIFY | ⭐⭐⭐ | 事件通知可以但实时行情不应过DB |

| **估时** | 3天(含在清明改造中) |
| **优先级** | 极高——PMS的前提条件 |

#### L9. NSSM→Servy迁移（v3.2新增）

> NSSM超过10年未更新，不支持--reload、无健康检查、无实时监控。
> Servy是现代替代品：GUI+CLI+PowerShell、健康检查、自动恢复、服务依赖管理。

**Servy管理的服务（有依赖顺序）:**
```
1. Redis           ← 最先启动
2. PostgreSQL      ← 数据库
3. QMT-DataService ← 连接QMT，行情推入Redis Streams
4. FastAPI         ← Web后端
5. Celery-Worker   ← 异步任务
6. Celery-Beat     ← 定时调度
7. PMS-Engine      ← 持仓管理/风控

崩溃恢复: 3秒自动重启，连续3次告警
```

| **估时** | 含在L8清明改造中 |

#### L10. 分钟数据聚合因子（v3.2新增）

> **核心思路**: 用QMT xtdata拉取分钟K线，聚合成日频特征，不改变调仓框架。
> 分钟数据能捕捉日频因子看不到的微观结构（日内成交量分布、价格形态、大单时段等）。

**可行的分钟聚合因子:**

| 因子 | 计算方式 | 捕捉的信息 |
|------|---------|-----------|
| morning_volume_ratio | 开盘1h成交量/全天成交量 | 散户(早盘)vs机构(尾盘)主导 |
| intraday_vol_skew | skew(分钟收益率) | 日内波动是否对称 |
| volume_concentration | std(minute_vol)/mean(minute_vol) | 成交集中放量vs均匀分散 |
| vwap_deviation | (close-VWAP)/VWAP | 收盘价偏离均价程度(精确版) |
| max_intraday_drawdown | max(cumulative drawdown in day) | 日内最大回撤 |

**参考:** 华泰金工"全频段量价融合因子"2025年全A超额20.94%; 方正证券"潮汐因子"; 东吴证券"换手率分布均匀度"

**落地步骤:**
1. QMT xtdata拉1只股票1年分钟数据，验证质量和可用性（1小时）
2. 计算上述5个聚合因子，跑IC对比日频因子（半天）
3. 如果IC显著>0且与日频因子低相关 → 拉Top 500的分钟数据（半天）
4. 批量计算 → 加入G1 LightGBM特征池
5. GPU加速（cuDF/rapids处理大量分钟数据）

| **估时** | 可行性验证1天 + 批量实现3-5天 |
| **依赖** | QMT xtdata确认可用 |

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

### 因子挖掘分层策略（v3.3新增）

> **核心洞察**: 项目实践证明简单低成本方法远超复杂高成本方法。
> 手工5因子+暴力枚举9秒+Alpha158半天 >> LLM ¥1.11零产出+GP管道5天零产出。
> 但GP/LLM的长期价值在于可持续供给，短期用暴力枚举铺量，长期建GP闭环。

#### 第一层: 确定性高、成本低（已完成/进行中）

| 方法 | 产出 | 成本 | 状态 |
|------|------|------|------|
| 手工设计(金融知识) | 5个核心因子 | 0 | ✅ PT在用 |
| 暴力枚举Layer 1-2 | 15个独立因子 | 9秒 | ✅ 完成 |
| Alpha158导入 | 8个独立因子 | 半天 | ✅ 完成(v3.3) |
| 暴力枚举Layer 3跨表 | 预计10-20个 | 半天 | ⬜ 待做 |

#### 第二层: 确定性中等、成本中等（短期可做）

| 方法 | 预期产出 | 成本 | 状态 |
|------|---------|------|------|
| 分钟数据聚合因子(L10) | 5-10个微观结构因子 | 3-5天 | ⬜ 依赖QMT xtdata验证 |
| 另类数据因子(K6) | 5-10个 | 5-7天 | ⬜ 龙虎榜/大宗/股东人数 |
| tsfresh/catch22时序特征 | 不确定 | 半天验证 | ⬜ 可能大部分是噪声，但验证成本低 |

#### 第三层: 长期建设、高价值（中期）

| 方法 | 预期产出 | 成本 | 前提条件 |
|------|---------|------|---------|
| GP进化搜索(55+算子) | 持续产出非线性因子 | 3-5天建设+持续 | GA6算子扩展+三目标适应度+Warm Start+GA2就绪 |
| LLM诊断驱动(GA3+GA5) | 提升GP搜索效率 | 7-10天 | GP先跑通产出因子 |
| 图特征(基金共同持仓等) | 关系维度因子 | 5天 | fund_portfolio数据(季报,滞后3月) |

#### 第四层: 研究探索（长期，需充分验证）

| 方法 | 理论价值 | A股实证 | 建议 |
|------|---------|--------|------|
| 互信息替代IC | 发现非线性因子-收益关系 | 很少 | 先用IC，遇到瓶颈时试 |
| Autoencoder潜在因子 | 自动降维发现模式 | 很少 | 特征池100+后考虑 |
| Double ML因果推断 | 因果效应而非相关性 | 几乎没有 | 学术探索方向 |

---

## 第六部分: 全局路线图

### 依赖关系（v3.3更新）

```
Phase A-F (已完成) + G2✅ + G2.5✅(无效) + G3✅ + G8✅
    │
    ├──→ GA2 EVENT回测器 (⭐2, 闭环评估层瓶颈)
    │    + GA1 StrategyMatcher (⭐3)
    │       ↓
    │    K2+K3 被冤杀因子正确框架重测
    │       ↓
    │    K4 多策略叠加回测
    │
    ├──→ GA6 算子扩展 → GP首次正式运行 (与上面并行)
    │       ↓
    │    GA3+GA4+GA5 (诊断Agent+AutoRouter+LLM数据驱动)
    │       ↓
    │    G6 因子+模型联合迭代
    │
    ├──→ G1 LightGBM Walk-Forward (与上面并行)
    │       ↓
    │    G1.1 LambdaRank → G1.2 时序特征 → G1.3 XGB+Cat
    │       ↓
    │    G1.4 三模型Ensemble → G1.5 分位数回归
    │       ↓
    │    G1.6 MLP+Stacking → G1.7 Regime感知
    │
    ├──→ Phase H (执行优化, QMT积累数据后)
    │
    ├──→ Phase I (风险升级, 与K并行)
    │
    ├──→ Phase J (研究效率, 随时可做)
    │
    └──→ Phase L (基础设施, L8✅L9✅清明完成)
```

### 执行优先级排序（v3.4更新）

| 优先级 | 任务 | 预期收益 | 工作量 | 状态/建议时间 |
|--------|------|---------|--------|---------|
| ~~⭐1~~ | ~~G2.5 动态仓位验证~~ | — | — | ✅ 完成(无效) |
| ~~⭐1~~ | ~~清明架构改造(L8+L9+PMS)~~ | — | — | ✅ 完成(v3.3) |
| ~~⭐2~~ | ~~GA2 EVENT回测器~~ | — | — | ✅ 完成(v3.4, mf_divergence无效) |
| **⭐5** | **G1 LightGBM v1.3** | **评估范式转移核心, 所有论文共识** | 10天 | **4/8立即开始** |
| ⭐3 | GA1 StrategyMatcher | 自动路由因子到正确回测框架 | 2天 | G1后 |
| ⭐2 | GA5 LLM数据驱动prompt + code gen实验 | LLM从盲猜→数据驱动, code-based因子生成 | 5+2天 | G1后 |
| ⭐1 | GA6 算子扩展28→40(非55+) | GP搜索空间扩展, 但范围缩小 | 3天 | GA5后 |
| 6 | GP首次正式运行(三目标+WarmStart) | 持续非线性因子供给 | 3天 | 7项条件全满足后 |
| 7 | K2+K3 PEAD/RSRS重测(先铁律11验IC) | 释放EVENT因子(如果IC验证通过) | 6天 | GA2✅+IC验证后 |
| 8 | G1.1-G1.4 ML模型扩展 | LambdaRank+时序特征+三GBDT Ensemble | 5天 | G1成功后 |
| 9 | K4 多策略叠加 | 核心+增强+防御三层策略 | 7天 | K2/K3后 |
| 10 | GA3+GA4+GA5 AI闭环串联 | 诊断Agent+AutoRouter+LLM数据驱动 | 15天 | GP跑通后 |
| 11 | G1.5-G1.7 ML高级扩展 | 分位数回归+MLP+Regime感知 | 12天 | G1.4后 |
| 12 | K1 行业轮动 | 独立维度alpha | 3天 | 随时 |
| 13 | I2 因子正交化监控 | 预警因子趋同 | 1天 | 随时 |
| 14 | K5 暴力枚举Layer 3-4 | 零成本因子扩展 | 2天 | 随时 |
| 15 | H1 TWAP拆单 | 滑点降50%+ | 3天 | QMT稳定后 |
| 16 | G6 因子+模型联合迭代 | 因子搜索+模型训练交替优化 | 7天 | G1+GP后 |
| 17 | J1 实验追踪 | 研究效率 | 2天 | 随时 |
| 18 | I1 宏观择时 | 系统性风险防御 | 5天 | G1后 |
| 19 | L7 实盘反馈循环 | 校准SimBroker | 3天 | QMT 2周后 |
| 20+ | K6/K7/K8/L1/I5 | 长期持续 | 各项 | 按需 |

### 总工时估算（v3.3更新）

| Phase | 工时 | 状态 |
|-------|------|------|
| A-F | ~69天 | ✅ 已完成 |
| G 组合升级+ML+DSR | ~45天 | G1⬜ G1.1-G1.7⬜(v3.3新增~17天) G2✅ G2.5✅ G3✅ G8✅ |
| GA AI闭环管道 | ~27天 | GA7✅(v3.3) 其他⬜ |
| H 执行优化 | ~8天 | ⬜ |
| I 风险升级 | ~29天 | I6 PMS v1.0✅(v3.3清明) |
| J 研究效率 | ~11天 | ⬜ |
| K Alpha多元化 | ~43天 | K0✅ 其他⬜ |
| L 基础设施 | ~44天 | L8✅ L9✅(v3.3清明完成) |
| **总计** | **~277天** | 并行可压缩到~6个月 |

---

## 第七部分: 行业对标参考（v3更新）

| 能力 | Qlib | RD-Agent | vnpy 4.0 | FinRL | QuantMind V2 |
|------|------|---------|----------|-------|-------------|
| 因子研究 | ⭐⭐⭐ Alpha158 | ⭐⭐⭐ 自动挖掘 | ⭐ Alpha模块 | ✗ | ⭐⭐⭐ 37因子+GP+LLM+暴力枚举 |
| ML模型 | ⭐⭐⭐ 15+模型 | ⭐⭐⭐ 联合优化 | ⭐⭐ LightGBM | ⭐⭐ PPO/SAC | ⭐⭐ LightGBM+XGB+Cat规划(G1.1-G1.7) |
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

## 第十部分: 前沿研究对标（v3.1新增, v3.4大幅扩展+分层重组）

> v3.4变化: 从8篇扩展到15篇, 按落地可行性分三层组织。
> **核心发现: 所有2025-2026年AI因子挖掘论文无一例外用ML模型(LightGBM/XGBoost)做最终评估, 而非单因子IC。这直接支持G1升为⭐5。**

### Tier 1: 直接可落地（有开源代码 + 明确落地方案）

| 论文 | 会议 | 核心贡献 | 对QuantMind的落地方案 | 对应Phase |
|------|------|---------|-------------------|----------|
| **AlphaAgent** | KDD 2025 | AST结构相似度去重 + hypothesis alignment + complexity control, CSI500 IC稳定4年, hit ratio +81% | 抽取AST去重模块加入Gate G8; originality enforcement加入GA3 | GA3/G8 |
| **QuantaAlpha** | Preprint 2026-02 | trajectory-level mutation/crossover进化因子, GPT-5.2 CSI300 IC=0.1501/ARR=27.75%/MDD=7.98% | G1后参考其LightGBM评估框架; GP warm start参考trajectory archive | GA/GP/G1 |
| **FactorMAD** | ICAIF 2025 | 两个LLM通过结构化辩论迭代优化因子, 直接生成可执行代码(不受算子集限制) | GA5扩展: LLM code-based因子生成实验(绕过FactorDSL 28算子限制), 1-2天探索性实验 | GA5/GA6 |

### Tier 2: 设计参考（思路对但不直接用代码, 影响架构设计）

| 论文 | 会议 | 核心贡献 | 设计影响 | 对应Phase |
|------|------|---------|---------|----------|
| **Sortify** | Preprint 2026-03 | Belief/Preference双通道解耦 + LLM元控制器 + 7表Memory DB + 一人AI Agent开发范式(98K行) | GA3双通道设计(IC评估vs约束调整分离); mining_knowledge闭环写入pipeline; IC→Sharpe transfer calibration思路 | GA3/GA5 |
| **FactorMiner** | 清华 Preprint 2026-02 | Ralph Loop + Experience Memory(成功模式+禁区) + 60+算子 | GA3 Experience Memory设计; GA6算子库参考 | GA3/GA6 |
| **Chain-of-Alpha** | Preprint 2025 | 双链架构(Generation多样性 + Optimization有效性), 全自动无人工反馈 | GA4重构: 分离"探索新因子"和"优化已有因子" | GA4 |
| **Alpha-GPT** | EMNLP Demo 2025 | 人机交互Alpha挖掘 + 分层RAG从因子库检索构建prompt | GA5分层RAG: 因子库+Experience Memory+mining_knowledge三层自动组装prompt | GA5 |
| **AlphaForge** | AAAI 2025 | 生成式神经网络 + 动态因子组合权重(每日重新评估Factor Zoo) | G7动态因子权重参考 | G7 |
| **RD-Agent(Q)** | NeurIPS 2025 | 因子+模型联合优化(Co-STEER), 5单元自动化 | G6联合迭代框架参考 | G6 |

### Tier 3: 验证/警示（确认方向或暴露风险）

| 论文 | 会议 | 核心贡献 | 警示 | 对应Phase |
|------|------|---------|------|----------|
| **Backtest Implementation Risk** | Preprint 2026-03 | 5个回测引擎对比, cost model差异导致最高97%结果偏差 | 验证铁律重要性; IC/回测pipeline不一致是系统性风险(mf_divergence事件的外部验证) | 铁律 |
| **Dynamic GP+LightGBM** | Comp. Economics 2026 | GP三目标适应度 + 滚动窗口 + LightGBM, CSI300 Sharpe 1.59 | K9 GP三目标验证; G1 LightGBM方向验证 | K9/G1 |
| **AI in Quant Survey** | HKUST Survey 2025 | Alpha策略三阶段: 手动→DL→LLM Agent | 确认我们处于DL→Agent过渡期方向正确 | 全局 |

### 论文共识 → QuantMind行动映射（v3.4新增）

| 论文共识 | 我们的现状 | 行动 |
|---------|---------|------|
| 所有论文用LightGBM/XGB做最终评估 | 单因子IC + 等权组合Sharpe | G1升⭐5, G1后Gate G8从等权升级为ML OOS |
| 因子价值=模型特征贡献, 非单因子IC | IC=9.1%→实际-2.27%, IC不可靠 | 铁律11 + G1后改Gate最终评估标准 |
| code-based因子生成>算子集搜索 | FactorDSL 28算子, LLM盲猜IC=0.006 | GA5加入code gen实验, GA6从28→40(非55+) |
| AST结构去重防止伪创新 | Gate G8用BH-FDR+相关性, 无结构检查 | G8加入AST similarity(参考AlphaAgent开源) |
| persistent memory跨轮累积 | mining_knowledge 25张空表 | 核心问题不是表设计而是GP/LLM从未跑起来 |

### 已讨论但0个代码级利用的开源项目

| 项目 | 可利用部分 | 落地方案 | 对应Phase |
|------|-----------|---------|----------|
| **Qlib Alpha158** | 158个因子公式 | ✅ GA7已完成(v3.3): 128因子→8个独立新因子入池 | GA7 |
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

## 第十二部分: 全面审计结论（v3.2新增）

> 2026-04-03完成: 55张表/2.36亿因子行/5年回测链路/FF3归因
> 报告: COMPREHENSIVE_AUDIT_REPORT.md + DATA_QUALITY_AUDIT.md

### Sharpe=0.91的真相

```
FF3回归: R_strategy = 1.76%/月 + 0.818×RM + 0.831×SMB + 0.002×HML
Alpha:  +21.1%/年  (t=2.45, p=0.017) ✅ 显著 — 有真正的选股能力
SMB:    +7.7%/年   (t=4.05)          ⚠️ 显著小盘暴露(31%收益来自此)
HML:    +0.0%/年   (t=0.01)          — 无价值暴露
R²=49%
```

| 调整项 | Sharpe | 说明 |
|--------|--------|------|
| 原始 | 0.91 | 5年月度等权Top15 volume_impact |
| DSR校正(~50次测试) | 0.77-0.82 | -10~15%多重检验膨胀 |
| 滑点高估修正 | +0.03-0.05 | 模型滑点>真实滑点 |
| **保守估计** | **0.70-0.85** | **策略有真实alpha但需打折** |

### 数据地基: 0❌ 9⚠️

| 核心表 | 评级 | 关键问题 |
|--------|------|---------|
| klines_daily | A | turnover_rate全NULL(已用daily_basic代替) |
| daily_basic | A- | PE_TTM极值140万条(正常:亏损股) |
| factor_values | A- | 52GB过大; 中性化IC与raw差异大 |
| moneyflow_daily | B+ | **比klines少263只股票(4.9%)** |
| 25张空表 | — | GP/AI管线全空, northbound/margin=0行 |

### 9个⚠️问题清单

1. IC测试universe比回测多272只(ST+新股+微盘) → IC脚本加过滤(0.5h)
2. index_components=0行(IC用当前CSI300成分) → 拉历史成分(2h)
3. moneyflow比klines少263只 → 已被中性化填充处理
4. 行业分类用当前值(非历史) → 拉历史变更记录(4h)
5. SMB beta=0.83 → G1考虑市值中性化约束
6. 滑点模型高估3.7x → PT 60天后用真实数据校准
7. DSR校正后Sharpe≈0.77-0.82 → G1目标设为>1.0
8. 25张空表(GP/AI管线未运行) → 按路线图推进
9. 2021/2025小盘牛市贡献大部分Sharpe → 策略依赖小盘行情

---

## 第十二部分(续): 评估范式转移（v3.4新增, 最重要的方向性变化）

> **核心认知**: 等权线性组合的因子评估框架已到天花板。G1 LightGBM不仅是"一个ML模型",
> 而是整个因子评估体系从线性到非线性的升级。没有G1, 因子挖掘自动化闭环无法正确闭合。

### 证据链

| # | 证据 | 来源 | 含义 |
|---|------|------|------|
| 1 | 等权5因子后加因子边际为负 | Sprint 1.5 (10种方式8 FAIL) | 等权线性组合天花板~5-6因子 |
| 2 | PEAD(IC=5.34%)加入等权组合Sharpe-0.085 | Sprint 1.3b | 高IC≠组合增量 |
| 3 | Alpha158 7因子(+vsump60+cord30) p=0.24不显著 | GA7集成回测(2026-04-04) | 再次确认天花板 |
| 4 | mf_divergence IC=9.1%→实际-2.27% | GA2验证(2026-04-04) | 单因子IC评估不可靠 |
| 5 | 所有2025-2026论文用ML模型做最终评估 | 15篇前沿论文(v3.4) | 行业共识: 因子价值=ML特征贡献 |

### 范式对比

| 维度 | 旧范式(当前) | 新范式(G1后) |
|------|-----------|-----------|
| 因子评估 | 单因子IC > 阈值? | 加入LightGBM特征池后OOS Sharpe提升 > 0? |
| 组合构建 | z-score→截面排名→等权Top-N | LightGBM预测→排名→Top-N |
| Gate最终关卡 | 等权组合Sharpe > 基线 | ML OOS Sharpe > 基线×1.2 + p<0.05 |
| 因子交互 | 不考虑(等权=独立贡献假设) | ML自动学习(如高换手+低波动组合效应) |
| 天花板 | ~5-6因子 | 理论上50+特征(QuantaAlpha IC=0.15) |

### 执行计划

1. **G1完成前**: 继续用等权IC做初筛(Gate G1-G7不变), 但不再做等权组合回测(Gate G8暂停)
2. **G1完成后**: Gate G8从"等权组合Sharpe > 基线"改为"加入ML特征池后OOS Sharpe提升 > 0"
3. **GP/LLM产出的因子**: 直接加入G1特征池评估, 不走等权组合这条已证明有天花板的路

---

## 第十三部分: 清明改造 ✅ 已完成（v3.3确认）

> **目标**: 彻底替换碎片化通信架构，建立统一实时数据总线，上线PMS v1.0
> **原则**: 彻底替换，不做并行运行
> **结果**: 4步全部完成，全链路验证10 PASS/2 SKIP/0 FAIL

| Step | 任务 | Commit | Tag | 新增代码 |
|------|------|--------|-----|---------|
| 1 | NSSM→Servy v7.6(4服务+SCM recovery) | `326f2ed` | `qingming-step1-servy` | 服务配置+管理脚本 |
| 2 | Redis 3.0→5.0.14.1 + StreamBus(10 Streams) | `ca9309d` | `qingming-step2-streams` | stream_bus.py 202行 |
| 3 | QMT A-lite + Config .env化 + 全景审计 | `f12d3b4` | `qingming-step3-qmt` | qmt_data_service 257行 + qmt_client 105行 |
| 4 | PMS v1.0 阶梯利润保护(3层+14:30检查) | `b60f418` | `qingming-step4-pms` | pms_engine 373行 + PMS.tsx 227行 |
| 文档 | CLAUDE.md+Roadmap更新 | `a075aea` | — | — |

**总计**: 5个commit, ~1980行新代码, 12个新文件

**审计纠正3个认知偏差**:
1. run_paper_trading.py实际1430行（非901行）
2. strategy_configs DB表不存在（配置硬编码在signal_engine.py，已改.env驱动）
3. 调度链路实际16:25→16:30（非16:15→17:00→17:15，data_fetch嵌入signal_task内部）

**改造后架构**:
- Servy管理4服务: FastAPI/Celery/CeleryBeat/QMTDataService + SCM三级恢复(5s/10s/30s)
- Redis Streams统一数据总线: 10个Stream, `qm:{domain}:{event_type}`命名
- QMT Data Service: 唯一xtquant连接点, 每60秒同步持仓/资产/价格到Redis
- PMS v1.0: 阶梯利润保护(L1:30%+15%/L2:20%+12%/L3:10%+10%), 14:30 Celery Beat检查
- 配置.env化: PT_TOP_N=20, PT_INDUSTRY_CAP=1.0(4/30首次调仓生效)

---

## 第十四部分: 更新后的落地行动计划（v3.4）

### 优先级原则（v3.4更新）

```
生存(4/7开盘验证) > 评估框架升级(G1 LightGBM) > 因子来源多元化(GA5+code gen) > 基础设施(GA1/GA6) > 研究(GP)
```

**v3.3→v3.4优先级变化:**
| 任务 | v3.3 | v3.4 | 变化原因 |
|------|------|------|---------|
| G1 LightGBM | 第三周 | **⭐5, 4/8立即开始** | 评估范式转移核心, 所有论文共识 |
| GA2 EVENT回测 | ⭐2 极高 | **✅已完成** | 引擎验证通过, mf_divergence证伪 |
| GA6 算子扩展 | ⭐3, 第三周 | **⭐1, G1之后** | FactorMAD证明code-based更优, 范围缩小28→40 |
| GP启动 | 第三周 | **G1+GA5之后** | 新增第7项条件(G1完成) |

### 已完成（4/2-4/4, 累计）

| 任务 | 结果 |
|------|------|
| G2风险平价7组 | ❌ 无效 |
| G2.5动态仓位3组 | ❌ 无效 |
| 双周调仓 | ❌ Sharpe 0.91→0.73 |
| K0因子资产盘点 | ✅ 37因子完整清单 |
| 32因子批量IC | ✅ 20个候选 |
| G3 FF3风格归因 | ✅ Alpha=21.1%(t=2.45), SMB=0.83 |
| G8 DSR粗估 | ✅ 保守Sharpe=0.70-0.85 |
| 全面数据审计 | ✅ 0❌9⚠️ |
| PMS利润保护回测 | ✅ 阶梯保护Calmar+54% |
| Top-15→20+去行业约束 | ✅ Sharpe 0.91→1.15 |
| 清明架构改造(L8+L9) | ✅ Servy+Redis5.0+StreamBus+QMT A-lite+PMS v1.0 |
| 数据质量修复 | ✅ IC universe过滤+CSI300历史成分 |
| GA7 Alpha158导入 | ✅ 8个独立新因子入池 |
| Alpha158集成回测 | ✅ 7因子Sharpe+0.11但p=0.24不显著 |
| 铁律统一+Hooks清理 | ✅ 10条铁律+iron_law_enforce.py |
| **GA2 EVENT回测器** | **✅ 引擎验证通过(357行+9/9测试)** |
| **mf_divergence IC证伪** | **✅ IC=9.1%→实际-2.27%, 幽灵数据** |

### 4/7（开盘日 — 不可推迟）

| 任务 | 说明 |
|------|------|
| 08:30 启动miniQMT | 手动启动 |
| 09:30 检查实时价格 | `redis-cli KEYS "market:latest:*"` |
| 14:30 PMS首次实战检查 | 观察日志确认阶梯保护逻辑正常 |
| 收盘后 peak_price更新 | 确认position_monitor数据正确 |

### 4/7-4/8（GA2收尾 + 铁律11）

| 任务 | 说明 | 工作量 |
|------|------|--------|
| PEAD IC现场验证(铁律11首次应用) | 先确认factor_ic_history有无记录, 无则现场计算IC+方向 | 半天 |
| 铁律11写入CLAUDE.md | iron_law_enforce.py新增IC入库检查 | 1小时 |
| 原则15写入CLAUDE.md | 结论传播必须标注来源和验证状态 | 30分钟 |

### 4/8-4/14（G1 LightGBM — ⭐5最高优先级）

| 任务 | 说明 | 工作量 |
|------|------|--------|
| G1特征工程 | 48+因子整理为LightGBM特征矩阵, 缺失值处理, 时间对齐 | 2天 |
| G1 Walk-Forward训练 | 7-fold + Optuna超参 + GPU(RTX 5070) | 3天 |
| G1 OOS评估 | Sharpe/MDD/年度分解 + paired bootstrap vs 等权基线 | 1天 |
| G1 fail-fast判断 | 见下方决策树 | 当天 |

**G1 fail-fast决策树:**
```
G1 OOS Sharpe ≥ 基线×1.2 且 p<0.05
  → 成功 → 上线影子PT → Gate G8升级为ML评估 → 继续G1.1-G1.4
G1 OOS Sharpe ≥ 基线 但 p>0.05
  → 方向对但特征不够 → GA5 code gen扩展特征池后重跑
G1 OOS Sharpe < 基线
  → ML在当前数据上无增量 → 审视原因(因子质量? 数据量? 信噪比?)
```

### 4/14-4/16（G1后续 — 视G1结果）

| 如果G1成功 | 如果G1未通过 |
|-----------|-----------|
| GA5 LLM code gen实验(1-2天) | 特征重要性分析, 哪些因子有贡献哪些是噪声 |
| GA1 StrategyMatcher(2天) | 扩展特征池: 分钟数据(L10), 另类数据(K6) |
| Gate G8升级为ML OOS评估 | 线性模型(Lasso/Ridge)是否比等权好 |

### 4/21起

| 任务 | 依赖 |
|------|------|
| G1.1-G1.4 ML扩展(LambdaRank+XGB+Cat+Ensemble) | G1成功 |
| GA6精简版(28→40) + AST去重 | GA5 code gen结论 |
| GP首次正式运行 | 7项启动条件全部满足 |

### 4/30（月末调仓）

| 任务 | 说明 |
|------|------|
| 首次使用top_n=20 + industry_cap=1.0 | .env驱动, 清明改造后首次调仓 |

---

## 第八部分(续): 关键工作原则（完整版）

*(保留原有11条, v3.2新增12-14条, v3.4新增15条)*

12. **全方面思考，不能太局限** — 不要在一个框架/方向上反复优化(G2教训), 质疑默认假设(为什么日频?为什么月度?为什么不做盘中风控?)(v3.2新增)
13. **外部资料参考但不盲从** — 搜索要广泛深入, 但每条结论需要独立判断是否适用于我们的数据量/策略类型/市场环境(v3.2新增)
14. **彻底替换优于并行运行** — 新旧系统并行增加复杂度和排查难度, 有窗口期就彻底切换(v3.2新增, 清明改造决策)
15. **结论传播必须标注来源和验证状态** — 任何影响优先级排序的定量结论(IC值/Sharpe值/p值), 在首次被用于决策时必须标注来源和验证状态(⚠️未入库/✅已验证)。未验证的结论不能作为路线图优先级排序的依据。(v3.4新增, mf_divergence教训 + Sortify Belief通道启示)

### 铁律11: IC可追溯性（v3.4新增）

> 任何因子的IC/IR必须有可追溯的计算记录（脚本路径+参数+factor_ic_history入库）。
> 对话或文档中提到的数字不能作为决策依据。**未入库的IC视为不存在。**
>
> **触发场景**: 当任何因子的IC被引用做优先级排序、回测决策、入池判断时,
> 必须先确认factor_ic_history表中有对应记录。无记录→先跑IC计算入库→再决策。
>
> **教训来源**: mf_divergence "IC=9.1%" 实际为 -2.27%, 错误数字驱动GA2⭐2优先级数月。

---

*本文档是QuantMind V2的完整技术路线图v3.4。*
*Phase A-F已完成, G2/G2.5已完成(全部无效), G3/G8已完成(Alpha真实t=2.45, 保守Sharpe 0.70-0.85)。*
*GA2 EVENT回测器已完成(引擎✅, mf_divergence IC=9.1%证伪为-2.27%)。GA7 Alpha158已完成(8新因子)。*
*v3.4核心: 评估范式转移(单因子IC→模型OOS), G1升⭐5最高优先级, mf_divergence证伪推翻"冤杀"叙事, GA2降回正常, GA6缩小(28→40)+code gen并行, GP启动条件+1(G1完成), 铁律11(IC可追溯性), 原则15(结论传播标注), 前沿论文15篇分三层对标。*
*v3.3核心: 清明改造完成, ML扩展规划(G1.1-G1.7), 因子挖掘分层策略, GP根因分析, Alpha158完成, 铁律统一。*
*v3.2核心: 全面审计结论(FF3/DSR/数据质量), Redis Streams实时架构, PMS持仓管理, Servy迁移, 清明改造计划。*
*v3.1核心: 前沿AI研究对标, Experience Memory, 动态因子权重, 实盘反馈闭环。*
*v3核心: 基线修正(0.91/-43%), AI闭环管道(Phase GA), 多策略架构, Alpha多元化优先。*
*QMT模拟盘4/2首次建仓, 当前15只持仓NAV≈¥958,684。PT毕业阈值=保守Sharpe×0.7≈0.56-0.60。*
*回测协议参考: Arnott, Harvey, Markowitz (2019) "A Backtesting Protocol in the Era of Machine Learning", JFDS 1(1), 64-74.*
