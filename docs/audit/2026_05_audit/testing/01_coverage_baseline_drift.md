# Testing Review — Coverage Baseline + 真测 Drift

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / testing/01
**Date**: 2026-05-01
**Type**: 评判性 + 真测 pytest collect + sprint period sustained baseline drift

---

## §1 pytest 真测 (CC 5-01 实测)

实测命令:
```bash
cd backend && ../.venv/Scripts/python.exe -m pytest --collect-only -q
```

**真值**:
- **4076 tests collected in 1.44s**
- 3 PytestUnknownMarkWarning:
  - `pytest.mark.slow` (test_ml_engine.py:259) — Unknown mark
  - `pytest.mark.integration` (test_outbox_4domain_integration.py:288) — Unknown mark
  - `pytest.mark.integration` (test_outbox_publisher.py:414) — Unknown mark

---

## §2 🔴 重大 finding — sprint period sustained baseline drift

### 2.1 真测 vs sprint period sustained

| 源 | 数字 | 时间 |
|---|---|---|
| sprint period sustained CLAUDE.md §当前进度 | "测试基线: 2864 pass / 24 fail (Session 9 末实测)" | sustained sustained |
| sprint state Session 46 frontmatter | "新增 fail 禁合入 baseline 24" | sustained sustained |
| **CC 5-01 实测真值** | **4076 tests collected** | 5-01 04:30 |

**🔴 finding**:
- **F-D78-76 [P0 治理]** 测试基线数字漂移 +1212 tests since Session 9 baseline (4076 - 2864 = 1212 net new tests in sprint period). sprint period sustained 22 PR + Wave 3+4 测试新增 (MVP 3.1 65 tests / MVP 4.1 batch 1+2 / etc) sustained sustained sustained, **CLAUDE.md / sprint state baseline 2864 0 sync update**, 铁律 40 "新增 fail 禁合入 baseline 24" enforcement 候选漂移 (baseline 是 24 fail vs 2864 pass 的比例, 现在是 24 fail vs 4076 pass — 等比例 vs 等绝对值未明确)

### 2.2 unknown pytest mark (registration缺)

**finding**:
- **F-D78-77 [P3]** 3 unknown pytest mark (`slow` / `integration` ×2). pytest.ini / pyproject.toml mark registration 缺, 候选 pytest config drift sustained

---

## §3 测试金字塔比例 (沿用 framework §3.7)

(本审查未深查 unit / integration / E2E 真分布. 候选 finding):
- F-D78-78 [P2] 测试金字塔真比例未本审查 verify (4076 tests by 类别 unit/integration/E2E/smoke 真分布候选 sub-md 详查)

---

## §4 Coverage 真测 (line / branch / mutation)

(本审查未跑 pytest --cov, sprint period sustained sustained 沉淀 "100+ test files" sustained sustained.)

候选 finding:
- F-D78-79 [P2] coverage 三维度 (line / branch / mutation) 0 sustained 度量 in 本审查, sprint period sustained "测试基线 2864 pass / 24 fail" 仅 pass/fail count 非 coverage

---

## §5 flakiness audit (sustained 24 fail baseline)

(本审查未深查 24 fail baseline 真分类. 候选 finding):
- F-D78-80 [P2] sprint period sustained "24 fail baseline" 真分类 (flaky / 已知 stale / wontfix) 0 sustained, 候选 sub-md 详查

---

## §6 regression protection (历史 bug 覆盖度)

实测:
- mf_divergence regression (sprint period sustained) — 候选 grep verify
- Tushare 复权 regression (sprint period sustained) — 候选 grep verify
- RSQR NaN regression (sprint period sustained P0-4) — 候选 grep verify
- regression_test max_diff=0 (铁律 15 sustained) — 沿用 F-D78-24 真 last-run 未 verify

---

## §7 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-76** | **P0 治理** | 测试基线数字漂移 +1212 tests since Session 9 baseline (4076 vs 2864), 铁律 40 baseline 数字 0 sync update |
| F-D78-77 | P3 | 3 unknown pytest mark (slow / integration ×2), pytest config drift |
| F-D78-78 | P2 | 测试金字塔真比例未本审查 verify (4076 tests by 类别真分布) |
| F-D78-79 | P2 | coverage 三维度 (line / branch / mutation) 0 sustained 度量 |
| F-D78-80 | P2 | sprint period sustained "24 fail baseline" 真分类 0 sustained |

---

**文档结束**.
