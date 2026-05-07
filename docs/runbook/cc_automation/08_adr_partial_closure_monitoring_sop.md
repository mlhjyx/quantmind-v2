# 08 — ADR Partial Closure Monitoring SOP

> **Why**: ADR-DRAFT row 7 (audit failure path coverage S2.4) + row 2 (News fetch query strategy SSOT) `→ ADR-XXX (committed, partial)` **partial closure** 体例 — **残余 sub-task 沉淀 反 forgotten** 漂移风险. ADR-039 retry policy ✅ + circuit breaker (sub-PR 8b-resilience 待办) + DingTalk push (sub-PR 9 待办) **残余** 沿用 row 7 partial closure 体例.
> **触发**: 任 ADR partial promote → **REGISTRY.md cite + ADR-DRAFT row mark + 残余 sub-task tracking** 三同步.

## **partial closure 体例**

### **partial promote 标记 体例** (ADR-DRAFT row N)
```markdown
| 7 | Audit failure path coverage S2.4 sub-task ... | sediment cite ... | **→ ADR-039 (committed, partial)** | 沿用 sub-PR 8b-resilience + sub-PR 9 待办 完整 closure |
```

### **残余 sub-task 沉淀 体例** (ADR file + REGISTRY)

**ADR-XXX file §Implementation 必含**:
```markdown
**留 sub-PR YYY (待办 sub-task name)**:
- <task description>
- <sub-task scope cite>
```

**REGISTRY.md row **残余 cite**:
```markdown
| ADR-XXX | <title> (S2.4 sub-task partial closure) | committed | ... **残余 sub-task**: <list> ... |
```

## **ADR partial closure cumulative drift 监控** (本 SOP scope)

### **5-07 cumulative state** (sample inventory)

| ADR | partial? | promote target | 残余 sub-task | reserved sub-PR |
|---|---|---|---|---|
| **ADR-039** | ✅ partial | ADR-DRAFT row 7 | circuit breaker / DingTalk push | sub-PR 8b-resilience + sub-PR 9 |
| **ADR-043** | ✅ partial | ADR-DRAFT row 2 | News Beat schedule entry register / RSSHub multi-route 503 fix | sub-PR 8b-cadence-B ✅ closed / audit chunk C-ADR 待办 |
| ADR-XXX (future) | TBD | ADR-DRAFT row N | TBD | TBD |

### **月度 audit 体例** (sub-PR 9 待办 implementation)
- python script `scripts/audit_adr_partial_closure.py`:
  - grep ADR file §Implementation `留 sub-PR XXX` cite
  - grep REGISTRY row `残余 sub-task` cite
  - grep ADR-DRAFT row mark `committed, partial`
  - 3 source cross-verify alignment
- DingTalk push 触发 partial closure **90 day 反**进展** alert (反 沉淀 forgotten)

## **反 anti-pattern** sediment

- ❌ ADR partial promote 反 cite 残余 sub-task → 沉淀 sub-task 沉默 forgotten
- ❌ "fully committed" 假设 ADR ✅ 全 closed 沿用 partial — **reserved sub-PR cite** 反 forgotten
- ❌ ADR # cite 反 align 残余 sub-PR cite — **3 source cross-verify** 沿用 SOP-6 体例

## **ADR-039 待办 cleanup path** (sub-PR 8b-resilience)

```markdown
**ADR-039 §Implementation update post-sub-PR 8b-resilience merge**:
- ✅ retry policy (sub-PR 8b-llm-audit-S2.4 PR #255)
- ✅ **circuit breaker (sub-PR 8b-resilience PR #YYY)** ← post-merge update
- 留 sub-PR 9 (DingTalk push 触发 LL_AUDIT_INSERT_FAILED, 待办)
```

REGISTRY row update:
```markdown
| ADR-039 | LLM audit failure path resilience — retry policy + **circuit breaker** + transient/permanent classifier (S2.4 sub-task **2/3 closure**) | committed | ... **残余 sub-task**: DingTalk push (sub-PR 9 待办) |
```

## 真生产真值 evidence (5-07)

- ADR-039 partial closure: sub-PR 8b-llm-audit-S2.4 PR #255 retry policy ✅ / 残余 2 sub-PR 待办 sediment
- ADR-043 partial closure: sub-PR 8b-cadence-A ADR sediment-only PR #256 ✅ / 残余 sub-PR 8b-cadence-B Beat entry register PR #257 ✅ / 残余 RSSHub multi-route 503 fix audit chunk C-ADR 待办
- chunk C-SOP-A 本 SOP **实证 monitoring chain**

## 关联

- ADR-022 反 silent overwrite + reserved row sediment governance
- ADR-037 governance pattern + SESSION_PROTOCOL.md 体例
- LL-105 SOP-6 4 source cross-verify
- 07_registry_status_count_sop.md (status count automation 待办)
- chunk C-SOP-B 待办 `scripts/audit_adr_partial_closure.py` + sub-PR 9 DingTalk push integration
