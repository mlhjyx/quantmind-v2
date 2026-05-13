# V3 实施期 Tier A Sprint Plan v0.1 (S1 + S2 + S2.5 + S3-S11, 12 sprint)

> **本文件 = V3 风控长期实施期 Tier A 12 sprint chain 起手前 user-approved plan sediment** (post-Finding 决议落地 真值, root level path per Push back #1 (i) accept).
>
> **Status**: ✅ User approved (plan v0.3, post-4 决议: Finding #1 (b) + #2 (b) + #3 (a) + Push back #1 (i) / #2 ack / #3 (b)). Sediment from workspace plan content (post-Push back #2 ack copy 体例).
>
> **本文件版本**: v0.1 (post-Tier A plan phase user approval sediment, 2026-05-09, V3 governance batch closure sub-PR 8 — Finding #1 (b) + #2 (b) + #3 (a) + 3 push back accept)
>
> **scope**: V3 Tier A sprint chain (S1 + S2 + S2.5 + S3-S11, 12 sprint) plan + Finding 决议 sediment + cycle baseline 真值 + cross-sprint surface risk + Gate A criteria + paper-mode SOP + plan review trigger SOP.
>
> **not scope**: V3 spec 详细拆分 → [QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §12 / Constitution layer scope → [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) §L0-L10 / sprint-by-sprint orchestration index → [V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) §2 / sprint chain 起手 SOP entry point → [V3_LAUNCH_PROMPT.md](V3_LAUNCH_PROMPT.md) §3.
>
> **关联 ADR**: ADR-022 (反 silent overwrite + 反 abstraction premature) / ADR-037 + 铁律 45 (4 doc fresh read SOP + cite source 锁定) / ADR-044/045/046 (committed sub-PR 2)
>
> **关联 LL**: LL-098 X10 (反 forward-progress default) / LL-100 (chunked SOP target) / LL-101/103/104/105/106/115/116/117/127/132/133/134/135/136 (committed sub-PR 1) / 后续 V3 实施期 LL

---

## Context

V3 风控长期实施期入口阶段. V3 6 件套 100% closure ✅ (Constitution v0.4 + skeleton v0.3 + 13 quantmind-v3-* skill + 13 hook cumulative + 7 charter + V3_LAUNCH_PROMPT v0.2). 红线 5/5 sustained: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102. PT 暂停清仓 (4-29 user 决议).

**Why this plan**: V3_DESIGN §12.1 Tier A 11 sprint chain → 12 sprint chain (post-Finding #2 (b) S2.5 加) 起手前必走 plan-then-execute 体例 (sustained Constitution §L8.1 (a) 关键 scope 决议 + LL-098 X10 反 silent self-trigger). User invoked `quantmind-v3-sprint-orchestrator` charter. Plan v0.3 user approved → 本文件 sediment.

**Inputs fresh re-read** (sustained Constitution §L1.1 9 doc fresh read SOP + LL-116 enforce):
- [docs/V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) v0.4 §L0/L1/L5/L6/L8/L10 全 layer scope (post-PR # sub-PR 8 Finding #1 (b) + #3 (a) sediment)
- [docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) v0.3 §2.1 Tier A sprint-by-sprint table (含 S2.5 row, post-Finding #2 (b) sediment)
- [docs/V3_LAUNCH_PROMPT.md](V3_LAUNCH_PROMPT.md) v0.2 §3 sprint chain SOP entry point
- [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §11.1 12 模块 + §11.4 RiskBacktestAdapter + §12.1 Tier A sprint table + §13.1 5 SLA + §14 失败模式 12 + §15.4 paper-mode 5d
- ⚠️ `docs/RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` — fresh verify NOT FOUND; Constitution §0.1 line 35 cite annotated "(planned, not yet sediment, V3 §18.3 reserved scope, sediment 时机决议 Tier B closure 后)" per Finding #1 (b) sediment

---

## §A Per-sprint plan (Tier A S1 + S2 + S2.5 + S3-S11, 12 sprint)

Each sprint row: scope cite → acceptance → file delta order → chunked sub-PR → cycle baseline → deps → LL/ADR sediment → reviewer reverse risk → 红线 SOP → paper-mode sustained.

**Numerical thresholds留 sprint 起手时 CC 实测决议 + ADR sediment 锁** (sustained user 5-08 决议 + memory #19/#20 + Constitution §L10 footer 体例).

### S1 — LiteLLM 接入 + V4-Flash 基础

| element | content |
|---|---|
| Scope | V3 §11.1 `LiteLLMRouter` (`backend/qm_platform/llm/`, ADR-031 path); V3 §5.5 LLM 路由 (V4-Flash/V4-Pro/Ollama); skeleton §2.1. **Status (post sub-PR 9 verify)**: ✅ substantially closed by V2 prior cumulative work — 5/8 acceptance items done, 3/8 closure-only gap (cov 实测 + SLA baseline ADR + cite 调和). 沿用 ADR-047 V3 §S1 closure acceptance + SLA baseline deferred |
| Acceptance | LiteLLM SDK install + import smoke ✅ (PR #221); 3 routes provider config 走 .env ✅ (deepseek-v4-flash + deepseek-v4-pro + qwen3-local, `config/litellm_router.yaml`); `LiteLLMRouter.call()` 接口 + 7 task enum ✅ (PR #222); unit ≥95% ⚠️ (8 test files exist, 87/95 pass, 8 pre-existing CRLF env issue 不归本 sprint); LiteLLM <3s + Ollama fallback SLA baseline 实测 ⚠️ deferred to S5 paper-mode 5d period (ADR-047 sediment, 反 silent stress test); `check_llm_imports.sh` CI lint ✅ (PR #219, V3 §17.1, Gate D prereq, 沿用 .sh 体例非 .py); ADR-031 path ✅ + ADR-032 caller bootstrap ✅ |
| File delta | ~3-5 files / ~400-700 lines (retroactive — V2 cumulative ~5630 行 / 48 mock + 2 e2e tests / 0 真账户 risk PR #219-#226 + 4 follow-ups #246/247/253/255 already done by V2 Sprint 1, post sub-PR 9 verify-only + cite reconcile + ADR sediment ~300-500 lines doc-only delta) |
| Chunked sub-PR | **single sub-PR** (verify-only + cite reconcile + ADR sediment hybrid, sub-PR 9 sediment) |
| Cycle | V3 §12.1 line 1310: 1 周 baseline (实际 V2 prior cumulative ~5-6 days 5-02 → 5-07; sub-PR 9 closure cycle <1 day verify + doc sediment) |
| Dependency | 前置: 0 (起点); V2 prior work cumulative: PR #219-#226 + #246/247/253/255 ~5630 行 已 done / 后置: S2/S2.5/S3/S5/S7/S8 |
| LL/ADR candidate | **ADR-047** ✅ promote (sub-PR 9 V3 §S1 closure acceptance + SLA baseline deferred to S5); **LL-137** ✅ promote (V3 §S1 substantially closed by V2 prior cumulative work + Tier A sprint chain framing 反 silent overwrite from-scratch assumption) |
| Reviewer reverse risk | 反 hardcoded API key (sustained 数值留 CC 实测 + ADR 锁); 反 SDK silent install 漂移 (LL-115) |
| 红线 SOP | redline_pretool_block hook + quantmind-v3-redline-verify skill (5/5 query); .env 改 → STOP + push user (memory #24 (b)) |
| Paper-mode | 0 真账户 mutation, 0 broker call, sustained 红线 5/5 |

### S2 — L0.1 News 6 源 + early-return + fail-open (✅ partial RSSHub 1/4)

| element | content |
|---|---|
| Scope | V3 §3.1 News 6 源 (RSSHub 1/4 ✅ partial — 4-29 痛点 fix 上下文); 6 源 mock + integration. **Status (post sub-PR 10 verify)**: ✅ substantially closed by V2 prior cumulative work — 6 fetcher classes + DataPipeline + NewsIngestionService + 2 migrations + Beat schedule + 11 test files + ADR-033 + ADR-043 cumulative ~22 files / ~3000-4000 行 done. 沿用 ADR-048 V3 §S2 closure acceptance + 4/4 RSSHub capacity expansion deferred to S5 |
| Acceptance | 6 源 ingest paths ✅ DONE (ZhipuNewsFetcher + TavilyNewsFetcher + AnspireNewsFetcher + GdeltNewsFetcher + MarketauxNewsFetcher + RsshubNewsFetcher, `backend/qm_platform/news/`); early-return SOP ✅ DONE (DataPipeline early_return_threshold=3 + 30s timeout, PR #239); fail-open 设计 ✅ DONE (DataPipeline fail-soft per source aggregate, V3 §3.5 + V3 §14 #6); NewsIngestionService orchestrator ✅ DONE (PR #243); news_raw + news_classified DDL ✅ DONE (PR #240); API endpoint POST /api/news/ingest + /ingest_rsshub ✅ DONE (PR #244 + #254); Celery Beat schedule + cadence ✅ DONE (4-hour cron `3,7,11,15,19,23`, PR #257 + ADR-043); integration smoke 11 test files ✅ DONE; ADR-033 News 源替换 ✅ committed (5-06); ADR-043 Beat schedule + RSSHub routing 契约 ✅ committed (PR #257); **4/4 RSSHub capacity expansion** ⚠️ deferred to S5 paper-mode 5d period (LL-115 deferred architecture decision: multi-Beat-entry vs task-iterator vs route-list-arg, 沿用 ADR-047 LiteLLM SLA baseline deferred to S5 体例) |
| File delta | ~5-8 files / ~600-1000 lines (retroactive — V2 cumulative ~22 files / ~3000-4000 行 / 11 test files done by V2 sub-PR 1-7c + 8a/8b/8b-cadence cumulative PR #234-#257; sub-PR 10 closure verify-only + cite reconcile + ADR/LL sediment ~6-8 files / ~400-700 lines doc-only delta) |
| Chunked sub-PR | **single sub-PR** (verify-only + closure-only gap fix + ADR/LL sediment + Plan/Constitution/skeleton patch hybrid, sub-PR 10 sediment, sustained sub-PR 9 ADR-047 + LL-137 体例) |
| Cycle | V3 §12.1 line 1311: 1 周 baseline (实际 V2 prior cumulative ~5-6 days 5-02 → 5-07 已 done; sub-PR 10 closure cycle <1 day verify-only + doc sediment) |
| Dependency | 前置: S1 ✅ closed (PR #296 sub-PR 9 ADR-047 sediment); V2 prior work cumulative: PR #234-#257 ~3000-4000 行 已 done / 后置: S3 (NewsClassifier post sub-PR closure) / 平行: S2.5 (per user 决议 #3 (α) sequential — S2 closure 先 merge 后 S2.5 起手, 反 Plan §A S2.5 cite "parallel S2 per Push back #3 (b)" 早决议 — 沿用 Constitution §L8.1 (a) + sub-PR 9 user 决议 (a) sequential) |
| LL/ADR candidate | **ADR-048** ✅ promote (sub-PR 10 V3 §S2 closure acceptance + 4/4 RSSHub capacity expansion deferred to S5); **LL-138** ✅ promote (V3 §S2 substantially closed by V2 prior cumulative work — sustained LL-137 plan-then-execute 体例 第 2 case 实证累积扩) |
| Reviewer reverse risk | RSSHub 1/4 partial 真值需 fresh re-verify (反 silent assume 全新, LL-115); 反 6 源 hardcoded URL 漂移 |
| 红线 SOP | sustained S1; News API key 改 → STOP |
| Paper-mode | sustained S1 |

### S2.5 — L0.4 AnnouncementProcessor 公告流 ingest + parser ⭐ (Finding #2 (b) sediment, parallel S2 per Push back #3 (b)) — ✅ CLOSED sub-PR 11a (PR #298) + 11b (PR #299) + 12 hotfix bundle (PR #300) + 13 RSSHub→AKShare reverse (本 PR sediment, ADR-049 §1 Decision 3 amendment + ADR-052 NEW + LL-142 第 2 silent miss case + 1:1 simulation real-data fetched=10 真cninfo announcements 2026-05-09 23:06)

| element | content |
|---|---|
| Scope | V3 §11.1 row 5 `AnnouncementProcessor` (`backend/app/services/news/`); 公告流 巨潮/交易所 RSS; **post-Finding #2 (b) sediment** — Tier A 11 → 12 sprint. **Status (post sub-PR 11b sediment)**: ✅ COMPLETE — 架构 sediment ✅ DONE (sub-PR 11a, ADR-049: 6 architecture decisions + 3 findings resolution + chunked 2 sub-PR split) + DDL sediment ✅ DONE (sub-PR 11a, announcement_raw NEW + rollback pair) + implementation ✅ DONE (sub-PR 11b, ADR-050: AnnouncementProcessor service + Celery task + API endpoint POST /api/news/ingest_announcement + Beat schedule announcement-ingest-trading-hours + 31/31 unit tests PASSED). post-merge ops 待: announcement_raw migration apply to production DB + Servy restart QuantMind-CeleryBeat (铁律 44 X9). 沿用 ADR-049 + ADR-050 cumulative |
| Acceptance | DDL announcement_raw NEW (12 columns + 6 enum CHECK + 3 indexes, 沿用 news_raw 4-phase pattern) ✅ DONE (sub-PR 11a); ADR-049 6 architecture decisions sediment ✅ DONE (sub-PR 11a); 公告流 ingest + parser (RSSHub route reuse, sustained sub-PR 6 RsshubNewsFetcher precedent + Decision 3 ADR-049) ⏳ sub-PR 11b 待办; AnnouncementProcessor service orchestrator (`backend/app/services/news/`) ⏳ sub-PR 11b 待办; integration smoke + mock RsshubNewsFetcher tests ⏳ sub-PR 11b; fail-open 设计 per-source fail-soft (任 1 source fail, 仅缺 announcement context, V3 §3.5 + Decision 5 ADR-049) ⏳ sub-PR 11b; unit ≥80% (L0 non-critical, V3 §12.3) ⏳ sub-PR 11b; Beat schedule trading-hours cron `9,11,13,15,17 minute=15` Asia/Shanghai (Decision 4 ADR-049) ⏳ sub-PR 11b; API endpoint `POST /api/news/ingest_announcement` (Decision 6 ADR-049) ⏳ sub-PR 11b; announcement_type EXCLUDE earnings disclosure filter (避免 dedup with earnings_announcements 207K rows Tushare path, Finding #2 ADR-049 §2 resolution) ⏳ sub-PR 11b real implementation; RSS endpoint structure verify (Finding #1 ADR-049 §2 deferred) ⏳ sub-PR 11b OR S5 paper-mode 5d period (sustained ADR-047 deferred 体例) |
| File delta | ~3-5 files / ~400-700 lines (Plan §A original estimate stale per Finding #3 ADR-049 §2). **真值 (post sub-PR 11a sediment + chunked 2 split)**: cumulative ~1200-1800 lines / 2 sub-PR — sub-PR 11a (本 sediment cycle) ~600-800 lines (DDL + ADR + LL + version bumps) + sub-PR 11b (待办 implementation) ~600-1000 lines (real code + tests) |
| Chunked sub-PR | **chunked 2 sub-PR** (反 sub-PR 8 sediment 单 sub-PR 估; sustained sub-PR 8 chunked 3a/3b/3c precedent for greenfield scope, ADR-049 §3 sediment): sub-PR 11a (DDL + architecture sediment, 本 PR) → sub-PR 11b (implementation, 待 user explicit ack post sub-PR 11a closure) |
| Cycle | +0-0.5 周 baseline (Plan §A original estimate, Push back #3 (b) parallel S2 cumulative). **真值 (post sub-PR 11a sediment, ADR-049 §3 honest re-estimate)**: ~1-1.5 周 cumulative (sub-PR 11a <1 day doc-only + DDL sediment + sub-PR 11b ~0.5-1 周 implementation); replan 1.5x = ~1.5-2.25 周 |
| Dependency | 前置: S1 ✅ closed (sub-PR 9 PR #296) + S2 ✅ closed (sub-PR 10 PR #297, sustained user 决议 #3 (α) sequential 反 Plan §A "parallel S2 per Push back #3 (b)" 早决议) / 平行: 反 (sequential per ADR-049 §3 sustained) / 后置: S5 (announcement context input via downstream Redis Stream channel sub-PR 11b 待办设计) + S6 push 内容 上游 候选 |
| LL/ADR candidate | **ADR-049** ✅ promote (sub-PR 11a 6 architecture decisions + 3 findings resolution sediment); **LL-139** ✅ promote (V3 §S2.5 architecture sediment 体例 + RSSHub route reuse decision + auto mode reasonable defaults 1st sediment 实证); ADR-050 候选 (sub-PR 11b Beat trading-hours cadence + per-source fail-soft 决议 锁); LL-140 候选 (sub-PR 11b 公告流 ingest + parser 真测 finding) |
| Reviewer reverse risk | AnnouncementProcessor V3 §11.1 row 5 silent miss 风险 (LL-115 capacity expansion 真值 silent overwrite 体例); fresh re-verify 6 News 源 vs 公告流 边界 |
| 红线 SOP | sustained S1; 任 .env RSS source URL 改 → STOP + push user |
| Paper-mode | sustained S1 |

### S3 — L0.2 NewsClassifier V4-Flash + 4 profile (✅ partial — needs fresh re-verify) — ✅ CLOSED sub-PR 13 (本 PR mixed bundle) — 8/8 ✅ DONE substantially closed by V2 prior cumulative work (PR #241 sub-PR 7b.2 + PR #242 sub-PR 7b.3-v2) + ADR-051 closure-only ADR sediment 第 3 case 实证累积扩

| element | content |
|---|---|
| Scope | V3 §3.2 NewsClassifierService; 4 profile 分类; skeleton §2.1 ✅ partial; 横切 §5.4 prompts/risk eval 起点 |
| Acceptance | re-verify ✅ partial 真值 (生产 path import smoke + 类存在 + LiteLLM call wire 真测); 4 profile prompt 实测 + 历史 news 回测; prompt eval methodology baseline 起点 |
| File delta | ~2-4 files / ~200-500 lines (gap fix 候选 if ✅ partial verified false) |
| Chunked sub-PR | **single sub-PR** (if ✅ verified) OR **chunked 2** (if gap surfaces); CC 起手 fresh re-verify 决议 |
| Cycle | V3 §12.1 line 1312: 1 周 (减半 if ✅ 真值; CC 实测决议) |
| Dependency | 前置: S1, S2 / 后置: S5 (sentiment modifier 输入) |
| LL/ADR candidate | LL — ✅ partial 真值 reality grounding (cite drift detect 体例); ADR — V4-Flash 4 profile prompt iteration v0 baseline 锁 |
| Reviewer reverse risk | skeleton ✅ partial cite drift 风险 (sustained V3 governance batch sub-PR 4 reveal sub-PR 3c P3 typo precedent); fresh re-verify gap (LL-116) |
| 红线 SOP | sustained S1 |
| Paper-mode | sustained S1 |

### S4 — L0.3 fundamental_context 8 维 schema + ingest (⏳ 决议待 — STOP gate) — ✅ CLOSED sub-PR 14 (本 PR single mixed bundle) — user 决议 (minimal) accepted ⭐ (Constitution §L8.1 (a) 关键 scope 决议) — 8 维 schema CREATE + AKShare stock_value_em 1 source valuation 维 ingest + smoke + ADR-053 NEW + LL-144 NEW + sub-PR 13 ride-next 5 reviewer findings bundle体例 第 2 实证累积扩 + greenfield (minimal) implementation体例 1st 实证 (反 sub-PR 9/10/13 V2 prior cumulative cite trail closure-only ADR体例)

| element | content |
|---|---|
| Scope | V3 §3.3 FundamentalContextService; 8 维 JSONB; **user 决议待** (skip / minimal / 完整, skeleton §2.1); Constitution §L8.1 (a) 关键 scope 决议 |
| Acceptance | per-决议: skip → 0 implementation + ADR 决议 锁 / minimal → 8 维 schema only + Tushare/AKShare 1 source ingest + smoke / 完整 → 8 维 + 2-3 sources ensemble + JSONB GIN 索引 |
| File delta | per-决议: 0 / ~3-5 / ~5-8 files |
| Chunked sub-PR | per-决议: 0 / single / chunked 2 |
| Cycle | V3 §12.1 line 1313: 1 周 (or 0 if skip 决议) |
| Dependency | 前置: DataPipeline (铁律 17) / 后置: S6 |
| LL/ADR candidate | ADR # — fundamental_context scope 决议 锁 (option + 论据); LL — option 论据 sediment |
| Reviewer reverse risk | **STOP gate**: S4 起手前必 user 决议 push (memory #24 (a)). CC NOT silent self-decide (LL-098 X10) |
| 红线 SOP | sustained S1; .env Tushare/AKShare key 改 → STOP |
| Paper-mode | sustained S1 |

### S5 — L1 实时化 + 9 RealtimeRiskRule ⭐⭐⭐ ✅ DONE (sub-PR 15-17 PR #303 2026-05-11 + audit-fix PR #306 2026-05-13: P1-1 subscriber.stop unsubscribe leak + P1-2 injectable avg_volume_provider)

| element | content |
|---|---|
| Scope | V3 §11.1 `RealtimeRiskEngine` (`backend/qm_platform/risk/realtime/`); V3 §4 + 4-29 痛点 fix 核心; xtquant subscribe_quote; 9 RealtimeRiskRule (8 V3 §4.3 + LiquidityCollapse 扩展); RiskBacktestAdapter stub |
| Acceptance | xtquant subscribe_quote heartbeat (5min 无 tick → degrade 60s sync, V3 §14 #2); 8 RiskRule 实现 + unit ≥95% (L1 critical); LimitDownDetection unit (9.99/10.00/10.01/10.05/主板 vs 科创, V3 §15.2); paper smoke L0→L1→L4 mock; **L1 detection P99<5s SLA** baseline 实测 + ADR 锁; RiskBacktestAdapter 接口 stub (0 broker / 0 alert / 0 INSERT) |
| File delta | ~10-15 files / ~1500-2500 lines |
| Chunked sub-PR | **chunked ≥3 sub-PR**: 5a (RiskEngine + xtquant adapter) / 5b (8 Rules atomic chunked 4+4) / 5c (RiskBacktestAdapter stub + paper smoke); CC 起手实测决议 |
| Cycle | V3 §12.1 line 1314: 1 周 (但 integration-first override + 横切 §5.5 prereq → sub-task creep 风险, replan 1.5x = 1.5 周) |
| Dependency | 前置: xtquant 真测 verified / S3 (sentiment context) / S2.5 (announcement context) / 后置: S6 (告警 wire) / S7 (动态阈值 fed back) |
| LL/ADR candidate | ADR-029 (L1 实时化, Constitution §L10.1); LL — xtquant subscribe_quote heartbeat 真测路径; **关键 LL** — RiskBacktestAdapter 接口设计 0 broker / 0 alert / 0 INSERT 真值 (T1.5 prereq) |
| Reviewer reverse risk | 横切 §5.5 prereq 内嵌 sprint scope creep 风险 (LL-098 X10 反 sub-task creep); xtquant subscribe_quote 不熟 → OMC `architect` agent + `deep-interview`; reviewer 反 silent broker call; **integration-first override** TDD coverage gap → sub-PR sediment 后补 unit ≥95% |
| 红线 SOP | redline_pretool_block hook + quantmind-redline-guardian subagent; .env LIVE_TRADING_DISABLED double-lock verify (V3 §14 #15) |
| Paper-mode | 0 真账户 mutation, paper smoke only, broker_qmt mock |

### S6 — L0 告警实时化 (3 级 + push cadence) ✅ DONE (sub-PR 18, PR #304, 2026-05-11)

| element | content |
|---|---|
| Scope | V3 §4.5 3 级 (P0/P1/P2) + push cadence; skeleton §2.1 (TDD-first); DingTalk push (现 PR #170 c3 dingtalk_alert helper sustained 扩) |
| Acceptance | DingTalk push <10s P99 SLA baseline + ADR 锁; 3 级 priority + cadence 实测; failure mode #5 retry 3 + email backup + 系统弹窗; unit ≥80% (L0 non-critical); DingTalk smoke |
| File delta | ~3-5 files / ~400-700 lines |
| Chunked sub-PR | **single sub-PR** (atomic) |
| Cycle | V3 §12.1 line 1315: 3 day |
| Dependency | 前置: S5 / 后置: S8 |
| LL/ADR candidate | LL — DingTalk priority + cadence 真测 finding |
| Reviewer reverse risk | DingTalk webhook 双向 (S8 prereq) 内嵌 scope creep 风险 — broker_qmt sell 单红线 surface 留 S8 only; S6 单向 push only |
| 红线 SOP | sustained S1; webhook 双向 留 S8 |
| Paper-mode | sustained S1 |

### S7 — L3 dynamic threshold + L1 集成 ✅ DONE (sub-PR 19 PR #305 2026-05-11 + audit-fix PR #306 2026-05-13)

| element | content |
|---|---|
| Scope | V3 §6 DynamicThresholdEngine (`backend/qm_platform/risk/dynamic_threshold/`); ATR/beta/liquidity; skeleton §2.1 (TDD-first) |
| Acceptance (closed) | ✅ dynamic threshold **5min Beat** wired in PR #306 (`risk-dynamic-threshold-5min`, `crontab(*/5 9-14 * * 1-5)` Asia/Shanghai, NEW `backend/app/tasks/dynamic_threshold_tasks.py`) / ✅ Stress 模拟 (3 tests in TestStressSimulation) / ✅ L1 wire fed back (S7→S5 reverse loop via `RealtimeRiskEngine.set_threshold_cache`) / ✅ thresholds_cache InMemory + Redis with lazy init fallback / ✅ unit 264/264 PASS post-audit-fix |
| File delta | sub-PR 19: ~5-7 files / ~700-1000 lines (initial). PR #306 audit-fix: +6 files / +542/-10 lines (NEW task module + NEW 2 test files + 3 EDIT) + reviewer fix `9593d75`: +6 files / +170/-16 lines (TTL/raise/TODO/rate-limit/stub-warn). |
| Chunked sub-PR | sub-PR 19 single (engine + cache + DDL + 47 tests). Audit-fix split commits: `5b1aba0` (Beat wire + S5 lifecycle) + `9593d75` (reviewer P1+P2 robustness) |
| Cycle | V3 §12.1 line 1316: 1 周. actual: sub-PR 19 <1 day; audit-fix re-execution <1 day (post-user 2026-05-13 flag). |
| Dependency | 前置: S5 ✅ / 后置: S5 reverse fed back loop ✅ wired |
| LL/ADR | ADR-055 §1-§7 (sub-PR 19) + §8 Amendment 1 (PR #306 audit-fix). LL-149 Part 1 (engine sediment) + Part 2 (audit-fix re-execution lesson). |
| Reviewer reverse risk | S7→S5 reverse loop verified via tests. Beat schedule 改 → 必 restart enforce (铁律 44 X9). **Audit-discovered**: prior sub-PR 19 closure missed Plan §A line 150 acceptance "5min Beat" wire — gap closed by PR #306; sediment lesson: sprint closure must run quantmind-v3-sprint-closure-gate skill line-by-line vs Plan §A. |
| 红线 SOP | sustained S1; Beat schedule 改 → 必 restart enforce (X9) |
| Paper-mode | sustained S1 |

### S8 — L4 STAGED 决策权 + DingTalk webhook 双向 ⭐⭐⭐ ✅ DONE (8a ✅ `dbf55c0`+sediment `dc17d88`; 8b ✅ PR #307 `e68b00a`+sediment `1442998`; 8c-partial ✅ PR #308 `3a4a324`+sediment `63ec25f`; 8c-followup ✅ PR #309 `184959c`+sediment 本commit)

| element | content |
|---|---|
| Scope | V3 §11.1 `L4ExecutionPlanner` (8a ✅) + `DingTalkWebhookReceiver` (8b ✅) + Celery sweep + STAGED smoke (8c-partial ✅) + broker_qmt sell wire (8c-followup ✅); V3 §7 + 4-29 痛点 fix 核心; ADR-027 STAGED default + 反向决策权 + 跌停 fallback; skeleton §2.1 |
| Acceptance progress | **8a ✅ DONE**: ExecutionPlan 不可变 dataclass + 状态机 + valid_transition 静态查表 + cancel_deadline ADR-027 §2.2 5 guardrails + STAGED_ENABLED=False default + DDL hypertable + 4 indexes + 180d retention + 39 tests. **8b ✅ DONE** (PR #307): 3-layer architecture + HMAC-SHA256 ±5min replay + constant-time compare + 4 verbs + race-safe UPDATE + LIKE wildcard escape + asyncio.to_thread + idempotent 2xx + empty secret→503 + strict UTF-8 decode. 48 tests. **8c-partial ✅ DONE** (PR #308): Celery Beat sweep `risk-l4-sweep-1min` crontab `* 9-14 * * 1-5` Asia/Shanghai + race-safe atomic UPDATE pattern (沿用 8b) + SWEEP_BATCH_LIMIT via settings override + STAGED smoke via RiskBacktestAdapter stub (0 broker / 0 alert / 0 INSERT) + adapter isolation verify pair. 25 tests (sweep 14 + smoke 11). **8c-followup ✅ DONE** (PR #309 `184959c`): 3-layer broker wire (broker_executor PURE engine / staged_execution_service DB orchestration / qmt_sell_adapter MiniQMTBroker wrapper) + `is_paper_mode_or_disabled()` factory routing + atomic webhook commit boundary (CONFIRMED+EXECUTED together) + live broker construction failure RAISES with P0 alert (反 silent false-EXECUTED) + race-safe UPDATE WHERE plan_id=CAST(%s AS uuid) AND status IN ('CONFIRMED','TIMEOUT_EXECUTED') + BrokerCallable protocol + stub-{plan_id_prefix} order_id synthesis + error_msg length cap 200 chars. 49 tests + 1 endpoint update. Closes ADR-058 §10 deferred items 1-4 (broker wire / order_id writeback / fill_status / integration smoke). |
| File delta | 8a: 4 files / 880 insertions. 8b: 8 files / 1768 insertions + reviewer follow-up. 8c-partial: 5 files / 691 insertions + reviewer follow-up. 8c-followup: 11 files / 2067 insertions (3 NEW services/engine/adapter + 2 wire MODIFY + 3 NEW tests + 3 MODIFY tests). |
| Chunked sub-PR | **chunked into 4**: 8a ✅ / 8b ✅ PR #307 / 8c-partial ✅ PR #308 / 8c-followup ✅ PR #309. Red-line decomposition pattern 1st 实证 closed — split scope to honor red-line gates without losing momentum (sustained pattern for .env paper→live cutover / production yaml mutation). |
| Cycle | V3 §12.1 line 1317: 1-2 周 (range, replan 1.5x = 1.5-3 周). actual 8a+8b+8c-partial+8c-followup all <1 day each (high-density session). |
| Dependency | 前置: S6 ✅ / broker_qmt ✅ wired via QMTSellAdapter / 后置: S9 |
| LL/ADR | ADR-027 (design SSOT) + ADR-056 (8a impl) + ADR-057 (8b impl) + ADR-058 (8c-partial impl + red-line partial-decomposition pattern) + **ADR-059 NEW** (8c-followup broker wire + 3-layer architecture replication 3rd 实证). LL-150 (8a) + LL-151 (8b) + LL-152 (8c-partial) + **LL-153 NEW** (8c-followup sediment + 5/5 红线 关键点 explicit user ack 3-step gate pattern: AskUserQuestion choice + auto-mode classifier backstop + explicit `授权` — 1st 实证). |
| Reviewer reverse risk | broker_qmt sell 单红线触发 (8c-followup) ✅ closed via explicit user ack 3-step gate. **8a/8b/8c-partial/8c-followup 反 deepseek-style sediment gap**: 4 consecutive PRs (#307+#308+#309 + sediment) proactively wrote ADR + LL + REGISTRY + Plan amend in same session, reviewer agent invoked BEFORE merge, findings addressed BEFORE merge. 5-sprint cumulative deepseek-pattern lesson 现 sustained as enforcement (4 实证). |
| 红线 SOP | redline_pretool_block hook + quantmind-redline-guardian subagent (双层); 5/5 红线 关键点 → explicit user ack 3-step gate (AskUserQuestion + classifier backstop + 授权); 8a/8b/8c-partial/8c-followup 0 broker call (paper-mode) + 0 真账户 mutation + 0 .env mutation sustained. |
| Paper-mode | LIVE_TRADING_DISABLED=true sustained; factory routes to RiskBacktestAdapter stub (0 broker call); live mode wired but gated by 3-layer defense (factory + LiveTradingGuard + adapter exception catch). |

### S9 — L4 batched + trailing + Re-entry ⚠️ PARTIAL (9a ✅ PR #311 `a1ac5f6`+sediment 本commit; 9b pending re-entry tracker)

| element | content |
|---|---|
| Scope | V3 §7.2 batched + §7.3 trailing + §7.4 Re-entry; skeleton §2.1 (TDD-first). Chunked into 9a (batched+trailing) + 9b (re-entry + 历史回放). |
| Acceptance progress | **9a ✅ DONE** (PR #311): NEW `batched_planner.py` PURE engine (N=max(3, ceil(×0.3)), 5min stagger, per-batch 30min deadline, equal qty split + remainder forward, priority drop/volume/sentiment/code, 0-qty skip, mode routing) + NEW `trailing_stop.py` RealtimeRiskRule (replaces PMSRule v1 static per ADR-016 D-M2; activation pnl≥20%, bracket trailing % per V3 §7.3, peak ratchet, in-memory state, ATR via context.realtime). 68 tests. **Activation-vs-tracking semantic correction** (reviewer HIGH cross-finding): once activated, state persists on retrace; test-by-accident anti-pattern 1st 实证. **9b PENDING**: V3 §7.4 re-entry tracker + DingTalk push + 历史回放 smoke + between-batch re-eval Celery task + PMSRule v1 actual deprecation. |
| File delta | 9a: 4 files / 1128 insertions (planner 220 + rule 215 + tests 410 + tests 285). 9b est: ~5-7 files / ~600-900 lines. |
| Chunked sub-PR | **chunked into 2**: 9a ✅ PR #311 / 9b pending. No new 5/5 红线 触发 in either (broker dispatch reuses S8 8c-followup wire). |
| Cycle | V3 §12.1 line 1318: 1 周 (range). 9a actual <1 day. 9b TBD. |
| Dependency | 前置: S8 ✅ / 后置: S10 |
| LL/ADR candidate | LL — Re-entry 决议算法 finding |
| Reviewer reverse risk | trailing stop 历史回放 sim-to-real gap 风险 (PR #210 体例); CC 起手 fresh re-read sim-to-real gap finding |
| 红线 SOP | sustained S8 |
| Paper-mode | sustained S8 |

### S10 — paper-mode 5d dry-run + 触发率验证

| element | content |
|---|---|
| Scope | V3 §15.4 E2E paper-mode 5d; skeleton §2.1 (E2E ~不适 TDD); **横切归属 §5.6 5 SLA verify** |
| Acceptance | 5d paper-mode 跑通 + 触发率 / 误报率 / 漏报 / STAGED cancel 率 / LLM cost / 元监控 KPI 实测; **5 SLA 全满足** baseline 实测 + ADR 锁; **V3 §15.4 验收 4 项** (CC 实测决议): P0 误报率<30% / L1 P99<5s / L4 STAGED 0 失败 / 元监控 0 P0; quantmind-v3-tier-a-mvp-gate-evaluator subagent verify |
| File delta | ~2-3 files / ~200-400 lines (E2E fixture + 元监控 query + ADR sediment) |
| Chunked sub-PR | **single sub-PR** (E2E + verify report sediment, OMC `ralph` long-running 5d) |
| Cycle | V3 §12.1 line 1319: 3 day (但 paper-mode 5d real time = 5d + verify 1-2d = 1 周 候选) |
| Dependency | 前置: S5-S9 全 closed / 后置: S11 |
| LL/ADR candidate | LL — paper-mode 5d 触发率 / 误报率 baseline 真测 finding; ADR — 5 SLA 阈值 baseline 锁 |
| Reviewer reverse risk | 5d real time 风险 (schedule 漂移 / 中段 fail / 重启) — LL-098 X10 反 silent forward; 反 silent self-trigger paper→live |
| 红线 SOP | LIVE_TRADING_DISABLED=true sustained 5d 全程; quantmind-v3-pt-cutover-gate skill verify Gate E prereq |
| Paper-mode | core deliverable — 5d full paper-mode dry-run, 0 真账户 mutation |

### S11 — Tier A ADR sediment + ROADMAP 决议 (post-Finding #1 (b))

| element | content |
|---|---|
| Scope | V3 §11.1 ADR-019/020/029 + Tier A 后续 ADR sediment; ROADMAP creation 决议 (post-Finding #1 (b) sediment, sediment 时机决议 Tier B closure 后 — Tier A S11 scope 不含 ROADMAP creation); skeleton §2.1 (doc-only) |
| Acceptance | Tier A ADR 全 committed (Constitution §L10.1); LL append 全 (S1-S10 cumulative); STATUS_REPORT sediment; doc review |
| File delta | ~5-10 files / ~500-1000 lines (mostly markdown + ADR-DRAFT row promote) |
| Chunked sub-PR | **chunked ≥2 sub-PR** (sustained governance batch closure pattern PR #286-#294 7 sub-PR 体例): 11a (ADR-cumulative-batch promote) / 11b (LL-cumulative-batch promote) / 11c (STATUS_REPORT) |
| Cycle | V3 §12.1 line 1320: 1 day (但 chunked governance batch = 0.5-1 周 候选) |
| Dependency | 前置: S1-S10 全 closed / 后置: T1.5 (Constitution §L10.2 Gate B prereq) |
| LL/ADR candidate | ADR # cumulative batch promote (CC 实测 git log + REGISTRY 决议); LL append cumulative batch (sustained PR #286 体例) |
| Reviewer reverse risk | doc-only sediment (LL-135 反 fire test 体例); ROADMAP creation 留 Tier B closure 后 sediment (Finding #1 (b) sustained) |
| 红线 SOP | sustained S1; doc-only 0 broker call |
| Paper-mode | sustained S1 |

---

## §B Cross-sprint surface risk

| # | risk | mitigation |
|---|---|---|
| 1 | S2 RSSHub 1/4 partial → 真值 fresh re-verify gap | sprint 起手 fresh re-read SOP (LL-116 13 case); CC 实测 6 源 ingest 当前真值 + cite source lock 4 元素 |
| 2 | S3 ✅ partial done → 真值 fresh re-verify gap | sprint 起手 import smoke + 类存在 + LiteLLM call wire 真测 |
| 3 | S4 user 决议 (skip/minimal/完整) | **STOP + push user before 起手** (Constitution §L8.1 (a)); CC NOT silent self-decide |
| 4 | S5 横切 §5.5 RiskBacktestAdapter 接口前置 内嵌 scope creep | sub-PR 5c chunked + RiskBacktestAdapter stub only; 不做完整 12 年 counterfactual replay (留 T1.5) |
| 5 | S5/S8 integration-first override → TDD coverage gap | Constitution §L6.3 sprint-by-sprint TDD override; sub-PR sediment 后补 unit ≥95% |
| 6 | S6/S8 DingTalk webhook 双向 — broker_qmt sell 单红线 surface | quantmind-redline-guardian subagent 必 invoke; redline_pretool_block hook 5/5 query |
| 7 | S7→S5 reverse fed back loop circular dep | cite source lock 4 元素 + skeleton §2.3 reverse loop 显式 documented |
| 8 | S10 paper-mode 5d dependent on S5-S9 全 closed | 任 sprint INCOMPLETE → STOP + push user (Constitution §L8.1 (c)); replan template (Constitution §L0.4) |
| 9 | S11 ADR sediment dependent on S1-S10 cumulative LL/ADR-DRAFT row | sustained governance batch closure pattern (sub-PR cumulative batch promote, ADR-022 反 silent overwrite) |
| 10 | 跨 sprint surface — 现 13 hook + mattpocock + OMC unexpected breakage | sprint 起手 fresh-read SOP (Constitution §L0.3 step (3)); 现 hook 真测 fire log verify (LL-133) |
| 11 | sub-task creep 风险 (任 sprint 实际超 baseline 1.5x) | quantmind-v3-sprint-replan skill trigger; replan template + push user |
| 12 | sim-to-real gap 风险 (PR #210 体例) | Constitution §L10.2 Gate B 验证 + Tier A 实施期间 0 复发 audit log |
| 13 | S2 + S2.5 parallel cumulative — 资源 contention 候选 (xtquant + Tushare + RSS) | sprint 起手 资源 budget verify (32GB 内存约束 — 铁律 9); CC 真测决议 parallel scope |

---

## §C Tier A closure → T1.5 trigger STOP gate

**Constitution §L10.1 Gate A 8 checklist** (CC 实测每项):
1. V3 §12.1 Sprint S1 / S2 / S2.5 / S3 / S4 / S5 / S6 / S7 / S8 / S9 / S10 / S11 全 closed (12 sprint, post-Finding #2 (b) S2.5 加 sediment, git log + PR # + ADR REGISTRY committed verify)
2. paper-mode 5d 验收 ✅ (V3 §15.4 标准, 数值 CC 起手时实测决议 + ADR 锁)
3. 元监控 risk_metrics_daily 全 KPI 14 day 持续 sediment
4. ADR-019 + ADR-020 + ADR-029 + Tier A 后续 ADR 全 committed
5. V3 §11.1 12 模块全 production-ready (import + smoke + module health check)
6. LiteLLM 月成本累计 ≤ V3 §16.2 上限 (CC 实测 SQL llm_cost_daily aggregate)
7. CI lint check_anthropic_imports.py 生效 + pre-push hook 集成
8. V3 §3.5 fail-open 设计实测 (任 1 News / fundamental_context / 公告流 fail, alert 仍发)

**STOP gate**: Tier A S11 closure → quantmind-v3-tier-a-mvp-gate-evaluator subagent (件 5) verify 8 checklist 全 ✅ → STOP + push user (Constitution §L8.1 (c) sprint 收口决议, sustained LL-098 X10 反 silent self-trigger T1.5)

**T1.5 起手 prereq**: Gate A ✅ + RiskBacktestAdapter 已 stub (S5 sub-PR 5c) + user 显式 ack T1.5 起手 (memory #24 (a))

---

## §D Tier A 期 paper-mode 5d 真测期 SOP

**S10 sprint paper-mode 5d 监控 SOP**:
- 元监控 risk_metrics_daily 0 P0 元告警 (V3 §13.2)
- 5 SLA 满足 verify (V3 §13.1: L1<5s / News 30s / LiteLLM<3s / DingTalk<10s / STAGED 30min)
- V3 §15.4 验收 4 项 (P0 误报率<30% / L1 P99<5s / L4 STAGED 0 失败 / 元监控 0 P0)
- 数值阈值 sprint 起手 CC 实测决议 + ADR sediment 锁

**反 silent self-trigger paper→live**:
- LIVE_TRADING_DISABLED=true sustained 5d 全程
- EXECUTION_MODE=paper sustained
- redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce
- paper→live cutover NOT in S10 scope, 仅 Gate E prereq verify (Constitution §L10.5)

**Gate E PT cutover gate prereq** (Constitution §L10.5, NOT in Tier A scope, 留 Tier A + T1.5 + Tier B + 横切层 全 closed 后):
- paper-mode 5d 通过 (Gate A 部分)
- 元监控 0 P0 (Gate A 部分)
- Tier A ADR 全 sediment (Gate A 部分)
- 5 SLA 满足
- 10 user 决议状态 verify (V3 §20.1, sustained PR #216)
- user 显式 .env paper→live 授权 (4 锁: LIVE_TRADING_DISABLED / DINGTALK_ALERTS_ENABLED / EXECUTION_MODE / L4_AUTO_MODE_ENABLED)

---

## §E Tier A estimated total cycle (post-Finding #3 (a) + Push back #3 (b) cumulative)

**per-sprint baseline cite** (V3 §12.1 lines 1308-1322):

| Sprint | baseline | replan trigger 1.5x |
|---|---|---|
| S1 | 1 周 | 1.5 周 |
| S2 | 1 周 | 1.5 周 |
| **S2.5** (Finding #2 (b), parallel S2 per Push back #3 (b)) | **+0-0.5 周** | **0.75 周** |
| S3 | 1 周 (减半 if ✅ partial 真值) | 1.5 周 / 5 day |
| S4 | 1 周 (or 0 if skip 决议) | 1.5 周 / 0 |
| S5 | 1 周 (integration-first override + 横切 prereq, sub-task creep 风险高) | 1.5 周 |
| S6 | 3 day | 4.5 day |
| S7 | 1 周 | 1.5 周 |
| S8 | 1-2 周 (range) | 1.5-3 周 |
| S9 | 1 周 | 1.5 周 |
| S10 | 3 day (paper-mode 5d real time = 5d + verify 1-2d = 1 周 候选) | 1.5 周 |
| S11 | 1 day (chunked governance batch = 0.5-1 周 候选) | 1.5 周 |

**Tier A total**: ~7-9.5 周 baseline (V3 §12.1 line 1322 cite ~7-9 周 + Finding #2 (b) S2.5 parallel S2 +0-0.5 周 per Push back #3 (b), 含 buffer). **post sub-PR 9 实测真值修订**: Tier A 真 net new scope 仅 S2.5 + S5 + S7 + S9 + S10 + S11 + 部分 S2/S3 真 GAP (S1/S4/S6/S8 substantially pre-built by V2 prior work) → **真 cycle ~3-5 周** (V2 prior cumulative ~5-6 days 5-02→5-07 已 close S1+S4+S6+S8; 真 net new 6/12 sprint scope ~3-5 周)

**V3 实施期总 cycle 真值再修订** (post sub-PR 9 V2 prior work cumulative cite sediment, sustained Finding #3 (a) + Push back #3 (b) 决议落地 cumulative scope):
- progress report Part 4 baseline cite: ~12-16 周, 紧 → **修订加标注 "(实际 ~14-18 周, baseline 真值再修订 sub-PR 9 cite, post-V2 prior cumulative cite sediment)"** (sustained ADR-022 反 silent overwrite + 反 retroactive content edit)
- 真值 estimate (post sub-PR 9): Tier A 真 net new ~3-5 周 + T1.5 2-4 + Tier B 4-5 + 横切层 ≥12 + cutover 1 = **~14-18 周** (~3.5-4.5 月) — **下降 ~10-13 周** vs sub-PR 8 sediment estimate ~26-31 周
- 真值差异根因: sub-PR 8 sediment 时 silent overwrite V2 prior work cumulative cite (V3 §S1+S4+S6+S8 substantially pre-built), 反 LL-115 capacity expansion 真值 silent overwrite anti-pattern (LL-137 sediment 候选)
- replan trigger 1.5x = ~21-27 周 (~5-7 月)

**replan trigger condition** (Constitution §L0.4): 任 sprint 实际超 baseline 1.5x → STOP + push user; quantmind-v3-sprint-replan skill (件 3) trigger; replan template = 治理债 surface + sub-task creep cite + remaining stage timeline 修订

---

## §F Plan review trigger SOP (sustained, post plan v0.3 user approve)

**Plan output → STOP + 反问 user** (反 silent self-trigger Tier A S1, sustained LL-098 X10 + Constitution §L8.1 (a) 关键 scope 决议):

**user options** (sustained workspace plan v0.3 review):
- **(i)** approve plan as-is → S1 起手 (CC exit plan mode → sprint 实施 cycle, Constitution §L0.3 5 step verify + V3_LAUNCH_PROMPT §3.1 SOP)
- **(ii)** sprint 顺序修订 (e.g. S4 决议提前 / S2/S3 真值 fresh re-verify 提前 / S5 横切 §5.5 RiskBacktestAdapter 拆独立 sprint)
- **(iii)** scope 拆分 (e.g. S5 chunked 进一步拆 / S8 chunked 进一步拆)
- **(iv)** chunked sub-PR 体例修订 (sustained sub-PR 3 chunked precedent + LL-100)
- **(v)** skip 某 sprint (e.g. S4 skip / S3 skip if ✅ verified clean)
- **(vi)** 其他修订 — ✅ accepted, plan-then-execute 体例 sub-PR sediment cycle (本文件 sediment)

**user 显式 trigger Tier A S1 起手** → CC exit plan mode → sprint 实施 cycle (sustained per-sprint cycle 体例)

---

## §G 主动思考 (sustained LL-103 SOP-4 反 silent agreeing)

### (I) Plan extensions beyond user prompt

**Tier A scope vs V3 §11.1 12 模块**: Tier A scope = 9 模块 (LiteLLMRouter + NewsIngestionService + NewsClassifierService + FundamentalContextService + AnnouncementProcessor + RealtimeRiskEngine + DynamicThresholdEngine + L4ExecutionPlanner + DingTalkWebhookReceiver) + RiskBacktestAdapter stub (T1.5 prereq). Tier B scope = 3 模块 (MarketRegimeService / RiskMemoryRAG / RiskReflectorAgent). **AnnouncementProcessor (V3 §11.1 row 5)** S2.5 sediment ✅ post-Finding #2 (b).

**Sprint dependency graph 真值差异**: skeleton §2.3 cite "S3 → S5" (sentiment modifier), S2.5 → S5/S6 (announcement context, post-Finding #2 (b) sediment), 但 S4 → S6 chain (fundamental_context → push 内容) 跟 S6 prereq S5 (告警实时化) 真值有交叉 — finding 候选 cross-verify.

### (II) CC-domain push back (post-3 push back accept)

**Push back #1 — Plan v0.1 file path subdir 反 ADR-022 premature abstraction ✅ user 决议 (i) accept**: 本文件 root level path `docs/V3_TIER_A_SPRINT_PLAN_v0.1.md` (sustained V3_* naming convention + ADR-045 V3 launch prompt file path 决议体例).

**Push back #2 — Plan v0.1 content source ✅ user 决议 ack**: 本文件 content = workspace plan v0.3 真值 (post-Finding 决议落地 copy, sustained sub-PR sediment 体例 + ADR-022 反 silent overwrite).

**Push back #3 — S2.5 dependency parallel cumulative ✅ user 决议 (b) accept**: S2.5 parallel S2 (前置 仅 S1 LiteLLMRouter prerequisite). baseline +0-0.5 周, V3 实施期总 cycle ~26-31 周.

### (III) Long-term + 二阶 / 三阶 反思

**V3 实施期 Tier A plan phase 修订 6 月后 governance 演化 sustainability**:
- sustained sub-PR 1-7 governance pattern + 本 sub-PR 8 Plan 修订 parallel 体例 真值落地实证累积扩 plan-then-execute 体例 sustainability
- Tier A 12 sprint baseline 真值落地 sustainability — Tier A 7-9.5 周 cycle (含 S2.5 parallel S2 +0-0.5 周) + replan trigger 1.5x = ~10.5-14.25 周 reasonable scope
- V3 实施期总 cycle ~26-31 周临界估计真值落地 sustainability — sustained V3 governance batch closure 7 sub-PR + 本 sub-PR 8 Plan 修订 闭环 → V3 实施期 Tier A → T1.5 → Tier B → 横切层 → cutover sprint chain ~26-31 周临界估计真值落地 sustainability sediment

### (IV) Governance/SOP/LL/ADR candidate sediment

- **plan-then-execute 体例 LL/ADR 候选 sediment** — promote 时机决议 V3 实施期 Tier A S1 sprint 起手 trigger 后 OR alternative direction
- **Finding #1/#2/#3 决议落地 LL 候选** (sustained 反 silent overwrite ADR-022 + 反 silent retroactive content edit + 反 silent inflate version + 反 silent baseline drift 真值落地实证累积扩)
- **第 11 项 prompt 升级 real-world catch 8 case 候选 sediment** (sustained sub-PR 6 pre-sediment Q5 + sub-PR 1 LL # next free + sub-PR 2 ADR-DRAFT row 11-26 cumulative + sub-PR 3a Constitution 版本号真值修正 + sub-PR 5 prompt cite "32 untracked" 真值 drift + sub-PR 7 git branch -r local cache stale + sub-PR 8 反 silent baseline drift + reverse plan path subdir abstraction + Constitution header version v0.2 vs version history v0.3 entry drift 真值修正 候选第 8 case)
- **sub-PR sediment 体例 hybrid 决议 SOP LL 候选** (sustained sub-PR 4-7 hybrid + sub-PR 8 sediment 体例真值落地实证累积扩 cumulative pattern 体例文档化候选)

---

## §H Phase 0 active discovery findings (sustained LL-115 enforce + Constitution §L5.3, 全 ✅ user 决议 sediment)

### Finding #1: "和我假设不同" — RISK_FRAMEWORK_LONG_TERM_ROADMAP.md 0 存在 ✅ user 决议 (b) sediment

**Cite drift detect**:
- user prompt cite "input doc `RISK_FRAMEWORK_LONG_TERM_ROADMAP.md`"
- Constitution §0.1 line 35 cite "`docs/RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` (V3 §18.3 reserved)"
- **Fresh verify (本 plan, 2026-05-09)**: Glob `**/RISK_FRAMEWORK_LONG_TERM_ROADMAP*` → "No files found" — **真值 0 存在**
- **类型**: 存在漂移 (Constitution §L5.2 5 类漂移 #3) + cross-reference 漂移 (#5)
- **影响**: S11 sprint scope cite "ROADMAP 更新" (skeleton §2.1) — 文件 0 存在, scope 真值需修订

**user 决议** ✅ (b) accepted:
- Constitution §0.1 line 35 cite 修订加 "(planned, not yet sediment, V3 §18.3 reserved scope, sediment 时机决议 Tier B closure 后)" 标注 (反 silent overwrite ADR-022, 0 创建 ROADMAP file)

### Finding #2: "prompt 没让做但应该做" — AnnouncementProcessor scope drift ✅ user 决议 (b) sediment

V3 §11.1 row 5 列 `AnnouncementProcessor` 模块 (`backend/app/services/news/`, 公告流 巨潮/交易所 RSS) 但 skeleton §2.1 Tier A S1-S11 表 NOT explicitly cite — silent miss 风险 (LL-115 capacity expansion 真值 silent overwrite 体例).

**user 决议** ✅ (b) accepted:
- S2.5 独立 sprint (S2.5 公告流 ingest + parser, Tier A 总 sprint 11 → 12, parallel S2 per Push back #3 (b), baseline +0-0.5 周)

### Finding #3: "prompt 让做但顺序错 / 有更好做法" — V3 实施期 baseline cycle 真值修订 ✅ user 决议 (a) sediment

progress report Part 4 cite "V3 实施期 baseline ~12-16 周, 紧" (Constitution §L0.4) → 真值 cycle (§G III) ~26-31 周; replan trigger 1.5x = 18-24 周 仍 too short.

**user 决议** ✅ (a) accepted (cumulative Push back #3 (b) parallel S2 micro-adjust):
- Constitution §L0.4 baseline 修订 → ~26-31 周 (Tier A 7-9.5 含 S2.5 parallel S2 +0-0.5 周 + T1.5 2-4 + Tier B 4-5 + 横切层 ≥12 + cutover 1)
- progress report Part 4 cite 加 "(实际 ~26-31 周, baseline 真值修订 sub-PR # cite)" 标注 (sustained ADR-022 反 retroactive content edit, 仅 append 标注)

---

## §I Sub-PR 8 sediment cycle (本文件 sediment trigger)

Sub-PR 8 sediment cycle = post plan v0.3 user approve → ExitPlanMode → 3 file delta atomic 1 PR:

| # | file | scope | line delta |
|---|---|---|---|
| 1 | [docs/V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) | header v0.2 → v0.4 + §0.1 line 35 ROADMAP 标注 + §L0.4 baseline 修订 + version history v0.4 entry append | edit + append |
| 2 | [docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) | header v0.2 → v0.3 + §2.1 加 S2.5 row + version history v0.3 entry append | edit + append |
| 3 | `docs/V3_TIER_A_SPRINT_PLAN_v0.1.md` (本文件) | NEW root level file, content = workspace plan v0.3 真值 (post-Finding 决议落地, post-Push back #2 ack copy) | NEW file |

Sub-PR 8 closure → V3 实施期 Tier A S1 sprint 起手 prerequisite 全 satisfied (post-Plan 修订真值落地) → §F (vi) plan review trigger SOP STOP gate before Tier A S1 起手 sustained (LL-098 X10).

---

## Critical files reference

**Authoritative inputs** (fresh re-read 2026-05-09):
- [docs/V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) v0.4 (§L10 Gate A criteria, post-sub-PR 8)
- [docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) v0.3 (§2.1 Tier A 12 sprint table, post-sub-PR 8 S2.5 row)
- [docs/V3_LAUNCH_PROMPT.md](V3_LAUNCH_PROMPT.md) v0.2 (§3 sprint chain SOP)
- [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) (§11.1/§11.4/§12.1/§13.1/§15.4)
- [memory/project_sprint_state.md](../memory/project_sprint_state.md) (cross-session sprint state)

**Charters / skills / hooks reference** (件 3+4+5):
- 件 5 charter: `quantmind-v3-sprint-orchestrator` (used to produce §A) / `quantmind-v3-sprint-closure-gate-evaluator` / `quantmind-v3-tier-a-mvp-gate-evaluator` / `quantmind-cite-source-verifier` / `quantmind-redline-guardian` / `quantmind-risk-domain-expert` / `quantmind-prompt-iteration-evaluator`
- 件 3 skills: 13 quantmind-v3-* (fresh-read-sop / cite-source-lock / active-discovery / redline-verify / anti-pattern-guard / sprint-closure-gate / doc-sediment-auto / banned-words / prompt-design-laws / sprint-replan / prompt-eval-iteration / llm-cost-monitor / pt-cutover-gate)
- 件 4 hooks: 8 V3-batch + 5 现有 sustained (cumulative 13 .py)

---

## Verification (post-sub-PR 8 closure, in execution phase per Tier A sprint chain)

- Per-sprint Constitution §L0.3 起手 verify 5 step run
- Per-sprint quantmind-v3-fresh-read-sop skill invoke
- Per-sprint quantmind-v3-sprint-orchestrator charter invoke (sprint chain state report)
- Per-sub-PR atomic sediment+wire 体例 (LL-117) — commit + push + PR + reviewer + AI self-merge + memory handoff
- Per-sprint sprint-closure-gate-evaluator charter invoke (PASS/FAIL/INCOMPLETE)
- Tier A S11 closure → tier-a-mvp-gate-evaluator charter invoke (Gate A 8 checklist)
- 红线 5/5 sustained per sprint (redline_pretool_block hook + quantmind-v3-redline-verify skill)
- paper-mode + LIVE_TRADING_DISABLED=true sustained per sprint

---

**本文件版本**: v0.1 (post-Tier A plan phase user approval sediment, 2026-05-09, V3 governance batch closure sub-PR 8 — Finding #1 (b) + #2 (b) + #3 (a) + 3 push back accept)

**关联 sub-PR**: PR # CC sediment cycle 时实测决议 + 关联 docs/V3_IMPLEMENTATION_CONSTITUTION.md v0.4 (header + §0.1 + §L0.4 + version history) + 关联 docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md v0.3 (header + §2.1 S2.5 row + version history)

**STOP gate sustained**: 本文件 sediment 完毕 → V3 governance batch closure sub-PR 8 closure → V3 实施期 Tier A S1 sprint 起手 prerequisite 全 satisfied → §F (vi) STOP gate before Tier A S1 起手 (LL-098 X10 反 forward-progress default)
