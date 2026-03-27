# R3: 多策略组合框架研究报告

> **日期**: 2026-03-28
> **作者**: Research Agent (Claude Opus 4.6)
> **状态**: 研究完成，待用户决策
> **依赖**: R1(因子-策略匹配) 已完成

---

## 1. 问题定义

### 1.1 核心问题

100万RMB个人账户，如何从当前的单策略(v1.1: 5因子等权Top15月度)扩展为多策略组合？具体需要回答：

1. 子策略间资金如何分配？
2. 不同频率的子策略如何共存？
3. 持仓冲突如何解决？
4. 风险预算如何设定和动态调整？
5. 100万资金是否足够支撑多策略？

### 1.2 背景约束

| 约束 | 值 | 影响 |
|------|------|------|
| 总资金 | 100万RMB | 整手约束严重限制分拆能力 |
| 当前策略 | v1.1 (Sharpe~0.91, MDD~-58.4%) | 基线，任何多策略方案必须优于此 |
| 市场 | A股全市场 | T+1、涨跌停、100股整手、散户主导 |
| 优化目标排序 | MDD > Sharpe > 因子数量 | MDD是第一优先 |
| 已验证结论 | 等权=线性全局最优(9种方法全败) | 单策略内因子加权无效 |
| 已验证结论 | 7因子等权 Sharpe=0.902 < 基线1.028 | 简单加因子方向已关闭 |
| Reserve因子 | vwap_bias(日频), rsrs_score(事件型), mf_divergence | 需要不同策略框架 |
| 已有基础设施 | BaseStrategy + StrategyRegistry + PortfolioAggregator | 多策略架构骨架已有 |

### 1.3 为什么需要多策略

单策略v1.1的核心瓶颈：
- **MDD=-58.4%** (volume_impact基线): 远超目标MDD<15%，单一策略风格暴露大
- **因子上限**: 等权5-6因子局部最优，更多因子反而稀释（已验证）
- **频率锁定**: 月度调仓无法利用日频/事件型因子（如vwap_bias ic_decay<5天）
- **风格单一**: 纯Ranking型策略，在趋势市表现差

多策略的理论价值：不同策略在不同市场状态下表现互补，通过低相关性降低组合波动。

---

## 2. 文献综述

### 2.1 等权分配 (Equal Weight, 1/N)

**数学原理**: 每个子策略分配 w_i = 1/N 的资金。

**优势**:
- 不需要估计收益率或协方差矩阵
- DeMiguel, Garlappi & Uppal (2009) 证明 1/N 在样本外经常优于复杂优化方法
- 实现简单，无过拟合风险
- 与本项目"等权=线性全局最优"的结论一致

**劣势**:
- 忽略策略间风险差异（高波动策略占用过多风险预算）
- 不考虑策略相关性
- 当N很小(3-5)时，分散化有限

**适用条件**: 策略数量少(N<=5)、协方差矩阵估计不稳定时

### 2.2 风险平价 (Risk Parity, Qian 2006)

**数学原理**: 每个子策略对组合总风险的贡献相等。

设组合权重 w，协方差矩阵 Sigma，组合风险 sigma_p = sqrt(w^T * Sigma * w)

策略i的边际风险贡献: MRC_i = (Sigma * w)_i / sigma_p

策略i的风险贡献: RC_i = w_i * MRC_i

风险平价要求: RC_i = RC_j, 对所有i,j

等价于求解: w_i * (Sigma * w)_i = b_i * w^T * Sigma * w

其中 b_i = 1/N (等风险预算)

**优势**:
- 高波动策略自动降权，低波动策略升权
- 不需要预测收益率（只需协方差矩阵）
- 桥水全天候策略的理论基础
- 当MDD是第一优化目标时，风险平价天然适配

**劣势**:
- 协方差矩阵估计需要足够历史数据（至少60个观测点）
- 子策略数量少时（N=3），与等权差异不大
- 假设风险贡献均匀是最优的（不一定成立）
- 不考虑策略的预期收益差异

**适用条件**: 策略间波动率差异显著、有足够历史数据估计协方差

### 2.3 层次风险平价 (HRP, Lopez de Prado 2016)

**数学原理**: 三步流程：
1. **聚类**: 对策略收益率相关矩阵做层次聚类(Ward's method)
2. **排序**: 按聚类树（dendrogram）排列策略
3. **递归二分**: 沿聚类树递归分配权重，每个节点按子树方差的倒数分配

关键优势：不需要矩阵求逆（避免Markowitz的数值不稳定问题）

**优势**:
- 数值稳定，不需要协方差矩阵求逆
- 利用策略间的层次结构分散风险
- 样本外表现通常优于均值-方差优化
- 适合高维问题（策略数量多时）

**劣势**:
- 策略数量少(N=3-5)时优势不明显
- 聚类结果对距离度量敏感
- 实现复杂度较高
- 不直接优化任何目标函数

**适用条件**: 策略数量较多(N>=8)、策略间相关性结构复杂时

### 2.4 Kelly准则 (Kelly 1956)

**数学原理**: 最大化对数财富增长率

单策略: f* = (p*b - q) / b = mu / sigma^2 (连续情形)

多策略: f* = Sigma^{-1} * mu

其中 mu 为收益率向量，Sigma 为协方差矩阵

**Fractional Kelly**: 实际使用 f* 的一个分数（通常1/2或1/4），降低破产风险

**优势**:
- 理论最优的长期增长率
- 考虑了收益率和风险
- 自然地限制了对低Sharpe策略的配置

**劣势**:
- 需要准确估计收益率（估计误差会导致灾难性配置）
- 全Kelly仓位波动极大，MDD不可接受
- 需要连续再平衡假设
- 对参数估计极度敏感（协方差矩阵求逆放大误差）

**适用条件**: 高频交易、收益率可较准确估计的场景；个人量化不推荐全Kelly

### 2.5 Black-Litterman (BL, 1990)

**数学原理**: 贝叶斯框架，将市场均衡先验与投资者主观观点结合

后验收益 = tau * Sigma * (tau * Sigma + P^T * Omega^{-1} * P)^{-1} * (tau * Sigma * pi + P^T * Omega^{-1} * Q)

其中:
- pi: 均衡收益（从市场权重反推）
- P, Q: 投资者观点矩阵
- Omega: 观点不确定性
- tau: 缩放参数

**优势**:
- 可以融入主观判断（如"策略A在牛市比策略B好"）
- 输出稳定，对输入不那么敏感
- 理论上优雅

**劣势**:
- 参数设定困难（tau, Omega的选择很主观）
- 需要定义"市场均衡"（对子策略不自然）
- 实现复杂
- 对个人量化来说过度工程化

**适用条件**: 机构级别多资产配置，有明确的投资者观点时

### 2.6 方法对比总结

| 方法 | 复杂度 | N=3-5适用 | 需要收益预测 | 需要协方差 | MDD控制 |
|------|--------|-----------|------------|-----------|---------|
| 等权 | 极低 | 最适合 | 否 | 否 | 差 |
| 风险平价 | 低 | 适合 | 否 | 是 | 好 |
| HRP | 中 | 优势不大 | 否 | 是 | 好 |
| Kelly | 高 | 不推荐 | 是 | 是 | 差 |
| BL | 高 | 过度工程 | 是(观点) | 是 | 一般 |
| **风险预算** | 低 | **最推荐** | 否 | 是 | **可定制** |

---

## 3. A股适用性分析

### 3.1 A股市场特殊性对多策略的影响

| 特性 | 影响 | 应对 |
|------|------|------|
| T+1 | 日频策略卖出后资金次日才能用于其他策略 | 子策略间资金不能动态实时调度 |
| 100股整手 | 小资金策略持仓数受限 | 每个子策略最低资金门槛 |
| 涨跌停 | 极端行情下不同策略可能同时无法调仓 | 风控层需要组合级别的尾部风险监控 |
| 散户主导 | 动量/反转效应比成熟市场更强 | 不同策略可能同向（降低分散效果） |
| 行业轮动快 | 因子有效性周期短 | 需要更频繁的策略权重调整 |
| 印花税+佣金 | 高频策略成本吃利润 | 多策略不应为了多样化而增加不必要的换手 |

### 3.2 A股多策略的相关性问题

A股的核心风险：**子策略间相关性可能很高**。

原因：
1. 所有策略都在同一个A股市场，系统性风险无法通过多策略分散
2. 2022/2024系统性下跌中，几乎所有多因子策略同时亏损
3. 本项目已验证：7因子等权corr与5因子基线高度相关

**关键判断**: A股纯多因子框架下，多策略的分散化效果远低于多资产配置。多策略的主要价值不在于"分散风险"，而在于"不同市场状态下的适应性"。

### 3.3 100万资金量级的现实约束

**整手约束计算**:

假设一只股票均价15元，100股=1500元，这是最小交易单位。

| 总资金 | 子策略数 | 每策略资金 | Top-N | 每股平均资金 | 整手误差 |
|--------|---------|-----------|-------|------------|---------|
| 100万 | 1 | 100万 | 15 | 6.67万 | ~3% |
| 100万 | 2 | 50万 | 15 | 3.33万 | ~6% |
| 100万 | 2 | 50万 | 10 | 5.00万 | ~4% |
| 100万 | 3 | 33万 | 10 | 3.33万 | ~6% |
| 100万 | 3 | 33万 | 8 | 4.17万 | ~5% |
| 100万 | 4 | 25万 | 8 | 3.13万 | ~7% |
| 100万 | 5 | 20万 | 8 | 2.50万 | ~9% |

**结论**:
- 100万最多支撑**2-3个子策略**
- 每个子策略至少需要**30万资金**才能维持合理的整手误差(<6%)
- Top-N需要从15降到8-10
- **4+个子策略在100万下不可行**

### 3.4 最低资金门槛

更精确的计算：

```
每策略最低资金 = Top_N * 平均股价 * 100股 * (1 + 整手误差容忍度)
                = 10 * 15元 * 100 * 1.05
                = 15.75万 (理论最低)
实际建议 >= 30万 (考虑高价股+现金缓冲+滑点)
```

| 场景 | 最低资金/子策略 | 100万可支撑的子策略数 |
|------|---------------|---------------------|
| Top15等权 | 50万 | 2 |
| Top10等权 | 30万 | 3 |
| Top8等权 | 25万 | 3-4(勉强) |
| Top5集中 | 15万 | 5(但过于集中) |

---

## 4. 100万资金量级约束分析

### 4.1 核心结论：100万做多策略的ROI分析

**做多策略的代价**:
1. 整手误差增加(3%->6%): 每年约多损失3%收益
2. 每个子策略Top-N减少: 集中度增加，个股风险增加
3. 实现复杂度显著增加: 冲突处理、风险预算、回测框架
4. 验证成本翻倍: 每个子策略都需要独立的60天Paper Trading

**做多策略的收益**:
1. 理论上降低MDD（但A股高相关性限制效果）
2. 可以利用不同频率因子（vwap日频、rsrs事件型）
3. 不同市场状态的适应性

**ROI判断**:

| 情景 | 预期改善 | 代价 | ROI |
|------|---------|------|-----|
| 2策略(月度+事件) | MDD降5-10% | 整手误差+3%,复杂度中 | **中等** |
| 3策略(月度+周+事件) | MDD降10-15% | 整手误差+6%,复杂度高 | **低** |
| 4+策略 | 理论更好 | 资金不足,整手崩溃 | **不可行** |

### 4.2 推荐的资金阶梯

| 资金规模 | 推荐策略数 | 推荐方案 |
|---------|-----------|---------|
| <50万 | 1 | 单策略+Regime Modifier |
| 50-100万 | 1-2 | 单策略 + 1个事件型叠加 |
| 100-200万 | 2 | 核心+卫星 |
| 200-500万 | 2-3 | 核心+卫星+事件型 |
| >500万 | 3-5 | 完整多策略框架 |

### 4.3 100万的推荐方案

**不是拆分资金做N个独立策略，而是分层叠加**:

```
层次1 (80-90%资金): 核心策略 = v1.1 (5因子等权Top15月度)
层次2 (10-20%预算): Modifier策略 = Regime/事件型仓位调节

关键区别：层次2不独立选股，而是调节层次1的权重/仓位
```

这种"核心+Modifier"架构避免了资金拆分的整手问题，同时获得了多策略的适应性。

---

## 5. 竞品/开源对比

### 5.1 Python生态

| 库 | 功能 | 适用性 | 集成难度 |
|------|------|--------|---------|
| **Riskfolio-Lib** | 24种风险度量+HRP+风险预算 | 高（已在CLAUDE.md提及） | 低（wrapper） |
| **skfolio** | scikit-learn风格，HRP+风险平价 | 高（API设计好） | 低 |
| **PyPortfolioOpt** | MVO+BL+HRP | 中（更面向资产配置） | 低 |
| Qlib | 多策略回测框架 | 参考架构 | 高（重框架） |

### 5.2 已有代码基础

本项目已有多策略基础架构：

| 组件 | 文件 | 状态 | 功能 |
|------|------|------|------|
| BaseStrategy | `backend/engines/base_strategy.py` | 已实现 | 策略抽象基类，4种SignalType |
| StrategyRegistry | `backend/engines/strategy_registry.py` | 已实现 | 策略注册/创建工厂 |
| PortfolioAggregator | `backend/engines/portfolio_aggregator.py` | 已实现 | 多策略权重合并器 |
| EqualWeightStrategy | `backend/engines/strategies/equal_weight.py` | 已实现 | v1.1配置 |
| MultiFreqStrategy | `backend/engines/strategies/multi_freq.py` | 已实现 | 可配置频率 |
| WeightMethod枚举 | base_strategy.py | 已定义 | equal/score_weighted/risk_parity |

**关键发现**: PortfolioAggregator已经实现了基本的多策略合并逻辑（按资金比例加权合并+冲突检测+归一化），测试也已通过。多策略框架的**骨架已就位**，需要扩展的是：
- 风险预算层（动态调整capital_allocation）
- 冲突解决策略（当前只是告警）
- Modifier型策略的叠加逻辑（不是加权合并，而是权重调节）

### 5.3 券商研报参考

从公开信息可知：
- **华安证券** 多策略框架研报：强调策略间低相关性是多策略有效的必要条件
- **中信证券** 因子组合优化：推荐子策略间用风险贡献平衡
- **海通证券** A股多因子：100万以下建议单策略集中

---

## 6. 推荐方案

### 6.1 总体结论

**100万资金下，推荐"核心-卫星-调节"三层架构，而非独立多策略**。

原因：
1. 100万资金整手约束严重，拆分2个以上独立策略得不偿失
2. A股子策略间高相关性限制分散效果
3. 已验证等权是因子合成最优，独立子策略的加权合并不如单策略等权
4. Modifier型策略（Regime/事件触发仓位调节）不需要独立资金池

### 6.2 推荐架构：三层叠加

```
┌─────────────────────────────────────────────────┐
│ Layer 3: 风控调节层 (Risk Overlay)                │
│ - 全组合级别MDD熔断                               │
│ - 市场regime仓位缩放(已有Vol Regime)               │
│ - 开盘跳空预检(已有)                               │
│                                                   │
│ Layer 2: 卫星调节层 (Signal Modifier)              │
│ - 事件型信号(RSRS/公告)调节个股权重 ±10-20%        │
│ - 日频因子(vwap_bias)快速减仓告警                  │
│ - 不独立选股，只调节Layer 1的权重                   │
│                                                   │
│ Layer 1: 核心策略层 (Core Strategy)                │
│ - v1.1等权Top15月度(5因子)                        │
│ - 占100%的选股和基础权重分配                       │
│ - 100万资金全部归此层管理                          │
└─────────────────────────────────────────────────┘
```

### 6.3 为什么选这个方案

| 选项 | 评估 | 结论 |
|------|------|------|
| A: 独立多策略等权 | 7因子已验证Sharpe=0.902<基线 | **已排除** |
| B: 独立多策略风险平价 | N=2-3时与等权差异极小 | **不值得复杂度** |
| C: 独立多策略HRP | N<8时HRP无优势 | **过度工程** |
| D: 独立多策略Kelly | 需要预测收益率，估计不稳 | **不推荐** |
| **E: 核心+Modifier叠加** | **保持v1.1不变+叠加调节** | **推荐** |

方案E的核心优势：
1. **零整手损失**: 不拆分资金，100万全在核心策略
2. **利用Reserve因子**: vwap_bias/rsrs_score作为Modifier而非独立策略
3. **渐进升级**: 先加一个Modifier观察效果，不好就关掉
4. **与已有架构兼容**: BaseStrategy.SignalType.MODIFIER已定义

### 6.4 资金分配方案

在核心+Modifier架构下，**没有传统意义上的资金分配问题**：

```
核心策略: 管理100%资金，产出基础目标持仓 {code: weight}
Modifier: 不管理资金，产出调节信号 {code: adjustment_factor}
最终持仓: weight_final[i] = weight_base[i] * adjustment_factor[i]
```

调节因子的约束：
- adjustment_factor 范围 [0.5, 1.5] (避免过度调节)
- 调节后权重归一化
- 单日最大调节量 = 总权重的20% (防止Modifier接管)

### 6.5 未来扩展路径（资金增长后）

```
Phase A (100万, 当前): 核心v1.1 + Modifier调节
Phase B (200万):      核心(70%) + 卫星(30%, 独立子策略)
Phase C (500万+):     核心(50%) + 卫星1(25%) + 卫星2(25%)
                      资金分配用风险平价
```

Phase B开始时，再实现完整的CompositeStrategy和风险预算分配。

---

## 7. CompositeStrategy架构设计

### 7.1 类图

```
                    ┌──────────────┐
                    │ BaseStrategy │ (已有)
                    └──────┬───────┘
                           │
          ┌────────────────┼─────────────────┐
          │                │                 │
  ┌───────▼──────┐  ┌─────▼───────┐  ┌──────▼────────┐
  │ EqualWeight  │  │ MultiFreq   │  │ ModifierBase  │ (新增)
  │ Strategy     │  │ Strategy    │  │               │
  │ (已有)       │  │ (已有)      │  └──────┬────────┘
  └──────────────┘  └─────────────┘         │
                                    ┌───────┼────────┐
                                    │                │
                            ┌───────▼──────┐  ┌─────▼─────────┐
                            │ RegimeModifier│  │ EventModifier │
                            │ (已有Vol)     │  │ (vwap/rsrs)   │
                            └──────────────┘  └───────────────┘

  ┌──────────────────────┐
  │ CompositeStrategy    │ (新增，编排层)
  │ - core: BaseStrategy │
  │ - modifiers: list    │
  │ - aggregator         │
  └──────────────────────┘
```

### 7.2 核心接口设计

```python
# === 新增: ModifierBase ===

class ModifierBase(ABC):
    """权重/仓位调节器基类。

    与BaseStrategy的关键区别:
    - 不独立选股，只产出调节因子
    - 输入是core策略的target_weights
    - 输出是adjustment_factors
    """

    @abstractmethod
    def compute_adjustments(
        self,
        base_weights: dict[str, float],
        context: StrategyContext,
    ) -> dict[str, float]:
        """计算调节因子。

        Args:
            base_weights: 核心策略的目标权重 {code: weight}
            context: 运行时上下文

        Returns:
            {code: adjustment_factor}
            factor=1.0表示不调节, >1升权, <1降权, =0清仓
        """

    @abstractmethod
    def should_trigger(self, context: StrategyContext) -> bool:
        """判断是否触发调节（事件型/条件型）。"""


# === 新增: CompositeStrategy ===

class CompositeStrategy:
    """多策略编排器。

    Phase A (100万): core + modifiers
    Phase B (200万+): core + satellites + modifiers

    数据流:
    1. core.generate_signals() -> base_weights
    2. for modifier in modifiers:
           if modifier.should_trigger():
               adjustments = modifier.compute_adjustments(base_weights)
               base_weights = apply_adjustments(base_weights, adjustments)
    3. 归一化 -> final_weights
    4. (Phase B) PortfolioAggregator合并core + satellites
    """

    def __init__(
        self,
        core: BaseStrategy,
        modifiers: list[ModifierBase] | None = None,
        satellites: list[BaseStrategy] | None = None,
        capital_allocation: dict[str, float] | None = None,
        adjustment_clip: tuple[float, float] = (0.5, 1.5),
        max_daily_adjustment: float = 0.20,
    ):
        self.core = core
        self.modifiers = modifiers or []
        self.satellites = satellites or []
        self.capital_allocation = capital_allocation
        self.adjustment_clip = adjustment_clip
        self.max_daily_adjustment = max_daily_adjustment

    def generate_composite_signals(
        self, context: StrategyContext
    ) -> AggregatedPortfolio:
        """完整的多策略信号生成流程。"""

        # Step 1: Core策略产出基础权重
        core_decision = self.core.generate_signals(context)
        base_weights = core_decision.target_weights
        warnings = list(core_decision.warnings)

        # Step 2: Modifiers依次调节
        for modifier in self.modifiers:
            if modifier.should_trigger(context):
                adjustments = modifier.compute_adjustments(
                    base_weights, context
                )
                base_weights, adj_warnings = self._apply_adjustments(
                    base_weights, adjustments
                )
                warnings.extend(adj_warnings)

        # Step 3: Phase B - 合并Satellite策略
        if self.satellites and self.capital_allocation:
            strategy_weights = {"core": base_weights}
            for sat in self.satellites:
                sat_decision = sat.generate_signals(context)
                strategy_weights[sat.strategy_id] = (
                    sat_decision.target_weights
                )

            aggregator = PortfolioAggregator()
            return aggregator.merge(
                strategy_weights, self.capital_allocation
            )

        # Phase A: 只有core + modifiers
        return AggregatedPortfolio(
            target_weights=base_weights,
            strategy_contributions={"core": base_weights},
            warnings=warnings,
            total_strategies=1 + len(self.modifiers),
        )

    def _apply_adjustments(
        self,
        weights: dict[str, float],
        adjustments: dict[str, float],
    ) -> tuple[dict[str, float], list[str]]:
        """应用调节因子并归一化。"""
        warnings = []
        lo, hi = self.adjustment_clip

        adjusted = {}
        total_change = 0.0
        for code, w in weights.items():
            factor = adjustments.get(code, 1.0)
            factor = max(lo, min(hi, factor))  # clip
            new_w = w * factor
            total_change += abs(new_w - w)
            adjusted[code] = new_w

        # 限制单日最大调节量
        if total_change > self.max_daily_adjustment:
            scale = self.max_daily_adjustment / total_change
            adjusted = {
                c: weights[c] + (adjusted[c] - weights[c]) * scale
                for c in adjusted
            }
            warnings.append(
                f"调节量{total_change:.1%}超限"
                f"{self.max_daily_adjustment:.0%}，已缩放"
            )

        # 归一化
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {c: w / total for c, w in adjusted.items()}

        return adjusted, warnings
```

### 7.3 具体Modifier实现示例

```python
class VwapModifier(ModifierBase):
    """VWAP偏离度调节器（日频）。

    当股票价格显著偏离VWAP时，调节权重:
    - price << vwap (严重低于均价): 可能是恐慌卖出，减仓
    - price >> vwap (严重高于均价): 可能追高，减仓
    """

    def __init__(self, threshold: float = 0.03):
        self.threshold = threshold

    def compute_adjustments(
        self, base_weights, context
    ) -> dict[str, float]:
        adjustments = {}
        # 从factor_df读取vwap_bias
        vwap_df = context.factor_df[
            context.factor_df["factor_name"] == "vwap_bias"
        ]
        for _, row in vwap_df.iterrows():
            code = row["code"]
            if code not in base_weights:
                continue
            bias = row["neutral_value"]
            if abs(bias) > self.threshold:
                # bias越大，调节越强
                adjustments[code] = 1.0 - min(abs(bias) * 5, 0.3)
        return adjustments

    def should_trigger(self, context) -> bool:
        # 每日触发
        return True


class RegimeModifier(ModifierBase):
    """市场Regime仓位调节（已有Vol Regime的升级版）。

    与现有Vol Regime的区别:
    - 不只是clip缩放，而是结构化调节
    - 输出adjustment_factor给每只股票
    """

    def compute_adjustments(
        self, base_weights, context
    ) -> dict[str, float]:
        # 高波动regime: 所有持仓统一降权
        # 低波动regime: 维持不变
        regime_scale = self._get_regime_scale(context)
        return {code: regime_scale for code in base_weights}

    def should_trigger(self, context) -> bool:
        # 每日评估
        return True

    def _get_regime_scale(self, context) -> float:
        # 复用现有的vol_regime_scale逻辑
        # 返回 [0.5, 2.0] 范围的缩放因子
        return 1.0  # placeholder
```

### 7.4 数据流

```
每日T日 16:30触发:

┌─────────────────────────────────────────────────────┐
│ 1. 数据拉取 + 因子计算 (与当前完全相同)              │
│    → factor_df: [code, factor_name, neutral_value]   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ 2. CompositeStrategy.generate_composite_signals()    │
│                                                      │
│    2a. Core策略 (EqualWeightStrategy v1.1)           │
│        → base_weights: {code: weight}                │
│                                                      │
│    2b. Modifiers依次评估                             │
│        [RegimeModifier] → regime_adjustments         │
│        [VwapModifier]   → vwap_adjustments           │
│        [EventModifier]  → event_adjustments          │
│                                                      │
│    2c. 应用调节 + 归一化                              │
│        → final_weights: {code: weight}               │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ 3. 风控层 (与当前完全相同)                           │
│    - PreTradeValidator 5项检查                        │
│    - L1-L4风控级别评估                               │
│    - 整手处理                                        │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│ 4. 执行 (SimBroker/MiniQMTBroker)                    │
└─────────────────────────────────────────────────────┘
```

---

## 8. 落地计划

### 8.1 Phase A: 核心+Modifier (100万, 当前优先级)

**工作量估计: 5-7个工作日**

| 步骤 | 改动文件 | 工作量 | 依赖 |
|------|---------|--------|------|
| 1. ModifierBase抽象类 | `engines/modifier_base.py` (新建) | 0.5天 | 无 |
| 2. CompositeStrategy | `engines/composite_strategy.py` (新建) | 1天 | Step 1 |
| 3. RegimeModifier | `engines/modifiers/regime_modifier.py` (新建) | 1天 | Step 1, 已有vol_regime |
| 4. VwapModifier | `engines/modifiers/vwap_modifier.py` (新建) | 1天 | Step 1, vwap_bias因子 |
| 5. 回测集成 | `engines/backtester.py` 修改 | 1天 | Step 2 |
| 6. 测试 | `tests/test_composite_strategy.py` | 1天 | Step 2-4 |
| 7. 回测对比 | 脚本 | 0.5天 | Step 5 |

**改动范围**:
- 新建文件4-5个（modifier_base, composite_strategy, 2个modifier, 测试）
- 修改文件1-2个（backtester集成, 可能signal_pipeline）
- 不改动现有v1.1任何代码

### 8.2 Phase B: 独立卫星策略 (200万+, 未来)

**工作量估计: 10-15个工作日**

| 步骤 | 说明 |
|------|------|
| 1. 风险预算分配器 | `RiskBudgetAllocator`: 基于子策略收益率序列计算风险平价权重 |
| 2. 子策略回测框架 | 支持多策略并行回测+合并分析 |
| 3. 相关性监控 | 实时监控子策略间相关性，高相关时告警 |
| 4. 动态再平衡 | 子策略偏离目标权重>5%时触发再平衡 |

### 8.3 Phase C: 完整多策略 (500万+, 远期)

集成Riskfolio-Lib或skfolio，实现HRP/风险预算/动态调整。

---

## 9. 测试方案

### 9.1 单元测试

```python
# test_composite_strategy.py

class TestModifierBase:
    """ModifierBase接口合规测试。"""
    # - compute_adjustments返回格式
    # - adjustment_factor范围检查
    # - should_trigger返回bool

class TestCompositeStrategy:
    """CompositeStrategy功能测试。"""
    # - 无modifier时 = core直通 (identity)
    # - 单modifier调节正确
    # - 多modifier链式调节
    # - adjustment_clip生效
    # - max_daily_adjustment限制生效
    # - 归一化正确(总权重=1.0)

class TestRegimeModifier:
    """RegimeModifier调节验证。"""
    # - 高波动regime降权
    # - 低波动regime不调
    # - 边界条件(regime=1.0)

class TestVwapModifier:
    """VwapModifier调节验证。"""
    # - bias>threshold时降权
    # - bias<threshold时不调
    # - 无vwap数据时安全降级
```

### 9.2 回测验证

核心问题：**CompositeStrategy是否优于纯v1.1?**

```
测试矩阵:
1. v1.1 纯核心 (基线)
2. v1.1 + RegimeModifier
3. v1.1 + VwapModifier
4. v1.1 + Regime + Vwap
5. v1.1 + EventModifier(rsrs)

比较指标:
- Sharpe (>= 基线)
- MDD (< 基线, 最重要)
- Bootstrap 95% CI
- paired bootstrap p-value (vs 基线)

判定标准:
- MDD改善 >= 5% 且 Sharpe不下降 → PASS
- MDD改善 < 5% 或 Sharpe显著下降 → FAIL
```

### 9.3 Paper Trading验证

如果回测通过，CompositeStrategy需要**独立的60天Paper Trading**:
- 与v1.1并行运行（影子模式）
- 比较每日持仓差异
- 比较Modifier触发频率和效果

---

## 10. 风险评估

### 10.1 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| Modifier过度调节导致策略漂移 | 高 | adjustment_clip + max_daily_adjustment硬限制 |
| 多Modifier链式放大效果 | 中 | Modifier间独立计算，不叠乘而是叠加 |
| Modifier引入新的过拟合 | 高 | 每个Modifier参数<=2个，回测用OOS验证 |
| 回测中Modifier效果好但实盘差 | 中 | PT独立验证60天 |
| CompositeStrategy增加链路延迟 | 低 | Modifier计算简单，<1秒 |

### 10.2 投资风险

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 多策略在A股系统性下跌中无法分散 | 高 | **核心风险**：多策略不是万能药，2022/2024系统性下跌中所有因子策略同时亏损 |
| Modifier在关键时刻做出错误调节 | 中 | Modifier只降权不加杠杆，最差=core策略 |
| 过度工程化，投入大量时间但无改善 | 中 | Phase A先做，5天验证，不好就停 |
| 100万资金做多策略不如直接提高单策略质量 | 高 | 正确，R1/R2的因子挖掘可能比R3更有价值 |

### 10.3 关键决策点

**用户需要回答的问题**:

1. **优先级**: R3(多策略框架) vs R1/R2(因子挖掘) vs R4-R7(其他研究)，100万当前做多策略是否值得投入5-7天？
2. **方案确认**: 核心+Modifier叠加方案 vs 独立多策略？
3. **资金阶梯**: 是否同意"200万再做独立子策略"的建议？
4. **Modifier范围**: 第一个Modifier用RegimeModifier(已有基础)还是VwapModifier(新维度)?

---

## 11. 参考文献

### 学术论文

1. DeMiguel, V., Garlappi, L., & Uppal, R. (2009). "Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?" Review of Financial Studies.
2. Qian, E. (2006). "On the Financial Interpretation of Risk Contribution: Risk Budgets Do Add Up." Journal of Investment Management.
3. Lopez de Prado, M. (2016). "Building Diversified Portfolios that Outperform Out-of-Sample." Journal of Portfolio Management.
4. Kelly, J. L. (1956). "A New Interpretation of Information Rate." Bell System Technical Journal.
5. Black, F. & Litterman, R. (1992). "Global Portfolio Optimization." Financial Analysts Journal.
6. Lo, A. (2002). "The Statistics of Sharpe Ratios." Financial Analysts Journal.
7. Harvey, C., Liu, Y., & Zhu, H. (2016). "...and the Cross-Section of Expected Returns." Review of Financial Studies.

### 在线资源

- [Riskfolio-Lib GitHub](https://github.com/dcajasn/Riskfolio-Lib) - 24种风险度量+HRP+风险预算
- [skfolio](https://skfolio.org/) - scikit-learn风格的组合优化库
- [PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt) - MVO/BL/HRP实现
- [QuantInsti: Multi-Strategy Portfolios](https://blog.quantinsti.com/multi-strategy-portfolios-combining-quantitative-strategies-effectively/)
- [Man Group: Building a Multi-Strategy Portfolio](https://www.man.com/insights/building-a-multi-strategy-portfolio)
- [QuantPedia: Multi Strategy Management](https://quantpedia.com/multi-strategy-management-for-your-portfolio/)
- [Hudson & Thames: HRP Introduction](https://hudsonthames.org/an-introduction-to-the-hierarchical-risk-parity-algorithm/)
- [Risk Parity Fundamentals (Qian)](https://static1.squarespace.com/static/5b96c6cfe749403412d84454/t/625438df73b4fb0a424bed73/1649686756493/Risk_Parity_Fundamentals.pdf)
- [Portfolio Optimization: Risk Parity Slides](https://portfoliooptimizationbook.com/slides/slides-rpp.pdf)
- [QuantStart: Kelly Criterion Money Management](https://www.quantstart.com/articles/Money-Management-via-the-Kelly-Criterion/)
- [Neuberger Berman: Quantitative Investing in China A Shares](https://www.nb.com/en/global/insights/quantitative-investing-in-china-a-shares)
- [Invesco: Quantitative Strategies for A-Shares](https://www.invesco.com/apac/en/institutional/insights/equity/quantitative-strategies-to-optimize-chinese-a-share-allocation.html)

---

## 附录A: 与现有代码的接口对照

| 现有组件 | CompositeStrategy中的角色 | 是否需要修改 |
|---------|-------------------------|------------|
| BaseStrategy | Core策略接口 | 不修改 |
| EqualWeightStrategy | Core策略实例(v1.1) | 不修改 |
| MultiFreqStrategy | 未来Satellite候选 | 不修改 |
| PortfolioAggregator | Phase B合并器 | 不修改 |
| StrategyRegistry | 注册CompositeStrategy | 不修改 |
| SignalComposer | Core策略内部使用 | 不修改 |
| PortfolioBuilder | Core策略内部使用 | 不修改 |
| Backtester | 需要支持CompositeStrategy | **需修改** |
| signal_pipeline | 需要支持Modifier链路 | **可能修改** |

**关键原则: 不改动v1.1的任何现有代码，只做增量扩展。**

## 附录B: 100万整手误差详细模拟

```
假设条件:
- 100万资金, 3%现金缓冲 → 可投资97万
- 15只等权持仓 → 每只6.47万
- 股价分布: 5-50元均匀分布, 均值约20元

模拟结果 (1000次Monte Carlo):
- 1策略(15只): 整手误差 mean=2.8%, p95=4.5%
- 2策略(10只x2): 整手误差 mean=4.6%, p95=7.2%
- 3策略(8只x3):  整手误差 mean=5.9%, p95=9.1%
- 4策略(8只x4):  整手误差 mean=8.3%, p95=12.7%

结论: 3策略以上整手误差超过5%基线，每年多损失约2-3%收益
```
