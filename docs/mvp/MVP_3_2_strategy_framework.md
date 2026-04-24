# MVP 3.2 Strategy Framework (multi-strategy 一等公民)

> **ADR**: ADR-002 Multi-Strategy / Platform Blueprint §4.7 / Framework #3 Strategy
> **Sprint**: Session 33 起 (2026-04-24), Wave 3 2/5
> **前置**: MVP 3.1 Risk Framework ✅ (Session 30 PR #55-#61) / MVP 3.0a PEAD prep (PIT bias) / Strategy interface.py ✅ (骨架 146 行)

## Context

**问题**: 当前 PT 单策略 (CORE3+dv_ttm 等权月度 Top-20 + SN b=0.50) 硬编在 `signal_engine.py` + `pt_live.yaml`, 无法支持第 2 策略 (PEAD Event-driven) 并跑. Wave 3 后续 MVP (3.3 Signal-Exec / 3.5 Eval Gate) 依赖 Strategy 作为一等公民.

**Precondition 实测发现** (Session 33 2026-04-24 DB 查询, 非推测):
- ❌ **`strategy_registry` DB 表不存在** — Agent B pre-research 误认 "已建", 实测 `information_schema` 0 行. **批 1 必含 migration**.
- ⚠️ **PEAD 因子多数 DEPRECATED**: `pead_q1` / `earnings_surprise_car` = DEPRECATED (Phase 3D ML NO-GO), `sue_pead` = warning (LEGACY pool, 7.2M rows to 2026-04-10), **无 active PEAD 因子**.
- ✅ **`earnings_announcements` 表可用**: 207,668 rows, 2015-04-07 → 2026-04-04, 含 `f_ann_date` + `eps_surprise_pct` (PEAD 事件触发完备数据).
- ✅ **当前 live strategy UUID**: `28fc37e5-2d32-4ada-92e0-41c11a5103d0` (257 position_snapshot rows to 2026-04-24), S1 迁移必须保此 UUID 不变避免 orphan.

## Scope (5-7 周, 4 批交付)

### 批 1: Framework Core + DB Migration (~2 周)

**交付物**:
1. `backend/migrations/strategy_registry.sql` ⭐ 新 (~50 行, 幂等 + rollback 配对):
   - `strategy_registry` 表: `strategy_id UUID PK` / `name TEXT UNIQUE` / `rebalance_freq TEXT` / `status TEXT` / `factor_pool JSONB` / `config JSONB` / `created_at` / `updated_at` + trigger
2. `backend/platform/strategy/registry.py` ⭐ 新 (~200 行):
   - `DBStrategyRegistry(StrategyRegistry)` concrete, CRUD + audit log
   - `get_live()` / `register()` / `update_status(reason)` 实现
3. `backend/platform/strategy/allocator.py` ⭐ 新 (~80 行):
   - `EqualWeightAllocator(CapitalAllocator)` 等权 1/N, 最小 concrete
4. `backend/tests/test_strategy_registry.py` + `test_equal_weight_allocator.py` ⭐ 新 ~200 行 / ~15 tests
5. `backend/tests/smoke/test_mvp_3_2_batch_1_live.py` ⭐ 新 (铁律 10b, subprocess import check + DB migration idempotent re-run)

### 批 2: S1 MonthlyRanking 当前 PT 迁移 (~1.5 周)

**交付物**:
1. `backend/engines/strategies/s1_monthly_ranking.py` ⭐ 新 (~250 行):
   - `S1MonthlyRanking(Strategy)` concrete
   - class attrs: `strategy_id = "28fc37e5-2d32-4ada-92e0-41c11a5103d0"` (复用 live UUID!) / `factor_pool = ["turnover_mean_20","volatility_20","bp_ratio","dv_ttm"]` / `rebalance_freq = MONTHLY`
   - `generate_signals(ctx)` 内部调 **现有** `SignalComposer + PortfolioBuilder` (铁律 16 唯一信号路径不变)
   - `validate_signals()` 调 Platform 公共 validator
2. 配置 migrate: `pt_live.yaml` 参数 + `PAPER_TRADING_CONFIG` → 写入 `strategy_registry.config` JSONB
3. `backend/app/services/strategy_service.py` ⚠️ MODIFY (~50 行 delta): DB 读 S1 → 路由到 `S1MonthlyRanking`
4. 回归验证: `regression_test.py --years 5` max_diff=0 (铁律 15, S1 迁移必须 bit-identical)

### 批 3: S2 PEAD EventStrategy (~1.5 周, DRY_RUN 状态)

**关键设计决策**:
- **不依赖 DEPRECATED `pead_q1`**: S2 直接从 `earnings_announcements` 实时查 eps_surprise_pct, 避免因子重激活阻塞 (重激需 factor_lifecycle + IC 验证一周)
- **signal_day 判定**: `f_ann_date + 1 trade_date` (post-announcement day 买入, 避 announcement day 实盘滑点 spike)
- **持仓窗口**: PEAD 标准 30 日 (从买入日起 T+30 卖出)
- **过滤条件**: eps_surprise_pct > Q80 (top 20%), 每 trigger 日至多持 5 股, 行业不限

**交付物**:
1. `backend/engines/strategies/s2_pead_event.py` ⭐ 新 (~300 行):
   - `S2PEADEvent(Strategy)` concrete, `rebalance_freq = EVENT`
   - `_find_trigger_dates(ctx)`: SELECT ann_date FROM earnings_announcements WHERE f_ann_date ≤ ctx.trade_date 且 buy_day (= f_ann_date + 1) = ctx.trade_date
   - `generate_signals`: 返 Top-5 eps_surprise_pct > Q80, target_weight=1/5 each
   - `_close_expired()`: 检查持仓 holding_days ≥ 30, 生成 sell signals
2. `backend/tests/test_s2_pead_event.py` ⭐ 新 ~250 行 ~20 tests (mock earnings_announcements + ctx 多 scenario)
3. `strategy_registry` INSERT row S2 status=DRY_RUN (不跑真单, 仅走 signal 生成 + 回测)

### 批 4: Wiring + Dual-Running (~0.5 周)

**交付物**:
1. `backend/app/tasks/daily_pipeline.py` ⚠️ MODIFY (~30 行 delta):
   - 16:30 signal phase: `for strategy in registry.get_live(): strategy.generate_signals(ctx)` 替换原单策略调用
2. `backend/app/services/risk_wiring.py` ⚠️ MODIFY (~20 行 delta):
   - 多策略 per-strategy RiskEngine instance (S1 + S2 独立 risk isolation)
3. `backend/tests/smoke/test_mvp_3_2_dual_running_live.py` ⭐ 新 (铁律 10b, subprocess 启两策略路径)
4. 7 日 DRY_RUN 观察: S2 signal 数量 + S1 不受 S2 干扰 bit-identical regression

## Out-of-scope (明确排除, 铁律 23)

- ❌ **重构 signal_engine.py 内部逻辑** (SignalComposer/PortfolioBuilder 不改, S1 包一层)
- ❌ **S2 live 模式** (本 MVP DRY_RUN 只跑 signal + 回测, live 留 MVP 3.2.1 或 Wave 3 后期)
- ❌ **动态 CapitalAllocator** (等权 50/50 静态, vol-target 留 Wave 4+)
- ❌ **ExecutionAuditTrail** (MVP 3.3 scope)
- ❌ **event_bus 事件发布** (MVP 3.3/3.4 scope, 本 MVP no-op)
- ❌ **PEAD 因子重激** (S2 绕开用 earnings_announcements 原始数据, 因子重激独立路径)
- ❌ **G10 经济机制自动化** (MVP 3.5 scope)

## 5 Key Questions 自答 (Session 33 pre-research agent 遗留)

| # | Q | 自答 |
|---|---|---|
| Q1 | MVP 3.4 snapshot 粒度 | **out of scope 3.2** |
| Q2 | ExecutionAuditTrail 临时表 vs event_log | **out of scope 3.2** |
| Q3 | S2 PEAD rebalance_freq=EVENT 信号日判定? | **`f_ann_date + 1 trade_date` 买入, +30 日卖出** (批 3 settled) |
| Q4 | CapitalAllocator 动态 trigger? | **Wave 3 静态等权 50/50, Wave 4+ 再评估** |
| Q5 | G10 经济机制 Wave 3 覆盖? | **out of scope 3.2, 人工 review 保留** |

## 关键架构决策 (铁律 39 显式声明)

### S1 UUID 复用当前 live
- 选择: `S1MonthlyRanking.strategy_id = "28fc37e5-2d32-4ada-92e0-41c11a5103d0"` (当前 live UUID)
- 理由: `position_snapshot` + `trade_log` + `perf_series` 257+ rows 已按此 UUID 索引, 换 UUID 会 orphan 所有历史
- 风险缓解: 批 2 migration 脚本幂等 upsert, 回滚只 DELETE strategy_registry 行不动历史数据

### S2 PEAD 绕开 DEPRECATED 因子
- 选择: 直接从 `earnings_announcements.eps_surprise_pct` 查询, 不依赖 `pead_q1` / `sue_pead` 因子
- 理由: factor_registry 3 PEAD 变体全 DEPRECATED/warning, 重激需 factor_lifecycle IC 验证 1 周阻塞 S2 启动
- 风险缓解: S2 DRY_RUN 状态 7 日观察, 若 signal 质量差再考虑重激因子

### 铁律 16 唯一信号路径保留
- 选择: S1 `generate_signals` 内部调现有 `SignalComposer + PortfolioBuilder`, 不 refactor
- 理由: 铁律 16 要求生产/回测/研究走同一路径, 当前已对齐 (MVP 2.3 Sub3 已 settle), S1 只包一层不动核心
- 回归验证: `regression_test --years 5 --years 12` max_diff=0 (铁律 15)

## LL-059 9 步闭环 (批 1-4 各 1 PR, 共 4 PR)

批 1 `feat/mvp-3-2-batch-1-framework-core` → 批 2 `feat/mvp-3-2-batch-2-s1-migration` → 批 3 `feat/mvp-3-2-batch-3-s2-pead-dry-run` → 批 4 `feat/mvp-3-2-batch-4-wiring`

每批独立 precondition + 实施 + 硬门 + commit + PR + 2 reviewer + P1 fix + AI self-merge.

## 验证 (硬门, 铁律 10b + 40)

```bash
# 批 1
pytest backend/tests/test_strategy_registry.py backend/tests/test_equal_weight_allocator.py -v  # ~15 PASS
pytest -m smoke --timeout=180  # +1 batch_1 smoke

# 批 2 (regression critical)
pytest backend/tests/test_s1_monthly_ranking.py -v  # ~15 PASS
python scripts/run_backtest.py --config configs/pt_live.yaml  # 验证 S1 via new path 等价
python scripts/regression_test.py --years 5  # max_diff=0 (铁律 15)

# 批 3
pytest backend/tests/test_s2_pead_event.py -v  # ~20 PASS
python scripts/run_backtest.py --strategy s2_pead_event --years 3  # S2 独立回测验证

# 批 4
pytest backend/tests/smoke/test_mvp_3_2_*.py  # +2 new smoke
python scripts/run_paper_trading.py signal --dry-run  # 双策略 iteration 实测 exit=0
```

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| S1 迁移破坏 regression max_diff=0 | PT 配置漂移 | 批 2 PR 硬门 `regression_test --years 5` 必 max_diff=0, 违反则回滚 |
| S2 DRY_RUN 7 日无 PEAD 事件 | 验证不充分 | earnings_announcements 207K rows 覆盖 2015+, 必有历史 PEAD 事件, 回测可跑 3yr 历史 |
| 批 1 DB migration 冲突并发 (若 Monday 后跑) | DDL 锁 | 所有 DDL 跑在 off-peak 04:00-06:00, 单 tx commit |
| 当前 PT 运行中断 (Monday 首触发+本 MVP 实施时间重叠) | 真金生产干扰 | 批 1-4 跑在本地分支, PR merged 后 Monday 下一周 (4-28+) 生效, 首触发 4-27 不受干扰 |
| S2 event signal 与 S1 monthly rebalance 同日冲突 | 双策略订单冲突 | 独立 RiskEngine isolation (批 4), per-strategy position_snapshot, S1/S2 仓位独立不互扣 |

## Follow-up (跨 PR, 不在本 plan)

1. S2 live 启动 (DRY_RUN → LIVE 升级, 需 1 个月数据 + 独立评估)
2. PEAD 因子重激 (sue_pead warning → active, 独立 factor_lifecycle PR)
3. Multi-strategy Observability /risk dashboard (Wave 4 MVP 4.x)
4. CapitalAllocator 动态分配 (vol-target, Wave 4+)
