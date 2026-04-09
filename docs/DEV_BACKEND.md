# QuantMind V2 — 后端服务层详细开发文档

> 文档级别：实现级（供 Claude Code 执行）
> 创建日期：2026-03-20
> 最后更新: 2026-04-09 (Step 3-A + Step 4-B + Step 5 + Step 6-A/B)
> 关联文档：QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md §第四部分, DEV_SCHEDULER.md
> 解决问题：后端架构/项目结构/服务层/数据流/模块协同

---

## §0 Step 3-A + 5 + 6 重构后的新分层 (2026-04-09, 优先阅读)

> 本节描述重构后的**实际代码结构**, 优先级高于下方历史章节。

### 新增分层: Data 层 (Step 5)

```
backend/data/
└── parquet_cache.py     # BacktestDataCache: 按年分区 Parquet 缓存 (233 行)
```

**职责边界**:
- 本地数据快照 / 缓存 (Parquet 文件)
- 无业务逻辑, 无 DB 访问
- 数据契约: 与生产 DB 表完全一致 (列名/类型/单位)
- 由 `scripts/build_backtest_cache.py` 从 DB 导出构建

**使用场景**:
- 回测引擎 (runner.py) 加载历史数据: 优先查 Parquet, 未命中回退 DB
- 研究脚本 (scripts/research/*.py) 快速启动: 30 min → 20 sec

**分层位置**:
```
Router(api/) → Service(services/) → Engine(engines/) ──→ Data(data/)
                                       │                    │
                                       └──→ Integration(data_fetcher/) → DB
```

Data 层在 Engine 层下方, Engine 直接消费 Data 层的 DataFrame, 完全不依赖 Integration 层 (DB)。

### Data Contract + DataPipeline (Step 3-A, 铁律 17)

```
backend/app/data_fetcher/
├── contracts.py    # 每张表的 TableContract (列/单位/rename_map/FK过滤)
└── pipeline.py     # DataPipeline.ingest(df, contract) — 唯一数据入库入口
```

**禁止**: 生产代码任何位置的 `INSERT INTO <core_table>` 都必须改为 `DataPipeline.ingest()`。违反即破坏单位一致性和 code 格式一致性。

**Contract 注册表** (11 张表, Step 6-B 新增 MINUTE_BARS):
- KLINES_DAILY / DAILY_BASIC / MONEYFLOW_DAILY / INDEX_DAILY
- FACTOR_VALUES / NORTHBOUND_HOLDINGS / SYMBOLS
- EARNINGS_ANNOUNCEMENTS / STOCK_STATUS_DAILY / MINUTE_BARS

**DataPipeline.ingest() 流程**:
1. rename (ts_code → code 等)
2. 列对齐 (保留 contract 列, 补缺失 nullable)
3. 单位转换 (千元→元, 万元→元)
4. 逐列验证 (PK 非空, 值域, inf/NaN → None)
5. FK 过滤 (symbols.code)
6. Upsert (ON CONFLICT DO UPDATE)

### 新增 Services (Step 4-B + 6-A)

```
backend/app/services/
├── config_loader.py         # Step 4-B: YAML 策略配置加载 (147 行)
├── pt_data_service.py       # Step 6-A: PT 并行数据拉取 (104 行)
├── pt_monitor_service.py    # Step 6-A: PT 开盘跳空检测 (90 行)
├── pt_qmt_state.py          # Step 6-A: QMT↔DB 状态同步 (84 行)
└── shadow_portfolio.py      # Step 6-A: LightGBM 影子选股 (238 行)
```

**config_loader.py**: `load_strategy_config(yaml_path)` 返回 (BacktestConfig, SignalConfig, config_hash)。config_hash 是 sha256(yaml_text), 写入 backtest_run.config_yaml_hash 满足铁律 15。

**pt_data_service.py**: `fetch_daily_data(trade_date, skip_fetch=False)` 并行拉取 klines/basic/index 三个 API (ThreadPoolExecutor max_workers=3), 走 DataPipeline.ingest() 入库。

**pt_monitor_service.py**: `check_opening_gap(exec_date, price_data, conn, notif_svc, dry_run)` — 单股跳空 >5% 告 P1, 组合加权跳空 >3% 告 P0。

**pt_qmt_state.py**: `save_qmt_state(conn, trade_date, qmt_positions, today_close, nav, prev_nav, qmt_nav_data, benchmark_close)` — 把 QMT 的实际持仓和 NAV 写入 position_snapshot + performance_series (execution_mode='paper')。

**shadow_portfolio.py**: 两个函数 `generate_shadow_lgbm_signals()` (Raw 选股) + `generate_shadow_lgbm_inertia()` (Inertia 0.7σ), 用 fold_{1..7}.txt 训练好的 LightGBM 模型预测, 写 shadow_portfolio 表。失败不阻塞主流程。

### PT 主脚本重构 (Step 6-A)

`scripts/run_paper_trading.py` 从 1734 行 → 345 行, 变成纯编排器:
- signal phase: 健康预检 → 配置守卫 → Step1 数据拉取(委托 pt_data_service) → Step1.5 NAV 更新(pt_qmt_state) → 风控 → 因子 → 信号 → 影子选股 → 收尾
- execute phase: QMT 连接 → 读信号 → 数据拉取 → QMT drift → 开盘跳空(pt_monitor_service) → 熔断 → 执行 → 收尾

业务逻辑全部在 4 个 pt_* Service 中, 脚本自身只编排。

### 重构后的调用链示例 (PT signal phase)

```
scripts/run_paper_trading.py :: run_signal_phase()
  ├─ health_check.run_health_check()
  ├─ config_guard.assert_baseline_config()  [铁律15]
  ├─ pt_data_service.fetch_daily_data()     [走 DataPipeline, 铁律17]
  │   └─ DataPipeline.ingest(df, KLINES_DAILY)
  │   └─ DataPipeline.ingest(df, DAILY_BASIC)
  │   └─ DataPipeline.ingest(df, INDEX_DAILY)
  ├─ QMTClient().get_positions() / get_nav()
  ├─ pt_qmt_state.save_qmt_state()
  ├─ risk_control_service.check_circuit_breaker_sync()
  ├─ factor_engine.compute_daily_factors()
  ├─ factor_engine.save_daily_factors()
  ├─ load_factor_values()
  ├─ SignalService().generate_signals()     [唯一信号路径, 铁律16]
  │   └─ SignalComposer.compose()
  └─ shadow_portfolio.generate_shadow_lgbm_signals() (实验, 失败不阻塞)
```

---

## 一、项目目录结构

```
quantmind-v2/
│
├── backend/                          # Python后端(FastAPI + Celery)
│   ├── main.py                       # FastAPI入口: app创建、路由注册、中间件
│   ├── config.py                     # 配置管理: 从.env加载所有配置
│   ├── database.py                   # 数据库连接池: SQLAlchemy async engine + session
│   │
│   ├── routers/                      # API路由层(按模块分文件)
│   │   ├── __init__.py
│   │   ├── dashboard.py              # /api/dashboard/* (总览)
│   │   ├── strategy.py               # /api/strategy/* (策略工作台)
│   │   ├── backtest.py               # /api/backtest/* (回测)
│   │   ├── factors.py                # /api/factors/* (因子库)
│   │   ├── mining.py                 # /api/mining/* (因子挖掘)
│   │   ├── pipeline.py               # /api/pipeline/* (AI闭环)
│   │   ├── forex.py                  # /api/forex/* (外汇)
│   │   ├── settings.py               # /api/settings/* (系统设置)
│   │   ├── notifications.py          # /api/notifications/* (通知)
│   │   └── websocket.py              # /ws/* (所有WebSocket端点)
│   │
│   ├── services/                     # 业务逻辑层(核心)
│   │   ├── __init__.py
│   │   ├── data_service.py           # 数据拉取+清洗+入库
│   │   ├── factor_service.py         # 因子计算+体检+生命周期
│   │   ├── signal_service.py         # 信号生成(IC加权/ML预测)
│   │   ├── backtest_service.py       # 回测管理(启动/查询/结果)
│   │   ├── strategy_service.py       # 策略CRUD+配置管理
│   │   ├── portfolio_service.py      # 组合构建+仓位管理
│   │   ├── risk_service.py           # 风控检查(A股+外汇)
│   │   ├── mining_service.py         # 因子挖掘(LLM/GP/枚举)
│   │   ├── pipeline_service.py       # AI闭环Pipeline编排
│   │   ├── forex_signal_service.py   # 外汇信号(3层因子)
│   │   ├── forex_broker_service.py   # 外汇SimBroker+实盘交易
│   │   ├── forex_risk_service.py     # 外汇风控(4层14项)
│   │   ├── notification_service.py   # 通知发送(统一入口)
│   │   ├── scheduler_service.py      # 调度监控+日历
│   │   ├── llm_service.py            # LLM调用(DeepSeek/Claude,模型路由)
│   │   └── ml_service.py             # ML模型(LightGBM/Optuna/RF)
│   │
│   ├── repositories/                 # 数据访问层(SQL查询封装)
│   │   ├── __init__.py
│   │   ├── kline_repo.py             # klines_daily读写
│   │   ├── factor_repo.py            # factor_registry/factor_values读写
│   │   ├── backtest_repo.py          # backtest_run/trades读写
│   │   ├── signal_repo.py            # daily_signals读写
│   │   ├── pipeline_repo.py          # pipeline_run/agent_decision_log读写
│   │   ├── forex_repo.py             # forex_bars/forex_*系列表读写
│   │   ├── notification_repo.py      # notifications表读写
│   │   ├── config_repo.py            # ai_parameters/system_config读写
│   │   └── scheduler_repo.py         # scheduler_task_log读写
│   │
│   ├── schemas/                      # Pydantic数据模型(请求/响应)
│   │   ├── __init__.py
│   │   ├── dashboard.py              # DashboardSummaryResponse等
│   │   ├── backtest.py               # BacktestConfigRequest, BacktestResultResponse等
│   │   ├── factor.py                 # FactorListResponse, FactorEvaluationResponse等
│   │   ├── strategy.py               # StrategyCreateRequest等
│   │   ├── forex.py                  # ForexAccountResponse, ForexPositionResponse等
│   │   ├── pipeline.py               # PipelineStatusResponse等
│   │   ├── notification.py           # NotificationResponse, PreferencesRequest等
│   │   └── common.py                 # PaginatedResponse, ErrorResponse等
│   │
│   ├── models/                       # SQLAlchemy ORM模型(映射51张表)
│   │   ├── __init__.py
│   │   ├── base.py                   # Base, TimestampMixin
│   │   ├── astock.py                 # klines, daily_basic, factor_registry等
│   │   ├── backtest.py               # backtest_run, backtest_trades等
│   │   ├── ai.py                     # pipeline_run, agent_decision_log等
│   │   ├── forex.py                  # forex_bars, forex_symbol_config等
│   │   ├── notification.py           # notifications, notification_preferences
│   │   └── system.py                 # ai_parameters, scheduler_task_log等
│   │
│   ├── tasks/                        # Celery异步任务
│   │   ├── __init__.py               # Celery app创建
│   │   ├── celery_config.py          # Beat schedule + 队列配置
│   │   ├── astock_tasks.py           # T1-T17 A股任务链
│   │   ├── forex_tasks.py            # FX1-FX11 外汇任务链
│   │   ├── ai_tasks.py               # AI Pipeline任务
│   │   ├── system_tasks.py           # 数据库维护、清理
│   │   └── task_utils.py             # 依赖检查、重试装饰器、通知Hook
│   │
│   ├── engines/                      # 核心计算引擎
│   │   ├── __init__.py
│   │   ├── factor_engine.py          # 34个A股因子的计算函数
│   │   ├── signal_engine.py          # 选股信号生成
│   │   ├── backtest_engine_py.py     # Python回测引擎(外汇用)
│   │   ├── forex_signal_engine.py    # 外汇3层信号合成
│   │   ├── forex_cost_model.py       # 外汇成本模型(点差/Swap/滑点)
│   │   ├── walk_forward.py           # Walk-Forward验证
│   │   ├── gp_engine.py              # GP遗传编程引擎
│   │   ├── sandbox.py                # 因子代码沙箱执行
│   │   └── ml_models.py              # LightGBM/Optuna/RF封装
│   │
│   ├── integrations/                 # 外部系统集成
│   │   ├── __init__.py
│   │   ├── akshare_client.py         # AKShare数据拉取
│   │   ├── tushare_client.py         # Tushare数据拉取
│   │   ├── mt5_client.py             # MT5 Adapter HTTP客户端
│   │   ├── deepseek_client.py        # DeepSeek API封装
│   │   ├── anthropic_client.py       # Claude API封装
│   │   ├── dingtalk_client.py        # 钉钉Webhook
│   │   └── miniqmt_client.py         # miniQMT接口(Phase 1)
│   │
│   ├── websocket/                    # WebSocket管理
│   │   ├── __init__.py
│   │   ├── manager.py                # 连接池管理+广播+房间
│   │   ├── backtest_ws.py            # /ws/backtest/{runId}
│   │   ├── mining_ws.py              # /ws/factor-mine/{taskId}
│   │   ├── pipeline_ws.py            # /ws/pipeline/{runId}
│   │   ├── forex_ws.py               # /ws/forex/realtime
│   │   └── notification_ws.py        # /ws/notifications
│   │
│   └── utils/                        # 工具函数
│       ├── __init__.py
│       ├── date_utils.py             # 交易日历、日期处理
│       ├── math_utils.py             # IC/IR/Sharpe/MDD计算
│       ├── validation.py             # 数据质量验证
│       └── logging.py                # loguru配置
│
├── rust_engine/                      # Rust回测引擎(A股)
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs                   # CLI入口(被Python通过subprocess调用)
│       ├── data_handler.rs           # 数据加载
│       ├── signal_generator.rs       # 信号向量化计算
│       ├── sim_broker.rs             # 模拟broker
│       └── portfolio.rs              # 组合管理
│
├── frontend/                         # React前端
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/                    # 12个页面组件
│   │   ├── components/               # 通用组件库
│   │   ├── hooks/                    # 自定义hooks(useWebSocket等)
│   │   ├── stores/                   # Zustand状态管理
│   │   ├── services/                 # API调用封装(axios/React Query)
│   │   └── styles/                   # Tailwind配置+主题
│   └── ...
│
├── mt5_adapter/                      # MT5网关(运行在Windows Parallels中)
│   ├── mt5_adapter.py                # FastAPI app(端口8001)
│   └── .env                          # MT5凭据
│
├── scripts/                          # 运维脚本
│   ├── start_all.sh                  # 一键启动所有服务
│   ├── stop_all.sh                   # 一键停止
│   ├── init_db.py                    # 建表+初始化数据
│   ├── import_histdata.py            # HistData导入(一次性)
│   ├── seed_factors.py               # 初始化34个因子配置
│   └── backup_db.sh                  # 数据库备份
│
├── tests/                            # 测试
│   ├── conftest.py                   # pytest fixtures(测试DB/mock)
│   ├── unit/                         # 单元测试(engines/services)
│   ├── integration/                  # 集成测试(API端到端)
│   └── backtest/                     # 回测确定性测试
│
├── alembic/                          # 数据库迁移
│   ├── alembic.ini
│   └── versions/
│
├── .env                              # 环境变量(不入git)
├── .env.example                      # 环境变量模板
├── CLAUDE.md                         # Claude Code项目上下文
├── pyproject.toml                    # Python依赖+工具配置
└── README.md
```

---

## 二、FastAPI应用结构

### 2.1 main.py

```python
# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.config import settings
from backend.database import init_db, close_db
from backend.routers import (
    dashboard, strategy, backtest, factors, mining,
    pipeline, forex, settings_router, notifications, websocket
)
from backend.utils.logging import setup_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await init_db()
    yield
    await close_db()

app = FastAPI(
    title="QuantMind V2",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(dashboard.router,      prefix="/api/dashboard",      tags=["dashboard"])
app.include_router(strategy.router,       prefix="/api/strategy",       tags=["strategy"])
app.include_router(backtest.router,       prefix="/api/backtest",       tags=["backtest"])
app.include_router(factors.router,        prefix="/api/factors",        tags=["factors"])
app.include_router(mining.router,         prefix="/api/mining",         tags=["mining"])
app.include_router(pipeline.router,       prefix="/api/pipeline",       tags=["pipeline"])
app.include_router(forex.router,          prefix="/api/forex",          tags=["forex"])
app.include_router(settings_router.router,prefix="/api/settings",       tags=["settings"])
app.include_router(notifications.router,  prefix="/api/notifications",  tags=["notifications"])
app.include_router(websocket.router,      tags=["websocket"])

@app.get("/api/health")
async def health(): return {"status": "ok"}
```

### 2.2 config.py

```python
# backend/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "postgresql+asyncpg://localhost:5432/quantmind"
    DATABASE_POOL_SIZE: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # 数据源
    TUSHARE_TOKEN: str = ""
    AKSHARE_ENABLED: bool = True

    # LLM
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    ANTHROPIC_API_KEY: str = ""

    # MT5 Adapter
    MT5_ADAPTER_URL: str = "http://localhost:8001"

    # 外汇
    FOREX_ENABLED: bool = False  # Phase 0关闭，Phase 2开启

    # 通知
    DINGTALK_WEBHOOK_URL: str = ""
    DINGTALK_ENABLED: bool = False

    # 日志
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/quantmind.log"

    class Config:
        env_file = ".env"

settings = Settings()
```

### 2.3 database.py

```python
# backend/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from backend.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    echo=False,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    # 连接测试(不建表，用alembic迁移)
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

async def close_db():
    await engine.dispose()

async def get_db():
    async with async_session() as session:
        yield session
```

---

## 三、服务层分层架构

### 3.1 调用规则（严格执行）

```
Router层(routers/):
  ✓ 参数验证(Pydantic schema)
  ✓ 调用Service层
  ✓ 返回Response schema
  ✗ 不包含业务逻辑
  ✗ 不直接访问数据库

Service层(services/):
  ✓ 所有业务逻辑
  ✓ 调用Repository层读写数据
  ✓ 调用Engine层做计算
  ✓ 调用其他Service(通过依赖注入)
  ✓ 调用NotificationService发通知
  ✗ 不处理HTTP请求/响应格式
  ✗ 不直接构造SQL

Repository层(repositories/):
  ✓ SQL查询封装
  ✓ 返回ORM对象或dict
  ✗ 不包含业务逻辑
  ✗ 不调用其他Repository(需要时由Service层协调)

Engine层(engines/):
  ✓ 纯计算(无IO)
  ✓ 输入DataFrame/dict，输出DataFrame/dict
  ✗ 不访问数据库
  ✗ 不调用外部API

Integration层(integrations/):
  ✓ 封装外部API调用
  ✓ 处理重试/超时/错误
  ✓ 返回标准化的dict/DataFrame
```

### 3.2 Router→Service示例

```python
# routers/backtest.py
from fastapi import APIRouter, Depends
from backend.services.backtest_service import BacktestService
from backend.schemas.backtest import BacktestConfigRequest, BacktestResultResponse

router = APIRouter()

@router.post("/run")
async def run_backtest(config: BacktestConfigRequest,
                       service: BacktestService = Depends()):
    """启动回测 → Celery异步任务"""
    run_id = await service.submit_backtest(config)
    return {"run_id": run_id, "status": "submitted"}

@router.get("/{run_id}/result", response_model=BacktestResultResponse)
async def get_result(run_id: str,
                     service: BacktestService = Depends()):
    return await service.get_result(run_id)
```

```python
# services/backtest_service.py
class BacktestService:
    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.repo = BacktestRepo(db)
        self.notifier = NotificationService()

    async def submit_backtest(self, config: BacktestConfigRequest) -> str:
        run = await self.repo.create_run(config.dict())
        # 提交Celery异步任务
        if config.market == 'astock':
            task = astock_backtest_task.delay(str(run.run_id), config.dict())
        elif config.market == 'forex':
            task = forex_backtest_task.delay(str(run.run_id), config.dict())
        await self.repo.update_celery_task_id(run.run_id, task.id)
        return str(run.run_id)

    async def get_result(self, run_id: str) -> dict:
        run = await self.repo.get_run(run_id)
        if not run: raise HTTPException(404)
        trades = await self.repo.get_trades(run_id)
        return self._build_result_response(run, trades)
```

---

## 四、端到端数据流

### 4.1 A股完整数据流

```
数据拉取
  AKShare/Tushare API
  → integrations/akshare_client.py: fetch_daily_klines()
  → services/data_service.py: update_daily_data()
  → repositories/kline_repo.py: batch_upsert()
  → 表: klines_daily, daily_basic, fina_indicator
  → 触发: Celery任务T1(06:00), 每交易日

数据质量检查
  → services/data_service.py: check_data_quality()
  → repositories/kline_repo.py: count_stocks(), check_nulls()
  → 写入: data_quality_log表(Phase 0可选)
  → 失败: notification_service.send('system.data_update_failed')
  → 触发: T2(06:35), 依赖T1

Universe构建
  → services/factor_service.py: build_universe()
  → engines/factor_engine.py: apply_8_filters()
    读: klines_daily(ST/停牌/涨跌停标记), daily_basic(市值/成交额)
    写: universe_daily表
  → 触发: T3(06:50), 依赖T2

因子计算
  → services/factor_service.py: compute_all_factors()
  → engines/factor_engine.py: compute_factor(name, data)
    读: klines_daily, daily_basic, fina_indicator, moneyflow_daily等
    计算: 34个因子, 截面标准化
    写: factor_values表
  → 触发: T4(07:00), 依赖T3

ML预测(启用时)
  → services/ml_service.py: predict()
  → engines/ml_models.py: lgbm.predict_proba()
    读: factor_values(当日截面)
    写: signal_scores表
  → 触发: T6(07:35), 依赖T4

信号生成
  → services/signal_service.py: generate_daily_signal()
  → engines/signal_engine.py: rank_and_select()
    读: factor_values或signal_scores, universe_daily
    计算: IC加权/ML得分 → Top-N → 风控过滤
    写: daily_signals表
  → 触发: T7(07:45), 依赖T4/T6

调仓决策
  → services/portfolio_service.py: generate_rebalance_orders()
    读: daily_signals(今日), portfolio_holdings(昨日持仓)
    计算: 对比→买卖清单→成本估算
    写: rebalance_orders表
  → 触发: T8(08:00), 依赖T7

交易执行
  → services/portfolio_service.py: execute_orders()
  → integrations/miniqmt_client.py: send_order()
    读: rebalance_orders
    执行: miniQMT TWAP/VWAP
    写: execution_log表
  → notification_service.send('trade.astock_rebalance')
  → 触发: T10(09:30), 依赖T8

盘后更新
  → services/data_service.py: post_market_update()
  → services/portfolio_service.py: update_portfolio_snapshot()
    读: 当日完整行情, execution_log
    写: portfolio_snapshot, daily_nav
  → 触发: T13(15:30)

绩效+日报
  → services/portfolio_service.py: calculate_performance()
  → notification_service.send(日报内容)
  → 触发: T14-T15(16:00-16:30)
```

### 4.2 外汇完整数据流

```
数据拉取
  → integrations/mt5_client.py: get_rates()
  → services/data_service.py: update_forex_daily()
  → repositories/forex_repo.py: upsert_bars()
  → 表: forex_bars, forex_events, forex_swap_rates
  → 触发: FX1-FX3(22:05-22:25 UTC)

因子计算
  → services/forex_signal_service.py: compute_all_factors()
  → engines/forex_signal_engine.py: compute_technical_factors()
    读: forex_bars(D1/H4), forex_macro_data, forex_cot_data
    写: 内存缓存(因子值不需要持久化，每日重算)
  → 触发: FX5-FX6(22:35-22:40)

ML+信号合成
  → services/forex_signal_service.py: generate_signals()
  → engines/forex_signal_engine.py: synthesize()
  → engines/ml_models.py: lgbm.predict_proba()
    宏观过滤 → 技术信号 → ML调整confidence
    写: forex_signals表(可选)
  → 触发: FX7-FX8(22:45-22:50)

持仓管理+执行
  → services/forex_broker_service.py: manage_positions()
  → services/forex_risk_service.py: pre_trade_check()
  → integrations/mt5_client.py: open_position/close_position
    读: MT5持仓, forex_signals
    执行: MT5 Adapter HTTP调用
    写: forex_trade_log, portfolio_snapshot
  → notification_service.send('trade.forex_open/close')
  → 触发: FX9-FX10(22:55-23:00)
```

### 4.3 回测数据流

```
用户操作
  前端: 配置回测参数 → POST /api/backtest/run
  → routers/backtest.py
  → services/backtest_service.py: submit_backtest()
  → 创建backtest_run记录(status='pending')
  → 提交Celery任务

Celery Worker执行
  → tasks/astock_tasks.py: astock_backtest_task()
    → 更新status='running'
    → 启动Rust引擎(subprocess) 或 Python引擎
    → 逐日推进: 信号→执行→净值→记录
    → 通过WebSocket推送进度: ws_manager.push('backtest', progress)
    → 写入: backtest_run(结果), backtest_trades(交易明细)
    → 更新status='completed'
    → notification_service.send('backtest.complete')

前端接收
  WebSocket /ws/backtest/{runId}: 实时进度+净值点
  完成后: GET /api/backtest/{runId}/result → 完整结果
```

### 4.4 AI闭环数据流

```
触发
  Celery Beat周日22:00 或 手动触发
  → tasks/ai_tasks.py: pipeline_run_task()
  → services/pipeline_service.py: run_pipeline()

Pipeline状态机(run_pipeline内部):
  IDLE → FACTOR_DISCOVERY
    → services/mining_service.py: discover()
    → integrations/deepseek_client.py: generate(R1_prompt)  # 假设
    → integrations/deepseek_client.py: generate(V3_prompt)  # 代码
    → engines/sandbox.py: execute()                         # 沙箱
    → engines/factor_engine.py: evaluate()                  # 评估
    → 写入: factor_mining_task表
    → ws推送进度

  FACTOR_DISCOVERY → FACTOR_EVALUATION
    → services/factor_service.py: evaluate_candidates()
    → engines/walk_forward.py: validate()
    → 写入: factor_evaluation表
    → Gate检验(8项A股/6项外汇)

  FACTOR_EVALUATION → FACTOR_APPROVAL_PENDING(L0/L1)
    → notification_service.send('factor.new_candidate')
    → 等待人工审批(L0) 或 自动审批(L2+)

  审批通过 → STRATEGY_BUILD
    → services/signal_service.py: optimize_weights()
    → engines/ml_models.py: train() (Optuna搜索)
    → 写入: strategy_config

  STRATEGY_BUILD → BACKTEST_RUNNING
    → services/backtest_service.py: submit_backtest()
    → (复用回测数据流)

  BACKTEST_RUNNING → RESULT_ANALYSIS
    → services/pipeline_service.py: analyze_result()

  RESULT_ANALYSIS → DIAGNOSIS(如果不达标)
    → services/pipeline_service.py: diagnose()
    → integrations/deepseek_client.py: generate(诊断prompt)
    → 写入: agent_decision_log

  → RISK_CHECK → DEPLOY_APPROVAL → COMPLETED
    → notification_service.send('pipeline.complete')
```

---

## 五、模块协同矩阵

### 5.1 "谁调谁"全景图

```
                    被调用方 →
调用方 ↓         Data  Factor Signal Backtest Portfolio Risk Mining Pipeline ForexSig ForexBrk Notif  LLM    ML
─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
DataService       —     —      —       —        —       —     —       —       —        —       ✓      —     —
FactorService     ✓     —      —       —        —       —     —       —       —        —       ✓      —     —
SignalService     —     ✓      —       —        —       ✓     —       —       —        —       —      —     ✓
BacktestService   —     —      —       —        —       —     —       —       —        —       ✓      —     —
PortfolioService  —     —      ✓       —        —       ✓     —       —       —        —       ✓      —     —
RiskService       —     —      —       —        —       —     —       —       —        —       —      —     —
MiningService     —     ✓      —       —        —       —     —       —       —        —       ✓      ✓     —
PipelineService   —     ✓      ✓       ✓        —       —     ✓       —       —        —       ✓      ✓     ✓
ForexSignalSvc    —     —      —       —        —       —     —       —       —        —       —      —     ✓
ForexBrokerSvc    —     —      —       —        —       ✓(fx) —       —       ✓        —       ✓      —     —
SchedulerService  —     —      —       —        —       —     —       —       —        —       ✓      —     —

Celery任务(tasks/)调用Service层，不直接调用其他Task。
Router层调用对应的Service层，不跨模块调用。
NotificationService是唯一的"被所有模块调用"的Service。
```

### 5.2 通知调用点清单（解决Review问题①）

```
每个模块在哪里调用notification_service.send():

DataService:
  update_daily_data() 失败 → 'system.data_update_failed' (P0)
  check_data_quality() 失败 → 'system.data_update_failed' (P0)

FactorService:
  factor_health_check() 发现衰退 → 'factor.degraded' (P1)

BacktestService:
  backtest完成(Celery task callback) → 'backtest.complete' (P2)
  backtest失败 → 'backtest.failed' (P1)

PortfolioService:
  execute_orders()成功 → 'trade.astock_rebalance' (P2)
  回撤熔断触发 → 'risk.drawdown_warning/pause/emergency' (P0/P1)
  每日最大亏损 → 'risk.daily_loss' (P1)

ForexBrokerService:
  开仓成功 → 'trade.forex_open' (P2)
  平仓成功 → 'trade.forex_close' (P2)
  移动止损 → 'trade.forex_sl_modified' (P3)
  周五减仓 → 'trade.friday_close' (P2)
  margin call → 'risk.margin_call' (P0)
  经济事件保护 → 'trade.event_protection' (P1)

ForexRiskService:
  保证金预警 → 'risk.margin_warning' (P1)
  连续亏损 → 'risk.consecutive_loss' (P1)

PipelineService:
  pipeline完成 → 'pipeline.complete' (P2)
  审批需要 → 'pipeline.approval_needed' (P2)

MiningService:
  挖掘完成(新候选) → 'factor.new_candidate' (P2)

MT5ConnectionManager:
  断连 → 'system.mt5_disconnect' (P0)
  重连 → 'system.mt5_reconnected' (P3)

SchedulerService:
  任务延迟 → 'system.scheduler_task_delayed' (P1)
  参数冷却期到期 → 'system.param_cooldown_expired' (P2)
```

### 5.3 A股与外汇共享组件的路由方式（解决Review问题⑤）

```
两种路由层级:

1. API层路由(market查询参数):
   GET /api/factors?market=astock  →  FactorService.list(market='astock')
   GET /api/factors?market=forex   →  FactorService.list(market='forex')
   
   Router层只负责传递market参数，不做业务分支。

2. Service层路由(内部分支):
   class FactorService:
       async def list(self, market: str):
           if market == 'forex':
               return await self.forex_repo.list_factors()
           else:
               return await self.factor_repo.list_factors()

   class BacktestService:
       async def submit(self, config):
           if config.market == 'forex':
               task = forex_backtest_task.delay(...)
           else:
               task = astock_backtest_task.delay(...)

   class PipelineService:
       async def run_step(self, state, market):
           if market == 'forex':
               agent = self.forex_factor_agent
           else:
               agent = self.astock_factor_agent

3. 共享的ai_parameters表:
   每个参数有market字段: 'astock' | 'forex' | 'global'
   读取时: SELECT * FROM ai_parameters WHERE market IN ('astock', 'global')
   ai_parameters表已有market字段设计(DEV_PARAM_CONFIG.md)
```

---

## 六、配置管理

### 6.1 .env.example

```env
# === 数据库 ===
DATABASE_URL=postgresql+asyncpg://localhost:5432/quantmind
DATABASE_POOL_SIZE=10

# === Redis ===
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# === 数据源 ===
TUSHARE_TOKEN=your_tushare_token
AKSHARE_ENABLED=true

# === LLM ===
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
ANTHROPIC_API_KEY=sk-ant-xxx

# === MT5 (外汇，Phase 2开启) ===
MT5_ADAPTER_URL=http://localhost:8001
FOREX_ENABLED=false

# === MT5 Adapter (Windows .env) ===
# MT5_LOGIN=888888
# MT5_PASSWORD=xxx
# MT5_SERVER=ECMarkets-Demo

# === 通知 ===
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_ENABLED=false

# === 日志 ===
LOG_LEVEL=INFO
LOG_FILE=logs/quantmind.log
```

---

## 七、测试策略

```
Phase 0测试重点(不求100%覆盖，但关键路径必须测):

必测:
  engines/factor_engine.py      — 34个因子的计算正确性(单元测试)
  engines/signal_engine.py      — Top-N选股逻辑(单元测试)
  回测确定性                     — 相同输入两次结果完全一致
  services/risk_service.py      — 风控5项检查(单元测试)
  services/data_service.py      — 数据质量检查(单元测试)
  API端到端                     — 回测提交→运行→结果(集成测试)

不测(Phase 0):
  前端组件
  LLM输出质量(不可确定性)
  GP进化结果(随机性)
  
pytest结构:
  tests/unit/test_factor_engine.py
  tests/unit/test_signal_engine.py
  tests/unit/test_risk_service.py
  tests/integration/test_backtest_api.py
  tests/backtest/test_determinism.py
```

---

## 八、日志框架

```python
# backend/utils/logging.py
from loguru import logger
import sys

def setup_logging():
    logger.remove()  # 移除默认handler
    
    # 控制台: 彩色+简洁
    logger.add(sys.stderr, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level:7s}</level> | {message}")
    
    # 文件: 完整+轮转
    logger.add("logs/quantmind.log", level="DEBUG",
               rotation="100 MB", retention="30 days",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:7s} | {module}:{function}:{line} | {message}")
    
    # 交易日志(独立文件):
    logger.add("logs/trades.log", level="INFO",
               filter=lambda record: "trade" in record["extra"],
               rotation="1 month")

# 使用:
logger.info("因子计算完成: 34因子×2800股")
logger.bind(trade=True).info("EURUSD做多0.19手已成交 @1.0842")
logger.error("AKShare数据拉取失败: {}", str(e))
```

---

## 九、错误处理

```python
# backend/main.py 中间件
from fastapi import Request
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={
        "error": "internal_server_error",
        "message": "服务暂时不可用，请稍后重试",
        "detail": str(exc) if settings.DEBUG else None,
    })

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "error": exc.detail,
        "message": exc.detail,
    })

# Celery任务错误处理
@celery_app.task(bind=True, max_retries=3)
def astock_daily_data(self):
    try:
        data_service.update_daily_data()
    except Exception as exc:
        notification_service.send_sync(
            level='P0', category='system', market='astock',
            title='A股数据更新失败',
            content=f'重试{self.request.retries}/{self.max_retries}: {str(exc)[:200]}',
        )
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))
```

---

## 十、WebSocket管理

```python
# backend/websocket/manager.py
from fastapi import WebSocket
from typing import Dict, Set
import asyncio, json

class WSManager:
    """全局WebSocket连接管理"""
    
    def __init__(self):
        # 通道 → {连接集合}
        self.channels: Dict[str, Set[WebSocket]] = {
            'notifications': set(),
            'forex_realtime': set(),
        }
        # 房间 → {连接集合} (回测/挖掘用run_id/task_id做房间)
        self.rooms: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, ws: WebSocket, channel: str, room: str = None):
        await ws.accept()
        if room:
            self.rooms.setdefault(room, set()).add(ws)
        else:
            self.channels.setdefault(channel, set()).add(ws)
    
    async def disconnect(self, ws: WebSocket, channel: str, room: str = None):
        if room and room in self.rooms:
            self.rooms[room].discard(ws)
        elif channel in self.channels:
            self.channels[channel].discard(ws)
    
    async def push(self, channel: str, data: dict, room: str = None):
        """推送消息到通道或房间"""
        targets = self.rooms.get(room, set()) if room else self.channels.get(channel, set())
        message = json.dumps(data, default=str)
        dead = []
        for ws in targets:
            try:
                await ws.send_text(message)
            except:
                dead.append(ws)
        for ws in dead:
            targets.discard(ws)

ws_manager = WSManager()
```

---

## 十一、Memory中的关键决策归档

以下决策在之前对话中确认但未写入任何文档，现在归档:

| 决策 | 选择 | 理由 | 影响范围 |
|------|------|------|---------|
| WebSocket路由方式 | Method A: payload中注入user_id | 单用户系统，最简单 | websocket/manager.py |
| AI服务层 | 复用现有AI service层，不用MCP tools | 已有LLM调用封装够用 | services/llm_service.py |
| 任务编排 | 单Celery task pipeline | 不需要Airflow级别编排 | tasks/ |
| 知识库 | ChromaDB本地进程模式 | 不需要独立服务 | engines/sandbox.py |

---

## 十二、全局ML模型路线图

### 12.1 11个模型的归属与Phase

| # | 模型 | A股用途 | 外汇用途 | Phase | 状态 |
|---|------|--------|---------|-------|------|
| 1 | **LightGBM** | 因子合成(34因子→综合得分) | 信号过滤(21因子→方向概率) | P0规则版/P1引入ML | 核心 |
| 2 | **随机森林** | baseline对比(LightGBM必须显著胜出) | baseline对比 | P1(A股)/P2(外汇) | baseline |
| 3 | **Optuna** | LightGBM超参搜索+策略参数搜索 | 同左 | P1(A股)/P2(外汇) | 核心 |
| 4 | **XGBoost** | 交叉验证LightGBM(两个都说涨→更可信) | 同左 | P3 | 集成 |
| 5 | **MLP** | 因子合成(2-3层,与LightGBM集成投票) | 信号合成(集成投票) | P3 | 集成 |
| 6 | **GRU** | 日频时序预测(数据量P4才够) | H1时序预测(H1数据量P3够) | P3(外汇)/P4(A股) | 进阶 |
| 7 | **LSTM** | 同GRU但参数更多,过拟合风险更高 | 谨慎,优先用GRU | P4 | 备选 |
| 8 | **CNN** | 未规划(横截面选股不需要) | 1D-CNN K线形态识别(辅助) | P3(外汇) | 可选 |
| 9 | **Transformer** | 预训练时序模型微调 | 同左 | P4(本地MLX) | 远期 |
| 10 | **GNN** | 股票关系图(行业/供应链) | 货币关联网络 | P4 | 远期 |
| 11 | **SVM** | ❌ 不用 | ❌ 不用 | — | LightGBM全面优于 |

### 12.2 按Phase的引入顺序

```
Phase 0 (MVP规则版):
  无ML模型。因子合成用IC加权(规则版)。
  所有AI参数用默认值。

Phase 1 (A股+AI第一批):
  ✅ LightGBM — 因子合成,替代IC加权(必须Sharpe提升>10%+WF验证)
  ✅ Optuna — LightGBM超参搜索 + 策略参数搜索(替代网格搜索)
  ✅ 随机森林 — baseline(LightGBM跑不过说明特征工程有问题)
  
  约束: max_depth≤5, num_leaves≤16, 强正则化
  验证: Purged K-Fold或Walk-Forward(禁止随机split)
  可解释: Top 10 feature importance,无法解释的特征删掉重训

Phase 2 (外汇):
  ✅ LightGBM — 信号过滤(50维特征→方向概率→调整confidence)
  ✅ Optuna — 策略参数搜索(MA周期/RSI阈值/GARCH倍数等)
  ✅ 随机森林 — baseline

Phase 3 (整合优化):
  🔄 XGBoost — 与LightGBM交叉验证
  🔄 MLP(2-3层) — 与LightGBM/XGBoost集成投票
  🔄 GRU — 外汇H1时序预测(H1数据量足够)
  🔄 CNN — 外汇K线形态识别(1D-CNN,辅助信号)
  
  集成投票: 3个模型加权平均,近30日准的权重高
  共识度: 3个都说涨→confidence×1.3, 分歧大→不交易

Phase 4 (Mac Studio + MLX):
  🔮 GRU/LSTM — A股日频时序(数据量终于够)
  🔮 Transformer — 预训练时序模型(Chronos/Kronos)微调
  🔮 GNN — 股票关系图(行业链/供应链/资金流关联)
```

### 12.3 ML模型在架构中的位置

```
所有ML模型统一封装在:
  backend/engines/ml_models.py    — 模型训练/预测/评估
  backend/services/ml_service.py  — 业务逻辑(训练调度/模型选择/集成)

调用方:
  services/signal_service.py      → ml_service.predict()  (A股因子合成)
  services/forex_signal_service.py → ml_service.predict()  (外汇信号过滤)
  services/pipeline_service.py    → ml_service.train()     (AI闭环中重训模型)

模型存储:
  训练好的模型文件: data/models/{market}_{model_type}_{version}.pkl
  模型元数据: model_registry表(已在V5定义)
  
  model_registry记录:
    model_type, market, version, train_date,
    oos_sharpe, feature_importance_json,
    file_path, status(active/candidate/retired)
```

### 12.4 共用的BaseMLPredictor架构

```python
class BaseMLPredictor(ABC):
    """ML预测器基类 — A股和外汇共用"""
    
    @abstractmethod
    def prepare_features(self, data) -> pd.DataFrame:
        """特征工程(每个市场不同)"""
    
    @abstractmethod  
    def prepare_labels(self, data) -> pd.Series:
        """标签生成(每个市场不同)"""
    
    def train_walk_forward(self, data, wf_config) -> dict:
        """Walk-Forward训练(通用框架)"""
    
    def get_feature_importance(self) -> dict:
        """特征重要性(通用)"""

class AStockLGBMPredictor(BaseMLPredictor):
    """A股: 34因子横截面 → 综合得分"""

class ForexLGBMPredictor(BaseMLPredictor):
    """外汇: 50维特征时序 → 方向概率"""

class EnsemblePredictor:
    """多模型集成(Phase 3): LightGBM+XGBoost+MLP加权投票"""
```

### 12.5 AI+量化研究路线图（Phase 3-4远期）

基于20个AI+量化交叉方向分析，以下5个高价值方向纳入远期路线图:

| Phase | 方向 | 实现方式 | 前置条件 |
|-------|------|---------|---------|
| P2-3 | 财经新闻情绪因子 | DeepSeek V3情绪打分→因子库 | akshare新闻数据 |
| P3 | 波动率Transformer预测 | GARCH→LightGBM→Transformer渐进 | 日频数据足够 |
| P3 | 宏观LSTM预测(外汇) | 利率/CPI方向预测→Layer 1宏观因子 | forex_macro_data |
| P4 | GNN股票关联图 | 行业+供应链+基金持仓→图因子 | Mac Studio + stock_graph表 |
| P4 | LSTM因子择时(meta) | 预测因子IC变化→动态权重 | Mac Studio GPU |

不纳入: 加密资产(不做)、高频(日频系统)、可转债(不同赛道)、流动性风控(机构级)

---

## 十三、.env.example 完整版（补充）

```env
# ═══ 数据库 ═══
DATABASE_URL=postgresql+asyncpg://localhost:5432/quantmind
DATABASE_POOL_SIZE=10

# ═══ Redis ═══
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2

# ═══ 数据源 ═══
TUSHARE_TOKEN=your_tushare_token_here
AKSHARE_ENABLED=true

# ═══ LLM ═══
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
ANTHROPIC_API_KEY=sk-ant-xxx
LLM_MONTHLY_BUDGET=500

# ═══ MT5 Adapter (Phase 2, Windows) ═══
MT5_ADAPTER_URL=http://localhost:8001
FOREX_ENABLED=false
# MT5_LOGIN=888888
# MT5_PASSWORD=xxx
# MT5_SERVER=ECMarkets-Demo

# ═══ 通知 ═══
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_ENABLED=false

# ═══ 回测 ═══
RUST_ENGINE_PATH=./rust_engine/target/release/quant-backtest

# ═══ 路径 ═══
DATA_DIR=./data
MODELS_DIR=./data/models
LOGS_DIR=./logs

# ═══ Paper Trading ═══
PAPER_TRADING_ENABLED=true
PAPER_TRADING_INITIAL_CAPITAL=500000

# ═══ 日志 ═══
LOG_LEVEL=INFO
LOG_FILE=logs/quantmind.log
DEBUG=false
```

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. Service层依赖注入（覆盖Service初始化方式）

所有Service统一用FastAPI的`Depends`链注入，**不要手动new**:
```python
# ✅ 正确写法
async def get_backtest_service(db: AsyncSession = Depends(get_db)) -> BacktestService:
    return BacktestService(db)

@router.post("/backtest/submit")
async def submit_backtest(service: BacktestService = Depends(get_backtest_service)):
    ...

# ❌ 错误写法（不要这样）
class BacktestService:
    def __init__(self, db = Depends(get_db)):
        self.notifier = NotificationService()  # 手动new，没有注入session
```

### P2. Celery Task与async Service的混合（确认方案A）

Celery task内部用`asyncio.run()`调用async Service:
```python
@celery_app.task(acks_late=True)  # crash后自动重试
def daily_factor_calc_task():
    asyncio.run(_async_daily_factor_calc())

async def _async_daily_factor_calc():
    async with get_async_session() as session:
        service = FactorService(session)
        await service.calc_daily_factors()
```

### P3. Broker策略模式（新增执行层设计）

Paper/实盘/外汇共用同一套因子→信号→风控链路，唯一区别是执行层:
```python
from abc import ABC, abstractmethod

class BaseBroker(ABC):
    """执行层抽象基类"""
    @abstractmethod
    async def submit_order(self, order: Order) -> Fill: ...
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    async def get_positions(self) -> list[Position]: ...
    @abstractmethod
    async def get_account(self) -> AccountInfo: ...

class SimBroker(BaseBroker):
    """Paper Trading — 虚拟资金+真实行情"""
    ...

class MiniQMTBroker(BaseBroker):
    """A股实盘 — 国金miniQMT（Phase 1）"""
    ...

class MT5Broker(BaseBroker):
    """外汇实盘 — ECMarkets MT5（Phase 2）"""
    ...

def get_broker() -> BaseBroker:
    if settings.EXECUTION_MODE == "paper":
        return SimBroker()
    elif settings.EXECUTION_MODE == "live":
        return MiniQMTBroker()
    elif settings.EXECUTION_MODE == "forex":
        return MT5Broker()
    raise ValueError(f"Unknown EXECUTION_MODE: {settings.EXECUTION_MODE}")
```
切换方式: 环境变量`EXECUTION_MODE=paper`，一行配置搞定。

### P4. 策略版本管理

`strategy_configs.config`是JSONB，每次变更**插入新version行**而不是更新旧行:
```python
# 版本变更
async def update_strategy_config(strategy_id: UUID, new_config: dict):
    current = await get_active_version(strategy_id)
    new_version = current.version + 1
    await insert_config_version(strategy_id, new_version, new_config)
    # 不更新旧行，旧版本保留用于回滚和对比

# 回滚
async def rollback_strategy(strategy_id: UUID, target_version: int):
    await set_active_version(strategy_id, target_version)
```
每个版本有独立回测记录，支持V1 vs V2 vs V3对比。

---

## 开源工具集成规范（从CLAUDE.md迁入）

> 核心原则：统一集成，不是拼凑。所有工具藏在Service内部，换任何一个工具其他层无感知。

### 规则1: 工具只在Service层内部使用，不暴露给外部
```python
# ✅ 正确：Service封装
class FactorService:
    def calculate_rsi(self, prices, period=14):
        result = talib.RSI(prices, timeperiod=period)
        return self._to_factor_values(result)

# ❌ 错误：API直接调工具
@router.get("/factors/rsi")
def get_rsi():
    return talib.RSI(...)
```

### 规则2: 数据格式统一
所有因子不管来源（自写/TA-Lib/Alpha158/GP），最终都是`(code, trade_date, factor_value)`写入factor_values表。下游只读这张表。

### 规则3: 组合优化输出标准化
不管用等权/HRP/风险平价，输出都是`{"600519": 0.05, "000001": 0.04}`。PortfolioBuilder内部切换方法，外部接口不变。

### 规则4: 绩效分析双轨
QuantStats生成HTML报告（给人看）。核心指标（Sharpe/MDD/CI）仍然自己算（给程序用、写入DB）。两者互为验证——不一致说明有bug。

### 规则5: 一个工具一个wrapper
```python
# wrappers/ta_wrapper.py — 统一接口，底层可换
def calculate_indicator(name, prices, **params):
    if name == "RSI":
        return talib.RSI(prices, timeperiod=params.get("period", 14))
```

### 规则6: 配置统一
所有工具参数走param_service或.env，不允许分散在各自配置文件。

### 模块协同矩阵
```
数据层(PG) → FactorService(TA-Lib/Alpha158/自写) → factor_values表
           → SignalService(Alphalens分析/合成) → signals表
           → PortfolioBuilder(Riskfolio-Lib/等权) → {code: weight}
           → RiskService(熔断/Riskfolio-Lib) → 风控检查
           → ExecutionService(miniQMT/SimBroker) → trade_log表
           → PerformanceService(QuantStats+自算指标) → performance_series
每层通过Service接口通信，工具藏在内部。
```

### 引入工具验收标准
- 现有测试全部通过（没破坏任何东西）
- 新工具有wrapper+wrapper测试
- 一年模拟重跑Sharpe偏差<0.01
- factor_values表格式没变、下游无感知
