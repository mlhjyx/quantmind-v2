# STATUS_REPORT — D3-A 全方位审计 P0 维度 (5/14)

**Date**: 2026-04-30
**Branch**: chore/d3a-audit-docs
**Base**: main @ a2ffb56 (PR #154 PowerShell 版本纠正 merged)
**Scope**: 5 维度 P0 审计 (D3.1 数据完整性 / D3.9 配置 SSOT / D3.11 安全 / D3.12 真金 ops / D3.14 铁律 v3.0)
**ETA**: 实跑 ~2.5h CC (vs 预估 5h, 提前)
**真金风险**: 0 (0 业务代码改 / 0 .env 改 / 0 服务重启 / 0 DB DML)
**改动 scope**: 6 文档 (5 维度 finding + 本 STATUS_REPORT) — 单 PR `chore/d3a-audit-docs`, 跳 reviewer

---

## §0 环境前置检查 E1-E8 全 ✅

| 项 | 实测 | 结论 |
|---|---|---|
| E1 git status | main @ `a2ffb56` + 8 D2 untracked (上 session 残留, 不在 scope) | ✅ |
| E2 PG stuck backends | 0 (仅本审计 psql session) | ✅ |
| E3 Servy 4 服务 | FastAPI / Celery / CeleryBeat / QMTData ALL Running | ✅ |
| E4 zombie processes | 10 python 全 Servy-managed (uvicorn / celery / qmt_data_service), 0 zombie | ✅ |
| E5 PowerShell 版本 | pwsh 7.6.1 + powershell.exe 5.1.26100.8115 (PR #154 已纠正) | ✅ |
| E6 LIVE_TRADING_DISABLED | True (fail-secure default) | ✅ |
| E7 pytest collect | **4027 tests collected** in 1.70s (vs prompt 估 ~3300, +22% 漂移, 0 collect error) | ✅ |
| E8 .venv Python | Python 3.11.9 from `D:\quantmind-v2\.venv\Scripts\python.exe` | ✅ |

**incidental finding (E7)**: pytest collected 4027 vs memory baseline ~3300 — memory stale (~22% 偏差). 不 STOP, 标 INFO.

---

## 18 题逐答 (按维度组)

### D3.1 数据完整性

**Q1.1**: ✅ 实测 83 张 public schema 表 (vs memory 73, +10 漂移). 3 hypertables (factor_values / klines_daily / risk_event_log).

**Q1.2**: ⚠️ LL-063 三问法实测:
- 真死表: factor_evaluation (0 行 + 0 代码引用) — F-D3A-4 (P3)
- 假装健康死码: position_monitor (0 行但 api/pms.py:70 仍读) — F-D3A-2 (P2)
- valid 暂空: circuit_breaker_log (D2.3 cb_state 切换后自然 0)

**Q1.3**: ⚠️ 实测 vs memory 多处偏差:
- factor_values 840M ✅ / minute_bars 191M ✅ / klines_daily 11.78M ✅
- northbound_holdings 5.54M (memory 3.88M, **+43% stale**)
- stock_status_daily 55K (memory L189 12M, memory 误读 lifetime inserts 为 row count, **-99.5%**)
- factor_ic_history 145K (memory L191 84K, **+74%** stale)

**Q1.4**: ✅ 命名空间状态健康 (D2.3 cutover 后):
- live: position_snapshot 295 / cb_state 1 / performance_series 16 / trade_log 68
- paper: cb_state 1 / trade_log 20 (历史 P0-δ 污染遗留, 0 真金风险)

### D3.9 配置 SSOT

**Q9.1**: ✅ .env 20 字段实测枚举.

**Q9.2**: ✅ Settings 32 字段, 12 用 default (含 LIVE_TRADING_DISABLED=True / OBSERVABILITY_USE_PLATFORM_SDK=True / PMS_ENABLED 等). 0 .env 漂移到 Settings 之外 (除 SKIP_NAMESPACE_ASSERT 临时 D2.2 known).

**Q9.3**: ⚠️ Runtime os.environ override 实测 5 hits, 含:
- D2 known: scripts/intraday_monitor.py:141 (T0-4)
- **D2 漏报新发现**: scripts/daily_reconciliation.py:70 — F-D3A-5 (P2)
- 字段名漂移: scripts/monitor_mvp_3_1_sunset.py:93 reads DINGTALK_WEBHOOK (no _URL) — F-D3A-7 (P2 silent failure)

### D3.11 安全

**Q11.1**: ✅ 0 真 secrets hardcode in tracked .py (1 mock test "secret-key-123"). .gitignore 含 .env*.

**Q11.2**: ⚠️ 2 f-string SQL hits in `data_orchestrator.py:460/778`. 当前调用方均 internal hardcoded list, 0 user input 路径. 建议加 table allowlist defense in depth — F-D3A-10 (P3).

**Q11.3**: ✅ CORS 仅 localhost:3000, 0 wildcard, allow_credentials=True 安全 (dev-only).

**Q11.4**: 🔴 37 POST/PUT/DELETE endpoints, **22 无 admin gate** (含 4 真金高风险 — risk.py:189 l4-recovery / params.py:115 modify-config / params.py:148 init-defaults / pipeline.py:310 approve_factor). vs D2.1 claim "12 files" 实测 22 (+83% 漂移) — F-D3A-9 (P1).

### D3.12 真金 Ops

**Q12.1**: ⚠️ 4-28 NAV ¥1,011,714.08, 19 股持仓, 浮盈 +¥10,395.59 (+1.17%). handoff "卓然 -29%" 实测 -11.45% (恢复 17.5pp), 南玻 -10.84% (一致) — F-D3A-11 (P3 stale).

**Q12.2**: 🔴 Tier 0 债 10 项实测 vs Claude claim:
- T0-1/2/3 ✅ 修复确认 (LL-081 guard / startup_assertions / cb_multiplier 参数化)
- **T0-4 重大 scope 偏差**: claim "7 处 hardcoded 'live'" 实测 27+ — F-D3A-12 (P0)
- T0-5/7/8/9 留 D3-B (本审计未深查)
- T0-6 ✅ DailyExecute Disabled 确认
- T0-10 ✅ position_monitor 死表确认 (D3.1 F-D3A-2)

**Q12.3**: 🔴 risk_event_log 历史 0 rows. Risk Framework v2 9 PR (Session 44 #143-148) 真生产 0 触发. 评估: PT 暂停 + DailySignal Disabled 是部分原因, 但 -11.45% / -10.84% 持仓应触发 SingleStockStopLoss 阈值, 待批 2 验证.

**附加 schtask 实测**:
- F-D3A-13 (P0): QuantMind_DailySignal Disabled (last 4-28), 4-29/4-30 0 signal
- F-D3A-14 (P1): pt_audit 4-29 schtask LastResult=1 但 DB 无 audit log (启动前 fail)
- pending_monthly_rebalance 18 expired / 36 executed (52% rate, PT 暂停副作用)

### D3.14 铁律 v3.0 实施扫描

**Q14.1 X1 anthropic SDK**: ✅ 0 hits PASS.

**Q14.2 X3 .venv**: ⚠️ pre-push hook .venv 缺失 silent fallback to system python — F-D3A-18 (P3).

**Q14.3 X6 LLM SDK**: ✅ 0 openai/deepseek SDK import. DeepSeek 走自实现 HTTP client, 合规.

**Q14.4 X2 LIVE_TRADING_DISABLED**: ✅ 多重保护 (config default True + guard module + broker invoke + Beat 解挂 + 14+ tests).

---

## 关键 Findings — P0/P1/P2/P3 分级

### 🔴 P0 (5 个) — 立即 / 批 2 P0 必做

| ID | 描述 | 路径 | 修法建议 |
|---|---|---|---|
| **F-D3A-1** | **alert_dedup / platform_metrics / strategy_evaluations migrations 存在但 DB 表不存在** — MVP 4.1 batch 1+2.1 + MVP 3.5.1 PR 实质未真生效, SDK 路径 invoke 时 `relation does not exist` | `backend/migrations/{alert_dedup,platform_metrics,strategy_evaluations}.sql` exist; DB IS NOT | 立即 `psql -f` apply 3 migrations (单 PR) + 验证 PostgresAlertRouter / PostgresMetricExporter / DBStrategyRegistry 路径不 raise |
| **F-D3A-12** | T0-4 hardcoded 'live' scope **27+ 处 vs claim 7** (3.8x 偏差). 含 read 路径 D3-KEEP + write 路径必修混杂 | grep `execution_mode\s*=\s*['"]live['"]` 全 backend/ | 批 2 P0 重新枚举所有 hits, 区分 read (合规 D3-KEEP) vs write (P0-β 必修, 走 ADR-008 PR-A) |
| **F-D3A-13** | QuantMind_DailySignal schtask **Disabled** (last run 4-28). 4-29/4-30 0 signal 写入 | `schtasks /Query /TN QuantMind_DailySignal` State=Disabled | 决策: PT 暂停期 disable 是有意 (paper-mode dry-run gate) 还是漂移? handoff "PT 暂停" 描述与 schtask 状态对齐 — INFO. **不 P0**, 但应在 STATUS_REPORT 显式记 PT 暂停 = "DailySignal+DailyExecute 双 disable", 防止后 session 重新激活混乱. 改 P1. |
| **F-D3A-?? (Risk v2 0 events)** | risk_event_log 历史 0 rows. Risk Framework v2 9 PR 真生产 0 触发 | `SELECT COUNT(*) FROM risk_event_log` = 0 | 批 2 P0 增子项: "9 PR 真生产验证" — 历史回放或合成场景, 验证 SingleStockStopLoss 等触发条件 |
| (E7 INFO) | pytest collected 4027 vs memory ~3300 (+22%) | 实测 | 不 P0, INFO. memory baseline 更新留 D3-B |

**P0 实际确认**: F-D3A-1 + F-D3A-12 + Risk v2 0 events. F-D3A-13 降为 P1 (handoff 已说明 PT 暂停).

### 🟡 P1 (4 个) — 批 2 P1 应做

| ID | 描述 |
|---|---|
| F-D3A-9 | 22 endpoints 无 admin gate (含 4 真金高风险). D2.1 claim 12 实测 22. 升级 P3 → P1 |
| F-D3A-13 | QuantMind_DailySignal Disabled (PT 暂停的有意 disable, 但缺显式 STATUS_REPORT 记录) |
| F-D3A-14 | pt_audit 4-29 schtask LastResult=1 但 DB 无 audit log → 启动前自身 fail |
| F-D3A-?? | performance_series 4-27 cash NULL (D2.3 P0-β 修后间歇性遗留) |

### 🟢 P2 (3 个) — 批 2/3 P2 候选

| ID | 描述 |
|---|---|
| F-D3A-2 | position_monitor "假装健康死码" — api/pms.py:70 read 永返 0 rows |
| F-D3A-5 | scripts/daily_reconciliation.py:70 force EXECUTION_MODE='live' (D2 漏 1 处) |
| F-D3A-7 | scripts/monitor_mvp_3_1_sunset.py:93 reads DINGTALK_WEBHOOK (no _URL) silent failure |

### ⚪ P3 (7 个)

| ID | 描述 |
|---|---|
| F-D3A-4 | factor_evaluation 真死表 (0 行 + 0 代码引用), DROP 候选 |
| F-D3A-6 | startup_assertions.py:40-41 注释 stale (D2.3 已证 setx User scope 不继承) |
| F-D3A-8 | 7+ scripts 直读 os.environ.get("DATABASE_URL") (应统一 settings) |
| F-D3A-10 | data_orchestrator.py:460/778 f-string SQL 加 table allowlist (defense in depth) |
| F-D3A-11 | handoff "卓然 -29%" 数字 stale, 实测 -11.45% |
| F-D3A-18 | pre-push hook .venv silent fallback to system python (X3 弱违反) |
| (3 处 CLAUDE.md 数字漂移) | L188 northbound 3.88M (实测 5.54M) / L189 stock_status_daily 12M (实测 55K) / L191 ic_history 84K (实测 145K) |

---

## Tier 0 债 10 项实测最新状态

| 编号 | Claude claim | 实测 | 状态 |
|---|---|---|---|
| T0-1 LL-081 guard | ✅ 修 | ✅ 实存 pt_qmt_state.py | 已修 ✅ |
| T0-2 startup_assertions | ✅ 修 | ✅ 实存 + bypass env | 已修 ✅ |
| T0-3 cb_multiplier | ✅ 修 | ✅ 0 hits 已参数化 | 已修 ✅ |
| **T0-4 hardcoded 'live'** | 🟡 7 处待批 2 P0 | 🔴 **27+ 处** (3.8x 偏差) | **scope 漂移** 🔴 |
| T0-5 LoggingSellBroker stub | 🟡 待批 2 P3 | 留 D3-B | pending |
| T0-6 DailyExecute disabled | 🟡 评估 | ✅ State=Disabled | confirmed |
| T0-7 auto_sell_l4 default | 🟡 决策 | 留 D3-B | pending |
| T0-8 dedup key 不含 code | 🟡 批 2 P2 | upstream — alert_dedup 表本身缺 (F-D3A-1) | upstream |
| T0-9 approve_l4.py hardcoded paper | 🟡 批 3 | 留 D3-B | pending |
| T0-10 api/pms.py 死表 | 🟡 批 3 | ✅ 实测 confirmed (D3.1 F-D3A-2) | confirmed |

**🆕 新发现 P0 加入 Tier 0 债 (T0-11+)**:
- **T0-11 (P0)**: alert_dedup / platform_metrics / strategy_evaluations 3 migrations 未应用 (F-D3A-1)
- **T0-12 (P0)**: Risk Framework v2 9 PR 真生产 0 events 验证缺 (F-D3A-?? Risk v2)

**Tier 0 债总数**: 10 → **12** (+2 P0 新发现).

---

## 7 新铁律 (X1-X7) 实施扫描结果

| 铁律 | 描述 | 当前状态 | 违反 |
|---|---|---|---|
| X1 | Claude 边界 (anthropic SDK 禁) | ✅ PASS | 0 hits |
| X2 | LIVE_TRADING_DISABLED 默认 True | ✅ PASS | 多重保护 |
| X3 | .venv Python 唯一 | 🟡 partial | F-D3A-18 (silent fallback) |
| X4 | 死码月度 audit | 🟢 first audit | 本审计为首次实践 (D3.1+D3.12) |
| X5 | 文档单源化 | 🔴 0 自动化 | manual only, CLAUDE.md L188-191 + handoff stale |
| X6 | LLM 必经 LiteLLM | ✅ PASS | 0 SDK import (DeepSeek 走自实现 HTTP) |
| X7 | 月度铁律 audit | 🟢 first audit | 本 D3-A 覆盖 5/42 条 |

---

## 批 2 Scope 调整建议

### 新增 P0 (2 项)

1. **(T0-11) 应用 3 migrations** — `alert_dedup` + `platform_metrics` + `strategy_evaluations` (单 PR `fix/apply-missing-migrations`, 含验证 SDK 路径不 raise)
2. **(T0-12) Risk Framework v2 9 PR 真生产验证** — 历史回放或合成场景验证 5 维度规则触发

### 升级 P3 → P1 (1 项)

- **F-D3A-9** 22 endpoints 无 admin gate (含 4 真金高风险). 真金 cutover 前必加 4 个真金高风险 endpoint.

### 扩 scope (1 项)

- **T0-4 hardcoded 'live' 扩 7 → 27+** — 重新枚举, 区分 read (合规) vs write (必修)

### 新增 P2 (2 项)

- **F-D3A-5** scripts/daily_reconciliation.py:70 删 (D2 Finding A 漏 1 处)
- **F-D3A-7** scripts/monitor_mvp_3_1_sunset.py:93 修 DINGTALK_WEBHOOK_URL 字段名

### 新增 P3 (4 项)

- F-D3A-2 api/pms.py:70 + pms_engine.py:358 删 / deprecate
- F-D3A-4 factor_evaluation DROP TABLE
- F-D3A-10 data_orchestrator.py table allowlist
- F-D3A-18 pre-push hook fail-loud

### CLAUDE.md / memory 数字 stale (3 处)

留 D3-B 整合 PR 统一更新 (CLAUDE.md L188 northbound 3.88M → 5.54M / L189 stock_status_daily 12M → 55K / L191 factor_ic_history 84K → 145K + memory PT 状态描述更新).

---

## LL "假设必实测纠错" 第 N 次同质统计

本 D3-A 第 N 次同质 LL 实例 (累计):

| 第 | 来源 | 假设 | 实测 |
|---|---|---|---|
| 1 | batch_1.5 | scheduler_task_log 状态依赖 | traceback = AttributeError on send_alert |
| 2 | batch_1.5 | risk_event_log path | dual-write |
| 3 | D2.2 | setx User scope 自动继承 | LocalSystem 不继承, 必 Machine |
| 4 | PR #152 batch 1.7 | mock target send_alert | _legacy_send_alert → _send_alert_unified |
| 5 | PR #154 | PowerShell 5.1 项目默认 | 7.6.1 user 默认 |
| 6 | D3-A D3.9 | D2 Finding A 1 处 EXECUTION_MODE=live | 实测 2 处 |
| 7 | D3-A D3.11 | D2.1 12 endpoints 无 auth | 实测 22 |
| 8 | D3-A D3.12 | T0-4 7 处 hardcoded 'live' | 实测 27+ |
| 9 | D3-A D3.12 | handoff "卓然 -29%" | 实测 -11.45% |
| 10 | D3-A E7 | pytest baseline ~3300 | 实测 4027 (+22%) |
| 11 | D3-A D3.1 | public_table_count 73 | 实测 83 (+10) |
| 12 | D3-A D3.1 | northbound 3.88M | 实测 5.54M (+43%) |

**复用规则 (LL 全局)**: 写文档/runbook/audit/finding 时, 任何"系统默认/项目标准/路径预设/版本预设/数字预设"假设, 必须附实测命令证据 + 命令输出快照. 否则降级 informational, 待二次实测.

---

## 硬门验证

| 硬门 | 结果 | 证据 |
|---|---|---|
| 改动 scope | ✅ 6 文档 (5 维度 + STATUS_REPORT) | git diff stat 验证 |
| ruff | ✅ N/A | 0 .py 改动 |
| pytest | ✅ N/A | 0 .py 改动 |
| pre-push smoke | ✅ N/A (push 时验) | bash hook (沿用上 PR) |
| 0 业务代码改 | ✅ | git diff main 仅 docs/audit/ 6 新文件 |
| 0 .env 改 | ✅ | grep diff main backend/.env = 0 |
| 0 服务重启 | ✅ | Servy 4 服务全程 Running |
| 0 DML | ✅ | 全程 SELECT only |

---

## 下一步建议

### 选项 A — 立即处理 P0 (推荐)

1. 单 PR `fix/apply-missing-migrations` — 应用 3 missing migrations (alert_dedup / platform_metrics / strategy_evaluations) + smoke 验证 SDK 路径
2. 然后启 D3-B 中维度 5 个 (~5h)

### 选项 B — 直接启 D3-B

跳过 P0 fix, 完成全 14 维 audit 后再批量修. 风险: alert_dedup 缺失若 schtask 触发可能 crash.

### 选项 C — 先 user 审 STATUS_REPORT 后决议

本 STATUS_REPORT merge 后, user 审 P0 finding + 批 2 scope 调整建议, 再决议下一步.

**Claude 推荐**: 选项 C — STATUS_REPORT 体量大, P0 finding (尤其 F-D3A-1 alert_dedup) 含 user 决策点 (3 migrations 是立即应用还是批 2 一起). 让 user 决议 scope 后再启实施.

---

## 关联

- **D2/D2.1/D2.2/D2.3** (8 untracked audit docs) — 本 D3-A 扩 5 维度. D3 整合阶段 (D3-final) 决议 8 D2 docs 命运 (合并/归档/补)
- **PR #152 batch 1.7** — 6 endpoint admin gate 已加, 但实测仍 22 endpoint 缺 gate
- **PR #153 runbook init** — runbook 治理基础设施已落地, 撤 setx runbook 待批 2 P3 后调用
- **PR #154 PowerShell 版本** — 实测确认 pwsh 7.6.1 + powershell 5.1
- **Session 44 Risk Framework v2 9 PR (#143-148)** — 真生产 0 events, 待 T0-12 验证
- **CLAUDE.md 铁律 v3.0 (X1-X7)** — 本审计为首次实施扫描, 5/42 覆盖
- **LL 第 6-12 次同质** — 累计 12 次 "假设必实测纠错" 实例, 复用规则已固化

---

## 用户接触

预期 0 (沿用 D2 系列 / 批 1.5 / runbook init / PR #154 模式, 0 业务代码 → 跳 reviewer + AI self-merge).

如本 STATUS_REPORT 触发 user 决策 (选项 A/B/C), user 接触 1 (决议下一步 scope).
