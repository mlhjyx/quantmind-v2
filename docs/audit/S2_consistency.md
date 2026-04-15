# S2 审计报告 — 一致性专项（PT ↔ 回测 ↔ 研究 ↔ 前端）

> **范围**: 动态代码路径审计 + 铁律 16 / 17 / 18 / 19 / 22 / 30 深度验证 + 前后端契约初扫
> **方法**: grep + Read + DB 查询 + Python 语法校验 + 代码路径追踪
> **时间**: 2026-04-15 夜 (继 S1 cleanup pass 之后)
> **覆盖铁律**: 16 / 17 / 18 / 19 / 22 / 30（已验证）；**未覆盖**: 1-10, 12, 15, 23, 24（留给 S3/S4/S5）

---

## 📋 执行摘要

| 分级 | S2 新增 | S1 累计 | 总计 |
|---|---|---|---|
| 🔴 P0 | **3** | 6 (F32 已闭) | 8 open |
| 🟠 P1 | **7** | 10 | 16 open |
| 🟡 P2 | **3** | 6 | 8 open |
| ✅ 关闭/修正 | **2** (F17/F64) | 5 | 10 closed |

**S2 新发现**（按严重性降序）:

1. **F53/F60 (P0) 🔴** — **`factor_onboarding._compute_ic_series` + `_compute_forward_returns` 双重违规**
   - 铁律 19 违反: 用 **raw return** 非 CSI300 超额
   - 前瞻偏差: 用 **T 日因子 vs T+h 价格**，缺 T+1 入场延迟
   - 路径活跃: approval_queue → `FactorOnboardingService` → `factor_ic_history`（生产路径）
   - 与 `fast_ic_recompute.py` 合规路径口径不一致，**同一张表写入两种 IC**

2. **F62 (P0) 🔴** — **`config.py:37 PT_SIZE_NEUTRAL_BETA: float = 0.0` 默认关闭**
   - 如果 `.env` 意外缺失 `PT_SIZE_NEUTRAL_BETA=0.50` → PT 静默降级到无 SN
   - 无 SN Sharpe ≈ 0.63 vs SN 0.50 Sharpe ≈ 0.87（**-27% Sharpe**）
   - 配合 S1 F45（config_guard 不检查此字段）构成**隐藏故障**

3. **F58 (P1)** — 调度链路分散两个编排器，无统一表
   - Celery Beat: 仅 2 task（`gp-weekly-mining` 周日 22:00 + `pms-daily-check` 14:30）
   - Windows Task Scheduler: PT 主链全部（16:25 / 16:30 / 09:31 / 15:10 对账）
   - CLAUDE.md 文档声称的调度流程**代码层不可追溯**，必须登陆 Windows 看任务计划程序

**S1 相关的修正与关闭**:
- **F17 关闭** (部分): `factor_engine.py:1400 save_daily_factors()` 实际走 DataPipeline（S1 指控的 `:2001` 是另一个函数的 dead code 路径，只被 archive 脚本调用）。真正活跃违反铁律 17 的是 **`factor_onboarding.py`**（S2 单独追踪）。
- **F64 新发现 ✅ PASS**: 成本模型 `backtest/config.py` / `pt_live.yaml` / `broker.py` 三处对齐。

---

## 🔴 P0 发现（Critical）

### F51 + F53 + F60 — factor_onboarding IC 计算三重违规

**单一根因**: `backend/app/services/factor_onboarding.py` 的 `_compute_forward_returns` + `_compute_ic_series` 自己实现了 IC 计算，不走统一的 `engines/ic_calculator.py`。

#### 违规 A (F53 / 铁律 19): 用 raw return 非超额收益

**位置**: `backend/app/services/factor_onboarding.py:568-598`

**证据**:
```python
def _compute_forward_returns(self, adj_df, trading_dates):
    pivot = adj_df.pivot(index="trade_date", columns="code", values="adj_close")
    pivot = pivot.sort_index()

    result_frames = []
    for h in HORIZONS:
        shifted = pivot.shift(-h)
        fwd_ret = (shifted / pivot) - 1.0        # ← raw return, 未减去 CSI300
        fwd_ret = fwd_ret.stack().reset_index()
        fwd_ret.columns = pd.Index(["trade_date", "code", f"fwd_{h}d"])
        result_frames.append(fwd_ret)
```

**对比合规实现** `backend/engines/ic_calculator.py` 以及 `backend/engines/factor_profiler.py:120-124`:
```python
entry = close_pivot.shift(-1)          # Buy at T+1 close
exit_p = close_pivot.shift(-(1 + h))   # Sell at T+1+h close
csi_entry = csi_close.shift(-1)        # CSI300 同步对齐
csi_exit = csi_close.shift(-(1 + h))
# stock_return - csi_return = excess_return
```

**铁律 19 原文**: *"IC 定义全项目统一... 前瞻收益: T+1 买入到 T+horizon 卖出的**超额收益**(相对 CSI300)"*

#### 违规 B (F60 / 前瞻偏差): 用 T 日因子对 T+h 价格

同上代码 `shifted = pivot.shift(-h)`：
- T 日因子值 vs T+h 价格 (隐含: T 日收盘后买入, T+h 收盘卖出)
- **但 A 股 T+1 制度**，T 日信号最早 T+1 才能入场
- 因此应该: `shifted = pivot.shift(-(1+h))` + entry = `pivot.shift(-1)`
- factor_profiler 实现是正确的, factor_onboarding 不是

**影响**: 因子 IC 被**系统性高估**（多吃了一天的价格动量 / 反转）。尤其 1-day IC 会把"T 日涨跌对后续 1 日的反转"当成因子预测能力。

#### 违规 C (F51 / 铁律 19 标识符): 口径不一致入库

**位置**: `backend/app/services/factor_onboarding.py:208 + 700+`（IC 入库 factor_ic_history）

**影响**: `factor_ic_history` 表此时存在两种不兼容的 IC 数字：

| 写入路径 | IC 定义 | 合规 |
|---|---|---|
| `scripts/fast_ic_recompute.py` → `ic_calculator.compute_ic_series` | T+1 入场超额 | ✅ |
| `backend/app/services/factor_onboarding.py._compute_ic_series` | T 日 raw return | ❌ |

查询 `factor_ic_history` 时**无法区分**这两种 IC（都写入 `ic_20d` 等列）。S1 已确认该表 133,125 行，但每行 IC 的口径需要按 `factor_name` + 写入时间倒推。

#### 调用链（为什么是 P0）

```
POST /api/pipeline/approve  (backend/app/api/pipeline.py:375)
    ↓
app.tasks.onboarding_tasks.process_factor_onboarding (:136)
    ↓
FactorOnboardingService() (:138)
    ↓
svc._compute_forward_returns() → 违规 B (前瞻偏差)
    ↓
svc._compute_ic_series() → 违规 A (raw return)
    ↓
svc._upsert_ic_history() → 写入 factor_ic_history
```

这条路径**在每次新因子通过 approval_queue 上线时触发**。虽然不是 PT 每日链路，但：
1. 每次新因子入库都会污染 `factor_ic_history`
2. `factor_profile` 表的 IC 字段若基于同路径也会被污染
3. **未来任何基于 `factor_ic_history` 的监控告警都会误触发**（因为合规与非合规 IC 数字可能相差 20%+）

#### 建议修复

**短期** (~15 min — 仅告警不改逻辑):
1. 在 `_compute_ic_series` 入口加 `logger.warning("[DEPRECATED] factor_onboarding IC 违反铁律 19, 见 S2 F51")`
2. 标记该代码路径为 DEPRECATED

**中期** (~2 小时 — 真正修复):
1. 删除 `_compute_forward_returns` 和 `_compute_ic_series`
2. 改调用 `ic_calculator.compute_forward_excess_returns` + `ic_calculator.compute_ic_series`
3. async → sync 边界：在 Celery task 里用 `asyncio.to_thread(ic_calculator.compute_ic_series, ...)`
4. 跑 `backend/tests/test_factor_onboarding.py` 确保回归通过
5. 手动跑一次新因子 onboarding 验证 `factor_ic_history` 写入的 IC 与 `fast_ic_recompute` 口径一致

**工作量**: 短期 15 min；中期 2 小时。

**谁负责**: S2 范围内只做短期告警。中期修复转 S2b 或 S3 专项处理（需要跑新因子 onboarding 端到端验证）。

---

### F62 — `PT_SIZE_NEUTRAL_BETA` default = 0.0 静默降级风险

**位置**: `backend/app/config.py:37`

**证据**:
```python
# config.py
PT_TOP_N: int = 20
PT_INDUSTRY_CAP: float = 1.0
PT_SIZE_NEUTRAL_BETA: float = 0.0  # 0.0=关闭, 0.50=Step 6-H验证最优. .env设置覆盖
```

**风险**: 如果某次 `.env` 被部分覆盖或 `.env` 重建时漏写 `PT_SIZE_NEUTRAL_BETA=0.50`，pydantic-settings 会**静默**使用 default `0.0`，PT 降级到无 SN。
- 无 SN: Sharpe ≈ 0.6095–0.6521（S1 基线）
- SN=0.50: Sharpe ≈ 0.8659 (WF OOS CORE3+dv_ttm) — **CORE 配置强依赖 SN**
- 差异: **-25% ~ -33% Sharpe**，MDD 也会恶化

**config_guard 是否拦截**: ❌ **否**（S1 F45）— `assert_baseline_config` 只检查 factor_names。

**类比事故**: S1 F41 的 `V12_CONFIG` 也是"default 值不对，没人检查"类事故。

#### 建议修复

**(a) config.py 改 default 为 `None` + `__post_init__` raise**（严格）:
```python
PT_SIZE_NEUTRAL_BETA: float | None = None

@model_validator(mode="after")
def validate_pt_params(self):
    if self.PT_SIZE_NEUTRAL_BETA is None:
        raise ValueError(
            "PT_SIZE_NEUTRAL_BETA must be set in .env (typical: 0.50). "
            "Step 6-H validated; CORE3+dv_ttm WF OOS Sharpe=0.8659 depends on it."
        )
    if self.PT_SIZE_NEUTRAL_BETA < 0 or self.PT_SIZE_NEUTRAL_BETA > 1:
        raise ValueError("PT_SIZE_NEUTRAL_BETA must be in [0, 1]")
    return self
```

**(b) 保留 default，启动时打 WARNING**（宽松）:
```python
def validate_pt_config_at_startup():
    if settings.PT_SIZE_NEUTRAL_BETA == 0.0:
        logger.warning(
            "⚠️  PT_SIZE_NEUTRAL_BETA=0.0 (SN disabled). "
            "Current PT baseline requires 0.50 (S1 F62). "
            "Check backend/.env."
        )
```

**推荐 (a)**（严格）— 铁律 26 "验证不可跳过"精神。

**工作量**: ~20 min + 测试所有 config 加载路径。

---

### F63 — 前端 API 层覆盖缺口（部分 P0 风险）

**位置**: `frontend/src/api/` vs `backend/app/api/`

**差异**:
```
前端 12 api files: agent, backtest, client, dashboard, execution, factors,
                   mining, pipeline, realtime, strategies, system, QueryProvider
后端 21 routes:   approval, backtest, dashboard, execution, execution_ops,
                   factors, health, market, mining, notifications, paper_trading,
                   params, pipeline, pms, portfolio, realtime, remote_status,
                   report, risk, strategies, system
```

**前端无对应 api 文件的 backend 路由**（12 个）:
- `approval` / `execution_ops` / `health` / `market` / `notifications` / `paper_trading` / `params` / `pms` / `portfolio` / `remote_status` / `report` / `risk`

**含义**（需要 S5 深入）:
1. 这些 UI 页面根本不存在（未实现）
2. 或者 UI 存在但**直接 `fetch('/api/pms/...')`**，绕过 api 层（违反 LL-035 响应格式转换）
3. 或者仅用于 Celery/外部监控（合理）

**P0 风险点**: `/api/pms/*` 端点在 S1 session 2026-04-15b 修复 PMS Bug 时被调用（`POST /api/pms/check`），但前端**没有**对应的 `pms.ts` api 文件 — 意味着 UI 层 PMS 监控页面可能存在但代码路径不规范。

**建议**: S5 做完整前后端契约核查。S2 不做修复，只记录。

---

## 🟠 P1 发现

### F50 — SignalComposer archive 历史变种（非生产）

**位置**: `scripts/archive/` 3 处
- `run_pead_backtest.py:210`: `class PEADSignalComposer(SignalComposer)` — 子类重载
- `test_7factor_equal_weight.py:392`: `def compose_signals(...)` — 独立函数
- `backtest_rsrs_weekly.py:132`: 注释明确 "不经过 SignalComposer"

**影响**: archive 路径，不进生产。但违反铁律 16 历史痕迹。

**建议**: archive 是归档区，不做修复。S5 如果执行 archive 清理，这些文件整体删除。

### F52 — factor_engine.py 同文件两条 INSERT 路径

**位置**: `backend/engines/factor_engine.py`
- `:1400 save_daily_factors()` 走 DataPipeline ✅
- `:1803 compute_batch_factors()` 内部 `:2001` 直接 INSERT ❌（dead code, 只 archive 调用）

**建议**:
- 短期: 在 `compute_batch_factors` 函数顶部加 `raise DeprecationWarning("Use save_daily_factors + DataPipeline. See S2 F52")` 或直接 `raise NotImplementedError`
- 中期: 删除该函数及其辅助代码（~300 行），降低 factor_engine.py 到 ~1700 行（F43 改善）

**工作量**: ~30 min + 测试。

### F54 — `factor_onboarding` 使用简化中性化（无 ln_mcap）

**位置**: `backend/engines/neutralizer.py:1-18`

**证据**（代码注释自白）:
```python
"""行业中性化共享模块 — 替代 factor_onboarding.py 中的截面 zscore 近似。

本模块保留供 factor_onboarding（GP 管道）使用，该路径暂无 ln_mcap 数据。
"""
```

**影响**: factor_onboarding 的"中性化"实际上只做行业中性（无市值中性），与铁律 4 "因子+中性化（行业+市值 WLS）"不一致。

配合 F53/F60，意味着新因子通过 approval_queue 入库时：
1. 中性化不完整（仅行业，缺 ln_mcap）
2. IC 计算违反铁律 19 + 前瞻偏差

**建议**: 与 F53/F60 一起中期重构 `factor_onboarding`。同时要求 GP 管道提供 ln_mcap 数据。

### F55 — PT 直接 import factor_engine（耦合但非违规）

**位置**: `scripts/run_paper_trading.py:35`
```python
from engines.factor_engine import compute_daily_factors, save_daily_factors
```

**分析**: 两个函数都是 factor_engine 的顶层公开函数，`save_daily_factors` 还走 DataPipeline。这属于**PT 直接依赖 factor_engine 的 API**。
- **非违规**: compute_daily_factors 返回 DataFrame（纯计算），save_daily_factors 走 DataPipeline（合规入库）
- **耦合问题**: PT 入口直接知道 factor_engine 实现，没有 Service 层抽象 — 若 factor_engine 签名改动需要同步改 PT
- 也是 F43 factor_engine.py 2034 行重构的诱因

**建议**: 中期做 `services/factor_calculation_service.py` 封装，PT 只调 Service。

### F57 + F58 — 调度链路分散无统一表

**位置**:
- `backend/app/tasks/beat_schedule.py`: 仅 gp-weekly + pms-daily-check
- **Windows Task Scheduler**: PT 主链 (16:15/16:25/16:30/09:31/15:10)

**证据** (`beat_schedule.py:50-63`):
```python
# ── [已移除] PT主链任务由Task Scheduler驱动，Beat不再触发 ──
# daily-health-check: 移除(2026-04-06) — 由Task Scheduler QM-HealthCheck 16:25触发
# daily-signal: 移除(2026-04-06) — 由Task Scheduler QuantMind_DailySignal 16:30触发
# daily-execute: 移除(2026-04-06) — 由Task Scheduler QuantMind_DailyExecute 09:31触发
```

**问题**:
1. 新人无法从代码中看到完整调度链路
2. CLAUDE.md 声称的链路在两个不同系统分散
3. Windows Task Scheduler 配置**不在 git 版本控制**（`schtasks /query /xml` 需手动导出）
4. 铁律 15 "回测可复现" 的外推 — 调度本身也应可复现

**建议**:
1. **短期**: 在 `docs/SYSTEM_RUNBOOK.md`（如果存在）或新建 `docs/SCHEDULING_LAYOUT.md` 写清每个时间点的执行主体、命令、依赖
2. **中期**: `schtasks /query /xml > docs/windows_task_schedules.xml` 纳入版本控制
3. **长期**: 逐步迁回 Celery Beat 统一编排（若可行）

**工作量**: 短期文档 ~1 小时；中期版本控制 ~30 min。

### F61 (新编号) — 配置漂移三向对齐 ✅ PASS (除 F62)

**检查**: `.env` / `configs/pt_live.yaml` / `backend/app/config.py` / `signal_engine.py`

| 字段 | .env | pt_live.yaml | config.py default | signal_engine default | 一致 |
|---|---|---|---|---|---|
| top_n | 20 | 20 | 20 | 20 (SignalConfig) | ✅ |
| industry_cap | 1.0 | 1.0 | 1.0 | 0.25 (SignalConfig, 漂移) | ⚠️ F40 |
| size_neutral_beta | 0.50 | 0.50 | **0.0 (危险 default)** | 0.0 | ❌ **F62** |
| rebalance_freq | — | monthly | — | "biweekly" (SignalConfig, 漂移) | ⚠️ F40 |
| factors | — | CORE3+dv_ttm | — | CORE3+dv_ttm (PAPER_TRADING_CONFIG) | ✅ |
| commission | — | 0.0000854 | — | — (backtest config) | ✅ |
| stamp_tax | — | historical | — | historical (backtest config) | ✅ |
| min_commission | — | 5.0 | — | 5.0 (backtest config) | ✅ |

**结论**: 除 F62（SN default=0.0 危险）+ F40（SignalConfig default 过期）两个残留隐患外，对齐良好。

### F17 + F43 更新 — factor_engine.py 结构债

**F17 关闭**: PT 生产路径合规（save_daily_factors）。

**F43 升级（本次新发现）**: `factor_engine.py` 不仅 2034 行巨石，还有 4 类职责混合:
1. **纯计算函数** (40+ calc_* 函数 line 24-420)
2. **预处理 pipeline** (preprocess_mad / fill / neutralize / zscore / pipeline line 1056-1200)
3. **数据加载** (load_daily_data / load_bulk_data / load_fundamental_pit_data / load_forward_returns line 926-1803) — **Engine 层读 DB**
4. **写入协调** (save_daily_factors line 1400 合规, compute_batch_factors line 1803 dead code)
5. **IC 计算** (calc_ic line 1217, 独立于 ic_calculator)

**F43 拆分建议**（长期）:
```
backend/engines/factor/        # 纯计算 (1-5)
├── price_factors.py
├── volume_factors.py
├── fundamental_factors.py
├── alpha158_factors.py
└── preprocess.py             # MAD/fill/WLS/zscore

backend/app/data/factor_loader.py   # 数据加载 (3)
backend/app/services/factor_calculation_service.py  # 协调 (4)
```

**工作量**: 1-2 周的重构 + 完整测试回归。

---

## 🟡 P2 发现

### F56 — `bruteforce_engine._compute_ic_series` 口径未验证

**位置**: `backend/engines/mining/bruteforce_engine.py:1108`

**代码签名**:
```python
def _compute_ic_series(
    factor_values: pd.Series,
    forward_returns: pd.Series | pd.DataFrame,
) -> pd.Series:
```

**口径取决于调用方传入的 `forward_returns`** — 是 raw 还是 excess 由调用者决定。

**行 917 调用点**（在同一文件）需要进一步查证。若 GP 管道里 forward_returns 是 raw return，则铁律 19 违规。

**建议**: S2b 或 S3 深入验证。

### F19 学习点（从 S1 继承）

TimescaleDB hypertable reltuples 为 0 不是真 0 — 用 `timescaledb_information.hypertables` + `hypertable_size()` 查询。S6 `invariant_check.py` 必须避坑。

### F2 cleanup follow — archive 126 个脚本可整体删除

F13 已确认无生产引用。建议在 S5 最后做一次 `git mv scripts/archive/ .archive-graveyard/` 或直接 `rm -rf`，只在 README 保留"曾经的研究脚本见 commit history"。

---

## ⚖ 铁律合规评分（S2 覆盖部分）

| # | 铁律 | 状态 | 证据 | Delta vs S1 |
|---|---|---|---|---|
| 16 | 信号路径唯一 | ✅ **PASS (生产)** | 30+ 调用全走 SignalComposer，archive 3 处偏离不算 | ↑ PASS |
| 17 | DataPipeline 唯一入库 | ⚠️ **部分 PASS** | PT 生产 save_daily_factors ✅，factor_onboarding 仍违规 | ↗ 修正 |
| 18 | 成本与实盘对齐 | ✅ **PASS** | backtest/pt_live.yaml/broker.py 三处对齐 F64 | ✅ 新验证 |
| 19 | IC 口径统一 | ❌ **FAIL** | factor_onboarding 生产路径违规 (F51/F60) | ❌ 新发现 |
| 22 | 文档跟代码 | 🟡 改善 | S1 cleanup 做了一半 | 🟡 进行中 |
| 30 | 中性化后重建缓存 | ✅ **PASS** | Parquet 2026-04-15 15:27 全量重建 | ✅ 新验证 |

---

## 📌 S2 修复清单（P0/P1 快修候选）

**S2 内可做**（低风险快修）:
- [ ] **F62** — config.py SN default 改为 `None + validator`（~20 min）
- [ ] **F40** — signal_engine.py `SignalConfig` default 收紧（~30 min）
- [ ] **F51/F53/F60 短期告警** — factor_onboarding 函数入口加 WARNING log + 注释标 DEPRECATED（~15 min）
- [ ] **F52 短期 guard** — factor_engine.compute_batch_factors 入口 `raise DeprecationWarning`（~10 min）

**S2 不做, 转 S2b / S3 / S5**:
- [ ] F51/F53/F60 中期修复（factor_onboarding IC 重构, 2+ 小时 + 测试回归）
- [ ] F63 前端契约完整核查（S5）
- [ ] F57/F58 调度链路文档化（S3 韧性 session 顺带做）
- [ ] F43 factor_engine.py 拆分（长期）

---

## 📎 附录 A: IC 计算路径清单（铁律 19 总览）

项目中当前**至少 4 种** IC 计算实现：

| 路径 | 文件 | 口径 | 调用方 | 状态 |
|---|---|---|---|---|
| A | `engines/ic_calculator.py:compute_ic_series` | T+1 超额 (CSI300) | fast_ic_recompute / phase3e / phase12 / noise_robustness / 大多数 research | ✅ 合规 |
| B | `services/factor_onboarding.py:_compute_ic_series` | Raw return + 无 T+1 | approval_queue → FactorOnboardingService | ❌ **活跃违规** F51/F60 |
| C | `engines/mining/bruteforce_engine.py:_compute_ic_series` | 取决于调用方 | bruteforce_engine 内部 line 917 | ⚠️ 未验证 F56 |
| D | `backend/scripts/compute_factor_ic.py` (deprecated) | Raw return | `compute_factor_phase21.py:233` / `compute_alpha158_ic.py:26` | ❌ dead but still imported |

**目标**: 所有 IC 写入 `factor_ic_history` 都经由 **A 路径**。B/C/D 要么迁移要么删除。

---

## 📎 附录 B: SignalComposer 调用点统计（铁律 16 总览）

**生产路径（全部合规 ✅）**:
```
backend/app/services/signal_service.py:136   → 生产 PT 信号
backend/engines/walk_forward.py:150           → WF 验证
scripts/run_backtest.py:314                   → CI 回测
```

**Research 脚本（合规 ✅）**:
```
scripts/research/wf_size_neutral.py:139
scripts/research/size_neutral_backtest.py:150
scripts/research/regime_size_neutral.py:103
scripts/research/modifier_experiments.py:283
scripts/research/verify_factor_expansion.py:193
scripts/research/verify_phase1_isolation.py:137
```

**Archive 偏离 (3 处, 非生产)**:
```
scripts/archive/run_pead_backtest.py:210        → 子类 PEADSignalComposer
scripts/archive/test_7factor_equal_weight.py:392 → 独立 compose_signals 函数
scripts/archive/backtest_rsrs_weekly.py:132      → 注释明确绕过
```

---

## 📎 附录 C: 调度链路分布（F57/F58）

```
Celery Beat (backend/app/tasks/beat_schedule.py):
  ├── gp-weekly-mining    Sun 22:00    → mining_tasks.run_gp_mining
  └── pms-daily-check     Mon-Fri 14:30 → daily_pipeline.pms_check

Windows Task Scheduler (不在 git):
  ├── QM-HealthCheck           16:25  → scripts/health_check.py
  ├── QuantMind_DailySignal    16:30  → scripts/run_paper_trading.py (signal generation)
  ├── QuantMind_DailyExecute   09:31  → scripts/run_paper_trading.py (T+1 execute)
  └── [对账 15:10 — 未验证实际命令]
```

**建议导出命令** (在用户 Windows 上执行):
```cmd
schtasks /query /TN "QuantMind_DailySignal" /xml > docs/schtasks/QM_DailySignal.xml
schtasks /query /TN "QuantMind_DailyExecute" /xml > docs/schtasks/QM_DailyExecute.xml
schtasks /query /TN "QM-HealthCheck" /xml > docs/schtasks/QM_HealthCheck.xml
```

---

**报告结束**。S2 静态审计完成度: **约 80%**。

下一步:
1. 执行 S2 内四个快修 (F62 / F40 / F51 告警 / F52 guard)
2. 更新 `AUDIT_MASTER_INDEX.md` 累计计数
3. Commit

S2b / S3 / S5 承接的中期修复清单已列入附录 / 正文。
