# TIER0_REGISTRY — Tier 0 治理债注册表

**Created**: 2026-05-01 (Step 6.4 G1 PR WI 9)
**Source**: 沿用 Step 6.3a §2.1 enumerate (T0-1 ~ T0-19, T0-13 gap = 18 unique IDs)
**Maintainer**: CC (AI 自主, 沿用 ADR-022 §2.4)
**Status**: 9 ✅ closed / 9 🟡 待修 (本表 §2)

---

## §1 Closed (9 项, 不需 PT 重启前再做)

| ID | 主题 | 关闭 PR | 关闭日期 |
|---|---|---|---|
| T0-1 | LL-081 `_assert_positions_not_evaporated` guard | 批 1 (sprint period 早期, sustained Step 6.3a §2.1 实测) | sprint period |
| T0-2 | startup_assertions | 批 1 (实存 + SKIP_NAMESPACE_ASSERT bypass env) | sprint period |
| T0-3 | cb_multiplier hardcoded | 批 1 (0 hits 已参数化) | sprint period |
| T0-11 (F-D3A-1) | 3 missing migrations (alert_dedup / platform_metrics / strategy_evaluations) | PR #170 (psql -f apply, 3 表 EXISTS verifier exit 0) | 2026-04-30 |
| T0-15 | LL-081 guard 不 cover QMT 断连 / fallback | PR #170 c4 (QMTFallbackTriggeredRule + 6 unit tests) | 2026-04-30 |
| T0-16 | qmt_data_service 26 天 silent skip | PR #170 c5 (5min 阈值 + dingtalk_alert escalate, 7 unit tests) | 2026-04-30 |
| ~~T0-17~~ | ~~Claude prompt 软处理 user 真金指令~~ | **撤销** PR #166 v3 (PR #150 是补丁不是替代) | 2026-04-30 |
| T0-18 | Beat schedule 注释式 link-pause 失效 | PR #170 c2 (X9 inline + LL-097 入册) | 2026-04-30 |
| T0-19 | emergency_close 后没自动刷 DB / cb_state / etc | PR #168 (业务代码 + 21 unit tests) + PR #170 c6 | 2026-04-30 |

---

## §2 待修 (9 项, owner + ETA + 阻塞依赖)

> **Step 6.4 G1 决议** (2026-05-01, 沿用 ADR-022 §2.4 反 "留 Step 7+" 滥用): 7 项 (T0-4/5/6/7/8/9/10) 走 T1.4 批 2.x AI 自主修. 2 项 (T0-12/14) 留 Step 7 T1.3 架构层决议 (G2 范围, CC 不能单方面决议).

### §2.1 T0-4 — 写路径漂移 7 处 hardcoded 'live' (P0)

- **owner**: CC
- **ETA**: T1.4 批 2.x P0 (PT 重启 gate 后 1-2 周)
- **阻塞依赖**:
  - 沿用 D3-B audit (大部分 ADR-008 D3-KEEP 设计合规, F18 已撤销 LL-060)
  - 真违规需 D3-B 深查列出具体函数 + 影响范围
- **修法**: 走 D3-B 后续审计 spike, AI 自主 PR (~30 行业务代码改动估算)

### §2.2 T0-5 — LoggingSellBroker stub (P3)

- **owner**: CC
- **ETA**: T1.4 批 2.x P3 (低优先级, PT 重启后才相关)
- **阻塞依赖**: 业务决策 — `LoggingSellBroker` 是否替代为 production broker (依赖 PT 是否重启 + .env paper→live 授权)
- **修法**: 沿用 PT 重启 gate, 决议后 AI 自主替代实施 (broker_qmt 已 production-ready, stub 仅 paper 模式 fallback)

### §2.3 T0-6 — DailyExecute 09:31 schtask disabled (P?)

- **owner**: CC + user (Stage 4.2 解锁 checklist 决议)
- **ETA**: PT 重启 gate 解锁后 (依赖 ⏳ 运维层 prerequisite)
- **阻塞依赖**:
  - F14 自愈 + Session 21 F19 phantom 清理 (sustained 已 closed)
  - paper-mode 5d dry-run + .env paper→live 授权
- **修法**: PT 重启 gate 通过 → schtask `Enable-ScheduledTask`, AI 自主 ops

### §2.4 T0-7 — auto_sell_l4 default False (P?)

- **owner**: CC + user (业务决策)
- **ETA**: T1.4 批 2.x P? (PT 重启 gate 后)
- **阻塞依赖**: 业务决策 — `auto_sell_l4 default=False` 是否改 `True` (L4 自动卖空开关默认值)
- **修法**: user 决议后 .env 配置改, 或 config schema default 改, AI 自主实施

### §2.5 T0-8 — dedup key 不含 code (P2)

- **owner**: CC
- **ETA**: T1.4 批 2.x P2
- **阻塞依赖**:
  - upstream alert_dedup 表已修 (T0-11=F-D3A-1, PR #170)
  - 剩 dedup key 升级到含 code (per-stock alert dedup 粒度)
- **修法**: AI 自主 PR (`format_dedup_key` 加 code 参数, ~10 行 + tests)

### §2.6 T0-9 — approve_l4.py 2 处 hardcoded 'paper' (P?)

- **owner**: CC
- **ETA**: T1.4 批 3 (低优先级, approve_l4 是紧急 ops CLI, 罕用)
- **阻塞依赖**: 沿用 ADR-008 D3-B (approve_l4 应走动态 execution_mode 而非 hardcoded)
- **修法**: AI 自主 PR (`scripts/approve_l4.py` 改 hardcoded 'paper' → 读 settings.execution_mode, ~5 行)

### §2.7 T0-10 — api/pms.py 死表 (position_monitor) (P?)

- **owner**: CC
- **ETA**: T1.4 批 3 (低优先级, deprecated endpoint)
- **阻塞依赖**:
  - 沿用 D3.1 F-D3A-2 实测 confirmed (api/pms.py:70 死读 position_monitor 表)
  - PMS 已并入 Wave 3 MVP 3.1 Risk Framework (ADR-010), api/pms 已 deprecated
- **修法**: AI 自主 PR (删除 api/pms.py 整 router, 或加 410 Gone response, 沿用 PR #34 PMS 死码处置 模式)

### §2.8 T0-12 — Risk Framework v2 9 PR 真生产 0 events 验证缺 (P0)

- **owner**: CC + user (架构决议 — 历史回放 / 合成场景 methodology)
- **ETA**: 留 **Step 7 T1.3** (G2 范围, 架构层决议)
- **阻塞依赖**:
  - 历史回放 methodology (使用 backtest 数据流模拟历史风控 events)
  - 或合成场景 methodology (写测试用例模拟 -29% / -10% scenario)
  - 选择哪种走 G2 user/CC 对话决议
- **修法**: Step 7 T1.3 决议 → AI 自主 PR

### §2.9 T0-14 — 历史 Tier 0 债 (具体 see SHUTDOWN_NOTICE §6) (P?)

- **owner**: CC + user (架构决议 — Step 7 T1.3 enumerate 完整列表)
- **ETA**: 留 **Step 7 T1.3** (G2 范围, 当前 enum 不完整)
- **阻塞依赖**:
  - SHUTDOWN_NOTICE §6 历史 Tier 0 enum 当前部分覆盖, 需 G2 user 决议是否扩 (T0-14 是否本身就是 placeholder)
- **修法**: Step 7 T1.3 决议 → AI 自主实施

---

## §3 维护规则

- 新 Tier 0 项发现 → 加入本表 §1 (closed) 或 §2 (待修)
- 项关闭后 → 从 §2 移到 §1 + 标 PR 链接
- 沿用 ADR-022 集中机制: 不在 SHUTDOWN_NOTICE / PROJECT_FULL_AUDIT inline 维护重复 enum, 本表是 SSOT
- 关联文档:
  - SHUTDOWN_NOTICE_2026_04_30 §6 (历史快照, 已 sync §9 closed status)
  - PROJECT_FULL_AUDIT_2026_04_30 line 89 (历史快照, 已 ADR-022 §2.1 #2 修订)
  - Step 6.3a STATUS_REPORT §2 (实测 enumerate source)
  - Step 6.4 G1 STATUS_REPORT (本 PR)

---

## §4 G1 vs G2 边界 (沿用 D72 + ADR-022 §2.4)

- **G1 (本 PR Step 6.4 G1 + T1.4 批 2.x AI 自主修)**: 7 项 (T0-4/5/6/7/8/9/10), 文档同步 + 业务代码修改 + ops 解锁均可 AI 自主
- **G2 (Step 7 T1.3 架构层决议)**: 2 项 (T0-12/14), 需 user/CC 对话决议 methodology 或 enum scope

---

**TIER0_REGISTRY.md 写入完成 (2026-05-01, Step 6.4 G1 PR WI 9)**.
