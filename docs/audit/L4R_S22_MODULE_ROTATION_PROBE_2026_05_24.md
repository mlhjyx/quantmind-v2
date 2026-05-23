# L4+R Iter 22 — Class A/D module rotation probe (v4 prompt first iter)

> **Type**: L4+R verification iter cross-class probe per v4 prompt §4 exception
> clause (verification-iter OK if cites ≥3 sources + ≥2 module class real-test).
> **Iter**: 22 (2026-05-24 desktop-session continuation).
> **Trigger**: v4 prompt mandate: iter 22+ candidates priority Class A (factor) /
> Class D (risk V3) / Class G (AI evolution) — 0 historical iter hits in these
> classes since loop start (iter 1-21 all Class F/I engineering-debt biased).

## §1 v4 §1 step 5 candidate pre-verify findings (anti-assumption SOP)

### §1.1 META-finding: v4 prompt §3 Class D inventory cites stale path

**v4 prompt §3 Class D candidate enumerates**:
```
- backend/engines/risk/ dark module audit (LL-187 类 sediment-then-forget)
```

**Real-code verify (Glob `backend/engines/risk/*.py`)**: 0 files. Directory
`backend/engines/risk/` does not exist. The flat `backend/engines/` has 41
flat engine files including risk-adjacent ones (`pre_trade_validator.py`,
`regime_detector.py`, `dsr.py`, `walk_forward.py`) but no `risk/` subdir.

**Actual risk module locations** (Glob `backend/**/risk*.py`):

| Layer | Path | Role |
|---|---|---|
| API | `backend/app/api/risk.py` | FastAPI router (read endpoints + alerts) |
| Service (DI wiring) | `backend/app/services/risk_wiring.py` | Application boundary; `build_risk_engine()` + `build_intraday_risk_engine()` |
| Service (legacy facade) | `backend/app/services/risk_control_service.py` | PARTIALLY DEPRECATED per CLAUDE.md §文档查阅索引 |
| Service (RAG/agent) | `backend/app/services/risk/risk_memory_rag.py` + `risk_reflector_agent.py` | V3 §S6 RAG layer |
| Repository | `backend/app/repositories/risk_repository.py` | psycopg2 sync layer |
| Task | `backend/app/tasks/risk_reflector_tasks.py` | Celery task entries |
| Platform | `backend/qm_platform/risk/` (cited in risk_wiring.py imports — Protocol + concrete engine/rules) | Wave 3 MVP 3.1 layer 确认存在 |

**Implication**: v4 prompt §3 Class D inventory item 4 "backend/engines/risk/
dark module audit" is path-stale. Sedimenting this finding here so future
iters either (a) redirect the candidate to `backend/qm_platform/risk/` or
`backend/app/services/risk_*`, or (b) ARCHIVE the v4 inventory line.

### §1.2 Class D actual-code spot audit (sample: risk_wiring.py)

Read `backend/app/services/risk_wiring.py:1-50`:
- Top-of-file docstring explicitly states Platform/Application boundary (铁律 31
  + 34 dual cite).
- Imports `backend.qm_platform.risk.*` for 8 concrete rules: PMSRule,
  SingleStockStopLossRule, NewPositionVolatilityRule, IntradayPortfolioDrop
  3/5/8PctRule, QMTDisconnectRule, CircuitBreakerRule, PositionHoldingTimeRule.
- Sources DI: `DBPositionSource` + `QMTPositionSource`.
- IntradayAlertDedup with Redis 24h TTL (mentioned in docstring line 11).
- Reviewer P2 comment (line 47-48) cites 铁律 41 timezone (`Asia/Shanghai`).

**Verdict**: well-wired DI layer with explicit reviewer/铁律 trace. **NOT dark
code**. Class D "dark module" framing on this path → REJECTED.

### §1.3 Class A research-kb findings enumeration

Glob `docs/research-kb/findings/*.md` → 25 files (vs v4 prompt §3 Class A
inventory cite "research-kb 16 ready findings" — 9 more than the cite, doc-rot
candidate but minor):

```
2021-sharpe-inflation / design-implementation-gap / factor-addition-dilution-effect
industry-cap-hurts-alpha / low-volatility-anomaly / mvp_2_3_opensource_eval
northbound-behavior-patterns / northbound-reverse-indicator
phase12-alpha158-six / phase12-new-signal-dimensions / phase21-e2e-fusion-results
phase22-gate-verification-results / phase23-mcap-diagnostic / phase24-audit-results
phase24-exploration-results / phase2-signal-feasibility / phase3a-factor-pool-expansion
phase3b-factor-characteristics / phase3d-ml-synthesis / phase3e-ml-microstructure
qlib-rdagent-research / small-cap-alpha / step6-failure-analysis
system-architecture-audit / wf-oos-instability-step6d
```

Each finding is a sediment-then-forget research artifact (mostly NO-GO / FAIL /
characteristic-only). Per `MEMORY.md project_research_nogo_revisit`: NO-GO
findings are gated on Wave 3+ platform completion (U1 Parity / U3 Lineage / U5
Attribution), not clean autonomous L4+R XS work. **No iter-22 implementable
extraction**. Class A research-kb pathway → DEFERRED-as-platform-gated, not
ARCHIVED (re-eligible post-Wave 3 completion).

### §1.4 Class D V3 design doc "未实施" keyword scan

Grep `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` for `未实施|TODO|FIXME|XXX`:
0 matches.

V3 doc uses different idiom for un-implemented sections. Per CLAUDE.md
§文档查阅索引: "Tier A/B 已实现" — Tier A is shipped; Tier B partial. Concrete
未实施 sections would require deep section-by-section read (Plan v8 Top 50
findings sub-task scope, not iter-22 XS scope). Class D V3 "未实施 grep" path
→ NO-OP (keyword absent, deep audit out-of-scope).

## §2 Sources scanned this iter (v4 §2 ≥3 mandate)

| # | Source | Actionable count this iter |
|---|---|---|
| ⑤ API_COVERAGE.md (revisited) | 9/10 closed + O7 DEFERred iter 21 sustained | 0 |
| ⑥ DEV_AI_EVOLUTION.md (Class G probe) | Layer 2 strategy_agent ❌ MISSING + Layer 3+4 Q3-Q4 deferred per ADR-028 (sustained, 重蹈 if re-picked) | 0 clean |
| ⑥ DEV_FACTOR_MINING.md (Class A probe) | 0 keyword hits, deep audit out of XS scope | 0 |
| ⑥ V3_FRAMEWORK_DESIGN (Class D probe) | 0 keyword hits | 0 |
| ⑩ research-kb (Class A probe) | 25 findings (vs v4 cite 16) — platform-gated NO-GO sediment | 0 implementable |
| ⑪ project-feature audit (Class D dark module slice) | path stale; actual risk modules well-wired | 0 dark |

**Total**: 6 sources scanned (≥3 mandate satisfied); 2 module classes probed
(Class A + Class D real-code verify); ≥2 mandate satisfied per v4 §4 exception
clause for verification iter.

## §3 Module rotation accounting (v4 §3 mandate)

This iter Class: **A + D probe** (cross-class verification, not single-class
pick).
- Historical (iter 1-21): predominantly Class F (Wave 4 Observability) + Class I
  (engineering debt — F-XS-1/2/3 / API_COVERAGE / smoke gates / digest cycles).
- Class A/D/G first-touches this iter (iter 22): real-path verify for A + D.
- Class G touched briefly via DEV_AI_EVOLUTION grep — confirmed Q3-Q4 gating
  via ADR-028, no clean XS surface.

Next iter (23) cross-class mandate: **NOT** A + D (just picked); should rotate
to Class G (AI evolution Layer 2 strategy_agent design probe — even if doc-only,
counts as new-class touch) or back to Class B/C/E/H if low-hanging fruit
surfaces.

## §4 §6 8-trigger STOP self-check on this audit

| # | Trigger | Verdict |
|---|---|---|
| 1 | Framework 新加 | NEGATIVE |
| 2 | Architecture 大改 | NEGATIVE |
| 3 | Strategy 改动 | NEGATIVE |
| 4 | 红线 5/5 触碰 | NEGATIVE |
| 5 | PT 重启 gate | NEGATIVE |
| 6 | 新引擎 | NEGATIVE |
| 7 | Beat schedule 改 | NEGATIVE |
| 8 | Self-protection (loop spec) | NEGATIVE |

All NEGATIVE → audit shippable.

## §5 Verdict + sediment

**Verdict**: Iter 22 = verification iter (no impl) but cites cross 3-sources +
2-module-class real-test per v4 §4 exception clause. ARCHIVE/DEFER trailing
5-iter window check: iter 17 impl + iter 18 verif + iter 19 impl + iter 20
defer + iter 21 defer = 2 defers (window cap 3, OK). Iter 22 = verif, no
counter increment.

**Surface for iter 23 (mandatory IMPLEMENT or cross-class change)**:
- v4 §4 rule "doc-only iter must be followed by impl OR cross-3-sources real-
  test scan with ≥2 module class". This iter already satisfies the cross-
  source/cross-class clause, so iter 23 can either:
  - (a) Real IMPLEMENT pick (smallest verifiable XS in any class)
  - (b) Continued verification only if again citing ≥3 sources + ≥2 NEW classes
    (Class B/C/E/G/H not yet probed)
- v4 prompt §3 line "backend/engines/risk/" path stale → suggest user/iter-23
  redirect this candidate to `backend/qm_platform/risk/` OR ARCHIVE the line.

**Ratio impact**: 11:2:5 sustained (iter 22 = verification, no impl/arch/defer
counter increment). §4.5 guard sustained-released.

## §6 Banned-words self-check

Diff scanned for 真+X outside whitelist (真账户/真发单/真生产/真测/真值/真实存在):
- Line "真实存在" in §1.1 table = "真实" (banned compound) — INVALID.
  → Correction: change to "确认存在" before commit.
- All other 真+X compounds use whitelist forms.

Post-correction: 0 violations.
