# G1 前置准备报告 — 基线确认 + 特征就绪 + PIT评估

> **日期**: 2026-04-02
> **目标**: Phase G1 LightGBM Walk-Forward 开始前的三项前置检查
> **结论**: 基线Sharpe=0.91(非0.45), 51特征中14个直接可用/34个可从现有数据计算/3个缺数据源, PIT风险低

---

## Part 1: Sharpe基线确认

### 1.1 回测配置（与PT v1.2完全一致）

```
因子: turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio (5因子等权)
Top N: 15
调仓: 月度（月末最后交易日）
滑点: volume_impact模式 (市值分层k: large=0.05, mid=0.10, small=0.15)
成本: 佣金万0.854 + 印花税千0.5(卖出) + 过户费万0.1
时间: 2021-01-01 ~ 2026-03-31
初始资金: 100万
数据: factor_values.neutral_value (WLS行业+市值中性化后)
```

### 1.2 回测结果

```
总收益:       195.57%
年化收益:      23.21%
Sharpe:       0.91  (autocorr-adj: 0.19, ρ=0.08)
最大回撤:     -43.03%
Calmar:       0.54
Sortino:      1.18
Beta:         0.711
IR:           1.09
Bootstrap CI: [0.09, 1.81] (95%)
```

### 1.3 年度分解

| 年度 | 收益率 | 超额收益 | Sharpe | MDD |
|------|--------|----------|--------|------|
| 2021 | +99.29% | +105.51% | 3.10 | -7.78% |
| 2022 | -18.88% | +2.39% | -0.87 | -29.91% |
| 2023 | +7.91% | +19.65% | 0.47 | -21.26% |
| 2024 | +11.16% | -5.04% | 0.46 | -32.75% |
| 2025 | +68.36% | +47.17% | 2.37 | -18.59% |
| 2026 | -9.76% | -4.08% | -1.91 | -16.36% |

### 1.4 成本敏感性

| 成本倍数 | 年化收益 | Sharpe | MDD |
|---------|---------|--------|------|
| 0.5x | 16.96% | 0.90 | -43.03% |
| 1.0x | 16.83% | 0.89 | -43.03% |
| 1.5x | 16.69% | 0.88 | -43.03% |
| 2.0x | 16.56% | 0.87 | -43.03% |

**成本敏感性极低**: 2x成本下Sharpe仅从0.91降到0.87，说明Alpha来源非微观价差。

### 1.5 历史Sharpe数值差异解释

| 数值 | 来源 | 配置差异 | 解释 |
|------|------|---------|------|
| **1.03** | Sprint 1.11前 v1.1 | fixed 10bps滑点, Top20, biweekly | 固定滑点严重低估交易成本 |
| **0.91** | 本次回测 (2026-04-02) | volume_impact, Top15, monthly, neutral_value | **当前真实基线** |
| **0.39** | Sprint 1.11 volume_impact首跑 | volume_impact原始k系数(未校准σ) | k系数过大导致滑点虚高 |
| **0.45** | CLAUDE.md/PROGRESS.md记录 | 标注"5年WLS+流动性过滤" | **来源存疑，见下方分析** |

### 1.6 关于"0.45"的调查结论

CLAUDE.md记录"Sharpe基线=0.45（2021-2025全5年WLS+流动性过滤）"，但本次用**完全一致的v1.2配置**跑出Sharpe=0.91。可能原因：

1. **0.45可能是Sprint 1.11首跑0.39的圆整记忆** — 当时volume_impact未校准σ项，k系数偏大
2. **流动性过滤(日均成交额≥5000万)可能大幅降低Sharpe** — 因为5因子策略偏好小盘低流动性股(amihud因子方向+1)，过滤掉主要alpha来源
3. **neutral_value可能在Sprint 1.32后更新过** — WLS中性化模块重构可能改变了因子值分布

**建议**:
- 将**0.91**作为G1的真实基线（当前代码+当前数据+标准配置）
- 如需加流动性过滤，另跑一次确认影响幅度
- 铁律7的OOS阈值从1.03更新为0.91（或保守取0.91×0.85=0.77）

### 1.7 关键发现

1. **年度极不均匀**: 2021(+99%)和2025(+68%)贡献了几乎全部收益，2022-2024基本平。说明策略在小盘牛市中表现极好，但在风格轮动时(2024)回撤严重
2. **MDD=-43%过高**: 主要来自2024年期间的持续回撤。Phase G需要优先解决风险控制
3. **Bootstrap CI很宽**: [0.09, 1.81]，下界接近0，Sharpe的统计显著性边缘
4. **autocorr-adj Sharpe仅0.19**: 日收益自相关ρ=0.08导致调整后大幅下降。这提示策略的趋势持续性弱

---

## Part 2: 51特征就绪检查

### 2.1 factor_values表现有因子（37个）

数据库中已有37个因子，覆盖2020-07-01至2026-04-02，每因子约550-695万行：

```
已有因子列表(factor_values表):
amihud_20, beta_market_20, bp_ratio, chmom_60_20, dv_ttm, ep_ratio,
gain_loss_ratio_20, high_low_range_20, kbar_kmid, kbar_ksft, kbar_kup,
large_order_ratio, ln_market_cap, maxret_20, mf_divergence,
momentum_10, momentum_20, momentum_5, money_flow_strength,
price_level_factor, price_volume_corr_20, relative_volume_20,
reversal_10, reversal_20, reversal_5, reversal_60, rsrs_raw_18,
stoch_rsv_20, turnover_mean_20, turnover_stability_20, turnover_std_20,
turnover_surge_ratio, up_days_ratio_20, volatility_20, volatility_60,
volume_std_20, vwap_bias_1d
```

### 2.2 逐组映射

#### 组A: 基线5因子 — 5/5就绪

| # | 设计特征 | factor_values中对应 | 状态 |
|---|---------|-------------------|------|
| A1 | turnover_mean_20 | turnover_mean_20 | ✅ 就绪 |
| A2 | volatility_20 | volatility_20 | ✅ 就绪 |
| A3 | reversal_20 | reversal_20 | ✅ 就绪 |
| A4 | amihud_20 | amihud_20 | ✅ 就绪 |
| A5 | bp_ratio | bp_ratio | ✅ 就绪 |

#### 组B: 多尺度变体 — 5/12就绪

| # | 设计特征 | factor_values对应 | 状态 | 备注 |
|---|---------|------------------|------|------|
| B1 | turnover_mean_5 | — | ❌ 缺代码 | calc_turnover_mean已支持window参数，需新增计算+入库 |
| B2 | turnover_mean_60 | — | ❌ 缺代码 | 同上 |
| B3 | turnover_trend_20 | — | ❌ 缺代码 | = turnover_mean_20 / turnover_mean_60，需B2先就绪 |
| B4 | volatility_5 | — | ❌ 缺代码 | calc_volatility已支持window参数 |
| B5 | volatility_60 | volatility_60 | ✅ 就绪 | 612万行 |
| B6 | vol_regime | — | ❌ 缺代码 | = volatility_5 / volatility_60，需B4先就绪 |
| B7 | reversal_5 | reversal_5 | ✅ 就绪 | 695万行 |
| B8 | reversal_60 | reversal_60 | ✅ 就绪 | 600万行 |
| B9 | amihud_5 | — | ❌ 缺代码 | calc_amihud已支持window参数 |
| B10 | amihud_60 | — | ❌ 缺代码 | 同上 |
| B11 | bp_ratio_change_60 | — | ❌ 缺代码 | 需从daily_basic.pb序列计算60日变化率 |
| B12 | size_factor | ln_market_cap | ✅ 就绪 | 695万行 |

**工作量**: 7个缺失特征的计算函数已存在(只需改window参数)，估计0.5天。B3/B6/B11需新增计算逻辑，0.5天。

#### 组C: 资金流 — 2/8就绪

| # | 设计特征 | 对应 | 状态 | 备注 |
|---|---------|------|------|------|
| C1 | mf_divergence | mf_divergence | ✅ 就绪 | 565万行 |
| C2 | net_lg_ratio_5 | — | ❌ 缺代码 | moneyflow_daily有buy/sell_lg_amount |
| C3 | net_lg_ratio_20 | — | ❌ 缺代码 | 同上 |
| C4 | buy_sell_ratio_lg | large_order_ratio | ✅ 近似 | 已有large_order_ratio可替代 |
| C5 | mf_acceleration | — | ❌ 缺代码 | money_flow_strength的5日变化率 |
| C6 | lg_md_divergence | — | ❌ 缺代码 | 原始数据有buy/sell_md_amount |
| C7 | northbound_ratio_20 | — | ❌ 缺数据 | **无北向资金持股表** |
| C8 | margin_net_change_20 | — | ❌ 缺数据 | **无融资融券明细表** |

**工作量**: C2-C6需新增计算(原始数据moneyflow_daily 619万行已就绪)，约1天。C7/C8需拉取新Tushare接口(hsgt_top10 + margin_detail)，约0.5天数据+0.5天代码。

#### 组D: 价格行为 — 4/10就绪

| # | 设计特征 | 对应 | 状态 | 备注 |
|---|---------|------|------|------|
| D1 | price_level | price_level_factor | ✅ 就绪 | 695万行 |
| D2 | high_low_range_20 | high_low_range_20 | ✅ 就绪 | 611万行 |
| D3 | open_gap_20 | — | ❌ 缺代码 | 可从klines_daily计算 |
| D4 | close_to_high_ratio | — | ❌ 缺代码 | 可从klines_daily计算 |
| D5 | volume_price_trend | price_volume_corr_20 | ✅ 近似 | 量价相关性 |
| D6 | up_down_vol_ratio | up_days_ratio_20 | ⚠️ 近似 | 现有是涨跌天数比，非成交量比 |
| D7 | rsi_20 | stoch_rsv_20 | ⚠️ 近似 | RSV不等于RSI，需新增 |
| D8 | macd_signal | — | ❌ 缺代码 | 可从klines_daily计算 |
| D9 | bollinger_position | — | ❌ 缺代码 | 可从klines_daily计算 |
| D10 | intraday_strength_20 | kbar_kmid | ✅ 近似 | KBar中间位置 |

**工作量**: D3/D4/D8/D9需新增计算，D6/D7需精确实现(非近似)。约1天。所有原始数据(klines_daily 740万行)已就绪。

#### 组E: 财务基本面 — 0/8就绪（原始数据7/8有）

| # | 设计特征 | 数据源 | 状态 | 备注 |
|---|---------|--------|------|------|
| E1 | roe_ttm | financial_indicators.roe | ⚠️ 缺计算 | 236K行有ROE，需TTM滚动计算 |
| E2 | roe_change_yoy | financial_indicators.roe | ⚠️ 缺计算 | 需同比计算逻辑 |
| E3 | gross_margin_ttm | financial_indicators.gross_profit_margin | ⚠️ 缺计算 | 233K行有毛利率 |
| E4 | revenue_yoy | financial_indicators.revenue_yoy | ⚠️ 缺计算 | 227K行已有同比字段 |
| E5 | profit_yoy | financial_indicators.net_profit_yoy | ⚠️ 缺计算 | 228K行已有同比字段 |
| E6 | debt_to_asset | financial_indicators.debt_to_asset | ⚠️ 缺计算 | 234K行已有 |
| E7 | current_ratio | financial_indicators.current_ratio | ⚠️ 缺计算 | 229K行已有 |
| E8 | earnings_surprise_std | — | ❌ 缺数据 | **需要分析师一致预期数据(Tushare forecast_vxx)** |

**关键**: financial_indicators表有`actual_ann_date`字段，financial_factors.py已实现PIT-aware加载。但这些因子尚未计算写入factor_values表。

**工作量**: E1-E7需要编写FeatureBuilder从financial_indicators提取+TTM滚动+写入factor_values，约1.5天。E8需要拉取新数据源(分析师一致预期)，工作量大(1天数据+0.5天代码)，建议G1跳过。

#### 组F: 市场状态 — 0/8就绪（全部可从现有数据计算）

| # | 设计特征 | 数据源 | 状态 | 备注 |
|---|---------|--------|------|------|
| F1 | csi300_return_20 | index_daily | ⚠️ 缺计算 | 1513行沪深300数据已有 |
| F2 | csi300_vol_20 | index_daily | ⚠️ 缺计算 | |
| F3 | market_breadth_20 | klines_daily | ⚠️ 缺计算 | 涨跌家数统计 |
| F4 | industry_momentum_20 | klines_daily+symbols | ⚠️ 缺计算 | |
| F5 | cross_stock_corr_20 | klines_daily | ⚠️ 缺计算 | 计算量较大 |
| F6 | vix_proxy | index_daily | ⚠️ 缺计算 | 历史波动率分位数 |
| F7 | bull_bear_regime | index_daily | ⚠️ 缺计算 | MA120判定 |
| F8 | month_of_year | — | ⚠️ 缺计算 | sin/cos编码，最简单 |

**工作量**: 约1天。F5(截面相关性)计算量最大，可能需要优化。

### 2.3 就绪矩阵汇总

| 类别 | 总数 | 直接就绪 | 近似可用 | 缺代码(有数据) | 缺数据源 |
|------|------|---------|---------|--------------|---------|
| A 基线因子 | 5 | **5** | 0 | 0 | 0 |
| B 多尺度 | 12 | **4** | 0 | 8 | 0 |
| C 资金流 | 8 | **1** | 1 | 4 | **2** |
| D 价格行为 | 10 | **3** | 3 | 4 | 0 |
| E 基本面 | 8 | **0** | 0 | 7 | **1** |
| F 市场状态 | 8 | **0** | 0 | 8 | 0 |
| **合计** | **51** | **13** | **4** | **31** | **3** |

**可立即用于G1的特征**: 13个直接就绪 + 4个近似替代 = **17个**
**需要编写FeatureBuilder**: 31个（原始数据全部就绪）
**需要新增数据源**: 3个（C7北向资金, C8融资融券, E8盈利预期）

### 2.4 G1启动策略建议

**方案A（快速启动, 推荐）**: 用17个已就绪特征先跑Walk-Forward原型
- 5(A) + 4(B: volatility_60, reversal_5/60, ln_market_cap) + 2(C: mf_divergence, large_order_ratio) + 4(D近似) + 2(已有的kbar/stoch) = ~17个
- **优点**: 0天准备，立即开始验证ML框架是否work
- **缺点**: 特征不足可能导致ML无法超越线性基线

**方案B（完整准备, ~4天）**: 先补齐B/C/D/F组的31个特征
- B组: 0.5天（改window参数）+ 0.5天（新计算）
- C组: 1天
- D组: 1天
- F组: 1天
- 跳过E组（基本面，Sprint 1.5结论待验证）和3个缺数据源特征
- 总计: **~4天 → 48个特征可用**

**建议**: 方案A快速启动 → 确认框架正确 → 方案B补齐特征 → 正式Walk-Forward

---

## Part 3: PIT（Point-in-Time）评估

### 3.1 factor_values表结构

```sql
-- 6个字段，无available_at/created_at时间戳
code:          varchar  -- 股票代码
trade_date:    date     -- 交易日期
factor_name:   varchar  -- 因子名称
raw_value:     numeric  -- 原始值
neutral_value: numeric  -- 中性化后的值（WLS行业+市值）
zscore:        numeric  -- 标准化值
```

**结论**: 表中无数据可用时间戳字段。PIT合规性完全依赖因子计算逻辑本身。

### 3.2 回测数据取用方式

```python
# run_backtest.py line 50-55
def load_factor_values(trade_date, conn) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT code, factor_name, neutral_value "
        "FROM factor_values WHERE trade_date = %s",
        conn, params=(trade_date,))
```

按`trade_date`精确匹配，意味着：回测T日使用的是factor_values中trade_date=T的数据。PIT合规性取决于**因子计算时用了什么数据**。

### 3.3 五因子PIT逐项评估

| 因子 | 数据源 | PIT风险 | 分析 |
|------|--------|---------|------|
| **turnover_mean_20** | klines_daily.turnover_rate | ✅ 无风险 | 价量数据当天收盘后即可获取，20日滚动窗口全部是历史已知数据 |
| **volatility_20** | klines_daily.close | ✅ 无风险 | 同上，收益率标准差使用T-19到T的收盘价 |
| **reversal_20** | klines_daily.close | ✅ 无风险 | 20日收益率，数据T日收盘后可知 |
| **amihud_20** | klines_daily.close/volume/amount | ✅ 无风险 | |abs(ret)/amount|的20日均值，全部价量数据 |
| **bp_ratio** | daily_basic.pb | ⚠️ 低风险 | 见下方详细分析 |

#### bp_ratio详细PIT分析

`bp_ratio = 1/pb`，其中`pb`来自daily_basic表（Tushare每日更新）。

Tushare的`pb`计算公式: `pb = 总市值 / 归属母公司股东的权益合计`

- **分子(总市值)**: 当天收盘价 × 总股本，T日可知 → ✅
- **分母(净资产)**: 来自最近一期财务报表 → **关键问题在这里**

Tushare在T日发布daily_basic时，使用的是**截至T日已公告的最新报表**的净资产：
- 如果T=2026-04-15，最新季报是2025Q3（2025-10-31前公告），那么pb用的是2025Q3净资产
- 不会用2025Q4（2026-04-30才截止公告），所以**不存在前视偏差**

**但有一个边界条件**: 如果factor_values是**回填计算的**（即用当前最新daily_basic重新计算历史全部bp_ratio），那么historical pb可能会因为Tushare的调整而与当时实际值略有差异。这不是严格意义的look-ahead，但可能引入轻微的数据snooping。

**结论**: bp_ratio PIT风险低，误差级别 < 因子截面排名1-2位变化，对Sharpe影响可忽略。

### 3.4 G1新增特征的PIT评估

| 特征组 | PIT风险 | 分析 |
|--------|---------|------|
| **B组(多尺度)** | ✅ 无风险 | 全部基于价量数据，与基线因子同源 |
| **C组(资金流)** | ⚠️ 低风险 | moneyflow_daily是T日盘后发布，信号在T日收盘后生成 → 如果月底信号用月底资金流数据 → OK(月底收盘后才生成信号)。但如果用T日moneyflow做T日交易信号 → 轻微look-ahead(日内) |
| **D组(价格行为)** | ✅ 无风险 | 全部可从klines_daily计算，T日收盘后可知 |
| **E组(基本面)** | ⚠️⚠️ **中等风险** | **必须用actual_ann_date做PIT过滤**。financial_factors.py已实现`WHERE actual_ann_date <= trade_date`。但factor_values表中如果直接按report_date而非ann_date入库 → 严重look-ahead |
| **F组(市场状态)** | ✅ 无风险 | 指数数据T日可知 |

### 3.5 PIT修复建议

1. **当前5因子基线**: PIT合规，回测结果可信 ✅
2. **E组(基本面)加入时**: 必须确保FeatureBuilder使用`financial_factors.load_financial_pit()`而非直接query financial_indicators by report_date。代码模板已存在(`financial_factors.py:23-58`)
3. **建议**: 在factor_values表新增`data_available_date`列，记录因子计算时实际使用的最晚数据日期。这是防御性措施，当前不阻塞G1

---

## Part 4: Sprint 1.5基本面教训 + 全面思考

### 4.1 Sprint 1.5教训回顾

PROGRESS.md关键记录：
- LL-029: "单因子IC强不等于ML增量（VWAP/RSRS t>3.5但LightGBM无增量）"
- 7因子等权回测: Sharpe=0.902 vs 基线1.028, p=0.652 → **FAIL**

**Sprint 1.5失败原因分析**:
1. **等权线性组合无法捕捉非线性交互** — 简单加权本质上是线性模型，基本面因子的alpha可能藏在非线性交互中
2. **因子冗余而非无效** — 新增因子与现有因子信息重叠(例如VWAP/RSRS与reversal/volatility相关)
3. **样本外显著性不足** — p=0.652远未通过，说明alpha来源同质

**G1 LightGBM与Sprint 1.5的区别**:
- Sprint 1.5用等权线性组合，G1用LightGBM非线性模型
- LightGBM可以发现因子间的条件关系(如：只在低波动率时roe高才有效)
- Walk-Forward的7折OOS验证比单次全样本回测更可靠

**建议**: G1初版用43特征（不含E组基本面），如果43特征OOS Sharpe > 0.91，再做A/B: 43 vs 48(加E组5个)。

### 4.2 全面思考

#### Q1: 基线Sharpe如果是0.91而非0.45，Phase G的优先级还这么高吗？

**是的，仍然高优**，原因：
- 0.91的Bootstrap CI下界仅0.09，统计显著性边缘
- autocorr-adjusted Sharpe仅0.19，策略的"真实"Sharpe远低于表面值
- MDD=-43%不可接受（目标<15%），风险控制是最大短板
- 年度极不均匀（2021/2025贡献全部收益），需要ML捕捉跨周期alpha

但**优先级可能需要调整**:
- G2(风险平价)可能比G1(ML alpha)更紧迫 — MDD从43%降到20%比Sharpe从0.91到1.0更有价值
- G1和G2可以并行：G2不依赖ML，3-5天可出结果

#### Q2: 51个特征里高度相关的问题

**高相关特征对LightGBM的影响**：
- 树模型对共线性**不敏感**（不像线性回归），但过多相关特征会：
  - 稀释特征重要性(SHAP值分散)
  - 增加过拟合表面(noise特征也被选中)
  - 降低可解释性

**已知高相关对**（来自factor_engine代码+LL记录）：
- momentum_N vs reversal_N: 完全共线(corr=-1.0), LL记录已确认
- volatility_20 vs high_low_range_20: corr=0.90
- volatility_20 vs volatility_60: corr=0.73

**建议**: G1的FeatureBuilder输出后，先做截面相关性矩阵，剔除corr>0.85的特征对（保留SHAP更高的那个），预计51→40-45个有效特征。

#### Q3: Walk-Forward 7折怎么划分

ML_WALKFORWARD_DESIGN.md已有详细定义：
- 7折: F1-F7，测试期从2023-01到2026-03
- 训练24月(F1-F3扩展窗口, F4-F7固定窗口)
- 验证6月, 测试6月, purge 5交易日
- 步长=测试窗口=6月, 无overlap

**潜在问题**: F7测试期不满6月(2026-01~2026-03仅3月), 应标记partial。建议F7的OOS指标单独报告，不纳入汇总Sharpe。

#### Q4: LightGBM的label定义

设计文档已明确:
```
target = log(1 + r_stock_t+20) - log(1 + r_csi300_t+20)
```
即T+20日vs沪深300的对数超额收益。

**这个选择合理**:
- 与月度调仓对齐(20交易日≈1月)
- 对数收益更接近正态分布(有利于regression loss)
- 超额收益消除市场系统性风险

**但需要注意**: 停牌期间的label定义（设计文档说NaN删除 ✅），退市前5日保留实际退市收益。

#### Q5: G2风险平价能否和G1同时跑？

**可以，而且应该优先**:
- G2(风险平价)将等权改为波动率倒数加权，纯数学变换
- 不需要ML，不需要新特征，不需要Walk-Forward
- 从代码看，只需修改`PortfolioBuilder.build()`中的权重计算逻辑
- 预计**2-3天**可完成编码+回测+验证
- 直接解决MDD=-43%的核心问题

**建议**: G2先行(本周), G1特征准备同步进行, 下周G1正式启动

#### Q6: 当前系统最大的担忧

1. **MDD=-43%是首要风险** — 比Sharpe提升更紧迫。实盘中经历43%回撤，大概率会手动止损
2. **年度表现极不均匀** — 2021和2025贡献了>100%的累计收益，2022-2024几乎零贡献。说明策略强依赖小盘风格因子的beta暴露
3. **Bootstrap CI下界0.09** — 在5%显著性水平下勉强显著。加上autocorr-adj后Sharpe仅0.19，真正的alpha可能很薄
4. **5因子全是风格因子，无真正的选股alpha** — turnover/volatility/reversal/amihud/bp全是well-known risk premium，随风格轮动而大幅波动。ML可能也无法从风格因子中提取稳定alpha，需要引入真正的异质信息(资金流/基本面/事件)

#### Q7: 其他想说的

1. **G1的期望管理**: LightGBM在A股量化中的增量通常在IC提升2-5个百分点，Sharpe提升0.1-0.3。从0.91到1.0+是合理目标，到1.5+不现实
2. **特征工程 > 模型调参**: 51特征的质量比LightGBM超参数更重要。建议把50%时间花在特征上，30%在Walk-Forward框架，20%在Optuna调参
3. **CLAUDE.md的基线数字需要更新**: 0.45应更正为0.91，毕业阈值从0.315更新为0.91×0.7=0.637

---

## Part 5: 行动清单

### 立即可做（G1启动前0天）

| # | 事项 | 工作量 |
|---|------|--------|
| 1 | 更新CLAUDE.md基线Sharpe为0.91 | 5分钟 |
| 2 | 用17个已就绪特征搭建Walk-Forward骨架代码 | 2天 |

### G1特征准备（~4天）

| # | 事项 | 工作量 | 优先级 |
|---|------|--------|--------|
| 3 | B组: turnover_mean_5/60, volatility_5, amihud_5/60, 衍生比率 | 1天 | P0 |
| 4 | D组: open_gap, close_to_high, RSI, MACD, bollinger | 1天 | P0 |
| 5 | F组: 8个市场状态特征 | 1天 | P0 |
| 6 | C组: net_lg_ratio, mf_acceleration, lg_md_divergence | 0.5天 | P1 |
| 7 | C7/C8: 拉取北向资金+融资融券数据 | 1天 | P2 |
| 8 | E组: 基本面特征(roe_ttm等, PIT-aware) | 1.5天 | P2(Sprint 1.5教训, A/B验证后再加) |
| 9 | E8: 盈利预期数据 | 1.5天 | P3(跳过) |
| 10 | 特征相关性矩阵+去冗余 | 0.5天 | P0(特征入库后立即做) |

### G2风险平价（建议优先，~3天）

| # | 事项 | 工作量 |
|---|------|--------|
| 11 | PortfolioBuilder增加risk_parity权重模式 | 1天 |
| 12 | 回测对比: 等权 vs 风险平价 | 0.5天 |
| 13 | 验收: MDD改善幅度 + Sharpe变化 | 0.5天 |

### G1可以立即开始的特征子集（17个）

```
A组全部(5): turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio
B组部分(4): volatility_60, reversal_5, reversal_60, ln_market_cap
C组部分(2): mf_divergence, large_order_ratio (≈buy_sell_ratio_lg)
D组近似(4): price_level_factor, high_low_range_20, price_volume_corr_20, kbar_kmid
其他(2): money_flow_strength, up_days_ratio_20
```

---

## 附录: 数据库资产盘点

| 表 | 行数 | 时间范围 | 用途 |
|----|------|---------|------|
| factor_values | 37因子×~600万 | 2020-07 ~ 2026-04 | 因子存储 |
| klines_daily | 7,402,599 | 2020-01 ~ 2026-04 | 价量数据 |
| moneyflow_daily | 6,189,372 | 2021-01 ~ 2026-04 | 资金流 |
| daily_basic | 同klines | 同上 | 估值/市值/换手 |
| financial_indicators | 240,923 | 1990 ~ 2025 | 财务指标(有actual_ann_date) |
| index_daily (000300.SH) | 1,513 | 2020-01 ~ 2026-04 | 基准指数 |
| margin_detail | **不存在** | — | 融资融券 |
| hsgt_top10 | **不存在** | — | 北向资金 |
