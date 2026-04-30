# 现状快照 — 配置 + API + (依赖见 06) (类 4+5)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 3 / snapshot/04+05
**Type**: 描述性 + 实测证据

---

## §1 类 4 — 配置真测 (CC 5-01 实测)

### 1.1 .env 真清单 (snapshot/01 §1 + security/01 §2.1)

20 keys / 37 lines (snapshot/01 §1 sustained):
- DATABASE_URL / REDIS_URL
- TUSHARE_TOKEN
- DEEPSEEK_API_KEY
- QMT_PATH / QMT_ACCOUNT_ID / QMT_ALWAYS_CONNECT / QMT_EXE_PATH
- EXECUTION_MODE=paper
- LOG_LEVEL / LOG_MAX_FILES
- PAPER_STRATEGY_ID / PAPER_INITIAL_CAPITAL / PT_TOP_N=20 / PT_INDUSTRY_CAP=1.0 / PT_SIZE_NEUTRAL_BETA=0.50
- DINGTALK_WEBHOOK_URL / DINGTALK_SECRET=空 / DINGTALK_KEYWORD=xin
- ADMIN_TOKEN

**真测 finding** (sustained 多 finding):
- F-D78-3 (复) DINGTALK_SECRET=空
- F-D78-72 (复) secret rotation 0 sustained
- F-D78-73 (复) .env vs .gitignore enforce 真 grep verify 候选
- F-D78-74 (复) DingTalk webhook URL 含 access_token

### 1.2 configs/*.yaml 真清单 (CC 未深查)

候选 finding:
- F-D78-107 [P3] configs/*.yaml 真清单 + 字段 + 调用方 grep + 死字段 candidate 0 sustained 深查 in 本审查

### 1.3 config_guard 启动硬 raise (铁律 34)

(本审查未深查 真 启动 raise 历史 + 真 config 一致性 enforce. sprint period sustained sustained sustained 沉淀.)

候选 finding:
- F-D78-108 [P2] config_guard 真启动 raise 历史 0 sustained sustained, sprint period sustained 铁律 34 sustained sustained 但 enforcement 真历史 candidate

---

## §2 类 5 — API + WebSocket 真清单 (CC 未深查)

实测 sprint period sustained sustained:
- FastAPI app sustained sustained
- /api/* endpoint count 0 本审查 verify
- /ws/* channel count 0 本审查 verify
- frontend grep + scripts grep 调用方 0 sustained
- deprecated / 死 endpoint candidate 0 sustained sustained

候选 finding:
- F-D78-109 [P2] API + WebSocket 真清单 + 调用方 + deprecated candidate 0 sustained 深查 in 本审查 (sustained framework §2.5)

---

## §3 类 6 — 依赖

(详 [`snapshot/06_dependencies.md`](06_dependencies.md))

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-107 | P3 | configs/*.yaml 真清单 0 sustained 深查 |
| F-D78-108 | P2 | config_guard 真启动 raise 历史 0 sustained, 铁律 34 enforcement 真历史 candidate |
| F-D78-109 | P2 | API + WebSocket 真清单 + 调用方 + deprecated 0 sustained 深查 |

---

**文档结束**.
