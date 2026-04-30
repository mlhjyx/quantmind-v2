# QuantMind V2 全方位系统审查 — Framework + CC 操作 Prompt

**Audit ID**: SYSTEM_AUDIT_2026_05
**Date**: 2026-05-01
**Type**: 一次性全方位系统审查 (read-only, 0 修改, 0 Phase 拆分, 0 时长限制)
**Goal**: 报告 — 系统现状 + 存在问题
**Status**: Framework 定稿, 待 CC 启动

---

## 文档导航

- [§0 审查目的 + 边界 (反 Claude 4 次错读)](#§0-审查目的--边界)
- [§1 审查方法论](#§1-审查方法论)
- [§2 现状快照 (What is) — 14 类清单](#§2-现状快照-what-is--14-类清单)
- [§3 Review Audit (Is it good) — 13 领域 × 8 方法论](#§3-review-audit-is-it-good--13-领域--8-方法论)
- [§4 端到端 + 独立性 (4 项跨领域)](#§4-端到端--独立性-4-项跨领域)
- [§5 Adversarial Review (推翻假设)](#§5-adversarial-review-推翻假设)
- [§6 输出形态 + 文件组织](#§6-输出形态--文件组织)
- [§7 反 CC 偷懒机制](#§7-反-cc-偷懒机制)
- [§8 不变项 + 硬边界](#§8-不变项--硬边界)
- [§9 关联](#§9-关联)
- [§10 CC 操作 Prompt](#§10-cc-操作-prompt)

---

## §0 审查目的 + 边界 (反 Claude 4 次错读)

### §0.1 User 4 次反问 + Claude 4 次错读 (sprint period 沉淀)

| User 反问 | Claude 错 | 真意 |
|---|---|---|
| D72 "为什么不一次性? 而要遗留?" | 推 D 选项 | 反 sprint period treadmill |
| D74 "你不生成总文档吗?" | 走 PR design doc | 真意是探讨 |
| D76 "我之前给你说的风控怎么设计?" | 推翻 user 4-29 决议 | 探讨延续 |
| D77 "整个项目系统审查, 不固定 Wave 1-4" | 用 known-knowns 列 22 维度 | 0 凭空假设 |
| D78 (本次) "一次性审完所有, 不分 Phase, 不设时长" | (我现在响应) | **一次性 + 报告 + 0 修改** |

### §0.2 真审查目的

**报告 — 系统现状 + 存在问题**. 不是修复. 不是 daily audit. 不是分 Phase 推进.

User 想要:
- 一次性了解整个系统真状况
- 找到所有现存问题
- 0 修改 / 0 干预
- 不限制 CC 时长 (CC 自己决议跑多久)

### §0.3 反 Claude 4 次错读守门

本 framework + prompt 严格反我之前 4 次错:
- ❌ 不拆 Phase (一次性)
- ❌ 不设时长 (CC 决议)
- ❌ 不 user review checkpoint 中段 (一次性 push)
- ❌ 不 forward-progress offer "Phase 2"
- ❌ 不固定 Wave 1-4 / 12 framework / 5+1 风控 等 known-knowns
- ❌ 不假设 audit md 数 / 行数 / 维度数 (CC 实测决议)

---

## §1 审查方法论

### §1.1 真 Framework (5 维度 × 8 方法 × 13 领域)

不再 enumerate 22 维度 (那是 Claude 拼凑). 用 matrix:

#### 5 维度 (系统视角)

| 维度 | 关心 | Stakeholder |
|---|---|---|
| **架构师视角** | 系统设计 / 跨模块边界 / 长期演进 | Claude.ai 战略 + user |
| **实施层视角** | 代码质量 / 接口契约 / sustained vs drift | CC + 代码审查 |
| **测试 / QA 视角** | 测试覆盖 / 质量 gate / regression 防复发 | CC + 历史 LL |
| **运维 / SRE 视角** | 服务健康 / 故障恢复 / SLA / 监控 | Servy + 真账户 ground truth |
| **业务 / 用户视角** | 工作流 / 决策权 / 痛点 vs 设计 | user 4-29 痛点 |

#### 8 方法论 (行业标准)

| 方法论 | 标准 | 适用 |
|---|---|---|
| **ATAM** (Architecture Tradeoff Analysis Method) | 架构 quality attribute 权衡 | 架构 + V3 风控 + 跨 framework 集成 |
| **SAAM** (Software Architecture Analysis Method) | 架构 vs scenario 适配 | 4-29 痛点 vs 设计 gap |
| **SAST + SCA** (Static Analysis + Software Composition Analysis) | 代码静态 + 依赖漏洞 | backend / frontend / scripts |
| **数据质量 6 维度** (Accuracy / Completeness / Consistency / Timeliness / Uniqueness / Validity) | DB 多表 + cache | DataPipeline + 因子库 + 第三方源 |
| **测试金字塔 + Mutation Testing** | coverage 不只 line, 真 fault detection | pytest baseline + 历史 regression |
| **SRE PRR** (Production Readiness Review) | 服务上线前 N 项 checklist | Servy + Celery Beat + 风控接入前置 |
| **STRIDE Threat Modeling** | Spoofing/Tampering/Repudiation/Info disclosure/DoS/Elevation | 真金边界 + .env + 第三方 webhook |
| **APM + 性能 profiling** | 真延迟 / 真吞吐 / OOM 复盘 | 32GB RAM + factor / backtest / 实时 |

#### 13 领域 (项目领域)

CC 实测决议每领域 scope (不假设 sub-section 数):

1. **架构** — Wave / framework / 5+1 风控 / 6 块基石 — 全部可质疑
2. **代码** — backend / frontend / scripts / engines — 静态 + 动态
3. **数据** — 全 DB schema + Parquet + 第三方源 + 数据契约
4. **因子** — 因子谱系 + 拥挤度 + 归因 + 治理 + 方法论
5. **回测** — 引擎正确性 + 可复现 + 性能 + 与生产一致性 + 历史 bug 防复发
6. **风控** — V2 现状 + V3 设计 gap + 4-29 root cause
7. **测试** — coverage 真实测 + 测试金字塔 + flakiness + regression 保护
8. **运维** — Servy + 调度 + DR + Observability + runbook
9. **安全** — 真金边界 + secrets + STRIDE + supply chain
10. **性能** — Memory / latency / throughput / 资源争用
11. **业务 / 用户** — 工作流 + 经济性 + 决策权 + 4-29 真根因 5 Why
12. **外部视角** — 行业对标 + 学术 methodology + 投资人 ROI + 第三方
13. **治理** — 6 块基石 真治理 vs over-engineering + D 决议链 + 跨文档漂移 + 协作效率

**[CC 主动扩展守门]** ⚠️

13 领域是 **Claude 起点 reference, 不是闭集**. CC 必须主动思考:

- 这 13 领域有没有重要领域漏了? (Claude 想不到的, 但项目真存在的)
- 候选未列领域 (CC 实测决议是否纳入): 数据科学方法论 (统计验证 / sample size / multiple testing) / 量化研究 reproducibility / model risk management / 客户/资金合规 (即使个人项目, 资金来源审视) / 业务连续性 (灾备 + 单点失败) / knowledge management (跨 session continuity) / vendor lock-in (Tushare/QMT/DingTalk 替换难度) / 法律 (数据使用合规 / 第三方 API ToS) / 项目可持续性 (user 退出后 N 月项目能维护吗) / 等等
- 其他 CC 实测发现的领域

**0 主动扩 = 偷懒** (沿用 §7 反偷懒守门). CC 写 audit 前必 cite "thinking through what dimensions this project ACTUALLY needs, beyond Claude's 13 list".

CC 输出 `governance/01_framework_dimension_audit.md` (CC 决议路径) 沉淀: 13 领域是否真合理 + 漏领域清单 + 多领域候选 + 推荐扩 vs 不扩 + 论据.

### §1.2 现状快照 vs Review Audit 双视角

CC 对每领域走两遍:

| 维度 | 输出 |
|---|---|
| **现状快照 (What is)** | 描述性 + 量化 + 全清单 (适合 onboarding / 数据驱动) |
| **Review Audit (Is it good)** | 评判性 + red/yellow/green + 修复建议 (但不实施) |

### §1.3 端到端 + 独立性审查 (跨领域 cross-validate)

除分领域审, 必须跨领域 cross-validate (§4 详).

---

## §2 现状快照 (What is) — 14 类清单

CC 实测全清单, 0 假设 sustained sustained:

### §2.1 Repo 清单
- 全 repo 文件树 (backend / frontend / scripts / engines / configs / docs / cache / tests / .claude / 等)
- 文件数 + 行数 + 文件类型分布 + 真 last-modified
- git log 演进史 (近 30/60/90/180/365 day 提交活跃度 by 文件)
- git blame 高频改动文件 = 设计反复 candidate
- git log 沉默地带 (>30 day 0 commit 但 production 关键文件) = 隐藏债 candidate

### §2.2 DB 清单
- 全 schema / 表 / column 真清单 (含 deprecated / 死表 candidate)
- 每表真行数 + 真 size + hypertable 配置 + chunks 数 + retention 策略 + compression
- 索引清单 + 慢查询 candidate (pg_stat_statements 实测)
- 跨表 FK / JOIN 关系真图
- 真最后 INSERT/SELECT timestamp by 表 (识别死表)

### §2.3 服务 + 调度清单
- Servy 全服务真状态 + 真 uptime + restart history
- Celery Beat 真 schedule entries (实测, 不沿用 memory)
- Celery worker pool / queue 配置 + 真负载
- Windows Task Scheduler 全 schtask 真状态 (Last Run + Result + Disabled?)
- 跨调度边界 + 失败传播 path

### §2.4 配置清单
- 全 `.env` 字段实测 (config_guard 真校验)
- 全 `configs/*.yaml` 字段
- Servy services config
- 谁读取每字段 (grep) + 失效会怎样
- 死字段 candidate

### §2.5 API + WebSocket 清单
- 全 `/api/*` endpoint 真清单 (FastAPI router scan)
- 全 `/ws/*` channel 真清单
- 调用方实测 (frontend grep + scripts grep + 第三方)
- deprecated / 死 endpoint candidate

### §2.6 依赖清单
- pip list (全 Python 依赖 + 版本)
- npm list (全 JS 依赖)
- requirements.txt vs pip 实测 drift
- pip-audit 漏洞扫描
- npm audit 漏洞扫描
- 第三方系统依赖 (PG / Redis / Servy / xtquant / TimescaleDB / 等版本)

### §2.7 因子清单
- factor_values 真因子清单 (DISTINCT factor_id 真 query)
- factor_ic_history 真 IC 入库清单 (factor_id × time 矩阵)
- FACTOR_TEST_REGISTRY.md 沉淀 vs 真实测 drift
- 真 active / warning / deprecated / invalidated 分布

### §2.8 数据流清单
- 端到端真路径: Tushare/AKShare/QMT/Baostock → DataPipeline → DB → Parquet cache → 各消费者
- 每一跳真 dropoff
- Redis Streams 真 alive 数 (沿用 F-D3B-6 假 alive 教训)
- 跨数据流 publish/subscribe map

### §2.9 测试清单
- 全 pytest 真清单 (按文件 / 类 / 函数, 真 last-run + pass/fail/skip)
- pytest config drift
- coverage 真实测 (line / branch / mutation 三维度)
- contract / smoke / integration / E2E 各层真覆盖
- skip 集合 (沿用 24 fail baseline 真分类)

### §2.10 文档清单
- 全 `*.md` 真清单 (CLAUDE / IRONLAWS / LESSONS_LEARNED / SYSTEM_STATUS / FACTOR_TEST_REGISTRY / docs/* / .claude/ / 等)
- 每文档行数 + 真 last-update
- 引用真 graph (跨文档 link)
- stale candidate (>30 day 0 update 但 sprint period 关键)

### §2.11 业务状态清单
- 真账户 ground truth (positions / cash / market_value, xtquant 真 query)
- cb_state.live 全字段
- position_snapshot live 真行
- risk_event_log 真行 + 时间分布
- portfolio NAV 历史 (近 30/90/180 day)
- PT 暂停后真状态 sustained (4-29 vs 当前)

### §2.12 ADR + LL + Tier 0 清单
- 全 ADR 真清单 — 实测沉淀 vs sprint period 声明
- 全 LL 真覆盖度 (有些 LL 写了但代码层未 enforce)
- TIER0_REGISTRY 真 closed/待修分布
- 候选铁律 X1/X3/X4/X5/X11 真 promote 状态

### §2.13 协作历史清单
- D 决议链 (D1 ~ D78) 真覆盖 + 跨 session 一致性
- Sprint period PR 链真 merge 时间 + 改动文件分布
- session 跨日 handoff 真有效度
- Claude.ai + CC + memory 协作模式真效率

### §2.14 LLM cost + 资源清单
- LLM call cost 真累计
- DB / Redis / Parquet / GPU 真资源占用
- 32GB RAM 真分布 (各服务 + buffer)
- 跨服务资源争用 detection

### §2.X CC 主动扩展守门 ⚠️

14 类清单是 **Claude 起点 reference, 不是闭集**. CC 必须主动思考:

- 真状态描述 14 类够吗? (Claude 没列但项目存在的清单)
- 候选未列清单 (CC 决议): 真账户对账历史 (broker 报告 vs cb_state 一致性) / 历史 alert 真触发统计 / 历史 PT 重启次数 + 失败原因 / 历史 GPU 利用率 (cu128 真用过吗) / 历史 OOM 事件 + 修复 / 历史误操作 (commit revert / 数据误删 / 等) / 用户输入历史 (user prompt 给 CC 的统计 + 反复反问 pattern) / 跨 session memory drift (Anthropic memory 历史 vs 真状态) / 实时 system call 频率 / shell history 真使用 pattern / 等等

**0 主动扩 = 偷懒**. CC 必 cite "thinking through what additional state inventories this project should have".

CC 输出 `snapshot/00_inventory_completeness_audit.md` 沉淀: 14 类是否真完整 + 漏清单候选 + 推荐扩 vs 不扩 + 论据.

---

## §3 Review Audit (Is it good) — 13 领域 × 8 方法论

CC 实测决议每领域走哪些方法论. 推荐 cells:

### §3.1 架构领域 (ATAM + SAAM)

- ATAM: 5+1 风控架构 / V3 设计 / 6 块基石 / Wave 1-4 / 12 framework — quality attribute 权衡
- SAAM: 4-29 痛点 scenario 跑过架构 — 现架构能 detect/prevent 4-29 类事件吗?
- 跨模块边界 contract (DataPipeline + SignalComposer + RiskEngine + BacktestEngine 4 接口)
- Long-term 演进路径 (V3 vs 推翻重做)

### §3.2 代码领域 (SAST + SCA)

- ruff / mypy / 圈复杂度 全 repo 实测
- 死码 / 死 import / 跨层违规 (Engine 层不读 DB 等铁律 31 enforce 度)
- pip-audit + npm audit 漏洞
- 跨 backend / frontend / scripts / engines / configs 全审

### §3.3 数据领域 (6 维度)

按数据质量 6 维度审 (Accuracy / Completeness / Consistency / Timeliness / Uniqueness / Validity):
- 每维度选样本表跑 (CC 决议样本 + 抽样依据必 cite)
- 跨表 join 一致性
- 第三方源 (Tushare 复权 / QMT / Baostock) 真值 verify
- DataContract vs 实测 schema drift
- Parquet cache 失效策略 enforce 度

### §3.4 因子领域

- 因子谱系图 (alpha decay over time, 单因子半衰期分析)
- 因子相关性矩阵稳定性 (regime change 下 corr 漂移)
- 因子拥挤度 (vs 学术因子 + vs 公开量化基金风格)
- 因子归因 (PnL 来自哪些因子真信号 vs noise)
- 因子治理 SOP enforce 率 (生命周期 / 验证 / 退役)
- 因子方法论审 (NO-GO 论据完整性 + false NO-GO candidate)

### §3.5 回测领域

- numerical correctness (双精度 / 复权 / 涨跌停 / 停牌 / ST)
- point-in-time correctness (look-ahead bias detection)
- 性能 + scaling (12yr × N 因子 × M 配置)
- 与生产路径一致性 (同 SignalComposer / 同成本模型 / 同 universe)
- 历史 bug 防复发 (mf_divergence / Tushare 复权 / RSQR NaN — regression test 覆盖)

### §3.6 风控领域

- V2 现状 (ADR-010 PMSRule + MVP 3.1b) 实施层真 enforce 度
- 4-29 真 root cause (5 Why) — 不止 "5min Beat 太慢", 深挖
- V3 设计 gap (Claude V3 设计文档 vs 现状真接入点)
- 决策权边界审 (现 0 自动 vs 设计 STAGED 是否合理)

### §3.7 测试领域

- coverage 三维度真实测 (line / branch / mutation)
- 测试金字塔比例 (unit 多 vs E2E 少 — 真分布)
- flakiness audit (24 fail baseline 真分类)
- regression protection 历史 bug 覆盖度

### §3.8 运维领域 (SRE PRR)

- Servy 4 服务 PRR checklist
- 调度跨边界 (schtask + Celery Beat) 健康
- SOP_DR 真可执行度 (灾备演练有跑过吗)
- Wave 4 MVP 4.1 Observability 真覆盖度 vs 设计声明
- runbook cc_automation 真覆盖度

### §3.9 安全领域 (STRIDE)

- 真金边界 (LIVE_TRADING_DISABLED + DINGTALK 双锁) STRIDE 全维度审
- secrets management (.env + DPAPI + git history secret leak)
- 第三方 webhook 安全 (DingTalk 反向决策权 + 签名)
- xtquant 唯一入口 + broker_qmt sell only enforce
- supply chain 第三方依赖风险

### §3.10 性能领域 (APM)

- Memory profiling (32GB RAM 真占用 + OOM 教训复盘)
- Latency critical paths (factor_engine + backtest + L1 实时)
- Throughput (Tushare API + DB write + Parquet 读)
- 资源争用 (并发约束 + Servy 资源分配)

### §3.11 业务 / 用户领域

- user 真日常工作流 vs 设计假设 (审查 4-29 真 use case)
- 经济性 (alpha vs cost / user 时间投入 vs 产出)
- 决策权 audit (自动 / 半自动 / 手工 决策点 + panic SOP)
- 4-29 root cause 5 Why (深挖)

### §3.12 外部视角领域

- 行业对标 (vs Qlib / RD-Agent / 公开量化基金披露)
- 学术 methodology (因子方法论 vs Gu Kelly Xiu 2020 / Harvey Liu Zhu 2016)
- 投资人 ROI 视角
- 新人 onboarding 难度 + 知识可持续性
- 跨 LLM session continuity (新 Claude session 走 audit doc 能 onboard 吗)

### §3.13 治理领域 (Claude 自审, 关键)

- 6 块基石真治理 alpha vs audit overhead (ROI 评估)
- ADR-022 反 anti-pattern enforcement 真有效?
- D 决议链 (D1-D78) 跨 session 一致性 + 矛盾 candidate
- 跨文档 fact 漂移真扫描
- Claude.ai + CC + memory 协作真效率
- sprint period 22 PR 链 ROI vs cost
- "凭空 enumerate" anti-pattern 复发 (Claude 写文档凭空假设)
- Claude 4 次错读 user 反问 — 是 Claude prompt 设计问题还是协作模式问题?

---

## §4 端到端 + 独立性 (4 项跨领域)

### §4.1 端到端真路径 audit

跑过完整业务路径 4 条:
1. **数据 → 因子 → 信号 → 回测**: Tushare 拉 → DataPipeline → factor_values → SignalComposer → run_backtest → 真 baseline
2. **数据 → 因子 → 信号 → PT**: 同上换 PT 真账户
3. **PT → 风控 → broker_qmt → 真账户**: 现 V2 风控真 enforce path
4. **告警 → user → 决策 → 执行**: DingTalk push → user reply → broker_qmt sell

每路径**实测真路径** (vs 设计声明), 找 gap / 断点 / silent fail.

### §4.2 独立性 audit (模块解耦度)

每模块审是否真独立:
- DataPipeline 失效 → 多少下游死?
- SignalComposer 失效 → 多少死?
- BacktestEngine 失效 → 多少死?
- RiskEngine 失效 → 多少死?
- broker_qmt 失效 → 多少死?
- DingTalk 失效 → 多少死?
- LiteLLM (待接入) 失效 → 多少死?

实测 import graph + 调用链, 不只看声明.

### §4.3 跨领域漂移 audit

同 fact 在多领域描述是否一致:
- 因子数 (CLAUDE.md / FACTOR_TEST_REGISTRY / DB 实测 / docs/ 跨多文档)
- Tier 0 数 (PROJECT_FULL_AUDIT / TIER0_REGISTRY / SHUTDOWN_NOTICE / handoff 跨多源)
- 测试 baseline (CLAUDE.md / SYSTEM_STATUS / pytest 实测)
- LL 数 (LESSONS_LEARNED / IRONLAWS §23 / sprint period 累计)

**沿用 sprint period broader 47 真实证**: 跨文档漂移高发, 实测扩 broader 50+ candidate.

### §4.4 时间维度 audit

每领域走 3 时维度:
- **历史**: git log + STATUS_REPORT 演进 + 历史 bug 沉淀
- **当前**: §2 现状快照 + §3 review
- **未来**: 路线图 + V3 设计 + Wave 5+ + PT 重启 prerequisite

时间 cross-check: 历史 bug 是否 regression 防复发? 当前状态是否 align 路线图? 未来路径是否依赖未 verify 的当前假设?

---

## §5 Adversarial Review (推翻假设)

User D77 显式开放 adversarial. CC 必须主动:

### §5.1 推翻 Claude 假设

CC 实测推翻 Claude 假设, 沉淀清单. Claude 沉淀但**必须质疑**的:

- Wave 1-4 + 12 framework + 6 升维完成度声明
- 5+1 层风控架构 (4-29 决议)
- 6 块基石治理胜利
- TIER0_REGISTRY 18 项分类
- ADR-021 / ADR-022 反 anti-pattern enforcement
- 9+ NO-GO 沉淀完整性
- CORE3+dv_ttm WF PASS sustained
- SignalComposer / DataPipeline / RiskEngine 真覆盖度
- Servy 4 服务 ALL Running 真状态
- regression_test max_diff=0 sustained
- 12 framework / 22 PR 链 / 6 块基石 — **全部可质疑**

### §5.2 推翻 user 假设

User 显式开放. CC 主动 flag user 假设错:
- 4-29 痛点真根因 (user 假设 "盘中盯盘 + 风控未设计", 真根因可能更深)
- PT 重启信心来源 (user 假设 "Tier A 完成 + paper-mode 5d → 重启", 真信心可能要更多)
- 经济性假设 (user 时间投入 vs 项目产出)
- 工作流假设 (Claude.ai + CC 协作真有效)

### §5.3 推翻共同假设

最深盲点. Claude+user 共同假设但都没意识到错的事:
- "项目按 Wave 推进是最佳" — vs 推翻重做 / 简化
- "sprint period 治理 6 块基石是 governance 胜利" — vs over-engineering
- "因子研究 + 风控 + 回测 三领域都需要 V3 升级" — vs 仅风控 / 仅因子 / 不升级
- "memory + repo + Claude.ai + CC 4 源协作有效" — vs 协作冗余 + 漂移

### §5.4 Unknown Unknowns

Claude+user 都没意识到的事. 按 Rumsfeld 定义不可 enumerate, 但 CC 实测可能发现.

### §5.5 推翻 framework 自身 (新加, 沿用"主动思考"守门) ⚠️

CC 必须**主动质疑本 framework 自身**:

- 5 维度 (架构师 / 实施层 / QA / SRE / 业务用户) 是否真合理? CC 实测如多余 / 漏, 反驳
- 8 方法论 (ATAM / SAAM / SAST / 数据 6 维 / 测试金字塔 / SRE PRR / STRIDE / APM) 是否真适合? 是否漏 (e.g. 量化研究 reproducibility / model risk / etc)
- 13 领域 + 14 类清单 + 4 端到端 + 4 adversarial — 本 framework 整体 matrix 真合理?
- 双视角 (现状快照 + Review audit) 真足够? 是否漏视角 (e.g. 演进趋势 / 比较 audit / 经济性 audit / 信任 audit / etc)
- "0 修改" 边界是否过窄? (D78 沿用, 但 CC 实测如发现 P0 风险必须立即修, 反驳)
- "一次性审完" 是否物理可行? (CC 实测如 scope 远超物理边界 → 反驳, 推翻 D78 假设)

CC 输出 `blind_spots/05_framework_self_audit.md` 沉淀:
- framework 是否真合理
- 推翻 framework 自身候选清单
- 推荐 framework 修订 (Phase 2+ 候选, **本审查不实施**)

**反驳成立 → STOP** (沿用 §7.6).

### §5.6 CC 主动思考扩 scope (新加) ⚠️

CC 在审查中**任何时刻**发现 framework 漏 audit 维度, 必:
1. cite 漏的维度 + 论据 (为什么重要)
2. 决议是否本审查纳入 (vs 留 Phase 2+)
3. 沉淀到 `blind_spots/05_framework_self_audit.md`

**0 主动思考 = 严重 anti-pattern** — 沿用 user D78 sprint period 累计教训, Claude 已 4 次错读, CC 不能依赖 framework 闭集.

---

## §6 输出形态 + 文件组织

### §6.1 CC 自建文件夹

```
docs/audit/2026_05_audit/
├── README.md                          (audit 总入口 + TOC)
├── EXECUTIVE_SUMMARY.md               (顶层 user 1h 可读完整)
├── snapshot/                          (§2 现状快照, ~14 md, CC 决议)
├── architecture/
├── code/
├── data/
├── factors/
├── backtest/
├── risk/
├── testing/
├── operations/
├── security/
├── performance/
├── business/
├── external/
├── governance/
├── end_to_end/                        (§4.1 端到端真路径)
├── independence/                      (§4.2 独立性)
├── cross_validation/                  (§4.3 跨领域漂移)
├── temporal/                          (§4.4 时间维度)
├── blind_spots/                       (§5 adversarial 4 类)
└── PRIORITY_MATRIX.md                 (问题优先级)
```

### §6.2 CC 决议每领域 sub-md 数

CC 实测决议每领域拆几个 sub-md (不假设固定数).

每 sub-md 含:
- 实测证据 (grep / SQL / 代码 cite)
- 发现 (red / yellow / green)
- 问题描述 (不含修复建议, 沿用 D78 user 要求 0 修改)
- 优先级 (P0/P1/P2/P3)
- 关联 (其他 audit md cross-link)

### §6.3 EXECUTIVE_SUMMARY.md 形态

User 1h 可读完整. 含:
- 项目真健康度 (1 页)
- Top 10 P0 问题 (1 页)
- 推翻 Claude/user/共同假设 Top 10 (1 页)
- 战略候选 (修复 vs 推翻重做 vs 维持) — 仅候选, **不决议**
- 所有 audit md 索引 + 阅读顺序

---

## §7 反 CC 偷懒机制

User D77/D78 显式: "防止 CC 偷懒". 沿用 sprint period broader 47 累计教训:

### §7.1 实测证据强制

每发现必 cite source:
- grep 命中行号
- SQL query + 真 result
- 代码 file:line
- git log commit hash
- 真账户 / DB 真值

无 source 引用的发现 = STOP, CC 重审.

### §7.2 反"沿用" anti-pattern

CC 默认行为 = 沿用 Claude memory + sprint period sustained. 本审查反此默认:
- "沿用 X" 必须 verify
- "假设 X" 必须实测推翻或 confirm
- "Claude 文档写 X" 必须 grep 真存

### §7.3 反"理论 cover" anti-pattern

沿用 Step 6.3a §3.2 教训. 本审查:
- "理论上正确" = 0 接受
- 必须 demonstrate (跑代码 / SQL / 历史回放)

### §7.4 反"抽样" anti-pattern

CC 倾向抽样. 反此:
- 现状快照必须**全清单** (不漏表)
- Review audit 可抽样, 但抽样依据必 cite

### §7.5 反"早退" anti-pattern

CC 可能因 context 长度 / fatigue 早退. 反此:
- 跑完所有 13 领域才能写 EXECUTIVE_SUMMARY
- 任何领域跳过必 cite 原因 + STOP 反问 user

### §7.6 STOP 触发

任一以下 CC STOP 反问:
- 发现某领域审到一半发现 scope 远超估值
- 发现 Claude 假设错 P0
- 发现 user 假设错 P0
- 发现真金风险 (e.g. LIVE_TRADING_DISABLED 实测 = false)
- 发现共同盲点 P0
- 任何领域跳过 (CC 必须 cite 原因)

### §7.7 LL-098 第 13 次 stress test

末尾 0 forward-progress offer (本 audit 末尾 + 每 STOP 反问末尾).

### §7.8 第 19 条铁律第 9 次 verify

prompt 0 具体数字假设 (audit md 数 / 行数 / 维度数 / 抽样数 全 CC 实测决议).

### §7.9 反"被动 follow framework" anti-pattern (新加, 关键) ⚠️

CC 默认行为 = 被动 follow Claude framework (5 维度 / 8 方法 / 13 领域 / 14 类). 本审查反此默认:

- CC 必**主动思考** framework 自身漏什么 (沿用 §1.1 / §2.X / §5.5 / §5.6)
- "follow Claude 13 领域审完" = **不够** — 必 cite "thinking through what dimensions/inventories project ACTUALLY needs beyond Claude's list"
- 写 audit 前 CC 必先沉淀 `blind_spots/05_framework_self_audit.md` (reflect framework 自身)
- 写 audit 中 CC 任何发现新维度立即追加 (vs 闭门 follow)
- 写 audit 后 CC 必 review 是否漏审 (vs 末尾草草收尾)

**违反 §7.9** = 严重偷懒, STOP 触发. 沿用 user D78 + Claude 4 次错读教训 — Claude 已证明 framework 是 known-knowns bias, CC 不能依赖.

---

## §8 不变项 + 硬边界

### §8.1 真金保护 (sustained)

- LIVE_TRADING_DISABLED=true sustained
- DINGTALK_ALERTS_ENABLED=false sustained
- EXECUTION_MODE=paper sustained
- PT 期间持续暂停 (4-29 决议 sustained)
- 真账户 ground truth read-only

### §8.2 read-only 边界

✅ 允许:
- grep / glob / find / read 任何 docs/ + 业务代码 read-only
- git log / git blame / git show
- python -c read-only
- pytest --collect-only (不跑) + 真 last-run timestamp
- SQL SELECT (read-only)
- pip-audit / npm audit / ruff / mypy (read-only static)
- web search (限定行业对标 / 学术 / Tushare/LiteLLM 等技术对标)
- 创建新文件 (在 audit 文件夹内) + commit + push + PR + AI self-merge

❌ 禁止 (硬边界):
- 改任何业务代码 (backend/ scripts/ engines/ frontend/)
- 改 .env / configs/
- 改任何已有 md / ADR / STATUS_REPORT / 等
- 跑任何 INSERT / UPDATE / DELETE / TRUNCATE / DROP SQL
- 重启 Servy / 触发 schtask / Beat
- 实施任何修复 (沿用 D78 user 要求 0 修改)
- 末尾 forward-progress offer
- "留 Phase 6+" / "建议下一步" 滥用

### §8.3 反 anti-pattern 守门

- 0 创建新 IRONLAWS §22 audit log entry
- 0 "留下次" 滥用
- 0 凭空削减 user 决议
- 0 sprint period treadmill 复发

---

## §9 关联

- **关联 ADR**: ADR-021 (IRONLAWS v3) sustained, ADR-022 (sprint period treadmill 反 anti-pattern) sustained
- **关联 PR**: 沿用 PR #172-#181 (sprint period 6 块基石建立)
- **本审查 PR**: 单 PR (audit doc 集中, CC 决议) — sustained 沿用 LOW 模式 (跳 reviewer + AI self-merge)
- **后续**: user review audit → user/Claude 战略对话 → 决议修复 vs 推翻重做 vs 维持

---

## §11 文档元数据

**版本**: 2.0 (反 Claude 4 次错读修订, 一次性审完 + 0 时长 + 0 修改)
**Date**: 2026-05-01

**反 anti-pattern verify**:
- ✅ 0 创建 IRONLAWS §22 entry
- ✅ enumerate 全 scope (现状 + review + 端到端 + 独立性 + adversarial)
- ✅ 0 凭空削减 user 4 次反问决议
- ✅ 0 拆 Phase (一次性审完, sustained D78)
- ✅ 0 时长限制 (CC 实测决议)
- ✅ 0 修改 (仅 audit doc, sustained D78)
- ✅ 沿用 ADR-022 集中机制

**LL-098 第 13 次 stress test**: 末尾 0 forward-progress offer.
**第 19 条铁律第 9 次 verify**: 0 具体数字假设.

**文档结束**.
