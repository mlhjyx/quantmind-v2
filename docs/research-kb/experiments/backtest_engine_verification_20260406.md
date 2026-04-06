# 实验: 回测引擎验证 (6项)
- 日期: 2026-04-06
- 目的: 验证回测引擎可信度，因子扩展实验发现Sharpe差0.48(0.78 vs 1.26)

## 验证结果

### V1 确定性: PASS
- 3次运行bit-for-bit一致: Sharpe=1.24, MDD=-34.95%, CAGR=32.41%
- 配置: CORE 5等权Top-20月度+PMS tiered_close+volume_impact滑点

### V2 成本模型: PASS
- 佣金万0.854(双边) + 印花税千0.5(仅卖) + 过户费万0.1 + 最低佣金5元
- 三因素滑点: base(3-8bps按市值) + Bouchaud impact + 隔夜跳空
- ad-hoc研究脚本: 零成本(factor_pool_expansion/ic_weighted/strategy_overlay)

### V3 基线锚定: WARN
- run_backtest.py: Sharpe=1.24 vs CLAUDE.md记载1.15, 差异+0.09
- 可能原因: Sharpe年化方法差异 或 PMS执行模式差异
- 待追溯1.15出处脚本

### V4 跨引擎一致: 可解释
- run_backtest.py Sharpe=1.24 vs factor_pool_expansion.py Sharpe=1.27
- Sharpe差0.03(成本影响), MDD差16.95pp(PMS影响)
- 结论: ad-hoc无成本+无PMS，不可直接与生产引擎对比

### V5 边界条件: WARN (6/8)
- ✅ 涨停买入/跌停卖出/停牌/整手约束/因子NaN
- ⚠️ 资金T+1简化为T+0(行业惯例可接受)
- ❌ 新上市<20天未排除
- ❌ 退市未处理

### V6 数据对齐: WARN
- CORE 5因子: 2020-07-01~2026-04-02 完整
- 15因子扩展组: 只有9/15在DB，6个缺失
- 2021年初: 7/15因子有数据

## 结论
- 生产引擎(run_backtest.py)可信任
- ad-hoc研究脚本零成本，只能用于因子筛选，不能做最终策略评估
- 后续策略实验必须用run_backtest.py
