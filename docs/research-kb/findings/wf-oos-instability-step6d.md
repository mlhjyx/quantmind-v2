# 发现: 5 因子等权策略 regime-conditional, SMB beta 驱动

- **日期**: 2026-04-09 (Step 6-D)
- **来源脚本**:
  - `scripts/build_12yr_baseline.py`
  - `scripts/wf_equal_weight_oos.py`
  - `scripts/yearly_breakdown_backtest.py`
  - `scripts/research/ff3_attribution.py`
- **结果文件**:
  - `cache/baseline/metrics_12yr.json` (12 年 in-sample)
  - `cache/baseline/wf_oos_result.json` (WF 5-fold OOS)
  - `cache/baseline/yearly_breakdown.json` (逐年度)
  - `cache/baseline/ff3_attribution.json` (FF3 归因)

## 核心数字

| 维度 | 值 | 意义 |
|------|-----|------|
| 12 年真实 in-sample Sharpe | **0.5309** | 之前文档误标为 0.6095, 实际是 5 年的数字 |
| 12 年真实 in-sample MDD | **-56.37%** | 比 5 年 -50.75% 更深 |
| 12 年 annual return | 13.06% | 1M → 4.48M |
| 5 年 regression baseline Sharpe | 0.6095 | `regression_test.py` 固定锚点 (2021-2025) |
| 逐年 Sharpe mean / std | 0.79 / 1.20 | 12 full years |
| 逐年 Sharpe 范围 | [-0.73, 3.48] | 2018 / 2021 两个极值 |
| 负 Sharpe 年份 | 2017, 2018, 2022, 2023 | 4/12 = 33% |
| WF 5-fold (2021-2026 only) chain-link Sharpe | 0.6336 | 折间 std = 1.52 UNSTABLE |
| FF3 全期 Alpha | **+18.98% 年化 (t=2.90 ✓)** | 真 alpha 存在, 但主要在 2014-2020 |
| FF3 2021-2026 Alpha | +12.64% (t=1.94) | Borderline significant, 衰减 |
| FF3 2014-2020 Alpha | +32.72% (t=3.10 ***) | 盲区期 alpha 更强 |
| FF3 全期 SMB beta | **+1.09** | 110% 小盘暴露 (远超文档宣称的 0.83) |
| FF3 全期 HML beta | -0.03 | 价值因子无贡献 |
| FF3 全期 MKT beta | +0.83 | 市场中性化不完整 |
| FF3 全期 R² | 0.464 | FF3 解释 46% 方差, 剩下 54% 里 alpha+noise |
| 2023 年 Alpha | **-21.70% (t=-2.26 **)** | 显著负! AI 主题杀小盘 |
| 2021 年 Alpha | **+81.80% (t=5.02 ***)** | 小盘牛市极端值 |

## 证据

### 1. 逐年度 Sharpe (2014-2025, 12 full years)

```
2014: +1.44  大牛市
2015: +1.33  股灾 (MDD -56%)
2016: +1.17  熔断反弹
2017: -0.39  蓝筹行情
2018: -0.73  大熊市 (MDD -29%)
2019: +1.12  反弹
2020: +0.86  疫情+核心资产
2021: +3.48  小盘牛 (MDD -11%, annual +95%)
2022: -0.36  俄乌熊
2023: -0.32  AI 主题杀小盘
2024: +0.12  政策期
2025: +1.73  北交所回暖
```

Mean=0.79, Median=0.99, Std=1.20. **有 1/3 年份 Sharpe 为负**, 标准差跟均值同量级 = 没有持续 alpha。

### 2. Walk-Forward 5-fold OOS (覆盖 2021-02 ~ 2026-04, **仅 5 年**, 前 7 年被 train_window 吃掉)

```
Fold 0 (2021-02~2022-02): Sharpe=+3.18, Annual=+75%  ← 2021 小盘牛
Fold 1 (2022-02~2023-03): Sharpe=+0.12, Annual=+0.3%
Fold 2 (2023-03~2024-03): Sharpe=-0.83, Annual=-22% ← AI 杀小盘
Fold 3 (2024-03~2025-03): Sharpe=+0.29, Annual=+4%
Fold 4 (2025-03~2026-04): Sharpe=+1.25, Annual=+32%
```

Chain-link Sharpe = 0.6336, 折间 std = **1.5186**, **1 fold 负 Sharpe**, verdict=UNSTABLE。

### 3. FF3 分期 (全/2014-2020/2021-2026)

```
全期 12yr:    Alpha=+18.98%*** (t=2.90)  MKT=+0.83  SMB=+1.09  HML=-0.03  R²=0.46
2014-2020:   Alpha=+32.72%*** (t=3.10)  MKT=+0.79  SMB=+1.45  HML=+0.11  R²=0.42
2021-2026:   Alpha=+12.64%    (t=1.94)  MKT=+0.91  SMB=+0.92  HML=-0.03  R²=0.63
```

Alpha 从 32.7% 衰减到 12.6%, t-stat 从 3.10 掉到 1.94, 越近越不显著。R² 上升说明近期策略越来越被 FF3 解释。

## 结论

1. **策略不是纯 alpha 策略** — 扣除 SMB beta 的部分收益后, 近 6 年 alpha 不显著
2. **Alpha 衰减趋势明显** — 2014-2020 每年 32%, 2021-2026 每年 12%, t-stat 从 3.10 → 1.94
3. **Regime 敏感** — 2017/2018/2022/2023 四年 Sharpe 为负, 且 2023 年 FF3 alpha 显著为负
4. **2021 是极端值** — 单年贡献 chain-link 85%+ 的超额收益
5. **5 年 (0.6095) vs 12 年 (0.5309) 的差距来自 2017-2018 连续弱期压低**, 不是样本偏差

## 应用

1. **PT 毕业标准需要重估** — 基于 5 年 0.94 算的 "Sharpe ≥ 0.67" 阈值太宽松, 应该基于 12 年真实基线 0.5309 或逐年 median 0.99 的 65% 重算
2. **不要在"OOS Sharpe 0.6336 约等于 5yr in-sample 0.6095" 上感到安慰** — WF 只测了 2021-2026, 等于把 5 年的数据切成 5 份评估自己, 没有真正的前 7 年 OOS 信息
3. **下一步策略研究优先级**:
   - 先解决 alpha 衰减 (找到 2021 后持续有效的新因子)
   - Modifier 层 (减 SMB 暴露 / 市场 regime 切换降仓位) 可能比加因子更有效
   - 分市值策略分拆 (大盘/中盘/小盘各一套因子) 可能比统一一套更能抓 regime

## 关联

- `docs/research-kb/findings/2021-sharpe-inflation.md` (2021 年异常收益, 跟 FF3 结果一致)
- `docs/research-kb/findings/small-cap-alpha.md` (小盘 alpha, 跟 SMB beta 1.09 吻合)
- `docs/research-kb/failed/factor-addition-dilution-effect.md` (因子扩展稀释, 跟"alpha 衰减" 相关)
- `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md` Step 6-D 章节

## 不要重复的错误

- 不要在 5 年 baseline (0.6095) 上做策略调优 — 5 年窗口忽略了 2015-2018 的熊市和蓝筹期, 会选出 bug 在熊市的参数
- 不要声称"12 年 Sharpe 0.6095" — 真值是 0.5309
- 不要用默认 `WFConfig(train=750)` 做 12 年 WF — 前 755 天会被吃掉, WF 只能覆盖后 5 年
- 不要把 WF chain-link Sharpe 0.6336 当作 "OOS 稳定性验证通过" — 折间 std 1.52 + 1 个负折说明策略 regime dependent
