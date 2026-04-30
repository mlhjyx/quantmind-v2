# 现状快照 — 依赖 + 漏洞 (类 6)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 3 / snapshot/06
**Date**: 2026-05-01
**Type**: 描述性 + 实测证据 + 漏洞扫描 (CC 扩 M13)

---

## §1 Python 依赖真测 (CC 5-01 实测)

实测命令:
```bash
.venv/Scripts/python.exe -m pip list | wc -l
```

**真值**:
- 总依赖数: ~116 (snapshot/01 §1 实测)
- pip list --outdated: **26 outdated** (CC 5-01 实测)

**finding**:
- **F-D78-69 [P2]** pip list --outdated 26 outdated dependencies, sprint period sustained 0 sustained dependency upgrade sweep, candidate sub-md 深查 critical packages

---

## §2 漏洞扫描 (pip-audit) 真测

实测命令:
```bash
.venv/Scripts/python.exe -m pip-audit --desc
```

**真值**:
- **`No module named pip-audit`** — pip-audit **未装** in .venv

**🔴 finding**:
- **F-D78-70 [P1]** pip-audit 未装 in .venv, sprint period sustained 0 sustained 漏洞扫描. **依赖漏洞 真值 0 visibility**, 候选 supply chain 单点失败风险 sustained (沿用 F-D78-38 第三方源 ToS unknown unknown). 沿用 framework_self_audit §2.1 D14 CC 扩 secret rotation + supply chain 沉淀

---

## §3 NPM 依赖真测 (frontend)

(本审查未跑 npm list / npm audit, sprint period sustained CLAUDE.md "前端 React 18 + TypeScript + Tailwind 4.1" sustained sustained.)

候选 finding:
- F-D78-71 [P2] NPM 依赖 + npm audit 0 跑过本审查, frontend 漏洞 真值 0 visibility

---

## §4 第三方系统依赖

实测 sprint period sustained sustained:

| 依赖 | 版本 | 真测 |
|---|---|---|
| PostgreSQL | 16.8 | sprint period sustained sustained ✅ |
| TimescaleDB | 2.26.0 | sprint period sustained sustained ✅ |
| Redis | 5.0.14.1 | sprint period sustained sustained (清明改造迁版) |
| Servy | v7.6 | sprint period sustained sustained (替换 NSSM 2026-04-04) |
| xtquant | (sprint state 沉淀) | 真版本未本审查 verify |
| Python | 3.11.9 | E4 实测 ✅ |
| PyTorch | cu128 (Blackwell sm_120) | sprint period sustained sustained, GPU 真利用率未本审查 verify (沿用 F-D78-候选 sub-md 18_gpu_usage_history) |

---

## §5 依赖单点失败 (沿用 external/01_vendor_lock_in)

详 [`external/01_vendor_lock_in.md`](../external/01_vendor_lock_in.md) §1-2.

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-69 | P2 | pip list --outdated 26 outdated, sprint period 0 sustained dependency upgrade sweep |
| **F-D78-70** | **P1** | pip-audit 未装 in .venv, 0 sustained 漏洞扫描, 依赖漏洞真值 0 visibility |
| F-D78-71 | P2 | NPM 依赖 + npm audit 0 跑过本审查, frontend 漏洞真值 0 visibility |

---

**文档结束**.
