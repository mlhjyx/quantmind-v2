> **⚠️ 文档状态: PARTIALLY_IMPLEMENTED (2026-04-10)**
> 实现状态: ~25% — 220 参数中约50个在用。Step 4-B YAML 配置驱动已实现核心参数。
> 仍有价值: 参数命名规范、配置分层原则
> 已过时/被替代: 未实现功能的参数定义无意义，实际参数以 configs/*.yaml 为准
> 参考: docs/QUANTMIND_FACTOR_UPGRADE_PLAN_V3.md

# QuantMind V2 — 参数可配置性系统 详细开发文档

> **对应总设计文档**: 第七章 §7.6
> **版本**: 2.0 | **日期**: 2026-03-19
> **设计哲学**: 最大化可配置——几乎所有参数都能在前端调
> **V2新增**: 回测引擎参数模块(§3.12)、Agent配置参数模块(§3.13)、前端技术Streamlit→React

---

# 1. 四级控制体系

```
Level 0 硬编码: 代码里写死，改代码才能改（安全底线）
Level 1 配置文件: YAML/ENV，开发者改，重启生效（系统级）
Level 2 前端可调: React界面滑块/下拉/输入框，实时生效（策略级）
Level 3 AI自动调: AI闭环动态优化，前端可切换手动覆盖（14个AI参数）
```

---

# 2. 统一参数交互组件

前端每个可调参数使用统一的交互组件：

```
┌─────────────────────────────────────────────┐
│ 参数名称                           [?帮助]  │
│                                               │
│ ○ 手动设定   ○ AI推荐   ● AI自动            │
│                                               │
│ [====●========================] 当前值       │
│ 范围: 最小值 ─────────────────── 最大值      │
│                                               │
│ 默认值: xxx | AI推荐: xxx | 历史最优: xxx    │
│                                               │
│ 💡 一句话说明参数含义                        │
└─────────────────────────────────────────────┘

三态说明：
  手动设定 → 滑块可拖动，值固定，AI不干预
  AI推荐  → 显示AI建议值，用户点"采纳"后生效
  AI自动  → AI直接控制，滑块变为只读显示当前AI选的值
```

---

# 3. 完整参数清单（11个模块，220+个参数）

> V2新增模块: §3.12 回测引擎(22个参数)、§3.13 Agent配置(28个参数)

## 3.1 GP遗传编程引擎（13个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 种群大小 | int | [100, 2000] | 500 | 滑块 | L2 |
| 进化代数 | int | [20, 500] | 100 | 滑块 | L2 |
| 交叉率 | float | [0.1, 0.95] | 0.7 | 滑块 | L2 |
| 变异率 | float | [0.01, 0.5] | 0.1 | 滑块 | L2 |
| 锦标赛大小 | int | [2, 10] | 5 | 滑块 | L2 |
| 最大树深度 | int | [3, 10] | 6 | 滑块 | L2 |
| 最大节点数 | int | [10, 80] | 30 | 滑块 | L2 |
| 反拥挤相关性阈值 | float | [0.5, 0.95] | 0.8 | 滑块 | L2 |
| 终端节点选择 | multi | 全部数据字段 | 全选 | 多选框 | L2 |
| 函数节点选择 | multi | 全部算子 | 全选 | 多选框 | L2 |
| 适应度-IC权重 | float | [0, 5] | 1.0 | 滑块 | L2 |
| 适应度-IR权重 | float | [0, 5] | 1.0 | 滑块 | L2 |
| 适应度-原创性权重 | float | [0, 5] | 1.0 | 滑块 | L2 |

## 3.2 LLM因子挖掘Agent（9个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| Idea Agent模型 | enum | R1/V3/GPT-4o/Claude | DeepSeek R1 | 下拉 | L2 |
| Factor Agent模型 | enum | V3/GPT-4o/Claude | DeepSeek V3 | 下拉 | L2 |
| 每轮假设数量 | int | [1, 10] | 3 | 滑块+AI开关 | L2/L3 |
| 代码重试次数 | int | [0, 5] | 3 | 滑块 | L2 |
| 搜索方向 | enum | 6个方向 | 调度器选 | 下拉+自动 | L2/L3 |
| temperature(Idea) | float | [0, 1.5] | 0.8 | 滑块 | L2 |
| temperature(Factor) | float | [0, 1.5] | 0.2 | 滑块 | L2 |
| max_tokens | int | [512, 8192] | 4096 | 滑块 | L2 |
| IC快速筛选阈值 | float | [0, 0.05] | 0.015 | 滑块 | L2 |

## 3.3 Factor Gate Pipeline（7个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| Gate1 IC阈值 | float | [0, 0.1] | 0.02 | 输入框 | L2 |
| Gate1 t-stat阈值 | float | [0, 5] | 2.0 | 输入框 | L2 |
| Gate2 单调性阈值 | float | [0, 1] | 0.7 | 滑块 | L2 |
| Gate3 相关性阈值 | float | [0, 1] | 0.7 | 滑块 | L2 |
| Gate4 分年稳定(N/5) | int | [1, 5] | 4 | 滑块 | L2 |
| IC计算窗口 | enum | 1Y/3Y/5Y/全量 | 全量 | 下拉 | L2 |
| IC类型 | enum | Spearman/Pearson | Spearman | 下拉 | L2 |

## 3.4 组合构建（6个参数，各有手动/AI切换）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 持仓数N | int | [10, 50] | 30 | 滑块+AI开关 | L2/L3 |
| 权重方案 | enum | 等权/IC加权/HRP/MVO | 等权 | 下拉+AI开关 | L2/L3 |
| 单股权重上限 | float | [3%, 15%] | 8% | 滑块+AI开关 | L2/L3 |
| 行业权重上限 | float | [10%, 35%] | 25% | 滑块+AI开关 | L2/L3 |
| 换手率上限 | float | [10%, 80%] | 50% | 滑块+AI开关 | L2/L3 |
| 调仓频率 | enum | 周/双周/月 | 月 | 下拉+AI开关 | L2/L3 |

## 3.5 Universe（5个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 新股天数 | int | [30, 365] | 60 | 滑块 | L2 |
| 市值门槛(亿) | float | [5, 50] | 20 | 滑块+AI开关 | L2/L3 |
| 成交额门槛(万/天) | float | [200, 2000] | 500 | 滑块+AI开关 | L2/L3 |
| 停牌天数门槛 | int | [3, 30] | 10 | 滑块+AI开关 | L2/L3 |
| 包含板块 | multi | 主板/创业板/科创/北交所 | 全选 | 多选框 | L2 |

## 3.6 风控（3个可调 + 5个只读）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 外汇单笔风险 | float | [0.5%, 5%] | 2% | 滑块 | L2 |
| 外汇保证金上限 | float | [20%, 80%] | 50% | 滑块 | L2 |
| 外汇单品种限仓 | float | [0.5, 10] | 3手 | 输入框 | L2 |
| 单股硬上限 | float | — | 15% | 只读 | L0 |
| 行业硬上限 | float | — | 35% | 只读 | L0 |
| 月亏损降仓 | float | — | 10% | 只读 | L1 |
| 累计亏损停止 | float | — | 25% | 只读 | L0 |
| 日亏损暂停 | float | — | 5% | 只读 | L1 |

## 3.7 回测（7个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 回测开始日期 | date | 2015-至今 | 2020-01-01 | 日期选择器 | L2 |
| 回测结束日期 | date | 开始日-至今 | 最新日 | 日期选择器 | L2 |
| 初始资金 | float | [10万, 1亿] | 100万 | 输入框 | L2 |
| 佣金费率 | float | [0, 万5] | 万2.5 | 输入框 | L2 |
| 滑点模型 | enum | 固定/动态/无 | 动态 | 下拉 | L2 |
| 滑点参数(k) | float | [0, 0.5] | 0.1 | 输入框 | L2 |
| 基准指数 | enum | CSI300/500/1000 | CSI300 | 下拉 | L2 |

## 3.8 AI模型管理（10个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| LightGBM n_estimators | int | [100, 5000] | 500 | 滑块 | L2 |
| LightGBM max_depth | int | [3, 15] | 6 | 滑块 | L2 |
| LightGBM learning_rate | float | [0.001, 0.3] | 0.05 | 滑块 | L2 |
| LightGBM subsample | float | [0.1, 1.0] | 0.8 | 滑块 | L2 |
| LightGBM colsample | float | [0.1, 1.0] | 0.8 | 滑块 | L2 |
| HMM状态数 | int | [2, 5] | 3 | 滑块 | L2 |
| IsolationForest contamination | float | [0.01, 0.3] | 0.05 | 滑块 | L2 |
| IsolationForest n_estimators | int | [50, 500] | 100 | 滑块 | L2 |
| 模型重训频率 | enum | 周/月/季 | 月 | 下拉 | L2 |
| 模型替换阈值 | float | [80%, 110%] | 95% | 滑块 | L2 |

## 3.9 调度时间（4个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 数据更新时间 | time | 15:00-20:00 | 16:30 | 时间选择器 | L2 |
| 信号生成时间 | time | 16:00-20:00 | 17:10 | 时间选择器 | L2 |
| 推送截止时间 | time | 17:00-21:00 | 17:45 | 时间选择器 | L2 |
| P1告警最大条数/天 | int | [1, 10] | 3 | 滑块 | L2 |

## 3.10 因子预处理（4个参数）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 去极值方法 | enum | MAD/Winsorize/3σ | MAD | 下拉 | L2 |
| MAD倍数 | float | [3, 10] | 5 | 滑块 | L2 |
| 缺失值填充 | enum | 行业中位数/0/前向填充 | 行业中位数 | 下拉 | L2 |
| 标准化方法 | enum | Z-Score/Rank/MinMax | Z-Score | 下拉 | L2 |

## 3.11 因子选择（每因子3个参数 × 34因子 = 102个）

每个因子有：
- **开关**: Toggle (on/off) — 是否参与alpha_score
- **方向**: Toggle (正向/反向) — 因子越大收益越高还是越低
- **窗口**: 滑块 — 时间窗口参数（如momentum用60天还是120天）

---

# 4. 参数变更安全机制

## 4.1 前端即时合理性检查

```python
PARAM_CONSTRAINTS = [
    # 逻辑约束
    ("single_stock_max <= industry_max",
     "单股上限不能超过行业上限"),
    ("holding_n * single_stock_max <= 100",
     "持仓数×单股上限不能超过100%"),
    ("turnover_min > 0",
     "换手率不能为0，否则永不调仓"),
    ("universe_cap_min < universe_cap_max",
     "市值门槛下限不能超过上限"),

    # 时序约束
    ("signal_time > data_update_time",
     "信号生成时间必须在数据更新之后"),
    ("push_deadline > signal_time",
     "推送截止必须在信号生成之后"),

    # 回测约束
    ("backtest_end > backtest_start",
     "回测结束日期必须在开始之后"),
]
```

## 4.2 变更影响预估弹窗

```python
def estimate_param_impact(param_name, old_value, new_value) -> str:
    """参数变更前弹窗显示预估影响"""
    impacts = {
        "holding_n": lambda o, n: f"持仓从{o}只→{n}只，换手率预计{'增加' if n<o else '减少'}{abs(n-o)/o*100:.0f}%",
        "single_stock_max": lambda o, n: f"单股上限{o*100:.0f}%→{n*100:.0f}%，集中度{'增加' if n>o else '降低'}",
        "turnover_max": lambda o, n: f"换手上限{o*100:.0f}%→{n*100:.0f}%，年交易成本预计变化{(n-o)*0.15*12:.1f}%",
        "commission_rate": lambda o, n: f"佣金{o*10000:.1f}→{n*10000:.1f}，年成本变化约{(n-o)*2*12:.2%}",
    }
    if param_name in impacts:
        return impacts[param_name](old_value, new_value)
    return f"{param_name}: {old_value} → {new_value}"
```

## 4.3 版本记录

```sql
CREATE TABLE param_change_log (
    id BIGSERIAL PRIMARY KEY,
    param_name VARCHAR(64),
    old_value DECIMAL(12,6),
    new_value DECIMAL(12,6),
    changed_by VARCHAR(16),     -- 'user' | 'ai'
    reason TEXT,                 -- 用户填写或AI的决策理由
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## 4.4 一键回滚

```python
def rollback_params_to(timestamp: datetime):
    """回滚所有参数到指定时间点的状态"""
    # 从param_change_log反向回放
    # 支持前端一键操作
```

---

# 5. ai_parameters表初始化数据

```sql
INSERT INTO ai_parameters (param_name, param_value, param_min, param_max, param_default, updated_by, authorization_level) VALUES
('universe_cap_threshold', 20, 5, 50, 20, 'human', 1),
('universe_volume_threshold', 500, 200, 2000, 500, 'human', 1),
('universe_suspend_threshold', 10, 3, 30, 10, 'human', 1),
('holding_count_n', 30, 10, 50, 30, 'human', 1),
('single_stock_max_weight', 0.08, 0.03, 0.15, 0.08, 'human', 1),
('industry_max_weight', 0.25, 0.10, 0.35, 0.25, 'human', 1),
('turnover_max', 0.50, 0.10, 0.80, 0.50, 'human', 1),
('alpha_score_method', 0, 0, 2, 0, 'human', 2),   -- 0=等权,1=IC加权,2=LightGBM
('weight_method', 0, 0, 2, 0, 'human', 2),         -- 0=等权,1=alpha加权,2=HRP
('rebalance_freq', 2, 0, 2, 2, 'human', 2),        -- 0=周,1=双周,2=月
('position_ratio', 1.0, 0, 1.0, 1.0, 'human', 1),  -- 总仓位比例
('cross_market_astock_ratio', 0.70, 0.50, 0.90, 0.70, 'human', 2),
('cross_market_forex_ratio', 0.30, 0.10, 0.50, 0.30, 'human', 2),
('mining_hypotheses_per_round', 3, 1, 10, 3, 'human', 1);
```

---

# 6. V2新增参数模块

## 3.12 回测引擎（22个参数）— V2新增

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 市场选择 | enum | a_share/forex | a_share | Radio | L2 |
| 股票池预设 | enum | 8种 | all_a | Radio | L2 |
| 行业筛选 | multi | 申万31行业 | 全选 | 多选框 | L2 |
| 回测开始日期 | date | 2015-至今 | 2018-01-01 | 日期选择器 | L2 |
| 回测结束日期 | date | 开始日-至今 | 最新日 | 日期选择器 | L2 |
| 排除时期 | multi | 预设+自定义 | 无 | 多选+日期 | L2 |
| 初始资金 | float | [10万,1亿] | 100万 | 输入框 | L2 |
| 基准指数 | enum | 300/500/1000 | 300 | 下拉 | L2 |
| 成交价 | enum | next_open/next_vwap | next_open | Radio | L2 |
| 调仓频率 | enum | 日/周/双周/月 | 周 | 下拉 | L2 |
| 信号日(周频) | enum | 周一~周五 | 周五 | 下拉 | L2 |
| 持仓数量 | int | [10,50] | 30 | 滑块 | L2/L3 |
| 权重方式 | enum | equal/score_weighted | equal | Radio | L2 |
| 佣金费率 | float | [0,万5] | 万1.5 | 输入框 | L2 |
| 印花税率 | float | [0,0.1%] | 0.05% | 输入框 | L2 |
| 滑点模型 | enum | volume_impact/fixed | volume_impact | Radio | L2 |
| 滑点k(大盘) | float | [0.01,0.3] | 0.05 | 输入框 | L2 |
| 滑点k(中盘) | float | [0.01,0.3] | 0.10 | 输入框 | L2 |
| 滑点k(小盘) | float | [0.01,0.3] | 0.15 | 输入框 | L2 |
| 隔夜跳空成本(bps) | float | [0,50] | 25 | 输入框 | L2 |
| 日波动率σ | float | [0.005,0.05] | 0.02 | 输入框 | L2 |
| 卖出惩罚系数 | float | [1.0,2.0] | 1.3 | 输入框 | L2 |
| 成交量上限 | float | [5%,30%] | 10% | 滑块 | L2 |
| 单行业上限 | float | [10%,50%] | 30% | 滑块 | L2 |
| 单股上限 | float | [3%,15%] | 5% | 滑块 | L2 |

### Walk-Forward参数（4个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| WF启用 | bool | on/off | off | Toggle | L2 |
| WF训练期(月) | int | [12,60] | 36 | 滑块 | L2 |
| WF验证期(月) | int | [3,12] | 6 | 滑块 | L2 |
| WF测试期(月) | int | [1,12] | 3 | 滑块 | L2 |

### 市场状态分析参数（3个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 市场状态启用 | bool | on/off | on | Toggle | L2 |
| 判定方法 | enum | ma/drawdown | ma | Radio | L2 |
| 均线窗口 | int | [60,240] | 120 | 滑块 | L2 |

## 3.13 Modifier策略参数（R3新增, Sprint 1.13+）

> 参考: `docs/research/R3_multi_strategy_framework.md` — CompositeStrategy核心+Modifier架构

### RegimeModifier参数（4个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| Regime启用 | bool | on/off | on | Toggle | L2 |
| 高波缩放系数 | float | [0.3,1.0] | 0.7 | 滑块 | L2 |
| 波动率基线方法 | enum | median/ma60/ma120 | median | 下拉 | L2 |
| 缩放clip范围 | tuple | — | [0.5, 2.0] | 双滑块 | L2 |

### CompositeStrategy参数（3个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 现金缓冲比例 | float | [0,10%] | 3% | 滑块 | L2 |
| Modifier列表 | list[str] | — | ["regime"] | 多选框 | L2 |
| 初始资金(可配置) | float | [10万,1亿] | 100万 | 输入框 | L2 |

### FactorClassifier参数（3个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| ic_decay快速阈值(天) | int | [3,10] | 5 | 滑块 | L2 |
| ic_decay标准阈值(天) | int | [10,30] | 15 | 滑块 | L2 |
| 分类置信度下限 | float | [0.5,0.9] | 0.7 | 滑块 | L2 |

## 3.14 AI闭环Agent配置（28个参数）— V2新增

### 全局控制（2个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 自动化级别 | enum | L0/L1/L2/L3 | L1 | 四按钮选择 | L2 |
| Pipeline最大循环次数 | int | [1,5] | 3 | 滑块 | L2 |

### 因子发现Agent（10个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 调度频率 | cron | — | 每周一2:00 | Cron编辑器 | L2 |
| 类别饱和阈值 | int | [5,30] | 15 | 滑块 | L2 |
| IC衰退紧急阈值 | float | [0.1,0.5] | 0.20 | 滑块 | L2 |
| LLM模型选择 | enum | deepseek/mlx | deepseek | 下拉 | L2 |
| LLM温度 | float | [0,1.5] | 0.8 | 滑块 | L2 |
| 每轮候选数 | int | [3,20] | 10 | 滑块 | L2 |
| IC入库阈值 | float | [0.01,0.05] | 0.02 | 输入框 | L2 |
| IC_IR入库阈值 | float | [0.1,1.0] | 0.3 | 输入框 | L2 |
| 相关性入库阈值 | float | [0.5,0.9] | 0.7 | 滑块 | L2 |
| GP收敛轮数 | int | [2,5] | 3 | 滑块 | L2 |

### 策略构建Agent（4个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 调度频率 | cron | — | 每月1日3:00 | Cron编辑器 | L2 |
| IC衰退阈值 | float | [0.3,0.8] | 0.5 | 滑块 | L2 |
| 最少因子数 | int | [2,10] | 3 | 滑块 | L2 |
| 最多因子数 | int | [5,30] | 15 | 滑块 | L2 |

### 诊断优化Agent（6个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| 最低年化收益 | float | [5%,30%] | 15% | 输入框 | L2 |
| 最大MDD | float | [10%,30%] | 15% | 输入框 | L2 |
| 最低Sharpe | float | [0.5,2.0] | 1.0 | 输入框 | L2 |
| 实盘衰减阈值 | float | [20%,50%] | 30% | 滑块 | L2 |
| 允许自动调权重 | bool | on/off | on | Toggle | L2 |
| 允许自动淘汰因子 | bool | on/off | on | Toggle | L2 |

### 风控Agent（6个）

| 参数 | 类型 | 范围 | 默认值 | 前端控件 | 级别 |
|------|------|------|--------|---------|------|
| WF过拟合阈值 | float | [0.3,0.8] | 0.5 | 滑块 | L2 |
| 最少回测年数 | int | [2,5] | 3 | 滑块 | L2 |
| 日亏损预警 | float | [1%,5%] | 3% | 滑块 | L2 |
| 连续亏损天数 | int | [3,10] | 5 | 滑块 | L2 |
| 衰减红色警报 | float | [30%,80%] | 50% | 滑块 | L2 |
| 自动暂停开关 | bool | on/off | off | Toggle | L2 |

---

# 7. 参数变更约束补充（V2新增）

```python
# 回测引擎约束
BACKTEST_CONSTRAINTS = [
    ("backtest_end > backtest_start", "结束日期必须在开始之后"),
    ("holding_count * single_stock_cap <= 100", "持仓数×单股上限不能超过100%"),
    ("wf_train_months >= 12", "WF训练期至少12个月"),
    ("wf_train_months > wf_valid_months + wf_test_months", "训练期必须大于验证+测试期"),
    ("slippage_k_large <= slippage_k_mid <= slippage_k_small", "滑点系数大盘≤中盘≤小盘"),
]

# Agent配置约束
AGENT_CONSTRAINTS = [
    ("min_factors <= max_factors", "最少因子数不能超过最多因子数"),
    ("min_sharpe < max_sharpe_overfit", "最低Sharpe不能超过过拟合阈值"),
    ("ic_threshold > 0", "IC阈值必须大于0"),
]
```

---

## ⚠️ Review补丁（2026-03-20）

### P1. 新增可配置参数

| 参数名 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| EXECUTION_MODE | enum | paper | paper/live/forex，控制Broker策略模式 |
| MAX_SINGLE_REBALANCE_TURNOVER | float | 0.50 | 单次调仓换手率上限（50%=最多换一半持仓） |
| PAPER_GRADUATION_DAYS | int | 60 | Paper Trading最少运行交易日 |
| PAPER_SHARPE_RATIO_THRESHOLD | float | 0.70 | Paper Sharpe ≥ 回测Sharpe × 此值 |
| PAPER_MDD_RATIO_THRESHOLD | float | 1.50 | Paper MDD ≤ 回测MDD × 此值 |
| PAPER_SLIPPAGE_DEVIATION_MAX | float | 0.50 | 滑点偏差上限(50%) |
| HEALTH_CHECK_MIN_DISK_GB | float | 10.0 | 预检最低磁盘空间(GB) |
| HEALTH_CHECK_FACTOR_SAMPLE_N | int | 10 | 预检因子NaN抽样股票数 |
| LOG_LEVEL | enum | INFO | DEBUG/INFO/WARNING/ERROR |
| LOG_MAX_FILES | int | 50 | 最大日志文件数 |
| COST_SENSITIVITY_MULTIPLIERS | list | [0.5,1.0,1.5,2.0] | 成本敏感性分析的倍数列表 |
| BOOTSTRAP_N_SAMPLES | int | 1000 | Bootstrap Sharpe采样次数 |
| FACTOR_CRITICAL_WEEKS | int | 4 | 因子critical持续N周后退休 |
| FACTOR_MIN_ACTIVE_COUNT | int | 12 | 活跃因子低于此值触发P1告警 |
| AI_CHANGE_SHARPE_DROP_MAX | float | 0.10 | AI变更验证: Sharpe下降>此值自动拒绝 |
| AI_CHANGE_MDD_WORSEN_MAX | float | 0.20 | AI变更验证: MDD恶化>此值自动拒绝 |
