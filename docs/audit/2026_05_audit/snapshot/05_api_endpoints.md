# 现状快照 — API + WebSocket 真测 (类 5)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 3 WI 3 / snapshot/05
**Date**: 2026-05-01
**Type**: 描述性 + 实测真值

---

## §1 FastAPI router 真测 (CC 5-01 实测)

实测命令:
```bash
grep -rE "@(app|router)\.(get|post|put|delete|patch|websocket)" backend/app/api/ backend/app/main.py | wc -l
```

**真值**:
- **HTTP routes**: **128** decorators
- **WebSocket routes**: **0** (grep `@(app|router)\.websocket` 0 hit)

---

## §2 真测 vs sprint period sustained

| 沿用 sprint period sustained CLAUDE.md / SYSTEM_STATUS | 真测 |
|---|---|
| "17 端点" (sprint period 沉淀 sprint state Session 2026-04-02) | ⚠️ 真 128 routes, 沿用 sprint period 17 端点数 sustained 沉淀严重漂移 |
| "/api/* endpoint + /ws/* channel" (CLAUDE.md sustained) | ⚠️ /api/* 128 + /ws/* **0** (sprint period sustained sustained "WebSocket" 提及 但真 0 ws endpoint) |
| `/api/system/streams` (CLAUDE.md sustained 调试端点) | (真 128 routes 中 1 个) |

**🔴 finding**:
- **F-D78-122 [P2]** API endpoints 数字漂移 (sprint period sustained "17 端点" sustained sustained 沉淀, 真测 128 routes), sprint state 数字 sustained 多次 sustained 但真值远超 sprint period 沉淀
- **F-D78-123 [P2]** WebSocket routes = **0** (sprint period sustained CLAUDE.md / SYSTEM_STATUS "ws" 提及 sustained 但真 0 ws endpoint), candidate sprint period sustained "WebSocket" 沉淀 sustained 沉淀 sustained 文档 vs 真测 disconnect

---

## §3 调用方 grep + deprecated candidate

(本审查未深查 frontend grep + scripts grep 真调用方. 候选 finding):
- F-D78-124 [P2] 128 routes 真调用方 + deprecated candidate 0 sustained sustained 度量 (frontend src/api/ + scripts/ 真 grep 候选 sub-md 详查)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-122 | P2 | API endpoints 数字漂移 (sprint period "17 端点" vs 真 128 routes) |
| F-D78-123 | P2 | WebSocket routes 真 0, sprint period sustained sustained "ws" 沉淀 sustained 文档 vs 真测 disconnect |
| F-D78-124 | P2 | 128 routes 真调用方 + deprecated candidate 0 sustained 度量 |

---

**文档结束**.
