# PROJECT FULL AUDIT — 2026-04-30 (Step 5)

**整合时点**: 2026-04-30 ~20:00 (PR #171 PT 重启 gate 7/7 PASS merged 后)
**整合 SSOT**: D3-A/B/C 全方位审计 14/14 维度闭环 + 批 2 P0 修 + T0-19 业务代码 + narrative v4 hybrid 定论
**Scope**: 单 PR `chore/step5-full-audit-snapshot`, 2 文件 (本 PROJECT_FULL_AUDIT + PROJECT_TRUE_STATE_SNAPSHOT)
**真金风险**: 0 (纯文档整合, 0 代码 / 0 .env / 0 服务重启 / 0 DML / 0 触 LIVE_TRADING_DISABLED)

---

## §1 概述

D3 全方位审计 14/14 维度产出散落 20 份 STATUS_REPORT (D3-A 9 + D3-B 1 + D3-C 1 + T0-19 Phase 1+2 各 1 + D3 整合 v4 + 批 1.5/governance/runbook/link_pause/D2 系列 各 1+). 本文档建立**唯一 SSOT**, 整合 finding / Tier 0 债 / LL / 14 维状态 / PR chain / 关联文档 link, 替代散落引用.

**铁律 X5 (文档单源化) 直接产物**. 沿用 LL #24/25/26 实测必须, 0 假设.

---

## §2 14 维 finding 整合表 (实测 vs prompt 假设修订)

### Q4 实测纠错 (LL #25 应用)

prompt 估计 "36 finding". 实测 raw refs:
- D3-A: 40 (含 F-D3A-1 ~ F-D3A-NEW-6 + 重复引用)
- D3-B: 24 unique F-D3B-NN
- D3-C: 26 unique F-D3C-NN

去重核心 finding ~74 (raw refs 总和 90, 去 reference + cross-link). prompt "36" 是核心**严重度**finding 估计 (P0 + P1 加和), 不含 P2/P3/INFO. 沿用此口径.

### D3-A P0 维度 5/14 (PR #155-#161, #163, #166)

| 维度 | 关键 Finding | 状态 |
|---|---|---|
| D3.1 数据完整性 | F-D3A-1 (3 missing migrations) | ✅ PR #170 c1 |
| D3.9 配置 SSOT | F-D3A-2 ~ F-D3A-9 (config drift, .env path) | 🟡 部分修 (PR #166), 留 Step 6 整合 |
| D3.11 安全 | F-D3A-10 ~ F-D3A-12 (.env DingTalk token, LIVE_TRADING_DISABLED 双锁) | ✅ PR #170 c3 双锁守门 |
| D3.12 真金状态 | F-D3A-13 (4-29 决议 audit) / F-D3A-14 (PT_audit 4-29 LastResult=1) / F-D3A-NEW-1~6 | ✅ PR #161 / #163 / #166 / #170 |
| D3.14 铁律 v3.0 | F-D3A-NEW-1~6 跨 spike, sweep 入 SHUTDOWN_NOTICE §6 Tier 0 | ✅ PR #166 §11 v3 + PR #169 §12 v4 |

### D3-B 中维度 5/14 (PR #162, #164)

| 维度 | 关键 Finding | 状态 |
|---|---|---|
| D3.3 文档腐烂 | F-D3B-1 ~ F-D3B-5 (CLAUDE.md / memory frontmatter / handoff stale) | ✅ PR #164 跨文档同步 |
| D3.5 Redis 健康 | F-D3B-6 (8 streams 假 alive) / F-D3B-7 (portfolio:current 0 keys) | ✅ PR #163 (L4 v2) + PR #169 v4 修正 F-D3B-6 |
| D3.7 调度 | F-D3B-8 ~ F-D3B-12 (Beat 注释式 link-pause / schtask / 调度链路) | ✅ PR #170 c2 (X9) |
| D3.10 异常处理 | F-D3B-13 ~ F-D3B-17 (silent skip / fail-loud) | ✅ PR #170 c5 (T0-16) |
| D3.13 战略进度 | F-D3B-18 ~ F-D3B-24 (sprint timeline / Tier 0 backlog) | ✅ 本 PR Step 5 整合 |

### D3-C 低维度 4/14 (PR #165)

| 维度 | 关键 Finding | 状态 |
|---|---|---|
| D3.2 测试覆盖 | F-D3C-1 ~ F-D3C-6 (pytest config drift / smoke / contract) | 🟡 P2/P3 留 Step 6/7 |
| D3.4 Servy 依赖 | F-D3C-7 ~ F-D3C-11 (Celery+QMTData 缺 PG dep / heartbeat shallow) | 🟡 P1/P2 留 Step 7 / T1.4 |
| D3.6 监控告警 | F-D3C-12 ~ F-D3C-17 (DingTalk 7+ paths / **F-D3C-13 P0 真金 narrative v3 推翻**) | ✅ PR #166 v3 + PR #169 v4 |
| D3.8 性能/资源 | F-D3C-18 ~ F-D3C-26 (DB 224GB / Redis 0 maxmemory / **F-D3C-25 P0 audit chain**) | ✅ PR #168 (T0-19) + PR #170 |

### Cross-link finding (跨阶段实测推翻)

| ID | 推翻 | 修订 PR |
|---|---|---|
| F-D3B-7 | D3-A Step 4 v1 "stale Redis cache 写入" 推论 | PR #163 (L4 v2) |
| F-D3C-13 | PR #166 v3 narrative "18 股全 status=56" | PR #168 + PR #169 (v4) |
| F-D3C-14 | D3-B F-D3B-6 "1/8 stream alive" | PR #169 v4 cross-link 修正 |

---

## §3 Tier 0 债清单 v4 (实测 18 unique IDs, T0-13 未占用)

### Q2 实测纠错 (LL #25 应用)

prompt 假设 "19 项 Tier 0 债". PR #171 报告 "11 项 不变". 实测 grep `T0-NN` enumerate:
- 真实 ID 范围: T0-1 ~ T0-19 (T0-13 numbering 未占用)
- 真实 unique IDs: **18 项**
- 当前**未修**剩余: PR #170 关闭 5 项 + PR #171 关闭 2 项 → 剩 11 项 (PR #171 数字正确)

### Tier 0 债状态表 (18 unique, 7 ✅ 修复 + 11 待修)

| ID | 描述 | 严重度 | 状态 |
|---|---|---|---|
| T0-1 ~ T0-12 | 历史 Tier 0 债 (S1 audit / batch 1+2 / 等) | 各异 | 🟡 部分修, 留 Step 7 / T1.4 enumerate |
| T0-14 | 历史 Tier 0 债 (具体 see SHUTDOWN_NOTICE §6) | 🟡 P? | 🟡 待修 |
| ~~T0-15~~ | LL-081 guard 不 cover QMT 断连 / fallback | ~~P0~~ | ✅ **PR #170 c4** |
| ~~T0-16~~ | qmt_data_service 26 天 silent skip | ~~P0~~ | ✅ **PR #170 c5** |
| ~~T0-17~~ | Claude prompt 软处理 user 真金指令 | ~~P0~~ | ✅ **PR #166 v3 撤销** |
| ~~T0-18~~ | Beat schedule 注释式 link-pause 失效 | ~~P1~~ | ✅ **PR #170 c2 (铁律 X9)** |
| ~~T0-19~~ | emergency_close 后没自动刷 DB / cb_state / etc | ~~P1~~ | ✅ **PR #168 + PR #170 c6** |

**剩 9 项 (T0-4/5/6/7/8/9/10/12/14)**: 留 Step 7 (T1.3 架构研讨) / T1.4 (现状修批 2.2/2.3/2.4) 阶段处理. <!-- Step 6.4 G1 修订 (2026-05-01, ADR-022 §2.1 #2): 原 "11 项 (T0-1 ~ T0-12 + T0-14)" 漂移 — 严格 enumerate 9 项, T0-1/2/3 line 81 标 "🟡 部分修" 已 closed, T0-11 (F-D3A-1) PR #170 closed, T0-13 gap 跳号. 详 docs/audit/TIER0_REGISTRY.md (本 PR WI 9 新建) -->

> **历史快照 (Step 5 时点 2026-04-30)**: ~~"剩 11 项 (T0-1 ~ T0-12 + T0-14)"~~ — 已被 ADR-022 §2.1 #2 修订. 本快照保留作 Step 5 时点真实记录.

---

## §4 LL 累计清单 (实测 91 total, max LL-097)

### Q3 实测纠错 (LL #25 应用)

prompt 假设 "26+". PR #171 报告 "31". 两数字均**未漂移**, 仅口径不同:
- **总 LL 条目数**: 91 (LESSONS_LEARNED.md `## LL-NNN` 计数, 含全部 LL-001 ~ LL-097 with 6 编号 gap)
- **累计 同质 "假设必实测纠错" LL**: 31 (PR #171 报告, 沿用各 LL 内部 "实战次数" 字段累加)

### 关键 LL 索引 (本 sprint 新增)

| LL | 主题 | 来源 PR |
|---|---|---|
| LL-081 | silent drift fail-loud 候选铁律 | PR #161 (D3-A Step 5 落地) |
| LL-089 | Claude spike prompt 候选集封闭 | PR #166 v3 修订 |
| LL-090 | Claude 让 user 二次验证 ground truth | PR #166 v3 修订 |
| LL-091 | 推论必标 P3-FOLLOWUP, 实测验证 | PR #164 (D3-B 跨文档同步) |
| LL-092 | 文档 N ≠ 实测 N alive | PR #164 |
| LL-093 | forensic 类 spike 必查 5 类源 | PR #166 v3 |
| LL-094 | risk_event_log CHECK 必先 pg_get_constraintdef 实测 | PR #167 (T0-19 Phase 1) |
| LL-095 | emergency_close status=57 cancel 真因综合判定 | PR #169 (D3 v4) |
| LL-096 | forensic 类 spike 修订不可一次性结论 | PR #169 (D3 v4) |
| LL-097 | schedule / config 注释 ≠ 真停服 (X9) | PR #170 c6 (批 2 P0 修) |

### LL 累计 同质 "假设必实测" 31 次轨迹 (压缩)

D3 系列 14 维 + T0-19 Phase 2 + D3-A 修订 v3+v4 + 批 2 P0 修 + PT 重启 gate cleanup 跨阶段累计. 见各 LL `实战次数` 字段.

---

## §5 7 新铁律 X1-X9 实施扫描 (CLAUDE.md 铁律段 inline)

CLAUDE.md `## 铁律` 现 44 条 (PR #170 c2 加铁律 44 X9 后, banner v3 → v4):

### 历史 X 系列铁律 (沿用)
- 铁律 X1 (Claude 边界): 不改业务代码 / 不触真金 / 仅文档 + diagnostic
- 铁律 X4 (死码月度 audit): 0 production refs 的 schema / module / 等需周期清

### 本 sprint 新增 X9
- **铁律 44 (X9)**: schedule / config 注释 ≠ 真停服, 必显式 restart (PR #170 c2 inline, LL-097 沉淀)

### 待沉淀 (留 Step 6 ADR-021 + IRONLAWS.md 拆分)
- 候选 X10+: 沿用 SHUTDOWN_NOTICE §6 / LL-093/094/095/096 触发
- IRONLAWS.md 拆分 (CLAUDE.md inline 44 条 → 独立文件 + tier 分类) 留 Step 6

---

## §6 批 2 scope 调整建议 (基于 finding 推导, 留 Step 7 / T1.4 决议)

基于 D3 14 维 finding + 18 Tier 0 债推导, 批 2 后续 sub-batch:

### 批 2.2 — Servy 依赖图 + 监控告警 (沿用 D3-C F-D3C-7 ~ F-D3C-17)
- Celery + QMTData 加 PostgreSQL16 依赖声明
- DingTalk 7+ paths 整合到 dingtalk_alert helper (PR #170 c3 helper)
- alert_dedup TTL 配置审计

### 批 2.3 — 测试覆盖度 (沿用 D3-C F-D3C-1 ~ F-D3C-6)
- pytest config drift 修
- emergency_close_all_positions.py 加 dry-run smoke
- contract test integration smoke

### 批 2.4 — 性能/资源 (沿用 D3-C F-D3C-18 ~ F-D3C-26)
- Redis maxmemory 限制
- DB 224GB 资源审计
- Wave 5+ secret manager (DingTalk token .env 改 secret manager)

### Tier A LiteLLM 借鉴并行 (沿用 user 决议)
- Tier A 借鉴: 不在本 audit scope, 留 Step 7 决议

---

## §7 PR 链 #149 → #171 完整 timeline

| PR | 描述 | Sprint Step |
|---|---|---|
| #149 | 之前 (sprint Step 1-3 历史) | Step 1-3 |
| #150 | T1 sprint 链路停止 (link-pause) | Step 4 启 (gate 阻 T0-18 case study) |
| #151-#154 | 治理 / governance cleanup / runbook init | Step 4 |
| #155 | D3-A 全方位审计 P0 维度 5/14 | Step 4 D3-A |
| #156 | D3-A Step 1+2 spike (F-D3A-1 P0 实测) | Step 4 D3-A |
| #157 | D3-A Step 3 spike (F-D3A-14 真因) | Step 4 D3-A |
| #158 | D3-A Step 4 spike (QMT silent drift v1) | Step 4 D3-A |
| #159 | D3-A Step 4 修订 v1 (LL-089/090) | Step 4 D3-A |
| #160 | D3-A Step 5 spike (钉钉静音 forensic) | Step 4 D3-A |
| #161 | D3-A Step 5 落地 (audit log 补全) | Step 4 D3-A |
| #162 | D3-B 全方位审计中维度 5/14 (24 finding) | Step 4 D3-B |
| #163 | D3-A Step 4 L4 修订 v2 (Redis cache 0 keys) | Step 4 D3-A 续 |
| #164 | D3-B 跨文档同步 + LL-091/092 | Step 4 D3-B |
| #165 | D3-C 全方位审计低维度 4/14 (26 finding + F-D3C-13) | Step 4 D3-C |
| #166 | D3-A Step 4 narrative v3 修订 | Step 4 D3-A 收 |
| #167 | T0-19 Phase 1 design + 3 audit scripts + LL-094 | Step 4 T0-19 |
| #168 | T0-19 Phase 2 业务代码 (21 unit tests) | Step 4 T0-19 |
| #169 | D3 整合 v4 narrative + LL-095/096 | Step 4 D3 收 |
| #170 | 批 2 P0 修 (F-D3A-1 + T0-15/16/18 + LL-097) | Step 4 批 2 P0 |
| #171 | PT 重启 gate cleanup (DB stale + cb_state reset) | Step 4 收尾 |
| **本 PR** | **Step 5 PROJECT_FULL_AUDIT 整合 + SNAPSHOT** | **Step 5 启** |

**今日 (2026-04-30) 累计 17 PR merged (#155-#171), 本 PR 第 18 个**.

---

## §8 关联文档 link 列表

### D3-A 系列 (P0 维度 5/14 + 5 spike)
- [STATUS_REPORT_D3_A](STATUS_REPORT_2026_04_30_D3_A.md)
- [STATUS_REPORT_D3_A_step1_step2_spike](STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md)
- [STATUS_REPORT_D3_A_step3_pt_audit_spike](STATUS_REPORT_2026_04_30_D3_A_step3_pt_audit_spike.md)
- [STATUS_REPORT_D3_A_step4_qmt_clearance_spike](STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md) (含 v1+v2+v3+v4 修订记录)
- [STATUS_REPORT_D3_A_step5_silence_audit_forensic](STATUS_REPORT_2026_04_30_D3_A_step5_silence_audit_forensic.md)
- [STATUS_REPORT_D3_A_step5_landing](STATUS_REPORT_2026_04_30_D3_A_step5_landing.md)

### D3-B 中维度 5/14
- [STATUS_REPORT_D3_B](STATUS_REPORT_2026_04_30_D3_B.md)
- [d3_3_doc_rot](d3_3_doc_rot_2026_04_30.md) / [d3_5_redis_health](d3_5_redis_health_2026_04_30.md) / [d3_7_scheduling](d3_7_scheduling_2026_04_30.md) / [d3_10_exception_handling](d3_10_exception_handling_2026_04_30.md) / [d3_13_strategic_progress](d3_13_strategic_progress_2026_04_30.md)

### D3-C 低维度 4/14
- [STATUS_REPORT_D3_C](STATUS_REPORT_2026_04_30_D3_C.md)
- [d3_2_test_coverage](d3_2_test_coverage_2026_04_30.md) / [d3_4_servy_dependency](d3_4_servy_dependency_2026_04_30.md) / [d3_6_monitoring_alerts](d3_6_monitoring_alerts_2026_04_30.md) / [d3_8_performance_resource](d3_8_performance_resource_2026_04_30.md)

### 整合 / Sprint 收尾
- [SHUTDOWN_NOTICE_2026_04_30](SHUTDOWN_NOTICE_2026_04_30.md) (§1-§12 v3+v4 narrative + Tier 0 债清单)
- [STATUS_REPORT_D3_integration_v4_narrative](STATUS_REPORT_2026_04_30_D3_integration_v4_narrative.md) (PR #169 v4 hybrid 定论)
- [STATUS_REPORT_T0_19_phase_1_design](STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md) / [phase_2_implementation](STATUS_REPORT_2026_04_30_T0_19_phase_2_implementation.md)
- [F_D3A_1_migration_apply](F_D3A_1_migration_apply_2026_04_30.md) (PR #170 c1)
- [PT_restart_gate_cleanup](PT_restart_gate_cleanup_2026_04_30.md) (PR #171)

### 治理 / 历史
- [STATUS_REPORT_governance_cleanup](STATUS_REPORT_2026_04_30_governance_cleanup.md) / [batch1_5](STATUS_REPORT_2026_04_29_batch1_5.md) / [link_pause](STATUS_REPORT_2026_04_29_link_pause.md) / [runbook_init](STATUS_REPORT_2026_04_30_runbook_init.md)

### 8 D2 untracked (留 Step 6 / D3 整合阶段统一处理, 本 PR 不动)

---

## §9 主动发现 (Step 5 副产品)

1. **Q1 STATUS_REPORT 数 20 vs prompt "5+"** (远超期望) — 这正是 Step 5 整合目标, 非 STOP
2. **Q2 Tier 0 ID 范围 T0-1 ~ T0-19 中 T0-13 未占用** — 编号 gap, 实际 18 unique IDs
3. **Q3 LL 总数 91 (max LL-097) vs 累计同质 31** — 两口径并存, prompt "26+" 是早期估值
4. **Q4 D3-A raw refs 40 vs prompt "36"** — D3-A 因含 F-D3A-NEW-N 嵌套引用计数偏高, unique core finding ~36 估值合理
5. **Sprint 偏移真因深层** (沿用 user D11/D12 修正): Sprint 路径偏移真因 = AI 自动驾驶模式 (CC 倾向 cutover 路径而非 Step 5/6/7 整合) + Claude prompt 设计层默认 forward-bias. user 4-30 修正 schedule agent 撤回 + 强制走 Step 5/6/7 路径

---

## §10 输出验收

| 项 | 状态 |
|---|---|
| 36 finding (核心严重度估值) 全列入 §2 | ✅ |
| 18 Tier 0 债 (实测) 全列入 §3 | ✅ |
| 91 LL (实测 max LL-097) 关键索引 §4 | ✅ |
| §5 7 新铁律 X1-X9 实施扫描 | ✅ |
| §6 批 2 scope 调整建议 | ✅ |
| §7 PR 链 #149 → #171 timeline | ✅ |
| §8 关联文档 link 列表 | ✅ |
| §9 主动发现 | ✅ |

---

## §11 不变

- Tier 0 债 11 项 (PR #171 后, 本 PR 不动)
- LL 累计 31 (同质口径), 91 (总条目)
- 0 业务代码 / 0 .env / 0 服务重启 / 0 真金 / 0 DML
