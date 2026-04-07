# Backtest Engine Hardening Plan

> **决策日期**: 2026-04-07
> **决策**: 加固自建Hybrid引擎 + 选择性集成Qlib组件（不整体迁移）
> **目标**: 回测结果严谨可信、分析专业完整、执行高效、架构可扩展
> **关联**: DEV_BACKTEST_ENGINE.md / ROADMAP_V3 K4/I5/H0 / CLAUDE.md铁律

---

## 1. 决策背景

### 1.1 审计触发

2026-04-07回测脚本`backtest_vwap_bias_weekly.py`出现**0成交bug**：`SimBroker.can_trade()`
因SQL查询遗漏`pre_close`字段而静默返回False，回测跑完全绿但0笔交易、NAV不变。
无任何报错。这暴露了自建引擎的系统性风险。

### 1.2 全面审计

三路并行审计：
1. **代码审计**(architect agent): 逐文件分析backtest_engine.py(981行)、vectorized_signal.py(145行)、slippage_model.py(383行)、datafeed.py(277行)、9个测试文件
2. **Qlib源码研究**: Exchange/Executor/Strategy/Position/Alpha158/risk_analysis深度分析
3. **RQAlpha/QUANTAXIS/vectorbt研究**: A股规则处理、Validator链、Deflated Sharpe、性能优化

### 1.3 核心结论

**不迁移到Qlib的原因**：

| 能力 | Qlib实际状态 | 我们的引擎 |
|------|------------|-----------|
| A股T+1 | 无内置，需自己在Position实现 | ✅ 已实现 |
| 涨跌停封板 | 简单`$change >= threshold`，无板块差异化 | ✅ 四板块差异化(10%/20%/20%/30%) |
| 100股整手 | 有`trade_unit`但无板块差异化 | ✅ 已实现 |
| 三因素滑点 | 简单二次方impact | ✅ Bouchaud 2018 + overnight_gap |
| PMS利润保护 | 无 | ✅ 3层阶梯 |
| 封板补单 | 无 | ✅ T+1重试 |
| 自定义成本模型 | 需override私有方法，版本升级会break | ✅ 完全控制 |
| 分红除权 | 也没有，靠数据层 | ❌ 也没有 |

**Qlib真正值得集成的组件**：
- Alpha158因子集（158个量价因子，对标我们63因子）
- 40+ ML模型库（TRA/ALSTM/Localformer, 通过StaticDataLoader集成）
- NestedExecutor设计模式（Stage 4 CompositeSignalEngine前置）
- risk_analysis()指标库

---

## 2. 审计发现：17项问题

### 2.1 影响回测准确性（🔴 静默偏差）

| # | 问题 | 代码位置 | 影响量化 | 验证方法 |
|---|------|---------|---------|---------|
| P1 | **缺少分红除权处理** | SimBroker日循环无ex_date检测 | 5年累计少算~10%收益(A股平均股息率~2%/年)，持有高股息股(银行/煤炭)时alpha被低估 | 对比持有高股息股有无分红的NAV差异 |
| P2 | **缺少送股/拆股处理** | SimBroker无stock split逻辑 | 持仓股10送10后holdings数量未翻倍，相当于丢失一半仓位。RQAlpha用Decimal精度处理 | 构造已知送股案例验证holdings调整 |
| P3 | **印花税率未区分历史期** | `backtest_engine.py:309` 固定0.05% | 2023-08-28前印花税实际0.1%，2021-2023回测期间成本低估~50% | 2022全年回测，对比0.05% vs 0.1%的Sharpe差异 |
| P4 | **缺少最低佣金5元/笔** | `execute_buy/sell`无min_cost | 小仓位(~5000元)佣金0.43元vs实际5元(12倍差)。20只持仓每月少算~90元 | 统计20只持仓中<1万元仓位的比例 |
| P5 | **overnight_gap滑点是死代码** | `slippage_model.py:119-167`已实现，`SimBroker.calc_slippage:275`未调用 | R4验证10-15bps/笔，月度换手~50%→年化少算~60-90bps，等于研究成果浪费 | grep确认`overnight_gap_cost`在backtest_engine.py无调用 |
| P6 | **pre_close缺失静默0成交** | `can_trade():204-206` close==0 or pre_close==0→False | 回测跑完0交易无报错，全部指标为0 | 已实际遭遇并修复(2026-04-07) |
| P7 | **Fill.slippage双重计数** | `backtest_engine.py:353,417` slippage*shares | calc_slippage返回单价滑点又乘shares，trade记录中slippage值虚高(不影响NAV但影响成本分析) | 对比Fill.slippage vs calc_slippage()*shares的值 |
| P8 | **Phase A缺少z-score clip±3** | `vectorized_signal.py:122-128`无clip | 极端值(z=10+)主导组合得分，与CLAUDE.md生产流程不一致 | 对比clip前后TopN选股重叠率 |

### 2.2 影响分析质量（🟡 功能缺失）

| # | 问题 | 影响 |
|---|------|------|
| P9 | **BacktestResult无内置metrics** | Sharpe/MDD/Calmar/Sortino全部在外部脚本手动算，每个脚本写一遍，且没有Deflated Sharpe Ratio |
| P10 | **无benchmark相对指标** | 存了benchmark_nav但不算alpha/beta/IR/tracking error，只做绝对收益分析 |
| P11 | **无Deflated Sharpe Ratio** | M=69次因子测试，不计算DSR无法评估过拟合风险 |
| P12 | **无子期间分析** | 不自动拆分牛熊/年度/regime子期间，2021牛市和2022-2023熊市的贡献看不出来 |
| P13 | **换手率只在调仓日记录** | PMS卖出和补单造成的换手未被捕获，总换手率被低估 |
| P14 | **无退市处理** | 持仓股退市后从price_data消失，变成"幽灵仓位"，现金被永久锁定 |

### 2.3 架构/性能（🟠）

| # | 问题 | 影响 |
|---|------|------|
| P15 | **price_idx用iterrows()构建** | 6M行价格数据遍历需要数分钟，是回测启动最大瓶颈 |
| P16 | **daily_close逐日filter全表** | O(days × rows)复杂度，重复扫描 |
| P17 | **单位转换用magic number** | `< 1e9`/`< 1e10`散布3处，换数据源就会静默出错 |

### 2.4 与第一梯队框架的差距矩阵

| 能力 | Qlib | RQAlpha | vectorbt | 我们 | 差距评级 |
|------|------|---------|----------|------|---------|
| 分红/送股处理 | ✅ | ✅完整(Decimal精度) | N/A | ❌ | **致命** |
| 历史印花税率 | ✅ | ✅(pit_tax) | N/A | ❌ | **高** |
| 最低佣金 | ✅(min_cost) | ✅(5元) | ✅(fixed_fees) | ❌ | **高** |
| 数据完整性校验 | 隐式(NaN=停牌) | 4层Validator链 | N/A | ❌ | **高** |
| 嵌套多频率执行 | ✅NestedExecutor | ❌ | ❌ | ❌ | **高**(Stage 4需要) |
| Deflated Sharpe | ❌ | ❌ | ✅ | ❌ | **中**(M=69需要) |
| 订单级执行质量 | ✅(FFR/PA/POS) | ✅ | ✅ | ❌ | **中** |
| benchmark相对指标 | ✅(alpha/beta/IR) | ✅(rqrisk全套) | ✅ | ❌ | **中** |
| Numpy缓存查询 | ✅(NumpyQuote+LRU) | ✅ | ✅(Numba JIT) | ❌(pandas) | **中** |
| 部分成交 | ❌ | ✅ | ✅ | ❌ | **低** |
| 退市自动清算 | ❌ | ✅ | ❌ | ❌ | **低** |
| VWAP撮合 | ✅ | ✅ | N/A | ❌ | **低** |
| Volume-Impact滑点 | 简单二次方 | 无 | 无 | ✅**三因素** | **我们领先** |
| PMS利润保护 | 无 | 无 | 无 | ✅ | **我们独有** |
| 封板补单 | 无 | 无 | 无 | ✅ | **我们独有** |

### 2.5 与v3设计文档的差距

| 设计需求 | 设计文档 | 实际状态 |
|---------|---------|---------|
| ExecutionSimulator独立类 | DEV_BACKTEST_ENGINE §4.3 | ❌ 合并在SimpleBacktester里 |
| BacktestConfig完整参数 | DEV_BACKTEST_ENGINE 20+字段 | ❌ 实际只有8字段 |
| 15种策略模板 | ROADMAP GA1-B | ❌ 只有模板1(月度等权)在用 |
| AutoBacktestRouter | ROADMAP GA4 | ❌ 未实现 |
| CompositeSignalEngine | ROADMAP K4 | 🟡 代码存在但未接入生产 |
| DSR/PBO集成到标准输出 | ROADMAP I5 | ❌ dsr.py/pbo.py存在但独立 |
| H0成本模型校准 | ROADMAP ⭐⭐⭐ | ❌ 未做 |
| 6张回测结果表 | DEV_BACKTEST_ENGINE | ❌ 只有2张(backtest_run + backtest_trades) |
| WebSocket进度推送 | DEV_BACKEND | ❌ 基础设施就绪但引擎不emit |
| Walk-Forward标准化 | DEV_BACKTEST_ENGINE §6 | 🟡 walk_forward.py存在但参数化不同 |

---

## 3. 改造方案：四阶段

### Phase 1: 数据正确性修复（3-4天）

**目标**: 回测结果准确可信，得到"真实的"基线Sharpe

#### 1.1 分红除权处理 [P1]

**数据源**: `dividend`表（DDL已有，Tushare `dividend`接口）

**实现方案**:
```
SimBroker日循环增加:
1. 每日开盘前检查holdings中的股票是否在当日除权
2. 现金分红: cash += shares * dividend_per_share * (1 - tax_rate)
3. 送股: holdings[code] = int(shares * (1 + bonus_ratio))
4. 配股: 暂不处理（需要额外资金注入逻辑复杂）

数据预加载:
- 回测前查询dividend表，构建 dict[date, list[DividendEvent]]
- DividendEvent: code, ex_date, cash_div, stock_div, record_date
```

**参考**: RQAlpha `StockPosition._handle_dividend_book_closure()` 使用Decimal精度

**测试**:
- 构造已知分红案例（如工商银行2024每股0.31元），验证NAV调整正确
- 对比有无分红的5年全量回测Sharpe差异

#### 1.2 送股/拆股处理 [P2]

**问题**: 持仓股10送10后holdings数量未翻倍，相当于丢失一半仓位。

**实现方案**:
```
SimBroker日循环增加（与§1.1分红一起处理）:
1. 送股: holdings[code] = int(shares * (1 + bonus_ratio))
2. 拆股: holdings[code] = int(shares * split_ratio)
3. 配股: 暂不处理（需要额外资金注入逻辑复杂）
```

**参考**: RQAlpha `StockPosition._handle_dividend_book_closure()` 使用Decimal精度处理

**测试**: 构造已知送股案例（如10送10），验证holdings数量翻倍且NAV不变

#### 1.3 印花税历史税率 [P3]

**实现**: `execute_sell`中一行判断
```python
stamp_tax_rate = 0.001 if exec_date < date(2023, 8, 28) else 0.0005
```

**验证**: 2022全年回测，对比固定0.05% vs 历史税率的总成本差异

#### 1.4 最低佣金5元/笔 [P4]

**实现**: `execute_buy`和`execute_sell`中
```python
commission = max(trade_value * self.config.commission_rate, 5.0)
```

**验证**: 统计5年回测中触发最低佣金的交易比例

#### 1.5 接入overnight_gap三因素滑点 [P5]

**实现**: `SimBroker.calc_slippage`调用`estimate_execution_price`替代当前的`volume_impact_slippage`

**关键**: 需要传入`open_price`和`prev_close`（price_idx行中已有）

**验证**: 对比二因素vs三因素的单笔成本差异，确认在R4验证的10-15bps范围

#### 1.6 DataFeed必填字段校验 [P6]

**实现**: `DataFeed.validate()`增加
```python
REQUIRED_FIELDS = {"code", "trade_date", "open", "close", "pre_close", "volume"}
missing = REQUIRED_FIELDS - set(df.columns)
if missing:
    raise ValueError(f"回测数据缺少必填字段: {missing}")
```

**额外**: `SimBroker.can_trade()`中`pre_close==0`改为raise而非静默返回False

#### 1.7 Phase A z-score clip±3 + Fix Fill.slippage [P8, P7]

**z-score clip**: `vectorized_signal.py:128`后加 `.clip(-3, 3)`
**Fill.slippage**: 修正`backtest_engine.py:353,417`的计算逻辑

#### 1.8 重跑5年基线

Phase 1全部修复后，用`run_backtest.py`重跑5因子等权月度Top-20：
- 预期Sharpe从1.15-1.24降到0.95-1.10（成本更真实）
- 此数字成为后续所有研究的新锚点
- 记录到FACTOR_TEST_REGISTRY.md作为新基线

---

### Phase 2: 分析能力专业化（2-3天）

**目标**: 每次回测自动输出专业级分析报告

#### 2.1 BacktestResult.metrics() [P9]

新增方法，返回dict包含：

| 指标 | 公式 | 来源 |
|------|------|------|
| annual_return | `(nav[-1]/nav[0])^(252/days) - 1` | 标准 |
| annual_volatility | `daily_ret.std() * sqrt(252)` | 标准 |
| sharpe_ratio | `annual_return / annual_volatility` | 标准 |
| sortino_ratio | `annual_return / downside_std` | vectorbt |
| calmar_ratio | `annual_return / abs(max_drawdown)` | 标准 |
| max_drawdown | `(cummax - nav).max() / cummax` | 标准 |
| max_dd_duration | 最长水下天数 | RQAlpha |
| win_rate | 正收益交易占比 | 标准 |
| profit_loss_ratio | 平均盈利/平均亏损 | 标准 |
| total_trades | 交易总数 | 现有 |
| avg_turnover | 平均换手率 | 现有(需修复P12) |

#### 2.2 Benchmark相对指标 [P10]

| 指标 | 说明 | 来源 |
|------|------|------|
| alpha | Jensen's alpha (CAPM回归截距) | RQAlpha rqrisk |
| beta | 对基准的敏感度 | RQAlpha rqrisk |
| information_ratio | 超额收益/跟踪误差 | Qlib evaluate |
| tracking_error | 超额收益标准差 * sqrt(252) | 标准 |
| excess_max_drawdown | 超额收益序列的最大回撤 | RQAlpha |

#### 2.3 Deflated Sharpe Ratio [P11]

**公式**: Bailey & Lopez de Prado (2014)

```python
def deflated_sharpe(observed_sr, num_trials, T, skew, kurtosis):
    """
    observed_sr: 观察到的Sharpe
    num_trials: M = FACTOR_TEST_REGISTRY累计测试数(当前69)
    T: 观察天数
    skew, kurtosis: 收益序列的偏度/峰度
    """
    sr_std = sqrt((1 - skew*observed_sr + (kurtosis-1)/4 * observed_sr**2) / (T-1))
    expected_max_sr = sr_std * ((1 - euler_mascheroni) * norm.ppf(1 - 1/num_trials)
                                + euler_mascheroni * norm.ppf(1 - 1/(num_trials*e)))
    return norm.cdf((observed_sr - expected_max_sr) / sr_std)
```

**输出**: DSR p-value。DSR < 0.05表示Sharpe显著高于随机多重测试预期。

**集成点**: `BacktestResult.metrics()`自动计算，M从FACTOR_TEST_REGISTRY读取

#### 2.4 子期间分析 [P12]

```python
def sub_period_analysis(nav, benchmark_nav):
    """按年度 + 牛熊regime自动拆分metrics"""
    results = {}
    # 按年度
    for year in nav.index.year.unique():
        year_nav = nav[nav.index.year == year]
        results[f"Y{year}"] = calc_metrics(year_nav)
    # 按牛熊(基准累计收益正负)
    bench_cum = benchmark_nav.pct_change().cumsum()
    bull = bench_cum > bench_cum.expanding().mean()
    results["Bull"] = calc_metrics(nav[bull])
    results["Bear"] = calc_metrics(nav[~bull])
    return results
```

#### 2.5 换手率完整捕获 [P13]

PMS卖出和封板补单造成的换手也需记录，当前只在调仓日统计换手率。

**实现**: SimBroker中所有execute_buy/sell执行后累加`self.total_turnover`，不限于调仓日。

#### 2.6 订单执行质量指标 [P13扩展]

每笔Fill增加字段：
- `fill_rate`: 成交量/目标量
- `price_advantage`: `sign * (trade_price / benchmark_price - 1)`
- `realized_slippage_bps`: 实际滑点基点

**参考**: Qlib Indicator框架 (FFR/PA/POS)

---

### Phase 3: 性能与健壮性（1-2天）

#### 3.1 price_idx用MultiIndex替代iterrows() [P15]

**当前**(慢):
```python
price_idx = {}
for _, row in price_data.iterrows():  # 6M行遍历
    price_idx[(row["code"], row["trade_date"])] = row
```

**改造后**(快):
```python
price_data = price_data.set_index(["code", "trade_date"]).sort_index()
# 查询: price_data.loc[(code, date)] 替代 price_idx.get((code, date))
```

**预期**: 回测数据准备从分钟级降到秒级（10-50x提速）

#### 3.2 daily_close一次性预构建 [P16]

**当前**(慢):
```python
for d in all_dates:
    day_data = price_data[price_data["trade_date"] == d]  # 每日filter全表
    daily_close[d] = dict(zip(day_data["code"], day_data["close"]))
```

**改造后**(快):
```python
close_pivot = price_data.pivot_table(index="trade_date", columns="code", values="close")
daily_close = {d: row.dropna().to_dict() for d, row in close_pivot.iterrows()}
```

#### 3.3 单位转换集中到DataFeed层 [P17]

在`DataFeed.validate()`后增加`standardize_units()`:
```python
def standardize_units(self):
    """统一转换为标准单位: 金额=元, 市值=元, 成交量=手"""
    # amount: Tushare千元 → 元
    if self.df["amount"].median() < 1e6:  # 中位数<百万→千元
        self.df["amount"] *= 1000
    # total_mv: Tushare万元 → 元
    if "total_mv" in self.df.columns and self.df["total_mv"].median() < 1e8:
        self.df["total_mv"] *= 10000
    self._units_standardized = True
```

消灭`backtest_engine.py`中散布的3处magic number判断。

#### 3.4 退市检测+自动清算 [P14]

```python
# SimBroker日循环中增加
for code in list(broker.holdings.keys()):
    if code not in daily_close.get(td, {}):
        # 股票今日无价格数据 → 可能退市/停牌
        last_price = self._get_last_known_price(code, td, price_idx)
        if last_price and (td - last_price_date).days > 20:
            # 连续20个交易日无数据 → 视为退市，按最后价格清算
            fill = broker.execute_sell(code, broker.holdings[code], last_price_row)
            trades.append(fill)
            logger.warning(f"[{td}] {code} 退市清算: {broker.holdings[code]}股 @ {last_price}")
```

#### 3.5 ValidatorChain（拆分can_trade）

**参考**: RQAlpha FrontendValidator模式

```python
class BaseValidator(ABC):
    @abstractmethod
    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        """返回None=通过, 返回str=拒绝原因"""

class SuspensionValidator(BaseValidator):
    def validate(self, code, direction, row):
        if row.get("volume", 0) == 0:
            return "停牌(volume=0)"
        return None

class PriceLimitValidator(BaseValidator):
    def validate(self, code, direction, row):
        # 涨跌停检测逻辑(从can_trade提取)
        ...

class DataCompletenessValidator(BaseValidator):
    def validate(self, code, direction, row):
        if row.get("pre_close", 0) == 0 or row.get("close", 0) == 0:
            return f"数据不完整(pre_close={row.get('pre_close')}, close={row.get('close')})"
        return None

class ValidatorChain:
    def __init__(self, validators: list[BaseValidator]):
        self.validators = validators

    def can_trade(self, code, direction, row) -> tuple[bool, str | None]:
        for v in self.validators:
            reason = v.validate(code, direction, row)
            if reason:
                return False, reason
        return True, None
```

好处: 可组合、可扩展、拒绝原因可追溯（不再静默）。

---

### Phase 4: Qlib集成 + 架构升级（1-2周，Stage 4前）

#### 4.1 Qlib StaticDataLoader适配器

```python
from qlib.data.dataset.loader import StaticDataLoader

class QuantMindQlibAdapter:
    """从TimescaleDB/Parquet加载数据，喂给Qlib模型"""

    def load_factor_data(self, factors, start, end) -> pd.DataFrame:
        """查询factor_values表，返回Qlib格式的DataFrame"""
        conn = get_db_connection()
        df = pd.read_sql(f"""
            SELECT code AS instrument, trade_date AS datetime,
                   factor_name, zscore AS value
            FROM factor_values
            WHERE factor_name IN ({','.join(f"'{f}'" for f in factors)})
            AND trade_date BETWEEN '{start}' AND '{end}'
        """, conn)
        # Pivot to wide format: (datetime, instrument) x factors
        wide = df.pivot_table(index=["datetime", "instrument"],
                              columns="factor_name", values="value")
        return wide

    def to_static_loader(self, factors, start, end):
        df = self.load_factor_data(factors, start, end)
        return StaticDataLoader(config=df)
```

#### 4.2 Alpha158因子移植

从Alpha158中选择我们缺失的高价值因子维度：

| 类别 | 因子数 | 示例 | 价值 |
|------|--------|------|------|
| KBAR蜡烛图特征 | 9 | KMID, KLEN, KUP, KLOW, KSFT | 新维度：日内形态 |
| 价量相关性 | 2×5=10 | CORR, CORD (5/10/20/30/60d) | 新维度：价量背离 |
| 方向计数 | 6×5=30 | CNTP, CNTN, CNTD, SUMP, SUMN, SUMD | 新维度：涨跌比例 |
| 量加权波动 | 1×5=5 | WVMA | 补充volatility_20 |

移植到`factor_engine.py`，注册到FACTOR_TEST_REGISTRY.md，走标准Gate G1-G9入池。

#### 4.3 Executor接口抽象

**借鉴Qlib NestedExecutor设计**:

```python
class BaseExecutor(ABC):
    @abstractmethod
    def execute(self, trade_decision: dict[str, float]) -> ExecutionResult:
        """执行交易决策，返回结果"""

class SimulatorExecutor(BaseExecutor):
    """当前SimBroker重构为Executor接口"""

class NestedExecutor(BaseExecutor):
    """月度→日度多层嵌套"""
    def __init__(self, outer_strategy, inner_executor: BaseExecutor):
        self.outer = outer_strategy
        self.inner = inner_executor

    def execute(self, trade_decision):
        # 外层月度目标 → 拆分为日度子订单 → 内层执行
        daily_slices = self.outer.decompose(trade_decision)
        results = []
        for day_slice in daily_slices:
            result = self.inner.execute(day_slice)
            results.append(result)
        return self.aggregate(results)
```

#### 4.4 CompositeSignalEngine接入回测

将现有`strategies/composite.py`接入`run_hybrid_backtest`：

```python
def run_composite_backtest(
    core_factor_df, core_directions,
    modifier_configs: list[ModifierConfig],
    price_data, config, benchmark_data=None,
):
    """CompositeStrategy回测入口"""
    # Phase A: 核心策略信号
    core_targets = build_target_portfolios(core_factor_df, core_directions, ...)

    # Phase A.5: Modifier调节
    composite = CompositeStrategy(core_strategy, modifiers)
    adjusted_targets = composite.apply_modifiers(core_targets, price_data)

    # Phase B: 执行
    tester = SimpleBacktester(config)
    return tester.run(adjusted_targets, price_data, benchmark_data)
```

#### 4.5 H0成本模型校准 [ROADMAP ⭐⭐⭐]

从QMT实际成交中取15笔，对比SimBroker模拟成本：
- 佣金: QMT实际 vs config.commission_rate
- 滑点: 实际成交价偏移 vs volume_impact_slippage计算值
- 总成本: 误差<5bps视为PASS

---

## 4. 目标架构图

```
┌─────────────────────────────────────────────────────────────┐
│              BacktestOrchestrator (统一入口)                   │
│  参数校验 + 数据预检 + WebSocket进度推送                       │
├───────────────┬─────────────────────────────────────────────┤
│ DataFeed层     │ validate() → standardize_units() → 预加载   │
│               │ 必填字段断言 / 分红日历 / 退市日历             │
├───────────────┼─────────────────────────────────────────────┤
│ Phase A       │ SignalGenerator (向量化)                      │
│ 信号生成      │ z-score(clip±3) → 方向 → Top-N等权           │
│               │ + 行业约束 + 流动性过滤 + ST过滤              │
├───────────────┼─────────────────────────────────────────────┤
│ Phase B       │ ExecutionEngine (事件驱动)                    │
│ 执行模拟      │ ├─ ValidatorChain (可组合Validator)           │
│               │ │  ├─ DataCompletenessValidator              │
│               │ │  ├─ SuspensionValidator                    │
│               │ │  ├─ PriceLimitValidator                    │
│               │ │  └─ VolumeValidator                        │
│               │ ├─ CostModel                                 │
│               │ │  ├─ commission(万0.854, min 5元)            │
│               │ │  ├─ stamp_tax(历史费率)                     │
│               │ │  └─ slippage(三因素: spread+impact+gap)     │
│               │ ├─ DividendHandler (分红除权)                 │
│               │ ├─ DelistingHandler (退市清算)                │
│               │ └─ PMS + 封板补单                             │
├───────────────┼─────────────────────────────────────────────┤
│ Analytics层   │ BacktestResult.metrics()                     │
│ 分析报告      │ ├─ 绝对: Sharpe/Sortino/Calmar/MDD/年化      │
│               │ ├─ 相对: alpha/beta/IR/tracking_error        │
│               │ ├─ 防过拟合: DSR(M=注册表总数) / PBO          │
│               │ ├─ 子期间: 年度 + 牛熊regime                  │
│               │ └─ 执行质量: fill_rate/price_advantage        │
├───────────────┼─────────────────────────────────────────────┤
│ Qlib ML层     │ StaticDataLoader ← TimescaleDB               │
│ (Phase 4)     │ LightGBM/TRA/ALSTM → 预测分数                │
│               │ 输出 → Phase A作为额外信号源                   │
└───────────────┴─────────────────────────────────────────────┘
```

---

## 5. 执行时间线

| 阶段 | 时间 | 交付物 | 验收标准 |
|------|------|--------|---------|
| Phase 1 | 本周(4/7-4/11) | 8项准确性修复 + 新基线Sharpe | 分红/送股/税率/佣金/滑点全部生效；重跑基线数字变化且可解释 |
| Phase 2 | 下周(4/14-4/16) | BacktestResult.metrics() + DSR + 子期间 | 回测输出包含15+指标；DSR自动计算 |
| Phase 3 | 第三周(4/17-4/18) | MultiIndex + ValidatorChain + 退市 | 回测启动<30s(当前分钟级)；can_trade拒绝有原因 |
| Phase 4 | Stage 4前(4/21-5/2) | Qlib适配器 + Alpha158因子 + Executor抽象 | Qlib模型可跑通；CompositeStrategy可回测 |

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Phase 1修复后基线Sharpe大幅下降 | 高 | 当前1.15可能降到<1.0 | 这是真实数字，旧数字本来就偏高。用新基线重新评估PT毕业阈值 |
| 分红数据不完整 | 中 | dividend表可能有缺失 | 先查dividend表覆盖率，必要时补拉Tushare dividend接口 |
| MultiIndex重构引入新bug | 低 | price_idx查询行为变化 | 重构前后对比同一回测的NAV/trades，必须bit-identical |
| Qlib依赖冲突 | 低 | gym/cvxpy等重依赖 | 用`--no-deps`安装，手动装需要的子集 |

---

## 7. 与现有设计文档对齐

| 设计文档需求 | 本计划对应 |
|-------------|-----------|
| DEV_BACKTEST_ENGINE 决策3: 滑点三因素 | Phase 1.5: 接入overnight_gap |
| DEV_BACKTEST_ENGINE 决策7: 6张结果表 | Phase 2: BacktestResult.metrics()先内存，后续持久化 |
| DEV_BACKTEST_ENGINE 决策10: unfilled handling | Phase 3.5: ValidatorChain + 拒绝原因追溯 |
| DEV_BACKTEST_ENGINE 决策4: 分红除权 | Phase 1.1 + 1.2: 现金分红+送股拆股 |
| DEV_BACKTEST_ENGINE §4.3: ExecutionSimulator独立类 | Phase 4.3: Executor接口抽象 |
| ROADMAP K4: CompositeSignalEngine | Phase 4.4 |
| ROADMAP I5: Anti-overfitting (DSR/PBO) | Phase 2.3 |
| ROADMAP H0: 成本模型校准 ⭐⭐⭐ | Phase 4.5 |
| ROADMAP GA1-B: 15策略模板 | Phase 4.3 Executor抽象是前置 |
| ROADMAP GA4: AutoBacktestRouter | Phase 4后续 |

---

## 8. 成功指标

| 指标 | 当前 | Phase 1后 | Phase 2后 | Phase 4后 |
|------|------|----------|----------|----------|
| 回测准确性 | 缺分红/送股/税率/佣金 | ✅ 8项全部修复 | ✅ | ✅ |
| 指标完整度 | 手动算3个 | 手动算3个 | ✅ 自动15+ | ✅ 自动20+ |
| DSR | 无 | 无 | ✅ 自动 | ✅ 自动 |
| 回测启动时间 | ~5min(6M行) | ~5min | ~5min | ✅ <30s |
| 可追溯拒绝 | 静默失败 | ✅ 报错 | ✅ 报错 | ✅ 链式原因 |
| 多策略支持 | 仅等权月度 | 仅等权月度 | 仅等权月度 | ✅ Composite |
| Qlib模型可用 | 无 | 无 | 无 | ✅ 40+模型 |
