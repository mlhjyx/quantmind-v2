---
adr_id: ADR-035
title: 智谱 News#1 fetcher (GLM-4.7-Flash) + V4 路由层 0 智谱决议 (5-06 (a)+(b) 修订)
status: accepted
related_ironlaws: [22, 25, 27, 34, 38]
recorded_at: 2026-05-06
---

## Context

5-02 sprint period News 6 源换源决议 (ADR-033) 智谱 cite "GLM-4-Flash 完全免费 + 联网搜索 MCP". 5-06 Sprint 2 prerequisite Step 2 + Step 2.5 实测发现 SSOT drift:

- **5-06 智谱真生产现状** (user 截图 + docs.bigmodel.cn web_fetch verify):
  - 0 GLM-4-Flash model (5-02 cite 反实测, 5-02 model 命名漂移)
  - GLM-4.7-Flash + GLM-4.5-Flash 永久免费 (~1M tokens/天 新户)
  - GLM-4.7 + GLM-4.5-air + GLM-4.6v 配额制资源包 (邀请 + 新户, 7-13 到期)
  - search-std/pro 走独立产品 (反 MCP 沿用)
  - GLM-4.7-Flash specs: 200K context / 128K max output / thinking + streaming + function calling + context caching + structured output + MCP integration ✅
- **5-06 user 决议 (a)+(b) 修订**:
  - (a) News#1 fetcher = GLM-4.7-Flash 永久免费 (替 5-02 GLM-4-Flash 漂移 cite)
  - (b) V4-Pro fallback = GLM-4.7 paid 取消 (智谱反 V4 路由层, 沿用 ADR-031 DeepSeek + Ollama 灾备)
  - GLM-4.5-air paid 32M tokens 资源包用途修订: Sprint 2 起手前 burst (历史回填 / 全市场 stress test, ~2 月窗口)
  - GLM-4.7 paid 5M tokens: 7-13 自然 cliff 0 caller 走 (反 fallback 触发)
- **V4 路由层 sustained ADR-031 §6**: V4-Flash + V4-Pro = DeepSeek (deepseek-v4-flash + deepseek-v4-pro), Ollama qwen3.5:9b 灾备 (PR #228 sediment). **0 智谱 alias** sustained.

**触发**: V3 Tier A Sprint 2 起手前 prerequisite Step 3 (BULL/BEAR mapping 修订 V4-Pro + ADR-033 patch + ADR-035/036 新建 + V3 doc patch). 走单 PR sediment 沿用 ADR-022 集中修订机制.

**沿用**:
- ADR-020 (Claude 边界 + LiteLLM 路由, reserved): V4 路由层走 LiteLLM Router 沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern): Sprint 内决议修订走集中机制
- ADR-031 §6 (S2 LiteLLMRouter implementation path): V4 路由层 sustained DeepSeek + Ollama, 0 智谱 alias
- ADR-033 (News 源换源决议): 5-02 sediment + 本 ADR 5-06 修订
- ADR-034 (LLM Fallback Model Upgrade): qwen3.5:9b 灾备沿用
- LL-098 X10 (反 forward-progress default): 本 PR 0 user 接触 implementation

## Decision

### News 6 源最终 cite (5-06 修订, 沿用 ADR-033 patch)

| # | 源 | model | 用途 | 政策 |
|---|---|---|---|---|
| **1** | **智谱** | **GLM-4.7-Flash 永久免费** | News fetcher 主源 (替 MiniMax) | ~1M tokens/天 / 200K context / MCP integration / function calling / OpenAI 兼容 |
| 2 | Tavily | search API | 英文 + 翻译 (海外信号) | 1000 credits/月 永久免费 (沿用) |
| 3 | Anspire | API | 中文财经主源 (沿用) | 新户 2500 点 / 即时注册 (反 5-02 cite "审批 1-2 周") |
| 4 | GDELT 2.0 | events API | 全球事件 | 0 API key / 完全免费 / rate limit 保护 ElasticSearch |
| 5 | Marketaux | news API | 金融 + sentiment | 100 req/day 免费 / 5000+ sources / 30+ languages (反 5-02 cite "80 markets") |
| 6 | RSSHub 自部署 | Docker | 中文财经 RSS (长尾) | 5000+ routes / 自部署 0 API key |

### 智谱资源包用途分工 (5-06 user 决议 sediment)

| 资源 | 用途 | sediment scope |
|---|---|---|
| GLM-4.7-Flash 永久免费 | News#1 fetcher daily caller | 沿用 5-06 (a) 决议 |
| GLM-4.5-air paid 32M (邀请 20M + 新户 12M, 7-13 到期) | Sprint 2 起手前 burst (历史回填 / 全市场 stress test, ~2 月窗口) | 5-06 user 决议修订 |
| GLM-4.7 paid 5M (实名, 7-13 到期) | 自然 cliff 0 caller 走 (反 fallback 触发) | 5-06 (b) 决议修订, 反 V4-Pro fallback |
| GLM-4.6v paid 6M (visual, 7-13 到期) | 反 V3 Tier A scope (Tier B+ 候选) | sustained 0 caller |
| search-std/pro 100 次 | 反 MCP 沿用, 0 caller (反 LLM 路由层) | sustained 0 wire |
| 通用 tokens 2M / 按次 20 次 | 沿用 fallback 候选 (audit Week 2 batch) | sustained reserve |

### V4 路由层 0 智谱 sustained (沿用 ADR-031)

| layer | model | endpoint |
|---|---|---|
| V4-Flash (alias `deepseek-v4-flash`) | DeepSeek deepseek-v4-flash | api.deepseek.com (OpenAI 兼容) |
| V4-Pro (alias `deepseek-v4-pro`) | DeepSeek deepseek-v4-pro | api.deepseek.com (OpenAI 兼容) |
| Fallback (alias `qwen3-local`) | Ollama qwen3.5:9b | localhost:11434 (PR #228) |

**0 智谱 alias** in LiteLLM router yaml. 智谱走 News ingestion 层独立 client (V3§3.1), 反 V4 路由层.

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) 沿用 5-02 ADR-033 GLM-4-Flash cite | 反修订 | ❌ 拒 — 0 GLM-4-Flash model 实测, 5-02 cite drift sustained 反 silent overwrite (ADR-022) |
| (2) 智谱走 V4-Pro fallback (GLM-4.7 paid 5M) | 沿用 5-02 (b) cite | ❌ 拒 — V4 路由层 sustained ADR-031 DeepSeek + Ollama, 智谱走 News ingestion 层独立 client |
| (3) 走 GLM-4.5-Flash 永久免费 (反 GLM-4.7-Flash) | 5-02 cite "GLM-4-Flash" 走 GLM-4.5-Flash 沿用版本 | ❌ 拒 — GLM-4.7-Flash specs 优 (200K vs 32K context / MCP integration / native thinking) |
| **(4) GLM-4.7-Flash News#1 + V4 路由层 0 智谱 (本 ADR 采纳)** | 5-06 user (a) sustained + (b) 取消 | ✅ 采纳 — 永久免费 / specs 优 / V4 路由层 sustained ADR-031 / 0 商授 risk |

## Consequences

### Positive

- **永久免费 News#1 fetcher** (~1M tokens/天 新户): daily Top-25+watchlist (~50 stocks × 2.5K tokens = 125K tokens/天) 沿用, 远低 1M cap.
- **GLM-4.7-Flash specs**: 200K context / 128K max output / function calling / structured output / MCP integration / native thinking — 反 5-02 GLM-4-Flash cite 漂移.
- **V4 路由层 sustained ADR-031**: DeepSeek + Ollama 灾备体例 sustained, 0 智谱 alias 反 LiteLLM yaml 改 (Step 2.5 finding sustained).
- **GLM-4.5-air burst 用途修订**: 32M tokens 资源包反闲置, 走 Sprint 2 起手前 burst (历史回填 / 全市场 stress test).
- **0 prod caller 改**: News ingestion 走独立 client (V3§3.1 修订后 Sprint 2 implementation 起手), 反 V4 路由层 caller 改.

### Negative / Cost

- **GLM-4.7 paid 5M cliff** (7-13 到期): 反 caller 走 (5-06 (b) 决议取消), 反 sediment 0 cost cliff. (audit Week 2 batch sediment 候选 LL-117).
- **智谱 quota 政策 0 fresh verify**: docs.bigmodel.cn web_fetch lazy load placeholder 反 cite 永久免费 quota 政策. 沿用 5-06 web_search Step 2 cite + user 截图 单源 verify (audit Week 2 batch user console 接触 fresh verify 候选).
- **search-std/pro 0 wire 0 sediment**: 智谱独立产品 sustained reserve, 反 V3 §5.5 路由层 cite, 反 V3 Tier A scope (Tier B+ 候选).
- **GLM-4.5-Flash deprecating soon** (5-06 Step 4-3 fresh verify 实证): docs.bigmodel.cn fresh fetch verify, GLM-4.5-Flash 走 deprecating 沉淀, GLM-4.7-Flash 真生产永久免费 successor (200K context + 128K output vs GLM-4.5-Flash 32K context + 96K output). 沿用 §1 Context cite "双 model 永久免费 ~1M tokens/天" 沉淀 5-02 web_search Step 2 单源, 5-06 Step 4-3 fresh verify 实证修订. Sprint 2 implementation 起手时走 `glm-4.7-flash` model_id (反 4.5-Flash deprecating cliff risk). (audit Week 2 batch sediment 候选 LL-115 强化实证).
- **GLM-4.7-Flash free tier qps cap finding** (5-06 Step 4-3 smoke test 实测): 4 candidate model_id fresh smoke test 实测 — `glm-4.7-flash` 反 HTTP 429 "访问量过大" rate limit code 1305 (free tier qps cap, 反 monthly token quota only sustained), `glm-4.5-flash` / `glm-4.5-air` / `glm-4.7` 全 HTTP 200 ✅ 0.6-2.6s. Sprint 2 implementation 起手时走 LiteLLM provider timeout=30s + retry backoff 沿用 PR #221 体例反 free tier qps spike 反 caller fail (沿用 cold-start 60s retry sediment Step 4-2 体例).

### Neutral

- **5-02 ADR-033 sediment sustained**: ADR-033 patch 修订智谱 model name + Anspire 申请方式 + Marketaux 范围 + RSSHub 中文财经源 verify, 沿用 §1 SSOT drift 主动 finding 体例.
- **sprint_state v7 line 110/119/197/240/265 老 6 源 cite drift sustained**: 走 memory direct write patch (反 git PR scope), 沿用 v7 patch 体例 (PR #227 sediment).
- **API key 申请方式修订**: Anspire 5-06 web_search 实测 = 即时 (反 5-02 cite "审批 1-2 周"), 沿用 LL-116 候选 sediment.
- **真生产 cost sustained ~$0.10/月** (沿用 Step 2.5 cite): News#1 GLM-4.7-Flash $0 + V4 路由层 ~$0.10/月 + Ollama $0. 远低 V3§20.1 #6 $50 cap.

## Implementation

| Step | scope | 接触方 | 时机 |
|---|---|---|---|
| Step 1 | ADR-033 patch (智谱 model name + Anspire/Marketaux/RSSHub 修订) | CC (本 PR) | 5-06 ✅ |
| Step 2 | V3§3.1 line 312-336 patch (智谱 model name + 政策依据 cite) | CC (本 PR) | 5-06 ✅ |
| Step 3 | ADR-035 sediment (本 file) | CC (本 PR) | 5-06 ✅ |
| Step 4 | REGISTRY/README +1 row (ADR-035) | CC (本 PR) | 5-06 ✅ |
| Step 5 | sprint_state v7 line drift patch (memory direct write) | CC (memory direct write, 反 git PR) | 5-06 ✅ |
| Step 6 | API key 申请 (智谱 + Tavily + Anspire + Marketaux 即时, GDELT/RSSHub 0 申请) | user 接触 | 留 Step 4 user 决议 |
| Step 7 | RSSHub 自部署 host 选型 (Servy D 盘 / 别的) | user 决议 + CC (Sprint 2 implementation) | Sprint 2 implementation 起手 |
| Step 8 | Sprint 2 ingestion implementation (backend/qm_platform/news/ 子包 + 6 源 client + LiteLLM provider 沿用 V4 路由层) | CC (Sprint 2 implementation) | 留 Step 5 user 决议起手时点 |

## References

- ADR-020 (Claude 边界 + LiteLLM 路由, reserved) — V4 路由层走 LiteLLM Router 沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制) — Sprint 内决议修订走集中机制
- ADR-031 §6 (S2 LiteLLMRouter implementation path) — V4 路由层 sustained DeepSeek + Ollama, 0 智谱 alias
- ADR-033 (News 源换源决议, 5-02 sediment) — 本 ADR §2 修订 5-06 cite drift
- ADR-034 (LLM Fallback Model Upgrade qwen3.5:9b) — Ollama 灾备沿用
- ADR-036 (BULL/BEAR Agent mapping V4-Pro) — 单 PR 跟随 sediment, V4 路由层 V4-Pro 走 BULL/BEAR/JUDGE/RISK_REFLECTOR
- LL-098 X10 (反 forward-progress default) — 本 PR 0 user 接触 implementation
- LL-114 候选 (cite drift cross-source) — sprint_state v7 老 6 源 cite drift sustained
- LL-115 候选 (model 选择 SOTA verify) — 5-02 GLM-4-Flash → 5-06 GLM-4.7-Flash 实证 + 5-06 Step 4-3 fresh verify 强化实证 (4 candidate model_id smoke test + docs.bigmodel.cn fresh fetch — GLM-4.5-Flash deprecating soon, GLM-4.7-Flash free tier qps cap finding) (audit Week 2 batch sediment)
- LL-116 候选 (API key 申请前 cite 锁定 SOP) — Anspire 申请方式 P2 漂移实证
- LL-117 候选 (API quota 7-13 cliff 处置前置 SOP) — 智谱 paid 资源包到期 risk
- LL-118 候选 (LiteLLM provider model id legacy 兼容 vs upstream model id 升级 SOP) — yaml deepseek-chat legacy vs DeepSeek 官网 NEW canonical
- LL-119 候选 (memory cite vs 真生产 yaml/官网现役 cross-verify SOP) — 本 PR 实证延伸
- 5-06 user 决议 (a) GLM-4.7-Flash News#1 sustained + (b) GLM-4.7 paid V4-Pro fallback 取消
- 5-06 web_search Step 2 + Step 2.5 cite (智谱 + DeepSeek + 4 source cross-verify)
- 5-06 Step 4-3 fresh verify (4 candidate model_id smoke test: `glm-4.7-flash` HTTP 429 / `glm-4.5-flash` + `glm-4.5-air` + `glm-4.7` HTTP 200 + docs.bigmodel.cn fresh fetch — GLM-4.7-Flash 200K context + 128K output sustained, GLM-4.5-Flash deprecating soon)
- 5-06 user 决议 Step 4-3: 沿用 (2) GLM-4.7-Flash sustained ADR-035 §2 (反 (1) 改 4.5-Flash / 反 (3) 双 model fallback / 反 (4) 别)
- docs.bigmodel.cn (GLM-4.7-Flash specs 200K context + MCP integration verify)
