# Backtest Review — Regression test 真状态

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / backtest/03
**Date**: 2026-05-01
**Type**: 评判性 + regression test 真验证 (sustained backtest/01 + 02)

---

## §1 regression baseline 真测 (CC 5-01 实测)

实测 sprint period sustained sustained:
- cache/baseline/regression_result_5yr.json (sustained 30 day 26 commits, governance/04 §1)
- cache/baseline/regression_result_12yr.json (sustained sprint period sustained sustained)
- configs/backtest_5yr.yaml (sustained snapshot/04+05+06 §3)
- configs/backtest_12yr.yaml + backtest_12yr_sn050.yaml

---

## §2 真 last-run timestamp 候选 verify

实测 sprint period sustained sustained:
- 真 regression 真 last-run timestamp 0 sustained sync update (F-D78-84 P2 sustained backtest/01 §1)
- 真 max_diff 真值 0 sustained sustained verify (F-D78-24 P3 sustained)

**finding** (sustained):
- F-D78-84 (复) [P2] regression test 真 last-run timestamp 0 sustained sync update, sprint period sustained sustained "5yr+12yr max_diff=0" sustained 但 真 last-run 时间漂移 candidate

---

## §3 regression baseline 30 day 26 commits 真活跃

实测 governance/04 §3.2:
- regression_result_5yr.json 30 day 26 commits sustained sustained
- 候选: regression baseline 真 update 频率 (~1 update/day) sustained sustained

候选 finding:
- F-D78-193 [P2] regression baseline 30 day 26 commits 真活跃 (~1 update/day), sprint period sustained sustained "max_diff=0 硬门" sustained 但 baseline 候选含 max_diff 漂移 candidate (sprint period 22 PR sustained baseline 候选 sync update)

---

## §4 历史 bug regression test 覆盖度

(沿用 [`backtest/02_correctness_deep.md`](02_correctness_deep.md) §5 sustained F-D78-145 P2 sustained sustained)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-84 (复) | P2 | regression test 真 last-run timestamp 0 sustained sync update |
| F-D78-193 | P2 | regression baseline 30 day 26 commits 真活跃, max_diff 候选漂移 candidate |

---

**文档结束**.
