# Testing Review — 测试金字塔真分布 (sustained testing/01)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 4 / testing/02
**Date**: 2026-05-01
**Type**: 评判性 + 测试金字塔真比例 (sustained testing/01 §3 F-D78-78 P2)

---

## §1 真测 (CC 5-01 实测)

实测 sprint period sustained sustained:
- pytest 4076 tests collected (testing/01 §1)
- 266 test_*.py files (snapshot/01 §1)

候选拆分维度 (本审查 partial):
- unit / integration / smoke / E2E
- by directory: backend/tests/* / backend/tests/smoke/* / backend/tests/integration/*
- by mark: @pytest.mark.slow / @pytest.mark.integration / 等

---

## §2 测试金字塔分布候选 (沿用 sprint period sustained)

实测 sprint period sustained sustained:
- "smoke 28 PASS" (CLAUDE.md sustained sustained, sprint state Session 9)
- "regression 5yr+12yr max_diff=0" (sustained 铁律 15 sustained)
- "100+ test files" (CLAUDE.md sustained sustained)
- 真 4076 tests (testing/01 sustained)

**真测金字塔候选** (本审查未深查):
- unit: 大头 (估 ~80%)
- integration: 中 (估 ~10-15%, sustained 3 unknown @pytest.mark.integration F-D78-77 候选)
- smoke: 28 sustained (CLAUDE.md sustained sustained)
- regression: 5yr+12yr 2 baseline (cache/baseline/regression_result_5yr.json + 12yr)
- E2E: 0 sustained sustained (CLAUDE.md "不做浏览器端到端测试" .claude/rules/quantmind-overrides.md sustained sustained)

候选 finding:
- F-D78-167 [P2] 测试金字塔真分布候选 (4076 tests by 类别 unit/integration/smoke/regression/E2E) 0 sustained sustained 真测度量, 沿用 testing/01 §3 F-D78-78 P2 sustained
- F-D78-168 [P3] E2E 测试 0 sustained (sustained .claude/rules/quantmind-overrides.md sustained "不做浏览器 E2E"), candidate 真生产 4-29 PT 暂停事件类 E2E 测试 candidate 缺 (沿用 F-D78-115/116/146 真生产 enforce 失败 cluster — E2E candidate 防 4-29 类事件)

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-167 | P2 | 测试金字塔真分布候选 (4076 tests by 类别) 0 sustained 真测度量 |
| F-D78-168 | P3 | E2E 测试 0 sustained, candidate 真生产 4-29 类事件 E2E 测试 candidate 缺 |

---

**文档结束**.
