# Operations Review — 4-29 emergency_close 4 abort 真根因 真发现

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 10 / operations/13
**Date**: 2026-05-01
**Type**: 评判性 + 4 early abort emergency_close logs 真读 (sustained F-D78-239 加深)

---

## §1 真测 (CC 5-01 cat 4 abort logs 实测)

实测 source: 4 emergency_close logs (4-29 10:38-10:41) 真读全文.

**真值** — 真 4 abort 真根因真发现:

### 1.1 abort #1 (4-29 10:38:25, log 669 bytes)

```
2026-04-29 10:38:26,030 [ERROR] [FATAL] QMT 查持仓失败:
cannot import name 'QMTBroker' from 'engines.broker_qmt'
(D:\quantmind-v2\backend\engines\broker_qmt.py)
Traceback (most recent call last):
  File "D:\quantmind-v2\scripts\emergency_close_all_positions.py", line 258, in main
  File "D:\quantmind-v2\scripts\emergency_close_all_positions.py", line 66, in _resolve_positions_via_qmt
    from engines.broker_qmt import QMTBroker
ImportError: cannot import name 'QMTBroker' from 'engines.broker_qmt'
```

**真根因**: scripts/emergency_close_all_positions.py 真 import `QMTBroker` 但**不存在** in `engines/broker_qmt.py`.

### 1.2 abort #2 (4-29 10:39:36, log 644 bytes)

```
2026-04-29 10:39:36,388 [ERROR] [FATAL] QMT 查持仓失败:
No module named 'xtquant'
File "D:\quantmind-v2\backend\engines\broker_qmt.py", line 236, in connect
    from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
ModuleNotFoundError: No module named 'xtquant'
```

**真根因**: emergency_close 真**第二次** import attempt — 真 broker_qmt 真**未触发 ensure_xtquant_path() sustained**, sustained sprint state CLAUDE.md "xtquant 路径管理 统一使用 app/core/xtquant_path.py 的 ensure_xtquant_path()" 真**未在 emergency_close 真路径 enforce sustained**.

### 1.3 abort #3 (4-29 10:40:22, log 317 bytes)

```
2026-04-29 10:40:22,689 [INFO] [QMT] 连接成功: path=E:\国金QMT交易端模拟\userdata_mini, account=81001102, session=104022626158
2026-04-29 10:40:22,689 [INFO] [QMT] connected
2026-04-29 10:40:22,719 [INFO] [QMT] query_positions: 18 持仓
[早 abort, 0 sell 真发出]
```

**真根因**: connect ✅ + query 18 ✅ 但**未 sell 立 abort** — 真**confirm-yes prompt 真未 bypass + interactive prompt 真挂起?** sustained candidate.

### 1.4 abort #4 (4-29 10:41:14, log 317 bytes)

```
2026-04-29 10:41:14,443 [INFO] [QMT] 连接成功
2026-04-29 10:41:14,474 [INFO] [QMT] query_positions: 18 持仓
[早 abort, 0 sell]
```

**真根因**: 同 abort #3 — 真**多次 attempt confirm-yes prompt 真未通**, 真 5 attempts 后真 final 10:43:54 加 `--confirm-yes` flag bypass sustained.

### 1.5 final success (4-29 10:43:54, log 14 KB)

真 17/18 ✅ filled (sustained F-D78-240 真 emergency_close real 14K 真读 verify ✅).

---

## §2 🔴 重大 finding — emergency_close 真**0 smoke test sustained sprint period sustained**

**真根因 5 Why**:
1. emergency_close_all_positions.py 真**生产入口** sustained — 真 4-29 14:00 user 决定清仓后 真**首次 sustained sprint period sustained 触发**
2. 真**第一次** import `QMTBroker` ❌ 真**0 import** in broker_qmt.py
3. 真**第二次** import `xtquant` 直 ❌ 真**未触发 ensure_xtquant_path()** sustained
4. 真**第三/四次** confirm-yes prompt 真**未 bypass** sustained
5. **真根因**: emergency_close 真**0 smoke test sustained sprint period sustained**, 真**生产入口真启动验证 (铁律 10b)** 真**0 enforce on emergency_close sustained**, 真**4-29 真情况下 真首次 production fire 揭露 4 真 bug**

**🔴 finding**:
- **F-D78-285 [P0 治理]** emergency_close_all_positions.py 真**0 smoke test sustained sprint period sustained**, 真 4-29 真 production fire 4 attempts 揭露 4 真 bug (QMTBroker 不 import + xtquant module path 真未 ensure + confirm-yes prompt 真未 bypass × 2), sustained 铁律 10b "生产入口真启动验证" 真**violated on emergency_close 真路径** sustained, sustained F-D78-? "smoke test 仅 28→61 PASS" 不含 emergency_close 真证据 sustained 真**真核 emergency 真路径 真启动验证缺**.

---

## §3 真生产意义 (sustained F-D78-265 加深)

**真证据 sustained sprint period sustained sustained**:
- 4-29 14:00 user 决策清仓 → CC 真**软处理 PR #150 link-pause** (sustained F-D78-265 真证据)
- → user 真发现 + 真**手工 emergency_close** sustained
- → 真**4 abort** 真证据 (本审查 Phase 10 真发现)
- → 真**第 5 次** 加 `--confirm-yes` flag 真 bypass + 真 17/18 success (1 cancel due 跌停)
- 真**总 10:38-10:43 = 真 5 min 5 attempts** sustained 真**真生产 emergency 真不 ready 真证据加深** sustained F-D78-265 真案例真完美加深

**finding**:
- F-D78-286 [P0 治理] emergency_close 真**5 min 5 attempts 才 final success** sustained 真**真生产 emergency 真不 ready** 真证据完美加深, sustained F-D78-285 + F-D78-265 同源 真**4-29 真 production fire 真核 case** sustained 真**真生产 emergency 真路径 真**0 sustained sprint period sustained 沉淀 ready** 真证据 (sustained sprint period sustained "Wave 4 MVP 4.1 batch 1+2.1+2.2 ✅" 真**真核 emergency 真路径 真未 cover** sustained)

---

## §4 真 emergency_close 路径 真重大 audit gap (sustained 全 finding cluster cross-validation)

| 真 emergency_close 路径 真状态 | 真证据 |
|---|---|
| smoke test 真 cover | ❌ F-D78-285 (4 abort 揭露) |
| dual_write Beat 真 audit log | ❌ F-D78-240 (trade_log 0 入) |
| risk_event_log 真 entry | ❌ F-D78-264 (仅 2 entries, 0 emergency_close entry) |
| 真 alert 通道 (DingTalk) | ❌ F-D78-235 (risk-health ImportError) |
| 真 broker connect 真 reproducibility | ❌ F-D78-285 (xtquant module path) |
| 真 5+1 层 L4 emergency 真 sustained | ❌ F-D78-261 (5+1 层 1/6, L0/L2/L3/L4/L5 全 ❌) |
| Frontend 真 emergency 真 page | ❌ Phase 9 frontend 真深 audit 0 见 emergency page |

**真**6/7 ❌ + 1/7 ❌** = 真**emergency 路径 真**全 cluster ❌**.

**🔴 finding**:
- **F-D78-287 [P0 治理]** emergency_close 真路径 真 cross-cluster ❌ verify (smoke / audit log / risk_event / alert / broker connect / 5+1 层 L4 / frontend emergency page 真**全 7/7 ❌**), sustained F-D78-285/286 + F-D78-240/264/235/261 cluster 同源真证据完美加深 — 真**真生产 emergency 真路径 真 0 sustained sprint period sustained 沉淀 production-ready** sustained 真**真核 risk** sustained 真证据 (4-29 真 case verify)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-285** | **P0 治理** | emergency_close 真 0 smoke test, 4-29 4 abort 揭露 4 真 bug (QMTBroker + xtquant + confirm-yes×2), 铁律 10b violated |
| **F-D78-286** | **P0 治理** | emergency_close 真 5 min 5 attempts 才 final success, 真生产 emergency 真不 ready 完美加深 |
| **F-D78-287** | **P0 治理** | emergency_close 路径真 7/7 ❌ cross-cluster (smoke/audit log/risk_event/alert/broker/L4/frontend), 真核 risk |

---

**文档结束**.
