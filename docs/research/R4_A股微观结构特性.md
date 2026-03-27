# R4 A股微观结构特性研究报告

> **研究维度**: 滑点/流动性/涨跌停精确建模与PT实测数据校准
> **日期**: 2026-03-28
> **状态**: 完成

---

## 1. 问题定义：当前成本模型状态与PT实测差距

### 1.1 当前模型架构

QuantMind V2的滑点模型(`backend/engines/slippage_model.py`)采用双因素结构：

```
total_slippage = base_bps + impact_bps
```

- **基础滑点(base_bps)**: 固定5bps，代表bid-ask spread
- **冲击成本(impact_bps)**: Bouchaud 2018 square-root law
  ```
  impact = Y * sigma_daily * sqrt(Q/V) * 10000
  ```
  其中Y按市值分档: Y_large=0.8 / Y_mid=1.0 / Y_small=1.5

### 1.2 三代模型对比

| 模型 | 估计滑点 | PT实测 | 偏差 | Sharpe |
|------|----------|--------|------|--------|
| Fixed 10bps | 10bps | 64.5bps | -85% (严重低估) | 1.03 |
| Volume-Impact (旧参数) | 55-60bps | 64.5bps | -8~15% | ~0.50 |
| Volume-Impact (sigma校准) | ~60bps | 64.5bps | ~7% | 0.91 |

### 1.3 核心差距分析

PT实测64.5bps的构成估计：
- Bid-ask spread: ~10-15bps (小盘股价差较大)
- 市场冲击: ~25-35bps (开盘集合竞价的价格偏移)
- 隔夜跳空: ~10-15bps (T日信号→T+1执行的overnight gap)
- 执行时机: ~5-10bps (开盘价vs理论价的偏差)

当前模型未显式建模隔夜跳空和执行时机偏差，这解释了剩余~7%的差距。

---

## 2. 文献综述：市场冲击模型数学原理

### 2.1 四大经典模型

#### (A) Kyle (1985) Lambda模型

最早的信息驱动市场冲击理论：

```
Delta_P = lambda * Q
```

- lambda = 做市商定价系数，反映信息不对称程度
- 线性冲击：Q翻倍则冲击翻倍
- **局限**: 实证发现大额订单冲击呈非线性(凹函数)，线性假设过于简化

Kyle lambda在A股实证中呈现W型日内模式(午休导致)，而非美股的U型。高频数据(ScienceDirect 2025)显示Kyle lambda对小盘股更高，与直觉一致。

#### (B) Almgren-Chriss (2000) 最优执行模型

将执行问题形式化为均值-方差优化：

```
min E[cost] + lambda * Var[cost]
```

分解为两个冲击分量：
- **永久冲击(permanent)**: g(v) = gamma * v，信息揭示导致的永久价格移动
- **临时冲击(temporary)**: h(v) = eta * sign(v) + epsilon * v，流动性需求导致的暂时价格偏移

最优执行轨迹为双曲正弦函数，紧急性越高(lambda越大)轨迹越前倾。

**适用场景**: 大资金拆单执行(TWAP/VWAP)，机构级别(百万级以上)。
**对QuantMind的适用性**: 30万/15只=2万/只，单笔太小，无需拆单。Almgren-Chriss的框架过重。

#### (C) Bouchaud (2003/2018) Square-Root Law

市场冲击最稳健的实证规律：

```
Delta_P / sigma = Y * sqrt(Q / V)
```

- sigma: 日波动率
- Q: 交易量
- V: 日均成交量(ADV)
- Y: 常数，约0.5-1.5（取决于市场和资产类型）

**关键性质**:
1. **无标度性**: 冲击只依赖参与率Q/V，不依赖拆单方式或执行时间
2. **凹函数**: sqrt(Q/V)意味着边际冲击递减
3. **波动率标度**: 高波动股票绝对冲击更大，但标准化后冲击相同
4. **普适性**: 在多个市场(美/欧/日/港)均得到验证

2024年11月东京证交所全样本研究(arXiv:2411.13965)确认了square-root law的严格普适性，包括小盘股。

**参数校准**: 实证中指数约0.5-0.6(略高于理论0.5)，Y约1.0上下。

#### (D) 简单线性模型

```
slippage_bps = k * (trade_amount / daily_amount)
```

- 最简单，参数少
- 在低参与率(<1%ADV)时与square-root近似
- 高参与率时严重低估(线性 vs 凹函数)

### 2.2 模型选择结论

**对QuantMind V2(30万总资金，Top15等权)的推荐**: 继续使用Bouchaud Square-Root Law。

理由：
1. **实证最稳健**: 2024年最新研究持续确认，包括亚洲市场
2. **参数简洁**: 只需Y, sigma, Q/V三个输入
3. **小盘股适用**: 东京全样本研究确认小盘股同样遵循
4. **当前实现已有**: `slippage_model.py`已实现，只需校准参数
5. 资金量级(2万/只)参与率极低，square-root和线性差异不大，但square-root更安全

Kyle lambda适合做流动性因子(已有amihud_20)，Almgren-Chriss适合大资金拆单——两者不适合直接作为滑点模型。

---

## 3. A股微观结构特性 (vs 美股差异)

### 3.1 制度差异矩阵

| 特性 | A股 | 美股 | 对滑点模型的影响 |
|------|-----|------|------------------|
| T+N | T+1 | T+0(2024→T+1) | 卖出资金当日可买(T+0可用)，但股票T+1才可卖 |
| 涨跌停 | 有(10/20/5/30%) | 无(有熔断) | 必须建模封板不可交易 |
| 最小交易单位 | 100股 | 1股 | 整手约束导致仓位偏差3-4% |
| 印花税 | 卖出0.05%(2023年下调) | 无 | 显性成本，卖出单边 |
| 做空机制 | 受限(融券T+1) | 相对自由 | 卖出冲击更大(无对冲方) |
| 午休 | 11:30-13:00 | 无 | 流动性W型模式(两次开盘效应) |
| 开盘机制 | 集合竞价9:15-9:25 | 连续交易 | 开盘价可能大幅偏离前收 |
| 散户比例 | ~60-70%交易量 | ~15-20% | 噪声交易多，动量效应弱 |
| 涨跌停幅度 | 主板10%/创业板科创板20%/ST 5%/北交所30% | N/A | 不同板块需分别处理 |

### 3.2 A股特有的微观结构效应

**3.2.1 开盘跳空效应**

T日收盘生成信号 → T+1开盘执行，存在约16小时的overnight gap。实证显示：
- 小盘股隔夜跳空幅度更大(信息更不对称)
- 利好/利空消息在夜间释放，开盘价可能偏离前收0.5-2%
- 这是当前模型未捕捉的~10-15bps滑点来源

**3.2.2 集合竞价价格发现**

9:15-9:25集合竞价期间:
- 9:15-9:20可撤单(虚假挂单多)
- 9:20-9:25不可撤单(真实供需)
- 广发证券研究显示09:15-09:20买单方向因子RankIC约-9.2%，具有独立alpha

**3.2.3 涨停板生态**

A股特有的"打板"文化:
- 一字板: 开盘即涨停，全天无成交机会(除非撬板)
- 换手板: 盘中打开后封回，有成交但不确定
- 封板率: 换手率<1%为强封板判断标准(当前实现)

### 3.3 卖出冲击不对称性

A股卖出冲击显著大于买入，原因:
1. 融券受限 → 卖方流动性天然稀缺
2. 散户持有偏好("不卖不亏") → 真正卖出时常伴随恐慌
3. 涨停板限制 → 利好时买不进，利空时抢着卖

当前sell_penalty=1.2偏保守，实证可能在1.3-1.5范围。

---

## 4. 100万资金量级的冲击分析

### 4.1 单笔交易规模

```
总资金: 300,000元
持仓数: 15只
单只金额: ~20,000元
现金缓冲: 3% → 实际单只 ~19,400元
```

### 4.2 参与率分析

按市值分层的典型日均成交额和参与率:

| 市值档 | 典型日均成交额 | 单笔2万参与率 | sqrt(参与率) | 备注 |
|--------|---------------|--------------|-------------|------|
| 大盘(500亿+) | 5-20亿 | 0.001-0.004% | 0.003-0.006 | 冲击可忽略 |
| 中盘(100-500亿) | 1-5亿 | 0.004-0.02% | 0.006-0.014 | 冲击很小 |
| 小盘(20-100亿) | 2000万-1亿 | 0.02-0.1% | 0.014-0.032 | 冲击可见但小 |
| 微盘(<20亿) | 500万-2000万 | 0.1-0.4% | 0.032-0.063 | 冲击显著 |

### 4.3 Bouchaud公式代入计算

以小盘股为例(市值50亿，日成交额5000万，sigma_daily=0.025):

```
impact = Y * sigma_daily * sqrt(Q/V) * 10000
       = 1.5 * 0.025 * sqrt(20000/50000000) * 10000
       = 1.5 * 0.025 * sqrt(0.0004) * 10000
       = 1.5 * 0.025 * 0.02 * 10000
       = 7.5 bps

total = 5.0(base) + 7.5(impact) = 12.5 bps
```

以微盘股为例(市值15亿，日成交额800万，sigma_daily=0.035):

```
impact = 1.5 * 0.035 * sqrt(20000/8000000) * 10000
       = 1.5 * 0.035 * 0.05 * 10000
       = 26.25 bps

total = 5.0 + 26.25 = 31.25 bps
```

### 4.4 关键发现

**纯市场冲击在2万/只级别普遍较小(7-30bps)**，而PT实测64.5bps远高于此。

这说明PT实测的64.5bps中，真正的市场冲击成本只占一部分，其余来自:
1. **隔夜跳空(overnight gap)**: 这是最大来源，约20-30bps
2. **开盘价偏移**: 集合竞价结果vs前收盘价的系统性偏差
3. **执行延迟**: 信号价格(前收)vs实际执行价(次日开盘)的自然漂移

**结论: 对于30万资金Top15策略，纯冲击成本不是主要问题。需要关注的是隔夜跳空和开盘价偏移。**

---

## 5. 涨跌停精确建模方案

### 5.1 当前实现评估

当前`can_trade()`逻辑(`backtest_engine.py:125-173`):

```python
# 封板判断
if direction == "buy":
    if abs(close - up_limit) < 0.015 and turnover < 1.0:
        return False
```

**优点**: 简洁，覆盖主要场景
**不足**:
1. 阈值0.015元是硬编码，对低价股(1-2元)可能偏大
2. 换手率1%阈值对所有板块一刀切
3. 未建模"部分成交"——实际上涨停板仍有部分成交可能
4. 未区分一字板(全天涨停)和换手板(盘中打开又封回)

### 5.2 改进方案

#### 方案A: 多维度封板判断(推荐)

```python
def can_trade_v2(
    code: str,
    direction: str,
    row: pd.Series,
    board_type: str = "main",  # main/gem/star/st/bse
) -> tuple[bool, float]:
    """返回 (可交易, 预估成交概率)。

    改进点:
    1. 封板阈值按价格自适应(消除低价股偏差)
    2. 换手率阈值按板块分层
    3. 部分成交概率估计
    4. 一字板 vs 换手板区分
    """
    close = row["close"]
    pre_close = row["pre_close"]
    up_limit = row.get("up_limit", pre_close * (1 + LIMIT_MAP[board_type]))
    down_limit = row.get("down_limit", pre_close * (1 - LIMIT_MAP[board_type]))
    turnover = row.get("turnover_rate", 999)
    volume = row.get("volume", 0)
    open_price = row.get("open", close)
    high = row.get("high", close)
    low = row.get("low", close)

    # 停牌
    if volume == 0:
        return (False, 0.0)

    # 自适应封板阈值: 价格的0.1%(至少1分钱)
    tol = max(close * 0.001, 0.01)

    if direction == "buy":
        at_limit = abs(close - up_limit) < tol
        if at_limit:
            # 一字板: open == high == close == up_limit
            is_yizi = abs(open_price - up_limit) < tol and abs(high - low) < tol
            if is_yizi:
                return (False, 0.0)  # 一字板完全不可买入

            # 换手板: 日内曾打开(low < up_limit)
            if turnover < 0.5:
                return (False, 0.0)  # 强封板
            elif turnover < 2.0:
                # 部分成交概率 = turnover / 5.0 (经验公式)
                fill_prob = min(turnover / 5.0, 0.8)
                return (True, fill_prob)
            else:
                return (True, 1.0)  # 换手充分，可全额成交

    elif direction == "sell":
        at_limit = abs(close - down_limit) < tol
        if at_limit:
            is_yizi = abs(open_price - down_limit) < tol and abs(high - low) < tol
            if is_yizi:
                return (False, 0.0)
            if turnover < 0.5:
                return (False, 0.0)
            elif turnover < 2.0:
                fill_prob = min(turnover / 5.0, 0.8)
                return (True, fill_prob)
            else:
                return (True, 1.0)

    return (True, 1.0)

LIMIT_MAP = {
    "main": 0.10,    # 主板
    "gem": 0.20,     # 创业板(300xxx)
    "star": 0.20,    # 科创板(688xxx)
    "st": 0.05,      # ST股
    "bse": 0.30,     # 北交所(8xxxxx/4xxxxx)
}
```

#### 方案B: 部分成交建模

当涨停板有成交量时，估算成交概率:

```python
def estimate_fill_probability(
    turnover_rate: float,
    volume: float,
    trade_shares: int,
    is_at_limit: bool,
) -> float:
    """估算涨停板下的成交概率。

    逻辑:
    - 涨停板的成交量代表"被放出来"的筹码
    - trade_shares占当日成交量的比例决定是否排得上队
    - 换手率越高，封板越松，成交概率越高
    """
    if not is_at_limit:
        return 1.0

    if volume <= 0:
        return 0.0

    # 因素1: 换手率 → 封板强度
    # 换手率<0.5%: 强封板, 概率<10%
    # 换手率0.5-2%: 中等封板, 概率10-60%
    # 换手率>2%: 弱封板/换手板, 概率>60%
    turnover_factor = min(turnover_rate / 3.0, 1.0)

    # 因素2: 我们的交易占比
    # 交易量越大, 越难全部成交
    our_share = trade_shares / volume if volume > 0 else 1.0
    share_factor = max(1.0 - our_share * 10, 0.0)  # >10%占比则概率为0

    return turnover_factor * share_factor
```

### 5.3 板块判断逻辑

通过股票代码前缀判断板块涨跌停幅度:

```python
def get_board_type(code: str) -> str:
    """根据股票代码判断板块类型。"""
    if code.startswith(("300",)):
        return "gem"      # 创业板 20%
    elif code.startswith(("688",)):
        return "star"     # 科创板 20%
    elif code.startswith(("8", "4")):
        return "bse"      # 北交所 30%
    # ST判断需要额外数据(名称包含ST)
    # 这里默认主板
    return "main"         # 主板 10%
```

**注意**: ST股判断不能仅靠代码前缀，需要查symbols表的name字段(包含"ST"或"*ST")。当前系统在`symbols`表已有此信息。

---

## 6. k系数校准方法(用PT数据)

### 6.1 校准框架

目标: 找到最优参数 {Y_large, Y_mid, Y_small, sell_penalty, base_bps} 使得模型预测滑点与PT实测最匹配。

#### 步骤1: PT数据采集

从`trade_log`表中提取(execution_mode='paper'):
```sql
SELECT
    t.code,
    t.trade_date,
    t.direction,
    t.signal_price,        -- 信号价格(前收或VWAP)
    t.execution_price,     -- 实际成交价
    t.shares,
    t.amount,
    k.volume,
    k.amount AS daily_amount,
    k.turnover_rate,
    db.total_mv AS market_cap,
    -- 实测滑点
    ABS(t.execution_price - t.signal_price) / t.signal_price * 10000 AS realized_bps
FROM trade_log t
JOIN klines_daily k ON t.code = k.ts_code AND t.trade_date = k.trade_date
JOIN daily_basic db ON t.code = db.ts_code AND t.trade_date = db.trade_date
WHERE t.execution_mode = 'paper'
ORDER BY t.trade_date;
```

#### 步骤2: 按市值分层统计

```python
def calibrate_Y_params(pt_trades: pd.DataFrame) -> dict:
    """用PT实测数据校准Y参数。

    方法: 对每个市值分层, 用最小二乘法拟合:
        realized_bps = base + Y * sigma * sqrt(Q/V) * 10000
    """
    results = {}
    for cap_group in ["large", "mid", "small"]:
        group = pt_trades[pt_trades["cap_group"] == cap_group]
        if len(group) < 10:
            continue

        # 构造特征: sigma * sqrt(Q/V)
        X = group["sigma_daily"] * np.sqrt(
            group["trade_amount"] / group["daily_amount"]
        )
        y = group["realized_bps"]

        # 线性回归: y = base + Y * X * 10000
        # 简化为: y = a + b * X, 其中 b = Y * 10000
        from sklearn.linear_model import LinearRegression
        model = LinearRegression().fit(X.values.reshape(-1, 1), y.values)
        Y_estimated = model.coef_[0] / 10000
        base_estimated = model.intercept_

        results[cap_group] = {
            "Y": Y_estimated,
            "base_bps": base_estimated,
            "n_trades": len(group),
            "r2": model.score(X.values.reshape(-1, 1), y.values),
        }

    return results
```

#### 步骤3: 交叉验证

- 用70%数据校准，30%验证
- 比较预测误差分布(MAE, RMSE)
- 检查参数稳定性(不同时间窗口的Y是否漂移)

### 6.2 当前参数合理性评估

| 参数 | 当前值 | 理论合理范围 | 评估 |
|------|--------|-------------|------|
| Y_large | 0.8 | 0.5-1.0 | 合理 |
| Y_mid | 1.0 | 0.8-1.5 | 合理 |
| Y_small | 1.5 | 1.0-2.5 | 偏保守，可能需上调至1.8-2.0 |
| sell_penalty | 1.2 | 1.2-1.5 | 偏低，A股卖出冲击更大 |
| base_bps | 5.0 | 5-15 | 偏低，小盘股bid-ask spread更宽 |

### 6.3 改进建议

1. **base_bps按市值分层**: 大盘3-5bps / 中盘5-10bps / 小盘10-20bps
2. **Y_small上调**: 从1.5提高到1.8-2.0，更好匹配小盘股高冲击
3. **sell_penalty上调**: 从1.2提高到1.3-1.4
4. **引入overnight_gap项**: 新增隔夜跳空成本估计

### 6.4 隔夜跳空建模(新增项)

当前模型完全忽略了隔夜跳空，而这可能是PT实测vs模型差距的最大来源:

```python
def overnight_gap_cost(
    sigma_daily: float,
    direction: str,
    gap_hours: float = 16.0,  # 信号生成到执行的时间差
) -> float:
    """估算隔夜跳空的期望成本(bps)。

    逻辑:
    - 隔夜价格变动 ~ N(0, sigma_overnight^2)
    - 期望绝对偏差 = sigma * sqrt(2/pi) (半正态分布)
    - 方向性: 如果信号是买入(看好), 开盘更可能高开(信息泄漏)
    """
    # 隔夜波动率 ≈ 日波动率的60-80%(经验值, 美股约50%)
    sigma_overnight = sigma_daily * 0.7

    # 期望绝对偏差
    expected_gap = sigma_overnight * math.sqrt(2 / math.pi)

    # 方向性惩罚: 买入信号时市场可能已price-in部分信息
    # 导致开盘价系统性偏高
    direction_bias = 0.3 if direction == "buy" else 0.2  # 买入bias更大

    gap_bps = (expected_gap * direction_bias) * 10000
    return gap_bps
```

---

## 7. 推荐的成本模型改进

### 7.1 增强型三因素滑点模型

```
total_slippage = base_bps(market_cap) + impact_bps(Y, sigma, Q/V) + gap_bps(sigma, direction)
```

新增第三项: 隔夜跳空成本。

### 7.2 具体改进清单

| # | 改进 | 预期效果 | 优先级 |
|---|------|---------|--------|
| 1 | base_bps按市值分层 | 更准确的固定成本 | P1 |
| 2 | 新增overnight_gap_cost | 缩小PT差距~10bps | P1 |
| 3 | can_trade增加部分成交 | 更真实的涨停板建模 | P2 |
| 4 | sell_penalty上调至1.3 | 匹配A股卖出不对称 | P2 |
| 5 | 板块涨跌停分层 | 创业板/科创板精确处理 | P2 |
| 6 | PT数据回归校准Y | 数据驱动参数 | P1(需PT数据积累) |
| 7 | 封板阈值自适应(价格比例) | 消除低价股偏差 | P3 |

### 7.3 不推荐的改进

1. **Almgren-Chriss拆单**: 2万/只太小，无需拆单优化
2. **集合竞价数据接入**: 需要Level-2数据(Tushare Pro 8000积分不够)，成本高收益低
3. **日内冲击曲线**: 月度调仓只用开盘价执行，日内模式无意义
4. **做市商模型**: A股没有专门做市商制度(仅北交所有)

---

## 8. 落地计划

### 8.1 修改文件清单

#### (1) `backend/engines/slippage_model.py` — 核心改动

```python
# 改动1: SlippageConfig增加分层base_bps
@dataclass(frozen=True)
class SlippageConfig:
    Y_large: float = 0.8
    Y_mid: float = 1.0
    Y_small: float = 1.8       # 上调: 1.5 → 1.8
    sell_penalty: float = 1.3   # 上调: 1.2 → 1.3
    base_bps_large: float = 3.0  # 新增: 分层base
    base_bps_mid: float = 8.0    # 新增
    base_bps_small: float = 15.0  # 新增
    overnight_gap_factor: float = 0.3  # 新增: 隔夜跳空系数

    def get_base_bps(self, market_cap: float) -> float:
        if market_cap >= 50_000_000_000:
            return self.base_bps_large
        elif market_cap >= 10_000_000_000:
            return self.base_bps_mid
        return self.base_bps_small

# 改动2: volume_impact_slippage增加gap参数
def volume_impact_slippage(..., include_gap: bool = False) -> float:
    # ...现有逻辑...
    if include_gap and config is not None:
        gap = overnight_gap_cost(sigma_daily, direction)
        total += gap
    return total

# 改动3: 新增overnight_gap_cost函数
def overnight_gap_cost(sigma_daily: float, direction: str) -> float:
    ...
```

#### (2) `backend/engines/backtest_engine.py` — can_trade改进

- `can_trade()`: 增加价格比例阈值(替代硬编码0.015)
- 增加板块识别(get_board_type)
- 增加部分成交返回值(可选，Phase 2)

#### (3) `backend/engines/backtest_engine.py` — calc_slippage改进

- 传入`include_gap=True`启用隔夜跳空
- base_bps改为市值分层

#### (4) 新增 `scripts/calibrate_slippage.py`

- 从trade_log读PT数据
- 按市值分层回归校准Y
- 输出校准报告
- 与SimBroker预测对比

### 8.2 实施顺序

```
Phase 1 (立即可做, 不需PT数据):
  1. SlippageConfig增加分层base_bps → slippage_model.py
  2. Y_small上调至1.8, sell_penalty上调至1.3
  3. can_trade阈值改为价格比例
  4. 新增overnight_gap_cost函数

Phase 2 (需PT数据积累60天):
  5. 编写calibrate_slippage.py
  6. 用PT数据校准Y参数
  7. 验证校准后模型 vs PT实测差距

Phase 3 (评估后决定):
  8. 部分成交建模(如果回测显示涨停板频率>5%)
  9. 流动性预测(如果成本敏感性分析显示必要)
```

---

## 9. 测试方案

### 9.1 单元测试

```python
# test_slippage_model.py 新增测试

def test_base_bps_tiered():
    """验证分层base_bps: 小盘>中盘>大盘。"""
    config = SlippageConfig()
    assert config.get_base_bps(100e9) < config.get_base_bps(30e9) < config.get_base_bps(5e9)

def test_overnight_gap_cost_positive():
    """隔夜跳空成本必须为正。"""
    gap = overnight_gap_cost(sigma_daily=0.025, direction="buy")
    assert gap > 0
    gap_sell = overnight_gap_cost(sigma_daily=0.025, direction="sell")
    assert gap_sell > 0

def test_overnight_gap_direction_asymmetry():
    """买入方向隔夜跳空成本应>卖出(买入bias更大)。"""
    gap_buy = overnight_gap_cost(0.025, "buy")
    gap_sell = overnight_gap_cost(0.025, "sell")
    assert gap_buy > gap_sell

def test_can_trade_low_price_stock():
    """低价股(2元)封板阈值应自适应。"""
    row = pd.Series({"close": 2.20, "pre_close": 2.00,
                      "up_limit": 2.20, "volume": 1000,
                      "turnover_rate": 0.3})
    # 2.20 == up_limit, 换手<1%, 应判定封板
    assert not broker.can_trade("600001", "buy", row)

def test_total_slippage_with_gap():
    """含隔夜跳空的总滑点应>不含的。"""
    base_only = volume_impact_slippage(..., include_gap=False)
    with_gap = volume_impact_slippage(..., include_gap=True)
    assert with_gap > base_only
```

### 9.2 回归测试

1. **基线Sharpe对比**: 新参数下重跑2021-2025回测，记录Sharpe变化
2. **确定性验证**: 同参数跑两次结果完全一致
3. **成本敏感性**: 验证2x成本下Sharpe是否仍>0.5

### 9.3 PT校准验证

```python
def test_calibration_reduces_error():
    """校准后预测误差应<校准前。"""
    # 校准前: MAE with default params
    mae_before = compute_mae(pt_data, default_config)
    # 校准后: MAE with calibrated params
    mae_after = compute_mae(pt_data, calibrated_config)
    assert mae_after < mae_before * 0.7  # 至少改善30%
```

### 9.4 成本敏感性分析要求

当前Sharpe对成本假设的敏感度估算:

```
基线(sigma校准后): Sharpe = 0.91
年化收益: ~8% (volume-impact模型下)
年化波动率: ~8.8% (= 8/0.91)

成本每增加10bps → 年化换手约6倍(月度调仓) → 额外成本 = 10bps * 6 = 60bps/年
Sharpe变化 ≈ 0.60% / 8.8% ≈ 0.068

即: 成本每增10bps, Sharpe下降约0.07
```

| 成本假设 | 额外年化成本 | 预估Sharpe |
|---------|-------------|-----------|
| 基线(~60bps) | 0 | 0.91 |
| +10bps(70bps) | 0.60% | 0.84 |
| +20bps(80bps) | 1.20% | 0.77 |
| +30bps(90bps) | 1.80% | 0.70 |

**结论**: 成本模型每10bps的误差导致Sharpe偏差约0.07。当前模型与PT实测差距~5bps，对应Sharpe误差~0.035，在可接受范围内。但持续校准仍有价值。

---

## 10. 具体问题回答总结

### Q1: 市场冲击模型选择
**Bouchaud Square-Root Law最适合**。在2万/只量级，参与率极低(0.01-0.1%)，square-root和线性差异不大，但square-root更有理论基础和实证支持。无需Almgren-Chriss(资金太小)或Kyle lambda(更适合做因子)。

### Q2: k系数校准
当前Y参数整体合理，Y_small偏低建议上调至1.8。核心差距不在Y，而在缺失的隔夜跳空项。PT数据积累60天后可用回归法精确校准。

### Q3: 涨跌停精确建模
当前方案(close==limit AND turnover<1%)基本足够。改进方向: (a)阈值改为价格比例(b)区分一字板/换手板(c)部分成交概率。代码已给出。

### Q4: 流动性预测
技术上可行(ML预测次日成交量，特征包括历史量/波动率/日历效应)，但对月度调仓策略价值有限。2万/只的参与率太低，流动性预测的边际收益不大。建议在因子层面已有的amihud_20/turnover_mean_20足够。

### Q5: 集合竞价
理论上9:20-9:25的数据对开盘价预测有帮助(广发研究RankIC约-9.2%)，但需Level-2数据(Tushare Pro当前积分不够)。投入产出比不高，建议Phase 2再考虑。

### Q6: 时间片冲击
2万/只在大部分小盘股中参与率<0.1%，纯市场冲击7-30bps。真正的成本来源是隔夜跳空(20-30bps)，不是冲击本身。冲击在这个资金量级基本可控。

### Q7: 成本敏感性
成本每增10bps，Sharpe下降约0.07。当前模型vs PT差距~5bps，对应Sharpe误差~0.035。可接受但应持续校准。

---

## 参考文献

1. Bouchaud, J.-P. "The Square-Root Law of Market Impact." (2024) - [Substack](https://bouchaud.substack.com/p/the-square-root-law-of-market-impact)
2. Almgren, R. & Chriss, N. "Optimal Execution of Portfolio Transactions." (2000) - [Paper](https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf)
3. Said, E. "Market Impact: Empirical Evidence, Theory and Practice." (2022) - [HAL](https://hal.science/hal-03668669v1/file/Market_Impact_Empirical_Evidence_Theory_and_Practice.pdf)
4. "Strict universality of the square-root law: A complete survey of the Tokyo Stock Exchange." arXiv:2411.13965 (2024) - [arXiv](https://arxiv.org/html/2411.13965v3)
5. "The two square root laws of market impact." arXiv:2311.18283 (2023) - [arXiv](https://arxiv.org/pdf/2311.18283)
6. "High-frequency liquidity in the Chinese stock market: Measurements, patterns, and determinants." (2025) - [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X25000186)
7. "Microstructure of the Chinese stock market: A historical review." (2024) - [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0927538X24003032)
8. Zipline VolumeShareSlippage implementation - [GitHub](https://github.com/quantopian/zipline/blob/master/zipline/finance/slippage.py)
9. Baruch MFE, "Optimal Execution: Models and Model Implications." (2016) - [Slides](https://mfe.baruch.cuny.edu/wp-content/uploads/2012/09/Chicago2016OptimalExecution.pdf)
10. "Forecasting Intraday Volume in Equity Markets with Machine Learning." arXiv:2505.08180 (2025) - [arXiv](https://arxiv.org/html/2505.08180v1)
11. 开源证券, "市场微观结构研究系列(29)" (2024) - [发现报告](https://www.fxbaogao.com/detail/4984776)
12. BigQuant, "竞价相关因子研究" - [Link](https://bigquant.com/square/paper/cd07e2e7-68ae-47a5-8d41-f166e88700b2)
13. Kyle, A.S. "Continuous Auctions and Insider Trading." Econometrica 53(6), 1985.
14. Almgren, R. "Direct Estimation of Equity Market Impact." (2005) - [Paper](https://www.cis.upenn.edu/~mkearns/finread/costestim.pdf)
15. 金纳科技, "交易成本分析" - [Link](http://genus-finance.com/home-news-id-1011.html)
