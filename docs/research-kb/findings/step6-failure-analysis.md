# Step 6-E/F/G/H 实验失败分析

**日期**: 2026-04-10 | **数据窗口**: 2014-01 ~ 2026-04

---

## 1. 实验成功/失败清单

### 成功 (3/14)
| 实验 | 结论 | 指标 |
|------|------|------|
| Partial SN b=0.50 | 唯一有效Modifier | inner 0.68, OOS 0.6521, MDD -39.35% |
| 噪声鲁棒性测试 | 21因子全PASS, 0 fragile | retention ≥0.59@20% |
| IC口径统一 | ic_calculator.py铁律19 | 53因子×12年=84K行IC入库 |

### 失败 (11/14)
| 实验 | 假设 | 实际结果 | Step |
|------|------|---------|------|
| 12年WF OOS | 策略稳定 | std=1.52 UNSTABLE | 6-D |
| Regime线性检测 | 宏观指标预测regime | 5指标全p>0.05 | 6-E |
| 因子替换(stability) | 窗口变体更优 | p=0.92不显著 | 6-F |
| 完全SN(b=1.0) | 消除SMB暴露 | 损11% Sharpe | 6-F |
| Vol-targeting | 控制波动率 | 3方案全损alpha | 6-G |
| DD-aware sizing | 降低MDD | 后视偏差, MDD反而更差 | 6-G |
| 组合Modifier | 多维度调整 | 叠加更差, 互相干扰 | 6-G |
| Regime动态beta | 自适应SN | static全面优于dynamic | 6-H |
| Regime binary | 牛熊切换 | 不如static | 6-H |
| LightGBM 5因子 | ML提升 | Sharpe=0.68 < 等权0.83 | G1 |
| LightGBM 17因子 | 更多特征 | IC=0.067正但Sharpe=0.09 | 6-H |

---

## 2. 三大失败模式

### 模式A：错误层面干预
**症状**: 在仓位层面解决信号层问题。
**案例**: Vol-targeting, DD-aware — 策略波动率来自选股(beta暴露)非仓位大小。缩减仓位不减波动率但减收益。
**教训**: 先诊断问题来源层(信号/组合/执行)，再在对应层干预。

### 模式B：线性方法对非线性现象
**症状**: 用线性回归/相关性分析捕捉regime转换。
**案例**: Regime线性检测(5指标全p>0.05), Regime动态beta(线性映射RSV→beta)。
**教训**: 市场regime转换是非线性突变。需要HMM/changepoint detection等非线性方法。

### 模式C：predict-then-optimize次优
**症状**: 先预测(IC)再优化(选股)，两步分离。
**案例**: LightGBM IC=0.067正但Sharpe=0.09。IC→Top-N是非线性映射，弱IC的Top-N选股噪声极大。
**教训**: 需要End-to-End方法(直接用Sharpe/PnL作loss)，或RD-Agent式因子-模型联合优化。

---

## 3. LightGBM IC正但Sharpe为零的3个根因

1. **IC→选股非线性**: IC=0.067意味着截面排名只比随机好6.7%。对Top-20选股来说，噪声主导信号。
2. **月度换手成本**: 弱信号的月度换手成本(佣金+滑点+冲击)吃掉微弱alpha。
3. **特征共线**: 17因子来自同源量价数据(corr>0.6)，信息维度不足。ML无法从高度共线的输入中提取额外alpha。

---

## 4. 学术界4个新方向

| 方向 | 代表论文/工具 | 核心思路 |
|------|-------------|---------|
| End-to-End Learning | Zhang et al. 2020 | 直接用portfolio Sharpe作loss训练 |
| Multi-Task Learning | RD-Agent (Microsoft) | 因子+模型+组合联合优化 |
| Graph Neural Network | FinGAT, HIST | 利用股票间行业/供应链关系 |
| Reinforcement Learning | FinRL | 交易执行和仓位管理联合优化 |

---

## 5. 15条关键教训

见 LESSONS_LEARNED.md LL-037 ~ LL-051（Step 6系列）。
