# User Tribal Knowledge — Explicit Enumeration (sustained P0-20 closure)

> **目的**: Plan v8 Master P0-20 closure (Knowledge Transfer 4/4 FAIL → 4/4 PASS). Tribal knowledge 100% in user head → CC + 远期第三方 接手 cognitive gap.
>
> **真讽刺**: 本 doc 是 sustained "list user-only knowledge". User 写完后, knowledge 不再 tribal. **CC may suggest additions, user verifies + sediment**.
>
> **Date**: 2026-05-19 Session 58+1 evening SH
> **Authors**: CC seed + user verify (sustained user touchpoint maintenance — quarterly review at minimum)
> **Related**:
> - [Plan v8 Master P0-20](audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) — Knowledge Transfer 4/4 audit
> - [Plan v8 S6 §28](audit/V3_AUDIT_S6_STRATEGIC_AND_CONTINUITY.md) §28.1 Tribal knowledge enumerate FAIL
> - [Plan v8 §VIII #25](audit/V3_AUDIT_S6_STRATEGIC_AND_CONTINUITY.md) — Future-Self Audit (3/6 月后还看得懂?)
> - [ONBOARDING.md](ONBOARDING.md) — 30-min restart playbook (本 doc 是 supplement)

---

## §1 PT 重启 user 决议清单

### 1.1 历史决议 (5-02 sprint close V3 §20.1 10/10 settled)

| # | 决议主题 | Status |
|---|---|---|
| #1 | L4 STAGED default 启用 sequence | ADR-027 §2.1 短期 default=OFF + 长期 default=STAGED (满足 5 prerequisite) |
| #2 | 跌停 fallback (V3 §7.2) | ADR-027 §2.3 — STAGED execute 路径检测跌停 → 切换次日开盘 limit |
| #3 | BGE-M3 1024 维 RAG embedding | ADR-028 §2.3 (本地隐私 + 0 cost) |
| #4 | V4-Pro 月度复盘 cadence | ADR-028 §2.2 (沿用 §17.4 隐私) |
| #5 | AUTO 模式 5 prerequisite | ADR-028 §1.2 (Sprint M+1~N defer) |
| #6 | LLM 预算 $50/月 + 80% warn / Ollama fallback | ADR-028 §3.3 |
| #7 | user 离线 STAGED 30min → execute | ADR-027 §2.2 (反向决策权) |
| #8 | L4 batched 平仓 batch interval | ADR-027 §2.3 (5min / 1min critical) |
| #9 | L5 lesson 入 RAG 自动度 (c) | ADR-028 §2.5 (自动 + 后置抽查) |
| #10 | DingTalk + 钉钉 keyword 'xin' wire | DINGTALK_ALERTS_ENABLED=true (5-17 flip) |

### 1.2 待决议 (post Phase B-2 5-27 live restart)

| # | 决议主题 | Pending question |
|---|---|---|
| U1 | PG password rotate timing | Phase B-2 前 OR 后? (P0-2) |
| U2 | gp-weekly disable for 5d window | 5-24 Sun 22:00 ambush prevention? |
| U3 | Phase B-2 5-27 Wed live flip trigger 3 | "你执行" 时点决议 |
| U4 | meta-monitor memory rule wire | ADR-086 Tier 2 immediate vs Day 3? |
| U5-U11 | Phase J 7 research items priority | sustained PLAN_V8_MASTER_FINDINGS_REGISTER §7.2 |
| U12 | Frontend stack decision (Plan v8 §9.3) | React 18 retain vs SvelteKit/Vue 3/Solid |
| U13 | Frontend hosting | local dev vs Servy persistent |
| U14 | Auth model upgrade | ADMIN_TOKEN → OAuth/RBAC? |
| U15 | AI-assisted ops boundary | NLP cancel order / threshold change? |

---

## §2 Risk Tolerance Bounds (sustained 4-29 清仓决议 context)

| 维度 | Bound | Source |
|---|---|---|
| 最大单股 position | 默认 PT_TOP_N=20 等权 (5% 单股), 灰度 5-18 调整 PT_TOP_N=5 → 20% 单股 | .env PT_TOP_N, SHUTDOWN_NOTICE_2026_04_30 |
| 行业上限 | PT_INDUSTRY_CAP=1.0 (不限) | .env |
| SN partial b | 0.50 (Step 6-H 唯一有效 Modifier) | .env, CLAUDE.md §策略配置 |
| 月度 LLM 预算 | $50/month (80% warn + 100% cap) | .env LLM_MONTHLY_BUDGET_USD + budget.py |
| L4 触发 default | OFF (沿用 ADR-027 短期 path), 长期 STAGED + 反向决策权 | ADR-027 §2.1 |
| 真账户 cash floor | ¥993,520.66 (sustained 4-29 清仓 sediment) | xtquant query_asset() |
| 日内 drawdown threshold | -3% L1 / -5% L2 / -8% L3 / Crisis regime L4 | qm_platform/risk/rules/ |
| 单笔下单 max | sustained PT_TOP_N constraint (¥1M / N) | derived |

---

## §3 AI Tool 使用偏好

| 偏好 | Setting |
|---|---|
| 主 LLM | DeepSeek V4-Flash (NewsClassifier / FundamentalSummar / Embedding) + V4-Pro (Bull/Bear/Judge/Reflector) |
| Fallback chain | V4 → qwen3-local Ollama (router.py:120) |
| Embedding | BGE-M3 1024 维 (V3 §20.1 #3 + ADR-028 §2.3) |
| AI 辅助 panel | 已 wire 4 entry points (Frontend v3 W6) — PipelineConsole / Dashboard / FactorLab / StrategyWorkspace |
| LLM CRIT ops boundary | NEVER LLM-triggered: execute_phase / env_flip / emergency_close / pause_trading / L4 force-reset (S9 §45.2) |
| Claude Code 模式 | Continuous mode (sustained 5-19 ~21:00 user "做完一个就接着下一个") |
| Plan v8 framework | 沿用 quarterly audit cadence (2026-08-01 next) |

---

## §4 Time Zone + Working Hours

| 维度 | Value |
|---|---|
| 交易时区 | Asia/Shanghai (内部 UTC, 展示 SH per 铁律 41) |
| User 工作时区 | Asia/Shanghai (sustained) |
| User 主要 active 时段 | Unknown sediment, CC 推断 daytime SH (沿用 commit timestamps) |
| Beat timezone | `Asia/Shanghai, enable_utc=False` (celery_app.py:43) |
| Beat 主要 fire 集中 | 09:00-20:30 SH trading hours + 22:00-23:00 SH gp-weekly Sun |

---

## §5 Trading Strategy Intent

### 5.1 Active strategy

- **CORE3+dv_ttm WF Sharpe=0.8659** (2026-04-12 PASS)
- Equal-weight (Step 6-G/H NO-GO on MVO/RP/BL, 等权最优 sediment)
- Partial Size-Neutral b=0.50 (Step 6-H 唯一有效 Modifier)
- Top 20 (灰度 5-18 PT_TOP_N=5)

### 5.2 Strategy edge philosophy

- Alpha source: 流动性溢价 (turnover) + 低波异象 (volatility) + Value FF (bp_ratio) + Dividend yield cash flow (dv_ttm)
- 模式: 简单线性 avg, 反 ML/MVO (Phase 2.1/2.2/3D 5 次独立验证 NO-GO)
- Capacity ceiling estimated ~¥10-30M for Top-5 小盘/中盘 universe (S7 §36.3)

### 5.3 Failed direction 8 项 (sustained 不重复 propose)

per CLAUDE.md §已知失败方向:
- 风险平价 / 最小方差权重 (G2 7组实验)
- 同因子换 ML 模型 / 完美预测 + MVO (G1 + 系列)
- Universe filter 替代 SN (Phase 2.4 Part 1)
- 第 5 因子加入 CORE3+dv_ttm (Phase 3B + 3E)
- Phase 3D LightGBM ML Synthesis (Phase 3D 4 实验全 FAIL)
- Vol-targeting / DD-aware Modifier (Step 6-G/H)
- Regime 线性检测 / 动态 beta (Step 6-E/H)
- RD-Agent / Qlib 数据层迁移 (阶段0 调研)
- E2E 可微 Sharpe Portfolio 优化 (Phase 2.1 Layer2 sim-to-real gap 282%)
- PMS v2.0 组合级保护 (v3.6 验证 p=0.655)
- LLM 自由生成因子 (IC=0.006-0.008)
- mf_divergence 独立策略 (GA2 证伪)

---

## §6 Backup + DR Knowledge

### 6.1 Daily Backup

- `scripts/pg_backup.py` 每日 daily dump (14.46 GB 5-18, 沿用 P0-3 finding — pg_restore 0 verify in 2026)
- monthly `20260501.dump` exists
- 0 cloud mirror / 0 off-site copy (P0-3 + S7 §38)

### 6.2 Rollback paths

- .env edits: `logs/.env-backup-pre-*.bak` chain (沿用 PR #169 + ADR-027 §7 + LL-105 SOP-6)
- schtask: Disable-ScheduledTask + Servy restart
- Beat schedule: comment-out + Beat restart
- Code: git revert + Servy restart

---

## §7 Hardware / Vendor Lock-In

### 7.1 Critical single vendors

| Vendor | Service | Backup? |
|---|---|---|
| 国金 miniQMT | 交易 broker | ❌ 0 backup, sustained P0 (S6 §25.1) |
| Tushare | 主数据源 | ⚠️ partial Baostock minute_bars fallback only (P1-33) |
| DeepSeek | 主 LLM | ✅ qwen3-local Ollama fallback (P2) |
| DingTalk webhook | 告警 | ❌ HMAC outbound disabled (P1-43) + 0 SMS/email backup (S6 §25.8) |
| Servy v7.6 | Windows service mgr | 0 backup (substitute NSSM possible) |
| PostgreSQL 16.8 + TimescaleDB 2.26.0 | DB | ❌ 0 hot standby (P0-3) |

### 7.2 Hardware

- R9-9900X3D 12C/24T + RTX 5070 12GB + 32GB DDR5
- **32 GB sustained 紧** (LL-009 4-03 PG OOM + LL-189 5-19 Celery OOM)
- 0 hot spare / 0 cloud failover (S6 §25.3)

---

## §8 Sediment Convention

### 8.1 Commit message style

- `docs(...)`: docs-only changes (铁律 42 直 push)
- `feat(...)`: new feature implementation
- `fix(...)`: bug fix
- `ops(...)`: operational tooling (scripts/, runbook, etc)
- Co-Authored-By line 沿用

### 8.2 LL sediment style

- `## LL-XXX: YYYY-MM-DD Session NN — Title` (沿用 LL-188/189/190 体例)
- 6 sections: 类 / Pattern / Root Cause / Remediation / 关联 / 铁律 + Heuristic backref

### 8.3 ADR sediment style

- 沿用 ADR-022 append-only 体例
- 8 sections: Context / Decision / Consequences / Anti-pattern verify / 实施 source / next step / 关联
- REGISTRY.md entry 同时 update (沿用 LL-105 SOP-6 SSOT)

### 8.4 STATUS_REPORT cadence

- Sprint close 必 sediment
- Pre-cutover gate trigger
- Post-LL P0 sediment
- 5d window observation (Day 0-5 daily)

---

## §9 What CC May Not Know (user verify)

> **User TODO**: Fill in below sections as discovered.

### 9.1 (CC seed) User preference unknowns

- Specific risk tolerance bands beyond bounds in §2?
- Preferred LLM cost trade-offs (V4-Flash vs V4-Pro per task)?
- Beat schedule expansion thresholds (e.g. when to add new Beat entry)?
- Failure response preferences (auto-rollback vs human-in-loop)?
- Communication channel priorities (DingTalk vs Email vs SMS)?

### 9.2 Domain knowledge unknowns

- 国金 miniQMT-specific quirks not in code? (e.g. fill latency patterns / API rate limits)
- A股 specific edge cases not yet caught? (T+1 / 集合竞价 / 涨跌停 / 退市 / 分红除权 quirks)
- Tushare quota / rate limit nuance?
- Sharpe target / drawdown thresholds for live trading?

### 9.3 Strategic intent unknowns

- Target capital scaling timeline (1M → 10M → 100M)?
- Multi-strategy expansion priority (PEAD / commodities / forex)?
- AI capability roadmap (V4 → V5 trigger)?
- Audit cycle preference (quarterly default vs event-driven only)?

---

## §10 Maintenance

### 10.1 Update cadence

- **Initial seed**: 2026-05-19 Session 58+1 (本 doc)
- **Recommended cadence**: Quarterly review + post-LL update + post-major-decision

### 10.2 Pruning rules

- Sediment 沿用 ADR-022 append-only (history annotation)
- Outdated bands → mark `(stale YYYY-MM-DD)` + new entry below
- 0 content delete

---

## §11 关联

- [ONBOARDING.md](ONBOARDING.md) §3-§6 — supplement context
- [audit_cadence_calendar](runbook/audit_cadence_calendar.md) §6 pre-cutover gate triggers
- [PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19](audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) §4 user touchpoint queue
- [LL-190](../LESSONS_LEARNED.md#ll-190) — sediment-then-forget pattern (本 doc 是 user-knowledge enforcement layer)
- [Plan v8 S6 §28.1](audit/V3_AUDIT_S6_STRATEGIC_AND_CONTINUITY.md) — Tribal knowledge enumerate FAIL 原始 finding

---

**End User Tribal Knowledge. Sustained user verify required to fill §9 unknowns. Quarterly review to prune outdated bands.**
