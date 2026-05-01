# Independence Review — Import graph 真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 5 / independence/02
**Date**: 2026-05-01
**Type**: 跨领域 + 真测 import graph (sustained independence/01 §2 F-D78-91)

---

## §1 backend/qm_platform 真 import 真测 (CC 5-01 实测)

实测命令:
```bash
grep -rE "^(import |from )" backend/qm_platform/ | wc -l
```

**真值**: **472 imports** in `backend/qm_platform/` (sprint period sustained sustained Wave 1+2+3 Platform 12 Framework 真活)

---

## §2 engine 层 DB violations 真测 (sustained code/02 §1)

实测真值: **9 文件含 psycopg/conn.cursor/engine.execute import** in `backend/engines/`:
1. base_strategy.py
2. beta_hedge.py
3. config_guard.py (sustained example)
4. datafeed.py (sustained example)
5. factor_analyzer.py
6. factor_engine/__init__.py
7. factor_gate.py
8. factor_profile.py
9. factor_profiler.py

(详 [`code/02_engine_31_violations.md`](../code/02_engine_31_violations.md))

---

## §3 模块独立性 真测 (sustained independence/01)

(沿用 [`independence/01_module_decoupling.md`](01_module_decoupling.md) §1)

实测候选 finding:
- DataPipeline / SignalComposer / BacktestEngine / RiskEngine / broker_qmt / DingTalk 6 模块 单点 sustained sustained sustained sustained
- 跨模块 import graph 0 sustained sustained sustained 度量 (sustained F-D78-91 P2)

---

## §4 候选深查 (本审查 partial)

候选 finding:
- F-D78-169 [P2] backend 全 import graph 真 dependency 0 sustained sustained 度量 (无 pylint --output-format=text / import-linter / pydeps / etc sustained sustained sustained), sprint period sustained sustained 沉淀 472 imports in qm_platform 真活 ✅ but 真 dependency depth + circular detection 0 sustained 度量
- F-D78-170 [P3] backend/engines/ vs backend/app/services/ vs backend/qm_platform/ 跨层 import 真 enforce 0 sustained sustained 度量 (sustained 铁律 31/32 sustained sustained 但 enforcement 真 audit candidate)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-169 | P2 | backend 全 import graph 真 dependency 0 sustained 度量 (无 pylint / import-linter / pydeps), 472 qm_platform imports ✅ but depth + circular 0 度量 |
| F-D78-170 | P3 | backend/engines vs services vs qm_platform 跨层 import 真 enforce 0 sustained 度量 (铁律 31/32 enforcement 真 audit candidate) |

---

**文档结束**.
