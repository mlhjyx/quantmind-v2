# 设计文档 vs 实际实现差距分析

**日期**: 2026-04-10 | **来源**: Step 6-H 审计 + QUANTMIND_FACTOR_UPGRADE_PLAN_V3.md

---

## 1. 11份设计文档实现率统计

| 文档 | 设计了什么 | 实现% | 主要差距 |
|------|----------|-------|---------|
| DESIGN_V5.md | 完整系统架构(500+页) | ~20% | 过度设计，实际运行的是子集 |
| DEV_BACKEND.md | 17个Service+57端点 | ~60% | 29个Service+22个API路由已实现, 三层分层完全落地 |
| DEV_BACKTEST_ENGINE.md | 3-Step引擎+Rust加速 | ~25% | 只有Step 1(8模块拆分+Hybrid), Step 2/3/Rust未启动 |
| DEV_FACTOR_MINING.md | GP+LLM+暴力枚举 | ~55% | Gate/Profiler/IC完整, GP引擎+暴力枚举+DeepSeek+3 Agent已实现, 未端到端闭环 |
| DEV_FRONTEND_UI.md | 12页面+53组件 | ~40% | 24个页面文件已创建(超过设计), 但部分功能不完整 |
| DEV_AI_EVOLUTION.md | 4 Agent+Pipeline | ~20% | IdeaAgent/FactorAgent/EvalAgent+PipelineOrchestrator有代码框架(4034行), 未闭环 |
| DEV_PARAM_CONFIG.md | 220个可配置参数 | ~25% | 52个yaml参数在用, 4个配置文件 |
| DEV_SCHEDULER.md | 28个定时任务 | ~25% | 7个Celery task+2 beat crontab+Windows Task Scheduler |
| DEV_FOREX.md | 完整外汇系统 | 0% | Phase 2+, A股优先 |
| DEV_NOTIFICATIONS.md | 多渠道通知 | ~30% | notification_service(706行)+templates(387行)+throttler(111行) |
| ML_WALKFORWARD_DESIGN.md | 完整ML WF | ~50% | WF框架OK, LightGBM验证ML无效 |

**加权平均实现率**: ~30% (基于代码验证, 原估~21%偏低)

---

## 2. 5个根因

### 根因1：过度设计（先写500页再动手）
- 11份设计文档总计超过3000行markdown
- 设计与现实脱节速度快——代码写完设计就过时
- **证据**: DESIGN_V5.md 500+页但只有~20%实现

### 根因2：模块间依赖死锁
- DEV_AI_EVOLUTION 依赖所有其他模块
- DEV_BACKEND 依赖前端/AI/外汇模块
- 没有一个模块能独立启动和验证
- **证据**: AI模块仅~20%实现(有代码框架但无端到端闭环)因为依赖链太长

### 根因3：没有MVP定义
- 设计文档描述"完整态"但不定义"最小可用态"
- 不知道何时算"完成"，永远在增加功能
- **证据**: DEV_PARAM_CONFIG 220参数但只需~50个

### 根因4：实验反馈未回写设计
- Step 6系列发现大量设计假设不成立（ML无效、Modifier无效等）
- 但发现没有反馈回设计文档，文档越来越过时
- **证据**: DEV_BACKTEST_ENGINE 未预见OOM问题

### 根因5：自建一切
- Qlib/RD-Agent 已实现90%设计功能
- 项目初期没有评估开源方案
- **证据**: DEV_AI_EVOLUTION 设计的4Agent+Pipeline = RD-Agent(Q)现成方案

---

## 3. 5个解决方案（V3原则）

| 原则 | 解决根因 | 内容 |
|------|---------|------|
| 原则1: 目标驱动 | 根因1(过度设计) | 不问"系统应该有什么"，问"Sharpe从0.68到1.0需要什么" |
| 原则2: 独立可执行 | 根因2(依赖死锁) | 每个任务不依赖其他未实现模块，有独立输入/输出/验收标准 |
| 原则3: 先实验后设计 | 根因3(无MVP) | 每个方向先2天实验验证可行，再写实现计划 |
| 原则4: 站在巨人肩膀上 | 根因5(自建一切) | 能用Qlib/RD-Agent的就不自己写 |
| 原则5: 文档跟随代码 | 根因4(无反馈) | 不维护"理想架构"，只维护"当前状态"+"下一步" |

---

## 4. 对应铁律

- 铁律21: 先搜索开源方案再自建（对应原则4）
- 铁律22: 文档跟随代码（对应原则5）
- 铁律23: 每个任务独立可执行（对应原则2）
- 铁律24: 设计不超过2页（对应原则1+3）
