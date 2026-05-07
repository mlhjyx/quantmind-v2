# 08 — ADR Partial Closure Monitoring SOP

> **Why**: ADR-DRAFT row 7 (audit failure path coverage S2.4) + row 2 (News fetch query strategy SSOT) sustained `→ ADR-XXX (committed, partial)` 真**partial closure** 体例 — 真**残余 sub-task 沉淀 sustained 反 forgotten** 漂移风险. ADR-039 真 retry policy ✅ + circuit breaker (sub-PR 8b-resilience 真预约) + DingTalk push (sub-PR 9 真预约) 真**残余** sustained 沿用 row 7 partial closure 体例.
> **触发**: 任 ADR partial promote → 真**REGISTRY.md cite + ADR-DRAFT row mark + 残余 sub-task tracking** 三同步.

## 真**partial closure 体例**

### 真**partial promote 标记 体例** (ADR-DRAFT row N)
```markdown
| 7 | Audit failure path coverage S2.4 sub-task ... | sediment cite ... | **→ ADR-039 (committed, partial)** | 沿用 sub-PR 8b-resilience + sub-PR 9 真预约 完整 closure |
```

### 真**残余 sub-task 沉淀 体例** (ADR file + REGISTRY)

**ADR-XXX file §Implementation 必含**:
```markdown
**留 sub-PR YYY (真预约 sub-task name)**:
- <task description>
- <sub-task scope cite>
```

**REGISTRY.md row 真**残余 cite**:
```markdown
| ADR-XXX | <title> (S2.4 sub-task partial closure) | committed | ... 真**残余 sub-task**: <list> sustained ... |
```

## 真**ADR partial closure cumulative drift 监控** (本 SOP scope)

### 真**5-07 cumulative state** (sample inventory)

| ADR | partial? | promote target | 残余 sub-task | reserved sub-PR |
|---|---|---|---|---|
| **ADR-039** | ✅ partial | ADR-DRAFT row 7 | circuit breaker / DingTalk push | sub-PR 8b-resilience + sub-PR 9 |
| **ADR-043** | ✅ partial | ADR-DRAFT row 2 | News Beat schedule entry register / RSSHub multi-route 503 fix | sub-PR 8b-cadence-B ✅ closed / audit chunk C-ADR 真预约 |
| ADR-XXX (future) | TBD | ADR-DRAFT row N | TBD | TBD |

### 真**月度 audit 体例** (sub-PR 9 真预约 implementation)
- python script `scripts/audit_adr_partial_closure.py`:
  - grep ADR file §Implementation `留 sub-PR XXX` cite
  - grep REGISTRY row `残余 sub-task` cite
  - grep ADR-DRAFT row mark `committed, partial`
  - 3 source cross-verify alignment
- DingTalk push 触发 partial closure 真**90 day 反**进展** alert (反 沉淀 forgotten)

## 真**反 anti-pattern** sediment

- ❌ ADR partial promote 反 cite 残余 sub-task → 沉淀 sub-task 沉默 forgotten
- ❌ "fully committed" 假设 ADR ✅ 全 closed 沿用 partial sustained — 真**reserved sub-PR cite** sustained 反 forgotten
- ❌ ADR # cite 反 align 残余 sub-PR cite — 真**3 source cross-verify** sustained 沿用 SOP-6 体例

## 真**ADR-039 真预约 cleanup path** (sub-PR 8b-resilience)

```markdown
**ADR-039 §Implementation update post-sub-PR 8b-resilience merge**:
- ✅ retry policy (sub-PR 8b-llm-audit-S2.4 PR #255)
- ✅ **circuit breaker (sub-PR 8b-resilience PR #YYY)** ← post-merge update
- 留 sub-PR 9 (DingTalk push 触发 LL_AUDIT_INSERT_FAILED, 真预约)
```

REGISTRY row update:
```markdown
| ADR-039 | LLM audit failure path resilience — retry policy + **circuit breaker** + transient/permanent classifier (S2.4 sub-task **2/3 closure**) | committed | ... sustained 真**残余 sub-task**: DingTalk push (sub-PR 9 真预约) sustained |
```

## 真生产真值 evidence (5-07)

- ADR-039 partial closure: sub-PR 8b-llm-audit-S2.4 PR #255 retry policy ✅ / 残余 2 sub-PR 真预约 sediment
- ADR-043 partial closure: sub-PR 8b-cadence-A ADR sediment-only PR #256 ✅ / 残余 sub-PR 8b-cadence-B Beat entry register PR #257 ✅ / 残余 RSSHub multi-route 503 fix audit chunk C-ADR 真预约
- chunk C-SOP-A 本 SOP 真**实证 monitoring chain** sustained

## 真关联

- ADR-022 反 silent overwrite + reserved row sediment governance
- ADR-037 governance pattern + SESSION_PROTOCOL.md 体例
- LL-105 SOP-6 4 source cross-verify
- 07_registry_status_count_sop.md (status count automation 真预约)
- chunk C-SOP-B 真预约 `scripts/audit_adr_partial_closure.py` + sub-PR 9 DingTalk push integration
