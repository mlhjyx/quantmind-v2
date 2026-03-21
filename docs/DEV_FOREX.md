# QuantMind V2 — 外汇模块详细开发文档

> 文档级别：实现级（供 Claude Code 执行）
> 创建日期：2026-03-20
> 关联文档：QUANTMIND_V2_DESIGN_V5.md, DEV_BACKTEST_ENGINE.md, DEV_AI_EVOLUTION.md
> Phase：Phase 2 实现，Phase 0 预留接口

---

## 一、概述与战略决策

### 1.1 外汇模块定位

A股+外汇双市场绝对收益系统。外汇模块Phase 2实现，与A股完全独立的策略/回测/执行管道，共用AI闭环框架和前端架构。

### 1.2 已确认战略决策

| # | 决策项 | 选择 |
|---|--------|------|
| 81 | Broker | ECMarkets |
| 82 | 账户类型 | STD（零佣金，点差≥1.0pip） |
| 83 | 杠杆 | 可配置，默认1:100 |
| 84 | 策略哲学 | 多层融合（宏观定方向+技术定入场+AI优化参数） |
| 85 | 交易频率 | 混合（日频趋势Phase 2 + 小时频短线Phase 3） |
| 86 | 品种范围 | 14对（7主要+5交叉+2贵金属），全部Phase 2实现 |
| 87 | 回测引擎 | Python纯事件驱动（不复用A股Rust引擎） |
| 88 | ML模型 | Phase 2: LightGBM+Optuna+随机森林 |
| 89 | LLM模型 | 可配置，默认分环节（假设Claude+代码V3+诊断Claude） |
| 90 | 风控 | 4层14项 |
| 91 | MT5对接 | Adapter架构（Windows FastAPI网关） |
| 92 | 跨市场分配 | AI动态，默认A70%/外30% |
| 93 | 多模型投票 | 预留接口，Phase 3开启 |

---

## 二、品种与市场特征

### 2.1 品种清单（14对）

#### Tier 1 — 核心（7对）

| 品种 | 类型 | STD典型点差 | 日均波幅(pip) | 最佳时段 | pip_value($/lot) | pip_digits |
|------|------|-----------|-------------|---------|-----------------|-----------|
| EUR/USD | 主要 | 1.2 | 80 | 欧美重叠 | $10.00 | 4 |
| GBP/USD | 主要 | 1.8 | 115 | 伦敦 | $10.00 | 4 |
| USD/JPY | 主要 | 1.4 | 85 | 亚洲+纽约 | ~$6.50 | 2 |
| AUD/USD | 商品 | 1.6 | 70 | 亚洲+伦敦 | $10.00 | 4 |
| USD/CAD | 商品 | 2.0 | 70 | 纽约 | ~$7.30 | 4 |
| NZD/USD | 商品 | 2.2 | 60 | 亚洲 | $10.00 | 4 |
| USD/CHF | 避险 | 1.8 | 65 | 欧美 | ~$11.20 | 4 |

#### Tier 2 — 扩展（5对）

| 品种 | 类型 | STD典型点差 | 日均波幅(pip) | pip_value($/lot) |
|------|------|-----------|-------------|-----------------|
| EUR/GBP | 交叉 | 2.0 | 50 | ~$12.60 |
| EUR/JPY | 交叉 | 2.5 | 100 | ~$6.50 |
| GBP/JPY | 交叉 | 3.5 | 145 | ~$6.50 |
| AUD/JPY | 交叉 | 2.8 | 85 | ~$6.50 |
| EUR/AUD | 交叉 | 3.0 | 95 | ~$6.50 |

#### Tier 3 — 贵金属（2对）

| 品种 | STD典型点差 | 日均波幅 | contract_size | pip_value |
|------|-----------|---------|--------------|----------|
| XAU/USD | 3.5 | $20 | 100 oz | $1.00/oz |
| XAG/USD | 3.5 | $0.45 | 5000 oz | $50.00/oz |

### 2.2 品种间相关性矩阵

高正相关(>0.7): EUR/USD↔GBP/USD(+0.80), AUD/USD↔NZD/USD(+0.85), EUR/JPY↔GBP/JPY(+0.85)
强负相关(<-0.7): EUR/USD↔USD/CHF(-0.90)
低相关(<0.3): EUR/GBP↔USD/JPY(+0.10), AUD/JPY↔EUR/GBP(+0.15)

### 2.3 交易时段（北京时间）

| 时段 | 北京时间 | UTC | 特点 | 活跃品种 |
|------|---------|-----|------|---------|
| 悉尼/东京 | 06:00-14:00 | 22:00-06:00 | 温和 | JPY/AUD/NZD |
| 伦敦 | 15:00-23:00 | 07:00-15:00 | 最大流动性 | EUR/GBP |
| 伦敦纽约重叠 | 20:00-23:00 | 12:00-16:00 | 波动最大,点差最窄 | 全部 |
| 纽约 | 21:00-05:00 | 13:00-21:00 | 活跃 | USD/CAD |
| 低流动性 | 05:00-06:00 | 21:00-22:00 | 点差2-5倍 | 避免交易 |

### 2.4 Swap方向（2025-2026利率环境）

做多收Swap: USD/JPY, AUD/JPY(套息交易)
做多付Swap: EUR/USD, GBP/USD
Swap每日22:00 GMT结算，周三三倍

---

## 三、数据管道

### 3.1 三个数据源

| 数据源 | 用途 | 频率 | 成本 |
|--------|------|------|------|
| HistData.com | 回测(M1, 2000-2024) | 一次性导入 | 免费 |
| MT5 Python API | 实时+增量更新 | 每日 | 免费(broker提供) |
| 经济日历 | 策略信号+风控 | 每日 | 先试MT5内置 |

### 3.2 HistData导入

格式: CSV, EST时区, M1级别OHLC+tick_volume
导入流程: 下载→解析→EST转UTC→清洗(剔除异常tick)→写入forex_bars→聚合M5/M15/H1/H4/D1
D1分界线: 17:00 EST(外汇行业惯例)
数据量: 14品种×25年 ≈ 1.7亿条M1, 存储~17GB

⚠️ HistData不含: bid/ask(需加点差模拟), Swap(需估算), 真实成交量(tick_volume仅供参考)

### 3.3 MT5实时数据

核心API: mt5.copy_rates_from()(历史K线), mt5.symbol_info_tick()(实时报价), mt5.symbol_info()(合约规格+Swap费率)
每日增量: 查forex_bars最新日期→MT5补齐→聚合→验证连续性
Swap记录: 每日mt5.symbol_info().swap_long/short→存入forex_swap_rates表

### 3.4 经济日历

方案: 先试MT5内置mt5.calendar_request(), 不行再爬虫investing.com
存入forex_events表, 标记importance(1-3)
高影响事件: 非农/央行利率/CPI/GDP

### 3.5 数据质量验证(data_source_checklist)

- [ ] HistData时区验证(第一根M1应为周日22:00 UTC)
- [ ] 价格连续性(相邻M1跳变<50pip)
- [ ] 每交易日1200-1440条M1
- [ ] D1聚合一致性(High=当日max(M1.High))
- [ ] 跨品种相关性验证(EUR/USD↔USD/CHF应为负)
- [ ] MT5与HistData重叠期数据对比(差异<2pip)
- [ ] ECMarkets Demo账户每品种filling_mode验证

### 3.6 数据管道调度

一次性: HistData导入+聚合(预计6小时)
每日00:00 UTC: MT5增量更新→经济日历→Swap费率→质量检查
每周一01:00: 合约规格验证+相关性矩阵更新

---

## 四、因子体系

### 4.1 与A股的根本区别

A股: 横截面选股(3000只中选30只), 因子=个股特征, 评估=IC
外汇: 时序择时(14品种判方向), 因子=市场状态信号, 评估=Sharpe/胜率/PF

### 4.2 Layer 1 — 宏观方向（6因子，日频/周频）

| # | 因子 | 计算 | 更新频率 | 方向逻辑 |
|---|------|------|---------|---------|
| M1 | interest_rate_diff | 基础货币利率-报价货币利率 | 月 | 正→做多(carry) |
| M2 | rate_change_momentum | 利率变化方向(加息/降息周期) | 月 | 加息→看多 |
| M3 | cpi_diff | 基础CPI同比-报价CPI同比 | 月 | 通胀低→货币强 |
| M4 | pmi_diff | 基础PMI-报价PMI | 月 | PMI高→经济强 |
| M5 | risk_appetite | VIX+信用利差 | 日 | VIX低→商品货币强,避险弱 |
| M6 | cot_positioning | CFTC投机净持仓百分位 | 周 | 极端(>90%/<10%)→反转 |

宏观合成: 各因子投票(+1/0/-1)×权重→score>0.3=bullish, <-0.3=bearish, 其他=neutral(不交易)

### 4.3 Layer 2 — 技术入场（15因子，H1/H4频）

趋势类(6): MA交叉(EMA12/26), MA趋势(EMA50/200位置), ADX(14), MACD柱状图, ROC(10), Donchian突破(20)
均值回归类(4): RSI(14), 布林带位置, 随机指标(14,3,3), 均值偏离(MA50)
波动率类(3): ATR通道, 波动率状态(ATR百分位), 布林带宽度
价格行为类(2): 支撑阻力, K线形态

### 4.4 Layer 3 — AI优化（Phase 3）

参数优化/信号权重/品种选择/仓位调整

### 4.5 信号合成

宏观方向(bullish/bearish/neutral) → 过滤品种和方向
技术信号(+1/0/-1) → 必须与宏观一致才触发
信号强度(confidence 0.5-1.0) → 多信号共振时更高
ML过滤(LightGBM概率) → 调整confidence

### 4.6 因子评估方式

不用IC, 用信号回测绩效: Sharpe/胜率/盈亏比/PF/信号频率/最大连亏
Gate阈值: Sharpe>0.3, 胜率>25%, RR>1.2, PF>1.1, 频率>1次/月, 连亏<12
综合评分≥60入库, ≥40候选, <40拒绝

---

## 五、策略模板

### 5.1 策略A — 日频趋势跟踪（Phase 2）

哲学: 抓趋势中段，不抓顶底。胜率35-45%, 盈亏比2:1-3:1, 持仓3-20天。

7步流程:
1. 宏观过滤: 每周一更新, 输出每品种long_only/short_only/skip
2. D1趋势确认: 价格>EMA50>EMA200 + ADX>20 = 上升趋势
3. H4入场信号: 4种任一触发(MA交叉/Donchian突破/回调入场/动量加速)
4. H1精确入场: Phase 2跳过, Phase 3加入
5. 仓位计算: risk_amount/(sl_pips×pip_value)=lot, ×confidence调整
6. 止损止盈: GARCH动态止损(2×σ), 盈亏比目标2:1
7. 持仓管理: 移动止损(浮盈>1×SL距离开始), 最大持仓20天, 周五减仓

### 5.2 策略B — 小时频短线（Phase 3预留）

H1信号+M15确认, 持仓2-48小时, 均值回归为主, 胜率50-55%, RR 1:1-1.5:1

### 5.3 三层可配置性

Level 1(固定): 风控5项必须执行, 必须有止损, 仓位基于风险计算, 不能跳过风控
Level 2(参数可配): ~35个策略参数(MA周期/RSI阈值/GARCH倍数/盈亏比等), 前端配置面板调整
Level 3(规则可自定义): 可视化模式(节点拖拽) + 代码模式(BaseForexStrategy子类), 5个预置模板

### 5.4 预置策略模板

① 经典趋势跟踪(默认) ② 保守趋势 ③ 激进动量 ④ 纯技术(无宏观) ⑤ 空白模板

### 5.5 策略评估验收标准（回测2005-2024）

必须通过: Sharpe>0.5, PF>1.3, MDD<25%, 月胜率>40%, RR>1.5, 连亏<8, 月交易>3次
期望目标: Sharpe 0.8-1.5, 年化8-15%, MDD<20%
过拟合信号: Sharpe>2.0, 年化>30%, 胜率>60%, MDD<10%

---

## 六、回测引擎

### 6.1 与A股回测的核心差异

A股: Hybrid(向量化+事件驱动), Rust, T+1, 只做多, 3000只, 全额交易
外汇: 纯事件驱动, Python, T+0, 双向, 14只, 保证金交易

不复用A股Rust引擎。14品种×20年日频=70,000 bar, Python秒级完成。

### 6.2 架构

ForexBacktestEngine → DataLoader + SignalEngine + SimBroker + RiskManager + PositionManager + CostModel + PerformanceTracker + WalkForwardEngine

### 6.3 SimBroker关键逻辑

开仓: 成交价=close±spread/2±slippage, 检查保证金
平仓: 成交价=close∓spread/2∓slippage, 计算盈亏(含pip_value汇率转换)
SL/TP检查: 用H4 bar细化日内执行(每D1=6根H4逐根检查)
Swap: 每日22:00 GMT结算, 周三三倍
保证金: 实时追踪, <50%强制平仓(从亏损最大开始平)
Gap: 周一开盘价穿过SL→以开盘价成交(亏损>预期)
同bar SL+TP都触发: 保守假设SL先触发

### 6.4 日内SL/TP精度

Phase 2: H4精度(每D1检查6根H4), 平衡速度和精度
Phase 3: 可选H1精度(24根)

### 6.5 Walk-Forward

复用A股WF框架思路, 参数调整: train=60月, test=12月, step=6月
外汇数据20年足够10+个OOS窗口

### 6.6 AI复用

Pipeline状态机: 直接复用, market路由
4个Agent: 框架复用, 业务逻辑替换(Prompt/评估/诊断树/检查项)
4级自动化+审批+决策日志: 直接复用
ai_parameters表: 直接复用, 新增~50个外汇参数
trial_registry: 直接复用
整体复用度: 框架~80%, 业务~30%, 综合~55%

### 6.7 回测结果

指标: 总收益/年化/Sharpe/DSR/MDD/Calmar + 交易统计(胜率/PF/RR/连亏) + 成本分解(点差/Swap/滑点) + 风控统计(margin_call/gap_sl/friday_close) + 品种分析
存入backtest_run表(market='forex') + forex_backtest_trades表

---

## 七、组合与仓位管理

### 7.1 单笔仓位计算

核心公式: lot = (equity × risk_pct × confidence) / (sl_pips × pip_value)
pip_value按品种计算: USD报价=$10/lot, USD基础=需汇率转换, 交叉盘=需USD中转

### 7.2 相关性风险管理

高相关品种(>0.5)同方向合并计算风险
同方向相关品种总风险上限4%
开仓前检查: 通过→正常 / 超限→缩减手数或拒绝

### 7.3 货币暴露计算

每笔持仓拆解为两个货币暴露(如EUR/USD做多=EUR做多+USD做空)
合并同币种暴露, 前端展示

### 7.4 保证金管理

margin = (lot × contract_size × price) / leverage
margin_level = equity / margin_used × 100%
状态: >200%健康, 100-200%注意, 50-100%危险, <50%强平

### 7.5 品种优先级

多信号同时出现时排序: confidence×0.4 + (1-max_corr)×0.3 + (1-spread_cost)×0.15 + atr_pct×0.15
取top-K(K=可开仓数)

### 7.6 跨市场资金分配

Phase 0-1: 固定A70%/外30%
Phase 3: AI动态(基于近期Sharpe/MDD/相关性/市场状态)
硬约束: A股50-90%, 外汇10-50%, 步进±5%, 冷却30天
跨broker转账需人工执行(miniQMT↔ECMarkets)

---

## 八、风控详细设计

### 8.1 Layer 1 — 开仓前检查（5项硬性）

| # | 检查项 | 默认阈值 | 范围 |
|---|--------|---------|------|
| ① | 单笔风险上限 | 2% | 0.5-3% |
| ② | 总保证金上限 | 50% | 30-70% |
| ③ | 单品种限仓 | 3手 | 1-10手 |
| ④ | 相关品种总风险上限 | 4% | 2-6% |
| ⑤ | 最大同时持仓数 | 8 | 3-14 |

执行顺序: ⑤→③→②→①→④(快→慢, 任一失败短路返回)

### 8.2 Layer 2 — 持仓中监控（4项）

| # | 监控项 | 默认阈值 | 触发行为 |
|---|--------|---------|---------|
| ⑥ | 每日最大亏损 | 3% / 5%(硬性) | 3%禁止新仓 / 5%强制平仓 |
| ⑦ | 总回撤熔断 | 15%/20%/25% | 减仓/暂停/全平+人工重启 |
| ⑧ | 持仓时间超限 | 20天 | 强制平仓 |
| ⑨ | 信号质量 | 胜率<20% / PF<0.8 / 连亏>6 | 暂停/减仓/冷却3天 |

### 8.3 Layer 3 — 极端事件保护（3项）

| # | 保护项 | 规则 |
|---|--------|------|
| ⑩ | 周五减仓 | 周五08:00UTC, 浮盈<1ATR→平仓, >1ATR→保留 |
| ⑪ | 经济事件 | 高影响前1h: SL移到保本+暂停新仓; 发布后30min恢复 |
| ⑫ | 流动性保护 | 05:00-06:00UTC禁止开仓 |

### 8.4 Layer 4 — 系统级保护（2项）

| # | 保护项 | 规则 |
|---|--------|------|
| ⑬ | MT5断连 | 30s心跳, 断连→重连3次→60s黄色→300s红色告警; SL在broker端仍有效 |
| ⑭ | 每日风控报告 | 账户状态+交易+风控+明日关注事件→钉钉推送 |

风控参数约25个, 纳入ai_parameters表。

---

## 九、成本模型

### 9.1 14品种成本参数

| 品种 | 典型点差 | 亚洲×倍 | 低流动性×倍 | 事件×倍 | 成本占ATR比 |
|------|---------|--------|-----------|--------|-----------|
| EUR/USD | 1.2 | 1.2 | 2.5 | 3.0 | 1.5% |
| GBP/USD | 1.8 | 1.3 | 3.0 | 3.5 | 1.6% |
| USD/JPY | 1.4 | 1.0 | 2.5 | 3.0 | 1.6% |
| AUD/USD | 1.6 | 1.0 | 2.5 | 2.5 | 2.3% |
| USD/CAD | 2.0 | 1.3 | 3.0 | 2.5 | 2.9% |
| NZD/USD | 2.2 | 1.0 | 3.0 | 2.5 | 3.7% |
| USD/CHF | 1.8 | 1.2 | 2.5 | 3.0 | 2.8% |
| EUR/GBP | 2.0 | 1.3 | 3.0 | 2.5 | 4.0% |
| EUR/JPY | 2.5 | 1.1 | 3.0 | 3.0 | 2.5% |
| GBP/JPY | 3.5 | 1.2 | 3.5 | 4.0 | 2.4% |
| AUD/JPY | 2.8 | 1.0 | 3.0 | 2.5 | 3.3% |
| EUR/AUD | 3.0 | 1.2 | 3.0 | 2.5 | 3.2% |
| XAU/USD | 3.5 | 1.2 | 3.0 | 3.0 | 1.8% |
| XAG/USD | 3.5 | 1.3 | 3.5 | 3.0 | 1.6% |

### 9.2 点差回测估算

Phase 2: 时段调整点差(base × session_multiplier × random±10%)
Phase 3: +经济事件调整

### 9.3 Swap估算

回测用利率差近似: swap ≈ (base_rate-quote_rate) × contract_size × price / 365 × 0.7(broker_markup)
需要历史利率数据(forex_macro_data表, indicator='interest_rate')

### 9.4 滑点模型

正常: 0.2-0.5pip(主要), 0.3-0.8pip(交叉), 0.5-1.0pip(贵金属)
低流动性: ×2, 高影响事件: +1-5pip
方向: 始终对交易者不利

### 9.5 成本对策略决策的影响

cost_aware_entry=True: 低流动性不开仓, overlap时段优先
avoid_wednesday_open=True: 避免周三开仓(三倍Swap)
prefer_swap_direction=True: 信号中性时偏向正Swap方向
STD vs ECN对比: 回测配置可选account_type切换

### 9.6 TCA分析

回测完成后输出: 总成本/成本分解(点差61%/Swap28%/滑点11%)/按品种/按时段/Swap分析/优化建议

---

## 十、MT5对接方案

### 10.1 部署架构

Windows(Parallels): MT5终端 + MT5 Adapter(FastAPI, localhost:8001)
macOS: QuantMind主服务(PostgreSQL+FastAPI+Celery)
通信: HTTP REST API, localhost(同机Parallels)

### 10.2 MT5 Adapter API端点

| 端点 | 方法 | 功能 |
|------|------|------|
| /account | GET | 账户信息(余额/净值/保证金) |
| /tick/{symbol} | GET | 实时报价(bid/ask/spread) |
| /rates/{symbol} | GET | 历史K线 |
| /symbol_info/{symbol} | GET | 合约规格(点差/Swap/保证金) |
| /positions | GET | 当前持仓列表 |
| /order/open | POST | 市价开仓(含SL/TP) |
| /order/close/{ticket} | POST | 平仓(全部/部分) |
| /order/modify_sl_tp | POST | 修改止损止盈(移动止损) |
| /history/deals | GET | 历史成交记录 |
| /heartbeat | GET | 心跳检查 |

### 10.3 交易执行引擎

信号→获取账户→获取持仓→风控5项→实时报价检查(市场开放+点差正常)→下单→验证成交→记录DB→推送通知

### 10.4 retcode处理

成功: 10009(DONE), 10008(PLACED)
可重试: 10004(REQUOTE), 10006(REJECT) → 最多重试2次
不可重试: 10013(INVALID), 10014(INVALID_VOLUME), 10019(NOT_ENOUGH_MONEY)
部分成交: 10010 → 接受已成交部分

### 10.5 filling_type兼容性

⚠️ 不同broker支持不同filling_type(FOK/IOC/RETURN)
Phase 2第一件事: ECMarkets Demo上验证每品种filling_mode
写入forex_symbol_config表

### 10.6 持仓同步

每分钟同步: MT5持仓 vs PostgreSQL
差异处理: MT5无DB有→SL/TP已触发→更新trade_log; MT5有DB无→手动开仓→纳入风控
启动对账: Python重启后全量对账

### 10.7 异常重连

30s心跳→断连→重连3次(10/30/60s)→失败→P0告警
SL/TP在broker端server-side执行, Python断连不影响止损保护

### 10.8 安全

凭据.env存储, Adapter只监听localhost, magic=88888标识自动交易, Demo验证3个月后切Live

### 10.9 实盘每日流程

06:00北京: 数据更新→持仓同步→信号生成→持仓管理→新信号执行→日报
全天: 30s心跳 + 1min持仓同步 + 1h经济事件检查
周五16:00: 周五减仓检查

---

## 十一、因子挖掘适配

### 11.1 复用框架, 替换内容

管道相同: R1假设→V3代码→沙箱→评估→Gate→入库
替换5个环节: Prompt/代码模板/评估方法/检验标准/Gate阈值

### 11.2 外汇R1 Prompt

市场特征: 24h交易/三大时段/双向/宏观驱动/趋势性强/套息交易/风险情绪
可用数据: forex_bars(多TF) + forex_events + forex_macro_data + forex_cot_data
6个搜索方向: 多TF动量/波动率状态转换/经济数据冲击/时段效应/货币强弱排名/Swap优化

### 11.3 外汇V3代码模板

函数签名: def compute_signal(data: dict) -> pd.DataFrame (signal/confidence/sl_atr_mult)
输入: data={'D1': df, 'H4': df, 'H1': df}
可用工具: ta.ema/sma/rsi/macd/adx/atr/bollinger/stochastic/donchian + crossover/crossunder/above/below

### 11.4 信号回测评估器

替代IC评估, 用简化回测: 信号+1→做多(SL=2ATR,TP=4ATR), 计算14品种平均绩效
输出: avg_sharpe/win_rate/profit_factor/rr_ratio/trades_per_month

### 11.5 外汇6项Gate检验

min_sharpe>0.3, min_win_rate>0.25, min_rr_ratio>1.2, min_pf>1.1, min_freq>1/月, max_consec_loss<12
综合评分≥60=active, ≥40=candidate, <40=rejected

### 11.6 GP搜索空间

终端节点: OHLCV + 预计算技术指标(ema_12/26/50, rsi_14, adx_14, atr_14, macd_hist, bb_*, donchian_*)
函数节点: add/sub/mul/div + gt/lt + crossover/crossunder + ts_mean/std/max/min/rank/delta
适应度: Sharpe

### 11.7 暴力枚举模板

5个模板: MA交叉参数(21组), RSI阈值(48组), ATR突破(20组), Donchian周期(7组), 多TF动量(9组)
总计~125个候选, 预计30分钟(Python)

---

## 十二、ML模型选型

### 12.1 Phase 2

| 模型 | 用途 | 理由 |
|------|------|------|
| LightGBM | 信号过滤(21因子→方向概率) | 表格数据强项, 训练快, 可解释 |
| Optuna | 策略参数+LightGBM超参搜索 | 贝叶斯优化, 比网格搜索高效10-100倍 |
| 随机森林 | baseline对比 | LightGBM跑不过说明特征有问题 |

### 12.2 LightGBM使用方式

输入特征(~50维): 宏观6 + 技术15当前值 + 时序统计15 + 品种特征5 + 其他
标签: 未来5日收益>0→1(二分类)
约束: max_depth≤5, num_leaves≤16, min_child_samples≥50, 强正则化
验证: Purged K-Fold或Walk-Forward(禁止随机split)
用途: 不直接产生信号, 调节规则信号的confidence(ML>0.6加强, <0.4拒绝)
可解释性: 输出top 10 feature importance, 无法解释的删掉重训

### 12.3 Optuna超参数搜索

策略参数搜索空间: MA周期/RSI阈值/ADX阈值/GARCH倍数/盈亏比等, 100次试验
LightGBM超参搜索: max_depth/num_leaves/learning_rate/n_estimators等, 50次试验
适应度: Walk-Forward OOS Sharpe

### 12.4 Phase 3+路线图

MLP(2-3层), XGBoost交叉验证, GRU(H1数据), CNN(K线形态)
Phase 4: Transformer微调, GNN货币关联
不做: SVM

### 12.5 与A股ML的统一架构

BaseMLPredictor基类: prepare_features()/prepare_labels()/train_walk_forward()/get_feature_importance()
AStockMLPredictor(34因子横截面) / ForexMLPredictor(50特征时序)

---

## 十三、LLM模型选型

### 13.1 可配置多模型方案

| 环节 | A股默认 | 外汇默认 | 备选 |
|------|--------|---------|------|
| R1假设生成 | DeepSeek R1 | Claude Sonnet | GPT-4o, DeepSeek R1 |
| V3代码生成 | DeepSeek V3 | DeepSeek V3 | Claude Sonnet |
| 诊断分析 | DeepSeek R1 | Claude Sonnet | GPT-4o, DeepSeek R1 |

前端Agent配置页可切换模型, 降级: Claude不可用→DeepSeek→本地(Phase 4)

### 13.2 成本

A股全DeepSeek: ~¥1.2/月
外汇分环节: ~¥10/月
总计: ~¥12/月, 月预算¥500内

### 13.3 多模型投票(Phase 3)

预留接口, 默认关闭。开启时: Claude+DeepSeek+GPT同方向生成假设→交集=高置信。

---

## 十四、A股ML模型升级

Phase 0: LightGBM(已设计) + IC加权baseline
Phase 1新增: Optuna(LightGBM超参+策略参数) + 随机森林baseline
Phase 3新增: XGBoost + MLP + 集成投票 + Optuna策略参数搜索
Phase 4: GRU/LSTM + Transformer微调

---

## 十五、Paper Trading与实盘切换

### 15.1 Paper Trading

ECMarkets Demo账户 = Paper Trading。切换只需改.env(LOGIN/PASSWORD/SERVER)。代码零改动。
最少运行3个月, 冻结配置, 不手动干预。

### 15.2 实盘切换检查清单

策略层(7项): Paper ≥3月, Sharpe>0.3, MDD<25%, 衰减率<50%, 连亏<8, PF>1.2, 月胜率>35%
系统层(6项): MT5稳定(断连<3次/30天), 重连成功>95%, 持仓同步零差异, 14项风控正常, 通知<5min延迟, 数据更新零失败
执行层(5项): 下单成功率>98%, 滑点偏差<50%, 点差偏差<30%, SL/TP精确触发, 移动止损正确

### 15.3 切换操作

备份Demo trade_log→切换.env→确认资金到账→确认杠杆→0.01手测试单→确认filling_mode→前2周max_risk=1%→无异常后恢复2%

### 15.4 回退方案

1个月内Sharpe<0→切回Demo诊断; MDD>15%→暂停观察; 系统故障→立即暂停修复

---

## 十六、数据库表汇总（7张新表）

```sql
-- 1. forex_symbol_config  — 品种配置
CREATE TABLE forex_symbol_config (
    symbol VARCHAR(10) PRIMARY KEY, display_name VARCHAR(20) NOT NULL,
    tier SMALLINT NOT NULL, base_currency VARCHAR(3) NOT NULL, quote_currency VARCHAR(3) NOT NULL,
    typical_spread FLOAT, daily_atr FLOAT, pip_value FLOAT, pip_digits SMALLINT DEFAULT 4,
    contract_size INT DEFAULT 100000, max_leverage INT DEFAULT 500, best_session VARCHAR(20),
    filling_mode INT, is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. forex_correlation  — 品种间相关性
CREATE TABLE forex_correlation (
    symbol_a VARCHAR(10) NOT NULL, symbol_b VARCHAR(10) NOT NULL,
    period_days INT NOT NULL, correlation FLOAT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol_a, symbol_b, period_days)
);

-- 3. forex_macro_data  — 宏观经济数据
CREATE TABLE forex_macro_data (
    currency VARCHAR(3) NOT NULL, indicator VARCHAR(30) NOT NULL,
    value FLOAT NOT NULL, period_date DATE NOT NULL, release_date DATE,
    source VARCHAR(20), created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (currency, indicator, period_date)
);

-- 4. forex_cot_data  — COT持仓数据
CREATE TABLE forex_cot_data (
    symbol VARCHAR(10) NOT NULL, report_date DATE NOT NULL,
    commercial_long BIGINT, commercial_short BIGINT,
    speculative_long BIGINT, speculative_short BIGINT,
    spec_net BIGINT, spec_net_pct FLOAT,
    PRIMARY KEY (symbol, report_date)
);

-- 5. forex_factor_config  — 外汇因子配置
CREATE TABLE forex_factor_config (
    factor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL, layer VARCHAR(10) NOT NULL, category VARCHAR(20) NOT NULL,
    timeframe VARCHAR(5), parameters JSONB, signal_type VARCHAR(10),
    is_active BOOLEAN DEFAULT TRUE, win_rate FLOAT, profit_factor FLOAT,
    avg_pnl_ratio FLOAT, signal_frequency FLOAT, backtest_sharpe FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. forex_backtest_trades  — 外汇回测交易明细
CREATE TABLE forex_backtest_trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID REFERENCES backtest_run(run_id),
    symbol VARCHAR(10) NOT NULL, direction VARCHAR(5) NOT NULL, lot FLOAT NOT NULL,
    open_time TIMESTAMPTZ NOT NULL, open_price FLOAT NOT NULL,
    close_time TIMESTAMPTZ, close_price FLOAT, stop_loss FLOAT, take_profit FLOAT,
    close_reason VARCHAR(20), pnl_pips FLOAT, pnl_usd FLOAT,
    spread_cost FLOAT, swap_cost FLOAT, slippage_cost FLOAT,
    entry_signal JSONB, max_favorable FLOAT, max_adverse FLOAT
);

-- 7. forex_swap_rates  — Swap费率历史
CREATE TABLE forex_swap_rates (
    symbol VARCHAR(10) NOT NULL, rate_date DATE NOT NULL,
    swap_long FLOAT, swap_short FLOAT, source VARCHAR(10),
    PRIMARY KEY (symbol, rate_date)
);

-- 已有表扩展:
--   forex_bars: 新增session/is_holiday/data_source字段
--   forex_events: 已有, 不变
--   backtest_run: 通过market='forex'区分
```

总数据库表: 43(A股已有) + 7(外汇新增) = **50张**
