# STRATEGY_CANDIDATES.md — 策略候选库

> strategy角色持续研究产出。目标：Paper Trading毕业时有3-5个经过初步验证的候选。
> 每个候选按标准格式记录，完整后按TEAM_CHARTER_V2.md §3.6.2提交评审。
> 版本：V1.0 (2026-03-22) — 首批3个候选初步设计

---

## 基线策略概况

| 项目 | 值 |
|------|-----|
| 因子 | volatility_20, reversal_20, turnover_mean_20, ln_market_cap, bp_ratio (5因子) |
| 合成 | 等权Top-20，月频调仓 |
| 行业约束 | IndCap=25% |
| Sharpe | 1.29 (回测全期) |
| 风格暴露 | 小盘价值 + 低波 + 反转，价量因子主导 |

**风格集中度风险**：当前5因子中价量因子3个(volatility_20, reversal_20, turnover_mean_20)，基本面仅bp_ratio一个。在价量因子拥挤或价值风格逆风时期（如2019-2020成长牛市），策略可能持续亏损。候选策略应重点补充风格多样性。

---

## 评估标准

- 与当前策略corr < 0.3
- 预期Sharpe > 0.5
- 能用现有数据实现（或数据缺口可在2周内补齐）
- 有学术或实践验证

---

## 候选列表

### 候选1: 质量成长策略 (Quality-Growth)

- **核心逻辑**: 选高ROE+高营收增速+低负债率的基本面优质成长股，以基本面驱动替代价量驱动，与基线策略形成因子正交互补。

- **因子依赖**:
  | 因子 | 计算方式 | 数据来源 | 方向 |
  |------|---------|---------|------|
  | roe_ttm | 最近4个季度ROE（滚动TTM） | financial_indicators.roe + report_date PIT对齐 | 正 |
  | revenue_yoy | 营收同比增速 | financial_indicators.revenue_yoy + ann_date PIT | 正 |
  | gross_margin | 毛利率 | financial_indicators.gross_profit_margin + PIT | 正 |
  | debt_to_asset | 资产负债率 | financial_indicators.debt_to_asset + PIT | 负 |
  | roe_stability | ROE连续4季度标准差（越小越稳定） | financial_indicators.roe 时序 | 负 |

- **数据依赖**:
  | 表/字段 | DB是否已有 | 数据量 | 备注 |
  |---------|-----------|--------|------|
  | financial_indicators.roe | 已有 | 240K行, 5499只股, 1990-2025 | 充足 |
  | financial_indicators.revenue_yoy | 已有 | 同上 | 充足 |
  | financial_indicators.gross_profit_margin | 已有 | 同上 | 充足 |
  | financial_indicators.debt_to_asset | 已有 | 同上 | 充足 |
  | financial_indicators.actual_ann_date | 已有 | PIT时间对齐用 | 关键字段 |

  **数据缺口**: 无。所有字段已在DB中，且覆盖时间充分。需注意financial_indicators用actual_ann_date做PIT对齐（CLAUDE.md强制要求），不可用report_date做时间索引。

- **预期Sharpe**: 0.6-1.0。A股质量因子（高ROE选股）的文献IC约0.03-0.05，弱于价量但稳定性好。成长因子(revenue_yoy)在A股IC约0.02-0.04，波动较大但与质量因子有互补。组合后预期Sharpe在0.7左右。

- **与当前策略相关性**: 预期corr **0.05-0.15**（极低）。理由：当前基线5因子全部来自价量+估值维度，质量成长因子来自财报维度，截面选股重叠度极低。高ROE成长股往往市值偏大、估值偏高（与基线的小盘价值倾向相反），进一步降低相关性。这是风格互补最强的候选。

- **实现难度**: **低**。
  - 财务因子计算框架已有（scripts/analyze_financial_factors.py, engines/financial_factors.py）
  - PIT对齐逻辑已在Route C实现
  - 仅需：(1) 计算roe_stability因子(滚动4Q标准差) (2) 因子合成+回测验证
  - 预计2-3天可完成初步验证

- **适合Phase**: **1B**（紧接当前Paper Trading验证期）

- **学术/实践依据**:
  - Novy-Marx (2013) "The Other Side of Value: The Gross Profitability Premium" (JFE): 毛利率因子(GPA)在美股有显著Alpha，且与价值因子(HML)负相关，组合后Sharpe显著提升
  - Asness, Frazzini, Pedersen (2019) "Quality Minus Junk" (RFS): Quality因子(含ROE/稳定性/低杠杆)跨市场有效，与Value因子互补
  - A股实证：scripts/analyze_gpa_ic.py已对GPA做过初步IC分析（可复查结果），国内券商研报普遍报告A股ROE因子IC_mean约0.03，成长因子约0.02

- **主动发现/风险提示**:
  - **强烈推荐作为第一优先实现**。理由：(1) 数据完全就绪零缺口 (2) 与基线相关性最低 (3) 实现框架已有 (4) 文献支持最强
  - **风险**：财报数据季频更新，在季报窗口期因子值不变约3个月，月频调仓时大部分时间信号不变化，换手率会很低。这既是优点（低成本）也是限制（反应慢）
  - **需要alpha_miner配合**：计算roe_stability因子（滚动4Q std），加入factor_registry
  - **需要quant验证**：PIT对齐是否正确（用ann_date不是report_date），避免lookahead bias

---

### 候选2: 红利低波策略 (Dividend Low-Volatility)

- **核心逻辑**: 选高股息率+低波动率的防御型股票。红利低波是A股最成熟的Smart Beta策略之一，在熊市和震荡市表现优异，与基线策略的反转/动量风格形成市场状态互补。

- **因子依赖**:
  | 因子 | 计算方式 | 数据来源 | 方向 |
  |------|---------|---------|------|
  | dv_ttm | 近12月股息率(TTM) | daily_basic.dv_ttm | 正 |
  | volatility_60 | 60日收益率标准差 | klines_daily.pct_change | 负 |
  | dv_stability | 近3年股息连续性(0/1编码+均值) | daily_basic.dv_ttm 时序 | 正 |
  | payout_ratio | 分红/净利润比 | 需从financial_indicators推算 | 正(适度) |

- **数据依赖**:
  | 表/字段 | DB是否已有 | 数据量 | 备注 |
  |---------|-----------|--------|------|
  | daily_basic.dv_ttm | 已有 | 7.3M行, 2020-2026, 约287万条有值 | 充足 |
  | daily_basic.dv_ratio | 已有 | 同上 | dv_ratio是近12月/当日价格 |
  | klines_daily.pct_change | 已有 | 7.3M行 | 充足 |
  | factor_values.volatility_60 | 已有 | 已在因子库中 | 直接可用 |

  **数据缺口**:
  - dv_stability需要从daily_basic.dv_ttm历史序列计算，数据从2020年起有约6年，勉强可以算3年连续分红。不需要额外拉取。
  - payout_ratio需要分红总额/净利润，financial_indicators中有eps和bps但没有直接的分红总额。**可用dv_ttm x 总市值 / 净利润近似计算**，或从Tushare dividend接口补充（需评估积分消耗）。初期可仅用dv_ttm+volatility_60两因子先验证，payout_ratio为增强项。

- **预期Sharpe**: 0.5-0.8。中证红利低波指数(H30269)历史年化约10-12%，Sharpe约0.6-0.8。个股层面选股有空间做到更好，但红利策略天花板不高（高股息股通常低增长）。

- **与当前策略相关性**: 预期corr **0.10-0.25**。基线已含volatility_20（负向=选低波），红利低波也选低波股票，这部分有重叠。但红利维度（高股息）与基线无重叠。总体相关性较低但不如候选1那么正交。

- **实现难度**: **低**。
  - dv_ttm数据已在DB，volatility_60已在factor_values
  - 仅需：(1) 将dv_ttm转为因子（截面rank） (2) 计算dv_stability (3) 合成+回测
  - 预计1-2天可完成初步验证

- **适合Phase**: **1B**

- **学术/实践依据**:
  - Baker, Bradley, Wurgler (2011) "Benchmarks as Limits to Arbitrage" (FAJ): 低波动异常(Low-Volatility Anomaly)跨市场存在
  - 中证指数公司: 中证红利低波动指数(H30269)自2013年基日至今年化超额沪深300约5-8%
  - A股实证: 红利低波在2018熊市、2022熊市中显著跑赢，但在2019-2020成长牛市中跑输。这恰好与基线策略（小盘价值反转）的弱势期重叠较多——两者都在成长牛市中弱势，这是一个需要关注的问题

- **主动发现/风险提示**:
  - **市场状态互补不如预期**：仔细分析后发现，红利低波和小盘价值在牛市（尤其成长牛）中可能同时跑输。两者虽然因子层面正交，但对市场状态的敏感性有一定同向性（都属于防御型/价值型风格）。组合时需要加入一个进攻型策略（如候选3的行业动量）来平衡
  - **优势**：实现极简、数据完备、策略逻辑清晰、投资者接受度高、换手率极低（高股息股票池稳定）
  - **需要quant验证**：dv_ttm字段在daily_basic中的填充率（2020年前的数据缺失需评估是否影响回测长度）
  - **需要alpha_miner配合**：将dv_ttm因子纳入factor_values表，计算dv_stability

---

### 候选3: 行业轮动策略 (Sector Rotation)

- **核心逻辑**: 基于行业层面的动量/反转/资金流信号做行业配置，再在选中行业内用当前基线个股选股逻辑选股。与个股选股策略天然低相关——个股Alpha来自截面选股，行业Alpha来自配置偏离。两个维度正交。

- **因子依赖**（行业层面因子，非个股层面）:
  | 因子 | 计算方式 | 数据来源 | 方向 |
  |------|---------|---------|------|
  | ind_momentum_20 | 行业指数20日动量 | klines_daily按industry_sw1聚合 | 正(动量)/负(反转) |
  | ind_reversal_60 | 行业指数60日反转 | 同上 | 负 |
  | ind_breadth | 行业内上涨股票比例(20日均值) | klines_daily.pct_change + symbols.industry_sw1 | 正 |
  | ind_vol_ratio | 行业成交额相对占比变化 | klines_daily.amount + industry聚合 | 正(资金流入) |
  | ind_concentration | 行业内个股相关性(越低越分散) | klines_daily收益率截面 | 负 |

- **数据依赖**:
  | 表/字段 | DB是否已有 | 数据量 | 备注 |
  |---------|-----------|--------|------|
  | klines_daily (价量) | 已有 | 7.3M行 | 充足，可按行业聚合 |
  | symbols.industry_sw1 | 已有 | 110个行业(SW二级) | 行业分类完备 |
  | index_components | **空表** | 0行 | 沪深300/500/1000成分股权重未填充 |
  | moneyflow_daily | **空表** | 0行 | 资金流数据未拉取 |

  **数据缺口**:
  - **index_components为空**：行业轮动策略本身不强依赖指数成分股，可以用symbols.industry_sw1直接聚合个股数据构造行业因子。但如果需要行业基准收益率用于归因分析，则需要补充申万行业指数数据（Tushare index_daily支持申万行业指数，如801010.SI等）。**建议data补充申万一级行业指数日线**
  - **moneyflow_daily为空**：ind_vol_ratio可用klines_daily.amount替代（成交额聚合），不严格需要资金流细分数据。资金流因子(ind_net_mf)作为增强项，需要data拉取moneyflow数据

- **预期Sharpe**: 0.4-0.7（行业轮动部分）。行业动量/反转在A股IC约0.02-0.04（行业层面截面较少约30个SW一级，统计噪声大）。叠加到个股选股之上，组合Sharpe预期提升0.1-0.2。

- **与当前策略相关性**: 预期corr **0.05-0.20**（极低）。行业轮动操作的是行业配置维度，基线操作的是个股截面选股维度，两个Alpha来源几乎正交。这是分散化价值最高的候选方向。

- **实现难度**: **中**。
  - 需要新建行业因子计算框架（个股因子聚合到行业层面）
  - 需要处理行业层面的信号合成逻辑（与个股选股逻辑不同）
  - 需要设计"行业配置 + 行业内选股"的两层组合结构
  - 预计5-7天完成初步验证

- **适合Phase**: **1C**（需要更多工程工作，适合在质量成长和红利低波验证之后）

- **学术/实践依据**:
  - Moskowitz, Grinblatt (1999) "Do Industries Explain Momentum?" (JF): 动量效应很大程度上是行业动量驱动的，行业动量独立于个股动量存在
  - A股实证: 申万一级行业月度动量因子在A股有效性时强时弱，2017-2023年行业反转比行业动量更有效（A股行业轮动快，纯动量容易追高）。建议短周期用动量(20日)、长周期用反转(60日)的混合方案

- **主动发现/风险提示**:
  - **分散化价值最高但实现最复杂**：行业轮动需要新的架构层（行业因子计算+两层组合构建），不是简单加几个因子能解决的
  - **A股行业轮动的特殊性**：A股行业轮动速度快于美股，纯动量策略容易在政策驱动的快速轮动中被whipsaw。建议加入ind_breadth（行业宽度/扩散度）因子作为动量确认信号——只在行业内多数个股上涨（而非仅龙头拉动）时才认为行业动量有效
  - **行业截面太小的问题**：SW一级仅31个行业，截面IC计算噪声大。建议用SW二级(110个)提高截面数量，但需要注意细分行业内股票数量可能很少
  - **需要arch配合**：设计两层组合结构（行业配置层+个股选股层），回测引擎需要支持
  - **需要data配合**：拉取申万行业指数日线数据（如801010.SI-801880.SI），填充index_daily表
  - **需要alpha_miner配合**：开发行业层面因子计算模块

---

## 实施优先级建议

| 优先级 | 候选 | 理由 | 预计时间 |
|--------|------|------|---------|
| **P0** | 候选1: 质量成长 | 数据零缺口 + corr最低 + 框架已有 + 文献最强 | 2-3天 |
| **P1** | 候选2: 红利低波 | 数据基本就绪 + 实现极简 + 防御互补 | 1-2天 |
| **P2** | 候选3: 行业轮动 | 分散化最优但需新架构 + 数据缺口需补 | 5-7天 |

**组合考虑**：三个候选覆盖了三个正交维度：
- 候选1 (质量成长) = 基本面Alpha
- 候选2 (红利低波) = 防御型收益/下行保护
- 候选3 (行业轮动) = 配置Alpha（行业维度）

与基线(价量+反转Alpha)组合后，四个策略在因子来源、市场状态敏感性、换手率特征上均有显著差异，具备真正的分散化价值。

---

## 未选候选及理由

### 事件驱动策略（方向3）
- **未选原因**：DB中缺少业绩预告、解禁、增减持等事件数据。需要从Tushare/AKShare拉取多个事件源，数据工程量大（预计2-3周）。且事件驱动策略的频率通常很高（日频/事件触发），与当前月频框架不兼容，需要架构改造。建议推迟到Phase 2。
- **数据缺口**：业绩预告(forecast_vip)、解禁数据(share_float)、增减持(stk_holdertrade)均需新拉取。

### 市场状态自适应策略（方向4）
- **未选原因**：严格说这不是一个独立策略，而是一个策略配置层（Meta-Strategy）。它需要先有多个子策略（如上述候选1/2/3），然后根据市场状态动态调整子策略权重。在子策略未经验证前，自适应层没有可操作的对象。建议在3个候选完成验证后，作为Phase 1C或Phase 2的组合层实现。
- **补充**：市场状态判别模型本身值得预研，建议alpha_miner或ml角色开始收集牛/熊/震荡的特征信号（如MA20/MA60交叉、波动率水位、融资余额变化等），为后续自适应层做准备。

---

## 待跟进事项

1. **[请求alpha_miner]**：为候选1计算roe_stability因子（近4季度ROE的std），纳入factor_registry
2. **[请求alpha_miner]**：将dv_ttm从daily_basic转为标准化因子纳入factor_values
3. **[请求data]**：评估补充申万一级行业指数日线到index_daily的工作量和积分消耗
4. **[请求data]**：确认moneyflow_daily拉取计划（候选3增强项）
5. **[请求quant]**：审查候选1的PIT对齐方案是否正确（ann_date vs report_date）
6. **[请求quant]**：评估红利低波与基线在市场状态层面的相关性（是否如我担心的在成长牛市中同时跑输）
7. **[自身后续]**：候选1验证后，设计4策略组合的权重方案（等权/风险平价/动态调整）

---

*本文档由strategy角色维护，每次更新需记录版本和日期。*
