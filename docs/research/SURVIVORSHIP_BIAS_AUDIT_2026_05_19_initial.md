# 生存者偏差审计 (Survivorship Bias Audit) — 初步发现 2026-05-19

> **目的**: Plan v8 Master P0-11 + S1 §1.4 + S7 §37 真值验证. 5yr/12yr 回测 universe 是否包含历史退市股票 (反生存者偏差).
>
> **触发**: Phase J B3 启动 (用户 5-19 ~20:50 SH "继续" trigger — 取消 5 日窗口分阶段思维, 改连续执行模式).
>
> **状态**: **初步真值验证 — Plan v8 P0-11 假设可能是误报** (反 P0-24 同体例 — 需深度验证后判定)
>
> **日期**: 2026-05-19 evening SH
> **作者**: CC autonomous (Phase J B3 起手)
> **关联**:
> - [Plan v8 Master P0-11 Survivorship Bias](audit/V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md) Top 24 P0
> - [Plan v8 S1 §1.4](audit/V3_AUDIT_S1_DOMAIN.md) Universe Characteristics
> - [Plan v8 S7 §37](audit/V3_AUDIT_S7_ML_COST_HARDWARE.md) Survivorship Bias Audit
> - [PLAN_V8_MASTER_FINDINGS_REGISTER §4.2 U7 B3](audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md) Phase J priority

---

## §0 初步结论 (TL;DR)

**Plan v8 P0-11 假设 "backtest universe EXCLUDES delisted stocks entirely" — 真值验证 PROBABLY 不成立**:

- ✅ **klines_daily 真实包含历史退市股票数据** (5743 全表 唯一股 vs 5476 最新交易日 — 267 只历史股不在最新交易日)
- ✅ **symbols 表 sediment 322 只退市记录** (含 delist_date, 2014-2026 cumulative, 注册制后 2020-2025 累计 210 只)
- ✅ **244 只退市候选股票** 历史有 klines 但最近 60 天 0 数据
- ✅ **backtest 加载 SQL** (parquet_cache.py) **无生存者过滤**:
  ```sql
  FROM klines_daily k
  LEFT JOIN daily_basic db ON ...
  LEFT JOIN stock_status_daily ss ON ...
  WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
  ```
  — **无 `WHERE symbols.is_active = true` / `delist_date IS NULL`** 过滤

**结论方向**: backtest 在 5yr (2021-2026) / 12yr (2014-2026) 窗口内**包含**历史退市股票, **没有显著生存者偏差** (与 Plan v8 假设相反).

**残余风险** (待深度验证):
- ST 标志 (`is_st` from `stock_status_daily`) 是否 retroactively backfilled (退市前 ST 阶段 真值)?
- factor_values 是否对退市股票 sediment 完整因子值 (退市前的最后交易日是否被 dropna)?
- backtest universe 真用还是 final selected 选股 后只有 active 股?

---

## §1 真值证据

### §1.1 DB schema + 行数 (2026-05-19 20:30 SH 真测)

| 表 | 行数 / 列数 | 关键字段 |
|---|---|---|
| `klines_daily` | ~11.7M 行 / 17 列 | 含 `is_st` / `is_suspended` / 无 `delist_date` |
| `symbols` | **5821 行** / 19 列 | 含 **`delist_date`** + `list_status` + `is_active` |
| `daily_basic` | ~11.6M 行 / 18 列 | 无生存者相关字段 |
| `universe_daily` | **0 行** | 设计字段 `in_universe` + `exclude_reason` 但**空表** ← 设计未实施 |
| `stock_status_daily` | (未查行数) | `is_st` / `is_suspended` 真值 source |

### §1.2 symbols.delist_date 真值 (2014-2026 退市分布)

```
2014: 3 只   2015: 5 只   2016: 2 只   2017: 4 只   2018: 7 只   2019: 10 只
2020: 18 只  2021: 22 只  2022: 43 只  2023: 48 只  2024: 49 只  2025: 30 只
2026: 3 只 (截至 5-19, 含 603056.SH 003-31 / 002231.SZ 03-27 / 300379.SZ 01-22 等)

Total: 322 只 cumulative 退市记录 (12yr 窗口完整覆盖)
```

**注册制后 (2020-2025) 累计 210 只退市**, 占总 322 只的 65%. 反映A股市场退市制度真实化进程.

### §1.3 klines_daily 5yr/12yr 窗口股票数

- **5yr 窗口 (2021-2026)**: 5694 只 有 klines_daily 数据
- **12yr 窗口 (2014-2026)**: 5743 只 有 klines_daily 数据
- 增量 (12yr vs 5yr): +49 只 (2014-2020 退市 + 已 delist 股)

### §1.4 backtest universe 加载 SQL (parquet_cache.py)

```python
# backend/data/parquet_cache.py 主 SQL
FROM klines_daily k
LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
LEFT JOIN latest_af laf ON k.code = laf.code
LEFT JOIN stock_status_daily ss ON k.code = ss.code AND k.trade_date = ss.trade_date
WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0
ORDER BY k.trade_date, k.code
```

**关键点**:
- 无 `JOIN symbols` (无 is_active / delist_date 过滤)
- `LEFT JOIN stock_status_daily` (ST 标志 per-date 真值)
- `WHERE volume > 0` (自动排除 退市后 OR 停牌日)

**含义**: 历史退市股票 (e.g. 600200.SH 退市 2025-12-31), 其 2014-2025-12-31 期间的 klines_daily 数据**会被 INCLUDED** 在 backtest universe 中.

### §1.5 backtest runner.py per-date 排除

```python
# backend/engines/backtest/runner.py:138-154
_has_status = "is_st" in price_data.columns
_status_by_date: dict[date, set[str]] = {}
if _has_status:
    for col in ("is_st", "is_suspended", "is_new_stock"):
        if col in price_data.columns:
            excluded = price_data.loc[price_data[col] == True, ["code", "trade_date"]]
            for td, grp in excluded.groupby("trade_date"):
                _status_by_date[td].update(grp["code"].tolist())
    # BJ 股 (board='bse')
    if "board" in price_data.columns:
        bj = price_data.loc[price_data["board"] == "bse", ["code", "trade_date"]]
        ...
```

**含义**: per-date 排除 ST / 停牌 / 新股 / BJ — 但**不排除退市股票** (退市后无 volume → WHERE volume>0 自动排除).

---

## §2 与 Plan v8 P0-11 假设对比

### §2.1 Plan v8 P0-11 原假设 (Subagent G 5-18 audit)

> "backend/engines/backtest/runner.py:138-154 — universe excludes ST/suspended/new_stock/BJ conditional on column presence; Grep delisted_at|退市 1 file (engine.py)
> **Backtest universe likely EXCLUDES delisted stocks entirely** (only stocks with current price data in DB). Historically delisted (ST*BL / 锐电 / etc.) silently absent. 12yr Sharpe=0.3594 might inflate by 0.1-0.2 if delisted included."

### §2.2 Session 58+1 真测真值反驳

| Plan v8 假设 | 真测真值 | 一致性 |
|---|---|---|
| backtest excludes delisted entirely | klines_daily 含 5743 唯一股 (含 322 退市), backtest SQL 无生存者过滤 | ❌ 假设不成立 |
| only stocks with current price data | WHERE k.trade_date BETWEEN %s AND %s — 历史日期 INCLUDED | ❌ 假设错误 |
| 12yr Sharpe inflated 0.1-0.2 | 0.3594 真值 sustained, 待 sensitivity test 量化 | ⏸ 待 验证 |

**Possible reasons for Subagent G 假设错误**:
- Subagent G grep "delisted_at|退市" 仅 1 file 命中 → 误判 universe 加载逻辑包含 delist 过滤
- 真值: `delist_date` 在 symbols 表 (5821 行 含 322 退市), 不在 klines_daily (按 date 自然 fade out 退市后)
- backtest 不 JOIN symbols → 历史退市股全部 included

### §2.3 真生存者偏差残余风险 (待深度验证)

1. **ST retroactive flag**: stock_status_daily 是否 sediment 真历史 ST 状态 (退市前的 ST 警示)? 若 ST 标志只 sediment 当前活跃股, 则历史退市股的 ST 期间错误地参与 backtest.
2. **factor_values 退市股 sediment 真值**: 退市股的 factor_values 是否 sediment 完整 (退市前最后交易日的 IC 是否被 dropna)?
3. **小盘 alpha + 退市 correlation**: CORE3+dv_ttm 选股 Top-20 (now PT_TOP_N=5) 是否真选过历史退市股? 如未选过 → 退市股的 included 不影响策略 Sharpe.

---

## §3 下一步深度验证 (~1-2 周 multi-session)

### §3.1 Phase J B3 完整 audit 任务清单

| # | 任务 | 验证方法 | Effort |
|---|---|---|---|
| 1 | factor_values 退市股 sediment 真值 | `SELECT MAX(trade_date) FROM factor_values WHERE code IN (322 退市股) GROUP BY code` | ~30min |
| 2 | stock_status_daily 历史 ST 真值 | `SELECT MIN/MAX(trade_date) FROM stock_status_daily WHERE is_st=true GROUP BY code, year_quarter` | ~30min |
| 3 | 5yr backtest 真 selected 选股 | 跑 `run_backtest --config configs/pt_live.yaml --start 2021-01-01 --end 2026-04-30` + 记录每月 Top-N 选股, 检验是否含已退市股 | ~3h |
| 4 | 12yr backtest 真 selected 选股 | 同上 12yr 窗口 | ~3h |
| 5 | Sensitivity test (含 vs 不含 退市) | 用 symbols.delist_date 显式构造两个 universe 集合, 比较 Sharpe diff | ~4h |
| 6 | Look-ahead bias 检验 | 退市股的 "最后选股日" 是否有信号 → 检验是否有 selection 之后退市的 case (即 selection 时退市未知, 但回测 hindsight 知道) | ~2h |
| 7 | 最终结论 sediment | Update Plan v8 P0-11 closure status + sediment LL-191 候选 (Subagent G 误报模式) | ~30min |

### §3.2 推荐 priority

**B3 任务 1+2 (factor_values + stock_status_daily 真值, ~1h)** 优先 — 决定后续 sensitivity test 必要性. 若任务 1+2 显示退市股的因子值/ST 标志 sediment 完整, 则:
- 假设证伪: Plan v8 P0-11 关闭 (类似 P0-24 false alarm)
- 假设部分成立: 任务 3-7 启动量化

### §3.3 timeline 预估

- 任务 1+2: 本 session 可执行 (~1h, autonomous)
- 任务 3+4: Phase B-2 后 (5-27+) 实施 (backtest run 需 1-2h GPU)
- 任务 5: 任务 1+2+3+4 完成后, ~4h
- 任务 6+7: 任务 5 后

**Total Phase J B3**: ~2 weeks 完整 close (含 backtest run + sensitivity).

---

## §4 关联

- [Plan v8 Master P0-11](audit/V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md) — 原始 finding
- [Plan v8 S1 §1.4 Universe Characteristics](audit/V3_AUDIT_S1_DOMAIN.md)
- [Plan v8 S7 §37 Survivorship Bias Audit](audit/V3_AUDIT_S7_ML_COST_HARDWARE.md)
- [PLAN_V8_MASTER_FINDINGS_REGISTER §4.2 U7 B3](audit/PLAN_V8_MASTER_FINDINGS_REGISTER_2026_05_19.md)
- backend/data/parquet_cache.py — backtest universe 加载 SQL (无生存者过滤验证)
- backend/engines/backtest/runner.py:138-154 — per-date ST/停牌/新股/BJ 排除
- LL-187 / LL-188 / LL-189 / LL-190 — 沿用 sediment pattern
- 候选 LL-191: Subagent audit 误报模式 (沿用 P0-11 + P0-24 双 false alarm precedent)

---

**初步审计结论**: Plan v8 P0-11 假设 PROBABLY FALSE. 待深度验证 (任务 1-7 完整 close). Phase J B3 起手 sediment 完成. 后续推进等用户决议 OR 续 session 接力.
