# 现状快照 — 数据流 + 测试 + 文档 (类 8+9+10)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 3 / snapshot/08+09+10
**Type**: 描述性 + 实测证据

---

## §1 类 8 — 数据流真清单

实测 sprint period sustained sustained:
- 真路径: Tushare/AKShare/QMT/Baostock → DataPipeline → DB → Parquet cache → 各消费者
- Redis Streams: `qm:{domain}:{event_type}` (maxlen=10000 sustained)
- StreamBus 模块 sustained sustained

**真测 (本审查 partial)**:
- event_outbox 真值 = 0/0 entries (risk/02 §2 F-D78-62 P0 治理)
- alert_dedup 真值未深查 (F-D78-63)
- factor_values 真值 276 distinct (factors/01 §1.1 F-D78-58 163 因子 raw 但 0 IC)

candidate finding:
- F-D78-110 [P2] Redis Streams 真 alive 数 0 sustained 监控 (沿用 sprint period sustained F-D3B-6 假 alive 教训), 真生产 stream 真触发统计 candidate

---

## §2 类 9 — 测试真清单

(详 [`testing/01_coverage_baseline_drift.md`](../testing/01_coverage_baseline_drift.md))

**真值复述** (sustained):
- pytest collect = **4076 tests** (CC 5-01 实测)
- sprint period sustained baseline = 2864 pass / 24 fail (sustained Session 9 末) — 数字漂移 +1212 (F-D78-76 P0 治理)
- pytest config drift: 3 unknown mark (slow / integration ×2) (F-D78-77 P3)

---

## §3 类 10 — 文档真清单

实测 sprint period sustained sustained:
- docs/ *.md = 270 (snapshot/01 §1)
- 全 repo *.md = 700 (snapshot/01 §1)
- 根目录 *.md = 8 (含 3 未授权, F-D78-5 P2)

**跨文档漂移** (sustained):
- broader 70+ (sprint period sustained 47 + 本审查 22+, F-D78-46 P2)
- 详 [`cross_validation/01_doc_drift_broader.md`](../cross_validation/01_doc_drift_broader.md)

候选 finding:
- F-D78-111 [P2] docs/* 700 *.md 真 last-update + 引用 graph + stale candidate (>30 day 0 update 但 sprint period 关键) 0 sustained 深查 in 本审查

---

## §4 类 12 — ADR + LL + Tier 0 (复述 sustained)

实测 sprint period sustained sustained:
- ADR-001 ~ ADR-022 sustained sustained (PR #181 + 之前)
- LL-001 ~ LL-098 sustained sustained
- TIER0_REGISTRY 18 unique IDs (T0-1 ~ T0-19 含 T0-13 gap), 9 closed + 9 待修 (sprint state Session 46 末) — sustained F-D78-4 (T0-19 stale 仍 active) sustained sustained

候选 finding:
- F-D78-112 [P2] TIER0_REGISTRY 真 closed/待修分布 实测 verify 候选 (sprint period sustained sustained 18 IDs sustained 但 sustained T0-19 类 closed 含义模糊 — 代码 vs 运维 closed 区分, 沿用 blind_spots/01 §1.4)

---

## §5 类 13 — 协作历史 (sustained sustained)

(详 [`governance/02_knowledge_management.md`](../governance/02_knowledge_management.md) 4 源 N×N 漂移)

---

## §6 类 14 — LLM cost + 资源

(详 [`snapshot/14_llm_resource_real.md`](14_llm_resource_real.md))

---

## §7 类 15-22 — CC 扩 8 类 (合并)

实测 sprint period sustained:

| 类 | 真测 | finding |
|---|---|---|
| 15 真账户对账历史 | sustained operations/01 (跨源 reconciliation SOP 0 sustained, F-D78-50 P1) | F-D78-50 |
| 16 历史 alert 真触发统计 | sustained risk/02 §2 (alert_dedup 真值未深查, F-D78-63 P1) | F-D78-63 |
| 17 历史 PT 重启次数 + 失败原因 | (sprint state sustained 沉淀 但本审查未深查 真 历史) | F-D78-113 |
| 18 历史 GPU 真利用率 | sustained snapshot/14 §3 (GPU 真利用率 0 sustained 监控, F-D78-83 P2) | F-D78-83 |
| 19 历史 OOM 事件 + 修复 | sustained performance/01 §1.2 (2026-04-03 PG OOM, 复发 detection 0 sustained, F-D78-100/82 P2) | F-D78-82/100 |
| 20 历史误操作 | (sprint period sustained sustained 22 PR 含 revert? 本审查未深查 git revert 真历史) | F-D78-114 |
| 21 用户输入历史 | sustained (D72-D78 4 次反问 + Claude 4 次错读 印证 协作 protocol drift, sustained blind_spots/02 §1.4 F-D78-32 P1) | F-D78-32 |
| 22 跨 session memory drift | sustained (sprint state 4-28 vs 真值 4-27 sustained F-D78-1 P2 + governance/02 §3 F-D78-26 P0 治理 同源) | F-D78-1/26 |

**新 finding**:
- F-D78-113 [P3] 历史 PT 重启次数 + 失败原因 0 sustained 深查 (sprint state sustained 沉淀 但本审查未深查 真历史)
- F-D78-114 [P3] 历史误操作 (commit revert / 数据误删 / etc) 0 sustained git revert 历史深查 in 本审查

---

## §8 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-110 | P2 | Redis Streams 真 alive 数 0 sustained 监控, 真生产 stream 真触发统计 candidate |
| F-D78-111 | P2 | docs/* 700 *.md 真 last-update + 引用 graph + stale candidate 0 sustained 深查 |
| F-D78-112 | P2 | TIER0_REGISTRY 真 closed/待修分布 实测 verify candidate (closed 含义模糊) |
| F-D78-113 | P3 | 历史 PT 重启次数 + 失败原因 0 sustained 深查 |
| F-D78-114 | P3 | 历史误操作 (commit revert / 数据误删 / etc) 0 sustained git revert 历史深查 |

---

**文档结束**.
