# MVP 3.3 Batch 2 Stage 3.0 — Real Cutover Plan (✅ EXECUTED Session 40, 2026-04-28)

> **状态**: ✅ **完结 — Stage 3.0 PR #116 + Stage 3.1 cleanup PR #118 (Session 40, 2026-04-28)**.
>   - 5-day gate 撤销 (用户挑战驱动 + 25 trade_dates bit-identical 实证)
>   - `signal_service.generate_signals` 内部走 SDK PlatformSignalPipeline.generate(S1, ctx)
>   - `_run_sdk_parity_dryrun` + `sdk_parity_scan.py` + `_build_sdk_strategy_context` 全删 (-970 行)
>   - SDK_PARITY_STRICT Windows User env 清理
>   - 16:30 schtask 真生产首跨 LastResult=0 + max_w_diff=0
>
> **以下为原始 plan draft, 历史 reference**:
>
> **状态**: PLAN DRAFT (2026-04-28 Session 40 中 ~14:50)
> **前置**: Step 2.5 STRICT mode live (PR #111 + #112), 1 周连续 STRICT OK 解锁条件
> **目标 Session**: Session 41+ (earliest Tuesday 5-04 if Tue 4-28 ~ Mon 5-04 全 STRICT OK)
> **Scope**: 替 `signal_service.generate_signals` (legacy compose path) → `PlatformSignalPipeline + PlatformOrderRouter` (SDK path) 作为生产 signal_phase 唯一信号生成路径

## 触发场景

Step 2 (PR #110 dual-run warn-only) + Step 2.5 (PR #111 STRICT raise on DIFF) 已落地. PR #112 14/14 历史 trade_dates pre-flip 验证 bit-identical (max_w_diff=0.00e+00). STRICT flip live (`SDK_PARITY_STRICT=true` Windows User env). Session 40 Tuesday 4-28 16:30 schtask 首次 STRICT 真跑.

**Stage 3.0 解锁条件** = 1 周连续 STRICT OK 累积:
- Tuesday 4-28 16:30
- Wednesday 4-29 16:30
- Thursday 4-30 16:30
- Friday 5-01: **法定节假日, A 股休市**. 注意: schtask trigger 仍 fire (Windows OS 不知 A 股日历), 但 `run_paper_trading.py` 的 `is_trading_day(conn, trade_date)` guard 会 early-return → process exit 0, signal_phase 不跑, **不计入 5 day gate**
- Monday 5-04 16:30 (5-02/5-03 weekend skip 同理 — schtask 不 trigger 因为 schedule 是 weekdays only)
- Tuesday 5-05 16:30
- Wednesday 5-06 16:30

= **5 个 trade_day 真生产 STRICT OK** (4-28/4-29/4-30/5-04/5-05) 后启动 Stage 3.0 PR.

**4-27 lookback gap interaction** (Session 40 reviewer P2.3 采纳): 4-27 DailySignal Mon 0xC0000142 失败 → klines/daily_basic/factor_values 4-27 当时缺. **Session 40 14:42 backfill 已修复** (5,481 rows klines/daily_basic, 131,544 factor_values, CORE 4 full coverage). 4-28 16:30 STRICT 跑用 4-27 真实数据 lookback, 不撞 gap. 4-28 计入 gate 正常 (假设 STRICT OK).

若未来重现类似 0xC0000142 → backfill 当日数据 + 该日 STRICT 跑视为 "data-recovery" 模式不计入 gate, 重启 5 day count.

## 生产 callers 实测 (Session 40 grep)

| 调用 | 位置 | 用途 | Stage 3.0 影响 |
|---|---|---|---|
| **L528-529** | `scripts/run_paper_trading.py` `run_signal_phase` (L528 instance, L529 `generate_signals` 调用) | **signal_phase 写信号到 signals 表** | ⚠️ **本 PR 改造 target** |
| L631-633 | `scripts/run_paper_trading.py` `run_execute_phase` (L631 instance, L633 `get_latest_signals` 调用) | execute_phase 读 latest signals | ✅ 不动 (读路径, signals 表 schema 不变) |
| L227 | `signal_service.py` `_write_signals` (internal) | `generate_signals` 内部调 | ⚠️ 拆掉或 wrap |
| L420 | `signal_service.py` `_write_signals` (def) | DB write 实施 | ⚠️ 复用或新写 |
| `sdk_parity_scan.py:110` | scan tool | 验证工具 | 🟢 Stage 3.0 后 deprecate (TODO marker 已留) |

只 1 处生产**写**路径 (L528). Scope 比 Session 39 估计的 "7 处" 小很多.

## 设计 (3 选 1)

### 选 A: Wrapper pattern (推荐)

`signal_service.generate_signals` 内部改走 SDK:

```python
def generate_signals(self, conn, strategy_id, trade_date, factor_df, universe, industry, config, dry_run):
    # SDK path (Stage 3.0 cutover)
    ctx = build_strategy_context(trade_date, factor_df, universe, industry, ...)
    pipe = PlatformSignalPipeline()
    strategy = StrategyRegistry.get(strategy_id)  # S1MonthlyRanking
    signals = pipe.generate(strategy, ctx)

    # Adapt to legacy SignalResult shape (target_weights, is_rebalance)
    signal_result = _signals_to_legacy_result(signals, prev_weights)

    if not dry_run:
        self._write_signals(conn, strategy_id, trade_date, signals_to_rows(signals))
    return signal_result
```

**优点**: L528 production 调用方无改动, sdk_parity_scan 可继续验证, 回滚仅 revert 1 文件. 渐进迁移.
**缺点**: 保留 SignalService 类作为 facade, 没真删 legacy 类 (短期接受).

### 选 B: Direct cutover

`run_signal_phase` L528 直接调 SDK, 删 SignalService.generate_signals:

```python
# Step 3: 信号生成 (Stage 3.0 SDK direct)
ctx = _build_sdk_strategy_context(trade_date, fv, universe, industry, ...)
signals = PlatformSignalPipeline().generate(S1MonthlyRanking(), ctx)
orders = PlatformOrderRouter().route(signals, current_positions, capital_alloc)
_write_signals_sdk(conn, strategy_id, trade_date, signals)  # 新 writer
```

**优点**: 最干净, 删 legacy 代码 ~500 行.
**缺点**: 改动面广 (run_paper_trading + signal_service + execute_phase L631 兼容验证), 回滚成本高.

### 选 C: Wrapper + 后续删 legacy (二阶段)

Stage 3.0 = 选 A wrapper.
Stage 3.1 = 删 legacy (Stage 3.0 1 周稳定后).

**推荐选 C**: 最小风险渐进路径. Stage 3.0 wrapper PR 先稳, Stage 3.1 干净删除留 1 周 buffer.

## 待解决设计问题 (Session 41+ plan 时回答)

1. **SDK Signal dataclass → signals 表列映射**:
   - SDK Signal: `code`, `target_weight`, `factor_scores: dict`, `metadata: dict`
   - signals 表: `code`, `target_weight`, `action`, `factor_score`, `factor_breakdown`, `created_at`, `strategy_id`, `trade_date`, `execution_mode`
   - Gap: SDK 没有 `action` 字段 (rebalance/hold). 需在 wrapper 中从 `prev_weights vs current_weights` 推导
   - Gap: `factor_score` legacy 是 weighted sum, SDK 是 raw factor_scores dict — 需 collapse

2. **`is_rebalance` 推导**:
   - Legacy: SignalService 内部判断 (基于月份末 + force_rebalance flag)
   - SDK: Strategy.generate_signals 已返 metadata, 但不一定有 is_rebalance — 需确认 S1MonthlyRanking metadata
   - Mitigation: PaperBroker 已有 "调仓日" 判断 (run_paper_trading log "2026-04-24 非调仓日"), wrapper 复用

3. **行业集中度 / Beta / 持仓重合度 logging**:
   - Legacy `generate_signals` log 5 行风控指标 (行业 / Beta / 重合度 / 因子覆盖率)
   - SDK `pipe.generate` 仅 log 1 行 (`signals=20 total_w=0.97`)
   - Mitigation: wrapper 内补 logging, 或单独 hook

4. **Regression bit-identical 验证**:
   - regression_test.py --years 5 max_diff=0 (铁律 15)
   - 但 regression 走的是 backtest 路径不是 signal_phase, 可能不直接验证 signals 表 row equality
   - 需新增: signal_phase 跑 4-24 历史日, 比 signals 表 row vs Mon 4-27 SDK 写入 row, max_diff=0
   - 或: 复用 sdk_parity_scan.py 比 weights, signals 表写入 round-trip 单测

## 测试 + 验收

- 新单测: `test_signal_service_sdk_wrapper.py` ~15 tests (cover wrapper signal mapping / is_rebalance / action 推导)
- 回归: regression 5yr+12yr max_diff=0 (铁律 15)
- 集成: smoke test `test_mvp_3_3_stage3_live.py` (subprocess signal_phase --dry-run + 验 signals 表 row 一致性, 铁律 10b)
- 手工: 1 个生产 trade_day --dry-run (e.g., 5-05 Tuesday) 跑完整 signal_phase, 比 signals 表 dry-run row vs SDK 直接生成 signals
- 1 周生产观察 (Stage 3.0 wrapper merge 后, 5-05 ~ 5-12): ⚠️ **reviewer P3.1 采纳关键修正**: Stage 3.0 wrapper 内 generate_signals 改走 SDK 后, 原 `_run_sdk_parity_dryrun` 的 dual-run 比对变成 "SDK-via-wrapper vs SDK-direct" = always 0 diff by construction, 失去 diff-detection 能力. 必须重设计观察机制:
  - **Option A (推荐)**: Stage 3.0 wrapper merge 前, **冻结 1 个 reference snapshot** (如 5-04 Monday 跑 legacy + 写 signals 表 → 存 cache/baseline/signals_5_04_legacy.parquet 作 truth set)
  - **Option B**: wrapper 内保留临时 dead-code 路径 "compute via legacy too" 仅 logger.info 比对, 1 周后 Stage 3.1 删 (但此期间 legacy 路径仍活跃, 维护成本)
  - **Option C**: 直接相信 Step 2/2.5/3.0 的 5+ trade_day pre-cutover 验证 + regression bit-identical, 不再做 post-cutover dual-run (依赖 1 周生产 NAV/signals 表 row review 而非自动比对)
  - 选 Option A 平衡风险/复杂度, Stage 3.0 wrapper PR 时同 PR 加 reference snapshot fixture
- 任 1 天 DIFF (legacy reference snapshot vs Stage 3.0 wrapper output) 立即回滚

## 回滚

- Wrapper PR (选 C 第 1 阶段): `git revert <PR sha>` → 1 文件 revert, 即恢复 legacy. 不影响 PR #110/#111/#112 STRICT mode (后者继续 dual-run warn).
- Legacy 删除 PR (选 C 第 2 阶段): 同上但需先反向恢复 legacy 文件 → 复杂度 +1, 1 周稳定后才上.

## 时间估算

| Sub-stage | 工作量 | 解锁条件 |
|---|---|---|
| Stage 3.0 wrapper PR | 1-2 天 | 5 个 trade_day 全 STRICT OK |
| Stage 3.1 legacy 删除 | 0.5-1 天 | Stage 3.0 1 周稳定 |
| sdk_parity_scan.py deprecate | 5 min | Stage 3.0 完结 (legacy 路径删后 scan 无意义) |

总: ~3 天工作量 + 2 周 buffer (5 trade days 解锁 + 1 周 stage 3.0 稳定).

## 关联

- 前置 PRs: #107 (batch 1) / #108 (batch 2.1) / #109 (batch 3) / #110 (Step 2 dual-run) / #111 (Step 2.5 STRICT) / #112 (parity scan + flip)
- LL: LL-082 / LL-083 / LL-084 / LL-085 / LL-086 / LL-087
- 铁律: 16 (信号路径唯一) / 15 (regression bit-identical) / 33 (fail-loud) / 42 (PR governance)
- 闭幕: Stage 3.1 删 legacy 后, MVP 3.3 Signal-Exec Framework 100% 完结, MVP 3.4 Event Sourcing 解锁
