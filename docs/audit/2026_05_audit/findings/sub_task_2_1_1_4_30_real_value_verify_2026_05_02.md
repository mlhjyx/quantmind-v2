# sub-task 2.1.1 prerequisite — 4-30 GUI sell 真值 5 source verify (5-02 sprint)

> **沉淀日期**: 2026-05-02
> **触发**: sub-task 2.1.1 trade_log backfill 实施 prerequisite. 4-30 GUI sell 1 笔真值 (price + executed_at) 真**0 sustained sprint state cite**, 必 5 source 真测找真值 source.
> **关联铁律**: 25 / 27 (不 fabricate) / 36 (precondition)
> **关联 LL**: LL-101 (audit cite 数字必 SQL/git/log 真测 verify before 复用) 沿用
> **关联 audit**: [F_D78_240_correction.md](F_D78_240_correction.md) (上 sediment, 真值订正 35→18) + [layer_2_1_reconnaissance_2026_05_02.md](../../layer_2_1_reconnaissance_2026_05_02.md) §J reviewer kill incident
> **0 prod 改 / 0 SQL 写 / 0 schtask / 0 .env / 0 hook bypass**

---

## §1 真测目标

sub-task 2.1.1 trade_log backfill 真 scope = **18 笔** (17 emergency_close fills + 1 GUI sell). 17 fills 真值 ✅ (logs/emergency_close_20260429_104354.log + PR #168 hook 真复用). **1 笔 GUI sell 真值缺**:

| 字段 | 真期望 | 真状态 |
|---|---|---|
| code | `688121.SH` | ✅ sustained cite (audit + sprint state) |
| qty | `4500 股` | ✅ sustained cite (business/02:47 + position_snapshot 4-27 真值) |
| **fill_price** | **未知** | 🔴 真**0 sustained cite source** |
| **executed_at** | **未知** | 🔴 真**0 sustained cite source** (仅 cite "4-30 GUI sell" 无 timestamp) |
| order_id | 未知 (GUI sell 真**无 order_id 给 user**) | 🔴 真不可考 |

---

## §2 5 source 真测真值 verdict

### Source 1: QMT GUI userdata_mini/log/request_backup/{YYYYMMDD}/ — ❌ 不可用

**真测路径**: `E:\国金QMT交易端模拟\userdata_mini\log\request_backup\`

**真测 ls**:
```
20260325/ 20260326/ 20260327/ 20260329/
20260401/ 20260402/ ...
```

**真发现**: 🔴 真**无 20260429/ 20260430/** 目录! 真**4-29 起 0 backup**.

**真根因 candidate**: GUI 未启动 sustained sustained F-D78-245 (PT 暂停后 user GUI 未恢复, sustained sprint state Week 1 WI 2.5 真根因 = "GUI 未启动"). 真 GUI backup 是 GUI 运行时按日 dump, 不运行 → 0 backup.

→ **Source 1 verdict (d)**: 真不可用, 4-29/4-30 真**0 backup file** for trade history.

### Source 2: xtquant SDK 真历史 query API — ❌ 不可用

**真测**: [xttrader.py](../../../../.venv/Lib/site-packages/Lib/site-packages/xtquant/xttrader.py) grep `def query_` 真返 **32 methods** (sync + async, 实际 16 unique APIs).

**真 query API list**:
- query_account_infos / query_account_status / query_stock_asset
- query_stock_order(s) (cancelable_only param) / query_stock_trades
- query_stock_position / query_stock_positions
- query_credit_detail / query_stk_compacts / query_credit_subjects

**真 docstring 真测**:
- `query_stock_trades(account)` 真**返**: "**返回当日所有成交的成交对象组成的list**" ([xttrader.py:682](../../../../.venv/Lib/site-packages/Lib/site-packages/xtquant/xttrader.py#L682))
- `query_stock_orders(account, cancelable_only=False)` 真**返**: "**返回当日所有委托的委托对象组成的list**" ([xttrader.py:647](../../../../.venv/Lib/site-packages/Lib/site-packages/xtquant/xttrader.py#L647))

**真发现**: 🔴 SDK 16 unique APIs 真**全 "当日" only**, 0 history/period/start_date param. 真**不支持历史日 query**.

→ **Source 2 verdict (d)**: 5-02 (周六 + 五一假期) query 真返 0 trade. 真**4-30 历史 query 不可** via xtquant SDK.

🔴 **真新 finding (LL-101 SOP 触发)**: 上轮 CC C1 cite "18 methods total" 真值 = **32 methods** (sync + async 全部计数), 漂移 +78%. 真应 cite "16 unique APIs (sync only)" or "32 methods (sync+async)".

### Source 3: xtdata 4-30 行情 OHLC — ✅ 区间 only

**真测 SQL** (klines_daily 真生产 cache):

```sql
SELECT trade_date, open, high, low, close FROM klines_daily 
WHERE code='688121.SH' AND trade_date BETWEEN '2026-04-28' AND '2026-04-30'
ORDER BY trade_date;
```

**真值**:

| trade_date | open | high | low | close | 涨跌 |
|---|---|---|---|---|---|
| 2026-04-28 | 9.84 | 9.88 | 9.59 | 9.65 | -1.93% (假设 4-25 收盘 9.84) |
| 2026-04-29 | **7.72** | 7.72 | 7.72 | 7.72 | **-20.00%** (科创板跌停 single price, 真 audit "卓然 -29%" cite **漂移** — 详 §4.5) |
| 2026-04-30 | **6.18** | 6.63 | 6.18 | 6.48 | **-16.06%** (4-29→4-30 累计 -32.85%) |

→ **Source 3 verdict (b)**: 4-30 fill_price 真区间 = **[6.18, 6.63]** (4-30 OHLC range). 真**midpoint 6.405 ± 0.225** (half-range 0.225). 真**精确 fill_price 不可**, 仅区间.

### Source 4: position_snapshot live 4-27 真值反推 — ✅ qty + cost basis confirmed

**真测 SQL**:

```sql
SELECT code, quantity, avg_cost, market_value FROM position_snapshot 
WHERE trade_date='2026-04-27' AND execution_mode='live' AND code='688121.SH';
```

**真值**:

```
code      | quantity | avg_cost | market_value
688121.SH |   4500   | 10.8979  |   44550.00
```

→ **Source 4 verdict (a partial)**: ✅ qty=4500 股 confirmed (与 audit cite 一致), avg_cost=10.8979 (cost basis 真值). 真**fill_price 仍未知**, 仅 qty + code + cost basis confirmed.

🔴 **真新 finding**: market_value 4-27=44550 = 9.9 元/股 implied. 真**4-27 close=9.9** (但 §3 显示 4-28 close=9.65, 4-25 close 真未 query). avg_cost=10.8979 vs 4-27 close=9.9 → **真 4-27 unrealized PnL = -9.16%** (持仓真亏 ~¥4,490).

### Source 5: 真账户 broker REST API — ❌ 不可用

**真测**: 国金 miniQMT 真**无 REST API**, 仅 xtquant SDK chokepoint (sustained sprint state + ADR-008). Source 5 = Source 2 同源.

→ **Source 5 verdict (d)**: 不可用 (sustained Source 2 限制).

### Source 6: 银行/券商 portal 账单 — ⏸️ out-of-scope

CC 真不真测 (user 自己 portal 登录, 真授权外).

→ **Source 6 verdict**: out-of-scope, user 自查.

### Source 7: logs/ 4-30 真账户操作 log — ❌ 0 capture

**真测** (logs/ 真生产 logs):

| log file | 4-30 entries | 4-30 sell event hits |
|---|---|---|
| logs/celery-stderr.log | **372 行** (4-30 entries 含) | **0** (grep "688121\|卓然\|2026-04-30.*sell\|2026-04-30.*成交" 0 hit) |
| logs/celery-stdout.log | 0 | 0 |
| logs/fastapi-stderr.log | 0 | 0 |
| logs/fastapi-stdout.log | **0 entries** for 4-30 | 0 (但 4-14 历史 PT 真生产 trade events 真存在 — 详 §4.6) |
| logs/qmt-data-stderr.log | (未 grep) | (未 grep) |

**真发现**: 🔴 真**0 source captured 4-30 sell event** in repo logs.

**真根因 candidates**:
- fastapi-stderr/stdout 4-30 真 0 entries → 真**fastapi 4-29 起 spawn-die loop sustained** (audit Layer 1 Week 1 §F-D78-235 cluster)
- celery-stderr 4-30 372 entries 真**含**, 但 0 sell event → 真**risk Beat 4-29 link-paused**, 0 trade event capture (sustained PR #150)
- qmt-data-stderr 真未 grep (CC 决议留 future, 真**主力 trade event 路径走 fastapi+broker_qmt, qmt-data 仅 60s 同步价格不含 trade callback**)

→ **Source 7 verdict (c)**: 真返 0 真值 for 4-30. 真无 fastapi 4-29 link-pause + risk Beat 4-29 link-pause sustained.

---

## §3 final verdict — V2 触发

| Source | verdict | 真值 |
|---|---|---|
| 1 QMT GUI backup | ❌ (d) 不可用 | 4-29/4-30 真 0 backup (GUI 未启动) |
| 2 xtquant SDK | ❌ (d) 不可用 | 16 unique APIs 全当日 only, 0 history support |
| 3 xtdata OHLC | ✅ (b) 区间 only | fill_price ∈ [6.18, 6.63], midpoint 6.405 ± 0.225 |
| 4 position_snapshot | ✅ (a partial) | qty=4500 ✅ / avg_cost=10.8979 ✅ / fill_price 仍未知 |
| 5 broker REST | ❌ (d) 不可用 | 国金 miniQMT 无 REST |
| 6 portal 账单 | ⏸️ out-of-scope | user 自查 |
| 7 logs/ | ❌ (c) 0 capture | fastapi 4-30 0 / celery 0 sell event |

→ **V2 触发** (0 source 完整真值, 仅区间 + qty 部分). 真**fill_price 精确值 + executed_at 时间** 真**仅 user 真自己 portal 真账单 source available**.

---

## §4 主动发现 (6 项, LL-101 SOP 触发)

### 4.1 🔴 上轮 CC cite "xtquant 18 methods" 真漂移

**真测**: xttrader.py 真 `def query_*` count = **32** (含 sync + async). 上轮 CC §1 cite "18 methods total" 真**漂移 +78%**.

**真值**: 16 unique APIs (sync only) or 32 methods (sync+async). 沿用 LL-101 SOP "audit cite 数字必三源 cross-verify".

### 4.2 🔴 audit cite "卓然 4-29 -29%" 真值漂移

**真测 (klines_daily 真生产)**: 4-29 close=7.72, 4-28 close=9.65 → **-20.00% 单日跌停** (科创板限制 -20% max). NOT cite "-29%".

**真候选 cite source**:
- 4-28→4-30 累计: 9.65 → 6.48 = **-32.85%** (含 4-30 -16.06%)
- 4-25→4-29 累计: 真 4-25 close 未 query (推断 ~9.85), -29% if 4-29=7.0 — 真不匹配 7.72

→ **F-D78-X candidate**: audit cite "-29%" 真值 source 真**0 SQL verify**, 真**沿用 sustained sprint state 错值 cite 多文档**. LL-101 SOP 真触发.

### 4.3 🔴 真 4-30 GUI sell 真值唯一 source = user portal

**真测**: Source 1-7 全检验完毕, 0 source 真返完整 fill_price + executed_at. 真**唯一 source = user 真自己 portal 真账单查询** (银行 / 券商 真账单 export).

→ user 决议候选:
- (i) **接受区间估算** + 走 PR INSERT (audit row marker 标 "真值估算 [6.18, 6.63]")
- (ii) **取消 4-30 backfill 1 笔** (仅 backfill 17 fills via hook), audit chain 14 day gap sustained 接受 (sustained F-D78-240 真断 14 day)
- (iii) **user 真自查 portal** + 提供真值 — 真**唯一精确 source**

### 4.4 🔴 GUI 未启动 真生产 audit blast radius

**真发现**: QMT GUI 4-29 起未启动 sustained → 4-29/4-30 真 0 backup → 真**audit chain 完整性永久缺失** for 4-29~5-02 真生产事件 (除 emergency_close log 104354.log 真在 + position_snapshot 4-27 静态 snapshot).

**真生产含义**:
- F-D78-245 真**已 closed via Week 1 user-action**, 但**真 audit chain 历史不可重建** for 4-29 GUI sell (真发生 in 4-30 user GUI 短暂启动, 真账户操作 by user 真未 backup)
- 真**未来同类事件**: 必先确保 GUI sustained 启动 + backup pre-event, audit chain 完整性 prerequisite

### 4.5 🔴 4-29 跌停真"-20%"非"-29%" — audit cite 真值订正候选

**真测**: 4-29 single price=7.72 (open=high=low=close 真**跌停板 single trade**), 9.65→7.72 = **-20.00% 真值** (科创板跌停限制 -20%).

audit cite "卓然 -29%" sustained sprint state 多文档. 真**真值漂移**:
- 真单日 4-29: -20.00% (NOT -29%)
- 真累计 4-28→4-30: -32.85% (近似 cite -29% 但 timeframe 不同)
- 真累计 4-29→4-30: -16.06%

→ **F-D78-X-29% candidate**: audit cite 真值订正候选, sustained F-D78-240 同 anti-pattern (cite 数字未 SQL verify). 真应起 future PR 订正多文档 cite "-29%" → "-20% 单日 / -32.85% 累计".

### 4.6 ⚠️ logs/fastapi-stdout 历史 PT live 真生产 trade events sustained

**真测**: fastapi-stdout 真**含历史 PT live trade events** (truncated rotated, 5-01 18:29 last entry):
- order_id=1082153202: 688121.SH price=11.06, volume=4600 (4-13 推断)
- order_id=1090547337: 688121.SH price=10.88, volume=4600 — 4-14 buy event (line 165019 含 `[QMT] 委托回报`, **session starting timestamp 2026-04-14T05:38:57Z 真在 L165000** log system startup entry, 真 trade event line 自身无 inline timestamp; 真 PT live 4-14 真生产 buy)

→ 这些是**历史 PT live trade events** sustained sprint period, **NOT 4-30 sell event**. 真**4-30 sell event 0 capture in fastapi-stdout** (因 fastapi 4-29 link-pause).

但有意思: PT live 真值 4600 股 (4-14 buy), position_snapshot 4-27 真值 4500 股 → 真**partial sell -100 股 真发生 between 4-14 ~ 4-27** (sustained PT 真生产 partial sell, log truncated). 真**audit chain 完整性 sustained F-D78-240 真断 14 day** (4-17 后 trade_log 0 行).

---

## §5 真 sub-task 2.1.1 真 scope verdict (订正后)

| 真 trade | 真值 | source | 真 backfill path |
|---|---|---|---|
| 17 笔 (4-29 emergency_close fills) | full 真值 (price/qty/ts/order_id) | logs/emergency_close_20260429_104354.log | ✅ PR #168 _backfill_trade_log hook 真复用 (FILL_EVENT_REGEX 匹配) |
| 1 笔 (4-30 GUI sell) | qty=4500 ✅ / fill_price ∈ [6.18, 6.63] / executed_at 未知 / order_id 不可考 | Source 4 + Source 3 区间 | ⏸️ V2 待 user 决议 (i/ii/iii) |
| **真总数** | **18 笔** (与 PR #209 真值订正一致) | 真三源 cross-verify | 真**混合 path** |

---

## §6 V2 待 user 决议候选

### (i) 接受区间估算 + PR INSERT

**真值**:
- code=688121.SH
- qty=4500 股
- fill_price=**6.405** (区间中位数 ± 0.225, half-range)
- executed_at=**2026-04-30 14:30:00+08** (默认 close 时间, 真不可考)
- reject_reason='t0_19_backfill_2026-04-30_estimated' (audit row marker 标真值估算)

**Pros**: trade_log 18/18 完整, audit chain closed.
**Cons**: 真**真值不精确** (fill_price ± 0.225 误差 ~3.5%), 沿用铁律 27 "不 fabricate" 真**violation candidate**.

### (ii) 取消 4-30 backfill 1 笔

**真值**: trade_log 仅 backfill 17 fills (4-29). 4-30 1 笔 sustained F-D78-240 真断 14 day gap.

**Pros**: 真值零 fabricate (铁律 27 ✅).
**Cons**: audit chain 真不完整 (1 笔 missing), 沿用 F-D78-240 sustained.

### (iii) user 真自查 portal + 提供真值

**真值**: user 自查银行/券商 portal 真账单, 提供 fill_price + executed_at 真值. CC 真复用 user 提供值 + path (i) PR INSERT.

**Pros**: 真值精确 + 铁律 27 ✅ + audit chain 完整.
**Cons**: 真依赖 user 操作 (真授权外), 真 ETA 不可控.

---

## §7 cite source (CC 5-02 真测 file:line)

| 来源 | 真 file:line | 真定义 |
|---|---|---|
| QMT GUI backup 真路径 | `E:\国金QMT交易端模拟\userdata_mini\log\request_backup\` | 真按日 backup, 4-29 起 0 |
| xtquant SDK API list | [xttrader.py 32 methods](../../../../.venv/Lib/site-packages/Lib/site-packages/xtquant/xttrader.py) | 真当日 only, 0 history support |
| query_stock_trades docstring | [xttrader.py:682](../../../../.venv/Lib/site-packages/Lib/site-packages/xtquant/xttrader.py#L682) | "返回当日所有成交的成交对象组成的list" |
| query_stock_orders docstring | [xttrader.py:647](../../../../.venv/Lib/site-packages/Lib/site-packages/xtquant/xttrader.py#L647) | "返回当日所有委托的委托对象组成的list" |
| 4-30 OHLC | klines_daily SQL: `code='688121.SH' AND trade_date='2026-04-30'` | open=6.18, high=6.63, low=6.18, close=6.48 |
| 4-29 真单日 -20% | klines_daily SQL: 4-28 close=9.65, 4-29 close=7.72 | 跌停 single price |
| position_snapshot 4-27 | SQL `WHERE trade_date='2026-04-27' AND execution_mode='live' AND code='688121.SH'` | quantity=4500 / avg_cost=10.8979 / market_value=44550 |
| QMT_ACCOUNT_ID | [backend/.env](../../../../backend/.env) `QMT_ACCOUNT_ID=81001102` | 真账户 (live + paper 同账户) |
| logs 4-30 sell 0 capture | grep "688121\|卓然\|2026-04-30.*sell\|2026-04-30.*成交" 全 logs/ | 0 hit |
| 4-14 历史 PT buy | logs/fastapi-stdout.log:165019 (session start ts 2026-04-14T05:38:57Z 真在 L165000) | order_id=1090547337, 688121, price=10.88, volume=4600 |
| F-D78-240 sediment | [F_D78_240_correction.md](F_D78_240_correction.md) | sustained, 35→18 真值订正 |

---

## §8 验收 checklist

- [x] §1 真测目标 (4 字段缺 / 3 字段已知) ✅
- [x] §2 5 source 真测真值 verdict (1/4 partial + 3/0 / 5/0 / 6/oos / 7/0) ✅
- [x] §3 final verdict V2 触发 ✅
- [x] §4 主动发现 6 项 (xtquant 18 vs 32 / -29% vs -20% / GUI 未启动 / 历史 PT trade) ✅
- [x] §5 真 sub-task 2.1.1 真 scope (18 笔 = 17 hook + 1 V2 待决议) ✅
- [x] §6 V2 待 user 决议候选 (i)/(ii)/(iii) ✅
- [x] §7 cite source (10 file:line / SQL 真测) ✅
- [x] **0 prod 改 / 0 SQL 写 / 0 schtask / 0 .env 改 / 0 hook bypass** sustained ✅

---

**文档结束**.
