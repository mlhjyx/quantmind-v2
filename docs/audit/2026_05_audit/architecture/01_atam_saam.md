# Architecture Review — ATAM + SAAM + V3 Gap

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / architecture/01
**Type**: 评判性 + ATAM (quality attribute trade-off) + SAAM (vs scenario)

---

## §1 ATAM 评估 (5+1 风控架构 / V3 / 6 块基石 / Wave 1-4 / 12 framework)

### 1.1 5+1 层风控架构 ATAM

| Quality Attribute | T1.3 V3 design 沉淀 | 真测 | trade-off |
|---|---|---|---|
| **Real-time enforcement** | L0 event-driven design | ❌ 0 实施 | sustained F-D78-21/25 路线图哲学局限 |
| **Throughput** | L1 batch 14:30 | ❌ PAUSED 4-29 | sustained F-D78-7 暂停后真生产 vacuum |
| **Modifiability** | 5+1 层模块化 | ⚠️ design 沉淀 但 1/6 实施 | sustained ADR-022 §7.3 缓解原则 |
| **Maintainability** | T1.3 design doc 342 行 sustained | ⚠️ design 沉淀 0 实施 | sustained F-D78-22 真接入点路径未 demonstrate |
| **Testability** | 5+1 层测试 candidate | ❌ 5 层 0 实施 → 0 测试 | sustained N/A |
| **Safety** (真金) | LIVE_TRADING_DISABLED + EXECUTION_MODE 双锁 | ✅ 真金 0 风险 (E5/E6 sustained) | ✅ trade-off 合理 |

**判定**: ⚠️ 5+1 层 ATAM design 沉淀完整 vs 实施 1/6, **architecture vs implementation 重大 gap** (sustained F-D78-22 + risk/02 §1)

---

### 1.2 6 块基石 ATAM (sustained governance/01_six_pillars_roi)

(详 governance/01 §2 总评 sustained sustained)

---

### 1.3 Wave 1-4 ATAM (sustained risk/01 5 Why)

| Quality Attribute | Wave 1-4 设计哲学 | 真测 | trade-off |
|---|---|---|---|
| **Modifiability** | 12 framework + 6 升维 模块化 | ✅ 设计 sustained | ⚠️ 12 framework + 6 升维 candidate over-engineering (sustained F-D78-28 1 人项目走企业级架构) |
| **Real-time enforcement** | batch + monitor 哲学 | 🔴 L0 event-driven 漏维度 | sustained F-D78-21/25 路线图哲学局限 (P0 治理) |
| **Performance** | TimescaleDB + Parquet 1000x + GPU 6.2x | ✅ sprint period sustained sustained | ✅ |
| **Reliability** | Servy 4 服务 sustained + Wave 4 Observability | 🔴 5 schtask 持续失败 cluster (sustained F-D78-8) | sustained "Wave 4 完工" 推翻 |
| **Security** (真金) | LIVE_TRADING_DISABLED + EXECUTION_MODE 双锁 | ✅ 真金 0 风险 | ✅ |

**判定**: 🔴 Wave 1-4 路线图设计哲学局限, batch + monitor vs L0 event-driven enforce 哲学外维度, sustained F-D78-21/25 P0 治理 sustained

---

## §2 SAAM 评估 — 4-29 痛点 scenario adapt 度

**Scenario**: 2026-04-29 PT 真生产 -29% 跌停事件 (688121.SH) + 000012 -10% 大跌, risk_event_log 0 真生产触发.

**架构 adapt 度**:
- 现 Wave 1-4 batch + monitor 哲学 → 4-29 类 event 0 实时 enforce
- L0 event-driven design 沉淀 (T1.3 V3) but 0 实施
- 真生产 enforce path: 5min Beat → 14:30 daily Beat → schtask audit log → user 手工
- **真 5min Beat 后续 4-29 后已 PAUSED** (sustained snapshot/03 §2.2)
- 真生产 4-29 类事件 detect time: ~10:25 (跌停后) → user 手工 emergency_close ~10:43 (~18 min lag)

**SAAM 判定**: 🔴 现架构对 4-29 scenario adapt 度极低 (0 实时 detect / 0 实时 enforce / 18 min lag user 手工), sustained F-D78-21/25 路线图哲学局限再印证

---

## §3 跨模块边界 contract (4 接口)

实测 sprint period sustained sustained:

| 接口 | sprint period sustained | 真 enforce |
|---|---|---|
| DataPipeline | 唯一入库通道 (铁律 17), 例外 subset UPSERT (LL-066) | ✅ sustained |
| SignalComposer + PortfolioBuilder | sprint period MVP 3.3 PR #116 共用 | ✅ sustained but 真生产 0 active (4-29 后) |
| RiskEngine | T1.3 V3 5+1 层 D-L0~L5 | ⚠️ design 沉淀, 1/6 实施 |
| BacktestEngine | regression max_diff=0 (铁律 15) | ⚠️ 真 last-run 待 verify (F-D78-24/84) |

---

## §4 Long-term 演进路径 (sustained framework §3.1 架构)

(沿用 EXECUTIVE_SUMMARY §4 战略候选 仅候选 0 决议)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| (sustained sustained 多 finding 复述) | (sustained F-D78-21/25/28 P0 治理) | 5+1 层 + Wave 1-4 + 6 块基石 ATAM 评估 sustained sustained F-D78 sustained sustained |

**本 sub-md 0 新 finding 编号** (论据沉淀 + ATAM 评估方法 cite, 沿用 sprint period sustained 多 P0 治理 finding 论据).

---

**文档结束**.
