# STATUS_REPORT — 链路停止 PR (T1 Sprint, 2026-04-29)

> **PR**: [#150](https://github.com/mlhjyx/quantmind-v2/pull/150) ✅ Merged via `--rebase --delete-branch`
> **main HEAD**: `9fa18e1` (本 PR 后 +2 commits)
> **触发**: T1 sprint 期间多手术 (链路停止 / 批 1.5 / 全方位审计 / V3 设计 / 文档), 防真金风险 + 钉钉刷屏
> **关联文档**: [docs/audit/link_paused_2026_04_29.md](docs/audit/link_paused_2026_04_29.md) / [docs/audit/full_baseline_2026_04_29.md](docs/audit/full_baseline_2026_04_29.md)
> **铁律**: 33 (fail-loud) / 34 (single source) / 40 (baseline 不增) / X2 候选 (真金硬开关, ADR-022 待写)

---

## ✅ 4 件事完整交付

| # | 改动 | 状态 |
|---|---|---|
| **A** | LIVE_TRADING_DISABLED 真金硬开关 (默认 fail-secure True, 双因素 OVERRIDE + audit + DingTalk P0) | ✅ |
| **B** | risk-daily-check Beat (14:30 工作日) 注释暂停 | ✅ |
| **C** | intraday-risk-check Beat (`*/5` 9-14 工作日) 注释暂停 | ✅ |
| **D** | 2 smoke skip marker (期望已暂停 Beat 的 SAST 测试) | ✅ |

启动断言 (D 层) + 数据链 (C 层) **保留** — 漂移仍可见, 数据继续刷.

---

## 实施清单 (12 文件 / +1078 / -35 = +1043 净)

### 新建 (6)
| 文件 | 内容 |
|---|---|
| [backend/app/exceptions.py](backend/app/exceptions.py) | `LiveTradingDisabledError(RuntimeError)` |
| [backend/app/security/__init__.py](backend/app/security/__init__.py) | package init |
| [backend/app/security/live_trading_guard.py](backend/app/security/live_trading_guard.py) | `assert_live_trading_allowed()` 双因素 + audit + DingTalk + sanitize markdown |
| [backend/tests/test_live_trading_disabled.py](backend/tests/test_live_trading_disabled.py) | 14 unit + SAST tests |
| [docs/audit/link_paused_2026_04_29.md](docs/audit/link_paused_2026_04_29.md) | 还原清单 (4 件事 + 命令 + 前置 + 紧急 OVERRIDE 用法) |
| [docs/audit/full_baseline_2026_04_29.md](docs/audit/full_baseline_2026_04_29.md) | D1 baseline (顺带, 4127 collected / 14 fail / 5 finding LL) |

### 修改 (6)
| 文件 | 改动 |
|---|---|
| [backend/app/config.py](backend/app/config.py) L36-44 | 加 `LIVE_TRADING_DISABLED: bool = True` (fail-secure default) |
| [backend/engines/broker_qmt.py](backend/engines/broker_qmt.py) L408-414 + L482-489 | place_order + cancel_order 前置 guard |
| [backend/app/tasks/beat_schedule.py](backend/app/tasks/beat_schedule.py) | 整段注释 risk Beat 2 任务, `[PAUSE T1_SPRINT_2026_04_29]` 标记 |
| [backend/.env.example](backend/.env.example) | 加 LIVE_TRADING_DISABLED 段 + 注释 |
| [backend/tests/smoke/test_mvp_3_1_risk_live.py](backend/tests/smoke/test_mvp_3_1_risk_live.py) L23 | `@pytest.mark.skip` |
| [backend/tests/smoke/test_mvp_3_1_batch_2_live.py](backend/tests/smoke/test_mvp_3_1_batch_2_live.py) L23 | `@pytest.mark.skip` |

---

## 测试硬门 (全绿)

| 项 | 数字 |
|---|---|
| 14 unit + SAST tests (.venv Python) | **14 passed in 0.08s** ✅ |
| Pre-push smoke (铁律 10b) | **55 passed, 2 skipped, 1 deselected in 48.45s** ✅ |
| Ruff (8 文件) | **All checks passed!** ✅ |
| Full pytest baseline (post-link-pause, 11:54) | **17 fail / 3942 pass / 47 skip / 2 xfail** |
| 真实净增 fail (PR 引入) | **0** ✅ 铁律 40 PASS |

### 17 fail vs D1 14 fail 责任分类

| # | 类别 | 数量 | 说明 |
|---|---|---|---|
| 1 | D1 历史债 (Risk v2 PR #143-148 测试落后 / MVP 4.1 PR #131 / DB-state) | 14 | PR 0 关联, D1 baseline 已记录 |
| 2 | **Env flake** | 1 | `test_services_healthcheck.test_all_ok` — Redis portfolio:nav stale (PT 暂停 6+h), test 漏 monkey-patch `check_redis_freshness`. D1 19:30 PASS / 20:35 FAIL 仅因 Redis 状态变化 |
| 3 | **Baseline 时序 false-positive** | 2 | 2 smoke fail. Baseline 启动 (~20:23) 时 skip marker 还没加 (~20:25 加), isolated 重跑 SKIPPED ✅ |

---

## Reviewer 双 agent 闭环

并行 spawn 2 reviewer (`oh-my-claudecode:code-reviewer` + `oh-my-claudecode:security-reviewer`),
合并 0 P0 + 0 P1 + 4 P2 + 7 P3 = 11 findings.

### ✅ 全采纳 P2 (4)

| # | 等级 | 来源 | 采纳 fix |
|---|---|---|---|
| #1 | P2 | sec | Future QMTSellBroker bypass: 加 `TestAllXtquantOrderCallsGuarded` SAST scan 全 codebase `_trader.order_stock` |
| #2 | P2 | sec | DingTalk markdown 注入: sanitize override_reason / script (backtick→单引号 + 限长 200/100) |
| #3 | P2 | code | cancel_order 语义错位: `code=str(order_id)` → `code=f"order_id={order_id}"` |
| #4 | P2 | code | DingTalk except 太宽: narrow `(OSError, RuntimeError, ValueError, TimeoutError)` |

### ✅ 部分采纳 P3 (2 doc typo)

- "5 文件" → "6 文件 (新建 3 / 改 3)" in 还原清单 §A
- "13 unit + 2 SAST + 1 settings + Beat = 13 tests" → "13 tests 覆盖 7 场景"

### ✗ Dismiss P3 (5, reviewer 自标 acceptable)

- DingTalk webhook URL 流转 (send_alert 不 log args)
- sys.argv[0] not trusted (operation/code 是权威)
- monkeypatch settings 模式 note (current pattern correct)
- smoke skip 减覆盖 (还原清单 §D 已 cover)
- lazy import 内函数 (Engine import App 张力, lazy 是 mitigation)

### Reviewer 共识 verdict
**APPROVE** — 0 CRITICAL/HIGH, "guard 设计 solid: dual-factor OVERRIDE + 100% xtquant order 覆盖 + fail-secure 默认 + 完整 audit trail".

---

## LL-059 9 步闭环 ✅ 完整执行

1. ✅ 8 题诊断 + RED 测试设计 (Q5/Q6/Q7/Q-NEW user 决议后)
2. ✅ Branch `fix/link-pause-T1-sprint` 创建
3. ✅ RED 失败状态 (`ImportError: No module named 'app.exceptions'`)
4. ✅ GREEN 实施 (5 新 + 6 改 + 14 tests pass)
5. ✅ Reviewer 双 agent 并行 (code + security)
6. ✅ 全 P2 finding 采纳 + fix commit (`91215ee`)
7. ✅ Verify (14 tests + ruff + pre-push smoke + full baseline 净增 0)
8. ✅ Push + PR ([#150](https://github.com/mlhjyx/quantmind-v2/pull/150))
9. ✅ AI self-merge `--rebase --delete-branch` + main sync (HEAD `9fa18e1`)

**User 接触**: 1 次 (Q5/Q6/Q7/Q-NEW 决议反馈), 其他全 AI 自主.

---

## main HEAD 更新

```
9fa18e1 fix(review): link-pause PR #150 reviewer 4 P2 + 2 P3 全采纳
626d343 feat(link-pause T1-sprint): LIVE_TRADING_DISABLED 真金硬开关 + 风控 Beat 暂停
708944a docs(P0 batch 1): STATUS_REPORT.md - Tier 0 债清单 + pre-flight checklist + 批 2 prompt
```

main 推进 **+2 commits** (1 feature + 1 review-fix).

---

## 紧急 OVERRIDE 用法 (T1 期间 manual sell 必备)

```cmd
:: Windows cmd
set LIVE_TRADING_FORCE_OVERRIDE=1
set LIVE_TRADING_OVERRIDE_REASON="Emergency close 600519.SH after gap-down"
.venv\Scripts\python.exe scripts\emergency_close_all_positions.py --code 600519.SH
```

每次 OVERRIDE bypass 立即触发:
- `logger.warning` audit dict (含 timestamp / reason / script / operation / code / EXECUTION_MODE)
- DingTalk P0 推送 (sanitize 后, 防 markdown 注入)
- 双因素强制: 单设 `FORCE_OVERRIDE=1` 不够, 必须配 `OVERRIDE_REASON='<非空>'`

详见 [docs/audit/link_paused_2026_04_29.md](docs/audit/link_paused_2026_04_29.md) §A.

---

## 下一步 — Prompt 2 草稿: 批 1.5 测试债清理

```text
任务: 批 1.5 — 测试债清理 (D1 14 fail 中可清的 11 fail)

【背景】
D1 baseline (PR #149 pre) 14 fail. PR #150 链路停止后 main @ 9fa18e1, 0 净增 fail.
14 fail 中 11 可清, 3 留批 2/3:

11 可清:
- 8 fail (Risk v2 PR #143-148 测试落后): test_risk_engine 3 + test_risk_wiring 5
  - 期望 ["pms"] 实际 ["pms","single_stock_stoploss","holding_time","new_position_volatility"]
  - INSERT INTO risk_event_log → event_outbox (event sourcing 准备) test 未更新
- 2 fail (MVP 4.1 PR #131): test_services_healthcheck.{test_no_webhook_returns_false_silent, test_dingtalk_exception_returns_false}
  - alert_dedup 表 migration 测试 DB 未跑
- 1 fail (MVP 4.1 PR #131): test_platform_skeleton.test_platform_import_has_no_side_effects
  - PostgresAlertRouter 顶层 import psycopg2 违反 platform 不持 DB 客户端契约 (架构债)

3 留 (本批不清):
- test_factor_determinism: 第二次跑返 0 行 (DB cache 状态依赖)
- test_factor_health_daily x2: DB / scheduler_task_log 状态依赖
- test_services_healthcheck.test_all_ok: env-flake (Redis stale)

【目标】
- 清 11 fail → 14 fail → 3 fail (剩 D1 中 3 fail + env-flake test_all_ok = 4 fail)
- 0 新逻辑, 纯 test fixture 更新 / migration 跑 / lazy import 修
- 走 LL-059 9 步闭环 + PR

【强制思考 (开工前 8 题)】
1. Risk v2 8 fail: 改 test 期望值匹配新接口 vs revert factory 默认 rule 集合 — 选哪个?
   (我倾向改 test, factory 行为是 PR #143-148 有意扩展)
2. event_outbox vs risk_event_log 切换: 是否会影响生产链路 reading 端 (audit / alert)?
3. alert_dedup 表 migration 是否在 conftest 自动 apply? 还是手工 ALTER 测试 DB?
4. PostgresAlertRouter psycopg2 顶层 import: 改 lazy import 是否破坏 retry / connection pooling?
5. 还有其他被本次扫漏的"测试落后"债? grep "Session 44 PR" + "Risk v2"
6. 顺带 fix env-flake (test_all_ok) 加 monkey-patch redis_freshness — 是否本批可一并清?
7. test_services_healthcheck.test_all_ok 是 D1 PASS / post-link FAIL, 算历史债还是新债?
8. 11 fail 是不是真都是测试落后, 不是生产代码 bug? 改 test 而非改生产是否安全决策?

【硬执行边界】
✅ 改 backend/tests/{test_risk_engine, test_risk_wiring, test_services_healthcheck, test_platform_skeleton}.py
✅ 改 backend/qm_platform/observability/{__init__, alert}.py 改 lazy import (P3-1 sec-reviewer 候选)
✅ 跑 alert_dedup migration 到测试 DB (conftest auto-apply pattern)
✅ 走 PR + reviewer + self-merge

❌ 改任何风控规则 / risk engine 业务逻辑 (留批 2/3)
❌ 改任何 broker / 调度 / event_outbox writer (留批 2)
❌ 修 3 个非 11 fail (test_factor_determinism / test_factor_health x2)

【输出】
1. 8 题先答 (含上述强制思考)
2. RED → GREEN 全 11 fail → 0 (保留 3 fail + env-flake)
3. baseline 验证 14 fail → 3 fail (-11)
4. 走 PR + reviewer + merge
5. STATUS_REPORT
```

---

## 用户决策点 (3 选 1 或并行)

> **状态**: 链路停止 PR ✅ 完整完成. main @ `9fa18e1`. 真金风险大幅降低 (默认 fail-secure block 真实下单), 钉钉刷屏止血 (2 风控 Beat 暂停).

1. **批 1.5 测试债清理** (Prompt 2 已草稿, 推荐立启) — 11 fail → 3 fail, ~2-3h, 0 新逻辑
2. **D2 live-mode 激活路径扫描** (D1 报告内已草稿) — 路径 A/B/C 决策铺垫, 纯诊断
3. **批 2 启动** (写路径漂移 + LoggingSellBroker → QMTSellBroker) — 真金风险消除

**推荐顺序**: 批 1.5 → D2 → 路径 A/B/C → 批 2.
