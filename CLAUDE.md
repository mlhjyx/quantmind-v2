# CLAUDE.md — QuantMind V2 量化交易系统

> **Claude Code: 这是你的主控文件。每次启动时自动读取。严格遵守本文件中的所有规则。**

---

## ⚠️ Compaction保护（触发compaction时必须保留以下信息）

```
--- 稳定层（几乎不变）---
当前阶段: Phase 1
v1.1配置: 5因子等权(turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio) + Top15 + 月度 + 行业25%
环境: Windows 11 Pro (R9-9900X3D 12C/24T + RTX 5070 12GB + 32GB DDR5-6000), PG: D:\pgdata16, 用户: xin
管理制度: 宪法V3.3(8铁律+按需spawn≤4+因子审批链+角色Spawn Prompt+交叉审查矩阵+strategy升级+设计文档对照)
关键文件: TEAM_CHARTER_V3.3.md / PROGRESS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md / docs/IMPLEMENTATION_MASTER.md
--- 动态层（读记忆+PROGRESS恢复）---
compaction/新session第一步: 读记忆文件(自动加载MEMORY.md索引) + PROGRESS.md 恢复完整上下文
⚠️ 记忆文件位置: C:\Users\hd\.claude\projects\D--quantmind-v2\memory\（MEMORY.md为索引，project_sprint_state.md为当前状态）
⚠️ 第二步: 确认当前Sprint + 读docs/IMPLEMENTATION_MASTER.md对应Sprint章节
⚠️ 第三步(LL-027+LL-030强制): 读TEAM_CHARTER_V3.3.md §1全文 → TeamCreate建团队 → 附录A角色Prompt
⚠️ Sprint启动顺序: TeamCreate → §5.1任务清单 → 附录A spawn prompt → 编码（编码是最后一步不是第一步）
⚠️ 用户计划有N个角色必须spawn N个，不能跳过任何一个
```

**compaction自定义指令**: 保留所有因子IC数据、配置变更记录、bug根因分析、§3.6.3决策和理由。可压缩：具体代码实现讨论、agent间中间对话、已解决的排查过程。

---

## 8铁律（宪法V3.3，每次回复前检查）

```
1. spawn了才算启动（LL-015）
2. 因子验证用生产基线+中性化（LL-013+LL-014合并）
3. 因子入组合前SimBroker回测（LL-017）
4. Sprint复盘不跳过（技术5问+投资人3问）
5. 下结论前验代码——状态判断必须grep/read验证，不信文档（LL-019）
6. Sprint结束必更新PROGRESS.md——复盘第一步（LL-020）
7. ML实验必须OOS验证——训练/验证/测试三段分离（DSR=0.591警告）
8. 因子评估前strategy必须确定匹配策略——ic_decay→调仓频率/权重/选股方式（LL-027）
```

---

## 管理模式（宪法V3.3）

- **按需spawn**：数量根据项目需要动态调整。Spawn前必须读附录A角色定义+§1.3的5项必填上下文
- **每角色每Sprint≤2任务**，编码组+研究组并行（LL-001教训）
- **因子审批链**：alpha_miner挖→factor审假设→quant审统计→★strategy确定匹配策略（铁律8）→SimBroker回测（过程拦截5检查点）
- **strategy角色升级**：从审查员升级为策略设计师，负责因子-策略匹配（V3.3关键变更）
- **编码前对照设计文档**：11个DEV文档中已设计的功能按设计实现，不重新发明（工作原则7）
- **交叉审查矩阵**：附录B定义谁challenge谁，验代码/数据不是读文档（铁律5）
- **投资人视角复盘**：每Sprint结束全员必答"敢投多少钱？什么时候亏？"
- **优化目标排序**：MDD > Sharpe > 因子数量（全团队共识）
- **自我问责**：违规记入LL，同一规则≥3次必须升级执行机制，隐瞒违规最严重
- **Generator-Evaluator分离**：编码agent不可自我审查，产出方和审查方必须不同agent（§6.5）
- **Agent成本控制**：session spawn≤8, Opus仅深度推理角色, 重试≤2次后升级用户（§1.4）
- **Hook升级机制**：同一规则触发≥3次未修正→从提醒升级为阻断（§13.4）
- **PT代码隔离**：PT运行期间禁止修改v1.1信号/执行链路代码（§12.4/§16.2）
- **环境一致性**：换环境后重跑基线确认Sharpe偏差<2%（§16.1）
- **文档完整性**：agent引用的文档路径必须指向实际存在文件，新增/删除文档后同步全部引用（§15.2）
- **重试限制**：任何操作失败重试≤2次，第3次必须升级汇报用户（§15.1）
- **研究方向**：§10按角色定义（quant统计前沿/factor Alpha158对标/strategy组合优化/risk压力测试/alpha_miner Gu Kelly Xiu 94特征/ml Qlib RollingGen）
- **文档体系**：5个文档，RISK_LOG和RESEARCH_LOG已废弃删除

详见 TEAM_CHARTER_V3.3.md

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

> **技术决策快查表**: 已迁移至 `docs/TECH_DECISIONS.md`（78项决策历史）

---

## 资源约束（Windows 11 Pro / AMD R9-9900X3D 12C/24T / RTX 5070 12GB / 32GB DDR5-6000 / 2TB NVMe）

> 显式声明系统资源上限，防止某个模块吃光资源。超过任何一项 → P1告警。

| 资源 | 上限 | 说明 |
|------|------|------|
| PostgreSQL | ~4GB数据 + ~1GB索引 | 日频数据5年+moneyflow 614万行+factor_values 1.38亿行 |
| Redis | <512MB | Celery broker + 缓存 |
| Python主进程 | <4GB RSS | FastAPI + 因子计算 |
| Celery worker | <1GB per worker (×4) | 后台任务 |
| LightGBM GPU | <12GB VRAM | RTX 5070训练 |
| ML单次训练 | <30分钟 | 超时需裁剪特征/数据 |
| ML实验并行 | ≤1个 | GPU独占 |
| Task Scheduler信号阶段 | <5分钟 | 16:30触发，17:00前完成 |
| Task Scheduler执行阶段 | <2分钟 | 09:00触发 |
| Windows总内存 | 32GB (后期升64GB) | 留>8GB给OS+miniQMT |
| PG+Redis+Python+Celery | <16GB总计 | — |
| 磁盘监控 | >100GB剩余 | 2TB NVMe |

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
- **月预算**: 弹性调整(根据实际需求，不设固定上限)
- **硬件**: Windows 11 Pro (AMD R9-9900X3D 12C/24T + RTX 5070 12GB VANGUARD SOC + 32GB DDR5-6000 EXPO → 后期64GB + 2TB NVMe)

## 技术栈

- **后端**: Python 3.11+ (FastAPI + Celery + asyncpg)
- **前端**: React 18 + TypeScript + Tailwind + ECharts/Recharts
- **数据库**: PostgreSQL 16 + Redis
- **AI模型**: DeepSeek API（因子挖掘/AI闭环）
- **交易对接**: 国金miniQMT (A股) + ECMarkets MT5 1:100 (外汇)
- **部署**: Windows 11原生，PG/Redis为Windows服务，Paper Trading用Task Scheduler(信号16:30/执行09:00)

## 开发路线

```
Phase 0 (当前): 从零MVP完整规则版管道 — 质量优先不设deadline
Phase 1: A股完整 + AI模块化替换（14个AI参数逐个验证替换规则版）
Phase 2: 外汇MT5
Phase 3: 整合 + AI闭环完整
Phase 4+: RTX 5070 GPU训练 + 64GB内存 + 本地模型
```

## 目录结构

```
quantmind-v2/
├── CLAUDE.md                              ← 本文件（Claude Code入口）
├── pyproject.toml                         ← Python依赖（已生成）
├── docs/
│   ├── IMPLEMENTATION_MASTER.md           ← ⭐ 实施总纲（117项/10Sprint/5轨道，唯一操作文档）
│   ├── DEVELOPMENT_BLUEPRINT.md           ← 设计vs现状审计（135功能，62%完成）
│   ├── QUANTMIND_V2_DDL_FINAL.sql         ← ⭐ 统一DDL（43张表，建表只看这个）
│   ├── QUANTMIND_V2_DESIGN_V5.md          ← A股总设计文档（核心）
│   ├── QUANTMIND_V2_FOREX_DESIGN.md       ← 外汇总设计（Phase 2）
│   ├── TECH_DECISIONS.md                  ← 技术决策快查表（78项历史）
│   ├── DESIGN_DECISIONS.md                ← 关键设计决策（93+40项）
│   ├── DEV_BACKEND.md                     ← 后端服务层+数据流+协同矩阵+工具集成规范
│   ├── DEV_BACKTEST_ENGINE.md             ← 回测引擎+可信度规则+报告指标
│   ├── DEV_AI_EVOLUTION.md                ← AI闭环后端
│   ├── DEV_FACTOR_MINING.md               ← 因子挖掘+计算规则
│   ├── DEV_PARAM_CONFIG.md                ← 参数可配置
│   ├── DEV_FRONTEND_UI.md                 ← 前端UI（13章695行）
│   ├── DEV_SCHEDULER.md                   ← 调度运维+时序+运维规则
│   ├── TUSHARE_DATA_SOURCE_CHECKLIST.md   ← ⭐ 数据源接入checklist
│   ├── research/                          ← R1-R7研究报告（7份已完成）
│   └── archive/                           ← 已归档过时文档
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

> **关键设计决策**: 已迁移至 `docs/DESIGN_DECISIONS.md`（93+40项，策略/数据/架构/风控/PT/AI闭环）

> **回测可信度规则 + 报告必含指标**: 已迁移至 `docs/DEV_BACKTEST_ENGINE.md`（6条硬规则+12项指标）

> **因子计算规则**: 已迁移至 `docs/DEV_FACTOR_MINING.md`（预处理顺序+IC定义）

> **调度时序 + 运维规则**: 已迁移至 `docs/DEV_SCHEDULER.md`（A股T日链路+预检+备份+日志）

> **开源工具集成规范**: 已迁移至 `docs/DEV_BACKEND.md`（6规则+协同矩阵+验收标准）

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
| **查下一步做什么/Sprint计划** | **`docs/IMPLEMENTATION_MASTER.md`** ⭐唯一操作总纲(117项/10Sprint/5轨道) |
| **建数据库表** | **`docs/QUANTMIND_V2_DDL_FINAL.sql`** ⭐唯一DDL来源 |
| 查技术决策历史 | `docs/TECH_DECISIONS.md`（78项决策） |
| 查架构设计决策 | `docs/DESIGN_DECISIONS.md`（93+40项决策） |
| 了解系统架构和技术选型 | `docs/QUANTMIND_V2_DESIGN_V5.md` §3 系统架构 |
| 查数据库表设计意图 | `docs/QUANTMIND_V2_DESIGN_V5.md` §4 (DDL在DDL_FINAL.sql) |
| 查设计vs实现差距 | `docs/DEVELOPMENT_BLUEPRINT.md`（135功能审计，62%完成） |
| 写后端服务/API/工具集成 | `docs/DEV_BACKEND.md` |
| 写回测引擎/可信度规则 | `docs/DEV_BACKTEST_ENGINE.md` |
| 写因子计算/因子规则 | `docs/DEV_FACTOR_MINING.md` |
| 写AI闭环模块 | `docs/DEV_AI_EVOLUTION.md` |
| 写参数配置 | `docs/DEV_PARAM_CONFIG.md` |
| 写前端页面 | `docs/DEV_FRONTEND_UI.md` |
| **接入任何数据源** | **`docs/TUSHARE_DATA_SOURCE_CHECKLIST.md`** ⭐必读 |
| 写调度任务/运维规则 | `docs/DEV_SCHEDULER.md` |
| 写ML Walk-Forward训练 | `docs/ML_WALKFORWARD_DESIGN.md`（LightGBM滚动训练框架） |
| 写风控服务 | `docs/RISK_CONTROL_SERVICE_DESIGN.md`（L1-L4熔断+PreTradeValidator） |
| 查R1-R7研究结论 | `docs/research/R1-R7`（因子匹配/挖掘技术/多策略/微观结构/对齐/生产/AI选型） |
| 查Qlib GP因子挖掘 | `docs/research/QLIB_GP_FACTOR_MINING_RESEARCH.md` |
| **写GP最小闭环（Step 2）** | **`docs/GP_CLOSED_LOOP_DESIGN.md`**（Warm Start GP+FactorDSL+SimBroker反馈） |
| 外汇相关（Phase 2） | `docs/archive/DEV_FOREX.md` + `docs/QUANTMIND_V2_FOREX_DESIGN.md` |
| 已归档文档（勿引用） | `docs/archive/`（已归档过时文件） |

---

## 策略版本化纪律（Paper Trading期间强制执行）

- 当前版本：**v1.1**（5因子等权+Top15+月度+行业25%）
- 因子：turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio
- 基线Sharpe：1.03（Windows环境，2021-2025全期，reversal_20补算后与Mac的1.037仅差0.007）
- 基线MDD：-39.7%
- 毕业标准：Sharpe ≥ 0.72, MDD < 35%, 滑点偏差 < 50%
- v1.0→v1.1变更：Top-N从20改为15（整手约束误差8%→3-4%）
- **任何参数变更 = 新版本号**（v1.1/v1.2...）
- Paper Trading期间**只允许运行一个版本**
- 改参数 = 新版本 → **60天Paper Trading重新计时**
- strategy_configs表的version字段必须严格维护，每次变更写入param_change_log
- 防止"Paper Trading到一半觉得不好就改参数"

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
- ✅ R1-R7研究全部完成（7份报告，73个可落地项）
- ✅ IMPLEMENTATION_MASTER v2.0（117项, 10 Sprint, 5轨道, 2522行）
- ✅ 文档瘦身完成（CLAUDE.md 864→~350行，详细内容迁移至DEV文档）
- 🔨 **Sprint 1.18完成, 下一步Sprint 1.19** ← 当前阶段
- ⬜ Phase 1: A股完整 + AI替换
- ⬜ Phase 2: 外汇MT5
- ⬜ Phase 3: 整合 + AI闭环

---

## 执行任务时的标准流程

1. 读取本文件（CLAUDE.md）了解全局上下文
2. 根据任务类型，去文档索引表找到对应DEV文档阅读
3. **如果涉及数据拉取/数据源接入 → 先读 `docs/TUSHARE_DATA_SOURCE_CHECKLIST.md`**
4. **如果涉及回测引擎 → 先读 `docs/DEV_BACKTEST_ENGINE.md`（含回测可信度规则6条+报告指标12项）**
5. **如果涉及因子计算 → 先读 `docs/DEV_FACTOR_MINING.md`（含因子计算规则：预处理顺序+IC定义）**
6. **如果涉及调度/运维 → 先读 `docs/DEV_SCHEDULER.md`（含调度时序+运维规则）**
7. 按照DEV文档中的规范实现代码
8. 实现完成后运行验证命令/测试
9. 如果发现需要偏离指令的地方 → 先报告，等确认后再执行

### 回测引擎架构要求
回测引擎必须支持**注入自定义行情数据**（不只是从DB读历史数据），
为Phase 1的压力测试模式（历史极端场景回放+合成场景注入）预留接口。
