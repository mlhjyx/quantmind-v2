---
adr_id: ADR-032
title: S4 caller bootstrap factory + naked LiteLLMRouter export 限制
status: accepted
related_ironlaws: [22, 25, 27, 33, 34]
recorded_at: 2026-05-03
---

## Context

V3 Tier A Sprint 1 真**S4 sub-task** 真主题 = caller bootstrap enforcement entry point.

S4 老主题 = Budget guardrails (LLM 月预算 + WARN/CAPPED 状态机). 5-02 sprint period 真**LL-111 候选 cite drift** 沉淀: S4 老主题真**已并入 S2.2 PR #223** (BudgetGuard + BudgetAwareRouter + llm_cost_daily 表). S4 编号转给**新主题** sustained user 决议:

- **意图**: 提供唯一 enforcement 入口, 应用代码只能拿 BudgetAwareRouter, 拿不到 naked LiteLLMRouter
- **反 anti-pattern**: naked LiteLLMRouter bypass audit + budget governance
- **沿用**: ADR-022 反 silent overwrite + ADR-031 §6 渐进 deprecate plan (S4 真**前置 enforcement**)

V3 Sprint 1 真 cumulative sediment (PR #219-#225, 7/8 完成):
- LiteLLM SDK + provider config (S1 PR #221)
- LiteLLMRouter core + 7 task enum (S2.1 PR #222)
- BudgetGuard + llm_cost_daily 表 (S2.2 PR #223)
- LLMCallLogger + audit trail (S2.3 PR #224)
- Ollama install runbook + e2e (S3 PR #225)

S4 真**最后 sub-task** (8/8) — 把 PR #221-#225 所有 sediment 沉到**唯一 sanctioned API**.

## Decision

**factory + _internal/ + hook 三组合**:

1. **factory function** (`backend/qm_platform/llm/bootstrap.py`):
   - `get_llm_router(*, settings=None, conn_factory=None) -> BudgetAwareRouter | LiteLLMRouter`
   - 沿用 `backend/qm_platform/observability/alert.py:528-554` 真 double-checked lock + `reset_llm_router()` 体例
   - process-level singleton (反 race + 反 重复 LiteLLM Router init cost)
   - **降级 mode**: `conn_factory=None` 走 naked LiteLLMRouter (反 BudgetGuard 真 None DB call), Sprint 2+ application bootstrap 时显式 wire conn_factory 启用全 governance

2. **_internal/ 子包** (`backend/qm_platform/llm/_internal/`):
   - 移 router.py / budget.py / audit.py 进 _internal/
   - public `__init__.py` 真**18 → 6 export** 重构: 仅 `get_llm_router / reset_llm_router` (factory) + `RiskTaskType / LLMMessage / LLMResponse / RouterConfigError / UnknownTaskError` (公共 enum + dataclass + exception 沿用 PR #222 sediment, 留 types.py)
   - 内部互引走 `from ..types import ...` + `from .router import ...` 体例

3. **hook 检测** (`scripts/check_llm_imports.sh`):
   - 加 S4_INTERNAL_PATTERN: `^[[:space:]]*from[[:space:]]+backend\.qm_platform\.llm\._internal`
   - scope: backend/app/ + backend/engines/ + scripts/ (caller code, 排除 backend/qm_platform/llm/ 自身 + backend/tests/* + scripts/check_llm_imports.sh)
   - allowlist marker: `# llm-internal-allow:` (test 真**file-level marker** 走 `# llm-internal-allow:test-only`)
   - 沿用 PR #219 现 anthropic / openai 真 PATTERN + ALLOWLIST_MARKER 体例 (反 invent 新机制)

## Alternatives Considered

| 候选 | 描述 | 拒收理由 |
|---|---|---|
| (1) 直接删 LiteLLMRouter export | __init__.py 删, 反**break 4 test 文件** | break PR #221-#225 test sediment, 撞 ADR-022 silent overwrite |
| (3) DeprecationWarning import 时 emit | warning + 完成 import (反 hard block) | warning 真生产可能漂移, audit Week 2 sediment hard block 候选 P3 backlog |
| (4) ruff/lint hook only (无 _internal/ 移) | 仅 hook BLOCK naked import, 反 path-level enforcement | hook 真**最后防线**, 反 path-level structure 真**反 silent bypass** 防御弱 |
| (2)+(4) 组合 (本 ADR 真采纳) | _internal/ 移 + hook 检测 | path-level structure (反 silent bypass) + hook (反 caller code drift) 双层防御 |

## Consequences

### Positive

- **唯一 sanctioned 入口**: caller 真**get_llm_router()** factory, 反 naked LiteLLMRouter bypass governance
- **process-level singleton 复用**: 反**重复 LiteLLM Router init cost** + 反 race condition (沿用 alert.py 体例)
- **降级 mode 兼容**: conn_factory=None 走 naked LiteLLMRouter, Sprint 2+ application bootstrap 时显式 wire conn_factory 启用全 governance
- **test isolation**: `reset_llm_router()` autouse fixture (反 cross-test pollution, 沿用 alert.py 体例)
- **ADR-031 §6 align**: S4 真**前置 enforcement**, factor_agent / idea_agent 切换 LiteLLMRouter (Sprint 2-N) 真 align ADR-031 §4.1 5 hard 触发条件

### Negative / Cost

- **4 test 文件 ~12-15 line mechanical 改 import path**: move-only, 0 logic 改, 反 break test mock 体例 (沿用 monkeypatch.setattr 体例)
- **public API surface 缩小**: 18 → 6 names. 4 test 真 deep cite (FallbackDetectionError / _is_fallback / BudgetGuard 等) 真**改走 _internal/ 直 import** + 加 `# llm-internal-allow:test-only` marker
- **hook 加复杂度**: 加 S4 第 2 轮 scan loop (caller scope 真 backend/app/ + backend/engines/ + scripts/, 反 llm/ + tests/ + check_llm_imports.sh)

### Neutral

- 0 prod caller break (沿用 S8 audit §3 0 hot path + S4 plan-mode cross-verify)
- factor_agent / idea_agent 沿用 deepseek_client (ADR-031 §6 渐进 deprecate plan, S4 真不触碰)
- V3 §11.1 path-level abstraction 沿用 (S4 真 implementation detail, 反 V3 doc patch)

## References

- ADR-022 (Sprint Period Treadmill 反 anti-pattern + 集中修订机制) — 反 silent overwrite 体例
- ADR-031 (S2 LiteLLMRouter implementation path 决议) — §6 渐进 deprecate plan, S4 真前置 enforcement
- V3 §5.5 (LiteLLM 路由真预约) — S4 真 caller bootstrap entry point
- V3 §11.1 (LiteLLM 模块清单) — backend/qm_platform/llm/ path-level abstraction (S4 真 implementation detail, 0 V3 patch)
- docs/LLM_IMPORT_POLICY.md §10.9 (S4 caller bootstrap factory + naked router export restriction)
- backend/qm_platform/observability/alert.py:528-554 (factory 体例参考: get_alert_router + reset_alert_router double-checked lock)
- backend/qm_platform/observability/metric.py (factory 体例参考)
- docs/audit/sprint_1/s8_deepseek_audit.md §3 (0 hot path 证据链)
- LL-111 候选 (S4 cite drift, 老 Budget 主题已并 S2.2 PR #223) — audit Week 2 sediment 候选
- scripts/check_llm_imports.sh (S6 PR #219 hook 沿用 + S4 PR #226 加 _internal pattern)
