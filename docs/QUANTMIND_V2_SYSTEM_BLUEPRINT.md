# QuantMind V2 — System Blueprint

> **唯一设计真相源。从代码出发，标记实现状态。**
> **创建**: 2026-04-16 | **基于**: 代码实际状态 + 6 项架构决策
> **状态标记**: ✅ DONE | 🔧 PARTIAL | ⬜ TODO | ❌ ABANDONED | 🧊 FROZEN | ⏳ DEFERRED

---

## §1 系统概述

### 1.1 定位
个人 A 股 + 外汇(⏳)量化交易系统，Python-first 全栈。

### 1.2 目标
| 指标 | 目标 | 当前 |
|------|------|------|
| 年化收益 | 15-25% | WF OOS ~18% (CORE3+dv_ttm) |
| Sharpe | 1.0-2.0 | WF OOS **0.8659** |
| MDD | <15% | WF OOS **-13.91%** |
| 策略数 | N 个独立策略 | 1 个 (等权 Top-N 月度) |

### 1.3 架构决策 (2026-04-16 确认)

| # | 决策 | 结论 |
|---|------|------|
| D1 | 外汇模块 | ⏳ DEFERRED — A股稳定盈利后启动，设计保留 |
| D2 | 前端系统 | PROGRESSIVE — 12 页面 + AI 助手 + 补运维操作 |
| D3 | 多策略框架 | StrategyBase 支持 N 个独立策略并行 |
| D4 | ML 层 | 换赛道: 微结构 ML / LLM 因子发现 / 另类数据 |
| D5 | 参数系统 | 50 核心 + 高价值待实现标记 |
| D6 | GP vs LLM | 并行互补: GP 先闭环 → LLM prompt 改造 → 轨迹进化 |

### 1.4 硬件约束
- Windows 11 Pro, R9-9900X3D, RTX 5070 12GB, 32GB DDR5
- PG shared_buffers=2GB 固定开销，重数据 Python 进程 max 2 并发 (铁律 9)
- cupy 不支持 Blackwell sm_120，GPU 用 PyTorch cu128

---

## §2 技术架构

### 2.1 技术栈

| 层 | 技术 | 状态 |
|----|------|------|
| 后端 API | FastAPI + sync psycopg2 + Celery + Redis | ✅ |
| 前端 | React 18 + TypeScript + Tailwind 4.1 + ECharts/Recharts + Zustand | 🔧 |
| 数据库 | PostgreSQL 16.8 + TimescaleDB 2.26.0 | ✅ |
| 事件总线 | Redis Streams (`qm:{domain}:{event_type}`) via StreamBus | ✅ |
| 服务管理 | Servy v7.6 (4 服务) | ✅ |
| 调度 | Windows Task Scheduler (16 任务) + Celery Beat (2 任务) | ✅ |
| 交易 | 国金 miniQMT (A 股) | ✅ |
| 缓存 | 本地 Parquet 快照 (按年分区) | ✅ |

### 2.2 分层架构 (铁律 31/32)

```
┌─────────────────────────────────────────────────┐
│  Router (backend/app/api/)                       │ 参数验证 + 调用 Service + 返回 Response
├─────────────────────────────────────────────────┤
│  Service (backend/app/services/)                 │ 业务逻辑, 内部不 commit (铁律 32)
├─────────────────────────────────────────────────┤
│  Engine (backend/engines/)                       │ 纯计算, 无 IO (铁律 31)
├─────────────────────────────────────────────────┤
│  Data (backend/data/ + backend/app/data_fetcher/)│ 本地缓存 + DataPipeline 入库 (铁律 17)
├─────────────────────────────────────────────────┤
│  DB: PostgreSQL + TimescaleDB + Redis            │ 持久化 + 缓存 + 事件总线
└─────────────────────────────────────────────────┘
```

### 2.3 Servy 服务 (启动顺序)

| # | 服务名 | 描述 | 依赖 |
|---|--------|------|------|
| 1 | QuantMind-FastAPI | uvicorn --workers 2, port 8000 | Redis, PG |
| 2 | QuantMind-Celery | celery worker --pool=solo | Redis |
| 3 | QuantMind-CeleryBeat | celery beat scheduler | Redis, Celery |
| 4 | QuantMind-QMTData | QMT→Redis 60s 同步 | Redis |

### 2.4 市场耦合度 (Forex 复用评估)

| 模块 | 耦合度 | 外汇复用 |
|------|--------|---------|
| DB/Redis/StreamBus | 市场无关 | 直接复用 |
| Celery/调度框架 | 市场无关 | 直接复用 |
| YAML 配置体系 | 市场无关 | 直接复用 |
| 前端架构 (React/Zustand) | 市场无关 | 加路由页面 |
| AI Pipeline 状态机 | 市场无关 | market 路由 |
| DataPipeline 框架 | A 股 Contract | 新增 forex Contract |
| 因子计算 | A 股截面 | 外汇时序, 独立写 |
| 回测引擎 | A 股 Hybrid | 外汇纯事件驱动, 独立写 |
| 执行系统 | miniQMT | MT5 Adapter, 独立写 |
| 风控状态机 | A 股 L1-L4 | 框架复用, 规则替换 |

---

## §3 数据管道

### 3.1 数据源

| 数据源 | 用途 | 频率 | 状态 |
|--------|------|------|------|
| Tushare Pro | 日频行情/财务/指数/北向 | 每日 16:15 | ✅ |
| Baostock | 5 分钟 K 线 | 一次性批量 | ✅ (190M 行) |
| 国金 miniQMT | 实时持仓/资产/价格 | 60s 同步 | ✅ |

### 3.2 DataPipeline (铁律 17)

```
数据入库唯一路径:
  DataPipeline.ingest(df, Contract) → rename → 列对齐 → 单位转换 → 值域验证 → FK 过滤 → Upsert
```

| 组件 | 文件 | 状态 |
|------|------|------|
| Contract 定义 (10 张表 schema) | `data_fetcher/contracts.py` | ✅ |
| DataPipeline 入库管道 | `data_fetcher/pipeline.py` | ✅ |
| Tushare 拉取 | `data_fetcher/tushare_fetcher.py` | ✅ |
| 数据加载 | `data_fetcher/data_loader.py` | ✅ |
| INSERT 违规残留 | 生产路径 6 处 CRITICAL | 🔧 待清理 |

### 3.3 核心数据表

| 表 | 行数 | 存储 | 时间范围 |
|----|------|------|---------|
| klines_daily | 11.7M | 4 GB (hypertable) | 2014-01 ~ now |
| daily_basic | 11.5M | 3 GB | 2014-01 ~ now |
| factor_values | **816M** | **155 GB** (hypertable) | 2014-01 ~ now |
| minute_bars | **191M** | 21 GB | 2021-01 ~ 2025-12 |
| moneyflow_daily | 11.4M | — | 2014-01 ~ now |
| northbound_holdings | 5.5M | — | 2017-01 ~ now |

### 3.4 Parquet 缓存

| 缓存 | 路径 | 用途 |
|------|------|------|
| 回测数据 | `cache/backtest/YEAR/*.parquet` | 12 年回测加载 30min→1.6s |
| 基线快照 | `cache/baseline/*.parquet` | regression_test 可复现锚点 |
| profiler 缓存 | `cache/profiler/` | 因子画像中间结果 |

### 3.5 调度链路

```
16:15 数据拉取 → 16:25 预检 → 16:30 因子+信号 → 17:00-17:30 收尾(moneyflow/巡检/衰减)
→ T+1 09:31 执行 → 15:10 对账
```

---

## §4 因子系统

### 4.1 因子池状态

| 池 | 数量 | 说明 |
|----|------|------|
| **CORE (Active)** | 4 | turnover_mean_20(-1), volatility_20(-1), bp_ratio(+1), dv_ttm(+1) |
| CORE5 (前任基线) | 5 | +amihud_20, reversal_20 (降级保留) |
| PASS 候选 | 48 | FACTOR_TEST_REGISTRY 中 PASS 状态 (含 Alpha158 六 + PEAD + 16 微结构) |
| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非 9.1%) |
| DEPRECATED | 5 | momentum_5/10/60, volatility_60, turnover_std_20 |
| LGBM 特征集 | 70 | 全部 factor_values 因子 (DB 自动发现) |

### 4.2 因子计算架构 (Phase C 完成, 2026-04-16)

```
backend/engines/factor_engine/        ← 纯计算包 (铁律 31)
  ├── __init__.py                     ← shim re-export (416 行, -80%)
  ├── _constants.py                   ← direction 字典 + metadata
  ├── calculators.py                  ← 30 个 calc_* 纯函数
  ├── alpha158.py                     ← Alpha158 helpers
  ├── preprocess.py                   ← MAD→fill→neutralize→zscore→IC
  └── pead.py                         ← PEAD 纯计算

backend/app/services/
  ├── factor_repository.py            ← 数据加载层 (load_daily/load_bulk*/load_pead*)
  └── factor_compute_service.py       ← 编排层 (compute_daily/batch/save, 走 DataPipeline)
```

### 4.3 因子评估流程

```
经济机制假设 (铁律 13/14)
  → IC 计算 + 入库 factor_ic_history (铁律 11)
  → 画像 (factor_profiler, 5 维)
  → 模板匹配 (T1-T15)
  → Gate G1-G10 (含 G9 AST 新颖性 + G10 可解释性)
  → 噪声鲁棒性 G_robust (铁律 20)
  → 回测验证 (paired bootstrap p<0.05, 铁律 5)
  → WF OOS 验证 (铁律 8)
```

### 4.4 IC 口径 (铁律 19, 全项目统一)

| 维度 | 定义 |
|------|------|
| 因子值 | neutral_value (MAD→fill→WLS 行业+ln 市值→zscore→clip±3) |
| 前瞻收益 | T+1 买入→T+horizon 卖出的超额收益 (相对 CSI300) |
| IC 类型 | Spearman Rank IC |
| 工具 | `backend/engines/ic_calculator.py` 唯一入口 |

### 4.5 关键模块

| 模块 | 文件 | 状态 |
|------|------|------|
| 因子画像 V2 | `engines/factor_profiler.py` | ✅ 48+15 因子, 12 章节 |
| 批量中性化 | `engines/fast_neutralize.py` | ✅ 15 因子/17.5min |
| IC 计算器 | `engines/ic_calculator.py` | ✅ 统一口径 |
| 中性化器 | `engines/neutralizer.py` | ✅ |
| 因子入库 pipeline | `services/factor_onboarding.py` | ✅ |

---

## §5 信号与选股

### 5.1 信号路径 (铁律 16, 唯一路径)

```
SignalComposer → PortfolioBuilder → BacktestEngine (回测)
                                  → ExecutionService (PT/实盘)
```

### 5.2 当前策略配置 (CORE3+dv_ttm, 2026-04-12 WF PASS)

| 参数 | 值 | 来源 |
|------|-----|------|
| 因子 | turnover_mean_20(-1), volatility_20(-1), bp_ratio(+1), dv_ttm(+1) | pt_live.yaml |
| 合成 | 等权平均 | pt_live.yaml |
| 选股 | Top 20 | .env PT_TOP_N |
| 调仓 | 月度 (月末最后交易日) | pt_live.yaml |
| Modifier | Partial SN b=0.50 | .env PT_SIZE_NEUTRAL_BETA |
| 约束 | 行业上限无, 换手率≤50%, 100 股整手, 日均成交≥5000 万 | pt_live.yaml |
| 排除 | BJ + ST + 停牌 + 新股(<60 天) | 代码硬编码 |

### 5.3 成本模型

| 成本项 | 值 |
|--------|-----|
| 佣金 | 万 0.854 (国金, min ¥5) |
| 印花税 | 2023-08-28 前 0.1%, 后 0.05% |
| 过户费 | 0.001% |
| 滑点 | 三因素 (spread + impact + overnight_gap) |

### 5.4 基线演进

```
1.24 (虚高) → 0.94 (Phase 1 加固) → 0.6095 (5yr regression)
→ 0.5309 (12yr) → 0.6521 (SN WF OOS) → 0.8659 (CORE3+dv_ttm WF OOS)
```

### 5.5 关键模块

| 模块 | 文件 | 状态 |
|------|------|------|
| 信号生成 | `services/signal_service.py` | ✅ |
| 配置加载 | `services/config_loader.py` | ✅ YAML 驱动 |
| 配置校验 | `engines/config_guard.py` | ✅ 6 参数硬校验 (铁律 34) |
| 滑点模型 | `engines/slippage_model.py` | ✅ 三因素 |

---

## §6 回测引擎

### 6.1 架构 (Step 4-A 拆分, 8 模块)

```
backend/engines/backtest/
  ├── engine.py       ← 核心事件循环 (562 行)
  ├── runner.py       ← run_hybrid/run_composite 入口 (281 行)
  ├── broker.py       ← 成本模型 + SimBroker (309 行)
  ├── validators.py   ← 涨跌停/停牌/完整性过滤链 (105 行)
  ├── executor.py     ← 事件执行器 (81 行)
  ├── types.py        ← BacktestResult/Fill/Order 数据类 (92 行)
  └── config.py       ← BacktestConfig (49 行)
```

### 6.2 关键特性

| 特性 | 状态 | 说明 |
|------|------|------|
| Hybrid 架构 (向量化信号 + 事件驱动执行) | ✅ | |
| YAML 配置驱动 | ✅ | `configs/pt_live.yaml`, `backtest_12yr.yaml` |
| 历史印花税率 | ✅ | 2023-08-28 分界 |
| 三因素滑点 | ✅ | spread + volume_impact + overnight_gap |
| 涨跌停过滤 | ✅ | validators.py |
| BJ 股排除 | ✅ | Step 6-C 修复 |
| Parquet 缓存 | ✅ | 12 年 30min→1.6s |
| 可复现 (铁律 15) | ✅ | (config_hash, git_commit) 入 DB, max_diff=0 |
| Walk-Forward | ✅ | 5-fold, `scripts/walk_forward.py` |
| 12 年全量跑通 | ✅ | 328s, OOM 已解决 |

### 6.3 回测入口

```bash
python scripts/run_backtest.py --config configs/pt_live.yaml        # 标准回测
python scripts/run_backtest.py --config configs/backtest_12yr.yaml  # 12 年基线
python scripts/walk_forward.py --config ...                         # WF 验证
python cache/baseline/regression_test.py                            # 回归测试
```

---

## §7 执行系统

### 7.1 Paper Trading 架构 (Step 6-A 拆分)

```
scripts/run_paper_trading.py (345 行编排器)
  → services/pt_data_service.py      ← 并行数据拉取
  → services/pt_monitor_service.py   ← 开盘跳空检测
  → services/pt_qmt_state.py         ← QMT↔DB 状态同步
  → services/shadow_portfolio.py     ← LightGBM 影子选股
```

### 7.2 QMT 数据架构 (A-lite 方案)

```
QMT Data Service (scripts/qmt_data_service.py) — 唯一 import xtquant 入口
  每 60s 同步: 持仓→Redis portfolio:current
                资产→Redis portfolio:nav
                价格→Redis market:latest:{code} (TTL=90s)

其他模块 → QMTClient (app/core/qmt_client.py) → Redis 缓存 (不直接 import xtquant)
```

### 7.3 调度链路

| 时间 | 任务 | 状态 |
|------|------|------|
| T-1 16:15 | 数据拉取 (Tushare 三 API 并行) | ✅ |
| T-1 16:25 | 预检 (health_check.py) | ✅ |
| T-1 16:30 | 因子计算 + 信号生成 | ✅ |
| T-1 17:00-17:30 | 收尾 (moneyflow/巡检/衰减) | ✅ |
| T 09:31 | 执行 (run_paper_trading.py) | ✅ |
| T 14:30 | PMS 阶梯利润保护 (Celery Beat) | ✅ |
| T 15:10 | 对账 | ✅ |

### 7.4 PT 状态
- **当前**: 自动运行中 (CORE3+dv_ttm, 配置已更新 2026-04-12)
- **WF OOS**: Sharpe=0.8659, MDD=-13.91%

---

## §8 风控系统

### 8.1 A 股风控层级

| 层 | 功能 | 状态 |
|----|------|------|
| L1 开仓前检查 | 行业集中度/单股上限/流动性/成交额 | ✅ |
| L2 持仓监控 | 回撤预警/因子衰减/持仓偏离 | ✅ |
| L3 自动熔断 | 回撤>阈值自动减仓 | ✅ |
| L4 人工熔断 | 紧急全清, 需 approve_l4.py 恢复 | ✅ |

### 8.2 PMS 阶梯利润保护

```
14:30 Celery Beat 检查 (非交易日跳过)
  L1: 浮盈>30% + 回撤>15% → 卖出
  L2: 浮盈>20% + 回撤>12% → 卖出
  L3: 浮盈>10% + 回撤>10% → 卖出

配置: .env PMS_ENABLED + PMS_LEVEL{1,2,3}_GAIN/DRAWDOWN
触发后: 更新 position_snapshot, 写 risk_event_log (事件名 `risk.triggered`)

⚠️ **post-MVP 3.1** (Session 30 2026-04-24 完结): 上述 pms_engine 路径已 DEPRECATED, PMS L1/L2/L3 保护迁入 Platform Risk Framework (`backend/platform/risk/rules/pms.py`), 走 `PlatformRiskEngine.run()` 14:30 Celery Beat `risk-daily-check`, 事件入 `risk_event_log` 替 老 `position_monitor` 表 + 废原 StreamBus `qm:pms:protection_triggered` 广播 (F27 死码). 老 pms_engine.py 保留不动 (Sunset gate 条件满足后清理).
```

### 8.3 关键模块

| 模块 | 文件 | 状态 |
|------|------|------|
| 风控状态机 | `services/risk_control_service.py` | ✅ L1-L4 |
| PMS 保护 | `services/pms_service.py` | ✅ 3 层 |
| L4 恢复 CLI | `scripts/approve_l4.py` | ✅ |
| config_guard | `engines/config_guard.py` | ✅ 铁律 34 |

---

## §9 多策略框架 ⬜ TODO (决策 D3)

### 9.1 目标架构

```
StrategyBase (抽象基类)
  ├── EqualWeightStrategy         ← 当前策略 (CORE3+dv_ttm Top-N 月度)
  ├── EventDrivenStrategy         ← PEAD/北向信号触发
  ├── MLMicrostructureStrategy    ← 微结构因子 ML 非线性组合 (新赛道 1)
  └── ...                         ← 未来扩展

每个策略独立:
  - YAML 配置 (configs/{strategy_name}.yaml)
  - 信号生成 (走 SignalComposer, 铁律 16)
  - 回测 + WF 验证
  - 风控规则

统一层:
  - 资本分配 (策略间权重, 初期固定, 后期 AI 动态)
  - 执行合并 (同股冲突消解 → 一个 ExecutionService 下单)
  - 组合监控 (Dashboard 多策略视图)
```

### 9.2 实现路径

| 步骤 | 内容 | 优先级 |
|------|------|--------|
| 1 | 抽象 StrategyBase 接口 (signal/portfolio/risk/config) | ⬜ 高 |
| 2 | 当前等权策略封装为 EqualWeightStrategy | ⬜ 高 |
| 3 | 资本分配层 (初期: 固定比例 YAML 配置) | ⬜ 中 |
| 4 | 执行合并层 (同股冲突消解) | ⬜ 中 |
| 5 | EventDrivenStrategy (PEAD/北向, 独立调仓频率) | ⬜ 后续 |
| 6 | MLMicrostructureStrategy (新赛道 1 产出) | ⬜ 后续 |

### 9.3 与因子评估框架的对应

| 策略类型 | 因子评估框架 | 调仓频率 |
|---------|------------|---------|
| RANKING | 等权 Top-N | 月度 |
| FAST_RANKING | 加权排名 | 周度 |
| EVENT | 事件触发 | 按事件 |
| ML_CONTINUOUS | ML 连续权重 | 日/周度 |

---

## §10 ML 系统 (决策 D4: 换赛道)

### 10.1 已关闭赛道 🧊 FROZEN

| 实验 | 方法 | 结果 | 失败原因 |
|------|------|------|---------|
| G1 | LightGBM 17 因子→排名→等权 | Sharpe=0.68 vs 等权 0.83 | 排名→等权丢失概率信息 |
| 6-H | LightGBM WF 月度 | IC=0.067, Sharpe=0.09 | IC 太弱, 成本吃掉 |
| 2.1 | E2E 可微 Sharpe | val=1.26→实盘-0.99 | A 股成本不可微分 |
| 2.2 | IC 加权/MVO/LambdaRank | 全败, 最佳 0.56 | Portfolio 层无优化空间 |
| 3D | ML Synthesis 4 配置 | A-REG=0.54 最优 | 更多因子=更差, 无新 alpha |

**解冻条件**: 新增≥3 类另类数据源, 或非等权策略 WF PASS

### 10.2 新赛道 1: 微结构 ML ⬜ 高优先级

```
数据: minute_bars 190M 行 (已有, 未利用)
  → 特征工程: 日内波动率曲线 / 成交量分布 / 尾盘模式 / VWAP 偏离 / 订单流不平衡
  → ML 非线性组合 (不走等权 Top-N, 走连续权重)
  → 多策略框架中的独立策略 (MLMicrostructureStrategy)

依据: Phase 3E 16 个微结构因子 IC PASS + noise ROBUST, 但等权加入 FAIL
  → 需要 ML 非线性组合才能释放价值
```

### 10.3 新赛道 2: LLM 数据驱动因子发现 ⬜ 中优先级

```
参考: AlphaAgent (KDD 2025, CSI500 IR=1.5)
      QuantaAlpha (清华/北大/CMU, 轨迹进化)
      QuantEvolve (MAP-Elites Quality-Diversity)

实现: 改造 LLM prompt 工程
  当前 (失败): "请生成一个因子" → IC=0.006
  改造后: "基于以下 IC 画像 + 市场假设 + AST 约束, 生成因子表达式"
  → 注入因子画像数据 + Gate G9 AST 去重 + G10 假设对齐
  → 与决策 D6 (GP vs LLM) 的 LLM 改造步骤对应
```

### 10.4 新赛道 3: 另类数据 ⬜ 长期

```
候选数据源:
  - 中文财经情感 (FinBERT/LLaMA, 分析师报告)
  - 知识图谱 (LLM 提取企业关系 → 供应链/竞争)
  - 事件数据 (PEAD 深化, 增发/回购/高管变动)

参考: 知识图谱驱动金融预测 (2026), 中文情感分析 (2025)
突破 IC 天花板 0.09 的最直接路径, 但数据获取成本高
```

### 10.5 非选股 ML ✅ OPEN (独立赛道)

| 应用 | 说明 | 优先级 |
|------|------|--------|
| 数据异常检测 | factor_values NaN/异常值自动发现 | ⬜ 高 |
| IC 衰减预警 | 因子 IC 时序预测, 提前预警衰退 | ⬜ 中 |
| 执行优化 | 预测日内价格冲击, 优化执行时机 | ⬜ 低 |
| Regime 检测 | 牛/熊/震荡分类 (5 指标线性检测已证伪, 考虑非线性) | ⬜ 低 |

### 10.6 在线学习 (长期方向)

```
参考: DoubleAdapt (KDD 2023, Qlib, CSI300/500 SOTA)
  双 meta-learner: 数据适配器 + 模型适配器
  解决 regime 漂移 (牛市训练→熊市崩溃)
  前提: 新赛道 1/2 产出可用 ML 模型后叠加
```

---

## §11 AI 闭环与因子发现 (决策 D6)

### 11.1 DEV_AI_EVOLUTION V2.1 (705 行, 设计完成)

```
四层架构:
  L1 监控层: IC 衰减检测 + 因子健康告警 + 自动报告
  L2 轨迹进化层: AlphaAgent/QuantaAlpha 式因子发现
  L3 Feature Map 层: Quality-Diversity 多样策略维护
  L4 资本分配层: 策略间动态权重

Orchestrator 状态机: 7 状态 + 16 转换规则
事件总线: Redis Streams (qm:ai:*)
自动化矩阵: 10 步 × 4 级 (L0 手动 → L3 全自动)
```

### 11.2 实现状态

| 组件 | 状态 | 说明 |
|------|------|------|
| L1 IC 监控 | 🔧 | `monitor_factor_ic.py` 存在, Phase 3 部署中 |
| L1 因子健康告警 | 🔧 | `factor_health_check.py` 存在 |
| L2 GP 引擎 | 🔧 40% | DEAP+WarmStart+岛屿模型, 缺闭环评估 |
| L2 LLM 因子生成 | ⬜ | prompt 工程待改造 (AlphaAgent 范式) |
| L3 Feature Map | ⬜ | QuantEvolve MAP-Elites |
| L4 资本分配 | ⬜ | 多策略框架先行 (§9) |
| Orchestrator | ⬜ | 状态机 + Redis Streams |
| Pipeline 控制台 (前端) | 🔧 | 页面存在, 后端 5 端点 |

### 11.3 GP vs LLM 实现路径 (决策 D6)

| 步骤 | 内容 | 优先级 |
|------|------|--------|
| 1 | GP 闭环: DSL→IC 自动评估→Gate 自动→入库 | ⬜ 高 |
| 2 | LLM prompt 改造: 注入画像数据+AST 去重+假设对齐 | ⬜ 中 |
| 3 | 轨迹进化: GP+LLM 产出的 trajectory 交叉进化 | ⬜ 后续 |

### 11.4 关键模块

| 模块 | 文件 | 状态 |
|------|------|------|
| GP 引擎 | `engines/mining/gp_engine.py` | 🔧 40% |
| FactorDSL | `engines/mining/factor_dsl.py` | ✅ |
| Pipeline 编排 | `engines/mining/pipeline_orchestrator.py` | 🔧 |
| GP Celery 任务 | `tasks/mining_tasks.py` | ✅ |
| GP Pipeline 工具 | `engines/mining/pipeline_utils.py` | ✅ |

---

## §12 前端系统 (决策 D2)

### 12.1 现有资产

| 类别 | 数量 |
|------|------|
| 页面文件 | 24 个 |
| API 客户端 | 12 个 |
| 后端 API 端点 | ~96 个 |
| 共享组件 | 53 个 |
| Zustand Store | 4 个 |

### 12.2 页面清单与状态

| 页面 | 文件 | 后端 API | 状态 |
|------|------|----------|------|
| Dashboard | `Dashboard/` | 8 端点 | 🔧 需审计数据绑定 |
| A 股详情 | `DashboardAstock.tsx` | (共用 dashboard API) | 🔧 |
| 回测配置 | `BacktestConfig.tsx` | 15 端点 (最完整) | 🔧 |
| 回测结果 | `BacktestResults.tsx` | (同上) | 🔧 |
| 回测运行 | `BacktestRunner.tsx` | (同上) | 🔧 |
| 因子库 | `FactorLibrary.tsx` | 8 端点 | 🔧 |
| 因子评估 | `FactorEvaluation.tsx` | (共用 factors API) | 🔧 |
| 因子实验室 | `FactorLab.tsx` | 5 端点 (mining) | 🔧 |
| 挖掘任务 | `MiningTaskCenter.tsx` | (同上) | 🔧 |
| Pipeline | `PipelineConsole.tsx` | 5 端点 | 🔧 |
| Agent 配置 | `AgentConfig.tsx` | (共用 pipeline API) | 🔧 |
| 执行 | `Execution/` | 3+14=17 端点 | 🔧 |
| PT 毕业 | `PTGraduation.tsx` | 5 端点 | 🔧 |
| PMS | `PMS.tsx` | 4 端点 | 🔧 |
| 风控 | `RiskManagement.tsx` | (共用 execution_ops) | 🔧 |
| 系统设置 | `SystemSettings.tsx` | 5 端点 | 🔧 |
| 策略工作台 | `StrategyWorkspace.tsx` | strategies API | 🔧 |
| 策略库 | `StrategyLibrary.tsx` | (同上) | 🔧 |
| 持仓 | `Portfolio.tsx` | 3 端点 | 🔧 |
| 报告 | `ReportCenter.tsx` | 3 端点 | 🔧 |
| 市场数据 | `MarketData.tsx` | 3 端点 | 🔧 |
| 外汇详情 | `DashboardForex.tsx` | 无后端 | ⏳ |
| 即将上线 | `ComingSoon.tsx` | — | 占位 |

### 12.3 缺失的运维功能 ⬜ TODO

| 功能 | 说明 | 后端支持 |
|------|------|---------|
| 日志查看器 | Servy 服务日志实时流 | ⬜ 需新增 API |
| 服务管理 | 启停/重启 Servy 服务 | ⬜ 需新增 API |
| 配置编辑 | 前端编辑 pt_live.yaml / .env 参数 | ⬜ 需新增 PUT API + 验证 |
| 快捷操作 | 一键 health_check / regression_test / 数据拉取 | 🔧 部分有 (system/scheduler) |

### 12.4 AI 助手面板

| 页面 | 助手功能 | 后端 API | 状态 |
|------|---------|---------|------|
| 策略工作台 | 生成策略/优化/解释/诊断 | POST /api/ai/strategy-assist | ⬜ |
| 因子实验室 | 设计建议/解释/诊断/推荐 | POST /api/ai/factor-assist | ⬜ |

后端需对接 LLM API (DeepSeek/Claude)，注入当前页面上下文。

### 12.5 设计参考
- UI 规范/组件/色彩: `docs/DEV_FRONTEND_UI.md` (仍有价值)
- 页面功能描述: 需与实际 96 端点重新对齐

---

## §13 调度与运维

### 13.1 Task Scheduler (16 active)

| # | 任务 | 频率 | 状态 |
|---|------|------|------|
| 1 | QM-DailyFetch | 16:15 工作日 | ✅ |
| 2 | QM-DailyPrecheck | 16:25 工作日 | ✅ |
| 3 | QM-DailyFactors | 16:30 工作日 | ✅ |
| 4 | QM-DailySignal | 17:00 工作日 | ✅ |
| 5 | QM-DailyExecuteAfterData | 09:31 工作日 | ✅ |
| 6 | QM-DailyReconciliation | 15:10 工作日 | ✅ |
| 7 | QM-DailyBackup | 02:00 每日 | ✅ |
| 8 | QM-Moneyflow | 17:10 工作日 | ✅ |
| 9 | QM-DataQuality | 17:15 工作日 | ✅ |
| 10 | QM-WeeklyFactorDecay | 周六 10:00 | ✅ |
| 11 | QM-CancelStaleOrders | 14:50 工作日 | ✅ |
| 12 | QM-IntradayMonitor | 10:00-14:30 每30min | ✅ |
| 13 | QM-MiniQMT-AutoStart | 09:15 工作日 | ✅ |
| 14 | QM-PTWatchdog | 每10min | ✅ |
| 15 | QM-ICMonitor | 17:20 工作日 | ✅ (Phase 3 新增) |
| 16 | QM-FactorHealth | 周六 11:00 | ✅ (Phase 3 新增) |

### 13.2 Celery Beat (2 任务)

| 任务 | 频率 | 状态 |
|------|------|------|
| pms-daily-check | 工作日 14:30 | ✅ |
| gp-weekly-mining | 周日 22:00 | ✅ |

### 13.3 StreamBus 事件

| Stream | 说明 | 状态 |
|--------|------|------|
| qm:signal:generated | 信号生成完成 | ✅ |
| qm:execution:completed | 执行完成 | ✅ |
| ~~qm:pms:protection_triggered~~ | ~~PMS 触发~~ — **DEPRECATED post-MVP 3.1** (F27 死码, 无 consumer). 改用 `risk_event_log` 表 (PMS/Intraday/CB 三类 RiskRule 统一写入, ADR-010 Risk Framework) | ❌ |
| qm:qmt:status | QMT 连接状态 | ✅ |
| qm:data:updated | 数据更新完成 | ✅ |

> **MVP 3.1 Risk Framework** (Session 30 2026-04-24) 事件统一写 `risk_event_log` 表 (event name 语义 `risk.triggered`, ADR-003 Event Sourcing 集成待 Wave 3 MVP 3.4 event_outbox 上线). 不再使用 StreamBus 广播 PMS 专用频道. 未来若需要 pub/sub 风控事件, 走 `risk_event_log → event_outbox → Redis Stream` 统一路径 (MVP 3.4).

---

## §14 参数配置 (决策 D5)

### 14.1 核心参数 (在用, 50 个)

| 类别 | 参数 | 来源 | 数量 |
|------|------|------|------|
| 因子 | factor_list, directions, weights | pt_live.yaml | 3 |
| 选股 | top_n, industry_cap, turnover_cap | .env + yaml | 3 |
| 调仓 | rebalance_freq, signal_day | pt_live.yaml | 2 |
| Modifier | size_neutral_beta | .env | 1 |
| 成本 | commission, stamp_tax, transfer_fee, min_commission | pt_live.yaml | 4 |
| 滑点 | slippage_model, spread/impact/gap 参数 | pt_live.yaml | 4 |
| 风控 | pms_enabled, pms_level{1,2,3}_{gain,drawdown} | .env | 7 |
| 风控 | circuit_breaker thresholds L1-L4 | config.py | 8 |
| 回测 | initial_capital, benchmark, start/end_date | yaml | 4 |
| 数据 | tushare_token, db_url, redis_url | .env | 3 |
| 调度 | 16 个 Task Scheduler cron 表达式 | Task Scheduler | ~11 |

### 14.2 高价值待实现 (~30 个)

| 参数 | 说明 | 关联决策 |
|------|------|---------|
| strategy_weights | 多策略间资本分配权重 | D3 多策略 |
| ml_retrain_frequency | ML 模型重训练频率 | D4 ML |
| gp_population_size | GP 种群大小 | D6 GP |
| gp_generations | GP 进化代数 | D6 GP |
| llm_model / llm_temperature | LLM 因子生成配置 | D6 LLM |
| ic_decay_alert_threshold | IC 衰减告警阈值 | §11 AI 闭环 |
| factor_auto_retire_days | 因子自动退役天数 | §11 AI 闭环 |
| wf_rolling_months | Rolling WF 窗口 | §11 监控 |
| notification_webhook | 告警 webhook URL | 运维 |
| notification_levels | 各级别开关 | 运维 |

### 14.3 铁律 34: Single Source of Truth

```
每个参数唯一权威来源:
  .env → config.py:Settings (pydantic-settings 自动加载)
  configs/*.yaml → config_loader.py (YAML 解析)

config_guard 启动时检查:
  .env + pt_live.yaml + Python 常量 三处对齐
  不一致 → RAISE ConfigDriftError (不允许只报 warning)
```

---

## §15 外汇模块 ⏳ DEFERRED (决策 D1)

### 15.1 状态
- **设计**: 完成 (`docs/DEV_FOREX.md`, 682 行)
- **实现**: 0%
- **启动前提**: A 股 PT 连续 3 个月 Sharpe>0.5 + MDD<20%
- **复用评估**: 框架 ~80%, 业务 ~30%, 综合 ~55%

### 15.2 已兼容 (零改动)
- `backtest_run.market` 字段
- StreamBus `qm:{domain}:{event}` 命名
- AI Pipeline 状态机 (market 路由)
- `ai_parameters` 通用参数表
- YAML 配置体系

### 15.3 启动时需新建
- 7 张 DB 表 (forex_symbol_config / forex_correlation / forex_macro_data / forex_cot_data / forex_factor_config / forex_backtest_trades / forex_swap_rates)
- MT5 Adapter (FastAPI localhost:8001)
- ForexBacktestEngine (纯事件驱动, 不复用 A 股)
- 外汇因子体系 (时序择时, 非截面选股)

### 15.4 预计工作量
~2 个月 (数据管道→回测→策略→MT5 对接→风控→Paper)

---

## §16 升级迭代机会

### 16.1 提升赚钱能力 (按预期收益排序)

| # | 方向 | 预期影响 | 依赖 | 优先级 |
|---|------|---------|------|--------|
| 1 | 微结构 ML 策略 (新赛道 1) | 突破等权 alpha 上限 | §9 多策略框架 + §10.2 | 高 |
| 2 | GP 闭环因子发现 | 持续发现新 alpha 因子 | §11.3 Step 1 | 高 |
| 3 | IC 衰减自动监控+告警 | 防止因子失效不自知 | Phase 3 已部署, 观察中 | 高 |
| 4 | Rolling WF 自动验证 | 每月自动验证策略有效性 | §11 L1 | 中 |
| 5 | LLM 数据驱动因子发现 | 探索非量价因子 | §11.3 Step 2 | 中 |
| 6 | 事件驱动策略 (PEAD/北向) | 独立 alpha 来源 | §9 多策略 | 中 |
| 7 | 另类数据 (情感/知识图谱) | 突破 IC 天花板 | §10.4 | 长期 |
| 8 | 外汇模块 | 新市场 alpha | §15 | 长期 |

### 16.2 提升系统可靠性

| # | 方向 | 说明 | 优先级 |
|---|------|------|--------|
| 1 | 前端运维功能 | 日志/服务管理/配置编辑替代 CLI | 高 |
| 2 | INSERT 违规清理 | 生产路径 6 处 CRITICAL 残留 | 中 |
| 3 | financial_indicators upsert | 只更新 3/16 字段 (H4 遗留) | 低 |
| 4 | 24 张空表清理 | 确认无用后删除 | 低 |

### 16.3 已证伪方向 (不可重复)

完整列表见 CLAUDE.md "已知失败方向"。核心教训:
- **等权框架 alpha 上限**: 4 因子 = 等权 Top-N 月度的信号质量天花板 (Phase 3B + 3E 双重确认)
- **ML 选股在日频量价因子上无效**: 5 次独立验证, IC 天花板 0.09 (换赛道, 非放弃 ML)
- **Portfolio 优化层无增量**: IC 加权/MVO/LambdaRank 全败, 瓶颈在预测质量非构建方法

---

## 附录 A: 文档索引

| 文档 | 用途 | 状态 |
|------|------|------|
| **本文件** (SYSTEM_BLUEPRINT.md) | 系统唯一设计真相源 | ✅ 当前 |
| CLAUDE.md | 编码规则 + 铁律 + 导航 | ✅ 持续维护 |
| SYSTEM_STATUS.md | 系统现状快照 | ✅ 按需更新 |
| DEV_BACKEND.md | 后端分层/数据流/协同矩阵 | 🔧 需与 Phase C 对齐 |
| DEV_BACKTEST_ENGINE.md | 回测引擎 Hybrid 架构 | 🔧 6 个 section 过时需重写 |
| DEV_FACTOR_MINING.md | 因子计算/预处理/IC | 🔧 需与 factor_engine/ 包对齐 |
| DEV_FRONTEND_UI.md | 前端 UI 规范/组件/色彩 | 🔧 功能描述需与 96 端点对齐 |
| DEV_SCHEDULER.md | 调度设计 | 🔧 需与 SCHEDULING_LAYOUT 对齐 |
| DEV_PARAM_CONFIG.md | 参数配置 220+ | 🔧 裁剪至实际在用 |
| DEV_AI_EVOLUTION.md | AI 闭环 V2.1 | ✅ 设计完成, 0% 实现 |
| DEV_FOREX.md | 外汇模块设计 | ⏳ DEFERRED |
| DEV_NOTIFICATIONS.md | 通知系统设计 | 🔧 |
| GP_CLOSED_LOOP_DESIGN.md | GP 因子挖掘闭环 | 🔧 40% 实现 |
| RISK_CONTROL_SERVICE_DESIGN.md | 风控 L1-L4 | ✅ |
| QUANTMIND_V2_DDL_FINAL.sql | 建表唯一来源 | ✅ |
| FACTOR_TEST_REGISTRY.md | 因子测试注册表 | ✅ 持续维护 |
| LESSONS_LEARNED.md | 经验教训 49 条 | ✅ |

## 附录 B: 铁律速查 (35 条)

| 类别 | 铁律 | 编号 |
|------|------|------|
| 工作原则 | 不猜测/验代码/不越权 | 1-3 |
| 因子研究 | 中性化/paired bootstrap/匹配策略 | 4-6 |
| 数据回测 | 数据地基/OOS/串行/全链路/IC 入库 | 7-11 |
| 因子质量 | AST 新颖性/经济机制/成本对齐 | 12-13, 18 |
| 重构原则 | 引擎不清洗/可复现/信号唯一/DataPipeline | 14-17 |
| IC 口径 | 统一 ic_calculator | 19 |
| 噪声鲁棒 | G_robust 5%/20% retention | 20 |
| 工程纪律 | 先搜开源/文档跟代码/独立可执行/设计<2页 | 21-24 |
| CC 执行 | 不靠记忆/验证不跳过/结论明确/发现即报 | 25-28 |
| 数据完整 | 禁 NaN 入 DB / 中性化后重建 Parquet | 29-30 |
| 基础设施 | Engine 纯计算/Service 不 commit/禁 silent fail/配置唯一/Secrets 环境变量 | 31-35 |
