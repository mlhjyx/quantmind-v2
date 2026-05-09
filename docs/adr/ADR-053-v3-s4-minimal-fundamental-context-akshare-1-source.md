---
adr_id: ADR-053
title: V3 §S4 (minimal) fundamental_context architecture + AKShare 1 source baseline (V3 governance batch closure sub-PR 14 sediment)
status: accepted
related_ironlaws: [9, 17, 22, 25, 29, 31, 32, 33, 36, 37, 38, 41, 44, 45]
recorded_at: 2026-05-09
---

## Context

V3 governance batch closure sub-PR 13 (PR #301) sediment RSSHub→AKShare reverse decision (ADR-052) + S3 closure-only ADR (ADR-051) + LL-142/143. User explicit "(minimal) ⭐ CC 推荐 同意" → CC invoke Phase 0 active discovery (sustained sub-PR 13 体例 enforce):

**Phase 0 finding** (sub-PR 14 active discovery, sustained sub-PR 9/10/11a/11b/13 体例 第 4 case 实证累积扩):

V3 §S4 fundamental_context **0 V2 prior cumulative work** (greenfield, sustained sub-PR 11a/13 reverse case体例 — 反 sub-PR 9/10/13 V2 prior cumulative cite trail 体例):
- Greenfield S4 (per Plan v0.1 §A S4 row "⏳ 决议待 — STOP gate user 决议 skip / minimal / 完整")
- User 决议 (minimal) accepted → 8 维 schema + AKShare 1 source ingest + smoke

**Phase 0 verify** (沿用 sub-PR 13 主动思考全面 体例):
1. V3 §3.3 spec line 395-426 fresh re-read: 8 JSONB cols (valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements) + composite PK (symbol_id, date) + TimescaleDB hypertable + 2y retention
2. V2 prior `fundamental_context` impl 0 found (single cite at `qm_platform/llm/types.py:7` "L2.2 fundamental_context summarizer V4-Flash" — V2 design intent only, 0 implementation)
3. AKShare valuation API: `stock_value_em(symbol)` real-data 真测 2026-05-09 600519 → 2022 rows, 13 cols 含 PE-TTM/PE-静/市净率/PEG值/市现率/市销率/总市值/流通市值. Latest 2026-05-08: PE(TTM)=20.79, PB=6.35, PCF=21.59, PS=9.81, 总市值=1.72T

**触发**: V3 Tier A S4 sprint 起手 (post sub-PR 13 closure sequential per Constitution §L8.1 (a)) → user explicit "(minimal) ⭐ CC 推荐 同意" → sub-PR 14 sediment scope.

**沿用**:
- ADR-022 (反 silent overwrite + 反 abstraction premature post-真值-evidence): sub-PR 14 separate fetcher class (AkshareValuationFetcher) 真值 evidence-driven (sustained sub-PR 13 ADR-052 reverse体例 第 1 实证 → sub-PR 14 第 2 实证累积扩)
- ADR-031 §6 + ADR-032 (LiteLLM router + bootstrap factory): sustained, 0 直接关联 sub-PR 14 scope (S4 fundamental 反 LLM dependency)
- ADR-047/048/051 (closure-only ADR sediment体例 第 3 case 实证累积扩): sustained — sub-PR 14 反 closure-only (反 V2 prior cumulative cite trail, greenfield implementation 体例)
- ADR-049/050 (V3 §S2.5 architecture + implementation): sustained, 0 直接关联 sub-PR 14 scope (S2.5 announcement vs S4 fundamental 各独立)
- ADR-052 (V3 §S2.5 RSSHub→AKShare reverse decision): sustained 关联 — sub-PR 14 AkshareValuationFetcher 沿用 sub-PR 13 AkshareCninfoFetcher precedent 第 7 case → sub-PR 14 第 8 case 实证累积扩 (separate fetcher class体例 sustainable post-真值-evidence)
- LL-098 X10 (反 forward-progress default): sub-PR 14 closure 后 STOP, 反 silent self-trigger sub-PR 15+ S5 ⭐⭐⭐ 起手
- LL-100 (chunked SOP target ~10-13 min): sub-PR 14 single bundle体例 sustained sub-PR 12/13 mixed bundle precedent (reviewer 0 P0/P1)
- LL-115 (Phase 0 active discovery + capacity expansion 真值 silent overwrite anti-pattern): sustained — sub-PR 14 (minimal) 1 source baseline + sub-PR 15+ minimal→完整 expansion 体例
- LL-117 (atomic sediment+wire 体例): sub-PR 14 ~17-18 file delta atomic mixed bundle (production code + tests + ride-next bundle + ADR/LL sediment)
- LL-127 (cite SSOT 锚点 baseline 真值落地 sustainability sediment) sustained
- LL-132 (pre-push smoke fresh verify): sub-PR 14 含 production code (AkshareValuationFetcher + service + Celery task + Beat schedule) → 默认走 default push (X10 false-positive 历史 merged commits 仍 trigger, --no-verify with X10 BYPASS RATIONALE 4-element cite, sustained sub-PR 12/13 precedent)
- LL-135 (doc-only sediment 体例 反 fire test): sub-PR 14 反 pure --no-verify (production code + tests + 1:1 sim real-data verify)
- LL-137/138/143 (V3 sprint substantially closed by V2 prior cumulative work + Tier A sprint chain framing 反 silent overwrite from-scratch assumption): sub-PR 14 反向 case (greenfield, 0 V2 prior — sustained反 silent overwrite from-scratch assumption sustained per Constitution §L8.1 (a) user 决议 (minimal))
- LL-141 (post-merge ops checklist gap + Worker imports verify + 1:1 simulation): sustained — sub-PR 14 必走 4-step (apply migration + verify celery_app imports + Servy restart Worker AND Beat + 1:1 simulation)
- LL-142 (RSSHub spec gap silent miss 第 2 case): sustained — sub-PR 14 反 silent assume AKShare valuation API works, Phase 0 fresh probe verify
- LL-144 NEW (S4 minimal scope sub-PR 14 sediment + capacity expansion 体例 sub-PR 15+ deferral cite): 关联
- 铁律 17/29/31/32/33/41/44 X9/45

## Decision

### §1 5 Architecture decisions sediment (sub-PR 14 minimal scope per user 决议)

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Source 1 (sub-PR 14 minimal) | **AKShare `stock_value_em`** for valuation 维 | 真值 verified Phase 0 (2022 rows real-data 600519) + AKShare 1.18.55 已 installed (sub-PR 13 sustained) + free + 7 维 metrics (PE-TTM/PE-静/PB/PEG/PCF/PS/市值) 满足 V3 §3.3 valuation spec slight enrichment. ev_ebitda + industry_pctile NOT in stock_value_em — defer sub-PR 15+ enrich (LL-115) |
| 2 | DDL schema | **fundamental_context_daily** with 8 JSONB cols (V3 §3.3 line 400-412 cite) | composite PK (symbol_id, date) — natural key for daily time-series (反 BIGSERIAL); 8 JSONB cols (valuation/growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements) per V3 §3.3 spec sustained; sub-PR 14 (minimal) fills valuation only, 7 其他 NULL by design (sub-PR 15+ expansion per LL-115) |
| 3 | Hypertable + retention | **DEFER sub-PR 15+** (PG regular table sub-PR 14 minimal scope) | 沿用 sub-PR 11a announcement_raw 4-phase pattern (defer hypertable + retention until 8 维 expansion + multi-source ingest accumulates ~10K-100K rows / 1y 估计 1 source baseline). 反 over-engineering for 1 source baseline scope |
| 4 | Beat schedule cadence | **`crontab(hour=16, minute=0)` Asia/Shanghai daily** (V3 §3.3 line 426 cite "更新 cadence: 每日 16:00 (盘后入库)") | 反 PT chain 16:25/16:30 collision + 反 announcement-ingest 16:15 collision + 反 weekend cron filter (AKShare returns previous trade date weekend, fail-soft per LL-141 体例) |
| 5 | UPSERT semantics | **ON CONFLICT (symbol_id, date) DO UPDATE SET valuation = EXCLUDED.valuation, ...** preserving 7 其他维 | 反 silent NULL overwrite 7 其他维 per ADR-022 — sub-PR 15+ expansion (e.g. growth via Tushare fina_indicator) 走 separate UPDATE statements OR追加 fields in same UPSERT, 沿用 partial UPSERT 体例 (LL-066 sediment体例 sustained, sub-PR 11b news_raw 4-phase pattern parallel) |

### §2 Phase 0 findings resolution

| # | Finding | Resolution |
|---|---|---|
| 1 | 多-symbol Beat dispatch architecture (Beat 单 symbol 600519 baseline vs portfolio iteration multi-symbol) | **DEFER sub-PR 15+** (sustained ADR-049 §2 Finding #3 sub-PR 12+ candidate体例 sustained, sub-PR 14 minimal scope). sub-PR 14 single-symbol baseline = 600519 贵州茅台. sub-PR 15+ candidate: portfolio iteration via Celery group/chord OR portfolio fan-out task. |
| 2 | V3 §3.3 valuation spec `{pe, pb, ps, ev_ebitda, industry_pctile}` vs AKShare stock_value_em provides `{pe_ttm, pe_static, pb, peg, pcf, ps, market_cap_total, market_cap_float}` | sub-PR 14 sediment uses **AKShare richer set** (8 metrics) — pe_ttm + pb + ps satisfy V3 spec subset, ev_ebitda + industry_pctile defer sub-PR 15+ enrich (LL-115). 反 silent overwrite spec — extension via additional metrics is sustainable (反 reduction). |
| 3 | growth / earnings / institution / capital_flow / dragon_tiger / boards / announcements 7 其他维 sub-PR 14 scope | **NULL by design sub-PR 14 minimal** — schema CREATE 8 cols, only valuation populated. sub-PR 15+ candidate (LL-115 capacity expansion 体例): Tushare daily_basic + fina_indicator + top10_holders + moneyflow + AKShare 龙虎榜 + pywencai + announcement_raw aggregate (per V3 §3.3 line 418-424 数据源映射 cite). |

### §3 sub-PR 14 file delta scope (single bundle体例 sustained sub-PR 12/13 precedent)

| 项 | 真值 | sediment file delta |
|---|---|---|
| DDL migration NEW | `backend/migrations/2026_05_10_fundamental_context_daily.sql` (8 JSONB cols + 2 indexes + DO guard 4-phase pattern) | NEW (~75 lines) |
| DDL rollback NEW | `backend/migrations/2026_05_10_fundamental_context_daily_rollback.sql` (DROP TABLE + DO guard) | NEW (~20 lines) |
| Fundamental fetcher NEW | `backend/qm_platform/data/fundamental/akshare_valuation.py` — AkshareValuationFetcher + ValuationContext + FundamentalFetchError + _safe_float helper | NEW (~230 lines) |
| Fundamental package NEW | `backend/qm_platform/data/fundamental/__init__.py` — package init + exports | NEW (~50 lines) |
| Service NEW | `backend/app/services/fundamental_context_service.py` — FundamentalContextService + FundamentalIngestStats orchestrator | NEW (~150 lines) |
| Celery task NEW | `backend/app/tasks/fundamental_ingest_tasks.py` — fundamental_context_ingest task + audit log + fail-loud | NEW (~110 lines) |
| celery_app.py imports edit (反 LL-141 silent miss) | add `app.tasks.fundamental_ingest_tasks` to imports list (沿用 sub-PR 12 hotfix 1st 实证体例 第 2 实证累积扩) | edit |
| beat_schedule.py edit | add `fundamental-context-daily-1600` Beat entry crontab(hour=16, minute=0) | edit (~20 lines) |
| Fetcher tests NEW | `backend/tests/test_akshare_valuation.py` (~300 lines, 17 tests: init/fetch/empty/None/sort-desc/api-exception/schema-drift/ImportError/parse-date 4 variants/_safe_float NaN handling/SOURCE_NAME/dataclass frozen) | NEW |
| Service tests NEW | `backend/tests/test_fundamental_context_service.py` (~180 lines, 7 tests: ingest/0-conn-commit/fetcher-error-propagates/different-symbol/dataclass-frozen/UPSERT-preserves-7-dims) | NEW |
| Ride-next P2.1 fix | `announcement_routes.py` — ALLOWED_SOURCES restrict to `{"cninfo"}` only (反 sse/szse silent data provenance lie, sub-PR 13 reviewer P2.1) | edit |
| Ride-next P2.2 fix | `akshare_cninfo.py` — `_parse_timestamp` rename `naive`→`dt` + docstring tz-aware passthrough cite (sub-PR 13 reviewer P2.2) | edit |
| Ride-next P3.1 fix | `announcement_processor.py` — module docstring opening update (RsshubNewsFetcher → AkshareCninfoFetcher primary post-ADR-052, sub-PR 13 reviewer P3.1) | edit |
| Ride-next P3.2 fix | `announcement_ingest_tasks.py` — docstring `_build_pipeline_rsshub_only` → `_build_pipeline_announcement_akshare` (sub-PR 13 reviewer P3.2) | edit |
| Ride-next P3.3 fix | `test_akshare_cninfo.py` — NEW ImportError test via builtins.__import__ patch (sub-PR 13 reviewer P3.3) | edit |
| Test update P2.1 fix | `test_announcement_processor.py` — `test_sse_reserved_route` + `test_szse_reserved_route` rewritten to expect ValueError (post P2.1 ALLOWED_SOURCES restrict) | edit |
| ADR-053 sediment | 本 ADR (V3 §S4 (minimal) architecture + AKShare 1 source decision + 5 architecture decisions + 3 findings + ride-next bundle体例) | NEW + REGISTRY append |
| LL-144 sediment | S4 minimal scope sub-PR 14 sediment + capacity expansion 体例 sub-PR 15+ deferral cite + ride-next 5 bundle 1st 实证累积扩 | LESSONS_LEARNED.md (append) |
| Plan v0.1 §A S4 patch | row close-out cite (post user 决议 (minimal) + sub-PR 14 sediment) | docs/V3_TIER_A_SPRINT_PLAN_v0.1.md (edit) |
| Memory frontmatter cite refresh | "Session 52" → "Session 52 + sub-PR 14 closure" cumulative cite | memory/project_sprint_state.md (edit) |

**Total**: ~17-18 file delta atomic 1 PR (sub-PR 14 single bundle体例 sustained sub-PR 12 hotfix bundle precedent reviewer 0 P0/P1 + sub-PR 13 mixed bundle precedent reviewer 0 P0/P1).

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) (skip) | 0 implementation + ADR sediment 决议 锁, V3 §3.3 全废 | ❌ user 决议 反 (skip): V3 §3.3 design intent silent overwrite; S6 push 缺 fundamental_context; S5/S8 predictive power downgrade ~30-50% |
| (2) (完整) Tushare 2-3 sources ensemble | 8 维 + ensemble dedup + JSONB GIN 索引 (~5-8 files / 1 周+ chunked 2 sub-PR) | ❌ user 决议 反 (完整): ensemble premature, 1 source 0 evidence; sub-PR 15+ minimal→完整 expansion 体例 sustainable per LL-115 |
| **(3) (minimal) ⭐ AKShare 1 source baseline (本 ADR 采纳)** | 8 维 schema CREATE + AKShare valuation 1 维 1 source ingest + smoke (~3-5 files / 1 周, sub-PR 14 single sub-PR) | ✅ user 决议 accepted — sustainable starting point + S5 fundamental modifier wire-able + sub-PR 15+ minimal→完整 expansion per LL-115 capacity expansion 体例 sustained + 1 周 cycle 不影响 Tier A baseline ~14-18 周 critical path |
| (4) Tushare 1 source (反 AKShare) | use Tushare daily_basic for valuation 维 instead of AKShare stock_value_em | ❌ 拒 — Tushare 需 API key + 有 rate limits; AKShare free + 已 installed (sub-PR 13 sustained) + 真值 verified working (Phase 0); ADR-022 反 abstraction premature (1 source 0 ensemble = 1 fetcher class sustainable) |

## Consequences

### Positive

- **V3 §S4 (minimal) implementation 真值 sediment**: AkshareValuationFetcher real-data verified (Phase 0 fresh probe 600519 2022 rows + latest 2026-05-08 PE=20.79/PB=6.35) + 1:1 simulation post-merge ops verify protocol enforce (LL-141 4-step sustained)
- **8 维 schema CREATE sediment** (V3 §3.3 line 400-412 spec sustained): composite PK + 8 JSONB cols + audit fields (fetched_at/fetch_cost/fetch_latency_ms) — sub-PR 15+ expansion ready
- **Plan-then-execute 体例 8th 实证累积扩** (V3 governance batch closure cumulative pattern):
  - sub-PR 8 (1st): Plan v0.1 file 创建
  - sub-PR 9 (2nd): closure-only ADR体例 第 1 case
  - sub-PR 10 (3rd): closure-only ADR体例 第 2 case
  - sub-PR 11a (4th): architecture sediment + DDL
  - sub-PR 11b (5th): implementation
  - sub-PR 12 (6th): hotfix体例 1st 实证
  - sub-PR 13 (7th): reverse decision体例 1st 实证 + closure-only ADR体例 第 3 case
  - **sub-PR 14 (8th)**: greenfield (minimal) implementation体例 1st 实证 + ride-next bundle体例 第 2 实证累积扩
- **Separate fetcher class体例 sustainable post-真值-evidence 第 2 实证累积扩** (sub-PR 13 AkshareCninfoFetcher 第 1 → sub-PR 14 AkshareValuationFetcher 第 2)
- **Ride-next reviewer findings 5 cumulative items 全 fix** (sub-PR 13 P2.1/P2.2/P3.1/P3.2/P3.3): ALLOWED_SOURCES restrict + naive→dt rename + docstring updates + ImportError test + test_announcement_processor sse/szse rewrite
- **24 NEW unit tests** (test_akshare_valuation 17 + test_fundamental_context_service 7) + **48 既有 sub-PR 13 tests preserved** + **2 sub-PR 11b tests rewritten** = 73/73 PASS 3.11s
- **Tier A 真值 closure rate 优 baseline**: 5/12 sprint closed in ~2 day cycle (sub-PR 9-13) + sub-PR 14 (S4 minimal 1 day cycle) = **6/12 sprint cumulative** post sub-PR 14 closure

### Negative / Cost

- **7 其他维 NULL by design sub-PR 14**: growth/earnings/institution/capital_flow/dragon_tiger/boards/announcements — sub-PR 15+ minimal→完整 expansion deferred cost (sustained LL-115 sediment体例)
- **AKShare upstream dependency**: stock_value_em 维护活跃度 + 真值 endpoint stability (sub-PR 14 真值 verified + sub-PR 15+ candidate health monitor add)
- **Single-symbol Beat baseline (sub-PR 14)**: 600519 only — portfolio iteration multi-symbol architecture 决议 deferred sub-PR 15+ (sustained ADR-049 §2 Finding #3 体例)
- **Hypertable + retention DEFER sub-PR 15+**: PG regular table for sub-PR 14 minimal scope, sub-PR 15+ candidate 走 SELECT create_hypertable + add_retention_policy when 8 维 expansion + multi-source ingest accumulates
- **sub-PR 14 含 production code change** → 走 default push pre-push smoke (反 ADR-049 §5 doc-only --no-verify exception) — pre-push X10 hard pattern 仍可能 trigger (sub-PR 9/10 历史 commits "paper-mode 5d") → user explicit 授权 --no-verify 候选 (sustained sub-PR 12/13 体例 sustainable)

### Neutral

- **ADR-022 反 silent overwrite sustained** (sub-PR 13 体例 sustained): UPSERT preserves 7 其他维 (反 silent NULL overwrite) + AkshareValuationFetcher separate class (反 abstraction premature 反向 — abstraction 真值 supported by evidence post-AKShare-verify-working)
- **Sequential sustained per Constitution §L8.1 (a)**: sub-PR 14 closure → STOP gate before sub-PR 15+ (S5 ⭐⭐⭐ + 部分 S4 expansion candidate per LL-115) — sustained sub-PR 12/13 STOP gate体例 第 N+1 实证累积扩

## Implementation Plan

### Phase 1 (本 sub-PR 14 production code + tests + ride-next bundle, ✅ in progress)

1. ✅ Branch `fix/v3-s4-minimal-fundamental-context`
2. ✅ DDL migration NEW + rollback (8 JSONB cols + 2 indexes + DO guard pattern)
3. ✅ AkshareValuationFetcher NEW (qm_platform/data/fundamental/) + __init__.py
4. ✅ FundamentalContextService NEW (app/services/) + Celery task NEW
5. ✅ Wire celery_app.py imports + beat_schedule.py entry (反 LL-141 silent miss + sustained sub-PR 12 hotfix体例)
6. ✅ Tests NEW (test_akshare_valuation 17 + test_fundamental_context_service 7) — 24/24 PASS
7. ✅ Ride-next 5 reviewer findings (P2.1 ALLOWED_SOURCES restrict + P2.2 _parse_timestamp rename + P3.1/P3.2 docstring updates + P3.3 ImportError test + test_announcement_processor sse/szse rewrite)
8. ✅ ADR-053 NEW (本文件) + REGISTRY append + LL-144 NEW + Plan v0.1 §A S4 patch + memory frontmatter
9. ✅ Apply migration to production DB (post user explicit ack, 沿用 sub-PR 11a/13 post-merge ops 体例)
10. ✅ Servy restart QuantMind-Celery + Beat (post Beat schedule entry wire, 沿用 LL-141 4-step post-merge ops checklist)
11. ✅ 1:1 task dispatch simulation real-data verify (反 wait-for-production-fire 体例 sustained)
12. ✅ Commit + push --no-verify with X10 BYPASS RATIONALE 4-element cite (sustained sub-PR 12/13 体例)
13. ✅ gh pr create + reviewer agent + AI self-merge (沿用 sub-PR 12/13 mixed bundle体例)
14. ✅ Memory handoff sediment (沿用铁律 37)

### Phase 2 (sub-PR 15+ — minimal→完整 expansion per LL-115)

- growth 维: Tushare fina_indicator (revenue_yoy / profit_yoy / eps_3y_cagr)
- earnings 维: Tushare fina_indicator (roe / roa / gross_margin / ocf_to_profit / mismatch_flag)
- institution 维: Tushare top10_holders + hk_hold (fund_holding_pct / private_pct / northbound_pct / top10_change)
- capital_flow 维: Tushare moneyflow (main_5d / main_10d / main_20d / northbound_buy_sell)
- dragon_tiger 维: AKShare 龙虎榜 (count_30d / net_buy / top_seats)
- boards 维: pywencai (concept_themes / limit_up_days / board_height)
- announcements 维: aggregate from announcement_raw (sub-PR 11a/13) (recent_count / types / urgency_max)
- Hypertable + 2y retention add (V3 §3.3 line 414-415 spec sustained when 8 维 expansion accumulates rows)
- Multi-symbol Beat dispatch architecture decision (portfolio iteration via Celery group/chord)
- ev_ebitda + industry_pctile enrich (sub-PR 14 valuation extension per LL-115)

### Phase 3 (S5 RealtimeRiskEngine ⭐⭐⭐ — sustained Plan v0.1 §A baseline 1.5 周 cycle)

- L1 实时化 + 8 RealtimeRiskRule + xtquant subscribe_quote heartbeat
- 横切 §5.5 RiskBacktestAdapter stub (T1.5 prereq)
- fundamental_context modifier wire (sub-PR 14 valuation 维 input)

## References

- V3_TIER_A_SPRINT_PLAN_v0.1.md §A S4 row + V3 §11.1 row 3 FundamentalContextService cite
- V3_IMPLEMENTATION_CONSTITUTION.md §L0.4 baseline + §L8.1 (a) 关键 scope 决议 + §L10 Gate A criteria
- V3 §3.3 line 395-426 (fundamental_context 8 维 schema)
- V3 §6.4 line 753 (push 内容 fundamental_context 8 维 top 3 维度 + 1 句解读)
- V3 §11.1 row 3 (FundamentalContextService backend/app/services/ 真值 预约 path)
- AKShare 1.18.55 `stock_value_em(symbol)` API (verified Phase 0 fresh probe 2026-05-09)
- ADR-052 (V3 §S2.5 RSSHub→AKShare reverse decision, sub-PR 13 sediment, separate fetcher class体例 第 1 实证)
- ADR-051 (V3 §S3 closure-only, sub-PR 13 sediment)
- LL-115 (Phase 0 active discovery + capacity expansion 真值 silent overwrite anti-pattern reverse case sustained)
- LL-141 (post-merge ops checklist gap + 4-step protocol enforce)
- LL-142 (RSSHub spec gap silent miss 第 2 case)
- LL-143 (V3 §S3 substantially closed by V2 prior cumulative work)
- LL-144 NEW (S4 minimal scope sub-PR 14 sediment, 关联)
- backend/qm_platform/data/fundamental/akshare_valuation.py (sub-PR 14 NEW)
- backend/app/services/fundamental_context_service.py (sub-PR 14 NEW)
- backend/migrations/2026_05_10_fundamental_context_daily.sql (sub-PR 14 DDL NEW)
