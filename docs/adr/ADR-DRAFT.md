# ADR-DRAFT — Append-only candidate ADR backlog

> **真意义**: 跨 sprint cumulative ADR # 候选 + 主题 sediment, 反**散落 LL backlog / sprint_state cite / handoff** 4 source 漂移 (沿用 LL-105 SOP-6 ADR # reservation 4 source cross-verify). 真**单 source 锁定 candidate** 给下一 sprint 起手 promote committed.
> **机制**: append-only — 每 sprint 真 candidate 加一行, **0 删 0 改顺序**. promote 走时 row 标 `→ ADR-XXX (committed)` + cite source PR/file.
> **触发**: 5-07 sub-PR 8a (5-06 ADR-037 + 铁律 45 + LL-106 sediment 后真**首次 SOP enforcement** 落 sub-PR 8a, 真讽刺案例 #7 候选 sediment).
> **关联文档**: [docs/adr/REGISTRY.md](REGISTRY.md) (committed + reserved SSOT) / [docs/adr/README.md](README.md) (索引 + 模板) / [LESSONS_LEARNED.md](../../LESSONS_LEARNED.md) LL-105/106 (4 source cross-verify + fresh read SOP).

## 真候选 list (append-only, 0 delete 0 reorder)

| # | 真主题 | 真 source (sprint period sediment) | 真状态 | promote target |
|---|---|---|---|---|
| 1 | News retention cron (hypertable + 90 day retention) | sub-PR 8a 5-07 sediment, V3§3.1 line 354 真预约 + 沿用 docs/audit/risk_replay/ retention 体例 | candidate | sub-PR 10 真起手时 promote |
| 2 | News fetch query strategy SSOT (5 源 vs RSSHub route path 体例分裂) | sub-PR 8a 5-07 sediment, V3§3.1 sub-PR 6 docstring "RSSHub 走独立 pipeline" sustained | candidate | sub-PR 8b cadence 决议时 promote (Beat schedule + cadence + RSSHub 路由层契约) |
| 3 | Beat schedule paused indefinite 体例 (X9 reverse case sediment) | sub-PR 8a 5-07 verify finding P0-1, risk-daily-check + intraday-risk-check 4-29 PAUSE 7 天 + sub-PR 8a 决议 indefinite paused | candidate | S5 L1 实时化时 sunset 切换 / 或独立 ADR audit Week 2 batch |
| 4 | Production-level vs import-level 闭环语义契约 | sub-PR 8a 5-07 verify finding 真讽刺案例 #6, "完整闭环" claim sediment 时必显式标 import-level vs production-level | candidate | audit Week 2 batch (governance 沿用) |
| 5 | News API key SSOT (settings vs os.environ 选型) | sub-PR 8a 5-07 sediment, 本 PR 加入 5 News API key 走 settings (Pydantic) 反 os.environ 直读 | candidate | 已落实 sub-PR 8a (本身 ADR-DRAFT row 1 真 promote candidate, 0 ADR # reserve) |
| 6 | LiteLLM cost registry V4 gap (cost_usd=None 真生产风险 + 7-24 deadline plan) | sub-PR 8a-followup-B-yaml PR #247 5-07 sediment. LiteLLM model_cost 真**0 entry** for `deepseek/deepseek-v4-flash` + `deepseek/deepseek-v4-pro` → BudgetGuard cost_usd_total 永 0, V3 §20.1 #6 $50/月 budget cap 真**反 trigger**. 7-24 deadline: deepseek-chat / deepseek-reasoner 弃用前 LiteLLM SDK 升级 prerequisite. 真生产 evidence: 5-07 sub-PR 8a-followup-B Phase 1 8 path 真测 cost_usd=None for v4-* | candidate | LiteLLM SDK 升级 verify v4-* registry entry 真生效 时 promote ADR-038 + 真生产 cost data 沿用体例 |
| 7 | Audit failure path coverage S2.4 sub-task 真起手 sediment | sub-PR 8a-followup-B-audit PR #248 5-07 sediment 部分 closed (BUG #2 + #3). Sprint 1 PR #224 真**success-only audit** deferred S2.4+ — 真**失败 path** error_class hardcoded None 真**audit blind primary fail signal** sustained 5-07 sub-PR 8a 真生产 6 row error_class=NULL 反 is_fallback=True. 已部分 closed: BUG #2 dynamic detect 4 case + BUG #3 try/except 包络 failure path audit row + re-raise. 真**残余 sub-task**: failure path 真**S2.4 完整 design** (含 retry policy / circuit breaker / DingTalk push 触发 LL_AUDIT_INSERT_FAILED 等). **5-07 sub-PR 8b-llm-audit-S2.4 partial promote**: retry policy 真**ADR-039** sediment ✅; 真**残余 sub-task**: circuit breaker (sub-PR 8b-resilience 真预约) + DingTalk push (sub-PR 9 真预约) sustained | **→ ADR-039 (committed, partial)** | 沿用 sub-PR 8b-resilience + sub-PR 9 真预约 完整 closure |
| 8 | DeepSeek API 3 层暗藏机制 (alias-pass-through + backend silent routing + LiteLLM cost registry gap) | sub-PR 8a-followup-B Phase 1 5-07 真测真值 sediment 候选 #12 + #13 + #14 真讽刺案例汇总. **3 层机制**: (a) alias-pass-through layer (DeepSeek API echoes caller-sent model name as response.model, 反 underlying provider/model name) / (b) backend silent routing layer (deepseek-chat / deepseek-reasoner 真**legacy alias** 走 V4 underlying via thinking on/off, 真**dual-mode model** sustained 沿用官方 7-24 deprecation map) / (c) LiteLLM cost registry layer (v4-* 真**0 cost data** sustained until SDK 升级). 真讽刺 #14 sediment: vanilla LiteLLM call 漏 thinking 参数 → 默认 thinking enabled → CC 3 次 push back 误归因, user 第 7 push back catch correctly (web_fetch 官方 API docs verify 真值) | candidate | DeepSeek API watch SOP ADR-040 sediment + 7-24 deadline plan governance PR (audit Week 2 batch B 候选) |
| 9 | yaml double-model sync governance (反 single-model drift 体例 sustained) | sub-PR 8a-followup-B-yaml PR #247 5-07 sediment 沿用 user 决议 #4 反留尾巴. yaml 修真**双 model 同步切换** (deepseek-v4-flash + deepseek-v4-pro 全切 V4 underlying), 反**单 model 切换** governance 漂移加深 (e.g. flash 切 V4 + pro 沿用 reasoner 真**alias-underlying inconsistency**). prompt 真测决议规则: "双 model path 1+2 不同步 → STOP escalate user (反单 model 切换, governance 漂移加深)". 真生产 sustained 5-07 yaml 双 model 同步 + thinking enabled/disabled 真**align V3 §5.5 chat/reasoner semantic** 体例 | candidate | governance ADR-041 sediment "双 model alias-underlying sync 体例" + 7-24 deadline plan migration governance PR |
| 10 | vanilla LiteLLM call thinking 参数 verify SOP (web_fetch 官方文档 prerequisite) | sub-PR 8a-followup-B Phase 1 5-07 真**真讽刺 #14** sediment. CC vanilla `litellm.completion(model=...)` 真**0 thinking 参数** → DeepSeek 默认 thinking enabled → reasoning_content 出现 → CC 3 次 push back 误归因 "silent routing reasoner", user 第 7 push back catch + 决议 web_fetch DeepSeek 官方 API docs 真测真值 (api-docs.deepseek.com/zh-cn/). SOP sediment: **任 3rd-party API frame finding/修复必 web_fetch 官方文档 verify prerequisite** (反 vanilla SDK call 默认参数误归因). 沿用 ADR-037 §Context 第 7 漂移类型 candidate (3rd-party API 默认参数误归因 silent semantic drift) | candidate | governance ADR-042 sediment "3rd-party API spec watch SOP + vanilla call 漏 thinking 参数 verify" + LL sediment 加 LESSONS_LEARNED.md (chunk B 候选) |

## 真 maintenance 规则

### Append-only 真意义

- 新 candidate 走**末尾 append**, 0 删 0 改顺序 (沿用 LL-099 append-only 体例).
- promote 时 row 真**保留** + `真状态` 改 `committed` + `promote target` cite ADR-XXX.
- 真 deprecated candidate 真**保留** + `真状态` 改 `deprecated` + `promote target` cite 撤销原因.

### 真 promote 走 SOP

新 candidate promote committed 时:
1. grep 4 source cross-verify (LL-105 SOP-6): V3 §18.1 / audit docs / sprint_state cite / LL backlog
2. 任一 source 漂移 → STOP + 反问 user
3. 全 source 一致 → reserve ADR-XXX in [REGISTRY.md](REGISTRY.md) → create ADR-XXX file + 同 PR update REGISTRY + ADR-DRAFT row 标 `→ ADR-XXX (committed)`

### 真 deprecated 走 SOP

candidate 真**不再相关** (e.g. 上游设计变化 / source 撤销):
- row 真保留 + `真状态` 改 `deprecated` + `promote target` cite 撤销原因
- 反**物理删除** (沿用 append-only 体例, 历史可追溯)

## 真讽刺案例 candidate (本 file 真触发)

### 候选 #7 (5-07 sediment, sub-PR 8a 触发)

**漂移类型**: ADR # reservation source 分散 (V3 §18.1 / audit docs / sprint_state cite / LL backlog 4 source 0 single source of truth, sustained 5-02 sprint period 2 次 N×N 同步漂移 textbook 案例 — ADR-024 + ADR-027).

**case**: 5-06 ADR-037 + 铁律 45 SOP enforcement 后, 5-07 sub-PR 8a 真**首次 SOP**生效 catch P0 finding (Risk Beat 4-29 PAUSE 7 天 + Sprint 2 0 caller wire). 沿用 5-06 SOP **真生效** 但 ADR # reservation 4 source SOP-6 真**未生效** — 本 sub-PR 8a 触发 5 candidate (News retention / Query strategy SSOT / Beat indefinite paused / production-level 闭环 / News API key SSOT) 真**散落 LL backlog + sprint_state cite + V3 line cite**, 真**单 source 锁定** 真候选 = 本 ADR-DRAFT.md.

**讽刺点**: ADR-DRAFT.md 真**预防 SOP-6 漂移** 的 cumulative sediment file, 但本 file 真**第一次 create 走 sub-PR 8a 5-07** — 沿用 5-02 sprint period sediment 后**5 天 0 触发**, sub-PR 8a 真**首次 catch** + create. 沿用 5-06 ADR-037 governance enforcement 体例 sustained.

**沿用 ADR-037 §Context 5 漂移类型 + 候选第 6 类**:
- 真**ADR # reservation source 分散** (本 file 真预防类型) — 沿用 SOP-6 LL-105 sediment

## 引用规范

- 新引用: `docs/adr/ADR-DRAFT.md row N` (e.g. `ADR-DRAFT.md row 1` for News retention)
- promote 后引用: `ADR-XXX (committed)` + 沿用 [REGISTRY.md](REGISTRY.md) 真**SSOT cite** 体例
