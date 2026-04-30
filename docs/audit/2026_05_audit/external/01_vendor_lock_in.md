# External Review — Vendor Lock-in (CC 扩领域)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 4 / external/01
**Date**: 2026-05-01
**Type**: 评判性 (CC 主动扩领域, sustained framework_self_audit §3.1 D5)

---

## §0 元说明

framework_self_audit §3.1 D5 决议: "Vendor lock-in (Tushare/QMT/DingTalk/OpenAI/Anthropic 替换难度) — 单点失败风险 + ToS 风险, 与"安全"重叠但独立 sub-md".

本 md 是 CC 扩领域 - 实测 vendor 单点失败 + 替换难度.

---

## §1 vendor list + 真依赖度

| Vendor | 角色 | 真依赖度 | 替换难度 | 单点失败影响 |
|---|---|---|---|---|
| **国金 miniQMT** | 唯一 broker | 100% | 极高 (broker 接口 + 真账户) | 真金交易停 (PT + Live 全停) |
| **xtquant** | broker SDK (Python) | 100% (生产入口 scripts/qmt_data_service.py) | 高 (替换 broker 后 SDK 也变) | 同上 |
| **Tushare** | 主数据源 (因子 + 行情) | ~50% | 中 (有 AKShare 备用) | 数据更新停 |
| **Baostock** | 5min K 线源 (190M 行 minute_bars) | ~30% | 中 (有 Tushare 5min 备用 但商业付费) | minute_bars 增量停 |
| **AKShare** | 备用数据源 | ~10% | 低 | 备用 N/A |
| **DingTalk** | 告警通道 | 100% (sustained sustained 唯一 alert 通道) | 中 (替换 Slack/Email) | alert 0 通知 |
| **PostgreSQL + TimescaleDB** | DB | 100% | 极高 (60+ GB 数据迁移) | DB 全停 |
| **Redis** | event bus + cache | 100% | 中 (替换 RabbitMQ 等) | event bus + cache 全停 |
| **Servy** | 服务管理 | 100% (replaced NSSM 2026-04-04) | 中 (替换 NSSM 或 native Windows Service) | 服务管理全停 |
| **Anthropic Claude** | LLM (Claude.ai 战略 + CC 实施) | 100% | 高 (协作模式重设计) | 协作模式全停 |
| **OpenAI / DeepSeek** | (备用 LLM, sprint state .env DEEPSEEK_API_KEY 沉淀) | ~5% | 低 (备用 N/A) | 备用 N/A |

---

## §2 关键单点失败评估

### 2.1 🔴 国金 miniQMT + xtquant (broker 单点)

- 真账户 ¥993,520.66 全在国金 miniQMT
- xtquant 是唯一 import xtquant 生产入口 (CLAUDE.md sustained sustained sustained)
- 替换难度: 替换 broker → 真账户迁移 + xtquant SDK 替换 + 全代码 broker_qmt 重写
- 单点失败影响: PT + Live 全停, 真金 frozen

**finding**:
- F-D78-53 [P0 治理] 国金 miniQMT + xtquant broker 单点失败风险, 真账户 ¥993,520.66 全 lock-in, 替换难度极高. 候选 multi-broker abstraction layer 设计 (但本审查 0 决议)

### 2.2 🔴 PostgreSQL + TimescaleDB (DB 单点)

- 60+ GB 数据 (minute_bars 36 GB + factor_values + moneyflow + etc) 全在 PG 16.8 + TimescaleDB 2.26.0
- 替换难度: TimescaleDB hypertable + Postgres 特性 (CTE / FK / 等) 替换困难
- 单点失败影响: DB 全停 → 全应用停

**finding**:
- F-D78-54 [P1] PostgreSQL + TimescaleDB DB 单点失败风险, 60+ GB 数据迁移 候选困难. 沿用 backup SOP (QM-DailyBackup schtask 2:00 sustained sustained ✅) 但全 fail-over SOP 0 sustained

### 2.3 ⚠️ DingTalk (alert 单点)

- 唯一 alert 通道 (sprint period sustained 沉淀)
- DINGTALK_SECRET=空 (F-D78-3, signature 1 锁)
- 替换难度: 中 (Slack / Email / SMS / 等)
- 单点失败影响: alert 0 通知 → silent failure (沿用 5 schtask cluster F-D78-8)

**finding**:
- F-D78-55 [P1] DingTalk alert 单点失败风险, signature 1 锁 (F-D78-3), 候选 multi-channel alert (Slack/Email backup)

### 2.4 ⚠️ Anthropic Claude LLM (协作单点)

- 项目协作模式 100% Claude (Claude.ai 战略 + CC 实施)
- 沿用 blind_spots/02_user_assumptions §1.4 F-D78-32 协作有效性 candidate 推翻
- 单点失败影响: 协作模式全停 → user 0 自动化协助
- DEEPSEEK_API_KEY .env 沉淀但**实测 0 用** (sprint period sustained 沉淀但未 sustained 协作)

**finding**:
- F-D78-56 [P2] Anthropic Claude 协作单点失败风险, DEEPSEEK 备用未 sustained 协作, 候选 multi-LLM 协作模式 (但本审查 0 决议)

---

## §3 ToS 风险 (沿用 blind_spots/04 §1.4 F-D78-38)

| Vendor | 商业 ToS | 风险 |
|---|---|---|
| Tushare | 商业 ToS sustained | 涨价 / 限频 / 终止服务 candidate |
| 国金 miniQMT | broker ToS sustained | 自动化标记 / 个人账户合规 candidate |
| Anthropic Claude | API ToS sustained | 调用频率 / 内容审查 / 终止服务 candidate |
| DingTalk | 免费 webhook | 限频 / 终止服务 candidate |

**finding**:
- F-D78-38 (复) [P2] 第三方源真 ToS + 真稳定性未深查

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-53** | **P0 治理** | 国金 miniQMT + xtquant broker 单点失败, 真账户 ¥993,520.66 全 lock-in, 候选 multi-broker abstraction |
| F-D78-54 | P1 | PostgreSQL + TimescaleDB DB 单点失败, 60+ GB 数据 + TimescaleDB hypertable 迁移困难 |
| F-D78-55 | P1 | DingTalk alert 单点失败, signature 1 锁, 候选 multi-channel backup |
| F-D78-56 | P2 | Anthropic Claude 协作单点失败, DEEPSEEK 备用未 sustained, 候选 multi-LLM |

---

**文档结束**.
