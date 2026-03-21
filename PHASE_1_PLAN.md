# Phase 1 计划 — A股完整 + AI + 实盘

> **状态**: ✅ 用户批准 (2026-03-22)
> **制定人**: Team Lead
> **日期**: 2026-03-22
> **三轮讨论**: 9人独立审查(Round 1) → 4议题交叉challenge(Round 2) → 收敛(Round 3)
> **前置**: Phase 0完成, Sprint 0.1完成, Paper Trading已通过20天模拟验证

---

## 总体目标

| 指标 | Phase 0现状 | Phase 1目标 | 系统总目标 |
|------|------------|------------|-----------|
| 年化收益 | 25.3%(unhedged) | 20-30% | 15-25% ✅ |
| Sharpe(回测) | 1.29(unhedged) | **≥ 1.4** | 1.0-2.0 |
| MDD | -33% | <25% | <15% |
| 因子数 | 5(规则) | 15-25(规则+ML+AI) | 30+ |
| 执行模式 | Paper Trading | 实盘(miniQMT) | 实盘 |

**关键差距**: MDD 33%→15%需要Phase 2/3跨市场分散。Phase 1目标MDD<25%通过因子多样化+风控。

### 衰减预算（Round 2共识 + 研究报告#1学术支撑）

**总衰减预估: 15-25%（回测Sharpe → 实盘Sharpe）**

两步衰减模型:
```
回测 Sharpe 1.4 → Paper Trading ×0.85~0.90 → 实盘 ×0.80~0.85
端到端: ×0.68~0.77 (中位0.72)
回测 Sharpe ≥ 1.4 → 实盘预期 Sharpe ≥ 1.0
```

**衰减来源分解（学术支撑）**:

| 衰减来源 | 预估幅度 | 可控性 | 学术依据 |
|---------|---------|--------|---------|
| 交易成本 | 5-10% | 可优化 | 佣金万1.5+印花税0.05%+滑点~0.1%/单边，月频调仓年化~0.3-0.5%成本 |
| 执行延迟 | 5-10% | 可优化 | T日信号→T+1执行，overnight gap风险 |
| 因子拥挤 | ~0% | N/A | 100万规模冲击可忽略（大基金数据不适用） |
| 模型不确定性 | 含在CI内 | 不可控 | Bootstrap CI已涵盖过拟合风险 |

**学术参考**:
- McLean & Pontiff (2016): 因子发表后样本外衰减~32%（但含大基金规模冲击，不完全适用）
- Research Affiliates: 大基金实盘因子收益是纸面的50%或更低（我们100万规模冲击远小于此）
- 因子半衰期: 价值25个月, 低波动12个月, 动量8个月（需持续监控因子IC衰减）

**对我们的适用性调整**: 学术数据主要来自大基金（规模冲击严重、空头执行成本高、多策略竞争激烈），我们100万规模+纯多头+A股散户行为Alpha，实际衰减应在学术数据的下限。15-25%是保守且合理的估计。

**回测Sharpe必须≥1.4才可进入Paper Trading**（给衰减留足安全边际）。

**Paper Trading期间的衰减监测阈值**:
- Paper Trading Sharpe > 1.0 → 实盘有望>0.75，可转实盘
- Paper Trading Sharpe 0.7-1.0 → 勉强，需评估原因
- Paper Trading Sharpe < 0.7 → 不应转实盘，先改进策略

---

## Phase 1 分阶段

```
Paper Trading启动 ──────────────────────────────── 毕业审查
    │                                                    │
    ├── Phase 1A: 工程基础+GPA因子 [5周]                │
    │   Sprint 1.0 (3周) + Sprint 1.1 (2周)             │
    │   团队: 7人 + GPA因子并行开发                      │
    │                                                    │
    ├── Phase 1B: 回测升级+前端+数据源 [9周]             │
    │   Sprint 1.2a/b (4周) + 1.3 (2周) + 1.4 (3周)    │
    │   团队: +frontend (8人)                            │
    │                                                    │
    └── Phase 1C: AI+ML+实盘 [10周, 4步渐进]            │
        1C-pre → alpha → beta1/2 → gamma                │
        团队: +ml (全员9人)                              │
                                              Paper Trading毕业
                                              → 实盘切换(1C-gamma)
```

**总工期预估: 24-28周**（Round 1九人评估共识，原14-18周严重低估）

---

## Phase 1A: 工程基础 + GPA因子 [5周]

**启用角色**: quant, arch, data, qa, factor, strategy, risk (7人)

### Sprint 1.0: 后端架构升级 [3周] ← Round 1: arch评估需3周

**双线并行**（Round 2议题J共识）：
- **主线**: Service→Repository分层重构 + Celery + 测试框架
- **辅线**: GPA因子引擎MVP（factor+arch并行）

| 里程碑 | 达标 | 及格 | 不及格 |
|--------|------|------|--------|
| Service分层 | 全部Service迁移 | 核心4个 | <4个 |
| Celery调度 | 7个定时任务 | 核心3个 | <3个 |
| GPA因子 | IC验证+入组合测试 | proxy版IC计算完成 | 未开始 |

**GPA提前的4个前提条件**（Round 2共识）：
1. Sprint 1.0第一周冻结FactorService接口契约
2. fina_indicator确认覆盖≥5年(2019-2024)
3. Service重构延期>1周则GPA暂停
4. GP种群初始限制200以内

**WebSocket Manager推迟到Sprint 1.4**（与前端同步，arch建议）

### Sprint 1.1: 通知+参数+风控 [2周]

任务不变。**新增**：
- Sprint 1.1末尾插入前端脚手架搭建(2-3天)：Vite初始化+Design Token+API client骨架
- 定义OpenAPI schema供前端mock开发（Round 2 frontend要求）

---

## Phase 1B: 回测升级+前端+数据源 [9周]

**新启用**: frontend (8人)

### Sprint 1.2a: 回测引擎核心升级 [2周] ← Round 1: quant+arch要求拆分

- Walk-Forward完整引擎 (arch)
- DSR (quant+arch)
- Volume-impact滑点模型 (arch+quant)
- FactorAnalyzer完整版 (arch+factor)

**Sprint 1.2a结束后立即做OOS基线测量**（Round 1 quant要求）：用WF测当前5因子策略的OOS Sharpe，根据实际衰减修订后续目标。

**Sprint 1.2a结束后做首轮压力测试**（Round 1 qa要求，原计划放在1.9太晚）。

### Sprint 1.2b: 回测引擎扩展 [2周]

- PBO (quant+arch) ← 从1.2a拆出，实现复杂度高
- Brinson归因 (strategy+arch)
- 市场状态检测(牛/熊/震荡) — **事后标注优先，实时切换Phase 2**（Round 1 strategy建议）
- 回测Celery异步任务化 (arch)
- 回测API 14端点 (arch)

### Sprint 1.3: 数据源+因子扩展 [2周] ← Round 1: data评估1周严重低估

| 周次 | 任务 | 负责 |
|------|------|------|
| Week 1 | 北向资金(AKShare) + 业绩预告(forecast) | data |
| Week 2 | 限售解禁 + 股东人数 + 新因子实现 | data+factor |

**跨表单位高危点清单**（Round 1 data整理）：
- `daily.amount`(千元) vs `moneyflow.amount`(万元) → 10倍差
- `fina_indicator.net_profit`(元) vs `forecast.net_profit`(万元) → 10000倍差

**Data Contract YAML推迟到Phase 2**（Round 1共识：当前ROI不高）

### Sprint 1.4: 前端MVP [3周] ← Round 1: frontend评估2周偏紧

| 里程碑 | 达标 | 及格 | 不及格 |
|--------|------|------|--------|
| 页面数 | 6页面 | 3页面(Dashboard+回测+设置) | <3 |
| 设计系统 | 全套Token+GlassCard | 基础组件 | 无设计系统 |
| API对接 | 20+端点 | 10端点(含mock) | <10 |

**API并行策略**（Round 2 frontend要求）：
- Sprint 1.2期间arch+frontend共同定义OpenAPI schema
- 前端用MSW(Mock Service Worker)做mock开发
- 每Sprint结束做一次前后端联调

---

## Phase 1C: AI+ML+实盘 [10周, 4步渐进]

**新启用**: ml (全员9人)

### Round 2共识：4步渐进式上线（替代原"大爆炸"模式）

```
1C-pre:   数据层准备（ML宽表+AI数据接口）         [1周]
1C-alpha: ML因子引擎上线 + 验证                    [2周]
1C-beta1: GP+暴力枚举引擎上线 + 验证               [2周]
1C-beta2: LLM因子引擎上线 + 验证                   [2周]
1C-gamma: 实盘切换                                  [3周]
```

每步有明确的**进入条件 → 验证指标 → 回滚条件**。

### 1C-pre: 数据层准备 [1周]

- ML特征宽表构建 (data+ml)
- AI引擎数据接口定义 (data+arch)
- 进入条件: Sprint 1.3数据源扩展完成

### 1C-alpha: ML因子引擎 [2周]

- BaseMLPredictor基类(接口在Sprint 1.2已定义) (ml)
- AStockLGBMPredictor + WalkForward训练 (ml)
- RandomForest baseline (ml)
- **验证**: ML因子IC均值>0.02, WF-OOS Sharpe报告
- **进入条件**: 数据层准备完成
- **回滚**: IC不达标则回退等权

### 1C-beta1: GP+暴力枚举 [2周] ← Round 1: ml评估Sprint 1.6需拆分

- 暴力枚举引擎(+剪枝) (arch+factor)
- GP遗传编程引擎(岛屿模型, 种群≤300) (ml+factor)
- **测试要求**（Round 1 qa要求）: GP确定性测试(种子固定)、因子去重阈值验证
- **进入条件**: 1C-alpha验证通过+稳定运行≥5天
- **验证**: GP/暴力产出因子≥3个通过IC Gate

### 1C-beta2: LLM因子引擎 [2周]

- Idea/Factor/Eval三Agent工程实现 (ml+factor)
- 沙箱安全执行环境 (ml)
- DeepSeek API集成+CostTracker (ml)
- **测试要求**: 沙箱安全测试(10个恶意代码全部拦截)
- **进入条件**: 1C-beta1验证通过
- **验证**: 1轮完整LLM挖掘流程跑通, 成本记录正确

### 1C-gamma: 实盘切换 [3周]

- miniQMT对接（Mac M1上运行Windows VM, arch自主处理工程细节§3.6.1）
- BaseBroker ABC + MiniQMTBroker (arch)
- **渐进式放量**（Round 2 risk要求）: 1手→5手→10%→50%→全仓
- 影子模式(下单但不执行, 对比SimBroker) → 小额实测 → 正式切换
- **进入条件**: 全部因子引擎稳定 + Paper Trading毕业标准达标
- **回滚演练**: 切换前48小时内验证实盘→Paper Trading回退全链路
- 策略版本管理(JSONB+回滚) (arch)

---

## 开源工具引入计划

### 第一批（Sprint 1.2-1.3，立刻可用）

| 工具 | 用途 | 替代什么 |
|------|------|---------|
| TA-Lib | 130+技术指标(RSI/MACD/KDJ/ATR等) | 手动移植算子 |
| Alphalens | 因子分析(IC/分组/换手/信息系数) | 自写FactorAnalyzer |
| QuantStats | 绩效分析+HTML报告 | 自写performance指标 |
| Qlib Alpha158 | 158个因子公式导入(只提取公式不装框架) | — |

### 第二批（Sprint 1.6-1.8，ML阶段）

| 工具 | 用途 |
|------|------|
| DEAP | GP遗传编程框架 |
| SHAP | LightGBM可解释性 |
| Numba | 因子计算JIT加速 |
| RD-Agent | 参考Co-STEER模式 |

### 第三批（Phase 1B组合优化）

| 工具 | 用途 |
|------|------|
| Riskfolio-Lib | HRP/风险平价/CVaR，24种风险度量 |

### Phase 3+远期（BACKLOG）

Kronos/PyTorch Geometric/FinRL/Polars

### GitHub项目利用计划

| 项目 | 时间 | 用法 |
|------|------|------|
| Qlib Alpha158 | Sprint 1.3 | 提取公式跑IC，不装框架 |
| PandaFactor | Sprint 1.3 | TA-Lib替代，PandaFactor做参考 |
| RD-Agent Co-STEER | Sprint 1.6-1.7 | 参考Research→Dev→Feedback循环 |
| Kronos | Phase 3/4 | 零样本K线信号 |
| QuantsPlaybook | 随时 | 策略研究参考 |

---

## 毕业标准

### Paper Trading毕业标准

| 指标 | 标准 | 来源 |
|------|------|------|
| 运行时长 | ≥ 60个交易日 | CLAUDE.md |
| Sharpe | ≥ 0.90 (= 回测1.29 × 70%) | 用户确认 |
| MDD | **≤ min(回测MDD×1.5, 35%)** | Round 2共识(D) |
| MDD计算方式 | 日频净值，不得用周频 | Round 2 factor要求 |
| 滑点偏差 | < 50% | 用户确认 |
| 链路完整性 | 信号→执行→归因 全链路无中断 | CLAUDE.md |
| 低波动延长 | 若60天内CSI300 20d波动率始终<15%年化，延长至90天 | Round 2折中(D) |

### 实盘熔断规则（Round 2共识E）

| 条件 | 动作 |
|------|------|
| 滚动60日Sharpe < 0.3 | 自动降仓50% |
| 滚动60日Sharpe < 0.3 持续20天 | 暂停实盘，回退Paper Trading复查 |

### Phase 1整体毕业标准

| 指标 | 标准 |
|------|------|
| 回测Sharpe(WF-OOS) | **≥ 1.4** (Round 2共识E, 给衰减留安全边际) |
| MDD | < 25% |
| 因子数 | ≥ 15个活跃因子(每个OOS IC>0.02, pairwise corr<0.5) |
| AI挖掘 | 至少1轮完整挖掘流程跑通 |
| 实盘 | miniQMT渐进放量测试通过 |
| 前端 | 6+页面可用 |

---

## 风险预判

| 风险 | 影响 | 缓解 | 来源 |
|------|------|------|------|
| Sprint 1.0延期 | GPA暂停，1B推迟 | GPA止损条件 | arch+risk |
| OOS Sharpe大幅衰减 | 回测目标1.4不可达 | Sprint 1.2a后立即测量并修订 | quant |
| miniQMT Windows VM不稳定 | 实盘延期 | 先Paper Trading跑满60天 | arch |
| LightGBM不优于等权 | ML方案失败 | RF作backup, 因子裁剪 | ml |
| GPA因子IC不达标 | 缺少质量维度 | 备选accrual_cf, roe_stability | factor |
| 16GB内存约束 | GP/ML训练慢 | 串行调度+种群限制 | ml+arch |
| 前端API未ready | 前端被阻塞 | MSW mock+接口先行 | frontend |
| Sprint 1.6工期 | AI引擎延期2-3周 | 已拆为beta1+beta2 | ml |

---

## 三轮讨论决议记录

| 议题 | Round 1发现 | Round 2决议 |
|------|------------|------------|
| A: Sprint 1.2超载 | quant+arch | 拆为1.2a(2周)+1.2b(2周) |
| B: Sprint 1.6超载 | ml+qa | 拆为beta1(2周)+beta2(2周) |
| C: miniQMT Windows | arch | Mac VM方案, arch §3.6.1自主处理 |
| **D: MDD毕业标准** | quant+risk | **min(回测×1.5, 35%)**, 低波段延长至90天 |
| **E: 实盘衰减** | strategy | **两步衰减模型, 回测≥1.4, 实盘Sharpe<0.3熔断** |
| F: 1C风险集中 | risk | — |
| **G: 1C拆分** | risk | **4步渐进(pre/alpha/beta1+2/gamma)** |
| H: 前端工作量 | frontend | Sprint 1.4从2周→3周, 1.9拆分 |
| I: 数据源工时 | data | Sprint 1.3从1周→2周 |
| **J: GPA提前** | factor | **提前到1.0-1.1, 附4个前提条件** |
| K: 压力测试 | qa | 提前到Sprint 1.2a后 |
| L: 1.6测试要求 | qa | 每个子阶段补测试要求 |
| M: OOS衰减 | quant | Sprint 1.2a后立即OOS基线测量 |
