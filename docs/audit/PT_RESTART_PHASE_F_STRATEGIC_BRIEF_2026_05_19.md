# PT 重启战略 brief (Phase F) — 2026-05-19 Session 58+1

> **目的**: 用户已选 "PT 重启战略讨论 (Phase F)". 本 doc 是 CC 整合 V3 §20.1 设计层 10/10 已决议 + ADR-027/028 现状 + 真值 schtask/Beat/env state, 输出可执行 decision tree + 真 trigger 路径. NOT autonomous execution — 等 user 显式 trigger.
>
> **Author**: CC (Session 58+1) | **Date**: 2026-05-19 evening SH | **Status**: AWAITING USER DECISION
>
> **铁律 backref**: X10 (CC 不抢跑) / 35 (.env secrets) / 27 (真账户保护) / 42 (PR + reviewer)

---

## §0 TL;DR (3 句话)

1. **真 gate 是 schtask `QuantMind_DailyExecute` = `Disabled`** (不是 `.env`). `.env=live` 已 armed 3+ weeks, broker enabled, 但 schtask 关闭 → 4-30 起 19 天 0 broker call sustained.
2. **重启 trigger = 单步**: `Enable-ScheduledTask -TaskName QuantMind_DailyExecute` (启用后下一 09:31 SH 工作日 fire 第一笔执行).
3. **决议树**: 走 (A) full restart Mon 5-25 / (B) staged 5d paper-dry-run 验证 / (C) 暂不重启留 Phase J 研究. CC 推荐 **(B)**, 因 ADR-027 §2.1 短期 prerequisite #4 "paper-mode 5d validated" 未完成.

---

## §1 现状真值 (Session 58+1 cold-verified)

### §1.1 .env 真值 (`backend/.env`)

```
EXECUTION_MODE=live                # cutover 5-15~5-17 (operator authorized)
LIVE_TRADING_DISABLED=false        # broker enabled (post-CT-2b)
DINGTALK_ALERTS_ENABLED=true       # flip 5-17 22:48 (PR sustained)
PT_TOP_N=5                         # 灰度 5 股 (5-18 backup logs/.env-backup-pre-pt-top-n-5-2026-05-18.bak)
PT_INDUSTRY_CAP=1.0                # 不限行业
PT_SIZE_NEUTRAL_BETA=0.50          # Step 6-H Partial SN
ADMIN_TOKEN=<set>                  # auth gate active
6 news source API keys             # 全 set
```

**注**: LL-188 Forensic (commit `4d37df0`) 已 sediment — sediment 层 claim "EXECUTION_MODE=paper" 3+ weeks drift, 但**代码层 .env 真值是 live**. Session 58 P0 ticking bomb (round-2 startup guard) 已 defuse (commit `c01817b` 3-factor advisory).

### §1.2 Windows Task Scheduler 状态 (PowerShell verified)

| 任务名 | 状态 | 触发 cron | 备注 |
|---|---|---|---|
| **QuantMind_DailyExecute** | **🔴 Disabled** | 09:31 工作日 | **PT restart 真 gate** |
| QuantMind_DailySignal | 🟢 Ready | 16:30 工作日 | signal 生成 (T 日盘后) |
| QuantMind_CancelStaleOrders | 🔴 Disabled | — | cancel 兜底 |
| QuantMind_DailyDataIngest_Preopen | 🔴 Disabled | 早盘前 | 数据 ingest preopen |
| QuantMind_DailyDataIngest_Postclose | 🔴 Disabled | 盘后 | 数据 ingest postclose |
| QM-SmokeTest | 🔴 Disabled | — | 冒烟测试 |
| QM-HealthCheck | 🟢 Ready | 16:25 | 健康预检 |
| QuantMind_PT_Watchdog | 🟢 Ready | — | PT 看门狗 |
| QuantMind_PTAudit | 🟢 Ready | 17:35 | PT audit |
| QuantMind_DailyReconciliation | 🟢 Ready | 15:40 | 对账 |
| QuantMind_DailyIC | 🟢 Ready | 18:00 | IC 增量入库 |
| QuantMind_IcRolling | 🟢 Ready | 18:15 | IC rolling |
| QuantMind_DailyMoneyflow | 🟢 Ready | 17:30 | moneyflow ingest |
| QuantMind_DataQualityCheck | 🟢 Ready | 17:45 | 数据质量 |
| QuantMind_LLMCostDaily | 🟢 Ready | — | LLM cost 日报 |
| QuantMind_VacuumAnalyze | 🟢 Ready | 周六 03:00 | DB VACUUM |
| QuantMind_RiskFrameworkHealth | 🟢 Ready | — | 风控健康 |
| QuantMind_IntradayMonitor | 🟢 Ready | 盘中 | 单股急跌告警 |
| QuantMind_FactorHealthDaily | 🟢 Ready | — | 因子健康日 |
| QuantMind_MiniQMT_AutoStart | 🟢 Ready | 08:50 | miniQMT 启动 |
| QuantMind_ServicesHealthCheck | 🟢 Ready | — | Servy 健康 |
| QuantMind_MVP31SunsetMonitor | 🟢 Ready | — | MVP 3.1 sunset |
| QM-DailyBackup | 🟢 Ready | — | DB backup |
| QM-ICMonitor | 🟢 Ready | — | IC 监控 |
| QM-LogRotate | 🟢 Ready | — | 日志轮转 |
| QM-PTDailySummary | 🟢 Ready | — | PT 日报 |
| QM-RollingWF | 🟢 Ready | — | rolling WF |

**关键观察 (LL-188 + §1.2 综合)**:
- ✅ `DailyExecute = Disabled` → broker call 0 路径 (4-30 起 19 天 sustained)
- ✅ `DailySignal = Ready` → signal 16:30 生成 sustained (但无 execute 消费 → signals 表 stale 累积)
- ✅ 监控/审计/对账/IC 全链路 Ready → restart 后立刻有 observability
- ⚠️ 数据 ingest preopen/postclose Disabled (历史决议: 由 16:35 DailyMoneyflow 17:30 替代 + Beat news 6x daily, sustained 体例)

### §1.3 Celery Beat 状态 (Servy QuantMind-CeleryBeat Running)

**22 Beat schedule entries 全 active** (5-18 14:11 SH 后 post M3 broker_qmt asyncio bootstrap fix 重启):

| Beat task | cron | 用途 |
|---|---|---|
| outbox-publisher-tick | 30s | event_outbox → Redis Streams |
| risk-l4-sweep-1min | 1min trading hrs | L4 STAGED PENDING_CONFIRM expired sweep |
| risk-l4-broker-stuck-sweep | 5min all hrs | broker plan stuck retry |
| risk-dynamic-threshold-5min | 5min trading hrs | DynamicThresholdEngine compute |
| meta-monitor-tick | 5min | 元告警 (7 rules, alert-on-alert) |
| risk-market-regime-0900/1430/1600 | 3 daily | Bull/Bear regime detection |
| risk-reflector-weekly | 周日 19:00 | L5 RiskReflector 5 维反思 |
| risk-reflector-monthly | 月 1 日 09:00 | L5 RiskReflector 月度 |
| risk-metrics-daily-extract-16-30 | 16:30 | 日 metrics 抽取 |
| daily-quality-report | 17:40 | 数据质量日报 |
| factor-lifecycle-weekly | 周五 19:00 | 因子 lifecycle |
| news-ingest-5-source-cadence | 4hr × 6 | 5 源新闻 ingest |
| news-ingest-rsshub-cadence | 4hr × 6 | RSSHub 独立 caller |
| announcement-ingest-trading-hours | 5 daily | cninfo 公告流 |
| fundamental-context-daily-1600 | 16:00 | 基本面 context |
| gp-weekly-mining | 周日 22:00 | GP 因子挖掘 |

**重要**: Beat 22 entries ARE FIRING. 这意味着 PT 重启**不需要**额外启动任何 Beat — 风控/反思/regime/news/factor lifecycle 全在 run. user 重启 PT = enable `QuantMind_DailyExecute` 即可.

### §1.4 DB真值 (LL-188 forensic + STATUS_REPORT 5-18 evening)

- trade_log: 17 rows total, 全部 4-29 emergency_close, 4-30 → 5-19 (19 days) **0 new rows**
- position_snapshot: empty (verified Session 58 round-1)
- cash: ¥993,520.66 (QMT xtquant query 5-19 cold check)
- risk_event_log: PR #212 sediment row (audit, not real fire)
- execution_plans: 0 new since 4-30 (DailyExecute disabled)

### §1.5 V3 §20.1 设计层 10/10 已决议 (Session 49 5-02 sprint close)

| # | 决议 | ADR |
|---|---|---|
| #1 | L4 STAGED default + 反向决策权 | ADR-027 §2.1 |
| #2 | 跌停 fallback (V3 §7.2) | ADR-027 §2.3 |
| #3 | BGE-M3 1024 维 RAG embedding | ADR-028 §2.3 |
| #4 | V4-Pro 月度复盘 cadence | ADR-028 §2.2 |
| #5 | AUTO 5 prerequisite | ADR-028 §1.2 |
| #6 | LLM 预算 $50/月 + 80% warn / Ollama fallback | ADR-028 §3.3 |
| #7 | user 离线 STAGED 30min → execute | ADR-027 §2.2 |
| #8 | L4 batched 平仓 batch interval (5min/1min) | ADR-027 §2.3 |
| #9 | L5 lesson 入 RAG 自动度 (c) | ADR-028 §2.5 |
| #10 | DingTalk + 钉钉 keyword 'xin' wire | DINGTALK_ALERTS_ENABLED=true (5-17 flip) |

✅ 全 10/10 设计层 settled. **未实施**:
- ADR-027 §2.1 STAGED **代码 implement** (.env `STAGED_ENABLED=false` default, 短期 path) — 检 grep 是否 wired
- ADR-028 §2 AUTO + RAG + backtest replay — Sprint M+1~N 长期 path, 短期不开发

---

## §2 ADR-027/028 5+5 prerequisite 真值 verify

### §2.1 ADR-027 STAGED 短期 → 长期 5 prerequisite

| # | Prerequisite | 真值 status | Evidence |
|---|---|---|---|
| 1 | LIVE_TRADING_DISABLED guard reconcile | ⚠️ partial | .env=false (5-15 flip), but app-layer guard 仍 wired |
| 2 | 跌停 fallback implement (4-29 case) | ❓ unknown | 需 grep V3 §7.2 broker layer wire |
| 3 | SOP-6 真生产下单 fail-safe sediment | ❓ pending | 沿用 LL-103 Part 2 SOP-5 体例 |
| 4 | **paper-mode 5d validated** | **🔴 NOT DONE** | LL-183 5-18 阻 paper-mode 5d (silent NOT-GATING bug fixed via PR/commit `355b813`) |
| 5 | user 显式 .env governance + commit | ✅ done (5-15) | .env=live operator authorized (no CC PR) |

**结论**: 5/5 中 1 partial + 1 unknown + 1 pending + 1 not-done + 1 done = **不满足长期 STAGED default = STAGED 启用条件**. 短期 default = OFF 路径 (即 .env `STAGED_ENABLED=false`) 沿用.

### §2.2 ADR-028 AUTO 5 prerequisite (在 ADR-027 5 完成基础上 extension)

| # | Prerequisite | 真值 status |
|---|---|---|
| 1 | STAGED 真实运行 ≥ 1 个月 0 事件 | 🔴 NOT STARTED (STAGED 未 deploy) |
| 2 | paper-mode 5d validated | 🔴 NOT DONE |
| 3 | SOP-6 sediment 完成 | ❓ pending |
| 4 | Crisis regime detection 3 互锁指标 + V4-Pro X 阈值 + RAG | 🔴 NOT IMPLEMENTED |
| 5 | user 显式 .env 双启用 (`AUTO_ENABLED=true`) | 🔴 NOT DONE |

**结论**: AUTO 是 Sprint M+1~N 长期路径, **当前 Sprint 1~M 期不在 scope**. 重启决议不涉及 AUTO.

---

## §3 PT 重启 3 路径 (Decision Tree)

### §3.1 路径 A: Full Restart Mon 5-25 (aggressive)

**Trigger**:
```powershell
Enable-ScheduledTask -TaskName QuantMind_DailyExecute
Enable-ScheduledTask -TaskName QuantMind_CancelStaleOrders  # 兜底
# (optional) Enable QM-SmokeTest preview verify
```

**第一笔执行**: 5-25 Mon 09:31 SH

**前置 (5-22 Fri 前):**
- ✅ Servy 4 服务确认 Running (Beat / Worker / FastAPI / QMTData)
- ✅ 5-22 Fri 16:30 DailySignal 真值生成 + signals 表写入 verify
- ✅ user 显式 commit signal off PR (e.g. ADR-085 PT-restart-Mon-5-25 cite)
- ✅ Mon 09:30 SH SI HealthCheck 16:25 Fri 已 PASS

**风险**:
- ADR-027 5 prerequisite #4 paper-mode 5d **未完成** — sim-to-real gap unverified (LL-183 残留 risk)
- LL-182 QMT 5-axis fix (5-18) **真 long-run verify** 0 — 首日重启即 long-run 起点
- 4-29 cleanup 后第一笔真生产 — psychological surface area 高
- 灰度 PT_TOP_N=5 (5 股) 已 5-18 调灰度, 暴露 5 × ~¥200k = ~¥1M positional risk 上限 (V3 §X 灰度 ≤ 30% 资金)

**优**:
- 0 额外 prep effort
- LL-182 在真生产 5-10 day 直接 long-run verify
- ADR-027 短期 path (default=OFF) 沿用, STAGED 代码 implement defer 长期 Sprint M

**适合**: user 决议 "已等够 3+ weeks, 5/5 红线 sustained 19 天 → 重启" + LL-188 sediment drift 已 surfaced + 0 broker call sustained 验证 schtask gate 真有效 + 接受 LL-182/183 残留 risk 用 5 股灰度兜底.

### §3.2 路径 B: Staged Paper-Mode 5d Dry-Run → Live Restart (CC 推荐)

**Phase B-1 (5-20 Tue ~ 5-26 Mon, 5 trading days)**: paper-mode dry-run
```powershell
# Step 1: 临时 flip .env back to paper (backup pre-flip)
Copy-Item backend/.env logs/.env-backup-pre-paper-dryrun-2026-05-20.bak
# Edit backend/.env:
#   EXECUTION_MODE=paper
#   LIVE_TRADING_DISABLED=true
# Step 2: Restart Servy 4 services
powershell -File scripts/service_manager.ps1 restart all
# Step 3: Enable DailyExecute (paper mode → 0 broker call 但走完整路径)
Enable-ScheduledTask -TaskName QuantMind_DailyExecute
Enable-ScheduledTask -TaskName QuantMind_CancelStaleOrders
# Step 4: 5 trading days 5-20 Tue → 5-26 Mon 观察:
#   - signals 表每日 16:30 update
#   - execution_plans 每日 09:31 paper-mode 写入 (但 broker_qmt 走 paper adapter)
#   - risk_event_log 0 incident
#   - meta_monitor_tick 0 P0 alert
#   - LL-183 regression gate 真生产 path verify
```

**Phase B-2 (5-27 Wed)**: 验证 paper-mode 5d → flip live
```powershell
# Step 5: paper-mode 5d 验证 PASS 后
Copy-Item backend/.env logs/.env-backup-pre-live-restart-2026-05-27.bak
# Edit backend/.env:
#   EXECUTION_MODE=live
#   LIVE_TRADING_DISABLED=false
# Step 6: Restart Servy
powershell -File scripts/service_manager.ps1 restart all
# Step 7: 5-27 Wed 09:31 第一笔 live execute
```

**前置**:
- ✅ 同 路径 A 前置
- ✅ paper-mode 5d 真实跑 + 0 incident verify

**风险**:
- 多 5 天等待
- paper-mode → live flip 期间 1 trading day 0 fire window
- (低) paper-mode broker adapter wire 漂移 — 但 PR #210 sim-to-real gap finding 已 documented

**优**:
- ADR-027 §2.1 prerequisite #4 satisfied
- LL-183 regression gate 真生产 path verify
- 第一笔 live execute 信心高
- 满足 SHUTDOWN_NOTICE §9 prerequisite ("paper-mode 5d dry-run NOT executed")
- 灰度 PT_TOP_N=5 在 paper-mode 验证 (5-18 调整后 0 真生产 verify)

**适合**: user 决议 "已等 3+ weeks 不差 5 天" + LL-183 4-29 cleanup 是真 cost 经验 → ADR-027 #4 paper-mode 5d 是真 due diligence.

### §3.3 路径 C: 暂不重启 → Phase J 研究优先

**Action**:
- 保持 `DailyExecute = Disabled` sustained
- 启动 Phase J 多周研究 (B1 Sharpe heterogeneity / B2 backup strategy / B3 survivorship bias / B4 slippage / C1 Alpha SPOF / C3 LL-182 long-run / D2 sim-to-real gap) — 见 [CC_ACTIONS_FOR_USER_2026_05_19.md §2](CC_ACTIONS_FOR_USER_2026_05_19.md)

**适合**: user 决议 "single Alpha SPOF + WF 0.86 vs 12yr 0.36 异质性 2.4× 不足以重启实盘, 需要 backup strategy candidate + sim-to-real gap verify 后再决议重启".

**风险**:
- 真账户 cash ¥993,520.66 闲置 → opportunity cost (~5% annual = ¥4-5万/年, 但 Phase J 研究有 alpha discovery 期望)
- Beat 22 entries 持续 fire → LLM cost ~$50/月 (sustained $50 budget)
- 真账户暴露/真长期 ops 体例无演练 → 重启 surface area 累积

**优**:
- 0 financial risk
- 真 alpha 加固后重启更稳
- LL-182/183 long-run verify 在 5d staged 之外 + ADR-028 AUTO 5 prerequisite #1 STAGED 1 月 0 事件 sustain 等条件 + 长期 prep ROI 更高

---

## §4 CC 推荐: 路径 B (staged paper-mode 5d)

**推荐理由 (5 axis)**:

1. **ADR-027 §2.1 #4** "paper-mode 5d validated" 是 V3 §20.1 决议层已 settled 的 prerequisite. 跳过 = 削减已决议 prerequisite (反 ADR-022 anti-pattern).
2. **LL-183 5-18 真生产事件** (silent NOT-GATING dry_run propagation, fix PR `355b813`) 真 production path 仅 pytest 验证, paper-mode 5d 是首次端到端真路径 verify.
3. **LL-182 QMT 5-axis fix** (5-18 PR `481ebcd`) 真 long-run verify 在 paper-mode 5d 满足"非首日"测试.
4. **灰度 PT_TOP_N=5 5-18 调整后 0 真生产 verify** — paper-mode 5d 在 paper layer 验证 5-stock 灰度选股逻辑 + 行业 cap=1.0 + SN beta=0.50 全链 path.
5. **机会成本可控** — 5 天等待 vs LL-183 类 P0 incident recurrence cost (4-29 emergency 17 orders 全 cancel 经验) — risk-adjusted favorable.

**预期 timeline**:
```
5-20 Tue (今天明天) — paper-mode .env flip + Servy restart + Enable DailyExecute
5-20 Tue 16:30 — DailySignal 真实生成 (Beat 已 active, 沿用)
5-20 Tue ... 5-26 Mon — 5 trading days 观察期
5-26 Mon 18:00 — paper-mode 5d 验证 PASS gate
5-27 Wed 09:31 — flip .env live + 第一笔 live execute
```

**预期 5d observation 验证 checklist** (CC 提供, user 验收):
- [ ] signals 表 5 daily writes, 每次 ≥ 5 rows
- [ ] execution_plans 5 daily writes (paper-mode)
- [ ] trade_log 0 new (paper-mode, broker_qmt paper adapter sustained)
- [ ] risk_event_log 0 P0 incident
- [ ] meta_monitor_tick 0 alert-on-alert (7 polled rules 全 PASS)
- [ ] DingTalk 0 fire (paper sustained 0 broker → 0 actionable)
- [ ] PT_Watchdog 0 alert
- [ ] LLM cost ≤ $50/月 / 80% threshold
- [ ] Beat 22 entries 100% 触发 (5-day window)
- [ ] PG / Redis / xtquant heartbeat 0 outage

---

## §5 Open Questions (user 决议 trigger)

A. **路径 选择**: A (full restart Mon 5-25) / B (staged paper 5d, CC 推荐) / C (Phase J 研究优先)?

B. **路径 B 选定后**: paper-mode flip 时机 5-20 Tue 还是 5-21 Wed (避开 5-19 Mon 已收盘)?

C. **5-27 live flip**: 即时 flip 还是再 buffer 1-2 day (e.g. 5-28 Thu)?

D. **PT_TOP_N**: 保持灰度 5 还是升 10 / 20 / 50? (sustained 5-18 user 决议 5)

E. **ADR-027 §2.1 STAGED 代码 implement**: 短期 path (default=OFF + STAGED_ENABLED=false) **是否 Sprint 1~M 期触发**? 还是 defer 到 长期 Sprint M+1 (满足 5 prerequisite 后)?

F. **ADR-028 §2 AUTO + RAG + backtest replay**: defer 到 Sprint M+1~N (沿用 ADR cite), 不重启决议触发?

G. **HTTPS migration** (CC_ACTIONS_FOR_USER §1.2): 重启前 fix 还是 defer?
  - **Option 1**: 本次重启前 nginx + cert + COOKIE_SECURE_FLAG=true (~3-5h work)
  - **Option 2**: 本次重启用 LOG.warning advisory 兜底 + 后续 sprint HTTPS
  - **Option 3**: 切换 API_HOST=127.0.0.1 localhost-only (简单避险)

H. **PG password rotate** (CC_ACTIONS_FOR_USER §1.3): 重启前 rotate 还是 defer 到下次 Servy 维护窗口?

---

## §6 CC 不能做的 (X10 enforce)

CC 永远不会自动:
- ❌ Enable `QuantMind_DailyExecute` schtask (需 user 显式 trigger)
- ❌ Edit `.env` EXECUTION_MODE / LIVE_TRADING_DISABLED / DINGTALK_ALERTS_ENABLED (5/5 红线 fields, 需 user 显式 trigger + ADR/PR)
- ❌ Restart Servy 4 services (需 user 显式 trigger)
- ❌ Run `python scripts/run_paper_trading.py --dry-run=false` (LL-183 后真账户 mutation 必 user trigger)

CC 可以在 user 显式 trigger 后:
- ✅ 执行 PowerShell `Enable-ScheduledTask` (sustained PR #170 Step 6.4 G1 体例)
- ✅ Edit `.env` (sustained PR #169 backup-then-edit 体例, ADR-027 §7 体例)
- ✅ Restart Servy (`powershell -File scripts/service_manager.ps1 restart all`)
- ✅ 起 paper-mode 5d observation period STATUS_REPORT 沉淀
- ✅ Live 切换 ADR + PR sediment

---

## §7 实施 source (本 doc 真值依据)

- V3 §20.1 设计层 10/10 决议 (Session 49 5-02 sprint close, Claude.ai+user 战略对话 sediment)
- [ADR-027](../adr/ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md) §2.1 5 STAGED prerequisite
- [ADR-028](../adr/ADR-028-auto-mode-v4-pro-rag-and-backtest-replay.md) §1.2 5 AUTO prerequisite
- [LL-188 forensic](../../LESSONS_LEARNED.md#ll-188) (5-19 Session 58 round-1 cold-start, .env=live 3+ weeks drift)
- [STATUS_REPORT_2026_05_18_evening_audit_closure](STATUS_REPORT_2026_05_18_evening_audit_closure.md) Top 5 P0 findings
- [CC_ACTIONS_FOR_USER_2026_05_19](CC_ACTIONS_FOR_USER_2026_05_19.md) §1.1 PT 重启 timeline
- [SHUTDOWN_NOTICE_2026_04_30](SHUTDOWN_NOTICE_2026_04_30.md) §9 PT 重启 prerequisite
- [V3_DRY_RUN_BUG_LL_183_2026_05_18](V3_DRY_RUN_BUG_LL_183_2026_05_18.md) LL-183 silent NOT-GATING fix
- [V3_QMT_CONNECT_ROOT_CAUSE_FIX_2026_05_18](V3_QMT_CONNECT_ROOT_CAUSE_FIX_2026_05_18.md) LL-182 5-axis fix
- PowerShell `Get-ScheduledTask` 5-19 Session 58+1 cold verify
- Beat schedule.py 22 entries (commits sustained 5-18 14:11 SH 重启 post-M3 asyncio bootstrap fix)

---

## §8 next step (user trigger 后 CC 接力)

**If user 答 A (full restart Mon 5-25)**:
1. CC 起 ADR-085 PT-restart-decision (~30min)
2. CC 5-22 Fri 提供 pre-flight checklist + 16:30 DailySignal 真值 + Servy 健康 verify
3. user 5-25 Mon 08:50 SH `Enable-ScheduledTask QuantMind_DailyExecute` 显式 trigger
4. CC monitor 5-25 09:31 SH 第一笔 + STATUS_REPORT

**If user 答 B (staged paper 5d, CC 推荐)**:
1. CC 起 ADR-085 PT-paper-dryrun-5d (~30min)
2. user 5-20 Tue 早 显式 trigger paper-mode flip + Servy restart + Enable DailyExecute
3. CC 5-21~5-26 daily 提供 5d observation STATUS_REPORT (1/day)
4. CC 5-26 Mon 提供 paper-mode 5d 验证 PASS gate report
5. user 5-27 Wed 显式 trigger live flip
6. CC monitor 5-27 09:31 SH 第一笔 live + STATUS_REPORT

**If user 答 C (Phase J 研究)**:
1. CC 起 Phase J 优先级 plan (B1/B2/B3/B4/C1/C3/D2 7 items)
2. user 决议 第一个 research item (e.g. B3 survivorship bias audit)
3. CC 起 research SOP + 1-2 sprint cycle

---

**End of brief. AWAITING USER DECISION 路径 A / B / C + Open Question §5 A-H 决议.**
