---
adr_id: ADR-001
title: Platform 包名 `backend.qm_platform` (不加 quantmind namespace)
status: accepted
related_ironlaws: [38]
recorded_at: 2026-04-17
---

## Context

Wave 1 启动前的开放问题之一: Platform SDK 包应放在 `backend.qm_platform.*` 还是 `backend.quantmind.platform.*`?

项目历史用 "quantmind_v2" 作代码库名, 但 Python 包没使用 `quantmind` 命名空间前缀. 有观点认为未来若项目演化为多个子系统 (backtest/PMS/forex) 需要顶层命名空间隔离.

决策时机: MVP 1.1 Platform Skeleton 写代码前, 若选长路径需回退 45+ 行 import.

## Decision

采用 **`backend.qm_platform`** 作为 Platform SDK 包根. Framework 子包直接挂在其下:

```
backend/platform/
├── data/
├── factor/
├── strategy/
├── signal/
├── backtest/
├── eval/
├── observability/
├── config/
├── ci/
├── knowledge/
├── resource/
└── backup/
```

## Alternatives Considered

| 选项 | 优势 | 劣势 | 为何不选 |
|---|---|---|---|
| `backend.quantmind.platform` | 未来多项目共存 | import 路径长 + `backend.quantmind` 中间层无意义 | Python 包已有项目级隔离 (monorepo 独立仓库), 再加 namespace 过度设计 |
| `backend.quantmind_core` | 明确"核心" | 命名模糊 + 非平台语义 | core 意图不清 |
| `quantmind_platform` (顶层) | 可独立 pip 包 | 与 `backend/app/` 脱钩 + 迁移成本 | 当前单仓库单部署, 不需 pip 发布 |

## Consequences

**正面**:
- 短路径: `from backend.qm_platform.factor.registry import DBFactorRegistry` (51 字符, 已够深)
- Python 已用 `sys.path` + 子模块语义隔离, 无需再加 namespace
- MVP 1.1 骨架一天搭完, 后续 MVP 不再改动包路径

**负面**:
- 若未来真有 Q2 项目 (e.g. `quantmind_forex`) 共享 Platform 代码, 需走 pip 发布路径, 非 import 共用
- `backend.qm_platform` 撞 stdlib `platform` — MVP 1.2 踩过一次坑 (pandas `import platform` 被覆盖). 解法: 所有 `sys.path.insert(0, backend_dir)` 改 `append` 保 stdlib 优先

## References

- `memory/project_platform_decisions.md` §Q1
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 1
- MVP 1.1 交付: commit (Wave 1 第 1 步)
- MVP 1.2 stdlib platform 踩坑记录: `docs/mvp/MVP_1_2_config_management.md`
