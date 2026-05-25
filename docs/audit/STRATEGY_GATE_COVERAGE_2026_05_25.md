# Strategy Gate G1-G10 + G1'-G3' Test Coverage Audit (2026-05-25)

> **Scope**: Verify真 test coverage vs design spec for Factor Gates G1-G10 + Strategy Gates G1'/G2'/G3' (MVP 3.5 Eval Gate Framework, Wave 3 ✅ 完结).
> **Method**: 4-element cite (path + line# + section + 2026-05-25 fresh verify).
> **Verdict**: 3 drift findings — G5/G6/G7 explicitly out-of-scope but DEV_FACTOR_MINING.md design lists them; G3 paired-bootstrap helper has 6 dedicated tests not counted in pipeline; legacy `engines/factor_gate.py` G1-G8 (FactorGatePipeline, distinct from Platform pipeline) carries 50+ tests, partially overlapping.

---

## §1 Factor Gate G1-G10 Design Spec

| Source | Definition |
|---|---|
| CLAUDE.md:91 §因子评估流程 | 5. Gate G1-G8 + BH-FDR |
| CLAUDE.md:320 (铁律 12 T1) | G9 Gate 新颖性 AST 相似度 > 0.7 拒绝 (AlphaAgent KDD 2025) |
| CLAUDE.md:321 (铁律 13 T1) | G10 Gate 市场逻辑可解释性 — "市场行为→因子信号→预测方向" |
| docs/DEV_FACTOR_MINING.md:816-822 §13.1 | G1 IC均值 / G2 IC_IR / G3 IC胜率 / G4 单调性 / G5 半衰期 / G6 相关性 / G7 覆盖率 / G8 综合评分 (legacy `engines/factor_gate.py`) |
| docs/mvp/MVP_3_5_eval_gate_framework.md:40-47 §批1 | Platform 7 Gates: G1 IC t>2.5 / G2 corr<0.7 / G3 paired bootstrap / G4 OOS WF / G8 BH-FDR / G9 novelty AST / G10 hypothesis |
| MVP 3.5:78 Out-of-scope | G5/G6/G7 留 Wave 4+ (Platform pipeline 不含) |

**注**: 设计层存在 **两套 G1-G8 语义** (legacy `engines/factor_gate.py` 沿 DEV_FACTOR_MINING.md / Platform `qm_platform/eval/gates/` 沿 MVP 3.5). 编号同名但语义不同 (e.g. legacy G3 = IC胜率 vs Platform G3 = paired bootstrap).

## §2 Strategy Gate G1'-G3' Design Spec

| Source | Definition |
|---|---|
| MVP_3_5:69 §批3 | G1' Sharpe vs baseline paired bootstrap p<0.05 / G2' max drawdown < threshold / G3' regression max_diff=0 vs old PT (铁律 15) |
| MVP_3_5:108-111 §G3' | 新策略无 baseline → G3' SKIP (PASS, reasoning="no baseline") |
| docs/adr/ADR-014-evaluation-gate-contract.md | 锁 G1-G10 + Strategy G1'-G3' 契约 (Wave 4+ 不可破坏) |

## §3 真 Test File Inventory (2026-05-25 fresh grep)

### Platform Pipeline Factor Gates (MVP 3.5 批1, qm_platform/eval/gates/)

| Gate | Implementation | Test file | 真 test fn 数 |
|---|---|---|---|
| G1 IC t>2.5 | `g1_ic_significance.py` | `test_evaluation_pipeline.py:107,117` | 2 |
| G2 corr<0.7 | `g2_corr_filter.py` | `test_evaluation_pipeline.py:128,134` | 2 |
| G3 paired bootstrap | `g3_paired_bootstrap.py` | `test_evaluation_pipeline.py:144,155` | 2 |
| G4 OOS WF | `g4_oos_walkforward.py` | `test_evaluation_pipeline.py:165,172` | 2 |
| G5 | OUT-OF-SCOPE (MVP_3_5:78) | — | 0 |
| G6 | OUT-OF-SCOPE | — | 0 |
| G7 | OUT-OF-SCOPE | — | 0 |
| G8 BH-FDR | `g8_bh_fdr.py` | `test_evaluation_pipeline.py:181,187` | 2 |
| G9 novelty AST | `g9_novelty_ast.py` | `test_evaluation_pipeline.py:224,237` | 2 |
| G10 hypothesis | `g10_hypothesis.py` | `test_evaluation_pipeline.py:252,261` | 2 |
| Helper (paired_bootstrap_pvalue / newey_west / BH thresh) | `eval/utils.py` | `test_evaluation_pipeline.py:39-99` | 7 |
| Pipeline 顶层 (verdict / report / decision / safe_evaluate / immutable / p2_1 vectorize) | `pipeline.py` | `test_evaluation_pipeline.py:303-434` | 11 |
| **Platform G1-G10 总计 (含 helper + pipeline)** | — | `test_evaluation_pipeline.py` | **32** |

### Platform Strategy Gates (MVP 3.5 批3, qm_platform/eval/strategy_gates.py)

| Gate | Class | Test file | 真 test fn 数 |
|---|---|---|---|
| G1' Sharpe paired bootstrap | `StrategyG1SharpeGate` | `test_strategy_eval_gates.py:29,42,55` | 3 |
| G2' max drawdown | `StrategyG2MaxDrawdownGate` | `test_strategy_eval_gates.py:67,78,89` | 3 |
| G3' regression max_diff=0 | `StrategyG3RegressionGate` | `test_strategy_eval_gates.py:102,110,122,135` | 4 |
| StrategyEvaluator 顶层 (all-pass / sim-to-real 3 cases) | — | `test_strategy_eval_gates.py:151,175,186,196` | 4 |
| Pipeline / 默认 threshold / immutable | — | `test_strategy_eval_gates.py:209,218,226` | 3 |
| **Strategy G1'-G3' 总计** | — | — | **17** |

### Lifecycle Integration (MVP 3.5 批2)

| 区块 | Test file | 真 test fn 数 |
|---|---|---|
| default pipeline + context + dual-path compare | `test_factor_lifecycle_eval_integration.py:28-201` | 16 |

### Legacy Factor Gate (engines/factor_gate.py G1-G8, DEV_FACTOR_MINING.md 语义)

| 区块 | Test file | 真 test fn 数 |
|---|---|---|
| G1-G8 + BH-FDR + Newey-West + G6/G7/G8 confirm + V11 integration | `test_factor_gate.py` (all) | 56 |

### Onboarding G8/G9/G10 (MVP 1.3c register())

| 区块 | Test file | 真 test fn 数 |
|---|---|---|
| upsert_registry G9/G10 + active corr + G8 auto-assist | `test_factor_onboarding_gates.py` | 19 |

### Smoke (铁律 10b)

| File | 用途 |
|---|---|
| `test_mvp_3_5_batch_1_live.py` | 批1 Platform pipeline live |
| `test_mvp_3_5_batch_2_live.py` | 批2 lifecycle live |
| `test_mvp_3_5_batch_3_live.py` | 批3 strategy gates live |
| `test_mvp_3_5_1_live.py` | 3.5.1 follow-up (PR #126) |

## §4 Drift Table (Design vs Actual)

| Item | Design (MVP_3_5) | Actual (2026-05-25 fresh) | Drift | 影响 |
|---|---|---|---|---|
| 批1 unit tests | ~22 (line 50) | 32 | +10 (+45%) | benign (additional p1/p2 reviewer tests) |
| 批2 unit tests | ~15 (line 63) | 16 | +1 | benign |
| 批3 unit tests | ~10 (line 73) | 17 | +7 (+70%) | benign (sim-to-real coverage) |
| Platform G1-G10 (in-scope 7) | 7 gates | 7 gates ✅ | 0 | aligned |
| G5/G6/G7 Platform gates | OUT-OF-SCOPE Wave 4+ | 0 impl / 0 test ✅ | 0 | aligned with MVP_3_5:78 |
| Strategy G1'/G2'/G3' | 3 gates | 3 gates ✅ | 0 | aligned |
| ADR-014 锁契约 | 必产 | `docs/adr/ADR-014-evaluation-gate-contract.md` ✅ | 0 | aligned |
| Legacy `engines/factor_gate.py` G1-G8 | DEV_FACTOR_MINING.md spec | 56 tests / co-exists with Platform pipeline | 双套 G1-G8 语义共存 | 文档负担 (语义同名异义), 非测试 gap |

## §5 Recommendation

1. **No missing Platform tests** — MVP 3.5 三批 design count (~47) 实际 65 (+38%), 全部 P0/P1 reviewer findings 已采纳 (per MVP_3_5:8-10 PR #123/#124/#125 merged).
2. **G5/G6/G7 Platform gates** — 设计明确 Wave 4+ deferred, 不构成 drift. Wave 4 全 ✅ 完结 (2026-05-25), 但未启动 G5/G6/G7 自动化 (MVP_3_5:148 Follow-up 1 仍 open).
3. **双套 G1-G8 语义文档负担** — Legacy `engines/factor_gate.py` (DEV_FACTOR_MINING.md:816-822 编号: G3=IC胜率) 与 Platform `qm_platform/eval/gates/` (MVP_3_5: G3=paired bootstrap) 编号冲突. 建议 ADR-014 §术语表 显式标注 "Legacy G1-G8 ≠ Platform G1-G10", 或将 legacy 重命名为 L1-L8 sunset.
4. **Smoke coverage** — 3 批 smoke + 1 follow-up smoke 全在位, 沿铁律 10b.
5. **No orphan tests** — 全部 G1-G10 + G1'-G3' test 均映射到 implementation 文件, 无 zombie.

## §6 4-Element Cite Source

| Cite | Path | Line# | Section | Fresh verify (2026-05-25) |
|---|---|---|---|---|
| 1 | `CLAUDE.md` | 91, 320, 321, 340 | §因子评估流程 / 铁律 12 / 铁律 13 / 铁律 20 | ✅ grep verified |
| 2 | `docs/DEV_FACTOR_MINING.md` | 816-822 | §13.1 Factor Gate 8项检验 | ✅ grep verified |
| 3 | `docs/mvp/MVP_3_5_eval_gate_framework.md` | 8-10, 40-47, 69, 78 | §进度 / §批1 / §批3 / §Out-of-scope | ✅ Read verified |
| 4 | `backend/tests/test_evaluation_pipeline.py` | 39-434 | 32 test fns | ✅ Grep verified |
| 5 | `backend/tests/test_strategy_eval_gates.py` | 29-226 | 17 test fns | ✅ Grep verified |
| 6 | `backend/tests/test_factor_lifecycle_eval_integration.py` | 28-201 | 16 test fns | ✅ Grep verified |
| 7 | `backend/tests/test_factor_gate.py` | 73-569 | 56 legacy test fns | ✅ Grep verified |
| 8 | `backend/qm_platform/eval/gates/` | g1-g10 files | 7 Platform gate impls | ✅ Glob verified |
| 9 | `docs/adr/ADR-014-evaluation-gate-contract.md` | — | ADR-014 lock contract | ✅ Glob verified |

红线 5/5 sustained: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / no commit/push.
