# 链路停止 还原清单 — 2026-04-29 (T1 Sprint)

> **PR**: `fix/link-pause-T1-sprint` → main
> **触发**: T1 sprint 期间手术多, 真金 + 钉钉刷屏双风险. 链路停止 PR 暂停 Beat 风控触发链 + 加 LIVE_TRADING_DISABLED 真金硬开关.
> **作者**: AI 自主 (LL-059 9 步闭环), 用户 0 接触.
> **关联 ADR**: ADR-022 (待写) 真金硬开关归属表.

---

## 暂停项总览 (4 件事)

| # | 改动 | 文件 | 还原前置 | 还原命令 |
|---|---|---|---|---|
| **A** | LIVE_TRADING_DISABLED 真金硬开关 (config + exceptions + guard + broker_qmt 双因素 OVERRIDE) | 6 文件 (新建 3 / 改 3) | 批 2 写路径漂移修 + 批 2 LoggingSellBroker→QMTSellBroker + .env=live | 见下 §A |
| **B** | Celery Beat `risk-daily-check` (14:30 工作日) 注释 | beat_schedule.py | T1.4 完成 / 漂移修 / 想恢复钉钉告警 | 见下 §B |
| **C** | Celery Beat `intraday-risk-check` (`*/5` 9-14 工作日) 注释 | beat_schedule.py | 同 §B | 见下 §C |
| **D** | 2 smoke skip (`test_mvp_3_1_risk_framework_imports` + `test_mvp_3_1_batch_2_intraday_imports`) | 2 smoke 文件 | §B + §C 还原后同步 | 见下 §D |

启动断言 (`backend/app/services/startup_assertions.py`) **保留** — 命名空间漂移仍可见, fail-loud 不被这次链路停止 cancel.

数据链 (`scripts/qmt_data_service.py` / `realtime_data_service.py`) **保留** — 数据继续刷, 持仓快照仍记录.

---

## §A — LIVE_TRADING_DISABLED 真金硬开关 (4 文件)

### 改动详情

| 文件 | 改动语义 | 行号 |
|---|---|---|
| `backend/app/exceptions.py` (**新建**) | `LiveTradingDisabledError(RuntimeError)` 类 | 全文件 |
| `backend/app/security/__init__.py` (**新建**) | 包初始化 | 1-3 |
| `backend/app/security/live_trading_guard.py` (**新建**) | `assert_live_trading_allowed()` 双因素 OVERRIDE + audit | 全文件 |
| `backend/app/config.py` | 加 `LIVE_TRADING_DISABLED: bool = True` 字段 | L36-44 (EXECUTION_MODE 后) |
| `backend/engines/broker_qmt.py` | `place_order` (L408-414) + `cancel_order` (L482-487) 前置 guard | 2 处 |
| `backend/.env.example` | 加 `LIVE_TRADING_DISABLED=true` 示例 + 注释 | L22-31 |
| `backend/.env` | (**未改 — 项目 hook 保护**) — 默认 True 在 config.py 已生效 | — |

### 还原前置

- ✅ 批 2 写路径漂移消除 (pt_qmt_state 5 处 hardcoded 'live' + execution_service._execute_live)
- ✅ 批 2 LoggingSellBroker → QMTSellBroker 替换 (PMS L1/L2/L3 触发后真卖)
- ✅ user 决策 .env=live cutover
- ✅ 全方位审计 PASS

### 还原命令

```bash
# 选项 1: revert 整个 PR (最简单)
git revert <PR-link-pause-merge-commit>

# 选项 2: 关 flag 但保代码 (推荐 — 紧急 OVERRIDE 通道仍在)
# 改 backend/.env (用户手工):
#   LIVE_TRADING_DISABLED=false
# 重启 Servy QuantMind-FastAPI / QuantMind-Celery

# 选项 3: 永久撤回 (T1 sprint 手术全完后 + 批 2/3 完成后)
# (a) 改 config.py:36-44 默认改回 False (撤 fail-secure)
# (b) 删 backend/app/security/live_trading_guard.py
# (c) 删 backend/app/exceptions.py (LiveTradingDisabledError 类)
# (d) 删 backend/engines/broker_qmt.py L408-414 + L482-487 guard 调用
# (e) 删 backend/tests/test_live_trading_disabled.py
# (f) 删 backend/.env.example LIVE_TRADING_DISABLED 段
```

### 紧急 OVERRIDE 用法 (T1 期间 manual sell 必备)

需要紧急清仓 (e.g. user 手工 `scripts/emergency_close_all_positions.py`) 时:

```cmd
:: Windows cmd
set LIVE_TRADING_FORCE_OVERRIDE=1
set LIVE_TRADING_OVERRIDE_REASON="Emergency close 600519.SH after gap-down 2026-04-30"
.venv\Scripts\python.exe scripts\emergency_close_all_positions.py --code 600519.SH
```

```bash
# bash
LIVE_TRADING_FORCE_OVERRIDE=1 \
  LIVE_TRADING_OVERRIDE_REASON="Emergency close" \
  .venv/Scripts/python.exe scripts/emergency_close_all_positions.py --code 600519.SH
```

**自动审计**: 每次 OVERRIDE bypass 立即 (a) `logger.warning` audit dict / (b) DingTalk P0 推送 / (c) sys.argv[0] 调用脚本记录.

**双因素**: 单设 `LIVE_TRADING_FORCE_OVERRIDE=1` 不够, 必须同时 `LIVE_TRADING_OVERRIDE_REASON='<非空 reason>'`.

---

## §B — risk-daily-check Beat 暂停

### 改动

`backend/app/tasks/beat_schedule.py:59-70` 整段注释 (10 行 → 11 行注释).

### 还原前置

- ✅ §A 还原后 (LIVE_TRADING_DISABLED 不再 fail-loud 阻断 wiring)
- ✅ T1.4 完成 / 漂移修 (entry_price=0 silent skip 根因消除)
- ✅ 用户重新激活钉钉告警链需求

### 还原命令

```bash
# 取消注释整个 risk-daily-check 段 (sed 较脆, 推荐手工编辑):
# 在 beat_schedule.py 找 "[PAUSE T1_SPRINT_2026_04_29] risk-daily-check 暂停" 行
# 后续 ~12 行: 删除 # 前缀, 恢复活动状态.

# 或 grep 验证暂停文案存在:
grep -n "PAUSE T1_SPRINT_2026_04_29.*risk-daily-check" backend/app/tasks/beat_schedule.py
```

---

## §C — intraday-risk-check Beat 暂停

### 改动

`backend/app/tasks/beat_schedule.py:71-83` 整段注释 (13 行 → 11 行注释).

### 还原前置

同 §B.

### 还原命令

```bash
# 取消注释整个 intraday-risk-check 段:
grep -n "PAUSE T1_SPRINT_2026_04_29.*intraday-risk-check" backend/app/tasks/beat_schedule.py
# 在该行后续 ~11 行: 删除 # 前缀.
```

---

## §D — 2 smoke skip 取消

### 改动

| 文件 | 改动 | 行号 |
|---|---|---|
| `backend/tests/smoke/test_mvp_3_1_risk_live.py` | 加 `@pytest.mark.skip(reason="T1 sprint link-pause...")` | L23 后 |
| `backend/tests/smoke/test_mvp_3_1_batch_2_live.py` | 加 `@pytest.mark.skip(reason="T1 sprint link-pause...")` | L23 后 |

### 还原前置

§B + §C 还原后同步.

### 还原命令

```bash
# 在两个文件中删除 skip 装饰器:
# grep 文件 + 手工编辑删除 @pytest.mark.skip(...) 整段 (4 行).
grep -rn "T1 sprint link-pause" backend/tests/smoke/
```

---

## 设计决策表 (本 PR 沉淀)

| 决议 | 选择 | 论据 |
|---|---|---|
| Q5 默认值 | `LIVE_TRADING_DISABLED: bool = True` (fail-secure) | 真金保护必须默认安全, 重启不带 .env 时立即生效 |
| Q6 paper 豁免 | (X) 物理隔离, guard 只挂 MiniQMTBroker.place_order/cancel_order | paper_broker 不 import guard, 自动豁免 |
| Q7 异常类型 | `LiveTradingDisabledError(RuntimeError)` in `app/exceptions.py` | 沿用 NamespaceMismatchError 模式, 类型化便于 catch |
| 加固 1 (双因素) | OVERRIDE=1 单独不够, 必须配 REASON 非空 | 防 OVERRIDE=1 误设 (e.g. 测试遗留 env), reason 强制 accountability |
| 加固 2 (审计) | bypass 同步 logger.warning audit + DingTalk P0 + sys.argv 脚本 | 真金行为必留 audit trail, 即使后续 broker 调用失败也已记录 |
| 钉钉失败容错 | silent_ok (try/except 包 send_alert + logger.exception) | 防 DingTalk 不可达时连紧急清仓都阻断 = 真紧急时 user 自己救不了 |

---

## 测试覆盖 (13 tests 覆盖 7 场景)

| 测试 | 目的 |
|---|---|
| `test_override_disabled_raises` | LIVE_TRADING_DISABLED=true + 无 OVERRIDE → raise |
| `test_disabled_false_passes` | LIVE_TRADING_DISABLED=false → 放行 (向后兼容) |
| `test_override_without_reason_raises` | OVERRIDE=1 + REASON 空 → raise (加固 1) |
| `test_override_with_whitespace_only_reason_raises` | REASON='   ' → strip 后空 → raise |
| `test_override_flag_zero_with_reason_still_raises` | FLAG=0 → raise (FLAG 必精确 == '1') |
| `test_override_with_reason_bypasses` | OVERRIDE=1 + REASON 非空 → bypass + DingTalk P0 |
| `test_override_logs_audit_trail` | bypass 时 logger.warning audit 含 timestamp/reason/script |
| `test_override_dingtalk_failure_does_not_block_bypass` | 钉钉 raise → bypass 仍 PASS (silent_ok) |
| `test_paper_broker_no_guard_import` | SAST: paper_broker.py 不 import guard |
| `test_broker_qmt_imports_guard` | SAST: broker_qmt.py 必 import guard |
| `test_broker_qmt_place_and_cancel_call_guard` | SAST: place_order + cancel_order 各 1 处 |
| `test_risk_beat_tasks_not_active` | Beat schedule 不再含 risk-daily-check / intraday-risk-check |
| `test_settings_default_is_true` | LIVE_TRADING_DISABLED 默认 True (fail-secure) |

---

## 还原校验 checklist (T1 全完后用)

还原 §A + §B + §C + §D 后, 验证:

- [ ] `pytest backend/tests/test_live_trading_disabled.py` → 13 fail (代码已删, tests 也应删, 同步)
- [ ] `pytest -m smoke` → 71 passed (无 skip, 还原 §D)
- [ ] `from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE` 含 `risk-daily-check` + `intraday-risk-check`
- [ ] `from app.config import settings; assert settings.LIVE_TRADING_DISABLED` raise AttributeError (字段已删)
- [ ] FastAPI / Celery / QuantMind-* 服务重启 PASS
- [ ] regression_test 5yr / 12yr max_diff=0 (回归不变)
- [ ] PT live 真启动 health_check OK (订单链路恢复)

---

> **状态**: T1 sprint link-pause active.
> **解除窗口**: 批 2 完成 + 用户 cutover 决策, 至少 1 周后 (2026-05-06+).
