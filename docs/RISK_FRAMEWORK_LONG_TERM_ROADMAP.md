# QuantMind V3 风控框架长期路线图 (12 月)

> **配合** [`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) — V3 §18.3 reserved scope.
> **本 file 定位**: V3 设计文档 §19 Roadmap (12 月) 标准化为独立 file + re-anchor 到当前真值 + carried deferral 路由 sediment。
> **创建**: 2026-05-15 (V3 横切层 Plan v0.3 §A **HC-4b**, sub-PR 第 2/3)。
> **sediment 触发**: Tier B closure REACHED (ADR-071, Gate B 5/5 + Gate C 6/6 ✅) → Constitution §0.1 (长期 Roadmap 行) "sediment 时机 now due"。TB-5c 仅标注 closure 触发, 完整 file 创建留 Plan v0.3 横切层 scope (sustained ADR-022 反 silent 创建)。
> **维护体例**: append-only 版本历史 (沿用 ADR-022)。本 file 是 forward-looking roadmap, NOT 进度日志 — 进度真值 SSOT 在 memory `project_sprint_state.md` + `docs/adr/REGISTRY.md`。

---

## §1 文档定位

| 维度 | 说明 |
|---|---|
| **是什么** | V3 风控框架从「设计完成」到「live 实战 + V4 演进」的 12 月 forward roadmap |
| **不是什么** | NOT 设计文档 (设计 SSOT = V3_DESIGN) / NOT 进度日志 (进度 SSOT = memory sprint_state + ADR REGISTRY) / NOT sprint plan (sprint SSOT = Tier A/B/横切层 3 个 SPRINT_PLAN doc) |
| **更新触发** | 每 Gate (D/E) closure 后 re-anchor 时序 + carried deferral 路由变更时 + V4 候选决议时 |
| **关联 SSOT** | V3_DESIGN §19 (时序 source) + §20.4 (V4 候选 source) + Constitution §L10 (5 Gate) + 3 个 SPRINT_PLAN (Tier A / Tier B / 横切层) |

V3_DESIGN §19 是本 roadmap 的内容母体, 但 §19 写于 v1.0 (2026-05-01), 其 §19.1 时序表是 **projection at design time**。本 file §3 用 **2026-05-15 真值** re-anchor (见 §2 快照 + §3 Finding 标注)。V3_DESIGN §19 本身不在 HC-4b scope 内改动 (design doc edit, sustained ADR-022 — 仅本 standalone file re-anchor, 设计 doc §19 保留 design-time projection 作历史)。

---

## §2 当前真值快照 (2026-05-15)

> cite source: memory `project_sprint_state.md` frontmatter (Session 53+32) + `docs/adr/REGISTRY.md` + Constitution §0.1 + 3 个 SPRINT_PLAN closure 标注 — 起手 fresh verify 2026-05-15 ✅。

| 层 / 阶段 | 状态 | 真值锚点 |
|---|---|---|
| **Tier A** (S1+S2+S2.5+S3-S11, 12 sprint) | ✅ code-side 12/12 closed | Constitution §0.1 — Session 53 cumulative 19 PR #296-#323 |
| **T1.5** (backtest_adapter formal close) | ✅ closed | Tier B Plan v0.2 起手 (ADR-064 期) |
| **Tier B** (T1.5+TB-1~5, 6 sprint) | ✅ FULLY CLOSED 2026-05-14 | ADR-071 — Gate B 5/5 + Gate C 6/6 ✅ |
| **横切层 HC-1** (元监控 alert-on-alert) | ✅ closed | ADR-073 |
| **横切层 HC-2** (失败模式 15 项 enforce + 灾备演练) | ✅ closed | ADR-074 |
| **横切层 HC-3** (CI lint verify + prompts/risk eval) | ✅ closed | ADR-075 |
| **横切层 HC-4a** (5y replay + north_flow/iv verify) | ✅ closed | PR #360 `3d508ca` — 5y replay ✅ PASS 全 4 项 V3 §15.4 |
| **横切层 HC-4b** (本 file + carried deferral 路由) | ⏳ 进行中 | 本 sub-PR |
| **横切层 HC-4c** (Gate D formal close + ADR-076) | ⏳ 待 | Plan v0.3 §A HC-4c |
| **Gate D** (横切层 closure, Constitution §L10.4) | ⏳ items 1-4 ✅ / item 5 ⏭ Gate E | HC-1~3 满足 item 1-4; item 5 LiteLLM 3-month → Gate E |
| **Gate E** (PT cutover, Plan v0.4) | ⏳ 未起手 | 横切层 closure 后 user 显式 trigger (LL-098 X10) |

**关键真值**: 截至 2026-05-15, V3 设计层 5+1 层 + Tier A/B 全部 code-side 闭环, 横切层 3.25/4 sprint closed。项目进度 **超前 V3_DESIGN §19.1 的 design-time projection** (§19.1 projection: "Q2 = Tier A / Q3 = Tier B" — 实际 Q2 上半即 Tier A+B+横切层大部完成)。

---

## §3 12 月时序 (re-anchored to 2026-05-15 真值)

> **Finding (HC-4b Phase 0, type a — stale cite)**: V3_DESIGN §19.1 时序表写于 2026-05-01 v1.0, projection "2026 Q2 Tier A / Q3 Tier B+T1.5 / Q4 PT 重启 / 2027 Q1+ V4"。2026-05-15 真值: Tier A + Tier B + T1.5 + 横切层 HC-1~3 + HC-4a 全 closed — 实际进度超前 §19.1 projection 约 1 quarter。本 §3 用真值 re-anchor; §19.1 design-time projection 保留在 V3_DESIGN 作历史 (不 retroactive 改, sustained ADR-022)。

### §3.1 已完成 — 2026 Q2 上半 (超前 §19 projection)

| 交付 | 状态 |
|---|---|
| LiteLLM Router + L0 多源数据 + L1 实时化 + L3 动态阈值 + L4 STAGED + L5 Reflector | ✅ Tier A 12 sprint code-side closed |
| L2 Bull/Bear regime + L2 Risk Memory RAG + backtest_adapter (回测引入风控, 纯函数) | ✅ Tier B 6 sprint closed |
| 元监控 alert-on-alert + 失败模式 15 项 enforce + 灾备演练 + CI lint + prompts/risk eval | ✅ 横切层 HC-1~3 closed |
| 5y full minute_bars replay long-tail acceptance (139.3M bars, ✅ PASS 4/4 §15.4) | ✅ HC-4a closed |

### §3.2 近期 — Gate D formal close + Gate E PT cutover critical path

| 阶段 | scope | gate |
|---|---|---|
| **HC-4b** (本 file) | RISK_FRAMEWORK_LONG_TERM_ROADMAP.md full sediment + carried deferral 路由 sediment | — |
| **HC-4c** | Gate D `sprint-closure-gate-evaluator` subagent verify + ADR-076 cumulative sediment + Constitution §L10.4 5-checkbox amend (含 item 2 "12 项→15 项" 真值订正 + item 3 `check_anthropic_imports.py`→`check_llm_imports.sh` path drift 订正 — sustained Plan v0.3 §B 风险 #1) + §0.1 ROADMAP closure 标注 + skeleton patch + Plan v0.3 closure markers + memory handoff + Plan v0.4 cutover prereq sediment | **Gate D** (Constitution §L10.4) |
| **Plan v0.4 (Gate E) 起手** | PT cutover plan — paper-mode 5d dry-run + 元监控 0 P0 + 5 SLA 满足 + user 显式 .env paper→live 授权 + LIVE_TRADING_DISABLED true→false 解锁 | **Gate E** (Constitution §L10.5) |

> **STOP gate** (sustained Plan v0.3 §C + LL-098 X10): 横切层 closure (HC-4c Gate D verify) 后 **NOT silent self-trigger** Plan v0.4 起手 — 必 user 显式 trigger。cutover 是真账户解锁动作, 必走 Constitution §L8.1 (c) sprint 收口决议 user 介入。

### §3.3 2026 Q3 (8-10 月) — live 实战调优

- paper→live cutover 完成后 live 实战观察 (沿用 PT 重启 gate prerequisite, SHUTDOWN_NOTICE_2026_04_30 §9)
- L5 RiskReflector 实战反思闭环首轮 (lesson→risk_memory→下次决策, V3_DESIGN §8.3 闭环核心)
- carried deferral Gate E 项 measurement: LiteLLM 月成本真实数据 (≥3 month 累积) + RAG retrieval 命中率 baseline + lesson 后置抽查 ≥1 live round (见 §4)
- T1.6 阈值扫参: 基于 Tier A/B 实施后参数 + L5 反思候选 (V3_DESIGN §19.3)

### §3.4 2026 Q4 (11-1 月) — 实战反思 + V4 评估前置

- L5 实战反思数据累积 (周报 / 月报 / 事件后 reflection, V3_DESIGN §18.3 `docs/risk_reflections/`)
- V3 实战数据 → V4 候选评估输入 (见 §7)
- LiteLLM 月成本 ≥3 month 持续数据 → Gate D item 5 真值落地 (若 cutover 在 Q3 完成)

### §3.5 2027 Q1+ — V4 评估

- 基于 V3 实战数据 + 新借鉴源研究 (RD-Agent Wave 3 末评估, ADR-013)
- V4 候选长期开放问题决议 (见 §7) — 实战数据驱动, NOT 设计阶段预判

---

## §4 carried deferral 路由 (HC-4b sediment)

> Plan v0.3 §C carried-deferral 路由表的独立 sediment (Plan §C = 横切层 closure → cutover trigger STOP gate 节, 内含 "carried deferral 路由 (HC-4b sediment)" 表)。每 deferral 显式 route (sustained Plan v0.3 §B 风险 #5 反 carried deferral silent drop)。本表与 Plan v0.3 §C 表保持同步 — Plan §C 是 SSOT, 本表是 ROADMAP 视角的 mirror。

| carried deferral | 来源 | 路由 | 状态 |
|---|---|---|---|
| 5y full minute_bars replay | ADR-064 D3=b | HC-4a | ✅ done (PR #360, ✅ PASS 4/4 §15.4) |
| north_flow_cny + iv_50etf real-data-source wire | ADR-067 D5 | HC-4a (verify, 实际 TB-2e #338 已 wire) | ✅ done (production-active verified) |
| RISK_FRAMEWORK_LONG_TERM_ROADMAP.md full sediment | Constitution §0.1 | HC-4b | ✅ done (本 file) |
| LiteLLM 月成本 ≥3 month ≤80% baseline | Gate D item 5 | ⏭ **Gate E** | DEFERRED — paper-mode 0 live LLM traffic, 3-month wall-clock 不可压缩 (D2, sustained ADR-063 paper-mode deferral pattern) |
| RAG retrieval 命中率 ≥ baseline measurement | Gate C item 3 / ADR-071 D4 | ⏭ **Gate E** | DEFERRED — need live production query traffic |
| lesson→risk_memory 后置抽查 ≥1 live round | Gate C item 5 / ADR-071 D4 | ⏭ **Gate E** | DEFERRED — need live production query traffic |

**路由总结**: 6 carried deferral — 3 项 (5y replay / north_flow-iv / ROADMAP) 在 HC-4a+HC-4b 清掉; 3 项 (LiteLLM 3-month / RAG 命中率 / lesson 抽查) 物理上需 live traffic, route to Gate E (Plan v0.4 cutover 后才有 live LLM/query traffic — paper-mode 无法等价模拟 wall-clock-bound + traffic-bound 的 measurement)。

> **Finding (HC-4b Phase 0, type a — minor cite inconsistency, 不 action)**: ADR-072 (Plan v0.3 3 决议 lock) + Plan §B 风险 #5 cite "5 carried deferral" (RAG 命中率 + lesson 后置抽查 合并计 1); Plan §C 表 + 本 §4 表拆为 6 row。两者内部一致, 仅 granularity 差异 — 6-row 拆分更精确, 不需 amend。

---

## §5 PT 重启 critical path (Gate E prerequisite)

> 沿用 V3_DESIGN §19.2 + SHUTDOWN_NOTICE_2026_04_30 §9 PT 重启 gate prerequisite。re-anchor 到 2026-05-15 真值。

| prerequisite | 状态 |
|---|---|
| T0-11 (F-D3A-1) closed | ✅ PR #170 |
| T0-15/16/18/19 closed | ✅ (sprint period) |
| Tier A Sprint 1-11 完成 | ✅ code-side 12/12 closed |
| Tier B + 横切层 closed | ⏳ Tier B ✅ / 横切层 3.25/4 (HC-4b+HC-4c 待) |
| Gate D formal close (Constitution §L10.4) | ⏳ HC-4c |
| paper-mode 5d dry-run 验收 | ⏳ Plan v0.4 (Gate E) |
| 元监控 0 P0 + 5 SLA 满足 | ⏳ Plan v0.4 (Gate E) |
| DB stale snapshot 清理 (4-28 遗留) | ⏳ 运维层, Plan v0.4 |
| **user 显式 .env paper→live 授权** | ⏳ Gate E — user 介入硬门 (Constitution §L10.5) |
| **LIVE_TRADING_DISABLED=true → false 解锁** | ⏳ Gate E — 红线解锁, user 显式 push |

**红线现状 (sustained 2026-04-30 user 决议清仓)**: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102。cutover 前全程 sustained。

---

## §6 与其他主线集成

> 沿用 V3_DESIGN §19.3。

| 主线 | 集成点 |
|---|---|
| **T1.6 阈值扫参** (Q3-Q4) | 基于 Tier A/B 实施后参数 + L5 反思候选输入 |
| **Wave 4 MVP 4.1 Observability** | 监控基础设施复用 (元监控 alert-on-alert layer 已 HC-1 wire) |
| **RD-Agent Re-evaluation** (ADR-013) | Wave 3 末评估, 不影响 V3; V4 评估期 (2027 Q1+) 重新纳入考量 |
| **legacy 因子主线** (CORE3+dv_ttm WF) | V3 风控是 execution/risk 层, 与因子 alpha 层正交 — 风控不改因子选股逻辑 |

---

## §7 V4 候选长期开放问题

> V3_DESIGN §20.4 长期开放问题 (V4 候选) 的 expand。**全部 V3 实战数据驱动 — NOT 设计阶段预判, NOT 自动推进** (沿用 LL-098 X10 反 forward-progress + V3_DESIGN §0.4 完整性 vs 简洁性原则)。

| # | V4 候选 | 决议依赖 | 借鉴源 |
|---|---|---|---|
| 1 | L2 Bull/Bear 2-Agent → 7-Agent 扩展 | V3 实战 regime detection 准确率数据 | QuantDinger 全实施体例 |
| 2 | L5 RiskReflector → multi-agent reflection 升级 | V3 实战反思 lesson 质量数据 | TradingAgents 5 Agent debate |
| 3 | RAG embedding → financial-domain finetune model (FinBERT 类) | V3 实战 retrieval 命中率 (Gate E measurement) | — |
| 4 | 多渠道推送 (DingTalk + Slack + 企微 + 短信) | V3 实战 DingTalk 故障率 | — |

**V4 启动 gate**: V4 评估期 (2027 Q1+) 起手前必 user 显式 trigger + V3 实战数据 ≥1 quarter 累积。0 候选自动 promote — 每项必走 ADR sediment + user 决议 (沿用 ADR-022 集中机制 + Constitution §L8.1 user 介入)。

---

## §8 文档元数据

**版本历史** (append-only, 沿用 ADR-022):

- **v1.0 (2026-05-15)**: 初稿创建 (V3 横切层 Plan v0.3 §A HC-4b)。V3_DESIGN §19 Roadmap 标准化为独立 file + re-anchor 到 2026-05-15 真值 (Finding: §19.1 design-time projection stale, 项目超前约 1 quarter) + carried deferral 6 项路由 sediment (3 done / 3 → Gate E) + PT 重启 critical path re-anchor + V4 候选 4 项 expand。sediment 触发 = Tier B closure REACHED (ADR-071) + Constitution §0.1 (长期 Roadmap 行)。

**关联**:
- 母体设计: [`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §19 + §20.4
- Constitution: [`docs/V3_IMPLEMENTATION_CONSTITUTION.md`](V3_IMPLEMENTATION_CONSTITUTION.md) §0.1 (长期 Roadmap 行) + §L10 (5 Gate)
- sprint plan: `docs/V3_TIER_A_SPRINT_PLAN_v0.1.md` + `docs/V3_TIER_B_SPRINT_PLAN_v0.1.md` + [`docs/V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md`](V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md) §A HC-4 + §C (carried deferral 路由)
- ADR: ADR-022 (反 silent 创建 + append-only) / ADR-063 (paper-mode deferral pattern) / ADR-064 D3=b (5y replay) / ADR-067 D5 (north_flow/iv) / ADR-071 (Tier B closure) / ADR-072 (Plan v0.3 3 决议 lock) / ADR-076 (HC-4 横切层 closure, HC-4c sediment)
- LL: LL-098 X10 (反 forward-progress default)
- 进度真值 SSOT: memory `project_sprint_state.md` + `docs/adr/REGISTRY.md`

**铁律**: 22 (文档跟随代码) / 38 (Blueprint 唯一长期架构记忆 — 本 file 是 V3 风控的 12 月 roadmap, 不替代 QPB)
