# QuantMind V2 开源量化生态对标分析 (Comprehensive Edition)

**日期**: 2026-04-26
**作者**: Claude Code (AI assist) + 人工审阅
**研究范围**: 24 个开源量化项目 × 10 评估维度
**目的**: Wave 3+ 路线图 / Wave 4 Observability / Wave 5 Operator UI / 长期工程债清理
**状态**: research, Part 7 行动路线图待批准后实施
**关联**: docs/QUANTMIND_PLATFORM_BLUEPRINT.md (QPB v1.8) / memory/project_borrowable_patterns.md

---

## 执行摘要 (TL;DR)

### 5 大核心结论

1. **QM 差异化护城河仍然成立**: 24 项目无一同时具备 (Walk-Forward 5-fold OOS + paired bootstrap p<0.05 + BH-FDR 多重检验 + 42 铁律 governance + ADR + Knowledge Registry + 真金 PT). alpha 严格性 + 治理体系是 QM 的不可替代价值.

2. **QM 真实工程债 6 类**, 优先级降序: ① 数据层灵活性 ② Observability/Run Record ③ UI 可观测面板 ④ 多策略 ensemble (MVP 3.2 内含) ⑤ 回测精度 (bar 内路径) ⑥ LLM 闭环抽象.

3. **Tier S 学术对标**: Qlib + RD-Agent + FinGPT + FinRobot + mlflow — 是 QM Wave 4+ AI 闭环 + ML 生命周期管理时**必读对位**.

4. **Tier A 实盘对标**: vnpy + NautilusTrader (Rust+Python institutional grade) + Lean + Freqtrade + Hummingbot — Forex 模块启动时**必读 broker abstraction**, 当前 QM 单 QMT 不动.

5. **重大决策反转**:
   - backtrader / pyfolio / alphalens / empyrical / catalyst 全部**停更 1+ 年**, 不再列对标 (Quantopian 路径技术债, 不要再借鉴)
   - vnpy 4.0 引入 `vnpy.alpha` 模块, 借鉴 Qlib Alpha158 — **QM Phase 1.2 Alpha158 借鉴路线被验证为正确路线**
   - RD-Agent (微软, 13K⭐, 2024-04 创建) 学术地位高, 阶段 0 NO-GO 应在 Wave 4 重评估
   - NautilusTrader (22K⭐, Rust 核心) 是 vnpy 的下一代, Forex/HFT 时该重新评估

### 30 个可学模式 (从前 22 扩展)

按 Wave 实施时间排序的 30 个具体可借鉴工程模式 (详见 Part 5), 跨数据/回测/策略/AI/UI/Observability 6 个维度.

---

## Part 1: 研究范围与方法论

### 1.1 研究范围 (24 项目)

| 类型 | 项目 | star | 收录理由 |
|---|---|---|---|
| Alpha + ML | Qlib, RD-Agent, FinGPT, FinRobot, mlflow, river | 高 | 学术对标 + ML 生命周期 |
| 实盘交易 | vnpy, NautilusTrader, Lean, Freqtrade, Hummingbot, Hikyuu, rqalpha, lumibot, jesse | 中-高 | broker 抽象 + 多市场 |
| 数据 + UI | OpenBB, akshare, 金策智算, QuantDinger | 中 | 数据聚合 + UI 工程化 |
| 回测 + 性能 | vectorbt, backtesting.py, bt, gs-quant, pysystemtrade, zipline-reloaded | 中 | 回测引擎设计模式 |
| RL + 在线 ML | FinRL, TensorTrade | 低 (路线不匹配) | 完整性 |
| 已死 / 不建议 | backtrader, pyfolio, alphalens, empyrical, catalyst, eiten, ML4Trading repo | N/A | 反例标记 |

### 1.2 排除原因

- **stop-pushed > 12 月**: backtrader (21月) / pyfolio (28月) / empyrical (22月) / catalyst (41月) / eiten (45月) / TensorTrade (慢, 边缘)
- **不是框架**: ML4Trading 是教材代码 / mlflow 不是 finance 专用
- **国内私域分散**: easytrader / abu / wondertrade 等社区分散

### 1.3 评估维度 10 项

| 维度 | 含义 | QM 当前 |
|---|---|---|
| D1 Alpha 严格性 | IC + 中性化 + WF + paired bootstrap p<0.05 + BH-FDR | ⭐⭐⭐⭐⭐ |
| D2 数据层灵活 | provider 抽象 + 增量同步 + 缓存策略 + 多源 fallback | ⭐⭐ |
| D3 回测精度 | 成本对齐 + bar 内路径 + OOM 防呆 + 可复现 | ⭐⭐⭐⭐ |
| D4 多策略 / 组合 | ensemble + capital allocation + tie_policy | ⭐ (MVP 3.2 后 ⭐⭐⭐⭐) |
| D5 实盘 / Broker | 单一 vs 多家 + gateway 抽象 | ⭐⭐ (单 QMT) |
| D6 Governance | 铁律 + ADR + Knowledge Registry + 测试基线 | ⭐⭐⭐⭐⭐ |
| D7 AI/LLM 闭环 | chat 包装 vs 真闭环 (建议 → IC → 验证 → 入池) | ⭐ (Wave 4+ 后 ⭐⭐⭐⭐) |
| D8 UI / 可观测 | 面板 + IDE + 实时监控 | ❌ (Wave 5 后 ⭐⭐⭐⭐) |
| D9 License 友好 | MIT/Apache > BSD > LGPL > GPL > 自定义商禁 | N/A (private) |
| D10 真实社区健康 | issue/PR 真用户参与 vs 营销 stars | ❌ (private repo) |

---

## Part 2: Tier 分级 (24 项目)

### Tier S — 学术 / AI 对标 (Wave 4+ 必读)

| 项目 | star | 推送 | License | 关键能力 |
|---|---:|---|---|---|
| **Qlib** | 41K | 4-22 | MIT | Alpha158/360 + ML 多范式 + workflow YAML 驱动 + RL 子模块 |
| **RD-Agent** | 13K | 4-22 | MIT | Multi-Agent factor mining (Researcher/Coder/Eval/Reflector) + arxiv paper |
| **FinGPT** | 20K | 4-24 | MIT | LLM for finance (FinLLaMA / FinGPT-RAG / forecaster) |
| **FinRobot** | 7K | 4-3 | Apache-2.0 | AI Agent platform for financial analysis using LLMs |
| **mlflow** | 25K | 4-25 | Apache-2.0 | ML 生命周期 (tracking + registry + serving), 通用但 QM ML 实验缺这个 |
| **river** | 6K | 4-23 | BSD-3 | Online ML (incremental learning, concept drift) |

### Tier A — 实盘交易 + Broker 抽象 (Forex 启动时必读)

| 项目 | star | 推送 | License | 关键能力 |
|---|---:|---|---|---|
| **vnpy** | 40K | 4-22 | MIT | 28+ broker gateway + v4.0 vnpy.alpha 借 Alpha158 |
| **NautilusTrader** | 22K | 4-25 | LGPL-3.0 | **Rust 核心 + Python API**, 事件驱动确定性, institutional grade HFT |
| **Lean (QuantConnect)** | 19K | 4-24 | Apache-2.0 | C# 内核 + Python API, 多市场最全 (cn/us/futures/forex/crypto) |
| **Freqtrade** | 49K | 4-25 | GPL-3.0 | crypto auto trading 头牌, 大量 indicator + telegram 控制 |
| **Hummingbot** | 18K | 4-22 | Apache-2.0 | crypto market making 头牌 |
| **Hikyuu** | 3K | 4-23 | Apache-2.0 | **C++ + Python**, 国内交易, 超高速 |
| **rqalpha** | 6K | 4-22 | Other | 米筐 (RiceQuant) 中国机构级回测+交易 |
| **lumibot** | 1K | 4-25 | GPL-3.0 | multi-broker (crypto/stocks/options/futures/forex) Python |
| **jesse** | 8K | 4-25 | MIT | crypto AI bot, 现代 Vue UI |

### Tier B — 数据 + UI 工程化

| 项目 | star | 推送 | License | 关键能力 |
|---|---:|---|---|---|
| **OpenBB** | 66K | 4-25 | Other | 数据 platform + Electron desktop + AI agent 集成 |
| **akshare** | 18K | 4-23 | MIT | **中国开源数据 SDK**, QM Tushare 备选 |
| **金策智算** | 469 | 4-24 | 自定义商禁 | 数据 4 模式同步 + multi-strategy ensemble (上轮深度分析) |
| **QuantDinger** | 2K | 4-24 | Apache-2.0 | LLM multi-provider + Vue indicator IDE (上轮深度分析) |

### Tier C — 回测 + 性能分析

| 项目 | star | 推送 | License | 关键能力 |
|---|---:|---|---|---|
| **vectorbt** | 7K | 4-25 | Other | **Numba 加速**, 千次回测组合搜索 (QM 已知评估) |
| **backtesting.py** | 8K | 2025-12-20 | AGPL-3.0 | 轻量回测引擎, AGPL 不友好 |
| **bt** | 3K | 3-31 | MIT | Tree-based 组合 backtest (`Algo` + `Strategy`) |
| **gs-quant** | 10K | 4-23 | Apache-2.0 | **Goldman Sachs 开源**, 衍生品 + 风险分析 + 大量 jupyter notebook |
| **pysystemtrade** | 3K | 4-2 | GPL-3.0 | Robert Carver "Systematic Trading" 教材配套 |
| **zipline-reloaded** | 2K | 2026-01-06 | Apache-2.0 | Quantopian zipline 维护 fork |

### Tier D — RL / 探索方向

| 项目 | star | 推送 | License | 备注 |
|---|---:|---|---|---|
| **FinRL** | 15K | 4-5 | MIT | RL trading agents, FinRL-X 升级中 |
| **TensorTrade** | 6K | 2-19 | Apache-2.0 | RL 环境, 慢更 |

⚠️ **QM Phase 2.1 已证 RL/E2E 在 A 股不可行** (sim-to-real gap 282%, A 股交易成本不可微). FinRL 在 crypto / forex 仍可观察, 但**不是 QM 当前路线**.

### Tier X — 已死 / 反例 (不建议借鉴)

| 项目 | last push | 状态 |
|---|---|---|
| backtrader | 2024-08-19 | 21 月停更. Python 回测经典已被 vectorbt/Qlib/vnpy 替代 |
| pyfolio | 2023-12-23 | 28 月停更. Quantopian 关停遗产 |
| alphalens-reloaded | (archived) | Quantopian 因子分析事实标准, 维护 fork 也已停 |
| empyrical | 2024-07-26 | 22 月停更. 性能指标库 |
| catalyst | 2022-11-26 | 41 月停更. crypto 算法交易 |
| eiten | 2022-07-30 | 45 月停更. 投资策略集 |
| ML4Trading repo | 2024-08-18 | book 配套代码非框架 |

⚠️ **QM 当前任何对 Quantopian 三件套 (alphalens/pyfolio/empyrical) 的引用都应当移除**. 自建 IC + 性能指标已替代.

---

## Part 3: 8 顶级项目深度画像

(Tier S + Tier A 顶配 + 已深度分析的 2 个共 8 个, 其余 16 个见 Part 2 概述)

### 3.1 Qlib (微软, 41K⭐) — 顶级对标 [QM 已部分对接]

**顶层结构**: `backtest / cli / contrib / data / model / rl / strategy / utils / workflow`

**标志能力**:
- **Alpha158 / Alpha360**: 158/360 个工业级量价因子表达式
- ML modeling paradigms: supervised + market dynamic + RL 三范式
- `.bin` 数据格式 (压缩高效) + workflow YAML 驱动
- Recorder + signal_record / portfolio analysis_record (类似 QM regression_test)

**QM 阶段 0 (2026-04-10) NO-GO 决策原因**:
- `.bin` 格式需双份数据 (Tushare 入 PG + 转 .bin), 存储倒退
- 无 PMS 阶梯利润保护
- 无 A 股涨跌停限制
- 无历史税率切换 (2023-08-28 印花税从 0.1% 降 0.05%)
- 迁移 = 倒退

**决策仍然成立**: 路线 C (借因子表达, 不迁框架) 正确.

**新发现**: Qlib 跟 vnpy 4.0 联姻 — Alpha158 通过 `vnpy.alpha.dataset.alpha_158` 进入实盘交易圈. **QM Phase 1.2 借鉴 6 个 Alpha158 因子的路线** (validated 6/6 PASS) **被验证为中国量化界主流路线**.

**借鉴清单**:
- `qlib.workflow` YAML 驱动 — QM `configs/pt_live.yaml` 已对齐
- `signal_record` / `portfolio_analysis_record` — 类似 QM Wave 4 Observability `task_run_record` 设计
- `qlib.data.dataset` 抽象 — 给 ML 训练的数据切片管道, QM Phase 2.1 LightGBM NO-GO 后未深用, 但 Wave 4+ 重启 ML 探索时是好蓝本

---

### 3.2 RD-Agent (微软, 13K⭐) — 顶级对标 [应重评估]

**项目背景**: 微软 Qlib 团队 2024-04 推出, 学术地位高
**论文**: arxiv 2505.15155 *"R&D-Agent-Quant: A Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization"*

**核心架构**: 多 Agent 闭环
- Researcher: 从论文/数据生成因子假设
- Coder: 实现假设代码
- Eval: 回测 + IC 验证
- Reflector: 分析失败原因 → 反馈下一轮假设生成

**QM 阶段 0 (2026-04-10) NO-GO 原因**:
- Docker 硬依赖
- Windows bug 多
- 不支持 Claude (主要 OpenAI/Anthropic Direct API)

**重评估建议** (Wave 4 启动前):
- 学术价值仍在: Multi-Agent factor mining 是 QM `DEV_AI_EVOLUTION V2.1` 4 Agent 闭环的**学术对位** (Researcher/Critic/Library_committer/Trader)
- 不必迁框架, 但**论文方法论应深度阅读**, 作为 QM AI 闭环设计的对照
- Hypothesis tracking 数据库设计跟 QM Knowledge Registry 概念对位

---

### 3.3 vnpy (中国, 40K⭐) — 实盘 + ML 双路线 [Forex 时必学]

**v4.0 重磅**: `vnpy.alpha` 模块 (ML 多因子, 借 Qlib Alpha158)

**标志能力**:
- **broker abstraction 中国事实标准**: 28+ gateway (CTP/IB/QMT/Binance/OKX/HuoBi/...)
- ML 多因子 + Lasso/LightGBM/MLP 三模型集成
- `vnpy.chart` 实时图表
- `vnpy.event` 事件总线
- `vnpy.rpc` 跨进程 RPC

**QM 现状对位**:
- QM 单 broker (国金 miniQMT) — 当前用够
- QM Phase 2.1 LightGBM NO-GO (val_sharpe=1.26 → 实盘 -0.99) — vnpy.alpha 是否能在中国市场破局值得**长期观察**

**借鉴清单**:
- **Forex 模块 (DEFERRED) 启动时**: `vnpy/gateway/*` broker abstraction pattern 是必学蓝本 (优于 QuantDinger live_trading/)
- `vnpy.event` 事件总线 — QM 已用 Redis Streams (StreamBus), 不必改

---

### 3.4 NautilusTrader (22K⭐, Rust+Python) — 下一代实盘内核 [新发现]

**关键差异**: 不是 Python 写 trading 然后调 Rust SDK. 是 **Rust 写核心引擎 + Python API**.

**特性**:
- 事件驱动确定性 (deterministic event-driven architecture)
- Production-grade institutional-class
- Backtest + Live 共享同一引擎代码 (跟 QM 铁律 16 信号路径唯一同方向)
- Multi-venue: 股票/期货/加密/Forex
- LGPL-3.0 (allow private use, modifications must release if distributed)

**vs vnpy**:
- vnpy: Python 端到端, Python GIL 限制单 ms 级延迟
- NautilusTrader: Rust 核心可达 微秒级延迟, institutional 级别
- 是 vnpy 的下一代, 但学习曲线陡

**QM 评估**:
- 当前 QMT 单一 broker + 月度调仓, **完全用不到微秒级**
- 但**Forex 启动时 + 未来 HFT 探索时**, NautilusTrader 是该 vnpy 的替代评估对象
- LGPL-3.0 允许私有使用, distribute 时需开源 — QM private 不影响

---

### 3.5 Freqtrade (49K⭐, GPL-3.0) — crypto 头牌

**地位**: 当前 GitHub 最大的开源 crypto 交易项目

**特性**:
- 大量内置 indicator + technical indicators
- Telegram bot 控制
- Hyperopt 超参优化
- Backtesting + Live trading 切换
- Edge positioning (基于 Win-rate 的 position sizing)

**QM 借鉴**: 几乎不需要 — QM 是 A 股 alpha + 真金, Freqtrade 是 crypto trading bot, 物种完全不同. 仅 Telegram 通知 / Hyperopt pattern 可参考.

⚠️ **GPL-3.0** 强 copyleft, 任何 copy 都污染 QM 整个仓库.

---

### 3.6 Lean (QuantConnect, 19K⭐, Apache-2.0) — 多市场最全

**特性**:
- C# 核心 + Python API wrapper (PythonNet)
- **多市场覆盖最全**: 股票 / 期货 / Options / Forex / Crypto / CFD
- 云端 backtest + 本地 backtest 切换
- 完善的 alpha streams 平台

**QM 借鉴**:
- 多 asset class abstraction 设计 — Forex 启动后参考
- Alpha API + Insight 抽象 — 跟 QM 信号路径有对位

---

### 3.7 OpenBB (66K⭐, Other License) — 数据 + UI 平台

**定位**: "Financial data platform for analysts, quants and AI agents" — 不是回测框架, 是数据聚合 + UI

**结构**: `cli / cookiecutter / desktop (Electron) / examples / openbb_platform`

**标志能力**:
- 多 provider 抽象 (Bloomberg / Yahoo / FRED / IEX / Polygon / 100+ source)
- Electron desktop app
- AI agent 集成 (官方支持 GPT/Claude/Gemini 嵌入)
- "Bloomberg Terminal alternative"

**QM 借鉴**:
- **Wave 5 UI 启动时**: Electron desktop + provider abstraction pattern 是顶级参考
- AI agent 集成模式可参考 — QM Wave 4+ LLM 闭环

---

### 3.8 mlflow (25K⭐, Apache-2.0) — ML 生命周期管理

**关键洞察**: 不是 finance 专用, 但 QM ML 实验**完全缺这层基础设施**.

**特性**:
- Tracking: experiment / run / metric / parameter / artifact 持久化
- Registry: model versioning + stage (dev/staging/prod)
- Serving: REST API 部署
- 跨 ML 框架 (sklearn/XGBoost/PyTorch/LightGBM)

**QM 现状**:
- Phase 2.1/3D LightGBM 实验靠 .pkl + 手工记录, 缺 mlflow 这层 versioning
- factor_registry 是因子级别的 mini-registry, 但缺 model 级别

**借鉴**: Wave 4+ 重启 ML 探索时 (如 vnpy.alpha 路径成熟反向再试), mlflow 集成是必备.

---

## Part 4: 10 维度对比矩阵 (核心 12 项目)

| 维度 | Qlib | RD-Agent | vnpy | Nautilus | Freqtrade | Lean | OpenBB | QuantDinger | 金策 | mlflow | FinGPT | **QM** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D1 Alpha 严格性 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ❌ | ❌ | ❌ | N/A | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| D2 数据层灵活 | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | N/A | ⭐⭐ | ⭐⭐ |
| D3 回测精度 | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | N/A | ⭐⭐⭐ | ⭐⭐ | N/A | N/A | ⭐⭐⭐⭐ |
| D4 多策略 ensemble | ⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | N/A | ⭐ | ⭐⭐⭐ | N/A | N/A | ⭐ → ⭐⭐⭐⭐ |
| D5 实盘 broker | ⭐ | N/A | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ (crypto) | ⭐⭐⭐⭐ | N/A | ⭐⭐⭐ | ⭐⭐ | N/A | N/A | ⭐⭐ |
| D6 Governance | ⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ |
| D7 AI/LLM 闭环 | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ → ⭐⭐⭐⭐ |
| D8 UI / 可观测 | ⭐⭐ | ⭐⭐⭐ Live demo | ⭐⭐⭐ chart | ⭐⭐ | ⭐⭐ Telegram | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ Desktop | ⭐⭐⭐⭐ Vue IDE | ⭐⭐ dashboard | ⭐⭐⭐⭐ MLflow UI | ⭐⭐ | ❌ → ⭐⭐⭐⭐ |
| D9 License 友好 | MIT | MIT | MIT | LGPL-3.0 | GPL-3.0 ⚠️ | Apache-2.0 | Other | Apache-2.0 | 商禁 ❌ | Apache-2.0 | MIT | N/A |
| D10 社区健康 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ❌ private |

---

## Part 5: 30 模式可学清单 (从前 22 扩展)

按 **(Wave / 工程量 / 收益)** 排序

### P0 立即可做 (cheap win, Sunday-Monday 后零散嵌入)

| # | 模式 | 来源 | 工程量 |
|---|---|---|---|
| 1 | **MTF_CONFIG OOM guard** (max_1m_days=15 / max_5m_days=365) | QuantDinger | 0.5 day |
| 2 | **read_only DB 连接** (factor_repository 读路径) | 金策 duckdb | 0.5 day |
| 3 | **bar 内 candle path 推断** (阳线 dip-rally / 阴线 rally-dip) | QuantDinger | 1 day (但日内策略上线前才必须) |

### P1 Wave 3 推进时 (MVP 3.2-3.5 设计稿纳入)

| # | 模式 | 来源 | 对应 MVP |
|---|---|---|---|
| 4 | **multi_strategy_ensemble** (vote/and/or + tie_policy + min_agree_count + direction conflict) | 金策 backtest_cabinet | **MVP 3.2** |
| 5 | **per-strategy capital + aggregate NAV** | 金策 | MVP 3.2 |
| 6 | **time_window_resolver** (lookback/custom/intraday/session_only) | 金策 history_sync | LL-076 真修复 (已在 LL 沉淀, 但**实施时机** Wave 3 后) |
| 7 | **sync_run_record** (record_{ts}.json + detail.csv) | 金策 history_sync | LL-068 / LL-077 同方向 |

### P2 Wave 4 Observability (~3-4 周)

| # | 模式 | 来源 | 优先 |
|---|---|---|---|
| 8 | **data_source_router** (多 provider fallback) | 金策 + OpenBB + akshare | 高 |
| 9 | **task_run_record** (任何 batch 任务持久化) | 金策 + QuantDinger ENGINE_VERSION | 高 |
| 10 | **factor_quality_check.py linting** (新因子注册时强制经济机制 + direction + 单位) | QuantDinger indicator_code_quality 启发 | 高 |
| 11 | **backtest_guard.py 用户层防呆** | QuantDinger MTF + 自创 | 高 |
| 12 | **LLM Multi-provider abstraction** (Enum + auto-detect + OpenAI-compatible) | QuantDinger llm.py | 中 |
| 13 | **Best-effort context builder** (ThreadPoolExecutor + success/failed dual) | QuantDinger market_data_collector | 中 |
| 14 | **LLM self-calibration** (consensus_score + actual_return → threshold 优化) | QuantDinger ai_calibration | 中 (Wave 4+ LLM 闭环必备) |
| **15** | **mlflow 集成** (experiment / run / metric / parameter persistence) | mlflow | 中 (重启 ML 探索时) |

### P3 Wave 5 Operator UI (~4-6 周, 你纠正后新增 Wave)

| # | 模式 | 来源 | 优先 |
|---|---|---|---|
| 16 | **Operator UI 5 子 MVP**: PT 状态 / IC 监控 / 回测对比 / 风控链路 / 调度 dashboard | OpenBB + QuantDinger | 高 |
| 17 | **event_coalesce + flow_emit_stride** (实时面板 backpressure) | 金策 | 高 |
| 18 | **Vue/Electron desktop 选型** | OpenBB + QuantDinger + jesse | 中 |
| 19 | **TF cache 进程内 LRU + TTL 按周期** | 金策 + QuantDinger | 低 (cheap win 但收益小) |

### P4 Wave 6+ 远期 (日内 / Forex / AI 闭环)

| # | 模式 | 来源 | 时机 |
|---|---|---|---|
| 20 | **strategy_script_runtime sandbox** (build_safe_builtins + safe_exec_with_validation) | QuantDinger | LLM 闭环安全前提 |
| 21 | **bar 内 candle path 推断升级** | QuantDinger | 日内策略上线前 |
| 22 | **Forex broker abstraction** | vnpy gateway pattern (优于 QuantDinger / NautilusTrader 评估) | Forex 模块启动 |
| 23 | **NautilusTrader Rust 核心评估** | NautilusTrader | 未来 HFT 探索时 |
| 24 | **RD-Agent multi-agent factor mining 闭环** | RD-Agent paper | DEV_AI_EVOLUTION V2.1 蓝本 |
| 25 | **online learning (concept drift detection)** | river | Wave 4+ ML 探索 |
| 26 | **akshare data fallback** | akshare | Tushare 挂掉时备份 |
| 27 | **Lean Alpha streams 设计** | Lean | 多策略多市场扩展时 |
| 28 | **gs-quant 衍生品 + 风险分析** | gs-quant | 未来期权策略时 |

### Cross-cutting 模式 (跨多个 Wave)

| # | 模式 | 价值 |
|---|---|---|
| **A** | **用户层防呆 / Linting 文化** (#10 #11) | QM 当前 governance 是给开发者, 缺给"用户面" (= 自己跑命令时) 的防呆 |
| **B** | **Run Record + 历史可回溯** (#7 #9 #15) | QM schtask Result code 太弱, batch 任务 record 缺位 |
| **C** | **Sandbox / Restricted Execution** (#20) | LLM 闭环安全前提, QM 还没意识到 |
| **D** | **进程内 + 跨周期 cache** (#19) | Wave 4 多次回测加速 |
| **E** | **多源 fallback 配置驱动** (#8 #12 #26) | Tushare/Claude 单点失败时降级 |

---

## Part 6: QM 真正的差异化 + 真实差距

### 6.1 差异化护城河 (24 项目无一同时具备)

1. **42 铁律 + 5 ADR + Knowledge Registry**: Governance 体系
2. **Walk-Forward 5-fold OOS + paired bootstrap p<0.05 + BH-FDR**: 学术严格性
3. **Phase 1 印花税历史税率 (2023-08-28 切换) + 三因素滑点 + H0 校准 (理论 vs QMT 实盘 <5bps)**: 成本对齐 (vs QuantDinger Issue #52 仍未扣手续费)
4. **真金 PT live ¥1M + MVP 3.1 Risk Framework 2026-04-27 09:00 首生产触发**: 实战验证
5. **factor_values 901M 行 + ic_calculator 统一口径 + neutral_value (MAD → fill → WLS → zscore → clip±3)**: 数据基础设施

### 6.2 真实工程债 (深读 24 项目后定位)

| 维度 | QM 当前 | 顶级对标 | 倍数差距 |
|---|---|---|---|
| 数据层灵活 | schtask 硬码单路径 | 金策 4 模式配置 / vnpy 28 gateway / OpenBB 100+ provider | 3-50× |
| 回测精度 (bar 内路径) | close 单点 | QuantDinger candle_path 推断 | 月度可接受 / 日内硬伤 |
| 多策略 ensemble | MVP 3.2 设计中 | 金策 vote/and/or + tie_policy + min_agree | 设计稿必含 |
| Observability / Run Record | schtask Result code | 金策 record_{ts}.json + QuantDinger config_snapshot/code_hash | 完全缺 |
| UI | 0% | OpenBB Electron / QuantDinger Vue / jesse modern UI | Wave 5 新建 |
| AI 闭环 | DEV_AI_EVOLUTION V2.1 设计 0% 实现 | RD-Agent multi-agent + FinGPT/FinRobot LLM | Wave 4+ 重启 |

### 6.3 是定位选择而非缺陷的部分

- 多 broker (QM 单 QMT 当前用够)
- 多市场 (Forex DEFERRED, 优先 A 股)
- 多用户 / 计费 / OAuth (QM 单用户系统)
- TDX/BLK 集成 (国内本土能力, 跟 alpha 路线不同物种)
- RL / E2E 可微 (QM Phase 2.1 已证 A 股不可行)
- Crypto (路线不在范围)

### 6.4 主动反思 — 几个 QM 没意识到的盲点

| 盲点 | 来源对标 | QM 当前认知 | 重评估时机 |
|---|---|---|---|
| **mlflow ML 生命周期管理** | mlflow + Qlib Recorder | factor_registry 是因子级 mini-registry, 缺 model 级 | Wave 4+ 重启 ML |
| **akshare 作为 Tushare fallback** | 金策已用 + akshare 18K star | 单 Tushare 路径 | LL-076 真修复一并做 |
| **NautilusTrader Rust 核心** | NautilusTrader 22K | vnpy 是当前唯一 broker abstraction 蓝本认知 | Forex / HFT 启动时 |
| **river online learning** | river 6K BSD-3 | LightGBM batch 训练 | Wave 4+ regime 检测探索时 |
| **FinGPT / FinRobot LLM-for-finance** | 20K + 7K AI4Finance | DEV_AI_EVOLUTION V2.1 (自建设计) | Wave 4+ 时 deep 阅读 paper, 不必抄代码 |
| **Quantopian 三件套已死** | alphalens/pyfolio/empyrical 全停更 | 项目历史可能有 import 引用 | 立即 grep 清理 |

---

## Part 7: 行动路线图

### 7.1 短期 (今晚-Monday, 不动)

- Sunday 02:00-06:00 维护窗口 (Phase 3 VACUUM FULL, -20~40 GB)
- Monday 4-27 09:00 MVP 3.1 Risk Framework 真生产首触发观察
- Tuesday 4-28+ S2PEADEvent LIVE 升级评估 (Stage 4.2)

### 7.2 Monday 后 (Wave 3 推进, ~4-6 周)

| 周 | 任务 | 关联 # |
|---|---|---|
| W1-2 | LL-076 真修复 (#6 + #7 一起) | P1 |
| W3-4 | MVP 3.2 Strategy Framework (含 #4 #5 ensemble 4 gotcha) | P1 |
| W5-6 | MVP 3.3 Signal-Exec / 3.4 Event Sourcing / 3.5 Eval Gate | 已有设计稿 |

### 7.3 Wave 4 Observability (~3-4 周)

| 周 | 任务 | 关联 # |
|---|---|---|
| W1 | data_source_router (#8 + #26 akshare fallback) | P2 |
| W2 | task_run_record + sync_run_record (#7 + #9) | P2 |
| W3 | factor_quality_check + backtest_guard (#10 + #11) | P2 |
| W4 | LLM Multi-provider + best-effort context builder + self-calibration (#12 + #13 + #14) | P2 |
| **新增** | **mlflow 集成评估** (#15) | P2 (备选) |

### 7.4 Wave 5 Operator UI (~4-6 周, 你纠正后新增)

| MVP | 内容 | 关联 # |
|---|---|---|
| 5.0 | UI 总纲 + 框架选型 (Vue + ECharts 或 Electron desktop) | #16 #18 |
| 5.1 | PT 状态实时面板 (Redis + DB + QMT 三源对账可视化) | #16 |
| 5.2 | IC 监控 + 因子衰减可视化 | #16 |
| 5.3 | 回测结果对比页 (regression + WF + Phase 实验对比) | #16 + #17 (event_coalesce 实时回测) |
| 5.4 | 风控事件链路追踪 (PMS/CB/Intraday) | #16 |
| 5.5 | 调度任务 dashboard (schtasks + Beat 健康) | #16 |

### 7.5 Wave 6+ 远期 (日内 / Forex / AI 闭环, 评估时机)

| 阶段 | 触发条件 | 关联 # |
|---|---|---|
| 日内策略上线前 | PEAD intraday 等真要做时 | #21 (bar 内路径) + #20 (sandbox) |
| Forex 模块启动 | A 股 alpha 稳定 + 资源允许 | #22 (vnpy 蓝本) + #23 (NautilusTrader 评估) |
| AI 闭环重启 | DEV_AI_EVOLUTION V2.1 重启 | #24 (RD-Agent paper) + #25 (river online) + FinGPT/FinRobot 阅读 |
| 期权 / 衍生品 | 远期 | #28 (gs-quant) |

---

## Part 8: 衍生文档清单 (本文档之后产出)

### 已存在 (Wave 3 设计稿)
- `docs/mvp/MVP_3_2_strategy_framework.md` (PR #87) — 需补 #4 #5 ensemble 4 gotcha
- `docs/mvp/MVP_3_3_signal_exec_framework.md` (PR #89)
- `docs/mvp/MVP_3_4_event_sourcing_outbox.md` (PR #92)
- `docs/mvp/MVP_3_5_eval_gate_framework.md` (PR #93)

### 待写 (Wave 4 Observability)
- `docs/mvp/MVP_4_1_observability_run_record.md` (#7 + #9)
- `docs/mvp/MVP_4_2_data_source_router.md` (#8 + #26)
- `docs/mvp/MVP_4_3_factor_quality_lint.md` (#10)
- `docs/mvp/MVP_4_4_backtest_guard.md` (#11)
- `docs/mvp/MVP_4_5_llm_provider_abstraction.md` (#12 + #13 + #14)
- `docs/mvp/MVP_4_6_mlflow_integration.md` (#15, 备选)
- `docs/mvp/MVP_4_7_time_window_resolver.md` (#6, LL-076 真修复)

### 待写 (Wave 5 Operator UI)
- `docs/mvp/MVP_5_0_operator_ui_overview.md` (#16 + #18 框架选型)
- `docs/mvp/MVP_5_1_pt_status_panel.md`
- `docs/mvp/MVP_5_2_ic_monitor_panel.md`
- `docs/mvp/MVP_5_3_backtest_comparison.md`
- `docs/mvp/MVP_5_4_risk_event_trace.md`
- `docs/mvp/MVP_5_5_scheduler_dashboard.md`

### Memory 更新
- `memory/project_borrowable_patterns.md` (本文档配套, 30 模式索引 + 实施时机)
- `memory/project_research_nogo_revisit.md` (添加 RD-Agent 重评估, 已有条目升级)
- `memory/project_platform_decisions.md` (添加新决策: backtrader/pyfolio 不再对标; vnpy.alpha 验证 Alpha158 路线)

### Blueprint 更新
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` v1.8 → v1.9
  - Wave 5 Operator UI 加入 Part 4 路径 (MVP 5.0-5.5)
  - 12 Framework + 候补 "Framework #13 Frontend / UI" placeholder
- 新增 [`docs/adr/ADR-012-wave-5-operator-ui.md`](../adr/ADR-012-wave-5-operator-ui.md) (基于本对标分析, **2026-04-26 已写**)
- 新增 `docs/adr/ADR-013-rd-agent-revisit.md` (Wave 4+ 重评估 RD-Agent, 待写)
- ⚠️ ADR-011 已被占用 (qmt-api-utilization-roadmap), 故本对标分析衍生 ADR 从 012 起编号

### 立即清理 (P0)
- ~~grep 全项目 `pyfolio` / `alphalens` / `empyrical` 引用 — 全部替换为自建 IC/性能指标~~
- ~~grep 全项目 `backtrader` 引用 — 移除~~

**✅ 2026-04-26 已验证 0 命中** (跑 `grep -rn "import alphalens\|import pyfolio\|import empyrical\|import backtrader" --include="*.py" backend/ scripts/`, 全部 0 命中). QM 自建 IC/性能指标早已替代 Quantopian 三件套, 无需清理.

---

## Part 9: 反思 (主动思考, 不局限思维)

### 9.1 我自己 5 轮回复的认知误差曲线

| 轮 | 误差类型 | 用户纠正 |
|---|---|---|
| 1 | "toy 实现" 过早下结论 (只看 41 行 dispatcher / 80 行 if/else) | "你没分析到位" |
| 2 | 数据层完全漏掉 (utils 185KB 没看) | "数据方面也没分析完整" |
| 3 | UI 标"反面教材, 不做" (dismissive thinking) | "UI 也需要做, 后端做好后做" |
| 4 | 偏重金策, QuantDinger 浮于表面 | "只有金策, 另外一个呢" |
| 5 | 只 2 个项目, 研究面太窄 | "可以去找其他项目, 不只这 2 个" |
| **6 (本文)** | **24 项目对标 + 30 模式 + Tier 分级** | (待审阅) |

### 9.2 方法论纠正

- **不要先下结论再找证据** — "toy" 是 dismissive label
- **不要用 stars 数判断质量** — QuantDinger 2K star 仍未扣手续费 / Quantopian 三件套停更但仍有人引用
- **不要把"现在没做"当成"不该做"** — UI 错判
- **跨项目对比要在 8+ 维度** — 单看 README 头 200 字判断不出深度
- **License 友好性必须前置过滤** — Apache 2.0 / MIT 友好可借鉴, GPL-3.0 / 自定义商禁不行
- **死项目要主动识别** — pushed 时间 > 12 月就是 stop, 不再当对标
- **扩大研究面要主动** — 不能等用户 push 5 次才扩

### 9.3 主动推到的 QM 没意识到的盲点 (本轮新发现)

1. **NautilusTrader (Rust+Python institutional grade)** — 之前完全没列入, vnpy 不是终点
2. **mlflow ML 生命周期管理** — QM ML 实验缺这层基础设施
3. **akshare 18K star** — 国内 Tushare 头部备选, 跟金策已用对位
4. **RD-Agent paper 学术价值** — 阶段 0 NO-GO 是工程原因, 学术价值仍在, 应深读 paper
5. **FinGPT (20K) / FinRobot (7K) LLM-for-finance 路径** — DEV_AI_EVOLUTION V2.1 设计的对位
6. **Quantopian 三件套全部停更 1+ 年** — alphalens/pyfolio/empyrical 不再对标
7. **vnpy 4.0 + Qlib 联姻**: vnpy.alpha 借 Alpha158 — **QM Phase 1.2 借鉴 Alpha158 路线被验证为中国量化主流路线**, 这是好消息
8. **QuantDinger Issue #52 (手续费没扣) 暴露 SaaS 营销 ≠ 实战核心扎实** — stars 不等于工程质量
9. **金策的"知识星球"营销 vs QuantDinger 的 Discord/YouTube 营销 vs QM 的 private** — 三种社区模式各有优劣
10. **Tier S 不是单一项目, 是 Qlib + RD-Agent + FinGPT + FinRobot + mlflow 组合** — 学术对位需要 5 个项目并读

---

## Part 10: 实施时间表 (供参考)

| 阶段 | 时间 | 内容 | 阻断条件 |
|---|---|---|---|
| 今晚-Sunday | 4-26 ~ 4-27 早 | 维护窗口 + handoff | 不打乱 |
| Monday 验证 | 4-27 09:00+ | MVP 3.1 真生产首触发观察 | 优先 |
| Tuesday | 4-28 | S2PEADEvent LIVE 评估 | Stage 4.2 |
| Week 18-19 | 4-28 ~ 5-11 | LL-076 真修复 (#6 + #7) + Quantopian 三件套清理 | 工程债 |
| Week 20-22 | 5-12 ~ 6-1 | MVP 3.2-3.5 串行交付 | Wave 3 完结 |
| Week 23-26 | 6-2 ~ 6-29 | Wave 4 Observability (#8-#15) | 4 周 |
| Week 27-32 | 6-30 ~ 8-10 | Wave 5 Operator UI (#16-#18) | 6 周 |
| Week 33+ | 8-11+ | Wave 6+ 远期 (#20-#28 评估) | 远期 |

**总评估**: 2026 全年路线明确, 工程债清理 + Wave 3-5 串行 + 远期 Wave 6+ 候补.

---

## 附录 A: 24 项目快速参考表

| # | 项目 | star | License | last push | 用途分类 | QM 借鉴度 |
|---|---|---:|---|---|---|---|
| 1 | Qlib | 41K | MIT | 2026-04-22 | Alpha + ML | ⭐⭐⭐⭐ |
| 2 | RD-Agent | 13K | MIT | 2026-04-22 | AI Agent | ⭐⭐⭐⭐ |
| 3 | vnpy | 40K | MIT | 2026-04-22 | 实盘 + ML | ⭐⭐⭐ |
| 4 | NautilusTrader | 22K | LGPL-3.0 | 2026-04-25 | 实盘 (Rust) | ⭐⭐⭐ (远期) |
| 5 | Freqtrade | 49K | GPL-3.0 ⚠️ | 2026-04-25 | crypto | ⭐ |
| 6 | Lean | 19K | Apache-2.0 | 2026-04-24 | 多市场 | ⭐⭐ |
| 7 | Hummingbot | 18K | Apache-2.0 | 2026-04-22 | crypto MM | 0 |
| 8 | Hikyuu | 3K | Apache-2.0 | 2026-04-23 | 国内 C++ | ⭐ |
| 9 | rqalpha | 6K | Other | 2026-04-22 | 米筐 | ⭐ |
| 10 | lumibot | 1K | GPL-3.0 | 2026-04-25 | multi-broker | ⭐ |
| 11 | jesse | 8K | MIT | 2026-04-25 | crypto AI | ⭐ |
| 12 | OpenBB | 66K | Other | 2026-04-25 | 数据 + UI | ⭐⭐⭐ |
| 13 | akshare | 18K | MIT | 2026-04-23 | 国内数据 | ⭐⭐ |
| 14 | 金策 | 469 | 自定义 ❌ | 2026-04-24 | 数据 + ensemble | ⭐⭐ (设计借, 不抄码) |
| 15 | QuantDinger | 2K | Apache-2.0 | 2026-04-24 | LLM + UI | ⭐⭐ |
| 16 | mlflow | 25K | Apache-2.0 | 2026-04-25 | ML 生命周期 | ⭐⭐⭐ |
| 17 | FinGPT | 20K | MIT | 2026-04-24 | LLM-for-finance | ⭐⭐ (论文) |
| 18 | FinRobot | 7K | Apache-2.0 | 2026-04-3 | AI Agent | ⭐⭐ (论文) |
| 19 | vectorbt | 7K | Other | 2026-04-25 | Numba 回测 | ⭐ (已知评估) |
| 20 | backtesting.py | 8K | AGPL-3.0 ⚠️ | 2025-12-20 | 轻量回测 | 0 (license) |
| 21 | bt | 3K | MIT | 2026-3-31 | 组合回测 | ⭐ |
| 22 | gs-quant | 10K | Apache-2.0 | 2026-04-23 | Goldman | ⭐ (远期期权) |
| 23 | pysystemtrade | 3K | GPL-3.0 ⚠️ | 2026-4-2 | 系统化交易 | ⭐ (论文) |
| 24 | zipline-reloaded | 2K | Apache-2.0 | 2026-01-06 | Quantopian fork | ⭐ |
| 25 | river | 6K | BSD-3 | 2026-04-23 | 在线 ML | ⭐ (远期) |
| 26 | FinRL | 15K | MIT | 2026-04-5 | RL trading | 0 (路线证伪) |
| 27 | TensorTrade | 6K | Apache-2.0 | 2026-2-19 | RL 环境 | 0 |
| **死** | backtrader | 21K | GPL-3.0 | 2024-08-19 | 已停更 | ❌ |
| **死** | pyfolio | 6K | Apache-2.0 | 2023-12-23 | 已停更 | ❌ |
| **死** | empyrical | 1K | Apache-2.0 | 2024-07-26 | 已停更 | ❌ |
| **死** | catalyst | 3K | Apache-2.0 | 2022-11-26 | 已停更 | ❌ |
| **死** | eiten | 3K | GPL-3.0 | 2022-7-30 | 已停更 | ❌ |
| **死** | ML4Trading repo | 17K | N/A | 2024-08-18 | 教材代码 | ❌ |

---

## 附录 B: 关键学术论文清单 (Wave 4+ AI 闭环阅读)

- arxiv 2505.15155 *R&D-Agent-Quant: Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization* (微软 RD-Agent)
- FinGPT 系列论文 (AI4Finance Foundation)
- FinRobot tech report (AI4Finance Foundation)
- Harvey, Liu, Zhu 2016 *...and the Cross-Section of Expected Returns* (QM 已用 t > 2.5 硬性下限)
- AlphaAgent KDD 2025 (QM 已用 G9 Gate 新颖性)

---

**文档版本**: v1.0 (2026-04-26 0930+)
**审阅状态**: pending user review
**下一步**: 用户批准后:
1. 写 `memory/project_borrowable_patterns.md` 配套索引
2. ~~Wave 5 UI 启动时, 写 `docs/adr/ADR-011-wave-5-operator-ui.md`~~ → **2026-04-26 已 fast-tracked 写入 [ADR-012](../adr/ADR-012-wave-5-operator-ui.md)** (因用户 4-26 已明确决策, 不需要等 Wave 5 启动)
3. Wave 4 Observability 启动时, 写 MVP 4.x 设计稿
4. Quantopian 三件套清理 grep 检查 (P0 立即可做)
