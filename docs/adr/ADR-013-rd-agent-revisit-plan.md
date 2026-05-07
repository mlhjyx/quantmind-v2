---
adr_id: ADR-013
title: RD-Agent Re-evaluation Plan (Wave 4+ Decision Gate, not adoption decision)
status: accepted
related_ironlaws: [21, 23, 25, 38]
recorded_at: 2026-04-26
supersedes: (none, supplements 阶段 0 RD-Agent NO-GO 决策 2026-04-10)
related: ADR-012-wave-5-operator-ui, QUANTMIND_LANDSCAPE_ANALYSIS_2026.md, DEV_AI_EVOLUTION V2.1
---

## Context

### 阶段 0 NO-GO (2026-04-10) 原因回顾

QM 阶段 0 (`memory/project_session_2026_0410b.md`) 评估 RD-Agent 后定为 NO-GO:

| 阻断原因 | 当时认知 |
|---|---|
| Docker 硬依赖 | RD-Agent 跑 strategy/factor 实验需 Docker container, Windows 集成路径长 |
| Windows bug 多 | 微软自己的项目 Windows-side 反而 issue 集中 |
| 不支持 Claude | 主要 OpenAI/Anthropic Direct API, Claude API 路径不官方 |

决策: 走路线 C (借因子表达, 不迁框架), 自建 `DEV_AI_EVOLUTION V2.1` 4 Agent 闭环.

### 24 项目对标 (2026-04-26) 新发现

[QUANTMIND_LANDSCAPE_ANALYSIS_2026.md](../research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md) Part 6.4 主动反思:

1. **学术地位** (我们 16 个月前没充分评估的)
 - 微软 Qlib 团队 2024-04 发布, 截至 2026-04 已 13K⭐ / 1520 fork / pushed 4-22 (高活跃)
 - 论文: arxiv 2505.15155 *"R&D-Agent-Quant: Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization"* — 学术圈引用增长中
 - 跟 vnpy 4.0 / Qlib Alpha158 形成中国量化生态学术对标三角

2. **跟 DEV_AI_EVOLUTION V2.1 高度对位**
 - RD-Agent 4 Agent: Researcher / Coder / Eval / Reflector
 - QM V2.1 4 Agent: Researcher / Critic / Library_committer / Trader
 - 角色命名不同, **方法论同源**: hypothesis 生成 → 实现 → 验证 → 反馈

3. **NO-GO 阻断点 16 月后可能改变**
 - Docker on Windows: WSL2 + Docker Desktop 现已稳定 (vs 2026-04-10 时 WSL2 还有 GPU passthrough 问题)
 - Claude 支持: RD-Agent 已加 LiteLLM provider 抽象 (社区 PR), 可走 Claude API
 - Windows bug: 24 个月项目成熟度 + 1520 fork 社区压力

### 真实痛点: V2.1 设计 0% 实现

`docs/DEV_AI_EVOLUTION_V2.1.md` (705 行) 是详细设计, 但 **0% 实现** (CLAUDE.md 已记录). 自建 4 Agent 闭环工程量 12-16 周, 全栈自研.

如 RD-Agent 16 月后 NO-GO 阻断点可破, 可能省 8-12 周. 但 NO-GO 阻断点是否破需**实测**, 不能凭推测.

## Decision

### D1 — 不预设采用, 也不预设否决, 走 4 周时间盒评估

**本 ADR 是评估计划, 不是采用决策**. Wave 4 Observability 完结后 (~2026 Q3, Week 23-26 完结), 启动 4 周 RD-Agent 深度评估, 评估结果决议入新 ADR (暂记 ADR-014 `RD-Agent Adoption Decision`).

### D2 — 4 周评估清单

| 周 | 任务 | 验收 |
|---|---|---|
| W1 | 论文阅读 + RD-Agent 0.5+ codebase walk-through (`rdagent/` 目录 / Multi-Agent loop / hypothesis tracking) | 写 1 份 internal review (~3 页), 标 `docs/research/RD_AGENT_DEEP_DIVE.md` |
| W2 | Docker on Windows 11 + Claude API 集成 PoC | RD-Agent demo 跑通 1 个 toy factor mining loop, Claude API 调用成功 (无 OpenAI key) |
| W3 | RD-Agent 跟 QM 数据对接 PoC | 喂 QM `factor_values` + `factor_ic_history` 数据, RD-Agent 能产出 1 个有意义的 factor hypothesis |
| W4 | 跟 V2.1 自建对比矩阵 + ADR-014 决议 | 决议: (a) 采用 RD-Agent 全栈 / (b) 借鉴 RD-Agent 设计但自建 V2.1 (路线 C 升级) / (c) 维持 NO-GO |

### D3 — 评估期硬约束

- **不打乱 Wave 3-4 任何 MVP**: 评估在 Wave 4 完结后启动, 不并行
- **不动 PT 金**: 评估全部在 dev 环境 + 历史数据 sandbox
- **失败 fast-fail**: 任一周 critical fail (如 Docker 装不上) 直接终止评估, 走 (c) 维持 NO-GO
- **不引入 RD-Agent 依赖到 PT 链路**: 评估期间 PT 继续走 CORE3+dv_ttm 等权 + Risk Framework
- **License 隔离**: RD-Agent MIT 友好, 但若选 (a) 全栈采用, 必须保证 QM 主仓不污染 (如以 git submodule 或独立 conda env 隔离)

### D4 — 评估输入材料 (评估开始前准备)

- ✅ [QUANTMIND_LANDSCAPE_ANALYSIS_2026.md](../research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md) Part 3.2 RD-Agent 画像 (本文档已含)
- ✅ `docs/DEV_AI_EVOLUTION.md` V2.1 (705 行自建设计)
- ✅ `memory/project_research_nogo_revisit.md` (RD-Agent 阶段 0 NO-GO 历史)
- ⬜ arxiv 2505.15155 paper PDF (待下载)
- ⬜ RD-Agent latest stable release notes (待评估前 fetch)

## Consequences

### 好处

1. **学术对位明确**: 不再凭直觉自建 V2.1, 而是**先看微软怎么做**
2. **风险有界**: 4 周时间盒 + fast-fail 兜底, 最坏情况浪费 1 个月
3. **决策可追溯**: 评估结果入 ADR-014, 后续质疑有 evidence
4. **跟 vnpy 4.0 + Qlib Alpha158 学术三角对齐**: QM 在中国量化生态学术地位有声量

### 风险

1. **机会成本**: 4 周不能用于 Wave 5 / Wave 6 推进
2. **评估漂移**: 4 周可能不够覆盖 Multi-Agent loop + 数据对接 + Docker / Claude 集成完整 PoC. **mitigation**: D2 任务清单逐周 fast-fail, 不是周末再评.
3. **采用后维护成本**: 如选 (a) 全栈采用, RD-Agent upstream 升级追踪 + bug 修补需投入, 可能跟 Wave 4-5 节奏冲突
4. **路线撕裂**: 如选 (a) 全栈, V2.1 设计稿 705 行作废, 需重写为"基于 RD-Agent 的 QM 适配层"

### 中性

- 评估结果不论 (a)(b)(c), 都会产出 1 份 `RD_AGENT_DEEP_DIVE.md` (3 页) 入研究知识库
- (b) 借鉴自建 是最可能结果 — 既享 RD-Agent 学术对位, 又保 QM 主仓 governance 不被污染. 跟阶段 0 路线 C 一脉相承.

## Alternatives Considered

### A1 — 跳过 RD-Agent 完全自建 V2.1
**否决**: 阶段 0 NO-GO 是 16 月前的判断, 此后 RD-Agent 已 13K⭐ / 1520 fork. 不评估直接走 V2.1 是凭直觉, 违反铁律 21 (先搜开源再自建) 跟铁律 25 (验证 over assumption).

### A2 — 直接采用 RD-Agent (跳过评估)
**否决**: 阶段 0 阻断点 (Docker / Claude / Windows) 没消失证据. 凭学术地位采用风险高 (Phase 2.1 LightGBM 也是高声量但实测 NO-GO).

### A3 — 本 ADR 评估方案 (4 周时间盒)
**采用**: 风险有界 + 决策可追溯 + 跟 V2.1 设计稿对照, 是 ROI 最高路径.

### A4 — 等 RD-Agent v1.0 stable release
**否决**: 不知道何时 stable. 微软 RD-Agent 当前是 active 开发中, 等 stable 是无限推迟.

## Migration Schedule

| 阶段 | 时间 | 内容 |
|---|---|---|
| Wave 4 完结 | ~2026 Q3 中 (Week 26 末) | 前置 Observability + Backup & DR 就绪, 评估 sandbox 不动 PT |
| 评估 W1-W4 | Week 27-30 | 论文 + Docker/Claude PoC + 数据对接 + 决议 |
| ADR-014 决议 | Week 30 末 | 决议 (a)(b)(c) 三选一, 入 ADR |
| 实施 (若 a 或 b) | Week 31+ | 按决议路线推进, 可能跟 Wave 5 UI 并行 |

⚠️ **跟 ADR-012 Wave 5 UI 启动时机重叠**. 本 ADR 评估 vs Wave 5 UI 实施二选一并行, 不强制. **建议**: Wave 5 UI MVP 5.1 (PT 状态面板) 优先于本评估, 因 UI 是操作刚需, 评估是研究投入.

## Validation

评估完成必须产出:

- [ ] `docs/research/RD_AGENT_DEEP_DIVE.md` (3 页 internal review)
- [ ] `docs/adr/ADR-014-rd-agent-adoption-decision.md` (a/b/c 决议)
- [ ] (若 b 或 c) `memory/project_research_nogo_revisit.md` 更新 RD-Agent 重评估结论
- [ ] (若 a) `docs/DEV_AI_EVOLUTION.md` V2.1 → V2.2 重写 (基于 RD-Agent 适配)
- [ ] (若 b) V2.1 设计稿补 "借鉴 RD-Agent 设计要点" 章节
- [ ] PoC 代码 + 测试不进 main, 留 `experimental/rd_agent_poc/` (评估失败可一键删)

## References

- [docs/research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md](../research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md) Part 3.2 + Part 6.4 (RD-Agent 主动反思)
- [memory/project_research_nogo_revisit.md](../../memory/project_research_nogo_revisit.md) (阶段 0 NO-GO 历史)
- [docs/DEV_AI_EVOLUTION.md](../DEV_AI_EVOLUTION.md) V2.1 (705 行自建设计, 0% 实现)
- arxiv 2505.15155 (RD-Agent-Quant paper, 待下载)
- 铁律 21 (先搜开源再自建) / 铁律 25 (验证 over assumption) / 铁律 38 (Blueprint 长期记忆)
