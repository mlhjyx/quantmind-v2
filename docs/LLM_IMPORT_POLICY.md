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
