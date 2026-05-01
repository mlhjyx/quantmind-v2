# Cross-Validation — 3 源 fact drift 真测 (sustained cross_validation/01)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 5 / cross_validation/02
**Date**: 2026-05-01
**Type**: 跨领域 + 3 源 fact drift 真测 (sustained F-D78-43 候选 P2 sustained)

---

## §1 3 源真测 (CLAUDE.md vs sprint state vs 真 DB/code)

### 1.1 fact 1: 因子数

| 源 | 数 |
|---|---|
| CLAUDE.md sustained | "70 LGBM 特征集 / 48 核心 / 32 PASS" |
| sprint state Session 22 | "282 factor IC backfill" / "113 factors with valid ma20" |
| 真 DB factor_values | **276 distinct factor_name** (factors/01 §1.1) |
| 真 DB factor_ic_history | **113 distinct factor_name** (factors/01 §1.1) |

**真测 align**: 真 DB 276/113 vs sprint state 282/113 (偏差 6 candidate Phase 3B/3D/3E 后续 0 sync update sustained)

**finding**: F-D78-60 (复) [P2] CLAUDE.md "BH-FDR M=213" 数字漂移 sustained sustained

### 1.2 fact 2: 测试基线

| 源 | 数 |
|---|---|
| CLAUDE.md sustained | "2864 pass / 24 fail (Session 9)" |
| sprint state Session 46 末 | "新增 fail 禁合入 baseline 24" |
| 真 pytest collect | **4076 tests** (testing/01 §1) |

**真测 drift**: +1212 tests since baseline (F-D78-76 P0 治理 sustained)

### 1.3 fact 3: PT 真账户

| 源 | NAV | positions |
|---|---|---|
| sprint state Session 46 末 | cash ¥993,520.16 (4-30 14:54) | 0 |
| 真 cb_state.live | nav ¥993,520.16 (4-30 19:48) | (无字段) |
| 真 xtquant 5-01 04:16 | cash ¥993,520.66 | 0 |
| 真 position_snapshot.live max | (无 nav 字段) | 19 持仓 / 4-day stale |

**真测 align**: 3 源 NAV align (差 ¥0.50 微小, F-D78-12) ✅ + position_snapshot.live drift (F-D78-4 P2 sustained)

### 1.4 fact 4: schedule 数

| 源 | 数 |
|---|---|
| sprint state Session 30 | "5 schedule entries 生产激活" |
| 真 Beat schedule | **active=4 + 2 PAUSED** (snapshot/03 §2) |
| 真 schtask | **13 active + 5 Disabled** (snapshot/03 §3) |

**真测 drift**: F-D78-7 P2 sprint state "5 entries" 漂移 sustained

### 1.5 fact 5: factor_values 字段名

| 源 | 字段 |
|---|---|
| CLAUDE.md sustained | factor_id (sustained §因子存储) |
| 真 DB schema | **factor_name** (factors/01 §1.1) |

**真测 drift**: F-D78-57 P2 sustained sustained

### 1.6 fact 6: cb_state 表名

| 源 | 表名 + 字段 |
|---|---|
| sprint state Session 46 末 | cb_state.live: level=0, nav=993520.16 |
| 真 DB schema | **circuit_breaker_state** + execution_mode (snapshot/02 §1.5) |

**真测 drift**: F-D78-2 P3 sustained sustained

### 1.7 fact 7: DB disk size

| 源 | size |
|---|---|
| CLAUDE.md sustained | "60+ GB" / "172 GB" / "159 GB" 多次漂移 |
| sprint state | (sustained 沉淀 sustained) |
| 真 du -sh D:/pgdata16 | **225 GB** |

**真测 drift**: F-D78-81 P2 sustained sustained

### 1.8 fact 8: API endpoints

| 源 | 数 |
|---|---|
| sprint state Session 2026-04-02 | "17 端点" |
| 真 grep FastAPI router | **128 routes / 0 ws** (snapshot/05) |

**真测 drift**: F-D78-122/123 P2 sustained sustained

### 1.9 fact 9: ADR count

| 源 | 数 |
|---|---|
| sprint state Session 46 末 | "ADR-001 ~ ADR-022" |
| 真 ls docs/adr/ | **18 文件 (含 README, 净 17 ADR)** + ADR-015~020 6 编号 gap (snapshot/12b) |

**真测 drift**: F-D78-153 P2 sustained sustained sustained

### 1.10 fact 10: LL count

| 源 | 数 |
|---|---|
| sprint state Session 46 末 | "LL-001 ~ LL-098" |
| 真 grep | **92 entries** (governance/05) |

**真测 drift**: F-D78-148 P3 sustained sustained sustained

### 1.11 fact 11: 5 schtask 真状态

| 源 | 真值 |
|---|---|
| sprint state | "Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅" |
| 真 schtasks /query | **5 schtask 持续 LastResult=1/2 失败** (snapshot/03 §4) |

**真测 drift**: F-D78-8 P0 治理 sustained sustained sustained

### 1.12 fact 12: risk_event_log 30 day

| 源 | 数 |
|---|---|
| sprint state Session 44 | "30 天 risk_event_log 0 行" |
| 真 SELECT count | **2 行 全 audit log 类** (risk/02 §1) |

**真测 drift**: F-D78-61 P0 治理 sustained sustained sustained

### 1.13 fact 13: alert_dedup

| 源 | 真值 |
|---|---|
| sprint period sustained | (alert routing 沉淀 但 真触发 0 sustained) |
| 真 SELECT | **3 entries / 38 fires/2 day** (operations/03 §1) |

**真测 drift**: F-D78-116 P0 治理 sustained sustained sustained

### 1.14 fact 14: event_outbox

| 源 | 真值 |
|---|---|
| sprint period | "Outbox Publisher MVP 3.4 batch 2 ✅" + Beat 30s 沉淀 |
| 真 SELECT | **0 entries** (risk/02 §2) |

**真测 drift**: F-D78-62 P0 治理 sustained sustained sustained

### 1.15 fact 15: T0-19 closed status

| 源 | 真值 |
|---|---|
| sprint state Session 45 | "T0-19 已 closed (PR #168+#170)" |
| 真 DB position_snapshot.live | **19 行 4-day stale 仍 active** (snapshot/07 §3) |

**真测 drift**: F-D78-4 P2 sustained sustained sustained

---

## §2 3 源 N×N 漂移矩阵 真测累计

实测 sprint period sustained sustained:
- broader 47 (sprint period sustained sustained)
- + 本审查 22+ (Phase 1+2 sustained, F-D78-46)
- + 本审查 Phase 3+4 扩 ~15 真测 fact (上述 §1.1-1.15)
- = **broader 累计 84+** (sprint period 47 + 本审查 37+)

**🔴 finding**:
- **F-D78-171 [P2]** 3 源 N×N fact drift 真测累计 broader 84+ (sprint period 47 + 本审查 37+), F-D78-46 sustained 扩, ADR-022 反 "数字漂移高发" enforcement 失败实证扩深

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-171 | P2 | 3 源 N×N fact drift 真测累计 broader 84+ (sprint period 47 + 本审查 37+), F-D78-46 sustained 扩 |
| (sustained 多 finding 复述) | (sustained) | F-D78-1/2/4/5/7/8/57/60/61/62/63/76/81/115/116/118/122/123/146/147/148/153 sustained sustained |

---

**文档结束**.
