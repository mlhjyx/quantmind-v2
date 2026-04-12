# Phase 2.2: Gate驱动的多方向验证 — NO-GO

**日期**: 2026-04-11
**结论**: NO-GO — 所有6种方法均未超越等权CORE5+SN基线

## 对比矩阵

| # | 方法 | Sharpe | MDD | 年化收益 | vs基线 |
|---|------|--------|-----|----------|--------|
| 0 | 等权CORE5+SN(同期基线) | **0.6211** | -15.88% | 10.01% | — |
| 0 | 等权CORE5(无SN) | 0.3956 | -40.69% | 6.91% | -36.3% |
| 1 | LambdaRank+SN | 0.5573 | -27.58% | 8.58% | -10.3% |
| 1 | LambdaRank(无SN) | 0.1678 | -61.47% | 0.62% | -73.0% |
| 0 | LightGBM regression+SN | 0.4421 | -33.66% | 6.06% | -28.8% |
| 0 | LightGBM regression(无SN) | -0.1559 | -74.21% | -7.87% | N/A |
| 3a | IC_IR加权+SN | 0.2694 | -49.32% | 3.64% | -56.6% |
| 3a | IC_IR加权(无SN) | 0.2199 | -60.99% | 2.00% | -64.6% |
| 3b | MVO(等权Top-40) | 0.2598 | -61.21% | 3.38% | -58.2% |
| 3b | IC+MVO | 0.2087 | -61.21% | 1.86% | -66.4% |

**Go条件**: 任一方法Sharpe > 0.717 (基线×1.1) → **未达到**
**OOS期间**: 2020-01-02 ~ 2026-03-12 (6年, 1516交易日)

## 关键发现

### 1. 等权不可超越(Equal-Weight Supremacy)
所有试图替代等权的方法(ML权重、IC_IR权重、MVO优化)都产生了更差的结果。等权CORE5+SN的Sharpe=0.6211是这组实验的天花板。

### 2. SN是唯一有效Modifier
- 无SN→+SN改善幅度: +57%(等权), +163%(LightGBM), +232%(LambdaRank), +23%(IC加权)
- SN通过惩罚micro-cap暴露来抑制执行成本，效果在所有方法上一致

### 3. LambdaRank是最接近的替代方案
- LambdaRank+SN(0.5573)比regression+SN(0.4421)高26%
- 排名优化确实帮助Top-N选股质量，但仍不足以超越等权
- IC从regression的0.049降到LambdaRank的0.049，但NDCG@20排名质量更好

### 4. IC加权反而更差的原因
- turnover_mean_20的|IC_IR|=2.41最高，获得最大权重
- 这放大了低流动性暴露(turnover方向=-1，即选低换手率)
- 低流动性股票执行成本极高(滑点+冲击成本)
- 等权框架下5因子互相平衡，IC加权打破了这种平衡

### 5. MVO失败原因
- 135/144次(94%)MVO优化失败，退化为等权
- 40只股票×60日估计窗口→协方差矩阵严重估计不稳定
- 即使用Ledoit-Wolf shrinkage也不够
- MVO需要更大的universe或更长的估计窗口

### 6. PN v2不值得继续
- Phase 2.1已证明sim-to-real gap 282%(val_sharpe=1.26→实盘-0.99)
- 无checkpoint需要15-20min重训练
- A股交易成本(min佣金¥5/印花税/overnight gap)不可微分
- 结论: 端到端可微优化在A股不可行

## 根因分析

**核心瓶颈不在portfolio构建层，而在信号层:**
1. CORE5因子IC天花板~0.09(Phase 2.1验证)
2. 信号维度不足: 5因子只有量价+价值，缺少基本面/另类数据
3. 所有"优化"方法(IC加权/MVO/ML权重)都在同一个低维信号空间内重新分配权重
4. 重新分配权重不能创造新的alpha，只能改变风险暴露分布
5. 而改变风险暴露分布在当前因子集下总是朝着更差的方向(过度暴露流动性风险)

## 对已知失败方向的更新

本次实验进一步确认:
- **IC加权/Lasso等下游优化**: 因子信息量不够时优化下游无效(v3.5原则16再次验证)
- **MVO portfolio优化**: 小universe + 短估计窗口 = 不可行
- **predict-then-optimize**: IC正但Sharpe≈0的gap无法通过ranking loss弥合

## 下一步建议

既然portfolio构建层所有方向都已验证失败，瓶颈回到信号层:

1. **新数据维度**: 基本面(财报/分析师预期)、另类数据(舆情/供应链)
2. **更长horizon**: 季度调仓+基本面因子(减少交易成本)
3. **多策略ensemble**: 不同horizon的独立策略组合(月度量价+季度基本面)
4. **Phase 3自动化**: 固化当前等权+SN基线，建设因子生命周期自动监控

## 文件索引

- 主脚本: `scripts/research/phase22_gate_verification.py`
- Gate 0结果: `cache/phase22/gate0_result.json`
- LambdaRank结果: `cache/phase22/part1_lambdarank_result.json`
- IC加权结果: `cache/phase22/part3_ic_weighted_result.json`
- MVO结果: `cache/phase22/part3_mvo_result.json`
- Phase 2.1 E2E结论: `docs/research-kb/findings/phase21-e2e-fusion-results.md`
