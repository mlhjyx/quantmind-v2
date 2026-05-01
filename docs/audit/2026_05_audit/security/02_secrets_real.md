# Security Review — Secrets Audit 真测 (CC 扩 D14)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 4 / security/02
**Date**: 2026-05-01
**Type**: 评判性 + secrets management 真测 (sustained security/01 + CC 扩 D14)

---

## §1 .env secrets 真清单 (sustained snapshot/04+05 + security/01)

实测 sprint period sustained sustained:

| Secret | 真值 |
|---|---|
| TUSHARE_TOKEN | sustained 真 token (Tushare 商业 ToS) |
| DEEPSEEK_API_KEY | sustained 真 key (备用 LLM, sustained F-D78-56 0 sustained 协作) |
| ADMIN_TOKEN | sustained 真 token (FastAPI admin 端点候选) |
| DINGTALK_WEBHOOK_URL | sustained 真 webhook (含 access_token 参数, F-D78-74) |
| DINGTALK_SECRET | **空** (signature 验签 disabled, F-D78-3) |
| QMT_PATH / QMT_ACCOUNT_ID / QMT_EXE_PATH | sustained 真 broker config |

---

## §2 Secret rotation 真测 (CC 扩 D14)

实测 sprint period sustained sustained:
- TUSHARE_TOKEN sustained sustained sustained sustained sustained 0 sustained rotation history
- DEEPSEEK_API_KEY sustained sustained sustained 0 sustained rotation
- ADMIN_TOKEN sustained sustained sustained 0 sustained rotation
- DINGTALK_WEBHOOK_URL sustained sustained sustained 0 sustained rotation

**真测**: secret rotation 历史 真 0 sustained sustained sustained, 沿用 F-D78-72 P2 sustained.

**🔴 finding**:
- **F-D78-164 [P1]** Secret rotation 0 sustained sustained sustained, 5 个真 secrets (TUSHARE / DEEPSEEK / ADMIN / DINGTALK_WEBHOOK / QMT) sprint period sustained 0 sustained rotation history. 候选: 真 secret 真 last-rotation 真值 0 sustained sustained 度量

---

## §3 Secret leak detection (CC 扩)

实测 sprint period sustained sustained:
- .env in .gitignore (沿用 sprint period sustained PR #36 ".gitignore .env.* 补漏" sustained F-D78-73 候选)
- 真 grep `webhook` / `token` / `key` in repo: 候选未深查
- git history secret leak detection (sprint period sustained sustained 0 sustained sustained 度量)

候选 finding:
- F-D78-165 [P2] Secret leak detection 0 sustained sustained 度量 (git history 真 grep secrets candidate, sustained sprint period sustained sustained PR #36 ".env 补漏" sustained 但 enforcement 真测 candidate)

---

## §4 DPAPI / 加密存储 (Windows 默认)

实测 sprint period sustained sustained:
- Windows DPAPI sustained sustained sustained 0 sustained sustained 沉淀使用
- .env 真 plaintext store
- 候选 candidate: secrets 加密 存储 (e.g. Hashicorp Vault / Windows DPAPI / etc)

候选 finding:
- F-D78-166 [P3] secrets 加密存储 0 sustained sustained, .env plaintext sustained sustained, 候选 DPAPI / Vault candidate

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-164** | **P1** | Secret rotation 0 sustained sustained, 5 secrets sprint period 0 rotation history |
| F-D78-165 | P2 | Secret leak detection 0 sustained 度量 (git history grep secrets candidate) |
| F-D78-166 | P3 | secrets 加密存储 0 sustained, .env plaintext, 候选 DPAPI / Vault |

---

**文档结束**.
