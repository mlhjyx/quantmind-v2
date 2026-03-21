# QuantMind V2 — AI 闭环详细开发文档

> 文档级别：实现级（供 Claude Code 执行）
> 创建日期：2026-03-19
> 关联文档：QUANTMIND_V2_DESIGN_V5.md、DEV_BACKTEST_ENGINE.md、DEV_FACTOR_MINING.md、DEV_BACKEND.md

---

## 一、概述

AI 闭环是 QuantMind V2 的终极目标——AI 自主完成"发现→评估→构建→回测→诊断→优化"的完整循环，人只做监督和决策。本文档覆盖：

- 三层架构设计（Agent 层→编排层→执行层）
- 4 个 Agent 的详细决策逻辑
- Pipeline 编排与状态机
- 4 级自动化控制
- 前端控制台设计（2 个页面）
- 因子挖掘前端（4 个页面）
- 数据库表结构（6 张新表）

---

## 二、已确认决策汇总（6 项）

| # | 决策项 | 选择 | 备注 |
|---|--------|------|------|
| 29 | AI 闭环架构 | 三层(Agent 层→编排层→执行层) | — |
| 30 | Agent 数量 | 4 个(因子发现/策略构建/诊断优化/风控监督) | — |
| 31 | 自动化级别 | 4 级(L0 全手动~L3 全自动), 默认 L1 半自动 | — |
| 32 | Agent 决策可审计 | 全部决策写入 agent_decision_log 表 | — |
| 33 | 审批机制 | approval_queue 表, L1 需人批入库+部署 | — |
| 34 | 闭环调度频率 | 因子发现周频/策略优化月频/体检双周/诊断周报 | — |

---

## 三、三层架构

```
┌─────────────────────────────────────────────────────────┐
│                    Agent 层 (决策大脑)                    │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ 因子发现   │  │ 策略构建   │  │ 诊断优化   │  │ 风控监督 │ │
│  │ Agent     │  │ Agent     │  │ Agent     │  │ Agent   │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
├─────────────────────────────────────────────────────────┤
│                    编排层 (流程调度)                      │
│                                                         │
│  ┌──────────────────────────────────────────────┐       │
│  │           Pipeline Orchestrator               │       │
│  │  (调度 Agent 执行顺序, 管理状态机, 决定是否继续)│      │
│  └──────────────────────────────────────────────┘       │
├─────────────────────────────────────────────────────────┤
│                    执行层 (已有模块)                      │
│                                                         │
│  因子计算引擎 | 回测引擎 | 因子评估器 | 知识库 | 数据库    │
└─────────────────────────────────────────────────────────┘
```

### 3.1 各层职责

**Agent 层**: 接收上下文 → LLM 推理 → 输出决策(结构化 JSON)。每个 Agent 有独立的系统 Prompt、决策规则、可调参数。

**编排层**: Pipeline Orchestrator 管理 Agent 执行顺序、状态流转、审批等待、错误重试。本质是一个状态机。

**执行层**: 回测引擎、因子计算、评估器等已有模块。Agent 的决策最终通过执行层落地。

---

## 四、Pipeline 完整流程

### 4.1 闭环流程图

```
因子发现 Agent
    ↓ 候选因子列表
因子评估(自动)
    ↓ 通过阈值的因子
入库审批(人/自动, 按 Level)
    ↓ 入库的因子
策略构建 Agent
    ↓ 策略定义 + 配置
回测验证(自动)
    ↓ 回测结果
结果分析(自动)
    ↓ 绩效指标
风控检查 Agent
    ↓ 通过/拒绝/警告
诊断优化 Agent
    ↓ 诊断报告 + 优化建议
    ├── 策略达标 → 部署审批(人) → 部署到模拟盘
    └── 策略不达标
            ├── Alpha 不足 → 触发因子发现 Agent(循环)
            └── 参数问题 → 触发策略构建 Agent(循环)
```

### 4.2 状态机定义

```python
class PipelineState(Enum):
    """Pipeline 状态机"""
    IDLE = 'idle'
    FACTOR_DISCOVERY = 'factor_discovery'
    FACTOR_EVALUATION = 'factor_evaluation'
    FACTOR_APPROVAL_PENDING = 'factor_approval_pending'
    STRATEGY_BUILD = 'strategy_build'
    BACKTEST_RUNNING = 'backtest_running'
    RESULT_ANALYSIS = 'result_analysis'
    RISK_CHECK = 'risk_check'
    DIAGNOSIS = 'diagnosis'
    DEPLOY_APPROVAL_PENDING = 'deploy_approval_pending'
    COMPLETED = 'completed'
    FAILED = 'failed'
```

状态转移规则:

```
IDLE → FACTOR_DISCOVERY (触发)
FACTOR_DISCOVERY → FACTOR_EVALUATION (发现完成)
FACTOR_EVALUATION → FACTOR_APPROVAL_PENDING (有候选因子, L0/L1)
FACTOR_EVALUATION → STRATEGY_BUILD (无需审批, L2/L3, 或无新因子)
FACTOR_APPROVAL_PENDING → STRATEGY_BUILD (审批完成)
STRATEGY_BUILD → BACKTEST_RUNNING (策略生成)
BACKTEST_RUNNING → RESULT_ANALYSIS (回测完成)
RESULT_ANALYSIS → RISK_CHECK (分析完成)
RISK_CHECK → DIAGNOSIS (风控完成)
DIAGNOSIS → DEPLOY_APPROVAL_PENDING (策略达标, L0/L1/L2)
DIAGNOSIS → FACTOR_DISCOVERY (Alpha 不足, 循环)
DIAGNOSIS → STRATEGY_BUILD (参数问题, 循环)
DEPLOY_APPROVAL_PENDING → COMPLETED (审批通过, 部署)
```

### 4.3 循环限制

为防止无限循环:
- 单轮 Pipeline 最大循环次数: 3（因子发现→诊断→再发现, 最多 3 轮）
- 超过后标记为 COMPLETED + 附带"未达标"标签, 通知用户人工干预

---

## 五、四个 Agent 详细设计

### 5.1 因子发现 Agent (FactorDiscoveryAgent)

**触发条件**:
- 定时触发(每周一次, 可配置)
- 手动触发
- 诊断 Agent 触发("Alpha 源不足, 需要新因子")

**输入上下文**:
```python
@dataclass
class DiscoveryContext:
    current_factors: List[dict]       # 当前因子库: [{name, category, ic, ir, status}]
    category_stats: Dict[str, int]    # 各类别因子数量
    recent_ic_trend: Dict[str, float] # 各因子近 3 个月 IC 变化
    last_mining_results: List[dict]   # 上次挖掘结果(成功/失败/方法)
    knowledge_base_hints: List[str]   # 知识库中的未探索方向
```

**决策逻辑**:

```python
class FactorDiscoveryAgent:
    """因子发现 Agent"""

    def __init__(self, llm_client, config: AgentConfig):
        self.llm = llm_client
        self.config = config

    def decide(self, context: DiscoveryContext) -> DiscoveryDecision:
        """
        决策流程:
          1. 分析当前因子库覆盖:
             - 价量因子 > 15 个 → 转向其他类别
             - 某类别 0 个 → 优先探索
          2. 分析最近挖掘效果:
             - 上次 GP 效果好 → 继续 GP, 扩大搜索空间
             - 上次 GP 收敛 → 切换 LLM 探索新方向
             - 上次 LLM 命中率低 → 调整 Prompt 方向
          3. 分析 IC 趋势:
             - 因子库总 IC 均值下降 > 20% → 紧急模式, 多方法并行
          4. 选择挖掘方法 + 配置参数
          5. 输出结构化决策
        """
        pass

    def _build_prompt(self, context: DiscoveryContext) -> str:
        """构建 LLM Prompt(用于 LLM 生成模式和方向决策)"""
        pass


@dataclass
class DiscoveryDecision:
    method: str              # 'gp' | 'llm' | 'brute' | 'multi'(多方法并行)
    target_category: str     # 目标类别
    reasoning: str           # 决策推理过程(可审计)
    config: dict             # 挖掘任务配置
    urgency: str             # 'normal' | 'urgent'(IC 衰退触发)
```

**可配置参数**:

```python
@dataclass
class DiscoveryAgentConfig:
    # 挖掘触发
    schedule_cron: str = '0 2 * * 1'         # 每周一凌晨 2 点
    category_saturation: int = 15            # 类别因子数饱和阈值
    ic_decline_threshold: float = 0.20       # IC 下降触发紧急挖掘

    # GP 默认参数
    gp_population: int = 500
    gp_generations: int = 50
    gp_max_depth: int = 4

    # LLM 参数
    llm_model: str = 'deepseek'             # 'deepseek' | 'mlx_local'
    llm_temperature: float = 0.8
    llm_candidates_per_run: int = 10

    # 入库阈值
    ic_threshold: float = 0.02
    ic_ir_threshold: float = 0.3
    correlation_threshold: float = 0.7
    coverage_threshold: float = 0.80

    # GP 收敛检测
    gp_stale_rounds: int = 3                # 连续 N 轮无新发现则切换方法
```

### 5.2 策略构建 Agent (StrategyBuildAgent)

**触发条件**:
- 新因子入库后自动触发
- 定期重新优化(每月)
- 手动触发
- 诊断 Agent 触发(参数问题)

**输入上下文**:
```python
@dataclass
class StrategyContext:
    active_factors: List[dict]          # 所有 active 因子 + IC/IR/衰减/相关性
    current_strategy: Optional[dict]    # 当前部署的策略(如有)
    recent_backtest_results: List[dict] # 最近 N 次回测结果
    diagnostic_suggestions: Optional[dict]  # 诊断 Agent 的优化建议(如有)
```

**决策逻辑**:

```python
class StrategyBuildAgent:
    """策略构建 Agent"""

    def decide(self, context: StrategyContext) -> StrategyDecision:
        """
        决策流程:
          1. 因子筛选:
             - 排除 IC 衰退因子(近 3 月 IC < 历史 IC × 0.5)
             - 排除高相关冗余(保留 IC_IR 更高的)
          2. 权重优化(选最优方法):
             - IC_IR 加权(简单有效)
             - 最大化组合 IC_IR(优化问题)
             - ML 特征重要性
          3. 参数搜索(在验证集上):
             - 持仓数量: [10, 20, 30, 40, 50]
             - 调仓频率: [周, 双周, 月]
          4. 如果有诊断建议 → 优先按建议调整
          5. 生成策略定义 + 推荐配置
        """
        pass


@dataclass
class StrategyDecision:
    selected_factors: List[str]
    factor_weights: Dict[str, float]
    compose_method: str                 # 'ic_weight' | 'equal_weight' | 'ml'
    holding_count: int
    rebalance_freq: str
    reasoning: str
    backtest_config: dict               # 完整 BacktestConfig
```

**可配置参数**:

```python
@dataclass
class StrategyAgentConfig:
    schedule_cron: str = '0 3 1 * *'         # 每月 1 日凌晨 3 点
    ic_decay_threshold: float = 0.5          # IC 衰退阈值(近 3 月/历史)
    min_factors: int = 3                     # 最少因子数
    max_factors: int = 15                    # 最多因子数
    holding_count_range: List[int] = field(default_factory=lambda: [10, 20, 30, 40, 50])
    rebalance_freq_options: List[str] = field(default_factory=lambda: ['weekly', 'biweekly', 'monthly'])
```

### 5.3 诊断优化 Agent (DiagnosticAgent)

**触发条件**:
- 每次回测完成后自动触发
- 模拟盘/实盘周度体检
- 手动触发

**输入上下文**:
```python
@dataclass
class DiagnosticContext:
    backtest_result: dict               # 回测绩效指标
    target_metrics: dict                # 目标(年化 15-25%, Sharpe 1.0-2.0, MDD <15%)
    factor_ic_trends: Dict[str, float]  # 各因子 IC 趋势
    trade_analysis: dict                # 交易分析(成交失败率/成本占比)
    live_vs_backtest: Optional[dict]    # 实盘 vs 回测对比(如有)
    current_strategy: dict              # 当前策略配置
```

**决策逻辑(诊断树)**:

```python
class DiagnosticAgent:
    """诊断优化 Agent"""

    def diagnose(self, context: DiagnosticContext) -> DiagnosticReport:
        """
        诊断树:

        收益不足? (年化 < 15%)
        ├─ 全部因子 IC < 0.02
        │  → 诊断: Alpha 源不足
        │  → 动作: 触发因子发现 Agent
        ├─ IC 正常但回测收益低
        │  → 诊断: 交易成本过高(换手率)
        │  → 建议: 降低调仓频率 / 提高因子自相关要求
        ├─ 成本正常但收益低
        │  → 诊断: 因子合成方法不优
        │  → 建议: 切换到 IC 加权 / ML
        └─ 某些年份特别差
           → 诊断: 需要条件因子(分市场状态)
           → 建议: 探索市场状态条件因子

        回撤过大? (MDD > 15%)
        ├─ 行业集中度 > 40%
        │  → 建议: 降低行业上限
        ├─ 个股集中度高
        │  → 建议: 增加持仓数量
        └─ 特定月份大亏
           → 分析: 系统性风险 vs 策略失效

        实盘衰减 > 30%? (如有实盘数据)
        ├─ 滑点差异大 → 调高滑点系数
        ├─ 成交失败多 → 放宽流动性要求
        └─ 信号延迟 → 检查数据更新时效

        Sharpe 达标? (1.0-2.0)
        ├─ < 1.0 → 综合以上诊断
        └─ > 2.0 → 警告: 可能过拟合, 检查 WF 验证
        """
        pass

    def suggest_actions(self, diagnosis: list) -> List[Action]:
        """
        将诊断转化为可执行动作:
          - 自动执行: 调整因子权重, 淘汰失效因子
          - 需审批: 更换策略, 调整仓位
          - 触发其他 Agent: 因子发现, 策略重建
        """
        pass


@dataclass
class DiagnosticReport:
    overall_status: str                 # 'healthy' | 'warning' | 'critical'
    issues: List[dict]                  # [{type, severity, description, evidence}]
    suggestions: List[dict]             # [{action, auto_executable, reasoning}]
    next_agent: Optional[str]           # 需要触发的下一个 Agent
    next_agent_context: Optional[dict]  # 传递给下一个 Agent 的上下文
```

**可配置参数**:

```python
@dataclass
class DiagnosticAgentConfig:
    # 诊断阈值
    min_annual_return: float = 0.15      # 年化收益下限
    max_mdd: float = 0.15               # MDD 上限
    min_sharpe: float = 1.0             # Sharpe 下限
    max_sharpe: float = 2.0             # Sharpe 上限(过拟合检测)
    live_decay_threshold: float = 0.30   # 实盘衰减阈值
    ic_monthly_decline: float = 0.30     # 因子月度 IC 下降阈值

    # 自动修复权限
    allow_auto_adjust_weights: bool = True
    allow_auto_archive_factors: bool = True
    allow_auto_change_strategy: bool = False    # 需审批
    allow_auto_adjust_position: bool = False    # 需审批
```

### 5.4 风控监督 Agent (RiskControlAgent)

**触发条件**:
- 策略部署前(必须通过)
- 模拟盘/实盘每日运行

**部署前检查**:

```python
class RiskControlAgent:
    """风控监督 Agent"""

    def pre_deploy_check(self, backtest_result: dict,
                         config: dict) -> RiskVerdict:
        """
        部署前检查清单:
          1. WF-OOS Sharpe / 全量 Sharpe < 0.5 → 拒绝(过拟合)
          2. 回测期 < 3 年 → 警告(样本不足)
          3. MDD > 20% → 警告(超目标)
          4. 因子数 < 3 → 警告(Alpha 来源单一)
          5. 年化换手 > 500% → 警告(成本过高)
          6. 单行业实际占比 > 50% → 拒绝(集中度风险)
        """
        pass

    def daily_monitor(self, live_data: dict) -> List[Alert]:
        """
        运行中每日监控:
          - 当日亏损 > 3% → 预警
          - 连续 5 日亏损 → 预警 + 建议减仓
          - 实盘 vs 回测衰减 > 50% → 红色警报 + 建议暂停
          - 持仓行业集中度突破阈值 → 预警
        """
        pass


@dataclass
class RiskVerdict:
    passed: bool
    level: str                          # 'pass' | 'warning' | 'reject'
    checks: List[dict]                  # [{check_name, passed, value, threshold, message}]
    blocking_reasons: List[str]         # 拒绝原因(如有)


@dataclass
class Alert:
    level: str                          # 'info' | 'warning' | 'critical'
    type: str                           # 'daily_loss' | 'consecutive_loss' | 'decay' | 'concentration'
    message: str
    action: str                         # 'notify' | 'suggest_reduce' | 'suggest_pause'
    auto_execute: bool                  # 是否自动执行(根据 Level 配置)
```

**可配置参数**:

```python
@dataclass
class RiskAgentConfig:
    # 部署前检查
    wf_overfit_threshold: float = 0.5    # WF/全量 Sharpe 比值下限
    min_backtest_years: int = 3
    max_mdd_deploy: float = 0.20
    min_factors_deploy: int = 3
    max_annual_turnover: float = 5.0     # 500%
    max_industry_concentration: float = 0.50

    # 运行中监控
    daily_loss_alert: float = 0.03       # 3%
    consecutive_loss_days: int = 5
    decay_critical_threshold: float = 0.50
    industry_breach_threshold: float = 0.40

    # 自动动作
    auto_pause_on_critical: bool = False  # 红色警报是否自动暂停
```

---

## 六、四级自动化控制

```
Level 0 — 全手动
  AI 只提供建议, 人执行全部操作
  适用: 初期验证阶段, 不信任 AI 决策

Level 1 — 半自动(默认)
  自动: 因子发现 + 评估 + 回测 + 诊断
  需人批: 因子入库 + 策略部署
  适用: 正常使用, 人保持关键决策权

Level 2 — 大部分自动
  自动: Level 1 全部 + 因子入库(通过阈值自动入)
  需人批: 仅策略部署到模拟盘/实盘
  适用: 因子库成熟后, 减少人工干预

Level 3 — 全自动
  自动: Level 2 全部 + 自动部署到模拟盘
  需人批: 仅实盘部署
  适用: 高度信任 AI, 模拟盘验证充分后
```

**Level 与审批规则映射**:

```python
APPROVAL_RULES = {
    # (action, level) → 'auto' | 'human'
    ('factor_entry', 0): 'human',
    ('factor_entry', 1): 'human',
    ('factor_entry', 2): 'auto',
    ('factor_entry', 3): 'auto',

    ('strategy_deploy_paper', 0): 'human',
    ('strategy_deploy_paper', 1): 'human',
    ('strategy_deploy_paper', 2): 'human',
    ('strategy_deploy_paper', 3): 'auto',

    ('strategy_deploy_live', 0): 'human',
    ('strategy_deploy_live', 1): 'human',
    ('strategy_deploy_live', 2): 'human',
    ('strategy_deploy_live', 3): 'human',    # 实盘始终需人批

    ('auto_adjust_weights', 0): 'human',
    ('auto_adjust_weights', 1): 'auto',      # L1+ 允许自动调权重
    ('auto_archive_factor', 0): 'human',
    ('auto_archive_factor', 1): 'auto',      # L1+ 允许自动淘汰因子
}
```

---

## 七、Pipeline Orchestrator

```python
class PipelineOrchestrator:
    """
    Pipeline 编排器 — 管理 Agent 执行顺序和状态流转
    """

    def __init__(self, agents: Dict[str, Any],
                 automation_level: int = 1):
        self.agents = agents
        self.level = automation_level
        self.state = PipelineState.IDLE
        self.current_run: Optional[PipelineRun] = None
        self.loop_count = 0
        self.max_loops = 3

    def trigger(self, trigger_type: str = 'scheduled') -> str:
        """
        启动一轮完整 Pipeline
        trigger_type: 'scheduled' | 'manual' | 'diagnostic'
        返回: run_id
        """
        pass

    def advance(self):
        """
        推进状态机到下一步
        核心逻辑:
          1. 根据当前 state 执行对应 Agent
          2. 根据 Agent 输出决定下一个 state
          3. 如果需要审批 → 进入 PENDING 状态, 等待人工
          4. 如果诊断建议循环 → 检查 loop_count, 决定继续或停止
        """
        pass

    def on_approval(self, approval_id: int, approved: bool):
        """处理人工审批结果, 推进状态机"""
        pass

    def _should_continue_loop(self, diagnostic: DiagnosticReport) -> bool:
        """
        循环控制:
          - loop_count < max_loops → 允许继续
          - loop_count >= max_loops → 停止, 标记未达标
        """
        return self.loop_count < self.max_loops

    def _log_decision(self, agent_name: str,
                      decision_type: str,
                      reasoning: str,
                      action: str,
                      context: dict,
                      result: dict):
        """写入 agent_decision_log 表(可审计)"""
        pass
```

---

## 八、前端页面（6 个）— 摘要

> 完整布局/交互/组件设计详见 DEV_FRONTEND_UI.md 第三、四章

### 因子挖掘模块（4 个页面）

| 页面 | 核心功能 | 关键 API |
|------|---------|---------|
| ⑥ 因子实验室 | 5 种创建模式(手动/表达式/GP/LLM/枚举) + AI 助手 | POST /api/factor/mine/* |
| ⑦ 挖掘任务中心 | 运行监控 + 进度推送 + 任务统计 | WS /ws/factor-mine/{task_id} |
| ⑧ 因子评估报告 | 6+6 增强 Tab(IC/分组/衰减/相关性/分年度/分市场状态) | GET /api/factor/{id}/report |
| ⑨ 因子库 | 生命周期管理(new→active→degraded→archived) + 健康度面板 | GET /api/factor/library |

### AI 闭环模块（2 个页面）

| 页面 | 核心功能 | 关键 API |
|------|---------|---------|
| ⑩ Pipeline 控制台 | 4 级自动化 + 状态流程图 + 审批队列 + 决策日志 | GET /api/pipeline/status |
| ⑪ Agent 配置 | 4 个 Agent 的阈值/LLM/GP 参数配置面板 | GET/PUT /api/agent/{name}/config |

---

## 十、后端 API 清单

### 10.1 因子挖掘 API

| API 端点 | 方法 | 页面 | 功能 |
|---------|------|------|------|
| `/api/factor/create` | POST | ①实验室 | 手动创建因子 |
| `/api/factor/validate` | POST | ①实验室 | 语法检查+快速预览 |
| `/api/factor/mine/gp` | POST | ①实验室 | 启动 GP 挖掘 |
| `/api/factor/mine/llm` | POST | ①实验室 | 启动 LLM 生成 |
| `/api/factor/mine/brute` | POST | ①实验室 | 启动暴力枚举 |
| `/api/ai/factor-assist` | POST | ①实验室 | AI 因子助手对话 |
| `/api/factor/tasks` | GET | ②任务中心 | 任务列表 |
| `/api/factor/tasks/{id}` | GET/DELETE | ②任务中心 | 任务详情/终止 |
| `/api/factor/{id}/report` | GET | ③评估 | 因子评估报告 |
| `/api/factor/evaluate/batch` | POST | ③评估 | 批量评估 |
| `/api/factor/library` | GET | ④因子库 | 因子库列表 |
| `/api/factor/{id}` | GET/PUT/DELETE | ④因子库 | 因子 CRUD |
| `/api/factor/{id}/archive` | POST | ④因子库 | 淘汰因子 |
| `/api/factor/health-check` | POST | ④因子库 | 全量体检 |
| `/api/factor/correlation-prune` | POST | ④因子库 | 相关性裁剪 |
| `/ws/factor-mine/{task_id}` | WS | ②任务中心 | 挖掘进度推送 |

### 10.2 AI 闭环 API

| API 端点 | 方法 | 页面 | 功能 |
|---------|------|------|------|
| `/api/pipeline/status` | GET | 控制台 | Pipeline 实时状态 |
| `/api/pipeline/trigger` | POST | 控制台 | 手动触发 Pipeline |
| `/api/pipeline/pause` | POST | 控制台 | 暂停 Pipeline |
| `/api/pipeline/history` | GET | 控制台 | 运行历史 |
| `/api/pipeline/pending` | GET | 控制台 | 待审批队列 |
| `/api/pipeline/approve/{id}` | POST | 控制台 | 审批通过 |
| `/api/pipeline/reject/{id}` | POST | 控制台 | 审批拒绝 |
| `/api/agent/{name}/config` | GET/PUT | Agent 配置 | Agent 配置读取/更新 |
| `/api/agent/{name}/logs` | GET | 控制台 | Agent 决策日志 |
| `/ws/pipeline/{run_id}` | WS | 控制台 | Pipeline 进度推送 |

---

## 十一、数据库表结构（6 张新表）

### 11.1 factor_registry — 因子注册表

```sql
CREATE TABLE factor_registry (
    factor_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    category        VARCHAR(20) NOT NULL,
    direction       SMALLINT NOT NULL,             -- 1=正向, -1=反向
    source          VARCHAR(20) NOT NULL,          -- builtin/manual/gp/llm/brute
    expression      TEXT,
    code_content    TEXT,                           -- 完整 compute 函数代码
    description     TEXT,
    lookback_days   INT,
    -- 最新评估指标(冗余)
    ic_mean         FLOAT,
    ic_ir           FLOAT,
    long_short_annual FLOAT,
    coverage        FLOAT,
    autocorrelation FLOAT,
    -- 生命周期
    status          VARCHAR(20) DEFAULT 'new',     -- new/active/degraded/archived
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_evaluated  TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ,
    archive_reason  TEXT
);
CREATE INDEX idx_factor_status ON factor_registry(status);
CREATE INDEX idx_factor_category ON factor_registry(category);
```

### 11.2 factor_evaluation — 因子评估历史

```sql
CREATE TABLE factor_evaluation (
    eval_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factor_id       UUID REFERENCES factor_registry(factor_id),
    eval_date       TIMESTAMPTZ DEFAULT NOW(),
    eval_period     VARCHAR(50),
    -- 完整指标
    ic_mean         FLOAT,
    ic_std          FLOAT,
    ic_ir           FLOAT,
    ic_series       JSONB,                         -- 每日 IC(压缩)
    group_returns   JSONB,
    long_short_annual FLOAT,
    ic_decay        JSONB,                         -- {1: 0.043, 5: 0.038, ...}
    coverage        FLOAT,
    autocorrelation FLOAT,
    correlation_with_existing JSONB,               -- {factor_name: corr}
    yearly_metrics  JSONB,
    regime_metrics  JSONB                          -- {bull: {...}, bear: {...}}
);
CREATE INDEX idx_factor_eval_factor ON factor_evaluation(factor_id, eval_date DESC);
```

### 11.3 factor_mining_task — 因子挖掘任务

```sql
CREATE TABLE factor_mining_task (
    task_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    method          VARCHAR(20) NOT NULL,          -- gp/llm/brute/manual
    config_json     JSONB NOT NULL,
    status          VARCHAR(20) DEFAULT 'running', -- running/completed/failed
    total_candidates INT,
    passed_filter   INT,
    entered_library INT,
    best_ic_ir      FLOAT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    error_msg       TEXT
);
CREATE INDEX idx_mining_task_status ON factor_mining_task(status);
CREATE INDEX idx_mining_task_created ON factor_mining_task(created_at DESC);
```

### 11.4 pipeline_run — AI 闭环运行记录

```sql
CREATE TABLE pipeline_run (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_number    INT NOT NULL,
    trigger_type    VARCHAR(20),                   -- scheduled/manual/diagnostic
    automation_level INT DEFAULT 1,
    current_state   VARCHAR(30) DEFAULT 'idle',
    status          VARCHAR(20) DEFAULT 'running', -- running/completed/failed
    loop_count      INT DEFAULT 0,
    -- 各阶段结果摘要
    factors_discovered  INT DEFAULT 0,
    factors_approved    INT DEFAULT 0,
    strategy_updated    BOOLEAN DEFAULT FALSE,
    new_sharpe          FLOAT,
    prev_sharpe         FLOAT,
    deployed            BOOLEAN DEFAULT FALSE,
    -- 时间
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX idx_pipeline_created ON pipeline_run(created_at DESC);
```

### 11.5 agent_decision_log — Agent 决策日志

```sql
CREATE TABLE agent_decision_log (
    id              BIGSERIAL PRIMARY KEY,
    pipeline_run_id UUID REFERENCES pipeline_run(run_id),
    agent_name      VARCHAR(50) NOT NULL,
    decision_type   VARCHAR(50),
    reasoning       TEXT,                          -- AI 推理过程(可审计)
    action_taken    TEXT,
    input_context   JSONB,
    output_result   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_agent_log_pipeline ON agent_decision_log(pipeline_run_id);
CREATE INDEX idx_agent_log_agent ON agent_decision_log(agent_name, created_at DESC);
```

### 11.6 approval_queue — 审批队列

```sql
CREATE TABLE approval_queue (
    id              BIGSERIAL PRIMARY KEY,
    pipeline_run_id UUID REFERENCES pipeline_run(run_id),
    approval_type   VARCHAR(30) NOT NULL,          -- factor_entry/strategy_deploy/config_change
    item_id         UUID,
    item_summary    JSONB,
    status          VARCHAR(20) DEFAULT 'pending', -- pending/approved/rejected
    decided_by      VARCHAR(50),                   -- 'user' | 'auto'
    decided_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_approval_pending ON approval_queue(status) WHERE status = 'pending';
```

---

## 十二、工具函数库（因子编写用）

用户在因子实验室编写因子时可直接调用的预置函数。实现在 `factors/tools.py`。

```python
"""
因子工具函数库
所有函数接受 pd.Series(MultiIndex: date × stock_code) 输入
"""

# === 时序函数(沿时间轴, 每只股票独立) ===

def ts_mean(x: pd.Series, window: int) -> pd.Series:
    """时序滚动均值"""
    return x.groupby(level='stock_code').rolling(window).mean()

def ts_std(x: pd.Series, window: int) -> pd.Series:
    """时序滚动标准差"""
    pass

def ts_rank(x: pd.Series, window: int) -> pd.Series:
    """时序排名百分位: 当前值在过去 window 内的排名/window"""
    pass

def ts_max(x: pd.Series, window: int) -> pd.Series:
    """时序滚动最大值"""
    pass

def ts_min(x: pd.Series, window: int) -> pd.Series:
    """时序滚动最小值"""
    pass

def ts_delta(x: pd.Series, period: int) -> pd.Series:
    """差分: x - x.shift(period)"""
    pass

def ts_return(x: pd.Series, period: int) -> pd.Series:
    """收益率: x / x.shift(period) - 1"""
    pass

def ts_corr(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    """时序滚动相关性"""
    pass

def ts_decay_linear(x: pd.Series, window: int) -> pd.Series:
    """线性衰减加权均值: 近期权重高"""
    pass

# === 截面函数(沿股票轴, 每日独立) ===

def cs_rank(x: pd.Series) -> pd.Series:
    """横截面排名百分位(每日)"""
    return x.groupby(level='date').rank(pct=True)

def cs_zscore(x: pd.Series) -> pd.Series:
    """横截面标准化(每日)"""
    pass
```

---

## 十三、调度配置

```python
# 默认调度(Celery Beat / APScheduler)
PIPELINE_SCHEDULES = {
    'factor_discovery': {
        'cron': '0 2 * * 1',         # 每周一凌晨 2:00
        'description': '因子发现',
    },
    'strategy_optimize': {
        'cron': '0 3 1 * *',         # 每月 1 日凌晨 3:00
        'description': '策略重新优化',
    },
    'factor_health_check': {
        'cron': '0 4 1,15 * *',      # 每月 1、15 日凌晨 4:00
        'description': '因子库体检',
    },
    'diagnostic_report': {
        'cron': '0 8 * * 1',         # 每周一上午 8:00
        'description': '模拟盘周度诊断',
    },
}
```

---

## 十四、与其他模块的关系

| 模块 | 关系 |
|------|------|
| 回测引擎(DEV_BACKTEST_ENGINE.md) | 策略构建 Agent 调用回测引擎验证策略 |
| 因子挖掘(DEV_FACTOR_MINING.md) | 因子发现 Agent 调用 GP/LLM/暴力枚举引擎 |
| 参数可配置(DEV_PARAM_CONFIG.md) | 所有 Agent 配置参数前端可调 |
| 模拟盘/实盘 | 风控 Agent 监控运行中策略, 部署审批后写入 |
| 知识库(ChromaDB) | 因子发现 Agent 查询知识库获取探索方向 |
| 前端 React | Pipeline 控制台 + Agent 配置 + 因子挖掘 4 页面 |

---

## 十五、实现优先级

```
Phase 0 — 质量优先 MVP:
  ✗ AI 闭环不在 Phase 0 范围内
  ✓ 因子实验室(手动编写 + 暴力枚举)可先做
  ✓ 因子评估报告可先做
  ✓ 因子库基础管理可先做

Phase 1 — A 股完整 + AI 模块化替换:
  ✓ GP 遗传编程
  ✓ LLM 生成(DeepSeek API)
  ✓ 策略构建 Agent(基础版)
  ✓ 诊断 Agent(基础版)

Phase 2+:
  ✓ 完整 4 Agent 闭环
  ✓ Pipeline 编排器
  ✓ 全部自动化级别
  ✓ Agent 决策日志审计
```

---

## 十六、补充设计（V5.1）

### 16.1 诊断Agent完整阈值表（A1补充）

| 诊断维度 | 指标 | 🟢健康 | 🟡预警 | 🔴严重 | 触发动作 |
|---------|------|--------|--------|--------|---------|
| 收益 | 年化收益率 | >15% | 5-15% | <5% | 🟡触发策略构建Agent 🔴触发因子发现Agent |
| 风险 | MDD | <15% | 15-25% | >25% | 🟡降低持仓集中度 🔴熔断+全面诊断 |
| 效率 | Sharpe | >1.0 | 0.5-1.0 | <0.5 | 🟡检查因子合成 🔴重新策略构建 |
| 过拟合 | Sharpe>2.0 | — | 2.0-3.0 | >3.0 | 🟡检查WF 🔴强制DSR/PBO验证 |
| 因子 | 平均IC | >0.03 | 0.02-0.03 | <0.02 | 🟡体检个别因子 🔴触发批量因子挖掘 |
| 因子衰退 | IC下降幅度 | <20% | 20-40% | >40% | 🟡标记degraded 🔴淘汰+替换 |
| 成本 | 换手率成本占比 | <15% | 15-30% | >30% | 🟡降低调仓频率 🔴换手控制加严 |
| 集中度 | 行业最大占比 | <25% | 25-40% | >40% | 🟡约束调整 🔴强制分散 |
| 实盘衰减 | 实盘/回测收益比 | >70% | 50-70% | <50% | 🟡调高滑点 🔴暂停策略诊断 |
| 连续亏损 | 月度连亏 | <2月 | 2-3月 | >3月 | 🟡检查市场状态 🔴暂停策略 |

### 16.2 A股策略构建Agent的Optuna搜索空间（A2补充）

```python
class AStockStrategyOptimizer:
    """A股策略参数Optuna搜索"""

    def optimize(self, data, n_trials=100):
        import optuna

        def objective(trial):
            params = {
                # 因子合成
                'compose_method': trial.suggest_categorical('compose', ['ic_weight', 'equal_weight']),

                # 组合构建
                'holding_count': trial.suggest_int('holding', 10, 50, step=5),
                'rebalance_freq': trial.suggest_categorical('rebal', ['weekly', 'biweekly', 'monthly']),
                'weight_method': trial.suggest_categorical('weight', ['equal', 'ic_weighted', 'risk_parity']),

                # 风控
                'industry_max_pct': trial.suggest_float('ind_max', 0.15, 0.40, step=0.05),
                'single_stock_max_pct': trial.suggest_float('stock_max', 0.03, 0.10, step=0.01),
                'turnover_limit': trial.suggest_float('turnover', 0.3, 1.0, step=0.1),

                # 动态仓位(Phase 1)
                'dynamic_position_enabled': trial.suggest_categorical('dyn_pos', [True, False]),
                'market_state_ma': trial.suggest_int('ma_period', 60, 250, step=10),
            }

            sharpe = run_wf_backtest(data, params)
            return sharpe

        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials, timeout=600)

        return {
            'best_params': study.best_params,
            'best_sharpe': study.best_value,
            'param_importance': optuna.importance.get_param_importances(study),
        }
```

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. AI诊断触发机制（覆盖定时触发设计）

诊断Agent不只周日定时跑——**绩效衰退>阈值时事件驱动即时触发**:
```python
# 每日盘后绩效计算后检查
async def check_performance_trigger(perf: PerformanceMetrics):
    rolling_sharpe_20d = perf.calc_rolling_sharpe(window=20)
    backtest_sharpe = await get_backtest_sharpe()
    
    # 近20日Sharpe低于回测的50% → 即时触发诊断
    if rolling_sharpe_20d < backtest_sharpe * 0.5:
        await trigger_diagnosis_pipeline(reason='sharpe_decay', 
                                         data={'rolling_20d': rolling_sharpe_20d})
```

`performance_series`表加**滚动绩效视图**（DB VIEW或物化视图）：
```sql
CREATE VIEW v_rolling_performance AS
SELECT date,
    AVG(daily_return) OVER (ORDER BY date ROWS 19 PRECEDING) * 252 / 
    NULLIF(STDDEV(daily_return) OVER (ORDER BY date ROWS 19 PRECEDING), 0) * SQRT(252) AS sharpe_20d,
    -- 类似计算 sharpe_60d, sharpe_120d, mdd_20d, mdd_60d
FROM performance_series;
```

### P2. Agent输入context组装逻辑

诊断Agent的LLM调用必须有明确的数据来源：
```python
async def assemble_diagnosis_context() -> dict:
    return {
        'performance': await query_rolling_performance(windows=[20, 60, 120]),
        'factor_ic_history': await query_factor_ic_recent(days=60),
        'active_factors': await get_active_factors_with_weights(),
        'recent_trades': await get_recent_trades(days=20),
        'market_state': await get_current_market_state(),
        'trigger_reason': trigger_reason,
    }
```
从 performance_series + factor_ic_history + active_factors + recent_trades 四张表拉数据，
拼成结构化JSON给LLM。

### P3. AI变更验证上线三步流程

```
1. AI输出变更建议 → 写入 approval_queue（不直接生效!）
   变更类型: 淘汰因子 / 增加因子 / 调整权重 / 调整参数

2. 自动触发快速回测验证（最近1年，非全量5年）
   对比: 变更前 vs 变更后的 Sharpe/MDD/换手率
   如果变更后 Sharpe 下降 >10% 或 MDD 恶化 >20% → 自动拒绝

3. 验证通过 → 等待人工审批 → 审批通过 → 生效到次日信号链路
   验证不通过 → 自动拒绝 + 记录原因到 agent_decision_log
```
**不允许AI变更跳过回测验证直接上线。**

### P4. Agent冲突仲裁（Phase 3）

- 风控Agent有**一票否决权**（安全优先）
- 因子发现和策略构建的分歧由回测结果裁定
- 所有冲突记录到 `agent_decision_log` 表
