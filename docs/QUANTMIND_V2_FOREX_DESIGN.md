# QuantMind V2 — 外汇模块总设计文档

> 文档级别：架构级（决策+架构+接口，与 QUANTMIND_V2_DESIGN_V5.md 平行）
> 详细开发文档：DEV_FOREX.md（实现级，676行）
> 创建日期：2026-03-20
> 状态：Phase 2 设计完成，Phase 0 预留接口

---

## 一、战略定位

### 1.1 为什么做外汇

| 维度 | A股 | 外汇 | 组合价值 |
|------|-----|------|---------|
| 交易时间 | 9:30-15:00 周一至周五 | 24小时 周一至周五 | 时间覆盖互补 |
| 方向 | 只做多 | 双向（做多+做空） | 熊市也能盈利 |
| 市场相关性 | 与中国经济高度相关 | 全球宏观驱动 | 地域分散化 |
| 监管风险 | A股监管趋严 | 海外broker监管稳定 | 风险分散 |
| 杠杆 | 无（全额交易） | 1:100（保证金交易） | 资金效率提升 |
| 流动性 | 涨跌停/停牌约束 | 无涨跌停，极高流动性 | 执行质量更好 |

预期：A股和外汇相关性<0.3，组合后Sharpe显著高于单市场。

### 1.2 外汇模块边界

```
外汇模块独立的:
  ✗ 策略逻辑（时序择时 vs A股横截面选股）
  ✗ 回测引擎（Python事件驱动 vs A股Rust Hybrid）
  ✗ 因子体系（3层21因子 vs A股34因子）
  ✗ 成本模型（点差+Swap vs 佣金+印花税）
  ✗ 风控规则（保证金+Gap+时段 vs 涨跌停+T+1）
  ✗ 交易接口（MT5 vs miniQMT）

外汇模块复用A股的:
  ✓ AI闭环框架（4Agent+Pipeline状态机+4级自动化）
  ✓ 因子挖掘管道（R1→V3→沙箱→评估→Gate→入库）
  ✓ 参数可配置架构（ai_parameters表+前端配置面板）
  ✓ Walk-Forward验证框架
  ✓ DSR/PBO统计检验工具
  ✓ 前端页面框架（市场切换器路由）
  ✓ 通知告警机制
```

---

## 二、决策汇总（13项，#81-93）

| # | 决策项 | 选择 | 理由 |
|---|--------|------|------|
| 81 | Broker | ECMarkets | FCA/ASIC监管，100+品种，MT5支持 |
| 82 | 账户类型 | STD（零佣金，点差≥1.0pip） | 日频策略点差成本<佣金，简化成本计算 |
| 83 | 杠杆 | 可配置，默认1:100 | 1:100保守风控，可调至1:500 |
| 84 | 策略哲学 | 多层融合（宏观+技术+AI） | 宏观定方向降低假信号，技术定时机提高精度 |
| 85 | 交易频率 | 混合（日频Phase 2 + 小时频Phase 3） | 日频先行验证，小时频后加 |
| 86 | 品种范围 | 14对（Tier 1/2/3全做） | 分散化需要足够品种 |
| 87 | 回测引擎 | Python纯事件驱动 | 14品种×20年=70K bar，Python秒级，不需要Rust |
| 88 | ML模型 | LightGBM+Optuna+RF（Phase 2） | 信号过滤+参数搜索+baseline |
| 89 | LLM模型 | 可配置，默认分环节选最优 | 外汇假设/诊断用Claude，代码用DeepSeek V3 |
| 90 | 风控 | 4层14项 | 纵深防御，开仓前+持仓中+极端+系统 |
| 91 | MT5对接 | Adapter架构（Windows FastAPI网关） | 解耦Windows依赖，macOS主服务通过HTTP调用 |
| 92 | 跨市场分配 | AI动态，默认A70%/外30% | Phase 0-1固定，Phase 3 AI调整 |
| 93 | 多模型投票 | 预留接口，Phase 3开启 | 避免过度设计 |

---

## 三、品种体系

### 3.1 三级品种架构

```
Tier 1（核心，7对）: EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, NZD/USD, USD/CHF
  特点: 流动性最好，点差最低（1.0-2.2pip），数据最完整
  
Tier 2（扩展，5对）: EUR/GBP, EUR/JPY, GBP/JPY, AUD/JPY, EUR/AUD
  特点: 点差稍高（2.0-3.5pip），有独立交易逻辑（交叉盘）
  
Tier 3（贵金属，2对）: XAU/USD, XAG/USD
  特点: 避险资产，与外汇策略互补，合约规格不同
```

### 3.2 品种间相关性（影响组合构建）

```
高正相关（同向开仓=风险叠加）:
  EUR/USD ↔ GBP/USD: +0.80    AUD/USD ↔ NZD/USD: +0.85

强负相关（同向开仓=互相对冲，浪费点差）:
  EUR/USD ↔ USD/CHF: -0.90

低相关（真正的分散化）:
  EUR/GBP ↔ USD/JPY: +0.10    AUD/JPY ↔ EUR/GBP: +0.15
```

### 3.3 交易时段

三大时段：悉尼/东京（06:00-14:00北京）→ 伦敦（15:00-23:00）→ 纽约（21:00-05:00）
最佳交易窗口：伦敦纽约重叠（20:00-23:00北京），点差最窄，流动性最高
禁止交易：05:00-06:00北京（低流动性，点差2-5倍）

> 详见 DEV_FOREX.md §二

---

## 四、数据架构

### 4.1 数据源

| 数据源 | 用途 | 内容 | 频率 |
|--------|------|------|------|
| HistData.com | 回测历史数据 | M1 OHLCV, 2000-2024 | 一次性导入 |
| MT5 Python API | 实时+增量 | 多TF OHLCV + 报价 + Swap | 每日 |
| 经济日历 | 信号+风控 | 全球经济事件 | 每日 |
| CFTC COT | 宏观信号 | 投机净持仓 | 每周 |
| 央行利率 | 宏观信号 | 8个央行基准利率 | 手动/月 |

### 4.2 数据流

```
HistData(CSV) → 导入+清洗+聚合 → forex_bars(M1→M5→M15→H1→H4→D1)
                                     ↓
MT5(API) → 每日增量 ──────────→ forex_bars(补最新数据)
MT5(API) → Swap费率 ──────────→ forex_swap_rates
经济日历 → 每日更新 ──────────→ forex_events
CFTC → 每周爬取 ─────────────→ forex_cot_data
央行利率 → 手动录入 ──────────→ forex_macro_data
```

### 4.3 数据量

M1: ~1.7亿条（14品种×25年），存储~17GB
聚合后全部时间框架: ~2亿条，~20GB
PostgreSQL + TimescaleDB hypertable，单品种单TF查询<1秒

### 4.4 数据质量要求

- [ ] HistData时区验证（EST→UTC）
- [ ] D1分界线验证（17:00 EST）
- [ ] 价格连续性（相邻M1跳变<50pip）
- [ ] ECMarkets filling_mode验证（每品种）
- [ ] MT5与HistData重叠期对比（<2pip差异）

> 详见 DEV_FOREX.md §三

---

## 五、因子体系

### 5.1 三层因子架构

```
Layer 1 — 宏观方向（6因子，日/周频）
  利率差 / 利率方向 / CPI差 / PMI差 / 风险偏好(VIX) / COT持仓
  → 输出: 每品种 bullish / bearish / neutral
  → 作用: 方向过滤（只允许与宏观一致的交易）

Layer 2 — 技术入场（15因子，H1/H4频）
  趋势(6): MA交叉/MA趋势/ADX/MACD/ROC/Donchian突破
  均值回归(4): RSI/布林带/随机指标/均值偏离
  波动率(3): ATR通道/波动率状态/布林带宽度
  价格行为(2): 支撑阻力/K线形态
  → 输出: 每品种 long/short/none + confidence

Layer 3 — AI优化（Phase 3）
  参数优化 / 信号权重 / 品种选择 / 仓位调整
```

### 5.2 与A股因子的本质区别

```
A股: 横截面因子 → 3000只股票打分排序 → 选top-N
     评估: IC / IR / 分组单调性

外汇: 时序信号 → 14品种判方向+时机 → 逐笔独立交易
     评估: Sharpe / 胜率 / 盈亏比 / Profit Factor
```

### 5.3 信号合成

宏观方向一致 + 技术信号触发 → 基础信号
ML过滤（LightGBM概率）→ 调整confidence
多信号共振 → confidence提升

> 详见 DEV_FOREX.md §四

---

## 六、策略体系

### 6.1 两类策略

| | 策略A: 日频趋势跟踪 | 策略B: 小时频短线 |
|--|---|---|
| Phase | Phase 2 实现 | Phase 3 实现 |
| 时间框架 | D1信号 + H4确认 | H1信号 + M15确认 |
| 持仓时间 | 3-20天 | 2-48小时 |
| 胜率预期 | 35-45% | 50-55% |
| 盈亏比 | 2:1 ~ 3:1 | 1:1 ~ 1.5:1 |
| 适合市场 | 趋势市（ADX>25） | 盘整市（ADX<20） |

### 6.2 策略A完整流程（7步）

```
Step 1: 宏观过滤    → 确定可交易品种和方向（每周一更新）
Step 2: D1趋势确认  → 价格>EMA50>EMA200 + ADX>20
Step 3: H4入场信号  → MA交叉/Donchian突破/回调入场/动量加速（任一触发）
Step 4: H1精确入场  → Phase 2跳过，Phase 3加入
Step 5: 仓位计算    → risk_amount / (sl_pips × pip_value) × confidence
Step 6: 止损止盈    → GARCH动态止损(2σ) + 盈亏比2:1止盈
Step 7: 持仓管理    → 移动止损 + 最大20天 + 趋势反转出场 + 周五减仓
```

### 6.3 三层可配置性

```
Level 1（固定不可改）: 风控5项必须执行 / 必须有止损 / 仓位基于风险计算
Level 2（参数可配）: ~35个参数（MA周期/RSI阈值/GARCH倍数/盈亏比等）
Level 3（规则可自定义）: 可视化搭建 + 代码模式（BaseForexStrategy子类）
```

5个预置模板: 经典趋势(默认) / 保守趋势 / 激进动量 / 纯技术 / 空白

### 6.4 策略验收标准（回测2005-2024）

必须通过: Sharpe>0.5, PF>1.3, MDD<25%, 月胜率>40%, RR>1.5
过拟合信号: Sharpe>2.0, 年化>30%, 胜率>60%（不现实）

> 详见 DEV_FOREX.md §五

---

## 七、回测引擎

### 7.1 架构选择

Python纯事件驱动，不复用A股Rust引擎。

理由: 14品种×20年日频=70K bar，Python秒级完成。双向交易+保证金+Swap的逻辑与A股完全不同，复用反而增加复杂度。

### 7.2 核心组件

```
ForexBacktestEngine
  ├── DataLoader        — 多TF数据加载
  ├── SignalEngine      — 3层因子信号计算
  ├── SimBroker         — 模拟broker（开平仓/保证金/Swap/Gap）
  ├── RiskManager       — 4层14项风控
  ├── CostModel         — 动态点差+Swap+滑点
  ├── PerformanceTracker — 净值/指标/TCA
  └── WalkForwardEngine  — 复用A股WF框架思路
```

### 7.3 SimBroker关键模拟

| 场景 | 模拟方式 |
|------|---------|
| 开仓执行 | close ± spread/2 ± slippage |
| 平仓执行 | close ∓ spread/2 ∓ slippage |
| SL/TP日内检查 | H4精度（每D1=6根H4逐根检查） |
| Swap结算 | 每日22:00 GMT，周三三倍 |
| 保证金强平 | margin_level<50%从亏损最大开始平 |
| 周末Gap | 周一开盘穿SL→以开盘价成交（亏损>预期） |
| 同bar SL+TP | 保守假设SL先触发 |

### 7.4 AI闭环复用

Pipeline状态机直接复用，通过market字段路由。
4个Agent框架复用，业务逻辑替换（Prompt/评估/诊断树/检查项）。
整体复用度: 框架~80%, 业务~30%, 综合~55%。

> 详见 DEV_FOREX.md §六

---

## 八、组合与仓位管理

### 8.1 与A股的根本区别

```
A股: "静态组合" — 选30只等权，调仓时整体换仓
外汇: "动态持仓" — 信号来一笔开一笔，每笔独立管理
```

### 8.2 仓位计算核心

```
lot = (equity × risk_pct × confidence) / (sl_pips × pip_value)

关键: 仓位由止损距离决定
  止损宽(50pip) → 自动小仓位
  止损窄(20pip) → 自动大仓位
  = 每笔风险恒定(2%)，仓位自适应
```

### 8.3 三个外汇特有的风险维度

**① 相关性风险**: EUR/USD做多+GBP/USD做多≈1.7倍做多非美。同方向高相关品种合并计算，总风险上限4%。

**② 货币暴露**: 每笔持仓拆解为两个货币。EUR/USD做多=EUR做多+USD做空。合并同币种暴露，前端展示。

**③ 保证金管理**: margin_level实时追踪。>200%健康，100-200%注意，<50%强制平仓。

### 8.4 跨市场资金分配

Phase 0-1: 固定A70%/外30%
Phase 3: AI动态调整（基于Sharpe/MDD/相关性/市场状态）
约束: A股50-90%, 外汇10-50%, 步进±5%, 冷却30天
跨broker转账需人工（miniQMT↔ECMarkets）

> 详见 DEV_FOREX.md §七

---

## 九、风控体系

### 9.1 四层纵深防御

```
Layer 1 — 开仓前（5项硬性检查，任一不过则拒绝）
  ① 单笔风险 ≤ 2%
  ② 总保证金 ≤ 50%
  ③ 单品种 ≤ 3手
  ④ 相关品种风险 ≤ 4%
  ⑤ 同时持仓 ≤ 8笔

Layer 2 — 持仓中（4项动态监控）
  ⑥ 每日最大亏损 3%禁新仓 / 5%强平
  ⑦ 回撤熔断 15%减仓 / 20%暂停 / 25%全平
  ⑧ 持仓超20天强制平仓
  ⑨ 信号质量衰退 → 暂停/冷却

Layer 3 — 极端事件（3项保护）
  ⑩ 周五减仓（浮盈<1ATR→平仓）
  ⑪ 经济事件保护（高影响前1h锁利+暂停新仓）
  ⑫ 低流动性禁止开仓（05:00-06:00 UTC）

Layer 4 — 系统级（2项兜底）
  ⑬ MT5断连保护（SL在broker端仍有效）
  ⑭ 每日风控报告推送
```

### 9.2 与A股风控的关系

共用: 分层架构 / 通知机制 / 日报模板 / ai_parameters存储 / 风控Agent框架
外汇独有: 保证金 / 相关性 / 周五减仓 / 经济事件 / 流动性时段 / MT5断连 / Swap监控

> 详见 DEV_FOREX.md §八

---

## 十、成本模型

### 10.1 成本构成

| 成本项 | A股 | 外汇(STD) |
|--------|-----|----------|
| 佣金 | 万1.5 | 0（含在点差中） |
| 税费 | 印花税0.05% + 过户费0.001% | 无 |
| 点差 | 无（集中竞价） | 1.0-3.5pip（品种+时段不同） |
| Swap | 无 | 每日结算（可正可负） |
| 滑点 | Volume-impact模型 | 0.2-5pip（市场状况不同） |

### 10.2 成本对策略的影响

成本占日均波动比: EUR/USD 1.5%（优秀）→ EUR/GBP 4.0%（较高）
日频策略（持仓3-20天）所有品种成本可控
小时频策略（Phase 3）高成本品种需排除

### 10.3 成本优化规则

- 低流动性时段不开仓（点差2-5倍）
- overlap时段优先（点差最窄）
- 避免周三开仓（三倍Swap）
- 信号中性时偏向正Swap方向

> 详见 DEV_FOREX.md §九

---

## 十一、交易接口（MT5）

### 11.1 部署架构

```
Windows(Parallels)                    macOS
┌─────────────────────┐              ┌──────────────────┐
│ MT5 Terminal        │              │ QuantMind主服务   │
│ (ECMarkets)         │              │ (PG+FastAPI+     │
│       ↕ IPC         │   HTTP/WS   │  Celery)         │
│ MT5 Adapter         │←───────────→│                  │
│ (FastAPI :8001)     │  localhost   │                  │
└─────────────────────┘              └──────────────────┘
```

### 11.2 关键设计

- Adapter封装所有MT5 API，主服务通过HTTP调用
- SL/TP在broker端server-side执行，Python断连不影响止损
- magic=88888标识自动交易，与手动操作区分
- 每分钟持仓同步（MT5→PostgreSQL）
- filling_type兼容性需Phase 2首日验证

### 11.3 Paper Trading → 实盘

Demo账户=Paper Trading，切换只需改.env
Demo最少3个月→通过18项检查清单→切Live→前2周半仓运行

> 详见 DEV_FOREX.md §十、§十五

---

## 十二、ML与LLM模型

### 12.1 ML模型路线图

| Phase | 模型 | 用途 |
|-------|------|------|
| Phase 2 | LightGBM | 信号过滤（21因子→方向概率→调整confidence） |
| Phase 2 | Optuna | 策略参数+LightGBM超参贝叶斯搜索 |
| Phase 2 | 随机森林 | baseline对比 |
| Phase 3 | MLP/XGBoost | 集成投票 |
| Phase 3 | GRU | H1时序预测 |
| Phase 4 | Transformer | 预训练微调 |

### 12.2 LLM模型（可配置）

| 环节 | A股默认 | 外汇默认 | 理由 |
|------|--------|---------|------|
| 假设生成 | DeepSeek R1 | Claude Sonnet | 外汇英文知识更强 |
| 代码生成 | DeepSeek V3 | DeepSeek V3 | 代码能力与领域无关 |
| 诊断分析 | DeepSeek R1 | Claude Sonnet | 品种特定诊断需外汇知识 |

前端Agent配置页可切换，降级: Claude→DeepSeek→本地(Phase 4)
多模型投票: Phase 3预留接口

### 12.3 A股ML升级（同步）

Phase 1加入: Optuna搜索LightGBM超参 + 随机森林baseline
Phase 3加入: XGBoost + MLP + 集成投票

> 详见 DEV_FOREX.md §十二、§十三、§十四

---

## 十三、数据库表（7张新表）

| # | 表名 | 用途 | 关键字段 |
|---|------|------|---------|
| 1 | forex_symbol_config | 品种配置 | symbol/tier/spread/atr/pip_value/filling_mode |
| 2 | forex_correlation | 品种间相关性 | symbol_a/symbol_b/period_days/correlation |
| 3 | forex_macro_data | 宏观经济数据 | currency/indicator/value/period_date |
| 4 | forex_cot_data | COT持仓 | symbol/spec_net/spec_net_pct |
| 5 | forex_factor_config | 外汇因子配置 | name/layer/category/win_rate/pf/sharpe |
| 6 | forex_backtest_trades | 回测交易明细 | symbol/direction/lot/pnl_pips/spread_cost/swap_cost |
| 7 | forex_swap_rates | Swap费率历史 | symbol/rate_date/swap_long/swap_short |

已有表扩展: forex_bars新增session/is_holiday/data_source字段
已有表复用: backtest_run(market='forex'), forex_events(不变)

总数据库表: 43(A股) + 7(外汇) = **50张**

> DDL详见 DEV_FOREX.md §十六

---

## 十四、Phase路线图

```
Phase 0（当前，不做外汇）:
  ✓ 数据库表预留(forex_bars + forex_events已建)
  ✓ market字段预留
  ✓ 前端外汇占位(Dashboard外汇卡片"Phase 2即将开放")

Phase 2（外汇MVP，预计4-6周）:
  Week 1-2: MT5环境搭建 + HistData导入 + 数据验证
  Week 2-3: 21因子实现 + 策略A规则编码 + 成本模型
  Week 3-4: Python回测引擎 + Walk-Forward
  Week 4-5: LightGBM信号过滤 + Optuna参数搜索
  Week 5-6: MT5 Adapter + 风控实现 + Demo账户Paper Trading

Phase 2 交付验收:
  回测: Sharpe>0.5, PF>1.3, MDD<25%
  系统: MT5连接稳定, 持仓同步正确, 14项风控生效
  → Paper Trading开始（最少3个月）

Phase 3（外汇完善 + AI闭环，Paper Trading期间）:
  策略B(小时频短线)
  Layer 3 AI优化
  MLP/XGBoost/GRU集成
  因子挖掘外汇适配全量运行
  跨市场AI动态分配

Phase 3 交付验收:
  Paper: 衰减率<50%, 3个月Sharpe>0.3
  → 通过实盘切换检查清单 → 切Live

Phase 4（本地MLX + 高级模型）:
  Transformer微调 / GNN货币关联 / 多模型投票
```

---

## 十五、与总设计文档的关系

```
QUANTMIND_V2_DESIGN_V5.md          ← A股总设计（决策1-80，表1-43）
QUANTMIND_V2_FOREX_DESIGN.md       ← 外汇总设计（决策81-93，表44-50）← 本文档
  │
  ├── DEV_FOREX.md                 ← 外汇详细开发文档（16章676行）
  │     完整实现规格/代码模板/Prompt/DDL
  │
  共用开发文档:
  ├── DEV_AI_EVOLUTION.md          ← AI闭环（外汇通过market路由复用）
  ├── DEV_FACTOR_MINING.md         ← 因子挖掘（外汇替换Prompt/评估）
  ├── DEV_PARAM_CONFIG.md          ← 参数可配置（新增外汇参数）
  ├── DEV_FRONTEND_UI.md           ← 前端UI（市场切换器路由）
  └── DEV_BACKTEST_ENGINE.md       ← A股回测（外汇独立，不复用）
```
