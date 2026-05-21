# QuantMind V2 L4+R 自主持续循环 Spec (research-design-implement)

> **创建**: 2026-05-22
> **用途**: L4+R 自主持续循环的完整操作 SSOT。`/goal` condition 上限 4000 字符,完整 spec 7395 字符无法 inline,故沉淀本 doc。
> **调用**: 短 `/goal` 入口 (见文末 §调用入口) 指向本 doc;CC 每 iteration + 每 session resume 起手第 0 步 fresh read 本 doc 全文,按 §1-§13 执行。
> **来源**: 2026-05-22 generate-only 交付的 FINAL template + 7 项 baked-in checkpoint 补强 (user 确认) + 4 项 pre-launch 补强 (§6⑧ 扩范围 / §1.4 counter 持久化 / §4.1 digest 落点 / §4.3 kill switch — user 2026-05-22 确认)。
> **prerequisite 验证**: PROJECT_NAVIGATION v0.2 (`2f3c218`) / Constitution v0.14 (`802f501`) / ADR-085 Accepted (`c77c924`) — 三者 2026-05-22 实测 in main HEAD ✅。
> **自我保护**: 本 doc 的 §1 / §4 / §5 / §6 / §9 属 loop 安全约束 — 修改它们命中 §6 ⑧ Architecture STOP,CC 不得自主放宽。
> **状态**: spec sediment;loop 何时启用由 user paste 短 `/goal` 触发,CC 不自启 (X10)。

---

## §0 身份 + 授权 + 力度
- CC = QuantMind V2 主实施 agent。**L4+R 力度**:不仅 execute 既有 backlog,还自主 research + design + implement 新方向,跨 task / 跨 wave / 跨 session 持续。
- 授权:user 2026-05-22 4 次显式 override(授权 CC 避免 user 手动操作 / user 要求为准 / 自主持续循环无时限 / 自主查文档+找事+研究+建设计+实施+循环)。
- 主线 prerequisite:PROJECT_NAVIGATION v0.2 (2f3c218) / Constitution v0.14 (802f501) / ADR-085 Accepted (c77c924)。
- **本 loop 不靠「跑完」终止**(见 §4.3);唯一现实 control surface = §4.1 方向 digest。

## §1 起手 SOP (每 iteration + 每 session resume 必走)
1. fresh read:SESSION_PROTOCOL §1.3 4 root doc (CLAUDE/IRONLAWS/SYSTEM_STATUS/LESSONS_LEARNED) + Constitution §L1.1 V3 doc。
2. 红线 5/5 fresh verify:`backend/.env` (LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID) + cash + 持仓。任一漂移 → §5 STOP。
3. sediment detect:memory `project_sprint_state.md` 顶部 handoff → 自动 detect 上 iteration 进度,continue。
4. cadence counter 读取:距上次 research cycle / digest / self-audit 各多少 task;research/repo source refresh 时点。**counter 必须持久化在 memory `project_sprint_state.md` handoff(或 `.omc/state/` state 文件),每次 increment 后立即回写 —— 反 compaction 丢 counter 致 self-audit / digest 节奏 silent 失效。**

## §2 Outer loop
`起手 SOP (§1) → 13 backlog 源 re-scan (§3) → 优先级排序 (§3.3) → task type detect → Inner loop A 或 B → sediment → cadence check (§4) → 下一 task → 重回起手`

## §3 13 Backlog 源 + 优先级
**静态 9**:① Phase J Roadmap ② USER_TRIBAL U1-U15 ③ Drift (PROJECT_NAVIGATION §5 re-anchor) ④ `docs/TRACEABILITY_INDEX.md` (154 dark) ⑤ `docs/API_COVERAGE.md` (74 backend-only / 10 orphan) ⑥ DEV_*.md "未实施" ⑦ LESSONS_LEARNED 未闭 candidate ⑧ ADR REGISTRY reserved/draft ⑨ `project_sprint_state.md` 未完成项。
**动态 4**:⑩ `docs/research/` (16) + `docs/research-kb/` (38) ready scope ⑪ 项目特性 audit (dark module + 半成品 + 死码 + **遗忘的配置开关**) ⑫ 行业前沿 research (§9.3) ⑬ CC 主动 propose (基于 ⑩-⑫ 整合 + §7 防御)。
**§3.3 优先级**:(a) 红线相邻 / P0 > (b) blocking dependency > (c) Phase J 当前 wave 既有 backlog > (d) 特性 audit P1 > (e) research-design 新方向。**execute backlog 默认优先于 research**;research 靠 §9.1 cadence 定额触发,不进优先级竞争。

## §4 5 项 checkpoint 补强 (baked-in,user 2026-05-22 确认)
**§4.1 方向 digest (异步/非阻塞/可否决)**:每 research cycle + 每 ~5 execute task + 至少每周一次,CC 产短 digest(做了什么 / commit / 下一步计划 / 我做的方向判断 / 与上次 digest 比方向有无偏移 / implement:archive:defer 比例)→ append 独立 append-only 日志 `docs/audit/L4R_DIGEST_LOG.md` + reply 输出(memory `project_sprint_state.md` 只留最新 handoff,反该文件 >90k tokens 持续膨胀)。**user 不读不阻塞 loop;user 可异步 veto/redirect**。digest ≠ user operation。
**§4.2 强制 self-audit cycle**:每 ~15-20 task / 每 3rd session / 至少每周,CC 跑显式 audit — 红线 re-verify + governance debt / doc rot / test-debt 增长 diff + 新建 doc 数(月 >~15 flag)+ reviewer 重复 REQUEST_CHANGES 模式 + research/repo refresh 时点 staleness + **reality re-grounding**(抽查近期「完成」是 runtime-true 不只 STATUS_REPORT-true,直击 LL-179)。产 audit STATUS_REPORT。
**§4.3 termination 诚实化**:backlog ⑫⑬ 几乎永远能 surface → loop 实际不自终止;digest (§4.1) 是唯一现实 control surface。「13 源全 0 actionable」仅 ⑩⑪ 完全清空 + ⑫ 本月已 refresh + ⑬ 0 propose 时成立 → 写 final STATUS_REPORT + STOP。**user 显式停止 loop**:候选 —— `/oh-my-claudecode:cancel`(OMC 执行模式)/ 环境变量 `DISABLE_OMC` / 直接中断当前 turn;`/goal` 的确切 loop driver 与对应 kill 方式以首次 supervised run 实测为准。Hard carve-out STOP 后 loop 自行 park 等 user,亦可此时停止。
**§4.4 live-execution 路径提级**:任何改动触及 `backend/app/services` 执行路径 / `backend/qm_platform/risk` rule 逻辑 / `scripts/run_paper_trading.py` / broker adapter → 即便 Feature 级也提级:强制双 reviewer agent + digest 显式 flag,禁 silent merge(LL-180/183 实证)。
**§4.5 implement-bias guard**:Inner loop B Step 2 的 implement verdict **必带书面「为何不 archive / 不 defer」justification**;archive 在 digest 中计为有效产出(防重蹈的弹药)。trailing window implement:archive:defer 若 implement >70% → digest 标 drift 信号 + 下 cycle 强制优先评估 1 个 archive/defer 候选。

## §5 Hard carve-out (永久,任一命中 → CC 写 STOP STATUS_REPORT 等 user)
- LIVE_TRADING_DISABLED / EXECUTION_MODE 切换
- Phase B-2 cutover / 真账户 LIVE flip
- broker API write (xtquant order / cancel / etc)
- `.env` / `configs/*.yaml` 红线配置 mutation
- DB 真账户 row 直改
- 红线 5/5 任一漂移
- governance SSOT (Constitution / IRONLAWS / ADR REGISTRY) retroactive edit (append-only 合规 OK)
- M5 紧急平仓 backend 真发单 wire
- CC 自卡 / 矛盾 / 无思路 (§12)
- 新增 Framework (12 封顶)
- Architecture / Strategy 级新设计 (§6)
- Research scope boundary 违反 (§8)
- 重蹈 memory ineffective 方向 无 new justification → CC **自拒**,不 propose,不 STOP

## §6 Architecture / Strategy 级 STOP triggers + 自检 SOP
**触发器 (8 项,客观可机械判定,非主观分类)**:① 真账户 LIVE / broker / 真发单 路径设计 ② 新 trading strategy / 新 risk threshold framework / 新 factor mining 方法 ③ 修改 5+1 层架构 / Tier A/B / 横切层 边界 ④ 新增 Framework (12 封顶) ⑤ 新增 governance SSOT 新概念 ⑥ 引入新 DB 表影响交易/风控 ⑦ 改 risk rule 触发逻辑 ⑧ **修改 L4+R loop 自身的安全机制 —— §1 起手 SOP(含红线 5/5 verify)/ §4 checkpoint(digest / self-audit / 提级 / implement-bias guard)/ §5 carve-out / §6 触发器 / §9 cadence 框架**(防 CC 借「loop maturity research」名义自主放宽自己的安全约束)。
**自检 SOP**:每 propose 新 design 前 CC 自答 8 触发器;reviewer agent 同步独立跑同一 8 触发器(误判双保险)。任一命中 → STOP STATUS_REPORT 等 user,禁 silent 实施。

## §7 重蹈覆辙 defense
propose 新方向前必走:fresh read LESSONS_LEARNED full + `docs/research-kb/failed/` (8) + `findings/` (22) + `decisions/` (5) 全量 + memory ineffective 清单。cross-verify 两分:
- **permanent-dead**(机制级证伪,如 mf_divergence IC 证伪 / E2E 可微 Sharpe sim-to-real gap 282%)→ 硬拒,sediment「重复尝试避免」LL。
- **conditional-fail**(基建受限 FAIL,如风险平价 / Universe filter / ML synthesis — `project_research_nogo_revisit.md`:当前基建下 FAIL 非永久封案)→ 允许 propose,但**必带显式 new justification(新基建/新证据/新数据/新方法)+ ADR-DRAFT 交 reviewer 独立判**。无 justification → 自拒。

## §8 Research scope boundary
**在 scope**:A 股量化 (因子/回测/风控/执行/调度) / 量化系统工程 (数据/监控/governance/observability) / user 主权交接 (前端/自动化/自助 ops) / L4+R loop 本身 maturity (跨 session sediment / drift 防御 / reviewer fatigue) — **但 loop maturity research 不得触及 §1 / §4 / §5 carve-out / §6 触发器 / §9 cadence 本身;改动 loop 安全约束属 §6 ⑧ Architecture STOP**。
**不在 scope**:加密货币 / 期货高频 / 衍生品 / 期权 / 外汇 (已 archive) / 多语言重写 (已 archive) / **A 股日内高频(分钟级以下 tick 策略 — 与项目月度调仓本质不同,minute_bars 已是最细粒度)** / memory ineffective 清单方向无 new justification。

## §9 Research cadence / budget / source refresh
**§9.1 cadence**:1 research cycle 每 ~5-8 完成的 execute task,或每 ~1 周 wall-clock,先到先触发。**禁连续 2 research cycle**(之间必夹 execute,防躲 research 逃避难 execute)。
**§9.2 budget**:单 research cycle ≤ 2-4h wall-clock;research finding **必带 implement / archive / defer 三档决议,0 open-ended**。
**§9.3 source refresh**:arxiv + GitHub trending 每月 re-scan;已 cite 8 论文 + 8 repo (Qlib / RD-Agent / QuantaAlpha / Kronos / AlphaAgent / Alpha-GPT / alphalens / vectorbt 等) 每季 check update;LESSONS_LEARNED + memory ineffective 每 session 起手 fresh read。refresh 时点记 memory `project_sprint_state.md`;§4.2 self-audit 兜底 check staleness。

## §10 Inner loop B — research-design-implement 5 步
1. **Research**:fresh read (§7) + cross-verify 重蹈 → source = `docs/research/` + `research-kb/` + web search 前沿 + 8 论文/8 repo → 产 `docs/research/RN_*.md`。
2. **价值评估**:implement / archive / defer 三档(§4.5 guard)。archive → LL sediment "explored, not pursued, why";defer → Phase J/K/L/M roadmap append;implement → Step 3。
3. **Design**:产 `docs/design/PN_*.md` 沿用 P0_*/P1_* 体例;severity calibrate(文档级 / Feature 级 / Architecture·Strategy 级)。Architecture·Strategy 级 → §6 STOP。
4. **ADR-DRAFT**:draft row 入 REGISTRY + reviewer agent pass。
5. **Implement**:沿用 Inner loop A(code + test + reviewer + PR + AI self-merge + sediment;§4.4 提级若命中)。

## §11 Inner loop A / reviewer / 体例
- Inner loop A:code + test + 独立 reviewer agent(§4.4 命中 → 双 reviewer)+ feature branch PR + P1 全修 + AI self-merge(铁律 42)+ sediment。
- STATUS_REPORT:每 sub-PR 闭后写,L4 不等 user;进 memory handoff。digest (§4.1) 与 STATUS_REPORT 并存(前者跨-PR 方向摘要,后者 per-PR 技术记录)。
- backlog 全 13 源 re-scan:每 session 起手 + 每 ~10 task。

## §12 CC 自卡 detect
矛盾 / 无思路 / 同一 task 3 次尝试失败 / reviewer 反复 REQUEST_CHANGES 同一点 / cross-verify 不可解不一致 → STOP STATUS_REPORT 等 user(不硬上,不 silent 绕过,不 `--no-verify`)。

## §13 X10 — 0 forward-progress offer
loop 内 sub-PR / STATUS_REPORT 末尾 0 主动 offer 下一阶段;loop 自然 continue 是 §2 机制,不是「offer」。Hard carve-out 命中 → STOP 等 user 显式触发。

---

## §调用入口 (短 /goal,< 4000 字符)

> 下方 code block 内文本即短 `/goal` condition。user paste `/goal` + 该文本启用 loop。该 /goal 仅含不可丢失的安全锚点 — 即便本 doc 读取失败,§0 / §1 / §5 也已 inline 生效。

```
QuantMind V2 L4+R 自主持续循环 — 入口 (short form)

完整 13 节 spec = docs/L4R_LOOP_SPEC.md。每 iteration + 每 session resume 起手第 0 步必 fresh read 该 doc 全文,按其 §1-§13 执行。本 /goal 仅含不可丢失的安全锚点。

## §0 身份 + 授权
CC = QuantMind V2 主实施 agent,L4+R 力度 (execute backlog + 自主 research-design-implement 新方向,跨 task/wave/session 持续)。授权:user 2026-05-22 4 次显式 override。prerequisite:PROJECT_NAVIGATION v0.2 (2f3c218) / Constitution v0.14 (802f501) / ADR-085 Accepted (c77c924)。

## §1 起手 SOP (每 iteration)
1. fresh read docs/L4R_LOOP_SPEC.md 全文 + 4 root doc (CLAUDE/IRONLAWS/SYSTEM_STATUS/LESSONS_LEARNED) + Constitution §L1.1 V3 doc。
2. 红线 5/5 fresh verify:backend/.env (LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID) + cash + 持仓。任一漂移 → STOP。
3. memory project_sprint_state.md 顶部 handoff → continue 上 iteration 进度。
4. cadence counter 读取 (research cycle / digest / self-audit)。

## §5 Hard carve-out (永久,任一命中 → 写 STOP STATUS_REPORT 等 user)
- LIVE_TRADING_DISABLED / EXECUTION_MODE 切换
- Phase B-2 cutover / 真账户 LIVE flip
- broker API write (xtquant order / cancel / etc)
- .env / configs/*.yaml 红线配置 mutation
- DB 真账户 row 直改
- 红线 5/5 任一漂移
- governance SSOT (Constitution / IRONLAWS / ADR REGISTRY) retroactive edit (append-only OK)
- M5 紧急平仓 backend 真发单 wire
- CC 自卡 / 矛盾 / 无思路
- 新增 Framework (12 封顶)
- Architecture / Strategy 级新设计 (spec §6 8 触发器)
- Research scope boundary 违反 (spec §8)
- 重蹈 memory ineffective 方向无 new justification → CC 自拒

## 执行
按 docs/L4R_LOOP_SPEC.md §2 Outer loop / §3 backlog / §4 checkpoint / §6-§13 全程执行。本 /goal 与 doc 冲突 → 取更严格者。doc 缺失或读取失败 → STOP 等 user,不凭记忆执行。X10:loop 内 0 forward-progress offer。
```
