# QuantMind V2 — 技术决策快查表

> 新会话恢复上下文时一眼看完整个决策历史。每个技术决策追加一行。
> 从 CLAUDE.md 迁移，原始位置已替换为指向本文件的引用。

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
| reversal_20补算 | 2021-01缺失20天补算，Sharpe 1.019→1.03 | KEEP | Sprint 1.4a |
| LightGBM上线标准 | 上线: p<0.05+Sharpe≥1.10+6红线; 优秀: Sharpe≥1.30+p<0.01 | 用户确认 | Sprint 1.4b |
| LightGBM-5feat默认 | OOS Sharpe=0.869,p=0.073,同期基线=-0.125,3项红线FAIL | NOT JUSTIFIED | Sprint 1.4b |
| LightGBM-5feat-optuna | OOS IC +2.5%但ICIR -1.7%,与默认超参无显著差异 | 选默认超参 | Sprint 1.4b |
| SHAP特征筛选 | 5基线完胜17特征(IC 7.06% vs 4.78%),ML特征引入噪声 | KEEP 5基线 | Sprint 1.4b |
| ML特征12个 | best_iter=2(噪声阻止学习),SHAP高但OOS差 | Reverted | Sprint 1.4b |
| 基本面delta特征(7个) | OOS IC 0.0439 vs 基线0.0823(下降46.7%),best_iter=6 | Reverted | Sprint 1.5 |
| **基本面方向彻底关闭** | **10种方式穷举：8 FAIL+1 MARGINAL+1 SKIP，证据充分** | **方向关闭** | Sprint 1.5b |
| Rolling ensemble | Sharpe=0.972(基线对比待清理),概念验证通过 | Pending验证 | Sprint 1.5 |
| 因子生命周期状态机 | factor_lifecycle表+监控脚本+5Active因子健康 | KEEP | Sprint 1.5 |
| Forecast分析师预期因子 | 全样本60月t<1.0，中性化后归零，LightGBM FAIL | 方向关闭 | Sprint 1.6 |
| 信号平滑Inertia(0.7σ) | Sharpe=1.172但p=0.09(Bonferroni后不显著) | 影子PT观察 | Sprint 1.6 |
| VWAP+RSRS单因子Gate | vwap t=-3.53, rsrs t=-4.35, 双PASS | Reserve池 | Sprint 1.6 |
| VWAP+RSRS LightGBM增量 | 无增量(IC不提升) | 无增量 | Sprint 1.6 |
| Rolling ensemble | Sharpe+13.6%但p=0.35 | Reserve | Sprint 1.6 |
| **7因子等权(+vwap+rsrs)** | **Sharpe=0.902<基线1.028, p=0.652, 换手+207%, 每年均差** | **Reverted** | Sprint 1.6 |
| DB连接P1修复 | 13脚本统一化 | KEEP | Sprint 1.6 |
| Drawdown P0修复 | qa 4/4 PASS | KEEP | Sprint 1.6 |
| 方案B execute拆分 | qa 5/5 PASS | KEEP | Sprint 1.6 |
| ic_decay交易日修复 | bisect_right偏移，国庆/春节测试PASS | KEEP | Sprint 1.9 |
| health→signal依赖链 | Redis gate+P0告警，4场景测试 | KEEP | Sprint 1.9 |
| BaseBroker ABC统一 | 3 Broker继承+get_broker工厂 | KEEP | Sprint 1.9 |
| 仓位偏差3指标 | mean_dev+max_dev+cash_drag替代单一均值 | KEEP | Sprint 1.9 |
| VWAP+RSRS入Reserve | 单因子Gate PASS但月度等权无增量 | Reserve | Sprint 1.9 |
| v1.2(K=3)不升级 | p=0.657不显著+60天PT重计时代价 | NOT JUSTIFIED | Sprint 1.9 |
| 每日风控(非仅调仓日) | signal阶段Step1.6新增L1-L4日终评估 | KEEP | Sprint 1.10 |
| PreTradeValidator 5项 | 单笔<15%/价格容差/行业/日亏/集中度 | KEEP | Sprint 1.10 |
| 现金缓冲3% | 权重总和0.97，整手约束余量+紧急调仓弹性 | KEEP | Sprint 1.10 |
| 波动率regime缩放 | 对数收益率+中位数baseline+clip[0.5,2.0] | KEEP | Sprint 1.10 |
| 开盘跳空预检 | 单股>5%P1/组合>3%P0，PT只告警 | KEEP | Sprint 1.10 |
| PT毕业标准5→9项 | +fill_rate/slippage/TE/gap_hours | KEEP | Sprint 1.10 |
| 自相关调整Sharpe | Lo(2002) ρ>0惩罚，月度策略可能高估 | KEEP | Sprint 1.10 |
| SlippageConfig市值分层 | k_large=0.05/k_mid=0.10/k_small=0.15 + direction sell_penalty | KEEP | Sprint 1.11 |
| volume_impact默认模式 | SimBroker slippage_mode="volume_impact" | KEEP | Sprint 1.11 |
| **volume_impact基线重跑** | **Sharpe 1.03→0.39, MDD -39.7%→-58.4%, 年化25%→8%** | **⚠️需用户决策** | Sprint 1.11 |
| PT心跳watchdog | 每日20:00检测+P0告警 | KEEP | Sprint 1.11 |
| config_guard入PT Step 0.5 | v1.1配置一致性强制检查 | KEEP | Sprint 1.11 |
| RSRS事件型策略(R1) | t=-4.35最强, weekly, 优先级1, 待1.12回测 | Pending验证 | Sprint 1.11 |
| **RSRS单因子weekly策略** | **Sharpe=0.15, MDD=-45%, 换手37倍, CI包含0** | **NOT JUSTIFIED** | Sprint 1.12 |
| **RSRS单因子monthly策略** | **Sharpe=0.28, MDD=-43%, CI包含0, 2024亏-12.7%** | **NOT JUSTIFIED** | Sprint 1.12 |
| **HMM 2-state regime detector** | **Sharpe=1.02<Vol Regime 1.08, MDD=-40.6%>Vol Regime -27.6%, 三方案最差** | **NOT JUSTIFIED** | Sprint 1.12 |
| **AI闭环三步走** | **Step1 PT赚钱→Step2 GP最小闭环→Step3完整AI闭环，GP-first不上LLM** | **KEEP(战略)** | Sprint 1.12 |
| **RD-Agent** | **借鉴思想(知识森林/联合优化/Co-STEER)，不直接集成(依赖Azure/不支持A股特有约束)** | **借鉴不集成** | Sprint 1.12 |
| **Warm Start GP** | **用现有5因子做模板初始化GP，结构约束进化(arxiv 2412.00896)，优于随机DEAP** | **KEEP(Step2)** | Sprint 1.12 |
| **Qlib** | **不集成为执行骨架(A股整手/涨跌停不支持)，但用Alpha158算子集做FactorDSL参考** | **算子参考** | Sprint 1.12 |
| **shadcn/ui跳过** | **Tailwind v4与shadcn/ui有兼容问题，用自定义Tailwind组件(GlassCard/MetricCard/Button)替代** | **KEEP** | Sprint 1.13 |
| **FactorClassifier决策树** | **规则简单透明(4条主规则+边界降权)，不用ML分类。R1明确建议保持简单规则** | **KEEP** | Sprint 1.13 |
| **StrEnum替代str+Enum** | **Python 3.11+ StrEnum更简洁，但Pyright有版本兼容问题(false positives)** | **KEEP(接受Pyright噪音)** | Sprint 1.13 |
| **RegimeModifier三级fallback** | **HMM→VolRegime→常数1.0，生产安全不崩溃** | **KEEP** | Sprint 1.13 |
| **CompositeStrategy不拆资金池** | **R3结论:100万下不拆分，Modifier只调权重不选股** | **KEEP** | Sprint 1.13 |
| **滑点三因素模型** | **tiered_base(大3/中5/小8bps)+impact(Bouchaud)+overnight_gap(R4跳空)，替代固定5bps** | **KEEP** | Sprint 1.14 |
| **BruteForce 44模板** | **从Alpha158+DESIGN_V5 §4.2提取，覆盖4类(价量/流动性/资金流/基本面)** | **KEEP(Engine1基线)** | Sprint 1.14 |
| **AST去重L1-L3** | **L1规范化+SHA256 > L2 dump比较 > L3 Spearman相关，比字符串去重准确率高81%(R2)** | **KEEP** | Sprint 1.14 |
| **Gate Pipeline G1-G5自动+G6-G8半自动** | **FAIL不中断继续输出完整报告，BH-FDR动态阈值M=74→t≈3.27** | **KEEP** | Sprint 1.15 |
| **WebSocket python-socketio** | **AsyncServer+ASGI挂载，WS优先+REST轮询fallback** | **KEEP** | Sprint 1.15 |
| **structlog JSON日志** | **dev(ConsoleRenderer)/prod(JSONRenderer)自动切换，RotatingFileHandler 10MB×7** | **KEEP** | Sprint 1.15 |
| **CompositeStrategy+RegimeModifier** | **模拟数据MDD改善21.6%(>5%阈值)，真实数据验证待DB接入** | **Pending验证** | Sprint 1.15 |
