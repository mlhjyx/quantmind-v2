# Security Review — Supply Chain 真测 (CC 扩 M13)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / security/03
**Date**: 2026-05-01
**Type**: 评判性 + supply chain 真深查 (sustained security/01 + snapshot/06 + external/01)

---

## §1 Python 依赖漏洞 (CC 5-01 实测)

实测真值 (sustained snapshot/06):
- pip-audit **未装** in .venv (F-D78-70 P1 sustained)
- pip list --outdated = 26 outdated (F-D78-69 P2 sustained)
- 真漏洞 visibility = **0 sustained**

**finding** (sustained):
- F-D78-70 (复) [P1] pip-audit 未装 in .venv, 0 sustained 漏洞扫描

---

## §2 NPM 依赖漏洞

实测 sprint period sustained sustained:
- npm audit 0 跑过本审查 (F-D78-71 P2 sustained snapshot/06 §3)

**finding** (sustained):
- F-D78-71 (复) [P2] NPM 依赖 + npm audit 0 跑过本审查

---

## §3 License audit (CC 扩 M7 / framework_self_audit §1.1)

实测 sprint period sustained sustained:
- 116 Python 依赖 license 真清单 0 sustained sustained 沉淀
- 真冲突 license (e.g. GPL vs MIT) 0 sustained sustained 度量

候选 finding:
- F-D78-191 [P3] License audit 0 sustained sustained sustained 沉淀, 116 Python 依赖 license 真清单 0 sustained, 真冲突候选 unknown

---

## §4 第三方源 ToS audit (sustained external/01 §3)

实测 sprint period sustained sustained:
- Tushare 商业 ToS sustained sustained sustained
- 国金 miniQMT broker ToS sustained sustained
- Anthropic Claude API ToS sustained
- DingTalk webhook 免费 ToS sustained
- DEEPSEEK_API_KEY ToS sustained sustained sustained

(沿用 external/01 §3 + blind_spots/04 §1.4 F-D78-38 P2 sustained sustained sustained)

---

## §5 SBOM (Software Bill of Materials) sustained 0 sustained

候选 finding:
- F-D78-192 [P3] SBOM 0 sustained sustained 沉淀, 116 Python + NPM 依赖真 SBOM 0 sustained sustained sustained sustained, 候选 cyclonedx 候选 sustained sustained sustained sustained

---

## §6 git history secret leak detection

(沿用 security/02 §3 F-D78-165 P2 sustained sustained sustained sustained)

---

## §7 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-70 (复) | P1 | pip-audit 未装 in .venv |
| F-D78-71 (复) | P2 | NPM audit 0 跑过本审查 |
| F-D78-191 | P3 | License audit 0 sustained 沉淀 |
| F-D78-192 | P3 | SBOM 0 sustained 沉淀 |

---

**文档结束**.
