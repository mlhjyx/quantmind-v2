# sprint_state.md reconcile draft v3 (5-02)

**vs v1/v2 改动 (memory prompt 铁律 v1/v2/v3 + 反 anti-pattern v4 沿用)**:
- v1/v2 错: 预填 Session # / PR count / yaml key / 文件路径推断值, CC 沿用导致 STOP 反问
- v3 修正: **所有数字 / Session # / yaml key / PR # / 文件路径全部留占位 "{{CC 实测决议}}", CC 真测真值后填入**

**性质**: 给 CC 的 input 模板, CC 真测真值后 patch sprint_state.md.

---

## 给 CC 的真测验收清单 (CC apply 前必 verify)

CC 真测每项, 任一不实立即 STOP 反问 user:

| # | 字段 | 真测方法 | 占位 |
|---|---|---|---|
| 1 | sprint_state.md 当前 frontmatter line 3 description 真值 | head -30 sprint_state.md | `{{CURRENT_DESCRIPTION_LINE_3}}` |
| 2 | sprint_state.md 当前 yaml key 真清单 | grep "^[a-z]" sprint_state.md head -30 | `{{CURRENT_YAML_KEYS}}` |
| 3 | 5-02 sprint 真 Session # (sequential after line 3 真 Session #) | 1 推断 | `{{NEW_SESSION_NUM}}` |
| 4 | line 3 archive 真 key 名 (匹配 已存在 archive 命名风格) | 2 + 3 推断 | `{{ARCHIVED_KEY_NAME}}` |
| 5 | main HEAD commit hash | git rev-parse HEAD | `{{MAIN_HEAD}}` |
| 6 | 5-01 ~ 5-02 PR merged 真清单 + count | gh pr list --search "merged:2026-05-01..2026-05-02" | `{{PR_LIST}}` / `{{PR_COUNT}}` |
| 7 | Layer 2.1.7 chain 5 commit hash 真值 | git show c0dac99 / 02f916f / cc0f4a7 / 7d80e50 / 42c9abc | `{{CHAIN_COMMITS}}` |
| 8 | ll_unique_ids 真值 | grep -c "^## LL-" LESSONS_LEARNED.md (减去 inline note 不存在的) | `{{LL_COUNT}}` |
| 9 | F-D78-240 订正 audit md 真路径 | ls docs/audit/2026_05_audit/findings/ (PR #209 sediment) | `{{F_D78_240_CORRECTION_PATH}}` |
| 10 | LL-101 真行号 LESSONS_LEARNED.md | grep -n "^## LL-101" | `{{LL_101_LINE}}` |

---

## Part A: 新 frontmatter description (CC patch 真值后插入 line 3)

操作 (CC 真测决议执行):
1. 读现 line 3 description (真值 = `{{CURRENT_DESCRIPTION_LINE_3}}`)
2. 改名为 `{{ARCHIVED_KEY_NAME}}` (匹配现 archive 命名风格)
3. line 3 位置插入新 description (内容见下面 §A.1)
4. yaml 验证: 现 `{{CURRENT_YAML_KEYS}}` 全保留 + 新增 1 个 archived key + 新 description 覆盖 line 3

### §A.1 新 description 草稿 (CC 真值替换占位)

```yaml
description: Session {{NEW_SESSION_NUM}} 末 (2026-05-02) — **Audit 5-01 Week 1 9/9 WI 闭环 (7 P0 治理 closed/demoted) + Sprint Close {{PR_COUNT}} PR + Layer 2.1.7 chain 闭环 + 5-02 双合并调查真测发现 F-D78-240 真值漂移 48.6% (35→18) + WF 4 治理债 + PR #209 真值订正 + LL-101 sediment**.

✅ main HEAD `{{MAIN_HEAD}}` (PR #209 merged 5-02 11:23Z, fast-forward 9cdaa91→{{MAIN_HEAD}}).

✅ Audit Week 1 (5-01 STATUS_REPORT_2026_05_01_week1.md) 9/9 WI 闭环: 0.5 ground truth (broker.connect ✅ + cash=¥993,520.66 + drift=0.0001%) / 1 pip CVE-2026-3219 → 26.1 (F-D78-271/272 closed) / 2 risk-health ImportError 修 (`get_notification_service()` factory + DingTalk verify, F-D78-235 closed) / 2.5 QMT broker reconnect (真根因=GUI 未启动, F-D78-245 fixed via user-action) / 3 schtask 17h 0 runs demoted P0→P3 (F-D78-289) / 4 factor IC backfill (MAX=2026-04-28 节前最后交易日, F-D78-257 closed) / 5 emergency SOP / 6 account truth log SOP / 7 STATUS_REPORT push.

🟡 5-01~02 Sprint Close 主线 = Layer 2.1.7 chain (dv_ttm 4-28 100% NULL): reconnaissance {{CHAIN_COMMIT_1}} → RC4 {{CHAIN_COMMIT_2}} (真因 = Tushare 非确定性回填) → A1 {{CHAIN_COMMIT_3}} → A1.1 {{CHAIN_COMMIT_4}} → A1.1.B {{CHAIN_COMMIT_5}} (factor_values variance 1→3487 distinct 恢复). 4-27/4-28 IC 仍 NULL 真因 2 = forward horizon T+5 未到, 5-08 后自然恢复.

✅ 红线 sustained: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true (4 层防御). PT 4-29 暂停清仓后 0 alpha generation sustained.

🆕 **5-02 双合并调查真测真金 finding** (CC 5-02 STATUS_REPORT + PR #209 sediment):
- **F-D78-240 真值漂移 48.6%** (cite "35" 真值 18, **NOT 47.4%** — LL-101 自身真讽刺纠错): 真值 = 17 CC emergency_close fills + 1 GUI sell. 漂移源 = audit risk/08:40 cite "user 4-30 GUI sell **18 股**" 歧义 ("18 股"=持仓数, 真 trade 笔数=1). PR #169 narrative v4 真值 source ✅. 订正 sediment: `{{F_D78_240_CORRECTION_PATH}}` (212 lines / 8 sections). LL-101 sediment LESSONS_LEARNED.md L{{LL_101_LINE}}+.
- WF 4 项治理债 (F-WF-1/2/3/4 候选, Step B sediment): STABLE 跨脚本两套 (LOOSE wf_phase24:385 vs STRICT wf_equal_weight:392-403, 同 CORE3+dv_ttm 真值 std=0.5839 在 LOOSE 判 STABLE 在 STRICT 判 HIGH_VARIANCE) / Overfit 阈值跨脚本两套 (0.5 vs 0.7) / wf_equal_weight docstring "2014-2026 12 年" 真 train 8 年 / full_sample_sharpe 真 6 年 (2020-2026) NOT 12 年.
- sim-to-real gap finding: 5 fold test 期最后=2026-04-10, **4-29 PT 真生产事件 (卓然 -29% / 南玻 -10%) 不在任何 fold 内**. WF Sharpe=0.8659 PASS 不验证 4-29 真期间 sim-to-real gap (audit F-D78-85 真证据加深).
- F-D78-291 候选 (P3 治理): `09_emergency_close_real.md` line 87 cite "17 fills" ✅ vs line 102 cite "GUI 18 trades" 错值, sub-md 内部真 0 cross-check. 留 future PR in-place 修.

✅ 0.8659 真定义订正: combined_oos_sharpe = 5 fold OOS NAV 拼接 1250 day → calc_sharpe. NOT fold mean (fold mean = 0.7874, 5 fold 真值 0.1882 / 0.286 / 0.5192 / 1.2652 / 1.6786, dispersion 8.8x).

✅ trade_log SQL 真测 (CC 5-02 Q1-Q5): 88 rows / MAX=2026-04-17 / 4-18~5-02 真 14 day gap / position_snapshot 4-27 live=19 + 4-28~5-02 全 0 silent drift / risk_event_log 30d 仅 2 entries (4-29 P0 ll081 + 4-30 info db_cleanup).

✅ PR #168 _backfill_trade_log hook 真状态: MERGED 4-30 10:31:50, t0_19_audit.py:178, 21 unit tests PASS, 5-02 sprint 0 改动. 17 emergency_close fills 真复用 (FILL_EVENT_REGEX 真匹配 104354.log) ✅. **4-30 GUI sell 1 笔不可复用** (logs/ 4-30 0 emergency_close file), 需 Step B 真测 xtquant query_history_trades 4-30 真值 + 决议 path.

🆕 **Audit 5-01 全景** (114 sub-md / ~12,300 行 / ~265 finding / 37 P0 治理): docs/audit/2026_05_audit/. Phase 1-9 完结. 5-01 user 修正 audit "1 人 vs 企业级" 命题为 **"3 角色协作 (Claude.ai + CC + user) 的 N×N 同步成本"**, 决议: 继续企业级 + Claude.ai 帮做.

✅ ll_unique_ids = **{{LL_COUNT}}** (LESSONS_LEARNED.md grep 真测).

**剩余 backlog**:

- **P1 (待 Step B prerequisite ready 后起手)**: Layer 2.1.1 trade_log backfill = audit F-D78-240 (真值 18 笔). 真 scope = 17 fills via _backfill_trade_log hook + 1 GUI sell via Step B 决议 path + risk_event_log audit row 1 行. **prerequisite**: (i) ✅ (C) 真值订正 PR #209 merged (35→18 sediment) (ii) Step B CC 真测 xtquant query_history_trades 4-30 真返 1 笔 (688121 / 4500 股 / fill_price / executed_at) (iii) user 决议 position_snapshot 4-28~5-02 stale 修不修.

- **P1 plan-mode**: Layer 2.1.7 A2 架构解耦 (Layer 2.3 主路径) — 改 prod + schtask, 大 blast radius, 需 plan-mode 起手.

- **P2 audit Week 2 candidate** (sediment, 0 forward-progress offer): F-D78-241 4 数据源 stale audit / F-D78-246 pytest -m regression 0 marker / F-D78-273 monthly_rebalance 33% expired 根因 / F-D78-264/265 risk_event_log 30d 2 entries (部分被 4-29 Risk v2 9 PR 覆盖, 部分留 sub-task 2.1.1 audit row 填补) / F-D78-268 minute_bars 18d 0 增量 / 14 callers cluster Layer 2 cleanup / position_snapshot 0 audit timestamp / F-D78-293 MiniQMT_AutoStart schtask 0 command / 🆕 F-D78-291 09_emergency_close_real.md 自相矛盾.

- **P3 long-tail**:
  - 4-15→4-20 dv_ttm cascade backfill (从 P2 降级, 并入 5-08 IC verify, ROI < 1% 12yr Sharpe)
  - 🆕 F-WF-1/2/3/4 (Step B audit md sediment, Step B PR merged 后 cite 真路径)
  - Layer 2.5.2 BH-FDR M backfill (F-D78-60)
  - F-D78-251/252 mypy install
  - F-D78-259/260 D-decision SSOT registry
  - F-D78-267 Frontend ~80% gap
  - Layer 2.5.3/5/6/8
  - 5-08 后 4-27/4-28 IC verify

- **哲学层 / 跨集群**:
  - F-D78-21 路线图 batch+monitor 哲学 vs L0 (V3 1823 行 sediment 0 实施)
  - F-D78-261 T1.3 20 决议 0 实施 (V3 部分 supersede)
  - F-D78-26/32 N×N 同步漂移 — 5-01 命题修正 + 本文档 SOP-1/SOP-2/SOP-3 应对
  - F-D78-19/33/48/176 治理 vs alpha disconnect (5-01 决议: 继续企业级 + Claude.ai 帮做)
  - 🆕 **F-D78-85 sim-to-real gap 真证据加深** (5-02 双合并调查发现, 5 fold 不含 4-29) — PT 重启决议必须含独立 sim-to-real gap verify, 不能仅 WF PASS

**V3 风控架构 status**: Draft 1.0 / 1823 行 / 20 章 / L0-L5 6 层 / Tier A 7-9 周 + Tier B 4-5 周. 等 §20 10 项决议 + Tier A scope finalize.

**Session 起手 SOP (5-02)**:

**SOP-1**: 推荐起手项前必 cross-check 3 源 dedup — (1) audit STATUS_REPORT (2) 本文档顶部+backlog (3) user 最近消息. 已闭环 / demoted finding 必明示 status, 不重复推荐. 任何"我推断"必标 source.

**SOP-2 (F-D78-240 漂移触发)**: audit cite 数字 (人数 / 笔数 / 行数 / 金额 / commit hash) **必 SQL/git/log 真测 verify before 复用**. 单 cite 不够, 三源交叉. cite 链漂移是 N×N 同步漂移 textbook 案例.

**🆕 SOP-3 (5-02 prompt 自身漂移触发)**: Claude.ai 写 CC prompt 必含的字段 (Session # / PR count / yaml key / 文件路径 / commit hash) **不预填推断值, 留占位 `{{CC 实测决议}}` CC 真测填入**. memory prompt 铁律 v1/v2/v3 沿用. CC 真测决议优先于 Claude.ai memory cite.

**5-02 实证 (5 重复发)**:
- SOP-1 触发: Claude.ai 推 "第一波 4 项" 含 pip CVE / risk-health / factor IC, 全部 5-01 已闭环.
- SOP-2 触发: F-D78-240 cite "35" 真值 18, 漂移 48.6%. audit Phase 1 cite "18 股"歧义 → 下游全错.
- 真讽刺自身实证: LL-101 PR #209 自身含 4 处 "47.4%" 错值 (正确 = 48.6%), reviewer 全抓出 fix.
- LL-100 chunked SOP 真生效证据: PR #209 reviewer 1 run 105s 完成, 0 kill, 0 retry, 5/5 spot-checks PASS.
- **🆕 SOP-3 触发**: PR #209 merged 30 min 内, Claude.ai v2 apply prompt 含 4 处 stale cite (Session 45 真值 48 / 17 PR 真值 26 / yaml 5 key 真值 9 / archived-44 双 key 冲突). LL-101 enforcement failure in real-time. v3 修正: 全部数字留占位.

**Session {{NEW_SESSION_NUM}}+1 入口**: Step B (B1) = WF 治理债 audit md sediment (4 指标真定义 + F-WF-1~4 + sim-to-real gap finding). 与 sprint_state v3 apply 串行 (sprint_state 干净后 Step B cite 真路径).

历史背景 (line 3 现 description 真值 archive 后): 详 `{{ARCHIVED_KEY_NAME}}`.
```

---

## Part B: 新 ## handoff section (插在第 1 个 `## 🚀` 之前)

操作 (CC 真测决议执行):
1. 读 sprint_state.md 找第 1 个 `## 🚀` 真 line # (CC 真测)
2. 在该 line 之前插入新 ## section (内容见下面 §B.1)

### §B.1 新 handoff section 草稿 (CC 真值替换占位)

```markdown
## 🚀 2026-05-02 Session {{NEW_SESSION_NUM}} 末 Handoff — **Audit Week 1 闭环 + Sprint Close {{PR_COUNT}} PR + Layer 2.1.7 chain + CC 双合并调查真测真金 finding + PR #209 真值订正**

**时段**: 2026-05-01 ~ 2026-05-02 (跨 sessions, 五一假期窗口)

**触发**: D72-D78 反 sprint period treadmill + Claude 4 次错读 → 5-01 全方位 audit (114 sub-md / ~12,300 行 / 37 P0 治理) → Week 1 P0 立即修 → 5-01~02 Layer 2.1.7 chain dv_ttm 4-28 NULL 真因诊断 + cascade 重算 → 5-02 Claude.ai+user 战略对话 → 5-02 双合并调查真测发现 F-D78-240 真值漂移 48.6% + WF 4 治理债 → PR #209 真值订正 + LL-101 sediment.

### Audit 5-01 全景 ✅

完整 audit folder: `docs/audit/2026_05_audit/` (137 文件 / 114 sub-md / ~12,300 行)
- Phase 1-9 完结
- ~265 finding / **37 P0 治理** / ~60 P1 / ~114 P2 / ~58 P3
- **0 P0 真金** (LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / xtquant 0 持仓 / cash=¥993,520.66 sustained)
- Phase 1-8 PR 8 个 (#182~#189) 已 merged

**6 cluster 真根因** (audit ROOT_CAUSE_ANALYSIS):
1. 路线图哲学层 (F-D78-21/25/61/89/195) — Wave 1-4 batch+monitor 哲学 vs L0 event-driven
2. 真生产 enforce silent failure (F-D78-8/235/240/241/245/268/273)
3. 治理 over-engineering (F-D78-19/26/33/147/176/251/259/260/276)
4. 盲点 + framework 自身缺 (F-D78-48/53/196/267/278-281)
5. 数字漂移 ex-ante prevention 缺 (F-D78-76/247/276)
6. security 真核 0 sustained (F-D78-271/272) — 8 month 0 install pip-audit/mypy

**5-01 user 命题修正**: audit "1 人 vs 企业级架构 disconnect" 缩小. 真问题 = **3 角色协作 (Claude.ai + CC + user) 的 N×N 同步成本** (4 源 N(N-1)/2 = 6 同步路径, 每路径都可能漂移). 解法: **修协作模式** (本文档 SOP-1/2/3 段), 不是砍架构. user 决议: 继续企业级 + Claude.ai 帮做.

### Audit Week 1 closure ✅ (5-01)

7 项 P0 治理 closed/demoted, 9/9 WI 闭环 — 详 STATUS_REPORT_2026_05_01_week1.md 真值表.

| WI | Audit Finding | 处理 |
|---|---|---|
| 0.5 | (oneshot ground truth) | broker.connect ✅ + cash=¥993,520.66 + drift=0.0001% |
| 1 | F-D78-271/272 (pip CVE-2026-3219, 8 month) | pip 26.0.1→26.1, pip-audit 0 vulns ✅ |
| 2 | F-D78-235 (risk-health ImportError 14-caller cluster) | `get_notification_service()` factory + DingTalk verify ✅ |
| 2.5 | F-D78-245 (Servy "Running" ≠ functional) | 真根因=GUI 未启动, user GUI restart 后 broker reconnect 真已生效 ✅ |
| 3 | F-D78-289 (schtask 17h 0 runs) | demoted P0→P3, 五一 holiday false-positive |
| 4 | F-D78-257 (factor IC 1 月 gap) | fast_ic_recompute --core, MAX=2026-04-28 (节前最后交易日) ✅ |
| 5 | (emergency SOP) | docs/audit/2026_05_audit/emergency_sop_v1.md ✅ |
| 6 | (account truth log SOP) | docs/audit/account_truth_log.md ✅ |
| 7 | (STATUS_REPORT + PR push) | merged ✅ |

### 5-01~02 Sprint Close {{PR_COUNT}} PR merged

主线 = **Layer 2.1.7 chain — dv_ttm 4-28 100% NULL 真因诊断 + cascade 重算**

| Phase | Commit | 内容 |
|---|---|---|
| reconnaissance | `{{CHAIN_COMMIT_1}}` | dv_ttm 4-28 NULL 范围调查 |
| RC4 | `{{CHAIN_COMMIT_2}}` | 真因 verify = Tushare 非确定性回填 |
| A1 backfill | `{{CHAIN_COMMIT_3}}` | 4-28 单日 dv_ttm 重拉 |
| A1.1 | `{{CHAIN_COMMIT_4}}` | 中性化 cascade |
| A1.1.B | `{{CHAIN_COMMIT_5}}` | factor_values cascade, **variance 1→3487 distinct** |

附: **LL-100 reviewer kill chunked SOP** + **LL-101 audit cite 必 SQL verify** (PR #209 sediment, main HEAD `{{MAIN_HEAD}}`).

PR 列表 (5-01 ~ 5-02 真测): {{PR_LIST}}

**4-27/4-28 IC 仍 NULL** = forward horizon T+5 未到 (5-01~5-05 五一假期, T+5 自然落 5-08). 不需修.

### 5-02 双合并调查 + PR #209 真值订正 🆕

(以下 6 节内容同 v2 draft, 详细记录 trade_log 真值 18 / 4-29 emergency_close 17 fills / 4-30 GUI 1 笔 / PR #168 hook verify / WF 4 指标真定义 + 4 治理债 / sim-to-real gap finding / F-D78-291 候选 / LL-100 chunked SOP 真生效)

[CC 决议: 详细 6 节内容直接 verbatim 从下面 §B.2 复用, 替换占位真值]

### Backlog
[详 frontmatter description backlog 段]

### Session 起手 SOP
[详 frontmatter description SOP 段, 含 SOP-1/2/3]

### Git status (Session {{NEW_SESSION_NUM}} 末)

✅ main @ `{{MAIN_HEAD}}` (PR #209 merged 5-02 11:23Z)
- working tree: 待 sprint_state v3 apply PR commit

### Session {{NEW_SESSION_NUM}}+1 入口

**Step B (B1)**: WF 治理债 audit md sediment (4 指标真定义 + F-WF-1~4 + sim-to-real gap finding) + 真测 xtquant query_history_trades 4-30 真值 + 我审视 CC 3 空隙 verify (xtquant query / position_snapshot 决议 prerequisite / risk_event_log audit row scope).

---
```

### §B.2 详细 6 节内容 (CC verbatim 复用 + 替换占位)

(以下 6 节是 §B.1 详细版, CC 真测决议是否 inline 进 handoff section, 还是 reference 到 PR #209 audit md `{{F_D78_240_CORRECTION_PATH}}`. 推荐 reference 节省 sprint_state.md 体积, 但 audit chain 可追溯性更强 inline 全文.)

**6 节内容**:
1. CC 任务 A 真测 verdict: trade_log (a)/(b)/(c) **不存在** for trade_log backfill (sub-task 2.1.1 是单一决议)
2. CC 任务 1 SQL 真测真值 — F-D78-240 真值漂移 48.6% (cite 35→真值 18 详细对照)
3. CC 任务 2 PR #168 hook 真状态 ✅ (6 字段独立 verify)
4. CC 任务 B walk_forward 4 指标真定义 ✅ + 4 项治理债 🆕 (F-WF-1/2/3/4 候选)
5. 🔴 真重要 finding: sim-to-real gap 不被 WF 验证 (5 fold test 期最后=2026-04-10, 4-29 不在 fold 内, audit F-D78-85 真证据加深)
6. PR #209 sediment 列表: F-D78-240 订正 audit md / LL-101 / audit Phase 1 sub-md reference / 真讽刺自身实证 (47.4→48.6 4 处 fix) / LL-100 chunked SOP 真生效 (1 run 105s)

CC 真测决议 inline 全文 vs reference 到 audit md, 选其一.

---

## Part C: Apply 流程 (CC LL-059 9 步闭环)

```
1. CC pull branch `docs/sprint-state-{{NEW_SESSION_NUM}}-reconcile-v3` (CC 决议真 branch 名)
2. CC 真测 verify 上面真测验收清单 10 项 (任一不实 STOP 反问 user)
3. CC patch sprint_state.md:
   - 顶部 frontmatter: 现 line 3 description 改名 `{{ARCHIVED_KEY_NAME}}` (CC 真测决议命名风格), 加新 description (Part A, 占位全替换真值)
   - 第 1 个 ## section 之前插入新 ## Session {{NEW_SESSION_NUM}} 末 Handoff (Part B, 占位全替换真值)
   - yaml 验证: 现 yaml key 全保留 + 新增 1 archived key + 新 description 覆盖 line 3
4. CC LL-059 9 步闭环 + reviewer chunked SOP (LL-100 沿用) + AI self-merge
5. user 下次 session 起手时验证 SessionStart hook 显示新 description ✅
```

---

## 隐含假设 + STOP 触发

### 假设 (CC 必真测 verify)
- 假设 A: sprint_state.md 现 frontmatter line 3 description 真值 (head 真测)
- 假设 B: 现 yaml key 真清单 (grep 真测)
- 假设 C: 真 Session # sequential (推断 + line 3 真 Session # base)
- 假设 D: archived key 命名风格 (匹配现已存在 archive key)
- 假设 E: PR #209 真 merged + main HEAD 真值
- 假设 F: 5-01 ~ 5-02 真 PR 列表 + count
- 假设 G: Layer 2.1.7 chain 5 commit 真存在
- 假设 H: ll_unique_ids 真值
- 假设 I: F-D78-240 订正 audit md 真路径 (PR #209 sediment)
- 假设 J: LL-101 真行号 (PR #209 sediment)

### STOP 触发
- 红线 3 项漂移 → STOP (绝对)
- 任一假设 verify 失败 → 报告 differ 反问 user
- yaml patch 后 key 验证失败 → STOP
- 任何"我推断"未真测 → STOP, 不写进 sprint_state.md

---

**文档结束**.

**等用户 review**:
- ✅ OK → 起 CC v3 apply prompt (CC 真测决议 10 项占位真值后 patch sprint_state.md)
- ⚠️ 想改 → 你说哪
- ❌ 重做 → 说哪里错
