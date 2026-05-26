# MVP 4.7 — RAG Consumer Wire + BGE-M3 Embedding Backfill (Phase J §1.4)

> **Created**: iter 173 (2026-05-26) via §v9.69 multi-agent fan-out (Explore + oh-my-claudecode:architect parallel) per user directive iter 166 "multi-agent 常态化"
> **Sediment trigger**: §v9.56 pivot ladder — MVP 4.6 Phase J §1.3 closed iter 168, §1.4 NEXT Tier A§1
> **Spec target**: ≤ 2 页 design doc per 铁律 24 + iter-friendly 5-chunk decomposition per §v9.65
> **Provenance**: `docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md` §1.4 lines 86-104

---

## §1 Problem Statement (Phase J §1.4 verified iter 173)

Manifest claims (verbatim):
> "BGE-M3 embedding cron NOT 实施 (F2 in ISSUES_PENDING_REGISTRY, 21 rows embedding NULL). 更关键: NewsClassifier / Bull / Bear / RegimeJudge **0 RAG consume** (V3 §5.4 line 710 设计的 'L1 push augmentation' 真值 wire 0). 当前 RAG 只 reflector 自反馈."

iter 173 Explore agent fresh verify (cite-source-locked):
- **risk_memory DDL** (`backend/migrations/2026_05_14_risk_memory.sql:21`): `embedding VECTOR(1024)`, ivfflat partial index `WHERE embedding IS NOT NULL`
- **risk_reflector_agent.py**: DOES compute embedding inline via `embedding_service.encode` at L252 (post-TB-4c closure). New rows since 5-14 should have embeddings.
- **21 NULL embedding rows** = historical backfill rows inserted BEFORE embedding service was wired. ivfflat partial index excludes them → `retrieve_similar` returns 0 hits for all queries currently.
- **BGE-M3 cron**: ❌ does NOT exist (no Beat entry, no standalone script). Verified via `backend/app/tasks/beat_schedule.py` scan.
- **4 RAG consumers — 0 consume confirmed**:
  - NewsClassifier (`backend/app/services/news/news_classifier_service.py:176-275`): pure LLM call, no `RiskMemoryRAG.retrieve()` invocation
  - BullAgent / BearAgent / RegimeJudge (`backend/qm_platform/risk/regime/agents.py`): `_build_messages()` composes indicators + bull/bear args only, no RAG slot
- **Existing RAG consumer**: only `risk_reflector_tasks.py:415-448` `_gather_rag_top5()` — self-feedback loop, increment minimal
- **V3 §5.4 design spec line 710-711** (`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`): "L1 trigger时, vector similarity search 历史相似事件 → push content含 '类似情况 N 次, 做 X 动作, 平均结果 Y'"
- **GPU resource**: RTX 5070 12GB confirmed (CLAUDE.md); BGE-M3 1024-dim @ batch 100 ~3.5GB VRAM — fits comfortably

**Gap**: RAG infrastructure (EmbeddingService + RiskMemoryRAG + repository.retrieve_similar) fully built and proven via reflector. Missing: (a) 21-row historical backfill + future NULL self-healing; (b) 4 consumer wire to actually invoke RAG retrieval at decision-time per V3 §5.4 design intent.

---

## §2 Design Sketch

Wire path (sibling pattern from MVP 4.6 risk_reflector_tasks.py reuse):
```
NewsClassifier.classify(news_item)
  → rag_context_builder.build(query="title + content", k=5, event_type='news')
    → RiskMemoryRAG.retrieve(query, k=5, event_type) → top-5 similar lessons
    → format as markdown table + fail-soft "数据不足" placeholder
  → inject {rag_context} into news_classifier_v1.yaml user_template
  → LLM call augmented with historical pattern context
  → 同 wire for Bull / Bear / RegimeJudge

Embedding self-healing Beat (every 6h):
  → scripts/backfill_risk_memory_embeddings.py
  → SELECT memory_id FROM risk_memory WHERE embedding IS NULL ORDER BY created_at LIMIT 100
  → BGE-M3 encode batch → UPDATE rows SET embedding = ...
  → idempotent loop (handles partial completion via WHERE embedding IS NULL)
```

**Design decisions** (3 critical, validated by architect agent):

1. **BGE-M3 cron model: Beat-driven incremental (every 6h)** — self-healing for any future NULL row source (reflector transient failure / manual INSERT / future event_reflection). LOC overhead vs one-shot ~20 LOC, eliminates ongoing operational debt. Idempotent `WHERE embedding IS NULL` query.

2. **RAG consume wire: Shared retrieval middleware layer** — extract `_gather_rag_top5` pattern from `risk_reflector_tasks.py:415-448` into `backend/app/services/risk/rag_context_builder.py`. All 4 consumers call shared builder with `compose_query` callback. Avoids 4x code duplication.

3. **Chunk decomposition: By-component** (not by-layer). 5 chunks vs 6 (collapse Bull+Bear+Judge into single regime chunk since same `MarketRegimeService` orchestration + identical yaml pattern).

**Pattern reuse** (sibling iter 132/162/166 canonical):
- `risk_reflector_tasks.py:143-168` `_get_rag()` lazy singleton pattern (shares BGE-M3 model across worker)
- `risk_reflector_tasks.py:415-448` `_gather_rag_top5()` canonical fail-soft retrieve + format pattern
- 铁律 32 (caller owns transaction) + 铁律 33 (silent_ok on RAG retrieve failure)
- 铁律 44 X9 (Beat schedule changes require post-merge Servy restart documentation)

---

## §3 Chunk Decomposition (5 chunks, iter 174→178)

### Chunk 1 — BGE-M3 Embedding Backfill Beat Task (~80 LOC) — iter 174
- **Goal**: NEW `scripts/backfill_risk_memory_embeddings.py` + Beat entry every 6h. Find `embedding IS NULL` rows, batch encode via BGE-M3, UPDATE rows. Self-healing for 21 historical + future transient NULL sources.
- **Files**: NEW `scripts/backfill_risk_memory_embeddings.py` + NEW `backend/app/tasks/embedding_backfill_tasks.py` + MODIFY `backend/app/tasks/beat_schedule.py`
- **Risk**: Low (BGE-M3 model pre-cached at `D:\quantmind-v2\models\bge-m3\`, <1s for 21 rows)
- **Test**: TDD mock embedding_service + verify UPDATE SET embedding; integration test runs against real DB, asserts 0 NULL rows post-run
- **Ship 三态 per LL-210**: backend-only ✅ verified (TDD + manual run independent of Servy unblock)
- **Post-merge ops** (铁律 44 X9): Servy restart Celery + CeleryBeat after merge

### Chunk 2 — Shared RAG Context Builder (~60 LOC) — iter 175
- **Goal**: NEW `backend/app/services/risk/rag_context_builder.py` extracting `_gather_rag_top5` pattern as general utility. Accepts `compose_query: Callable` + `k` + `event_type` + RiskMemoryRAG instance. Returns formatted markdown table OR fail-soft placeholder.
- **Files**: NEW `backend/app/services/risk/rag_context_builder.py`
- **Risk**: Low (refactor of proven pattern + new tests)
- **Dependency**: Chunk 1 (embeddings exist so retrieve returns hits)
- **Test**: TDD mock RiskMemoryRAG, verify query composition + format + fail-soft
- **Ship 三态**: backend-only ✅ verified (pure unit test)

### Chunk 3 — NewsClassifier RAG Wire (~90 LOC) — iter 176
- **Goal**: Add `{rag_context}` placeholder to `prompts/risk/news_classifier_v1.yaml` user_template + wire `news_classifier_service.py` to call `rag_context_builder.build()` + bootstrap RAG singleton via `news_ingest_tasks.py`.
- **Files**: MODIFY `prompts/risk/news_classifier_v1.yaml` + MODIFY `news_classifier_service.py` + MODIFY `news_ingest_tasks.py`
- **Risk**: MEDIUM (prompt template change touches classification quality; use `.format_map(defaultdict(str, ...))` to avoid KeyError if rag_context absent)
- **Dependency**: Chunk 2 (shared builder)
- **Test**: TDD mock RAG builder, verify classify() passes rag_context to LLM messages; integration verify existing classification tests sustain
- **Ship 三态**: backend-only ✅ verified (prompt quality = manual eval, not automated)

### Chunk 4 — Bull/Bear/Judge RAG Wire (~120 LOC) — iter 177
- **Goal**: Add `{rag_context}` placeholder to 3 yamls (`bull_agent_v1.yaml` / `bear_agent_v1.yaml` / `regime_judge_v1.yaml`) + wire `market_regime_service.py` to call shared builder once + share rag_context across 3 agents within same classify() call.
- **Files**: MODIFY 3 yamls + MODIFY `market_regime_service.py` + MODIFY `regime/agents.py` (`_ArgumentsAgent._build_messages` + `RegimeJudge._build_messages`)
- **Risk**: MEDIUM (3 yamls touched simultaneously; same KeyError mitigation as Chunk 3)
- **Dependency**: Chunk 2 (shared builder)
- **Test**: TDD mock RAG builder per agent, verify `_build_messages` includes rag_context; integration verify existing regime classification regression
- **Ship 三态**: backend-only ✅ verified

### Chunk 5 — Integration Smoke + Servy Restart Doc + LL Sediment (~50 LOC) — iter 178
- **Goal**: Full-path smoke test (embed NULL row → retrieve → inject prompt → parse LLM response). Verify Beat schedule entry deployed (post-Servy restart). Append LL-211 candidate sediment if shared-middleware pattern + reality re-grounding learnings warrant.
- **Files**: NEW `backend/tests/test_rag_consumer_smoke.py` (@pytest.mark.smoke) + MODIFY `docs/audit/PHASE_J_DEFER_MANIFEST_2026_05_20.md` §1.4 closure marker
- **Dependency**: Chunks 1-4 merged
- **Test**: Self-tested + 红线 5/5 verify
- **Ship 三态**: backend-only ✅ verified pre-Servy; runtime-verified ✅ post-Servy elevated restart + Beat fire verify

---

## §4 Cross-cutting

### ADR-DRAFT candidates
- **prompt yaml versioning protocol**: `{rag_context}` added as optional placeholder with `.format_map(defaultdict(str, ...))` default empty. No v1→v2 version bump needed (avoids `PromptLoadError` regression). Documented as ADR for future consumer extensions.
- **RAG context injection architecture**: shared builder vs per-consumer decision. Future consumers (e.g., DynamicThresholdEngine L3 or post-Wave-5 Operator UI assistance) reuse shared `rag_context_builder.build()` via `compose_query` callback.

### Frontend parity (§v9.43)
- 0 frontend impact. RAG context server-side prompt injection only. Regime/news classification outputs structurally unchanged. Tier B Wave 5 Operator UI may later surface RAG-augmented LLM decisions (sediment trigger for future MVP 5.x).

### Reality verification (§v9.49)
- Before Chunk 1: fresh `psql -c "SELECT COUNT(*) FROM risk_memory WHERE embedding IS NULL"` (manifest claims 21, may have grown)
- Before Chunks 3+4: fresh verify 4 yaml file checksums to confirm no other-session drift since iter 173
- Post Chunk 5: 红线 5/5 fresh verify + factor_values max_td vs LL-208 SOP (parallel to MVP 4.7 chunks, iter ~175)

### Recommended order
**Chunk 1 → 2 → 3 → 4 → 5** (strict sequential).

Rationale: Chunk 1 first because without embeddings, RAG retrieve returns empty (all consumer chunks dormant if started before backfill). Chunk 2 before 3+4 because shared builder is dependency. Chunk 3 before 4 (NewsClassifier simpler, validates pattern before 3-yaml regime chunk).

---

## §5 Risk + STOP triggers

- **§6 carve-out**: 0 .env mutation / 0 broker write / 0 production DB row mutation (Beat fires write embedding column UPDATE only, no INSERT to risk_event_log/trade_log) / 0 红线 drift / 0 governance SSOT retroactive / 0 new Framework. Safe scope.
- **User authorization gates**:
  - (a) Beat schedule additions require post-merge Servy restart (sustained iter 142+143 blocker; §v9.57 ops blocker SOP — Chunk 1 + Chunk 5 backend-only ✅ verified pre-Servy, runtime-verified blocked behind Servy)
  - (b) GPU resource: RTX 5070 12GB available, no contention with PT (paper-mode dormant 28+ days). No new authorization needed.
- **红线 5/5 sustained**: cash ¥993,520.66 / 0 持仓 / paper / true / 81001102 — wire dormant in paper-mode (RAG retrieve may be called by news classifier even in paper, but no production resource implications)
- **Regression risk** (Chunks 3+4): yaml `{rag_context}` placeholder must use `defaultdict(str)` to avoid KeyError if not supplied. Mitigation tested in TDD per chunk.

---

## §6 Effort estimate

Per architect agent: **~400 LOC across 5 chunks, ~5-7 iter (iter 174-178 sequential)**. At 1 chunk per iter cadence (~30-60min), expect **iter 174-178 cumulative = 5 iter** plus iter ~179 buffer for unexpected reviewer cycles.

Wall clock: ~1 week at current velocity (1-2 iter per session with multi-agent fan-out).

Post Chunk 5 closure:
- Phase J §1.4 RAG consumer wire complete (4 consumers + BGE-M3 cron + smoke verify)
- 21 historical NULL embeddings backfilled + future self-healing
- Tier A§1 Phase J 4 of 5 chunks closed (§1.1 + §1.2 + §1.3 + §1.4 = 4 closed; §1.5 trade event StreamBus remaining)
- Backend-only ✅ chunks 1-4; runtime-verified ✅ on Chunk 5 post-Servy restart (sustained blocker dependency)

Phase J remaining post §1.4: §1.5 streaming event-sourcing trade event → flow 4 risk consumer (single remaining Phase J chain item).

---

**Provenance**: iter 173 §v9.69 multi-agent fan-out — Explore agent (file:line state inventory, 8 components + DDL verify + GPU check) + oh-my-claudecode:architect agent (3 design decisions + 5-chunk decomposition + ADR-DRAFTs + risk + trade-off table). All cites verified at 2026-05-26 ~17:45 SH via fresh Read. Sibling pattern: MVP 4.5 (L1 RealtimeRisk Wire) + MVP 4.6 (daily_reconciliation revival) 5-iter chains.

**iter 173 ship 三态 per LL-210**: backend-only ✅ doc-sediment scope (design doc only, 0 code change, 0 mutation surface).
