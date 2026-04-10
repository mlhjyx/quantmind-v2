> **⚠️ 文档状态: PARTIALLY_IMPLEMENTED (2026-04-10)**
> 实现状态: ~25% — Step 4-A 完成8模块拆分，Hybrid 架构已实现。Step 2(向量化)/Step 3(Rust加速)未启动。
> 仍有价值: §3 Hybrid架构设计、§4 接口定义、SignalComposer 已实现部分
> 已过时/被替代: 性能优化路径(Rust/向量化)未启动，OOM 问题未在原设计中预见
> 参考: docs/QUANTMIND_FACTOR_UPGRADE_PLAN_V3.md

# QuantMind V2 — 回测引擎详细开发文档

> 文档级别：实现级（供 Claude Code 执行）
> 创建日期：2026-03-19
> 最后更新: 2026-04-09 (Step 4-A + Step 4-B + Step 5)
> 关联文档：QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md §第四部分、DEV_FACTOR_MINING.md、DEV_PARAM_CONFIG.md、DEV_AI_EVOLUTION.md、DEV_BACKEND.md

---

## §0 Step 4-A 模块拆分 (2026-04-09, 优先阅读)

> 本节描述重构后的**实际代码结构**, 优先级高于下方的 §三 / §四 的历史设计描述。
> 历史章节保留作为决策记录和接口契约来源。

### 拆分动机

原 `backend/engines/backtest_engine.py` 单文件 >3000 行, 融合事件循环/broker 成本/校验器/数据结构/config 多重职责:
- SRP 严重违反, 单元测试困难 (无法只测 broker 不连带 engine 初始化)
- import 圆环 (engine ↔ broker ↔ executor)
- 研究脚本 import 整个 3000 行模块, 启动开销大

### 拆分后的 8 模块

```
backend/engines/backtest/
├── __init__.py          (18 行, 只导出公开符号)
├── engine.py            (562 行) — BacktestEngine 核心事件循环
├── broker.py            (309 行) — SimBroker + 三因素成本模型
├── runner.py            (281 行) — run_hybrid_backtest() / run_composite_backtest() 公开入口
├── validators.py        (105 行) — ValidatorChain (涨跌停/停牌/完整性)
├── types.py             ( 92 行) — BacktestResult / Fill / Order / Trade dataclass
├── executor.py          ( 81 行) — 事件执行器 (把 signal 转为 order)
└── config.py            ( 49 行) — BacktestConfig dataclass
```

### 依赖关系

```
runner.py
  ├─ config.py (BacktestConfig)
  ├─ engine.py
  │   ├─ broker.py (SimBroker)
  │   │   └─ types.py (Fill/Order)
  │   ├─ validators.py (ValidatorChain)
  │   ├─ executor.py
  │   └─ types.py (BacktestResult)
  └─ types.py (BacktestResult)
```

规则:
- `runner.py` 是唯一公开入口, 外部代码只 import runner 中的函数 (run_hybrid_backtest, run_composite_backtest)
- `types.py` 是叶节点, 不依赖其他子模块
- `config.py` 只依赖标准库
- `engine.py` / `broker.py` / `validators.py` / `executor.py` 相互独立, 可单测

### 公开入口 (兼容性)

外部代码的 import 保持不变:

```python
# 老代码 (保留, 通过 backend/engines/backtest_engine.py 顶层 shim 或直接迁移)
from backend.engines.backtest_engine import run_hybrid_backtest, BacktestConfig

# 新代码 (推荐)
from backend.engines.backtest.runner import run_hybrid_backtest
from backend.engines.backtest.config import BacktestConfig
```

研究脚本 (scripts/research/*.py) 只用公开入口, 不受影响。

### 数据层: Step 5 新增

```
backend/data/
└── parquet_cache.py     (233 行) — BacktestDataCache 按年分区 Parquet 缓存
```

`BacktestDataCache.build(start, end, conn)` 按年导出:
```
cache/backtest/2014/price_data.parquet
cache/backtest/2014/factor_data.parquet
cache/backtest/2014/benchmark.parquet
cache/backtest/2015/...
...
cache/backtest/cache_meta.json  (build_date, row_counts, git_commit)
```

`BacktestDataCache.load(start, end)` 只读取需要的年份。加载速度从 30 分钟 (DB) 降到 20 秒 (Parquet) — ~90x 加速。
run_backtest.py 先查 cache, 没有再回退到 DB。

### Step 4-B 配置加载

```
backend/app/services/config_loader.py  (147 行)
configs/
├── pt_live.yaml                       — PT生产配置 (5因子等权Top-20月度+PMS)
├── backtest_12yr.yaml                 — 12年基线回测 (2014-2025)
└── backtest_5yr.yaml                  — 5年回测 (历史比对)
```

`load_strategy_config(yaml_path) → (BacktestConfig, SignalConfig, config_hash)`:
- 读 YAML 文件
- 映射到 BacktestConfig (成本/滑点/窗口等)
- 映射到 SignalConfig (因子列表/方向/Top-N/行业约束)
- 计算 sha256(yaml_text) 作为可复现指纹
- 指纹写入 backtest_run.config_yaml_hash (铁律 15)

CLI 入口:
```bash
python scripts/run_backtest.py --config configs/pt_live.yaml
```

### 测试覆盖 (Step 5 新增 48 测试)

- `test_validators.py` (8): price_limit 板块 / suspension / data_completeness / 封板
- `test_broker_costs.py` (8): commission min5元 / 印花税历史税率 / 过户费 / lot_size 100 股 / buy/sell 更新 holdings+cash
- `test_pms.py` (6): 阈值/L1/L3 触发 / adj_close 除权日不误触发 / T+1 延迟卖出 / disabled
- `test_config_loader.py` (6): YAML 加载 / BacktestConfig 映射 / SignalConfig 映射 / directions 提取 / hash 确定性 / 缺失文件报错
- `test_engine_e2e.py` (4): 5yr Parquet 基准匹配 / 确定性 / 空 factor raise / 单月回测

### 基线数据 (12 年)

- 5 年回测 (Phase 1 加固后): Sharpe=0.94, MDD=-40.77%
- **5 年回测 (Step 5 基线): Sharpe=0.6095, MDD=-50.75%, 耗时 80s** (注: 0.6095是5年非12年, 12年真实Sharpe=0.5309, Step 6-D首跑)
- `cache/baseline/regression_result.json` 存基准, max_diff=0 验证可复现
- `python scripts/regression_test.py` 做基准比对

### 铁律落地 (Step 6-B)

| 铁律 | 落地点 |
|------|-------|
| 14 (引擎不做数据清洗) | backend/engines/backtest/engine.py 不做 ST 推断/单位猜测, 只用 DataFeed 提供的数据 |
| 15 (结果可复现) | backtest_run.config_yaml_hash + git_commit 列, regression_test.py max_diff=0 |
| 16 (信号路径唯一) | runner.py 调用 SignalComposer.compose(), 不再有 vectorized_signal 独立链路 |
| 17 (DataPipeline 入库) | 回测引擎不入库, 只消费 DataFeed; DataFeed 的数据来源必须经 DataPipeline |

---

## 一、概述

回测引擎是 QuantMind V2 的核心基础设施，负责将因子信号转化为模拟交易，验证策略有效性。本文档覆盖：

- 后端引擎架构（Hybrid 模式）
- 前端交互页面（5 个页面）
- 数据库表结构（6 张新表）
- 全部已确认决策（34 项）
- 三步渐进实现计划

---

## 二、已确认决策汇总（34 项）

### 2.1 后端引擎决策（17 项）

| # | 决策项 | 选择 | 备注 |
|---|--------|------|------|
| 1 | 架构模式 | Hybrid（向量化信号 + 事件驱动执行） | 速度 + 真实性兼顾 |
| 2 | 成交价 | 次日开盘（默认）+ VWAP（可选），可配置 | T+1 天然匹配 |
| 3 | 滑点模型 | Volume-impact 双因素（市值分层 + 换手率调整）+ 固定 fallback | 6 参数可配置 |
| 4 | 交易成本 | 佣金万 1.5 + 印花税 0.05% + 过户费 0.001% | volume_impact模型(市值分层k) + overnight_gap + tiered_base，详见R4研究 |
| 5 | 实现节奏 | 三步渐进：Step1 信号验证→Step2 执行模拟→Step3 WF | 累积式构建不重写 |
| 6 | WF 窗口 | 36+6+3+3（可配置） | 训练/验证/测试/步长（月） |
| 7 | 结果存储 | PostgreSQL 6 张新表 | 暂不分区 |
| 8 | Forward return | 同时计算 1/5/10/20 日 | 全面对比因子衰减 |
| 9 | 因子预处理 | MAD 去极值→zscore 标准化→市值+行业中性化 | 完整三步 |
| 10 | 未成交资金 | 现金持有（默认）+ 按比例分配/替补可配置 | 三种策略 |
| 11 | 停牌复牌 | 复牌首日按开盘价立即卖出（如不在目标池） | — |
| 12 | 涨跌停判断 | 数据源标记字段优先→涨跌停价比对→涨幅近似（三级 fallback） | 需验证数据源 |
| 13 | 基准指数 | 沪深 300 默认，可配置 500/1000 | — |
| 14 | 超额收益 | 对数收益相减 | ln(1+r_s) - ln(1+r_b) |
| 15 | 调仓日历 | 可配置，默认周五信号 + 下周一执行 | 基于交易日序列 |
| 16 | 做空 | Step 1-3 不支持，Phase 2 外汇再加 | assert 限死 |
| 17 | 滑点 k 系数 | 按市值分层(0.05/0.10/0.15) + 换手率调整(power=-0.5) | clip(0.5, 3.0) |

### 2.2 前端/交互决策（11 项）

| # | 决策项 | 选择 | 备注 |
|---|--------|------|------|
| 18 | 股票池 | 8 种预设(全 A/300/500/1000/创业板/科创板/行业/自定义) | — |
| 19 | 涨跌停幅度 | 按板块自动判定(主板 10%/创业板科创板 20%/ST 5%) | — |
| 20 | 市场状态分析 | 默认启用，均线法(MA120)判定牛/熊/震荡 | — |
| 21 | 时间段 | 支持快捷选择 + 排除特殊时期 + 自定义 | — |
| 22 | 多市场预留 | market 字段预留，Phase 2 外汇激活 | — |
| 23 | 结果页补充 | 新增参数敏感性 Tab + 实盘对比 Tab | — |
| 24 | 策略编辑模式 | 可视化与代码并重，可自由切换 | — |
| 25 | AI 助手范围 | 全功能（生成策略 + 优化 + 解释 + 诊断） | — |
| 26 | 策略对比 | 支持勾选 2 个策略进入双栏对比视图 | — |
| 27 | 配置模板 | 支持保存/加载常用配置组合 | — |
| 28 | 回测运行监控 | WebSocket 推送进度 + 实时净值曲线 | 复用已有 WS 架构 |

### 2.3 AI 闭环相关决策（6 项）

| # | 决策项 | 选择 | 备注 |
|---|--------|------|------|
| 29 | AI 闭环架构 | 三层(Agent 层→编排层→执行层) | 详见 DEV_AI闭环文档 |
| 30 | Agent 数量 | 4 个(因子发现/策略构建/诊断优化/风控监督) | 详见 DEV_AI闭环文档 |
| 31 | 自动化级别 | 4 级(L0 全手动~L3 全自动)，默认 L1 半自动 | 详见 DEV_AI闭环文档 |
| 32 | Agent 决策可审计 | 全部决策写入 agent_decision_log 表 | 详见 DEV_AI闭环文档 |
| 33 | 审批机制 | approval_queue 表，L1 需人批入库+部署 | 详见 DEV_AI闭环文档 |
| 34 | 闭环调度频率 | 因子发现周频/策略优化月频/体检双周/诊断周报 | 详见 DEV_AI闭环文档 |

---

## 三、后端架构

### 3.1 Hybrid 架构数据流

```
Phase A: 向量化层（批量，快）
─────────────────────────────────────
日线数据(DataFrame)
  → 因子计算(34 个因子，全向量化)
  → 因子预处理(MAD→zscore→中性化)
  → 因子合成(加权/ML)
  → 排序打分
  → 目标持仓生成(top-N 股票 + 目标权重)

Phase B: 事件驱动层（逐日，精确）
─────────────────────────────────────
逐交易日循环:
  Day T 收盘后:
    ├─ 读取目标持仓(来自 Phase A)
    ├─ 对比当前持仓 → 生成订单(买入/卖出清单)
    ├─ 卖出约束检查: T+1 / 跌停拒单 / 停牌冻结
    ├─ 卖出执行 → 资金回笼
    ├─ 买入约束检查: 涨停拒单 / 成交量约束 / 资金充足性
    ├─ 买入执行(滑点 + 交易成本扣除)
    ├─ 持仓更新 + 现金更新
    └─ 记录: 交易明细、每日净值、持仓快照
```

### 3.2 前后端完整交互流

```
前端 ─────────────────────────────────────────── 后端

① 策略工作台
   用户选因子/写代码/AI 辅助
   ↓ 保存策略 (POST /api/strategy)
② 配置面板
   用户选股票池/时间段/调参数
   ↓ POST /api/backtest/run
③ 运行监控 ←── WS 推送进度 ←── Celery Worker
   ↓ 完成                        ├── Phase A: 向量化信号层
④ 结果分析 ←── API 拉取结果 ←──   ├── Phase B: 事件驱动执行层
   ↓ 满意                        └── 结果写入 PG 6 张表
   [部署到模拟盘]
```

### 3.3 目录结构

```
quantmind_v2/
├── config/
│   ├── __init__.py
│   ├── settings.py              # 全局配置（DB 连接、路径等）
│   └── backtest_config.py       # BacktestConfig + CostConfig + SlippageConfig
│
├── data/
│   ├── __init__.py
│   ├── datafeed.py              # DataFeed: 从 PG 加载日线→DataFrame
│   ├── universe.py              # UniverseFilter: 8 层过滤
│   └── calendar.py              # TradingCalendar: 交易日历工具
│
├── factors/
│   ├── __init__.py
│   ├── registry.py              # FactorRegistry: 因子注册中心
│   ├── base.py                  # BaseFactor 抽象基类
│   ├── price_volume.py          # 价量因子(12 个)
│   ├── liquidity.py             # 流动性因子(6 个)
│   ├── money_flow.py            # 资金流因子(6 个)
│   ├── fundamental.py           # 基本面因子(8 个)
│   ├── size.py                  # 市值因子(1 个)
│   ├── industry.py              # 行业因子(1 个)
│   ├── tools.py                 # 工具函数库: ts_mean, ts_std, cs_rank 等
│   └── preprocess.py            # 因子预处理: MAD 去极值 / zscore / 中性化
│
├── signal/
│   ├── __init__.py
│   ├── composer.py              # SignalComposer: 因子合成→综合得分
│   └── portfolio_builder.py     # PortfolioBuilder: 得分→目标持仓
│
├── backtest/
│   ├── __init__.py
│   ├── protocol.py              # IBacktester Protocol 定义
│   ├── simple_backtester.py     # Step 1: 简化回测器
│   ├── execution_simulator.py   # Step 2: 完整执行模拟器
│   ├── constraint_checker.py    # 执行约束检查器(T+1/涨跌停/停牌/成交量)
│   ├── cost_model.py            # CostModel: 交易成本计算
│   ├── slippage_model.py        # SlippageModel: 双因素滑点计算
│   ├── portfolio_tracker.py     # PortfolioTracker: 持仓/现金/净值跟踪
│   └── walk_forward.py          # Step 3: Walk-Forward 引擎
│
├── analysis/
│   ├── __init__.py
│   ├── performance.py           # PerformanceAnalyzer: 绩效指标
│   ├── factor_analysis.py       # 单因子 IC/IR/分组收益分析
│   ├── sensitivity.py           # 参数敏感性分析
│   ├── regime.py                # 市场状态分析(牛/熊/震荡)
│   └── report.py                # 生成分析报告
│
├── utils/
│   ├── __init__.py
│   ├── logger.py
│   └── validators.py            # 数据一致性验证工具
│
├── tests/
│   ├── test_datafeed.py
│   ├── test_universe.py
│   ├── test_factors.py
│   ├── test_simple_backtest.py
│   ├── test_execution.py
│   ├── test_cost_model.py
│   ├── test_slippage.py
│   ├── test_constraint_checker.py
│   └── test_determinism.py      # 确定性验证: 同参数跑两次结果一致
│
└── run_step1.py                 # Step 1 入口(开发调试用，生产走 API)
```

---

## 四、核心类接口定义

### 4.1 配置体系

```python
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

@dataclass
class SlippageConfig:
    """双因素滑点配置"""
    # 基础系数(按市值分层)
    k_large: float = 0.05       # 500 亿+ 大盘
    k_mid: float = 0.10         # 100-500 亿 中盘
    k_small: float = 0.15       # 100 亿以下 小盘

    # 换手率调整
    turnover_ref: float = 0.02   # 参考换手率(2%)
    turnover_power: float = -0.5 # 调整幂次

    # 固定滑点 fallback（已废弃，默认使用volume_impact模式）
    fixed_slippage_bps: float = 10.0

    # Sprint 1.11+ 新增参数（R4研究成果）
    overnight_gap_bps: float = 25.0       # 隔夜跳空成本(bps)，PT实测20-30bps为主要成本
    sigma_daily: float = 0.02             # 日波动率σ，用于Bouchaud平方根模型
    sell_penalty: float = 1.3             # 卖出方向惩罚系数（R4建议从1.2→1.3）


@dataclass
class CostConfig:
    """交易成本配置"""
    # Step 1: 固定估算（已升级为volume_impact，保留向后兼容）
    estimated_cost_bps: float = 10.0      # 已废弃，仅fallback用

    # Step 2+: 精确模型
    commission_rate: float = 0.00015      # 佣金万 1.5（单边）
    commission_min: float = 5.0           # 最低佣金 5 元
    stamp_tax_rate: float = 0.0005        # 印花税 0.05%（卖出）
    transfer_fee_rate: float = 0.00001    # 过户费 0.001%（双向）

    # 滑点
    slippage_mode: str = 'volume_impact'  # 'volume_impact' | 'fixed'
    slippage: SlippageConfig = field(default_factory=SlippageConfig)
    volume_cap_pct: float = 0.10          # 单日成交量上限 10%


@dataclass
class MarketRegimeConfig:
    """市场状态判定参数"""
    enabled: bool = True
    method: str = 'ma'              # 'ma' | 'drawdown' | 'manual'
    ma_window: int = 120            # 均线法窗口(交易日)
    bull_threshold: float = 0.20    # 回撤法: 从低点涨 20%+
    bear_threshold: float = -0.20   # 回撤法: 从高点跌 20%+


@dataclass
class BacktestConfig:
    """回测主配置"""
    # === 市场/股票池 ===
    market: str = 'a_share'                       # 'a_share' | 'forex'(Phase 2)
    universe_preset: str = 'all_a'                # 'all_a'|'hs300'|'csi500'|'csi1000'|'gem'|'star'|'industry'|'custom'
    universe_industries: Optional[List[str]] = None
    universe_custom_codes: Optional[List[str]] = None

    # === 时间段 ===
    start_date: str = '2018-01-01'
    end_date: str = '2025-12-31'
    exclude_periods: Optional[List[Tuple[str, str]]] = None  # 排除时段

    # === 基本参数 ===
    initial_capital: float = 1_000_000
    benchmark: str = '000300'                     # 沪深 300

    # === 执行参数 ===
    exec_price: str = 'next_open'                 # 'next_open' | 'next_vwap'
    rebalance_freq: str = 'weekly'                # 'daily'|'weekly'|'biweekly'|'monthly'
    rebalance_weekday: int = 4                    # 信号生成日: 周五(0=周一)
    holding_count: int = 30
    weight_method: str = 'equal'                  # 'equal' | 'score_weighted'

    # === 成本 ===
    cost: CostConfig = field(default_factory=CostConfig)

    # === 风控 ===
    industry_cap_pct: float = 0.30                # 单行业上限 30%
    single_stock_cap_pct: float = 0.05            # 单股上限 5%
    unfilled_handling: str = 'cash'               # 'cash' | 'redistribute' | 'substitute'

    # === 市场状态分析 ===
    regime: MarketRegimeConfig = field(default_factory=MarketRegimeConfig)

    # === Walk-Forward ===
    wf_enabled: bool = False
    wf_train_months: int = 36
    wf_valid_months: int = 6
    wf_test_months: int = 3
    wf_step_months: int = 3
```

### 4.2 DataFeed（数据馈送）

```python
class DataFeed:
    """从 PostgreSQL 加载日线数据，构建统一 DataFrame"""

    def __init__(self, db_engine):
        self.engine = db_engine

    def load(self, start_date: str, end_date: str,
             stock_codes: List[str] = None) -> pd.DataFrame:
        """
        返回: MultiIndex DataFrame
            index: (date, stock_code)
            columns: open, high, low, close, volume, amount,
                     adj_factor, turnover, total_mv, circ_mv,
                     industry_code, is_st, is_suspended,
                     limit_up, limit_down
        关键:
        - 一次 SQL 加载全部数据到内存(预计 ~2GB for 全 A 股 8 年)
        - 使用后复权价格(close * adj_factor)
        - 涨跌停三级 fallback:
          1. 数据源 limit_up/limit_down 布尔字段
          2. 数据源涨跌停价格 → close == up_limit
          3. 自行计算(前收盘 × 板块涨跌幅)
        """
        pass

    def get_trade_dates(self, start: str, end: str) -> List[str]:
        """获取区间内交易日列表"""
        pass

    def get_next_trade_date(self, date: str) -> str:
        """获取下一个交易日"""
        pass
```

### 4.3 UniverseFilter（股票池 8 层过滤）

```python
class UniverseFilter:
    """
    逐日构建可交易股票池。
    流程: 用户选择初始池(预设/自定义) → 8 层过滤 → 每日可交易列表

    8 层过滤:
      1. 剔除 ST/*ST
      2. 剔除上市不满 60 日(次新股)
      3. 剔除停牌
      4. 剔除当日涨跌停(涨停不可买, 跌停不可卖)
      5. 剔除日均成交额 < 500 万(过去 20 日)
      6. 剔除总市值 < 10 亿(微盘股)
      7. 剔除北交所(仅保留沪深主板 + 创业板 + 科创板)
      8. 剔除退市风险警示股

    预设股票池:
      all_a      — 全 A 股(~5000→过滤后 ~3000)
      hs300      — 沪深 300 成分股
      csi500     — 中证 500 成分股
      csi1000    — 中证 1000 成分股
      gem        — 创业板(300/301 开头)
      star       — 科创板(688 开头)
      industry   — 按申万一级行业筛选
      custom     — 用户自定义代码列表
    """

    def __init__(self, config: BacktestConfig):
        self.preset = config.universe_preset
        self.industries = config.universe_industries
        self.custom_codes = config.universe_custom_codes

    def get_initial_pool(self, date: str, df: pd.DataFrame) -> pd.Index:
        """获取初始池(预设筛选，在 8 层过滤之前)"""
        pass

    def filter(self, date: str, df: pd.DataFrame,
               purpose: str = 'buy') -> pd.Index:
        """
        返回: 该日可交易的 stock_code 列表
        purpose: 'buy'(涨停不可买) | 'sell'(跌停不可卖) | 'hold'(无方向过滤)
        """
        pass
```

### 4.4 涨跌停幅度判定

```python
def get_limit_pct(stock_code: str, is_st: bool) -> float:
    """获取个股涨跌停幅度(按板块自动判定)"""
    if is_st:
        return 0.05                                       # ST 股 ±5%
    elif stock_code.startswith('688'):
        return 0.20                                       # 科创板 ±20%
    elif stock_code.startswith(('300', '301')):
        return 0.20                                       # 创业板 ±20%(2020.8 注册制后)
    else:
        return 0.10                                       # 主板 ±10%
```

### 4.5 BaseFactor + FactorRegistry

```python
from abc import ABC, abstractmethod

class BaseFactor(ABC):
    """所有因子的抽象基类"""
    name: str            # 因子名, 如 'momentum_20d'
    category: str        # 类别: price_volume/liquidity/money_flow/fundamental/size/industry
    direction: int       # 1=正向(越大越好), -1=反向(越小越好)
    lookback_days: int   # 所需历史数据天数
    description: str     # 因子含义描述

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """
        输入: MultiIndex DataFrame (date × stock_code)
        输出: Series, index=(date, stock_code), values=因子值
        要求: 全向量化, 禁止逐行循环
        """
        pass


class FactorRegistry:
    """因子注册中心"""
    _factors: Dict[str, BaseFactor] = {}

    @classmethod
    def register(cls, factor: BaseFactor):
        cls._factors[factor.name] = factor

    @classmethod
    def compute_all(cls, df: pd.DataFrame) -> pd.DataFrame:
        """批量计算所有已注册因子"""
        pass

    @classmethod
    def get_by_category(cls, category: str) -> List[BaseFactor]:
        pass

    @classmethod
    def list_all(cls) -> List[str]:
        pass
```

### 4.6 因子预处理

```python
class FactorPreprocessor:
    """
    因子预处理流程（每日横截面处理）:
      1. MAD 去极值: 中位数 ± 5 × MAD
      2. zscore 标准化: (x - mean) / std
      3. 市值 + 行业中性化: 对 ln(市值) + 行业哑变量做回归, 取残差
    """

    def process(self, factor_values: pd.Series, 
                market_cap: pd.Series,
                industry: pd.Series) -> pd.Series:
        """
        输入: 原始因子值 Series (date × stock_code)
        输出: 预处理后因子值 Series
        """
        result = self._mad_winsorize(factor_values)
        result = self._zscore(result)
        result = self._neutralize(result, market_cap, industry)
        return result

    def _mad_winsorize(self, s: pd.Series, n: float = 5.0) -> pd.Series:
        """MAD 去极值(每日横截面)"""
        pass

    def _zscore(self, s: pd.Series) -> pd.Series:
        """zscore 标准化(每日横截面)"""
        pass

    def _neutralize(self, s: pd.Series,
                    market_cap: pd.Series,
                    industry: pd.Series) -> pd.Series:
        """市值 + 行业中性化(每日横截面回归取残差)"""
        pass
```

### 4.7 SignalComposer + PortfolioBuilder

```python
class SignalComposer:
    """因子合成: 多因子→综合得分"""

    def __init__(self, method: str = 'equal_weight'):
        """
        method:
          'equal_weight' — 等权(Step 1 默认)
          'ic_weight'    — IC 加权(用过去 N 日 IC 均值)
          'ml'           — ML 模型(Step 2+)
        """
        self.method = method

    def compose(self, factor_df: pd.DataFrame,
                factor_names: List[str],
                weights: Dict[str, float] = None) -> pd.Series:
        """
        流程:
          1. 每个因子按 direction 调整方向(direction=-1 的取负)
          2. 横截面标准化(每日 zscore)
          3. 按权重加权求和
        """
        pass


class PortfolioBuilder:
    """得分→目标持仓"""

    def build(self, scores: pd.Series, date: str,
              universe: pd.Index, config: BacktestConfig) -> Dict[str, float]:
        """
        流程:
          1. 取 universe 内的得分
          2. 排序取 top-N (config.holding_count)
          3. 按 weight_method 分配权重
          4. 行业约束裁剪(单行业 <= 30%)
          5. 单股约束裁剪(单股 <= 5%)
          6. 权重归一化
        输出: {stock_code: target_weight}
        """
        pass
```

### 4.8 IBacktester Protocol + SimpleBacktester

```python
from typing import Protocol

class IBacktester(Protocol):
    """统一回测接口 — Step 1/2 共享"""
    def run(self, config: BacktestConfig,
            target_portfolios: Dict[str, Dict[str, float]],
            data: pd.DataFrame) -> 'BacktestResult':
        ...


@dataclass
class BacktestResult:
    """回测结果容器"""
    daily_nav: pd.Series                # 日期→净值
    daily_returns: pd.Series            # 日期→日收益率
    benchmark_nav: pd.Series            # 基准净值
    benchmark_returns: pd.Series        # 基准日收益率
    excess_returns: pd.Series           # 超额收益(对数相减)
    trades: pd.DataFrame                # 交易记录
    holdings: Dict[str, pd.DataFrame]   # 每个调仓日的持仓快照
    turnover_series: pd.Series          # 每次调仓的换手率
    config: BacktestConfig              # 回测配置快照


class SimpleBacktester:
    """
    Step 1 简化回测器 — 快速验证因子信号

    简化点(vs Step 2):
      - 不模拟 T+1(假设都能成交)
      - 不检查涨跌停拒单(Universe 已过滤)
      - 不检查成交量约束
      - 简化成本估算(volume_impact模型，参见R4: docs/research/R4_A股微观结构特性.md)
      - 不模拟停牌冻结

    保留的真实性:
      - 次日开盘价成交(无 look-ahead)
      - 扣除交易成本
      - 调仓频率控制
    """

    def run(self, config: BacktestConfig,
            target_portfolios: Dict[str, Dict[str, float]],
            data: pd.DataFrame) -> BacktestResult:
        pass
```

### 4.9 ExecutionSimulator（Step 2）

```python
class ExecutionSimulator:
    """
    Step 2 完整执行模拟器 — 事件驱动层
    替代 SimpleBacktester，接口完全相同(IBacktester)
    """

    def __init__(self, config: BacktestConfig):
        self.cost_model = CostModel(config.cost)
        self.slippage_model = SlippageModel(config.cost.slippage)
        self.constraint = ConstraintChecker()
        self.tracker = PortfolioTracker(config.initial_capital)

    def run(self, config: BacktestConfig,
            target_portfolios: Dict[str, Dict[str, float]],
            data: pd.DataFrame) -> BacktestResult:
        pass

    def _execute_day(self, date: str, target: Dict[str, float],
                     market_data: pd.DataFrame):
        """
        单日执行逻辑:
          1. 计算需卖出的股票
          2. 卖出约束过滤(T+1 / 跌停 / 停牌)
          3. 执行卖出 → 资金回笼
          4. 计算需买入的股票 + 资金分配
          5. 买入约束过滤(涨停 / 成交量)
          6. 执行买入
          7. 未成交处理(cash / redistribute / substitute)
          8. 记录快照
        """
        pass


class ConstraintChecker:
    """执行约束检查器 — 每个约束独立方法, 可单独开关"""

    def check_t1(self, sells, buy_dates) -> List:
        """T+1: 过滤掉今日买入的股票"""
        pass

    def check_limit_up(self, buys, market_data) -> List:
        """涨停不可买"""
        pass

    def check_limit_down(self, sells, market_data) -> List:
        """跌停不可卖"""
        pass

    def check_suspended(self, orders, market_data) -> List:
        """停牌冻结: volume==0"""
        pass

    def check_volume_cap(self, orders, market_data,
                         cap_pct: float = 0.10) -> List:
        """成交量约束: 单笔不超过日成交量的 X%"""
        pass
```

### 4.10 双因素滑点模型

```python
import numpy as np

class SlippageModel:
    """Volume-impact 双因素滑点模型"""

    def __init__(self, config: SlippageConfig):
        self.config = config

    def calc(self, order_amount: float,
             daily_volume: float,
             total_mv: float,
             daily_turnover: float) -> float:
        """
        滑点 = k(市值) × turnover_adj × √(order_amount / daily_volume)

        k(市值):       按市值分层(大/中/小盘)
        turnover_adj:  (actual_turnover / ref) ^ power
                       换手率低→adj 放大→滑点增大
        √(占比):       经典 square-root impact 模型

        fallback: 缺成交量数据时用固定滑点
        """
        c = self.config
        if daily_volume <= 0 or daily_turnover <= 0:
            return c.fixed_slippage_bps / 10000

        # 1. 市值分层取 k
        if total_mv >= 500e8:
            k = c.k_large
        elif total_mv >= 100e8:
            k = c.k_mid
        else:
            k = c.k_small

        # 2. 换手率调整
        turnover_adj = (daily_turnover / c.turnover_ref) ** c.turnover_power
        turnover_adj = np.clip(turnover_adj, 0.5, 3.0)

        # 3. square-root impact
        participation = order_amount / daily_volume
        impact = k * turnover_adj * np.sqrt(participation)

        return impact
```

### 4.11 交易成本模型

```python
class CostModel:
    """A 股交易成本精确计算"""

    def __init__(self, config: CostConfig):
        self.config = config

    def calc_buy_cost(self, amount: float) -> dict:
        """
        买入成本:
          佣金 = max(金额 × 费率, 5 元)
          过户费 = 金额 × 0.001%
        """
        commission = max(amount * self.config.commission_rate,
                        self.config.commission_min)
        transfer = amount * self.config.transfer_fee_rate
        return {'commission': commission, 'transfer_fee': transfer,
                'stamp_tax': 0, 'total': commission + transfer}

    def calc_sell_cost(self, amount: float) -> dict:
        """
        卖出成本:
          佣金 + 印花税 + 过户费
        """
        commission = max(amount * self.config.commission_rate,
                        self.config.commission_min)
        stamp_tax = amount * self.config.stamp_tax_rate
        transfer = amount * self.config.transfer_fee_rate
        total = commission + stamp_tax + transfer
        return {'commission': commission, 'stamp_tax': stamp_tax,
                'transfer_fee': transfer, 'total': total}
```

### 4.12 Walk-Forward 引擎（Step 3）

```python
class WalkForwardEngine:
    """
    Walk-Forward 滚动验证框架

    时间轴示例(36+6+3+3):
      |----训练36月----|--验证6月--|--测试3月--|
                       |----训练36月----|--验证6月--|--测试3月--|
                                        |----训练36月----|...
    """

    def __init__(self, config: BacktestConfig):
        self.config = config

    def generate_windows(self, start_date, end_date) -> List[dict]:
        """
        生成所有滚动窗口

        算法:
          cursor = start_date + train_months
          while cursor + valid_months + test_months <= end_date:
            window = {
              'train_start': cursor - train_months,
              'train_end':   cursor,
              'valid_start': cursor,
              'valid_end':   cursor + valid_months,
              'test_start':  cursor + valid_months,
              'test_end':    cursor + valid_months + test_months,
            }
            windows.append(window)
            cursor += step_months

        Purged Gap:
          训练集和测试集之间留gap_days天(默认5天)
          防止信息泄露(训练最后几天的标签依赖测试期价格)
          train_end = cursor - gap_days
          valid_start = cursor

        典型结果(2010-2024, 36+6+3, step=3):
          ~44个窗口, 每个窗口独立训练+OOS测试
        """
        windows = []
        train_m = self.config.wf_train_months
        valid_m = self.config.wf_valid_months
        test_m = self.config.wf_test_months
        step_m = self.config.wf_step_months
        gap_days = 5

        cursor = start_date + pd.DateOffset(months=train_m)
        while cursor + pd.DateOffset(months=valid_m + test_m) <= end_date:
            windows.append({
                'id': len(windows),
                'train_start': cursor - pd.DateOffset(months=train_m),
                'train_end':   cursor - pd.Timedelta(days=gap_days),
                'valid_start': cursor,
                'valid_end':   cursor + pd.DateOffset(months=valid_m),
                'test_start':  cursor + pd.DateOffset(months=valid_m),
                'test_end':    cursor + pd.DateOffset(months=valid_m + test_m),
            })
            cursor += pd.DateOffset(months=step_m)
        return windows

    def run(self, data, factor_df, backtester) -> dict:
        """
        完整WF回测:

        for window in windows:
          # 1. 训练期: 学习因子权重/ML模型
          model = train_model(factor_df[train_start:train_end])

          # 2. 验证期: 选最优参数(持仓数N/调仓频率等)
          best_params = grid_search(model, factor_df[valid], param_grid)

          # 3. 测试期: 严格OOS(不能再调参数)
          oos_result = backtester.run(data[test], model, best_params)

          # 4. 记录每窗口结果
          window_results.append({
            'window_id': window['id'],
            'train_sharpe': train_result.sharpe,
            'valid_sharpe': valid_result.sharpe,
            'test_sharpe': oos_result.sharpe,
            'test_return': oos_result.total_return,
            'test_mdd': oos_result.max_drawdown,
            'n_trades': oos_result.n_trades,
            'params_used': best_params,
          })

        # 5. 拼接所有OOS → 计算最终指标
        all_oos_nav = concat(window.oos_nav for window in window_results)
        final_sharpe = calc_sharpe(all_oos_nav)
        final_mdd = calc_mdd(all_oos_nav)

        # 6. DSR校正
        dsr = self.calc_deflated_sharpe(final_sharpe, window_results)

        # 7. PBO检验
        pbo = self.calc_pbo(window_results)

        return {
          'oos_sharpe': final_sharpe,
          'oos_dsr': dsr,
          'oos_pbo': pbo,
          'oos_mdd': final_mdd,
          'n_windows': len(window_results),
          'window_details': window_results,
          'all_oos_nav': all_oos_nav,
        }
```

### 4.12.1 Deflated Sharpe Ratio (DSR)

```python
def calc_deflated_sharpe(self, observed_sharpe: float,
                          window_results: list) -> float:
    """
    Lopez de Prado (2014) Deflated Sharpe Ratio

    问题: 从N个策略/窗口中选最优，观测到的Sharpe被膨胀
    DSR校正: 考虑试验次数、偏度、峰度

    公式:
      E[max(SR)] ≈ σ_SR × ((1-γ)×Φ^{-1}(1-1/N) + γ×Φ^{-1}(1-1/(N×e)))
      γ ≈ 0.5772 (Euler-Mascheroni常数)

      DSR = Φ((SR_observed - E[max(SR)]) / σ_SR × √T
              × √(1 - skew×SR/3 + (kurt-3)×SR²/12))

    其中:
      N = 试验次数(窗口数 × 参数组合数)
      T = 观测数(交易日数)
      skew = 收益率偏度
      kurt = 收益率峰度
      σ_SR = SR的标准差 ≈ √((1 + 0.5×SR² - skew×SR + (kurt-3)×SR²/4) / T)

    解读:
      DSR > 0.95: 有统计显著性(Sharpe大概率不是运气)
      DSR 0.5-0.95: 可疑(可能部分来自过拟合)
      DSR < 0.5: 不显著(大概率是过拟合)

    前端展示:
      回测结果页: "Sharpe 0.87 (DSR: 0.92 ✅)"
    """
    from scipy.stats import norm
    import numpy as np

    all_returns = self._concat_oos_returns(window_results)
    T = len(all_returns)
    sr = observed_sharpe
    skew = float(pd.Series(all_returns).skew())
    kurt = float(pd.Series(all_returns).kurtosis()) + 3  # excess→raw
    N = len(window_results) * max(self.config.param_grid_size, 1)

    # SR的标准差
    sigma_sr = np.sqrt((1 + 0.5*sr**2 - skew*sr/3 + (kurt-3)*sr**2/4) / T)

    # 期望最大SR (Bonferroni近似)
    gamma = 0.5772
    e_max_sr = sigma_sr * ((1-gamma)*norm.ppf(1-1/N) + gamma*norm.ppf(1-1/(N*np.e)))

    # DSR
    z = (sr - e_max_sr) / sigma_sr
    dsr = float(norm.cdf(z))
    return dsr
```

### 4.12.2 Probability of Backtest Overfitting (PBO)

```python
def calc_pbo(self, window_results: list) -> float:
    """
    Bailey et al. (2015) PBO — CPCV方法

    核心思想:
      将WF窗口组合成多条独立的OOS路径
      计算每条路径的IS(样本内)排名 vs OOS(样本外)排名
      如果IS排名最优的配置在OOS也最优 → 不是过拟合
      如果IS最优的在OOS排名差 → 过拟合

    简化实现(不做完整CPCV，用WF窗口近似):
      对每个窗口: train_sharpe排名 vs test_sharpe排名
      计算 Rank Correlation (Spearman)
      PBO = 1 - P(IS_best在OOS中排名前50%)

    解读:
      PBO < 0.3: 低过拟合风险 ✅
      PBO 0.3-0.6: 中等风险 ⚠️
      PBO > 0.6: 高过拟合风险 🔴

    前端展示:
      回测结果页WF Tab: "过拟合概率: 18% ✅"
    """
    if len(window_results) < 5:
        return -1  # 窗口太少无法计算

    train_sharpes = [w['train_sharpe'] for w in window_results]
    test_sharpes = [w['test_sharpe'] for w in window_results]

    from scipy.stats import spearmanr
    corr, _ = spearmanr(train_sharpes, test_sharpes)

    # PBO近似: 训练/测试相关性越低 → 过拟合越严重
    pbo = max(0, (1 - corr) / 2)
    return float(pbo)
```

### 4.12.3 Celery Task模板（回测异步执行）

```python
# backend/tasks/astock_tasks.py

@celery_app.task(bind=True, queue='astock_compute')
def astock_backtest_task(self, run_id: str, config_dict: dict):
    """
    A股回测Celery任务

    被调用: BacktestService.submit_backtest() → .delay()
    """
    from backend.services.backtest_service import BacktestService
    from backend.websocket.manager import ws_manager

    try:
        # 1. 更新状态
        repo.update_status(run_id, 'running')

        # 2. 构建配置
        config = BacktestConfig(**config_dict)

        # 3. 加载数据
        data = DataFeed(config).load()

        # 4. 运行回测(带进度回调)
        def on_progress(day, total, metrics):
            ws_manager.push_sync('backtest', {
                'type': 'progress',
                'run_id': run_id,
                'progress': day / total,
                'day': day,
                'total': total,
                'current_sharpe': metrics.get('sharpe'),
                'current_mdd': metrics.get('mdd'),
            }, room=run_id)

        if config.wf_enabled:
            engine = WalkForwardEngine(config)
            result = engine.run(data, on_progress=on_progress)
        else:
            engine = SimpleBacktester(config)
            result = engine.run(data, on_progress=on_progress)

        # 5. 保存结果
        repo.save_result(run_id, result)
        repo.update_status(run_id, 'completed')

        # 6. WS通知完成
        ws_manager.push_sync('backtest', {
            'type': 'complete', 'run_id': run_id,
        }, room=run_id)

        # 7. 通知
        notification_service.send_sync(
            level='P2', category='backtest', market='astock',
            title=f'回测完成: Sharpe {result["sharpe"]:.2f}',
            link=f'/backtest/{run_id}/result',
        )

    except Exception as e:
        repo.update_status(run_id, 'failed', error=str(e))
        notification_service.send_sync(
            level='P1', category='backtest', market='astock',
            title=f'回测失败', content=str(e)[:200],
        )
        raise
```

### 4.12.4 A股 BaseStrategy 接口

```python
class BaseStrategy(ABC):
    """A股策略基类 — 策略工作台代码模式的用户接口"""

    @abstractmethod
    def compute_alpha(self, data: dict) -> pd.DataFrame:
        """
        计算Alpha得分

        输入:
          data = {
            'klines': pd.DataFrame,       # OHLCV+adj_factor
            'daily_basic': pd.DataFrame,   # 市值/PE/PB/换手率
            'factor_values': pd.DataFrame, # 预计算的34因子值
          }

        输出:
          pd.DataFrame, index=stock_code, columns=['alpha_score']
          分数越高越好(排序选Top-N)
        """
        pass

    def filter_universe(self, universe: pd.DataFrame) -> pd.DataFrame:
        """
        自定义Universe过滤(可选覆盖)
        默认用8层标准过滤，用户可以加额外条件
        """
        return universe  # 默认不额外过滤

    def on_rebalance(self, current_holdings: dict,
                      target_holdings: dict) -> dict:
        """
        自定义调仓逻辑(可选覆盖)
        默认: 全部换仓到target
        用户可以: 限制换手率、保留强趋势股等
        """
        return target_holdings


class ICWeightedStrategy(BaseStrategy):
    """默认策略: IC加权因子合成(规则版)"""

    def __init__(self, factor_weights: dict):
        self.weights = factor_weights

    def compute_alpha(self, data):
        scores = pd.DataFrame(index=data['factor_values'].index)
        scores['alpha_score'] = sum(
            data['factor_values'][f] * w
            for f, w in self.weights.items()
        )
        return scores


class LGBMStrategy(BaseStrategy):
    """Phase 1: LightGBM因子合成"""

    def __init__(self, model_path: str):
        self.model = joblib.load(model_path)

    def compute_alpha(self, data):
        X = data['factor_values'][self.model.feature_name_]
        scores = pd.DataFrame(index=X.index)
        scores['alpha_score'] = self.model.predict(X)
        return scores
```

### 4.13 FactorAnalyzer（单因子分析）

```python
@dataclass
class FactorReport:
    """单因子评估报告"""
    ic_mean: float
    ic_std: float
    ic_ir: float                      # IC_IR = ic_mean / ic_std
    ic_series: pd.Series              # 每日 IC
    group_returns: pd.DataFrame       # 分组收益(5 组 × 时间)
    long_short_return: pd.Series      # 多空收益
    ic_decay: Dict[int, float]        # {1: 0.05, 5: 0.04, 10: 0.03, 20: 0.02}
    autocorrelation: float            # 因子自相关
    coverage: float                   # 平均覆盖率
    yearly_metrics: pd.DataFrame      # 分年度指标
    regime_metrics: Dict[str, dict]   # 分市场状态指标

    @property
    def is_effective(self) -> bool:
        """因子是否有效的初步判断"""
        return abs(self.ic_mean) > 0.02 and self.ic_ir > 0.3


class FactorAnalyzer:
    """单因子深度分析"""

    def analyze(self, factor_values: pd.Series,
                forward_returns: Dict[int, pd.Series],
                groups: int = 5) -> FactorReport:
        """
        forward_returns: {1: 1日前瞻收益, 5: 5日, 10: 10日, 20: 20日}

        计算内容:
          1. IC 序列(每日横截面 Spearman 相关, 对每个 forward 周期)
          2. IC 均值、IC_IR
          3. 分组收益(5 组)
          4. 多空收益(top-bottom)
          5. IC 衰减曲线
          6. 因子自相关
          7. 因子覆盖率
          8. 分年度指标
          9. 分市场状态指标
        """
        pass
```

### 4.14 市场状态判定

```python
class MarketRegimeDetector:
    """市场状态判定器"""

    def __init__(self, config: MarketRegimeConfig):
        self.config = config

    def detect(self, benchmark_close: pd.Series) -> pd.Series:
        """
        输入: 基准指数收盘价序列
        输出: Series, index=date, values='bull'|'bear'|'sideways'

        方法 'ma': 指数在 MA120 之上=牛, 之下=熊
        方法 'drawdown': 从低点涨 20%+=牛, 从高点跌 20%+=熊
        """
        pass
```

### 4.15 超额收益计算

```python
def calc_excess_return(strategy_return: pd.Series,
                       benchmark_return: pd.Series) -> pd.Series:
    """
    对数收益相减(更精确):
      excess = ln(1 + r_strategy) - ln(1 + r_benchmark)
    """
    return np.log(1 + strategy_return) - np.log(1 + benchmark_return)
```

### 4.16 调仓日历

```python
class RebalanceCalendar:
    """
    调仓日历生成器

    时间线(周频默认):
      周五收盘后 → 计算因子+信号+目标持仓 (signal_date)
      下周一开盘 → 执行交易 (exec_date)

    各频率:
      weekly   — 每周最后一个交易日信号, 下周第一个交易日执行
      biweekly — 每两周
      monthly  — 每月最后一个交易日信号, 下月第一个交易日执行
      daily    — 每个交易日收盘后信号, 下一交易日执行

    节假日: 不需要特殊处理, 调仓日定义在交易日序列上
    关键 assert: signal_date < exec_date (防 look-ahead)
    """

    def __init__(self, trade_dates: List[str], config: BacktestConfig):
        self.trade_dates = trade_dates
        self.freq = config.rebalance_freq
        self.signal_weekday = config.rebalance_weekday

    def generate(self) -> List[Tuple[str, str]]:
        """返回: [(signal_date, exec_date), ...]"""
        pass
```

---

## 五、三步渐进实现计划

### Step 1: 信号层 + 简化回测（3-5 天）

**目标**: 34 个因子有没有信号？哪些值得留？

**实现范围**:
- DataFeed + UniverseFilter(完整版)
- 34 个因子全量计算(BaseFactor + FactorRegistry)
- 因子预处理(MAD→zscore→中性化)
- FactorAnalyzer(完整版, 1/5/10/20 日 forward return)
- SimpleBacktester(简化版)
- PerformanceAnalyzer(完整版)
- SignalComposer(等权)
- PortfolioBuilder(完整版)

**验收标准**:

| 验收项 | 通过条件 | 失败动作 |
|--------|----------|----------|
| 有效因子数量 | ≥5 个因子 IC 均值>0.02 | 停下审视因子体系 |
| 多空收益 | top-bottom 年化>5% | 检查因子方向和预处理 |
| 回测确定性 | 同参数跑 2 次完全一致 | 排查随机性来源 |
| 数据完整性 | 因子覆盖率>90%平均 | 检查数据源和计算逻辑 |
| 回测基本合理 | Sharpe 在 0.3~3.0 | <0.3 无信号, >3.0 有 bug |

### Step 2: 完整执行模拟器（5-7 天）

**目标**: 执行约束吃掉多少收益？

**在 Step 1 基础上新增**:
- ExecutionSimulator(替代 SimpleBacktester)
- ConstraintChecker(T+1 / 涨跌停 / 停牌 / 成交量)
- CostModel(精确版)
- SlippageModel(双因素)
- PortfolioTracker(完整版)

**验收标准**:
- Step 1 vs Step 2 收益对比报告(量化执行 gap)
- 全部 5 个约束通过单元测试
- 确定性验证通过

### Step 3: Walk-Forward 框架（5-7 天）

**目标**: 真实 Sharpe 多少？是否过拟合？

**在 Step 2 基础上新增**:
- WalkForwardEngine
- 窗口结果存储(backtest_wf_windows 表)

**验收标准**:
- WF-OOS 拼接 Sharpe vs 全量 Sharpe 对比
- 如果 WF-Sharpe < 全量 × 0.5 → 过拟合严重, 需简化模型

---

## 六、前端页面（5 个）— 摘要

> 完整布局/交互/组件设计详见 DEV_FRONTEND_UI.md 第二章

| 页面 | 核心功能 | 关键 API |
|------|---------|---------|
| ① 策略工作台 | 三栏: 因子面板 + 双模式编辑器(可视化/代码) + AI 助手 | POST /api/strategy, POST /api/ai/strategy-assist |
| ② 回测配置面板 | 6 个 Tab: 市场股票池/时间段/执行/成本/风控/动态仓位 | POST /api/backtest/run |
| ③ 回测运行监控 | WebSocket 实时进度 + 净值曲线 + 运行日志 | WS /ws/backtest/{run_id} |
| ④ 回测结果分析 | 8 个 Tab: 净值/月度归因/持仓/交易/WF/敏感性/实盘对比/仓位 | GET /api/backtest/{run_id}/result |
| ⑤ 策略库 | 列表/对比/历史 | GET /api/strategy, POST /api/backtest/compare |

BacktestConfig 字段与配置面板 Tab 的对应关系:
- Tab 1 市场/股票池 → market, universe_preset, universe_industries, universe_custom_codes
- Tab 2 时间段 → start_date, end_date, exclude_periods, regime
- Tab 3 执行参数 → exec_price, rebalance_freq, holding_count, weight_method
- Tab 4 成本模型 → cost (CostConfig + SlippageConfig)
- Tab 5 风控/高级 → industry_cap_pct, single_stock_cap_pct, unfilled_handling, wf_*
- Tab 6 动态仓位 → dynamic_position_enabled, position_signal, position_thresholds

---

## 七、后端 API 清单

| API 端点 | 方法 | 页面 | 功能 |
|---------|------|------|------|
| `/api/strategy` | POST | ① | 保存策略定义 |
| `/api/strategy` | GET | ⑤ | 策略列表 |
| `/api/strategy/{id}` | GET/PUT/DELETE | ①⑤ | 策略 CRUD |
| `/api/factors/summary` | GET | ① | 34 因子 IC/IR 摘要 |
| `/api/ai/strategy-assist` | POST | ① | AI 助手对话 |
| `/api/backtest/run` | POST | ② | 提交回测任务 |
| `/api/backtest/{run_id}/result` | GET | ④ | 回测结果 |
| `/api/backtest/{run_id}/trades` | GET | ④ | 交易明细(分页) |
| `/api/backtest/{run_id}/holdings/{date}` | GET | ④ | 某日持仓快照 |
| `/api/backtest/{run_id}/sensitivity` | POST | ④ | 参数敏感性分析 |
| `/api/backtest/{run_id}/live-compare` | GET | ④ | 实盘对比数据 |
| `/api/backtest/compare` | POST | ⑤ | 策略对比数据 |
| `/api/backtest/history` | GET | ⑤ | 回测历史列表 |
| `/ws/backtest/{run_id}` | WS | ③ | 实时进度推送 |

---

## 八、数据库表结构（6 张新表）

### 8.1 strategy — 策略定义表

```sql
CREATE TABLE strategy (
    strategy_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(200) NOT NULL,
    version         INT DEFAULT 1,
    description     TEXT,
    market          VARCHAR(20) DEFAULT 'a_share',
    universe_preset VARCHAR(20) DEFAULT 'all_a',
    -- 策略定义
    mode            VARCHAR(20) NOT NULL,          -- 'visual' | 'code'
    factor_config   JSONB,                         -- 可视化模式: 因子选择+权重
    code_content    TEXT,                           -- 代码模式: Python 代码
    -- 元信息
    is_favorite     BOOLEAN DEFAULT FALSE,
    status          VARCHAR(20) DEFAULT 'draft',   -- draft | backtested | deployed
    last_run_id     UUID,                          -- 最近回测 run_id(FK 延迟添加)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_strategy_updated ON strategy(updated_at DESC);
CREATE INDEX idx_strategy_status ON strategy(status);
```

### 8.2 backtest_run — 回测运行记录

```sql
CREATE TABLE backtest_run (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID REFERENCES strategy(strategy_id),
    run_name        VARCHAR(200),
    strategy_type   VARCHAR(50),                   -- 'multi_factor' | 'single_factor'
    market          VARCHAR(20) DEFAULT 'a_share',
    universe_preset VARCHAR(20),
    config_json     JSONB NOT NULL,                -- BacktestConfig 完整快照
    factor_list     TEXT[],                        -- 使用的因子名列表
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    status          VARCHAR(20) DEFAULT 'running', -- running | completed | failed
    -- 汇总指标(冗余, 列表页快速展示)
    annual_return   FLOAT,
    sharpe_ratio    FLOAT,
    max_drawdown    FLOAT,
    calmar_ratio    FLOAT,
    total_turnover  FLOAT,
    win_rate        FLOAT,
    -- 时间
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    error_msg       TEXT
);
CREATE INDEX idx_backtest_run_created ON backtest_run(created_at DESC);
CREATE INDEX idx_backtest_run_strategy ON backtest_run(strategy_id);
```

### 8.3 backtest_daily_nav — 每日净值

```sql
CREATE TABLE backtest_daily_nav (
    run_id          UUID REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    nav             FLOAT NOT NULL,
    cash            FLOAT NOT NULL,
    market_value    FLOAT NOT NULL,
    daily_return    FLOAT,
    benchmark_nav   FLOAT,
    benchmark_return FLOAT,
    excess_return   FLOAT,                         -- 对数收益相减
    PRIMARY KEY (run_id, trade_date)
);
```

### 8.4 backtest_trades — 交易明细

```sql
CREATE TABLE backtest_trades (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    signal_date     DATE NOT NULL,
    exec_date       DATE NOT NULL,
    stock_code      VARCHAR(10) NOT NULL,
    side            VARCHAR(4) NOT NULL,           -- 'buy' | 'sell'
    shares          INT NOT NULL,
    target_price    FLOAT,
    exec_price      FLOAT NOT NULL,
    slippage_bps    FLOAT,
    commission      FLOAT,
    stamp_tax       FLOAT,
    transfer_fee    FLOAT,
    total_cost      FLOAT,
    reject_reason   VARCHAR(50),                   -- NULL=成交, 'limit_up'/'suspended'/...
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_bt_trades_run_date ON backtest_trades(run_id, exec_date);
CREATE INDEX idx_bt_trades_stock ON backtest_trades(run_id, stock_code);
```

### 8.5 backtest_holdings — 每日持仓快照

```sql
CREATE TABLE backtest_holdings (
    run_id          UUID REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    stock_code      VARCHAR(10) NOT NULL,
    shares          INT NOT NULL,
    cost_basis      FLOAT,
    market_price    FLOAT,
    market_value    FLOAT,
    weight          FLOAT,
    pnl             FLOAT,
    buy_date        DATE,                          -- T+1 判断用
    industry_code   VARCHAR(10),
    PRIMARY KEY (run_id, trade_date, stock_code)
);
```

### 8.6 backtest_wf_windows — Walk-Forward 窗口记录

```sql
CREATE TABLE backtest_wf_windows (
    run_id          UUID REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    window_id       INT NOT NULL,
    train_start     DATE NOT NULL,
    train_end       DATE NOT NULL,
    valid_start     DATE,
    valid_end       DATE,
    test_start      DATE NOT NULL,
    test_end        DATE NOT NULL,
    oos_annual_return FLOAT,
    oos_sharpe      FLOAT,
    oos_max_drawdown FLOAT,
    selected_factors TEXT[],
    model_params    JSONB,
    PRIMARY KEY (run_id, window_id)
);
```

### 8.7 数据量估算

| 表 | 单次回测行数 | 100 次回测 | 结论 |
|----|-------------|-----------|------|
| backtest_daily_nav | ~2,000 | 20 万 | 很小 |
| backtest_trades | ~24,000 | 240 万 | 不大 |
| backtest_holdings | ~60,000 | 600 万 | 中等 |
| backtest_wf_windows | ~8 | 800 | 极小 |

**结论: 暂不需要分区, 索引够用。**

---

## 九、待办 Checklist（代码前必须完成）

| 待办 | 内容 | 优先级 | 影响 |
|------|------|--------|------|
| data_source_checklist | 验证 akshare/tushare 涨跌停标记或涨跌停价格字段 | P0 | Step 2 涨跌停判断 |
| data_source_checklist | 验证 VWAP 数据可获取性 | P0 | 成交价可选项 |
| data_source_checklist | 验证复权因子 adj_factor 更新频率和准确性 | P0 | 价格准确性 |
| data_source_checklist | 验证沪深 300/中证 500/1000 成分股历史列表可获取性 | P1 | 股票池预设 |
| data_source_checklist | 验证申万行业分类数据可获取性 | P1 | 行业过滤+中性化 |

---

## 十、与其他模块的关系

| 模块 | 关系 | 接口 |
|------|------|------|
| 因子挖掘(DEV_FACTOR_MINING.md) | Phase A使用因子挖掘产出的因子 | factor_values表 |
| AI闭环(DEV_AI_EVOLUTION.md) | 策略构建Agent和诊断Agent调用回测引擎 | BacktestService.submit() |
| 参数可配置(DEV_PARAM_CONFIG.md) | BacktestConfig全部参数前端可调 | ai_parameters表 |
| 后端服务层(DEV_BACKEND.md) | Router→Service→Task→Engine调用链 | 见DEV_BACKEND §四数据流 |
| 通知系统(NotificationService) | 回测完成/失败→NotificationService | backtest.complete/failed模板 |
| 调度系统(DEV_SCHEDULER.md) | Celery Beat可配置定期回测 | astock_backtest_task |
| 前端(DEV_FRONTEND_UI.md) | 5个页面通过API+WS交互 | §七 API清单 |
| 外汇回测(Phase 2) | 独立Python引擎，不复用Rust | 共用WF/DSR/PBO框架 |

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. 因子预处理顺序修正（覆盖 §4.6）

原文档顺序（错误）：MAD去极值 → zscore → 中性化
**正确顺序**：
```python
class FactorPreprocessor:
    """
    因子预处理流程（每日横截面处理）— 顺序不可调换:
      1. MAD 去极值: 中位数 ± 5 × MAD
      2. 缺失值填充: 行业中位数填充, 仍缺则0
      3. 市值+行业中性化: 对 ln(市值)+行业哑变量回归, 取残差  ← 先中性化
      4. zscore 标准化: (x - mean) / std                      ← 再标准化
    """
    def process(self, factor_values: pd.Series,
                market_cap: pd.Series,
                industry: pd.Series) -> pd.Series:
        result = self._mad_winsorize(factor_values)
        result = self._fill_missing(result, industry)   # 新增: 缺失值填充
        result = self._neutralize(result, market_cap, industry)  # 先中性化
        result = self._zscore(result)                            # 再标准化
        return result

    def _fill_missing(self, s: pd.Series, industry: pd.Series) -> pd.Series:
        """缺失值填充: 行业中位数填充, 仍缺则0"""
        pass
```
**原因**: 如果先zscore再中性化，中性化回归的残差分布不对，所有因子IC都不准。

### P2. 涨跌停封板成交限制（覆盖 §4.4 并扩展 §4.9 ConstraintChecker）

§4.4 的 `get_limit_pct()` 保留，新增北交所：
```python
def get_limit_pct(stock_code: str, is_st: bool) -> float:
    if is_st:
        return 0.05           # ST ±5%
    elif stock_code.startswith('688'):
        return 0.20           # 科创板 ±20%
    elif stock_code.startswith(('300', '301')):
        return 0.20           # 创业板 ±20%
    elif stock_code.startswith(('8', '4')):
        return 0.30           # 北交所 ±30%
    else:
        return 0.10           # 主板 ±10%
```

新增 `can_trade()` 函数（SimBroker和ConstraintChecker必须实现）：
```python
def can_trade(code: str, date: date, direction: str,
              market_data: pd.DataFrame) -> bool:
    """
    判断某只股票在某日某方向是否可成交。
    不处理封板限制会让回测假设任何信号都能成交，严重失真。
    """
    row = market_data.loc[(date, code)]
    # 停牌
    if row['volume'] == 0:
        return False
    limit_pct = get_limit_pct(code, is_st=row.get('is_st', False))
    limit_up_price = row['pre_close'] * (1 + limit_pct)
    limit_down_price = row['pre_close'] * (1 - limit_pct)
    turnover = row.get('turnover_rate_f', 999)
    # 买入 + 封涨停板(收盘≈涨停价 且 换手率<1%) → 买不进
    if direction == 'buy' and abs(row['close'] - limit_up_price) / limit_up_price < 0.001 and turnover < 1.0:
        return False
    # 卖出 + 封跌停板(收盘≈跌停价 且 换手率<1%) → 卖不出
    if direction == 'sell' and abs(row['close'] - limit_down_price) / limit_down_price < 0.001 and turnover < 1.0:
        return False
    return True
```

### P3. 整手约束和资金T+1建模（扩展 §4.9 ExecutionSimulator）

`_execute_day()` 必须增加以下逻辑：

**整手约束**:
```python
# A股最小交易单位100股
actual_shares = math.floor(target_value / price / 100) * 100
actual_value = actual_shares * price
# 30只等权持仓的整手误差累积可能导致总仓位<95%
```

**资金T+1规则**:
```python
class PortfolioTracker:
    cash_available: Decimal   # 可用资金(含当日卖出回款, T+0可用于买入)
    cash_withdrawable: Decimal  # 可取资金(不含当日卖出, T+1才可取)
    
    def on_sell(self, amount: Decimal, date: date):
        self.cash_available += amount       # 当日即可用于买入
        # cash_withdrawable 在次日开盘前才增加
    
    def on_day_end(self, date: date):
        self.cash_withdrawable = self.cash_available  # 结算
```

**部分成交处理**: 剩余部分次日继续执行，不取消。

**"实际vs理论仓位偏差"**: 作为回测输出指标。偏差长期>3%说明资金利用效率有问题。

### P4. 存活偏差处理（新增 §4.3 扩展）

回测引擎的 `UniverseFilter` 必须处理退市股：
- symbols表必须包含已退市股票（Tushare `stock_basic(list_status='D')`）
- 在历史日期的Universe中，退市前的股票应该存在
- 退市前5个交易日强制平仓，按最后可交易价格结算
- 不处理存活偏差会让回测收益虚高2-5%/年

### P5. 确定性测试用固定数据快照

- 确定性测试用**Parquet文件**作为数据快照，不依赖数据库当前状态
- 测试流程: `load_snapshot → run_backtest → compare_hash(result)`
- 精确到**小数点后6位**完全一致（不是近似相等）
- 任何引入随机性的地方（pandas排序稳定性、浮点累积）都必须固定
- `sort_values()` 必须加 `kind='mergesort'` 保证稳定排序

### P6. Bootstrap Sharpe置信区间

每次回测自动计算：
```python
def bootstrap_sharpe_ci(daily_returns: pd.Series, n_bootstrap: int = 1000,
                        ci: float = 0.95) -> tuple[float, float, float]:
    """
    返回: (sharpe_mean, sharpe_lower, sharpe_upper)
    展示格式: Sharpe: 1.21 [0.43, 1.98] (95% CI)
    如果 sharpe_lower < 0 → 标红警告"策略可能不赚钱"
    """
    sharpes = []
    for _ in range(n_bootstrap):
        sample = daily_returns.sample(len(daily_returns), replace=True)
        sharpes.append(sample.mean() / sample.std() * np.sqrt(252))
    lower = np.percentile(sharpes, (1 - ci) / 2 * 100)
    upper = np.percentile(sharpes, (1 + ci) / 2 * 100)
    return np.mean(sharpes), lower, upper
```

### P7. 交易成本敏感性分析

回测结果必须包含不同成本假设下的绩效对比：
```
成本倍数    年化收益    Sharpe    MDD
0.5x       ...        ...      ...
1.0x       ...        ...      ...（基准）
1.5x       ...        ...      ...
2.0x       ...        ...      ...
```
实现方式: 基准回测跑完后，用同一组交易记录重新计算不同成本下的净值曲线（不需要重跑信号）。
如果2倍成本下Sharpe < 0.5，标红警告。

### P8. IC计算forward return定义（覆盖 §4.13 FactorAnalyzer）

- forward return使用**相对沪深300的超额收益**（不是绝对收益）
- 必须用**复权价格**（close × adj_factor / latest_adj_factor）计算
- 停牌期间的return用**行业指数**代替
- 同时计算1/5/10/20日IC，因子评估报告展示"绝对IC"和"超额IC"

### P9. 回测报告新增12项指标（扩展 backtest_run 结果字段）

| 指标 | 字段名 | 说明 |
|------|--------|------|
| Calmar Ratio | calmar_ratio | 年化收益/最大回撤 |
| Sortino Ratio | sortino_ratio | 只看下行波动率 |
| 最大连续亏损天数 | max_consecutive_loss_days | 心理压力指标 |
| 胜率 | win_rate | 盈利交易占比 |
| 盈亏比 | profit_loss_ratio | 平均盈利/平均亏损 |
| Beta | beta | 相对沪深300，绝对收益应<0.3 |
| 信息比率 | information_ratio | IR>0.5算不错 |
| 年化换手率 | annual_turnover | ×单边成本=年交易成本 |
| Bootstrap Sharpe CI | sharpe_ci_lower, sharpe_ci_upper | 95%置信区间 |
| 开盘跳空统计 | avg_overnight_gap | 买入日open vs 前日close偏差 |
| 实际vs理论仓位偏差 | position_deviation | 整手约束导致的偏差 |
| 成本敏感性 | cost_sensitivity_json | JSONB存0.5x/1x/1.5x/2x结果 |

**年度分解**: backtest_run结果中必须包含每年的收益/Sharpe/MDD单独列出。最差年度标红。
**市场状态分段**: 自动分牛市/熊市/震荡三段，分别展示绩效。

### P10. 回测引擎架构要求

回测引擎的DataFeed必须支持**注入自定义行情数据**（不只是从DB读历史数据），
为Phase 1的压力测试模式（历史极端场景回放+合成场景注入）预留接口：
```python
class DataFeed:
    @classmethod
    def from_database(cls, config: BacktestConfig) -> 'DataFeed': ...
    
    @classmethod
    def from_parquet(cls, path: str) -> 'DataFeed': ...  # 确定性测试用
    
    @classmethod
    def from_dataframe(cls, df: pd.DataFrame) -> 'DataFeed': ...  # 压力测试/注入用
```

---

## 回测可信度规则（强制执行，从CLAUDE.md迁入）

> 回测结果不可信 = 所有后续工作白费。以下规则与工作原则同等重要。

### 规则1: 涨跌停封板必须处理

SimBroker必须实现 `can_trade()` 函数：
```python
def can_trade(code: str, date: date, direction: str) -> bool:
    # 停牌（volume=0 且 close=pre_close）→ False
    # 买入 + 收盘价==涨停价 + 换手率<1% → False（封板买不进）
    # 卖出 + 收盘价==跌停价 + 换手率<1% → False（封板卖不出）
    # 成交量==0 → False
```
涨跌停幅度区分：主板10%、创业板/科创板20%、ST股5%、北交所30%。

### 规则2: 整手约束和资金T+1必须建模

**整手约束**:
```python
actual_shares = floor(target_value / price / 100) * 100  # A股最小交易单位100股
```

**资金T+1规则**:
- A股卖出资金当日可用于买入（T+0可用），但不可取出（T+1可取）
- SimBroker需跟踪：可用资金（含当日卖出回款）和 可取资金（不含当日卖出）
- 部分成交处理：剩余部分次日继续执行，不取消

**"实际vs理论仓位偏差"**: 作为回测输出指标。偏差长期>3%说明资金利用效率有问题。

### 规则3: 确定性测试用固定数据快照

- 用Parquet文件作为测试数据快照，不依赖数据库当前状态
- 测试流程：`load_snapshot → run_backtest → compare_hash(result)`
- 精确到**小数点后6位**完全一致（不是近似相等）

### 规则4: 回测结果必须有统计显著性

自动计算 **bootstrap Sharpe 95%置信区间**：
- 对日收益率序列做1000次bootstrap采样，计算Sharpe的5%/95%分位
- 展示格式：`Sharpe: 1.21 [0.43, 1.98] (95% CI)`
- 如果5%分位的Sharpe < 0，标红警告"策略可能不赚钱"

### 规则5: 隔夜跳空必须统计

回测报告加 **"开盘跳空统计"** 指标：
- 买入日 open vs 前日close 的平均偏差
- 如果偏差持续>1%，说明信号有"追涨"倾向

### 规则6: 交易成本敏感性分析

回测结果必须包含不同成本假设下的绩效对比：
```
成本倍数    年化收益    Sharpe    MDD
0.5x       ...        ...      ...
1.0x       ...        ...      ...（基准）
1.5x       ...        ...      ...
2.0x       ...        ...      ...
```
如果2倍成本下Sharpe < 0.5，策略在实盘中大概率不行。

---

## 回测报告必含指标（从CLAUDE.md迁入）

| 指标 | 说明 |
|------|------|
| Calmar Ratio | 年化收益/最大回撤 |
| Sortino Ratio | 只看下行波动率的Sharpe |
| 最大连续亏损天数 | 心理压力指标 |
| 胜率 + 盈亏比 | 交易心理参考 |
| 月度收益热力图 | 发现季节性 |
| Beta | 策略跟大盘关联度，绝对收益策略应<0.3 |
| 信息比率(IR) | 超额收益稳定性，>0.5算不错 |
| 年化换手率 | × 单边成本 = 年交易成本 |
| Bootstrap Sharpe CI | `Sharpe: 1.21 [0.43, 1.98] (95% CI)` |
| 成本敏感性 | 0.5x/1x/1.5x/2x成本下的Sharpe |
| 开盘跳空统计 | 买入日open vs 前日close偏差 |
| 实际vs理论仓位偏差 | 整手约束导致的偏差 |

**年度分解**: 每年的收益/Sharpe/MDD单独列出。最差年度标红。
**市场状态分段**: 自动分牛市/熊市/震荡三段，分别看绩效。

---

## 回测引擎加固计划（2026-04-07审计后新增）

> 详细实施方案: `docs/BACKTEST_ENGINE_HARDENING_PLAN.md`

### 审计发现与修复优先级

**Phase 1 — 数据正确性（影响所有历史回测结论）**:
- P1: 分红除权处理（SimBroker日循环检测ex_date，调整cash/holdings）
- P2: 印花税历史税率（2023-08-28前0.1%，之后0.05%）
- P3: 最低佣金5元/笔（execute_buy/sell增加min_cost）
- P4: overnight_gap三因素滑点接入（当前slippage_model.py中是死代码）
- P5: DataFeed必填字段校验（pre_close/volume/close缺失即报错，不静默）
- P6: Fill.slippage双重计数修正
- P7: Phase A z-score clip±3（与CLAUDE.md生产流程对齐）

**Phase 2 — 分析专业化**:
- BacktestResult.metrics()内置计算（Sharpe/Sortino/Calmar/MDD/年化等15+指标）
- Benchmark相对指标（alpha/beta/IR/tracking_error）
- Deflated Sharpe Ratio（M=FACTOR_TEST_REGISTRY累计测试数）
- 子期间分析（年度+牛熊regime自动拆分）
- 订单执行质量（fill_rate/price_advantage/realized_slippage）

**Phase 3 — 性能与健壮性**:
- price_idx用MultiIndex替代iterrows()（10-50x提速）
- daily_close一次性预构建
- 单位转换集中到DataFeed层（消灭magic number）
- 退市检测+自动清算
- ValidatorChain（拆分can_trade为可组合Validator，拒绝原因可追溯）

**Phase 4 — Qlib集成+架构升级（Stage 4前置）**:
- Qlib StaticDataLoader适配器（从TimescaleDB喂数据给Qlib ML模型）
- Alpha158因子移植（KBAR/CORR/方向计数，因子池63→100+）
- Executor接口抽象 + NestedExecutor（借鉴Qlib设计，月度→日度嵌套）
- CompositeSignalEngine接入回测
- H0成本模型校准（QMT实盘15笔 vs SimBroker，误差<5bps）

### 与本文档已有设计的对齐

| 本文档决策 | 加固计划对应项 |
|-----------|-------------|
| 决策3: 滑点三因素模型 | Phase 1.4 接入overnight_gap（已实现但未wired） |
| 决策5: 三步渐进（Step1信号+Step2执行+Step3 WF） | Phase 3.5 ValidatorChain拆分Step2能力 |
| 决策7: 6张结果表 | Phase 2 BacktestResult.metrics()先内存计算 |
| 决策10: unfilled handling | Phase 3.5 ValidatorChain + 拒绝原因 |
| §回测报告必含指标 | Phase 2 全部内置自动计算 |
