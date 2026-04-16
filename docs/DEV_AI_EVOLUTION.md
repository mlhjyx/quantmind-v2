# QuantMind V2 — AI 闭环进化设计文档

> **版本**: 2.0 | **日期**: 2026-04-16
> **状态**: DESIGN (基于 28 个失败方向 + 213 次因子测试 + 3 篇 2025 前沿论文实证校准)
> **前版**: V1.0 (2026-03-19, 1064 行, 4-Agent + Pipeline 全自动闭环) → 本版精简重构
> **路线图**: `docs/QUANTMIND_FACTOR_UPGRADE_PLAN_V4.md` §Phase 3
> **实验证据**: `docs/research-kb/` (19 条目) + `CLAUDE.md` §已知失败方向 (28 条)

---

## 一、核心目标

**比 alpha 衰减更快地产出替代因子和策略。**

A 股传统多因子超额收益 2020-2025 从 8% 降至 3%。CORE4 因子（换手/波动/BP/股息）是经典因子，alpha 衰减是确定性事件。AI 闭环的价值不是"一次性找到完美策略"，而是**持续进化的能力**。

**量化目标**:
- 因子管道吞吐: 每月产出 ≥2 个 PASS 因子候选
- 策略进化: 每季度 Feature Map 至少新增/升级 1 个策略格子
- Alpha 半衰期监测: 检测到衰减 → 2 周内启动替代搜索
- WF OOS Sharpe 组合目标: 1.0-1.5 (当前单策略 0.87)

---

## 二、四层架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 4: 资本分配 (策略间 Risk Budgeting)                        │
│  riskfolio-lib / 季度更新 / 3-8 策略 / 单策略 10%-60%            │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3: Feature Map (策略种群矩阵)                              │
│  行=策略类型(RANKING/FAST/EVENT/MODIFIER)                        │
│  列=风险偏好(低回撤/平衡/高收益) × 市值段(微盘/小盘/全市场)      │
│  AI 目标: 填充空格 + 提升已有格质量 + 策略生命周期管理            │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: 轨迹进化引擎 (因子发现 + 策略生成)                     │
│  Idea Agent → Factor Agent → Strategy Agent → Eval Agent         │
│  轨迹级进化: 成功交叉 + 失败定位重写 + 知识库积累                │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1: 自动化监控 (纯规则, 无 AI)                              │
│  IC 衰减 / Rolling WF / 因子健康 / 策略 Sharpe 跟踪              │
│  已有: ic_monitor + rolling_wf + pt_daily_summary + health_check │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、Layer 1 — 自动化监控

纯规则驱动，不需要 LLM。**当前已部分实现**。

### 3.1 因子生命周期自动管理

| 状态 | 触发条件 | 动作 | 授权 |
|---|---|---|---|
| `active` → `warning` | IC_MA20 < IC_MA60 × 0.8 (轻度衰减) | 日报标黄，不调权 | L1 自动 |
| `warning` → `degraded` | IC_MA20 < IC_MA60 × 0.5 持续 20 天 | 权重降至 0.5x，触发 Layer 2 替代搜索 | L1 自动 |
| `degraded` → `archived` | IC_MA60 < 0.01 持续 60 天，且无 regime 条件恢复 | 移出 active 池 | L2 人确认 |
| `archived` → `conditional` | Regime 变化检测到因子 IC 恢复 (rolling 20d IC > 0.03) | 进入条件因子池，特定 regime 下可激活 | L1 自动 |

### 3.2 策略生命周期管理

```
experimental → paper_trading → live → degraded → archived
     ↑                                     │
     └──── 条件回收 (regime 变化) ←─────────┘
```

| 转换 | 证据门槛 |
|---|---|
| experimental → paper_trading | WF OOS Sharpe > 0.5, MDD < 30%, ≥3 年回测 |
| paper_trading → live | 60 天 paper 验证, 实盘/回测衰减 < 30% |
| live → degraded | Rolling 60d Sharpe 低于基线 50% 持续 2 个月 |
| degraded → archived | 3 个月未恢复 + 诊断无修复方案 |

### 3.3 已实现的监控脚本

| 脚本 | 频率 | 功能 | Task Scheduler |
|---|---|---|---|
| `scripts/ic_monitor.py` | 周 (20:00) | CORE4 IC 趋势 + 衰减告警 | QM-ICMonitor |
| `scripts/rolling_wf.py` | 日 (02:00) | 月度 Rolling WF 验证 | QM-RollingWF |
| `scripts/pt_daily_summary.py` | 日 (17:35) | PT 日报 (NAV/收益/持仓) | QM-PTDailySummary |
| `scripts/health_check.py` | 日 (16:25) | 盘前预检 + config drift | QM-HealthCheck |
| `scripts/factor_health_daily.py` | 日 (17:30) | 因子覆盖率 + NaN 检测 | QuantMind_FactorHealthDaily |

**待实现**: 因子生命周期自动状态转换 + 策略级 Sharpe 跟踪

---

## 四、Layer 2 — 轨迹进化引擎

核心创新：借鉴 [QuantaAlpha (2025)](https://arxiv.org/abs/2602.07085) 的轨迹级进化 + [AlphaAgent (KDD 2025)](https://arxiv.org/abs/2502.16789) 的 AST 去重。

### 4.1 轨迹定义

一条轨迹 = 完整的因子/策略发现过程：

```python
@dataclass
class Trajectory:
    """一条完整的因子/策略发现轨迹"""
    trajectory_id: str
    hypothesis: str              # 市场假设 (Idea Agent 产出)
    data_sources: list[str]      # 使用的数据源
    factor_code: str             # 因子代码 (Factor Agent 产出)
    factor_profile: dict         # 画像结果 (5 维)
    strategy_config: dict        # 策略配置 (Strategy Agent 产出)
    backtest_result: dict        # 回测结果
    diagnosis: str               # 诊断结论
    status: str                  # success / failed / partial
    failure_step: str | None     # 失败定位 (hypothesis/code/profile/strategy/backtest)
    failure_reason: str | None   # 失败原因
    parent_ids: list[str]        # 进化来源 (交叉/变异的父代)
```

### 4.2 四 Agent 协作

```
Idea Agent (假设生成)
  ↓ {hypothesis, target_data, search_direction}
Factor Agent (因子实现)
  ↓ {factor_code, factor_name, expression}
  ↓ 自动: factor_profiler V2 画像 → 模板匹配 T1-T15
Strategy Agent (策略匹配/生成) ← 本版新增
  ↓ {strategy_config, target_feature_map_cell}
Eval Agent (评估 + 反馈)
  ↓ {快速回测 → 完整 WF → 诊断}
  ↓ 失败时: 定位失败步骤 → 局部重写 → 重新提交
```

#### Idea Agent (假设生成)

- **模型**: DeepSeek R1 (推理强, 中文好, ~0.1 元/轮)
- **输入 context**: 当前因子库状态 + 近 10 轮成败摘要 + 高相关因子对 + IC 衰退因子 + Feature Map 空格
- **输出**: 结构化假设 `{phenomenon → behavior → bias → predictability → data_source → direction}`
- **搜索方向调度**: UCB1 Multi-Armed Bandit (6 方向: 跨源组合/条件因子/非线性/抗衰减/未探索/精炼)
- **关键约束**: 每条假设必须有完整因果链 (铁律 13 G10 Gate)

#### Factor Agent (因子实现)

- **模型**: GLM5 或 DeepSeek V3 (代码生成, 低温度 0.2)
- **输入**: 假设 + FactorDSL 算子集 + 知识库中相似因子代码
- **输出**: Python 函数 (符合 `calc_<name>(close, volume, ..., window) -> pd.Series` 签名)
- **代码约束**: 9 条硬规则 (函数签名/groupby/无未来数据/除零保护/...) 来自 V1 设计
- **重试**: 最多 3 次, 注入 Python 错误 + 行号

#### Strategy Agent (策略匹配/生成) — **V2 新增**

基于因子画像自动决定使用方式：

```python
TEMPLATE_TO_STRATEGY = {
    "T1":  "RANKING_MONTHLY",     # IC 强 + 衰减慢 + 成本可行
    "T2":  "RANKING_WEEKLY",      # IC 强 + 衰减快 + 高换手
    "T3":  "COMPOSITE_ONLY",      # IC 弱但稳定, 仅在组合中贡献
    "T5":  "ML_FEATURE_ONLY",     # IC 强 + 成本过高, 作 ML 特征
    "T11": "EVENT_DRIVEN",        # 事件触发型 (PEAD/业绩预告/解禁)
    "T12": "MODIFIER",            # Regime 敏感, 调权不选股
    "T15": "MULTI_USE",           # 全维度优秀, 多策略同时用
}
```

Strategy Agent 的决策逻辑：
1. 查 Feature Map 哪个格子有空位或可提升
2. 如果因子匹配已有策略 → ADD_TO_EXISTING (需 WF 验证增量)
3. 如果因子需要新框架 → CREATE_NEW_STRATEGY (需 L2 人确认)
4. 如果因子是 Modifier 类型 → ADD_MODIFIER (调权参数搜索)
5. 如果因子高成本 → ADD_TO_ML_FEATURES (仅作辅助输入)

**关键改变 vs V1**: V1 假设所有因子塞进一个 alpha_score 等权组合。V2 认识到不同因子需要不同框架 (铁律 6)。

#### Eval Agent (评估 + 反馈)

自动化 pipeline, 不需要 LLM:

```
Step 1: 代码安全检查 (AST 解析, 无 import/exec/网络)
Step 2: 沙箱执行 (60s / 2GB 限制)
Step 3: IC 快速筛选 (|IC| > 0.015, 铁律 19 统一口径)
Step 4: Gate G1-G10 全量评估
  - G9: AST 相似度 < 0.7 (AlphaAgent 创新, 铁律 12)
  - G10: 假设-因子语义对齐 (LLM 评估)
Step 5: 噪声鲁棒性 (铁律 20, 20% 噪声 retention > 0.50)
Step 6: 快速回测 (1 年, 简化成本, ~1s)
Step 7: 完整 WF (5-12 年, 全成本, ~15-75s) — 仅 Top 20%
Step 8: 写入知识库 + 更新 FACTOR_TEST_REGISTRY (铁律 11)
```

**失败定位与局部重写** (from QuantaAlpha):
- 假设错误 → 仅重新生成假设, 保留其余
- 代码错误 → 仅重写代码, 保留假设
- 策略错配 → 仅重新匹配策略, 保留因子
- 回测不通过 → 诊断具体原因 (成本/衰减/regime), 针对性修复

### 4.3 轨迹进化

每周进化一代 (可配置):

```
1. 运行 N 条新轨迹 (默认 10)
2. 评估所有轨迹 (快速回测)
3. 选择 Top 3 成功轨迹 + 3 条"有潜力"的失败轨迹
4. 交叉: 成功轨迹 A 的假设 + 成功轨迹 B 的代码模板 → 新轨迹
5. 变异: 失败轨迹定位失败步骤 → 局部重写 → 重新评估
6. 知识库更新: 成功模式 + 失败原因 + AST 黑名单
```

### 4.4 GP 引擎 (补充搜索通道)

保留 V1 设计, 与 LLM Agent 并行:

- FactorDSL: 11 TS + 2 TS-binary + 2 CS + 5 unary + 7 binary + 25 terminals
- **Terminal 扩展 (V2)**: 加入微结构字段 (vol_autocorr/skewness/max_ret/kurtosis) + 融资融券 + 业绩预告
- 适应度: `SimBroker_Sharpe × (1 - 0.1 × complexity) + 0.3 × novelty_bonus`
- 反拥挤: corr > 0.6 with existing Top 因子 → penalty
- Warm Start: 80% 种群来自上轮最优 + 20% 随机

### 4.5 数据维度扩展计划

| 优先级 | 数据源 | 接口 | 因子方向 | 对应策略类型 |
|---|---|---|---|---|
| P1 | 融资融券 | margin_detail (Tushare 5000) | 杠杆情绪/多空博弈 | RANKING / MODIFIER |
| P1 | 业绩预告 | forecast (Tushare 5000) | PEAD 增强 | EVENT |
| P1 | 限售解禁 | share_float (Tushare 5000) | 供给冲击 | EVENT |
| P2 | 大宗交易 | block_trade (Tushare 2000) | 机构行为 | RANKING |
| P2 | 股东人数 | stk_holdernumber (5000) | 筹码集中度 | RANKING (季度) |
| P2 | 沪深港通持股 | AKShare 免费 | 北向行为 V2 | MODIFIER |

接入规则: 每个新数据源必须走 DataPipeline (铁律 17) + 创建 Data Contract。

---

## 五、Layer 3 — Feature Map (策略种群矩阵)

借鉴 [QuantEvolve (2025)](https://arxiv.org/abs/2510.18569) 的 Quality-Diversity 优化。

### 5.1 矩阵定义

```
             低回撤(<20%)    平衡         高收益(>20%年化)
             微盘          全市场        微盘          全市场
月度RANKING  [S1:CORE4✅]  [空]         [空]          [空]
周度FAST     [空]          [空]         [空]          [空]
事件EVENT    [空]          [空]         [空]          [空]
Modifier     [SN_0.50✅]   [空]         [空]          [空]
季度VALUE    [空]          [空]         [空]          [空]
```

当前只填了 2 个格子 (S1 + SN)。AI 的目标是**填充空格并提升质量**。

### 5.2 策略种群进化规则

- **填充优先**: 选 Feature Map 中空的、预期收益最高的格子
- **提升其次**: 已有策略 Sharpe < 目标时, 尝试替换因子/调参
- **多样性约束**: 任意两个策略的 daily return 相关性 < 0.5
- **市值分散**: 不允许所有策略都集中在微盘 (至少 1 个全市场策略)

### 5.3 32 个 PASS 因子的分配预案

基于已有画像数据和模板匹配:

| 策略格子 | 候选因子 (从 32 PASS 中) | 预期框架 |
|---|---|---|
| 周度 FAST_RANKING | vol_autocorr_20, skewness_20, kurtosis_20, max_ret_range_20 等 16 微结构因子 | 周度 Top-30 等权, 高换手因子池 |
| 事件 EVENT | PEAD-SUE (direction=-1), 业绩预告 (待接入), 限售解禁 (待接入) | 触发式, 持仓 5-20 天 |
| 季度 VALUE | dv_ttm, bp_ratio (已在 CORE4), 新增 ROE 季度 | 季度调仓, 大中盘, 低换手 |
| Modifier | 北向行为 V2 (15 因子), Regime 条件因子 | 不选股, 调权/择时 |

---

## 六、Layer 4 — 资本分配

### 6.1 策略间 Risk Budgeting

- **方法**: riskfolio-lib Risk Parity / Risk Budgeting
- **输入**: 每个策略 ≥60 天 NAV 历史
- **频率**: 季度更新 (策略级波动慢)
- **约束**: 单策略 10%-60%, 现金储备 5%-20%

**为什么在策略级有效**: Phase 2.2 MVO 在 40 股 × 60 日上 94% 失败 (协方差不稳定)。但 3-5 个策略 × 240 日 = 稳定的协方差矩阵。

### 6.2 Regime-Conditional 权重调整

Feature Map 中的 Modifier 策略负责跨策略权重微调:

| Regime | S1 月度 | S3 周度 | S2 事件 | 逻辑 |
|---|---|---|---|---|
| 牛市 (动量强) | 40% | 30% | 20% | 加权动量/微结构 |
| 熊市 (恐慌) | 50% | 10% | 20% | 收缩高频, 保留低频价值 |
| 震荡 (均值回归) | 35% | 25% | 30% | 事件驱动更有效 |

Regime 检测: 非线性方法 (HMM / changepoint), 不用线性回归 (已证伪, Step 6-E)。

---

## 七、授权与安全 (保留 V1 核心设计)

### 7.1 四级授权

```
L0 全手动: AI 只提供建议, 人执行全部
L1 半自动 (默认): 自动因子发现+评估+画像+快速回测, 需人批因子入库+策略部署
L2 大部分自动: L1 + 因子自动入库 (通过 Gate 自动入), 仅策略部署需人批
L3 全自动: L2 + 自动部署到 paper_trading, 仅 live 部署需人批
```

**实盘部署始终需要人确认** — 所有 Level 均如此。

### 7.2 三级 Fallback

```
AI 策略异常 → 回退到上次确认的规则策略 (CORE4 等权)
规则策略也异常 → 清仓等待
清仓后 → P0 告警 (DingTalk + 日志)
```

### 7.3 诊断树 (保留 V1, 校准阈值)

```
收益不足? (年化 < 8%, 校准后)
├─ 全因子 IC < 0.02 → Alpha 源不足 → 触发 Layer 2 因子发现
├─ IC 正常但收益低 → 交易成本过高 → 降频/提流动性门槛
├─ 成本正常收益低 → 策略框架错配 → 检查 Feature Map 分配
└─ 某些年份特别差 → Regime 问题 → 检查 Modifier / 条件因子池

回撤过大? (MDD > 25%, 校准后)
├─ 行业集中 > 40% → 分散约束
├─ 市值集中 > 90% 微盘 → SN beta 上调
└─ 特定月份大亏 → 系统性风险 vs 策略失效

组合 Sharpe < 0.5? → 全面诊断 (逐策略检查 + 相关性分析)
组合 Sharpe > 2.0? → 过拟合警告 (检查 WF overfit ratio)
```

---

## 八、知识管理

### 8.1 知识库 Schema (mining_knowledge 表, 已存在)

每条记录包含: 假设、因子代码、表达式、IC 指标、Gate 通过情况、AST hash、失败原因、搜索方向、轨迹 ID。

### 8.2 失败知识注入

- 28 个已知失败方向 (CLAUDE.md) → 编码为 GP/LLM 搜索约束
- 每条新失败轨迹 → 提取失败模式 → 注入下一代 Idea Agent prompt
- AST 黑名单: 已证伪的因子表达式 + 相似度 > 0.7 的变体

### 8.3 BH-FDR 多重检验

- 当前 M = 84 (FACTOR_TEST_REGISTRY.md)
- 每次新测试递增 M, 调整 t 阈值 (Harvey Liu Zhu 2016)
- AI 必须记录每次测试到 registry, 不允许 off-registry IC 评估 (铁律 11)

---

## 九、已验证约束 (实验证据摘要)

基于 28 个失败方向 + 213 次因子测试, 以下是 AI 闭环的硬约束:

### 9.1 信号层

| 约束 | 证据 | 设计影响 |
|---|---|---|
| 等权框架 ≤4 因子 | Phase 3B (8/8 FAIL) + Phase 3E (0/6 FAIL) | 超过 4 因子必须用非等权框架 |
| IC 正不等于 Sharpe 正 | LightGBM IC=0.067/Sharpe=0.09, 微结构 17/20 IC PASS/0/6 WF PASS | 适应度必须用 Sharpe, 不用 IC |
| OHLCV 窗口变体 IC 上限 0.06 | 暴力枚举 Layer 1-2 | GP DSL 必须扩展 terminal 到非 OHLCV 数据 |
| ML 预测 5 次独立验证均不超等权 | G1/6-H/2.1/2.2/3D | 不在当前因子集上重试 ML 选股 |

### 9.2 组合层

| 约束 | 证据 | 设计影响 |
|---|---|---|
| 权重优化无效 (低因子数) | G2 7 组实验 + Phase 2.2 6 方法 | riskfolio-lib 仅用于策略级, 不用于个股级 |
| 完美预测下 MVO = 等权 | Phase 2.1 A.8 | 不投资组合构建优化 |
| A 股成本不可微分 | Phase 2.1 282% gap | 不用梯度优化 portfolio loss |

### 9.3 风控层

| 约束 | 证据 | 设计影响 |
|---|---|---|
| Alpha 100% 微盘 | Phase 2.3 (91.5% 微盘) | 风控通过 SN, 不通过 universe 限制 |
| 止损破坏 alpha | 3 组实验, 66% 止损股反弹 | 只用利润保护 (PMS), 不用止损 |
| Modifier 不可叠加 | Step 6-G | 每个策略最多 1 个 Modifier |
| SN beta 最优区间 0.3-0.5 | Step 6-F/6-H | SN beta 不超过 0.5 |

---

## 十、LLM 模型选择

| 角色 | 推荐模型 | 备选 | 理由 |
|---|---|---|---|
| Idea Agent | DeepSeek R1 | GLM-4 | 推理链强, 中文好, 成本低 |
| Factor Agent | GLM5 / DeepSeek V3 | — | 代码生成, 低温度, 需中文注释 |
| G10 语义对齐 | DeepSeek R1 | Claude | 评估假设与因子的一致性 |
| 策略诊断 | DeepSeek R1 | — | 诊断树推理 |

**成本控制**: 每轮完整轨迹 ~0.3-0.5 元, 每周 10 轨迹 = ~5 元/周, 月预算 ~20-50 元。需实测后根据效果调整。

---

## 十一、实现路线

| 阶段 | 内容 | 预计 | 依赖 | 产出 |
|---|---|---|---|---|
| **3.1** | Layer 1 完善: 因子生命周期自动状态转换 + 策略 Sharpe 跟踪 | 2 天 | 已有 3 脚本 | 全自动监控 |
| **3.2** | 数据扩展: 融资融券 + 业绩预告 + 限售解禁 接入 DataPipeline | 3 天 | Tushare 5000 积分 | 3 个新 Data Contract |
| **3.3** | Layer 2 MVP: Idea Agent + Factor Agent + Eval Agent (单轨迹, 不进化) | 5 天 | 3.2 | 端到端因子发现 |
| **3.4** | Strategy Agent + Feature Map: 因子画像→策略匹配→自动回测 | 5 天 | 3.3 | 多策略框架 |
| **3.5** | 轨迹进化: 交叉/变异 + 失败定位 + 知识库积累 | 3 天 | 3.4 | 自我进化能力 |
| **3.6** | Layer 4: 策略间 Risk Budgeting + Regime 权重 | 3 天 | ≥2 个策略运行 | 组合 Sharpe 提升 |
| **3.7** | GP 引擎激活 + DSL terminal 扩展 | 3 天 | 3.2 | 双通道发现 |

每阶段独立可执行 (铁律 23), 每阶段完成后运行验证 (regression + WF)。

---

## 十二、前端 API 设计 (对齐后端实际)

### 12.1 已有端点 (可直接使用)

| 端点 | 功能 |
|---|---|
| `GET /api/pipeline/status` | Pipeline 实时状态 |
| `GET /api/pipeline/runs` | 运行历史 |
| `GET /api/pipeline/runs/{run_id}` | 单次运行详情 + 候选因子 |
| `POST /api/pipeline/runs/{run_id}/approve/{factor_id}` | 审批通过 |
| `POST /api/pipeline/runs/{run_id}/reject/{factor_id}` | 审批拒绝 |
| `GET /api/approval/queue` | 待审批队列 |
| `GET /api/factors/{name}` | 因子详情 |
| `POST /api/factors/{name}/archive` | 归档因子 (Phase E 新增) |

### 12.2 待实现端点

| 端点 | 功能 | Phase |
|---|---|---|
| `POST /api/pipeline/trigger` | 手动触发 Pipeline | 3.3 |
| `POST /api/pipeline/pause` | 暂停 Pipeline | 3.3 |
| `GET /api/agent/{name}/config` | Agent 配置读取 | 3.3 |
| `PUT /api/agent/{name}/config` | Agent 配置更新 | 3.3 |
| `GET /api/agent/{name}/logs` | Agent 决策日志 | 3.3 |
| `GET /api/strategies/feature-map` | Feature Map 可视化数据 | 3.4 |
| `GET /api/strategies/{id}/lifecycle` | 策略生命周期状态 | 3.4 |

---

## 十三、DB Schema (增量, 对齐 DDL)

已有表 (无需改动): `factor_registry`, `pipeline_runs`, `gp_approval_queue`, `mining_knowledge`, `factor_ic_history`, `factor_values`

待新增:

```sql
-- 轨迹记录 (Layer 2)
CREATE TABLE IF NOT EXISTS trajectory_history (
    trajectory_id   VARCHAR(64) PRIMARY KEY,
    hypothesis      TEXT NOT NULL,
    factor_name     VARCHAR(100),
    factor_code     TEXT,
    strategy_config JSONB,
    backtest_result JSONB,
    status          VARCHAR(20) DEFAULT 'running',  -- running/success/failed
    failure_step    VARCHAR(30),                     -- hypothesis/code/profile/strategy/backtest
    failure_reason  TEXT,
    parent_ids      JSONB DEFAULT '[]',              -- 进化来源
    search_direction VARCHAR(30),                     -- UCB1 方向
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 策略种群 (Layer 3 Feature Map)
CREATE TABLE IF NOT EXISTS strategy_instances (
    strategy_id     VARCHAR(64) PRIMARY KEY,
    strategy_type   VARCHAR(30) NOT NULL,            -- RANKING_MONTHLY/WEEKLY/EVENT/MODIFIER
    risk_profile    VARCHAR(20) NOT NULL,            -- low_dd/balanced/high_return
    market_cap_seg  VARCHAR(20) DEFAULT 'all',       -- micro/small/all
    factors         JSONB NOT NULL,                  -- 因子列表 + 权重
    config          JSONB NOT NULL,                  -- 完整回测配置
    lifecycle_state VARCHAR(20) DEFAULT 'experimental',
    wf_oos_sharpe   FLOAT,
    wf_oos_mdd      FLOAT,
    last_validated   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Agent 决策日志 (审计)
CREATE TABLE IF NOT EXISTS agent_decision_log (
    id              BIGSERIAL PRIMARY KEY,
    trajectory_id   VARCHAR(64),
    agent_name      VARCHAR(50) NOT NULL,
    decision_type   VARCHAR(50),
    reasoning       TEXT,
    input_context   JSONB,
    output_result   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_agent_log_trajectory ON agent_decision_log(trajectory_id);
CREATE INDEX idx_agent_log_agent ON agent_decision_log(agent_name, created_at DESC);
```

---

## 十四、学术参考

| 论文 | 年份 | 关键贡献 | 我们借鉴的 |
|---|---|---|---|
| [AlphaAgent](https://arxiv.org/abs/2502.16789) | KDD 2025 | AST 去重 + 假设对齐 + 复杂度控制 | G9 Gate + G10 语义对齐 |
| [QuantaAlpha](https://arxiv.org/abs/2602.07085) | 2025 | 轨迹级进化 + 失败定位重写 | Layer 2 轨迹进化引擎 |
| [QuantEvolve](https://arxiv.org/abs/2510.18569) | 2025 | Feature Map + 端到端策略生成 | Layer 3 策略种群矩阵 |
| Harvey Liu Zhu (2016) | 2016 | 多重检验校正 (BH-FDR) | t > 2.5 硬门槛 + M 累积 |
| Amihud (2002) | 2002 | 非流动性溢价 | CORE4 因子之一 |

---

## 附录: V1→V2 变更摘要

| V1 (2026-03-19) | V2 (2026-04-16) | 变更原因 |
|---|---|---|
| 4 Agent 全自动 L3 目标 | 4 层渐进, 默认 L1 | 铁律 24: 设计不超 2 页精神 |
| 所有因子→等权 alpha_score | Factor Profile → 策略模板匹配 | 铁律 6 + Phase 3B/3E 等权天花板 |
| IC_IR 加权权重优化 | 等权基线 + 策略级 Risk Budget | Phase 2.2 6 方法全 FAIL |
| Optuna 参数大搜索 | 已证伪参数空间剔除 | 28 个失败方向 |
| RD-Agent 集成 | 自建 GP + LLM Agent | Docker+Windows+Claude 三重阻断 |
| 1064 行 | ~600 行 | 精简, 每节可独立执行 |
| 诊断阈值 (年化 15%/Sharpe 1.0) | 校准后 (年化 8%/Sharpe 0.5) | 12yr 基线 Sharpe=0.36, WF OOS=0.87 |
| 单一策略框架 | 多策略 Feature Map | QuantEvolve 启发 + 32 PASS 因子利用 |
| 无轨迹进化 | 轨迹级交叉/变异/失败定位 | QuantaAlpha 启发 |
| ~20% 实现 (声称) | 0% (agents/ 已删), 重新开始 | 2026-04-15 agents 停用 |
