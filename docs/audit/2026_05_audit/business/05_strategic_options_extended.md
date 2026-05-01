# Business Review — 战略候选 扩 (sustained architecture/03)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 7 WI 4 / business/05
**Date**: 2026-05-01
**Type**: 评判性 + 战略候选扩 (sustained architecture/03 + Phase 7 新发现)

---

## §0 元说明

(沿用 D78 + framework §6.3 + LL-098 — **仅候选, 0 决议**)

本 sub-md 在 architecture/03 21 类战略候选基础上, **扩 Phase 7 新发现** (frontend / D 决议链 / Event Sourcing / PMS deprecate / 等).

---

## §1 Phase 7 新战略候选 (扩 architecture/03)

### 1.1 Frontend 维度扩 (新)

候选维度 (沿用 frontend/01+02 sustained):
- ✅ **维持**: Frontend 12 api + 4 store + 17+ pages + 4 components subdirs (sustained sprint period sustained ✅)
- ⚠️ **修复**: Frontend 真 npm audit + ESLint + ?.null-safe enforce + 12 API contract vs backend 128 routes (F-D78-199~205 + F-D78-215)
- ⚠️ **修复**: Frontend realtime.ts + socket.io vs Backend WebSocket 真 0 endpoint disconnect (F-D78-217 P1)
- ⚠️ **简化**: Forex Dashboard sprint period DEFERRED 但真存 (F-D78-216)

### 1.2 D 决议链 SSOT 候选 (新)

- ⚠️ **修复**: CLAUDE.md add D 决议链 banner reference (F-D78-221 P1)
- ⚠️ **修复**: D_DECISION_REGISTRY.md sustained 沉淀 (跨 7+ 源 0 SSOT, F-D78-222)

### 1.3 Event Sourcing 候选 (新)

- ⚠️ **修复 / 推翻重做**: ADR-003 Event Sourcing design vs 真生产 0 真使用 (F-D78-218)
  - candidate root cause: 4-29 PT 暂停 sustained 后 event source 0 produce / Beat publisher 真 connect 0 sustained / etc

### 1.4 PMS v1 deprecate 候选 (新)

- ⚠️ **简化 / 修复**: PMS v1 真 deprecate 状态 verify (真删 vs 仅 stop calling, F-D78-220)
- ⚠️ **修复**: ADR 编号漂移 修 (F-D78-219 sprint state "ADR-016" vs 真 "ADR-010")

### 1.5 因子池 候选 (新)

- ⚠️ **修复**: factor_values 276 distinct vs CLAUDE.md ~143 累计 +133 candidate sync update (F-D78-223)
- ⚠️ **修复**: 真 IC 入库率 ~41% (113/276) candidate 加 IC enforce (F-D78-224)

---

## §2 战略候选 总扩

实测 architecture/03 21 类 + Phase 7 扩 ~10 类:

| 候选 | 数 (Phase 1-7 累计) |
|---|---|
| 维持 | 4 类 (含 Frontend 维持) |
| 修复 | 14 类 (含 Frontend / D 链 / Event Sourcing / PMS / 因子池) |
| 推翻重做 | 6 类 (含 Event Sourcing 推翻重做候选) |
| 简化 | 7 类 (含 Forex DEFERRED + PMS 简化) |

**总**: ~31 类战略候选 (sprint period sustained 0 决议).

---

## §3 finding 汇总

(本 sub-md 论据沉淀, 0 新 finding 编号. 沿用 sprint period sustained 多 P0 治理 + P1 finding sustained sustained sustained sustained sustained sustained sustained sustained sustained sustained.)

---

**文档结束**.
