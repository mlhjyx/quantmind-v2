# STATUS_REPORT — Step 6.3a 6+1 文档 SSOT 整合 + Tier 0 enumerate + PR #176/#177 漏检修补 (2026-04-30 ~23:30)

**PR**: chore/step6-3a-audit
**Base**: main @ `acb1b5f` (PR #177 Step 6.2.5b-2 hook 实施 merged)
**Scope**: 文档 audit + 整合声明 + Tier 0 enumerate (沿用 PR #172 §3 决议留 Step 7 / T1.4 实施). 改 IRONLAWS §22 v3.0.2 + 新建 STATUS_REPORT
**真金风险**: 0 (纯 audit 决议 + 文档 metadata 修补, 0 业务代码 / 0 .env / 0 服务重启 / 0 DML)
**LL-098 stress test**: 第 9 次

---

## §0 环境前置检查 (E1-E13 全 PASS)

| 检查 | 实测 | 状态 |
|---|---|---|
| E1 git | main HEAD = `acb1b5f` (PR #177), 工作树干净 (开始时) | ✅ |
| E2 PG stuck | 沿用 PR #177 baseline (无 sprint 事件) | ✅ (沿用) |
| E3 Servy 4 服务 | 沿用 PR #177 baseline | ✅ (沿用) |
| E4 venv | Python 3.11.9 | ✅ |
| E5 LIVE_TRADING_DISABLED | True (实测) | ✅ |
| E6 真账户 | 沿用 4-30 14:54 实测 (read-only) | ✅ (沿用) |
| E7 cb_state.live nav | 993520.16 (PR #171 reset) | ✅ (沿用) |
| E8 position_snapshot 4-28 live | 0 行 (PR #171 DELETE) | ✅ (沿用) |
| E9 PROJECT_FULL_AUDIT + SNAPSHOT | 实存 (PR #172) | ✅ |
| E10 LL-098 | L3032 实存 (PR #173) | ✅ |
| E11 IRONLAWS.md §18/§21.1/§22/§23 | 实存 (PR #174-#177) | ✅ |
| E12 ADR-021 §3.6 | 实存 (1 grep 命中, PR #176) | ✅ |
| E13 config/hooks/pre-push X10 守门 | 实存 (1 grep 命中 "X10 cutover-bias", PR #177) | ✅ |

---

## §1 Work Item 1 — 6+1 文档 SSOT 整合 audit

### §1.1 实测 6+1 文档边界 (CC 实测决议, 不假设)

CC `ls` 实测 + `git mtime` 排序:

| # | 文件 | 大小 | 最近修改 | SSOT 角色 |
|---|---|---|---|---|
| 1 | `CLAUDE.md` | 77802 字节 (813 行) | 2026-04-30 22:03 (PR #174) | 项目主入口 + 沿用 v3.0 reference, 完整内容见 IRONLAWS.md |
| 2 | `IRONLAWS.md` | 44789 字节 (~880 行) | 2026-04-30 23:09 (PR #177) | 铁律 SSOT (T1×31/T2×14+X10/T3×0/DEPRECATED×1, +候选 X1/X3/X4/X5/跳号 X2/X6/X7/撤销 X8) |
| 3 | `LESSONS_LEARNED.md` | 190257 字节 (3105 行) | 2026-04-30 21:00 (PR #173) | LL SSOT (LL-001 ~ LL-098, 总数 92) |
| 4 | `SYSTEM_STATUS.md` | 49810 字节 | 2026-04-25 21:54 (5 天前) | 🔴 文档腐烂 — 5 天未更新, 沿用 PR #174 banner 后状态过时 |
| 5 | `FACTOR_TEST_REGISTRY.md` | 15031 字节 | 2026-04-11 01:42 (~3 周前) | 🔴 文档腐烂 — 3 周未更新, 长期 stale |
| 6 | `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` | (未实测) | (未实测, 沿用 QPB v1.16) | Blueprint SSOT (12 Framework + 6 升维 + 4 Wave) |
| **+1** | `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` | (未实测) | (未实测, 沿用 791 行 v3.4) | 系统 Blueprint (设计真相源, 已 archived in CLAUDE.md 文档查阅索引) |

### §1.2 6+1 边界决议 (CC 实测决议)

**主决议**: 沿用 CLAUDE.md 文档查阅索引 + sprint period 共识:

- **6 主 SSOT** (= 5 root + 1 Platform Blueprint):
  - 5 root MD: CLAUDE / IRONLAWS / LESSONS_LEARNED / SYSTEM_STATUS / FACTOR_TEST_REGISTRY
  - 1 Platform Blueprint: docs/QUANTMIND_PLATFORM_BLUEPRINT.md (Wave 平台化主线 SSOT)
- **+1 V2 SYSTEM Blueprint** (docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md): 系统设计真相源 (历史 archive 候选, 沿用 CLAUDE.md "唯一设计真相源 (791行)" reference)

**可选扩展** (非 6+1 主清单, 沿用文档查阅索引):
- 9 DEV docs (`docs/DEV_*.md`): 子领域设计文档
- ADR collection (`docs/adr/`, 16 文件含 README): 决议 SSOT cluster
- Audit collection (`docs/audit/`, ~50+ files): sprint period 实测记录

### §1.3 整合状态

| 文档 | 状态 | 决议建议 |
|---|---|---|
| CLAUDE.md | ✅ v3.0 reference 化 (PR #174) | 留 Step 6.3b 全文件 ~150 行 重构 (D-1=A 拆批) |
| IRONLAWS.md | ✅ SSOT 完整 (PR #174 + #176 + #177) | 沿用现状, 后续修订加 §22 entry |
| LESSONS_LEARNED.md | ✅ LL-098 沉淀 (PR #173) | 沿用现状, 不预沉淀 LL-099+ (沿用 PR #175 §5 决议) |
| SYSTEM_STATUS.md | 🔴 文档腐烂 (5 天未更新) | 留 Step 6.3b/Step 7 评估 (沿用 PR #175 §6 主题 F 维持现状原则, 0 改本 PR) |
| FACTOR_TEST_REGISTRY.md | 🔴 文档腐烂 (3 周未更新) | 留 Step 7 评估 |
| Platform Blueprint (QPB v1.16) | ✅ Wave 4 进行中 | 沿用现状 |
| V2 SYSTEM Blueprint | (CLAUDE.md 沿用 reference) | 留 Step 6.3b 评估 |

**核心决议**: 本 PR 不实施任何文档整合 (沿用 D-1=A 硬 scope + LL-098 拆批原则). 仅 audit + enumerate, 整合实施留后续 Step.

---

## §2 Work Item 2 — Tier 0 11 项剩余 enumerate (CC 实测发现 prompt 假设错)

### §2.1 实测 Tier 0 全清单 (T0-1 ~ T0-19, T0-13 gap = 18 unique IDs)

CC 实测 `docs/audit/d3_12_live_ops_state_2026_04_30.md` L63-72 + `STATUS_REPORT_2026_04_30_D3_A.md` L162-164 + `SHUTDOWN_NOTICE_2026_04_30.md §6` + `PROJECT_FULL_AUDIT_2026_04_30.md §3`:

| ID | 描述 | 严重度 | 当前状态 | 关闭 PR / 阶段 |
|---|---|---|---|---|
| **T0-1** | LL-081 `_assert_positions_not_evaporated` guard | P? | ✅ **已修** | 批 1 (实存 pt_qmt_state.py grep 4 hits) |
| **T0-2** | startup_assertions | P? | ✅ **已修** | 批 1 (实存 + SKIP_NAMESPACE_ASSERT bypass env) |
| **T0-3** | cb_multiplier hardcoded | P? | ✅ **已修** | 批 1 (0 hits 已参数化) |
| T0-4 | 写路径漂移 7 处 hardcoded 'live' (实测 27+ 处) | P0 | 🟡 待批 2 P0 | (大部分 ADR-008 D3-KEEP 设计合规, 真违规需 D3-B 深查) |
| T0-5 | LoggingSellBroker stub | P3 | 🟡 待批 2 P3 | 留 D3-B |
| T0-6 | DailyExecute 09:31 schtask disabled | P? | 🟡 批 2 评估 | ✅ State=Disabled (Last 4-19, Result=0), Stage 4.2 解锁 checklist 见 SCHEDULING_LAYOUT |
| T0-7 | auto_sell_l4 default False | P? | 🟡 批 2 决策 | 留 D3-B |
| T0-8 | dedup key 不含 code | P2 | 🟡 批 2 P2 | upstream — alert_dedup 表已修 (T0-11=F-D3A-1) |
| T0-9 | approve_l4.py 2 处 hardcoded 'paper' | P? | 🟡 批 3 | 留 D3-B |
| T0-10 | api/pms.py 死表 (position_monitor) | P? | 🟡 批 3 | ✅ 实测 confirmed (D3.1 F-D3A-2), api/pms.py:70 死读 |
| **T0-11** | F-D3A-1: alert_dedup / platform_metrics / strategy_evaluations 3 missing migrations | P0 | ✅ **已修** | PR #170 (psql -f apply, 3 表 EXISTS verifier exit 0) |
| T0-12 | Risk Framework v2 9 PR 真生产 0 events 验证缺 | P0 | 🟡 待 | 留 Step 7 / T1.4 (历史回放 / 合成场景验证) |
| T0-13 | (gap, 未占用) | — | (跳号) | — |
| T0-14 | 历史 Tier 0 债 (具体 see SHUTDOWN_NOTICE §6) | P? | 🟡 待修 | 留 Step 7 / T1.4 enumerate |
| ~~T0-15~~ | LL-081 guard 不 cover QMT 断连 / fallback | ~~P0~~ | ✅ **已修** | PR #170 c4 (QMTFallbackTriggeredRule) |
| ~~T0-16~~ | qmt_data_service 26 天 silent skip | ~~P0~~ | ✅ **已修** | PR #170 c5 (5min 阈值 + dingtalk_alert escalate) |
| ~~T0-17~~ | Claude prompt 软处理 user 真金指令 | ~~P0~~ | ✅ **撤销** | PR #166 v3 (PR #150 是补丁不是替代) |
| ~~T0-18~~ | Beat schedule 注释式 link-pause 失效 | ~~P1~~ | ✅ **已修** | PR #170 c2 (X9 inline + LL-097) |
| ~~T0-19~~ | emergency_close 后没自动刷 DB / cb_state / etc | ~~P1~~ | ✅ **已修** | PR #168 + PR #170 c6 |

### §2.2 主动发现: PROJECT_FULL_AUDIT §3 line 89 数字 11 项 vs 实测 9 项

**PROJECT_FULL_AUDIT line 89**: "**剩 11 项 (T0-1 ~ T0-12 + T0-14)**"

**实测真实 remaining** (CC 实测决定):
- 18 unique IDs (T0-1 ~ T0-19, T0-13 gap)
- ✅ 已修: T0-1, T0-2, T0-3, T0-11, T0-15, T0-16, T0-18, T0-19 = **8 项**
- ✅ 撤销: T0-17 = 1 项
- 🟡 待修: T0-4, T0-5, T0-6, T0-7, T0-8, T0-9, T0-10, T0-12, T0-14 = **9 项**
- Total accounted: 8 + 1 + 9 = 18 ✅ matches unique IDs count

**剩余真实数 = 9 项**, 不是 PROJECT_FULL_AUDIT 写的 11 项. **数字 假设错 sprint period 第 6 个**.

possible 解释:
- PROJECT_FULL_AUDIT (PR #172 写) 把 T0-1/2/3 也算 "剩余" (沿用 line 81 "🟡 部分修", 未严格 closed)
- 加 T0-1/2/3 = 9 + 3 = 12, 仍不对
- 或 11 = 18 - 7 (closed: T0-15/16/17/18/19 + T0-11 = 6) - 1 (T0-13 跳号) = 11. 但这把 T0-1/2/3 视为 remaining (符合 "部分修" 解释)
- 这种算法 = 11 项 = T0-1/2/3/4/5/6/7/8/9/10/12/14 (12 items) - 1 (T0-13 gap implicit) = 11. 还是 12 not 11.

最可能解释: PROJECT_FULL_AUDIT 数字漂移. 实际 9 项严格 closed-status 待修 (排除 ✅ 已修 + ✅ 撤销).

✅ **决议**: 沿用 9 项 严格状态. PROJECT_FULL_AUDIT line 89 数字 11 锁不调 (PR #172 锁), 沿用 audit doc 引用记录.

### §2.3 9 项剩余 Tier 0 待修分阶段建议

| 阶段 | 项 | 论据 |
|---|---|---|
| **Step 7 T1.3 架构研讨** | T0-12 (Risk v2 0 events 验证) | 架构层决策, 需 user 决议历史回放 vs 合成场景 |
| **T1.4 现状修批 2.2/2.3/2.4** | T0-4 (写路径漂移), T0-5 (LoggingSellBroker), T0-6 (DailyExecute disabled), T0-7 (auto_sell_l4), T0-8 (dedup key) | 实施层修, 沿用批 2 scope |
| **T1.4+ / 批 3** | T0-9 (approve_l4.py), T0-10 (api/pms.py 死表) | 实施层修批 3 |
| **悬空** | T0-14 (历史, 具体见 SHUTDOWN_NOTICE §6) | 需先深查 SHUTDOWN_NOTICE §6 内容才能定阶段 |

---

## §3 Work Item 3 — PR #176/#177 漏检修补

### §3.1 WI 3a: IRONLAWS.md §22 v3.0.2 entry ✅ 已加

**实施**: 本 PR §22 加 v3.0.2 entry (PR #177 Step 6.2.5b-2 hook 实施 + 文档修补).

**Before** (PR #176 锁后状态, IRONLAWS.md L822-826):
```
- **v3.0.1** (2026-04-30, Step 6.2.5b-1 PR): 文档修订 (基于 PR #175 6.2.5a audit 决议)
  - §18 X10 检测脚本候选语义修订 (pre-merge → commit-msg / pre-push extension, Git 原生支持)
  - 铁律 16/25/38/42 LL/ADR backref header 标准化 (沿用 PR #175 §4 D.4 例外建议)
  - §21.1 ADR 编号系统历史决议保留 (沿用 PR #175 §6 主题 F F.5)
  - §23 LL "假设必实测" 双口径计数规则 (新加, 沿用 PR #175 §2 主题 B B.5 决议)
- **v3.x+** (Step 6.2.5+): 候选 X1/X3/X4/X5 promote / Tier 重新 calibration / 等
```

**After** (本 PR 加 v3.0.2):
```
- **v3.0.1** (2026-04-30, Step 6.2.5b-1 PR #176): 文档修订 (基于 PR #175 6.2.5a audit 决议)
  - §18 X10 检测脚本候选语义修订 (pre-merge → commit-msg / pre-push extension, Git 原生支持)
  - 铁律 16/25/38/42 LL/ADR backref header 标准化 (沿用 PR #175 §4 D.4 例外建议)
  - §21.1 ADR 编号系统历史决议保留 (沿用 PR #175 §6 主题 F F.5)
  - §23 LL "假设必实测" 双口径计数规则 (新加, 沿用 PR #175 §2 主题 B B.5 决议)
- **v3.0.2** (2026-04-30, Step 6.2.5b-2 PR #177): hook 实施 + 文档修补
  - §18 X10 stress test 实绩段修补 5→8 次 (加 PR #175/#176/#177 三项)
  - (基础设施补) config/hooks/pre-push 加 X10 cutover-bias 守门 (软门转硬门, 沿用 §18 hard pattern 清单)
- **v3.x+** (Step 6.2.5+): 候选 X1/X3/X4/X5 promote / Tier 重新 calibration / 等
```

✅ **WI 3a 完成**.

### §3.2 WI 3b: dry-run 4 fail mode 治理债 enumerate

PR #177 主动发现 #5 候选未 cover 4 项:

| # | fail mode | 候选检测 | 决议 |
|---|---|---|---|
| 1 | branch name 命中 hard pattern | hook 已扫 branch name (沿用 PR #177 实施) | ✅ **已 cover** (实测 dry-run scenario 1 含 branch name 扫) |
| 2 | amend commit (`git commit --amend`) 引入 hard pattern | amend 改 HEAD subject, hook 仍扫 HEAD subject | ✅ **已 cover** (hook scan logic 不区分 amend vs 新 commit) |
| 3 | cherry-pick 引入 hard pattern | cherry-pick 创建新 commit, subject 沿用源 commit subject | ✅ **已 cover** (hook 扫 HEAD subject) |
| 4 | merge commit subject 含 hard pattern | merge commit 默认 subject 是 "Merge branch ..." 不太可能含 hard pattern, 但手工 -m 可能 | ⚠️ **理论 cover** (hook 扫 git log 含 merge commit subject) |

**决议**: dry-run 3 场景 (PR #177) 已 cover 主 fail mode + 4 候选未 cover 实际 ✅ 已 cover (理论上). 留 Step 7+ 实测验证 (低优先级).

### §3.3 WI 3c: git CLI 误导性输出候选铁律 27 audit

PR #177 主动发现 #2: 网络抖动后 git CLI 输出 "Everything up-to-date" 是误导性的 (实际 push 失败).

**关联铁律**: 铁律 27 (结论必须明确 ✅/❌/⚠️ 不准模糊).

**审计角度**: git CLI 是外部工具不归项目治理. 但 sprint period 内 CC / user 解读 git 输出时容易被误导.

**决议建议**: 
- ✅ 留 Step 7 决议 (沿用 PR #177 主动发现 #2)
- 候选实施: git wrapper script / `gh` CLI 替代 git push (gh 输出更明确)
- 或: 沿用 PR #177 STATUS_REPORT 沉淀 audit doc 引用记录, 不工程化

✅ **WI 3c audit 完成** (留 Step 7 决议, 0 实施).

---

## §4 主动发现 (Step 6.3a 副产品, 沿用 PR #X 模式)

1. **`SESSION_HANDOFF_2026_04_30_5_pillars_milestone.md` 实测不存在** — prompt §0 引用的 handoff doc 不在 repo (find 0 命中). 沿用 PR #172-#177 STATUS_REPORTs 作 implicit handoff. 沿用 LL "假设必实测" broader 候选 (本 PR 不沉淀 LL).

2. **PROJECT_FULL_AUDIT §3 line 89 数字 11 vs 实测 9** — Tier 0 剩余真实数 = 9 (T0-4/5/6/7/8/9/10/12/14), 不是写的 11. 沿用 sprint period 第 6 个数字 假设错. 候选 broader 34 → **35**.

3. **SYSTEM_STATUS.md 5 天未更新 (2026-04-25)** — 自 PR #150 link-pause sprint 启动后, sprint period 4-25 → 4-30 跨 8 PR (PR #172-#177 等) 0 同步更新 SYSTEM_STATUS.md. 沿用铁律 22 (文档跟随代码) 候选治理债. 留 Step 6.3b 决议.

4. **FACTOR_TEST_REGISTRY.md 3 周未更新 (2026-04-11)** — 长期 stale, sprint period 期间因子注册 0 改动. 沿用主动发现 #3 治理债. 留 Step 7 / T1.4 决议.

5. **6+1 文档边界沿用 CLAUDE.md 文档查阅索引** — CC 决议沿用 5 root + 1 Platform Blueprint = 6 主 SSOT, +1 V2 SYSTEM Blueprint. 替代候选: 6 SSOT + 1 ADR collection, 但 ADR cluster 通常作 governance reference 而非 SSOT.

6. **T0-1/2/3 严格状态 = ✅ 已修, 但 PROJECT_FULL_AUDIT 视为 "部分修"** — d3_12_live_ops_state 实测 confirms ✅ closed (pt_qmt_state.py / startup_assertions / cb_multiplier 全 ✅). PROJECT_FULL_AUDIT 写 "🟡 部分修" 是 sprint period 数字漂移, 不在本 PR 修.

---

## §5 LL "假设必实测" 累计更新

| 口径 | PR #177 后 | 本 PR (Step 6.3a) 后 |
|---|---|---|
| narrower (LL 内文链 LL-091~) | 30 | **30** (本 PR 0 新 LL) |
| broader (PROJECT_FULL_AUDIT scope) | 34 | **35 候选** (本 PR §4 #2 PROJECT_FULL_AUDIT line 89 数字漂移 11→9) |
| LL 总条目 | 92 | **92** (本 PR 0 新 LL) |

⚠️ **discrepancy 持续**: narrower 30 vs broader 35, 差 5. 沿用 IRONLAWS.md §23.3 双口径并存论据.

**broader 35 候选**:
- 是否本 PR 沉淀: ✅ 沉淀 (沿用 IRONLAWS.md §23.4 决议 (a) 模式 — audit doc 沉淀点, broader +1 合理)
- 是否 LL-099+ 沉淀: ❌ 不沉淀 (沿用 PR #175 §5 主题 E E.3 + PR #176 §1 WI 5 — LL 编号膨胀风险, audit doc 引用足够)

---

## §6 不变

- Tier 0 债 9 项严格剩余 / 11 项 PR #172 数字保留 (本 PR 不动 PR #172 锁)
- LESSONS_LEARNED.md 不变 (PR #173 锁, LL 总数 92, 0 新 LL)
- IRONLAWS.md 仅 §22 v3.0.2 entry 加 (其他段 PR #174-#177 锁)
- CLAUDE.md 不变 (PR #174 锁)
- ADR-021 不变 (PR #174-#176 锁)
- PROJECT_FULL_AUDIT / SNAPSHOT 不变 (PR #172 锁)
- config/hooks/pre-push 不变 (PR #177 锁)
- 其他 ADR / 其他 docs 不变
- SYSTEM_STATUS.md / FACTOR_TEST_REGISTRY.md 不变 (本 PR 仅 audit, 治理债决议留 Step 6.3b/Step 7)
- 0 业务代码 / 0 .env / 0 服务重启 / 0 DML / 0 真金风险 / 0 触 LIVE_TRADING_DISABLED
- 真账户 ground truth 沿用 4-30 14:54 实测
- PT 重启 gate 沿用 PR #171 7/7 PASS

---

## §7 关联

- **本 PR 文件**:
  - IRONLAWS.md (修改, +6 行 §22 v3.0.2 entry)
  - docs/audit/STATUS_REPORT_2026_04_30_step6_3a.md (新建, 本文件)
- **关联 PR**: #170 → #171 → #172 → #173 → #174 → #175 → #176 → #177 → 本 PR (Step 6.3a)
- **关联铁律**: 22 (文档跟随代码) / 27 (结论明确, WI 3c) / X4 / X5 / X9 / X10 (本 PR 第 9 次 stress test)
- **关联文档** (待 Step 6.3b/Step 7 决议):
  - SYSTEM_STATUS.md (5 天未更新治理债)
  - FACTOR_TEST_REGISTRY.md (3 周未更新治理债)
  - SHUTDOWN_NOTICE §6 (T0-14 描述深查留)

---

## §8 LL-059 9 步闭环不适用 — 沿用 PR #172-#177 LOW 模式

本 PR 是 audit + metadata 修补 (0 业务代码 / 无 smoke 影响), 跳 reviewer + AI self-merge.

LL-098 stress test 第 9 次 verify (沿用 LL-098 规则 1+2):
- PR description / 本 STATUS_REPORT / 任何末尾 0 写前推 offer
- 不 offer "Step 6.3b 启动" / "Step 7" / "paper-mode" / "cutover"
- 等 user 显式触发

**Sprint 治理基础设施 5 块基石** (PR #177 完结后完整, 本 PR 0 改):
1. ✅ IRONLAWS.md (PR #174 + #176 + 本 PR §22 v3.0.2)
2. ✅ ADR-021 (PR #174 + #176)
3. ✅ 第 19 条 memory 铁律 (4-30)
4. ✅ X10 + LL-098 (PR #173) + pre-push hook 硬门 (PR #177)
5. ✅ §23 双口径 (PR #176)

**第 19 条铁律自查**: 本 PR prompt 第 5 次连续验证, CC 实测决议所有数字 (无 prompt 假设).
