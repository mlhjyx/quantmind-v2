# Governance Review — CLAUDE.md 极高 churn 真测 + 5 Why

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 4 / governance/04
**Date**: 2026-05-01
**Type**: 评判性 + git log 30 day hotspot 真测 + 5 Why 推翻 sprint period sustained "ADR-022 反数字漂移" 治理假设

---

## §1 git 30 day hotspot 真测 (CC 5-01 实测)

实测命令:
```bash
git log --since="30 days ago" --pretty=format: --name-only | sort | uniq -c | sort -rn | head -15
```

**真值**:

| commits | 文件 |
|---|---|
| **103** | **CLAUDE.md** |
| 34 | LESSONS_LEARNED.md |
| 26 | cache/baseline/regression_result_5yr.json |
| 26 | SYSTEM_STATUS.md |
| 25 | scripts/run_paper_trading.py |
| 21 | scripts/setup_task_scheduler.ps1 |
| 21 | docs/QUANTMIND_PLATFORM_BLUEPRINT.md (QPB) |
| 19 | docs/audit/AUDIT_MASTER_INDEX.md |
| 18 | backend/app/tasks/daily_pipeline.py |
| 16 | backend/engines/backtest_engine.py |
| 15 | backend/engines/signal_engine.py |

---

## §2 🔴 CLAUDE.md 103 commits 30 day 真测 — 重大

**真值**: **CLAUDE.md = 103 commits in 30 day** (~3.4 commits/day)

### 2.1 sprint period sustained sustained "CLAUDE.md 重构 813→509 行" 假设 部分推翻

sprint state Session 46 末沉淀: "Step 6.3b PR #179 CLAUDE.md 813→509 行 重构".

**真测验证**: ✅ 重构 1 次 + ⚠️ 后续 30 day 102 次 update (重构后 churn sustained 沉淀)

**真根因**: CLAUDE.md = sprint period sustained 22 PR 治理 sprint period 主战场 (governance/01 §3 F-D78-19 P0 治理)

### 2.2 5 Why 推到底

**Why 1**: CLAUDE.md 103 commits/30 day = 极高 churn?
- ✅ 真. 治理 sprint period 真核心.

**Why 2**: 为什么 CLAUDE.md 是治理 sprint period 主战场?
- CLAUDE.md = 项目入口 / Claude Code 启动自动读
- 沿用铁律 22 sustained "文档跟随代码" — 任何代码改 → CLAUDE.md 同步候选
- 沿用 ADR-021 sustained "CLAUDE.md banner + 铁律段 reference 化" — sprint period 大改

**Why 3**: 为什么文档跟随代码 sustained 触发 N+ commits?
- 4 源协作 N×N 漂移 (F-D78-26 P0 治理) → CLAUDE.md 是 4 源之一, sustained 同步压力
- ADR-022 反"数字漂移高发" sustained sustained 但 enforcement 失败 (F-D78-16 ex-post 沉淀 ex-ante 0)

**Why 4**: 为什么 ADR-022 ex-ante prevention 缺?
- ADR-022 是 sprint period 6.4 G1 PR #180 末次 reactive 沉淀
- 1 人项目 0 自动化 prevention (handoff 数字 SQL verify before 写候选 0 sustained sustained sustained)

**Why 5 真根因**: 1 人项目走企业级 4 源协作架构 (F-D78-28 sustained candidate 推翻 P1) — N×N 同步 sustained 在 CLAUDE.md 集中爆发

### 2.3 CLAUDE.md churn ROI 量化

实测 sprint period:
- 30 day 22 PR (sprint period sustained), 103 commits CLAUDE.md update
- 平均每 PR ~5 次 CLAUDE.md update
- CLAUDE.md 真核心修改 = ~5-10 次 (重构 / 铁律 reference / 决议)
- 其余 ~90+ 次 = 数字漂移修 / 时间漂移修 / 同步漂移修 (低价值 maintenance)

**🔴 finding**:
- **F-D78-147 [P0 治理]** CLAUDE.md 30 day 103 commits = 极高 churn (~3.4 commits/day), 治理 sprint period 主战场, 真根因 = 1 人项目走企业级 4 源协作 N×N 同步 sustained 集中爆发. 沿用 F-D78-28 (1 人 vs 企业级架构 candidate 推翻) + F-D78-26 (4 源协作推翻) + F-D78-16 (ADR-022 ex-ante 缺) — 治理 over-engineering 真实证扩

---

## §3 其他 hotspot 文件 finding

### 3.1 LESSONS_LEARNED.md 34 commits / SYSTEM_STATUS.md 26 commits / QPB 21 commits / AUDIT_MASTER_INDEX 19 commits

**真测**: 4 顶级 SSOT 文档 30 day 累计 100+ commits (LL 34 + SYS 26 + QPB 21 + AUDIT_INDEX 19), 沿用 F-D78-46 跨文档漂移 broader 70+ 真实证扩

### 3.2 cache/baseline/regression_result_5yr.json 26 commits (代码层 baseline)

**真测**: regression baseline 30 day 26 update — 沿用 F-D78-24 sustained "regression max_diff=0 sustained" 候选 (真 baseline 26 update 含 max_diff 漂移 candidate verify)

### 3.3 scripts/run_paper_trading.py 25 commits + setup_task_scheduler.ps1 21 commits

**真测**: PT 启动脚本 + schtask 配置 30 day 高 churn — 沿用 F-D78-8 (5 schtask 失败 cluster) + F-D78-115 (intraday 真根因) candidate root cause sprint period 高 churn 但 enforcement 失败

### 3.4 daily_pipeline.py 18 + backtest_engine 16 + signal_engine 15 commits (核心生产代码)

**真测**: 核心生产代码 30 day 高 churn ✅ (sprint period 22 PR Wave 4 batch 3.x SDK migration sustained sustained sustained, 部分 sustained ✅ 真业务前进)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-147** | **P0 治理** | CLAUDE.md 30 day 103 commits = 极高 churn, 治理 sprint period 主战场, 真根因 1 人项目走企业级 4 源 N×N 同步集中爆发 |

---

**文档结束**.
