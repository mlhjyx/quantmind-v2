# ADR-031: S2 LiteLLMRouter implementation path 决议 (新建模块 + 渐进 deprecate)

**Status**: committed
**Date**: 2026-05-03
**Sprint**: V3 Tier A Sprint 1 (S8 audit sediment)
**关联**: V3 §5.5 (LLM 路由) / ADR-020 (Claude 边界 + LiteLLM + CI lint, V3 §18.1 row 2 reserved) / ADR-022 (反 silent overwrite) / [docs/audit/sprint_1/s8_deepseek_audit.md](../audit/sprint_1/s8_deepseek_audit.md)
**SSOT**: [docs/adr/REGISTRY.md](REGISTRY.md) (本 # 真状态)

---

## §1 Context

V3 Sprint 1 S2 sub-task 真起手前,需决议 LiteLLMRouter 真 implementation path。

现状:
- `backend/engines/mining/deepseek_client.py` (396 lines) + 2 callers (factor_agent.py / idea_agent.py) + 57 mock 测试,Sprint 1.17 sediment 真 GP 闭环 prototype
- 该模块含 ModelRouter (4 路由: IDEA/FACTOR/EVAL/DIAGNOSIS) + CostTracker + DeepSeekClient
- V3 §5.5 真预约 LiteLLMRouter (新模块) 服务 risk control 域 6 任务 (NewsClassifier / summarizer / Bull-Bear / Judge / RiskReflector / Embedding + Ollama fallback)
- ModelRouter 4 路由跟 V3 §5.5 6 任务 **0 mapping overlap** (domain 正交,详见 audit §4)

3 候选 path 待决议,user X2 决议 = (ii)。

---

## §2 Decision

**采纳 path (ii)**: 新建 `backend/qm_platform/llm/router.py` LiteLLMRouter 模块,deepseek_client.py **0 logic mutation**,渐进 deprecate (S2 sediment 后由 user 显式决议起手 caller 切换 + 显式 deprecate PR)。

**拒 path (i)**: 改造现 deepseek_client.py 为 LiteLLMRouter (in-place mutation)
**拒 path (iii)**: 双 router 长期并存 (LiteLLMRouter for risk + ModelRouter for factor mining 长期不 deprecate)

---

## §3 Rationale

### §3.1 path (ii) 决议依据

1. **ADR-020** (V3 §18.1 row 2 真预约): LiteLLM 是 only path,沿用 4-29 user 决议
2. **ADR-022** (反 silent overwrite + 集中修订机制): 现 1026 lines GP 闭环 prototype 不能 silent mutation
3. **user 决议 2 (p1)** (5-02 sprint period): deepseek_client.py 0 logic mutation 直到 S2 sediment + user 显式 deprecate 决议
4. **V3 §5.5 line 728** 已写 "LiteLLMRouter (新模块) 强制走 LiteLLM" — 设计层就是新建,不是改造
5. **domain 0 重叠** (S8 audit §4 mapping 表): ModelRouter 服务 factor mining (4 任务),LiteLLMRouter 服务 risk control (6 任务),职责正交
6. **0 hot path 风险** (S8 audit §3 证): deepseek_client 真生产 0 路径触达 (0 scheduler/router/service 引用 agents),渐进 deprecate 0 中断

### §3.2 反驳 path (i)

- 改造现 deepseek_client.py 为 LiteLLMRouter 会 silent overwrite Sprint 1.17 已稳定的 396 lines + 57 tests
- 改造范围: ModelRouter 4 路由 → LiteLLM 6+ 路由,语义不兼容 (FACTOR=qwen3 本地 vs L2.3 Bull/Bear=V4-Flash 模型选择不一致)
- in-place 修改违反 ADR-022 sprint period treadmill 反 anti-pattern
- ModelRouter callers (factor_agent / idea_agent) 必须同步改 → 事故影响半径放大

### §3.3 反驳 path (iii)

- 双 router 长期并存绕 ADR-020 LiteLLM-only enforce
- ModelRouter 走 native deepseek API (deepseek_v3 endpoint),不经 LiteLLM 中间层 → 4 项 governance 全失效:
  1. Budget guardrails (V3 §20.1 #6: $50/月 + 80% warn / 100% Ollama fallback)
  2. Cost monitoring (V3 §16.2: daily 累计 + DingTalk push)
  3. Multi-provider fallback (V3 §5.5: DeepSeek + Ollama)
  4. Audit trail (LL-103 SOP-5: 5 condition audit row)
- 长期不 deprecate 违反 V3 §5.5 unified path 真精神

---

## §4 渐进 deprecate plan

```
[Sprint 1: 本 PR sediment]
├─ ADR-031 (本 file): S2 path 决议 sediment
├─ S8 audit: deepseek_client 现状 + 0 hot path 证据链
└─ 沿用 # llm-import-allow:S2-deferred-PR-219 marker (PR #219, line 222)

[Sprint 1 末: S2 implementation]
S2 sub-task: LiteLLMRouter 新建模块
├─ 路径: backend/qm_platform/llm/router.py (V3 §5.5 真预约)
├─ 6 任务路由 (V3 §5.5 line 714-720 实测)
├─ Budget guardrails ($50/月 + 80% warn, V3 §20.1 #6)
├─ Cost monitoring (daily 累计 + DingTalk, V3 §16.2)
├─ Audit trail (LL-103 SOP-5 5 condition)
└─ Ollama fallback (V3 §5.5 line 720)

[Sprint 2-N: 渐进迁移 (user 显式决议起手)]
caller 切换 PR (sustained ADR-022 集中修订机制):
├─ factor_agent.py 引用 ModelRouter → LiteLLMRouter
├─ idea_agent.py 引用 DeepSeekClient → LiteLLMRouter
├─ TaskType.FACTOR/IDEA 映射到 LiteLLM 真任务 enum
├─ 跑 mock test pass + paper-mode 5d dry-run cite cost
└─ 切换 PR merged 后 grep cross-verify 0 caller 残留

[Sprint N+: deprecate 显式 PR (user 决议)]
0 caller 真 0 状态时:
├─ grep "DeepSeekClient\|ModelRouter" backend/ scripts/ → 0 输出
├─ 显式 deprecate PR (cite ADR-031 + ADR-022)
├─ deepseek_client.py 删除 OR 移到 docs/archive/legacy/ (user 决议)
├─ test_deepseek_client.py 同步删除 (57 tests)
└─ test_llm_import_block_governance.py:test_deepseek_client_marker_preserved 同步删除
```

### §4.1 显式 deprecate 触发条件 (硬门)

全部满足才允许 deprecate:

1. ✅ LiteLLMRouter Sprint N 验收通过 (paper-mode 5d cite cost + 0 fail)
2. ✅ factor_agent + idea_agent caller 切换 PR merged (Sprint 2-N)
3. ✅ `grep "DeepSeekClient\|ModelRouter"` 真 0 production 输出 (cross-verify SSOT)
4. ✅ user 显式决议 deprecate (NOT auto, NOT silent)
5. ✅ 沿用 ADR-022 集中修订机制 (NOT 单步 silent overwrite)

---

## §5 Consequences

### §5.1 Positive

- deepseek_client.py 0 mutation,Sprint 1.17 GP 闭环 prototype 稳定保持
- LiteLLMRouter 新模块清晰职责边界 (risk control 域),domain 正交不交错
- 渐进 deprecate path 0 生产中断 (sustained 0 hot path)
- ADR-020 + ADR-022 + V3 §5.5 真预约 三联齐
- S6 hook (PR #219) allowlist marker 机制保护 deepseek_client.py:222 lazy openai import 直到 deprecate

### §5.2 Negative

- 短期 (Sprint 1-N) 双 LLM client 并存 (deepseek_client + LiteLLMRouter),代码复杂度临时上升
- 监控成本: 渐进 deprecate 期间需跟踪 caller 切换进度 + grep cross-verify
- 长期债务: 若 deprecate 未真 sediment (e.g. caller 切换 PR 永远不起手),violator 长期保留 (S6 hook allowlist marker 月度 audit 机制 §9 防御)

### §5.3 Neutral

- ModelRouter 4 路由 → 渐进 deprecate 后,GP 因子挖掘域全统一走 LiteLLMRouter 真 LLM 路由
- LL-098 X10: 本 ADR 0 forward-progress action,等 user 显式决议 S2/Sprint 2-N 起手

---

## §6 实施 checklist (Sprint 后续)

- [x] **本 PR**: ADR-031 sediment + S8 audit + REGISTRY.md update + V3 §18.1 row 11 真预约
- [ ] **S1** (1.5h): LiteLLM SDK install (.venv) + .env 配置 split (V4-Flash/V4-Pro key) + tests
- [ ] **S2** (1-2d): LiteLLMRouter 新建模块 (backend/qm_platform/llm/router.py) + 6 任务路由 + cost monitoring + audit trail
- [ ] **S3** (0.5d): Ollama install + Qwen3 fallback path
- [ ] **S4** (1d): Budget guardrails ($50/月 + 80% warn + 100% Ollama fallback)
- [ ] **S5** (0.5-1d): LLM cost monitoring daily 累计 + DingTalk push
- [ ] **(deferred)** Sprint 2-N: caller 切换 PR (factor_agent / idea_agent → LiteLLMRouter)
- [x] **Sprint 2 sub-PR 7b.2** (#241, 5-07): NewsClassifierService L0.2 V4-Flash sediment (caller class + yaml prompt + tests mock-only)
  - 实现: `backend/app/services/news/news_classifier_service.py` (V3 line 1223 真预约 path) + `prompts/risk/news_classifier_v1.yaml` (V3 line 390 真预约 yaml)
  - 路由: `RiskTaskType.NEWS_CLASSIFY` → `deepseek-v4-flash` (router.py:57 sediment, ADR-035 §2 V4 路由层 0 智谱 sustained)
  - 灾备: Ollama qwen3.5:9b (LLMResponse.is_fallback → ClassificationResult.classifier_cost=NULL, ADR-031 §6 灾备体例 sustained)
  - 测试: 47 mock-only (4 category × 4 profile × 4 urgency × sentiment boundary + parse fail-loud + persist NotImplementedError verify)
  - persist hook stub = NotImplementedError 沿用本 §6 line 141 "Sprint 2-N caller 切换" 体例 留 sub-PR 7b.3 真 wire
- [x] **Sprint 2 sub-PR 7b.3 v2** (#242, 5-07): NewsClassifierService.persist 真 wire + bootstrap factory + requires_litellm_e2e marker register + e2e live test
  - 实现: `backend/app/services/news/news_classifier_service.py:persist` (NotImplementedError stub → INSERT INTO news_classified ON CONFLICT DO UPDATE 沿用 sub-PR 7b.1 v2 #240 FK CASCADE) + `backend/app/services/news/bootstrap.py` (新, get_news_classifier + reset_news_classifier double-checked lock factory 沿用 alert.py:528-554 体例) + `pyproject.toml` +requires_litellm_e2e marker (沿用 sub-PR 1-6 命名体例)
  - 铁律: 32 (Service 不 commit, caller 管事务) + 31 (DataPipeline 0 DB IO sustained) + 33 (news_id=None fail-loud)
  - 测试: 47 → 60 mock-only + 2 e2e live (requires_litellm_e2e marker, real V4-Flash + mock conn capture SQL, 反 quota burn minimal payload)
  - 真讽刺案例 #10 + #11 候选 lesson 真应用: sub-PR 7b.3 v1 STOP push back (CC fresh verify) → v2 (β) split sediment 反 pipeline.py 架构违反 + 反 phantom marker reference
- [x] **Sprint 2 sub-PR 7c** (#243, 5-07): NewsIngestionService orchestrator + Sprint 2 ingestion 闭环 Layer 2.2 完整闭环 sediment ✅
  - 实现: `backend/app/services/news/news_ingestion_service.py` (V3 line 1222 真预约 path, NewsIngestionService class + IngestionStats dataclass) + `__init__.py` +exports
  - 全链 architecture (沿用铁律 31 + 32 sustained 真讽刺案例 #11 候选 lesson 真应用 sustained):
    - DataPipeline (sub-PR 7a #239, qm_platform/news/, 0 DB IO 铁律 31) → list[NewsItem]
    - 本 service (app/services/news/, orchestrator 真**入库点**) → conn → INSERT news_raw RETURNING news_id (9 cols, NewsItem 1:1 align)
    - NewsClassifierService.classify (sub-PR 7b.2 #241) → ClassificationResult
    - NewsClassifierService.persist (sub-PR 7b.3 v2 #242) → news_classified UPSERT (FK news_raw)
    - 0 conn.commit (铁律 32, caller 真事务边界管理者)
  - per-item fail-soft (沿用 sub-PR 7b.2 contract): ClassificationParseError → audit log + skip + classify_failed count, news_raw row 真**已 INSERT 成功** (容忍 partial classify, sub-PR 7b.2 真**未来 backfill** path 真预约)
  - 测试: 12 mock-only + 1 e2e live (TestConstructor 2 + TestIngestHappyPath 3 + TestIngestFailSoft 2 + TestIngestNewsRawInsert 3 + TestIngestTransactionBoundary 2 + TestE2ELive 1)
  - **Sprint 2 ingestion 闭环 Layer 2.2 完整闭环 sediment ✅** (Layer 1 sub-PR 1-6 + Layer 1.5 sub-PR 7a + Layer 2.0 sub-PR 7b.1 v2 + Layer 2.1 sub-PR 7b.2 + Layer 2.1.5 sub-PR 7b.3 v2 + Layer 2.2 sub-PR 7c)
- [ ] **(deferred)** Sprint N+: 显式 deprecate PR (deepseek_client.py 删除 + 57 tests 同步删 + S6 hook marker test 同步删)

---

## §7 References

- [docs/audit/sprint_1/s8_deepseek_audit.md](../audit/sprint_1/s8_deepseek_audit.md) — 本 ADR 真 audit 数据来源
- [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](../QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §5.5 (LLM 路由真预约) + §16.2 (cost monitoring) + §18.1 row 2 (ADR-020 reserve) + row 11 (本 ADR row,本 PR 新增)
- [docs/adr/REGISTRY.md](REGISTRY.md) — 本 # 真状态 SSOT (本 PR 新增 row)
- [docs/LLM_IMPORT_POLICY.md](../LLM_IMPORT_POLICY.md) §8 — Known Legacy Violator (deepseek_client.py:222 marker 真预约 sediment)
- [LESSONS_LEARNED.md](../../LESSONS_LEARNED.md) LL-098 (X10) / LL-103 (SOP-5 audit trail) / LL-105 (SOP-6 ADR # registry SSOT)
- ADR-020 (Claude 边界 + LiteLLM 路由 + CI lint, V3 §18.1 row 2 reserved)
- ADR-022 (反 silent overwrite + 集中修订机制)
