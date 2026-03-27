# Phase 1 计划 — A股完整 + AI + 实盘

> **状态**: 已迁移至 `docs/IMPLEMENTATION_MASTER.md`
> **原始制定人**: Team Lead | **原始日期**: 2026-03-22
> **迁移日期**: 2026-03-28

---

## 说明

本文件原为 Phase 1 的详细执行计划（三轮讨论、9人审查）。

R1-R7 七维度研究完成后，所有可落地项已整合到新的实施总纲中：

**→ [`docs/IMPLEMENTATION_MASTER.md`](docs/IMPLEMENTATION_MASTER.md)**

该文档包含：
- §1 执行摘要（当前状态 + 4并行轨道）
- §2 架构决策（R1-R7精华，标注哪些更新了DESIGN_V5原始设计）
- §3 运行时架构（调度链路/CompositeStrategy/挖掘Pipeline/部署架构）
- §4 接口规格（6个核心API定义）
- §5 Sprint 1.13-1.20 详细计划（每个Sprint = 1 PR边界）
- §6 R-Item追踪矩阵（73项 → Sprint分配）

## 原始决策保留

以下原始Phase 1决策仍然有效（详见IMPLEMENTATION_MASTER §2）：
- 衰减预算: 回测→实盘 ×0.68~0.77 (中位0.72)
- MDD优先: MDD > Sharpe > 因子数量
- PT毕业标准: 9项全部达标才能转实盘
- v1.1锁死: 60天PT期间不改参数

## 历史文档

原始完整版已归档: `docs/archive/` 目录（如需查阅三轮讨论细节）
