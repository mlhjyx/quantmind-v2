# PRIORITY_MATRIX — SYSTEM_AUDIT_2026_05 (Phase 1 + Phase 2)

**目的**: 全 finding 严重度矩阵 (P0真金/P0治理/P1/P2/P3 5 级)
**Status**: ✅ Phase 1 完成 (PR #182 merged) + ✅ Phase 2 主体完成

---

## 严重度定义

| 级别 | 定义 | SOP |
|---|---|---|
| **P0 真金** | 真金 ¥993K 直接风险 | STOP 反问 user 立即 |
| **P0 治理** | 项目治理崩溃 / sprint period 重大假设推翻 | 沉淀 + audit 末尾决议是否 STOP 反问 user 扩 scope |
| **P1** | 重要, 影响下次 sprint period 决策 | 沉淀, audit 末尾汇总 |
| **P2** | 一般, 供战略对话参考 | 沉淀 |
| **P3** | 微小, sprint period anti-pattern 候选 | 沉淀 |

---

## P0 真金 (0 项 ✅)

E5/E6 sustained: LIVE_TRADING_DISABLED=True / EXECUTION_MODE=paper / xtquant 0 持仓 / cash=¥993,520.66

---

## P0 治理 (10 项 ⚠️)

| ID | 描述 | 来源 sub-md |
|---|---|---|
| **F-D78-8** | 5 schtask 持续失败 cluster, sprint period sustained "Wave 4 Observability ✅" 重大推翻 — RiskFrameworkHealth 自愈机制本身失败 silent failure | snapshot/03 §4 |
| **F-D78-19** | sprint period 22 PR 是治理 sprint period (0 业务前进), "6 块基石治理胜利" 部分推翻 (3/6 ✅) | governance/01 §3 |
| **F-D78-21** | 4-29 PT 暂停事件真根因 (5 Why): Wave 1-4 路线图设计哲学局限 = batch + monitor, L0 event-driven 哲学外维度 | risk/01 §2-3 |
| **F-D78-25** | 共同假设 "Wave 路线图最佳" 推翻, 4-29 真金 ~¥6,479 损失印证 | blind_spots/03 §1.1 |
| **F-D78-26** | 共同假设 "4 源协作有效" 推翻, 4 源 N×N 同步矩阵 sustained 漂移 | blind_spots/03 §1.2 |
| **F-D78-33** | User 项目目标 (alpha 15-25%) vs 真测投入产出 (治理+Observability) disconnect, 真目标候选 = 治理 maturity 而非 alpha | blind_spots/02 §1.5 |
| **F-D78-48** | 项目 bus factor 极低. 接手者 onboarding 极困难 | business/01 §3 |
| **F-D78-53** | 国金 miniQMT + xtquant broker 单点失败 (¥993,520.66 全 lock-in) | external/01 §2.1 |
| **F-D78-61** | risk_event_log 仅 2 entries 全 audit log 类, 0 真生产风控触发, 沦为 audit log 写入位 (沿用 4-29 5 Why 路线图哲学局限再印证) | risk/02 §1 |
| **F-D78-62** | event_outbox = 0/0 真测, sprint period sustained "Outbox Publisher MVP 3.4 batch 2 ✅" + Beat 30s 沉淀, 真生产 0 真使用. event sourcing 架构 candidate 仅 design 0 enforce | risk/02 §2 |
| **F-D78-76** | 测试基线数字漂移 +1212 tests since Session 9 baseline (4076 vs 2864), 铁律 40 baseline 数字 0 sync update | testing/01 §2 |
| **F-D78-89** | 路径 3 自 4-29 后 真生产风控 enforce 0 active, "Wave 3 MVP 3.1 Risk Framework 完结" 推翻再印证 | end_to_end/01 §3 |

---

## P1 (15 项)

| ID | 描述 | 来源 |
|---|---|---|
| F-D78-27 | 共同假设 "三领域 V3 同步升级" 推翻, 候选风控 V3 独立优先 | blind_spots/03 §1.4 |
| F-D78-28 | 共同假设 "1 人量化走企业级架构" 候选推翻 | blind_spots/03 §1.5 |
| F-D78-29 | 共同假设 "PT 重启 5d dry-run = 充分条件" 推翻 | blind_spots/03 §1.6 |
| F-D78-30 | 共同假设 "audit 沉淀越多越好" 候选推翻 | blind_spots/03 §1.7 |
| F-D78-31 | User 时间投入 vs 项目产出经济性候选推翻 | blind_spots/02 §1.3 |
| F-D78-32 | 协作模式 (Claude.ai + CC + memory + repo 4 源) 候选推翻有效性 | blind_spots/02 §1.4 |
| F-D78-41 | Unknown unknown — User 健康 + 持续性 + 项目 bus factor 风险 | blind_spots/04 §1.7 |
| F-D78-49 | panic SOP 沉淀 0 (4-29 ad-hoc) | business/01 §4 |
| F-D78-50 | 跨源 reconciliation SOP 沉淀 0, broker → DB position_snapshot 4-29 后 0 触发 | operations/01 §4 |
| F-D78-51 | 新 Claude session onboard 难度高, onboard SOP 0 自动化 | governance/02 §2 |
| F-D78-52 | sprint state 关键 context 在 Anthropic memory (not repo), 新接手者 0 access | governance/02 §4 |
| F-D78-54 | PostgreSQL + TimescaleDB DB 单点失败 | external/01 §2.2 |
| F-D78-55 | DingTalk alert 单点失败 | external/01 §2.3 |
| **F-D78-59** | Model Risk Management 框架 0 sustained (model card / independent validation / auto stress test 全缺) | factors/01 §2 |
| **F-D78-63** | alert_dedup + Wave 4 MVP 4.1 alert 真触发统计 0 真测 | risk/02 §2 |
| **F-D78-70** | pip-audit 未装 in .venv, 0 sustained 漏洞扫描 | snapshot/06 §2 |
| **F-D78-85** | sim-to-real gap 真测候选 — WF OOS Sharpe=0.8659 vs 真期间 PT NAV ~-0.65% / Sharpe ~0 (60 day) | backtest/01 §2 |
| **F-D78-88** | 路径 2 (PT) 自 4-29 后 0 active, prerequisite 推翻 | end_to_end/01 §2 |
| **F-D78-90** | 路径 4 (告警→user→broker) 真 last-trigger 0 sustained, panic SOP 0 sustained | end_to_end/01 §4 |
| **F-D78-92** | 未来 PT 重启 + Wave 5+ + V3 风控 路径全依赖未 verify 的当前假设 | temporal/01 §3.4 |
| **F-D78-104** | Servy 4 服务 PRR checklist 关键 5+ 项 ❌/🔴 | operations/02 §1.2 |
| **F-D78-105** | DR 真演练 0 sustained, restore 真 verify 0 sustained, RTO/RPO unknown | operations/02 §3 |

---

## P2 (40+ 项)

(详 sub-md 中 finding 汇总段, 累计 P2 含 sustained 复述 sustained 多)

P2 关键新增 (Phase 2):
| ID | 描述 | 来源 |
|---|---|---|
| F-D78-56 | Anthropic Claude 协作单点失败 | external/01 §2.4 |
| F-D78-57 | sprint state CLAUDE.md 写 "factor_id" 字段, 真 schema 是 `factor_name` | factors/01 §1.1 |
| F-D78-58 | factor_values 276 distinct vs factor_ic_history 113, 163 因子 raw 但 0 IC 入库 | factors/01 §1.1 |
| F-D78-60 | CLAUDE.md "BH-FDR M=213" 数字漂移 (Phase 3B/3D/3E 后续未同步) | factors/01 §3 |
| F-D78-64 | ruff 6 errors (3 unique rules SIM102 ×4 / B905 ×1 / E902 ×1) — CLAUDE.md "提交前 ruff check" enforcement 失败 | code/01 §1 |
| F-D78-65 | mypy 全 repo 0 跑过本审查 | code/01 §3 |
| F-D78-66 | sprint period "死码清理" 真删除 vs 仅 stop calling 候选 verify | code/01 §4 |
| F-D78-67 | 铁律 31 Engine 层 enforcement 真 grep verify 候选 | code/01 §5 |
| F-D78-69 | pip list --outdated 26 outdated dependencies | snapshot/06 §1 |
| F-D78-71 | NPM 依赖 + npm audit 0 跑过本审查 | snapshot/06 §3 |
| F-D78-72 | secret rotation 历史 0 sustained sustained | security/01 §2.2 |
| F-D78-74 | DingTalk webhook URL 含 access_token, 0 sustained URL leak detection | security/01 §3 |
| F-D78-75 | broker_qmt design 含 buy 候选, 候选真金 attack surface 评估 | security/01 §4 |
| F-D78-78 | 测试金字塔真比例未 verify | testing/01 §3 |
| F-D78-79 | coverage 三维度 (line/branch/mutation) 0 sustained | testing/01 §4 |
| F-D78-80 | 24 fail baseline 真分类 (flaky/已知 stale/wontfix) 0 sustained | testing/01 §5 |
| **F-D78-81** | **D:/pgdata16 真测 = 225 GB**, sprint period CLAUDE.md "60+/172/159 GB" 数字漂移. **D:/quantmind-v2 = 63 GB / .venv = 1.9 GB. 总 ~290 GB disk** | snapshot/14 §1 |
| F-D78-82 | RAM 真测 0 sustained 监控, OOM 复发 detection 0 sustained | snapshot/14 §2 |
| F-D78-83 | GPU (RTX 5070 12GB cu128) 真利用率 0 sustained 监控 | snapshot/14 §3 |
| F-D78-84 | regression test 真 last-run timestamp 0 sustained sync update | backtest/01 §1 |
| F-D78-86 | 回测 vs 生产 SignalComposer 真同一性实测 verify 候选 | backtest/01 §3 |
| F-D78-87 | 路径 1 端到端真 last-trace + 真 dropoff 0 sustained | end_to_end/01 §1 |
| F-D78-91 | 跨模块 import graph 真 dependency 0 sustained 度量 | independence/01 §2 |
| F-D78-93~99 | 数据质量 6 维度 + 跨表 + 第三方源 + DataContract + Parquet cache 真测全 0 sustained | data/01 §1-5 |
| F-D78-100 | OOM 复发 detection + memory monitoring 0 sustained 自动化 | performance/01 §1 |
| F-D78-106 | runbook cc_automation 真覆盖度 0 sustained 度量 | operations/02 §4 |
| F-D78-108 | config_guard 真启动 raise 历史 0 sustained, 铁律 34 enforcement 真历史 candidate | snapshot/04+05 §1.3 |
| F-D78-109 | API + WebSocket 真清单 + 调用方 + deprecated 0 sustained 深查 | snapshot/04+05 §2 |
| F-D78-110 | Redis Streams 真 alive 数 0 sustained 监控 | snapshot/08+09+10 §1 |
| F-D78-111 | docs/* 700 *.md 真 last-update + 引用 graph + stale 0 sustained 深查 | snapshot/08+09+10 §3 |
| F-D78-112 | TIER0_REGISTRY 真 closed/待修分布 实测 verify 候选 | snapshot/08+09+10 §4 |

---

## P3 (~15 项)

(sustained Phase 1 + Phase 2 累计 sustained 复述, 详 sub-md 末尾)

新增 Phase 2 P3:
- F-D78-77 (3 unknown pytest mark / pytest config drift)
- F-D78-99 (Parquet cache invalidation 真 enforce 度 audit)
- F-D78-101 (latency critical paths 真 last-measure 0 sustained)
- F-D78-102 (throughput 真测 0 sustained)
- F-D78-103 (真生产并发约束 enforce 度 0 sustained)
- F-D78-107 (configs/*.yaml 真清单 0 sustained 深查)
- F-D78-113 (历史 PT 重启次数 + 失败原因 0 sustained 深查)
- F-D78-114 (历史误操作 git revert 历史 0 sustained 深查)
- (其他)

---

## 统计 (Phase 1 + Phase 2)

| 严重度 | Phase 1 | Phase 2 新增 | 累计 |
|---|---|---|---|
| P0 真金 | 0 | 0 | 0 ✅ |
| **P0 治理** | 7 | **5** (F-D78-61/62/76/89 + 复 F-D78-19/21/25/26/33/48/53/8) | **12** ⚠️ |
| P1 | 8 | **9** (F-D78-59/63/70/85/88/90/92/104/105) | **~17** |
| P2 | 22 | **27** (F-D78-56-114 跨多 sub-md sustained) | **~50** |
| P3 | 10 | **8** | **~18** |
| **小计** | **47** | **~50** | **~97** (含 sustained 复述) |

---

## sprint period sustained 假设推翻清单 (Phase 1+2 累计)

| 假设 | 真值 | 来源 finding |
|---|---|---|
| **Wave 4 MVP 4.1 Observability batch 1+2.1+2.2 ✅** | 5 schtask 持续失败 + RiskFrameworkHealth 自愈机制本身失败 silent failure | F-D78-8 |
| 6 块基石治理胜利 | 3/6 ✅ + 2/6 ⚠️ + 1/6 🔴 | F-D78-19 |
| 5 Beat schedule entries 生产激活 | active=4 + 2 PAUSED | F-D78-7 |
| DB 4-28 stale 19 行 | max(trade_date)=2026-04-27 错 1 天 | F-D78-1 |
| T0-19 已 closed | 仍 active (5-01 实测仍未自愈) | F-D78-4 |
| factor_values hypertable 152 chunks | chunk ID 已超 200+ | F-D78-9 |
| 根目录 7 *.md 上限 | 实测 8 (多 3 未授权) | F-D78-5 |
| **测试基线 2864 pass / 24 fail (Session 9)** | 真 4076 tests collected (+1212 since baseline) | F-D78-76 |
| **risk_event_log 30 day 0 行 (sprint state)** | 真 2 行 全 audit log 类 0 真生产触发 | F-D78-61 |
| **event_outbox MVP 3.4 batch 2 ✅** | 真 0/0 entries (event sourcing 0 真使用) | F-D78-62 |
| Wave 路线图最佳 | 路线图设计哲学局限 (batch+monitor) | F-D78-25 |
| 4 源协作有效 | N×N 同步矩阵 sustained 漂移 | F-D78-26 |
| User 项目目标 = alpha 15-25% | 真测投入产出 disconnect | F-D78-33 |
| 4-29 真根因 = 盘中 + 风控未设计 | 真根因深 3 层 = 路线图哲学局限 | F-D78-21 |
| **factor_id 字段 (CLAUDE.md sustained)** | 真 schema 是 factor_name | F-D78-57 |
| **CLAUDE.md "BH-FDR M=213"** | 真累积测试 ≥ 276 distinct factor_name (Phase 3B/3D/3E 未同步) | F-D78-60 |
| **CLAUDE.md "60+/172/159 GB DB"** | D:/pgdata16 真 225 GB | F-D78-81 |
| Wave 3 MVP 3.1 Risk Framework 完结 | 路径 3 自 4-29 后 真生产 enforce 0 active | F-D78-89 |

---

**文档结束**.
