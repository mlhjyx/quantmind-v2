---
adr_id: ADR-008
title: execution_mode 命名空间契约 (live/paper 物理隔离 + signals 跨模式共享)
status: accepted
related_ironlaws: [25, 33, 34, 36, 39]
recorded_at: 2026-04-19
---

## Context

Session 10 (2026-04-19 周日) PT 回撤根因调查发现: live 模式 PT 运行 2 周 (4-02~4-17) 期间, 核心交易路径的 **写入用 `'live'`, 读取 hardcoded `'paper'`**, 造成读取命名空间永远 empty, 多个子系统静默失效.

### 根因链

```
DDL 层: 4 张共享状态表 (signals / trade_log / position_snapshot / performance_series)
         + 2 张熔断表 (circuit_breaker_state / circuit_breaker_log)
         均以 (strategy_id, execution_mode) 作为命名空间键

写入层: live 模式写 'live' ✓
         - save_qmt_state (pt_qmt_state.py:115/158) → position_snapshot + performance_series 'live'
         - _save_live_fills (execution_service.py:367) → trade_log 'live'

读取层: 10+ 处 hardcoded 'paper' ✗
         - paper_broker.load_state L60/80/95/117
         - signal_service._load_prev_weights L296-299
         - risk_control_service.check_circuit_breaker_sync L1217/1381
         - pt_monitor_service.check_opening_gap L57-58
         - beta_hedge.calc_portfolio_beta L40

行为层 (live 模式下):
  - paper_broker.load_state → state.holdings={} → needs_rebalance=True 每日触发
  - _load_prev_weights → {} → _check_overlap 跳过
  - check_circuit_breaker_sync → L0 "首次运行" **熔断 L1-L4 全部失效**
  - check_opening_gap → total_w=0 **组合加权跳空检测静默失效**
```

### 实测证据 (DB 4 表 execution_mode 分布, Session 10)

| 表 | rows | 分布 | 说明 |
|---|---|---|---|
| signals | 100 | 全 'paper' | 信号层硬编码设计 (跨模式共享) — 正确 |
| trade_log | 84 | 64 'live' + 20 'paper' (仅 4-16) | live 主流, paper 来自 17:05 Task Scheduler 污染 |
| position_snapshot | 138 | 全 'live' | save_qmt_state 写入, 无 paper 残留 |
| performance_series | 9 | 全 'live' | save_qmt_state 写入 |
| circuit_breaker_state | (empty live) | 写 'paper' 但读永远 empty | **熔断 2 周裸奔** |

### 不是 Bug 的地方 (有意设计)

- `signals` 表 hardcoded 'paper' — 信号是"策略意图", 不区分执行路径, 跨模式共享
- `backend/app/api/paper_trading.py` / `paper_trading_service.py` / `scripts/paper_trading_status.py` 等 — paper 面板/分析工具**专查 paper 历史**, 硬编码正确
- `scripts/bayesian_slippage_calibration.py` / `check_graduation.py` / `pt_graduation_assessment.py` — paper 毕业/统计分析专用, 硬编码正确

**本 ADR 仅约束**: 核心交易路径 (broker + signal_service + risk_control + pt_monitor + beta_hedge) 的运行时读写.

## Decision

### 契约 D1 — 两命名空间物理隔离

每条 `(strategy_id, execution_mode)` row 独立. 读写必须带 `execution_mode` 显式过滤. 严禁同 strategy_id 跨模式读数据 (paper 模式不读 live 数据, 反之亦然).

### 契约 D2 — 读写模式动态化 (核心交易路径)

核心路径所有 hardcoded `execution_mode='paper'` 改为 `settings.EXECUTION_MODE` 动态:

| 文件 | 行号 | 改动 |
|---|---|---|
| `backend/engines/paper_broker.py` | 60/80/95/117/522/546/563/574 | `execution_mode='paper'` → `settings.EXECUTION_MODE` (读+写) |
| `backend/app/services/signal_service.py` | 296-299 | `_load_prev_weights` WHERE `paper` → 动态 |
| `backend/app/services/risk_control_service.py` | 1217/1269/1330/1381 | 熔断 state/log 读写 → 动态 |
| `backend/app/services/pt_monitor_service.py` | 57-58 | 跳空组合权重读 → 动态 |
| `backend/engines/beta_hedge.py` | 40 | beta 计算读 → 动态 |

**实施约束**: 每处改动必须带单测覆盖 `live` + `paper` 两个模式分支, 防回归.

### 契约 D3 — signals 层保持 'paper' 硬编码 (跨模式共享)

`signals` 表 execution_mode 字段在 `_write_signals` L435 + `get_latest_signals` L272 + DELETE L426 **保持 hardcoded 'paper'** 不动.

**理由**:
- 信号是"策略意图" (Top-20 code + target_weight + alpha_score), 与 broker/执行路径无关
- live broker + paper broker 消费同一份信号 (paper 影子对照需求也走这条)
- 前端 UI `paper_trading_service` 读 'paper' 命名空间作为信号档案, 契约稳定

### 契约 D4 — paper UI/分析工具保持 'paper' 硬编码

以下**保留 hardcoded 'paper'** (专查 paper 数据):
- `backend/app/api/paper_trading.py` 前端 API
- `backend/app/services/paper_trading_service.py`
- `scripts/paper_trading_status.py` / `paper_trading_stats.py` / `pt_daily_summary.py`
- `scripts/bayesian_slippage_calibration.py` (paper 滑点校准)
- `scripts/check_graduation.py` / `pt_graduation_assessment.py` (paper 毕业评估)
- `scripts/approve_l4.py` (paper 熔断 L4 审批)
- `scripts/pt_watchdog.py` (paper 心跳)
- `backend/tests/test_a4_a6.py` / `test_e2e_full_chain.py`

### 契约 D5 — 迁移/数据清理策略

- **不清理 4-16 trade_log 20 rows paper 污染**: 保留作为根因审计证据, 新代码修复后新数据自然隔离
- **circuit_breaker_state 'paper' 空 row 保留**: 阶段 2 PR 修复后, 新 'live' row INSERT 时与老 'paper' row 物理隔离 (DB CHECK 约束 `UNIQUE(strategy_id, execution_mode)` 已有)
- **position_snapshot 4-17 缺失数据**: 阶段 2 PR 前一次性手动补录 (从 QMT Redis 19 股 + 4-14~4-17 trade_log fills 重算)

### 契约 D6 — 硬防御 (DDL 级别, 阶段 3 根治)

阶段 3 新增 `strategy.execution_mode` 字段 + CHECK 约束:

```sql
ALTER TABLE strategy ADD COLUMN execution_mode VARCHAR(16) NOT NULL DEFAULT 'paper';
ALTER TABLE strategy ADD CONSTRAINT chk_strategy_mode
    CHECK (execution_mode IN ('paper', 'live'));
```

- 一个 strategy_id 只能绑定一种模式 (paper 或 live)
- 迁移: 现 `STRAT=28fc37e5-...` 拆成 `live_STRAT=28fc37e5-...` (保留) + `paper_STRAT=新生成 UUID` (影子对照)
- 17:05 任务若重启用, 改用 paper_STRAT (不污染 live)

## Alternatives Considered

### 方案 B: 统一所有写入为 'paper'

**做法**: `save_qmt_state` / `_save_live_fills` 改写 'paper', 读路径不变.

**Pros**: 改动最小 (2 处写入 vs 10+ 处读取).

**Cons**:
- 破坏 `daily_reconciliation.write_live_snapshot` 契约 (已约定写 'live')
- 未来真引入 paper 影子对照时, live 和 paper 数据混在 'paper' 命名空间, 再次根因
- 掩盖 bug 而非根治, 违反铁律 33 精神 (fail-loud)

**不选理由**: 治标不治本. 把熔断/跳空/换仓问题从"读不到"变成"读到 paper 数据假装", 语义更混乱.

### 方案 C: 新引入逻辑层抽象 `StateRepository.read_state(mode)`

**做法**: 抽 `StateRepository` 接口, 所有读/写走它, 内部根据 settings.EXECUTION_MODE 分发.

**Pros**: 单点控制, 后续切换模式只改一处.

**Cons**:
- 工程量 5-10 天 (重构 10+ 调用点 + 单测 + 集成测)
- Sub2 阶段 (下周) 无法交付, 拖延 live 重启
- 契约 D2 的动态化方案已覆盖本质

**不选理由**: 过度工程, 不符合铁律 23 (不预设抽象). 若未来真出现多模式需求再抽.

## Consequences

### 好处

- **熔断 L1-L4 live 模式恢复工作** — 真金白银有保护层
- **每日误换仓消除** — paper_broker.load_state 读到真实持仓, needs_rebalance 按月度判定
- **组合跳空检测恢复** — pt_monitor live 模式正确读持仓权重
- **铁律 34 修复** — config SSOT 精神扩展到运行时状态命名空间

### 成本/约束

- **阶段 2 3 PR 工作量**: ~2 天 (10+ 点改动 + 20+ 单测)
- **阶段 3 DDL 迁移**: ~1 天 (加字段 + backfill + 现 strategy_id 拆分)
- **regression 锚点风险**: `run_backtest.py` 单测 paper 路径可能依赖老读 'paper'. 需 regression 5yr+12yr max_diff=0 验证 (铁律 15)
- **暂停 PT 1 周** (用户已同意): 机会成本约 1 周 × 年化 15% / 52 ≈ 0.29%

### Tech debt 记录

- D2 动态化是修复不是根治, 未来 D6 DDL 层约束才是根治. 如 D6 推迟, 需在 commit message + 本 ADR 显式记录
- 1 strategy_id 历史数据 paper+live 混存 (阶段 2 PR 前 trade_log 64 live + 20 paper), 长期查询需带 execution_mode 过滤

## References

### 铁律关联
- **铁律 25** 代码变更前必读当前代码 — 修复前 grep 全部 hardcoded 'paper' (本 ADR 已列 D2 清单)
- **铁律 33** 禁 silent failure — 熔断 "L0 首次运行" 日志不告警是 silent failure 实锤
- **铁律 34** 配置 single source of truth — execution_mode 读写对齐是 SSOT 精神扩展
- **铁律 36** 代码变更前必核 precondition — 阶段 2 PR 前必验 DB 4 表 execution_mode 分布不变
- **铁律 39** 架构/实施模式切换必显式声明 — 本 ADR 是架构模式产物, 阶段 2 PR 是实施模式

### 相关代码
- `backend/engines/paper_broker.py:60/80/95/117` (load_state)
- `backend/app/services/signal_service.py:296-299` (_load_prev_weights)
- `backend/app/services/risk_control_service.py:1217/1381` (熔断)
- `backend/app/services/pt_monitor_service.py:57-58` (跳空)
- `backend/app/services/pt_qmt_state.py:115/158` (live 写入)
- `backend/app/services/execution_service.py:367` (_save_live_fills)

### 相关 ADR
- ADR-005: CRITICAL 不落 DB 走事件 — 同源 silent failure 治理
- ADR-004: CI 3 层本地 — 单测覆盖 live+paper 双模式必须纳入 daily full

### 相关 Session
- Session 10 (2026-04-19) PT 回撤根因调查, 完整调查过程见 `memory/project_sprint_state.md` Session 10 handoff
- LL-061 (待写) "命名空间读写不对称导致熔断裸奔 2 周" — 教训沉淀

## Follow-up

- [x] **阶段 1** (2026-04-19 Session 10): schtasks disable 3 任务 + CLAUDE.md L639-648 -10.2% 误读修正 PR
- [x] **阶段 2 PR-A** (2026-04-19 Session 11 PR #23 `ece3e70`): execution_mode 动态化 (契约 D2), 5 核心文件 + 单测 + regression
- [x] **阶段 2 D2-a** (2026-04-19 Session 13 PR #25 `9ced069`): `save_qmt_state` L1 fail-loud 守卫 (`_assert_positions_not_evaporated`), 防 QMT 断连蒸发 snapshot
- [x] **阶段 2 PR-B** (2026-04-19 Session 14 PR #26 `6e1f050`): `load_universe` ST LEFT JOIN + COALESCE conservative, 关闭 P0-ε 688184.SH ST race
- [x] **阶段 2 D2-b** (2026-04-20 Session 15, 诊断闭合): P1-b 4-17 snapshot 蒸发根因定位 — `save_qmt_state` 在 D2-a 合并前无守卫 → **已被 D2-a 根除**, 不需新 code change. 详见下节 "D2-b 诊断结论".
- [ ] **阶段 2 D2-c** (2026-04-20 Session 15): 手工补 4-17 snapshot (独立 PR + 执行分离)
- [ ] **阶段 2 PR-C** (下周): pt_audit.py 5 检测 (ST 漏 / mode 错位 / 换手异常 / rebalance 日不符 / QMT drift)
- [ ] **阶段 3 PR-D** (下下周): DDL strategy.execution_mode + 现有 strategy_id 迁移拆分
- [ ] **阶段 4** (下下周末): 验证全套 + 重启 Servy live + 盯开盘 + audit guard 观察首周
- [ ] 注册 ADR-008 → `python scripts/knowledge/register_adrs.py --apply`

## D2-b 诊断结论 (2026-04-20 Session 15)

**问题**: Session 10 handoff 记 P1-b — 4-17 `position_snapshot` live 行 0, QMT 真实 19 股. 起初假设根因是 `daily_reconciliation` 未兜住, 实际 DB probe 推翻该假设.

### 时序还原 (2026-04-17)

| 时刻 | 事件 | 结果 |
|---|---|---|
| 09:31 | schtasks `DailyExecute` → QMT 20 单成交 | `trade_log` 写 20 行 live (10 buy + 10 sell) |
| 15:40 | schtasks `DailyReconciliation` (延迟 30min) | `write_live_snapshot` DELETE + INSERT **19 行 live** ✅ (`scheduler_task_log` `qmt_stocks=19 db_stocks=19 mismatches=0`) |
| 16:30 或 20:58 | `save_qmt_state` 被 signal_phase / 手工重跑调用, QMTClient 读 Redis `portfolio:current` 返空 (Servy QMTData cache stale 或 xtquant 断连) | `_save_qmt_state_impl` **DELETE live rows + INSERT 0 行** → 19 蒸发 ❌ |

### 根因 (与 P1-b 假设吻合)

`save_qmt_state` 在 **Session 13 D2-a 合并前**无 fail-loud 守卫, 允许"前日 ≥1 持仓 + 今日 QMT 返 0" silent DELETE + INSERT 0. 这不是 `daily_reconciliation` 的问题 — `write_live_snapshot` 当日 15:40 正确写入了 19 行, 是后续 `save_qmt_state` 不对称读写覆盖了它.

### 修复 (已完成, 无需新 code)

PR #25 (Session 13 D2-a) 在 `_save_qmt_state_impl` 首行添加:

```python
_assert_positions_not_evaporated(cur, trade_date, strategy_id, qmt_positions)
```

当 `qmt_positions` 空 + 前一交易日 live `quantity > 0` 行数 ≥ 1 → `raise QMTEmptyPositionsError`. PT 主流程 `run_paper_trading.py:246` 差异化 `except` 放行此异常到 outer log_step → `sys.exit`, 拒绝 DELETE. **同类 bug 不再能复现**.

### 遗留: D2-c 一次性数据修复

4-17 live snapshot 仍需手工补. 由独立 PR 提交 `scripts/repair/restore_snapshot_20260417.py` (reconstruction = 4-16 snapshot + 4-17 trade_log), dry-run → 用户批准 → apply. 详见该 PR.
