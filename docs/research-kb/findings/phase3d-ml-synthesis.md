# Phase 3D: ML Synthesis — Final Report

> **结论: ML预测层 CLOSED** — 4个实验全部 FAIL，最优A-REG(Sharpe=0.54)仅为基线的62%。
> **日期**: 2026-04-14
> **基线**: 等权CORE3+dv_ttm+SN050, WF 5-fold OOS Sharpe=0.8659, MDD=-13.91%

---

## 1. 实验设计

### 目标
验证LightGBM能否通过非线性因子交互超越等权alpha上限(0.8659)。

### 架构
使用 `WalkForwardEngine` (System 2) 保证与等权基线完全相同的fold/回测/NAV链接:
- WFConfig: 5-fold, 750d train, 250d test, gap=5
- 回测: SimpleBacktester, T+1开盘执行, 三因素滑点, 月度调仓
- SN: b=0.50 (与基线一致)

### 实验矩阵

| Exp ID | 因子集 | 因子数 | 模式 | 说明 |
|--------|--------|--------|------|------|
| A-REG | CORE4 + 独立因子 | 11 | regression | 低相关性因子 |
| A-LR | 同上 | 11 | lambdarank | 排名优化 |
| B-REG | 全部PASS因子 | 33 | regression | 大因子集 |
| B-LR | 同上 | 33 | lambdarank | 大因子集+排名 |

### LightGBM参数
```
objective: regression/lambdarank, boosting: gbdt, lr: 0.05
num_leaves: 63, max_depth: 6, min_child_samples: 50
reg_alpha: 1.0, reg_lambda: 5.0, subsample: 0.8, colsample: 0.8
device: GPU (RTX 5070), max_bin: 63, seed: 42
early_stopping: patience=50, max_rounds=500
```

---

## 2. 结果总览

| Exp | 因子 | OOS Sharpe | OOS MDD | 年化 | vs 基线 | 负fold | FI稳定性 |
|-----|------|-----------|---------|------|---------|--------|----------|
| **基线** | **4** | **0.8659** | **-13.91%** | **—** | **—** | **0/5** | **—** |
| A-REG | 11 | 0.5366 | -24.15% | 10.69% | -38.0% | 0/5 | 0.620 |
| A-LR | 11 | 0.14~0.28* | -47~58% | ~1% | -67~84% | 2~3/5 | ~0.4 |
| B-REG | 33 | 0.3043 | -42.93% | 4.67% | -64.9% | 2/5 | 0.320 |
| B-LR | 33 | 0.0428 | -60.42% | -2.97% | -95.1% | 2/5 | 0.386 |

*A-LR GPU LambdaRank不可复现, 多次运行Sharpe在0.14~0.28之间

### PASS标准检查

| 标准 | A-REG | A-LR | B-REG | B-LR |
|------|-------|------|-------|------|
| OOS Sharpe > 0.8659 | ❌ 0.54 | ❌ 0.14~0.28 | ❌ 0.30 | ❌ 0.04 |
| 无灾难fold (>-0.5) | ✅ | ❌ Fold2=-0.72 | ✅ | ❌ Fold2=-0.80 |
| FI稳定性 > 0.5 | ✅ 0.62 | ❌ ~0.4 | ❌ 0.32 | ❌ 0.39 |
| 可复现 | ✅ | ❌ | ✅* | ❌* |

*REG模式可复现, LR模式GPU非确定性导致不可复现

**全部4个实验 FAIL。**

---

## 3. Per-Fold 分析 (A-REG — 最优配置)

| Fold | 训练期 | 测试期 | Train IC | Valid IC | OOS Sharpe | MDD | best_iter |
|------|--------|--------|----------|----------|-----------|------|-----------|
| 0 | 2018-01~2021-01 | 2021-02~2022-02 | 0.154 | 0.081 | 0.88 | -14.2% | 37 |
| 1 | 2019-01~2022-02 | 2022-02~2023-03 | 0.193 | 0.101 | 0.10 | -24.2% | 62 |
| 2 | 2020-01~2023-02 | 2023-03~2024-03 | 0.223 | 0.107 | 0.16 | -23.3% | 42 |
| 3 | 2021-02~2024-03 | 2024-03~2025-03 | 0.148 | 0.092 | 0.83 | -16.9% | 30 |
| 4 | 2022-02~2025-03 | 2025-03~2026-04 | 0.122 | 0.040 | 0.75 | -11.9% | 12 |

**观察:**
- Train IC (0.12~0.22) 远大于 Valid IC (0.04~0.11) → **过拟合**
- Train/Valid IC比值: 1.5~3.0x，最严重在Fold 4 (3.05x)
- Fold 1&2 OOS最差(0.10/0.16)，对应2022-2023熊市 → ML在下行市场预测能力弱
- best_iter很小(12~62)，说明early stopping快速触发，模型复杂度极低

---

## 4. 特征重要性分析

### A-REG Top-10 (5-fold平均gain importance)

| # | 特征 | 平均增益 | 属性 |
|---|------|---------|------|
| 1 | reversal_60 | 2266 | Reserve因子 |
| 2 | turnover_mean_20 | 2069 | **CORE4** |
| 3 | price_level_factor | 1314 | Reserve因子 |
| 4 | dv_ttm | 1305 | **CORE4** |
| 5 | bp_ratio | 1062 | **CORE4** |
| 6 | volatility_20 | 975 | **CORE4** |
| 7 | RSQR_20 | 816 | Alpha158 |
| 8 | IMIN_20 | 765 | Alpha158 |
| 9 | a158_cord30 | 414 | Alpha158 |
| 10 | price_volume_corr_20 | 409 | Reserve因子 |
| 11 | CORD5 | 0 | 99.8% NaN无用 |

**关键发现:**
- CORE4因子占Top-6中的4个 → ML主要在学习CORE因子的非线性组合
- 没有发现新的alpha来源
- CORD5 (99.8% NaN) 完全无用，应从特征集中移除

### B-LR 特征不稳定性 (FI=0.386)

B-LR Per-fold Top-5特征完全不同:
- Fold 0: ln_market_cap, ep_ratio, reversal_20, turnover_mean_20, bp_ratio
- Fold 1: price_volume_corr_20, a158_std60, ln_market_cap, reversal_60, price_level_factor
- Fold 2: a158_vsump60, a158_std60, reversal_60, price_level_factor, gap_frequency_20
- Fold 3: dv_ttm, amihud_20, price_level_factor, reversal_20, ln_market_cap
- Fold 4: dv_ttm, amihud_20, volatility_20, a158_std60, ln_market_cap

→ 33因子时模型每fold学到完全不同的模式，泛化能力极差。

---

## 5. 根因分析

### 5.1 为什么ML不如等权？

**核心矛盾**: ML增加了模型复杂度但没有增加信息量。

等权CORE4的signal是：`score = mean(z(turnover_mean_20), z(volatility_20), z(bp_ratio), z(dv_ttm))`

ML实际学到的也是这4个因子的某种加权组合（Top-6 gain importance有4个是CORE4）。但ML引入的非线性 **在OOS中不稳定**，导致：
- 信号精度下降（从等权的"稳定平均"变成"过拟合的非线性"）
- Fold间一致性下降（best_iter波动12~62）
- 选股偏差增大（ML倾向集中选某些特征空间的股票）

### 5.2 更多因子为什么更差？

| 维度 | A (11因子) | B (33因子) |
|------|-----------|-----------|
| Sharpe | 0.54 | 0.30 |
| FI稳定性 | 0.62 | 0.32 |
| 负fold | 0/5 | 2/5 |

增加因子的问题:
1. **噪声因子稀释信号** — 33因子中大量因子IC<0.03，是噪声而非信号
2. **维度诅咒** — 样本量不变(~4000股/天)，维度翻3倍，有效样本密度骤降
3. **多重共线性** — 33因子存在大量相关性(如reversal_5/10/20/60)，LightGBM分裂时在冗余特征间随机选择
4. Phase 2.1 Exp-B已有相同结论: 16因子IC降25%

### 5.3 LambdaRank为什么更差？

1. **GPU非确定性** — LambdaRank + GPU的梯度计算有浮点精度随机性（即使`deterministic=True`仍有Fold 0/4不一致）
2. **排名目标vs回归目标** — Top-20选股实际上是一个精确排名任务，但LambdaRank优化的是NDCG@20（pair-wise比较），在小样本组（每天~4000股）上梯度信噪比低
3. **标签离散化损失** — per-date quantile labels (5 bins)丢弃了连续return的细粒度信息
4. Phase 2.2/2.4已确认: LambdaRank在此框架下不如regression

### 5.4 Bug修复前后对比

本次实验发现并修复3个Bug:

| Bug | 影响 | 修复前 | 修复后 |
|-----|------|--------|--------|
| `_PRICE_COLS`缺少`amount` | 所有交易500bps最大滑点 | Sharpe=-1.60 | Sharpe=+0.54 |
| SN尺度不匹配 | ML信号(±0.05)被SN(±1.5)覆盖 | 选股随机化 | z-score后SN正常 |
| 全局quantile标签 | LambdaRank部分组零梯度 | 训练效率低 | per-date quantile |

**`amount`缺失是灾难性Bug** — 导致每次交易额外损失5%(500bps)，~72%年化滑点损失。修复后ML结果从负值恢复到正值区间。

---

## 6. 历史一致性

这是第5次独立验证ML无法超越等权:

| 实验 | 日期 | ML Sharpe | 等权Sharpe | 结论 |
|------|------|-----------|-----------|------|
| G1 LightGBM 17因子 | 2026-04-09 | 0.68 | 0.83 | ML落后 |
| Step 6-H WF | 2026-04-10 | 0.09 | 0.65 | ML大幅落后 |
| Phase 2.1 E2E | 2026-04-11 | -0.99 (实盘) | 0.62 | sim-to-real gap |
| Phase 2.2 Gate | 2026-04-11 | 0.56 (LR+SN) | 0.62 | ML不如等权 |
| **Phase 3D** | **2026-04-14** | **0.54 (最优)** | **0.87** | **ML大幅落后** |

---

## 7. 结论与决策

### ML预测层 — **CLOSED**

基于以下证据:
1. 4个实验全部 FAIL (最优0.54 vs 基线0.87)
2. 更多因子 → 更差结果 (11因子0.54 > 33因子0.30)
3. Feature-C 不执行 (Feature-A/B均未达标)
4. 5次独立验证结论一致
5. 特征重要性显示ML仅在学习CORE4的非线性变体，无新alpha

### 瓶颈确认

**信号层信息量不足，非模型复杂度问题。** 当前量价+基本面因子在A股市场的截面预测力天花板~IC=0.09。ML无法从相同因子中提取超过等权平均的信息。

### 下一步方向

ML在当前因子集上已穷尽。突破需要新的信息来源:
1. **另类数据因子** — PEAD-SUE(已有IC=-0.098), 北向资金行为, 资金流向
2. **分钟级微结构因子** — 139M行minute_bars待挖掘
3. **Phase 3自动化** — 因子生命周期管理 + Rolling WF + IC监控
4. **Phase 4 PT重启** — 等权CORE3+dv_ttm配置已就绪

---

## 8. 可复现性验证

| 实验 | 可复现? | 验证方法 |
|------|---------|---------|
| A-REG | ✅ 完全一致 | 两次运行5-fold Sharpe全部match (diff=0) |
| A-LR | ❌ 不可复现 | GPU LambdaRank残余非确定性 (3/5 fold一致) |
| B-REG | ✅ (seed=42) | 单次运行, REG模式deterministic |
| B-LR | ❌ (GPU限制) | 同A-LR, LambdaRank+GPU问题 |

`deterministic=True` + 显式seed修复后LR从2/5→3/5 fold一致，但GPU LambdaRank无法保证bit-level可复现。

---

## 附录: 修复的Bug清单

1. **`_PRICE_COLS`缺少`amount`列** (phase3d_ml_synthesis.py:131) — 根因: Parquet缓存包含amount但加载时未选择该列, 导致slippage_model对所有交易返回500bps最大滑点
2. **SN z-score缺失** (phase3d_ml_synthesis.py:673-684) — ML预测值(~±0.05)未标准化就与SN(~±1.5)混合, 信号被市值完全覆盖
3. **全局quantile标签** (phase3d_ml_synthesis.py:432-455) — LambdaRank使用全局quantile导致部分日期组标签全相同, 梯度为零
4. **LambdaRank非确定性** (phase3d_ml_synthesis.py:111-114) — 添加`deterministic=True`+显式seed, 改善但未完全解决GPU LambdaRank问题
