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
gap = (today - last_date).days # 自然日，假期会误杀

# ✅ 必须
gap = trading_days_between(last_date, today) # 交易日
```

**执行标准**: ruff自定义规则或pre-commit hook检测`(date1 - date2).days`模式并报错。

#### 措施3: 模拟脚本必须与生产crontab时序bit-identical

```python
# 模拟脚本的时序必须这样写（已在LL-004修复，Phase 1强制）
for i, td in enumerate(trading_days):
    run_signal(td) # T日: 盘后信号生成
    if i + 1 < len(trading_days):
        run_execute(trading_days[i + 1]) # T+1日: 开盘执行
```

**新增**: 模拟脚本启动时自动对比crontab配置，时序不一致则拒绝运行。

#### 措施4: 每个因子必须有方向声明和验证

```python
FACTOR_DIRECTION = {
    "momentum_20d": -1, # A股动量反转，负方向
    "reversal_5d": +1, # 短期反转，正方向
    "bp_ratio": +1, # 低估值正向
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
- 因子的正价值需要非线性合成方法（ML）才能释放
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

**根因**: Team Lead把自己定位为"任务分配器"而非"项目合伙人"。没有在session开始时认阅读宪法全文，只是选择性地读了自己认为需要的部分。宪法存在但不执行等于不存在。

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

**事件**: CLAUDE.md和多处文档将5yr Sharpe 0.6095误标为"12年基线"。Step 6-D首次跑12年后发现12yr Sharpe实际为0.5309，差距巨大。

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
2. **PT 状态 SSOT**: 选定 CLAUDE.md L565-581 为 PT 状态唯一相源, 其他文档只能 reference 不能 restate
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
- Session 7 PR A 实证: **双 reviewer agent 并行 (code-reviewer + database-reviewer) 能当 reviewer**, 识别 4 P1 HIGH findings (2 代码 correctness + 2 DB idempotency/index), 与人审价值等价.
- "用户 merge" 条款造成 AI 每次做完都要询问/等待, 与 Auto mode + 单人项目 0 接触目标矛盾.
- **结论**: 铁律 42 升级 — "用户 merge" → "AI 自 merge (reviewer agents 全 APPROVE + 硬门全绿)".

**改进措施 — 9 步 AI 闭环**:

1. **Plan 模式**: `EnterPlanMode` → Explore agent 读代码 + precondition → 写 plan file → `AskUserQuestion` clarify-only (只问 choice-between-approaches, 不问 "approve 吗") → `ExitPlanMode`. 用户明确问题才问, 不空转.
2. **铁律 25/36 precondition 含 DB 实测**: 不只读文档/interface.py, 还要 `\d table_name` / row count / FK / existing constraints. Session 7 PR A 就是靠 DB 实测发现 `backtest_run` 已存在 (设计稿凭印象 = LL-055 同源).
3. **铁律 42 PR 拆分**: ADR-first (铁律 38) / migration (最小边界) / code+tests+docs (合逻辑单元) 3 个 commit. + 可选 fix commit (保审查历史, 不 amend).
4. **硬门全跑**: unit (`.venv/Scripts/python.exe` ≠ 系统 `python`, 必 .venv 因 `.pth` 在 .venv) + ruff + regression max_diff=0 + smoke (marker `smoke and not live_tushare`) + full pytest (≤ 24 fail baseline) + DB 幂等 2 次 + rollback 验证.
5. **独立 reviewer agents 并行审**: `code-reviewer` (python + docs 通用) + `database-reviewer` (SQL migration) 并行 spawn. 按需补 `python-reviewer` / `security-reviewer` / `typescript-reviewer`. **必不自审** (superpowers "Never self-approve in the same active context") — 自审必漏自己盲区.
6. **P1 findings 全修 merge 前**: reviewer P1 = bug / 架构缺陷 / 幂等性 gap, 必修. P2/P3 视情况 (推后续 PR 或 MVP 3.x cleanup 可接受). 新 fix commit (不 amend, 保审查历史轨迹).
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

## LL-060: grep-only 扫描 = 铁律 25 自律失败, F18 误报根因 (Session 19→20, 2026-04-20)

**事件**: Session 19 盘后 3 轮扫描第 3 轮在 `backend/app/services/signal_service.py:278/436` 发现 hardcoded `'paper'`, 直接列为 **Finding 18 (P1 bug)** "PR-A 遗漏 2 处 prev_weights 查询". 写入 `memory/project_sprint_state.md` + Session 19 handoff + CLAUDE.md PT 状态 section. Session 20 cutover 开场 precondition check 时, 按铁律 25 正式读目标代码**含上下文注释**, 才发现:

```python
# signal_service.py L274 (F18 误报点 L278 的上一行)
# ADR-008 D3-KEEP: signals 表跨模式共享, execution_mode 保持 hardcoded 'paper'
# (前端 UI + 分析工具契约)
```

以及 L432 同样 D3-KEEP 注释, 以及 `backend/tests/test_execution_mode_isolation.py:471/479` 明确 assert 该 hardcode 必须保留. **F18 从来不是 bug, 是 ADR-008 有意设计 (D3-KEEP)**. Session 20 正式撤回 F18, findings 总数 18→17.

**根因 — grep-first → 结论-second 的认知短路**:
- Session 19 执行 `grep -n "'paper'" backend/app/services/signal_service.py` → 返 L278/L436 → 大脑自动填充 "硬编 = Session 10 P0-β 变种 = PR-A 遗漏 = bug"
- **未读目标行上下文** (前 3 行 + 后 3 行), 未读相邻函数注释, 未搜已有 D3-KEEP 契约文档
- 铁律 25 原文: "任何修改/新建/删除代码的操作前, 必须读目标代码的**当前实际内容**", Session 19 扫描虽然不是代码变更但**最终目标是触发 PR 代码变更**, 属于铁律 25 覆盖范围. "代码变更决策前必验证" 原文已涵盖此类场景.
- 铁律 25 补充条款 "改什么就读什么" 不够精确. 应加: **"读什么"** 包含目标行 + 上下文注释 + 相邻同表/同命名空间函数 + 已有契约测试. 仅 grep 返行号不算"读代码".

**影响 (好 + 坏)**:
- 好: Session 20 cutover 执行前 precondition 发现, 未导致 PR #31 误改代码
- 坏: Session 19 handoff + frontmatter description + CLAUDE.md PT 状态 section 均写入 "F18 P1 bug", 污染 3 个文档. 需 Session 20 追写撤回
- 坏: 若 Session 19 未做 precondition check 直接写 PR 改 L278/L436 去掉 'paper', **会 break D3-KEEP 契约**, 前端 UI 信号页面显示错乱, `test_execution_mode_isolation.py:471/479` 2 个断言 fail, 测试债务+1, 触发铁律 40 baseline 违反
- **二阶教训**: scan → finding → handoff write-through 链路无硬门, 中间发现错误难撤回. 铁律 28 "发现即报告" 的反面: 报告前必须验证, 否则成为"假 P0/P1 噪声"

**改进措施 (3 条)**:

1. **"Scan 发现 hardcoded 常量" 的 3 步验证流程** (before 下 finding 判定):
 - a. Read 目标行 ±5 行上下文注释
 - b. `grep "D3-KEEP\|契约\|hardcoded\|KEEP\|namespace" 同文件 + 相邻同逻辑文件`
 - c. `grep "test.*isolation\|test.*contract" backend/tests/` 看是否有对应契约断言
 任一发现 "D3-KEEP / 契约保留 / 测试强制硬编" 证据 → **降级为"已验证 by design"**, 不列 finding

2. **Finding 写入 handoff 前的 Quality Gate**:
 - P0 finding 必含至少 3 个证据 (代码行 + 上下文注释 + 测试引用 or DB 实测 or 历史 ADR 反推), 缺一不列
 - P1 finding 必含至少 2 个证据
 - 证据采集由 grep + Read 双工具完成, 不可单 grep

3. **"撤回" 协议 (误报后补救)**:
 - 撤回语 明确 "Finding X 撤回, 根因: 我违反铁律 25" (Session 20 已实施)
 - 所有污染文档列出 (memory + handoff + CLAUDE.md 等), 追写修正
 - 在 LL 写入新条目作警示 (本 LL-060)
 - findings 总数调整 (18→17)
 - 不删除历史 Finding X, 用 strikethrough + 撤回注

**Session 19 违反铁律 25 的技术栈症状**:

| Session | 违反 | 代价 |
|---|---|---|
| Session 5 (2026-04-18) | PT 状态凭印象, 把 4-13→4-17 "NAV +0.5%" 记成 "-10.2% 回撤" (混淆 market_value vs nav) | Session 10 花 30 min 用 psql 手工算 5 天 pct_change 撤回, 污染 CLAUDE.md L606 永久警示条目 |
| Session 5 (2026-04-18) | "PT 已暂停+已清仓 2026-04-10" (实测 Redis portfolio:current 有 19 股持仓, 明显未清) | LL-054 入册 |
| Session 7 (2026-04-18) | "3085 行 factor_engine.py" 实际 1218 行 (LL-055 根因之一) | 铁律 42 诞生 |
| **Session 19 (2026-04-20)** | **F18 scan grep-only 未读 D3-KEEP 注释** | **本 LL-060** |

累计 4 次同源违反, 都是"AI 高速产出 + 单人无 pair" governance gap. 铁律 25 看似老生常谈但**每次 session 高压下都有新变体**.

**持久化**:
- 本 LL 条目 (警示后续)
- CLAUDE.md 铁律 25 补充条款 (读什么的细化) — 未来适时合入
- `memory/feedback_scan_verification.md` 新 feedback memory (Session 20 写入)
- Session 20 handoff 明确 F18 撤回事实 + 证据链

**执行状态**: ✅ F18 撤回已写 Session 20 handoff frontmatter description + Session 20 cutover section (117 行) + LL-060 本条. CLAUDE.md PT 状态 section 待 Session 20 "可以, 需思考全面" 触发时同步更新 (含 Session 20 cutover note).

## LL-061: 无 git PR 纯运维 cutover 变体 — LL-059 9 步简化模板 (Session 20 `.env` 切换 2026-04-20)

**事件**: Session 20 (2026-04-20 17:47) 执行 `.env:17 EXECUTION_MODE=paper→live` cutover. `.env` 在 `.gitignore` 无法走 git PR, 但仍是金生产环境下 P0 配置变更 (读写命名空间翻转). 需要一个既保 LL-059 核心风控精神, 又适配无 git 变更的简化 workflow.

**根因 — LL-059 原 9 步隐含 "有 git tracked 文件"**:
- LL-059 每步围绕 commit / push / PR / reviewer agents / self-merge 展开, 前提是**改动在 repo 内**
- Session 20 cutover 唯一代码变更 (`.env:17`) 是非 tracked 文件, 走不了这套
- 但 cutover 改变 runtime 语义 (settings.EXECUTION_MODE 全链路读写方向翻转), 影响 P0 生产, 不能"因非 git 就跳过守门"

**改进措施 — 9 步变体 (适配纯运维 cutover)**:

| LL-059 原步 | Session 20 cutover 变体 |
|---|---|
| 1. Plan 模式 | ✅ 保留 — precondition check, 发现 F18 撤回 (铁律 25 自律) |
| 2. 铁律 25/36 precondition 含 DB 实测 | ✅ 保留 — `.env` 当前值 + settings.EXECUTION_MODE 代码扫描 + 相关契约测试 grep |
| 3. 铁律 42 PR 拆分 | ❌ 跳过 — 无 git 变更 |
| 4. 硬门全跑 (unit/ruff/regression/smoke/pytest) | ⚠️ 简化 — `/health` 端点返 `{"execution_mode":"live"}` 作 smoke test 等价物; manual FastAPI 启动日志查异常 |
| 5. 独立 reviewer agents 并行 | ❌ 跳过 — 无代码可 review |
| 6. P1 findings 全修 | ❌ N/A |
| 7. `gh pr comment` 记 fix 证据 | ⚠️ 替代 — 入 handoff + ADR Production Cutover 章节 |
| 8. pre-push hook smoke green | ❌ N/A |
| 9. AI 自 merge + cleanup | ⚠️ 替代 — **(a)** user approve 切换决策; **(b)** `cp .env .env.bak.${DATE}-${NAME}` 备份 (必须!); **(c)** sed -i 改目标行; **(d)** Servy restart 相关服务; **(e)** `curl` 验证 runtime effective; **(f)** 日志审查 10 min 无 post-restart error; **(g)** 配套文档改 (入 git 走 PR 或 直推 per 铁律 42) 下一 session 前 commit |

**新增步骤 (无 git 特有)**:
- **步 0 备份**: 改任何非 tracked 生产配置前, `cp <file> <file>.bak.${YYYYMMDD}-${tag}` — 本 bak 文件留本地 (也不入 git), 用于急回滚
- **步 10 回滚路径验证**: (a) 测试 `cp <bak> <file>` + Servy restart + `/health` 读期望回退值; (b) 历史 live namespace 数据保留 (铁律: 回滚不清数据, 只切读写方向)

**Session 20 实测执行证据**:
- 17:47:12 `cp backend/.env backend/.env.bak.20260420-session20-cutover` (1109 bytes)
- 17:47:25 `sed -i 's/^EXECUTION_MODE=paper$/EXECUTION_MODE=live/' backend/.env`
- 17:48:55 `powershell scripts/service_manager.ps1 restart all` (4 服务新 PID)
- 17:49:10 `curl /health` → `{"status":"ok","execution_mode":"live"}` ✓
- 日志审查 10 min 无 post-restart 异常 (Uvicorn Windows multi-worker race 预存噪声 + QMT 重连成功)
- 关联 git PR 后续 (PR #31) 含 docs + F21 修 + test

**Break 简化闭环的唯一合法场景**:
- 切换影响面 > 单表/单 service (如涉及多 upstream 系统联动) → 升级到完整 git-tracked PR 路径 (加 script + test + reviewer)
- 回滚路径不可逆 (如 DDL / 数据删除) → 禁用本模板, 强制完整 PR + 额外 DB 备份

**Session 20 user 接触统计**: 1 (approve 今晚切换决策). 对比 LL-059 full code PR user 接触 0, 本 cutover 变体多 1 (因生产风险需 user 明示 approve). 这是安全设计而非 overhead.

**持久化**:
- 本 LL 条目 (cross-session 参考)
- Session 20 ADR-008 Production Cutover 章节 (docs/adr/, Session 20 Cutover context specific)
- CLAUDE.md 铁律 42 未来可 refine (当前条款只覆盖"git-tracked 文件类别 → PR 必须性", 无"非 tracked 运维变更"类别, 属铁律漏项)

**执行状态**: ✅ Session 20 cutover 实战验证本变体. 未来 `.env` 类 / `settings.json` 类 / Servy 配置类 / schtasks 定义类 (通过 `.ps1` 改写, 其本身 tracked) 运维变更参考此 LL.

## LL-062: 手工 bootstrap 提前验证 — F14 自愈不等 19h schtasks 回归 (Session 20 2026-04-20)

**事件**: Session 20 cutover 17:47 完成后, F14 (circuit_breaker_state live 0 rows) 按 ADR-008 计划等明日 4-21 16:30 schtasks 触发 `signal_phase` 自动写入 live L0 首行自愈 (19h 等待窗口). User 20:20 质疑 "今天不能验证吗? 同样都是收盘后", 引发重新评估.

**根因 — "等 schtasks 自动触发" 是约定非技术限制**:
- 最初回答"等明日 16:30 schtasks" 隐含假设 = 只有 schtasks 才能触发验证
- 实际: F14 自愈本质 = 调用 `_upsert_cb_state_sync(level=0)` 写 live 首行, 这是**普通 service 层函数**可手工调
- schtasks 触发 signal_phase 只是其中**一种**调用路径 (还含 integration 层 load_universe / compute_signals / save_qmt_state / publish_stream 等副作用)
- 单点验证 F14 自愈 (只写 cb_state live 首行) **不需要**整 signal_phase 跑

**改进措施 — 手工 bootstrap 提前验证模板 (4 步)**:

**步 1 — 识别可单点验证的自愈目标**:
- 某 finding 的"自愈路径"是否由**纯 service 层函数**写单表? (非整链路 side effect)
- 如是: 可手工 bootstrap; 否则: 等 schtasks 完整触发

**步 2 — 写 one-shot script (非 git tracked)**:
- 位置: `D:/quantmind-v2/_tmp_<purpose>_<sessionID>.py` (project root, 跑后删除)
- 铁律 10b 防护: **CWD = project root + `sys.path.append("backend")` 不用 insert** (防 stdlib platform shadow)
- 内容: load `.env` → import service 层函数 → 调用写入 → commit → 读回 verify

**步 3 — 执行 + 双重验证**:
- Script 自身 `[PASS]` 输出
- DB 直查确认 `SELECT * FROM <table> WHERE <namespace>=<expected>` 符合预期
- 关联 Redis / 其他缓存同步 (如适用)

**步 4 — 清理**:
- `rm _tmp_<purpose>_<sessionID>.py`
- handoff 记录 "手工 bootstrap 完成 + schtasks 次日 upsert refresh 回归"
- 下次 schtasks 触发时**仍会跑一次** (upsert 幂等), 作为独立 regression 验证, 两个 "proof" 叠加更稳

**Session 20 F14 实测**:
- Script: `_tmp_bootstrap_cb_state_live_session20.py` (调 `_upsert_cb_state_sync(level=0, reason='Session 20 cutover bootstrap — F14 self-heal verification')`)
- 20:38:04 COMMIT OK
- DB 终态: paper L0 @16:30:24 + **live L0 @20:38:04** ✓
- 明日 4-21 16:30 schtasks signal_phase 仅 upsert refresh (entered_at 保留, level=0 不变), 17:35 pt_audit C4 check 直接 PASS
- 19h 自愈窗口从"等 schtasks"缩到"一次 bootstrap 立即"

**价值**:
- **时间价值**: 19h 压缩到 15 min (Session 内闭环, 不跨 session)
- **attribution 价值**: 今晚 bootstrap 成功 = cutover 代码路径+ ADR-008 D2 动态写入正确, 明日若 schtasks 仍失败 = 独立其他问题 (非 cutover), attribution 矩阵更清晰
- **心理价值**: user 不用等 19h 才知道 cutover 是否生效

**不适用场景**:
- 自愈路径依赖**实时数据/时间窗口** (如只有盘中能触发 `load_positions()` 返回真实值)
- 写入需**上游 event** 先到 (如依赖 stream bus 某事件触发)
- 副作用复杂 (如同时需 publish 多 stream + write 多表, 单点手工写会破坏 invariant)

**Session 20 user 接触**: 2 次
- "今天不能验证吗? 同样都是收盘后" — 触发重评估
- "可以开始" — approve bootstrap

**持久化**:
- 本 LL 条目
- 未来 F15/F16/F19/F20 等 finding 自愈路径评估是否适用本模板
- Session 20 ADR-008 Production Cutover 章节引用

**执行状态**: ✅ Session 20 F14 实战. 模板生效.

---

## LL-063: 假装健康的死码比坏的更危险 (2026-04-21)

**事件**: Session 21 深查 PMS (Profit-Maximizing Stop) v1.0 状态, 发现整体死码 5 重失效 (F27-F31):
- `position_monitor` 建库至今 **0 行** (核心输出表全空)
- StreamBus `qm:pms:protection_triggered` 发布 **0 消费者** (只告警不卖)
- `sync_positions` 读 **T-1 snapshot** 非实时 QMT (滞后 1 日)
- hardcoded `'live'` 对 paper 老持仓保护盲 (~10+ 股 entry_price=0 静默 skip)
- `daily_pipeline.py:226` + `api/pms.py:175` 两处重复 publish 逻辑 (DRY 违反)

但 Celery Beat `pms-daily-check` 每日 14:30 跑出 `"[PMS] 同步持仓:24只股票"` + 5 条 phantom WARN, **日志看起来运行正常**. 金 cutover 18h 零 PMS 保护, 靠 intraday_monitor 组合告警 + 盘后 reconciliation 三检运气守住.

**根因**: 设计意图 (个股阶梯 trailing stop 自动卖) 在实现时只做 publish 半成品, 没人补 consumer, 没人验证 position_monitor 是否有数据. 代码看起来在跑 = "单测通过 + Beat 调度成功" 假象, 但**端到端核心路径从未正触发过**. 建库至 2026-04-21 的 7 个月里, 位置保护这道墙是空的.

**改进措施**:

1. **三问法识别"表面运行"**:
 - a. 核心输出表有行吗? (position_monitor = 0 行 → 红灯)
 - b. 告警链路有消费者吗? (grep XREAD = 0 → 红灯)
 - c. 触发条件下代码路径能走完吗? (entry_price=0 → silently skip → 红灯)

2. **Dead code 月度 audit**: 每月执行 `SELECT COUNT(*)` 扫所有"设计要写"的表, 识别"建库 0 行"的死码候选. **inaugural 2026-04-21 已跑** → `docs/audit/dead_code_2026_04.md` (25 empty / 79 total, 2 confirmed dead [position_monitor / circuit_breaker_log] + 19 future anchor + 4 需调查). 下次 2026-05-21.

3. **新 smoke 硬门候选 (铁律 10b 延伸)**: 任何"会触发动作"的功能 (下单 / 告警 / 写入), 生产 smoke 必须包含**模拟触发 + 验证端到端 side effect**. 只验证"调用不抛异常" ≠ 验证 "触发后正确动作". PMS 这类"被动等待触发"的代码特别危险, 未来 MVP 验收标准需要强制包含"触发后核心表有行"断言 (MVP 3.1 已在验收标准第 3 条固化).

4. **架构整合优先于 patch**: 当发现死码有多重 bug (PMS 5 重), 不要逐个 patch 堆技术债. 正确做法是评估是否重构. Session 21 决策走方案 D+ (并入 Wave 3 Risk Framework 重构, 不修 PMS) 而非方案 A (补 consumer) / B (PMS v2 单模块) / C (废 PMS 扩 intraday), 因为 PMS 多重 bug + 架构碎片 (5 监控系统互不通信) 只能通过统一重构根治.

**价值**:
- 金 cutover 后 18h 发现 PMS 零保护事实 (否则继续假跑数月)
- 避免在死码上投入 1 天 patch 工作 (方案 A 仅解 F27), 直接进 Wave 3 Risk Framework 重构 (方案 D+)
- 推动 Session 21 ADR-010 + MVP 3.1 规划落地
- 固化"表面运行 ≠ 跑"的 mental model, 未来验收标准升级

**Session 21 user 接触**: 5 次关键触发点
- "盘中监控有吗? 你核查了吗?" — 触发 schtasks + Redis + DB 全量盘中状态核
- "pms 呢? 昨天已经完整的运行了一遍了，发现问题了吗?" — 触发 PMS 深度核 (之前误以为 'live 已修, 功能完整')
- "哪里来的 24 只股票?" — 触发 sync_positions MAX(trade_date) 逻辑核, 发现 T-1 滞后 bug (F28)
- "直接 pms 为什么设计你知道吗?" — 触发设计初衷回顾 ("盘中无监控 → 14:30 实时卖锁利润"), 对比现实 publish-only
- "你的建议是什么? 需思考全面, 我需要质量" — 触发方案 A/B/C + 新方案 D+ 架构对比, 最终决定 D+

**持久化**:
- 本 LL 条目
- ADR-010 PMS Deprecation + Risk Framework Migration (引用本 LL)
- MVP 3.1 Risk Framework 验收标准第 3 条 ("core 输出表非触发 dry-run 证据")
- 未来 CLAUDE.md 铁律候选 "Dead code audit 月度"

**执行状态**: ✅ Session 21 文档化. 实施 Session 22 (PR #32 死码处置) 和 Wave 3 MVP 3.1 Risk Framework.

---

## LL-064: 架构级文档 direct push 前必须独立 reviewer (2026-04-21)

**事件**: Session 21 下午 PMS 深查 + Wave 3 Risk Framework 规划决议后, 6 份文档 (ADR-010 + MVP 3.1 + QPB v1.6 + SYSTEM_STATUS + LESSONS_LEARNED + memory 多处) 直接 commit + push 到 main (`13fdf13`), **未经 reviewer agents 审**. User 反问"gh 用了吗? 分级审查这些用不了吗?" 触发 post-hoc reviewer (architect + critic 并行 Opus), 发现 **6 项 P1 + 4 项 P2 + 5 项隐藏风险**:

- P1#1: QPB Quickstart path L94 未随 Wave 3 MVP 重排更新 (内部矛盾 → 违反铁律 22)
- P1#2: risk_control_service.py 是 async SQLAlchemy 不是 sync psycopg2, 批 3 async→sync 重写 1030 行 CB 状态机, 0.5 周估算严重低估
- P1#3: 过渡期"3 道防线"全是 alert-only, zero automated sell — ADR Consequences Negative 未明示, emergency_stock_alert.py 顺序颠倒 (应先建再停 Beat)
- P1#4: 批 3 CB 无回滚路径, 如批 1-2 上线后 CB 无法干净映射到 RiskRule → split-brain (需批 0 feasibility spike 前置)
- P1#5: risk_event_log JSONB 无 TTL/partition/retention governance
- P1#6: Blueprint 引用不存在的 MVP 3.2-3.5 文件名 (铁律 22 违反)

**根因**: 铁律 42 字面条款"docs/** + memory/** + 根目录 md 允许 direct push" 降低流程开销是**对**的, 但这针对的是 typo fix / 小章节补充等低风险编辑. 本 Session 的 ADR-010 (重排 Wave 3 路线图 + 5 监控系统架构决议) + QPB v1.6 (总蓝图修订 + MVP 编号 shift) + MVP 3.1 spec (锁 1.5-2 周工程范围) 属于**架构宪章级**决策, 实质重要性远超普通文档. 跳过 reviewer = 走了流程允许的路但绕过了质量门.

Ironically 这和刚写完的 LL-063 "假装健康的死码比坏的更危险" 是**同模式 mirror**: LL-063 说"表面运行 ≠ 跑", LL-064 是"走流程允许 ≠ 质量已守". 铁律设的字面条款 ≠ 铁律的底层意图.

**改进措施**:

1. **新铁律候选**: 架构级文档 (ADR / MVP spec / Blueprint / CLAUDE.md 铁律 / 决策 memo) 在 direct push 前必须走独立 reviewer agent 审, 即使铁律 42 字面允许. 识别标准 (任一命中即架构级):
 - 影响已有 MVP 编号 / Wave 路线图 / Framework 数量
 - 锁定跨 session 实施范围 (≥1 周工程)
 - 建立新 interface / 新表 schema / 新 API 契约
 - 改动铁律条款或 Blueprint Part 0/1/2

2. **Post-hoc reviewer 流程** (本 Session 已验证可行): `oh-my-claudecode:architect` + `oh-my-claudecode:critic` 并行 Opus, 每个 ≤500 words 报告. Architect 审架构一致性, Critic 挑战假设 / 隐藏风险. 若 P1 blocking → 新 commit fix (不 amend 保历史); P2 non-blocking → 记录 accept. ~20-30 min 完成.

3. **Pre-hoc 更好**: 下次 spawn reviewer 应在 commit **之前** (仍 direct push, 但 reviewer 先过目), 而非 push 后 retrofit. 避免已推文档在未修版本被其他 session 拉走.

4. **Review 要覆盖 "隐藏风险"**: Critic agent 这次挖出 5 项 Consequences 漏项 (过渡期 alert-only / PEAD 风险 gap / broker wiring 未指定 / QMT 60s 延迟 framing / pt_audit 定位), 这些都是单侧决策人 (我) 难自省的. 独立 eye 价值在此.

**Session 21 user 接触**: 1 次反问触发
- "gh 用了吗? 分级审查这些用不了吗?" — 敏锐发现流程 gap

**持久化**:
- 本 LL 条目
- ADR-010 / MVP 3.1 / QPB 三份文档已打 "v1.1 review" 标签修复 P1 6 项
- 未来 CLAUDE.md 铁律候选 (等 2-3 个此类教训后固化为硬铁律)

**对比 LL-063**:
- LL-063: 代码层"假装健康的死码" (PMS 5 重失效)
- LL-064: 流程层"走流程允许绕过质量门"
- 共同根因: 识别"形式合规 vs 实质安全"边界的能力

**执行状态**: ✅ Session 21 post-hoc reviewer 已跑, P1 6 项全部修, 待第二次 commit push.

---

## LL-065: AI /compact summary 嵌入数字在行动前必须反向验证 (Session 21 加时, 2026-04-21)

**事件**: Session 21 加时 user 清除时间限制后, 我据 `/compact` 阶段 AI 生成的 "Session 22 follow-up 列表" 启动 P1+P2 待办, 执行后发现 **两项均 FALSE ALARM**, 数字无原始数据证据支撑:

### P1 F19 "phantom 5 rows DELETE" 反证

原假设: Session 20 handoff "F19 phantom DELETE" → snapshot 5 码冗余应 DELETE

交叉验证:
- SQL: `trade_log` 4-17 live 20/20 完整 (10 sell + 10 buy), 推翻 ADR-008 L289 "trade_log 不完整"
- 5 码 4-17 EOD qty > 0 (3600/900/571/60/65), 与 trade_log fills 对账一致
- Redis: 4-21 实时 19 positions 不含 5 码 (4-18/19 非交易日自然蒸发)
- pt_audit `check_db_drift` 语义: drift 来自 `reconstruct(4-17 snapshot + 4-20 fills=0) = 24` vs `actual 4-20 snapshot = 19`, **非 snapshot phantom 冗余, 而是 reconstruct 假设所有 position 变化走 trade_log, 对非交易日蒸发无处理**

DELETE 会销毁**唯一历史证据**, 4 根因候选永久不可查.

### P2 bp_ratio "IC=-0.0355 vs direction=+1 sign conflict" 反证

原假设: Session 22 跟进项 "bp_ratio 20 日 IC=-0.0355 与 direction=+1 方向冲突"

DB grep factor_ic_history:
- 2977 行 (2014-01-02 → 2026-04-07)
- `ic_20d` 最近 15 条 non-null (2026-02-10 → 2026-03-10) **全正** (+0.017 → +0.151)
- `ic_ma60` 最近 non-null (2026-04-02) = **+0.1247** (稳定正)
- "-0.0355" 不出现在任何列/日期, **AI summary 阶段凭记忆编造**

若启动方向翻转流程, 会改 `pt_live.yaml` direction = -1 干扰 PT, 金潜在损失.

**根因**: `/compact` 生成 summary 是 AI 高度压缩推论, 为节省 token **会丢失原始数字的数据源锚点**. 下一 session 接 summary 时, 叙述部分 ("做了 X Y Z") 可信, **嵌入数字** (IC=-0.0355 / phantom 5 / MDD=-10.2%) 失去 provenance → 不可当执行依据.

同类模式: LL-063 "假装健康的死码" / LL-064 "走流程允许 ≠ 质量已守". 三者**表面 accessible ≠ 实证 verified**.

**改进措施**:

1. **铁律 25 外延**: AI summary / session handoff / memory 中的具体数字 (IC/Sharpe/相关性/行数/fail 数/坐标) 在采取**真实动作** (DELETE/UPDATE/配置改动/flip flag) 前, 必须:
 - grep 原始数据源反向验证 (factor_ic_history / trade_log / git log / 实测 SQL)
 - 数字不符合原始 → 改用真实值 / 标记"估算"
 - 找不到原始 → 假定数字编造, 撤回动作

2. **Summary 可信度分层**: "方向" (做了什么) > "代号" (F19/pk codes) > "嵌入数字". 嵌入数字 = 提示, 非断言.

3. **跨模式严格度 (铁律 39)**: 实施模式 100% 必核原始数据; 架构模式至少 1 次关键数字验证.

**Session 21 加时产出** (18:20 → ~19:30):
- F19: `docs/audit/F19_position_vanishing_root_cause.md` 4 根因候选 + ADR-008 L289 反证标记
- bp_ratio: `docs/audit/bp_ratio_direction_verification.md` FALSE ALARM 关闭 + 顺带发现 IC 入库 14 天 gap (铁律 11 违反, Session 22+ 跟进)
- F22: **PR #36 merged** (`739104d`), DataPipeline NULL ratio guard 铁律 33 fail-loud + 1 P1 + 4 P2 + 2 P3 reviewer 全采纳 + `.gitignore` `.env.*` 补漏 (铁律 35)
- 2 commits (c0e07a0 + 739104d) + PR #36 + 本 LL

**Session 21 user 接触**: 1 次 (加时开场"你思考一下"/清除时间限制)

**持久化**:
- 本 LL 条目 (LL-065)
- `memory/feedback_no_time_limits.md` 新建
- 铁律候选: "Summary 数字行动前校验" (等 2-3 个类似教训固化铁律 43)

---

## LL-066: DataPipeline.ingest 对 subset-column 写入有破坏性, 只写部分列必手工 partial UPSERT (Session 22 Part 7 + Session 23 Part 1, 2026-04-22)

**事件**: 今日两次独立 PR 落地 factor_ic_history 写入路径, 两次踩到同一陷阱:

### 踩坑 1: compute_ic_rolling.py (PR #43, Session 22 Part 7)

初版设计走 `DataPipeline.ingest(FACTOR_IC_HISTORY)`. 分析时发现 pipeline 逻辑:
- Step 2 (pipeline.py:241-246): **补缺失 nullable 列为 `None`**
- Step 6 (pipeline.py:646): `ON CONFLICT DO UPDATE SET {col}=EXCLUDED.{col} for all non-pk cols`

脚本只提供 `[factor_name, trade_date, ic_ma20, ic_ma60]` 4 列, pipeline 会填 `ic_5d/ic_10d/ic_20d/ic_abs_5d/decay_level = None` → UPDATE SET 全 NULL → **摧毁 compute_daily_ic 刚写的 ic_5d/10d/20d 数据**.

修复: 手工 UPDATE SQL + `execute_values`, 显式 `SET ic_ma20=EXCLUDED.ic_ma20, ic_ma60=EXCLUDED.ic_ma60` 仅 2 列. docstring 显式"铁律 17 例外"声明.

### 踩坑 2: fast_ic_recompute.py (PR #45, Session 23 Part 1)

我**忘记** Part 7 教训 (跨 session 遗忘), 初版 PR #45 再次设计走 DataPipeline.ingest + 派生 ic_abs_5d, 认为"只要自己提供 ic_5d/10d/20d/ic_abs_5d 4 列, contract 会正确 UPSERT". 提交 PR 后, reviewer (code-reviewer agent) 识别到:

- 此路径会把 `ic_1d/ic_abs_1d/ic_ma20/ic_ma60/decay_level` 5 列填 None → SET EXCLUDED → **摧毁 PR #43 刚回填的 142,990 rows ic_ma20/60 + factor_decay 的 decay_level 数据**
- 与 PR #43 同源陷阱, compute_ic_rolling.py docstring L16-21 已显式警告

若未修则首次 apply → factor_lifecycle 周五评估全部变 warning (ic_ma20/60 均 NULL) → 假 alert 风暴 + 最坏触发 PT direction 翻转决策.

修复: 对齐 PR #43 模式, 手工 UPSERT 显式 `SET ic_5d/ic_10d/ic_20d/ic_abs_5d=EXCLUDED.*` 仅 4 列, docstring"铁律 17 例外" + 引用 reviewer CRITICAL finding.

### 根因

`DataPipeline.ingest` 契约设计假设 **"输入 df 包含所有 contract 列" 或 "缺失列的语义 = 显式设为 NULL"**. 现实业务场景 (columnar incremental write, e.g. 今天 compute_daily_ic 只写 ic_5d/10d/20d, 明天 compute_ic_rolling 只写 ic_ma20/60, 后天 factor_decay 只写 decay_level) 违反此假设 → subset write 会 **cascading NULL 化** 其他 writer 的数据.

### 规则 (铁律 17 例外条款)

写入 factor_ic_history (以及其他多 writer 共享表) 时:
- **若 df 含 contract 所有列** → 走 DataPipeline.ingest 正确
- **若 df 只含 subset** → 必**手工 partial UPSERT**:
```sql
  INSERT INTO {table} ({subset_cols}) VALUES %s
  ON CONFLICT ({pk}) DO UPDATE SET
      {col1} = EXCLUDED.{col1}, -- 仅列出 subset_cols 的每一列
      {col2} = EXCLUDED.{col2}
  ```
- docstring 必含 `**铁律 17 例外声明**`, 说明为什么不走 DataPipeline + 保护哪些列

**实例参考**:
- `scripts/compute_ic_rolling.py::apply_updates` (PR #43)
- `scripts/fast_ic_recompute.py::upsert_ic_history_partial` (PR #45)

### 改进措施

1. **测试守护**: 新增 source-code level 契约测试 `test_sql_protects_*_columns` 断言 SET 子句不含保护列 (PR #45 `backend/tests/test_fast_ic_recompute.py::test_sql_protects_ic_1d_ic_ma_and_decay_columns`)
2. **铁律 17 条款补充**: CLAUDE.md 铁律 17 加例外注释, 未来 reviewer 看到 DataPipeline.ingest + 明显 subset df → 警觉触发
3. **DataPipeline 本体增强** (长期, 不本 Session): 支持可选 `update_columns` 参数, 限制 `DO UPDATE SET` 范围

### 对比

同类模式**"框架假设 vs 业务场景错配"**. DataPipeline 设计假设是 "整行写", 但多 writer 共享表天然是"列级分工". 框架无原罪, 但使用者必理解假设.

**Session 23 user 接触**: 0 次 (reviewer agent 识别 CRITICAL, AI 自采纳修正, user 只做 merge approval)

---

## LL-067: Reviewer agent 是 AI 自循环 PR 流程的正第二把尺子, high-risk 写入 PR 必 spawn (Session 23 Part 1, 2026-04-22)

**事件**: PR #45 初版设计, 我 (AI) 完整走完:
- 铁律 36 precondition (读源码 + 对比 compute_daily_ic / compute_ic_rolling 三文件)
- 40 unit tests 自写全绿
- ruff + check_insert_bypass "生产无违规" ✅
- 12 年全量 --core --dry-run 实跑 IC 值与历史一致

**所有内部验证都通过**. 但 code-reviewer agent 独立审查**第一轮就识别 CRITICAL 数据破坏 bug** — DataPipeline 会 NULL 化 142,990 rows ic_ma20/60.

我的 40 tests 没覆盖这个场景 (没有 mock 全列 contract + 验证 SET 子句), 因为"不知道自己不知道"—设计者天然对自己设计盲区. Reviewer 用不同视角 (审查 DataPipeline 源码 + 对比历史 PR #43 同源绕过) 补位.

### 救场 impact

若未被 reviewer 发现:
- PR merged → 某次手动 `python scripts/fast_ic_recompute.py --core` 触发 → 142K rows ic_ma20/60 全 NULL + decay_level 全 NULL
- 周五 19:00 factor-lifecycle Beat 读 ic_ma20/60 全 NULL → 所有因子判 warning (因为 ratio 计算 ÷0)
- 钉钉假 alert 风暴
- 最坏: 我跨 session 看到 alert → 误 "dv_ttm 衰减" → 手动 flip `pt_live.yaml` direction → **金损失**

### 规则

**所有涉及生产数据写入 / SQL mutation / transaction boundary / 铁律例外路径的 PR, 必 spawn ≥1 reviewer agent, 即使 AI 自评认为设计正确**. 特别:
- DataPipeline.ingest 路径新增
- Service 层 conn.commit 修改
- ON CONFLICT / UPSERT / DELETE SQL
- 生产数据 backfill / migration
- .env / config 改动

**反例** (适合 AI 自循环无 reviewer):
- 纯 docs 更新 (CLAUDE.md / memory / README)
- ADR-only commit
- 测试新增 (不改生产代码)
- Type hint / docstring / ruff format-only

### 数据支撑

Session 22 Part 7 (PR #43): 2 reviewer (code + python) 8 findings 全采纳, 其中 P1 rowcount multi-batch bug 是**psycopg2 官方文档明确**的 bug, 我设计时未读 docs. Reviewer 指出后立修.

Session 23 Part 1 (PR #45): 2 reviewer 发现 1 CRITICAL (数据破坏) + 1 P1 (NameError) + 3 P2 + 1 P3. CRITICAL 是跨 session 遗忘 (LL-066).

两 PR 共 14 reviewer findings, 全采纳修复, 无 1 项是"pedantic style" — 都是**真实 bug / 维护性缺陷**. Reviewer agent 的 precision/recall 比我自 review 明显高.

### 改进措施

1. **LL-059 9 步闭环硬门**: "spawn reviewer" 从可选变**必选** for high-risk PR 分类. 分类逻辑落文档 (本 LL § "规则" 段已定).
2. **Reviewer 分层**:
 - **code-reviewer**: 架构 + 逻辑 + 铁律合规 (必选 for 所有 code PR)
 - **python-reviewer** (or 语言相关): 语言 idiom + Pythonic + PEP 8 (subset 列/SQL/transaction 场景选加)
 - **database-reviewer**: SQL / schema / transaction (纯 SQL PR 必选)
 - **security-reviewer**: 认证 / 授权 / secrets / injection (涉及这些必选)
3. **反向确认**: 若我自评"小 PR 不需要 reviewer", 至少 spawn 1 general code-reviewer 二次确认判断. 否则 LL-067 自证自循环盲区.

### 对比

LL-051 (开源优先) / LL-055 (AI Auto mode 风险) / LL-060 (单 grep 证据不足) / LL-067 (本): 都是 **AI 自循环失效的不同切面**. 共同根因: **AI 无法给自己提供 "我不知道我不知道" 的搜索范围**, 需外部 eye.

**Session 23 user 接触**: 1 次 (merge 确认 "可以")

**持久化**:
- 本 LL 条目 (LL-067)
- CLAUDE.md 铁律 42 PR 分级审查补充"high-risk classification → reviewer 必选"
- 下次 LL-068/069 同类教训后考虑固化为铁律 43

---

## LL-068: Python script schtask hang 的三维根因 + fail-loud 硬化清单 (Session 26, 2026-04-24)

**事件**: `QuantMind_DataQualityCheck` Windows schtask 连续 2 天 hang:
- 4-22 17:49:36: log 写 3 行后 hang, 被 schtask 5min ExecutionTimeLimit kill (LastResult=267014)
- 4-23 17:45:01: log **0 行** (更早 hang), 同 LastResult=267014
- 钉钉 2 天无告警, 我 (AI) 以为数据质量正常, 差点错过 4-20+ klines 真实滞后

**直接发现**: Session 24 user 调 17:45, Session 25 首日自然验证即 repro, Session 26 深查 + 修 + 合入 PR #47.

### 三维根因 (从全错误归因模型出发)

| 维度 | 根因 | 证据 |
|------|------|------|
| 🔴 DB 层 | PG `statement_timeout=0` 默认, 单 SQL 永不超时 | 12:40 `SHOW statement_timeout` = 0; psycopg2 连接不设 session GUC |
| 🟠 调度层 | 17:30-18:15 dense window (moneyflow+factor_health 17:30 / pt_audit 17:35 / daily_ic 18:00 / ic_rolling 18:15 = 5 task) 并发驱逐索引 out of shared_buffers | 12:40 off-peak manual cold COUNT **17s** vs warm COUNT **0.00s**; klines_daily 索引 `idx_klines_date` 存在但被 evict |
| 🟡 OS 层 | Windows 进程 5min kill 后文件锁延迟释放 → 下一 process `FileHandler` open 失败 silent swallow | 4-22 log 3 行写入正常 (file handle OK), 4-23 log 0 行 (file handle 被 zombie 占用). Python `logging` 不会 propagate open 失败 |
| 🟢 可见性层 | `klines_daily` 1 row `TA010.SH @ 2099-04-30` 脏 sentinel → `MAX(trade_date)` 返 2099 → log 写 "最新日期=2099-04-30 OK" → **2 天真实滞后被假正确掩盖** | 12:40 DB 直查, 4-20/4-21/4-22 日志全部含此错误 OK |

**关键观察**: 单维度修复不够. 如果只修 statement_timeout, schtask 仍可能因文件锁 0 log. 如果只修文件锁, PG query 仍可能 hang. 如果只移 18:30 打散 window, 未来其他 task 叠上来会 repro. **必须四维全打**.

### 修复清单 (PR #47 落地)

脚本硬化 (`scripts/data_quality_check.py`):
1. `psycopg2.connect(options='-c statement_timeout=60000', connect_timeout=30)` — DB 层超时
2. `FileHandler(..., delay=True)` — OS 层 lazy open 防 zombie 锁
3. `main()` top-level `try/except` → `stderr + exit(2)` — fail-loud
4. `main()` 首行 `print('[boot] ...', flush=True, file=sys.stderr)` — 早期探针, schtask stderr 捕获最早证据
5. per-step `logger.info('→/← %s', step_name)` probe — 下次 hang 精确定位
6. `run_checks` per-step `try/except` 隔离 — 单步失败不阻塞
7. `check_future_dates` 新增 P0 alert — 脏数据现行检出
8. `check_latest_dates` 用 effective_max (`WHERE trade_date <= today+7d`) — 未来日期不再掩盖 lag

schtask 层 (`scripts/setup_task_scheduler.ps1`):
9. trigger 17:45 → **18:30** (避 dense window, IcRolling 18:15 后 15min buffer)
10. ExecutionTimeLimit 5min → **10min** (冷况 3x safety)

### 通用规则 (候选铁律 43)

**所有生产环境定时运行的 Python script 默认必须包含**:

```python
# 1. DB 连接硬超时 (psycopg2)
conn = psycopg2.connect(
    url,
    connect_timeout=30,
    options="-c statement_timeout=60000", # 单 SQL 60s 上限
)

# 2. logger FileHandler delay=True
handler = logging.FileHandler(path, delay=True)

# 3. main() 首行 stderr boot probe
def main() -> int:
    print(f"[script_name] boot {datetime.now().isoformat()}",
          flush=True, file=sys.stderr)
    try:
        return run_actual_work()
    except Exception as e:
        print(f"[script_name] FATAL: {type(e).__name__}: {e}",
              flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2 # schtask LastResult 非零触发监控
```

**覆盖的 script 候选** (按优先级, Session 27+ 逐步迁):
- `scripts/compute_daily_ic.py` (已部分合规, check: statement_timeout)
- `scripts/compute_ic_rolling.py` (同上)
- `scripts/fast_ic_recompute.py` (同上)
- `scripts/pull_moneyflow.py`
- `scripts/pull_klines.py`
- `scripts/factor_lifecycle_monitor.py`
- `scripts/pt_watchdog.py`
- `scripts/data_quality_check.py` ✅ (本 PR 已落地)

### 数据支撑 (本 Session)

- 手工 12:40 off-peak COUNT 17s (cold) → 13:00 same COUNT 0.00s (warm) 验证 cache eviction 假说
- 连 2 天 hang 于 dense window 17:30-18:15, 0 次 hang 于 off-peak
- PR #47 硬化版 13:00 手工 **2.7s 完成** exit=1, 2099 sentinel + 真实滞后两条都 surface

### 预测 & 验证

**预测**: 今晚 (4-24) 18:30 首次自然 trigger 应 ~3-30s 完成, exit=1 (因 2099 sentinel 已清 + klines 今日暂无数据会报 "行数=0 可能未拉取" + 3 表滞后 1 天 P1 = 4 alerts), 钉钉告警 content 与 12:58 dry-run 一致. 若 hang / 0 log / 无钉钉 → 未知第 5 维根因, 需 spawn investigation.

**User 接触次数** (本 Session): 2 次 (plan 批准 + cleanup A 批准)

**持久化**:
- 本 LL 条目 (LL-068)
- PR #47 merge at `e094e39`
- 候选铁律 43 (Session 27+ 再 1-2 次同类应用后固化)

---

## LL-069: Integration dry-run 是必要保险层 — mock 单测无法捕数据层/import-time drift (Session 31+32, 2026-04-24)

### 触发事件 (2 次印证, 同周内)

**事件 A: PR #63 CB adapter column drift (Session 31)**
- MVP 3.1 批 3 PR #61 CircuitBreakerRule Hybrid adapter merged, `SELECT level FROM circuit_breaker_state`
- 但 DDL 实际列名 `current_level` (非 `level`). 2 opus reviewer 漏审 (unit test 走 mock conn, 返 hardcoded dict 不触 SQL execute)
- adapter 内部 `except Exception: return 0` silent 吞 UndefinedColumn → `prev_level` 永远返 0 → escalate 每日重复 emit + recovery 永 missed
- **Sunset Gate 条件 B 被锁死** (L4 审批永不能触发 cb_recover event)
- Session 31 dry-run 实测 (非单测) 捕获: integration conn execute SQL → UndefinedColumn stacktrace
- 修复 PR #63: SQL `level → current_level` + 窄化 except 铁律 33 合规 + 3 regression guards (文本锚定 + UndefinedColumn fail-loud + ConnectionError fail-loud)

**事件 B: PR #67 pt_daily_summary platform shadow (Session 32)**
- MVP "Phase 3 自动化" 2026-04-16 delivered `scripts/pt_daily_summary.py` + schtask 17:35
- `sys.path.insert(0, str(BACKEND_DIR))` → `backend/platform/` shadow stdlib `platform`
- sqlalchemy → pandas `platform.python_implementation()` circular → AttributeError → exit=1
- **8 天 silent-fail**, schtask LastResult=1 循环, 无 alert, 无监控
- 症状隐匿 3 重: (1) schtask LastResult 非零无 alert 链路 (2) PTAudit 同时段 17:35 掩盖"17:35 有东西跑"的观察 (3) script stderr 不推钉钉
- Session 32 post-merge SCHEDULING_LAYOUT reconcile 主动实测 → dry-run 捕获 stacktrace → 根因
- 修复 PR #67: `insert(0)` → `append + guard` (对齐 compute_ic_rolling/compute_daily_ic 已知好 pattern)

### 教训核心

**Mock 单测永远绿, 生产 integration 才见章**. 2 个事件共性:
- unit test 走 mock conn / 假 path → 不触 DB execute / 不触 import 链
- 生产启动 integration 路径 → SQL schema drift / sys.path order 触发真实 AttributeError

### 对应铁律基线

- **铁律 10b** 生产入口启动验证 (已有): subprocess 从生产启动路径启动一次, 捕 import-time + top-level 执行错
- **LL-069 扩展**: 启动验证不只是 import 能过, 还必须 **走 1 次生产数据路径** (DB query + import chain 全跑通), 返 exit=0 + 产出 expected artifact (日报 / event row / alert)

### 预防措施 (Session 32+ 落地)

1. **schtask LastResult 监控**: 当前 schtask LastResult 非零**无 alert 链路** (事件 B 8 天未察觉的直接原因). 候选铁律 43 扩展项 (e): schtask 驱动 Python 脚本必 wrap 顶层 `sys.exit(code)` 外加 stderr + 调 PT_Watchdog-like 监控发钉钉. Session 33+ 考虑.
2. **启动 dry-run 作为 PR 硬门**: high-risk write-path PR (CB 状态机 / schtask 新脚本 / Platform DAL) reviewer 后 merge 前必补 1 次启动 dry-run. PR #63/#67 都是 post-merge 发现, 若 pre-merge 补 dry-run 可更早拦截.
3. **sys.path.insert(0, backend) 硬禁**: 候选铁律 44 — 所有生产 Python 脚本 `sys.path` 操作禁 `insert(0, backend_dir)`, 改 `append + guard` pattern. Session 32 PR #67+#68 已把所有 7 个 production scripts 迁移完成.

### 数据支撑

- PR #63 dry-run 捕 UndefinedColumn 时间: Session 31 2026-04-24 (PR #61 merged 同日)
- PR #67 dry-run 捕 AttributeError 时间: Session 32 2026-04-24 (script delivered 2026-04-16, **8 天延迟**)
- Mock 单测数量: PR #61 16 tests / PR #67 0 tests (script 纯脚本无单测), 都"绿"
- 生产证据: PR #61 dry-run status=ok checked=0 实测 / PR #67 dry-run exit=0 NAV ¥1,012,178 真实日报产出

### 持久化

- 本 LL 条目 (LL-069)
- PR #63 merge at `61ed678` + PR #67 merge at `6a777be`
- Sprint state Session 31 + 32 均记
- 候选铁律 43 扩展 (e) schtask 失败告警 + 候选铁律 44 sys.path.insert(0) 禁用 (Session 33+ 观察 1-2 次再应用后固化)

---

## LL-070: backend/platform/ 命名 shadow stdlib platform — sys.path.insert(0) 是 latent 地雷 (Session 32, 2026-04-24)

### 具体 pattern

**危险 pattern** (11 scripts 曾存在):
```python
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR)) # ← 把 backend 塞 sys.path 首位
```

**后果**: Python 按 sys.path 顺序找模块. `backend/` 首位 → `import platform` → 命中 `backend/platform/` (项目 Platform 包) 而非 stdlib `platform`. 若 `backend/platform/__init__.py` 又 transitively import pandas/sqlalchemy 会触发循环 import:
```
AttributeError: partially initialized module 'platform' has no attribute
'python_implementation' (most likely due to a circular import)
```

### 为什么是 latent (8 天未爆)

Shadow 只在**特定 import 链**触发:
- `sqlalchemy.ext.asyncio` → `sqlalchemy/util/compat.py` → `import platform` → `platform.python_implementation()` (pandas 下游)
- 普通 `psycopg2` direct 路径不触

11 scripts 中仅 `pt_daily_summary.py` 路径命中 shadow (因其调 `from app.services.db import get_sync_conn` 带 sqlalchemy asyncio ext 链). 其余 10 scripts 同 pattern 但运气避开.

### 安全 pattern (推荐)

```python
BACKEND_DIR = PROJECT_ROOT / "backend"
# .venv/.pth 已把 backend 加入 sys.path. 不用 insert(0) 避免与 stdlib `platform`
# 冲突 (铁律 10b shadow fix: backend/platform/ 会 shadow stdlib platform).
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))
```

**关键变化**:
- `insert(0, ...)` → `append(...)`: append 把 backend 放 sys.path 末尾, stdlib 优先
- 加 `if ... not in sys.path` guard: 幂等, 防重复 import 重复 append

### 已迁移 scripts (Session 32)

- PR #67: `pt_daily_summary.py` (唯一 broken, 8 天 silent-fail 根因)
- PR #68 批量预防: `factor_lifecycle_monitor.py` / `rolling_wf.py` / `ic_monitor.py` / `run_gp_pipeline.py` / `compute_factor_phase21.py` / `bayesian_slippage_calibration.py` (6 scripts)
- 已有好 pattern 保持: `compute_ic_rolling.py` / `compute_daily_ic.py`

### 不在 scope (天然 SAFE)

4 scripts 用 `insert(0, scripts/) + append(backend)` 模式, backend 不在 sys.path 首位:
- `run_paper_trading.py` / `factor_health_daily.py` / `fix_st_cleanup_20260414.py` / `compute_minute_features.py`

研究脚本 `scripts/research/**` 按 CLAUDE.md 研究脚本豁免, 不做硬化.

### 候选铁律 44 (Session 33+ 观察)

"生产 Python 脚本 (schtask/Celery Beat 驱动) **禁止** `sys.path.insert(0, BACKEND_DIR)`, 必须 `append + guard`. 研究脚本豁免. 自动检查工具: 未来 CI 可加 ruff custom rule 或 pre-commit grep 扫描."

Session 33+ 再 1 次同类事件 (若 scripts/research/ 迁 production) 即可固化铁律 44.

### 持久化

- 本 LL 条目 (LL-070)
- PR #67 merge `6a777be` (pt_daily_summary fix) + PR #68 merge `e7ce25b` (6 scripts 预防)
- 候选铁律 44 tracking

---

## LL-074: CeleryBeat 静默死亡 0 logs — schtask Python 监控以 schedule.dat freshness 突破 (Session 35, 2026-04-25)

### 触发事件

Session 34 (2026-04-25 02:20 UTC) 例行启动 status check 抓出 **QuantMind-CeleryBeat 服务在 04-24 19:26:50 → 04-25 02:20 静默死亡 ~7h**:
- 0 stderr crash log (`logs/celery-beat-stderr.log` 时间停在 19:26)
- 0 stdout 输出
- 0 Windows Event Log entry (`Get-EventLog -Source ...`)
- 0 Servy 重启记录 (服务 StopType 显示 manual stop, 无 crash recovery)
- 系统 uptime 2 days 10h 确认非 reboot

**直接生产风险**: 若 Monday 4-27 09:00 首次 MVP 3.1 Risk Framework 真生产触发前再次发生:
- `risk-daily-check` (14:30 Mon-Fri Beat) → missed
- `intraday-risk-check` (`*/5 9-14 * * 1-5` Beat, 72/日) → 全 missed
- 金 ¥1M 0 熔断保护 (无 PMS L1/L2/L3 + 无 CircuitBreaker L1-L4 + 无 IntradayDrop)

**唯一现有 watchdog**: `PT_Watchdog` schtask 1/日 20:00 触发. Beat 凌晨死 → 20:00 = **17h 静默 gap** ≫ Monday 09:00 deadline.

### 根因分析 (假设, Session 35 未根除底层 Beat 死亡问题)

1. Servy 进程 (`celery beat scheduler`) **kill -9 类信号**或 OOM → 无 stderr 输出
2. Windows 进程死亡未触发 Service Failure Recovery (Servy 配置 `sc qfailure` 实测无 recovery action 配置)
3. PersistentScheduler 后台 thread 死锁可能 — 进程仍 RUNNING 状态但 schedule.dat 不更新 (zombie)

**本 session 不做底层修复**, 而是**接受 Beat 可能死亡的现实, 加监控让 Monday 前死亡 ≤ 15min 内发现**.

### 修复方案 (Session 35 PR #74 ServicesHealthCheck)

#### 设计哲学

- **不修 Beat, 修 detection**: Beat 仍可能死, 但 15min 内 P0 钉钉告警 → 人工 servy-cli start
- **双重检测** 防 zombie 假阳性:
 - Layer 1: 4 Servy 服务 `sc query` 状态 → 死服务必抓
 - Layer 2: `celerybeat-schedule.dat` LastWriteTime ≤ 10min stale → zombie process 也抓 (服务 RUNNING 但 scheduler thread 卡死)
- **不依赖 PG**: subprocess + file stat only. PG 挂时本脚本仍能告警 (核心 LL-074 价值)

#### 关键参数

| 参数 | 值 | 推理 |
|------|------|------|
| schtask 频次 | 15min (96/日) | Monday 09:00 deadline 前 ≤ 15min 检测延迟 |
| Beat heartbeat 阈值 | 10min stale | PersistentScheduler 5min 默认 cycle × 2x 容忍 (Windows fs flush + Beat cycle 抖动) |
| 钉钉 dedup window | 1h | 防 96/日 × 钉钉无配额 spam, 出事故 1 次/h 告警足够 |
| state file | `logs/services_healthcheck_state.json` | file-based, 不依赖 PG (核心: PG 挂时仍 dedup) |
| Subprocess 超时 | 5s + Popen kill | Windows `subprocess.run(timeout=)` 不杀子进程, sc.exe 累积 orphan |

### 教训

#### LL-074-A: Windows 服务可静默死亡 0 logs

Servy v7.6 + Celery Beat + Windows 11 组合下, 进程死亡可能完全无 stdout/stderr/Event log. 不能假设"如果死了肯定会报错". 必须**主动健康检查**.

#### LL-074-B: schtask 1/日 频次远不够生产监控

PT_Watchdog 1/日 20:00 模式留 17h 静默 gap. 金链路 (尤其 9:00 + 14:30 高 stake 时点) 必须 ≤ 15-30min 频次健康检查.

#### LL-074-C: zombie process 检测必须看应用层 artifact, 不能只看服务状态

`Get-Service Status=Running` 不等于 Beat 在跑 schedule. PersistentScheduler 5min cycle 写 `celerybeat-schedule.dat` LastWriteTime 才是心跳 (类似 LL-068 schtask hang 也是看 stderr/log freshness).

#### LL-074-D: 监控脚本不能依赖被监控的下游 (PG)

如果 Beat 死的同时 PG 也挂 (灾难联动场景), PG-依赖型监控脚本本身 fail → 0 告警. ServicesHealthCheck 故意 0 PG conn, file-based dedup, 是 LL-074 的**核心独立性设计**.

### 候选铁律 44 (Session 36+ 观察)

> "生产关键链路 (PT 信号 / 风控 / 资金) 监控 schtask **频次 ≤ 30min**, 且**不允许依赖被监控对象** (e.g. 监控 PG 不依赖 PG, 监控 Beat 不依赖 Beat task)."

Session 36+ 1 次同类事件 (其他静默死亡子系统) 即可固化.

### 持久化

- 本 LL 条目 (LL-074)
- PR #74 merge `2d0010b` (ServicesHealthCheck 15min 监控)
- spawn task: pytest baseline drift 24→40 调查 (独立任务, 不堵本 LL)
- 候选铁律 44 tracking

---

## LL-076: schtask script `_check_trading_day_or_skip` 用 today 而非 args.start — 周末手工 backfill silent skip (Session 36 末, 2026-04-25)

### 触发事件

Session 36 末 pre-Monday audit (2026-04-25 Saturday 22:35) 发现 F25: `moneyflow_daily` 4-24 (Friday 交易日) 缺数据. 手工 backfill 命令 `python scripts/pull_moneyflow.py --start 20260424 --end 20260424` 输出 "**非交易日，跳过moneyflow拉取**" 并 exit 0.

但 4-24 是交易日 (`klines_daily` / `factor_values` / `position_snapshot` 实测 4-24 全有数据). 用户传 `--start 20260424` 应该 backfill 4-24, 实际被 silent skip.

### 根因

`scripts/pull_moneyflow.py:251` `_check_trading_day_or_skip()` 检查的是 `date.today()` (今天 Saturday 4-25) 而非 `args.start`:

```python
def _check_trading_day_or_skip() -> bool:
    cur.execute(
        "SELECT is_trading_day FROM trading_calendar WHERE trade_date = %s",
        (date.today(),), # ← BUG: 应根据上下文用 args.start
    )
```

逻辑误解:
- 函数名暗示 "if today is trading day proceed" — schtask daily auto run 语义没问题
- 但 `--start YYYYMMDD` 手工 backfill 路径下, 应校验 args.start 是否交易日
- 周末 (Saturday=非交易日) 跑历史 backfill 被今天 skip 掉

### Workaround (Session 36 紧急 backfill)

inline Python 直调 `_run(args)` 绕过 `_check_trading_day_or_skip`:
```python
import argparse
from pull_moneyflow import _run
args = argparse.Namespace(start='20260424', end='20260424', verify=False, recent=False)
_run(args) # 5179 rows backfilled
```

### 正式修复 (PR #90)

`_check_trading_day_or_skip(target_date: date | None = None)`:
- 默认 `target_date=None` → `date.today()` (schtask daily auto run 语义不变)
- main() 解析 `args.start` (YYYYMMDD) → `datetime.strptime(...).date()` 传入
- args.start invalid format → stderr WARNING + fallback today (PR #90 reviewer MEDIUM 采纳, 防 silent fallback 用户误以为日期错而非 format 错)

### 教训

#### LL-076-A: 函数命名暗示语义不匹配多用法时, 必显式参数

`_check_trading_day_or_skip()` 名字暗示"今天", 但有两种调用语义:
- schtask daily: 校验今天 (auto-run 上下文)
- 手工 backfill: 校验 args 指定日期

应在 API 层显式区分 (加可选参数), 而非靠 caller 来推断.

#### LL-076-B: 周末测试是 schtask script 的盲区

schtask scripts 5 个生产 script (data_quality_check / pt_watchdog / compute_daily_ic / compute_ic_rolling / fast_ic_recompute) 历史所有测试都在工作日跑 (CI / 开发都是平日). 周末手工 backfill 是 silent failure 的高风险窗口. 未来同类 script 的 unit test 必须含 "Saturday/Sunday + --start trading-day" 场景.

#### LL-076-C: 铁律 33 silent_ok 必带 stderr 诊断 — invalid format 也是

`except ValueError: check_date = None` 看似 silent_ok 合理 (fallback 不抛), 但用户视角下游错误信息 "非交易日跳过" 完全误导. silent_ok 必带 stderr 警告让用户知道 fallback 原因 (LL-068 同 pattern: 异常路径必写 stderr 诊断痕迹).

### 候选铁律 (TBD)

> "schtask script 的可选参数路径 (e.g. `--start`, `--target-date`) 不能让 `today()` 隐式接管. 任何"今天"判断逻辑必须在 API 层暴露 `target_date` 参数, 调用方传入或显式 None=today."

Session 37+ 同类 bug 1 次 (其他 schtask script 类似 today/args mismatch) 即可固化.

### 持久化

- 本 LL 条目 (LL-076)
- PR #90 merge `cdab4bd` (fix code) + `07d03a7` (reviewer MEDIUM 采纳 invalid-format stderr warn)
- F25 backfill: `inline _run(args)` 5179 rows manual + Session 36 audit doc
- 候选铁律 tracking

---

## LL-074 Amendment: ServicesHealthCheck 投资在 zombie 模式无效, PR-X3 闭合 gap (Session 38 实战推翻, 2026-04-27)

### 触发事件 (LL-081 实战实测)

LL-074 (Session 35 2026-04-25 02:20 UTC) 沉淀 "schtask Python 监控 schedule.dat freshness 突破", LL-077 (Session 36 末) 进一步声明 "ServicesHealthCheck 投资 1 天内收回". 但 **Session 38 真生产首日 (2026-04-27) zombie 4h17m 实战推翻一部分**:

ServicesHealthCheck v1.0 (LL-074 投资) 仅监控:
1. Servy 4 服务 `Running` 状态 ✓
2. CeleryBeat `schedule.dat` 心跳 (10min 阈值) ✓

漏检的真生产 zombie 模式:
- QMTData service Servy 报 `Running` 但 Python 内部 hang (xtquant 断连后 query_asset 卡死)
- Beat schedule.dat 仍 fresh (Beat 进程没死, 只 QMTData hang)
- → ServicesHealthCheck 周一 13:51-18:08 4h17m 期间 全 ok, 0 钉钉告警
- → 盘下午 70min 金 ¥1M 0 实时价 + Risk Framework 全 silent

### 教训

进程层 alive (Servy `Running`) **是必要不充分条件**. 必须看应用层 freshness:
- **Redis key updated_at gap** (e.g. portfolio:nav, sync_loop 60s 应持续 refresh)
- **StreamBus stream last event time** (e.g. qm:qmt:status, 交易时段持续应有 events)
- **DB last write time** (e.g. risk_event_log 交易日 14:30 必有 evaluate 痕迹)

任一应用层 stale > 阈值即视为 zombie, 即使进程层 alive.

### 修复 (LL-081 PR-X3 #103)

`scripts/services_healthcheck.py` 加:
- `RedisFreshnessCheck` dataclass + `check_redis_freshness()` function
- HealthReport.redis_freshness field, build_report 集成 → failures
- send_alert markdown 加 "Redis Freshness (LL-081 PR-X3)" 段
- 后续 PR #105 补 trading_hours guard 防非交易时段 stream 噪声

### 应用规则更新

ServicesHealthCheck v2.0 (LL-074 + LL-081) 监控 4 层:
1. ✓ Servy 4 服务 `Running` (进程层)
2. ✓ CeleryBeat `schedule.dat` 心跳 (调度层)
3. ✓ **Redis key freshness** (应用层 portfolio:nav updated_at < 5min)
4. ✓ **Redis stream freshness** (应用层 qm:qmt:status last event < 30min, 仅交易时段 alertable)

### 持久化

- 本 amendment (LL-074 v2.0)
- LL-081 主条目 (本文档)
- PR #103 (LL-081 PR-X3 init) + PR #105 (trading_hours guard follow-up) 全 merged 到 main

---

## LL-077: Servy 服务依赖配置触发 worker restart 级联 stop Beat — 必有显式 start protocol (Session 36 末, 2026-04-25)

### 触发事件

Session 36 末 22:38 执行 `servy-cli restart --name="QuantMind-Celery"` (worker 内载 Sprint 5 PR #87 strategy_bootstrap 改动). 7 分钟后 (22:45) ServicesHealthCheck (PR #74 LL-074) 钉钉告警:

```
🚨 Services Health DEGRADED (LL-074)
触发原因: transition (ok → degraded)
✅ QuantMind-FastAPI: RUNNING
✅ QuantMind-Celery: RUNNING
❌ QuantMind-CeleryBeat: STOPPED
✅ QuantMind-QMTData: RUNNING
失败项: service:QuantMind-CeleryBeat=STOPPED
```

Beat heartbeat 最后写入 22:38:13 — **正好 worker restart 时点**.

### 根因

`CLAUDE.md` L196 servyMan 表显式声明:

| 服务名 | 依赖 |
|---|---|
| QuantMind-CeleryBeat | Redis, **QuantMind-Celery** |
| QuantMind-Celery | Redis |

Servy `restart QuantMind-Celery` 触发**依赖级联**: 依赖 Celery 的 Beat 被 stop. 但 Servy 不自动 start dependent — Beat 永久停留 STOPPED, 直到人工 `servy-cli start --name="QuantMind-CeleryBeat"`.

**Session 33 Part 4 (2026-04-25 02:25)** 也曾抓到 Beat=Stopped, 当时根因未确认; 本次实测同模式 (worker 类操作 + Beat 级联), 强化假设. (LL-074 触发事件本身可能也是同 root cause: 某个 19:26-02:20 间的 worker restart 触发 Beat stop.)

### 修复 (Session 36 末)

1. 立即手工 `servy-cli start --name="QuantMind-CeleryBeat"` → Beat boot 22:49:43, schedule.dat 24s fresh ✓
2. ServicesHealthCheck 验证恢复 (15min 后下次心跳告 OK transition)

### 教训

#### LL-077-A: 服务依赖配置必有显式 lifecycle protocol

Servy 自动级联 stop dependent (Beat) 但**不自动级联 start**. Worker restart 后 Beat 留 zombie STOPPED 状态. 必有运维 protocol:
- **要么** 修 Servy config 让依赖关系**对称** (restart Celery → 自动 restart Beat dependency)
- **要么** 任何 worker restart 后 **必跟** `servy-cli start --name="QuantMind-CeleryBeat"`
- 当前选择: 后者 + ServicesHealthCheck 监控兜底

#### LL-077-B: ServicesHealthCheck 是 LL-077 的关键防护

PR #74 LL-074 ServicesHealthCheck (15min × 96/日) 7min 内捕获本次事件. 若无此监控, Beat 会静默 STOPPED 直到 PT_Watchdog 20:00 才发现 (17h gap, 跨周末跨 Monday 09:00 风险).

LL-074 的"投资"在 LL-077 立即收回 (Session 35 设计监控 → Session 36 实战救场 1 天内验证). 监控的价值不在它告警了什么 bug, 而在它**能告警** silent 问题.

#### LL-077-C: 操作 + 审计同步是 audit completeness 必要条件

我执行 `servy-cli restart` 时只看到 worker PID 切换 (37904 → 41120) 验证成功, 没**主动** check Beat 状态. 7min 钉钉告警是 ServicesHealthCheck 救场, 否则审计完整性失败 (操作"成功"但 hidden 副作用未发现).

未来高 stake 操作协议: action → 不只 check 直接目标, 还 check 上下游依赖. (类似 PR-DRECON 同模式: ps1 register 后必须 verify state, 不只 verify register 命令 exit 0.)

### 候选铁律 (TBD, vs LL-074 Session 35 候选铁律 44 合并)

> "服务/任务状态变更 (start / stop / restart / register / disable) 后**必 verify 上下游 state**, 不止变更直接目标. 钉钉告警是兜底, 操作时主动 check 是首选."

LL-074 已提候选铁律 44, LL-077 是同模式补强证据. Session 37+ 1 次同模式即可固化.

### 持久化

- 本 LL 条目 (LL-077)
- 无独立 PR (运维 incident, ServicesHealthCheck 已是 PR #74)
- 22:49 Beat 恢复 PID 35040, schedule.dat 24s fresh ✓
- 候选铁律 44 (LL-074 已提) 同模式补强
- worker restart 协议加 SCHEDULING_LAYOUT.md / RUNBOOK 更新 (Session 37+)

---

## LL-078: TimescaleDB hypertable 不支持 CREATE INDEX CONCURRENTLY (Session 36 末加时, 2026-04-25 23:53)

### 现象

Saturday 23:53 跑 `CREATE INDEX CONCURRENTLY idx_fv_factor_date ON public.factor_values (factor_name, trade_date)` (factor_values 是 TimescaleDB hypertable) 立刻报错:

```
ERROR: hypertables do not support concurrent index creation
```

### 根因

TimescaleDB hypertable 通过 chunk fanout 管理 152 子表, CONCURRENTLY 在 PG 层是单表 lock-free 算法, 不能跨 chunk 协调. TimescaleDB 文档明确不支持.

### 教训

**TimescaleDB hypertable 索引创建只能 plain CREATE INDEX**, 接受 chunk-level 锁 (写入新 chunk 不阻塞, 但 backfill/UPDATE 旧 chunk 期间会等). 实测 152 chunks × 200M 行 plain CREATE INDEX 单 worker ~30-60 min, 多 PG worker 并行可缩短.

### 应用规则

- TimescaleDB 表上索引变更必须 schedule 到 **写入低峰窗** (Saturday 凌晨 / Sunday 凌晨)
- 不能依赖 CONCURRENTLY 来"在线"加索引
- 替代: TimescaleDB 14+ 有 `CREATE INDEX ... ON ONLY` 单 chunk 模式 (高级用法)

### 持久化

- 本 LL 条目 (LL-078)
- 后续: 检查 timescaledb 升级是否支持 CONCURRENTLY (官方未来 roadmap)

---

## LL-079: pg_ctl restart 不刷新 Windows Service 状态 — Servy 依赖 PostgreSQL16 启动失败 (Session 36 末加时, 2026-04-26 00:00)

### 现象

Saturday 23:38 用 `pg_ctl restart -D D:\pgdata16` 重启 PG (升 shared_buffers 8GB), 之后 Servy `start QuantMind-FastAPI` 报 `Failed to start service`.

### 根因

PG 安装为 Windows Service `PostgreSQL16`, 但 `pg_ctl restart`是 PG 命令层操作, **不通过 Windows Service Control Manager**. 结果:
- `postgres.exe` 进程实际运行 (psql 连得通, port 5432 active)
- Windows Service `PostgreSQL16` 状态显示 **Stopped** (SCM 视角)

Servy `QuantMind-FastAPI` 配置 `ServiceDependencies: Redis; PostgreSQL16` — Servy 在启动 FastAPI 前**通过 Windows SCM 检查依赖服务 Running**. SCM 看 PG=Stopped → 依赖检查失败 → FastAPI 启不起来.

### 教训

**PG (Windows Service 模式) 必须通过 Windows Service 启停**, 不能用 pg_ctl. 错误用 pg_ctl 后修复:

```powershell
# 1. 停 standalone PG
pg_ctl stop -D D:\pgdata16 -m fast

# 2. 启 Windows Service (会自动加载 postgresql.auto.conf 含 shared_buffers=8GB)
Start-Service PostgreSQL16

# 3. 验证
Get-Service PostgreSQL16 # 应 Running
psql -c "SHOW shared_buffers" # 应反映新值
```

### 应用规则

- PG 改 shared_buffers (需 restart) 必走 `Stop-Service PostgreSQL16; Start-Service PostgreSQL16` (PowerShell) 或 `sc stop/start PostgreSQL16` (CMD)
- pg_ctl restart **仅用于** PG 非 Windows Service 模式 (开发/测试)
- 维护脚本 (`sunday_pg_maintenance.ps1`) 必更新此协议

### 持久化

- 本 LL 条目 (LL-079)
- `scripts/maintenance/sunday_pg_maintenance.ps1` 改用 Stop-Service/Start-Service (Session 37+ 修正)
- LL-074 / LL-077 同模式延伸: Servy 依赖链 + Windows Service 状态分裂坑

---

## LL-080: drop covering 索引前必看 EXPLAIN 真实查询 — pg_stat_user_indexes idx_scan 数字误导 (Session 36 末加时, 2026-04-26 00:00)

### 现象

Saturday 23:50 实测 `idx_fv_factor_date_covering` 5y idx_scan=10K (vs idx_fv_date_factor 506M), 判定"极度浪费"立即 DROP. DB 263→218 GB ✅. 但 Q2 (1 因子 1 年 bulk SELECT) 从 2.35s → 5.5s **regression 2.3x slower**.

### 根因

EXPLAIN 实测发现 PG planner 对 Q2 模式 (`WHERE date BETWEEN AND factor_name = X`) 走 covering 不多 (idx_scan 数字小), 但**用了 idx_scan + index-only-scan 取列值**. drop covering 后 PG fallback 到 `idx_fv_date_factor` (序为 date,factor) Bitmap + Parallel Seq Scan filter — 慢 2-3x.

`idx_scan` 字段只统计 **传统 Index Scan**, 不计 **Index-Only Scan** 全部 share. 因此单看 idx_scan 数字会低估 covering 价值.

### 教训

**drop 大索引前必跑生产代表性查询 EXPLAIN**, 不能只看 pg_stat_user_indexes idx_scan:

```sql
-- ❌ 误判工具
SELECT idx_scan FROM pg_stat_user_indexes WHERE indexrelname = '<idx>'

-- ✅ 真实判断
EXPLAIN (ANALYZE, BUFFERS) SELECT ... -- 各 production 查询模式跑一遍
-- 看 plan 是否提到 <idx>, 是 Index Scan / Index-Only Scan / Bitmap?
```

### 应用规则

- DROP 索引前 checklist:
 - [ ] pg_stat_user_indexes idx_scan + idx_tup_read + idx_tup_fetch 全看
 - [ ] EXPLAIN (ANALYZE, BUFFERS) 至少 5 个 production 查询模式
 - [ ] 测试 DROP 后 plan 退化情况 (若 fallback 到 Seq Scan, 重建小索引补偿)
- covering INCLUDE 索引特殊: 大但提供 index-only-scan, idx_scan 数字不反映其价值
- 修复模式: drop 大 covering → CREATE INDEX (factor_name, trade_date) 无 INCLUDE → 通常 5-10x 小 + 80% 加速

### 持久化

- 本 LL 条目 (LL-080)
- 实战修复: idx_fv_factor_date 重建中 (Saturday 23:56 启动, ~30-60 min)
- 后续 PG 维护脚本 (`sunday_pg_vacuum.ps1` analyze phase) 加 EXPLAIN 模板

---

## LL-081: QMT zombie + Redis status 无 TTL 导致 4h+ silent failure (Session 38 真生产首日, 2026-04-27)

### 现象

Monday 4-27 18:00 实测发现: Redis `portfolio:nav` updated_at = 13:50 CST (滞后 4h10m), Servy `QuantMind-QMTData` 报 Running 但内部 zombie. 4-27 09:00-13:50 上午 5h 正常, 13:51-18:08 下午 4h17m zombie. 期间:

- 14:30 risk-daily-check 触发, PMSRule.evaluate 19 持仓 → 19/19 `current_price <= 0` (Redis market:latest:* 已 expire) → 全 `continue` skip → `risk_event_log` 写 0 行 (伪健康)
- intraday-risk-check */5 9-14 13:55-14:55 共 13 次, QMTDisconnectRule.evaluate 调 `qmt_client.is_connected()` → 返 True (误判) → 0 触发
- ServicesHealthCheck (LL-074 投资) 只看 Servy `status` Running → 0 钉钉告警
- **盘下午 70min 无实时价 + Risk Framework 全程哑火**, 18:08 用户手动 `servy-cli stop/start QuantMind-QMTData` 才恢复

### 根因 (3 个 silent failure 叠加)

**根因 #1** (`scripts/qmt_data_service.py:92-98`): `SET qmt:connection_status connected` 无 TTL (实测 `redis-cli TTL` = -1), 只在 connect 边沿 SET, sync_loop 不 refresh. service hang 后 key 永久卡 "connected" → `qmt_client.is_connected()` (`backend/app/core/qmt_client.py:38-44`) 看 GET == "connected" → 永久 True.

**根因 #2** (`backend/qm_platform/risk/rules/pms.py:101-102`): `if pos.entry_price <= 0 or pos.peak_price <= 0 or pos.current_price <= 0: continue` 完全 silent. zombie 期 19/19 持仓 current_price=0 全 skip 无任何 log/告警 → 14:30 evaluate 看似"健康 0 触发".

**根因 #3** (`scripts/services_healthcheck.py`): 只 probe Servy `status` 进程层, 不看 Redis 应用层 freshness (`portfolio:nav` updated_at gap / `qm:qmt:status` stream last event time). LL-074 投资在本类 zombie 模式无效.

### 教训

1. **Redis status key 必带 TTL + heartbeat refresh** — 边沿 SET 模式 (connect/disconnect 时 SET 一次) 在 service hang 时 silent. 必须 sync_loop 每周期 SETEX(2x sync interval) 让 key 自动 expire 兜底.
2. **Rule silent skip 大比例 (>50%) 必 fail-loud** — PMSRule 单股 skip OK (e.g. 1 股 entry_price=0 数据问题), 但 19/19 全 skip 是系统性故障, 必 log P1 + 钉钉告警.
3. **监控必看应用层 freshness 而非进程层 alive** — Servy `status=Running` 是必要不充分条件. 真生产监控必 probe (a) Redis 关键 key updated_at gap, (b) StreamBus 关键 stream last event time, (c) DB 关键表 last write time. 三层任一 stale > 阈值即视为 zombie.

### 应用规则

- **qmt_data_service.py 修复模板** (PR-X1):
```python
  # 边沿 SET → SETEX with TTL=120s (2x sync_loop 60s)
  self._get_redis().setex(CACHE_QMT_STATUS, 120, "connected")
  
  # sync_loop 每周期 heartbeat refresh
  def _sync_once(self):
      try:
          # ... query_positions / query_asset ...
          r.setex(CACHE_QMT_STATUS, 120, "connected") # 周期性 refresh
      except Exception:
          r.setex(CACHE_QMT_STATUS, 120, "disconnected")
  ```
- **PMSRule 修复模板** (PR-X2):
```python
  total_positions = len(context.positions)
  skipped_zero_price = 0
  for pos in context.positions:
      if pos.current_price <= 0:
          skipped_zero_price += 1
          continue
      # ... evaluate ...
  
  # fail-loud: 大比例 skip 必告警 (60% threshold)
  if total_positions > 5 and skipped_zero_price / total_positions > 0.6:
      logger.warning(
          "PMS skip ratio %d/%d (%.0f%%) suggests QMT data failure",
          skipped_zero_price, total_positions,
          100 * skipped_zero_price / total_positions
      )
      # 通过 RuleResult.metrics 上报 risk_event_log (而非吞)
  ```
- **ServicesHealthCheck 修复模板** (PR-X3):
```python
  # 加 Redis freshness probe
  nav_updated_at = json.loads(r.get("portfolio:nav") or "{}").get("updated_at")
  if nav_updated_at:
      gap = (datetime.now(UTC) - parse(nav_updated_at)).total_seconds()
      if gap > 300: # 5 min
          alerts.append(f"portfolio:nav stale {gap/60:.0f}min (zombie risk)")
  
  # 加 stream freshness probe
  last_event = r.xrevrange("qm:qmt:status", count=1)
  if last_event:
      last_ts_ms = int(last_event[0][0].split('-')[0])
      gap = time.time() - last_ts_ms / 1000
      if gap > 600: # 10 min
          alerts.append(f"qm:qmt:status stale {gap/60:.0f}min")
  ```

### 持久化

- 本 LL 条目 (LL-081)
- **PR-X1**: `scripts/qmt_data_service.py` SET → SETEX + sync_loop heartbeat (Session 38)
- **PR-X2**: `backend/qm_platform/risk/rules/pms.py` 大比例 skip fail-loud (Session 38)
- **PR-X3**: `scripts/services_healthcheck.py` Redis + stream freshness probe (Session 38)
- **LL-074 amendment**: 原 LL-074 "ServicesHealthCheck 投资 1 天内收回" 在本类 zombie 模式不成立, PR-X3 闭合此 gap.
- **铁律 33 fail-loud 强化**: 边沿 SET + 无 TTL = silent failure 模式之一, future Redis status key 设计必带 TTL + heartbeat.

---

## LL-082: SDK audit hook 时机 — 检查通过后批量 record 防 outbox phantom (Session 39, 2026-04-27)

### 现象

MVP 3.3 batch 3 (PR #109) `PlatformOrderRouter` 接 `audit_trail.record('order.routed', ...)` hook 时, **初版**写在 `orders.append(order)` 紧后 (per-signal 循环内). 审查发现: 当后续 `turnover_cap` 全局检查 raise `TurnoverCapExceeded`, 已生成的 1-N 个 Order 对应的 audit records 已 fire — Step 1 stub 仅 logger.info 无副作用, 但 MVP 3.4 替换为 `DBOutboxAuditTrail` 时, **outbox 表已写但实际 Order 未下单**, caller 重试整批 → outbox 重复 + 与单不一致.

### 根因

audit hook 时机错配. 原意 "Order 创建即刻 record" 是同步直觉, 但忽略了**整批校验失败**场景下, 已 record 但未生效的 phantom entries 污染 audit trail. 这类 contract 设计需考虑:
- **stub 期 vs concrete 期行为差异**: 当前 stub 安全, 替换 concrete (写 DB / event_bus) 时延迟暴露
- **失败原子性**: route() raise 时, 整批 orders 应视为"未执行", audit 也应"未记录"

### 教训

**SDK 接 audit hook 必批量 record (检查通过后), 非 per-event 即时 record**. 设计原则:

1. **暂存 metadata 而非即刻 record**: 循环内仅 `meta_list.append((target_shares, price))`
2. **全局检查通过后批量 record**: turnover_cap / IdempotencyViolation / InsufficientCapital 等所有 raise 路径过完后, `for order, meta in zip(orders, meta_list, strict=True): audit.record(...)`
3. **`if self._audit_trail is not None and orders:` 双 guard**: 空 orders 也跳过
4. **payload 含 `recorded_at` UTC timestamp**: schema 现锁定, MVP 3.4 outbox 不需迁移 (铁律 41)

### 应用规则

- **SDK 类接 hook (audit / event_bus / outbox)**: 凡涉及外部副作用的 record/publish, 必走"暂存 → 检查 → 批量 fire"模式
- **失败语义统一**: route() raise 时不留任何痕迹, 让 caller 重试干净
- **stub vs concrete 测试隔离**: stub 期就要测 "TurnoverCapExceeded 时 record_count == 0", 不等替换才发现

### 持久化

- 本 LL 条目 (LL-082)
- **PR #109 修复**: `backend/qm_platform/signal/router.py` 暂存 `order_audit_meta = [(target_shares, price), ...]` + 等 turnover_cap 检查通过后 `for order, (ts, p) in zip(orders, order_audit_meta, strict=True): audit_trail.record(...)`
- **配套 test**: `test_audit_no_phantom_records_on_turnover_cap_exceeded` (TurnoverCapExceeded 时 record_count == 0 invariant)
- **MVP 3.4 接入点**: `DBOutboxAuditTrail` 替换 `StubExecutionAuditTrail` 时无需改 router.py — hook 时机已正确

---

## LL-083: SDK type guard `isinstance(price, (int, float))` 拒 np.float64 / Decimal — Step 2 wire DAL 必炸 (Session 39, 2026-04-27)

### 现象

MVP 3.3 batch 2 Step 1 (PR #108) `PlatformOrderRouter.route()` 验证 `signal.metadata['price']` 时**初版**写:

```python
if not isinstance(price, (int, float)) or price <= 0:
    raise ValueError(...)
```

审查发现: 当 Step 2 wire `daily_pipeline` 时, price 来自 DAL (`access_layer.py:201` cast 到 float64) 或 QMT (`qmt_source.py:110 last_price: float64`) 都是 **`numpy.float64`** 类型. `isinstance(np.float64(100.0), (int, float))` 返 **False** — 每个 signal route 必 raise `ValueError`. 同理 `Decimal` 价格 (来自 metadata JSON 反序列化) 也被拒. **Step 1 SDK only 没暴露此 bug — Step 2 wire 时才炸**.

### 根因

Python type system 陷阱:
- `numpy.float64` 是 `np.floating` 子类, **不是** `float` 的子类 (PEP 3141 narrows numeric tower 但 numpy 不挂钩)
- `Decimal` 完全独立 (`numbers.Number` 兄弟分支), 跟 `float` 无 isinstance 关系
- `bool` 是 `int` 子类 (会通过 `(int, float)` check, 但语义错)

### 教训

**SDK 边界数值类型 guard 用 `float()` coerce + 显式验证, 不用 `isinstance((int, float))`**. 标准 pattern:

```python
try:
    price_f = float(price) # coerce np.float64 / Decimal / int / numeric str
except (TypeError, ValueError) as e:
    raise TypeError(f"price 必须可 float() 转换, got {type(price).__name__}") from e

if math.isnan(price_f) or math.isinf(price_f):
    raise ValueError(f"price 不能 NaN/inf, got {price!r}")

if price_f <= 0:
    raise ValueError(f"price 必须 > 0, got {price!r}")
```

关键设计:
- **拆 type vs value 错误**: TypeError (类型) vs ValueError (值), caller debug 时不被误导
- **NaN/inf 显式 guard**: `float('nan') <= 0` 返 False, NaN 会 silent pass `isinstance + > 0` 检查
- **bool exclusion** (可选): `isinstance(price, bool): raise TypeError` 防 `True/False` 当 1.0/0.0 用
- **String numeric accept**: `float("100.0")` 成功是 feature (JSON 反序列化容错)

### 应用规则

- **SDK 边界 (任何 caller 可注入数值的入口)**: 必走 `float()` coerce + 三层 guard (type / NaN-inf / value range)
- **DAL 返回 dtype 实测**: 写 SDK 前必读 DAL/source 返 dtype (`access_layer.py` / `qmt_source.py` / `tushare_source.py`), 不能假设是 stdlib float
- **Step 1 SDK only 测试覆盖**: 必含 `test_decimal_price_accepted` / `test_int_price_accepted` / `test_numeric_string_price_accepted` 防 Step 2 wire 时炸

### 持久化

- 本 LL 条目 (LL-083)
- **PR #108 修复**: `backend/qm_platform/signal/router.py` 改 `try: float(price) except → raise TypeError` + `math.isnan/isinf` guard + 拆 type vs value 错误消息
- **配套 5 tests** (TestPriceTypeFlexibility): Decimal / int / NaN / inf / non-numeric str / None 全覆盖
- **未来 SDK 数值入口 checklist**: route() / build() / compose() 等接 caller 数值参数时, 必跑此 pattern

---

## LL-084: Wave 3 主线大切片 — Session 38+39 单日 10 PR 实战记录 (2026-04-27)

### 现象

Wave 3 5/5 MVP 进度跨越 (Session 28-39):
- 3.1 Risk Framework: Session 28-30 (6 PR) ✅
- 3.2 Strategy Framework: Session 33-36 (5 PR) ✅
- **3.3 Signal-Exec Framework**: Session 38+39 (3 PR /5 子任务, 60% 完成)
 - ✅ batch 1 PlatformSignalPipeline (PR #107)
 - ✅ batch 2 Step 1 PlatformOrderRouter SDK (PR #108)
 - ✅ batch 3 StubExecutionAuditTrail (PR #109)
 - 🟡 batch 2 Step 2/3 (Tuesday 4-28+ 接力)
- 3.4 Event Sourcing 🟡 design only
- 3.5 Eval Gate 🟡 design only

Session 38+39 单日 (Monday 4-27) 18:00-22:30 累计 **10 PR merged**:
- LL-081 5 PR (#100/#101/#102/#103/#105) zombie 三通道 + trading_hours
- LL-076 phase 2 完结 2 PR (#104/#106)
- MVP 3.3 启动 3 PR (#107/#108/#109)

### 根因 / 模式

**LL-059 9 步闭环 7 次 (#72-#78) + 双 reviewer agent**:
- 平均每 PR ~30min (precondition + impl + tests + reviewer + fix + merge)
- reviewer 发现的 bug 包含 multiple 高价值 proactive 修 (LL-082 + LL-083)
- AI 自主 merge, user 接触 ~12 次 (主要授权 + 决策点)
- 0 regression / 0 production 事故 / pytest baseline 不增 fail

### 教训

**SDK only batch 模式适合 single session 高产出**:
- batch 1 + batch 2 Step 1 + batch 3 都是 SDK 不接生产 → regression trivially PASS
- **production switching batch (Step 2/3) 应隔离 single session** + clear mind 做
- 时间紧 + 累 + regression 硬门 = 高 fail 风险, 不强推

**reviewer agent 价值已超 'process formality'**:
- PR #107/108/109 共 35 项 findings, 0 假报, 修复 8 项 P1 (proactive 防 future bug)
- np.float64 type guard / json.dumps order_id / audit hook 时机 / fill_id PII — 都是 reviewer 抓的
- 单人开发场景 reviewer agent 是 force multiplier

### 应用规则

- **single session 上限 ~10 PR**: 累 + 时间紧 = regression fail 风险, 收尾优于强推
- **batch 切片设计**: SDK only / production switching 分开 PR, regression 硬门隔离
- **reviewer agent 当 partner**: 不当 process gate, 信任 0 假报 + bug 抓取能力
- **铁律 37 必做**: Session 关闭前 handoff 是不可省的最后一步, 防 compaction 上下文丢失

### 持久化

- 本 LL 条目 (LL-084)
- **Session 38+39 handoff**: `memory/session_38_handoff_2026_04_27.md` 含 4 part 加时记录
- **Wave 3 状态**: QPB Blueprint v1.10 (待 bump) MVP 3.3 60% 完成
- **下 Session 40 入口**: Tuesday 4-28 早间 + MVP 3.3 batch 2 Step 2 (regression 硬门)

---

## LL-085: 历史多日 batch 验证 > 等 production 单数据点 — 用户挑战驱动 (Session 39 加时, 2026-04-28 00:30)

### 触发场景

Session 39 半夜 PR #111 (Step 2.5 STRICT mode) merged 后, 我提议 "Tuesday 16:30 schtask 跑后看 parity OK 再 flip SDK_PARITY_STRICT=true". 用户立即挑战:

> "为什么要等16:30？而不能提前测试呢？"

一句击中懒惰假设. 16:30 不是物理硬约束, 它只是 production schtask 的下一次自动触发时刻. **历史 trade_dates 的 factor_values 全有数据**, `_run_sdk_parity_dryrun` 是 pure helper, 给定 (trade_date, factor_df, universe, industry, legacy_weights, conn) 就能跑.

### 改方案 — `scripts/sdk_parity_scan.py` 多日批量

30 min 写工具:
- 复用 production data-loading 链 (`load_factor_values + load_universe + load_industry`)
- `SignalService.generate_signals(dry_run=True)` 取 legacy weights (无 DB 写)
- `_build_sdk_strategy_context` + `PlatformSignalPipeline.generate(s1, ctx)` 取 SDK signals
- 比对 codes (`symmetric_difference`) + weights (`max(abs(a-b))`) → ParityResult

10 min 跑 14 个 trade_dates (4-07 ~ 4-24): **14/14 PASS**, codes=20 各日, max_w_diff=**0.00e+00 全场**.

证据强度: 14 数据点 vs 1 数据点 = **14 倍**, 时间成本 40 min vs 16 hours = **24 倍效率**.

### 根因

我陷入了"production = single authoritative data-point"的错觉. 实际上 production 只是真实数据的最新一帧, **历史数据帧同样是真实数据** — 都从同一 factor_values 表来. 多日扫不是"模拟", 是"批量回放真实数据".

类似的懒惰陷阱:
- "等明天看一下" → 今天能跑相同测试吗?
- "下周 stable 后再说" → 今晚多个版本对比有 blocker 吗?
- "production 跑过才知道" → 历史数据回放等效吗?

### 应用规则

任何"等 X 时刻才能验"的 claim, 先问:
1. **历史数据是否覆盖此 case?** factor_values / signals / klines_daily 等表通常有 N 年历史
2. **代码路径能否 dry-run?** SignalService 有 `dry_run=True`, 不写 DB
3. **batch 工具写多久?** 30-60 min 写一次性脚本 vs 16+ hours 等待
4. **失败 cost 不对称吗?** Tuesday 16:30 出 DIFF, 你已经睡了, schtask LastResult≠0 触发钉钉 → 人工值守; 今晚多日扫主动验证, 出 DIFF 立刻调试

**反例** (合理等待场景, 不适用本规则):
- 等真实交易日盘中数据 (盘后回放 ≠ 实时风险)
- 等用户行为/外部信号 (无法 retroactive)
- 等 OS / 第三方服务窗口 (不可控时间)

### 持久化

- 本 LL 条目 (LL-085)
- 工具: `scripts/sdk_parity_scan.py` (✅ 已删 Stage 3.1 cleanup PR #118 Session 40 2026-04-28; LL 历史 reference)
- 实战: PR #112 14/14 PASS 后当晚 flip STRICT=true (vs 等到 Tuesday 16:30)

---

## LL-086: Windows User env via setx — schtask spawn 自动继承, 不需 Servy 4 服务 restart (Session 39 加时, 2026-04-28 00:35)

### 触发场景

Session 39 PR #112 决议 flip `SDK_PARITY_STRICT=true`. 选项:
1. 改 `.env` 文件 (但 `run_paper_trading.py` 不调 `python-dotenv.load_dotenv()`, .env 不入 `os.environ`, 仅 pydantic-settings.Settings 读)
2. 修代码加 `python-dotenv.load_dotenv()` (要 Stage 2.5 改 production code, 风险)
3. **Windows User env via `setx`** (推荐)

### 关键认知

```powershell
# write
setx SDK_PARITY_STRICT true
# → 写 HKEY_CURRENT_USER\Environment, 持久化跨重启

# verify (registry-level, 必走 PowerShell)
[Environment]::GetEnvironmentVariable("SDK_PARITY_STRICT", "User")
# → 'true'

# verify (python sees it in fresh shell)
.venv\Scripts\python.exe -c "import os; print(os.environ.get('SDK_PARITY_STRICT'))"
# → 'true'

# rollback
[Environment]::SetEnvironmentVariable("SDK_PARITY_STRICT", $null, "User")
# 或 setx SDK_PARITY_STRICT ""
```

**当前 shell 不见 setx 改动**: setx 只影响**未来**进程. 若想验证, 必走新开 shell (PowerShell 工具每次 spawn 新 PS = 自动新 shell).

### schtask 继承机制

QuantMind_DailySignal 在 `setup_task_scheduler.ps1:85-108` 配置:
```powershell
$signalAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "$ProjectRoot\scripts\run_paper_trading.py signal" `
    -WorkingDirectory $ProjectRoot
# 无 wrapper, 无 -EnvironmentVariables, 无 .ps1 中转
```

→ 16:30 触发时 Task Scheduler 直接 spawn `python.exe`, 进程继承 **当时** Windows User env. setx 后任意时刻触发的 schtask 都见新 env.

### Servy 不需 restart

`SDK_PARITY_STRICT` 仅 `run_paper_trading.py` (schtask 调用) 读. Servy 4 服务 (FastAPI/Celery/Beat/QMTData) 都不读此 env, **不必 stop/start**.

(对比: `EXECUTION_MODE` 是 `app.config.Settings` 字段, FastAPI/Celery 都读 → 改它必 Servy restart 4 服务. SDK_PARITY_STRICT 是 raw os.environ, scope 窄, 不耦合 Servy.)

### 应用规则

env 改动决策树:
1. **谁读它?** grep + `app/config.py` Settings + 直接 `os.environ.get` 全找
2. **schtask 用?** setx + 不需 Servy restart
3. **Servy 服务用?** Servy stop/start (因 service 进程长生不读新 setx)
4. **代码 hardcode?** 改代码 + 走 PR
5. **rollback path 必预先想清楚** (任何 env 改动都要)

避免:
- 仅改 `.env` 但代码用 raw `os.environ.get` (silent no-op)
- 改 `.env` 后忘 Servy restart (Settings cached in process memory)
- 改 setx 后期望当前 shell 立即见 (必新开)

### 持久化

- 本 LL 条目 (LL-086)
- Session 39 PR #112: STRICT flip 切换 LIVE 实战
- 文档: Session 39 handoff 含 verify + rollback PowerShell 命令清单

---

## LL-087: Transition-only event audit log ≠ heartbeat — false-positive 告警 + 设计 anti-pattern (Session 40, 2026-04-28 10:00 真生产告警驱动)

### 触发场景

Session 40 Tuesday 早盘 10:00:03 CST 钉钉告警:

```
🚨 Services Health DEGRADED
✅ 4 服务全 RUNNING
✅ Beat heartbeat 0min ago
✅ redis:portfolio:nav: 0.4min ok
❌ redis:qm:qmt:status: 650.9min ago STALE (zombie 风险)
```

实测 QMT 完全健康 (portfolio:nav 3min前 fresh, 19 持仓 ¥1.015M, sync_loop 60s 正常跑).
**False-positive 告警**.

### 根因 (设计 anti-pattern)

`scripts/services_healthcheck.py:489-538` (LL-081 PR-X3 自加, Session 38) 把 Redis Stream
`qm:qmt:status` 当作 QMT 健康 heartbeat 检查. 但此 stream 是 **transition-only event audit
log** — `qmt_data_service.py:99/106/117` 仅在 connect/connect_failed/disconnected 时调
`_publish_status()` publish event. 健康连接保持连接 = 0 transitions = stream 自然 stale.

LL-081 PR-X3 作者 (Session 38 的本人) 已半意识到此问题, 加 `is_failure_alertable` flag +
`_is_trading_hours_now()` 在非交易时段降级 INFO 防噪声. 但**交易时段健康 QMT 也不该
transition** (连着不动) → 30min threshold 在交易时段照样 false positive.

### 概念错配

| | event 流 (transition-only) | heartbeat 流 (periodic) |
|---|---|---|
| 写入触发 | 状态变化 (connect / disconnect / fail) | 周期 (60s sync_loop tick) |
| 健康场景 | 0 events 完全合理 (稳定连接) | 必有定期 events (≤ tick interval) |
| 用途 | audit trail / event sourcing | liveness probe |
| stale 含义 | "无状态变化" (中性, 通常是好事) | "进程死了" (告警) |

LL-081 PR-X3 把第一类当第二类用 → 设计 anti-pattern.

### 修复 (Session 40 PR #113)

撤销 stream check, 仅保留 `portfolio:nav` updated_at age check:
- portfolio:nav 是 sync_loop 60s heartbeat (`_sync_positions` 调 `query_asset()`
 成功后才写 nav 含 updated_at)
- sync_loop 死 → query_asset() throws → except 路径 → nav 不更新 → 5min threshold
 自然 stale → 告警
- portfolio:nav 单 probe 已是 strict superset, cover Monday 4-27 LL-081 zombie 4h17m 场景
- 移除 197 行: stream check block (50) + `_is_trading_hours_now` (24) + `is_failure_alertable`
 field (3) + 11 obsolete tests + helpers

### 应用规则

**判断 Redis Stream / Kafka / event-sourced log 是不是 heartbeat candidate**:

1. **写入是 periodic 还是 event-driven?** Periodic OK 当 heartbeat, event-driven 必拒.
2. **健康系统期望事件频率多少?** 健康系统 0 events 期间正常 → 不是 heartbeat.
3. **如果换更长 threshold 能否避免 false positive?** 不能 — event 频率非时间均匀分布,
 threshold 调多大都漏抓 / 误报随机交替.
4. **替代方案:** 找业务侧 periodic 写入的 key (`portfolio:nav` updated_at, `setex` TTL
 key, 心跳文件 mtime), 或者新加一个独立的 periodic heartbeat publisher.

**反例 (合理 stream-based health 检查)**:
- 检查 stream 是否**存在** (不查 last event time): event-sourced 系统初始化校验
- 检查 stream **总长度增长率**: 业务流量监控 (高频系统下变 heartbeat-like)
- 检查 **特定 event type 比例**: anomaly detection (e.g. failed:total > 0.05)

### Defense-in-depth 真实定义

LL-081 PR-X3 名义上"两层兜底", 实际两 probe 共享同一根 (sync_loop 死). defense-in-depth
需要 INDEPENDENT failure mode probe. 例:
- Probe 1: portfolio:nav age (sync_loop liveness) — depends on sync_loop
- Probe 2: 独立进程直 ping QMT broker — 不 depends on sync_loop, 独立

本 PR 仅去伪 probe (stream), probe 2 留 future work (超 PR scope).

### 持久化

- 本 LL 条目 (LL-087)
- 修复: PR #113 (commit `3c00b12` + reviewer fix `950a554`), Session 40 main @ `950a554`
- 反例参考: Session 38 LL-081 PR-X3 设计 over-engineering, 本 LL 修正
- 双 reviewer 仅 code-reviewer 单审 (cleanup PR python-reviewer 增量价值低): 0 P1 / 2 P2 (1 采纳 / 1 拒绝技术依据) / 1 P3 采纳
- 应用规则未来必查: 任何加新 Redis key freshness check 前先 grep "publish_sync\|setex\|expire", 区分 transition-only vs periodic.

---

## LL-088: Resource counter 必加 GC finalizer 兜底 — 假告警吞 222+ 次/日 (Session 40, 2026-04-28)

### 触发场景

Session 40 (2026-04-28 14:30) Tuesday 早盘 sanity scan 发现 celery worker logs 频繁告警:

```
[2026-04-28 14:55:00,015: WARNING/MainProcess] sync连接数达到上限(15)，可能存在连接泄漏
```

频次累计 (`grep -c "连接数达到上限" logs/celery-stderr.log`):
- 2026-04-25 (Sat): 0
- 2026-04-26 (Sun): 0
- **2026-04-27 (Mon): 219** — MVP 3.1 真生产首日 10:10 起 (intraday-risk-check `*/5 9-14`)
- **2026-04-28 (Tue 14:55前): 233** — 持续累积

### 根因 (实测发现)

`_TrackedConnection` (`backend/app/services/db.py`) wrapper 跟踪 `_active_count`:
- `get_sync_conn()` 增计数
- `_TrackedConnection.close()` 减计数 (gated on `_counted=True`, 防双减)

**漏洞**: 调用方未显式 `conn.close()` (依赖 GC / `with` 退出 / 异常路径) 时:
- psycopg2.connection 自身 `__del__` 关闭 socket → PG conn 释放正常
- BUT `_TrackedConnection.close()` 永不被调 → `_counted=True` 永不 decrement
- counter 累积 → 超过 `_MAX_CONNECTIONS=15` → 每次后续 `get_sync_conn()` fire warning

**实测验证**: PG `pg_stat_activity` active+idle conns = **2** (TimescaleDB Background + 1 probe). **非泄漏 — counter logic 漏洞** 假告警 ~222 次/日.

### 特例 (推动 counter 不减): with-block 路径

```python
with get_sync_conn() as conn: # __enter__ 返 self._conn (raw psycopg2 conn)
    cur = conn.cursor()
    cur.execute(...)
# __exit__ 仅 commit/rollback, 不 close conn (psycopg2 设计)
# wrapper 脱离 with 后 ref count = 0, GC 自动 finalize, BUT close() 未被调
```

`with` 退出时调 `_TrackedConnection.__exit__` → `self._conn.__exit__` → psycopg2 conn `__exit__` 仅事务边界, 不 close 连接. wrapper 脱离 scope 后 GC 处理 — 之前的设计依赖 `__del__` 但 `__del__` 不存在.

### 修复 (PR #115 commit `3798ddd` + `6107817`)

加 `__del__` finalizer 兜底:

```python
def __del__(self):
    """GC 兜底 counter decrement + connection close (defense-in-depth)."""
    try:
        if self._counted:
            object.__setattr__(self, "_counted", False)
            global _active_count
            _active_count = max(0, _active_count - 1)
        self._conn.close() # idempotent, defense-in-depth for non-CPython runtime
    except Exception: # noqa: BLE001
        pass # silent_ok: __del__ during interpreter shutdown when globals may be unset
```

设计要点:
- 显式 `close()` 路径不变 (`_counted=False` gate 防双减, CPython GIL 保单线程 close + __del__ 不竞态)
- GC 路径新增兜底 — 调用方 leak wrapper 不再 leak counter
- silent except 防 interpreter shutdown 时 globals 可能 None
- 显式调 `_conn.close()` defense-in-depth (PR #115 reviewer P2 采纳, PyPy / cyclic ref 路径)

### 应用规则 (设计 review checklist)

**任何 module-level resource counter (DB conn / file handle / lock / socket / etc.)**:

1. **必有 `__del__` finalizer 兜底 GC 路径** — 不能仅依赖显式 release. Python 调用方实际:
 - 显式调 `.close()` ✅ 但 ~30% 路径漏
 - `with` block 退出 — 取决于 `__exit__` 实现
 - 异常路径未 try/finally — 100% leak
 - 局部 var 出 scope GC 回收 — 依赖 finalizer
2. **Finalizer 必含 silent except** — interpreter shutdown 时 globals 可能 None, 抛异常污染 stderr
3. **底层资源 close 在 finalizer 中 idempotent 调用** — defense-in-depth (PyPy / cyclic ref)
4. **重复 release 必 gate** — boolean flag (`_counted=False`) 防双减 → counter 误负
5. **counter underflow 必 `max(0, ...)`** — CPython GIL 保单线程不会双减但需注释说明

**反例 (本 LL 触发的 anti-pattern)**:
- 仅 close() 减 counter, 无 `__del__` 兜底
- 调用方手册说 "用完必须 close()" — 实际上调用方总有 30% 漏

### 持久化

- 本 LL 条目 (LL-088)
- 修复: PR #115 (commits `3798ddd` + `6107817`), main @ `6107817`
- 测试: `backend/tests/test_db_tracked_connection.py` 10 tests cover close / del / passthrough / close-raise edge case
- 后续 (Session 41+): celery worker logs 监控验证假告警停止 (期望 4-29 起 0 occurrences)
- 应用 checklist 未来 review: 加新 resource counter 必查 4 步法 (finalizer / silent except / idempotent close / underflow guard)

## LL-089: Claude spike prompt 候选集封闭 + 不查 user 决策日志 — 漏判因 (Session 45 加时, 2026-04-30 14:50 user 质问驱动)

**事件**: D3-A Step 4 spike PR #158 (14:48 merged) 误判 root cause "L1 QMT 4-04 01:06 断连后 user **未察觉** (运维 gap)". user 14:50 质问 "4.29 我叫你清仓的, 你忘记了？没有记录了？" 触发回查. 实测 [memory/project_sprint_state.md:27](memory/project_sprint_state.md:27) Session 44 末 handoff **明确记录** "用户决策"全清仓暂停 PT + 加固风控"". CC 漏读 handoff, Claude 当时 PR #150 prompt **主动**把 "全清仓" 转化为 link-pause (commit `626d343` 2026-04-29 20:39, 紧急清仓留 user 手工 `emergency_close_all_positions.py`).

**根因**: Claude spike prompt 设计两层错:
1. **候选集封闭** — 列 A (silent drift) / B (paper 污染) / C (DB 同步) 假装穷举, 漏 D "Claude 自身 prompt 设计错 (4-29 软处理 user 金指令)"
2. **不查 user 决策日志** — Q-Pre 块缺失. 没 grep handoff / project_sprint_state / 4-29 commit timeline 找 user 真实决策原文

**复用规则 (任何 spike prompt 必含)**:
1. **Q-Pre 块** (前置必做): 查 handoff / `memory/project_sprint_state.md` / 最近 N 天 user 决策日志 / 4-29 commit timeline / docs/audit 历史 STATUS_REPORT
2. **候选集开放**: 列已知候选 + 1 个 "**unknown / 不在上述任何候选**" (留出 Claude 自身 / 流程债 / 跨 session context 等盲区)
3. **决议规则不强收敛**: N 项证据 align 但根因解释还有歧义 → STOP, 不下决议. 防止 4 项证据 misleading aligned 但都解释同一表象 (如 Step 4 4 项证据均显示 "DB 静止", 但根因可以是 silent drift OR Claude 软处理 user 指令)

**实战次数**: D3-A 自身 14 次 + Step 4 修订 2 次 (LL-089 + LL-090) = 累计 22 次同质 LL.

## LL-090: Claude 让 user 二次验证 ground truth (D44 减负教训扩展, Session 45 加时, 2026-04-30 15:00)

**事件**: 14:48 Step 4 spike merged 时, user 已明确陈述 "我已经把 QMT 全部清仓" + "不影响 PR #158+ 启动". CC 在 spike 报告 "用户决策点" 段写: "user 何时清仓 QMT? 4-04 之前还是之后? (帮助回填 Redis cache 时间线)" — **让 user 二次验证 ground truth**. user 14:50 质问也部分由此引发.

**根因**: CC 把 user 陈述当作"待验证假设"而非 ground truth. 这是 D44 减负教训 (LL-068+ "user 减负原则") 的反向同质违反: "let user verify" = "user 帮 CC 干活", 不让 user 减负.

**复用规则**:
1. user 已明确陈述的事实 → **标 ground truth**, 不需 user 二次验证
2. 所有 forensic 数据 (timestamps / prices / counts / paths) → **CC 自查**:
 - DB SQL SELECT
 - 文件系统 grep
 - xtquant API read-only (Q1.b 实测真账户)
 - QMT 客户端 log forensic (Q2 4-29/4-30 XtMiniQmt log)
 - Servy stop/start (Q1.c read-only 重连尝试)
3. 实在无法 CC 自查 (e.g. user 头脑里的私人记忆) → 标 "**CC 不可考, user 陈述作 ground truth, 真实数据无法重建**", 不让 user 提供, 不影响决议
4. spike 报告 "用户决策点" 段仅含**决议问题** (启动顺序 / 优先级 / 风险接受度), **不含** ground truth 验证

**实战 case (Step 4)**:
- ✅ Q1.b xtquant API 实测: 真账户 0 持仓 + cash ¥993,520.16 (CC 自查, 不让 user 验证)
- ✅ Q2 4-29/4-30 XtMiniQmt log forensic: 4-29 全天 1210 次 19 持仓 / 4-30 仅 1 次 (CC 自查)
- ✅ 价格 forensic 不可考 → 标 "user GUI 手工 sell 不走 API, 价格无法重建", 不让 user 提供, 推算损失 -¥18,194 (-1.8%) 由 NAV diff 推

**实战次数**: 累计 22 次同质 LL (LL-089 + LL-090 同 batch).

## LL-091: 推断必明示 "推论=不实测", 留 P3-FOLLOWUP 真实测验证 — D3-A Step 4 stale Redis cache 推论被 D3-B 0 keys 实测推翻 (Session 45 D3-B, 2026-04-30 17:00)

**事件**: D3-A Step 4 spike PR #158 + 修订 v1 PR #159 推断 "DB 4-28 19 股 stale snapshot = stale Redis cache 写入" (Q4 conclusion + 5-layer L4 + L4 NEW v1 全采用此推论). 推断基础: 2 项前提 (a) qmt_data_service 4-04 起断连 26 天 silent skip → portfolio:current cache 状态推测 stale + (b) DB 4-28 19 股 = DailySignal 4-28 16:30 跑过 → 推 "经 stale Redis cache 写 DB". D3-B PR #162 F-D3B-7 Q5.1 redis-cli 实测: `KEYS "portfolio:*" = 0`. 推翻原推论 — Redis cache **完全不存在** (qmt_data_service 26 天 SET 0 次 → key TTL 自然到期 expired), 因 QMTClient fallback 路径直读 stale DB position_snapshot 自身 (cache miss → DB self-referential stale loop, Redis 旁路).

**根因**: Step 4 spike report Q4 conclusion 写 "stale Redis cache 写入" 时, **没实测** redis-cli `KEYS "portfolio:*"` / `TYPE` / `TTL`, 仅基于 "qmt_data_service silent skip 26 天" + "DB 4-28 stale" 双前提推断 cache 状态. 缺 P3-FOLLOWUP 标 "本结论是推论, 待 redis-cli 实测验证".

**复用规则 (任何 spike / status_report / finding 含 "推断 / 推测 / 推论" 字样)**:
1. **明示** "本结论基于 N 项前提推论, 推论 ≠ 实测"
2. **列前提**: 每项前提附 "(已实测 ✅ / 待实测 ⚠️)" 标
3. **留 P3-FOLLOWUP 标**: 推论部分单独段落 + ✋ icon + "实测命令: <CLI>" 留待后续 spike / audit 实跑
4. **决议规则**: 推论部分**不**作为 root cause 主链节点, 仅作辅助证据. root cause 必须**全实测**支撑

**实战 case**:
- ❌ D3-A Step 4 Q4(c) "DB 4-28 19 股 = stale Redis cache 写入" — 推论, 没实测 redis-cli, 后被 D3-B 推翻 (本 LL)
- ✅ 修订: 加 "P3-FOLLOWUP: redis-cli KEYS portfolio:* 实测 verify cache 是否存在" 标, 推论段独立, 不作 L4 主链
- ✅ D3-B Q5.1 实测纠错: redis-cli DBSIZE / KEYS "portfolio:*" / TYPE / TTL 全 4 命令 → 推翻 4 个推论同时

**实战次数**: 累计 23 次同质 LL (LL-089 D3-A 候选集封闭 + LL-090 让 user 验证 ground truth + LL-091 本 LL).

### 持久化

- 本 LL 条目 (LL-091)
- 修复: PR #163 (`32a1ef1`, D3-A Step 4 spike L4 修订 v2) 加 "L4 修订 v2" 段引 D3-B F-D3B-7 实测; PR #164 (本 PR `chore/d3b-cross-doc-sync`) 入册 LESSONS_LEARNED.md
- 实测命令固化: `redis-cli DBSIZE` / `redis-cli KEYS "<prefix>:*"` / `redis-cli TYPE <key>` / `redis-cli TTL <key>` 必入 D3-C / 批 2 audit checklist

## LL-092: 文档 N 个 ≠ 实测 N 个 alive — StreamBus "10 streams" claim 实测仅 1/8 alive (Session 45 D3-B, 2026-04-30 17:00)

**事件**: CLAUDE.md L31 + memory frontmatter 长期 claim "Redis Streams `qm:{domain}:{event_type}`, StreamBus 模块" + "10 streams". D3-A Step 1 + Step 5 跨 spike 假设 "8 streams 是 10 streams 子集, sample N 全 alive 推全 alive". D3-B PR #162 F-D3B-6 Q5.1 redis-cli 实测: `KEYS "qm*"` 7 hits + `KEYS "qmt*"` 1 hit, 共 8 streams (非 10). **TYPE + TTL 实测每条**: 仅 `qm:order:routed` TYPE=stream + TTL=-1 alive ✅, 其他 7 个 TYPE=none + TTL=-2 (key 已 expired, KEYS 返回是 ghost). ** alive 比率 1/8 = 12.5%**.

**根因**: D3-A 系列 spike 对 streams 状态采用 "sample 全 alive 推全 alive" 假设, 没逐条 TYPE + TTL 实测. 文档"10 streams"长期 stale, "8 streams 子集"假设也错误. alive 1/8 严重违反铁律 X5 (文档单源化).

**复用规则 (任何 "文档 N 个 / 实测 ≤ N" 类假设)**:
1. **逐条实测**: 每条 key / stream / migration / table / endpoint 必单独 TYPE + TTL + state 实测
2. **不接受 sample 推全**: "sample 5 个全 alive → 推 N 全 alive" 永远错, alive 是 boolean per-instance, 不可统计推论
3. **alive 比率 < 90% → 文档腐烂红线**: 单源化文档 claim 与实测 alive 比率 diff > 10% 必触发 audit + 修文档
4. **死 key 处理**: TYPE=none + TTL=-2 是 ghost key (KEYS 返回, 但已 expired), 不 alive, 必标 dead 不 alive

**实战 case**:
- ❌ D3-A Step 1+5 假设 8 streams 全 alive — sample 推全, 没逐条实测 TYPE/TTL
- ✅ D3-B Q5.1 实测纠错: 8 streams 逐条 TYPE+TTL → 1 alive (qm:order:routed) + 7 dead (TYPE=none + TTL=-2)
- ⚠️ 修文档红线触发: F-D3B-6 P1, CLAUDE.md L31 + memory frontmatter "10 streams" claim 待 D3-C 整合 PR 修

**实战次数**: 累计 24 次同质 LL (含本 LL).

### 持久化

- 本 LL 条目 (LL-092)
- 修复: PR #164 (本 PR) 入册 LESSONS_LEARNED.md; D3-C 整合 PR 修 CLAUDE.md L31 + memory frontmatter "10 streams" claim
- 实测命令固化: `redis-cli KEYS "<pattern>"` + `redis-cli TYPE <key>` + `redis-cli TTL <key>` 必入 D3-C / 批 2 audit checklist (与 LL-091 同源)

## LL-093: forensic 类 spike 必查 5 类源 — D3-A Step 4 spike 漏查 logs/emergency_close_*.log 致 narrative v1+v2 全错 (Session 45 D3-C+v3 修订, 2026-04-30 17:30)

**事件**: D3-A Step 4 spike (PR #158, 4-30 14:48) + 修订 v1 (PR #159, 15:14) + 修订 v2 (PR #163, 16:30) 推断 "user 4-30 GUI 手工 sell 18 股" + "Claude PR #150 软处理 user 金指令". D3-C STATUS_REPORT (PR #165, ~17:00) F-D3C-13 实测发现:

- `logs/emergency_close_20260429_*.log` 5 文件 (项目本地, **非** XtMiniQmt query log)
- 4-29 10:43:54 emergency_close_20260429_104354.log 13,992 字节含完整 18 股 sell trace
- chat-driven `--confirm-yes` flag bypass interactive prompt
- 18 unique tickers 全 status=56 traded N/N (含 1 partial fill 002623)

→ **CC 4-29 上午 ~10:43 通过 chat 授权用 emergency_close_all_positions.py 实战清仓 18 股**, 不是 4-30 GUI 手工 sell. D3-A Step 4 spike narrative v1+v2 全错.

**根因**: D3-A Step 4 spike forensic 仅查 1 类源 (`E:/国金QMT交易端模拟/userdata_mini/log/XtMiniQmt_*.log` query 路径), 没扩到项目本地 `logs/emergency_close_*.log` order 路径. forensic 类 spike 5 类源缺 1 (项目本地 logs/), 导致 narrative 误判.

**复用规则 (forensic 类 spike 必查 5 类源, 缺 1 即 STOP)**:
1. **(a) 项目本地 logs/ 全文件** (含 emergency_close_* / pt_audit_* / health_check_* / signal_phase_* / etc, **不仅查通用 stdout/stderr**)
2. **(b) git commit log 全期** (`git log --all --since=<date>` + grep chat-driven 调用证据 / 关键 keyword)
3. **(c) DB 表 query**:
 - `risk_event_log` (新事件 audit)
 - `scheduler_task_log` (schtask + Celery task 历史)
 - `trade_log` (真实成交)
 - `position_snapshot` / `performance_series` (DB state 时间线)
4. **(d) Redis Streams XRANGE + XLEN** (实测每 stream, 非 sample, 沿用 LL-092)
5. **(e) QMT 客户端 log 全 3 类**:
 - XtMiniQmt query log (`E:/国金QMT交易端模拟/userdata_mini/log/`)
 - xtquant API order/trade log (项目本地 logs/emergency_close_* / logs/qmt-*)
 - QMT GUI manual operation log (用户手动 sell, 通常在 `userdata/log/Tdx/`)

**实战 case (D3-A Step 4 spike forensic 漏查)**:
- ❌ v1 (PR #158): 0 forensic, 仅推断 "user 未察觉" (后被 v1 修订推翻)
- ❌ v1 修订 (PR #159): 仅查 (e) XtMiniQmt query log, 推断 "user 4-30 GUI sell, 价格不可考"
- ❌ v2 (PR #163): 加 D3-B F-D3B-7 实测推翻 "stale Redis cache" 推论, 但 narrative L1-L4 主体不变
- ✅ v3 (PR #166 + D3-C F-D3C-13): 查 (a) 项目本地 logs/emergency_close_* → 因暴露 (CC 4-29 10:43 实战 sell), narrative v1+v2 全推翻

**反思**: forensic 类 spike 必须**先**枚举 5 类源, **再**逐条实测 + 标已查/待查. D3-A Step 4 prompt 设计层默认仅查 (e) XtMiniQmt, 漏 (a) + (b) + (c) + (d). LL-091 (D3-A 推断 stale Redis cache 漏 redis-cli) 是 LL-093 的 (d) 维度同质 case.

**实战次数**: 累计 25 次同质 LL (LL-091/092/093 同源 D3 全方位审计 5 类源覆盖反思).

### 持久化

- 本 LL 条目 (LL-093)
- 修复: PR #166 (本 PR) 入册 LESSONS_LEARNED.md + SHUTDOWN_NOTICE_2026_04_30.md §11 v3 修订段引用
- forensic 5 类源 checklist 固化: (a) 项目 logs/ + (b) git log + (c) DB 4 表 + (d) Redis Streams + (e) QMT 3 子类 log. 必入 D3 整合 PR / 批 2 spike prompt template
- 关联: D3-C F-D3C-13 (P0 金) + STATUS_REPORT_D3_C + d3_6_monitoring_alerts F-D3C-13 详细证据

## LL-094: risk_event_log CHECK constraint allowed values 必先 pg_get_constraintdef 实测 (T0-19 Phase 1 收尾, 2026-04-30 17:30)

**事件**: D3-A Step 5 (PR #160) Q2(c) 设计 SQL 模板用 `action_taken='manual_audit_recovery'` INSERT risk_event_log P0 audit row, **被 PG CHECK constraint 拒**:

```
ERROR: new row for relation "_hyper_9_208_chunk" violates check constraint
       "risk_event_log_action_taken_check"
DETAIL: Failing row contains (..., manual_audit_recovery, ...).
```

实测 `pg_get_constraintdef`:
```
risk_event_log_action_taken_check:
  CHECK (action_taken IN ('sell', 'alert_only', 'bypass'))
```

→ 改用 `action_taken='alert_only'` (silent drift audit 仅 alert 不 action) → INSERT 成功 (id=67beea84-e235-4f77-b924-a9915dc31fb2).

**根因**: Claude Phase 1 design 阶段假设 action_taken 是 free-form text, 没先查 CHECK enum. PG 拒后才回查实测.

**复用规则 (任何 SQL INSERT 含 CHECK 字段前必先实测)**:
1. **目标表 CHECK constraint enum 必先 pg_get_constraintdef**:
```sql
   SELECT conname, pg_get_constraintdef(c.oid)
   FROM pg_constraint c
   JOIN pg_class t ON c.conrelid = t.oid
   WHERE t.relname = '<table>' AND c.contype = 'c';
   ```
2. **不假设 enum 含义**: 'sell'/'alert_only'/'bypass' 是 ops 决策语义 (action 发 vs 仅 alert vs 故意 bypass), 不是 audit category. T0-19 emergency_close audit row 用 'sell' 贴清仓语义.
3. **任何文档 / spike prompt 设计 INSERT SQL 模板时必标 "CHECK enum 已实测 ✅" + cite pg_get_constraintdef 输出**, 否则视为推论 (沿用 LL-091 复用规则)
4. **CI / 验证脚本 layer**: scripts/audit/check_alembic_sync.py 候选扩 — 启动期 `pg_get_constraintdef` 全 audit 表 + grep 代码 INSERT SQL 字串匹配 enum 值

**实战 case**:
- ❌ D3-A Step 5 PR #160 SQL 模板 'manual_audit_recovery' 被拒 (踩坑)
- ✅ Phase 1 §1 Q3 实测确认 'sell'/'alert_only'/'bypass' 3 enum
- ✅ T0-19 Phase 2 audit row 用 'sell' (emergency_close 清仓), 区别于 PR #161 id=67beea84 用 'alert_only' (silent drift 仅 alert)

**关联 LL**: 与 LL-091 (推断必标 P3-FOLLOWUP) 同源 — 都是 "假设 → 实测推翻" 第 N 次. 但本 LL 范围特定 (CHECK constraint), 复用规则更具体可操作.

**实战次数**: 累计 26 次同质 LL (LL-091/092/093/094 同源 D3 系列假设必实测).

### 持久化

- 本 LL 条目 (LL-094)
- 触发 case: PR #160 D3-A Step 5 Q2(c) 'manual_audit_recovery' 被拒
- 验证 case: PR #161 ID=67beea84 INSERT 成功 (用 'alert_only')
- Phase 1 sweep 入册: PR #167 (本 PR) 收尾 commit
- 沿用扩展: 任何 SQL INSERT 含 CHECK 字段前 `pg_get_constraintdef` 实测 + 标 "CHECK enum 已实测 ✅"
- 候选扩 scripts/audit/check_alembic_sync.py 加 CHECK enum 全 audit (Wave 5+)

## LL-095: emergency_close status=57 cancel 因综合判定 — 不假设单一原因 (D3 整合 v4 narrative, 2026-04-30 18:30+)

**事件**: PR #168 Phase 2 实测 `logs/emergency_close_20260429_104354.log` 发现 18 orders placed 中 1 笔 cancel:

```
2026-04-29 10:43:57,400 [INFO] [QMT] 下单: 688121.SH sell 4500股 @0.000 type=market
2026-04-29 10:43:57,506 [ERROR] [QMT] 下单失败: order_id=1090551149,
    error_id=-61, error_msg=最优五档即时成交剩余撤销卖出 [SH688121]
    [251005][证券可用数量不足]
2026-04-29 10:43:57,506 [INFO] [QMT] 委托回报: order_id=1090551149,
    code=688121.SH, status=57, traded=0/4500
```

CC 单方面假设 "T+1 当日买入限制" 触发 cancel — 实测 position_snapshot 显示 [688121.SH](https://github.com) 4500 股自 4-20 起持仓 ≥ 9 天, T+1 应早已解除. **假设错**.

User 4-30 confirm 因: **跌停撮合规则**. 卓然 4-29 跌停 (-29% 量级), `MARKET_SH_CONVERT_5_CANCEL` (xtconstant 42, 最优五档即时成交剩余撤销) 撮合规则下跌停板**无买盘对手方**, broker 视可用数量=0 → cancel.

**根因**: error_id=-61 "证券可用数量不足" 因**多元**, 不可单一假设. 至少 4 维度 cover:
1. **市场行情**: 跌停 / 涨停 / 停牌 (本 case 命中跌停)
2. **broker 撮合规则**: 最优五档即时成交剩余撤销 vs 限价 vs 市价 vs 集合竞价 (本 case 五档撮合规则下跌停 cancel)
3. **持仓时间**: T+1 当日买入限制 (本 case 排除, ≥ 9 天持仓)
4. **持仓状态**: 质押 / 司法冻结 / 风险警示 lockup (本 case 排除)

**复用规则 (任何 emergency_close / live trade cancel 解释)**:
1. **status=57 (cancel) 必查 4 维度**: market state + broker rule + holding age + position state
2. **error_id=-61 不假设单一原因**: "证券可用数量不足"是症状, 因需 broker statement / market log / 行情数据综合
3. **audit hook 仅 backfill status=56 fills**: 失败单不 fabricate (沿用铁律 27, T0-19 Phase 2 已实现 ✅)
4. **narrative 写因前必 user confirm 或 broker statement 实测**: 不可 CC 单方面推断

**实战 case (4-29 [688121.SH](https://github.com))**:
- ❌ CC 假设 T+1 → 实测 4-20+ 持仓推翻
- ❌ CC 假设 broker bug → 4 维度排查后 user confirm 跌停 + 五档撮合
- ✅ 因 user confirm: 跌停 (1) + 最优五档撤销 (2)
- ✅ T0-19 Phase 2 audit hook **正确处理**: 仅 17 fills backfill, 不 fabricate 1 失败单

**实战次数**: 累计 27 次同质 LL (LL-091~094 + 本 LL).

### 持久化

- 本 LL 条目 (LL-095)
- 触发 case: PR #168 Phase 2 test_parse_real_log_17_fills_not_18 实测 + user 4-30 confirm 跌停因
- 关联 PR: PR #166 v3 → **PR #169 v4 narrative 修订** (17+1 hybrid 定论)
- 沿用扩展: emergency_close hook 设计 / 金 audit 描述必含 4 维度排查 checklist
- 关联代码: `scripts/emergency_close_all_positions.py` 用 `MARKET_SH_CONVERT_5_CANCEL` (xtconstant 42) + `MARKET_SZ_CONVERT_5_CANCEL` (47); `backend/engines/broker_qmt.py` 注释 "最优五档即时成交剩余撤销"

## LL-096: forensic 类 spike 修订不可一次性结论 — 必留"未确认尾巴" (D3 整合 v4 narrative, 2026-04-30 18:30+)

**事件**: D3-A Step 4 narrative 4 轮修订:

| 版本 | PR | 主张 | 推翻原因 |
|---|---|---|---|
| **v1** | #158 | "user 未察觉 + L1 QMT 4-04 断连后运维 gap" | user 4-30 14:50 质问 "4.29 我叫你清仓的, 你忘记了?" |
| **v1 修订** | #159 | "user 4-29 ~14:00 决策 + Claude 软处理 link-pause + user 4-30 GUI sell 18 股" | D3-C F-D3C-13 实测 logs/emergency_close_20260429_104354.log |
| **v2** | #163 | (L4 因果链精化, L1-L3 narrative 主体不变) | (L4 仍成立) |
| **v3** | #166 | "CC 4-29 emergency_close 18 股全 status=56" | PR #168 实测 17 fills + 1 cancel |
| **v4** | #169 (本 PR) | "17 CC 4-29 + 1 user 4-30 GUI sell hybrid + 跌停撮合因" | (本 PR 定论) |

4 轮修订 50 小时 (4-30 13:30 PR #158 → 18:30 PR #169) 暴露 forensic 类 spike 单次结论易漏:
- v1: 漏 user 决策日志 (handoff)
- v1 修订: 漏 logs/emergency_close_*.log
- v3: 漏 status=57 / error_id=-61 / 跌停撮合 / broker side 上下文

**根因**: forensic 类 spike 默认"结论性表述", 不留 P3-FOLLOWUP 标. 沿用 LL-091 (推论必标 P3-FOLLOWUP) + LL-093 (forensic 5 类源) 加强:

**复用规则 (forensic 类 spike 修订防过度修正)**:
1. **结论必加 v_N 修订标记**: 每次 narrative 重大修订 bump version (v1 → v2 → v3 → v4), 不简单覆盖, 保留历史层叠 archive
2. **forensic 4 维度自检 checklist**:
 - (a) **5 类源** (LL-093): 项目 logs/ + git log + DB 4 表 + Redis Streams + QMT 3 子类 log
 - (b) **市场行情**: 跌停 / 涨停 / 停牌 / 集合竞价
 - (c) **broker 撮合规则**: 最优五档 / 限价 / 市价 / 集合
 - (d) **市场参与者状态**: 持仓时间 / 质押 / 司法冻结 / 风险警示
3. **未确认尾巴标识**: 任何"由 X 推断, 但 broker 端未 confirm" 段必加 "[P3-FOLLOWUP: user/broker confirm 后定]" 标
4. **修订门槛**: 修订前必 user confirm 或 broker statement 实测, 不 CC 单方面推断 (沿用 LL-091)

**实战 case (D3-A Step 4 narrative 4 轮修订)**:
- v1 → v2 (P3-FOLLOWUP missing): 推断 stale Redis cache 是 DB stale 源 → D3-B Q5.1 实测 0 keys 推翻
- v3 → v4 (broker side 漏): 假设 18 全 status=56 → PR #168 实测 17+1 推翻
- v4 (本 PR): 加 4 维度 checklist + user confirm 跌停撮合, 留 "[P3-FOLLOWUP]" 标记如下次发现新维度

**实战次数**: 累计 28 次同质 LL (LL-091~095 + 本 LL, D3 系列假设必实测全部 28 次同源).

### 持久化

- 本 LL 条目 (LL-096)
- 触发 case: D3-A Step 4 narrative 4 轮修订暴露 forensic 类 spike 单次结论风险
- 关联 PR: PR #158/159/163/166/169 (4 轮 narrative)
- 沿用扩展: 任何 forensic / spike / status_report PR 必含
 (a) v_N 修订标记
 (b) 4 维度 self-check (5 类源 + 市场行情 + broker 撮合 + 持仓状态)
 (c) [P3-FOLLOWUP] 标记未确认尾巴
- 关联其他 LL: LL-091 (P3-FOLLOWUP 推论必标) + LL-093 (forensic 5 类源) + LL-095 (status=57 因综合判定)
- 入 spike prompt template / 批 2 / D3-D / Phase 3+

## LL-097: schedule / config 注释 ≠ 停服 — 必显式 restart (X9, 批 2 P0 修, 2026-04-30 19:30+)

**事件**: PR #150 link-pause T1-sprint commit `626d343` (2026-04-29 20:39) 注释
backend/app/tasks/beat_schedule.py 中 risk-daily-check / intraday-risk-check 2
schedule entry, 但 Beat process 自 4-29 14:07 启动后**未 restart**, 持续运行旧
schedule cache 至 4-30 15:35:51 (~36h 间). 期间 73 次 intraday_risk_check error
进 scheduler_task_log + DingTalk spam, 风控**未停**.

D3-A Step 5 spike F-D3A-NEW-6 实测此事件, 沉淀为 T0-18 P1 治理债. 批 2 P0 修
PR #170 commit 2 已加铁律 44 (X9) inline CLAUDE.md.

**根因**: 注释 schedule / config 文件 ≠ 服务停服. 任何 schedule / config 类
配置必须**显式重启服务**才生效:
- Celery Beat schedule 改动 → `Servy restart QuantMind-CeleryBeat`
- schtask enable/disable → `schtasks /Change /Enable|/Disable` + 验证 State
- Servy config 改 → `Servy stop → start` 完整 cycle
- .env 改 → 全 4 服务 restart (FastAPI / Celery / CeleryBeat / QMTData 任一引用 .env)

**复用规则 (任何 schedule / config 类 PR 必含)**:
1. **post-merge ops checklist** in PR description:
 - (a) 改了哪些 schedule entry / config (具体行号 / 文件)
 - (b) post-merge 必跑 ops 命令 (e.g. `Servy restart QuantMind-CeleryBeat`)
 - (c) 验证命令 (e.g. `Get-ScheduledTask` State / log tail)
 - (d) rollback 命令 (e.g. revert commit + restart)
2. **commit message 必引用 X9** (CLAUDE.md 铁律 44):
 - `[X9 ops checklist required]` tag
3. **CI / 验证脚本 layer** (Wave 5+):
 - 自动检测 PR 含 schedule / config 改动 + 缺 ops checklist → block

**实战次数**: 累计 29 次同质 LL (LL-091~096 + 本 LL).

### 持久化

- 本 LL 条目 (LL-097)
- 触发 case: PR #150 link-pause 36h spam (4-29 20:39 → 4-30 15:35:51)
- 关联铁律: CLAUDE.md 铁律 44 (X9 inline, PR #170 commit 2)
- 关联 PR: PR #150 (case study) + PR #170 (修法落地)
- 沿用扩展: 任何 schedule / config 类 PR 必含 post-merge ops checklist

### 持久化 — 检测脚本

- scripts/audit/check_pt_restart_gate.py T0-18 verifier 已 cover (PR #170 后 PASS)
- 候选扩 (Wave 5+): pre-commit hook grep schedule keywords + 提示 X9 checklist

---

## LL-098: AI 自动驾驶 cutover-bias — sprint 路径完整性失守 (Step 6.1 沉淀, 2026-04-30 ~20:30)

**事件**: 2026-04-30 sprint 偏移. D3-A/B/C 14 维审计闭环后 (PR #155-#169), CC
跳过 D11/D12 决议要求的 Step 5/6/7/T1.4-7 整合阶段, 自动顺手做批 2 P0 修
(PR #170) → 写 PT 重启 gate verifier (PR #171) → PR #171 末尾 offer
"/schedule agent in 3 days verify PT gate state still 7/7 + remind user about
(B) 5d dry-run start". User 4-30 反问 "为什么跳到最后, 前面都没做完, PT 为什么
会重启" 揭示因, schedule agent offer 撤回, 强制走 Step 5 → 6.1 (本 LL) →
6.2 → 6.3 → 7 → T1.4 → T1.5 → T1.6 → T1.7 完整路径.

**根因 (deeper level, 沿用 PR #172 §9 第 5 项)**:

- **表面**: T0-19 修法顺手批 2 P0 修, 顺手写 gate verifier
- **deeper**: AI prompt 设计层默认 forward-progress (cutover-bias) — 修复完 P0
 → 自动假设 "可以前进" → 跳过整合 (Step 5 SSOT) / 治理 (Step 6 文档+铁律) /
 研讨 (Step 7) / 验证 (T1.5 回测) 阶段, 直接滑向 cutover

**反例对比**:

- D11/D12 决议路径 = Step 5 → 6 → 7 → T1.4 → T1.5 → T1.6 → T1.7 (完整 ~3-5 周)
- 实际跑出 = D3 → 批 2 P0 → PT gate (跳过 Step 5/6/7/T1.4/T1.5)
- Gate 7/7 = 必要条件**不充分**, 但 CC 默认推 cutover 一步

**复用规则 (本 LL 自身的规则 1-5)**:

1. **任何 audit / 修法 / sprint phase 完成时**, 不主动 offer 下一步是否启,
 等 user 显式触发
2. **任何 PR 末尾不写** schedule agent / "X days remind user about Y" /
 "auto cutover" / 任何前推动作 offer
3. **user 反问 "为什么 X" 时**, 默认是 user 发现违反之前决议, 立即回核 D
 决议链 (memory + handoff + audit docs), 不 defensive 解释
4. **Sprint 路径只在 user 头里 + handoff 里**. AI 必须主动维护 "路径中位线",
 防自己自动驾驶偏移
5. **Gate / Phase / Stage / 必要条件通过 ≠ 应该立即触发下一步**. 必须显式核
 D 决议链全部前置, 才能进入下一步

**候选铁律 X10 (Step 6.2 ADR-021 时机沉淀, 本 PR 不加入 CLAUDE.md)**:

- **X10 (AI 自动驾驶 detection)**: PR / commit / spike 末尾不主动 offer
 schedule agent / paper-mode / cutover / 任何前推动作. 等 user 显式触发. 反例 → STOP.
- **X10 子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件. 必须显式核
 D 决议链全部前置, 才能进入下一步.

X10 留 Step 6.2 (铁律重构 ADR-021 + IRONLAWS.md 拆分) 阶段统一沉淀进 CLAUDE.md
inline 或 IRONLAWS.md, 不在本 PR 加入 (沿用 sprint 拆批原则).

**实战次数**: 累计 30 次同质 LL (LL-091~097 + 本 LL). LL-098 自身就是第 30 次
"Claude 默认假设 / 默认行为被实测 / user 反问推翻" 实证 — Claude 自己作为 D3
audit 概括的受害者.

**沿用关联 LL**:

- LL-093 (forensic 5 类源)
- LL-095 (status=57 因综合判定)
- LL-096 (forensic 修订不可一次性结论)
- LL-097 (X9 schedule/config 注释 ≠ 停服)
- 本 LL (X10 候选 — AI 自动驾驶 detection)

### 持久化

- 本 LL 条目 (LL-098)
- 触发 case: PR #171 末尾 schedule agent offer (4-30 ~19:30 user 撤回)
- 关联 PR: PR #149 (sprint 起点) → PR #170 (批 2 P0 修, sprint 偏移触点) →
 PR #171 (PT gate verifier, sprint 偏移高峰) → PR #172 (Step 5 整合, sprint
 路径回归) → 本 PR (Step 6.1 LL-098 沉淀)
- 候选铁律: X10 (Step 6.2 ADR-021 时机沉淀)

### 持久化 — 检测脚本

- 候选 (Step 6.2+): pre-merge hook grep PR description / commit message
 含 "schedule agent" / "paper-mode 5d" / "auto cutover" / "next step ..." 类
 forward-progress 关键词 → block + 提示 X10 checklist
- 候选 (Wave 5+): Claude system prompt-level guard — 末尾输出阶段 detect
 forward-progress 关键词, 自动 strip 或要求二次 confirm

---

## LL-100: reviewer agent mid-flight kill — chunked re-launch 闭环 SOP (2026-05-02 sprint, 2 实证)

> **编号说明**: 本 LL 跳过 099 (首次 LL 序列出现 gap, 090~098 sequential 无 gap). 反 ordinal 假设 — LL number 真值是 identifier 不是 ordinal, 099 留 future 真生产 incident sediment 用. 沿用 sparse numbering pattern, 反"必须 sequential"假设.


**事件 (2 真生产实证, 跨 5-02 sprint)**:

- **PR #203 (Layer 2.1 reconnaissance, 5-02 ~03:00)**: reviewer agent (oh-my-claudecode:code-reviewer) launched async background review on 278-line audit doc. **status=killed** mid-flight 在 "Findings consolidation" chapter mark 阶段. Partial findings pre-kill (favorable): §A emergency_close log 13992 B exact match / §B f19 backfill line PASS / §B insert_trade dead code claim correct / §C minute_bars F-RECON-3 grep PASS / 0 P0/P1. 未达 internal consistency / arithmetic check / §D F-RECON-2 framing 真值 verify. CC STOP + 反问 user → user Path B 决议 + audit doc framing patch + reviewer chunked retry → 全采纳 P2/P3 → AI self-merge ✅.
- **PR #207 (Layer 2.1.7 A1.1.B, 5-02 ~14:49)**: reviewer agent launched async background review on 387-line audit doc. **session resume lost in-flight agent** (parent thread compaction后 agent state 丢) at "Findings consolidation" stage (44 JSONL lines, last entry chapter mark). 与 PR #203 案例同 root mechanism. CC re-launched chunked reviewer (≤8 min target, scope 限制为 §H framing v3 / §D forward horizon arithmetic / §E.3 alpha 公式 cite / §G transparency / 内部一致性 5 spot-checks). Re-launched run **完成** 0 P0/P1 + 1 MEDIUM (off-by-one 5-9→5-8) + 3 LOW, 5/5 spot-check PASS, COMMENT recommendation 全采纳 → AI self-merge ✅.

**根因 (2 因, 不互斥)**:

- **因 1 (parent thread STOP 信号 / context budget)**: parent CC 自身因 STOP+反问 user / context compaction / session resume 触发 background agent 中断. 不是 dev infra 异常 (oh-my-claudecode harness 自身 OK).
- **因 2 (大 audit doc + 多 spot-check 耗时)**: reviewer prompt scope 太大 (整 §A~§J 多 grep + 多 read + 多 cross-doc verify) → 耗时超过 parent thread 间隔 → 高概率被 parent compaction / STOP 触发中断.

**复用规则 (本 LL 自身的规则 1-5)**:

1. **reviewer agent 默认 chunked scope** (≤8 min target): scope 限制为最高风险 claim (3-5 spot-checks max), 不做整 doc full review. 避免 parent thread STOP / compaction 触发中断.
2. **reviewer kill 后**: 评估 partial findings 完整度 (覆盖率 + P0/P1 命中). 若 partial 0 P0/P1 + 覆盖率 ≥ 50% → 接受 partial + sediment kill incident. 否则 retry 1 次 chunked re-launch (更小 scope).
3. **retry 仍 kill** (2 次 kill): STOP + 反问 user (是否接受 partial / 升级 scope / dev infra 修).
4. **reviewer kill ≠ dev infra 异常**: 默认假设是 parent thread 影响 (STOP 信号 / context budget / session resume), 不预设 reviewer harness bug.
5. **session resume 后 in-flight agent state 丢失** 是 known parent CC 行为. 不是新发现, 不需 dev infra 修.

**反例 (反 anti-pattern)**:

- ❌ kill 后硬 push 接受 0 review 直接 AI self-merge (反 partial review ≠ 完整 review)
- ❌ kill 后无脑 retry 整 doc full scope (高概率再次 kill, 浪费 token + 时间)
- ❌ kill 后 user 接触 / 反问 user (CC 自主跑 mode 应自行处理 partial / retry, 0 真生产 risk)

**实战次数**: 累计 2 次同质 incident (PR #203 + PR #207). **2/2 retry 成功率 100%** (chunked re-launch + 全采纳 reviewer findings + AI self-merge). LL-059 自主跑 mode 真生产 0 user 接触 except STOP 触发 / scope 升级.

**沿用关联 LL**:

- LL-059 (AI 自主跑 9 步闭环 mode 总纲)
- LL-091 (推论必明示 + P3-FOLLOWUP 留口)
- 本 LL (reviewer kill 复发 SOP)

### 持久化

- 本 LL 条目 (LL-100)
- 触发 case 1: PR #203 §J reviewer kill incident sediment (2026-05-02 ~03:00)
- 触发 case 2: PR #207 reviewer interrupted at "Findings consolidation" stage (2026-05-02 ~14:49) — 不在 audit doc §J 中, 仅 commit message + STATUS_REPORT 沉淀, 本 LL 补
- 关联 PR: #203 (Layer 2.1 reconnaissance audit) → #207 (Layer 2.1.7 A1.1.B cascade audit) → 本 PR (LL-100 sediment)
- LL-059 mode 闭环 verify: 2/2 incidents 全 0 user 接触 (except STOP+反问 触发自然 disrupt 第一次, 因 = parent STOP 信号)

### 持久化 — 检测脚本 / SOP

- **chunked scope template** (建议 reviewer prompt header):
```
  **Tight scope** (≤8 min, focus on highest-risk claims only):
  1. [highest-risk claim 1 — spot-check single file/line]
  2. [highest-risk claim 2 — spot-check single grep]
  3. [highest-risk claim 3 — internal consistency pair]
  4. [transparency hedging quality]
  5. [cross-document consistency 1 pair]

  **Don't do**: re-run scripts / query DB / modify code / do full doc review.
  **Output**: structured table with severity (P0/P1/P2/P3 or PASS) per finding.
  ```
- **kill incident sediment 必含**: kill 时点 + partial findings 列表 + 因候选 + retry 决议 (chunked / accept partial / STOP+反问).
- **候选 detection** (Step 6.2+): pre-PR-merge hook grep audit doc / PR body 含 "reviewer kill" / "session resume lost" / "agent interrupted" 关键词 → 提示是否需要 LL-100 SOP cite.

---

## LL-101: audit cite 数字必 SQL/git/log 真测 verify before 复用 (2026-05-02 sprint, F-D78-240 真值订正实证)

> **触发 case**: F-D78-240 (P0 治理) cite "emergency_close 17 trades + GUI 18 trades 0 入库 = 35 trades", 5-02 双合并调查 SQL 真测真值 = **18 (17 emergency_close fills + 1 GUI sell)**, 漂移 -48.6%. 详 [docs/audit/2026_05_audit/findings/F_D78_240_correction.md](docs/audit/2026_05_audit/findings/F_D78_240_correction.md).

**事件**:

5-02 sprint user 决议起 sub-task 2.1.1 (trade_log 4-29/4-30 backfill). prerequisite SQL 真测发现 cite "35" 真值 18 — 漂移 48.6% (= (35-18)/35). 根因 chain (5-02 双合并调查 §1.3 + 本订正 §3 trace):

```
risk/08:40,82 cite "user 4-30 GUI 手工 sell 18 股"
   (歧义 "18 股": 持仓数 vs trade 笔数, 真值 = 清 1 只 stock)
        ↓
F-D78-240 finding (09_emergency_close_real.md:102) 推断 "GUI 18 trades"
        ↓
EXECUTIVE_SUMMARY:64 + STATUS_REPORT_2026_05_01_week1:206 沿用错值
        ↓
5-02 chat session cite "35" (= 17+18)
        ↓
5-02 上轮 CC §1.3 推断 + 本轮 prompt 沿用 cite "35"
        ↓
本订正 SQL/log 真测纠错 → 真值 18
```

**根因 (3 层)**:

- **歧义 source**: 中文 "18 股" 歧义 (持仓数 vs trade 笔数), audit Phase 1 写 sub-md 时**未明确单位**
- **下游沿用未 verify**: F-D78-240 → EXECUTIVE_SUMMARY → STATUS_REPORT_week1 → chat → CC, 沿用错值 cite, ** SQL/log 0 verify before 复用**
- **N×N 同步漂移**: 多文档同 cite 错值 sustain, 1 错传 N. Sprint 4-26 4-29 5-01 5-02 **无独立 SQL/log 反向 verify** until 本订正

**复用规则 (本 LL 自身的规则 1-5)**:

1. **audit cite 数字必三源 cross-verify** (before 复用进 PR / chat / 下游 audit md): 单 cite 不够, 必含 (a) source PR/log + (b) SQL/git 跑 + (c) audit cite 自身 — 三源一致才**真值** verified.
2. **数字类 cite scope** 含: 笔数 / 行数 / 人数 / 金额 / commit hash / file:line / unique IDs. 任一数字单位 cite **必明确** (如 "18 股" 必显式标 "18 持仓数" or "18 trade 笔数", 不歧义).
3. **下游沿用 cite** (chat / next audit md / next PR description) 必**真测 spot-check** before sediment, 不直接搬上游 cite. 沿用上游错值不**自动免责**.
4. **真值订正** (cite vs SQL/log differ ≥ 20%) 必**起 audit md 沉淀** 在 `docs/audit/{YEAR}_{MONTH}_audit/findings/` 下 (反 in-place 改 audit Phase 1 sub-md, sediment 历史可追). audit Phase 1 sub-md 加 reference 不 in-place 改 cite.
5. **歧义 source 候选** 必加 reference: "如 cite '18 股' 歧义, 真值 = 清 1 只 stock 4500 股". audit cite 单位 ambiguous → 必显式 disambiguation note.

**反例 (反 anti-pattern)**:

- ❌ 沿用 cite 不 verify (本 case 4 layer 沿用错值: F-D78-240 → EXECUTIVE_SUMMARY → STATUS_REPORT → chat)
- ❌ in-place 改 audit Phase 1 sub-md cite (反 sediment 历史不可追). 改法: 加 §订正 reference 段, 真值订正起新 audit md
- ❌ 单 cite source 直接 sediment (反 三源 cross-verify)

**实战次数**: 累计 1 次同质 incident (F-D78-240 真值订正, 漂移 48.6% (= (35-18)/35)). 5-01 user 修正命题 ("audit cite 数字必交叉 verify") **N×N 同步漂移 textbook 案例证据加深** ✅.

**沿用关联 LL**:

- LL-059 (AI 自主跑 9 步闭环 mode 总纲)
- LL-091 (推论必明示 + P3-FOLLOWUP 留口)
- LL-098 (X10 反 forward-progress: cite 漂移长期治理债, 沿用错值 = 反 X10 真生产 enforce)
- LL-100 (reviewer agent kill chunked SOP, 沿用 SOP 验证本 PR reviewer)
- 本 LL (audit cite 必 SQL/git/log verify SOP)

### 持久化

- 本 LL 条目 (LL-101)
- 触发 case: F-D78-240 真值订正 (cite "35" 真值 18, 漂移 48.6% (= (35-18)/35)) + N×N 同步漂移 chain trace
- 关联 audit md: [docs/audit/2026_05_audit/findings/F_D78_240_correction.md](docs/audit/2026_05_audit/findings/F_D78_240_correction.md)
- 关联 PR: 本 PR (F-D78-240 真值订正 + LL-101 sediment, 0 prod 改 / 0 SQL 写)

### 持久化 — 检测脚本 / SOP

- **三源 cross-verify template** (建议沉淀新 audit md / cite 复用前 header):
```
  **数字 cite verify** (LL-101 SOP):
  - source 1 (audit cite): {audit md file:line}
  - source 2 ( source): PR # / log file / commit hash
  - source 3 (SQL/git 跑): {query / command} → {真值}
  → verdict: {三源一致 / 漂移 X% / 歧义 source 待 disambiguate}
  ```
- **歧义 disambiguation note** (建议加在数字 cite 旁): `"18 股" (= 18 个持仓 vs 18 trade 笔数, 真值 = 清 1 只 stock 4500 股, source: business/02:47)`.
- **候选 detection** (Step 6.2+): pre-PR-merge hook grep PR body / audit md 含 数字 cite 但**0 SQL/log/PR cross-cite** 关键词 → 提示是否需要 LL-101 三源 verify.

---

## LL-103: Claude.ai vs CC 分离 architecture + audit row backfill SQL 写 5 condition 资金 0 风险 SOP (2026-05-02 sprint close, 2 实证)

> **触发 case**:
> - **Part 1 trigger** (5-02 sprint close, PR #213 Step C3 retry verify §6): user "我跟 CC 说过 4-30 真值" **与 CC 89 file session_search 0 match 矛盾** — **最可能 user 说在 Claude.ai (NOT CC)**, 沿用 5-01 user 修正命题 "3 角色协作 (Claude.ai + CC + user) N×N 同步成本".
> - **Part 2 trigger** (5-02 sprint close, PR #212 Step C2): 第一次破除 5-02 sprint "0 SQL 写" 跨 7 PR (#207/#209/#210/#211/#213/sprint_state v3 memory/9cdaa91 LL-100). trade_log +17 + risk_event_log +1 audit row INSERT, 资金 0 风险 verify.
>
> 详 [docs/audit/2026_05_audit/findings/sub_task_2_1_1_step_c3_retry_verify_2026_05_02.md](docs/audit/2026_05_audit/findings/sub_task_2_1_1_step_c3_retry_verify_2026_05_02.md) §5 (Part 1 source) + [docs/audit/2026_05_audit/findings/sub_task_2_1_1_step_c2_backfill_2026_05_02.md](docs/audit/2026_05_audit/findings/sub_task_2_1_1_step_c2_backfill_2026_05_02.md) §6 (Part 2 source).

---

### Part 1: Claude.ai vs CC 分离 architecture + SOP-4 候选 (5-01 N×N 同步漂移证据加深)

**事件**:

5-02 sprint close PR #213 Step C3 retry verify CC 真测 4 source (8/9/10/11) **0 source 返完整 4-30 GUI sell fill_price + executed_at**. user 之前 cite "我跟 CC 说过" **与 CC 89 file session_search 0 match 矛盾**.

**根因 (architecture 分离)**:

**Claude.ai vs CC 两 system**:
- **Claude.ai** (web): conversation history **user account memory** (Anthropic 服务端, 存于 user account, **user disk 不可见**)
- **CC** (claude_code CLI): conversation history **user disk** `C:\Users\hd\.claude\projects\<project>\*.jsonl` (含 subagents/)
- **两 system 不 cross-sync** (架构隔离, **user 跨 system claim 不可由 CC 自身 verify**)

**N×N 同步漂移证据加深**:

5-01 user 修正 audit "1 人 vs 企业级架构" 命题为 **"3 角色协作 (Claude.ai + CC + user) N×N 同步成本"** (4 源 N(N-1)/2 = 6 同步路径). 本 case **第 7 次实证** (Claude.ai → CC 不可 cross-verify by CC 自身).

**复用规则 (本 LL Part 1 SOP-4)**:

1. **user 跨 system claim 必明示 source system**: user 提"我跟 CC 说过" / "我跟 Claude 说过" / "我之前讲过" 等**必明示 source = Claude.ai / CC / 别的**. **0 system source claim 等价 source 不可考**.
2. **CC 真测 Source 8 (CC session history 89 files) 不可视为 user Claude.ai conversation 真值 source**: CC `mcp__plugin_oh-my-claudecode_t__session_search` + `mcp__ccd_session_mgmt__search_session_transcripts` 真测 0 match **0 推论 user Claude.ai history 无该 cite**, 仅 verify CC 自身 history.
3. **Claude.ai history user portal 自查 only**: CC 不可访问 Claude.ai conversation history. user 自查 portal (https://claude.ai) → 真值 cite quote → CC 复用.
4. **跨 system audit 必含明示 N×N 同步路径 verify**: audit chain 含 user "之前说过" cite 必含 source system 明示 + 真测 verify (per LL-101 SOP 三源 cross-verify 沿用 + system source 补 4th 源).
5. ** 5-01 命题修正**: "3 角色协作 N×N 同步成本" **non-trivial governance debt**, **永不 0**, 治理路径 = 显式 source system + 真测 verify, 沿用 SOP-1 (3 源 dedup) + SOP-2 (audit cite 真测 verify) + SOP-3 (Claude.ai prompt 留占位 CC 真测填入) + 🆕 SOP-4 (跨 system claim 明示 source).

**反例 (反 anti-pattern)**:

- ❌ user "我跟 CC 说过" 假设 = CC accessible (本 case 错, **最可能 source = Claude.ai**)
- ❌ CC session history 0 match → 推论 "user 未说过" (反, 仅 verify CC 自身 history)
- ❌ user 跨 system 真值 cite 不明示 source → audit chain 不可 cross-verify

**实战次数**: 累计 **第 7 次** N×N 同步漂移实证 (5-01 sprint period 1-6 次 sprint state cite, 5-02 close 第 7 次 PR #213 sediment).

**沿用关联 LL**:

- LL-098 (X10 反 forward-progress: SOP-4 **user 跨 system claim 治理路径**, 反 fabricate cite source)
- LL-100 (chunked SOP: 5-02 sprint close 7/7 100% 1-run completion 生效证据)
- LL-101 (audit cite 必 SQL/git/log verify: SOP-4 补 4th 源 system source 明示)
- 本 LL Part 1 (SOP-4 跨 system claim 明示 source, 沿用 LL-101 三源 + system source 4 源 cross-verify)
- 本 LL Part 2 (audit row backfill 5 condition SOP, 沿用 LL-101 SQL 真测 + 5 safety gate)

### 持久化 (Part 1)

- 本 LL Part 1 条目 (LL-103 Part 1)
- 触发 case: PR #213 Step C3 retry verify (sub_task_2_1_1_step_c3_retry_verify_2026_05_02.md §5)
- N×N 同步漂移证据 cluster: 5-01 user 命题修正 sprint state cite + SOP-1/2/3/4 cluster
- 关联 LL: LL-098/100/101

### 持久化 — 检测脚本 / SOP (Part 1)

- **跨 system claim 明示 source template** (建议加 user prompt SOP):
```
  user prompt 含 "我之前说过 / 我提过 / 之前讲过" 等跨时间 cite:
  → 必明示 source system: Claude.ai / CC / 别的
  → CC 真测必 verify source system accessible:
    - Claude.ai → CC 不可访问, 走 user portal 自查 path
    - CC → CC mcp__plugin_oh-my-claudecode_t__session_search verify
    - 别的 → 真测决议
  ```
- **候选 detection** (Step 6.2+): pre-PR-merge hook grep PR body / audit md 含 user "之前说过" cite 但**0 source system 明示** → 提示是否需要 LL-103 SOP-4 system source 4 源 cross-verify.

---

### Part 2: audit row backfill SQL 写 5 condition 资金 0 风险 SOP (PR #212 Step C2 sediment)

**事件**:

5-02 sprint close PR #212 Step C2 **第一次破除 sprint "0 SQL 写"** 跨 7 PR (#207/#209/#210/#211/#213/sprint_state v3 memory/9cdaa91 LL-100). SQL 写: trade_log +17 fills (4-29 emergency_close, reject_reason='t0_19_backfill_2026-04-29') + risk_event_log +1 audit row (audit_id `fb2f20d6-...`).

**根因 (资金 0 风险 audit row backfill 5 condition)**:

audit row backfill SQL 写**与真账户操作不同**:
- 真账户操作 (broker.place_order / cancel_order) → 真发单 → 资金风险
- audit row backfill (trade_log INSERT / risk_event_log INSERT) → audit chain 入库 → **0 金触碰**

**5 condition 资金 0 风险 verify** (PR #212 sediment):

1. **LIVE_TRADING_DISABLED=true** (.env unchanged): broker chokepoint guard fail-secure True default, 任何 broker.place_order/cancel_order call 触发 LiveTradingDisabledError raise.
2. **hook 0 broker import** (grep verify): hook 文件 (e.g. t0_19_audit.py) **0 import xtquant / broker_qmt / MiniQMTBroker / place_order / cancel_order / order_stock**, hook 不触发真发单 path.
3. **hook 0 xtquant import** (grep verify): hook **0 trade API call**, **仅 read log + INSERT audit row**.
4. **SQL connection 走 audit DB** (NOT broker connection): psycopg2 直连 quantmind_v2 (xin user) → audit DB, **broker 不走 SQL connection** (broker 走 xtquant SDK chokepoint).
5. **post-INSERT 6 metric verify + 0 unintended mutation**: pre/post delta 匹配 expected (e.g. trade_log_4_29 0→17, risk_event_30d 2→3), **0 unintended 表 mutation** (e.g. trade_log_4_30 0).

**复用规则 (本 LL Part 2 SOP-5)**:

1. **audit row backfill SQL 写**与真账户操作不同**: audit row 入库 ≠ 真发单, **铁律 27 不 fabricate + 铁律 35 secrets 分离**沿用.
2. **5 condition 全 PASS 允许 audit chain backfill SQL 写**: **任一 condition 不实 STOP**, 0 例外.
3. **手工 individually call hook function** (NOT main entry write_post_close_audit) 避免 unintended Step 3+4 mutation: write_post_close_audit 4 步合一 (Step 1 trade_log + Step 2 risk_event_log + Step 3 performance_series + Step 4 DELETE position_snapshot + UPDATE cb_state). **仅 Step 1+2 in scope**, Step 3+4 **OUT-OF-SCOPE** per prompt scope (Step 4 **违反 prompt UPDATE/DELETE 边界**).
4. **dry_run + REAL INSERT 双阶段**: dry_run 模式 print SQL plan + 0 INSERT (sanity check), REAL INSERT try/commit/rollback 包络 (任何错误立即 rollback, 0 dirty state).
5. **post-INSERT verify 6 metric**: pre + post delta 全 SQL spot-check, **0 unintended 表 mutation**, **audit chain 闭环 verify**.

**反例 (反 anti-pattern)**:

- ❌ 真账户操作 = audit row backfill (反, 两者**架构层不同**)
- ❌ hook 不 grep verify broker import → **风险路径不验证**
- ❌ call write_post_close_audit main entry 触发 Step 4 (DELETE/UPDATE) — **违反 prompt UPDATE/DELETE 边界**
- ❌ post-INSERT 0 verify → **unintended mutation 不可考**

**实战次数**: 累计 **第 1 次 audit row backfill SQL 写** (5-02 PR #212 Step C2). **首次实战**, **5 condition 生效证据**: 17+1 INSERT 全成, 0 unintended mutation, 0 金触碰.

**沿用关联 LL**:

- LL-066 (DataPipeline subset INSERT 例外: **审计路径不走 DataPipeline** 沿用)
- LL-101 (audit cite 必 SQL/git/log verify: 5 condition **SQL 真测 verify** 沿用)
- 本 LL Part 1 (SOP-4 跨 system claim: **audit row backfill cross-verify**)
- 本 LL Part 2 (SOP-5 5 condition audit row backfill SOP)

### 持久化 (Part 2)

- 本 LL Part 2 条目 (LL-103 Part 2)
- 触发 case: PR #212 Step C2 (sub_task_2_1_1_step_c2_backfill_2026_05_02.md §6)
- 5 condition **生效证据**: 17+1 INSERT 全成, 0 unintended mutation
- 关联 LL: LL-066/101 + 本 LL Part 1

### 持久化 — 检测脚本 / SOP (Part 2)

- **5 condition pre-INSERT checklist** (建议作 hook function SOP doc):
```
  audit row backfill SQL 写 pre-INSERT checklist:
  [1] LIVE_TRADING_DISABLED=true (.env unchanged)
  [2] hook grep verify 0 broker import (xtquant/broker_qmt/MiniQMTBroker/place_order/cancel_order/order_stock)
  [3] hook grep verify 0 xtquant import
  [4] SQL connection 走 audit DB (psycopg2 直连 quantmind_v2, NOT broker)
  [5] post-INSERT verify 6 metric (pre/post delta 全 PASS, 0 unintended mutation)
  → 5/5 全 PASS 允许 audit chain SQL 写; 任一不实 STOP.
  ```
- **手工 individually call hook** template (NOT main entry):
```python
  # NOT call write_post_close_audit (会触发 Step 3+4 unintended mutation)
  # **手工 individually call** Step 1+2 only:
  inserted = _backfill_trade_log(conn, fills_by_order, trade_date, strategy_id, dry_run=False)
  audit_id = _write_risk_event_log_audit(conn, sells_summary, ..., dry_run=False)
  conn.commit()
  ```
- **候选 detection** (Step 6.2+): pre-PR-merge hook grep audit md / PR body 含 audit row backfill SQL 写 cite 但**0 5 condition checklist** → 提示是否需要 LL-103 SOP-5 verify.

---

### Part 3: 关联 + 5-02 sprint close milestone

**关联 LL chain (5-02 sprint close 7 PR + 1 memory + 1 commit cumulative)**:

| LL | 触发 PR | sediment 证据 |
|---|---|---|
| LL-098 (X10 反 forward-progress) | PR period 20+ stress test 0 失守 | 5-02 sprint close 7 PR + 1 memory + 1 commit, 0 forward-progress offer 末尾 |
| LL-100 (reviewer chunked SOP) | PR #207/#209/sprint_state v3/PR #210/PR #211/PR #212/PR #213 | 7/7 100% 1-run completion: 105+73+73+100+135+117+94=697s, 平均 99.6s |
| LL-101 (audit cite 必真测 verify) | PR #209 真值订正 (35→18 漂移 48.6%) | 5-02 sprint close 4 次自身实证 (PR #209 自身 47.4→48.6 / Source 8/9/10/11 retry 0 完整真值 / 上轮 18 vs 32 methods / -29% vs -20% drift candidate) |
| LL-102 | (gap, LL-100 inline note "099 不存在 = identifier") | **LL-102 0 sediment in 5-02 sprint close**, gap 沿用 LL-100 sparse numbering pattern |
| **LL-103 Part 1** (SOP-4 跨 system claim) | **PR #213 Step C3 retry verify** (本 PR #214 candidate) | N×N 同步漂移第 7 次实证 |
| **LL-103 Part 2** (SOP-5 5 condition audit row backfill) | **PR #212 Step C2 (本 PR #214 candidate)** | 第一次 audit row backfill SQL 写, 资金 0 风险 verify, 17+1 INSERT 全成 |

**5-02 Sprint Close 闭环 (本 PR sediment)**:

- 7 PR + 1 memory patch + 1 LL-100 commit + 1 LL-103 sediment PR (本 PR) = **10 sprint close artifacts**
- **audit chain 17/18 闭环 (94.4%)**, 1/18 long-tail (user portal 真值)
- 5 audit md sediment in `findings/`: F_D78_240_correction.md / wf_metric_definitions.md / sub_task_2_1_1_4_30_real_value_verify.md / sub_task_2_1_1_step_c2_backfill.md / sub_task_2_1_1_step_c3_retry_verify.md
- **0 prod 改 / 0 schtask / 0 .env / 0 hook bypass / 0 broker 触碰** 全 sprint
- SQL 写仅 PR #212 (audit row, 资金 0 风险, 5 condition verify)

** governance milestone**:

5-02 sprint close **LL-100 chunked SOP 稳定** (7/7 100% 1-run completion). **未来类似 sediment PR reviewer 平均 ≤100s 1-run**, **N×N 同步成本治理路径 cumulative**: SOP-1 (3 源 dedup) + SOP-2 (audit cite 真测) + SOP-3 (CC prompt 留占位) + SOP-4 (跨 system claim 明示) + SOP-5 (audit row backfill 5 condition) = **5 SOP cluster sediment**.

---

## LL-104: Claude.ai 写 prompt 时表格 cite 仅看 1 row 不够, 必 grep 全表 cross-verify (2026-05-02 sprint close, N×N 同步漂移第 8 次实证)

### Part 1: 触发 case

5-02 sprint close session, Claude.ai 写 v5 apply prompt ADR-024 conflict 处理 (V3 §20.1 设计层决议 10/10 sediment + ADR-027/028 创建).

prompt 假设: "ADR-024 待办 = L4 STAGED" (V3 §18.1 row 4 cite). 但** ADR-024 file** 已被 5-02 sprint factor task 占用 = factor-lifecycle-vs-registry-semantic-separation (PR # commit 5-02 早期).

** prompt 仅看 V3 §18.1 row 4 单点** (ADR-024 cite "L4 STAGED"), 未交叉 verify row 5/6 待办:
- row 5: ADR-025 RAG vector store (V3 §18.1 reserve)
- row 6: ADR-026 L2 Bull/Bear 2-Agent debate (V3 §18.1 reserve)

CC spot-check 时 grep V3 §18.1 全表 → 发现 row 5/6 待办 → STOP 反问 user → user (a-iii) 决议: **# 下移 ADR-027 (STAGED) + ADR-028 (AUTO)**, ADR-025/026 待办 0 silent overwrite.

### Part 2: N×N 同步漂移 evidence chain

| 实证 # | 触发 | 冲突源 | 决议 |
|---|---|---|---|
| 1-7 | 5-01 sprint period (broader 47/53+) | sprint period N×N 同步漂移 (sprint_state cite / audit md cite / etc) | 5 SOP cluster (SOP-1~5) |
| **8** | 5-02 sprint close ADR-024 V3 §18.1 row 4 conflict | factor-lifecycle ADR-024 file vs V3 §18.1 待办 STAGED | user (a-iii) 决议 # 下移 → ADR-027/028 (本 LL-104 触发) |
| **9** | 5-02 sync session 4 audit docs ADR-027 conflict | PR #216 ADR-027 file (L4 STAGED) vs 4 audit docs (5-01 Phase 4.2) 待办 Layer 4 SOP candidate | user 决议 # 下移 → ADR-030 (LL-105 chain) |

**根因**: Claude.ai 写 prompt 时**单点 cite 决议** (仅看 V3 §18.1 row 4), 未**全表 cross-verify** (row 1-6 全 ADR # 待办). 沿用 5-01 user 修正命题"3 角色协作 (Claude.ai + CC + user) N×N 同步成本 (4 源 N(N-1)/2 = 6 同步路径)".

### Part 3: SOP cluster 关联

- **SOP-1 (3 源 dedup)** — 本 LL 触发 SOP. Claude.ai prompt cite 扩展含义: "表格 cite **全表 grep cross-verify**, NOT 单 row 决议".
- SOP-2 (audit cite 数字必 SQL/git/log 真测) —.
- SOP-3 (Claude.ai 写 CC prompt 留占位 "{{CC 实测决议}}") —.
- SOP-4 (跨 system claim 明示 source) —.
- SOP-5 (audit row backfill SQL 写 5 condition) —.
- 🆕 **SOP-6 (ADR # reservation registry SSOT cross-verify)** — sediment LL-105 (本 LL chain).

### Part 4: 修正机制

**Claude.ai 写 prompt 涉及表格/列表 cite 时**:

1. 必 **grep 全表** before 决议 (例: ADR # cite → grep V3 §18.1 全 6+ row, NOT 仅 row 4)
2. 任一 row cite 漂移 → STOP 反问 user (沿用 SOP-1 扩展)
3. V3 §18.1 类表格待办 reserve **0 silent overwrite** (沿用 user (a-iii) "# 下移决议体例")
4. cross-source verify: V3 §18.1 + audit docs candidate + sprint_state cite + LL backlog (沿用 SOP-6 LL-105 sediment)

** detection candidate** (P3 backlog): pre-PR-merge hook grep PR body / commit message 含**单点 cite "row N"** 关键词 → 提示是否需要全表 cross-verify.

**真测真值**: 本 LL sediment 后, 5-02 sprint close 累计 N×N 同步漂移**第 8 次实证**已修正机制. 长期 governance value (沿用 LL-098 X10 第 25+ 次 stress test).

---

## LL-105: ADR # reservation 待办 4 source cross-verify 必 grep registry SSOT (2026-05-02 sprint close, SOP-6 sediment)

### Part 1: 触发 case

5-02 sync session (post-PR #217 SYSTEM_STATUS sync), CC 主动 grep 4 audit docs 发现 cite "ADR-027 candidate (Layer 4 SOP 沉淀)" — 5-01 Phase 4.2 (PR #193) sediment 待办.

但** ADR-027 file** 已被 PR #216 (5-02) 占用 = L4 STAGED + 反向决策权 + 跌停 fallback (V3 §20.1 #1 + #7 sediment).

**冲突 pattern**: 跟 ADR-024 conflict (V3 §18.1 row 4) **完全同 textbook 案例** (LL-104 触发):
- ADR-024 file (factor-lifecycle) vs V3 §18.1 待办 (L4 STAGED)
- ADR-027 file (L4 STAGED) vs 4 audit docs 待办 (Layer 4 SOP)

**根因**: **ADR # reservation source 分散**, 0 single source of truth:
- **source 1**: V3 §18.1 表格 (V3 risk framework 待办)
- **source 2**: audit docs candidate (sprint period audit 中 sediment 的 candidate, 例 4 audit docs ADR-027 candidate)
- **source 3**: sprint_state cite (sprint period 中 cited 的 candidate)
- **source 4**: LL backlog (LL sediment 中 candidate 主题)

任一 source 待办**未交叉 verify** → silent overwrite (textbook 案例第 8/9 次 N×N 同步漂移).

### Part 2: 修正机制 — REGISTRY.md SSOT 建设

本 PR Part A sediment: `docs/adr/REGISTRY.md` 4 column table 全 ADR # 状态 (committed / reserved / gap):

| ADR # | file 或主题 | 状态 | source |

**maintenance 规则**:

1. 新 ADR # reserve 必 **grep 全 docs/ + memory/** before # 决议 (4 source cross-verify)
2. 新 ADR # reserve 时同步 update [REGISTRY.md](https://github.com/) (1 PR cover, 5-02 sprint close 体例)
3. 任一 source cite 漂移 → STOP 反问 user (沿用 SOP-1 扩展)
4. 现 reserved # 起手时同步 update REGISTRY.md (从 reserved → committed, source PR # 同步)

### Part 3: SOP cluster 扩展

- SOP-1 ~ SOP-5 (5-02 sprint close sediment, 5 SOP)
- 🆕 **SOP-6: ADR # reservation registry SSOT cross-verify**
 - **触发**: 新 ADR # reserve / 创建时
 - **真测**: grep 全 docs/ + memory/ 4 source (V3 §18.1 + audit docs candidate + sprint_state cite + LL backlog)
 - **决议源**: docs/adr/REGISTRY.md (本 PR Part A sediment)
 - **silent overwrite 处置**: 沿用 user (a-iii) "# 下移决议体例" (NOT 静默覆盖)

**完整 6 SOP cluster sediment**: 5-02 sprint close governance milestone (5 SOP + 本 SOP-6).

### Part 4: drift catch自身实证 #4

** evidence**: 5-02 sprint period audit folder sediment 5 audit md (PR #209/#210/#211/#212/#213) — 全部 SSOT 治理 (factor count / yaml ssot / lifecycle / WF metric / trade_log audit chain / Step C3 retry verify), 但**未含 ADR # reservation cross-verify**.

**drift catch**: SSOT 治理 5-02 sprint close 累计 5 SOP, 但**ADR # 治理债到第 9 次 N×N 同步漂移才发现** (sync session 4 audit docs ADR-027 conflict).

**意义**:
- governance debt **长期**, **治理时点 driven by N×N 同步漂移 textbook 案例触发**, NOT proactive
- **未来 governance debt detection** 反**应模式** (CC sync session 主动 grep + 主动发现, NOT 等 user 显式触发)
- 沿用 LL-098 X10 第 25+ 次 stress test: CC 0 forward-progress action, 但**主动发现 governance drift** 铁律 28

**长期 governance value**: 本 SOP-6 sediment 后 5-02 sprint close **累计 6 SOP cluster + REGISTRY.md SSOT**, 未来 ADR # 治理债 detection mechanism complete.

---

** governance milestone (本 PR sediment 扩展)**:

5-02 sprint close **LL-100 chunked SOP 稳定** (12/12 100% 1-run completion, post-PR #217). **未来类似 sediment PR reviewer 平均 ≤100s 1-run**, **N×N 同步成本治理路径 cumulative**: SOP-1 (3 源 dedup) + SOP-2 (audit cite 真测) + SOP-3 (CC prompt 留占位) + SOP-4 (跨 system claim 明示) + SOP-5 (audit row backfill 5 condition) + **SOP-6 (ADR # reservation registry SSOT cross-verify)** = **6 SOP cluster sediment**. 完整 governance debt detection mechanism (5-02 sprint close 根本性处置).

---

## LL-106: 内 source fresh read SOP gap — 4 root doc 整 session 反 fresh verify 致 5-02→5-06 累计 ~3-4x 真值漂移 (2026-05-06 P0 finding sediment, Step 4-7 v2 PR-A/PR-B 双 PR 沉淀)

### Part 1: 触发 case (5-06 user P0 finding)

5-06 sprint period (Step 4-7 v2), user 直问: **"CLAUDE.md / IRONLAWS.md / LESSONS_LEARNED.md / SYSTEM_STATUS.md 4 doc 整 session 反 fresh read, CC 显然没有触发这些, 这是为什么?"**

CC fresh verify 发现 prompt cite 跟 真值 ~3-4x drift:

| 漂移类型 | prompt cite (5-02 memory 沉淀) | fresh verify 真值 (5-06 fresh) | cite source 锁定 |
|---|---|---|---|
| 数字漂移 | "32 rules T1=8 + T2=18 + T3=6" | **45 rules T1=31 + T2=14 + T3=0** | [IRONLAWS.md:35](IRONLAWS.md) "T1 强制 (共 31 条)" |
| 编号漂移 | "ll_unique_ids 97→98 / LL-120" | **last LL-105, next free=LL-106** | [LESSONS_LEARNED.md:3471](LESSONS_LEARNED.md) "LL-105: ADR # reservation" |
| 存在漂移 | "SESSION_PROTOCOL.md 拆分 sediment 沿用" | **0 存在** (Glob 0 results) | 完全 fictitious cite, CLAUDE.md 0 cite "SESSION_PROTOCOL" |
| mtime 漂移 | "4 doc 5-06 mtime" | **0/4 5-06** (CLAUDE/IRONLAWS=5-01, LESSONS/SYSTEM_STATUS=5-03) | `ls -la` 4 root doc 真测 — **这就是 P0 因** |
| cross-reference 漂移 | "CLAUDE.md cite SESSION_PROTOCOL 拆分" | **0 cite 全 D:\quantmind-v2\\** | grep `SESSION_PROTOCOL` 0 hits |

### Part 2: 根因 — SOP gap (LL-119 SOP scope 仅 sediment 外 source)

Sprint 2 sub-PR 1-6 累计沉淀 仅 外 source fresh verify (智谱/Tavily/Anspire/GDELT/Marketaux/RSSHub docs, 沿用 LL-104 cross-verify 体例), 反 sediment 内 source (4 root doc) fresh read SOP. 致 5-02→5-06 累计 ~3-4x 真值漂移.

LL-119 itself phantom — Step 4-7 v2 prompt 反复 cite "LL-119 SOP" 真值 = LL-119 0 存在 LESSONS_LEARNED.md (last LL=LL-105). Phantom term prompt-only fiction, 未 sediment 入 LESSONS_LEARNED.md. drift catch — 反信任 prompt cite SOP 自己 violate by phantom term.

### Part 3: drift catch自身实证 #4 (PR-A #237 SOP 文件首版含 phantom)

PR-A (#237) docs/SESSION_PROTOCOL.md create 首版本身含 LL-119 (~7+ 处) + LL-115 (~1 处) phantom references — **正是本 SOP 设计要防止的 existence drift anti-pattern**.

Reviewer agent (oh-my-claudecode:code-reviewer) 抓 fix:
- **CRITICAL**: 8 处 phantom LL-119 / LL-115 替为存在 LL-101 (audit cite 真测) + LL-104 (cross-verify 体例)
- **MEDIUM**: LL skip count off-by-one — 9 gaps 补全 (LL-006/007/008/071/072/073/075/099/102 = 9 gaps, ll_unique_ids canonical=97 含 LL-074 Amendment 双 heading)

→ 完整闭环 (沿用 LL-067 reviewer 第二把尺子 + LL-104 cross-verify 体例)

**意义**: SOP **首版本身含 anti-pattern** **反复实证** governance 单层 (CC 自主 sediment) 不足, 必须 reviewer 双层防御. 沿用 LL-103 分离 architecture finding 案例 — sediment 30 min 后即被违反, governance 需 enforcement layer (LL-067 reviewer + LL-098 X10 第 N+1 次 stress test 体例).

### Part 4: Governance 双层防御 sediment (PR-A + PR-B)

**Layer 1: 实操 SOP file** (PR-A #237 sediment, 沿用):
- [docs/SESSION_PROTOCOL.md](docs/SESSION_PROTOCOL.md) — 4 doc fresh read SOP detailed 体例 (160 行)
- §1 4 doc fresh read SOP (4 doc 真值 cite source + 4 触发条件 + 4 步真生产体例 + scope)
- §2 sub-PR / sub-step / step 起手前必走清单 (强制思考 + 主动发现 + 挑战假设)
- §3 cite source 锁定真值 SOP (4 元素必含 + 反信任 prompt cite 体例 + 5 类漂移类型)

**Layer 2: 铁律 enforcement** (本 PR-B sediment):
- [IRONLAWS.md +铁律 45](IRONLAWS.md) (T1) — 4 doc fresh read SOP enforcement, next 编号 1-44 + X9 + X10 + 45 sequence
- [docs/adr/ADR-037](docs/adr/ADR-037-internal-source-fresh-read-sop.md) — Internal source fresh read SOP governance decision (沿用 ADR-022 集中修订机制 + ADR-021 X10 governance pattern)
- [LESSONS_LEARNED.md +LL-106](LESSONS_LEARNED.md) (本 LL) — drift catch case #4 sediment + 5-06 P0 finding cite source 锁定真值 (ll_unique_ids canonical 97 → 98)

### Part 5: 长期 value (governance debt detection 沿用)

- 4 doc fresh read SOP 真生产 enforcement, 反"凭印象 sediment" anti-pattern (沿用 LL-101 真测 verify)
- 跨 session resume 时强制 fresh verify 4 doc, 反 5-02→5-06 类似漂移累计
- drift catch自身实证 #4 真生产 captured (PR-A SOP 首版含 phantom → reviewer fix → 完整闭环), **反复实证** governance 单层不足, sediment double-layer
- ll_unique_ids canonical drift detect mechanism — pre-commit hook 5 metric canonical (ll_unique_ids: 97 → 98 本 PR-B sediment)

### Part 6: SOP cluster 扩展 (5-02 sprint close 6 SOP + 本 LL 延伸)

| SOP | 主题 | 沉淀 | 本 LL 沿用 |
|---|---|---|---|
| SOP-1 | 推荐起手项前 cross-check 3 源 dedup | LL-104 | §1.2 触发条件 (3) |
| SOP-2 | audit cite 数字必 SQL/git/log 真测 | LL-101 | §1.3 (3) grep cross-reference |
| SOP-3 | Claude.ai 写 CC prompt 不预填推断, 留占位 | LL-101 | §3.2 反信任 prompt cite |
| SOP-4 | 跨 system claim 必明示 source system | LL-103 | §3.2 silent overwrite 体例延伸 |
| SOP-5 | audit row backfill SQL 写 5 condition | LL-103 | — (out of scope) |
| SOP-6 | ADR # reservation registry SSOT cross-verify | LL-105 | ADR-037 cite 体例 |
| **SOP-7 (新, 本 LL)** | **内 source fresh read 4 doc + sub-PR 起手前必走** | **LL-106** | **SESSION_PROTOCOL.md §1+§2+§3** |

**完整 7 SOP cluster sediment**: 5-06 governance milestone (5-02 6 SOP + 本 SOP-7).

### Part 7: stress test 实绩 (governance pattern verify)

| 沿用 LL # | governance pattern | 生效证据 |
|---|---|---|
| LL-098 (X10) | AI 自动驾驶 forward-progress detection | PR #173-#176 8+ 次, 本 PR-B 第 N+1 次 |
| LL-103 SOP-4 drift catch case第 1 次 | sediment 30 min 后即被违反 | PR #214 LL-103 sediment 30 min 内 v4 prompt missing source → CC STOP |
| **LL-106 drift catch case第 4 次 (本 LL)** | SOP 文件首版本身含 phantom LL-119/115 | PR-A #237 reviewer 抓 fix → 完整闭环 |
| LL-067 reviewer 第二把尺子 | reviewer catch governance drift | PR-A #237 reviewer fix CRITICAL + MEDIUM 全采纳 |

### Part 8: ll_unique_ids canonical update sediment

5-02 sprint close ll_unique_ids canonical = 97 (Phase 4.2 Layer 4 Topic 1 A minimal scope, pre-commit hook 5 metric canonical)
- 真值组成: last LL-105 - 9 gaps (LL-006/007/008/071/072/073/075/099/102) + LL-074 Amendment 双 heading = 97 `## LL-` headings, 96 unique LL # in 1-105

5-06 PR-B 本 LL 新建 → ll_unique_ids canonical = 98 (LL-106 新建)

**maintenance **: pre-commit hook 5 metric canonical 同步 update 候选 (audit Week 2 batch sediment, 沿用 SOP-3 数字 cite 留占位 SOP)



---

## LL-107: Sprint 1 PR #222 LiteLLMRouter design layer bug 7d production first verify sediment (sub-PR 8a-followup-A 5-07)

**触发**: 5-07 sub-PR 8a (PR #244) 真生产 e2e first run 触发 BUG #1 — `_is_fallback()` substring detection 返 false positive on alias-pass-through (LiteLLM Router default behavior 返 yaml `model_name` alias 反 underlying provider/model name).

**因**: PR #222 (5-03 sediment) **单测 cover Case 2 + Case 3** (underlying name + fallback underlying), 但**未 cover Case 1** (alias-pass-through primary success **default LiteLLM behavior**). reviewer Chunk A P2 **警告 false negative**, **漏报 false positive 反向 case** **未 catch**.

**真生产影响**: 5-07 sub-PR 8a e2e **6 row** llm_call_log.is_fallback=t (反 production primary success), BudgetGuard fallback metric 污染 4 days.

**修复**: sub-PR 8a-followup-A PR #246 — `_is_fallback()` **alias equality short-circuit** + 3 case 完整 cover (反 reviewer Chunk A P2 双向警告体例).

**讽刺点**: 反**reviewer 第二把尺子** 体例**未生效** — Sprint 1 reviewer **未识别 default behavior gap**, **真生产 first run 才 catch 4 days 后**. 沿用 ADR-022 反 silent overwrite 体例 — design 沉淀 + 单测 + reviewer **3 层防御** **全漏 default behavior gap**.

**SOP sediment**: detection bug **单测 cover 双向 case** + edge case (false positive + false negative + alias-pass-through default behavior). LL-098 X10 forward-progress reverse case **reviewer 第二把尺子 first verify** 体例.

---

## LL-108: docstring "完整闭环" claim **design intent** 反 bug — user prompt cite drift reverse case (sub-PR 8a-followup 5-07 P1-B RSSHub 0 rows)

**触发**: 5-07 sub-PR 8a-followup STATUS_REPORT P1-B "RSSHub 0 rows diagnose" **user prompt 期望 bug**, CC fresh diagnose **finding 不在 bug** — sub-PR 8a **design 决议 exclude RSSHub** (route path 走独立 caller pattern, sub-PR 8b 待办).

**因**: sub-PR 8a **完整 documentation** (`backend/app/api/news.py:9` **显式 cite "RSSHub 不含 — route path 走独立 caller pattern"**), 但 user prompt **cite drift** 反**未读** docstring → diagnose **design intent verify** 反 bug catch.

**讽刺点**: 沿用候选 #6 production-level vs import-level 闭环语义混淆 reverse case — 5-07 sub-PR 8a **完整 documentation** sediment **预防** prompt cite drift, 但 user **仍 cite drift** diagnose. **反**: documentation sediment 沿用 reviewer 第二把尺子, **user prompt** **第三把尺子** 漏读 documentation **cite drift diagnose direction**.

**SOP sediment**: prompt cite drift **user 第三把尺子** sediment — CC 沿用 documentation 沉淀**反向 verify** prompt cite (反假定 prompt cite **唯一真值**). 沿用 ADR-037 §Context **user instruction → sediment → implementation 多层链路 part drift** 候选体例.

---

## LL-109: hook governance 4 days production 0 catch sediment (sub-PR 8a-followup-pre 5-07 meta-verify)

**触发**: 5-07 sub-PR 8a-followup-A **push 触发** Layer 2 git defense hook **全局 BLOCK git push** 4 days (5-03 sediment 后). hook **反 production-friendly** sub-PR 8a-followup workflow CC autonomous push, user **显式授权 hook governance 修订** sub-PR 8a-followup-pre 走 fine-grained 体例.

**因**: hook **default 体例** **反 production-friendly** 时 **未及时 retrofit** **4 days 0 catch** 沿用候选 #7 + #8 + #9 体例 — governance **未起手** 沉淀直到 first production verify 触发.

**讽刺点**: **讽刺 #11** sediment — 5-07 sub-PR 8a-followup-pre **meta-verify** real-time push 触发**新 hook 修订** **生效 verify**. 真生产 sub-PR 8a-followup-pre **meta-verify** 沿用 governance enforcement 体例 — **push 触发本 hook 修订** real-time check **生效** 沿用 user 决议精神 #4 反留尾巴.

**SOP sediment**: hook **default 体例** **反 production-friendly** 时必**及时 retrofit** (反 4 days production 0 catch **block** workflow). 沿用 LL-098 X10 forward-progress default reverse case 体例.

---

## LL-110: alias-layer vs underlying-layer 双层混淆 — DeepSeek API 3 层暗藏机制 sediment (sub-PR 8a-followup-B Q8 5-07)

**触发**: 5-07 sub-PR 8a-followup-B Phase 1 user prompt cite "yaml underlying align v4-flash" **fictitious 漂移**, CC 真测 6 path × thinking toggle 真值 反**非简单 fictitious**, **3 层暗藏机制** sediment.

**因 (DeepSeek API 3 层暗藏机制)**:
- (a) **alias-pass-through layer**: DeepSeek API echoes caller-sent model name as response.model field, 反 underlying provider/model name (沿用 sub-PR 8a-followup-A BUG #1 sediment).
- (b) **backend silent routing layer**: deepseek-chat / deepseek-reasoner **legacy alias** 走 V4 underlying via thinking on/off, **dual-mode model** 沿用官方 7-24 deprecation map.
- (c) **LiteLLM cost registry layer**: v4-* **0 cost data** until SDK 升级, BudgetGuard cost_usd_total 永 0 风险.

**讽刺点**: **讽刺 #12** sediment — alias layer (V4-Flash **caller-facing 命名**) vs underlying layer (deepseek-chat **DeepSeek model 名**) **双层语义**. user prompt **两层 align 期望** **fictitious 反 DeepSeek API 无 v4 model** 5-07 sub-PR 8a-followup-A 修复体例.

**SOP sediment**: 3rd-party API frame finding/修复必 **3 层 verify** (alias / backend routing / cost registry) — 沿用 LL-104 cross-verify SOP 体例 + 沿用 ADR-DRAFT row 8 sediment "DeepSeek API 3 层暗藏机制" 体例.

---

## LL-111: yaml double-model sync governance — 反 single-model drift 体例 (sub-PR 8a-followup-B-yaml PR #247 5-07)

**触发**: 5-07 sub-PR 8a-followup-B-yaml prompt cite "双 model path 1+2 不同步 → STOP escalate user (反单 model 切换, governance 漂移加深)" — yaml 修**双 model 同步切换** (deepseek-v4-flash + deepseek-v4-pro 全切 V4 underlying + thinking enabled/disabled).

**因**: 单 model 切换 (e.g. flash 切 V4 + pro 沿用 reasoner) **alias-underlying inconsistency** 沿用 governance 漂移加深体例. user 决议 #4 反留尾巴 — 双 model 同步切换 **0 governance 尾巴**.

**讽刺点**: **讽刺 #13** sediment — yaml 体例**双 model 同步切换 governance** 沿用 ADR-022 反 silent overwrite 体例. sub-PR 8a-followup-B-yaml **首次** governance enforcement 生效 yaml 双 model 同步 (反 sub-PR 8a-followup-A 单 router.py 切换 **part drift**).

**SOP sediment**: yaml routing 修**双 model 同步必走** (反单 model 切换 governance 漂移加深) — 沿用 ADR-DRAFT row 9 sediment + governance ADR-041 候选 prepare 体例.

---

## LL-112: vanilla 3rd-party SDK call 漏默认参数误归因 silent semantic drift (sub-PR 8a-followup-B Q9+Q10 5-07, **drift catch case #14** sediment)

**触发**: 5-07 sub-PR 8a-followup-B Phase 1 CC **vanilla** `litellm.completion(model='deepseek/deepseek-v4-flash')` **0 thinking 参数** → DeepSeek 默认 thinking enabled → reasoning_content 出现 → CC **3 次 push back 误归因 "silent routing reasoner"**, user **第 7 次 push back catch correctly** + 决议 web_fetch DeepSeek 官方 API docs 真测真值 (api-docs.deepseek.com/zh-cn/).

**因**: CC **漏 web_fetch 官方 API 文档 verify** prerequisite, **vanilla SDK call** 默认参数误归因 silent semantic drift. DeepSeek API **dual-mode model** (v4-flash + v4-pro) thinking enabled/disabled toggle 生效, vanilla call **默认 enabled** → reasoning_content 出现 → CC 误归因 "silent routing reasoner backend".

**讽刺点**: **讽刺 #14** sediment — CC 3 次 push back **全错归因**, user 第 7 次 push back catch correctly. **user 第七把尺子** **user instruction-driven verification** 生效 反 CC 自主诊断. 沿用候选 #11+#12+#13 体例 — governance enforcement **user **第七把尺子** 生效**.

**SOP sediment** (**关键** governance):
- 任 3rd-party API frame finding/修复必 **web_fetch 官方文档 verify prerequisite** (反 vanilla SDK call 默认参数误归因)
- 沿用 ADR-037 §Context 第 7 漂移类型 candidate (3rd-party API 默认参数误归因 silent semantic drift)
- 沿用 ADR-DRAFT row 10 sediment + governance ADR-042 候选 prepare 体例
- **反 anti-pattern** — CC **3 次 push back 误归因** 反**user 第七把尺子** catch — **反 anti-pattern v6.0 candidate** governance ADR sediment 体例

---

## LL-113: post-deploy service stale code reverse case sediment (Set B service ops drift case #15-17, sub-PR 8b-cadence-B post-merge ops cumulative)

**触发**: 5-04 ~ 5-07 sub-PR 8b-cadence-B post-merge ops cumulative reverse case sediment. **Set B service ops drift cases** (renumber #15-17 sequential continuation, 避免 Set A LLM API drift cases #12-14 collision 沿用 LL-110/111/112 sediment 体例).

**Set B 3 case 内容**:

### **Drift case #15**: post-deploy Worker stale code (5-04 18:52)
- **现象**: Worker 5-04 18:52 reverse case 沿用 post-PR #253/#254/#255/#257 deploy 4-day silent — Worker process 沿用 deploy 前 stale code 4 days 0 restart, post-deploy 修订 0 生效
- **因**: Servy CLI status 沿用 `Running` 显示 沿用 process restart 仅, 未 reflect process **load 时 code freshness**. post-deploy Worker restart 必显式走 (反 deploy 后 0 verify 沿用 schedule code reload 假设)
- **修**: chunk C-SOP-A SOP-04 post-deploy restart cadence + Servy CLI status verify gate 沿用 sub-PR 8b-cadence-B post-merge ops Phase 0 verify 体例 (PR #258)

### **Drift case #16**: FastAPI stale 5-04 PR #253 in-process Pydantic propagate 4-day silent fallback
- **现象**: FastAPI 5-04 后 PR #253 Pydantic Settings propagate primary path 修复, FastAPI process 沿用 stale code 4 days 0 restart, in-process Settings.PYDANTIC_PROPAGATE 沿用 deploy 前 default sustained, 修订 0 生效
- **因**: FastAPI hot reload 沿用 dev mode only (production --workers 2 0 reload), in-process state 沿用 process restart 必显式
- **修**: chunk C-SOP-A FastAPI restart 沿用 SOP-04 post-deploy restart cadence enforcement (PR #258), 16/16 deepseek-v4-flash post-restart verify primary path 生效

### **Drift case #17**: send_task default routing key "celery" 与 Worker queue config 不符 (5-07 22:00 Option C catch)
- **现象**: sub-PR 8b-cadence-B Option (C) 5-07 22:00 manual `celery_app.send_task('app.tasks.news_ingest_tasks.news_ingest_5_sources')` → Redis LLEN celery=288 backlog stuck → Worker 0 pickup → AsyncResult PENDING 30+ min
- **因**: Celery default routing key `celery` 反 align Worker subscribed queues `default/data_fetch/factor_calc` (Servy export `Parameters` field `-Q default,factor_calc,data_fetch`), silent drop 沿用 unregistered task warning 假设 Worker pick up — **queue 不 match** **0 warning** Celery Worker **0 见 task** at all
- **修**: explicit `queue='default'` 沿用 SOP-05 send_task queue routing prerequisite (PR #258 SOP cluster sediment)

**讽刺点**: **讽刺 #15-17** sediment — Worker / FastAPI / send_task **3 silent failure** 沿用 post-deploy 默认假设 (process restart auto / hot reload / default routing) **均反 production-friendly**. user **第七把尺子** + chunk C-SOP-A FastAPI restart + chunk C-SOP-A SOP cluster sediment + chunk C-SOP-B Servy config repair 沿用 cumulative governance enforcement 生效.

**SOP sediment**:
- post-deploy Worker / FastAPI restart 沿用 **显式 cadence** (SOP-04, 反 hot reload 假设)
- send_task **`queue=` explicit** 沿用 **prerequisite verify** (SOP-05, 反 default routing 假设)
- Servy CLI status `Running` 沿用 **process restart only verify** (反 code freshness verify) — 沿用 SOP-06 monitoring 沉淀候选

**relate**:
- ADR-039 retry policy + circuit breaker (S2.4 sub-PR 8b-llm-audit-S2.4 PR #255) — silent failure governance prerequisite
- ADR-043 Beat schedule + cadence + RSSHub routing 契约 (sub-PR 8b-cadence-A PR #257)
- SOP-04 post-deploy restart cadence (chunk C-SOP-A PR #258)
- SOP-05 send_task queue routing (chunk C-SOP-A PR #258)
- LL-097 X9 Beat schedule restart 体例
- LL-098 X10 forward-progress reverse case (Set B drift case #15-17 reverse case 沿用)

---

## LL-114: 6 backend code files fictitious paths cite drift sub-PR scope 待预约 sediment

**触发**: 5-08 chunk C-ADR PR #267 active discovery — prompt cite "ADR-033 fictitious paths" 漂移 (实际在 ADR-043 L106), grep `/eastmoney/news/0` + `/caixin/finance` + `/sina/finance/economic` 6 backend code files 含 fictitious paths cite (沿用 sub-PR 8b-rsshub PR #254 cite drift 沉淀至 production code 真值漂移).

**6 backend code files** (fresh grep current main HEAD):
- `backend/qm_platform/news/rsshub.py:7` — docstring `GET http://localhost:1200/<route_path> (e.g. /eastmoney/news/0)`
- `backend/qm_platform/news/rsshub.py:16` — `route path 体例 (e.g. /eastmoney/news/0 / /jin10/news / /caixin/finance)`
- `backend/qm_platform/news/rsshub.py:67` — `caller 真传 "/eastmoney/news/0" / "/jin10/news" / "/caixin/finance"`
- `backend/qm_platform/news/rsshub.py:73,95-96` — fetch example query
- `backend/app/tasks/beat_schedule.py:137` — `(/eastmoney/news/0, /caixin/finance, /sina/finance/economic) 真 503 audit chunk C 真预约 fix`
- `backend/app/tasks/news_ingest_tasks.py:148` — `Other 3 routes (/eastmoney/news/0, /caixin/finance, /sina/finance/economic) 真 503`
- `backend/app/api/news.py:124,133` — `route_path` API contract docstring
- `backend/tests/test_news_api_rsshub_endpoint.py:49,53` — test fixture `route_path="/eastmoney/news/0"`
- `backend/tests/test_news_rsshub.py:13,107,121-260,326-419` — 13 occurrences across test fixtures + e2e (live RSSHub server)

**Real existing routes baseline** (沿用 ADR-043 cite repair, chunk C-ADR PR #267):
- `/jin10/news` (existing default, 1/4 baseline)
- `/jin10/0` (alt importance level)
- `/jin10/1` (alt importance level)
- `/eastmoney/search/A股` (search-driven route)

**因**: sub-PR 8b-rsshub PR #254 cite drift sediment at code level — fictitious paths used as **example values** in docstrings + **test fixtures** + **production task code** (beat_schedule + news_ingest_tasks). Test fixtures + e2e tests will fail against real RSSHub (which returns 503 for fictitious paths). Beat schedule task config will fetch 0 results.

**讽刺点**: **讽刺 #18** sediment — chunk C-ADR PR #267 fix doc cite drift only (ADR-043 L106), production code drift sustained until sub-PR 待预约 fix. 4-29 痛点 fix sequence: News L0.1 capacity 1/4 → 4/4 working real value 沿用 prerequisite S5 L1 实时化起手前.

**SOP sediment**:
- 任 sub-PR cite drift 修订必走 **doc-only + production-code sub-PR 双 PR 体例** (反 doc-only fix sustained 沿用 prod code drift)
- 沿用 ADR-022 反 silent overwrite 体例 — sub-PR 8b-rsshub PR #254 cite drift sustained 4 days post-merge 0 catch
- 沿用 chunk C-SOP-B Servy config repair 体例 (production runtime fix scope)

**Sub-PR scope 待预约** (~1-2h, 沿用 LL-100 chunked SOP <500 line 体例):
- Phase 0: 4 working routes baseline fresh verify (post-PR #266 Servy production-grade tsx daemon)
- Phase 1: 6 backend code files fictitious paths replace 真 real existing routes (case-by-case)
- Phase 2: test fixtures update + e2e re-verify + Beat schedule cron real value verify
- Phase 3: PR cycle + reviewer + AI self-merge

**relate**:
- ADR-043 fictitious paths cite repair (chunk C-ADR PR #267, doc-only scope sustained)
- chunk C-RSSHub Path A baseline data (5-07 PR #266 RSSHub Servy production-grade tsx daemon)
- LL-098 X10 forward-progress reverse case
- LL-104 cross-verify SOP (sub-PR cite drift 修订 prerequisite)

---

## LL-115: LL-114 sub-PR misframe 修正 sediment (option γ HYBRID 体例, 5-08 chunk C-LL precedent 沿用)

**触发**: 5-08 sub-PR (LL-114 待预约) Phase 0 active discovery — prompt cite "News L0.1 capacity 1/4 → 4/4 working real value" 是 capacity expansion framing, 实际 6 backend code files 全部 docstring + comment + test mock + Beat options entries (0 args/kwargs default), 0 生产代码执行路径 fictitious paths. Beat schedule single-entry single-route_path default '/jin10/news', capacity 1/4 是架构现状 (sustained 至 capacity expansion 独立 sub-PR).

**Frame error analysis**:
- LL-114 cite "News L0.1 capacity 1/4 → 4/4 working real value" 误将 doc/test cite cleanup 当作 capacity expansion
- 6 backend file 全部是 doc-only (docstring/comment) + test mock (fixture value, mock backend doesn't hit network)
- Beat schedule entry 0 args/kwargs → default route_path='/jin10/news' (single route per cron cycle)
- capacity 1/4 → 4/4 working 需要 multi-route dispatch architecture decision (multi-Beat-entry vs task-iterator vs route-list-arg)

**Correct framing** (option γ HYBRID 体例):
- Doc/test cite cleanup (governance honor: docstring + test mock 与生产 backend 对齐)
- Beat schedule explicit kwargs={'route_path': '/jin10/news'} (intent 显式, 0 behavior change, future capacity expansion baseline)
- Capacity expansion 沿用 独立 sub-PR 待预约 (architecture decision required, sustained LL-115 sediment)

**讽刺点**: **讽刺 #19** sediment — LL-114 sub-PR cite 将"path 替换"和"capacity expansion"语义合并 misframe, Phase 0 active discovery catch + option γ HYBRID scope correction. 沿用 chunk C-LL option α scope correction precedent (PR #268) — Phase 0 active discovery 是 governance enforcement 关键 prerequisite, 反 prompt assume scope blind execute.

**SOP sediment**:
- 任 sub-PR cite 含 "capacity / scale / throughput" 等 framing 必 Phase 0 verify 实际架构 (反 single path replace 假设 capacity expansion)
- 沿用 chunk C-LL option α scope correction precedent — Phase 0 active discovery 沿用 prompt cite drift catch 体例 sustained
- 沿用 chunk C-ADR ADR-033 → ADR-043 drift catch precedent — prompt cite location drift 沿用 fresh grep verify
- LL append-only 沿用 ADR-022 不 silent overwrite 体例 — LL-114 retroactive edit 0, LL-115 修正 sediment 沿用

**Capacity expansion 待预约 sub-PR scope** (~3-4h, architecture decision):
- Option (i) multi-Beat-entry: 4 Beat entries, one per route, 4x cron triggers
- Option (ii) task-iterator: news_ingest_rsshub task iterates 4 routes per call
- Option (iii) route-list-arg: Beat passes `route_paths=['/jin10/news', '/jin10/0', '/jin10/1', '/eastmoney/search/A股']`
- ADR design + reviewer + AI self-merge

**relate**:
- LL-114 (sub-PR 待预约 misframe sediment, append-only sustained)
- chunk C-LL PR #268 (option α scope correction precedent — Phase 0 active discovery enforcement)
- chunk C-ADR PR #267 (ADR-043 cite repair doc-only 体例 + ADR-033 → ADR-043 drift catch precedent)
- ADR-043 4 working routes baseline cite (chunk C-RSSHub Path A closure 5-07)
- LL-098 X10 forward-progress reverse case
- LL-104 cross-verify SOP
