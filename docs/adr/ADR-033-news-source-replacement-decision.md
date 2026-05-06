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
- sprint_state v7 line 110/197/265 sustained 老 6 源 cite (0 sediment 5-02 换源决议)
- V3 doc §3.1 + §20.1 #10 0 patch (本 PR sediment) — 反 silent drift, 走 ADR-022 集中修订机制

**触发**: V3 Tier A Sprint 2 起手前 prerequisite (V3 §3.1 6 News 源 API key 申请) — 必先 V3 doc patch + ADR sediment 后, Sprint 2 ingestion implementation 起手.

**沿用**:
- 4-29 ADR-020 (Claude 边界 + LiteLLM 路由, reserved): 6 源全走 LiteLLM 接入沿用
- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制): 5-02 换源决议沿用 V3 doc patch + ADR sediment, 反 silent overwrite
- LL-098 X10 (反 forward-progress default): 本 PR 0 ingestion implementation 起手, 留 Sprint 2 implementation scope

## Decision

**新 6 源** (沿用 V3 §3.1 表格体例):

| # | 源 | 类型 | 用途 | API 限速策略 | 替换 / 沿用 |
|---|---|---|---|---|---|
| 1 | 智谱 GLM-4-Flash | 中文 LLM 接入 + 联网搜索 | 中文综合主源 | 完全免费 + OpenAI 兼容 + LiteLLM 多 Key 负载均衡 | 替 MiniMax |
| 2 | Tavily | 英文 + 翻译 | 海外信号 (港美 ADR 联动) | 1000 credits/月永久免费 + LiteLLM 限速 fallback | 沿用 |
| 3 | Anspire | 中文财经 | 中文财经主源 | 新户 2500 点 + LiteLLM 多 Key 负载均衡 | 沿用 |
| 4 | GDELT 2.0 | 全球事件 | 跨境 + 突发 | 0 API key + 完全免费 + 7×24 实时 stream | 替 Bocha |
| 5 | Marketaux | 金融专用 | 金融信号 + sentiment 标签 | 80 markets + 完全免费 (100 req/day) + sentiment pre-tagged | 替 SerpAPI |
| 6 | RSSHub 自部署 | 中文财经 RSS | 长尾 + 全主流源 | 自部署 + 0 API key + 0 第三方依赖 | 替 Brave |

**砍源 4 个** (5-02 web_search 验证后决议):

| # | 砍源 | 砍因 |
|---|---|---|
| 1 | Serper | 中文覆盖弱 + 配额限 |
| 2 | DuckDuckGo | 反 API + 仅 Web scraping, 反生产稳定 |
| 3 | Bocha | 收费层冲突 + 0 商授 free tier verify |
| 4 | Alpha Vantage | 英文金融 only + 中文 0 覆盖, 跟 Marketaux 重合 |

**月成本**: $0/month (全 6 源完全免费层 / Tavily 1000 credits 永久 / Anspire 2500 点新户 / 智谱 GLM-4-Flash 完全免费 / GDELT 0 API key / Marketaux 100 req/day / RSSHub 自部署).

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
