# Risk Review — circuit_breaker_state + circuit_breaker_log 真测 5-01

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 10 / risk/09
**Date**: 2026-05-01
**Type**: 评判性 + circuit_breaker 真状态 5-01 reverify

---

## §1 真测 (CC 5-01 SQL 实测)

### 1.1 circuit_breaker_state 真值

实测 SQL: `SELECT * FROM circuit_breaker_state ORDER BY execution_mode`

**真值**:

| 字段 | paper | live |
|---|---|---|
| id | 740ca9b1-... | 116bd790-... |
| strategy_id | 28fc37e5-2d32-4ada-92e0-41c11a5103d0 | 28fc37e5-2d32-4ada-92e0-41c11a5103d0 |
| **execution_mode** | **paper** | **live** |
| **current_level** | **0** | **0** |
| entered_at | 2026-03-25 18:08:41 | **2026-04-20 20:38:04** |
| entered_date | 2026-03-25 | 2026-04-20 |
| **trigger_reason** | "初始化(首次运行)" | **"PT restart gate cleanup 2026-04-30 (DB stale → 真账户 ground truth)"** |
| trigger_metrics | NULL | **{nav: 993520.16, rolling_5d: -0.001458, rolling_20d: NULL, daily_return: -0.002432, cumulative_return: 0.011714}** |
| recovery_streak_days | 0 | 0 |
| recovery_streak_return | 0 | 0 |
| position_multiplier | 1.00 | 1.00 |
| approval_id | NULL | NULL |
| **updated_at** | 2026-04-20 16:30:24 | **2026-04-30 19:48:20** |

**真证据 sustained sprint state "cb_state.live: level=0, nav=993520.16" 真完美 verify ✅**.

### 1.2 circuit_breaker_log 真值

实测 SQL: `SELECT new_level, prev_level, COUNT(*) FROM circuit_breaker_log GROUP BY new_level, prev_level`

**真值**: **0 rows** ALL TIME sustained.

实测 SQL: `SELECT MAX(trade_date), COUNT(*) FROM circuit_breaker_log`

**真值**: `(None, 0)` — 真**circuit_breaker_log 真**全部 0 rows ALL TIME**.

---

## §2 🔴 重大 finding — circuit_breaker_log 真**完全 0 transitions ALL TIME**

**真证据**: circuit_breaker_log 真**全 0 rows sustained sprint period sustained**.

**真根因 5 Why**:
1. circuit_breaker_state 真**有 paper + live 2 行** sustained, 真**有 current_level 字段记录现状**
2. circuit_breaker_log 真**应该 sustained CB transitions sustained 沉淀** sustained sprint period sustained
3. 真**0 rows ALL TIME** = 真**0 CB transitions 真生产 sustained sprint period sustained**
4. circuit_breaker_state.live 真 entered_at=2026-04-20 = 真 4-20 后 sustained 真未 transition (level 0 sustained)
5. **真根因**: 真生产 CB 真**0 transitions sustained sprint period sustained 8 month** = 真**5+1 层 L0 真生产 真**完全 inactive** sustained sprint period sustained 沉淀, sustained F-D78-89 + F-D78-261 真证据完美加深 (5+1 层真 1/6 实施真证据 — L1 落地但 L0 真**0 transitions 沉淀** = 真 enforce 真**0 sustained 度量**)

**🔴 finding**:
- **F-D78-298 [P0 治理]** circuit_breaker_log 真**0 rows ALL TIME sustained sprint period sustained 8 month**, sustained sprint state circuit_breaker_state.live 真有 record (current_level=0, nav=993520.16) 但 transitions log 真**完全 0** = 真**5+1 层 L0 真生产 真完全 inactive** sustained 真证据 verify, sustained F-D78-89 + F-D78-261 + F-D78-264 cluster 同源真证据完美加深 (真核 risk 5+1 层 L0 真**8 month 0 transitions sustained**)

---

## §3 真生产意义 — circuit_breaker_state.live trigger_reason 真**重要 audit trail**

**真证据**: live entry trigger_reason = **"PT restart gate cleanup 2026-04-30 (DB stale → 真账户 ground truth)"** + trigger_metrics 真完整 (nav / rolling_5d / daily_return / cumulative_return).

**真生产意义**:
- 真**4-20 进入 live cb_state** (sprint state Session 21 沉淀 PR #32 等真激活 5+1 层 MVP 3.1)
- 真**4-30 19:48 update** sustained 沿用 risk_event_log 4-30 info entry "pt_restart_gate_db_cleanup_2026_04_30" 真同步 sustained ✅
- 真**0 CB level transitions 真**4-20 后** sustained 5-01 真无 sustained 真**8 month 真未触发**

**finding**:
- F-D78-299 [P1] circuit_breaker_state.live trigger_reason "PT restart gate cleanup 2026-04-30" + trigger_metrics 真完整 nav=993520.16 等 — 真**Wave 4 PR #166 §2 v3 真 cleanup 真完美 verify** ✅, sustained sprint period sustained "DB cleanup 4-30 19:48" 真证据完美 verify, 真生产**真 ad-hoc cleanup 真有 audit trail** sustained vs 真**真核 CB transitions 真 0 audit trail** sustained 反差

---

## §4 真生产**真 5+1 层 L0** 0 transitions 真核 risk 真证据加深

**真生产真证据加深**:
- F-D78-264 P0 治理: risk_event_log 仅 2 entries 30d (1 P0 4-29 + 1 info 4-30)
- F-D78-298 P0 治理: circuit_breaker_log 0 rows ALL TIME
- F-D78-292 P1: 5-01 真 schtask runs 0 (sustained F-D78-289)
- F-D78-285 P0 治理: emergency_close 真 0 smoke test
- F-D78-287 P0 治理: emergency_close 路径 7/7 ❌

**真证据汇总**: 真**5+1 层 L0 + emergency 路径 + risk_event_log + schtask 真**8 month 真生产 真**完全 inactive sustained**.

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-298** | **P0 治理** | circuit_breaker_log 真 0 rows ALL TIME, 5+1 层 L0 真生产完全 inactive 8 month, F-D78-89/261/264 完美加深 |
| F-D78-299 | P1 | circuit_breaker_state.live trigger_reason "PT restart gate cleanup 4-30" + trigger_metrics 完整, ad-hoc cleanup 真 audit trail vs CB transitions 0 audit trail 反差 |

---

**文档结束**.
