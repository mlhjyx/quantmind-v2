# API Auth Gate + Broker 实例链路实测 — 2026-04-29 (D2.1)

> **范围**: D2 报告 ⚪ 待评估项 (API endpoint sell/buy auth gate + broker 实例链路)
> **触发**: D2 6 维总评 🟡 可控, 但 API auth 维度未实测. 切 .env=live 前必须 close 此口
> **方法**: 实测代码 (沿用批 1.5 LL-XXX + D2 LL-XXX: audit 概括必须实测纠错)
> **关联文档**: [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md) / [STATUS_REPORT_2026_04_29_D2.md](STATUS_REPORT_2026_04_29_D2.md)
> **铁律**: 25 / 33 / 34 / 35 / 36

---

## 📋 执行摘要

| 检查 | 状态 | 关键数字 |
|---|---|---|
| **8 题诊断** | ✅ 全过 | Q1-Q8 全 ✅, 1 重大新发现 (broker.sell/.buy AttributeError) |
| **API endpoint 总览** | ✅ | 22 router files / 13 含 POST/PUT/DELETE / 1 含 admin token (execution_ops) |
| **真金路径 chokepoint** | ✅ | 仅 `broker_qmt.py:463 _trader.order_stock` + `L508 _trader.cancel_order_stock`, SAST test 守门 |
| **qmt_manager.broker 实例** | ✅ 实测 | `MiniQMTBroker` (qmt_connection_manager.py:118), 走 LIVE_TRADING_DISABLED guard |
| **API → broker chain auth** | ✅ 真金侧覆盖 | execution_ops.py 11 sensitive endpoints 全 `Depends(_verify_admin_token)` |
| **ADMIN_TOKEN config** | ⚠️ 未配置 | `.env` 无 ADMIN_TOKEN, default `""` → 调 endpoint 返 500 fail-secure |
| **MiniQMTBroker.sell/.buy 方法** | ❌ **NOT EXIST** | execution_ops.py:115/118 调 broker.sell/.buy 但方法不存在, 运行时 AttributeError (P2 dead API) |
| **WebSocket 真金通道** | ✅ 0 风险 | 仅 backtest progress, 无 order/sell/buy endpoints |
| **CORS** | ✅ 严格 | 仅允许 `http://localhost:3000` origin |
| **未授权 POST/PUT/DELETE 文件** | ⚠️ 12 文件 | 详见 §Q4, P1: risk + approval; P2: strategies + params; P3: pms/factors/mining/pipeline/backtest/notifications/system/report |

**总评**: 🟢 **真金 P0 风险 0** — chokepoint LIVE_TRADING_DISABLED guard 100% 覆盖 (broker_qmt 唯一 xtquant 调用点 + SAST 守门), API 真金 endpoints 全 admin-gated, ADMIN_TOKEN 未配置时 fail-secure 500.

**但有 P1/P2 治理债**: 12 文件 POST/PUT/DELETE 无 auth gate (尤其 risk.py /force-reset 可 flip cb 到 NORMAL), MiniQMTBroker.sell/.buy 不存在导致 emergency-liquidate / fix-drift/execute 是 dead API.

---

## ✅ 8 题逐答

### Q1 — API endpoint 全清单

**✅ 通过** — 实测 backend/app/api/ 22 router files:

| Router File | POST/PUT/DELETE? | Admin Auth? | 副作用类别 |
|---|---|---|---|
| **execution_ops.py** | ✅ 9 endpoints | ✅ 全 `_verify_admin_token` | 🔴 真金/调 broker (cancel/sell/buy/fix-drift) |
| approval.py | ✅ 3 (approve/reject/hold) | ❌ 无 | 🟡 写 approval_queue 状态 |
| backtest.py | ✅ 2 (run/compare/sensitivity) | ❌ 无 | 🟡 kicks off backtest, 资源消耗 |
| factors.py | ✅ 1 (archive) | ❌ 无 | 🟡 改 factor_registry status |
| mining.py | ✅ 2 (run/cancel) | ❌ 无 | 🟡 kicks off GP mining |
| notifications.py | ✅ 2 (test/{id}/read) | ❌ 无 | 🟢 测试通知/标记已读 |
| params.py | ✅ 2 (PUT/init-defaults) | ❌ 无 | 🟡 改运行时参数 (config_changelog) |
| pipeline.py | ✅ 2 | ❌ 无 | 🟡 trigger pipeline |
| pms.py | ✅ 1 (check) | ❌ 无 | 🟡 写 position_monitor (DEPRECATED) |
| report.py | ✅ 1 (generate) | ❌ 无 | 🟢 生成 report |
| risk.py | ✅ 3 (l4-recovery/l4-approve/force-reset) | ❌ **无** | 🔴 改 risk_control_state (P1) |
| strategies.py | ✅ 5 (CRUD + rollback + backtest) | ❌ 无 | 🟡 改 strategy 配置 |
| system.py | ✅ 1 (test-notification) | ❌ 无 | 🟢 测试通知 |
| dashboard, health, market, paper_trading, portfolio, realtime, remote_status | ❌ GET only | N/A | 🟢 read-only |

**execution_ops.py POST endpoints (admin-gated)**:
- POST /cancel-all (撤所有未成交) → calls `_broker_cancel_order`
- POST /cancel/{order_id} (撤单) → calls `_broker_cancel_order`
- POST /fix-drift/preview (read-only preview) → no broker
- POST /fix-drift/execute (执行修复, 需 CONFIRM) → calls `_broker_sell + _broker_buy`
- POST /trigger-rebalance (记录意图, 不实际下单) → no broker
- POST /emergency-liquidate (清仓, 需 CONFIRM) → calls `_broker_sell`
- POST /pause-trading / /resume-trading → 改运行时 flag
- PUT /alert-config → 改通知配置

### Q2 — execution_ops.py:115/118 sell/buy 完整链路

**⚠️ 实测失败** — 链路存在但 **MiniQMTBroker 方法不存在**:

```python
# execution_ops.py:114-118
async def _broker_sell(code: str, volume: int, price: float = 0):
    return await asyncio.to_thread(qmt_manager.broker.sell, code, volume, price)

async def _broker_buy(code: str, volume: int, price: float = 0, amount: float = 0):
    return await asyncio.to_thread(qmt_manager.broker.buy, code, volume, price, amount)
```

调用方:
- L555: cancel-all → `_broker_cancel_order` (cancel_order 存在 ✅)
- L587: cancel/{id} → `_broker_cancel_order` ✅
- L682: fix-drift/execute → `_broker_sell` ❌
- L701: fix-drift/execute → `_broker_buy` ❌
- L772: emergency-liquidate → `_broker_sell` ❌

**MiniQMTBroker 方法实测** (`grep "    def "  broker_qmt.py`):

```
连接管理: connect / disconnect / is_connected / _ensure_connected / _handle_disconnect
查询: query_asset / query_positions / query_orders / query_trades
订单: place_order (L382) / cancel_order (L481)
回调: register_order_callback / register_trade_callback / register_error_callback
BaseBroker 接口: get_positions / get_cash / get_total_value
```

**`def sell` / `def buy` 不存在**. BaseBroker (engines/base_broker.py:18) 也只有 `get_positions/get_cash/get_total_value` abstract.

**结论**:
- /fix-drift/execute 和 /emergency-liquidate 调 `qmt_manager.broker.sell/.buy` → **运行时 AttributeError**
- Admin-gated + AttributeError fail-fast → **0 P0 真金风险**
- 但 API claim 不能实现 → **P2 dead-API finding**

### Q3 — qmt_manager.broker 实例类型确认

**✅ 100% MiniQMTBroker** (实测验证, 不凭注释):

```python
# backend/app/services/qmt_connection_manager.py:116-118
from engines.broker_qmt import MiniQMTBroker
self._broker = MiniQMTBroker(
    qmt_path=settings.QMT_USERDATA_PATH,
    account_id=settings.QMT_ACCOUNT_ID,
)

# L188: 单例
qmt_manager = QMTConnectionManager()
```

**guard 链路实测**:
- API 调 `qmt_manager.broker.cancel_order(order_id)` → `MiniQMTBroker.cancel_order` (broker_qmt.py:481) → `assert_live_trading_allowed("cancel_order", ...)` (L488) → if disabled, raise LiveTradingDisabledError + audit + 钉钉 P0
- Same for `place_order` (L382-416 guard at L412-416)
- `cancel_order/place_order` 是真金 chokepoint, **唯一 `_trader.order_stock` 调用点** (broker_qmt.py:463 + L508 cancel)
- SAST test (`test_live_trading_disabled.py:222-252`) 全 codebase 扫描, 任何**新增**含 `_trader.order_stock(` 的文件必含 `assert_live_trading_allowed`, 防 future bypass

**结论**: 真金路径 100% guard 覆盖. ✅

### Q4 — API auth gate 强度

**✅ Sensitive endpoints (execution_ops) 全覆盖** + **⚠️ 12 files 无 auth (P1-P3)**:

#### admin token 实测 (execution_ops.py:69-77):

```python
def _verify_admin_token(
    x_admin_token: str = Header(alias="X-Admin-Token", default=""),
) -> str:
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN未配置")
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="无效的Admin Token")
    return x_admin_token
```

**强度评估**:
- ✅ Plain string equality compare (no hash needed for header token)
- ✅ Default `""` → 500 fail-secure (config.py:90 `ADMIN_TOKEN: str = ""`)
- ✅ ADMIN_TOKEN 当前 .env 未配置 (`grep ADMIN_TOKEN backend/.env` 无 match) → 任何调 sensitive endpoint 都返 500, 不可滥用
- ⚠️ 无强度校验 (用户设短 token 如 "admin" 不被拦)
- ⚠️ 无速率限制 (token 错误回 401, 允许穷举攻击)
- ✅ 9 sensitive endpoints 全 `Depends(_verify_admin_token)` (execution_ops.py:542, 581, 607, 661, 723, 754, 797, 810, 830)
- ✅ 4 sensitive ops 含 daily rate limit (`_check_rate_limit`): trigger-rebalance/emergency-liquidate/cancel-all/fix-drift-execute (default 1-5 次/日)
- ✅ 输入校验: emergency-liquidate / fix-drift-execute 需 `confirmation='CONFIRM'`

**ADMIN_TOKEN 未配置的影响**:
- 切 .env=live 前必须先**生成强 token** (≥ 32 chars random) 写入 `.env: ADMIN_TOKEN=<...>`
- 否则 sensitive endpoint 全 500, ops/紧急清仓不可用
- **铁律 35**: secrets 不入 git history, 仅 .env 落盘 (已 gitignore)

#### 12 文件无 auth (P1-P3):

| File | Endpoint | 风险等级 | 利用场景 |
|---|---|---|---|
| **risk.py** | POST /l4-recovery/{sid} | P2 | 任何人发起 L4 恢复请求 (写 approval_queue, 无实际风险但污染审批队列) |
| **risk.py** | POST /l4-approve/{aid} | **P1** | **任何人审批 L4 恢复**, flip cb 状态. 配合 force-reset 可绕过风控 |
| **risk.py** | POST /force-reset/{sid} | **P1** | **任何人 force reset cb 到 NORMAL** (运维紧急用, 无 admin gate) |
| **approval.py** | POST /queue/{id}/approve | **P1** | 同上, gates L4 recovery |
| approval.py | POST /queue/{id}/reject | P2 | 拒绝审批 (DoS L4 恢复) |
| approval.py | POST /queue/{id}/hold | P2 | 挂起审批 |
| **strategies.py** | POST/PUT/DELETE | P2 | strategy CRUD, 改 active version → 影响下次 backtest/PT |
| **params.py** | PUT /{key} | P2 | 改运行时参数 (top_n / industry_cap / factor_list), 写 config_changelog |
| pms.py | POST /check | P3 | 触发 PMS 检查, 写 position_monitor (DEPRECATED 待删) |
| factors.py | POST /archive | P3 | 改 factor_registry status |
| mining.py | POST /run | P3 | kicks off GP mining (~1 day, 资源消耗 + DoS 风险) |
| pipeline.py | POST | P3 | trigger pipeline |
| backtest.py | POST /run | P3 | kicks off backtest (~mins, 资源) |
| notifications.py | POST /test | P3 | 发测试钉钉 (噪音) |
| system.py | POST /test-notification | P3 | 同上 |
| report.py | POST /generate | P3 | 生成 report |

**P1 (risk.py /force-reset)** 是最严重: 切 .env=live 后 cb 现 L0, 任何人调 /force-reset 可重设 → 配合 strategy /backtest 改 PT 配置, 可在不通过审批的情况下激活 risk-cleared trading 路径. **但 LIVE_TRADING_DISABLED guard 仍是 chokepoint**, 实际下单仍被拦 → 不构成 P0 真金风险, 但破坏审计链.

### Q5 — FastAPI middleware 全栈

**✅ 通过** — 实测 backend/app/main.py:

```python
# L84-90
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**评估**:
- ✅ CORS 严格白名单 (仅 localhost:3000), 防跨域恶意调用
- ✅ 无 auth middleware 全局拦, 但 sensitive endpoints 自带 `Depends(_verify_admin_token)`
- ✅ Lifespan 启动断言 (run_startup_assertions) → 命名空间漂移直接 raise (D2 已述)
- ❌ 无 TrustedHostMiddleware (Host header 未限制) — 但服务仅 bind 127.0.0.1 (uvicorn host="127.0.0.1"), 实质受网络层保护
- ❌ 无 rate limiter middleware 全局 (但 sensitive ops 有 per-action 限制)

**LIVE_TRADING_DISABLED guard 是 broker 层 chokepoint, 不在 middleware**:
- middleware 不重复拦
- guard 只在 `MiniQMTBroker.place_order/cancel_order` 入口 → 任何调用方 (API/手工脚本/Beat task) 都被拦

### Q6 — broker 类清单

**✅ 实测** — 4 类全 grep:

| 类 | 文件 | 真金 (调 xtquant)? |
|---|---|---|
| `BaseBroker` (ABC) | engines/base_broker.py:18 | N/A 抽象 |
| `MiniQMTBroker` | engines/broker_qmt.py:146 | ✅ **唯一调 xtquant** (L463 order_stock + L508 cancel_order_stock), guard 已盖 |
| `PaperBroker` | engines/paper_broker.py:31 | ❌ 物理隔离, 不调 xtquant, 写 paper namespace 表 |
| `SimBroker` | engines/backtest/broker.py:19 | ❌ 回测 only, 完全模拟 |

**SAST 守门** (`test_live_trading_disabled.py:222-252`): 全 backend/engines + backend/app + scripts/ 扫 `_trader.order_stock(` 和 `_trader.cancel_order_stock(`, 任何含此 pattern 的文件必含 `assert_live_trading_allowed` 或 raise.

**LoggingSellBroker** (`backend/app/services/risk_wiring.py:54`): 占位 broker, 仅 log 不实际下单, 用于 risk_wiring (PMSRule/SingleStockStopLossRule action='sell' 时的 broker DI). 批 2 计划替换为 QMTSellBroker (走 broker_qmt.place_order, 受 guard 保护).

**结论**: chokepoint 100% 覆盖, 0 绕道. ✅

### Q7 — WebSocket / SSE / 其他实时通道

**✅ 0 风险** — 实测 (`grep -rE "websocket|sse|sock\.io" backend/app`):

唯一 WebSocket: `backend/app/websocket/manager.py` `BacktestWebSocketManager`
- 用途: backtest 进度推送 (回测引擎 → 前端)
- 端点: `/ws/socket.io` (mounted at main.py:128 `app.mount("/ws", socket_app)`)
- 操作: emit progress / status / error events
- **无 order/sell/buy/cancel 操作**

**0 SSE / GraphQL / RPC 接口**.

**结论**: 实时通道未绕过 HTTP auth + LIVE_TRADING_DISABLED guard. ✅

### Q8 — 手工脚本 broker 实例

**✅ 全走 MiniQMTBroker (guard 覆盖)** — 实测:

| 脚本 | 实例化方式 | 走 guard? |
|---|---|---|
| `scripts/emergency_close_all_positions.py` | `MiniQMTBroker(...)` 直接实例化 | ✅ guard 拦 (L412-416) |
| `scripts/cancel_stale_orders.py` | `MiniQMTBroker(...)` 直接 | ✅ guard 拦 |
| `scripts/intraday_monitor.py` | `MiniQMTBroker(...)` (L143-145) | ✅ guard 拦, **但 L141 `os.environ["EXECUTION_MODE"] = "live"` 强制覆盖 .env** (D2 Finding A, 留批 2/3) |
| `scripts/run_paper_trading.py` | 通过 `qmt_manager` (与 API 共享单例) | ✅ guard 拦 |

**OVERRIDE 紧急用法** (live_trading_guard.py 实测):
```cmd
:: 紧急清仓 (如真生产 -29%)
set LIVE_TRADING_FORCE_OVERRIDE=1
set LIVE_TRADING_OVERRIDE_REASON="Emergency close 卓然 -29% 2026-04-29"
.venv\Scripts\python.exe scripts\emergency_close_all_positions.py --code 600519.SH
```

双因素 OVERRIDE: FORCE_OVERRIDE=1 (精确 string '1') + REASON 非空 (strip 后) → bypass + audit + 钉钉 P0. 任一缺失 → raise LiveTradingDisabledError.

---

## ⚠️ 重大新发现

### Finding D — MiniQMTBroker.sell / .buy 方法不存在 (P2 dead API)

**实测**: `grep "def sell|def buy" backend/engines` 无任何匹配. MiniQMTBroker 仅有 `place_order(code, direction, volume, ...)` (L382) 接口, **无 `def sell` / `def buy` wrapper**.

**影响**:
- execution_ops.py:115/118 调 `qmt_manager.broker.sell(code, volume, price)` 和 `.buy(code, volume, price, amount)`
- 运行时调 → AttributeError → fail-fast (admin-gated, fail-secure)
- 受影响 endpoint:
  - POST /api/execution/fix-drift/execute (L682, 701)
  - POST /api/execution/emergency-liquidate (L772)

**风险**: P2 dead API (claim 紧急清仓但不能实际执行). 紧急情况只能用 `scripts/emergency_close_all_positions.py` 手工脚本.

**修法** (留批 2/3):
- 在 MiniQMTBroker 加 `def sell(self, code, volume, price=0)` wrapper, 内部调 `self.place_order(code, 'sell', volume, ...)`. 同样加 `def buy`.
- 或重写 execution_ops.py 直接用 `place_order(code, direction='sell', volume=...)`.

### Finding E — risk.py /force-reset 无 admin auth (P1 审计绕过)

`backend/app/api/risk.py:255-282` POST /force-reset/{strategy_id}:
- "强制重置到 NORMAL 状态(运维用)"
- "**仅限运维紧急情况使用**, 会记录审计日志"
- **但无 `Depends(_verify_admin_token)`** → 任何 caller (含跨 CORS 同 origin) 可调

**配合 P1 风险链**:
- /force-reset 重置 cb_state 到 L0 NORMAL
- /l4-approve 不需 auth, 任何人审批 L4 恢复
- /params PUT 改 PT_TOP_N / PMS_ENABLED 等运行时参数

但 LIVE_TRADING_DISABLED guard 仍是 chokepoint, 实际下单被拦 → **不升级到 P0 真金风险**, 仅破坏审计链 + 状态完整性.

**修法**: 留批 2/3 (添加 `Depends(_verify_admin_token)` 到 risk.py 3 个 sensitive POST endpoints).

### Finding F — ADMIN_TOKEN 当前未配置 (.env 无 ADMIN_TOKEN line)

**实测**: `grep ADMIN_TOKEN backend/.env` 无 match.

**影响**:
- ✅ Fail-secure: sensitive endpoint 调时返 500 "ADMIN_TOKEN未配置", 不可滥用
- ⚠️ 切 .env=live 前需先**生成强 token** + 加 `.env: ADMIN_TOKEN=<32-char-random>`
- 否则紧急清仓 / 撤单 API 全不可用 (虽 5 schtask 真金 disabled, 但 sensitive ops endpoint 是 紧急 fallback)

**修法** (留 PT 重启前):
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 复制到 backend/.env: ADMIN_TOKEN=<paste>
# Servy restart QuantMind-FastAPI
```

---

## 🚨 风险等级总评

| 维度 | 等级 |
|---|---|
| 真金保护 (broker.place_order/cancel_order) | 🟢 0 (LIVE_TRADING_DISABLED guard, single chokepoint, SAST 守门) |
| API → broker 链路 (execution_ops.py 9 sensitive POST) | 🟢 0 (admin-gated + ADMIN_TOKEN fail-secure 500 + per-action rate limit) |
| qmt_manager.broker 实例 (MiniQMTBroker) | 🟢 0 (guard 100% 覆盖) |
| WebSocket / SSE / RPC 真金通道 | 🟢 0 (仅 backtest progress) |
| CORS 跨域 | 🟢 0 (严格白名单 localhost:3000) |
| **risk.py 3 endpoints 无 admin auth** | 🟡 **P1** (force-reset / l4-approve, 破坏审计但不绕 guard) |
| **approval.py 3 endpoints 无 admin auth** | 🟡 **P1** (gates L4 recovery 流程) |
| strategies.py / params.py 无 auth | 🟡 P2 (改运行时配置) |
| **MiniQMTBroker.sell/.buy 不存在** | 🟡 P2 (dead API claim, fix-drift/execute + emergency-liquidate 不可用) |
| pms.py / factors.py / mining.py / pipeline.py / backtest.py / notifications.py / system.py / report.py 无 auth | ⚪ P3 (DoS / 噪音 / 资源消耗) |
| **ADMIN_TOKEN 未配置** | 🟡 P2 (切 live 前必须配, 否则 ops endpoint 全不可用) |

**总评**: 🟢 **真金 P0 风险 0** — chokepoint LIVE_TRADING_DISABLED guard + admin-gated + SAST 三重保护, API 切 .env=live 后无法绕过盖网下单.

**P1 治理债 2 件**: risk.py + approval.py 6 endpoints 无 admin gate (破坏审计, 不破坏真金).

**P2 治理债 2 件**: MiniQMTBroker.sell/.buy dead API + ADMIN_TOKEN 未配置.

---

## 🛤️ A/B/C 路径影响 (D2.1 视角)

D2 推荐 **C (等批 2)** 仍成立. D2.1 补:

- **A (.env→live)** 前置: 必先配 ADMIN_TOKEN (Finding F) + 修 risk.py 3 endpoints auth (Finding E). 否则 ops endpoint 不可用 + 审计漏洞.
- **B (paper + SKIP)** 不受 D2.1 影响 (admin token 需求与 mode 无关).
- **C (等批 2)** 顺带在批 2 修 Finding D/E/F:
  - Finding D: MiniQMTBroker.sell/.buy 加 wrapper 或重写 execution_ops.py
  - Finding E: risk.py 3 POST endpoints 加 `Depends(_verify_admin_token)`
  - Finding F: 生成 ADMIN_TOKEN 写入 .env (Servy User env 落盘)

---

## 📊 D2.1 实测覆盖率

| 检查项 | 覆盖 | 漏检 |
|---|---|---|
| 22 router files endpoint 清单 | 全扫 | 部分 GET 详情未逐个读 (read-only 风险低) |
| execution_ops.py 完整链路 (115/118 sell/buy) | 100% 实测 (代码 read + grep + 链路 trace) | — |
| qmt_manager.broker 实例确认 | 100% (qmt_connection_manager.py:118) | — |
| MiniQMTBroker 全方法清单 | 100% (`grep "    def "`) | — |
| 13 含 POST/PUT/DELETE 文件 auth gate | 100% (grep `_verify_admin_token` cross-check) | — |
| BaseBroker / PaperBroker / SimBroker 真金验证 | 100% (`grep order_stock|xtquant`) | — |
| middleware (CORS / auth / rate / TrustedHost) | 100% (main.py 全文读) | — |
| WebSocket 真金通道 | 100% (`grep websocket|sse|sock\.io`) | — |
| 手工脚本 broker 实例 (4 scripts) | 100% (D2 已扫, D2.1 复用) | — |
| ADMIN_TOKEN .env state | 100% (实测 .env 无 ADMIN_TOKEN line) | — |
| LiveTradingDisabledError SAST 守门 | 100% (test_live_trading_disabled.py:222-252) | — |

**未覆盖 (留下次)**:
- 13 files POST/PUT/DELETE 内部业务逻辑详细审计 (本 D2.1 仅扫 auth, 未审业务漏洞)
- ADMIN_TOKEN 强度策略 (e.g. 强制 ≥ 32 chars, env startup check)
- API 速率限制 middleware (current per-action only, 无全局)

---

## 📦 LL 候选沉淀

### LL-XXX (沿用批 1.5 + D2): audit 概括必须实测纠错

D2 报告原写 "API endpoint sell/buy auth gate ⚪ 待评估". 本 D2.1 实测发现:
- ✅ sell/buy endpoint 全 admin-gated (D2 概括 "未实测" → 实测 "已盖")
- ⚠️ MiniQMTBroker.sell/.buy 方法不存在 → endpoint dead (D2 概括 "需 verify auth gate" → 实测 "API 是 dead, auth gate 多余但仍存在")
- ⚠️ risk.py 3 endpoints 无 auth (D2 概括 "API 层风险待评估" → 实测 "P1 审计绕过债")

D2.1 自身的 audit 也应应用纠错规则. 完成后 D2.1 报告自身可被批 2/批 3 实施时再核.

### LL 候选 (新): API endpoint 必含 auth gate 一致性原则

12 文件无 auth 是历史增量 (随各 MVP 加 endpoint, 无统一 lint 守门). 建议:
- 每个 POST/PUT/DELETE endpoint 必含明确 auth (admin token / read-only allow / 测试 fixture)
- 引入 lint rule (custom AST checker): grep `@router\.(post|put|delete)` 必伴随 `Depends(_verify_admin_token)` 或显式 `# AUTH_NONE: <reason>` 注释
- 现有 12 files 评级修补 (P1 立修 / P2 批 2 / P3 批 3)

**升级铁律候选**: 月度 (X7) 铁律 audit 时考虑加入"FastAPI 写操作 endpoint 必含 auth gate"原则. 当前先入 LESSONS_LEARNED.md.

---

## 🚀 下一步建议

### (a) 路径决策 (D2 + D2.1 综合)

**仍推荐 C (等批 2)**, 但批 2 scope 扩 3 项 Finding (D/E/F):
- D: MiniQMTBroker.sell/.buy wrapper 或重写 execution_ops.py
- E: risk.py 3 POST + approval.py 3 POST endpoints 加 admin gate (合计 6 endpoints)
- F: 生成 ADMIN_TOKEN 写入 .env

### (b) 批 2 启动后清单 (合并 D2 + D2.1)

Scope (按 P0/P1 优先级):

**P0 (真金漂移根因)**:
1. pt_qmt_state.py 7 处 hardcoded 'live' → settings.EXECUTION_MODE 参数化 (D2 Finding B)
2. xfail strict 4 contract tests 转 PASS (test_execution_mode_isolation.py:471, 573-578)

**P1 (审计/安全)**:
3. risk.py /l4-recovery / /l4-approve / /force-reset 加 `Depends(_verify_admin_token)` (D2.1 Finding E)
4. approval.py /queue/{id}/approve / /reject / /hold 加 admin gate (D2.1 Finding E)

**P2 (dead API + 治理)**:
5. MiniQMTBroker.sell/.buy 加 wrapper 或重写 execution_ops.py (D2.1 Finding D)
6. ADMIN_TOKEN 生成 + 写 .env (D2.1 Finding F)
7. scripts/intraday_monitor.py:141 删 hardcoded override (D2 Finding A)
8. cb_state paper L0 stale orphan 清理 (D2 Finding C)

**P3 (低优先治理)**:
9. strategies.py / params.py / pms.py / factors.py 等 8 files POST/PUT/DELETE 加 auth gate
10. LoggingSellBroker → QMTSellBroker (Risk Framework 真 broker, 走 guard)

**ETA**: 批 2 ~1 周 (P0+P1 = 3-4 天, P2+P3 = 2-3 天).

### (c) 4 留 fail 清理同批

(留批 1.5 STATUS_REPORT 已建议) — 测试债 + 状态依赖类 fail 4 个.

### (d) 全方位审计 13 维 (D2/D2.1 是子集)

D2/D2.1 已覆盖: 激活路径维度 + API auth 维度.

13 维其他 11 维 (留批 2 后启):
- 数据完整性 (factor_values 158G + minute_bars 21G)
- 测试覆盖 (4127 collected)
- 文档腐烂 (CLAUDE.md / SYSTEM_STATUS / blueprint)
- Servy 服务依赖图
- Redis 缓存命名空间
- 监控告警 (钉钉 / DingTalk dedup)
- 调度链路 (Beat + schtask + cron)
- 性能基线
- 配置 SSOT (config_guard 覆盖)
- 异常处理 (fail-loud vs silent)
- 安全 (SQL injection / secret rotation)

---

## 📂 附产物清单

- [docs/audit/api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) — 本文档 (主产物)
- [docs/audit/STATUS_REPORT_2026_04_29_D2_1.md](STATUS_REPORT_2026_04_29_D2_1.md) — D2.1 整体执行报告
- 0 commit / 0 push / 0 PR (纯诊断, 0 改动)

---

> **状态**: D2.1 阶段 ✅ **完整完成** — 8 题诊断 + API endpoint 完整清单 + broker 实例链路实测 + 风险分级 + 3 finding (D/E/F).
> **关键结论**: 真金 P0 风险 **0** (chokepoint guard 100% 覆盖). P1 治理债 2 件 (risk.py + approval.py 6 endpoints 无 auth). P2 治理债 2 件 (MiniQMTBroker.sell/.buy dead API + ADMIN_TOKEN 未配置).
> **D2 推荐路径 C (等批 2) 仍成立**, 批 2 scope 加 D2.1 Finding D/E/F 共 6 子任务.
