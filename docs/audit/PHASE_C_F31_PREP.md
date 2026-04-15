# Phase C F31 Prep — factor_engine.py 拆分准备

> **状态**: prep 文档完成, 待下一个 fresh session 执行 C1/C2/C3
> **建立时间**: 2026-04-16 凌晨 (Phase B M3 commit `33df369` 之后)
> **目的**: 让下一个 fresh session 直接开工, 无需重新扫盘 factor_engine.py
> **接管 bootstrap**: 读本文档 + `docs/audit/AUDIT_MASTER_INDEX.md` 即可
> **当前 git HEAD**: `33df369 audit(b-m3): F45 full closure`

---

## 背景与目标

`backend/engines/factor_engine.py` (**2049 行, 48 个 top-level 函数**) 是 S1 审计 F31 + F43 的主角, 违反 **铁律 31** (Engine 层纯计算). 具体违规点:

- Engine 层有 10 处 DB IO (`cur.execute` / `pd.read_sql` / `INSERT INTO` / `conn.commit`)
- 1 处 `INSERT INTO factor_values` 是 F86 已知债务的最后一条 (`check_insert_bypass.py` baseline 中 3 条已知债务之一)
- 25 个生产/测试/研究文件 import 本模块, 改名必须全量同步

**目标**: 把 `factor_engine.py` 拆分为:
1. **纯计算 Engine** (`backend/engines/factor_engine/`) — 铁律 31 合规, 可单测, 无 IO
2. **Data Repository Service** (`backend/app/services/factor_repository.py`) — 所有 DB 读取集中到一处
3. **编排 Service** (`backend/app/services/factor_compute_service.py`) — 调用 repository + engine + preprocess, 通过 DataPipeline 入库

**不做** 的事:
- 因子算法本身改动 (所有 calc_* 内部逻辑 100% 保留)
- Public API 签名大改 (`compute_daily_factors` / `save_daily_factors` 保持可用, 走兼容层)
- ML / 信号 / 回测逻辑

---

## 当前文件结构 (S4 scout 实测, 2026-04-16)

### 1. 纯计算函数 (Engine 合规) — lines 24-438, ~30 个

以下函数输入 `pd.Series/DataFrame`, 输出 `pd.Series`, **无 IO**:

| 行号 | 函数名 | 类型 |
|---|---|---|
| 24 | calc_momentum | 量价 |
| 37 | calc_reversal | 量价 |
| 42 | calc_volatility | 量价 |
| 48 | calc_volume_std | 量价 |
| 53 | calc_turnover_mean | 换手 |
| 58 | calc_turnover_std | 换手 |
| 63 | calc_turnover_stability | 换手 |
| 85 | calc_amihud | 流动性 (DEPRECATED CORE, 仍保留) |
| 97 | calc_ln_mcap | 规模 |
| 102 | calc_bp_ratio | 价值 |
| 107 | calc_ep_ratio | 价值 |
| 112 | calc_pv_corr | 价量 |
| 117 | calc_hl_range | 波动 |
| 125 | calc_price_level | 价位 |
| 130 | calc_relative_volume | 量能 |
| 136 | calc_turnover_surge_ratio | 换手突增 |
| 149 | calc_kbar_kmid | K线形态 (Alpha158) |
| 164 | calc_kbar_ksft | K线形态 (Alpha158) |
| 183 | calc_kbar_kup | K线形态 (Alpha158) |
| 203 | calc_mf_divergence | 资金流 (INVALIDATED 但保留) |
| 222 | calc_large_order_ratio | 资金流 |
| 245 | calc_money_flow_strength | 资金流 |
| 265 | calc_maxret | 极值 (Alpha158) |
| 281 | calc_chmom | 动量 (Alpha158) |
| 301 | calc_up_days_ratio | 胜率 (Alpha158) |
| 320 | calc_vwap_bias | VWAP |
| 347 | calc_rsrs_raw | RSRS |
| 374 | calc_beta_market | 市场 beta |
| 394 | calc_stoch_rsv | 随机指标 |
| 414 | calc_gain_loss_ratio | 盈亏比 |

### 2. Preprocess 流水线 (Engine 合规) — lines 1056-1249

| 行号 | 函数名 | 用途 |
|---|---|---|
| 1056 | preprocess_mad | 去极值 |
| 1077 | preprocess_fill | 填充 |
| 1100 | preprocess_neutralize | WLS 行业+市值中性化 |
| 1160 | preprocess_zscore | 标准化 |
| 1172 | preprocess_pipeline | 组合 1056+1077+1100+1160 |
| 1217 | calc_ic | IC 计算 (已被 ic_calculator 统一, 此处是 legacy) |

### 3. Alpha158 工具 + 复合因子 — lines 542-926

| 行号 | 函数名 | IO 状态 | 备注 |
|---|---|---|---|
| 542 | _alpha158_rolling | 纯 | helper |
| 615 | calc_pead_q1 | **IO** (cur.execute line 639 读 earnings_announcements) | ⚠️ PEAD 因子, DB 读取是内置的 |
| 778 | calc_high_vol_price_ratio_wide | 纯 | 宽表版本 |
| 830 | calc_alpha158_simple_four | 纯 | IMAX/IMIN/CORD/QTLU 合成 |
| 867 | calc_alpha158_rsqr_resi | 纯 | RSQR/RESI 合成 |

### 4. Data Loaders (违反铁律 31) — lines 926-1803

| 行号 | 函数名 | IO | 备注 |
|---|---|---|---|
| 926 | load_fundamental_pit_data | pd.read_sql ×多 | 基本面 PIT 数据 |
| 1250 | load_daily_data | pd.read_sql (1312) | 单日 K 线+basic+moneyflow |
| 1319 | load_forward_returns | pd.read_sql (1342/1386) | T+1 到 T+horizon 前瞻收益 (应统一走 ic_calculator) |
| 1400 | **save_daily_factors** | DataPipeline.ingest ✅ | **已合规** (走 FACTOR_VALUES contract) |
| 1459 | compute_daily_factors | orchestrator | 调用 load_daily_data + calc_* + preprocess_pipeline |
| 1554 | load_bulk_data | pd.read_sql (1620) | 区间 K 线+basic |
| 1633 | load_bulk_moneyflow | pd.read_sql (1680) | 区间 moneyflow |
| 1688 | load_index_returns | pd.read_sql (1731) | 区间 CSI300 收益 |
| 1743 | load_bulk_data_with_extras | orchestrator | 组合 1554+1633+1688 |

### 5. 批量编排器 (违反铁律 17 + 31) — lines 1803-2049

| 行号 | 函数名 | 违规 |
|---|---|---|
| 1803 | **compute_batch_factors** | DB read (多处) + `INSERT INTO factor_values` (line 2016) + `conn.commit()` (line 2026) — **铁律 17 最后一条 known_debt** |

---

## DB 访问点清单 (10 个)

| # | 行号 | 函数 | 类型 | 目标表 |
|---|---|---|---|---|
| 1 | 639 | calc_pead_q1 | cur.execute | earnings_announcements |
| 2 | 1312 | load_daily_data | pd.read_sql | klines_daily + daily_basic |
| 3 | 1342 | load_forward_returns | pd.read_sql | klines_daily (date range) |
| 4 | 1386 | load_forward_returns | pd.read_sql | klines_daily + index_daily |
| 5 | 1620 | load_bulk_data | pd.read_sql | klines_daily + daily_basic |
| 6 | 1680 | load_bulk_moneyflow | pd.read_sql | moneyflow_daily |
| 7 | 1731 | load_index_returns | pd.read_sql | index_daily |
| 8 | 2016 | compute_batch_factors | **INSERT INTO** | factor_values |
| 9 | 2026 | compute_batch_factors | conn.commit | — |
| 10 | 926-1055 | load_fundamental_pit_data | pd.read_sql (多处) | fundamental_pit* |

**注意**: `save_daily_factors` (line 1400) 已经走 DataPipeline 合规, 只有 `compute_batch_factors` 没走. Phase C milestone C3 的目标就是把 `compute_batch_factors` 也改走 DataPipeline, 彻底关闭 F86 baseline 里的最后一条 known_debt.

---

## Import 调用方 (过滤 worktree/archive 后)

### 生产路径 (必须不能破) — 2 个

| 文件 | 用到的符号 | 风险等级 |
|---|---|---|
| `scripts/run_paper_trading.py` | compute_daily_factors, save_daily_factors | 🔴 P0 |
| `backend/app/services/factor_onboarding.py` | (S2b 重构后, 间接使用 compute_daily_factors/save_daily_factors 或 preprocess) | 🔴 P0 |

### 测试路径 (必须保持全绿) — 8 个

| 文件 | 用到的符号 |
|---|---|
| `backend/tests/test_a4_a6.py` | calc_amihud, calc_vwap_bias, calc_money_flow_strength |
| `backend/tests/test_factor_determinism.py` | compute_daily_factors, preprocess_pipeline |
| `backend/tests/test_factor_engine_unit.py` | 多 import (几乎全量) |
| `backend/tests/test_pead_factor.py` | calc_pead_q1, PEAD_FACTOR_DIRECTION |
| `backend/tests/test_turnover_stability.py` | (turnover 相关) |
| `backend/tests/test_vwap_rsrs.py` | calc_rsrs_raw, calc_vwap_bias |
| `backend/tests/test_vwap_rsrs_pipeline.py` | (多 import) |
| `backend/tests/test_wls_neutralize_and_clip.py` | (preprocess 相关) |

### 研究路径 (可以更新, 非生产) — 4 个

| 文件 | 用到的符号 |
|---|---|
| `scripts/compute_factor_phase21.py` | PHASE21_FACTOR_DIRECTION |
| `scripts/research/earnings_factor_calc.py` | preprocess_neutralize |
| `scripts/research/phase3e_fast_eval.py` | preprocess_pipeline |
| `scripts/research/phase3e_noise_robustness.py` | preprocess_pipeline |

### Archive 路径 (可以忽略, 死代码) — 11 个

`scripts/archive/*` — S1 F2 确认 126 个归档脚本零生产引用, 不修改也不影响生产. Phase C 允许这些 import 失败后再在第二阶段清理, 或者保留兼容层.

**Worktrees 路径** (`.claude/worktrees/*`): 忽略, 是 git worktree 缓存.

---

## 拆分方案 (建议目录结构)

```
backend/engines/factor_engine/              # 新包
├── __init__.py                             # 兼容层 re-export 所有旧 API
├── _constants.py                           # FACTOR_DIRECTION, LGBM_V2_BASELINE_FACTORS, PEAD_FACTOR_DIRECTION, PHASE21_FACTOR_DIRECTION
├── calculators.py                          # 30 个 calc_* 纯函数 (lines 24-438)
├── alpha158.py                             # _alpha158_rolling, calc_high_vol_price_ratio_wide, calc_alpha158_simple_four, calc_alpha158_rsqr_resi
├── pead.py                                 # calc_pead_q1 的纯计算部分 (DB 读取拆到 repository)
└── preprocess.py                           # preprocess_mad/fill/neutralize/zscore/pipeline + calc_ic (legacy)

backend/app/services/factor_repository.py   # 新文件, DB IO 全集中
# 包含:
#   load_daily_data(conn, trade_date, ...) -> pd.DataFrame
#   load_forward_returns(conn, trade_date, horizon, ...) -> pd.DataFrame
#   load_bulk_data(conn, start, end, ...) -> pd.DataFrame
#   load_bulk_moneyflow(conn, start, end) -> pd.DataFrame
#   load_index_returns(conn, start, end, index_code) -> pd.DataFrame
#   load_bulk_data_with_extras(conn, start, end) -> dict[str, pd.DataFrame]
#   load_fundamental_pit_data(conn, trade_date) -> dict[str, pd.Series]
#   load_pead_announcements(conn, trade_date, lookback) -> pd.DataFrame  # calc_pead_q1 用

backend/app/services/factor_compute_service.py  # 新文件, 编排层
# 包含:
#   compute_daily_factors(trade_date, conn, factor_set="full") -> pd.DataFrame
#     内部调用 factor_repository.load_daily_data + engines/factor_engine/calculators + preprocess
#   compute_batch_factors(start, end, conn, factor_set, write=True) -> dict
#     内部调用 factor_repository.load_bulk_* + calculators + preprocess
#     write=True 时走 DataPipeline.ingest(FACTOR_VALUES)  ← 关闭 F86 最后一条 known_debt

backend/engines/factor_engine.py             # 兼容层 shim (暂时保留), 从新位置 re-export
# from engines.factor_engine.calculators import *
# from engines.factor_engine.preprocess import *
# from engines.factor_engine._constants import *
# from app.services.factor_repository import load_daily_data, load_forward_returns, ...
# from app.services.factor_compute_service import compute_daily_factors, compute_batch_factors
# save_daily_factors: 保留现有位置或搬到 factor_compute_service, 任一都可 (已合规)
#
# 一轮 import 更新 + 全绿验证后, 此 shim 可删除 (Phase C+1)
```

**关键原则**:
1. **Engine 包只做 move**, 代码内容一行不改 (除 import 路径)
2. **Repository 只做提取**, SQL 字符串 100% 保留原样
3. **Compute service 是新文件**, 但函数体搬自 compute_daily_factors/compute_batch_factors 原实现
4. **Shim 层保证向后兼容**, 所有 25 个 import 调用方不需要立刻改

---

## 金标快照策略 (铁律 15 + 回归保护)

拆分前冻结金标, 拆分后每步验证 `max_diff=0`:

### 冻结范围 (pre-split baseline)

```python
# scripts/audit/phase_c_freeze_baseline.py  # 新建, 一次性跑
# 冻结: 8 因子 × 12 年 × 全 A 股 = ~80M 行
FREEZE_FACTORS = [
    # CORE 4 (当前 PT)
    "turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm",
    # 非 CORE PASS 4 (广覆盖)
    "amihud_20", "reversal_20", "maxret_20", "ln_mcap",
]
DATE_RANGE = ("2014-01-01", "2026-04-14")

# 对每个因子: load 全量 factor_values → 写 parquet
# cache/phase_c_baseline/factor_values_{factor}_frozen.parquet
```

### 验证点 (每个 milestone 执行)

```python
# scripts/audit/phase_c_verify_split.py  # 新建
# 1. 重新 compute_daily_factors 或 compute_batch_factors 算 8 因子 × 同区间
# 2. 加载 cache/phase_c_baseline/*.parquet
# 3. 对齐 (code, trade_date, factor_name) 后 max(abs(raw_diff)) + max(abs(neutral_diff))
# 4. 断言 max_diff == 0 (位级一致)
# 失败立刻回滚到上一个 milestone
```

### 5 把尺子 (每个 milestone 必须全绿)

1. `pytest backend/tests/test_factor_engine_unit.py` — 全绿 (最核心的单测)
2. `pytest backend/tests/test_factor_determinism.py` — 全绿 (确定性测试)
3. `pytest backend/tests/test_factor_onboarding.py` — 28/28 不回归
4. `regression_test.py --years 5` — `max_diff=0.0`, Sharpe 0.6095=0.6095
5. `scripts/audit/phase_c_verify_split.py` — 8 因子 × 12 年 `max_diff=0.0` (新建, 金标快照)
6. **[额外]** `check_insert_bypass.py --baseline` — known_debt 必须 **减少 1 条** (最后一条 `factor_engine.py:2016`), 在 C3 完成后

---

## Milestones (建议 3 步走, 各 1 个独立 session)

### C1 — 纯计算 + preprocess 搬家 (最低风险, 单 session, ~2-3h)

**范围**:
- 创建 `backend/engines/factor_engine/` 目录
- 搬家:
  - `calculators.py` ← 30 个 calc_* 纯函数 (lines 24-438)
  - `alpha158.py` ← _alpha158_rolling, calc_high_vol_price_ratio_wide, calc_alpha158_simple_four, calc_alpha158_rsqr_resi
  - `preprocess.py` ← preprocess_mad/fill/neutralize/zscore/pipeline + calc_ic
  - `_constants.py` ← FACTOR_DIRECTION, LGBM_V2_BASELINE_FACTORS, PEAD_FACTOR_DIRECTION, PHASE21_FACTOR_DIRECTION
- 原 `factor_engine.py` 变为兼容层 shim, re-export 上述符号
- **pead 暂时不动** (calc_pead_q1 内部有 cur.execute, 留到 C2)

**风险**: 🟢 低 — 只是文件搬家, signature 不变, shim 层保证兼容

**验收**:
- 尺子 1/2/3/4 全绿
- 金标验证 (尺子 5) 必须位级一致: **max_diff=0.0** for 8 因子 × 12yr
- `ruff check + ruff format` 新目录全绿
- `check_insert_bypass.py` 未变化 (3 known_debt)

**commit message**: `audit(c-1): factor_engine split milestone 1 - calculators + preprocess extracted to package`

---

### C2 — Data Loaders → factor_repository (中风险, 单 session, ~3-4h)

**范围**:
- 创建 `backend/app/services/factor_repository.py`
- 搬家 (SQL 字符串原样保留):
  - `load_daily_data` (line 1250)
  - `load_forward_returns` (line 1319) — ⚠️ 与 `ic_calculator.compute_forward_excess_returns` 存在功能重叠, 本 milestone 仅搬家, 不合并 (留到未来的 IC 路径统一 session)
  - `load_bulk_data` (1554), `load_bulk_moneyflow` (1633), `load_index_returns` (1688), `load_bulk_data_with_extras` (1743)
  - `load_fundamental_pit_data` (926) — 涉及多张 PIT 表, 搬家时逐个 SQL 原样保留
  - **calc_pead_q1 的 DB 读取部分** (line 639 `cur.execute`) 拆出为 `load_pead_announcements(conn, trade_date, lookback)`
- `calc_pead_q1` 变成纯函数 `calc_pead_q1(ann_df: pd.DataFrame) -> pd.Series`, 搬到 `engines/factor_engine/pead.py`
- 原 `factor_engine.py` 兼容层 shim 更新: 从 `factor_repository` re-export loader 函数

**风险**: 🟡 中 — signature 需要改 (conn 参数位置可能移动), 调用方 import 路径改变

**验收**:
- 尺子 1-5 全绿
- 金标验证 `max_diff=0.0` 8 因子 × 12yr (特别关注 PEAD 因子)
- `test_pead_factor.py` 全绿 (PEAD 拆分是本 milestone 最大风险点)

**commit message**: `audit(c-2): factor_engine split milestone 2 - DB loaders extracted to factor_repository + PEAD purified`

---

### C3 — 编排层 + compute_batch_factors 走 DataPipeline (高风险, 单 session, ~2-3h)

**范围**:
- 创建 `backend/app/services/factor_compute_service.py`
- 搬家:
  - `compute_daily_factors` (line 1459) — orchestrator, 内部调用 factor_repository + engine + preprocess
  - `compute_batch_factors` (line 1803) — orchestrator + **INSERT INTO 改走 DataPipeline.ingest(FACTOR_VALUES)**
- `save_daily_factors` 留在原位或搬到 compute_service (已合规, 无技术债务)
- **关键改动**: `compute_batch_factors` 的 `INSERT INTO factor_values` (line 2016) + `conn.commit()` (line 2026) 换为:
  ```python
  from app.data_fetcher.contracts import FACTOR_VALUES
  from app.data_fetcher.pipeline import DataPipeline
  pipeline = DataPipeline(conn)
  result = pipeline.ingest(pd.DataFrame(day_rows, columns=[...]), FACTOR_VALUES)
  ```
- 兼容层 shim 最终更新

**风险**: 🔴 高 — compute_batch_factors 是批量入库关键路径, DataPipeline 改造有数据完整性风险

**验收**:
- 尺子 1-5 全绿
- 金标验证 `max_diff=0.0` 8 因子 × 12yr
- **尺子 6 (本 milestone 独有)**: `check_insert_bypass.py --baseline` 扫描结果减少 1 条, 剩余 **2 条 known_debt** (fetch_base_data ×2). `scripts/audit/insert_bypass_baseline.json` 更新.
- 跑一次 `compute_batch_factors --dry-run` (read-only) 对 2024 全年, 再跑 `--commit` 小范围验证入库行数与旧代码一致

**commit message**: `audit(c-3): factor_engine split milestone 3 - compute_service + F86 factor_engine known_debt closed`

---

### C4 (可选) — 删除兼容层 shim + import 路径全面更新

**范围**:
- 更新所有 25 个 import 调用方, 使用新模块路径 (e.g. `from engines.factor_engine.calculators import calc_momentum`)
- 删除 `backend/engines/factor_engine.py` shim 文件
- archive/* 调用方: 失败就失败, 反正是死代码 (S1 F2 确认)

**风险**: 🟡 中 — 只是机械重命名, 但量大

**不急**: Shim 层可以长期保留, C4 可在 Phase D 或更晚做

---

## 待定决策 (Phase C 开始前确认)

### D1: calc_pead_q1 DB 依赖处理

**方案 A** (推荐, C2 做): 拆成 `load_pead_announcements(conn, ...)` + `calc_pead_q1(ann_df)` 两个函数, DB 归 repository, 计算归 engine.

**方案 B**: 保持 calc_pead_q1 依赖 conn, 标记为"Engine 合规例外", 铁律 31 加脚注.

**建议 A**, 避免铁律 31 破口.

### D2: load_forward_returns 与 ic_calculator 的关系

- `engines/factor_engine.py:1319 load_forward_returns` 计算 T+1 前瞻收益 (raw)
- `engines/ic_calculator.py:compute_forward_excess_returns` 计算 T+1 前瞻**超额**收益 (CSI300 相对)
- 功能重叠但不等价. S2b 根治 F60 时只改了 `factor_onboarding.py` 的调用方, `factor_engine.load_forward_returns` 仍在.

**方案 A** (推荐): Phase C 仅搬家 load_forward_returns 到 repository, **不合并** (合并是独立议题).

**方案 B**: Phase C 同时把 load_forward_returns 标 DEPRECATED, 强制所有调用方改用 ic_calculator.

**建议 A**, 避免 Phase C 范围膨胀, 合并留给未来的 "IC 路径统一" 独立 session.

### D3: archive/* 兼容性

S1 F2 确认 126 个 archive 脚本零生产引用. Phase C 是否更新 archive/*.py 的 import?

**建议**: 不更新. Shim 层保证 archive 不立刻坏. 未来清理 archive 是独立任务.

### D4: 金标快照 ground truth 的时机

- 方案 A: Phase C 执行前 (M3 commit 后立刻冻结) → 冻结 11.71M × 8 因子 = 93.7M 行 parquet, ~2-3GB
- 方案 B: 每个 milestone 之前临时 recompute (更慢但更省存储)

**建议 A**, 存储成本可控 (D:\ 还有 150GB+ 空余). 冻结一次管整个 Phase C.

---

## 工作量预估

| Milestone | 预估时间 | 复杂度 | 回归风险 |
|---|---|---|---|
| C1 (pure calc + preprocess 搬家) | 2-3h | 低 | 🟢 低 |
| C2 (DB loaders + PEAD 纯化) | 3-4h | 中 | 🟡 中 |
| C3 (compute_service + F86 final closure) | 2-3h | 高 | 🔴 高 |
| 金标快照冻结 (C0, Phase C 开始前) | ~1h (跑 build_12yr_baseline 类似耗时) | 极低 | — |
| **合计** | **~10-11h (约 3 个 session)** | — | — |

**建议节奏**:
- Session 1 (C0 + C1): 冻结金标 + 搬家纯计算
- Session 2 (C2): DB loaders + PEAD 纯化
- Session 3 (C3 + 收尾): compute_service + F86 final closure + AUDIT_MASTER_INDEX 更新

每个 session 独立 commit, 独立 5 把尺子验收, 失败可单独回滚. 不跨 session 改任何有风险的代码.

---

## 已知风险与 mitigation

1. **factor_values 位级一致性**: 8 因子 × 12yr × 全 A 股 = ~80M 行 parquet 金标, 任何一行 raw_value 或 neutral_value 差异都能被 `max_diff=0` 捕获. Mitigation: C0 一次冻结, 每个 milestone 对比, 差异立刻回滚.

2. **PEAD 因子 DB 拆分风险**: calc_pead_q1 内部 `cur.execute` 有自定义参数 (trade_date + lookback), 拆成 `load_pead_announcements` 时 SQL 字符串必须 100% 保留 (包括 ORDER BY / LIMIT 等细节). Mitigation: 同一 milestone (C2) 内完成, test_pead_factor.py 作为回归验证.

3. **Import 路径大量修改**: 25 个 import 调用方, 机械替换风险低但量大. Mitigation: 兼容层 shim 保证旧路径仍然工作, C1/C2/C3 只验证"新路径可用 + 旧路径不坏", C4 才做全量路径迁移.

4. **IC 路径未统一**: load_forward_returns 与 ic_calculator.compute_forward_excess_returns 功能重叠. Mitigation: Phase C 明确不合并, 只搬家, 合并留给未来独立 session.

5. **compute_batch_factors 改走 DataPipeline 的数据完整性**: DataPipeline 会做 `fillna(None)` / 列对齐 / FK 校验, 可能会把某些旧代码认为"可入库"的行过滤掉. Mitigation: C3 小范围对比 (2024 全年 compute_batch_factors 旧路径 vs 新路径), 对比入库行数 + sample rows.

---

## 接管 bootstrap (下一个 session 用这段启动)

```
继续 QuantMind V2 审计 Phase C. 读 docs/audit/PHASE_C_F31_PREP.md +
docs/audit/AUDIT_MASTER_INDEX.md, 按 PHASE_C_F31_PREP §Milestones 执行 C0+C1.

当前 git HEAD=33df369 audit(b-m3). 前置条件:
- RTK 已装 (C:\Users\hd\rtk\rtk.exe) + ripgrep 已装 (winget)
- Phase B M1/M2/M3 全关闭 (F86/F75/F45)
- pt_live.yaml CORE3+dv_ttm WF OOS Sharpe=0.8659 不变
- regression_test 5yr baseline: Sharpe=0.6095, max_diff=0 (铁律 15)

C0 任务: 写 scripts/audit/phase_c_freeze_baseline.py, 冻结 8 因子 × 12yr 金标到
cache/phase_c_baseline/*.parquet. 跑一次确认存储占用, 记录入 AUDIT_MASTER_INDEX.

C1 任务: 创建 backend/engines/factor_engine/ 目录, 搬家纯计算 + preprocess, 原
factor_engine.py 改兼容层 shim. 验证 5 把尺子 + 金标 max_diff=0. commit.

不要读 S2b / config_guard / ic_calculator 路径 — 已闭环. 只读 factor_engine.py 主文件
和新建的模块.
```

---

## 附录: 相关铁律 (Phase C 必须遵守)

- **铁律 31** (Engine 纯计算) — Phase C 核心目标
- **铁律 17** (DataPipeline 入库) — C3 关闭最后一条 known_debt
- **铁律 15** (回测可复现) — 金标 max_diff=0 是验收门槛
- **铁律 2** (验代码不信文档) — 每个 milestone 前重新 grep 实际代码, 不信本 prep 文档过时的行号
- **铁律 3** (范围外改动先报告) — 遇到 Alpha158 算法 bug 等 Engine 外部问题必须停手问用户
- **铁律 22(a)** (代码改动 → 文档同步) — C1/C2/C3 必须同步更新 SYSTEM_STATUS.md factor_engine 描述 + CLAUDE.md 目录结构段
- **铁律 25/26/27** (不靠记忆靠代码 + 验证不可跳过 + 结论明确) — 每个 milestone 5 把尺子独立验证

---

**本 prep 文档由 `33df369` 之后的 audit session 编写**. 如果 Phase C 开始前 factor_engine.py 被其他 session 大改, 本文档里的行号清单需要立刻重新 scout, 不能按本文档的行号直接动刀 (铁律 2 + 25).
