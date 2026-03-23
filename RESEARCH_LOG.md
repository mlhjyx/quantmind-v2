# RESEARCH_LOG.md — 研究记录

> TEAM_CHARTER §9.4.3 格式。所有研究发现记录于此。

---

## 2026-03 研究记录

### [quant] Deflated Sharpe Ratio评估基线策略
- **来源**: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio"
- **核心方法**: 考虑多重检验偏差，校正因尝试多个策略导致的Sharpe膨胀
- **对项目价值**: DSR=0.591("可疑")，说明Sharpe 1.037部分来自数据挖掘。Paper Trading是唯一验证手段
- **实现难度**: 低（已实现在engines/dsr.py）
- **状态**: ✅ 已实现，Sprint 1.2a

### [quant] BH-FDR多重检验校正
- **来源**: Benjamini & Hochberg (1995); Harvey, Liu & Zhu (2016) "...and the Cross-Section of Expected Returns"
- **核心方法**: 用累积测试总数M（非当批N）做FDR控制，防止因子挖掘"碰运气"
- **对项目价值**: 64个因子测试中控制假阳性率，t>2.5硬下限+BH-FDR校正
- **实现难度**: 低（已实现在config_guard.py）
- **状态**: ✅ 已实现，Sprint 1.3b

### [quant] Paired Bootstrap检验因子增量
- **来源**: Ledoit & Wolf (2008), "Robust Performance Hypothesis Testing"
- **核心方法**: 对同一股票池同一时段，bootstrap 5因子vs6因子IC差异的分布
- **对项目价值**: 发现v1.2(+mf_divergence)增量仅+0.10%(p=0.387)——NOT JUSTIFIED。防止了一次无效版本切换
- **状态**: ✅ 已使用，Sprint 1.3a

### [risk] 波动率自适应熔断阈值
- **来源**: Engle (1982) ARCH/GARCH框架; 研究报告#1课题2
- **核心方法**: 阈值×clip(portfolio_vol/baseline_vol, 0.5, 2.0)，高波放宽低波收紧
- **对项目价值**: CSI300 2021-2025波动率中位数14.85%作为基线。解决静态阈值"牛市频繁误触/熊市反应太慢"
- **状态**: ✅ 已实现，Sprint 1.2a

### [risk] L3日频触发方案5阈值对比
- **来源**: A股历史急跌事件回测(2015/2016/2020/2024)
- **核心方法**: 5个阈值(-3%/-5%/-6%/-7%/-10%)对比触发次数/误杀率/漏报率
- **对项目价值**: 确定5d<-7% OR 20d<-10%为最优，年均触发2次。-5%误触发严重(年均3.8次)
- **状态**: ✅ 参数已确认，编码实现中

### [strategy] 同框架多策略在A股不可行
- **来源**: 5个候选策略全部SimBroker验证失败
- **核心发现**: 因子正交≠选股正交(LL-009)，proxy回测≠SimBroker回测(LL-011)。同样用5因子等权框架的子策略与基线corr=0.49-0.78
- **对项目价值**: 降MDD不能靠同框架多策略捷径。正确路径：因子分散化+timing+风控
- **状态**: 📝 记录，V8.0方向转型为基线优化

### [alpha_miner] 资金流因子虚假alpha模式
- **来源**: Batch 6/8中性化验证
- **核心发现**: 资金流因子天然与市值/波动率高相关。big_small_consensus原始IC=12.74%中性化后-1.0%。必须做中性化验证(LL-014)
- **对项目价值**: 避免纳入虚假alpha因子污染组合
- **状态**: 📝 规则已写入CLAUDE.md

### [alpha_miner] PEAD效应在A股逐年增强
- **来源**: Batch PEAD earnings_surprise_car IC验证
- **核心发现**: A股PEAD IC从2021年3.57%递增至2025年7.50%，IR从0.46升至1.07。中性化后IC反而更高。与现有因子corr<0.11
- **对项目价值**: 全项目最干净的新维度因子，已通过factor+quant联合审批
- **状态**: ✅ PASS，待6因子组合回测

### [factor] 因子池22因子→5级评级
- **来源**: FACTOR_HEALTH_REPORT.md全面盘点
- **核心发现**: 5 Active / 10 Reserve / 2 Watch / 5 Deprecated。5个Deprecated停止计算省23%算力
- **对项目价值**: 因子池管理从"只加不减"转为主动维护
- **状态**: ✅ 报告完成，Deprecated待arch实施

### [strategy] 交易执行优化——100万规模TWAP/VWAP不需要
- **来源**: 研究报告#2课题1
- **核心发现**: 100万/15只=6.5万/只，A股单票日均成交额5000万+，参与率0.1%，零市场冲击。唯一值得做的是封板补单(次日补1次)
- **对项目价值**: 避免过度工程化执行层。TWAP/VWAP等资金>500万后再做
- **状态**: 📝 记录，封板补单Sprint 1.3b实现

### [strategy] 分层排序的熊市防御特性 → Sprint 1.8 LightGBM特征参考
- **来源**: Sprint 1.3b分层排序回测方案A
- **核心发现**: 方案A(分层5F)在2022年Sharpe=+0.15 vs 基线-0.40，MDD=-16% vs -22%。分层排序有明确的熊市防御特性——先筛流动性再选反转/低波，在下跌市中自动偏向防御型股票
- **对项目价值**: LightGBM特征中加入"市场状态"指标（MA20/MA60比率、波动率水位、行业动量分散度），让模型在熊市自动学到类似分层的逻辑
- **状态**: 📝 记入Sprint 1.8特征工程参考
