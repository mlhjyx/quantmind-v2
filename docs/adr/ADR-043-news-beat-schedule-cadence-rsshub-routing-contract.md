---
adr_id: ADR-043
title: News Beat schedule + cadence + RSSHub 路由层契约 (sub-PR 8b-cadence-A sediment-only, partial closure)
status: accepted
related_ironlaws: [22, 33, 41, 44]
recorded_at: 2026-05-07
---

## Context

**5-07 sub-PR 8b-cadence-A sediment trigger**: ADR-DRAFT row 2 promote target — News fetch query strategy SSOT (5 源 vs RSSHub route path 体例分裂). source cite 真值 = `V3§3.1 sub-PR 6 docstring "RSSHub 走独立 pipeline" sustained` (沿用 [`backend/qm_platform/news/pipeline.py:73`](../../backend/qm_platform/news/pipeline.py) 真值 + [`rsshub.py:1`](../../backend/qm_platform/news/rsshub.py) "V3§3.1 中文财经 RSS 长尾" + [`base.py:76`](../../backend/qm_platform/news/base.py) "sub-PR 6: RSShubNewsFetcher (自部署)").

**Sprint 2 sub-PR 8b 全 chunk cumulative sediment** (5-07 单日累计 12 PR merged + 2 sediment-only):
- sub-PR 8b-pre PR #251 hook field-level whitelist + PR #252 atomic URL drift fix ✅
- sub-PR 8b-llm-fix PR #253 Pydantic Settings → os.environ bootstrap propagate (DeepSeek primary 100% fallback 4-day production fix) ✅
- sub-PR 8b-rsshub PR #254 RsshubNewsFetcher wire route_path 独立 caller (POST /api/news/ingest_rsshub endpoint) ✅
- sub-PR 8b-gdelt closure (sediment-only, post-PR #253 classify_failed=0 sustained, fail-soft 已 in place) ✅
- sub-PR 8b-llm-audit-S2.4 PR #255 ADR-039 retry policy + transient/permanent classifier ✅

**真因 sediment**:

post-PR #254 News API endpoint 真值 sustained (反 Beat schedule register):
- `POST /api/news/ingest` (5-source: GLM/Anspire/Marketaux/GDELT/Xinhua) — manual trigger sustained
- `POST /api/news/ingest_rsshub` (route_path: 1/4 routes 真生效 + 3/4 真 503 defer audit chunk C 真预约) — manual trigger sustained
- [`api/news.py:316`](../../backend/app/api/news.py) docstring sustained: "Note (Beat schedule defer 到 sub-PR 8b-cadence): 本 endpoint 真**manual trigger** sustained. cron 频率 + dingtalk rate-limit + cost cap 决议 留 sub-PR 8b-cadence 真预约 (沿用 ADR-DRAFT row 2 sediment)"

**真现存 Beat 体例 sediment** ([`backend/app/tasks/beat_schedule.py`](../../backend/app/tasks/beat_schedule.py) 4 entries sustained):
- `gp-weekly-mining` (Sun 22:00 day_of_week=0, GP 因子挖掘)
- `outbox-publisher-tick` (30s 持续, MVP 3.4 batch 2 outbox)
- `daily-quality-report` (Mon-Fri 17:40, DATA_SYSTEM_V1 P1-2)
- `factor-lifecycle-weekly` (Fri 19:00 day_of_week=5, Phase 3 MVP A)

**真 PT chain 真 mechanism 沿用 Task Scheduler** (反 Celery Beat, [beat_schedule.py:50-52](../../backend/app/tasks/beat_schedule.py) sustained: "PT 主链任务由 Task Scheduler 驱动, Beat 不再触发 — DailySignal 16:30 / DailyExecute 09:31 / HealthCheck 16:25").

**真 Risk v2 Beat schedule 4-29 [PAUSE T1_SPRINT_2026_04_29] 7+ day sustained** ([beat_schedule.py:59 + 74](../../backend/app/tasks/beat_schedule.py) commented out, risk-daily-check 14:30 + intraday-risk-check 5min 双块) 沿用 memory #24 候选 (b) 显式 indefinite paused 体例 sustained.

**真**反**真生产真值** sub-PR 8b-cadence-A meta-verify Phase 0+1 fresh tool 真测真值 sediment (沿用 LL-105 SOP-6 4 source cross-verify + LL-110 web_fetch verify SOP):
- prompt cite "V3 §3.4" 真 fictitious (V3 §3.4 真**Parquet 缓存** 反 News Beat) — frame drift 第 9 次 catch
- prompt cite "ADR-040" 真 silent overwrite ADR-DRAFT row 8 (DeepSeek API watch SOP informal reservation) — frame drift 第 10 次 catch, N×N 同步漂移 案例 #4 候选 sustained
- 沿用 REGISTRY.md 案例 1 (ADR-024 V3§18.1 row 4) + 案例 2 (ADR-027 4 audit docs Layer 4 SOP) + 案例 3 (ADR-023 V3§18.1 row 3) 真**# 下移体例** sustained 真预约 ADR-043 (反 ADR-040)

## Decision

**6 决议 sediment** (本 ADR-043 scope, sediment-only 反 implementation patch):

1. **News Beat schedule 真 mechanism = Celery Beat** (反 Windows Task Scheduler) 沿用 4 现存 Beat entries 体例 sustained. 真**生产 active** 沿用 Servy `QuantMind-CeleryBeat` 服务 sustained ([CLAUDE.md §Servy 服务](../../CLAUDE.md) 真值).

2. **cron 频率 = `crontab(hour="3,7,11,15,19,23", minute=0)`** (4-hour offset 3h, 6/day). PT 时序 conflict 分析 sustained:
   - 03:00 / 07:00 / 11:00 / 15:00 / 23:00 真**0 conflict** sustained
   - 19:00 真**软 conflict Fri factor-lifecycle-weekly 19:00 day_of_week=5** sustained (Beat scheduler 真 sequential dispatch, 软 conflict tolerated)
   - 反 hard collision PT chain 16:25 HealthCheck / 16:30 DailySignal / 09:31 DailyExecute / 17:40 daily-quality-report sustained
   - 时区 Asia/Shanghai (`celery_app.py:42` `enable_utc=False`) sustained

3. **RSSHub 路由层契约 = standalone `POST /api/news/ingest_rsshub` endpoint sustained** (sub-PR 8b-rsshub PR #254 sediment 沿用), route_path semantic 反 search keyword. 真**Beat schedule 真 task** 真预约 sub-PR 8b-cadence-B 真**双 Beat entry**:
   - `news-ingest-5-source-cadence` (主链路 5-source ingest, 4-hour cron)
   - `news-ingest-rsshub-cadence` (RSSHub route_path ingest, 4-hour cron, 1/4 route 真生效 sustained)
   - 真**RSSHub multi-route 503** (3/4 routes) 真预约 audit chunk C 真**fix** 反**本 ADR scope** sustained.

4. **cost cap 真值 = decision sediment 沿用 ADR-DRAFT row 6 真预约** (反 implementation patch). 真因: BudgetGuard implementation 已 in place ([`backend/qm_platform/llm/_internal/budget.py:14`](../../backend/qm_platform/llm/_internal/budget.py) sustained `LLM_MONTHLY_BUDGET_USD + LLM_BUDGET_WARN/CAP_THRESHOLD`), 但 ADR-DRAFT row 6 sustained `cost_usd=None for deepseek-v4-flash + deepseek-v4-pro` (LiteLLM model_cost 0 entry) → BudgetGuard cap **永 0 trigger** for v4-* sustained until LiteLLM SDK 升级 (7-24 deadline plan, ADR-DRAFT row 6 真预约 ADR-038 reservation).

5. **dingtalk rate cap 真值 = decision sediment 沿用 sub-PR 9 alert wiring 真预约** (反 implementation patch). 真因: per-message dedup TTL 已 in place ([`config.py:113`](../../backend/app/config.py) sustained `DINGTALK_DEDUP_TTL_MIN=60` + [`dingtalk_alert.py:13`](../../backend/app/services/dingtalk_alert.py) "1h TTL 默认 severity 驱动 caller 可 override"). schedule-level rate cap (per-Beat-source max-per-hour) 真**反 implemented** sustained 真预约 sub-PR 9 alert wiring (LL_AUDIT_INSERT_FAILED 触发) 体例 sustained ADR-039:90-91 真值.

6. **Risk v2 Beat schedule 真 indefinite paused 体例 sustained** 沿用 memory #24 候选 (b) 显式 indefinite paused 体例 sustained 反**resume** in 本 ADR scope. 真**resume gate prerequisite** 真预约 PT 重启 gate ([SHUTDOWN_NOTICE_2026_04_30 §9](../audit/SHUTDOWN_NOTICE_2026_04_30.md) 体例 sustained).

## Alternatives Considered

**(1) Windows Task Scheduler 真 mechanism (沿用 PT chain 体例 sustained)** — schtask register 直触发 Python script (沿用 QuantMind_DailySignal 16:30 体例). **未选**: 4 现存 Beat entries 体例 sustained 沿用 Celery Beat (gp-weekly + outbox + daily-quality + factor-lifecycle), Beat 真**生产 active** Servy `QuantMind-CeleryBeat` 服务 sustained. Task Scheduler 真**PT chain 专属 mechanism** sustained 反 News-style sub-second tolerance 体例 — News 真**4-hour cadence** 沿用 Beat 真**timezone 自动 + Servy 集中管理** 体例 sustained.

**(2) hourly cron (24/day 高频)** — `0 * * * *`. **未选**: 真**反 cost guard** sustained — sub-PR 8b-llm-fix V4-Flash 5-07 0.0001 USD/call quote sustained, 24/day × 5-source = 120 calls/day cumulative, BudgetGuard cap 反 trigger for v4-* sustained until LiteLLM SDK 升级 (ADR-DRAFT row 6 真预约). 真**moderate cadence 4-hour** sustained 反 cost overhead risk + 反 Tushare/Anspire/Marketaux rate-limit 风险 sustained (沿用 sub-PR 8b-pre URL drift 体例).

**(3) 30-minute cron offset (`30 1,5,9,13,17,21 * * *` 沿用 daily-quality-report 17:40 体例)** — half-hour offset. **未选**: hard collision risk sustained — 09:30 close 09:31 DailyExecute (1min gap, **HARD collision risk** Beat scheduler 真 sequential dispatch + Worker `--pool=solo --concurrency=1` Windows 真**单 worker** sustained) + 17:30 close 17:40 daily-quality-report 10min gap (软 conflict 加深). 真**hour-offset 3h** sustained 真**反 hard collision** sustained.

**(4) 多 row promote 同 PR cover (ADR-DRAFT row 2 + row 6 + row 7 残余 sub-task 全 promote)** — single mega-chunk PR. **未选**: 沿用 LL-100 chunked SOP <400 line single chunk 体例 + ADR-DRAFT row 6 (LiteLLM cost registry V4 gap) 真预约 ADR-038 (LiteLLM SDK 升级 prerequisite) + row 7 (audit failure path) 真预约 ADR-039 sub-PR 8b-resilience + sub-PR 9 残余 sub-task sustained. 单 row 2 promote sub-PR 8b-cadence-A scope sustained 反 scope creep.

## Consequences

**正面**:
- News Beat schedule cadence 真**4-hour offset** sustained 反 hard collision PT chain + 4 现存 Beat entries 体例 sustained
- 沿用 ADR-037 governance pattern + ADR-031 §6 渐进 deprecate plan + ADR-032 caller bootstrap factory + ADR-039 retry policy 体例 sustained
- 真**Celery Beat 真 mechanism** sustained 沿用 Servy `QuantMind-CeleryBeat` 服务 sustained 反 PT chain Task Scheduler reverse case
- 真**RSSHub route_path semantic 独立 caller** sustained 沿用 sub-PR 8b-rsshub PR #254 sediment 真**反 5-source search keyword 体例分裂** sustained
- 真**cost cap + dingtalk rate cap decision sediment** 沿用 ADR-DRAFT row 6 + sub-PR 9 真预约 体例 sustained 反 implementation scope creep
- 真**Risk v2 Beat schedule indefinite paused** sustained 沿用 memory #24 候选 (b) 体例 sustained 反 PT 重启 gate 漂移

**负面**:
- 真**软 conflict Fri 19:00 factor-lifecycle-weekly** sustained — Beat scheduler 真 sequential dispatch + Worker `--pool=solo --concurrency=1` Windows 真**单 worker** sustained, 真**queue 等待** 软 conflict tolerated. 真**production verify** 真预约 sub-PR 8b-cadence-B Beat schedule entry register + e2e verify 体例 sustained.
- 真**cost cap v4-* 0 visible** sustained until LiteLLM SDK 升级 (ADR-DRAFT row 6 真预约 ADR-038, 7-24 deadline plan). 真**budget breach silent miss** risk sustained — 真**alternative metric** (token_count cap / latency budget) 真预约 sub-PR 9 alert wiring 真生效时 sediment.
- 真**dingtalk schedule-level rate cap 0 implemented** sustained — per-message dedup TTL 已 in place (`DINGTALK_DEDUP_TTL_MIN=60`) 反 schedule-level cap. 真**News pipeline 触发 dingtalk push 高频 spam risk** sustained until sub-PR 9 alert wiring 真生效.
- 真**RSSHub multi-route 503 (3/4 routes)** sustained 沿用 sub-PR 8b-rsshub PR #254 sediment, 真**audit chunk C** 真预约 fix 体例 sustained — 真**Beat schedule entry register sub-PR 8b-cadence-B 真触 1/4 route 真生效** sustained.
- 真**残余 sub-task** sustained: News Beat schedule entry register + e2e verify 真预约 sub-PR 8b-cadence-B (实施 patch ~200 line) — ADR-DRAFT row 2 真**partial closed** sustained, 0 全 closed in 本 ADR scope.

## Implementation

**本 PR (sub-PR 8b-cadence-A, sediment-only ~150 line)**:
- create [`docs/adr/ADR-043-news-beat-schedule-cadence-rsshub-routing-contract.md`](ADR-043-news-beat-schedule-cadence-rsshub-routing-contract.md): 本 ADR file (~150 line)
- update [`docs/adr/REGISTRY.md`](REGISTRY.md): +ADR-043 row (committed) + 跳号 ADR-040/041/042 sustained 沿用 ADR-DRAFT row 8/9/10 informal reservation 反 silent overwrite 体例
- update [`docs/adr/ADR-DRAFT.md`](ADR-DRAFT.md): row 2 mark `→ ADR-043 (committed, partial)` 沿用 ADR-DRAFT row 7 ADR-039 partial closure 体例
- create memory file `memory/sprint_2_sub_pr_8b_cadence_a_2026_05_07.md` (LL-100 chunked SOP <400 line single chunk)

**留 sub-PR 8b-cadence-B (Beat schedule entry register, 实施 patch ~200 line, 真预约)**:
- patch [`backend/app/tasks/beat_schedule.py`](../../backend/app/tasks/beat_schedule.py): +`news-ingest-5-source-cadence` Beat entry + `news-ingest-rsshub-cadence` Beat entry (cron `crontab(hour="3,7,11,15,19,23", minute=0)` sustained 本 ADR §Decision #2 + RSSHub route_path = `/jin10/news` sustained 沿用 sub-PR 8b-rsshub PR #254 1/4 route 真生效 体例)
- create [`backend/app/tasks/news_ingest_tasks.py`](../../backend/app/tasks/news_ingest_tasks.py): Celery task wrapper 沿用 [`backend/app/tasks/daily_pipeline.py`](../../backend/app/tasks/daily_pipeline.py) 体例 sustained
- create unit tests + integration smoke + Sprint 2 e2e re-run verify post-Beat trigger evidence (DB query 真**fetched/ingested/classified 真生产 batch trigger** + retry policy 真生效 production-level)

**留 audit chunk C (RSSHub multi-route 503 fix + ADR # 重整, 真预约)**:
- RSSHub 3/4 routes 503 fix (`/eastmoney/news/0`, `/caixin/finance`, `/sina/finance/economic`) 沿用 sub-PR 8b-rsshub PR #254 sediment 体例 sustained
- ADR-DRAFT row 8/9/10 informal reservation # 重整 (沿用 REGISTRY 案例 1/2/3 # 下移体例 sustained)

## References

- [ADR-DRAFT.md row 2](ADR-DRAFT.md) — News fetch query strategy SSOT (本 ADR promote target)
- [ADR-031 §6](ADR-031-litellm-router-implementation-path.md) — S2 LiteLLMRouter implementation path (本 ADR 沿用 LLM 路由层 sustained)
- [ADR-032](ADR-032-caller-bootstrap-factory.md) — caller bootstrap factory (本 ADR 沿用 NewsIngestionService 体例)
- [ADR-033](ADR-033-news-source-replacement-2026-05-02.md) — News 源替换决议 (本 ADR 沿用 5-source ingest 体例)
- [ADR-035](ADR-035-zhipu-news-source-1-glm-flash.md) — 智谱 News#1 fetcher (本 ADR 沿用 GLM-4.7-Flash 体例)
- [ADR-037](ADR-037-internal-source-fresh-read-sop.md) — Internal source fresh read SOP (本 ADR 沿用 SOP-6 cross-verify)
- [ADR-039](ADR-039-llm-audit-failure-path-resilience.md) — LLM audit failure path resilience (本 ADR 沿用 retry policy 体例)
- LL-067 — Reviewer agent 真第二把尺子 (本 ADR 沿用 single chunk PR + reviewer 体例)
- LL-098 (X10) — AI 自动驾驶 forward-progress reverse case (本 ADR 沿用 sequence-based + LL-100 chunked SOP)
- LL-100 — chunked SOP <400 line single chunk 体例
- LL-105 — SOP-6 4 source cross-verify (本 ADR 沿用 ADR # reservation 反 silent overwrite 体例)
- LL-110 — web_fetch 官方文档 verify SOP (本 ADR 沿用 fresh tool real cite verify 体例)
- 真讽刺案例 #19 候选 sediment 加深 — frame drift 第 8+9+10 次 catch (sub-PR 8b-gdelt prompt premise inversion + sub-PR 8b-cadence V3 §3.4 fictitious + sub-PR 8b-cadence-A ADR-040 silent overwrite reverse case) defer audit chunk C 真**frame drift 体例汇总** 真预约
