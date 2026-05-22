# L4+R 方向 Digest Log

> **用途**: L4+R 自主持续循环 §4.1 方向 digest 的 append-only 落点。
> **写入**: CC 每 research cycle + 每 ~5 execute task + 至少每周一次 append 一条 digest(做了什么 / commit / 下一步计划 / 方向判断 / 与上次 digest 方向偏移 / implement:archive:defer 比例)。
> **读取**: user 可异步翻阅 veto/redirect;§4.2 self-audit 抽查方向漂移。
> **体例**: append-only,新 entry 追加在文件末尾(时序正序),0 retroactive edit。
> **来源 spec**: docs/L4R_LOOP_SPEC.md §4.1
> **创建**: 2026-05-22(loop 未启用,首条 digest 待 loop 首次触发)

---

<!-- digest entries appended below by L4+R loop §4.1 -->

## Digest #1 — 2026-05-22 (iterations 1-2)

**做了什么**
- **Iteration 1 — Phase K O2**: the frontend `triggerPipeline()` POSTed `/pipeline/trigger` with no body → backend `TriggerPipelineRequest` 422'd (the "手动触发 Pipeline" button was broken). Fixed it to send `{engine, config}` + a typed return; added a 4-test regression file; reconciled `docs/API_COVERAGE.md` §6.1. **PR #444 merged** (`d184712` + `c225896`) — independent reviewer APPROVE, tsc/vite/smoke all green.
- **Iteration 2 — verification iteration (no code PR)**. Checked 4 quick backlog items from the iteration-1 punch-list; all stale or imprecise: Calendar `get_calendar()` conn_factory bug (already fixed by "Plan D" 2026-05-20), M-1/M-3 DSN-leak (imprecise — the canonical scripts already use `get_sync_conn`; the real issue is the deferred-gated 铁律 35 fallback-cred closure), RUST_ENGINE_PATH (not actually in `.env.example`), plus the iteration-1 O4/O5/O6 (already fixed by prior work). factors O9/O10 confirmed real orphans but backend-build scope.

**commit / artifact**: PR #444 (merged). Iteration 2: 0 commits — finding-only.

**方向判断 (direction judgment)**
The quick-task backlog seeded from the 2026-05-19/05-20 handoffs is **decayed** — 4/4 micro-items checked were already done or imprecise (later work superseded them). The genuine remaining work is **"build" scope**, dominated by one coherent chunk: the **frontend-action-orphan cluster** — designed UI "action" buttons (pipeline pause / logs / automation-level; factor 因子体检 / 相关性裁剪 / 重评; backtest cancel) wired to backend endpoints that were never built. These need real backend builds with implementation choices, not quick fixes.

**下一步计划**: Pivot from "quick wins" to substantial builds. Iteration 3 = build `POST /api/factors/health-check` (factors O9 — the missing backend for the "因子体检"/"重评" buttons), modeled on the existing `POST /api/pipeline/trigger`. Then iterate the rest of the cluster.

**implement : archive : defer** — iter 1: 1:0:1 · iter 2: 0:0:1 · cumulative 1:0:2 (implement 33%, healthy band).

**方向偏移**: N/A — first digest.

**⚠️ user veto/redirect surface** (this is the §4.1 control surface — async, non-blocking): if you would rather the loop prioritize something other than the orphan-cluster builds — e.g. the 22-day-stale **regression baseline refresh** (铁律 15), a **frontier-research cycle**, the backend **"未实施" stubs** (BruteForce mining / report generation), or a specific orphan order — say so and the loop redirects. Otherwise it proceeds with the orphan-cluster builds starting at factors O9.

---

## Digest #2 — 2026-05-22 (iterations 3-7 + research cycle 1)

**做了什么**
- **Iterations 3-6 — 3 PRs merged** (Inner loop A): #445 factors O9 (`POST /api/factors/health-check` — wires the 因子体检/重评 buttons) · #446 backtest O1 (`POST /api/backtest/{run_id}/cancel` + cooperative-cancel guards) · #447 `daily_data_ingest` failure DingTalk alert (closes `# TODO Step 12 BAU`). All independent-reviewer APPROVE (0 P1/P2); ruff/test/smoke green.
- **Iteration 6** also ran a fresh current-code re-scan and deep-investigated BruteForce-mining wiring → found it L-with-design (`run_full_gate` is GP-specific), re-scoped to Inner-loop-B (D3).
- **Iteration 7 — research cycle 1** (Inner loop B, §10): re-tread defense + frontier scan → `docs/research/RN_001_frontier_scan_2026_05_22.md`.

**commit / artifact**: PR #445 (c213d95) · #446 (ecde9c8 + d4151cd) · #447 (533a8df) · RN-001 (this commit).

**方向判断**
Research-cycle verdict = **ARCHIVE**. Two firm conclusions: (1) the A-share *alpha* frontier offers nothing genuinely new — every angle re-treads a documented mechanism-level failure or the equal-weight dilution wall; CORE3+dv_ttm is a real ceiling. (2) The scope-B "statistical-rigor" candidates a research subagent ranked "genuinely-new" were **all already built** (DSR wired in the standard metrics report + WF; 3-level factor-decay run daily; data-quality checker exists). **META-finding**: 4th time this session a research/backlog candidate "looked new" but was already in the codebase — QuantMind V2 has substantial built-but-dark code; candidates must be code-grep-verified before any verdict (LL-candidate; see RN-001 §6).

**下一步计划**: The clean Inner-loop-A execute backlog is genuinely thin — the loop has shipped the easy items. What remains is design-scope (D1 orphan-cluster remainder O3/O7/O8/O10 + `/pipeline/status` contract; D3 BruteForce — all need product/architecture decisions) or user-gated (D2 cred rotation; the PT-restart path). §9.1 forbids a consecutive research cycle. The honest state: high-value remaining work is design-gated or user-gated.

**与上次 digest 方向偏移**: Digest #1's "pivot to build scope" held — 3 build PRs shipped. New: the build backlog of *clean* items is now also near-exhausted; the loop is approaching the §4.3 low-actionable state for *clean autonomous* work (not at it — Inner-loop-B design work on D1/D3 remains possible).

**implement : archive : defer** — cumulative 4 : 1 : 3 (the research cycle = the 1 archive). implement 50%, healthy.

**⚠️ user veto/redirect surface** (§4.1 — async, non-blocking): the loop has shipped 4 PRs and surveyed the frontier. Genuinely-remaining work is design-gated (D1/D3 need product/architecture decisions a research-then-design Inner-loop-B cycle could tackle) or user-gated (D2; PT-restart). If you want the loop to (a) take a D1/D3 item through Inner-loop-B (design doc + ADR-DRAFT), (b) do the XS cleanup then idle-check, or (c) something specific — say so. Otherwise the loop continues with what clean autonomous work remains and will honestly report when it reaches §4.3 low-actionable.
