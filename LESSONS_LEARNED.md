# LESSONS_LEARNED.md — 经验教训记录

> TEAM_CHARTER §6.2要求。每个教训记录：事件+根因+改进措施+执行状态。

---

## LL-001: 研究组任务遗漏 (2026-03-22)

**事件**: Sprint 1.1期间，研究报告#1的3项并行任务（IVOL验证/bp_ratio评估/波动率自适应阈值）全部未启动。用户发现后才补启动。

**根因**: Team Lead编码组注意力占满后忘了分配研究组任务。违反§1.6"编码组和研究组同时工作"规则。

**改进措施**: 每个Sprint开始时，Team Lead必须同时列出编码组和研究组的任务清单，不允许只列编码组。格式：
```
Sprint X.Y 任务分配
编码组:
  arch: ...
  qa: ...
研究组:
  quant: ...
  factor: ...
  strategy: ...
  risk: ...
```

**执行状态**: Sprint 1.2开始时按此执行。

---

## LL-002: 持仓膨胀bug — _apply_turnover_cap并集问题 (2026-03-22)

**事件**: 1年模拟发现持仓从20膨胀到43只。

**根因**: `_apply_turnover_cap()`对target(20只)和prev(20只)取并集blend，产出30+持仓。换手率上限50%保护了旧持仓不被卖出，导致累积膨胀。

**改进措施**: blend后只保留target_codes中的股票。添加了qa测试6个用例覆盖。

**执行状态**: ✅ 已修复+测试通过。

---

## LL-003: MDD计算peak初始化bug (2026-03-22)

**事件**: quant审查发现`performance_repository.py`的`get_rolling_stats()`中MDD的peak初始化为最新NAV而非最早NAV。

**根因**: 数据是DESC排序，peak应从时间正序第一个(navs[-1])开始，但代码写了navs[0]（最新的）。

**改进措施**: 修复为`peak = navs[-1]`。强调：涉及时序计算时必须明确数据排序方向。

**执行状态**: ✅ 已hotfix。

---

## LL-004: 模拟脚本时序与生产不一致 (2026-03-22)

**事件**: 5天模拟和1年模拟（第一版）中，同一天运行signal+execute，导致execute读不到当天signal写的信号（execute去查前一天），月度调仓从未触发。

**根因**: 模拟脚本没有模拟T日signal→T+1日execute的真实时序。

**改进措施**: 修改为`signal(td)` + `execute(trading_days[i+1])`。模拟脚本必须与生产crontab时序完全一致。

**执行状态**: ✅ 已修复，1年重跑12/12检查点通过。

---

## LL-005: execute阶段盲信signal的rebalance标记 (2026-03-22)

**事件**: execute阶段Step 5.6的独立验证`needs_rebalance(exec_date)`会覆盖signal的rebalance标记。在生产crontab下，T日月末signal标记rebalance，T+1日（下月第1天）execute验证"T+1不是月末"→覆盖为hold，永远不调仓。

**根因**: Step 5.6设计初衷是防止重复运行，但逻辑错误——不应该用exec_date验证调仓条件（调仓决策是signal phase在T日做的）。

**改进措施**: execute信任signal的rebalance标记，仅在信号过时(>5天)时覆盖。

**执行状态**: ✅ 已修复。
