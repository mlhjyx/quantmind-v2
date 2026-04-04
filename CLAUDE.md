# CLAUDE.md — QuantMind V2

> **Claude Code 入口文件。启动时自动读取。只含编码必需信息。**
> **详细运行手册**: SYSTEM_RUNBOOK.md（启动链路/数据流/接口契约/模块依赖）

---

## 项目概述

QuantMind V2: 个人A股+外汇量化交易系统，Python-first 全栈。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **当前**: Phase 1, Sprint 1.35 完成, PT v1.2 Day 2/60, **QMT live模式**(SimBroker已禁用), Sharpe基线=0.91（2021-2025全5年volume_impact无流动性过滤）, 毕业阈值=0.315
- **硬件**: Windows 11 Pro, R9-9900X3D, RTX 5070 12GB, 32GB DDR5
- **PMS**: v1.0阶梯利润保护已实现（3层保护, 14:30 Celery Beat检查, 前端页面 /pms）
- **下一步**: PT v1.3切换(Top-20+去行业约束+PMS已配置) → G1 LightGBM
- **调度链路**: 09:31 QMT live执行 → 09:35-15:00 盘中监控 → 15:10 对账 → 16:30 信号 → 17:30 因子衰减

## 技术栈（实际使用，非设计文档）

| 层 | 技术 |
|----|------|
| 后端 | FastAPI + **sync psycopg2** + Celery + Redis |
| 前端 | React 18 + TypeScript + Tailwind 4.1 + ECharts/Recharts + Zustand |
| 数据库 | PostgreSQL 16 (D:\pgdata16, user=xin, db=quantmind) + Redis 5.0.14.1 |
| 事件总线 | Redis Streams (`qm:{domain}:{event_type}`), StreamBus模块 |
| 服务管理 | Servy v7.6 (`D:\tools\Servy`), 替代NSSM |
| 调度 | Windows Task Scheduler (PT) + Celery Beat (GP) |
| 交易 | 国金miniQMT (A股) |

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
├── SYSTEM_RUNBOOK.md            ← ⭐ 系统运行手册
├── PROGRESS.md                  ← 开发进度
├── LESSONS_LEARNED.md           ← 经验教训（36条）
├── FACTOR_TEST_REGISTRY.md      ← 因子测试注册表（74条）
├── docs/
│   ├── QUANTMIND_V2_DDL_FINAL.sql  ← ⭐ 建表唯一来源（43张表）
│   ├── QUANTMIND_V2_DESIGN_V5.md   ← 总设计文档
│   ├── IMPLEMENTATION_MASTER.md    ← 实施总纲（117项/10Sprint）
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
│       │   ├── factor_onboarding.py  # Sprint 1.32: 调用FactorNeutralizer
│       │   ├── db.py                 # sync psycopg2连接器(22行)
│       │   └── trading_calendar.py   # 交易日工具(60行)
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic请求/响应
│       ├── tasks/               # Celery任务
│       │   ├── celery_app (或 __init__.py)
│       │   ├── mining_tasks.py  # GP挖掘Celery封装
│       │   └── beat_schedule.py # 定时调度配置
│       └── data_fetcher/        # 数据拉取
├── backend/engines/             # ⭐ 核心计算引擎（纯计算无IO）
│   ├── factor_engine.py         # 34因子计算
│   ├── backtest_engine.py       # 回测引擎(Hybrid: 向量化+事件驱动)
│   ├── slippage_model.py         # 三因素滑点模型(R4研究)
│   ├── neutralizer.py           # Sprint 1.32: FactorNeutralizer共享模块
│   └── mining/                  # GP因子挖掘子包
│       ├── gp_engine.py         # GP引擎(DEAP+WarmStart+岛屿模型)
│       ├── pipeline_utils.py    # Sprint 1.32: GP管道5个公开函数
│       ├── factor_dsl.py        # FactorDSL算子集
│       └── pipeline_orchestrator.py  # 闭环编排(部分实现)
├── frontend/src/                # React前端
│   ├── api/                     # API调用层
│   ├── pages/                   # 22个页面
│   ├── components/              # 44个共享组件
│   └── store/                   # Zustand 4个store
├── scripts/
│   ├── run_paper_trading.py     # ⭐ PT主脚本（~901行，运行期间禁改）
│   ├── monitor_factor_ic.py     # 因子IC监控
│   ├── pt_watchdog.py           # PT心跳监控
│   ├── pg_backup.py             # 数据库备份
│   └── data_quality_check.py    # 数据巡检
└── backend/tests/               # 1876+个测试
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

### PT核心参数（.env驱动）

- `PT_TOP_N`: 选股数量（当前=20），改后重启服务生效
- `PT_INDUSTRY_CAP`: 行业上限（当前=1.0=不限），改后重启服务生效
- 读取路径: `.env` → `config.py` → `signal_engine.py:PAPER_TRADING_CONFIG`

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
| QuantMind-FastAPI | uvicorn --workers 2, port 8000 | Redis, PostgreSQL16 | logs/fastapi-std{out,err}.log |
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
- PG安装路径: `D:\pgsql\bin\pg_ctl.exe`, 数据目录: `D:\pgdata16`

### SQL
- SQLAlchemy text() 中用 `CAST(:param AS type)`，**禁止** `::type` 语法（LL-034）
- 所有 (symbol_id, date) 组合必须有联合索引
- 金额字段列注释标明单位

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
13. **市场逻辑可解释性（G10 Gate）** — 新因子注册必须附带经济机制描述「[市场行为]→[因子信号]→[预测方向]」。IC显著不是充分理由，无法解释预测力来源的因子不允许进入Active池（reversal_20在momentum regime下反转的教训）

### 工作原则补充
14. **新因子必须有可解释的市场逻辑假设** — 不接受"IC显著就行"。每个候选因子必须有经济机制假设且与因子表达式语义对齐
15. **相似因子不是新因子** — GP/LLM产出的候选因子IC计算前必须先过G9新颖性Gate。48个量价因子的窗口变体不算新因子
16. **回测成本实现必须与实盘对齐** — 新策略正式评估前必须确认H0验证通过（理论成本vs QMT实盘误差<5bps）

## 因子审批硬标准

- t > 2.5 硬性下限（Harvey Liu Zhu 2016）
- BH-FDR校正: M = FACTOR_TEST_REGISTRY.md 累积测试总数（当前M=202）
- 与现有Active因子 corr < 0.7, 选股月收益 corr < 0.3
- 中性化后IC必须验证（原始IC和中性化IC并列展示）
- 因子预处理顺序: **去极值(MAD 5σ) → 填充(行业中位数) → 中性化(行业+市值WLS) → z-score**（不可变）

## 策略配置（v1.2，PT运行中）
# v1.1→v1.2变更: WLS中性化 + 涨跌停板块 + volume_cap 10% + zscore clip±3 + mergesort
# v1.1归档: Day 0-3 (2026-03-23~27), NAV终值=995,338

```
因子: turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio
合成: 等权平均
选股: Top 15
调仓: 月度（月末最后交易日）
约束: 行业上限 25%, 换手率上限 50%, 100股整手(floor), 日均成交额≥5000万(20日均)
基线: Sharpe=0.91（2021-2025全5年, WLS+volume_impact+无流动性过滤）, MDD=-43.03%
# 0.91为5年全量回测确认值。保守估计(DSR+风格调整)=0.70-0.85。PT毕业阈值=0.45×0.7=0.315
# 新最优配置X-D(未部署): Top-20+无行业约束+PMS(same_close) → Sharpe=1.15, MDD=-35.1%
成本: 佣金万0.854(国金实际) + 印花税0.05%(卖出) + 过户费0.001% + volume_impact滑点
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

**PT期间禁止修改**: signal_service.py / execution_service.py / run_paper_trading.py 中 v1.2 链路代码

## 文档查阅索引

| 你要做什么 | 读这个 |
|-----------|--------|
| 了解系统怎么跑/模块怎么对接 | **SYSTEM_RUNBOOK.md** ⭐ |
| 查Sprint计划/下一步 | docs/IMPLEMENTATION_MASTER.md |
| 建数据库表 | docs/QUANTMIND_V2_DDL_FINAL.sql ⭐ |
| 接入数据源 | docs/TUSHARE_DATA_SOURCE_CHECKLIST.md ⭐ |
| 写后端Service/理解分层 | docs/DEV_BACKEND.md (§3分层/§4数据流/§5协同矩阵) |
| 写回测引擎/理解Hybrid架构 | docs/DEV_BACKTEST_ENGINE.md (§3Hybrid/§4接口) |
| 写因子计算 | docs/DEV_FACTOR_MINING.md |
| 写前端页面 | docs/DEV_FRONTEND_UI.md |
| 写调度任务 | docs/DEV_SCHEDULER.md |
| 写GP相关 | docs/GP_CLOSED_LOOP_DESIGN.md (FactorDSL/WarmStart) |
| 写风控 | docs/RISK_CONTROL_SERVICE_DESIGN.md (L1-L4状态机) |
| 查设计决策 | docs/DESIGN_DECISIONS.md (93+40项) |

## 当前进度

- ✅ Phase 0 设计完成（11文档, 8004行, 93+40决策）
- ✅ R1-R7 研究完成（7份报告, 73项可落地）
- ✅ Sprint 1.32-1.35 完成（中性化+GP验证+实时数据+前端重构+审计）
- ✅ G2研究完成（25+组回测: 权重优化无效, PMS有效, Top-20>15, 去行业约束）
- ✅ 全面数据审计完成（0❌9⚠️, FF3: Alpha=21.1% t=2.45, SMB beta=0.83）
- ✅ 因子盘点完成（37个DB因子, 20候选入池, 3个P0因子冗余, GP管线0产出）
- ✅ 清明改造完成（Servy+Redis5.0+StreamBus+QMT A-lite+PMS v1.0+配置.env化）
- 🔨 PT v1.2 运行中 Day 2/60, Sharpe基线=0.91
- ⬜ 下一步: PT v1.3切换(Top-20+去约束+PMS已配置) → G1 LightGBM
- 📋 路线图: QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.2)
---

## 执行标准流程

1. 读本文件了解全局
2. **读 SYSTEM_RUNBOOK.md** 了解系统怎么跑、模块怎么对接
3. 根据任务类型读对应DEV文档（见查阅索引）
4. 编码 → 测试 → 验证
5. 发现需要偏离指令的地方 → **先报告，等确认**
6. 任务完成后更新 SYSTEM_RUNBOOK.md 对应章节（保持RUNBOOK与代码一致）
