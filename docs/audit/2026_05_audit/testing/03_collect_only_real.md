# Testing Review — pytest collect-only 真测 + smoke/regression real

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / testing/03
**Date**: 2026-05-01
**Type**: 评判性 + pytest 真 count

---

## §1 真测 (CC 5-01 pytest --collect-only 实测)

实测 cmd:
```
cd D:/quantmind-v2
.venv/Scripts/python.exe -m pytest backend/tests --collect-only -q
.venv/Scripts/python.exe -m pytest backend/tests -m smoke --collect-only -q
.venv/Scripts/python.exe -m pytest backend/tests -m regression --collect-only -q
```

**真值**:

| 维度 | 真测 count | sprint period sustained | 漂移 |
|---|---|---|---|
| **总 tests collected** | **4076** ✅ | sprint state "2864 pass / 24 fail (Session 9 baseline)" | **+1212 (+42%) 真漂移** |
| **smoke (pytest -m smoke)** | **61** ✅ | sprint period sustained "smoke 28 PASS" | **+33 (+118%) 真漂移** |
| **regression (pytest -m regression)** | **0** (no tests collected, 4076 deselected) | sprint period sustained "regression 5yr+12yr max_diff=0" | **🔴 0 marker 真存在** |

实测 pytest warning 真证据:
```
test_outbox_4domain_integration.py:288: PytestUnknownMarkWarning:
Unknown pytest.mark.integration - is this a typo?
```

---

## §2 🔴 重大 finding — regression marker 真 0 测试

**真测**: `-m regression` 真 0 tests collected, 4076 全 deselected.

**真根因**:
- 真 4076 tests 中 0 标记 `@pytest.mark.regression`
- sprint period sustained "regression 5yr+12yr max_diff=0" 是 **scripts/run_backtest.py + cache/baseline_*.json 走的, 不是 pytest -m regression**
- → 真 pytest regression marker 真**0 sustained 沉淀** sustained sustained sprint period sustained 沉淀 "regression baseline 5yr+12yr max_diff=0" 但 真**通过 pytest 0 reproducibility** sustained

**🔴 finding**:
- **F-D78-246 [P0 治理]** pytest -m regression 真 0 tests collected, sprint period sustained "regression baseline 5yr+12yr max_diff=0" 真**通过 pytest 0 reproducibility** sustained, 真 regression baseline 真路径 = scripts/run_backtest.py + cache/baseline JSON, 不是 pytest test runner. 沿用 sprint period sustained ADR-022 §22 + 铁律 15 sustained 真断 真证据 (regression baseline 真审 0 自动化 sustained pytest 内)

---

## §3 测试基线漂移真测 (sustained F-D78-76 加深)

| sprint period sustained | 真测 5-01 | 漂移 |
|---|---|---|
| 2864 pass / 24 fail | 4076 collected (含 fail+skip) | **+42% / +1212 漂移** |
| smoke 28 PASS | 61 smoke collected | +118% / +33 漂移 |

**🔴 真证据 sustained F-D78-76 + F-D78-147 加深**: 测试基线 sprint period sustained 沉淀数字真 stale ~2 week, sprint state Session 9 数字 (4-19) 真**未 update**, sustained F-D78-17 P2 sustained "handoff 写入层 0 enforce" 真证据 (handoff 数字必 SQL/pytest verify before 写候选 0 sustained)

**finding**:
- F-D78-247 [P2] sprint period sustained "smoke 28 PASS" 真测 61 smoke collected = 真 +118% 漂移, sustained F-D78-76 + F-D78-147 同源 测试基线漂移真证据 sustained verify

---

## §4 警告 - integration marker 未 register

实测 pytest warning:
```
PytestUnknownMarkWarning: Unknown pytest.mark.integration
```

**真测**: pytest 真 integration marker 真**未在 pyproject.toml/pytest.ini register** sustained, 真 silent skip + warning 累积 sustained sprint period sustained.

**finding**:
- F-D78-248 [P3] pytest.mark.integration 真未 register, sustained warning 累 sustained sprint period sustained sustained, sustained 铁律 33 silent_failure 同源 候选

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-246** | **P0 治理** | pytest -m regression 真 0 tests, regression baseline 真**通过 pytest 0 reproducibility** sustained |
| F-D78-247 | P2 | smoke 28→61 +118% 漂移, 测试基线 sprint period sustained 数字真 stale 2 week |
| F-D78-248 | P3 | pytest.mark.integration 真未 register, warning 累积 |

---

**文档结束**.
