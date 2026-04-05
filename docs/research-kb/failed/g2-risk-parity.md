# 失败方向: G2 风险平价/最小方差权重(7组)
- 日期: 2026-04-03
- 假设: risk_parity/min_variance/vol_regime权重分配可以改善Sharpe/MDD
- 实验: 7组权重方法回测(等权vs risk_parity vs min_variance vs vol_regime × 2参数)
- 结果: 全部Sharpe下降或不变，MDD无改善
- 失败原因: 等权在Top-N选股策略中已接近最优——因子选股的alpha主要在选股不在权重
- 适用条件: Top-N因子选股月度策略，资金量<500万
- 不应重复: 任何形式的权重优化(含inverse vol, max diversification等)
