# Wave 2 Synthesis Template (Coordinator-Maintained)

**Trigger**: /goal 5-20 — 协调 5 Wave 1 agents 综合审计
**Status**: 🟡 Wave 1 agents running, awaiting completion
**Sediment timestamp**: 2026-05-20 ~early SH

---

## §1 Wave 1 Agent Outputs (To Be Filled)

### Agent A: Code Health (铁律 31/32/33 + dead code + magic)
- agentId: a1e2dd3e9649fb427
- Expected: P0 silent failure / engine impurity / service commit violations + 死代码候选 + magic numbers
- Output: _pending_

### Agent B: Security (secrets / SQL / API auth / broker bypass / 红线)
- agentId: a971d51ccdbedb836
- Expected: CRITICAL/HIGH findings + 5/5 红线 sustained verdict + Phase B-1 frozen breach paths
- Output: _pending_

### Agent C: Documentation Drift (CLAUDE.md numeric vs reality)
- agentId: a54d0e3ee7a13244b
- Expected: 数字漂移 (factor count / ADR count / LL count / 测试 baseline) + archive candidates
- Output: _pending_

### Agent D: Business Closed-Loop (6 流 trace)
- agentId: ac14e86364d01107a
- Expected: 6 流闭环度 + cross-flow risks (e.g. AlertDispatcher flush trigger wire)
- Output: _pending_

### Agent E: Test Coverage + Stability (pytest --co + 铁律 10b/40)
- agentId: a3c77f1d536bd9bca
- Expected: baseline 真值 + critical path coverage gaps + xfail/skip 累积 + regression baseline status
- Output: _pending_

---

## §2 Cross-Reference to Known Catalog (ISSUES_PENDING_REGISTRY_2026_05_19.md)

### Already-closed (don't re-spawn fix agents):
- S1 admin_token httpOnly: ✅ ae4b70d
- F1 LLM cost forward fix: ✅ 23ebea5
- F3 VACUUM schtask: ✅ 15a7d93 (script ready, 留 user register)
- A4 AgentConfig PUT: ✅ 506a2cf
- A5/C4/H4 Calendar wire: ✅ df79ec4
- D1 DB 4-28 stale: ✅ b644ad1
- G1 8 DEV docs: ✅ be0a6de
- H1 silent UI lie: ✅ b644ad1
- L2/L3/A3 frontend: ✅ 9ecd588
- L8 Memory archive: ✅ 15a7d93
- C2 silent failure 4 annotations: ✅ 9ecd588
- P4 SSE endpoint: ✅ be00471
- P7 audit middleware: ✅ be00471
- P2 prompt_history: ✅ 506a2cf
- P8 dead tables: ✅ ADR-083 KEEP
- P9 LLM cache-hit: ✅ 6d51a77

### Open (user touchpoint, can't autonomous fix):
- S2 PG password rotation (playbook ready)
- F2 BGE-M3 embedding cron (GPU + ~4h cron)
- B1-B4 Phase J multi-week research
- C1 single point of failure (Phase J)
- C2 silent NOT-GATING audit-wide enforce (partial)
- 4 schtask register pending (Beat heartbeat, Schtask freshness, Market watcher, Servy log rotate)

### Defer Phase J post 5-27 (Phase B-2):
- P0-4 Reflector→ThresholdEngine wire (design ready)
- P0-17 Disaster drill scenarios (design ready)
- P0-21 Live trade reproducibility (multi-week)

---

## §3 Triage Rules (Wave 2 Decision Tree)

For each Wave 1 finding:

**Step 1 — Catalog cross-check**:
- Already in §2 closed list? → SKIP (false positive surface)
- Already in §2 user touchpoint? → ESCALATE only
- Already in §2 Phase J defer? → SUSTAIN per design doc, no new action

**Step 2 — 红线 risk check**:
- Touches broker / .env / schtask register / DB row? → ESCALATE only, NO autonomous fix
- Pure code refactor (no runtime mutation)? → Wave 3 fix-agent

**Step 3 — Phase B-1 frozen check**:
- Modifying production code path? → Defer to Phase B-2 post 5-27
- Pure test / doc / dead code cleanup? → Wave 3 fix-agent immediate

**Step 4 — Effort check**:
- ≤ 30min fix? → Wave 3 immediate
- 30min-2h? → Wave 3 batch (multiple agents)
- > 2h? → sediment to Phase J design doc, no fix

---

## §4 Wave 3 Dispatch Slots (To Be Filled)

| Slot | Finding | Source agent | Effort | Agent type |
|---|---|---|---|---|
| 1 | _pending_ | A/B/C/D/E | XXmin | executor |
| ... | | | | |

---

## §5 Wave 4 Verify Checklist (To Be Run After Wave 3)

- [ ] pytest --co exit=0 (no new collection error)
- [ ] pytest critical path tests pass (test_realtime_alert + test_l4_execution_planner + test_dry_run_no_broker_call + test_smoke)
- [ ] 5/5 红线 verify cite (4 .env field + 1 default)
- [ ] git status clean (no orphan changes)
- [ ] STATUS_REPORT sediment
- [ ] Memory handoff prepend

---

**Coordinator Note**: This template fills as agents return. Final synthesis will replace `_pending_` placeholders with structured findings + dispatch plan.
