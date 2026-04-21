# F19 根因调查: 5 position 4-17 EOD → 4-20 open 蒸发

**Date**: 2026-04-21 (Session 21 加时)
**Status**: ⚠️ 根因未完全确定, 需 QMT `query_history_trades` 直查 4-18/4-20 补证
**Owner**: Session 22 跟进
**Related**: ADR-008 L287-289, Session 20 pt_audit 17:35 P1 alert, F20 trade_log 完整性

## 初版认知 (Session 20 末)

> "F19 phantom 5 码, 每日污染 PMS; trade_log 可能不完整, 是 F19 真实根因" (ADR-008 L289)

**拟修复**: Session 21 `DELETE FROM position_snapshot WHERE code IN (5 phantom)`.

## 实测 (Session 21 Bash+SQL 交叉验证)

### 事实 1: 4-17 trade_log live 有 20 行, **无缺失**

```sql
SELECT trade_date, COUNT(*), COUNT(DISTINCT code) FROM trade_log
  WHERE execution_mode='live' ORDER BY trade_date DESC;
-- 2026-04-17: 20 rows / 20 codes (10 sell + 10 buy, 全 09:32:06 executed_at)
-- 2026-04-15:  8 rows
-- 2026-04-14: 36 rows (BJ 清仓 day)
```

**推翻 ADR-008 L289 假设**: QMT 20 fills = trade_log 20 rows ✓, 无入库缺失.

### 事实 2: 5 码 4-17 EOD 正常持仓 (qty > 0, 非 phantom)

```sql
-- position_snapshot 4-17 for 5 codes
002441.SZ qty=3600  avg_cost=10.02  (4800 → 4-17 sell 1200 → 3600 ✓)
300833.SZ qty=900   avg_cost=33.79  (1400 → 4-17 sell 500 → 900 ✓)
688739.SH qty=571   avg_cost=24.41  (1900 → 4-17 sell 1329 → 571 ✓)
920212.BJ qty=60    avg_cost=NULL   (4-13: 4160 → 4-14 sell 3874 → ? 剩 286?)
920950.BJ qty=65    avg_cost=NULL   (4-15: 4-15 sell 300 后剩 65 ✓)
```

**所有 qty 和 trade_log fills 对得上**. `restore_snapshot_20260417.py:217` `qty > 0` filter 正确过滤 0 qty 码, 保留 5 码正常.

**结论**: 4-17 snapshot 记录是**真实 EOD 持仓**, 非 phantom.

### 事实 3: 4-18/4-19 非交易日, 4-20 Redis 已无 5 码

```bash
redis-cli HKEYS portfolio:current  # 19 codes, 全不含 002441/300833/688739/920212/920950
redis-cli GET portfolio:nav       # total_value=1013191, position_count=19
```

4-20 16:30 signal_phase 写 snapshot 4-20 = 19 codes ✓ (与 QMT reality 对齐).

### 事实 4: db_drift 语义澄清

```python
# pt_audit.py:462 check_db_drift
expected = reconstruct(prev_snapshot + today_live_fills)
actual   = today's snapshot
drift    = expected_codes △ actual_codes  # 对称差
```

4-20 17:35 audit:
- `expected = reconstruct(4-17 snapshot 24 codes + 4-20 fills 0 [DailyExecute disabled])` = **24**
- `actual = 4-20 snapshot` = **19**
- drift = **5** (expected but not in actual: 002441/300833/688739/920212/920950)

**非 DELETE 类 phantom** (snapshot 无冗余), 而是 "reconstruct 函数对非交易日自然蒸发的 position 无假设".

## 真实根因候选 (未确定)

### 候选 A: QMT 盘后/盘前自动结算清掉小额持仓 (推测最可能)

| code | qty 4-17 EOD | 特征 |
|---|---|---|
| 920212.BJ | 60 | BJ 股 + **非整手** (< 100 股) |
| 920950.BJ | 65 | BJ 股 + **非整手** |
| 688739.SH | 571 | 科创板 + **非整手尾数 71** |
| 002441.SZ | 3600 | **整 36 手**, 看似正常 |
| 300833.SZ | 900 | **整 9 手**, 看似正常 |

3/5 码是 sub-lot position. QMT 或券商 (国金 miniQMT) 周末/周一开盘前可能自动清理 "碎股" (< 100 股). 但 002441 (3600=36 手) 和 300833 (900=9 手) 是标准整手, 此 hypothesis 解释不了.

### 候选 B: 手工 QMT 桌面交易 4-20 09:00-09:31 (DailyExecute 前)

用户或其他自动化在 4-20 开盘 9:00-9:31 之间通过 QMT 桌面客户端手工清仓 5 码. 因 DailyExecute 已废除 (Stage 4 Session 17), 系统 trade_log 无入库. Redis `qmt_data_service` 每 60s sync, 9:31 后显示 19.

可行性: ⚠️ 需与用户确认是否当日手工操作. 如无操作此假设 falsify.

### 候选 C: QMT 数据上报 bug (4-20 9:31 `query_stock_positions` 返 19 而非 24)

`qmt_data_service.py` 每 60s 拉 `xtquant.xttrader.query_stock_positions()`, 若 QMT 缓存异常 upstream 返 19 而非 24, 则 Redis → snapshot 链路都显示 19. 真实 QMT 账户可能仍持 24, 但系统看到 19.

**证伪方法**: 直连 QMT 桌面客户端对账 (需手工). 或 QMT `query_stock_asset()` 查 market_value 与 Redis `total_value=1013191` 对比:
- 若 QMT 账户 `total_value` 含 5 码 (> 1013191), 则 Redis 丢失 → 候选 C 真.
- 若 QMT 账户 `total_value` = Redis, 则候选 A/B 真.

### 候选 D: 4-18/4-19 周末 OTC 事件 (股息/分红/换股)

5 码同时发生 OTC 事件 (分红除权/股票期权行权) 导致 position 重算. 低可能性 (5 码同时同源事件概率极低).

## 推荐动作

### Session 21 今日 (do)

1. **不 DELETE** 4-17 historical snapshot (候选 A-D 任一为真, DELETE 都销毁历史证据)
2. 写本 findings report 入 `docs/audit/F19_*.md` (已执行)
3. 更新 ADR-008 L289 `F19 真实根因` 描述: "trade_log 入库完整 (已反证), 根因待 Session 22+ QMT 直查"
4. **不升级** reconstruct_positions (候选 C 真则改函数治标不治本)

### Session 22+ (todo)

1. 手工 QMT 桌面客户端对账: 实时查 `query_stock_positions()` 5 码 vs Redis
2. QMT `query_history_trades(4-18, 4-20)` 查是否有 untracked 成交记录
3. 询问用户是否 4-20 早 9 点手工操作 QMT (候选 B 证伪)
4. 若候选 C 证实 (Redis 丢失 QMT data) → 开 F23 QMT Data Service reliability 改造: `query_stock_positions` 失败重试 + sanity check (`position_count` 周环比 variance alert)
5. pt_audit `check_db_drift` 加第 6 个 sub-check: **"消失 position 无对应 sell fill"** 独立 finding 而非嵌在 db_drift (区分"真 phantom"和"蒸发 bug")

## 教训预映 (LL-065 候选)

**结论不应先设**: Session 20 handoff "F19 phantom DELETE" 是基于 17:35 audit P1 alert 的**措辞**直接套用, 未验证是否真"phantom" (冗余记录)还是"蒸发" (真实记录但失步). Session 21 交叉 trade_log+Redis+restore script 后才定性为后者.

**铁律 25 外延**: 不仅"代码变更前读代码", **DB 清理前读全部关联表** (position_snapshot + trade_log + klines_daily + Redis 四源对账). 否则 DELETE 操作可能销毁唯一证据链, 导致根因永久不可查.

## 记录

- Session 21 (2026-04-21) 加时战场 P1 原计划 "DELETE 5 phantom rows"
- 交叉验证 3 数据源 + 读 pt_audit 代码后撤销 DELETE 计划
- 改出本 findings report
- 改做 P2 bp_ratio direction conflict 调研 (见 Session 21 handoff)
