# Live-Mode 激活路径扫描 — 2026-04-29 (D2)

> **范围**: 切 `.env EXECUTION_MODE=paper→live` 后哪些路径会激活 + 副作用 + 切前安全检查
> **触发**: 批 1.5 完成 (PR #151), main @ `bc8bad4`. 用户决策 A/B/C 前需要扫描激活路径
> **方法**: 实测代码读 + 实测 DB + 实测 schtask/Servy/Beat 当前激活状态 (沿用批 1.5 LL-XXX: audit 概括必须实测纠错)
> **审计员**: AI 自主, 用户 0 接触
> **铁律**: 25 (改什么读什么) / 33 (fail-loud) / 34 (SSOT) / 36 (precondition) / 40 (test debt)

---

## 📋 执行摘要

| 检查 | 状态 | 关键数字 |
|---|---|---|
| **11 题诊断** | ✅ 全过 | Q1-Q11 全 ✅, 1 项重大新发现 (intraday_monitor hardcoded override) |
| **EXECUTION_MODE 全分布** | ✅ | 27 文件 EXECUTION_MODE / 50+ 文件 hardcoded 'live'/'paper' / **总 ~200+ hits** |
| **DB 命名空间状态** | ✅ 实测 | position_snapshot live=**295** paper=**0** / trade_log 30d live=68 paper=20 / cb_state live=L0(4-28) paper=L0(4-20 stale) |
| **Beat 当前激活清单** | ✅ 4 项 | gp-weekly + outbox-publisher + quality-report + factor-lifecycle (risk Beat 2 paused) |
| **Schtask 当前激活清单** | ✅ 12 ready / 5 disabled | DailyExecute / DailySignal / IntradayMonitor / DailyReconciliation / CancelStaleOrders 全 disabled |
| **broker_qmt LIVE_TRADING_DISABLED guard** | ✅ 已激活 | place_order:415 + cancel_order:482 双因素 OVERRIDE 才放行 |
| **写路径漂移修复状态** | ❌ 未修 | pt_qmt_state.py 7 处 hardcoded 'live' 仍存 (留批 2) |
| **隐藏 hardcoded override** | ⚠️ **新发现** | scripts/intraday_monitor.py:141 `os.environ["EXECUTION_MODE"]="live"` 强制覆盖 .env (但 schtask Disabled) |

**风险等级总评**: 🟡 **可控** — 切 .env=live 后 broker guard 已盖真金, startup 断言 pass (live in DB), 但写路径漂移源头未修 (碰巧对齐 .env=live 了所以"看起来"无事). 切 live 不解决根因, 只是消除"驰高 vs DB"显象.

**A/B/C 推荐**: **C (等批 2)** > A (.env→live) > B (paper+SKIP). 详见 §11.

---

## ✅ 11 题逐答

### Q1 — EXECUTION_MODE 全分布

**✅ 通过** — grep 实测命中数:

| 模式 | grep 命中数 | 文件数 |
|---|---|---|
| `EXECUTION_MODE` (常量名) | ~50 hits | 27 files |
| `execution_mode\s*==?\s*['"]live['"]\|paper['"]` | ~120 hits | 50+ files |
| `execution_mode\s*=\s*['"]live['"]\|paper['"]` (赋值) | 包含上 | 同上 |

**总命中**: ~200 hits 跨 70+ files (含 archive / tests / scripts / backend).

**主要分布** (顶 10 文件 by hits):
1. `scripts/archive/simulate_1year_paper.py` — 14 hits (archived, dormant)
2. `backend/app/services/pms_engine.py` — 9 hits (DEPRECATED per ADR-010, dormant)
3. `scripts/check_graduation.py` — 8 hits (live tool, ad-hoc)
4. `scripts/daily_reconciliation.py` — 11 hits (schtask Disabled, dormant)
5. `backend/app/services/pt_qmt_state.py` — 7 hits (生产写路径, **未修漂移**)
6. `backend/app/services/realtime_data_service.py` — 5 hits (FastAPI live)
7. `backend/app/services/signal_service.py` — 6 hits (Beat/Schtask 触发)
8. `scripts/pt_audit.py` — 4 hits (schtask Ready)
9. `scripts/repair/restore_snapshot_20260417.py` — 6 hits (one-shot repair, dormant)
10. `backend/app/services/paper_trading_service.py` — 11 hits (FastAPI paper API endpoint)

详见 §Q2 6 大分类完整命中表.

### Q2 — 6 大分类 (按副作用)

**✅ 通过** — 分类如下 (主要文件汇总, 非 archive/tests):

| 类别 | 副作用 | 命中文件 | 切 live 后行为 |
|---|---|---|---|
| 🔴 **真金路径** | 调真实 broker.order_stock | `backend/engines/broker_qmt.py:415-416` (place_order)<br>`backend/engines/broker_qmt.py:482-489` (cancel_order)<br>`backend/engines/qmt_execution_adapter.py` (调 broker_qmt) | LIVE_TRADING_DISABLED guard 拦截, 双因素 OVERRIDE 才放行 (见 Q7) |
| 🟡 **写关键表** (生产链路) | INSERT/UPDATE/DELETE position_snapshot / trade_log / performance_series / cb_state / risk_event_log | `backend/app/services/pt_qmt_state.py:158, 171, 197, 214` (5 处 hardcoded 'live')<br>`backend/app/services/execution_service.py:124, 146, 311` (live branch 走 _execute_live)<br>`backend/app/services/risk_control_service.py` (cb_state UPSERT)<br>`backend/qm_platform/risk/engine.py:307` (risk_event_log + outbox dual-write) | **写仍 hardcoded 'live'** — 即使 .env=paper 写也是 'live' 命名空间 (这就是漂移源头, 留批 2) |
| 🟠 **读状态决定行为** | 根据 mode 选 SELECT 命名空间 | `backend/app/services/signal_service.py:217, 249, 363-368` (beta / broker / pos_snap)<br>`backend/app/tasks/daily_pipeline.py:289, 524` (risk_check / intraday_risk_check)<br>`backend/qm_platform/risk/sources/db.py` (DBPositionSource.load) | 切 .env=live 后, 读路径走 'live' 命名空间, 与写路径漂移自然对齐 (carry-over from prior session) |
| 🟢 **数据采集 / 对账** | 读/写 reconciliation (日终对账) | `scripts/daily_reconciliation.py` (11 hits hardcoded 'live')<br>`backend/app/services/qmt_reconciliation_service.py:79, 111` | schtask **Disabled**, 即使 .env=live 也不跑. 留批 2/3 评估 reenable. |
| ⚪ **配置 / 日志 / 注释** | 不影响行为 | `backend/app/config.py:12` (Pydantic field)<br>`backend/.env` (key/value)<br>注释 / docstring 中 'live' 字符串 | 0 副作用 |
| ❓ **隐藏 hardcoded override** | **绕过 .env 强制设 live** | **scripts/intraday_monitor.py:141 `os.environ["EXECUTION_MODE"] = "live"`** | ⚠️ **新发现 — schtask Disabled, 但 reenable 后会强制 live 覆盖 .env**, 详见 §Q9 Finding A |

### Q3 — 激活时序 (a-f)

**✅ 通过** — 6 时序覆盖每条 🔴 / 🟡 命中:

| 时序 | 触发条件 | 涉及命中 | 切 live 后激活? |
|---|---|---|---|
| (a) **立即激活** | FastAPI/Worker 启动那一刻 | startup_assertions (BLOCK if drift) | ✅ — 启动断言会重新核 (见 Q5) |
| (b) **Beat 触发** | Celery Beat 周期到 | gp-weekly / outbox-publisher / quality-report / factor-lifecycle | 🟢 4 项 Beat 都不直接调 broker (gp 周日 22:00 仅训练 / outbox 30s 发 Redis / quality_report 数据巡检 / factor_lifecycle 改 factor_registry status) |
| (c) **Schtask 触发** | Windows Task Scheduler | 12 ready / 5 disabled (见 Q8) | ⚠️ DailyIC / DailyMoneyflow / DataQualityCheck / FactorHealthDaily / IcRolling / PTAudit / PT_Watchdog / RiskFrameworkHealth / ServicesHealthCheck — 全部读路径或非真金, 切 live 不立即触发真金 |
| (d) **API 触发** | FastAPI endpoint 被 HTTP 调 | execution_ops.py:204-248 (3 处 'live' SQL)<br>realtime_data_service.py:400-471 (5 处 'live' SQL) | ⚪ 默认无定时 cron 调 API. 用户/前端手工调时才走. |
| (e) **手工脚本** | 用户手工 python 触发 | emergency_close_all_positions.py / approve_l4.py / pt_audit.py | ⚪ 用户手工时才跑 (按需触发, 仍受 LIVE_TRADING_DISABLED guard 保护) |
| (f) **永久 dormant** | 代码存在但当前不可达 | scripts/archive/* (16+ files)<br>pms_engine.py (DEPRECATED per ADR-010)<br>daily_reconciliation.py (schtask Disabled)<br>scripts/diag/* (one-shot tools) | ⚪ 切 live 不影响 |

### Q4 — 写路径漂移当前状态 (实测)

**❌ 未修** — 与上轮 STATUS_REPORT (批 1) 描述一致, **批 1 + 链路停止 PR + 批 1.5 全未触动写路径**:

#### pt_qmt_state.py 7 处仍 hardcoded 'live' (实测验证)

| 行 | 操作 | SQL 片段 |
|---|---|---|
| L46 | SELECT prev pos_snap | `WHERE strategy_id = %s AND execution_mode = 'live' AND trade_date < %s` |
| L55 | SELECT count current pos_snap | `WHERE strategy_id = %s AND execution_mode = 'live' AND trade_date = %s AND quantity > 0` |
| L147 | SELECT trade_log avg_cost | `WHERE strategy_id = %s AND execution_mode = 'live' AND direction = 'buy' AND code IN (...)` |
| L158 | DELETE position_snapshot | `WHERE trade_date = %s AND execution_mode = 'live' AND strategy_id = %s` |
| L171 | INSERT position_snapshot | `VALUES (..., 'live')` literal |
| L197 | SELECT MAX(nav) perf_series | `WHERE execution_mode = 'live' AND strategy_id = %s` |
| L214 | INSERT performance_series | `VALUES (..., 'live')` literal |

#### execution_service.py 写路径 (mode-aware 但仍含 hardcoded)

- L124 `if execution_mode == "live"`: L1 cb 触发 P1 send_alert (no DB write)
- L146 `if execution_mode == "live"`: routes to `_execute_live(...)` (调 QMTExecutionAdapter → broker_qmt.place_order)
- L311 注释: "写trade_log（live模式用execution_mode='live'标记）" — 实际 INSERT 走 broker._save_live_fills, 通过参数传 mode

#### 影响判定

- **当前 .env=paper 状态**: pt_qmt_state.save_qmt_state 在 paper 启动下仍写 live 命名空间 → 这就是 ADR-008 漂移根因.
- **切 .env=live 后**: 写仍是 'live' (一直如此), 读路径 (signal_service.py:368) 会改成 'live' (settings.EXECUTION_MODE 动态), 写读自然对齐 — **看起来"漂移消失了"实际是碰巧, 不是根治**.
- **批 2 修法**: pt_qmt_state.py 改 hardcoded → settings.EXECUTION_MODE 参数化, 测试用 4 contract tests xfail strict 守门 (test_execution_mode_isolation.py L573-578).

### Q5 — 启动断言切 live 后行为 (实测)

**✅ 通过** — 实测 startup_assertions.py L97-103 + L105-111:

| 场景 | env_mode | DB modes | 行为 |
|---|---|---|---|
| 当前 (.env=paper) | "paper" | {"live": 295} | ❌ **BLOCK 启动** (env_mode 不在 db_modes keys) — 当前 Servy 重启如不带 SKIP_NAMESPACE_ASSERT=1 会 fail-loud |
| 切 .env=live | "live" | {"live": 295} | ✅ **pass** ("live" in {"live": 295} → return) |
| 极端: paper + DB 仍残留 paper trade_log | "paper" | (position_snapshot 30d 不含 paper) | ❌ **BLOCK** (因 trade_log 不参与断言, 仅 position_snapshot 30d) |

**结论**: 切 .env=live 立即可消解启动断言阻塞. 当前 paper 模式必须 `SKIP_NAMESPACE_ASSERT=1` 或迁数据.

**实测命令** (read-only, 0 改动):
```bash
PGPASSWORD=quantmind D:/pgsql/bin/psql.exe -U xin -d quantmind_v2 -tA -c \
  "SELECT execution_mode, COUNT(*) FROM position_snapshot WHERE trade_date >= CURRENT_DATE - INTERVAL '30 days' GROUP BY 1"
# 返: live|295
```

### Q6 — Paper-mode 残留状态盘点

**⚠️ 部分孤儿** — 切 .env=live 后这些 paper 数据成 dormant orphan, 不影响生产链路:

| 表 | 命名空间 | 行数 | 时间 | 切 live 后影响 |
|---|---|---|---|---|
| position_snapshot | paper (30d) | **0** | — | ⚪ 已清, 0 影响 |
| trade_log | paper (30d) | **20** | 4-16 only | ⚪ 4-16 batch_3.4 paper signal write, 历史归档. 读路径 (paper_trading_service.py) 仍可见, 但 PT 切 live 后不查 |
| circuit_breaker_state | paper L0 | **1** | 4-20 16:30 (stale 9 days) | ⚠️ orphan. 当前 cb_state lookup by execution_mode 时如果有代码走 paper 命名空间会读到这个 stale L0. 需 verify (见 Q9) |
| performance_series | paper | TBD (待查) | — | ⚪ paper_trading_service API 仍可读, 切 live 后 PT 不查 |
| signals | paper (跨模式共享) | 默认 hardcoded 'paper' | 持续 | ✅ 设计如此 (ADR-008 D3-KEEP, signal_service.py:336) — 跨模式共享, 不算孤儿 |

**结论**: 孤儿无生产影响, 但 cb_state paper L0 stale 是隐患, 切 live 后任何走 paper 命名空间的代码 (如某些 ad-hoc tools) 会读 stale L0 → 误判恢复. 留批 2/3 清理.

### Q7 — broker_qmt LIVE_TRADING_DISABLED guard 实测

**✅ 完全激活** — 实测 broker_qmt.py:

```python
# L407-416 place_order:
"""
Raises:
    LiveTradingDisabledError: 真金保护激活 (T1 sprint link-pause).
        双因素 OVERRIDE 才允许 bypass.
"""
self._ensure_connected()
# L412-416
from app.security.live_trading_guard import assert_live_trading_allowed
assert_live_trading_allowed(operation="place_order", code=code)
from xtquant import xtconstant
# ... 后续 _trader.order_stock 才被调
```

```python
# L482+ cancel_order: 同样 assert_live_trading_allowed(operation="cancel_order", ...)
```

**guard 行为** (live_trading_guard.py 实测):
- **不依赖 EXECUTION_MODE** — 只看 settings.LIVE_TRADING_DISABLED 默认 True
- 切 .env=live 不会 disarm guard. 必须 (a) 改 LIVE_TRADING_DISABLED=false 或 (b) 设双因素 OVERRIDE (FORCE_OVERRIDE=1 + REASON 非空)
- guard 触发: raise LiveTradingDisabledError + audit + 钉钉 P0 (sanitize markdown)

**回归测试覆盖** (`test_live_trading_disabled.py` 14 unit + SAST):
- TestAllXtquantOrderCallsGuarded SAST 全 codebase scan `_trader.order_stock`
- 实测 grep `_trader.order_stock` only `broker_qmt.py:463` 一处, 其他无绕道

**结论**: 真金路径 100% 盖. 切 .env=live 仍受 guard 拦截, 必须显式 OVERRIDE 才能下单.

### Q8 — Beat / Schtask 当前激活清单 (实测)

**✅ 完整** — 实测如下:

#### Celery Beat (实测 beat_schedule.py)

| Task | Schedule | State | 触发副作用 |
|---|---|---|---|
| `gp-weekly-mining` | 周日 22:00 | ✅ Active | GP 因子挖掘, 写 pipeline_runs / factor_registry, 不调 broker, 不写关键交易表 |
| `outbox-publisher-tick` | 每 30s | ✅ Active | 读 event_outbox WHERE published_at IS NULL → publish Redis Streams (qm:risk:* / qm:fill:* / qm:signal:*), 标记 published_at. **写关键 outbox 表**, 但 mode 不敏感 (跨 paper/live 共享 outbox). 切 live 不影响. |
| `daily-quality-report` | 工作日 17:40 | ✅ Active | 数据巡检, 读 factor_values + klines_daily 完整性. 不调 broker, 不写关键交易表. |
| `factor-lifecycle-weekly` | 周五 19:00 | ✅ Active | factor_registry status 转换 (active↔warning), 不涉 mode |
| `risk-daily-check` | 14:30 工作日 | ❌ **PAUSED** (T1 sprint link-pause PR #150) | 撤销见 link_paused_2026_04_29.md |
| `intraday-risk-check` | `*/5 9-14` 工作日 | ❌ **PAUSED** (同上) | 同上 |

**Beat 切 live 行为**: 4 个 Active Beat **均不调 broker**, **均不直接写 trade_log/position_snapshot**. 仅 outbox-publisher-tick 写 outbox (mode-agnostic). 安全.

#### Windows Task Scheduler (实测 PowerShell Get-ScheduledTask)

**Ready (12)** — 切 live 后会触发:

| Task | 触发时间 | 副作用 (切 live 后) |
|---|---|---|
| `QuantMind_DailyIC` | 工作日 18:00 | 写 factor_ic_history (mode 无关) |
| `QuantMind_DailyMoneyflow` | 工作日 17:30 | 拉 moneyflow 数据 (mode 无关) |
| `QuantMind_DataQualityCheck` | 工作日 17:45 | 数据巡检 (mode 无关) |
| `QuantMind_FactorHealthDaily` | 工作日 (TBD 时间) | factor 健康检查 (mode 无关) |
| `QuantMind_IcRolling` | 工作日 18:15 | ic_ma20/60 rolling 刷新 (mode 无关) |
| `QuantMind_MiniQMT_AutoStart` | 启动时 | 启动 miniQMT 客户端 (无 DB 写) |
| `QuantMind_MVP31SunsetMonitor` | 周日 04:00 | 监控 risk-daily-check / intraday Beat 是否激活 (mode 无关) |
| `QuantMind_PTAudit` | 工作日 17:35 | **读 'live' 命名空间** (pt_audit.py:269,282,339,484), 5-check 主动守门, 失败发钉钉 |
| `QuantMind_PT_Watchdog` | 持续 | 心跳监控 (mode 无关) |
| `QuantMind_RiskFrameworkHealth` | TBD | risk framework 健康检查 |
| `QuantMind_ServicesHealthCheck` | TBD | servy 服务健康检查 (mode 无关) |
| `QuantMind_DailyReconciliation` | (Disabled) | — |

**Disabled (5)** — 切 live 仍不触发:

- `QuantMind_DailyExecute` — **核心真金风险** (09:31 调用 run_paper_trading.execute_phase). Disabled = 切 live 后**仍不会** 09:31 自动下单
- `QuantMind_DailySignal` — 16:30 信号生成. Disabled = 切 live 后无新 signals 生成
- `QuantMind_DailyReconciliation` — 17:00 对账. Disabled = 切 live 后无对账写入
- `QuantMind_CancelStaleOrders` — 紧急撤单. Disabled = 切 live 后无自动撤单
- `QuantMind_IntradayMonitor` — 5min 盘中监控. Disabled = ⚠️ 详见 §Q9 Finding A

**结论**: 切 live 后 schtask Ready 12 项仅 PTAudit 读 'live' 命名空间会有变化 (从读"空 paper" 到 "295 row live"); 5 个真金/写路径 schtask 全 Disabled, **不会自动激活**, 必须用户手工 enable 才能触发真金链路.

### Q9 — signal_engine + execute_phase 链路实测

**✅ 通过** — 实测如下:

#### signal_service.py 路径

- L217 `calc_portfolio_beta(execution_mode=settings.EXECUTION_MODE, ...)` — beta 监控只读 perf_series, 不写
- L249 `PaperBroker(execution_mode=settings.EXECUTION_MODE)` — 切 live 后 PaperBroker init 用 live, 但**实际写路径走 _execute_live → QMTExecutionAdapter → broker_qmt.place_order** (受 LIVE_TRADING_DISABLED guard 保护)
- L336 `WHERE ... execution_mode = 'paper'` (signals SELECT) — **ADR-008 D3-KEEP 有意保持 'paper' hardcoded** (signals 表跨模式共享前端契约)
- L363-368 `position_snapshot SELECT` 用动态 settings.EXECUTION_MODE — 切 live 后读 'live' 命名空间正确

#### daily_pipeline.py risk_check / intraday_risk_check

- L289, L524 `execution_mode = settings.EXECUTION_MODE` — 切 live 后 risk engine context 用 'live'. 但 Beat 已 PAUSED, 这条不会触发. 切 live 不会 unpause Beat.
- L342 `engine = build_risk_engine(extra_rules=[build_circuit_breaker_rule()])` — 当前 Beat PAUSED, 不调

#### scripts/run_paper_trading.py (execute_phase)

- L309: hardcoded `WHERE ... execution_mode='paper'` (legacy) — 实测后续走 settings.EXECUTION_MODE 路径, L309 仅一处
- 整个 script 由 schtask `QuantMind_DailyExecute` 09:31 触发, **schtask Disabled** → 切 live 不自动激活

#### ⚠️ Finding A — scripts/intraday_monitor.py:141 hidden hardcoded override

```python
# Line 139-142:
# 设置环境让qmt_manager识别live模式
os.environ["EXECUTION_MODE"] = "live"
from engines.broker_qmt import MiniQMTBroker
```

**问题**: 此 script 在运行时**强制覆盖 EXECUTION_MODE = "live"**, 绕过 .env 设置. 即使 .env=paper, 此 script 启动后 settings.EXECUTION_MODE 读到 "live" (但 settings 是模块级 cached, 实际 effect 取决于 settings 读取时序).

**当前状态**: schtask `QuantMind_IntradayMonitor` **Disabled**, 不触发. 但任何用户手工 `python scripts/intraday_monitor.py` 都会强制 live, 风险盲点.

**修法建议** (留批 2/3): 删除 L141 hardcoded, 用 LiveTradingDisabledError guard 拦截或纯 read-only 监控.

### Q10 — API endpoint 风险盘点

**✅ 通过** — 实测 backend/app/api/:

| Endpoint | 文件:行 | 副作用 | auth gate? |
|---|---|---|---|
| `/api/execution/sell-position` | execution_ops.py (POST) | 调 broker → place_order (受 LIVE_TRADING_DISABLED guard 拦截) | ⚠️ 实测需 verify (见下) |
| `/api/execution/buy` | execution_ops.py (POST) | 同上 | 同上 |
| `/api/execution/positions` | execution_ops.py:204 | SELECT WHERE execution_mode='live' AND quantity > 0 (read-only) | 通常无 auth 但 read-only 安全 |
| `/api/execution/asset` | execution_ops.py:248 | SELECT WHERE execution_mode='live' (read-only) | read-only 安全 |
| `/api/realtime/*` | realtime_data_service.py:400-471 | SELECT WHERE execution_mode='live' (5 处, read-only) | read-only 安全 |
| `/api/paper-trading/*` | paper_trading.py:240, 261 | hardcoded execution_mode='paper' (paper API, 物理隔离) | 无影响 |

**Auth gate 实测建议** (留下次 audit): 验证 sell/buy endpoint 是否要求 admin token. 当前未实测.

**结论**: read-only endpoint 切 live 后只是从读 "空 paper" 切到读 "295 live", **数据展示一致性更好**. 写路径 endpoint (sell/buy) 受 LIVE_TRADING_DISABLED guard 保护, 即使切 live 也不能下单.

### Q11 — 切 live 安全清单 (4 类)

**✅ 通过** — 基于 Q1-Q10 实测综合:

#### (a) 必须先 disable 才能切 live 的路径

**当前状态**: ✅ **已 disable / paused** (链路停止 PR + schtask manual disable):

- ✅ `risk-daily-check` Beat — paused (注释)
- ✅ `intraday-risk-check` Beat — paused (注释)
- ✅ `QuantMind_DailyExecute` schtask — disabled
- ✅ `QuantMind_DailySignal` schtask — disabled
- ✅ `QuantMind_DailyReconciliation` schtask — disabled
- ✅ `QuantMind_IntradayMonitor` schtask — disabled
- ✅ `QuantMind_CancelStaleOrders` schtask — disabled
- ✅ broker_qmt.place_order/cancel_order — LIVE_TRADING_DISABLED guard 默认拦截

**已就位**: 切 live 不需额外操作. **不能切 live 的路径已悉数 disable**.

#### (b) 可以立即激活的路径 (切 live 后 0 风险或受保护)

| 路径 | 风险评估 |
|---|---|
| FastAPI 启动 (lifespan) | startup_assertions pass (.env=live + DB 295 live) |
| Beat: outbox-publisher-tick (30s) | mode-agnostic, 0 风险 |
| Beat: gp-weekly-mining (周日 22:00) | mode-agnostic, 0 风险 |
| Beat: daily-quality-report (17:40 工作日) | mode-agnostic, 0 风险 |
| Beat: factor-lifecycle-weekly (周五 19:00) | mode-agnostic, 0 风险 |
| Schtask 12 ready (Ready 但 mode 无关或 read-only) | 0 风险 |
| API: /api/execution/positions / asset / realtime/* | read-only 'live' 命名空间, 数据显示更准 |

#### (c) 激活但需观察的路径

| 路径 | 观察点 |
|---|---|
| `QuantMind_PTAudit` (17:35 工作日) | 切 live 后从 paper → live 命名空间. 需 verify 5-check 不误报 (DB 4-28 live cb L0 + 4-29 paper cb L0 stale 共存) |
| API: /api/execution/sell-position / buy (HTTP) | 受 LIVE_TRADING_DISABLED guard 保护, 但需 verify auth gate 防滥用 |
| pt_qmt_state.save_qmt_state (写路径漂移源头) | 即使 .env=live 也仍 hardcoded 'live'. 留批 2 修. **当前是"碰巧对齐"不是修复**. |
| paper namespace orphans (cb_state paper L0 stale, trade_log 4-16 paper 20 行) | 任何走 paper namespace 的 ad-hoc tool 会读 stale 数据. 留批 2/3 清理. |

#### (d) 永久 dormant 的路径 (切 live 不影响)

- `scripts/archive/*` (16+ files) — 全部 archive, 0 触发
- `backend/app/services/pms_engine.py` — DEPRECATED per ADR-010 (PMSRule 已迁 risk framework, 老 pms_engine 物理删除留批 3)
- `scripts/repair/restore_snapshot_20260417.py` — one-shot repair tool, 0 触发
- `scripts/diag/f19_*` (one-shot diag) — 0 触发
- `scripts/bayesian_slippage_calibration.py` — research tool, manual run only

---

## ⚠️ 3 项重大新发现

### Finding A — scripts/intraday_monitor.py:141 hidden hardcoded override

详见 §Q9. `os.environ["EXECUTION_MODE"] = "live"` 在 script 入口强制覆盖 .env. 当前 schtask Disabled, 但隐患:
- 用户手工 `python scripts/intraday_monitor.py` 会立即激活 live
- 任何 future schtask reenable 都会绕过 .env 切 live

**修法**: 留批 2/3 (删 L141 hardcoded 或加 guard).

### Finding B — pt_qmt_state.py 写路径漂移仍未修

Q4 已实测验证. 批 1 / 链路停止 / 批 1.5 全未触动. **真金风险已被 LIVE_TRADING_DISABLED guard 盖**, 但**漂移源头** (写仍 hardcoded 'live') **持续**, 切 .env=live 只是"碰巧对齐"不是根治.

**修法**: 批 2 必修 (pt_qmt_state.py 5 处 hardcoded → settings.EXECUTION_MODE).

### Finding C — circuit_breaker_state paper L0 stale orphan (4-20 16:30)

DB 实测: cb_state has live=L0 (4-28) + paper=L0 (4-20 stale 9 days). paper 行从 Session 20 cutover 时遗留, 链路停止 PR 后无人写 paper namespace, stale 持续.

**影响**: 任何读 cb_state by execution_mode='paper' 的 ad-hoc tool 会读 stale L0, 误判 "no breaker". 主链路 (build_risk_engine) 用 settings.EXECUTION_MODE 动态读, 切 live 后不再读 paper → orphan dormant.

**修法**: 留批 2/3 清理 (DELETE FROM cb_state WHERE execution_mode='paper' OR archive table).

---

## 🚨 风险等级总评

| 维度 | 风险 | 等级 |
|---|---|---|
| 真金保护 (broker.place_order / cancel_order) | LIVE_TRADING_DISABLED guard 默认 True, 双因素 OVERRIDE 才放行 | 🟢 0 风险 |
| schtask 自动激活真金路径 | DailyExecute / IntradayMonitor / DailySignal / DailyReconciliation / CancelStaleOrders 全 Disabled | 🟢 0 风险 |
| Beat 自动激活真金路径 | risk-daily / intraday-risk Beat 已 PAUSED. 4 active Beat 均不调 broker | 🟢 0 风险 |
| 启动断言 | 切 live 后立即 pass (live 在 DB 295) | 🟢 0 风险 |
| 写路径漂移 (pt_qmt_state hardcoded 'live') | 切 live 后碰巧对齐, 但**根因未修**. 实施批 2 之前任何回切 paper 都会再次触发漂移 | 🟡 P2 风险 (需批 2 根治) |
| paper namespace orphans (cb_state / trade_log 4-16) | dormant, 不影响主链路, 但 ad-hoc tool 会读 stale | 🟡 P3 风险 |
| **scripts/intraday_monitor.py:141 hardcoded override** | schtask Disabled 但用户手工/reenable 会绕过 .env | 🟡 P2 风险 (留批 2/3) |
| API endpoint sell/buy auth gate | 待 audit (本 D2 未实测) | ⚪ 待评估 |

**总评**: 🟡 **可控** — 切 .env=live 后**真金风险 0** (broker guard + 5 schtask Disabled), 主要风险是**写路径漂移根因仍存** + **scripts/intraday_monitor 隐藏 override**. 这些是 P2/P3, 不阻断切 live, 留批 2/3 治理.

---

## 🛤️ A/B/C 路径推荐

### 推荐排序: **C > A > B**

#### 推荐 C — 等批 2 完成 (.env 保 paper + SKIP_NAMESPACE_ASSERT=1)

**理由**:
- 当前 .env=paper, 启动断言会 BLOCK. 但 SKIP bypass 后 FastAPI/Worker 能正常启动
- 真金不会触发 (broker guard + schtask Disabled)
- PT 已暂停 (用户决策), 不需要 .env=live 来对齐生产
- **批 2 修写路径漂移 → 根治 ADR-008 命名空间问题** > "切 .env=live 碰巧对齐"
- 切 live 后任何回切 paper 都会立即重新触发漂移 (因为写仍 hardcoded 'live')

**反对意见 (最强)**:
- DB 已全 live, .env=paper 是"假装 paper", 误导未来 onboarding 工程师
- SKIP bypass 是临时, 长期保留违反铁律 33 (silent failure)
- ad-hoc tool (paper_trading_status.py 等) 在 paper namespace 读 0 行, 用户体验差

**反驳**: 这些是接受的临时成本. 批 2 ETA ~1 周, 期间用 SKIP bypass + 用户清楚 PT 已停, 无运维事故.

#### 备选 A — 切 .env=live (NOT recommended now)

**适用场景**: 如果用户决定**立即重启 PT live** (与批 2 并行). 但 PT 重启 gate 仍剩 (paper-mode 5d dry-run 未做).

**理由**:
- startup 断言立即通过, FastAPI/Worker 干净重启
- 写读路径自动对齐 (写仍 hardcoded live, 读用 settings.EXECUTION_MODE=live)
- API endpoint 显示数据正确 (live 命名空间)

**反对意见 (最强, 阻断)**:
- 切 live 不修写路径漂移根因. **看起来无事 ≠ 修了**.
- 任何后续操作要回 paper (e.g. PT 暂停 + .env=paper 测试场景) 都会立即重新触发漂移
- LL-XXX 教训: "audit 概括必须实测代码纠错". 切 live 不是修复, 是 workaround.

**结论**: 仅在 PT 重启决策同步进行时才推荐. 单独切 live 是 false positive, 不解决根因.

#### 备选 B — 保 paper + SKIP_NAMESPACE_ASSERT=1 (Servy User env)

**当前状态**: 推测目前已实施 (用户已 .env 改回 paper, FastAPI 必须 bypass 才能启动).

**理由**: 临时应急. 与 C 等价 (C 的实施手段就是 B).

**反对意见**: SKIP bypass 是 emergency override, 不应长期保留 (违反铁律 33 fail-loud 精神). 但批 2 ETA 短, 接受.

**结论**: B 是 C 的实施手段, 不是独立路径. 真正决策是 C (等批 2) vs A (立即切 live).

---

## 📦 finding 清单 (N 题外)

### finding 1: 链路停止 PR 后 risk-daily-check Beat 暂停状态正确

beat_schedule.py L66-73 + L77-84 注释完整, 含 PAUSE T1_SPRINT_2026_04_29 标记 + 撤销链接到 link_paused_2026_04_29.md. 与 STATUS_REPORT (link_pause) 描述一致, ✅.

### finding 2: factor-lifecycle-weekly Beat 周五 19:00 - 切 live 影响

切 live 后 factor-lifecycle 仍跑 (与 mode 无关), 但批 1.5 baseline 已观察 dv_ttm warning. 切 live 后下次 (本周五 5-2 19:00) lifecycle 跑会刷新 ic_ma20/60 ratio. 留观察.

### finding 3: signal_service.py:336 hardcoded 'paper' 是 ADR-008 D3-KEEP 有意设计

实测验证 + test_execution_mode_isolation.py:471 守门契约: "D3 破契约: signal_service.py get_latest_signals 必须保留 execution_mode='paper'". 不算漂移, 是有意设计 (signals 表跨模式共享前端 UI).

### finding 4: outbox-publisher-tick 30s 频率 vs T1 sprint 静默期

outbox-publisher-tick 仍 active 30s 跑, 但 risk-daily-check Beat PAUSED 后无 risk_event 入队列, outbox publisher 实际 SELECT 几乎总返 0 行. 0 风险, 但 expires=25 配置 (30s 周期内 25s 过期) 留观察 — 长期空跑 OK.

### finding 5: 4 留 fail (批 1.5) 状态依赖类未修

D2 不修, 留批 2/3:
- test_factor_determinism (DB cache flaky)
- test_factor_health_daily x2 (DB / scheduler_task_log 状态依赖)
- test_services_healthcheck.test_all_ok (env-flake)

切 live / 不切 live 都不影响这 4 个 fail.

### LL 候选 (沿用批 1.5 LL-XXX): D2 自身的 audit 也应实测验证

本 D2 自身就是 audit 性质. 已应用 LL-XXX 教训:
- ✅ 不凭代码外观判定 ("看到 if mode=='live' 不代表它会跑")
- ✅ 实测 schtask state (PowerShell Get-ScheduledTask) + Beat 注释 + DB SQL 查
- ✅ 任何 "看起来" / "应该" → 实测证据替换

但 D2 报告自身的 一阶概括 (如 "4 active Beat 均不调 broker") 在批 2 实施时仍应再 verify (e.g. outbox publisher 是否真 0 broker 调用) — D2 报告是当前实测快照, 非永久真理.

---

## 🚀 下一步建议

### (a) 路径决策对话

用户根据 §11 推荐做 A/B/C 决策. 建议选 **C** (等批 2). 如选 A 需配套 PT 重启评估 (paper-mode 5d dry-run + .env paper→live cutover).

### (b) 启批 2 (写路径漂移消除)

**Scope**:
- pt_qmt_state.py 7 处 hardcoded 'live' → settings.EXECUTION_MODE 参数化
- execution_service.py:311 注释验证 (实际写已用参数, 注释更新)
- daily_reconciliation.py 11 处 hardcoded 'live' (schtask Disabled 但 future reenable 时需修)
- intraday_monitor.py:141 删 hardcoded override + 加 guard
- LoggingSellBroker → QMTSellBroker 替换 (Risk Framework 真 broker, 留批 2 PR 2)
- xfail strict 4 contract tests 转 PASS (test_execution_mode_isolation.py:471, 573-578)

**预估**: 2-3 天 (不含真金 cutover, 仅写路径修)

### (c) 启全方位审计 13 维 (D2 是审计的子集)

D2 是 13 维审计中"激活路径维度"的子集. 完整审计还包括:
- 数据完整性 (factor_values 158G + minute_bars 21G + klines)
- 测试覆盖 (4127 collected / 3955 pass)
- 文档腐烂 (CLAUDE.md / SYSTEM_STATUS / blueprint)
- API auth gate
- Servy 服务依赖图
- Redis 缓存命名空间
- 监控告警 (钉钉 / DingTalk)
- ... 等 13 维

如要启 13 维审计, 是 1 周级任务, 建议批 2 后再启.

### (d) 4 留 fail 清理

留批 2/3 与 §11 写路径漂移修同批进行 (DB/状态依赖类测试).

---

## 📂 附产物清单

- [docs/audit/live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md) — 本文档 (主产物)
- [docs/audit/STATUS_REPORT_2026_04_29_D2.md](STATUS_REPORT_2026_04_29_D2.md) — D2 整体执行报告 (整体审计)
- 0 commit / 0 push / 0 PR (纯诊断, 0 改动)

---

> **状态**: D2 阶段 ✅ **完整完成** — 11 题诊断 + 6 大分类完整命中表 + 切 live 安全清单 + A/B/C 推荐 + 3 finding (新发现).
> **关键发现**: scripts/intraday_monitor.py:141 hidden hardcoded override + pt_qmt_state.py 7 处写路径漂移仍未修 + cb_state paper L0 stale orphan.
> **风险评估**: 🟡 可控 — 切 .env=live 后真金 0 风险 (guard + schtask), 但写路径根因未修.
> **推荐**: C (等批 2 完成) > A (.env→live, 仅 PT 重启时) > B (保 paper + SKIP, 临时手段).
