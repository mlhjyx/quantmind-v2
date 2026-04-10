# CLAUDE.md — QuantMind V2

> **Claude Code 入口文件。启动时自动读取。只含编码必需信息。**
> **系统现状**: SYSTEM_STATUS.md（环境/数据库/代码/架构全景）

---

## 项目概述

QuantMind V2: 个人A股+外汇量化交易系统，Python-first 全栈。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **当前**: Phase A-F完成, v3.8路线图, Step 0→6-H重构+研究完成, PT已暂停+已清仓(2026-04-10, 等V4 Phase 2验证后重启), Sharpe基线=**5yr 0.6095 (regression_test.py) / 12yr 0.5309 / SN b=0.50 inner 0.68 / SN WF OOS 0.6521**
- **硬件**: Windows 11 Pro, R9-9900X3D, RTX 5070 12GB(PyTorch cu128), 32GB DDR5
- **PMS**: v1.0阶梯利润保护3层(14:30 Celery Beat检查, v2.0已验证无效不实施)
- **下一步(V4路线图)**: ~~Phase 1.1~~ ✅完成(841s→14.6s) → ~~Phase 1.2~~ ✅完成(Alpha158六因子+行业动量+北向V2+PEAD+SW1中性化迁移) → **Phase 2 信号框架**(融合E2E主攻: LightGBM预测层+Portfolio Network权重层 + IC加权/MVO baseline) → Phase 3 自动化(因子生命周期+Rolling WF) → Phase 4 PT重启
- **调度链路**: 16:15数据拉取 → 16:25预检 → 16:30因子+信号 → 17:00-17:30收尾(moneyflow/巡检/衰减) → T+1 09:31执行 → 15:10对账

## 技术栈（实际使用，非设计文档）

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + **sync psycopg2** + Celery + Redis |
| 前端 | React 18 + TypeScript + Tailwind 4.1 + ECharts/Recharts + Zustand |
| 数据库 | PostgreSQL 16.8 + TimescaleDB 2.26.0 (D:\pgsql, D:\pgdata16, user=xin, db=quantmind_v2) + Redis 5.0.14.1 |
| 事件总线 | Redis Streams (`qm:{domain}:{event_type}`), StreamBus模块 |
| 服务管理 | Servy v7.6 (`D:\tools\Servy`), 替代NSSM |
| 调度 | Windows Task Scheduler (PT) + Celery Beat (GP) |
| GPU | PyTorch cu128, RTX 5070 12GB (cupy不支持Blackwell sm_120) |
| 缓存 | 本地Parquet快照(backend/data/parquet_cache.py按年分区), factor_values 501M行→TimescaleDB hypertable |
| 交易 | 国金miniQMT (A股) |
| Portfolio优化 | riskfolio-lib 7.2.1 (MVO/RP/BL, 阶段2评估) |
| 向量化回测 | vectorbt 0.28.5 (Numba加速, 待评估快速筛选用) |

## 因子系统

### 因子池状态
| 池 | 数量 | 说明 |
|----|------|------|
| CORE (Active, PT在用) | 5 | turnover_mean_20, volatility_20, reversal_20(WARNING), amihud_20, bp_ratio |
| PASS候选 | 32 | FACTOR_TEST_REGISTRY.md中PASS状态因子(含Alpha158六+PEAD-SUE)，待评估入池 |
| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非9.1%, v3.4证伪) |
| DEPRECATED | 5 | momentum_5/momentum_10/momentum_60/volatility_60/turnover_std_20 |
| 北向个股RANKING | 15 | nb_ratio_change_5d等, IC反向(direction=-1), G1特征池 |
| LGBM特征集 | 63 | 全部factor_values因子(48核心+15北向, DB自动发现) |

### 因子存储
- **factor_values**: 501M行(12年扩展后), TimescaleDB hypertable ~53GB
- **factor_ic_history**: IC唯一入库点(铁律11), 未入库IC视为不存在
- **Parquet缓存**: `_load_shared_data` 30min→1.6s(1000x), `fast_neutralize_batch` 15因子/17.5min
- **minute_bars**: 139M行(Step 6-B已统一code格式), 5年(2021-2025), Baostock 5分钟K线, 2537只股票(0/3/6开头, 无BJ)

### 因子评估流程
1. 经济机制假设(铁律13/14) → 2. IC计算+入库(铁律11) → 3. 画像(factor_profiler, 5维) → 4. 模板匹配(T1-T15) → 5. Gate G1-G8+BH-FDR → 6. 回测验证(paired bootstrap p<0.05)

## 架构分层（DEV_BACKEND §3.1）

```
Router(api/) → Service(services/) → Engine(engines/) + DB
  Router: 参数验证+调用Service+返回Response, 不含业务逻辑
  Service: 所有业务逻辑, 内部不commit, sync psycopg2
  Engine: 纯计算(无IO无DB), 输入/输出DataFrame/dict
```

## 目录结构

```
quantmind-v2/
├── CLAUDE.md                    ← 本文件
├── SYSTEM_STATUS.md             ← ⭐ 系统现状全景（重构前体检产出）
├── LESSONS_LEARNED.md           ← 经验教训（49条, LL-001~052）
├── FACTOR_TEST_REGISTRY.md      ← 因子测试注册表（74条）
├── docs/
│   ├── QUANTMIND_V2_DDL_FINAL.sql  ← ⭐ 建表来源（DDL 45张+代码动态建表17张=DB实际62张）
│   ├── QUANTMIND_V2_DESIGN_V5.md   ← ⚠️历史设计(被ROADMAP_V3替代，仅局部参考)
│   ├── IMPLEMENTATION_MASTER.md    ← 已归档至docs/archive/
│   ├── archive/TEAM_CHARTER_V3.3.md ← 团队运营参考（已归档）
│   ├── DEV_BACKEND.md              ← 后端设计(分层/数据流/协同矩阵)
│   ├── DEV_BACKTEST_ENGINE.md      ← 回测引擎(Hybrid架构/34项决策)
│   ├── DEV_FACTOR_MINING.md        ← 因子计算(预处理/IC定义)
│   ├── DEV_FRONTEND_UI.md          ← 前端设计
│   ├── DEV_SCHEDULER.md            ← 调度设计(A股T1-T17/外汇FX1-FX11)
│   ├── DEV_PARAM_CONFIG.md         ← 参数配置(220+可配置参数)
│   ├── DEV_AI_EVOLUTION.md         ← AI闭环设计(4Agent+Pipeline)
│   ├── GP_CLOSED_LOOP_DESIGN.md    ← GP最小闭环(FactorDSL+WarmStart)
│   ├── RISK_CONTROL_SERVICE_DESIGN.md ← 风控(L1-L4状态机)
│   └── TUSHARE_DATA_SOURCE_CHECKLIST.md ← ⭐ 数据源接入必读
├── backend/
│   └── app/
│       ├── main.py              # FastAPI入口
│       ├── config.py            # pydantic-settings
│       ├── api/                 # API路由
│       ├── core/                # 核心基础设施
│       │   └── stream_bus.py    # Redis Streams统一数据总线
│       ├── services/            # ⭐ 业务逻辑层（sync）
│       │   ├── signal_service.py
│       │   ├── execution_service.py
│       │   ├── risk_control_service.py
│       │   ├── factor_onboarding.py  # 因子入库pipeline
│       │   ├── config_loader.py      # ⭐ Step 4-B: YAML策略配置加载
│       │   ├── pt_data_service.py    # ⭐ Step 6-A: PT并行数据拉取
│       │   ├── pt_monitor_service.py # ⭐ Step 6-A: PT开盘跳空检测
│       │   ├── pt_qmt_state.py       # ⭐ Step 6-A: QMT↔DB状态同步
│       │   ├── shadow_portfolio.py   # ⭐ Step 6-A: LightGBM影子选股
│       │   ├── db.py                 # sync psycopg2连接器
│       │   └── trading_calendar.py   # 交易日工具
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic请求/响应
│       ├── tasks/               # Celery任务
│       │   ├── celery_app (或 __init__.py)
│       │   ├── mining_tasks.py  # GP挖掘Celery封装
│       │   └── beat_schedule.py # 定时调度配置
│       └── data_fetcher/        # 数据拉取
│           ├── contracts.py     # ⭐ Step 3-A: Data Contract (10张表schema+单位)
│           ├── pipeline.py      # ⭐ Step 3-A: DataPipeline统一入库管道(铁律17)
│           ├── tushare_fetcher.py
│           ├── tushare_client.py
│           └── data_loader.py
├── backend/data/                # ⭐ Step 5新增: Data层(本地缓存/快照, 无业务逻辑)
│   └── parquet_cache.py         # BacktestDataCache 按年分区Parquet缓存
├── backend/engines/             # ⭐ 核心计算引擎（纯计算无IO）
│   ├── factor_engine.py         # 因子计算
│   ├── factor_profiler.py       # 因子画像V2（48+15因子, 12章节报告）
│   ├── fast_neutralize.py       # 批量中性化（Parquet写入, 17.5min/15因子）
│   ├── backtest/                # ⭐ Step 4-A: 回测引擎8模块拆分
│   │   ├── engine.py            #   核心事件循环(562行)
│   │   ├── runner.py            #   run_hybrid_backtest/run_composite_backtest入口(281行)
│   │   ├── broker.py            #   成本模型+SimBroker(309行)
│   │   ├── validators.py        #   涨跌停/停牌/完整性过滤链(105行)
│   │   ├── executor.py          #   事件执行器(81行)
│   │   ├── types.py             #   BacktestResult/Fill/Order数据类(92行)
│   │   └── config.py            #   BacktestConfig(49行)
│   ├── config_guard.py          # 基线配置断言(PT启动前检查)
│   ├── slippage_model.py        # 三因素滑点模型(R4研究)
│   ├── neutralizer.py           # FactorNeutralizer共享模块
│   └── mining/                  # GP因子挖掘子包
│       ├── gp_engine.py         # GP引擎(DEAP+WarmStart+岛屿模型)
│       ├── pipeline_utils.py    # GP管道公开函数
│       ├── factor_dsl.py        # FactorDSL算子集
│       └── pipeline_orchestrator.py  # 闭环编排(部分实现)
├── configs/                     # ⭐ Step 4-B新增: YAML配置
│   ├── pt_live.yaml             # PT生产配置(5因子等权Top-20月度+PMS v1.0)
│   ├── backtest_12yr.yaml       # 12年基线回测
│   └── backtest_5yr.yaml        # 5年回测(历史基线比对用)
├── frontend/src/                # React前端
│   ├── api/                     # API调用层
│   ├── pages/                   # 35个页面
│   ├── components/              # 53个共享组件
│   └── store/                   # Zustand 4个store
├── scripts/
│   ├── run_paper_trading.py     # ⭐ PT主脚本(345行编排器, Step 6-A拆分后)
│   ├── run_backtest.py          # ⭐ 回测脚本(345行, Step 4-B改造为YAML驱动: --config configs/pt_live.yaml)
│   ├── fetch_minute_bars.py     # ⭐ Step 6-B: Baostock 5分钟拉取(走DataPipeline)
│   ├── build_backtest_cache.py  # Step 5: 构建Parquet缓存
│   ├── qmt_data_service.py      # QMT数据同步→Redis(Servy常驻)
│   ├── health_check.py          # 盘前健康检查
│   ├── monitor_factor_ic.py     # 因子IC监控
│   ├── pt_watchdog.py           # PT心跳监控
│   ├── pg_backup.py             # 数据库备份
│   ├── data_quality_check.py    # 数据巡检
│   ├── approve_l4.py            # L4熔断恢复CLI(紧急)
│   ├── cancel_stale_orders.py   # QMT紧急撤单(紧急)
│   ├── archive/                 # 131个归档脚本(审计完成, README.md有说明)
│   └── research/                # 研究脚本(验证/回测实验)
├── cache/                       # Parquet缓存（profiler/中性化用）
├── docs/research-kb/            # 研究知识库（failed/findings/decisions）
├── .claude/skills/              # 7个自定义skills(factor-discovery/research/overnight/db-safety/performance/research-kb/omc-reference)
└── backend/tests/               # 2076+个测试（90个test文件）
```

## 编码规则（强制）

### Python
- 类型注解 + Google style docstring（中文）
- **sync psycopg2**, Service内部不commit, 调用方管理事务
- Engine层 = 纯计算, 无IO, 无数据库访问
- 金融金额用 `Decimal`
- 提交前: `ruff check` + `ruff format`
- 测试: `pytest`

### React/TypeScript
- 函数组件 + Hooks
- API调用统一通过 `src/api/` 层，**必须做响应格式转换**（LL-035）
- 新组件必须 `?.` null-safe 防御
- 状态管理: Zustand, 异步请求: @tanstack/react-query

### xtquant/miniQMT 规则（清明改造后）

- **唯一允许 `import xtquant` 的生产入口**: `scripts/qmt_data_service.py`（QMT Data Service独立进程）
- **其他模块读QMT数据**: 通过 `QMTClient` (`app/core/qmt_client.py`) 从Redis缓存读取，**不直接import xtquant**
- **路径管理**: 统一使用 `app/core/xtquant_path.py` 的 `ensure_xtquant_path()`
- **降级路径**: QMTClient读Redis超时时可降级直连xtquant（应急通道）
- xtquant安装在 `.venv/Lib/site-packages/Lib/site-packages`，用 `append` 不是 `insert`

### Redis Streams 数据总线规则

- 命名规范: `qm:{domain}:{event_type}`（如 `qm:signal:generated`）
- 发布: `from app.core.stream_bus import get_stream_bus; bus.publish_sync(stream, data, source="module_name")`
- publish失败不阻塞主流程（try/except包裹）
- maxlen=10000，防止Stream无限增长
- 调试: `redis-cli XRANGE qm:signal:generated - + COUNT 5`
- 管理端点: `GET /api/system/streams`

### PMS 阶梯利润保护规则

- 14:30 Celery Beat执行检查（非交易日自动跳过）
- 三层保护: L1(浮盈>30%+回撤>15%), L2(>20%+>12%), L3(>10%+>10%)
- 配置在.env: `PMS_ENABLED`, `PMS_LEVEL{1,2,3}_GAIN`, `PMS_LEVEL{1,2,3}_DRAWDOWN`
- PMS卖出后自动更新`position_snapshot`，确保信号生成看到最新持仓
- 触发记录写`position_monitor`表，通过StreamBus广播`qm:pms:protection_triggered`
- 前端页面: `/pms`

### 部署规则（Servy服务管理）
- **服务管理工具**: Servy v7.6 (`D:\tools\Servy\servy-cli.exe`)，替代NSSM（2026-04-04迁移）
- 后端代码修改后重启: `powershell -File scripts\service_manager.ps1 restart fastapi`
- 重启所有服务: `powershell -File scripts\service_manager.ps1 restart all`
- 查看服务状态: `powershell -File scripts\service_manager.ps1 status`
- 前端代码修改后: `npm run build`（生产模式）或确认dev server自动热更新
- 开发调试时可手动启动: `cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- 调试前需先停止Servy服务: `D:\tools\Servy\servy-cli.exe stop --name="QuantMind-FastAPI"`，避免端口冲突
- **Celery Worker graceful shutdown需要30秒，不要强制kill**

#### Servy管理的服务（启动顺序）
| 服务名 | 描述 | 依赖 | 日志 |
|--------|------|------|------|
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 | Redis, PostgreSQL 16.8 | logs/fastapi-std{out,err}.log |
| QuantMind-Celery | celery worker --pool=solo | Redis | logs/celery-std{out,err}.log |
| QuantMind-CeleryBeat | celery beat scheduler | Redis, QuantMind-Celery | logs/celery-beat-std{out,err}.log |
| QuantMind-QMTData | QMT数据同步→Redis缓存(60s) | Redis | logs/qmt-data-std{out,err}.log |

#### QMT数据架构（A-lite方案, 2026-04-04）
- **QMT Data Service** (`scripts/qmt_data_service.py`): 独立常驻进程，唯一允许 `import xtquant` 的生产入口
- 每60秒同步: 持仓→`portfolio:current` (Hash), 资产→`portfolio:nav` (JSON), 价格→`market:latest:{code}` (TTL=90s)
- 其他模块通过 `QMTClient` (`app/core/qmt_client.py`) 读取Redis缓存，**不直接import xtquant**
- xtquant路径统一管理: `app/core/xtquant_path.py` 的 `ensure_xtquant_path()`
- 连接状态通过StreamBus广播 `qm:qmt:status`

#### PT核心参数（.env驱动）
- `PT_TOP_N`: 选股数量（默认20, 改后重启服务生效）
- `PT_INDUSTRY_CAP`: 行业上限（默认1.0=不限, 改后重启服务生效）
- 读取路径: `.env` → `config.py:Settings` → `signal_engine.py:PAPER_TRADING_CONFIG`
- config_guard验证因子列表一致性（不验证top_n/industry_cap，因为是可配置的）

#### 回滚到NSSM（紧急）
NSSM配置备份在 `config/nssm-backup/`，包含注册表导出文件(.reg)和审计文档。

### 并发限制（32GB内存硬约束，2026-04-03 OOM事件）
- **最多同时运行2个**加载全量价格数据的Python进程
- 每个进程估计占用3-4GB内存（加载7M行price_data）
- PG shared_buffers=2GB是固定开销
- 违反此规则会导致PG OOM崩溃（Windows error 1455 + postgres.exe 0xc0000409）
- 因子计算、回测等重数据任务必须串行或最多2并发
- 轻量任务（API测试、IC计算等<500MB）不受此限制
- PG安装路径: `D:\pgsql\bin\pg_ctl.exe`, 数据目录: `D:\pgdata16`, db=quantmind_v2

### SQL
- SQLAlchemy text() 中用 `CAST(:param AS type)`，**禁止** `::type` 语法（LL-034）
- 所有 (symbol_id, date) 组合必须有联合索引
- 金额字段列注释标明单位

### 研究任务资源调度
- 启动前检查: `tasklist | grep python` + `nvidia-smi` (Windows)
- CPU密集(回测/IC): RAM可用<8GB时不启动新重型任务
- GPU任务(LightGBM/PyTorch): VRAM可用<4GB时不启动
- DB密集(大表SELECT): 同时最多1个(PG连接池限制)
- 32GB机器禁止同时跑两个>4GB的Python进程
- 铁律9: 重数据max 2并发

---

## 铁律（违反即停）

### 工作原则类
1. **不靠猜测做技术判断** — 外部API/数据接口必须先读官方文档确认
2. **下结论前验代码** — grep/read代码验证，不信文档不信记忆（LL-019）
3. **不自行决定范围外改动** — 先报告建议和理由，等确认后再执行

### 因子研究类
4. **因子验证用生产基线+中性化** — raw IC和neutralized IC并列展示，衰减>50%标记虚假alpha（LL-013/014）
5. **因子入组合前回测验证** — paired bootstrap p<0.05 vs 基线，不是只看Sharpe数字（LL-017）
6. **因子评估前确定匹配策略** — RANKING→月度，FAST_RANKING→周度，EVENT→触发式，不能用错框架评估（LL-027）

### 数据与回测类
7. **IC/回测前确认数据地基** — universe与回测对齐+无前瞻偏差+数据质量检查（IC偏差教训）
8. **ML实验必须OOS验证** — 训练/验证/测试三段分离，OOS Sharpe < 基线不上线（DSR教训）

### 系统安全类
9. **重数据任务串行执行** — 最多2个重数据Python进程并发，违反→PG OOM崩溃（2026-04-03事件）
10. **基础设施改动后全链路验证** — PASS才能上线，不跳过验证直接部署（清明改造教训）
11. **IC必须有可追溯的入库记录** — factor_ic_history表无记录的IC视为不存在，不可用于决策（mf_divergence"IC=9.1%"实为-2.27%教训）

### 因子质量类
12. **新颖性可证明性（G9 Gate）** — 新候选因子与现有因子AST相似度>0.7直接拒绝，不进入IC评估。未经新颖性验证的因子视为变体（AlphaAgent KDD 2025：无此Gate有效因子比例低81%）
    > 补充: 相似因子不是新因子。GP/LLM产出的候选因子IC计算前必须先过G9 Gate，48个量价因子的窗口变体不算新因子。
13. **市场逻辑可解释性（G10 Gate）** — 新因子注册必须附带经济机制描述「[市场行为]→[因子信号]→[预测方向]」。IC显著不是充分理由，无法解释预测力来源的因子不允许进入Active池（reversal_20在momentum regime下反转的教训）
    > 补充: 新因子必须有可解释的市场逻辑假设, 不接受"IC显著就行"。经济机制假设必须与因子表达式语义对齐。

### 重构原则类（Step 6-B, 2026-04-09）
14. **回测引擎不做数据清洗** — 数据必须在入库时通过 DataPipeline 验证和标准化。回测引擎不猜单位、不推断ST、不计算adj_close。DataFeed 提供什么就用什么。违反→数据契约被冲破，回测不可复现。
15. **任何回测结果必须可复现** — 每次回测必须记录 `(config_yaml_hash, git_commit)` 到 backtest_run 表。`regression_test.py` 能验证同一输入产出完全相同的 NAV (max_diff=0)。违反→策略迭代失去基准比对能力。
16. **信号路径唯一** — 所有回测/研究/PT 必须走 `SignalComposer → PortfolioBuilder → BacktestEngine`。禁止编写独立的简化信号生成或回测框架。违反→PT 与回测结果不一致(原历史问题: `load_factor_values`/`vectorized_signal` 各读各的字段)。
17. **数据入库必须通过 DataPipeline** — 禁止直接 `INSERT INTO` 生产表。`DataPipeline.ingest(df, Contract)` 负责 rename → 列对齐 → 单位转换 → 值域验证 → FK 过滤 → Upsert。违反→重新引入单位混乱/code 格式不一致等历史技术债。

### 成本对齐
18. **回测成本实现必须与实盘对齐** — 新策略正式评估前必须确认H0验证通过（理论成本vs QMT实盘误差<5bps）

### IC 口径统一（Step 6-E, 2026-04-09）
19. **IC 定义全项目统一** — 所有 IC 计算必须走 `backend/engines/ic_calculator.py` 共享模块:
    - 因子值: `neutral_value` (MAD → fill → WLS 行业+ln市值 → zscore → clip±3)
    - 前瞻收益: T+1 买入到 T+horizon 卖出的**超额收益** (相对 CSI300)
    - IC 类型: Spearman Rank IC
    - Universe: 排除 ST/BJ/停牌/新股 (调用方负责 filter)
    - 标识符: `neutral_value_T1_excess_spearman` (version 1.0.0)

    **raw_value 的 IC 只作参考对比, 不作入池/淘汰依据**。未经 `ic_calculator` 计算的 IC 数字视为不可追溯, 不允许写入 factor_ic_history / factor_profile / factor_registry 作决策依据。违反→口径漂移 (IVOL 在 registry 写+0.067, 实测 -0.103 反向) 重新出现。

### 因子噪声鲁棒性（Step 6-F, 2026-04-10）
20. **因子噪声鲁棒性 G_robust** — 新候选因子必须通过噪声鲁棒性测试:
    - 方法: 对截面因子值加 N(0, σ) 高斯噪声, σ = noise_pct × cross_section_std
    - 重算 IC, 计算 retention = |noisy_IC| / |clean_IC|
    - **5% 噪声 retention < 0.95**: 警告 (信号质量下降)
    - **20% 噪声 retention < 0.50**: 标记 fragile, 不得进入 Active 池
    - 工具: `scripts/research/noise_robustness.py --noise-pct 0.20`
    - 实证: 21 个 PASS 因子在 5% 噪声下 retention 全部 ≥ 0.94 (无 fragile),
      在 20% 噪声下 retention 仍全部 ≥ 0.59 (最弱: nb_new_entry 0.591). CORE 5 因子全部稳健 (retention ≥ 0.96 @ 20%)

### 工程纪律类（Step 6-H后, 2026-04-10）
21. **先搜索开源方案再自建** — 任何新功能开发前先花半天搜索成熟开源实现（Qlib/RD-Agent/alphalens等）。自建引擎90%功能已被Qlib覆盖的教训。违反→重复造轮子浪费数月。
22. **文档跟随代码** — 每次代码变更后必须同步更新受影响的文档（CLAUDE.md/SYSTEM_STATUS.md/DEV_*.md）。不留过时信息。违反→文档与代码不一致导致错误决策（5yr/12yr Sharpe混淆教训）。
23. **每个任务独立可执行** — 不允许任务依赖未实现的模块。如果存在依赖，先实现依赖或拆分为独立可执行的子任务。违反→依赖死锁导致整个功能链条卡住（11份设计文档80%未实现的根因）。
24. **设计不超过2页** — 超过2页的设计文档说明范围太大，需要拆分为可独立交付的子模块。每个子模块的设计必须包含MVP定义和验收标准。违反→过度设计无法落地（DEV_AI_EVOLUTION 0%实现教训）。

### CC执行纪律类（2026-04-10）
25. **不靠记忆靠代码** — 每个判断必须有当前代码证据（文件路径+行号+实际内容）。违反→基于错误前提做出错误修改。
26. **验证不可跳过不可敷衍** — 验证=读完整代码+理解上下文+交叉对比+明确结论，跳过=任务失败。违反→P0 SN未生效就是验证缺失的直接后果。
27. **结论必须明确（✅/❌/⚠️）不准模糊** — 不接受"大概没问题""应该是对的"。违反→模糊结论掩盖真实问题。
28. **发现即报告不选择性遗漏** — 执行中发现的任何异常不管是否在任务范围内都必须报告。违反→问题被发现又被埋没。

## 因子审批硬标准

- t > 2.5 硬性下限（Harvey Liu Zhu 2016）
- BH-FDR校正: M = FACTOR_TEST_REGISTRY.md 累积测试总数（当前M=88，排除重复验证+CANCELLED）
- 与现有Active因子 corr < 0.7, 选股月收益 corr < 0.3
- 中性化后IC必须验证（原始IC和中性化IC并列展示）
- 因子预处理顺序: **去极值(MAD 5σ) → 填充(行业中位数) → 中性化(行业+市值WLS) → z-score**（不可变）

## 因子画像评估协议（Factor Profiler V2, 2026-04-05）

1. **模板推荐须经多维度验证** — IC显著性+衰减速率+单调性+成本可行性+冗余性五维联合判定，不可单凭IC选模板
2. **Regime切换仅限方向反转** — `sign(ic_bull) ≠ sign(ic_bear)` 才推荐模板12，幅度差异（regime_sensitivity>0.03但同方向）不构成regime切换理由
3. **成本可行性一票否决高频** — `annual_cost > estimated_alpha × 0.5` 的因子不可作为独立策略的主因子，只能作为ML特征或Modifier输入
4. **冗余因子标记不可绕过** — `|corr| > 0.85` 的因子对中，IC较低者标记 `keep_recommendation=drop`，不得同时进入Active组合（镜像对corr<-0.85取绝对值后同理）
5. **FMP候选须经聚类验证** — 独立组合候选因子必须满足与所有其他聚类代表 `|corr| < 0.3`，不可凭主观判断跳过相关性检查

## 性能规范

| 优化项 | 基线 | 优化后 | 方法 |
|--------|------|--------|------|
| 数据加载(`_load_shared_data`) | 30min(DB) | 1.6s | Parquet缓存, 按日期分区 |
| 因子中性化 | 慢(逐因子DB读写) | 15因子/17.5min | `fast_neutralize_batch` Parquet批量 |
| GPU矩阵运算 | CPU numpy | 6.2x加速(5000×5000 matmul) | PyTorch cu128, RTX 5070 12GB |
| Pipeline Step1 | 串行拉取 | 三API并行 | klines+daily_basic+moneyflow并行 |
| 时间范围查询 | 全表扫描 | chunk exclusion | TimescaleDB hypertable自动分区 |
| 回测Phase A信号生成 | 841s(12yr) | ~15s | groupby预索引+bisect O(logN)替代O(N×M)全表扫描 |

- **Parquet缓存路径**: 本地快照, 按日期分区, `_load_shared_data`自动检测缓存有效性
- **cupy**: 不支持Blackwell架构(sm_120), 暂不可用, 用PyTorch替代
- **分钟数据**: Baostock 5min全A股x5年, 本地Parquet分片存储

## 已知失败方向（不可重复）

| 方向 | 结论 | 来源 |
|------|------|------|
| 风险平价/最小方差权重 | 等权最优, 降风险=降Alpha(小盘暴露) | G2 7组实验 |
| 动态仓位(20d momentum) | 新基线上无效 | G2.5 3组实验 |
| 双周调仓 | Sharpe 0.91→0.73 | G2实验 |
| 基本面因子(等权框架) | 10种方式8 FAIL | Sprint 1.5 |
| 量价因子窗口变体 | IC天花板0.05-0.06, 边际收益极低 | 暴力枚举Layer 1-2 |
| PMS v2.0组合级保护 | p=0.655等于随机, 2022慢熊0触发 | v3.6验证 |
| LLM自由生成因子 | IC=0.006-0.008, 需数据驱动prompt | 5次测试 |
| mf_divergence独立策略 | IC=-2.27%(非9.1%), 14组回测全负 | GA2证伪 |
| 同因子换ML模型 | ML Sharpe=0.68 vs 等权0.83, 瓶颈在数据维度 | G1 LightGBM |
| LightGBM 17因子WF | OOS IC=0.067正但弱, 月度回测Sharpe=0.09, 再次确认ML无效 | Step 6-H |
| IC加权/Lasso等下游优化 | 因子信息量不够时优化下游无效 | v3.5原则16 |
| Regime动态beta(RSV) | static b=0.50 Sharpe=0.6287 > dynamic 0.5253 > binary 0.5669 | Step 6-H |
| Vol-targeting/DD-aware | 无改善或更差, Partial SN是唯一有效Modifier | Step 6-G |
| 完全Size-neutral(b=1.0) | 损11% Sharpe, 过度惩罚小盘暴露 | Step 6-F |
| 因子替换turnover_stability_20 | paired bootstrap p=0.92不显著, 非真alpha | Step 6-F |
| Regime线性检测(5指标) | 5指标全p>0.05, 线性方法无法捕捉regime | Step 6-E |
| 组合Modifier(Vol+DD叠加) | 叠加更差, Modifier相互干扰 | Step 6-G |
| RD-Agent集成 | Docker硬依赖+Windows bug+Claude不支持, 三重阻断 | 阶段0调研(2026-04-10) |
| Qlib数据层/回测引擎迁移 | .bin格式需双份数据, 回测无PMS/涨跌停/历史税率, 迁移=倒退 | 阶段0调研(2026-04-10) |
| predict-then-optimize两阶段独立策略 | IC正但Sharpe≈0: 问题在portfolio构建层(排名→Top-N等权丢失alpha)不在预测层; LightGBM预测能力保留为融合系统层1 | G1+Step 6-H两次验证 |

## 策略配置（v1.2→Top-20已部署，Step 0→6-H完成 PT已暂停+已清仓 2026-04-10）
# 基线演进: 1.24(虚高)→0.94(Phase 1加固, 5年)→0.6095(Step 5, 5年regression)→0.5309(Step 6-D, 真实12年)
# 配置来源: configs/pt_live.yaml (Step 4-B, 铁律15要求YAML驱动)
# 回测入口: python scripts/run_backtest.py --config configs/pt_live.yaml

```
因子: turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio
合成: 等权平均
选股: Top 20 (PT_TOP_N=20)
调仓: 月度（月末最后交易日）
Modifier: Partial Size-Neutral b=0.50 (adj_score = score - 0.50*zscore(ln_mcap), Step 6-H验证)
约束: 行业上限=无(PT_INDUSTRY_CAP=1.0), 换手率上限 50%, 100股整手(floor), 日均成交额≥5000万(20日均)
排除: 北交所BJ股 + ST + 停牌 + 新股(list<60天)

基线历史演进:
  旧值1: 5年回测, Sharpe=0.91, Top-15+行业25%, WLS+volume_impact无流动性过滤, MDD=-43.03%
  旧值2(Phase 1加固, 5年): Sharpe=0.94, 年化22.57%, MDD=-40.77%, Calmar=0.55, Sortino=1.19, IR=1.09
    - Phase 1修复(2026-04-07): 印花税历史税率(2023前0.1%)+overnight_gap三因素+z-score clip±3+DataFeed校验
    - 1.24→0.94, 旧值因缺印花税历史税率+缺overnight_gap而虚高
  5年基线(`regression_test.py`, 2021-01~2025-12): Sharpe=0.6095, MDD=-50.75%, 1212天
    - 来源: cache/baseline/nav_5yr.parquet + metrics_5yr.json
    - 用途: CI回归固定锚点, max_diff=0 验收铁律15可复现
  12年真实基线(Step 6-D, 2014-01~2026-04): **Sharpe=0.5309, MDD=-56.37%**, 2980天
    - 来源: cache/baseline/nav_12yr.parquet + metrics_12yr.json (2026-04-09 首次真跑)
    - 此前文档误把5yr 0.6095写成12yr, 实际12yr 0.5309 更差
    - 年化13.06%, 总收益347.9%, NAV 1M→4.48M
    - 2014-2016强(Sharpe 1.17-1.44), 2017-2018弱(-0.39/-0.73), 2021爆赚(3.48)
    - 逐年Sharpe mean=0.79 ± 1.20, 负年份: 2017/2018/2022/2023 (4/12年)
    - WF 5-fold OOS (仅覆盖 2021-02~2026-04): chain-link Sharpe=0.6336, std=1.52 UNSTABLE
    - 结论: regime-dependent, 小盘牛/熊市杀, 非alpha强策略 (FF3归因见 cache/baseline/ff3_attribution.json)
  SN b=0.50 inner (Step 6-H, 2014-01~2026-04): **Sharpe=0.68, MDD=-39.35%**
    - 来源: cache/baseline/wf_sn050_result.json
    - WF 5-fold OOS: Sharpe=0.6521, MDD=-30.23% (优于base 0.6336/-45.7%)
    - 唯一有效Modifier, PT已激活 (pt_live.yaml size_neutral_beta=0.50)

成本: 佣金万0.854(国金实际, min 5元) + 印花税(2023-08-28前0.1%,后0.05%) + 过户费0.001% + 三因素滑点(spread+impact+overnight_gap)
```

**因子健康状态（2026-04-05检查）:**
- turnover_mean_20: ✅ active (IC=-0.091, direction=-1, 方向正确)
- volatility_20: ✅ active (IC=-0.114, direction=-1, 方向正确)
- bp_ratio: ✅ active (IC=+0.107, direction=+1, 方向正确)
- amihud_20: ✅ active (IC=+0.041, direction=+1, 方向正确)
- reversal_20: **⚠️ WARNING（IC方向反转观察中）**
  - 月度IC: 24月中22月为正，2月为负，非持续反转
  - 根因: momentum regime下反转逻辑暂时减弱
  - 处理: 保留Active，等权框架下不单独降权
  - 恢复条件: 连续3月IC_adjusted>0.01自动确认

**PT状态**: 已暂停+已清仓 (2026-04-10)。原因: 等权Top-N框架触到天花板(11实验1成功), V4 Phase 2 E2E验证后重启。重启前提: E2E OOS Sharpe > 等权基线(0.6336) + MDD < 40%。

## 文档查阅索引

| 你要做什么 | 读这个 |
|-----------|--------|
| 了解系统现状/模块怎么对接 | **SYSTEM_STATUS.md** ⭐ |
| 建数据库表 | docs/QUANTMIND_V2_DDL_FINAL.sql ⭐ |
| 接入数据源 | docs/TUSHARE_DATA_SOURCE_CHECKLIST.md ⭐ |
| 写后端Service/理解分层 | docs/DEV_BACKEND.md (§3分层/§4数据流/§5协同矩阵) |
| 写回测引擎/理解Hybrid架构 | docs/DEV_BACKTEST_ENGINE.md (§3Hybrid/§4接口) |
| 写因子计算 | docs/DEV_FACTOR_MINING.md |
| 写前端页面 | docs/DEV_FRONTEND_UI.md |
| 写调度任务 | docs/DEV_SCHEDULER.md |
| 写GP相关 | docs/GP_CLOSED_LOOP_DESIGN.md (FactorDSL/WarmStart) |
| 写风控 | docs/RISK_CONTROL_SERVICE_DESIGN.md (L1-L4状态机) |
| 查设计决策 | V3 附录F（从DESIGN_DECISIONS+TECH_DECISIONS合并） |
| ML Walk-Forward设计/G1结论 | docs/ML_WALKFORWARD_DESIGN.md (v2.1, 1096行) |
| 研究知识库(防重复失败) | `docs/research-kb/` (19条目: 8 failed + 6 findings + 5 decisions) |
| 性能优化最佳实践 | `.claude/skills/quantmind-performance/` |
| 路线图/全面状态/决策历史 | docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.8) |

## 当前进度

### 累计完成
- ✅ Phase A-F全部完成（185新测试, 904全量通过, 0回归）
- ✅ R1-R7 研究完成（7份报告, 73项可落地）
- ✅ G1 LightGBM Walk-Forward完成（ML Sharpe=0.68 vs 等权同期0.83）
- ✅ G2风险平价+G2.5动态仓位: 均无效, 等权是最优权重方案
- ✅ 因子画像V2完成（48因子全量画像, 模板T1=33/T2=4/T11=6/T12=5）
- ✅ 北向研究三轮完成
- ✅ 性能优化（TimescaleDB 2.26.0 + Parquet缓存1000x + GPU 6.2x）
- ✅ 清明改造完成（Servy+Redis5.0+StreamBus+QMT A-lite+PMS v1.0）
- ✅ 回测引擎Phase 1加固(印花税+三因素滑点+z-score clip+DataFeed校验)

### Step 0→6-H 重构 + OOS 验证 + 研究收束 (2026-04-09~10)
- ✅ Step 0: PT暂停+备份+基线建立(Sharpe=0.94, 5年)
- ✅ Step 1: DB全表code格式统一带后缀 + 缓存重建
- ✅ Step 2: 信号路径统一为SignalComposer(铁律16)
- ✅ Step 3-A: Data Contract + DataPipeline统一入库管道(铁律17) + 单位标准化
- ✅ Step 3-B: stock_status_daily表 + adj_close + 日期级过滤 + is_suspended完整检测
- ✅ Step 4-A: backtest_engine.py拆分为backend/engines/backtest/ 8模块
- ✅ Step 4-B: YAML配置驱动 + config_loader + run_backtest改造
- ✅ Step 5: Parquet缓存系统(`cache/backtest/2014-2026/`, 12年×3文件) + 48新测试
- ✅ Step 6-A: run_paper_trading.py拆分1734→345行 + 4个pt_* Service
- ✅ Step 6-B: minute_bars格式统一(139M行) + 7份文档全面更新 + 重构遗留项收尾
- ✅ Step 6-C: 冒烟测试8/8 + PT重启 + 6 runtime bug修复
- ✅ Step 6-D: walk_forward.py修复 + 12年首次真跑(Sharpe=0.5309) + WF 5-fold OOS + 逐年度分解 + FF3归因
- ✅ Step 6-E: IC基础设施修复 (ic_calculator统一口径 + 铁律19) + Alpha衰减归因
- ✅ Step 6-F: 因子替换无效 + Size-neutral有效 + 噪声鲁棒性全PASS + 铁律20
- ✅ Step 6-G: Modifier层实验 (Vol-targeting/DD-aware无效, Partial SN是唯一有效Modifier)
- ✅ Step 6-H: SN inner实现(Sharpe=0.68) + WF验证(0.6521) + Regime CLOSED + LightGBM CLOSED + PT激活SN b=0.50

### 已解决的遗留项(Step 6-B~6-H期间)
- ✅ BJ股过滤: `load_universe()` 已过滤 `board != 'bse'`, PT+回测+WF三路径全覆盖
- ✅ is_st标记: stock_status_daily已有552K/12M条is_st=true记录
- ✅ 12年OOM: Parquet缓存+groupby替代pivot_table, Step 6-D成功跑通12年(2980天)

### 待办(V4路线图)
- ✅ 阶段0: Qlib + RD-Agent 技术调研完成 → 路线C(混合): 自建核心 + Alpha158因子借鉴 + riskfolio-lib (2026-04-10)
- ✅ **Phase 1.1**: 回测Phase A优化（841s→14.6s, groupby+bisect替代O(N×M)全表扫描, 2026-04-10）
- ✅ **Phase 1.2**: 新信号维度（Alpha158六因子6/6 PASS + 行业动量2/2 PASS + 北向V2 15因子 + PEAD方向修正为-1 + SW1中性化迁移53因子, 2026-04-11）
- ⬜ **Phase 2.1**: 融合E2E（LightGBM预测层+Portfolio Network权重层, loss=-Sharpe, 详见V4附录A）
- ⬜ **Phase 2.2**: IC加权SignalComposer（baseline对比）
- ⬜ **Phase 2.3**: riskfolio-lib Portfolio优化 MVO/RP/BL（baseline对比）
- ⬜ **Phase 3**: 简版AI闭环（因子生命周期自动化 + Rolling WF + IC监控告警）
- ⬜ **Phase 4**: PT重启（前提: E2E OOS Sharpe > 0.6336 + MDD < 40%）
- 详见 docs/QUANTMIND_FACTOR_UPGRADE_PLAN_V4.md

📋 路线图: `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md` (v3.8 + 第四部分重构记录)
📊 测试: 2115 tests / 98 test files (Step 5新增48测试)
---

## 文件归属规则（防腐）

### 根目录只允许以下文件
CLAUDE.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md / pyproject.toml / .gitignore
- 新审计/盘点报告 → `docs/reports/`
- 新研究报告 → `docs/research/`
- 回测输出 → 用完即删，不留根目录
- 临时文件/artifact → 用完即删

### 引用完整性规则
- 引用文件必须用完整相对路径
- 归档/移动文件后 `grep -r "文件名" --include="*.md" --include="*.py"` 更新所有引用
- 重构函数/重命名后检查所有import方

### 数字同步规则
- CLAUDE.md中的统计数字（表数/因子数/测试数）变更时同步更新
- 不确定的数字标注"约"或"截至日期"
- 因子池状态以FACTOR_TEST_REGISTRY.md为唯一真相源

### 文档层级（固定）
- **总设计**: `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md`
- **系统现状**: `SYSTEM_STATUS.md`
- **入口导航**: `CLAUDE.md`（本文件）
- **Schema定义**: `docs/QUANTMIND_V2_DDL_FINAL.sql`
- DESIGN_V5只做局部参考，不是当前总设计

## 执行标准流程

1. 读本文件了解全局
2. **读 SYSTEM_STATUS.md** 了解系统现状、模块怎么对接
3. 根据任务类型读对应DEV文档（见查阅索引）
4. 编码 → 测试 → 验证
5. 发现需要偏离指令的地方 → **先报告，等确认**
6. 任务完成后更新 SYSTEM_STATUS.md 对应章节（保持文档与代码一致）
