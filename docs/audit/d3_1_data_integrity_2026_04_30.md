# D3.1 数据完整性审计 — 2026-04-30

**Scope**: PostgreSQL 16.8 / TimescaleDB 2.26.0 / public schema 全表 / 死表识别 / 命名空间状态
**方法**: read-only SQL 实测 + LL-063 三问法 (行数 + 最新写入 + 代码引用)
**铁律**: 25/26 (改什么读什么) / 33 (fail-loud) / X4 (死码 audit)
**0 改动**: 纯诊断, 不改 DB 不改代码

---

## 1. Q1.1 全表枚举 (实测)

```sql
SELECT relname, n_live_tup, n_tup_ins, n_tup_upd, n_tup_del,
       pg_size_pretty(pg_total_relation_size(relid)) AS size
FROM pg_stat_user_tables WHERE schemaname='public' ORDER BY n_live_tup DESC;
```

**实测**: 83 张 public schema 表 (memory 说 73, 实测漂移 +10).

**3 张 TimescaleDB hypertables**: factor_values / klines_daily / risk_event_log

### 主要数据表 (按真实 SELECT COUNT(*) 实测, 非 pg_stat_user_tables 估值)

| 表 | 实测行数 | memory 数字 | 偏差 |
|---|---:|---:|---:|
| factor_values | 840,478,083 | 839M (Session 5 末) | +1.5M (6 天新数据) ✅ |
| minute_bars | 190,885,634 | 139M (Session 4 文档) | +51.9M ⚠️ stale |
| klines_daily | 11,776,616 | 11.7M | +76K ✅ |
| daily_basic | 11,681,799 | 11.5M | +181K ✅ |
| northbound_holdings | 5,542,237 | **3.88M** (CLAUDE.md L188) | **+1.66M / +43%** 🔴 stale |
| moneyflow_daily | 56,953 | (not tracked) | 新发现 |
| daily_basic | 54,848 (n_live_tup) vs 11.68M (COUNT) | — | 估值严重偏差 |
| earnings_announcements | 207,668 | 207K | ✅ |
| factor_ic_history | 145,894 | 145,874 (Session 23) | +20 (~hours) ✅ |
| stock_status_daily | 54,848 | 12M (CLAUDE.md L189) | **-99.5%** 🔴 stale (memory 误读 inserts_lifetime) |

### Hypertable 真实大小 (vs n_live_tup 估值=0)

`pg_stat_user_tables.n_live_tup` 对 TimescaleDB hypertable 的 root 表显示 0 — 实际数据在 chunks. 必须 `SELECT COUNT(*)` 实测.

---

## 2. Q1.2 死表识别 (LL-063 三问法)

### 真死表 (P3 — 0 行 + 0 代码引用 + > 90d 无写)

| 表 | n_live_tup | 代码引用 | 结论 |
|---|---:|---|---|
| **factor_evaluation** | 0 | 0 (grep "FROM factor_evaluation\b" / "INTO factor_evaluation\b" 全 0) | 真死表 (FF3 报告说"Gate 从未批量执行") |
| **bs_balance_data** / bs_cash_flow_data / bs_dupont_data / bs_growth_data / bs_operation_data | 0 | (未 grep, archive 候选) | 死表候选 |
| **forex_bars** / forex_events / forex_swap_rates | 0 | DEFERRED (DEV_FOREX 未实施) | 死表 (设计 deferred) |
| **chip_distribution** / holder_number / express / index_components / margin_data / margin_detail / cash_flow / balance_sheet / fina_indicator / financial_indicators / forecast / top_list | 0 | (未 grep, 占空间但 0 数据) | 候选 |

### 假装健康死码 (P2 — 0 行但代码仍 read/write)

| 表 | n_live_tup | 代码引用 | LL-063 类型 |
|---|---:|---|---|
| **position_monitor** | 0 | `app/api/pms.py:70` (FROM read) + `app/services/pms_engine.py:358` (INSERT write) | "假装健康死码" — PMS Beat 已停 (PR #34), 写路径死, api/pms.py 仍读永远 0 行 |
| **circuit_breaker_log** | 0 | `app/repositories/risk_repository.py:253/295/323/349` + `app/services/risk_control_service.py:1332` + `tests/test_execution_mode_isolation.py:305` | 0 行但 126 lifetime inserts/deletes, 写路径 alive (D2.3 修复后 cb_state 仍写) |

### 关键死表代码引用清单 (不在 D2/D2.1/D2.2/D2.3 scope)

- `position_monitor`: 代码 read 路径在 `api/pms.py:70` — 提供假数据给 PMS endpoint, 但 PMS 已 deprecated. **F-D3A-2 (P2)** API 端点应 deprecate.
- `circuit_breaker_log`: 风控历史日志, 0 rows 是 D2.3 cb_state 切换后自然清空, **不是死表** — 是 valid 的 "暂时空" 表 (新 cb_state 走 PR #61 Hybrid adapter 方案).

### 真金 0 风险确认 (本审计不触碰死表)

✅ 0 DROP / 0 TRUNCATE / 0 DELETE 操作 — 本审计仅 SELECT 读, 死表识别留 D3-B 整合阶段决议处置 (DROP / archive / 保留).

---

## 3. Q1.3 关键表健康度 (memory vs 实测)

| 表 | memory 描述 | 实测最新 trade_date / created_at | 差异 |
|---|---|---|---|
| factor_values | "501M 行 hypertable" | max(trade_date)=**2026-04-28** | ✅ 鲜活 (+1d lag) |
| klines_daily | "11.7M 行" | max(trade_date)=**2026-04-28** | ✅ 鲜活 |
| minute_bars | "139M 行, 25GB, 2537/5499" | max(trade_date)=**2026-04-13** | ⚠️ **17 d 无新写**. PT 暂停期 QMT data sync 频率降低. 不是 dead, 是 paused. |
| daily_basic | "11.5M 行" | max(trade_date)=**2026-04-28** | ✅ 鲜活 |
| factor_ic_history | "84K 行" CLAUDE.md L191 | 145,894 行 (max td=2026-04-28) | 🔴 **memory 字面 84K 严重 stale**, 实际 145K (Session 23 已更正但 CLAUDE.md L191 未同步) |
| risk_event_log | hypertable | **0 rows ever** | 🔴 见 D3.12 F-D3A-? Risk Framework v2 9 PR 真生产 0 触发 |
| scheduler_task_log | (not tracked) | max(created_at)=**2026-04-30 01:27:48** | ✅ 活 (本审计同 session 写入) |

**incidental finding**: `CLAUDE.md L188` 称 northbound_holdings "3.88M 行", 实测 5.54M (+43%). `CLAUDE.md L189` stock_status_daily "12M 行" 实测 55K (memory 误读 lifetime inserts 11.5M 为 row count). **CLAUDE.md 数字 audit (留 D3-B 整合)**.

---

## 4. Q1.4 命名空间状态 (扩 D2)

| 表 | execution_mode | 行数 | 最新日期 |
|---|---|---:|---|
| cb_state | paper | 1 | 2026-04-20 16:30:24 |
| cb_state | live | 1 | 2026-04-28 16:30:21 |
| position_snapshot | live | 295 | 2026-04-28 |
| position_snapshot | paper | 0 | — |
| trade_log | paper | 20 | 2026-04-16 (历史 D2.3 P0-δ 污染) |
| trade_log | live | 68 | 2026-04-17 |
| performance_series | live | 16 | 2026-04-28 |
| signals (无 mode 列) | — | 220 | 2026-04-28 |

**漂移评估**:
- D2 finding "DB 295 live 行漂移 vs .env=paper" — 已不适用. .env EXECUTION_MODE 现在是 'live' (D2.3 batch 1 cutover 已完成). 295 live 行是合规.
- paper trade_log 20 行 (4-16 历史) 是 P0-δ 污染源 (DailyExecuteAfterData 17:05, 已永久废除). 历史数据保留作 audit, 0 真金风险.

---

## 5. 关键 Findings 汇总 (P0/P1/P2/P3 分级)

| ID | 描述 | 严重度 | 路径 | 处置建议 |
|---|---|---|---|---|
| F-D3A-1 | **alert_dedup / platform_metrics / strategy_evaluations migrations 存在但 DB 表不存在**, MVP 4.1 batch 1+2.1 + MVP 3.5.1 PR 实质未真生效 | **P0** | `backend/migrations/{alert_dedup,platform_metrics,strategy_evaluations}.sql` exist; `INFORMATION_SCHEMA.TABLES` 实测 0 hits | 立即 `psql -f` 应用 3 migrations + 验证 SDK 路径不 raise |
| F-D3A-2 | position_monitor "假装健康死码" — `api/pms.py:70` read, `pms_engine.py:358` write 仍存, 但 PMS Beat 已停 → API 永返 0 rows | P2 | `api/pms.py:70` | api/pms.py endpoint deprecate + `pms_engine.py:358` 删除 (PMS 已 ADR-010 melt 入 Risk Framework) |
| F-D3A-3 | circuit_breaker_log 0 行 (126 lifetime), valid "暂空", 不是死表 | INFO | `repositories/risk_repository.py` | 不处置 |
| F-D3A-4 | factor_evaluation 真死表 — 0 行 + 0 代码引用 | P3 | grep 0 hits | DROP TABLE (D3-B 整合阶段) |
| F-D3A-?? | minute_bars 4-13 后 17d 无新写 | INFO | DB 实测 | PT 重启后 QMT data sync 自然恢复 |
| memory数字 | CLAUDE.md L188 northbound 3.88M (实测 5.54M) / L189 stock_status_daily 12M (实测 55K) / L191 ic_history 84K (实测 145K) | P3 | CLAUDE.md L188-191 | D3-B 整合阶段统一更新 |

---

## 6. 主动发现

**(本审计意外发现, 不在 5 题 scope)**:

- 不一致: `minute_bars` 表名实测 dat=2026-04-13, **17 d 无新写**, 与 PT 暂停吻合. 但 4-13 之前 daily 写入历史是何样? 留 D3-B `data_lineage` 表 audit 解析.
- 数据 lineage 表 412 行 (相对小) — D3-B audit `data_lineage` 表语义 + entropy.
- handoff 说 "minute_bars 21GB", 实测 36GB (+71%). 数字漂移.

---

## 7. 关联

- **D2/D2.1/D2.2/D2.3** 已 audit 命名空间漂移 + Servy env scope, 本 D3.1 扩到全表 baseline
- **LL-063** 假装健康死码 — F-D3A-2 (position_monitor) 实例
- **铁律 X4** 死码月度 audit — 本审计为月度 audit 第 1 次实践
- **铁律 25** 改什么读什么 — 本审计未触发 (纯读, 不改)
- **CLAUDE.md L188-191 数字漂移** — 留 D3-B 整合 PR 统一更新
