# docs/research-kb/risk_findings/ — V3 §8.3 RiskReflector 候选沉淀 dir

> **用途**: V3 §8.3 line 965-972 — RiskReflector 反思产出的参数候选 / 候选规则,
> 经 user DingTalk webhook reply approve/reject 后沉淀于此。
> **写入方**: `backend/app/services/risk/reflection_candidate_service.py` (TB-4d sediment)。
> **关联**: V3 §8.3 (闭环) / ADR-069 (TB-4 closure) / Plan v0.2 §A TB-4 row。

## 闭环 (V3 §8.3 line 965-972)

```
RiskReflector 5 维反思 → ReflectionDimensionOutput.candidates
  ↓
TB-4b DingTalk push 摘要 (含 candidate_id: `<period_label>#<index>`)
  ↓
user DingTalk webhook reply: `approve <candidate_id>` / `reject <candidate_id>`
  ↓
TB-4d ReflectionCandidateService → 沉淀于本 dir:
  - <date>_<period>_idx<N>_approved.md  (status: approved)
  - <date>_<period>_idx<N>_rejected.md  (status: rejected, 长尾留存 line 968)
  ↓
[approved only] scripts/generate_risk_candidate_pr.py (显式触发)
  → git branch + commit + push (NEVER merge)
  ↓
user 显式 review + merge PR (反 silent .env mutation, ADR-022 sustained)
```

## 安全边界 (PR #345 plan option B)

| 组件 | git 操作 | .env 操作 | 触发方式 |
|---|---|---|---|
| DingTalk webhook handler | ❌ 0 | ❌ 0 | webhook 热路径 (自动) |
| ReflectionCandidateService | ❌ 0 | ❌ 0 | webhook handler 调用 |
| generate_risk_candidate_pr.py | branch+commit+push (**NEVER merge**) | ❌ 0 (含 red-line self-check) | **显式 human/CC 触发** |
| user | merge PR | 经 PR review 后才改 | 显式 |

候选**永不自动改 .env / production config** — 候选是 PR diff 供 user review。

## 记录格式

每条候选记录 markdown frontmatter:
```yaml
candidate_id: 2026_W19#1
status: approved | rejected
period_label: 2026_W19
candidate_index: 1
source_report: docs/risk_reflections/2026_W19.md
decided_at: 2026-05-14T...
pr_generated: false   # scripts/generate_risk_candidate_pr.py 处理后 → true
```

## 候选规则新增 (V3 §8.3 line 970-972)

反思发现的**新规则候选** (e.g. "T+0 衍生品异动 → 现货 alert") 也 enumerate 进本 dir,
不立即实施,走正常 PR 流程 (与日常因子研究同流程)。
