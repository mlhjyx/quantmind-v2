# CLAUDE.md — QuantMind V2

> **Claude Code 入口文件。启动时自动读取。只含编码必需信息。**
> **详细运行手册**: SYSTEM_RUNBOOK.md（启动链路/数据流/接口契约/模块依赖）

---

## 项目概述

QuantMind V2: 个人A股+外汇量化交易系统，Python-first 全栈。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **当前**: Phase A-F完成, v3.8路线图, PT QMT live运行中, Sharpe基线=1.15(Top-20+无行业约束+PMS), 毕业阈值≈0.56-0.60
- **硬件**: Windows 11 Pro, R9-9900X3D, RTX 5070 12GB(PyTorch cu128), 32GB DDR5
- **PMS**: v1.0阶梯利润保护3层(14:30 Celery Beat检查, v2.0已验证无效不实施)
- **下一步**: 阶段2(盈利公告因子+分钟聚合因子+北向MODIFIER) → 阶段4(CompositeSignalEngine)
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
| 缓存 | 本地Parquet快照(因子/价格), factor_values 352M行→TimescaleDB hypertable |
| 交易 | 国金miniQMT (A股) |

## 因子系统

### 因子池状态
| 池 | 数量 | 说明 |
|----|------|------|
| CORE (Active, PT在用) | 5 | turnover_mean_20, volatility_20, reversal_20(WARNING), amihud_20, bp_ratio |
| FULL | 14 | CORE+扩展(momentum_20等) |
| RESERVE | 1 | vwap_bias |
| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非9.1%, v3.4证伪) |
| DEPRECATED | 8 | momentum_5/10等(冗余或IC衰减) |
| 北向个股RANKING | 15 | nb_ratio_change_5d等, IC反向(direction=-1), G1特征池 |
| LGBM特征集 | 63 | 全部factor_values因子(48核心+15北向, DB自动发现) |

### 因子存储
- **factor_values**: 352M行, TimescaleDB hypertable, 71 chunks ~53GB
- **factor_ic_history**: IC唯一入库点(铁律11), 未入库IC视为不存在
- **Parquet缓存**: `_load_shared_data` 30min→1.6s(1000x), `fast_neutralize_batch` 15因子/17.5min

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
├── SYSTEM_RUNBOOK.md            ← ⭐ 系统运行手册
├── PROGRESS.md                  ← 开发进度
├── LESSONS_LEARNED.md           ← 经验教训（36条）
├── FACTOR_TEST_REGISTRY.md      ← 因子测试注册表（74条）
├── docs/
│   ├── QUANTMIND_V2_DDL_FINAL.sql  ← ⭐ 建表唯一来源（62张表）
│   ├── QUANTMIND_V2_DESIGN_V5.md   ← 总设计文档
│   ├── IMPLEMENTATION_MASTER.md    ← 实施总纲（历史参考，当前用Phase/G/GA编号）
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
│       │   ├── db.py                 # sync psycopg2连接器
│       │   └── trading_calendar.py   # 交易日工具
│       ├── models/              # SQLAlchemy ORM
│       ├── schemas/             # Pydantic请求/响应
│       ├── tasks/               # Celery任务
│       │   ├── celery_app (或 __init__.py)
│       │   ├── mining_tasks.py  # GP挖掘Celery封装
│       │   └── beat_schedule.py # 定时调度配置
│       └── data_fetcher/        # 数据拉取
├── backend/engines/             # ⭐ 核心计算引擎（纯计算无IO）
│   ├── factor_engine.py         # 因子计算
│   ├── factor_profiler.py       # 因子画像V2（48+15因子, 12章节报告）
│   ├── fast_neutralize.py       # 批量中性化（Parquet写入, 17.5min/15因子）
│   ├── backtest_engine.py       # 回测引擎(Hybrid: 向量化+事件驱动)
│   ├── slippage_model.py        # 三因素滑点模型(R4研究)
│   ├── neutralizer.py           # FactorNeutralizer共享模块
│   └── mining/                  # GP因子挖掘子包
│       ├── gp_engine.py         # GP引擎(DEAP+WarmStart+岛屿模型)
│       ├── pipeline_utils.py    # GP管道公开函数
│       ├── factor_dsl.py        # FactorDSL算子集
│       └── pipeline_orchestrator.py  # 闭环编排(部分实现)
├── frontend/src/                # React前端
│   ├── api/                     # API调用层
│   ├── pages/                   # 35个页面
│   ├── components/              # 53个共享组件
│   └── store/                   # Zustand 4个store
├── scripts/
│   ├── run_paper_trading.py     # ⭐ PT主脚本（~1511行，运行期间禁改）
│   ├── monitor_factor_ic.py     # 因子IC监控
│   ├── pt_watchdog.py           # PT心跳监控
│   ├── pg_backup.py             # 数据库备份
│   └── data_quality_check.py    # 数据巡检
├── cache/                       # Parquet缓存（profiler/中性化用）
├── docs/research-kb/            # 研究知识库（failed/findings/decisions）
├── .claude/skills/              # 6个QuantMind自定义skills
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
| IC加权/Lasso等下游优化 | 因子信息量不够时优化下游无效 | v3.5原则16 |

## 策略配置（v1.2→Top-20已部署，PT运行中）
# v1.1→v1.2变更: WLS中性化 + 涨跌停板块 + volume_cap 10% + zscore clip±3 + mergesort
# v1.2→Top-20: 选股15→20, 行业约束25%→无(1.0), PMS v1.0阶梯保护(.env驱动)

```
因子: turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio
合成: 等权平均
选股: Top 20 (PT_TOP_N=20)
调仓: 月度（月末最后交易日）
约束: 行业上限=无(PT_INDUSTRY_CAP=1.0), 换手率上限 50%, 100股整手(floor), 日均成交额≥5000万(20日均)
基线(旧): Sharpe=0.91（2021-2025全5年, Top-15+行业25%, WLS+volume_impact无流动性过滤）, MDD=-43.03%
基线(新,已部署): Sharpe=1.15（Top-20+无行业约束+PMS same_close）, MDD=-35.1%, Calmar=0.83
# 0.91为旧配置5年全量回测值。1.15为当前部署配置。DSR保守估计=0.70-0.85
# run_backtest.py验证(2026-04-06): Sharpe=1.24(同配置3次确定性PASS), MDD=-34.95%, Calmar=0.93
# 1.24 vs 1.15差异0.09待追溯(可能年化方法或PMS执行模式差异)
# FF3归因: Alpha=21.1%/年(t=2.45), 但2023-2025 OOS Alpha仅+6.6%(t=0.58不显著), 近年靠SMB beta盈利
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
| ML Walk-Forward设计/G1结论 | docs/ML_WALKFORWARD_DESIGN.md (v2.1, 1096行) |
| 研究知识库(防重复失败) | `docs/research-kb/` (19条目: 8 failed + 6 findings + 5 decisions) |
| 性能优化最佳实践 | `.claude/skills/quantmind-performance/` |
| 路线图/全面状态/决策历史 | docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.8) |

## 当前进度

- ✅ Phase A-F全部完成（185新测试, 904全量通过, 0回归）
- ✅ R1-R7 研究完成（7份报告, 73项可落地）
- ✅ G1 LightGBM Walk-Forward完成（ML Sharpe=0.68 vs 等权同期0.83, 差距0.15, pipeline保留为评估工具）
- ✅ G2风险平价+G2.5动态仓位: 均无效, 等权是最优权重方案
- ✅ GA2 EVENT回测器完成（mf_divergence IC=9.1%证伪→实际-2.27%, 铁律11由此诞生）
- ✅ 因子画像V2完成（48因子全量画像, 7项推荐逻辑修正, 模板T1=33/T2=4/T11=6/T12=5）
- ✅ 北向研究三轮完成（RANKING→G1池, MODIFIER V1废弃, V2八因子OOS通过）
- ✅ 性能优化（TimescaleDB 2.26.0 + Parquet缓存1000x + GPU 6.2x + Pipeline并行化）
- ✅ 清明改造完成（Servy+Redis5.0+StreamBus+QMT A-lite+PMS v1.0+配置.env化）
- ✅ GitHub+代码质量（mlhjyx/quantmind-v2 private, Ruff 5704→0）
- ✅ ECC/ARIS（8 skills + research-kb 19条 + Continuous Learning hooks）
- 🔨 PT QMT live运行中, Top-20+无行业约束+PMS, 基线Sharpe=1.15
- 🔄 分钟数据全量拉取中（Baostock 5min, 全A股x5年, ~36%完成）
- ⬜ 阶段2: 盈利公告因子+分钟聚合因子+北向MODIFIER → 阶段3: 策略层扩展 → 阶段4: CompositeSignalEngine
- 📋 路线图: QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.8)
---

## 执行标准流程

1. 读本文件了解全局
2. **读 SYSTEM_RUNBOOK.md** 了解系统怎么跑、模块怎么对接
3. 根据任务类型读对应DEV文档（见查阅索引）
4. 编码 → 测试 → 验证
5. 发现需要偏离指令的地方 → **先报告，等确认**
6. 任务完成后更新 SYSTEM_RUNBOOK.md 对应章节（保持RUNBOOK与代码一致）
