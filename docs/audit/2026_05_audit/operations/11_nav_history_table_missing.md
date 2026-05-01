# Operations Review — qm_nav_history 表 真不存在

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / operations/11
**Date**: 2026-05-01
**Type**: 评判性 + qm_nav_history 表真测

---

## §1 真测 (CC 5-01 SQL 实测)

实测 SQL: `SELECT MIN(snapshot_date), MAX(snapshot_date), COUNT(*) FROM qm_nav_history`

**真值**: `psycopg2.errors.UndefinedTable: relation "qm_nav_history" does not exist`

**真测**: qm_nav_history 真**不存在** in PostgreSQL 16.8 quantmind_v2 schema.

---

## §2 表清单真测 (LIKE '%nav%' OR '%log%' OR '%trade%')

实测真值 13 表:
- agent_decision_log
- backtest_daily_nav (✅ NAV 真在 backtest 表)
- backtest_trades
- circuit_breaker_log
- execution_audit_log
- factor_health_log
- intraday_monitor_log
- operation_audit_log
- param_change_log
- risk_event_log
- scheduler_task_log
- strategy_status_log
- trade_log

**真值**: NAV 真历史**仅在 backtest_daily_nav** (回测专用), 真生产 PT NAV 真**0 sustained 沉淀表** sustained.

---

## §3 🔴 真发现 — 真生产 NAV history 0 表沉淀

**真根因**:
- sprint period sustained sustained "NAV ¥993,520.16" sustained (sprint state) 仅在 cb_state.live (单行 hot state, 沿用 sprint period sustained "cb_state.live: nav=993520.16")
- **真生产 NAV history (per snapshot 时间序列)** 真 0 sustained 表
- → 真 PT NAV 趋势真**0 sustained 度量** (无法 plot NAV 历史曲线 from DB)

**真证据 sustained sprint period sustained**:
- 4-30 user GUI sell + risk_event_log 4-30 P0 ll081_silent_drift `Diff: -¥18,194 (-1.8%)` 真证据 sustained 但 **真 NAV 历史趋势 0 表 sustained 度量**

**🔴 finding**:
- **F-D78-243 [P1]** qm_nav_history (or PT NAV history) 表真**不存在** sustained, 真生产 PT NAV 历史趋势真 0 表沉淀 (仅 cb_state.live 单行 hot state). sustained F-D78-? observability sustained 缺 sustained: PT NAV 真**0 sustained 时间序列度量** = 真生产 NAV trajectory replay 0 reproducibility (沿用 F-D78-242 同源)
- F-D78-244 [P2] 真生产 + 回测 NAV 真两套表 (回测=backtest_daily_nav, 真生产=cb_state.live 单行) 真分裂 sustained, sustained 铁律 16 "信号路径唯一且契约化" 同源 反 anti-pattern (NAV 路径不唯一)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-243** | **P1** | qm_nav_history 表真不存在, PT NAV 历史 0 表沉淀, 真 0 sustained 度量 |
| F-D78-244 | P2 | 真生产 + 回测 NAV 真两套表 (cb_state.live 单行 vs backtest_daily_nav) 真分裂 |

---

**文档结束**.
