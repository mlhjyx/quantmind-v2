# S8 — DeepSeek Prototype Audit (Sprint 1)

> **scope**: read-only audit, 0 生产代码改动 / 0 install / 0 .env 改 / 0 SQL 写
> **时间点**: 2026-05-03
> **main HEAD**: `270d5e1` (post-PR #219 S6 hook 完整 enforce)
> **关联**: V3 Sprint 1 sub-task S8 (deepseek_client.py 现状审计 + S2 LiteLLMRouter implementation path 决议)
> **沿用**: SOP-1 (Claude.ai prompt 表格 cite 全表 grep cross-verify) / SOP-2 (audit cite SQL/git/log 实测 verify) / SOP-6 (ADR # reservation 4 source cross-verify, LL-105)

---

## §1 audit scope + 时间点 + main HEAD reference

- **scope**: backend/engines/mining/deepseek_client.py (396 lines) + 2 callers + 57 tests + ModelRouter 4 路由 + V3 §5.5 LiteLLMRouter 真预约 mapping
- **时间点**: 2026-05-03 (Session 51)
- **main HEAD**: `270d5e1d6ef7c35cb4d01951679607587ff4eea8`
- **前置 PR**: PR #219 (S6 CI lint anthropic/openai import block + allowlist marker, sustained `# llm-import-allow:S2-deferred-PR-219` 标记 line 222)
- **后置 sub-task**: S2 LiteLLMRouter 新建模块 (本 audit 决议 implementation path)

---

## §2 deepseek_client.py 现状

### §2.1 文件结构

| 类 | 行号 | 职责 |
|---|---|---|
| `CostTracker` | 99 | 月度成本累计 + 预算阈值告警 (Sprint 1.17 sediment) |
| `ModelRouter` | 134 | 4 任务类型 → 模型路由 |
| `DeepSeekClient` | 169 | 主调用层 + lazy openai import + native deepseek API |

总 396 lines.

### §2.2 ModelRouter 路由表 (line 65-70 TaskType + 134-159 ModelRouter class, route() 方法 line 147-159)

```python
class TaskType(StrEnum):
    IDEA      = "idea"       # Idea Agent: 因子假设生成
    FACTOR    = "factor"     # Factor Agent: 代码生成
    EVAL      = "eval"       # Eval Agent: 统计评估
    DIAGNOSIS = "diagnosis"  # Diagnosis Agent: 根因分析
```

| TaskType | 主路由 | fallback |
|---|---|---|
| IDEA | deepseek-reasoner (R1) | — |
| FACTOR | qwen3 本地 (零成本) | deepseek-chat |
| EVAL | deepseek-chat | — |
| DIAGNOSIS | deepseek-reasoner (R1) | — |

### §2.3 CostTracker logic

- 月度累计 cost (sum of completion_tokens × price)
- 阈值 80% warn / 100% hard stop (SOP)
- 0 持久化 (内存计数, restart 清零) — 跟 V3 §5.5 月度预算 review 半契合

### §2.4 callers (生产范围)

`grep -rln "DeepSeekClient\|ModelRouter" backend/ scripts/ --include="*.py" | grep -v __pycache__`:

| 文件 | cite 数 | 类型 |
|---|---|---|
| `backend/engines/mining/agents/factor_agent.py` (233 lines) | 5 | 引用 DeepSeekClient + ModelRouter + TaskType |
| `backend/engines/mining/agents/idea_agent.py` (397 lines) | 2 | 引用 DeepSeekClient |
| `backend/engines/mining/deepseek_client.py` | self | self-define |
| `backend/tests/test_deepseek_client.py` | 57 tests | mock test |
| `backend/tests/test_llm_import_block_governance.py` | — | S6 governance test (PR #219) |

**0 引用** 出现在 `backend/app/` (FastAPI 服务层) / `scripts/` (schtask) / `backend/app/tasks/` (Celery beats).

---

## §3 0 真生产 hot path 证据链

### §3.1 上轮 plan-mode finding 错点订正

- 上轮 finding: "DEEPSEEK_API_KEY=sk-xxx 默认 mock_mode"
- 本轮实测: `backend/.env:9` = `DEEPSEEK_API_KEY=sk-ad4c1faa3feb4d209b2dd04230e64d6a` (真 key)
- 同时 `mock_mode: bool = False` 默认 (line 197), 走 `self.mock_mode = mock_mode or not self.api_key` (line 206) — API key 存在则 mock_mode=False

→ 上轮 "0 hot path 由 SDK 缺失 + mock_mode 保证" 推理路径 **错**。

### §3.2 本轮 0 hot path 证据 (架构未接线)

`grep -rn "engine_selector\|EngineSelector\|FactorAgent\|IdeaAgent" backend/app/ scripts/ --include="*.py" | grep -v __pycache__` → **0 行输出**。

| 维度 | 证据 |
|---|---|
| FastAPI 服务层 (`backend/app/api/`) | 0 引用 agents/engine_selector |
| schtask 脚本 (`scripts/`) | 0 引用 agents/engine_selector |
| Celery beats (`backend/app/tasks/`) | 0 引用 agents |
| settings 注册 (`param_defaults.py:921,929`) | 仅 settings key 注册 (`llm_mining.idea_agent_model` / `llm_mining.factor_agent_model`),**0 实际调用** |
| 唯一调用方 | `backend/tests/test_d5_d6_agents_selector.py` + `test_deepseek_client.py` (mock 测试) |
| openai SDK 安装 | `pip show openai` → not found,即使 agents 被调用,FACTOR 路由 (qwen3 本地) 走 lazy openai import 会 ImportError fail-loud |

### §3.3 hot path 风险结论

**生产运行时 0 路径触达 agents**。证据:

1. **架构未接线** (主证据): 0 scheduler / 0 router / 0 service endpoint 引用 agents 类
2. **lazy import fail-loud** (副证据): 即使有人手动调用 FACTOR 路由,openai SDK 0 install → ImportError 立即 fail (NOT silent),走 deepseek_client.py:217-228 显式 raise

→ 结论可信度高,与 backend/.env 真 API key 存在 **0 矛盾**。即使 .env 配 key,真生产路径仍 0 触达。

---

## §4 ModelRouter 4 路由 → V3 §5.5 6 任务 mapping

V3 §5.5 line 714-720 真任务表:

| V3 §5.5 任务 | 模型 | 频率 | ModelRouter 现 4 路由 mapping |
|---|---|---|---|
| L0.2 NewsClassifier | V4-Flash | 100-300 calls/天 | **0 mapping** |
| L2.2 fundamental_context summarizer | V4-Flash | 10/天 | **0 mapping** |
| L2.3 Bull/Bear Agent | V4-Flash | 6/天 | **0 mapping** |
| L2.3 Judge | V4-Pro | 3/天 | **0 mapping** |
| L5 RiskReflector | V4-Pro | 周1+月1+post-event | **0 mapping** |
| Embedding (RAG ingest) | V4-Flash | 1/事件 | **0 mapping** |
| 灾备 fallback | Ollama 本地 | LiteLLM 全 timeout 时 | **0 mapping** |

ModelRouter 现 4 路由 (IDEA/FACTOR/EVAL/DIAGNOSIS) 服务 GP closed-loop 因子挖掘域,**V3 §5.5 6 任务全 risk control 域**,domain 0 重叠。

→ S2 LiteLLMRouter 新建模块,跟 ModelRouter **职责正交** (前者 risk LLM 路由,后者 factor mining LLM 路由)。

---

## §5 S2 LiteLLMRouter implementation path 决议

### §5.1 user 决议 X2 = (ii) 新建 LiteLLMRouter + deepseek_client 渐进 deprecate

3 候选 path:

| path | 说明 | 决议 verdict |
|---|---|---|
| (i) | 改造现 deepseek_client.py 为 LiteLLMRouter (in-place) | **拒** (违反 ADR-022 反 silent overwrite + 决议 2 (p1) deepseek_client 0 mutation) |
| **(ii)** | **新建 backend/qm_platform/llm/router.py LiteLLMRouter,deepseek_client 0 改 + 渐进 deprecate** | **采纳** (沿用 V3 §5.5 LiteLLMRouter 真预约 + ADR-022 + 决议 2 (p1)) |
| (iii) | 双 router 并存长期 (LiteLLMRouter for risk, ModelRouter for factor mining 不 deprecate) | **拒** (违反 ADR-020 LiteLLM-only enforce, ModelRouter 走 native deepseek API 不经 LiteLLM 路由,绕 budget guardrails / cost monitoring / multi-provider 统一) |

### §5.2 path (ii) 决议依据

1. **ADR-020** (V3 §18.1 row 2 真预约): LiteLLM 是 only path,沿用 4-29 user 决议
2. **ADR-022** (反 silent overwrite): 现 1026 lines GP 闭环 prototype (deepseek_client + agents + tests, Sprint 1.17 sediment) 0 mutation by stealth
3. **user 决议 2 (p1)**: deepseek_client.py 0 logic mutation 直到 S2 sediment
4. **V3 §5.5 LiteLLMRouter 是新模块** (line 723: "LiteLLMRouter (新模块) 强制走 LiteLLM"),从 V3 设计层就预定为新建
5. **domain 正交** (§4 mapping 证): ModelRouter 服务 factor mining,LiteLLMRouter 服务 risk control,职责不重叠
6. **0 hot path 风险** (§3 证): deepseek_client 真生产 0 触达,渐进 deprecate 0 中断生产

### §5.3 反驳 (i) 路径

- 改造现 deepseek_client.py 为 LiteLLMRouter 会 silent overwrite Sprint 1.17 真已稳定的 396 lines + 57 tests
- 改造范围: ModelRouter 4 路由 → LiteLLM 6+ 路由,语义不兼容 (FACTOR=qwen3 本地 vs L2.3 Bull/Bear=V4-Flash)
- 违反 ADR-022 sprint period treadmill 反 anti-pattern + ADR-008 命名空间契约

### §5.4 反驳 (iii) 路径

- 双 router 并存绕 ADR-020 LiteLLM-only enforce
- ModelRouter 走 native deepseek API (deepseek_v3 endpoint),不经 LiteLLM 中间层 → budget guardrails / cost monitoring / multi-provider fallback 全失效
- V3 §5.5 LLM 调用 unified path 失败,违反 V3 §16.2 cost monitoring (daily 累计 + DingTalk push) + LL-103 SOP-5 audit trail

---

## §6 渐进 deprecate plan

S2 LiteLLMRouter 完成后渐进 deprecate path (sediment 到 ADR-031):

```
[Sprint 1 末]
S2 LiteLLMRouter 新建模块 (backend/qm_platform/llm/router.py)
  ├─ 6 任务路由 (V3 §5.5 真表)
  ├─ Budget guardrails (ADR-020 + V3 §20.1 #6)
  ├─ Cost monitoring daily 累计 (V3 §16.2)
  ├─ Audit trail (LL-103 SOP-5)
  └─ Ollama fallback (V3 §5.5 line 720)

[Sprint 2-N: 渐进迁移]
factor_agent + idea_agent caller 改造 (S2 完成 + user 显式决议时):
  ├─ 引用从 ModelRouter → LiteLLMRouter
  ├─ TaskType.FACTOR/IDEA → LiteLLM 真任务 enum
  ├─ 跑 mock test pass + 跑 1 次 dry-run cite cost
  └─ 沿用 ADR-022 集中修订机制 (NOT 单步 silent overwrite)

[Sprint N+: 0 caller 状态]
deepseek_client.py 真 0 caller (factor_agent + idea_agent 全切到 LiteLLMRouter):
  ├─ 跑 grep cross-verify 0 caller
  ├─ 显式 deprecate PR (cite ADR-031 + 沿用 ADR-022)
  ├─ 真 file 删除 OR 移到 docs/archive/legacy/ (user 决议)
  └─ test_deepseek_client.py 同步删除 (57 tests)

[deprecate 显式条件]
- LiteLLMRouter Sprint N 验收通过 (跑 paper-mode 5d)
- factor_agent + idea_agent 切换 PR merged
- grep "DeepSeekClient\|ModelRouter" 真 0 输出 (production scope)
- user 显式决议 deprecate (NOT auto)
```

### §6.1 全 repo grep 主动发现 (沿用 SOP-1)

直接 caller (`grep -rln "deepseek_client\|DeepSeekClient" backend/ scripts/ --include="*.py" | grep -v __pycache__`):

| caller | 类型 | S2 后 path |
|---|---|---|
| backend/engines/mining/agents/factor_agent.py | 生产 caller | Sprint N 切到 LiteLLMRouter |
| backend/engines/mining/agents/idea_agent.py | 生产 caller | Sprint N 切到 LiteLLMRouter |
| backend/engines/mining/deepseek_client.py | self | deprecate 时删 |
| backend/tests/test_deepseek_client.py | mock 测试 | deprecate 时删 |
| backend/tests/test_llm_import_block_governance.py | S6 治理测试 | **保留**,删除 deepseek_client.py:222 marker preserve 测试 (那条测试由 S2 PR 同步删) |

间接 caller (引用 agents/engine_selector, 真 deprecate 时一并处理):

| caller | 引用 | 类型 | S2 后 path |
|---|---|---|---|
| backend/tests/test_d5_d6_agents_selector.py | `FactorAgent` + `engine_selector` | mock 测试 | deprecate 时删 (跟 agents 同步删) |
| backend/engines/mining/engine_selector.py | comment line 16 cite agents | 文件本身 | deprecate 时删 (跟 agents 同步删) |

**0 别的潜在 caller** (主动 grep cross-verify 通过)。

### §6.2 deprecate 硬门 grep (扩展, 沿用 reviewer chunked SOP findings)

```bash
# 主 caller cross-verify
grep -rln "DeepSeekClient\|ModelRouter" backend/ scripts/ --include="*.py" | grep -v __pycache__
# 间接 caller cross-verify (agents/selector 真删除前)
grep -rln "FactorAgent\|IdeaAgent\|engine_selector" backend/ scripts/ --include="*.py" | grep -v __pycache__
```

两个命令真 0 production 输出 (test 路径除外) 才允许 deprecate PR 起手。

---

## §7 P3 backlog 候选 (LL-108)

### §7.1 主题

V3 §5.5 计费表 line 714-720 单位混用 (天 vs 月)。

### §7.2 实测引用

```
| L0.2 NewsClassifier | V4-Flash | 每日 100-300 calls | $0.05-0.15/天 |
| L2.2 fundamental_context summarizer | V4-Flash | 每 alert 1 call (~10/day) | $0.02/天 |
| L2.3 Bull Agent / Bear Agent | V4-Flash | 每日 6 calls | $0.03/天 |
| L2.3 Judge | V4-Pro | 每日 3 calls | $1/天 |
| L5 RiskReflector | V4-Pro | 周 1 + 月 1 + post-event | $5-10/月 |    ← 单位漂
| Embedding (RAG ingest) | V4-Flash | 每 risk_event 1 call | $0.01/事件 |  ← 单位漂
```

5 行 $/天 + 1 行 $/月 + 1 行 $/事件 三单位混用,$50/月 budget 真核需先归一。

### §7.3 sediment 时机

- 本 PR scope 外 (audit Week 2 候选讨论时 sediment)
- LL-108 候选 + ll_unique_ids 当前 97 → audit Week 2 sediment 后 98
- 上轮 plan-mode 给出的 cite line 718-723 微漂,实测 line 714-720 (4 行偏移),归因可能 V3 doc 多次 patch 后行号变 — sediment 时 cite 必走 git blame 锁 commit

---

## §8 audit 总结

### §8.1 本 audit 决议

| # | 决议 | 状态 |
|---|---|---|
| 1 | deepseek_client.py 0 mutation | **保持** (sustained 决议 2 (p1)) |
| 2 | S2 LiteLLMRouter implementation path = (ii) 新建模块 + 渐进 deprecate | **采纳** (沿用 user 决议 X2) |
| 3 | ADR-031 sediment | **本 PR 创建** |
| 4 | LL-108 (V3 §5.5 计费表单位混用) | **deferred** (audit Week 2 候选) |
| 5 | factor_agent + idea_agent 切换 PR | **deferred** (S2 sediment 后 + user 显式决议) |

### §8.2 后续 sub-task

- **S1** (LiteLLM SDK install + .env 配置 split V4-Flash/V4-Pro): 1.5h work
- **S2** (LiteLLMRouter 新建模块 + 6 任务路由): 1-2d work
- **S3** (Ollama install + Qwen3 fallback): 0.5d
- **S4** (Budget guardrails + 月度 review): 1d
- **S5** (LLM cost monitoring daily 累计 + DingTalk): 0.5-1d
- **S7** (6 News 源 API key registry): Sprint 2 deferred

### §8.3 验证清单 (本 audit 后 Sprint 1 进度)

| sub-task | 状态 |
|---|---|
| S6 (CI lint anthropic/openai block) | ✅ PR #219 |
| **S8 (本 PR)** | ✅ 进行中 |
| S1 / S2 / S3 / S4 / S5 | ⏳ pending |
| S7 | deferred to Sprint 2 |

→ 本 PR merge 后 **Sprint 1 进度 2/8** (S6 + S8)。
