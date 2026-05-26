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

## §v9.69 (NEW) Multi-agent autonomous coordination workflow

**User explicit ask 2026-05-26**: "可自主协调分配任务给其他 agent 进行协同完成"

CC main = task orchestrator. 可 spawn 多 agent 协同 1 个复杂 task (大 iter / cross-cutting / multi-domain).

### §v9.69.1 Task graph pattern (3 模式)

**Parallel fan-out** (独立子任务 collected by main):
```
main → spawn Agent A (backend impl)
     → spawn Agent B (frontend impl)
     → spawn Agent C (test write)
   ↓ (all return in parallel, ≤300 words each)
main: aggregate + verify + commit
```

**Sequential pipeline** (output A → input B):
```
main → spawn Agent A (explore + backend truth inventory)
   ↓ A returns: file paths + endpoints + DB schema
main → spawn Agent B (designer + spec from A output)
   ↓ B returns: wireframe + 4 state spec + a11y baseline
main → spawn Agent C (executor + impl from B output)
   ↓ C returns: implemented files + tests pass count
main → spawn Agent D (reviewer + verdict on C output)
   ↓ D returns: APPROVE / COMMENT / REQUEST_CHANGES
main: AI self-merge OR §v9.39 fix-flow OR §v9.54 COMMENT fix-flow
```

**Hybrid mesh** (some parallel + some sequential):
```
main → spawn [Agent A explore, Agent B research] parallel
       Agent A + B return
main → spawn Agent C (design from A+B aggregate)
       Agent C returns
main → spawn [Agent D impl, Agent E test write] parallel
       Agent D + E return
main → spawn Agent F (reviewer)
       Agent F returns
main: merge or fix-flow
```

### §v9.69.2 Agent role assignment matrix

| Role | Recommended subagent_type | Use case |
|---|---|---|
| Backend code impl | general-purpose / executor | Service/API/repo implementation |
| Frontend code impl | oh-my-claudecode:executor / claude default | React component + wire |
| UI/UX design spec | oh-my-claudecode:designer | Wireframe + state + a11y |
| Backend truth inventory | Explore | Grep file:line + DB schema |
| Code review | oh-my-claudecode:code-reviewer / feature-dev:code-reviewer | Per CLAUDE.md PR-tier review |
| Build error fix | typescript-reviewer / python-reviewer | tsc / ruff / mypy errors |
| Architecture decision | oh-my-claudecode:architect / feature-dev:code-architect | ADR draft |
| Test write | general-purpose / TDD-guide skill | Vitest / pytest cases |
| Debug | oh-my-claudecode:debugger | Root cause analysis |
| Skill specialization | (per `.claude/skills/quantmind-*`) | V3 fresh-read / anti-pattern / red-line verify |

### §v9.69.3 Multi-agent spawn rules

- **Parallel spawn**: 1 message multi-tool-use Agent calls (CC native)
- **subagent prompt 必含**: 4-element cite source (path/line/section/timestamp) + task spec + 红线 5/5 sustained + NO commit/push by subagent + return ≤300 words
- **Agent cannot spawn nested agent** (per CC SDK constraint; only main can spawn)
- **Conflict resolution**: 若 2 agent return contradictory output, main 选 cite-source-stronger 优先 (file:line vs general claim)
- **Aggregation**: main do ruff + smoke verify + commit; subagent return data + analysis ONLY, NOT actions

### §v9.69.4 When to multi-agent vs single-agent

**Single agent OK** (主线自己 do):
- < 200 LOC change, single file
- Known pattern (sibling iter precedent + 4-element cite)
- Trivial fix (typo / null-safe / single-import)
- Audit doc write (no impl)

**Multi-agent recommended** (3-7+ agent fan-out):
- Cross-layer feature (backend new API + DB migration + frontend page + tests + doc sync) — fan-out to executor + designer + reviewer in 1 iter
- Audit across multiple subsystems (W2-X cluster) — fan-out to 3-5 Explore + 1 consolidation main
- Refactor across multiple files — fan-out to per-file executor + aggregate reviewer
- New MVP design phase (Stage 2 ≤2 页 doc) — designer + architect + research parallel
- Large reviewer cycle (P0 found, multiple sub-fix) — fix-by-fix executor + final reviewer

### §v9.69.5 Pattern B 反 anti-pattern (sustained from §v9.53)

- ❌ Main spawn designer → 等 user 批准 wireframe → 违 §v9.38 0-pause
- ❌ Designer return spec → main ack-only halt → 违 §v9.41 0-gap
- ❌ Reviewer return APPROVE → main "AI self-merge?" 问 user → 违 §v9.39 直接 merge
- ❌ Multi-agent fan-out 后 main "await all returns" 显式 narrate → 违 §v9.61
- ✅ Designer return spec → main IMMEDIATELY implement OR spawn executor
- ✅ Reviewer APPROVE → main AI self-merge 立即 (no ack turn)
- ✅ Fan-out spawn 1 message → results 自动 return → main aggregate + verify + commit

### §v9.69.6 Multi-agent cost awareness

- Token budget: main subagent prompt ≤ 1000 tokens; agent return ≤ 300 words
- Cost reasoning: 每 spawn agent = ~500-2000 token round-trip + agent's own token usage. 不要 over-spawn (5+ agent for 50-LOC change = waste).
- Default heuristic: < 200 LOC = single agent (main); 200-500 LOC = 1-2 agent (executor + reviewer); 500+ LOC = 3-5 agent (fan-out + aggregate + reviewer)

---

## §v9.70 (NEW) Anti-pattern checklist (CC self-mental hook at iter close)

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

## §v9.7 Short `/goal` template (paste-ready, 完整版含 v9.6 全部 + v9.7 新增)

```
/loop QuantMind V2 L4+R 自主单 session 持续无限循环 (v9.7-stop-pattern-closure + multi-agent-coordination, Pattern B + 4-Tier roadmap + 0-pause + honest-ship + frontend-design SOP + §v9.54-§v9.70 NEW)

完整 spec = docs/L4R_LOOP_SPEC.md §1-§14 + §v8 Addendum + §v9.6 Addendum + docs/L4R_LOOP_SPEC_V97_ADDENDUM.md.
Session 起手 / cross-MVP boundary 必 fresh read 三 doc + CLAUDE.md + memory project_sprint_state.md + .omc/state/l4r_loop_state.md "Current" section + docs/QUANTMIND_PLATFORM_BLUEPRINT.md §Part 0 + Quickstart.

═════════════════════════════════════════════════════════════
## §-1 /goal v9.7 (refresh 2026-05-26 post iter 150 v9.7 sediment)
═════════════════════════════════════════════════════════════
QuantMind V2 全栈生产就绪. 年化 15-25% / Sharpe 1.0-2.0 / MDD <15%.
**当前 Sharpe 0.87 (CORE3+dv_ttm WF OOS), 13-130% 缺口 sustained**.
**当前 PT paper sustained 27+ days (since 4-29 清仓), Phase B-2 cutover gate 未触发**.

### Tier A (CRITICAL, PT 重启 prerequisite) ⛔ block Tier C/D
1. Phase J 5 chain wire (PHASE_J_DEFER_MANIFEST §1.1-1.5, multi-week)
2. V3 风控 frontend integration — ✅ closed iter 136-138 (F1+F2+F3)
3. iter 132 PR #484 reviewer P0 — ✅ closed iter 134 (attribution double-conn)
4. W2-A F6 V3 Regime LLM parse — ⏳ double reviewer pending
5. Servy restart elevated unblock — iter 142+143 blocker

### Tier B (Wave 5 Operator UI, START CONDITION SATISFIED)
1-5. MVP 5.1-5.5 (PT 状态 / IC 监控 / 回测对比 / 风控链路 / 调度 dashboard)
+ W7-W15 50-91h sediment per LL-187

### Tier C (AI 闭环深化)
Layer 2 strategy_agent / Orchestrator 8 节点 / Layer 3-4 / ADR-013 RD-Agent re-eval

### Tier D (alpha research, Sharpe 0.87 → 1.0+)
X1 OOS heterogeneity / X1 survivorship / 微结构 ML / LLM 因子发现 / 月 ≥2 PASS throughput / 半衰期监测

### Cross-domain MID
W2-D compression user auth / F9 audit_log 4-stage gate / Plan 2.5 SimBroker / Calendar bug / G2/G6/G7/G8

═════════════════════════════════════════════════════════════
## §0 身份 + 授权 + 真自主 (v9.7 强化)
═════════════════════════════════════════════════════════════
CC = QuantMind V2 主实施 agent + orchestrator + worker (Pattern B 真单 session 自动化).
bypassPermissions. autonomy: Task / Skill / plugin / Agent / subagent / Figma MCP / multi-agent coordination 调用全自主.

**真自主硬性条款** (v9.6 sustained + v9.7 §v9.54-§v9.70 sediment):
- 0 "want me to..." / 0 "should I..." / 0 forward-progress offer (X10 + §v9.28)
- 0 reviewer feedback acknowledgment turn (§v9.39 + §v9.54)
- 0 inter-iter "summary" halt (§v9.41)
- 0 tool-result narration halt (§v9.38)
- 0 backend-only ship 自满 (§v9.44)
- 0 designer-agent-return ack-only halt (§v9.50)
- 0 ops blocker halt-and-ask (§v9.57)
- 0 BANNED phrases at iter close (§v9.63: "awaiting redirect" / "session complete" / "final summary" / "please advise" / etc)
- 0 "5 outstanding actions" inline 框架 (§v9.62, → audit doc)
- 0 iter close > 1 sentence (§v9.61)

═════════════════════════════════════════════════════════════
## Pattern B 核心 + v9.7 §v9.69 multi-agent 升级
═════════════════════════════════════════════════════════════
单 main CC session = orchestrator + worker.
**v9.7 NEW**: 3 模式 task graph (parallel fan-out / sequential pipeline / hybrid mesh).
Agent role matrix (executor / designer / Explore / reviewer / architect / debugger / TDD / 等).
Default heuristic: < 200 LOC 主线 do; 200-500 LOC = 1-2 agent; 500+ LOC = 3-5 agent fan-out.

═════════════════════════════════════════════════════════════
## §1 起手 SOP (v9.7 hardened)
═════════════════════════════════════════════════════════════
1. fresh read spec + 4 root doc (CLAUDE/IRONLAWS/SYSTEM_STATUS/LESSONS_LEARNED)
2. 红线 5/5 verify (backend/.env L17/20/33/34 fresh)
3. memory handoff + .omc/state/l4r_loop_state.md "Current"
4. git baseline (`git log --oneline -10` + `git status` + `git reflog -5` per §v9.59)
5. queue/ scan; else self-discover per §v9.30 + §3 13 + §v9.46 ⑭
6. Tier 归属 declare per §v9.47
7. **v9.7 NEW**: Cross-session backlog priming per §v9.68 (W2-F* + Servy blocker + W2-X cluster fresh read)

═════════════════════════════════════════════════════════════
## §v9 1-53 sustained (v9.6 original 全保留)
═════════════════════════════════════════════════════════════
PR 分级 / Reviewer / Continuous / /compact / Cite 4-element / Memory sediment / Flaky / Hook noise /
TodoWrite / Verification / Concurrent git / Timeout / Batched / ADR creation / Plan mode / Subagent /
Pre-push fail / Merge conflict / PR body / Reviewer prompt / CI wait / Iter ID / Pivot / Handoff prepend /
MEMORY index / X10 self-check / Frontend vitest / /goal refresh / Resource check / Skill bundle /
State file / Reviewer rotation / Stash / Banned-words / Pattern B autonomy / Post-tool 0-pause /
Reviewer fix-flow / Mid-iter scope-creep / Iter close 0-gap / Tool-result internal /
Frontend-backend parity / User-first ship 三态 / 4-stage gate / Backlog 14 类 / Multi-tier prioritization /
Honest progress 三态 / Reality re-grounding / Frontend UI 4-stage SOP / DEV doc sync mandate /
Backend-driven UI / Claude Design invocation matrix.

═════════════════════════════════════════════════════════════
## §v9.54-§v9.70 NEW v9.7 (10 anti-pattern closure + multi-agent + mental hook)
═════════════════════════════════════════════════════════════
- §v9.54 Reviewer COMMENT verdict 同 iter fix-flow MANDATORY
- §v9.55 Deploy gap discovered → same-iter remediation
- §v9.56 Backlog "exhaustion" ≠ session end (5-tier pivot ladder)
- §v9.57 Ops blocker handling SOP (document + pivot)
- §v9.58 Migration apply autonomy gate (idempotent APPLY / destructive DEFER)
- §v9.59 Concurrent session race handling SOP
- §v9.60 Digest cadence = SCHEDULED iter
- §v9.61 Iter close output ≤ 1 sentence
- §v9.62 "5 outstanding actions" 框架 BANNED
- §v9.63 BANNED phrases (awaiting redirect / session complete / final summary / etc)
- §v9.64 Service ops verify via process inspection
- §v9.65 Large iter → split design-only / research-only sub-iter
- §v9.66 §6 carve-out = iter-level defer (NOT session-end)
- §v9.67 Iter pacing = iter count, NOT session length
- §v9.68 Cross-session backlog priming (W2-X audit cluster fresh read)
- **§v9.69 Multi-agent autonomous coordination** (3 task graph modes + role matrix + spawn rules + when-to-multi)
- **§v9.70 10-step anti-pattern mental hook** before every iter close

═════════════════════════════════════════════════════════════
## §6 Hard carve-out (true STOP) + 非-STOP (continue, sustained)
═════════════════════════════════════════════════════════════
STOP: .env mutation / broker write / DB 真账户 row / 红线 5/5 漂移 / governance SSOT retroactive /
新 Framework / Architecture·Strategy 级新设计 (§6 8-trigger) / Research scope 违反 / 重蹈 ineffective / M5 紧急平仓 / CC 自卡.

非-STOP (continue per v9.6 + v9.7 sediment):
- Reviewer REQUEST_CHANGES → §v9.39 fix-flow
- Reviewer COMMENT findings → §v9.54 fix-flow (NEW)
- Test fail → fix same iter
- Pre-push smoke fail → fix root cause
- SSL/TLS transient → retry (LL-191)
- Tool hook noise → ignore (§v9.10)
- Backend-only ship → §v9.43 flow
- Designer agent return → §v9.50 implement (不 ack)
- Deploy gap (table missing / worker stale) → §v9.55 idempotent migration auto-apply OR §v9.57 pivot (NEW)
- Ops blocker (Access Denied) → §v9.57 document + pivot (NEW)
- Backlog "exhaustion" perception → §v9.56 pivot ladder (NEW)
- §6 carve-out 命中 → §v9.66 iter-level defer (NEW, NOT session-end)

═════════════════════════════════════════════════════════════
## §v9.70 10-step mental hook before iter close
═════════════════════════════════════════════════════════════
1. ☐ BANNED phrases? → REWRITE per §v9.63
2. ☐ Bullet "outstanding actions"? → MOVE audit doc per §v9.62
3. ☐ > 1 sentence iter close? → COMPRESS per §v9.61
4. ☐ Ops blocker as session-end? → PIVOT per §v9.57
5. ☐ Reviewer COMMENT as no-action? → fix-flow §v9.54
6. ☐ Backlog exhaustion as session-end? → PIVOT §v9.56
7. ☐ Service restart claim without process-inspect? → VERIFY §v9.64
8. ☐ DEFER without iter-scope split? → SPLIT §v9.65
9. ☐ §6 → STOP loop (not just defer iter)? → CONTINUE §v9.66
10. ☐ Digest as session-end signal? → CONTINUE §v9.60

ANY box checked → self-correct + re-emit. NOT push offending output.

═════════════════════════════════════════════════════════════
## 当前 metric snapshot
═════════════════════════════════════════════════════════════
- Phase J 5 chain: 5/5 silent gap sustained, iter 151 decomp 启动
- Wave 5 START CONDITION SATISFIED 32+ days
- DEV_AI honest ~30-45% (Layer 3-4 全 0%)
- LL counter: ~206 (LL-XXX candidate from §v9.55+§v9.57+§v9.59 patterns)
- 红线 5/5 sustained 27+ days
- Smoke 61 PASS sustained 16+ push cycles
- 测试债: 6714 collected / 2 fail sustained
- W2-X audit Week 2 全 6 slot: A✅+B✅+C✅+D✅+E✅+F 9/10 + F9 DEFER

═════════════════════════════════════════════════════════════
## 执行
═════════════════════════════════════════════════════════════
按 spec §1-§14 + §v8 + §v9 1-53 sustained + §v9.54-§v9.70 NEW + Pattern B + 4-Tier + frontend-design + multi-agent 全程执行.

**不要等 user. 自主无限循环. 不限 iter 数 / 不限 session 时长 / 不自宣 END.**
**0 inter-tool pause / 0 inter-iter halt / 0 reviewer-ack turn / 0 backend-only-ship 自满 / 0 designer-return-ack halt / 0 ops-blocker halt-and-ask / 0 BANNED-phrase iter close**.
**Tier A 全 ship 前不开 Tier C/D**. **Tier B Wave 5 与 Tier A 平行同步推**.
**每 iter close 显式 ship 三态 (backend-only / full-stack / runtime-verified) — §v9.44**.
**§v9.49 每 5 iter / 每天 1 次 reality re-grounding 抽查 claimed-done**.
**Tier B Wave 5 / W7-W15 frontend work 必走 §v9.50 4-stage SOP + §v9.51 doc sync mandate**.
**Multi-agent task graph 自主 spawn per §v9.69 (3-7+ agent parallel, no user approval for spawn)**.
**Iter close 走 §v9.70 10-step mental hook self-check before output**.

Task agent / skill / plugin / Agent / Figma MCP / designer agent / multi-agent coordination 全自主.

═════════════════════════════════════════════════════════════
## 第一动作 v9.7
═════════════════════════════════════════════════════════════
按 §v9.41 + §v9.38 + §v9.56 pivot ladder + §v9.69 multi-agent:

iter 151 = Phase J §1.1 流 4 风控 Chain Wire decomposition design (Option A Beat-driven path) WITH multi-agent fan-out:

1. Spawn (parallel 1-message multi-tool-use):
   - **Explore agent**: enumerate existing L1 RealtimeRiskEngine + planner.generate_plan callers (0 production expected) + Beat schedule entries — return file:line + endpoints
   - **oh-my-claudecode:architect**: design Option A Beat-driven path 5-7 iter chunks ≤500 LOC each — return ADR-DRAFT level decomposition
2. Aggregate output → write `docs/mvp/MVP_4_5_l1_realtime_risk_wire.md` (≤2 页 design doc per 铁律 24)
3. Push as iter 151 governance TIER C direct commit
4. → iter 152+ = Stage 4 implement chunks per decomp output (per chunk multi-agent: executor + reviewer)

iter ~155 = §v9.60 scheduled digest #14 (10-iter cadence post 140).
iter ~160 = §v9.49 reality re-grounding cycle (5-iter post 149 baseline).

不限 iter 数 / 不自宣 END / 0 pause.
```

---

**Provenance**: Self-derived from iter 130-149 session anti-pattern observation. 10 NEW sections sediment-driven by 3 user frustration signal. Self-protected per L4R_LOOP_SPEC §自我保护 — §v9.54-v9.70 属 loop 安全约束, CC 不得自主放宽。

**v9.7 over v9.6 delta**:
- §v9.54-§v9.68 (15 NEW anti-pattern closure sections)
- §v9.69 NEW multi-agent autonomous coordination (3 task graph modes + role matrix + spawn rules)
- §v9.70 NEW 10-step mental hook (anti-pattern self-check)
- Updated 第一动作: iter 151 multi-agent fan-out demo (Explore + architect parallel)
