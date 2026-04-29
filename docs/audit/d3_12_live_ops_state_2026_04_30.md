# D3.12 真金 Ops 状态审计 — 2026-04-30

**Scope**: 当前持仓 / 资金 / Tier 0 债 10 项实测 / 30d risk_event_log / schtask 状态
**铁律**: X2 (LIVE_TRADING_DISABLED) / 33 (fail-loud)
**0 改动**: 纯诊断 read-only

---

## 1. Q12.1 当前持仓 + 资金 (实测)

### NAV (2026-04-28 close)

| 日期 | NAV | daily_return | drawdown | cash | position_count |
|---|---:|---:|---:|---:|---:|
| 2026-04-28 | ¥1,011,714.08 | -0.243% | -0.243% | ¥110,624.08 | 19 |
| 2026-04-27 | ¥1,014,180.08 | +0.198% | 0.000% | (NULL) | 19 |
| 2026-04-24 | ¥1,012,178.08 | -0.005% | -0.176% | ¥110,624.08 | 19 |

### 19 股持仓明细 (2026-04-28)

| code | qty | avg_cost | mv (¥) | pnl_pct | holding_days |
|---|---:|---:|---:|---:|---:|
| **688121.SH 卓然新能** | 4500 | 10.90 | 43,425 | **-11.45%** | **0** |
| **000012.SZ 南玻 A** | 10700 | 4.52 | 43,121 | **-10.84%** | **0** |
| 600028.SH 中石化 | 8600 | 5.77 | 46,010 | -7.23% | 0 |
| 002623.SZ | 2100 | 21.80 | 44,457 | -2.89% | 0 |
| 000507.SZ | 9200 | 5.31 | 47,840 | -2.07% | 0 |
| 002282.SZ | 6900 | 6.87 | 46,989 | -0.87% | 0 |
| 688391.SH | 1500 | 30.28 | 45,195 | -0.50% | 0 |
| 601988.SH 中行 | 8500 | 5.76 | 49,385 | +0.87% | 0 |
| 300750.SZ 宁德时代 | 100 | 423.49 | 42,767 | +0.99% | 0 |
| 601398.SH 工行 | 6500 | 7.45 | 48,945 | +1.07% | 0 |
| 600900.SH 长江电力 | 1800 | 26.33 | 48,114 | +1.52% | 0 |
| 601857.SH 中石油 | 4200 | 11.91 | 51,156 | +2.27% | 0 |
| 600941.SH 中国移动 | 500 | 93.39 | 48,015 | +2.83% | 0 |
| 688211.SH | 1400 | 32.89 | 47,390 | +2.92% | 0 |
| 601088.SH 中国神华 | 1000 | 45.65 | 48,150 | +5.48% | 0 |
| 000333.SZ 美的 | 600 | 75.95 | 48,270 | +5.92% | 0 |
| 600938.SH 中海油 | 1300 | 36.87 | 51,701 | +7.87% | 0 |
| 688981.SH 中芯 | 400 | 100.69 | 45,600 | +13.22% | 0 |
| 601138.SH 工业富联 | 800 | 58.65 | 54,560 | +16.28% | 0 |

**汇总**: 19 股, 总成本 ¥890,694.63, 总市值 ¥901,090.00, **浮盈 +¥10,395.59 (+1.17%)**.

### F-D3A-11 (P3) — Handoff 数字 stale

Session 44 handoff 称 "卓然 -29% / 南玻 -10%". 实测 4-28 卓然 **-11.45%** (已部分恢复 from -29%), 南玻 **-10.84%** (一致). LL 第 8 次同质 — handoff 数字必实测.

### F-D3A-?? (D2 known, INFO) — holding_days 全 0

`position_snapshot.holding_days = 0` 全部 19 股. D2 known issue (写路径漂移), 不影响交易决策但破坏 PositionHoldingTime risk rule (Risk Framework v2 PR #148). 已知, 待批 2 P0/P1 修.

### F-D3A-?? (P1 NEW) — performance_series 4-27 cash NULL

4-27 行 cash 字段 NULL — `save_qmt_state` 写路径漂移. D2.3 P0-β 修后 4-24/4-28 cash 写入正常, 4-27 NULL 是 schtask 4-27 间歇性失败遗留. **D3-B 续查**.

---

## 2. Q12.2 Tier 0 债 10 项实测 (vs Claude 综合 claim)

| 编号 | Claude 描述 | Claude claim | CC 实测 | 偏差 |
|---|---|---|---|---|
| T0-1 | LL-081 `_assert_positions_not_evaporated` guard | ✅ 修 (批 1) | ✅ 实存 `pt_qmt_state.py` (grep 4 hits) | 0 |
| T0-2 | startup_assertions | ✅ 修 (批 1) | ✅ 实存, 含 SKIP_NAMESPACE_ASSERT bypass | 0 |
| T0-3 | cb_multiplier hardcoded | ✅ 修 (批 1) | ✅ 0 hits → 已参数化 | 0 |
| T0-4 | 写路径漂移 7 处 hardcoded 'live' | 🟡 待批 2 P0 | **🔴 实测 27+ 处** (含注释/读路径混杂) | **+285% scope 偏差** |
| T0-5 | LoggingSellBroker stub | 🟡 批 2 P3 | (未深查, 留 D3-B) | ? |
| T0-6 | DailyExecute 09:31 schtask disabled | 🟡 批 2 评估 | ✅ State=Disabled (Last 4-19, Result=0) | 0 |
| T0-7 | auto_sell_l4 default False | 🟡 批 2 决策 | (未深查, 留 D3-B) | ? |
| T0-8 | dedup key 不含 code | 🟡 批 2 P2 | (alert_dedup 表本身缺失见 F-D3A-1, 上层先) | upstream |
| T0-9 | approve_l4.py 2 处 hardcoded 'paper' | 🟡 批 3 | (未深查, 留 D3-B) | ? |
| T0-10 | api/pms.py 死表 | 🟡 批 3 | ✅ 实测 position_monitor 0 行 + api/pms.py:70 死读 (D3.1 F-D3A-2) | 0 |

### F-D3A-12 (P0 SCOPE UPDATE) — T0-4 真实 scope 27+ 而非 7

```bash
grep -rn "execution_mode\s*=\s*['\"]live['\"]" backend/ --include="*.py"
```

实测 hits (按文件):
- `engines/base_broker.py:78` (注释)
- `app/api/execution_ops.py`: 3 处 (L204/206/248)
- `app/services/execution_service.py:311` (注释)
- `app/services/pt_qmt_state.py`: 5 处 (L46/55/147/158/197)
- `app/services/pms_engine.py`: 9 处 (L10/149/152/169/212/217/364/397/410)
- `app/services/realtime_data_service.py`: 5 处 (L400/403/438/468/471)
- `app/services/qmt_reconciliation_service.py`: 2 处 (L79/111)
- `engines/strategies/s1_monthly_ranking.py`: 2 处 (L21/71 注释)
- `engines/config_guard.py`: 1 处 (L306)

**实质 hardcoded (排除注释)**: ~25-27 处. 注释里也有 hardcoded 'live' 表述, 共 ~30+ hits.

**很多是合规的 read 路径** (ADR-008 D3-KEEP 设计 — read 始终 'live' 过滤 live positions). 但 **D2 batch_1.5 STATUS_REPORT 数字 7 是 1 阶 audit 概括的 imprecise scope**.

**LL 第 9 次同质** (假设/概括必实测纠错). 批 2 P0/P2 scope 必须重新枚举所有 hits, 区分:
- (a) read 路径 D3-KEEP (合规)
- (b) write 路径 hardcoded (ADR-008 P0-β 必修, 待批 2 PR-A 动态 execution_mode)

---

## 3. Q12.3 30 天 risk_event_log + schtask 状态 (实测)

### risk_event_log = 0 rows ever

```sql
SELECT COUNT(*) FROM risk_event_log;  -- 0
SELECT COALESCE(MAX(created_at)::text, 'never') FROM risk_event_log;  -- 'never'
```

### F-D3A-?? (P0 candidate) — Risk Framework v2 9 PR 真生产 0 events

Session 44 handoff 称 "Risk Framework v2 9 PR 全闭环 5 维度全覆盖", 但 `risk_event_log` **0 rows 历史**. 

**评估**:
- (a) 是否 PT 暂停期 schtask Disabled 自然不触发? 实测 schtask 4-29 Mon-Fri 仍跑 intraday/daily risk check (见下) — 触发条件不达
- (b) 是否 4-28 持仓含 -11.45% / -10.84% 应触发 SingleStockStopLoss? — 阈值是否高于 10%, 待批 2 验证
- (c) 是否写路径 silent failure (PR #144 scheduler_task_log audit 包络后是否真覆盖 risk_event_log 写入)?

**当前结论**: P1 (升级 P0 候选, 批 2 P0 应增 "9 PR 真生产验证, 触发条件回放" 子项).

### Schtask 状态 (实测 5 关键 task)

| Task | State | Last Run | LastResult | 评估 |
|---|---|---|---|---|
| QuantMind_DailyExecute | **Disabled** | 04/19/2026 09:31 | 0 | T0-6 已知, 待批 2 评估 reenable |
| **QuantMind_DailySignal** | **Disabled** | **04/28/2026 16:30** | 0 | **🔴 F-D3A-13 (P0)** — 4-29/4-30 0 signal |
| QuantMind_DailyMoneyflow | Ready | 04/29/2026 17:30 | 0 | ✅ |
| QuantMind_DailyIC | Ready | 04/29/2026 18:00 | 0 | ✅ |
| QuantMind_PTAudit | Ready | 04/29/2026 17:35 | **1** | 🟡 F-D3A-14 (P1) — 4-29 fail |

### F-D3A-13 (P0) — DailySignal 4-29/4-30 Disabled

Schtask `QuantMind_DailySignal` State=Disabled, last run 4-28 16:30. 表示 **4-29/4-30 0 signal 写入** (signals 表 max trade_date=2026-04-28 验证).

scheduler_task_log 同期:
- signal_phase 3 success, last 4-28 16:31 ← 与 schtask 一致
- 4-29 / 4-30 缺 signal_phase 记录

**评估**: handoff 说 PT 暂停 — 但 `performance_series` 4-28 仍写 (snapshot 不依赖 signal). 是否 PT 暂停 = "暂停信号生成", 留 D3-B 调查 disable 时点 + 决策日志.

### F-D3A-14 (P1) — pt_audit 4-29 schtask Result=1 但 DB 无 audit log

```bash
schtasks /Query QuantMind_PTAudit  # LastResult=1 (P1 alert per script convention)
```

但 scheduler_task_log:
```sql
SELECT * FROM scheduler_task_log WHERE task_name='pt_audit' AND start_time > '2026-04-29';  -- 0 rows
```

pt_audit 4-29 schtask 触发但 DB 没记录, 表示 **pt_audit 自身 fail 在 DB 写入之前** (import-time / .env 加载 / 等). 铁律 33 fail-loud + 铁律 43 schtask 硬化 (boot stderr probe + 顶层 try/except) 应有 stderr trace, 但本审计未查 schtask stderr 日志.

**D3-B 续查**: `Get-WinEvent` 或 schtask 历史 stderr.

### F-D3A-?? (P1) — pending_monthly_rebalance 18 expired (52% rate)

```sql
SELECT task_name, status, COUNT(*) FROM scheduler_task_log
WHERE start_time > NOW() - INTERVAL '7 days' GROUP BY 1,2;
-- pending_monthly_rebalance | executed | 36
-- pending_monthly_rebalance | expired  | 18
```

52% expired rate 是 PT 暂停期间正常副作用 (DailySignal Disabled → 月度调仓 signal 不生成 → expired). 不是 imminent 真金风险, 但表示批 2 PT 重启 gate 必含 "清空 pending_monthly_rebalance 积压" 子项.

---

## 4. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3A-12 | T0-4 hardcoded 'live' scope **27+ 处 vs claim 7 处** (3.8x 偏差). 含注释/read 路径/write 路径混杂. 批 2 P0/P2 scope 必重新枚举 | **P0** |
| F-D3A-13 | QuantMind_DailySignal schtask Disabled (last 4-28). 4-29/4-30 0 signal 写入 | **P0** |
| F-D3A-?? | risk_event_log 历史 0 rows, Risk Framework v2 9 PR 真生产 0 触发. Session 44 handoff 已知, 待批 2 验证 (触发条件回放) | P0 候选 |
| F-D3A-14 | pt_audit 4-29 schtask Result=1 但 DB 无 audit log → schtask 启动前自身 fail | P1 |
| F-D3A-?? | performance_series 4-27 cash NULL (D2.3 P0-β 修后间歇性遗留) | P1 |
| F-D3A-11 | handoff "卓然 -29% / 南玻 -10%" 数字 stale, 实测 -11.45% / -10.84% | P3 |
| F-D3A-?? | pending_monthly_rebalance 52% expired rate (PT 暂停副作用) | INFO |

---

## 5. 关联

- **Session 44 Risk Framework v2 9 PR (#143-148)** — 真生产 0 events 待验证
- **D2.3 P0-β cash NULL 修** — 4-27 间歇性 NULL 仍存在
- **铁律 33 fail-loud + 铁律 43 schtask 硬化** — pt_audit 4-29 fail 应有 stderr trace
- **LL 第 9 次同质** (假设必实测) — T0-4 scope 7 → 27+
- **批 2 scope 调整建议** (见 STATUS_REPORT)
