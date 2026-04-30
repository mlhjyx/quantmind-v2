# 现状快照 完整性审 (FRAMEWORK §2.X 强制)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 3 / snapshot/00
**Date**: 2026-05-01
**Type**: 完整性 audit (反 §7.4 抽样 anti-pattern)

---

## §0 元说明

沿用 FRAMEWORK §2.X **CC 主动扩展守门**: 14 类清单 = Claude reference, 不是闭集. CC 必主动思考 14 类是否真完整 + 漏清单候选 + 推荐扩.

本 md 是 snapshot 第 0 篇, 后续 snapshot/01-NN 各 sub-md 引用本 md 作 framework.

---

## §1 Claude framework 14 类 完整性 verify

| # | Claude 类 | sub-md | 完整性 |
|---|---|---|---|
| 类 1 | Repo 清单 (文件树 / 行数 / git log 演进 / blame 高频改动 / 沉默地带) | snapshot/01_repo_inventory.md | ✅ 后续填 |
| 类 2 | DB 清单 (schema / 表 / 行数 / 索引 / 慢查询 / FK / 死表) | snapshot/02_db_schema.md | ✅ 后续填 |
| 类 3 | 服务+调度 (Servy / Celery Beat / worker / schtask / 跨调度) | snapshot/03_services_schedule.md | ✅ 后续填 |
| 类 4 | 配置 (.env / configs/ / Servy services config / 失效会怎样 / 死字段) | snapshot/04_config.md | ✅ 后续填 |
| 类 5 | API + WebSocket (FastAPI router / channel / 调用方 / deprecated) | snapshot/05_api.md | ✅ 后续填 |
| 类 6 | 依赖 (pip / npm / requirements.txt drift / vulnerability 扫描) | snapshot/06_dependencies.md | ✅ 后续填 |
| 类 7 | 因子清单 (factor_values DISTINCT / factor_ic_history / FACTOR_TEST_REGISTRY drift / lifecycle 分布) | snapshot/07_factors.md | ✅ 后续填 |
| 类 8 | 数据流 (Tushare/AKShare/QMT/Baostock → DataPipeline → DB → Parquet → 消费者 / Redis Streams) | snapshot/08_dataflow.md | ✅ 后续填 |
| 类 9 | 测试 (pytest 真清单 / coverage / contract / smoke / E2E / skip) | snapshot/09_tests.md | ✅ 后续填 |
| 类 10 | 文档 (*.md / 行数 / last-update / 引用 graph / stale) | snapshot/10_docs.md | ✅ 后续填 |
| 类 11 | 业务状态 (真账户 / cb_state / position_snapshot / risk_event_log / NAV 历史 / PT 暂停) | snapshot/11_business_state.md | ✅ 后续填 |
| 类 12 | ADR + LL + Tier 0 (ADR 真清单 / LL 真覆盖 / TIER0 closed/待修 / 候选铁律) | snapshot/12_adr_ll_tier0.md | ✅ 后续填 |
| 类 13 | 协作历史 (D 决议链 / sprint period PR 链 / handoff 真有效度) | snapshot/13_collaboration.md | ✅ 后续填 |
| 类 14 | LLM cost + 资源 (LLM call cost / DB / Redis / Parquet / GPU / 32GB RAM 分布 / 资源争用) | snapshot/14_llm_resource.md | ✅ 后续填 |

---

## §2 CC 主动扩 8 类 (沿用 framework_self_audit §3.1)

| # | CC 扩类 | sub-md | 论据 |
|---|---|---|---|
| 类 15 | 真账户对账历史 (broker 报告 vs cb_state 一致性 + xtquant vs DB drift) | snapshot/15_real_account_recon_history.md | F-D78-4 sprint period 4-day stale 印证 (本审查 E 阶段实测) |
| 类 16 | 历史 alert 真触发统计 (Wave 4 MVP 4.1 设计 vs 实测多少触发?) | snapshot/16_alert_trigger_history.md | silent failure candidate (LL-098 同源风险) |
| 类 17 | 历史 PT 重启次数 + 失败原因 | snapshot/17_pt_restart_history.md | Tier 0 closure rate verify |
| 类 18 | 历史 GPU 真利用率 (cu128 装了真用过吗) | snapshot/18_gpu_usage_history.md | CLAUDE.md cu128 提了, 真利用率 verify |
| 类 19 | 历史 OOM 事件 + 修复 | snapshot/19_oom_history.md | 32GB RAM 教训 (2026-04-03 PG OOM) |
| 类 20 | 历史误操作 (commit revert / 数据误删 / 误操作 patterns) | snapshot/20_misops_history.md | 协作 maturity, sprint period 22 PR 链可能含 revert |
| 类 21 | 用户输入历史 (user prompt + 反复反问 patterns, e.g. D72-D78 4 次反问) | snapshot/21_user_prompt_patterns.md | Claude protocol drift detection |
| 类 22 | 跨 session memory drift (Anthropic memory 历史 vs 真状态 e.g. sprint state 4-28 vs 真值 4-27) | snapshot/22_memory_drift.md | F-D78-1 印证 |

---

## §3 漏清单 candidate (本审查不纳入, 留 framework v3.0 修订候选)

CC 实测决议**不本审查纳入**的清单候选 (沿用 framework_self_audit §2.1 ⚠️ 部分纳入):
- 类 X: 实时 system call / shell history 真使用 patterns — 部分纳入到类 16 alert / 类 3 服务调度 sub-section
- 类 Y: 法律 / ToS / 数据使用合规 — 部分纳入到 external 领域 sub-section
- 类 Z: gh PR 历史 reviewer 真触发率 — 纳入到类 13 协作历史 sub-section

---

## §4 sub-md 实施策略 (沿用 framework_self_audit §3.2)

CC 决议每类 sub-md 数 (实测决议合并 vs 拆):
- 22 类 → ~12-15 sub-md (合并相邻小类, e.g. 类 4+5+6 → 1 sub-md, 类 19+20 → 1 sub-md)
- 单 sub-md 控制 ~5-15K bytes (防 context overflow)
- 每 sub-md 必含: 实测证据 cite (grep/SQL/file:line/git hash) + 发现 (red/yellow/green) + 优先级 (P0真金/P0治理/P1/P2/P3)

---

## §5 元 verify

### 5.1 反 §7.4 抽样 anti-pattern 自查

CC 是否抽样? **否**:
- ✅ 22 类全 enumerate 不漏
- ✅ Claude 14 类 sustained + CC 8 类扩 主动思考扩 scope (反 §7.9 被动 follow)
- ✅ 漏 candidate 沉淀 (留 framework v3.0)

### 5.2 反 §7.6 STOP 触发自查

CC 是否触发 STOP? **否** (本 md 0 P0 真金触发, 0 framework 漏 P0 阻断 audit).

---

**文档结束**.
