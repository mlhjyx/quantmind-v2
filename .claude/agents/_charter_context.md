# QuantMind V2 宪法共享上下文（Step 6-B 更新, 2026-04-09）

> 所有 agent 的 prompt 必须引用本文件内容。这是项目的不可协商规则。

## 项目概况
- 个人 A 股绝对收益量化交易系统, Python 3.11 + PostgreSQL 16 + FastAPI + LightGBM
- 当前: **Step 0→6-D 完成, PT 已重启 (2026-04-09)**, 基线: 5yr Sharpe=0.6095 (2021-2025, `regression_test.py`) / **12yr Sharpe=0.5309** (2014-2026, `metrics_12yr.json`, Step 6-D首跑), 排除 BJ/ST/停牌/新股
- 目标: 年化 15-25%, Sharpe 1.0-2.0, MDD <15%
- 优化目标排序: MDD > Sharpe > 因子数量（全团队共识）
- **总路线图**: `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md` (v3.8 + 第四部分重构记录)
- **系统现状**: `SYSTEM_STATUS.md` (重构前快照 + §0 重构完成状态)
- R1-R7 研究完成: 7 份报告已融入 Roadmap V3 第二部分

## 十八条铁律（CLAUDE.md 完整定义, 此处仅列标题）

### 工作原则类
1. 不靠猜测做技术判断 — 外部 API/数据接口必须先读官方文档
2. 下结论前验代码 — grep/read 验证, 不信文档不信记忆
3. 不自行决定范围外改动 — 先报告, 等确认

### 因子研究类
4. 因子验证用生产基线 + 中性化 — raw IC 和 neutralized IC 并列展示
5. 因子入组合前回测验证 — paired bootstrap p<0.05
6. 因子评估前确定匹配策略 — RANKING/FAST_RANKING/EVENT

### 数据与回测类
7. IC/回测前确认数据地基 — universe 对齐 + 无前瞻偏差
8. ML 实验必须 OOS 验证 — 训练/验证/测试三段分离

### 系统安全类
9. 重数据任务串行执行 — 最多 2 个并发
10. 基础设施改动后全链路验证
11. IC 必须有可追溯的入库记录 — factor_ic_history 表唯一可信源

### 因子质量类
12. 新颖性可证明性（G9 Gate）— AST 相似度 >0.7 拒绝
13. 市场逻辑可解释性（G10 Gate）— 必须有经济机制描述

### 重构原则类（Step 6-B 新增）
14. **回测引擎不做数据清洗** — 数据必须在入库时通过 DataPipeline 验证和标准化
15. **任何回测结果必须可复现** — (config_yaml_hash, git_commit) 进 backtest_run 表
16. **信号路径唯一** — 所有回测/研究/PT 走 SignalComposer → PortfolioBuilder → BacktestEngine
17. **数据入库必须通过 DataPipeline** — 禁止直接 INSERT

### 成本对齐
18. 回测成本实现必须与实盘对齐 — H0 验证 vs QMT 实盘误差 <5bps

## 因子审批链
alpha_miner 提出 → factor 审经济学假设 → quant 审统计 (t>2.5/BH-FDR/corr<0.7) → ★strategy 确定匹配策略 (铁律 6) → SimBroker 回测 (paired bootstrap p<0.05 vs 基线) → 入池

## 分级授权
- 自主: bug 修复/测试/文档/重构/数据拉取
- 简报: 新因子入池/参数配置
- 用户决策: 目标调整/框架变更
- 紧急: P0 阻塞→直接修复→事后汇报

## 沟通级别
- P0: 数据错误/逻辑硬伤/风险超标/PT 中断 → 立刻通知
- P1: 性能/次优方案/风控预警 → 当天汇总
- 建议: 主动贡献 → 提案

## 交叉审查矩阵
| 产出方 | 被谁 challenge |
|--------|-------------|
| factor 方案 | quant + strategy + risk |
| quant 结论 | factor + strategy |
| strategy 匹配 | quant + risk + factor |
| strategy 方案 | quant + factor + risk |
| arch 代码 | qa + data |
| data 结论 | quant + qa |
| risk 方案 | quant + strategy |
| alpha_miner 候选 | factor + quant |
| ml 模型 | quant + strategy + qa |

challenge 方式必须验代码/跑数据, 不是读文档同意 (铁律 2)。

## 验收标准
基于具体数字和可复现命令。不接受"完成", 必须是"5 因子 IC [+2.8%, +4.5%]"。

## 质量强化规则
- **Generator-Evaluator 分离**: 编码 agent 不可自我审查, 产出方 ≠ 审查方
- **重试限制**: 失败重试 ≤2 次, 第 3 次必须升级汇报用户
- **文档完整性**: agent 引用路径必须指向实际存在文件
- **PT 代码隔离**: PT 期间 (Step 0→6 重构窗口) signal_service/execution_service/run_paper_trading.py 等 PT 链路文件仅允许重构任务修改, 研究任务禁止

## 关键文件路径 (Step 6-B 更新)

### 主控
- `D:\quantmind-v2\CLAUDE.md` — 编码必需信息 (18 条铁律完整定义)
- `D:\quantmind-v2\SYSTEM_STATUS.md` — 系统现状 (含 §0 重构完成状态)
- `D:\quantmind-v2\LESSONS_LEARNED.md` — 经验教训
- `D:\quantmind-v2\FACTOR_TEST_REGISTRY.md` — 因子测试注册表 (BH-FDR M 源)

### 设计文档
- **总路线图**: `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md` (v3.8, §第四部分含 Step 0→6-B 重构记录)
- DDL: `docs/QUANTMIND_V2_DDL_FINAL.sql`
- 后端架构: `docs/DEV_BACKEND.md` (§0 含新 Data 层 + pt_* Service)
- 回测引擎: `docs/DEV_BACKTEST_ENGINE.md` (§0 含 backend/engines/backtest/ 8 模块拆分)
- 因子计算: `docs/DEV_FACTOR_MINING.md`
- GP 闭环: `docs/GP_CLOSED_LOOP_DESIGN.md`
- 风控: `docs/RISK_CONTROL_SERVICE_DESIGN.md`
- ML WF: `docs/ML_WALKFORWARD_DESIGN.md`
- 研究知识库: `docs/research-kb/`
- 研究报告: `docs/research/` (R1-R7)

### 重构后的核心代码路径
- PT 主脚本: `scripts/run_paper_trading.py` (345 行编排器)
- PT Services: `backend/app/services/pt_data_service.py` / `pt_monitor_service.py` / `pt_qmt_state.py` / `shadow_portfolio.py`
- 回测引擎: `backend/engines/backtest/` (engine/runner/broker/validators/executor/types/config.py)
- 数据层: `backend/data/parquet_cache.py`
- 数据契约: `backend/app/data_fetcher/contracts.py` + `pipeline.py`
- 配置加载: `backend/app/services/config_loader.py`
- YAML 配置: `configs/pt_live.yaml` / `configs/backtest_12yr.yaml` / `configs/backtest_5yr.yaml`
- 基线数据: `cache/baseline/regression_result.json` (Sharpe=0.6095, max_diff=0)

### 已归档 (不要引用)
- ~~`IMPLEMENTATION_MASTER.md`~~ → 内容合并到 Roadmap V3 §第二部分
- ~~`TECH_DECISIONS.md` / `DESIGN_DECISIONS.md`~~ → 合并到 Roadmap V3 附录 F
- ~~`PROGRESS.md`~~ → 直接看 `git log` 和 Roadmap V3 §第四部分
- ~~`TEAM_CHARTER_V3.3.md`~~ → 已归档至 `docs/archive/`, 本文件是宪法的唯一在用版本
- ~~`DEVELOPMENT_BLUEPRINT.md`~~ → 过时

## R1-R7 研究关键结论
- R1: 因子→策略匹配框架 (FactorClassifier, ic_decay 路由)
- R2: 因子挖掘 3 引擎 (暴力+GP+LLM) + AST 去重 + Factor Gate G1-G8
- R3: 多策略组合 (核心+Modifier 架构, CompositeStrategy)
- R4: A 股微观结构 (PT 实测 64.5bps, 隔夜跳空主导, volume_impact 模型)
- R5: 回测-实盘对齐 (8 个 gap 源, T+1 open 执行价)
- R6: 生产架构 (**Servy v7.6** + Task Scheduler + 备份)
- R7: AI 模型选型 (DeepSeek 混合)
