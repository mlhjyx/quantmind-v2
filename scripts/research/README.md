# scripts/research/ — 研究脚本索引

> 所有脚本为一次性研究用途，不在生产调度链路中。
> 按 Step 编号分组，最新在前。

---

## Step 6-H: SN 实盘化 + Regime + LightGBM (2026-04-10)

| 脚本 | 用途 | 结论 |
|------|------|------|
| `regime_size_neutral.py` | Regime动态beta vs static SN | static b=0.50 全面优于 dynamic/binary |
| `lgbm_17factor_wf.py` | LightGBM 17因子 Walk-Forward | OOS IC=0.067正但Sharpe=0.09, ML无效 |
| `prepare_ml_features.py` | LightGBM 特征工程准备 | 配合 lgbm_17factor_wf.py 使用 |
| `wf_size_neutral.py` | SN b=0.50 Walk-Forward OOS验证 | WF OOS Sharpe=0.6521, 唯一有效Modifier |

## Step 6-G: Modifier 层实验 (2026-04-10)

| 脚本 | 用途 | 结论 |
|------|------|------|
| `modifier_experiments.py` | Vol-targeting/DD-aware/组合Modifier | 3方案全部损alpha, Partial SN唯一有效 |
| `template11_modifier_backtest.py` | Template 11 Modifier回测 | Modifier层干预实验 |
| `template11_param_optimize.py` | Template 11 参数优化 | 参数敏感度分析 |
| `mdd_reduction_dual_modifier.py` | MDD降低双Modifier叠加 | 叠加更差, Modifier相互干扰 |

## Step 6-F: 因子替换 + Size-Neutral + 噪声鲁棒性 (2026-04-10)

| 脚本 | 用途 | 结论 |
|------|------|------|
| `factor_swap_paired_bootstrap.py` | 因子替换 paired bootstrap检验 | turnover_stability_20 p=0.92不显著 |
| `noise_robustness.py` | 因子噪声鲁棒性测试(G_robust) | 21因子全PASS, retention≥0.59@20% |
| `size_neutral_backtest.py` | Size-neutral不同b值回测 | b=0.50最优, b=1.0损11%Sharpe |

## Step 6-E: IC 基础设施 + Alpha 衰减 (2026-04-09)

| 脚本 | 用途 | 结论 |
|------|------|------|
| `regime_detection.py` | Regime线性检测(5指标) | 5指标全p>0.05, 线性方法无效 |
| `alpha_decay_attribution.py` | Alpha衰减归因分析 | 半衰期~6月, 需持续补充新因子 |

## Step 6-D: 12年 OOS + FF3 归因 (2026-04-09)

| 脚本 | 用途 | 结论 |
|------|------|------|
| `ff3_attribution.py` | Fama-French 3因子归因 | Alpha=+18.98%/年(t=2.90), SMB beta~1.09 |

## Earlier Research (Sprint 1.x)

| 脚本 | 用途 |
|------|------|
| `earnings_factor_calc.py` | 盈利公告因子计算 |
| `earnings_factor_explore.py` | 盈利公告因子探索 |
| `factor_pool_expansion.py` | 因子池扩展候选评估 |
| `factor_pool_ic_weighted.py` | IC加权因子组合实验 |
| `factor_pool_independence_screen.py` | 因子独立性筛选 |
| `paired_bootstrap_candidates.py` | 候选因子 paired bootstrap |
| `paired_bootstrap_top9.py` | Top-9候选因子验证 |
| `verify_factor_expansion.py` | 因子扩展效果验证 |
| `verify_phase1_isolation.py` | Phase 1加固隔离验证 |
| `verify_random_signal_bias.py` | 随机信号偏差检测 |
| `composite_dsr_improvement.py` | DSR改进组合策略 |
| `strategy_overlay_backtest.py` | 策略叠加回测 |
| `template12_analysis.py` | Template 12分析 |
| `backtest_vwap_bias_weekly.py` | VWAP偏差周度回测 |
| `pull_historical_data.py` | 历史数据拉取工具 |
