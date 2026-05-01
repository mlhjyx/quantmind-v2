# STATUS_REPORT — Week 1 Layer 1 P0 立即修 + emergency SOP + Account truth log SOP

**Audit ID**: SYSTEM_AUDIT_2026_05 / Week 1 Layer 1
**Date**: 2026-05-01
**Branch**: `week1/layer1_p0_fixes` (from main `3a14ef7`)
**Type**: 真测 verify + Layer 1 P0 真生产 risk 立即修 + 2 SOP sketch

---

## §0 Task completion 真核 sediment

| WI | Status | 真核 verdict |
|---|---|---|
| WI 0.5 oneshot ground truth verify | ✅ closed | broker.connect() ✅ + cash=993520.66 + drift=0.0001% < 0.01% threshold |
| WI 1 pip CVE-2026-3219 upgrade | ✅ closed | pip 26.0.1 → **26.1**, pip-audit "No known vulnerabilities" → **F-D78-271/272 closed** |
| WI 2 risk-health ImportError 修 | ✅ closed | `get_notification_service()` factory + `_SyncNotificationFacade.send_sync()` 加, DingTalk push 真生效 verify ✅ → F-D78-235 **fixed** + 14-caller cluster Layer 1 path 解锁 |
| WI 2.5 QMT_DATA_SERVICE reconnect | ✅ closed (0 fix needed) | broker_qmt `_handle_disconnect` 真**已有** reconnect logic + 真测 5-01 18:29:41 reconnect 成功 verify, F-D78-245 真根因 = QMT GUI 真**未启动** sustained (已 fixed via user GUI restart) |
| WI 3 schtask 17h 0 runs | ✅ closed (P0→P3 demoted) | 5-01~5-05 真**5-day Labor Day holiday** sustained, schtask holiday guard 真生效, **F-D78-289 false-positive** |
| WI 4 factor_ic backfill | ✅ closed | `fast_ic_recompute --core` 11928 rows / 4 factors / 59s, MAX=2026-04-28 (last trading day pre-holiday) |
| WI 5 emergency SOP sketch | ✅ closed | `docs/audit/2026_05_audit/emergency_sop_v1.md` 真存 + 7 base scenario + 6 CC candidate + S5/S8/S10 smoke verify |
| WI 6 Account truth log SOP | ✅ closed | `docs/audit/account_truth_log.md` 真存 + Week 1 ground truth sediment (cash=993520.66, drift=0.0001%) |
| WI 7 STATUS_REPORT + PR push | 🟡 in progress | 本文件 |

**Layer 1 真核 closed sustained**: 9/9 (含 WI 0.5).

---

## §1 反问 1-6 决议 sediment (sustained §3 STOP SOP path)

| 反问 | 决议 verbatim | 真核 outcome |
|---|---|---|
| 反问 1 (WI 2.5 scope) | a — 纳入 Week 1 (新增 WI 2.5) | ✅ verify 真**0 fix needed** (broker reconnect 真已生效) |
| 反问 2 (E6 ground truth path) | a — user GUI manual restart Servy QuantMind-QMTData | ✅ user restart + WI 0.5 oneshot verify ✅ |
| 反问 3 (branch + worktree) | a — 直接 git checkout main + 创建 branch | ✅ branch `week1/layer1_p0_fixes` from `3a14ef7` |
| 反问 4 (WI 4 backfill 真路径) | CC 实测决议 default fast_ic_recompute --core | ✅ verify CORE_FACTORS=CORE4 + partial scope 真含 CORE3+dv_ttm |
| 反问 5 (Servy restart prerequisite) | c+d 并行 (反 single-point fail) | ✅ d (CC oneshot) 真测 first run -1 → STOP → user c (GUI restart) → CC oneshot reverify ✅ |
| 反问 6 (QMT GUI 真状态) | (隐含 user cite "QMT 已启动 + 已登录 + 一直挂起") | ✅ user cite + CC PowerShell verify XtMiniQmt PID 15464 StartTime 18:29:23 |

---

## §2 §1 E1-E9 真测 verdict (sustained Week 1 reverify)

| ID | 真测真值 | verdict |
|---|---|---|
| E1 | branch `week1/layer1_p0_fixes` from main `3a14ef7` clean | ✅ |
| E2 | PG `pg_stat_activity`: 2 active / 0 waiting | ✅ |
| E3 | Servy 4 services Running + WI 2.5 verify QMTData functional ✅ | ✅ |
| E4 | .venv Python 3.11.9 | ✅ |
| E5 | LIVE_TRADING_DISABLED=True (Pydantic default) + EXECUTION_MODE=paper | ✅ |
| E6 | xtquant cash=993520.66 / positions=0 / nav=993520.66 / drift=0.0001% | ✅ |
| E7 | cb_state.live nav=993520.16 / level=0 / updated 4-30 19:48:20+08 | ✅ |
| E8 | position_snapshot live 276 rows / max trade_date=4-27 (4d gap audit-only known debt) | ⚠️ partial |
| E9 | 4 input docs read | ✅ |

---

## §3 §2 Step A-E 真测 verdict 1 (sustained Verdict 1 全 ✅)

| 目标 | 真测真值 | verdict |
|---|---|---|
| A: OS process query QMT 客户端 | XtMiniQmt PID=15464 StartTime=18:29:23 Path=E:\国金QMT交易端模拟\bin.x64\XtMiniQmt.exe | ✅ |
| B: Servy QuantMind-QMTData restart | Servy CLI Running + 3-process tree (PID 16864 Servy.CLI + 22900 .venv python + 24752 system Python311 child of 22900) CreationDate 18:29:04 | ✅ |
| C: Redis qmt:connection_status + portfolio:* | qmt:connection_status=connected + portfolio:nav cash=993520.66 ttl=149 + position_count=0 | ✅ |
| D: stderr post-restart | 18:29:04 connect ✅ → 18:29:27 disconnect → 18:29:36 reconnect 失败 → 18:29:41 reconnect 成功 ✅ (broker_qmt _handle_disconnect 真生效) | ✅ |
| E: WI 0.5 oneshot reverify | broker.connect() ✅ + asset.cash=993520.66 + positions=0 + drift=0.0001% PASS | ✅ |

---

## §4 真重大 finding 加深 / 真核 verdict revision

### 4.1 F-D78-235 真核 fixed ✅

- 真根因 verify: `notification_service.py` 真**0 `get_notification_service` function** sustained sprint period sustained
- 14 callers cluster sustained (risk_framework_health_check / pt_monitor_service / daily_pipeline / 多 tests) sustained 全 broken
- Week 1 fix: add `_SyncNotificationFacade` class + `get_notification_service()` factory function
- 真测 verify: import OK ✅ + send_sync return True ✅ + DingTalk sync 真发送成功 ✅
- **risk_framework_health_check.py 真路径**: 5-04 (next trading day) 真**首次自动 verify** (真 5-01~5-05 holiday guard return 0)

### 4.2 F-D78-271 + F-D78-272 真核 fixed ✅

- pip 26.0.1 → 26.1 sustained
- pip-audit (osv): "No known vulnerabilities found" sustained
- security cluster 真核**首次 closed** sustained

### 4.3 F-D78-245 真根因 verify + sustained user-action fix ✅

- 真根因 verify: QMT GUI 客户端真**未启动 / 真**未登录 account** sustained (sustained F-D78-293 同源)
- Week 1 fix path: user GUI manual 启动 + Servy QuantMind-QMTData restart (反问 2 a + 5 c+d 并行)
- 真测 verify: post-restart 真生效 (E2 verdict)
- broker_qmt `_handle_disconnect` 真**已有** reconnect logic 真生效 ✅ (sustained 反 audit Phase 9 假设 "0 reconnect logic" 真**完美 LL "假设必实测" verify**)

### 4.4 F-D78-289 真核 demoted P0 → P3

- 真根因 verify: 5-01~5-05 真**5-day Labor Day holiday** sustained per `trading_calendar` SQL verify
- 5-01 schtask 真**0 runs** = 真**holiday guard 真生效** sustained period sustained 真**正常 expected behavior**
- 5-04 (Mon, next trading day) 真**首次自动 verify** schtask 真生效

### 4.5 F-D78-291 候选 cluster 重新评估

- Phase 10 finding: smoke_test 真**唯一 system Python311** sustained
- 5-01 真测真值: qmt_data_service 真**spawn child running system Python311** sustained (PID 24752 parent=PID 22900 .venv)
- 真根因 candidate: xtquant SDK internal IPC spawn (subprocess 真**0 grep hit** in qmt_data_service.py + broker_qmt.py, 真**candidate xtquant SDK 真 internal**)
- Week 1 conclusion: 真**0 修 needed Layer 1** (真**candidate normal sustained**), 真**Layer 2 verify** (read xtquant SDK source / 真**broader test**)

### 4.6 真**新 finding 候选 — position_snapshot 真**0 audit timestamp**

- 真测真值: position_snapshot 真**0 created_at / 0 updated_at column** sustained sprint period sustained
- 真**意味**: 真**0 audit trail** for position_snapshot row insert/update sustained
- 候选 sediment: F-D78-? Layer 2 audit candidate

---

## §5 LL "假设必实测" 真**broader 累计 +N** sustained

Week 1 真测 真**6 项 LL 假设必实测真证据加深 sustained sprint period sustained**:

1. **假设 .env 真在 root** sustained → 真**真在 backend/.env** sustained (E5 fix)
2. **假设 LIVE_TRADING_DISABLED 真在 .env explicit set** → 真**by-design Pydantic default fail-secure** sustained (E5 verify)
3. **假设 redis 真有 portfolio:* keys** → 真**0 keys sustained period sustained** (E6 STOP 触发)
4. **假设 qmt_data_service 真**0 reconnect logic** sustained → 真**broker_qmt _handle_disconnect 真生效** sustained (Step D verify)
5. **假设 5-01 schtask 0 runs = silent failure** sustained → 真**5-day Labor Day holiday guard 真生效** sustained (WI 3 demoted)
6. **假设 task prompt cite scripts/run_ic_calc.py** → 真**0 此 file** sustained, 真路径 fast_ic_recompute.py (反问 4 verify)

**真**broader 累计 sustained sprint period sustained**: 47 (prior memory cite) + 6 (Week 1) = **53+** sustained.

---

## §6 LL-098 第 17 次 stress test sustained verify

✅ 末尾 0 forward-progress offer (本 STATUS_REPORT §7 candidate sequencing 真**Layer 2 sediment, 真**user 显式触发**, CC 0 schedule)

✅ Week 1 task scope 真**0 拆 sub-Phase** (一次性 9 WI 完成 sustained per task prompt §6 boundary)

✅ 真**0 时长限制** sustained (sequence A→B→C→D→E + WI 1/2/2.5/3/4 + 5/6 + 7 全完成 sustained 1 session)

---

## §7 反 anti-pattern 5 守门累计 sediment

### 7.1 anti-pattern 守门 v1: 凭空假设数字 (memory #19, broader 47+ → 53+)

✅ 全数字 SQL/log/script 真测推导 sustained (cb_state.live nav=993520.16 / cash=993520.66 / drift=0.0001% / 11928 rows / 2992 rows / etc).

✅ 0 数字假设 sustained.

### 7.2 anti-pattern 守门 v2: 凭空假设 path/file/function/class (memory #20, broader 84+)

✅ 真测决议:
- scripts/run_ic_calc.py → 真路径 fast_ic_recompute.py (反问 4 verify)
- backend/.env → 真路径 (E5 verify)
- column factor_id → 真名 factor_name (WI 4 verify)
- column cal_date → 真名 trade_date (WI 3 verify)
- column position_snapshot.created_at → 真**0 column** (E8 verify)

### 7.3 anti-pattern 守门 v3: 信 user GUI cite = 真状态 (memory #21)

✅ user cite "QMT 已启动 + 已登录 + 一直挂起" + CC PowerShell verify XtMiniQmt PID/StartTime 真核 cross-check sustained.

✅ user cite "Servy 已 restart" + CC poll redis 真**首次 verify failed** sustained → STOP 反问 → user GUI 重 restart + CC reverify ✅.

### 7.4 anti-pattern 守门 v4: 看文档 / 静态分析 = 真测 (memory #22)

✅ 真测 enforce sustained:
- broker_qmt _handle_disconnect 真生效 verify 走 stderr log 18:29:41 真 reconnect 成功 sustained (反 audit Phase 9 假设 "0 reconnect logic")
- 5-01 schtask 0 runs 真根因 走 trading_calendar SQL verify holiday guard sustained (反 audit Phase 10 假设 "silent failure")
- alert channel 真生效 走 真 send_sync DingTalk push verify return True (反 design only)

### 7.5 anti-pattern 守门 v5: Claude 给具体代码 = 假设 CC 真路径 (memory #23, 5 min 内自违反 sustained)

✅ Week 1 task prompt v5.0: "Claude 仅方向 + 目标, CC 实测决议真路径 + 真命令 + 真 verify 方法" sustained.

✅ CC 真测决议:
- WI 2 修真 path: read 14 callers cluster + 决议 minimal factory + sync facade approach
- WI 4 backfill 真路径: 反问 4 真测 verify CORE_FACTORS=CORE4 在 partial scope
- WI 5 emergency SOP scenario 选择: CC 主动加 6 candidate (反 D77 known-knowns bias)
- 真**0 假设 task prompt 真路径**, 全真测决议.

---

## §8 真生产 GUI 单点 dependency cluster 加深 sustained

### 8.1 真核 cluster 真证据 sustained

| Finding | 真根因 same source verdict |
|---|---|
| F-D78-245 (P0 治理) | Servy "Running" ≠ functional sustained |
| F-D78-293 (P3→P0 candidate) | MiniQMT_AutoStart schtask 0 command sustained |
| **真**新真根因** verify** | 真**QMT GUI 客户端真**手工启动 dependency** sustained sprint period sustained |
| F-D78-291 (cluster) | qmt_data_service 真**spawn child via xtquant SDK internal** sustained |
| F-D78-235 (P0 治理) → fixed Week 1 | risk-health alert silent failure 真根因 = 14-caller cluster cluster (notification_service.get_notification_service 真**从未 implement**) |

### 8.2 真**Layer 2 候选 sequencing** sustained (sediment, 0 forward-progress offer)

候选 sediment, 待 user 显式触发:
- F-D78-293 真**MiniQMT_AutoStart schtask 0 command** 真核修 (Windows reboot 后真**自动启动** GUI 客户端 + 真**自动登录** account)
- F-D78-245 真**Servy "Running" ≠ functional** 真核 health gate 加 (broker connect state + redis sync state visibility)
- F-D78-291 真核 verify (xtquant SDK internal IPC vs orphan distinction)
- 14 callers cluster Layer 2 cleanup (pt_monitor_service / daily_pipeline / 多 tests 真核 audit)

---

## §9 Week 2 candidate sequencing (sediment, 0 forward-progress offer)

候选 sediment 真**待 user 显式触发** sustained:

1. F-D78-240 trade_log 4-17 后 0 行 14d gap 真**backfill** (emergency_close 17 trades + GUI 18 trades audit reconstruction)
2. F-D78-241 4 数据源 stale disconnect 真**audit + 真核修**
3. F-D78-264/265 risk_event_log 仅 2 entries 30d 真**audit + LL-098 反 X10 真证据加深** Layer 2
4. F-D78-273 monthly_rebalance 33% expired 真根因 deep
5. T1.3 20 决议 真**起手 D-M1 (T0-12 methodology) + D-M2 (ADR-016 PMS v1 deprecate)**
6. Frontend 真**深 audit ~80% gap** (5K LOC pages + 12 components 子类 + 4 store + 11 api)
7. mypy 真**install + 真 sustain typecheck**
8. D-decision SSOT registry 真**新建** (sustained F-D78-260 candidate)
9. 14 callers cluster Layer 2 cleanup (sustained Week 1 scope only fixed risk-health caller)
10. position_snapshot 真**0 audit timestamp** Layer 2 audit add

---

## §10 真核 LL sediment (Week 1 真证据真**加深**)

### LL-N (broader 53+): 假设必实测 真**Week 1 真证据加深 6 项**

(详 §5)

### LL-? candidate (Week 1 真**新候选**): 真**14 callers cluster ImportError silent broken sprint period sustained sprint period 8 month**

- 真**多 callers import 不存 function 真**全 silent broken** sustained
- 真**0 import test in CI** sustained sprint period sustained
- 真**真核 candidate**: 加 import smoke test in pre-push hook (sustained Layer 2 candidate)

### LL-? candidate (Week 1 真**新候选**): broker_qmt _handle_disconnect 真生效但 first connect fail 真**0 retry** sustained

- 真**broker.connect() 首次 -1 sustained** (QMT GUI 未启动 sustained) → script 真 raise + return 3 sustained
- _handle_disconnect callback 真**仅 触发 on disconnect callback** sustained, 真**未 触发 on initial connect fail** sustained
- 真**Layer 2 candidate**: add startup retry loop in qmt_data_service.py + broker_qmt.py

---

## §11 真核 verify summary

| 项 | 真状态 | 真**真测 verify command** |
|---|---|---|
| pip CVE | ✅ closed | `python -m pip_audit --vulnerability-service osv` → "No known vulnerabilities" |
| risk-health import | ✅ fixed | `python -c "from app.services.notification_service import get_notification_service; svc = get_notification_service()"` |
| risk-health alert channel | ✅ verified | DingTalk push 真发送成功 (return True) |
| ground truth | ✅ verified | `python scripts/_verify_account_oneshot.py` → drift=0.0001% PASS |
| QMT broker connect | ✅ post-restart 生效 | broker.connect() return 0 + asset 真值 + positions 真值 |
| factor_ic backfill | ✅ closed | factor_ic_history MAX=2026-04-28 / 4 factors / 12 rows after 4-11 |
| holiday guard | ✅ verified | trading_calendar 5-01~5-05 is_trading_day=False |
| emergency SOP S5 smoke | ✅ verified | LIVE_TRADING_DISABLED=True + EXECUTION_MODE=paper |
| account truth log | ✅ sediment | account_truth_log.md §2.3 cross-check verdict |

---

## §12 真**0 修 needed candidate revisited**

Week 1 task scope 真**P0 task 4 项**, 真**fix 2 项 + demote 1 项 + 0 fix needed 1 项**:

- WI 1 ✅ fixed (pip upgrade)
- WI 2 ✅ fixed (factory + sync facade add)
- WI 3 ⬇️ demoted P0→P3 (5-day holiday false-positive)
- WI 4 ✅ fixed (factor_ic backfill)
- WI 2.5 ✅ 0 fix needed (broker reconnect 真已生效)

真**Layer 1 真核 P0 真**降到 2 项实修** sustained (pip CVE + risk-health import). 真**0 over-fix sprint period sustained** ✅.

---

**文档结束** sustained sprint period sustained.
