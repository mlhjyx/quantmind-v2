# 北向资金市场级MODIFIER因子V2研究报告

> 生成时间: 2026-04-05
> 训练期: 2021-01-01~2023-12-31 | OOS: 2024-01-01~2025-12-31
> 因子数: 15个

## 1. 因子定义

| # | 因子 | 含义 |
|---|------|------|
| 1 | nb_breadth_ratio | 买入股票数/卖出股票数 — 广度而非金额 |
| 2 | nb_buy_concentration | 净买入HHI — 集中少数股=有观点,分散=被动 |
| 3 | nb_asymmetry | 买入力度/卖出力度 — >1积极做多,<1积极出逃 |
| 4 | nb_turnover | 北向换仓率 — 净流入为0但活跃调仓也有信息 |
| 5 | nb_contrarian_market_5d | 5日逆势买入强度 — 市场跌+北向买=可能反弹 |
| 6 | nb_size_shift_20d | 北向市值偏好变化 — 大盘→小盘或小盘→大盘 |
| 7 | nb_extreme_outflow | 极端流出(P5) — 恐慌底部信号 |
| 8 | nb_extreme_inflow | 极端流入(P95) — 过热顶部信号 |
| 9 | nb_vol_change | 北向波动率突变 — 不确定性指标 |
| 10 | nb_streak_reversal | 连续流入/流出后反转 — 直接利用'反向指标'发现 |
| 11 | nb_sh_sz_divergence | 沪股通vs深股通分歧 — 大盘蓝筹vs中小创分歧 |
| 12 | nb_industry_rotation | 行业轮动强度 — 行业间调仓活跃度 |
| 13 | nb_active_share | 北向vs CSI300偏离度 — 主动选股vs被动配置 |
| 14 | nb_reverse_percentile | 反向百分位 — 直接翻转V1的百分位因子 |
| 15 | nb_momentum_divergence | 北向流入vs市场动量背离 — 同向减弱/反向增强 |

## 2. 训练期信号质量 (2021-2023)

| 因子 | 最优horizon | 最优corr | t_stat | Q1收益% | Q5收益% | 单调性 | 稳定性 |
|------|-----------|---------|--------|---------|---------|--------|--------|
| nb_asymmetry | 60d | -0.1132 | -2.87 | -1.75 | -1.42 | 0.5 | 0.32 |
| nb_contrarian_market_5d | 60d | -0.1095 | -2.8 | -0.33 | -1.44 | 0.5 | 0.43 |
| nb_active_share | 60d | +0.0887 | 2.26 | -1.89 | -1.49 | 0.25 | 0.45 |
| nb_sh_sz_divergence | 20d | -0.0881 | -2.32 | 0.51 | -0.61 | 0.5 | 0.47 |
| nb_vol_change | 1d | -0.0856 | -2.28 | -1.3 | -1.71 | 0.5 | 0.27 |
| nb_industry_rotation | 5d | +0.0811 | 2.15 | -1.29 | -1.31 | 0.25 | 0.57 |
| nb_turnover | 60d | -0.0801 | -2.04 | -1.16 | -1.77 | 0.5 | 0.48 |
| nb_momentum_divergence | 10d | -0.0776 | -2.05 | -1.64 | -1.34 | 0.5 | 0.32 |
| nb_extreme_inflow | 1d | -0.0770 | -2.05 | ? | ? | ? | 0.26 |
| nb_buy_concentration | 10d | -0.0559 | -1.47 | -1.17 | -1.85 | 0.25 | 0.24 |
| nb_reverse_percentile | 5d | +0.0466 | 1.23 | -1.4 | -1.12 | 0.75 | 0.66 |
| nb_streak_reversal | 60d | +0.0444 | 1.13 | -1.55 | -1.07 | 0.5 | 0.61 |
| nb_size_shift_20d | 10d | -0.0391 | -1.02 | -0.69 | -1.19 | 0.5 | 0.37 |
| nb_breadth_ratio | 10d | +0.0234 | 0.62 | -1.48 | -1.54 | 0.75 | 0.37 |
| nb_extreme_outflow | 60d | +0.0199 | 0.5 | ? | ? | ? | 0.52 |

## 3. OOS验证 (2024-2025)

| 因子 | 最优horizon | OOS corr | OOS t | 训练corr | 方向一致 |
|------|-----------|---------|-------|---------|---------|
| nb_size_shift_20d | 60d | -0.3043 | -2.96 | -0.0391 | Yes |
| nb_breadth_ratio | 20d | -0.2062 | -4.43 | +0.0234 | No |
| nb_turnover | 60d | -0.1815 | -3.7 | -0.0801 | Yes |
| nb_industry_rotation | 10d | -0.1706 | -3.68 | +0.0811 | No |
| nb_momentum_divergence | 60d | +0.1686 | 3.43 | -0.0776 | No |
| nb_contrarian_market_5d | 60d | +0.1640 | 3.33 | -0.1095 | No |
| nb_vol_change | 5d | -0.1512 | -3.27 | -0.0856 | Yes |
| nb_active_share | 60d | -0.1427 | -2.89 | +0.0887 | No |
| nb_asymmetry | 10d | -0.1263 | -1.52 | -0.1132 | Yes |
| nb_reverse_percentile | 5d | +0.1166 | 2.51 | +0.0466 | Yes |
| nb_buy_concentration | 20d | -0.1144 | -1.32 | -0.0559 | Yes |
| nb_extreme_outflow | 60d | -0.0890 | -1.79 | +0.0199 | No |
| nb_sh_sz_divergence | 1d | -0.0682 | -1.47 | -0.0881 | Yes |
| nb_extreme_inflow | 10d | +0.0613 | 1.3 | -0.0770 | No |
| nb_streak_reversal | 60d | +0.0576 | 1.16 | +0.0444 | Yes |

## 4. 仓位调节回测 (有效因子, 全期)

| 策略 | Sharpe | MDD% | CAGR% | 平均仓位 | 减仓天数 |
|------|--------|------|-------|---------|---------|
| 满仓CSI300 | -0.046 | -45.6 | -2.43 | 1.0 | 0 |
| MODIFIER(nb_buy_concentration) | -0.542 | -36.15 | -8.07 | 0.756 | 494 |
| MODIFIER(nb_asymmetry) | -0.786 | -42.8 | -10.97 | 0.748 | 471 |
| MODIFIER(nb_turnover) | -0.029 | -41.7 | -1.62 | 0.818 | 442 |
| MODIFIER(nb_size_shift_20d) | -0.759 | -37.79 | -10.57 | 0.761 | 463 |
| MODIFIER(nb_vol_change) | 0.134 | -37.31 | 0.9 | 0.8 | 454 |
| MODIFIER(nb_streak_reversal) | -0.382 | -42.93 | -5.55 | 0.648 | 810 |
| MODIFIER(nb_sh_sz_divergence) | 0.095 | -36.44 | 0.29 | 0.801 | 433 |
| MODIFIER(nb_reverse_percentile) | -0.285 | -47.25 | -5.12 | 0.808 | 519 |

## 5. 结论

- 训练期+OOS双验证通过(方向一致且|corr|>0.03): **8个因子**
- 有效因子: nb_buy_concentration, nb_asymmetry, nb_turnover, nb_size_shift_20d, nb_vol_change, nb_streak_reversal, nb_sh_sz_divergence, nb_reverse_percentile

### vs V1对比
- V1(4因子): 信号方向反向(corr=-0.093), 无法做择时
- V2(15因子): 从行为模式/极端事件/跨板块等维度挖掘, 8个因子通过OOS验证