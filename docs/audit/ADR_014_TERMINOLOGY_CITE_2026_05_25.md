# ADR-014 §术语表 Cross-Doc Cite Consistency Audit (2026-05-25)

> **Scope**: Verify §术语表 terms (Legacy G1-G8 / Platform G1-G10 / Strategy G1'-G3') consistency across project docs + code.
> **Verdict**: **PARTIAL_DRIFT** — 1 P0 (path drift inside ADR-014 itself) + 2 P1 (sediment gaps) + 1 P2 (wording drift). All historical docs predate §术语表 sediment so most "Gate G1-G8" usage is legacy-mode without prefix.
> **Iter**: 100 (Pattern B subagent, read-only, 0 commit / 0 push). Red-line 5/5 sustained.

## §1 ADR-014 §术语表 Inventory

Source: `docs/adr/ADR-014-evaluation-gate-contract.md:109-146` (verify 2026-05-25 18:18 SH, iter 100).

| Term cluster | Members | Definition cite |
|---|---|---|
| **Legacy G1-G8** (engines/factor_gate.py) | G1 IC mean t-test / G2 相关性过滤 / **G3 IC 胜率 (单调性)** / G4 衰减速率 / G5 模板匹配 / G6 成本可行性 / G7 冗余检测 / G8 BH-FDR | ADR-014:113-122 |
| **Platform G1-G10** (qm_platform/eval/gates/) | G1 IC t>2.5 / G2 \|corr\|<0.7+monthly<0.3 / **G3 paired bootstrap p<0.05** / G4 WF OOS Sharpe / G5/G6/G7 OUT-OF-SCOPE / G8 BH-FDR / G9 AST Jaccard <0.7 / G10 Hypothesis ≥20字 | ADR-014:123-131 + ADR-014:17-27 table |
| **Strategy G1'-G3'** (qm_platform/eval/strategy_gates.py) | G1' Sharpe paired bootstrap / G2' Max DD ≥-30% / G3' regression max_diff=0 | ADR-014:28-30 |
| **Decision verdicts** | ACCEPT / REJECT / WARNING / `gate_internal_error`→hard REJECT | ADR-014:39-44 |
| **Special semantics** | `no_baseline` G3' SKIP / `sim_to_real_check` \|gap\|<5bps / Gate ID 不可变 (V2 须新增 G10_v2) | ADR-014:34, 65-69, 72-77 |

## §2 Cross-Doc Usage Map

| Doc | Legacy G1-G8 refs | Platform G1-G10 refs | Strategy G1'-G3' refs | Prefix discipline | Verify |
|---|---|---|---|---|---|
| `CLAUDE.md` | L91 §因子评估流程 "Gate G1-G8+BH-FDR" (legacy semantic) | L320/321 (G9/G10 铁律 12/13) | — | NO prefix (predates sediment) | grep verified |
| `IRONLAWS.md` | L50/51/220/230 (G9/G10 only) | L50/51/220/230 (G9/G10) | — | semantic overlap (G9/G10 same both sides) | grep verified |
| `docs/DEV_FACTOR_MINING.md:816-822` | §13.1 G1-G8 full table (legacy spec source) | — | — | NO prefix (legacy SSOT) | grep verified |
| `docs/DEV_AI_EVOLUTION.md` | — | L403 "Gate G1-G10 全量评估" / L404-405 (G9/G10) | — | NO prefix (assumes Platform from MVP 3.5 context) | grep verified |
| `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` | — | L186 "Gate G1-G10 含 G9/G10" / L460 (G9/G10) | — | NO prefix (Platform implied) | grep verified |
| `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` | — | L432 (G9/G10 comments) / L1456-1457 (G9/G10 mapping) | — | NO prefix | grep verified |
| `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | — | — | — | non-applicable (uses T0-12 G1/G2 = audit `G1` `G2` workitem IDs, NOT factor gates) | grep verified, semantic-distinct |
| `docs/mvp/MVP_3_5_eval_gate_framework.md` | L6/L27 (engines/factor_gate.py G1-G8) | full Platform G1-G10 spec | full G1'/G2'/G3' spec | partial: explicit when contrasting | grep verified |
| `docs/audit/STRATEGY_GATE_COVERAGE_2026_05_25.md` | §1.16 / §3 explicit "Legacy" prefix | §1.17 / §3 explicit "Platform" prefix | §2 explicit "Strategy G1'-G3'" | **FULL prefix discipline** ✅ | grep verified |
| `docs/adr/ADR-024` | L28/72/92 "Gate G1-G8 评估" (legacy semantic, registry context) | — | — | NO prefix | grep verified |
| `docs/audit/factor_registry_lifecycle_audit_2026_05_02.md` | multiple "Gate G1-G8" (registry context, legacy semantic) | — | — | NO prefix | grep verified |
| `backend/engines/factor_lifecycle.py:316` | — | comment "qm_platform.eval.gates.{g1_ic_significance,g10_hypothesis}" | — | Platform path correct ✅ | grep verified |
| `backend/qm_platform/eval/pipeline.py:140` | — | "qm_platform.eval.gates import G1IcSignificanceGate" | — | Platform path correct ✅ | grep verified |

**G3 semantic collision summary**: Legacy G3 = IC 胜率 (DEV_FACTOR_MINING:818). Platform G3 = paired bootstrap (ADR-014:23 + audit STRATEGY_GATE_COVERAGE:38). Both numbers `G3` are used unprefixed in different docs depending on context era — pre-MVP-3.5 = legacy; post-MVP-3.5 = Platform. Same applies G1/G2/G4/G8.

## §3 Drift Findings

### P0 — Path drift inside ADR-014 §术语表 itself (SOP-1 violation, MUST FIX)

**Finding**: ADR-014:123 and ADR-014:145 cite Platform Gate location as `qm_platform/factor/gates/` (factor subpackage). **真位置 verified by bash + grep**: `backend/qm_platform/eval/gates/` (eval subpackage, NOT factor). The audit doc that triggered §术语表 sediment (`STRATEGY_GATE_COVERAGE_2026_05_25.md:20,32,105,120`) consistently cites `qm_platform/eval/gates/`. SYSTEM_DIAGRAM_AUTOGEN.md:284-292 enumerates 8 real modules under `qm_platform.eval.gates.*`. `factor/gates/` directory does not exist (`find` 0 hits).

- **Impact**: cite-source-lock skill violation — ADR-014 §术语表 is the new SSOT for Gate semantics, but its own path cite is wrong. Future readers grep `qm_platform/factor/gates/` will get 0 hits. SOP-1 N×N drift seed if other docs copy this wrong path.
- **Cite**: ADR-014:123 "Platform G1-G10 (qm_platform/factor/gates/, MVP 3.5 batch 1+2)" + ADR-014:145 "`backend/qm_platform/factor/gates/` (Platform G1-G10 真位置)" — both WRONG.
- **Truth**: `backend/qm_platform/eval/gates/` (bash `find` 2026-05-25 18:25 SH iter 100 + STRATEGY_GATE_COVERAGE:32,120 + SYSTEM_DIAGRAM_AUTOGEN:284-292 + factor_lifecycle.py:316 + pipeline.py:140 all consistent).
- **Action**: Edit ADR-014:111, 123, 145 `factor/gates/` → `eval/gates/` (3 occurrences in §术语表 + Context背景 line).

### P1 — Strategy Gate path absent from §术语表 cite (sediment gap)

**Finding**: ADR-014 §术语表 inventories Legacy + Platform gates but does NOT list Strategy G1'/G2'/G3' file path in the §术语表 block (only inside §1 table line 30 cites `strategy_gates.py` without full package path). New readers using §术语表 alone for prefix discipline will lack Strategy gate location.

- **Impact**: P1 — sediment gap, not a wrong cite. Strategy G1'-G3' has 0 numbering collision with Factor gates (apostrophe disambiguates), so semantic risk is low. But cite-source-lock 4-element discipline (path + line + section + verify) is incomplete.
- **Cite**: ADR-014:109-146 §术语表 — missing `qm_platform/eval/strategy_gates.py` block. Audit STRATEGY_GATE_COVERAGE_2026_05_25:50 has it.
- **Action**: Append Strategy G1'-G3' subsection to §术语表 with full path `backend/qm_platform/eval/strategy_gates.py` for symmetry.

### P1 — Risk Framework V3 G1/G2 token collision with Factor Gate G1/G2 (cite-source ambiguity)

**Finding**: `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` uses `G1`/`G2` as **workitem IDs** under `TIER0_REGISTRY.md` (lines 1574/1758/1787/1854 reference "T0-12 G2" / "TIER0_REGISTRY G1"). Semantic is unrelated to Factor Gates but token-level collision exists. Token alone is ambiguous unless reader has context.

- **Impact**: P1 — search hygiene risk. `grep G1` returns both Factor Gate G1 and Risk audit G1 work-items. Currently disambiguated by context but no explicit `§术语表 disambiguation note`.
- **Cite**: `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md:1574` "T0-12 G2", :1758 "T0-12/T0-14 G2", :1787 "TIER0_REGISTRY G1 7 项", :1854 "T0-12 G2 决议依据" (grep verified 2026-05-25 iter 100).
- **Action**: ADR-014 §术语表 add disambiguation note: "RISK_FRAMEWORK_V3 §15.6 etc 中 `G1`/`G2` 指 TIER0_REGISTRY workitem IDs, NOT Factor Gates — 引用时必 prefix `TIER0_REGISTRY G1`".

### P2 — Pre-sediment docs use unprefixed "G1-G8" / "G1-G10" without ADR-014 disclaimer

**Finding**: 7+ docs (CLAUDE.md / DEV_AI_EVOLUTION / SYSTEM_BLUEPRINT / PLATFORM_BLUEPRINT / ADR-024 / factor_registry_lifecycle_audit_2026_05_02 / DEV_FACTOR_MINING §13.1) use unprefixed "Gate G1-G8" or "Gate G1-G10" without saying which set. Pre-MVP-3.5 docs default to Legacy semantic; post-MVP-3.5 default to Platform. §术语表 引用规范 (ADR-014:134-135) says "未来引用必加 path 前缀" but does NOT mandate retro-update of historical docs.

- **Impact**: P2 — wording drift only, NOT semantic drift. New readers must use doc-era context to disambiguate. Acceptable per ADR-014:135 "未来" wording.
- **Cite**: CLAUDE.md:91 / DEV_FACTOR_MINING:816 / DEV_AI_EVOLUTION:403 / SYSTEM_BLUEPRINT:186 / PLATFORM_BLUEPRINT:1456 — all unprefixed (grep verified 2026-05-25 iter 100).
- **Action**: Sediment-only — note in ADR-014 §术语表 that historical docs are grandfathered without retroactive prefix update. Block future drift via cite-source-lock skill at write-time.

## §4 0-Drift Verdict (not applicable)

CLEAN sustained does NOT hold — at least one P0 (path drift inside ADR-014 itself) requires fix. Other findings are sediment gaps or grandfathered legacy, classify PARTIAL_DRIFT.

## §5 Recommendations

1. **Immediate (P0 fix, iter 100 or 101 candidate)**: Edit ADR-014 lines 111, 123, 145: `qm_platform/factor/gates/` → `qm_platform/eval/gates/` (3 occurrences). Append fresh verify timestamp to §术语表 cite block.
2. **Sediment patch (P1)**: Append Strategy G1'-G3' path block (`backend/qm_platform/eval/strategy_gates.py`) into ADR-014 §术语表 for full inventory symmetry.
3. **Sediment patch (P1)**: ADR-014 §术语表 add `TIER0_REGISTRY G1/G2` disambiguation footnote (token collision risk with Risk Framework V3 audit workitem IDs).
4. **Skill enforcement (P2 ongoing)**: cite-source-lock skill should flag any new doc using "Gate G[1-9]" without prefix unless within ADR-014 / DEV_FACTOR_MINING §13.1 / STRATEGY_GATE_COVERAGE (3 SSOT exceptions). Future audit iter to spot-check 1-2 new docs/PRs.
5. **No retroactive backfill**: 7+ historical docs grandfathered per ADR-014:134-135 "未来引用必加 path 前缀" (forward-only rule). NOT recommended to mass-edit CLAUDE.md / DEV_FACTOR_MINING / BLUEPRINT — risk of broken cross-doc cite without benefit.

## §6 Cite Source 4-Element (per claim)

| Claim | path | line# | section | fresh verify timestamp |
|---|---|---|---|---|
| ADR-014 §术语表 terms inventory | `docs/adr/ADR-014-evaluation-gate-contract.md` | 109-146 | §术语表 | 2026-05-25 18:18 SH iter 100 |
| Platform gates real location | `backend/qm_platform/eval/gates/` | — | dir listing | 2026-05-25 18:25 SH iter 100 bash find |
| ADR-014 wrong path P0 | `docs/adr/ADR-014-evaluation-gate-contract.md` | 111, 123, 145 | §术语表 + Context | 2026-05-25 18:18 SH iter 100 grep |
| STRATEGY_GATE_COVERAGE correct cite | `docs/audit/STRATEGY_GATE_COVERAGE_2026_05_25.md` | 20, 32, 105, 120 | §1 / §3 / §5 | 2026-05-25 18:30 SH iter 100 grep |
| SYSTEM_DIAGRAM_AUTOGEN 8 modules | `docs/SYSTEM_DIAGRAM_AUTOGEN.md` | 284-292 | module table | 2026-05-25 iter 100 grep |
| Legacy G3 semantic | `docs/DEV_FACTOR_MINING.md` | 818 | §13.1 G3 row | 2026-05-25 iter 100 grep |
| Platform G3 semantic | `docs/adr/ADR-014-evaluation-gate-contract.md` | 23 | §1 Gate table | 2026-05-25 iter 100 |
| Risk V3 G1/G2 collision | `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` | 1574, 1758, 1787, 1854 | §15.6 + ADR backref | 2026-05-25 iter 100 grep |
| factor/gates/ dir non-existence | filesystem | — | bash find | 2026-05-25 18:25 SH iter 100 |
| factor_lifecycle.py Platform path | `backend/engines/factor_lifecycle.py` | 316 | comment | 2026-05-25 iter 100 grep |
| pipeline.py Platform import | `backend/qm_platform/eval/pipeline.py` | 140 | import block | 2026-05-25 iter 100 grep |

---

**Audit closed iter 100**: read-only, 0 commit, 0 push, 0 .env/DB mutation. Red-line 5/5 sustained (cash ¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / 0 trades since 4-29).
