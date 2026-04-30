# Adversarial — Unknown Unknowns

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 6 / blind_spots/04
**Date**: 2026-05-01
**Type**: adversarial review (sustained framework §5.4 — Rumsfeld Unknown Unknowns)

---

## §0 元说明

framework §5.4 沉淀: "Claude+user 都没意识到的事. 按 Rumsfeld 定义不可 enumerate, 但 CC 实测可能发现".

CC 主动思考: 项目实际状态 vs 双方意识真值 — 候选 unknown unknown 沉淀.

---

## §1 候选 Unknown Unknowns (CC 实测推断)

### 1.1 ⚠️ U1: 真账户 broker 视角 vs 项目视角 disconnect

**Claude+User 共同未意识**: 真账户 broker (国金 miniQMT) 视角看本项目是什么? Claude 与 user 全部聚焦项目内部 (cb_state / position_snapshot / Risk Framework / etc), 但 broker 视角看到:

- 本账户 (81001102) 实际交易模式 (vs broker 监管 标记)
- 4-29 -29% 跌停事件 broker 端是否有风控 alert? (broker 端可能有自己的风控 vs 项目端 0)
- 真金 ¥993,520.66 中是否含已结算资金 vs 待结算 (sprint state cash 字段单独显示)
- broker 月报 / 季报 vs 项目内部 cb_state 跨源 verify (本审查未深查)

**unknown 程度**: ✅ 真 unknown — Claude+user 共同未深查 broker 视角

**finding candidate**:
- F-D78-35 [P2] Unknown unknown — broker 视角看项目状态未深查, broker 端风控 / 月报 / 资金状态分类等真值未实测

---

### 1.2 ⚠️ U2: 项目运行的真硬件成本

**Claude+User 共同未意识**: 项目真硬件成本累计?

- 32GB RAM 单机 sustained 运行 ~60 day (3-25 → 5-01)
- TimescaleDB 60+ GB / minute_bars 36 GB / moneyflow 4.4 GB / etc
- GPU (RTX 5070 12GB) 真利用率 (CLAUDE.md cu128 提了真用过吗) — F-D78-候选 sub-md 18_gpu_usage_history
- 电费 + 服务器维护 + 第三方源费用 (Tushare 商业 ToS) 真累计

**unknown 程度**: ✅ 真 unknown — Claude+user 共同未深查硬件成本

**finding candidate**:
- F-D78-36 [P2] Unknown unknown — 项目硬件成本累计真值未深查 (32GB RAM + 60+ GB DB + GPU + 第三方 API + 电费 等)

---

### 1.3 ⚠️ U3: 项目代码遗留风险 (legacy code 未识别)

**Claude+User 共同未意识**: 项目代码 846 *.py 中, 多少是真生产 path 真用 vs 历史遗留死码?

- sprint period 沉淀 多次"死码清理" (sprint period sustained PMS v1 deprecate / dual-write Beat 退役 / 等)
- 但本审查 grep 未深查死码总量 + 真比例
- ruff / mypy 全 repo 实测 (snapshot/02_db_schema 留 verify) 未跑

**unknown 程度**: ⚠️ 部分 known (sprint period 局部 dead code 沉淀) but 全 repo 真比例 unknown

**finding candidate**:
- F-D78-37 [P3] 项目 846 *.py 死码 + 真生产 path 比例未深查, 候选 ruff / mypy 全 repo 静态扫描

---

### 1.4 ⚠️ U4: 第三方源 (Tushare / Baostock / QMT) 真稳定性 + 真 ToS 风险

**Claude+User 共同未意识**: 第三方数据源真稳定性?

- Tushare 商业 ToS — sprint period sustained 沉淀 sustained, 但真 ToS 文档 vs 项目实际使用 真 compliance 未深查
- Baostock 免费 5min K 线 — 真稳定性 (项目 sustained 假设 sustained, 但 5 年历史 vs 未来稳定性 unknown)
- QMT broker — 商业 broker, 项目唯一交易接口, 单点失败风险

**unknown 程度**: ✅ 真 unknown — Tushare/Baostock 真 ToS + 稳定性未深查

**finding candidate**:
- F-D78-38 [P2] Unknown unknown — 第三方源 (Tushare / Baostock / QMT) 真 ToS + 真稳定性未深查, 单点失败 + 商业 ToS 风险

---

### 1.5 ⚠️ U5: 法规 / 合规风险 (个人量化交易边界)

**Claude+User 共同未意识**: 个人量化交易 vs 监管法规边界?

- 项目自动化下单 (broker_qmt 单边 sell only sustained 但 design 含 buy 候选)
- 个人账户 (81001102) 自动交易是否需 broker 合规标记?
- 真金交易 vs 模拟交易合规边界 (LIVE_TRADING_DISABLED=True sustained 但 design 含 live)

**unknown 程度**: ✅ 真 unknown — Claude+user 共同未深查合规边界

**finding candidate**:
- F-D78-39 [P2] Unknown unknown — 个人量化交易合规法规边界未深查 (broker 合规标记 / 自动化标记 / 真金 vs 模拟边界)

---

### 1.6 ⚠️ U6: 项目 Anthropic LLM 资源 cost (sprint period 累计真值)

**Claude+User 共同未深查**: Anthropic API token cost 真累计?

- sprint period sustained 22 PR 跨日, 每 PR 多次 plan + execute + reviewer 调用
- LLM call 累计 token cost 真值未深查 (snapshot/14_llm_resource 留 verify)
- LLM cost ROI 评估 (vs 项目产出, 沿用 blind_spots/02_user_assumptions §1.3)

**unknown 程度**: ⚠️ 部分 known (Anthropic plan 月费但 token cost 累计未深查) 

**finding candidate**:
- F-D78-40 [P2] LLM cost 累计真值未深查, sprint period 22 PR 跨日多次调用累计 token cost 候选 sub-md 14_llm_resource

---

### 1.7 ⚠️ U7: 用户健康 + 持续性风险

**Claude+User 共同未意识**: User 全职单人项目, 健康 + 持续性 (bus factor) 真风险?

- D72-D78 4 次反问 + 多次跨日 sustained 工作 (sprint period sustained "工作执行力要求高" user_profile)
- User 退出 / 度假 / 健康问题 → 项目 idle / auto-recover 能力 (Servy auto-restart? schtask 自动?) — F-D78-13 (git history 90 day, bus factor 已 finding)
- 项目长期可持续性 vs user 全职机会成本 (沿用 blind_spots/02_user_assumptions §1.3)

**unknown 程度**: ⚠️ user 健康 + 持续性 — Claude+user 共同避谈

**finding candidate**:
- F-D78-41 [P1] Unknown unknown — User 健康 + 持续性 + 项目 bus factor 风险, 项目无 user N 月能 sustain 真测真值未深查

---

### 1.8 ⚠️ U8: 数据演进未来风险 (本审查 sprint period sustained 数据 vs 未来 N 年)

**Claude+User 共同未意识**: 项目数据 (factor_values 840M + minute_bars 190M + etc) 沉淀 sustained 但**未来 N 年数据演进**?

- A 股市场结构变化 (北交所 / 注册制 / 量化监管收紧 / etc) 对因子有效性影响
- Tushare / Baostock 数据源真未来 (商业 ToS 涨价 / 服务终止 / etc)
- TimescaleDB hypertable scaling 上限 (200+ chunks, 后续多少年数据可装?)

**unknown 程度**: ✅ 真 unknown — Claude+user 共同未深查未来数据演进

**finding candidate**:
- F-D78-42 [P2] Unknown unknown — 项目数据未来 N 年演进风险 (市场结构 / 第三方源 / scaling) 未深查

---

## §2 元 verify

### 2.1 反 §7.9 被动 follow 自查
CC 主动扩 8 unknown unknowns (framework §5.4 仅写 "Rumsfeld 不可 enumerate"), CC 实测推断扩 ✅

### 2.2 LL-098 第 13 次 stress test verify
本 md 末尾 0 forward-progress offer ✅

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-35 | P2 | Unknown unknown — broker 视角看项目状态未深查 (broker 端风控 / 月报 / 资金分类) |
| F-D78-36 | P2 | Unknown unknown — 项目硬件成本累计真值未深查 (32GB RAM + 60+ GB DB + GPU + 第三方 + 电费) |
| F-D78-37 | P3 | 项目 846 *.py 死码 + 真生产 path 比例未深查, 候选 ruff / mypy 全 repo 静态扫描 |
| F-D78-38 | P2 | Unknown unknown — 第三方源真 ToS + 真稳定性 + 单点失败风险未深查 |
| F-D78-39 | P2 | Unknown unknown — 个人量化交易合规法规边界未深查 |
| F-D78-40 | P2 | LLM cost 累计真值未深查 |
| **F-D78-41** | **P1** | **Unknown unknown — User 健康 + 持续性 + 项目 bus factor 风险未深查** |
| F-D78-42 | P2 | Unknown unknown — 项目数据未来 N 年演进风险未深查 |

---

**文档结束**.
