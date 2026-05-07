---
adr_id: ADR-034
title: LLM Fallback Model Upgrade (qwen3:8b → qwen3.5:9b, 5-06 sediment)
status: accepted
related_ironlaws: [22, 25, 27, 34]
recorded_at: 2026-05-06
---

## Context

5-02 sprint period qwen3:8b 决议时 Qwen 3.5 系列未发布 (Qwen 3.5 release 2026-02-16 大约 4 天前). PR #225 (S3) 走 ollama_chat/qwen3:8b (~5.2 GB Q4_K_M) 作 LLM fallback path.

5-06 user 实测 ollama pull qwen3.5:9b + Ollama desktop UI run 中文输出流畅, RTX 5070 12 GB VRAM 沿用 fit (反 OOM). LiteLLM router yaml + e2e test 沿用 qwen3:8b cite drift, 走 Sprint 1.5 S5 sub-task 升级 sediment.

**触发**: V3 Tier A Sprint 2 起手前 model SOTA 升级 prerequisite. Qwen 3.5 9B intelligence index 32 vs Qwen3 8B 17 (+15 分差距, source: artificialanalysis.ai). 256K context window vs 32K (Qwen3 base). multimodal native (text + image). native tool calling + thinking.

**沿用**:
- ADR-022 (Sprint Period Treadmill 反 anti-pattern): Sprint 内 model 升级走集中修订机制
- ADR-031 (S2 LiteLLMRouter implementation path) §6: ollama_chat endpoint + alias resolve 走 yaml 沿用
- ADR-032 (S4 caller bootstrap factory): caller 走 get_llm_router() 沿用, 0 prod caller 改
- LL-098 X10 (反 forward-progress default): 本 PR 0 user 接触 implementation, CC 自主 stress test + sediment
- PR #225 S3 Ollama install runbook (D 盘 + GPU 加速)

## Decision

| 项 | qwen3:8b (PR #225 sediment) | qwen3.5:9b (本 ADR 升级) | 验证 |
|---|---|---|---|
| Model ID | `ollama_chat/qwen3:8b` | `ollama_chat/qwen3.5:9b` | 5-06 ollama list ✅ |
| Q4_K_M size | 5.2 GB | 6.6 GB (+1.4 GB) | 5-06 ollama list ✅ |
| Intelligence index (artificialanalysis.ai) | 17 | 32 (+15 分) | Qwen 3.5 release sediment |
| Context window | 32K | 256K | Qwen 3.5 release sediment |
| Multimodal | text only | text + image native | Qwen 3.5 release sediment |
| Tool calling | partial | native | Qwen 3.5 release sediment |
| Thinking mode | external prompt | native (Qwen3.5 small series 反 default thinking) | 5-06 stress test ✅ |
| LiteLLM endpoint | ollama_chat | ollama_chat 沿用 | yaml line 38 patch |
| Router alias | qwen3-local | qwen3-local 沿用 (反改) | yaml line 12 |
| API key | 0 (本地) | 0 (本地) | env-driven |
| Cost | $0 | $0 | 本地 Ollama |

**5-06 CC 自主 stress test 真值** (RTX 5070 12 GB):
- VRAM baseline: 1643 MB / 12227 MB (~13%)
- VRAM post-load peak: **9592 MB / 12227 MB (~78% utilization, ~2.6 GB headroom)**
- GPU utilization (idle post-load): 27%
- Total response duration: 9.8s (load 5.0s + prompt eval 0.05s + 343 tokens output 4.7s)
- Prompt eval rate: **472.57 tokens/s**
- Eval rate (output): **73.36 tokens/s**
- Verdict: ✅ fit RTX 5070 12 GB, 反 OOM, 0 P1 finding

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) 沿用 qwen3:8b | PR #225 sediment, 0 改 | ❌ 拒 — Qwen 3.5 SOTA +15 分差距, 256K context, native multimodal/tool calling 沿用反就绪 |
| (2) 升级 qwen3.5:4b | 更小 model (~2.4 GB), VRAM 更充裕 | ❌ 拒 — intelligence 22 仍 < qwen3.5:9b 32, 沿用 RTX 5070 12 GB 9b fit headroom OK |
| **(3) 升级 qwen3.5:9b (本 ADR 采纳)** | SOTA + RTX 5070 12 GB fit | ✅ 采纳 — intelligence +15 / 256K context / VRAM 78% peak (~2.6 GB headroom) / 0 prod caller 改 |
| (4) 双 model 共存 (qwen3:8b + qwen3.5:9b 沿用) | 沿用 Ollama 双 model, alias 切换 | ❌ 拒 — 沿用 disk overhead 11.8 GB / yaml router alias 单值 / 0 多 model fallback 触发场景 (沿用 V3 §5.5 单 fallback) |

## Consequences

### Positive

- **Intelligence +15 分** (artificialanalysis.ai): 17 → 32. NewsClassifier V4-Flash fallback / RiskReflector V4-Pro fallback 沿用质量提升.
- **256K context window**: 32K → 256K (8 倍). RAG retrieval + 长 prompt 沿用反 truncate.
- **Native multimodal**: text + image native. 反 V3 §17.4 离线模式 chart screenshot 输入 (沿用 future Sprint 候选).
- **Native tool calling**: 沿用 LiteLLM tool_choice 体例反**重写 prompt fallback path**.
- **Native thinking mode**: Qwen3.5 small series 反 default thinking, 反**`<thinking>` external prompt manual** (5-06 stress test 实测 thinking + done thinking trace OK).
- **0 prod caller 改**: caller 走 get_llm_router() 沿用 ADR-032 体例, model 切换走 yaml. 0 backend/qm_platform/llm/ 8 文件改.
- **5-06 user 实测 + CC 自主 stress test 双 verify**: VRAM fit RTX 5070 12 GB / 73 t/s / 9.8s response 真值.

### Negative / Cost

- **Disk +1.4 GB**: 5.2 GB → 6.6 GB Q4_K_M. D:\ollama-models 走 OLLAMA_MODELS env (PR #225 sediment 沿用).
- **VRAM 78% peak vs qwen3:8b ~50% peak**: ~2.6 GB headroom 沿用 (反 OOM), 反**256K context 真生产 stress test** 留 audit Week 2 batch 候选 (沿用 LL-098 X10 反 silent ramp).
- **VRAM recommend 18 GB (Qwen3.5 9b 官方 cite) vs 12 GB RTX 5070**: 沿用 user 5-06 实测 fit (走 Q4_K_M quantization + KV cache 优化), 反**完整精度 / 256K full context** 走 RTX 5090 / A100 推荐 (沿用 future Sprint 候选).
- **qwen3:8b model 沿用 disk** (5-06 user 0 删): 走 user 决议时点删除 (ADR §5 Step 7).

### Neutral

- **ollama_chat endpoint 沿用** (PR #225 PR #226 sediment): 反改 endpoint, 反 LiteLLM provider config 改.
- **Router alias `qwen3-local` 沿用**: 反改 alias 反 BudgetAwareRouter completion_with_alias_override 反 backward-compat break.
- **Apache 2.0 license 沿用**: Qwen3.5 9B Apache 2.0 = qwen3:8b license, 0 商授 risk drift.
- **0 e2e test break**: 函数名 `test_e2e_ollama_chat_qwen3_via_alias_override` 沿用 (反 rename 走 git history backward-compat). model name cite 沿用 yaml replace, e2e fixture.

## Implementation

| Step | scope | 接触方 | 时机 |
|---|---|---|---|
| Step 1 | ollama pull qwen3.5:9b (D:\ollama-models, 6.6 GB) | user 接触 (5-06) | 5-06 ✅ |
| Step 2 | Ollama desktop UI 中文 stress test | user 接触 (5-06) | 5-06 ✅ |
| Step 3 | CC 自主 stress test (VRAM peak + token/s + nvidia-smi) | CC (本 PR) | 5-06 ✅ (VRAM 9592/12227 MB, 73 t/s, 9.8s) |
| Step 4 | config/litellm_router.yaml patch (line 12 cite + line 38 model) | CC (本 PR) | 5-06 ✅ |
| Step 5 | backend/tests/test_litellm_e2e.py model name cite patch + pytest -m requires_ollama PASS verify | CC (本 PR) | 5-06 ✅ |
| Step 6 | docs/runbook/cc_automation/03_ollama_install_runbook.md patch + VRAM stress test cite section | CC (本 PR) | 5-06 ✅ |
| Step 7 | ADR-034 sediment + REGISTRY/README add row | CC (本 PR) | 5-06 ✅ |
| Step 8 | 256K context stress test (audit Week 2 batch 候选) | CC (留 audit Week 2) | 留 audit Week 2 |
| Step 9 | qwen3:8b model 删/沿用决议 | user 决议时点 | 留 user 决议 |

## References

- PR #225 (S3 Ollama install runbook + ollama_chat endpoint patch + 2 e2e requires_ollama)
- PR #226 (S4 caller bootstrap factory + ADR-032)
- PR #227 (V3 §3.1 + §20.1 #10 patch + ADR-033)
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制) — Sprint 内 model 升级体例
- ADR-031 (S2 LiteLLMRouter implementation path) — ollama_chat endpoint + alias resolve 沿用
- ADR-032 (S4 caller bootstrap factory) — caller 走 get_llm_router() 沿用, 0 prod caller 改
- LL-098 X10 (反 forward-progress default) — 本 PR 0 user 接触 implementation
- LL-114 候选 (cite drift cross-source) — yaml + e2e + runbook + sprint_state v7 cite qwen3:8b 沿用 audit Week 2 batch 候选
- LL-115 候选 (audit Week 2 batch sediment) — "model 选择 Sprint period 起手前 SOTA verify + cite drift cross-verify"
- 5-06 user 实测 (ollama pull qwen3.5:9b ✅ + Ollama desktop UI 中文输出 ✅ + RTX 5070 12 GB fit ✅)
- 5-06 CC 自主 stress test (VRAM 9592/12227 MB peak / 73.36 tokens/s eval rate / 9.8s total duration / thinking + done thinking trace ✅)
- Qwen 3.5 release (2026-02-16) — Qwen 3.5 9B Q4_K_M, intelligence index 32, 256K context, multimodal native
