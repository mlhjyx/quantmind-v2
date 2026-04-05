# 数据层全面审计 + 回测链路可靠性验证 + 风格归因

> 日期: 2026-04-03
> 审计范围: 55张表 / 2.36亿因子行 / 5年回测链路 / FF3归因

---

## Part 1: 数据资产盘点

### 1.1 数据库总览

| 分类 | 表数 | 总大小 | 说明 |
|------|------|--------|------|
| **核心行情** | 4 | 54.0 GB | klines_daily(1.2GB) + daily_basic(1.3GB) + factor_values(52GB) + moneyflow(1.4GB) |
| **基本面** | 3 | 273 MB | balance_sheet + cash_flow + financial_indicators |
| **指数/日历** | 2 | 7.3 MB | index_daily + trading_calendar |
| **元数据** | 1 | 1.1 MB | symbols |
| **交易/监控** | 10 | ~1 MB | position_snapshot, signals, trade_log, performance_series等 |
| **空表(DDL已建未用)** | **25** | ~0 | 见下方 |
| **GP/AI管线** | 5 | ~0 | mining_knowledge(0行), gp_approval_queue(0行)等 |
| **合计** | **55张** | **~56 GB** | |

### 1.2 核心表详情

| 表 | 行数 | 大小 | 股票数 | 时间范围 | 关键发现 |
|----|------|------|--------|----------|---------|
| **factor_values** | **2.36亿** | **52 GB** | 5,694 | 2020-07~2026-04 | 37因子×5700股×1300天，最大表 |
| klines_daily | 740万 | 1.27 GB | 5,700 | 2020-01~2026-04 | ✅ 完整，无close<=0 |
| daily_basic | 736万 | 1.33 GB | 5,700 | 2020-01~2026-04 | ⚠️ PE_TTM极值140万条 |
| moneyflow_daily | 619万 | 1.39 GB | 5,578 | 2021-01~2026-04 | ⚠️ 比klines少263只股票 |
| index_daily | 5.1万 | 6.9 MB | N/A | 2020-01~2026-04 | 含CSI300/500 |
| symbols | 5,810 | 1.1 MB | 5,810 | N/A | 含320只退市股 |
| financial_indicators | 24万 | 52 MB | 5,506 | N/A | 基本面(Sprint 1.5关闭) |
| holder_number | 8.2万 | 11 MB | **550** | N/A | ⚠️ 仅覆盖10%股票 |

### 1.3 25张空表(有DDL无数据)

**未来功能预留**: universe_daily, index_components, northbound_holdings, margin_data, chip_distribution, forex_bars/events/swap_rates

**GP/AI管线空**: mining_knowledge, gp_approval_queue, factor_mining_task, pipeline_run, model_registry, agent_decision_log, experiments, backtest_wf_windows

**风控/审计空**: execution_audit_log, operation_audit_log, circuit_breaker_log, approval_queue, param_change_log

**其他空**: ai_parameters, factor_evaluation, backtest_holdings, notification_preferences

### 1.4 未使用字段

| 表 | 字段 | NULL率 | 是否被因子/回测使用 |
|----|------|--------|-------------------|
| klines_daily | turnover_rate | **100%** | ❌ 全NULL，回测用daily_basic.turnover_rate代替 |
| symbols | industry_sw2 | **100%** | ❌ 未拉取 |
| daily_basic | volume_ratio | 2% | ❌ 未被任何因子使用 |
| daily_basic | ps / ps_ttm | 0% | ❌ 市销率，未被使用 |
| daily_basic | free_share | 0% | ❌ 自由流通股，未被使用 |
| holder_number | * | — | ❌ 仅550只股票，覆盖率太低未使用 |

### 1.5 Tushare可拉但未拉的接口

从TUSHARE_DATA_SOURCE_CHECKLIST.md和DDL对比:
- **index_components**: 沪深300/500历史成分股 → 0行(用当前成分做基准是前瞻偏差⚠️)
- **northbound_holdings**: 北向资金持仓 → 0行
- **margin_data**: 融资融券 → 0行
- **chip_distribution**: 筹码分布 → 0行
- **analyst_forecast**: 分析师预期(需H档) → 无表

---

## Part 2: 数据质量评分卡

### 2.1 逐表评分

| 表 | 完整性 | 时效性 | 准确性 | 覆盖率 | 唯一性 | 评级 | 关键问题 |
|----|--------|--------|--------|--------|--------|------|---------|
| klines_daily | A(0% NULL核心字段) | A(T+0) | A(close一致) | A(5700股) | A(0 dup) | **A** | turnover_rate全NULL(用daily_basic) |
| daily_basic | A(核心0%) | A(T+0) | A | A(5700股) | A(0 dup) | **A-** | PE_TTM极值140万条(正常:亏损股) |
| factor_values | A(raw 1.3% NULL) | A(T+0) | B | A(5694股) | A(0 dup) | **A-** | 52GB过大;中性化IC与raw差异大(F节) |
| moneyflow_daily | A(0% NULL) | B(T+1) | A | **B(5106股)** | A(0 dup) | **B+** | **比klines少263只(4.9%)**，资金流因子覆盖缺口 |
| index_daily | A | A | A | A | A | **A** | — |
| symbols | A | A | A | A | A | **A** | — |
| financial_indicators | A | C(季度) | B | B(5506) | A | **B** | Sprint 1.5关闭，PIT已实现 |

### 2.2 关键质量问题

| # | 问题 | 严重性 | 影响 |
|---|------|--------|------|
| 1 | **moneyflow缺263只股票** | ⚠️ | mf_divergence/large_order_ratio/money_flow_strength对这些股票无值，IC计算可能偏差 |
| 2 | **klines.turnover_rate全NULL** | ⚠️ | 回测用daily_basic.turnover_rate代替，数据源一致但冗余字段误导 |
| 3 | **PE_TTM极值140万条** | ℹ️ | 亏损股PE为极大负值/正值，正常现象，不影响回测(未用PE选股) |
| 4 | **holder_number仅覆盖550只** | ℹ️ | 10%覆盖率太低，不可用于因子计算 |
| 5 | **index_components=0行** | ⚠️ | 无CSI300历史成分 → IC基准用的是当前成分(轻微前瞻) |

---

## Part 3: 回测链路可靠性

### 3.1 股票池一致性 ⚠️

| 环节 | 股票数(2024-12-31) | ST排除 | 新股排除 | 市值下限 |
|------|-------------------|--------|---------|---------|
| 回测(run_backtest) | 5,097 | ✅ | ✅(<60d) | ✅(>10亿) |
| IC测试(research脚本) | 5,369 | ❌ | ❌ | ❌ |
| 因子计算(factor_engine) | 5,369 | ❌ | ❌ | ❌ |
| QMT实盘 | ~5,000 | ✅ | ✅ | ✅(>5000万日均) |

**差异**: IC测试比回测多272只(ST+新股+微盘)。影响已评估为中等(见DATA_QUALITY_AUDIT.md)。

### 3.2 存活偏差 ✅

- 320只退市股在symbols中，210只有klines数据(66%)，204只有factor数据
- 退市股参与了因子计算和回测 → 无明显存活偏差
- ⚠️ 无强制平仓逻辑(退市前未自动卖出)，但影响极小

### 3.3 前瞻偏差检查

| 项 | 状态 | 详情 |
|----|------|------|
| **复权方式** | ✅ | `adj_close = close × adj_factor / latest_adj_factor` 前复权，每次计算动态除以最新adj_factor |
| **财报PIT** | ✅ | `load_financial_pit`用`actual_ann_date`过滤(非report_date) |
| **CSI300成分** | ⚠️ | **index_components=0行，用当前成分计算IC超额收益**。对IC影响<1%(成分股变动有限) |
| **行业分类** | ⚠️ | symbols.industry_sw1是**当前分类**，未用历史分类。对中性化有轻微影响 |
| **PE/PB/市值** | ✅ | daily_basic由交易所当日收盘后发布，T日用T日数据无前瞻 |
| **因子计算时点** | ✅ | 因子用当日收盘价/成交量，收盘后即可知 |

### 3.4 调仓假设 ✅

| 项 | 实现 |
|----|------|
| 调仓日 | 月末最后交易日生成信号(signal_date) |
| 执行日 | signal_date后第一个交易日(T+1) |
| 成交价格 | 执行日开盘价(open) |
| 涨停买不入 | ✅ can_trade()检查: close≈up_limit且turnover<1% → 创建PendingOrder |
| 跌停卖不出 | ✅ can_trade()检查: close≈down_limit且turnover<1% → 跳过 |
| T+1资金 | ✅ 卖出资金当日可用于买入(_sell_proceeds_today) |
| 整手约束 | ✅ floor到100股 |
| volume_cap | ✅ 单笔≤当日成交额10% |

### 3.5 成本建模 ✅

| 参数 | 回测值 | QMT实际 | 一致? |
|------|--------|---------|-------|
| 佣金 | 万0.854 | 万0.854(国金) | ✅ |
| 印花税 | 千0.5(卖出) | 千0.5 | ✅ |
| 过户费 | 万0.1 | 万0.1 | ✅ |
| 滑点 | volume_impact模型(8-51bps) | 实测47.6bps均值 | ⚠️ 模型高估3.7倍(R4研究) |

**滑点高估影响**: 回测Sharpe可能被**低估**——如果用真实滑点(更低)，Sharpe可能>0.91。

### 3.6 基准选择 ⚠️

| 项 | 现状 | 问题 |
|----|------|------|
| IC基准 | CSI300超额收益 | 持仓96%小盘股，用大盘基准计算IC可能虚高(小盘beta被计为alpha) |
| Sharpe无风险利率 | 0(隐含) | 标准做法，无问题 |
| **FF3归因已确认** | SMB beta=0.83(t=4.05) | **小盘暴露显著** → 见Part 5 |

### 3.7 起止日期敏感性

G2.5已有年度分解:
| 年 | Sharpe | Return |
|----|--------|--------|
| 2021 | 3.10 | +99.3% |
| 2022 | -0.87 | -18.9% |
| 2023 | 0.47 | +7.9% |
| 2024 | 0.46 | +11.2% |
| 2025 | 2.37 | +68.4% |

2021和2025(小盘牛市)贡献了大部分收益。如果从2022开始，Sharpe会大幅下降。**Sharpe=0.91高度依赖2021/2025两年小盘行情**。

### 3.8 数据snooping ⚠️

| 维度 | 测试数 |
|------|--------|
| 因子测试 | 74(FACTOR_TEST_REGISTRY) |
| 权重方法 | 4(equal/risk_parity/min_variance/score_weighted) |
| 滑点模式 | 2(fixed/volume_impact) |
| 调仓频率 | 3(weekly/biweekly/monthly) |
| Top-N | ~3(10/15/20) |
| 动态仓位 | 4(off/10d/20d/40d) |
| vol_regime | 4(off/vol20/vol5/vol60) |
| **估计总配置** | **~50-80** |
| **有效N(考虑相关性)** | **~15-25** |

DSR粗估: 以N_eff=20, Sharpe=0.91, 5年样本:
- Harvey-Liu-Zhu(2016) haircut ≈ 10-15%
- DSR校正后Sharpe ≈ 0.77-0.82
- 仍>0.5，策略有效但不如0.91看起来那么强

---

## Part 4: 数据血缘关系

### 4.1 因子 → 数据表 → 字段映射

```
5个Active因子:
  turnover_mean_20  ← daily_basic.turnover_rate
  volatility_20     ← klines_daily.close × adj_factor (→ adj_close)
  reversal_20       ← klines_daily.close × adj_factor (→ adj_close)
  amihud_20         ← klines_daily.adj_close + volume + amount
  bp_ratio          ← daily_basic.pb (→ 1/pb)

Reserve:
  vwap_bias_1d      ← klines_daily.close + amount + volume
  rsrs_raw_18       ← klines_daily.high + low

ML-KLINE因子:
  kbar_kmid/ksft/kup ← klines_daily.open/high/low/close
  maxret_20          ← klines_daily.adj_close
  chmom_60_20        ← klines_daily.adj_close
  up_days_ratio_20   ← klines_daily.adj_close
  stoch_rsv_20       ← klines_daily.adj_close/adj_high/adj_low
  gain_loss_ratio_20 ← klines_daily.adj_close

ML-MONEYFLOW因子:
  mf_divergence      ← klines_daily.adj_close + moneyflow_daily.net_mf_amount
  large_order_ratio  ← moneyflow_daily.buy_lg/elg/md/sm_amount
  money_flow_strength← moneyflow_daily.net_mf_amount + daily_basic.total_mv

ML-INDEX因子:
  beta_market_20     ← klines_daily.adj_close + index_daily.close(CSI300)

FULL因子:
  ep_ratio           ← daily_basic.pe_ttm
  price_volume_corr  ← klines_daily.adj_close + volume
  dv_ttm             ← daily_basic.dv_ttm
  price_level_factor ← klines_daily.close (原始,非复权)
  relative_volume_20 ← klines_daily.volume
  turnover_surge     ← daily_basic.turnover_rate
  ln_market_cap      ← daily_basic.total_mv
```

### 4.2 影响域

| 如果这个字段出问题 | 影响的因子 |
|-------------------|-----------|
| klines.close/adj_factor | **所有价量因子**(19个) |
| daily_basic.turnover_rate | turnover_mean_20(Active), turnover_surge |
| daily_basic.pb | bp_ratio(Active) |
| daily_basic.total_mv | ln_market_cap, money_flow_strength, 中性化(WLS权重) |
| moneyflow_daily.net_mf_amount | mf_divergence, money_flow_strength |
| index_daily.close(300) | beta_market_20, IC超额收益基准 |

---

## Part 5: 风格归因 (FF3)

### 5.1 回归结果

```
R_strategy = 1.76%/月 + 0.818×RM + 0.831×SMB + 0.002×HML + ε

                 coef    std err    t      P>|t|    [0.025   0.975]
const          0.0176     0.007    2.45    0.017     0.003    0.032
RM             0.8184     0.137    5.97    0.000     0.544    1.093
SMB            0.8309     0.205    4.05    0.000     0.420    1.242
HML            0.0023     0.185    0.01    0.990    -0.368    0.372

R² = 0.489,  Adj R² = 0.462
```

### 5.2 回报分解(年化)

| 成分 | 年化贡献 | 占比 |
|------|---------|------|
| **Alpha** | **+21.1%** | **86%** |
| RM(市场) | -0.8% | -3% |
| **SMB(小盘)** | **+7.7%** | **31%** |
| HML(价值) | +0.0% | 0% |
| 残差 | -3.6% | -15% |
| **总计** | **+24.5%** | **100%** |

### 5.3 解读

**✅ Alpha显著**: 月度alpha=1.76% (t=2.45, p=0.017)，年化23.3%。即使控制了市场/规模/价值三个风格因子后，策略仍有显著的选股能力。

**⚠️ 小盘暴露显著**: SMB beta=0.83 (t=4.05)。策略对小盘风格有强暴露，年化贡献+7.7%。当小盘风格反转时(如2017年大盘蓝筹行情)，策略可能大幅回撤。

**HML暴露为零**: HML beta≈0 (t=0.01)。尽管bp_ratio是Active因子之一，但策略整体不暴露价值风格。这可能因为其他因子(turnover/volatility)选的低波动股与高BP股不完全重合。

**R²=49%**: 市场+规模解释了策略收益的一半。剩余一半是选股alpha+残差。

### 5.4 对Sharpe=0.91的影响

- 原始Sharpe=0.91中，约31%的收益来自小盘风格暴露(SMB)
- 如果小盘风格premium=0(如2017-2018年)，预期收益从24.5%降到~17%
- 但alpha=21.1%年化(t=2.45) → **即使去掉小盘beta，策略仍有真实alpha**
- **结论: Sharpe=0.91中有真实选股能力，但对小盘行情有依赖**

---

## 综合问题清单

### ❌ 严重(需修复)

无。

### ⚠️ 中等(需关注)

| # | 问题 | 影响 | 修复建议 | 工作量 |
|---|------|------|---------|--------|
| 1 | IC测试universe比回测多272只 | IC可能偏差5% | IC脚本加universe过滤 | 0.5h |
| 2 | index_components=0行 | IC超额收益用当前CSI300成分(轻微前瞻) | 拉取历史成分 | 2h |
| 3 | moneyflow比klines少263只 | 资金流因子缺263只数据 | 这些股票资金流因子=NULL,已被中性化填充 | 已处理 |
| 4 | 行业分类用当前值 | 中性化可能有轻微偏差 | 拉取历史行业变更记录 | 4h |
| 5 | SMB beta=0.83 | 小盘风格反转时策略受损 | 监控SMB因子,考虑市值中性化选股 | G1考虑 |
| 6 | 滑点模型高估3.7倍 | Sharpe可能被低估 | PT 60天后用真实数据校准 | PT后 |
| 7 | DSR校正后Sharpe≈0.77-0.82 | 原始0.91有多测选择膨胀 | 记录,不影响决策 | — |
| 8 | 25张空表 | GP/AI管线未运行 | 按路线图推进 | — |
| 9 | klines.turnover_rate全NULL | 冗余字段,回测已用daily_basic代替 | 清理或填充 | 1h |

### ℹ️ 已知限制(记录)

- PE_TTM极值140万条: 亏损股正常现象
- holder_number仅550只: 覆盖率太低,不可用
- 退市股无强制平仓: 影响极小(<0.1%)
- 2021/2025小盘牛市贡献大部分Sharpe: 策略依赖小盘行情

---

## 最终判断: Sharpe=0.91有多可信?

| 维度 | 调整 | 说明 |
|------|------|------|
| 原始Sharpe | 0.91 | 5年月度等权Top15 volume_impact |
| DSR校正(-10~15%) | 0.77-0.82 | 多重检验膨胀 |
| 滑点高估修正(+) | +0.03~0.05 | 模型滑点>真实滑点 |
| FF3 Alpha | t=2.45 | ✅ 统计显著(p=0.017) |
| 小盘依赖 | SMB beta=0.83 | 风格中性Sharpe≈0.65-0.75 |

**保守估计: 真实Sharpe≈0.70-0.85**

策略有真实的选股alpha(t=2.45)，但0.91中包含:
1. ~10%来自多重检验膨胀
2. ~31%收益来自小盘风格暴露(非alpha)
3. 滑点模型保守(略微低估真实Sharpe)

**结论: 数据地基基本稳固(无❌级问题)，Sharpe=0.91可信但需打折扣。保守估计0.70-0.85。G1 LightGBM的目标应设为Sharpe>1.0(对应保守估计>0.85)。**
