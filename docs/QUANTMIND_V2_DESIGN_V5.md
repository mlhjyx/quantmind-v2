# QuantMind V2 — AI量化交易终端系统 总设计文档

> **⚠️ 文档状态: ARCHIVED (2026-04-10)**
> 实现状态: ~20% — 已被 ROADMAP_V3 替代。整体架构设计过大，实际运行的是子集。
> 仍有价值: 数据模型定义、分层架构原则
> 已过时/被替代: 大部分模块设计被 DEV_*.md 系列替代，总路线图迁移至 ROADMAP_V3
> 参考: docs/QUANTMIND_FACTOR_UPGRADE_PLAN_V3.md

> **版本**: 5.0 | **日期**: 2026-03-19
> **作者**: Stanley Tu + Claude (Anthropic)
> **决策**: 完全重新开发，V1仅作为教训参考
> **目标市场**: A股（多因子选股） + 外汇CFD（MT5/ECMarkets） | 预留：美股/港股
> **核心定位**: 绝对收益策略（A股 + 外汇均为绝对收益）
> **设计原则**: AI闭环驱动 · 验证前置 · 最小复杂度 · 模块化替换

---

# 目录

- 第一章 战略决策总览
- 第二章 V1教训与V2设计原则
- 第三章 系统总体架构与底层运行闭环
- 第四章 A股因子体系
- 第五章 A股Universe构建
- 第六章 A股组合构建逻辑
- 第七章 AI智能层——闭环设计
- 第八章 风控体系
- 第九章 数据层 (DataHub)
- 第十章 数据库完整Schema
- 第十一章 回测层
- 第十二章 执行层
- 第十三章 验证层
- 第十四章 归因分析
- 第十五章 前端层（11个页面已设计）
- 第十六章 外汇详细设计 [待讨论]
- 第十七章 AI进化闭环完整设计（4 Agent + Pipeline已设计）
- 第十八章 每日调度与运维 [待讨论]
- 第十九章 通知告警系统 [待讨论]
- 第二十章 配置管理体系 [待讨论]
- 第二十一章 miniQMT对接方案 [待讨论]
- 第二十二章 高级特性整合 [待讨论]
- 第二十三章 MVP定义与实施路线图
- 第二十四章 项目文件结构
- 第二十五章 成本预算与容量规划
- 第二十六章 心理纪律框架
- 第二十七章 协作流程与知识管理
- 附录A V1教训清单
- 附录B 完整决策记录
- 附录C 学术与开源参考资料
- 附录D 待讨论议题清单
- 附录E 开发文档索引

---

# 第一章：战略决策总览

## 1.1 已确认的25项核心决策（+34项回测/AI闭环决策，详见附录B）

### 战略层（5项）

| # | 决策点 | 结论 |
|---|--------|------|
| 1 | A股策略哲学 | D: 人工设定因子框架 + AI在框架内挖掘优化 |
| 2 | 外汇策略哲学 | C: 多层融合——宏观定方向+技术定入场+AI优化参数 |
| 3 | 外汇交易频率 | C: 混合频率——日频趋势策略+小时频短线策略组合 |
| 4 | 外汇品种范围 | C: 主要货币对+商品货币(AUD/CAD/NZD)+避险货币(JPY/CHF) |
| 5 | 两市场关系 | D: AI动态调整两个市场的资金分配比例 |

### 因子与选股（5项）

| # | 决策点 | 结论 |
|---|--------|------|
| 6 | A股核心因子 | 全选四类: ①价量技术 ②流动性 ③资金流向 ④基本面价值 |
| 7 | A股扩展因子 | 全选四类: ⑤成长 ⑥分析师预期 ⑦事件驱动 ⑧情绪舆情 |
| 8 | Universe范围 | A: 全A股含北交所（主板±10%/创业板科创板±20%/北交所±30%） |
| 9 | 持仓数量 | C: AI动态调整N（10-50范围，默认30） |
| 10 | 权重分配 | D: AI动态选择权重方案（等权/因子加权/HRP间切换） |

### 执行与调仓（3项）

| # | 决策点 | 结论 |
|---|--------|------|
| 11 | A股执行通路 | miniQMT（国金证券，开户中，待搭建） |
| 12 | 调仓频率 | D: 混合——基础周期+事件触发+AI优化周期参数 |
| 13 | 仓位管理 | C: 规则底线(熊市强制降仓)+AI在范围内优化仓位 |

### AI体系（3项）

| # | 决策点 | 结论 |
|---|--------|------|
| 14 | AI自主权边界 | D: 分层授权——L1自动/L2人工确认/L3双重确认 |
| 15 | AI启动策略 | D: 模块化替换——逐环节验证，AI超过规则才替换 |
| 16 | AI安全网 | B: 层级fallback——AI失败→规则版→清仓 |

### 风控（3项）

| # | 决策点 | 结论 |
|---|--------|------|
| 17 | A股风控哲学 | D: 分层——硬规则(不可破)+软规则(AI可调)+熔断机制 |
| 18 | 止损硬底线 | B: 月亏>10%降仓，累计>25%停止交易 |
| 19 | 外汇风控 | 全选5项: 单笔≤2%/保证金≤50%/周五减仓/单品种限仓/GARCH止损 |

### 技术架构（3项）

| # | 决策点 | 结论 |
|---|--------|------|
| 20 | 回测引擎 | D: Python先行，性能瓶颈时局部Rust（渐进式） |
| 21 | 前端技术 | B: Streamlit启动→后期React重写 |
| 22 | 外汇broker | ECMarkets标准账户，1:100杠杆，点差包含在报价中无佣金 |

### 项目规划（3项）

| # | 决策点 | 结论 |
|---|--------|------|
| 23 | MVP定义 | C: 完整规则版管道（数据+因子+回测+Paper Trading+通知+Streamlit） |
| 24 | Phase 0时间 | D: 不设时间限制，质量优先 |
| 25 | 开发方式 | C: 全职投入 |

## 1.2 AI控制的14个动态参数

系统中由AI动态调整的参数完整清单，所有参数都有硬边界和规则版默认值：

| 参数 | 搜索范围 | 默认值(fallback) | 授权级别 |
|------|---------|-----------------|---------|
| 跨市场资金分配 | A股50-90%/外汇10-50% | A股70%/外汇30% | L2 |
| Universe市值门槛 | 5亿-50亿 | 20亿 | L1 |
| Universe成交额门槛 | 200万-2000万/天 | 500万/天 | L1 |
| Universe停牌天数门槛 | 3-30天 | 10天 | L1 |
| 因子中性化方式 | 每因子独立决定 | 市值+行业双重 | L1 |
| 因子权重/择时 | [0.5x, 1.5x]调整 | IC加权 | L1 |
| Alpha Score合成方案 | {等权,IC加权,LightGBM} | 等权 | L2 |
| 持仓数N | 10-50 | 30 | L1 |
| 权重方案 | {等权,alpha加权,HRP} | 等权 | L2 |
| 单股权重上限 | 3%-15% | 8% | L1 |
| 行业权重上限 | 10%-35% | 25% | L1 |
| 换手率上限 | 10%-80% | 50% | L1 |
| 总仓位比例 | 0%-100% | 规则决定 | L1(范围内)/L2(突破规则) |
| 调仓频率 | {周/双周/月}+事件触发 | 月频 | L2 |

授权级别说明：
- L1: AI自动执行，不需人工确认
- L2: 需要人工确认后AI才执行
- L3: 需要人工确认+验证管道双重确认

---

# 第二章：V1教训与V2设计原则

## 2.1 V1五大事故

| # | 事故 | 根因 | V2对策 |
|---|------|------|--------|
| 1 | Tushare复权——5个月回测全不可信 | 没看文档假设数据格式 | Data Contract |
| 2 | HashMap非确定性——Sharpe随机波动 | Rust HashMap随机遍历 | Python先行+确定性CI |
| 3 | LLM因子挖掘零产出 | 无假设/正则化/闭环 | 三级退化Plan A/B/C |
| 4 | WF脚本bash数组bug | 缺测试 | Python重写+单元测试 |
| 5 | Paper Trading 502 | 服务太多管不过来 | cron+脚本，最少服务 |

## 2.2 V2六条铁律

1. **先验证再建设** — notebook验证通过后才工程化
2. **数据不可信直到证明可信** — 自动化Data Contract
3. **确定性是CI门禁** — 改动后自动测试，不一致则构建失败
4. **站在巨人肩膀上** — 成熟开源库优先（alphalens/riskfolio-lib/mlfinlab）
5. **最小复杂度** — 每个模块问"对Alpha有直接贡献吗"
6. **文档即代码** — 字段含义用类型系统固化

## 2.3 完全重写的决策理由

代码不复用，但知识复用。V1教训清单（附录A）作为V2设计指南逐条对照。V1仓库保留不动（git tag v1-final-archive）。

## 2.4 五条工作原则（从V1继承）

1. 不靠猜测做技术判断，涉及外部接口必须先完整阅读官方文档
2. 任何数据源接入前先建data_source_checklist验证正确性
3. 做上层设计前先验证底层假设
4. 不确定就说不确定，不要基于猜测给方案
5. 每个模块完成后必须有自动化验证

---

# 第三章：系统总体架构与底层运行闭环

## 3.1 架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          QuantMind V2 系统架构 (V5.1)                        │
│                                                                              │
│  ┌─────────────────────────────── 前端层 ───────────────────────────────┐   │
│  │  React 18 + Tailwind + shadcn/ui + ECharts/Recharts                  │   │
│  │  12个导航页面 | Glassmorphism | WebSocket实时 | 市场切换器(A股/外汇)  │   │
│  └────────────────────────────────┬──────────────────────────────────────┘   │
│                                   │ HTTP REST + WebSocket                    │
│  ┌────────────────────────────────┴──────────────────────────────────────┐   │
│  │                        后端API层 (FastAPI)                             │   │
│  │  routers/ → services/ → repositories/ → PostgreSQL                    │   │
│  │  ~57 REST端点 + 5 WebSocket通道                                       │   │
│  └──┬─────────┬──────────┬──────────┬───────────┬───────────────────────┘   │
│     │         │          │          │           │                            │
│  ┌──┴──┐  ┌──┴──┐  ┌───┴───┐  ┌──┴──┐  ┌────┴─────┐                      │
│  │数据层│  │研究层│  │回测层  │  │AI层  │  │执行层     │                      │
│  │     │  │     │  │       │  │     │  │          │                      │
│  │AKSh │  │34因子│  │Rust引擎│  │4Agent│  │miniQMT   │                      │
│  │Tush │  │21外汇│  │Py外汇  │  │LLM/GP│  │MT5 Adapt │                      │
│  │MT5  │  │LgBM │  │WF/CPCV│  │Optuna│  │(Windows) │                      │
│  └──┬──┘  └──┬──┘  └───┬───┘  └──┬──┘  └────┬─────┘                      │
│     │        │         │         │           │                              │
│  ┌──┴────────┴─────────┴─────────┴───────────┴──────────────────────────┐   │
│  │                    异步任务层 (Celery + Redis)                         │   │
│  │  Celery Beat(cron调度) → 8个队列 → Worker × 4                        │   │
│  │  A股15任务 + 外汇11任务 + AI Pipeline + 系统维护                      │   │
│  └──────────────────────────────┬────────────────────────────────────────┘   │
│                                 │                                            │
│  ┌──────────────────────────────┴────────────────────────────────────────┐   │
│  │                    数据持久层                                          │   │
│  │  PostgreSQL + TimescaleDB | 51张表(A股41+外汇7+通知2+调度1)           │   │
│  │  Redis: Celery Broker + 缓存 + 任务状态 + 节流控制                    │   │
│  └──────────────────────────────┬────────────────────────────────────────┘   │
│                                 │                                            │
│  ┌──────────────────────────────┴────────────────────────────────────────┐   │
│  │                    通知与监控层                                        │   │
│  │  NotificationService(4级分级) → 站内WS + 钉钉Webhook                  │   │
│  │  25+通知模板 | 防洪泛 | 静默时段 | 偏好配置                           │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  MacBook Pro M1 Pro (开发) → Mac Studio M3 Ultra (Phase 4生产)              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 3.2 技术栈（V5.1更新）

| 层 | 选型 | 理由 |
|---|------|------|
| 后端框架 | FastAPI (async) | 高性能异步API + WebSocket原生支持 |
| 前端 | React 18 + Tailwind + shadcn/ui | 组件化 + Glassmorphism设计系统 |
| A股回测 | Rust(向量化信号) + Python(事件驱动执行) Hybrid | 3000股×1200天需要性能 |
| 外汇回测 | Python纯事件驱动 | 14品种×20年，Python秒级完成 |
| 因子研究 | pandas + talib + 自定义因子引擎 | 灵活性优先 |
| ML模型 | LightGBM + Optuna + 随机森林(Phase 2+: MLP/XGB/GRU) | 渐进式复杂度 |
| AI因子挖掘 | DeepSeek R1/V3(A股) + Claude Sonnet(外汇,可配置) + GP遗传编程 | 分环节最优模型 |
| 任务调度 | Celery Beat + Celery Worker + Redis | 单一调度框架，8个队列 |
| A股执行 | miniQMT (国金证券) | Python接口 |
| 外汇执行 | MT5 Python API (ECMarkets) + FastAPI Adapter(Windows) | 解耦Windows依赖 |
| 数据库 | PostgreSQL 16 + TimescaleDB | 时序查询+JSONB灵活存储 |
| 缓存/消息 | Redis 7 | Celery Broker + 状态缓存 + 节流控制 |
| WebSocket | FastAPI内置 + socket.io-client(前端) | 5个通道，实时推送 |
| 日志 | loguru | 结构化日志 + 文件轮转 |
| 环境 | brew/pip，不用Docker | 节省16GB内存 |

## 3.3 硬件环境

**开发期：MacBook Pro M1 Pro 16GB / 512GB**
- ✓ FastAPI+Celery+PostgreSQL+Redis全部本地运行
- ✓ Python回测、LightGBM/GARCH、React前端开发
- ✗ Transformer训练、本地LLM推理
- ✗ MT5原生(需Parallels Desktop虚拟机)

**生产期（Phase 4）：Mac Studio M3 Ultra 256GB / 4TB**
- 所有开发期能力 + 本地MLX大模型 + MT5 PD虚拟机24小时

## 3.4 模块间通信（V5.1更新）

```
所有模块通过三种方式通信:

1. 同步请求: 前端 ←→ FastAPI REST API ←→ Service层 ←→ PostgreSQL
   用于: 页面数据加载、配置读写、用户操作

2. 异步任务: FastAPI → Celery任务队列 → Worker执行 → 结果写入PostgreSQL
   用于: 回测运行、因子计算、AI Pipeline、数据更新

3. 实时推送: 后端 → WebSocket → 前端
   用于: 回测进度、外汇实时报价、通知推送

调用方向(严格单向):
  Router → Service → Repository → Database
  Service → CeleryTask(异步)
  Service → NotificationService(通知)
  CeleryTask → Service(复用业务逻辑)
  CeleryTask → NotificationService(任务完成/失败通知)

禁止:
  ✗ Router直接访问Database
  ✗ Repository调用Service(循环依赖)
  ✗ 前端直接访问Database
```

## 3.5 进程模型（开发环境）

```
启动顺序:

1. PostgreSQL    (brew services start postgresql@16)
2. Redis         (brew services start redis)
3. FastAPI       (uvicorn backend.main:app --reload --port 8000)
4. Celery Worker (celery -A backend.tasks worker -Q astock_data,... --concurrency=4)
5. Celery Beat   (celery -A backend.tasks beat)
6. React Dev     (cd frontend && npm run dev -- --port 3000)

外汇交易时(额外):
7. Parallels     (Windows VM)
8. MT5 Terminal  (ECMarkets登录)
9. MT5 Adapter   (uvicorn mt5_adapter:app --port 8001)  # Windows内

所有进程通过一个启动脚本(scripts/start_all.sh)管理
开发时用tmux多窗格，每个进程一个窗格
```

---

# 第四章：A股因子体系

## 4.1 设计哲学

人工设定因子框架（4大类+4扩展类），AI在框架内挖掘和优化。因子不是固定的——AI闭环持续搜索新因子、淘汰失效因子、优化因子权重。

## 4.2 核心因子清单（Phase 0-1，34个）

### 类别①：价量技术类（12个）

| 因子名 | 公式简述 | 方向 | 数据源 | 学术支持 |
|--------|---------|------|--------|---------|
| reversal_5 | 5日收益率 | 反向 | klines_daily | ★★★★★ |
| reversal_20 | 20日收益率 | 反向 | klines_daily | ★★★★★ |
| momentum_60 | 60日收益率 | 正向 | klines_daily | ★★★★ |
| momentum_120 | 120日收益率(跳过最近20日) | 正向 | klines_daily | ★★★★ |
| volatility_20 | 20日收益率标准差 | 反向 | klines_daily | ★★★★★ |
| idio_vol_20 | 残差波动率(FF3残差std) | 反向 | klines_daily | ★★★★★ |
| max_ret_20 | 20日最大单日涨幅 | 反向 | klines_daily | ★★★★ |
| volume_price_corr | 量价相关性(20日) | 反向 | klines_daily | ★★★★ |
| KMID | (close-open)/open | 正向 | klines_daily | ★★★ |
| KSFT | (2*close-high-low)/open | 正向 | klines_daily | ★★★ |
| CNTP_20 | 20日上涨天数占比 | 正向 | klines_daily | ★★★ |
| RSV_20 | 相对强弱值 | 正向 | klines_daily | ★★★ |

### 类别②：流动性类（6个）

| 因子名 | 公式简述 | 方向 | 数据源 | 学术支持 |
|--------|---------|------|--------|---------|
| turnover_20 | 20日平均换手率 | 反向 | daily_basic | ★★★★★ |
| turnover_vol_20 | 换手率波动率(20日std) | 反向 | daily_basic | ★★★★★ |
| amihud_20 | Amihud非流动性(\|ret\|/amount) | 正向 | klines_daily | ★★★★ |
| volume_ratio_20 | 成交量比(vol/vol_ma60) | 反向 | klines_daily | ★★★★ |
| amount_std_20 | 成交额波动率(20日) | 反向 | klines_daily | ★★★★ |
| turnover_zscore_20 | 标准化换手率(z-score) | 反向 | daily_basic | ★★★★ |

### 类别③：资金流向类（6个）

| 因子名 | 公式简述 | 方向 | 数据源 | 学术支持 |
|--------|---------|------|--------|---------|
| north_flow_net_20 | 北向资金净买入20日累计 | 正向 | hk_hold | ★★★★ |
| north_flow_change | 北向资金变化率 | 正向 | hk_hold | ★★★ |
| big_order_ratio | 大单净流入占比 | 正向 | moneyflow | ★★★ |
| margin_balance_chg | 融资余额变化率 | 正向 | margin_data | ★★★ |
| short_ratio | 融券余额/融资余额 | 反向 | margin_data | ★★★ |
| winner_rate | 获利盘比例 | 反向 | cyq_perf | ★★★ |

### 类别④：基本面价值类（8个）

| 因子名 | 公式简述 | 方向 | 数据源 | 学术支持 |
|--------|---------|------|--------|---------|
| ep | 1/PE_TTM(盈利收益率) | 正向 | daily_basic | ★★★★ |
| bp | 1/PB(账面市值比) | 正向 | daily_basic | ★★★ |
| div_yield | 股息率TTM | 正向 | daily_basic | ★★★ |
| roe_ttm | 净资产收益率TTM | 正向 | fina_indicator | ★★★★ |
| gross_margin | 毛利率 | 正向 | fina_indicator | ★★★ |
| roa_ttm | 总资产收益率TTM | 正向 | fina_indicator | ★★★ |
| debt_to_asset | 资产负债率 | 反向 | fina_indicator | ★★★ |
| current_ratio | 速动比率 | 正向 | fina_indicator | ★★★ |

### 类别⑤：规模（1个）

| 因子名 | 公式简述 | 方向 | 数据源 |
|--------|---------|------|--------|
| ln_float_cap | ln(流通市值) | 反向 | daily_basic |

### 类别⑥：行业（1个，用于中性化和归因）

| 因子名 | 说明 | 数据源 |
|--------|------|--------|
| sw_industry_1 | 申万一级行业（31个） | Tushare index_classify |

**合计：34个（32个参与alpha_score + 2个用于中性化/归因）**

## 4.3 扩展因子（Phase 1+，AI闭环挖掘）

| 类别 | 方向 | 数据源 | Phase |
|------|------|--------|-------|
| ⑤成长 | 营收增速/利润增速/ROE变化 | fina_indicator | Phase 1 |
| ⑥分析师预期 | 一致预期变化/目标价偏离 | report_rc | Phase 1 |
| ⑦事件驱动 | 解禁/增减持/业绩预告 | share_float+stk_holdertrade | Phase 1+ |
| ⑧情绪舆情 | 新闻情感+NLP | AKShare+DeepSeek | Phase 2 |

## 4.4 因子预处理标准化流程

每个截面日期独立执行，顺序不可颠倒：

```
Step 1: 缺失值处理
  缺失率>30%的股票 → 该因子标记NaN不参与排名
  缺失率≤30% → 行业中位数填充

Step 2: 去极值（MAD法）
  median ± 5×MAD，超出截断到边界

Step 3: 中性化（AI决定每个因子是否中性化）
  方式: factor_neutral = residual of: factor ~ ln_cap + industry_dummies
  回归方法: WLS（市值加权）
  AI测试每个因子中性化和不中性化的Gate结果，选更优的

Step 4: 标准化
  Z-Score: (x - mean) / std → 均值0标准差1

Step 5: 再次截断
  |z| > 3 截断到 ±3
```

## 4.5 因子衰减处置流程

```
Level 1: IC_MA20 < IC_MA60 × 0.8（轻微衰减）
  → P2告警（日报标黄）
  → 不自动操作

Level 2: IC_MA20 < IC_MA60 × 0.5（显著衰减）
  → P1告警
  → 自动降权至0.5x（L1授权，不需人工）
  → 触发AI闭环诊断

Level 3: IC_MA60 < 0.01 连续60天（持续失效）
  → 从active退为candidate（需人工确认）
  → 触发AI因子挖掘闭环寻找替代
```

## 4.6 因子择时机制

```
每个因子的权重不是固定的，AI在[0.5x, 1.5x]范围内动态调整：

监控维度：
  滚动IC（20日/60日）
  因子拥挤度（多头组换手率变化）
  宏观状态（货币-信用周期）

调整规则（L1自动授权）：
  因子近期IC走强 → 权重提升（最高1.5x）
  因子近期IC走弱 → 权重降低（最低0.5x）
  不能完全删除因子（L2权限）
```

## 4.7 交互因子搜索空间（AI闭环探索）

```
AI因子挖掘闭环的搜索空间定义：

跨类别组合（候选）：
  价量×流动性: reversal_5 × (1 - turnover_rank)
  资金流×价量: north_flow_net_20 × momentum_60
  基本面×流动性: roe_ttm × amihud_20

搜索方法（三级退化）：
  Plan A: AlphaAgent/RD-Agent完整集成
  Plan B: DeepSeek API简化版三Agent
  Plan C: 人工提假设+AI生成代码

GP遗传编程（补充搜索）：
  表达式树进化搜索，自动发现因子公式
  搜索空间: 基础算子{+,-,×,÷,rank,ts_mean,ts_std,ts_corr,delay}
```

---

# 第五章：A股Universe构建

## 5.1 过滤规则（8层）

```
Layer 1: 剔除ST/*ST/退市整理期          硬规则     stock_basic
Layer 2: 剔除上市不足60天的新股          硬规则     stock_basic
Layer 3: 剔除当日停牌                    硬规则     suspend_d
Layer 4: 剔除当日涨停（买不进）          硬规则     price=limit_up
Layer 5: 剔除当日跌停（已持仓卖不出）    条件规则   price=limit_down
Layer 6: 剔除流通市值<AI门槛             AI软规则   daily_basic
Layer 7: 剔除20日均成交额<AI门槛         AI软规则   klines_daily
Layer 8: 剔除连续停牌>AI门槛天           AI软规则   suspend_d
```

## 5.2 AI动态门槛

| 参数 | 硬底线 | AI范围 | 默认值 | 调整频率 |
|------|--------|--------|--------|---------|
| 市值门槛 | 5亿 | 5亿-50亿 | 20亿 | 月度 |
| 成交额门槛 | 200万/天 | 200万-2000万 | 500万/天 | 月度 |
| 停牌天数 | 3天 | 3-30天 | 10天 | 月度 |

AI调整逻辑：牛市放宽（小票活跃）→ 熊市收紧（流动性枯竭）

## 5.3 三种涨跌停规则

| 板块 | 涨跌停 | 识别字段 |
|------|--------|---------|
| 主板（沪深） | ±10% | symbols.board = 'main' |
| 创业板+科创板 | ±20% | symbols.board IN ('gem','star') |
| 北交所 | ±30% | symbols.board = 'bse' |

回测引擎必须根据board字段使用不同阈值。

## 5.4 时间一致性（防前视偏差）

T日Universe只用T日及之前的信息构建。输出写入universe_daily表。回测引擎只读此表。

## 5.5 已持仓股票保护

持仓中的股票被剔出Universe → 不强制卖出，只是不会新买入。停牌/跌停的持仓 → 等复牌/解除后按正常逻辑处理。

---

# 第六章：A股组合构建逻辑

## 6.1 完整链路（7步）

```
因子值(34个) → ①Alpha Score合成 → ②排名选股(Top-N)
→ ③权重分配 → ④约束调整 → ⑤换手控制
→ ⑥整手处理(100股) → ⑦最终目标持仓
```

## 6.2 Step ① Alpha Score合成

```
规则baseline: 等权平均 alpha_score = mean(z1, z2, ..., z34)
AI候选方案:
  IC加权: alpha_score = Σ(IC_i × z_i)，滚动60天IC
  LightGBM: alpha_score = model.predict(z1,...,z34)，月度重训
  HRP因子权重: riskfolio-lib计算

模块化替换: 哪个OOS超过等权就切换到哪个
```

## 6.3 Step ② 排名选股

```
N = AI动态[10-50]，默认30
逻辑: 因子信号强且集中→N小(集中)，信号弱且分散→N大(分散)
并列处理: 按成交额降序（确定性tie-break）
```

## 6.4 Step ③ 权重分配

```
规则baseline: 等权 1/N
AI候选: {alpha加权, HRP, MVO}
模块化替换
```

## 6.5 Step ④ 约束调整

```
单股权重: AI动态[3%-15%]，默认8%，硬上限15%
行业权重: AI动态[10%-35%]，默认25%，硬上限35%
总仓位: 规则底线(市场状态)+AI优化

超限处理:
  超重股票 → 截断到上限
  多出权重 → 按比例分配给未超限股票
  行业超限 → 该行业内按alpha降序保留到限额
```

## 6.6 Step ⑤ 换手控制

```
AI动态换手率上限: [10%-80%]，默认50%
硬底线10%（至少做一些调整），硬上限80%

触及上限时的处理:
  对每个变更计算: 边际改善 = alpha(新) - alpha(旧) - 交易成本估算
  按边际改善降序执行，直到触及上限
  剩余变更延迟到下次调仓
```

## 6.7 Step ⑥ 整手处理

```
目标股数 = floor(总资金 × 权重 / 股价 / 100) × 100
零头保留现金（通常<2%）
北交所同样100股最小单位
```

## 6.8 Step ⑦ 执行顺序（T+1）

```
1. 计算目标持仓 vs 当前持仓差异
2. 检查涨跌停/停牌 → 移出调仓列表
3. 先卖出（回收资金，A股卖出资金当天可用于买入）
4. 计算可用资金
5. 按alpha降序执行买入（资金不够时优先买最强信号）
6. 100股round down
7. 记录实际持仓 vs 目标持仓偏差
```

---

# 第七章：AI智能层——闭环设计

## 7.1 分层授权机制

```
L1 全自动（不需人工确认）：
  日常调仓执行（在已确认的策略框架内）
  因子权重微调（[0.5x, 1.5x]范围内）
  持仓数N在[10-50]范围内调整
  Universe门槛在搜索范围内调整
  单股/行业权重在范围内调整
  换手率上限调整

L2 需要人工确认：
  新因子上线到active
  Alpha Score合成方案切换
  权重方案切换
  调仓频率方案切换
  跨市场资金分配大幅调整（>10%）
  AI参数搜索范围本身的修改

L3 需要人工+验证管道双重确认：
  策略逻辑变更
  风控硬规则参数修改
  模型架构变更
```

## 7.2 模块化替换策略

```
Phase 0: 所有环节用规则版（默认值）
Phase 1: 逐个环节让AI接管

替换条件: AI版OOS指标 > 规则版指标（至少在3个月的OOS期间）
替换方式: 只替换一个环节，其余不动
验证: Walk-Forward + 确定性测试

如果AI版不如规则版 → 保持规则版，记录失败原因，下个月重试
```

## 7.3 层级Fallback

```
AI版崩溃/异常 → 加载最后确认有效的规则版参数
规则版也异常 → 清仓等待人工介入
清仓后 → P0告警（钉钉+短信）
```

## 7.4 模型训练更新触发

| 模型 | 定期 | 事件触发 | 训练数据 | 更新条件 |
|------|------|---------|---------|---------|
| LightGBM | 每月第一周末 | WF Sharpe连续2月下降 | 滚动24个月 | 新OOS≥旧95% |
| HMM | 每季度 | CUSUM状态突变 | 全量 | 状态识别准确率提升 |
| IsolationForest | 每月 | 新类型异常出现 | 滚动12个月 | 异常召回率提升 |

## 7.5 AI因子挖掘——完整设计

### 7.5.1 四引擎并行架构

```
搜索引擎        擅长什么                    成本    速度    Phase
──────────────────────────────────────────────────────────────
Engine 1:       简单量价因子穷举            0       极快    Phase 0
暴力枚举        (算子×字段×窗口排列组合)

Engine 2:       经典因子批量导入            0       快      Phase 0
开源因子库      Alpha158/Alpha101/TA-Lib

Engine 3:       有经济学逻辑的复杂因子      ¥0.1-0.2/轮  中    Phase 1
LLM三Agent      跨数据源组合、条件因子

Engine 4:       非直觉的非线性因子公式      0       慢      Phase 1+
GP遗传编程      表达式树进化搜索
```

V2策略：Engine 1+2先跑通建立因子池基线，Engine 3+4在基线之上做增量搜索。

### 7.5.2 LLM三Agent闭环

```
模型选择: 渐进式——先R1(假设)+V3(代码)，效果不好时加入其他模型
架构: 三Agent为核心 + GP为另一条搜索线，共享评估层和知识库
知识库: PostgreSQL结构化存储（mining_knowledge表）
运行频率: 每天自动一轮
假设数量: AI动态调整（前端可切手动/AI，默认3个）
代码重试: 最多3次+报错反馈（前端可调[0-5]）
```

**Idea Agent (DeepSeek R1):**
- System Prompt包含：A股市场特征、可用数据字段完整列表、可用算子列表、评估标准(IC>0.02等)、输出JSON格式
- User Prompt动态注入：当前因子库状态、最近10轮成功/失败摘要、高相关因子对、IC衰减因子、本轮搜索方向
- 6个搜索方向Hint模板：cross_source/conditional/nonlinear/decay_resistant/underexplored/refinement
- 每个假设要求完整因果链：市场现象→投资者行为→定价偏差→可预测性

**Factor Agent (DeepSeek V3):**
- System Prompt包含：代码硬约束9条（函数签名/groupby/禁止未来数据/除零保护等）、V1常见错误模式4个、正确代码模板4个(简单时序/滚动统计/跨字段/条件因子)
- User Prompt：假设内容+知识库中相似因子代码参考
- 重试时注入Python报错信息+行号

**Eval Agent (自动化管道，非LLM):**
- 6步：代码安全检查→沙箱执行(60秒/2GB)→IC快速筛选(|IC|>0.015)→4层Gate→正则化检查(AST原创性+假设对齐+复杂度)→写入知识库

**反馈闭环:**
- Gate失败时构建反馈Prompt，包含具体IC值、失败的Gate层、最相似因子名、分年IC
- 反馈注入下一轮Idea Agent的User Prompt

### 7.5.3 Prompt工程细节

```
LLM调用参数（全部前端可调）：
  Idea Agent:  temperature=0.8(默认), max_tokens=4096, top_p=0.95
  Factor Agent: temperature=0.2(默认), max_tokens=4096, top_p=0.9

Few-shot策略: 混合
  System Prompt: 2个固定经典案例（1成功跨源因子+1失败过拟合因子）
  User Prompt: 从知识库动态拉取与当前搜索方向最相关的1-2个案例

输出格式校验: 三层防护
  第1层: 正则表达式尝试从非JSON输出中提取关键字段
  第2层: 提取失败→重试1次（注入"请只返回JSON"提示）
  第3层: 还失败→跳过该假设，记录到知识库

Prompt版本管理:
  每个Prompt模板有版本号(如idea_system_v2.1)
  变更记录在PROMPT_CHANGELOG中
  支持A/B测试不同版本的Prompt效果
```

### 7.5.4 GP遗传编程引擎

```
表达式树:
  终端节点: $close/$open/$high/$low/$volume/$amount/$turnover + 常数
  函数节点: add/sub/mul/div/ts_mean/ts_std/ts_rank/ts_corr/ts_max/ts_min/delay/rank/abs/log/sign

进化参数（全部前端可调）：
  种群大小: 500 [100-2000]    交叉率: 0.7 [0.1-0.95]
  进化代数: 100 [20-500]      变异率: 0.1 [0.01-0.5]
  锦标赛: 5 [2-10]            最大树深: 6 [3-10]
  最大节点: 30 [10-80]         反拥挤阈值: 0.8 [0.5-0.95]

适应度: IC_mean × IC_IR × (1 - max_corr_with_existing)
反拥挤: 每代淘汰与已有因子corr>0.8的个体
输出: 进入共享4层Gate Pipeline
```

### 7.5.5 搜索方向调度器

```
算法: UCB1 Multi-Armed Bandit
方向池: cross_source/conditional/nonlinear/decay_resistant/underexplored/refinement
选择: score = avg_reward + sqrt(2*ln(total)/direction_rounds)
reward = 该方向成功因子数 / 总轮数
连续3轮无产出 → 自动切换方向
```

### 7.5.6 知识库Schema

```sql
CREATE TABLE mining_knowledge (
    id SERIAL PRIMARY KEY,
    source VARCHAR(16),           -- 'llm_agent'|'gp'|'brute_force'|'import'
    round_id INT,
    search_direction VARCHAR(32),
    hypothesis TEXT,
    hypothesis_model VARCHAR(32),
    factor_name VARCHAR(64),
    factor_code TEXT,
    expression TEXT,              -- GP才有
    category VARCHAR(32),
    direction VARCHAR(8),
    complexity_score INT,
    ast_node_count INT,
    ic_mean DECIMAL(8,6),
    ic_ir DECIMAL(8,6),
    t_stat DECIMAL(8,4),
    monotonicity DECIMAL(8,4),
    max_corr_existing DECIMAL(8,4),
    yearly_ic JSONB,
    gate_1_pass BOOLEAN, gate_2_pass BOOLEAN,
    gate_3_pass BOOLEAN, gate_4_pass BOOLEAN,
    all_gates_pass BOOLEAN,
    originality_score DECIMAL(8,4),
    hypothesis_alignment BOOLEAN,
    failure_reason VARCHAR(128),
    failure_detail TEXT,
    status VARCHAR(16),           -- 'success'|'failed'|'candidate'|'active'
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 7.6 参数可配置性体系

### 7.6.1 设计哲学

最大化可配置——几乎所有参数都能在前端调，给用户完全控制权。AI可以建议参数值，但最终决定权在用户。

### 7.6.2 四级控制体系

```
Level 0 硬编码: 安全底线（单股硬上限15%、累计亏损25%停止）
Level 1 配置文件: 系统级（API密钥、DB连接、熔断阈值）
Level 2 前端可调: 策略/搜索/展示参数（滑块/下拉/输入框实时生效）
Level 3 AI自动调: 14个AI动态参数（前端可切换手动/AI推荐/AI自动三态）
```

### 7.6.3 统一参数交互组件

```
每个参数的前端组件包含：
  三态切换: ○手动设定  ○AI推荐  ●AI自动
  控制器: 滑块/下拉/输入框（根据参数类型）
  信息行: 默认值 | AI推荐值 | 历史最优值
  说明: 参数含义的一句话解释

参数变更安全机制：
  合理性检查（前端即时，如单股上限<行业上限）
  影响预估（弹窗提示预计影响）
  版本记录（每次变更写入param_change_log）
  一键回滚到任何历史版本
```

### 7.6.4 前端可调参数完整清单

**GP引擎:** 种群/代数/交叉率/变异率/锦标赛/最大深度/节点数/反拥挤阈值/终端节点选择/函数节点选择/适应度权重 (13个)

**LLM Agent:** 模型选择/每轮假设数/重试次数/搜索方向/temperature/max_tokens/top_p/System Prompt编辑/IC快速筛选阈值 (9个)

**Factor Gate:** IC阈值/t-stat阈值/单调性阈值/相关性阈值/分年稳定N/IC计算窗口/IC类型 (7个)

**组合构建:** 持仓N/权重方案/单股上限/行业上限/换手率上限/调仓频率 (6个，各有手动/AI切换)

**Universe:** 新股天数/市值门槛/成交额门槛/停牌天数/包含板块 (5个)

**风控:** 外汇单笔风险/保证金上限/单品种限仓 (3个，A股硬规则只读)

**回测:** 时间范围/初始资金/佣金费率/滑点参数/基准指数/WF窗口/WF步进 (7个)

**AI模型:** LightGBM超参(5个)/HMM状态数/IsolationForest参数(2个)/重训频率/替换阈值 (10个)

**调度:** 数据更新时间/信号生成时间/推送截止时间/告警最大条数 (4个)

**因子预处理:** 去极值方法/MAD倍数/缺失值填充/标准化方法 (4个)

**因子选择:** 每个因子的开关/方向/窗口参数 (34×3=102个)

---

# 第八章：风控体系

## 8.1 A股分层风控

### 硬规则（代码级强制，AI无权修改）

```
单股权重硬上限: 15%
行业权重硬上限: 35%
总仓位上限: 100%
市值门槛硬底线: 5亿
成交额硬底线: 200万/天
```

### 软规则（AI可在范围内调整）

```
单股目标权重: AI在[3%-15%]内选
行业目标权重: AI在[10%-35%]内选
换手率上限: AI在[10%-80%]内选
动态仓位: AI在规则底线之上优化
```

### 熔断机制

```
L1: 单策略日亏>3% → 该策略暂停1天
L2: 总组合日亏>5% → 全部暂停
L3: 月亏>10% → 降仓50%
L4: 累计>25% → 停止所有交易 + 人工全面审查
```

## 8.2 外汇风控（5项全选）

```
① 单笔最大风险 ≤ 账户净值2%
② 总持仓保证金 ≤ 净值50%
③ 周五尾盘减仓（weekend gap风险）
④ 单品种最大持仓限制
⑤ GARCH动态止损（波动率高时加宽止损）
```

## 8.3 跨市场风控

```
正常期: A股和外汇相关性低(<0.2) → 分散化有效
危机期: 相关性急升(>0.8) → 自动降低总仓位到30%

压力测试场景（必须跑的）：
  2015年6-8月: A股股灾+人民币贬值
  2020年3月: 全球疫情抛售
  2022年: A股熊市+美联储加息+美元走强
```

---

# 第九章：数据层 (DataHub)

## 9.1 数据源架构

```
A股主数据源: Tushare Pro 8000积分(500次/分钟)
  日线+复权因子、每日指标、财务三表、资金流向、融资融券
  北向资金、券商预测、限售解禁、筹码分布、ST/停牌

A股补充源: AKShare（免费）
  分钟线、个股新闻、行业概念、宏观交叉验证

外汇: HistData.com(回测,M1数据2000-2024,3GB免费)
      MT5 API(ECMarkets,实时+执行)
```

## 9.2 Data Contract机制

每个数据源必须有YAML契约文件，定义字段类型/单位/值域/已知坑。接入流程：读文档→填契约→拉样本验证→交叉验证→completeness检查→复权专项检查。

## 9.3 关键设计

- **幂等性**: 所有写入用INSERT ON CONFLICT UPDATE
- **时区**: 数据库统一UTC，显示层转北京时间
- **PIT**: financial_indicators用actual_ann_date，回测WHERE actual_ann_date <= trade_date
- **增量更新**: 默认每日增量；数据有误/逻辑变更时全量重算

## 9.4 分红除权处理（V5.1补充）

```
存储方案: 不复权价格 + 复权因子(adj_factor)
  klines_daily: open/high/low/close = 不复权(历史事实，永远不变)
  klines_daily: adj_factor = 当日复权因子(每日更新)
  
计算时按需复权:
  close_adj = close × adj_factor
  return = close_adj[t] / close_adj[t-1] - 1  (自动包含分红收益)

为什么不存前复权:
  V1事故教训: Tushare前复权价格随时间变化(每次分红后历史全部重算)
  导致: 同一天同一只股票不同时间查出不同价格 → 回测非确定性
  
数据更新(每日T1):
  1. 拉取当日不复权OHLCV
  2. 拉取全市场最新adj_factor
  3. 写入klines_daily

data_source_checklist:
  - [ ] adj_factor在除权日跳变，验证跳变幅度=分红/拆股比例
  - [ ] adj_factor必须Point-in-Time(不能用今天的复权因子复权去年的价格)
  - [ ] 每日检查adj_factor变化股票数量合理(正常0-50只，年报季100+)

回测使用:
  因子计算: 全部用复权价格(close_adj)
  信号生成: 用复权价格排序
  执行价格: 用不复权价格(实际成交)
  收益计算: 用复权价格(包含分红)
```

## 9.5 指数基准数据（V5.1补充）

```
用途: 超额收益/信息比率/Beta计算 + 市场状态判断 + 总览页展示

指数清单:
  000300.SH — 沪深300 (默认基准, 可配置)
  000905.SH — 中证500
  000852.SH — 中证1000 (可选)
  399006.SZ — 创业板指 (可选)

存储: index_daily表
  index_code VARCHAR(10), trade_date DATE,
  open/high/low/close FLOAT, volume BIGINT, amount FLOAT

数据源: tushare index_daily() 或 akshare stock_zh_index_daily()
更新: 每日T1任务附带拉取(数据量极小: 4指数×5000天=20,000行)

使用:
  market_state = 'bull' if close > MA(120) else 'bear'
  benchmark_nav = close / close[0]
  excess_return = strategy_return - benchmark_return
  information_ratio = mean(excess) / std(excess) × √252
```

## 9.6 交易日历（V5.1补充）

```
存储: trading_calendar表
  trade_date DATE, market VARCHAR(10), is_trading_day BOOLEAN, is_half_day BOOLEAN

数据源:
  A股: akshare tool_trade_date_hist_sina() 或 tushare trade_cal()
  外汇: 周一至周五(除圣诞12/25和元旦1/1)

初始化: scripts/init_trading_calendar.py 导入2000-2026
每年12月更新下一年节假日

使用:
  调度(DEV_SCHEDULER.md): should_run_task()查表判断
  回测: 只在交易日推进bar
  数据拉取: 非交易日跳过
```

---

# 第十章：数据库完整Schema

## 28张基础表 + 12张新增表 = 41张表，11个功能域

> V5新增：域9回测(6张)、域10因子挖掘管理(3张)、域11 AI闭环(3张)。详见DEV_回测引擎、DEV_AI闭环文档。

### 域1：基础数据（5张表）

- **symbols** — 股票/货币对基础信息(code, name, market, board, industry_sw1, list_date, price_limit, lot_size)
- **klines_daily** — A股日线行情(OHLCV, turnover_rate, adj_factor, is_suspended, is_st) [TimescaleDB hypertable]
- **forex_bars** — 外汇K线多时间框架(D1/H4/H1/M15, OHLC, tick_volume, spread) [TimescaleDB hypertable]
- **daily_basic** — A股每日指标(PE/PB/PS, total_mv, circ_mv, div_yield)
- **trading_calendar** — 交易日历(date, market, is_trading_day, is_half_day)

### 域2：另类数据（5张表）

- **moneyflow_daily** — 资金流向(大单/中单买卖额)
- **northbound_holdings** — 北向资金持仓(hold_vol, hold_ratio)
- **margin_data** — 融资融券(margin_balance, short_balance)
- **chip_distribution** — 筹码分布(winner_rate, cost_5/15/50/85/95pct)
- **financial_indicators** — 财务指标PIT版(report_date+actual_ann_date双时间戳, ROE/ROA/毛利率等)

### 域3：因子（3张表）

- **factor_registry** — 因子注册表(name, category, direction, expression, hypothesis, neutralization, status, gate_ic/ir/mono/t)
- **factor_values** — 因子值PIT版(raw_value, neutral_value, zscore三列) [TimescaleDB hypertable]
- **factor_ic_history** — 因子IC监控(ic, ic_ma20, ic_ma60, decay_level)

### 域4：Universe与信号（3张表）

- **universe_daily** — 每日可交易池(in_universe, exclude_reason)
- **signals** — 策略信号(alpha_score, rank, target_weight, action)
- **index_daily** — 指数基准(CSI300/CSI500)

### 域5：交易执行（3张表）— 统一输出契约

- **trade_log** — 每笔交易(direction, quantity, target/fill_price, slippage, commission, stamp_tax, swap_cost, execution_mode)
- **position_snapshot** — 每日持仓快照(quantity, avg_cost, market_value, weight, unrealized_pnl, holding_days)
- **performance_series** — 每日绩效(nav, daily_return, cumulative_return, drawdown, cash_ratio, position_count, turnover)

### 域6：AI模型管理（3张表）

- **model_registry** — 模型注册(model_type, purpose, file_path, oos_sharpe, parameters, status)
- **ai_parameters** — 14个AI旋钮的当前值(param_value, param_min, param_max, param_default, updated_by, authorization_level)
- **experiments** — 实验记录(experiment_type, parameters JSONB, results JSONB)

### 域7：系统运维（4张表）

- **data_versions** — 数据版本(version_tag, tables_affected)
- **notification_log** — 告警日志(level P0/P1/P2, category, title, message)
- **health_checks** — 健康检查(pg/disk/memory/data_freshness/mt5/cron状态)
- **strategy_configs** — 策略配置DB备份(strategy_id, version, config JSONB, changelog)

### 域8：外汇专用（2张表）

- **forex_swap_rates** — Swap费率历史(swap_long, swap_short)
- **forex_events** — 经济日历(datetime, currency, event_name, importance, actual/forecast/previous)

### 域9：回测引擎（6张表）— V5新增

- **strategy** — 策略定义(mode:visual/code, factor_config JSONB, code_content, status:draft/backtested/deployed)
- **backtest_run** — 回测运行记录(strategy_id, config_json, factor_list, status, 汇总指标冗余)
- **backtest_daily_nav** — 每日净值(nav, cash, market_value, daily_return, benchmark_nav, excess_return)
- **backtest_trades** — 交易明细(signal_date, exec_date, side, exec_price, slippage_bps, cost_detail, reject_reason)
- **backtest_holdings** — 每日持仓快照(shares, cost_basis, market_price, weight, buy_date, industry_code)
- **backtest_wf_windows** — Walk-Forward窗口记录(train/valid/test日期, oos_sharpe, selected_factors)

### 域10：因子挖掘管理（3张表）— V5新增

- **factor_registry_v2** — 因子注册表升级版(expression, code_content, source:builtin/gp/llm/brute/manual, status:new/active/degraded/archived, 冗余IC指标)
- **factor_evaluation** — 因子评估历史(完整IC/IR/分组/衰减/相关性/分年度/分市场状态指标, JSONB存储)
- **factor_mining_task** — 因子挖掘任务(method, config_json, total_candidates, passed_filter, entered_library)

### 域11：AI闭环（3张表）— V5新增

- **pipeline_run** — AI闭环运行记录(round_number, trigger_type, automation_level, current_state, 各阶段结果摘要)
- **agent_decision_log** — Agent决策日志(agent_name, decision_type, reasoning, action_taken, input/output JSONB, 可审计)
- **approval_queue** — 审批队列(approval_type:factor_entry/strategy_deploy, item_summary, status:pending/approved/rejected)

---

# 第十一章：回测层

> V5更新：回测引擎已完成完整设计，详见 DEV_回测引擎详细开发文档.md（34项决策、6张新表、5个前端页面）。

## 11.1 架构模式：Hybrid（向量化信号 + 事件驱动执行）

- **Phase A 向量化层**：因子计算→预处理(MAD→zscore→中性化)→合成→排序→目标持仓，全numpy/pandas批量运算
- **Phase B 事件驱动层**：逐日循环处理T+1、涨跌停拒单、停牌冻结、成交量约束、Volume-impact双因素滑点

## 11.2 关键设计决策（17项已确认）

| 决策 | 选择 |
|------|------|
| 成交价 | 次日开盘(默认) + VWAP(可选) |
| 滑点 | Volume-impact双因素(市值分层+换手率调整) + 固定fallback |
| 交易成本 | 佣金万1.5 + 印花税0.05% + 过户费0.001% |
| 涨跌停判断 | 数据源标记优先→涨跌停价比对→涨幅近似(三级fallback) |
| 涨跌停幅度 | 按板块自动判定(主板10%/创业板科创板20%/ST 5%) |
| 调仓日历 | 可配置，默认周五信号+下周一执行 |
| 超额收益 | 对数收益相减 ln(1+r_s) - ln(1+r_b) |
| 未成交处理 | 现金持有(默认) + 按比例分配/替补可配置 |
| Walk-Forward | 36+6+3+3(可配置)，滚动窗口OOS拼接 |
| 做空 | Step 1-3不支持，Phase 2外汇再加 |

## 11.3 三步渐进实现

- **Step 1(3-5天)**: 信号层+简化回测 → 回答"34个因子哪些有信号"
- **Step 2(5-7天)**: 完整执行模拟器(T+1/涨跌停/停牌/成交量/精确成本)
- **Step 3(5-7天)**: Walk-Forward框架 → 验证真实Sharpe

## 11.4 前端页面(5个)

①策略工作台(因子面板+双模式编辑+AI助手) → ②回测配置面板(市场/股票池/时间段/执行/成本/风控) → ③运行监控(WS实时进度) → ④结果分析(7个Tab含参数敏感性和实盘对比) → ⑤策略库(管理/对比/复用)

## 11.5 股票池(8种预设)

全A股 / 沪深300 / 中证500 / 中证1000 / 创业板 / 科创板 / 按行业 / 自定义。市场状态分析(均线法MA120)自动判定牛/熊/震荡。

---

# 第十二章：执行层

## 12.1 A股执行

```
Phase 0: 回测模式（引擎内部模拟）
Phase 1: Paper Trading（每日钉钉推送目标持仓，手动执行/观察）
Phase 1+: miniQMT半自动（国金证券，开户后搭建）
未来: miniQMT全自动
```

## 12.2 Paper Trading验证逻辑

```
A股成交假设: T日信号→T+1开盘价成交

偏差指标（三项取最差）：
  ① corr(paper_daily_return, backtest_daily_return) > 0.8
  ② |paper_cumret - backtest_cumret| / backtest_cumret < 20%
  ③ max(|paper_ret - backtest_ret|) < 3%

连续5天任一不达标→P1告警
三项同时不达标→暂停策略
```

## 12.3 外汇执行

MT5 Python API → ECMarkets标准账户(1:100杠杆)
每个order_send前经过风控检查

---

# 第十三章：验证层

```
验证管道（一键运行）：
  数据校验→因子Gate(IC/单调性/换手/相关性)→确定性(3次)
  →Walk-Forward→DSR→PBO→baseline对比→报告

CI门禁: 确定性不通过=构建失败
回归门禁: Sharpe下降>10%=构建失败+告警
```

---

# 第十四章：归因分析

```
因子归因: 每因子对收益的贡献（Brinson分解）
行业归因: 超额来自行业选择还是个股选择（申万一级）
时间归因: 分月/分市场状态表现
成本归因: 扣成本前后差异、换手成本占比
```

---

# 第十五章：前端层（11个页面已设计）

> V5更新：前端从[待讨论]变为已设计。详见 DEV_回测引擎(5页面)、DEV_AI闭环(6页面) 文档。

## 15.1 前端技术：React（已确认从Streamlit切换）

## 15.2 页面总览（11个页面，3个模块）

### 回测模块（5个页面）
1. **策略工作台** — 左栏因子面板(34因子) + 中央双模式编辑(可视化/代码) + 右栏AI助手
2. **回测配置面板** — 5个Tab(市场股票池/时间段/执行参数/成本模型/风控高级)
3. **回测运行监控** — WebSocket实时进度+净值曲线+WF窗口指标
4. **回测结果分析** — 7个Tab(净值/月度归因/持仓/交易/WF/参数敏感性/实盘对比)
5. **策略库** — 列表管理+双栏对比+历史记录

### 因子挖掘模块（4个页面）
6. **因子实验室** — 5种创建方式(手动/表达式/GP/LLM/暴力枚举) + AI助手
7. **挖掘任务中心** — 运行监控+进度推送+任务统计
8. **因子评估报告** — 6个Tab(IC/分组/衰减/相关性/分年度/分市场状态) + 批量评估
9. **因子库** — 生命周期管理(new→active→degraded→archived) + 健康度面板

### AI闭环模块（2个页面）
10. **Pipeline控制台** — 4级自动化+状态流程图+审批队列+决策日志
11. **Agent配置** — 4个Agent的阈值/LLM/GP参数配置

## 15.3 后端API总数：~40个端点（REST + WebSocket）

---

# 第十六章：外汇详细设计 [待讨论]

Phase 2设计，等A股回测引擎完成后讨论。

---

# 第十七章：AI进化闭环完整设计（4 Agent + Pipeline）

> V5更新：AI闭环已完成完整设计，详见 DEV_AI闭环详细开发文档.md（6项决策、6张新表、2个前端页面）。

## 17.1 三层架构

- **Agent层**: 4个Agent(因子发现/策略构建/诊断优化/风控监督)，各有独立系统Prompt和决策规则
- **编排层**: Pipeline Orchestrator状态机，管理Agent执行顺序和审批等待
- **执行层**: 回测引擎、因子计算、评估器等已有模块

## 17.2 四级自动化

- L0全手动 → L1半自动(默认) → L2大部分自动 → L3全自动
- 实盘部署始终需人批

## 17.3 完整闭环流程

因子发现→评估→入库审批→策略构建→回测→诊断→风控→部署审批
诊断不达标→循环(Alpha不足→重新发现 / 参数问题→重新构建，最多3轮)

## 17.4 Agent决策可审计

全部决策写入agent_decision_log表，含推理过程、输入上下文、输出结果。

---

# 第十八章至第二十二章 [待讨论]

以下章节需要在后续讨论中确认：

- **第十八章 每日调度与运维** — 时序、cron配置、健康检查
- **第十九章 通知告警系统** — P0/P1/P2分级、钉钉对接
- **第二十章 配置管理体系** — 策略/风控/全局配置的层次关系
- **第二十一章 miniQMT对接方案** — API接口、下单流程、异常处理
- **第二十二章 高级特性整合** — GP/GNN/Kronos/RD-Agent联合优化

---

# 第二十三章：MVP定义与实施路线图

## 23.1 MVP定义（V5.1更新）

```
MVP = 完整规则版管道（所有AI参数用默认值）

包含：
  ✓ PostgreSQL+TimescaleDB + 51张表
  ✓ AKShare/Tushare全量数据（经Data Contract验证 + 复权因子adj_factor）
  ✓ 指数基准数据（沪深300/中证500，index_daily表）
  ✓ 交易日历（trading_calendar表，A股+外汇）
  ✓ 分红除权处理（不复权价格+adj_factor存储，计算时按需复权）
  ✓ 34个因子（Python实现，复权价格计算）
  ✓ 因子Gate Pipeline（8项检验+FDR多重检验校正）
  ✓ Rust回测引擎（Hybrid: 向量化信号+事件驱动执行）
  ✓ 规则版组合构建（等权Top-30周频）
  ✓ Paper Trading + 钉钉通知
  ✓ FastAPI后端 + React前端（12个页面）
  ✓ Celery调度（15任务链）
  ✓ 通知系统（4级分级+25模板）
  ✓ 确定性测试通过

不含：
  ✗ AI动态参数（全用默认值）
  ✗ 外汇（Phase 2，设计已完成）
  ✗ miniQMT自动执行（Phase 1）
  ✗ 高级AI模型（LightGBM/Optuna/GRU等，Phase 1+）
```

## 23.2 Phase规划（V5.1更新）

```
Phase 0: 从零搭建MVP（质量优先，不设时间限制）
  基础设施: PostgreSQL+Redis+FastAPI+Celery+React
  数据层: AKShare/Tushare全量+复权因子+指数基准+交易日历
  研究层: 34因子(复权价格)+Factor Gate
  回测层: Rust Hybrid引擎+Walk-Forward
  策略层: 等权Top-30+规则版风控
  执行层: Paper Trading(手动确认)
  前端: 12页面+Glassmorphism
  通知: 钉钉Webhook+站内通知
  测试: 确定性CI+关键路径单元测试

Phase 1: A股完整+AI第一批
  因子: 18→34因子全量上线
  ML: LightGBM+Optuna因子合成+参数搜索
  AI: 因子挖掘管道(LLM+GP+暴力枚举)
  验证: WF/CPCV/DSR/PBO完整体系
  交易: miniQMT对接+自动执行
  14个AI参数逐个验证替换规则版

Phase 2: 外汇（设计已全部完成，10个模块）
  数据: HistData导入+MT5增量
  引擎: Python事件驱动回测
  策略: 策略A日频趋势+3层21因子
  ML: LightGBM信号过滤+Optuna
  风控: 4层14项
  执行: MT5 Adapter+Paper Trading 3个月
  跨市场: 资金分配A70%/外30%

Phase 3: 整合优化
  AI闭环Pipeline完整上线(4Agent+4级自动化)
  外汇策略B(小时频短线)
  多模型集成(MLP/XGBoost/GRU)
  跨市场AI动态分配
  多模型投票(LLM)

Phase 4+: Mac Studio迁移
  本地MLX大模型推理
  Transformer微调/GNN货币关联
  高级特性
```

## 23.3 重写风险与应对

| 风险 | 应对 |
|------|------|
| Python回测性能不够 | Rust Hybrid引擎(信号向量化+执行事件驱动) |
| 因子Gate筛掉太多 | 降低阈值或扩大搜索空间 |
| AI模块不如规则版 | 保持规则版，记录失败原因 |
| miniQMT搭建困难 | 先Paper Trading，手动执行 |
| 复权数据不一致 | 存不复权+adj_factor，每日验证 |
| LLM因子质量差 | 暴力枚举兜底，LLM只是补充 |

---

# 第二十四章：项目文件结构

> V5.1更新：以DEV_BACKEND.md §一为准。以下为摘要。

```
quantmind-v2/
├── backend/                    # Python后端(FastAPI+Celery)
│   ├── main.py                 # FastAPI入口
│   ├── config.py               # .env配置加载
│   ├── database.py             # SQLAlchemy async连接池
│   ├── routers/                # API路由(10个文件,~57端点)
│   ├── services/               # 业务逻辑(17个Service)
│   ├── repositories/           # 数据访问(9个Repo)
│   ├── schemas/                # Pydantic数据模型
│   ├── models/                 # SQLAlchemy ORM(51张表)
│   ├── tasks/                  # Celery异步任务(28个定时)
│   ├── engines/                # 核心计算(因子/信号/回测/GP/ML)
│   ├── integrations/           # 外部API(AKShare/Tushare/MT5/LLM/钉钉)
│   ├── websocket/              # WebSocket管理(5通道)
│   └── utils/                  # 工具(日期/数学/验证/日志)
├── rust_engine/                # Rust回测引擎(A股)
├── frontend/                   # React 18前端(12页面)
├── mt5_adapter/                # MT5网关(Windows,Phase 2)
├── scripts/                    # 运维脚本
├── tests/                      # 测试
├── alembic/                    # 数据库迁移
└── .env / CLAUDE.md / pyproject.toml
```

详细目录结构见 DEV_BACKEND.md §一。

---

# 第二十五章：成本预算与容量规划

| 阶段 | API | VPS | 合计 |
|------|-----|-----|------|
| Phase 0-1 | ¥30-100 | ¥0 | ¥30-100 |
| Phase 2 | ¥50-200 | ¥0(PD)/50-80(VPS) | ¥50-280 |
| Mac Studio后 | ¥0-50 | ¥0-80 | ¥0-130 |

月预算上限¥500。

---

# 第二十六章：心理纪律框架

```
铁律1: 不在回撤期改参数（检查风控→未触发→继续执行）
铁律2: 变更必须经验证管道（不允许"先上线试试"）
铁律3: 每月第一个周末复盘（自动报告+人工分析）
铁律4: 最大可接受亏损（月>10%降仓/累计>25%停止）
铁律5: 不追求完美（Sharpe 1.0-2.0合理，单月可能亏损）
```

---

# 第二十七章：协作流程与知识管理

- **CLAUDE.md**: ≤500行，只写当前状态+最近变更+编码约定
- **任务卡**: 目标+输入条件+输出条件+验证标准+失败处理
- **Git**: 每任务一个feature branch→验证→merge main

---

# 附录A：V1教训清单

## A.1 数据层教训
- □ Tushare daily返回不复权价格（必须配合adj_factor）
- □ vol单位手(×100)，amount千元(×1000)，moneyflow万元(×10000)
- □ pre_close 99.97%空，不可依赖
- □ 退市股票要单独拉取
- □ abs(daily_return)>20%且非新股 → 异常过滤

## A.2 回测引擎教训
- □ 所有排序必须有确定性tie-break
- □ 复权: close × adj_factor / latest_adj_factor
- □ 买入按alpha降序，卖出按alpha升序
- □ f64排序处理NaN
- □ 涨跌停用不复权价判断

## A.3 因子层教训
- □ Spearman IC不受遍历顺序影响
- □ 暴力枚举 > LLM直接生成
- □ turnover因子与现有高度相关，增量有限

## A.4 工程教训
- □ 确定性测试是CI门禁
- □ 接入数据源前看完文档
- □ 不要同时运行太多服务

---

# 附录B：完整决策记录

| # | 决策 | 结论 | 日期 |
|---|------|------|------|
| 1 | 策略定位 | A股+外汇绝对收益 | 2026-03-19 |
| 2 | 开发vs迁移 | 完全重新开发 | 2026-03-19 |
| 3 | A股策略哲学 | 人工框架+AI挖掘优化 | 2026-03-19 |
| 4 | 外汇策略哲学 | 多层融合(宏观+技术+AI) | 2026-03-19 |
| 5 | 外汇频率 | 日频+小时频混合 | 2026-03-19 |
| 6 | 外汇品种 | 主要+商品+避险货币 | 2026-03-19 |
| 7 | 两市场关系 | AI动态调整资金分配 | 2026-03-19 |
| 8 | 核心因子 | 全四类(价量+流动性+资金流+基本面) | 2026-03-19 |
| 9 | 扩展因子 | 全四类(成长+分析师+事件+情绪) | 2026-03-19 |
| 10 | Universe | 全A含北交所 | 2026-03-19 |
| 11 | 持仓数 | AI动态[10-50] | 2026-03-19 |
| 12 | 权重方案 | AI动态切换 | 2026-03-19 |
| 13 | A股执行 | miniQMT国金证券 | 2026-03-19 |
| 14 | 调仓频率 | 混合(基础周期+事件+AI) | 2026-03-19 |
| 15 | 仓位管理 | 规则底线+AI优化 | 2026-03-19 |
| 16 | AI自主权 | 分层授权L1/L2/L3 | 2026-03-19 |
| 17 | AI启动策略 | 模块化替换 | 2026-03-19 |
| 18 | AI安全网 | 层级fallback | 2026-03-19 |
| 19 | A股风控 | 分层(硬+软+熔断) | 2026-03-19 |
| 20 | 止损底线 | 月>10%降仓/累计>25%停 | 2026-03-19 |
| 21 | 外汇风控 | 5项全选 | 2026-03-19 |
| 22 | 回测引擎 | Python→局部Rust | 2026-03-19 |
| 23 | 前端 | Streamlit→React | 2026-03-19 |
| 24 | 外汇broker | ECMarkets标准1:100 | 2026-03-19 |
| 25 | MVP | 完整规则版管道 | 2026-03-19 |
| 26 | Phase 0时间 | 质量优先不设限 | 2026-03-19 |
| 27 | 开发方式 | 全职投入 | 2026-03-19 |
| 28 | 因子中性化 | AI决定每个因子 | 2026-03-19 |
| 29 | 市值因子 | 纳入（ln_float_cap） | 2026-03-19 |
| 30 | 新股天数 | 60天 | 2026-03-19 |
| 31 | 市值门槛 | AI动态[5亿-50亿] | 2026-03-19 |
| 32 | 成交额门槛 | AI动态[200万-2000万] | 2026-03-19 |
| 33 | 停牌门槛 | AI动态[3-30天] | 2026-03-19 |
| 34 | 单股权重 | AI动态[3%-15%] | 2026-03-19 |
| 35 | 行业权重 | AI动态[10%-35%] | 2026-03-19 |
| 36 | 换手率控制 | AI动态[10%-80%] | 2026-03-19 |
| 37 | 因子挖掘模型 | 渐进式(R1+V3先行，效果不好加其他) | 2026-03-19 |
| 38 | Agent架构 | 混合(三Agent+GP共享评估层+知识库) | 2026-03-19 |
| 39 | 挖掘知识库 | PostgreSQL结构化(mining_knowledge表) | 2026-03-19 |
| 40 | 挖掘运行频率 | 每天自动一轮 | 2026-03-19 |
| 41 | 假设数量 | AI动态(前端可切手动/AI) | 2026-03-19 |
| 42 | 代码重试 | 最多3次+报错反馈(前端可调[0-5]) | 2026-03-19 |
| 43 | LLM调用参数 | 全部前端可调(temperature/max_tokens/top_p) | 2026-03-19 |
| 44 | Few-shot策略 | 混合(System固定案例+User动态知识库) | 2026-03-19 |
| 45 | 输出格式校验 | 三层防护(正则提取→重试→跳过) | 2026-03-19 |
| 46 | 参数可配置哲学 | 最大化可配置，几乎所有参数前端可调 | 2026-03-19 |
| 47 | 回测架构模式 | Hybrid(向量化信号+事件驱动执行) | 2026-03-19 |
| 48 | 回测成交价 | 次日开盘(默认)+VWAP(可选)，可配置 | 2026-03-19 |
| 49 | 回测滑点模型 | Volume-impact双因素(市值+换手率)+固定fallback | 2026-03-19 |
| 50 | 回测交易成本 | 佣金万1.5+印花税0.05%+过户费0.001% | 2026-03-19 |
| 51 | 回测实现节奏 | 三步渐进(信号验证→执行模拟→WF) | 2026-03-19 |
| 52 | WF窗口参数 | 36+6+3+3(可配置) | 2026-03-19 |
| 53 | 回测结果存储 | PostgreSQL 6张新表 | 2026-03-19 |
| 54 | Forward return | 同时计算1/5/10/20日 | 2026-03-19 |
| 55 | 因子预处理流程 | MAD去极值→zscore→市值+行业中性化 | 2026-03-19 |
| 56 | 未成交资金处理 | 现金持有(默认)+按比例/替补可配置 | 2026-03-19 |
| 57 | 停牌复牌处理 | 复牌首日按开盘价立即卖出(如不在目标池) | 2026-03-19 |
| 58 | 涨跌停判断 | 数据源标记→涨跌停价→涨幅近似(三级fallback) | 2026-03-19 |
| 59 | 基准指数 | 沪深300默认，可配置500/1000 | 2026-03-19 |
| 60 | 超额收益计算 | 对数收益相减 | 2026-03-19 |
| 61 | 调仓日历 | 可配置，默认周五信号+下周一执行 | 2026-03-19 |
| 62 | 做空支持 | Step 1-3不支持，Phase 2外汇再加 | 2026-03-19 |
| 63 | 滑点k系数 | 按市值分层(0.05/0.10/0.15)+换手率调整 | 2026-03-19 |
| 64 | 股票池预设 | 8种(全A/300/500/1000/创业板/科创板/行业/自定义) | 2026-03-19 |
| 65 | 涨跌停幅度 | 按板块自动判定(主板10%/创业板科创板20%/ST 5%) | 2026-03-19 |
| 66 | 市场状态分析 | 默认启用，均线法(MA120)判定牛/熊/震荡 | 2026-03-19 |
| 67 | 回测时间段 | 快捷选择+排除特殊时期+自定义 | 2026-03-19 |
| 68 | 多市场预留 | market字段预留，Phase 2外汇激活 | 2026-03-19 |
| 69 | 结果页补充 | 参数敏感性Tab+实盘对比Tab | 2026-03-19 |
| 70 | 策略编辑模式 | 可视化与代码并重，可自由切换 | 2026-03-19 |
| 71 | AI助手功能 | 全功能(生成+优化+解释+诊断) | 2026-03-19 |
| 72 | 因子创建方式 | 5种(手动/表达式/GP/LLM/暴力枚举) | 2026-03-19 |
| 73 | 因子工具函数库 | ts_*/cs_*系列预置函数 | 2026-03-19 |
| 74 | 因子生命周期 | new→active→degraded→archived+定期体检 | 2026-03-19 |
| 75 | AI闭环架构 | 三层(Agent→编排→执行) | 2026-03-19 |
| 76 | Agent数量 | 4个(发现/构建/诊断/风控) | 2026-03-19 |
| 77 | 自动化级别 | 4级(L0全手动~L3全自动)，默认L1半自动 | 2026-03-19 |
| 78 | Agent决策可审计 | 全部写入agent_decision_log表 | 2026-03-19 |
| 79 | 审批机制 | approval_queue表，L1需人批入库+部署 | 2026-03-19 |
| 80 | 闭环调度频率 | 发现周频/优化月频/体检双周/诊断周报 | 2026-03-19 |

---

# 附录C：学术与开源参考资料

## 论文
- López de Prado《Advances in Financial Machine Learning》— Triple-Barrier, Purged CV, DSR, HRP
- Arnott, Harvey & Markowitz (2019) — 七条协议
- AlphaAgent (KDD 2025) — 三Agent闭环因子挖掘，CSI500 IC=0.0212，hit ratio提升81%
- RD-Agent-Quant (arxiv:2505.15155) — 因子+模型联合优化
- QuantaAlpha (2026) — LLM+进化策略，自进化轨迹因子挖掘
- Alpha-GPT (EMNLP 2025) — 人机交互因子挖掘，层级RAG
- AlphaQuanter — 单Agent RL编排
- FinKario — 金融知识图谱
- EFS — LLM因子搜索+稀疏组合
- Kronos — K线预训练基础模型，120亿K线预训练
- 清华五道口《中国A股量化因子白皮书》— 56因子实证，13个有效因子

## GitHub仓库
- microsoft/qlib — Alpha158因子体系+PIT数据
- microsoft/RD-Agent — 自动化因子-模型联合优化
- QuantaAlpha/QuantaAlpha — LLM+进化因子挖掘平台
- shiyu-coder/Kronos — K线预训练模型
- QuantConnect/Lean — 五组件Algorithm Framework
- vnpy/vnpy — 事件驱动引擎+CTP Gateway
- PandaAI-Tech/panda_factor — 因子研究平台
- hugo2046/QuantsPlaybook — 策略模板库

---

# 附录D：待讨论议题清单

已完成的议题 ✅：
```
✅ 战略决策（25项 → 扩展到46项 → 80项含回测/AI闭环）
✅ A股因子体系（34因子+预处理+衰减+择时+交互因子）
✅ Universe构建（8层过滤+AI动态门槛+三种涨跌停）
✅ 组合构建（7步完整链路+14个AI参数）
✅ 数据库Schema（28张基础表+12张新表=41张）
✅ 风控分层体系
✅ AI参数+授权+fallback框架
✅ 因子挖掘完整设计（四引擎+三Agent+GP+Prompt+知识库+调度器）
✅ 参数可配置性体系（四级控制+统一组件+170+个前端可调参数）
✅ 回测引擎完整设计（Hybrid架构+34项决策+6张表+5个前端页面）
✅ 前端UI设计（11个页面: 回测5+因子挖掘4+AI闭环2）
✅ AI进化闭环完整设计（4 Agent+Pipeline状态机+4级自动化+6项决策）
✅ 因子挖掘前端（因子实验室+任务中心+评估报告+因子库）
✅ 策略编辑（可视化+代码双模式+AI全功能助手）
✅ 因子生命周期管理（new→active→degraded→archived+定期体检）
```

待讨论的议题（按优先级）— V5.1更新状态：
```
P0（影响Phase 0开发）：
  ✅ 每日调度时序（cron配置+任务依赖）→ DEV_SCHEDULER.md
  ✅ 通知告警系统（钉钉对接+4级分类）→ DEV_NOTIFICATIONS.md

P1（影响Phase 1）：
  ✅ 外汇具体品种清单和每个品种特性 → DEV_FOREX.md §二
  ✅ 外汇策略模板（趋势跟踪完整规则）→ DEV_FOREX.md §五
  □ miniQMT对接方案（API接口+下单流程+异常处理）→ Phase 1再讨论
  ✅ 交易日历管理 → DEV_SCHEDULER.md §六 + 本文档补充
  ✅ 指数基准数据 → 本文档补充(index_daily表+CSI300/500)

P2（可边开发边完善）：
  □ 高级特性（GNN/Transformer微调/RD-Agent）→ Phase 3/4
  □ 模型注册与版本管理详细设计 → Phase 1
  ✅ 分红除权处理 → 本文档补充(不复权+adj_factor方案)
  ✅ 外汇保证金计算+仓位管理 → DEV_FOREX.md §七
  ✅ 配置管理统一方案 → DEV_BACKEND.md §六 + DEV_PARAM_CONFIG.md
```

---

*本文档版本5.1。A股部分含80项已确认决策，41张数据库表。外汇部分(13项决策，7张新表)详见QUANTMIND_V2_FOREX_DESIGN.md。调度1张+通知2张新表。全系统合计：93项决策，51张表(+Phase 3预留2张=53张)。系统架构§3已更新为FastAPI/Celery/React。§23 MVP定义/§24项目结构已更新。后端服务层设计详见DEV_BACKEND.md。分红除权/指数基准/交易日历已补充设计。*
*V5新增：回测引擎+AI闭环+前端12页面+因子挖掘+外汇10模块+调度+通知+后端服务层。*
*P0设计全部完成。P1待讨论：miniQMT对接。*
*所有开发工作以本文档为准。*

---

# 附录E：开发文档索引

总设计文档 = 摘要级（做什么+为什么）。开发文档 = 实现级（怎么做+完整代码/Prompt/SQL）。

```
文档架构：

QUANTMIND_V2_DESIGN_V5.md              ← 本文档（A股决策+架构+接口，80项决策，41张表）
│
├── QUANTMIND_V2_FOREX_DESIGN.md        ← 外汇总设计文档 ✅ 已完成
│     外汇决策13项(#81-93) + 架构概述 + 7张新表
│     品种/因子/策略/回测/风控/成本/MT5/ML/LLM
│     详细开发: DEV_FOREX.md(16章676行)
│
├── DEV_FACTOR_MINING.md                ← 因子挖掘详细开发文档 ✅ 已完成(V2)
│     完整Prompt文本(Idea/Factor/Feedback)
│     6个搜索方向Hint
│     GP配置+适应度函数
│     知识库SQL + 调度器代码
│     一轮完整流程 + 输出格式校验
│     因子生命周期 + 工具函数库
│
├── DEV_PARAM_CONFIG.md                 ← 参数可配置性详细开发文档 ✅ 已完成(V2)
│     220+参数完整清单(11模块)
│     统一交互组件规格 + 安全机制
│     ai_parameters表初始化SQL
│     回测引擎参数模块 + Agent配置参数模块
│
├── DEV_BACKTEST_ENGINE.md              ← 回测引擎详细开发文档 ✅ 已完成
│     Hybrid架构 + 34项决策
│     核心类接口(15个类) + DDL(6张表)
│     双因素滑点 + 精确成本模型
│     三步渐进实现 + Walk-Forward框架
│
├── DEV_AI_EVOLUTION.md                 ← AI闭环详细开发文档 ✅ 已完成
│     三层架构(Agent→编排→执行)
│     4个Agent决策逻辑 + Pipeline状态机
│     4级自动化 + 审批规则
│     DDL(6张表) + 工具函数库 + 调度配置
│
├── DEV_FRONTEND_UI.md                  ← 前端UI详细开发文档 ✅ 已完成
│     Glassmorphism毛玻璃金融风
│     12个页面完整布局/交互/组件规格
│     涨跌色可配置 + ECharts/Recharts分工
│     全局交互规范(错误处理/导出导入/冷却期/FDR/移动端)
│     后端API汇总(~48端点)
│
├── DEV_FOREX.md                        ← 外汇详细开发文档 ✅ 已完成
│     14品种+3Tier+相关性+时段+Swap
│     3层21因子(宏观6+技术15)+信号合成
│     策略A日频趋势7步+3层可配置+5模板
│     Python事件驱动回测引擎+SimBroker
│     4层14项风控+成本模型(动态点差+Swap)
│     MT5 Adapter架构+执行引擎+持仓同步
│     因子挖掘适配(Prompt/评估/Gate/GP/枚举)
│     ML: LightGBM+Optuna+RF / LLM: 可配置多模型
│     7张新表+Paper Trading+实盘切换清单
│
├── DEV_BACKEND.md                      ← 后端服务层详细开发文档 ✅ 已完成
│     项目目录结构 + FastAPI应用 + 服务层分层
│     端到端数据流(A股+外汇+回测+AI闭环)
│     模块协同矩阵 + 通知调用点 + 市场路由
│     配置管理 + 测试策略 + 日志 + WebSocket管理
│
├── DEV_SCHEDULER.md                    ← 调度与运维详细开发文档 ✅ 已完成
│     A股15任务链(06:00→16:30)+外汇11任务链(22:05→23:10UTC)
│     Celery Beat配置+8队列+依赖管理+交易日历+重试+监控
│
├── DEV_MINIQMT.md                      ← miniQMT对接详细开发文档 [待讨论,P1]
│
└── DEV_NOTIFICATIONS.md                ← 通知告警详细开发文档 ✅ 已完成
      NotificationService统一入口+钉钉Webhook
      25+预定义模板+防洪泛+4级分级+偏好+2张新表

文件名对照（索引名 = 实际文件名）：
  QUANTMIND_V2_DESIGN_V5.md         = A股总设计文档
  QUANTMIND_V2_FOREX_DESIGN.md      = 外汇总设计文档
  DEV_FACTOR_MINING.md              = 因子挖掘
  DEV_PARAM_CONFIG.md               = 参数可配置性
  DEV_BACKTEST_ENGINE.md            = 回测引擎
  DEV_AI_EVOLUTION.md               = AI闭环
  DEV_FRONTEND_UI.md                = 前端UI
  DEV_FOREX.md                      = 外汇详细开发
  DEV_BACKEND.md                     = 后端服务层
  DEV_SCHEDULER.md                  = 调度与运维
  DEV_NOTIFICATIONS.md              = 通知告警
```

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. 存活偏差处理（补充 symbols 表和 Universe 设计）

symbols表必须包含已退市股票:
- 拉取时用 `stock_basic(list_status='D')` 获取全量退市股
- symbols表的`list_status`字段: L=上市, D=退市, P=暂停
- 回测Universe构建时，历史日期的退市前股票应该在Universe中
- 退市处理: 退市前5个交易日强制平仓，按最后可交易价格结算
- 不处理存活偏差会让回测收益虚高2-5%/年

### P2. 新增 index_components 表

```sql
CREATE TABLE index_components (
    index_code  VARCHAR(10) NOT NULL,   -- 如 '000300.SH'
    code        VARCHAR(10) NOT NULL,   -- 成分股代码
    trade_date  DATE NOT NULL,          -- 生效日期
    weight      DECIMAL(8,6),           -- 权重(如 0.035 = 3.5%)
    PRIMARY KEY (index_code, code, trade_date)
);
COMMENT ON TABLE index_components IS '指数成分股权重历史（沪深300/中证500/中证1000）';
CREATE INDEX idx_index_comp_date ON index_components(trade_date, index_code);
```
用途: 行业中性化基准、基准对冲、IC超额收益计算。

### P3. execution_mode 字段（补充 trade_log 和 position_snapshot 表）

```sql
-- trade_log 表新增字段
ALTER TABLE trade_log ADD COLUMN execution_mode VARCHAR(10) DEFAULT 'paper';
COMMENT ON COLUMN trade_log.execution_mode IS 'paper=模拟, live=实盘';

-- position_snapshot 表新增字段
ALTER TABLE position_snapshot ADD COLUMN execution_mode VARCHAR(10) DEFAULT 'paper';
COMMENT ON COLUMN position_snapshot.execution_mode IS 'paper=模拟, live=实盘';
```
Paper Trading和实盘共用strategy_id，通过execution_mode区分记录。

### P4. health_checks 表与调度绑定

```sql
CREATE TABLE health_checks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_date      DATE NOT NULL,
    check_time      TIMESTAMPTZ DEFAULT NOW(),
    postgresql_ok   BOOLEAN NOT NULL,
    redis_ok        BOOLEAN NOT NULL,
    data_fresh      BOOLEAN NOT NULL,
    factor_nan_ok   BOOLEAN NOT NULL,
    disk_ok         BOOLEAN NOT NULL,
    celery_ok       BOOLEAN NOT NULL,
    all_pass        BOOLEAN NOT NULL,
    failed_items    TEXT[],             -- 失败项列表
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE health_checks IS '每日全链路健康预检记录';
CREATE INDEX idx_health_date ON health_checks(check_date DESC);
```
每日调度链路第一步（T0）写入此表。all_pass=false时暂停后续全部任务。

### P5. 交易日历维护机制

- 年初从Tushare `trade_cal` 接口导入全年日历
- 每日T0预检中校验: 今天是否交易日 vs 实际市场开盘状态
- 提供手动修改API: `PUT /api/system/trading-calendar/{date}` 应对临时变动
- 临时休市（特殊事件）需要手动维护后触发调度链路跳过

### P6. 调度时序修正

A股调度从"T+1日凌晨06:00计算"改为"**T日盘后16:00-18:00计算，T+1日盘前仅确认执行**"。
详见 DEV_SCHEDULER.md Review补丁§P1。

### P7. 因子预处理顺序修正

正确顺序: 去极值→填充→**中性化→标准化**（先中性化再zscore）。
详见 DEV_BACKTEST_ENGINE.md Review补丁§P1 和 DEV_FACTOR_MINING.md Review补丁§P1。
