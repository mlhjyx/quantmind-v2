# 现状快照 — 业务状态 (类 11)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 3 / snapshot/07
**Date**: 2026-05-01
**Type**: 描述性 + 实测证据 + finding (含 sprint period sustained 假设推翻)

---

## §1 真账户 ground truth (CC 5-01 04:16 实测 xtquant)

实测命令:
```python
from xtquant import xttrader
acc = StockAccount('81001102')
trader = xttrader.XtQuantTrader('E:/国金QMT交易端模拟/userdata_mini', session_id)
asset = trader.query_stock_asset(acc)
positions = trader.query_stock_positions(acc)
```

实测真值:
- **cash**: ¥993,520.66
- **frozen_cash**: ¥0.00
- **market_value**: ¥0.00
- **total_asset**: ¥993,520.66
- **positions count**: **0**

---

## §2 cb_state (真表 circuit_breaker_state) 真值

实测 SQL:
```sql
SELECT * FROM circuit_breaker_state ORDER BY updated_at DESC LIMIT 3;
```

最新 1 行 (execution_mode=live):
- `id`: 116bd790-...-5698ed
- `strategy_id`: 28fc37e5-...-c11a5103d0 (PAPER_STRATEGY_ID, .env)
- `execution_mode`: live
- `current_level`: **0**
- `entered_at`: 2026-04-20 20:38
- `entered_date`: 2026-04-20
- `trigger_reason`: "PT restart gate cleanup 2026-04-30 (DB stale → 真账户 ground truth)"
- `trigger_metrics`: `{'nav': 993520.16, 'rolling_5d': -0.001458, 'rolling_20d': None, 'daily_return': -0.002432, 'cumulative_return': 0.011714}`
- `recovery_streak_days`: 0
- `position_multiplier`: 1.00
- `updated_at`: 2026-04-30 19:48

第 2 行 (execution_mode=paper):
- `current_level`: 0, `entered_at`: 2026-03-25, `trigger_reason`: "初始化(首次运行)", `updated_at`: 2026-04-20 16:30

---

## §3 position_snapshot live 真值

实测 SQL:
```sql
SELECT trade_date, COUNT(*), SUM(quantity), SUM(market_value)
FROM position_snapshot
WHERE execution_mode='live'
GROUP BY trade_date ORDER BY trade_date DESC LIMIT 5;
```

| trade_date | count | sum(quantity) | sum(market_value) |
|---|---|---|---|
| **2026-04-27** | 19 | 70,600 | ¥901,554.00 |
| 2026-04-24 | 19 | 70,600 | ¥901,554.00 |
| 2026-04-23 | 19 | 70,600 | ¥901,415.00 |
| 2026-04-22 | 19 | 70,600 | ¥900,701.00 |
| 2026-04-21 | 19 | 70,600 | ¥902,567.00 |

总: COUNT=276 行 / 48 distinct codes / MAX(trade_date)=**2026-04-27**

---

## §4 跨源 drift cross-validate (真账户 vs cb_state vs position_snapshot)

| 源 | 时间戳 | nav / cash | positions | 一致性 |
|---|---|---|---|---|
| **xtquant 真账户** | 2026-05-01 04:16 (实测) | cash=¥993,520.66 | 0 | (基准) |
| **cb_state.live** | 2026-04-30 19:48 (updated_at) | nav=¥993,520.16 | (无 positions 字段) | nav 差 ¥0.50 (隔天 1 day 微小利息或费用) |
| **position_snapshot.live** | 2026-04-27 (max trade_date) | (无 nav 字段) | 19 持仓 70600 股 ¥901,554 | **🔴 4 trade days stale + 持仓数 19 vs 真 0 严重 drift** |

**判定**:
- xtquant ↔ cb_state: ✅ 一致 (差 ¥0.50 微小)
- xtquant ↔ position_snapshot: 🔴 **4 trade days stale**, 持仓 19 vs 真 0
- sprint state Session 45 (4-30 ~02:30) 写 "DB 4-28 stale 19 行 (T0-19 known debt audit-only)" — 实测 max trade_date=**4-27** (sprint state handoff 写 "4-28" 漂移 1 天, F-D78-1)
- **F-D78-4 [P2]** DB live position vs xtquant drift sustained, T0-19 known debt 仍 active (审查 4-30 + 5-01 都未自愈)

---

## §5 risk_event_log 历史

(本审查未深查 risk_event_log 真行数 + 时间分布. 留 sub-md 16_alert_trigger_history 详查. sprint state Session 44 写 "30天 risk_event_log 0 行" 是 PT 暂停前的关键触发点.)

---

## §6 NAV 历史 (近 30/90/180 day)

(本审查未深查 NAV 演进. 留 snapshot/17_pt_restart_history 详查. sprint state 写 "PT 配置 CORE3+dv_ttm WF Sharpe=0.8659 (2026-04-12 PASS)", 但真 PT 期间 NAV 演进 vs 回测 Sharpe 是否 align? — 留 verify.)

---

## §7 PT 暂停 sprint period sustained 状态

| 时间点 | 状态 | 来源 |
|---|---|---|
| 2026-04-29 ~10:43 | CC emergency_close 17 股 | sprint state Session 44 |
| 2026-04-29 跌停 cancel | 1 股 (688121.SH 卓然新能 4500 股) | 同上 |
| 2026-04-30 user GUI sell | 卓然新能 4500 股清 | 同上 |
| 2026-04-30 14:54 | 真账户 0 持仓 / cash ¥993,520.16 | sprint state 沉淀 |
| **2026-05-01 04:16** | **真账户 0 持仓 / cash ¥993,520.66 (差 ¥0.50)** | **本审查 E6 实测** |

**判定**: ✅ PT 暂停 sustained, 真金 0 风险 (LIVE_TRADING_DISABLED=True / EXECUTION_MODE=paper / 0 持仓).

---

## §8 PT 重启 gate prerequisite 真值 (沿用 sprint state 修订)

sprint state Session 45 (4-30) 修订:
- ✅ **已 closed (代码层)**: T0-11 (F-D3A-1, PR #170) / T0-15/16/18 (PR #170) / T0-19 (PR #168+#170)
- ⏳ **真待办 (运维层)**: DB 4-28 stale snapshot 清 + paper-mode 5d dry-run + .env paper→live 用户授权

本审查实测:
- T0-19 ⏳ 真待办 (DB 4-28 stale snapshot 清) — 实测 4-27 仍 stale (sprint state 写 "4-28" 错 1 天 + 沿用 sustained 4 trade days stale)
- paper-mode 5d dry-run — 0 实测证据, sprint state sustained 沉淀但未触发
- .env paper→live 用户授权 — sprint state sustained sustained, 但 user D78 已开放质疑 prerequisite 本身合理性

---

## §9 发现汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-1 (复) | P2 | sprint state handoff 数字漂移 (写 "4-28" 真值 4-27, 错 1 天) |
| F-D78-4 (复) | P2 | DB live position vs xtquant 真账户 4 trade days stale (T0-19 sustained, 仍 active) |
| F-D78-12 | P3 | xtquant cash 4-30 14:54 → 5-01 04:16 差 ¥0.50 (微小利息或费用, 非 anomaly) |

---

**文档结束**.
