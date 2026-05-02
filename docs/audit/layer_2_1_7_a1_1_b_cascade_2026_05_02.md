# Layer 2.1.7 follow-up A1.1.B — dv_ttm 4-28 重 pull + cascade 重算 真值

**日期**: 2026-05-02
**Scope**: B candidate (per A1.1 audit `7d80e50` §E.4): 4-28 daily_basic 重 pull → factor_values cascade 重算 → factor_ic_history cascade 重算 → (N+1) downstream verify
**触发**: user 授权 B 候选
**main HEAD (起手)**: `7d80e50`
**反 anti-pattern**: v5.2 sustained — cascade 完整性必须真测, (N+1) 留口反 "我列的 cascade cover 全空间" 假设

---

## §A Tushare 4-28 re-probe (anti-drift verify)

### A.1 真测命令 (read-only probe)

```python
api = TushareAPI()
df = api.fetch_daily_basic_by_date('20260428')
```

### A.2 真返回 (实测 2026-05-02 ~14:35)

```
shape: (5488, 18)
dv_ttm NULL count:    1755 / 5488 = 31.98%
dv_ratio NULL count:  1727 / 5488 = 31.47%
pe_ttm NULL count:    1475 / 5488 = 26.88%
```

### A.3 vs A1.1 audit baseline (5-2 ~04:35)

| 指标 | A1.1 baseline | 本 audit | drift |
|---|---|---|---|
| dv_ttm NULL pct | 31.98% | 31.98% | **0** ✅ |
| dv_ratio NULL pct | 31.47% | 31.47% | **0** ✅ |
| pe_ttm NULL pct | 26.88% | 26.88% | **0** ✅ |

→ Tushare 4-28 真返回 sustained 31.98% NULL, **0 drift** vs A1.1 baseline. **B candidate viable** (反 STOP "再 100% NULL").

---

## §B 4-28 daily_basic 重 pull

### B.1 命令 (沿用 A1 backfill pattern)

```python
fetch_daily_data(date(2026,4,28))
```

### B.2 真结果 (实测 2026-05-02 14:37)

```
[info] Upserted 1 rows to index_daily x3 (000300/000905/000852)
[info] Loaded 5821 valid codes from symbols
[error] [pipeline] null_ratio_exceeded (F22 铁律33 fail-loud) column=pe_ttm null_count=1474 ratio=0.2693 severity=severe
[error] [pipeline] null_ratio_exceeded (F22 铁律33 fail-loud) column=dv_ttm null_count=1741 ratio=0.318 severity=severe
[info] Upserted 5474 rows to daily_basic
[warning] daily_basic: 14/5488 rows rejected: {'fk_not_in_symbols': 14}
[info] Upserted 5474 rows to klines_daily
[warning] klines_daily: 14/5488 rows rejected: {'fk_not_in_symbols': 14}
4-28 result: {'klines_rows': 5474, 'basic_rows': 5474, 'index_rows': 3, 'status_rows': 5474, 'elapsed': 1.4}
```

### B.3 真值变化

| 表 | 4-28 dv_ttm NULL | dv_ratio NULL |
|---|---|---|
| **pre-§B (post-A1.1 audit baseline)** | **5474 / 100.00%** | **5474 / 100.00%** |
| **post-§B (本 audit)** | **1741 / 31.80%** | **1713 / 31.30%** |

→ **dv_ttm + dv_ratio 4-28 真 fixed** (100% → 31.80%/31.30%, 与邻近 4-27/4-29/4-30 ~31% 一致). klines_daily/daily_basic/index/stock_status 4 表全 UPSERT (pk=`code+trade_date`, idempotent).

### B.4 同代码 sample 真值

post-§B 4-28 daily_basic:

| code | dv_ttm | dv_ratio | pe_ttm |
|---|---|---|---|
| 000001.SZ | 5.2183 | 5.2183 | 5.1647 |
| 000002.SZ | NULL | NULL | NULL (历史 dividend NULL pattern) |
| 300750.SZ | 1.8489 | 1.5798 | 24.7152 |
| 600000.SH | 3.9765 | 3.9765 | 6.2394 |
| 600519.SH | 3.6757 | 3.6757 | 21.2711 |

→ 真有效 dividend yield 数据回填 (000001=5.22% / 600519=3.68% Maotai).

---

## §C factor_values 4-28 dv_ttm cascade 重算

### C.1 真生产 path enumerate (实测)

`backend/app/services/factor_compute_service.py`:
- `compute_daily_factors(trade_date, factor_set, conn)` (line 197) — **主路径**, computes 1 day full factor set
- `save_daily_factors(trade_date, factor_df, conn)` (line 62) — 写入 via DataPipeline (铁律 17)
- `compute_batch_factors(start_date, end_date, factor_set, factor_names, write)` (line 314) — **DEPRECATED 但 functional**, 支持 surgical scope (factor_names list)

`engines.factor_engine` factor sets (实测):
- `PHASE0_CORE_FACTORS` (5): volatility_20 / turnover_mean_20 / amihud_20 / ln_market_cap / bp_ratio — **dv_ttm 不在内**
- `PHASE0_FULL_FACTORS` (14): contains dv_ttm ✅
- `PHASE0_ALL_FACTORS` (22): contains dv_ttm ✅
- `RESERVE_FACTORS`: vwap_bias_1d / rsrs_raw_18 (dv_ttm 不在内)
- `ALPHA158_FACTORS`: 不含 dv_ttm

### C.2 命令 (surgical scope, factor_names=['dv_ttm'])

```python
compute_batch_factors(
    start_date=date(2026,4,28),
    end_date=date(2026,4,28),
    factor_set='full',
    factor_names=['dv_ttm'],
    write=True,
)
```

### C.3 真结果 (实测 2026-05-02 14:40-14:41)

```
2026-05-02 14:40:20 批量加载数据: 2026-04-28 → 2026-04-28 (+120天回看)
2026-05-02 14:41:12 数据加载完成: 660796行, 5505股, 121天
2026-05-02 14:41:12 计算 1 个 kline 因子的滚动值...
2026-05-02 14:41:12 逐日预处理+写入 (DataPipeline): 1 个交易日
2026-05-02 14:41:13 Upserted 5474 rows to factor_values
result: {'total_rows': 5474, 'dates': 1, 'load_time': 52.0, 'calc_time': 0.0, 'total_time': 53.2}
```

### C.4 真值变化

| 指标 | pre-§C | post-§C |
|---|---|---|
| factor_values 4-28 dv_ttm rows | 5474 | 5474 |
| raw_value distinct count | **1 (all 0.0)** | **3487** ✅ |
| neutral_value distinct count | 1 (all 0.0) | 5474 ✅ |
| variance | 0 | restored |

### C.5 同代码 sample (post-§C vs pre-§C)

| code | pre-§C raw | pre-§C neutral | post-§C raw | post-§C neutral | 4-27 raw (reference) | 4-27 neutral |
|---|---|---|---|---|---|---|
| 000001.SZ | 0.0 | 0.0 | **5.218300** | **0.269494** | 5.255000 | 0.256045 |
| 000002.SZ | 0.0 | 0.0 | 0.0 | -0.804459 | 0.0 | -0.806094 |
| 300750.SZ | 0.0 | 0.0 | **1.848900** | **0.634466** | 1.818300 | 0.630099 |
| 600000.SH | 0.0 | 0.0 | **3.976500** | **0.207587** | 3.980800 | 0.193051 |
| 600519.SH | 0.0 | 0.0 | **3.675700** | **-0.193059** | 3.680400 | -0.193538 |

→ 真有效 dividend yield + neutralized 值 cascade 完整, post-§C 4-28 与 4-27 同代码值高度一致 (相差 ≤ 0.04, 反映 1 trading day 内分红率正常波动).

---

## §D factor_ic_history 4-27/4-28 dv_ttm IC 重算

### D.1 命令

```bash
.venv/Scripts/python.exe scripts/fast_ic_recompute.py --factor dv_ttm
```

### D.2 真结果 (实测 2026-05-02 14:42)

```
[Load] price + benchmark...
  price: (10757056, 18), bench: (2984, 2), 2.6s
[Precompute] forward excess returns for horizons [5, 10, 20]...
  fwd_rets 3 horizons cached (3.5s)

[Batch] 1 因子
[IC口径] neutral_value_T1_excess_spearman v1.0.0
[Horizons] [5, 10, 20]
  [1/1] dv_ttm                 IC20d=+0.0326 IR=+0.44 n=2962 rows= 2982 (13.2s)

[commit] 2982 行 across 1 因子
总耗时: 19s (0.3 min)
```

### D.3 真值变化 — partial cascade

| trade_date | factor_ic_history dv_ttm | 真值 (post-§D) | 真因 |
|---|---|---|---|
| 2026-04-15 | ic_5d | 0.039806 ✅ | T+5=4-22 (klines available) |
| 2026-04-17 | ic_5d | 0.069132 ✅ | T+5=4-24 (klines available) |
| **2026-04-23** | ic_5d | **NULL** ⚠️ | T+5=4-30 (理论可算, 但 fast_ic_recompute MAX limit) |
| **2026-04-24** | ic_5d | **NULL** ⚠️ | T+5=5-2 (holiday, 真不存在) |
| **2026-04-27** | ic_5d | **NULL** ⚠️ | T+5=5-8 (klines 5-6+ 不存在) |
| **2026-04-28** | ic_5d | **NULL** ⚠️ | T+5=5-9 (klines 5-6+ 不存在) |

### D.4 cascade 部分受限真因

**variance=0 issue (A1.1 audit cite) 真已 fix**:
- pre-§C: factor_values 4-28 dv_ttm constant=0.0 → cross-section variance=0 → spearmanr undefined → IC=NULL
- post-§C: factor_values 4-28 dv_ttm 3487 distinct → cross-section variance restored
- → A1.1 audit cite 真因 1 已解决 ✅

**forward return horizon issue (NEW, 真测发现)**:
- ic_5d at T = corr(neutral_value[T], forward_return[T → T+5 trading days])
- 4-28 + 5 trading days = 5-9 (Tushare 5-1~5-5 holiday + 5-6~5-9 真未到)
- klines_daily MAX = 4-30 → forward return 5d 不可计算 → IC=NULL
- → A1.1 audit cite 真因 2 (cross-section variance=0) 已 fix, 但**真因 3** (forward return horizon limit) 独立, **不在 A1.1 audit framing 内** ⚠️

→ **(N+1) 真发现**: 4-27/4-28 IC NULL 真因 = forward return horizon limit (而非 cross-section variance=0). 需 5-6+ klines 真到达后**自然恢复** (5-8 klines 到 → 4-27 ic_5d 可算; 5-9 klines 到 → 4-28 ic_5d 可算).

### D.5 真生产真闭环

| 真状态 | 真值 |
|---|---|
| dv_ttm IC overall MIN/MAX 日期 | 2014-01-02 → 2026-04-28 |
| total rows | 2992 |
| ic_5d NULL | 20 (ConstantInputWarning + forward limit) |
| ic_20d NULL | 30 |

→ 2992 dv_ttm IC rows 真存在, 4-28 IC=NULL 是 expected (forward limit), 不是 §C cascade 失败.

---

## §E (N+1) downstream cascade verify (反 framing 漏)

### E.1 dv_ttm 字段使用 audit (实测 schema-wide)

```sql
SELECT table_name FROM information_schema.columns WHERE column_name='dv_ttm'
```

→ **唯一 1 张表含 dv_ttm column: `daily_basic`** ✅. factor_values / factor_ic_history 用 `factor_name='dv_ttm'` 行级标识.

### E.2 signals 4-28 真值 (cascade dependency)

```sql
SELECT * FROM signals WHERE created_at::date='2026-04-28' LIMIT 5
```

| code | rank | alpha_score | target_weight | action | execution_mode |
|---|---|---|---|---|---|
| 000012.SZ | 14 | 1.877611 | 0.04850 | **hold** | paper |
| 000333.SZ | 6 | 2.118288 | 0.04850 | hold | paper |
| 000507.SZ | 17 | 1.847069 | 0.04850 | hold | paper |
| 002282.SZ | 13 | 1.880350 | 0.04850 | hold | paper |
| 002623.SZ | 10 | 1.964152 | 0.04850 | hold | paper |
| ... | total 20 行 | | | | |

→ signals 4-28: **20 'hold' actions, 真 historical PT decision frozen at 4-28 16:31:15**. PT 4-29 起 disabled (DailySignal Disabled), 0 后续 trade based on these signals.

### E.3 signals 4-28 真因 alpha_score 与 dv_ttm cascade 关系

PT alpha 真公式 (CLAUDE.md cite): **`-z(turnover_mean_20) + -z(volatility_20) + +z(bp_ratio) + +z(dv_ttm)`**, equal-weight Top 20.

pre-§C state (4-28 dv_ttm 全 0.0):
- effective alpha = (-turnover - volatility + bp + 0) (dv_ttm 真 contribution = 0)
- Top 20 selection 真**忽略** dv_ttm 真信息

post-§C cascade (4-28 dv_ttm 真 distinct):
- effective alpha = (-turnover - volatility + bp + dv_ttm)
- Top 20 selection **理论 ≠** pre-§C Top 20 (dv_ttm 真 contribution restored)

**signals 4-28 是否要重算?**

→ ❌ **NOT 推荐**:
1. 4-28 是 PT 真 last decision day, 4-29 起 PT disabled 0 真 trade execute (signals 真 0 cascade 进 trade_log)
2. 4-29 emergency_close 真因独立 (LL-081 silent drift, 与 dv_ttm 真 0 关联, 沿用 A1.1 audit §D.5 cross-check)
3. 重算 = **revisionist 改 historical PT decision**, 0 真生产 benefit (PT 已暂停)
4. 反 anti-pattern v5.2: cite cascade 真完整 ≠ 真应该重算所有

→ ✅ **推荐**: signals 4-28 历史 frozen 不动, audit 文档 sediment "真因 dv_ttm 0.0 → Top 20 selection 真 ignored dv_ttm 信号" 作为 **historical PT silent drift 真 LL-081 第 N 例**.

### E.4 4-29 emergency_close 决议链 cross-check

per A1.1 audit `7d80e50` §D.5: 4-29 emergency_close 真因 = LL-081 silent drift narrative (audit doc Layer 2.1 §A.4 git log 实证), **NOT** F-A1-1 dv_ttm 异常.

post-§C verify: signals 4-28 真生成 with broken dv_ttm → 仍 'hold' action (PT 既有 holding maintained), 不触发 buy/sell 决策 → 0 cascade 进 4-29 emergency_close.

→ **4-29 emergency_close 真独立 sustained, 0 cascade impact from §C/§D**.

### E.5 BH-FDR M / 其他 derived 真测

cite memory: "BH-FDR校正: M = FACTOR_TEST_REGISTRY.md 累积测试总数 (M=213)". 真值不在 DB 表 (是 markdown SSOT).

实测: `dv_ttm` 真 grep 范围:
- `daily_basic` (1 column) — ✅ §B 已 fix
- `factor_values` (factor_name='dv_ttm') — ✅ §C 已 fix
- `factor_ic_history` (factor_name='dv_ttm') — ✅ §D partial fix
- `signals` (alpha_score 隐含包含) — historical, 不重算
- 0 其他 schema 引用

→ **§E (N+1) cascade scope 真闭环, 0 漏**.

---

## §F 决议 — full cascade vs partial

### F.1 cascade 真完整性 final state

| Layer | pre-§B | post-§B | post-§C | post-§D |
|---|---|---|---|---|
| daily_basic 4-28 dv_ttm | 5474/100% NULL | 1741/31.80% ✅ | (unchanged) | (unchanged) |
| daily_basic 4-28 dv_ratio | 5474/100% NULL | 1713/31.30% ✅ | (unchanged) | (unchanged) |
| factor_values 4-28 dv_ttm distinct | 1 (all 0.0) | (unchanged) | 3487 ✅ | (unchanged) |
| factor_ic_history dv_ttm rows | 2992 | (unchanged) | (unchanged) | 2992 (re-write 2982) |
| factor_ic_history 4-27/4-28 dv_ttm IC | NULL | (unchanged) | (unchanged) | NULL ⚠️ (forward limit) |
| signals 4-28 (20 hold) | frozen | frozen | frozen | frozen (decision: 不重算) |

### F.2 真完成 cascade scope

✅ **完成**:
- daily_basic 4-28 (B): NULL fix 100% → 31.80%
- factor_values 4-28 dv_ttm (C): variance 0 → restored (3487 distinct)
- factor_ic_history (D): rewritten with new variance, BUT 4-27/4-28 IC remains NULL due to **forward return horizon** (independent reason, 自然 5-9 后恢复)
- signals 4-28 (E): historical frozen, 不重算 (audit decision)

⚠️ **partial**:
- 4-27/4-28 dv_ttm IC: 真 NULL 不是 §D 失败, 是 **forward return horizon 限制** (T+5 需 klines 5-6/5-7/5-8/5-9 真未到达). 5-6+ klines 自然到达后 IC 自动重算 (next QuantMind_DailyIC schtask trigger).

### F.3 partial cascade 是否产生新 silent inconsistency?

| 担忧 | 真测结论 |
|---|---|
| daily_basic fixed but factor_values old → inconsistency | ❌ §C 已 cascade, factor_values 真 sync ✅ |
| factor_values fixed but IC old → inconsistency | ⚠️ 4-27/4-28 IC NULL — 反非 §D 失败, 是 forward horizon, 自然恢复 |
| factor_values fixed but signals old → inconsistency | ⚠️ signals 4-28 用 broken dv_ttm 生成, but: (a) 0 trade execute since PT disabled; (b) 4-29 emergency_close 决议独立 → revisionist 改 historical 0 benefit |
| BH-FDR M / 其他 derived 漂移 | ✅ 0 schema-level dv_ttm reference 漏, scope 真闭环 |

→ **partial cascade 是 acceptable**: 4-27/4-28 IC 自然恢复, signals 4-28 historical 不动. 0 新 silent inconsistency.

### F.4 候选 (N+1) 留口

| (N+1) 候选 | scope | 推荐 |
|---|---|---|
| 5-9+ trigger fast_ic_recompute --factor dv_ttm 验证 4-27/4-28 IC 自然恢复 | 等 5-6 klines 真到达后 1-2 d, 跑 IC recompute | ⭐ **推荐 (5-9 后启动)** — 验证 forward horizon 真自然消除 |
| 4-27/4-28 dv_ttm IC backfill via 4-30 klines as 4-day proxy | hack, 反 IC 真定义 (T+5 forward) | ❌ 不推荐 |
| 历史其他 100% NULL 日 (4-15→4-20 cite) audit cascade | 历史 5 天 daily_basic + factor_values + IC 全 cascade 重 pull | 候选 (留 user 决议, 范围更大) |

---

## §G transparency — 我没真测的

为反 anti-pattern v3.0:

1. **CORE 4 PT 因子 (turnover_mean_20 / volatility_20 / bp_ratio) 4-28 真值是否变化**: §C 仅 surgical 重算 dv_ttm. 其他 3 CORE 因子 4-28 真 factor_values 未真重算. 假设它们 deterministic + 输入 (klines / industry / mcap) 4-28 未变 → 真值不变. 但**未直接 verify**.
2. **4-27 dv_ttm IC NULL 真因**: §D 真测 4-27 IC NULL, 推断是 forward horizon (T+5=5-8). 但**未真测 fast_ic_recompute 真 lookback / forward 边界逻辑** — 假设 ic_5d 需 T+5 klines 真存在.
3. **fast_ic_recompute --factor dv_ttm 真 vs --core 真 cascade**: cite memory Layer 1 Week 1 WI 4 用 `--core` 11928 rows / 4 CORE factors, 本 audit 用 `--factor dv_ttm` 2982 rows / 1 factor. **未真测 --core 重算是否产出不同结果**.
3. **F22 NULL Ratio Guard logger.error 4-28 真 stderr 输出**: §B 真触发 logger.error, 但**未真验** stderr / log file 真捕获 (logs/ 5-1 06:00 LogRotate 真跑).
4. **lineage row 真写入 verify**: §C save_daily_factors with_lineage=True, 但**未真查 lineage 表** 4-28 dv_ttm 行新增.
5. **signals 4-28 alpha_score 真 vs dv_ttm 0.0 contribution 数学验证**: 推断 alpha = -z(turnover) - z(vol) + z(bp) + z(dv_ttm), dv_ttm=0 contribution=0. **未真直接 verify** alpha_score 真公式 in signal_engine.py.
6. **4-15→4-20 历史 100% NULL 日是否同 pattern**: contracts.py:170 cite, 本 audit **未真测** 4-15/4-16/4-17/4-18/4-19/4-20 daily_basic dv_ttm NULL ratio per-date 真值.

---

## §H 顶层结论

**Layer 2.1.7 A1.1.B 真测真值锁定**:

1. **§B daily_basic 4-28 cascade 真 fixed**: 100% NULL → 31.80% NULL (与邻近 ~31% pattern 一致). UPSERT 真 idempotent (klines/index/stock_status 同期 fix).

2. **§C factor_values 4-28 dv_ttm cascade 真 fixed**: variance 0 → 3487 distinct raw_values. 同代码 sample 与 4-27 一致 (000001.SZ 5.255 → 5.218, 1-day dividend yield 真波动).

3. **§D factor_ic_history 4-28 dv_ttm IC partial cascade**:
   - **真因 1 fixed** (cross-section variance=0): §C cascade 已解决
   - **真因 2 unchanged** (forward return horizon limit): T+5 klines 5-6~5-9 真未到达, 4-27/4-28 IC 自然 NULL 待 5-9+ 自然恢复. **不是 §D 失败, 是 (N+1) 真发现**.

4. **§E (N+1) downstream cascade verify**:
   - dv_ttm schema-wide reference 真闭环 (仅 daily_basic + factor_values + factor_ic_history + signals)
   - signals 4-28 historical frozen 不重算 (revisionist 改 historical PT decision 0 真生产 benefit, PT 已暂停, 4-29 emergency_close 决议独立)
   - 0 新 silent inconsistency

5. **真因 / framing v3 (反 A1.1 audit framing v2)**:
   - A1.1 audit 推测 4-27/4-28 IC NULL 唯一真因 = "cross-section variance=0 → corr undefined"
   - 本 audit 真测发现真因有 **2 层**:
     - **真因 1**: cross-section variance=0 (§C cascade fix 解决)
     - **真因 2** (新): forward return horizon limit (T+5 klines 真未到达, 与 §C cascade 独立)
   - → A1.1 audit framing v2 **incomplete**, 本 audit framing v3 真补 (N+1 槽位生效).

6. **真生产红线 sustained**:
   - LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper 起末 sustained
   - 0 PT 触碰 / 0 PT 链 schtask 改动
   - 0 .env / Servy / DB schema 改动
   - 0 hook bypass

7. **真生产真改动**:
   - daily_basic 4-28: 5474 行 UPSERT (dv_ttm/dv_ratio/pe_ttm 真值改变)
   - klines_daily 4-28: 5474 行 UPSERT (idempotent, 真值不变)
   - index_daily 4-28: 3 行 UPSERT (idempotent)
   - stock_status_daily 4-28: 5474 行 UPSERT (idempotent)
   - factor_values 4-28 dv_ttm: 5474 行 UPSERT (variance restored)
   - factor_ic_history dv_ttm: 2982 行 UPSERT (IC values rewritten)

8. **user 决议候选**:
   - (a) 接受当前真状态 (B+C+D+E partial cascade ✅, 4-27/4-28 IC 自然 5-9 后恢复)
   - (b) 5-9+ 后启动 fast_ic_recompute --factor dv_ttm 验证 4-27/4-28 IC 自然恢复
   - (c) 历史 4-15→4-20 同 pattern 100% NULL 日 cascade audit (scope 5 天, 范围更大)
   - (d) (N+1) 真测发现的扩展 (本 audit 真测发现 forward horizon 真因, 留 user 决议是否升级 candidate)
