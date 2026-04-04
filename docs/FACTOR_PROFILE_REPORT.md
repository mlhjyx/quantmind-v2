# 因子画像汇总报告 (2026-04-05) — V2

- Forward return方法: close[T+1] -> close[T+h]
- 数据范围: 2021-01-01 ~ 2025-12-31
- Universe: 排除ST/停牌, 与load_universe()对齐
- 超额基准: CSI300同期收益
- 120d IC: 有效范围约2021-07~2025-06（两端各缺~120交易日）

## 一、多周期IC（按|IC_20d|降序，t<2.0标W）

因子                         IC_5d(t)    IC_10d(t)    IC_20d(t)    IC_60d(t)   IC_120d(t)    最优    IR       趋势      天花板
----------------------------------------------------------------------------------------------------------------------------------
atr_norm_20            -0.094(-3.2) -0.088(-3.8) -0.104(-4.5) -0.122(-6.5) -0.133(-6.3) 120d^ -0.58   stable
ivol_20                -0.082(-3.4) -0.082(-4.4) -0.102(-5.1) -0.119(-7.2) -0.123(-6.3) 120d^ -0.66   stable
turnover_mean_20       -0.058(-4.6) -0.069(-6.7) -0.099(-8.9) -0.132(-15.6) -0.153(-20.7) 120d^ -1.15   stable
turnover_stability_20  -0.060(-5.3) -0.070(-7.4) -0.099(-9.5) -0.128(-15.2) -0.146(-20.1) 120d^ -1.23   stable
gap_frequency_20       -0.078(-3.3) -0.077(-4.3) -0.098(-5.3) -0.110(-7.3) -0.111(-6.4) 120dv -0.69   stable
volatility_20          -0.066(-4.4) -0.072(-5.8) -0.095(-7.9) -0.114(-10.6) -0.132(-13.0) 120d^ -1.01   stable
maxret_20              -0.054(-3.7) -0.064(-5.8) -0.087(-9.1) -0.093(-10.3) -0.102(-12.7) 120d^ -1.21   stable
turnover_std_20        -0.046(-4.2) -0.054(-5.9) -0.080(-7.8) -0.114(-13.6) -0.132(-19.4) 120d^ -1.04 improving
high_low_range_20      -0.060(-3.6) -0.059(-4.5) -0.080(-5.8) -0.107(-8.8) -0.126(-12.4) 120d^ -0.78   stable
volatility_60          -0.055(-3.1) -0.052(-3.8) -0.079(-5.5) -0.113(-9.8) -0.133(-13.0) 120d^ -0.73   stable
ln_market_cap          -0.022(-1.2)W -0.053(-2.7) -0.065(-3.4) -0.102(-5.1) -0.143(-7.0) 120d^ -0.44   stable
bp_ratio                +0.051(4.4)  +0.048(4.8)  +0.064(6.4) +0.089(11.0) +0.109(14.1) 120d^ +0.83   stable
amihud_20              +0.019(1.7)W  +0.040(3.8)  +0.060(5.7)  +0.087(8.2) +0.110(11.0) 120d^ +0.74   stable
price_volume_corr_20   -0.033(-4.4) -0.041(-6.1) -0.056(-7.1) -0.062(-7.7) -0.061(-9.2)  60dv -0.92 improving
a158_cord30            -0.032(-4.3) -0.036(-5.6) -0.053(-7.2) -0.057(-7.8) -0.055(-9.5)  60dv -0.93   stable
reversal_20             +0.034(2.8)  +0.046(4.2)  +0.051(4.7)  +0.044(4.3)  +0.036(4.5)  20d +0.61   stable
momentum_20            -0.036(-2.8) -0.045(-4.1) -0.047(-4.4) -0.039(-3.7) -0.029(-3.7)  20d -0.57   stable
price_level_factor      +0.052(3.8)  +0.043(3.5)  +0.047(3.9)  +0.072(6.0)  +0.090(8.9) 120d^ +0.51 decaying
large_order_ratio      -0.028(-3.4) -0.026(-3.4) -0.044(-5.4) -0.045(-5.0) -0.036(-3.8)  60dv -0.72 improving
rsrs_raw_18            -0.038(-4.5) -0.035(-4.9) -0.043(-6.1) -0.051(-8.1) -0.053(-11.7) 120d^ -0.79 improving
kbar_kup               -0.027(-3.1) -0.032(-4.8) -0.042(-6.2) -0.052(-10.0) -0.057(-10.9) 120d^ -0.83   stable
a158_vsump60           -0.031(-4.3) -0.034(-5.0) -0.040(-5.9) -0.043(-7.3) -0.040(-7.7)  60dv -0.78   stable
a158_corr5             -0.023(-3.7) -0.025(-4.3) -0.039(-6.7) -0.040(-8.5) -0.034(-7.9)  60dv -0.86   stable
reversal_60            +0.018(1.3)W +0.024(1.9)W  +0.039(2.8)  +0.046(4.5)  +0.040(4.1)  60dv +0.37   stable
a158_std60             -0.025(-1.5)W -0.025(-1.7)W -0.038(-2.8) -0.052(-5.3) -0.060(-6.1) 120d^ -0.37   stable
relative_volume_20     -0.035(-4.2) -0.041(-5.0) -0.037(-4.8) -0.037(-5.4) -0.034(-5.5)  10d -0.62   stable
momentum_10            -0.030(-2.5) -0.032(-2.9) -0.037(-3.7) -0.037(-4.1) -0.016(-2.4)  20d -0.48   stable
reversal_10             +0.030(2.5)  +0.032(2.9)  +0.037(3.7)  +0.037(4.1)  +0.016(2.4)  20d +0.48   stable
dv_ttm                 +0.014(1.8)W  +0.018(2.5)  +0.036(4.4)  +0.050(5.4)  +0.066(6.9) 120d^ +0.57   stable
ep_ratio                +0.025(2.8)  +0.027(3.4)  +0.036(4.3)  +0.049(5.4)  +0.062(6.3) 120d^ +0.56   stable
gain_loss_ratio_20     -0.032(-2.7) -0.040(-3.7) -0.035(-3.2) -0.031(-2.8) -0.018(-2.1)  10d -0.43 improving
momentum_5             -0.038(-3.2) -0.030(-3.2) -0.033(-4.2) -0.024(-3.0) -0.011(-1.6)W   5d -0.54   stable
reversal_5              +0.038(3.2)  +0.030(3.2)  +0.033(4.2)  +0.024(3.0) +0.011(1.6)W   5d +0.54   stable
mf_divergence          -0.008(-1.2)W -0.016(-2.6) -0.028(-4.5) -0.033(-6.0) -0.037(-7.5) 120d^ -0.60 improving
money_flow_strength    +0.003(0.4)W +0.012(1.8)W  +0.027(3.8)  +0.028(4.6)  +0.031(6.0) 120d^ +0.50   stable
turnover_surge_ratio   -0.023(-3.1) -0.024(-3.6) -0.023(-3.5) -0.024(-4.0) -0.018(-3.1)  60dv -0.45 improving
chmom_60_20            -0.014(-1.3)W -0.012(-1.2)W -0.022(-2.1) -0.019(-2.4) -0.010(-1.4)W  20d -0.28   stable
stoch_rsv_20           -0.025(-2.2) -0.026(-2.6) -0.020(-2.0) -0.018(-1.9)W -0.000(-0.0)W  10d -0.27 improving
volume_std_20          +0.003(0.2)W -0.010(-1.1)W -0.020(-2.0)W -0.012(-1.3)W -0.004(-0.5)W  20d -0.27 improving
up_days_ratio_20       -0.016(-1.7)W -0.022(-2.4) -0.018(-2.1) -0.022(-2.5) -0.017(-2.3)  10d -0.28 improving
beta_market_20         -0.024(-1.7)W -0.012(-1.2)W -0.016(-1.5)W -0.007(-0.7)W -0.021(-2.9)   5d -0.20   stable
a158_rank5             -0.020(-2.2) -0.017(-2.0)W -0.013(-1.4)W -0.006(-0.7)W +0.001(0.2)W   5d -0.18 improving
kbar_kmid              -0.025(-1.8)W -0.022(-2.4) -0.012(-1.3)W -0.011(-1.2)W -0.006(-0.9)W   5d -0.17   stable
a158_vsump5            -0.021(-3.6) -0.012(-2.2) -0.011(-2.0)W -0.004(-0.9)W -0.001(-0.1)W   5d -0.26   stable
vwap_bias_1d           -0.025(-2.1) -0.018(-2.5) -0.011(-1.3)W -0.003(-0.4)W +0.005(0.8)W   5d -0.17 decaying
a158_vma5               +0.020(3.5)  +0.015(3.1) +0.008(1.5)W +0.008(1.7)W +0.002(0.4)W   5d +0.20 decaying
kbar_ksft              -0.022(-1.6)W -0.015(-1.8)W -0.004(-0.4)W +0.001(0.1)W +0.009(1.3)W   5d -0.05 decaying
a158_vstd30            +0.012(1.8)W +0.008(1.2)W +0.003(0.4)W -0.007(-1.3)W -0.012(-2.0)   5d +0.05 improving

## 二、排名自相关+换手率+成本

因子                      ac_1d  ac_5d ac_20d    月换手           推荐    年成本   可行
a158_vsump5             0.453 -0.312  0.000   80% daily_signal 27.5%    N
a158_vma5               0.324 -0.080  0.013   79% daily_signal 34.1%    N
momentum_5              0.742 -0.039 -0.027   78%       weekly 10.8%    N
reversal_5              0.742 -0.039 -0.027   78%       weekly 10.8%    N
a158_rank5              0.470 -0.030  0.001   80% daily_signal 26.7%    N
vwap_bias_1d           -0.021 -0.004  0.012   77% daily_signal 51.4%    N
kbar_kmid              -0.024 -0.003 -0.013   77% daily_signal 51.6%    N
kbar_ksft              -0.014 -0.001 -0.004   77% daily_signal 51.1%    N
money_flow_strength     0.082  0.072  0.019   75%      monthly  1.8%    Y
a158_corr5              0.662  0.084  0.035   78%      monthly  1.9%    Y
kbar_kup                0.166  0.121  0.094   73%      monthly  1.7%    Y
turnover_surge_ratio    0.922  0.332 -0.115   84% regime_switch  1.0%    Y
momentum_10             0.861  0.428 -0.036   77%      monthly  1.9%    Y
reversal_10             0.861  0.428 -0.036   79%      monthly  1.9%    Y
relative_volume_20      0.695  0.441  0.115   77%       weekly  5.8%    Y
a158_vsump60            0.718  0.455  0.187   72%      monthly  1.7%    Y
large_order_ratio       0.521  0.473  0.448   58%      monthly  1.4%    Y
a158_vstd30             0.748  0.501  0.080   75% regime_switch  0.9%    Y
stoch_rsv_20            0.873  0.505 -0.045   75% regime_switch  0.9%    Y
mf_divergence           0.903  0.541  0.089   71%      monthly  1.7%    Y
rsrs_raw_18             0.912  0.559  0.079   75%      monthly  1.8%    Y
gain_loss_ratio_20      0.927  0.654 -0.053   74%       weekly  3.6%    N
price_volume_corr_20    0.955  0.666  0.182   71%      monthly  1.7%    Y
momentum_20             0.927  0.678 -0.059   76%      monthly  1.8%    Y
reversal_20             0.928  0.679 -0.058   78%      monthly  1.9%    Y
up_days_ratio_20        0.934  0.695  0.012   74% regime_switch  0.9%    Y
beta_market_20          0.951  0.728  0.164   64% regime_switch  0.8%    Y
maxret_20               0.954  0.765  0.262   62%      monthly  1.5%    Y
chmom_60_20             0.957  0.790  0.308   53%      monthly  1.3%    Y
a158_cord30             0.958  0.820  0.351   63%      monthly  1.5%    Y
reversal_60             0.974  0.871  0.565   50%      monthly  1.2%    N
volatility_20           0.979  0.882  0.479   57%      monthly  1.4%    Y
turnover_std_20         0.987  0.887  0.561   46%      monthly  1.1%    Y
gap_frequency_20        0.985  0.894  0.488   53%      monthly  1.3%    Y
ivol_20                 0.981  0.895  0.534   56%      monthly  1.3%    Y
turnover_stability_20   0.987  0.898  0.578   47%      monthly  1.1%    Y
volume_std_20           0.991  0.926  0.719   38%      monthly  0.9%    Y
high_low_range_20       0.993  0.937  0.647   44%      monthly  1.1%    Y
a158_std60              0.987  0.937  0.639   44%      monthly  1.1%    N
atr_norm_20             0.993  0.943  0.681   50%      monthly  1.2%    Y
volatility_60           0.996  0.965  0.811   29%      monthly  0.7%    Y
amihud_20               0.995  0.966  0.830   24%      monthly  0.6%    Y
turnover_mean_20        0.997  0.967  0.780   34%      monthly  0.8%    Y
dv_ttm                  0.995  0.975  0.930   11%      monthly  0.3%    Y
ep_ratio                0.995  0.985  0.947   11%      monthly  0.3%    Y
bp_ratio                0.998  0.993  0.980    9%      monthly  0.2%    Y
ln_market_cap           0.999  0.997  0.990    6%      monthly  0.1%    Y
price_level_factor      1.000  0.998  0.994    5%      monthly  0.1%    Y

## 三、行业中性IC

- atr_norm_20: raw=-0.1039 neutral=-0.0689 OK
- ivol_20: raw=-0.1015 neutral=-0.0768 OK
- turnover_mean_20: raw=-0.0991 neutral=-0.1009 OK
- turnover_stability_20: raw=-0.0986 neutral=-0.1095 OK
- gap_frequency_20: raw=-0.0980 neutral=-0.0777 OK
- volatility_20: raw=-0.0947 neutral=-0.0821 OK
- maxret_20: raw=-0.0870 neutral=-0.0829 OK
- turnover_std_20: raw=-0.0804 neutral=-0.1127 OK
- high_low_range_20: raw=-0.0803 neutral=-0.0929 OK
- volatility_60: raw=-0.0795 neutral=-0.0922 OK
- ln_market_cap: raw=-0.0653 neutral=-0.0773 OK
- bp_ratio: raw=+0.0637 neutral=+0.0648 OK
- amihud_20: raw=+0.0604 neutral=+0.0729 OK
- price_volume_corr_20: raw=-0.0557 neutral=-0.0754 OK
- a158_cord30: raw=-0.0531 neutral=-0.0440 OK
- reversal_20: raw=+0.0508 neutral=+0.0483 OK
- momentum_20: raw=-0.0467 neutral=-0.0496 OK
- price_level_factor: raw=+0.0466 neutral=+0.0308 OK
- large_order_ratio: raw=-0.0443 neutral=-0.0519 OK
- rsrs_raw_18: raw=-0.0433 neutral=-0.0644 OK
- kbar_kup: raw=-0.0417 neutral=-0.0520 OK
- a158_vsump60: raw=-0.0400 neutral=-0.0427 OK
- a158_corr5: raw=-0.0393 neutral=-0.0353 OK
- reversal_60: raw=+0.0390 neutral=+0.0462 OK
- a158_std60: raw=-0.0383 neutral=-0.0339 OK
- relative_volume_20: raw=-0.0372 neutral=-0.0427 OK
- momentum_10: raw=-0.0371 neutral=-0.0376 OK
- reversal_10: raw=+0.0371 neutral=+0.0376 OK
- dv_ttm: raw=+0.0356 neutral=+0.0395 OK
- ep_ratio: raw=+0.0356 neutral=+0.0536 OK
- gain_loss_ratio_20: raw=-0.0350 neutral=-0.0389 OK
- momentum_5: raw=-0.0327 neutral=-0.0216 OK
- reversal_5: raw=+0.0327 neutral=+0.0216 OK
- mf_divergence: raw=-0.0284 neutral=-0.0404 OK
- money_flow_strength: raw=+0.0269 neutral=+0.0176 OK
- turnover_surge_ratio: raw=-0.0229 neutral=-0.0358 OK
- chmom_60_20: raw=-0.0216 neutral=-0.0303 OK
- stoch_rsv_20: raw=-0.0205 neutral=-0.0076 OK
- volume_std_20: raw=-0.0204 neutral=-0.0560 OK
- up_days_ratio_20: raw=-0.0181 neutral=-0.0149 OK
- beta_market_20: raw=-0.0164 neutral=-0.0047 OK
- a158_rank5: raw=-0.0133 neutral=-0.0182 OK
- kbar_kmid: raw=-0.0118 neutral=-0.0279 OK
- a158_vsump5: raw=-0.0114 neutral=-0.0224 OK
- vwap_bias_1d: raw=-0.0110 neutral=-0.0173 OK

## 四、分位收益单调性+选股建议

- kbar_kmid: mono=+0.00W Q1=+1.1% Q5=+0.9% spread=-0.16% — 不适合排名选股(单调性0.00)，建议极端分位触发或仅作ML特征
- reversal_60: mono=+0.00W Q1=+1.5% Q5=+1.5% spread=+0.04% — 不适合排名选股(单调性0.00)，建议极端分位触发或仅作ML特征
- a158_vsump5: mono=+0.10W Q1=+1.7% Q5=+1.8% spread=+0.02% — 不适合排名选股(单调性0.10)，建议极端分位触发或仅作ML特征
- atr_norm_20: mono=+0.10W Q1=+0.8% Q5=+1.0% spread=+0.13% — 不适合排名选股(单调性0.10)，建议极端分位触发或仅作ML特征
- price_level_factor: mono=-0.20W Q1=+1.6% Q5=+1.7% spread=+0.09% — 不适合排名选股(单调性-0.20)，建议极端分位触发或仅作ML特征
- stoch_rsv_20: mono=+0.20W Q1=+1.1% Q5=+1.5% spread=+0.36% — 不适合排名选股(单调性0.20)，建议极端分位触发或仅作ML特征
- vwap_bias_1d: mono=-0.20W Q1=+1.6% Q5=+1.6% spread=+0.02% — 不适合排名选股(单调性-0.20)，建议极端分位触发或仅作ML特征
- dv_ttm: mono=+0.30W Q1=+1.4% Q5=+1.5% spread=+0.13% — 排名选股但建议缩小N(Top-10而非Top-20)
- gain_loss_ratio_20: mono=-0.30W Q1=+1.3% Q5=+1.2% spread=-0.07% — 排名选股但建议缩小N(Top-10而非Top-20)
- ivol_20: mono=-0.30W Q1=+1.0% Q5=+0.8% spread=-0.27% — 排名选股但建议缩小N(Top-10而非Top-20)
- up_days_ratio_20: mono=-0.30W Q1=+1.2% Q5=+0.9% spread=-0.24% — 排名选股但建议缩小N(Top-10而非Top-20)
- a158_cord30: mono=-0.40W Q1=+1.9% Q5=+1.6% spread=-0.20% — 排名选股但建议缩小N(Top-10而非Top-20)
- beta_market_20: mono=-0.40W Q1=+1.1% Q5=+0.8% spread=-0.30% — 排名选股但建议缩小N(Top-10而非Top-20)
- ep_ratio: mono=+0.40W Q1=+1.4% Q5=+1.5% spread=+0.14% — 排名选股但建议缩小N(Top-10而非Top-20)
- volatility_60: mono=-0.40W Q1=+1.3% Q5=+0.7% spread=-0.62% — 排名选股但建议缩小N(Top-10而非Top-20)
- a158_rank5: mono=-0.50W Q1=+1.7% Q5=+1.7% spread=-0.02% — 排名选股但建议缩小N(Top-10而非Top-20)
- chmom_60_20: mono=-0.50W Q1=+1.3% Q5=+1.2% spread=-0.12% — 排名选股但建议缩小N(Top-10而非Top-20)
- momentum_20: mono=-0.50W Q1=+1.7% Q5=+1.3% spread=-0.37% — 排名选股但建议缩小N(Top-10而非Top-20)
- momentum_5: mono=-0.50W Q1=+1.7% Q5=+1.6% spread=-0.15% — 排名选股但建议缩小N(Top-10而非Top-20)
- reversal_5: mono=+0.50W Q1=+1.6% Q5=+1.7% spread=+0.15% — 排名选股但建议缩小N(Top-10而非Top-20)
- a158_std60: mono=-0.60 Q1=+1.6% Q5=+1.6% spread=-0.01% — 排名选股Top-N有效
- momentum_10: mono=-0.60 Q1=+1.9% Q5=+1.2% spread=-0.78% — 排名选股Top-N有效
- reversal_10: mono=+0.60 Q1=+1.2% Q5=+1.9% spread=+0.78% — 排名选股Top-N有效
- volume_std_20: mono=-0.60 Q1=+1.1% Q5=+0.6% spread=-0.45% — 排名选股Top-N有效
- a158_corr5: mono=-0.70 Q1=+1.9% Q5=+1.4% spread=-0.41% — 排名选股Top-N有效
- a158_vsump60: mono=-0.70 Q1=+1.8% Q5=+1.4% spread=-0.37% — 排名选股Top-N有效
- high_low_range_20: mono=-0.70 Q1=+1.2% Q5=+0.9% spread=-0.30% — 排名选股Top-N有效
- kbar_kup: mono=-0.70 Q1=+1.3% Q5=+1.0% spread=-0.29% — 排名选股Top-N有效
- maxret_20: mono=-0.70 Q1=+1.3% Q5=+0.7% spread=-0.63% — 排名选股Top-N有效
- turnover_stability_20: mono=-0.70 Q1=+2.7% Q5=+0.8% spread=-1.97% — 排名选股Top-N有效
- volatility_20: mono=-0.70 Q1=+2.0% Q5=+1.2% spread=-0.83% — 排名选股Top-N有效
- bp_ratio: mono=+0.90 Q1=+1.4% Q5=+1.8% spread=+0.40% — 排名选股Top-N有效
- gap_frequency_20: mono=+0.90 Q1=+1.0% Q5=+2.4% spread=+1.44% — 排名选股Top-N有效
- large_order_ratio: mono=-0.90 Q1=+1.5% Q5=+1.0% spread=-0.51% — 排名选股Top-N有效
- rsrs_raw_18: mono=-0.90 Q1=+2.1% Q5=+1.0% spread=-1.04% — 排名选股Top-N有效
- turnover_mean_20: mono=-0.90 Q1=+2.7% Q5=+0.8% spread=-1.84% — 排名选股Top-N有效
- turnover_std_20: mono=-0.90 Q1=+2.1% Q5=+0.3% spread=-1.74% — 排名选股Top-N有效
- turnover_surge_ratio: mono=-0.90 Q1=+2.1% Q5=+1.2% spread=-0.86% — 排名选股Top-N有效
- amihud_20: mono=+1.00 Q1=+0.9% Q5=+2.9% spread=+1.96% — 排名选股Top-N有效
- ln_market_cap: mono=-1.00 Q1=+2.6% Q5=+0.9% spread=-1.75% — 排名选股Top-N有效
- mf_divergence: mono=-1.00 Q1=+1.6% Q5=+0.8% spread=-0.78% — 排名选股Top-N有效
- money_flow_strength: mono=+1.00 Q1=+0.8% Q5=+1.5% spread=+0.77% — 排名选股Top-N有效
- price_volume_corr_20: mono=-1.00 Q1=+2.3% Q5=+1.0% spread=-1.27% — 排名选股Top-N有效
- relative_volume_20: mono=-1.00 Q1=+1.9% Q5=+1.3% spread=-0.55% — 排名选股Top-N有效
- reversal_20: mono=+1.00 Q1=+1.5% Q5=+1.8% spread=+0.34% — 排名选股Top-N有效

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

## 六、Regime分析

### 6A. Bull/Bear方向反转（5个，推荐模板12）

- **beta_market_20**: bull=-0.0565 bear=+0.0231 side=-0.0203 sens=0.0796 W样本不足
- **up_days_ratio_20**: bull=+0.0191 bear=-0.0393 side=-0.0161 sens=0.0584 W样本不足
- **turnover_surge_ratio**: bull=+0.0100 bear=-0.0298 side=-0.0291 sens=0.0398 W样本不足
- **stoch_rsv_20**: bull=+0.0009 bear=-0.0381 side=-0.0148 sens=0.0390 W样本不足
- **a158_vstd30**: bull=-0.0057 bear=+0.0234 side=-0.0041 sens=0.0291 W样本不足

### 6B. 同向不同幅度（29个，保持原模板）

- atr_norm_20: bull=-0.0915 bear=-0.0378 side=-0.1378 sens=0.1000
- ivol_20: bull=-0.0741 bear=-0.0497 side=-0.1335 sens=0.0837
- volatility_60: bull=-0.0729 bear=-0.0307 side=-0.1065 sens=0.0758
- high_low_range_20: bull=-0.0667 bear=-0.0370 side=-0.1066 sens=0.0696
- gap_frequency_20: bull=-0.0908 bear=-0.0563 side=-0.1179 sens=0.0616
- volume_std_20: bull=+0.0104 bear=+0.0084 side=-0.0442 sens=0.0546
- volatility_20: bull=-0.0947 bear=-0.0573 side=-0.1114 sens=0.0541
- kbar_ksft: bull=-0.0427 bear=-0.0010 side=+0.0112 sens=0.0540
- gain_loss_ratio_20: bull=-0.0046 bear=-0.0568 side=-0.0294 sens=0.0522
- turnover_std_20: bull=-0.0702 bear=-0.0495 side=-0.0994 sens=0.0500
- maxret_20: bull=-0.0933 bear=-0.0519 side=-0.1002 sens=0.0483
- kbar_kmid: bull=-0.0473 bear=-0.0076 side=+0.0005 sens=0.0478
- a158_std60: bull=-0.0420 bear=-0.0063 side=-0.0529 sens=0.0465
- momentum_10: bull=-0.0071 bear=-0.0526 side=-0.0366 sens=0.0455
- reversal_10: bull=+0.0071 bear=+0.0526 side=+0.0366 sens=0.0455
- momentum_20: bull=-0.0295 bear=-0.0739 side=-0.0347 sens=0.0444
- money_flow_strength: bull=+0.0017 bear=+0.0214 side=+0.0425 sens=0.0408
- turnover_mean_20: bull=-0.0974 bear=-0.0706 side=-0.1112 sens=0.0405
- vwap_bias_1d: bull=-0.0372 bear=-0.0188 side=+0.0026 sens=0.0397
- a158_corr5: bull=-0.0589 bear=-0.0212 side=-0.0410 sens=0.0376
- turnover_stability_20: bull=-0.0953 bear=-0.0734 side=-0.1098 sens=0.0363
- ln_market_cap: bull=-0.0789 bear=-0.0825 side=-0.0471 sens=0.0355
- reversal_60: bull=+0.0205 bear=+0.0552 side=+0.0300 sens=0.0348
- mf_divergence: bull=-0.0398 bear=-0.0057 side=-0.0368 sens=0.0341
- dv_ttm: bull=+0.0164 bear=+0.0158 side=+0.0498 sens=0.0340
- large_order_ratio: bull=-0.0428 bear=-0.0222 side=-0.0561 sens=0.0339
- reversal_20: bull=+0.0381 bear=+0.0704 side=+0.0412 sens=0.0322
- ep_ratio: bull=+0.0185 bear=+0.0170 side=+0.0482 sens=0.0312
- price_level_factor: bull=+0.0661 bear=+0.0453 side=+0.0353 sens=0.0307

## 七、成本可行性校验

- **a158_rank5**: 成本侵蚀: daily_signal换手53%, 年化成本26.7%, 预估alpha0.3%, 建议降频至月度或仅作ML特征
- **a158_std60**: 
- **a158_vma5**: 成本侵蚀: daily_signal换手68%, 年化成本34.1%, 预估alpha2.5%, 建议降频至月度或仅作ML特征
- **a158_vsump5**: 成本侵蚀: daily_signal换手55%, 年化成本27.5%, 预估alpha0.3%, 建议降频至月度或仅作ML特征
- **gain_loss_ratio_20**: 成本侵蚀: weekly换手35%, 年化成本3.6%, 预估alpha0.8%, 建议降频至月度或仅作ML特征
- **kbar_kmid**: 成本侵蚀: daily_signal换手102%, 年化成本51.6%, 预估alpha1.9%, 建议降频至月度或仅作ML特征
- **kbar_ksft**: 成本侵蚀: daily_signal换手101%, 年化成本51.1%, 预估alpha2.3%, 建议降频至月度或仅作ML特征
- **momentum_5**: 成本侵蚀: weekly换手104%, 年化成本10.8%, 预估alpha1.8%, 建议降频至月度或仅作ML特征
- **reversal_5**: 成本侵蚀: weekly换手104%, 年化成本10.8%, 预估alpha1.8%, 建议降频至月度或仅作ML特征
- **reversal_60**: 
- **vwap_bias_1d**: 成本侵蚀: daily_signal换手102%, 年化成本51.4%, 预估alpha0.2%, 建议降频至月度或仅作ML特征

## 八、冗余因子标注

### 8A. 冗余对（corr>0.85，择一）

- atr_norm_20 <-> ivol_20 (corr=0.94) — atr_norm_20: 替代
- gain_loss_ratio_20 <-> momentum_20 (corr=0.93) — gain_loss_ratio_20: 替代
- high_low_range_20 <-> volatility_20 (corr=0.91) — high_low_range_20: 替代
- kbar_ksft <-> vwap_bias_1d (corr=0.92) — kbar_ksft: 替代
- maxret_20 <-> volatility_20 (corr=0.90) — maxret_20: 保留
- turnover_mean_20 <-> turnover_stability_20 (corr=0.91) — turnover_mean_20: 替代
- turnover_stability_20 <-> turnover_std_20 (corr=0.99) — turnover_stability_20: 保留

### 8B. Mirror Pairs（corr<-0.85，注意方向对齐）

- momentum_10 <-> reversal_10 (corr=-1.00)
- momentum_20 <-> reversal_20 (corr=-0.98)
- momentum_5 <-> reversal_5 (corr=-1.00)

## 九、FMP独立组合候选

聚类代表: 32个, FMP候选(两两corr<0.3): 2个

- **mf_divergence**: IC_20d=-0.0284 IR=-0.60 tmpl=1
- **beta_market_20**: IC_20d=-0.0164 IR=-0.20 tmpl=12

## 十、策略模板推荐汇总（V2修正后）

- **模板1(月度)** [33个]: a158_cord30, a158_corr5, a158_std60, a158_vsump60, amihud_20, atr_norm_20, bp_ratio, chmom_60_20, dv_ttm, ep_ratio, gap_frequency_20, high_low_range_20, ivol_20, kbar_kup, large_order_ratio, ln_market_cap, maxret_20, mf_divergence, momentum_10, momentum_20, money_flow_strength, price_level_factor, price_volume_corr_20, reversal_10, reversal_20, reversal_60, rsrs_raw_18, turnover_mean_20, turnover_stability_20, turnover_std_20, volatility_20, volatility_60, volume_std_20
- **模板2(周度)** [4个]: gain_loss_ratio_20, momentum_5, relative_volume_20, reversal_5
- **模板11(仓位)** [6个]: a158_rank5, a158_vma5, a158_vsump5, kbar_kmid, kbar_ksft, vwap_bias_1d
- **模板12(regime切换)** [5个]: a158_vstd30, beta_market_20, stoch_rsv_20, turnover_surge_ratio, up_days_ratio_20

## 十一、框架匹配度

当前全部用月度等权(模板1)。推荐非月度: **15个** (31%)
推荐月度(模板1): **33个** (69%)

## 十二、多模板评分（Top-2）

因子                        主模板    分数     备选    分数
--------------------------------------------------
atr_norm_20                 1  0.82     11  0.27
ivol_20                     1  0.84     11  0.29
turnover_mean_20            1  0.98      2  0.35
turnover_stability_20       1  0.92      2  0.33
gap_frequency_20            1  0.96      2  0.37
volatility_20               1  0.92      2  0.34
maxret_20                   1  0.88      2  0.37
turnover_std_20             1  0.96      2  0.37
high_low_range_20           1  0.94      2  0.32
volatility_60               1  0.88      2  0.25
ln_market_cap               1  1.00      2  0.36
bp_ratio                    1  0.98      2  0.34
amihud_20                   1  1.00      2  0.37
price_volume_corr_20        1  0.91      2  0.46
a158_cord30                 1  0.84     11  0.33
reversal_20                 1  0.67      2  0.46
momentum_20                 1  0.57     11  0.39
price_level_factor          1  0.84      2  0.20
large_order_ratio           1  0.83      2  0.50
rsrs_raw_18                 1  0.86      2  0.47
kbar_kup                    1  0.68     11  0.60
a158_vsump60                1  0.78      2  0.46
a158_corr5                  1  0.67      2  0.57
reversal_60                 1  0.78     11  0.27
a158_std60                  1  0.92     11  0.25
relative_volume_20          2  0.63      1  0.54
momentum_10                 1  0.52      2  0.45
reversal_10                 1  0.52      2  0.45
dv_ttm                      1  0.86      2  0.23
ep_ratio                    1  0.88      2  0.24
gain_loss_ratio_20          2  0.47     11  0.38
momentum_5                  2  0.65     11  0.45
reversal_5                  2  0.65     11  0.45
mf_divergence               1  0.87      2  0.50
money_flow_strength         1  0.72      2  0.64
turnover_surge_ratio       12  0.78     12  0.78
chmom_60_20                 1  0.61      2  0.32
stoch_rsv_20               12  0.70      2  0.45
volume_std_20               1  0.67      2  0.30
up_days_ratio_20           12  0.91     11  0.70
beta_market_20             12  0.94     11  0.65
a158_rank5                 11  0.86      2  0.65
kbar_kmid                  11  1.00      2  0.54
a158_vsump5                11  0.86      2  0.65
vwap_bias_1d               11  0.99      2  0.58
a158_vma5                  11  0.90      2  0.58
kbar_ksft                  11  0.99      2  0.60
a158_vstd30                12  0.76     12  0.69