# PT 重启 gate cleanup — DB stale + cb_state reset (2026-04-30 ~19:55)

**PR**: chore/pt-restart-gate-db-cleanup
**Base**: main @ 1a6f959 (PR #170 批 2 P0 修 merged)
**Scope**: DELETE position_snapshot 4-28 stale (19 rows) + UPDATE cb_state nav → ¥993,520.16 + audit row INSERT
**真金风险**: 0 (DML scope 限定, 0 改业务代码 / 0 .env / 0 服务重启)

---

## §1 触发

PR #170 批 2 P0 修后 PT 重启 gate 5/7 PASS, 剩 2 项 = DB stale 清 + cb_state nav reset (T0-19 / 真账户 ground truth 落地). User 决议 A → B → C 一条龙, 本 PR (A) 闭合最后 2 hard-gate prerequisites.

## §2 8-Q forensic 实测 (0 STOP)

| Q | 实测 | 结论 |
|---|---|---|
| 1 | `SELECT COUNT(*) WHERE trade_date='2026-04-28' AND execution_mode='live'` → 19 | ✅ 与 PR #166 v3 一致 |
| 2 | 19 ticker = 18 (PR #169 v4 narrative) + **000012.SZ** (南玻, Session 44 user 4-28 前手工 sold, 4-28 snapshot stale 含此码) | ✅ 已知差异 |
| 3 | `grep position_snapshot.*4-28 backend/ scripts/` → 仅 audit 脚本 docstring (cosmetic, 非生产 read) | ✅ 0 production refs |
| 4 | `\d+ position_snapshot` triggers + FK refs → 0 / 0 | ✅ DELETE safe (Phase 1 §1 Q5 沿用) |
| 5 | cb_state.live `id=116bd790-4b87-4545-9856-e791dc5698ed`, nav=1,011,714.08 stale (4-28 16:30 last update) | ✅ 与 PR #168 Phase 1 §1 Q4 一致 |
| 6 | `\d+ circuit_breaker_state` triggers → 0 | ✅ UPDATE safe |
| 7 | 单 transaction (BEGIN/COMMIT) | ✅ 默认 |
| 8 | post-DML 期望 check_pt_restart_gate.py 7/7 PASS exit 0 | ✅ 实测达标 |

附加 verify: `SELECT trade_date, COUNT(*) FROM position_snapshot WHERE trade_date >= '2026-04-29' AND execution_mode='live'` → **0 rows** (4-29 + 4-30 真清仓后 0 行存在, DELETE 4-28 不影响其他日期) ✅

## §3 SQL 执行 (单 transaction)

```sql
BEGIN;

-- Step 1: DELETE 4-28 stale 19 行
DELETE FROM position_snapshot
 WHERE trade_date = '2026-04-28' AND execution_mode = 'live';
-- DELETE 19  ✅

-- Step 2: cb_state nav reset (jsonb_set 仅改 nav 字段, 保留其他 metrics)
UPDATE circuit_breaker_state
   SET trigger_metrics = jsonb_set(
         COALESCE(trigger_metrics, '{}'::jsonb),
         '{nav}', '993520.16'::jsonb, true),
       trigger_reason = 'PT restart gate cleanup 2026-04-30 (DB stale → 真账户 ground truth)',
       updated_at = NOW()
 WHERE id = '116bd790-4b87-4545-9856-e791dc5698ed';
-- UPDATE 1  ✅

-- Step 3: audit INSERT (LL-094 CHECK enum 验证)
INSERT INTO risk_event_log (
    strategy_id, execution_mode, rule_id, severity, triggered_at,
    code, shares, reason, context_snapshot, action_taken, action_result, created_at
) VALUES (
    '28fc37e5-2d32-4ada-92e0-41c11a5103d0', 'live',
    'pt_restart_gate_db_cleanup_2026_04_30', 'info', NOW(),
    '', 0,
    'PT 重启 gate cleanup: DELETE position_snapshot 4-28 stale (19 rows) + ...',
    '{"delete_rows": 19, "update_id": "116bd790-...", "nav_before": 1011714.08, "nav_after": 993520.16, ...}'::jsonb,
    'alert_only',
    '{"status": "logged_only", "audit_chain": "complete", "gate": "pt_restart_2/7"}'::jsonb,
    NOW()
);
-- INSERT id = e1598f37-45b8-44bd-bfdd-e67c8f532ed5  ✅

COMMIT;
```

## §4 Post-DML verify

| Check | Pre | Post |
|---|---|---|
| position_snapshot WHERE trade_date='2026-04-28' AND execution_mode='live' | 19 | **0** ✅ |
| circuit_breaker_state.live.trigger_metrics->>'nav' | 1,011,714.08 | **993,520.16** ✅ (= ground truth, diff 0.00) |
| risk_event_log audit row | (none) | id=`e1598f37-45b8-44bd-bfdd-e67c8f532ed5` ✅ |

## §5 PT 重启 gate 7/7 PASS ✅

```
check_pt_restart_gate.py 实测输出:
   1  T0-15 LL-081 v2 (QMT 断连/fallback cover)              ✅ PASS
   2  T0-16 qmt_data_service fail-loud                     ✅ PASS
   3  T0-18 铁律 X9 (schedule 注释后必 restart)                  ✅ PASS
   4  T0-19 emergency_close audit hook                     ✅ PASS
   5  F-D3A-1 3 missing migrations apply                   ✅ PASS
   6  DB 4-28 19 股 stale snapshot 清理                       ✅ PASS
   7  cb_state live reset ¥993,520 (实测真账户)                 ✅ PASS
✅ GATE CLEARED — 全部 7/7 prerequisites ✓
```

## §6 LL-094 复用 (CHECK enum 实测)

audit row 用 `severity='info'` + `action_taken='alert_only'` (LL-094 enum 验证). 沿用 LL-094 复用规则: SQL INSERT 含 CHECK 字段前必 `pg_get_constraintdef` 实测 (本 PR 沿用 PR #161 + Phase 1 §1 Q3 已验证 enum, 0 STOP 触发).

## §7 不变

- Tier 0 债 11 项不变 (本 PR 不动)
- LL 累计 31 不变 (本 PR 不加新 LL)
- 0 业务代码 / 0 .env / 0 服务重启 / 0 真金 sell / 0 触 LIVE_TRADING_DISABLED

## §8 关联

- PR #170 (批 2 P0 修, T0-15/16/18 + F-D3A-1 落地)
- PR #168 (T0-19 Phase 2 业务代码)
- PR #169 (D3 整合 v4 narrative + LL-095/096)
- PR #166 §2 (xtquant 4-30 14:54 实测 ground truth ¥993,520.16 来源)
- SHUTDOWN_NOTICE §9 v3 prerequisite list

## §9 下一步 (B paper-mode 5d dry-run)

PT 重启 gate **7/7 PASS, 仅剩 2 项手工 user 决议项**:
- (B) paper-mode 5d dry-run (5 个交易日观察期)
- (C) `.env paper→live` 显式授权 (LIVE_TRADING_DISABLED 二级硬开关)

本 PR 完结后, 启 (B) paper-mode dry-run 准备工作 (Servy / schtask Disabled→Auto + ops checklist).
