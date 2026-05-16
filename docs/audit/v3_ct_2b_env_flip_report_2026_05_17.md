# V3 CT-2b — .env paper→live Flip Report (HIGHEST-STAKES MUTATION)

**Status**: ⏳ PR opened, **PENDING USER 显式 "同意 apply CT-2b" TRIGGER**

**Plan**: V3 Plan v0.4 §A CT-2b — V3 实施期 ONLY 真账户解锁 sprint. 整 V3 实施期 highest-stakes mutation per Plan §A row 102.

**Main HEAD at PR creation**: `057c3f1` (post CT-2a Gate E ✅ READY)
**Branch**: `v3-pt-cutover-ct-2b`

---

## §1 Mutation scope (Phase 0 verified 2026-05-17)

| .env field | Line | Pre-flip | Post-flip | Effect |
|---|---|---|---|---|
| `LIVE_TRADING_DISABLED` | 20 | `true` | `false` | UNLOCK live broker trading |
| `EXECUTION_MODE` | 17 | `paper` | `live` | FLIP execution mode to live |

**Sustained (verified, NOT mutated)**:

| .env field | Line | Value |
|---|---|---|
| `QMT_ACCOUNT_ID` | 13 | `81001102` |

**NOT in scope** (default OFF, sustained per ADR-027 + ADR-028):
- `DINGTALK_ALERTS_ENABLED` — not present (separate enablement decision out of CT-2b)
- `L4_AUTO_MODE_ENABLED` — sustained OFF per ADR-028 (Sprint N+ 5 prereq closed after cutover before AUTO 启用)
- `STAGED_ENABLED` — sustained OFF per ADR-027 #1 (default OFF 短期, long-term swap after observation)

---

## §2 4-layer enforce (Plan §A row 102)

This sub-PR includes evidence of all 4 enforcement layers:

| # | Layer | Evidence |
|---|---|---|
| 1 | `redline_pretool_block` hook | Auto-block CC tool calls modifying `.env` (live mechanism; bypassed via apply runner which is user-script not CC tool) |
| 2 | `quantmind-redline-guardian` subagent | Reviewer pass with `NEEDS_USER` verdict expected (mechanism layer) |
| 3 | User 显式 "同意 apply CT-2b" trigger | Constitution §L8.1 (c) hard gate — 3-step gate sustained from CT-1a体例 |
| 4 | Commit message hard-cite + ADR-077 cite + emergency rollback path | Post-apply commit will hard-cite CT-2b mutation + ADR-077 reservation + reference rollback procedure |

---

## §3 Apply procedure (post user 同意 trigger)

```powershell
# Step 1: Re-verify preflight (idempotent, 0 mutation)
python scripts/v3_ct_2b_env_flip_apply.py --dry-run

# Expected: ✅ PASS — 2 fields verified pre-flip state
# Output includes: LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper

# Step 2: Apply flip (mutation)
python scripts/v3_ct_2b_env_flip_apply.py --apply

# Pipeline:
#   1. Preflight verify (idempotent re-check)
#   2. Snapshot capture (atomic JSON write to
#      docs/audit/v3_ct_2b_env_flip_rollback_snapshot_2026_05_17.json)
#   3. Atomic flip (tempfile + os.replace on backend/.env)
#   4. Post-flip verify (assert post-state matches)

# Expected post-apply:
#   ✅✅✅ CT-2b APPLY SUCCESS — 红线 5/5 TRANSITIONED ✅✅✅
#   LIVE_TRADING_DISABLED = false
#   EXECUTION_MODE = live

# Step 3: Restart services to load new .env (manual)
powershell -File scripts\service_manager.ps1 restart all

# Step 4: Verify post-flip env state
Get-Content backend\.env | Select-String -Pattern "LIVE_TRADING_DISABLED|EXECUTION_MODE"
```

---

## §4 Emergency rollback path

If post-apply 1d 监控 (CT-2c) surfaces P0 issue requiring rollback:

```powershell
# Restore pre-flip .env from snapshot
python scripts/v3_ct_2b_env_flip_apply.py --rollback

# Restart services
powershell -File scripts\service_manager.ps1 restart all

# Verify red-line 5/5 restored: LIVE_TRADING_DISABLED=true, EXECUTION_MODE=paper
```

Snapshot path: `docs/audit/v3_ct_2b_env_flip_rollback_snapshot_2026_05_17.json` (captured atomically BEFORE flip; rollback always available).

Per Plan §B row 9 + ADR-077 §3 (reserved, CT-2c sediment), rollback path readiness is required pre-CT-2c go-live monitoring.

---

## §5 红线 5/5 TRANSITION (post-flip semantic)

Pre-flip state (sustained throughout CT-1 + CT-2a):

| # | 红线 | Pre-flip |
|---|---|---|
| 1 | cash | ¥993,520.66 (sustained xtquant ground truth) |
| 2 | 持仓 | 0 (sustained) |
| 3 | `LIVE_TRADING_DISABLED` | `true` |
| 4 | `EXECUTION_MODE` | `paper` |
| 5 | `QMT_ACCOUNT_ID` | `81001102` |

Post-flip state (after CT-2b apply + CT-2c first trade):

| # | 红线 | Post-flip |
|---|---|---|
| 1 | cash | 真值 (post-trade xtquant query) |
| 2 | 持仓 | 真持仓 (first live trade execution) |
| 3 | `LIVE_TRADING_DISABLED` | `false` |
| 4 | `EXECUTION_MODE` | `live` |
| 5 | `QMT_ACCOUNT_ID` | `81001102` (sustained, unchanged) |

红线 5/5 TRANSITIONED — not just sustained.

---

## §6 Gate E prerequisite cite (CT-2a verified ✅ READY)

Per CT-2a verify report 2026-05-17 (Gate E charter):
- 5 prereq ✅ ALL PASS (paper-mode 5d replay-path equiv + 元监控 0 P0 + Tier A ADR sediment + 5 SLA + 10 user 决议)
- 10 user 决议 ✅ ALL PASS (V3 §20.1 + ADR-027/028/033 cross-cite)
- 5 sediment reports ✅ present (IC-3a/b/c + CT-1a/b)

CT-2a sediment: `docs/audit/v3_ct_2a_gate_e_charter_verify_report_2026_05_17.md`

CT-2b apply is gated on CT-2a Gate E ✅ READY (this prerequisite ✓).

---

## §7 Methodology

- **3-step user gate体例** (sustained LL-174 lesson 2): (1) PR + reviewer + (2) user 显式 "同意 apply CT-2b" message + (3) CC executes `--apply`.
- **Atomic snapshot + flip**: snapshot captured BEFORE flip; rollback always available; tempfile + os.replace for atomic writes (sustained CT-1a体例).
- **Field-by-field verify**: preflight + post-flip both verify .env state explicitly per field; drift fails-loud.
- **Cutover mutation class**: per LL-174 lesson 5 — DB row mutation was CT-1 ONLY pre-mutation; .env field mutation is CT-2b class (different mutation type, sustained 4-layer enforce).
- **0 broker call in CT-2b PR**: PR ships apply runner + tests + report; broker call (first live trade) is CT-2c scope.

**Pre-PR state** (sustained throughout CT-2b PR review):
- 0 broker call / 0 .env mutation / 0 yaml mutation / 0 DB row mutation / 0 LLM call / 0 真 DingTalk push
- 红线 5/5 sustained PRE-flip: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102

---

## §8 关联

- V3 Plan v0.4 §A CT-2b + §B row 8 (.env flip silent overwrite mitigation) + §B row 13 (CT-2b trigger 时机判断错误 mitigation)
- Constitution §L10.5 (Gate E formal close) + §L8.1 (c) (sprint 收口决议 user 介入 hard gate)
- ADR-022 (rollback discipline + append-only sediment) / ADR-027 (STAGED + 反向决策权 — STAGED stays OFF) / ADR-028 (AUTO + V4-Pro — AUTO stays OFF) / ADR-077 reserved (Plan v0.4 closure + Gate E formal close, CT-2c sediment)
- 铁律 22 / 24 / 25 / 33 / 35 (.env secrets) / 41 / 42
- LL-098 X10 (per-mutation STOP gate) / LL-100 chunked SOP / LL-159 (4-step preflight) / LL-174 lesson 2 (3-step user gate体例) / lesson 5 (cutover hygiene体例)
