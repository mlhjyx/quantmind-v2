# ADR-085: PT 重启 staged paper-mode 5d dry-run → live flip (path B)

> **Status**: Proposed (5-19 Session 58+1 起草, 等 user 第二 trigger "你执行" merge = Accept signal)
> **Date**: 2026-05-19
> **Authors**: CC Session 58+1 + user 决议 "同意你的推荐" (5-19 evening SH)
> **Related**:
> - [docs/audit/PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19.md](../audit/PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19.md) (strategic brief 真值 schtask gate + 3 路径 decision tree)
> - [ADR-027](ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md) §2.1 5 STAGED prerequisite (本 ADR 满足 #4 paper-mode 5d)
> - [ADR-028](ADR-028-auto-mode-v4-pro-rag-and-backtest-replay.md) (AUTO 长期 Sprint M+1~N defer, 不在本 ADR scope)
> - [LL-188 forensic](../../LESSONS_LEARNED.md#ll-188) (sediment drift root cause)
> - [SHUTDOWN_NOTICE_2026_04_30](../audit/SHUTDOWN_NOTICE_2026_04_30.md) §9 paper-mode 5d prerequisite
> - [ADR-027 §7 amend annotation](ADR-027-l4-staged-default-reverse-decision-with-limit-down-fallback.md#7-amend-annotation-2026-05-17-evening-phase-c-c1a-dingtalk_alerts_enabled-flip-append-only-per-adr-022) (双 trigger 体例 sediment, DINGTALK_ALERTS_ENABLED 5-17 flip)

## §1 Context

### 1.1 触发背景

- **5-19 Session 58+1 cold-start forensic** (LL-188): `.env=live` armed 3+ weeks (5-15~5-17 operator cutover) 但 sediment 层 claim sustain "paper". 真 gate 是 `QuantMind_DailyExecute = Disabled` schtask. trade_log 4-30 → 5-19 (19 days) 0 new rows verified.
- **PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19** §3.2 path B (staged paper-mode 5d → live flip) CC 推荐, user 决议 "同意你的推荐" (5-19 evening SH).
- **真值 schtask gate**: `QuantMind_DailyExecute = Disabled` 是 broker call 0 路径 root cause, 非 `.env`.
- **path A (full restart Mon 5-25) ❌**: ADR-027 #4 paper-mode 5d 跳过 + LL-183/182 残留 risk
- **path C (Phase J 研究优先) ❌**: opportunity cost ~5%/年 + 长期 prep ROI 与 5d dry-run 共存可获
- **path B ✅ CC 推荐**: 满足 ADR-027 #4 + LL-183/182 真路径 verify + 灰度 PT_TOP_N=5 (5-18 调整后) 在 paper-mode 验证

### 1.2 ADR-027 §2.1 5 STAGED prerequisite 真值 verify

| # | Prerequisite | path B verify status |
|---|---|---|
| 1 | LIVE_TRADING_DISABLED guard reconcile | path B step 1 flip back true → app-layer guard 重新 effective |
| 2 | 跌停 fallback implement (V3 §7.2) | path B 不触发 (paper-mode 0 broker call), 长期 Sprint M-1 verify |
| 3 | SOP-6 真生产下单 fail-safe sediment | path B step 1 flip + 5d 沉淀 SOP-6 第 1 次实证 |
| 4 | **paper-mode 5d validated** | **path B 直接 satisfies** |
| 5 | user 显式 .env governance + commit | path B step 1 显式 ADR + commit, step 2 同 path |

## §2 Decision

### 2.1 path B 实施 sequence (2 phase, 5d dry-run + 1d flip)

**Phase B-1 (5-20 Wed → 5-26 Tue, 5 trading days paper-mode dry-run)**:

1. **Backup .env** (atomic):
   ```powershell
   Copy-Item backend/.env logs/.env-backup-pre-paper-dryrun-2026-05-20.bak
   ```

2. **Edit `backend/.env`** (2 red-line field flip, sustained ADR-027 §7 体例):
   - `EXECUTION_MODE=live` → `EXECUTION_MODE=paper`
   - `LIVE_TRADING_DISABLED=false` → `LIVE_TRADING_DISABLED=true`
   - (其他 fields 0 改: DINGTALK_ALERTS_ENABLED=true sustained / QMT_ACCOUNT_ID=81001102 sustained / PT_TOP_N=5 sustained / PT_INDUSTRY_CAP=1.0 sustained / PT_SIZE_NEUTRAL_BETA=0.50 sustained)

3. **Restart 4 Servy services** (sustained PR #170 体例):
   ```powershell
   powershell -File scripts/service_manager.ps1 restart all  # 3 Servy (FastAPI / Worker / Beat)
   D:\tools\Servy\servy-cli.exe restart --name="QuantMind-QMTData"  # 4th service
   ```

4. **Enable PT schtask 2 entries**:
   ```powershell
   Enable-ScheduledTask -TaskName QuantMind_DailyExecute       # currently Disabled
   Enable-ScheduledTask -TaskName QuantMind_CancelStaleOrders  # currently Disabled
   ```

5. **5 trading days observation** (5-20 Wed → 5-26 Tue):
   - signals 表 5 daily writes verify
   - execution_plans 5 daily writes (paper-mode 写入但 broker_qmt 走 paper adapter)
   - trade_log 0 new rows (paper sustained)
   - risk_event_log 0 P0 incident
   - meta_monitor_tick 0 alert-on-alert
   - DingTalk 0 fire (paper 0 broker → 0 actionable)
   - PT_Watchdog 0 alert
   - LLM cost ≤ $50/月 / 80% threshold
   - Beat 22 entries 100% 触发 (5-day window)
   - PG / Redis / xtquant heartbeat 0 outage

**Phase B-2 (5-27 Wed flip live)**:

1. **Verify Phase B-1 5d observation 10/10 checklist PASS** (CC 沉淀 STATUS_REPORT)
2. **Backup .env** (atomic):
   ```powershell
   Copy-Item backend/.env logs/.env-backup-pre-live-restart-2026-05-27.bak
   ```
3. **Edit `backend/.env`** (2 red-line field flip back):
   - `EXECUTION_MODE=paper` → `EXECUTION_MODE=live`
   - `LIVE_TRADING_DISABLED=true` → `LIVE_TRADING_DISABLED=false`
4. **Restart 4 Servy services**:
   ```powershell
   powershell -File scripts/service_manager.ps1 restart all
   D:\tools\Servy\servy-cli.exe restart --name="QuantMind-QMTData"
   ```
5. **Schtask state 沿用** (Phase B-1 已 Enable, 不需再 Enable)
6. **5-27 Wed 09:31 SH 第一笔 live execute** monitor + STATUS_REPORT

### 2.2 双 trigger 体例 (沿用 ADR-027 §7 sediment)

- **Trigger 1** "同意" ✅ (5-19 Session 58+1 evening SH, user reply to brief)
- **Trigger 2** "你执行" ⏳ (待 user 显式 trigger merge 本 ADR-085 PR = Accept signal)

CC 0 自动 mutation. mutation 走 user 显式 trigger 2 后 CC 接力执行 (沿用 PR #170 + PR #169 + ADR-027 §7 体例).

### 2.3 灰度 sustained (反 PT_TOP_N 调整)

- PT_TOP_N=5 sustained (5-18 backup logs/.env-backup-pre-pt-top-n-5-2026-05-18.bak 沿用)
- PT_INDUSTRY_CAP=1.0 sustained (不限行业)
- PT_SIZE_NEUTRAL_BETA=0.50 sustained (Step 6-H Partial SN)

### 2.4 红线 5/5 verify (Trigger 2 前 CC autonomous verify)

| # | Red-line field | path B 期望状态 (Phase B-1) | path B 期望状态 (Phase B-2) |
|---|---|---|---|
| 1 | EXECUTION_MODE | paper | live |
| 2 | LIVE_TRADING_DISABLED | true | false |
| 3 | QMT_ACCOUNT_ID | 81001102 (0 改) | 81001102 (0 改) |
| 4 | DINGTALK_ALERTS_ENABLED | true (0 改) | true (0 改) |
| 5 | L4_AUTO_MODE_ENABLED | unset (0 改) | unset (0 改) |

### 2.5 GP weekly 体例 (5-24 Sun 22:00 期间 collision verify)

- Phase B-1 5-day window 含 5-24 Sun 22:00 gp-weekly-mining Beat
- gp-weekly 周日 22:00 不依赖 PT signal/execute, 0 collision
- 0 mitigation required

## §3 Consequences

### 3.1 Pros

- ADR-027 #4 paper-mode 5d 满足
- LL-183 (silent NOT-GATING dry_run) 真路径 verify 5d
- LL-182 QMT 5-axis fix (5-18) long-run 起点 5d
- 灰度 PT_TOP_N=5 (5-18 调整后) paper-mode 验证
- 5-27 Wed flip live 信心高
- SHUTDOWN_NOTICE_2026_04_30 §9 prerequisite 满足

### 3.2 Cons

- 5 trading days 等待 (5-20 → 5-26)
- paper→live flip 期间 1 day 0 fire window (5-27 Wed 流程切换)
- (低) paper-mode broker adapter wire 漂移 — 但 PR #210 sim-to-real gap finding 已 documented

### 3.3 Backup chain (沿用 PR #169 体例)

- Pre-Phase B-1: `logs/.env-backup-pre-paper-dryrun-2026-05-20.bak`
- Pre-Phase B-2: `logs/.env-backup-pre-live-restart-2026-05-27.bak`
- Rollback path: 任意时刻 `Copy-Item logs/.env-backup-*.bak backend/.env` + Servy restart all + Disable schtask 2 entries

### 3.4 Observation period STATUS_REPORT cadence

- 5-21 Thu morning: Day 1 STATUS_REPORT (paper-mode 5d, Phase B-1 启动 24h sediment)
- 5-22 Fri evening: Day 2 + Beat news 6x daily cumulative verify
- 5-25 Mon morning: Day 3 weekend gap analysis (Beat outbox 30s sustained?)
- 5-26 Tue evening: Day 5 final verify + Phase B-2 readiness check
- 5-27 Wed morning: Phase B-2 readiness GO/NO-GO gate

## §4 Anti-pattern verify (沿用 ADR-022)

- ✅ **不 fabricate**: path B 5d dry-run sediment ADR-027 §2.1 #4 prerequisite (NOT 凭空 5d 假设)
- ✅ **不削减 user 决议**: 沿用 user "同意你的推荐" + 双 trigger 体例 (NOT auto-execute 0 trigger 2)
- ✅ **5/5 红线 protect**: §2.4 5 red-line field map + backup chain + rollback path
- ✅ **paper-mode 0 broker call**: 沿用 paper adapter wire (broker_qmt PaperBroker class)
- ✅ **双 trigger 体例**: 沿用 ADR-027 §7 (DINGTALK_ALERTS_ENABLED 5-17 flip 体例)
- ✅ **schtask gate 真识**: LL-188 forensic + STATUS_REPORT 5-18 evening cross-cite (反 .env-only mental model)

## §5 发现 sediment 候选 (P3 backlog)

- **LL-189 候选** ("schtask gate 真识 vs .env mental model 漂移"): LL-188 forensic 发现真 gate 是 `QuantMind_DailyExecute = Disabled`, 反 CC + user 主流 mental model "LIVE_TRADING_DISABLED 是 trip wire". 沿用 LL-188 体例 sub-class, 待 5-27 Wed live restart 后 sediment 起手 — 真 production retrofit context.
- **ADR-086 候选** ("PT 重启 SOP 体例化"): 本 ADR-085 是 first sub-task, 长期沉淀 PT restart SOP (backup + .env edit + Servy restart + schtask Enable + 5d observation + STATUS_REPORT cadence) 5/5 体例. 沿用 ADR-027 §7 amend 体例 → 长期 ADR-086 sub-task. (5-27 flip live 后 sediment)
- **AUTO + RAG defer 注释**: 本 ADR 0 含 AUTO 决议 (沿用 ADR-028 长期 Sprint M+1~N defer 体例).

## §6 实施 source

- PT_RESTART_PHASE_F_STRATEGIC_BRIEF_2026_05_19.md §3.2 path B + §4 CC 推荐 5 axis + §5 Open Questions + §6 X10 enforce
- ADR-027 §2.1 5 STAGED prerequisite + §7 双 trigger amend annotation (DINGTALK_ALERTS_ENABLED 5-17 flip)
- ADR-028 §1.2 5 AUTO prerequisite (本 ADR 0 触发)
- LL-188 forensic (.env=live 3+ weeks drift root cause + schtask gate 真识)
- SHUTDOWN_NOTICE_2026_04_30 §9 (PT 重启 prerequisite path)
- V3_DRY_RUN_BUG_LL_183_2026_05_18 (LL-183 silent NOT-GATING fix, paper-mode 真路径 verify driver)
- V3_QMT_CONNECT_ROOT_CAUSE_FIX_2026_05_18 (LL-182 5-axis fix, long-run verify driver)
- PR #170 Step 6.4 G1 实测修订 (schtask Enable/Disable 体例 sediment)
- PR #169 backup-then-edit 体例 (清仓 v4 hybrid narrative)
- PowerShell `Get-ScheduledTask` 5-19 Session 58+1 cold verify (27 schtask state)
- Beat schedule.py 22 entries (5-18 14:11 SH 重启 post-M3 asyncio bootstrap fix sustained)

## §7 next step (trigger 2 后)

CC 接力 sequence:
1. user 显式 "你执行" → trigger 2 received
2. CC 运行 `scripts/pt_restart_path_b_step1.ps1` (Phase B-1 launch, 5-20 Wed 早 SH 触发)
3. CC daily STATUS_REPORT (5d cadence, 沿用 §3.4)
4. CC 5-27 Wed 早 `scripts/pt_restart_path_b_step2.ps1` (Phase B-2 launch) + 9:31 SH 第一笔 live execute monitor
5. CC LL-189 + ADR-086 sediment (post-5-27 retrofit)
