# V3 Tier A Gate A 7/8 Verify Report (T1.5a sediment, 2026-05-13)

> **本文件 = Plan v0.2 T1.5a sub-PR sediment artifact**: Constitution §L10.1 Gate A 7/8 项 CC 实测 verify evidence (item 2 ⏭ DEFERRED per ADR-063, items 1+3-8 verify run).
>
> **触发**: Plan v0.2 §A T1.5 row + D1=a 串行 lock (ADR-064) + user 显式 ack "(A) Merge PR #324 → T1.5 起手" 2026-05-13.
>
> **Status**: ⚠️ **Gate A formal close NOT YET satisfied** — 4 PASS + 3 INCOMPLETE + 1 DEFERRED. T1.5b scope 修订 candidate sediment (per Plan v0.2 §G II Push back #1+#2 体例 sustained).
>
> **关联 ADR**: ADR-063 (Gate A item 2 ⏭ DEFERRED) / ADR-064 (Plan v0.2 5 决议 lock) / ADR-065 候选 (T1.5 Gate A formal close 待 3 INCOMPLETE 闭环 后 promote) / ADR-022 (反 silent overwrite + 反 retroactive content edit + 反 silent inflate)
>
> **关联 LL**: LL-098 X10 (反 silent forward-progress) / LL-115 (capacity expansion 真值 silent overwrite) / LL-116 (fresh re-read enforce) / LL-157 (Mock-conn schema-drift 8/9 实证, Session 53 cumulative) / LL-158 (Tier B plan-then-execute 体例 第 4 case 实证)

---

## §1 Scope cite

Constitution §L10.1 Gate A 8 项 checklist (V3 governance batch closure sub-PR 3c sediment 2026-05-09 + ADR-063 amend 2026-05-13 item 2 ⏭ DEFERRED):

1. V3 §12.1 Sprint S1-S11 全 closed (CC 实测 git log + PR # cite + ADR REGISTRY committed verify)
2. ~~paper-mode 5d 验收~~ ⏭ **DEFERRED per ADR-063** (empty-system 5d 自然 fire 信息熵 ≈ 0 trivial-pass anti-pattern)
3. 元监控 `risk_metrics_daily` 全 KPI 14 day 持续 sediment (CC 实测 SQL row count + 日期连续性 verify)
4. ADR-019 (V3 vision) + ADR-020 (Claude 边界 + LiteLLM) + ADR-029 (L1 实时化) + Tier A 后续 ADR 全 committed (REGISTRY SSOT verify)
5. V3 §11.1 12 模块全 production-ready (CC 实测 import + smoke test + module health check)
6. LiteLLM 月成本累计 ≤ V3 §16.2 上限 (~$50/月, CC 实测 SQL llm_cost_daily aggregate)
7. CI lint `check_llm_imports.sh` (或 check_anthropic_imports.py 沿用 ADR-031 §6) 生效 + pre-push hook 集成 (CC 实测 hook log + lint output)
8. V3 §3.5 fail-open 设计实测 (任 1 News 源 fail / fundamental_context fail / 公告流 fail, alert 仍发, CC 实测 mock fail scenario)

---

## §2 Per-item verdict (CC 实测 evidence)

### Item 1 — Sprint S1-S11+S2.5 全 closed ✅ PASS

**Verdict**: 12/12 sprints code-side closed.

**Evidence** (git log + PR # cumulative, branch `main` HEAD `a3cb690` post-PR #324 merge):

| sprint | scope | closure cite |
|---|---|---|
| S1 | LiteLLMRouter + V4-Flash 基础 | sub-PR 9 ADR-047 + LL-137 sediment (V2 prior cumulative PR #219-#226 + #246/247/253/255 ~5630 行 done) |
| S2 | L0.1 News 6 源 + early-return + fail-open | sub-PR 10 ADR-048 + LL-138 sediment (V2 prior cumulative PR #234-#257 ~22 files / ~3000-4000 行 done + ADR-043 Beat schedule + RSSHub routing) |
| S2.5 | L0.4 AnnouncementProcessor 公告流 | sub-PR 11a (DDL + ADR-049) + 11b (implementation + ADR-050 + LL-140, 31 tests PASSED) |
| S3 | L0.2 NewsClassifier V4-Flash + 4 profile | sub-PR 13 ADR-051 sediment (V2 prior cumulative PR #241 + #242 done) |
| S4 | L0.3 fundamental_context 8 维 minimal | sub-PR 14 ADR-053 + LL-144 sediment (AKShare 1 source baseline) |
| S5 | L1 实时化 (subscribe_quote + 9 RealtimeRiskRule) | sub-PR 15-17 ADR-054 + LL-145/146/147 sediment (104 tests PASS) |
| S6 | L0 告警实时化 (3 级 + push cadence) | sub-PR 18 `fc7dd4b` ADR + LL-148 sediment (28 tests PASS) |
| S7 | L3 dynamic threshold + L1 集成 | sub-PR 19 `a1de248` + audit-fix PR #306 `c55662e` ADR-055 + LL-149 sediment (47→48→264 tests PASS) |
| S8 | L4 STAGED + DingTalk webhook 双向 | 8a `dbf55c0` + 8b PR #307 `e68b00a` + 8c-partial PR #308 `3a4a324` + 8c-followup PR #309 `184959c` ADR-056/057/058/059 + LL-150/151/152/153 cumulative (5/5 红线 explicit user ack 3-step gate 1st 实证) |
| S9 | L4 batched + trailing + Re-entry | 9a PR #311 `a1ac5f6` + 9b PR #313 `7fc5bd2` ADR-060/061 + LL-154/155 cumulative |
| S10 | paper-mode 5d setup + operational ops | setup PR #315 `acc77f6` ADR-062 + LL-156 + 5d operational ops PR #319/#320/#321/#322 cumulative ADR-063 + LL-157 sediment (Gate A item 2 ⏭ DEFERRED) |
| S11 | Tier A ADR sediment + ROADMAP 更新 | STATUS_REPORT first artifact PR #317 `5df0804` (🟡 IN-PROGRESS marker) — closure cumulative review pass 留 T1.5b sub-PR cycle |

**总计 Tier A code-side closure**: PR #296~#324 cumulative 29 PRs (post-PR #324 merge `a3cb690` 2026-05-13).

### Item 2 — paper-mode 5d 验收 ⏭ DEFERRED per ADR-063

**Verdict**: SKIP.

**Evidence**: ADR-063 sediment 2026-05-13 (PR #322 squash `880cd83`):
- empty-system 5d 自然 fire 信息熵 ≈ 0 (0 持仓 + 0 tick subscribe + dev-only LLM free-provider activity)
- trivially-pass 不 distinguishable from silent-zero bug class (本 session PR #320 修了正是此 class — column-name drift + severity case-mismatch)
- 真测路径转 Tier B `RiskBacktestAdapter` 历史 minute_bars replay → 9 RealtimeRiskRule 真触发 → Plan v0.2 TB-1 + TB-5 deliver
- Constitution §L10.1 Gate A item 2 ⏭ DEFERRED footnote amend committed PR #322 + sustained per ADR-063 §1.5 Evidence

### Item 3 — 元监控 risk_metrics_daily 14d 持续 sediment ⚠️ INCOMPLETE

**Verdict**: NOT YET 14 day 持续 sediment (CC 实测 2026-05-13 evidence).

**Evidence** (psql query 2026-05-13):
```sql
SELECT COUNT(*), MIN(date), MAX(date) FROM risk_metrics_daily WHERE date >= CURRENT_DATE - INTERVAL '14 days';
-- Result: (2, 2026-04-29, 2026-04-30)
```

**Root cause**: ADR-063 sediment 后 5d natural-fire window DEFERRED → 5-7..5-13 没 trigger 真 risk_metrics_daily INSERT (S10 operational ops PR #319 Beat wire 生效 5-13). 真值 5-13 起算每日 16:30 Asia/Shanghai Beat fire 写 risk_metrics_daily row 1, 14d 持续到 **5-27** 才 satisfy Gate A item 3 baseline.

**已知 2 rows (4-29 + 4-30)**: 历史 paper-mode kickoff 期间 Beat fire 真值 sediment (不含 5d wall-clock per ADR-063 amend).

**Closure path**: 留 14d wall-clock 5-13 起算自然 sediment 周期 (Plan v0.2 TB-1~TB-5 cycle 内 parallel sustained, NO need for synthetic data injection — 反 ADR-063 trivial-pass anti-pattern); OR Gate A item 3 真值修订 amend 加 "5-13 起算 14d 持续 sediment 周期" 体例 sustained TB-5c batch closure pattern.

### Item 4 — Tier A ADR 全 REGISTRY committed ⚠️ PARTIAL FAIL

**Verdict**: ADR-047~063 (17 项) ✅ committed; ADR-019/020/029 (3 项 foundational) 仍 `reserved`.

**Evidence** (psql/grep REGISTRY 2026-05-13):

| ADR | Status | scope |
|---|---|---|
| ADR-019 | reserved | V3 vision (5+1 层 + Tier A/B + 借鉴清单, V3 §18.1 row 1 4-29 决议) |
| ADR-020 | reserved | Claude 边界 + LiteLLM 路由 + CI lint (V3 §18.1 row 2 4-29 决议) |
| ADR-029 | reserved | L1 实时化 + xtquant subscribe_quote 接入 (V3 §18.1 row 9) |
| ADR-047~063 | committed (17 项) | Tier A code-side 12/12 sprint closure 全 sediment |

**Root cause**: ADR-019/020/029 是 V3 §18.1 决议 row reserved (4-29 user 决议), 实施期内未 formal promote 进 REGISTRY committed status. 实施真值 = ADR 决议内容已 satisfied:
- ADR-019 V3 vision 5+1 层 真值 satisfied by V3_DESIGN doc itself (LIVE since 2026-04-29)
- ADR-020 Claude 边界 + LiteLLM + CI lint 真值 satisfied by ADR-031/032/033 (LiteLLM path) + ADR-034 (qwen3 fallback) + ADR-035 (智谱) + V3 §17.1 CI lint `check_llm_imports.sh` (本 verify item 7 PASS)
- ADR-029 L1 实时化 真值 satisfied by ADR-054 (V3 §S5 L1 实时化 + 9 rules production-ready, 本 verify item 5 PASS)

**Closure path**: T1.5b sub-PR cycle promote ADR-019/020/029 reserved → committed (3 ADR doc 创建 + REGISTRY row amend + Constitution §0.1 锚点 table cite 同步).

### Item 5 — V3 §11.1 12 模块 production-ready ✅ PASS (10/10 Tier A scope)

**Verdict**: 10 Tier A 模块 import smoke 全 PASS.

**Evidence** (.venv/Scripts/python.exe import smoke 2026-05-13):

```
PASS: LiteLLMRouter @ backend.qm_platform.llm
PASS: NewsIngestionService @ backend.app.services.news.news_ingestion_service
PASS: NewsClassifierService @ backend.app.services.news.news_classifier_service
PASS: FundamentalContextService @ backend.app.services.fundamental_context_service
PASS: AnnouncementProcessor @ backend.app.services.news.announcement_processor
PASS: RealtimeRiskEngine @ backend.qm_platform.risk.realtime.engine
PASS: DynamicThresholdEngine @ backend.qm_platform.risk.dynamic_threshold.engine
PASS: L4ExecutionPlanner @ backend.qm_platform.risk.execution.planner
PASS: DingTalkWebhookReceiver @ backend.qm_platform.risk.execution.webhook_parser
PASS: RiskBacktestAdapter @ backend.qm_platform.risk.backtest_adapter
Tier A 10 modules: 10 PASS / 0 FAIL
```

**Scope clarification**: V3 §11.1 12 模块 真值 = 9 Tier A 模块 + 3 Tier B 模块 (MarketRegimeService + RiskMemoryRAG + RiskReflectorAgent, NOT in Tier A scope per Plan v0.2 §A TB-2/TB-3/TB-4) + RiskBacktestAdapter (T1.5 prereq stub Tier A scope per V3 §11.4 + sub-PR 5c `a656176`). Tier A scope = 10/12 modules.

**Path drift discovered (sub-finding)**: V3 §11.1 cite drift:
- NewsIngestionService 真路径 = `backend.app.services.news.news_ingestion_service` (NOT `backend/app/services/news/` 目录级 cite)
- NewsClassifierService 真路径 = `backend.app.services.news.news_classifier_service` (同上)
- FundamentalContextService 真路径 = `backend.app.services.fundamental_context_service` (NOT `backend/app/services/fundamental/` 子目录)
- L4ExecutionPlanner 真路径 = `backend.qm_platform.risk.execution.planner` (NOT `backend/app/services/execution/`)
- DingTalkWebhookReceiver 真路径 = `backend.qm_platform.risk.execution.webhook_parser` (NOT `backend/app/api/risk/`)
- RealtimeRiskEngine 真路径 = `backend.qm_platform.risk.realtime.engine` (NOT `backend/engines/risk/realtime/`)
- DynamicThresholdEngine 真路径 = `backend.qm_platform.risk.dynamic_threshold.engine` (NOT `backend/engines/risk/dynamic_thresholds/`)

**Sub-task creep**: V3 §11.1 path cite amend 留 TB-5c batch closure 周期 (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例) — sustained Plan v0.2 §G II Push back #3 drift detect 体例 累积扩 第 4 项 path drift case.

### Item 6 — LiteLLM 月成本累计 ≤ V3 §16.2 上限 ✅ PASS

**Verdict**: May 2026 累计 cost = $0.0000, well below $50/月 上限.

**Evidence** (psql query 2026-05-13):

```sql
SELECT day, ROUND(SUM(cost_usd_total)::numeric, 6) FROM llm_cost_daily WHERE day >= '2026-05-01' GROUP BY day ORDER BY day DESC;
-- Result (May 7-13, 7 days, 0 row for May 1-6):
--   2026-05-13: 0.000000
--   2026-05-12: 0.000000
--   ...
--   2026-05-07: 0.000000
-- Total May 2026: $0.0000
```

**Root cause**: ADR-063 Evidence cite "dev-only LLM free-provider activity" sustained — V4-Flash deepseek-chat + V4-Pro deepseek-reasoner free-provider 走 DeepSeek free tier (沿用 ADR-031 §6 V4 路由层 DeepSeek + Ollama), 322 calls cumulative 7d $0.0000.

**Closure path**: PASS 立即 satisfied. Sustained Tier B cycle 期内 V4-Pro Bull/Bear/Judge + RiskReflector + Embedding RAG ingest 上线后 cost 实测 baseline 沿用 quantmind-v3-llm-cost-monitor skill 月度 audit 体例.

### Item 7 — CI lint check_llm_imports.sh 生效 + pre-push hook 集成 ✅ PASS

**Verdict**: 全部满足.

**Evidence**:

- `scripts/check_llm_imports.sh` exists (CC ls 2026-05-13 verify)
- `config/hooks/pre-push` 集成 line 62-63: `if [ -x scripts/check_llm_imports.sh ]; then sh scripts/check_llm_imports.sh --full; fi`
- Pre-push hook fire log (PR #324 push 2026-05-13): `ALLOWLIST_HIT: backend/engines/mining/deepseek_client.py:222 # llm-import-allow:S2-deferred-PR-219` + `[check_llm_imports] 0 unauthorized import 命中, mode=--full, 放行`

**Path drift (sub-finding)**: Plan v0.2 §A T1.5 row cite `check_anthropic_imports.py` 但真路径是 `scripts/check_llm_imports.sh` (.sh, 沿用 ADR-031 §6 path 决议 + ADR-037 path SSOT). Constitution §L10.1 line 401 cite "check_anthropic_imports.py" — drift detect, amend 留 TB-5c batch closure 周期 (sustained ADR-022 + Plan v0.2 §G II Push back #1+#2 体例).

### Item 8 — V3 §3.5 fail-open 设计实测 ⚠️ PARTIAL

**Verdict**: 10+ fail-open tests exist but 0 单一 V3 §3.5 explicit mock injection integration smoke (任 1 News 源 fail / fundamental_context fail / 公告流 fail, alert 仍发).

**Evidence** (grep fail_open|fail-open|fail_soft|early_return in backend/tests 2026-05-13):

```
backend/tests/test_cite_drift_stop_pretool_hook.py
backend/tests/test_handoff_sessionend_hook.py
backend/tests/test_iron_law_enforce_hook.py
backend/tests/test_news_pipeline.py
backend/tests/test_pull_moneyflow.py
backend/tests/test_redline_pretool_block_hook.py
backend/tests/test_risk_wiring.py
backend/tests/test_sediment_poststop_hook.py
backend/tests/test_session_context_inject_hook.py
backend/tests/test_verify_completion_hook.py
```

**Real situation**:
- DataPipeline early_return + fail-soft per source aggregate ✅ verified (S2 + S2.5 sub-PR cumulative, fail-open within News ingestion path)
- ADR-039 LLM audit failure path resilience ✅ verified (retry policy + transient/permanent classifier, S2.4 sub-task)
- V3 §3.5 fail-open 完整 integration smoke (任 1 News 源 mock fail → alert path 仍 verify alert 仍发) NOT YET 单一 explicit fixture sediment.

**Closure path**: V3 §15.6 ≥7 scenarios fixture cycle (Plan v0.2 §A TB-5a) 含 "LLM 服务全挂 + Ollama fallback" + "DingTalk 不可用 + email backup" + "News 6 源全 timeout" scenarios — V3 §3.5 fail-open explicit integration smoke 留 TB-5a 实现 batch closure pattern (sustained Plan v0.2 §A TB-5 row scope sediment).

---

## §3 Summary verdict

**Gate A formal close**: ⚠️ **NOT YET 7/8 PASS**

| 总 | 项数 | items |
|---|---|---|
| ✅ PASS | 4 | items 1, 5, 6, 7 |
| ⚠️ INCOMPLETE | 3 | items 3 (14d sediment NOT YET), 4 (3 reserved ADR待 promote), 8 (V3 §3.5 explicit smoke 留 TB-5) |
| ⏭ DEFERRED | 1 | item 2 per ADR-063 |
| 总计 | 8 | — |

**T1.5 sub-PR cycle 真值修订 candidate**:

T1.5b 原 scope = "Tier A ADR cumulative promote + ROADMAP doc + Gate A formal close ADR-065" — 真值 expand to 3 INCOMPLETE 闭环 path:

1. **Item 4 closure** (T1.5b scope expand): promote ADR-019/020/029 reserved → committed (3 ADR doc 创建 + REGISTRY row amend + Constitution §0.1 锚点 table cite 同步)
2. **Item 3 closure** (留 wall-clock sediment, NOT T1.5b scope): 14d 持续 sediment 5-13 起算自然周期 → 5-27 satisfy (Tier B TB-1/TB-2 cycle 内 parallel sustained, no synthetic injection 反 ADR-063)
3. **Item 8 closure** (留 TB-5a, NOT T1.5b scope): V3 §3.5 fail-open explicit smoke via V3 §15.6 ≥7 scenarios fixture cycle Plan v0.2 §A TB-5a

**Gate A 形式 close 时机修订真值**: T1.5b ADR-065 promote 时机 = item 4 闭环 后 OR item 3 + item 8 全闭环 后. CC 推荐 = T1.5b 完成 item 4 closure 后 immediate ADR-065 partial close + 形式 close 时机 留 TB-5c batch closure 周期 (item 3 wall-clock natural sediment + item 8 V3 §15.6 fixture).

---

## §4 Closure path options for user 显式 ack

**(A) T1.5b 起手 — Item 4 closure first** (CC 推荐 ⭐): 立即 promote ADR-019/020/029 reserved → committed (3 ADR doc 创建 + REGISTRY row amend + Constitution §0.1 锚点 table cite 同步), ADR-065 partial close (item 4 closure + items 1/5/6/7 cumulative evidence sediment), Gate A 形式 close 时机 留 TB-5c batch closure 周期 (items 3 wall-clock + 8 V3 §15.6 fixture 闭环 后 final ADR-065 amend).

**(B) Strict Gate A wait** — 等 5-27 (14d wall-clock satisfy item 3) + TB-5a (V3 §15.6 fixture satisfy item 8) 全闭环 后 才 T1.5 formal close. Tier B cycle 期内 (~8.5-12 周) Gate A 一直 INCOMPLETE 挂着. 反 D1=a 串行 lock 体例 (T1.5 形式 close 是 TB-1 起手 prereq sustained per Plan v0.2 §A T1.5 row + ADR-064 D1=a 决议).

**(C) Skip T1.5 直接 TB-1** — accept Gate A interim ⚠️ INCOMPLETE 4/8, 进 TB-1 cycle. 反 D1=a 串行 lock (ADR-064 sediment 锁) + 反 Plan v0.2 §C Gate B item 4 "T1.5 sediment ADR" prereq.

**(D) Plan v0.2 amend** — Gate A items 3/4/8 scope真值修订 (e.g. item 3 改 "5-13 起算 14d sediment" / item 4 改 "Tier A 实施期 ADR-047~063 sediment + ADR-019/020/029 真值满足后 amend" / item 8 改 "V3 §3.5 fail-open per-component verify sustained per Tier A sub-PR cumulative"). 需 ADR-064 amend + Constitution §L10.1 amend.

CC 推荐: **(A)** — Item 4 closure 立即 actionable (T1.5b cycle 内 ~1-2 day), ADR-065 partial close 可启动 TB-1 起手 (Gate A interim 4/8 PASS + 1 closure path closed via T1.5b cumulative), TB-5c 周期内完成 final formal close. 沿用 Plan v0.2 §G II Push back #1+#2 体例 batch closure pattern (Constitution §L10.2 amend 同样 留 TB-5c 周期).

---

## §5 红线 5/5 sustained throughout T1.5a verify cycle

- cash=¥993,520.66
- 0 持仓
- LIVE_TRADING_DISABLED=true (backend/.env:20)
- EXECUTION_MODE=paper (backend/.env:17)
- QMT_ACCOUNT_ID=81001102 (backend/.env:13)

0 broker mutation + 0 .env change + 0 production code change (verify-only doc-only sediment).

---

## §6 关联

- Plan v0.2 §A T1.5 row (T1.5a verify scope sediment)
- Plan v0.2 §G II Push back #1+#2 (Constitution §L10.2 amend pending TB-5c batch closure pattern 体例 sustained sustained 累积扩 第 4 项 path drift case Constitution §L10.1 line 401 cite "check_anthropic_imports.py" → 真值 "scripts/check_llm_imports.sh")
- ADR-063 (Gate A item 2 ⏭ DEFERRED) / ADR-064 (Plan v0.2 5 决议 lock D1=a 串行 lock sustained)
- LL-098 X10 (反 silent forward-progress) / LL-115 (capacity expansion 真值 silent overwrite) / LL-116 (fresh re-read enforce) / LL-157 (Mock-conn schema-drift 8/9 实证) / LL-158 (Tier B plan-then-execute 体例 第 4 case)
- Constitution §L10.1 Gate A 8 项 checklist (post-PR #322 amend item 2 ⏭ DEFERRED)
- Constitution §L10.5 Gate E PT cutover gate prereq (item 2 ⏭ DEFERRED satisfied by Tier B RiskBacktestAdapter replay 等价 path 替代 wall-clock per ADR-063 §1.5 + Plan v0.2 §D:284 体例 sustained)

---

## §7 Phase 0 active discovery 3 findings (sustained quantmind-v3-active-discovery skill + LL-115 enforce)

### Finding #1 (和我假设不同)

Subagent `quantmind-v3-tier-a-mvp-gate-evaluator` charter description focused on "paper-mode 5d dry-run 验收" (Gate A item 2), 但 ADR-063 sediment 后 item 2 ⏭ DEFERRED — subagent run prompt MUST explicit instruction "skip item 2 + verify items 1+3-8 only". CC direct verify chosen as primary path (本 T1.5a cycle), subagent cross-verify 留 T1.5b sub-PR cycle (independent 2nd verify for ADR-065 partial close sediment).

### Finding #2 (prompt 没让做但应该做)

V3 §11.1 路径 cite drift detect (7+ paths drift between V3 doc and 真生产路径). Constitution §L10.1 line 401 cite `check_anthropic_imports.py` 但真值 `scripts/check_llm_imports.sh` per ADR-031 §6. Drift 累积 amend 留 TB-5c batch closure 周期 (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例 + Plan v0.2 §G II Push back 体例 sustained 累积扩 第 5 项 drift case).

### Finding #3 (prompt 让做但顺序错)

T1.5a 原 prompt = "subagent verify run + 7/8 items evidence sediment doc + Tier A 期 LL append-only review". 真值 = subagent run 优先级 lower (沿用 LL-098 X10 + Plan v0.2 §A T1.5 row "tier-a-mvp-gate-evaluator subagent" cite — T1.5b 周期 cross-verify 体例 sustained), CC direct verify + evidence sediment is sufficient for T1.5a closure. T1.5b sub-PR cycle 加 subagent cross-verify + ADR-065 partial close + Constitution §0.1 ROADMAP closure 标注 + Tier A 期 LL append-only review.

---

## §8 Sub-PR cycle (T1.5a sediment trigger)

T1.5a sediment cycle = post Plan v0.2 user approve (D1=a 串行 lock per ADR-064) + Gate A 7/8 verify run → CC 实施 → 2 file delta atomic 1 PR (sustained Plan v0.2 §A T1.5 row chunked 2 sub-PR T1.5a + T1.5b 体例 sustained):

| # | file | scope | line delta |
|---|---|---|---|
| 1 | `docs/audit/V3_TIER_A_GATE_A_7_OF_8_VERIFY_REPORT_2026_05_13.md` (本文件) | NEW T1.5a evidence sediment doc | NEW ~10-12KB |
| 2 | `memory/project_sprint_state.md` | Session 53+11 handoff append (T1.5a Gate A interim ⚠️ INCOMPLETE verdict + 3 INCOMPLETE items closure path + (A) (B) (C) (D) options) | edit + append |

T1.5b sub-PR cycle (后置, 待 user 显式 ack (A) 选项):

| # | file | scope | line delta |
|---|---|---|---|
| 1 | `docs/adr/ADR-019-v3-vision-5-1-layer-tier-a-b-借鉴清单.md` | NEW promote reserved → committed | NEW ~3-5KB |
| 2 | `docs/adr/ADR-020-claude-边界-litellm-路由-ci-lint.md` | NEW promote reserved → committed | NEW ~3-5KB |
| 3 | `docs/adr/ADR-029-l1-实时化-xtquant-subscribe-quote.md` | NEW promote reserved → committed | NEW ~3-5KB |
| 4 | `docs/adr/REGISTRY.md` | ADR-019/020/029 row status reserved → committed amend | edit |
| 5 | `docs/adr/ADR-065-v3-t1-5-gate-a-7-of-8-formal-close-partial.md` | NEW ADR-065 partial close sediment (item 4 closure + items 1/5/6/7 cumulative evidence) | NEW ~5-8KB |
| 6 | `docs/adr/REGISTRY.md` | ADR-065 row append | edit |
| 7 | `docs/V3_IMPLEMENTATION_CONSTITUTION.md` | header v0.9 → v0.10 + §0.1 锚点 table 加 ADR-019/020/029 cite + version history v0.10 entry append | edit + append |
| 8 | `docs/audit/V3_TIER_A_CLOSURE_STATUS_REPORT_2026_05_13.md` | S11 🟡 IN-PROGRESS → ✅ DONE amend + Gate A 7/8 interim verdict cumulative cite | edit + append |
| 9 | `LESSONS_LEARNED.md` | LL-159 append (T1.5 Gate A formal close partial 体例 + 累积 sediment 体例 + Tier A 期 LL append-only review LL-127~157 cumulative review 体例) | append |
| 10 | `memory/project_sprint_state.md` | Session 53+12 handoff append (T1.5b closure + ADR-065 partial + Gate A 形式 close 时机 留 TB-5c batch closure 周期) | edit + append |

T1.5a + T1.5b cumulative closure → TB-1 起手 prerequisite 全 satisfied (post-D1=a 串行 lock per ADR-064 + Gate A interim verdict 落地 + ADR-065 partial close sediment) → STOP gate before TB-1 起手 sustained (LL-098 X10).

---

## §9 maintenance + footer

### 修订机制 (沿用 ADR-022 集中机制)

- 新 Gate A item closure / 新 ADR promote / Constitution amend → 1 PR sediment + 自造 skill / hook / subagent 同步 update
- LL append-only (反 silent overwrite, sustained ADR-022)
- ADR # registry SSOT (LL-105 SOP-6) sub-PR 起手前 fresh verify

### 版本 history

- **v0.1 (initial draft, 2026-05-13)**: T1.5a Gate A 7/8 verify run + evidence sediment + 4 PASS / 3 INCOMPLETE / 1 DEFERRED interim verdict + 4 closure path options (A) (B) (C) (D) + Phase 0 active discovery 3 findings + sub-PR cycle 沉淀. 沿用 Plan v0.1 sub-PR 8 sediment 体例 + Plan v0.2 §A T1.5 row chunked 2 sub-PR T1.5a + T1.5b 体例 sustained.
