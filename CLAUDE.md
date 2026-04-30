# CLAUDE.md — QuantMind V2

> **Claude Code 入口文件。启动时自动读取。只含编码必需信息。**
> **系统现状**: SYSTEM_STATUS.md（环境/数据库/代码/架构全景）
> **铁律 SSOT (v3.0, 2026-04-30)**: [IRONLAWS.md](IRONLAWS.md) — 完整铁律 (1-44 + X9 + X10) + tier 标识 (T1/T2/T3) + LL/ADR backref. 本文件铁律段已 reference 化, 详 [ADR-021](docs/adr/ADR-021-ironlaws-v3-refactor.md).
> **D 决议 (4-30 user 决议)**: D-1=A 硬 scope (仅铁律段 reference) / D-2=A 仅 X10 inline / D-3=A ADR-021 编号锁定.
> **Step 6.3b 重构 (2026-04-30/05-01)**: 全文件温和精简 (Path C, 0 新文件创建). 目录结构 / 已知失败方向 / 策略配置 / 当前进度 4 段大幅精简, 详细历史→ SYSTEM_STATUS.md / docs/audit/. ADR-021 §4.5 "~150 行" target 实测与 SSOT 现实冲突 (STOP-1+STOP-2 双触发), Path C 折中 (~530 行), 详 [Step 6.3b STATUS_REPORT](docs/audit/STATUS_REPORT_2026_05_01_step6_3b.md).

---

## 项目概述

QuantMind V2: 个人A股+外汇量化交易系统，Python-first 全栈。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **当前**: Phase A-F + Step 0→6-H 重构 + 研究收束完成. PT 配置 = CORE3+dv_ttm WF OOS Sharpe=0.8659 (2026-04-12 PASS). PT 真账户 0 持仓 + cash ¥993,520 (2026-04-29 user 决议清仓, 详 [SHUTDOWN_NOTICE_2026_04_30](docs/audit/SHUTDOWN_NOTICE_2026_04_30.md)). 主线 = Wave 4 MVP 4.1 Observability (batch 1+2.1+2.2 ✅).
- **硬件**: Windows 11 Pro, R9-9900X3D, RTX 5070 12GB(PyTorch cu128), 32GB DDR5
- **PMS**: v1.0阶梯利润保护3层 — **已并入 Wave 3 MVP 3.1 Risk Framework** (ADR-010, PMSRule L1/L2/L3 14:30 Beat)
- **下一步**: Wave 4 MVP 4.1 batch 3.x (17 scripts SDK migration, 进行中) + Wave 4 剩 4.2/4.3/4.4. PT 重启 gate prerequisite 见 [SHUTDOWN_NOTICE_2026_04_30 §9](docs/audit/SHUTDOWN_NOTICE_2026_04_30.md). 历史 V4 路线图 (Phase 1.1-3 + Phase 4) 全 ✅ 或 NO-GO 沉淀, 详 SYSTEM_STATUS.md §0 / [QPB v1.16](docs/QUANTMIND_PLATFORM_BLUEPRINT.md).

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
| 缓存 | 本地Parquet快照(backend/data/parquet_cache.py按年分区), factor_values 840M行→TimescaleDB hypertable |
| 交易 | 国金miniQMT (A股) |
| Portfolio优化 | riskfolio-lib 7.2.1 (MVO/RP/BL, 阶段2评估) |
| 向量化回测 | vectorbt 0.28.5 (Numba加速, 待评估快速筛选用) |

## 因子系统

### 因子池状态
| 池 | 数量 | 说明 |
|----|------|------|
| CORE (Active, PT在用) | 4 | turnover_mean_20(-1), volatility_20(-1), bp_ratio(+1), dv_ttm(+1) — **WF OOS Sharpe=0.8659, MDD=-13.91%** (2026-04-12 PASS) |
| CORE5 (前任, 回测基线) | 5 | turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio — regression_test基线对照用 |
| PASS候选 | 32+16 | FACTOR_TEST_REGISTRY.md中PASS状态因子(含Alpha158六+PEAD-SUE) + 16微结构因子(Phase 3E neutral IC PASS+noise ROBUST, 但WF等权加入FAIL) |
| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非9.1%, v3.4证伪) |
| DEPRECATED | 5 | momentum_5/momentum_10/momentum_60/volatility_60/turnover_std_20 |
| 北向个股RANKING | 15 | nb_ratio_change_5d等, IC反向(direction=-1), G1特征池 |
| LGBM特征集 | 70 | 全部factor_values因子(48核心+15北向+7新因子Phase2.1, DB自动发现) |

### 因子存储 (2026-04-30 Session 45 D3-B 实测)
- **factor_values**: 840,478,083 行 (~172 GB, TimescaleDB hypertable 152 chunks)
- **factor_ic_history**: 145,894 行 (~36 MB), IC唯一入库点 (铁律 11), 未入库IC视为不存在
- **minute_bars**: 190,885,634 行 (~36 GB), 5年(2021-2025), Baostock 5分钟K线, 2537只股票(0/3/6开头, 无BJ)
- **klines_daily**: 11,776,616 行 (~4 GB, TimescaleDB hypertable 53 chunks)
- **daily_basic**: 11,681,799 行 (~3.7 GB)
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

## 目录结构 (high-level)

> 完整目录树详见 [DEV_BACKEND.md §一](docs/DEV_BACKEND.md). 本节仅列顶层 + 关键 anchor.

```
quantmind-v2/
├── CLAUDE.md / IRONLAWS.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md  # 根目录 5 doc (铁律 22 同步)
├── docs/
│   ├── QUANTMIND_V2_DDL_FINAL.sql              # ⭐ 建表来源
│   ├── QUANTMIND_V2_SYSTEM_BLUEPRINT.md        # ⭐ 当前总设计真相源
│   ├── QUANTMIND_PLATFORM_BLUEPRINT.md         # ⭐ 平台化路线图 (QPB v1.16)
│   ├── DEV_BACKEND.md / DEV_BACKTEST_ENGINE.md / DEV_FACTOR_MINING.md / DEV_FRONTEND_UI.md / DEV_SCHEDULER.md / DEV_PARAM_CONFIG.md / DEV_AI_EVOLUTION.md / DEV_FOREX.md / DEV_NOTIFICATIONS.md
│   ├── adr/                                     # 架构决议 (ADR-001 ~ ADR-022)
│   ├── audit/                                   # 一次性诊断 / STATUS_REPORT
│   ├── mvp/                                     # MVP 设计稿 (≤2 页, 铁律 24)
│   ├── research-kb/                             # 研究知识库 (failed / findings / decisions)
│   ├── runbook/cc_automation/                   # CC 可触发 ops runbook
│   └── TUSHARE_DATA_SOURCE_CHECKLIST.md / SETUP_DEV.md
├── backend/
│   ├── app/                                     # FastAPI app (main / config / api / core / services / models / schemas / tasks / data_fetcher)
│   ├── platform/                                # ⭐ Wave 1+2+3 Platform 12 Framework + 6 升维 (data / factor / strategy / signal / backtest / eval / observability / config / ci / knowledge / resource / backup)
│   ├── engines/                                 # 核心计算引擎 (factor_engine / backtest / fast_neutralize / config_guard / slippage_model / mining)
│   ├── migrations/                              # SQL migration (幂等 + rollback 配对)
│   ├── data/                                    # Data 层 (parquet_cache 等)
│   └── tests/                                   # 100+ test files (Session 9 实测 2864 pass / 24 fail baseline)
├── frontend/src/                                # React (api / pages / components / store)
├── scripts/                                     # ⭐ run_paper_trading / run_backtest / qmt_data_service / health_check / pt_watchdog / pg_backup / approve_l4 / cancel_stale_orders / data_quality_check / monitor_factor_ic / registry / knowledge / archive / research
├── configs/                                     # YAML 配置 (pt_live / backtest_5yr / backtest_12yr)
├── config/hooks/                                # Git hooks (pre-push 含 X10 + smoke)
├── cache/                                       # Parquet 缓存 + baseline (regression 锚点)
├── docs/research-kb/                            # decisions / failed / findings
└── .claude/skills/                              # 7 自定义 skills
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

- **当前实施**: 已并入 Wave 3 MVP 3.1 Risk Framework (ADR-010), PMSRule L1/L2/L3 在 risk-daily-check Celery Beat (14:30) 触发
- 三层保护: L1(浮盈>30%+回撤>15%), L2(>20%+>12%), L3(>10%+>10%)
- 配置在.env: `PMS_ENABLED`, `PMS_LEVEL{1,2,3}_GAIN`, `PMS_LEVEL{1,2,3}_DRAWDOWN`
- 旧版 PMS Beat (`pms.py` daily_pipeline 调用 + `api/pms`) 已 deprecated (PR #34 停 Beat + 去重)

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

## 铁律（v3.0 reference, 完整内容见 [IRONLAWS.md](IRONLAWS.md)）

> **本段已 reference 化** ([ADR-021](docs/adr/ADR-021-ironlaws-v3-refactor.md), 2026-04-30 Step 6.2). 完整铁律 (1-44 编号 + X9 + X10 + 候选 X1/X3/X4/X5 + 跳号 X2/X6/X7 + 撤销 X8 历史决议) 沉淀到 [IRONLAWS.md](IRONLAWS.md) 作 SSOT.
>
> **历史编号保持不变** (防其他文档引用漂移). DEPRECATED 占位保留 (条目 2 合并入 25).
> **测试**: 10 年后此条仍成立? "是, 只是实现方式变了" → 保留. "否, 某阶段后不适用" → 不该是铁律 (应入 Blueprint).

### Tier 索引 (T1 强制 / T2 警告 / T3 建议)

- **T1 强制 (31 条, 违反 → block PR / 真金风险)**: 1 / 4 / 5 / 6 / 7 / 8 / 9 / 10 / 10b / 11 / 12 / 13 / 14 / 15 / 16 / 17 / 18 / 19 / 20 / 25 / 29 / 30 / 31 / 32 / 33 / 34 / 35 / 36 / 41 / 42 / 43
- **T2 警告 (14 条, 违反 → 提示 + commit message 写 reason)**: 3 / 21 / 22 / 23 / 24 / 26 / 27 / 28 / 37 / 38 / 39 / 40 / 44 (X9) / **X10 (新)**
- **T3 建议**: 本版本 0 条 (留 Step 6.2.5+ promote)
- **DEPRECATED**: 条目 2 (合并入 25)
- **候选未 promote (Step 6.2.5+)**: X1 (Claude 边界) / X3 (.venv fail-loud) / X4 (死码月度 audit) / X5 (文档单源化)
- **跳号 / 撤销 (历史决议保留)**: X2 / X6 / X7 (跳号未定义) / X8 (撤销, T0-17 撤销同源)

### 编号简述索引 (link IRONLAWS.md §X.YY 完整)

#### 工作原则类 (1-3) — IRONLAWS.md §2

1. [T1] 不靠猜测做技术判断 — 外部 API/数据接口必须先读官方文档确认
2. [DEPRECATED] ~~下结论前验代码~~ — 已并入 25
3. [T2] 不自行决定范围外改动 — 先报告建议和理由

#### 因子研究类 (4-6) — IRONLAWS.md §3

4. [T1] 因子验证用生产基线+中性化 — raw IC + neutralized IC 并列, 衰减>50%标记虚假 alpha (LL-013/014)
5. [T1] 因子入组合前回测验证 — paired bootstrap p<0.05 vs 基线 (LL-017)
6. [T1] 因子评估前确定匹配策略 — RANKING/FAST_RANKING/EVENT 框架不混用 (LL-027)

#### 数据与回测类 (7-8) — IRONLAWS.md §4

7. [T1] IC/回测前确认数据地基 — universe 对齐 + 无前瞻偏差 + 数据质量
8. [T1] 任何策略改动必须 OOS 验证 — walk-forward / paired bootstrap p<0.05 硬门槛

#### 系统安全类 (9-11) — IRONLAWS.md §5

9. [T1] 所有资源密集任务必须经资源仲裁 — 全局原则 (PG OOM 2026-04-03)
10. [T1] 基础设施改动后全链路验证 — 清明改造教训
    - **10b** 生产入口真启动验证 — `pytest -m smoke` 必须全绿 (MVP 1.1b shadow fix)
11. [T1] IC 必须有可追溯的入库记录 — factor_ic_history 唯一入库点 (mf_divergence 教训)

#### 因子质量类 (12-13) — IRONLAWS.md §6

12. [T1] G9 Gate 新颖性可证明性 — AST 相似度 > 0.7 拒绝 (AlphaAgent KDD 2025)
13. [T1] G10 Gate 市场逻辑可解释性 — 必须附带「市场行为→因子信号→预测方向」 (reversal_20 教训)

#### 重构原则类 (14-17, Step 6-B) — IRONLAWS.md §7

14. [T1] 回测引擎不做数据清洗 — DataPipeline 入库验证, Engine 不猜单位
15. [T1] 任何回测结果必须可复现 — `(config_yaml_hash, git_commit)` + max_diff=0
16. [T1] 信号路径唯一且契约化 — 生产/回测/研究走同一 SignalComposer→PortfolioBuilder 路径
17. [T1] 数据入库必须通过 DataPipeline — 禁裸 INSERT (ADR-0009). **例外条款**: subset-column UPSERT 走手工 partial UPSERT (LL-066, PR #43/#45)

#### 成本对齐 (18) — IRONLAWS.md §8

18. [T1] 回测成本实现必须与实盘对齐 — H0 验证 < 5bps + 季度复核

#### IC 口径统一 (19, Step 6-E) — IRONLAWS.md §9

19. [T1] IC 定义全项目统一 — 走 `backend/engines/ic_calculator.py` (`neutral_value_T1_excess_spearman` v1.0.0)

#### 因子噪声鲁棒性 (20, Step 6-F) — IRONLAWS.md §10

20. [T1] 因子噪声鲁棒性 G_robust — 5% 噪声 retention ≥ 0.95 / 20% ≥ 0.50

#### 工程纪律类 (21-24, Step 6-H 后) — IRONLAWS.md §11

21. [T2] 先搜索开源方案再自建 — Qlib/RD-Agent/alphalens (90% 重叠)
22. [T2] 文档跟随代码 — CLAUDE.md/SYSTEM_STATUS/DEV_*/Blueprint 同步或 `NO_DOC_IMPACT`
23. [T2] 每个任务独立可执行 — 不允许任务依赖未实现模块
24. [T2] 设计文档必须按抽象层级聚焦 — MVP ≤2页 / Framework ≤5页 / Blueprint TOC 必含

#### CC 执行纪律类 (25-28) — IRONLAWS.md §12

25. [T1] 代码变更前必读当前代码验证 — 改什么读什么 (含铁律 2 合并)
26. [T2] 验证不可跳过不可敷衍 — 读完整代码 + 交叉对比 + 明确结论
27. [T2] 结论必须明确 (✅/❌/⚠️) 不准模糊 — 不接受"大概没问题"
28. [T2] 发现即报告不选择性遗漏 — 范围外异常也报告

#### 数据完整性类 (29-30, P0-4 2026-04-12) — IRONLAWS.md §13

29. [T1] 禁止写 float NaN 到 DB — RSQR_20 11.5M 行教训
30. [T1] 缓存一致性必须保证 — 下一交易日内生效, 否则视为过期

#### 工程基础设施类 (31-35, S1-S4 审计沉淀) — IRONLAWS.md §14

31. [T1] Engine 层纯计算 — `backend/engines/**` 不读写 DB/HTTP/Redis (Phase C 落地)
32. [T1] Service 不 commit — 事务边界由调用方 (Router/Celery) 管
33. [T1] 禁止 silent failure — fail-safe / fail-loud / `# silent_ok` 注释三选一
34. [T1] 配置 single source of truth — `config_guard` 启动硬 raise
35. [T1] Secrets 环境变量唯一 — 0 fallback 默认值 / `.env` 必 `.gitignore`

#### 实施者纪律类 (36-41, 2026-04-17 新增) — IRONLAWS.md §15

36. [T1] 代码变更前必核 precondition — 依赖 / 老路径 / 测试数据三项核
37. [T2] Session 关闭前必写 handoff — `memory/project_sprint_state.md` 顶部
38. [T2] Platform Blueprint 是唯一长期架构记忆 — QPB 跨 session 真相源
39. [T2] 双模式思维 — 架构/实施切换必须显式声明
40. [T2] 测试债务不得增长 — 新增 fail 禁合入 (baseline 沿用 pre-push diff)
41. [T1] 时间与时区统一 — UTC 内部 + Asia/Shanghai 展示 + TradingDayProvider

#### PR 治理类 (42) — IRONLAWS.md §16

42. [T1] PR 分级审查制 (Auto mode 缓冲层) — `docs/**` 直 push / `backend/**` 必走 PR + reviewer + AI 自 merge

#### schtask 硬化类 (43) — IRONLAWS.md §17

43. [T1] schtask Python 脚本 fail-loud 硬化标准 — 4 项清单 (PG timeout / FileHandler delay / boot probe / 顶层 try/except)

#### X 系列治理类 (44 X9 + X10 新) — IRONLAWS.md §18

44. [T2] **(X9)** Beat schedule / config 注释 ≠ 真停服, 必显式 restart — schedule 类 PR 必含 post-merge ops checklist (LL-097)

**X10 (新, 2026-04-30 Step 6.2 PR 落地)** [T2]: **AI 自动驾驶 detection — 末尾不写 forward-progress offer**
- **主条款**: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作. 等 user 显式触发. 反例 → STOP.
- **子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件. 必须显式核 D 决议链全部前置, 才能进入下一步.
- **触发 case**: PR #171 PT 重启 gate 7/7 PASS 后 CC 自动 offer "schedule agent 5d dry-run reminder", user 4-30 撤回 + 强制走 Step 5/6/7/T1.4-7 完整路径. 详 [LL-098](LESSONS_LEARNED.md) + [IRONLAWS.md §18](IRONLAWS.md).

### 引用规范

- **新引用**: 直接 link `IRONLAWS.md §X.YY` (e.g. `IRONLAWS.md §18 X10`)
- **历史引用** (CLAUDE.md inline 时代写的 "铁律 33"): 沿用编号, 仍可走本段 reference 找到 link

## 因子审批硬标准

- t > 2.5 硬性下限（Harvey Liu Zhu 2016）
- BH-FDR校正: M = FACTOR_TEST_REGISTRY.md 累积测试总数（当前 SSOT 显示 M=213, 2026-04-11 末次更新; Phase 3B/3D/3E 实验未沉淀但全 FAIL 不改 active 状态, 详 [FACTOR_TEST_REGISTRY.md](FACTOR_TEST_REGISTRY.md) §累积统计）
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

## 已知失败方向（high-level, 完整列表见 [docs/research-kb/failed/](docs/research-kb/failed/) + [docs/research-kb/decisions/](docs/research-kb/decisions/)）

> 30+ 失败方向已沉淀到 research-kb (8 failed + 25 findings + 5 decisions, Step 6.4 G1 实测修订). 本节仅列**最关键**的方向 (新研究启动前必读), 完整历史 + 详细论据 走 research-kb.

| 关键失败方向 | 结论 | 来源 |
|---|---|---|
| 风险平价 / 最小方差权重 | 等权最优, 降风险 = 降 Alpha (小盘暴露) | G2 7组实验 |
| 同因子换 ML 模型 / 完美预测 + MVO | ML Sharpe < 等权, portfolio 优化在预测完美时无增量 (G1 / Step 6-H / Phase 2.1 / 2.2 / 3D 5 次独立验证) | G1 LightGBM + Phase 系列 |
| Universe filter 替代 SN | Alpha 100% 微盘, 收窄 universe 毁灭 alpha | Phase 2.4 Part 1 |
| 第 5 因子加入 CORE3+dv_ttm | 8 个 P1 候选全 FAIL, **CORE3+dv_ttm = 等权 alpha 上限** (Phase 3B + 3E 双重确认) | Phase 3B / 3E-II |
| Phase 3D LightGBM ML Synthesis | 4 实验全 FAIL, **ML 预测层 CLOSED** | Phase 3D |
| Vol-targeting / DD-aware Modifier | 无改善或更差, **Partial SN b=0.50 是唯一有效 Modifier** | Step 6-G / 6-H |
| Regime 线性检测 / 动态 beta | 5 指标全 p>0.05, static b=0.50 > dynamic / binary | Step 6-E / 6-H |
| RD-Agent / Qlib 数据层迁移 | 三重阻断 / .bin 双份数据 / 回测无 PMS 涨跌停 | 阶段0 调研 |
| E2E 可微 Sharpe Portfolio 优化 | sim-to-real gap 282%, A 股交易成本不可微分 | Phase 2.1 Layer2 |
| PMS v2.0 组合级保护 | p=0.655 等于随机, 2022 慢熊 0 触发 | v3.6 验证 |
| LLM 自由生成因子 | IC=0.006-0.008, 需数据驱动 prompt | 5 次测试 |
| mf_divergence 独立策略 | IC=-2.27% (非 9.1%), 14 组回测全负 | GA2 证伪 |

## 策略配置（CORE3+dv_ttm WF PASS, PT配置已更新 2026-04-12）

> **配置来源**: [configs/pt_live.yaml](configs/pt_live.yaml) (Step 4-B, 铁律 15 要求 YAML 驱动)
> **回测入口**: `python scripts/run_backtest.py --config configs/pt_live.yaml`
> **历史基线演进 + 漂移说明 + Session 10 P0 表 + Session 20 cutover** 详 [SYSTEM_STATUS.md §0](SYSTEM_STATUS.md).

```
因子: turnover_mean_20(-1) / volatility_20(-1) / bp_ratio(+1) / dv_ttm(+1)  [CORE3+dv_ttm, 2026-04-12 WF PASS]
合成: 等权平均
选股: Top 20 (PT_TOP_N=20)
调仓: 月度（月末最后交易日）
Modifier: Partial Size-Neutral b=0.50 (Step 6-H 验证, .env PT_SIZE_NEUTRAL_BETA=0.50)
约束: 行业上限=无 (PT_INDUSTRY_CAP=1.0), 换手率上限 50%, 100 股整手, 日均成交额 ≥ 5000 万 (20 日均)
排除: 北交所 BJ 股 + ST + 停牌 + 新股 (list<60 天)
成本: 佣金万 0.854 (国金实际, min 5 元) + 印花税 (2023-08-28 前 0.1%, 后 0.05%) + 过户费 0.001% + 三因素滑点 (spread+impact+overnight_gap)
基线: 5yr Sharpe=0.6095 / 12yr Sharpe=0.3594 / SN b=0.50 inner Sharpe=0.68 / WF OOS Sharpe=0.6521 (CORE5+SN) → 0.8659 (CORE3+dv_ttm+SN)
```

**因子健康状态** (2026-04-18 Session 5 factor_lifecycle 实测):
- turnover_mean_20 / volatility_20 / bp_ratio: ✅ active
- dv_ttm: ⚠️ active → warning (Session 5 lifecycle, ratio=0.517 < 0.8). PT 生产配置仍包含, 周五 19:00 lifecycle 再评估.
- amihud_20 / reversal_20: CORE5 基线保留, 不参与 PT 信号.

**PT 状态 (2026-04-30 Session 45 实测真账户)**:
- xtquant API 4-30 14:54: positions=0 / cash=¥993,520.16 / market_value=0
- **清仓 v4 hybrid narrative** (PR #169): 17 股 CC 4-29 10:43:54 emergency_close + 1 股 (688121.SH 卓然新能 4500 股) 4-29 跌停 cancel → 4-30 user GUI sell
- **PT 重启 gate prerequisite** (Step 6.4 G1 实测修订, 沿用 Step 6.3a §2.1 closed status):
  - ✅ **已 closed (代码层)**: T0-11 (F-D3A-1, PR #170) / T0-15/16/18 (PR #170) / T0-19 (PR #168+#170)
  - ⏳ **真待办 (运维层)**: DB 4-28 stale snapshot 清 + paper-mode 5d dry-run + .env paper→live 用户授权
- 详 [SHUTDOWN_NOTICE_2026_04_30](docs/audit/SHUTDOWN_NOTICE_2026_04_30.md) + ADR-008 命名空间契约

## 文档查阅索引

| 你要做什么 | 读这个 |
|-----------|--------|
| **系统总设计/架构全景** | **docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md** ⭐ (唯一设计真相源, 791行, 16章节) |
| **平台化演进蓝图 (下阶段主线)** | **docs/QUANTMIND_PLATFORM_BLUEPRINT.md** ⭐ (QPB v1.16, 12 Framework + 6 升维 + 4 Wave, 2026-04-17) |
| MVP 设计文档 (Wave 1+) | `docs/mvp/MVP_*.md` (每个 MVP ≤ 2 页, 铁律 24) |
| 了解系统现状/模块怎么对接 | **SYSTEM_STATUS.md** ⭐ |
| 建数据库表 | docs/QUANTMIND_V2_DDL_FINAL.sql ⭐ |
| 接入数据源 | docs/TUSHARE_DATA_SOURCE_CHECKLIST.md ⭐ |
| **新环境 bootstrap** (`.pth` + Servy + hooks) | **docs/SETUP_DEV.md** ⭐ (铁律 10b + MVP 1.1b 沉淀) |
| 写后端Service/理解分层 | docs/DEV_BACKEND.md (§3分层/§4数据流/§5协同矩阵) |
| 写回测引擎/理解Hybrid架构 | docs/DEV_BACKTEST_ENGINE.md (§3Hybrid/§4接口) |
| 写因子计算 | docs/DEV_FACTOR_MINING.md |
| 写前端页面 | docs/DEV_FRONTEND_UI.md |
| 写调度任务 | docs/DEV_SCHEDULER.md |
| 写GP相关 | docs/GP_CLOSED_LOOP_DESIGN.md (FactorDSL/WarmStart) |
| 写风控 | docs/RISK_CONTROL_SERVICE_DESIGN.md (L1-L4状态机) |
| 写AI闭环/因子发现 | docs/DEV_AI_EVOLUTION.md (V2.1, 705行) |
| 写外汇模块(⏳) | docs/DEV_FOREX.md (682行, DEFERRED) |
| ML Walk-Forward设计/G1结论 | docs/ML_WALKFORWARD_DESIGN.md (v2.1, 1096行) |
| 研究知识库(防重复失败) | `docs/research-kb/` (38条目: 8 failed + 25 findings + 5 decisions, Step 6.4 G1 实测修订) |
| 性能优化最佳实践 | `.claude/skills/quantmind-performance/` |
| **CC 自动化操作 (runbook)** | **`docs/runbook/cc_automation/00_INDEX.md`** ⭐ (撤 setx / Servy 重启 / 等 ops runbook) |
| 路线图(历史, 已归档) | docs/archive/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.8, 被Blueprint替代) |

## 当前进度 (high-level milestones, 详细 Sprint state 见 [SYSTEM_STATUS.md](SYSTEM_STATUS.md) + Anthropic memory `project_sprint_state.md` frontmatter)

### 累计完成
- ✅ Phase A-F 全部完成（185 新测试, 904 全量通过, 0 回归）
- ✅ R1-R7 研究完成 / 因子画像 V2 完成 / 性能优化 (TimescaleDB + Parquet 1000x + GPU 6.2x)
- ✅ 清明改造完成 (Servy + Redis5.0 + StreamBus + QMT A-lite)
- ✅ Step 0→6-H 重构 + 12 年 OOS 验证 + 研究收束 (2026-04-09~10)

### 重要里程碑 (按时序倒排)

| 阶段 | 状态 | 关键产出 | 详情 |
|---|---|---|---|
| **Wave 4 MVP 4.1 Observability** | 🟡 进行中 | batch 1+2.1+2.2 ✅ (PostgresAlertRouter / MetricExporter / AlertRulesEngine), batch 3.x 17 scripts SDK migration 进行中 | SYSTEM_STATUS §0 + QPB v1.16 |
| **Wave 3 MVP 3.3 Signal-Exec ✅** | 🟢 完结 (Session 40, 2026-04-28) | Stage 3.0 真切换 PR #116, signal_service 内部走 PlatformSignalPipeline | LL-082~088 + memory sprint_state |
| **Wave 3 MVP 3.1 Risk Framework ✅** | 🟢 完结 (Session 30, 2026-04-24) | 6 PR / 65 新 tests / Celery Beat 5 schedule entries 生产激活 | ADR-010 addendum |
| **Wave 2 ✅ 完结** | 🟢 (Session 9, 2026-04-19) | Data Framework / Lineage / MVP 2.1c / 2.2 / 2.3 Sub1+Sub2+Sub3 | SYSTEM_STATUS §0.0 |
| **Wave 1 ✅ 完结 7/7** | 🟢 (2026-04-17) | Platform Skeleton / Config / DAL / Registry / Direction DB 化 / Knowledge Registry | docs/mvp/MVP_1_*.md |
| **铁律 11+17 全链完工** | 🟢 (Session 21-23, 2026-04-21~22) | 28 commits / 16 PR (#31~#45), 3 IC 脚本分工 + 2 schtask wire | LL-066 (DataPipeline subset 例外) |
| **PT 暂停清仓** | ⛔ (2026-04-29 user 决议) | 真账户 0 持仓, cash ¥993,520, 重启 gate prerequisite 见 SHUTDOWN_NOTICE | docs/audit/SHUTDOWN_NOTICE_2026_04_30.md |
| **Phase 3 MVP A 因子生命周期** | 🟡 (2026-04-17) | factor_lifecycle.py + Celery 周五 19:00 调度, 26/26 tests | docs/mvp/ |
| **PT 配置 CORE3+dv_ttm WF PASS** | ✅ (2026-04-12) | Sharpe=0.8659, MDD=-13.91%, 0 negative folds | Phase 2.4 + WF 验证 |
| **Phase 2.1/2.2/3B/3D/3E NO-GO** | ❌ | E2E Fusion / Gate / 第 5 因子 / ML Synthesis / 微结构 — 4 因子 = 等权 alpha 上限 | research-kb/findings + failed |

### 其他状态

- **Sprint 治理基础设施 5 块基石** (2026-04-30, Step 6-6.3a): IRONLAWS.md / ADR-021 / 第 19 条 memory 铁律 / X10+LL-098+pre-push hook / §23 双口径
- **MVP 串行交付**: 完成一个再 plan 下一个, 不预批量写设计稿 (铁律 23/24)
- **测试基线**: 2864 pass / 24 fail (Session 9 末实测, 铁律 40 baseline 保持) + smoke 28 PASS + regression 5yr+12yr max_diff=0

📋 系统蓝图: `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` (当前真相) + `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (演进规划)

---

## CC 自动化操作

`docs/runbook/cc_automation/` 集中存放可触发的 CC ops runbook (e.g. 撤 setx / Servy 全重启 / DB 命名空间修复 / 等). 索引见 [`docs/runbook/cc_automation/00_INDEX.md`](docs/runbook/cc_automation/00_INDEX.md).

**触发模式**: user 一句话 → CC 加载对应 runbook → 自主执行 (前置检查 + 真金 0 风险确认 + 验证清单 + 失败回滚) → STATUS_REPORT 归档. user 0 手工操作.

跟 `docs/audit/` (一次性诊断) / `docs/adr/` (架构决议) / `docs/mvp/` (功能设计) 区分: runbook 是**可重复触发**的运维资产.

---

## 文件归属规则（防腐）

### 根目录只允许以下文件
CLAUDE.md / IRONLAWS.md / SYSTEM_STATUS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md / pyproject.toml / .gitignore
- 新审计/盘点报告 → `docs/audit/` (一次性诊断 / STATUS_REPORT) 或 `docs/reports/`
- 新研究报告 → `docs/research/` 或 `docs/research-kb/`
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
- **总设计 (当前真相)**: `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` ⭐
- **平台化蓝图 (未来 6 月主线)**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` ⭐ (QPB v1.16)
- **MVP 设计**: `docs/mvp/MVP_*.md` (每个 ≤ 2 页, 铁律 24)
- **系统现状**: `SYSTEM_STATUS.md`
- **铁律 SSOT**: `IRONLAWS.md` (v3.0)
- **入口导航**: `CLAUDE.md`（本文件）
- **Schema定义**: `docs/QUANTMIND_V2_DDL_FINAL.sql`
- DESIGN_V5/ROADMAP_V3 已归档至 docs/archive/, SYSTEM_BLUEPRINT 是当前总设计 + PLATFORM_BLUEPRINT 是演进规划

## 执行标准流程

1. 读本文件了解全局
2. **读 SYSTEM_STATUS.md** 了解系统现状、模块怎么对接
3. 根据任务类型读对应DEV文档（见查阅索引）
4. 编码 → 测试 → 验证
5. 发现需要偏离指令的地方 → **先报告，等确认**
6. 任务完成后更新 SYSTEM_STATUS.md 对应章节（保持文档与代码一致）
