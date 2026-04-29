# PROJECT_DIAGNOSTIC_REPORT — QuantMind V2 风控系统独立法医审计

**审计日期**: 2026-04-29
**审计员**: 独立法医（不信任文档/不信任注释/只信代码与证据）
**审计范围**: 全部风控代码路径（新 `backend/qm_platform/risk/` + 老 `risk_control_service.py` + `pms_engine.py` + `daily_pipeline.py`）
**审计方法**: 代码逐行追踪 + DB 实测查询 + Redis 实测 + 配置一致性核对 + 与 LESSONS_LEARNED 交叉验证
**审计结论级**: **CATASTROPHIC**（资金保护层名义存在，实际近乎零）

---

## TL;DR — 一段话死刑判决

**真金 ¥1M 当前没有任何自动止损。** 14:30 风控日检 + 09:00–14:55 每 5 分钟盘中检查的 9 条规则**全部走完后产出零真实卖出动作**，根本原因**叠加**为 5 重失效：

1. **`LoggingSellBroker` 是占位 stub** —— 任何 `action=sell` 的规则触发 → broker 直接 `return {"status": "logged_only"}`，从未替换为真 broker（[risk_wiring.py:54-79](backend/app/services/risk_wiring.py:54)）。批 1 占位 5 个月未升级到批 2。
2. **8/9 条规则 action 是 `alert_only`** —— 即使 broker 是真的，单股止损/盘中跌 3-8%/QMT 断连/CB 转移**全部只发钉钉**，不下单（[interface.py:122-125](backend/qm_platform/risk/interface.py:122)）。
3. **唯一 `action=sell` 的 PMSRule 在当前持仓状态下永不触发** —— PMS 要求"浮盈 ≥10/20/30% 且回撤 ≥10/12/15%"，**真金 -29% 卓然股份从未浮盈过 → 任何亏损场景都不命中**（[pms.py:122-129](backend/qm_platform/risk/rules/pms.py:122)）。
4. **当前 `EXECUTION_MODE=paper` 但持仓数据全是 `live` 命名空间** —— `trade_log` `WHERE execution_mode='paper'` 返 0 行 → `entry_price=0.0` → 所有依赖 entry_price 的规则 `if pos.entry_price <= 0: continue` **silent skip**（[_enricher.py:52-71](backend/qm_platform/risk/sources/_enricher.py:52) + [pms.py:115](backend/qm_platform/risk/rules/pms.py:115) + [single_stock.py:138](backend/qm_platform/risk/rules/single_stock.py:138)）。
5. **LL-081 的 `>5 持仓 + >60% skip` fail-loud 守门在单仓被 100% bypass** —— 现在持仓只剩 1 股（已清仓 18），守门条件 `total_positions > 5` 不满足 → 完全 silent（[pms.py:172](backend/qm_platform/risk/rules/pms.py:172)）。

**今天 14:30 的实测证据（DB scheduler_task_log）**：
```
risk_daily_check | success | 2026-04-29 14:30:00 |
  {'status': 'ok', 'alerted': 0, 'checked': 1, 'signals': [], 'triggered': 0, ...}
```
持仓 688121.SH（卓然，-29%）—— **0 触发，0 告警，0 钉钉，risk_event_log 0 行**。

**`risk_event_log` 表建表至今总行数 = 0**（DB 实测）。Risk Framework MVP 3.1 上线 5 天，**从未真正记录过任何风控事件**——这与 CLAUDE.md "Wave 3 1/5 完结 ✅" 的庆功语严重背离。

明天若开盘暴跌 8%：系统会发 3-5 条钉钉，CB 升 L2，**0 卖出 0 降仓**（CB L2 的 `position_multiplier=1.0`，根本不降仓），次日 L2 自动恢复 L0，账户裸跌到底。详见第 7 部分逐分钟反应序列图。

---

## 第一部分：资产盘点与新旧关系图谱

### 1.1 风控系统真实文件清单（实测）

| 层 | 路径 | 行数 | 状态 |
|---|---|---|---|
| **新 Platform 层（MVP 3.1 Risk Framework）** | `backend/qm_platform/risk/` | ~1,411 | ✅ 实施 |
| ├ interface（ABC + Protocol） | `interface.py` | 209 | ✅ |
| ├ Engine 编排器 | `engine.py` | 411 | ✅ 但接占位 broker |
| ├ Position Source（Primary/Fallback） | `sources/qmt_realtime.py` + `sources/db_snapshot.py` + `sources/_enricher.py` | ~290 | ✅ |
| ├ PMSRule（L1/L2/L3） | `rules/pms.py` | 184 | ✅ action=sell 但 broker 是 stub |
| ├ CircuitBreakerRule（Hybrid adapter） | `rules/circuit_breaker.py` | 252 | ✅ action=alert_only |
| ├ IntradayPortfolioDrop3/5/8% + QMTDisconnect | `rules/intraday.py` | 224 | ✅ alert_only |
| ├ SingleStockStopLoss（4 档） | `rules/single_stock.py` | 197 | ✅ 默认 alert_only |
| ├ PositionHoldingTime（30 天） | `rules/holding_time.py` | 118 | ✅ alert_only |
| └ NewPositionVolatility（7 天 -5%） | `rules/new_position.py` | 149 | ✅ alert_only |
| **老 Service 层（部分死码 + CB Hybrid 仍在用）** | | | |
| ├ Risk Control Service（async + 1640 行 + CB 状态机） | `backend/app/services/risk_control_service.py` | 1640 | ⚠️ CB 部分仍在用 |
| ├ PMSEngine v1.0（DEPRECATED） | `backend/app/services/pms_engine.py` | ~360 | ❌ 死码但 `api/pms.py` 还在调 |
| **API 层（前端入口）** | | | |
| ├ Risk API（走 RiskControlService） | `backend/app/api/risk.py` | 520 | ⚠️ 仍走老 async service |
| └ PMS API（走死 PMSEngine） | `backend/app/api/pms.py` | 184 | ❌ 读 `position_monitor` 0 行死表 |
| **调度层** | | | |
| ├ Celery Beat schedule | `backend/app/tasks/beat_schedule.py` | 124 | ✅ 5 entries |
| ├ Daily pipeline tasks | `backend/app/tasks/daily_pipeline.py` | 700+ | ✅ |
| ├ Risk Wiring（DI 工厂） | `backend/app/services/risk_wiring.py` | 399 | ⚠️ broker 是 stub |
| └ L4 人工审批 CLI | `scripts/approve_l4.py` | 228 | ✅ |
| **数据库 schema** | | | |
| └ risk_event_log（hypertable + 90d retention） | `backend/migrations/risk_event_log.sql` | 143 | ✅ migration 已跑 |

### 1.2 文档腐烂证据

CLAUDE.md L116（项目结构）声称：
> `backend/platform/` ← MVP 1.1 Platform Skeleton

实际：`backend/platform/` **不存在**。Glob 结果为空。代码实际路径是 `backend/qm_platform/`。
全文 CLAUDE.md 多处提到 `backend/platform/risk/` —— 文档与代码两套命名。

CLAUDE.md L378（PT 状态）声称：
> Session 20 17:47 sed + Servy restart 4 服务，`/health` 返 `{"execution_mode":"live"}`

实际 backend/.env L4 实测：
```
EXECUTION_MODE=paper
```
（Session 20 cutover 之后又被改回 paper 但 CLAUDE.md 未更新——文档腐烂证据）。

### 1.3 新旧调用关系有向图

```
┌─────────────────────────────────────────────────────────────┐
│  Celery Beat (beat_schedule.py)                             │
│   ├─ 14:30 risk-daily-check                                 │
│   └─ */5 9-14 intraday-risk-check                           │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
   ┌────────────────────────────────────┐
   │  daily_pipeline.py                 │
   │   ├─ risk_daily_check_task         │
   │   └─ intraday_risk_check_task      │
   └─────┬──────────────────────────────┘
         │ build_risk_engine(extra_rules=[build_circuit_breaker_rule()])
         ▼
   ┌────────────────────────────────────┐
   │  risk_wiring.py                    │
   │   ├─ LoggingSellBroker (stub!)     │ ← ★ 死信号源头
   │   ├─ DingTalkRiskNotifier          │
   │   └─ build_risk_engine             │
   └─────┬──────────────────────────────┘
         │
         ▼
   ┌────────────────────────────────────┐
   │  qm_platform/risk/engine.py        │
   │   PlatformRiskEngine               │
   │    ├─ build_context                │
   │    ├─ run                          │
   │    └─ execute → broker.sell (stub) │
   └─────┬─────────────┬────────────────┘
         │             │
         ▼             ▼
   ┌──────────┐  ┌────────────────────┐
   │ rules/*  │  │ CircuitBreakerRule │
   │ 8 rules  │  │ (Hybrid adapter)   │
   └──────────┘  └─────┬──────────────┘
                       │ ★ 跨边界依赖
                       ▼
                 ┌─────────────────────────────┐
                 │ risk_control_service.py     │
                 │  check_circuit_breaker_sync │ ← 1640 行老 service
                 │   └─ _upsert_cb_state_sync  │
                 └─────────────────────────────┘

┌─────────────────────────────────────────┐
│ FastAPI:  /api/risk/* (api/risk.py)     │── async ──> RiskControlService (老)
│ FastAPI:  /api/pms/*  (api/pms.py)      │── sync ───> PMSEngine (老, 死码) → position_monitor (0 行)
└─────────────────────────────────────────┘
```

**关键观察**：
- 新 Engine 通过 Hybrid adapter 反向依赖老 `risk_control_service.check_circuit_breaker_sync`（铁律 31 例外，[circuit_breaker.py:8-12](backend/qm_platform/risk/rules/circuit_breaker.py:8) ADR-010 addendum）
- 没有循环依赖，但有**两套并行 cb_state 写路径**：(a) Engine.execute → _log_event → risk_event_log；(b) check_circuit_breaker_sync 内部 _upsert_cb_state_sync → circuit_breaker_state + circuit_breaker_log
- 老 PMS 仍被 FastAPI `/api/pms/*` 调用（`api/pms.py:22` 还 import `PMSEngine`），前端访问 PMS dashboard 拿到的是死表 0 行数据
- `/api/risk/*` 走 RiskControlService，与 Risk Framework Engine 绕开 — UI 看到的 cb_state 是真的，但 PMS 看到的是死表

---

## 第二部分：四大核心链路穿透测试

### 2.1 PMS 利润保护

#### 正向追踪
```
Celery Beat 14:30 →
risk_daily_check_task ([daily_pipeline.py:242](backend/app/tasks/daily_pipeline.py:242)) →
  if not settings.PMS_ENABLED: return  ← ★ single point of failure
  build_risk_engine(extra_rules=[build_circuit_breaker_rule()]) →
  engine.build_context →
    QMTPositionSource.load → 读 Redis portfolio:current → {code: shares}
    ([qmt_realtime.py:50-75](backend/qm_platform/risk/sources/qmt_realtime.py:50))
    load_entry_prices → trade_log WHERE execution_mode=settings.EXECUTION_MODE
    ([_enricher.py:31-71](backend/qm_platform/risk/sources/_enricher.py:31))  ← ★ 命名空间漂移漏点
    load_peak_prices → klines_daily MAX(close) since entry_date
    load_entry_dates → MIN(buy.trade_date) since last sell
  engine.run([PMSRule, ...]) →
    PMSRule.evaluate ([pms.py:100-183](backend/qm_platform/risk/rules/pms.py:100)):
      for pos in context.positions:
        if pos.entry_price <= 0 or peak <= 0 or current <= 0: continue  ← ★ silent skip
        unrealized_pnl = (current - entry) / entry
        drawdown = (effective_peak - current) / effective_peak
        for lvl in (L1=30%/15%, L2=20%/12%, L3=10%/10%):
          if pnl >= lvl.min_gain AND drawdown >= lvl.max_drawdown:
            triggered_level = lvl; break
        if triggered_level: results.append(RuleResult(rule_id=f"pms_l{N}", shares=pos.shares))
  engine.execute(results) →
    rule.action == "sell":  ← PMS 是唯一 sell action
      _execute_sell → broker.sell(code, shares)  ← ★ 死信号
        LoggingSellBroker.sell() returns {"status": "logged_only"}  ← ★★★ 占位
    _log_event → INSERT risk_event_log (action_taken='sell', action_result={'status': 'logged_only'})
    _notify → DingTalkRiskNotifier.send → send_alert
```

#### 反向验证："导致这个卖出动作不执行的 100 种方式"

实测可触发**沉默吞动作**的 13 个独立通道：

| # | 通道 | 文件:行 | 是否真实存在 |
|---|---|---|---|
| 1 | `LoggingSellBroker.sell()` 直接 return logged_only | [risk_wiring.py:65-79](backend/app/services/risk_wiring.py:65) | ✅ **当前** |
| 2 | `entry_price <= 0` silent continue（命名空间错位） | [pms.py:115](backend/qm_platform/risk/rules/pms.py:115) | ✅ **当前** |
| 3 | `peak_price <= 0` silent continue（无 trade_log buy 历史） | [pms.py:115](backend/qm_platform/risk/rules/pms.py:115) | ✅ |
| 4 | `current_price <= 0` silent continue（Redis market:latest 缺失） | [pms.py:115](backend/qm_platform/risk/rules/pms.py:115) | ✅ |
| 5 | `PMS_ENABLED=False` 跳过整个 task | [daily_pipeline.py:282](backend/app/tasks/daily_pipeline.py:282) | ✅ |
| 6 | 非交易日 TradingDayChecker → return | [daily_pipeline.py:276](backend/app/tasks/daily_pipeline.py:276) | ✅ |
| 7 | `get_live_strategies_for_risk_check()` 返 [] | [daily_pipeline.py:312](backend/app/tasks/daily_pipeline.py:312) | ✅ |
| 8 | `get_qmt_client().is_connected() == False` → PositionSourceError | [qmt_realtime.py:52](backend/qm_platform/risk/sources/qmt_realtime.py:52) | ✅ |
| 9 | Primary 抛 → fallback 抛 → 整 strategy 标 error，per-strategy continue | [daily_pipeline.py:400-410](backend/app/tasks/daily_pipeline.py:400) | ✅ |
| 10 | dedup 已 mark → skip execute，本次告警/卖出不执行 | [daily_pipeline.py:363-373](backend/app/tasks/daily_pipeline.py:363) | ✅ |
| 11 | `broker.sell` 抛 → silent return `{status:'sell_failed'}` 不 retry | [engine.py:256-266](backend/qm_platform/risk/engine.py:256) | ✅ |
| 12 | `risk_event_log INSERT` 失败 → log error 不 raise，事件丢失 | [engine.py:365-369](backend/qm_platform/risk/engine.py:365) | ✅ |
| 13 | LL-081 fail-loud 在 `total_positions <= 5` 时被 bypass | [pms.py:172](backend/qm_platform/risk/rules/pms.py:172) | ✅ **当前唯一持仓** |

**当前生产中至少 1+2+13 三通道叠加生效** —— 卓然 -29% 14:30 检查 0 触发的根因。

### 2.2 L1/L2 熔断（CircuitBreakerRule + check_circuit_breaker_sync）

#### 正向追踪
```
14:30 daily_pipeline → build_risk_engine(extra_rules=[CircuitBreakerRule]) →
  engine.run → CircuitBreakerRule.evaluate ([circuit_breaker.py:121-196](backend/qm_platform/risk/rules/circuit_breaker.py:121))
    conn = self._conn_factory()
    prev_level = self._read_current_level(conn, strategy_id, execution_mode)  ← 读 cb_state
    cb_result = check_circuit_breaker_sync(conn, sid, exec_date, initial_capital)
    ↓
    risk_control_service.check_circuit_breaker_sync ([risk_control_service.py:1349](backend/app/services/risk_control_service.py:1349)):
      _ensure_cb_tables_sync(conn)  ← 建表幂等
      cur.execute "SELECT ... FROM performance_series WHERE execution_mode = settings.EXECUTION_MODE"  ← ★ 又一个命名空间陷阱
      if not rows: 初始化 L0 NORMAL  ← paper 模式 perf_series 0 行 → 永远首次
      ...计算 latest_ret / rolling_5d / rolling_20d / cum_loss
      触发判定:
        L4: cum_loss < -25% → action=halt, position_mult=0.0
        L3: rolling_5d < -7% OR rolling_20d < -10% → action=reduce, mult=0.5
        L2: latest_ret < -5% → action=pause, mult=1.0  ← ★★★ L2 不降仓！
        L1: latest_ret < -3% → action=skip_rebalance, mult=1.0  ← ★★★ L1 不降仓！
      _upsert_cb_state_sync(conn, sid, new_level, ...)  ← 写 cb_state
      _insert_cb_log_sync → cb_log
      send_alert(P0/P2, ...)  ← 同步发钉钉
      return {'level':N, 'action':..., 'position_multiplier':..., 'reason':...}
    ↑
    if new_level == prev_level: return []  ← 不变化不入 risk_event_log
    if new_level > prev_level: rule_id=f"cb_escalate_l{N}", severity=P0(L≥3) or P1
    if new_level < prev_level: rule_id=f"cb_recover_l{N}", severity=P2
  engine.execute:
    rule.action == "alert_only" → 不调 broker  ← ★★★ CB 转移不卖
    _log_event → INSERT risk_event_log (action_taken='alert_only')
    _notify → 钉钉
```

#### 反向验证："导致系统在熔断状态下依然可以调仓的 100 种方式"

| # | 通道 | 证据 |
|---|---|---|
| 1 | **L1 / L2 的 `position_multiplier=1.0`** —— 熔断升级了但仓位不缩 | [risk_control_service.py:1152](backend/app/services/risk_control_service.py:1152): `CB_POSITION_MULTIPLIER = {0:1, 1:1, 2:1, 3:0.5, 4:0}` |
| 2 | L1/L2 仅靠 `signal_engine` 在 16:30 **跳过调仓** —— 但**不卖现有持仓**，下跌中持仓仍裸跌 | check_circuit_breaker_sync 返回 `action='pause'/'skip_rebalance'`，下游消费在 signal_engine |
| 3 | `EXECUTION_MODE` 命名空间漂移：performance_series WHERE execution_mode='paper' 0 行 → 永远 L0 首次运行（[risk_control_service.py:1391](backend/app/services/risk_control_service.py:1391) 已带 ADR-008 注释承认） | DB 实测：cb_state 'paper' 命名空间停留 4-20 "初始化(首次运行)" L0 |
| 4 | `_read_current_level` 历史 bug：column 名拼错 `level` vs `current_level`，`except Exception: return 0` 吞所有错 | [circuit_breaker.py:206-243](backend/qm_platform/risk/rules/circuit_breaker.py:206) Session 31 修了，但说明此函数曾 silent 返 0 |
| 5 | `circuit_breaker_log` 60 天 0 行 —— 证明 60 天内 0 次 transition（DB 实测） | psql 实测 `SELECT count FROM circuit_breaker_log WHERE created_at >= NOW() - 60d` = 0 |
| 6 | L1/L2 次日自动恢复：`exec_date > entered_date` 即 recover（[risk_control_service.py:1450](backend/app/services/risk_control_service.py:1450)）—— 即使昨天 -5% 触发 L2，今天又 -5% 不会升级到 L3 | 状态机设计本身 |
| 7 | CB 通过 `position_multiplier` 影响下游 signal_engine sizing —— 但 14:30 触发后**下次 sizing 是次日 16:30 的 DailySignal**，盘中无人执行 multiplier | 调度时序 |
| 8 | `CircuitBreakerRule.evaluate` 在 `_LAZY_IMPORT_OK == False` 时 raise ImportError → 整个 strategy 进 error 路径 → 其它规则也跟着 skip | [circuit_breaker.py:134-138](backend/qm_platform/risk/rules/circuit_breaker.py:134) |

### 2.3 L4 熔断 + 人工审批

#### 正向追踪 + 恢复步骤计数

L4 触发条件: `cum_loss < -25%`，`position_multiplier=0.0`，**name `halt`**。
但 "halt" 的执行依然是 `action=alert_only`：CB 不卖，仅设置 `position_multiplier=0` → 下游 signal_engine 看到 multiplier=0 → 16:30 不下任何单。**已有持仓继续裸跌**。

恢复路径有 **2 套**：

**A. 标准 4 步流程**（[approve_l4.py:68-105](scripts/approve_l4.py:68)）：
1. `python scripts/approve_l4.py --list` → 看 pending UUID
2. `python scripts/approve_l4.py --approve --approval-id <UUID>` → UPDATE approval_queue.status='approved'
3. **等下次 PT 执行**（次日 09:31 DailyExecute or 14:30 daily_check）
4. `check_circuit_breaker_sync` L4 恢复检查 → 看到 approval='approved' → 自动重置 cb_state.current_level=0

**B. 紧急 1 步 force-reset**（[approve_l4.py:133-191](scripts/approve_l4.py:133)）：
1. `python scripts/approve_l4.py --force-reset --reason "..."`

#### "如果周末发生灾难，周一开盘前需要多少步"

如果用户是非技术人员或任何一步漏：
- 漏 `--list` 看 UUID → 不知道 approval-id 怎么填
- 漏 conn close 或 DB 锁定 → approve_l4.py 内部 `conn.commit()` 可能 hang（[approve_l4.py:95](scripts/approve_l4.py:95)）
- 漏检查 `EXECUTION_MODE` —— **approve_l4.py:42 写死 `WHERE cbs.execution_mode='paper'`**，如果当前生产是 live，**list 会列空**！同样 `--force-reset` 第 145 行也写死 `'paper'` —— **live 模式下 force-reset 不修任何行！**（DB 已实测 cb_state 有 paper 行也有 live 行，2 行各自命名空间）
- 漏 PT 自动执行（次日 09:31 DailyExecute 当前 disabled）→ standard 流程的第 3 步永远等不到
- 漏 verify cb_state.current_level —— 用户以为审批通过就是恢复，实际 DB 状态可能仍 L4

**结论**：approve_l4.py 自身有 2 处 hardcoded 'paper' 是 LL-060 / ADR-008 命名空间问题没修干净的残留。如果当前 .env 是 paper 但 cb_state 在 live 命名空间，运维**漏掉这步会以为已审批但 PT 仍熔断**。

实测 DB：`approval_queue WHERE status='pending'` = 0 行。所以当前没有挂起的 L4 审批。

### 2.4 盘中监控（Intraday）

#### 反向验证："导致系统在熔断状态下依然可以调仓的 100 种方式"（intraday 版）

13 通道 silent skip：

| # | 通道 | 证据 |
|---|---|---|
| 1 | `prev_close_nav is None` → return [] | [intraday.py:99-104](backend/qm_platform/risk/rules/intraday.py:99) |
| 2 | `prev_close_nav <= 0` → return [] | [intraday.py:103](backend/qm_platform/risk/rules/intraday.py:103) |
| 3 | `prev_close_nav` is NaN → return [] | [intraday.py:101](backend/qm_platform/risk/rules/intraday.py:101) |
| 4 | `portfolio_nav <= 0` → return [] | [intraday.py:105](backend/qm_platform/risk/rules/intraday.py:105) |
| 5 | `portfolio_nav` is NaN → return [] | [intraday.py:105](backend/qm_platform/risk/rules/intraday.py:105) |
| 6 | `prev_close_nav` 来自 performance_series 但 .env paper 模式查 0 行 → load_prev_close_nav 返 None → 全 skip | [risk_wiring.py:205-251](backend/app/services/risk_wiring.py:205) + 命名空间陷阱 |
| 7 | `position_snapshot no rows` 抛 PositionSourceError → 整 strategy 标 error → 本次 0 触发（**今天 14:10 实测发生过**） | DB scheduler_task_log 4-29 14:10 record |
| 8 | `qmt_client.is_connected()` 错误返 True（LL-081 zombie） | [qmt_client.py:38-44](backend/app/core/qmt_client.py:38) |
| 9 | `Redis qm:risk:dedup:*` 已 mark → skip alert（rule_id 一日仅 1 alert） | [risk_wiring.py:294-307](backend/app/services/risk_wiring.py:294) |
| 10 | Beat 进程 zombie 不写 schedule.dat → ServicesHealthCheck 15 分钟才发现 | LL-074 风险持续存在 |
| 11 | Servy QuantMind-Celery + QuantMind-CeleryBeat 任一停 → intraday-risk 不跑 | LL-077 |
| 12 | `PMS_ENABLED=False` flag → 整个 intraday_risk_check 跳过 | [daily_pipeline.py:517](backend/app/tasks/daily_pipeline.py:517) |
| 13 | 节假日 TradingDayChecker → 跳过 | [daily_pipeline.py:511](backend/app/tasks/daily_pipeline.py:511) |

---

## 第三部分：边界与异常输入测试（代码追踪法）

### 3.1 PMSRule 输入边界（[pms.py:114-118](backend/qm_platform/risk/rules/pms.py:114)）

| 输入 | 行为 | 风险 |
|---|---|---|
| `current_price = None` | Position dataclass 类型 = float，None 会 raise TypeError 进 engine.run except → log + 钉钉 P1 + continue | 中 |
| `current_price = 0.0` | `current_price <= 0: continue` silent skip | **高（zombie 模式）** |
| `current_price = -1.0` | 同上 silent skip | 中 |
| `entry_price = 0.0` | silent skip（**命名空间漂移当前命中**） | **CRITICAL** |
| `entry_price = NaN` | NaN <= 0 是 False → continue 不命中 → 进入计算 → unrealized_pnl=NaN → triggered_level=None → 不触发，但**没有 NaN guard 显式拒绝** | 高 |
| Redis cache 30 min 前的旧价 | rule 没法识别 staleness，照样计算 | 高（盘中突变看不到） |

### 3.2 IntradayPortfolioDropRule（[intraday.py:95-134](backend/qm_platform/risk/rules/intraday.py:95)）

NaN 已显式 guard（`math.isfinite`）✅。其它 None/0/负数走 silent return []。**没有"前一天 NAV 缺失"告警** —— 整个表 silent。

### 3.3 CircuitBreakerRule._read_current_level（[circuit_breaker.py:225-252](backend/qm_platform/risk/rules/circuit_breaker.py:225)）

`UndefinedTable` silent_ok 返 0（首次运行 OK）✅。
其它 SQL 错（`UndefinedColumn`、连接 timeout）`raise` fail-loud ✅（Session 31 修补）。

### 3.4 Redis / QMT 完全不可用

```
qmt_client.is_connected:
  except: return False  ← [qmt_client.py:43] silent
qmt_client.get_nav:
  except: return None  ← [qmt_client.py:62-64]
qmt_client.get_prices:
  except: return {}  ← [qmt_client.py:91-93] silent
```

每一步 silent，调用方被迫 fallback：
- `is_connected=False` → QMTPositionSource.load 抛 PositionSourceError → engine 切 DBPositionSource fallback → DB 命名空间不一致**第二次失败**没有 fallback → 整 strategy error
- `get_nav` None → engine.build_context 用 `sum(shares*current)` 估算（[engine.py:174-179](backend/qm_platform/risk/engine.py:174)）—— **不含 cash, 不准**
- `get_prices` {} → enricher.build_positions current=0.0 → 全规则 silent skip

**结论**：Redis 完全可用 → silent skip ; Redis 部分缺失 → silent skip ; Redis 全断 → primary fail + fallback fail → P1 钉钉。**最危险的中间态（部分缺失）静默最深**。

---

## 第四部分：配置一致性审核

### 4.1 阈值溯源表（生产生效来源）

| 参数 | code 默认 | .env 实测 | YAML 实测 | **最终生效** | 多源风险 |
|---|---|---|---|---|---|
| `EXECUTION_MODE` | "paper" ([config.py:34](backend/app/config.py:34)) | `paper` | `mode: paper` ([pt_live.yaml:22](configs/pt_live.yaml:22)) | **paper** | ⚠️ 但 cb_state/position_snapshot 实际是 live 命名空间 → 命名空间漂移 |
| `PMS_ENABLED` | True ([config.py:46](backend/app/config.py:46)) | (未设) | true ([pt_live.yaml:41](configs/pt_live.yaml:41)) | **True** | ✅ |
| `PMS_LEVEL1_GAIN` | 0.30 | (未设) | 0.30 | **0.30** | ✅ |
| `PMS_LEVEL1_DRAWDOWN` | 0.15 | (未设) | 0.15 | **0.15** | ✅ |
| `PMS_LEVEL2_GAIN` / `PMS_LEVEL2_DRAWDOWN` | 0.20 / 0.12 | (未设) | 0.20/0.12 | **0.20/0.12** | ✅ |
| `PMS_LEVEL3_GAIN` / `PMS_LEVEL3_DRAWDOWN` | 0.10 / 0.10 | (未设) | 0.10/0.10 | **0.10/0.10** | ✅ |
| 单股止损 L1-L4 | hardcoded 0.10/0.15/0.20/0.25 ([single_stock.py:64-69](backend/qm_platform/risk/rules/single_stock.py:64)) | - | - | **hardcoded** | ⚠️ 不可调 |
| `auto_sell_l4` | False（[single_stock.py:104](backend/qm_platform/risk/rules/single_stock.py:104)） | (未设) | - | **False** | ⚠️ L4 永远 alert_only |
| Intraday 3/5/8% | hardcoded ([intraday.py:148/159/170](backend/qm_platform/risk/rules/intraday.py:148)) | - | - | **hardcoded** | ⚠️ |
| CB L1-L4 阈值 | hardcoded -3/-5/-7/-10/-25 ([risk_control_service.py:1141](backend/app/services/risk_control_service.py:1141)) | - | - | **hardcoded** | ⚠️ |
| `CB_POSITION_MULTIPLIER` | {0:1, 1:1, 2:1, 3:0.5, 4:0} ([risk_control_service.py:1152](backend/app/services/risk_control_service.py:1152)) | - | - | **hardcoded** | ⚠️ **L1/L2 不降仓 是设计而非 bug** |
| `PositionHoldingTime threshold_days` | 30（[holding_time.py:35](backend/qm_platform/risk/rules/holding_time.py:35)） | - | - | hardcoded | - |
| `NewPositionVolatility new_days/loss%` | 7 / 0.05（[new_position.py:41-42](backend/qm_platform/risk/rules/new_position.py:41)） | - | - | hardcoded | - |
| `DINGTALK_WEBHOOK_URL` | "" | 已设 | - | **set** | ✅ |
| `DINGTALK_SECRET` | "" | 空字符串 | - | **空** | ⚠️ 阿里钉钉无签名告警可能被拒 |

### 4.2 "僵尸规则" 清理 / 注册 vs Beat 入口对照

| RiskRule | 注册 | 调用入口 | 频率 |
|---|---|---|---|
| PMSRule | ✅ build_risk_engine [risk_wiring.py:176](backend/app/services/risk_wiring.py:176) | risk-daily-check 14:30 | 1/工作日 |
| SingleStockStopLossRule | ✅ build_risk_engine [risk_wiring.py:182](backend/app/services/risk_wiring.py:182) + build_intraday_risk_engine [risk_wiring.py:366](backend/app/services/risk_wiring.py:366) | 14:30 + 9-14 */5 | 73/日 |
| PositionHoldingTimeRule | ✅ build_risk_engine [risk_wiring.py:189](backend/app/services/risk_wiring.py:189) | 14:30 | 1/工作日 |
| NewPositionVolatilityRule | ✅ build_risk_engine [risk_wiring.py:190](backend/app/services/risk_wiring.py:190) | 14:30 | 1/工作日 |
| IntradayPortfolioDrop3PctRule | ✅ build_intraday_risk_engine [risk_wiring.py:359](backend/app/services/risk_wiring.py:359) | 9-14 */5 | 72/日 |
| IntradayPortfolioDrop5PctRule | ✅ [risk_wiring.py:360](backend/app/services/risk_wiring.py:360) | 同上 | 72/日 |
| IntradayPortfolioDrop8PctRule | ✅ [risk_wiring.py:361](backend/app/services/risk_wiring.py:361) | 同上 | 72/日 |
| QMTDisconnectRule | ✅ [risk_wiring.py:362](backend/app/services/risk_wiring.py:362) | 同上 | 72/日 |
| CircuitBreakerRule | ✅ build_circuit_breaker_rule [risk_wiring.py:381-398](backend/app/services/risk_wiring.py:381) → daily_pipeline 14:30 | 1/工作日 | 1/日 |

**所有 9 条规则均注册且有 Beat 入口** ✅。**没有完美但忘记注册的孤儿规则**。

---

## 第五部分：与历史血债交叉验证（实证而非推断）

### LL-063：假装健康的死码比真坏的更危险（PMS v1.0 5 重失效）

**LL 主张修复**：月度 audit + 死表 DROP + 重构入 Wave 3。

**实证当前状态**:
- DB 实测：`SELECT count(*) FROM position_monitor` = **0**（建库至今 0 行 ✅ LL-063 修复未引入新写入路径）
- DB 实测：`SELECT count(*) FROM circuit_breaker_log WHERE created_at >= NOW() - 30 days` = **0**（60 天 0 行）
- `pms_state` 表不存在（`SELECT to_regclass('pms_state')` = NULL）
- `api/pms.py:64-75` **仍读 position_monitor** → 死表查询返 0 行 → 前端 PMS history 永远空（但代码没死, 用户访问 `/api/pms/history` 看到 `count: 0`）
- `api/pms.py:131-181` `/api/pms/check` endpoint 仍走老 `PMSEngine.check_all_positions` —— **手工触发还是走死路径**

**判定**: ⚠️ **修复部分生效**。新 Risk Framework 替代了老 PMS 的 Beat 调度，但**老 API endpoint 仍在前端可调用**，UI 看到的是死数据。`api/pms.py` 应整体 deprecate 或重写走 RiskFramework。**新退化路径**：用户访问 `/pms` 前端页面拿到 0 行历史会**误以为系统从未触发过保护**——同样是"假装健康"。

### LL-074：CeleryBeat 静默死亡 + ServicesHealthCheck schtask

**LL 主张修复**：PR #74 services_healthcheck.py，每 15 min 检查 Servy 状态 + schedule.dat freshness < 10 min。

**实证当前状态**:
- 文件 `scripts/services_healthcheck.py` 存在
- DB 实测：scheduler_task_log 14 天里看不到 services_healthcheck 入口（task_name 列出有 execute_phase / signal_phase / pt_audit / risk_daily_check / intraday_risk_check / factor_health_daily / pending_monthly_rebalance / reconciliation —— **没有 services_healthcheck**）
- 这意味着：(a) services_healthcheck.py 不写 scheduler_task_log（只发钉钉告警），或 (b) 该 schtask 当前未启用

**判定**: ⚠️ **修复存在但难以验证**。需要看 Windows Task Scheduler 实际启用状态。LL-074 阶段 1 设计的进程层检查不能捕获 LL-081 应用层 zombie，PR-X3 部分弥补但又被 LL-087 部分撤销。**复合状态**：现在依赖单一 probe `portfolio:nav updated_at < 5min`。如果 sync_loop hang 但 setex 还能跑 → **probe 看不见**（zombie 通道 #2，LL-081 教训未根除）。

### LL-077：Servy 服务依赖 Beat 级联 stop

**LL 主张修复**：人工 protocol（worker restart 后必跟 Beat start）+ ServicesHealthCheck 兜底。

**实证当前状态**:
- CLAUDE.md L283-287 仍声明依赖关系
- 没有自动化 — 完全依靠人工 + 15min HealthCheck

**判定**: ✅ 文档有记录，但 **退化路径强**：人工流程 + 15min 检查 → 这 15min 内 Beat 死即所有调度链路（含风控）裸跑。

### LL-081：QMT zombie + Redis status 无 TTL

**LL 主张修复**：3 通道 PR-X1/X2/X3。

**实证当前状态**:

**PR-X1（qmt_data_service SETEX）**:
```
Redis 实测: qmt:connection_status TTL = 158（剩余）
✅ TTL 启用，sync_loop heartbeat refresh 中
```

**PR-X2（PMSRule fail-loud >5 持仓 + >60% skip）**:
```python
# pms.py:172
if (total_positions > SKIP_RATIO_MIN_POSITIONS  # 5
    and skipped_invalid_data / total_positions > SKIP_RATIO_ALERT_THRESHOLD):  # 0.6
    logger.warning(...)
```
✅ 代码在位。**但当前生产 1 持仓全 skip 时被 100% bypass**（`1 > 5` False）。**新退化路径**: 单仓清仓后规则降级回 silent。这是 PR-X2 设计的边界缺陷 —— 假设场景是 19/19 大盘 zombie，没考虑被裁到 1 持仓。

**PR-X3（services_healthcheck Redis freshness）**:
- portfolio:nav updated_at < 5min ✅ 还在
- qm:qmt:status stream check 已撤销（LL-087 修正）✅

**判定**:
- PR-X1 ✅ 真生效
- PR-X2 ⚠️ **当前持仓 1 股时实际 bypass，silent failure 重现** ← 这就是今天 14:30 0 trigger 的根因之一
- PR-X3 ✅ 但 LL-087 撤销 stream check 后仅剩 portfolio:nav 单 probe，单点

### LL-087：transition-only event ≠ heartbeat（false positive）

**LL 主张修复**：PR #113 撤销 stream check，仅留 portfolio:nav probe。

**实证当前状态**:
- `services_healthcheck.py` 不再 import stream check 代码（agent 报告确认）
- Redis 实测：portfolio:nav updated_at = 16:57 北京时间（2 分钟前 fresh）✅

**判定**: ✅ **修复生效**。但暴露了一个隐藏退化：**heartbeat 现在只剩 portfolio:nav 一道**，如果有人未来再加 stream check 就会重蹈覆辙；如果 portfolio:nav 写路径自身 hang（sync_loop 卡在 query_positions hang 但还能 setex），probe 看不见。

---

## 第六部分：审计员补充发现（指令未涵盖但极其重要）

### F-A1：`api/pms.py:131-181` 手动触发 PMS 仍走死路径，导致用户**手动检查 = 假装健康**

`/api/pms/check` POST endpoint 仍在调用 `PMSEngine.check_all_positions`（老死码），即使前端调用看似 OK，**根本没碰新 Risk Framework**。用户测试 PMS 时拿到 `triggered: 0` 不是"安全"而是"死路径不会触发"。**与 LL-063 同模式，应紧急 deprecate 此 endpoint 或改路由到新 Engine**。

### F-A2：`scripts/approve_l4.py` 写死 `execution_mode='paper'`（2 处）

[approve_l4.py:42](scripts/approve_l4.py:42) `WHERE cbs.execution_mode = 'paper'`
[approve_l4.py:145](scripts/approve_l4.py:145) `WHERE strategy_id = %s AND execution_mode = 'paper'`

如果生产是 live，**`--list` 看不到 live 状态的 pending L4，`--force-reset` 不修 live cb_state**。Session 20 cutover live 后 5 天用户没机会触发 L4 所以没暴露，但**周末灾难发生时这 2 处写死会让运维误以为已恢复但实际没动**。**与 ADR-008 D3 命名空间漂移同源未根除**。

### F-A3：`risk_event_log` 表建表至今 0 行

`SELECT count(*) FROM risk_event_log` = **0**

整个 Risk Framework MVP 3.1 上线 5 天里没记录过任何风控事件。CLAUDE.md 自夸"首次真生产触发 2026-04-27"是空头支票 —— scheduler_task_log Audit 4-29 当天 risk_daily_check 1 success / intraday 9 success，但 **alerted=0 / triggered=0** 在 result_json 里。**LL-063 三问法中"核心输出表有行吗"测试当前是红灯**。

### F-A4：CB Hybrid adapter 双写问题

[circuit_breaker.py:129-133](backend/qm_platform/risk/rules/circuit_breaker.py:129) 注释自承：
> `check_circuit_breaker_sync` 内部 L1597 也调 send_alert，本 adapter 返 RuleResult 后 Engine.execute 再调 _notify → 双钉钉告警。Sunset gate 条件 A+B+C 满足后 inline 重构时去重。当前接受此小重复（实战观察）。

**结果**: CB 升级 1 次，钉钉响 2 次。运维可能误以为升级了 2 级。

### F-A5：CircuitBreakerRule._read_current_level 显式 conn close 改 with 块异常清理

[circuit_breaker.py:140-153](backend/qm_platform/risk/rules/circuit_breaker.py:140) `try/finally conn.close()` 是 PR #61 P1 reviewer 指出的连接泄漏修复。但**异常路径**（`raise` UndefinedColumn）会触发 `finally conn.close()` —— OK。**但如果 raise 之前 conn.rollback 失败（被 contextlib.suppress 吃掉）**，连接已损坏 close 也可能泄漏。低概率但存在。

### F-A6：`risk_event_log` 90 天 retention 删除 + outbox dual-write best-effort 但**下游 consumer 没起来**

[risk_event_log.sql:81](backend/migrations/risk_event_log.sql:81) `add_retention_policy('risk_event_log', INTERVAL '90 days')`
[engine.py:357-364](backend/qm_platform/risk/engine.py:357) outbox 失败仅 ERROR log 不阻断。

**风险**: 如果某次 risk event INSERT 成功但 outbox 失败 → audit 在但下游报警系统漏 → 90 天后 audit 也被 retention 删 → 永久丢失证据。但当前 risk_event_log 0 行，问题暂未暴露。

### F-A7：dedup `qm:risk:dedup:{rule_id}:{strategy}:{mode}:{date}` Redis fail-open

[risk_wiring.py:301-307](backend/app/services/risk_wiring.py:301) Redis 失败 fail-open → "宁可误告警不漏告警"。设计 OK。

但**反向**：如果 Redis 故障 + 同一规则 5min 一次 intraday × 4-6h = 50+ 次告警风暴。**未限流**。可能压垮钉钉 webhook（阿里钉钉 20 条/min 限制）。

### F-A8：`scheduler_task_log` 包络是 Session 44（今天）才加的

之前的 task 跑没有 audit row → **Session 44 之前历史"是否真跑了"无法回溯**。CLAUDE.md 称 Monday 4-27 首次生产触发 → 实际 audit 包络 4-29 才有 → **4-27/4-28 的运行无证据**。

### F-A9：`PMS_ENABLED=False` 是 single point of failure

[daily_pipeline.py:282](backend/app/tasks/daily_pipeline.py:282)（daily 14:30）和 [daily_pipeline.py:517](backend/app/tasks/daily_pipeline.py:517)（intraday */5）**都用同一个 flag**：
```python
if not settings.PMS_ENABLED:
    logger.info("跳过")
    return
```

误改 `PMS_ENABLED=False` 一次 → 同时关闭 PMS / 单股止损 / 持仓时长 / 新仓波动 / 盘中跌幅 / QMT 断连 / CB 9 条规则全部. **应分 5 个 flag**（PMS_ENABLED / SINGLE_STOCK_ENABLED / INTRADAY_ENABLED / CB_ENABLED 等）。

### F-A10：Position dataclass 没 NaN guard

[interface.py:20-41](backend/qm_platform/risk/interface.py:20) `Position` dataclass 字段是 float，但 `__post_init__` 没拒 NaN 输入。如果 enricher 传 NaN（罕见但可能），rule 内**只显式 guard 了 IntradayPortfolioDropRule**，其他规则的 `<= 0` 检查对 NaN 不敏感（`NaN <= 0 == False`）。

### F-A11：`signal_engine` 是否消费 `position_multiplier` 未在本审计验证

CB 通过 `position_multiplier` 影响下游 signal_engine sizing。我没读 signal_engine.py 完整代码确认 multiplier=0 真的会让其不下单。**这是审计未覆盖的剩余盲区**。如果 signal_engine **不消费 multiplier**，CB 完全是装饰品。

### F-A12：钉钉 `DINGTALK_SECRET=`（空字符串）

backend/.env 实测：
```
DINGTALK_SECRET=
DINGTALK_KEYWORD=xin
```

阿里钉钉机器人有 3 种安全设置（关键词/IP白名单/签名），当前只配关键词 "xin"。**如果机器人改成签名验证模式，所有告警会被钉钉拒**。低概率但脆弱。

### F-A13：Position.holding_days = 0 全部（DB 实测）

```
('688121.SH', 4500, Decimal('10.8979'), Decimal('43425.00'), 0, 'live')
('000012.SZ', 10700, 4.52, 43121.0, 0, 'live')
... 全部 holding_days = 0
```

position_snapshot 的 `holding_days` 字段全是 0。**意味着 signal_engine 写 snapshot 时没填该字段**（默认 0）。`PositionHoldingTimeRule` 走 enricher.load_entry_dates 来源是 trade_log，不是 position_snapshot.holding_days，但前端如果显示 holding_days 会全是 0 误导。

### F-A14：测试覆盖 vs 生产覆盖 巨大 gap

`backend/tests/test_risk_engine.py` 和 `test_risk_wiring.py` 存在，agent 报告 90+ tests 全绿。但：
- 这些测试都用 mock broker / mock conn，**没测 LoggingSellBroker 实际不卖**这一最关键事实
- 没测 EXECUTION_MODE 命名空间漂移 → 0 trigger 这一场景
- 没测 1 持仓 100% skip 时 LL-081 guard 失效

**测试通过 ≠ 生产保护**。LL-063 同模式重现。

---

## 第七部分：最终判决 + 暴跌 8% 反应序列图

### 7.1 当前实盘资金的有效保护层级（截至 2026-04-29 16:00）

| 保护层 | 名义状态 | **实际有效性** |
|---|---|---|
| **PMS L1/L2/L3 阶梯利润保护** | ✅ 注册并调度 | ❌ **失效** —— 即使触发也走 LoggingSellBroker stub 不卖；当前持仓全 entry_price=0 命名空间漂移 silent skip |
| **CircuitBreaker L1/L2 暂停调仓** | ✅ 注册 | ⚠️ **部分有效** —— L1/L2 升级时仅设 `position_multiplier=1.0`（不降仓），仅靠下游 signal_engine 16:30 跳过当日调仓；**已有持仓继续裸跌**；alert_only 不卖 |
| **CircuitBreaker L3 降仓 50%** | ✅ 注册 | ⚠️ **部分有效** —— 升 L3 设 multiplier=0.5，但同样依赖 signal_engine 配合，且 alert_only 不主动卖；从 L0 直接到 L3 需 5 日 -7% 或 20 日 -10% 累积 |
| **CircuitBreaker L4 停止 + 人工审批** | ⚠️ 需手动 | ⚠️ **有效但脆弱** —— L4 触发后 multiplier=0 阻止下游下单；恢复需 4 步 + approve_l4.py 写死 'paper'，命名空间漂移可能让运维"假审批" |
| **盘中 Portfolio Drop 3/5/8% 告警** | ✅ 5 min 一次 | ⚠️ **仅告警** —— `action='alert_only'`，每日同 rule_id 仅 1 次钉钉，**不卖** |
| **QMT 断连告警** | ✅ 5 min 一次 | ⚠️ **仅告警** —— alert_only，不能下单时只能人工介入 |
| **单股止损 L1/L2/L3/L4 (-10/-15/-20/-25%)** | ✅ daily + intraday | ❌ **完全是装饰** —— `auto_sell_l4=False` 默认；即使触发 L4 也 alert_only；当前持仓 entry_price=0 命名空间漂移 silent skip |
| **新仓 7 天 -5% 早期预警** | ✅ daily | ⚠️ alert_only；命名空间漂移 entry_date=None silent skip |
| **持仓 30 天长尾警示** | ✅ daily | ⚠️ alert_only；命名空间漂移 entry_date=None silent skip |
| **PMS v1.0 老引擎（前端 /pms 页面）** | ❌ DEPRECATED | ❌ **假装运行**：API 返 0 行死表数据；用户访问看到的是 LL-063 同模式 |

**最终结论**：

> **当前真金 ¥1M 没有任何自动止损能力。**
> 整个风控系统是"钉钉告警发射器 + 数据库 row 表演 + LoggingSellBroker 笑话"。
> 唯一会**间接**减少损失的链路是 CB L3/L4 通过 `position_multiplier` 影响**次日**调仓（如果 DailyExecute schtask 启用），但当前 DailyExecute 状态是 disabled（CLAUDE.md L370）。
> 即使 DailyExecute 启用，next-day 才生效 → **盘中暴跌 0 防护**。
> 卓然 -29% 已持续 7 个交易日 + 0 risk_event_log 行 + 0 钉钉告警是这个系统当前真实保护水平的实证。

### 7.2 已知但未被修复的漏洞清单

| ID | 漏洞 | 触发条件 | 预期资金损失 |
|---|---|---|---|
| V-1 | LoggingSellBroker 占位未替换 | 任何 PMS L1/L2/L3 触发 | 浮盈丢失 = 触发线以下回撤幅度 × 仓位（无上限） |
| V-2 | EXECUTION_MODE=paper + position 是 live → entry_price=0 silent skip | 当前每天 14:30 + 每 5min | 各股全程裸跌（如卓然 -29% × 4500 股 = ¥14,306 已实测） |
| V-3 | LL-081 guard 在 1 持仓时 bypass | 任何清仓后剩 1-5 股的状态 | 100% silent，单仓下跌不告警 |
| V-4 | auto_sell_l4=False，单股 -25% 也不卖 | 任意时间任意股 -25% | 单股 -25% 起继续下跌（无下限） |
| V-5 | CB L1/L2 不降仓（mult=1.0） | 单日 -3% 或 -5% | 已有持仓继续裸跌；只有"次日不再调仓"无任何保护 |
| V-6 | CB 转移钉钉双告警（铁律 31 例外） | CB 升级时 | 误读级别（运维风险） |
| V-7 | approve_l4.py 写死 'paper' | live 模式 L4 恢复 | 运维以为已恢复但实际未动 → 持续 halt |
| V-8 | PMS_ENABLED 是 9 规则 single point | 误改 1 个 flag | 全风控关闭 |
| V-9 | api/pms.py 仍读 position_monitor 死表 | 用户查 PMS 历史 | 假装健康（无直接资金损失但误导决策） |
| V-10 | scheduler_task_log 包络 4-29 才加 | 历史回溯需求 | 无法证明 4-27/4-28 是否真跑 |
| V-11 | dedup 24h TTL，盘中突变 2 次跌穿同一阈值 | 反弹后再跌 | 第二次跌穿不再告警 |
| V-12 | DINGTALK_SECRET=空 | 钉钉机器人改签名模式 | 全告警被拒 |
| V-13 | risk_event_log 90 天 retention + outbox best-effort | event INSERT 后 outbox 失败 | 90 天后 audit 也被删，永久丢失证据 |
| V-14 | RuleResult.action='sell' 但 broker stub | 永久 | 永远不卖 |
| V-15 | dedup Redis 故障时 fail-open 但无限流 | Redis 故障 + 持续触发 | 钉钉风暴 (20/min 上限) |

### 7.3 暴跌 8% 反应序列图（精确到分钟）

**前置假设**：明天 09:30 集合竞价完成后，组合（19 持仓）瞬间 -8%。当前 .env=paper / EXECUTION_MODE=paper / persistence=live 命名空间不匹配状态保持。PT 当前已被用户清仓只剩 1 股（实际状况）—— 但为了演示风控**能否**保护一个完整组合，下面假设组合恢复到 19 股 live 模式（用户未来重启 PT 后的常态）。

```
T-1 (4-29 收盘):
  performance_series[trade_date=4-29, mode=live].nav = ¥1,000,000 (假设)
  Redis: portfolio:nav.total_value = ¥1,000,000
  cb_state[mode='live'].current_level = 0 (NORMAL)
  qmt:connection_status = 'connected' (TTL=120s, sync_loop refresh)

09:00:00 -- intraday-risk-check 第1次跑 (盘前)
  ├─ TradingDayChecker: True ✓
  ├─ PMS_ENABLED=True ✓
  ├─ build_intraday_risk_engine
  ├─ build_context: Redis portfolio:current 19 持仓
  │   load_prev_close_nav('live') = 1,000,000 ✓
  ├─ context: portfolio_nav=1,000,000, prev_close=1,000,000
  ├─ run rules:
  │   IntradayDrop3/5/8% → drop_pct=0 → []
  │   QMTDisconnect → is_connected=True → []
  │   SingleStockStopLoss → 各股开盘前价格未变 → []
  └─ result: triggered=0, alerted=0  ✓ silent (期望)

09:30:00 -- 集合竞价完成. 组合 -8% 瞬间.
  Redis sync_loop (60s 周期):
    09:30:30 sync_once → query_asset → portfolio:nav 写入 {total=920000, cash=...}
    09:30:30 setex qmt:connection_status TTL=120s
    09:30:30 setex market:latest:* 各股新价

09:35:00 -- intraday-risk-check 第2次 (盘中首次)
  ├─ build_context: portfolio_nav=920000, prev_close=1000000
  ├─ run rules:
  │   IntradayDrop3PctRule: drop_pct = -8% < -3% → 触发 P2 RuleResult
  │   IntradayDrop5PctRule: -8% < -5% → 触发 P1 RuleResult
  │   IntradayDrop8PctRule: -8% < -8% → 触发 P0 RuleResult
  │   QMTDisconnect → []
  │   SingleStockStopLoss: 各股 -8% 还没到 -10% L1 阈值 → []
  ├─ dedup: rule_id 'intraday_portfolio_drop_3pct'/'5pct'/'8pct' 同 strategy 同日首次
  │   should_alert all True → execute all 3
  ├─ engine.execute:
  │   每个 rule.action='alert_only':
  │     _log_event → INSERT risk_event_log × 3
  │     _notify → DingTalkRiskNotifier.send × 3
  │   broker.sell 调用次数 = 0  ★★★ 0 卖
  │   dedup mark_alerted × 3
  └─ result: triggered=3, alerted=3
  ★ 钉钉收到 3 条告警: P0 / P1 / P2
  ★ 持仓 0 变化, NAV 仍 920k

09:40:00 -- intraday-risk-check 第3次
  ├─ 同样触发 3 rules
  ├─ dedup: 已 mark → should_alert all False → skip execute
  └─ result: triggered=3, alerted=0  (silent)
  ★ 钉钉无消息 (dedup 抑制 24h)

10:00:00 -- 假设持仓继续跌, 个股开始 -10%
  intraday-risk-check 第6次 (盘中第5次)
  ├─ IntradayDrop8PctRule 已 dedup 抑制
  │ (即使现在到 -10% 也不会再发)
  ├─ SingleStockStopLossRule: 多股 loss=-10% <= -10% L1 → 触发多个 RuleResult
  │   rule_id='single_stock_stoploss_l1' (同一 rule_id)
  │   evaluate 每股 break L4→L3→L2→L1 反序, 命中 L1 即停
  │   返回 N 个 RuleResult (每股一个)
  ├─ dedup: rule_id='single_stock_stoploss_l1' 同 strategy 同日首次 → execute
  │   注意 dedup key 不含 code → **第一只股触发 mark 后, 同日同 rule_id 其他股都不再发**
  │   ☆☆☆ 这是 dedup 的设计缺陷 — 同一 rule_id 多股触发只发首只
  ├─ engine.execute first stock:
  │   action='alert_only' (auto_sell_l4=False, L1 anyway alert_only)
  │   _notify → 1 钉钉
  │   broker.sell 调用 0
  │   dedup mark
  └─ 后续 19 股的 L1 触发 silent
  ★ 钉钉收到 1 条 P2 单股 -10%
  ★ 0 卖

11:30:00 -- 持仓深跌 -15%
  SingleStockStopLossRule:
    rule_id='single_stock_stoploss_l2' 同日首次 → 1 alert
    L1 已 dedup 抑制
  ★ 钉钉 +1 条 P1 单股 -15%

13:00:00 -- 盘后跳水 -20%
  SingleStockStopLossRule:
    rule_id='single_stock_stoploss_l3' 同日首次 → 1 alert P0
  ★ 钉钉 +1 条 P0 单股 -20%

14:00:00 -- -25% 跌幅
  SingleStockStopLossRule:
    rule_id='single_stock_stoploss_l4'
    auto_sell_l4=False → effective_action='alert_only'
    shares=0 (因 effective_action='alert_only' → result_shares=0)
    1 alert P0
  ★ 钉钉 +1 条 P0 单股 -25%
  ★ 0 broker.sell

14:30:00 -- risk-daily-check
  ├─ build_risk_engine + CircuitBreakerRule
  ├─ build_context: live 命名空间 → entry_price 来自 trade_log live ✓
  ├─ run:
  │   PMSRule: 各股全部 -25% 没浮盈 → 不触发
  │   SingleStockStopLossRule: 同上, dedup 抑制 (盘中已 mark)
  │   PositionHoldingTimeRule: 持仓 7 天 < 30 → []
  │   NewPositionVolatilityRule: 7 天 + -25% < -5% → 触发 (假设刚买)
  │     dedup 'new_position_volatility' 首次 → 1 alert P1
  │   CircuitBreakerRule:
  │     check_circuit_breaker_sync(execution_mode='live'):
  │       SELECT FROM performance_series WHERE mode='live' → 4-29 nav=1M, ret=0
  │       (假设今天 14:30 还没写当日 perf_series → latest 仍是 4-29)
  │       cum_loss = (1M / 1M) - 1 = 0  ← 还没看到今天暴跌
  │       L4: 0 < -25%? No
  │       L3: rolling 5d/20d ? (依赖历史, 可能 No 因为 5d 历史没那么差)
  │       L2: latest_ret < -5%? latest 是 4-29 数据, 不是今天
  │       L1: latest_ret < -3%? No
  │       triggered_level = 0 → no escalate
  │     return [] (no transition)
  │   ☆☆☆ 14:30 时 performance_series 还没今天的数据 (16:30 才写)
  │     → CB 看不到暴跌 → 不升级 → 装饰品
  ├─ engine.execute → 1 alert (NewPositionVolatility)
  └─ ★ 钉钉 +1 条 P1
  ★ 0 broker.sell

14:55:00 -- intraday-risk-check 最后一次. 同样 dedup 抑制. 0 新告警.

15:00:00 收盘. NAV ¥750k (假设跌到 -25%).

16:30:00 -- DailySignal task (signal_engine.py)
  写 performance_series[trade_date=今天, mode='live'].nav=750000, daily_return=-25%
  signal_engine 计算下一日组合
  ↑ 此时 cb_state.current_level 还是 0 (14:30 没升)
  → signal_engine 不知道有 CB 限制
  → 计算正常的下一日 weight

17:35:00 -- pt_audit
  发现 NAV -25% 写 finding, 钉钉告警 P0
  但 audit 不卖

次日 09:00 -- intraday-risk-check 第1次 (新一日, dedup key 含日期 → 重置)
  build_context: prev_close_nav=750000, portfolio_nav=750000 (假设隔夜不变)
  drop_pct=0 → 0 触发

次日 14:30 -- risk-daily-check
  CircuitBreakerRule:
    check_circuit_breaker_sync:
      SELECT performance_series → 看到昨天的 -25% daily_return
      L4: cum_loss = -25% < -25%? No (=不严格小于). 假设 cum_loss=-24.9% → No
        若 cum_loss < -25%, 触发 L4: position_multiplier=0
      L3: rolling 5d 包含 -25% → 5d 累计大概 -25% < -7% Yes → 触发 L3
        position_multiplier=0.5
      或 L2: latest_ret=-25% < -5% Yes → L2, but L3 优先 (上面 elif L3 优先于 L2)
      → triggered_level=3
      _upsert_cb_state_sync(level=3, ..., position_multiplier=0.5)
      send_alert P0
      log to circuit_breaker_log
    return {'level': 3, 'position_multiplier': 0.5, ...}
    rule_id='cb_escalate_l3', severity=P0
  ├─ engine.execute → action='alert_only'
  │   _log_event → INSERT risk_event_log
  │   _notify → 钉钉 (★ 双钉钉问题: send_alert + _notify 两次)
  │   broker.sell 调用 0
  ★ 0 broker.sell, 但 cb_state.current_level 写为 3
  ★ position_multiplier=0.5

次日 16:30 -- DailySignal task
  signal_engine 检查 cb_state → L3, mult=0.5
  如果 signal_engine 真消费 multiplier (F-A11 待验证):
    target weights × 0.5 → 仓位减半
    生成卖单 (50% 仓位 sell)
  signal 写入 signals 表

次日次日 (T+2) 09:31 -- DailyExecute task
  ★ 当前 schtask 是 disabled → 不执行
  即使启用, 也是 T+2 早上才真正下卖单
  ★ 从 T 暴跌 8% → T+2 才有 broker.sell 真发生
  ★ 从触发到执行延迟 ~ 19 小时
  ★ 在此期间持仓 0 减仓
```

### 7.4 资金保护判决

> **会被一枪爆头还是被保护？**
>
> **结论：会被一枪爆头。**
>
> 在 09:30 -8% 暴跌发生时：
> - 09:35-14:55 盘中：发 5-7 条钉钉告警，**0 卖出，0 减仓**
> - 14:30 daily check：因 performance_series 当日未写，CB 看不到暴跌 → 不升级
> - 16:30 signal 任务：写当日 perf_series；signal_engine 是否消费 multiplier 未验证（F-A11 盲区）
> - 17:35 pt_audit：发 P0 finding；不卖
> - **次日 14:30 才真升 CB L3/L4**
> - **次日 16:30 才生成减仓信号**
> - **T+2 09:31 才真发卖单**（且当前 DailyExecute 是 disabled，需手动启用）
>
> **从暴跌到第一个 broker.sell 调用的最快路径 = T+2 早上 ≈ 19 小时延迟**。
>
> 这 19 小时里持仓**完全裸露在市场**。如果继续跌到 -15%、-20%，系统的反应仍只是"多发几条钉钉 + 数据库 row 升级"，**broker.sell 调用次数 = 0**。
>
> **唯一真有效的资金保护是 CB L4 在次日通过 `position_multiplier=0` 阻止下游再下单**——但这只是"不再加仓"，不是"卖出止损"。
>
> 当前真金 ¥1M（实际只剩 1 股 ¥43k）已用 7 个交易日 + 卓然 -29% + risk_event_log 0 行的实证证明这个判决。
>
> **如果用户期望系统在暴跌时能自动止损，当前架构在三层独立设计上根本不允许这件事发生**：
> 1. 唯一会调 broker.sell 的规则 PMSRule 要求先有浮盈（亏损场景永不触发）
> 2. 即使触发，broker 是 LoggingSellBroker stub
> 3. 即使 broker 是真的，命名空间漂移让 entry_price=0 silent skip
> 4. 即使 entry_price 不是 0，1 持仓状态下 LL-081 guard bypass 完全 silent
>
> **这是一个被错觉成"风控系统"的 audit log 系统。** 文档（CLAUDE.md / LL-081 / Wave 3 1/5 完结 ✅）每一条都说"正常"——这就是 LL-063 "假装健康的死码比真坏的更危险" 升级为整个 Risk Framework 范围。

---

## 第八部分：紧急修复优先级（如要恢复 PT live）

下列动作**必须在重启 PT live 之前完成**，否则 V-1/V-2/V-3/V-4/V-7 任一**单独**会导致下次暴跌时再来一次卓然。

| 优先级 | 动作 | 文件 | 耗时 |
|---|---|---|---|
| **P0-阻断** | 实现 `QMTSellBroker` 替换 `LoggingSellBroker` 或显式将 PMSRule.action 改为 `alert_only` 让"会卖"的口径与现实一致 | risk_wiring.py:54-79 | 0.5-2 天 |
| **P0-阻断** | 修 ADR-008 命名空间漂移：要么 .env=live + 全部 mode=live 数据；要么 build_context 强制读 'live' 持仓而不论 settings.EXECUTION_MODE | _enricher.py + check_circuit_breaker_sync L1391 | 1 天 |
| **P0-阻断** | LL-081 guard bypass 修：`SKIP_RATIO_MIN_POSITIONS` 改 0 或加 `or total_positions == 1 + skip_ratio==1.0` 单仓全 skip 也告警 | pms.py:172 | 5 分钟 |
| **P0-阻断** | approve_l4.py 2 处 hardcoded 'paper' → 接受 `--execution-mode` 参数 | approve_l4.py:42 + L145 | 10 分钟 |
| **P1** | `auto_sell_l4=True` 默认（当 -25% 时真卖） | risk_wiring.py 注入或 single_stock.py:104 | 5 分钟 |
| **P1** | 拆分 PMS_ENABLED single point：增 SINGLE_STOCK_ENABLED / INTRADAY_ENABLED / CB_ENABLED 各自 flag | daily_pipeline.py:282 + 517 | 30 分钟 |
| **P1** | `api/pms.py` 整体 deprecate 或重写走新 RiskFramework 不读 position_monitor 死表 | api/pms.py | 1-2 小时 |
| **P1** | CB 双钉钉去重（[circuit_breaker.py:129-133](backend/qm_platform/risk/rules/circuit_breaker.py:129) TODO） | check_circuit_breaker_sync 内 send_alert 移除 OR adapter skip _notify | 30 分钟 |
| **P2** | dedup key 加 code 维度（避免单一 rule_id 多股触发只发首只） | risk_wiring.py:286-292 | 15 分钟 |
| **P2** | dedup Redis 故障 fail-open 加令牌桶限流（< 5 钉钉/min） | risk_wiring.py | 1 小时 |
| **P2** | DINGTALK_SECRET 启用签名验证（防机器人改设置后告警全拒） | .env + 钉钉控制台 | 30 分钟 |
| **P3** | scheduler_task_log 包络回填 4-27/4-28 历史无 audit 缺口 | 一次性脚本 | 1 小时 |

---

**审计员声明**: 本报告所有结论基于实测代码 + DB 查询 + Redis 实测 + 配置文件读取 + LESSONS_LEARNED 交叉对比。所有文件路径与行号在 2026-04-29 16:30 北京时间核实。审计未覆盖的盲区已在 F-A11 显式声明（signal_engine 是否消费 position_multiplier 需另行验证）。

**审计员忠告**: 在 P0 全部修复 + 一个完整持仓在合成场景跑过 1 次真 broker.sell 之前，**禁止 PT live 重启**。当前文档（CLAUDE.md / LL-081 修复声明 / Wave 3 ✅）的"已恢复"声明是文字游戏；DB `risk_event_log = 0` 是事实。
