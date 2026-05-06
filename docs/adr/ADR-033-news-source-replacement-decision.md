---
adr_id: ADR-033
title: News 源替换决议 (5-02 sprint period sediment, V3 §3.1 + §20.1 #10 patch)
status: accepted
related_ironlaws: [22, 25, 27, 34, 38]
recorded_at: 2026-05-06
---

## Context

V3 §3.1 News 多源接入 (L0.1) 4-29 D5-D9 拍板 6 源 (Anspire / Tavily / SerpAPI / Bocha / Brave / MiniMax). 5-02 sprint period user 战略对话 + web_search 验证后决议换源 (4 替 + 2 沿用), 月成本 $0.

**SSOT drift 主动 finding** (audit Week 2 batch sediment 候选, 沿用 LL-114 cite drift 体例):
- 5-02 换源决议 SSOT source 仅 user prompt + Claude.ai 战略对话
- sprint_state v7 line 110/197/265 sustained 老 6 源 cite (0 sediment 5-02 换源决议) — 5-06 sprint_state v7 patch 走 memory direct write (沿用 v7 patch 体例)
- V3 doc §3.1 + §20.1 #10 0 patch (本 PR sediment) — 反 silent drift, 走 ADR-022 集中修订机制

**5-06 cross-verify 修订** (Step 2 + Step 2.5 sediment, 沿用 ADR-035 + ADR-036):
- 智谱 GLM-4-Flash → GLM-4.7-Flash (5-02 cite drift, 0 GLM-4-Flash 实测; 5-06 user 截图 + docs.bigmodel.cn 实测 GLM-4.7-Flash specs 200K context + MCP integration)
- Anspire 申请方式: ≤2 周 → 即时 (5-06 web_search 实测)
- Marketaux: 80 markets → 5000+ sources / 30+ languages (5-06 web_search 实测)
- RSSHub 中文财经源 cite: docs.rsshub.app verify 候选 (audit Week 2 batch)

**触发**: V3 Tier A Sprint 2 起手前 prerequisite (V3 §3.1 6 News 源 API key 申请) — 必先 V3 doc patch + ADR sediment 后, Sprint 2 ingestion implementation 起手.

**沿用**:
- 4-29 ADR-020 (Claude 边界 + LiteLLM 路由, reserved): 6 源全走 LiteLLM 接入沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制): 5-02 换源决议沿用 V3 doc patch + ADR sediment, 反 silent overwrite
- LL-098 X10 (反 forward-progress default): 本 PR 0 ingestion implementation 起手, 留 Sprint 2 implementation scope

## Decision

**新 6 源** (沿用 V3 §3.1 表格体例):

| # | 源 | 类型 | 用途 | API 限速策略 | 替换 / 沿用 |
|---|---|---|---|---|---|
| 1 | 智谱 GLM-4.7-Flash (5-06 修订, 沿用 ADR-035) | 中文 LLM 接入 + 联网搜索 + MCP integration | News#1 fetcher 主源 | 永久免费 (~1M tokens/天) + 200K context + 128K max output + OpenAI 兼容 | 替 MiniMax |
| 2 | Tavily | 英文 + 翻译 | 海外信号 (港美 ADR 联动) | 1000 credits/月永久免费 + LiteLLM 限速 fallback | 沿用 |
| 3 | Anspire | 中文财经 | 中文财经主源 | 新户 2500 点 + 申请即时 (5-06 web_search 修订, 反 5-02 cite "审批 1-2 周") + LiteLLM 多 Key 负载均衡 | 沿用 |
| 4 | GDELT 2.0 | 全球事件 | 跨境 + 突发 | 0 API key + 完全免费 + 7×24 实时 stream | 替 Bocha |
| 5 | Marketaux | 金融专用 | 金融信号 + sentiment 标签 | 5000+ sources / 30+ languages + 完全免费 (100 req/day) + sentiment pre-tagged (5-06 修订, 反 5-02 cite "80 markets" 漂移) | 替 SerpAPI |
| 6 | RSSHub 自部署 | 中文财经 RSS | 长尾 + 全主流源 | 自部署 + 0 API key + 0 第三方依赖 | 替 Brave |

**砍源 4 个** (5-02 web_search 验证后决议):

| # | 砍源 | 砍因 |
|---|---|---|
| 1 | Serper | 中文覆盖弱 + 配额限 |
| 2 | DuckDuckGo | 反 API + 仅 Web scraping, 反生产稳定 |
| 3 | Bocha | 收费层冲突 + 0 商授 free tier verify |
| 4 | Alpha Vantage | 英文金融 only + 中文 0 覆盖, 跟 Marketaux 重合 |

**月成本**: $0/month (全 6 源完全免费层 / Tavily 1000 credits 永久 / Anspire 2500 点新户 + 申请即时 / 智谱 GLM-4.7-Flash 永久免费 ~1M tokens/天 (5-06 修订沿用 ADR-035) / GDELT 0 API key / Marketaux 100 req/day / RSSHub 自部署).

## Alternatives Considered

| 候选 | 描述 | 评价/理由 |
|---|---|---|
| (1) 沿用 4-29 老 6 源 | Anspire / Tavily / SerpAPI / Bocha / Brave / MiniMax | ❌ 拒 — SerpAPI 收费 ($75/月) + Bocha 0 free tier verify + Brave 中文覆盖弱 + MiniMax 配额限 |
| (2) 仅替 SerpAPI + Bocha (保 Brave + MiniMax) | 2 替 + 4 沿用 | ❌ 拒 — Brave 中文覆盖 RSSHub 自部署完胜 + MiniMax 智谱 GLM-4-Flash 完胜 (联网搜索 MCP) |
| (3) 全 6 替 (反沿用) | 6 全新 | ❌ 拒 — Tavily 1000 credits/月 + Anspire 2500 点新户生产 OK, 沿用 reduces migration cost |
| **(4) 4 替 + 2 沿用 (本 ADR 采纳)** | 智谱+GDELT+Marketaux+RSSHub 替 / Tavily+Anspire 沿用 | ✅ 采纳 — 月成本 $0 / 中文 + 全球 + 金融三维覆盖 / Tavily+Anspire 反 migration 风险 |

## Consequences

### Positive

- **月成本 $0**: 全 6 源完全免费层. 沿用 V3 §20.1 #6 LLM 预算 $50/月 (NewsClassifier V4-Flash + RAG embedding) 反 News fetch 成本.
- **中文覆盖 + 全球事件 + 金融专用三维**: 智谱 + Anspire + RSSHub (中文) / Tavily + GDELT (全球 + 翻译) / Marketaux (金融 + sentiment).
- **0 商授 risk**: 6 源全免费层, 反 SerpAPI / Bocha 收费层 + 商授不确定.
- **API key 申请 ≤2 周**: GDELT/Marketaux/RSSHub/智谱即时, Anspire 沿用 (新户 2500 点), Tavily 沿用. 反 4-29 老 6 源新源 API key 申请 cost.
- **沿用 LiteLLM 接入**: 4-29 ADR-020 LiteLLM 多 Key 负载均衡 + retry exponential backoff 沿用, 0 LLM 路由层重写.

### Negative / Cost

- **RSSHub 自部署运维**: 0 第三方依赖 = 自维护 (Docker 部署 + 1 host) — 留 Sprint 2 implementation 时 host 选型 (Servy 沿用 D 盘 / 别的 host).
- **GDELT 2.0 学习曲线**: 全球事件 schema 跟 SerpAPI/Bocha 不同 (event-driven NOT keyword-driven), Sprint 2 implementation 时 schema mapping cost.
- **智谱 GLM-4-Flash 联网搜索 MCP 可用性**: 5-02 web_search 验证 OK, 沿用 LiteLLM provider config (Sprint 1 PR #221 体例) — Sprint 2 implementation 时 verify provider 兼容.

### Neutral

- **Tavily + Anspire 沿用**: 4-29 决议 2/6 源沿用, reduces migration cost. 0 影响 LiteLLM provider config 沿用.
- **0 prod caller break** (沿用 Sprint 1 8/8 PR sediment): V3 §3.1 + §20.1 #10 doc patch only, 0 ingestion implementation. Sprint 2 implementation 时 caller (V4-Flash NewsClassifier) 走新建模块沿用 ADR-031 体例.
- **V3 §11.1 path-level abstraction sustained**: News 6 源走 implementation detail, 沿用 path-level (反 V3 doc 加 row 6 源 module). Sprint 2 implementation 时 backend/qm_platform/news/ 子包沿用 ADR-001 体例.

## Implementation

| 阶段 | scope | 接触方 | 时机 |
|---|---|---|---|
| Step 1 | V3 §3.1 line 314 + 318-323 patch (老 6 源 → 新 6 源) | CC (本 PR) | 5-06 V3 doc patch |
| Step 2 | V3 §20.1 #10 line 1773 cite 同步订正 | CC (本 PR) | 5-06 V3 doc patch |
| Step 3 | ADR-033 sediment (本 file) | CC (本 PR) | 5-06 ADR # registry SSOT |
| Step 4 | REGISTRY.md ADR-033 row + 23→24 committed cite | CC (本 PR) | 5-06 ADR # registry SSOT |
| Step 5 | README.md ADR-033 row + 注释行修订 | CC (本 PR) | 5-06 ADR # registry SSOT |
| Step 6 | 6 News 源 mini-verify (web_search 沿用 SOP-2) | user 接触 + CC (Sprint 2 起手前 next sub-task) | Sprint 2 起手前 |
| Step 7 | API key 申请 (GDELT/Marketaux/RSSHub/智谱即时, Anspire 沿用, Tavily 沿用) | user 接触 | Sprint 2 起手前 ≤2 周 |
| Step 8 | RSSHub 自部署 host 选型 (Servy 沿用 D 盘 / 别的) | user 决议 + CC (Sprint 2 implementation) | Sprint 2 implementation 起手时 |
| Step 9 | Sprint 2 ingestion implementation (backend/qm_platform/news/ 子包 + LiteLLM provider 沿用) | CC (Sprint 2 implementation, 留下次 PR scope) | Sprint 2 起手 |

## Implementation finding cumulative (sub-PR 1-6 + 7a sediment, 5-06)

Sprint 2 ingestion implementation 累计 plugin-specific finding sediment (沿用 LL-115 候选 cite source 锁定真值 sustained, audit Week 2 batch sediment 候选):

| 源 | sub-PR | plugin-specific finding (5-06 fresh doc verify) | impl 体例 |
|---|---|---|---|
| 智谱 GLM-4.7-Flash | #231 (sub-PR 1) | POST + Bearer + **1302/1305 双 rate limit code** + 永久免费 ~1M tokens/天 | _ZhipuRetryableError sentinel + tenacity retry |
| Tavily | #232 (sub-PR 2) | POST + Bearer + topic="news" + **432/433 NEW limit codes** (反 429 traditional) + 0 published_date → now() UTC fallback | _TavilyRetryableError sentinel + plan/PAYG limit fail-loud |
| Anspire | #233 (sub-PR 3) | GET + Bearer + **64 char query hard limit** (5-06 fresh doc verify finding) + **top_k enum (10/20/30/40/50)** + **多 candidate response wrapper** (data/results/items) + `date` field ISO 8601 | _clamp_top_k() helper + 多 wrapper resolver |
| GDELT 2.0 | #234 (sub-PR 4) | GET + **0 API key (anonymous)** + articles 单 wrapper + **seendate YYYYMMDDTHHMMSSZ format** (5-06 fresh doc verify) + **language human-readable mapping** (English→en, Chinese→zh) + MAXRECORDS clamp [1, 250] | _parse_seendate() custom + LANGUAGE_MAP |
| Marketaux | #235 (sub-PR 5) | GET + **api_token query param (反 Bearer)** + **custom UA header** (反 default UA → Cloudflare 1010 block, 5-06 实测 finding) + data 单 wrapper + **ISO 8601 microseconds + Z parse** (Python 3.10 fallback) | DEFAULT_USER_AGENT="QuantMind-V2/1.0 (Python httpx)" |
| RSSHub 自部署 | #236 (sub-PR 6) | GET + **0 auth + Self-hosted localhost:1200** + **RSS XML response (反 JSON)** + **route path query** (e.g. "/jin10/news", 反 search keyword) + feedparser parse | Servy register sustained + DEFAULT_BASE_URL="http://localhost:1200" |
| **DataPipeline (sub-PR 7a)** | #本 PR | **6 fetcher 集成 ThreadPoolExecutor** (concurrent.futures, 沿用 6 fetcher 全 sync httpx.Client) + **早返回 (≥3 sources hit, V3§3.1 line 329)** + **hard timeout 30s** + **dedup url-first + title-hash fallback** (RSSHub None URL fallback) | concurrent + fail-soft per-source + dedup |

**真生产 enforcement 体例 sustained**: sub-PR 1-6 plugin-specific finding 真未 sediment 入 V3 §3.1 / ADR-033 main body — 沿用 LL-115 候选 sediment audit Week 2 batch (沿用 LL-098 X10 反 forward-progress default sustained). 本 ADR-033 patch 仅 sediment Implementation finding cumulative section, 真**反 V3 doc patch + 反 LL-115 row 真新建** (留 audit Week 2 batch sediment 候选 sustained).

**沿用案例 #5 真讽刺 lesson**: sub-PR 7 v1 prompt cite "DataPipeline + NewsClassifier 同 backend/qm_platform/news/ 子包 sediment" sustained 反 V3 line 1223 + news/__init__.py:28 docstring 真预约 ground truth → CC Phase 1 (b) STOP push back → user 决议 (1) PR 拆分 + path 修正 sustained → 本 sub-PR 7a (DataPipeline only) + sub-PR 7b NewsClassifier defer Sprint 3 prerequisite (V3 line 1223 真预约 path = `backend/app/services/news/`). 真**反复实证** governance 双层防御 (CC fresh verify + reviewer agent + V3 line/docstring cross-verify, 沿用 LL-067 + LL-104 sustained).

## References

- V3 §3.1 News 多源接入 (L0.1) — 6 源清单 + LiteLLM 接入 (本 PR line 312 + 318-323 patch)
- V3 §20.1 #10 — News 6 源全实施决议 (本 PR line 1773 cite 同步订正)
- ADR-020 (Claude 边界 + LiteLLM 路由, reserved) — 6 源全走 LiteLLM 接入沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制) — 5-02 换源决议沿用 V3 doc patch + ADR sediment
- ADR-031 (S2 LiteLLMRouter implementation path) — Sprint 2 ingestion module pattern 沿用
- ADR-032 (S4 caller bootstrap factory + naked LiteLLMRouter export 限制) — caller 走 get_llm_router() 沿用
- LL-098 X10 (反 forward-progress default) — 本 PR 0 ingestion implementation 起手
- LL-114 候选 (audit cite schtask total 跟 active register 区别, 5-06 v7 patch sediment 候选) — sprint_state v7 SSOT drift 沿用 cite drift 体例 audit Week 2 batch sediment
- 5-02 web_search 验证 (智谱 GLM-4-Flash + GDELT 2.0 + Marketaux + RSSHub) — user prompt + Claude.ai 战略对话 sediment SSOT
- sprint_state v7 cite 5-02 换源决议 SSOT drift 主动 finding (line 110/197/265 sustained 老 6 源 cite, 0 sediment 5-02 换源决议) — audit Week 2 batch sediment 候选
