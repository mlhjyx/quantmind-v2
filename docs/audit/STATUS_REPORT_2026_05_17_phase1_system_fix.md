# STATUS_REPORT — Phase 1 System Fix (2026-05-17 evening)

## 战略校正

用户在 session 中段 push: **Monday 09:31 SH default fire 不应坚持**, 需要全方面体检. Plan v0.4 Gate E formal close ✅ **不等于** Mon live-fire 充分条件 (LL-098 X10 真应用第 15 次实证). 战略从 "Mon 日期触发" 调整为 **"verifiable readiness 触发"**.

## 完成 P0 items (autonomous execution)

### P0-1 health_check.py sys.path drift (PR #378, MERGED `69f2153`)
- **真根因 surface (DB 实测 9 entries scheduler_task_log)**: signal_phase 14 天 9 entries 分布:
  - 5 days `健康预检失败` (5-11~5-15 连续): `check_config_drift FAIL: No module named 'backend'`
  - 3 days `QMT 持仓蒸发` (5-06, 5-07, 5-17 15:16): position_snapshot evaporation false-alarm
  - 1 day success (5-17 15:23, 本 session cleanup 后)
- **修复**: `scripts/health_check.py:24` 仅 append `backend/`, 但 `engines.config_guard:155` `from backend.qm_platform.config.auditor` 需要 PROJECT_ROOT 也在 sys.path. 加 idempotent guard.
- **同 PR**: rolling_wf.py 同 pattern fix (7th drift)
- **Reviewer P2 fix**: canonical order PROJECT_ROOT first (matches pt_watchdog/data_quality_check/services_healthcheck)
- **Verify**: `python scripts/health_check.py` → all 8 PASS ✅

### P0-3 intraday tradability pre-filter (PR #379, MERGED `d11307b`)
- **User 真问题**: 0→20 initial build, N stocks 涨停 → adapter reject N orders → N×weight cash idle
- **现有保护 (verified)**: `QMTExecutionAdapter._check_buy_protection` 已有 per-order 涨停 reject via 实时 tick (fail-safe)
- **新加保护**: pre-execution layer — `_filter_nontradable_codes` (T日 stock_status_daily + klines.up_limit) + capital re-normalize
  - is_suspended OR is_new_stock → 移除
  - close >= up_limit * 0.998 → 移除 (T日 涨停)
  - 剩余权重 `scale = original_total / new_total` 保留 CB constraint
  - MIN_TRADABLE_AFTER_FILTER=5 防集中风险 (reviewer P2)
  - `with conn.cursor() as cur` 防 leak (reviewer P1)
- **Tests**: 9/9 PASS (empty / suspended / new_stock / limit_up / precedence / mixed / re-normalize math / all-dropped edge / min-floor)

### P0-6 proactive sys.path sweep (PR #380, MERGED `8579cbb`)
- **方法**: 9 critical schtask scripts 批量 `--help` import test
- **3 broken found**:
  - `scripts/pt_audit.py`: 完全无 sys.path setup → ModuleNotFoundError 'qm_platform'
  - `scripts/pull_moneyflow.py`: 仅 backend → ModuleNotFoundError 'backend'
  - `scripts/daily_reconciliation.py`: 仅 backend → ModuleNotFoundError 'backend'
- **3 fixed** with canonical pattern. Verified post-fix all boot past previous ModuleNotFoundError.

### P0-5 signal_phase E2E verify ✅
- `python scripts/run_paper_trading.py signal --dry-run --date 2026-05-15 --skip-fetch --skip-factors`
- **Result**: 19s success, all 8 health checks PASS, S1 generate 20 signals total_weight=0.97, PaperBroker init 全现金 0 持仓 → 初始建仓 path verified.

## Phase 1 完整 closure addendum (post-21:00 SH continuation, user push "不要往后推")

### P0-2 RESOLVED ✅ (PR #381 merged)
- `rolling_wf.py` cache API alignment: `BacktestDataCache.load(start, end)` returns dict + `load_ln_mcap_pivot(start, end, conn)` new signature applied
- Reviewer P1 fix: replaced hardcoded DSN with `get_sync_conn()` (env-driven, 铁律 35)
- Reviewer P2 fix: assert `neutral_value` column present (铁律 33 fail-loud)
- **Verified end-to-end re-run**: OOS Sharpe = **0.8665** vs baseline 0.8659 (drift **+0.07%**) STABLE
- MDD = -13.91% identical / Annual 12.83% / OOS days 1250 / Fold 4 best Sharpe=1.79
- 35-day data drift → **zero impact on chain Sharpe**. Strategy time-effectiveness verified ✅

### P0-4 RESOLVED ✅ (PR #382 merged)
- True root cause surfaced: signal_phase 5-11~5-15 connected fail → `pt_data_service._fetch_index` never ran for those dates → index_daily 000300.SH missing 5-08 + 5-11~5-14
- CSI300 benchmark gap → `compute_daily_ic` fwd_rets via benchmark = NaN → CORE4 IC NULL for 4-01~5-15
- Fix: new `scripts/backfill_index_daily_5_2026.py` one-shot Tushare pull (5 rows upserted)
- Cascade recovery 3-stage executed: index_daily UPSERT → `compute_daily_ic` (96 rows, 4-01~4-14 ic_5d/10d/20d populated) → `compute_ic_rolling --core` (31 ic_ma20/ma60 updates)
- Post-refresh CORE4 ratios (DB-verified):
  - turnover_mean_20: ratio=0.686 (warning)
  - volatility_20: ratio=0.277 (warning)
  - bp_ratio: ratio=0.044 (warning)
  - dv_ttm: ratio=0.383 (warning)
- **Decision**: all 4 CORE in warning BUT WF passes → MONITOR + ACCEPT (no better candidates per Phase 3B/3E findings) + partial-pilot path when triggered
- Decision matrix: **(WF PASS + lifecycle WARNING) = cautious-yellow** (Phase 3 partial-pilot OK, scale-up gated on lifecycle recovery)
- Recurrence prevention: `pt_data_service._fetch_index` automatically resumes now signal_phase fixed

### LL-176 sedimented ✅ (main HEAD `e6f3933`)
- 5 core lessons + comprehensive proactive audit 2-stage pattern 第 7 case
- Captures Mon-default → verifiable-readiness pivot strategic decision
- 10 cumulative sys.path drift fixes this session
- ADR-082 4 new BAU candidate items (D8 sys.path consolidation .pth install, D9 causal-chain alerts cascading silent failure, D10 factor lifecycle decision matrix, D11 reviewer P1 BLOCK iterative pattern)

## ~~Deferred to P1~~ (NULL — all P0 closed in single session)

### ~~P0-2 WF re-run BLOCKED~~ — RESOLVED above

### ~~P0-4 CORE4 factor health UNVERIFIABLE~~
- `factor_registry`: 4 PT factors (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm) **all status='warning'**
- 最近一次 lifecycle 评估 updated_at=2026-04-24 / 04-18 (24~30 天前)
- `factor_ic_history` ic_ma20/ic_ma60 last non-null = 2026-03-30 (48 天 gap)
- Backfill 尝试: `compute_daily_ic --core --start 20260401 --end 20260515` 跑了 96 rows 但 dv_ttm ic_20d=NaN (ConstantInputWarning — Spearman corr undefined for some dates)
- **Root cause**: compute_daily_ic 仅对 T+20 forward returns 全可用的 dates 才填值 + 部分 dates 返 NaN
- **结论**: CORE4 当前真实健康状态 **无法判断**

## 红线 5/5 sustained
- cash=¥993,520.66 (per session knowledge)
- 0 持仓 (DB position_snapshot live=0 rows confirmed)
- LIVE_TRADING_DISABLED=false (.env, per config_guard log)
- EXECUTION_MODE=live (.env, per config_guard log)
- QMT_ACCOUNT_ID=81001102 (per session knowledge)

## 关键 forcing function

`Disable-ScheduledTask -TaskName QuantMind_DailyExecute` → Mon 09:31 auto-fire 已阻断. 这是 Phase 1 实施期的硬约束 — schtask 不应重启直到 P0-2 (WF) + P0-4 (factor health) 解决 + paper-mode 5d dry-run 完成.

## 累计本 session sys.path drift fixes

总计 **10 次** (LL-175 lesson 2 同 pattern):
1-5 (earlier in session): TB-5b / services_healthcheck / data_quality_check / pt_watchdog / broker_qmt (PR #377)
6-7 (PR #378): health_check / rolling_wf
8-10 (PR #380): pt_audit / pull_moneyflow / daily_reconciliation

**LL-176 候选**: project-wide sys.path bootstrap consolidation (单 shared import boilerplate / .pth installation per SETUP_DEV.md) 消除 recurring pattern.

## 下一阶段 path (per Phase 1+2+3 strategy)

### Phase 1 剩余 (本周 5-18 ~ 5-22):
- **P0-2 follow-up**: rolling_wf.py BacktestDataCache API alignment (cache.load_factor_data → cache.load)
- **P0-4 follow-up**: factor lifecycle replace 自动化 decision + IC compute_daily_ic gap fix (recent dates ic_1d/5d/10d NULL even when forward return exists)
- check_opening_gap 阈值/halt 决议
- dv_ttm warning decision (replace / monitor / accept-with-cap)

### Phase 2 (下周 5-25 ~ 5-29):
- live-mode-runtime + schtask DISABLED 全周 paper-mode dry-run
- 5d 自然观察 Gate E §L10.5 paper-mode 5d 验收 (V3 §15.4 SLA)

### Phase 3 (再下周 6-01 onward):
- Phase 1 全 P0 closed + Phase 2 PASS 后
- Partial 5-stock pilot day 1 → observation → scale to 10 → scale to 20

## PR cumulative this session (post compact)

| PR | Title | Status |
|---|---|---|
| #377 | broker_qmt.py ensure_xtquant_path() (Mon-critical) | MERGED (earlier) |
| #378 | health_check.py + rolling_wf.py sys.path | MERGED `69f2153` |
| #379 | intraday tradability pre-filter + tests | MERGED `d11307b` |
| #380 | proactive sys.path sweep 3 scripts | MERGED `8579cbb` |

## STOP gate (next session)

不应自启 forward-progress without user trigger (LL-098 X10 sustained):
- Phase 2 paper-mode 5d dry-run 实施 → wait user
- Re-enable schtask QuantMind_DailyExecute → wait user
- .env LIVE_TRADING_DISABLED 翻转 → wait user
- Tier B / Tier C sprint 起 → wait user
