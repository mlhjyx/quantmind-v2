---
adr_id: ADR-010-addendum
title: Circuit Breaker 状态机映射 RiskRule 可行性 Spike (Wave 3 MVP 3.1 批 0)
status: accepted
parent_adr: ADR-010
related_ironlaws: [24, 31, 36]
recorded_at: 2026-04-24
---

## Context

MVP 3.1 `docs/mvp/MVP_3_1_risk_framework.md` §"实施结构" 明确批 0 feasibility
spike 目标: 验证 `RiskRule` / `RiskContext` 抽象能否干净映射 circuit_breaker
L1-L4 状态机. 若不 fit, 立即调整 RiskRule interface, 不等批 1 上线再发现 split-brain.

本 addendum 是批 0 spike 产出, Session 27 (2026-04-24) 完成.

## 实测分析: risk_control_service.py 关键结构 (1639 行)

### CB 状态机 5 级
```python
class CircuitBreakerLevel(enum.IntEnum):
    NORMAL = 0         # 正常
    L1_PAUSED = 1      # 单策略日亏>3%, 暂停1天
    L2_HALTED = 2      # 总组合日亏>5%, 全部暂停
    L3_REDUCED = 3     # 月亏>10%, 降仓50%
    L4_STOPPED = 4     # 累计>25%, 停止交易 (需人工审批)
```

### 与 RiskRule 抽象的 4 个冲突点

**冲突 1: Cross-invocation state (持久化状态机)**
- CB `check_and_update()` 读 `current_level` 从 `circuit_breaker_state` 表
- `recovery_streak_days` / `recovery_streak_return` 跨日累积 (需 L3 连续 5 日 +2% 才自动降级)
- `MVP 3.1 D1 RiskContext` 是 frozen dataclass 纯数据, 无持久化字段语义
- RiskRule 默认契约 `evaluate(context) -> list[RuleResult]` 是 stateless

**冲突 2: L4 人工审批 (外部系统依赖)**
- L4 恢复需 `approval_queue` 表 entry + `scripts/approve_l4.py` CLI + `approve_l4_recovery()` 异步调用
- RiskRule.evaluate 返 `list[RuleResult]` 语义是"规则评估产物", 无法表达"等待外部审批中"
- `CircuitBreakerState.approval_id: UUID | None` 字段跨调用携带

**冲突 3: Action 模型 (非立即卖)**
- MVP 3.1 D2 `action: Literal["sell", "alert_only", "bypass"]`
- CB 触发 → `get_position_multiplier` 返 [0.0, 0.5, 0.75, 1.0] 调整**未来信号 sizing**
- L1/L2 = 暂停 1 日 (skip today's signal), L3 = 降仓 50% (multiplier=0.5), L4 = stop
- 这是 **"影响未来调度的 throttle"**, 非 "sell N shares now"

**冲突 4: Escalate vs Recover 双向转移**
- RuleResult 语义是 "触发 → 动作", 无"恢复 → 撤销先前动作"对称语义
- CB 有 `TransitionType.ESCALATE / RECOVER / MANUAL` 三向状态机
- `_check_recovery_conditions` + `_update_recovery_streak` 逻辑复杂 (streak 重置 / 部分满足 / L4 approval gate)

## 结论

**❌ 当前 RiskRule/RiskContext 抽象不适合直接承载 CB L1-L4 完整状态机.**

批 3 若强行 async→sync 重写 + 装入 RiskRule, 会:
- (a) 污染 `RiskContext` 加 `cb_state_history` / `approval_queue_ctx` 等特殊字段, 破坏铁律 24 单一职责
- (b) 扩展 `action` 枚举加 `"adjust_multiplier"` / `"wait_approval"`, Engine._execute 分支膨胀
- (c) `RiskRule.evaluate` 返回类型需扩展表达状态转移而非触发事件, 偏离设计

## Decision (修正 MVP 3.1 批 3 方案)

### 方案 C — Hybrid wrapper (推荐)

将 CB 作 **orthogonal concern** 保留现有 `risk_control_service`, 以**薄 adapter** 接入 Risk Engine:

```python
# backend/platform/risk/rules/circuit_breaker_adapter.py
#
# Reviewer P1-1 修正 (2026-04-24): 真实 sync API 签名实测 risk_control_service.py:1349
# def check_circuit_breaker_sync(conn, strategy_id, exec_date, initial_capital) -> dict
# 返 {"level", "action", "reason", "position_multiplier", "recovery_info"}, 无 transition
# 对象. Adapter 读 circuit_breaker_state 表前后快照 (字段 prev_level 已存, L101/288/742)
# 推导 transition, 不需改 sync API 签名 (方案 D 被 dismiss, 见下).
class CircuitBreakerRule(RiskRule):
    """薄 adapter: 包 risk_control_service 状态机, 不重写核心逻辑.

    evaluate() 查 DB pre-snapshot → 调 check_circuit_breaker_sync (触发 state 变更 +
    _upsert_cb_state_sync DB commit) → 查 post-snapshot → diff 推导 transition →
    仅在 level 变化时返 RuleResult.
    Engine 的 execute() 对 CB events 走 action='alert_only' (写 risk_event_log +
    钉钉). CB 本身通过 get_position_multiplier 影响 signal_engine 未来 sizing,
    非 Risk Engine 直调 broker.
    """
    severity = Severity.P1
    action = "alert_only"

    def __init__(self, conn_factory, initial_capital: float):
        self._conn_factory = conn_factory
        self._initial_capital = initial_capital

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        with self._conn_factory() as conn:
            prev_level = self._read_current_level(conn, context.strategy_id)
            # check_circuit_breaker_sync 内部动态读 settings.EXECUTION_MODE +
            # performance_series, 无需 execution_mode / daily_return 入参 (ADR-008 对齐)
            result = check_circuit_breaker_sync(
                conn,
                context.strategy_id,
                context.timestamp.date(),
                self._initial_capital,
            )
        new_level = int(result["level"])
        if new_level == prev_level:
            return []  # 无 level 变化不写事件 (铁律 33 fail-loud: 只真事件入 log)
        transition_type = "escalate" if new_level > prev_level else "recover"
        return [RuleResult(
            rule_id=f"cb_{transition_type}_l{new_level}",
            severity=Severity.P1 if new_level >= 3 else Severity.WARNING,
            trigger_reason=result["reason"],
            trigger_metrics={
                "prev_level": prev_level,
                "new_level": new_level,
                "cb_action": result["action"],  # "normal"/"pause"/"halt"/"reduce"/"stop"
                "position_multiplier": result["position_multiplier"],
                "recovery_info": result["recovery_info"],
            },
        )]

    @staticmethod
    def _read_current_level(conn, strategy_id: str) -> int:
        """读 circuit_breaker_state 当前 level (调 sync API 前). 首次运行返 0."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT level FROM circuit_breaker_state WHERE strategy_id = %s "
                "AND execution_mode = %s ORDER BY entered_date DESC LIMIT 1",
                (strategy_id, settings.EXECUTION_MODE),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0
```

**action="alert_only" 语义澄清** (reviewer P2-3 采纳): MVP 3.1 D2 `action ∈ {sell,
alert_only, bypass}` 是 **Risk Engine 执行意图** (不调 broker, 仅写 event_log + 钉钉),
不代表业务严重度. CB L4 业务严重度 (halt trading + 需人工审批) 通过 `severity=P1`
+ `rule_id=cb_escalate_l4` + `trigger_metrics.cb_action=stop` 传递, 下游 signal_engine
读 `get_position_multiplier` 实现实际 throttle. 批 3 启动前在 MVP 3.1 D2 补注释明确此
语义分离 (action = Engine 行为 vs severity+rule_id = 业务严重度).

### 方案 C 优势
- **不重写 1030 行 async → sync**: 老代码已有 `check_circuit_breaker_sync` (L1349) 可直接复用
- **CB 状态机完整独立**: `circuit_breaker_state` 表 + `approval_queue` 表 + CLI 保持原样
- **Risk Engine 只管审计 + 告警**: CB events 落 `risk_event_log` 统一格式, signal_engine 继续读 `get_position_multiplier`
- **批 3 工作量降至 ~200 行**: wrapper + 4 rule_id 名字 + tests, 从原估 ~400 行 async→sync + ~100 行 rules = ~500 行 降至 ~200 行

### 方案 C 劣势 + 接受
- CB 状态仍在老表 (`circuit_breaker_state`), 非 `risk_event_log` 单源
  * 接受: state table 是 snapshot 语义 (当前状态), event_log 是 history 语义 (触发流)
  * 两者正交不冲突
- 双系统 (risk_control_service.py 留 + Risk Engine 走 wrapper) 2 月内并存
  * 接受: 批 3 末尾若 CB 运行稳定可择机做第二次重构把 wrapper inline

### 不推荐方案

**方案 A (原 MVP 3.1 批 3)**: 完整 async → sync 重写 + RiskRule 吞 CB 状态机
- 1030 行重写风险集中, 批 0 识别的 4 冲突未解决
- 耗时 1-1.5 周, 风险 "卡住批 1-2 已上线 split-brain"

**方案 B**: CB 完全不接 Risk Framework (最小改动)
- Wave 3 MVP 3.1 目标 "取代 5 个独立监控系统" 不完整, risk_control 仍独立
- 审计断层: CB 触发不出现在 risk_event_log

**方案 D — 扩展 `check_circuit_breaker_sync` 签名返 transition** (reviewer P1-2 补评)

最小侵入扩展老 API: 不重写 1030 行 async, 仅对 L1349 sync API 扩返回 dict 加
`prev_level` / `new_level` / `transition_type` / `metrics` 字段, adapter 零状态推导:

```python
# risk_control_service.py:1349 扩展 (非破坏, 加字段):
return {
    **existing_dict,
    "prev_level": prev_level_from_state_snapshot,
    "new_level": new_level,
    "transition_type": "escalate" | "recover" | "no_change",
    "metrics": {...},  # 触发指标 snapshot
}
```

**Dismiss 理由**:
- 工作量等价方案 C (adapter ~200 行 vs API 扩展 ~100 行 + adapter ~100 行)
- 侵入面更大: 改老 service 影响现有 14 处 caller (grep `check_circuit_breaker_sync`),
  需 regression 所有 caller; 方案 C adapter 独立新文件零侵入
- 方案 C "两表并存" 劣势在方案 D 下同样存在 (circuit_breaker_state 仍是 source of
  truth, D 只改 return payload 不改 storage), 方案 D 没解决 P2-2 Event Sourcing 集成
  问题, 优势不明显
- 决策倾向: **C > D** 因为独立 adapter 文件 maintainability + 零 caller regression;
  若未来批 3b wrapper inline 时可重新评估方案 D 融入.

## Consequences

### Positive
- **批 3 工作量降 60%** (从 ~500 行 async→sync 重写 + rules → ~200 行 wrapper + tests)
- **async→sync 迁移风险移除**: 不触碰 1030 行状态机核心
- **批 3 时长重估**: 1-1.5 周 → 0.5-0.7 周
- **MVP 3.1 总工作量重估**: 2.5-3.5 周 → **2-2.7 周** (批 0 1-2h + 批 1 1 周 + 批 2 0.5 周 + 批 3 0.5-0.7 周)

### Negative
- CB 仍保留独立存储 (`circuit_breaker_state` 表), 非 `risk_event_log` 单源. 事件流审计 OK (Event 会入 event_log), 当前状态查询需读两表
- 老 `risk_control_service.py` 1030 行保留 ~2 月 (批 3 稳定后择机二次重构)

### Neutral / 下游 MVP 影响 (reviewer P2-2 采纳展开)

- **MVP 3.2 Strategy Framework**: Risk Engine 对外接口 (run/execute) 不变, 内部 CB
  adapter 透明. Strategy 层调 `risk_engine.run(context)` 获 events 后走 execute,
  与其他 rule 无差别. ✅ 无影响.
- **MVP 3.3 Signal & Execution** (隐性耦合 flag): CB 影响 signal_engine 现走
  `get_position_multiplier` 直读 `circuit_breaker_state` 表. Risk Engine execute 对
  CB events 是 **no-op** (action=alert_only). 未来 MVP 3.3 若把 order routing 从
  signal_engine 抽出 (Signal Pipeline 统一入口), 这个 "signal_engine 直读 multiplier"
  的耦合必须同步迁移到 order_router → 批 3b 或 MVP 3.3 设计时 flag.
- **MVP 3.4 Event Sourcing** (集成路径决策): CB state 保留在 `circuit_breaker_state`
  表, transition 事件走 `risk_event_log` (adapter 返 RuleResult → Engine write_log).
  **关键选择**: CB events 是否进 `event_outbox` (ADR-003 Event Sourcing)?
  - **当前决策**: 进 event_outbox (统一风控可回放), rule_id=`cb_escalate_l*` /
    `cb_recover_l*` 对齐 QPB v1.6 §event 重命名 `pms.triggered → risk.triggered`
    (parent ADR-003 应同步更新事件名清单加 `risk.triggered`, 留 Follow-up)
  - 保留当前状态查询 (get_position_multiplier) 仍读 circuit_breaker_state, 事件审计
    读 event_outbox, 两源正交无冲突

## Follow-up (MVP 3.1 批次调整 + 跨 ADR 同步)

1. **MVP_3_1_risk_framework.md 更新**: 批 3 从 "async→sync 重写" 改为 "CBRule adapter 复用", 耗时 1-1.5 周 → 0.5-0.7 周 (本 PR 已改)
2. **批 1 启动不受影响**: Framework core + PMS 迁入按原计划
3. **批 3 设计文档**: 新增 `docs/mvp/MVP_3_1_batch_3_cb_wrapper.md` (批 3 启动前, 不预写)
   详化 adapter + rule_id 命名 + risk_event_log/circuit_breaker_state 分工. 必明确:
   - L4 transition adapter 返的 `cb_action=stop` 是否触发 emergency human-approval 钉钉
     (对齐 scripts/approve_l4.py CLI 手工审批流)
   - adapter 是否包裹 `conn` 事务边界 (铁律 32: check_circuit_breaker_sync 内调
     _upsert_cb_state_sync 会 DB commit, adapter 对 conn 不额外管理)
4. **ADR-003 事件名同步** (reviewer P2-1): 事件清单加 `risk.triggered` 取代
   `pms.triggered`, 对齐 QPB v1.6 §1263 L. 本 ADR addendum 不执行 (跨文档 scope),
   另开小 PR 处理.
5. **Sunset gate** (reviewer P3-1, 精确化 "2 月并存" 条件): risk_control_service.py
   + circuit_breaker_state/log 表 sunset 的硬门 (非单纯时间):
   - **条件 A** (必): 批 3 adapter live 30 日 + `risk_event_log.rule_id LIKE 'cb_%'` 有 ≥1 真事件 (非 dry-run smoke)
   - **条件 B** (必): 有 1 次 L4 审批完整跑通 (approve_l4.py CLI → approval_queue → cb_state_change event → signal_engine multiplier 恢复 1.0)
   - **条件 C** (或): Wave 4 Observability 启动, 统一 /risk dashboard 有 CB 可视化替代 /risk_control 老 API
   - 满足 A+B+C 其一后启动批 3b (wrapper inline), 否则延续并存. 避免 PMS 死码覆辙
     (F30 position_monitor 0 行 10 个月未发现).
6. **批 3b 明确化** (reviewer P3-2): 批 3b 归属 **QPB v1.6 Wave 4 Observability MVP
   4.x "Risk Framework L2 整合" 子任务**, 非 "无限延期 Wave 4+". 本 ADR addendum
   flag 此 backlog 项, QPB 下次 bump 时同步进 Wave 4 MVP 细化.

## Related
- ADR-010 PMS Deprecation (parent)
- MVP_3_1_risk_framework.md (批 0 产出落地点)
- 铁律 24 单一职责 (方案 C 保持 RiskRule 抽象纯净)
- 铁律 31 Engine 纯计算 (方案 C 保持 Risk Framework 薄, 复杂状态机留在 service 层)
- 铁律 36 Precondition (本 spike 是铁律 36 严格执行 — 先读 1030 行代码再决策)
