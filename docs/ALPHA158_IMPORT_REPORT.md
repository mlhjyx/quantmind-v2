# Alpha158因子批量导入报告

> **日期**: 2026-04-04
> **来源**: Microsoft Qlib Alpha158 (https://github.com/microsoft/qlib)
> **数据范围**: 2021-01-01 ~ 2025-12-31, 5260只A股
> **Universe过滤**: 排除ST/新股(<60d)/微盘(<100亿)/停牌（与回测一致）

---

## 统计汇总

| 阶段 | 数量 | 说明 |
|------|------|------|
| Alpha158总公式 | 158 | 9 KBAR + 4 PRICE + 145 ROLLING |
| 跳过（计算太慢） | 30 | BETA/RSQR/RESI/IMAX/IMIN/IMXD × 5窗口 |
| 实际计算 | 128 | 全部用pandas向量化，13分钟完成 |
| IC筛选通过 (|IC_20d|≥0.02) | 102 | 79.7%通过率 |
| Alpha158内部去重 (corr>0.7) | 23 | 79个窗口变体/数学等价被淘汰 |
| vs 现有40因子去重 (corr>0.7) | **8** | 15个与现有因子重叠 |

---

## 最终入池因子（8个独立新因子）

| 因子 | IC_20d | IR_20d | 公式 | 与现有最高corr | 分类 |
|------|--------|--------|------|--------------|------|
| **STD60** | -0.060 | -0.33 | Std(close,60)/close | 0.69 volatility_60 | RANKING |
| **VSUMP60** | -0.059 | -0.67 | Sum(Greater(Δvol,0),60)/Sum(|Δvol|,60) | 0.64 relative_volume_20 | RANKING |
| **CORD30** | -0.052 | -0.52 | Corr(ret, Δlog_vol, 30) | 0.64 price_volume_corr_20 | RANKING |
| **RANK5** | -0.046 | -0.37 | 5日时序百分位排名 | 0.63 momentum_5 | FAST_RANKING |
| **CORR5** | -0.040 | -0.58 | Corr(close, log(vol), 5) | 0.53 price_volume_corr_20 | FAST_RANKING |
| **VSTD30** | +0.022 | +0.30 | Std(volume,30)/volume | 0.48 turnover_surge_ratio | RANKING |
| **VSUMP5** | -0.021 | -0.27 | Sum(Greater(Δvol,0),5)/Sum(|Δvol|,5) | 0.49 turnover_surge_ratio | FAST_RANKING |
| **VMA5** | +0.020 | +0.27 | Mean(volume,5)/volume | 0.41 ivol_20 | FAST_RANKING |

---

## 入池因子经济学含义

1. **STD60** — 60日价格波动率（长期），与现有volatility_20互补（不同窗口），IC方向负=低波好
2. **VSUMP60** — 60日成交量上涨比例（RSI类指标for volume），衡量量能持续性
3. **CORD30** — 30日收益率vs成交量变化相关性，量价背离信号
4. **RANK5** — 5日时序价格位置，短期动量/反转
5. **CORR5** — 5日价量相关性（短期），与现有20日版本互补
6. **VSTD30** — 30日成交量波动率，衡量交易活跃度稳定性
7. **VSUMP5** — 5日成交量上涨比例（短期量能方向）
8. **VMA5** — 5日成交量均值比，衡量近期交易放大/缩小

---

## 与现有因子重叠的高IC因子（供参考，不入池）

| 因子 | IC_20d | 重叠因子 | corr |
|------|--------|---------|------|
| KLEN | -0.088 | atr_norm_20 | 0.90 |
| KLOW | -0.065 | atr_norm_20 | 0.84 |
| QTLD60 | +0.093 | gain_loss_ratio_20 | 0.75 |
| CORR20 | -0.047 | price_volume_corr_20 | 0.91 |
| VMA60 | +0.058 | relative_volume_20 | 0.89 |

---

## 策略匹配建议（铁律8）

| 因子 | IC_decay建议调仓频率 | 权重方式 |
|------|---------------------|---------|
| STD60, VSUMP60, CORD30, VSTD30 | 月度（慢衰减） | 等权/IC加权 |
| RANK5, CORR5, VSUMP5, VMA5 | 双周/周度（快衰减，窗口≤5） | 等权 |

---

## 代码文件

- `backend/engines/alpha158_factors.py` — 158个因子的pandas实现
- `backend/scripts/compute_alpha158_ic.py` — IC批量计算脚本（内存优化版）
- `models/alpha158_ic_results.csv` — 128个因子IC结果
- `models/alpha158_survived.csv` — 23个Alpha158内部去重后存活
- `models/alpha158_vs_existing.csv` — 23个因子vs现有40因子相关性

---

## 下一步

1. 8个入池因子写入`factor_values`表 → 需要先在`factor_engine.py`注册计算函数
2. 与现有5因子组合做回测验证（增量Sharpe贡献）
3. 4个FAST_RANKING因子(窗口≤5)考虑双周调仓策略匹配
4. 跳过的30个慢算子（Slope/R²/Residual/IdxMax/IdxMin）如果需要，可用numpy优化后补算
