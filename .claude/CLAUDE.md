<!-- OMC:START -->
<!-- OMC:VERSION:4.9.1 -->

# oh-my-claudecode - Intelligent Multi-Agent Orchestration

You are running with oh-my-claudecode (OMC), a multi-agent orchestration layer for Claude Code.
Coordinate specialized agents, tools, and skills so work is completed accurately and efficiently.

<operating_principles>
- Delegate specialized work to the most appropriate agent.
- Prefer evidence over assumptions: verify outcomes before final claims.
- Choose the lightest-weight path that preserves quality.
- Consult official docs before implementing with SDKs/frameworks/APIs.
</operating_principles>

<delegation_rules>
Delegate for: multi-file changes, refactors, debugging, reviews, planning, research, verification.
Work directly for: trivial ops, small clarifications, single commands.

**QuantMind V2 专业角色路由（优先于通用agent）：**
本项目有10个领域专用agent定义在 `.claude/agents/`，每个包含完整的宪法上下文（铁律/交叉审查/设计文档路径）。
任务分配时必须优先使用这些角色，不用OMC通用agent：

| 任务类型 | 路由到 | 说明 |
|---------|--------|------|
| 后端编码/架构/引擎 | `arch` (sonnet) | Service层/回测引擎/调度链路/CompositeStrategy/NSSM |
| 测试/质量/验证 | `qa-tester` (sonnet) | 破坏性测试，测试不过=不验收 |
| 量化逻辑/统计审查 | `quant-reviewer` (opus) | IC/过拟合/交易成本/Gate统计标准，一票否决 |
| 因子研究/经济学假设 | `factor-researcher` (sonnet) | 因子分类框架(R1)/生命周期/Alpha158对标 |
| 策略设计/因子匹配/Modifier | `strategy-designer` (opus) | 铁律8核心/FactorClassifier/CompositeStrategy/Modifier设计 |
| 风险评估/熔断/压力测试 | `risk-guardian` (opus) | "怎么不亏钱"/Modifier组合风险/滑点监控，一票否决 |
| 数据拉取/质量/单位对齐/备份 | `data-engineer` (sonnet) | Tushare/AKShare/备份架构(R6)/滑点数据(R4) |
| 因子挖掘/IC验证/Pipeline | `alpha-miner` (sonnet) | 3引擎Pipeline(R2)/Gate G1-G8/29个未实现因子 |
| ML训练/GP引擎/DeepSeek | `ml-engineer` (sonnet) | LightGBM/DEAP GP(R2)/DeepSeek集成(R7)/OOS验证 |
| React前端/12页面/基础设施 | `frontend-dev` (sonnet) | Router/Zustand/WebSocket/12页面/57端点 |

所有agent共享宪法上下文: `.claude/agents/_charter_context.md`（8铁律/交叉审查矩阵/工作原则）。
编码完成后必须由对应交叉审查角色review（如arch代码→qa+data challenge）。
</delegation_rules>

<model_routing>
`haiku` (quick lookups), `sonnet` (standard), `opus` (architecture, deep analysis).
Direct writes OK for: `~/.claude/**`, `.omc/**`, `.claude/**`, `CLAUDE.md`, `AGENTS.md`.
</model_routing>

<skills>
Invoke via `/oh-my-claudecode:<name>`. Trigger patterns auto-detect keywords.
Tier-0 workflows include `autopilot`, `ultrawork`, `ralph`, `team`, and `ralplan`.
Keyword triggers: `"autopilot"→autopilot`, `"ralph"→ralph`, `"ulw"→ultrawork`, `"ccg"→ccg`, `"ralplan"→ralplan`, `"deep interview"→deep-interview`, `"deslop"`/`"anti-slop"`→ai-slop-cleaner, `"deep-analyze"`→analysis mode, `"tdd"`→TDD mode, `"deepsearch"`→codebase search, `"ultrathink"`→deep reasoning, `"cancelomc"`→cancel.
Team orchestration is explicit via `/team`.
Detailed agent catalog, tools, team pipeline, commit protocol, and full skills registry live in the native `omc-reference` skill when skills are available, including reference for `explore`, `planner`, `architect`, `executor`, `designer`, and `writer`; this file remains sufficient without skill support.
</skills>

<verification>
Verify before claiming completion. Size appropriately: small→haiku, standard→sonnet, large/security→opus.
If verification fails, keep iterating.
</verification>

<execution_protocols>
Broad requests: explore first, then plan. 2+ independent tasks in parallel. `run_in_background` for builds/tests.
Keep authoring and review as separate passes: writer pass creates or revises content, reviewer/verifier pass evaluates it later in a separate lane.
Never self-approve in the same active context; use `code-reviewer` or `verifier` for the approval pass.
Before concluding: zero pending tasks, tests passing, verifier evidence collected.
</execution_protocols>

<hooks_and_context>
Hooks inject `<system-reminder>` tags. Key patterns: `hook success: Success` (proceed), `[MAGIC KEYWORD: ...]` (invoke skill), `The boulder never stops` (ralph/ultrawork active).
Persistence: `<remember>` (7 days), `<remember priority>` (permanent).
Kill switches: `DISABLE_OMC`, `OMC_SKIP_HOOKS` (comma-separated).
</hooks_and_context>

<cancellation>
`/oh-my-claudecode:cancel` ends execution modes. Cancel when done+verified or blocked. Don't cancel if work incomplete.
</cancellation>

<worktree_paths>
State: `.omc/state/`, `.omc/state/sessions/{sessionId}/`, `.omc/notepad.md`, `.omc/project-memory.json`, `.omc/plans/`, `.omc/research/`, `.omc/logs/`
</worktree_paths>

## Setup

Say "setup omc" or run `/oh-my-claudecode:omc-setup`.

<!-- OMC:END -->
