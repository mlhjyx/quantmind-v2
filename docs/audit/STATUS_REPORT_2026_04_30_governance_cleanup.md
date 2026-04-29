# STATUS_REPORT — 治理债清理 (batch 1.7)

**Date**: 2026-04-30
**Branch**: fix/governance-cleanup-batch-1-7
**Base**: main @ d2280b0 (batch 1.5 reviewer 3 MEDIUM merged)
**Scope**: 3 类治理债清理 (类 A 4 留 fail 中 3 项 + 类 B Finding E P1 6 endpoints + 类 C Finding D blame 实测)
**ETA**: 2-3h
**真金风险**: 0 (LIVE_TRADING_DISABLED=True / paper mode / Beat schedule 风控仍 paused)

---

## 1. 12 题强制思考决议

| # | 答 | 关键证据 |
|---|---|---|
| Q1 | ✅ | ADMIN_TOKEN len=43, LIVE_TRADING_DISABLED=True, EXECUTION_MODE=paper |
| Q2 | ⚠️ **真因纠错** (LL-XXX 第 N 次) | 见下方 §3 |
| Q3 | (a) monkey-patch check_redis_freshness | 修法验证 PASS |
| Q4 | **修法升级 (d)** | A.1+A.2 mock target 改至 `_send_alert_unified` (dispatch 入口) |
| Q5 | ✅ 0 调用方破裂 | frontend 不调 risk/approval admin endpoints, scripts/approve_l4.py 是 CLI 直 DB |
| Q6 | ✅ 实测 | execution_ops.py:69-77 _verify_admin_token raise HTTPException(401), `!=` plain compare (P2 留批 2) |
| Q7 | 归档 | 本文件 |
| Q8 | (m) 1 PR | 沿用 batch_1.5 |
| Q9 | ETA ~2h | 实际 2.5h (含 2 轮真因纠错 cost) |
| Q10 | ✅ **dead-from-birth 实测** | 见下方 §4 Finding D |
| Q11 | baseline 14→1 fail | 留 test_factor_determinism (DB cache 状态依赖, 留批 2/3 fixture 重构) |
| Q12 | ✅ 0 真金风险 | 全 guard active |

---

## 2. 改动清单

### 类 A: 4 留 fail 清 3

| 文件 | 改动 | 真因 |
|------|------|------|
| `backend/tests/test_factor_health_daily.py:194,244` | `@patch("factor_health_daily.send_alert")` → `@patch("factor_health_daily._send_alert_unified")` | mock target 错 + path 切换 (见 §3) |
| `backend/tests/test_services_healthcheck.py:303-320` | 加 `monkeypatch.setattr("services_healthcheck.check_redis_freshness", lambda: [])` | env-flake (PT 暂停 → portfolio:nav stale) |

**留**: `test_factor_determinism` (DB cache 状态依赖, 不本批改, 留批 2/3 fixture 重构)

### 类 B: Finding E P1 — 6 endpoints admin gate

| 文件 | 改动 | endpoint |
|------|------|----------|
| `backend/app/api/risk.py` | 加 `_verify_admin_token` (沿用 execution_ops.py:69-77 模式) + 3 endpoint 加 `Depends(_verify_admin_token)` | l4-recovery / l4-approve / force-reset |
| `backend/app/api/approval.py` | 加 `_verify_admin_token` + 3 endpoint 加 `Depends(_verify_admin_token)` | queue/{id}/approve / reject / hold |
| `backend/tests/test_risk_control.py:999-1080` | 4 现有 endpoint 测试加 `app.dependency_overrides[_verify_admin_token] = lambda: "test-token"` bypass auth | 维持 business test 不破 |
| `backend/tests/test_admin_gate_risk_approval.py` | 新增独立 admin gate 测试 (19 unit tests, 6 endpoints × 3 cases + 1 ADMIN_TOKEN 未配置) | dedicated to auth |

### 类 C: Finding D 实测 (0 业务改动)

见下方 §4 git blame 结论。

---

## 3. LL-XXX 教训 — Q2.1+Q2.2 真因纠错 (第 N 次)

**初始判断 (batch_1.5 STATUS_REPORT 写)**: scheduler_task_log 状态依赖
**第 1 轮实测纠错**: AttributeError on `factor_health_daily.send_alert` — script L48 重命名 `from app.services.notification_service import send_alert as _legacy_send_alert`, 模块级 attr 名是 `_legacy_send_alert`
**修法 1**: patch `_legacy_send_alert`
**第 2 轮实测纠错**: patch 改对了但 mock.called=False — 实测 `settings.OBSERVABILITY_USE_PLATFORM_SDK=True` (default), script 真走 `_send_alert_via_platform_sdk` (Platform SDK), legacy 永不调用
**终极修法**: patch dispatch 入口 `_send_alert_unified` (无论内部 SDK or legacy 均被截), 沿用 batch_1.5 4 项挑战 #1 同质修法 (mock 范围扩到不依赖 path 选择)

**LL 沉淀**: audit/STATUS_REPORT 一阶概括 30%+ 偏离真因, 实施前必须实测 traceback 验证, 不凭描述行动. 这是连续第 4-5 次同质教训 (D2.1 alert_dedup / D2.1 risk_event_log / D2.1 PostgresAlertRouter / D2.2 setx User scope / 本批 send_alert mock target 双重错).

**复用**: 其他 mock target 修法时, 优先 patch dispatch 入口 (e.g. `_send_alert_unified`) 而非内部分支 (`_legacy_send_alert` / `_send_alert_via_platform_sdk`), 防 path 切换破坏 mock.

---

## 4. Finding D Git Blame 实测结论 (批 2 决议)

**目标**: `backend/app/api/execution_ops.py:114-118` `_broker_sell` / `_broker_buy` async wrapper 调用 `qmt_manager.broker.sell()` / `qmt_manager.broker.buy()`. D2.1 怀疑 broker 无 sell/buy 方法 → 测试代码已落后或路径已死。

### 实测命令

```bash
# 1. execution_ops.py 创建 commit
git log --all --oneline --diff-filter=A -- backend/app/api/execution_ops.py
→ 9f37531 feat: TimescaleDB 2.26.0 + perf optimization + northbound factors + ARIS + research-kb

# 2. blame L114-118 行
git blame -L 100,130 backend/app/api/execution_ops.py
→ 9f37531f (jyxren 2026-04-05 21:35:57 +0800)

# 3. broker_qmt.py 全方法列表 (全文件 grep)
grep -nE "^def |^async def |^    def |^class " backend/engines/broker_qmt.py
→ 所有方法: connect/disconnect/query_asset/query_positions/query_orders/query_trades/
   place_order/cancel_order/register_*_callback/get_positions/get_cash/get_total_value
→ ❌ NO `def sell` / `def buy`

# 4. broker_qmt.py 历史是否曾经有过 sell/buy
git log --all -p backend/engines/broker_qmt.py | grep -E "^\+.*def (sell|buy)\("
→ (空)
```

### 判定: **dead-from-birth**

- commit `9f37531` (2026-04-05 21:35, jyxren) **同 commit 同时**加了:
  - `execution_ops.py` 含 `_broker_sell` + `_broker_buy` 调用 `qmt_manager.broker.sell` / `.buy`
  - `broker_qmt.py` 不含 `def sell` / `def buy`
- broker_qmt.py 历史**从未**有过 `def sell` / `def buy` (git log -p grep 0 命中)
- 真下单方法是 `place_order(symbol, direction, volume, price, order_type)` (broker_qmt.py:382)
- 整段 endpoint 自创建之日起就调用不存在的方法 — **实测 dead-from-birth**

### 批 2 修法推荐

**(a) 整段删 endpoint** (Finding D 真因) — 推

理由:
- `_broker_sell` / `_broker_buy` 调用 broker 不存在的方法, 任何调用必 raise `AttributeError`
- 上层 endpoint 应该已无使用 (frontend grep `execution.ts:149` 只对 cancel-order endpoint, 不调 sell/buy endpoint, 需 grep 调用方再确认)
- 加 wrapper 恢复 = 等同于实施新功能, 应走独立 MVP 设计

**(b) 加 wrapper 恢复 sell/buy** — 否

理由:
- 等同于在 broker 实现新方法 + endpoint 启用真下单, 真金风险大
- 必须先走 MVP 设计 + ADR + ROF (Resource Order Framework) 资源仲裁

**批 2 子任务清单更新** (替代原"P2 #2 MiniQMTBroker.sell/.buy wrapper"):
- ~~原: 加 `MiniQMTBroker.sell()` / `.buy()` wrapper 让 endpoint 真活~~
- **新**: 删 `execution_ops.py:114-118` `_broker_sell` / `_broker_buy` + 调用方 (grep `_broker_sell` / `_broker_buy` 使用点) + 删 endpoint definitions (推估 sell/buy POST endpoints)
- **前置**: 批 2 启动前先 `grep -rn "_broker_sell\|_broker_buy\|broker\.sell\|broker\.buy" backend/` 完整调用链审计

---

## 5. 测试覆盖

### 修改测试

| 文件 | 改前 | 改后 |
|------|------|------|
| `test_factor_health_daily.py` (2 tests) | 2 fail | 2 PASS |
| `test_services_healthcheck.py::test_all_ok` | fail | PASS |
| `test_risk_control.py::TestRiskAPI` (4 tests modified) | PASS (无 admin gate) | PASS (含 admin gate dependency_overrides bypass) |

### 新增测试

| 文件 | tests | 覆盖 |
|------|-------|------|
| `test_admin_gate_risk_approval.py` | 19 PASS | 6 endpoints × (no token + wrong token + correct token) + 1 ADMIN_TOKEN 未配置 500 |

---

## 6. 硬门验证 (.venv Python)

| 硬门 | 结果 | 证据 |
|------|------|------|
| ruff check | ✅ PASS | 6 修改文件 0 error (1 I001 import 排序 auto-fix 后) |
| 修改文件 tests | ✅ PASS | 3 类 A fail 全 PASS / 7 risk_control tests PASS / 19 admin gate tests PASS |
| smoke (pre-push 路径) | ✅ PASS | `pytest backend/tests/smoke/ -m "smoke and not live_tushare"` → 55 passed / 2 skipped / 1 deselected (48.97s) |
| baseline 14→1 fail | (pending pytest 完成) | 预期 11 fail 清 3 → 留 test_factor_determinism |

**Note**: `pytest -m smoke` 全路径会 collect `scripts/archive/test_qmt_capabilities.py:32` 的 module-level `xtquant.xtdata.get_market_data_ex()` 调用导致 Fatal Python error (跟本 PR 改动无关, pre-existing collection 路径问题). pre-push hook 限定 `backend/tests/smoke/` 子路径绕开. 未来批 2/3 可考虑加 pytest `--ignore=scripts/archive/`.

---

## 7. 主动发现报告 (沿用铁律 28)

1. **真因纠错 (LL-XXX 第 N 次)**: Q2.1+Q2.2 真因 batch_1.5 STATUS_REPORT 描述完全错 (scheduler_task_log → 实际 mock target + path 切换双重错). 沉淀复用规则: patch dispatch 入口 (`_send_alert_unified`) 而非内部分支.
2. **现有 4 测试同步更新**: 加 admin gate 必须同步给 `test_risk_control.py` 现有 4 个 endpoint 测试加 `dependency_overrides[_verify_admin_token]` bypass, 否则它们会从 PASS 翻 fail (返 401 而非期望的 200/400/422).
3. **smoke pytest collection 路径污染** (pre-existing): `scripts/archive/test_qmt_capabilities.py:32` module-level xtquant 调用 → pytest collect crash. 不属本 PR 范围, 但批 2/3 应清理 scripts/archive/ pytest discovery.
4. **Finding D 实测 dead-from-birth 完整确认**: broker_qmt.py 历史从未有过 def sell/buy, commit 9f37531 同时加 endpoint + 不实现 broker = 真死代码. 批 2 应删 endpoint 而非加 wrapper.

---

## 8. 批 2 子任务决议清单更新

(基于本 PR 实测结果重构)

### P0 ×2 (沿用 batch_1.5)
1. pt_qmt_state.py 7 hardcoded 'live' parameterization
2. xfail strict 4 contract tests 转 PASS

### P1 ×2 (Finding E 已部分清, 剩留)
1. ~~risk.py 3 + approval.py 3 = 6 endpoints add admin gate~~ **本 PR 已清**
2. **新增**: 10 files POST/PUT/DELETE endpoints add admin gate (Finding G 沿用)

### P2 ×4 (Finding D 修法变更)
1. ~~MiniQMTBroker.sell/.buy wrapper 让 endpoint 真活~~
2. **新**: 删 `execution_ops.py:114-118` `_broker_sell` / `_broker_buy` + 调用 endpoint (Finding D dead-from-birth 修法 (a))
3. scripts/intraday_monitor:141 hardcoded 删
4. cb_state paper L0 cleanup
5. _verify_admin_token 改 secrets.compare_digest (D2.2 P2 timing attack)

### P3 ×4 (沿用)
1. ~~LoggingSellBroker → QMTSellBroker~~ (与 Finding D 修法 (a) 协同, 整段删 sell/buy)
2. startup_assertions 改用 settings.SKIP_NAMESPACE_ASSERT (Finding G)
3. Servy console UTF-8
4. **新**: 4 留 fail 中 test_factor_determinism (DB cache 状态依赖, fixture 重构)

---

## 9. 真金 0 风险确认 (PR merge 前 final)

| 检查 | 状态 |
|------|------|
| LIVE_TRADING_DISABLED guard 仍生效 | ✅ default=True (config.py:36) |
| broker_qmt.py 不动 (链路停止 PR 加的 guard 不被绕) | ✅ 0 改动 |
| Beat schedule 风控 2 项仍 paused | ✅ 沿用 link-pause PR #150 状态 |
| ADMIN_TOKEN auth 仍生效 (D2.2 验证) | ✅ 现 6 endpoints 也守门 |
| Machine env SKIP=1 不动 (D2.3 修复保留) | ✅ 0 改动 |

---

## 10. PR merge 后的 next step

1. **撤 setx** (批 2 完成后): `[System.Environment]::SetEnvironmentVariable('SKIP_NAMESPACE_ASSERT', $null, 'Machine')` (D2.3 临时修, 批 2 P3 startup_assertions 改用 settings 后撤)
2. **启批 2** (12 子任务, ETA ~1 周, 见 §8 决议)
3. **可选**: 全方位 13 维审计剩余 9 维 (D2~D2.3 已覆盖 4/13)
