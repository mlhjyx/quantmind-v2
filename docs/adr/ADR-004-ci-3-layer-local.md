---
adr_id: ADR-004
title: CI 策略 — 3 层本地 (pre-commit + pre-push + daily full)
status: accepted
related_ironlaws: [22, 40]
recorded_at: 2026-04-17
---

## Context

Wave 4 引入 CI 验证 protocol 保证铁律 22 (文档跟随代码) + 铁律 40 (测试债务不得增长). 候选:

1. **GitHub Actions** — 云端 CI, 每 push 触发
2. **本地 3 层 git hooks** — pre-commit (快速) + pre-push (中等) + 本地 cron daily full

项目是单人闭源 monorepo, 未推 GitHub 公开仓库. 使用 GitHub Actions 需:
- 把代码推到 GitHub (当前在本地 git + 本地部署)
- 或用 Gitea / GitLab self-hosted 另建 CI runner

考虑单人项目的实际工作流: push 频率远低于 commit 频率, 大批测试在 push 前跑即可. 每 commit 跑全量 pytest (>10min) 会阻塞开发.

## Decision

采用 **3 层本地 CI** (无云端):

| 层 | 触发 | 耗时 | 内容 |
|---|---|---|---|
| **pre-commit hook** | `git commit` | ≤ 5s | ruff format + ruff check + smoke test (仅新文件) |
| **pre-push hook** | `git push` | 30s-2min | MVP 锚点 pytest (~300 tests) + ruff all + regression 不跑 |
| **daily full (cron)** | 19:00 每日 | 10-15min | 全量 pytest + regression_test --years 5 + full ruff + 报告到 sprint_state |

`scripts/service_manager.ps1` 加 `daily-ci` 任务, Windows Task Scheduler 触发.

## Alternatives Considered

| 选项 | 成本 | 延迟 | 为何不选 |
|---|---|---|---|
| **3 层本地** ⭐ | 0 云 + 低 overhead | 即时 | — (选此) |
| GitHub Actions | 免费层够用, 但需公开仓库或 token | 2-5 min 启动 | 代码敏感 (A 股策略细节), 不推公开仓库 |
| GitLab Self-hosted | 运维一个 GitLab 实例 | 即时 | 单人项目杀鸡用牛刀 |

## Consequences

**正面**:
- 0 运维成本, 0 云依赖 (项目已断网也能工作)
- pre-push 在推前把关, 符合铁律 40 "新代码不增加 fail"
- daily full 覆盖 10-15min 全量 + regression, 催生每日 fail 监控习惯

**负面**:
- 没 CI UI 面板, fail 靠终端日志 + sprint_state 手写
- pre-commit 若 5s 超了, 开发者可能 bypass (`git commit --no-verify`) — 需警惕
- 多设备协作不友好 (若未来加协作者), 得换 GitHub Actions

## References

- `memory/project_platform_decisions.md` §Q4
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 4 Wave 4 CI
- `.claude/hooks/` 现有 hook 示例
- 铁律 40: 测试债务不得增长 → pre-push 阻断 fail 数涨
