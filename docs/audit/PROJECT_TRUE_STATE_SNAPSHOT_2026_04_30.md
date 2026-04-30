# PROJECT TRUE STATE SNAPSHOT — 2026-04-30 ~20:00

**1-2 页 baseline**, 沿用 PROJECT_FULL_AUDIT_2026_04_30.md 整合结果. 真金 ops 状态 + sprint 进度 + 下一步路径 (Step 6/7/T1.4-7) + 防自动驾驶提示.

---

## §1 真金 ops 当前状态 (实测 ground truth)

| 维度 | 值 | 来源 |
|---|---|---|
| **xtquant 真账户** | 0 持仓 + cash ¥993,520.16 | PR #166 §2 (4-30 14:54 实测), PR #169 v4 hybrid (17 CC + 1 user GUI) |
| **DB position_snapshot** | 4-28 live = **0 行** ✅ (PR #171 DELETE 后) | PR #171 实测 |
| **DB cb_state.live.nav** | **¥993,520.16** ✅ (= ground truth, diff 0.00) | PR #171 UPDATE 后 |
| **risk_event_log audit chain** | id=`67beea84` (P0 silent_drift) + id=`e1598f37` (info gate cleanup) | PR #161 + PR #171 |
| **LIVE_TRADING_DISABLED 双锁** | True (config.py:44 default) | PR #170 c3 verifier ✅ |
| **DINGTALK_ALERTS_ENABLED 双锁** | False (config.py default-off) | PR #170 c3 helper ✅ |
| **EXECUTION_MODE** | paper (.env) | 沿用 |
| **Beat schedule 状态** | risk-daily-check / intraday-risk-check 注释 + Beat restart (4-30 15:35) | PR #150 + PR #161 |
| **Servy 4 服务** | ALL Running (FastAPI / Celery / CeleryBeat / QMTData) | 沿用 |
| **schtask 关键状态** | DailyExecute disabled / DailySignal disabled / DailyReconciliation disabled / IntradayMonitor disabled | 沿用 link-pause |
| **PT 重启 gate** | **7/7 PASS ✅** (T0-15/16/18/19 + F-D3A-1 + DB stale 清 + cb_state reset) | PR #170 + #171 |

**fail-secure 双锁守门**: LIVE_TRADING_DISABLED=true (broker 层硬阻 sell/buy) + DINGTALK_ALERTS_ENABLED=false (alert 层 default-off).

---

## §2 Sprint 进度 (D11/D12 路径回归)

| Step | 描述 | 状态 |
|---|---|---|
| Step 1-3 | (历史 sprint, 沿用) | ✅ |
| Step 4 | T1 sprint 链路停止 (PR #150) → D3 14 维全方位审计 (D3-A/B/C) → T0-19 修法 → 批 2 P0 修 → PT 重启 gate cleanup | ✅ (今日完结, PR #150 → #171) |
| **Step 5** | **PROJECT_FULL_AUDIT 整合 + PROJECT_TRUE_STATE_SNAPSHOT** | **✅ 本 PR** |
| Step 6 | 6+1 文档 + 铁律重构 ADR-021 + IRONLAWS.md 拆分 | 🟡 待启 (~1.5-2 day) |
| Step 7 | T1.3 架构研讨 18-20 决策 | 🟡 待启 (~1-2 day) |
| T1.4 | 现状修 (批 2.2/2.3/2.4 + Tier A LiteLLM 借鉴并行) | 🟡 待启 |
| T1.5 | 回测引入风控 2-3 周 Q3 闭环 | 🟡 待启 |
| T1.6 | 阈值扫参 | 🟡 待启 |
| T1.7 | PT 重启评估 (paper-mode 5d + cutover) | 🟡 待启 (~3-5 周后) |

---

## §3 关键数字 baseline (实测 2026-04-30)

| 数字 | 实测 | 来源 |
|---|---|---|
| factor_values 行数 | 840,478,083 | PR #164 (CLAUDE.md L48 sync) |
| factor_values 体积 | ~172 GB (TimescaleDB hypertable) | PR #164 |
| factor_ic_history 行数 | 145,894 | PR #164 |
| minute_bars 行数 | 190,885,634 (~36 GB) | PR #164 |
| klines_daily 行数 | 11,776,616 (~4 GB) | PR #164 |
| daily_basic 行数 | 11,681,799 (~3.7 GB) | PR #164 |
| pytest collected (backend/tests) | 4027 tests | D3-C F-D3C-1 实测 |
| pytest smoke (-m smoke) | 55 passed / 2 skipped / 1 deselected | PR #170 / #171 |
| LESSONS_LEARNED.md `## LL-NNN` 总数 | 91 (max LL-097) | 本 PR 实测 |
| LL 累计 同质 "假设必实测" | 31 | PR #171 沿用 |
| Tier 0 债 unique IDs | 18 (T0-1~T0-19, T0-13 未占用) | 本 PR 实测 |
| Tier 0 债剩余未修 | 11 (PR #170 c4 + PR #170 c5 + PR #166 v3 + PR #170 c2 + PR #168 关闭 5 项 + PR #171 关 2 项 = 7 关闭, 18-7=11) | 本 PR 实测 |
| STATUS_REPORT 散落数 | 20 (本 PR Step 5 整合目标) | 本 PR 实测 |
| 今日 PR 链 (2026-04-30) | 18 (#155-#171 + 本 PR) | 本 PR 实测 |
| QPB 版本 | v1.16 | PR #164 sync |
| CLAUDE.md 铁律段 | 44 条 (v4 2026-04-30, PR #170 c2 加 X9) | PR #170 |

---

## §4 下一步路径 (Step 6 → 7 → T1.4-7, ~3-5 周)

### Step 6 — 6+1 文档 + 铁律重构 ADR-021 + IRONLAWS.md 拆分 (~1.5-2 day)

- 6 主文档梳理 (CLAUDE.md / SYSTEM_RUNBOOK / DEV_*.md / etc) 整合 D3 14 维 finding
- 铁律重构 ADR-021 (44 条 → tier 化分类)
- IRONLAWS.md 拆出 CLAUDE.md inline (新独立文件, 沿用 D3-C F-D3C-12 建议)
- 沿用 LL-097 (X9) 完成 schedule/config 治理一致性
- 8 D2 untracked audit docs 处理 (留本 Step 决议)

### Step 7 — T1.3 架构研讨 18-20 决策 (~1-2 day)

- 沿用本 audit §6 批 2 scope 调整建议
- 18-20 项架构决策 (具体 enumerate 留 Step 7 prompt)
- 与 LiteLLM Tier A 借鉴并行评估

### T1.4 — 现状修 (批 2.2/2.3/2.4 + Tier A LiteLLM 借鉴并行)

- 批 2.2: Servy 依赖图 + 监控告警整合
- 批 2.3: 测试覆盖度 (pytest config drift / smoke / contract)
- 批 2.4: 性能/资源 (Redis maxmemory / DB / Wave 5+ secret manager)

### T1.5 — 回测引入风控 2-3 周 Q3 闭环

### T1.6 — 阈值扫参

### T1.7 — PT 重启评估 (paper-mode 5d + cutover)

只有走完 Step 5 → 6 → 7 → T1.4 → T1.5 → T1.6 后, 才到 T1.7. **paper-mode 5d 是 T1.7 子步骤, 不是 Step 5/6 后立即触发**.

---

## §5 防自动驾驶提示 (Gate 7/7 ≠ paper-mode 5d 启动条件)

⚠️ **PT 重启 gate 7/7 PASS = 必要条件, 不充分**.

### 不允许立即触发:
- ❌ paper-mode 5d dry-run 启动
- ❌ Servy schtask Disabled → Auto 切换
- ❌ Beat schedule 注释解除 + restart (沿用铁律 X9, schedule 改后必 ops checklist)
- ❌ `.env paper→live` cutover
- ❌ /schedule agent 自动追踪 paper-mode

### 必须先完成:
- ✅ Step 5 PROJECT_FULL_AUDIT 整合 (本 PR)
- 🟡 Step 6 6+1 文档 + 铁律重构 ADR-021 + IRONLAWS.md 拆分
- 🟡 Step 7 T1.3 架构研讨 18-20 决策
- 🟡 T1.4 现状修
- 🟡 T1.5 回测引入风控
- 🟡 T1.6 阈值扫参
- 🟡 T1.7 PT 重启评估 (含 paper-mode 5d 作为子步骤)

### 自动驾驶反例 (本 sprint 已踩 + 修正)

- 4-30 ~19:30: PR #171 末尾 Claude offer "/schedule agent in 3 days verify PT gate state still 7/7" — **user 4-30 修正撤回**, 沿用 D11/D12 路径强制走 Step 5/6/7 路径
- AI 自动驾驶倾向: cutover-bias (Claude prompt 设计层默认 forward-progress, 跳过整合阶段). 沿用 LL-093 (forensic 5 类源) + LL-095 (status=57 真因综合) + LL-096 (forensic 修订不可一次性) 加强守门

---

## §6 user 决议时点

本 PR 完结后, **CC STOP, 等 user 启 Step 6 prompt**. 不预设 Step 6 内容.

如 user 不启 Step 6, **不主动建议**, **不 schedule agent**, **不 cutover**.

---

## §7 关联

- [PROJECT_FULL_AUDIT_2026_04_30](PROJECT_FULL_AUDIT_2026_04_30.md) (本 PR 文件 1, 详细整合)
- [SHUTDOWN_NOTICE_2026_04_30](SHUTDOWN_NOTICE_2026_04_30.md) §6 v4 + §11 v3 修订 + §12 v4 修订
- [PT_restart_gate_cleanup_2026_04_30](PT_restart_gate_cleanup_2026_04_30.md) (PR #171)
- check_pt_restart_gate.py (verifier 7/7 PASS)
