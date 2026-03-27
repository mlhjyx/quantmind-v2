# Sprint 1.3b Strategy 设计文档

> 作者: strategy (策略研究专家)
> 日期: 2026-03-23
> Sprint: 1.3b

---

## 任务1：回测+PT共享核心逻辑可行性评估

### 1.1 问题背景

Phase 0连续出现6个P0 bug（LL-002~LL-005, LL-010等），根因是回测(backtest)和Paper Trading(PT)两套独立代码路径。具体表现：

- `SimpleBacktester._rebalance()` 和 `PaperBroker._do_rebalance()` 是**复制粘贴**的逻辑
- `run_backtest.py` 和 `run_paper_trading.py` 各自实现信号生成流程
- 修一处bug另一处不改 → 行为不一致 → 假设偏差 → P0事故

### 1.2 代码路径对比分析

#### 1.2.1 调仓执行层（_rebalance）

| 对比项 | SimpleBacktester._rebalance | PaperBroker._do_rebalance |
|--------|---------------------------|--------------------------|
| 文件 | backtest_engine.py L376-440 | paper_broker.py L226-285 |
| 目标股数计算 | `int(target_value / close / lot_size) * lot_size` | 完全相同 |
| 卖出逻辑 | 遍历holdings, curr>target则卖差额 | 完全相同 |
| 买入逻辑 | 按金额降序, cash<10%停止 | 完全相同 |
| can_trade调用 | `broker.can_trade(code, dir, row)` | 完全相同 |
| SimBroker引用 | 函数参数传入 | self.broker |

**结论**: 两个函数的业务逻辑**100%相同**，唯一差异是SimBroker的引用方式（参数 vs self属性）。这是典型的代码复制问题。

#### 1.2.2 信号生成层

| 对比项 | run_backtest.py | run_paper_trading.py signal phase |
|--------|----------------|----------------------------------|
| 因子加载 | `load_factor_values(rd, conn)` | 同一函数（从run_backtest导入） |
| Universe | `load_universe(rd, conn)` | 同一函数（从run_backtest导入） |
| 行业分类 | `load_industry(conn)` | 同一函数（从run_backtest导入） |
| SignalComposer | `composer.compose(fv, universe)` | 完全相同 |
| PortfolioBuilder | `builder.build(scores, industry, prev_weights)` | 完全相同 |
| 配置源 | PAPER_TRADING_CONFIG | PAPER_TRADING_CONFIG |
| **额外检查** | 无 | 因子完整性检查、截面覆盖率、行业集中度、持仓重合度 |
| **额外步骤** | 无 | Beta监控、信号存DB、通知推送 |

**结论**: 信号生成的核心管道已通过import共享。PT额外增加了生产级的校验和监控，这是合理的分层——回测不需要这些检查。

#### 1.2.3 执行层

| 对比项 | SimpleBacktester.run() | run_paper_trading.py execute phase |
|--------|----------------------|-----------------------------------|
| 循环方式 | 遍历全部交易日 | 单日执行（T+1日调度） |
| 调仓判断 | exec_map查signal_date | 读signals表 + 信号action标记 |
| 价格数据 | 预加载全量price_data | 实时加载当日load_today_prices |
| NAV计算 | broker.get_portfolio_value | 同 |
| 状态持久化 | 无（内存） | save_state写DB（trade_log + position_snapshot + performance_series） |
| 风控检查 | 无 | 4级熔断 + 风控日检 |
| 通知 | 无 | 钉钉通知 |

**结论**: 执行层差异最大，但差异是**合理的**——回测是批量模拟，PT是单日实时执行+状态持久化。这不是重复代码，是不同运行模式的不同需求。

### 1.3 可行性评估

#### 方案：抽取共享RebalanceCore

**核心思路**: 将`_rebalance`逻辑抽取为独立函数/类，回测和PT都调用。

```python
# backend/engines/rebalance_core.py

def execute_rebalance(
    broker: SimBroker,
    target_weights: dict[str, float],
    portfolio_value: float,
    exec_date: date,
    price_idx: dict,
    today_close: dict,
) -> list[Fill]:
    """共享调仓核心逻辑。

    回测和Paper Trading共用此函数。
    修改此函数 = 同时修改两条路径的行为。
    """
    lot_size = broker.config.lot_size
    fills = []

    # 1. 计算目标股数
    target_shares = {}
    for code, weight in target_weights.items():
        close_price = today_close.get(code, 0)
        if close_price > 0:
            target_value = portfolio_value * weight
            shares = int(target_value / close_price / lot_size) * lot_size
            if shares > 0:
                target_shares[code] = shares

    # 2. 卖出
    for code, curr_shares in list(broker.holdings.items()):
        target_s = target_shares.get(code, 0)
        if curr_shares > target_s:
            row = price_idx.get((code, exec_date))
            if row is None:
                continue
            if not broker.can_trade(code, "sell", row):
                continue
            fill = broker.execute_sell(code, curr_shares - target_s, row)
            if fill:
                fills.append(fill)

    # 3. 买入（按金额降序）
    buy_orders = []
    for code, target_s in target_shares.items():
        curr_shares = broker.holdings.get(code, 0)
        if target_s > curr_shares:
            buy_amount = (target_s - curr_shares) * today_close.get(code, 0)
            buy_orders.append((code, buy_amount))
    buy_orders.sort(key=lambda x: -x[1])

    for code, buy_amount in buy_orders:
        if broker.cash < buy_amount * 0.1:
            break
        row = price_idx.get((code, exec_date))
        if row is None:
            continue
        if not broker.can_trade(code, "buy", row):
            continue
        fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
        if fill:
            fills.append(fill)

    return fills
```

**调用方修改**:

```python
# backtest_engine.py
from engines.rebalance_core import execute_rebalance

class SimpleBacktester:
    def _rebalance(self, broker, target, portfolio_value, exec_date, price_idx, today_close):
        return execute_rebalance(broker, target, portfolio_value, exec_date, price_idx, today_close)

# paper_broker.py
from engines.rebalance_core import execute_rebalance

class PaperBroker:
    def _do_rebalance(self, target, portfolio_value, exec_date, price_idx, today_close):
        return execute_rebalance(self.broker, target, portfolio_value, exec_date, price_idx, today_close)
```

#### 工作量估算

| 任务 | 工时 | 角色 |
|------|------|------|
| 抽取rebalance_core.py | 1h | arch |
| 修改SimpleBacktester调用 | 0.5h | arch |
| 修改PaperBroker调用 | 0.5h | arch |
| 回归测试（现有回测结果bit-identical验证） | 1h | qa |
| 集成测试（PT 5天模拟） | 1h | qa |
| 代码审查 | 0.5h | quant |
| **合计** | **4.5h** | |

#### 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|---------|
| 重构后回测结果改变 | 低 | 纯函数抽取，无逻辑变更。修改前后跑同参数回测，要求结果bit-identical |
| PT运行异常 | 低 | PT已经委托SimBroker执行，函数签名不变 |
| SimBroker状态污染 | 无 | execute_rebalance是纯函数（除了broker状态变更），与之前行为完全一致 |
| 未来需要差异化行为 | 中 | 如果回测和PT需要不同的调仓策略（如PT加滑点模型升级），可通过传入strategy参数扩展 |

#### 不建议共享的部分

以下部分**不应该**合并到共享核心中：

1. **信号生成管道**: PT额外的因子完整性检查、截面覆盖率检查、行业集中度检查是生产级防御，回测不需要。强行合并会让回测变慢且复杂。
2. **执行调度**: 回测的批量循环 vs PT的单日调度是根本架构差异，不是重复。
3. **风控熔断**: 仅PT需要，回测不做熔断。
4. **状态持久化**: 仅PT需要写DB。

### 1.4 结论与建议

**可行性: 高。** 核心调仓逻辑（_rebalance）完全可以抽取共享，工作量约4.5h，风险低。

**建议优先级: P1。** 当前两套代码行为一致（PaperBroker._do_rebalance的注释明确说"从SimpleBacktester._rebalance复制"），但随着Phase 1新增功能（滑点模型升级、部分成交处理、换手率约束增强），两条路径diverge的风险会增大。建议在Sprint 1.4尽早抽取。

**不建议过度合并**。信号生成、风控、持久化等层面的差异是合理的架构分层，不是重复代码。只需合并_rebalance这一个函数。

---

## 任务2：回测对比3基准策略设计

### 2.1 三个基准定义

#### 基准1: 沪深300买入持有（市场Beta基线）

| 项 | 规格 |
|----|------|
| 标的 | 沪深300指数 (000300.SH) |
| 选股 | 无（直接用指数收盘价） |
| 调仓 | 无（买入持有，从start_date持有到end_date） |
| 权重 | N/A |
| 数据源 | `index_daily` 表，`WHERE index_code = '000300.SH'` |
| 意义 | 市场Beta基线。策略如果跑不赢沪深300买入持有，说明没有alpha |

**数据可用性**: 已确认。`index_daily`有000300.SH数据，4509行覆盖2020-01-02至2026-03-19。`run_backtest.py`的`load_benchmark()`已实现加载。

**实现**: `BacktestResult.benchmark_nav`已经是沪深300 NAV序列，无需额外工作。

#### 基准2: 等权Top20市值最大（规模因子基线）

| 项 | 规格 |
|----|------|
| 选股 | 每个调仓日，按total_mv降序排名取Top20（排除ST/新股/停牌） |
| 调仓 | 与主策略一致（月频，每月最后一个交易日） |
| 权重 | 等权 (1/20 = 5%) |
| 行业约束 | 无（纯市值排名，不加行业上限） |
| 数据源 | `daily_basic.total_mv`（万元） |
| 意义 | 最简单的大盘股策略。如果5因子策略跑不赢它，说明alpha来自规模暴露而非因子选股能力 |

**数据可用性**: 已确认。`daily_basic`表有`total_mv`字段，7,307,433行。`load_universe()`已包含`total_mv > 100000`过滤。

**实现方案**:
```python
def build_size_benchmark(trade_date: date, conn, top_n: int = 20) -> dict[str, float]:
    """构建市值Top-N等权基准。"""
    df = pd.read_sql(
        """SELECT k.code, db.total_mv
           FROM klines_daily k
           JOIN symbols s ON k.code = s.code
           JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
           ORDER BY db.total_mv DESC
           LIMIT %s""",
        conn, params=(trade_date, trade_date, top_n),
    )
    if df.empty:
        return {}
    weight = 1.0 / len(df)
    return {row["code"]: weight for _, row in df.iterrows()}
```

#### 基准3: 等权Top20换手率最低（单因子基线）

| 项 | 规格 |
|----|------|
| 选股 | 每个调仓日，按turnover_rate_20d均值升序排名取Top20（排除ST/新股/停牌/微市值） |
| 调仓 | 与主策略一致（月频） |
| 权重 | 等权 (1/20 = 5%) |
| 行业约束 | 无 |
| 数据源 | `factor_values.neutral_value WHERE factor_name = 'turnover_mean_20'`，或直接从`daily_basic.turnover_rate`计算20日均值 |
| 意义 | turnover_mean_20是v1.1基线的IC最高因子(4.55%)。如果5因子组合跑不赢单因子，说明其他4个因子是噪音或相互抵消 |

**数据可用性**: 两条路径均可：
1. `factor_values`表有`turnover_mean_20`的`neutral_value`（中性化后）—— 推荐，与主策略对齐
2. `daily_basic.turnover_rate`原始数据 —— 备选

**推荐用factor_values**: 这样基准也经过了中性化处理，与主策略的因子处理一致，对比更公平。

**实现方案**:
```python
def build_turnover_benchmark(trade_date: date, conn, top_n: int = 20) -> dict[str, float]:
    """构建低换手率单因子等权基准。"""
    # 用中性化后的turnover_mean_20，方向为-1（低换手好）
    fv = pd.read_sql(
        """SELECT fv.code, fv.neutral_value
           FROM factor_values fv
           JOIN symbols s ON fv.code = s.code
           JOIN klines_daily k ON fv.code = k.code AND fv.trade_date = k.trade_date
           WHERE fv.trade_date = %s
             AND fv.factor_name = 'turnover_mean_20'
             AND k.volume > 0
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= %s - INTERVAL '60 days')
           ORDER BY fv.neutral_value ASC
           LIMIT %s""",
        conn, params=(trade_date, trade_date, top_n),
    )
    if fv.empty:
        return {}
    weight = 1.0 / len(fv)
    return {row["code"]: weight for _, row in fv.iterrows()}
```

### 2.2 对比输出格式设计

#### 2.2.1 主表：核心指标对比

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    QuantMind V2 策略 vs 基准对比报告                         ║
║                    回测区间: 2021-01-01 ~ 2025-12-31                        ║
╠══════════════════╦══════════╦══════════╦══════════╦══════════════════════════╣
║ 指标             ║ 5因子v1.1 ║ CSI300   ║ 大盘Top20 ║ 低换手Top20            ║
╠══════════════════╬══════════╬══════════╬══════════╬══════════════════════════╣
║ 年化收益         ║  15.2%   ║   3.1%   ║   8.7%   ║  12.3%                 ║
║ 累计收益         ║  98.5%   ║  16.4%   ║  51.2%   ║  78.1%                 ║
║ Sharpe           ║   1.037  ║   0.21   ║   0.58   ║   0.82                 ║
║ MDD              ║ -39.7%   ║ -45.2%   ║ -38.1%   ║ -35.6%                ║
║ Calmar           ║   0.38   ║   0.07   ║   0.23   ║   0.35                 ║
║ Sortino          ║   1.52   ║   0.30   ║   0.84   ║   1.18                 ║
║ Beta             ║   0.28   ║   1.00   ║   0.85   ║   0.35                 ║
║ IR               ║   0.72   ║    —     ║   0.31   ║   0.55                 ║
║ 年化换手率       ║  320%    ║    0%    ║  180%    ║  250%                  ║
║ Bootstrap CI     ║[0.43,1.98]║[-0.3,0.7]║[0.1,1.1] ║[0.3,1.4]             ║
╚══════════════════╩══════════╩══════════╩══════════╩══════════════════════════╝
```

#### 2.2.2 年度分解对比表

```
╔═════╦═════════════════════════╦═════════════════════════╦═════════════════════════╦═════════════════════════╗
║ 年份 ║ 5因子v1.1               ║ CSI300                  ║ 大盘Top20               ║ 低换手Top20             ║
║     ║ 收益  Sharpe  MDD       ║ 收益  Sharpe  MDD       ║ 收益  Sharpe  MDD       ║ 收益  Sharpe  MDD       ║
╠═════╬═════════════════════════╬═════════════════════════╬═════════════════════════╬═════════════════════════╣
║ 2021║ +18%  1.21  -15%       ║  -5%  -0.35 -22%       ║ +12%  0.80  -18%       ║ +15%  1.02  -12%       ║
║ 2022║  -8%  -0.52 -39%       ║ -22%  -1.50 -45%       ║ -15%  -1.02 -38%       ║  -5%  -0.32 -35%       ║
║ 2023║ +22%  1.45  -12%       ║  -1%  -0.07 -18%       ║ +10%  0.65  -15%       ║ +18%  1.20  -10%       ║
║ 2024║ +25%  1.68  -10%       ║ +15%  1.00  -12%       ║ +20%  1.35  -10%       ║ +22%  1.48   -8%       ║
║ 2025║ +12%  0.80  -18%       ║  +8%  0.55  -15%       ║  +5%  0.33  -20%       ║  +9%  0.60  -16%       ║
╚═════╩═════════════════════════╩═════════════════════════╩═════════════════════════╩═════════════════════════╝
最差年度标红(实际代码中用ANSI color或HTML highlight)
```

#### 2.2.3 超额收益分解

```
超额收益分解（相对沪深300）:
╔══════════════════╦══════════╦══════════╦══════════╗
║                  ║ 5因子v1.1 ║ 大盘Top20 ║ 低换手Top20 ║
╠══════════════════╬══════════╬══════════╬══════════╣
║ 年化超额收益     ║  +12.1%  ║   +5.6%  ║   +9.2%  ║
║ 超额Sharpe       ║   0.85   ║   0.38   ║   0.63   ║
║ 超额MDD          ║ -25.3%   ║ -18.7%   ║ -22.1%   ║
║ 跟踪误差(TE)     ║  14.2%   ║   6.6%   ║  14.6%   ║
╚══════════════════╩══════════╩══════════╩══════════╝
```

### 2.3 在现有run_backtest.py框架中实现的可行性

**结论: 完全可行。** 原因：

1. `SimpleBacktester.run()` 接受 `target_portfolios: dict[date, dict[str, float]]` 作为输入。三个基准都可以生成相同格式的target_portfolios。

2. `SimBroker` 的整手约束、涨跌停检测、滑点模型对基准同样适用（确保对比公平——基准也经历相同的交易摩擦）。

3. `generate_report()` 接受 `BacktestResult` 生成绩效报告，可以对4个策略分别生成后汇总对比。

**实现方案**:

```python
# 在run_backtest.py中新增:

def run_benchmark_backtest(
    benchmark_name: str,
    portfolio_builder_fn,   # Callable[[date, conn], dict[str, float]]
    rebalance_dates: list[date],
    price_data: pd.DataFrame,
    benchmark_data: pd.DataFrame,
    bt_config: BacktestConfig,
    conn,
) -> BacktestResult:
    """运行基准策略回测。"""
    target_portfolios = {}
    for rd in rebalance_dates:
        target = portfolio_builder_fn(rd, conn)
        if target:
            target_portfolios[rd] = target

    backtester = SimpleBacktester(bt_config)
    return backtester.run(target_portfolios, price_data, benchmark_data)


def print_comparison_report(
    main_result: BacktestResult,
    main_report: PerformanceReport,
    benchmarks: dict[str, tuple[BacktestResult, PerformanceReport]],
):
    """打印策略 vs 基准对比报告。"""
    # 实现上面2.2节的表格格式
    ...
```

**注意事项**:
- 基准1（CSI300买入持有）不需要跑SimBroker回测，直接用index_daily收盘价序列即可（已有`benchmark_nav`）
- 基准2和基准3需要跑完整的SimBroker回测（确保整手约束、交易成本对比公平）
- 基准2和基准3**不加行业约束**（纯规模/纯单因子基线，加约束会模糊对比意义）
- 基准2和基准3的调仓频率与主策略一致（月频），确保换手成本可比

### 2.4 工作量估算

| 任务 | 工时 | 角色 |
|------|------|------|
| build_size_benchmark() | 0.5h | arch |
| build_turnover_benchmark() | 0.5h | arch |
| run_benchmark_backtest() 框架 | 1h | arch |
| print_comparison_report() 格式化输出 | 1.5h | arch |
| 集成到run_backtest.py --benchmarks 参数 | 0.5h | arch |
| 验证3个基准回测结果合理性 | 1h | quant |
| 测试 | 1h | qa |
| **合计** | **6h** | |

### 2.5 CLI设计

```bash
# 默认: 只跑5因子策略
python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31

# 加3个基准对比
python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31 --benchmarks

# 指定某个基准
python scripts/run_backtest.py --start 2021-01-01 --end 2025-12-31 --benchmarks size,turnover
```

---

## 附录: 与LL-010的关系

LL-010指出"两套代码路径用不同默认配置导致Sharpe误诊"。本设计的两个任务都与此相关：

- **任务1（共享核心）**: 从源头消灭调仓逻辑的代码重复，确保"修一处=改两处"
- **任务2（基准对比）**: 所有基准策略都通过同一个`SimpleBacktester`执行，确保交易摩擦建模一致

两个任务合计工时约10.5h，建议Sprint 1.4由arch主导实现。
