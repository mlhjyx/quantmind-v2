# 重构前回测基准记录

> **目的**: 固定当前引擎输出作为重构后的对比锚点
> **日期**: 2026-04-09
> **git tag**: `pre-refactor-baseline` (commit d8f69e4)
> **注意**: 这些数字反映当前引擎+当前数据(含code混乱)的真实输出，不代表"正确"结果

---

## 1. 数据快照

| 文件 | 行数 | 列 | 日期范围 | 大小 | MD5 |
|------|------|-----|---------|------|-----|
| price_data_5yr.parquet | 6,129,996 | code,trade_date,open,high,low,close,pre_close,volume,amount,up_limit,down_limit,is_st,turnover_rate | 2021-01-04~2025-12-31 | 172.3MB | 366ec10492ab34ec376f77182453de9d |
| factor_data_5yr.parquet | 30,626,040 | code,trade_date,factor_name,raw_value | 2021-01-04~2025-12-31 | 288.9MB | 44ab360112cb3087ed70c530cdb28d4c |
| benchmark_5yr.parquet | 1,212 | trade_date,close | 2021-01-04~2025-12-31 | 0.0MB | 7a6d2b9e3aeb354873214a1235b51b77 |

数据来源SQL:
- price_data: `klines_daily LEFT JOIN daily_basic ON code+trade_date, WHERE volume>0`
- factor_data: `factor_values WHERE factor_name IN (5核心因子), COALESCE(neutral_value, raw_value)`
- benchmark: `index_daily WHERE index_code='000300.SH'`

## 2. 5年基准回测 (2021-2025)

**配置**: 5因子等权, Top-20, 月度调仓, volume_impact滑点, 历史印花税, PMS enabled

| 指标 | 值 |
|------|-----|
| Sharpe | 0.4494 |
| MDD | -99.44% |
| 年化收益 | 24.23% |
| Calmar | 0.2437 |
| Sortino | 47.1854 |
| 总交易 | 1,902 |
| NAV起始 | 1,000,000.00 |
| NAV终值 | 2,839,586.75 |
| NAV最低 | 12,043.22 |
| NAV最高 | 2,945,785.26 |
| 交易日 | 1,212 |
| 耗时 | 83s |

### ⚠️ MDD=-99.44%的原因

NAV从100万跌到1.2万再涨到284万。根因:
1. **code格式混乱**: price_data含4788个带后缀的orphan code，factor全是无后缀
2. **退市垃圾股被选入**: 因子(amihud/bp_ratio)偏好低价小盘→选入退市前的垃圾股
3. **无ST过滤**: 当前回测路径(vectorized_signal)不过滤ST股
4. **BJ北交所股参与排名**: 北交所±30%涨跌停，风险远高于主板

重构后预期: MDD显著改善(code统一+ST过滤+信号路径统一)

## 3. 12年基准回测 (2014-2025, 排除BJ)

**配置**: 同上，但SQL额外加 `WHERE code LIKE '%.SH' OR code LIKE '%.SZ' OR code ~ '^[036]'`

| 指标 | 值 |
|------|-----|
| Sharpe | 0.3638 |
| MDD | -97.71% |
| 年化收益 | 13.25% |
| Sortino | 5.8140 |
| 总交易 | 4,484 |
| NAV终值 | 4,225,871 |
| NAV最低 | 104,955 |
| 交易日 | 2,919 |
| 耗时 | 432s (含190s数据加载) |

## 4. 回归测试 (regression_test.py)

| 项目 | Run 1 | Run 2 |
|------|-------|-------|
| max_diff | 0.0 | 0.0 |
| max_pct_diff | 0.0% | 0.0% |
| days_above_0.001% | 0 | 0 |
| Sharpe | 0.4496 | 0.4496 |
| 耗时 | 118s | 98s |
| **确定性** | **YES ✅** | |

Run 1 vs baseline: max_diff=0.0 (完全一致)
Run 1 vs Run 2: max_diff=0.0 (确定性验证通过)

## 5. 备份

| 类型 | 路径 | 大小 | 状态 |
|------|------|------|------|
| pg_dump (custom) | backups/pre_refactor_20260409.dump | 9.5GB | ✅ |
| git tag | pre-refactor-baseline | commit d8f69e4 | ✅ |
| 每日自动备份 | backups/daily/quantmind_v2_20260408.dump | 7.7GB | ✅ |

## 6. 已知问题对基准数字的影响

| 问题 | 影响方向 | 预计影响量级 |
|------|---------|-------------|
| code格式混乱(37%带后缀) | 部分股票因子与价格不匹配→NAV异常 | MDD虚高50%+ |
| 无ST过滤 | 退市垃圾股被选入 | MDD虚高30%+ |
| 双信号路径(PT用SignalComposer,回测用vectorized_signal) | 回测结果不代表PT | 未知 |
| factor_data用COALESCE(neutral,raw) | 混合中性化和原始值 | Sharpe偏差±0.1 |
| rebalance_freq默认"biweekly"但PT用"monthly" | 不影响(基准显式传了monthly) | 0 |

**重构完成后**: 用相同的regression_test.py对比，预期Sharpe上升、MDD大幅改善。
