# GLOSSARY — SYSTEM_AUDIT_2026_05

**目的**: 新 Claude session / Claude.ai / 新 user 走 audit folder 0 context onboarding 必读 (沿用 framework §6.3 自包含 + WI 7 验证).

**收录原则**: audit md 涉及但**项目内非通用**术语 (e.g. Servy, T0-N, D 决议, 6 块基石, sprint period, etc). 通用术语 (Python, FastAPI, etc) 不收录.

---

## A — 项目核心架构

| 术语 | 定义 | 来源 / 关联 |
|---|---|---|
| **CLAUDE.md** | 项目入口文件 / 编码必需 / Claude Code 启动自动读 | 根目录, sprint period sustained |
| **IRONLAWS.md** | 项目铁律 SSOT (v3.0.3, 44 条 + X9 + X10 候选) | 根目录, sprint period 6 块基石之一 |
| **LESSONS_LEARNED.md** | 历史教训累计 (LL-001 ~ LL-098) | 根目录, sprint period sustained |
| **FACTOR_TEST_REGISTRY.md** | 因子审批累积统计 (M=213) | 根目录, BH-FDR 校正基准 |
| **SYSTEM_STATUS.md** | 系统现状描述 (路线图 + Sprint period 进度) | 根目录, sprint period sustained |
| **QPB / Platform Blueprint** | docs/QUANTMIND_PLATFORM_BLUEPRINT.md (v1.16, 12 Framework + 6 升维 + 4 Wave) | 平台化路线图 SSOT |
| **System Blueprint** | docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md (791 行, 16 章节) | 当前总设计真相源 |
| **DDL_FINAL** | docs/QUANTMIND_V2_DDL_FINAL.sql (建表唯一来源) | 数据 schema SSOT |

## B — 治理 + 协作

| 术语 | 定义 | 来源 / 关联 |
|---|---|---|
| **D 决议链** | User-Claude 显式决议 (D1-D78), 沿用 sprint period sustained | sprint state handoff frontmatter |
| **D72-D78** | sprint period 4 次反问 + 本审查决议 (一次性 + 0 修改 + 0 时长) | FRAMEWORK.md §0.1 |
| **Sprint period** | sprint period 22 PR (#172-#181 + 之前) 治理基础设施跨日链 | sprint state handoff |
| **6 块基石** | sprint period 治理沉淀: IRONLAWS SSOT / ADR-021 编号锁定 / ADR-022 反 anti-pattern / 第 19 条 memory 铁律 / X10+LL-098+pre-push hook / §23 双口径 | FRAMEWORK §0 + sprint state |
| **ADR-021** | IRONLAWS v3 拆分 + reference 化 (sprint period 6 块基石之一) | docs/adr/ADR-021-ironlaws-v3-refactor.md |
| **ADR-022** | sprint period treadmill 反 anti-pattern + TIER0_REGISTRY (sprint period 6 块基石之一) | docs/adr/ADR-022 |
| **LL-098** | "AI 自动驾驶 detection — 末尾不写 forward-progress offer" 教训 (X10 候选铁律来源, sprint period 第 13 次 stress test) | LESSONS_LEARNED.md / IRONLAWS §18 X10 |
| **Tier 0 / T0-N** | 真金 P0 待修清单 (T0-1 ~ T0-19, sprint period 9 closed + 9 待修分布) | docs/audit/TIER0_REGISTRY.md (sprint period PR #180 新建) |
| **5 维度 / 8 方法论 / 13 领域 / 14 类** | Claude framework 设计 (FRAMEWORK.md §1) | FRAMEWORK.md |
| **8 维度 / 14 方法论 / 16 领域 / 22 类** | CC 实测决议扩 framework (本审查实施) | blind_spots/05_framework_self_audit.md §3.1 |
| **第 19 条铁律** | "memory + handoff 数字必 SQL verify before 写, 不假设" (sprint period 累计 9 次 verify) | IRONLAWS.md |
| **§22 audit log** | IRONLAWS §22 历史 audit 链 (ADR-022 反 §22 entry 滥用) | IRONLAWS §22 |
| **§23 双口径** | IRONLAWS §23 双口径 (沿用 sprint period 6 块基石之一) | IRONLAWS §23 |

## C — 服务 / 调度 / 真账户

| 术语 | 定义 | 来源 / 关联 |
|---|---|---|
| **Servy** | Windows 服务管理工具 v7.6 (替代 NSSM, 2026-04-04 迁移) | D:\tools\Servy\servy-cli.exe |
| **Servy 4 服务** | QuantMind-FastAPI / Celery / CeleryBeat / QMTData | CLAUDE.md §部署规则 |
| **QMT / miniQMT** | 国金 miniQMT 交易端 (账户 81001102) | E:\国金QMT交易端模拟 |
| **xtquant** | QMT Python SDK (.venv/Lib/site-packages/Lib/site-packages 双层嵌套) | CLAUDE.md §xtquant 规则 |
| **QMT Data Service** | scripts/qmt_data_service.py (唯一允许 import xtquant 的生产入口, 60s 同步 → Redis) | CLAUDE.md §QMT 数据架构 |
| **QMTClient** | app/core/qmt_client.py (其他模块通过此读 Redis 缓存, 不直接 xtquant) | CLAUDE.md §xtquant 规则 |
| **PT / Paper Trading** | 模拟实盘交易 (sprint period 4-29 暂停清仓, 真账户 0 持仓) | CLAUDE.md §当前进度 + sprint state |
| **EXECUTION_MODE** | paper / live (.env 配置, sprint period sustained=paper) | backend/.env |
| **LIVE_TRADING_DISABLED** | bool 真金保护 (config.py:44 默认=True, .env 0 override) | backend/app/config.py:44 + backend/app/security/live_trading_guard.py |
| **DINGTALK 双锁** | webhook URL + secret (signature 验签). sprint period sustained: webhook 配置 / secret=空 / keyword=xin (1 锁) | backend/.env |
| **cb_state / circuit_breaker_state** | DB 表名漂移. **真表名**: circuit_breaker_state. **sprint state 用别名**: cb_state. **真字段**: execution_mode (sprint state 写 source) | DB schema 真测 + sprint state handoff |
| **position_snapshot** | DB 持仓快照表 (字段: code/trade_date/strategy_id/market/quantity/avg_cost/market_value/weight/unrealized_pnl/holding_days/execution_mode) | DB schema 真测 |
| **schtask** | Windows Task Scheduler 调度 (PT 类) | CLAUDE.md §调度 |
| **Celery Beat** | Python 调度 (GP / 因子 lifecycle / 风控 / Observability 类) | CLAUDE.md §调度 |
| **schedule entries** | Celery Beat 注册任务清单 | backend/app/tasks/beat_schedule.py |

## D — 因子 / 回测 / 风控

| 术语 | 定义 | 来源 / 关联 |
|---|---|---|
| **CORE3+dv_ttm** | 当前 PT 配置因子集 (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm), WF OOS Sharpe=0.8659 (2026-04-12 PASS) | configs/pt_live.yaml |
| **CORE5** | 前任基线因子集 (5 因子, 含 reversal_20 + amihud_20) | regression test 基线 |
| **PMS / PMSRule** | 阶梯利润保护 (L1/L2/L3 14:30 Beat), 已并入 Wave 3 MVP 3.1 Risk Framework (ADR-010) | backend/qm_platform/risk/rules/pms.py |
| **MVP 3.1 / 3.1b Risk Framework** | Wave 3 风控基础 (PMSRule + SingleStockStopLoss + ConcentrationGuard + 等 ~10 rules) | docs/mvp/MVP_3_*.md |
| **5+1 层风控架构 (D-L0~L5)** | T1.3 design doc 决议 (sprint period PR #181 沉淀, ✅ L1 已落地 / L0/L2/L3/L4/L5 ❌ 0 repo sediment, memory only) | docs/audit/T1_3_RISK_FRAMEWORK_DECISION_DOC.md |
| **factor_values** | DB 因子值表 (840M 行, ~172GB, TimescaleDB hypertable 152 chunks) | DB 真测 sprint period |
| **factor_ic_history** | DB IC 唯一入库点 (铁律 11), 145894 行 | DB 真测 sprint period |
| **WF / Walk-Forward OOS** | 时间序列样本外验证 (paired bootstrap p<0.05 硬门) | docs/ML_WALKFORWARD_DESIGN.md |
| **SN / Size-Neutral** | Partial Size-Neutral b=0.50 (Step 6-H 验证, .env PT_SIZE_NEUTRAL_BETA=0.50) | configs/pt_live.yaml |
| **Phase 3D / 3E** | LightGBM ML synthesis NO-GO (Phase 3D 4 实验全 FAIL) + 微结构 16 因子 (Phase 3E neutral PASS / WF FAIL) | docs/research-kb/findings/ |
| **Wave 1-4** | 平台化 4 大波次 (Wave 1 ✅ Skeleton/DAL/Registry / Wave 2 ✅ Data Lineage / Wave 3 ✅ Risk Signal Exec / Wave 4 🟡 Observability 进行中) | QPB v1.16 |
| **MVP 4.1 batch 3.x** | Wave 4 Observability 17 schtask scripts SDK migration | sprint state handoff |

## E — 数据 + 第三方源

| 术语 | 定义 | 来源 / 关联 |
|---|---|---|
| **Tushare** | 数据源 (因子 + 行情, 商业 ToS) | docs/TUSHARE_DATA_SOURCE_CHECKLIST.md |
| **Baostock** | 数据源 (5min K 线 5 年 / 2537 只股票, 免费) | minute_bars (190M 行) |
| **AKShare** | 数据源 (备用, sprint period sustained 不主用) | configs/ |
| **DataPipeline** | 入库唯一通道 (铁律 17), 禁裸 INSERT (例外: subset-column UPSERT, LL-066 PR #43/#45) | backend/qm_platform/data/ |
| **Parquet cache** | 本地缓存 (按日期分区, _load_shared_data 30min→1.6s, 1000x) | backend/data/parquet_cache.py |
| **TimescaleDB** | PG 16.8 + 扩展 2.26.0 (factor_values / klines_daily hypertable) | D:\pgsql + D:\pgdata16 |
| **Redis Streams** | 事件总线 (qm:{domain}:{event_type}, maxlen=10000) | backend/qm_platform/observability/ + app/core/stream_bus.py |

## F — 严重度分级 (CC 实测扩 framework)

| 级别 | 定义 | SOP |
|---|---|---|
| **P0 真金** | 真金 ¥993K 直接风险 (LIVE_TRADING_DISABLED 实测 false / xtquant 误下单 / 等) | STOP 反问 user 立即 (D78 0 修改例外, framework §5.5 反驳条款) |
| **P0 治理** | 项目治理崩溃 (sprint period 重大假设推翻 / framework 漏 P0 维度) | 沉淀 audit md + STOP 反问 user 决议是否扩 scope |
| **P1** | 重要发现, 影响下次 sprint period 决策 | 沉淀 audit md, audit 末尾汇总 |
| **P2** | 一般发现, 沉淀供 user/Claude 战略对话参考 | 沉淀 audit md |
| **P3** | 微小发现, sprint period 累积 anti-pattern 候选 | 沉淀 audit md |

## G — 本审查 finding 命名规范

`F-D78-N` — 本审查 finding 编号. 例:
- F-D78-1 [P2] sprint state handoff 数字漂移 (4-28 vs 真值 4-27)
- F-D78-2 [P3] cb_state alias 漂移 (真表 circuit_breaker_state)
- F-D78-3 [P3] DINGTALK_SECRET=空 (signature 1 锁)
- F-D78-4 [P2] DB live position vs xtquant 真账户 4 trade days stale (T0-19 sustained)

---

**文档结束**.
