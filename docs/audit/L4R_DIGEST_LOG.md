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

---

## Digest #3 — 2026-05-23/24 (iterations 8-12 + reviewer-fix mini-loop)

**做了什么**
- **Iteration 8 — XS cleanup** (Inner loop A): removed dead `--inplace` flag from `scripts/generate_system_status.py` (`4e41d47`, PR #449). Reviewer APPROVE 0 findings; 24 false-positive `inplace=` hits in archive/research confirmed as pandas kwargs.
- **Iteration 9 — §4.2 self-audit-lite** (no PR; audit report only): runtime-verified 3/5 of iter 1-8 shipped PRs (#445 factors O9 / #446 backtest O1 / #449 --inplace). All RUNTIME-TRUE; 0 production drift. Doc-rot LOW finding D-1 (DEV_FRONTEND_UI.md:319 stale approval endpoint listing — backlogged inline). Audit report `docs/audit/L4R_AUDIT_001_2026_05_23.md` committed `a940fe9`. LL-179 reality re-grounding satisfied — Inner-loop-B unblocked.
- **Iteration 10 — D1 O8 automation-level persistence** (Inner loop B + A): design `PN_001_automation_level_persistence.md` (`bde8864`) → PR #450 `d26ac2a` (singleton `pipeline_settings` table + GET/PUT `/api/pipeline/automation-level` + 5 backend pytest + 6 frontend vitest) → ADR-087 sediment `7b1fb66`.
- **Iteration 11 — D1 O10 factor correlation prune** (Inner loop B + A): design `PN_002_factor_correlation_prune.md` (`c4787c6`) → PR #451 `f47a6df` (analysis-only `POST /api/factors/correlation-prune` dry_run-only scope + IC-series Spearman + 5 mock pytest) → ADR-088 sediment `bea6cc2`.
- **Iteration 12 — D1 O3 pipeline pause gate** (Inner loop B + A): design `PN_003_pipeline_pause_gate.md` (`9ee9468`) → PR #452 `d406a8c` (POST /pause + /resume + `paused_at`/`paused_reason` cols + gate-at-entry in /trigger + run_gp_mining + run_bruteforce_mining + 6 backend pytest + 3 frontend vitest) → reviewer fix `94753c9` (P2 typing + fail-safe doc) → ADR-089 sediment `327266b`. Mid-run cooperative abort explicitly OUT OF SCOPE.

**commit / artifact**: 5 iters / 11 commits on main / 3 backend PRs squash-merged (#450/#451/#452) / 1 docs-direct (audit-001) / 1 XS-cleanup PR (#449) / 3 ADRs committed (087/088/089) / 3 design docs (PN-001/002/003) / 5 ADR-DRAFT rows promoted to committed.

**方向判断 (direction judgment)**
Inner-loop-B is **productive and sustainable** — 3 consecutive iter cycles (design + ADR-DRAFT + Inner-loop-A + reviewer fix + sediment) shipped real backend functionality without architectural drift, broker risk, or red-line touches. The pattern locks: smallest-design-first scope picking (per state RESUME ranking) + §6 8-trigger STOP self-check + §7 重蹈 defense grep + §4.5 written verdict + general-purpose reviewer subagent fallback (python-reviewer model-router gap sustained) + §14.2 rule 2 independent triage (1-3 reviewer findings declined per iter with explicit rationale, not auto-accepted). The §4.3 low-actionable concern from digest #2 was **wrong**: design-gated work *is* tractable when the design scope is constrained correctly (gate-at-entry pause, dry_run-only prune, single-column singleton persist — all small enough to bound design risk).

Frontend orphan cluster status: started session at 10 orphans; closed O2 (iter 1) / O9 (iter 3-4) / O1 (iter 5) / O8 (iter 10) / O10 (iter 11) / O3 (iter 12) = **6 of 10 closed**. Remaining: O7 log-history (medium-large, storage decision) + GET /pipeline/status contract refactor (small, mostly done via PN-001 + PN-003 status extensions) + D3 BruteForce gating-design (largest) + O4/5/6 already resolved by prior work pre-loop.

**下一步计划**: Iter 14 should be **research cycle 2** — `since_last_research_cycle=5` satisfies §9.1 anti-consecutive; RN-001 §7 owes web + arxiv source refresh (only GitHub releases hit last time). A second cycle (a) re-tests the §4.3 low-actionable hypothesis with fresh 2026-frontier sources, (b) rebalances implement:archive:defer ratio toward archive (8:2:3 = 62% vs current 67% trending up), and (c) lets the loop honestly check if the "build remaining D1 orphans" path still has value or if a strategic pivot is warranted. If research cycle 2 lands IMPLEMENT verdict for a specific candidate, iter 15+ executes; if ARCHIVE, iter 15 picks O7 or `/pipeline/status` contract refactor as the next smallest.

**与上次 digest 方向偏移**: Digest #2 predicted "loop approaching §4.3 low-actionable for clean autonomous work" — that was **falsified**. 3 design-implement cycles (iter 10/11/12) successfully shipped via Inner-loop-B without architecture escalation. Correction: design-scope constraint discipline (smallest first + explicit out-of-scope deferrals) keeps Inner-loop-B productive longer than digest #2 expected. The honest re-frame: the loop has high autonomous capacity *if* candidates are constrained to single-feature gate-at-entry / dry-run-only / persist-only scopes; large-scope work (D3 BruteForce, /pipeline/status full refactor) still requires product/architecture decisions.

**implement : archive : defer** — cumulative 8 : 1 : 3 (implement 67%, healthy band ceiling). Trending up since digest #2 (was 4:1:3 = 50%). Iter 13 = digest (this artifact, not impl). Iter 14 research cycle 2 → ARCHIVE verdict would rebalance to 8:2:3 = 62%.

**⚠️ user veto/redirect surface** (§4.1 — async, non-blocking): the loop has shipped 3 more backend PRs (#450/#451/#452) closing 3 frontend orphans (O8/O10/O3) + 3 ADR sediments (087/088/089). Cloud /schedule 1h fallback heartbeat armed (`trig_013qZ68B4G6WWPvFbm3r9nQk`). Web auto-archive identified as the local-session interruption root cause — desktop/CLI both work for 60-180s rapid fire. If you want the loop to (a) iter 14 = research cycle 2 (recommended — rebalances ratio + tests §4.3 hypothesis fresh), (b) iter 14 = D1 O7 log-history Inner-loop-B (storage-decision design), (c) iter 14 = `/pipeline/status` contract refactor (smallest cleanup, mostly done), (d) iter 14 = D3 BruteForce gating-design (largest, may surface architecture decision needing user), or (e) something else — say so. Otherwise the loop continues with research cycle 2 as the planned iter 14.
