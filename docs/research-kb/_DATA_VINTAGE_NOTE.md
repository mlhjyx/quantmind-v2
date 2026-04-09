# Research KB Data Vintage Notice

> **创建**: 2026-04-10 (Step 6-F)
> **目的**: 标记 research-kb 内所有 IC/Sharpe/alpha 数字的数据 vintage

---

## 关键事实

**所有 dated 2026-04-09 之前的 research-kb 文件** (除 `wf-oos-instability-step6d.md`, `_DATA_VINTAGE_NOTE.md` 本身) 引用的 IC / Sharpe / alpha 数字基于 **pre-Step 6-E 的旧 factor_ic_history 数据**, 当时的口径是:

- IC 公式: 不统一 (compute_factor_ic.py 用 raw return, factor_profiler 用超额收益)
- 数据范围: 5 年 (2021-01-04 ~ 2026-04-02), 不是 12 年
- 数据格式: factor_values 表 code 格式混合 (Step 1 之前部分有后缀, 部分无后缀)
- IVOL 等因子的方向标注可能错误 (registry 写 +0.067, 实测 -0.10)

**Step 6-E (2026-04-09)** 完成的修复:
- 新建 `backend/engines/ic_calculator.py` (铁律 19 标准, version 1.0.0, id `neutral_value_T1_excess_spearman`)
- 用 `scripts/fast_ic_recompute.py` 在 12 年数据 (2014-2026) 上重算 53 个因子的 IC, 写入 factor_ic_history (~84,000 行, 含 26K+ pre-2021 行)
- 修正 IVOL 方向 (registry 改为 -0.0667, direction=-1)

**Step 6-F (2026-04-10)** 进一步发现:
- CORE 5 因子 IC **没有衰减** (retention 0.84-1.04 between 2014-2020 vs 2021-2026)
- 因子替换 paired bootstrap 全部不显著 (p > 0.7) → 旧 KB 中 "因子 IR 高就更好" 的论断不成立
- Size-neutral 强制后 Sharpe -0.06 (10.6% annual vs 13.1%) → 旧 KB 中 "small-cap-alpha" 仍然成立但是 trade-off 比预期大
- Regime 5 个候选指标全部 p > 0.05 → 旧 KB 中"线性 regime 检测"方向被否决

---

## 各文件的 vintage 状态

下表标注每个 KB 文件的 IC 数据来源:

| 文件 | 日期 | IC vintage | 是否需要重审 |
|------|------|-----------|------------|
| **decisions/** | | | |
| factor-profile-before-template.md | <2026-04-09 | 旧 (pre Step 6-E) | ⚠️ 概念性结论, 12yr 仍部分成立 |
| mdd-layer-xd.md | <2026-04-09 | 旧 | ⚠️ 概念性, 不引用具体 IC |
| ml-pipeline-eval-only.md | <2026-04-09 | 旧 (G1 Sharpe 0.68 是 5yr) | ⚠️ 12yr ML 重测 (待 Part 2) |
| monthly-equal-weight-baseline.md | 2026-03-28 | 旧 (Sharpe=0.91 是 5yr) | ⚠️ 已被 Step 6-D 12yr=0.5309 取代 |
| pms-v1-tiered-protection.md | <2026-04-09 | 旧 | ✅ PMS 设计独立, 不依赖 IC |
| **failed/** | | | |
| biweekly-rebalance.md | <2026-04-09 | 旧 | ⚠️ Sharpe 数字基于 5yr |
| fundamental-factors.md | 2026-04-03 | 旧 | ⚠️ 12yr 重审推迟 |
| g2-risk-parity.md | 2026-04-03 | 旧 | ✅ 等权 vs RP 结论结构性, 仍成立 |
| g25-dynamic-position.md | <2026-04-09 | 旧 | ⚠️ 5yr 结论 |
| hard-stop-loss.md | <2026-04-09 | 旧 | ⚠️ |
| mf-divergence-fake-ic.md | <2026-04-09 | 旧 | ✅ "IC 必须可追溯" 教训本身仍成立 |
| northbound-modifier-v1.md | <2026-04-09 | 旧 | ⚠️ Step 6-E factor_ic_history 北向因子各只 1 行 IC |
| pms-v2-consecutive-days.md | <2026-04-09 | 旧 | ✅ PMS 设计独立 |
| **findings/** | | | |
| 2021-sharpe-inflation.md | 2026-04-03 | 旧 (5yr 视角) | ✅ Step 6-D 逐年度回测确认 2021 Sharpe=3.48 是异常值 |
| factor-addition-dilution-effect.md | 2026-04-08 | 旧 (5yr paired bootstrap) | ⚠️ Step 6-F Part 1 验证: 单因子替换也不显著 (与稀释一致) |
| industry-cap-hurts-alpha.md | <2026-04-09 | 旧 | ⚠️ 12yr 行业约束未重测 |
| low-volatility-anomaly.md | <2026-04-09 | 旧 | ✅ Step 6-E volatility_20 IR=-0.94 (12yr) 仍成立 |
| northbound-behavior-patterns.md | <2026-04-09 | 旧 | ⚠️ 北向因子 IC 缺失 |
| northbound-reverse-indicator.md | <2026-04-09 | 旧 | ⚠️ |
| small-cap-alpha.md | 2026-04-03 | 旧 (5yr 分市值) | ✅ Step 6-F Part 3 size-neutral 确认 (Sharpe -0.06 trade-off) |
| wf-oos-instability-step6d.md | 2026-04-09 | 新 (Step 6-D) | ✅ |

---

## 重审优先级

### 高 (结论可能彻底改变)
- `failed/fundamental-factors.md`: 5yr 测试基本面无效, 12yr 是否仍如此未知
- `failed/g25-dynamic-position.md`: 5yr 动态仓位失败, 12yr 多了 2 次 regime 切换
- `decisions/ml-pipeline-eval-only.md`: G1 5yr ML Sharpe 0.68, Part 2 21因子 12yr 待跑

### 中 (结论方向可能不变, 数字需要更新)
- `findings/factor-addition-dilution-effect.md`: 已被 Step 6-F Part 1 重新验证 (paired bootstrap 全不显著, 不是单纯稀释而是因子相关性)
- `failed/biweekly-rebalance.md`
- `findings/industry-cap-hurts-alpha.md`

### 低 (结构性结论, 不依赖具体 IC 数字)
- `failed/g2-risk-parity.md`
- `failed/mf-divergence-fake-ic.md`
- `findings/2021-sharpe-inflation.md`
- `findings/low-volatility-anomaly.md`
- `findings/small-cap-alpha.md`

---

## 数据 vintage 引用规则 (新建议)

新写入 research-kb 的文件**必须包含** vintage 标签:

```markdown
---
date: 2026-XX-XX
ic_calculator_version: 1.0.0
ic_calculator_id: neutral_value_T1_excess_spearman
data_range: 2014-01-02 ~ 2026-04-09  # 12yr
universe: A 股 (排除 ST/BJ/停牌/新股)
sources:
  - cache/baseline/factor_ic_yearly_matrix.json (Step 6-E 输出)
  - cache/baseline/factor_swap_bootstrap.json (Step 6-F 输出)
---
```

参考: `docs/research-kb/findings/wf-oos-instability-step6d.md` (已是新格式).

---

## 相关

- **铁律 19** (CLAUDE.md): IC 定义全项目统一, 走 ic_calculator
- **铁律 20** (CLAUDE.md, Step 6-F): 因子噪声鲁棒性 G_robust
- **基础设施**: `backend/engines/ic_calculator.py` + `scripts/fast_ic_recompute.py` + `scripts/research/noise_robustness.py`
- **数据源**: `cache/baseline/factor_ic_yearly_matrix.json` (12yr CORE 5 矩阵)
