# 因子资产全面盘点 + 被冤杀因子重测方案

> 生成日期: 2026-04-02
> 数据来源: factor_values DB (37因子) + FACTOR_TEST_REGISTRY (74条) + factor_lifecycle (5条) + factor_engine.py代码 + FactorClassifier

---

## 1. 因子全景表

### 1.1 DB中有数据的37个因子完整清单

| # | 因子名 | 类别 | IC_mean | t-stat | 所在池 | DB行数 | 时间范围 | 覆盖率 | Classifier类型 | 推荐动作 |
|---|--------|------|---------|--------|--------|--------|----------|--------|----------------|----------|
| 1 | **turnover_mean_20** | 流动性 | -0.0643 | -7.31 | **Active** | 695万 | 2020-07~2026-04 | 99.2% | RANKING(月度) | 维持Active |
| 2 | **volatility_20** | 风险 | -0.0690 | -6.37 | **Active** | 695万 | 2020-07~2026-04 | 99.7% | RANKING(月度) | 维持Active |
| 3 | **reversal_20** | 价量 | +0.0386 | +3.50 | **Active** | 695万 | 2020-07~2026-04 | 99.5% | **FAST_RANKING(双周)** | ⚠️ **被冤杀候选**: 半衰期14.7天，月度调仓时已衰减60% |
| 4 | **amihud_20** | 流动性 | +0.0215 | +2.69 | **Active** | 695万 | 2020-07~2026-04 | 99.7% | RANKING(月度) | 维持Active |
| 5 | **bp_ratio** | 价值 | +0.0523 | +6.02 | **Active** | 695万 | 2020-07~2026-04 | 98.7% | RANKING(月度) | 维持Active |
| 6 | vwap_bias_1d | 价量 | -0.0464 | -2.69 | **Reserve** | 644万 | 2021-01~2026-04 | 100% | 需IC衰减数据 | ⚠️ **被冤杀候选**: IC=-4.6%强但未入组合，需正确框架重测 |
| 7 | rsrs_raw_18 | 技术 | -0.0371 | -3.99 | **Reserve** | 695万 | 2020-07~2026-04 | 99.8% | 需IC衰减数据 | ⚠️ **被冤杀候选**: ICIR=-0.54，阻力支撑因子 |
| 8 | ep_ratio | 价值 | +0.0341 | +4.80 | FULL | 695万 | 2020-07~2026-04 | 77.9% | 需IC衰减数据 | LGBM特征(覆盖率低需注意) |
| 9 | price_volume_corr_20 | 价量 | -0.0394 | -6.41 | FULL | 695万 | 2020-07~2026-04 | 99.8% | 需IC衰减数据 | **IC强(3.9%), Reserve候选** |
| 10 | reversal_5 | 价量 | +0.0273 | +3.10 | FULL | 695万 | 2020-07~2026-04 | 99.9% | 需IC衰减数据 | LGBM特征 |
| 11 | reversal_10 | 价量 | +0.0391 | +3.77 | FULL | 695万 | 2020-07~2026-04 | 99.7% | 需IC衰减数据 | CONDITIONAL(corr(rev20)=0.67) |
| 12 | price_level_factor | 价量 | +0.0549 | +4.99 | FULL(v1.2) | 695万 | 2020-07~2026-04 | 100% | 需IC衰减数据 | **IC强(5.5%), Reserve Tier1** |
| 13 | relative_volume_20 | 流动性 | -0.0280 | -3.94 | FULL(v1.2) | 695万 | 2020-07~2026-04 | 99.2% | 需IC衰减数据 | LGBM特征 |
| 14 | dv_ttm | 价值 | +0.0313 | +5.49 | FULL(v1.2) | 695万 | 2020-07~2026-04 | 97.5% | 需IC衰减数据 | LGBM特征(股息率) |
| 15 | turnover_surge_ratio | 流动性 | -0.0357 | -3.93 | FULL(v1.2) | 695万 | 2020-07~2026-04 | 99.2% | 需IC衰减数据 | LGBM特征 |
| 16 | ln_market_cap | 规模 | -0.0308 | -2.09 | CORE | 695万 | 2020-07~2026-04 | 99.4% | 需IC衰减数据 | LGBM特征(t偏低) |
| 17 | kbar_kmid | K线 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 100% | 需IC衰减数据 | LGBM特征 |
| 18 | kbar_ksft | K线 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 100% | 需IC衰减数据 | LGBM特征 |
| 19 | kbar_kup | K线 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 100% | 需IC衰减数据 | LGBM特征 |
| 20 | maxret_20 | 价量 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 99.8% | 需IC衰减数据 | LGBM特征 |
| 21 | chmom_60_20 | 动量 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 98.5% | 需IC衰减数据 | LGBM特征 |
| 22 | up_days_ratio_20 | 价量 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 99.8% | 需IC衰减数据 | LGBM特征 |
| 23 | stoch_rsv_20 | 技术 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 99.8% | 需IC衰减数据 | LGBM特征 |
| 24 | gain_loss_ratio_20 | 技术 | — | — | ML_KLINE | 565万 | 2021-01~2026-03 | 99.8% | 需IC衰减数据 | LGBM特征 |
| 25 | mf_divergence | 资金流 | +0.0910 | — | ML_MONEYFLOW | 565万 | 2021-01~2026-03 | 95.2% | 需IC衰减数据 | ⚠️ **被冤杀: IC=9.1%全项目最强但等权组合增量=0(LL-017)** |
| 26 | large_order_ratio | 资金流 | — | — | ML_MONEYFLOW | 565万 | 2021-01~2026-03 | 96.1% | 需IC衰减数据 | LGBM特征 |
| 27 | money_flow_strength | 资金流 | — | — | ML_MONEYFLOW | 565万 | 2021-01~2026-03 | 96.1% | 需IC衰减数据 | LGBM特征 |
| 28 | beta_market_20 | 风险 | — | — | ML_INDEX | 565万 | 2021-01~2026-03 | 99.8% | 需IC衰减数据 | LGBM特征 |
| 29 | momentum_5 | 动量 | -0.0273 | -3.10 | **Deprecated** | 695万 | 2020-07~2026-04 | 99.9% | — | 保留(= -reversal_5) |
| 30 | momentum_10 | 动量 | -0.0391 | -3.77 | **Deprecated** | 695万 | 2020-07~2026-04 | 99.7% | — | 保留(= -reversal_10) |
| 31 | momentum_20 | 动量 | -0.0395 | -3.57 | **Deprecated** | 691万 | 2020-07~2026-03 | 99.5% | — | 确认Deprecated(= -reversal_20) |
| 32 | volatility_60 | 风险 | -0.0696 | -5.77 | **Deprecated** | 611万 | 2020-07~2026-03 | 99.2% | — | 保留给LGBM(corr(vol20)=0.76) |
| 33 | volume_std_20 | 流动性 | -0.0117 | -1.31 | **Deprecated** | 611万 | 2020-07~2026-03 | 99.8% | — | 确认Deprecated(IC弱) |
| 34 | turnover_std_20 | 流动性 | -0.0681 | -8.46 | **Deprecated** | 611万 | 2020-07~2026-03 | 99.2% | — | 保留给LGBM(corr(turn_mean)=0.91) |
| 35 | high_low_range_20 | 风险 | -0.0746 | -6.53 | **Deprecated** | 611万 | 2020-07~2026-03 | 99.8% | — | 保留给LGBM(corr(vol20)=0.89) |
| 36 | turnover_stability_20 | 流动性 | — | — | **Deprecated** | 644万 | 2021-01~2026-04 | 99.3% | — | 确认Deprecated(corr(turn_mean)=0.904) |
| 37 | reversal_60 | 价量 | +0.0270 | +2.28 | 无池归属 | 601万 | 2021-01~2025-12 | 100% | — | **孤儿因子**: PASS但未入任何池 |

### 1.2 池分布汇总

| 池 | 数量 | 因子 |
|----|------|------|
| **Active** (factor_lifecycle) | 5 | turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio |
| **Reserve** | 2 | vwap_bias_1d, rsrs_raw_18 |
| **FULL** (非Active/Reserve) | 9 | ep_ratio, pv_corr_20, reversal_5/10, price_level, relative_vol, dv_ttm, turnover_surge, ln_mcap |
| **ML特征** (KLINE+MF+INDEX) | 12 | kbar_kmid/ksft/kup, maxret, chmom, up_days, stoch_rsv, gain_loss, mf_divergence, large_order, money_flow_str, beta_market |
| **Deprecated** | 8 | momentum_5/10/20, volatility_60, volume_std, turnover_std/stability, high_low_range |
| **孤儿** (有数据无池) | 1 | reversal_60 |

### 1.3 代码中已实现但DB无数据的因子 (设计文档级)

| 因子 | 代码位置 | 需要的数据 | 状态 |
|------|----------|-----------|------|
| 6个基本面delta | factor_engine.py L637-740 | financial_indicators (PIT) | 代码已实现，Sprint 1.5证明无效 |
| 2个时间特征 | factor_engine.py L732-734 | 无额外数据 | 代码已实现，Sprint 1.5证明无效 |

### 1.4 FACTOR_TEST_REGISTRY中PASS但未入任何池的因子

| # | 因子 | IC | t-stat | Registry状态 | DB有数据? | 为什么不在池中? |
|---|------|-----|--------|-------------|-----------|---------------|
| 19 | IVOL | +0.0667 | — | PASS | **否** | 未实现计算代码 |
| 40 | gap_frequency | +0.0595 | — | PASS | **否** | 未实现计算代码 |
| 43 | mf_momentum_divergence | +0.0910 | — | PASS | **否** | signal_engine有DIRECTION但factor_engine无实现 |
| 44 | net_mf_amount | +0.0490 | — | PASS | **否** | 未实现 |
| 46 | big_small_divergence | +0.0375 | — | PASS | **否** | 未实现 |
| 57 | earnings_surprise_car | +0.0534 | — | PASS | **否** | PEAD事件因子，需EVENT框架 |
| 60 | RSI_14 | -0.0606 | — | PASS | **否** | TA-Lib因子，未实现 |
| 61 | MACD_hist | +0.0373 | — | PASS | **否** | TA-Lib因子，未实现 |
| 62 | KDJ_K | -0.0373 | — | PASS | **否** | TA-Lib因子，未实现 |
| 63 | CCI_14 | -0.0469 | — | PASS | **否** | TA-Lib因子，未实现 |
| 64 | ATR_norm | -0.1016 | — | PASS | **否** | TA-Lib因子，IC=10.16%全注册表最强 |

**11个PASS因子DB无数据** — 这是最大的资产浪费。

---

## 2. 被冤杀因子清单

### 2.1 FactorClassifier确认的框架不匹配

| 因子 | 当前框架 | Classifier推荐 | IC | 证据 |
|------|---------|---------------|-----|------|
| **reversal_20** | 月度RANKING | **FAST_RANKING(双周)** | 3.86% | 半衰期14.7天，月度调仓时IC衰减60%。Classifier置信度仅0.59(其余Active>0.85) |
| **vwap_bias_1d** | 月度RANKING(未入) | 待测(可能FAST_RANKING) | 4.64% | 日频因子用月度框架严重不匹配 |
| **rsrs_raw_18** | 月度RANKING(未入) | 待测(可能EVENT/FAST_RANKING) | 3.71% | 阻力支撑信号是事件性的 |

### 2.2 IC强但等权组合增量=0的因子 (LL-017)

| 因子 | 单因子IC | 组合增量 | 组合框架 | 失败原因 |
|------|---------|---------|---------|----------|
| **mf_divergence** | **9.1%** (最强) | +0.10%(p=0.387) | 月度等权6因子 | 等权合成稀释+预测维度隐性重叠 |
| **earnings_surprise_car(PEAD)** | **5.34%** | Sharpe-0.085 | 月度等权6因子 | 事件因子强制塞入月度框架 |

### 2.3 有数据但从未被回测验证过的ML因子

以下12个ML因子有完整DB数据，但从未跑过单独的IC test或框架匹配分析:

| 因子 | 类别 | DB行数 | 说明 |
|------|------|--------|------|
| kbar_kmid | K线 | 565万 | 中间价位因子 |
| kbar_ksft | K线 | 565万 | 上下影因子 |
| kbar_kup | K线 | 565万 | 上影因子 |
| maxret_20 | 价量 | 565万 | 最大日收益率 |
| chmom_60_20 | 动量 | 565万 | 累积动量差异(60d-20d) |
| up_days_ratio_20 | 价量 | 565万 | 上涨天数占比 |
| stoch_rsv_20 | 技术 | 565万 | 随机指标RSV |
| gain_loss_ratio_20 | 技术 | 565万 | 盈亏比 |
| large_order_ratio | 资金流 | 565万 | 大单占比 |
| money_flow_strength | 资金流 | 565万 | 资金流强度 |
| beta_market_20 | 风险 | 565万 | 市场beta |
| reversal_60 | 价量 | 601万 | 60日反转(**孤儿因子**) |

---

## 3. mining_knowledge和gp_approval_queue状态

| 表 | 记录数 | 状态 |
|----|--------|------|
| mining_knowledge | **0** | 空表 — GP虽然跑过验证(Sprint 1.32)但产出0个通过Gate的因子 |
| gp_approval_queue | **0** | 空表 — 无待审批因子 |

GP产出为0的原因(Sprint 1.32记录): 5代×20 population太小 + 缺pb/circ_mv等market data字段。

---

## 4. 关键发现

### 发现1: 11个PASS因子0实现 — 最大资产浪费

FACTOR_TEST_REGISTRY中有11个IC通过测试的因子从未实现到factor_engine.py:
- ATR_norm (IC=10.16%), IVOL (IC=6.67%), gap_frequency (IC=5.95%) — 这3个IC都极强
- 5个TA-Lib因子 (RSI/MACD/KDJ/CCI/ATR) — 用ta-lib库几行代码就能实现
- mf_momentum_divergence (IC=9.1%) — signal_engine.py有DIRECTION(-1)但factor_engine无计算函数

### 发现2: reversal_20是Active中唯一被错误框架使用的因子

Classifier明确分类为FAST_RANKING(双周)，置信度0.59（其他4个Active都是0.85）。半衰期14.7天意味着月度调仓时信号已衰减60%。如果改成双周调仓，reversal_20的alpha贡献应大幅提升。

### 发现3: 12个ML因子有数据但从未跑过单因子IC测试

这些因子在Sprint 1.4b的LightGBM实验中作为特征使用过(#66-72)，但SHAP分析显示17特征组劣于5基线。然而这不代表每个因子单独无效——可能是LightGBM过拟合导致的，需要单独验证每个因子的IC和半衰期。

### 发现4: 资金流因子生态完整但利用率为0

DB中有3个资金流因子(mf_divergence/large_order_ratio/money_flow_strength)，Registry中还有5个PASS的(mf_momentum_div/net_mf_amount/big_small_div等)。但目前Active池中**0个资金流因子**。mf_divergence IC=9.1%是全项目最强因子。

### 发现5: 孤儿因子reversal_60

有601万行数据(2021-01~2025-12)，Registry #35 PASS (IC=2.7%, t=2.28)，但未归入任何池。可能是因为数据只到2025-12没有更新到最新。

---

## 5. 被冤杀因子正确框架重测方案

### 5.1 重测目标

| 优先级 | 因子 | 当前IC | 推荐框架 | 预期改善 | 工作量 |
|--------|------|--------|---------|---------|--------|
| **P0** | reversal_20 | 3.86% | FAST_RANKING(双周) | Sharpe可能+0.1~0.2(衰减60%→20%) | 0.5天(改run_backtest --freq biweekly) |
| **P0** | mf_divergence | 9.1% | LightGBM非线性 / EVENT | 因子IC极强,线性合成无法利用 | G1 LGBM已包含 |
| **P1** | vwap_bias_1d | 4.64% | FAST_RANKING(周度/双周) | 日频信号用月度框架严重不匹配 | 0.5天 |
| **P1** | rsrs_raw_18 | 3.71% | EVENT(阈值触发) | 阻力支撑突破是事件性信号 | 1天(需EventStrategy) |
| **P1** | earnings_surprise_car | 5.34% | EVENT(公告后20日) | 月度等权框架无法捕获PEAD漂移 | 1天 |
| **P2** | price_level_factor | 5.49% | RANKING/LGBM | IC强但未入Active,可能被corr拦截 | 0.5天验证 |
| **P2** | price_volume_corr_20 | 3.94% | RANKING | IR=0.64高，7/7年一致 | 0.5天验证 |

### 5.2 重测实验设计

**实验A: reversal_20双周调仓 (P0, 0.5天)**
```
python scripts/run_backtest.py --start 2021-01-01 --end 2026-03-31 --freq biweekly --top-n 15
```
对比: 月度 Sharpe=0.91 vs 双周 Sharpe=?
如果双周Sharpe > 月度+0.05 且 换手率增加的成本可接受 → 切换PT v1.3频率

**实验B: 6因子组合(+mf_divergence) 用LightGBM (P0, G1已包含)**
mf_divergence在等权线性组合中失败，但IC=9.1%。LightGBM可以学到mf_divergence与其他因子的非线性交互。G1 Walk-Forward设计已包含此因子。

**实验C: vwap_bias_1d + rsrs_raw_18 双周/周度回测 (P1, 1天)**
```
# 7因子(5Active + vwap + rsrs) 双周调仓
# 对比: 5因子月度 vs 7因子双周
```

**实验D: PEAD EVENT框架回测 (P1, 1天)**
需要EventStrategy已实现(engines/strategies/event_strategy.py存在)。
```
# earnings_surprise_car: 公告后买入，持有20日，到期卖出
# 独立子策略，不进主组合
```

### 5.3 未实现因子补全优先级

| 优先级 | 因子 | IC | 实现难度 | 依赖 |
|--------|------|-----|---------|------|
| **P0** | ATR_norm | 10.16% | 低(ta-lib 3行) | pip install ta-lib |
| **P0** | RSI_14 | 6.06% | 低(ta-lib) | 同上 |
| **P0** | IVOL | 6.67% | 中(需Fama-French残差) | index_daily |
| **P1** | CCI_14 | 4.69% | 低(ta-lib) | 同上 |
| **P1** | mf_momentum_divergence | 9.1% | 低(已有DIRECTION,缺calc函数) | moneyflow_daily |
| **P1** | gap_frequency | 5.95% | 低(open/pre_close计算) | klines_daily |
| **P2** | MACD_hist | 3.73% | 低(ta-lib) | 同上 |
| **P2** | KDJ_K | 3.73% | 低(ta-lib) | 同上 |
| **P2** | net_mf_amount | 4.90% | 低(直接取字段) | moneyflow_daily |
| **P2** | big_small_divergence | 3.75% | 中 | moneyflow_daily |

**估算**: P0因子补全约1.5天，P1约2天，P2约1天。总计4.5天可把因子池从37扩展到47+。

---

## 6. Layer 3暴力枚举评估

FACTOR_TEST_REGISTRY已有37个DB因子的数据。对这37个因子做全组合枚举:
- C(37,2) = 666个二元组合
- 每个组合跑5年IC → 约需10小时计算时间

**评估: 暂不建议做。** 原因:
1. 37个因子中有8个Deprecated(高冗余)，去掉后C(29,2)=406个
2. 但更重要的是先把11个PASS但未实现的因子补上 → 做C(48,2)=1128个更有价值
3. 优先级应该是: 补因子 → 跑单因子IC → 做Classifier分类 → 然后再枚举组合

---

## 7. 行动建议排序

| 序号 | 任务 | 预期收益 | 工作量 | 前置依赖 |
|------|------|---------|--------|---------|
| 1 | **实验A: reversal_20双周调仓** | Sharpe可能+0.1~0.2 | 0.5天 | 无(run_backtest已支持--freq) |
| 2 | **P0因子补全(ATR/RSI/IVOL)** | 3个IC>6%的强因子入池 | 1.5天 | pip install ta-lib |
| 3 | **12个ML因子跑单因子IC+半衰期** | 发现被遗漏的alpha | 1天 | 无 |
| 4 | **实验C: 7因子双周组合** | 验证vwap+rsrs增量 | 0.5天 | 任务1完成 |
| 5 | **G1 LightGBM(含mf_divergence)** | 非线性释放mf_div的IC=9.1% | 5天+ | G1设计已完成 |
| 6 | **P1因子补全(CCI/mf_mom_div/gap)** | 扩展因子池 | 2天 | 任务2完成 |
| 7 | **PEAD EVENT框架回测** | 独立子策略alpha | 1天 | EventStrategy |
| 8 | **全因子IC+半衰期批量计算** | Classifier输入 | 1天 | 任务2,6完成 |
| 9 | **Layer 3组合枚举** | 发现协同效应 | 2天 | 任务8完成 |

**最高ROI路径**: 任务1(0.5天) → 任务3(1天) → 任务2(1.5天) → 任务4(0.5天) = 3.5天可能把Sharpe从0.91提升到1.0+
