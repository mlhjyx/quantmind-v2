# MVP 3.1b Risk Framework v2 — 单股层风控补全 (P0 真生产事件驱动)

> **状态**: 🔴 P0 紧急 (Session 44, 2026-04-29)
> **触发**: 真生产 PT live 卓然股份 (688121) -29.17% / -¥14,306 + 南玻 (000012) -9.75% / -¥4,715, **Risk Framework 30 天 0 触发** (实测 risk_event_log 0 行)
> **范围**: Phase 1 SingleStockStopLossRule + Phase 2 可观测性补全 (1 PR)
> **耗时**: 4-6h
> **设计文档**: 本文 (≤ 2 页, 铁律 24)

## 实测真根因 (Session 44, 2026-04-29)

**Risk Framework 在跑但 4 规则全部对当前事件设计上失效**:

| 规则 | 触发条件 | 卓然 -29% 实测 | 触发? |
|---|---|---|---|
| PMSRule L1/L2/L3 | 浮盈 ≥ +10/20/30% **AND** 回撤 ≥ 10/12/15% | 从未浮盈过 (从买入即跌) | ❌ |
| IntradayPortfolioDrop 3/5/8% | 组合 NAV 跌 ≥ 3% | 单股 -¥14k / NAV ¥1M = -1.4% | ❌ |
| QMTDisconnectRule | QMT 断线 | 一直连接 | ❌ |
| CircuitBreakerRule | 组合 NAV 大幅跌 | -0.18% | ❌ |

**结构性 gap**: 现 4 规则**全部组合层**, 单股层 0 保护. PMS 设计假设"先涨后跌", 对"买入即跌"完全失效.

**第二根因**: `scheduler_task_log` 30 天**未记录** `risk-daily-check` / `intraday-risk-check` (worker 真跑了, 但 task 内部不写 log), 与其他 task (pt_audit / signal_phase) 不一致 → 可观测性 gap.

## Scope (Phase 1+2 合 1 PR, ~4-6h)

### Phase 1: SingleStockStopLossRule (单股止损规则)

**新建** `backend/qm_platform/risk/rules/single_stock.py`:
- `SingleStockStopLossRule` 单 class, 4 档阈值: -10% (P2 alert), -15% (P1 alert), -20% (P0 alert), -25% (P0 sell)
- 触发条件: `(current_price - entry_price) / entry_price <= -threshold`
- **不依赖浮盈/回撤** (与 PMSRule 互补 — PMS 保护"涨完回撤", SingleStockStopLoss 保护"买入即跌")
- 默认 action="alert_only" (不自动卖, 防误触发引发 silent sell, 钉钉告警让用户手工决策)
- -25% 档可配置 action="sell" (用户开 flag 后启用真正自动止损)

**接入 wiring**: `risk_wiring.py::build_daily_risk_engine()` 加 `SingleStockStopLossRule()`,
`build_intraday_risk_engine()` 同步加. daily 14:30 + intraday `*/5 9-14` 双频检查.

### Phase 2: scheduler_task_log 写入修复

**修** `backend/app/tasks/daily_pipeline.py::risk_check_task` + `intraday_risk_check_task`:
- 与 `pt_audit_task` / `signal_phase_task` 一致 pattern: `_log_task_run(task_name, status, duration, error_message, result_json)`
- task 入口 `start_time = utcnow()`, exit/exception 时统一 finally 写 scheduler_task_log
- result_json 含 `total_triggered / total_alerted / total_dedup_skipped / strategies_count`

## Out-of-scope (留 Phase 1.5/3+)

- ❌ `PositionHoldingTimeRule` 持仓 ≥ 7 天 + 亏损 ≥ -10% — 依赖 Position 契约扩展 entry_date 字段, 单独 PR (Phase 1.5)
- ❌ `NewPositionVolatilityRule` 新建仓 ≤ 7 天 -15% — 同上依赖 entry_date, Phase 1.5
- ❌ `IndustryConcentrationRule` 单行业 > 30% — 依赖 SW1 行业映射注入, Phase 3
- ❌ `ConcentratedLossRule` 多股累计亏损告警 — Phase 3
- ❌ position_snapshot.holding_days 字段维护修复 — 独立 PR (Phase 1.5 + Phase 1 协同, 现 dead 字段)
- ❌ ADR-016 PMS v1.0 deprecate 决策 — 留架构评估 PR (Phase 3+)
- ❌ 实盘 vs 回测偏离规则 — Phase 4

## 关键架构决策 (铁律 39 平台工程师视角)

| 决策 | 选择 | 理由 |
|---|---|---|
| **action 默认值** | `alert_only` 不自动 sell | 误触发自动卖 = 真金事故; 钉钉告警让用户决策 (-25% 档 future flag 升 sell) |
| **-25% 档 severity** | P0 + alert_only | 阈值已极严, 但 sell 不开默认 (与 PMSRule sell 区分 — PMS 是"已盈利保护", 不致灾) |
| **挂 daily + intraday** | 两个 engine 都接 | daily 14:30 一次, intraday 5min 高频, 任一触发都告警 |
| **不动 PMSRule** | 共存 | PMS 仍保护"涨完回撤", SingleStockStopLoss 互补 "买入即跌" |
| **Position 契约不扩展** | Phase 1 不动 | 减少 schema risk; entry_date 留 Phase 1.5 单独评估 |
| **dedup_key 设计** | 同 IntradayAlertDedup 模式: `single_stock_stoploss_l{N}:{strategy_id}:{code}:{date}` | 同股同档 24h 仅 1 次告警, 防 5min × 4 档 = 频繁刷屏 |

## Pattern Usage (Application caller, batch 3.x SDK 迁后)

```python
# daily_pipeline.risk_check_task / intraday_risk_check_task 内部
engine = build_daily_risk_engine()  # 含 PMSRule + CB + SingleStockStopLossRule
context = engine.build_context(strategy_id, execution_mode)
results = engine.run(context)
# results 现可包含 SingleStockStopLossRule 触发 (例 卓然 -29% → rule_id=single_stock_stoploss_l4)
engine.execute(to_execute, context)  # 写 risk_event_log + 钉钉
```

## 验证 (硬门, 铁律 10b + 40 + 33)

- ≥ 12 unit tests (4 阈值档 × 触发/不触发 + edge cases entry_price=0/current=0/shares=0)
- 1 smoke (subprocess + ABC + 静态 marker)
- ruff clean
- 不破现有 PMSRule + intraday rules 测试
- pre-push smoke 全过 (现 baseline 50)
- 真 PG 测试: 历史 4-29 数据回放 (卓然 -29% / 南玻 -9.75% 必触发 SingleStockStopLossRule, 写入 risk_event_log)

## 验收 (Phase 1+2 完结)

- ✅ 卓然/南玻级别单股 -10%+ 必触发, 写入 risk_event_log
- ✅ 钉钉告警送达 (与 PMSRule 同 channel)
- ✅ scheduler_task_log 含 risk-daily-check / intraday-risk-check 行 (与 pt_audit 一致)
- ✅ daily-risk-check 14:30 + intraday-risk-check 5min 真生产首日 (PT 重启后) 必跑出 N 行 risk_event_log
- ✅ 不破 PMS 老逻辑 (PMS 还保护 "涨完回撤" 场景)

## LL-059 9 步闭环

`feat/risk-v2-single-stock-protection` → impl + tests → ruff → push → PR → reviewer (everything-claude-code:python-reviewer) → fix → comment → self-merge → sync main.

## 后续 PR (Phase 1.5/3/4)

- **Phase 1.5** (本周内): Position 契约扩展 entry_date + position_snapshot.holding_days 修复 + PositionHoldingTimeRule + NewPositionVolatilityRule (1 PR ~500 行)
- **Phase 3** (下周): IndustryConcentrationRule + ConcentratedLossRule (1 PR)
- **Phase 4** (2 周内): 实盘 vs 回测偏离 + Performance Attribution (1 PR)
- **ADR-016** (Wave 4 末): PMS v1.0 deprecate 决议 (与 v2 共存 vs 替换)
