# QuantMind V2 — 项目全面体检报告

> 日期：2026-03-27
> 审查人：Team Lead
> 触发：Sprint 1.11完成后，用户要求系统性审查
> 方法：11个设计文档 vs 实际代码，前沿研究，miniQMT验证

---

## 一、执行摘要

| 维度 | 状态 | 风险等级 |
|------|------|---------|
| Phase 0 (PT运行) | 65-70%完成 | 🟡 中 |
| Phase 1 (AI闭环) | 设计100%, 代码0% | 🔴 高 |
| 因子覆盖 | 5/34 (14.7%) | 🟡 中 |
| 前端 | 1/12页面 | 🔴 低优先 |
| 风控 | L1-L4+PreTrade+Watchdog | 🟢 良好 |
| 数据质量 | 日检+备份+巡检 | 🟢 良好 |
| **滑点模型校准** | **Sharpe 1.03→0.39** | **🔴 最高** |

**最紧急发现**: volume-impact滑点模型揭示v1.1基线严重高估。k系数校准是当前最高优先事项。

---

## 二、⚠️ 紧急事项：滑点模型k系数校准

### 问题
Sprint 1.11集成volume-impact模型后，v1.1回测Sharpe从1.03暴跌至0.39。原因是市值分层k系数(DEV_BACKTEST_ENGINE.md §4.5设计值):
- k_large=0.05 (500亿+)
- k_mid=0.10 (100-500亿)
- k_small=0.15 (<100亿)

这些值来自设计文档，未经A股实际数据校准。v1.1 Top15组合偏小盘，k_small=0.15对月度调仓可能偏高。

### 可落地方案

**方案1: PT实际数据校准（推荐）**
- 文件: `backend/engines/slippage_model.py`
- 方法: 收集PT实际成交的signal_price vs executed_price偏差，反向推算k
- 数据需求: 至少20个交易日的成交数据（约Day 23，4月底可用）
- 工作量: 1天
- 预期: 校准后的k值更真实，Sharpe在0.39和1.03之间

**方案2: 学术文献参数（快速）**
- Almgren-Chriss (2001)临时冲击: η=0.01-0.05（A股流动性好于美股小盘）
- 如果k_small从0.15降到0.08，Sharpe预计回升到0.6-0.8
- 工作量: 2小时（只改param_defaults.py默认值）

**方案3: 按ADV比例动态调整（中期）**
- 文件: `backend/engines/slippage_model.py`
- 当前: k固定按市值分档
- 改进: k = k_base × (trade_size / ADV_20)^0.5，参与率越高k越大
- 这更符合Kyle(1985)模型——冲击与参与率的平方根成正比
- 工作量: 2天

**建议执行顺序**: 方案2（快速止血）→ 方案1（数据积累后校准）→ 方案3（中期优化）

---

## 三、设计文档 vs 代码差距分析（Top 10可落地项）

### 3.1 数据服务集中化（P0, 2天）

**设计文档**: DEV_BACKEND.md §4.3
**现状**: 数据拉取散落在scripts和daily_pipeline中，无统一Service
**改动**:
- 新建 `backend/app/services/data_service.py`
- 封装Tushare/AKShare调用、限速、断点续传、降级策略
- 当前数据拉取代码从scripts移到Service
**预期**: 数据拉取可靠性提升，故障恢复更快

### 3.2 UniverseFilter 8层过滤器（P1, 1天）

**设计文档**: DEV_BACKTEST_ENGINE.md §4.5
**现状**: 过滤逻辑分散在signal_engine.py中
**改动**:
- 新建 `backend/engines/universe_filter.py`
- 8层显式pipeline: 停牌→ST→上市日→流动性→市值→行业→涨跌停→自定义
- signal_engine.py调用UniverseFilter
**预期**: 选股宇宙更干净，减少噪声

### 3.3 资金流因子接入（P1, 3天）

**设计文档**: DESIGN_V5 §4.2 类别③
**现状**: 34个设计因子只实现5个，北向资金/大单/融资融券全部缺失
**改动**:
- `backend/app/data_fetcher/tushare_fetcher.py` — 新增hk_hold/moneyflow接口
- `backend/engines/factor_engine.py` — 新增calc_north_flow_20/calc_big_order_ratio
- 数据检查: TUSHARE_DATA_SOURCE_CHECKLIST.md已有moneyflow接口文档
**预期**: 新增2-3个独立因子维度，可能发现正交Alpha

### 3.4 Walk-Forward验证框架（P1, 3天）

**设计文档**: DEV_BACKTEST_ENGINE.md §4.9
**现状**: `backend/engines/walk_forward.py`存在但未集成到回测脚本
**改动**:
- `scripts/run_backtest.py` — 新增--walk-forward模式
- 实现24月训练/6月验证/12月测试滚动窗口
**预期**: OOS验证更严格，减少过拟合风险

### 3.5 压力测试场景（P1, 2天）

**设计文档**: DESIGN_V5 §8.3
**现状**: 无独立压力测试脚本，风控只有L1-L4熔断
**改动**:
- 新建 `scripts/stress_test.py`
- 5个历史场景: 2015股灾/2016熔断/2020疫情/2024踩踏/2025关税
- 注入自定义行情到回测引擎（BacktestConfig已预留接口）
**预期**: 量化极端场景下的MDD和恢复时间

### 3.6 ExecutionSimulator升级（P2, 5天）

**设计文档**: DEV_BACKTEST_ENGINE.md §4.6
**现状**: SimpleBacktester (Step 1) 已实现，ExecutionSimulator (Step 2) 缺失
**改动**:
- 新建 `backend/engines/execution_simulator.py`
- 包含: ConstraintChecker + CostModel + SlippageModel + PortfolioTracker
- 替代SimpleBacktester作为主回测引擎
**预期**: 更真实的执行模拟，成交量约束、部分成交处理

### 3.7 因子生命周期监控（P1, 1天）

**设计文档**: CLAUDE.md 因子生命周期状态机
**现状**: `factor_lifecycle`表已创建，监控逻辑存在但未自动化
**改动**:
- 在daily_pipeline中新增因子健康检查任务
- 因子IC低于阈值→自动告警→连续4周→状态从active→warning→critical
**预期**: 因子失效能及时发现

### 3.8 通知模板补全（P2, 0.5天）

**设计文档**: DEV_NOTIFICATIONS.md §4
**现状**: 19个模板已实现，设计25+个
**改动**: 补充回撤预警/回测完成/因子告警等6个模板
**预期**: 告警覆盖率从76%提升到100%

### 3.9 参数系统补全（P2, 2天）

**设计文档**: DEV_PARAM_CONFIG.md
**现状**: ~50个参数注册，设计220+个
**改动**: 批量注册缺失参数到param_defaults.py，重点是factor/signal/risk模块
**预期**: 所有参数可通过API查询和修改

### 3.10 缺失的设计文档

当前有11个设计文档，但缺少以下领域的文档：

| 缺失文档 | 覆盖范围 | 建议 |
|---------|---------|------|
| DEV_DATA_PIPELINE.md | 数据拉取→清洗→入库→质检全链路 | 需新建 |
| DEV_MONITORING.md | 系统监控/日志/告警/可观测性 | 需新建 |
| DEV_DEPLOYMENT.md | Windows部署/Task Scheduler/灾难恢复SOP | 需新建 |
| DEV_STRESS_TEST.md | 压力测试场景/方法/预期/通过标准 | 需新建 |

---

## 四、前沿研究待补充（研究agent运行中）

研究agent正在搜索以下维度：
1. A股市场冲击成本实证参数
2. 2024-2025因子投资前沿
3. 组合构建非线性方法
4. 执行优化算法
5. 风险管理前沿
6. ML/AI最新方法（Qlib/Transformer）
7. 基础设施最佳实践
8. 微信公众号/知乎中文资源

研究结果将追加到本文档第五章。

---

## 五、前沿研究关键发现（可落地）

### 5.1 ⚠️ k系数偏高3-10x（P0，最紧急）

**来源**: Bouchaud et al. (2018) square-root law; Almgren et al. (2005); 上交所市场质量报告2023

**问题**: 当前公式 `impact = k * sqrt(Q/V) * 10000` 中k_small=0.15，对典型交易(6.7万元/5000万日成交额)产生**55 bps冲击**。而学术标准公式 `I = Y * σ * sqrt(Q/V)` 中Y≈1.0, σ≈2%，同样参数只产生**7 bps**。上交所实测10万元交易冲击约15-16 bps。

**方案**: 重构公式，加入σ(日波动率)项:
```python
# 当前: impact = k * sqrt(participation_rate) * 10000
# 修正: impact = Y * sigma_daily * sqrt(participation_rate) * 10000
# Y_large=0.8, Y_mid=1.0, Y_small=1.5
# sigma_daily从volatility_20(已有因子)获取
```
- 文件: `backend/engines/slippage_model.py`
- 工作量: 4-6小时（含重跑回测）
- 预期: Sharpe从0.39回升到0.75-0.90（真实区间）

### 5.2 HRP非线性组合优化（P1）

**来源**: Lopez de Prado (2016); Return-Adjusted HRP (Noguer i Alonso, 2025, SSRN)

**现状**: 等权在9种线性方法中最优(LL-018)，非线性未探索
**方案**: Hierarchical Risk Parity不需要收益率预测，不需要矩阵求逆
- 文件: `backend/engines/portfolio_optimizer.py`（新建）
- 依赖: riskfolio-lib（已在技术栈中）
- 工作量: 8-12小时
- 预期: Sharpe提升0.05-0.15，主要通过MDD降低

### 5.3 HMM Regime Detection（P1）

**来源**: QuantStart (2024); hmmlearn库

**现状**: Sprint 1.10的vol_regime用单特征启发式
**方案**: 3-state HMM(牛/熊/震荡)替换启发式
- 文件: `backend/engines/regime_detector.py`（新建）
- 工作量: 12-16小时
- 预期: MDD降低5-10个百分点（-39.7%→-30~-35%）

### 5.4 日内因子（日频近似版）（P1）

**来源**: 国盛证券2024-2025量化策略展望

**发现**: 2024-2025 A股最强alpha来自日内特征(minute_turn_std IR=2.64, minute_volatility IR=2.03)。但需分钟数据。
**可行近似**: daily_turn_std（日频换手率稳定性）可从现有数据计算，预期IR 1.5-2.0
- 文件: `backend/engines/factor_engine.py` 新增 `calc_turnover_stability_20()`
- 工作量: 4小时
- 预期: 如果通过t>2.5 Gate，可能替换弱因子

### 5.5 VWAP执行优化（P1）

**方案**: 月度调仓拆成30分钟TWAP窗口，优先大盘股
- SimBroker用daily VWAP(=amount/volume)替代open作为成交价
- 文件: `backend/engines/backtest_engine.py` SimBroker + `paper_broker.py`
- 工作量: 6小时
- 预期: 每次调仓减少3-8 bps，年化36-96 bps

### 5.6 因子拥挤度监控（P2）

**来源**: MSCI Integrated Factor Crowding Model; Hua & Sun (2024)

**方案**: 4维度拥挤度指标（估值离散度/收益相关性/因子反转/异常换手）
- 文件: `backend/engines/crowding_monitor.py`（新建）
- 工作量: 8小时
- 预期: 因子衰减早期预警

### 5.7 Qlib DoubleEnsemble（Phase 1参考）

**发现**: Qlib基准显示DoubleEnsemble(IR=1.343)显著优于单LightGBM(IR=1.016)
**启示**: Phase 1 ML策略应直接用DoubleEnsemble而非独立LightGBM

---

## 六、Sprint 1.12建议（可落地优先）

| 优先级 | 项目 | 预计工作量 | 预期收益 | 文件 |
|--------|------|-----------|---------|------|
| **P0** | **k系数重构(加σ项)+重跑基线** | **6小时** | **Sharpe 0.39→0.75-0.90** | slippage_model.py |
| P0 | RSRS事件型策略SimBroker验证 | 2天 | 验证卫星策略 | base_strategy.py |
| P1 | VWAP执行优化(TWAP窗口) | 6小时 | 年化-36~96 bps | backtest_engine.py |
| P1 | HMM Regime Detection | 2天 | MDD降5-10pp | regime_detector.py(新) |
| P1 | 资金流因子(north_flow+big_order) | 3天 | 新正交Alpha | factor_engine.py |
| P1 | daily_turn_std因子 | 4小时 | 潜在IR 1.5-2.0 | factor_engine.py |
| P1 | 压力测试脚本 | 2天 | 量化极端风险 | stress_test.py(新) |
| P1 | Walk-Forward集成 | 3天 | 更严格OOS | run_backtest.py |
| P2 | HRP组合优化 | 1.5天 | Sharpe+0.05-0.15 | portfolio_optimizer.py(新) |
| P2 | 拥挤度监控 | 1天 | 因子衰减预警 | crowding_monitor.py(新) |
| P2 | 前端MVP | 5天 | 可视化 | frontend/ |

---

*本文档将随前沿研究结果持续更新。*
