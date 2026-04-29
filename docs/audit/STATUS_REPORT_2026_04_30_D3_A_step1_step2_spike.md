# STATUS_REPORT — D3-A Step 1+2 Spike (F-D3A-1 真因 + F-D3A-13 决策日志)

**Date**: 2026-04-30
**Branch**: chore/d3a-step1-step2-spike
**Base**: main @ 31a37ba (PR #155 D3-A audit docs merged)
**Scope**: 2 unresolved D3-A finding spikes (Step 1 SDK invoke 真因 + Step 2 DailySignal disable 决策日志)
**ETA**: 实跑 ~25 min CC (vs 预估 30, 提前)
**真金风险**: 0 (0 业务代码改 / 0 .env 改 / 0 服务重启 / 0 DB DML / 0 真发 DingTalk / 0 真触 LLM SDK)
**改动 scope**: 1 文档 (本 STATUS_REPORT) — 单 PR `chore/d3a-step1-step2-spike`, 跳 reviewer

---

## §0 环境前置检查 E1-E5 全 ✅

| 项 | 实测 | 结论 |
|---|---|---|
| E1 git status | main @ `31a37ba` (PR #155), 8 D2 untracked (上 session 残留, 不在 scope) | ✅ |
| E2 PG stuck backends | 0 (仅本审计 psql session, pid 21472 active 0s) | ✅ |
| E3 Servy 4 服务 | FastAPI / Celery / CeleryBeat / QMTData ALL Running | ✅ |
| E4 .venv Python | Python 3.11.9 | ✅ |
| E5 真金 fail-secure | `LIVE_TRADING_DISABLED=True` + `OBSERVABILITY_USE_PLATFORM_SDK=True` | ✅ |

---

## Step 1 — F-D3A-1 真因 spike

### Q1.1 ✅ 3 missing migrations 内容核实

```bash
wc -l backend/migrations/{alert_dedup,platform_metrics,strategy_evaluations}.sql
# alert_dedup.sql:           52 行
# platform_metrics.sql:     141 行
# strategy_evaluations.sql:  71 行
# 264 行 total
```

每个 migration DDL 头实测 (Read 验证):
- **alert_dedup.sql**: 普通表 (非 hypertable). PRIMARY KEY `dedup_key` (TEXT, char_length 1-512) + `severity` CHECK ('p0'/'p1'/'p2'/'info') + `last_fired_at` / `suppress_until` / `fire_count` (BIGINT >=1) + `last_title`. MVP 4.1 batch 1.
- **platform_metrics.sql**: TimescaleDB hypertable, 7d chunk_time_interval, 30d retention. 字段 `name` (TEXT dotted) + `value` (DOUBLE PRECISION) + `metric_type` ('gauge'/'counter'/'histogram') + `labels` (JSONB) + `ts` TIMESTAMPTZ. MVP 4.1 batch 2.1.
- **strategy_evaluations.sql**: append-only 历史表, FK to `strategy_registry(strategy_id)` ON DELETE RESTRICT. 字段 `passed` (BOOLEAN) + `blockers` (JSONB) + `p_value` (DOUBLE PRECISION) + `details` (JSONB) + `evaluated_at` TIMESTAMPTZ. MVP 3.5.1.

### Q1.2 ✅ DB 表不存在 + 3 SDK 类定位

**SQL 实测** (D3-A confirm):
```sql
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('alert_dedup','platform_metrics','strategy_evaluations');
-- 0 rows
```

**3 SDK 类独立 grep + Read 验证**:

| SDK 编号 | 类 | import path | 真 read missing 表? |
|---|---|---|---|
| **S1** | `PostgresAlertRouter` | `qm_platform.observability.alert` (alert.py:161) | ✅ `_is_deduped` (L416): `SELECT suppress_until FROM alert_dedup` |
| **S2** | `PostgresMetricExporter` | `qm_platform.observability.metric` (metric.py:53) | ✅ `_emit` (L237): `INSERT INTO platform_metrics` |
| **S3** | `DBStrategyRegistry` | `qm_platform.strategy.registry` (registry.py:80) | ✅ `_assert_eval_passed_for_live` (L429): `SELECT passed, blockers, evaluated_at FROM strategy_evaluations` (private, 由 `update_status(LIVE)` 触发) |

3 类**全确认真 read missing 表**. 0 类有 auto-create-table / auto-migrate 行为.

**0 第 4+ SDK 类发现** (grep `FROM (alert_dedup|platform_metrics|strategy_evaluations)` + `INTO ...` + `UPDATE ...` 全覆盖).

### Q1.3 ✅ 3 SDK invoke 真因实测 (核心)

CC 自定义 spike script (`/tmp/d3a_spike_invoke.py`, read-only invoke, 不真改 DB / 不真发 DingTalk):

```python
# S2: PostgresMetricExporter().gauge("d3a_spike.dummy", 1.0)
# S1: PostgresAlertRouter().fire(Alert(...severity=INFO...), dedup_key="d3a_spike_2026_04_30_test_only")
# S3: get_sync_conn → cur.execute("SELECT passed, blockers, evaluated_at FROM strategy_evaluations LIMIT 1")
```

**实测输出快照**:

| SDK | Exception class | err msg | 在哪 raise |
|---|---|---|---|
| **S1** | `psycopg2.errors.UndefinedTable` | `relation "alert_dedup" does not exist` | `alert.py:416 _is_deduped` (fire 第 1 步) |
| **S2** | `qm_platform.observability.metric.MetricExportError` (wraps `UndefinedTable`) | `Failed to emit metric 'd3a_spike.dummy' (type=gauge): relation "platform_metrics" does not exist` | `metric.py:254 _emit` |
| **S3** | `psycopg2.errors.UndefinedTable` | `relation "strategy_evaluations" does not exist` | 直接 SQL 复刻 `_assert_eval_passed_for_live` 路径 |

**S1 安全验证**: fire() 第 1 步 `_is_deduped` 立即 raise → 不会到 `_dispatch` (DingTalk send) 也不会到 `_upsert_dedup` (write). **0 真发 DingTalk / 0 写 DB**.

**S2 stderr log**:
```
[MetricExporter] emit failed name=d3a_spike.dummy type=gauge value=1.0 err=relation "platform_metrics" does not exist
```
metric.py default `reraise=True` → log error + raise (而非 silent skip). **铁律 33 fail-loud 合规**.

**S3**: 直接 SQL 等价 `_assert_eval_passed_for_live` 内 SELECT (private method 由 update_status(LIVE) 触发). 任何 caller 调 `update_status(LIVE)` 时, 在 `strategy_registry` 校验通过后立即 raise UndefinedTable.

### Q1.4 ✅ 真因分类决议 (无模糊)

| SDK | 类别 | 实测行为 | 严重度 |
|---|---|---|---|
| **S1 PostgresAlertRouter** | **A** | raise `psycopg2.errors.UndefinedTable` | **P0** |
| **S2 PostgresMetricExporter** | **A** (with log) | raise `MetricExportError` wraps UndefinedTable + stderr log | **P0** |
| **S3 DBStrategyRegistry** | **A** | raise `psycopg2.errors.UndefinedTable` (via update_status(LIVE) → _assert_eval_passed_for_live) | **P0** |

**3/3 全 A 类 (raise)** → **F-D3A-1 严重度维持 P0** (D3-A 判断准确, 实测确认非过度).

**铁律 33 fail-loud 评估**: 3 SDK 全 fail-loud 合规 (raise + log). **0 silent skip finding** (Q1.4 B/C/D 类 0 命中).

### F-D3A-1 P0 实测确认 — 关键关联发现

**意外关联** (D3-A 未识别): D3-A F-D3A-14 "pt_audit 4-29 schtask LastResult=1 但 DB 无 audit log" 真因极可能是**走 SDK alert path 遭遇 alert_dedup 缺失 raise**. 验证逻辑:

- pt_audit 4-29 启动 → invoke `PostgresAlertRouter.fire()` (报告异常) → `_is_deduped` SELECT alert_dedup → UndefinedTable raise → schtask 整体失败 (非 0 退出)
- pt_audit DB 无 audit log = 走铁律 43 `main()` 顶层 try/except → stderr + exit(2) 路径, 但 alert_dedup raise 发生在 audit log 写之前

**升级 F-D3A-14**: **P1 → P0 候选** (待 D3-B 实测 schtask stderr trace 确认). 这是 spike 副产品, 非本 spike scope.

---

## Step 2 — F-D3A-13 决策日志查证

### Q2.1 ✅ 决策日志多源 grep (6+ 源全找到)

| # | 源 | 路径 | 决策证据 |
|---|---|---|---|
| 1 | git log | `258fb61 fix(scheduler): Stage 4 schtasks 重排` | "DailySignal reenable + 17:05 废除" — Stage 4 曾 reenable |
| 2 | docs/audit | `STATUS_REPORT_2026_04_29_D2.md:63` | `Disabled (5): DailyExecute / DailySignal / DailyReconciliation / IntradayMonitor / CancelStaleOrders` (D2 audit 4-29 已记) |
| 3 | docs/audit | `live_mode_activation_scan_2026_04_29.md:19/218/289/359` | `12 ready / 5 disabled` + 显式 "切 live 后无新 signals 生成" + "🟢 0 风险" |
| 4 | docs/audit | `servy_env_injection_debug_2026_04_30.md:140` | `✅ schtask DailyExecute / IntradayMonitor / DailySignal / DailyReconciliation / CancelStaleOrders 仍 Disabled` (4-30 复核) |
| 5 | docs/archive | `PT_PAUSE_RECORD_20260409.md:19` | `QuantMind_DailySignal | Ready | 2026-04-08 17:15 | 2026-04-09 17:15 | ✅ Disabled` (4-09 PT pause 首次 disable record) |
| 6 | docs/audit | `STATUS_REPORT_2026_04_29_batch1.md:138` | "16:30 DailySignal 与 09:31 DailyExecute 之间存在依赖断点... 批 2 重启评估时一并处理 (T0-6)" |

**时间线综合**:
- 2026-04-09 PT pause → 5 schtask 首次 Disabled (含 DailySignal)
- Stage 4 (commit `258fb61`) → DailySignal 曾 reenable (PR-DRECON 同 pattern 复活风险)
- 2026-04-29 D2 audit → 5 schtask 全 Disabled (含 DailySignal) — 与 4-09 pause 状态一致
- 2026-04-30 D3-A → DailySignal Disabled, last run 4-28 16:30 — 与 D2 状态一致

DailySignal Disabled 是 **PT 暂停决策的 5-task disable 包络** 一部分 (含 DailyExecute / IntradayMonitor / DailyReconciliation / CancelStaleOrders), **决策记录完整且多源**.

### Q2.2 ✅ F-D3A-13 决议 — INFO (推翻 D3-A 原 P1)

**D3-A STATUS_REPORT_2026_04_30_D3_A.md:121** 自评 "QuantMind_DailySignal Disabled (PT 暂停的有意 disable, 但**缺显式 STATUS_REPORT 记录**)"

**Q2.1 实测推翻**: 决策记录在 6+ 文档源 + 1 git commit 全有记录, **不缺记录**. D3-A 当时未 grep 到这些源 (CC 1 阶概括第 N 次).

**F-D3A-13 决议**: **INFO** — 不是 P1, 不需要批 2 处理.

**LL "假设必实测纠错" 累计**: D3-A 自身 12 次 → 本 spike 新增 **2 次**:
- LL #13: "F-D3A-13 缺决策记录" → 实测 6+ 源全有
- LL #14: F-D3A-14 真因可能是 alert_dedup raise (Step 1 副产品)

---

## F-D3A-1 严重度更新决议 — **P0 维持** (D3-A 判断实测确认)

| 路径 | 原 D3-A | 实测 Q1.4 | 严重度 |
|---|---|---|---|
| S1 PostgresAlertRouter | P0 (假设 raise) | A 类 raise UndefinedTable | **P0** ✅ |
| S2 PostgresMetricExporter | P0 (假设 raise) | A 类 raise MetricExportError + log | **P0** ✅ |
| S3 DBStrategyRegistry | P0 (假设 raise) | A 类 raise UndefinedTable | **P0** ✅ |

**整体**: 3/3 全 A → **F-D3A-1 维持 P0** (无路径独立分级, 全合并). 无铁律 33 silent skip 违反 finding (3 SDK 都 fail-loud 合规).

**修法 (待 user 决议)**: 立即应用 3 migrations (单 PR `fix/apply-missing-migrations`) — `psql -U xin -d quantmind_v2 -f backend/migrations/alert_dedup.sql` × 3 + smoke 验证 SDK 路径不 raise.

---

## F-D3A-13 决议 — **INFO** (推翻 D3-A P1)

决策记录在 6 文档源 + git commit 全有, **不缺记录**. PT 暂停决策的 5-task disable 包络 (DailyExecute / DailySignal / IntradayMonitor / DailyReconciliation / CancelStaleOrders 同期 Disabled).

**修法**: 0 (INFO). D3-A STATUS_REPORT_2026_04_30_D3_A.md 涉及 F-D3A-13 段落留 D3-B 整合阶段 markdown 修正 (改 P1 → INFO + 引用 6 源).

---

## 批 2 Scope 调整建议

### 维持 (1 项)

- **F-D3A-1 P0** (3 missing migrations) — 立即修, 单独 PR

### 升级候选 (1 项)

- **F-D3A-14 P1 → P0 候选**: pt_audit 4-29 LastResult=1 真因极可能是 alert_dedup 缺失 raise. 待 D3-B 实测 schtask stderr trace 确认. 如确认 → 应用 3 migrations 后自然修复.

### 降级 (1 项)

- **F-D3A-13 P1 → INFO**: 决策记录完整 (6+ 源), 不需要批 2 处理.

### 新增 finding (0 项)

- 0 新 finding (本 spike 是 D3-A 收尾, 不扩 scope).
- 0 silent skip finding (Q1.4 B/C 类 0 命中).
- 0 第 4+ SDK 类发现.

---

## LL "假设必实测纠错" 第 N 次同质统计 (D3-A 续)

D3-A STATUS_REPORT 累计 12 次 (LL #1-12) → **本 spike 新增 2 次** (LL #13-14):

| 第 | 来源 | 假设 | 实测 |
|---|---|---|---|
| 13 | D3-A F-D3A-13 描述 "缺显式 STATUS_REPORT 记录" | 决策日志缺失 | 6+ 文档源 + 1 git commit 全有, 决策记录完整 |
| 14 | D3-A F-D3A-14 P1 "pt_audit 启动前自身 fail" | 启动 import / .env 加载失败 | 真因极可能是 alert_dedup 缺失 raise (Step 1 副产品), 升级 P0 候选 |

**累计 14 次**. 复用规则 (LL 全局): 写 finding 时, 任何 "缺 X / X 不存在 / X 是 Y" 假设, 必须附实测命令证据 + 输出快照. 否则降级 informational, 待二次实测.

---

## 硬门验证

| 硬门 | 结果 | 证据 |
|---|---|---|
| 改动 scope | ✅ 1 文档 (本 STATUS_REPORT) | `git status --short` |
| ruff | ✅ N/A | 0 .py 改动 |
| pytest | ✅ N/A | 0 .py 改动 |
| pre-push smoke | (push 时验) | bash hook (沿用上 PR) |
| 0 业务代码改 | ✅ | git diff main 仅本文件 |
| 0 .env 改 | ✅ | grep diff main backend/.env = 0 |
| 0 服务重启 | ✅ | Servy 4 服务全程 Running |
| 0 DML | ✅ | 全程 SELECT only + Q1.3 invoke 期望 raise (alert_dedup/platform_metrics/strategy_evaluations 缺失就立即 raise, 不到 INSERT/UPDATE 路径) |
| 0 真发 DingTalk | ✅ | S1 fire() 在 _is_deduped 阶段立即 raise, 不到 _dispatch (DingTalk send) |
| 0 LLM SDK 调用 | ✅ | 本 spike 是开发诊断边界 (铁律 X1) |

---

## 下一步建议

### 立即 (2 选项 — 推荐 A)

- **A**: user 决议是否立即启 PR `fix/apply-missing-migrations` 应用 3 migrations (耗时 ~30 min) — F-D3A-1 P0 + F-D3A-14 候选 P0 一次解决
- **B**: 直接启 D3-B 中维度 5 个 (~5h), 3 migrations 留批 2

### 后续 (D3-B / 批 2)

- D3-B 实测 schtask stderr trace 验证 F-D3A-14 真因 (pt_audit 4-29 是否真是 alert_dedup raise)
- D3-A STATUS_REPORT 涉及 F-D3A-13 段落 D3-B 整合时改 P1 → INFO

---

## 关联

- **D3-A STATUS_REPORT** ([STATUS_REPORT_2026_04_30_D3_A.md](STATUS_REPORT_2026_04_30_D3_A.md)) — 本 spike 收尾 D3-A 2 unresolved finding
- **F-D3A-1** D3-A audit P0 (3 missing migrations) — 实测确认 P0 (3/3 raise)
- **F-D3A-13** D3-A audit P1 (DailySignal disable 决策记录) — 实测降级 INFO
- **F-D3A-14** D3-A audit P1 (pt_audit 4-29 fail) — 副产品发现真因关联 alert_dedup
- **铁律 33 fail-loud** — 3 SDK 全 fail-loud 合规 (0 silent skip)
- **铁律 X1 Claude 边界** — 本 spike 是开发诊断, 0 LLM SDK 调用
- **LL "假设必实测纠错"** 第 13-14 次 (累计 14 次)

---

## 用户接触

实际 0 (沿用 D2/D3-A/runbook init/PR #154 LOW 改动模式, 0 业务代码 + 跳 reviewer + AI self-merge).

如本 STATUS_REPORT 触发 user 决策 (选项 A/B), user 接触 1 (决议下一步).
