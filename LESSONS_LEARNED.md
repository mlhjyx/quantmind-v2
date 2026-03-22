# LESSONS_LEARNED.md — 经验教训记录

> TEAM_CHARTER §6.2要求。每个教训记录：事件+根因+改进措施+执行状态。

---

## LL-001: 研究组任务遗漏 (2026-03-22)

**事件**: Sprint 1.1期间，研究报告#1的3项并行任务（IVOL验证/bp_ratio评估/波动率自适应阈值）全部未启动。用户发现后才补启动。

**根因**: Team Lead编码组注意力占满后忘了分配研究组任务。违反§1.6"编码组和研究组同时工作"规则。

**改进措施**: 每个Sprint开始时，Team Lead必须同时列出编码组和研究组的任务清单，不允许只列编码组。格式：
```
Sprint X.Y 任务分配
编码组:
  arch: ...
  qa: ...
研究组:
  quant: ...
  factor: ...
  strategy: ...
  risk: ...
```

**执行状态**: Sprint 1.2开始时按此执行。

---

## LL-002: 持仓膨胀bug — _apply_turnover_cap并集问题 (2026-03-22)

**事件**: 1年模拟发现持仓从20膨胀到43只。

**根因**: `_apply_turnover_cap()`对target(20只)和prev(20只)取并集blend，产出30+持仓。换手率上限50%保护了旧持仓不被卖出，导致累积膨胀。

**改进措施**: blend后只保留target_codes中的股票。添加了qa测试6个用例覆盖。

**执行状态**: ✅ 已修复+测试通过。

---

## LL-003: MDD计算peak初始化bug (2026-03-22)

**事件**: quant审查发现`performance_repository.py`的`get_rolling_stats()`中MDD的peak初始化为最新NAV而非最早NAV。

**根因**: 数据是DESC排序，peak应从时间正序第一个(navs[-1])开始，但代码写了navs[0]（最新的）。

**改进措施**: 修复为`peak = navs[-1]`。强调：涉及时序计算时必须明确数据排序方向。

**执行状态**: ✅ 已hotfix。

---

## LL-004: 模拟脚本时序与生产不一致 (2026-03-22)

**事件**: 5天模拟和1年模拟（第一版）中，同一天运行signal+execute，导致execute读不到当天signal写的信号（execute去查前一天），月度调仓从未触发。

**根因**: 模拟脚本没有模拟T日signal→T+1日execute的真实时序。

**改进措施**: 修改为`signal(td)` + `execute(trading_days[i+1])`。模拟脚本必须与生产crontab时序完全一致。

**执行状态**: ✅ 已修复，1年重跑12/12检查点通过。

---

## LL-005: execute阶段盲信signal的rebalance标记 (2026-03-22)

**事件**: execute阶段Step 5.6的独立验证`needs_rebalance(exec_date)`会覆盖signal的rebalance标记。在生产crontab下，T日月末signal标记rebalance，T+1日（下月第1天）execute验证"T+1不是月末"→覆盖为hold，永远不调仓。

**根因**: Step 5.6设计初衷是防止重复运行，但逻辑错误——不应该用exec_date验证调仓条件（调仓决策是signal phase在T日做的）。

**改进措施**: execute信任signal的rebalance标记，仅在信号过时(>5天)时覆盖。

**执行状态**: ✅ 已修复。

---

## LL-009: 因子正交 ≠ 选股正交 (2026-03-22)

**事件**: Strategy评估红利低波候选策略时，预估与基线corr=0.10-0.25（因子层面正交）。quant实测选股月收益相关性=**0.778**（严重高估分散化效果）。

**根因**: dv_ttm(股息率)和bp_ratio(市净率倒数)在因子空间中看似不同维度，但选出的Top50股票高度重叠——银行/煤炭/公用事业同时是高股息和高BP的股票。因子正交不等于持仓正交。

**改进措施**: 以后strategy评估候选策略时，必须让quant跑**选股重叠度验证**（Top-N持仓的月收益相关性），不能只估算因子层面的corr。写入评估标准：
- 因子corr < 0.3 ← 必要条件但不充分
- **选股月收益corr < 0.3** ← 充分条件，必须实测

**执行状态**: 写入STRATEGY_CANDIDATES.md评估标准。

---

## LL-010: 两套代码路径用不同默认配置导致Sharpe误诊 (2026-03-22)

**事件**: arch用run_backtest.py跑出Sharpe=0.50，诊断脚本用相同5因子跑出1.05。差异100%——原因是run_backtest.py默认用8因子（含3个弱因子），不是Paper Trading的5因子。导致全团队紧急暂停crontab，浪费数小时排查。

**根因**: run_backtest.py的SignalConfig默认8因子列表与PAPER_TRADING_CONFIG的5因子不一致。两个入口用不同配置，没有统一配置源。

**改进措施**:
- run_backtest.py的默认因子列表改为从PAPER_TRADING_CONFIG读取
- 所有回测入口必须使用同一个配置源，不允许各自定义默认值
- CLAUDE.md新增规则：策略参数有且只有一个权威来源(PAPER_TRADING_CONFIG)

**执行状态**: arch §3.6.1自主修复。

---

## Phase 0 复盘总结 (2026-03-22)

### 共同模式

将8个P0 bug分为4类：

**A. 金融领域知识缺失（2个）**
- #1 momentum方向反转 — 不了解A股动量为负的市场特征，因子方向设反
- #6 reversal因子3月缺失 — full因子集补算逻辑不完整，遗漏边界月份

**B. 时序/状态机错误（3个）**
- #4 days_gap假期误杀 — 自然日vs交易日混淆，国庆/五一7天自然日触发误杀
- #5 L1阻止月度调仓 — L1风控没区分"异常调仓"和"正常月度调仓"，一刀切阻止
- #8 模拟脚本时序错误 — signal+execute同天运行，破坏T日→T+1日时序契约

**C. 集合/边界逻辑错误（2个）**
- #2 持仓膨胀20→43 — 并集blend导致持仓只增不减，缺少max_positions硬约束
- #3 needs_rebalance覆盖 — execute用exec_date重新验证调仓条件，覆盖signal的正确决策

**D. 数值计算方向性错误（1个）**
- #7 MDD peak初始化 — DESC排序数据取[0]当peak，方向搞反

**核心规律**：8个bug中有5个（#1/#4/#5/#7/#8）的本质是**"隐含假设未显式化"**：
- #1 假设动量方向为正
- #4 假设间隔=自然日
- #5 假设L1应拦截所有调仓
- #7 假设数据是ASC排序
- #8 假设同天运行等价于次日执行

剩余3个（#2/#3/#6）是**边界条件遗漏**：并集膨胀、跨阶段状态传递、补算完整性。

### 根因分析

**1. 缺乏"假设清单"机制**
每个模块内部的隐含假设（数据排序方向、日期类型、因子方向）没有显式文档化。开发者脑中的假设和代码实际行为不一致时，无人发现。

**2. 测试覆盖偏向happy path**
Phase 0的测试主要验证"正常流程能跑通"，缺少：
- 边界条件测试（假期前后、月末月初交界、满仓/空仓极端）
- 不变量断言（持仓数<=max_positions、因子数=预期数、数据排序方向）
- 跨模块集成测试（signal→execute时序、因子计算→信号生成完整性）

**3. 代码审查缺少"防御性检查清单"**
review时关注"代码能不能跑"，没有系统性检查：
- 这个函数对输入数据的排序有假设吗？
- 集合操作后size是否符合预期？
- 时间相关计算用的是交易日还是自然日？

**4. 模拟环境与生产时序不一致**
模拟脚本"图方便"把signal+execute放同一天跑，破坏了T/T+1时序契约。任何简化生产时序的测试都会掩盖时序bug。

### Phase 1 改进措施

#### 措施1: 强制不变量断言（Invariant Assertions）

在关键路径插入runtime断言，生产环境也不关闭：

```python
# 每个模块必须定义自己的不变量
class PortfolioInvariants:
    @staticmethod
    def check(positions: list, config: dict):
        assert len(positions) <= config['max_positions'], \
            f"持仓{len(positions)}超过上限{config['max_positions']}"
        assert sum(p.weight for p in positions) <= 1.01, \
            f"总权重{sum(p.weight for p in positions)}超过100%"

class FactorInvariants:
    @staticmethod
    def check(df: pd.DataFrame, expected_factors: list, date: date):
        missing = set(expected_factors) - set(df['factor_name'].unique())
        assert not missing, f"{date}缺失因子: {missing}"

class TimeSeriesInvariants:
    @staticmethod
    def check_ascending(series: pd.Series, name: str):
        assert series.index.is_monotonic_increasing, \
            f"{name}数据必须升序排列，实际首尾: {series.index[0]}→{series.index[-1]}"
```

**执行标准**: 每个PR必须包含该模块的不变量断言，缺少则打回。

#### 措施2: 交易日历强制使用工具函数

禁止在业务代码中直接做日期差计算。所有"N天前/后"必须走统一工具：

```python
# 唯一合法的日期间隔计算方式
from app.utils.trading_calendar import trading_days_between, nth_trading_day_before

# ❌ 禁止
gap = (today - last_date).days  # 自然日，假期会误杀

# ✅ 必须
gap = trading_days_between(last_date, today)  # 交易日
```

**执行标准**: ruff自定义规则或pre-commit hook检测`(date1 - date2).days`模式并报错。

#### 措施3: 模拟脚本必须与生产crontab时序bit-identical

```python
# 模拟脚本的时序必须这样写（已在LL-004修复，Phase 1强制）
for i, td in enumerate(trading_days):
    run_signal(td)           # T日: 盘后信号生成
    if i + 1 < len(trading_days):
        run_execute(trading_days[i + 1])  # T+1日: 开盘执行
```

**新增**: 模拟脚本启动时自动对比crontab配置，时序不一致则拒绝运行。

#### 措施4: 每个因子必须有方向声明和验证

```python
FACTOR_DIRECTION = {
    "momentum_20d": -1,    # A股动量反转，负方向
    "reversal_5d": +1,     # 短期反转，正方向
    "bp_ratio": +1,        # 低估值正向
    # ...每个因子必须显式声明
}

# 因子入库前自动验证: IC符号与声明方向一致
def validate_factor_direction(factor_name: str, ic: float):
    expected_sign = FACTOR_DIRECTION[factor_name]
    if np.sign(ic) != expected_sign and abs(ic) > 0.01:
        raise FactorDirectionError(
            f"{factor_name} IC={ic:.4f}，与声明方向{expected_sign}矛盾"
        )
```

#### 措施5: PR审查增加"假设检查清单"

每个PR的reviewer必须回答以下问题（加入PR template）：

```markdown
## 假设检查清单
- [ ] 数据排序方向：本PR中的时序数据是否有排序假设？假设是否显式验证？
- [ ] 日期计算：是否使用交易日工具函数？有无直接.days计算？
- [ ] 集合操作：并集/交集/差集后，结果size是否有上下界检查？
- [ ] 跨阶段状态：本模块的输出被下游怎么消费？下游会不会覆盖/误解？
- [ ] 因子完整性：涉及因子列表变更时，补算逻辑是否覆盖所有历史日期？
```

#### 措施6: 关键路径集成测试（端到端）

Phase 0缺少的不是单元测试，是跨模块集成测试：

```python
# tests/integration/test_signal_to_execute.py
def test_monthly_rebalance_across_month_boundary():
    """验证T日月末signal→T+1日月初execute能正确触发调仓"""

def test_holiday_gap_no_false_trigger():
    """验证国庆7天假期后不会触发异常检测"""

def test_full_factor_set_consistency():
    """验证补算后每个交易日的因子数量=预期因子总数"""

def test_turnover_cap_preserves_max_positions():
    """验证换手率限制后持仓数不超过max_positions"""
```

**执行标准**: Phase 1每个Sprint的QA验收必须包含集成测试通过。

### 流程改进

| 环节 | Phase 0做法 | Phase 1改进 |
|------|-----------|------------|
| 开发 | 隐含假设在脑中 | 每个模块README写明前置假设 |
| 测试 | happy path为主 | 不变量断言 + 边界测试 + 集成测试 |
| 审查 | "能跑就行" | 假设检查清单强制过 |
| 模拟 | 简化时序图方便 | 与生产bit-identical，不允许简化 |
| 因子 | 方向靠经验判断 | 方向显式声明 + IC自动验证 |
| 日期 | 随手写.days | 统一工具函数 + lint规则禁止裸算 |

## LL-011: Proxy分析≠正式回测，差异可达Sharpe 1.1个点 (2026-03-22)

**事件**: 候选4(大盘低波) strategy proxy分析显示Sharpe=1.009、MDD=-10.65%，50/50组合MDD=-15%（接近系统目标）。全团队据此将候选4升为P0。但SimBroker正式回测结果：Sharpe=-0.11、MDD=-50.27%。差异达1.1个Sharpe点。

**根因**: Proxy分析用"截面Top20等权月收益"估算策略表现，没有经过SimBroker的整手约束/滑点/涨跌停封板/调仓逻辑/资金T+1等真实交易摩擦。大盘低波Top10在正式回测中换手率更高、封板影响更大、整手误差累积更严重。

**改进措施**:
- 所有策略候选必须跑SimBroker正式回测才能做决策（不接受proxy估算）
- strategy的初步研究可以用proxy快速筛选方向，但§3.6.2正式提交前必须附正式回测结果
- 写入STRATEGY_CANDIDATES.md评估标准：新增"正式回测验证"为必要条件

**执行状态**: 写入评估标准。候选4已否决。

---

#### 措施7: LL-009/LL-010作为永久检查项

每次因子/策略评估和配置变更时必须检查：
- **LL-009**: 因子corr < 0.3不等于选股corr < 0.3。必须实测选股月收益相关性。
- **LL-010**: 所有回测/模拟/Paper Trading入口必须使用同一个配置源(PAPER_TRADING_CONFIG)。不允许各自定义默认参数。

### 总结

Phase 0的8个P0 bug不是随机的。它们集中暴露了一个系统性问题：**隐含假设没有被代码显式表达和自动验证**。Phase 1的核心防线不是"更小心"，而是让错误的假设在写入代码的瞬间就被机器拦截。6项措施中，措施1（不变量断言）和措施2（交易日历强制工具函数）优先级最高，应在Phase 1 Sprint 1.1第一周落地。
