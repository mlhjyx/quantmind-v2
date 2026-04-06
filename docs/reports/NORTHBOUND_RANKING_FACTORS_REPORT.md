# 北向资金个股RANKING因子研究报告

> 生成时间: 2026-04-05
> 数据范围: 2021-01-01 ~ 2025-12-31
> 因子数量: 15个候选

## 1. 因子IC汇总

| 因子 | IC均值 | t统计量 | 正IC占比 | 月数 | 状态 |
|------|--------|---------|----------|------|------|
| nb_increase_ratio_20d | -0.0362 | -2.82 | 41% | 54 | **Active** |
| nb_new_entry | -0.0132 | -2.43 | 43% | 42 | **Active** |
| nb_contrarian | -0.0134 | -2.11 | 42% | 60 | **Active** |
| nb_consecutive_increase | -0.0168 | -1.53 | 45% | 49 | Weak |
| nb_concentration_signal | -0.0065 | -1.49 | 42% | 60 | Weak |
| nb_net_buy_ratio | +0.0090 | 1.10 | 59% | 49 | Weak |
| nb_rank_change_20d | +0.0073 | 0.94 | 53% | 60 | Rejected |
| nb_net_buy_5d_ratio | +0.0052 | 0.78 | 49% | 49 | Rejected |
| nb_net_buy_20d_ratio | +0.0032 | 0.37 | 48% | 54 | Rejected |
| nb_ratio_change_20d | -0.0021 | -0.25 | 47% | 60 | Rejected |
| nb_change_excess | -0.0021 | -0.25 | 47% | 60 | Rejected |
| nb_acceleration | +0.0010 | 0.16 | 45% | 60 | Rejected |
| nb_change_rate_20d | +0.0009 | 0.10 | 52% | 54 | Rejected |
| nb_trend_20d | -0.0000 | -0.00 | 49% | 53 | Rejected |
| nb_ratio_change_5d | +0.0000 | 0.00 | 50% | 60 | Rejected |

## 2. 筛选结果

- **Active** (|t|>=2.0): 3个 — nb_increase_ratio_20d, nb_new_entry, nb_contrarian
- **Weak** (1.0<=|t|<2.0): 3个 — nb_consecutive_increase, nb_concentration_signal, nb_net_buy_ratio
- **Rejected** (|t|<1.0): 9个

## 3. 因子经济机制

| 因子 | 方向 | 经济机制 |
|------|------|----------|
| nb_ratio_change_5d | + | 外资5日增持→正面信息尚未反映→预测上涨 |
| nb_ratio_change_20d | + | 外资20日持续增持→中期趋势性看好→预测上涨 |
| nb_change_rate_20d | + | 外资持仓相对变化率→小基数翻倍比大基数微增信息量大→预测上涨 |
| nb_consecutive_increase | + | 外资连续增持天数→持续性买入=conviction强→预测上涨 |
| nb_increase_ratio_20d | + | 20日中增持天数占比→一致性增持信号→预测上涨 |
| nb_trend_20d | + | 持仓线性趋势斜率→趋势性增持=机构持续建仓→预测上涨 |
| nb_change_excess | + | 个股增持超额(去市场中位数)→被外资偏爱→预测上涨 |
| nb_rank_change_20d | + | 持仓比例排名变化→相对其他股票被增持更多→预测上涨 |
| nb_net_buy_ratio | + | 日均净买入额/流通市值→资金流入强度→预测上涨 |
| nb_net_buy_5d_ratio | + | 5日累计净买入额/流通市值→短期资金涌入→预测上涨 |
| nb_net_buy_20d_ratio | + | 20日累计净买入额/流通市值→中期资金流入→预测上涨 |
| nb_contrarian | + | 北向增持×股价下跌→外资逆势买入=信息优势→预测反弹 |
| nb_acceleration | + | 持仓变化加速度→增持在加速=信心增强→预测上涨 |
| nb_new_entry | + | 外资从0→有持仓→首次关注=新信息→预测上涨(EVENT类) |
| nb_concentration_signal | + | 持仓比例从低于中位数升到高于→集中买入→预测上涨 |

## 4. 结论

发现3个IC显著的北向RANKING因子。
这些因子基于外资机构的个股选择行为，可能与量价因子低相关，
值得进一步验证与现有5核心因子的增量贡献。