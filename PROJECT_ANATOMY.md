# QuantMind V2 项目解剖报告

> **目的**: 重构架构设计前的深度系统理解——不是"系统有什么"，而是"系统怎么运转的"
> **日期**: 2026-04-09
> **方法**: 全量代码追踪+交叉验证，所有结论基于实际代码，非设计文档

---

## §1 code格式：系统中最深的伤口

### 1.1 code在系统中怎么流动

```
Tushare API
  │ 返回 ts_code = "600519.SH"
  ▼
┌─────────────────────────────────────────────────────────────┐
│ 数据入库（两条路径，行为不同）                                │
│                                                             │
│ 路径A: fetch_base_data.py (历史全量)                         │
│   L121: code = ts_code.split(".")[0]  → "600519"            │
│   L153: INSERT INTO symbols (code, ts_code, ...)            │
│         code="600519", ts_code="600519.SH" (两个都存)        │
│   L295: code = ts_code.split(".")[0]  → klines存"600519"    │
│   L395: code = ts_code.split(".")[0]  → daily_basic存"600519"│
│                                                             │
│ 路径B: pull_historical_data.py (后来补拉2014-2019)           │
│   直接用Tushare原始ts_code → klines存"600519.SH"            │
│   没有split(".")操作                                        │
│                                                             │
│ 路径C: tushare_fetcher.py (日增量)                           │
│   L184: df['code'] = df['code'].str.split('.').str[0]       │
│   → 日增量存"600519"（无后缀）                               │
│                                                             │
│ 路径D: data_loader.py (通用upsert)                          │
│   L154: df = df.rename(columns={'ts_code': 'code'})         │
│   L156: df['code'] = df['code'].str.split('.').str[0]       │
│   → 走这条路的都无后缀                                      │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ 数据库（混合态）                                             │
│                                                             │
│ klines_daily:    63.4%无后缀 + 36.6%有后缀                  │
│ daily_basic:     63.6%无后缀 + 36.4%有后缀                  │
│ moneyflow_daily: 54.6%无后缀 + 45.4%有后缀                  │
│ factor_values:   76.1%无后缀 + 23.9%有后缀                  │
│ northbound:      100%无后缀                                  │
│ symbols:         50%无后缀(5810) + 50%有后缀(5821退市补充)   │
│ trade_log:       100%无后缀                                  │
│ signals:         100%无后缀                                  │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ 因子计算 (factor_engine.py)                                  │
│   读klines_daily → 混合code格式进来                          │
│   compute_batch_factors: 不做code格式转换                    │
│   写factor_values → 继承klines的混合格式                     │
│                                                             │
│ ⚠️ 同一只股票"600519"和"600519.SH"被当作两只不同的股票       │
│   因子值被分别计算和存储                                     │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ 信号生成                                                     │
│                                                             │
│ PT路径: run_paper_trading.py                                 │
│   L938: fv = load_factor_values(trade_date, conn)            │
│   run_backtest.py L51: SELECT code, factor_name, neutral_value│
│   → 不加WHERE过滤code格式，混合都进来                        │
│   → SignalService.generate_signals() → SignalComposer        │
│   → 输出target_weights: {"600519": 0.05, ...} (无后缀)      │
│                                                             │
│ 回测路径: scripts/research/*.py                              │
│   SQL: SELECT code, trade_date, factor_name, ...             │
│   → 同样混合格式进来                                         │
│   → vectorized_signal.build_target_portfolios()              │
│   → 输出target: {"600519": 0.05, "600519.SH": 0.05, ...}   │
│   → ⚠️ 如果有带后缀的因子值更高，它可能被选入Top-N           │
│     但在klines中找不到对应的价格数据（因为klines也是混合的）  │
└─────────────────────────────────────────────────────────────┘
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ 执行层                                                       │
│                                                             │
│ QMT: _to_qmt_code("600519") → "600519.SH" (加后缀)          │
│ Redis: portfolio:current 用 "600707.SH" (带后缀)             │
│ PT trade_log/signals: "600519" (无后缀)                      │
│ 前端展示: 从API拿到无后缀code，展示时不加后缀                │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 统一为带后缀格式的改动清单

**选择带后缀(`600519.SH`)的理由**:
- Tushare原生格式，减少入库转换
- QMT/Redis已经用带后缀
- 全球惯例（Bloomberg: 600519 CH, Wind: 600519.SH）

**需要改动的代码**（17处）:

| 文件 | 行 | 当前操作 | 改为 |
|------|-----|---------|------|
| fetch_base_data.py | L121 | `ts_code.split(".")[0]` | 保留原始ts_code |
| fetch_base_data.py | L295 | `ts_code.split(".")[0]` | 保留原始ts_code |
| fetch_base_data.py | L395 | `ts_code.split(".")[0]` | 保留原始ts_code |
| fetch_base_data.py | L530 | `ts_code.split(".")[0]` | 保留原始ts_code |
| tushare_fetcher.py | L184 | `df['code'].str.split('.').str[0]` | 删除此行 |
| data_loader.py | L156 | `df['code'].str.split('.').str[0]` | 删除此行 |
| qmt_execution_adapter.py | `_to_qmt_code()` | 6位→加后缀 | 如已有后缀则直接返回 |
| signal_engine.py | - | compose()输出无后缀 | 确认输出带后缀 |
| execution_ops.py | L336 | `split(".")[0]` | 删除(QMT已返回带后缀) |

**DB迁移策略**:

不建议原地UPDATE 501M行factor_values——按当前写入速度(~5M行/分钟)需要100+分钟，期间表被锁。

建议方案:
```
1. 新建 factor_values_v2 (同结构)
2. INSERT INTO factor_values_v2 SELECT 
     CASE WHEN code NOT LIKE '%.%' THEN code || 
       CASE WHEN code ~ '^6' THEN '.SH'
            WHEN code ~ '^[03]' THEN '.SZ'  
            WHEN code ~ '^[489]' THEN '.BJ' END
     ELSE code END,
     trade_date, factor_name, raw_value, neutral_value, zscore
   FROM factor_values
3. 同样处理 klines_daily, daily_basic, moneyflow_daily 等
4. RENAME TABLE 老表→_backup, 新表→正式名
5. 验证后删除_backup
```

预估: factor_values ~2小时(501M行), klines_daily ~15分钟(11.7M行), 总计~3小时。
风险: 磁盘空间需要临时翻倍(~60GB for factor_values)。D盘剩余853GB，充足。

---

## §2 完整数据流图

### 路径A: 每日增量数据

```
16:15 Task Scheduler → run_paper_trading.py signal phase

  Step0: health_check.py → health_checks表
  
  Step1: 数据拉取 (L636-L780)
    TushareFetcher._api_call_with_retry("daily", trade_date=td)
      → df (ts_code格式)
      → merge_daily_data(): strip后缀→"600519", is_st=stock_basic查询
      → data_loader.upsert_klines_daily(conn, df)
          → INSERT INTO klines_daily ON CONFLICT DO UPDATE
    TushareFetcher._api_call_with_retry("daily_basic")
      → data_loader.upsert_daily_basic(conn, df)
    (moneyflow由单独task 17:00拉取: pull_moneyflow.py → moneyflow_daily)
  
  Step1.5: 更新NAV (L780-L860)
    QMTClient → Redis portfolio:nav → performance_series表
  
  Step2: 因子计算 (L920-L938)
    compute_daily_factors(trade_date, factor_set="full", conn)
      → factor_engine._prepare_base_data() → pd.read_sql(klines+basic JOIN)
      → 计算7个kline因子(rolling) + 预处理(MAD→fill→neutralize→zscore)
      → save_daily_factors() → INSERT INTO factor_values
  
  Step3: 信号生成 (L938-L1016)
    load_factor_values(trade_date) → SELECT neutral_value FROM factor_values
    SignalService.generate_signals()
      → SignalComposer.compose(factor_df, universe, industry)
          → z-score合成 → Top-N排序 → 等权
      → 写signals表 + StreamBus发布qm:signal:generated
```

### 路径B: 因子计算完整流

```
klines_daily + daily_basic
    │ (pd.read_sql JOIN, 含120天回看)
    ▼
factor_engine._prepare_base_data()
    │ 返回: code, trade_date, open, high, low, close, volume, amount,
    │       pre_close, turnover_rate, circ_mv, sw_l1 (行业)
    ▼
滚动因子计算 (per code groupby)
    │ turnover_mean_20, volatility_20, amihud_20, reversal_20,
    │ bp_ratio, vwap_bias_1d, rsrs_raw_18, ...
    │ ⚠️ 这里用的amount单位是千元(klines_daily原始), 
    │   vwap = amount*10/volume 隐含了千元→元的转换
    ▼
逐日预处理 (_daily_preprocess)
    │ 1. 去极值: MAD 5σ winsorize
    │ 2. 填充: 行业中位数 (需要sw_l1列)
    │ 3. 中性化: 行业+ln(circ_mv) WLS回归取残差
    │ 4. z-score: (x-mean)/std, clip ±3
    ▼
factor_values表
    │ code | trade_date | factor_name | raw_value | neutral_value | zscore
    │ ⚠️ code格式取决于klines_daily的格式（混合）
```

### 路径C: 回测数据流

```
研究脚本 (scripts/research/*.py)
    │ SQL加载: factor_values + klines_daily + daily_basic
    │ ⚠️ 用COALESCE(neutral_value, raw_value) AS raw_value
    ▼
run_hybrid_backtest(factor_df, directions, price_data, config)
    │
    ├─ Phase A: vectorized_signal.build_target_portfolios()
    │   │ factor_df.pivot_table(index="code", columns="factor_name", values="raw_value")
    │   │ → z-score × direction → 等权平均 → nlargest(top_n) → 等权weight
    │   │ ⚠️ pivot用"raw_value"字段名，但实际值可能是neutral_value（取决于SQL）
    │   │ ⚠️ 无ST过滤、无停牌过滤、无流动性过滤
    │   ▼
    │   target_portfolios: {date: {code: weight}}
    │
    └─ Phase B: SimpleBacktester.run()
        │ price_data → sort → dict-based PriceIdx
        │ daily_close: groupby trade_date → {date: {code: close}}
        │ 日循环: 调仓→SimBroker填单→PMS检查→退市检测→NAV计算
        ▼
        BacktestResult (daily_nav, daily_returns, trades, ...)
```

### 路径D: PT数据流（与C的关键差异）

```
                      PT (路径D)              回测 (路径C)
─────────────────────────────────────────────────────────────
信号入口:         SignalService               vectorized_signal
                  .generate_signals()         .build_target_portfolios()

合成器:           SignalComposer.compose()     内联z-score+排序

因子值来源:       neutral_value (L51)          COALESCE(neutral,raw) AS raw_value

Universe过滤:     传入universe参数             无过滤(全量)
                  (from load_universe())

ST过滤:           无 ⚠️                        有(但是集合级非日期级) ⚠️

行业数据:         load_industry()传入          无

输出格式:         target_weights dict          target_portfolios dict

执行:             ExecutionService             SimBroker (内置)
                  → QMT真实下单                → 模拟填单

│ ⚠️ 同一策略(5因子等权Top-20)在PT和回测中可能产生不同的选股结果 │
│    因为合成逻辑、universe、ST处理全部不同                      │
```

### 路径E: QMT执行流

```
run_paper_trading.py execute phase
    │
    ├─ 读取signals表 (当天生成的信号)
    │   → target_weights: {"600519": 0.05, ...} (无后缀)
    │
    ├─ QMTClient → Redis portfolio:current (带后缀"600519.SH")
    │   → 当前持仓dict
    │   → ⚠️ 需要strip后缀才能与signals比较
    │
    ├─ 计算diff: 应买/应卖
    │
    ├─ ExecutionService.execute_rebalance()
    │   ├─ 先撤未完成订单
    │   ├─ check_circuit_breaker_sync() → L1-L4风控
    │   └─ QMT下单:
    │       qmt_execution_adapter._to_qmt_code("600519") → "600519.SH"
    │       → xtquant.place_order("600519.SH", ...)
    │
    └─ 回流: QMTClient → Redis → trade_log表(无后缀)
             ⚠️ 某处做了strip后缀写入trade_log
```

---

## §3 run_paper_trading.py完整解剖

### 3.1 结构

```
L1-100:     imports (45个) + 常量
L103-152:   工具函数 (log_step, load_today_prices, get_benchmark_close, _get_notif_service)
L154-258:   _check_opening_gap (104行) — 开盘跳空分析，unique to PT
L258-280:   _ensure_shadow_portfolio_table — DDL幂等创建
L280-390:   LightGBM影子模型函数 (_select_fold_model, _get_lgbm_scored_universe)
L390-512:   影子组合写入 (_write_shadow_portfolio, generate_shadow_lgbm_*)
L512-596:   _save_qmt_state — QMT状态快照到Redis
L596-1156:  ★ run_signal_phase (560行) — T日盘后核心
L1156-1687: ★ run_execute_phase (531行) — T+1日执行核心  
L1687-1734: main() — argparse入口
```

### 3.2 run_signal_phase内部流程 (560行)

```
Step0: 健康预检 (L618)
  └─ health_check.run_health_check()

Step1: 数据拉取 (L636-L780, 3个API并行)
  ├─ TushareFetcher.fetch_daily_data() → upsert_klines_daily
  ├─ TushareFetcher.fetch_basic_data() → upsert_daily_basic  
  └─ Tushare adj_factor → UPDATE klines_daily

Step1.5: 更新NAV (L780-L860)
  └─ QMTClient → Redis → performance_series

Step1.6: 风控评估 (L860-L887)
  └─ 日内跌幅/持仓集中度检查

Step1.7: 数据完整性预检 (L887-L920)
  └─ 价格/因子数据缺失检查

Step2: 因子计算 (L920-L938)
  ├─ compute_daily_factors(trade_date, "full")
  └─ save_daily_factors()

Step3: 信号生成 (L938-L1016)
  ├─ load_factor_values / load_universe / load_industry
  ├─ config_guard.assert_baseline_config()
  └─ SignalService.generate_signals()

Step4: LightGBM影子信号 (L1016-L1100)
  └─ generate_shadow_lgbm_signals/inertia (仅记录，不影响PT)

Step5: 通知 (L1100-L1139)
  └─ StreamBus + 钉钉通知

Step6: 收尾 (L1139-L1156)
  └─ factor_decay + log_step
```

### 3.3 run_execute_phase内部流程 (531行)

```
Step1: QMT连接 (L1185-L1250)
  ├─ qmt_manager.startup()
  ├─ 检查miniQMT进程是否在运行
  └─ 启动QMT如果没运行

Step2: 读取信号 (L1254-L1290)
  └─ SELECT FROM signals WHERE signal_date=...

Step3: 加载当日价格 (L1290-L1340)
  └─ klines_daily当日数据

Step4: 开盘跳空分析 (L1340-L1390)
  └─ _check_opening_gap()

Step5: 持仓对比+Drift修复 (L1390-L1540)
  ├─ QMTClient → 当前持仓
  ├─ 与目标持仓比较
  ├─ 计算买卖清单
  └─ ⚠️ 这段包含复杂的drift fix逻辑（200+行）

Step5.9: 熔断检查 (L1539)
  └─ check_circuit_breaker_sync()

Step6: 执行调仓 (L1561-L1610)
  ├─ exec_svc.process_pending_orders()
  └─ exec_svc.execute_rebalance()

Step7: 记录+对账 (L1610-L1670)
  ├─ UPDATE signals SET executed_at
  ├─ QMT持仓快照
  └─ 执行报告

Step8: 通知 (L1670-L1687)
```

### 3.4 unique逻辑（不在其他模块中）

| 逻辑 | 行数 | 说明 |
|------|------|------|
| _check_opening_gap | 104行 | 开盘跳空统计+对冲建议 |
| LightGBM影子模型 | 230行 | _select_fold_model + scoring + inertia |
| Drift修复 | ~200行 | QMT实际持仓vs目标的差异修复 |
| QMT进程管理 | ~60行 | 检测/启动miniQMT进程 |
| _save_qmt_state | 84行 | QMT状态序列化到Redis |
| Step1数据拉取编排 | ~150行 | 3个API并行+重试 |

### 3.5 与其他模块重叠的逻辑

| PT逻辑 | 重叠模块 | 差异 |
|--------|---------|------|
| 因子计算调用 | factor_engine | 只是调用,无重叠 |
| 信号生成 | signal_engine(PT) vs vectorized_signal(回测) | 🔴 **两条不同路径** |
| NAV更新 | backtest_engine的daily_close计算 | 不同数据源(QMT vs 模拟) |
| 风控检查 | risk_control_service | PT调sync版本 |
| 数据拉取 | fetch_base_data vs tushare_fetcher | 🔴 **两套拉取逻辑** |

### 3.6 自然拆分方案

```
run_paper_trading.py (1734行)
    ↓ 拆为
├── pt_signal_pipeline.py (~400行)
│     Step0-Step3: 健康检查→数据拉取→因子计算→信号生成
│     复用统一的data_ingestion模块
│
├── pt_execute_pipeline.py (~350行)
│     QMT连接→读信号→Drift修复→执行→对账
│     复用统一的execution模块
│
├── pt_shadow_models.py (~230行)
│     LightGBM影子信号(独立,不影响主流程)
│
├── pt_gap_analyzer.py (~104行)
│     开盘跳空分析
│
└── pt_qmt_manager.py (~80行)
      QMT进程管理+状态快照
```

---

## §4 所有入口点

### 4.1 Task Scheduler (16个任务)

| 任务 | 时间 | 脚本 | 活跃 | 说明 |
|------|------|------|------|------|
| QM-DailyBackup | 02:00 | pg_backup.py | ✅ | |
| QuantMind_DailyBackup | 02:00 | pg_backup.py | ⚠️ | 与上面重复 |
| QM-HealthCheck | 16:25 | health_check.py | ✅ | |
| QuantMind_DailySignal | 17:15 | run_paper_trading.py signal | ⚠️ | NextRun=3/25 |
| QuantMind_DailyExecute | 09:31 | run_paper_trading.py execute | ✅ | --execution-mode live |
| QuantMind_DailyMoneyflow | 17:00 | pull_moneyflow.py | ✅ | |
| QuantMind_DataQualityCheck | 16:40 | data_quality_check.py | ✅ | |
| QuantMind_FactorHealthDaily | 17:30 | factor_health_daily.py | ✅ | |
| QuantMind_DailyReconciliation | 15:40 | daily_reconciliation.py | ✅ | Session 36 PR-DRECON align |
| QuantMind_IntradayMonitor | 09:35 | intraday_monitor.py | ✅ | 每5分钟 |
| QuantMind_CancelStaleOrders | 09:05 | cancel_stale_orders.py | ✅ | |
| QuantMind_PTWatchdog | 20:00 | pt_watchdog.py | ✅ | |
| QM-LogRotate | 06:00 | log_rotate.py | ✅ | |
| QM-SmokeTest | 00:05 | smoke_test.py | ❌ Disabled | |
| QuantMind_DailyExecuteAfterData | 17:05 | run_paper_trading.py execute | ❌ Disabled | SimBroker模式 |
| QuantMind_MiniQMT_AutoStart | - | (QMT自启动) | ✅ | |

### 4.2 FastAPI Endpoints (114个)

按路由分组:
- `/api/dashboard/*` (8): summary, nav-series, alerts, monthly-returns, ...
- `/api/portfolio/*` (4): holdings, daily-pnl, sector-distribution, ...
- `/api/factors/*` (5): health, correlation, stats, summary, ...
- `/api/backtest/*` (4): run, history, compare, ...
- `/api/execution/*` (4): pending-orders, log, algo-config, ...
- `/api/execution-ops/*` (15): positions, orders, drift, fix-drift, cancel, emergency, ...
- `/api/risk/*` (9): state, history, overview, limits, stress-tests, ...
- `/api/paper-trading/*` (5): status, graduation, positions, ...
- `/api/pms/*` (5): positions, history, config, check, ...
- `/api/system/*` (5): health, datasources, scheduler, streams, ...
- `/api/mining/*` (4): run, tasks, evaluate, ...
- `/api/approval/*` (5): queue, approve, reject, hold, history
- `/api/report/*` (3): list, quick-stats, generate
- `/api/market/*` (3): indices, sectors, ...
- `/api/health/*` (2): checks, qmt
- `/api/realtime/*` (2): portfolio, market
- `/api/params/*` (2): changelog, init-defaults
- `/api/notifications/*` (1)
- `/api/remote-status/*` (2): ping, status

### 4.3 活跃scripts (25个)

核心PT链路: run_paper_trading.py, run_backtest.py, health_check.py
QMT: qmt_data_service.py, cancel_stale_orders.py
监控: intraday_monitor.py, pt_watchdog.py, daily_reconciliation.py
因子: factor_health_daily.py, monitor_factor_ic.py, precompute_cache.py
数据: pull_moneyflow.py, data_quality_check.py
运维: pg_backup.py, log_rotate.py, smoke_test.py, approve_l4.py
评估: check_graduation.py, pt_graduation_assessment.py, paper_trading_stats.py
其他: setup_paper_trading.py, run_gp_pipeline.py, bayesian_slippage_calibration.py, disaster_recovery_verify.py

### 4.4 Celery Tasks

定义在`backend/app/tasks/`但**CeleryBeat已停**:
- `onboarding_tasks.py`: `onboard_factor` — 因子入库pipeline
- `mining_tasks.py`: `run_gp_pipeline` — GP挖掘
- `daily_pipeline.py`: 各种定时task(但实际调度已转Task Scheduler)

---

## §5 模块耦合度

### 5.1 engines/依赖图

```
                    ┌─────────────────────────────────────┐
                    │         backtest_engine (1352L)      │
                    │  SimBroker + SimpleBacktester + run_ │
                    └───┬───┬───┬───┬───┬───┬─────────────┘
                        │   │   │   │   │   │
        ┌───────────────┘   │   │   │   │   └──────────┐
        ▼                   ▼   │   ▼   ▼              ▼
   base_broker          datafeed│ metrics  slippage   vectorized_
   (87L)                (307L)  │ (865L)   _model      signal
     ▲  ▲                      │          (382L)      (145L)
     │  │                      ▼
     │  └── paper_broker  base_strategy ◄── modifiers/base
     │      (634L) [DB]   (238L) [DB]       (170L)
     │                         ▲    ▲
     └── broker_qmt            │    └── modifiers/regime_modifier [DB]
         (564L) [IO]           │    └── modifiers/northbound_modifier [DB]
                               │
                          signal_engine ◄── config_guard [IO]
                          (440L) [DB]

   ─── 独立模块(无engine内部依赖) ───
   factor_engine (1899L) [DB]    ← 最大单文件,直接做DB IO
   ml_engine (1400L) [DB]
   qmt_execution_adapter (728L) [DB]  
   factor_profiler (1135L) [DB]
   mining/* (7个文件, 5600+L)
   + 20个其他独立模块
```

### 5.2 Hub模块（被最多引用）

| 模块 | 被引用次数 | 说明 |
|------|-----------|------|
| base_strategy | 5 | Modifier系统的基类 |
| backtest_engine | 5 | 核心回测(但只被研究脚本引用,不被其他engine引用) |
| base_broker | 3 | Broker继承链根 |
| signal_engine | 3 | PT信号合成 |

### 5.3 Engine层IO违规（应为纯计算但做了DB/IO）

| 模块 | 违规类型 | 说明 |
|------|---------|------|
| factor_engine | DB read+write | `_prepare_base_data`直接pd.read_sql, `save_daily_factors`直接INSERT |
| base_strategy | DB read | StrategyContext接受conn参数 |
| signal_engine | DB read | 读settings/config |
| factor_profiler | DB read+write | 直接查DB生成画像 |
| fast_neutralize | DB read+write | 读factor_values写Parquet |
| factor_gate | DB read | 读factor_ic_history |
| modifiers/* | DB read | 读index_daily/northbound_holdings |
| ml_engine | DB read | 读factor_values |
| paper_broker | DB write | 写trade_log |
| mining/pipeline_orchestrator | DB read+write | 全链路编排 |

> **53个engine模块中23个有DB/IO操作(43%)**——"Engine层纯计算无IO"原则事实上不成立。

---

## §6 好的设计（安全区）

### ✅ 经过验证，重构中应保留的

**1. 三因素滑点模型 (slippage_model.py, 382行)**
- spread + volume_impact(Bouchaud) + overnight_gap 三因素分离
- 参数来自Phase 1加固5层验证
- SlippageConfig可配置、可测试
- **保留原因**: 经过实盘H0校准设计(虽然H0还未完成)，逻辑清晰

**2. 因子预处理4步流程 (factor_engine.py `_daily_preprocess`)**
- MAD 5σ去极值 → 行业中位数填充 → 行业+市值WLS中性化 → z-score clip ±3
- 顺序固定且有铁律保护（CLAUDE.md明确定义不可变）
- **保留原因**: 因子研究的基石，数十次IC验证依赖此流程

**3. ValidatorChain (backtest_engine.py)**
- 可组合验证器(Suspension/DataCompleteness/PriceLimit)
- 每个验证器返回(pass, reason)，拒绝原因可追溯
- **保留原因**: 设计合理，刚实现，测试覆盖

**4. BacktestResult + metrics()**
- 一行调用生成20+指标(Sharpe/MDD/DSR/Sortino/子期间等)
- **保留原因**: Phase 2刚完成，经过验证

**5. PMS阶梯利润保护 (backtest_engine.py内)**
- 3层: L1(30%/15%) / L2(20%/12%) / L3(10%/10%)
- .env可配置
- **保留原因**: G2研究验证有效(Sharpe+0.06~0.24)

**6. adj_factor PIT安全 (已验证)**
- DB中存储的是拉取时的历史值，非最新值
- **保留原因**: 复权正确性的基础

**7. Modifier链架构 (modifiers/base.py + regime_modifier + northbound_modifier)**
- ModifierBase → should_trigger → compute_adjustments → 返回adjustment_factors
- 可组合、可测试
- **保留原因**: 架构clean，双层Modifier验证Sharpe+0.27

### ⚠️ 逻辑正确但实现有问题

**SimBroker成本模型**: 逻辑正确(佣金min 5元+历史印花税+过户费+三因素滑点)，但volume单位注释说"股"实际是"手"，slippage_model文档说"股"。碰巧正确(volume_impact只用amount不用volume)，但脆弱。

**退市检测**: 逻辑合理(20天无数据→清算)，但20天阈值太短(长期停牌6个月)。

---

## §7 废弃代码

| 路径 | 状态 | 证据 |
|------|------|------|
| `backend/wrappers/quantstats_wrapper.py` | 🗑️ 废弃 | 仅test文件引用,无生产调用 |
| `backend/wrappers/ta_wrapper.py` | 🗑️ 废弃 | 仅test文件引用,无生产调用 |
| `backend/services/notification_service.py` | 🗑️ 废弃 | 文件自己标注DEPRECATED,转发到app/services/ |
| `backend/engines/event_backtest_engine.py` | ❓ 不确定 | 无引用,可能是GA2 EVENT回测器(已完成研究) |
| `backend/engines/beta_hedge.py` | ❓ 不确定 | 无引用,可能是预留 |
| `backend/engines/attribution.py` | ❓ 不确定 | 无引用,FF3归因独立模块 |
| `backend/engines/pbo.py` | ❓ 不确定 | Probability of Backtest Overfitting,无引用 |
| `backend/engines/portfolio_aggregator.py` | ❓ 不确定 | 无引用 |
| `backend/engines/pre_trade_validator.py` | ❓ 不确定 | 无引用(被ValidatorChain替代?) |
| `backend/engines/walk_forward.py` | ❓ 不确定 | 无引用(G1 LightGBM用过?) |
| `models/*.csv` | 🗑️ 研究产出 | Alpha158研究结果,非可执行模型 |
| `models/*.txt` | 🗑️ 研究产出 | 股票列表,已在DB中 |

---

## §8 配置散落

### 8.1 配置来源清单

| 来源 | 参数数 | 例子 |
|------|--------|------|
| `.env` | 18 | DATABASE_URL, PT_TOP_N=20, EXECUTION_MODE |
| `BacktestConfig` defaults | 15 | commission_rate=0.0000854, top_n=20 |
| `signal_engine.PAPER_TRADING_CONFIG` | ~8 | top_n=settings.PT_TOP_N |
| `run_backtest.py` argparse | ~10 | --top-n, --rebalance-freq |
| `config_guard.py` | ~10 | assert因子列表/方向一致性 |
| `SlippageConfig` defaults | 6 | spread_bps=3.0, impact_coeff=0.1 |
| `PMSConfig` defaults | 7 | enabled=False(但.env覆盖为True) |

### 8.2 已知矛盾

| 参数 | 位置A | 位置B | 矛盾 |
|------|-------|-------|------|
| `rebalance_freq` | BacktestConfig默认"biweekly" | PT实际"monthly" | ⚠️ 回测默认双周但PT月度 |
| `top_n` | BacktestConfig默认20 | signal_engine从settings读 | 一致(都是20) ✅ |
| `pms.enabled` | PMSConfig默认False | .env覆盖True | 需要显式配置,不算矛盾 |

> `rebalance_freq`矛盾是最危险的: 如果研究脚本不显式传"monthly"，默认跑的是双周调仓，与PT不一致。

---

## §9 架构建议

### 9.1 推荐的重构顺序

我认为你提出的"code统一→数据管道→引擎拆分→性能→文档"基本正确，但有一个关键调整:

**第0步应该是"统一信号路径"，而不是code格式。**

理由: code格式是数据问题，修了之后回测结果仍然不可信——因为PT和回测走的是两条不同的信号路径。即使code统一了，两条路径产生的选股结果仍然不同。**信号路径统一**才是"回测结果可指导生产"的前提。

**推荐顺序:**

```
Phase 0: 信号路径唯一化 (1-2天)
  └─ 让PT也用vectorized_signal.build_target_portfolios()
     或让回测也用SignalComposer.compose()
     选一个,灭另一个。

Phase 1: code格式统一 (1天代码 + 3小时迁移)
  └─ 统一为带后缀 → 17处代码改动 → DB迁移

Phase 2: 数据管道重建 (2-3天)
  ├─ 合并TushareClient+TushareFetcher为统一入口
  ├─ 新建DataCleaner统一清洗
  ├─ 建st_history表替代is_st列
  └─ 显式单位元数据替代启发式

Phase 3: 引擎拆分 (2-3天)
  ├─ backtest_engine.py拆为5个文件
  ├─ run_paper_trading.py拆为5个文件
  └─ Engine层去IO(至少factor_engine)

Phase 4: 性能 (1-2天)
  ├─ 分块回测(按年)
  ├─ Parquet缓存重建(12年)
  └─ float32存储

Phase 5: 文档对齐 + 回归测试 (1天)
```

### 9.2 更简单的解法

**信号路径统一**: 不需要大重构。最简单的修法是让`SignalService.generate_signals()`内部调用`build_target_portfolios()`而不是`SignalComposer.compose()`。大约改20行代码。然后`SignalComposer`变成legacy可以慢慢废弃。

**12年回测OOM**: 不需要引擎重写。最简单的修法是在SQL层加`WHERE code LIKE '%.SH' OR code LIKE '%.SZ'`排除BJ（如之前验证的那样能跑通）。code统一后这个问题自然解决(BJ股有自己的后缀可以过滤)。长期的分块回测是Phase 4。

**DataFeed.from_database()**: 这个方法从未在生产中使用过。研究脚本都直接写SQL加载数据。修复它不如直接废弃它,用统一的`DataLoader.load_backtest_data(start, end)`替代。

### 9.3 牵一发动全身的改动

1. **code格式统一**: 改了code格式后所有Parquet缓存失效(cache/目录全部需要重建)。所有SQL hardcoded的code字符串(如CSI300成分股查询中的index_code='000300.SH')需要检查。

2. **拆分backtest_engine.py**: SimBroker内部依赖的闭包变量(pms_state, _delist_count, _price_dict, daily_close)是拆分的主要障碍。这些状态目前活在`run()`方法内部,拆分需要显式传递。

3. **信号路径统一**: 如果废弃SignalComposer改用vectorized_signal,需要确认两者的z-score计算完全一致(包括clip范围、NaN处理、排序稳定性)。建议先写一个比较脚本验证两者输出是否完全相同。

### 9.4 你的方案中我认为的问题

1. **"加新因子只需写一个文件注册即可"** — 当前factor_engine.py的因子定义是Python lambda dict(PHASE0_CORE_FACTORS等)。改成文件注册需要重新设计因子注册机制(类似Qlib的yaml配置或Python装饰器模式)。这不是1-2天能完成的，建议作为独立Phase。

2. **"12年回测<2分钟"** — 以当前数据量(11M行price_data)和dict-based执行模型,2分钟很挑战。Qlib用Cython+bin文件能做到,但我们用Python+SQL+Pandas很难。建议目标放宽到"5分钟无OOM"更现实。

3. **"PT和回测走完全相同的信号+执行路径"** — 信号路径统一是对的。但**执行路径**不可能完全相同:PT用QMT真实下单,回测用SimBroker模拟。应该是"信号完全相同,执行接口相同(BaseExecutor),实现不同"。

### 9.5 我发现的你没问的问题

1. **minute_bars的ts_code列与其他表code列不一致** — 不是简单的带/不带后缀问题。minute_bars的ts_code格式可能是Baostock格式(如`sh.600519`)而非Tushare格式(`600519.SH`)。统一code格式时这张1.4亿行的表也需要处理。

2. **factor_values 501M行中可能有重复** — 同一只股票的无后缀版和有后缀版各有一份因子值。code统一后需要去重(保留一份)。

3. **CeleryBeat停止意味着PMS不工作** — 如果PT还在live运行,这是一个**当前正在发生的生产风险**——持仓没有利润保护。

4. **backtest_engine.py中BacktestConfig.rebalance_freq默认"biweekly"** — 但CLAUDE.md和所有PT配置都说"monthly"。如果有研究脚本忘了显式传monthly,它的回测结果就是双周调仓的——与PT不可比。

---

*报告完毕。所有结论基于实际代码追踪,未修改任何代码或数据。*
*发现设计文档说A但代码做B的地方已标注⚠️。*
