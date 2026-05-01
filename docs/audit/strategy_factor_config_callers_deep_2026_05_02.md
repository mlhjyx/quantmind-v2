# Audit — strategy.factor_config 6 字段 caller 深查 (2026-05-02)

> **触发**: Layer 2.5 plan v0.2 sub-task 2.5.1. ADR-023 §1.3 标 "/api/execution/algo-config (execution.py:190): 不取 factors, **真读哪些字段未深查 (FU-1 范围)**". 本 task 真测每字段 caller, ADR-023 reversibility 评估.
> **范围**: 纯审计, 0 修代码 / 0 改数据 / 0 改 ADR / 0 PR. 仅交付证据 + reversibility 判定 + Layer 2.5.5 合并决议.
> **顶层结论**: **判定 (i) — 0 prod trading path 读 stale, ADR-023 §2 现状保留 + 防御层 sustained, 0 修订**. 但发现 (a) ADR-023 §1.1 真值表 2 处误标 (turnover_cap / weight_method 实际 = yaml, 非 stale); (b) strategy_configs v2 top_n=15 vs yaml=20 是新发现 stale 字段 (ADR-023 §1.1 未列); (c) 3 表 (strategy_registry/evaluations/status_log) 是 multi-strategy 系列, 与 ADR-023 不同 scope, 不合并 2.5.5.

---

## §0 TL;DR (3 句)

1. **生产 trading path 0 引用 DB stale 字段** — signal_engine.py:218 真读 yaml `strategy.get("factors", [])` (注释 L114 显式 "权威: configs/pt_live.yaml:strategy.factors auditor.py L96-98 注释明定"). run_paper_trading / execution_service / Celery task 同走 yaml. ADR-023 §2 sustained.
2. **唯一 DB stale 真读 caller**: `/api/execution/algo-config` ([backend/app/api/execution.py:202-236](backend/app/api/execution.py:202)) — 仅前端展示, 5 字段 stale 透传 (slippage_bps=10, top_n=20/v2 实际 15, turnover_cap=0.5 与 yaml 相同). ADR-023 FU-2 前端 banner 已 cover.
3. **🆕 新发现 3 项**: (a) ADR-023 §1.1 turnover_cap / weight_method 误标 stale (实测 = yaml); (b) strategy_configs v2 `top_n=15` ≠ yaml=20, ADR-023 §1.1 未列; (c) 3 overlap 表是 multi-strategy 系列 (与 ADR-023 不同 scope), 不合并 2.5.5.

---

## §A 真值 drift 对照 (5-02 重测 ADR-023 §1.1)

### A.1 yaml 真值 (configs/pt_live.yaml)

```yaml
strategy:
  factors:                          # 4 (CORE3+dv_ttm)
    - {name: turnover_mean_20, direction: -1}
    - {name: volatility_20, direction: -1}
    - {name: bp_ratio, direction: 1}
    - {name: dv_ttm, direction: 1}
  compose: equal_weight             # ⚠️ 字段名是 "compose" 不是 "weight_method"
  top_n: 20
  industry_cap: 1.0
  turnover_cap: 0.5

execution:
  costs:
    commission_rate: 0.0000854      # 国金证券实际万 0.854
  slippage:
    mode: volume_impact             # ⚠️ yaml 不用 fixed slippage_bps
    config: { ... Bouchaud 系数 ... }
```

### A.2 strategy.factor_config (jsonb) 真值

```json
{
  "top_n": 20,
  "factors": ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"],
  "beta_hedge": {"method": "rolling_60d", "enabled": true, ...},
  "industry_cap": 0.25,
  "slippage_bps": 10.0,
  "turnover_cap": 0.5,
  "weight_method": "equal",
  "rebalance_freq": "monthly",
  "stamp_tax_rate": 0.0005,
  "commission_rate": 0.00015,
  "initial_capital": 1000000
}
```
strategy `28fc37e5-2d32-4ada-92e0-41c11a5103d0` (Phase0_PaperTrading), active_version=2.

### A.3 strategy_configs.config 真值 (按 created_at DESC)

| version | created_at | top_n | factors | industry_cap | turnover_cap | weight_method | slippage_bps | commission_rate |
|---|---|---:|---|---:|---:|---|---:|---:|
| 2 | 2026-03-22 03:39 | **15** ⚠️ | CORE5 (5) | 0.25 | 0.50 | equal | (无字段) | (无字段) |
| 1 | 2026-03-21 19:03 | 20 | CORE5 (5) | 0.25 | 0.5 | equal | 10.0 | 0.00015 |

### A.4 7 字段 drift 真测对照 ⭐

| 字段 | yaml | strategy | strategy_configs v2 | strategy_configs v1 | drift status | ADR-023 §1.1 标记 |
|---|---|---|---|---|---|---|
| **factors[]** | 4 (CORE3+dv_ttm) | 5 (CORE5) | 5 (CORE5) | 5 (CORE5) | ⚠️ **stale** | ✅ stale (正确) |
| **top_n** 🆕 | 20 | 20 | **15** ⚠️ | 20 | ⚠️ **strategy_configs v2 漂移** | ❌ 未列 (新 finding) |
| **industry_cap** | 1.0 | 0.25 | 0.25 | 0.25 | ⚠️ **stale** | ✅ stale (正确) |
| **commission_rate** | 0.0000854 | 0.00015 | (无字段) | 0.00015 | ⚠️ **stale** | ✅ stale (正确, 差 1.76x) |
| **slippage_bps** | (无, volume_impact mode) | 10.0 | (无字段) | 10.0 | ⚠️ **mode 不匹配** | ✅ stale (正确, 但 yaml 不用 fixed bps) |
| **turnover_cap** | 0.5 | 0.5 | 0.50 | 0.5 | ✅ **same** | ❌ ADR-023 误标 stale "(yaml 真值)" |
| **weight_method** | "equal_weight" (compose) | "equal" | "equal" | "equal" | ✅ **same (字段名差异)** | ❌ ADR-023 误标 stale "(yaml 真值)" |

🆕 ADR-023 §1.1 真值表修订建议:
- **turnover_cap 真不漂** (yaml=0.5, DB=0.5 完全相同) → ADR-023 §1.1 应去掉此行
- **weight_method 真不漂** (yaml `compose: equal_weight` ≡ DB `weight_method: "equal"` 同语义) → ADR-023 §1.1 应去掉或加注 "字段名差异不是值差异"
- **top_n** 是 strategy_configs v2 唯一独有 stale (yaml=20, v2=15, v1=20) → ADR-023 §1.1 应加此行

ADR-023 整体决议**不变** (现状保留 + 防御层), 仅 §1.1 真值表本身需修. 候选 ADR-023 v0.4 修订或 sub-doc 补丁.

### A.5 PT_TOP_N / PT_INDUSTRY_CAP .env 配置 (信令路径真用)

`backend/.env` Layer 2.5.7 sustained:
```
PT_TOP_N=20            (yaml 同步)
PT_INDUSTRY_CAP=1.0    (yaml 同步)
EXECUTION_MODE=paper
LIVE_TRADING_DISABLED=true   (5-02 加)
```
`signal_engine.py:241` 读 `settings.PT_INDUSTRY_CAP` (env 权威). 与 yaml=1.0 同步 ✅.

---

## §B 6 字段 caller 分类对照表

### §B.1 总览统计

| 字段 | total caller 数 | 生产 trading | backtest | analysis | frontend | test | docstring/config |
|---|---:|---:|---:|---:|---:|---:|---:|
| factors[] | ~15 | **2** (yaml-driven) | 多 (yaml-driven) | 0 | 0 | 多 | 多 |
| industry_cap | ~25 | **2** (.env) | 多 | 1 | 1 (algo-config) | 多 | 多 |
| commission_rate | ~22 | 0 (yaml costs) | 多 | 0 | 0 (algo-config 不返回) | 多 | 多 |
| slippage_bps | ~28 | 0 (yaml volume_impact) | 0 (config) | 0 | 1 (algo-config) | 多 | 多 (trade_log 列) |
| turnover_cap | ~25 | **2** (yaml) | 多 | 0 | 1 (algo-config) | 多 | 多 |
| weight_method | ~25 | **2** (yaml) | 多 | 0 | 0 | 多 | 多 |

### §B.2 关键 caller 详细 (按字段)

#### factors[] (核心生产路径)

| # | file:line | 真读源 | 真用途 |
|---|---|---|---|
| f.1 | [backend/engines/signal_engine.py:218](backend/engines/signal_engine.py:218) | yaml `strategy.get("factors", [])` | ⭐ 生产 PT 信令主入口, raise if empty |
| f.2 | [backend/engines/signal_engine.py:114](backend/engines/signal_engine.py:114) | (注释) | 显式声明 "权威: pt_live.yaml:strategy.factors" |
| f.3 | [scripts/run_paper_trading.py:205](scripts/run_paper_trading.py:205) | (兼容性校验) | 防外部脚本篡改 factors, warning-level |
| f.4 | [scripts/run_paper_trading.py:514](scripts/run_paper_trading.py:514) | argparse `--skip-factors` flag | 调试旁路 |

✅ **0 caller 读 strategy.factor_config 或 strategy_configs.config 的 factors**

#### industry_cap

| # | file:line | 真读源 | 真用途 |
|---|---|---|---|
| ic.1 | [backend/engines/signal_engine.py:241](backend/engines/signal_engine.py:241) | `settings.PT_INDUSTRY_CAP` (.env) | ⭐ 生产 PT 信令 industry_cap, env=1.0 同步 yaml |
| ic.2 | [backend/app/services/config_loader.py:122](backend/app/services/config_loader.py:122) | yaml `strategy.get("industry_cap", 1.0)` | yaml-loaded SignalConfig |
| ic.3 | [backend/engines/base_strategy.py:221](backend/engines/base_strategy.py:221) | `self.config.get("industry_cap", 0.25)` | base strategy 接受 dict-injected config (从 yaml 来) |
| ic.4 | [backend/engines/strategies/equal_weight.py:220](backend/engines/strategies/equal_weight.py:220) | `self.config.get("industry_cap", 0.25)` | EqualWeight strategy 同上 |
| ic.5 | [backend/engines/pre_trade_validator.py:79-238](backend/engines/pre_trade_validator.py:79) | constructor parameter | PreTradeValidator 接受 industry_cap 注入 |
| ic.6 | [backend/engines/multi_freq_backtest.py:93](backend/engines/multi_freq_backtest.py:93) | parameter default 0.25 | 多频回测引擎 |
| ic.7 | [backend/engines/factor_classifier.py:415](backend/engines/factor_classifier.py:415) | hardcoded 0.25 | factor 分类器 default |
| ic.8 | [backend/engines/backtest/runner.py:108,260](backend/engines/backtest/runner.py:108) | hardcoded 1.0 | 回测 runner default 无约束 |

✅ **0 caller 直接读 DB strategy.factor_config.industry_cap** (生产+回测都走 .env / yaml / hardcoded)

#### commission_rate

| # | file:line | 真读源 | 真用途 |
|---|---|---|---|
| cr.1 | [backend/app/services/config_loader.py:100](backend/app/services/config_loader.py:100) | yaml `costs.get("commission_rate", 0.0000854)` | ⭐ yaml costs 真权威 |
| cr.2 | [backend/engines/backtest/broker.py:148,216,228](backend/engines/backtest/broker.py:148) | `self.config.commission_rate` | 回测 broker (BacktestConfig 传入) |
| cr.3 | [backend/engines/backtest/config.py:41](backend/engines/backtest/config.py:41) | default 0.0000854 | BacktestConfig default = yaml 同步 |
| cr.4 | [backend/qm_platform/config/schema.py:83](backend/qm_platform/config/schema.py:83) | Field default 0.0000854 | platform schema 同步 |
| cr.5 | [backend/engines/multi_freq_backtest.py:39](backend/engines/multi_freq_backtest.py:39) | `STANDARD_COST = {"commission_rate": 0.0000854}` | 多频 hardcoded = yaml 同步 |
| cr.6 | tests (~10 hits) | 0.0000854 | 测试 fixture 全走 yaml 真值 |

✅ **0 caller 读 DB.commission_rate (0.00015)**, 全 hardcoded = yaml 0.0000854 ✅

🆕 `/api/execution/algo-config` ([execution.py:222-236](backend/app/api/execution.py:222)) returned dict **不含 commission_rate** — 仅 slippage_model/slippage_bps/order_type/top_n/rebalance_freq/turnover_cap/cash_buffer/max_single_weight/max_industry_weight. commission_rate 不暴露给前端.

#### slippage_bps

| # | file:line | 真读源 | 真用途 |
|---|---|---|---|
| sb.1 | [backend/app/api/execution.py:228](backend/app/api/execution.py:228) | `cfg.get("slippage_bps", 10)` | ⚠️ **唯一 DB 真读 caller** — strategy_configs.config 透传给前端 |
| sb.2 | [backend/app/api/paper_trading.py:169-187](backend/app/api/paper_trading.py:169) | `SELECT AVG(slippage_bps) FROM trade_log` | post-trade 实测滑点 |
| sb.3 | [backend/app/models/trade.py:82](backend/app/models/trade.py:82) | column `slippage_bps` | trade_log 实测列 (post-fill) |
| sb.4 | [backend/app/services/execution_service.py:375](backend/app/services/execution_service.py:375) | INSERT trade_log slippage_bps | 真生产写入实测滑点 |
| sb.5 | tests | 0 / 10 / etc | 测试 fixture |

⚠️ sb.1 是 ADR-023 §1.3 cite 的 caller — DB strategy_configs v1 有 slippage_bps=10, 透传给前端 (但 yaml 真用 volume_impact mode, 不是 fixed bps).

✅ 0 prod **trading** path 读 DB.slippage_bps (生产 slippage 来自 yaml execution.slippage.config, signal_engine 不读 DB).

#### turnover_cap

| # | file:line | 真读源 | 真用途 |
|---|---|---|---|
| tc.1 | [backend/engines/signal_engine.py:223](backend/engines/signal_engine.py:223) | yaml `strategy.get("turnover_cap", 0.50)` | ⭐ 生产 PT 信令 turnover_cap |
| tc.2 | [backend/engines/signal_engine.py:212-215](backend/engines/signal_engine.py:212) | SignalConfig 字段 | yaml-derived |
| tc.3 | [backend/app/services/config_loader.py:105,123](backend/app/services/config_loader.py:105) | yaml `strategy.get` | yaml SignalConfig 加载 |
| tc.4 | [backend/app/api/execution.py:232](backend/app/api/execution.py:232) | `cfg.get("turnover_cap", 0.5)` | algo-config endpoint, DB stale → 前端 (但 0.5 = yaml ⚠️ 真值相同, 实质无 stale) |
| tc.5 | [backend/engines/config_guard.py:11](backend/engines/config_guard.py:11) | (注释) | "YAML 是 turnover_cap 权威" |
| tc.6 | [backend/engines/base_strategy.py:223](backend/engines/base_strategy.py:223) | `self.config.get("turnover_cap", 0.50)` | base strategy 接受 yaml-injected |

✅ 0 caller 读 DB.turnover_cap **作为决策值**. 即使 algo-config 真返回 DB 值, 该值=yaml 真值 (不漂).

#### weight_method

| # | file:line | 真读源 | 真用途 |
|---|---|---|---|
| wm.1 | [backend/engines/signal_engine.py:367](backend/engines/signal_engine.py:367) | `self.config.weight_method` | ⭐ 生产权重方法 (从 yaml compose 派生) |
| wm.2 | [backend/app/services/config_loader.py:120](backend/app/services/config_loader.py:120) | yaml `strategy.get("compose", "equal")` | yaml `compose` 字段映射到 SignalConfig.weight_method |
| wm.3 | [backend/engines/base_strategy.py:220,229](backend/engines/base_strategy.py:220) | `self.config.get("weight_method", "equal")` + required 校验 | base strategy yaml-injected |
| wm.4 | [backend/engines/strategies/equal_weight.py:262](backend/engines/strategies/equal_weight.py:262) | yaml-derived | strategy 校验 weight_method=='equal' |
| wm.5 | [backend/engines/walk_forward.py:144](backend/engines/walk_forward.py:144) | hardcoded "equal" | WF 回测 |

✅ 0 caller 直接读 DB.weight_method. 全走 yaml `compose` 字段 → 映射 weight_method (字段名差异不是值差异).

---

## §C ADR-023 reversibility 评估

### §C.1 4 状态判定

| 状态 | 描述 | 真测结果 | 触发? |
|---|---|---|---|
| (i) | 0 prod path 真用 stale | ✅ 真测确认: signal_engine / execution_service / run_paper_trading 全 0 引用 DB stale | **判定 (i)** ⭐ |
| (ii) | prod path 读 stale 但值 = yaml | 不适用 (无 prod path 读 DB stale) | — |
| (iii) | prod path 读 stale 且 ≠ yaml | 不适用 | — |
| (iv) | Backtest / Analysis 读 stale | 0 backtest / 0 analysis 直接读 DB stale, 全走 yaml 或 hardcoded | — |

### §C.2 ADR-023 reversibility 结论

**ADR-023 不触发修订** — §2 现状保留 + 防御层 sustained.

但 ADR-023 §1.1 真值表本身需修订 (元数据修订, 不是决议变更):
- 去掉 turnover_cap 行 (实测 yaml=DB=0.5, 不漂)
- 去掉 weight_method 行 (字段名差异不是值差异)
- 加 top_n 行 (strategy_configs v2 漂 yaml=20 vs v2=15)

候选 ADR-023 v0.4 增量补丁 (P3, 不在本 audit scope, 留给 user 决议).

### §C.3 唯一 DB 真读 caller — `/api/execution/algo-config` 详查

ADR-023 §1.3 cite "/api/execution/algo-config (execution.py:190): 不取 factors, 真读哪些字段未深查".

5-02 真测 [backend/app/api/execution.py:222-236](backend/app/api/execution.py:222) 真返回 dict 11 字段:

| 字段 | 来源 | DB stale 真透传? | yaml 真值 | DB 真值 (v1) |
|---|---|---|---|---|
| strategy_name | row["strategy_name"] | n/a | n/a | "Phase0_PaperTrading" |
| version | row["version"] | n/a | n/a | 2 |
| updated_at | row["created_at"].isoformat() | n/a | n/a | 2026-03-22 |
| execution_mode | cfg.get("execution_mode", "paper") | DB 无字段 → fallback "paper" | paper | (无) |
| **slippage_model** | cfg.get("slippage_model", "fixed_bps") | DB 无字段 → fallback "fixed_bps" ⚠️ | volume_impact | (无) |
| **slippage_bps** | cfg.get("slippage_bps", 10) | ⚠️ **DB v1 真值 10 透传** | (无, 用 volume_impact) | 10.0 |
| order_type | cfg.get("order_type", "market_open") | DB 无字段 → fallback | (无) | (无) |
| **top_n** | cfg.get("top_n", 20) | ⚠️ **DB v2 真值 15 / v1 真值 20** (LIMIT 1 ORDER BY version DESC = v2 = 15) | 20 | 15 (v2) / 20 (v1) |
| rebalance_freq | cfg.get("rebalance_freq", "monthly") | DB v2 = "monthly" = yaml | monthly | monthly |
| **turnover_cap** | cfg.get("turnover_cap", 0.5) | DB = 0.5 = yaml ✅ | 0.5 | 0.5 |
| cash_buffer | cfg.get("cash_buffer", 0.03) | DB 无字段 → fallback 0.03 | 0.03 | (无) |
| max_single_weight | cfg.get("max_single_weight", 0.1) | DB 无字段 → fallback 0.1 | (无, 不约束) | (无) |
| **max_industry_weight** | cfg.get("max_industry_weight", 1.0) | DB 无字段 → fallback 1.0 = yaml ✅ | 1.0 | (无) |

🆕 真展示给前端 stale 的字段:
- `slippage_model = "fixed_bps"` (yaml 真用 volume_impact)
- `slippage_bps = 10` (yaml 真用 volume_impact, 没 fixed bps)
- `top_n = 15` (yaml=20, DB v2=15) ⚠️ **前端可能误读 PT 选 15 股而非 20**

但 PT 真生产**不读** algo-config 响应 — 这是给 frontend 显示用. 用户不会因此误下单, 但 mental model 困惑.

ADR-023 FU-2 (前端 banner) 已 cover. 本 task 加强证据但不改 ADR-023 决议.

---

## §D Stage D 重叠候选 (3 表 caller)

### §D.1 strategy_evaluations / strategy_status_log / strategy_registry 真测

| 表 | caller 真测 | 真用途 | 与 ADR-023 关系 |
|---|---|---|---|
| **strategy_evaluations** | [backend/migrations/strategy_evaluations.sql](backend/migrations/strategy_evaluations.sql) (DDL only, 0 prod read) + MVP 3.5.1 | append-only 评估历史审计 | ❌ 不同 scope (评估资产, 非配置) |
| **strategy_status_log** | [backend/app/services/strategy_bootstrap.py:21](backend/app/services/strategy_bootstrap.py:21) (注释提及) | 状态变更审计日志 (MVP 3.2 batch 4) | ❌ 不同 scope (审计, 非配置) |
| **strategy_registry** | [backend/app/services/strategy_bootstrap.py:91](backend/app/services/strategy_bootstrap.py:91) (S2PEADEvent 注册) + [backend/app/tasks/daily_pipeline.py:291,315](backend/app/tasks/daily_pipeline.py:291) (`get_live()` 多策略 iteration) + [backend/engines/strategies/s2_pead_event.py:68](backend/engines/strategies/s2_pead_event.py:68) (S2 hyperparams 通过 strategy_registry.config JSONB 覆盖) | **multi-strategy registry** (MVP 3.2 batch 1, 真生产读路径) | ❌ 不同 scope (multi-strategy 注册, 非 strategy_configs 单策略历史) |

### §D.2 合并决议 — **不合并**

3 表是 **multi-strategy registry 系列** (MVP 3.2 batch 1 + MVP 3.5.1 stack), 与 ADR-023 (单 PT 策略 strategy_configs.config 历史) 完全不同 scope:
- strategy_registry: 多策略注册 (S1=PT, S2=PEAD)
- strategy_status_log: 状态变更审计 (insert/update/delete events)
- strategy_evaluations: PlatformStrategyEvaluator 验证历史 (G1'-G3' Gates)

它们与 "yaml vs DB strategy_configs stale" 无关, 不属于 ADR-023 stale 范围. **2.5.1 不合并 2.5.5**.

3 表是否同 stale (ADR-023 FU-5) 是独立 P3 sub-task, 留 Layer 2.5 plan 2.5.5 单独处理.

⚠️ 但发现 **strategy_registry 真在生产 trading path 上** ([daily_pipeline.py:291](backend/app/tasks/daily_pipeline.py:291) `strategy_registry.get_live()` 多策略 iteration). 这与 task 5 audit (factor_registry 4-17 冻结) 是**不同表** (factor_registry vs strategy_registry — 名字像但完全不同 schema/scope). task 5 audit 没混淆, ADR-024 范围正确.

---

## §E 我没真测的 (transparency)

- **frontend `/strategies/{id}` 详情页路径**: 没在 frontend/src 找具体 component 引用. ADR-023 FU-2 banner 实施时需具体 path.
- **Backtest 引用 strategy.factor_config**: 没真测是否有 backtest 脚本走 DB 而不走 yaml. 推测 0 (因 backtest 也用 BacktestConfig + yaml costs), 但没 100% verify.
- **Analysis notebooks**: 没真测 jupyter notebook 是否引用 DB stale (ADR-023 FU-1 范围, 本 task 仅查 .py / .sql).
- **strategy_registry yaml-driven 还是 DB-driven**: daily_pipeline 用 `get_live()`, 但策略 hyperparams 通过 strategy_registry.config 覆盖 — 没深查覆盖路径是否漂 yaml.
- **strategy_configs v2 top_n=15 真因**: 没 git blame 找何时改 v2 (推测 setup_paper_trading.py 改过 + 没同步 yaml).

---

## §F STOP trigger 评估

| # | 触发条件 | 真测 | 行动 |
|---|---|---|---|
| 1 | C.2 (iii) 真生产 path 读 stale 且 ≠ yaml | 0 prod path 读 DB stale | ❌ 不 STOP |
| 2 | LIVE_TRADING_DISABLED ≠ true 或 EXECUTION_MODE ≠ paper | EXECUTION_MODE=paper / LIVE_TRADING_DISABLED=true 真测 | ❌ 不 STOP |
| 3 | yaml / DB 真值 vs ADR-023 §1.1 (5-02) drift > 0 | turnover_cap / weight_method 误标 (元数据修订) + top_n 新发现 | ⚠️ 报告不 STOP |
| 4 | 第 7+ stale 字段 (ADR-023 §1.1 表外) | top_n (v2=15) 是新发现 | ⚠️ 报告不 STOP (ADR-023 §1.1 修订, 非 §2 决议变更) |
| 5 | 阶段 D 合并候选超出 prompt scope | 不合并 (3 表 different scope) | ❌ 不 STOP |

**总结**: 0 硬 STOP. 3 项报告 (ADR-023 §1.1 真值表 2 处误标 + 1 新发现 top_n).

---

## §G Memory / sprint state 真值更新建议

| 建议 | 内容 |
|---|---|
| ADR-023 §1.1 元数据修订 | (a) 去掉 turnover_cap 行 (yaml=DB=0.5); (b) 去掉 weight_method 行 (字段名差异不是值差异); (c) 加 top_n 行 (yaml=20, strategy_configs v2=15). 决议 §2 不变. 候选 v0.4 增量 patch (P3) |
| GLOSSARY §10 footnote 更新 | 加 "🆕 7 字段真测 (5-02 task 2.5.1): 4 字段 stale + 2 字段误标 + 1 新发现, 但 0 prod path 真用, ADR-023 决议不变" |
| ADR-023 FU-1 状态 | ✅ 完成 (本 audit 真测 6 字段全 caller, 0 prod path 漏掉) — 候选标 done |
| ADR-023 FU-5 状态 | 维持 P3 (本 audit Stage D 真测 3 表与 stale scope 不同, 仍待独立 verify 是否 multi-strategy registry 也有 stale) |
| sprint state cite "DB strategy_configs latest = 5 (CORE5)" | 加注 "v2 top_n=15 是 v1 后改的, ADR-023 §1.1 未列, task 2.5.1 5-02 真测发现" |

---

## §H Decision

**ADR-023 §2 决议 sustained**: yaml SSOT, DB strategy_configs 是 setup-time legacy snapshot, 现状保留 + 防御层. 0 修订.

**ADR-023 §1.1 真值表元数据修订建议** (不变 §2 决议):
- 去 turnover_cap / weight_method 误标
- 加 top_n (v2=15)

**Layer 2.5.5 不合并 2.5.1** — 3 表 multi-strategy 系列与 ADR-023 不同 scope, 留独立 P3 sub-task.

---

## §I 文档版本

- **v0.1** (2026-05-02): 初稿, 7 字段真测 (6 ADR-023 列出 + 1 新发现 top_n) + 3 状态发现 (2 误标 + 1 新). 0 修代码 / 0 改 ADR / 0 PR. push branch `audit/strategy-factor-config-callers-2026-05-02` 等 user review.
