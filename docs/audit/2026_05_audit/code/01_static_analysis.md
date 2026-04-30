# Code Review — Static Analysis (SAST) 真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / code/01
**Date**: 2026-05-01
**Type**: 评判性 + 真测 ruff + 死码 candidate (CC 扩 M5 Code archaeology 候选)

---

## §1 ruff 真测 (CC 5-01 实测)

实测命令:
```bash
.venv/Scripts/python.exe -m ruff check backend/ scripts/ engines/
```

**真值**:
- **18 errors** (12 fixable with --fix, 4 hidden fixes with --unsafe-fixes)
- (单个 rule 分类待 §2 stats)

**🔴 finding**:
- **F-D78-64 [P2]** ruff 18 errors 跨 backend/ + scripts/ + engines/ 0 修. 沿用 CLAUDE.md "提交前: ruff check + ruff format" sustained sustained, **enforcement 失败** (sprint period 22 PR 治理 sprint period 包括 docs/ 但代码静态分析未 sweep)

---

## §2 ruff stats 详查 (rule by rule)

(本审查 §1 ruff 输出仅总 errors 数, --statistics 输出待 retry. 候选 finding):

- 候选 sub-md 详 sub-md / rule 拆分
- 候选 fixed via `ruff check --fix` (但本审查 0 修, 沿用 D78 0 修改 sustained)

---

## §3 mypy 真测 (CC 扩 — 未跑)

(本审查未跑 mypy 全 repo. CLAUDE.md sustained "类型注解 + Google style docstring" sustained 但 mypy 真 enforcement 度未实测.)

候选 finding:
- F-D78-65 [P2] mypy 全 repo 0 跑过本审查, 类型注解 enforcement 度未实测

---

## §4 死码 candidate (沿用 F-D78-37 + CC 扩 M5)

实测真值:
- 全 repo *.py = 846 (snapshot/01 §1)
- ruff 18 errors 含部分 unused import (待 §2 stats 拆分 verify)
- sprint period 沉淀多次"死码清理" (PMS v1 deprecate / dual-write Beat 退役 / 等)

候选 finding:
- F-D78-37 (复) [P3] 项目 846 *.py 死码 + 真生产 path 比例未深查
- F-D78-66 [P2] sprint period 沉淀的"死码清理" (PMS v1 / dual-write / etc) 真删除 vs 仅 stop calling 候选 verify, 候选 ruff F401 unused import 实测 / pyflakes 全 repo

---

## §5 跨层违规 (铁律 31 sustained Engine 不读 DB/HTTP/Redis)

(本审查未跑 Engine 层 grep verify. 沿用 sprint period sustained "Phase C F31 全部完成 (C0+C1+C2+C3): factor_engine.py 2049→416 行, 25 调用方零改动, 铁律 31 落地" sustained sustained.)

候选 finding:
- F-D78-67 [P2] 铁律 31 (Engine 不读 DB/HTTP/Redis) 真 enforcement 全 engines/ 目录 grep verify 候选, 沿用 sprint period sustained "F31 全部完成" 表层 sustained 但 enforcement 真测候选

---

## §6 圈复杂度 (CC 扩 — 未跑)

(本审查未跑 radon / mccabe 全 repo 圈复杂度. 候选 finding):
- F-D78-68 [P3] 圈复杂度 0 sustained 度量, 候选 sub-md 深查

---

## §7 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-64** | **P2** | ruff 18 errors 跨 backend/ + scripts/ + engines/ 0 修, CLAUDE.md "提交前 ruff check" sustained 但 enforcement 失败 |
| F-D78-65 | P2 | mypy 全 repo 0 跑过本审查, 类型注解 enforcement 度未实测 |
| F-D78-66 | P2 | sprint period 沉淀的"死码清理" 真删除 vs 仅 stop calling 候选 verify |
| F-D78-67 | P2 | 铁律 31 Engine 层 enforcement 真 grep verify 候选, sprint period sustained 表层 sustained |
| F-D78-68 | P3 | 圈复杂度 0 sustained 度量, 候选 sub-md 深查 |
| F-D78-37 (复) | P3 | 846 *.py 死码 + 真生产 path 比例未深查 |

---

**文档结束**.
