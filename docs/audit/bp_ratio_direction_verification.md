# bp_ratio direction=+1 vs "IC=-0.0355 冲突" 调研 — **FALSE ALARM**

**Date**: 2026-04-21 (Session 21 加时 P2)
**Status**: ✅ 冲突不存在, bp_ratio direction=+1 正确, 无需改动
**Owner**: 自验证关闭 (非 Session 22 follow-up)

## 背景 (原疑点)

Session 21 compact summary 列 "bp_ratio 20日 IC=-0.0355 vs direction=+1 sign conflict (Session 22 follow-up)" 作为未决跟进项.

## 实测证据

### factor_registry state
```sql
SELECT name, direction, status, pool FROM factor_registry WHERE name='bp_ratio';
-- bp_ratio | direction=1 | status=active | pool=CORE ✓
```

### factor_ic_history 全量 (2014-01-02 → 2026-04-07, 2977 行)
```
ic_20d 最近 15 条 non-null (2026-02-10 → 2026-03-10):
  2026-03-10: +0.017461
  2026-03-09: +0.104313
  2026-03-06: +0.066871
  ... (全 15 条 > 0, 范围 +0.017 ~ +0.151)
```

### ic_ma60 (60 日 rolling mean, 稳定性信号)
```
2026-04-02: +0.124718 ← 最近 non-null
2026-04-01: +0.124071
2026-03-31: +0.122953
... (全区间正值)
```

### 研究基线 (factor_profile v2)
- IC = +0.0523 (v1.1 baseline, 7/7 年正, single-factor Sharpe=1.31)
- 价值类因子, 经济机制: 账面价值高 → 低估 → 正向回报 → direction=+1 ✓
- Alpha158 + Qlib baseline 一致 direction=+1

## 结论

**没有 "IC=-0.0355" 证据**. 此数字不在 factor_ic_history 任何时间窗口 / 任何列出现. 来源推测:

- Session 21 compact AI summary 阶段凭记忆/错位推论, 写入 "Session 22 follow-up" 列表但无 DB/脚本落脚点
- 真实 bp_ratio 20 日 IC 最近 non-null 值 = **+0.017461** (2026-03-10), 与 direction=+1 同向
- ic_ma60 = +0.1247 稳定正值, 长期 alpha 健康

## Session 21 今日关闭

- bp_ratio direction 冲突 **不存在**, 不作为 Session 22 跟进项
- 无需触发 `factor_onboarding` 方向翻转流程
- 无需改 `pt_live.yaml` 或 `signal_engine.PAPER_TRADING_CONFIG`

## 顺带发现 (Session 22 真正跟进项)

### A. IC 计算停在 2026-04-07

6 CORE+related 因子 (bp_ratio/dv_ttm/turnover_mean_20/volatility_20/reversal_20/amihud_20) factor_ic_history `MAX(trade_date) = 2026-04-07`. 过去 **14 天 (4-08 ~ 4-21) 零 IC 入库**.

这违反 **铁律 11** (IC 必须有可追溯的入库记录). Session 22+ 优先级调查:
- `monitor_factor_ic.py` schedule 是否 4-07 后 broken?
- Celery beat `factor-ic-monitor-daily` 执行记录查证 (beat_schedule.py L? 待查)
- 若 broken, factor_lifecycle 近期 "warning → active recovery" 判定可能基于**过期 IC_MA20/60**

### B. ic_20d 2026-03-10 后全 NULL

即使在"有 IC"的 4-07 记录中, `ic_20d` 也是 NULL. 说明 20d 窗口特别有数据缺失. 需查 IC 计算函数 20d window 是否要求 ≥ N 样本而当前覆盖不够.

### C. ic_1d / ic_abs_1d / ic_abs_5d 全 NULL

所有记录 `ic_1d` 列全 NULL (我 25 条查询中无一条填). 说明 1d 横截面 IC 从未入库. factor_profile_v2 可能依赖这些空字段做判断, 导致部分因子"永远 insufficient data".

## 教训

**AI summary 数字警戒**: AI 在 `/compact` 阶段生成的"跟进项列表"数字 (IC/Sharpe/相关性) 必须 grep 原始数据源**反向验证**. 本次若不查 factor_ic_history, Session 22 可能基于虚构 -0.0355 启动方向翻转讨论, 浪费 workflow.

**铁律 25 外延**: 新 session 接 summary 时, 任何具体数值 (含 summary 二次转述) 在采取行动前 = 查一次 DB/源码. summary 文字叙述可信度 > summary 内嵌数字.
