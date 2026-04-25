# MVP 3.3 Signal-Exec Framework (铁律 16 信号路径唯一契约 + 订单路由统一)

> **ADR**: Platform Blueprint §4.7 / Framework #6 Signal-Exec / 铁律 16/26/32/34
> **Sprint**: Wave 3 3/5 (Session 37+ 起, post MVP 3.2 全 4 批 ✅)
> **前置**: MVP 3.2 Strategy Framework ✅ (Session 33-36, S1+S2 注册激活) / Signal interface.py ABC 骨架 ✅ (`backend/qm_platform/signal/interface.py` 138 行)

## Context

**问题**: 当前 PT 的 signal → order 路径**有 ABC 无 concrete**:
- `SignalPipeline` ABC 已定义 (`compose` / `generate`), 但生产 PT 直调 `engines/signal_engine.py::generate_signals()` 绕过 SDK.
- `OrderRouter` ABC 定义但无 concrete, `execution_service.py` 直接做 signal → QMT 下单 (turnover/lot/cash 三约束硬编 broker.py).
- `ExecutionAuditTrail` ABC 定义但无 concrete (依赖 MVP 3.4 Event Sourcing outbox).

**Precondition 实测发现** (Session 36 末 grep 结果, Session 37+ 开工前需复核):
- ✅ `backend/qm_platform/signal/interface.py`: 3 ABC 已存 (138 行, MVP 3.2 batch 1 同期 + Sub3 collateral 之后未演进)
- ✅ `backend/engines/signal_engine.py`: PAPER_TRADING_CONFIG SSOT, S1 strategy 已经 wrap 此入口 (MVP 3.2 batch 2)
- ✅ `backend/app/services/execution_service.py`: 当前 signal → order 实施层, MVP 3.3 改造 target
- ⚠️ MVP 3.4 Event Sourcing 是 ExecutionAuditTrail 依赖, 本 MVP 不包含 audit concrete
- ⚠️ S2PEADEvent.status=DRY_RUN, 不参与本 MVP 的 OrderRouter 真单路径 (S2 升 LIVE 独立 PR)

## Scope (~3-4 周, 3 批交付, 串行)

### 批 1: SignalPipeline concrete + 现 PT wrap (~1 周)

**交付物**:
1. `backend/qm_platform/signal/pipeline.py` ⭐ 新 ~150 行
   - `PlatformSignalPipeline(SignalPipeline)` concrete
   - `compose(factor_pool, trade_date, ctx)`: 内部调 `engines.signal_engine.SignalComposer + PortfolioBuilder` (铁律 16, 不重写)
   - `generate(strategy, ctx)`: 调 `strategy.generate_signals(ctx)` (Strategy ABC delegation)
   - 返 `list[Signal]` 标准化 (target_weight ∈ [0, 1], sum ≤ 1.0)
2. `backend/qm_platform/signal/__init__.py` ⚠️ MODIFY: 导出 `PlatformSignalPipeline`
3. `backend/tests/test_platform_signal_pipeline.py` ⭐ 新 ~120 行 ~10 tests
4. `backend/tests/smoke/test_mvp_3_3_batch_1_live.py` ⭐ 新 (铁律 10b subprocess import + S1 path equivalence)

**验收**: regression `regression_test --years 5` max_diff=0 (铁律 15, S1 走 SDK 路径 bit-identical 当前 PT)

### 批 2: OrderRouter concrete + 替 execution_service signal→order (~1.5 周)

**交付物**:
1. `backend/qm_platform/signal/router.py` ⭐ 新 ~200 行
   - `PlatformOrderRouter(OrderRouter)` concrete
   - `route(signals, current_positions, capital_allocation, turnover_cap)`: target diff → `list[Order]` 含 (code/direction/quantity/price_limit), 内部调 broker.py 整手 + cash buffer 约束
   - `cancel_stale(cutoff_seconds)`: 调 `app/services/execution_service.py` 撤单逻辑 (复用 cancel_stale_orders.py 路径)
   - 幂等键: order_id = sha256(strategy_id + trade_date + code + direction)
2. `backend/app/services/execution_service.py` ⚠️ MODIFY (~80 行 delta)
   - 拆出 signal → order 阶段交给 `PlatformOrderRouter.route()`, 保留 QMT 下单 + fill 回写
3. `backend/app/tasks/daily_pipeline.py` ⚠️ MODIFY (~30 行 delta)
   - `signal_phase`: `for strategy in strategies: signals = pipeline.generate(strategy, ctx); orders = router.route(signals, positions, alloc)`
4. `backend/tests/test_platform_order_router.py` ⭐ 新 ~250 行 ~20 tests
5. `backend/tests/smoke/test_mvp_3_3_batch_2_live.py` ⭐ 新 (铁律 10b)

**验收**: regression max_diff=0 + S1 真生产链路 dry-run + 钉钉 0 false alarm

### 批 3: AuditChain stub + Event 发布 hook (~0.5-1 周)

**交付物**:
1. `backend/qm_platform/signal/audit.py` ⭐ 新 ~80 行
   - `StubExecutionAuditTrail(ExecutionAuditTrail)` concrete (no-op record + raise AuditMissing on trace)
   - 接受 PlatformOrderRouter 的 record() callback, 当前实现仅 logger.info, MVP 3.4 outbox concrete 时替换
2. `PlatformOrderRouter` ⚠️ wire `audit.record('order.routed', payload)` hook (铁律 33 fail-loud)
3. `backend/tests/test_audit_stub.py` ⭐ 新 ~50 行 ~5 tests

**验收**: hook 链路 logger 可见 + MVP 3.4 接入点显式声明 (interface.record 契约 outbox-ready)

## Out-of-scope (明确排除, 铁律 23)

- ❌ `ExecutionAuditTrail.trace()` 真实现 (依赖 MVP 3.4 Event Sourcing outbox)
- ❌ S2PEADEvent → OrderRouter LIVE (status=DRY_RUN, 独立升级 PR)
- ❌ Multi-broker routing (仅 miniQMT, IB/Forex 留 Wave 4+)
- ❌ Order book matching / smart routing 算法 (TWAP/VWAP execution algo, MVP 3.5+)
- ❌ Capital allocation 动态计算 (MVP 3.2 EqualWeightAllocator 静态 50/50, 本 MVP 沿用)
- ❌ 重写 signal_engine.py 内部逻辑 (SignalComposer/PortfolioBuilder 铁律 16 唯一路径不动)

## 关键架构决策 (铁律 39 显式)

### 铁律 16 唯一信号路径 — wrap 而非 refactor
- 选择: `PlatformSignalPipeline.compose` 内部调 `engines.signal_engine` 现有逻辑, 不重写
- 理由: 当前 PT + 回测 + research 已对齐 (MVP 2.3 Sub3), 重写会引入 sim-to-real gap 风险
- 验证: 批 1 PR 硬门 `regression_test --years 5` max_diff=0

### OrderRouter 接管 turnover/lot/cash 约束 — 不重写 broker.py
- 选择: PlatformOrderRouter 调用现有 `engines/backtest/broker.py` 约束逻辑生成 Order list, broker.py 不动
- 理由: broker.py 是回测+实盘共享路径, 重写会破坏 H0 验证 (理论 vs 实盘 <5bps 误差)
- 验证: 批 2 PR 硬门 commission/slippage bit-identical regression

### AuditChain 占位 stub — 不阻塞 MVP 3.3 完工
- 选择: MVP 3.3 批 3 仅交付 stub + record hook 接入点, trace() raise NotImplementedError 委 MVP 3.4 outbox
- 理由: 铁律 23 独立可执行, 不依赖未实现模块
- 升级路径: MVP 3.4 outbox concrete 时替换 stub, hook 协议不变

### S2PEADEvent OrderRouter 路径
- 选择: S2 status=DRY_RUN 时 OrderRouter 跳过真单 (record audit 但不 send_order), 升 LIVE 后启用
- 实现: `OrderRouter.route` 内 `if strategy.status != LIVE: log + skip_send`
- 风险隔离: S2 错误 signal 即便 generate 也不会触发真金, 7 日观察 + 回测 PASS 后 update_status

## LL-059 9 步闭环 (3 批 = 3 PR, 串行)

批 1 `feat/mvp-3-3-batch-1-signal-pipeline` → 批 2 `feat/mvp-3-3-batch-2-order-router` → 批 3 `feat/mvp-3-3-batch-3-audit-stub`

每批: precondition 实测 (DB/接口/测试锚点) → 实施 → 硬门 (pytest + ruff + smoke + regression) → commit + push → gh pr create → 2 reviewer (code + python) → P1 fix → AI self-merge.

## 验证 (硬门, 铁律 10b + 40 + 15)

```bash
# 批 1
pytest backend/tests/test_platform_signal_pipeline.py -v  # ~10 PASS
python scripts/regression_test.py --years 5  # max_diff=0 铁律 15

# 批 2
pytest backend/tests/test_platform_order_router.py -v  # ~20 PASS
python scripts/regression_test.py --years 5  # max_diff=0
python scripts/run_paper_trading.py signal --dry-run  # S1 真生产链路 0 干扰

# 批 3
pytest backend/tests/test_audit_stub.py -v  # ~5 PASS
pytest -m smoke --timeout=180  # +3 batch smoke 全绿
pytest --co -q | wc -l  # 铁律 40 baseline 不增
```

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 批 1 wrap signal_engine 引入隐式行为漂移 | regression diff > 0 | 硬门 max_diff=0, fail 即回滚 |
| 批 2 OrderRouter 替 execution_service signal-side 破坏当前 fill 回写 | T+1 持仓不一致 | 批 2 拆 signal-side / fill-side 独立, fill 回写不动. dry-run 周末 + 工作日双验证 |
| S2 DRY_RUN signal 经 OrderRouter 时 skip 不生效 | 真金触发 | 双重保险: 批 2 测试覆盖 status filter + run_paper_trading.py 入口 strategy.status 二次检 |
| 批 3 AuditChain stub trace() raise 阻塞下游 | 调用方 fail-loud | stub 仅 record() 实现, trace() 文档显式 NotImplementedError, 下游不应在 MVP 3.4 完工前调 trace() |
| MVP 3.3 与 MVP 3.4 串行依赖 | 时序耦合 | 接口契约固定 (interface.py 不变), MVP 3.4 替换 stub 内部不破坏 record() 协议 |

## Follow-up (跨 PR, 不在本 plan)

1. ExecutionAuditTrail concrete (MVP 3.4 Event Sourcing outbox 落地后)
2. S2PEADEvent OrderRouter LIVE 升级 (独立 update_status PR + 7 日观察 + 钉钉强化)
3. Multi-broker routing (Wave 4 Forex + IB 引入时设计, MVP 4.x)
4. Smart execution algo (TWAP/VWAP, MVP 3.5+ Eval Gate 后期)
5. ADR-012 Signal-Exec 契约稳定性 (MVP 3.3 完工后写, 锁 SDK 公共方法签名防 Wave 4+ 破坏)
