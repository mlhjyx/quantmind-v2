"""参数默认值定义 — 核心50个参数的约束与元数据。

DEV_PARAM_CONFIG.md: 四级控制体系（L0硬编码/L1配置文件/L2前端可调/L3 AI自动调）。
本文件定义L2级别参数的默认值、类型、范围约束和所属模块。

DDL对应表: ai_parameters (param_name/param_value/param_min/param_max/param_default/param_type/module)
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ParamType(StrEnum):
    """参数值类型。"""

    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    ENUM = "enum"
    STR = "str"
    LIST = "list"


class ParamModule(StrEnum):
    """参数所属模块。"""

    FACTOR = "factor"
    SIGNAL = "signal"
    BACKTEST = "backtest"
    RISK = "risk"
    PAPER_TRADING = "paper_trading"
    UNIVERSE = "universe"
    EXECUTION = "execution"
    GP_ENGINE = "gp_engine"
    LLM_MINING = "llm_mining"
    SCHEDULER = "scheduler"
    DATA = "data"
    NOTIFICATION = "notification"
    MONITOR = "monitor"
    SYSTEM = "system"
    MODIFIER = "modifier"
    AI_AGENT = "ai_agent"
    WALK_FORWARD = "walk_forward"


@dataclass(frozen=True)
class ParamDef:
    """单个参数的完整定义。

    Attributes:
        key: 参数唯一标识，格式为 module.param_name。
        default_value: 默认值。
        param_type: 值类型。
        module: 所属模块。
        description: 中文说明。
        min_value: 最小值（数值型参数）。
        max_value: 最大值（数值型参数）。
        enum_options: 枚举选项（enum型参数）。
        level: 控制级别 L0-L3。
    """

    key: str
    default_value: Any
    param_type: ParamType
    module: ParamModule
    description: str
    min_value: int | float | None = None
    max_value: int | float | None = None
    enum_options: list[str] | None = None
    level: str = "L2"


# ═══════════════════════════════════════════════════
# 核心参数定义（50个，按模块分组）
# ═══════════════════════════════════════════════════

PARAM_DEFINITIONS: dict[str, ParamDef] = {}


def _register(*params: ParamDef) -> None:
    """批量注册参数定义。"""
    for p in params:
        PARAM_DEFINITIONS[p.key] = p


# --- 因子模块 (factor) ---
_register(
    ParamDef(
        key="factor.ic_threshold",
        default_value=0.02,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="因子IC绝对值阈值，低于此值的因子不进入候选池",
        min_value=0.005,
        max_value=0.1,
    ),
    ParamDef(
        key="factor.ic_decay_window",
        default_value=60,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="IC衰减评估窗口（交易日数）",
        min_value=20,
        max_value=250,
    ),
    ParamDef(
        key="factor.neutralize_method",
        default_value="market_industry",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="因子中性化方法（CLAUDE.md: 先中性化再标准化）",
        enum_options=["none", "market", "industry", "market_industry"],
    ),
    ParamDef(
        key="factor.preprocess_mad_multiplier",
        default_value=5.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="MAD去极值倍数（中位数绝对偏差的倍数）",
        min_value=2.0,
        max_value=10.0,
    ),
    ParamDef(
        key="factor.missing_fill_method",
        default_value="industry_median",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="缺失值填充方法",
        enum_options=["zero", "median", "industry_median", "forward_fill"],
    ),
    ParamDef(
        key="factor.max_active_count",
        default_value=20,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="最大活跃因子数量",
        min_value=5,
        max_value=50,
    ),
    ParamDef(
        key="factor.min_active_count",
        default_value=12,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="最小活跃因子数量（低于此值触发P1告警+紧急挖掘）",
        min_value=5,
        max_value=30,
    ),
    ParamDef(
        key="factor.crowding_threshold",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="因子拥挤度阈值，超过则自动降权",
        min_value=0.3,
        max_value=0.95,
    ),
    ParamDef(
        key="factor.critical_to_retired_days",
        default_value=10,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="因子critical状态持续N个交易日后自动退休",
        min_value=5,
        max_value=30,
    ),
)

# --- 信号模块 (signal) ---
_register(
    ParamDef(
        key="signal.top_n",
        default_value=30,
        param_type=ParamType.INT,
        module=ParamModule.SIGNAL,
        description="Top-N选股数量",
        min_value=5,
        max_value=100,
    ),
    ParamDef(
        key="signal.weight_method",
        default_value="equal",
        param_type=ParamType.ENUM,
        module=ParamModule.SIGNAL,
        description="权重分配方式（CLAUDE.md: 等权Top-N为基线）",
        enum_options=["equal", "ic_weighted", "risk_parity"],
    ),
    ParamDef(
        key="signal.rebalance_freq",
        default_value="weekly",
        param_type=ParamType.ENUM,
        module=ParamModule.SIGNAL,
        description="调仓频率",
        enum_options=["daily", "weekly", "biweekly", "monthly"],
    ),
    ParamDef(
        key="signal.industry_cap",
        default_value=0.2,
        param_type=ParamType.FLOAT,
        module=ParamModule.SIGNAL,
        description="单行业持仓上限比例",
        min_value=0.05,
        max_value=0.5,
    ),
    ParamDef(
        key="signal.turnover_cap",
        default_value=0.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.SIGNAL,
        description="单次调仓换手率上限（CLAUDE.md: 50%）",
        min_value=0.1,
        max_value=1.0,
    ),
    ParamDef(
        key="signal.single_stock_cap",
        default_value=0.1,
        param_type=ParamType.FLOAT,
        module=ParamModule.SIGNAL,
        description="单只股票持仓上限比例",
        min_value=0.02,
        max_value=0.3,
    ),
)

# --- 回测模块 (backtest) ---
_register(
    ParamDef(
        key="backtest.initial_capital",
        default_value=1000000.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="回测初始资金（元）",
        min_value=100000.0,
        max_value=100000000.0,
    ),
    ParamDef(
        key="backtest.slippage_bps",
        default_value=5.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点（基点，1bps=0.01%）, fixed模式使用",
        min_value=0.0,
        max_value=50.0,
    ),
    ParamDef(
        key="backtest.slippage_mode",
        default_value="volume_impact",
        param_type=ParamType.STR,
        module=ParamModule.BACKTEST,
        description="滑点模型: volume_impact(市值分层动态) / fixed(固定bps)",
    ),
    ParamDef(
        key="backtest.slippage_Y_large",
        default_value=0.8,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点冲击乘数Y-大盘(500亿+, Bouchaud 2018)",
        min_value=0.1,
        max_value=3.0,
    ),
    ParamDef(
        key="backtest.slippage_Y_mid",
        default_value=1.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点冲击乘数Y-中盘(100-500亿)",
        min_value=0.1,
        max_value=3.0,
    ),
    ParamDef(
        key="backtest.slippage_Y_small",
        default_value=1.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点冲击乘数Y-小盘(100亿以下)",
        min_value=0.1,
        max_value=3.0,
    ),
    ParamDef(
        key="backtest.slippage_base_bps",
        default_value=5.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="基础滑点(bps, bid-ask spread)",
        min_value=0.0,
        max_value=20.0,
    ),
    ParamDef(
        key="backtest.volume_cap_pct",
        default_value=0.10,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="单日成交量上限(占日成交量%, DEV_PARAM_CONFIG.md §3.7)",
        min_value=0.05,
        max_value=0.30,
    ),
    ParamDef(
        key="backtest.commission_rate",
        default_value=0.0003,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="佣金费率（双边）",
        min_value=0.0,
        max_value=0.003,
    ),
    ParamDef(
        key="backtest.stamp_tax_rate",
        default_value=0.0005,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="印花税率（卖出单边收取）",
        min_value=0.0,
        max_value=0.003,
    ),
    ParamDef(
        key="backtest.lot_size",
        default_value=100,
        param_type=ParamType.INT,
        module=ParamModule.BACKTEST,
        description="最小交易单位（A股100股/手，CLAUDE.md回测规则2）",
        min_value=1,
        max_value=1000,
        level="L0",
    ),
    ParamDef(
        key="backtest.benchmark",
        default_value="000300.SH",
        param_type=ParamType.STR,
        module=ParamModule.BACKTEST,
        description="基准指数代码（沪深300）",
    ),
    ParamDef(
        key="backtest.bootstrap_samples",
        default_value=1000,
        param_type=ParamType.INT,
        module=ParamModule.BACKTEST,
        description="Bootstrap采样次数（CLAUDE.md回测规则4）",
        min_value=100,
        max_value=10000,
    ),
    ParamDef(
        key="backtest.cost_sensitivity_multipliers",
        default_value=[0.5, 1.0, 1.5, 2.0],
        param_type=ParamType.LIST,
        module=ParamModule.BACKTEST,
        description="成本敏感性分析的倍数列表（CLAUDE.md回测规则6）",
    ),
)

# --- 风控模块 (risk) ---
_register(
    ParamDef(
        key="risk.l1_single_stock_loss",
        default_value=-0.08,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L1风控: 个股止损线（相对买入价跌幅）",
        min_value=-0.3,
        max_value=-0.01,
    ),
    ParamDef(
        key="risk.l2_portfolio_daily_loss",
        default_value=-0.03,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L2风控: 组合日亏损阈值",
        min_value=-0.1,
        max_value=-0.005,
    ),
    ParamDef(
        key="risk.l3_monthly_drawdown",
        default_value=-0.10,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L3风控: 月度回撤阈值（触发降仓，CLAUDE.md回撤熔断状态机）",
        min_value=-0.3,
        max_value=-0.03,
    ),
    ParamDef(
        key="risk.l4_total_drawdown",
        default_value=-0.25,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L4风控: 累计回撤阈值（触发停止，需人工审批重启）",
        min_value=-0.5,
        max_value=-0.1,
    ),
    ParamDef(
        key="risk.l3_recovery_profit",
        default_value=0.02,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L3降仓恢复条件: 连续5日累计盈利阈值",
        min_value=0.005,
        max_value=0.1,
    ),
    ParamDef(
        key="risk.l3_recovery_days",
        default_value=5,
        param_type=ParamType.INT,
        module=ParamModule.RISK,
        description="L3降仓恢复条件: 连续盈利天数",
        min_value=3,
        max_value=20,
    ),
    ParamDef(
        key="risk.position_reduce_ratio",
        default_value=0.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L3降仓比例（保留多少仓位）",
        min_value=0.1,
        max_value=0.8,
    ),
)

# --- Paper Trading模块 ---
_register(
    ParamDef(
        key="paper_trading.graduation_days",
        default_value=60,
        param_type=ParamType.INT,
        module=ParamModule.PAPER_TRADING,
        description="Paper Trading毕业最低运行天数（CLAUDE.md: >=60交易日）",
        min_value=20,
        max_value=250,
    ),
    ParamDef(
        key="paper_trading.graduation_sharpe_ratio",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.PAPER_TRADING,
        description="毕业标准: Sharpe >= 回测Sharpe * 此比例",
        min_value=0.3,
        max_value=1.0,
    ),
    ParamDef(
        key="paper_trading.graduation_mdd_ratio",
        default_value=1.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.PAPER_TRADING,
        description="毕业标准: 最大回撤 <= 回测MDD * 此倍数",
        min_value=1.0,
        max_value=3.0,
    ),
    ParamDef(
        key="paper_trading.graduation_slippage_deviation",
        default_value=0.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.PAPER_TRADING,
        description="毕业标准: 滑点偏差 < 此比例（CLAUDE.md: 50%）",
        min_value=0.1,
        max_value=1.0,
    ),
    ParamDef(
        key="paper_trading.initial_capital",
        default_value=1000000.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.PAPER_TRADING,
        description="模拟账户初始资金（元）",
        min_value=100000.0,
        max_value=100000000.0,
    ),
)

# --- 选股宇宙模块 (universe) ---
_register(
    ParamDef(
        key="universe.min_market_cap",
        default_value=2000000000.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.UNIVERSE,
        description="最小市值（元），过滤小盘股",
        min_value=0.0,
        max_value=50000000000.0,
    ),
    ParamDef(
        key="universe.exclude_st",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.UNIVERSE,
        description="是否排除ST/*ST股票",
    ),
    ParamDef(
        key="universe.exclude_suspended",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.UNIVERSE,
        description="是否排除停牌股",
    ),
    ParamDef(
        key="universe.min_listing_days",
        default_value=60,
        param_type=ParamType.INT,
        module=ParamModule.UNIVERSE,
        description="最小上市天数（排除次新股）",
        min_value=0,
        max_value=365,
    ),
    ParamDef(
        key="universe.min_avg_turnover",
        default_value=5000000.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.UNIVERSE,
        description="最小日均成交额（元），过滤流动性差的票",
        min_value=0.0,
        max_value=100000000.0,
    ),
)

# --- 执行模块 (execution) ---
_register(
    ParamDef(
        key="execution.mode",
        default_value="paper",
        param_type=ParamType.ENUM,
        module=ParamModule.EXECUTION,
        description="执行模式（CLAUDE.md: Broker策略模式）",
        enum_options=["paper", "live"],
    ),
    ParamDef(
        key="execution.partial_fill_action",
        default_value="continue_next_day",
        param_type=ParamType.ENUM,
        module=ParamModule.EXECUTION,
        description="部分成交处理方式（CLAUDE.md: 剩余次日继续执行）",
        enum_options=["cancel", "continue_next_day"],
    ),
    ParamDef(
        key="execution.delist_force_sell_days",
        default_value=5,
        param_type=ParamType.INT,
        module=ParamModule.EXECUTION,
        description="退市前强制平仓天数（CLAUDE.md: 5个交易日）",
        min_value=1,
        max_value=20,
    ),
)

# --- GP遗传编程引擎 (gp_engine) ---
_register(
    ParamDef(
        key="gp_engine.population_size",
        default_value=500,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="GP种群大小",
        min_value=100,
        max_value=2000,
    ),
    ParamDef(
        key="gp_engine.generations",
        default_value=100,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="GP进化代数",
        min_value=20,
        max_value=500,
    ),
    ParamDef(
        key="gp_engine.crossover_rate",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="GP交叉率",
        min_value=0.1,
        max_value=0.95,
    ),
    ParamDef(
        key="gp_engine.mutation_rate",
        default_value=0.1,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="GP变异率",
        min_value=0.01,
        max_value=0.5,
    ),
    ParamDef(
        key="gp_engine.anti_crowding_threshold",
        default_value=0.6,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="反拥挤相关性阈值（CLAUDE.md: 降到0.5-0.6）",
        min_value=0.5,
        max_value=0.95,
    ),
)

# --- 调度模块 (scheduler) ---
_register(
    ParamDef(
        key="scheduler.data_pull_time",
        default_value="16:30",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="T日数据拉取开始时间（CLAUDE.md: 16:30）",
    ),
    ParamDef(
        key="scheduler.pre_market_confirm_time",
        default_value="08:30",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="T+1日盘前确认时间（CLAUDE.md: 08:30）",
    ),
    ParamDef(
        key="scheduler.health_check_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.SCHEDULER,
        description="是否启用全链路健康预检（CLAUDE.md: 调度第一步）",
    ),
)

# --- 组合构建模块 (portfolio) — §3.4 ---
_register(
    ParamDef(
        key="signal.top_n_min",
        default_value=10,
        param_type=ParamType.INT,
        module=ParamModule.SIGNAL,
        description="选股数量下限（DESIGN_V5 §6.2，可配置[10-50]）",
        min_value=5,
        max_value=50,
    ),
    ParamDef(
        key="signal.top_n_max",
        default_value=50,
        param_type=ParamType.INT,
        module=ParamModule.SIGNAL,
        description="选股数量上限（DESIGN_V5 §6.2，可配置[10-50]）",
        min_value=10,
        max_value=100,
    ),
    ParamDef(
        key="signal.alpha_score_method",
        default_value="equal",
        param_type=ParamType.ENUM,
        module=ParamModule.SIGNAL,
        description="Alpha Score合成方式（DEV_BACKTEST_ENGINE §6.2：等权/IC加权/LightGBM）",
        enum_options=["equal", "ic_weighted", "lightgbm"],
    ),
    ParamDef(
        key="signal.cash_buffer_pct",
        default_value=0.03,
        param_type=ParamType.FLOAT,
        module=ParamModule.SIGNAL,
        description="现金缓冲比例（R3 CompositeStrategy权重归一化后保留3%现金）",
        min_value=0.0,
        max_value=0.1,
    ),
    ParamDef(
        key="signal.turnover_cap_min",
        default_value=0.10,
        param_type=ParamType.FLOAT,
        module=ParamModule.SIGNAL,
        description="换手率上限下界（DEV_PARAM_CONFIG §3.4，可配置[10%-80%]）",
        min_value=0.05,
        max_value=0.5,
    ),
    ParamDef(
        key="signal.turnover_cap_max",
        default_value=0.80,
        param_type=ParamType.FLOAT,
        module=ParamModule.SIGNAL,
        description="换手率上限上界（DEV_PARAM_CONFIG §3.4，可配置[10%-80%]）",
        min_value=0.1,
        max_value=1.0,
    ),
)

# --- 因子计算参数 (factor preprocessing) — §3.10 ---
_register(
    ParamDef(
        key="factor.winsorize_std",
        default_value=3.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Winsorize去极值标准差倍数（DEV_FACTOR_MINING：3σ截断）",
        min_value=1.0,
        max_value=5.0,
    ),
    ParamDef(
        key="factor.zscore_clip",
        default_value=3.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Z-Score标准化后截断值（DEV_FACTOR_MINING：±3截断）",
        min_value=1.5,
        max_value=5.0,
    ),
    ParamDef(
        key="factor.preprocess_method",
        default_value="mad",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="去极值方法（DEV_PARAM_CONFIG §3.10：MAD/Winsorize/3σ）",
        enum_options=["mad", "winsorize", "sigma3"],
    ),
    ParamDef(
        key="factor.normalize_method",
        default_value="zscore",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="标准化方法（DEV_PARAM_CONFIG §3.10：Z-Score/Rank/MinMax）",
        enum_options=["zscore", "rank", "minmax"],
    ),
    ParamDef(
        key="factor.ic_type",
        default_value="spearman",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="IC类型（DEV_PARAM_CONFIG §3.3：Spearman/Pearson）",
        enum_options=["spearman", "pearson"],
    ),
    ParamDef(
        key="factor.gate1_ic_threshold",
        default_value=0.02,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Gate1 IC阈值（DEV_PARAM_CONFIG §3.3）",
        min_value=0.0,
        max_value=0.1,
    ),
    ParamDef(
        key="factor.gate1_tstat_threshold",
        default_value=2.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Gate1 t-stat阈值（CLAUDE.md铁律：t>2.5硬性下限，此为初筛软阈值）",
        min_value=1.0,
        max_value=5.0,
    ),
    ParamDef(
        key="factor.gate2_monotonicity_threshold",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Gate2 单调性阈值（DEV_PARAM_CONFIG §3.3）",
        min_value=0.0,
        max_value=1.0,
    ),
    ParamDef(
        key="factor.gate3_correlation_threshold",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Gate3 与已有因子相关性上限（DEV_PARAM_CONFIG §3.3）",
        min_value=0.0,
        max_value=1.0,
    ),
)

# --- 风控扩展参数 (risk) — §3.6 ---
_register(
    ParamDef(
        key="risk.max_single_position",
        default_value=0.08,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="单股最大持仓比例（DEV_PARAM_CONFIG §3.6：3%-15%）",
        min_value=0.03,
        max_value=0.15,
    ),
    ParamDef(
        key="risk.max_industry_concentration",
        default_value=0.25,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="单行业最大持仓比例（DEV_PARAM_CONFIG §3.6：10%-35%）",
        min_value=0.10,
        max_value=0.35,
    ),
    ParamDef(
        key="risk.max_drawdown_l1",
        default_value=-0.08,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L1熔断：单股止损线（RISK_CONTROL_SERVICE_DESIGN L1）",
        min_value=-0.30,
        max_value=-0.01,
    ),
    ParamDef(
        key="risk.max_drawdown_l2",
        default_value=-0.05,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="L2熔断：组合日亏损阈值（RISK_CONTROL_SERVICE_DESIGN L2）",
        min_value=-0.10,
        max_value=-0.01,
    ),
    ParamDef(
        key="risk.single_stock_hard_cap",
        default_value=0.15,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="单股持仓硬上限（L0不可调，DEV_PARAM_CONFIG §3.6）",
        level="L0",
    ),
    ParamDef(
        key="risk.industry_hard_cap",
        default_value=0.35,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="行业持仓硬上限（L0不可调，DEV_PARAM_CONFIG §3.6）",
        level="L0",
    ),
)

# --- 滑点参数 (slippage) — §3.7 + DEV_BACKTEST_ENGINE ---
_register(
    ParamDef(
        key="backtest.slippage_k_large",
        default_value=0.05,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点冲击系数k-大盘（DEV_PARAM_CONFIG §3.12，Bouchaud平方根冲击模型）",
        min_value=0.01,
        max_value=0.3,
    ),
    ParamDef(
        key="backtest.slippage_k_mid",
        default_value=0.10,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点冲击系数k-中盘（DEV_PARAM_CONFIG §3.12）",
        min_value=0.01,
        max_value=0.3,
    ),
    ParamDef(
        key="backtest.slippage_k_small",
        default_value=0.15,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="滑点冲击系数k-小盘（DEV_PARAM_CONFIG §3.12）",
        min_value=0.01,
        max_value=0.3,
    ),
    ParamDef(
        key="backtest.overnight_gap_bps",
        default_value=25.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="隔夜跳空成本（bps，DEV_PARAM_CONFIG §3.12，T+1 open执行价附加成本）",
        min_value=0.0,
        max_value=50.0,
    ),
    ParamDef(
        key="backtest.execution_price",
        default_value="next_open",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="回测执行价（R5 T+1对齐：next_open/next_vwap）",
        enum_options=["next_open", "next_vwap"],
    ),
    ParamDef(
        key="backtest.start_date",
        default_value="2018-01-01",
        param_type=ParamType.STR,
        module=ParamModule.BACKTEST,
        description="回测开始日期（DEV_PARAM_CONFIG §3.7，格式YYYY-MM-DD）",
    ),
    ParamDef(
        key="backtest.rebalance_signal_day",
        default_value="friday",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="周频调仓信号日（DEV_PARAM_CONFIG §3.12）",
        enum_options=["monday", "tuesday", "wednesday", "thursday", "friday"],
    ),
)

# --- AI/ML模型参数 (llm_mining) — §3.8 ---
_register(
    ParamDef(
        key="llm_mining.n_estimators",
        default_value=500,
        param_type=ParamType.INT,
        module=ParamModule.LLM_MINING,
        description="LightGBM n_estimators（DEV_PARAM_CONFIG §3.8）",
        min_value=100,
        max_value=5000,
    ),
    ParamDef(
        key="llm_mining.max_depth",
        default_value=6,
        param_type=ParamType.INT,
        module=ParamModule.LLM_MINING,
        description="LightGBM max_depth（DEV_PARAM_CONFIG §3.8）",
        min_value=3,
        max_value=15,
    ),
    ParamDef(
        key="llm_mining.learning_rate",
        default_value=0.05,
        param_type=ParamType.FLOAT,
        module=ParamModule.LLM_MINING,
        description="LightGBM learning_rate（DEV_PARAM_CONFIG §3.8）",
        min_value=0.001,
        max_value=0.3,
    ),
    ParamDef(
        key="llm_mining.subsample",
        default_value=0.8,
        param_type=ParamType.FLOAT,
        module=ParamModule.LLM_MINING,
        description="LightGBM subsample（DEV_PARAM_CONFIG §3.8）",
        min_value=0.1,
        max_value=1.0,
    ),
    ParamDef(
        key="llm_mining.colsample_bytree",
        default_value=0.8,
        param_type=ParamType.FLOAT,
        module=ParamModule.LLM_MINING,
        description="LightGBM colsample_bytree（DEV_PARAM_CONFIG §3.8）",
        min_value=0.1,
        max_value=1.0,
    ),
    ParamDef(
        key="llm_mining.idea_agent_model",
        default_value="deepseek-reasoner",
        param_type=ParamType.ENUM,
        module=ParamModule.LLM_MINING,
        description="因子Idea Agent模型（DEV_PARAM_CONFIG §3.2）",
        enum_options=["deepseek-reasoner", "deepseek-chat", "gpt-4o", "claude-sonnet-4-6"],
    ),
    ParamDef(
        key="llm_mining.factor_agent_model",
        default_value="deepseek-chat",
        param_type=ParamType.ENUM,
        module=ParamModule.LLM_MINING,
        description="因子代码生成Agent模型（DEV_PARAM_CONFIG §3.2）",
        enum_options=["deepseek-chat", "gpt-4o", "claude-sonnet-4-6"],
    ),
    ParamDef(
        key="llm_mining.idea_temperature",
        default_value=0.8,
        param_type=ParamType.FLOAT,
        module=ParamModule.LLM_MINING,
        description="Idea Agent temperature（DEV_PARAM_CONFIG §3.2）",
        min_value=0.0,
        max_value=1.5,
    ),
    ParamDef(
        key="llm_mining.factor_temperature",
        default_value=0.2,
        param_type=ParamType.FLOAT,
        module=ParamModule.LLM_MINING,
        description="Factor Agent temperature（DEV_PARAM_CONFIG §3.2）",
        min_value=0.0,
        max_value=1.5,
    ),
    ParamDef(
        key="llm_mining.ic_quick_filter_threshold",
        default_value=0.015,
        param_type=ParamType.FLOAT,
        module=ParamModule.LLM_MINING,
        description="IC快速筛选阈值（DEV_PARAM_CONFIG §3.2，低于此值不进入Gate2+）",
        min_value=0.0,
        max_value=0.05,
    ),
)

# --- GP遗传编程扩展参数 (gp_engine) — §3.1 ---
_register(
    ParamDef(
        key="gp_engine.tournament_size",
        default_value=5,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="GP锦标赛选择大小（DEV_PARAM_CONFIG §3.1）",
        min_value=2,
        max_value=10,
    ),
    ParamDef(
        key="gp_engine.max_tree_depth",
        default_value=6,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="GP表达式树最大深度（DEV_PARAM_CONFIG §3.1）",
        min_value=3,
        max_value=10,
    ),
    ParamDef(
        key="gp_engine.max_nodes",
        default_value=30,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="GP表达式树最大节点数（DEV_PARAM_CONFIG §3.1）",
        min_value=10,
        max_value=80,
    ),
    ParamDef(
        key="gp_engine.fitness_ic_weight",
        default_value=1.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="GP适应度-IC权重（DEV_PARAM_CONFIG §3.1）",
        min_value=0.0,
        max_value=5.0,
    ),
    ParamDef(
        key="gp_engine.fitness_ir_weight",
        default_value=1.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="GP适应度-IR权重（DEV_PARAM_CONFIG §3.1）",
        min_value=0.0,
        max_value=5.0,
    ),
    ParamDef(
        key="gp_engine.fitness_originality_weight",
        default_value=1.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="GP适应度-原创性权重（DEV_PARAM_CONFIG §3.1）",
        min_value=0.0,
        max_value=5.0,
    ),
)

# --- 调度扩展参数 (scheduler) — §3.9 ---
_register(
    ParamDef(
        key="scheduler.signal_generate_time",
        default_value="17:10",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="T日信号生成时间（DEV_PARAM_CONFIG §3.9，在数据拉取完成后）",
    ),
    ParamDef(
        key="scheduler.push_deadline_time",
        default_value="17:45",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="T日推送截止时间（DEV_PARAM_CONFIG §3.9）",
    ),
    ParamDef(
        key="scheduler.p1_alert_max_per_day",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.SCHEDULER,
        description="P1告警最大条数/天（DEV_PARAM_CONFIG §3.9）",
        min_value=1,
        max_value=10,
    ),
)

# --- 数据模块 (data) ---
_register(
    ParamDef(
        key="data.tushare_retry_count",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.DATA,
        description="Tushare API失败重试次数",
        min_value=1,
        max_value=10,
    ),
    ParamDef(
        key="data.fallback_to_akshare",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.DATA,
        description="Tushare失败后是否降级到AKShare",
    ),
    # ================================================================
    # F2补全: 以下参数来自 DEV_PARAM_CONFIG.md §3.1-3.14
    # Sprint 1.33 补全 (106→220+)
    # ================================================================

    # ── §3.3 Factor Gate Pipeline 补全 ──
    ParamDef(
        key="factor.gate4_year_stability",
        default_value=4,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="Gate4: 分年稳定性要求(N/5年IC显著)",
        min_value=1, max_value=5,
    ),
    ParamDef(
        key="factor.gate6_bh_fdr_t_hard",
        default_value=2.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Gate6: BH-FDR多重检验t硬性下限(Harvey Liu Zhu 2016)",
        min_value=2.0, max_value=4.0,
    ),
    ParamDef(
        key="factor.gate7_sharpe_baseline",
        default_value=0.91,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="Gate7: SimBroker回测Sharpe基线(volume_impact模式)",
        min_value=0.0, max_value=3.0,
    ),

    # ── §3.6 风控补全 ──
    ParamDef(
        key="risk.forex_single_risk_pct",
        default_value=0.02,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="外汇单笔风险比例",
        min_value=0.005, max_value=0.05,
    ),
    ParamDef(
        key="risk.forex_margin_cap",
        default_value=0.50,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="外汇保证金上限比例",
        min_value=0.20, max_value=0.80,
    ),
    ParamDef(
        key="risk.forex_position_limit",
        default_value=3.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="外汇单品种限仓(手)",
        min_value=0.5, max_value=10.0,
    ),
    ParamDef(
        key="risk.daily_loss_pause_pct",
        default_value=0.05,
        param_type=ParamType.FLOAT,
        module=ParamModule.RISK,
        description="日亏损暂停阈值",
        min_value=0.02, max_value=0.10,
    ),

    # ── §3.7 回测补全 ──
    ParamDef(
        key="backtest.end_date",
        default_value="latest",
        param_type=ParamType.STR,
        module=ParamModule.BACKTEST,
        description="回测结束日期(latest=最新交易日)",
    ),
    ParamDef(
        key="backtest.sell_penalty",
        default_value=1.3,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="卖出惩罚系数(R4研究)",
        min_value=1.0, max_value=2.0,
    ),
    ParamDef(
        key="backtest.sigma_daily",
        default_value=0.02,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="日波动率σ默认值",
        min_value=0.005, max_value=0.05,
    ),
    ParamDef(
        key="backtest.industry_cap",
        default_value=0.30,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="回测单行业持仓上限",
        min_value=0.10, max_value=0.50,
    ),
    ParamDef(
        key="backtest.single_stock_cap",
        default_value=0.05,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="回测单股持仓上限",
        min_value=0.03, max_value=0.15,
    ),
    ParamDef(
        key="backtest.market",
        default_value="a_share",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="回测市场选择",
        enum_options=["a_share", "forex"],
    ),
    ParamDef(
        key="backtest.universe_preset",
        default_value="all_a",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="股票池预设",
        enum_options=["all_a", "csi300", "csi500", "csi1000", "gem", "star", "main_board", "custom"],
    ),
    ParamDef(
        key="backtest.weight_method",
        default_value="equal",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="回测权重方式",
        enum_options=["equal", "score_weighted"],
    ),

    # ── §3.8 AI模型管理 ──
    ParamDef(
        key="ai_agent.hmm_n_states",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="HMM市场状态数",
        min_value=2, max_value=5,
    ),
    ParamDef(
        key="ai_agent.isolation_forest_contamination",
        default_value=0.05,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="IsolationForest异常比例",
        min_value=0.01, max_value=0.30,
    ),
    ParamDef(
        key="ai_agent.isolation_forest_n_estimators",
        default_value=100,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="IsolationForest树数量",
        min_value=50, max_value=500,
    ),
    ParamDef(
        key="ai_agent.model_retrain_freq",
        default_value="monthly",
        param_type=ParamType.ENUM,
        module=ParamModule.AI_AGENT,
        description="模型重训频率",
        enum_options=["weekly", "monthly", "quarterly"],
    ),
    ParamDef(
        key="ai_agent.model_replace_threshold",
        default_value=0.95,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="模型替换阈值(新模型Sharpe/旧模型Sharpe)",
        min_value=0.80, max_value=1.10,
    ),

    # ── §3.10 因子预处理补全 ──
    ParamDef(
        key="factor.fill_method",
        default_value="industry_median",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="因子缺失值填充方法",
        enum_options=["industry_median", "cross_section_median", "zero", "drop"],
    ),
    ParamDef(
        key="factor.neutralize_variables",
        default_value="industry+market_cap",
        param_type=ParamType.ENUM,
        module=ParamModule.FACTOR,
        description="中性化变量组合",
        enum_options=["industry+market_cap", "industry_only", "market_cap_only", "none"],
    ),

    # ── §3.12 回测引擎V2新增 ──
    ParamDef(
        key="backtest.transfer_fee_rate",
        default_value=0.00001,
        param_type=ParamType.FLOAT,
        module=ParamModule.BACKTEST,
        description="过户费率(万0.1)",
        min_value=0.0, max_value=0.0001,
    ),
    ParamDef(
        key="backtest.rebalance_freq",
        default_value="monthly",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="回测调仓频率",
        enum_options=["daily", "weekly", "biweekly", "monthly"],
    ),
    ParamDef(
        key="backtest.top_n",
        default_value=15,
        param_type=ParamType.INT,
        module=ParamModule.BACKTEST,
        description="回测持仓数量",
        min_value=5, max_value=50,
    ),

    # ── §3.12 Walk-Forward参数 ──
    ParamDef(
        key="walk_forward.enabled",
        default_value=False,
        param_type=ParamType.BOOL,
        module=ParamModule.WALK_FORWARD,
        description="Walk-Forward验证启用",
    ),
    ParamDef(
        key="walk_forward.train_months",
        default_value=36,
        param_type=ParamType.INT,
        module=ParamModule.WALK_FORWARD,
        description="WF训练期(月)",
        min_value=12, max_value=60,
    ),
    ParamDef(
        key="walk_forward.validation_months",
        default_value=6,
        param_type=ParamType.INT,
        module=ParamModule.WALK_FORWARD,
        description="WF验证期(月)",
        min_value=3, max_value=12,
    ),
    ParamDef(
        key="walk_forward.test_months",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.WALK_FORWARD,
        description="WF测试期(月)",
        min_value=1, max_value=12,
    ),

    # ── §3.12 市场状态分析参数 ──
    ParamDef(
        key="backtest.regime_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.BACKTEST,
        description="市场状态分析启用",
    ),
    ParamDef(
        key="backtest.regime_method",
        default_value="ma",
        param_type=ParamType.ENUM,
        module=ParamModule.BACKTEST,
        description="市场状态判定方法",
        enum_options=["ma", "drawdown"],
    ),
    ParamDef(
        key="backtest.regime_ma_window",
        default_value=120,
        param_type=ParamType.INT,
        module=ParamModule.BACKTEST,
        description="市场状态均线窗口(天)",
        min_value=60, max_value=240,
    ),

    # ── §3.13 Modifier策略参数 ──
    ParamDef(
        key="modifier.regime_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.MODIFIER,
        description="RegimeModifier启用",
    ),
    ParamDef(
        key="modifier.regime_scale_risk_off",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.MODIFIER,
        description="高波缩放系数(risk_off)",
        min_value=0.3, max_value=1.0,
    ),
    ParamDef(
        key="modifier.regime_vol_baseline",
        default_value="median",
        param_type=ParamType.ENUM,
        module=ParamModule.MODIFIER,
        description="波动率基线方法",
        enum_options=["median", "ma60", "ma120"],
    ),
    ParamDef(
        key="modifier.regime_clip_low",
        default_value=0.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.MODIFIER,
        description="缩放clip下限",
        min_value=0.1, max_value=1.0,
    ),
    ParamDef(
        key="modifier.regime_clip_high",
        default_value=2.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.MODIFIER,
        description="缩放clip上限",
        min_value=1.0, max_value=3.0,
    ),
    ParamDef(
        key="modifier.cash_buffer_pct",
        default_value=0.03,
        param_type=ParamType.FLOAT,
        module=ParamModule.MODIFIER,
        description="CompositeStrategy现金缓冲比例",
        min_value=0.0, max_value=0.10,
    ),
    ParamDef(
        key="modifier.initial_capital",
        default_value=1000000.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.MODIFIER,
        description="CompositeStrategy初始资金(可配置)",
        min_value=100000.0, max_value=100000000.0,
    ),

    # ── §3.13 FactorClassifier参数 ──
    ParamDef(
        key="factor.classifier_fast_threshold",
        default_value=5,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="FactorClassifier快衰减阈值(天)",
        min_value=3, max_value=10,
    ),
    ParamDef(
        key="factor.classifier_standard_threshold",
        default_value=15,
        param_type=ParamType.INT,
        module=ParamModule.FACTOR,
        description="FactorClassifier标准阈值(天)",
        min_value=10, max_value=30,
    ),
    ParamDef(
        key="factor.classifier_confidence_min",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.FACTOR,
        description="分类置信度下限",
        min_value=0.5, max_value=0.9,
    ),

    # ── §3.14 AI闭环Agent 全局控制 ──
    ParamDef(
        key="ai_agent.automation_level",
        default_value="L1",
        param_type=ParamType.ENUM,
        module=ParamModule.AI_AGENT,
        description="AI自动化级别(L0手动/L1半自动/L2自动/L3全自动)",
        enum_options=["L0", "L1", "L2", "L3"],
    ),
    ParamDef(
        key="ai_agent.pipeline_max_loops",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="Pipeline单轮最大循环次数",
        min_value=1, max_value=5,
    ),

    # ── §3.14 因子发现Agent ──
    ParamDef(
        key="ai_agent.discovery_schedule",
        default_value="0 2 * * 1",
        param_type=ParamType.STR,
        module=ParamModule.AI_AGENT,
        description="因子发现调度(cron: 每周一2:00)",
    ),
    ParamDef(
        key="ai_agent.category_saturation_threshold",
        default_value=15,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="类别饱和阈值(达到后切换搜索方向)",
        min_value=5, max_value=30,
    ),
    ParamDef(
        key="ai_agent.ic_decay_urgent_threshold",
        default_value=0.20,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="IC衰退紧急阈值(触发紧急挖掘)",
        min_value=0.10, max_value=0.50,
    ),
    ParamDef(
        key="ai_agent.llm_model_selection",
        default_value="deepseek",
        param_type=ParamType.ENUM,
        module=ParamModule.AI_AGENT,
        description="LLM模型选择",
        enum_options=["deepseek", "qwen3_local"],
    ),
    ParamDef(
        key="ai_agent.llm_temperature",
        default_value=0.8,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="LLM温度(因子发现)",
        min_value=0.0, max_value=1.5,
    ),
    ParamDef(
        key="ai_agent.candidates_per_round",
        default_value=10,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="每轮候选因子数",
        min_value=3, max_value=20,
    ),
    ParamDef(
        key="ai_agent.ic_onboard_threshold",
        default_value=0.02,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="IC入库阈值",
        min_value=0.01, max_value=0.05,
    ),
    ParamDef(
        key="ai_agent.ir_onboard_threshold",
        default_value=0.3,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="IC_IR入库阈值",
        min_value=0.1, max_value=1.0,
    ),
    ParamDef(
        key="ai_agent.correlation_onboard_threshold",
        default_value=0.7,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="相关性入库阈值(低于此值才入库)",
        min_value=0.5, max_value=0.9,
    ),
    ParamDef(
        key="ai_agent.gp_convergence_rounds",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="GP收敛轮数(连续N轮无新因子则切换引擎)",
        min_value=2, max_value=5,
    ),

    # ── §3.14 策略构建Agent ──
    ParamDef(
        key="ai_agent.strategy_schedule",
        default_value="0 3 1 * *",
        param_type=ParamType.STR,
        module=ParamModule.AI_AGENT,
        description="策略构建调度(cron: 每月1日3:00)",
    ),
    ParamDef(
        key="ai_agent.ic_decay_threshold",
        default_value=0.5,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="IC衰退阈值(触发策略重构)",
        min_value=0.3, max_value=0.8,
    ),
    ParamDef(
        key="ai_agent.min_factor_count",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="策略最少因子数",
        min_value=2, max_value=10,
    ),
    ParamDef(
        key="ai_agent.max_factor_count",
        default_value=15,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="策略最多因子数",
        min_value=5, max_value=30,
    ),

    # ── §3.14 诊断优化Agent ──
    ParamDef(
        key="ai_agent.min_annual_return",
        default_value=0.15,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="最低年化收益目标",
        min_value=0.05, max_value=0.30,
    ),
    ParamDef(
        key="ai_agent.max_mdd",
        default_value=0.15,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="最大回撤容忍度",
        min_value=0.05, max_value=0.30,
    ),
    ParamDef(
        key="ai_agent.min_sharpe",
        default_value=1.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.AI_AGENT,
        description="最低Sharpe目标",
        min_value=0.5, max_value=2.0,
    ),
    ParamDef(
        key="ai_agent.diagnosis_schedule",
        default_value="0 4 * * 5",
        param_type=ParamType.STR,
        module=ParamModule.AI_AGENT,
        description="诊断优化调度(cron: 每周五4:00)",
    ),
    ParamDef(
        key="ai_agent.diagnosis_lookback_days",
        default_value=60,
        param_type=ParamType.INT,
        module=ParamModule.AI_AGENT,
        description="诊断回看天数",
        min_value=20, max_value=252,
    ),
    ParamDef(
        key="ai_agent.auto_param_adjust",
        default_value=False,
        param_type=ParamType.BOOL,
        module=ParamModule.AI_AGENT,
        description="诊断后是否自动调参(L3级别)",
    ),

    # ── 通知参数 ──
    ParamDef(
        key="notification.dingtalk_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.NOTIFICATION,
        description="钉钉告警启用",
    ),
    ParamDef(
        key="notification.p0_channels",
        default_value="dingtalk,log",
        param_type=ParamType.STR,
        module=ParamModule.NOTIFICATION,
        description="P0告警渠道(逗号分隔)",
    ),
    ParamDef(
        key="notification.p1_channels",
        default_value="dingtalk,log",
        param_type=ParamType.STR,
        module=ParamModule.NOTIFICATION,
        description="P1告警渠道",
    ),
    ParamDef(
        key="notification.p2_channels",
        default_value="log",
        param_type=ParamType.STR,
        module=ParamModule.NOTIFICATION,
        description="P2告警渠道",
    ),
    ParamDef(
        key="notification.throttle_window_sec",
        default_value=300,
        param_type=ParamType.INT,
        module=ParamModule.NOTIFICATION,
        description="告警节流窗口(秒，同类告警间隔)",
        min_value=60, max_value=3600,
    ),
    ParamDef(
        key="notification.daily_digest_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.NOTIFICATION,
        description="每日汇总报告启用",
    ),
    ParamDef(
        key="notification.daily_digest_time",
        default_value="20:00",
        param_type=ParamType.STR,
        module=ParamModule.NOTIFICATION,
        description="每日汇总发送时间",
    ),

    # ── 监控参数 ──
    ParamDef(
        key="monitor.health_check_interval_sec",
        default_value=300,
        param_type=ParamType.INT,
        module=ParamModule.MONITOR,
        description="健康检查间隔(秒)",
        min_value=60, max_value=3600,
    ),
    ParamDef(
        key="monitor.pt_watchdog_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.MONITOR,
        description="PT心跳监控启用",
    ),
    ParamDef(
        key="monitor.pt_watchdog_timeout_min",
        default_value=30,
        param_type=ParamType.INT,
        module=ParamModule.MONITOR,
        description="PT心跳超时(分钟，超时触发P0)",
        min_value=10, max_value=120,
    ),
    ParamDef(
        key="monitor.db_connection_pool_size",
        default_value=5,
        param_type=ParamType.INT,
        module=ParamModule.MONITOR,
        description="数据库连接池大小",
        min_value=1, max_value=20,
    ),
    ParamDef(
        key="monitor.redis_health_check_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.MONITOR,
        description="Redis健康检查启用",
    ),
    ParamDef(
        key="monitor.disk_usage_warn_pct",
        default_value=80,
        param_type=ParamType.INT,
        module=ParamModule.MONITOR,
        description="磁盘使用率告警阈值(%)",
        min_value=50, max_value=95,
    ),
    ParamDef(
        key="monitor.factor_ic_check_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.MONITOR,
        description="因子IC日检启用",
    ),

    # ── 系统参数 ──
    ParamDef(
        key="system.log_level",
        default_value="INFO",
        param_type=ParamType.ENUM,
        module=ParamModule.SYSTEM,
        description="日志级别",
        enum_options=["DEBUG", "INFO", "WARNING", "ERROR"],
    ),
    ParamDef(
        key="system.log_format",
        default_value="json",
        param_type=ParamType.ENUM,
        module=ParamModule.SYSTEM,
        description="日志格式(json=生产, console=开发)",
        enum_options=["json", "console"],
    ),
    ParamDef(
        key="system.log_max_bytes",
        default_value=10485760,
        param_type=ParamType.INT,
        module=ParamModule.SYSTEM,
        description="单日志文件最大字节(10MB)",
        min_value=1048576, max_value=104857600,
    ),
    ParamDef(
        key="system.log_backup_count",
        default_value=7,
        param_type=ParamType.INT,
        module=ParamModule.SYSTEM,
        description="日志轮转保留数",
        min_value=3, max_value=30,
    ),
    ParamDef(
        key="system.api_cors_origins",
        default_value="http://localhost:5173",
        param_type=ParamType.STR,
        module=ParamModule.SYSTEM,
        description="CORS允许来源(逗号分隔)",
    ),
    ParamDef(
        key="system.api_rate_limit_per_min",
        default_value=120,
        param_type=ParamType.INT,
        module=ParamModule.SYSTEM,
        description="API限流(请求/分钟)",
        min_value=30, max_value=600,
    ),
    ParamDef(
        key="system.backup_retention_days",
        default_value=7,
        param_type=ParamType.INT,
        module=ParamModule.SYSTEM,
        description="数据库备份保留天数",
        min_value=3, max_value=30,
    ),
    ParamDef(
        key="system.backup_monthly_enabled",
        default_value=True,
        param_type=ParamType.BOOL,
        module=ParamModule.SYSTEM,
        description="月度永久备份启用",
    ),
    ParamDef(
        key="system.cache_ttl_sec",
        default_value=300,
        param_type=ParamType.INT,
        module=ParamModule.SYSTEM,
        description="Redis缓存默认TTL(秒)",
        min_value=60, max_value=3600,
    ),
    ParamDef(
        key="system.timezone",
        default_value="Asia/Shanghai",
        param_type=ParamType.STR,
        module=ParamModule.SYSTEM,
        description="系统时区",
    ),

    # ── GP引擎补全 ──
    ParamDef(
        key="gp_engine.n_islands",
        default_value=2,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="岛屿模型子种群数",
        min_value=1, max_value=8,
    ),
    ParamDef(
        key="gp_engine.migration_interval",
        default_value=5,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="岛屿迁移间隔(代)",
        min_value=3, max_value=20,
    ),
    ParamDef(
        key="gp_engine.migration_size",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.GP_ENGINE,
        description="每次迁移个体数",
        min_value=1, max_value=10,
    ),
    ParamDef(
        key="gp_engine.seed_ratio",
        default_value=0.8,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="Warm Start种子比例",
        min_value=0.0, max_value=1.0,
    ),
    ParamDef(
        key="gp_engine.complexity_penalty",
        default_value=0.1,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="适应度-复杂度惩罚系数",
        min_value=0.0, max_value=0.5,
    ),
    ParamDef(
        key="gp_engine.novelty_weight",
        default_value=0.3,
        param_type=ParamType.FLOAT,
        module=ParamModule.GP_ENGINE,
        description="适应度-新颖性权重",
        min_value=0.0, max_value=1.0,
    ),

    # ── LLM Mining补全 ──
    ParamDef(
        key="llm_mining.code_retry_count",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.LLM_MINING,
        description="代码生成重试次数",
        min_value=0, max_value=5,
    ),
    ParamDef(
        key="llm_mining.hypotheses_per_round",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.LLM_MINING,
        description="每轮假设数量",
        min_value=1, max_value=10,
    ),
    ParamDef(
        key="llm_mining.max_tokens",
        default_value=4096,
        param_type=ParamType.INT,
        module=ParamModule.LLM_MINING,
        description="LLM最大token数",
        min_value=512, max_value=8192,
    ),

    # ── 调度补全 ──
    ParamDef(
        key="scheduler.gp_schedule",
        default_value="0 2 * * 6",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="GP挖掘调度(cron: 每周六2:00)",
    ),
    ParamDef(
        key="scheduler.factor_health_time",
        default_value="17:30",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="因子健康日报时间",
    ),
    ParamDef(
        key="scheduler.backup_time",
        default_value="02:00",
        param_type=ParamType.STR,
        module=ParamModule.SCHEDULER,
        description="数据库备份时间",
    ),
    ParamDef(
        key="scheduler.task_timeout_sec",
        default_value=3600,
        param_type=ParamType.INT,
        module=ParamModule.SCHEDULER,
        description="调度任务超时(秒)",
        min_value=300, max_value=7200,
    ),

    # ── Universe补全 ──
    ParamDef(
        key="universe.include_boards",
        default_value="main,gem,star",
        param_type=ParamType.STR,
        module=ParamModule.UNIVERSE,
        description="包含板块(main=主板,gem=创业板,star=科创板,bse=北交所)",
    ),
    ParamDef(
        key="universe.max_pe_ratio",
        default_value=200.0,
        param_type=ParamType.FLOAT,
        module=ParamModule.UNIVERSE,
        description="PE上限(排除极端估值)",
        min_value=50.0, max_value=500.0,
    ),

    # ── Execution补全 ──
    ParamDef(
        key="execution.qmt_path",
        default_value="D:\\国金QMT交易端模拟\\userdata_mini",
        param_type=ParamType.STR,
        module=ParamModule.EXECUTION,
        description="miniQMT安装路径",
    ),
    ParamDef(
        key="execution.account_id",
        default_value="81001102",
        param_type=ParamType.STR,
        module=ParamModule.EXECUTION,
        description="QMT账户ID",
    ),
    ParamDef(
        key="execution.order_timeout_sec",
        default_value=300,
        param_type=ParamType.INT,
        module=ParamModule.EXECUTION,
        description="下单超时(秒)",
        min_value=60, max_value=600,
    ),
    ParamDef(
        key="execution.max_retry",
        default_value=3,
        param_type=ParamType.INT,
        module=ParamModule.EXECUTION,
        description="下单最大重试次数",
        min_value=0, max_value=5,
    ),

    # ── Data补全 ──
    ParamDef(
        key="data.tushare_token",
        default_value="",
        param_type=ParamType.STR,
        module=ParamModule.DATA,
        description="Tushare API token(从环境变量读取)",
    ),
    ParamDef(
        key="data.daily_pull_start_time",
        default_value="16:30",
        param_type=ParamType.STR,
        module=ParamModule.DATA,
        description="每日数据拉取开始时间",
    ),
    ParamDef(
        key="data.adj_factor_method",
        default_value="qfq",
        param_type=ParamType.ENUM,
        module=ParamModule.DATA,
        description="复权方式",
        enum_options=["qfq", "hfq", "none"],
    ),
    ParamDef(
        key="data.index_codes",
        default_value="000300.SH,000905.SH,000852.SH",
        param_type=ParamType.STR,
        module=ParamModule.DATA,
        description="需拉取的指数代码(逗号分隔)",
    ),

    # ── Paper Trading补全 ──
    ParamDef(
        key="paper_trading.signal_time",
        default_value="17:20",
        param_type=ParamType.STR,
        module=ParamModule.PAPER_TRADING,
        description="PT信号生成时间",
    ),
    ParamDef(
        key="paper_trading.execution_time",
        default_value="09:30",
        param_type=ParamType.STR,
        module=ParamModule.PAPER_TRADING,
        description="PT执行时间(T+1开盘)",
    ),
    ParamDef(
        key="paper_trading.watchdog_time",
        default_value="20:00",
        param_type=ParamType.STR,
        module=ParamModule.PAPER_TRADING,
        description="PT心跳监控时间",
    ),
)


def get_param_def(key: str) -> ParamDef | None:
    """获取参数定义。

    Args:
        key: 参数唯一标识。

    Returns:
        参数定义，不存在时返回None。
    """
    return PARAM_DEFINITIONS.get(key)


def get_all_param_defs(module: str | None = None) -> dict[str, ParamDef]:
    """获取全部参数定义（可按模块过滤）。

    Args:
        module: 模块名，为None时返回全部。

    Returns:
        参数key→定义的字典。
    """
    if module is None:
        return dict(PARAM_DEFINITIONS)
    return {k: v for k, v in PARAM_DEFINITIONS.items() if v.module.value == module}


def get_modules() -> list[str]:
    """获取所有模块名列表。"""
    return sorted({p.module.value for p in PARAM_DEFINITIONS.values()})
