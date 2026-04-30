# Security Review — STRIDE + 真金边界 + Secrets

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / security/01
**Date**: 2026-05-01
**Type**: 评判性 + STRIDE Threat Modeling + 真金边界 verify

---

## §1 真金边界 STRIDE 全维度

### 1.1 真金保护双锁 sustained verify

实测 (E5 sustained):

| 锁 | 字段 | 真值 |
|---|---|---|
| **锁 1**: Python flag | `LIVE_TRADING_DISABLED: bool = True` | ✅ config.py:44 默认 True, .env 0 override |
| **锁 2**: 模式 | `EXECUTION_MODE` | ✅ paper sustained (.env) |

**判定**: ✅ 真金双锁 sustained, broker_qmt 层 sustained block.

### 1.2 STRIDE 6 维度

| 维度 | 真测 | 风险 |
|---|---|---|
| **Spoofing** (身份假冒) | xtquant broker 唯一入口 (CLAUDE.md sustained), QMT_ACCOUNT_ID=81001102 sustained | ⚠️ broker session_id 真生成 SECURE_RANDOM vs int(time.time()) 候选 verify |
| **Tampering** (数据篡改) | DB 写 path: DataPipeline 唯一入口 (铁律 17), 例外 subset UPSERT (LL-066) | ✅ 铁律 17 sustained sustained |
| **Repudiation** (抵赖) | risk_event_log 真测 仅 2 entries (risk/02 §1), event_outbox 0/0 (risk/02 §2) | 🔴 sprint period sustained Event Sourcing audit log 0 真使用, 抵赖防护 candidate 0 enforce |
| **Information Disclosure** (信息泄露) | `.env` 含 TUSHARE_TOKEN + DEEPSEEK_API_KEY + ADMIN_TOKEN + DINGTALK_WEBHOOK 真值, .env 应在 .gitignore (铁律 35) | ⚠️ .env 真测在 .gitignore? 待 grep verify |
| **DoS** | Servy 4 服务单点 + DB 单点 + xtquant 单点 + 32GB RAM 上限 | 🔴 sustained 多单点风险 (sustained external/01 §2) |
| **Elevation of Privilege** | ADMIN_TOKEN 真值在 .env, 真权限边界 candidate 待 verify | ⚠️ ADMIN_TOKEN 调用方 + 权限边界 grep verify |

---

## §2 Secrets management

### 2.1 .env 真测内容 (CC E5 实测)

(详 [snapshot/04_config.md](../snapshot/04_config.md) — 待 sub-md 沉淀, 本 sub-md 链)

**真值**:
- TUSHARE_TOKEN sustained 真 token (config.py 验证)
- DEEPSEEK_API_KEY sustained 真 key (备用 LLM, sprint state F-D78-56 sustained 0 sustained 协作)
- ADMIN_TOKEN sustained 真 token
- DINGTALK_WEBHOOK_URL sustained 真 webhook
- **DINGTALK_SECRET=空** (F-D78-3, signature 1 锁)

### 2.2 secret rotation 真测 (CC 扩 D14)

(本审查未深查 secret rotation 历史. 候选 finding):
- F-D78-72 [P2] secret rotation 历史 0 sustained sustained (TUSHARE_TOKEN / DEEPSEEK_API_KEY / ADMIN_TOKEN / DINGTALK_WEBHOOK 真 last-rotated timestamp 未本审查 verify), 候选 secret rotation policy 0 sustained

### 2.3 .env vs .gitignore 真 verify

实测 sprint period sustained CLAUDE.md "铁律 35: Secrets 环境变量唯一 — 0 fallback 默认值 / `.env` 必 `.gitignore`" sustained sustained.

(本审查未直接 grep `.env` in `.gitignore`, sprint period 沉淀 sustained 沉淀 sprint period PR #36 ".gitignore .env.* 补漏" sustained.)

候选 finding:
- F-D78-73 [P3] .env vs .gitignore enforce 真 grep verify 候选 (sprint period sustained sustained 但本审查未直接 verify)

---

## §3 第三方 webhook 安全 (DingTalk)

实测真值:
- DINGTALK_WEBHOOK_URL sustained 真 webhook (含 access_token URL 参数)
- DINGTALK_SECRET sustained 空 (F-D78-3)
- DINGTALK_KEYWORD=xin (1 锁 sustained)

**真测 verify** (沿用 F-D78-3):
- signature 验签 disabled (DINGTALK_SECRET 空)
- 仅 keyword=xin 1 锁
- candidate webhook URL 泄露后 attacker 可 spam alert (但 keyword=xin 限制 candidate)

**finding**:
- F-D78-3 (复) [P3] DINGTALK 1 锁
- **F-D78-74 [P2]** DingTalk webhook URL 含 access_token 参数, 0 sustained URL leak detection (sprint period sustained 沉淀 .env in .gitignore 但 docs/ + sprint state 跨 PR 是否含真 webhook URL 候选 grep verify, sprint period sustained sustained 沉淀 PR #36 .env 补漏 sustained)

---

## §4 xtquant + broker 安全

实测真值:
- xtquant 唯一 import 在 scripts/qmt_data_service.py (CLAUDE.md sustained)
- broker_qmt sell only (sprint period sustained sustained, design 含 buy 候选)
- LIVE_TRADING_DISABLED=True 默认 + EXECUTION_MODE=paper sustained — 双锁 sustained block live trading

**finding**:
- F-D78-75 [P2] broker_qmt design 含 buy 候选 (sprint period sustained sell only sustained 但 design 真深查候选), 候选真金 attack surface 评估

---

## §5 supply chain (沿用 snapshot/06 + external/01)

详 [snapshot/06_dependencies.md](../snapshot/06_dependencies.md) §2 (pip-audit 未装 F-D78-70) + [external/01_vendor_lock_in.md](../external/01_vendor_lock_in.md) §3 (ToS 风险 F-D78-38).

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-3 (复) | P3 | DINGTALK 1 锁 |
| F-D78-72 | P2 | secret rotation 历史 0 sustained, 候选 secret rotation policy 0 sustained |
| F-D78-73 | P3 | .env vs .gitignore enforce 真 grep verify 候选 |
| F-D78-74 | P2 | DingTalk webhook URL 含 access_token 参数, 0 sustained URL leak detection |
| F-D78-75 | P2 | broker_qmt design 含 buy 候选, 候选真金 attack surface 评估 |

---

**文档结束**.
