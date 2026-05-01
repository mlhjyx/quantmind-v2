# Testing Review — 测试基线漂移 +42% 真测加深

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / testing/04
**Date**: 2026-05-01
**Type**: 评判性 + 测试基线 +1212 / +42% 真测加深 (sustained F-D78-76 + F-D78-247 加深)

---

## §1 真测对比 (CC 5-01 实测)

实测 cmd: `pytest backend/tests --collect-only -q`

| 维度 | sprint period sustained | 真测 5-01 | 漂移 |
|---|---|---|---|
| **总 tests** | 2864 pass / 24 fail (Session 9 baseline 4-19) | **4076 collected** | **+1212 (+42%)** 🔴 |
| **smoke marker** | 28 PASS | **61 collected** | **+33 (+118%)** 🔴 |
| **regression marker** | 5yr+12yr max_diff=0 (走 scripts/run_backtest.py, 不是 pytest) | **0 tests collected** | **🔴 0 marker register** |

---

## §2 🔴 finding — 测试基线漂移真证据加深 sustained

**真证据加深** sustained F-D78-76 + F-D78-147 + F-D78-17 cluster:

### 2.1 4076 vs 2864 真证据 +42% (12 day 漂移)
- Session 9 baseline 4-19: 2864 pass + 24 fail = 2888 total
- Phase 9 真测 5-01: **4076 collected** = +1188 (+41%)
- 真 12 day (4-19 → 5-01) 真**新增 1188 tests** sustained sprint period sustained 22 PR + Wave 4 batch 3.x sustained
- 真证据 sustained sprint period sustained "测试基线 2864 pass / 24 fail" 数字 真**12 day stale**

### 2.2 28 vs 61 smoke 真证据 +118% (12 day 漂移)
- Session 9 sustained "smoke 28 PASS"
- Phase 9 真测 5-01: **61 smoke collected** = +33 (+118%)
- 真 12 day 真**新增 33 smoke tests** sustained Wave 4 MVP 4.1 batch 1+2 sustained

### 2.3 regression marker 真 0 真证据
- 真 0 tests `@pytest.mark.regression` sustained sprint period sustained
- 真 regression baseline 走 `scripts/run_backtest.py` + `cache/baseline_*.json` (sustained sprint period sustained 沉淀 "regression 5yr+12yr max_diff=0")
- 真 pytest 真**0 sustained regression coverage** sustained sustained

---

## §3 真根因 sustained F-D78-17 加深

**真根因 sustained F-D78-17 P2 sustained "handoff 写入层 0 enforce"** 真证据加深:
- sprint state 沉淀数字 4-19 (Session 9) 真**12 day 0 update sustained** sprint period sustained 22 PR sustained
- handoff 写入层 真**0 reverify SQL/pytest before 写候选** sustained 真**多次复发 sustained**
- → 真 sprint state 数字 真**多 stale sustained sprint period sustained**

**🔴 finding**:
- **F-D78-276 [P1]** 测试基线 +1188 (+41%) 漂移 sustained sprint period sustained 12 day, sustained sprint state Session 9 sustained "2864 pass / 24 fail" 真**12 day 0 update sustained**, sustained F-D78-76 + F-D78-147 + F-D78-17 cluster 同源真证据完美加深 (handoff 数字必 SQL/pytest verify before 写候选 0 sustained 真复发 sustained)

---

## §4 真生产意义 — Wave 4 真测试新增 +1188 真证据加深

**真测**: 12 day 真+1188 tests 真证据加深 sustained sprint period sustained "Wave 4 MVP 4.1 batch 3.x 17 scripts SDK migration" + "MVP 3.1 Risk Framework 65 新 tests" sustained 真证据.

**真生产 ROI** (sustained F-D78-176 同源):
- 真 12 day +1188 tests sustained 22 PR + Wave 4 batch 3.x sustained
- 真 12 day +0 alpha generation (PT 4-29 暂停后 NAV ¥993K sustained)
- 真**测试 ROI (test count) >> alpha ROI sustained** 真证据加深 (sustained F-D78-176 协作 ROI 量化 0 业务前进 同源真证据)

**finding**:
- F-D78-277 [P2] 12 day +1188 tests sustained 22 PR + Wave 4 sustained, vs 同 12 day 真**alpha 生成 0** = 真**测试 ROI >> alpha ROI 反差** sustained 真证据加深

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-276** | **P1** | 测试基线 +1188 (+41%) 12 day 漂移, sprint state 12 day 0 update, F-D78-17 cluster 真证据完美加深 |
| F-D78-277 | P2 | 12 day +1188 tests vs 同 12 day alpha 生成 0 = 测试 ROI >> alpha ROI 反差 sustained |

---

**文档结束**.
