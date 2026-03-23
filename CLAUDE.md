# CLAUDE.md — QuantMind V2 量化交易系统

> **Claude Code: 这是你的主控文件。每次启动时自动读取。严格遵守本文件中的所有规则。**

---

## ⚠️ Compaction保护（触发compaction时必须保留以下信息）

```
当前阶段: Phase 1, Sprint 1.3b
Paper Trading: v1.1运行中(2026-03-23启动), Day 2, 60天倒计时
v1.1配置: 5因子等权(turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio) + Top15 + 月度 + 行业25%
基线Sharpe: 1.037, MDD: -39.7%, 毕业标准: Sharpe≥0.73, MDD<35%
团队: 10+1人(quant/arch/data/qa/factor/strategy/risk/frontend/ml/alpha_miner + Team Lead)
已启用: quant/arch/data/qa/factor/strategy/risk/alpha_miner (8人)
未启用: frontend(Phase 1B)/ml(Phase 1C)
阻塞项: 无
战略调整: v1.1锁死不升级(等权天花板LL-017), alpha_miner转为LightGBM特征池, 分层排序研究中
管理制度: 宪法V3.0(5铁律+按需spawn≤4+因子审批链) — 替代V2.4
关键文件: TEAM_CHARTER_V3.md / PHASE_1_PLAN.md / PROGRESS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md
```

**compaction自定义指令**: 保留所有因子IC数据、配置变更记录、bug根因分析、§3.6.3决策和理由。可压缩：具体代码实现讨论、agent间中间对话、已解决的排查过程。

---

## 5铁律（宪法V3.0，每次回复前检查）

```
1. spawn了才算启动（LL-015）
2. IC分析用生产基线（LL-013）
3. 新因子必须中性化验证（LL-014）
4. Sprint复盘不跳过
5. 用户指令立即执行
```

---

## 管理模式（宪法V3.0）

- **按需spawn**：同时≤4个agent，完成即释放。不维持常驻团队。
- **每角色每Sprint≤2任务**
- **Sprint开始**：同时列编码+研究任务（LL-001）
- **因子审批链**：alpha_miner挖→factor审假设→quant审统计（唯一保留的交叉审查）
- **三轮讨论**：仅§4.3级别重大决策（改配置/改架构/上实盘）才做
- **废弃制度**：组长制/全矩阵交叉审查/研究独立考核/过程拦截/10铁律→精简为上述

详见 TEAM_CHARTER_V3.md

---

## 上下文管理制度

### 操作规则（每次会话/Sprint/compaction时执行）

**每次会话开始**：读PROGRESS.md + TodoWrite列表恢复状态，确认活跃agent列表

**每天结束**：更新PROGRESS.md（任务状态+阻塞项），上下文>60%时主动`/compact`

**Sprint结束**：`/clear`清空上下文，归档到PROGRESS.md，新Sprint新会话

**Agent管理**：
- 同时spawn不超过4个agent（token成本+管理复杂度）
- 轻量任务用subagent而非full agent
- spawn prompt精简到最小必要信息，不让每个agent读整个CLAUDE.md
- qa/data等不需要最强推理的角色可用Sonnet模型

**防compaction丢失**：
- 关键决策写入文件（LESSONS_LEARNED/strategy_configs/param_change_log），不依赖对话记忆
- 每次compaction后自检：还知道当前Sprint？还知道有哪些agent？不知道就读文件恢复
- CLAUDE.md顶部compaction保护段落必须随Sprint进展更新

---

## 技术决策快查表

> 新会话恢复上下文时一眼看完整个决策历史。每个技术决策追加一行。

| 决策 | 结果 | 判定 | 阶段 |
|------|------|------|------|
| Beta对冲 | 现金拖累36%，去掉后Sharpe 1.01→1.29 | Reverted | Phase 0 |
| GPA因子 | 行业proxy，中性化后IC不显著(p=0.14) | Reverted | Phase 0 |
| 候选2红利低波 | 与基线corr=0.778，无分散价值 | Reverted | Sprint 1.2 |
| 候选4大盘低波 | OOS Sharpe=-0.11，2022年亏-37.85% | Reverted | Sprint 1.2 |
| 候选5中期反转 | corr=0.627，不够正交 | Reverted | Sprint 1.2 |
| Top20→Top15 | 整手误差8%→3%，Sharpe 1.054→1.037无差异 | KEEP | Sprint 1.2 |
| 波动率自适应阈值 | 高波放宽低波收紧，clip(0.5, 2.0) | KEEP | Sprint 1.1 |
| L1延迟方案C | L1触发时月度调仓延迟不跳过 | KEEP | Sprint 1.2 |
| days_gap改交易日 | 自然日→交易日，修复国庆/五一误杀 | KEEP | Sprint 1.2 |
| mf_divergence | IC=9.1%全项目最强，资金流新维度 | KEEP(入池) | Sprint 1.3 |
| price_level | IC=8.42%，低价股效应 | KEEP(入池) | Sprint 1.3 |
| PEAD earnings_surprise | IC=5.34%，corr<0.11最干净新维度 | Pending审批 | Sprint 1.3b |
| IVOL替换vol_20 | IC 6.67% vs 3.27%，但OOS Sharpe持平 | Pending | Sprint 1.3 |
| 等权 vs IC加权 | 等权表现更好（三轮讨论共识） | KEEP等权 | Phase 0 |
| 同框架多策略 | 5候选全部失败，50/50组合拉低基线 | Reverted方向 | Sprint 1.2 |
| 5因子vs8因子 | 8因子Sharpe=0.50(弱因子稀释)，5因子=1.05 | KEEP 5因子 | Sprint 1.2 |
| Deprecated 5因子 | momentum_20/high_low_range等停止计算省23% | KEEP | Sprint 1.3b |
| v1.2升级(+mf_divergence) | paired bootstrap p=0.387，增量不显著 | NOT JUSTIFIED | Sprint 1.3a |
| big_small_consensus | 原始IC=12.74%中性化后-1.0%，虚假alpha | Reverted | Sprint 1.3a |
| PEAD加入等权组合 | IC=5.34%但组合Sharpe-0.085(等权天花板LL-017) | Reverted | Sprint 1.3b |
| 等权因子数上限 | 5-6因子局部最优，更多反而差 | KEEP 5因子 | Sprint 1.3b |
| v1.1配置锁死 | 不再等权升级，60天Paper Trading跑完 | KEEP | Sprint 1.3b |
| KBAR 15因子 | 15/20 PASS但大部分与vol/rev冗余，3个独立候选入Reserve | Reserve | Sprint 1.3b |
| 最大化ICIR加权 | Sharpe=0.992<基线1.035，集中度过高(turnover50-70%) | Reverted | Sprint 1.3b |
| 最大化IC加权 | Sharpe=0.929，更激进更差 | Reverted | Sprint 1.3b |
| ICIR简单加权 | Sharpe=0.912，CI下界<0 | Reverted | Sprint 1.3b |
| 收益率加权 | Sharpe=0.861 | Reverted | Sprint 1.3b |
| 因子择时(5F) | Sharpe=0.876，择时引入滞后噪声 | Reverted | Sprint 1.3b |
| 因子择时+PEAD(6F) | Sharpe=0.679最差，PEAD 2024崩塌-23.5% | Reverted | Sprint 1.3b |
| 半衰期加权 | Sharpe=0.838 | Reverted | Sprint 1.3b |
| BP子维度融合 | Sharpe=0.820，子维度增加噪声 | Reverted | Sprint 1.3b |
| **线性合成全面对比** | **9种方法全部劣于等权，等权=线性全局最优(LL-018)** | **KEEP等权** | Sprint 1.3b |

---

## 资源约束（Mac M1 Pro 16GB环境）

> 显式声明系统资源上限，防止某个模块吃光资源。超过任何一项 → P1告警。

| 资源 | 上限 | 说明 |
|------|------|------|
| PostgreSQL | ~3GB数据 + ~1GB索引 | 日频数据5年+moneyflow 614万行 |
| Redis | <512MB | Celery broker + 缓存 |
| Python主进程 | <2GB RSS | FastAPI + 因子计算 |
| Celery worker | <1GB per worker | 后台任务 |
| crontab信号阶段 | <5分钟 | 16:30触发，17:00前完成 |
| crontab执行阶段 | <2分钟 | 17:00触发 |
| Mac总内存 | 16GB | 留>8GB给OS |
| PG+Redis+Python+Celery | <8GB总计 | — |
| 磁盘监控 | >50GB剩余 | 健康检查已覆盖 |

---

## 因子审批硬性标准

> 研究报告#2确定，Harvey Liu Zhu (2016)折中标准。

- **t > 2.5**：硬性下限，不管BH-FDR结果如何，t<2.5直接否决
- **t 2.0-2.5**：需额外经济学解释支撑才可有条件通过
- **BH-FDR校正**：用FACTOR_TEST_REGISTRY.md中的累积测试总数M作为分母
- **中性化后IC**：所有新因子必须做中性化验证（LL-014）

---

## 项目概述

QuantMind V2 是个人A股+外汇绝对收益量化交易系统，完全从零重写（V1已废弃）。
- **目标**: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- **用户**: 1人使用，全职投入
- **月预算**: ≤¥500
- **硬件**: Mac M1 Pro 16GB → 后期迁移Mac Studio

## 技术栈

- **后端**: Python 3.11+ (FastAPI + Celery + asyncpg)
- **前端**: React 18 + TypeScript + Tailwind + ECharts/Recharts
- **数据库**: PostgreSQL 16 + Redis
- **AI模型**: DeepSeek API（因子挖掘/AI闭环）
- **交易对接**: 国金miniQMT (A股) + ECMarkets MT5 1:100 (外汇)
- **部署**: Mac本地，Homebrew原生，非Docker

## 开发路线

```
Phase 0 (当前): 从零MVP完整规则版管道 — 质量优先不设deadline
Phase 1: A股完整 + AI模块化替换（14个AI参数逐个验证替换规则版）
Phase 2: 外汇MT5
Phase 3: 整合 + AI闭环完整
Phase 4+: Mac Studio + MLX本地模型
```

## 目录结构

```
quantmind-v2/
├── CLAUDE.md                              ← 本文件（Claude Code入口）
├── pyproject.toml                         ← Python依赖（已生成）
├── docs/
│   ├── QUANTMIND_V2_DDL_FINAL.sql         ← ⭐ 统一DDL（43张表，建表只看这个）
│   ├── QUANTMIND_V2_DESIGN_V5.md          ← A股总设计文档（核心）
│   ├── QUANTMIND_V2_FOREX_DESIGN.md       ← 外汇总设计（Phase 2）
│   ├── DEV_BACKEND.md                     ← 后端服务层+数据流+协同矩阵
│   ├── DEV_BACKTEST_ENGINE.md             ← 回测引擎后端
│   ├── DEV_AI_EVOLUTION.md                ← AI闭环后端
│   ├── DEV_FACTOR_MINING.md               ← 因子挖掘后端
│   ├── DEV_PARAM_CONFIG.md                ← 参数可配置
│   ├── DEV_FRONTEND_UI.md                 ← 前端UI（13章691行）
│   ├── DEV_FOREX.md                       ← 外汇详细开发（Phase 2）
│   ├── DEV_SCHEDULER.md                   ← 调度运维
│   ├── DEV_NOTIFICATIONS.md               ← 通知告警
│   └── TUSHARE_DATA_SOURCE_CHECKLIST.md   ← ⭐ 数据源接入checklist
├── backend/                               # Python后端
│   ├── app/
│   │   ├── main.py                        # FastAPI入口
│   │   ├── config.py                      # pydantic-settings
│   │   ├── models/                        # SQLAlchemy/asyncpg模型
│   │   ├── services/                      # 业务逻辑层
│   │   ├── api/                           # API路由
│   │   ├── tasks/                         # Celery任务
│   │   └── data_fetcher/                  # 数据拉取模块
│   ├── tests/
│   ├── pyproject.toml
│   └── .env
├── frontend/                              # React前端
│   ├── src/
│   ├── package.json
│   └── tsconfig.json
└── scripts/                               # 运维脚本
```

## 数据库

- **43张表**（统一DDL: `docs/QUANTMIND_V2_DDL_FINAL.sql`，旧DDL已废弃）
- **220+可配置参数**
- **12个前端页面**
- **93项已确认的设计决策** + 40项review补充决策（三轮review）

---

## 关键设计决策（已确认，必须遵守）

### 策略层

**信号合成**: Phase 0 两个都做——**等权Top-N为基线**（先跑），IC加权为对比版。
等权更稳健、更易调试。IC加权如果不如等权，则锁定等权作为规则版。

**换手率上限**: 单次调仓换手率上限50%（即每次调仓最多换一半持仓），不是年化换手率。

### 数据完整性层

**存活偏差处理**: symbols表必须包含已退市股票。
拉取时用 `stock_basic(list_status='D')` 获取全量退市股。
回测中退市股处理：退市前5个交易日强制平仓，按最后可交易价格结算。
不处理存活偏差会让回测收益虚高2-5%/年。

**交易日历维护**: 年初从Tushare导入后，加每日校验（今天是否交易日 vs 实际市场开盘状态）。
加手动修改交易日历的API应对临时变动（如特殊事件休市）。

### 数据存储层

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

### 架构层

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

### 风控层

**回撤熔断恢复状态机**（Phase 1实现）:
```
正常 → 降仓（月亏>10%）→ 正常（连续5个交易日累计盈利>2%）
降仓 → 停止（累计亏>25%）→ 人工审批重启
```

**外汇关联敞口限制**（Phase 2实现）:
相关性>0.7的品种对，合并计算敞口，总和不超过单品种限仓的1.5倍。

### Paper Trading 运行模式与毕业标准

**Paper Trading = 实时回测**: 真实行情 + 虚拟资金，走和实盘完全一样的
因子→信号→风控→执行链路，唯一区别是Broker用SimBroker。
- 每日走T日盘后调度链路（16:30→17:20），与实盘完全一致
- `trade_log`和`position_snapshot`用`execution_mode = 'paper'`字段区分
- Paper和实盘共用`strategy_id`，通过`execution_mode`区分记录

**毕业标准（转实盘前必须全部达标）**:

| 指标 | 标准 |
|------|------|
| 运行时长 | ≥ 60个交易日（约3个月） |
| Sharpe | ≥ 回测Sharpe × 70% |
| 最大回撤 | ≤ 回测MDD × 1.5倍 |
| 滑点偏差 | 实际滑点与模型预估偏差 < 50% |
| 链路完整性 | 信号→审批→执行→归因 全链路无中断 |

**不达标不允许上实盘。降低标准需要书面记录理由。**

### AI闭环层（Phase 1+）

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

---

## ⭐ 回测可信度规则（Phase 0 强制执行）

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
不处理封板限制会让回测假设任何信号都能成交，严重失真。

### 规则2: 整手约束和资金T+1必须建模

**整手约束**:
```python
actual_shares = floor(target_value / price / 100) * 100  # A股最小交易单位100股
```
30只等权持仓的整手误差累积可能导致总仓位<95%，5%+现金拖累。

**资金T+1规则**:
- A股卖出资金当日可用于买入（T+0可用），但不可取出（T+1可取）
- SimBroker需跟踪：可用资金（含当日卖出回款）和 可取资金（不含当日卖出）
- 部分成交处理：剩余部分次日继续执行，不取消

**"实际vs理论仓位偏差"**: 作为回测输出指标。偏差长期>3%说明资金利用效率有问题。

### 规则3: 确定性测试用固定数据快照

- 用Parquet文件作为测试数据快照，不依赖数据库当前状态
- 测试流程：`load_snapshot → run_backtest → compare_hash(result)`
- 精确到**小数点后6位**完全一致（不是近似相等）
- 任何引入随机性的地方（排序稳定性、浮点累积）都必须固定

### 规则4: 回测结果必须有统计显著性

自动计算 **bootstrap Sharpe 95%置信区间**：
- 对日收益率序列做1000次bootstrap采样，计算Sharpe的5%/95%分位
- 展示格式：`Sharpe: 1.21 [0.43, 1.98] (95% CI)`
- 如果5%分位的Sharpe < 0，标红警告"策略可能不赚钱"

### 规则5: 隔夜跳空必须统计

回测报告加 **"开盘跳空统计"** 指标：
- 买入日 open vs 前日close 的平均偏差
- 如果偏差持续>1%，说明信号有"追涨"倾向，需要调整

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

## 因子计算规则（Phase 0 强制执行）

### 因子预处理顺序（严格按此顺序，不可调换）

```
1. 去极值（MAD）
2. 缺失值填充
3. 中性化（回归掉市值+行业）  ← 先中性化
4. 标准化（zscore）            ← 再标准化
```
**如果先zscore再中性化，中性化回归的残差分布会不对，所有因子IC都不准。**

### IC计算的forward return定义

- forward return使用**相对沪深300的超额收益**（不是绝对收益）
- 必须用**复权价格**（close × adj_factor / latest_adj_factor）计算
- 停牌期间的return用**行业指数**代替
- 同时计算1/5/10/20日IC，因子评估报告展示"绝对IC"和"超额IC"

---

## 调度时序（Phase 0 确认方案）

### A股：T日盘后计算，T+1日盘前确认执行

原方案（T+1日凌晨6:00计算）不可行——AKShare/Tushare数据在T日16:00-17:00才完整可用。

**修正方案**:
```
T日 16:30  拉取T日收盘数据（Tushare入库时间约15:00-16:00）
T日 17:00  因子计算（~15min）
T日 17:20  信号生成 + 调仓指令（存库）
T日 17:30  通知推送（钉钉/邮件，含调仓明细）
------- 隔夜 -------
T+1日 08:30  读指令 → 确认无异常 → 最终确认
T+1日 09:30  开盘执行
```
这样时间充裕，不用凌晨跑任务，也避免数据未更新的风险。

### 全链路健康预检（每日T日调度开始前）

调度链路第一步不是拉数据，而是跑预检。任何一项失败 → P0告警 + 暂停当日链路：
```
✓ PostgreSQL 连接正常
✓ Redis 连接正常
✓ 昨日数据已更新（klines_daily最新日期 = 上一交易日）
✓ 因子计算无NaN（抽样检查最近一日10只股票）
✓ 磁盘空间 > 10GB
✓ Celery worker 全部在线
✗ miniQMT 连接（Phase 1，实盘模式才检查）
✗ MT5 连接（Phase 2）
```
预检结果写入`health_checks`表，并与调度链路绑定——预检不过不触发后续任务。

### 外汇（Phase 2）
- Celery Beat统一用UTC
- 所有cron表达式写UTC
- 加 `utils/timezone.py` 封装 UTC ↔ 北京时间 ↔ broker时间转换
- forex调度加夏令时偏移表

---

## 回测报告必含指标

除了已有的Sharpe/MDD/年化收益/超额收益，必须包含：

| 指标 | 说明 |
|------|------|
| Calmar Ratio | 年化收益/最大回撤（关注尾部风险） |
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

## 运维规则（Phase 0 实现）

### 数据库备份
- 每日 `pg_dump` 到外部存储（外部硬盘或NAS）
- 关键表（klines_daily, factor_values）额外导出Parquet作为二级备份
- `scripts/verify_backup.sh` 定期验证备份可恢复

### 日志管理
- 开发阶段用DEBUG级别，Paper Trading及之后用**INFO级别**
- 因子计算详细日志走单独文件（`logs/factor_calc.log`），定期归档
- 加 `LOG_MAX_FILES` 配置，限制总日志大小（避免16GB机器磁盘撑满）

### 优雅停机与状态恢复
- 因子计算用**事务写入**：要么全部因子写成功，要么全部回滚
- 或每个因子独立写入 + **完成标记**，重启后检查标记只重算未完成的
- Celery task加 `acks_late=True`，crash后自动重试

---

## ⚠️ 工作原则（强制执行，违反即停止）

### 原则1: 不靠猜测做技术判断
涉及外部API、数据接口、第三方工具时，**必须先完整阅读官方文档**确认数据格式、字段含义、使用限制。不确定就说不确定，不要基于猜测给方案。

### 原则2: 数据源接入前必须过checklist
**任何Tushare/AKShare数据接入前，必须先读 `docs/TUSHARE_DATA_SOURCE_CHECKLIST.md`**，确认：
1. 该接口每个字段的单位（元/千元/万元/手/股/%）
2. 入库时是否需要单位转换
3. 跨表计算时单位是否对齐
4. 拉取后必须跑验证SQL

### 原则3: 做上层设计前先验证底层假设
一行SQL就能验证的事不要假设。拉完数据先抽样比对官方工具，确认数据正确再写因子。

### 原则4: 每个模块完成后必须有自动化验证
回测确定性验证（同参数跑两次结果bit-identical）、数据一致性检查、单元测试。

### 原则5: 不要自行决定范围外的改动
执行过程中如果发现需要额外的更改、改进、或偏离指令的地方，**先报告建议和理由，等确认后再执行**。

---

## 文档索引（按需查阅，不要一次全读）

| 你要做什么 | 读哪个文件 |
|-----------|-----------|
| **建数据库表** | **`docs/QUANTMIND_V2_DDL_FINAL.sql`** ⭐唯一DDL来源 |
| 了解系统架构和技术选型 | `docs/QUANTMIND_V2_DESIGN_V5.md` §3 系统架构 |
| 查数据库表设计意图 | `docs/QUANTMIND_V2_DESIGN_V5.md` §4 (DDL在DDL_FINAL.sql) |
| 写后端服务/API | `docs/DEV_BACKEND.md` |
| 写回测引擎 | `docs/DEV_BACKTEST_ENGINE.md` |
| 写因子计算 | `docs/DEV_FACTOR_MINING.md` |
| 写AI闭环模块 | `docs/DEV_AI_EVOLUTION.md` |
| 写参数配置 | `docs/DEV_PARAM_CONFIG.md` |
| 写前端页面 | `docs/DEV_FRONTEND_UI.md` |
| **接入任何数据源** | **`docs/TUSHARE_DATA_SOURCE_CHECKLIST.md`** ⭐必读 |
| 写调度任务 | `docs/DEV_SCHEDULER.md` |
| 写通知告警 | `docs/DEV_NOTIFICATIONS.md` |
| 外汇相关（Phase 2） | `docs/DEV_FOREX.md` + `docs/QUANTMIND_V2_FOREX_DESIGN.md` |

---

## 数据源关键信息（速查）

> 详细信息必须查阅 `docs/TUSHARE_DATA_SOURCE_CHECKLIST.md`，以下仅为速查提醒。

### Tushare Pro（8000积分已开通）

| 接口 | 关键字段单位 | 常见陷阱 |
|------|-------------|---------|
| daily | vol=**手**(×100=股), amount=**千元** | 价格是未复权！必须配合adj_factor |
| adj_factor | 累积因子（非每日比率） | 每次拉新数据后必须用最新因子重算全部历史adj_close |
| daily_basic | total_mv=**万元**, turnover_rate=**%** | turnover_rate vs turnover_rate_f 含义不同，不能混用 |
| moneyflow | 金额=**万元**, vol=**手** | 与daily的amount(千元)相差10倍！ |
| fina_indicator | 百分比字段已×100 | **必须用ann_date(公告日)做时间对齐，不是end_date** |

### AKShare（免费备用源）
- 北向资金持股、融资融券：优先用AKShare（Tushare无此接口或积分要求高）
- 降级策略: Tushare失败 → 重试3次 → 切AKShare → 都失败则报警

### 跨源单位对齐（最危险）
- `daily.amount`(千元) vs `moneyflow.amount`(万元) → 相差10倍
- `daily.amount`(千元) vs `daily_basic.total_mv`(万元) → 相差10倍
- 做截面排序(cs_rank)的因子不受单位影响，跨表计算的因子必须对齐

---

## 策略版本化纪律（Paper Trading期间强制执行）

- 当前版本：**v1.1**（5因子等权+Top15+月度+行业25%）
- 因子：turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio
- 基线Sharpe：1.037（修复后代码，2021-2025全期）
- 基线MDD：-39.7%
- 毕业标准：Sharpe ≥ 0.73, MDD < 35%, 滑点偏差 < 50%
- v1.0→v1.1变更：Top-N从20改为15（整手约束误差8%→3-4%）
- **任何参数变更 = 新版本号**（v1.1/v1.2...）
- Paper Trading期间**只允许运行一个版本**
- 改参数 = 新版本 → **60天Paper Trading重新计时**
- strategy_configs表的version字段必须严格维护，每次变更写入param_change_log
- 防止"Paper Trading到一半觉得不好就改参数"

---

## 开源工具集成规范

> 核心原则：统一集成，不是拼凑。所有工具藏在Service内部，换任何一个工具其他层无感知。

### 规则1: 工具只在Service层内部使用，不暴露给外部
```python
# ✅ 正确：Service封装
class FactorService:
    def calculate_rsi(self, prices, period=14):
        result = talib.RSI(prices, timeperiod=period)
        return self._to_factor_values(result)

# ❌ 错误：API直接调工具
@router.get("/factors/rsi")
def get_rsi():
    return talib.RSI(...)
```

### 规则2: 数据格式统一
所有因子不管来源（自写/TA-Lib/Alpha158/GP），最终都是`(code, trade_date, factor_value)`写入factor_values表。下游只读这张表。

### 规则3: 组合优化输出标准化
不管用等权/HRP/风险平价，输出都是`{"600519": 0.05, "000001": 0.04}`。PortfolioBuilder内部切换方法，外部接口不变。

### 规则4: 绩效分析双轨
QuantStats生成HTML报告（给人看）。核心指标（Sharpe/MDD/CI）仍然自己算（给程序用、写入DB）。两者互为验证——不一致说明有bug。

### 规则5: 一个工具一个wrapper
```python
# wrappers/ta_wrapper.py — 统一接口，底层可换
def calculate_indicator(name, prices, **params):
    if name == "RSI":
        return talib.RSI(prices, timeperiod=params.get("period", 14))
```

### 规则6: 配置统一
所有工具参数走param_service或.env，不允许分散在各自配置文件。

### 模块协同矩阵
```
数据层(PG) → FactorService(TA-Lib/Alpha158/自写) → factor_values表
           → SignalService(Alphalens分析/合成) → signals表
           → PortfolioBuilder(Riskfolio-Lib/等权) → {code: weight}
           → RiskService(熔断/Riskfolio-Lib) → 风控检查
           → ExecutionService(miniQMT/SimBroker) → trade_log表
           → PerformanceService(QuantStats+自算指标) → performance_series
每层通过Service接口通信，工具藏在内部。
```

### 引入工具验收标准
- 现有测试全部通过（没破坏任何东西）
- 新工具有wrapper+wrapper测试
- 一年模拟重跑Sharpe偏差<0.01
- factor_values表格式没变、下游无感知

---

## 代码规范

### Python
- 所有函数必须有类型注解
- Google style docstring（中文）
- 所有数据库操作用 async/await
- 金融金额用 `Decimal`（不用float做金额计算）
- 日期统一用 `datetime.date` / `datetime.datetime`
- 提交前: `ruff check` + `ruff format`
- 测试: `pytest` + `pytest-asyncio`

### React/TypeScript
- 函数组件 + Hooks，不用Class
- UI风格: Glassmorphism毛玻璃 + 涨跌色可配置
- 图表: ECharts（复杂图表）+ Recharts（简单图表）混合
- 状态管理: Zustand
- API调用统一通过 `src/api/` 层

### 数据库
- 所有表的金额/数量字段必须在列注释中标明单位
- 例: `COMMENT ON COLUMN klines_daily.volume IS '成交量（手，1手=100股）';`
- 索引: 所有 (symbol_id, date) 组合必须有联合索引

---

## 当前进度

- ✅ P0设计全部完成（11个文档，8004行）
- ✅ 93项设计决策 + 40项review补充决策（三轮review）已确认
- ✅ 数据源Checklist完成（716行）
- ✅ CLAUDE.md完整（含回测可信度规则、因子规则、调度时序、运维规则）
- 🔨 **Phase 0代码实现** ← 当前阶段
- ⬜ Phase 1: A股完整 + AI替换
- ⬜ Phase 2: 外汇MT5
- ⬜ Phase 3: 整合 + AI闭环

---

## 执行任务时的标准流程

1. 读取本文件（CLAUDE.md）了解全局上下文
2. 根据任务类型，去文档索引表找到对应DEV文档阅读
3. **如果涉及数据拉取/数据源接入 → 先读 TUSHARE_DATA_SOURCE_CHECKLIST.md**
4. **如果涉及回测引擎 → 先读本文件"回测可信度规则"章节（6条硬规则）**
5. **如果涉及因子计算 → 先读本文件"因子计算规则"章节（预处理顺序+IC定义）**
6. 按照DEV文档中的规范实现代码
7. 实现完成后运行验证命令/测试
8. 如果发现需要偏离指令的地方 → 先报告，等确认后再执行

### 回测引擎架构要求
回测引擎必须支持**注入自定义行情数据**（不只是从DB读历史数据），
为Phase 1的压力测试模式（历史极端场景回放+合成场景注入）预留接口。
