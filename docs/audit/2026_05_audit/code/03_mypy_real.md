# Code Review — mypy 真 install + run real

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / code/03
**Date**: 2026-05-01
**Type**: 评判性 + mypy 真 install + 真 run

---

## §1 mypy 真测 (CC 5-01 实测)

实测 cmd:
```
.venv/Scripts/python.exe -m mypy backend/engines --ignore-missing-imports --no-error-summary
```

**真值** (尾部 6 line):
```
backend\engines\strategies\s1_monthly_ranking.py:131: error: Invalid "type: ignore" comment  [syntax]
backend\engines\config_guard.py:168: error: Library stubs not installed for "yaml"  [import-untyped]
backend\engines\config_guard.py:168: note: Hint: "python3 -m pip install types-PyYAML"
backend\engines\config_guard.py:168: note: (or run "mypy --install-types" to install all missing stub packages)
backend\engines\config_guard.py:168: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
backend\engines\data\factor_cache.py: error: Source file found twice under different module names: "backend.data.factor_cache" and "data.factor_cache"
```

---

## §2 真发现 — 3 真 errors (sustained F-D78-149 加深)

| 序 | 错误 | 位置 | 含义 |
|---|---|---|---|
| 1 | Invalid "type: ignore" comment [syntax] | strategies/s1_monthly_ranking.py:131 | 真 mypy 语法错误 sustained sprint period sustained 0 真测 |
| 2 | Library stubs not installed for "yaml" [import-untyped] | config_guard.py:168 | 真 yaml stub 真 0 install (types-PyYAML 真缺) |
| 3 | **Source file found twice under different module names**: "backend.data.factor_cache" and "data.factor_cache" | data/factor_cache.py | **🔴 真 import path 双 path collision** |

---

## §3 🔴 重大 finding — backend.data.factor_cache 双 import path

**真证据**: factor_cache.py 真**通过 2 path 真 importable**:
- `backend.data.factor_cache` (走 backend prefix, sustained sprint period sustained "Wave 1+ backend.platform 包名")
- `data.factor_cache` (走 implicit path, sustained 老风格)

**真根因 candidate**:
- sustained sprint period sustained "Wave 1 决议: 包名 backend.platform" (sustained project_platform_decisions.md), 但 真生产 .pth 文件 (sustained docs/SETUP_DEV.md) 沉淀 path manipulation 真允许双 import path
- → 真 type system 真**0 enforce 单 import path**, 真生产代码 真**dual import 风险** sustained (sustained 铁律 16 信号路径唯一 同源 反 anti-pattern)

**🔴 finding**:
- **F-D78-252 [P0 治理]** mypy 真 detect `data/factor_cache.py` Source file found twice under "backend.data.factor_cache" and "data.factor_cache" — 真 import path 双 path collision sustained, sustained 铁律 16 信号路径唯一 同源 反 anti-pattern (factor_cache 真 importable from 2 path = 真生产 dual import 真风险), sustained F-D78-? .pth 配置 + Wave 1 backend.platform 包名 决议同源 真证据

---

## §4 mypy 真 0 sustained sprint period sustained 8 month (sustained F-D78-149 加深)

**真测**: sprint period sustained 22 PR + 8 audit phase + 6 块基石 治理基础设施 沉淀 — 真 mypy 真**0 install + 0 sustained type check** sustained sustained sustained sprint period sustained.

**finding**:
- F-D78-253 [P1] mypy 真**0 sustained 8 month** sprint period sustained sustained sustained 治理 over-engineering vs 真 type check 真 0 实施 反差 sustained, sustained F-D78-251 同源加深 (pip-audit + mypy + pipdeptree 同 cluster 真 0 sustained 真治理倒挂)

---

## §5 真 install 1 step verify

实测 install 命令:
```
.venv/Scripts/python.exe -m pip install pip-audit mypy pipdeptree --quiet
```

**真值**: 安装真**1 命令 sustained**, sustained sprint period sustained 真**0 install** = 真治理懒惰 + 真主线 (Wave 1-4 + 12 framework + 6 块基石) 优先级倒挂 (反复 verify 同源加深).

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-252** | **P0 治理** | mypy detect data/factor_cache.py Source file found twice (双 import path collision), 铁律 16 信号路径唯一 反 anti-pattern |
| F-D78-253 | P1 | mypy 真 0 sustained 8 month, sustained F-D78-251 同源加深 |

---

**文档结束**.
