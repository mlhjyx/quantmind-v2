# 因子中性化与入库体系 (Factor Onboarding System)

> **版本**: v1.0 (2026-04-12)
> **触发**: P0-4 — RSQR_20 NaN事件暴露系统性缺陷

---

## 1. 存储架构

### 1.1 核心表

| 表名 | 用途 | 行数(估) | 存储引擎 |
|------|------|----------|---------|
| `factor_values` | 所有因子的统一存储 | ~590M | TimescaleDB hypertable |
| `factor_ic_history` | IC计算结果入库 | ~100K | 普通表 |
| `factor_registry` | 因子元数据注册 | ~84 | 普通表 |
| `northbound_holdings` | 北向持仓原始数据 | ~15M | 普通表 |
| `moneyflow_daily` | 资金流向原始数据 | ~15M | 普通表 |
| `daily_basic` | 估值/市值/换手率 | ~15M | 普通表 |
| `earnings_announcements` | 盈利公告事件 | ~50K | 普通表 |

### 1.2 factor_values Schema

```sql
CREATE TABLE factor_values (
    code          VARCHAR(10) NOT NULL,
    trade_date    DATE NOT NULL,
    factor_name   VARCHAR(50) NOT NULL,
    raw_value     DECIMAL(16,6),       -- 原始计算值
    neutral_value DECIMAL(16,6),       -- 中性化后的值
    zscore        DECIMAL(16,6),       -- 标准化值（部分因子）
    PRIMARY KEY (code, trade_date, factor_name)
);
-- TimescaleDB hypertable, 按trade_date分区
```

**关键约束**:
- `raw_value` 和 `neutral_value` 都是 DECIMAL(16,6)，PostgreSQL 中 NaN 是合法的 NUMERIC 值但**不等于 NULL**
- `COALESCE(neutral_value, raw_value)` 在 neutral_value = NaN 时返回 NaN（不回退到 raw_value）

### 1.3 Parquet 缓存架构

```
cache/backtest/{year}/
  ├── price_data.parquet     # klines + daily_basic + stock_status
  ├── factor_data.parquet    # COALESCE(neutral_value, raw_value) as raw_value (仅CORE5)
  ├── benchmark.parquet      # CSI300 index
  └── cache_meta.json        # 元数据
```

- **生成脚本**: `scripts/build_backtest_cache.py`
- **触发方式**: 手动 (❌ 无自动化)
- **包含因子**: 仅 CORE5 (turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio)
- **问题**: Phase 1.2 SW1迁移后未重建，导致DB/Parquet不一致

---

## 2. 因子清单与健康状态 (2024年采样)

### 2.1 汇总

| 状态 | 数量 | 说明 |
|------|------|------|
| ✅ 健康 | 54 | neutral_value > 90% 有效 |
| ❌ NaN | 6 | Phase 2.1 因子，中性化产生 float NaN (正在修复) |
| ⚠️ NULL | 10 | 北向因子，从未做过中性化 |
| **总计** | **70** | |

### 2.2 ❌ NaN 因子 (Phase 2.1, 2026-04-12 修复中)

| 因子 | 行数 | NaN% | 根因 | 修复状态 |
|------|------|------|------|---------|
| RSQR_20 | 1,294,202 | 0.2% | factor_onboarding写入NaN | ✅ 已修复 |
| QTLU_20 | 1,327,826 | 100% | 同上 | 🔄 修复中 |
| IMAX_20 | 1,327,826 | 100% | 同上 | ⬜ 排队 |
| IMIN_20 | 1,327,826 | 100% | 同上 | ⬜ 排队 |
| CORD_20 | 1,285,710 | 100% | 同上 | ⬜ 排队 |
| RESI_20 | 1,327,826 | 100% | 同上 | ⬜ 排队 |
| high_vol_price_ratio_20 | 1,296,118 | 100% | 同上 | ⬜ 排队 |

**根因**: `factor_onboarding.py:432` 写入 `float(neutral_series.get(code, np.nan))`，当中性化失败时写入 NaN 而非 NULL。

### 2.3 ⚠️ NULL 因子 (北向，从未中性化)

| 因子 | 行数 | 说明 |
|------|------|------|
| nb_acceleration | 800,142 | 北向加速度 |
| nb_change_excess | 798,302 | 北向变化超额 |
| nb_change_rate_20d | 798,302 | 北向20日变化率 |
| nb_concentration_signal | 907,218 | 北向集中度信号 |
| nb_consecutive_increase | 907,218 | 北向连续增持 |
| nb_net_buy_20d_ratio | 771,672 | 北向20日净买入比 |
| nb_net_buy_5d_ratio | 776,888 | 北向5日净买入比 |
| nb_net_buy_ratio | 778,062 | 北向净买入比 |
| nb_rank_change_20d | 798,302 | 北向排名变化 |
| nb_ratio_change_20d | 798,302 | 北向比例变化20d |
| nb_trend_20d | 798,486 | 北向趋势20d |

**说明**: 这些因子已有 raw_value，但未运行中性化。部分北向因子(nb_contrarian等4个)已有 neutral_value。

---

## 3. 中性化规则表

### 3.1 规则矩阵

| 因子类型 | 代表因子 | 需要中性化? | 方法 | 理由 |
|----------|---------|------------|------|------|
| **量价截面** | turnover_mean_20, volatility_20, amihud_20 | ✅ 需要 | WLS(行业SW1 + ln市值) | 不同行业/市值的换手率、波动率天然不同，不中性化等于选行业+选大小盘 |
| **估值因子** | bp_ratio, ep_ratio, dv_ttm, pe_ttm | ✅ 需要 | WLS(行业SW1 + ln市值) | PE/PB跨行业差异巨大(银行PE=5 vs 科技PE=50)，不中性化本质是选银行/公用事业 |
| **动量/反转** | reversal_20, momentum_20 | ✅ 需要 | WLS(行业SW1 + ln市值) | 大盘股动量更强(机构持仓惯性)，小盘反转更强(散户过度反应) |
| **Alpha158截面** | RSQR_20, QTLU_20, CORD_20 | ✅ 需要 | WLS(行业SW1 + ln市值) | 来自价格序列的统计量，有行业/市值偏差 |
| **Alpha158 rank类** | a158_rank5 | ⚠️ 待定 | 需验证 | 已做截面rank，但rank与行业/市值仍可能相关。需跑中性化前后IC对比 |
| **技术指标** | RSI, KDJ, MACD | ⚠️ 待定 | 需验证 | 价格衍生指标，理论上行业中性但可能有市值偏差(大盘股RSI更稳定)。需实证验证 |
| **资金流向因子** | money_flow_strength, large_order_ratio | ✅ 需要 | WLS(行业SW1 + ln市值) | 大盘股资金流入金额天然更大，即使用比率指标仍有市值偏差(大盘股机构参与率高) |
| **北向因子** | nb_increase_ratio_20d, nb_contrarian | ✅ 需要 | WLS(行业SW1 + ln市值) | 北向资金有明显行业偏好(消费/金融)和市值偏好(大盘蓝筹)。已有4个因子完成中性化验证有效 |
| **事件驱动** | earnings_surprise (SUE) | ⚠️ 谨慎 | 仅行业中性化(不含市值) | 盈利水平与行业强相关(银行ROE>科技)，需行业中性化。但市值中性化可能剥离"大公司盈利更稳定"的有效信号 |
| **季频财务** | ROE, ROA (未入库) | ✅ 需要 | 先forward-fill到日频，再WLS | 季频数据需先用最近一期值填充到日频，再做截面中性化。注意PIT对齐(用actual_ann_date) |

### 3.2 中性化方法统一

**唯一允许的方法** (铁律4, 不可变):

```
去极值(MAD 5σ) → 填充(行业中位数) → WLS中性化(行业SW1 + ln市值) → z-score clip ±3
```

**执行工具**: `backend/engines/fast_neutralize.py` → `fast_neutralize_batch()`

### 3.3 不需要中性化的场景

- **ln_market_cap**: 本身就是中性化的自变量，中性化会消除自身
- **因子用于ML特征而非独立选股**: LightGBM等模型内部处理非线性关系，raw_value即可
- **因子已经是行业内rank**: 如某些自定义因子已在计算时做了行业内排名

---

## 4. 标准化入库流程

### 4.1 新因子入库 Pipeline

```
                      ┌──────────────┐
                      │ 1. 经济假设   │ 铁律13: 必须有市场逻辑
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 2. 数据拉取   │ DataPipeline / 独立计算脚本
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 3. 写入DB     │ factor_values.raw_value (禁止写NaN!)
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 4. 中性化     │ fast_neutralize_batch → neutral_value
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 5. 健康检查   │ factor_health_check.py → ✅/❌
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 6. IC评估     │ ic_calculator → factor_ic_history
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 7. 因子画像   │ factor_profiler → 5维评估
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 8. 注册       │ FACTOR_TEST_REGISTRY.md
                      └──────┬───────┘
                             ▼
                      ┌──────────────┐
                      │ 9. 缓存重建   │ build_backtest_cache.py (如需)
                      └──────────────┘
```

### 4.2 每步详细规范

#### Step 3: 写入DB (raw_value)
- **禁止写 float NaN**: `if np.isnan(value): value = None` (转为 SQL NULL)
- **使用 DataPipeline**: `DataPipeline.ingest(df, FACTOR_VALUES)` (铁律17)
- **批量写入**: `execute_values` 每批 5000 行
- **幂等性**: 使用 `ON CONFLICT (code, trade_date, factor_name) DO UPDATE`

#### Step 4: 中性化
- **工具**: `fast_neutralize_batch(factor_names, update_db=True, write_parquet=False)`
- **写入目标**: `factor_values.neutral_value` (仅DB，Parquet在Step 9统一重建)
- **失败处理**: 中性化失败的行写 NULL (不写 NaN)
- **日志**: 记录每年处理行数、耗时、失败数

#### Step 5: 健康检查
- **脚本**: `scripts/factor_health_check.py <factor_name>`
- **PASS 条件**:
  - neutral_value NaN 占比 < 1%
  - neutral_value 值域在 [-10, 10] 内
  - 数据覆盖率 > 90% (股票数 × 交易日)
  - 最新数据日期 = 预期日期
- **FAIL = 不进入后续步骤**

#### Step 9: 缓存重建
- **触发条件**: 中性化完成后 + 健康检查通过
- **命令**: `python scripts/build_backtest_cache.py --start <year>`
- **TODO**: 添加自动触发机制 (中性化完成后自动调用)

### 4.3 批量入库 (Alpha158 等)
1. 一次性计算所有因子 → DataFrame
2. 批量写入 factor_values (按因子分组，每组 execute_values)
3. 批量中性化: `fast_neutralize_batch(all_factor_names)`
4. 批量健康检查: `factor_health_check.py` (不指定因子 = 全量)
5. 批量 IC: 循环每个因子跑 ic_calculator

### 4.4 增量更新 (每日新数据)
1. 调度链路 16:30 计算今日因子值
2. 写入 factor_values.raw_value
3. **不需要每日中性化** — 中性化是离线批量操作
4. 回测使用 `COALESCE(neutral_value, raw_value)`，新数据自动用 raw_value
5. 定期批量重新中性化 (周末/月末)

### 4.5 出错回滚
- **raw_value 写入失败**: 事务回滚，重试
- **中性化失败**: neutral_value 保持为 NULL (COALESCE 自动回退到 raw_value)
- **部分年份失败** (如 OOM): 重跑该因子即可 (幂等性，会覆盖已有值)
- **Parquet 不一致**: 删除 cache 目录重建

---

## 5. 已知陷阱 (Known Pitfalls)

| 陷阱 | 影响 | 解决方案 |
|------|------|---------|
| float NaN vs SQL NULL | COALESCE 不回退 NaN | **铁律**: 禁止写 float NaN，统一用 NULL |
| Parquet 缓存过期 | 回测用旧数据 | 中性化后必须重建缓存 |
| 中性化 OOM | 部分年份写入失败 | 串行处理，不与其他重 DB 操作并发 (铁律9) |
| Parquet 仅含 CORE5 | 新因子不在缓存中 | 扩展 CORE_FACTORS 或研究脚本直接读 DB |
| 季频因子 PIT | 前瞻偏差 | 使用 actual_ann_date，非 report_date |
| 北向因子部分未中性化 | IC/回测可能有偏差 | 全量中性化后验证 |

---

## 6. 自动验证机制

### 6.1 验证脚本
- **路径**: `scripts/factor_health_check.py`
- **用法**:
  ```bash
  # 全量检查 (2024年)
  python scripts/factor_health_check.py

  # 指定因子
  python scripts/factor_health_check.py RSQR_20 dv_ttm

  # 含Parquet一致性检查
  python scripts/factor_health_check.py --check-parquet

  # 全量详细
  python scripts/factor_health_check.py --year 2024 -v
  ```

### 6.2 集成点 (TODO)
- [ ] 中性化完成后自动调用 health_check
- [ ] health_check 失败时阻止 Parquet 重建
- [ ] 定期健康检查 (每周 Celery Beat)
- [ ] 新因子入库时自动触发完整 Pipeline

---

## 7. 存储空间预估

| 当前 | 规模 |
|------|------|
| factor_values | ~590M 行, ~119GB (70因子 × 12年) |
| 单因子/年 | ~1.3M 行, ~170MB |

**300+因子预估**:
- 300因子 × 12年 × 1.3M行/因子年 = **46.8亿行**
- 估计存储: 300/70 × 119GB ≈ **510GB**
- **建议**: 分区策略已有(TimescaleDB)，暂不需分表。但需监控磁盘空间。

---

## 8. 因子命名规范

### 8.1 现有命名模式

| 模式 | 示例 | 数量 |
|------|------|------|
| `{metric}_{window}` | turnover_mean_20, volatility_20 | ~30 |
| `{metric}` | bp_ratio, dv_ttm, ep_ratio | ~10 |
| `nb_{metric}` | nb_increase_ratio_20d, nb_contrarian | ~15 |
| `a158_{name}` | a158_cord30, a158_rank5 | ~8 |
| `UPPER_{window}` | RSQR_20, QTLU_20, CORD_20 | ~7 |
| 其他 | mf_divergence, kbar_kmid | ~5 |

### 8.2 建议规范 (Phase 3起执行)

```
{category}_{name}[_{window}]

category: qp (量价) / val (估值) / mom (动量) / fund (基本面) / 
          nb (北向) / mf (资金流) / tech (技术指标) / evt (事件) /
          a158 (Alpha158)
name:     描述性名称 (snake_case)
window:   时间窗口 (可选, 如 20d, 60d, 1q)
```

**注意**: 现有因子不改名(向后兼容)，新因子遵循此规范。
