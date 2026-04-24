# MVP 3.1 批 3 · CircuitBreaker Rule Adapter (Hybrid Wrapper 方案 C)

> **ADR**: [ADR-010](../adr/ADR-010-pms-deprecation-risk-framework.md) + [ADR-010 addendum](../adr/ADR-010-addendum-cb-feasibility.md)
> **Plan**: Session 30 末, plan file `C:\Users\hd\.claude\plans\concurrent-sleeping-bird.md`
> **前置**: 批 1 PMS (Session 29 PR #55/#57/#58) + 批 2 intraday (Session 30 PR #59/#60)
> **状态**: 批 3 实施完成 — Hybrid adapter ~200 行, 包现有 `risk_control_service.py` 1640 行不重写
> **耗时**: ~0.5 周 (从原估 ~500 行 async→sync 重写降至 ~200 行 adapter)

---

## 1 · 批 3 目标

**In-scope**:
1. `backend/platform/risk/rules/circuit_breaker.py`: `CircuitBreakerRule` Hybrid adapter (~200 行)
2. `backend/platform/risk/rules/__init__.py`: 导出 `CircuitBreakerRule` (+1 export)
3. `backend/app/services/risk_wiring.py`: `build_circuit_breaker_rule()` factory (+~30 行)
4. `backend/app/tasks/daily_pipeline.py`: `risk_daily_check_task` 注入 CB via `extra_rules` (+~5 行 delta)
5. `backend/tests/test_risk_rules_circuit_breaker.py`: 19 L1 unit tests
6. `backend/tests/smoke/test_mvp_3_1_batch_3_live.py`: 1 L4 smoke (铁律 10b)
7. 本设计文档 `docs/mvp/MVP_3_1_batch_3_cb_wrapper.md`

**Out-of-scope** (铁律 23 最小变动):
- ❌ 重写 `risk_control_service.py` 1640 行 async → sync
- ❌ 删 `circuit_breaker_state` / `circuit_breaker_log` 老表 (Sunset gate 满足后批 3b)
- ❌ 删 `scripts/approve_l4.py` L4 人工审批 CLI (独立运维保留)
- ❌ 删老 `run_paper_trading.py` signal_phase 调 `check_circuit_breaker_sync` 点
- ❌ ADR-003 `risk.triggered` 事件名同步 (跨 PR, 另立)

---

## 2 · 架构决策回顾

### 2.1 方案 C Hybrid Wrapper (ADR-010 addendum)

| 方案 | 工作量 | 风险 | 决策 |
|---|---|---|---|
| A. 完整重写 1640 行 async→sync | ~500 行 | 高 (状态机破坏) | ❌ |
| B. CB 完全不接 Risk Framework | 0 | — | ❌ (ADR-010 "统一监控" 目标不完整) |
| **C. Hybrid adapter ~200 行** | **~200 行** | **低** | **✅ 采纳** |
| D. 扩展 sync API 签名返 transition | ~200 行 | 中 (侵老 caller) | ❌ (caller regression) |

### 2.2 铁律 31 **例外声明** (ADR-010 addendum 明确接受)

- 标准: `backend/platform/**` Engine 纯计算, 不 IO
- 批 3 特例: `CircuitBreakerRule.evaluate` 调 `check_circuit_breaker_sync` 内部 DB commit + NotificationService
- **接受依据**: 重写 1640 行风险 >> 违反 P31 代价
- **缓解**: adapter 职责最小化 (调 sync API + diff snapshot + 返 RuleResult), 状态机核心逻辑仍在 `risk_control_service.py`
- **Sunset gate 后**: 批 3b inline 重审消除此例外

### 2.3 单 Rule 多 rule_id (vs 4 子类)

- 选择: 单 `CircuitBreakerRule` 类, RuleResult.rule_id 动态 `cb_escalate_l{N}` / `cb_recover_l{N}` (8 可能值)
- 模式对齐: 批 1 `PMSRule` (L1/L2/L3 单类) + 批 2 `IntradayPortfolioDropRule` (3 子类)
- 优势: 避免 4 子类重复 `check_circuit_breaker_sync` 调用 (单 adapter 一次 sync + 状态 diff 判 transition)

### 2.4 挂 daily 不挂 intraday

- 批 2 intraday Celery Beat 5min × 72 次/日 — 不加 CB 避免 `_upsert_cb_state_sync` 频率放大
- 批 1 daily Celery Beat 14:30 — 加 CB (CB 阈值日频语义, 1 次/日 足够)
- 未来评估: 若 CB 需盘中触发, 抽 read-only passive check 分离

---

## 3 · 实施细节

### 3.1 `CircuitBreakerRule.evaluate` 流程

```
1. 读 prev_level = SELECT level FROM circuit_breaker_state WHERE strategy=? AND mode=?
   (首次运行 / 表不存在 → fallback L0)
2. 调 check_circuit_breaker_sync(conn, strategy_id, date, initial_capital)
   (内部: _ensure_cb_tables_sync → 评估 5 级状态 → _upsert_cb_state_sync → 通知)
3. new_level = result["level"]
4. IF prev == new: return [] (no event, 铁律 33 只真 transition 入 log)
5. IF new > prev: rule_id=f"cb_escalate_l{new}"
6. IF new < prev: rule_id=f"cb_recover_l{new}"
```

### 3.2 rule_id 动态模式 (对齐批 1 PMSRule)

| Transition | rule_id | Example |
|---|---|---|
| L0 → L1 | `cb_escalate_l1` | 单策略日亏 > 3% |
| L0 → L2 | `cb_escalate_l2` | 总组合日亏 > 5% |
| L1 → L3 | `cb_escalate_l3` | 滚动 5d/20d 亏损 |
| L2 → L4 | `cb_escalate_l4` | 累计亏损 > 25% |
| L1 → L0 | `cb_recover_l0` | 次日自动恢复 |
| L3 → L2 | `cb_recover_l2` | 降级部分恢复 |
| L4 → L0 | `cb_recover_l0` | 人工 approve 后完全恢复 |

### 3.3 `root_rule_id_for` 反查

- `cb_escalate_l*` / `cb_recover_l*` → `"circuit_breaker"` (ownership)
- 其他 triggered_id → passthrough (非 CB pattern)

---

## 4 · 验证硬门 (实测数字)

| 硬门 | 结果 |
|---|---|
| pytest CB unit (19 tests) | 19 PASS ✅ |
| pytest 全 risk + smoke regression | 105 + 20 new = **125 PASS** ✅ |
| pre-push smoke (铁律 10b) | 33 PASS (批 1 31 + 批 2 1 + 批 3 1) ✅ |
| ruff clean (7 files) | Clean ✅ |

---

## 5 · Sunset Gate (ADR-010 addendum Follow-up §5)

批 3 adapter merged 后 **不立即删老代码**. 满足 **A+B+C** 其一后启动批 3b (wrapper inline + 老表 DROP):

- **条件 A** (必): adapter live 30 日 + `risk_event_log.rule_id LIKE 'cb_%'` 有 ≥1 真事件 (非 smoke)
- **条件 B** (必): 1 次 L4 审批完整跑通 (`approve_l4.py` CLI → `approval_queue` → `cb_recover_l0` event → signal_engine multiplier=1.0)
- **条件 C** (或): Wave 4 Observability MVP 4.x 启动, `/risk` dashboard 统一可视化替代 `/risk_control` 老 API

未满足前延续并存, 避免 PMS F30 死码覆辙 (position_monitor 0 行 10 个月未发现).

---

## 6 · L4 人工审批流程 (并行保留)

```
L4 触发 → circuit_breaker_state.level=4 + approval_queue.status='pending'
  ↓
scripts/approve_l4.py --list  # 运维查看待审批
scripts/approve_l4.py --approve <approval_id>  # 审批通过
  ↓
approval_queue.status='approved'
  ↓
下一次 daily_risk_check_task (14:30) → CircuitBreakerRule.evaluate:
  - prev_level=4, check_circuit_breaker_sync 检测 approved → new_level=0
  - 返 RuleResult(rule_id='cb_recover_l0') + risk_event_log 记录
```

adapter 仅 **read + report**, approve_l4 独立运维. 无冲突.

---

## 7 · Follow-up (跨 PR, 不在本 MVP)

1. **ADR-003 事件名同步**: 清单加 `risk.triggered` 取代 `pms.triggered` (独立 PR)
2. **QPB v1.7 → v1.8**: 批 3 完结 bump, MVP 3.1 状态改 ✅
3. **Session handoff 更新**: `memory/project_sprint_state.md` Session 30 末 (铁律 37)
4. **Sunset gate 监控**: 设 Wave 4 Observability 启动前 30 日触发 A+B+C 检查脚本

---

## 8 · MVP 3.1 Risk Framework 整体总结

| 批 | 内容 | Session | PR | 行数 |
|---|---|---|---|---|
| 批 0 | Feasibility spike (ADR-010 addendum) | Session 27 | - | 250 docs |
| 批 1 | Framework core + PMS L1/L2/L3 | Session 29 | #55 + #57 + #58 | ~800 |
| 批 2 | intraday 4 rules + Celery Beat 5min | Session 30 | #59 + #60 | ~1100 |
| **批 3** | **CircuitBreaker Hybrid wrapper** | **Session 30 末** | **(本 PR)** | **~500** |

**MVP 3.1 Risk Framework 正式完结** ✅. 5 碎片监控统一, 批 3b Sunset gate 后老代码 DROP.

---

**END of MVP 3.1 批 3 设计文档**
