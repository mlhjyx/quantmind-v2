# QuantMind V2 — 关键设计决策（已确认，必须遵守）

> 从 CLAUDE.md 迁移，原始位置已替换为指向本文件的引用。
> 这些决策经过三轮review确认（93项+40项补充），变更需用户审批。

## 策略层

**信号合成**: Phase 0 两个都做——**等权Top-N为基线**（先跑），IC加权为对比版。
等权更稳健、更易调试。IC加权如果不如等权，则锁定等权作为规则版。

**换手率上限**: 单次调仓换手率上限50%（即每次调仓最多换一半持仓），不是年化换手率。

## 数据完整性层

**存活偏差处理**: symbols表必须包含已退市股票。
拉取时用 `stock_basic(list_status='D')` 获取全量退市股。
回测中退市股处理：退市前5个交易日强制平仓，按最后可交易价格结算。
不处理存活偏差会让回测收益虚高2-5%/年。

**交易日历维护**: 年初从Tushare导入后，加每日校验（今天是否交易日 vs 实际市场开盘状态）。
加手动修改交易日历的API应对临时变动（如特殊事件休市）。

## 数据存储层

**factor_values用长表**: TimescaleDB hypertable，按月分chunk（不是默认7天）。
索引 `(symbol_id, date, factor_name)`。读取时永远带date范围条件。
5年1.27亿行在TimescaleDB可承受。Phase 1因子数涨到100+时如果出现瓶颈再迁宽表。
**写入模式: 按日期批量写**——每日因子计算完成后，一次事务写入当日全部股票×全部因子。
不要按因子逐个写（会产生34次事务，性能差且中途crash导致数据不一致）。
```python
# ✅ 正确: 按日期批量写
async def save_daily_factors(date: date, factor_df: pd.DataFrame):
    """factor_df: columns=[symbol_id, factor_name, value], 当日全部因子"""
    async with session.begin():  # 单事务
        await bulk_upsert(factor_df)  # 全部写入或全部回滚

# ❌ 错误: 按因子逐个写
for factor_name in factors:
    await save_single_factor(date, factor_name, values)  # 34次事务，crash风险
```

**index_components表**: 需新建，存沪深300/中证500等指数的成分股权重历史。
```sql
CREATE TABLE index_components (
    index_code VARCHAR(10),
    code VARCHAR(10),
    trade_date DATE,
    weight DECIMAL(8,6),
    PRIMARY KEY (index_code, code, trade_date)
);
```

## 架构层

**Service依赖注入**: 统一用FastAPI的 `Depends` 链注入，不要手动new。
所有Service通过Depends获取db session，保证同一请求共享session。

**Celery与async的混合**: 采用方案A——Celery task内部用 `asyncio.run()` 调用async Service。
简单够用，每次创建新事件循环的开销对定时任务可忽略。
```python
# Celery task 标准写法
@celery_app.task
def daily_factor_calc_task():
    asyncio.run(_async_daily_factor_calc())

async def _async_daily_factor_calc():
    async with get_async_session() as session:
        service = FactorService(session)
        await service.calc_daily_factors()
```

**执行层Broker策略模式**: Paper/实盘/外汇共用同一套因子→信号→风控链路，
唯一区别是执行层。用策略模式切换，配置项`EXECUTION_MODE = paper / live`：
```python
class BaseBroker(ABC):
    async def submit_order(self, order: Order) -> Fill: ...
    async def cancel_order(self, order_id: str) -> bool: ...
    async def get_positions(self) -> list[Position]: ...

class SimBroker(BaseBroker): ...       # Paper Trading（Phase 0）
class MiniQMTBroker(BaseBroker): ...   # A股实盘（Phase 1）
class MT5Broker(BaseBroker): ...       # 外汇实盘（Phase 2）

# 工厂函数
def get_broker() -> BaseBroker:
    if settings.EXECUTION_MODE == "paper":
        return SimBroker()
    elif settings.EXECUTION_MODE == "live":
        return MiniQMTBroker()
```

**策略版本管理**: `strategy_configs.config`是JSONB，每次变更**插入新version行**
而不是更新旧行。回滚 = 把`strategy.active_version`指回旧版本号。
每个版本有独立回测记录，支持V1 vs V2 vs V3对比。

## 风控层

**回撤熔断恢复状态机**（Phase 1实现）:
```
正常 → 降仓（月亏>10%）→ 正常（连续5个交易日累计盈利>2%）
降仓 → 停止（累计亏>25%）→ 人工审批重启
```

**外汇关联敞口限制**（Phase 2实现）:
相关性>0.7的品种对，合并计算敞口，总和不超过单品种限仓的1.5倍。

## Paper Trading 运行模式与毕业标准

**Paper Trading = 实时回测**: 真实行情 + 虚拟资金，走和实盘完全一样的
因子→信号→风控→执行链路，唯一区别是Broker用SimBroker。
- 每日走T日盘后调度链路（16:30→17:20），与实盘完全一致
- `trade_log`和`position_snapshot`用`execution_mode = 'paper'`字段区分
- Paper和实盘共用`strategy_id`，通过`execution_mode`区分记录

**毕业标准（转实盘前必须全部达标，9项）**:

| # | 指标 | 标准 |
|---|------|------|
| 1 | 运行时长 | ≥ 60个交易日（约3个月） |
| 2 | Sharpe | ≥ 回测Sharpe × 70% |
| 3 | 最大回撤 | ≤ 回测MDD × 1.5倍 |
| 4 | 滑点偏差 | 实际滑点与模型预估偏差 < 50% |
| 5 | 链路完整性 | 信号→审批→执行→归因 全链路无中断 |
| 6 | fill_rate | ≥ 95%（成交率，封板/停牌导致执行不全） |
| 7 | avg_slippage | ≤ 30bps（平均滑点，执行质量） |
| 8 | tracking_error | ≤ 2%（年化跟踪误差，信号→实际偏离） |
| 9 | gap_hours | 12-20h（信号生成→执行的时间差，标准链路T日17:20→T+1 09:30≈16h） |

**不达标不允许上实盘。降低标准需要书面记录理由。**

## AI闭环层（Phase 1+）

**三步走战略（2026-03-28确认）**:
```
Step 1 (当前): PT毕业→实盘，不需要AI闭环也能赚钱
Step 2 (PT后):  GP最小闭环 = FactorDSL + Warm Start GP + FactorGate G1-G8 + SimBroker反馈
Step 3 (GP验证后): LLM Agent层 + 知识森林 + PipelineOrchestrator + 因子+模型联合优化
```
**GP-first原则**: GP零成本、确定性高、天然闭环。GP跑不通→LLM也跑不通。
**Warm Start GP**: 用现有5因子表达式结构做模板初始化（arxiv 2412.00896），适应度=SimBroker回测Sharpe（不是IC proxy）。
**RD-Agent借鉴**: 知识森林(跨轮次经验)/因子+模型联合优化/Co-STEER代码生成。不直接集成（依赖Azure/不支持A股约束）。
**Qlib算子参考**: 不集成Qlib回测（不支持整手/涨跌停），但用Alpha158算子集作为FactorDSL设计参考。

**LLM因子门槛**: 降低初始门槛到 IC > 0.015 即可入候选池观察。
重点评估正交性（与现有因子相关性 < 0.5），低IC但高正交性的因子在组合中有分散化价值。

**Agent冲突仲裁**（Phase 3）:
- 风控Agent有一票否决权（安全优先）
- 因子发现和策略构建的分歧由回测结果裁定
- 所有冲突记录到 agent_decision_log

**AI诊断触发机制**（Phase 1）:
- 不只周日定时跑——**绩效衰退>阈值时事件驱动即时触发**
- `performance_series`表加**滚动绩效视图**（近20/60/120天Sharpe/MDD），供Agent直接查询
- 明确Agent输入context组装逻辑：从performance_series + factor_ic_history +
  active_factors + recent_trades 四张表拉数据，拼成结构化JSON给LLM

**AI变更验证上线流程**（Phase 1，三步机制）:
```
1. AI输出变更建议 → 写入 approval_queue（不直接生效）
2. 自动触发快速回测（最近1年，非全量5年）验证变更效果
3. 验证通过 + 人工审批 → 生效到次日信号链路
   验证不通过（回测变差）→ 自动拒绝 + 记录原因到 agent_decision_log
```
**不允许AI变更跳过回测验证直接上线。**

**GP引擎优化**（Phase 1）:
- 反拥挤阈值降到0.5-0.6（0.8太高，相关性0.79本质是同一因子变体）
- 适应度加复杂度惩罚：`fitness = IC×w1 + IR×w2 + 原创性×w3 - 节点数×w4`
- 岛屿模型：种群分3-4个子群独立进化，每N代交换少量个体
- GP发现的因子必须通过样本外测试（GP只在训练集上跑）

**暴力枚举剪枝**（Phase 1）:
- 量纲不匹配的组合直接跳过（如 `ts_corr(volume, pe_ttm, 20)` 无经济学意义）
- 分批优先级：先算单算子单字段（~150个），过IC快筛后再做二元组合
- 设时间预算上限（如最多2小时），超时按已算IC排序取Top

**LLM因子质量控制**（Phase 1）:
- 去重检测：新因子与已有因子embedding相似度>0.8直接拒绝
- 快速验证：代码生成后先跑100只股票×1年（~5秒），通过再跑全量
- 有效率监控：连续5轮通过Gate的比例<5%自动暂停并触发诊断

**知识库去重改进**（Phase 1）:
- 去重基于因子值的Spearman相关性>0.7判定重复（不是表达式embedding）
- failure_reason结构化：`{"gate": "ic", "ic_mean": 0.008, "threshold": 0.02}`
- 给Idea Agent注入"这些方向已尝试N次都失败"的上下文

**因子生命周期状态机**（Phase 1）:
```
candidate → active → warning → critical → retired
                ↑                              │
                └──── 新因子替补 ←─── 触发挖掘 ←┘
```
- critical持续2周 → 自动降权到0（保留计算用于监控恢复）
- 活跃因子数<12 → P1告警 + 触发紧急因子挖掘
- 退休因子进入冷宫6个月后自动检查一次（市场风格可能轮回）

**因子拥挤度监控**（Phase 1，架构预留）:
- 公式：`crowding = corr(factor_rank, abnormal_volume, cross_section)`
- 拥挤度>阈值时自动降低该因子权重
- 作为元因子(meta-factor)，Phase 0架构预留接口
