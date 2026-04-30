# Independence Review — 模块解耦真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 5 / independence/01
**Type**: 跨领域 + 模块解耦 (sustained framework §4.2)

---

## §1 模块独立性真测 (sustained framework §4.2)

实测 sprint period sustained sustained:

| 模块失效 → 多少下游死? | 真测 candidate |
|---|---|
| **DataPipeline 失效** | 全 fetcher → factor_values 入库 → IC → 回测 → PT 信号 全断 | 🔴 P0 单点 |
| **SignalComposer 失效** | 回测 + PT 信号生成 全断 (sprint period sustained PR #116 共用) | 🔴 P0 单点 |
| **BacktestEngine 失效** | 回测 + WF + regression 全断 | 🟡 影响范围 design 但生产可继续 |
| **RiskEngine 失效** | 真生产风控 0 (4-29 已 PAUSED, 实测 sustained) | 🟡 已 PAUSED 4-29 后 |
| **broker_qmt 失效** | 真账户 sell 路径断 (panic SOP 候选 ad-hoc) | 🔴 真金 P0 单点 (sustained external/01 §2.1 F-D78-53) |
| **DingTalk 失效** | alert 0 通知 (sustained external/01 §2.3 F-D78-55) | 🟡 P1 |
| **LiteLLM 失效** | (待接入, 未 sustained) | (N/A) |

---

## §2 import graph 真测

实测真值 (本审查未深 grep import graph):
- xtquant 唯一 import in scripts/qmt_data_service.py (CLAUDE.md sustained sustained)
- 跨模块 import 真 graph 0 sustained sustained 度量 (无 pylint --output-format=text or import-linter sustained)

候选 finding:
- F-D78-91 [P2] 跨模块 import graph 真 dependency 0 sustained 度量 (无 pylint / import-linter sustained), 候选 sub-md import graph 详查

---

## §3 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-91 | P2 | 跨模块 import graph 真 dependency 0 sustained 度量, 候选 sub-md import graph 详查 |

(其他单点风险 sustained external/01 + risk/02, 本 sub-md 不重复.)

---

**文档结束**.
