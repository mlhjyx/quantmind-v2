# STATUS_REPORT — T0-19 Phase 2 Implementation (2026-04-30)

**Date**: 2026-04-30 ~17:45+
**Branch**: feat/t0-19-phase2-implementation
**Base**: main @ aaa2d9b (PR #167 Phase 1 merged)
**Scope**: Phase 1 design 4 项修法**业务代码落地** + 21 unit tests + 1 critical 实测 finding
**真金风险**: 0 (LIVE_TRADING_DISABLED=true 双锁 + dry_run_audit=True 默认 self-test, 真 INSERT 留 PT 重启 gate)

---

## §0 8-Q investigation (Phase 1 design §2 verify, 0 hard STOP)

| Q | 实测 | 一致 |
|---|---|---|
| Q1 t0_19_audit.py 新文件 vs existing module | services/ 0 audit module → **NEW file** | ✅ |
| Q2 exceptions.py 现有 RuntimeError 父类 | LiveTradingDisabledError(RuntimeError) — T0_19 系列沿用 | ✅ |
| Q3 4 步顺序 FK / trigger | 5 表 0 FK 0 triggers, 顺序无 cascade | ✅ |
| Q4 hook 失败处理 | 选 (b) 各 step 独立 commit (audit trail 优先) | ✅ |
| Q5 emergency_close L306 hook 位置 | After `summary = _execute_sells(...)`, before stderr AUDIT print | ✅ |
| Q6 commission/stamp_tax 取值 | log 0 hits → NULL (沿用铁律 27 不 fabricate) | ✅ |
| Q7 weighted_avg 算法 | SUM(price*volume)/SUM(volume), 3 unit test cover | ✅ |
| Q8 cb_state reset 真值 | hardcoded ¥993,520 (--realtime 留 PT gate) | ✅ |

---

## §1 🔴 NEW Phase 2 实测 Finding (LL-094 复用规则触发, sweep 入 LL 同源)

**事件**: pytest test_dry_run_audit_e2e_real_log 期望 18 trade_log INSERT, 实测仅 17. 深查 logs/emergency_close_20260429_104354.log:

```
2026-04-29 10:43:57,400 [INFO] [QMT] 下单: 688121.SH sell 4500股
2026-04-29 10:43:57,506 [ERROR] [QMT] 下单失败: order_id=1090551149, error_id=-61,
    error_msg=最优五档即时成交剩余撤销卖出 [SH688121] [COUNTER]
    [251005][证券可用数量不足]
2026-04-29 10:43:57,506 [INFO] [QMT] 委托回报: order_id=1090551149,
    code=688121.SH, status=57, traded=0/4500
```

→ **18 orders placed, 17 fills (status=56), 1 FAILED (688121.SH 4500 股, status=57, "证券可用数量不足")**.

### 推翻 PR #166 narrative v3 部分 claim

| 项 | PR #166 claim | 实测 (Phase 2) |
|---|---|---|
| 18 股全 status=56 | ✅ all filled | ❌ **17 status=56 + 1 status=57 (688121 cancelled)** |
| 18 unique tickers | ✅ 18 places + 18 fills | ⚠️ 18 places + 17 fills, 18 unique codes (含 688121 placed but failed) |
| 真账户 4-30 0 持仓 | ✅ verified xtquant | ✅ 仍正确 (688121 后续被卖, 路径未知) |
| -¥18,194 NAV diff | ✅ 17 股 fill 加成本 | ✅ ~match (688121 在 4-29~4-30 间被另路径卖, 价差合算) |

**688121.SH 4500 股 后续路径**: 4-29 emergency_close 失败 → 4-30 14:54 xtquant 实测 0 持仓 → **路径仍未知** (可能 user 4-30 GUI sell 1 股 / 隔日早盘成交 / 或其他). 这部分 D3-A Step 4 v1+v2 narrative "user 4-30 GUI 手工 sell 18 股" 可能**部分回归** (至少 688121 这 1 笔), 但 v3 narrative 主体 (CC 4-29 emergency_close 17 股) 仍正确.

### Phase 2 实现正确处理 17 fills

- ✅ trade_log backfill 仅 17 行 (沿用铁律 27 不 fabricate 失败单)
- ✅ risk_event_log audit row `shares=submitted_count` (sells_summary 含真实 submitted, 非 18 假设)
- ✅ test_parse_real_log_17_fills_not_18 单元测试锁定此实测
- ⚠️ docstring + module DESC 用 "N rows" 占位 (避免 hardcode 18 vs 17 漂移)

### Tier 0 债不变 (T0-19 仍 P1, 修法范围未扩)

T0-19 修法范围未变 (4 项), 但 audit chain 完整性需补:
- 688121.SH 4500 股 4-29 失败单 audit: 当前 trade_log 不写 (正确), risk_event_log audit row reason 字段含失败单引用 (本 Phase 2 已实现, context.sells_summary.failed_count)
- 后续路径 forensic: 留 D3 整合 PR / 批 2 (查 xtquant later session log + QMT GUI manual sell log)

### LL 累计 26 → 27 候选 (Phase 2 发现, sweep 入 D3 整合 PR / Phase 3)

> LL-095 候选: emergency_close 失败单 (status=57) 与成功单 (status=56) 区分必要 — backfill 仅 fill, 不 fill failed orders. 沿用铁律 27 不 fabricate 跨场景固化. 关联 case: 688121.SH 4-29 "证券可用数量不足".

---

## §2 5 Deliverables 落地

### (a) backend/app/services/t0_19_audit.py (新, 458 行)

8 主函数:
- `write_post_close_audit` (主入口, 4 步骤 orchestration)
- `_collect_chat_authorization` (Phase 1 §2.4 schema)
- `_check_idempotency` (双保险 trade_log + flag file)
- `_parse_emergency_close_log` (regex 提取 fill events)
- `_aggregate_fill_per_order` (weighted_avg)
- `_backfill_trade_log` / `_write_risk_event_log_audit` /
  `_write_performance_series_row` / `_clear_position_snapshot_and_reset_cb_state`
- `_write_idempotency_flag`

关键设计:
- `dry_run_audit=True` 默认 hook 跳真 INSERT, 仅 print SQL (Phase 2 self-test)
- LL-094 复用: CHECK enum 常量 RISK_EVENT_LOG_ACTION_ENUM = {"sell","alert_only","bypass"}
- 铁律 27: commission/stamp_tax NULL (log 无)
- LL-066 例外: subset INSERT 不走 DataPipeline (会 cascade NULL 其他列)

### (b) backend/app/exceptions.py (+57 行, 3 新 exception)

- T0_19_AlreadyBackfilledError (RuntimeError) — 重入检测
- T0_19_AuditCheckError (RuntimeError) — CHECK constraint 违反
- T0_19_LogParseError (RuntimeError) — log 解析失败

沿用 LiveTradingDisabledError 风格 (RuntimeError 父类 + 详细 docstring + 触发场景 + 复用规则).

### (c) scripts/emergency_close_all_positions.py L306+ hook insertion (+22 行)

```python
summary = _execute_sells(broker, sellable)

# T0-19 post-execution audit hook (Phase 2 PR #168, design Q8)
try:
    from app.services.t0_19_audit import write_post_close_audit
    from app.services.t0_19_audit import _collect_chat_authorization

    audit_summary = write_post_close_audit(
        broker=broker, sells_summary=summary, log_file=LOG_FILE,
        chat_authorization=_collect_chat_authorization(args),
        dry_run_audit=False,
    )
    ...
except Exception as hook_err:
    logger.error("[T0-19 audit hook] FAILED: %s", hook_err, exc_info=True)
```

铁律 33 fail-loud: hook 失败 stderr + log, **不阻 sells 完成** (audit trail 优先, sells 已成功).

### (d) backend/tests/test_t0_19_audit.py (新, 21 tests, 全 PASS)

测试 case 覆盖:

| 类别 | tests | 覆盖 |
|---|---|---|
| weighted_avg 算法 | 3 | single fill / multi partial fills (002623) / zero volume edge |
| Real log parse | 2 | **17 fills (NOT 18)** + 17 specific tickers (688121 NOT in fills) |
| LogParseError | 4 | missing file / empty file / no fills / unparseable filename |
| AlreadyBackfilledError | 3 | trade_log reentry / flag file exists / clean passes |
| AuditCheckError enum (LL-094) | 2 | action_taken enum / severity enum |
| 4-29 trade_date enforcement (修订 1) | 3 | trade_log / performance_series / risk_event_log 全 4-29 not 4-30 |
| chat_authorization signature | 2 | chat-driven / interactive mode |
| E2E dry-run real log | 2 | 17 fills + filename 推断 |

测试结果:
```
============================= 21 passed in 0.07s ==============================
```

### (e) docs/audit/STATUS_REPORT_2026_04_30_T0_19_phase_2_implementation.md (本文件)

---

## §3 verifier 实测 (4/5 PASS, check 5 subprocess 跳)

```
LIVE_TRADING_DISABLED: PASS — LIVE_TRADING_DISABLED=True (config.py default) ✓
t0_19_audit module:    PASS — t0_19_audit.py + 4 函数全在
exceptions classes:    PASS — 3 exception 类全在
emergency_close hook:  PASS — T0-19 hook 已插入 (3 关键字 grep ✓)
dry-run subprocess:    SKIP (subprocess 会真连 QMT, 本 PR 不跑, 留 PT 重启 gate user 决议时跑)
```

Phase 2 implementation 4/5 PASS = 符合 Phase 1 design 期望.

---

## §4 硬门验证

| 硬门 | 结果 |
|---|---|
| pytest test_t0_19_audit | ✅ 21/21 PASS in 0.07s |
| ruff scripts + backend/app/services + backend/app | (push 时 pre-push smoke 验) |
| pre-push smoke | (push 时 hook 跑) |
| 0 真 INSERT (DB) | ✅ dry_run_audit=True 默认 + 测试全 mock conn |
| 0 触 LIVE_TRADING_DISABLED | ✅ 不动 .env / 不动 config.py default True |
| 0 .env / configs/ 改 | ✅ |
| 0 服务重启 | ✅ |
| 0 实战 sell / 0 xtquant order_stock | ✅ 测试不 spawn emergency_close subprocess |
| 0 schema 改 / 0 alembic upgrade | ✅ 沿用 trade_log 现有 schema (Q2 实测 reject_reason sentinel) |

---

## §5 Tier 0 债 + LL 累计

- **Tier 0 债 16 项不变** (T0-19 修法落地 = 业务代码 ✅, 真 INSERT 路径留 PT 重启 gate user 授权下次跑 emergency_close 时触发)
- **LL 累计 27 → 28 候选** (LL-095 emergency_close failed 单 ≠ filled 单, sweep 入 D3 整合 PR / Phase 3)

---

## §6 关联

- T0-19 来源: PR #166 SHUTDOWN_NOTICE_2026_04_30 §6 + STATUS_REPORT_D3_C F-D3C-13
- Phase 1 design: docs/audit/STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md (PR #167)
- 实测推翻 narrative v3 部分: PR #166 "18 股全 status=56" → 17 status=56 + 1 status=57
- LL-094 复用 (CHECK enum 实测): 本 audit 模块固化 RISK_EVENT_LOG_*_ENUM 常量 + 单元测试
- LL-095 候选 (failed vs filled 区分): sweep 入 D3 整合 PR / Phase 3

---

## §7 下一步

1. **Phase 2 PR (本 PR) self-merge** (此 PR 完结闭环, T0-19 业务代码上)
2. **D3 整合 PR** (CLAUDE.md / SHUTDOWN_NOTICE / memory frontmatter narrative 同步 17 vs 18 修订)
3. **批 2 P0 修启动** (T0-15/16/18/19 + F-D3A-1 真 INSERT 路径解锁 PT 重启 gate)
4. **PT 重启 gate user 决议时** scripts/audit/check_t0_19_implementation.py + check_pt_restart_gate.py 跑全 ✅

---

## §8 用户接触

实际 0 (Phase 2 完全自驱动). 唯一用户决议点为 PT 重启 gate (留 user 真金授权).
