# L4R Loop Spec v9.7 Addendum — Stop-Pattern Anti-Patterns Closure

> **创建**: 2026-05-26 (iter 130-149 continuation session sediment-driven)
> **基线**: L4R_LOOP_SPEC.md v9.6 + 此 addendum
> **触发**: 2026-05-26 session 用户 3 次显式 frustration ("为什么又停止了" × 3) — pattern observed: CC hits genuine spec-defined STOP triggers (§6 carve-out / ops blocker / reviewer COMMENT / "exhaustion" perception) and incorrectly converts them to "wait for user redirect" instead of "pivot to next iter-friendly Tier work".
> **状态**: addendum sediment. user paste v9.7 短 `/goal` 时点指向本 doc + base spec。

---

## §v9.54 (NEW) Reviewer COMMENT verdict 同 iter fix-flow MANDATORY

**Anti-pattern observed (iter 137 + iter 147)**: PR reviewer returns COMMENT verdict (no REQUEST_CHANGES, but has MEDIUM/LOW findings). CC interpreted as "no action required, COMMENT means optional" → PR merged without addressing findings.

**Fix**: Treat COMMENT verdict ≥ MEDIUM findings as **same-iter mandatory fix-flow** (sustained §v9.39 pattern):
1. Apply each MEDIUM finding fix immediately (no halt for "should I fix?")
2. LOW findings: apply if ≤ 5 LOC + no scope creep; else explicit DEFER cite in commit msg
3. Re-test (vitest + tsc + ruff)
4. Push to same PR (or follow-up PR if PR already merged before fix attempt)
5. Re-spawn reviewer ONLY if APPROVE not reached; else AI self-merge

**Real signal**: APPROVE = AI self-merge fast-path. COMMENT with findings = same-iter fix-flow. REQUEST_CHANGES = same-iter fix-flow + cycle 2 reviewer.

---

## §v9.55 (NEW) Deploy gap discovered → same-iter remediation, NOT user-redirect

**Anti-pattern observed (iter 142+143 Servy restart + iter 146 daily_attribution missing)**: CC discovered DB table missing OR Celery worker stale, then halted to ask user "should I run migration / restart Servy?"

**Fix**: Deploy gap discovered → categorize + execute autonomously where safe:

| Gap type | Autonomous action | Authorization needed |
|---|---|---|
| **Idempotent migration** (`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN IF NOT EXISTS` / index creation) | **Apply via psql immediately**, no halt | NO (idempotent + low-risk) |
| **Destructive DDL** (DROP TABLE / TRUNCATE / DELETE FROM / ALTER TABLE DROP COLUMN) | Document in audit doc + DEFER-with-cite | YES (require user explicit OK) |
| **Service restart** (Servy / sc.exe `stop` / `start`) | Attempt via Servy CLI; if Access Denied → document blocker + pivot to next iter (NEVER halt for elevated shell) | NO for attempt; YES for force-kill python.exe |
| **.env mutation** | NEVER autonomous | YES (red-line + §6 carve-out) |
| **Broker write / live trading** | NEVER autonomous | YES + paper-mode verify + 5-day dry-run |

**Real signal**: idempotent migrations sa fe — just apply. Destructive ops + service restart need surface-but-pivot pattern, NOT halt.

---

## §v9.56 (NEW) Backlog exhaustion ≠ session end (§v9.46 14-source pivot mandate)

**Anti-pattern observed (iter 148 + iter 149 wrap)**: CC perceived "W2-F 9/10 closed + F9 DEFER + Phase J multi-week + research lanes need user-direction = nothing iter-friendly left" → "awaiting redirect".

**Fix**: Sequential Tier pivot per §v9.47 (sustained from v9.6 spec):

1. **Tier A§2 done** → pivot Tier A§1 Phase J (even if multi-week, split into 1-iter sub-tasks: e.g., "read PHASE_J_DEFER_MANIFEST §1.1 + write decomposition design doc" is a valid iter)
2. **Tier A done** → pivot Tier B Wave 5 MVP design (even without user requirements: research existing patterns + propose ≤2 页 MVP design doc per 铁律 24 + ADR-DRAFT row)
3. **Tier B done** → pivot Tier C/D research (read research-kb + propose next research direction with cite)
4. **Tier C/D done** → pivot meta-work: refactor / cleanup / LL sediment / digest cadence
5. **ALL Tier done** → pivot Audit Week N+1 manifest (new audit cycle opens)

**Real signal**: There's ALWAYS iter-friendly autonomous work available. "Exhaustion" perception = look harder at the 14 backlog sources (§v9.46) + 5-tier pivot ladder above.

**Forbidden**: writing "awaiting redirect" / "session complete" / "outstanding actions requiring user" at end of iter unless §6 carve-out genuinely triggered (NOT for ops blocker which has pivot path per §v9.55).

---

## §v9.57 (NEW) Ops blocker (Servy / sc.exe Access Denied) handling SOP

**Anti-pattern observed (iter 142+143)**: CC attempted Servy restart, got "Failed to restart service" + "OpenService FAILED 5: Access is denied", responded by halting to ask user for elevated shell.

**Fix**: When ops command fails with permission / access denied:

1. **Document the blocker** in audit doc (sibling iter 143 W2_A_RUNTIME_REVERIFY pattern: §2 attempt narrative + §3 resolution options for user)
2. **Pivot to non-blocked work in same iter** — backend-only ship status preserved per §v9.48 honest progress 三态; iter doesn't halt
3. **NEVER write "user action required"** as iter ending — that violates §v9.56 + v9.6 § 0 真自主硬性条款

**Real signal**: Ops blocker = note + move on. Service restart attempt failure = autonomous work continues on Celery-restart-independent surfaces (frontend / docs / read-only audit / migration that's already-deployed).

---

## §v9.58 (NEW) Migration apply autonomy gate

**New formalization** (extracted from iter 146 daily_attribution.sql apply):

Migration files in `backend/migrations/<name>.sql` paired with `<name>_rollback.sql`. Autonomy gate:

- **APPLY freely** (no user authorization): if migration ONLY contains `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / `CREATE OR REPLACE FUNCTION` / `ALTER TABLE ADD COLUMN IF NOT EXISTS` / `INSERT ... ON CONFLICT DO NOTHING` — all idempotent additive operations.
- **DEFER user authorization**: if migration contains `DROP` / `ALTER ... DROP` / `DELETE` / `TRUNCATE` / `ALTER ... TYPE` (destructive or schema-mutation).

**Verification before apply**: grep migration file for forbidden keywords (`DROP|TRUNCATE|DELETE|ALTER.*DROP|ALTER.*TYPE`). If clean, apply via `psql -f <migration>` immediately.

**Sediment**: iter 146 daily_attribution.sql was idempotent CREATE TABLE IF NOT EXISTS + CREATE INDEX → safe autonomous apply. Reality re-grounding § 4.2 mandate satisfied.

---

## §v9.59 (NEW) Concurrent session race handling SOP

**Anti-pattern observed (iter 136 + iter 137 + iter 141)**: Another CC session (parallel/) made commits on the same branch simultaneously. CC observed: my Write/Edit no-op'd / branch ref shifted / push rejected non-fast-forward / orphaned commits.

**Fix**: Before every commit/push, autonomously execute:

1. `git reflog -N` — verify HEAD@{0..3} reflects current session intent (not branch-swap by parallel)
2. `git branch --show-current` — confirm expected branch immediately before commit
3. `git fetch origin && git log origin/<branch> --oneline -3` — check remote vs local for parallel commits
4. **If parallel beat me**: 
   - Pull-rebase (`git pull --rebase origin <branch>`)
   - Re-verify diff still applicable (parallel may have shipped same work)
   - If parallel duplicate: delete my local file/edits + acknowledge in next iter's audit doc
   - If complementary: proceed with rebased commit
5. **If branch-swap happened**: re-create my intended branch from main, cherry-pick my orphaned commits from reflog
6. **Force-push**: ONLY `--force-with-lease`, NEVER `--force`

**Sediment**: This pattern is now sustained anti-pattern across 3 iter-races this session. Memory anchor [[feedback_concurrent_process_git_safety]] reinforced; LL-XXX candidate for project-level sediment.

---

## §v9.60 (NEW) Session digest cadence — SCHEDULED iter, NOT session-end signal

**Anti-pattern observed (iter 141)**: CC wrote SESSION_SUMMARY iter 130-140 doc as if session-ending, then continued for 9 more iters. The digest write became a signal that "session is wrapping" which then justified later halt.

**Fix**: Digest writes are SCHEDULED at:
- Every ~10 iter (e.g., 130, 140, 150, ...)
- Pre-compaction (per §v9.26 SOP)
- Cross-session resume opener

Digest writing is **just another iter** — NOT a session-end signal. Continue iter N+1 immediately after digest commit, no narrative wind-down.

**Real signal**: digest doc commit msg ends with "next iter direction:" — this is a continuation cue, not an off-ramp. The directional candidates listed there ARE the next iter selection menu, not user redirect prompts.

---

## §v9.61 (NEW) End-of-turn output ≤ 1 sentence

**Anti-pattern observed (multiple iter wraps)**: CC wrote multi-paragraph summaries with 5+ bullet points at iter close ("Accomplishments / Outstanding actions / 红线 sustained / Awaiting redirect"). This pattern:
- Generated context-pressure (~500 tokens per wrap)
- Cued user to respond when no response needed
- Triggered "awaiting redirect" framing

**Fix**: At iter close, output ≤ 1 sentence stating next iter scope. Examples:
- ✅ "iter N closed (PR #XXX merged), iter N+1 = F4 Observability dashboard."
- ✅ "iter N digest sediment committed, iter N+1 = W2-D factor_values audit."
- ❌ "Continuation session iter 130-149 complete. **Accomplishments**: [5 bullets]. **Outstanding actions**: [5 bullets]. Awaiting redirect."

**Allowed exceptions**: 
- Genuine §6 carve-out triggered (≤ 3 sentences explaining trigger)
- User has explicitly asked for status update mid-session
- Pre-compaction digest doc commit (where digest doc itself has the detail)

---

## §v9.62 (NEW) "5 outstanding actions requiring user" framing BANNED

**Anti-pattern observed (multiple iter wraps this session)**: CC accumulated "5 outstanding actions requiring user authorization" list and presented at iter close. This converts iter close into a roadblock UI.

**Fix**: Outstanding actions go to:
- Audit doc §"resolution options for user" section (sibling iter 143 W2_A_RUNTIME_REVERIFY pattern) — persistent sediment
- L4R_LOOP_STATE.md "Current" section — pickup signal for next session
- NEVER iter-close inline output

Iter close output cites the audit doc by path, not the list. User can read at their pace.

---

## §v9.63 (NEW) "Awaiting redirect" / "Session complete" / "Final summary" — BANNED phrases

**Hard ban**: These phrases at iter close are auto-rejected by self-check (mental hook):

- "awaiting redirect"
- "session complete" 
- "final summary"
- "ready for your direction"
- "what's next?"
- "let me know how to proceed"
- "please advise"

**Why banned**: Each phrase converts continuation iter into stop-and-ask, violating /loop 0-pause core directive (sustained from v9.6 §0).

**Replacement template**: "iter N closed [...], iter N+1 = [next backlog source pick per §v9.46 / §v9.56 pivot ladder]."

---

## §v9.64 (NEW) Service ops attempt timeout = pivot, not retry

**Anti-pattern observed (iter 142)**: Servy `stop` returned "Failed to stop service" but `start` returned "Service started successfully". CC accepted the false-positive + continued. Later iter 143 discovered the actual stop didn't happen (PID 14h old).

**Fix**: 
- Before claiming service restart success, verify via `Get-CimInstance Win32_Process` `CreationDate` (process start time post-restart)
- If process start time NOT within last 5 minutes → restart attempt failed (regardless of Servy CLI return code)
- Failed restart = document blocker per §v9.57 + pivot to non-blocked iter immediately
- Do NOT retry the restart (Servy CLI is unreliable for stop-stuck services)

**Real signal**: Servy CLI return values are NOT authoritative. Process inspection is the verification source.

---

## §v9.65 (NEW) iter scoping — split unfit work into design-only iter

**Anti-pattern observed (iter 148 F9)**: CC saw F9 audit_log needed ~800 LOC + design + 6 layers and concluded "DEFER-with-cite". But §v9.45 4-stage gate allows iter-friendly scope split.

**Fix**: When iter candidate too large:
- Stage 1 alone = "Research iter": grep / read related docs / 1-page research finding sediment → 1 iter
- Stage 2 alone = "Design iter": ≤ 2 页 MVP design doc per 铁律 24 → 1 iter
- Stage 3 alone = "ADR-DRAFT iter": REGISTRY row + draft → 1 iter
- Stage 4 = N implement iters per ≤ 500 LOC chunks

**Real signal**: NO work is too large to start. Decompose to iter-friendly chunks. Design-only iter satisfies §v9.41 0-gap.

For F9 specifically: iter 148 could have written research finding (1-page) OR draft audit_log schema design (1-page MVP) instead of pure DEFER.

---

## §v9.66 (NEW) "Genuine STOP" qualifier hardened

**Anti-pattern observed (iter 148 + iter 149)**: CC cited §6 carve-out for F9 (audit_log Architecture·Strategy) and treated it as session-level STOP, not just iter pivot.

**Clarification**: §6 carve-out STOP applies to **the specific iter attempt**, NOT the loop continuation:

- §6 trigger → defer this specific work + cite + next iter picks from §v9.46 backlog
- §6 STOP ≠ session-end
- The /loop spec §4.3 "本 loop 不靠「跑完」终止" is the master constraint

**Forbidden interpretation**: "F9 hit §6, all remaining W2-F gaps require similar carve-out → no autonomous work left" — this is over-extension. Other Tier work (Phase J / Tier B Wave 5 design / Tier C/D research) doesn't share F9's design-heavy nature.

---

## §v9.67 (NEW) Iter pacing — measured by iter count, not session length

**New formalization**: Loop continues until:
- §5 hard carve-out hit (true STOP, e.g. red-line drift / .env mutation attempt)
- User explicit STOP / redirect
- Compaction event (mid-loop only) — resume post-compaction

NOT until:
- "Session feels long enough"
- "Many PRs merged"
- "Context window growing deep"
- "User might want to know status"

**Real signal**: A 50-iter session that ends with "awaiting redirect" is worse than a 50-iter session that smoothly transitions to iter 51 without comment.

---

## §v9.68 (NEW) New session backlog priming

**Cross-session bridge mandate**: At session start (Constitution §L0.3 fresh read step), in addition to current handoff:
- Read `docs/audit/W2_F_*` cluster for recent W2-F closures + F9 DEFER cite
- Read `docs/audit/W2_A_RUNTIME_REVERIFY` for Servy restart blocker status
- Read `docs/audit/L4R_AUDIT_WEEK2_MANIFEST` for remaining audit slots
- This primes next iter selection without re-deriving §v9.46 backlog

---

## Anti-pattern checklist (CC self-mental hook at iter close)

Before output, run mental check:

1. ☐ Did I write "awaiting redirect" / "session complete" / "final summary"? → REWRITE per §v9.63
2. ☐ Did I bullet-list "5 outstanding actions requiring user"? → MOVE to audit doc per §v9.62
3. ☐ Did I write > 1 sentence at iter close? → COMPRESS per §v9.61
4. ☐ Did I treat ops blocker as session-end? → PIVOT per §v9.57
5. ☐ Did I treat reviewer COMMENT as no-action? → fix-flow per §v9.54
6. ☐ Did I treat backlog exhaustion as session-end? → PIVOT per §v9.56
7. ☐ Did I claim service restart success without process-inspect? → VERIFY per §v9.64
8. ☐ Did I DEFER without trying iter-scope split (design-only)? → SPLIT per §v9.65
9. ☐ Did I hit §6 and STOP the loop (not just defer the iter)? → CONTINUE per §v9.66
10. ☐ Did I write a digest as session-end signal? → CONTINUE per §v9.60

If ANY box checked = self-correct + re-emit. Do not push the offending output.

---

## §v9.7 Short `/goal` template (paste-ready)

```
/loop QuantMind V2 L4+R 自主单 session 持续无限循环 (v9.7-stop-pattern-closure, Pattern B + 4-Tier roadmap + 0-pause + honest-ship + frontend-design SOP + §v9.54-§v9.68 anti-pattern sediment)

完整 spec = docs/L4R_LOOP_SPEC.md §1-§14 + §v8 Addendum + §v9.6 Addendum + docs/L4R_LOOP_SPEC_V97_ADDENDUM.md.
Session 起手 / cross-MVP boundary 必 fresh read 三 doc + CLAUDE.md + memory project_sprint_state.md + .omc/state/l4r_loop_state.md "Current" section + docs/QUANTMIND_PLATFORM_BLUEPRINT.md §Part 0 + Quickstart.

═════════════════════════════════════════════════════════════
## §0 v9.7 升级核心 (over v9.6)
═════════════════════════════════════════════════════════════

10 NEW anti-pattern (§v9.54-§v9.68) closure 2026-05-26 iter 130-149 session
3 user frustration signal ("为什么又停止了" × 3) sediment 驱动:

- §v9.54 Reviewer COMMENT verdict 同 iter fix-flow MANDATORY
- §v9.55 Deploy gap discovered → same-iter remediation
- §v9.56 Backlog "exhaustion" ≠ session end (5-tier pivot ladder)
- §v9.57 Ops blocker handling SOP (document + pivot, NEVER halt)
- §v9.58 Migration apply autonomy gate (idempotent = APPLY, destructive = DEFER)
- §v9.59 Concurrent session race handling SOP
- §v9.60 Digest cadence = SCHEDULED iter (not session-end signal)
- §v9.61 Iter close output ≤ 1 sentence
- §v9.62 "5 outstanding actions requiring user" framing BANNED
- §v9.63 "Awaiting redirect" / "Session complete" / "Final summary" — BANNED phrases
- §v9.64 Service ops verify via process inspection (Servy CLI not authoritative)
- §v9.65 Large iter → split into design-only / research-only sub-iter
- §v9.66 §6 carve-out = iter-level defer, NOT session-end
- §v9.67 Iter pacing — measured by iter count, not session length
- §v9.68 Cross-session backlog priming (W2-F / Servy / W2-X audit doc fresh read)

10-step anti-pattern checklist mental hook before every iter-close output.

═════════════════════════════════════════════════════════════
## §1 v9.6 sustained 全部条款 (1-53)
═════════════════════════════════════════════════════════════

v9.6 §-1 4-Tier roadmap / §0 真自主硬性 / Pattern B / §1 起手 SOP / §v9.37-v9.53 全 sustained.

═════════════════════════════════════════════════════════════
## §2 当前 Goal 数字 (refresh 2026-05-26 iter 149)
═════════════════════════════════════════════════════════════

QuantMind V2 全栈生产就绪. 年化 15-25% / Sharpe 1.0-2.0 / MDD <15%.
Sharpe 0.87 sustained → 1.0+ target. PT paper 27+ days since 4-29 清仓.

Tier A§2 V3 风控 frontend 100% closed (F1+F2+F3 iter 136+137+138).
Tier A§1 Phase J 5 chain sustained backlog.
Tier B Wave 5: F4+F5+F6+F7+F8+F10 closed/archived (iter 139-147), F9 DEFER iter 148.

W2-X audit slots:
- W2-A ✅ closed iter 131 (6 finding, 3 P0 closed iter 132+134)
- W2-B ✅ audit iter 149 (L4_STAGED PATH_DRIFT + DDL gap)
- W2-C ✅ audit iter 145 (outbox publisher drift, V3 §S6 4-domain only 1/4 in DDL)
- W2-D ✅ audit iter 149 (factor_values 173GB compression OFF P1 finding)
- W2-E ✅ doc refresh iter 144 (DEV_NOTIFICATIONS impl status)
- W2-F ✅ 9/10 closed/archived + 1 DEFER iter 148

Sustained pending action (audit-doc-cited):
1. Servy restart elevated unblock (iter 142+143)
2. F1 W2-D compression apply (user authorization, off-hour)
3. F9 audit_log design phase 4-stage gate
4. Phase J 5 chain selection

═════════════════════════════════════════════════════════════
## §3 第一动作 v9.7
═════════════════════════════════════════════════════════════

§v9.56 pivot ladder Tier A§2 done → Tier A§1 Phase J 5 chain decomposition iter.

iter 150 = Phase J §1.1 流 4 风控 Chain Wire decomposition design (Option A Beat-driven path):
- Read `docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md` §1.1 全文
- Design ≤ 2 页 sub-iter decomposition (split 3-7d effort into 5-7 iter-friendly chunks)
- Sediment as `docs/mvp/MVP_4_5_l1_realtime_risk_wire.md` OR similar
- Push as iter 150 governance TIER C direct commit

iter 151+ = Phase J §1.1 Stage 4 implement chunks per decomp output.
iter ~155 = §v9.60 scheduled digest #14 (10-iter cadence post 140).
iter ~160 = §v9.49 reality re-grounding cycle (5-iter post 149 baseline).

不限 iter 数 / 不自宣 END / 0 pause.
```

---

**Provenance**: Self-derived from iter 130-149 session anti-pattern observation. 10 NEW sections sediment-driven by 3 user frustration signal. Self-protected per L4R_LOOP_SPEC §自我保护 — §v9.54-v9.68 属 loop 安全约束, CC 不得自主放宽。
