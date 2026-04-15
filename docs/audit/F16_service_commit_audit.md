# F16 — Service .commit() 审计扫盘报告

> **铁律 32**: Service 层所有函数不允许调用 `conn.commit()`. 事务边界由调用方（Router / Celery task）管理. Service 发现错误必须 raise, 由调用方决定 rollback 或 retry.
> **审计时间**: 2026-04-16 (Phase D D2a)
> **当前 git HEAD**: `f200dd5 audit(d-1)`
> **扫盘命令**: `rtk grep -rn "\.commit()" backend/app/services/ | grep -v test_ | grep -v ".bak"`

---

## TL;DR

- **真实 sync .commit() 违规**: **12 处, 6 文件** (factor_compute_service.py 的 2 处是 docstring/注释, 不计)
- **Async (F18 范围, 留 Phase E)**: 7 处 — `await self._session.commit()` in `backtest_service.py` (4) + `mining_service.py` (3)
- **本扫盘后分类**: **Class A (直接删 commit) = 8 处, Class B (重构事务边界) = 0 处, Class C (leaf utility / DDL 例外) = 4 处**
- **D2c 不需要**: 原 plan 假设 risk_control_service 4 处是 Class B 重构, 实测后全部是 Class A (单事务收尾点, 调用方 `run_paper_trading.py` 已是顶层). Phase D D2 简化为 D2a + D2b 两段.

---

## 真实违规分布 (12 hits, 6 files)

| # | 文件:行号 | 函数 (def 行) | 内部 SQL | 调用链 (顶层入口) | 当前事务边界 | 分类 | 修复方案 |
|---|---|---|---|---|---|---|---|
| 1 | `notification_service.py:575` | `send_alert` (def 539) | `INSERT notifications` | 16 callers (services + scripts) | leaf utility, 已有 try/except + rollback | **C** | **保留**, docstring 注明 "C 类例外: leaf notification helper, 自管事务" |
| 2 | `notification_service.py:670` | `send_daily_report` (def 591) | `INSERT notifications` | 0 external callers (legacy/dead) | 同上 leaf 模式 | **C** | **保留**, 同 #1 docstring 注明 |
| 3 | `shadow_portfolio.py:43` | `_ensure_shadow_portfolio_table` (def 24) | `CREATE TABLE IF NOT EXISTS` (DDL) | 私有, 仅 `_write_shadow_portfolio` 调用 | DDL 幂等 | **C** | **保留**, docstring 注明 "C 类例外: idempotent DDL bootstrap" |
| 4 | `shadow_portfolio.py:183` | `_write_shadow_portfolio` (def 146) | `INSERT shadow_portfolio` 循环 | `generate_shadow_lgbm_*` ← `scripts/run_paper_trading.py:234` | INSERT loop 后 commit | **A** | **删 commit**, 调用方 `run_paper_trading.py` 是 top-level script, 自管事务 |
| 5 | `pt_monitor_service.py:88` | `check_opening_gap` (def 19) | (调 `notif_svc.send_sync` 后 commit) | `scripts/run_paper_trading.py` + `test_opening_gap_check.py` | **冗余** — `notif_svc.send_sync` 内部已经 commit | **A** | **删 commit (冗余)** |
| 6 | `pt_qmt_state.py:120` | `save_qmt_state` (def 16) | `INSERT performance_series` upsert | `scripts/run_paper_trading.py` | upsert 后 commit | **A** | **删 commit**, top-level script 自管事务 |
| 7 | `pt_data_service.py:235` | `_incremental_from_previous` (def 180) | `execute_values INSERT stock_status_daily` | `update_stock_status_daily` ← `fetch_daily_data` ← `scripts/run_paper_trading.py:160/295` | batch insert 后 commit | **A** | **删 commit** |
| 8 | `pt_data_service.py:309` | `_full_build_single_day` (def 246) | `execute_values INSERT stock_status_daily` | 同上 chain | 同上 | **A** | **删 commit** |
| 9 | `risk_control_service.py:1196` | `_ensure_cb_tables_sync` (def 1155) | `CREATE TABLE IF NOT EXISTS circuit_breaker_*` (DDL) | 私有, 仅 `check_circuit_breaker_sync` / `_upsert_cb_state_sync` 调用 | DDL 幂等 | **C** | **保留**, docstring 注明 "C 类例外: idempotent DDL bootstrap" |
| 10 | `risk_control_service.py:1376` | `check_circuit_breaker_sync` (def 1329) — 首次运行 init 早返回 | `_upsert_cb_state_sync` 后 commit | `scripts/run_paper_trading.py` | 早返回前 commit | **A** | **删 commit**, run_paper_trading 是 top-level |
| 11 | `risk_control_service.py:1554` | `check_circuit_breaker_sync` (def 1329) — 主返回路径 | 多步 `_upsert_cb_state_sync` + `_insert_cb_log_sync` 后单一 commit | 同上 | 状态机末尾 commit | **A** | **删 commit**, 同 #10 |
| 12 | `risk_control_service.py:1615` | `create_l4_approval_sync` (def 1566) | `INSERT approval_queue` + `UPDATE circuit_breaker_state` | **零调用方** (suspected dead code, grep 项目内仅 def 自身) | 单事务原子 (insert + update) | **A (with note)** | **删 commit**; 加注释 "TODO Phase E: verify dead code, possibly remove function entirely (F16 audit 2026-04-16 found zero callers)" |

---

## Async 违规 (F18 范围, 不在 Phase D)

| 文件:行号 | 函数 | 备注 |
|---|---|---|
| `backtest_service.py:84` | _ensure_table | `await self._session.commit()` |
| `backtest_service.py:102` | save_run | 同 |
| `backtest_service.py:116` | save_run (rollback path) | 同 |
| `backtest_service.py:317` | save_metrics | 同 |
| `mining_service.py:115` | (TBD) | 同 |
| `mining_service.py:146` | (TBD) | 同 |
| `mining_service.py:338` | (TBD) | 同 |

→ **Phase E F18 (async sync→sync 迁移) 处理**, 不在 Phase D D2 范围. Async 路径用 SQLAlchemy `AsyncSession`, 不能直接套铁律 32 (因为 SQLAlchemy session 的 commit 语义和 raw psycopg2 不同, 需要更深层重构).

## 注释/docstring 误报 (不是真违规)

| 文件:行号 | 内容 |
|---|---|
| `factor_compute_service.py:11` | docstring 提及 Phase C C3 改造历史 |
| `factor_compute_service.py:224` | 注释说明 INSERT 改 DataPipeline |

---

## 分类原则 (与铁律 32 一致)

### Class A (直接删除 commit)
- Service 函数内 commit 是冗余, 调用方 (Router / Celery task / 顶层脚本) 已经管理或会管理事务
- **修复**: 删除 `conn.commit()`, 测试验证, 5 把尺子全绿
- 8 处: shadow_portfolio:183, pt_monitor:88, pt_qmt_state:120, pt_data:235/309, risk_control:1376/1554/1615

### Class B (重构事务边界)
- Service 函数边界本身错了, 内部多步需要拆分, 把 commit 推到上层 Router/task
- **本次扫盘 0 处** — 原 plan 假设 risk_control 是 Class B, 实测后发现所有 risk_control 的 commit 都在状态机收尾点 (单一 commit per logical action), 调用方 `run_paper_trading.py` 是顶层脚本, 已经是事务边界, 拆分函数无收益.

### Class C (leaf utility / DDL 例外, 文档化保留)
- 4 处:
  - `notification_service.send_alert` — leaf 通知工具, 16 调用方, 自管 try/except + rollback. 推到调用方反而增加每个 caller 的事务负担, 违反 Don't Repeat Yourself.
  - `notification_service.send_daily_report` — 同上 leaf 模式, 即使 0 external callers 也保持一致性.
  - `shadow_portfolio._ensure_shadow_portfolio_table` — DDL 幂等, `CREATE TABLE IF NOT EXISTS` 必须 commit 才能让后续 SELECT 看到, 是合理的 bootstrap pattern.
  - `risk_control_service._ensure_cb_tables_sync` — 同 DDL bootstrap.
- **修复**: 不删 commit, **在函数 docstring 顶部加 "C 类例外: <理由>"** 注释 + 在文件顶部 module docstring 列出本文件的 C 类例外清单.

---

## D2b 修复顺序 (低风险 → 高风险)

每个文件单独 commit, 单独 5 把尺子. 估时 2-3h.

| Step | 文件 | 改动 | 测试 | 风险 |
|---|---|---|---|---|
| 1 | `notification_service.py` | 加 C 类例外 docstring (#1, #2) | `pytest test_notification_system.py` | 🟢 极低 (无代码改动) |
| 2 | `shadow_portfolio.py` | 加 C 类 docstring (#3) + 删 commit (#4) | `pytest test_pt_graduation_metrics.py` (间接覆盖) | 🟢 低 |
| 3 | `pt_monitor_service.py` | 删 commit (#5) | `pytest test_opening_gap_check.py` | 🟢 低 (冗余删除, notif_svc 还会 commit) |
| 4 | `pt_qmt_state.py` | 删 commit (#6) | `pytest test_qmt_*.py` (可能间接覆盖) | 🟡 中 (PT 关键路径) |
| 5 | `pt_data_service.py` | 删 commit (#7, #8) | `pytest test_daily_pipeline.py` (间接覆盖) | 🟡 中 (PT 数据拉取关键路径) |
| 6 | `risk_control_service.py` | 加 C 类 docstring (#9) + 删 commit (#10, #11, #12) + #12 dead code TODO | `pytest test_risk_control.py test_daily_risk_check.py` | 🟡 中 (熔断状态机, 多 commit 一次性删) |

**每 commit 后 sanity**:
- regression_test --years 5 max_diff=0
- check_insert_bypass --baseline 2 known_debt 不变

**最后一步 (D2 总验收)**:
- `health_check.py` 全绿 (PT 路径完整性)
- `AUDIT_MASTER_INDEX.md` F16 ⬜→✅

---

## 调用方追溯证据 (铁律 25 不靠记忆靠代码)

### send_alert (16 callers)
```
backend/app/services/signal_service.py
backend/app/services/execution_service.py
backend/app/services/risk_control_service.py
backend/app/services/pt_monitor_service.py
backend/app/services/qmt_reconciliation_service.py
backend/app/services/notification_service.py (self)
backend/services/notification_service.py (legacy duplicate)
scripts/factor_health_daily.py
scripts/daily_reconciliation.py
scripts/approve_l4.py
scripts/intraday_monitor.py
scripts/pt_watchdog.py
scripts/pg_backup.py
scripts/archive/approve_l4.py
backend/tests/test_service_smoke.py
backend/tests/test_daily_risk_check.py
```
→ 推到调用方需要 16 处加 try/except + commit, 严重 DRY 违反. 维持 Class C.

### check_opening_gap callers
```
scripts/run_paper_trading.py (top-level)
backend/tests/test_opening_gap_check.py
```
→ 单一顶层 script. Class A. 注意 commit 是在 `notif_svc.send_sync` 之后, 而 `notif_svc.send_sync` 自己已经 commit, 所以 line 88 的 commit 是 **逻辑冗余** — 即使没有 commit 也已经被 notif_svc 提交. 删除毫无副作用.

### save_qmt_state callers
```
scripts/run_paper_trading.py (top-level)
```
→ 单一顶层. Class A.

### update_stock_status_daily / fetch_daily_data callers
```
scripts/run_paper_trading.py:160, 295 (top-level)
backend/app/services/pt_data_service.py:102 (internal call: fetch_daily_data → update_stock_status_daily)
```
→ 顶层是 run_paper_trading. Class A.

### check_circuit_breaker_sync callers
```
scripts/run_paper_trading.py (top-level)
```
→ 单一顶层. Class A.

### create_l4_approval_sync callers
```
backend/app/services/risk_control_service.py:1566 (def only)
```
→ **零调用方**. Suspected dead code. 现阶段 Class A (删 commit) + 加 TODO 注释, 留 Phase E 决策是否删除函数.

### run_daily_risk_check_sync callers
```
backend/app/services/risk_control_service.py:1634 (def only)
```
→ 同样零调用方, 但本函数没有 .commit() 不在 F16 范围, 一并标 TODO.

### generate_shadow_lgbm_signals/inertia callers
```
scripts/run_paper_trading.py:234 (top-level, for-loop)
```
→ 单一顶层. shadow_portfolio:183 Class A.

### send_daily_report callers
```
backend/app/services/notification_service.py (self)
backend/services/notification_service.py (legacy duplicate, also self)
```
→ **零真实外部调用方**. 函数可能是 dead code, 但保持 Class C 一致性 (与 send_alert 同模式).

---

## 工件清单 (Phase D D2a 产出)

- 本报告: `docs/audit/F16_service_commit_audit.md`
- 0 代码改动 (扫盘 only)
- D2b 阶段开始执行修复 (per file commit)

---

**铁律 28 范围外发现** (Phase D D2a 期间发现, 不在本 Phase 范围, 留 Phase E):

1. **`risk_control_service.create_l4_approval_sync` suspected dead code** — 零调用方. 但 L4 熔断恢复链路可能依赖. 需要 Phase E 验证: 是否被 `scripts/approve_l4.py` 调用? 是否被前端 approval API 调用? 是否被 Celery beat 任务调用?
2. **`risk_control_service.run_daily_risk_check_sync` suspected dead code** — 同上, 零调用方.
3. **`backend/services/notification_service.py`** legacy duplicate file 存在 — 应该统一到 `backend/app/services/notification_service.py`, 但需要先确认 legacy 文件零生产引用. Phase E 清理.
4. **F18 async sync→sync 迁移** — `backtest_service.py` (4 commits) + `mining_service.py` (3 commits) — Phase E P1.
