# V3 Audit Section VI — Strategic & Knowledge Continuity (2026-05-18 evening)

> **Source**: Subagent I §25-30 + Section VIII 30 additional suggestions
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §25 Strategic Risks (SPF Enumeration)

| SPF | Probability | Impact | Mitigation Gap |
|---|---|---|---|
| **单 user (bus factor=1)** | High (持续) | **Catastrophic** — 项目即刻 frozen | 0 onboard doc (CLAUDE.md 512 行 是入口 not 30min onboard) / sprint state 768KB 不可读 / tribal knowledge 100% in user head (**P0-19, P0-20**) |
| **单 strategy (CORE3+dv_ttm)** | Med (factor decay) | High (单押) | Phase 3B/3D/3E 全 NO-GO / 0 diversification active / dv_ttm "warning" lifecycle ratio=0.517 |
| **单 machine (R9-9900X3D / 32GB / RTX 5070)** | Low/yr (HW failure) | High (recovery >1d) | 0 hot spare / 0 cloud failover / 0 fail-over SOP (F-D78-187 P1) |
| **单 ISP** | Med (outage) | High during trading hours | 0 backup ISP / 0 LTE fallback documented |
| **单 broker (国金 miniQMT)** | Low/yr | Catastrophic (账户冻结) | 0 backup broker code path / 0 broker abstraction (xtquant tight coupling) |
| **单 Tushare account** | Low | High (data freeze) | 0 backup data vendor for Tushare core / Baostock minute_bars only fallback / 0 ADR for vendor swap (P1-33) |
| **单 LLM provider (DeepSeek)** | Med (API drift, LL-180 实证 5-07 4-day undetected drift) | High (V3 risk pipeline halt) | Fallback `qwen3-local` 存 (router.py:120 `FALLBACK_ALIAS`) but 0 prod verify / ADR-034 V5 backup planning still draft |
| **单 DingTalk webhook** | Med (rate limit / bot revoke) | Med (alert blind) | 0 SMS backup (MVP 4.1 stub only) / 0 email channel active |

### §25.1 P0 Bus Factor=1
- CLAUDE.md is entry doc, not onboard playbook
- 768KB sprint state超 Read tool 上限
- 0 `docs/ONBOARDING.md`
- 若 user 突发休假/伤病 → CC restart cannot reconstruct 24h
- **Alt 1**: 30min onboard playbook (≤300 行)
- **Alt 2**: Sprint state monthly chunk
- **Alt 3**: External git mirror + S3 daily DB snapshot

---

## §26 Roadmap Alignment

### §26.1 Wave 4 MVP 4.1 Progress
- 批 1 ✅ PostgresAlertRouter + PG dedup (PR #131)
- 批 2.1 ✅ MetricExporter
- 批 2.2 ✅ AlertRulesEngine
- 批 3.x 🟡 **进行中** — 17 scripts SDK migration. Sprint state 0 PR# cite for batch 3 progress → status freshness drift (P1-status)

### §26.2 Wave 5/6 Planning
- ADR-012 Operator UI cited in QPB:1129 (4-6 weeks)
- Wave 6 未规划

### §26.3 V3 §19 Roadmap (12 month)
- ADR-064~ADR-081 sediment 沉淀 Tier A 7/8 PASS (ADR-065)
- Tier B closure (ADR-071)
- HC closure (ADR-076)
- Tier C 1b operational readiness (5-17)

### §26.4 PT Live-Fire Timeline (Post LL-183)
- LL-180 (5-18 14:02) — L4 STAGED live broker wire FAIL (xtquant asyncio compat)
- LL-181 — 5-18 afternoon 4h natural cycle PASS
- LL-182 — multi-process safety
- LL-183 — dry-run flag silent NOT-GATING fix
- **0 forward schedule post LL-183** (X10 enforce sustained)

---

## §27 Future-Proofing

| 维度 | Current | Target | Gap |
|---|---|---|---|
| Capital 100万→1000万 | ¥993,520 cash | 10x | 0 liquidity test; Top 20 × 10x = ¥500K each = ~30-40K shares × ¥5-7 stock — at 1000万 single stock 可能 >1% ADV impact |
| Strategy diversification | 1 (CORE3+dv_ttm) | 3+ | PEAD ADR-002 / RD-Agent ADR-013 reactivate candidates / 0 PT |
| Asset class expansion | A 股 only | 港股/美股/外汇 | DEV_FOREX 682 行 DEFERRED 0 backend impl |
| HW upgrade signals | 32GB DDR5 (OOM 4-03 实证) | 64GB | factor_values 840M 行已挤压 |
| AI capability V4→V5 | DeepSeek V4-Flash/Pro | V5 (ADR-034 plan) | qwen3→qwen3.5 fallback / V5 0 release |

**P1 §27.1**: Capital 10x readiness 0 verify. **Alt 1**: 100万 跑 historical replay 模拟 1000万 impact. **Alt 2**: capital_scale × ADV_constraint test 入 backtest gate. **Alt 3**: raise universe 流动性 floor 至 ¥1亿 ADV.

---

## §28 知识传承 (Knowledge Continuity)

| 维度 | Verify | Status |
|---|---|---|
| CC restart 30min onboard | CLAUDE.md 512 行 entry doc | **FAIL** — not onboard checklist |
| Memory file index | project_sprint_state.md 768KB | **FAIL** — 超 Read tool 上限 |
| Audit trail browsability | docs/audit/ 122 files | **WARN** — 缺 latest INDEX.md, 0 reverse-chrono summary |
| Tribal knowledge | (in user head) | **FAIL** — 0 enumerated list (e.g. "PT 重启需 user 决议清单") |

**P0 §28.1**: 4/4 维度 sub-target.

---

## §29 Reproducibility

| 维度 | Source | Status |
|---|---|---|
| Backtest (config_yaml_hash + git_commit) | IRONLAWS.md:252 max_diff=0 | **PASS (设计层)** |
| Backtest 真做过 max_diff=0? | (per PR validation) | **PARTIAL** — IRONLAWS.md:525 says PT 配置切换 anchor verify, 但无 evidence 每 PR 都过 |
| Factor calc | factor_values 840M 行 + factor_ic_history 145K 行 | **PASS** — 铁律 11 enforce |
| IC calc | factor_ic_history 唯一入库点 | **PASS** |
| **Live trade replay** | F-D78-241 trade_log MAX=4-17, 4-29 17 emergency_close + 4-30 GUI sell 18 trades 0 入 | **FAIL** — **铁律 15 实质违反** (P0-21) |

---

## §30 Process Maturity (CMMI-like)

| 维度 | Level | Evidence |
|---|---|---|
| Code change → CI | **L2 Proactive** | Pre-push hook + smoke + regression |
| Audit cadence | **L1 Reactive** — driven by user push back, 0 calendar | F-D78-33 sustained |
| Incident response (LL-180 5-18 14:02 P0) | **L2** — 32 min Beat resumed via M1/M3 双管 | LL-180 lesson 1-5 sediment |
| Reproducibility | **L1** (设计 L2 but live trade L0) | F-D78-241 |
| Strategic forecasting | **L0 Ad-hoc** | PT 重启 timeline 5d→2d→4-day flat, "no time limit" stance per memory |
| Knowledge transfer | **L0** | bus factor=1, 0 onboard doc |

**Overall**: **L1 Reactive** (avg). Gap to L2 Proactive: 知识 transfer + audit calendar + reproducibility live-trace.

---

## §VIII 30 Additional Suggestions Status

| # | Suggestion | Status | Recommendation |
|---|---|---|---|
| 1 | Project Onboarding Doc (30min) | **MISSING** | 新建 `docs/ONBOARDING.md` ≤300 行 |
| 2 | System Recovery Playbook | **PARTIAL** — `2026_05_audit/emergency_sop_v1.md` 存 | 加 fail-over SOP F-D78-187 |
| 3 | Strategy Confidence Decomp (Sharpe=0.8659) | **MISSING** | luck/skill 分解 paired bootstrap 已存 (LL-027) 但 0 confidence interval per-fold |
| 4 | Decision Tree per-LL | **EXISTS** — LESSONS_LEARNED.md 6000 行 | 加 INDEX |
| 5 | Pre-mortem Templates | **MISSING** | 入 skill |
| 6 | Capacity Stress Tests | **MISSING** | LL-181 4h cycle 已做, 1000万 0 test |
| 7 | Disaster Drill Calendar | **MISSING** — F-D78-187 P1 | 季度 drill |
| 8 | Architecture Decision Records | **STRONG** — 67 ADRs (vs CLAUDE.md cite "022") | 加 ADR index INSTEAD-OF |
| 9 | Skill Health Dashboard | **MISSING** | MVP 4.1 batch 后 |
| 10 | Audit Findings Tracker | **PARTIAL** — F-D78-* numbering 存 | 入 DB 表 |
| 11 | Reproducibility Lock | **PARTIAL** (设计 L2, live trade L0) | F-D78-241 修 |
| 12 | LLM Call Audit Trail | **STRONG** — `llm_call_log` schema 完整 | DB-VERIFY pending |
| 13 | RAG Quality Eval | **MISSING** | §34 alt (c) |
| 14 | Cost Per Decision | **PARTIAL** — schema 存 | DB-VERIFY |
| 15 | Failover Plan | **MISSING** — F-D78-187 | 新建 |
| 16 | Strategic Diversification Roadmap | **PARTIAL** — PEAD ADR-002 / RD-Agent ADR-013 | timeline 锁定 |
| 17 | Hardware Upgrade Triggers | **MISSING** | 阈值 trigger 入 settings |
| 18 | LLM Model Lifecycle | **PARTIAL** — ADR-034 sediment | V5 schedule |
| 19 | Capital Scale Test | **MISSING** | §27.1 alt (a) |
| 20 | Multi-Broker Abstraction | **MISSING** | xtquant tight coupling |
| 21 | Smoke Test Coverage | **STRONG** — `pytest -m smoke` 28 PASS | 维持 |
| 22 | Audit Pyramid (deep+wide) | **PARTIAL** — 1 audit 2026_05 cycle | 季度化 |
| 23 | Regression Gate Live | **STRONG** — max_diff=0 | live trade extend §29 |
| 24 | Cost Drift Detection | **MISSING** | heuristic #6 |
| 25 | Knowledge Graph (LL ↔ ADR ↔ MVP) | **MISSING** | new |
| **26 (NEW v8)** | **Decision Log "why X over Y"** | **PARTIAL** — ADRs cover but 0 fork explicit | **ADR template add §Alternatives Considered + §Why-Not-Y** |
| **27 (NEW v8)** | **Living Documentation (design + smoke)** | **MISSING** | **MVP 4.1 batch 3 后落地** |
| **28 (NEW v8)** | **Auto System Diagram (AST→mermaid)** | **MISSING** | **Python AST script ~80 行 (one-shot)** |
| **29 (NEW v8)** | **Audit Calendar (heuristic #17)** | **MISSING** | **cron + `docs/audit/CALENDAR.md`** |
| **30 (NEW v8)** | **Reverse Traceability (code↔doc)** | **MISSING** | **Grep-based generator 入 pre-push hook** |

---

**End Section VI.**
