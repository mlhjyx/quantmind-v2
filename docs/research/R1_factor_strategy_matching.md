# R1: 因子-策略匹配框架研究报告

> **报告编号**: R1
> **日期**: 2026-03-27
> **作者**: strategy-designer (Opus)
> **状态**: 初版
> **交叉审查**: 待 quant-reviewer + risk-guardian + factor-researcher challenge

---

## 0. 摘要

QuantMind V2在Sprint 1.2-1.12期间累计进行了10+次策略验证实验，全部使用"等权Top-N月度调仓"单一框架。这导致多个统计上显著的因子（RSRS t=-4.35, mf_divergence IC=9.1%, PEAD IC=5.34%）在组合层面表现不佳。本报告提出一套基于因子信号特征的**可扩展分类框架**和策略匹配决策树，将因子按ic_decay半衰期、信号分布形态、触发机制三维度进行连续特征映射。初始聚类为4类（排序型/快排序型/事件型/调节型），但框架设计为数据驱动可扩展——新因子如果落在现有分区边界外可自动创建新类型（如混合型/条件型）。验证覆盖全部已测试因子（74个），不限于少数案例。报告给出了可执行的代码落地方案，与现有`BaseStrategy`/`StrategyRegistry`架构完全兼容。

---

## 1. 问题定义

### 1.1 为什么单一策略框架反复失败

我们的v1.1基线配置是：5因子等权合成 -> Top-15选股 -> 月度调仓 -> 等权分配。这个框架隐含三个假设：

1. **所有因子的信号都是截面排序可比的**。但RSRS是阈值突破信号（beta斜率突然下降=支撑位确认），不是"越高越好/越低越好"的连续排序值。
2. **所有因子的最优持有期都是~20个交易日（月度）**。但reversal_20的半衰期约10天，月度调仓已经错过了最佳退出点；bp_ratio的半衰期约60天，月度调仓反而换手过频。
3. **所有因子的Alpha可以线性加总**。但LL-018已证明9种线性合成方法全部劣于等权，等权是线性合成的全局最优——因为我们的5因子IC都在3-7%区间，差异不大到值得加权。

这三个假设在不同因子上分别崩溃的证据：

| 因子 | IC/t值 | 使用策略 | 结果 | 失败原因 |
|------|--------|----------|------|----------|
| RSRS (rsrs_raw_18) | t=-4.35 | 等权Top-15月度 | Sharpe=0.28 | 事件信号被当作排序信号，稀释在3000+股截面中 |
| RSRS | t=-4.35 | 单因子Top-15周度 | Sharpe=0.15 | 提频到weekly但仍用排序选股，换手37倍 |
| mf_divergence | IC=9.1% | v1.1+第6因子等权 | p=0.387 | 第6因子边际贡献被5因子噪声平均掉(LL-017) |
| PEAD | IC=5.34% | v1.1+第6因子等权 | Sharpe降0.085 | 事件信号(公告后20天)被月度调仓截断 |
| 7因子(+vwap+rsrs) | 各自PASS | 等权Top-15月度 | Sharpe=0.902 | 弱因子稀释强因子，换手+207% |

### 1.2 因子的本质差异

不同因子在以下4个维度存在根本差异，这些差异直接决定了适配的策略类型：

**维度1: 信号衰减速度 (ic_decay half-life)**

| 因子 | IC(1d) | IC(5d) | IC(10d) | IC(20d) | 半衰期 | 含义 |
|------|--------|--------|---------|---------|--------|------|
| reversal_20 | 5.2% | 4.1% | 3.2% | 2.1% | ~10天 | 短周期均值回复，月度已过期 |
| turnover_mean_20 | 6.4% | 5.8% | 5.1% | 4.2% | ~25天 | 中等持续性，月度合理 |
| volatility_20 | 6.9% | 6.3% | 5.6% | 4.5% | ~28天 | 中等持续性，月度合理 |
| amihud_20 | 2.2% | 2.0% | 1.9% | 1.7% | ~30天 | 慢衰减，月度合理 |
| bp_ratio | 5.2% | 5.1% | 5.0% | 4.8% | ~60天 | 极慢衰减，季度更优 |

**维度2: 信号分布形态**

- **连续排序型**: turnover/volatility/bp_ratio的截面分布接近正态，因子值的排序位置直接反映Alpha强度
- **稀疏触发型**: RSRS的有效信号集中在极端分位(如<5%分位)，90%的截面值是噪声
- **条件依赖型**: mf_divergence在特定市场环境下(如资金分歧放大时)才有效

**维度3: 触发机制**

- **持续型**: bp_ratio每天都有有效信号，适合定期调仓
- **脉冲型**: PEAD在公告后1-5天信号最强，20天后消失
- **条件型**: regime因子只在市场状态切换时产生信号

**维度4: 交易成本敏感度**

- 高换手因子(reversal): 信号强但频繁交易侵蚀收益
- 低换手因子(bp_ratio): 信号持久但更新慢
- 事件型因子(RSRS): 交易次数少但单次仓位变动大

---

## 2. 文献综述

### 2.1 学术界：因子投资的策略多样性

**MSCI因子投资框架** (MSCI白皮书): MSCI将因子分为6大类(Value/Momentum/Quality/Size/Volatility/Yield)，每类有独立的指数构建方法。关键观点：Value因子年化换手约20%，Momentum因子年化换手约100%——同一个"Top-N等权"框架不可能同时适配两者。

**AQR因子投资** (Asness, JPM 2023): 强调因子的实施细节(implementation)对最终表现的影响可以超过因子本身的Alpha。调仓频率、交易成本控制、信号平滑是三个最关键的实施参数。

**Timing the Factor Zoo** (Neuhierl et al.): 不同因子需要不同的择时信号。Value因子用宏观指标(利率/信用利差)择时效果好，Momentum因子用自身波动率择时效果好。统一择时模型不存在。

**Factor Zoo导航** (Springer 2021): 因子换手率是决定因子实际OOS表现的最关键变量。换手率调整后，很多"显著"因子变得不显著。

### 2.2 A股实证

**华安证券2025 -- 因子舒适区**: 提出"舒适度得分"概念，用分位数差值法量化单只股票对某因子的敏感度。中证1000增强IR=2.40，核心洞见是**不同因子在不同股票上的有效性不同**——某些股票天然"舒适"于某因子。

**华安证券2025 -- 动态因子配置**: 基于SJM(稀疏跳跃模型)做因子级牛熊识别，因子权重随市场状态动态调整。多因子组合IR从0.05提升到0.4。关键方法论：不是对组合择时，而是对单个因子择时。

**华泰/长江证券 -- 高频因子研究**: 结构化反转因子(用日内分钟数据计算)IC_IR可达1.0，是基础reversal_20的3倍。但需要分钟级数据，超出我们当前数据范围。

**A股反转实证** (知乎/复旦): A股市场反转效应远强于动量效应(与美股相反)。短期反转(5-20天)半衰期约10天，这与我们reversal_20的实测数据一致。

### 2.3 事件驱动策略文献

**PEAD (Post-Earnings Announcement Drift)**: 多篇学术研究确认A股存在盈余公告后漂移，但幅度弱于美股。最佳实践是：(1)设置Earnings Surprise阈值(>2sigma), (2)公告后1-5天建仓, (3)持有5-20个交易日, (4)XGBoost可增强选股。年化Alpha 10-25%（回测，不含成本）。

**RSRS阻力支撑**: 天风证券研报提出的技术指标。核心逻辑是回归斜率突破作为趋势信号。在我们的测试中t=-4.35（单因子Gate最强），但月度/周度排序选股都失败。

### 2.4 开源项目方案对比（详见第5节）

| 项目 | 策略框架 | 多策略支持 | 因子-策略匹配 |
|------|----------|-----------|-------------|
| Qlib | Alpha158 + RollingGen | 有TopkDropout/WeightStrategy | 无显式匹配，靠ML端到端 |
| QuantsPlaybook | 研报逐个复现 | 无统一框架 | 每篇研报自带策略 |
| BigQuant | 低代码平台 | 有策略模板 | 手动配置 |

---

## 3. A股适用性分析

### 3.1 T+1制度的影响

A股T+1规则对不同策略类型的影响截然不同：

- **排序型(月度)**: 影响最小。月度调仓间隔远大于T+1约束。
- **排序型(周度/日度)**: T+1导致买入后至少持有1天。日度策略的"当天买当天卖"不可能，周度策略的影响可控。
- **事件型**: 影响较大。公告当天(T日)发现信号，最早T+1开盘才能买入。如果T日尾盘已大涨（信号已price-in），T+1追买面临开盘跳空风险。
- **过滤型**: 影响最小。过滤条件通常是慢变量，T+1无影响。

**结论**: T+1对排序型月度策略（我们的v1.1）影响可忽略。但事件型策略需要特别设计"信号确认延迟"——不在信号当天执行，而是等待1-2天确认。

### 3.2 涨跌停的影响

| 策略类型 | 涨跌停影响 | 应对 |
|----------|-----------|------|
| 排序型(月度) | 轻微：调仓日个别股票封板买不进，替补即可 | unfilled_handling='substitute' |
| 排序型(周度) | 中等：高频调仓累积的封板概率更高 | 增大替补池(Top-N x 1.5) |
| 事件型 | 严重：事件触发日往往是涨停日(如利好公告)，买不进 | 延迟1-2日+限价委托 |
| 过滤型 | 轻微 | 标准处理 |

### 3.3 A股特有的因子特征

- **反转远强于动量**: A股散户占比高，过度反应后均值回复快。reversal_20半衰期~10天，比美股短。
- **价值因子长效**: bp_ratio半衰期~60天，A股价值因子与美股类似，慢变量。
- **流动性因子独特**: 换手率在A股有极强预测力(IC=-6.4%)，远强于美股。这与A股的高换手率特征有关。
- **资金流因子**: mf_divergence(IC=9.1%)利用了A股独有的Level-2资金流数据。
- **涨跌停制度创造事件**: A股的涨跌停板制度本身就创造了可交易的事件信号（如涨停板打开、跌停板反弹）。

---

## 4. 资金量级适用性

### 4.1 100万资金的约束

我们的初始资金为100万元。这意味着：

- **Top-15等权**: 每只股票约6.5万元。整手约束(100股)在大部分股票上不构成问题（除非股价>650元的贵州茅台级别）。
- **交易冲击可忽略**: 100万的单笔交易量(~6.5万)相对A股平均日成交额(亿级)微不足道。volume_impact滑点模型中，我们的交易量/日成交量<0.01%，冲击成本接近0。
- **策略容量不是瓶颈**: 任何在A股全市场中有效的因子策略，在100万资金下都不会有容量问题。

### 4.2 小资金的独特优势

1. **可以交易小盘股**: 小盘股的Alpha通常更大(amihud因子正是捕捉这一点)。大资金无法建仓小盘股，但100万可以。
2. **换手成本低**: 100万级别的交易不影响市场价格，实际滑点接近0。这意味着高频调仓策略(周度)的成本惩罚远小于大资金。
3. **可以更集中**: Top-15已经是相对集中的持仓。如果信号足够强，可以考虑Top-10甚至Top-5(但需要更强的风控)。
4. **灵活性**: 调仓执行可以在1-2分钟内完成，不需要分批建仓。

### 4.3 对策略匹配的影响

小资金让我们可以更激进地匹配策略——不需要担心容量问题。这意味着：
- 周度调仓的交易成本惩罚很小，可以为reversal_20等短半衰期因子使用周度频率
- 事件型策略的单次大仓位变动不会冲击市场
- 可以考虑更集中的持仓(Top-10)用于强信号因子

---

## 5. 竞品对比

### 5.1 Qlib (Microsoft)

**方案**: Qlib使用Alpha158因子集+LightGBM(或其他ML模型)端到端学习。策略层提供`TopkDropoutStrategy`（保留top-k，允许dropout避免频繁换手）和`WeightStrategy`（自定义权重）。

**优势**:
- ML端到端学习隐式解决了因子-策略匹配问题——模型直接输出排序
- `RollingGen`提供了时序交叉验证的标准流程
- 社区活跃，有大量公开的因子和策略实现

**劣势**:
- 仍然是单一的"排序选股"范式，没有事件驱动策略支持
- 没有显式的因子衰减分析和频率推荐
- Qlib的`TopkDropoutStrategy`固定频率调仓，没有按因子特性分频率的机制

**与我们的差异**: Qlib依赖ML来隐式解决匹配问题，我们需要显式的匹配框架（因为我们的LL-018已证明线性/ML合成在5因子等权场景下不优于简单等权）。

### 5.2 QuantsPlaybook (hugo2046)

**方案**: 券商研报复现合集(22+策略)，每个策略独立实现。包含RSRS择时、聪明钱因子、行业配置等。

**优势**:
- 策略多样性高——每篇研报自带策略，天然是"多策略"
- RSRS择时的实现可以直接参考
- 代码质量较高，可作为策略模板

**劣势**:
- 没有统一框架，22个策略是22个独立脚本
- 没有因子分类和策略匹配的方法论
- 没有组合管理（多策略如何分配资金）

**与我们的差异**: 我们需要的是在统一框架(`BaseStrategy`)内支持多种策略类型，而不是每个因子写一个独立脚本。

### 5.3 BigQuant

**方案**: 低代码平台，提供策略模板。

**优势**: 可视化配置，低门槛。

**劣势**: 闭源平台，不透明。策略模板有限。

**与我们的差异**: 我们是自建系统，需要代码级的灵活性。

### 5.4 竞品总结

没有现成的开源方案解决"因子-策略匹配"问题。Qlib用ML绕过了这个问题，QuantsPlaybook用独立脚本回避了这个问题。我们需要自建一套显式的匹配框架。

---

## 6. 推荐方案

### 6.1 因子分类标准

基于三个可量化指标将因子分为4类：

**指标1: IC衰减半衰期 (half_life_days)**
- 使用`factor_profile.py`中已实现的`fit_exponential_decay()`计算
- 输入: {1d: IC_1, 5d: IC_5, 10d: IC_10, 20d: IC_20}
- 输出: 半衰期(天)

**指标2: 信号稀疏度 (signal_sparsity)**
- 定义: 有效信号(|z-score|>2)占截面总股票数的比例
- 计算方法: 在历史截面上统计
- 高稀疏度(>80%有效): 连续排序型
- 低稀疏度(<20%有效): 稀疏触发/事件型

**指标3: 触发模式 (trigger_mode)**
- 持续触发: 每个截面都有有效排序(如bp_ratio)
- 条件触发: 只在特定条件下有信号(如RSRS突破阈值)
- 事件触发: 由外部事件驱动(如PEAD公告)

**初始四类因子定义（可扩展框架，非固定枚举）:**

> **重要**: 以下4类是基于当前已测试因子的初始聚类结果，不是固定分类。随着因子池扩大，
> 分类应由数据驱动自动扩展。`classify_factor()`输出的是连续特征向量(half_life, sparsity, trigger_score)，
> 当前4类是对这个特征空间的初始分区。如果新因子落在现有分区边界外，应自动创建新类型。

| 类型 | 半衰期 | 稀疏度 | 触发 | 典型因子 | 策略模板 |
|------|--------|--------|------|----------|----------|
| **排序型(Ranking)** | >15天 | >50%有效 | 持续 | bp_ratio, turnover, volatility, amihud | Top-N定期调仓 |
| **快排序型(Fast-Ranking)** | <15天 | >50%有效 | 持续 | reversal_20, reversal_5 | Top-N高频调仓 |
| **事件型(Event)** | N/A | <20%有效 | 条件/事件 | RSRS, PEAD | 阈值触发+固定持有期 |
| **调节型(Modifier)** | >60天 | N/A | 条件 | regime, volatility_target | 仓位调整/风险预算 |

**潜在的第5-N类（待验证）:**

| 潜在类型 | 特征 | 可能因子 | 触发条件 |
|----------|------|----------|----------|
| **混合型(Hybrid)** | 半衰期中等+低稀疏度，同时具有排序和事件特征 | mf_divergence(IC=9.1%但稀疏度~60%) | 当因子不能被干净地分到单一类型时 |
| **条件型(Conditional)** | 只在特定市场regime下有效 | 某些动量因子(牛市有效/熊市反转) | 需regime×因子交互测试确认 |
| **配对型(Paired)** | 需要两个因子同时满足条件才触发 | vwap+rsrs联合信号 | 单因子Gate PASS但独立策略失败时探索 |
| **自适应型(Adaptive)** | 根据市场状态自动切换策略参数 | 波动率+反转(高波时反转更强) | 当同一因子在不同regime表现差异>2倍时 |

**扩展机制**: 分类不是硬编码的if-else，而是基于特征向量的距离度量。当新因子与所有现有类型的距离>阈值时，自动标记为"未分类(Unclassified)"并触发人工审查+新类型定义。

### 6.2 每类因子的适配策略模板

#### 6.2.1 排序型 (Ranking) -- 对应 `EqualWeightStrategy`

**适用因子**: bp_ratio (半衰期~60天), turnover_mean_20 (~25天), volatility_20 (~28天), amihud_20 (~30天)

**策略参数**:
- 调仓频率: `monthly`（半衰期>15天的因子）
- 选股方式: 截面排序Top-N（现有逻辑不变）
- 权重方案: 等权（LL-018确认最优）
- 换手控制: `turnover_cap=0.50`
- 退出条件: 定期调仓自然退出（不在目标池则卖出）

**这就是我们现有的v1.1配置**，不需要改动。

#### 6.2.2 快排序型 (Fast-Ranking) -- 新增 `FastRankingStrategy`

**适用因子**: reversal_20 (半衰期~10天), reversal_5 (~5天)

**策略参数**:
- 调仓频率: `weekly` 或 `biweekly`（半衰期<15天）
- 选股方式: 截面排序Top-N（与排序型相同）
- 权重方案: 等权
- 换手控制: `turnover_cap=0.70`（高频调仓需要更宽松的换手限制）
- 退出条件: 定期调仓 + **信号反转强制退出**（如果持仓股因子值从Top-10%跌到Bottom-50%，提前卖出）
- **特殊约束**: `max_replace`限制每次最大换仓数（控制换手成本）

**与排序型的关键差异**: 调仓频率更高，换手约束更宽松，增加了信号反转退出机制。

**代码集成**: 继承`BaseStrategy`，覆盖`should_rebalance()`使用更高频率，新增`check_signal_reversal()`方法。

```python
# backend/engines/strategies/fast_ranking.py
class FastRankingStrategy(BaseStrategy):
    signal_type = SignalType.RANKING

    def should_rebalance(self, trade_date, conn):
        # 基于config.rebalance_freq (weekly/biweekly)
        ...

    def generate_signals(self, context):
        # 标准排序选股
        scores = self.compute_alpha(context.factor_df, context.universe)
        target = self.build_portfolio(scores, context.industry_map, context.prev_holdings)

        # 信号反转退出: 上期持仓中因子值恶化的提前卖出
        if context.prev_holdings:
            target = self._apply_signal_reversal_exit(target, scores, context)

        return StrategyDecision(target_weights=target, ...)

    def _apply_signal_reversal_exit(self, target, scores, context):
        """如果上期持仓股的因子排名从Top-10%跌到Bottom-50%，强制退出。"""
        ...
```

#### 6.2.3 事件型 (Event) -- 新增 `EventDrivenStrategy`

**适用因子**: RSRS (阈值突破), PEAD (盈余公告)

**策略参数**:
- 调仓频率: **不定期**——由信号触发，不是日历驱动
- 选股方式: **阈值过滤**（不是排序）。只选择信号强度超过阈值的股票
- 信号阈值: 因子z-score < -2.0 (RSRS) 或 earnings_surprise > 2sigma (PEAD)
- 持有期: 固定N天后退出（RSRS: 10天, PEAD: 20天）
- 仓位管理: 每个事件信号分配固定仓位（如每只股票3-5%）
- 最大同时持仓: 限制为K只（如10只）
- 退出条件: (1) 持有期到期自动退出, (2) 止损-5%强制退出, (3) 因子信号反转退出
- 空仓处理: 无信号时不开仓，资金闲置（持现金或配置在排序型策略中）

**与排序型的根本差异**:
1. 不是"每月选15只最好的"，而是"有信号就建仓，没信号就空仓"
2. 持仓数量不固定——可能0只（无信号），可能10只（多个信号同时触发）
3. 每只股票有独立的退出条件，不是统一调仓日全部换仓

**代码集成**:

```python
# backend/engines/strategies/event_driven.py
class EventDrivenStrategy(BaseStrategy):
    signal_type = SignalType.EVENT

    def should_rebalance(self, trade_date, conn):
        # 事件型每天都检查信号，但不一定触发调仓
        return True  # 每天检查，generate_signals内部决定是否有新操作

    def generate_signals(self, context):
        # 1. 检查新信号: 因子值突破阈值的股票
        new_signals = self._detect_events(context)

        # 2. 检查持有期到期: 已持仓股票是否到期
        exits = self._check_holding_period(context)

        # 3. 检查止损: 已持仓股票是否触发止损
        stop_losses = self._check_stop_loss(context)

        # 4. 合并: 新建仓 + 保持 + 退出
        target = self._merge_positions(new_signals, exits, stop_losses, context)

        return StrategyDecision(
            target_weights=target,
            is_rebalance=bool(new_signals or exits or stop_losses),
            signal_type=SignalType.EVENT,
            ...
        )

    def _detect_events(self, context):
        """检测因子值突破阈值的股票。"""
        threshold = self.config.get("signal_threshold", -2.0)
        max_positions = self.config.get("max_positions", 10)
        ...

    def _check_holding_period(self, context):
        """检查持仓股是否到达持有期上限。"""
        holding_days = self.config.get("holding_days", 10)
        ...

    def _check_stop_loss(self, context):
        """检查持仓股是否触发止损。"""
        stop_loss_pct = self.config.get("stop_loss_pct", -0.05)
        ...
```

**StrategyContext扩展需求**: 事件型策略需要知道每只股票的**建仓日期**和**建仓以来的收益率**。当前`StrategyContext.prev_holdings`只有权重没有时间信息。需要扩展：

```python
@dataclass
class StrategyContext:
    # ... 现有字段 ...
    position_details: Optional[dict[str, PositionDetail]] = None  # 新增

@dataclass
class PositionDetail:
    code: str
    weight: float
    entry_date: date
    entry_price: float
    unrealized_pnl: float
```

#### 6.2.4 调节型 (Modifier) -- 新增 `ModifierStrategy`（或作为插件）

**适用因子**: regime (市场状态), volatility_target (波动率目标)

**不是独立策略，而是叠加在其他策略之上的调节层**:
- 当regime=熊市时，将排序型策略的仓位缩减50%
- 当组合波动率>目标时，按比例缩减权重
- 当regime切换时，降低换手约束允许更快调仓

**代码集成**: 不需要新的Strategy子类。在现有`BaseStrategy.on_rebalance()`钩子中实现：

```python
# 在EqualWeightStrategy或FastRankingStrategy中覆盖on_rebalance
def on_rebalance(self, current_holdings, target_holdings):
    # 读取regime状态
    regime = self._get_current_regime()
    if regime == "bear":
        # 仓位缩减50%
        target_holdings = {k: v * 0.5 for k, v in target_holdings.items()}
    return target_holdings
```

这与Sprint 1.10已实现的"波动率regime缩放"(clip[0.5, 2.0])一致，不需要额外开发。

### 6.3 决策树：给定新因子，如何确定策略类型

```
输入: 新因子的 ic_decay, 截面分布, 触发机制

Step 1: 计算IC衰减半衰期
         └── 调用 factor_profile.fit_exponential_decay(ic_decay)
         └── 得到 half_life_days

Step 2: 计算信号稀疏度
         └── sparsity = count(|z-score| > 2) / total_stocks
         └── 在历史截面上取中位数

Step 3: 判断触发模式
         └── 如果因子依赖外部事件(公告/突破) → trigger = "event"
         └── 如果因子依赖市场状态切换 → trigger = "condition"
         └── 否则 → trigger = "continuous"

Step 4: 分类决策
         ├── trigger == "event" → 事件型 (EventDrivenStrategy)
         ├── trigger == "condition" AND half_life > 60 → 调节型 (Modifier)
         ├── sparsity < 0.20 AND trigger != "continuous" → 事件型
         ├── half_life < 15 → 快排序型 (FastRankingStrategy)
         └── 否则 → 排序型 (EqualWeightStrategy / MultiFreqStrategy)

Step 5: 确定策略参数
         ├── 排序型: freq=monthly, top_n=15, turnover_cap=0.50
         ├── 快排序型: freq=recommend_freq(half_life), top_n=15, turnover_cap=0.70
         ├── 事件型: threshold=config, holding_days=2*half_life, max_positions=10
         └── 调节型: 叠加到主策略的on_rebalance钩子
```

**代码实现** (新文件 `backend/engines/strategy_matcher.py`):

```python
from engines.factor_profile import FactorProfile, fit_exponential_decay, recommend_freq

@dataclass
class FactorClassification:
    """因子分类结果，包含连续特征向量和离散类型。"""
    factor_name: str
    factor_type: str              # "ranking" / "fast_ranking" / "event" / "modifier" / "hybrid" / "unclassified"
    feature_vector: dict          # {"half_life": float, "sparsity": float, "trigger_score": float}
    confidence: float             # 分类置信度 0-1，越低越可能是边界/混合型
    recommended_strategy: str     # 推荐策略类名
    notes: str = ""               # 人工审查备注

# 已注册的类型中心点（可扩展，新类型通过register_factor_type添加）
FACTOR_TYPE_REGISTRY = {
    "ranking":      {"half_life": (15, 120), "sparsity": (0.5, 1.0), "trigger": "continuous"},
    "fast_ranking": {"half_life": (1, 15),   "sparsity": (0.5, 1.0), "trigger": "continuous"},
    "event":        {"half_life": (0, 999),  "sparsity": (0.0, 0.2), "trigger": "event|condition"},
    "modifier":     {"half_life": (60, 999), "sparsity": (0.0, 1.0), "trigger": "condition"},
}

def classify_factor(profile: FactorProfile, signal_sparsity: float,
                    trigger_mode: str = "continuous") -> FactorClassification:
    """因子分类决策树（可扩展版本）。

    输出连续特征向量+离散类型+置信度。置信度<0.6的因子标记为"需人工审查"。
    不匹配任何已注册类型的因子标记为"unclassified"。

    Args:
        profile: 因子画像(含ic_decay, half_life_days)
        signal_sparsity: 有效信号占比(0-1)
        trigger_mode: "continuous" / "event" / "condition"

    Returns:
        FactorClassification (含类型、特征向量、置信度)
    """
    feature_vector = {
        "half_life": profile.half_life_days,
        "sparsity": signal_sparsity,
        "trigger_score": {"continuous": 0.0, "condition": 0.5, "event": 1.0}[trigger_mode],
    }

    # 决策逻辑（保持简单规则，不用ML）
    if trigger_mode == "event":
        factor_type, confidence = "event", 0.9
    elif trigger_mode == "condition" and profile.half_life_days > 60:
        factor_type, confidence = "modifier", 0.85
    elif signal_sparsity < 0.20 and trigger_mode != "continuous":
        factor_type, confidence = "event", 0.75
    elif profile.half_life_days < 15:
        factor_type, confidence = "fast_ranking", 0.8
    elif signal_sparsity > 0.50:
        factor_type, confidence = "ranking", 0.85
    else:
        # 落在边界区域 → 可能是混合型或新类型
        factor_type, confidence = "hybrid", 0.5

    # 边界情况降低置信度
    if 12 < profile.half_life_days < 18:  # 排序/快排序边界
        confidence *= 0.7
    if 0.15 < signal_sparsity < 0.25:     # 排序/事件边界
        confidence *= 0.7

    return FactorClassification(
        factor_name=profile.factor_name,
        factor_type=factor_type,
        feature_vector=feature_vector,
        confidence=confidence,
        recommended_strategy=STRATEGY_MAP.get(factor_type, "manual_review"),
        notes="需人工审查" if confidence < 0.6 else "",
    )

def recommend_strategy_config(factor_type: str, profile: FactorProfile) -> dict:
    """根据分类推荐策略配置。"""
    if factor_type == "ranking":
        return {
            "strategy_name": "equal_weight",
            "rebalance_freq": "monthly",
            "top_n": 15,
            "weight_method": "equal",
            "turnover_cap": 0.50,
        }
    elif factor_type == "fast_ranking":
        return {
            "strategy_name": "fast_ranking",
            "rebalance_freq": recommend_freq(profile.half_life_days),
            "top_n": 15,
            "weight_method": "equal",
            "turnover_cap": 0.70,
            "signal_reversal_exit": True,
        }
    elif factor_type == "event":
        return {
            "strategy_name": "event_driven",
            "holding_days": max(5, int(profile.half_life_days * 2)),
            "signal_threshold": -2.0,
            "max_positions": 10,
            "position_size": 0.05,  # 每只5%
            "stop_loss_pct": -0.05,
        }
    elif factor_type == "modifier":
        return {
            "strategy_name": "modifier",
            "target_strategy": "equal_weight",  # 叠加到哪个策略
            "regime_method": "vol_scaling",
            "scaling_range": [0.5, 2.0],
        }
```

### 6.4 全因子分类矩阵（不止4个案例）

> **原则**: 验证案例必须覆盖所有已测试/已实现因子，不是挑选代表。以下分为三组：
> A组(v1.1活跃因子), B组(Reserve池/已测试因子), C组(设计文档中待实现因子的预分类)。

**A组: v1.1活跃5因子（验证当前框架匹配度）**

| 因子 | ic_decay | 半衰期 | 稀疏度 | 触发 | 分类 | 推荐策略 | 当前策略 | 匹配度 |
|------|----------|--------|--------|------|------|----------|----------|--------|
| turnover_mean_20 | {1:6.4%, 20:4.2%} | ~25天 | >80% | 持续 | **排序型** | EqualWeight/Monthly | Monthly等权 | ✅完全匹配 |
| volatility_20 | {1:6.9%, 20:4.5%} | ~28天 | >80% | 持续 | **排序型** | EqualWeight/Monthly | Monthly等权 | ✅完全匹配 |
| amihud_20 | {1:2.2%, 20:1.7%} | ~30天 | >80% | 持续 | **排序型** | EqualWeight/Monthly | Monthly等权 | ✅完全匹配 |
| bp_ratio | {1:5.2%, 20:4.8%} | ~60天 | >80% | 持续 | **排序型** | EqualWeight/Monthly(季度更优) | Monthly等权 | ⚠️可降频 |
| reversal_20 | {1:5.2%, 20:2.1%} | ~10天 | >80% | 持续 | **快排序型** | FastRanking/Weekly | Monthly等权 | ❌错配(月度浪费半衰期) |

**结论**: v1.1的5因子中，4个匹配排序型/月度，1个(reversal_20)实际是快排序型。
但reversal_20与其他4因子组合使用时，月度框架是折中方案，独立拆出需要多策略组合支持。

**B组: Reserve池+已测试因子（需要重新匹配策略测试）**

| 因子 | IC/t值 | 半衰期(估) | 稀疏度(估) | 触发 | 分类 | 推荐策略 | 之前测试 | 是否需重测 |
|------|--------|-----------|-----------|------|------|----------|----------|-----------|
| **RSRS** | t=-4.35 | N/A | <10% | 条件突破 | **事件型** | EventDriven/信号触发 | 月度Sharpe=0.28 | ✅优先 |
| **mf_divergence** | IC=9.1% | ~8天 | ~60% | 持续 | **混合型⚠️** | FastRanking/Weekly或Hybrid | 等权第6因子p=0.387 | ✅优先 |
| **price_level** | IC=8.42% | 待测 | 待测 | 持续 | 待分类 | 待ic_decay数据 | 入池未组合测试 | ✅需ic_decay |
| **PEAD** | IC=5.34% | ~15天(公告后) | <20%(公告日) | 事件 | **事件型** | EventDriven/公告后建仓 | 等权第6因子降Sharpe | ✅优先 |
| **VWAP** | t=-3.53 | 待测 | 待测 | 持续 | 待分类 | 待ic_decay数据 | 月度等权无增量 | ✅需ic_decay |
| **IVOL** | IC=6.67% | 待测 | 待测 | 持续 | 待分类 | 可能排序型 | OOS Sharpe持平v1.1 | ⚠️需确认 |
| **big_small_consensus** | 原始IC=12.74% | N/A | N/A | 持续 | N/A | N/A | 中性化后IC=-1%虚假alpha | ❌已证伪 |
| **turnover_stability_20** | Reserve | 待测 | 待测 | 持续 | 待分类 | 待ic_decay数据 | 未测试 | ✅需完整测试 |

**注意**: mf_divergence稀疏度~60%，落在排序型(>50%)和事件型(<20%)的边界，分类为"混合型"，
置信度只有~0.5。需要测试两种策略(FastRanking/Weekly vs EventDriven/阈值)，选表现更好的。

**C组: 设计文档34因子中待实现的预分类（基于经济学先验）**

| 因子类别 | 预期分类 | 因子数 | 理由 |
|----------|----------|--------|------|
| 技术面-动量类(momentum系列) | 排序型或快排序型 | ~5个 | 连续信号，按半衰期分频 |
| 技术面-波动类(high_low_range等) | 排序型 | ~3个 | 与volatility_20类似 |
| 基本面-价值类(ep_ratio等) | 排序型(季度频率) | ~4个 | 慢变量，半衰期>60天 |
| 基本面-质量类(roe_growth等) | 排序型(季度频率) | ~3个 | 公告驱动但信号持久 |
| 资金流类(mf系列) | 快排序型或混合型 | ~4个 | 半衰期短，但稀疏度不确定 |
| 事件类(限售解禁/增减持等) | 事件型 | ~3个 | 明确的事件触发 |
| 另类数据(北向资金/融资余额等) | 待测定 | ~5个 | 需要实际ic_decay数据 |
| KBAR特征(已测试15个) | 排序型(3个独立候选入Reserve) | 3个 | 大部分与vol/rev冗余 |

**C组的分类在因子实现后需要用实际数据验证，先验分类仅作参考。**

**案例1: reversal_20 -- 从月度提频到周度**

当前状态: reversal_20是v1.1的5因子之一，使用月度调仓。但其半衰期~10天，月度调仓时信号已衰减到50%以下。

匹配建议: 如果reversal_20作为独立策略(或快排序子组合)，应使用weekly调仓。但注意：reversal_20目前与其他4个月度因子组合使用，拆分出来单独跑需要多策略组合框架。

当前不改动v1.1(锁死中)，但这个发现应该记录为Phase 1的优化方向。

**案例2: bp_ratio -- 月度调仓合理，季度可能更优**

当前状态: bp_ratio的半衰期~60天，使用月度调仓。`recommend_freq(60)`返回"monthly"，当前匹配合理。

匹配建议: 保持现状。如果未来有季度调仓选项，bp_ratio可以进一步降频以节省换手成本。

**案例3: RSRS -- 被"冤杀"的事件型因子**

当前状态: RSRS t=-4.35（单因子Gate全项目最强），但月度排序Sharpe=0.28，周度排序Sharpe=0.15。均NOT JUSTIFIED。

问题诊断: RSRS的有效信号集中在极端分位(<5%)。在3000+股截面中，大部分股票的RSRS值接近0（无信号）。把RSRS当作排序因子，Top-15选出来的股票信号强度差异很小。而且RSRS信号是脉冲型（突破后几天内最有效），月度/周度定期调仓无法捕捉这个时间窗口。

匹配建议: EventDrivenStrategy，配置如下：
```python
{
    "strategy_name": "event_driven",
    "factor_names": ["rsrs_raw_18"],
    "signal_threshold": -2.0,       # z-score < -2.0 触发
    "holding_days": 10,             # 持有10个交易日
    "max_positions": 10,            # 最多同时持有10只
    "position_size": 0.05,          # 每只5%
    "stop_loss_pct": -0.05,         # 止损-5%
    "confirmation_delay": 1,        # 信号确认延迟1天(避免追涨)
}
```

**验证优先级**: HIGH。RSRS是Sprint 1.12中被NOT JUSTIFIED的因子，如果事件型策略能让它Sharpe>0.5，就证明匹配框架有价值。

**案例4: mf_divergence -- 从等权第6因子到独立快排序**

当前状态: mf_divergence IC=9.1%（全项目最强），但加入v1.1等权6因子组合后增量不显著(p=0.387)。

问题诊断: LL-017分析——等权合成有天花板。当5因子IC在3-7%区间时，第6个因子的边际贡献被平均掉。mf_divergence的半衰期~8天，月度调仓已经浪费了大部分信号。

匹配建议: 作为独立FastRankingStrategy运行(weekly调仓)，然后在多策略组合层与v1.1排序型策略按风险预算分配权重。

### 6.5 多策略组合设计

当不同因子使用不同策略后，需要一个**组合层**将多个策略的仓位合并。

**核心-卫星架构**:

```
整体组合 (100万)
├── 核心策略 (70%): v1.1等权5因子月度 (排序型)
│   └── 因子: turnover_mean_20 + volatility_20 + reversal_20 + amihud_20 + bp_ratio
│   └── 策略: EqualWeightStrategy, monthly, Top-15
│
├── 卫星策略 (20%): 独立策略子组合
│   ├── 卫星A: mf_divergence快排序 (10%)
│   │   └── FastRankingStrategy, weekly, Top-10
│   └── 卫星B: RSRS事件驱动 (10%)
│       └── EventDrivenStrategy, signal-triggered
│
└── 现金缓冲 (10%): 应急+整手约束余量
```

**资金分配规则**:
1. 核心策略分配70%固定资金
2. 卫星策略各分配固定资金(10%/10%)
3. 各策略独立运行，互不干扰
4. 每月评估一次卫星策略表现，连续3月Sharpe<0则暂停该卫星
5. 现金缓冲10%用于整手约束余量和紧急调仓

**代码实现** (`backend/engines/strategies/composite.py`):

```python
class CompositeStrategy:
    """多策略组合管理器。

    不继承BaseStrategy（因为它不是单一策略），
    而是编排多个BaseStrategy子实例。
    """

    def __init__(self, strategies: list[dict]):
        """
        Args:
            strategies: [
                {"name": "core", "strategy": EqualWeightStrategy(...),
                 "allocation": 0.70},
                {"name": "satellite_mf", "strategy": FastRankingStrategy(...),
                 "allocation": 0.10},
                ...
            ]
        """
        self.strategies = strategies
        self.cash_buffer = 1.0 - sum(s["allocation"] for s in strategies)

    def generate_combined_signals(self, context):
        """运行所有子策略，合并目标持仓。"""
        combined = {}
        for strat_info in self.strategies:
            alloc = strat_info["allocation"]
            decision = strat_info["strategy"].generate_signals(context)
            # 按资金比例缩放权重
            for code, weight in decision.target_weights.items():
                combined[code] = combined.get(code, 0) + weight * alloc
        return combined
```

---

## 7. 落地计划

### 7.1 需要新建的文件

| 文件路径 | 内容 | 优先级 |
|----------|------|--------|
| `backend/engines/strategy_matcher.py` | 因子分类+策略推荐决策树 | P0 |
| `backend/engines/strategies/event_driven.py` | 事件驱动策略 | P0 |
| `backend/engines/strategies/fast_ranking.py` | 快排序策略 | P1 |
| `backend/engines/strategies/composite.py` | 多策略组合管理器 | P1 |
| `backend/tests/test_strategy_matcher.py` | 匹配决策树测试 | P0 |
| `backend/tests/test_event_driven.py` | 事件驱动策略测试 | P0 |
| `scripts/backtest_rsrs_event.py` | RSRS事件型策略回测验证 | P0 |

### 7.2 需要修改的文件

| 文件路径 | 修改内容 | 优先级 |
|----------|----------|--------|
| `backend/engines/base_strategy.py` | 扩展`StrategyContext`增加`position_details` | P0 |
| `backend/engines/strategy_registry.py` | 注册`event_driven`和`fast_ranking` | P0 |
| `backend/engines/backtest_engine.py` | SimBroker支持event型策略的持有期跟踪 | P0 |
| `backend/engines/factor_profile.py` | 增加`signal_sparsity`计算方法 | P1 |
| `backend/app/services/param_defaults.py` | 事件型策略参数注册到L2配置 | P2 |

### 7.3 不需要改动的文件

- `backend/engines/strategies/equal_weight.py` -- v1.1配置不动
- `backend/engines/signal_engine.py` -- SignalComposer/PortfolioBuilder不变
- `scripts/run_paper_trading.py` -- PT链路不动(v1.1锁死)

### 7.4 实施顺序

```
Phase 1a: 验证框架可行性 (1 Sprint)
  1. 实现strategy_matcher.py (决策树+单元测试)
  2. 实现EventDrivenStrategy (核心类+单元测试)
  3. 扩展StrategyContext (position_details)
  4. 扩展SimBroker (持有期跟踪)
  5. 用RSRS做第一个SimBroker回测验证

Phase 1b: 扩展和组合 (1 Sprint)
  6. 实现FastRankingStrategy
  7. 实现CompositeStrategy
  8. 用mf_divergence做FastRanking验证
  9. 核心-卫星组合回测

Phase 1c: 生产化 (1 Sprint)
  10. 参数配置集成(param_defaults)
  11. 前端页面支持(策略类型选择)
  12. PT链路集成(如果验证通过)
```

---

## 8. 测试方案

### 8.1 RSRS事件型策略作为第一个验证案例

**目标**: 证明"RSRS用事件型策略"的Sharpe显著高于"RSRS用排序型策略"(当前0.28/0.15)。

**成功标准**:
- Sharpe > 0.5 (显著好于排序型的0.28)
- Bootstrap 95% CI下界 > 0
- 年化换手率 < 10倍 (远低于排序型的37倍)
- 2024年不持续亏损(或亏损幅度< 10%)

**回测配置**:
```python
{
    "strategy_name": "event_driven",
    "factor_names": ["rsrs_raw_18"],
    "start_date": "2021-01-01",
    "end_date": "2025-12-31",
    "initial_capital": 1_000_000,
    "signal_threshold": -2.0,
    "holding_days": 10,
    "max_positions": 10,
    "position_size": 0.05,
    "stop_loss_pct": -0.05,
    "confirmation_delay": 1,
    "slippage_mode": "volume_impact",
}
```

**对比基准**: RSRS周度排序(Sharpe=0.15) + RSRS月度排序(Sharpe=0.28)

**测试脚本**: `scripts/backtest_rsrs_event.py`

### 8.2 mf_divergence快排序验证

**目标**: 证明mf_divergence独立运行weekly FastRanking的Sharpe > 加入v1.1等权组合的增量。

**成功标准**:
- 独立Sharpe > 0.5
- 与v1.1的相关性 < 0.5 (有分散化价值)

### 8.3 多策略组合验证

**目标**: 核心70%+卫星20%+现金10%的组合Sharpe > 纯v1.1的Sharpe(0.91)。

**成功标准**:
- 组合Sharpe > 0.95 (paired bootstrap p < 0.10)
- 组合MDD < v1.1 MDD
- 组合最差年度表现 > v1.1最差年度表现

### 8.4 全因子分类验证（N因子 × M策略矩阵）

**方法**: 不是只验证4个案例，而是对所有已测试因子做全覆盖验证。

**Step 1: 自动分类验证**
对FACTOR_TEST_REGISTRY中的74个已测试因子，全部跑一遍`classify_factor()`决策树：
- 检查分类结果是否与经济学直觉一致
- 标记置信度<0.6的"边界因子"供人工审查
- 输出分类分布（预期：排序型>50%, 快排序型~15%, 事件型~10%, 混合/未分类~25%）

**Step 2: 关键因子策略对比回测**
对A组+B组中的重点因子（≥8个），做N×M矩阵回测：

| 因子 | Ranking/Monthly | Ranking/Weekly | FastRanking/Weekly | EventDriven | 最优策略 |
|------|----------------|----------------|-------------------|-------------|----------|
| reversal_20 | 基线(v1.1) | 待测 | 待测 | N/A | 取Sharpe最高 |
| bp_ratio | 基线(v1.1) | N/A | N/A | N/A | 验证季度更优 |
| RSRS | 0.28(已测) | 0.15(已测) | N/A | 待测 | 对比事件型 |
| mf_divergence | p=0.387(已测) | 待测 | 待测 | 待测 | 混合型两种都测 |
| PEAD | 降Sharpe(已测) | N/A | N/A | 待测 | 事件型 |
| price_level | 未测 | 待测 | 待测 | N/A | 需先跑ic_decay |
| VWAP | 无增量(已测) | 待测 | 待测 | N/A | 需先跑ic_decay |
| IVOL | 持平(已测) | 待测 | N/A | N/A | 验证分类 |

**Step 3: 分类准确性验证**
最优策略应与`classify_factor()`的推荐一致。如果>30%因子的最优策略≠推荐策略，说明决策树需要调整。

**Step 4: 新因子自动化流程验证**
模拟新因子入池流程：factor_profile → classify_factor → recommend_strategy → backtest → 验证推荐是否合理。

---

## 9. 风险评估

### 9.1 多策略引入的新风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| **策略间相关性高** | 中 | 分散化失效 | 要求卫星与核心相关性<0.5 |
| **卫星策略持续亏损** | 中 | 拖累整体表现 | 连续3月Sharpe<0暂停卫星 |
| **事件型策略空仓期长** | 高 | 无信号期间资金闲置 | 闲置资金回流核心策略 |
| **复杂度增加导致bug** | 中 | 回测不可复现 | 确定性测试(CLAUDE.md规则3) |
| **SimBroker不支持持有期跟踪** | 确定 | 事件型无法回测 | 必须先扩展SimBroker |
| **过度拟合策略匹配** | 中 | 匹配规则本身过拟合 | 用简单规则(3个指标)，不ML |

### 9.2 Fallback方案

如果多策略组合表现不如纯v1.1：
1. **保持v1.1不动**（当前PT链路锁死，这是默认fallback）
2. 卫星策略仅在影子模式运行，收集真实信号但不实际交易
3. 60天后评估影子模式表现，决定是否切换到多策略

### 9.3 v1.1配置安全保证

**强调**: 本报告的所有建议**不影响当前PT链路**。v1.1配置锁死，Paper Trading继续跑60天。多策略框架是并行开发+影子验证，只有在严格验证通过后才可能替换v1.1。

### 9.4 最大的风险不是"多策略失败"而是"继续在单一框架打转"

回顾项目历史：从Sprint 1.2到1.12，我们在"等权Top-N月度"框架内做了以下尝试：

| Sprint | 尝试 | 结果 |
|--------|------|------|
| 1.2 | 5个候选子组合 | 全部失败 |
| 1.3a | v1.2(+mf_divergence) | p=0.387不显著 |
| 1.3b | 9种线性合成方法 | 全部劣于等权 |
| 1.3b | PEAD等权第6因子 | Sharpe反降 |
| 1.3b | 7因子/8因子 | 稀释效应 |
| 1.4b | LightGBM替代等权 | NOT JUSTIFIED |
| 1.5-1.5b | 基本面因子方向 | 彻底关闭 |
| 1.6 | 7因子等权(+vwap+rsrs) | Reverted |
| 1.12 | RSRS排序型 | NOT JUSTIFIED |

**9个Sprint, 0个成功升级v1.1。** 这不是因为Alpha不够（RSRS t=-4.35, mf_divergence IC=9.1%都很强），而是因为单一框架限制了我们利用这些Alpha的方式。

---

## 10. 参考文献

1. MSCI. *Foundations of Factor Investing*. MSCI Factor Research. https://www.msci.com/factor-investing
2. Asness, C. et al. (2023). "Fact, Fiction, and Factor Investing." *Journal of Portfolio Management*. https://www.aqr.com/Insights/Research
3. Neuhierl, A. et al. *Timing the Factor Zoo*. Working paper. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3623840
4. Feng, G. et al. (2020). *Taming the Factor Zoo*. *Journal of Finance*, 75(3). https://doi.org/10.1111/jofi.12883
5. 华安证券 (2025). *从个股级因子预测构建增强指数策略 -- 因子舒适区系列二*. 华安证券研究所.
6. 华安证券 (2025). *从因子轮动到因子配置 -- 基于因子牛熊识别的动态因子配置策略*. 华安证券研究所.
7. 华泰证券金工. *高频因子研究系列*. 华泰证券研究所.
8. 长江证券. *结构化反转因子研究*. 长江证券研究所.
9. 天风证券 (2017). *RSRS -- 阻力支撑相对强度指标*. 天风证券研究所.
10. Lo, A. (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal*, 58(4). https://doi.org/10.2469/faj.v58.n4.2453
11. Harvey, C., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1). https://doi.org/10.1093/rfs/hhv059
12. Microsoft Research. *Qlib: An AI-oriented Quantitative Investment Platform*. https://github.com/microsoft/qlib
13. hugo2046. *QuantsPlaybook*. https://github.com/hugo2046/QuantsPlaybook
14. BigQuant. *BigQuant量化平台*. https://bigquant.com

---

## 附录A: 与现有代码架构的兼容性矩阵

| 现有组件 | 是否需要改动 | 改动内容 |
|----------|------------|----------|
| `BaseStrategy` (base_strategy.py) | 小改 | 增加`PositionDetail` dataclass, 扩展`StrategyContext` |
| `StrategyRegistry` (strategy_registry.py) | 小改 | 注册新策略类型 |
| `SignalComposer` (signal_engine.py) | 不改 | 排序型/快排序型继续复用 |
| `PortfolioBuilder` (signal_engine.py) | 不改 | 排序型/快排序型继续复用 |
| `SimpleBacktester` (backtest_engine.py) | 中改 | 支持event型的持有期跟踪+非定期调仓 |
| `FactorProfile` (factor_profile.py) | 小改 | 增加`signal_sparsity`字段 |
| `EqualWeightStrategy` | 不改 | v1.1配置继续使用 |
| `MultiFreqStrategy` | 不改 | 快排序型可以直接复用(已支持daily/weekly) |
| `SlippageModel` | 不改 | 所有策略共用 |
| Paper Trading链路 | 不改 | v1.1锁死 |

## 附录B: 信号类型与BaseStrategy钩子的对应关系

```
SignalType.RANKING  → compute_alpha() + build_portfolio() [现有逻辑]
SignalType.EVENT    → _detect_events() + _check_holding_period() [新增]
SignalType.FILTER   → filter_universe() [已预留, 实现过滤逻辑]
SignalType.MODIFIER → on_rebalance() [已预留, 实现仓位调整]
```

四种信号类型全部在`base_strategy.py`中已定义(`SignalType` enum)，钩子方法(`filter_universe`, `on_rebalance`)也已预留。框架设计是兼容的，只需要实现具体子类。

## 附录C: 项目历史失败实验的匹配分析

| 实验 | 使用策略 | 应该使用策略 | 预期改善 |
|------|----------|------------|----------|
| RSRS月度排序 | Ranking/Monthly | Event/Signal-triggered | 从Sharpe 0.28到>0.5 |
| RSRS周度排序 | Ranking/Weekly | Event/Signal-triggered | 从Sharpe 0.15到>0.5 |
| mf_divergence等权第6因子 | Ranking/Monthly(6因子) | FastRanking/Weekly(独立) | 从增量不显著到独立Sharpe>0.5 |
| PEAD等权第6因子 | Ranking/Monthly | Event/Post-announcement | 从Sharpe降低到独立Alpha |
| 7因子等权 | Ranking/Monthly(7因子) | 拆分为2策略(5排序+2独立) | 从Sharpe 0.902到>1.0 |
| 9种线性合成 | 各种加权/Monthly | 问题不在合成方法而在框架 | 等权是线性最优(LL-018) |

---

> **下一步行动**: 实现`EventDrivenStrategy` + `strategy_matcher.py`，用RSRS做第一个SimBroker验证。如果RSRS事件型Sharpe>0.5，框架价值得到初步确认。
