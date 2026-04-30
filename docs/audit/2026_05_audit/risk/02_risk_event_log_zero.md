# Risk Review — risk_event_log 真触发统计 (4-29 路径哲学局限再印证)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / risk/02
**Date**: 2026-05-01
**Type**: 评判性 + risk event 真测 + 4-29 真根因再印证

---

## §1 risk_event_log 真测 (CC 5-01 实测)

### 1.1 总数 + 时间分布

实测 SQL:
```sql
SELECT COUNT(*), MIN(triggered_at), MAX(triggered_at) FROM risk_event_log;
```

**真值**:
- **total = 2 行 only**
- MIN(triggered_at) = 2026-04-29 14:00 (4-29 PT 暂停事件当日)
- MAX(triggered_at) = 2026-04-30 19:48 (4-30 PT restart gate cleanup audit)

### 1.2 真 entries 详查

| triggered_at | severity | rule_id | 性质 |
|---|---|---|---|
| 2026-04-29 14:00 | info | `ll081_silent_drift_2026_04_29` | 🟡 silent drift audit log (LL-081 sustained, 非真生产风控触发) |
| 2026-04-30 19:48 | p0 | `pt_restart_gate_db_cleanup_2026_04_30` | 🟡 PT restart gate cleanup audit log |

**🔴 重大 finding**:
- **F-D78-61 [P0 治理]** **risk_event_log 仅 2 entries, 全 audit log 类 (silent_drift / cleanup), 0 真生产风控触发**
- 4-29 -29% 跌停事件 (688121.SH) 0 真触发 risk_event 记录 (沿用 sprint state Session 44 沉淀 "30 天 risk_event_log 0 行" 部分推翻 — 真值 30 天 2 行, 但 2 行均 audit log 非真风控触发)
- **再印证 F-D78-21 真根因**: Wave 1-4 路线图设计哲学局限 = batch + monitor, L0 event-driven enforce 是路线图外维度. **risk_event_log 沦为 audit log 写入位**, 非真风控触发记录

---

## §2 alert tables 真测

实测 schema:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND (table_name LIKE 'alert%' OR table_name LIKE 'risk%' OR table_name LIKE 'event%');
```

实测真表:
- `alert_dedup` (sprint period sustained MVP 4.1 batch 1 PostgresAlertRouter 沉淀)
- `event_outbox` (sprint period sustained MVP 3.4 outbox-publisher-tick 沉淀)
- `risk_event_log` (上述)

**🔴 finding**:
- **F-D78-62 [P0 治理] event_outbox = 0/0** (total / published) — sprint period sustained "Outbox Publisher MVP 3.4 batch 2 ✅" + Beat 30s 高频 outbox-publisher-tick sustained 沉淀, **真测 0 entries** = 真生产 0 真使用 / 0 真触发. event sourcing 架构 candidate 仅 design 0 enforce
- **F-D78-63 [P1] alert_dedup 真值未深查** (本审查未跑 SELECT COUNT FROM alert_dedup), Wave 4 MVP 4.1 alert 真触发统计 (D13 CC 扩) 候选 0 真测

---

## §3 4-29 真根因再印证 (沿用 risk/01 5 Why)

**risk_event_log 真测 vs 5 Why 真根因**:

| Why | risk/01 沉淀 | risk/02 真测验证 |
|---|---|---|
| Why 1 (-29% 0 风控告警) | batch 5min Beat vs event-driven | ✅ 印证 — 真 risk_event_log 0 真生产触发 |
| Why 2 (batch vs event-driven) | L0 实施未到位 | ✅ 印证 — risk_event_log 沦为 audit log 写入位 |
| Why 3 (L0 未实施) | 项目优先级 | (无新数据) |
| Why 4 (优先级 batch+monitor) | 路线图设计 | ✅ 印证 — 真测验证 batch+monitor 路线图 |
| Why 5 (路线图哲学局限) | event-driven 哲学外 | ✅ **重大 实测验证** — 路线图哲学局限 sustained, event-driven enforce 真 0 实施 |

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-61** | **P0 治理** | risk_event_log 仅 2 entries, 全 audit log 类 (silent_drift / cleanup), 0 真生产风控触发. 沿用 F-D78-21 真根因 路线图哲学局限再印证. risk_event_log 沦为 audit log 写入位 |
| **F-D78-62** | **P0 治理** | event_outbox = 0/0 真测, sprint period sustained "Outbox Publisher MVP 3.4 batch 2 ✅" + Beat 30s 沉淀, 真生产 0 真使用. event sourcing 架构 candidate 仅 design 0 enforce |
| F-D78-63 | P1 | alert_dedup + Wave 4 MVP 4.1 alert 真触发统计 (D13 CC 扩) 候选 0 真测 |

---

**文档结束**.
