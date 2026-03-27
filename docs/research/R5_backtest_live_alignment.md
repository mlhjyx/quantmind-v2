# R5 回测-实盘对齐研究报告

> QuantMind V2 研究维度 R5 | 2026-03-28
> 核心问题: 回测结果和实盘表现的gap来自哪里？如何系统性缩小？

---

## 1. 问题定义: 当前已知Gap

### 1.1 数值基线

| 指标 | 回测(fixed 10bps) | 回测(volume-impact) | PT实测(Day 3) | 差距 |
|------|-------------------|---------------------|---------------|------|
| Sharpe | 1.03 | 0.91 | -- (数据不足) | -- |
| avg_slippage | 10 bps | ~55-60 bps | 64.5 bps | +544.9%(vs fixed) |
| MDD | -39.7% | -- | -- | -- |

**关键观察**: volume-impact模型估计55-60bps与PT实测64.5bps已较接近(偏差~7-17%), 而fixed 10bps偏差高达544.9%。这说明成本模型升级已大幅缩小了最大的单一gap来源, 但仍有残差需要解释。

### 1.2 PT毕业标准(9项)

| # | 指标 | 标准 | 当前状态 |
|---|------|------|----------|
| 1 | 运行时长 | >= 60交易日 | Day 3/60 |
| 2 | Sharpe | >= 0.72 | 数据不足 |
| 3 | MDD | < 35% | 数据不足 |
| 4 | 滑点偏差 | < 50% | **FAIL** (544.9% vs fixed; ~17% vs volume-impact) |
| 5 | 链路完整性 | 全链路无中断 | 运行中 |
| 6 | fill_rate | >= 95% | 待统计 |
| 7 | avg_slippage | <= 30bps | **FAIL** (64.5bps) |
| 8 | tracking_error | <= 2% | 待统计 |
| 9 | gap_hours | 12-20h | ~16h(标准链路) |

### 1.3 已识别的Gap来源清单

1. **成本模型偏差** -- 已部分解决(fixed->volume-impact)
2. **隔夜跳空** -- 信号T日17:20, 执行T+1 09:30, ~16h gap
3. **信号延迟衰减** -- 因子信号从生成到执行的alpha decay
4. **数据look-ahead bias** -- 复权因子/财报公告日对齐等
5. **部分成交/封板** -- fill_rate < 100%对组合构建的影响
6. **集合竞价机制** -- 开盘价 vs 信号假设价格的偏差

---

## 2. 文献综述: 回测偏差分类学

### 2.1 经典偏差分类框架

回测偏差可分为**数据偏差**、**方法偏差**和**执行偏差**三大类:

**数据偏差(Data Biases)**:
- **存活偏差(Survivorship Bias)**: 只包含当前存在的证券, 忽略退市/破产标的。实证研究显示年化收益可虚高1-4%, 且复利效应下长期累积严重。我们的系统已通过`stock_basic(list_status='D')`拉取退市股+退市前5日强制平仓来处理。
- **前视偏差(Look-ahead Bias)**: 使用决策时点不可用的信息。最隐蔽的形式包括: 财报数据用end_date而非ann_date对齐、复权因子当日未更新就使用、指数成分股用当前而非历史权重。
- **数据质量偏差**: 数据供应商的回填修正(backfill)、价格错误、拆分调整错误等。

**方法偏差(Methodological Biases)**:
- **数据窥探(Data Snooping)**: Harvey, Liu, Zhu (2016)的核心发现: 累计测试超过300个因子后, 新因子需要t > 3.0才可信。传统t > 2.0标准在多重检验下严重不足。我们采用t > 2.5的折中标准(BH-FDR校正)。
- **过拟合(Overfitting)**: Bailey等人提出的PBO(Probability of Backtest Overfitting)框架量化了过拟合概率。参数越多、测试次数越多, 过拟合概率越高。
- **样本选择偏差**: 选择性报告"好"的回测窗口, 忽略"差"的窗口。

**执行偏差(Execution Biases)**:
- **交易成本低估**: 固定滑点假设vs真实市场冲击。Bouchaud (2018)的square-root law: impact ~ sigma * sqrt(Q/V)。
- **流动性假设**: 假设任何信号都能以收盘价成交, 忽略涨跌停/封板/流动性不足。
- **市场冲击忽略**: 自身交易对价格的影响(尤其小盘股)。
- **时间偏差**: 信号生成时间 vs 可执行时间的gap。

### 2.2 Harvey, Liu, Zhu (2016) 多重检验框架

该框架的核心贡献在于:
1. 将因子发现视为**多重假设检验问题**, 而非单一检验
2. 提出**累积测试次数M**作为校正分母
3. 推荐BH-FDR(Benjamini-Hochberg False Discovery Rate)控制方法
4. 给出动态显著性阈值: 随测试因子数增加, 阈值从t~2.0逐步提高到t~3.0+

**对本项目的直接影响**: 我们的FACTOR_TEST_REGISTRY.md记录的累积测试数M是BH-FDR校正的输入。每新增一个候选因子, 现有因子的统计显著性门槛都在隐性提高。

### 2.3 Qlib的回测-生产一致性设计

Microsoft Qlib在回测-生产对齐方面的关键设计模式:
- **Point-in-Time数据库**: 确保回测每个时间点只使用该时间点可用的信息, 从数据层根本性防止前视偏差。
- **声明式工作流(YAML)**: 同一配置驱动回测和生产, 减少"回测用代码A, 生产用代码B"的不一致。
- **OnlineManager**: 将回测的rolling workflow无缝迁移到生产环境的在线更新。
- **松耦合组件**: 数据提供者、模型、策略、执行器各自独立, 替换执行层不影响信号层。

---

## 3. Gap来源系统分析(按影响排序)

### 3.1 影响量化估计

基于文献和我们的PT初步数据, 对各gap来源的影响进行排序估计:

| 排序 | Gap来源 | 估计年化影响 | 估计Sharpe影响 | 可控程度 | 当前状态 |
|------|---------|-------------|---------------|---------|---------|
| 1 | **交易成本模型偏差** | -8%~-15% | -0.3~-0.5 | 高 | volume-impact已上线 |
| 2 | **隔夜跳空** | -2%~-5% | -0.05~-0.15 | 中 | 有统计, 未建模补偿 |
| 3 | **信号alpha decay(16h)** | -1%~-3% | -0.03~-0.10 | 低 | 架构决定 |
| 4 | **部分成交/封板** | -0.5%~-2% | -0.02~-0.08 | 中 | SimBroker已处理 |
| 5 | **集合竞价偏差** | -0.5%~-1.5% | -0.02~-0.05 | 低 | 未建模 |
| 6 | **Look-ahead bias残留** | 0~-2% | 0~-0.08 | 高 | 需系统排查 |
| 7 | **数据延迟/不完整** | 0~-1% | 0~-0.03 | 高 | 16:30拉取已缓解 |
| 8 | **存活偏差残留** | 0~-0.5% | 0~-0.02 | 高 | 已处理 |

**合计估计**: 所有gap来源叠加可能导致年化-12%~-25%, Sharpe下降-0.4~-0.8。这与我们观察到的Sharpe从1.03(理想回测)降至0.91(volume-impact回测)的0.12降幅基本一致, 说明成本模型是最大的单一修正项。

### 3.2 各来源详细分析

#### 3.2.1 交易成本模型偏差(已部分解决)

**机制**: 回测假设10bps固定滑点, 实际市场冲击远高于此。

**当前状态**: 已实现Bouchaud (2018) square-root law模型:
- 公式: `impact = Y * sigma_daily * sqrt(Q/V) * 10000`
- 市值分层: Y_large=0.8(500亿+), Y_mid=1.0(100-500亿), Y_small=1.5(<100亿)
- 卖出惩罚: sell_penalty=1.2
- 基础滑点: base_bps=5.0

**残余问题**:
- PT实测64.5bps vs 模型估计55-60bps, 仍有~7-17%的残差
- sigma_daily默认0.02可能需要用实际个股波动率替代
- 集合竞价的价格发现机制未被square-root law捕获

#### 3.2.2 隔夜跳空

**机制**: 信号基于T日收盘数据生成(17:20), 执行在T+1日开盘(09:30), 中间~16小时的信息真空。

**已有实现**: `calc_open_gap_stats()`函数计算买入日open vs 前日close的平均偏差。

**待补充**:
- 跳空分布的分位数统计(不只是均值)
- 按市值/行业/波动率分层的跳空特征
- 跳空与信号强度的相关性(信号越强的票, 跳空是否越大?)
- 跳空的时间序列特征(牛市/熊市/震荡期差异)

#### 3.2.3 信号Alpha Decay

**机制**: 因子信号在生成后随时间衰减。月度调仓策略的信号有效期理论上为20个交易日, 但16小时的执行延迟本身也有衰减。

**量化方法**: 通过ic_decay分析, 对比t+0信号IC和t+1信号IC的差异, 差值即为隔夜衰减量。

#### 3.2.4 部分成交/封板

**机制**: 涨停封板时买不进, 跌停封板时卖不出。SimBroker已实现`can_trade()`检查。

**回测vs实盘差异**: 回测中涨停检测基于日线收盘数据(事后确认), 而实盘中开盘即封板的情况需要实时判断。月度调仓策略受影响较小(非日内策略)。

#### 3.2.5 集合竞价偏差

**机制**: A股09:15-09:25集合竞价, 09:25确定开盘价。开盘价由集合竞价撮合决定, 不一定等于前收盘价。

**特征**: 上海市场开盘时流动性成本呈"L"型, 开盘时刻最高然后逐渐下降。这意味着以开盘价执行的订单面临最高的流动性成本。

---

## 4. 隔夜跳空建模

### 4.1 A股隔夜跳空分布特征

根据学术研究和市场数据:

**基本统计量**:
- 均值: ~0.67%(正偏, 反映A股的正向开盘倾向)
- 标准差: ~0.40%
- 偏度: ~8.68(严重右偏, 极端跳空事件频繁)
- 峰度: 高(尾部肥厚)
- 中位数: ~0.55%

**分布特征**: 绝大多数跳空集中在较小范围内, 但少数极端跳空(如重大利好/利空新闻)对分布有显著影响。上证指数历史上813次跳空中, 96.31%最终被回补, 说明跳空在统计上存在均值回复性。

### 4.2 对QuantMind的影响建模

**场景分析**:

我们的链路: T日17:20信号 -> T+1 09:30执行。信号基于T日收盘价计算target weight, 执行价格是T+1日开盘价。

**跳空对组合的影响路径**:
1. **买入票跳空高开**: 实际买入价 > 信号假设价, 实际持仓量 < 目标(整手约束下更少手数)
2. **买入票跳空低开**: 实际买入价 < 信号假设价, 有利但也意味着信号可能基于"过时"信息
3. **卖出票跳空低开**: 实际卖出价 < 预期, 亏损扩大
4. **卖出票跳空高开**: 实际卖出价 > 预期, 但卖出信号可能已不合适

**建模方案**:

```
# 方案A: 统计加成法(推荐, 实现简单)
# 在SimBroker中, 将跳空纳入滑点估计
adjusted_slippage = base_slippage + E[|overnight_gap|] * gap_penalty_factor

# 方案B: 历史模拟法(更精确)
# 直接使用次日open作为执行价, 而非close+slippage
execution_price = next_day_open  # 而非 close * (1 + slippage)

# 方案C: 跳空分布采样法(最精确但计算量大)
# 蒙特卡洛采样跳空分布, 评估组合构建的分布
gap_sample = sample_from_empirical_gap_distribution()
execution_price = close * (1 + gap_sample + slippage)
```

**推荐**: 方案B最直接。回测引擎应默认使用T+1日open作为执行价(而非T日close+slippage), 这自然地包含了隔夜跳空。我们的SimBroker目前使用什么价格需要确认。

### 4.3 跳空预检机制

项目已有`开盘跳空预检`设计(Sprint 1.10):
- 单股>5%: P1告警
- 组合>3%: P0告警
- PT阶段: 只告警不阻止

建议增加:
- **跳空统计追踪**: 每日记录实际跳空 vs 模型预期, 累积校准数据
- **极端跳空回退**: 跳空>某阈值时自动缩减该票的目标权重(而非直接执行)

---

## 5. Look-ahead Bias完整检查清单

### 5.1 数据层

| # | 检查项 | 风险等级 | 检查方法 | 当前状态 |
|---|--------|---------|---------|---------|
| D1 | **复权因子时效性** | 高 | 除权除息日当天adj_factor是否已更新? 验证: 对比Tushare adj_factor更新时间 vs 16:30拉取时间 | 待验证 |
| D2 | **财报数据用ann_date** | 高 | SQL审计: 所有join财报数据的查询是否用ann_date而非end_date | 已设计(CLAUDE.md) |
| D3 | **指数成分股历史化** | 高 | index_components表是否存储历史权重? 回测是否用历史成分而非当前成分? | 已设计(DDL) |
| D4 | **停牌/退市数据** | 中 | 停牌日是否有前视的"复牌后价格"混入? | 行业指数代替(已设计) |
| D5 | **数据供应商回填** | 中 | Tushare数据是否有事后修正(restatement)? 是否记录了修正前后版本? | 无PIT版本控制 |
| D6 | **交易日历** | 低 | 是否有节假日交易日错判? 国庆/五一误杀已修复(days_gap交易日) | 已修复 |

### 5.2 因子计算层

| # | 检查项 | 风险等级 | 检查方法 |
|---|--------|---------|---------|
| F1 | **预处理顺序** | 高 | 确认执行顺序: MAD->缺失值->中性化->zscore, 不可调换 |
| F2 | **滚动窗口对齐** | 高 | 20日均值计算时, 是否包含了当日数据? 应只用t-20到t-1 |
| F3 | **forward return计算** | 高 | IC计算的forward return是否严格只用未来数据? 不能用当日收盘 |
| F4 | **中性化回归数据** | 中 | 市值和行业数据是否用当日(可获取)还是未来(不可获取)? |
| F5 | **因子值填充** | 中 | 缺失值填充是否用了截面中位数(ok)还是全局中位数(可能包含未来)? |

### 5.3 信号层

| # | 检查项 | 风险等级 | 检查方法 |
|---|--------|---------|---------|
| S1 | **信号生成时间戳** | 高 | 信号使用的数据是否严格 <= 信号日期? |
| S2 | **复合得分排名** | 中 | 排名是否稳定(相同分数的排序是否确定性)? 不稳定排名 = 随机性 |
| S3 | **调仓日期确定** | 中 | 月度调仓日的确定是否只用过去信息?(如月末交易日 vs 自然日) |
| S4 | **风控触发** | 中 | L1-L4风控等级评估是否用了当日不可获取的数据? |

### 5.4 回测执行层

| # | 检查项 | 风险等级 | 检查方法 |
|---|--------|---------|---------|
| E1 | **成交价格** | 高 | 是否用T日close作为T日信号的执行价? 实际应用T+1 open |
| E2 | **涨跌停判断** | 中 | 涨跌停是用日线收盘确认还是开盘时判断? 日线=事后确认=轻微look-ahead |
| E3 | **成交量可得性** | 中 | can_trade()中用的volume是当日的(不可用)还是前日的? |
| E4 | **资金可用性** | 低 | T+0卖出回款是否正确处理? |

### 5.5 系统性排查流程

```
Step 1: 代码审计 — grep所有数据访问点, 标注时间戳
Step 2: 延迟注入测试 — 将所有数据延迟1天, 跑回测, 如果Sharpe下降显著说明有look-ahead
Step 3: 随机日期测试 — 在某个调仓日, 用T-1日数据生成信号, 与T日信号对比
Step 4: PT回放比对 — 用回测引擎回放PT同期数据, 比对信号是否一致
```

---

## 6. 信号一致性验证方案

### 6.1 核心思路: 回放比对

**目标**: 验证PT生成的信号和回测引擎使用同期历史数据生成的信号**完全一致**。

**方法**:
```
1. PT每日生成信号后, 记录:
   - 信号日期, 全量股票因子值, composite score, 排名, 最终target_weights
   - 保存为 pt_signals_{date}.parquet

2. 回测引擎"回放模式":
   - 输入: 同一日期的同一批数据(从DB快照)
   - 用完全相同的配置(v1.1: 5因子等权+Top15+月度+行业25%)
   - 输出: backtest_signals_{date}.parquet

3. 比对:
   - diff = pt_signals - backtest_signals
   - 允许偏差: 因子值<1e-6, 权重<1e-4
   - 任何超出阈值的偏差 → P1告警 + 根因分析
```

### 6.2 不一致的常见根因

| 根因 | 表现 | 修复 |
|------|------|------|
| **数据版本不同** | 因子值不同 | PT和回测必须从同一DB快照读 |
| **代码路径分叉** | 同数据不同结果 | PT和回测共用FactorService/SignalService |
| **随机性** | 分数相同但排名不同 | 打破平局: 加symbol_id作为次级排序键 |
| **配置漂移** | 参数不一致 | config_guard强制检查(已有Sprint 1.11) |
| **时间窗口边界** | 滚动窗口差1天 | 统一日期处理逻辑 |

### 6.3 自动化对比脚本设计

```python
# scripts/signal_consistency_check.py (概念设计)
def daily_signal_check(pt_date: date):
    """每日PT信号vs回测回放对比。"""
    # 1. 读取PT当日保存的信号
    pt_signals = load_pt_signals(pt_date)

    # 2. 回测引擎回放
    replay_signals = backtest_replay(pt_date, config=V1_1_CONFIG)

    # 3. 比对
    report = compare_signals(pt_signals, replay_signals)

    # 4. 结果
    if report.max_deviation > THRESHOLD:
        alert_p1(f"信号不一致: {report.summary}")

    save_consistency_report(pt_date, report)
```

---

## 7. PT数据分析框架

### 7.1 60天PT数据的利用策略

PT的60天数据不只是"等毕业", 而是**校准回测模型**的珍贵样本:

**阶段1: Day 1-20(数据积累期)**
- 每日记录: 信号 vs 实际执行 vs 回测回放
- 统计: 实际滑点分布(按市值/行业/波动率分层)
- 初步校准: volume-impact模型的Y参数微调

**阶段2: Day 21-40(校准期)**
- 跳空模型校准: 用20天数据拟合跳空分布
- 滑点模型校准: 用Bayesian更新调整Y_large/Y_mid/Y_small和sell_penalty
- fill_rate统计: 封板频率 vs 回测假设
- 回放比对: 累积不一致率统计

**阶段3: Day 41-60(验证期)**
- 用校准后的模型重跑回测, 与PT数据做out-of-sample比对
- 9项毕业指标的趋势预测
- 决策点: 需要延长PT? 需要重新校准? 可以毕业?

### 7.2 关键分析维度

#### 7.2.1 滑点分解分析

```
PT_slippage = spread_component + impact_component + timing_component

其中:
- spread_component = (ask - bid) / 2  (可从tick数据估计)
- impact_component = f(Q/V, market_cap)  (Bouchaud模型)
- timing_component = execution_price - arrival_price  (隔夜跳空+集合竞价)
```

**PT数据可直接计算**:
- `arrival_price` = T日收盘价(信号生成时的参考价)
- `execution_price` = T+1实际成交价
- `total_slippage` = |execution_price - arrival_price| / arrival_price
- `model_slippage` = volume_impact_slippage(参数)
- `residual` = total_slippage - model_slippage (需要解释的部分)

#### 7.2.2 跳空贡献分离

```
overnight_gap = (T+1_open - T_close) / T_close
intraday_slippage = (execution_price - T+1_open) / T+1_open
total = overnight_gap + intraday_slippage  (近似)
```

这个分解可以回答: 64.5bps中, 多少来自隔夜跳空, 多少来自日内执行?

#### 7.2.3 按维度切片

| 维度 | 分组 | 关注指标 |
|------|------|---------|
| 市值 | 大盘/中盘/小盘 | avg_slippage, fill_rate |
| 行业 | 28个一级行业 | 行业间差异 |
| 方向 | 买入/卖出 | 买卖不对称性 |
| 波动率 | 高波/中波/低波 | sigma与滑点的关系 |
| 信号强度 | Top5/Top10/Top15 | 信号越强是否执行越差? |
| 时间 | 按周/月 | 是否有周效应 |

---

## 8. 推荐的对齐改进方案

### 8.1 短期(PT期间, 0-60天)

| 优先级 | 改进项 | 预期效果 | 复杂度 |
|--------|--------|---------|--------|
| P0 | **执行价格改用T+1 open** | 消除隔夜跳空的系统性bias | 低 |
| P0 | **信号保存+回放比对** | 发现PT-回测不一致 | 中 |
| P1 | **滑点分解日报** | 量化各gap来源贡献 | 中 |
| P1 | **sigma_daily用实际值** | volume-impact模型精度提升 | 低 |
| P2 | **Look-ahead延迟注入测试** | 排除前视偏差 | 中 |

### 8.2 中期(PT毕业前后, 60-120天)

| 优先级 | 改进项 | 预期效果 | 复杂度 |
|--------|--------|---------|--------|
| P1 | **volume-impact参数Bayesian校准** | 用PT数据调优Y参数 | 中 |
| P1 | **跳空分布建模** | 回测中引入更真实的跳空估计 | 中 |
| P2 | **集合竞价滑点附加** | 捕获开盘时刻的额外成本 | 低 |
| P2 | **Point-in-Time数据审计** | 系统性排查数据前视 | 高 |

### 8.3 长期(Phase 1+)

| 改进项 | 预期效果 | 复杂度 |
|--------|---------|--------|
| **PIT数据库** | 从根本上消除前视偏差 | 极高 |
| **Tick级回测** | 更精确的执行模拟 | 极高 |
| **自适应成本模型** | 根据市场regime动态调整参数 | 高 |
| **ML滑点预测** | 用PT数据训练个股级滑点模型 | 高 |

---

## 9. 落地计划: 工具/脚本/自动化

### 9.1 工具清单

| 工具/脚本 | 功能 | 触发方式 | 输出 |
|-----------|------|---------|------|
| `scripts/signal_consistency_check.py` | PT信号 vs 回测回放比对 | 每日PT信号生成后 | consistency_report_{date}.json |
| `scripts/slippage_decompose.py` | PT滑点分解(跳空/冲击/spread) | 每日执行后 | slippage_decomp_{date}.csv |
| `scripts/pt_alignment_dashboard.py` | 汇总所有对齐指标的仪表板 | 手动/每周 | HTML报告 |
| `scripts/lookahead_audit.py` | 数据延迟注入测试 | Sprint级 | audit_report.md |
| `scripts/gap_distribution_fit.py` | 隔夜跳空分布拟合 | PT积累20天后 | gap_model_params.json |
| `scripts/volume_impact_calibrate.py` | 用PT数据校准Y参数 | PT积累30天后 | calibrated_config.json |

### 9.2 自动化对齐检查流水线

```
每日T+1 10:00(执行完成后):
  1. signal_consistency_check.py  → 信号一致性 (PASS/FAIL)
  2. slippage_decompose.py        → 滑点分解   (overnight/impact/residual)
  3. pt_graduation_check.py       → 9项毕业指标更新

每周五 18:00:
  4. pt_alignment_dashboard.py    → 周度汇总报告
  5. 如果累积天数>=20: gap_distribution_fit.py → 跳空模型更新

PT Day 30:
  6. volume_impact_calibrate.py   → 中期校准

PT Day 45:
  7. 用校准后模型重跑历史回测 → 对比新旧回测 vs PT实测
```

### 9.3 数据存储设计

```sql
-- PT对齐追踪表(建议新增)
CREATE TABLE pt_alignment_log (
    id SERIAL PRIMARY KEY,
    pt_date DATE NOT NULL,
    -- 信号一致性
    signal_match_rate DECIMAL(5,4),  -- 信号匹配率(0-1)
    max_weight_deviation DECIMAL(8,6),  -- 最大权重偏差
    -- 滑点分解
    avg_overnight_gap_bps DECIMAL(8,2),  -- 隔夜跳空(bps)
    avg_impact_bps DECIMAL(8,2),  -- 市场冲击(bps)
    avg_spread_bps DECIMAL(8,2),  -- 买卖价差(bps)
    avg_total_slippage_bps DECIMAL(8,2),  -- 总滑点(bps)
    model_predicted_bps DECIMAL(8,2),  -- 模型预测滑点(bps)
    -- 执行质量
    fill_rate DECIMAL(5,4),
    partial_fill_count INT,
    limit_hit_count INT,  -- 涨跌停阻止次数
    -- 毕业指标快照
    cumulative_sharpe DECIMAL(6,3),
    cumulative_mdd DECIMAL(6,4),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.4 告警规则

| 条件 | 级别 | 动作 |
|------|------|------|
| signal_match_rate < 0.95 | P0 | 停止次日执行, 人工排查 |
| avg_total_slippage > 100bps | P1 | 检查流动性/市场状态 |
| model_predicted vs actual偏差 > 50% | P1 | 触发模型校准 |
| fill_rate < 90% | P1 | 检查涨跌停/流动性 |
| 连续3天slippage偏差增大 | P2 | 检查市场regime变化 |

---

## 10. 参考文献

### 学术论文

1. Harvey, C. R., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5-68. -- 多重检验框架, 因子显著性阈值t>3.0
2. Bailey, D. H., Borwein, J. M., et al. (2014). "The Probability of Backtest Overfitting." -- PBO框架量化过拟合概率
3. Harvey, C. R. & Liu, Y. (2020). "False (and Missed) Discoveries in Financial Economics." *Journal of Finance*, 75(5). -- BH-FDR方法在金融因子发现中的应用
4. Bouchaud, J.-P. (2018). *Trades, Quotes and Prices: Financial Markets Under the Microscope*. Cambridge University Press. -- Square-root market impact law
5. Kyle, A. S. (1985). "Continuous Auctions and Insider Trading." *Econometrica*, 53(6), 1315-1335. -- 市场冲击的理论基础
6. Lo, A. W. (2002). "The Statistics of Sharpe Ratios." *Financial Analysts Journal*, 58(4), 36-52. -- 自相关调整Sharpe

### 技术平台与工具

7. Microsoft Qlib -- Point-in-Time数据库和声明式工作流: https://github.com/microsoft/qlib
8. BigQuant -- A股隔夜跳空因子研究: https://bigquant.com/square/paper/0eeec134-5e64-4806-a3d1-e09a36eb1c33
9. 华安证券 -- 昼夜分离: 隔夜跳空与日内反转选股因子(市场微观结构系列九)

### 社区与实践

10. 知乎/量化社区 -- 回测与实盘差距讨论: https://www.zhihu.com/question/653420094
11. QuantStart -- Backtesting Algorithmic Trading Strategies: https://www.quantstart.com/articles/Successful-Backtesting-of-Algorithmic-Trading-Strategies-Part-I/
12. QuantJourney -- Look-Ahead Bias Prevention: https://quantjourney.substack.com/p/advanced-look-ahead-bias-prevention
13. kx.com -- TCA Drift Detection in Live Trading: https://kx.com/blog/drift-detections-blind-spot-how-live-tca-insights-help-firms-win-the-race-against-alpha-decay/

---

## 附录A: 回测-实盘偏差快速诊断表

```
症状 → 最可能原因 → 检查方法
────────────────────────────────────
PT Sharpe远低于回测 → 成本模型低估 → 比较avg_slippage
PT持仓与回测不同   → 信号不一致     → signal_consistency_check
PT MDD远大于回测   → 跳空/流动性    → slippage_decompose
PT fill_rate低     → 封板/流动性    → 检查limit_hit_count
PT某行业表现差     → 行业流动性     → 分行业slippage分析
PT周一表现差       → 周末信息积累   → 按星期分析跳空
```

## 附录B: 与现有代码的映射

| 报告建议 | 现有实现 | 状态 |
|---------|---------|------|
| 隔夜跳空统计 | `backend/engines/metrics.py: calc_open_gap_stats()` | 已有, 需扩展 |
| Volume-impact滑点 | `backend/engines/slippage_model.py` | 已有, 需校准 |
| 涨跌停处理 | `backend/engines/backtest_engine.py: can_trade()` | 已有 |
| 执行价格选择 | `BacktestConfig.slippage_mode` | 需确认是否用open |
| 整手约束 | `BacktestConfig.lot_size = 100` | 已有 |
| PT毕业检查 | `scripts/run_paper_trading.py` | 运行中 |
| 配置一致性 | `config_guard`(Sprint 1.11) | 已有 |
