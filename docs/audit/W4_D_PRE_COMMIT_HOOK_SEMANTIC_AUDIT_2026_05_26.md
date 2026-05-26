# W4-D PRE_COMMIT_HOOK_SEMANTIC_AUDIT (iter 164)

**Audit date**: 2026-05-26 16:15 SH
**Iter ID**: 164 (Week 4 cluster, sibling to W4-A iter 162)
**Method**: read `config/hooks/pre-commit` lines 107-154 LL-188 detection logic (read-only)
**Trigger**: W4-A iter 162 finding (21/21 false-positive sustained) — W4-D extends with refinement spec.

---

## §1 Hook detection logic (current state)

`config/hooks/pre-commit` LL-188 step 0 sediment-drift check:

```python
# Lines 107-154 verbatim semantic:
1. Read backend/.env → extract EXECUTION_MODE actual + LIVE_TRADING_DISABLED actual
2. git diff --cached --name-only --diff-filter=ACM | filter .md
3. For each staged .md:
   - git show :FILE → get cached blob content
   - re.finditer(r'EXECUTION_MODE=(\w+)', content) — match ANY occurrence
   - If claimed != env_actual_mode.lower() → append warning
   - Same for LIVE_TRADING_DISABLED=(\w+)
4. Cap warnings at 10 for display (sustained 21 actual mismatches per W4-A)
5. Warning-only mode (sustained Phase 4.2 minimal scope per hook self-comment)
```

---

## §2 Logic gap analysis (extending W4-A finding)

W4-A iter 162 audit classified 21/21 staged .md matches as INTENTIONAL historical/runtime context. Root cause: hook regex `EXECUTION_MODE=(\w+)` is **context-free** — matches in any text position regardless of semantic role.

**Context types misclassified as "stale claim"**:

| Context type | Example | Should detect? |
|---|---|---|
| Code block ` ``` ... ``` ` | ` ```EXECUTION_MODE=live``` ` | ❌ NO (code snippet) |
| Inline code span `\`...\`` | `\`EXECUTION_MODE=live\`` in narrative | ❌ NO (inline code) |
| Historical phrasing | "post-CT-2b period EXECUTION_MODE=live" | ❌ NO (historical context) |
| Bash command verbatim | `sed -i 's/^EXECUTION_MODE=paper$/EXECUTION_MODE=live/'` | ❌ NO (runtime trace) |
| Current "Now:" / "Current:" marker | "Current state: EXECUTION_MODE=live" | ✅ YES (true stale claim) |
| Live red-line summary | "红线 sustained: ... EXECUTION_MODE=paper" | ✅ YES (true current claim — should match env) |
| Meta-reference (audit doc) | "hook says claims EXECUTION_MODE=live..." | ❌ NO (meta self-reference) |

---

## §3 Verdict

**W4-D state**: CONFIRMED W4-A finding + LOGIC GAP SPEC'D

- ✅ W4-A 21/21 false-positive empirically validated by W4-D code-trace
- ❌ Regex too broad — 6 context types misclassified out of ~7 total contexts
- ❌ Hook can't distinguish 1 TRUE positive (current red-line claim) from 6 INTENTIONAL contexts

**Severity**: P2 (sustained noise, no data correctness gap; promotion to Layer 2 strict block currently blocked)

---

## §4 Recommendations (refinement spec, DEFER implementation)

| # | Action | Tier | Effort | Trigger |
|---|---|---|---|---|
| R1 (IMPLEMENT) | Sediment this W4-D audit + refinement spec | Tier C | 1 commit | this iter 164 |
| R2 (DEFER — main refactor) | Hook regex refinement per refinement spec below | Tier B hook config + user authorize | ~30 LOC python | post user authorization |
| R3 (DEFER) | Optional: post-refactor regression test (commit fixture .md with various contexts to verify hook classification matrix) | Tier C test | ~30 LOC pytest | post R2 |
| R4 (DEFER) | If Layer 2 strict block upgrade desired (per hook self-comment line 158), MUST land R2 first | Tier B production hook | gated on R2 | post R2 + user authorize |

### Refinement spec (R2 detail)

Replace current regex `EXECUTION_MODE=(\w+)` with context-aware scanning:

```python
# Pseudocode
for line_idx, line in enumerate(content.split('\n')):
    # Skip if inside code block fence
    if line.strip().startswith('```'):
        in_code_block = not in_code_block
        continue
    if in_code_block:
        continue

    # Strip inline code spans before matching
    line_stripped = re.sub(r'`[^`]+`', '', line)

    # Match EXECUTION_MODE claims
    for m in re.finditer(r'EXECUTION_MODE=(\w+)', line_stripped):
        claimed = m.group(1).lower()
        # Skip if line contains historical context phrasing
        if any(phrase in line for phrase in ['post-CT-2', 'pre-CT-2', 'historical', '过去', '历史', 'previously']):
            continue
        # Skip if line contains meta-reference (audit doc citing hook)
        if any(phrase in line for phrase in ['claims EXECUTION_MODE', 'hook detection', 'audit', 'LL-188']):
            continue
        # True claim — check against env actual
        if claimed in ('paper', 'live') and claimed != env_actual_mode.lower():
            ll_188_warnings.append(f'{f}:{line_idx}: claims {claimed} but env={env_actual_mode}')
```

Effect: would reduce false-positive rate from 100% (21/21) to ~0% on existing LL/audit/sediment content. New true-positive detection limited to current-claim phrasing in newly authored sediment docs.

---

## §5 §6 8-trigger STOP check

All NEGATIVE (audit-only read-only, no hook modification this iter).

---

## §6 Cite source

| # | Path | Lines | Verify state | Verify timestamp |
|---|---|---|---|---|
| 1 | `config/hooks/pre-commit` | L107-154 | LL-188 detection python embedded in pre-commit shell | 2026-05-26 iter 164 fresh |
| 2 | iter 162 W4-A audit doc | §1-4 | 21/21 false-positive classification | iter 162 |
| 3 | `backend/.env` L17, L20 | red lines sustained | iter 164 |
| 4 | Hook self-comment line 158 | "Phase 4.2 minimal scope: warning-only, 真**0 block** sustained" | sustained |

---

**iter 164 classification**: 1 IMPLEMENT (this audit) + 3 DEFER (R2 hook refactor + R3 regression test + R4 Layer 2 promotion). §4.5 ratio: +1 impl +3 defer.

**Week 4 progress (post iter 164)**:
- W4-A ✅ iter 162 (LL-188 hook 21/21 false-positive)
- W4-D ✅ iter 164 (this audit, refinement spec defined)
- W4-E ✅ iter 163 (cron healthy)
- W4-B/C pending

**Hook refactor blocking analysis** (W4-A + W4-D cumulative):
- 100% false-positive rate sustained
- Layer 2 strict block upgrade BLOCKED on R2 implementation
- Refinement spec defined + ready for R2 implementation pending user authorization (Tier B per hook touches production gate config)
