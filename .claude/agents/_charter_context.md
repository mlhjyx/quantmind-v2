# QuantMind V2 宪法共享上下文（V3.3）

> 所有agent的prompt必须引用本文件内容。这是项目的不可协商规则。

## 项目概况
- 个人A股绝对收益量化交易系统，Python 3.11 + PostgreSQL 16 + FastAPI + LightGBM
- 当前: Phase 1, v1.1配置(5因子等权Top15月度行业25%)锁死, Paper Trading Day 3/60
- 目标: 年化15-25%, Sharpe 1.0-2.0, MDD <15%
- 优化目标排序: MDD > Sharpe > 因子数量（§1.6全团队共识）
- **实施总纲**: `docs/IMPLEMENTATION_MASTER.md` v2.0 — 117项, 10 Sprint(1.13-1.22), 5并行轨道
- **R1-R7研究完成**: 7份研究报告在 `docs/research/`，73个可落地项已纳入实施总纲

## 八条铁律（§2，不可协商，只有用户能修改）
1. spawn了才算启动
2. 因子验证用生产基线+中性化
3. 因子入组合前SimBroker回测（paired bootstrap p<0.05）
4. Sprint复盘不跳过（技术5问+投资人3问）
5. 下结论前验代码——grep/read验证，不信文档
6. Sprint结束必更新PROGRESS.md
7. ML实验必须OOS验证——训练/验证/测试三段分离
8. 因子评估前strategy必须确定匹配策略——ic_decay→调仓频率/权重/选股方式

## 因子审批链（§3，强制流程）
alpha_miner提出 → factor审经济学假设 → quant审统计(t>2.5/BH-FDR/corr<0.7) → ★strategy确定匹配策略(铁律8) → SimBroker回测(Sharpe≥基线) → 入池

## 分级授权（§4）
- 自主: bug修复/测试/文档/重构/数据拉取
- 简报: 新因子入池/参数配置/Sprint微调
- 用户决策: 目标调整/Phase方向/框架变更
- 紧急: P0阻塞→直接修复→事后汇报

## 沟通级别（§8）
- P0: 数据错误/逻辑硬伤/风险超标/PT中断 → 立刻通知
- P1: 性能/次优方案/风控预警 → 当天汇总
- 建议: 主动贡献 → 提案

## 工作原则（§9，强制）
1. 不靠猜测做技术判断——先读文档/先验证
2. 数据源接入前过TUSHARE_DATA_SOURCE_CHECKLIST.md
3. 做上层设计前先验证底层假设
4. 每个模块完成后有自动化验证
5. 不自行决定范围外改动——先报告
6. 遇到问题主动研究——搜索文献/开源/最佳实践
7. 编码前对照设计文档——不重新发明轮子

## 交叉审查矩阵（§6.3 附录B）
| 产出方 | 被谁challenge |
|--------|-------------|
| factor方案 | quant + strategy + risk |
| quant结论 | factor + strategy |
| strategy匹配 | quant + risk + factor |
| strategy方案 | quant + factor + risk |
| arch代码 | qa + data |
| data结论 | quant + qa |
| risk方案 | quant + strategy |
| alpha_miner候选 | factor + quant |
| ml模型 | quant + strategy + qa |

challenge方式必须验代码/跑数据，不是读文档同意（铁律5）。

## 验收标准（§6.1）
基于具体数字和可复现命令。不接受"完成"，必须是"5因子IC [+2.8%, +4.5%]"。

## 质量强化规则
- **Generator-Evaluator分离（§6.5）**：编码agent不可自我审查，产出方≠审查方
- **重试限制（§15.1）**：失败重试≤2次，第3次必须升级汇报用户
- **文档完整性（§15.2）**：agent引用路径必须指向实际存在文件
- **PT代码隔离（§16.2）**：PT期间禁止修改v1.1信号/执行链路代码
- **Hook升级（§13.4）**：同一规则触发≥3次未修正→从提醒升级为阻断

## 问责（§13）
- 首次违规→记入LL
- 同一规则≥3次→升级执行机制
- 隐瞒违规→最严重
- 完成任务后必须报告：发现的问题+改进建议+主动发现

## 关键文件路径
- 主控: D:\quantmind-v2\CLAUDE.md
- 宪法(已归档): D:\quantmind-v2\docs\archive\TEAM_CHARTER_V3.3.md
- 进度: D:\quantmind-v2\PROGRESS.md
- 教训: D:\quantmind-v2\LESSONS_LEARNED.md
- 因子注册: D:\quantmind-v2\FACTOR_TEST_REGISTRY.md
- **实施总纲: D:\quantmind-v2\docs\IMPLEMENTATION_MASTER.md**（唯一"下一步做什么"操作文档）
- 技术决策: D:\quantmind-v2\docs\TECH_DECISIONS.md（78项决策历史）
- 设计决策: D:\quantmind-v2\docs\DESIGN_DECISIONS.md（93+40项）
- 设计文档目录: D:\quantmind-v2\docs\
- 研究报告: D:\quantmind-v2\docs\research\（R1-R7，7份已完成）
- 设计vs现状审计: D:\quantmind-v2\docs\DEVELOPMENT_BLUEPRINT.md
- ML Walk-Forward设计: D:\quantmind-v2\docs\ML_WALKFORWARD_DESIGN.md
- 风控服务接口: D:\quantmind-v2\docs\RISK_CONTROL_SERVICE_DESIGN.md
- Qlib GP深研: D:\quantmind-v2\docs\research\QLIB_GP_FACTOR_MINING_RESEARCH.md
- **GP最小闭环设计: D:\quantmind-v2\docs\GP_CLOSED_LOOP_DESIGN.md**（Warm Start GP+FactorDSL+SimBroker反馈，Sprint 1.16-1.17）

## R1-R7研究关键结论（已融入IMPLEMENTATION_MASTER）
- R1: 因子→策略匹配框架(FactorClassifier, ic_decay路由)
- R2: 因子挖掘3引擎(暴力+GP+LLM) + AST去重 + Factor Gate G1-G8
- R3: 多策略组合(核心+Modifier架构, CompositeStrategy)
- R4: A股微观结构(PT实测64.5bps, 隔夜跳空主导, volume_impact模型)
- R5: 回测-实盘对齐(8个gap源, T+1 open执行价)
- R6: 生产架构(NSSM+Task Scheduler+Tailscale+备份)
- R7: AI模型选型(DeepSeek混合, ~$65-95/月)
