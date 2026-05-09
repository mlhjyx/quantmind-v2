---
adr_id: ADR-052
title: V3 §S2.5 AnnouncementProcessor RSSHub→AKShare reverse decision (V3 governance batch closure sub-PR 13 sediment, ADR-049 §1 Decision 3 reverse)
status: accepted
related_ironlaws: [9, 17, 22, 25, 31, 33, 36, 37, 38, 41, 44, 45]
recorded_at: 2026-05-09
---

## Context

V3 governance batch closure sub-PR 12 (PR #300) sediment hotfix bundle + LL-141 (post-merge ops 4-step expansion) + ADR-050 §post-merge ops checklist patch. User "为什么要等10-11日才能验证？不能提前模拟一比一验证吗？" → 1:1 task dispatch simulation post-sub-PR-12-merge → User "可以，主动思考全面" → CC Phase 0 active discovery 5 parallel checks → 3 critical findings caught:

**C2 RSSHub `/cninfo/announcement/*` HTTP 404 across 5 variants probed** (sub-PR 13 Phase 0 active discovery, LL-142 sediment):
- Local RSSHub instance HTTP 404: `/cninfo/announcement/600519` / `/cninfo/announcement/szse/000001` / `/cninfo/announcement/sh.600519` / `/cninfo/announcement/sh/600519` / `/cninfo/announcement/000001`
- Local instance routes that DO work: `/jin10/news` HTTP 200 / `/eastmoney/search/A股` HTTP 200 (sustained sub-PR 6 chunk C-RSSHub Path A 4 working routes precedent)
- **Root cause**: local RSSHub instance lacks cninfo namespace plugin (HTML root mentions `cninfo/announcement/` as text reference but actual routes不存在)
- Upstream `rsshub.app/cninfo/announcement/sse/600519/gssh0600519` → HTTP 403 production block: "Due to cost considerations, we will gradually restrict access to rsshub.app... rsshub.app is intended for testing purposes only"
- RSSHub upstream issue #6102 (closed via PR #6103) confirms cninfo route was broken by website redesign — fix exists in upstream master but not in local instance build

**1:1 simulation (sub-PR 12, 22:11)**: scheduler_task_log row `status=success` `result_json={fetched: 0, ingested: 0}` — fetched=0 was misinterpreted as "data condition" but真值 was **route 404 fail-soft to empty result** (LL-142 silent miss 第 2 case, LL-141 reverse case 第 1 实证).

**触发**: user "你需要解决，可以去查询相关文档和互联网" → CC web search + WebFetch GitHub + AKShare API probe → AKShare `stock_zh_a_disclosure_report_cninfo` real-data verify (2026-04-01 ~ 2026-05-09 → 30 rows for 600519 含 5/8 回购股份/4/29 业绩说明会/4/25 一季报/4/17 年报 等) → reverse decision sub-PR 13 sediment scope.

**沿用**:
- ADR-022 (反 silent overwrite + 反 retroactive content edit + 反 abstraction premature): sub-PR 13 reverse Decision 3 但 cite trail 保留 (build_announcement_route + ROUTE_TEMPLATE 常量 sustained for backward compat with DeprecationWarning)
- ADR-031 §6 (V4 路由层 sustained) + ADR-032 (caller bootstrap factory): sustained
- ADR-033 (News 6 源换源决议) + ADR-043 (News Beat schedule): sustained, 反 cninfo 6 News 源 (cninfo 真**announcement source 反 News source**)
- ADR-049 (V3 §S2.5 architecture sediment) §1 Decision 3 amendment via 本 ADR-052: RSSHub route reuse 真值 verified broken
- ADR-050 (V3 §S2.5 implementation Beat trading-hours cadence + per-source fail-soft): sustained, sub-PR 13 0 Beat schedule change (Beat entry retains, AKShare fetcher swapped behind same task path)
- ADR-051 (V3 §S3 closure-only ADR sediment): sustained 关联 (sub-PR 13 mixed bundle)
- LL-098 X10 (反 forward-progress default): sub-PR 13 closure 后 STOP, 反 silent self-trigger sub-PR 14 S4 implementation
- LL-100 (chunked SOP target ~10-13 min): sub-PR 13 mixed bundle体例 sustained sub-PR 12 hotfix bundle precedent (reviewer 0 P0/P1)
- LL-115 (Phase 0 active discovery + capacity expansion 真值 silent overwrite anti-pattern): sustained sub-PR 13 Phase 0 5 parallel checks + WebSearch + WebFetch 真值 evidence
- LL-117 (atomic sediment+wire 体例): sub-PR 13 13-15 file delta atomic mixed bundle
- LL-135 (doc-only sediment 体例): 反 fire test 体例 — sub-PR 13 含 production code (AkshareCninfoFetcher NEW + integration + tests) + 1:1 simulation real-data verify
- LL-141 (post-merge ops checklist gap + Worker imports verify + 1:1 simulation): sustained sub-PR 13 1:1 simulation real-data verify protocol enforce 第 1 实证累积
- LL-142 (RSSHub spec gap silent miss 第 2 case + LL-141 reverse case 第 1 实证, sub-PR 13 sediment NEW): 关联
- 铁律 17 (DataPipeline 入库) / 31 (Engine 层纯计算) / 33 (fail-loud) / 41 (timezone TIMESTAMPTZ tz-aware) / 44 (X9 Beat schedule restart)

## Decision

### §1 ADR-049 §1 Decision 3 reverse: AKShare direct API replaces RSSHub route reuse

| dimension | sub-PR 11a Decision 3 (original) | sub-PR 13 reverse (本 ADR) |
|---|---|---|
| Adapter | RsshubNewsFetcher with route_path arg | **AkshareCninfoFetcher** (NEW separate class) |
| Source | RSSHub Self-hosted localhost:1200 | AKShare 1.18.55 already installed in `.venv` |
| API | RSSHub `/cninfo/announcement/{stockCode}` | `ak.stock_zh_a_disclosure_report_cninfo(symbol, market='沪深京', start_date, end_date, category='')` |
| Query semantic | route_path string (e.g. `/cninfo/announcement/600519`) | symbol_id 6-digit string (e.g. `600519`) |
| Cost | $0 (self-hosted localhost) | $0 (AKShare free, cninfo backend free) |
| Verify真测 | 0 实测 (route 0 verified, "1:1 simulation success" was 404 fail-soft to 0 items) | ✅ 1:1 simulation real-data 2026-05-09 23:06: fetched=10 real cninfo announcements for 600519 (回购股份/业绩说明会/经营数据/独立董事述职/风险评估/审计委员会/年度报告/一季报) |
| Schema | RSS 2.0 / Atom 1.0 XML feedparser | pandas DataFrame `代码/简称/公告标题/公告时间/公告链接` |
| Architecture rationale (反 abstraction premature) | sustained sub-PR 6 RsshubNewsFetcher precedent — 反 separate fetcher class体例 sustainable when route_path arg sufficient | **真值 evidence reversed**: route 0 functional, 反 separate fetcher class 0 longer rational. AkshareCninfoFetcher separate class is now 真值 grounded — sustained NewsFetcher abc + plugin 体例 sub-PR 1-7c precedent |

### §2 Backward compatibility (反 silent overwrite per ADR-022)

`backend/qm_platform/news/announcement_routes.py`:
- `DEFAULT_CNINFO_ROUTE_TEMPLATE` / `RESERVED_SSE_ROUTE_TEMPLATE` / `RESERVED_SZSE_ROUTE_TEMPLATE` constants 保留 (cite trail + sub-PR 11a Decision 3 真值 evidence sustained, ADR-022 反 silent overwrite)
- `build_announcement_route(*, source, symbol_id) -> str` 保留 with `DeprecationWarning` (sustained test backward compat 4 tests in `test_announcement_processor.py:TestBuildAnnouncementRoute`)
- `validate_source(source) -> None` NEW — extracted source enum validation (sustained 铁律 33 fail-loud + sub-PR 13 ingest 路径 reuse without route_path semantic)
- `ALLOWED_SOURCES = frozenset({"cninfo", "sse", "szse"})` NEW — enum lock

`backend/app/services/news/announcement_processor.py:ingest()`:
- before: `route_path = build_announcement_route(source, symbol_id); pipeline.fetch_all(query=route_path)`
- after: `validate_source(source); pipeline.fetch_all(query=symbol_id)` (反 RSSHub route_path semantic, 真值 reverse evidence)

### §3 SSE/SZSE additional sources deferral (sustained ADR-049 §2 Finding #1)

| dimension | sub-PR 11a (original) | sub-PR 13 reverse (本 ADR) |
|---|---|---|
| sse / szse | reserved 待 sub-PR 11b S5 paper-mode 5d period verify (RSSHub route reuse 假设) | reserved 待 **sub-PR 14+** AKShare additional source verify (`stock_zh_a_disclosure_report_*` enum check) — sustained ADR-049 §2 Finding #1 deferral体例, 反 premature 多源 expansion (LL-115 sustained) |

### §4 1:1 simulation real-data verify protocol (LL-141 第 1 实证累积扩)

**sub-PR 13 mandatory verify before sediment**:
1. AKShare API direct probe (Python REPL) — verify schema + non-zero rows for known active stock
2. Worker autodiscover post celery_app.py 0 change (反 sub-PR 11b imports gap silent miss体例)
3. Servy restart QuantMind-Celery (Worker reload AKShare module)
4. `celery_app.send_task(...)` real dispatch — verify scheduler_task_log row + result_json schema
5. `SELECT COUNT(*) FROM announcement_raw` — verify INSERT row count (filter logic transparency, sub-PR 11b conservative type filter sustained)

**Real-data evidence (2026-05-09 23:06)**:
- task_id `650ef637-9bb0-4793-a068-9239fa0fe0e7` status=success
- result_json `{fetched: 10, ingested: 0, skipped_unknown: 8, skipped_earnings: 2}` 真生产 cninfo data
- announcement_raw COUNT(*) = 0 (反 bug, 真值 conservative type filter design — 8 'other' + 2 earnings filtered per sub-PR 11b ADR-049 §2 Finding #2 cite)
- **sub-PR 14+ candidate** (sustained announcement_processor.py:138 cite "sub-PR 12+ relax based on real production traffic"): relax 'other' filter OR enrich material_event regex to capture 回购股份/业绩说明会/经营数据/风险评估/审计委员会/独立董事述职 等 真生产 categories

### §5 sub-PR 13 file delta scope

| 项 | 真值 | sediment file delta |
|---|---|---|
| AkshareCninfoFetcher NEW | `backend/qm_platform/news/akshare_cninfo.py` (~250 lines) — implements NewsFetcher abc, fetch(query=symbol_id) → list[NewsItem], 30d rolling lookback, fail-loud NewsFetchError, tz-aware UTC | NEW file |
| qm_platform/news/__init__.py export | add `AkshareCninfoFetcher` import + `__all__` entry | edit |
| announcement_routes.py reverse | add `validate_source` + `ALLOWED_SOURCES` + DeprecationWarning on build_announcement_route + ADR-052 cite | edit |
| announcement_processor.py.ingest() reverse | replace `build_announcement_route` call with `validate_source` + `pipeline.fetch_all(query=symbol_id)` | edit |
| announcement_ingest_tasks.py factory swap | `_build_pipeline_rsshub_only` → `_build_pipeline_announcement_akshare` | edit |
| api/news.py factory NEW + endpoint swap | NEW `_build_pipeline_announcement_akshare()` + `POST /api/news/ingest_announcement` swap factory | edit |
| test_announcement_processor.py update | assert `query="600519"` instead of `query="/cninfo/announcement/600519"` (sub-PR 13 ADR-052 reverse semantic) | edit |
| test_akshare_cninfo.py NEW | 17 unit tests — init / fetch success / fetch empty / fetch None / limit truncation / API exception / schema drift / timestamp helpers / NewsFetcher contract / NewsItem instances | NEW file |
| ADR-049 §1 Decision 3 amendment | strikethrough original + AMENDED row + 真值 reverse evidence cite | edit |
| ADR-051 NEW (S3 closure-only) | V3 §S3 8/8 ✅ DONE + V2 prior cumulative cite | NEW file (mixed bundle) |
| ADR-052 NEW (本文件) | V3 §S2.5 AKShare reverse decision + 1:1 simulation real-data verify | NEW file |
| REGISTRY.md append | ADR-051 + ADR-052 rows | edit |
| LL-142 NEW | RSSHub spec gap silent miss 第 2 case + LL-141 reverse case 第 1 实证 | LESSONS_LEARNED.md (append) |
| LL-143 NEW | V3 §S3 substantially closed by V2 prior cumulative work, sustained LL-137/138 第 3 case 实证累积扩 | LESSONS_LEARNED.md (append) |
| Plan v0.1 §A S2.5/S3 row patch | S2.5 row close-out cite + AKShare reverse / S3 row close-out cite + V2 prior cumulative | docs/V3_TIER_A_SPRINT_PLAN_v0.1.md (edit) |
| Memory frontmatter cite refresh | "Session 51 v7 (2026-05-03)" → "Session 52 (2026-05-09 sub-PR 8-13 cumulative)" | memory/project_sprint_state.md (edit) |

**Total**: ~14-15 file delta atomic 1 PR (sub-PR 13 mixed bundle体例 sustained sub-PR 12 hotfix bundle precedent reviewer 0 P0/P1).

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) Disable Beat entry only (defer fix) | sub-PR 13 = ops disable + LL-142 + ADR-049 amendment, defer source decision to sub-PR 14+ | ❌ 拒 — user explicit "你需要解决" 反 defer; production code change 必备 + AKShare 真值 verified working = no rational delay; 反 LL-098 X10 reverse case (defer = silent forward over broken upstream) |
| (2) Investigate RSSHub local instance build (upgrade cninfo plugin) | 投入 1-2h investigate RSSHub Docker / build config / install cninfo plugin | ❌ 拒 — RSSHub upgrade is infrastructure work scope creep + 仍 dependent on upstream cninfo HTML scraper stability + AKShare 已 installed + 已 真值 verified working = simpler path |
| (3) Use upstream rsshub.app | change RSSHub_BASE_URL env from localhost:1200 to https://rsshub.app | ❌ 拒 — rsshub.app HTTP 403 production block (RSSHub policy 2025-10+ enforcement); cost / rate-limit / political risk 反 production-grade |
| (4) Direct cninfo.com.cn HTTP scraper (DIY) | implement own scraper for cninfo HTML | ❌ 拒 — DIY complexity 高 (HTML scraper 维护成本 + cninfo 网站 redesign 风险 sustained — 即上游 RSSHub PR #6103 fix the same 真因) |
| (5) Tushare announcement API | use Tushare `pro.disclosure()` or similar | ⚠️ candidate — Tushare 已 integrated in project (earnings_announcements 207K rows); 但 ADR-049 §2 Finding #2 真值 EXCLUDE earnings_announcements scope (避免 dedup) → Tushare announcement 真值 narrow scope vs AKShare 全 cninfo announcement; sub-PR 14+ 候选 if AKShare unavailable scenarios (sustained Plan B) |
| **(6) AKShare `stock_zh_a_disclosure_report_cninfo` (本 ADR 采纳)** | implement `AkshareCninfoFetcher` separate class via NewsFetcher abc | ✅ 采纳 — AKShare 已 installed (1.18.55 in `.venv`) + API 真值 verified working (30 rows real cninfo data 2026-04 范围 for 600519) + free + 实证 cumulative ecosystem (akshare 维护活跃, cninfo 网站 fix sustained); separate fetcher class 真值 grounded post-真值-evidence (反 ADR-022 abstraction premature 反向 — abstraction 真值 supported by evidence) |

## Consequences

### Positive

- **AKShare reverse decision 真值 verified**: 1:1 simulation real-data verify 2026-05-09 23:06 fetched=10 real cninfo announcements (反 sub-PR 11b silent miss 0 fetched 真值 = 404 fail-soft); production capability functional
- **ADR-049 §1 Decision 3 amendment真值 sediment** (反 silent overwrite per ADR-022): original Decision 3 cite preserved with strikethrough + AMENDED 真值 evidence row; cite trail intact
- **NewsFetcher abc plugin 体例 sustained 第 7 case 实证累积扩** (1=Zhipu / 2=Tavily / 3=Anspire / 4=GDELT / 5=Marketaux / 6=RSSHub / 7=AkshareCninfo, sustained sub-PR 1-7c precedent + 真值 reverse case)
- **plan-then-execute 体例 7th 实证累积** (sub-PR 8 1st + 9 2nd + 10 3rd + 11a 4th + 11b 5th + 12 6th hotfix体例 + 13 7th mixed bundle reverse decision体例)
- **真值 evidence体例 sediment 第 1 case 实证累积扩**: sub-PR 11a/11b ADR-049 §1 Decision 3 cite "sub-PR 11b 待办 verify 真值 RSSHub announcement route endpoint" never actually verified; sub-PR 13 真值 verify SOP 反 silent miss 体例 enforce — Phase 0 active discovery 5 parallel checks → WebSearch + WebFetch + AKShare REPL probe → 1:1 simulation real-data verify
- **LL-142 sediment** — RSSHub spec gap silent miss 第 2 case (LL-141 reverse case 第 1 实证 体例累积扩 — silent miss 体例 自身 sediment evidence)
- **17 NEW unit tests (test_akshare_cninfo.py)** + 31 existing tests preserve (test_announcement_processor.py, 4 DeprecationWarning by design) = 48/48 PASS

### Negative / Cost

- **Architecture decision reversal in 1 day** (sub-PR 11a → 11b → 13 cumulative ~30h cycle, RSSHub route reuse 真值 broken evidence caught only at sub-PR 12 post-merge ops): cycle overhead ~10-15% Tier A baseline (~1 day vs ~14-18 周 baseline) — sustained 反 silent overwrite 体例 + 真值 evidence-driven amendment体例 sustainability cost
- **AKShare upstream dependency**: cninfo 网站 redesign / AKShare 维护活跃度 / category enum 真值 sub-PR 14+ traffic evidence based relaxation 候选 (sustained announcement_processor.py:138 cite)
- **DataPipeline single-fetcher pattern sustained** (反 multi-source dedup) — sub-PR 14+ candidate SSE/SZSE additional sources expansion deferred (sustained ADR-049 §2 Finding #1)
- **sub-PR 13 含 production code change** → 走 default push pre-push smoke (反 ADR-049 §5 doc-only --no-verify exception) — pre-push X10 hard pattern 仍可能 trigger (sub-PR 9/10 历史 commits "paper-mode 5d") → user explicit 授权 --no-verify 候选 (sustained sub-PR 12 体例 sustainable)

### Neutral

- **ADR-022 反 silent overwrite sustained**: build_announcement_route + ROUTE_TEMPLATE 保留 with DeprecationWarning + ADR-049 §1 Decision 3 strikethrough + AMENDED row (cite trail intact, sub-PR 11a sediment 体例 sustained)
- **Sequential sustained per Constitution §L8.1 (a)**: sub-PR 13 closure → STOP gate before S4 起手 (S4 user 决议 BLOCKER skip/minimal/完整 待 user explicit ack — sustained sub-PR 12 STOP gate体例 第 N+1 实证累积扩)

## Implementation Plan

### Phase 1 (本 sub-PR 13 doc + production code sediment, ✅ in progress)

1. ✅ Branch `fix/v3-s2-5-akshare-cninfo-fetcher`
2. ✅ AkshareCninfoFetcher NEW (`backend/qm_platform/news/akshare_cninfo.py`)
3. ✅ qm_platform/news/__init__.py export
4. ✅ announcement_routes.py reverse (validate_source + DeprecationWarning + ALLOWED_SOURCES)
5. ✅ announcement_processor.py.ingest() reverse (validate_source + query=symbol_id)
6. ✅ announcement_ingest_tasks.py factory swap (`_build_pipeline_announcement_akshare`)
7. ✅ api/news.py factory NEW + endpoint swap
8. ✅ test_announcement_processor.py assert update (query="600519")
9. ✅ test_akshare_cninfo.py NEW (17 unit tests)
10. ✅ Servy restart QuantMind-Celery + 1:1 simulation real-data verify
11. ✅ ADR-049 §1 Decision 3 amendment (strikethrough + AMENDED row)
12. ✅ ADR-051 NEW (V3 §S3 closure-only) + ADR-052 NEW (本文件) + REGISTRY append
13. ✅ LL-142 NEW + LL-143 NEW (LESSONS_LEARNED.md append)
14. ✅ Plan v0.1 §A S2.5/S3 row patch (close-out cites)
15. ✅ Memory frontmatter cite refresh (Session 52)
16. ✅ Commit + push (default — production code change, ADR-049 §5 sediment体例; user explicit --no-verify if X10 hard pattern false positive)
17. ✅ gh pr create + reviewer agent + AI self-merge (沿用 sub-PR 12 hotfix bundle体例)
18. ✅ Memory handoff sediment (沿用铁律 37)

### Phase 2 (sub-PR 14+ — S4 implementation per user 决议)

- per Constitution §L8.1 (a) 关键 scope 决议 — user explicit ack required: (skip) / (minimal CC 推荐) / (完整)
- minimal scope: 8 维 schema + Tushare/AKShare 1 source ingest + smoke (~3-5 files / 1 周 cycle)
- 反 silent self-trigger sub-PR 14 (sustained LL-098 X10 STOP gate before user 显式 ack)

### Phase 3 (sub-PR 14+ candidate — relax 'other' filter or enrich material_event regex)

- announcement_processor.py:138 cite "sub-PR 12+ candidate to relax based on real production traffic"
- 真值 evidence sub-PR 13 1:1 simulation: 8/10 'other' filtered (real cninfo categories: 回购股份/业绩说明会/经营数据/风险评估/审计委员会/独立董事述职)
- enrich `_PATTERN_MATERIAL` regex OR add `_PATTERN_GOVERNANCE` (董事会/监事会/审计委员会) + `_PATTERN_OPERATIONAL` (经营数据/回购股份/业绩说明会) categories
- announcement_type CHECK constraint enum expand (sub-PR 11a DDL 6 enum → 8-10 enum, alembic migration)

## References

- V3_TIER_A_SPRINT_PLAN_v0.1.md §A S2.5 row + V3 §11.1 row 5 AnnouncementProcessor cite
- V3_IMPLEMENTATION_CONSTITUTION.md §L0.4 baseline + §L8.1 (a) 关键 scope 决议 + §L10 Gate A criteria
- V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md §2.1 S2.5 row
- ADR-049 §1 Decision 3 (RSSHub route reuse, 本 ADR amendment)
- ADR-050 (V3 §S2.5 implementation, sustained, 0 Beat schedule change)
- ADR-051 (V3 §S3 closure-only, sub-PR 13 mixed bundle 关联)
- LL-141 (post-merge ops checklist gap, sub-PR 12 sediment, 1:1 simulation real-data verify protocol enforce 第 1 实证)
- LL-142 (RSSHub spec gap silent miss 第 2 case + LL-141 reverse case 第 1 实证, sub-PR 13 sediment)
- LL-143 (V3 §S3 substantially closed by V2 prior cumulative work, sustained LL-137/138 第 3 case 实证累积扩, sub-PR 13 mixed bundle 关联)
- AKShare 1.18.55 `stock_zh_a_disclosure_report_cninfo` API (verified Phase 0 fresh probe 2026-05-09)
- RSSHub upstream issue #6102 closed via PR #6103 (cninfo route fix in upstream master)
- backend/qm_platform/news/akshare_cninfo.py (sub-PR 13 NEW, AKShare cninfo fetcher implementation)
- backend/tests/test_akshare_cninfo.py (sub-PR 13 NEW, 17 unit tests)
