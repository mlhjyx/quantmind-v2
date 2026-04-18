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

## LL-012: Team Lead管理模式从"被动响应"到"主动推进"(2026-03-22)

**事件**：用户至少4次提醒"研究组空闲""待办没跟进""工具导入忘了""strategy没任务了"。Team Lead每次汇报说"零空闲"但下次检查又发现多人空闲。

**根因**：
1. Team Lead把"管理"等于"分配任务+等agent结果"——缺少"持续跟踪+主动推进"
2. §1.6.2管理仪表板写了但执行率<30%
3. Agent完成后只处理结果，不检查其他人状态
4. §9.4研究制度只写入宪法没有执行机制

**改进措施**：
1. **每个agent结果处理后**，立即执行§1.6.2自检（不是"想起来才做"）
2. **研究组不存在"等待"状态**——本职完成后自动切换到§9.4研究任务
3. **Sprint任务清单在开始时就列全**（编码组+研究组），不是编码组先列研究组忘了
4. **3h定时不够**——应该每次agent批次完成后就检查全员+分配
5. 用户不应该是质量检查员——Team Lead必须在用户之前发现问题

**执行状态**：写入LL-012，从现在起严格执行。

---

#### 措施7: LL-009/LL-010作为永久检查项

每次因子/策略评估和配置变更时必须检查：
- **LL-009**: 因子corr < 0.3不等于选股corr < 0.3。必须实测选股月收益相关性。
- **LL-010**: 所有回测/模拟/Paper Trading入口必须使用同一个配置源(PAPER_TRADING_CONFIG)。不允许各自定义默认参数。

### 总结

Phase 0的8个P0 bug不是随机的。它们集中暴露了一个系统性问题：**隐含假设没有被代码显式表达和自动验证**。Phase 1的核心防线不是"更小心"，而是让错误的假设在写入代码的瞬间就被机器拦截。6项措施中，措施1（不变量断言）和措施2（交易日历强制工具函数）优先级最高，应在Phase 1 Sprint 1.1第一周落地。

## LL-013: IC分析必须用生产一致的基线因子集 (2026-03-23)
**来源**: quant v1.2 paired bootstrap
**问题**: batch7报告mf_divergence增量+1.12%，但用的基线含ln_market_cap/momentum_20而非实际v1.1的reversal_20/amihud_20。正确基线下增量仅+0.10%(p=0.387)
**规则**: 任何IC对比分析，基线因子集必须与PAPER_TRADING_CONFIG完全一致。脚本开头打印因子列表供核对

## LL-014: 资金流因子天然与市值/波动率高相关，必须中性化验证 (2026-03-23)
**来源**: alpha_miner batch 8 moneyflow depth
**问题**: big_small_consensus原始IC=12.74%，中性化后→-1.0%。mf_price_vol_ratio同理
**规则**: 所有新因子（特别是资金流/成交量类）必须做中性化后IC验证。原始IC>5%但中性化后<1.5%的标记为"虚假alpha"

## LL-015: 说了就要做，做了才算数 (2026-03-23)
**来源**: Team Lead说"启动中"但没spawn agent
**规则**: "启动"=Agent工具已调用。文字回复"开始执行"不算启动。用户问"在做吗"时如果没有running agent=失职

---

## LL-016: 执行机制不能依赖记忆 (2026-03-23)

**事件**: §1.6.2管理助理机制写入宪法后从未自动执行。LL-015（说了没做）第三次重犯。用户至少5次提醒"你又忘了"。

**根因**: 用"记住要做X"来解决"忘了做X"——死循环。写再多规则，如果执行依赖记忆，就会被忘记。

**改进措施**: 
- 在CLAUDE.md加入"每次回复前强制自检清单"（4项，不可跳过）
- 自检不通过时在回复开头写"⚠️自检发现问题"然后先修再答
- 不再新增"要记住做X"类规则——所有规则必须有强制触发机制

**本质**: 规则数量不等于执行质量。10条被执行的规则 > 100条被遗忘的规则。

**执行状态**: 已写入CLAUDE.md操作规则。

---

## LL-017: 单因子IC强≠组合增量正，等权合成有天花板 (2026-03-23)

**事件**: 连续两次验证"IC强因子加入等权组合后Sharpe下降"：
- mf_divergence: IC=9.1%(全项目最强) → 组合增量+0.10%(p=0.387, NOT JUSTIFIED)
- PEAD: IC=5.34%(中性化后更强) → 组合Sharpe-0.085（反而降低）

**根因**: 等权合成假设每个因子贡献相等。当已有5个因子覆盖了主要alpha维度后，新因子的边际信息被等权稀释。即使新因子IC很高，它占1/6=16.7%的权重，但如果它与其他因子的预测目标有隐性重叠（即使截面corr低），等权组合无法利用它的独特价值。

**核心教训**:
- 等权合成有天花板（约5-6因子是局部最优）
- 超过后边际收益为负——新因子反而稀释了强因子的信号
- 因子的真正价值需要非线性合成方法（ML）才能释放
- 单因子IC是入池的必要条件，不是组合提升的充分条件

**改进措施**:
- v1.1等权5因子锁死，不再尝试等权框架内升级
- alpha_miner目标改为"为LightGBM准备特征池"而非"找能加入等权的因子"
- Sprint 1.8 LightGBM用20+因子作特征，OOS Sharpe必须>1.054
- 中间尝试分层排序等非等权线性方法作为过渡

**执行状态**: v1.1锁定，分层排序回测启动中。

---

## LL-018: 线性因子合成方法全面比较——等权是局部最优 (2026-03-23)

**事件**: 测试了6种因子合成方法(等权/IC加权3种/分层排序3种/因子专属池)，全部对比v1.1基线(等权5因子Sharpe=1.054)。

**结果**:
- IC加权(纯IC/IC_IR/衰减IC): 最好1.24，都劣于等权1.29(旧基线)
- 等权+新因子(mf_divergence/PEAD): 组合Sharpe反而下降
- 分层排序A/B/C: Sharpe 0.666-0.820，全部劣于等权
- 因子专属池D: Sharpe 0.312，最差

**根因**: 
1. 等权的简单性正是它的优势——不引入权重估计误差
2. 5因子已覆盖主要alpha维度，更多因子在线性框架下边际为负
3. 分层/专属池限制选股池→损害分散化→Top15多样性下降
4. DeMiguel et al.(2009)理论在A股得到验证：1/N在有限因子下近似最优

**教训**: 9种线性合成方法全面测试（改权重×4+改时序×2+改选股池×2+改因子×1），全部劣于等权。突破需要非线性（LightGBM可以学习因子间交互效应、动态权重、条件选择——正是线性方法无法做的）。

**执行状态**: v1.1锁定60天Paper Trading。Sprint 1.8 LightGBM是下一个突破点。

---

## LL-019: Agent状态判断必须验代码，不信文档 (2026-03-25)

**事件**: Sprint 1.3b复盘时，risk agent说"L1/L2熔断连续两个Sprint逾期，最大风控失职"。Team Lead采信并写入复盘汇总。实际检查代码发现L1/L2/L3/L4早已在run_paper_trading.py:175-744完整实现且集成到Paper Trading管道。

**根因**: PROGRESS.md写着"🔨 L1/L2熔断机制"（2026-03-20旧信息，5天未更新）。risk agent读了文档就下结论，没grep代码验证。Team Lead也没独立验证就采信。两层防护都失效。

**改进措施**: 宪法V3.1新增铁律5"下结论前验代码"。§6.3交叉验证强化为"必须验代码/数据，不是读文档然后同意"。

**执行状态**: 写入宪法V3.1。

---

## LL-020: PROGRESS.md维护不能依赖"每天更新" (2026-03-25)

**事件**: V3.0§7写了"每天结束更新PROGRESS.md"，但从3/20到3/25五天没人更新。Sprint 1.1~1.3b的大量进展只在CLAUDE.md compaction段有，PROGRESS.md完全空白。

**根因**: "每天更新"没有强制触发点。写文档和写代码是不同agent，信息传递断裂。违反LL-016"执行不能依赖记忆"。

**改进措施**: 宪法V3.1新增铁律6"Sprint结束必更新PROGRESS.md"。§7.3定义3个强制触发点替代"每天更新"。Compaction段分稳定层/动态层，动态信息只在PROGRESS.md维护一份。

**执行状态**: 写入宪法V3.1。

---

## LL-021: 关税冲击场景需纳入压力测试 (2026-03-25，迁移自RISK-007)

**事件**: 1年模拟中2025-04-07单日亏损-13.15%，原因为突发关税政策冲击导致全市场暴跌。

**影响**: 以Paper Trading当前NAV计算约亏损12.9万，会触发L1级别。Paper Trading 60天窗口（3月底至6月初）正值中美贸易政策不确定性较高时期。

**改进措施**: 此场景已加入压力测试场景库。作为L1/L2集成测试的必测用例。

**执行状态**: 场景已记录，L1/L2代码已实现（run_paper_trading.py:175-744）。

---

## LL-022: 研究不能片面——遇到问题必须主动查阅最新方法/论文/技术 (2026-03-25)

**事件**: V3.0→V3.1修订时，Team Lead仅凭已有知识写宪法，没有去搜索"量化团队最佳实践"、"LLM agent治理框架"、"MLOps实验管理"等外部资源。用户指出后，Team Lead搜索发现：
- Qlib Alpha158因子集（158个因子，我们只覆盖22个）
- Qlib RollingGen walk-forward框架（可直接参考）
- LawClaw宪法治理模式（agent不可修改自身规则）
- Gu Kelly Xiu 2020（94个ML特征，LightGBM截面预测经典论文）
- QuantaAlpha（LLM+进化策略自动挖掘因子）

如果不搜索，这些关键参考资料全部错过。

**根因**: Team Lead把"我已经知道的"当作全部，没有"我不知道的可能更重要"的意识。合伙人遇到问题应该主动研究，不是只靠脑子想。

**改进措施**:
- 宪法V3.2 §9新增第6条工作原则："遇到问题主动研究——搜索文献/开源项目/最佳实践，不只靠脑子想"
- 每个角色的研究方向（§10）明确列出了关注前沿+资源+应用
- Sprint规划时必须包含"本Sprint需要研究的问题"清单

**关键参考资源（已发现，待Sprint 1.4深入）**:
- [Qlib Alpha158](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml) — 因子池对标
- [Qlib RollingGen](https://qlib.readthedocs.io/en/latest/advanced/task_management.html) — Walk-Forward框架
- [Gu Kelly Xiu 2020](https://academic.oup.com/rfs/article/33/5/2223/5758276) — 94特征ML截面预测
- [QuantaAlpha](https://github.com/QuantaAlpha/QuantaAlpha) — LLM因子挖掘
- [R&D-Agent-Quant](https://arxiv.org/html/2505.15155v2) — 多Agent因子+模型联合优化
- [LawClaw](https://dev.to/nghiahsgs/i-built-an-ai-agent-that-governs-itself-separation-of-powers-for-llms-123) — AI agent宪法治理
- [MLOps for Quant](https://medium.com/@online-inference/mlops-best-practices-for-quantitative-trading-teams-59f063d3aaf8) — 回测作为一等公民

**执行状态**: 写入宪法V3.2 §9.6 + §10研究方向。Sprint 1.4已深入研究Alpha158和Gu Kelly Xiu 2020。

---

## LL-023: ML特征质量>数量，维度噪声比过拟合更危险（Sprint 1.4b）

**事件**: LightGBM用5基线特征OOS IC=0.0706，加入12个ML特征后OOS IC降到0.0478。SHAP显示ML特征有validation importance但OOS不泛化。所有含ML特征的配置best_iter=2（模型几乎无法学习）。

**根因**: 12个ML特征（KBAR/资金流/技术指标）覆盖率74-95%不等，引入的维度噪声稀释了5基线因子的信号。模型在高维空间中找不到比"第1棵树"更好的分裂路径，early stopping立即触发。

**改进措施**: 新因子入ML特征集前，必须先验证：(1) 单因子OOS IC > 0.02; (2) 与现有5因子的平均截面corr < 0.5; (3) 加入后LightGBM best_iter > 10（能持续学习）。

**执行状态**: 已写入Sprint 1.5特征筛选标准。

---

## LL-024: 全量入库前先小样本验证（Sprint 1.4b）

**事件**: 12个ML特征全量入库（553万行×12因子）耗时40分钟，但SHAP最终证明它们全部是噪声，不应入库。

**根因**: 跳过了小样本验证步骤，直接全量计算+写入DB。

**改进措施**: 新因子入库前强制小样本IC筛选（100只股票×1年，<10秒），IC>0.015且方向符合预期后才执行全量入库。

**执行状态**: 写入Sprint 1.5因子开发流程。

---

## LL-025: OOS评估时间段选择极大影响结论（Sprint 1.4b）

**事件**: 等权基线全期(2021-2025) Sharpe=1.03，但近3年(2023-2026) Sharpe=-0.125。LightGBM OOS Sharpe=0.869看似不达标（<1.10），但同期远胜基线。

**根因**: 2023年小盘因子全面失效（基线-38.82%），严重拖累近3年表现。不同评估窗口给出截然不同的结论。

**改进措施**: OOS评估必须同时报告：(1) 全期Sharpe+CI; (2) 滚动12月Sharpe时序; (3) 年度分解。不能只看单一数字。

**执行状态**: 已写入evaluate_lgb_vs_baseline.py的年度分解功能。

---

## LL-026: A股基本面因子在ML框架中仍然无效——方向关闭（Sprint 1.5）

**事件**: Sprint 1.5用6个基本面delta特征（roe_delta/revenue_growth_yoy/gross_margin_delta/eps_acceleration/debt_change/net_margin_delta）+ 2个时间特征加入LightGBM。F1 fold结果：OOS IC从基线0.0823暴跌到0.0439（-46.7%），best_iter从52降到6。

**历史累积**:
- Sprint 1.3b: 7个基本面水平值因子(roe_ttm等)全部FAIL（FACTOR_TEST_REGISTRY #21-28）
- Sprint 1.4b: 12个价量ML特征FAIL（维度噪声）
- Sprint 1.5: 7个基本面delta特征FAIL（即使用变化率替代水平值仍然失败）
- 三轮验证（水平值→线性合成→delta+ML），基本面方向彻底关闭

**根因**: A股基本面因子IC结构性偏弱（中性化后1-3%），原因是散户主导市场+财报质量差+壳价值效应。季度更新频率与月度调仓的频率不匹配导致stale signal问题。即使在LightGBM非线性框架中，弱基本面特征仍然稀释了强价量因子的信号（days_since_announcement的Gain=2966远超其他，模型过度依赖时间特征而非基本面内容）。

**Sprint 1.5b穷举验证（10种使用方式，8/10已测）**:

| # | 方案 | OOS结果 | 判定 |
|---|------|---------|------|
| 原始 | 7delta直接喂ML | IC=0.044(基线0.082) | FAIL |
| 1 | ROE宇宙预筛选 | Sharpe=-0.287 vs 0.644 | FAIL |
| 3 | 交互因子(3个) | IC≈0, t<2.5 | FAIL |
| 5 | 只加days_since | IC=0.070, iter=7 | FAIL |
| 6 | 只加top2 delta | IC=0.058, iter=51 | FAIL |
| 7 | ROE动量3Q平滑 | IC=-8.47%(方向反转) | FAIL |
| 8 | Piotroski简化F5 | 不测(用户决策) | SKIP |
| 9 | 双模型融合 | IC+0.006但M2质量差 | MARGINAL |
| 10 | 排除风险股 | Sharpe 0.738<0.831 | FAIL |

**改进措施**:
1. **基本面方向彻底关闭**（8/10 FAIL + 1 MARGINAL，LL-022穷举验证已完成）
2. 新特征入ML前必须通过"best_iter>10"门槛
3. 未来因子扩展方向：分析师预期修正（新信息源，非基本面变体）

**执行状态**: 用户确认关闭。Sprint 1.6转向Rolling ensemble + 分析师预期修正因子。

---

## LL-027: Team Lead系统性执行失败——未遵守宪法团队管理规则（Sprint 1.4-1.5全程）

**事件**: 整个Sprint 1.4到1.5期间，Team Lead：
1. 从未用TeamCreate建立持久化团队，全部使用一次性孤立agent
2. Spawn agent时从未读附录A的角色Spawn Prompt（§1.2违规）
3. Agent启动时缺失"角色定义+交叉预期+主动发现"（§1.3违规）
4. 被动执行用户指令，缺乏合伙人的主动思考（§1.5违规）
5. 用户多次提醒后才意识到问题

**根因**: Team Lead把自己定位为"任务分配器"而非"项目合伙人"。没有在session开始时认真阅读宪法全文，只是选择性地读了自己认为需要的部分。宪法存在但不执行等于不存在。

**改进措施**:
1. 每次新session开始，Team Lead必须读TEAM_CHARTER_V3.md §1全文（不是只读CLAUDE.md摘要）
2. Sprint开始时用TeamCreate建团队，Sprint结束时shutdown
3. 每次spawn前复制附录A的角色prompt，加上§1.3要求的4项信息
4. 每天自检：我今天是被动执行还是主动发现？

**执行状态**: 写入feedback记忆。下次session必须从TeamCreate开始。

**严重等级**: 最高——这不是技术错误，是管理意识缺失。

## LL-028: Spawn prompt必须包含设计文档完整路径（Sprint 1.9）

**问题**: Sprint 1.9 spawn arch时，只给了设计文档名（如"DEV_BACKEND.md"）没给完整路径（如`D:\quantmind-v2\docs\DEV_BACKEND.md`）。Agent没有跨session记忆，无法自行定位文件。

**根因**: §1.3要求"设计文档路径"但Team Lead理解为"文档名"即可。实际上agent需要完整路径才能执行Read操作。

**改进措施**: 每次spawn时§1.3的5个必填字段中"设计文档"项必须给完整路径。模板：
```
必读设计文档（编码前必须Read）：
- D:\quantmind-v2\docs\DEV_BACKEND.md
- D:\quantmind-v2\docs\DEV_BACKTEST_ENGINE.md
```

**执行状态**: Sprint 1.10已修正。写入feedback记忆。

**严重等级**: 中——不影响代码正确性但降低agent效率。

## LL-029: commit前必须完成复盘——不能"先commit再补"（Sprint 1.10）

**问题**: Sprint 1.10所有Task完成后直接git commit，跳过了宪法§5.2要求的复盘顺序（先更新PROGRESS.md→复盘→再commit）。违反铁律4和铁律6。

**根因**: 急于"完成"的心理——所有测试通过后觉得"大功告成"就直接提交了，忘记复盘是Sprint结束的**必须步骤**不是可选步骤。

**改进措施**:
1. 铁律4强制执行：commit message中必须包含"复盘已完成"标记
2. 复盘清单贴在commit前：§5.4复盘5问 + §5.5投资人3问 + PROGRESS.md更新 + CLAUDE.md决策表 + LL检查
3. 如果再次违反（≥3次），需要升级为Hooks强制检查

**执行状态**: 已补做复盘。写入feedback记忆。

**严重等级**: 中——不影响代码但影响知识积累和团队纪律。

---

## LL-030: 宪法流程是编码的前置条件，不能跳过（Sprint 1.11）

**事件**: Sprint 1.11开始时，Team Lead再次跳过宪法团队管理流程：
1. 没有TeamCreate就直接派ad-hoc subagent编码（违反§1.2）
2. 第一个arch agent没有包含V3.3附录A的完整角色Prompt+8项上下文（违反§1.3+LL-027重犯）
3. 用户两次提醒"别忘记宪法中的要求"后才纠正

**根因**: 与LL-027同根——急于"开始编码"的执行冲动压过了"先建团队"的流程纪律。尽管已有LL-027教训、feedback记忆、V3.3宪法全文都读过，但在执行时依然"知道但没做到"。根本问题不是"不知道规则"而是"执行优先级错误"：把编码当成Sprint第一步，而宪法要求团队建立才是第一步。

**改进措施**:
1. **Sprint启动清单（强制顺序，不可跳过）**:
   ```
   Step 0: 读PROGRESS.md + 记忆文件恢复上下文 ✓
   Step 1: 读TEAM_CHARTER_V3.3.md全文 ✓
   Step 2: TeamCreate建团队 ← 必须在任何编码之前
   Step 3: 按§5.1列出编码组+研究组任务清单
   Step 4: 按附录A + §1.3构建spawn prompt
   Step 5: spawn agent开始编码 ← 最早在这一步
   ```
2. **同一规则≥3次违反（LL-027是第1次，本次是第2次）**: 如果第3次再犯，必须升级为Hooks强制检查（§13.2要求）
3. **在CLAUDE.md的compaction保护段落加入**: "Sprint启动第一步=TeamCreate，不是编码"

**执行状态**: 已记录。Sprint 1.11中已纠正（TeamCreate完成，后续agent使用完整spawn prompt）。

---

## LL-031: 宪法新增规则必须立即执行，不能"知道了下次再说"（Sprint 1.13-1.15）

**事件**: 用户在Sprint 1.13前提交了宪法更新（ac25825），新增§5.2任务复盘、§5.6 Sprint完成报告模板、verify_completion.py交叉审查检查。Team Lead阅读后回复"看到了，下次严格执行"，然后连续三个Sprint系统性跳过：
- §5.3 Sprint结束10步流程（1.13/1.14完全跳过）
- §6.5 交叉审查（1.14/1.15未spawn审查agent）
- §5.1 doc_drift_check（三个Sprint都没运行）
- §1.2 每角色≤2任务（1.15给arch分了4项）
- BLUEPRINT/TECH_DECISIONS更新（三个Sprint都没做）

**根因**: 与LL-027/LL-030同根但更严重——不是"不知道规则"甚至不是"忘记规则"，而是**主动选择跳过**。为了追求"一晚上交付3个Sprint"的效率，系统性地省略了所有不直接产出代码的治理流程。用户明确纠正："我不希望是快速交付，我希望是完整的，慢点都可以，保证质量。"

**改进措施**:
1. **每Sprint任务数上限**: 宁可减少编码任务，也必须留时间执行§5.3全部10步
2. **Sprint结束检查清单（必须逐项打勾）**:
   - [ ] §5.3-1: PROGRESS.md更新
   - [ ] §5.3-2: 复盘5问+投资人3问
   - [ ] §5.3-3: 改善建议汇总
   - [ ] §5.3-4: LESSONS_LEARNED.md
   - [ ] §5.3-5: TECH_DECISIONS.md
   - [ ] §5.3-6: 规则执行记分卡
   - [ ] §5.3-7: 审计日志审查
   - [ ] §5.3-8: BLUEPRINT更新
   - [ ] §5.3-9: §5.6报告输出
   - [ ] §5.3-10: Git commit + tag
3. **这是同一规则第3次违反**（LL-027→LL-030→LL-031），按§13.2必须升级为Hook强制检查

**执行状态**: ✅ 已升级执行机制。verify_completion.py Stop hook中 check_progress_updated + check_cross_review_executed 从提醒(exit 0)升级为阻断(exit 2)。audit_log.py 升级记录subagent_type。TEAM_CHARTER §13.4已记录升级规则。Sprint 1.16起强制执行。

---

## LL-032: Agent声称"已安装依赖"不可信，必须验证import（Sprint 1.15）

**事件**: arch agent报告"依赖已安装: python-socketio, structlog"，但实际pip install未执行。导致test_websocket.py和test_logging_config.py collection失败（ModuleNotFoundError）。Team Lead手动pip install后才通过。

**根因**: Agent在subprocess中无法执行pip install（或执行了但在不同虚拟环境）。Agent报告基于"我执行了install命令"而非"我验证了import成功"。

**改进措施**:
1. Agent spawn prompt中新增要求: "安装新依赖后必须运行 `python -c 'import xxx; print(xxx.__version__)'` 验证成功"
2. Team Lead在验证agent产出时，遇到新依赖必须先检查是否已安装

**执行状态**: Sprint 1.15中手动修复。Sprint 1.16 spawn prompt将包含验证步骤。

**严重等级**: 高——LL-027同根问题，第2次违反。再犯必须升级执行机制。

---

## LL-033: 模块堆叠≠系统完成——每Sprint必须端到端集成验证（Sprint 1.13-1.18）

**事件**: Sprint 1.13-1.18连续6个Sprint产出了1361个测试、88% BLUEPRINT完成度、全栈12页面+Pipeline+GP+SHAP。但安装fastapi后发现Factor API返回500（factor_registry列名不匹配），暴露出严重的集成问题：
- 前端全部使用mock数据，没有一个页面连通真实后端API
- PipelineOrchestrator只在内存模式测试（conn=None）
- GP Engine从未在真实A股数据上运行
- WebSocket挂载了但没有调用方emit
- SHAP/lambdarank没有用真实LightGBM模型测试

用户指出："不要功能都有了，但是功能之间的协同没有。不希望是摆设。"

**根因**: 每个Sprint的agent只做单元测试验证自己的模块，从未启动完整服务栈（FastAPI+PG+Redis）验证模块间协同。BLUEPRINT完成度统计的是"文件存在"，不是"端到端可用"。Team Lead追求Sprint数量而非集成质量。

**改进措施**:
1. **每个Sprint必须包含集成验证任务**: 启动FastAPI+PG → 调用API → 验证响应（不是只跑pytest）
2. **前端开发后必须至少1个页面连通真实API验证**（不能全mock）
3. **新引擎/Pipeline必须用真实数据跑一次**（哪怕小样本100只×30天）
4. **BLUEPRINT区分"文件存在度"和"端到端可用度"两列**
5. **Sprint 1.19定为集成Sprint**: 不加新功能，专门修复集成问题

**执行状态**: 用户2026-03-28指出。Sprint 1.19将作为集成Sprint执行。

---

## LL-034: SQLAlchemy text()中不用PG专有::type语法（Sprint 1.30B）

**事件**: Portfolio/Risk/Execution/Report/PaperTrading 5个API文件共17处使用`:sid::uuid`（PostgreSQL专有cast语法），SQLAlchemy的`text()`将`::uuid`误解析为命名参数`:uuid`，导致所有带strategy_id的查询静默返回空结果。Portfolio页面显示0持仓而Dashboard显示15持仓，排查耗时30分钟。

**根因**: PG的`::type`语法在原生psycopg2中可用，但在SQLAlchemy text() binding中与`:param`命名参数语法冲突。开发时用psycopg2直接测试通过，但通过FastAPI+asyncpg调用时失败。没有统一的SQL编写规范。

**改进措施**:
1. **全局规范**: SQLAlchemy text()中一律使用`CAST(:param AS type)`替代`:param::type`
2. **代码审查checklist**: 新增SQL text()检查项——禁止PG专有cast语法
3. **grep守卫**: 可在pre-commit hook中检查`::uuid\|::int\|::text`出现在text()附近

**执行状态**: Sprint 1.30B已修复全部17处。规范已记录。

---

## LL-035: 新API端点必须同步写前端适配层（Sprint 1.30B）

**事件**: 后端API返回`{total, items}`但前端期望`[]`（backtest/history）；后端返回`run_id`但前端期望`task_id`（mining/tasks）；后端返回嵌套结构但前端期望扁平结构（factors/report）。3个crash + 3个数据不匹配，全部因为前后端开发时未同步适配。

**根因**: 后端和前端在不同Sprint开发，API响应格式在后端变更后，前端适配层（api/*.ts）未同步更新。适配层直接`return res.data`透传，无类型转换。开发者倾向"先把后端写好，前端后面再对"，导致集成时大面积崩溃。

**改进措施**:
1. **同步开发**: 每个新API端点，必须同时写前端适配层（包含响应格式转换+字段默认值+null guard）
2. **适配层模式**: `apiClient.get<any>()` → map/transform → return typed object，不直接透传
3. **集成验证**: 新端点完成后必须用preview验证前端能正确渲染

**执行状态**: Sprint 1.30B修复了4个适配层。规范已记录。

---

## LL-036: 因子入库IC口径必须与生产基线一致（Sprint 1.31）

**事件**: factor_onboarding.py的中性化使用截面zscore近似，而生产基线compute_factor_ic.py使用完整行业中性化。QA审查标记为违反铁律2（因子验证用生产基线+中性化）。入库后的gate_ic/gate_ir/gate_t与因子库显示的IC不一致，可能导致Gate误判。

**根因**: 入库服务为了快速交付，使用了简化的中性化方法。开发者意识到不一致但选择标注TODO而非立即修复。

**改进措施**:
1. **硬性要求**: 因子入库时的IC计算必须调用与生产基线完全相同的中性化函数
2. **共享函数**: 将中性化逻辑提取为`backend/engines/neutralizer.py`共享模块，compute_factor_ic.py和factor_onboarding.py统一调用
3. **验证**: 入库后IC与`/api/factors/{name}/report`返回值交叉验证，差异>5%报警

**执行状态**: 已记录为Sprint 1.32 P0任务。

---

## LL-037: 文档数字不信，必须跑代码验证（Step 6-D, 2026-04-09）

**事件**: CLAUDE.md和多处文档将5yr Sharpe 0.6095误标为"12年基线"。Step 6-D首次真跑12年后发现12yr Sharpe实际为0.5309，差距巨大。

**根因**: 5yr回测数字被多处复制粘贴时标签错误，无人实际跑12年验证。文档传抄导致错误扩散。

**改进措施**: 任何基线数字的来源必须标明`(来源: cache/baseline/xxx.json, 日期: yyyy-mm-dd)`。新增铁律22：文档跟随代码。

**执行状态**: Step 6-D已修正，12yr基线建立。

---

## LL-038: WF OOS不稳定说明策略regime-dependent（Step 6-D, 2026-04-09）

**事件**: Walk-Forward 5-fold OOS chain-link Sharpe=0.6336但std=1.52（UNSTABLE标记）。逐fold Sharpe: 0.44/1.44/-0.16/1.92/0.55。

**根因**: 策略依赖小盘暴露(SMB beta~1.09)，在小盘牛市(2021)暴利，在小盘熊市(2022-2023)亏损。非全天候alpha。

**改进措施**: 评估策略有效性不只看平均Sharpe，必须检查std和最差fold。std>1.0标记UNSTABLE。引入Size-neutral降低regime依赖。

**执行状态**: SN b=0.50已激活，WF OOS std改善中。

---

## LL-039: FF3归因揭示alpha来自SMB暴露非纯alpha（Step 6-D, 2026-04-09）

**事件**: Fama-French 3因子归因显示Alpha=+18.98%/年(t=2.90显著)，但SMB beta~1.09（定性，FF3构造corr=0.41非精确）。

**根因**: 5因子等权策略的选股偏向小盘(Top-20中小盘占比高)。部分"alpha"实际是SMB暴露的beta收益。

**改进措施**: 引入Size-neutral Modifier控制小盘暴露。b=0.50是最优平衡点——降低SMB暴露但保留足够信号强度。

**执行状态**: SN b=0.50已实施(Step 6-H)，MDD从-56.37%降至-39.35%。

---

## LL-040: IC口径不统一导致因子方向反转（Step 6-E, 2026-04-09）

**事件**: IVOL因子在factor_registry记录IC=+0.0667(direction=+1)，但用ic_calculator统一口径重算后IC=-0.1033(direction=-1)。符号完全反转。

**根因**: 不同时期的IC计算用了不同的中性化方法、收益定义、universe过滤。raw_value IC和neutral_value IC方向可以完全不同。

**改进措施**: 新增铁律19——IC定义全项目统一走`ic_calculator.py`。raw_value IC只作参考，不作入池/淘汰依据。已修正IVOL方向。

**执行状态**: 铁律19已生效，53因子12年IC(84K行)已重算入库。

---

## LL-041: Alpha衰减半衰期约6月，需要持续补充新因子（Step 6-E, 2026-04-09）

**事件**: IC retention分析显示5因子在12年内retention 0.84-1.04，没有系统性衰减。但逐年Sharpe波动大(4/12年为负)，说明alpha不是衰减而是regime-switching。

**根因**: 量价因子的有效性受市场regime(牛/熊/震荡)影响。2017/2018/2022/2023年负Sharpe对应小盘弱势期。

**改进措施**: 持续补充正交信号维度(行业动量/PEAD/基本面)，降低对单一regime的依赖。目标是不同regime里至少有一个维度有效。

**执行状态**: 阶段2规划中。

---

## LL-042: 因子替换需paired bootstrap验证（Step 6-F, 2026-04-10）

**事件**: 尝试用turnover_stability_20替换turnover_mean_20，paired bootstrap p=0.92（远不显著）。IC差异不到0.01，统计上无法区分。

**根因**: 窗口变体因子之间的信息量高度重叠(IC天花板0.05-0.06)，替换无法带来统计显著的改善。

**改进措施**: 因子替换必须用paired bootstrap p<0.05验证，不能只看IC数字大小。对于同源因子的窗口变体，默认预期是"不显著"。

**执行状态**: 已记录到已知失败方向。铁律5已要求paired bootstrap。

---

## LL-043: Size-neutral b值需WF验证，完全中性过度惩罚小盘（Step 6-F, 2026-04-10）

**事件**: 完全Size-neutral(b=1.0)损失11% Sharpe。b=0.50是最优平衡点：保留足够信号强度，同时降低MDD。b=0.75 OOS衰减39%。

**根因**: 策略的部分alpha确实来自小盘暴露。完全消除小盘暴露等于删除有效信号。需要部分保留。

**改进措施**: Modifier参数必须用WF OOS验证。inner Sharpe高不够，OOS衰减>20%说明过拟合。b=0.50 inner 0.68 vs OOS 0.6521(衰减4%)是健康的。

**执行状态**: b=0.50已在PT激活。

---

## LL-044: 噪声鲁棒性测试可快速排除fragile因子（Step 6-F, 2026-04-10）

**事件**: 对21个PASS因子加5%和20%高斯噪声重算IC。结果：0/21 fragile（20% retention全≥0.59）。CORE 5因子retention≥0.96@20%。

**根因**: 鲁棒的因子对小扰动不敏感，说明捕捉的是真实统计规律而非噪声拟合。

**改进措施**: 新增铁律20——新候选因子必须通过G_robust Gate(20% noise retention≥0.50)。测试成本极低(几分钟)，应作为标准评估步骤。

**执行状态**: 铁律20已生效。

---

## LL-045: Vol-targeting/DD-aware在等权框架下无效（Step 6-G, 2026-04-10）

**事件**: Vol-targeting 3方案(12%/15%/18%目标)全部损alpha。DD-aware sizing后视偏差严重(用未来drawdown信息)。组合叠加更差。

**根因**: 等权月度策略的波动率来自选股(beta暴露)而非仓位大小。缩减仓位不减波动率但减收益。DD-aware本质是用未来信息。

**改进措施**: Modifier层不再尝试直接控制波动率。降低MDD的正确路径是: Size-neutral降低SMB暴露+多信号维度分散化。记入已知失败方向。

**执行状态**: 已关闭，Partial SN是唯一有效Modifier。

---

## LL-046: Modifier叠加相互干扰，单一Modifier原则（Step 6-G, 2026-04-10）

**事件**: Vol-targeting + DD-aware叠加后Sharpe比单独任何一个都更差。两个Modifier的调整方向冲突。

**根因**: 每个Modifier都在调整仓位权重，多个Modifier叠加时信号被多次扭曲，最终偏离原始alpha信号。

**改进措施**: Modifier层采用"单一Modifier原则"——同一时刻只启用一个Modifier。如果未来需要多维度调整，应该在Portfolio Optimization层统一处理。

**执行状态**: 当前只启用SN b=0.50。

---

## LL-047: Regime检测线性模型无效（Step 6-E, 2026-04-09）

**事件**: 用5个宏观指标(GDP增速/PMI/CPI/M2增速/CSI300收益)做线性Regime检测，5指标全p>0.05。

**根因**: 市场regime转换是非线性、突变性的。线性回归无法捕捉。牛熊转换通常不是渐进的。

**改进措施**: 如果未来重新尝试Regime检测，应使用非线性方法(HMM/changepoint detection)。但当前优先级低于新信号维度探索。

**执行状态**: 已关闭。静态参数优于动态(LL-049)。

---

## LL-048: LightGBM瓶颈在数据维度非模型复杂度（Step 6-H, 2026-04-10）

**事件**: LightGBM 17因子WF: OOS IC=0.067(正但弱)，月度回测Sharpe=0.09≈0。IC正但选股完全无效。

**根因**: 3个原因——(1)IC→选股是非线性映射，弱IC的Top-N选股噪声极大；(2)月度换手成本吃掉微弱alpha；(3)17因子高度共线(量价同源)，信息维度不足。

**改进措施**: ML有效的前提是输入特征有足够的信息维度。当前5个量价因子IC同步(corr>0.6)，ML无法从中提取额外alpha。需要先扩展信号维度(阶段2)，再尝试ML。

**执行状态**: ML路径暂时关闭，优先阶段2信号维度探索。

---

## LL-049: Static parameter优于dynamic（Step 6-H, 2026-04-10）

**事件**: SN beta static b=0.50 (Sharpe=0.6287) > dynamic (0.5253) > binary (0.5669)。动态方法全面不如静态。

**根因**: 动态参数引入额外的预测噪声(预测beta本身就有误差)。在样本量有限的情况下，动态参数的过拟合风险大于潜在收益。Occam's razor成立。

**改进措施**: 默认使用静态参数。只有当动态方法在OOS上显著优于静态(paired bootstrap p<0.05)时才启用。"更复杂"不等于"更好"。

**执行状态**: 所有参数当前都是静态的。

---

## LL-050: WF inner vs OOS差距>15%说明过拟合（Step 6-H, 2026-04-10）

**事件**: SN b=0.50: inner Sharpe=0.68, WF OOS=0.6521（衰减4%，健康）。对比b=0.75: inner更高但OOS衰减39%（过拟合）。

**根因**: inner/OOS差距是过拟合的直接指标。差距>15%说明参数对训练集过度拟合，泛化能力差。

**改进措施**: 任何策略/参数的评估必须同时报告inner和OOS。衰减>15%直接拒绝。衰减<5%是理想的。4%衰减说明b=0.50泛化能力强。

**执行状态**: 已成为标准评估指标。

---

## LL-051: 开源方案优先——Qlib已实现90%自建功能（Step 6-H, 2026-04-10）

**事件**: 审计11份设计文档发现80%未实现。同时发现Qlib和RD-Agent已经实现了大部分设计功能(回测引擎/因子库/ML pipeline/portfolio优化)。

**根因**: 项目初期"自建一切"的决策导致大量设计停留在纸面。如果早期就评估开源方案，可以节省数月开发时间。

**改进措施**: 新增铁律21——先搜索开源方案再自建。任何新功能开发前先花半天搜索成熟开源实现。阶段0安排Qlib+RD-Agent技术调研。

**执行状态**: V3方案原则4"站在巨人肩膀上"已确立。

## LL-052: PT配置双源导致SN未生效——YAML有值但代码不读（2026-04-10）

**事件**: Step 6-H声称"SN b=0.50已激活PT"，`configs/pt_live.yaml`的`size_neutral_beta: 0.50`也已设置。但PT实际运行`PAPER_TRADING_CONFIG`来自`signal_engine.py:_build_paper_trading_config()`，该函数未设置`size_neutral_beta`，使用dataclass默认值0.0（关闭）。`config.py:Settings`类也无`PT_SIZE_NEUTRAL_BETA`字段。结果：PT从4/9起以b=0.0运行，SN从未生效。

**根因**: 配置双源——回测走YAML（config_loader.py解析），PT走.env→Settings→`_build_paper_trading_config()`。新增策略参数`size_neutral_beta`时只更新了YAML，没有同步到PT的.env→config.py→signal_engine.py链路。缺少运行时值验证步骤。

**改进措施**:
1. 新策略参数上PT前必须验证运行时实际值（打印`PAPER_TRADING_CONFIG.xxx`确认），不能只看YAML配置文件
2. PT停止/重启必须有checklist验证所有配置参数的运行时值
3. `config_guard.py:print_config_header()`已添加SN beta显示，PT启动时可视化确认
4. 修复：config.py添加`PT_SIZE_NEUTRAL_BETA`，.env设置0.50，`_build_paper_trading_config()`传入

**执行状态**: 已修复(config.py+signal_engine.py+config_guard.py)，.env受保护需用户手动添加。PT暂停中待全部门槛满足后重启。

---

## LL-053: pydantic-settings 读 .env 不 push os.environ — 生产代码读 token 必须 settings.X（Session 5, 2026-04-18）

**事件**: Session 5 末 Sub3-prep dual-write 监控脚本落地后, `scripts/dual_write_check.py` 用 `os.environ.get("TUSHARE_TOKEN")` 读 token, Servy 重启 Celery worker 场景下读不到 token, 整脚本走 exit=2 ERROR 分支. `backend/tests/smoke/test_mvp_2_1b_tushare_live.py` 同样 bug. 用户一句 "Step 0 这个我不是设置了吗? 在 .env 里面" 戳破.

**根因**: `app/config.py` 的 `class Settings(BaseSettings)` 通过 `env_file="backend/.env"` 读配置, pydantic-settings 只填充 **Settings 对象属性**, **不 push 到 os.environ**. 所以:
- `settings.TUSHARE_TOKEN` ✅ 有值
- `os.environ.get("TUSHARE_TOKEN")` ❌ None
- `os.environ["TUSHARE_TOKEN"]` ❌ KeyError

旧代码 (`scripts/archive/fetch_earnings.py` 等) 依赖 Servy service.xml 把 token push 到 process env, 但新代码 subprocess 启动 (Celery / 本地 CLI / pytest subprocess) 时这条链路不存在.

**改进措施**:
1. 生产代码读任何 `.env` 配置必须走 `from app.config import settings; settings.X`, 禁止 `os.environ.get("X")` fallback default
2. 归档脚本 (`scripts/archive/*` / `scripts/research/*`) 用 `os.environ` 不强制修 (非生产链路), 但新写代码必须 settings
3. 生产路径 grep 审计 (完成本 session, 2026-04-18): `trading_day_checker.py` / `tushare_api.py` / 3 个 archive pull_* / `dual_write_check.py` / smoke / DUAL_WRITE_RUNBOOK 全 SSOT 对齐 `settings.TUSHARE_TOKEN`
4. 铁律 34 (配置 SSOT) 覆盖本条 — 写在铁律 34 的延伸

**执行状态**: ✅ 已修复 (commit `b825cc2`). 生产链路全走 `settings.TUSHARE_TOKEN`. 研究/归档 3 处 `os.environ` 已确认非生产链路, 保留不改.

---

## LL-054: PT 状态必须实测 DB+Redis, 文档腐烂 8 天未被发现（Session 5, 2026-04-18）

**事件**: Session 5 末用户问 "pt 状态, 你核实过吗?" 促使实测. CLAUDE.md L573 原写 "PT 已暂停+清仓 2026-04-10" (且 LL-052 执行状态也写 "PT 暂停中"). 实测 Redis `portfolio:nav` + DB `position_snapshot`: PT 从未清仓, **连续持仓自 2026-04-02 起**, 到 2026-04-17 为 19 股 NAV ¥1,008,299 (+0.83%). **8 天文档腐烂从未被捕获**.

**根因**:
1. Session 间状态同步靠"抄", 不靠实测 — 前 session 写 "PT 暂停" 后, 后续 session 默认继承, 无人验证
2. 铁律 22 "文档跟随代码" 对 PT 状态这类**运行时状态**没有强制核实机制
3. LL-052 "PT 暂停中待全部门槛满足后重启" 结语当时是对的 (2026-04-10), 但后续 PT 恢复运行 (4-02 ~ 4-17 连续持仓) 没有同步更新 LL-052 或 CLAUDE.md L573
4. PT 状态散在 3 处 (CLAUDE.md L573 / LL-052 执行状态 / memory/project_qmt_live.md), 任一处更新另两处没跟

**改进措施**:
1. **PT 状态断言必须实测** (核心原则): 任何 "PT 暂停/重启/清仓/调仓" 陈述前必核 Redis `HGETALL portfolio:nav` + DB `SELECT * FROM position_snapshot ORDER BY date DESC LIMIT 7`, 禁止从 LESSONS_LEARNED / 旧 session memory / CLAUDE.md 历史文本抄
2. **PT 状态 SSOT**: 选定 CLAUDE.md L565-581 为 PT 状态唯一真相源, 其他文档只能 reference 不能 restate
3. **全局 audit 脚本**: Session 6 提议建 `scripts/platform_state_audit.py` 周度跑一次, 比较 Redis/DB 实测 vs CLAUDE.md 断言, drift 告警
4. **Session 关闭前必核 PT 状态** (补铁律 37 延伸): Session 结束前 handoff 必含 `python -c "from redis import Redis; r=Redis(); print(r.hgetall('portfolio:nav'))"` 实测截图

**执行状态**: ✅ CLAUDE.md L565-581 已写实测时间线 (commit `f37694b`, 2026-04-18). LL-052 结语未同步修改 (保留原文避免重复校订, 本 LL-054 作为"LL-052 运行时状态已过期"的声明). Session 6 平台化 scripts/platform_state_audit.py 待建.

---

## LL-055: handoff 数字凭印象写, 跨 session 累积腐烂 + PR governance 诞生（Session 6 开场, 2026-04-18）

**事件**: Session 5 末 `memory/project_sprint_state.md` 顶部 frontmatter description 写 "20 commits / 2 commits ahead of origin", L106 "main branch, 2 commits ahead of origin (push 过 18 个)". Session 6 开场用户问 "接下来做什么?" 我推荐 #1 = push 2 commits. 实测 `git status`: **"up to date with origin/main"**, 0 ahead. handoff 数字是腐烂, push 任务本不存在. 同时连带发现 sprint_state L98 的 planning gap (`docs/mvp/MVP_2_1c_*.md` 不存在) 是真实存在的.

**根因**:
1. handoff 写完后 commit + push 是两步, push 之间 Claude 写 handoff 时 commits 仍是 ahead, push 后 ahead 变 0 但 handoff 没回写
2. 铁律 22 "文档跟随代码" 没覆盖**手写 handoff 数字** (memory file 不在 git working tree, post-commit hook 看不到)
3. 跨 session 状态同步靠"抄", 与 LL-054 (PT 状态腐烂 8 天) 同源
4. AI 高速产出 + 单人无审查 = 累积腐烂无人发现

**改进措施**:
1. **handoff 数字必实测** (Session 6 即生效): 写 "X commits ahead" 必前 `git status` + `git log --oneline origin/main..HEAD` 实测, 禁凭印象 / 抄上 session
2. **PR 分级审查制 (新铁律 42)**: AI 提议高风险代码改动必走 PR (feature branch + 自审 + 用户 merge), 给跨 session 状态一个"暂停 + revisit" buffer. 文档/memory 类允许直 push (低风险)
3. **Session 关闭前 git status 必核** (补铁律 37 延伸): Session 结束前 handoff 必含 `git status` 实测输出 + `git log --oneline origin/main..HEAD` 验证 ahead 数

**执行状态**: ✅ Session 6 开场已修 sprint_state 5 处 ("2 ahead" → "0 ahead" + planning gap closed, 见 sprint_state L3/L10/L63/L98/L105). 铁律 42 (PR 分级) 本 commit 落地 (CLAUDE.md L459-466). PR workflow Session 6+ 实施 (高风险代码改动开 feature branch + PR; 文档类继续直 push 例外).

---

## LL-056: MVP smoke ≠ dual-write, 完成前必跑跨系统一致性验证（Session 6 中段, 2026-04-18）

**事件**: Session 5 末 Sub3-prep (cf86447) commit msg 声明 "硬门全绿: tushare live smoke 3 字段覆盖 97.8% + 29 unit PASS + regression max_diff=0". Session 6 开场用户提议 "5 天窗口不能模拟吗?" 触发 backfill 过去 19 交易日 dual-write check. **结果 19/19 全 FAIL**, 暴露 Sub3-prep 层 3 类未捕获 drift:
1. `volume` 精度 (Tushare `vol` 返 float, 老 fetcher int cast, dual_write_check 脚本层没模拟 DataPipeline 入库 cast)
2. `up/down_limit` 304 行 `only_old_nan` (全是 BJ 股, 老 fetcher 不合 stk_limit API 为 BJ 股) — **新路径补历史缺, feature 非 bug**
3. `codes_only_in_new` ≤ 9 行 (FK 过滤噪音, MVP 2.1b L173 设计意图) — 脚本判定过严不符合本设计

**根因**:
1. **smoke ≠ dual-write**: smoke 只验 API 返回格式 (schema 对), 不验**新老系统一致性** (数据值对齐)
2. Sub3-prep 只跑 smoke 就声明 "硬门全绿", 没在 MVP 完成前跑 backfill 类验证
3. `dual_write_check.py` 严判 "100% bit-identical" 不符合 MVP 2.1b L173 "≤50 FK 噪音正常" 设定, 也不符合 Tushare 真实数据行为 (API 偶尔历史修正 + float 精度 + 历史精度演进如 amount 2026-04-08 前后 5 元级 → 0.01 元级)
4. 跨系统一致性验证缺 per-column tolerance 工程 (业界标准, MLOps Uber Michelangelo / Netflix Metaflow 均有)

**改进措施**:
1. **MVP 完成前必跑跨系统验证** (本 LL 核心): 涉及新老路径并行的 MVP (如本 Sub3-prep), commit claim "硬门全绿" 前必跑 dual-write backfill 或等价验证, 不能只 smoke
2. **Per-column tolerance 业界标准设计**: `scripts/dual_write_check.py::_COL_TOLERANCE` 加: 价格列 1e-6 严 / volume 100 股 (1 手) / amount 10 元 (Tushare 精度级)
3. **Historical_gap_filled 识别**: `only_old_nan > 0 && only_new_nan == 0` = 新路径补老 DB 历史缺失, feature 非 drift (LL-056 入册前判 FAIL)
4. **Backfill 模拟 = 生产等价**: 硬门字面 "5 交易日" 不限未来, 过去 5+ 天 backfill 等价甚至更强 (节省等待时间 + 提前暴露 bug), 业界标准做法
5. **非交易日 SKIP**: `backfill` 检测 (old=0 new=0) 自动 SKIP 不计 fail, 修 exit code 逻辑

**执行状态**: ✅ `scripts/dual_write_check.py` 修 (+67/-14 行) + `backend/tests/test_dual_write_check.py` 新增 11 unit test (全绿) + `docs/ops/DUAL_WRITE_RUNBOOK.md` 加硬门细则 + backfill equivalence 章节 + MVP 2.1c 设计稿 v1.1 update (drift 发现 + Sub3 main 2026-04-20 unblocked). **Backfill 最终: 19 PASS / 0 FAIL / 9 SKIP**, 硬门 #1 达成. Sub3 main 下周一 2026-04-20 可启动.

---

## LL-057: head/tail truncate 隐藏关键 evidence + 多步骤实测必查全输出（Session 6 末, 2026-04-18）

**事件**: Session 6 末用户问 "PT 每日 signal 怎么自动跑". 我用 `powershell Get-ScheduledTask | head -25` 列出 8 个 Task, 断言 "QuantMind_DailySignal 不存在 / setup_task_scheduler 设计 13 个但实际 8 个 / 9 个 missing". 用户截图 pt_watchdog 钉钉告警 + 提供反证, 我重跑 `Out-String -Width 200` 不 truncate, 实测**18 个 Task** 全注册 (12/13 设计的全在, 仅 QuantMind_GPPipeline 缺), 包括我说"不存在"的 QuantMind_DailySignal Ready + QuantMind_PT_Watchdog Ready. **6 处错误断言全是 truncate 误导**.

**根因**:
1. **head/tail 截断作 verify**: 我习惯 `head -25` 限输出 (token 经济), 但当输出 > 25 行时, **truncate 把后面的 evidence 全埋了**, 我看到截断后的"完整"列表却以为是真实全集
2. **没核 truncate 是否完全**: PowerShell `Format-Table` 默认按 console width auto-truncate 列, 我没 `Out-String -Width 200` 强制完整输出
3. **凭部分 evidence 跳到结论**: 看到 "8 Task" 就断言"design 13 vs actual 8 = 5 missing", 没核每一个名字是否在/不在
4. 与 LL-055 (handoff 凭印象) / LL-054 (PT 状态凭文档抄) 同源 — **不严谨实测的不同表现**

**改进措施**:
1. **verify 类查询禁 head 截断** (本 LL 核心): 跑 `Get-ScheduledTask | Out-String -Width 200` 强制完整 / `schtasks /query /fo csv /nh` 全列 / 必要时 `--no-truncate` flag. 任何 verify 类查询 head 不超过预期 max 数量 + 10 buffer.
2. **断言"X 不存在"前必跑精确查询**: `Get-ScheduledTask -TaskName "X" -ErrorAction SilentlyContinue` 单点查 (而非依赖 filter 列表), 返 None 才说不存在
3. **多步 verify 序列**: 当 verify 输出 ≥ 20 项, 自动用 `wc -l` / `Measure-Object` 数 row count 二次确认, 与 head 输出对齐
4. **报告 evidence 时标 "snapshot or truncated"**: 给用户 list 时明示是否完整, 让用户能判断是否需要 deeper query

**额外发现 (副产物, Session 7 待办)**: 调查时发现 04-17 周五 PT signal Task LastRunResult=0 但 signals 表 0 records (signal_latest_date 仍 04-16). app.log 04-17 16:30:21~25 显示 **5 个进程同时启动**反复 "日志系统已配置" + QMT 连接失败. 怀疑 acquire_lock 抢锁 silent skip 早退. **PT 实际 04-16 后已断 2 天未生成 signal**. 与本 LL 解耦, Session 7 深入调查 `scheduler_task_log` 表 + acquire_lock 实现.

**执行状态**: ✅ MVP 2.1c v1.3 update 加 18 Task 实测列表 + 修 v1.2 错误断言. CLAUDE.md L83 "pt_data_service 104 行" → "337 行" 修. LL-057 入册. PT 04-17 failure 进 Session 7 待办 (Sub3 main 不阻塞).

---

## LL-058: PT 链路 silent ingest failure + over-strict health check 双层 bug 致 4 天断（Session 6 末, 2026-04-18）

**事件**: Session 6 末用户截图 pt_watchdog 04-18 20:00 钉钉告警 "signal_latest_date=2026-04-16, 绩效数据缺失 1523 交易日". Session 6 前断言 "PT 04-02~04-17 连续运行" (CLAUDE.md L573) 基于 holdings 未清仓 (LL-054 同源), 未核 signal 链路. 实测 `signals` 表仅 04-14/15/16 各 20 行, **04-17 周五 0 records**. `scheduler_task_log` `signal_phase` 04-17 16:30:17 "failed 健康预检失败" + 04-13 17:15 前一次 fail. 用户 04-17 23:15/17/20 手动 retry 3 次全失败.

**根因链** (Bug A + Bug B 双层):
1. **Bug A** (`pt_data_service.py::fetch_daily_data` L100-105 silent swallow): 04-16 `update_stock_status_daily()` 抛异常, catch 只 `logger.error` + `status_rows=0`, **不 raise**. fetch_daily_data 正常返回, signal_phase Step 1 以为成功继续.
2. 04-16 `stock_status_daily` 缺失 (实测 MAX=04-15).
3. **Bug B** (`health_check.py::check_stock_status` L143-144 hard fail): 04-17 Step 0 health check 要求 `stock_status >= 04-16`, 实测 04-15. `return False` → signal_phase `sys.exit(1)`.
4. 04-17 周五 + 04-18 周六 PT signal 链路全断. 用户 pt_watchdog 20:00 钉钉告警才暴露.

**根因**:
1. **silent swallow (Bug A)**: 铁律 33 fail-loud 违反. silent error 让上层以为成功, 下游 (health check) 才暴露, 但相差 1 天延迟. 真实事故发生 → 暴露点 gap = 数据已损坏 1 天.
2. **over-strict health check (Bug B)**: 1 天滞后 hard fail = 单点故障放大. stock_status 临时缺 1 天应 self-heal 或降级 warning, 不应 block 整 signal.
3. Session 6 前 "PT 连续运行" 断言只看 holdings 不看 signal (LL-054 同源: 状态断言不实测多维).
4. 与 LL-055 (handoff 凭印象) / LL-056 (smoke ≠ dual-write) / LL-057 (head truncate) 同源 — **"AI 不严谨实测 → 凭部分 evidence 跳结论"**.

**改进措施**:
1. **Bug A 修 (fail-loud)**: `pt_data_service.py::fetch_daily_data` L100-105 catch 加 `raise`. 传 → signal_phase except → `log_step("signal_phase", "failed", ...)` → scheduler_task_log + pt_watchdog 20:00 钉钉告警. 不再静默 1 天延迟暴露.
2. **Bug B 修 (tolerant)**: `health_check.py::check_stock_status` 从 hard fail 改分级: 滞后 ≤ 2 交易日 warning pass (不阻塞 signal), > 2 交易日 hard fail. 避免单日临时缺失就 block 整链路.
3. **7 new unit test** (`backend/tests/test_pt_data_service_fail_loud.py`): Bug A inspect source 验证 `raise` + FAIL-LOUD marker. Bug B 6 scenarios (no lag / lag 1 / lag 2 / lag 3 / empty / signature).
4. **Session 6 末手动修复 step** (已完成): `update_stock_status_daily(date(2026,4,16), conn)` 补 5491 行 + `python scripts/run_paper_trading.py signal --date 2026-04-17` 71s SUCCESS → signals+klines+stock_status 全续到 04-17 → PT 04-20 周一 09:31 execute 可正常跑.
5. **PT 状态断言多维核对 (LL-054 延伸)**: 未来 PT 状态声明必核 holdings / signal_latest_date / scheduler_task_log / pt_watchdog heartbeat 4 维, 任一 stale = 状态未知.

**执行状态**: ✅ PR #4 `7365731` merged (Bug A + Bug B fix + 7 unit test). Session 6 末手动修复 PT 已续上 (signals 04-14~04-17 各 20 行, klines/stock_status 到 04-17). pt_watchdog 04-19 20:00 再跑应 heartbeat_date=04-17 + perf_latest=04-17 正常. 本 LL entry 单独 PR #5 入册.

---

## LL-059: 代码 PR 9 步 AI 闭环 workflow — 用户 0 接触 (Session 7 PR A 沉淀, 2026-04-18→19)

**事件**: Session 7 开场 MVP 2.3 Sub1 PR A (PR #11, backtest_run ALTER migration + ColumnSpec 扩 array + ADR-007) 执行过程中, 用户多次澄清理念 ("审查审核自己调用相关代码审查", "形成一个闭环", "不由我来审查", "这个需要记住, 不要每次来询问和我来提醒"). 本 LL 沉淀 Session 7 PR A 实战提炼的**代码 PR 9 步 AI 闭环 workflow**, 作为后续所有代码 PR 的默认模式.

**根因 — 铁律 42 原文需要修订**:
- 铁律 42 (Session 6 LL-055 触发诞生) 原文 "必须走 PR + 用户 merge". 当时想法: AI 自审不可靠 → 人审 buffer.
- Session 7 PR A 实证: **双 reviewer agent 并行 (code-reviewer + database-reviewer) 真能当 reviewer**, 识别 4 P1 HIGH findings (2 代码 correctness + 2 DB idempotency/index), 与人审价值等价.
- "用户 merge" 条款造成 AI 每次做完都要询问/等待, 与 Auto mode + 单人项目 0 接触目标矛盾.
- **结论**: 铁律 42 升级 — "用户 merge" → "AI 自 merge (reviewer agents 全 APPROVE + 硬门全绿)".

**改进措施 — 9 步 AI 闭环**:

1. **Plan 模式**: `EnterPlanMode` → Explore agent 读代码 + precondition → 写 plan file → `AskUserQuestion` clarify-only (只问 choice-between-approaches, 不问 "approve 吗") → `ExitPlanMode`. 用户明确问题才问, 不空转.
2. **铁律 25/36 precondition 含 DB 实测**: 不只读文档/interface.py, 还要 `\d table_name` / row count / FK / existing constraints. Session 7 PR A 就是靠 DB 实测发现 `backtest_run` 已存在 (设计稿凭印象 = LL-055 同源).
3. **铁律 42 PR 拆分**: ADR-first (铁律 38) / migration (最小边界) / code+tests+docs (合逻辑单元) 3 个 commit. + 可选 fix commit (保审查历史, 不 amend).
4. **硬门全跑**: unit (`.venv/Scripts/python.exe` ≠ 系统 `python`, 必 .venv 因 `.pth` 在 .venv) + ruff + regression max_diff=0 + smoke (marker `smoke and not live_tushare`) + full pytest (≤ 24 fail baseline) + DB 幂等 2 次 + rollback 验证.
5. **独立 reviewer agents 并行审**: `code-reviewer` (python + docs 通用) + `database-reviewer` (SQL migration) 并行 spawn. 按需补 `python-reviewer` / `security-reviewer` / `typescript-reviewer`. **必不自审** (superpowers "Never self-approve in the same active context") — 自审必漏自己盲区.
6. **P1 findings 全修 merge 前**: reviewer P1 = 真 bug / 架构缺陷 / 幂等性 gap, 必修. P2/P3 视情况 (推后续 PR 或 MVP 3.x cleanup 可接受). 新 fix commit (不 amend, 保审查历史轨迹).
7. **`gh pr comment`** 记 fix 证据: 每个 P1 fix source/location/rationale + re-verify 数字 (unit / ruff / DB round-trip) + 残留 non-blocking findings 推后处理方案.
8. **pre-push hook smoke green 本地守门**: `config/hooks/pre-push` 强制 push 前 `pytest -m smoke` 绿, 阻断 smoke fail push.
9. **AI 自 merge + cleanup**: reviewer agents 全 APPROVE (或 P1 已修) + 硬门全绿 → `gh pr merge <N> --rebase --delete-branch` → `git checkout main && git fetch origin && git reset --hard origin/main`. **不询问用户**, 自动推进.

**Break 闭环的唯一合法场景 (回询问用户)**:
- reviewer agent 报 **P0 BLOCKER** 且语义决策 AI 无法判断修法 (如 "该用方案 A 还是 B")
- 硬门 fail 且与本 commit 改动有因果关系 (非环境问题 — 环境问题 AI 自己定位修)
- Plan 阶段 `AskUserQuestion` clarify (ExitPlanMode 是 approval, 不 break)

**不 break 闭环的场景** (默认 yes, 不问):
- "commit 吗" / "merge 吗" / "push 吗" — 默认 yes
- "需要跑 review 吗" — 默认必跑
- "reviewer 给 APPROVE_WITH_COMMENTS, 是否接受" — 修 P1 后自 merge
- "要不要加这个 test" — 覆盖度不够就加
- "发现老 schema 冲突, 选方案 A/B/C?" — 如果 AI 能做技术判断 (blast radius / 数据安全 / tech debt 三维权衡) 就自决 + 写 ADR, 不问

**持久化** (跨 session 生效):
- `C:/Users/hd/.claude/projects/D--quantmind-v2/memory/feedback_code_pr_workflow.md` — 用户级 memory
- `memory/MEMORY.md` 索引
- CLAUDE.md 铁律 42 修订 (引用本 LL 全流程)
- 本 LL 条目

**Session 7 PR A 实证数据点**:
- PR #11 (4 commits: 8255ce6 ADR-007 + 99c9f23 migration + 6025bad code+tests+docs + a0e01db fix): 3-4 小时工程量
- reviewer agents: 2 并行 spawn, 165s + 89s, 识别 4 P1 + 5 P2/P3
- P1 全修 + re-verify: ~15 分钟
- 硬门 (unit 24 / ruff / regression 0 / smoke 25 / pytest 24 / DB 5 步): 全绿
- 用户接触点: 0 (除了 plan 模式 clarify 3 问 + 授权继续). 实际 merge/push/cleanup 全 AI 自主.

**执行状态**: ✅ Session 7 PR A (`a0e01db` merged 到 origin/main) 实战验证本 workflow. 后续所有代码 PR 默认遵循, 不征求用户确认. 本 LL + CLAUDE.md 铁律 42 修订 + memory 持久化 **本 PR 完成沉淀**.
