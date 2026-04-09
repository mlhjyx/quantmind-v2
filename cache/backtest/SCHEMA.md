# cache/backtest/ Parquet 缓存 Schema

> **创建**: Step 5 (2026-04-09)
> **文档**: Step 6-D Fix 1 (2026-04-09)
> **构建脚本**: `backend/data/parquet_cache.py` 的 `BacktestDataCache.build()`
> **CLI**: `python scripts/build_backtest_cache.py --start 2014-01-01 --end 2026-04-09`

---

## 目录结构

```
cache/backtest/
├── SCHEMA.md                    ← 本文件
├── 2014/
│   ├── price_data.parquet       (~20 MB)
│   ├── factor_data.parquet      (~25 MB)
│   └── benchmark.parquet        (<1 KB)
├── 2015/ 2016/ ... 2025/ 2026/  (同样三文件)
└── cache_meta.json              (构建时间戳, 可选)
```

13 年份共 39 个 Parquet 文件, 总计约 **936 MB**。

---

## price_data.parquet (18 列)

每行 = 一只股票在一个交易日的完整行情 + 状态标记。

| 列 | 类型 | 说明 | 单位 |
|----|------|------|------|
| `code` | str | 带后缀 (例 `600519.SH`/`920819.BJ`) — Step 1 后统一 | - |
| `trade_date` | date | 交易日 | - |
| `open` | float | 开盘价 | 元 |
| `high` | float | 最高价 | 元 |
| `low` | float | 最低价 | 元 |
| `close` | float | 收盘价 | 元 |
| `pre_close` | float | 前收盘 (T-1 复权前) | 元 |
| `volume` | float | 成交量 | 手 |
| `amount` | float | 成交额 | **元** (非千元, Step 3-A 后统一) |
| `up_limit` | float | 当日涨停价 | 元 |
| `down_limit` | float | 当日跌停价 | 元 |
| `adj_factor` | float | 复权因子 (Tushare 原始, PIT 安全) | - |
| `adj_close` | float | 前复权收盘价 = `close × adj_factor / latest_adj_factor` | 元 |
| `turnover_rate` | float | 日换手率 (来自 daily_basic) | % (0-100) |
| `is_st` | bool | ST 标记 (来自 stock_status_daily) | - |
| `is_suspended` | bool | 停牌标记 (volume=0 或 Tushare 标记) | - |
| `is_new_stock` | bool | 次新股标记 (list_date<60 日) | - |
| `board` | str | 板块 `main` / `gem` (创业板) / `star` (科创板) / `bse` (北交所) | - |

**构建 SQL**: `PRICE_SQL` in `backend/data/parquet_cache.py`, JOIN `klines_daily` + `daily_basic` + `stock_status_daily`。

---

## factor_data.parquet (4 列) ⚠️ **列名误导**

每行 = 一个因子在一只股票一个交易日的值。

| 列 | 类型 | 说明 |
|----|------|------|
| `code` | str | 带后缀 |
| `trade_date` | date | 交易日 |
| `factor_name` | str | 因子名 (CORE 5: `turnover_mean_20`/`volatility_20`/`reversal_20`/`amihud_20`/`bp_ratio`) |
| `raw_value` | float | **⚠️ 实际是 WLS 中性化后的值**, 见下方警告 |

### ⚠️ `raw_value` 列名陷阱

**这个列名是历史遗留, 不要按字面意思理解。**

构建时 SQL 是:
```sql
SELECT code, trade_date, factor_name,
       COALESCE(neutral_value, raw_value) as raw_value  -- ← 别名冲突
FROM factor_values
```

**实际语义**:
1. 优先返回 `factor_values.neutral_value` (MAD → fill → WLS 行业+ln_mcap → zscore → clip±3)
2. 仅当 `neutral_value IS NULL` 时才回退到真正的 `factor_values.raw_value`
3. 结果集被**别名为 `raw_value`**

所以 Parquet 里的 `raw_value` 列 **99%+ 是中性化后的值**, 少数回退的行才是真正的原始值 (通常很少, 因为全量生产因子都走了中性化管道)。

### 为什么不直接叫 `neutral_value`

因为 `run_hybrid_backtest()` (runner.py) 在入口有这行兼容代码:
```python
if "neutral_value" not in factor_df.columns and "raw_value" in factor_df.columns:
    factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})
```

回测引擎内部消费的都是 `neutral_value`, 但外层接受 `raw_value` 输入。改列名会要求:
1. 重建全部 39 个 Parquet 文件 (约 5-10 分钟)
2. 重置 `cache/baseline/nav_5yr.parquet` 基线 hash
3. `regression_test.py` 重新 pin max_diff=0

为了保持 Step 5 基线的可重现性 (`Sharpe=0.6095, max_diff=0`), 决定**不改列名, 只加文档**。

---

## benchmark.parquet (2 列)

CSI300 指数日线。

| 列 | 类型 | 说明 |
|----|------|------|
| `trade_date` | date | 交易日 |
| `close` | float | 指数收盘价 |

---

## 直接读 Parquet 的正确姿势

### ✅ 走回测引擎入口 (推荐)

```python
import pandas as pd
from engines.backtest import BacktestConfig
from engines.backtest.runner import run_hybrid_backtest

# 加载 12 年数据
frames_pd, frames_fd, frames_bm = [], [], []
for year in range(2014, 2027):
    frames_pd.append(pd.read_parquet(f"cache/backtest/{year}/price_data.parquet"))
    frames_fd.append(pd.read_parquet(f"cache/backtest/{year}/factor_data.parquet"))
    frames_bm.append(pd.read_parquet(f"cache/backtest/{year}/benchmark.parquet"))
price_df  = pd.concat(frames_pd, ignore_index=True)
factor_df = pd.concat(frames_fd, ignore_index=True)  # "raw_value" 列实际是中性化值
bench_df  = pd.concat(frames_bm, ignore_index=True)

directions = {
    "turnover_mean_20": -1, "volatility_20": -1,
    "reversal_20": 1, "amihud_20": 1, "bp_ratio": 1,
}
config = BacktestConfig(initial_capital=1_000_000, top_n=20, rebalance_freq="monthly")
result = run_hybrid_backtest(factor_df, directions, price_df, config, bench_df)
# run_hybrid_backtest 内部自动 rename raw_value → neutral_value
```

### ⚠️ 直接读 `raw_value` 做 IC 计算 (常见错误)

```python
# 错误心智模型:
fv = pd.read_parquet("cache/backtest/2021/factor_data.parquet")
# 用户以为: fv["raw_value"] 是原始因子值
# 实际上: fv["raw_value"] 是 WLS 中性化 + zscore clip±3 后的值
# → 计算 "raw IC" 会得到 neutralized IC, 符号/大小跟 factor_ic_history 可能不一致
```

如果你**真的**需要原始 (非中性化) 因子值, 请直接查 `factor_values.raw_value` 列:
```sql
SELECT code, trade_date, factor_name, raw_value
FROM factor_values
WHERE factor_name IN (...) AND trade_date BETWEEN ... AND ...
```
而不是读这里的 Parquet。

---

## 已知的下游使用者

| 文件 | 怎么用 | 正确性 |
|------|--------|-------|
| `scripts/regression_test.py` | 读 `cache/baseline/*_5yr.parquet` | ✅ 经过 `run_hybrid_backtest`, rename 生效 |
| `scripts/run_backtest.py` (YAML path) | 通过 `backend/data/parquet_cache.py::BacktestDataCache.load()` | ✅ 同上 |
| `backend/data/parquet_cache.py` (builder) | 构建 Parquet, SQL COALESCE | ✅ 写入时就是中性化 |
| `backend/engines/backtest/runner.py` | rename hack | ✅ |
| (新) `scripts/wf_equal_weight_oos.py` | 通过 `make_equal_weight_signal_func`, 自动 rename | ✅ |
| (老) 任何直接 `pd.read_parquet` + 使用 `raw_value` 名义的代码 | ⚠️ 需要注意 |

---

## 相关文件

- `backend/data/parquet_cache.py` — 缓存构建 + 读取
- `scripts/build_backtest_cache.py` — CLI 入口
- `backend/engines/backtest/runner.py` — `run_hybrid_backtest()` 入口, rename hack 在这
- `cache/baseline/BASELINE_RECORD.md` — regression 基线记录
- `scripts/regression_test.py` — 基线回归测试
