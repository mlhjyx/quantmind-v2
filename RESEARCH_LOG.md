# RESEARCH_LOG.md — 研究记录

> 所有研究发现记录于此，无论是否采纳。
> 格式：[角色] 标题 / 来源 / 核心方法 / 对项目价值 / 状态

---

## 2026-03 研究记录

### [factor] GPA(Gross Profit to Assets)因子在A股的方向反转

- **来源**: Novy-Marx (2013), "The Other Side of Value: The Gross Profitability Premium", JFE
- **核心发现**: A股GPA因子方向与美股相反——低毛利率股票5日跑赢高毛利率（IC=-0.038, t=-2.95）
- **quant审查结论**: 行业中性化后IC衰减61.6%至-0.011(p=0.14不显著)。本质是行业暴露proxy，不是stock-level alpha
- **对项目的价值**: 排除了一个潜在因子，避免引入伪alpha
- **状态**: ❌ 不纳入组合（quant否决）

### [quant] 回测与Paper Trading模拟的入场时机差异

- **发现**: 同期(2025-04~2026-03)回测Sharpe=3.07 vs 模拟Sharpe=1.80，差异源于回测4月空仓(等月末首信号)躲过4/7关税冲击-13.15%
- **方法论启示**: 回测start_date的首次建仓时机会显著影响结果。建议加`--initial-rebalance-now`参数
- **状态**: 📝 BACKLOG（回测参数改进）

### [factor] 下一因子候选方向（BACKLOG → Sprint 1.3）

- **方向1**: 盈利惊喜因子——ann_date前后超额收益，捕捉PEAD(Post-Earnings-Announcement Drift)
- **方向2**: 股东人数变化——stk_holdernumber季度变化率，筹码集中度proxy
- **数据依赖**: 方向1需fina_indicator已有数据，方向2需Sprint 1.3新增stk_holdernumber接口
- **状态**: 📋 BACKLOG，Sprint 1.3数据源扩展时推进

### [risk] 2025-04-07 关税冲击事件

- **事件**: 单日组合亏损-13.15%（20只等权），触发L2熔断
- **对项目的价值**: 真实的"突发政策冲击"压力测试案例
- **状态**: 📋 纳入压力测试场景库（Sprint 1.2）
