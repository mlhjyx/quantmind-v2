# RN-002 — Research Cycle 2: Frontier Re-Scan + Structural Finding

> **Type**: L4+R loop research note (`docs/L4R_LOOP_SPEC.md` §10 Inner loop B output).
> **Date**: 2026-05-24 · **Cycle**: 2 (second research cycle of the L4+R loop).
> **Budget**: well within §9.2 (≤2-4h wall-clock; actual ~15min — structural blocker hit fast).
> **Verdict**: **ARCHIVE** (direction sustained from RN-001) + **structural finding** (new).

## §1 Question + scope

Per §9.1 (anti-consecutive satisfied — 5 execute tasks since RN-001) and RN-001 §7
carry-forward ("web + arxiv literature scan must be re-run when search is restored"),
this cycle: (a) retry the literature half RN-001 deferred, (b) re-scan GitHub-tracked
frontier for movement since 2025-08/2025-11, (c) re-issue verdict.

Scope unchanged from RN-001: (A) A-share quant factor / strategy / backtest / risk;
(B) quant-system engineering. Excluded: crypto / HFT / options / forex / intraday-tick.

## §2 Re-tread defense (§7) — sustained from RN-001

`docs/research-kb/` snapshot 2026-05-24: `failed/` 8 entries · `findings/` 22 entries ·
`decisions/` 5 entries. Spot-grep confirms no entries added/edited since RN-001 cycle 1
(no new permanent-dead / conditional-fail surfaces to add to the catalog this cycle).
RN-001 §2 permanent-dead + conditional-fail map sustained verbatim.

## §3 Frontier scan — 3 channels surveyed

### §3.1 GitHub-tracked open-source quant (1/3 — AVAILABLE)

`gh api repos/.../releases` — verified 2026-05-24:

| Project | Latest release | Date | Movement since RN-001 |
|---|---|---|---|
| `microsoft/qlib` | v0.9.7 | 2025-08-15 | **0** (same version as RN-001 §3) |
| `microsoft/RD-Agent` | v0.8.0 | 2025-11-03 | **0** (same version as RN-001 §3) |
| `RyanLiu112/AlphaAgent` | n/a | n/a | repo 404 (RN-001 §4 cited "AlphaAgent KDD 2025" — academic ref, not GitHub) |

Interpretation: 9 months since Qlib's last release; 6 months since RD-Agent v0.8.0. Both
RN-001 conclusions sustained — Qlib has no alpha-methodology move (incremental infra
only); RD-Agent's Docker-required NO-GO blocker stands (ADR-013 time-box still owns
revisit).

### §3.2 Web search — LLM-summarized (2/3 — STRUCTURALLY BLOCKED)

`WebSearch` tool: 4 queries attempted (A-share factor 2026 / arxiv quant LLM A-share /
Qlib AlphaAgent benchmark / PBO+DSR implementation). All 4 returned same error:

> "There's an issue with the selected model (deepseek-v4-pro[1m]). It may not exist or
> you may not have access to it."

**This is the same model-router gap blocking `everything-claude-code:python-reviewer`**
(the L4+R loop has consistently fallen back to `general-purpose` subagent reviewer since
iter 8). Affects WebSearch backend the same way. **Not transient — structural in this
harness.**

### §3.3 arxiv direct API — raw curl (3/3 — STRUCTURALLY BLOCKED)

`curl https://export.arxiv.org/api/query?cat=q-fin.PM&...` → HTTP body: `Rate exceeded.`
RN-001 §3 reported the same "arxiv rate-limited" blocker on 2026-05-22. **Same blocker
2/2 cycles** — likely IP-based rate-limit on the harness sandbox egress, not transient.

## §4 Candidate verification — N/A this cycle

No new candidates surfaced (0/3 channels productive; the 1 available channel showed 0
movement). Cross-verification step (RN-001 §6 META-finding: code-grep-verify candidates
against `backend/engines/`) was not needed.

## §5 Verdicts (§9.2 — non-open-ended)

### §5.1 Direction verdict — ARCHIVE (sustained)

Per RN-001 §5 — A-share alpha frontier ARCHIVE; scope-B statistical-rigor ARCHIVE;
PBO-into-gate DEFER; RD-Agent re-eval DEFER (ADR-013). **All RN-001 verdicts sustained**
— GitHub-release evidence shows 0 relevant version drift; no new project KB entries to
revise; no literature-side surface available to challenge.

### §5.2 Structural verdict — Literature half permanently closed in this harness

**NEW finding (sediment-worthy, LL-candidate):** The L4+R loop's research-cycle
literature-scan half is **structurally unavailable** in the current Anthropic harness:

- WebSearch: blocked by deepseek-v4-pro model-router gap (same blocker as
  `everything-claude-code:python-reviewer` — affects multiple downstream tools).
- arxiv direct API: rate-limited (2/2 cycles).
- WebFetch: redirected through `context-mode` hook — not reliably usable for arbitrary
  literature URLs (designed for known-URL ingestion, not search).

**Process correction**: future research cycles should NOT budget the literature half
unless the harness regains a working LLM-summarized web search. Cycles should focus on
(a) GitHub-tracked open-source quant releases (reliable + cheap), (b) project KB
re-grep (reliable + zero cost), and (c) user-supplied papers/URLs if user has external
literature flow. RN-001 §7 carry-forward ("re-run literature scan when search restored")
is **closed as structurally unavailable**, not deferred indefinitely.

This is L4+R loop self-knowledge: research cycle 2 yielded **0 direction findings + 1
structural finding about the loop itself**. Both are valid sediment per spec §4.5
(ARCHIVE = "防重蹈的弹药").

## §6 Carry-forward

- **Literature half PERMANENTLY CLOSED** in current harness (see §5.2). Reopen condition:
  WebSearch deepseek-v4-pro gap fixed OR new harness with working LLM-summarized search.
- **Next research cycle eligibility**: after another ~5 execute tasks (§9.1 anti-consecutive).
  When triggered, default scope = GitHub-release scan only; literature unless capability
  proven first.
- **iter 15 candidate**: per iter 14 RESUME POINT alternatives (none blocked by RN-002):
  - D1 O7 log-history endpoint (medium-large, storage decision)
  - `/pipeline/status` contract refactor (small — most fields already shipped via PN-001
    + PN-003; remaining = `nodes[]` mapping + Celery schedule fields)
  - D3 BruteForce gating-design (largest, may need user architecture decision)
  - Recommendation: **`/pipeline/status` contract refactor** (smallest, cleanup).

## §7 implement : archive : defer ratio update

Iter 14 = ARCHIVE → cumulative 8 : 2 : 3 (implement 62%, healthy). Trending back into
mid-band per digest #3 forecast. Confirms Inner-loop-B + periodic research-cycle
rotation is a sustainable ratio-balancing pattern.
