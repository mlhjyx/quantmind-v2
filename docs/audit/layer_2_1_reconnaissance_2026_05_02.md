# Layer 2.1 Reconnaissance — trade_log + 数据源 stale 真状态评估

**日期**: 2026-05-02
**Scope**: read-only 真测真值 + finding enumerate, 0 修代码 / 0 backfill / 0 dual_write
**触发**: Layer 2 V2 真核 enforce 起手 sub-task (memory plan 5-01 标线索, 真测后再决议实施 scope)
**反 anti-pattern**: v5.2 sustained — cite 是线索, 实测才是真值, 不预设 framing
**main HEAD**: `6f2cf5d` (5-02 sprint 末, ground truth verify ✅ 24h+ 内)

---

## §A trade_log 表当前真状态

### A.1 真测真值

```sql
-- 命令: SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT trade_date) FROM trade_log
-- 真值 (2026-05-02 ~02:35):
total_rows     = 88
min_date       = 2026-04-14
max_date       = 2026-04-17
distinct_dates = 4 (4-14 / 4-15 / 4-16 / 4-17)
```

per-date breakdown (>=4-15):

| trade_date | rows |
|---|---|
| 2026-04-15 | 8 |
| 2026-04-16 | 20 |
| 2026-04-17 | 24 |
| 2026-04-18 ~ 2026-05-01 | **0** |

### A.2 vs cite verify

memory cite Session 21 末 PR #41 backfill: "4 码 9538 股补录 / 2 BJ 125 股留独立调查". 真测**未细分 backfill rows**, 但 88 total rows / 4 distinct dates / MAX=4-17 全部 **vs cite 0 drift** ✅.

### A.3 4-29 emergency_close cite verify (memory T0-19)

memory cite "4-29 10:43:54 emergency_close 18 持仓清仓". 真测:

| 数据源 | 4-29 行数 | 真值 |
|---|---|---|
| `trade_log` | **0** | ❌ 0 audit row |
| `risk_event_log` | **0** (4-29 当日实时), 1 行 4-29 14:00 P0 后填 LL-081 narrative | ❌ |
| `execution_audit_log` | **0** (>=4-25 全 0, 总 269 rows MAX 早于 4-25) | ❌ |
| `signals` | **0** (4-29 起 signal pipeline 停) | (expected, 4-29 user 决策) |
| 真 emergency_close log | **存在** `logs/emergency_close_20260429_104354.log` (13992 bytes / 134 行) | ✅ 真发单 + 真成交 |
| `emergency_close_*.DONE.flag` | **0** (logs/ 下无 DONE flag) | ❌ T0-19 audit chain 未运行 |

**真值**: 4-29 真发单 18 持仓 (log 134 行有 18 `[QMT] 下单` + `成交回报` 实证), DB 4 张 audit 表 0 行 4-29 (trade_log / risk_event_log / execution_audit_log / signals).

### A.4 真因 (git log 实测)

```
2026-04-29 commits (无 T0-19 hook 相关):
  d1522cc feat(mvp 3.1b phase 1): SingleStockStopLossRule
  79aa653 fix(review): PR #139 reviewer

2026-04-30 18:31:49 (T0-19 hook 首次落地):
  fb256c0 feat(t0-19): phase 2 — 4 项修法落地 (#168)
```

→ **4-29 emergency_close 真跑 时 T0-19 hook 真不存在** (PR #168 是 4-30 18:31 才合入, 比 emergency_close 晚 ~32 小时). audit chain 0 行 **不是 hook bypass, 是 hook 后到 + 4-29 历史 emergency_close fill 真未 backfill 进 trade_log/risk_event_log**.

### A.5 当前 T0-19 hook 真状态 (verifier 实跑)

`scripts/audit/check_t0_19_implementation.py` 当前真测 (2026-05-02 ~02:38):

| Check | Status |
|---|---|
| LIVE_TRADING_DISABLED 双锁守门 | ✅ PASS |
| `backend/app/services/t0_19_audit.py` | ✅ PASS (4 函数全在) |
| `backend/app/exceptions.py` 3 classes | ✅ PASS |
| emergency_close hook insertion | ❌ FAIL |
| dry-run subprocess path | ❌ FAIL |

但 Read 真值 [emergency_close_all_positions.py:308-327](scripts/emergency_close_all_positions.py:308-327) **真有** `from app.services.t0_19_audit import _collect_chat_authorization, write_post_close_audit` + `write_post_close_audit(...)` 调用. **verifier 是 false-positive FAIL** — literal grep `"from app.services.t0_19_audit import write_post_close_audit"` 不匹配 multi-import line `from app.services.t0_19_audit import _collect_chat_authorization, write_post_close_audit`. 见 §E 候选 sub-task 2.1.1.

---

## §B trade_log INSERT 写路径 enumerate

### B.1 真生产 INSERT 路径 (5)

| # | file:line | 函数 | 用途 | 触发条件 | 当前真状态 |
|---|---|---|---|---|---|
| 1 | [paper_broker.py:458](backend/engines/paper_broker.py:458) | `save_fills_only` | paper 路径 (signal+execute 拆分后) | execution_service.execute → 调 paper_broker | **未触发** (4-29 起 signal pipeline 停) |
| 2 | [paper_broker.py:509](backend/engines/paper_broker.py:509) | `save_state` | 旧路径 (signal+execute 一体, paper) | 旧 PT pipeline | **未触发** (拆分后历史) |
| 3 | [execution_service.py:373](backend/app/services/execution_service.py:373) | `_save_live_fills` | live 模式专用 | EXECUTION_MODE=live 时 execute_real | **未触发** (EXECUTION_MODE=paper sustained) |
| 4 | [t0_19_audit.py:193](backend/app/services/t0_19_audit.py:193) | `_backfill_trade_log` | emergency_close audit hook | emergency_close --execute → write_post_close_audit | **0 真触发** (PR #168 4-30 落地, 4-29 未 backfill) |
| 5 | [trade_repository.py:98](backend/app/repositories/trade_repository.py:98) | `TradeRepository.insert_trade` (async) | generic async repo | 调用方 grep `TradeRepository\(\)` 0 matches | **dead code candidate** (0 真生产调用) |

### B.2 调用方 (execution_service)

| caller line | 调用 path |
|---|---|
| `execution_service.py:191` | `paper_broker.save_fills_only(fills, conn)` (paper 主路径) |
| `execution_service.py:313` | `self._save_live_fills(conn, strategy_id, fills)` (live 主路径) |
| `execution_service.py:502` | `paper_broker.save_fills_only(retry_fills, conn)` (retry 路径) |

### B.3 One-off backfill / repair (非生产)

- [`scripts/diag/f19_trade_log_backfill_2026-04-17.py:232`](scripts/diag/f19_trade_log_backfill_2026-04-17.py:232) — F19 PR #41 4-17 历史 backfill (已跑, audit marker `reject_reason='F19_backfill_2026-04-17'`)
- [`scripts/archive/rebalance_fix.py:329`](scripts/archive/rebalance_fix.py:329) — archive (dead)
- 多 test fixture INSERT (test scope, 不计)

### B.4 真生产写入活跃度 (4-15 ~ 5-01 实测)

trade_log MAX=4-17. 4-18 起 0 写入, **跨 5 真生产 INSERT path 全停** ≥ 11 trading days.

`scheduler_task_log` (1242 rows) 4-15~5-01 task 真值:

| task_name | 总次数 | MAX date | 真状态 |
|---|---|---|---|
| `pending_monthly_rebalance` | 568 | 2026-04-30 | L1 触发延迟月度调仓 (signal_date=2025-05/06/07, **补历史**, 不写 trade_log) |
| `signal_gen` | 223 | 2026-04-07 | **停于 4-07** |
| `execute_phase` | 223 | 2026-04-01 | **停于 4-01** |
| `execute_phase_paper` | 2 | 2026-04-16 | **停于 4-16** |
| `execute_phase_live` | 19 | 2026-04-17 | **停于 4-17** ← trade_log 真 MAX 一致 |
| `intraday_risk_check` | 83 | 2026-04-30 | 4-29 12 次 success / 4-30 72 次 **error** (silent error_message=NULL, see §C2) |
| `pt_audit` | 13 | 2026-05-01 | 4-30/5-01 仍跑 |

→ **silent gap finding**: signal/execute schtask 4-07~4-17 之后真停, 但 4-15~4-28 期间 `signals` 表仍有 20/day 写入 (8 dates / 160 rows). signals 写入路径 ≠ scheduler_task_log 记账路径, 真生产可观测性割裂. 见 §E 2.1.6.

---

## §C 数据源 stale 真状态

### C.1 关键真生产表 freshness 真测

| 表 | 真 MAX 日期 | 行数 | gap (vs today=5-02) | 评估 |
|---|---|---|---|---|
| `klines_daily` | 2026-04-28 | 11,776,616 | 4 calendar days (2 trading days, 5-01~5-05 holiday window) | ⚠️ stale (holiday-driven) |
| `daily_basic` | 2026-04-28 | 11,681,799 | 同 klines | ⚠️ 同根 |
| `factor_values` | 2026-04-28 | 840,478,083 | 同 klines | ⚠️ 依赖 klines |
| `factor_ic_history` | 2026-04-28 | 145,894 | 同 klines (Layer 1 fast_ic_recompute MAX cite 一致 ✅) | ⚠️ |
| `moneyflow_daily` | **2026-04-30** | 11,458,587 | 2 calendar days (most current!) | ✅ 真新 |
| `minute_bars` | **2026-04-13** | 190,885,634 | **19 calendar days (~13 trading days)** | ❌ **stale 严重** |
| `signals` | 2026-04-28 | 220 | 4 days, 但 signal pipeline 4-29 停 (user 决策) | (expected) |
| `modifier_signals` | 2025-12-31 | 2,341 | legacy | (legacy, 不再 active) |
| `backtest_daily_nav` | 2024-12-31 | 224 | legacy | (legacy) |

### C.2 schtask LastResult=1 真因诊断 (实跑实测)

ground truth verify 2026-05-02 标 2 个 schtask LastResult=1, 真因实跑诊断:

#### `QM-HealthCheck` (`scripts/health_check.py`)

```
健康预检: 2026-05-02
  OK postgresql_ok / redis_ok / stock_status_ok / factor_nan_ok / disk_ok / celery_ok / config_drift_ok
  FAIL data_fresh: 数据过期: klines最新=2026-04-28, 期望>=2026-04-30
  ❌ 预检失败，链路暂停
```

→ 真因: `data_fresh` check 期望 `klines >= 4-30`, 实际 4-28. **klines 4-29~5-05 holiday 不发数据**, tolerance 阈值未对齐 holiday window.

#### `QuantMind_DataQualityCheck` (`scripts/data_quality_check.py`)

```
WARNING 发现 3 项异常:
  - klines_daily 2026-04-30 行数=0 (可能未拉取数据)
  - [P0] klines_daily 最新日期=2026-04-28，预期=2026-04-30，滞后2个交易日
  - [P0] daily_basic 最新日期=2026-04-28，预期=2026-04-30，滞后2个交易日
exit_code=1
```

→ 真因: **同 health_check 同根**. holiday tolerance 未对齐, 触发 P0 alert (DingTalk push 已真发, alert key=`data_quality:summary:2026-04-30`).

### C.3 minute_bars 4-13 stale 真因诊断

grep `minute_bars|baostock.*minute|pull_minute|fetch_minute` `scripts/**/*.py`:

- `scripts/research/minute_data_loader.py` (research, 非生产)
- `scripts/research/eval_minute_ic.py` (research)
- `scripts/data/neutralize_minute_batch.py` (factor 中性化, 非拉取)
- `scripts/compute_minute_features.py` (factor compute)
- `scripts/archive/fetch_minute_bars.py` (archive, 历史一次性 5min K线 batch fetch)

→ **真生产 daily minute_bars 拉取 schtask 0 找到**. `scheduler_task_log` 1242 rows 全部 task_name 中无 minute pull task. **minute_bars 4-13 后无人拉取, pipeline 真不存在**.

memory cite "Phase 3E 微结构 16 因子 ROBUST" 表明 minute_bars 真用过, 但当前**生产 pipeline 已经停 ~13 trading days**, 0 schtask 维护.

---

## §D synthesis — stale 与 trade_log gap 关系

### D.1 三条独立 finding chain (NOT 同根因)

| Finding | 真因 chain | 与他 finding 关系 |
|---|---|---|
| **F-RECON-1** trade_log gap 4-17 → 5-01 | execute_phase_live 真停 4-17 + signal_gen 真停 4-07 + 4-29 emergency_close 走旁路 (走 emergency_close_all_positions.py xtquant 直发, 4-29 当时 T0-19 hook 不存在) | **独立**: PT 暂停 + audit chain 缺失 |
| **F-RECON-2** klines/daily_basic/factor_* 4-28 stale | 5-01~5-05 5-day Labor Day holiday + Tushare 不发 holiday data + health_check/data_quality_check tolerance 未 holiday-aware | **独立 (holiday-driven, 节后自然恢复)**: 已知, Layer 1 Week 1 WI 3 sediment 5-01~5-05 真 holiday |
| **F-RECON-3** minute_bars 4-13 stale (~13 trading days) | 真生产 minute pull pipeline **不存在** (0 schtask, 0 真生产 daily script). archive/fetch_minute_bars.py 历史一次性. | **独立 (非 holiday)**: 13 trading days 远超 holiday window |

### D.2 verifier false-positive finding (Layer 1 Week 1 漏)

| Finding | 真因 |
|---|---|
| **F-RECON-4** `check_t0_19_implementation.py` literal grep 不匹配 multi-import | expected `"from app.services.t0_19_audit import write_post_close_audit"` vs 真值 `"from app.services.t0_19_audit import _collect_chat_authorization, write_post_close_audit"`. PR #168 后**verifier 自身 false-positive FAIL**. dry-run subprocess `stdout 无 'DRY-RUN mode' 提示` 同样需 deep verify. |

### D.3 真生产可观测性割裂 finding

| Finding | 真因 |
|---|---|
| **F-RECON-5** 4-30 intraday_risk_check 72 'error' rows error_message=NULL | 铁律 33 silent_failure 候选: status='error' 但 error_message 全 NULL, 无法定位真因 |
| **F-RECON-6** signals 4-15~4-28 写 160 rows, scheduler_task_log signal_gen MAX=4-07 | signal 真生产写入路径 ≠ scheduler_task_log 记账路径, 双 sink 漂移 |

---

## §E 候选 sub-task 拆分 + 推荐次序

| 编号 | 标题 | scope | 依赖 | risk | 优先级 |
|---|---|---|---|---|---|
| **2.1.1** | T0-19 audit chain 4-29 历史 backfill 决议 + verifier 真因诊断 | 决议 4-29 emergency_close 18 真成交是否 backfill 进 trade_log/risk_event_log (沿用 PR #168 _backfill_trade_log + emergency_close log 解析). 含 F-RECON-4 verifier false-positive 修. | 仅 audit 决议; 若决议 backfill, 走 PR #168 既有 hook 无需新代码 | 真金 0 风险 (read emergency_close log → backfill audit row, 不真发单) | **P1** (4-29 是真生产事件, audit chain 缺失影响合规) |
| **2.1.2** | minute_bars 真生产 pull pipeline 缺失诊断 + 决议 | enumerate 历史 fetch_minute_bars.py 调度方式 + 评估当前是否有 PT live 重启 minute_bars 依赖 (Phase 3E 16 微结构 ROBUST 但 Phase 3E-II WF FAIL, 当前 CORE3+dv_ttm 0 用 minute) | Layer 1 Phase 4.2 dependency 检查 | 0 真金风险 | **P2** (无 PT live minute 依赖, 但 13 trading days stale 是真实数据债务) |
| **2.1.3** | health_check + data_quality_check holiday-aware tolerance 升级 | 5-01~5-05 + 后续法定假日 tolerance 适配 (TradingDayProvider 接入), 减少 schtask LastResult=1 假阳 alert | 修代码 (≠ 本 reconnaissance scope, 留 Layer 2.2/2.3) | 修代码 risk | **P2** (假阳 alert noise, 不影响真生产) |
| **2.1.4** | `TradeRepository.insert_trade` (async) dead code 决议 | grep `TradeRepository\(\)` 0 真生产调用. evaluate deprecate vs PT live 重启时启用. | 0 | 0 | **P3** |
| **2.1.5** | `modifier_signals` (2025-12-31) / `backtest_daily_nav` (2024-12-31) legacy 表清理评估 | enumerate referrers + 决议 archive vs drop | 0 | 0 | **P3** |
| **2.1.6** | F-RECON-5 silent error_message=NULL 沉淀 + F-RECON-6 signals/schtask sink 漂移诊断 | 4-30 intraday_risk_check 72 error 真因诊断 + signal 写路径双 sink audit | 修代码候选 (Layer 2.2+) | 0 真金 | **P2** |

### E.1 推荐起手次序

1. **首推 2.1.1** (T0-19 audit chain backfill + verifier 修)
   - 4-29 是真生产事件, audit chain 缺失影响合规
   - 0 真金风险 (仅 read log + INSERT audit row)
   - PR #168 既有 hook 可直接复用, 无需新代码
   - verifier false-positive 是 Layer 1 Week 1 P0 修漏, 这次补
2. **次推 2.1.2** (minute_bars pipeline 诊断)
   - read-only 决议, 0 修代码
3. **2.1.3 / 2.1.6 留 Layer 2.2** (修代码 ≠ reconnaissance)
4. **2.1.4 / 2.1.5 留 Layer 2.3** (cleanup, 非紧急)

### E.2 不推荐 / scope 守门

- ❌ **不推荐**: 一起性把 2.1.1 ~ 2.1.6 全做 — 反 sub-task 串行交付铁律 23/24, 留 user 决议起 2.1.1 后再 plan 2.1.2
- ❌ **不推荐**: holiday tolerance 升级随手做 — 修代码超出 reconnaissance scope, 必走 Layer 2.2/2.3 独立 plan + reviewer

---

## §F transparency — 我没真测的

为反 anti-pattern v3.0 (cite 当真值), 列出本 audit **未真测**项目:

1. **emergency_close_20260429_104354.log 真 fill 数 vs T0-19 audit 期望差异**: PR #168 commit msg 标 "实测发现 17 fills (NOT 18)", 但本 audit 未真测 log 解析后 fill_by_order 真值. 留 sub-task 2.1.1 做.
2. **PT live 重启 gate prerequisite cite (SHUTDOWN_NOTICE_2026_04_30 §9)**: 本 audit 未跨读 SHUTDOWN_NOTICE. trade_log gap 与 PT 重启 gate 关系未深查.
3. **`scripts/health_check.py` data_fresh check 真 tolerance 阈值**: 实跑 stderr 标"期望>=2026-04-30", 但脚本内真硬编码逻辑未深读 (是 today / today-2 / today-N 计算?). 留 sub-task 2.1.3.
4. **`signals` 表写入路径**: 4-15~4-28 8 dates / 20/day, 真写入入口未 grep enumerate (不像 trade_log 走 5 INSERT, signals 真生产 INSERT 路径未 enumerate 是 §B 的 scope 外).
5. **PR #168 4-30 后 emergency_close 真**未跑过**: 4-30/5-01/5-02 期间 0 emergency_close 真 invoke, 因此 T0-19 hook 真生产真触发能力**仍未实测验证**. 留 sub-task 2.1.1 决议 (是否走 dry-run path 真测).

---

## §G 验收 checklist

- [x] §A trade_log 真测真值 (rows / dates / 4-29 cite verify) ✅
- [x] §B trade_log INSERT 5 真生产 paths + 1 audit + 调用方 enumerate ✅
- [x] §C 数据源 stale 真测 (9 表) ✅
- [x] §C2 schtask LastResult=1 真因 (health_check + data_quality_check 实跑) ✅
- [x] §D synthesis (3 独立 finding chain + 1 verifier false-positive + 2 silent obs gap) ✅
- [x] §E 候选 sub-task 6 enumerate + 推荐次序 ✅
- [x] §F transparency (5 未真测项目) ✅
- [x] 0 修代码 / 0 backfill / 0 dual_write sustained ✅
- [x] 0 PT 触碰 / 0 .env modifications sustained ✅

---

## §H 顶层结论

**Layer 2.1 reconnaissance 真测真值锁定**:

1. trade_log 88 rows / MAX=4-17 / 4-29 emergency_close 0 audit row — **真值 vs cite 0 drift, 但 4-29 真发单 18 持仓 audit chain 缺失** (PR #168 hook 4-30 后到, 4-29 历史未 backfill)
2. 5 真生产 INSERT path enumerate, 真生产写入活跃度 4-17 后真停 ≥ 11 trading days
3. 数据源 stale 3 独立 finding chain: trade_log gap (PT 暂停) / klines/daily_basic 4-28 (holiday-driven) / minute_bars 4-13 (~13 trading days, pipeline 真不存在)
4. verifier false-positive (T0-19 implementation check literal grep) + 2 silent obs gap (intraday_risk_check error_message=NULL / signals vs schtask sink 漂移)

**推荐起手**: sub-task 2.1.1 (T0-19 audit chain 4-29 历史 backfill 决议 + verifier 修), 0 真金风险, PR #168 既有 hook 复用.

**user 决议起**: 待 user 真决议 sub-task 2.1.1 起手 / 改其他 / 跳过 / 调整 scope.
