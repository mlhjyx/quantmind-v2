# RN-001 — Research Cycle 1: Frontier Scan + Re-tread Defense

> **Type**: L4+R loop research note (`docs/L4R_LOOP_SPEC.md` §10 Inner loop B output).
> **Date**: 2026-05-22 · **Cycle**: 1 (first research cycle of the L4+R loop).
> **Budget**: within §9.2 (≤2-4h wall-clock). **Verdict**: see §5 — net **ARCHIVE**.

## §1 Question + scope

QuantMind V2's factor / strategy / portfolio-optimization space is heavily explored
and largely exhausted. This cycle asks: across the current (2025-2026) frontier, is
there anything genuinely new — **not** a re-tread of a documented project failure —
worth an implement or defer verdict? Scope (§8): (A) A-share quant factor/strategy/
backtest/risk; (B) quant-system engineering (data quality / observability / ML-ops /
governance / backtest-infra). Excluded: crypto / futures-HFT / options / forex /
intraday-tick.

## §2 Re-tread defense (§7) — documented-failure map

Compiled from `docs/research-kb/` (8 failed / 22 findings / 5 decisions), `CLAUDE.md`
"已知失败方向", `LESSONS_LEARNED.md`, and `memory/project_research_nogo_revisit.md`.

**Permanent-dead (mechanism-level disproof — do not revisit):** weight optimization
(risk-parity / min-variance / MVO — equal-weight already near-optimal for Top-N);
fixed-threshold per-stock stop-loss; vol-targeting / dynamic position sizing; PMS v2.0
portfolio-level protection; biweekly rebalance; E2E differentiable-Sharpe portfolio
optimization (sim-to-real gap 282%); linear regime detection (5 indicators p>0.05);
raw fundamental-level factors as monthly ranking.

**Conditional-fail (failed under current infra — revisit only post-platformization):**
ML synthesis (6 independent validations — best ML 0.54-0.60 vs equal-weight 0.87; root
cause = IC≈0.09 signal-quality ceiling, not model class); 5th factor into CORE3+dv_ttm
(8 P1 candidates all FAIL — "CORE3+dv_ttm = equal-weight alpha ceiling"); microstructure
factors equal-weight-added (factor-addition dilution effect); Qlib/RD-Agent data-layer
migration.

**Established findings that hold:** alpha is ~100% microcap (SN-off = 91.5% sub-¥10B);
alpha is decaying (FF3 32%→12%/yr); the strategy is regime-conditional (4/12 negative
years).

## §3 Frontier scan (§9.3 source refresh — PARTIAL this cycle)

- **GitHub releases (verified via API)**: RD-Agent v0.8.0 (2025-11) — still hard-requires
  Docker for backtest scenarios (the 2026-04 NO-GO blocker stands; `--no-check-docker`
  is only a partial health-check escape hatch). Qlib v0.9.7 (2025-08) — Parquet support
  + a DRAFT Data Health Checker (#1574); incremental infra, no alpha-methodology move.
- **Web search + arxiv**: **UNAVAILABLE this cycle** (search backend error; arxiv
  rate-limited). The frontier verdict therefore rests on the two GitHub facts + the
  project's own documented findings. A follow-up cycle must re-run the literature scan
  when search is restored — see §7.

## §4 Candidate verification (the decisive step)

A research-collection subagent proposed 7 candidates and ranked a scope-B top-3 as
"genuinely-new, implement-worthy". **Cross-verified against current code (`backend/
engines/`), all three were already built** — the subagent did not grep the engine layer:

| Subagent candidate | Verified current-code reality | Verdict |
|---|---|---|
| #1 "DSR + PBO at the WF gate — genuinely-new, no DSR/PBO" | **WRONG.** `engines/dsr.py` (`deflated_sharpe_ratio`, `interpret_dsr`) + `engines/metrics.py` already compute DSR in the standard `MetricsReport` (`deflated_sharpe`, with `num_trials` multiple-testing correction); `scripts/rolling_wf.py:182` already uses it; `backend/tests/test_dsr.py` covers it. DSR is fully built + wired + tested. | not-new |
| #2 "factor-decay early-warning monitor — genuinely-new" | **WRONG.** `engines/factor_decay.py` (`check_all_factors_decay`, `DecayLevel` L0-L3) is already run **daily** by `scripts/factor_health_daily.py` (the "因子衰减3级检测" section), which also writes `factor_ic_history.decay_level`. A production decay monitor already exists. | not-new |
| #3 "DB-level data-quality health-checker — genuinely-new" | Partially exists — `scripts/data_quality_check.py` is a registered schtask. A Qlib-style checker over the 3 large tables may add coverage, but the gap is unverified and incremental. | partly-exists |
| PBO at the gate | `engines/pbo.py::probability_of_backtest_overfitting` is **built + appears to have 0 callers (dark)**. The one semi-genuine finding. But `engines/metrics.py`'s DSR already applies the `num_trials` multiple-testing correction — the same statistical-rigor family — so PBO's marginal value over the wired DSR is low, and wiring it into the gate is a gate-design decision, not a clean build. | marginal |
| RD-Agent v0.8.0 re-eval | Re-tread of `qlib-rdagent-research.md` — Docker still required; ADR-013 already owns a time-boxed revisit. | defer (ADR-013) |
| Quarterly rebalance + Top-25~40 | `phase24` found these beat baseline but never WF-validated. Conditional-fail-revisitable; belongs to a strategy sprint, needs WF. | defer |
| GNN cross-sectional model | Re-tread of ML-synthesis (bottleneck is IC≈0.09, not model class). | archive |

## §5 Verdicts (§9.2 — non-open-ended)

- **A-share alpha frontier → ARCHIVE.** Nothing genuinely new. Every 2025-2026 alpha
  angle either re-treads a mechanism-level failure or hits the equal-weight dilution
  wall. The CORE3+dv_ttm ceiling is real; further alpha hunting is not justified until
  the platform provides U1 Parity / U5 Attribution (per `project_research_nogo_revisit.md`).
- **Scope-B "statistical-rigor" candidates → ARCHIVE.** The project already has the
  rigor machinery built and wired (DSR in the standard metrics report + WF; 3-level
  factor-decay run daily). No new build is warranted.
- **PBO-into-the-gate → DEFER (low priority).** `engines/pbo.py` is built-but-dark, but
  the wired DSR already covers multiple-testing rigor; wiring PBO is a marginal,
  design-decision item — recorded, not pursued.
- **RD-Agent re-eval / quarterly rebalance → DEFER** to their existing owners (ADR-013 /
  a future strategy sprint).
- Net cycle result: **ARCHIVE** — surveyed, nothing implement-worthy emerged. Per
  spec §4.5 an archive verdict is valid output ("防重蹈的弹药").

## §6 META-finding (sediment candidate)

This is the **fourth time this session** a research/backlog subagent surfaced
"genuinely-new" candidates that were already built (iter-2 verification: 4 stale items;
iter-6 re-scan: BruteForce mis-sized; iter-6 BruteForce dive; this cycle: top-3 all
already-built). Root cause: subagents that don't deep-grep `backend/engines/` produce
false-new candidates — QuantMind V2 has substantial built-but-not-obvious code (dark /
unwired modules). **Process correction**: any research/backlog candidate MUST be
code-grep-verified (`backend/engines/` + `scripts/` + callers) before any
implement/archive/defer verdict. LL-candidate for `LESSONS_LEARNED.md`.

## §7 Carry-forward

- **Source refresh INCOMPLETE**: web + arxiv literature scan must be re-run when search
  is restored. Until then `last_research_source_refresh` = "2026-05-22 partial (GitHub
  only)". The next research cycle (§9.1 — not consecutive; after ≥1 execute task) should
  complete the literature half.
- No design / ADR-DRAFT / implement step follows (verdict is ARCHIVE, not implement).
