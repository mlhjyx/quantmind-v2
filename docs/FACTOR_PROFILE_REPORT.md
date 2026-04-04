# 因子画像汇总报告 (2026-04-05)

- Forward return方法: close[T+1] → close[T+h]
- 数据范围: 2021-01-01 ~ 2025-12-31
- Universe: 排除ST/停牌, 与load_universe()对齐
- 超额基准: CSI300同期收益

## 一、多周期IC（按|IC_20d|降序，t<2.0标⚠️）

因子                       IC_1d(t)   IC_5d(t)  IC_10d(t)  IC_20d(t)  IC_60d(t)   最优    IR   胜率       趋势
--------------------------------------------------------------------------------------------------------------
atr_norm_20            +0.000(0.0)⚠️ -0.094(-3.2) -0.088(-3.8) -0.104(-4.5) -0.122(-6.5)  60d -0.58 100%   stable
ivol_20                +0.000(0.0)⚠️ -0.082(-3.4) -0.082(-4.4) -0.102(-5.1) -0.119(-7.2)  60d -0.66 100%   stable
turnover_mean_20       +0.000(0.0)⚠️ -0.058(-4.6) -0.069(-6.7) -0.099(-8.9) -0.132(-15.6)  60d -1.15 100%   stable
turnover_stability_20  +0.000(0.0)⚠️ -0.060(-5.3) -0.070(-7.4) -0.099(-9.5) -0.128(-15.2)  60d -1.23 100%   stable
gap_frequency_20       +0.000(0.0)⚠️ -0.078(-3.3) -0.077(-4.3) -0.098(-5.3) -0.110(-7.3)  60d -0.69 100%   stable
volatility_20          +0.000(0.0)⚠️ -0.066(-4.4) -0.072(-5.8) -0.095(-7.9) -0.114(-10.6)  60d -1.01 100%   stable
maxret_20              +0.000(0.0)⚠️ -0.054(-3.7) -0.064(-5.8) -0.087(-9.1) -0.093(-10.3)  60d -1.21 100%   stable
turnover_std_20        +0.000(0.0)⚠️ -0.046(-4.2) -0.054(-5.9) -0.080(-7.8) -0.114(-13.6)  60d -1.04 100% improving
high_low_range_20      +0.000(0.0)⚠️ -0.060(-3.6) -0.059(-4.5) -0.080(-5.8) -0.107(-8.8)  60d -0.78 100%   stable
volatility_60          +0.000(0.0)⚠️ -0.055(-3.1) -0.052(-3.8) -0.079(-5.5) -0.113(-9.8)  60d -0.73 100%   stable
ln_market_cap          +0.000(0.0)⚠️ -0.022(-1.2)⚠️ -0.053(-2.7) -0.065(-3.4) -0.102(-5.1)  60d -0.44 100%   stable
bp_ratio               +0.000(0.0)⚠️ +0.051(4.4) +0.048(4.8) +0.064(6.4) +0.089(11.0)  60d +0.83 100%   stable
amihud_20              +0.000(0.0)⚠️ +0.019(1.7)⚠️ +0.040(3.8) +0.060(5.7) +0.087(8.2)  60d +0.74 100%   stable
price_volume_corr_20   +0.000(0.0)⚠️ -0.033(-4.4) -0.041(-6.1) -0.056(-7.1) -0.062(-7.7)  60d -0.92 100% improving
a158_cord30            +0.000(0.0)⚠️ -0.032(-4.3) -0.036(-5.6) -0.053(-7.2) -0.057(-7.8)  60d -0.93 100%   stable
reversal_20            +0.000(0.0)⚠️ +0.034(2.8) +0.046(4.2) +0.051(4.7) +0.044(4.3)  20d +0.61 100%   stable
momentum_20            +0.000(0.0)⚠️ -0.036(-2.8) -0.045(-4.1) -0.047(-4.4) -0.039(-3.7)  20d -0.57 100%   stable
price_level_factor     +0.000(0.0)⚠️ +0.052(3.8) +0.043(3.5) +0.047(3.9) +0.072(6.0)  60d +0.51 100% decaying
large_order_ratio      +0.000(0.0)⚠️ -0.028(-3.4) -0.026(-3.4) -0.044(-5.4) -0.045(-5.0)  60d -0.72 100% improving
rsrs_raw_18            +0.000(0.0)⚠️ -0.038(-4.5) -0.035(-4.9) -0.043(-6.1) -0.051(-8.1)  60d -0.79 100% improving
kbar_kup               +0.000(0.0)⚠️ -0.027(-3.1) -0.032(-4.8) -0.042(-6.2) -0.052(-10.0)  60d -0.83 100%   stable
a158_vsump60           +0.000(0.0)⚠️ -0.031(-4.3) -0.034(-5.0) -0.040(-5.9) -0.043(-7.3)  60d -0.78 100%   stable
a158_corr5             +0.000(0.0)⚠️ -0.023(-3.7) -0.025(-4.3) -0.039(-6.7) -0.040(-8.5)  60d -0.86 100%   stable
reversal_60            +0.000(0.0)⚠️ +0.018(1.3)⚠️ +0.024(1.9)⚠️ +0.039(2.8) +0.046(4.5)  60d +0.37 100%   stable
a158_std60             +0.000(0.0)⚠️ -0.025(-1.5)⚠️ -0.025(-1.7)⚠️ -0.038(-2.8) -0.052(-5.3)  60d -0.37 100%   stable
relative_volume_20     +0.000(0.0)⚠️ -0.035(-4.2) -0.041(-5.0) -0.037(-4.8) -0.037(-5.4)  10d -0.62 100%   stable
momentum_10            +0.000(0.0)⚠️ -0.030(-2.5) -0.032(-2.9) -0.037(-3.7) -0.037(-4.1)  20d -0.48 100%   stable
reversal_10            +0.000(0.0)⚠️ +0.030(2.5) +0.032(2.9) +0.037(3.7) +0.037(4.1)  20d +0.48 100%   stable
dv_ttm                 +0.000(0.0)⚠️ +0.014(1.8)⚠️ +0.018(2.5) +0.036(4.4) +0.050(5.4)  60d +0.57 100%   stable
ep_ratio               +0.000(0.0)⚠️ +0.025(2.8) +0.027(3.4) +0.036(4.3) +0.049(5.4)  60d +0.56 100%   stable
gain_loss_ratio_20     +0.000(0.0)⚠️ -0.032(-2.7) -0.040(-3.7) -0.035(-3.2) -0.031(-2.8)  10d -0.43 100% improving
momentum_5             +0.000(0.0)⚠️ -0.038(-3.2) -0.030(-3.2) -0.033(-4.2) -0.024(-3.0)   5d -0.54 100%   stable
reversal_5             +0.000(0.0)⚠️ +0.038(3.2) +0.030(3.2) +0.033(4.2) +0.024(3.0)   5d +0.54 100%   stable
mf_divergence          +0.000(0.0)⚠️ -0.008(-1.2)⚠️ -0.016(-2.6) -0.028(-4.5) -0.033(-6.0)  60d -0.60 100% improving
money_flow_strength    +0.000(0.0)⚠️ +0.003(0.4)⚠️ +0.012(1.8)⚠️ +0.027(3.8) +0.028(4.6)  60d +0.50 100%   stable
turnover_surge_ratio   +0.000(0.0)⚠️ -0.023(-3.1) -0.024(-3.6) -0.023(-3.5) -0.024(-4.0)  60d -0.45 100% improving
chmom_60_20            +0.000(0.0)⚠️ -0.014(-1.3)⚠️ -0.012(-1.2)⚠️ -0.022(-2.1) -0.019(-2.4)  20d -0.28 100%   stable
stoch_rsv_20           +0.000(0.0)⚠️ -0.025(-2.2) -0.026(-2.6) -0.020(-2.0) -0.018(-1.9)⚠️  10d -0.27 100% improving
volume_std_20          +0.000(0.0)⚠️ +0.003(0.2)⚠️ -0.010(-1.1)⚠️ -0.020(-2.0)⚠️ -0.012(-1.3)⚠️  20d -0.27 100% improving
up_days_ratio_20       +0.000(0.0)⚠️ -0.016(-1.7)⚠️ -0.022(-2.4) -0.018(-2.1) -0.022(-2.5)  10d -0.28 100% improving
beta_market_20         +0.000(0.0)⚠️ -0.024(-1.7)⚠️ -0.012(-1.2)⚠️ -0.016(-1.5)⚠️ -0.007(-0.7)⚠️   5d -0.20 100%   stable
a158_rank5             +0.000(0.0)⚠️ -0.020(-2.2) -0.017(-2.0)⚠️ -0.013(-1.4)⚠️ -0.006(-0.7)⚠️   5d -0.18 100% improving
kbar_kmid              +0.000(0.0)⚠️ -0.025(-1.8)⚠️ -0.022(-2.4) -0.012(-1.3)⚠️ -0.011(-1.2)⚠️   5d -0.17 100%   stable
a158_vsump5            +0.000(0.0)⚠️ -0.021(-3.6) -0.012(-2.2) -0.011(-2.0)⚠️ -0.004(-0.9)⚠️   5d -0.26 100%   stable
vwap_bias_1d           +0.000(0.0)⚠️ -0.025(-2.1) -0.018(-2.5) -0.011(-1.3)⚠️ -0.003(-0.4)⚠️   5d -0.17 100% decaying
a158_vma5              +0.000(0.0)⚠️ +0.020(3.5) +0.015(3.1) +0.008(1.5)⚠️ +0.008(1.7)⚠️   5d +0.20 100% decaying
kbar_ksft              +0.000(0.0)⚠️ -0.022(-1.6)⚠️ -0.015(-1.8)⚠️ -0.004(-0.4)⚠️ +0.001(0.1)⚠️   5d -0.05 100% decaying
a158_vstd30            +0.000(0.0)⚠️ +0.012(1.8)⚠️ +0.008(1.2)⚠️ +0.003(0.4)⚠️ -0.007(-1.3)⚠️   5d +0.05 100% improving

## 二、排名自相关+换手率

因子                      ac_1d  ac_5d ac_20d    月换手       推荐
a158_vsump5             0.453 -0.312  0.000   80% daily_signal
a158_vma5               0.324 -0.080  0.013   79% daily_signal
momentum_5              0.742 -0.039 -0.027   78%   weekly
reversal_5              0.742 -0.039 -0.027   78%   weekly
a158_rank5              0.470 -0.030  0.001   80% daily_signal
vwap_bias_1d           -0.021 -0.004  0.012   77% daily_signal
kbar_kmid              -0.024 -0.003 -0.013   77% daily_signal
kbar_ksft              -0.014 -0.001 -0.004   77% daily_signal
money_flow_strength     0.082  0.072  0.019   75%  monthly
a158_corr5              0.662  0.084  0.035   78%  monthly
kbar_kup                0.166  0.121  0.094   73%  monthly
turnover_surge_ratio    0.922  0.332 -0.115   84%  monthly
momentum_10             0.861  0.428 -0.036   77%  monthly
reversal_10             0.861  0.428 -0.036   79%  monthly
relative_volume_20      0.695  0.441  0.115   77%   weekly
a158_vsump60            0.718  0.455  0.187   72%  monthly
large_order_ratio       0.521  0.473  0.448   58%  monthly
a158_vstd30             0.748  0.501  0.080   75% daily_signal
stoch_rsv_20            0.873  0.505 -0.045   75%   weekly
mf_divergence           0.903  0.541  0.089   71%  monthly
rsrs_raw_18             0.912  0.559  0.079   75%  monthly
gain_loss_ratio_20      0.927  0.654 -0.053   74%   weekly
price_volume_corr_20    0.955  0.666  0.182   71%  monthly
momentum_20             0.927  0.678 -0.059   76%  monthly
reversal_20             0.928  0.679 -0.058   78%  monthly
up_days_ratio_20        0.934  0.695  0.012   74% daily_signal
beta_market_20          0.951  0.728  0.164   64% daily_signal
maxret_20               0.954  0.765  0.262   62%  monthly
chmom_60_20             0.957  0.790  0.308   53%  monthly
a158_cord30             0.958  0.820  0.351   63%  monthly
reversal_60             0.974  0.871  0.565   50%  monthly
volatility_20           0.979  0.882  0.479   57%  monthly
turnover_std_20         0.987  0.887  0.561   46%  monthly
gap_frequency_20        0.985  0.894  0.488   53%  monthly
ivol_20                 0.981  0.895  0.534   56%  monthly
turnover_stability_20   0.987  0.898  0.578   47%  monthly
volume_std_20           0.991  0.926  0.719   38%  monthly
high_low_range_20       0.993  0.937  0.647   44%  monthly
a158_std60              0.987  0.937  0.639   44%  monthly
atr_norm_20             0.993  0.943  0.681   50%  monthly
volatility_60           0.996  0.965  0.811   29%  monthly
amihud_20               0.995  0.966  0.830   24%  monthly
turnover_mean_20        0.997  0.967  0.780   34%  monthly
dv_ttm                  0.995  0.975  0.930   11%  monthly
ep_ratio                0.995  0.985  0.947   11%  monthly
bp_ratio                0.998  0.993  0.980    9%  monthly
ln_market_cap           0.999  0.997  0.990    6%  monthly
price_level_factor      1.000  0.998  0.994    5%  monthly

## 三、行业中性IC

- atr_norm_20: raw=-0.1039 neutral=-0.0689 ✅
- ivol_20: raw=-0.1015 neutral=-0.0768 ✅
- turnover_mean_20: raw=-0.0991 neutral=-0.1009 ✅
- turnover_stability_20: raw=-0.0986 neutral=-0.1095 ✅
- gap_frequency_20: raw=-0.0980 neutral=-0.0777 ✅
- volatility_20: raw=-0.0947 neutral=-0.0821 ✅
- maxret_20: raw=-0.0870 neutral=-0.0829 ✅
- turnover_std_20: raw=-0.0804 neutral=-0.1127 ✅
- high_low_range_20: raw=-0.0803 neutral=-0.0929 ✅
- volatility_60: raw=-0.0795 neutral=-0.0922 ✅
- ln_market_cap: raw=-0.0653 neutral=-0.0773 ✅
- bp_ratio: raw=+0.0637 neutral=+0.0648 ✅
- amihud_20: raw=+0.0604 neutral=+0.0729 ✅
- price_volume_corr_20: raw=-0.0557 neutral=-0.0754 ✅
- a158_cord30: raw=-0.0531 neutral=-0.0440 ✅
- reversal_20: raw=+0.0508 neutral=+0.0483 ✅
- momentum_20: raw=-0.0467 neutral=-0.0496 ✅
- price_level_factor: raw=+0.0466 neutral=+0.0308 ✅
- large_order_ratio: raw=-0.0443 neutral=-0.0519 ✅
- rsrs_raw_18: raw=-0.0433 neutral=-0.0644 ✅
- kbar_kup: raw=-0.0417 neutral=-0.0520 ✅
- a158_vsump60: raw=-0.0400 neutral=-0.0427 ✅
- a158_corr5: raw=-0.0393 neutral=-0.0353 ✅
- reversal_60: raw=+0.0390 neutral=+0.0462 ✅
- a158_std60: raw=-0.0383 neutral=-0.0339 ✅
- relative_volume_20: raw=-0.0372 neutral=-0.0427 ✅
- momentum_10: raw=-0.0371 neutral=-0.0376 ✅
- reversal_10: raw=+0.0371 neutral=+0.0376 ✅
- dv_ttm: raw=+0.0356 neutral=+0.0395 ✅
- ep_ratio: raw=+0.0356 neutral=+0.0536 ✅
- gain_loss_ratio_20: raw=-0.0350 neutral=-0.0389 ✅
- momentum_5: raw=-0.0327 neutral=-0.0216 ✅
- reversal_5: raw=+0.0327 neutral=+0.0216 ✅
- mf_divergence: raw=-0.0284 neutral=-0.0404 ✅
- money_flow_strength: raw=+0.0269 neutral=+0.0176 ✅
- turnover_surge_ratio: raw=-0.0229 neutral=-0.0358 ✅
- chmom_60_20: raw=-0.0216 neutral=-0.0303 ✅
- stoch_rsv_20: raw=-0.0205 neutral=-0.0076 ✅
- volume_std_20: raw=-0.0204 neutral=-0.0560 ✅
- up_days_ratio_20: raw=-0.0181 neutral=-0.0149 ✅
- beta_market_20: raw=-0.0164 neutral=-0.0047 ✅
- a158_rank5: raw=-0.0133 neutral=-0.0182 ✅
- kbar_kmid: raw=-0.0118 neutral=-0.0279 ✅
- a158_vsump5: raw=-0.0114 neutral=-0.0224 ✅
- vwap_bias_1d: raw=-0.0110 neutral=-0.0173 ✅

## 四、分位收益单调性（<0.6标⚠️）

- ln_market_cap: mono=-1.00 Q1=+2.6% Q5=+0.9% spread=-1.75%
- mf_divergence: mono=-1.00 Q1=+1.6% Q5=+0.8% spread=-0.78%
- price_volume_corr_20: mono=-1.00 Q1=+2.3% Q5=+1.0% spread=-1.27%
- relative_volume_20: mono=-1.00 Q1=+1.9% Q5=+1.3% spread=-0.55%
- large_order_ratio: mono=-0.90 Q1=+1.5% Q5=+1.0% spread=-0.51%
- rsrs_raw_18: mono=-0.90 Q1=+2.1% Q5=+1.0% spread=-1.04%
- turnover_mean_20: mono=-0.90 Q1=+2.7% Q5=+0.8% spread=-1.84%
- turnover_std_20: mono=-0.90 Q1=+2.1% Q5=+0.3% spread=-1.74%
- turnover_surge_ratio: mono=-0.90 Q1=+2.1% Q5=+1.2% spread=-0.86%
- a158_corr5: mono=-0.70 Q1=+1.9% Q5=+1.4% spread=-0.41%
- a158_vsump60: mono=-0.70 Q1=+1.8% Q5=+1.4% spread=-0.37%
- high_low_range_20: mono=-0.70 Q1=+1.2% Q5=+0.9% spread=-0.30%
- kbar_kup: mono=-0.70 Q1=+1.3% Q5=+1.0% spread=-0.29%
- maxret_20: mono=-0.70 Q1=+1.3% Q5=+0.7% spread=-0.63%
- turnover_stability_20: mono=-0.70 Q1=+2.7% Q5=+0.8% spread=-1.97%
- volatility_20: mono=-0.70 Q1=+2.0% Q5=+1.2% spread=-0.83%
- a158_std60: mono=-0.60 Q1=+1.6% Q5=+1.6% spread=-0.01%
- momentum_10: mono=-0.60 Q1=+1.9% Q5=+1.2% spread=-0.78%
- volume_std_20: mono=-0.60 Q1=+1.1% Q5=+0.6% spread=-0.45%
- a158_rank5: mono=-0.50⚠️ Q1=+1.7% Q5=+1.7% spread=-0.02%
- chmom_60_20: mono=-0.50⚠️ Q1=+1.3% Q5=+1.2% spread=-0.12%
- momentum_20: mono=-0.50⚠️ Q1=+1.7% Q5=+1.3% spread=-0.37%
- momentum_5: mono=-0.50⚠️ Q1=+1.7% Q5=+1.6% spread=-0.15%
- a158_cord30: mono=-0.40⚠️ Q1=+1.9% Q5=+1.6% spread=-0.20%
- beta_market_20: mono=-0.40⚠️ Q1=+1.1% Q5=+0.8% spread=-0.30%
- volatility_60: mono=-0.40⚠️ Q1=+1.3% Q5=+0.7% spread=-0.62%
- gain_loss_ratio_20: mono=-0.30⚠️ Q1=+1.3% Q5=+1.2% spread=-0.07%
- ivol_20: mono=-0.30⚠️ Q1=+1.0% Q5=+0.8% spread=-0.27%
- up_days_ratio_20: mono=-0.30⚠️ Q1=+1.2% Q5=+0.9% spread=-0.24%
- price_level_factor: mono=-0.20⚠️ Q1=+1.6% Q5=+1.7% spread=+0.09%
- vwap_bias_1d: mono=-0.20⚠️ Q1=+1.6% Q5=+1.6% spread=+0.02%
- kbar_kmid: mono=+0.00⚠️ Q1=+1.1% Q5=+0.9% spread=-0.16%
- reversal_60: mono=+0.00⚠️ Q1=+1.5% Q5=+1.5% spread=+0.04%
- a158_vsump5: mono=+0.10⚠️ Q1=+1.7% Q5=+1.8% spread=+0.02%
- atr_norm_20: mono=+0.10⚠️ Q1=+0.8% Q5=+1.0% spread=+0.13%
- stoch_rsv_20: mono=+0.20⚠️ Q1=+1.1% Q5=+1.5% spread=+0.36%
- dv_ttm: mono=+0.30⚠️ Q1=+1.4% Q5=+1.5% spread=+0.13%
- ep_ratio: mono=+0.40⚠️ Q1=+1.4% Q5=+1.5% spread=+0.14%
- reversal_5: mono=+0.50⚠️ Q1=+1.6% Q5=+1.7% spread=+0.15%
- reversal_10: mono=+0.60 Q1=+1.2% Q5=+1.9% spread=+0.78%
- bp_ratio: mono=+0.90 Q1=+1.4% Q5=+1.8% spread=+0.40%
- gap_frequency_20: mono=+0.90 Q1=+1.0% Q5=+2.4% spread=+1.44%
- amihud_20: mono=+1.00 Q1=+0.9% Q5=+2.9% spread=+1.96%
- money_flow_strength: mono=+1.00 Q1=+0.8% Q5=+1.5% spread=+0.77%
- reversal_20: mono=+1.00 Q1=+1.5% Q5=+1.8% spread=+0.34%

## 五、被月度框架可能冤杀的因子

- **a158_rank5**: 最优5d, IC_5d=-0.0200 > IC_20d=-0.0133
- **a158_vma5**: 最优5d, IC_5d=+0.0196 > IC_20d=+0.0080
- **a158_vstd30**: 最优5d, IC_5d=+0.0124 > IC_20d=+0.0026
- **a158_vsump5**: 最优5d, IC_5d=-0.0207 > IC_20d=-0.0114
- **beta_market_20**: 最优5d, IC_5d=-0.0240 > IC_20d=-0.0164
- **kbar_kmid**: 最优5d, IC_5d=-0.0252 > IC_20d=-0.0118
- **kbar_ksft**: 最优5d, IC_5d=-0.0215 > IC_20d=-0.0036
- **momentum_5**: 最优5d, IC_5d=-0.0376 > IC_20d=-0.0327
- **reversal_5**: 最优5d, IC_5d=+0.0376 > IC_20d=+0.0327
- **stoch_rsv_20**: 最优10d, IC_5d=-0.0251 > IC_20d=-0.0205
- **vwap_bias_1d**: 最优5d, IC_5d=-0.0251 > IC_20d=-0.0110

## 六、Regime敏感（sensitivity>0.03）

- **atr_norm_20**: bull=-0.0915 bear=-0.0378 side=-0.1378 sens=0.1000 ⚠️样本不足
- **ivol_20**: bull=-0.0741 bear=-0.0497 side=-0.1335 sens=0.0837 ⚠️样本不足
- **beta_market_20**: bull=-0.0565 bear=+0.0231 side=-0.0203 sens=0.0796 ⚠️样本不足
- **volatility_60**: bull=-0.0729 bear=-0.0307 side=-0.1065 sens=0.0758 ⚠️样本不足
- **high_low_range_20**: bull=-0.0667 bear=-0.0370 side=-0.1066 sens=0.0696 ⚠️样本不足
- **gap_frequency_20**: bull=-0.0908 bear=-0.0563 side=-0.1179 sens=0.0616 ⚠️样本不足
- **up_days_ratio_20**: bull=+0.0191 bear=-0.0393 side=-0.0161 sens=0.0584 ⚠️样本不足
- **volume_std_20**: bull=+0.0104 bear=+0.0084 side=-0.0442 sens=0.0546 ⚠️样本不足
- **volatility_20**: bull=-0.0947 bear=-0.0573 side=-0.1114 sens=0.0541 ⚠️样本不足
- **kbar_ksft**: bull=-0.0427 bear=-0.0010 side=+0.0112 sens=0.0540 ⚠️样本不足
- **gain_loss_ratio_20**: bull=-0.0046 bear=-0.0568 side=-0.0294 sens=0.0522 ⚠️样本不足
- **turnover_std_20**: bull=-0.0702 bear=-0.0495 side=-0.0994 sens=0.0500 ⚠️样本不足
- **maxret_20**: bull=-0.0933 bear=-0.0519 side=-0.1002 sens=0.0483 ⚠️样本不足
- **kbar_kmid**: bull=-0.0473 bear=-0.0076 side=+0.0005 sens=0.0478 ⚠️样本不足
- **a158_std60**: bull=-0.0420 bear=-0.0063 side=-0.0529 sens=0.0465 ⚠️样本不足
- **momentum_10**: bull=-0.0071 bear=-0.0526 side=-0.0366 sens=0.0455 ⚠️样本不足
- **reversal_10**: bull=+0.0071 bear=+0.0526 side=+0.0366 sens=0.0455 ⚠️样本不足
- **momentum_20**: bull=-0.0295 bear=-0.0739 side=-0.0347 sens=0.0444 ⚠️样本不足
- **money_flow_strength**: bull=+0.0017 bear=+0.0214 side=+0.0425 sens=0.0408 ⚠️样本不足
- **turnover_mean_20**: bull=-0.0974 bear=-0.0706 side=-0.1112 sens=0.0405 ⚠️样本不足
- **turnover_surge_ratio**: bull=+0.0100 bear=-0.0298 side=-0.0291 sens=0.0398 ⚠️样本不足
- **vwap_bias_1d**: bull=-0.0372 bear=-0.0188 side=+0.0026 sens=0.0397 ⚠️样本不足
- **stoch_rsv_20**: bull=+0.0009 bear=-0.0381 side=-0.0148 sens=0.0390 ⚠️样本不足
- **a158_corr5**: bull=-0.0589 bear=-0.0212 side=-0.0410 sens=0.0376 ⚠️样本不足
- **turnover_stability_20**: bull=-0.0953 bear=-0.0734 side=-0.1098 sens=0.0363 ⚠️样本不足
- **ln_market_cap**: bull=-0.0789 bear=-0.0825 side=-0.0471 sens=0.0355 ⚠️样本不足
- **reversal_60**: bull=+0.0205 bear=+0.0552 side=+0.0300 sens=0.0348 ⚠️样本不足
- **mf_divergence**: bull=-0.0398 bear=-0.0057 side=-0.0368 sens=0.0341 ⚠️样本不足
- **dv_ttm**: bull=+0.0164 bear=+0.0158 side=+0.0498 sens=0.0340 ⚠️样本不足
- **large_order_ratio**: bull=-0.0428 bear=-0.0222 side=-0.0561 sens=0.0339 ⚠️样本不足
- **reversal_20**: bull=+0.0381 bear=+0.0704 side=+0.0412 sens=0.0322 ⚠️样本不足
- **ep_ratio**: bull=+0.0185 bear=+0.0170 side=+0.0482 sens=0.0312 ⚠️样本不足
- **price_level_factor**: bull=+0.0661 bear=+0.0453 side=+0.0353 sens=0.0307 ⚠️样本不足

## 七、策略模板推荐汇总

- **模板1(月度)**: a158_cord30, a158_vsump60, amihud_20, bp_ratio, chmom_60_20, kbar_kup, price_volume_corr_20, rsrs_raw_18
- **模板2(周度)**: momentum_5, relative_volume_20, reversal_5
- **模板11(仓位)**: a158_rank5, a158_vma5, a158_vstd30, a158_vsump5
- **模板12(regime切换)**: a158_corr5, a158_std60, atr_norm_20, beta_market_20, dv_ttm, ep_ratio, gain_loss_ratio_20, gap_frequency_20, high_low_range_20, ivol_20, kbar_kmid, kbar_ksft, large_order_ratio, ln_market_cap, maxret_20, mf_divergence, momentum_10, momentum_20, money_flow_strength, price_level_factor, reversal_10, reversal_20, reversal_60, stoch_rsv_20, turnover_mean_20, turnover_stability_20, turnover_std_20, turnover_surge_ratio, up_days_ratio_20, volatility_20, volatility_60, volume_std_20, vwap_bias_1d

## 八、框架匹配度

当前全部用月度等权(模板1)。推荐非月度: **40个** (83%)
这些因子在当前框架下alpha被低估或误用。