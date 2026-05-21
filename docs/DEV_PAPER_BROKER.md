# DEV_PAPER_BROKER — Paper Broker Design Specification

> **Plan v8 P1-39 closure** (sediment-then-implement, 反 LL-190 sediment-only)
> **Source**: `backend/engines/paper_broker.py` + `backend/engines/backtest_engine.py:SimBroker`
> **Created**: 2026-05-19 Session 58+1 evening
> **Status**: 起手 spec, future enhancement Phase J 候选

---

## §1 Purpose & Scope

Paper Broker 是 backtest SimBroker 的**状态持久化包装** — 同样的撮合/费用/T+1 逻辑, 但状态从 DB 加载/写回, 跨 process restart 持久.

**Use cases**:
1. **PT (Paper Trading) dry-run** — Path B Phase B-1 paper-mode (current state, 5-19 evening)
2. **Backtest regression** — pytest 用 PaperBroker 真值 replay 历史 trade_log
3. **Strategy iteration** — researcher 改 alpha 因子后, dry-run 看新 signal 行为

**Not in scope**:
- Real broker (国金 miniQMT) — 走 `backend/engines/broker_qmt.py` + xtquant
- Cross-venue routing — 单 A 股, 无 cross-venue 需求

---

## §2 Architecture

### §2.1 Layered Design (沿用 backtest_engine SimBroker)

```
PaperBroker (state persistence) — backend/engines/paper_broker.py
    ↓ delegate
SimBroker (matching + costs + T+1) — backend/engines/backtest_engine.py
    ↓ uses
- Fill / PendingOrder dataclasses
- 三因素 slippage_model (spread + impact + overnight_gap)
- 限价/涨跌停 guard
- 集合竞价 vs 连续竞价 撮合
```

### §2.2 PaperState 持久化

```python
@dataclass
class PaperState:
    cash: float           # 当前现金 (Decimal preferred future)
    holdings: dict[str, int]  # code → shares 当前持仓
    nav: float            # 净值 (cash + market_value)
    last_trade_date: date | None
    last_rebalance_date: date | None
```

**DB persistence** (沿用 PT live 同一 schema):
- `position_snapshot` table — current holdings (UPSERT on snapshot_date)
- `nav_history` table — daily NAV time series
- `trade_log` table — fills audit trail (INSERT-only)

---

## §3 T+1 Semantics (A 股关键)

A 股 T+1 制度: 当日买入的股票当日不可卖. 以下为 PaperBroker / SimBroker 的**真实现**
(code-truth verify, Plan 2 2026-05-20).

### §3.1 Share-side T+1 — 结构性保证 (非显式 guard)

PaperBroker 是**月频调仓**引擎. `paper_broker.py:_do_rebalance` 在单次
`execute_rebalance` 调用内**先卖后买**: 卖出操作的 `holdings` 来自最近一次
`position_snapshot` 快照 (上一次调仓时 `save_state` 写入), 买入在卖出之后执行;
两次调仓相隔 ~20 个交易日. 因此
"当日买入又当日卖出" 在当前架构下**结构上不可能发生** —— share-side T+1 规则由
调仓架构本身保证. `process_pending_orders` (T+1 封板补单) 只买不卖, 同样不产生违规.

**无 `last_trade_date_per_code` 字段, 无 `T1Violation` 异常** —— 当前架构下它们会是
死代码 (永不触发). 显式 fail-loud guard 是 Phase J §8.2 (real-time / intraday fill)
的前置项: 一旦支持日内成交, 同日 buy-then-sell 才可能发生, 届时才需要显式 guard.

**CI 锁定**: `backend/tests/test_paper_broker.py::TestT1Invariant` 断言单次调仓内
无任何 code 同时出现 buy fill 与 sell fill (结构不变量).

### §3.2 Cash-side — 卖出回款当日可用

`SimBroker._sell_proceeds_today` (`backtest/broker.py`): 卖出净回款当日即计入
`cash`, 当日买入可复用 (A 股资金 T+0 可复用). `new_day()` 每日重置该计数器.

### §3.3 Cross-Day State Continuity

T 日收盘后 `save_state` 写回 DB (position_snapshot / performance_series /
trade_log) → T+1 日 `load_state` 从 DB 加载. holdings 跨进程持续 (Servy restart
不丢 state); T+1 卖出 yesterday-buy 合法 —— 这正是 §3.1 结构性保证的另一面:
跨调仓周期的持仓本就是上一周期买入的.

---

## §4 Cost Model (沿用 SimBroker)

### §4.1 三因素 Slippage (铁律 18)

`slippage_bps = spread_bps + impact_bps + overnight_gap_bps`

- **spread_bps** — bid-ask 估算 (固定 1bps for active stocks, 历史 BJ 高至 10bps)
- **impact_bps** — 三因素模型 (`backend/engines/slippage_model.py`):
  - `f(quantity, ADV_20)` — buy/sell 不对称
  - Bayesian quarterly recalibration (P0-10 closure)
- **overnight_gap_bps** — 跨日 limit order 估算 (5bps default)

### §4.2 Commission

- 国金 PT 模型: **万 0.854** (min ¥5/笔)
- 印花税: 2023-08-28 前 0.1%, 后 0.05% (卖出)
- 过户费: 0.001%

### §4.3 H0 Verification (铁律 18)

季度复核: 实盘 trade_log vs PaperBroker backtest 同 signal 同 trade_date, 真值 slippage diff < 5bps.

- Implementation: `backend/app/tasks/slippage_calibration_tasks.py:quarterly_recalibrate` (P0-10 closure)

---

## §5 Order Lifecycle

### §5.1 Pending → Filled

```
1. place_order(spec) → PendingOrder(status=PENDING, expected_price=X)
2. _try_fill(now, market_data):
   a. Check 涨跌停: skip if blocked
   b. Check liquidity: skip if 0 volume
   c. Apply slippage: filled_price = expected_price * (1 ± slippage_bps / 10000)
   d. Generate Fill(code, qty, price, ts, status=FILLED)
   e. PendingOrder.status = FILLED
3. holdings[code] += signed_qty (+buy / -sell)
4. cash -= (filled_price * qty + commission + tax)
```

### §5.2 Pending → Cancelled

- L4 STAGED `cancel_deadline` 触达 (ADR-027 §2.2)
- P1-25 closure: `cancel_window_minutes` constructor injection (yaml-driven)
- 集合竞价 09:25 / 14:55 final auction cutoff

### §5.3 Pending → Rejected

- LIVE_TRADING_DISABLED=true (paper-mode hard gate)
- pt_live.yaml universe filter (BJ / ST / 停牌)
- 资金不足 (cash + cost > available)

---

## §6 SimBroker vs PaperBroker Differences

| Aspect | SimBroker (backtest) | PaperBroker (paper-mode dry-run) |
|---|---|---|
| State | In-memory only | DB persistent (position_snapshot + nav_history + trade_log) |
| Time | trade_date param drives | datetime.now(SH) drives |
| Order rejection | 0 outside rules | `LIVE_TRADING_DISABLED=true` extra gate |
| Fill announcement | Return Fill obj | INSERT trade_log row (audit) |
| Reproducibility | Same input → same output (max_diff=0 铁律 15) | Same input → same output (T+1 state from DB) |
| Cross-process | None | Servy restart 不丢 state |

---

## §7 Test Coverage

### §7.1 Existing tests

- `backend/tests/test_paper_broker.py` — PaperBroker 行为单测 (Plan 2 NEW): load_state
  cold-start / needs_rebalance 月末逻辑 / execute_rebalance 先卖后买 / T+1 结构不变量
  / process_pending_orders 补单
- `backend/tests/test_base_broker.py` — BaseBroker 统一接口 (PaperBroker 子类)
- `backend/tests/test_pending_orders.py` — execute_rebalance / process_pending_orders
  返回契约 + 封板 → PendingOrder
- `backend/tests/test_execution_mode_isolation.py` — load_state 按 execution_mode 隔离
- SimBroker 撮合 / 费用: `test_broker_costs.py` / `test_broker_executor.py`

### §7.2 Gap

- ~~T+1 cross-day violation test~~ → ✅ Plan 2: `TestT1Invariant` 锁定结构不变量
  (当前架构 T+1 由先卖后买保证). 显式 `T1Violation` raise 测试 → Phase J §8.2
  (随 real-time fill guard 一并补).
- Cost model alignment H0 < 5bps 季度复核 — 走 `slippage_calibration_tasks`
  (Plan v10 P0-10 closure, 铁律 18).

---

## §8 Future Enhancement (Phase J)

### §8.1 Multi-account support

- `account_id` field on PaperState
- 多策略 paper-trade 隔离 (single user but multi-strategy)

### §8.2 Real-time fill mode

- 当前: Beat 16:30 SH 收盘后 batch fill
- Phase J: tick-level fill (consume qm:qmt:status Redis stream)
- 用 case: intraday signal (currently 0 use case, 但 V3 §16 Bull/Bear LLM 可能 trigger 真实 intraday)
- **T+1 显式 guard 前置于此** (§3.1): real-time / intraday fill 下同日 buy-then-sell
  才可能, 届时 SimBroker 需 `_bought_today` set + `execute_sell` fail-loud
  (`T1ViolationError`). 当前月频架构下结构性保证已足够.

### §8.3 Cross-asset (deferred)

- DEV_FOREX archived (P1-37, 5-19, deferred Phase 2+)
- Stocks-only sustained

---

## §9 Related ADRs

- ADR-008 — PT 命名空间契约
- ADR-010 — PMS 并入 Risk Framework
- ADR-027 — L4 STAGED + 反向决策权 + 跌停 fallback
- ADR-085 — Path B Staged Paper-Dryrun 5d (5-19)

## §10 Related LLs

- LL-035 — Frontend API response format
- LL-066 — DataPipeline subset-column UPSERT
- LL-180 — QMT connect 5-axis fix
- LL-181 — Beat death silent NOT-GATING
- LL-183 — dry_run silent NOT-GATING
- LL-188 — sediment drift forensic

---

**Maintenance**: P1-39 起手 sediment, Phase J 候选 deep expansion (T+1 violation test + multi-account + tick-level).
**Cross-ref**: backend/engines/paper_broker.py + SimBroker (backtest_engine.py)
**Last updated**: 2026-05-20 Plan 2 (§3 T+1 code-truth correction + §7 test consolidation)
