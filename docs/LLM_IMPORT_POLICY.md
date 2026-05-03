# LLM Import Policy (S6 Governance)

> **真意**: backend/ + scripts/ 禁直接 import anthropic / openai. 真 only path = LiteLLMRouter (V3 §5.5 cite, S2 sub-task 待 sediment).
> **沿用**: V3 §5.5 + ADR-020 真预约 + ADR-022 反 silent overwrite + LL-098 X10 stress test.
> **enforcement**: pre-commit hook (--staged) + pre-push hook (--full) 双层 BLOCK (sustained X10 hard pattern 体例).
> **关联文档**: [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §5.5 (LLM 路由) / [docs/adr/REGISTRY.md](adr/REGISTRY.md) (ADR # registry SSOT, ADR-020 reserve sustained) / [scripts/check_llm_imports.sh](../scripts/check_llm_imports.sh) (hook script SSOT).

## §1 真禁止 Pattern

| Pattern | 真触发 |
|---|---|
| `import anthropic` | BLOCK |
| `from anthropic import ...` | BLOCK |
| `from anthropic.X import ...` | BLOCK |
| `import openai` | BLOCK |
| `from openai import ...` | BLOCK |
| `from openai.X import ...` | BLOCK |

## §2 真 Scope

**真扫描**: `backend/**/*.py` + `scripts/**/*.py`

**真排除**:
- `**/tests/*` — mock cite 真合法 (e.g. `unittest.mock.patch("openai.ChatCompletion.create")`)
- `config/hooks/` — hook 自身, 0 LLM 调用风险
- `scripts/check_llm_imports.sh` — 本 hook script 自身

## §3 真触发时点

### Pre-commit (`config/hooks/pre-commit`)
- 模式: `--staged` (仅扫 staged Python files)
- 真意: 真早期拦截 (commit 前), cheap (仅当 commit 有 .py 改动)
- 真触发: `git commit` 时

### Pre-push (`config/hooks/pre-push`)
- 模式: `--full` (扫全 backend/ + scripts/)
- 真意: defense-in-depth (防 squash/amend/cherry-pick 漏检)
- 真触发: `git push` 时
- 顺序: X10 cutover-bias scan → S6 LLM import block → 铁律 10b smoke

## §4 真背景

### V3 §5.5 — LiteLLM 路由

V3 风控架构 §5.5 cite "LiteLLMRouter (新模块)" 真意 = LLM 调用真 unified path. 真目的:

1. **多 provider 统一**: DeepSeek V4-Flash + V4-Pro + Ollama fallback (真 0 vendor lock-in)
2. **Budget guardrails**: 80% warn / 100% Ollama fallback / 月度 review (V3 §20.1 #6)
3. **Cost monitoring**: daily 累计 + DingTalk push (V3 §16.2)
4. **Audit trail**: 沿用 LL-103 SOP-5 5 condition (audit row 真金 0 风险)

直接 import anthropic / openai 真 bypass 上述 4 项 governance.

### ADR-020 — Claude 边界 + LiteLLM 路由 + CI lint

ADR-020 (V3 §18.1 row 2 真预约, 0 file 等真起手时 sediment) 真意 = LiteLLM-only enforce. 本 hook 真**先决 implementation** (sustained ADR-020 真 file 创建前真已生效).

### ADR-022 — 反 silent overwrite

ADR-022 sustained sprint period treadmill 反 anti-pattern. 真意: 已 existing 模块 (e.g. `backend/engines/mining/deepseek_client.py` 真 1026 lines 真 GP 闭环 prototype, sustained Sprint 1.17) 真**0 mutation by stealth**, 沿用 user (a-iii) "# 下移决议体例" + S2 sub-task 真改造 LiteLLMRouter 真后 deepseek_client.py 真 deprecation path 由 user 显式决议.

## §5 真合法 Import (替代 path)

### 真生产 path

```python
# 真生产: LiteLLMRouter (S2 sub-task 待 sediment)
from backend.qm_platform.llm.router import LiteLLMRouter

router = LiteLLMRouter(...)
response = router.chat(messages=[...])  # 真 unified path, multi-provider routing
```

### 真 Test path

```python
# tests/ 内 mock cite 真合法 (本 hook 真排除 /tests/)
from unittest.mock import patch

@patch("openai.ChatCompletion.create")
def test_my_thing(mock_openai):
    ...
```

## §6 真紧急绕过 (违反 SOP)

```bash
git commit --no-verify   # 跳 pre-commit
git push --no-verify     # 跳 pre-push
```

**真要求**: commit message 显式声明绕过原因. 沿用 LL-098 X10 体例 (commit body 内 cite "X10-bypass: <真 specific reason>").

**真禁用 case**:
- 真生产 LLM 调用 path 真改造 (S2 LiteLLMRouter sediment) — 0 必要 bypass
- 真测试 import — 用 `tests/` 子目录 (本 hook 真排除)
- 真原型 spike — 用 LiteLLMRouter (sustained S2 真完成后)

## §7 历史

- 5-02 sprint period: V3 §5.5 sediment (PR #216) + ADR-020 预约 (V3 §18.1 row 2)
- 5-02 sprint period: 讽刺自身实证 #5 (Claude.ai 写 V3 Sprint 1 prompt 假设 7+ prerequisite 未 verify, 沿用 F2 verify-only 体例)
- 本 hook implementation = S6 sub-task (Sprint 1 起手)
- 5-02 sprint period: 讽刺自身实证 #6 (上轮 plan-mode `grep ^(import|from)` 漏 inline lazy import — deepseek_client.py:222, 沿用 LL-106 sediment 候选)

## §8 Known Legacy Violator (S2-deferred)

| 文件:行号 | 违反内容 | marker | 计划清除时间点 | 关联 PR |
|---|---|---|---|---|
| `backend/engines/mining/deepseek_client.py:222` | `from openai import OpenAI` (inline lazy import in `_get_openai_client` method) | `# llm-import-allow:S2-deferred-PR-219` | S2 LiteLLMRouter 完成 + deepseek_client.py refactor 后 | 本 hook PR #219 加 marker / S2 PR (TBD) 删 marker |

**为什么有这个 violator**:

`deepseek_client.py` 是 Sprint 1.17 sediment 的 GP 闭环 prototype (396 lines main + 2 callers factor_agent.py + idea_agent.py = 共 1026 lines LLM 模块). 含 DeepSeek native API + lazy import OpenAI SDK 作为 fallback path (访问 DeepSeek 兼容 API endpoint).

S2 sub-task (LiteLLMRouter 新建) 完成后, `deepseek_client.py` 的 OpenAI lazy import 路径会被 LiteLLMRouter 替代, 这一行会被删除 — 那时 marker 也一起删除.

**为什么不直接 refactor 现在**:

- user 决议 2 (p1) sustained: deepseek_client.py 0 logic mutation 直到 S2 sediment
- ADR-022 反 silent overwrite: 已 existing 模块的 deprecation path 必须 user 显式决议 (NOT silent removal)
- 1 line inline marker 不算 logic 改动, 沿用 user (a-vi) 决议 (S6 完整 enforce + 1 line marker)

**月度 audit 检查 (沿用 §9)**:

每月 1 日 audit 本表, 验证:
1. 表中每行的 violator 仍存在 (file + line)
2. marker 仍在该行 (没被意外删除)
3. 关联 PR 进度 (S2 是否已 sediment, marker 是否应清除)
4. 没有 backlog 漏掉的新 violator (新 import 应通过 hook BLOCK 阻挡, 但 audit 是 defense-in-depth)

## §9 Allowlist Marker 使用规范

### marker 格式

```python
# llm-import-allow:<reason-or-issue-ref>
```

- `<reason-or-issue-ref>` 必须是 PR # 或 issue # 或 sub-task ID, **不能是空 / "TODO" / "FIXME" 这类没具体 cite 的占位**
- 例: `# llm-import-allow:S2-deferred-PR-219` ✅
- 例: `# llm-import-allow:TODO` ❌ (没 cite, 月度 audit 无从检查)
- 例: `# llm-import-allow:` ❌ (空 reason, hook 会跳过 BLOCK 但月度 audit 会标 STALE)

### 适用场景

| 适用 | 不适用 |
|---|---|
| Legacy 模块 (S2 LiteLLMRouter sediment 前的 deepseek_client.py 类) | 新建模块直接绕过 (走 LiteLLMRouter) |
| 真生产已运行的代码 0 mutation 决议 (沿用 ADR-022) | "暂时方便" 跳 LiteLLM (没有 user 决议) |
| 跨 sub-task 的 deferred path (有具体清除时间点) | Routine bypass (没具体清除计划) |

### 添加 marker 的流程

1. 在 PR body / commit message 显式 cite 为什么需要 marker (legacy + 关联 sub-task)
2. 在 §8 Known Legacy Violator 表中加一行 (file:line + reason + 计划清除时间点 + 关联 PR)
3. PR review 时 reviewer 必须确认 marker 有合理 reason (不是 routine bypass)
4. 月度 audit 检查 marker 是否过期未清除

### 删除 marker 的时机

当 §8 表中某行的"计划清除时间点"达到时:

1. 验证关联 sub-task 已 sediment (e.g. S2 LiteLLMRouter 已完成)
2. Refactor 该 lazy import 路径走 LiteLLMRouter
3. 删除 marker (这一行整个被 refactor)
4. 更新 §8 表 (该行移到"已清除历史"区或直接删除)
5. 跑 hook --full 验证 0 ALLOWLIST_HIT log (确认彻底清除)

### 紧急 bypass (NOT marker)

如果某种特殊场景需要 commit/push 但 hook 阻塞, 走紧急 bypass:

```bash
git commit --no-verify   # 跳 pre-commit
git push --no-verify     # 跳 pre-push
```

**要求**: commit message body 显式声明 bypass 原因 (沿用 LL-098 X10 体例 commit 内 cite "X10-bypass: <具体原因>").

紧急 bypass 跟 allowlist marker **不是同一个概念**:
- allowlist marker = legacy 模块的临时豁免 (有 PR cite + 计划清除)
- 紧急 bypass = 单次 commit/push 跳过 hook (不留持久痕迹, 真特殊场景)

routine 用 bypass 而不是 marker = 治理债积累, 月度 audit 时如果发现 commit message 含 bypass cite 但没对应 marker, 需要追溯 bypass 是否合理.

## §10 LiteLLM install 状态 + cascade 依赖说明

### §10.1 install 状态 (S1 sub-task PR #221, 2026-05-03)

| 包 | 来源 | 版本 | 装入时机 |
|---|---|---|---|
| `litellm` | PyPI 直接 (pyproject.toml [project].dependencies) | `>=1.83.14` (实测装 1.83.14) | S1 PR #221 |
| `openai` | LiteLLM cascade | `2.24.0` (LiteLLM 1.83.14 pin) | S1 PR #221 自动 cascade |

cascade 关系: `pip install litellm` 自动装 openai (LiteLLM SDK 内部 import openai 走 OpenAI-compatible providers 真路径).

附带依赖升降级 (LiteLLM 1.83.14 真要求, 实测): `pydantic 2.13.2→2.12.5` / `click 8.3.2→8.1.8` / 新增 `aiohttp / fastuuid / hf-xet / huggingface-hub / jiter / regex / tiktoken / tokenizers / typer / jsonschema` 等。pre-push smoke 55 PASS 验证 0 回归。

### §10.2 跟 deepseek_client 真 lazy openai import marker 的关系

- `backend/engines/mining/deepseek_client.py` 内 `_get_openai_client` 方法含 `from openai import OpenAI  # llm-import-allow:S2-deferred-PR-219` 行 (PR #219 sediment, 防 line 号漂移用 grep marker 文本而非行号)
- S6 hook 走 `--full` mode 全 repo 扫: `# llm-import-allow:` marker 跳 BLOCK 但 stderr log `ALLOWLIST_HIT`
- S1 install 后 openai SDK 真在 .venv 里 → marker 行 lazy import **可正常 import** (NOT ImportError)
- 跟 0 hot path 结论 **0 矛盾**: 即使 import 成功, 0 production scheduler 触达 agents (详 `docs/audit/sprint_1/s8_deepseek_audit.md` §3)

### §10.3 deprecate 触发条件 (S2+ sub-task)

S6 marker (deepseek_client.py:222) 真删除条件: 沿用 `docs/audit/sprint_1/s8_deepseek_audit.md` §6 渐进 deprecate plan + ADR-031 §4.1 硬门 5 项.

### §10.4 关联

- [docs/adr/ADR-031-s2-litellm-router-implementation-path.md](adr/ADR-031-s2-litellm-router-implementation-path.md) — S2 LiteLLMRouter 新建模块决议
- [docs/audit/sprint_1/s8_deepseek_audit.md](audit/sprint_1/s8_deepseek_audit.md) — 0 hot path 证据链 + 间接 caller table
- [config/litellm_router.yaml](../config/litellm_router.yaml) — provider config (本 PR 创建, S2 真消费)
- [backend/tests/test_litellm_install.py](../backend/tests/test_litellm_install.py) — 7 install + config smoke tests
- [backend/qm_platform/llm/router.py](../backend/qm_platform/llm/router.py) — LiteLLMRouter core (S2.1 PR #222 sediment)
- [backend/qm_platform/llm/types.py](../backend/qm_platform/llm/types.py) — RiskTaskType StrEnum 7 task + LLMResponse dataclass

### §10.5 LiteLLMRouter core (S2.1 sub-task PR #222, 2026-05-03)

#### §10.5.1 模块位置

`backend/qm_platform/llm/`:
- `__init__.py` — 公共 API 导出 (LiteLLMRouter / RiskTaskType / LLMMessage / LLMResponse / TASK_TO_MODEL_ALIAS / FALLBACK_ALIAS / RouterConfigError / UnknownTaskError)
- `types.py` — 7 任务 enum (RiskTaskType StrEnum) + LLMResponse dataclass + 异常类
- `router.py` — LiteLLMRouter 类 (path 决议 + completion 包装 + fallback 检测)

V3 §11.1 line 1217 row 1 路径 **本 PR 修订**: `backend/app/integrations/litellm/` → `backend/qm_platform/llm/` (沿用 ADR-031 §3 + qm_platform 体例 + N×N 漂移第 10 次实证)。

#### §10.5.2 7 任务 → model alias mapping

| RiskTaskType | primary alias | fallback alias | V3 §5.5 行 |
|---|---|---|---|
| NEWS_CLASSIFY | deepseek-v4-flash | qwen3-local | L0.2 |
| FUNDAMENTAL_SUMMARIZE | deepseek-v4-flash | qwen3-local | L2.2 |
| BULL_AGENT | deepseek-v4-flash | qwen3-local | L2.3 |
| BEAR_AGENT | deepseek-v4-flash | qwen3-local | L2.3 |
| EMBEDDING | deepseek-v4-flash | qwen3-local | RAG ingest |
| JUDGE | deepseek-v4-pro | qwen3-local | L2.3 |
| RISK_REFLECTOR | deepseek-v4-pro | qwen3-local | L5 |

mapping 走 Python in-code (`backend/qm_platform/llm/router.py:TASK_TO_MODEL_ALIAS`),反 yaml-Python 双 SSOT 漂移。alias 真值跟 `config/litellm_router.yaml` model_list 严格对齐 (init 时 cross-verify)。

#### §10.5.3 deferred (S2.2 / S2.3 scope)

- **S2.2 budget guardrails**: BudgetGuard 类 + `llm_cost_daily` 表 + $50/月 + 80% warn + 100% Ollama 强制 fallback
- **S2.3 cost monitoring + audit trail**: LLMCallLogger + `llm_call_log` 表 + LL-103 SOP-5 5 condition + DingTalk push (V3 §16.2)
- **S5 退役**: daily aggregate 真 logic 合到 S2.3 (沿用决议 6 (a))

#### §10.5.4 关联

- ADR-031 (S2 LiteLLMRouter implementation path) — `docs/adr/ADR-031-s2-litellm-router-implementation-path.md`
- V3 §5.5 (LLM 路由真预约) / V3 §11.1 row 1 (本 PR 修订) / V3 §16.2 / V3 §20.1 #6
- 决议 2 (p1) — deepseek_client.py 0 mutation, 渐进 deprecate (ADR-031 §6)
- 决议 X2 = (ii) — 新建模块, 不改造 deepseek_client

### §10.6 Budget Guardrails (S2.2 sub-task PR #223, 2026-05-03)

#### §10.6.1 模块组件

`backend/qm_platform/llm/budget.py` (新文件):
- `BudgetState` StrEnum — 3 state (NORMAL / WARN_80 / CAPPED_100)
- `BudgetSnapshot` dataclass — check 返值 (state + month_to_date_cost + 阈值)
- `BudgetExceededError` 异常 — strict mode 反 silent fallback
- `BudgetGuard` 类 — 月聚合查询 + UPSERT record_cost (走 conn_factory DI)
- `BudgetAwareRouter` 类 — composition wrap LiteLLMRouter (NOT 继承, 沿用 ADR-022)

`backend/qm_platform/llm/router.py` 加 method (additive change, 0 mutation 现 completion):
- `LiteLLMRouter.completion_with_alias_override(task, messages, *, model_alias, decision_id, **kwargs)`
- path C 决议 — 强制覆盖 task → primary alias 走 caller 指定 model_alias
- 沿用决议 2 (p1) deepseek_client 0 mutation + ADR-022 反 silent overwrite

#### §10.6.2 3 阈值 (Settings env var, 沿用铁律 34 SSOT)

| Settings 字段 | 默认值 | V3 §20.1 #6 cite |
|---|---|---|
| `LLM_MONTHLY_BUDGET_USD` | 50.0 | $50/月上限 |
| `LLM_BUDGET_WARN_THRESHOLD` | 0.80 | 80% budget warn |
| `LLM_BUDGET_CAP_THRESHOLD` | 1.00 | 100% Ollama fallback |

调阈值 0 改代码 (沿用 BaseSettings + .env 体例)。.env.example 已加 3 var 注释 (PR #223 sediment)。

#### §10.6.3 llm_cost_daily 表 (migrations/2026_05_03_llm_cost_daily.sql)

| 列 | 类型 | 说明 |
|---|---|---|
| `day` | DATE PRIMARY KEY | 自然按日切, 0 reset cron 必要 |
| `cost_usd_total` | NUMERIC(10,4) | 当日 LLM 总 cost (UPSERT 累加) |
| `call_count` | INTEGER | 当日 LLM 调用计数 |
| `fallback_count` | INTEGER | 当日 fallback 命中计数 (含 capped 强制) |
| `capped_count` | INTEGER | 当日 capped 状态触发计数 |
| `updated_at` | TIMESTAMPTZ | 反 silent stale row |

UPSERT pattern (沿用 feature_flag.py:151 体例):
```sql
INSERT INTO llm_cost_daily (...) VALUES (...)
ON CONFLICT (day) DO UPDATE SET
    cost_usd_total = llm_cost_daily.cost_usd_total + EXCLUDED.cost_usd_total,
    call_count = llm_cost_daily.call_count + 1,
    ...
```

#### §10.6.4 BudgetAwareRouter completion 流程

```
snapshot = budget.check()           # 月聚合 cost + state 计算
                                    
if state == CAPPED_100 and strict:
    raise BudgetExceededError       # strict mode 显式禁 (RiskReflector V4-Pro only 候选)
                                    
elif state == CAPPED_100:
    response = router.completion_with_alias_override(model_alias=FALLBACK_ALIAS, ...)
                                    # 强制 qwen3-local fallback
                                    
elif state == WARN_80:
    logger.warning(extra={...})    # 结构化 JSON via stdlib extra (S2.3 audit ingest 前向兼容)
    response = router.completion(...)
                                    
else:  # NORMAL
    response = router.completion(...)  # 透传

budget.record_cost(response.cost_usd, is_fallback, is_capped)  # UPSERT 当日 row
return response
```

#### §10.6.5 LL-109 候选 (race window, P3 audit Week 2 sediment 候选)

主题: BudgetGuard.check + record_cost 真 race window — strict mode 终极保护

trigger:
- T0: task A check() → state=NORMAL
- T1: task B record_cost() → 累计撞 capped (并发其他 task)
- T2: task A 透传走 v4-pro (本应 fallback 但 check 已晚)

处置:
- strict=False (默认) → 软保护, 允许 race window 期间 1 次透传 (V3 §20.1 #6 fallback 优先)
- strict=True per-task → 终极保护 (RiskReflector / V4-Pro only 任务), capped 直接 raise
- 0 cache 决议 (S2.2 plan-mode 决议 3 沿用) — 实时正确性 > 1ms cache 节省, 缩小 race window

本候选不 sediment LESSONS_LEARNED.md (P3 backlog), 留 audit Week 2 讨论时 sediment LL-109。

#### §10.6.6 deferred (S2.3 scope)

- **audit trail**: LLMCallLogger + `llm_call_log` 表 + LL-103 SOP-5 5 condition (decision_id chain)
- **DingTalk push**: WARN_80 / CAPPED_100 状态 webhook (V3 §16.2)
- **daily aggregate 报告**: 沿用决议 6 (a) S5 退役 → S2.3 合并

#### §10.6.7 关联

- [backend/qm_platform/llm/budget.py](../backend/qm_platform/llm/budget.py)
- [backend/migrations/2026_05_03_llm_cost_daily.sql](../backend/migrations/2026_05_03_llm_cost_daily.sql)
- [backend/tests/test_litellm_budget.py](../backend/tests/test_litellm_budget.py) — 13 budget tests
- ADR-031 §6 (S2 渐进 deprecate plan)
- V3 §20.1 #6 line 1769 (LLM 月预算 sediment)
- 决议 2 (p1) / 决议 X2 = (ii) 沿用

### §10.7 Audit Trail + Cost Monitoring + DingTalk Push (S2.3 sub-task PR #224, 2026-05-03)

#### §10.7.1 模块组件

`backend/qm_platform/llm/audit.py` (新文件):
- `LLMCallRecord` frozen dataclass — 13 字段对齐 llm_call_log 表 (反 mutation, 沿用铁律 33)
- `LLMCallLogger` 类 — runtime audit log INSERT (走 conn_factory DI, 沿用 BudgetGuard 体例)
- `compute_prompt_hash` 函数 — sha256 truncated 16 hex (反 md5 collision)

`backend/qm_platform/llm/budget.py` patch (additive only, 0 break PR #223):
- `BudgetAwareRouter.__init__` 加 optional `audit: LLMCallLogger | None = None` param
- `BudgetAwareRouter.completion` 4 步 flow 真 final step 加 `_audit_log()` (audit None → skip)
- 沿用决议 6 NULL 允许体例 (反 break 老 caller, audit param 默认 None)

`scripts/llm_cost_daily_report.py` (新文件):
- 沿用 compute_daily_ic.py 体例 (argparse + dotenv + ZoneInfo + 顶层 try/except)
- 输出: 当日 sum / month-to-date sum / per-task / per-budget_state breakdown / fallback rate
- DingTalk markdown push (composition 调 dispatchers/dingtalk.py, NOT 重写, 沿用铁律 34 SSOT)
- exit code: 0=success / 1=DingTalk push 失败 / 2=fatal (沿用铁律 43 d)

#### §10.7.2 llm_call_log 表 (migrations/2026_05_03_llm_call_log.sql)

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | UUID DEFAULT gen_random_uuid() | composite PK 含 triggered_at (hypertable 硬要求) |
| `triggered_at` | TIMESTAMPTZ DEFAULT NOW() | hypertable partition column (月度 chunk) |
| `task` | VARCHAR(40) NOT NULL | 7 任务 enum CHECK (RiskTaskType cite) |
| `primary_alias` | VARCHAR(40) NOT NULL | TASK_TO_MODEL_ALIAS cite (反 fallback 检测漏报) |
| `actual_model` | VARCHAR(80) NOT NULL | LiteLLM 真返 model 名 |
| `is_fallback` | BOOLEAN NOT NULL | 是否走 qwen3-local fallback |
| `budget_state` | VARCHAR(12) NOT NULL | NORMAL / WARN_80 / CAPPED_100 CHECK |
| `tokens_in` | INTEGER NOT NULL CHECK >=0 | prompt tokens |
| `tokens_out` | INTEGER NOT NULL CHECK >=0 | completion tokens |
| `cost_usd` | NUMERIC(8,4) NOT NULL CHECK >=0 | 单次成本 (Decimal, 沿用 LLMResponse 体例) |
| `latency_ms` | INTEGER | NULL 允许 |
| `decision_id` | VARCHAR(64) | NULL 允许 (决议 6, 反 break 老 caller) |
| `prompt_hash` | VARCHAR(64) | NULL 允许 (决议 5, sha256 truncated 16 hex) |
| `error_class` | VARCHAR(40) | NULL on success / class name on failure (铁律 33) |

**3 indexes** + **180 天 TimescaleDB retention** (决议 4: 5-10 年累计 ~40-110MB, 季度审计 + 月度 review backref).

**rollback**: `2026_05_03_llm_call_log_rollback.sql` (DROP TABLE CASCADE + DO 验证).

#### §10.7.3 BudgetAwareRouter completion 流程 (S2.3 加 step 4)

```
1. snapshot = budget.check()                       # 月聚合 cost + state 计算
2. response = router.completion(...) or completion_with_alias_override(...)
3. budget.record_cost(response.cost_usd, ...)      # llm_cost_daily UPSERT
4. if audit: audit.log_call(LLMCallRecord(...))    # llm_call_log INSERT (S2.3 additive)
return response
```

**audit_log 失败 path** (决议 7 沿用铁律 33):
- INSERT 异常 → `logger.warning(structured)` + return False (反 raise — caller 沿用 completion success)
- conn_factory raise → `logger.warning(conn_factory_failed)` + return False
- prompt_hash sha256 异常 (理论不可能) → warning + prompt_hash=None

**反 except: pass silent miss** (铁律 33). 沿用 contextlib.suppress(Exception) + silent_ok 注释体例.

#### §10.7.4 daily aggregate cadence (沿用决议 6 (a) S5 退役合并)

`scripts/llm_cost_daily_report.py` Mon-Fri **20:30** (16th schtask, `setup_task_scheduler.ps1` Section 16):

- 20:30 选择: PT_Watchdog 20:00 后 30min, 全 dense window (17:30-18:45) 后 0 资源争抢
- 反 17:30 (S2.3 plan-mode finding: cadence 真 DailyMoneyflow + FactorHealthDaily 2 task 占用)
- Mon-Fri 仅: A 股非交易日 LLM 路径 (Bull/Bear/Judge) 真无活动, 周末跑只产 0 row 噪声
- DingTalk push 走 dispatchers/dingtalk.py composition (NOT 重写, 反双 SSOT 漂移)
- webhook_url 0 set 时真 noop (沿用决议 (I) stub 反 break local dev)
- DINGTALK_ALERTS_ENABLED=False 时真 noop (沿用 .env 双锁体例)

#### §10.7.5 LL-110 候选 (audit log fail-loud SOP, P3 backlog)

主题: audit log 失败时真**fail-loud warning 体例 SOP**.

trigger:
- audit.log_call INSERT 失败 → caller 沿用 completion success (反 break LLM 调用)
- 但 fail-loud warning log 真 emit (反 silent miss, 铁律 33)
- 反 except: pass (反 silent_ok 滥用)

处置 (本 PR 沿用):
- LLMCallLogger.log_call 真包络 try/except → logger.warning(structured) + return False
- contextlib.suppress(Exception) 真**仅 conn.rollback / conn.close** (close 失败 0 影响 caller)
- 反 INSERT 主路径 silent skip

本候选不 sediment LESSONS_LEARNED.md (P3 backlog), 留 audit Week 2 讨论时 sediment LL-110.

#### §10.7.6 deferred (Sprint 8 sediment 候选)

- **V3 §20.2 #3 signature scheme**: DingTalk webhook 高可用签名 (沿用 SOP-1 反预设, Sprint 8 sediment)
- **LL-104 候选 N×N drift 第 9 次实证**: V3 §11.3 RISK Sprint S5 vs LLM Sprint S5 同名不同主题 (audit Week 2 sediment 候选)
- **caller 强制走 BudgetAwareRouter (反 naked LiteLLMRouter bypass audit)**: 真**S3+ application bootstrap 时 wire** (沿用决议 2 (p1) router 0 mutation)

#### §10.7.7 关联

- [backend/qm_platform/llm/audit.py](../backend/qm_platform/llm/audit.py)
- [backend/migrations/2026_05_03_llm_call_log.sql](../backend/migrations/2026_05_03_llm_call_log.sql)
- [scripts/llm_cost_daily_report.py](../scripts/llm_cost_daily_report.py)
- [backend/tests/test_litellm_audit.py](../backend/tests/test_litellm_audit.py) — 10 audit tests
- [backend/app/services/dispatchers/dingtalk.py](../backend/app/services/dispatchers/dingtalk.py) (composition 调用)
- [docs/runbook/cc_automation/02_llm_cost_daily_runbook.md](runbook/cc_automation/02_llm_cost_daily_runbook.md)
- ADR-031 §6 (S2 渐进 deprecate plan)
- V3 §16.2 line 1579 (LLM 成本 budget) / V3 §20.1 #6 line 1769 (月预算)
- 决议 3-7 (沿用 S2.3 plan-mode 7 项 sediment)

### §10.8 Ollama Local Fallback Wire (S3 sub-task PR #225, 2026-05-03)

#### §10.8.1 install 决议 (完全 D 盘体例 II)

user 决议沿用 plan-mode + mini-verify finding:

| 项 | 决议 |
|---|---|
| install 路径 | `D:\tools\Ollama` (走 `OllamaSetup.exe /DIR=` 命令行参数, 沿用 GitHub issue #2776 PR #6967 GA 支持). 路径选 `D:\tools\` 沿用 user 现整理风格 (跟 `D:\tools\Servy` / `D:\quantmind-v2` 同 D 盘体例对齐) |
| 模型 cache 路径 | `D:\ollama-models` (走 `setx OLLAMA_MODELS /M` system-level env, sustained service 启动读 system env) |
| install 体例 | `OllamaSetup.exe` (反 winget — Ollama Inc 0 在 winget repo, 反 install.ps1 — 0 custom path 参数) |
| user 接触 | ~2 clicks (1 UAC click + 1 安装向导 "Install" click) + 3 PS commands (PS Start-Process install + setx /M + ollama pull). ~5-15 min wall-clock (含 5.2 GB 网络下载) |

完整步骤沿用 [`docs/runbook/cc_automation/03_ollama_install_runbook.md`](runbook/cc_automation/03_ollama_install_runbook.md).

#### §10.8.2 yaml endpoint patch (ollama → ollama_chat)

`config/litellm_router.yaml` line 33 patch:

```yaml
# 旧 (PR #221): model: ollama/qwen3:8b          → 走 /api/generate (legacy)
# 新 (PR #225): model: ollama_chat/qwen3:8b     → 走 /api/chat (LiteLLM 官方推荐)
```

LiteLLM docs cite "for better responses" — chat endpoint 输出质量沿用. 路由 alias 沿用 `qwen3-local` (PR #221+ contract, 0 break BudgetAwareRouter `completion_with_alias_override(model_alias=FALLBACK_ALIAS)`).

#### §10.8.3 PRIMARY_MODEL_SUBSTRINGS fallback 检测沿用

`backend/qm_platform/llm/router.py` PRIMARY_MODEL_SUBSTRINGS:

```python
{
    "deepseek-v4-flash": "deepseek-chat",
    "deepseek-v4-pro": "deepseek-reasoner",
}
```

actual_model (e.g. `ollama_chat/qwen3:8b` 沿用 LiteLLM 真返 model 名 `qwen3:8b` 或类似) 真**不含** `deepseek-chat` / `deepseek-reasoner` 子串 → `is_fallback=True` 自动检测沿用. PR #222 sediment 0 改.

#### §10.8.4 e2e 1-2 冒烟 (requires_ollama marker)

`backend/tests/test_litellm_e2e.py` 2 tests:

| test | 验证 |
|---|---|
| `test_e2e_ollama_chat_qwen3_via_alias_override` | LiteLLMRouter.completion_with_alias_override 走 ollama_chat/qwen3:8b endpoint, content 非空 + is_fallback=True + cost_usd=0 + latency_ms>0 |
| `test_e2e_budget_capped_forces_ollama_fallback` | BudgetAwareRouter 4 步 flow CAPPED_100 强制 fallback, actual_model 含 "qwen" + is_fallback=True |

skip logic:
- 模块级 socket probe `localhost:11434` — 0 listening → skip 全模块 (沿用 LL-098 X10, e2e 反 CI / pre-push 跑)
- pytest marker `requires_ollama` 沿用 `pyproject.toml` markers list (跟 smoke / live_tushare 体例对齐)
- pre-push 走 `backend/tests/smoke/ -m "smoke and not live_tushare"` 限 smoke/ 子目录, e2e tests 在顶层 `backend/tests/` 0 收录, 0 break pre-push

#### §10.8.5 Ollama Windows service 自启 (0 schtask wire)

Ollama 官方 OllamaSetup.exe 自动注册 Windows service "Ollama" + StartType=Automatic. reboot 后 service 自启 — **0 schtask wire 必要** (反 setup_task_scheduler.ps1 改).

verify (post-install):

```powershell
Get-Service Ollama
# 期望: Status=Running, StartType=Automatic
```

#### §10.8.6 GPU CUDA 加速沿用

RTX 5070 12 GB VRAM → Ollama 自动检测 CUDA, qwen3:8b Q4_K_M 沿用 ~5 GB VRAM (12 GB 充裕). 反需手工配置 — runbook 03 troubleshoot 沿用 `nvidia-smi` 验证.

#### §10.8.7 deferred (Sprint 1 后)

- **Sprint 8**: V3 §20.2 #3 DingTalk webhook 高可用签名 (沿用 SOP-1 反预设)
- **audit Week 2**: LL-110 候选 (audit log fail-loud SOP, S2.3 sediment) + LL-111 候选 (S4 cite drift, S4 老主题 Budget 已并入 S2.2)
- **S3+ application bootstrap wire**: caller 强制走 BudgetAwareRouter (反 naked LiteLLMRouter bypass audit + budget) — sustained 决议 2 (p1) router 0 mutation

#### §10.8.8 关联

- [config/litellm_router.yaml](../config/litellm_router.yaml) (S3 PR #225 ollama→ollama_chat patch)
- [backend/tests/test_litellm_e2e.py](../backend/tests/test_litellm_e2e.py) (2 e2e + requires_ollama marker)
- [docs/runbook/cc_automation/03_ollama_install_runbook.md](runbook/cc_automation/03_ollama_install_runbook.md)
- ADR-031 §6 (S2 渐进 deprecate plan, S3 Ollama wire 沿用)
- V3 §20.1 #6 line 1769 (100% Ollama fallback 沿用)
- [GitHub issue #2776](https://github.com/ollama/ollama/issues/2776) (custom install dir support, /DIR= GA)
- [Ollama qwen3 Library](https://ollama.com/library/qwen3) (5.2 GB Q4_K_M default)
- [LiteLLM Ollama Provider Docs](https://docs.litellm.ai/docs/providers/ollama) (ollama_chat better responses)

### §10.9 S4 Caller Bootstrap Factory + Naked Router Export Restriction (PR #226, 2026-05-03)

#### §10.9.1 决议 sediment

V3 Sprint 1 S4 sub-task (8/8 完成, ADR-032). 老主题 (Budget guardrails) 已并入 S2.2 PR #223, 编号转给新主题 caller bootstrap enforcement.

| 项 | 决议 |
|---|---|
| factory 体例 | `get_llm_router(*, settings=None, conn_factory=None)` 沿用 `alert.py:528-554` double-checked lock + reset_*() |
| singleton lifecycle | process-level cache (module-level _router_singleton + threading.Lock) |
| 降级 mode | `conn_factory=None` 走 naked LiteLLMRouter (反 BudgetGuard 真 None DB call), Sprint 2+ application bootstrap 时显式 wire 启用全 governance |
| _internal/ 子包 | router.py / budget.py / audit.py 全移 _internal/ (caller 反直接 import) |
| public API surface | 18 → 6 export (factory 2 + types 5: RiskTaskType / LLMMessage / LLMResponse / RouterConfigError / UnknownTaskError) |
| hook 检测 | `scripts/check_llm_imports.sh` 加 S4_INTERNAL_PATTERN + allowlist marker `# llm-internal-allow:` |
| test 排除 | backend/tests/* 走 hook scope 排除 (沿用 PR #219), 加 file-level marker 沿用 documentation |

#### §10.9.2 模块结构 (S4 PR #226)

```
backend/qm_platform/llm/
├── __init__.py            # 公共 API 6 names (get_llm_router / reset_llm_router + 5 types)
├── bootstrap.py           # factory + singleton 沿用 alert.py 体例
├── types.py               # 公共 dataclass + enum + exception (PR #222 sediment, sustained)
└── _internal/             # internal-only, caller 反直接 import (hook BLOCK)
    ├── __init__.py
    ├── router.py          # 移自 backend/qm_platform/llm/router.py (S4 git mv)
    ├── budget.py          # 移自 backend/qm_platform/llm/budget.py (S4 git mv)
    └── audit.py           # 移自 backend/qm_platform/llm/audit.py (S4 git mv)
```

#### §10.9.3 caller 真生产典型用法

```python
# ✅ 沿用 sanctioned path (factory)
from backend.qm_platform.llm import get_llm_router, RiskTaskType, LLMMessage

# === Mode 1: 降级 mode (conn_factory=None default) ===
# return type: LiteLLMRouter (反 BudgetGuard / Audit, 沿用决议 — Sprint 2+ wire)
# completion signature: completion(task, messages, *, decision_id=None, **kwargs)
# 沿用 LiteLLMRouter 真 completion API (PR #222 sediment, _internal/router.py)
router = get_llm_router()
response = router.completion(
    task=RiskTaskType.JUDGE,
    messages=[LLMMessage("user", "判定...")],
    decision_id="risk-event-uuid-xxx",
)
# response.cost_usd / response.is_fallback 沿用 LLMResponse contract (PR #222)
# 反 BudgetGuard.check_state / 反 LLMCallLogger.log_call (降级 mode 0 wire).

# === Mode 2: 全 governance mode (Sprint 2+ application bootstrap) ===
# return type: BudgetAwareRouter (BudgetGuard + LLMCallLogger 全 wire)
# completion signature: completion(task, messages, *, decision_id=None, **kwargs)
# 沿用 BudgetAwareRouter 真 completion API (PR #223+#224 sediment, _internal/budget.py)
def _conn_factory():
    return psycopg2.connect(settings.DATABASE_URL_SYNC)

router = get_llm_router(conn_factory=_conn_factory)
# 4 步 flow: budget.check() → router.completion() → budget.record_cost() → audit.log_call()
# response 沿用同 LLMResponse contract, 但走全 governance 路径 (反 silent skip).
```

**caller 真**不必关心 return type 区分**真**completion API 一致** (沿用 PR #222 contract, 反 break 老 caller). 仅**走 BudgetGuard / LLMCallLogger 真 governance** 真区别. 反**强制走全 governance** sustained 决议 (Sprint 2+ wire 时 caller 显式传 conn_factory).

```python
# ❌ 反向用法 — bypass factory + audit + budget governance, hook 自动 BLOCK
from backend.qm_platform.llm._internal.router import LiteLLMRouter
```

#### §10.9.4 test isolation (autouse fixture)

```python
# backend/tests/conftest.py (S4 PR #226 sediment)
@pytest.fixture(autouse=True)
def _reset_llm_singleton():
    """LLM Router 全局 singleton 跨 test reset (沿用 alert.py reset_*() 体例)."""
    yield
    from backend.qm_platform.llm import reset_llm_router
    reset_llm_router()
```

反 cross-test pollution: 上 test mock monkeypatch litellm.Router.completion → 下 test 沿用 mock 漂移 — autouse reset 真**反此 silent miss**.

#### §10.9.5 hook 检测 + allowlist marker

`scripts/check_llm_imports.sh` 真 S4 第 2 轮 scan loop:

| 项 | 真值 |
|---|---|
| S4_INTERNAL_PATTERN | `^[[:space:]]*from[[:space:]]+backend\.qm_platform\.llm\._internal` |
| ALLOWLIST_MARKER | `# llm-internal-allow:` |
| scope (--full mode) | backend/app/ + backend/engines/ + scripts/ (排除 backend/qm_platform/llm/ + backend/tests/* + scripts/check_llm_imports.sh) |
| scope (--staged mode) | git diff --cached staged Python files, 排除同上 |
| BLOCK 体例 | exit 1 + 详细错误 + 修复指引 (改 `from backend.qm_platform.llm import get_llm_router`) |
| 临时豁免 (legacy only) | 行内加 `# llm-internal-allow:<reason-or-issue-ref>` (沿用 PR #219 体例) |

test 真 file-level marker (沿用 4 test 文件):

```python
# llm-internal-allow:test-only — S4 PR #226 sediment, mock 体例真依赖 _internal/ 直接 import
from backend.qm_platform.llm._internal.router import LiteLLMRouter
```

#### §10.9.6 0 prod caller break

| path | 现状 | S4 后 |
|---|---|---|
| backend/app/ FastAPI | 0 LiteLLMRouter import (S8 audit §3 0 hot path) | sustained 0 触碰 |
| backend/app/tasks/ Celery beats | 0 LiteLLMRouter import | sustained 0 触碰 |
| backend/engines/ | 0 LiteLLMRouter import | sustained 0 触碰 |
| scripts/llm_cost_daily_report.py (S2.3) | 0 LLM import (仅 DB SELECT + DingTalk push) | sustained 0 触碰 |
| factor_agent / idea_agent | sustained deepseek_client (ADR-031 §6 deprecate plan) | sustained 0 触碰 (沿用决议 2 (p1)) |
| **未来 caller** (RiskReflector / Bull/Bear / NewsClassifier) | 0 实施 | Sprint 2+ application bootstrap 真**走 get_llm_router()** |

#### §10.9.7 deferred (Sprint 2+ / audit Week 2)

- **Sprint 2+ application bootstrap wire**: caller (RiskReflector / Bull/Bear / NewsClassifier) 显式 `get_llm_router(conn_factory=...)` 启用全 governance
- **ADR-031 §6 渐进 deprecate plan**: factor_agent / idea_agent 切换 LiteLLMRouter (Sprint 2-N)
- **audit Week 2 batch sediment**:
  - LL-110 (audit log fail-loud SOP)
  - LL-111 (S4 cite drift, 老 Budget 主题已并 S2.2)
  - LL-112 (bash 残留 hook trap 防长期残留)
  - _CappedFakeCursor helper extraction (3 test 文件 mock 重复, audit Week 2 follow-up PR)

#### §10.9.8 关联

- [docs/adr/ADR-032-s4-caller-bootstrap-factory-and-naked-router-export-restriction.md](adr/ADR-032-s4-caller-bootstrap-factory-and-naked-router-export-restriction.md)
- [backend/qm_platform/llm/bootstrap.py](../backend/qm_platform/llm/bootstrap.py) (factory + singleton)
- [backend/qm_platform/llm/_internal/](../backend/qm_platform/llm/_internal/) (internal-only 子包)
- [backend/qm_platform/observability/alert.py](../backend/qm_platform/observability/alert.py) :528-554 (factory 体例参考)
- [scripts/check_llm_imports.sh](../scripts/check_llm_imports.sh) (S6 PR #219 + S4 PR #226 sediment)
- ADR-022 反 silent overwrite / ADR-031 §6 渐进 deprecate plan
- V3 §5.5 (LiteLLM 路由) / V3 §11.1 (path-level abstraction, 0 V3 patch)
- 决议 2 (p1) sustained: deepseek_client.py 0 mutation
