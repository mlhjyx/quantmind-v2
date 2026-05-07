# CC Automation Runbook 索引

各场景的 CC 自动化操作指令存档. 触发时 user 一句话 → CC 加载对应 runbook → 自主执行 → user 0 手工操作.

## 用途

存放**可重复触发**的运维操作 prompt. 跟 `docs/audit/` (一次性诊断报告) / `docs/adr/` (架构决议) / `docs/mvp/` (功能设计) 区分.

适合放这里的内容:
- 撤回某项临时配置 (e.g. setx env / Servy override)
- 标准化的服务重启 / 状态检查序列
- 紧急止血操作 (PT 全清仓 / Beat schedule 全停 / 等)
- DB 命名空间修复 / cb_state 清理 / 等定型操作

不适合放这里的内容:
- 一次性诊断报告 → `docs/audit/`
- 架构决议 → `docs/adr/`
- MVP 设计 → `docs/mvp/`
- 代码逻辑文档 → `docs/DEV_*.md`

## 当前 runbook

| # | 文件 | 触发场景 | 资金风险 |
|---|------|---------|---------|
| 01 | [`01_setx_unwind_runbook.md`](01_setx_unwind_runbook.md) | 撤回 D2.3 临时 setx (Machine `SKIP_NAMESPACE_ASSERT=1`), 批 2 P3 startup_assertions 改用 settings 后调用 | 0 (paper mode + LIVE_TRADING_DISABLED=True) |
| 02 | [`02_llm_cost_daily_runbook.md`](02_llm_cost_daily_runbook.md) | LLM 成本日报 daily aggregate + DingTalk push (Mon-Fri 20:30 schtask 真生产 / user 显式触发) — S2.3 PR #224 合并 S5 退役 | 0 (LLM 路径 0 broker call + 仅 SELECT 聚合查询) |
| 03 | [`03_ollama_install_runbook.md`](03_ollama_install_runbook.md) | Ollama D 盘 install (`D:\tools\Ollama` + `D:\ollama-models`) + `ollama pull qwen3:8b` (5.2 GB), 启用 BudgetAwareRouter Capped100 fallback path — S3 PR #225 sediment | 0 (LLM fallback 路径 0 broker call + 本地 Ollama 0 对外暴露 + LIVE_TRADING_DISABLED 沿用) |
| 04 | [`04_post_deploy_restart_cadence_sop.md`](04_post_deploy_restart_cadence_sop.md) | Post-deploy Servy restart cadence (Worker / FastAPI / CeleryBeat / RSSHub / QMTData) — Sprint 2 sub-PR 8b chain 5-07 4-day silent fallback reverse case sediment, 3-layer evidence chain verify (process timestamp + stdout banner + transitive endpoint trigger) | 0 (Servy restart 真生产 capacity ops + 0 .env / yaml mutation + LIVE_TRADING_DISABLED 沿用) |
| 05 | [`05_send_task_queue_routing_sop.md`](05_send_task_queue_routing_sop.md) | Celery `send_task` queue routing — manual dispatch **queue= explicit** 沿用 Beat entry config 反 default routing key "celery" silent drop reverse case (sub-PR 8b-cadence-B Option (C) 5-07 22:00 catch) | 0 (Redis broker write only + 0 broker call) |
| 06 | [`06_beat_monitoring_sop.md`](06_beat_monitoring_sop.md) | CeleryBeat schedule health 4-layer verify (Servy CLI status + process timestamp + celerybeat-schedule.dat shelve introspect + celery-beat-stderr.log ticking) — X9 Beat Stopped silent drift reverse case sediment | 0 (read-only verify) |
| 07 | [`07_registry_status_count_sop.md`](07_registry_status_count_sop.md) | ADR `docs/adr/REGISTRY.md` status distribution count automation — committed/reserved/gap count update 沿用 PR add row 体例, N×N drift cross-verify (REGISTRY + ADR-DRAFT + V3 + LL backlog) ADR-022 反 silent overwrite (sub-PR 8b-cadence-A reviewer HIGH 5-07 sediment) | 0 (doc-only) |
| 08 | [`08_adr_partial_closure_monitoring_sop.md`](08_adr_partial_closure_monitoring_sop.md) | ADR partial closure cumulative drift 监控 (`→ ADR-XXX (committed, partial)` 体例 + 残余 sub-task tracking + 3 source cross-verify), 反 forgotten 漂移 (ADR-039 + ADR-043 partial closure sediment) | 0 (doc-only) |

## 添加新 runbook

按命名 `NN_<scenario>_runbook.md` 加入. 同时更新本索引表 (新增行).

**命名规则**:
- `NN`: 2 位序号, 按时间顺序递增, 不复用
- `<scenario>`: snake_case, 简短描述触发场景
- 后缀必须是 `_runbook.md` (executable ops 多步操作 + rollback 体例) 或 `_sop.md` (monitoring/verification SOP, **lighter template** 反 destructive ops, e.g. governance / audit / drift detection)
- 区分于 `_audit.md` / `_design.md` (ADR / one-shot diagnostic)

**runbook 模板必含字段**:
1. **触发条件** (何时调用 — 前置依赖)
2. **资金 0 风险确认** (LIVE_TRADING_DISABLED guard / paper mode / Beat 状态)
3. **前置检查清单** (实测命令 + 期望输出)
4. **执行步骤** (每步含命令 + 期望输出 + 失败回滚路径)
5. **验证清单** (每个 ok/fail 判定)
6. **失败回滚** (任意步骤失败如何还原)
7. **STATUS_REPORT 输出** (`docs/audit/STATUS_REPORT_<date>_<scenario>.md` 路径)
