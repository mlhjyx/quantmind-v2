# QuantMind Project Navigation

> **本文件 = QuantMind V2 项目级 top-down navigation hub** — "我想做 X → 看哪个 doc" 的 random-access 入口表.
>
> **scope**: 当前真值快照 + task → doc 锚点表 + 前端主权交接路线 + 红线 + 维护体例. **0 inline 重复 SSOT 内容** (沿用 Constitution §0.1 reference-only 体例).
>
> **not scope**: 设计内容 (走 V3_DESIGN / DEV_*.md) / sprint plan (走 V3_TIER_A/B/CROSSCUTTING_SPRINT_PLAN) / 进度日志 (走 memory `project_sprint_state.md` + ADR REGISTRY) / 30 min onboard playbook (走 ONBOARDING.md) / session 起手 SOP (走 SESSION_PROTOCOL.md).
>
> **本文件版本**: v0.1 (initial draft, 2026-05-22)
> **创建动机**: 50+ docs/ 文件已存在但缺单一 task-oriented navigation 入口 — N×N 同步漂移实证 (e.g. API_COVERAGE.md 5-20 已生成 738 行 vs DEV_FRONTEND_UI.md 头部仍写"待建, Plan v9 backlog").
> **维护体例**: append-only (沿用 ADR-022) + re-anchor 触发条件见 §5.
> **关联**: [V3_IMPLEMENTATION_CONSTITUTION.md](V3_IMPLEMENTATION_CONSTITUTION.md) §0.1 锚点表 / [ONBOARDING.md](ONBOARDING.md) (linear playbook 互补) / [SESSION_PROTOCOL.md](SESSION_PROTOCOL.md) (4 doc fresh read SOP).

---

## §0 本文件是什么 / 不是什么

| 维度 | 是 | 不是 |
|---|---|---|
| 性质 | random-access lookup table | linear playbook (走 ONBOARDING.md) |
| 受众 | user 自己 + CC + 远期接手 | 仅 CC restart (走 ONBOARDING.md §1-§9) |
| 内容 | task → doc 锚点 + 真值 timestamp | 设计 spec / sprint plan / 进度日志 |
| 长度 | ≤ 200 行 硬约束 (反 V5 颗粒度反模式) | 不限页数 (走 QPB Blueprint) |
| 数字 | 仅 anchor timestamp + cite source | hardcode 百分比 / 实施度 |

**反 anti-pattern 验证** (沿用 Constitution §0.2 体例):
- ✅ 0 凭空 enumerate 新决议
- ✅ 0 inline 重复 SSOT 内容
- ✅ 0 末尾 forward-progress offer (LL-098 X10)
- ✅ 禁词遵守 (memory #25 HARD BLOCK; whitelist 仅: 真账户 / 真发单 / 真生产 / 真测 / 真值)
- ✅ 0 hardcoded line# / function name / SQL (cite 走 path + section anchor + fresh verify timestamp)

---

## §1 当前真值快照

> fresh verify timestamp: **2026-05-22** (基于 docs.zip 5-20 sediment + Constitution v0.13 + Phase J Roadmap 5-20 + USER_TRIBAL_KNOWLEDGE 5-19).

| 维度 | 真值 | cite source |
|---|---|---|
| **V3 风控** | ✅ 全 Tier 完结 (Tier A 12/12 + Tier B 6/6 + 横切层 HC-1~4a closed + Gate D items 1-4 ✅ + Gate E partial closed) | Constitution §0.1 5-gate footer / RISK_FRAMEWORK_LONG_TERM_ROADMAP §2 |
| **当前 Phase** | Phase B-1 dry-run 进行中 (5-20 → 5-26) → Phase B-2 实际 live flip 5-27 Wed | Phase J Roadmap §1 Sequencing Principles |
| **5-18 LIVE-FIRE armed** | (c) push back 到 5-27 Phase B-2 — 5-18 armed live-fire 经 3 P0 事件 (LL-179/180/183) 后 .env 回滚 paper; 新 Path B (ADR-085) | backend/.env (fresh verify 5-22) / LL-179·180·183 / Phase J Roadmap §1 |
| **红线 5/5** | 见 §4 | account_truth_log.md + .env / configs/pt_live.yaml |
| **待 user 决议项** | U1-U15 (PG password / gp-weekly disable / Phase B-2 trigger / meta-monitor / Phase J 7 items / Frontend stack / hosting / auth / AI ops boundary) | USER_TRIBAL_KNOWLEDGE.md §1.2 |
| **下一里程碑** | Phase J Week 1 (5-27 → 6-3): Schtask register batch + PG password rotate + DingTalk HMAC | Phase J Roadmap §2 |

---

## §2 task → doc 锚点表

> 沿用 Constitution §0.1 "reference, 0 inline 重复" 体例. 每行 = 一个 user-facing task → 主入口 doc.

| 我想做什么 | 主入口 doc | 辅助 doc |
|---|---|---|
| 看后端有哪些 endpoint / 前后端 API 覆盖 | `docs/API_COVERAGE.md` (738 行 5-20 generated) | `scripts/build_api_coverage.py` (regenerate) |
| 看代码模块哪些没文档 mention | `docs/TRACEABILITY_INDEX.md` (588 modules / 154 dark / 66 critical) | `scripts/build_traceability_index.py` |
| 看调度时间线 (何时跑何任务) | `docs/SCHEDULING_LAYOUT.md` | `scripts/setup_task_scheduler.ps1` (canonical source) |
| 看 CC 可触发的 ops 操作 | `docs/runbook/cc_automation/00_INDEX.md` | 9 个 `NN_*_runbook.md` |
| 看 V3 风控完结状态 + 路线图 | `docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md` §20 | `docs/RISK_FRAMEWORK_LONG_TERM_ROADMAP.md` |
| 看下一步该做什么 (post-live 时序) | `docs/PHASE_J_ROADMAP_POST_LIVE_RESTART.md` | Phase K/L/M sections |
| 看 docs/design/ 10 个 P0/P1 实施时序 | Phase J Roadmap §2-§8 | `docs/design/P0_*.md` + `P1_*.md` |
| 看 user 待决议 + 历史决议 | `docs/USER_TRIBAL_KNOWLEDGE.md` §1 | `docs/DECISION_LOG.md` (D-1 ~ D-79) |
| 看 V3 实施 sprint 用法 (6 件套) | `docs/V3_IMPLEMENTATION_CONSTITUTION.md` | `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` + `docs/V3_LAUNCH_PROMPT.md` |
| 看 V3 sprint plan 拆分 | `docs/V3_TIER_A_SPRINT_PLAN_v0.1.md` | Tier B / 横切层 / PT cutover 各 plan file |
| 新 CC session 冷启动 / human onboard | `docs/ONBOARDING.md` (30 min playbook) | `docs/SESSION_PROTOCOL.md` (4 doc fresh read SOP) |
| 看灾备 / 紧急操作 | `docs/SOP_EMERGENCY.md` | `docs/SOP_DISASTER_RECOVERY.md` |
| 看铁律 / LL / ADR | `IRONLAWS.md` (v3.0) | `LESSONS_LEARNED.md` + `docs/adr/REGISTRY.md` |
| 看系统实际现状 | `SYSTEM_STATUS.md` | `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Quickstart |
| 红线决策 (.env / LIVE_TRADING / EXECUTION_MODE 切换) | `docs/V3_PT_CUTOVER_PLAN_v0.1.md` | ADR-027 / ADR-028 + Constitution §L10.5 |
| 平台 12 Framework + 6 升维 + 17 MVP | `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (QPB v1.16) | Wave 1-4 各 MVP 设计 |
| 因子相关 (定义 / 状态 / 测试) | `FACTOR_TEST_REGISTRY.md` | `FACTOR_COUNT_GLOSSARY.md` + `docs/FACTOR_ONBOARDING_SYSTEM.md` |
| 前端继续开发 / 主权交接路线 | §3 本节 | Phase J Roadmap §5+ + Phase K K6 (P1-36 frontend integration) |

---

## §3 前端主权交接路线

> **动机**: V3 风控完结 → user 痛点从"工程完成度"切到"主权交接" — user 不应长期依赖 CC session 执行 daily ops.

### §3.1 现状真值 (fresh verify timestamp: 2026-05-22)

| 维度 | 真值 | cite source |
|---|---|---|
| 后端 endpoint 总数 | 148 (across 25 router files) | API_COVERAGE.md §1 |
| 前端 consumed | 74 (50%) | API_COVERAGE.md §1 |
| Backend-only (无前端 consumer) | 74 (50%) | API_COVERAGE.md §1 |
| Frontend-only orphan (bug candidate) | 10 | API_COVERAGE.md §1 |
| 前端页面数 | 35 (post Phase H W1-6, 5-19) | DEV_FRONTEND_UI.md 头部 status |
| 前端 API client modules | 11 | DEV_FRONTEND_UI.md 头部 status |
| 前端实施度 | ~65% (post Phase H) | DEV_FRONTEND_UI.md 头部 |

### §3.2 CC 退场 milestone (M1-M5, 候选)

| # | milestone | user 不再需要 CC 的 daily action | 依赖 |
|---|---|---|---|
| M1 | user 看持仓 / 净值 / 告警 (readonly) | 现状已基本满足 (Frontend Phase H W1-6) | API_COVERAGE 已 consumed 部分 |
| M2 | user 调 .env / LIVE_TRADING_DISABLED / EXECUTION_MODE 切换 | EnvStateBanner + SafetyControlPanel (Phase H 已 wire) | Phase H W1-6 |
| M3 | user 处置 Gate E 决策 (DINGTALK / L4_AUTO_MODE 等) | 决策审批面板 + Gate 状态可视化 | P1-36 §5 + ADR-027/028 |
| M4 | user 处置 Reflector lesson 后置抽查 | Lesson queue UI | DEV_AI Layer 2 strategy_agent + P1-36 write API |
| M5 | user 看告警 + 紧急操作 (无 CC) | 紧急操作 + 风控告警 UI | Frontend Phase J wave (post live restart) |

### §3.3 时序 cite (不重复 Phase J Roadmap 内容)

| 阶段 | 前端主权动作 | cite |
|---|---|---|
| Phase B-1 (5-20 → 5-26) | M1-M2 已可用 (Phase H sustained) | DEV_FRONTEND_UI 头部 |
| Phase B-2 (5-27 → ) | live 期间 M1-M2 真生产 sustained | Phase J Roadmap §2 |
| Phase J Week 1-8 | M3 前置工作 (P0-21 reproducibility / P0-9 commit refactor / P1-36 risk API Phase 1) | Phase J Roadmap §3-§5 |
| Phase K (Q3) | M3-M4 前端集成 (P1-36 Phase 2-3) | Phase J Roadmap §6 K6 |
| Phase L (Q4) | M4-M5 完成 + closed loop UI | Phase J Roadmap §7 |

### §3.4 user 战略决策未定项 (cite USER_TRIBAL §1.2)

- U12 — Frontend stack decision (React 18 retain vs SvelteKit/Vue 3/Solid)
- U13 — Frontend hosting (local dev vs Servy persistent)
- U14 — Auth model upgrade (ADMIN_TOKEN → OAuth/RBAC)
- U15 — AI-assisted ops boundary (NLP cancel order / threshold change)

---

## §4 红线 5/5

> sustained 4-29 PT 清仓后. 任一漂移 = block + audit. 走 Constitution §L10.5 trigger.

| # | 项 | 真值 (5-22 anchor) | verify source |
|---|---|---|---|
| 1 | cash | ¥993,520.66 sustained | account_truth_log.md / Constitution v0.13 header |
| 2 | 持仓 | 0 (19+ days sustained as of 5-19) | xtquant API + position_snapshot |
| 3 | `LIVE_TRADING_DISABLED` | `true` (fresh verify 5-22) | `backend/.env:20` |
| 4 | `EXECUTION_MODE` | `paper` (fresh verify 5-22) | `backend/.env:17` + `configs/pt_live.yaml:26` |
| 5 | `QMT_ACCOUNT_ID` | 81001102 (反 v2 prompt cite "2039" 漂移 PR #211) | `.env` |

---

## §5 维护体例 + cite source SOP

### §5.1 re-anchor 触发条件

任一 true → 必更新 §1 + §3.1 + §4 真值:

1. Gate D / Gate E formal closure
2. Phase B-1 → B-2 → Phase J → K → L → M 阶段切换
3. 红线 5/5 任一项变更 (尤其 LIVE_TRADING / EXECUTION_MODE)
4. V4 候选 trigger (§20.4 4 V4 candidates)
5. 任何 cite source 文档结构变更 (e.g. API_COVERAGE regenerate)

### §5.2 cite source SOP (沿用 LL-105 SOP-6 cite 4 元素)

每个 cite 必含: **path + section anchor + fresh verify timestamp** (line# 仅当 section 不唯一时补).

### §5.3 数字 / 真值约束

- 数字仅含 anchor timestamp,不 hardcode 百分比 / 实施度漂移
- 不引超 1 周未 verify 数字 (沿用 memory #19/#20)
- 5-day-old 数字必标 `(待 fresh verify)`
- 5/5 红线项需 5-day 内 fresh verify

### §5.4 版本历史 (append-only, ADR-022)

- v0.1 (2026-05-22): initial draft. 触发 = 50+ docs/ 缺 navigation hub + N×N drift 实证 (API_COVERAGE vs DEV_FRONTEND_UI).
