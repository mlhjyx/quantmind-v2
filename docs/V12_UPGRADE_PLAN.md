# V1.2 升级方案：因子扩展回测 + 封板补单设计

> **作者**: strategy (策略研究员)
> **日期**: 2026-03-23
> **状态**: 方案设计，待arch/quant实现
> **前置依赖**: alpha_miner已完成mf_momentum_divergence IC验证(9.1%)，V12_CONFIG已在signal_engine.py中定义

---

## 目录

1. [任务1: v1.2因子升级SimBroker回测方案](#任务1-v12因子升级simbroker回测方案)
2. [任务2: 封板补单方案详细设计](#任务2-封板补单方案详细设计)

---

## 任务1: v1.2因子升级SimBroker回测方案

### 1.1 变更概述

| 项目 | v1.1 (当前Paper Trading) | v1.2 (候选) |
|------|--------------------------|-------------|
| 因子数 | 5 | 6 |
| 因子列表 | turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio | 同左 + **mf_momentum_divergence** |
| Top-N | 15 | 15 |
| 调仓频率 | 月频 | 月频 |
| 行业约束 | IndCap=25% | IndCap=25% |
| 合成方式 | 等权 | 等权 |
| 换手率上限 | 50%/次 | 50%/次 |

**新增因子说明**:
- `mf_momentum_divergence`: 资金流-价格背离因子，IC=9.1%
- 方向: -1（值越负=背离越大=信号越强）
- 维度: 资金流，与基线5因子（价量3+规模0+估值1）无概念重叠
- 已在`signal_engine.py`中定义为`V12_CONFIG`

### 1.2 回测配置

```python
# 复用已有V12_CONFIG，仅需指定回测参数
backtest_config = BacktestConfig(
    initial_capital=1_000_000.0,
    top_n=15,
    rebalance_freq="monthly",
    slippage_bps=10.0,
    commission_rate=0.00015,    # 佣金万1.5
    stamp_tax_rate=0.0005,      # 印花税千0.5(仅卖出)
    transfer_fee_rate=0.00001,  # 过户费万0.1
    lot_size=100,
    turnover_cap=0.50,
    benchmark_code="000300.SH",
)
```

| 回测参数 | 值 | 说明 |
|---------|-----|------|
| 区间 | 2021-01-01 ~ 2025-12-31 | 5年，与v1.1基线Sharpe=1.037的计算区间一致 |
| 引擎 | SimpleBacktester + SimBroker | 含涨跌停封板/整手约束/资金T+1/滑点 |
| 因子预处理 | MAD去极值 -> 缺失值填充 -> 中性化 -> zscore | 严格按CLAUDE.md顺序 |
| 信号合成 | V12_CONFIG (6因子等权) | signal_engine.py已定义 |
| Universe | 全A股(排除ST/新股60天/停牌/总市值<10亿) | 与v1.1一致 |
| 基准 | 沪深300 | 超额收益基准 |

### 1.3 执行脚本方案

复用现有`scripts/run_backtest.py`框架，新建`scripts/backtest_v12_comparison.py`:

```python
#!/usr/bin/env python3
"""v1.1 vs v1.2 因子升级对比回测。

用法:
    python scripts/backtest_v12_comparison.py

输出:
    1. v1.1回测结果 (5因子)
    2. v1.2回测结果 (6因子)
    3. 对比报告 (Sharpe/MDD/年度分解/bootstrap检验)
"""

# 核心逻辑:
# 1. 用PAPER_TRADING_CONFIG跑v1.1
# 2. 用V12_CONFIG跑v1.2
# 3. 两次回测共享完全相同的price_data/benchmark_data/universe
# 4. 对比输出
```

**关键实现要求**:
- v1.1和v1.2必须使用**完全相同的price_data和universe**，确保差异仅来自因子
- mf_momentum_divergence的factor_values必须在回测前已写入DB（或从Parquet加载）
- 两次回测使用**独立的SimBroker实例**（不共享状态）

### 1.4 对比指标清单

#### A. 核心指标对比表

| 指标 | v1.1 | v1.2 | 差异 | 判定 |
|------|------|------|------|------|
| 年化收益率 | | | | |
| Sharpe Ratio | 1.037(已知) | | | v1.2 > v1.1? |
| Max Drawdown | -39.7%(已知) | | | v1.2 MDD更小? |
| Calmar Ratio | | | | |
| Sortino Ratio | | | | |
| 年化换手率 | | | | v1.2不应显著高于v1.1 |
| Bootstrap Sharpe 95%CI | | | | CI重叠程度 |

#### B. 年度分解

| 年份 | v1.1收益 | v1.2收益 | v1.1 Sharpe | v1.2 Sharpe | 赢家 |
|------|---------|---------|-------------|-------------|------|
| 2021 | | | | | |
| 2022 | | | | | |
| 2023 | | | | | |
| 2024 | | | | | |
| 2025 | | | | | |

**重点关注**: v1.1最差年份（预期2022或2024），v1.2是否有改善。因子分散化的主要收益应体现在最差年度的MDD降低，而非最好年度的收益提升。

#### C. 风格暴露对比

- 日收益率相关性: corr(v1.1_daily_ret, v1.2_daily_ret)
  - 预期 > 0.85（因为5/6因子相同）
  - 如果 < 0.7 需要检查mf_momentum_divergence是否过度影响选股
- 持仓重叠度: 每个调仓日，v1.1和v1.2的持仓交集/并集
  - 预期 > 60%（大部分持仓相同）
- 新增因子对选股的边际影响: v1.2独有持仓的平均mf_momentum_divergence排名

### 1.5 Gate标准（v1.2是否通过）

#### Gate 1: Sharpe不退化（必须通过）

```
条件: v1.2_Sharpe >= v1.1_Sharpe * 0.95
即:   v1.2_Sharpe >= 1.037 * 0.95 = 0.985
```

**理由**: 6因子等权下单因子权重从20%降到16.7%，Sharpe可能因为分散化略降，但不应低于5%。低于0.985说明新因子有负面影响。

#### Gate 2: Bootstrap显著性检验（建议通过）

```python
# Bootstrap检验: v1.2 Sharpe是否显著优于v1.1
def bootstrap_sharpe_diff(ret_v11, ret_v12, n_bootstrap=5000):
    """
    H0: Sharpe(v1.2) <= Sharpe(v1.1)
    H1: Sharpe(v1.2) > Sharpe(v1.1)

    方法: 对(ret_v12 - ret_v11)的日收益差做bootstrap
    如果差值Sharpe的95%CI下界 > 0，则v1.2显著优于v1.1
    """
    diff = ret_v12 - ret_v11
    n = len(diff)
    sharpe_diffs = []
    for _ in range(n_bootstrap):
        sample = np.random.choice(diff, size=n, replace=True)
        sharpe_diffs.append(sample.mean() / sample.std() * np.sqrt(252))

    ci_low = np.percentile(sharpe_diffs, 5)
    ci_high = np.percentile(sharpe_diffs, 95)
    p_value = np.mean(np.array(sharpe_diffs) <= 0)

    return {
        "sharpe_diff_mean": np.mean(sharpe_diffs),
        "ci_90": (ci_low, ci_high),
        "p_value": p_value,
        "significant": ci_low > 0,  # 单侧检验
    }
```

**判定规则**:
- `significant == True` (p < 0.05): v1.2显著优于v1.1 -> 强烈建议升级
- `p_value < 0.20` 且 Gate 1通过: v1.2略优但不显著 -> 建议升级（分散化收益）
- `p_value >= 0.20` 且 Gate 1通过: v1.2与v1.1无差异 -> 仍可升级（新维度有保险价值）
- Gate 1未通过: 不升级，v1.2因子组合有问题

#### Gate 3: MDD改善（加分项）

```
条件: v1.2_MDD < v1.1_MDD (即绝对值更小)
即:   |v1.2_MDD| < 39.7%
```

这是因子分散化的核心预期收益。如果MDD未改善，说明mf_momentum_divergence与基线因子在极端行情下的保护作用有限。

#### Gate 4: 最差年度不恶化（安全阈值）

```
条件: v1.2在v1.1最差年份的收益 >= v1.1该年收益 * 0.85
```

如果v1.2在最差年份比v1.1更差15%以上，即使总体Sharpe更高，也需要审慎评估。

### 1.6 升级决策矩阵

| Gate 1 | Gate 2 | Gate 3 | Gate 4 | 决策 |
|--------|--------|--------|--------|------|
| PASS | Significant | PASS | PASS | **升级v1.2，Paper Trading重新计时60天** |
| PASS | Not significant | PASS | PASS | **升级v1.2**（分散化+MDD改善值得60天代价） |
| PASS | Not significant | FAIL | PASS | 不升级，保持v1.1（MDD未改善=新因子无保险价值） |
| PASS | Any | Any | FAIL | 不升级，最差年度恶化风险太高 |
| FAIL | Any | Any | Any | **不升级**，v1.2退化 |

### 1.7 Paper Trading升级代价评估

**升级代价**: Paper Trading 60天重新计时（CLAUDE.md强制）

**当前状态**: v1.1于2026-03-23启动Paper Trading

**成本-收益分析**:
- 如果现在升级(假设回测需1-2天，即3月25日切换): 新的60天从3月25日算起，约5月底毕业
- 如果不升级: 继续v1.1，5月中旬毕业（3月23日+60交易日）
- 差异: 约2周延迟

**建议**: 如果Gate 1+3+4全部通过，即使Gate 2未达显著性，也建议升级。理由:
1. 2周延迟 vs 更分散化的因子组合，后者对实盘运行更重要
2. v1.1才刚启动Paper Trading（第1天），沉没成本几乎为零
3. 越早切换越好，拖到v1.1 Paper Trading跑了30天再切换，代价更大

**如果v1.1已跑超过20个交易日**: 除非Gate 2显著，否则不建议中途切换（沉没成本过高）。

### 1.8 实施步骤

```
Step 1: [arch/quant] 确认mf_momentum_divergence的factor_values已入库(2021-2025全量)
Step 2: [arch/quant] 新建scripts/backtest_v12_comparison.py
Step 3: [arch/quant] 跑v1.1回测(验证Sharpe=1.037可复现)
Step 4: [arch/quant] 跑v1.2回测
Step 5: [strategy] 评估Gate 1-4，写入结论到STRATEGY_CANDIDATES.md
Step 6: [用户决策] 是否升级Paper Trading
Step 7: [如升级] 更新PAPER_TRADING_CONFIG -> V12_CONFIG，param_change_log记录变更
```

---

## 任务2: 封板补单方案详细设计

### 2.1 问题背景

当前SimBroker在调仓日执行时，如果目标股票涨停封板（`can_trade()`返回False），该买入指令被**直接丢弃**。这导致:

1. 目标持仓无法达成，实际仓位偏离目标
2. 现金比例被动升高（本应买入的资金闲置）
3. 涨停封板的股票往往是最强信号股（排名靠前），丢弃它们损失最大

**历史研究结论**: 在5个执行优化方向中，封板未成交补单是唯一值得实现的:
- 分笔成交建模: 计算复杂，对月频策略收益<0.1%，不值得
- TWAP/VWAP拆单: 月频策略单次调仓金额小，无需
- 滑点动态调整: Phase 1再做
- 部分成交建模: 已有整手约束，额外收益极小
- **封板补单: 值得做**，约3-5%的调仓日会遇到封板，Top-15中通常1-2只

### 2.2 补单规则设计

#### 核心规则

| 规则 | 值 | 理由 |
|------|-----|------|
| 补单次数 | 仅1次 | 连续封板2天以上=市场极端,不追 |
| 补单时机 | T+1日（原执行日的下一个交易日）开盘 | SimBroker用开盘价成交 |
| 补单条件 | T+1日该股票`can_trade("buy")==True` | 如果T+1日仍封板,放弃 |
| 补单金额 | 原目标金额（按T+1日组合市值重算权重） | 不用T日的旧金额 |
| 补单上限 | 单只补单金额 <= 组合市值 * 10% | 防止单只过度集中 |
| 补单数量 | 单次调仓最多补3只 | 超过3只封板说明极端行情,不追 |
| 资金来源 | 使用闲置现金（调仓日封板未买入的部分） | 不卖出已有持仓来腾资金 |

#### 补单不执行的情况

1. T+1日该股票仍然涨停封板 -> 放弃，不再重试
2. T+1日该股票停牌 -> 放弃
3. 闲置现金不足以买入1手(100股) -> 放弃
4. 距离下次调仓日 <= 5个交易日 -> 放弃（即将调仓，补单无意义）
5. 补单数量已达3只上限 -> 按原始score降序，只补前3只

### 2.3 pending_orders表结构

```sql
-- 封板未成交补单队列
-- 不是DDL_FINAL.sql的一部分（回测引擎内部数据结构），
-- 但Paper Trading/实盘时需要持久化
CREATE TABLE pending_orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(10) NOT NULL,
    signal_date     DATE NOT NULL,           -- 原始信号日
    exec_date       DATE NOT NULL,           -- 原定执行日（封板发生日）
    retry_date      DATE,                    -- 补单执行日（T+1）
    strategy_id     UUID,
    direction       VARCHAR(4) NOT NULL DEFAULT 'buy',  -- 目前仅支持买入补单
    target_weight   DECIMAL(8,6) NOT NULL,   -- 目标权重
    target_amount   DECIMAL(16,2),           -- 目标金额（按retry_date组合市值重算）
    filled_shares   INT DEFAULT 0,           -- 实际成交股数
    filled_amount   DECIMAL(16,2) DEFAULT 0, -- 实际成交金额
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
        -- pending: 等待补单
        -- filled: 补单成功
        -- cancelled: 放弃（T+1仍封板/停牌/资金不足/距调仓日太近）
        -- expired: 超时未处理
    cancel_reason   VARCHAR(100),            -- 取消原因
    original_score  DECIMAL(12,6),           -- 原始composite score（用于排序）
    execution_mode  VARCHAR(10) DEFAULT 'paper',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pending_orders_status ON pending_orders(status, retry_date);
CREATE INDEX idx_pending_orders_date ON pending_orders(exec_date, strategy_id);

COMMENT ON TABLE pending_orders IS '封板未成交补单队列。仅买入方向。每个订单最多重试1次。';
```

**注意**: 在回测引擎(SimpleBacktester)中，pending_orders不需要写入DB，用内存中的list[dict]即可。仅Paper Trading和实盘需要持久化到DB。

### 2.4 SimBroker集成方案

#### 2.4.1 数据结构（回测引擎内部）

```python
@dataclass
class PendingOrder:
    """封板未成交的补单记录（回测引擎内部使用）。"""
    code: str
    signal_date: date
    exec_date: date          # 封板发生日
    target_weight: float     # 目标权重
    original_score: float    # 原始composite score（排序用）
    direction: str = "buy"
    status: str = "pending"  # pending / filled / cancelled
    cancel_reason: str = ""
```

#### 2.4.2 SimpleBacktester修改

在现有`SimpleBacktester.run()`的主循环中，增加补单处理逻辑:

```python
class SimpleBacktester:
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.pending_orders: list[PendingOrder] = []  # 新增
        self.max_retry_orders = 3                      # 单次调仓最多补3只
        self.retry_weight_cap = 0.10                   # 单只补单上限10%
        self.min_days_to_next_rebal = 5                # 距下次调仓<5天不补

    def run(self, target_portfolios, price_data, benchmark_data=None):
        broker = SimBroker(self.config)
        # ... 现有准备逻辑 ...

        for i, td in enumerate(all_dates):
            broker.new_day()

            # ===== 新增: 处理补单 =====
            if self.pending_orders:
                self._process_pending_orders(
                    broker, td, price_idx, daily_close.get(td, {}),
                    all_dates, exec_map, trades
                )

            # ===== 现有: 调仓日处理 =====
            if td in exec_map:
                signal_date = exec_map[td]
                target = target_portfolios[signal_date]
                portfolio_value = broker.get_portfolio_value(daily_close.get(td, {}))

                day_fills, new_pending = self._rebalance_with_pending(
                    broker, target, portfolio_value, td,
                    price_idx, daily_close.get(td, {}),
                    signal_date,
                    # 传入composite scores用于pending排序
                )
                trades.extend(day_fills)
                self.pending_orders.extend(new_pending)

            # 每日NAV
            prices = daily_close.get(td, {})
            nav_series[td] = broker.get_portfolio_value(prices)

        # ... 现有结果转换 ...
```

#### 2.4.3 _rebalance_with_pending（修改自现有_rebalance）

```python
def _rebalance_with_pending(
    self, broker, target, portfolio_value, exec_date,
    price_idx, today_close, signal_date
) -> tuple[list[Fill], list[PendingOrder]]:
    """执行调仓，记录封板未成交为pending_orders。"""
    fills = []
    new_pending = []

    # 1. 计算目标持仓股数（与现有逻辑相同）
    target_shares = {}
    for code, weight in target.items():
        close_price = today_close.get(code, 0)
        if close_price > 0:
            target_value = portfolio_value * weight
            shares = int(target_value / close_price / self.config.lot_size) * self.config.lot_size
            if shares > 0:
                target_shares[code] = shares

    # 2. 卖出（与现有逻辑相同）
    sell_codes = []
    for code, curr_shares in list(broker.holdings.items()):
        target_s = target_shares.get(code, 0)
        if curr_shares > target_s:
            sell_codes.append((code, curr_shares - target_s))

    for code, sell_shares in sell_codes:
        row = price_idx.get((code, exec_date))
        if row is None:
            continue
        if not broker.can_trade(code, "sell", row):
            continue
        fill = broker.execute_sell(code, sell_shares, row)
        if fill:
            fills.append(fill)

    # 3. 买入（修改: 记录封板为pending）
    buy_orders = []
    for code, target_s in target_shares.items():
        curr_shares = broker.holdings.get(code, 0)
        if target_s > curr_shares:
            buy_amount = (target_s - curr_shares) * today_close.get(code, 0)
            weight = target.get(code, 0)
            buy_orders.append((code, buy_amount, weight))

    buy_orders.sort(key=lambda x: -x[1])

    for code, buy_amount, weight in buy_orders:
        if broker.cash < buy_amount * 0.1:
            break
        row = price_idx.get((code, exec_date))
        if row is None:
            continue

        if not broker.can_trade(code, "buy", row):
            # ===== 封板: 记录为pending_order =====
            logger.debug(f"[{exec_date}] {code} 买入封板，加入补单队列")
            new_pending.append(PendingOrder(
                code=code,
                signal_date=signal_date,
                exec_date=exec_date,
                target_weight=weight,
                original_score=weight,  # 等权下weight相同，用buy_amount排序
            ))
            continue

        fill = broker.execute_buy(code, min(buy_amount, broker.cash), row)
        if fill:
            fills.append(fill)

    return fills, new_pending
```

#### 2.4.4 _process_pending_orders（新增方法）

```python
def _process_pending_orders(
    self, broker, today, price_idx, today_close,
    all_dates, exec_map, trades_list
):
    """处理封板补单。T+1日尝试买入。"""
    # 清理已过期的pending（不是T+1日的）
    actionable = []
    for po in self.pending_orders:
        if po.status != "pending":
            continue

        # 找到exec_date的下一个交易日
        retry_date = None
        for d in all_dates:
            if d > po.exec_date:
                retry_date = d
                break

        if retry_date is None or retry_date != today:
            # 不是今天该处理的，或者已经过了retry_date
            if retry_date is not None and today > retry_date:
                po.status = "cancelled"
                po.cancel_reason = "expired"
            continue

        # 检查距下次调仓是否太近
        next_rebal_dates = [d for d in exec_map.keys() if d > today]
        if next_rebal_dates:
            days_to_next = all_dates.index(next_rebal_dates[0]) - all_dates.index(today)
            if days_to_next <= self.min_days_to_next_rebal:
                po.status = "cancelled"
                po.cancel_reason = f"too_close_to_next_rebalance({days_to_next}d)"
                continue

        actionable.append(po)

    # 按original_score降序，最多补3只
    actionable.sort(key=lambda x: -x.original_score)
    actionable = actionable[:self.max_retry_orders]

    for po in actionable:
        row = price_idx.get((po.code, today))
        if row is None:
            po.status = "cancelled"
            po.cancel_reason = "no_price_data"
            continue

        if not broker.can_trade(po.code, "buy", row):
            po.status = "cancelled"
            po.cancel_reason = "still_limit_up_or_suspended"
            continue

        # 按当前组合市值重算目标金额
        portfolio_value = broker.get_portfolio_value(today_close)
        target_amount = portfolio_value * min(po.target_weight, self.retry_weight_cap)

        if target_amount < row["open"] * self.config.lot_size:
            po.status = "cancelled"
            po.cancel_reason = "insufficient_for_one_lot"
            continue

        fill = broker.execute_buy(po.code, min(target_amount, broker.cash), row)
        if fill:
            trades_list.append(fill)
            po.status = "filled"
        else:
            po.status = "cancelled"
            po.cancel_reason = "insufficient_cash"

    # 超出3只上限的标记取消
    for po in self.pending_orders:
        if po.status == "pending" and po not in actionable:
            # 检查是否今天该处理但被数量限制
            retry_date = None
            for d in all_dates:
                if d > po.exec_date:
                    retry_date = d
                    break
            if retry_date == today:
                po.status = "cancelled"
                po.cancel_reason = "exceeded_max_retry_count"
```

### 2.5 补单统计指标（加入回测报告）

在BacktestResult中新增或在generate_report中新增以下统计:

```python
@dataclass
class PendingOrderStats:
    """补单统计。"""
    total_pending: int          # 总封板次数
    filled_count: int           # 补单成功次数
    cancelled_count: int        # 放弃次数
    fill_rate: float            # 补单成功率 = filled / total
    avg_retry_return_1d: float  # 补单股票T+1日平均涨幅（衡量追涨风险）
    cancel_reasons: dict        # {reason: count}
```

**关键监控指标**:
- `avg_retry_return_1d`: 如果补单股票在补单日(T+1)普遍高开（>2%），说明补单在"追涨"，需要降低retry_weight_cap
- `fill_rate`: 如果>80%，说明大部分封板次日打开，补单机制有效；如果<30%，说明连续封板多，机制收益有限

### 2.6 风控约束汇总

| 约束 | 值 | 机制 |
|------|-----|------|
| 单只补单金额上限 | 组合市值 * 10% | `retry_weight_cap = 0.10` |
| 单次调仓最大补单数 | 3只 | `max_retry_orders = 3` |
| 补单重试次数 | 仅1次 | T+1日不成功即放弃 |
| 距下次调仓最小间隔 | 5个交易日 | `min_days_to_next_rebal = 5` |
| 资金来源 | 仅用闲置现金 | 不卖出现有持仓 |
| 补单方向 | 仅买入 | 卖出跌停封板不补单(月频调仓下几乎不影响) |

**卖出不补单的理由**: 跌停封板的卖出在月频策略中极少发生（持仓已过中性化，不太会出现连续跌停），且强制卖出跌停股可能恰好卖在最低点。如果需要卖出的股票跌停，保持持仓到下个月再处理更安全。

### 2.7 Paper Trading / 实盘集成

#### Paper Trading模式（paper_broker.py）

```python
class PaperBroker:
    """Paper Trading的封板补单集成。"""

    async def check_and_retry_pending_orders(self, trade_date: date):
        """每日盘前检查pending_orders表。

        调度时机: T+1日 08:30（在正常调仓确认之前）
        """
        pending = await self.db.fetch_all(
            "SELECT * FROM pending_orders WHERE status='pending' AND retry_date=%s",
            trade_date
        )

        for order in pending:
            # 检查是否可交易
            can = await self.can_trade(order.code, "buy", trade_date)
            if not can:
                await self.update_pending_status(order.id, "cancelled", "still_limit_up")
                continue

            # 重算目标金额
            portfolio_value = await self.get_portfolio_value(trade_date)
            target_amount = portfolio_value * min(order.target_weight, 0.10)

            # 执行补单
            fill = await self.execute_buy(order.code, target_amount, trade_date)
            if fill:
                await self.update_pending_status(order.id, "filled")
            else:
                await self.update_pending_status(order.id, "cancelled", "insufficient_cash")
```

#### 调度集成

```
T日 17:20  信号生成 + 调仓指令
T日 17:30  通知推送
T+1日 08:30  补单检查（新增步骤）
  → 查pending_orders表
  → 检查封板是否打开
  → 执行补单 / 标记取消
T+1日 08:40  正常调仓确认 + 补单结果一并确认
T+1日 09:30  开盘执行（正常调仓 + 补单一起执行）
```

### 2.8 实施优先级

| 优先级 | 任务 | 角色 | 依赖 |
|--------|------|------|------|
| **P0** | 在SimpleBacktester中实现PendingOrder内存逻辑 | arch/quant | 无 |
| **P0** | 跑v1.1 with/without补单对比，量化补单收益 | strategy | 上一步 |
| P1 | pending_orders表建表(DDL) | arch | 无 |
| P1 | paper_broker.py集成补单逻辑 | arch | DDL |
| P2 | 补单统计指标加入回测报告 | quant | SimpleBacktester |

**预期收益**: 基于历史数据估算，月频调仓约3-5%的调仓日会有1-2只股票封板。补单成功率预期60-70%（次日大多数封板会打开）。对年化收益的边际贡献预计0.3-0.8%。收益不大但实现成本低（约半天工作量），且提高了策略对目标持仓的跟踪精度。

---

## 附录: 检查清单

### v1.2回测执行前检查

- [ ] mf_momentum_divergence factor_values已入库，覆盖2021-2025
- [ ] 确认mf_momentum_divergence的方向为-1（signal_engine.py FACTOR_DIRECTIONS）
- [ ] 确认V12_CONFIG的6个因子名称与factor_values表中的factor_name完全匹配
- [ ] 先单独跑v1.1验证Sharpe=1.037可复现（±0.01以内）
- [ ] price_data包含up_limit/down_limit/turnover_rate（SimBroker封板检测需要）

### 封板补单实现前检查

- [ ] 确认现有`_rebalance()`的封板丢弃逻辑位置（backtest_engine.py L433-434）
- [ ] 确认`can_trade()`返回False的所有情况都适用于补单（不只是涨停，还有停牌）
- [ ] 补单逻辑不影响现有回测的确定性（相同输入→相同输出）
- [ ] 补单统计在回测报告中有独立section
