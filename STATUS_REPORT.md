# STATUS_REPORT — Risk Framework P0 修批 1

> **日期**: 2026-04-29
> **批次**: P0 紧急修复批 1（B+ 路径）
> **触发事件**: 4-29 真生产风控失效 — 卓然股份 -29% / 南玻 -10% / 7 天 risk_event_log 0 行
> **PR**: `fix/p0-batch1-ll081-guard-namespace-assert` → main
> **关联文档**: [PROJECT_DIAGNOSTIC_REPORT.md](PROJECT_DIAGNOSTIC_REPORT.md) / [docs/audit/write_path_namespace_audit_2026_04_29.md](docs/audit/write_path_namespace_audit_2026_04_29.md)

---

## Tier 0 债清单（按批次归属）

风控系统当前 Tier 0 债 **8 项**：

| # | 债项 | 触发风险 | 批次 | 状态 |
|---|---|---|---|---|
| **T0-1** | LL-081 guard `total > 5 AND ratio > 60%` 在单仓 1/1 全 skip 时 100% bypass | 单仓 silent skip 0 alert（4-29 事件主因） | **批 1** | ✅ 修 |
| **T0-2** | `.env=paper` 与 DB 持仓数据 `live` 命名空间漂移，无启动检测 | entry_price=0 silent skip 全规则 | **批 1** | ✅ 修（启动断言） |
| **T0-3** | `run_paper_trading.py:468` hardcoded `position_multiplier=0.5`，与 cb 状态机解耦 | L4 应停下单变成减半 / L0 应满仓变成半仓 | **批 1** | ✅ 修 |
| **T0-4** | 写路径漂移：`pt_qmt_state.save_qmt_state` 5 处 hardcoded `'live'` + `execution_service._execute_live` 1 处 | 命名空间漂移持续累积，DB 与 .env 永不收敛 | **批 2** | 🟡 待启（contract test xfail strict 守门） |
| **T0-5** | `LoggingSellBroker.sell()` 占位 stub，PMS L1/L2/L3 触发不真卖 | 即使触发也不卖，永久浮盈丢失 | **批 2** | 🟡 待启 |
| **T0-6** | `09:31 DailyExecute schtask` 当前 disabled，CB multiplier 即使升级也无人执行 | T+1 调仓不发生 → 14:30 升 L4 → 持仓继续裸跌至次日仍不卖 | **批 2** | 🟡 待启 |
| **T0-7** | `auto_sell_l4=False` 默认，单股 -25% L4 也只 alert_only | 个股 -25%/30%/40%... 自由跌无止损 | **批 2** | 🟡 待启 |
| **T0-8** | `dedup` key 不含 code 维度，同 rule_id 多股触发只发首只钉钉 | 全组合 -10% 时只告警 1 股 | **批 2** | 🟡 待启 |
| **T0-9** | `approve_l4.py` 2 处 hardcoded `'paper'`，live 模式 L4 恢复看不见 | 周末 L4 灾难时运维误以为已审批但 cb_state 没动 | **批 3** | 🟡 待启 |
| **T0-10** | `api/pms.py` 仍读 `position_monitor` 死表，前端 PMS 历史永久 0 行 | 用户访问 `/pms` 看到空数据误判系统从未触发过保护 | **批 3** | 🟡 待启 |

注：批 1 修 3 项 + 1 项守门（T0-4 contract test xfail strict）。批 2/3 范围**留待用户后续指令分批执行**。

---

## 批 1 完成证据

### 修复实施清单

| Fix | 文件 | 改动行数 | 测试 |
|---|---|---|---|
| **Fix 1**: LL-081 guard 三段升级 (`total==0` / `ALL_SKIPPED` / `partial>60%`) | [backend/qm_platform/risk/rules/pms.py:159-218](backend/qm_platform/risk/rules/pms.py) | +40 / -8 | 3 new + 2 update |
| **Fix 2a**: 新模块 `startup_assertions.py` | [backend/app/services/startup_assertions.py](backend/app/services/startup_assertions.py) | +130（new） | 11 new |
| **Fix 2b**: `main.py` lifespan wire + try/except + engine.dispose | [backend/app/main.py:36-72](backend/app/main.py) | +20 / -1 | 2 new SAST |
| **Fix 3**: `run_paper_trading.py:468` hardcoded 0.5 → cb.get() | [scripts/run_paper_trading.py:462-485](scripts/run_paper_trading.py) | +9 / -1 | 3 new SAST |
| **Fix 4**: 4 contract tests 写路径命名空间守门 | [backend/tests/test_execution_mode_isolation.py:539-650](backend/tests/test_execution_mode_isolation.py) | +110（append） | 4 new (2 xfail strict) |
| **Diagnosis 5**: 写路径漂移审计文档 | [docs/audit/write_path_namespace_audit_2026_04_29.md](docs/audit/write_path_namespace_audit_2026_04_29.md) | +250（new） | — |
| **Diagnosis 6**: 本文档 + 前轮 PROJECT_DIAGNOSTIC_REPORT.md | [STATUS_REPORT.md](STATUS_REPORT.md) + [PROJECT_DIAGNOSTIC_REPORT.md](PROJECT_DIAGNOSTIC_REPORT.md) | +200 + 700 | — |

### 测试硬门验证

```
pytest backend/tests/{test_risk_rules_pms,test_run_paper_trading_position_multiplier,test_startup_assertions,test_execution_mode_isolation}.py
  → 82 passed, 2 xfailed (Fix 4 BATCH 2 BUG-flagged 符合预期)

pytest backend/tests/smoke/ -m smoke
  → 58 PASS (铁律 10b)

ruff check (全 8 个修改文件)
  → All checks passed
```

### Reviewer 双 agent 闭环

派 2 个独立 reviewer agent (oh-my-claudecode + everything-claude-code) 并行审，**9 项 findings 全采纳**（1 P0 + 5 P1 + 3 P2）：

| 编号 | 等级 | 来源 | 采纳 |
|---|---|---|---|
| #1 | P0 | OMC | ✅ main.py engine.dispose 防泄漏 |
| #2 | P1 | ECC | ✅ Servy 重启 loop → SKIP_NAMESPACE_ASSERT bypass |
| #3 | P1 | ECC | ✅ 7d → 30d window |
| #4 | P1 | ECC | ✅ pms.py 钉钉 routing TODO 标记 |
| #5 | P1 | OMC | ✅ pms.py logger 简化 + 删 %%s |
| #6 | P2 | OMC | ✅ max(by count) 替 list(...)[0] |
| #7 | P2 | OMC | ✅ SAST regex 加 intermediate var |
| #8 | P2 | ECC | ✅ test_main_lifespan 紧 regex + 加 dispose 守门 + bypass test |
| #9 | P2 | ECC | ✅ cb.get fallback 1.0 dead code 注释 |

LL-059 9 步闭环执行完整，user 0 接触（P0 修复批 1 全 AI 自主）。

---

## 命名空间漂移当前真实状态

### .env vs DB 漂移图

```
backend/.env (实测 mtime 2026-04-29 10:58):
  EXECUTION_MODE=paper                          ← 用户 PT 暂停后改回

backend/.env.bak.20260420-session20-cutover (mtime 2026-04-20 17:47):
  EXECUTION_MODE=live                           ← Session 20 LL-061 cutover 节点

DB position_snapshot 30d (4-2 → 4-28):
  295 行全部 'live'                              ← 写路径 hardcoded 'live' 持续写入

DB trade_log 30d:
  68 'live' (4-14~4-17) + 20 'paper' (4-16 仅) ← Session 14 PR #26 backfill 残留

DB performance_series 14d:
  10 行全 'live'                                ← daily_reconciliation 写入

DB circuit_breaker_state:
  2 行各占空间 — paper 行 4-20 stale "初始化(首次运行)" L0
                live 行 4-28 仍 active L0
```

**结论**: `.env=paper` 但 DB 99%+ 数据是 `live` 命名空间。**当前批 1 启动断言生效后，FastAPI 启动会立即 fail-loud 拒绝**——这是**有意为之**：强制运维感知漂移并决策修法。

### 路径选择推荐

#### 路径 A（**强烈推荐**）: 改 `.env` 回 `EXECUTION_MODE=live`

**理由**:
- DB 实测 295/295 持仓 + 10/10 perf_series 全 `live`，cb_state.live 4-28 仍 active
- 与历史 cutover 决策（4-20 LL-061）对齐
- 启动断言通过，FastAPI/Celery 正常运行
- 14:30 风控读路径 `enricher.load_entry_prices('live')` → `trade_log live` 有 68 行 → entry_price 真实 → 全规则正常评估
- 写路径 `pt_qmt_state.save_qmt_state` 仍 hardcoded 'live'，与 .env 一致后**漂移消失**（直到批 2 修源头才彻底解决）
- 风险低: PT 已被用户清仓只剩 1 股 + DailyExecute schtask disabled → cutover 不触发交易

#### 路径 B: 保持 `.env=paper` + 设 `SKIP_NAMESPACE_ASSERT=1` 应急 bypass

**仅在以下场景使用**:
- 用户主动决策保留 paper 命名空间做分析（需迁移 DB live → paper）
- 批 2 修写路径漂移期间，避免启动断言阻断开发

**风险**: 漂移持续，14:30 风控仍然 entry_price=0 silent skip — **本批 1 的 Fix 1 LL-081 guard 升级会捕获此场景并 ERROR 告警**（这正是 Fix 1 的目的）。但持仓真实风险无任何止损。**不推荐长期保留**。

#### 路径 C: 等批 2 完成

**时间窗**: 批 2 估计 1-2 周（5 项 T0 债）。**期间真金风控仍 silent**。**不推荐**——无谓延长无保护期。

### signal_engine 是否消费 multiplier — 上轮确认结论复述

**`backend/engines/signal_engine.py` grep `position_multiplier|cb_state|current_level|circuit_breaker|can_rebalance|check_circuit_breaker` → 0 hits**。Engine 层 0 消费。

但 multiplier 在另外 2 处真消费：
- `scripts/run_paper_trading.py:441-485` (Step 5.9 execute_phase) — 调 CB + 传 cb_level + position_multiplier 给 ExecutionService
- `backend/app/services/execution_service.py:51-117 execute_rebalance` — 真消费 cb_level (L4 cut, L3 reduce, L2 pause)

**链路有效但 schtask 阻断**: 09:31 `QuantMind_DailyExecute` 当前 disabled (CLAUDE.md L370)，即使 cb_state 升级 → execute_phase 不跑 → 整链空转。CB 多 PR 合并后实质作用仅在**信号生成 (16:30 DailySignal)** 与**下一交易日执行 (09:31 DailyExecute)** 之间存在依赖断点，需在批 2 重启评估时一并处理（T0-6）。

---

## PT live restart Pre-flight Checklist

**用户决策点**: 完成下列 8 项才允许 PT live cutover (从 paper-mode dry-run 转 live)：

| # | 检查项 | 状态 | 阻断批次 |
|---|---|---|---|
| **PRE-1** | 写路径漂移修完 (`pt_qmt_state` 5 处 + `execution_service` 1 处 hardcoded `'live'` → `settings.EXECUTION_MODE` 或函数参数) | 🟡 未修 | 批 2 |
| **PRE-2** | `LoggingSellBroker` → `QMTSellBroker` 真接 broker.sell（PMS L1/L2/L3 触发后真卖出） | 🟡 未修 | 批 2 |
| **PRE-3** | `09:31 DailyExecute schtask` 重启评估 reenable（含 P0-α/β 自愈验证 + 5 phantom 处置） | 🟡 未修 | 批 2 |
| **PRE-4** | `dedup` key 加 code 维度（避免单一 rule_id 多股触发只发首只） | 🟡 未修 | 批 2 |
| **PRE-5** | `auto_sell_l4=True` 决策（单股 -25% 真自动止损） | 🟡 未修 | 批 2 |
| **PRE-6** | `approve_l4.py` 2 处 hardcoded `'paper'` 修（接受 `--execution-mode` 参数） | 🟡 未修 | 批 3 |
| **PRE-7** | `api/pms.py` deprecate 或重写走 RiskFramework（消死表 0 行） | 🟡 未修 | 批 3 |
| **PRE-8** | `replay_risk_rules` 在 live 命名空间跑出 ≥ 1 行 `risk_event_log`（端到端真触发证据） | 🟡 未跑 | 批 2 末尾 |

**PT live 何时可重启**: 8 项全 ✅。当前 0/8 完成，距离重启**至少 1-2 周工程**。**不可强推**。

---

## 下一步 P0 批 2 CC prompt 草案

```
任务: Risk Framework P0 紧急修复批 2 (写路径漂移消除 + 真 broker)

【先决条件】
- 批 1 已 merge (本 PR)
- .env 已切回 EXECUTION_MODE=live (用户决策, 路径 A)
- DB cb_state live 行 active L0 / paper 行 stale 不动

【全面思考与主动发现】
开工前回答:
1. .env 当前 EXECUTION_MODE 实测值
2. 启动断言是否通过 (是, 还是 SKIP_NAMESPACE_ASSERT=1 bypass)
3. pt_qmt_state.save_qmt_state 5 处 hardcoded 'live' 修法决策:
   选项 A: 替 settings.EXECUTION_MODE
   选项 B: 函数签名加 execution_mode 参数 + 调用方显式传
4. execution_service._execute_live trade_log INSERT VALUES 'live' 修法
5. daily_reconciliation.py 11 处 'live' 是否 D5-KEEP (盘后对账 vs 漂移源)
6. QMTSellBroker 是否已存在 (grep PaperBroker / qmt_client.sell)? 如果不存在, 实施范围估计
7. 09:31 DailyExecute schtask 当前 disabled 原因深查 (Stage 4.2 评估文档)
8. dedup key 加 code 维度对历史 dedup state 的兼容性

修复 1: pt_qmt_state.save_qmt_state 漂移消除
- 5 处 hardcoded 'live' → settings.EXECUTION_MODE (选项 A 推荐)
- 删 4-29 注释 "execution_mode 从 paper 改为 live"
- 加 4 个 unit test (settings='live'/'paper' 各 2: SQL 参数 + INSERT VALUES)
- 删除 test_save_qmt_state_uses_settings_execution_mode 的 xfail 标记

修复 2: execution_service._execute_live trade_log INSERT
- VALUES (..., 'live', %s) → VALUES (..., %s, %s) + execution_mode 参数
- 删除 test_save_live_fills_uses_settings_execution_mode 的 xfail 标记

修复 3: LoggingSellBroker → QMTSellBroker
- 新建 backend/app/services/risk_brokers/qmt_sell_broker.py
- 实现 BrokerProtocol.sell() 调 qmt_client.sell + 写 trade_log
- risk_wiring.py 注入 QMTSellBroker (paper 模式仍用 PaperBrokerSellAdapter)
- 加端到端 smoke test (paper-mode dry-run sell triggered)

修复 4: 09:31 DailyExecute schtask 评估
- 详查 CLAUDE.md L370 disabled 原因 (5 phantom 码 / F19 backfill 状态)
- 写 docs/audit/dailyexecute_reenable_eval.md
- 准备 reenable PR (留批 2 末尾)

修复 5: dedup key 加 code 维度
- risk_wiring.IntradayAlertDedup._build_key: + ":{code}"
- 历史 key 兼容: 旧 key 24h TTL 自然过期, 新 key namespace 独立
- 1 unit test

修复 6: auto_sell_l4 决策
- settings 加 SINGLE_STOCK_AUTO_SELL_L4: bool = False
- risk_wiring.build_risk_engine 注入 SingleStockStopLossRule(auto_sell_l4=settings.SINGLE_STOCK_AUTO_SELL_L4)
- 文档: 启用前必先验证 PT live 已稳定 5 个交易日

验收:
- 批 2 PR 通过 LL-059 9 步闭环 (precondition / RED / GREEN / reviewer / fix / merge)
- 删除 contract test xfail 标记 (Fix 4 contract tests now PASS)
- replay_risk_rules 跑 14:30 daily_check 在 live 命名空间出 ≥ 1 行 risk_event_log
- pytest 全绿 (含修批 1 + 修批 2 新 tests, baseline 不增 fail)
- pre-push smoke 全 PASS

不允许 (留批 3):
- approve_l4.py 修
- api/pms.py deprecate
- 真启动 PT live (要等 PRE-1~8 全过)
```

---

## 总结一句话

> **批 1 完成: 3 修（LL-081 guard / 启动断言 / cb multiplier）+ 4 contract tests 写路径守门 + 2 审计文档**。真金风控**已不再 silent**——卓然 -29% 类事件下次发生时，14:30 daily_check 会捕获 ALL_SKIPPED ERROR + Servy 重启循环用 SKIP_NAMESPACE_ASSERT 应急。但 broker 仍是 stub、写路径仍 hardcoded 'live'、execute_phase 仍 schtask disabled——**真金主动止损还要批 2 完成**才能开 PT live。当前 0/8 pre-flight checklist 完成，强烈不推荐重启 PT live。
