# V3 实施期 横切层 Sprint Plan v0.1 (HC-1 + HC-2 + HC-3 + HC-4, 4 sprint)

> **本文件 = V3 风控长期实施期 横切层 (Gate D) 4 sprint chain 起手前 user-approved plan sediment** (post-Tier B 6-sprint chain FULLY CLOSED cumulative Session 53+24 + ADR-071 sediment 真值落地, plan-then-execute 体例 第 5 case 实证累积扩, sustained Plan v0.2 sub-PR sediment 体例).
>
> **Status**: ✅ User approved (Session 53+25, 3 决议 lock: D1=4-sprint HC-1~4 / D2=both-DEFER LiteLLM-3month + dashboard / D3=both-into-HC-4 5y-replay + north_flow/iv). Sediment from CC 推荐 (Gate D 5-item state assessment + 3 fork) + user AskUserQuestion 1 round ack (3 决议 全 picked CC 推荐).
>
> **本文件版本**: v0.1 (post-Tier B FULLY CLOSED cumulative + ADR-071 sediment + 3 决议 lock + plan-then-execute 体例 第 5 case 实证累积扩 cumulative 体例 sustainability, 2026-05-14, Plan v0.3 sub-PR sediment cycle)
>
> **scope**: V3 横切层 sprint chain (HC-1 元监控 alert-on-alert + HC-2 失败模式 15 项 enforce + 灾备演练 synthetic + HC-3 CI lint verify + prompts/risk eval + HC-4 carried deferral 路由 + 5y replay + north_flow/iv wire + ROADMAP sediment + Gate D formal close) plan + 3 决议 lock sediment + cycle baseline 真值 + cross-sprint surface risk + Gate D criteria + 横切层 真测期 SOP + plan review trigger SOP.
>
> **not scope**: V3 spec 详细拆分 → [QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §13/§14/§17.1 / Constitution layer scope → [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) §L10.4 / sprint-by-sprint orchestration index → [V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) §2.3 (Plan v0.3 sediment NEW) / sprint chain 起手 SOP entry point → [V3_LAUNCH_PROMPT.md](V3_LAUNCH_PROMPT.md) §3 / Tier A scope → [V3_TIER_A_SPRINT_PLAN_v0.1.md](V3_TIER_A_SPRINT_PLAN_v0.1.md) / Tier B scope → [V3_TIER_B_SPRINT_PLAN_v0.1.md](V3_TIER_B_SPRINT_PLAN_v0.1.md) / cutover scope → 留 Plan v0.4 (Gate E scope).
>
> **关联 ADR**: ADR-022 (反 silent overwrite + 反 retroactive content edit + 反 abstraction premature) / ADR-037 + 铁律 45 (4 doc fresh read SOP + cite source 锁定) / ADR-049 §3 (chunked sub-PR 体例 greenfield scope) / ADR-063 (paper-mode skip empty-system anti-pattern — 本 plan D2 LiteLLM-3month defer 沿用 paper-mode deferral pattern) / ADR-064 (Plan v0.2 5 决议 lock + D4=否 每 Tier 独立 plan 体例, 本 Plan v0.3 直接 follow-up) / ADR-070 (TB-5b replay acceptance — 本 plan HC-4 5y replay 沿用 `_TimingAdapter` 体例) / ADR-071 (Tier B FULLY CLOSED + 2 Gate C sub-item DEFERRED to Plan v0.3 + 8-item batch doc-amend) / ADR-072 候选 (Plan v0.3 3 决议 lock, 本 sub-PR sediment) / 横切层 期内候选 ADR-073 (HC-1 元监控 alert-on-alert closure) + ADR-074 (HC-2 失败模式 enforce + 灾备演练 closure) + ADR-075 (HC-3 prompts/risk eval iteration closure) + ADR-076 (HC-4 横切层 closure cumulative + Gate D formal close)
>
> **关联 LL**: LL-098 X10 (反 forward-progress default) / LL-100 (chunked SOP target) / LL-115/116 (fresh re-read enforce family) / LL-158 (Tier B plan-then-execute 体例 第 4 case) / LL-164 (Tier B closure 体例 + verification-methodology-must-match-rule-semantics + Gate verifier-as-charter pattern) / LL-165 候选 (横切层 plan-then-execute 体例 第 5 case sediment, 本 sub-PR sediment) / 横切层 期内候选 LL-166 (HC-1 元告警 5 P0 场景 synthetic injection 实测) + LL-167 (HC-2 失败模式 15 vs 12 真值差异 + 灾备演练 synthetic 体例) + LL-168 (HC-3 prompts/risk eval V4-Flash→V4-Pro 决议体例) + LL-169 (HC-4 横切层 closure 体例 sediment)

---

## Context

V3 Tier B (6-sprint chain T1.5→TB-1→TB-2→TB-3→TB-4→TB-5) **FULLY CLOSED 2026-05-14** (TB-5c PR #349 ADR-071, Gate B 5/5 + Gate C 6/6 + V3 §15.4 4/4 + §13.1 5/5). Plan v0.3 = V3 实施期第 3 个 Tier-level plan (沿用 ADR-064 D4=否 每 Tier 独立 plan 体例: v0.1=Tier A / v0.2=Tier B / **v0.3=横切层** / v0.4=cutover).

**横切层 = Constitution §L10.4 Gate D**. Gate D checklist 5 项:

1. V3 §13 元监控 `risk_metrics_daily` + alert-on-alert production-active
2. V3 §14 失败模式 enforce (设计 §14 表 enumerate **15 模式**, 非 checklist cite 的 "12 项" — 见 §H Finding #1) + 灾备演练 ≥1 round 沉淀 `docs/risk_reflections/disaster_drill/`
3. V3 §17.1 CI lint `check_llm_imports.sh` 生效 + pre-push hook 集成
4. `prompts/risk/*.yaml` prompt eval iteration ≥1 round (V4-Flash → V4-Pro upgrade 决议体例 sediment)
5. LiteLLM 月成本 ≤ V3 §16.2 上限 ≥3 month 持续 ≤80% baseline

**起手前 state assessment** (CC fresh re-read Constitution §L10.4 + V3 §13/§14/§16.2/§17.1 实测):

| Gate D 项 | Tier A/B 已建? | 横切层 净新工作量 |
|---|---|---|
| 1. 元监控 risk_metrics_daily + alert-on-alert | `risk_metrics_daily` 表 + `daily_aggregator.py` + `daily_metrics_extract_tasks.py` + Beat ✅ production-active (Tier A S10, ADR-062) | **alert-on-alert (§13.3 元告警) 5 P0 场景未 wire** — HC-1 净新 |
| 2. 失败模式 enforce + 灾备演练 | 检测/降级路径散落各处 (S3-S9 cumulative) | enforce matrix audit + 缺失 wire + 灾备演练 sediment dir 空 — HC-2 净新 |
| 3. CI lint + pre-push 集成 | `check_llm_imports.sh` + `config/hooks/pre-push` + `pre-commit` + `test_llm_import_block_governance.py` + `docs/LLM_IMPORT_POLICY.md` ✅ (ADR-020/032) | **verify-only** — HC-3 基本已 closed |
| 4. prompts/risk eval ≥1 round | 5 YAML prompts ✅ + `quantmind-v3-prompt-eval-iteration` skill ✅ | eval iteration 实跑 ≥1 round + ADR — HC-3 净新 |
| 5. LiteLLM 月成本 ≥3 month ≤80% baseline | `quantmind-v3-llm-cost-monitor` skill ✅ | **inherently wall-clock** — paper-mode 0 traffic, D2=defer to Gate E |

**carried-forward DEFERRALS from Tier B** (Plan v0.2 §C 横切层 起手 prereq sediment + ADR-071 D4):

- Gate C item 3 sub-item — RAG retrieval 命中率 ≥ baseline measurement → **route to Gate E** (need live production query traffic, paper-mode 物理不可做)
- Gate C item 5 sub-item — lesson→risk_memory 后置抽查 ≥1 live round → **route to Gate E** (同上)
- 5y full minute_bars replay (ADR-064 D3=b — Tier B 仅 2 关键窗口) → **HC-4** (D3 决议)
- ADR-067 D5 — `north_flow_cny` + `iv_50etf` MarketIndicators real-data-source wire → **HC-4** (D3 决议)
- `RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` full sediment (Constitution §0.1) → **HC-4** (Tier B closure REACHED, sediment 时机 now due)

**3 决议 lock** (ADR-072 sediment, sustained ADR-064 5-决议-lock 体例):

- **D1 = 4-sprint HC-1~4** — HC-1 元监控 alert-on-alert / HC-2 失败模式 15 项 enforce + 灾备演练 synthetic / HC-3 CI lint verify + prompts/risk eval / HC-4 carried deferral 路由 + 5y replay + north_flow/iv wire + ROADMAP sediment + Gate D formal close. 每 sprint chunked 2-3 sub-PR (沿用 LL-100 chunked SOP + Tier B sub-PR 体例).
- **D2 = both DEFER** — (a) Gate D item 5 LiteLLM 月成本 ≥3 month ≤80% baseline → ⏭ DEFERRED to Gate E 自然累积 (paper-mode 0 live LLM traffic, 3-month wall-clock 不可压缩, sustained ADR-063 paper-mode deferral pattern); (b) V3 §13.4 监控 dashboard (frontend `risk-monitoring` 页面) → NOT in Gate D checklist (checklist item 1 仅要求 risk_metrics_daily + alert-on-alert production-active, dashboard 是 §13.4 独立设计), 留独立 frontend track, NOT 横切层 scope.
- **D3 = both into HC-4** — 5y full minute_bars replay (~191M rows, TB-1 RiskBacktestAdapter + ADR-070 `_TimingAdapter` infra 已就绪 → 纯 replay run) + ADR-067 D5 `north_flow_cny`/`iv_50etf` real-data-source wire → 都纳入 HC-4 scope, 清掉 carried deferral backlog (剩 2 个 Gate C sub-item route to Gate E — paper-mode 物理不可做).

---

## §A Per-sprint plan (横切层 HC-1 + HC-2 + HC-3 + HC-4, 4 sprint)

### HC-1 — 元监控 alert-on-alert production-active (Gate D 项 1)

| element | content |
|---|---|
| Scope | V3 §13.3 元告警 (alert-on-alert) 5 P0 场景 wire: (1) L1 RealtimeRiskEngine 心跳超 5min 无 tick (xtquant 断连) / (2) LiteLLM API 失败率 > 50% (5min window) / (3) DingTalk push 失败 (无 200 response) / (4) L0 News 6 源全 timeout (5min) / (5) L4 STAGED 单 status PENDING_CONFIRM 超 35min (cancel_deadline 失效). + 元告警 channel fallback chain: 主 DingTalk @ user → 备 Email backup → 极端 (DingTalk 不可用) 系统弹窗 + log P0 (V3 §13.3 line 1426-1429). risk_metrics_daily 表 + daily_aggregator + Beat 已 production-active (Tier A S10 ADR-062) → HC-1 在其上 wire meta-alert layer, NOT 重建 metrics 表. 3-layer 体例 sustained (铁律 31/32): Engine PURE (meta-alert rule eval 纯函数 — 心跳 delta / 失败率窗口计算 / timeout 判定) / Application (meta_monitor_service orchestration + channel fallback) / Beat dispatch (meta_monitor_tasks 5min cadence, transaction owner 铁律 32). |
| Acceptance | 5 P0 元告警 场景 each unit-tested (边界 case: 心跳 4:59 vs 5:01 / 失败率 49% vs 51% / News 5/6 源 timeout vs 6/6 / STAGED 34min vs 36min); 元告警 channel fallback chain verified (DingTalk 200 → 跳过 backup / DingTalk 非 200 → email / email 失败 → 系统弹窗+log P0); synthetic-injection integration test (沿用 TB-5a synthetic scenario fixture 体例 — 注入 5 场景 trigger condition, assert 元告警 fire + channel 正确); risk_metrics_daily aggregate "0 P0 元告警" verify path (V3 §15.4 #4 sustained); 0 真账户 / 0 broker / 0 .env mutation 红线 5/5 sustained. |
| File delta | ~8-12 files / ~1000-1800 lines (meta-alert Engine PURE interface + rules ~300-500 / meta_monitor_service Application ~200-400 / meta_monitor_tasks Beat + beat_schedule wire ~100-200 / channel fallback (沿用现 dingtalk_webhook_service + email backup) ~100-200 / unit + synthetic-injection tests ~400-600 / ADR-073 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 3 sub-PR**: HC-1a (meta-alert Engine PURE interface + 5 元告警 rule 纯函数 + unit tests) → HC-1b (meta_monitor_service Application + channel fallback chain + meta_monitor_tasks Beat wire + beat_schedule entry) → HC-1c (synthetic-injection integration test + risk_metrics_daily "0 P0 元告警" verify path + ADR-073 sediment) |
| Cycle | ~1-1.5 周 baseline (HC-1a ~0.4 周 + HC-1b ~0.4 周 + HC-1c ~0.4 周); replan trigger 1.5x = ~1.5-2.25 周 |
| Dependency | 前置: Tier B FULLY CLOSED ✅ (ADR-071); risk_metrics_daily production-active ✅ (Tier A S10 ADR-062) / 后置: HC-2 (失败模式 15 项 元告警 flag 依赖 alert-on-alert layer) |
| LL/ADR candidate | **ADR-073** ✅ promote (HC-1 元监控 alert-on-alert closure — 5 P0 元告警 场景 + channel fallback chain 决议 lock); **LL-166** ✅ promote (元告警 5 P0 场景 synthetic injection 实测 + 边界 case finding) |
| Reviewer reverse risk | 元告警 silent skip 某场景 (LL-098 X10, mitigation: 5 场景 each 独立 unit test + synthetic-injection integration assert); channel fallback chain silent short-circuit (mitigation: fallback chain 3 段 each test); 元告警 与 §13.4 dashboard scope creep (mitigation: D2=defer dashboard, HC-1 仅 wire alert-on-alert layer, NOT frontend) |
| 红线 SOP | redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce; 0 .env mutation; 0 真账户 broker call; 0 production yaml mutation; 红线 5/5 sustained (cash + 0 持仓 + LIVE_TRADING_DISABLED + EXECUTION_MODE + QMT_ACCOUNT_ID) |
| Paper-mode | sustained; 元告警 channel = mock DingTalk/email/弹窗 in test; synthetic-injection 走 fixture trigger condition, 0 真 live production system contact |

### HC-2 — 失败模式 15 项 enforce matrix + 灾备演练 synthetic ≥1 round (Gate D 项 2)

| element | content |
|---|---|
| Scope | V3 §14 失败模式表 audit — 设计表 enumerate **15 模式** (mode 1-12 + mode 13 BGE-M3 OOM + mode 14 RiskReflector V4-Pro 失败 + mode 15 LIVE_TRADING_DISABLED 双锁失效; checklist cite "12 项" 是 V3 §14 表演进前的 stale cite — 见 §H Finding #1, 决议 enforce 全 15 superset). 每模式 audit: 触发条件 / 检测 mechanism / 降级路径 / 恢复条件 / 元告警 flag 是否 wired → produce enforcement matrix doc (gap list). Wire 任何缺失的 detection/degrade path. 灾备演练 ≥1 round = **synthetic injection** (沿用 TB-5a synthetic scenario fixture 体例 — 注入 failure mode 1-12 trigger condition via pytest fixture/script, NOT calendar-style monthly wall-clock drill — sustained memory feedback_no_observation_periods 反日历式观察期). Sediment `docs/risk_reflections/disaster_drill/2026-MM-DD.md` (V3 §14.1 line 1472 dir 体例). |
| Acceptance | 15-mode enforcement matrix doc complete (每 mode: 触发条件 cite + 检测 mechanism file:line cite + 降级路径 file:line cite + 恢复条件 + 元告警 flag); gap list 中 缺失 detection/degrade 全 wired + unit test; 灾备演练 ≥1 round synthetic injection 覆盖 mode 1-12 (V3 §14.1 line 1465-1470 演练清单: 1-2 LiteLLM+xtquant / 3-5 PG+Redis+DingTalk / 6 News 6 源 / 9 Crisis regime / 11 RealtimeRiskEngine kill) + sediment doc; failure-mode-injection tests CI green (沿用 pre-push hook X10 + smoke pattern); 0 真账户 / 0 broker / 0 .env mutation 红线 5/5 sustained. |
| File delta | ~10-15 files / ~1200-2000 lines (enforcement matrix audit doc ~300-500 / 缺失 detection/degrade wire ~300-600 + unit tests ~300-500 / 灾备演练 synthetic injection fixture/script ~300-500 + sediment doc ~150-300 / ADR-074 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 3 sub-PR**: HC-2a (V3 §14 15-mode enforcement matrix audit doc + gap list — verify-heavy, 每 mode file:line cite) → HC-2b (gap list 缺失 detection/degrade path wire + unit tests) → HC-2c (灾备演练 ≥1 round synthetic injection mode 1-12 + sediment doc `docs/risk_reflections/disaster_drill/` + ADR-074 sediment) |
| Cycle | ~1.5-2 周 baseline (HC-2a ~0.5 周 + HC-2b ~0.6 周 + HC-2c ~0.6 周); replan trigger 1.5x = ~2.25-3 周 |
| Dependency | 前置: HC-1 closed (失败模式 mode 1/2/5/6/11 的 元告警 flag 依赖 alert-on-alert layer) / 后置: HC-4 (Gate D formal close 依赖 失败模式 enforce + 灾备演练 ≥1 round) |
| LL/ADR candidate | **ADR-074** ✅ promote (HC-2 失败模式 15 项 enforce + 灾备演练 synthetic ≥1 round closure — 15 vs 12 真值差异 + enforcement matrix 体例 + 灾备演练 synthetic methodology lock); **LL-167** ✅ promote (失败模式 15 vs 12 真值差异 finding + 灾备演练 synthetic injection 体例 反日历式观察期) |
| Reviewer reverse risk | 失败模式 silent skip mode 13/14/15 (因 checklist cite "12 项", LL-098 X10, mitigation: §H Finding #1 决议 enforce 全 15 superset + matrix doc 全 15 row); enforcement matrix file:line cite 漂移 (LL-115 family, mitigation: 每 cite fresh grep verify, sustained 铁律 45); 灾备演练 退化为日历式观察期 (memory feedback_no_observation_periods, mitigation: synthetic injection fixture 体例 sustained TB-5a, 0 wall-clock wait); 灾备演练 sediment doc silent overwrite (ADR-022, mitigation: append-only dir 体例) |
| 红线 SOP | sustained HC-1; redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce; 0 .env mutation (mode 15 LIVE_TRADING_DISABLED 双锁 test 走 config_guard mock, NOT 真改 .env); 0 真账户 broker call (mode 12 broker 故障 test 走 mock); 红线 5/5 sustained |
| Paper-mode | sustained HC-1; 灾备演练 synthetic injection 全走 fixture/mock (mock LiteLLM key off / mock xtquant 断连 / mock PG/Redis/DingTalk down / mock Crisis regime 合成 -7% 大盘 + 500 跌停 / mock RealtimeRiskEngine kill), 0 真 live production system contact |

### HC-3 — CI lint verify-only + prompts/risk eval iteration ≥1 round (Gate D 项 3 + 4)

| element | content |
|---|---|
| Scope | **(项 3) CI lint verify-only**: V3 §17.1 CI lint 已 substantially closed in Tier A (ADR-020 + ADR-032) — `scripts/check_llm_imports.sh` + `config/hooks/pre-push` + `config/hooks/pre-commit` + `backend/tests/test_llm_import_block_governance.py` + `docs/LLM_IMPORT_POLICY.md` 全 exist. HC-3 = **verify-only** confirm production-active (NOT 重建): check_llm_imports.sh 实跑 verify + pre-push hook 集成 verify + governance test CI green verify. 注: V3 §17.1 spec cite `check_anthropic_imports.py` 是 pre-ADR-031 path drift, 真值 = `scripts/check_llm_imports.sh` (sustained Constitution §L10.1 item 7 path drift 真值修正 + ADR-031 §6 path 决议). **(项 4) prompts/risk eval iteration ≥1 round**: 走 `quantmind-v3-prompt-eval-iteration` skill on 5 YAML (`prompts/risk/news_classifier_v1.yaml` / `bull_agent_v1.yaml` / `bear_agent_v1.yaml` / `regime_judge_v1.yaml` / `reflector_v1.yaml`) — eval methodology + per-prompt result + V4-Flash → V4-Pro upgrade 决议体例 sediment + ADR. |
| Acceptance | CI lint verify report: 5 components (check_llm_imports.sh / pre-push / pre-commit / governance test / LLM_IMPORT_POLICY.md) each production-active confirmed + check_llm_imports.sh 实跑 0 BLOCKED on current `backend/app/**` + `backend/scripts/**` (除 `integrations/litellm/`); prompts/risk eval iteration ≥1 round complete (5 YAML each: eval methodology cite + result + V4-Flash/V4-Pro routing 决议 — sustained ADR-036 LLM model routing 体例); ADR-075 sediment 锁 eval 结果 + routing 决议; 0 真账户 / 0 broker / 0 .env mutation 红线 5/5 sustained. |
| File delta | ~5-8 files / ~500-1000 lines (CI lint verify report doc ~150-300 / prompts/risk eval methodology + result doc ~300-500 / 任何 prompt YAML iteration patch (若 eval 决议 iterate) ~50-150 / ADR-075 sediment ~5-8KB) |
| Chunked sub-PR | **chunked 2 sub-PR**: HC-3a (CI lint verify-only report — 5 components production-active confirm + check_llm_imports.sh 实跑 verify) → HC-3b (prompts/risk eval iteration ≥1 round on 5 YAML + V4-Flash→V4-Pro routing 决议 + ADR-075 sediment) |
| Cycle | ~1 周 baseline (HC-3a ~0.3 周 verify-only + HC-3b ~0.6 周); replan trigger 1.5x = ~1.5 周 |
| Dependency | 前置: HC-1 closed (serial 体例 sustained per Plan v0.2 D1=a — HC-3 与 HC-2 内容上可并行, 但沿用串行 phase transition 干净体例, NOT 并行) / 后置: HC-4 (Gate D formal close 依赖 CI lint verify + prompts eval ≥1 round) |
| LL/ADR candidate | **ADR-075** ✅ promote (HC-3 prompts/risk eval iteration closure — eval methodology + 5 YAML result + V4-Flash→V4-Pro routing 决议体例 lock; CI lint verify-only confirm 不另 ADR, 沿用 ADR-020/032); **LL-168** ✅ promote (prompts/risk eval V4-Flash→V4-Pro 决议体例 + CI lint Tier-A-prebuilt verify-only 真值) |
| Reviewer reverse risk | CI lint "verify-only" 误判为 "需重建" scope creep (mitigation: HC-3a 起手 precondition 实测 5 components exist 真值 + verify-only declare); prompts eval 0 round silent skip (LL-098 X10, mitigation: 5 YAML each eval result 强制 cite); V4-Flash→V4-Pro 决议 silent (mitigation: ADR-075 sediment 锁 routing 决议 + 沿用 ADR-036 体例); check_anthropic_imports.py vs check_llm_imports.sh path drift 复发 (mitigation: ADR-031 §6 path 真值 cite sustained) |
| 红线 SOP | sustained HC-1; redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce; 0 .env mutation; 0 真账户 broker call; prompts/risk eval 走 LiteLLM mock OR offline eval (NOT 真 production LLM call burst); 红线 5/5 sustained |
| Paper-mode | sustained HC-1; prompts/risk eval iteration 走 offline eval fixture OR LiteLLM mock, 0 真 production LLM cost burst; CI lint verify 走 read-only 静态分析 path |

### HC-4 — carried deferral 路由 + 5y replay + north_flow/iv wire + ROADMAP sediment + Gate D formal close

| element | content |
|---|---|
| Scope | **(D3) 5y full minute_bars replay**: ~191M rows × 2537 stocks, TB-1 RiskBacktestAdapter.evaluate_at + ADR-070 `_TimingAdapter` side-channel infra 已就绪 (0 changes to closed TB-1 code, sustained ADR-022) → 纯 replay run, long-tail acceptance vs Tier B 2 关键窗口. **(D3) ADR-067 D5 north_flow/iv wire**: `north_flow_cny` + `iv_50etf` MarketIndicators real-data-source wire (TB-2 left DEFERRED — HC-4 wires 真数据源, sustained 铁律 1 先读官方文档确认接口). **(carried) ROADMAP sediment**: `docs/RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` full sediment (Constitution §0.1 line 35 — Tier B closure REACHED, sediment 时机 now due; TB-5c 仅标注 closure 触发, HC-4 创建完整 file — sustained ADR-022 反 silent 创建). **(D2) LiteLLM 3-month cost routing**: Gate D checklist item 5 标注 ⏭ DEFERRED-to-Gate-E (paper-mode 0 live LLM traffic, 3-month wall-clock 不可压缩, sustained ADR-063 paper-mode deferral pattern). **(carried) 2 Gate C sub-item routing**: RAG 命中率 baseline + lesson 后置抽查 ≥1 round → route to Gate E (need live production query traffic). **(closure) Gate D formal close**: Constitution §L10.4 verifier (`sprint-closure-gate-evaluator` subagent + Gate D charter, 借用 charter verify 体例 sustained TB-5c Gate B/C). ADR-076 (横切层 closure cumulative) + Constitution §L10.4 5-checkbox amend + §0.1 ROADMAP closure 标注 + Constitution version bump + skeleton patch + Plan v0.3 doc HC-1~4 closure markers + memory handoff + Plan v0.4 cutover (Gate E) prereq sediment. |
| Acceptance | 5y replay complete + result sediment `docs/audit/v3_hc_4_5y_replay_acceptance_report_YYYY_MM_DD.md` (误报率 / latency P99 / STAGED 闭环 on full 5y period, 沿用 ADR-070 FP classification methodology — daily-dedup + prev_close baseline counterfactual); north_flow_cny/iv_50etf real-data-source wired + verified (接口实测 + MarketIndicators 集成 test); `RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` full sediment (V3 §18.3 reserved scope); Gate D 5/5 checklist 真值落地 (item 1 ✅ HC-1 + item 2 ✅ HC-2 + item 3 ✅ HC-3 + item 4 ✅ HC-3 + item 5 ⏭ DEFERRED-to-Gate-E per D2); Gate D `sprint-closure-gate-evaluator` subagent verify PASS; ADR-076 + Constitution §L10.4 amend + Plan v0.4 prereq sediment; `quantmind-v3-doc-sediment-auto` skill enforce 多 doc 同步 (Plan v0.3 / Constitution §L10.4 amend / REGISTRY / memory handoff); 0 真账户 / 0 broker / 0 .env mutation 红线 5/5 sustained. |
| File delta | ~12-18 files / ~2000-3500 lines (5y replay runner script + result report doc ~400-700 / north_flow/iv MarketIndicators wire + 接口 client + test ~400-700 / RISK_FRAMEWORK_LONG_TERM_ROADMAP.md NEW full file ~300-600 / ADR-076 sediment ~6-10KB / Constitution §L10.4 5-checkbox amend + §0.1 标注 + version history ~100-200 / skeleton §2.3 横切层 chain row closure + version history ~50-100 / Plan v0.3 doc HC-1~4 closure markers ~50-100 / REGISTRY rows ~10-20 / memory handoff append) |
| Chunked sub-PR | **chunked 3 sub-PR**: HC-4a (5y full minute_bars replay run + ADR-070 `_TimingAdapter` 沿用 + north_flow_cny/iv_50etf real-data-source wire + result report doc) → HC-4b (`RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` full sediment + carried deferral 路由 sediment — LiteLLM 3-month + 2 Gate C sub-item → Gate E 标注) → HC-4c (Gate D `sprint-closure-gate-evaluator` subagent verify run + ADR-076 cumulative sediment + Constitution §L10.4 5-checkbox amend + §0.1 ROADMAP closure 标注 + skeleton patch + Plan v0.3 doc closure markers + 横切层 LL append-only review + memory handoff + Plan v0.4 cutover prereq sediment) |
| Cycle | ~1-1.5 周 baseline (HC-4a ~0.5 周 含 5y replay run + HC-4b ~0.3 周 + HC-4c ~0.4 周); replan trigger 1.5x = ~1.5-2.25 周 |
| Dependency | 前置: HC-1 + HC-2 + HC-3 全 ✅ closed (Gate D item 1-4 全 真值落地) / 后置: Plan v0.4 cutover 起手 prereq (Gate E scope: paper-mode 5d + 元监控 0 P0 + Tier A ADR + 5 SLA + 10 user 决议 verify + user 显式 .env paper→live 授权, NOT in Plan v0.3 scope per ADR-064 D4 每 Tier 独立 plan 体例, 留 Plan v0.4) |
| LL/ADR candidate | **ADR-076** ✅ promote (HC-4 横切层 closure cumulative + Gate D formal close + 5y replay long-tail acceptance + north_flow/iv wire + carried deferral 路由 决议 + Plan v0.4 prereq sediment); **LL-169** ✅ promote (横切层 closure 体例 sediment + plan-then-execute 第 5 case 全链 closure 真值落地实证累积扩 sustainability cumulative pattern 体例文档化 6 case cumulative) |
| Reviewer reverse risk | 5y replay 阈值 silent drift (LL-115, mitigation: ADR-076 sediment 锁 阈值 + 沿用 ADR-070 FP classification methodology); 5y replay scope creep 回 12 年 full (ADR-064 D3=b lock sustained, mitigation: 5y = minute_bars 实际覆盖范围 2021-2025, NOT 12 年); Gate D 5 items silent skip (LL-098 X10, mitigation: sprint-closure-gate-evaluator subagent + Gate D charter 5 items 全 verify); Constitution §L10.4 amend silent overwrite (ADR-022, mitigation: 仅 append 标注 + checkbox amend, NOT retroactive content edit); ROADMAP.md silent inflate (ADR-022, mitigation: full sediment 基于 V3 §18.3 reserved scope 真值, NOT 凭空 enumerate); carried deferral silent drop (LL-098 X10, mitigation: HC-4b 路由 sediment 每 deferral 显式 route — Gate E vs done) |
| 红线 SOP | sustained HC-1~3; redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce throughout HC-4; 0 .env mutation; 0 真账户 broker call (5y replay 走 mock broker/notifier/price reader + historical minute_bars); 0 production yaml mutation; Gate D subagent verify 走 read-only path; 红线 5/5 sustained throughout 横切层 closure |
| Paper-mode | sustained HC-1~3; 横切层 closure → cutover prereq (Plan v0.4 起手前 user 显式 trigger sustained LL-098 X10), NOT cutover (cutover 留 Plan v0.4 Gate E scope); 5y replay 走 mock broker/notifier/price reader + historical minute_bars (2021-2025) + ADR-070 `_TimingAdapter` side-channel, 0 真 live production system contact; north_flow/iv wire 走 真数据源 read-only API (沿用 铁律 1 先读官方文档, 0 mutation) |

---

## §B Cross-sprint surface risk register

| # | surface risk | mitigation |
|---|---|---|
| 1 | 失败模式 checklist "12 项" vs V3 §14 表 15 模式 真值差异 (§H Finding #1) | §H Finding #1 决议 enforce 全 15 superset; HC-2a enforcement matrix doc 全 15 row; Constitution §L10.4 item 2 amend 留 HC-4c batch closure 标注 (sustained ADR-022 反 retroactive content edit) |
| 2 | CI lint "verify-only" 误判为重建 scope creep | HC-3a 起手 precondition 实测 5 components exist 真值 + verify-only 显式 declare (sustained 铁律 36 precondition 核); ADR-031 §6 path 决议 cite sustained |
| 3 | 元告警 layer 与 §13.4 dashboard scope creep | D2=defer dashboard (NOT Gate D checklist scope); HC-1 仅 wire alert-on-alert layer (Engine PURE rule + Application service + Beat), 0 frontend |
| 4 | 5y replay scope creep 回 12 年 full | ADR-064 D3=b lock sustained; 5y = minute_bars 实际覆盖 2021-2025 真值 (CLAUDE.md §因子存储 cite: minute_bars 190,885,634 行 5 年 2021-2025); NOT 12 年 |
| 5 | carried deferral silent drop (5 个 deferral 路由不全) | HC-4b 路由 sediment — 每 deferral 显式 route: 5y replay→HC-4a done / north_flow-iv→HC-4a done / ROADMAP→HC-4b done / LiteLLM-3month→Gate E 标注 / RAG 命中率+lesson 抽查→Gate E 标注 |
| 6 | 灾备演练 退化为日历式观察期 | memory feedback_no_observation_periods 反日历式观察期; 灾备演练 = synthetic injection fixture 体例 sustained TB-5a (0 wall-clock wait, instant) |
| 7 | N×N 同步漂移 (Plan v0.3 / Constitution §L10.4 / skeleton §2.3 / REGISTRY / memory handoff 多 doc) | `quantmind-v3-doc-sediment-auto` skill 强制多 doc 同步; sub-PR closure 闭后 sediment SOP; HC-4c batch closure sediment cycle 含多 doc 同步 patch |
| 8 | Constitution §L10.4 amend retroactive content edit | sustained ADR-022 — Constitution §L10.4 amend 仅 checkbox [x] + closure blockquote append, NOT retroactive content 改写; amend 留 HC-4c batch closure 周期 (sustained TB-5c §L10.2/§L10.3 amend 体例) |
| 9 | north_flow/iv 真数据源接口未确认 (铁律 1) | HC-4a 起手 先读 数据源官方文档确认 north_flow_cny (北向资金) + iv_50etf (50ETF 隐含波动率) 接口 — Tushare / akshare / 其他; 0 凭猜测 wire |
| 10 | HC-2 ↔ HC-3 内容可并行但串行 phase transition | 沿用 Plan v0.2 D1=a 串行 phase 干净体例 (sub-task creep 风险 lower); §F (ii) 允许 user 修订为并行 if 时间窗口需要 |
| 11 | sim-to-real gap on 5y replay (PR #210 体例 sustained) | sustained ADR-066 D3 + ADR-070 D6 caveat family — 5y replay synthetic universe-wide Position = 误报率 upper-bound proxy, latency = lower-bound proxy; ADR-076 sediment 显式标注 caveat, NOT silent 假设 production precision |
| 12 | Gate D verifier-as-charter REQUEST_CHANGES pre-sediment (LL-164 体例) | sustained LL-164 — Gate D subagent pre-sediment 可能 flag HC-4c 自身 deliverable (ADR-076 未创建 etc); NOT STOP condition, post-sediment re-run flip PASS |

---

## §C 横切层 closure → cutover trigger STOP gate

**Constitution §L10.4 Gate D 5 项 checklist** (CC 实测每项 via HC-4c `sprint-closure-gate-evaluator` subagent run + Gate D charter):

### Gate D (横切层 closure level, Constitution §L10.4)

1. V3 §13 元监控 `risk_metrics_daily` + alert-on-alert production-active — HC-1 (5 P0 元告警 场景 + channel fallback chain + risk_metrics_daily Tier A S10 已 production-active)
2. V3 §14 失败模式 **15 项** (§H Finding #1: checklist "12 项" 是 stale cite, V3 §14 表真值 15 模式) enforce + 灾备演练 ≥1 round 沉淀 `docs/risk_reflections/disaster_drill/` — HC-2
3. V3 §17.1 CI lint `check_llm_imports.sh` (V3 §17.1 spec cite `check_anthropic_imports.py` 是 pre-ADR-031 path drift 真值) 生效 + pre-push hook 集成 — HC-3 (verify-only, Tier A ADR-020/032 已建)
4. `prompts/risk/*.yaml` prompt eval iteration ≥1 round (V4-Flash → V4-Pro upgrade 决议体例 sediment, ADR-075) — HC-3
5. LiteLLM 月成本 ≤ V3 §16.2 上限 ≥3 month 持续 ≤80% baseline — ⏭ **DEFERRED to Gate E** per D2 (paper-mode 0 live LLM traffic, 3-month wall-clock 不可压缩, sustained ADR-063 paper-mode deferral pattern; Constitution §L10.4 item 5 amend 留 HC-4c batch closure 标注)

### carried deferral 路由 (HC-4b sediment)

| carried deferral | 来源 | Plan v0.3 路由 |
|---|---|---|
| 5y full minute_bars replay | ADR-064 D3=b | ✅ HC-4a done |
| north_flow_cny + iv_50etf real-data-source wire | ADR-067 D5 | ✅ HC-4a done |
| RISK_FRAMEWORK_LONG_TERM_ROADMAP.md full sediment | Constitution §0.1 | ✅ HC-4b done |
| LiteLLM 月成本 ≥3 month ≤80% baseline | Gate D item 5 | ⏭ Gate E (D2, paper-mode 物理不可做) |
| RAG retrieval 命中率 ≥ baseline measurement | Gate C item 3 / ADR-071 D4 | ⏭ Gate E (need live query traffic) |
| lesson→risk_memory 后置抽查 ≥1 live round | Gate C item 5 / ADR-071 D4 | ⏭ Gate E (need live query traffic) |

**STOP gate**: 横切层 closure → HC-4c `sprint-closure-gate-evaluator` subagent (件 5) + Gate D charter 借用 charter verify Gate D 5/5 (item 1-4 ✅ + item 5 ⏭ DEFERRED-to-Gate-E) → STOP + push user (Constitution §L8.1 (c) sprint 收口决议, sustained LL-098 X10 反 silent self-trigger cutover Plan v0.4 起手)

**Plan v0.4 cutover 起手 prereq**: 横切层 closure ✅ + Gate E scope (paper-mode 5d + 元监控 0 P0 + Tier A ADR + 5 SLA + 10 user 决议 verify + user 显式 .env paper→live 授权 4 锁) Plan v0.4 起手前 user 显式 ack (sustained Plan v0.1 §F (vi) plan-then-execute 体例 + ADR-064 D4 每 Tier 独立 plan 体例)

---

## §D 横切层 真测期 SOP

**HC-2 灾备演练 synthetic injection 真测 SOP** (沿用 TB-5a synthetic scenario fixture 体例 + memory feedback_no_observation_periods 反日历式观察期):

- 灾备演练 ≥1 round = pytest fixture/script 注入 failure mode 1-12 trigger condition, instant (0 wall-clock wait)
- 每 mode: 注入 trigger condition → assert 检测 mechanism fire → assert 降级路径 taken → assert 恢复条件 path → assert 元告警 flag (若 wired)
- sediment `docs/risk_reflections/disaster_drill/2026-MM-DD.md`: 每 mode round 结果 + gap finding + enforcement matrix cross-ref

**HC-4 5y replay 真测 SOP** (沿用 ADR-070 TB-5b replay acceptance 体例):

- 5y full minute_bars replay 走 RiskBacktestAdapter.evaluate_at + `_TimingAdapter` side-channel (0 changes to closed TB-1 code, sustained ADR-022)
- FP classification: daily-dedup P0 events to first-per-(code, rule_id, day) + `prev_close`-baseline counterfactual (沿用 ADR-070 D2 — FP if day-end close recovered ≥ prev_close)
- result sediment `docs/audit/v3_hc_4_5y_replay_acceptance_report_YYYY_MM_DD.md`: 误报率 / latency P99 / STAGED 闭环 on full 5y period
- caveat 显式标注 (sustained ADR-066 D3 + ADR-070 D6): synthetic universe-wide Position = 误报率 upper-bound proxy; latency = lower-bound proxy (per-evaluate_at wall-clock, excludes I/O)

**Gate D subagent verify SOP** (沿用 TB-5c Gate B/C verifier-as-charter 体例, LL-164):

- HC-4c spawn `sprint-closure-gate-evaluator` subagent + self-contained Gate D charter (5 item checklist + evidence map)
- pre-sediment verifier 可能 REQUEST_CHANGES flag HC-4c 自身 deliverable (ADR-076 未创建 / Constitution §L10.4 未 amend) — NOT STOP condition (sustained LL-164 core lesson 3), post-sediment re-run flip PASS

---

## §E 横切层 estimated total cycle

per-sprint baseline cite (Plan v0.3 §A HC-1~4 cumulative):

| Sprint | baseline | replan trigger 1.5x | chunked sub-PR |
|---|---|---|---|
| HC-1 | 1-1.5 周 | 1.5-2.25 周 | 3 (HC-1a + HC-1b + HC-1c) |
| HC-2 | 1.5-2 周 | 2.25-3 周 | 3 (HC-2a + HC-2b + HC-2c) |
| HC-3 | 1 周 | 1.5 周 | 2 (HC-3a + HC-3b) |
| HC-4 | 1-1.5 周 | 1.5-2.25 周 | 3 (HC-4a + HC-4b + HC-4c) |

**横切层 total**: ~4.5-6 周 baseline (含 buffer), replan 1.5x = ~7-9 周.

**Baseline 真值漂移 surface** (Constitution §L5.2 5 类漂移 #2 scope 真值漂移, 主动 flag): Plan v0.1 §E + Plan v0.2 §E cite "横切层 Plan v0.3 = ≥12 周" — 本 plan 自底向上估 **~4.5-6 周**, >2x 下修. 原因: Gate D 5 项中 item 1 (risk_metrics_daily) + item 3 (CI lint) 已在 Tier A S10/S-series 实建 (ADR-062 + ADR-020/032), HC-1 仅 wire alert-on-alert layer / HC-3 项 3 = verify-only — 沿用 Tier A "真 net new << 名义" pre-built 真值体例 (Plan v0.2 §E "Tier A 真 net new ~3-5 周, V2 prior cumulative substantially pre-built"). 此漂移 = 正向 (pre-built 减负), NOT 治理债; sediment 于本 §E + §H Finding #2.

**V3 实施期总 cycle 真值再修订** (post Plan v0.3 sediment):

- Tier A 真 net new ~3-5 周 ✅ closed Session 53 cumulative 19 PR (#296-#323)
- Tier B Plan v0.2 = ~8.5-12 周 baseline ✅ closed Session 53+24 cumulative ~23 chunked sub-PR (#325-#349)
- 横切层 Plan v0.3 = ~4.5-6 周 baseline (本 plan 真值修订, vs Plan v0.1/v0.2 cite "≥12 周")
- cutover Plan v0.4 = 1 周
- **真值 estimate (post Plan v0.3 sediment)**: Tier A ~3-5 + Tier B ~8.5-12 + 横切层 ~4.5-6 + cutover 1 = **~17-24 周** (~4-6 月), vs Plan v0.2 §E cite "~25-30 周" — 下修 ~8 周 (横切层 ≥12 → ~4.5-6 真值修订)
- replan trigger 1.5x = ~25-36 周 (~6-9 月)

**replan trigger condition** (Constitution §L0.4): 任 sprint 实际超 baseline 1.5x → STOP + push user (sprint 收口决议) + `quantmind-v3-sprint-replan` skill (件 3) trigger; replan template = 治理债 surface + sub-task creep cite + remaining stage timeline 修订

---

## §F Plan review trigger SOP (sustained, post Plan v0.3 user approve)

**Plan output → STOP + 反问 user** (反 silent self-trigger HC-1, sustained LL-098 X10 + Constitution §L8.1 (a) 关键 scope 决议, sustained Plan v0.1/v0.2 §F 体例):

**user options**:

- **(i)** approve plan as-is → HC-1 起手 (CC exit plan mode → sprint 实施 cycle, Constitution §L0.3 5 step verify + V3_LAUNCH_PROMPT §3.1 SOP)
- **(ii)** sprint 顺序修订 (e.g. HC-2 / HC-3 并行 / HC-3 提前 HC-2)
- **(iii)** scope 拆分 (e.g. HC-2 chunked 进一步拆 (3 → 4) / HC-4 chunked 进一步拆 (3 → 4))
- **(iv)** chunked sub-PR 体例修订 (sustained LL-100 + Tier B sub-PR 体例)
- **(v)** skip 某 sprint (e.g. HC-3 项 3 CI lint verify-only 可并入 HC-4)
- **(vi)** 其他修订 — ✅ accepted, plan-then-execute 体例 sub-PR sediment cycle (本文件 sediment)

**user 显式 trigger HC-1 起手** → CC exit plan mode → sprint 实施 cycle (sustained per-sprint cycle 体例)

---

## §G 主动思考 (sustained LL-103 SOP-4 反 silent agreeing)

### (I) 3 决议 lock sediment 反思

**D1=4-sprint HC-1~4 lock**:

- ✅ Gate D 5 项 自然 cluster 成 4 sprint: item 1 → HC-1 (元监控 alert-on-alert 独立 layer) / item 2 → HC-2 (失败模式 enforce + 灾备演练, 最大 net new) / item 3+4 → HC-3 (CI lint verify-only + prompts eval, 体量轻 合并) / item 5 + carried deferral + closure → HC-4
- ✅ 每 sprint chunked 2-3 sub-PR, 沿用 LL-100 chunked SOP + Tier B sub-PR 体例 (TB-1~5 全 chunked 2-4 sub-PR 实证)
- ⚠️ trade-off: HC-3 体量轻 (~1 周) — 可并入 HC-4, 但保持独立 sprint 让 Gate D item 3+4 closure 干净 (sub-task creep 风险 lower); §F (v) 允许 user 修订

**D2=both DEFER lock** (LiteLLM 3-month cost + §13.4 dashboard):

- ✅ LiteLLM 月成本 ≥3 month ≤80% baseline = inherently wall-clock (paper-mode 0 live LLM traffic, 3-month 自然累积不可压缩) → Gate E 自然累积 sustained ADR-063 paper-mode deferral pattern; honest scope handling, NOT silent skip
- ✅ §13.4 监控 dashboard NOT in Gate D checklist (checklist item 1 仅要求 risk_metrics_daily + alert-on-alert production-active, dashboard 是 §13.4 独立 frontend 设计) → 留独立 frontend track, 反 scope creep 误入横切层
- ⚠️ trade-off: dashboard 不在 横切层 → 横切层 closure 后风控仍无可视化面板; accept — dashboard 是 frontend track 独立交付, 不阻 Gate D closure

**D3=both into HC-4 lock** (5y replay + north_flow/iv wire):

- ✅ 5y full replay — TB-1 RiskBacktestAdapter + ADR-070 `_TimingAdapter` infra 已就绪, 纯 replay run (0 新 evaluator code), 清掉 ADR-064 D3=b carried deferral
- ✅ north_flow/iv wire — ADR-067 D5 TB-2 left DEFERRED, HC-4 wire 真数据源, 清掉 carried deferral backlog
- ⚠️ trade-off: 5y replay ~191M rows wall-clock run time (TB-1c 2 关键窗口 ~3.32M+0.96M bars; 5y ~191M ≈ 40x) — accept, HC-4a cycle 含此 run time buffer (~0.5 周)

### (II) CC-domain push back

**Push back #1 — Gate D checklist "12 项" vs V3 §14 表 15 模式 真值差异** (§H Finding #1 详): Constitution §L10.4 item 2 + §0.1 footer cite "失败模式 12 项", V3 §14 表真值 enumerate 15 模式 (mode 13 BGE-M3 OOM / mode 14 RiskReflector V4-Pro 失败 / mode 15 LIVE_TRADING_DISABLED 双锁失效 是 V3 §14 表演进新增, checklist "12 项" 是 stale cite). 决议: HC-2 enforce 全 15 superset (反 silent skip mode 13/14/15). Constitution §L10.4 item 2 amend 留 HC-4c batch closure 标注 (sustained ADR-022 仅 append 标注).

**Push back #2 — 横切层 baseline "≥12 周" vs 自底向上 ~4.5-6 周 真值漂移** (§E surface 详): Plan v0.1/v0.2 §E cite "横切层 ≥12 周" — 自底向上 HC-1~4 估 ~4.5-6 周. 原因: Gate D item 1 (risk_metrics_daily) + item 3 (CI lint) 已在 Tier A 实建. 决议: §E sediment 真值漂移 + V3 实施期总 cycle 真值再修订 (~25-30 → ~17-24 周). 正向漂移 (pre-built 减负), NOT 治理债.

**Push back #3 — 灾备演练 "每月 1 次" wall-clock vs synthetic injection**: V3 §14.1 cite "每月 1 次, 模拟 failure mode 1-12". 真值: memory feedback_no_observation_periods 反日历式观察期 (Session 42-43 两次挑战). 决议: HC-2 灾备演练 = synthetic injection fixture 体例 (沿用 TB-5a, instant, 0 wall-clock wait), ≥1 round 覆盖 mode 1-12. NOT 月度 wall-clock drill.

### (III) Long-term + 二阶 / 三阶 反思

- plan-then-execute 体例 sustainability cumulative 第 5 case (case 1 Plan v0.1 5-09 + case 2 sub-PR 11b + case 3 sub-PR 13 + case 4 Plan v0.2 5-13 + case 5 本 Plan v0.3 5-14)
- 横切层 4 sprint baseline ~4.5-6 周 + replan 1.5x = ~7-9 周 reasonable scope
- V3 实施期总 cycle ~17-24 周 真值落地 sustainability — Tier A ~3-5 + Tier B ~8.5-12 + 横切层 ~4.5-6 + cutover 1
- 二阶: Gate D closure 后 → Plan v0.4 cutover (Gate E) 是 V3 实施期最后一个 Tier-level plan, paper→live cutover gate
- 三阶: 横切层 = "监控风控系统自身 + 失败模式兜底 + CI 边界" — closure 后 V3 风控系统具备 production 自我观测 + 灾备 + 边界 enforcement 能力, 是 cutover 的安全前提

### (IV) Governance/SOP/LL/ADR candidate sediment

- **ADR-072** (本 sub-PR): Plan v0.3 3 决议 lock (D1=4-sprint / D2=both-DEFER / D3=both-into-HC-4)
- **ADR-073~076** reserved (HC-1~4 closure ADR)
- **LL-165** (本 sub-PR): 横切层 plan-then-execute 体例 第 5 case + Gate D 5-item state assessment 体例 (Tier A pre-built 真值识别 → baseline 真值修订)
- **LL-166~169** reserved (HC-1~4 closure LL)

---

## §H Phase 0 active discovery findings (sustained LL-115 enforce + Constitution §L5.3)

### Finding #1: "和我假设不同" — Gate D checklist "失败模式 12 项" vs V3 §14 表 15 模式 ✅ sediment

**discovery**: Constitution §L10.4 item 2 + §0.1 footer cite "V3 §14 失败模式 12 项", 但 V3 §14 表 (line 1445-1461) enumerate **15 模式** — mode 1-12 + mode 13 (BGE-M3 OOM) + mode 14 (RiskReflector V4-Pro 失败) + mode 15 (LIVE_TRADING_DISABLED 双锁失效). mode 13/14/15 是 V3 §14 表演进新增 (BGE-M3 / RiskReflector / 双锁 是 Tier B + 横切层 期相关), checklist "12 项" 是 stale cite (V3 §14 表演进前).

**Drift type**: scope 真值漂移 (Constitution §L5.2 5 类漂移 #2).

**决议**: HC-2 enforce 全 15 superset (反 silent skip mode 13/14/15 — mode 15 LIVE_TRADING_DISABLED 双锁失效 尤其 critical, 是红线 enforcement). Constitution §L10.4 item 2 + §0.1 footer cite amend 留 HC-4c batch closure 标注 "12 项 → 15 模式 per V3 §14 表真值" (sustained ADR-022 反 retroactive content edit, 仅 append 标注).

### Finding #2: "prompt 让做但有更好做法" — 横切层 baseline "≥12 周" 真值漂移 ✅ sediment

**discovery**: Plan v0.1/v0.2 §E cite "横切层 Plan v0.3 = ≥12 周". 自底向上 HC-1~4 估 ~4.5-6 周 (>2x 下修). 原因: Gate D item 1 (risk_metrics_daily + daily_aggregator + Beat) 已在 Tier A S10 实建 (ADR-062), item 3 (CI lint check_llm_imports.sh + pre-push + governance test) 已在 Tier A 实建 (ADR-020/032) — HC-1 仅 wire alert-on-alert layer / HC-3 项 3 = verify-only.

**Drift type**: scope 真值漂移 (#2) + 正向 (pre-built 减负, NOT 治理债).

**决议**: §E sediment 真值漂移 + V3 实施期总 cycle 真值再修订 (~25-30 → ~17-24 周). 沿用 Tier A "真 net new << 名义, V2 prior cumulative substantially pre-built" 体例.

### Finding #3: "prompt 让做但顺序/方法" — 灾备演练 wall-clock vs synthetic injection ✅ sediment

**discovery**: V3 §14.1 cite "灾备演练 每月 1 次, 模拟 failure mode 1-12". 月度 wall-clock drill = 日历式观察期 anti-pattern (memory feedback_no_observation_periods, Session 42-43 两次 user 挑战).

**Drift type**: 方法漂移 (sustained TB-5a synthetic scenario 体例 + Plan v0.2 替代 日历式观察期 体例).

**决议**: HC-2 灾备演练 = synthetic injection fixture 体例 (沿用 TB-5a, instant, 0 wall-clock wait), ≥1 round 覆盖 mode 1-12. V3 §14.1 "每月 1 次" cite NOT amend (设计层保留 production cadence 建议), 但 Gate D closure 验收走 synthetic injection ≥1 round (HC-2c sediment 显式 declare 方法).

---

## §I Sub-PR (Plan v0.3 sediment) cycle (本文件 sediment trigger)

Sub-PR (Plan v0.3 sediment) cycle = post Plan v0.3 user approve (D1=4-sprint / D2=both-DEFER / D3=both-into-HC-4) → CC 实施 → ~7 file delta atomic sediment (docs-only 直 push per 铁律 42, sustained Plan v0.2 sub-PR sediment 体例):

| # | file | scope | line delta |
|---|---|---|---|
| 1 | `docs/V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md` (本文件) | NEW file, content = Plan v0.3 inline 完整 (post 3 决议 lock + 主动思考 sediment + Phase 0 active discovery + sub-PR cycle 沉淀) | NEW file ~30-40KB |
| 2 | [docs/V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) | header v0.10 → v0.11 + §0.1 横切层 sprint plan row 加 (sustained Tier A/B plan row 体例) + version history v0.11 entry append (NOT amend §L10.4 — §L10.4 amend 留 HC-4c batch closure 周期) | edit + append |
| 3 | [docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md](V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md) | header version bump + §2.3 NEW 横切层 sprint chain (HC-1~4) row 体例 (sustained §2.1 Tier A + §2.2 Tier B sprint chain row 体例) + version history entry append | edit + append |
| 4 | [docs/adr/REGISTRY.md](adr/REGISTRY.md) | ADR-072 NEW row (Plan v0.3 3 决议 lock + 横切层 sprint chain plan sediment) + ADR-073~076 reserved row cumulative sediment + status counts update | edit + append |
| 5 | `docs/adr/ADR-072-v3-crosscutting-plan-v0-3-3-decisions-lock.md` | NEW file, content = 3 决议 (D1=4-sprint / D2=both-DEFER / D3=both-into-HC-4) lock rationale + cumulative cite (Plan v0.3 §A acceptance + §G I sediment + §H Finding) | NEW file ~5-8KB |
| 6 | [LESSONS_LEARNED.md](../LESSONS_LEARNED.md) | LL-165 append (横切层 plan-then-execute 体例 第 5 case sediment + Gate D 5-item state assessment 体例 + Tier A pre-built 真值识别 → baseline 真值修订) | append |
| 7 | `memory/project_sprint_state.md` | Session 53+25 handoff 顶部 update (Plan v0.3 user approved + 3 决议 lock + HC-1 起手 prereq + cumulative cite Plan v0.2 sub-PR sediment 体例) | edit + append |

Sub-PR (Plan v0.3 sediment) closure → 横切层 HC-1 sprint 起手 prerequisite 全 satisfied (post-Plan v0.3 3 决议 lock 真值落地) → §F (vi) plan review trigger SOP STOP gate before HC-1 起手 sustained (LL-098 X10).

---

## maintenance + footer

### 修订机制 (沿用 ADR-022 集中机制)

- 新 横切层 sprint sediment / 新 user 决议 / 新 V3 设计扩展 → 1 sediment cycle + Plan v0.3 同步 update + 自造 skill / hook / subagent 同步 update
- LL append-only (反 silent overwrite, sustained ADR-022)
- ADR # registry SSOT (LL-105 SOP-6) sub-PR 起手前 fresh verify
- Plan v0.3 fresh read SOP (本文件 §H + sustained Constitution §L1.1 fresh read SOP)
- Constitution §L10.4 amend (item 2 "12 项 → 15 模式" per §H Finding #1 + item 5 "⏭ DEFERRED-to-Gate-E" per D2) 留 HC-4c sediment 周期 batch closure pattern (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例)

### 版本 history

- **v0.1 (initial draft, 2026-05-14)**: Plan v0.3 横切层 sprint chain (HC-1 + HC-2 + HC-3 + HC-4, 4 sprint) + 3 决议 lock (D1=4-sprint HC-1~4 / D2=both-DEFER LiteLLM-3month + dashboard / D3=both-into-HC-4 5y-replay + north_flow/iv) + cycle baseline ~4.5-6 周 + cross-sprint risk register 12 项 + Gate D 5 项 criteria + carried deferral 6 项路由表 + 横切层 真测期 SOP (灾备演练 synthetic injection + 5y replay + Gate D verifier-as-charter) + plan review trigger SOP + Phase 0 active discovery 3 Finding (失败模式 15 vs 12 真值 / baseline ≥12 → ~4.5-6 周 真值修订 / 灾备演练 synthetic vs wall-clock). 沿用 Plan v0.2 sub-PR sediment 体例 (post-Tier B FULLY CLOSED cumulative Session 53+24 + ADR-071 sediment 真值落地 plan-then-execute 体例 第 5 case 实证累积扩 sustainability cumulative pattern 体例文档化).

---

## §J Cumulative cite footer (Plan v0.3 sediment, sustained Plan v0.1/v0.2 体例 + Constitution §L10 footer 体例)

**Plan v0.3 sub-PR sediment cumulative cite**:

- **plan-then-execute 体例 sustainability cumulative scope**: case 1 Plan v0.1 5-09 + case 2 sub-PR 11b 5-09 + case 3 sub-PR 13 5-09 + case 4 Plan v0.2 5-13 + case 5 本 Plan v0.3 5-14 (横切层 context) cumulative pattern 体例文档化 5 case 实证累积扩 sustainability sustained
- **3 决议 lock 体例 cumulative**: D1=4-sprint / D2=both-DEFER / D3=both-into-HC-4 3 项决议 lock via Plan v0.3 §G I sediment + ADR-072 sediment 锁 + LL-165 promote 本 sub-PR sediment cumulative (沿用 ADR-064 Plan v0.2 5-决议-lock 体例)
- **横切层 期 ADR sediment cumulative**: ADR-072 (本 sub-PR) + ADR-073 (HC-1 元监控 alert-on-alert closure) + ADR-074 (HC-2 失败模式 enforce + 灾备演练 closure) + ADR-075 (HC-3 prompts/risk eval iteration closure) + ADR-076 (HC-4 横切层 closure cumulative + Gate D formal close) — 5 项 横切层 ADR cumulative sediment
- **横切层 期 LL sediment cumulative**: LL-165 (本 sub-PR) + LL-166 (HC-1 元告警 5 P0 场景 synthetic injection 实测) + LL-167 (HC-2 失败模式 15 vs 12 真值差异 + 灾备演练 synthetic 体例) + LL-168 (HC-3 prompts/risk eval V4-Flash→V4-Pro 决议体例) + LL-169 (HC-4 横切层 closure 体例 sediment) — 5 项 横切层 LL cumulative sediment
- **Constitution amend pending HC-4c batch closure**: §L10.4 item 2 "12 项 → 15 模式" amend per §H Finding #1 + item 5 "⏭ DEFERRED-to-Gate-E" amend per D2 + §0.1 ROADMAP closure 标注 (sustained ADR-022 反 retroactive content edit, 仅 append 标注体例 留 HC-4c sediment 周期 batch closure pattern)
- **5/5 红线 sustained throughout Plan v0.3**: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 (sustained Plan v0.1/v0.2 §J cumulative cite 体例 + redline_pretool_block hook + quantmind-redline-guardian subagent 双层 enforce throughout Plan v0.3 sediment cycle)
