# FACTOR_TEST_REGISTRY — 因子测试注册表

> BH-FDR校正基础。每次测试新因子都追加记录。累积M = 总行数。
> IC方法: Spearman rank correlation(zscore, 5日前瞻超额收益 vs 沪深300)
> 数据范围: 2020-07-01 ~ 2026-03-23 (除特别注明)
> 维护规则: 新因子测试完成后，必须在此表追加一行，否则BH-FDR的M值失真。

---

## 累积统计

- **累积测试总数 M**: 213 (74原始 + 128 Alpha158批量 + 6 Alpha158用户定义 + 5 PEAD-SUE验证, 2026-04-11)
- **PASS**: 32 (原23 + 6 Alpha158六因子 + 3 PEAD-SUE)
- **FAIL**: 34 (原32 + 2 PEAD-SUE弱信号)
- **CONDITIONAL**: 6
- **REVERTED**: 3
- **INVALIDATED**: 1 (mf_momentum_divergence, v3.4证伪)
- **BLOCKED**: 2
- **DEPRECATED**: 5
- **NOT_TESTED**: 2
- **CANCELLED**: 2

---

## 注册表

| # | 因子名 | IC_mean | t-stat | p-value | 测试日期 | 批次 | 结果 | 原因 |
|---|--------|---------|--------|---------|----------|------|------|------|
| 1 | turnover_mean_20 | -0.0643 | -7.31 | <0.001 | 2026-03-20 | Phase0-原始18 | PASS | v1.1 Active因子, IR最高(-0.73), 7/7年方向一致 |
| 2 | volatility_20 | -0.0690 | -6.37 | <0.001 | 2026-03-20 | Phase0-原始18 | PASS | v1.1 Active因子, |IC|最大, 7/7年方向一致 |
| 3 | reversal_20 | +0.0386 | +3.50 | <0.001 | 2026-03-20 | Phase0-原始18 | PASS | v1.1 Active因子, 6/7年方向一致 |
| 4 | amihud_20 | +0.0215 | +2.69 | 0.008 | 2026-03-20 | Phase0-原始18 | PASS | v1.1 Active因子, 流动性因子 |
| 5 | bp_ratio | +0.0523 | +6.02 | <0.001 | 2026-03-20 | Phase0-原始18 | PASS | v1.1 Active因子, IC最强价值因子 |
| 6 | momentum_5 | -0.0273 | -3.10 | 0.002 | 2026-03-20 | Phase0-原始18 | PASS | Reserve, 6/7年方向一致, corr(reversal_20)=0.47 |
| 7 | momentum_10 | -0.0391 | -3.77 | <0.001 | 2026-03-20 | Phase0-原始18 | CONDITIONAL | Watch: |IC|=3.9%强但corr(reversal_20)=0.67接近阈值 |
| 8 | momentum_20 | -0.0395 | -3.57 | <0.001 | 2026-03-20 | Phase0-原始18 | DEPRECATED | corr(reversal_20)=1.00, 完全冗余(符号相反) |
| 9 | reversal_5 | +0.0273 | +3.10 | 0.002 | 2026-03-20 | Phase0-原始18 | PASS | Reserve, 6/7年方向一致, 短周期反转 |
| 10 | reversal_10 | +0.0391 | +3.77 | <0.001 | 2026-03-20 | Phase0-原始18 | CONDITIONAL | Watch: |IC|=3.9%强但corr(reversal_20)=0.67接近阈值 |
| 11 | volatility_60 | -0.0696 | -5.77 | <0.001 | 2026-03-20 | Phase0-原始18 | DEPRECATED | corr(volatility_20)=0.76, 长周期变体冗余 |
| 12 | turnover_std_20 | -0.0681 | -8.46 | <0.001 | 2026-03-20 | Phase0-原始18 | DEPRECATED | corr(turnover_mean_20)=0.91, 信息冗余 |
| 13 | ep_ratio | +0.0341 | +4.80 | <0.001 | 2026-03-20 | Phase0-原始18 | PASS | Reserve, 7/7年方向一致, NaN=22%需补数据 |
| 14 | ln_market_cap | -0.0308 | -2.09 | 0.038 | 2026-03-20 | Phase0-原始18 | PASS | Reserve, 6/7年方向一致, 独立性极好(corr=0.21) |
| 15 | price_volume_corr_20 | -0.0394 | -6.41 | <0.001 | 2026-03-20 | Phase0-原始18 | PASS | Reserve, 7/7年方向一致, IR=0.64高, 量价背离 |
| 16 | high_low_range_20 | -0.0746 | -6.53 | <0.001 | 2026-03-20 | Phase0-原始18 | DEPRECATED | corr(volatility_20)=0.89, 同一因子变体 |
| 17 | volume_std_20 | -0.0117 | -1.31 | 0.192 | 2026-03-20 | Phase0-原始18 | DEPRECATED | |IC|=1.2%<1.5%, 预测力不足 |
| 18 | dv_ttm | +0.0313 | +5.49 | <0.001 | 2026-03-21 | Batch1 | PASS | Reserve, |IC|=3.1%, IR=0.55, 7/7年稳定. NaN=33%需补数据 |
| 19 | IVOL (ivol_20) | **-0.0667** | — | — | 2026-03-21 / 修正 2026-04-09 | Batch1 | PASS (方向-1) | Step 6-E 修正: 原记录 `+0.0667` 是 `\|IC\|` 未含符号, 实测 factor_ic_history avg_ic_20d=-0.1033. **方向-1 (IVOL puzzle: 高特质波动→低未来收益)**. 跟 volatility_20 高相关, 不建议独立入池 |
| 20 | turnover_surge_ratio | -0.0250 | -3.93 | <0.001 | 2026-03-21 | Batch1 | PASS | Reserve, |IC|=2.5%(后验3.57%), 7/7年稳定 |
| 21 | roe_stability | +0.0150 | — | — | 2026-03-21 | Batch1 | FAIL | |IC|=1.50%, 低于入池门槛, 预测力不足 |
| 22 | roe_ttm | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 23 | revenue_growth | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 24 | net_profit_growth | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 25 | current_ratio | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 26 | debt_to_equity | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 27 | operating_cashflow_ratio | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 28 | asset_turnover | — | — | — | 2026-03-21 | Batch1-否决 | FAIL | 数据覆盖不足或IC不显著 |
| 29 | kbar_body_ratio | +0.0096 | — | — | 2026-03-22 | Batch2 | FAIL | |IC|=0.96%, 低于入池门槛 |
| 30 | analyst_surprise | +0.0052 | — | — | 2026-03-22 | Batch2 | FAIL | |IC|=0.52%, 低于入池门槛 |
| 31 | net_profit_yoy | -0.0174 | — | — | 2026-03-22 | Batch2 | FAIL | |IC|=-1.74%, 方向反直觉, 不稳定 |
| 32 | accrual_anomaly | — | — | — | 2026-03-22 | Batch2 | BLOCKED | 数据依赖blocked(需cash_flow表) |
| 33 | turnover_surge (验证) | -0.0357 | — | — | 2026-03-22 | Batch2 | PASS | 二次验证|IC|=3.57%, 确认通过 |
| 34 | price_level_factor | +0.0549 | +4.99 | <0.001 | 2026-03-22 | Batch3 | PASS | Reserve Tier1, |IC|=5.5%(报告8.42%), 7/7年稳定 |
| 35 | reversal_60 | +0.0270 | +2.28 | 0.024 | 2026-03-22 | Batch3 | PASS | Reserve, |IC|=2.7%(报告4.05%), 5/5年方向一致 |
| 36 | large_cap_low_vol | — | — | — | 2026-03-22 | Batch3 | FAIL | 与基线冗余, 独立信息不足 |
| 37 | turnover_vol_ratio | — | — | >0.05 | 2026-03-22 | Batch3 | FAIL | IC不显著(ns) |
| 38 | volume_mom_divergence | — | — | >0.05 | 2026-03-22 | Batch3 | FAIL | IC不显著(ns) |
| 39 | relative_volume_20 | -0.0280 | -3.94 | <0.001 | 2026-03-22 | Batch4 | PASS | Reserve, |IC|=2.8%(报告6.00%), 7/7年方向一致 |
| 40 | gap_frequency | +0.0595 | — | — | 2026-03-22 | Batch4 | PASS | |IC|=5.95%, 通过筛选 |
| 41 | return_consistency | -0.0287 | — | — | 2026-03-22 | Batch4 | FAIL | |IC|=-2.87%, 方向反直觉或不稳定 |
| 42 | turnover_skewness | — | — | >0.05 | 2026-03-22 | Batch4 | FAIL | IC不显著(ns) |
| 43 | mf_momentum_divergence | ~~+0.0910~~ **-0.0227** | — | — | 2026-03-22 / 修正 2026-04-10 | Batch5 | **INVALIDATED** | 原始IC=+9.1%为raw_value虚高, 中性化后IC=-2.27%. 14组回测全负. v3.4证伪(GA2). 见CLAUDE.md已知失败方向 |
| 44 | net_mf_amount | +0.0490 | — | — | 2026-03-22 | Batch5 | PASS | |IC|=4.9%, 净资金流 |
| 45 | big_order_ratio | — | — | — | 2026-03-22 | Batch5 | REVERTED | 方向反转: 大单占比方向与预期相反 |
| 46 | big_small_divergence | +0.0375 | — | — | 2026-03-23 | Batch5b | PASS | |IC|=3.75%, 大小单分歧度 |
| 47 | mf_volatility | +0.0204 | — | — | 2026-03-23 | Batch5b | CONDITIONAL | |IC|=2.04%, 边界通过, 需观察稳定性 |
| 48 | mf_persistence | — | — | >0.05 | 2026-03-23 | Batch5b | FAIL | IC不显著(ns) |
| 49 | big_small_consensus | -0.0100 | — | — | 2026-03-23 | Batch6 | REVERTED | 虚假alpha: 原始IC=12.74%, 中性化后→-1.0% (LL-014) |
| 50 | mf_price_vol_ratio | — | — | — | 2026-03-23 | Batch6 | REVERTED | 波动率proxy: 中性化后IC大幅衰减 (LL-014) |
| 51 | elg_ratio_change | +0.0248 | — | — | 2026-03-23 | Batch6 | CONDITIONAL | |IC|=2.48%, 边界因子, 需更多验证 |
| 52 | mf_concentration | +0.0159 | — | — | 2026-03-23 | Batch6 | CONDITIONAL | |IC|=1.59%, 勉强过1.5%门槛, 观察 |
| 53 | net_big_momentum | — | — | >0.05 | 2026-03-23 | Batch6 | FAIL | IC不显著(ns) |
| 54 | GPA | -0.0380 | -2.95 | 0.004 | 2026-03-22 | 研究否决 | FAIL | A股方向反转(-0.038), 中性化后IC=-0.011(p=0.14), 行业proxy非alpha |
| 55 | revenue_accel | — | — | — | 2026-03-22 | 研究否决 | FAIL | 不入库, 数据质量/覆盖不足 |
| 56 | roe_change_q | — | — | — | 2026-03-22 | 研究否决 | FAIL | 不入库, 数据质量/覆盖不足 |
| 57 | earnings_surprise_car | +0.0534 | — | — | 2026-03-23 | PEAD | PASS | |IC|=5.34%, 盈利惊喜CAR. **方向修正**: A股PEAD为反转效应(direction=-1), 非美股式正漂移. 详见#83-87 SUE验证 |
| 58 | earnings_revision | — | — | >0.05 | 2026-03-23 | PEAD | FAIL | IC不显著(ns) |
| 59 | ann_date_proximity | — | — | >0.05 | 2026-03-23 | PEAD | FAIL | IC不显著(ns) |
| 60 | RSI_14 | -0.0606 | — | — | 2026-03-23 | TA-Lib | PASS | |IC|=6.06%, 超卖信号 |
| 61 | MACD_hist | +0.0373 | — | — | 2026-03-23 | TA-Lib | PASS | |IC|=3.73%, 趋势动量 |
| 62 | KDJ_K | -0.0373 | — | — | 2026-03-23 | TA-Lib | PASS | |IC|=3.73%, 随机指标 |
| 63 | CCI_14 | -0.0469 | — | — | 2026-03-23 | TA-Lib | PASS | |IC|=4.69%, 商品通道指数 |
| 64 | ATR_norm | -0.1016 | — | — | 2026-03-23 | TA-Lib | PASS | |IC|=10.16%, 归一化真实波幅, IC最强TA因子 |
| 65 | turnover_surge (Batch2验证) | -0.0357 | — | — | 2026-03-22 | Batch2-验证 | PASS | 重复验证条目(见#33), 不计入独立测试 |
| 66 | LightGBM-5feat (基线5因子) | IC=0.0823 | — | 0.073 | 2026-03-25 | ML-Sprint1.4b | FAIL | OOS Sharpe=0.869<1.10, p=0.073>0.05, 4连亏月 |
| 67 | LightGBM-top8-shap | IC=0.0493 | — | — | 2026-03-25 | ML-Sprint1.4b | FAIL | F1 OOS IC劣于5基线(4.93% vs 7.06%), 未跑7-fold |
| 68 | LightGBM-top5-shap | IC=0.0614 | — | — | 2026-03-25 | ML-Sprint1.4b | FAIL | F1 OOS IC劣于5基线(6.14% vs 7.06%), 未跑7-fold |
| 69 | LightGBM-5feat-optuna | IC=0.0844 | — | — | 2026-03-25 | ML-Sprint1.4b | FAIL | OOS IC +2.5%但ICIR -1.7%, 与默认无显著差异 |
| 70 | LightGBM-topK-optuna | — | — | — | 2026-03-25 | ML-Sprint1.4b | CANCELLED | SHAP筛选后5基线完胜, 无需跑 |
| 71 | LightGBM-17feat | IC=0.0478 | — | — | 2026-03-25 | ML-Sprint1.4b | FAIL | F1 OOS IC=4.78%劣于5基线7.06%, best_iter=2(噪声) |
| 72 | LightGBM-17feat-optuna | — | — | — | 2026-03-25 | ML-Sprint1.4b | CANCELLED | 17特征SHAP确认为噪声, 无需跑 |
| 73 | vwap_bias_1d | -0.0464 | -2.69 | 0.009 | 2026-03-25 | Sprint1.6-VWAP | PASS | 中性化IC=-0.0349 t=-3.53, ICIR=-0.43, 66月全样本, max_corr=0.36(turnover), 反转效应 |
| 74 | rsrs_raw_18 | -0.0371 | -3.99 | <0.001 | 2026-03-25 | Sprint1.6-RSRS | PASS | 中性化IC=-0.0301 t=-4.35, ICIR=-0.54, 66月全样本, max_corr=0.27(volatility), 阻力支撑 |
| 75 | ind_mom_20 | -0.0308 | -11.32 | <0.001 | 2026-04-10 | Phase1.2-IndMom | PASS | SW1行业20日动量, direction=-1(A股行业反转效应), ICIR=-0.218, hit=42.9%, 不推荐独立入池: 与reversal_20 IC时序相关性0.539超过0.5冗余阈值 |
| 76 | ind_mom_60 | -0.0347 | -12.91 | <0.001 | 2026-04-10 | Phase1.2-IndMom | PASS | SW1行业60日动量, direction=-1(A股行业反转效应), ICIR=-0.249, hit=40.1%, max_core_corr=0.286(reversal_20), **推荐E2E特征池** |
| 77 | RSQR_20 | +0.0515 | +22.19 | <0.001 | 2026-04-11 | Phase1.2-A158Six | PASS | CAPM式R²(stock~market rolling 20d), direction=+1(高R²=机构重仓), ICIR=+0.409, hit=67.7%, max_core_corr=0.348(bp_ratio), **推荐E2E特征池(独立)** |
| 78 | QTLU_20 | -0.0823 | -29.24 | <0.001 | 2026-04-11 | Phase1.2-A158Six | PASS | 收益率75th分位(rolling 20d), direction=-1(右尾过度乐观), ICIR=-0.539, hit=30.9%, max_core_corr=0.673(turnover_mean_20), **推荐E2E特征池(borderline独立)** |
| 79 | IMAX_20 | -0.0904 | -35.55 | <0.001 | 2026-04-11 | Phase1.2-A158Six | PASS | 窗口内最大日收益率(rolling 20d), direction=-1(彩票偏好), ICIR=-0.656, hit=25.2%, max_core_corr=0.760(volatility_20), 冗余不推荐独立入池 |
| 80 | IMIN_20 | +0.0481 | +15.31 | <0.001 | 2026-04-11 | Phase1.2-A158Six | PASS | 窗口内最小日收益率(rolling 20d), direction=+1(深跌均值回归), ICIR=+0.282, hit=63.2%, max_core_corr=0.733(volatility_20), 冗余不推荐独立入池 |
| 81 | CORD_20 | -0.0447 | -16.63 | <0.001 | 2026-04-11 | Phase1.2-A158Six | PASS | close-time相关性(rolling 20d), direction=-1(趋势反转), ICIR=-0.307, hit=39.4%, max_core_corr=0.740(reversal_20), 冗余不推荐独立入池 |
| 82 | RESI_20 | -0.0681 | -25.29 | <0.001 | 2026-04-11 | Phase1.2-A158Six | PASS | CAPM回归截距/alpha(rolling 20d), direction=-1(跑输→均值回归), ICIR=-0.466, hit=33.2%, max_core_corr=0.817(reversal_20), 冗余不推荐独立入池 |
| 83 | sue_all (PEAD验证) | -0.0340 | -12.90 | <0.001 | 2026-04-11 | Phase1.2-PEAD | PASS | SUE全报告类型(154K事件), direction=-1(A股反转效应), 5d/10d/20d IC均显著, 非独立测试(#57验证) |
| 84 | sue_q3 (PEAD验证) | -0.0980 | -19.40 | <0.001 | 2026-04-11 | Phase1.2-PEAD | PASS | **最强PEAD信号**: Q3报告×10d IC=-0.098(t=-19.4), direction=-1(利空出尽效应), 38645事件, **推荐E2E特征池** |
| 85 | sue_y (PEAD验证) | -0.0410 | -7.50 | <0.001 | 2026-04-11 | Phase1.2-PEAD | PASS | 年报SUE, direction=-1, 全持有期显著(t>6), 33725事件 |
| 86 | sue_q1 (PEAD验证) | -0.0080 | -1.60 | 0.110 | 2026-04-11 | Phase1.2-PEAD | FAIL | Q1报告SUE信号弱, 10d IC=-0.008(t=-1.6不显著), 36708事件 |
| 87 | sue_h1 (PEAD验证) | -0.0090 | -1.70 | 0.090 | 2026-04-11 | Phase1.2-PEAD | FAIL | H1(半年报)SUE信号弱, 20d IC=-0.009(t=-1.7不显著), 37828事件 |

---

## 使用说明

### BH-FDR校正

当前累积M = 88（排除重复验证条目#65 + 2个CANCELLED, 包含#77-82 Alpha158六因子 + #83-87 PEAD-SUE验证）。

BH-FDR校正步骤:
1. 对所有M个p-value排序: p_(1) <= p_(2) <= ... <= p_(M)
2. 对第k个因子，校正阈值 = alpha * k / M
3. 找到最大的k使得 p_(k) <= alpha * k / M
4. 所有排名 <= k 的因子通过FDR校正

### 结果编码

| 结果 | 含义 |
|------|------|
| **PASS** | IC显著, 方向合理, 可入Reserve/Active池 |
| **FAIL** | IC不显著 / 方向异常 / 数据不足 |
| **CONDITIONAL** | 边界通过, 需进一步验证或特殊条件下可用 |
| **REVERTED** | 初始通过后发现问题(如中性化后衰减/方向反转)被撤回 |
| **INVALIDATED** | 经深入验证证伪(如raw IC虚高, 中性化后IC方向反转, 回测全负) |
| **BLOCKED** | 数据依赖未满足, 无法测试 |
| **DEPRECATED** | 与已有因子高度冗余(corr>0.7), 建议停止计算 |
| **NOT_TESTED** | 已提出但尚未实际运行IC测试 |

### 维护规则

1. **每次新因子IC测试完成后**, 必须在此表追加一行
2. **REVERTED因子**保留记录(不删除), 作为"已尝试"的证据
3. **重复验证**标注为"验证"批次, 不计入独立测试计数M
4. **p-value缺失的因子**(标记为—), 在BH-FDR计算中使用IC_mean的近似p-value
5. 配合 `backend/engines/config_guard.py` 中的 `get_cumulative_test_count()` 自动读取M值
