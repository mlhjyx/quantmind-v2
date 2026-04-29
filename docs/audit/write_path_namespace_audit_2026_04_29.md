# 写路径命名空间漂移审计 — 2026-04-29

> **作者**: Risk Framework P0 修批 1
> **触发**: 2026-04-29 卓然 -29% / 南玻 -10% 7 天 risk_event_log 0 行
> **范围**: 所有写持仓/净值/资金流水/风控状态的代码路径，核 `execution_mode` 来源
> **批次归属**: 本审计在批 1 完成；写路径漂移修复留批 2

---

## TL;DR

`backend/.env: EXECUTION_MODE=paper`（自 4-20 17:47 cutover live 后某时点改回），但 4 个核心写路径中**有 2 个 hardcoded `'live'` 不跟随 settings**，导致 DB 持续以 live 命名空间存数据。每天 14:30 / 09:00–14:55 风控读路径用 `settings.EXECUTION_MODE='paper'` → trade_log/position_snapshot WHERE 0 行 → entry_price=0 → 全规则 silent skip → 0 trigger / 0 钉钉 / 0 risk_event_log（卓然 -29% 7 天 0 alert 的代码层根因）。

| 写点 | mode 来源 | 是否合规 |
|---|---|---|
| `pt_qmt_state.save_qmt_state` | **5 处 hardcoded `'live'`** | ❌ BUG |
| `execution_service._execute_live` 写 trade_log | **1 处 hardcoded `'live'`** | ❌ BUG |
| `risk_control_service._upsert_cb_state_sync` | `settings.EXECUTION_MODE` 动态 | ✅ |
| `signal_service._write_signals` | hardcoded `'paper'` | ✅ ADR-008 D3-KEEP（设计意图） |

---

## 1. 实测命名空间分布（DB 查询，2026-04-29 17:00）

### 1.1 position_snapshot 最近 30 天
```sql
SELECT execution_mode, COUNT(*), MIN(trade_date), MAX(trade_date)
FROM position_snapshot
WHERE trade_date >= CURRENT_DATE - 30 GROUP BY 1;
-- ('live', 295, 2026-04-02, 2026-04-28)
```
**全 295 行都是 `live`，0 paper**。

### 1.2 trade_log 最近 30 天
```sql
-- ('live',  68, 2026-04-14, 2026-04-17)
-- ('paper', 20, 2026-04-16, 2026-04-16)   ← 仅 4-16 一天 backfill 残留
```
paper 仅 4-16 一天的 20 行（Session 14 PR #26 backfill），其余全是 live。

### 1.3 performance_series 最近 14 天
```sql
-- ('live', 10, 2026-04-15, 2026-04-28)   ← 全 live
```

### 1.4 circuit_breaker_state（2 行各占一空间）
```
('28fc37e5-...', 'live',  L0, 2026-04-20, '正常',                 mult=1.00, 4-28)
('28fc37e5-...', 'paper', L0, 2026-03-25, '初始化(首次运行)',      mult=1.00, 4-20)
```
live 行 4-28 仍在更新；paper 行 4-20 后停滞（"初始化"状态）。

### 1.5 .env 实测
```
EXECUTION_MODE=paper                       ← 4-29 10:58
backend/.env.bak.20260420-session20-cutover  ← 4-20 17:47 LL-061 cutover live 节点
```
推断时间漂移：4-20 17:47 cut to live → 4-29 10:58 之前某点改回 paper（不在 git 历史，无精确点）。

---

## 2. 4 个核心写入点详细审计

### 2.1 ❌ `pt_qmt_state.save_qmt_state`（**主要漂移源**）

**文件**: [backend/app/services/pt_qmt_state.py](../../backend/app/services/pt_qmt_state.py)
**调用方**: `scripts/run_paper_trading.py` Step 1.5（signal phase 16:30）& Step 5.x（execute phase 09:31）
**职责**: 把 QMT 实际持仓/净值写入 `position_snapshot` + `performance_series`

**5 处 hardcoded `'live'`**:

| 行号 | 上下文 | SQL |
|---|---|---|
| L46-47 | `_assert_positions_not_evaporated` 读前一日 snapshot | `WHERE strategy_id = %s AND execution_mode = 'live' AND trade_date < %s` |
| L54-55 | 同上 prev count check | `WHERE strategy_id = %s AND execution_mode = 'live' AND trade_date = %s AND quantity > 0` |
| L147 | `_save_qmt_state_impl` 读 trade_log avg_cost | `WHERE strategy_id = %s AND execution_mode = 'live' AND direction = 'buy' AND code IN (...)` |
| L158 | `_save_qmt_state_impl` DELETE 当日 snapshot | `DELETE FROM position_snapshot WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s` |
| L171 | `_save_qmt_state_impl` INSERT position_snapshot | `VALUES (%s, %s, %s, 'astock', ..., 'live')` |
| L197 | `_save_qmt_state_impl` 读 perf_series peak | `WHERE execution_mode = 'live' AND strategy_id = %s` |
| L214 | `_save_qmt_state_impl` UPSERT perf_series | `VALUES (%s, %s, 'astock', ..., 'live')` |

**注释自承（L81-82）**:
> 2026-04-15修复: execution_mode 从 'paper' 改为 'live', 对齐
> execution_service._save_live_fills 和 daily_reconciliation.write_live_snapshot。

Session 15c 这次 "对齐" 把 `'paper'` → `'live'` hardcoded，本意是统一命名空间，但**没接 `settings.EXECUTION_MODE`**——把灵活配置变成静态硬编码。这是漂移在写路径生效的根本原因。

**修法（批 2）**:
- 选项 A: 替为 `settings.EXECUTION_MODE`（5 处 + 2 个 INSERT VALUES `'live'` literal）
- 选项 B: 函数签名加 `execution_mode: str` 参数，调用方显式传（更可测）

**Contract test 守门**: `backend/tests/test_execution_mode_isolation.py::test_save_qmt_state_uses_settings_execution_mode`（xfail strict，批 2 修后自动 XPASS strict 提示删 xfail）。

---

### 2.2 ❌ `execution_service._execute_live` 写 trade_log

**文件**: [backend/app/services/execution_service.py](../../backend/app/services/execution_service.py)
**调用方**: `ExecutionService.execute_rebalance` 在 `execution_mode == "live"` 分支
**职责**: 把 QMT live 真实成交回填 `trade_log`

**1 处 hardcoded `'live'`** (L373-378):
```python
"""INSERT INTO trade_log
   (code, trade_date, strategy_id, direction, quantity,
    fill_price, slippage_bps, commission, stamp_tax,
    total_cost, execution_mode, executed_at)
   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'live', %s)
   ON CONFLICT DO NOTHING"""
```

讽刺：函数 `execute_rebalance` 签名 L63 已有 `execution_mode: str = "paper"` 参数，且 L146 已根据它路由到 `_execute_live` / `_execute_paper`，但**到了 SQL 这层又把 mode hardcode 回去**。这是命名空间约定二次破坏。

**修法（批 2）**: VALUES 中 `'live'` 替为 `%s` + 参数 `execution_mode`（已在函数局部作用域）。

**Contract test 守门**: `test_save_live_fills_uses_settings_execution_mode`（xfail strict）。

---

### 2.3 ✅ `risk_control_service._upsert_cb_state_sync`（合规）

**文件**: [backend/app/services/risk_control_service.py:1236-1303](../../backend/app/services/risk_control_service.py)
**注释自承（L1265）**: `# ADR-008 D2: circuit_breaker_state 写按 settings.EXECUTION_MODE 动态`

**实测 L1290-1292**:
```python
cur.execute(
    """INSERT INTO circuit_breaker_state ... VALUES (%s, %s, ...)""",
    (
        strategy_id,
        settings.EXECUTION_MODE,   # ← 动态
        ...
    ),
)
```

读路径 `_load_cb_state_sync` (L1213-1220) 同样动态 ✅。

但 cb_state 表已被漂移污染 — DB 当前 2 行各占 paper/live 命名空间，paper 行卡在 4-20 "初始化(首次运行)" L0，live 行 4-28 仍更新。读哪个看 `settings.EXECUTION_MODE`，当前 paper 模式读 paper 行 → 永远 L0。这是数据层漂移，非代码层。

**Contract test 守门**: `test_save_risk_state_uses_settings_execution_mode`（PASS，反向防 future refactor 误改）。

---

### 2.4 ✅ `signal_service._write_signals`（D3-KEEP 合规）

**文件**: [backend/app/services/signal_service.py:336/494](../../backend/app/services/signal_service.py)
**ADR-008 D3 设计意图**: signals 表跨 paper/live 命名空间共享（**唯一 cross-mode 表**），`_write_signals` / `get_latest_signals` / DELETE 全部 hardcoded `'paper'` 是契约。
**LL-060 反证**: Session 19 误判此 hardcoded 为 BUG，事后 Scan 验证 3 步澄清这是 D3-KEEP 不是漏修。

**实测**:
- L336 `get_latest_signals`: `SELECT ... FROM signals WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'paper'`
- L494 `_write_signals`: `INSERT INTO signals (...) VALUES (..., 'paper', ...)`

**已有 D3 SAST 守门**: `test_d3_signal_service_signals_table_stays_paper` (line 460+)、`test_d3_run_paper_trading_signals_update_stays_paper` (line 484+)。

**Contract test（命名规范化 wrapper）**: `test_write_signals_keeps_paper_per_d3`（PASS，与既有 D3 守门同源）。

---

## 3. 漂移影响传播链

```
.env: EXECUTION_MODE=paper (4-29)
   │
   ├──→ run_paper_trading.py / FastAPI / Celery Beat 启动 → settings.EXECUTION_MODE='paper'
   │
   ├── 写路径 (BUG hardcoded 'live')
   │     ├── pt_qmt_state.save_qmt_state            → 写 position_snapshot 'live'
   │     ├── execution_service._execute_live (paper 模式不调本分支) → 不写
   │     └── daily_reconciliation.py 11 处 'live'   → 写 perf_series/snapshot 'live'
   │   结果: DB 持续以 live 命名空间填新数据
   │
   └── 读路径 (settings 动态)
         ├── enricher.load_entry_prices('paper')    → trade_log WHERE 'paper' = 0 行
         ├── DBPositionSource.load('paper')         → snapshot WHERE 'paper' = 0 行
         ├── _load_cb_state_sync                    → cb_state WHERE 'paper' = 4-20 stale
         └── check_circuit_breaker_sync             → perf_series WHERE 'paper' = 0 行 → "首次运行" L0
   
风控决策点 (14:30 / 9-14 */5):
   │
   build_context('paper') → entry_price=0 (load_entry_prices 0 行) →
   │
   ├── PMSRule.evaluate                → entry<=0 silent skip
   ├── SingleStockStopLossRule.evaluate → entry<=0 silent skip
   ├── PositionHoldingTimeRule         → entry_date=None silent skip
   ├── NewPositionVolatilityRule        → entry_date=None silent skip
   ├── IntradayPortfolioDropRule       → prev_close_nav=None silent skip
   └── CircuitBreakerRule              → cb_state L0 stale → no transition

结果: 0 trigger / 0 alert / 0 risk_event_log row
真金 -29% 卓然股份 7 天 silent. ★★★ LL-081 zombie 模式变种 ★★★
```

---

## 4. 推荐 .env 处置策略

### 短期（批 1 完成后立即执行）

**选项 A（推荐）**: 把 `.env` 改回 `EXECUTION_MODE=live` —— 与持仓数据 DB 命名空间对齐，启动断言通过，风控读路径立即看到真实持仓，PMSRule / SingleStockStopLoss 等正常评估。

**风险**: 任何还在依赖 `settings.EXECUTION_MODE='paper'` 走 paper 分支的代码会切换行为（如 ExecutionService.execute_rebalance L146 路由到 `_execute_live`）。当前 PT 已被用户清仓只剩 1 股 + DailyExecute schtask disabled，cutover 风险低。

**选项 B**: 保持 `.env=paper` 等批 2 修写路径漂移源头。
**风险**: 启动断言会 RAISE 拒绝启动 FastAPI / Celery / PT。需先 disable 启动断言（或 .env 加 `SKIP_NAMESPACE_ASSERT=1`）暂缓。**不推荐** —— 拖延漂移修复 = 持续真金风险。

### 中期（批 2 完成后）

写路径漂移修完，`pt_qmt_state.save_qmt_state` 接 `settings.EXECUTION_MODE`，`.env` 切换不再需要 DB 数据迁移。

### 长期（迁移工具）

如要真切到 paper 命名空间分析，写一次性迁移脚本：
```sql
UPDATE position_snapshot SET execution_mode='paper'
WHERE strategy_id='28fc37e5-...' AND execution_mode='live';
-- 同样迁 trade_log / perf_series / cb_state / cb_log
```
但当前无迫切需求，DB 数据保留 live 命名空间不影响功能（只要 .env 也对齐）。

---

## 5. 批次划分（防爬升）

| 批 | 范围 | 状态 |
|---|---|---|
| **批 1（本批）** | 诊断 + LL-081 guard + 启动断言 + 5.9 hardcoded 0.5 修 + 4 contract tests + 本审计文档 | ✅ |
| **批 2** | (a) 修 `pt_qmt_state.save_qmt_state` 5 处 hardcoded 'live' → settings；(b) 修 `execution_service._execute_live` trade_log VALUES 'live' → 函数参数；(c) `daily_reconciliation.py` 11 处 'live' 评估（盘后对账，可能是 D5 同 D3-KEEP 设计意图保留，需确认）；(d) `LoggingSellBroker → QMTSellBroker` 真接 broker.sell；(e) `auto_sell_l4=True` 决策 | 🟡 待启 |
| **批 3** | (a) `approve_l4.py` 2 处 hardcoded 'paper' 修；(b) `api/pms.py` deprecate 或重写走 RiskFramework；(c) `dedup` key 加 code 维度；(d) PT live restart 7 项 pre-flight checklist 走完 | 🟡 待启 |

---

## 6. 关联文档

- [PROJECT_DIAGNOSTIC_REPORT.md](../../PROJECT_DIAGNOSTIC_REPORT.md) — 法医审计（顶层）
- [STATUS_REPORT.md](../../STATUS_REPORT.md) — 批 1 状态 + Tier 0 债清单 + pre-flight checklist
- LL-060 / LL-061 / LL-081 — 历史 ADR-008 命名空间教训
- ADR-008 — execution_mode 命名空间契约（D2 / D3 / D4）
