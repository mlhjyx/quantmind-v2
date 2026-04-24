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
class CircuitBreakerRule(RiskRule):
    """薄 adapter: 包 risk_control_service 状态机, 不重写核心逻辑.

    evaluate() 只返 **状态变更事件** (Escalate/Recover 当次触发) 用于 risk_event_log
    审计; 不试图表达跨日状态机 / L4 审批流.
    Engine 的 execute() 对 CB events 走 no-op action (CB 本身通过 get_position_multiplier
    影响 signal_engine, 非 Risk Engine 直调 broker).
    """
    rule_id = "cb_state_change"
    severity = Severity.P1
    action = "alert_only"  # CB 自身不卖, Risk Engine 只记 log + 钉钉

    def __init__(self, cb_service):
        self._cb = cb_service  # 复用 risk_control_service 实例

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        # 调老 check_circuit_breaker_sync (L1349), 已 sync 不需重写 async
        transition = self._cb.check_and_update_sync(
            strategy_id=context.strategy_id,
            execution_mode=context.execution_mode,
            trade_date=context.timestamp.date(),
            daily_return=context.portfolio_daily_return,
            ...
        )
        if transition is None or transition.prev_level == transition.new_level:
            return []
        return [RuleResult(
            rule_id=f"cb_{transition.transition_type}_{transition.new_level.name.lower()}",
            severity=Severity.P1 if transition.new_level >= 3 else Severity.WARNING,
            trigger_reason=transition.reason,
            trigger_metrics=transition.metrics,
        )]
```

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

## Consequences

### Positive
- **批 3 工作量降 60%** (从 ~500 行 async→sync 重写 + rules → ~200 行 wrapper + tests)
- **async→sync 迁移风险移除**: 不触碰 1030 行状态机核心
- **批 3 时长重估**: 1-1.5 周 → 0.5-0.7 周
- **MVP 3.1 总工作量重估**: 2.5-3.5 周 → **2-2.7 周** (批 0 1-2h + 批 1 1 周 + 批 2 0.5 周 + 批 3 0.5-0.7 周)

### Negative
- CB 仍保留独立存储 (`circuit_breaker_state` 表), 非 `risk_event_log` 单源. 事件流审计 OK (Event 会入 event_log), 当前状态查询需读两表
- 老 `risk_control_service.py` 1030 行保留 ~2 月 (批 3 稳定后择机二次重构)

### Neutral
- 对 MVP 3.2/3.3/3.4 无影响: Risk Framework 对外接口 (RiskEngine / run / execute) 不变, 内部 CB 实现细节不暴露

## Follow-up (MVP 3.1 批次调整)

1. **MVP_3_1_risk_framework.md 更新**: 批 3 从 "async→sync 重写" 改为 "CBRule adapter 复用", 耗时 1-1.5 周 → 0.5-0.7 周
2. **批 1 启动不受影响**: Framework core + PMS 迁入按原计划
3. **批 3 设计文档**: 新增 `docs/mvp/MVP_3_1_batch_3_cb_wrapper.md` (批 3 启动前, 不预写) 详化 CBRule adapter + cb_state_change rule_id 命名 + risk_event_log 与 circuit_breaker_state 查询分工

## Related
- ADR-010 PMS Deprecation (parent)
- MVP_3_1_risk_framework.md (批 0 产出落地点)
- 铁律 24 单一职责 (方案 C 保持 RiskRule 抽象纯净)
- 铁律 31 Engine 纯计算 (方案 C 保持 Risk Framework 薄, 复杂状态机留在 service 层)
- 铁律 36 Precondition (本 spike 是铁律 36 严格执行 — 先读 1030 行代码再决策)
