# Architecture Review — 跨模块边界契约真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / architecture/02
**Date**: 2026-05-01
**Type**: 评判性 + 4 接口契约真测 (sustained framework §3.1 + architecture/01)

---

## §1 qm_platform 真清单 (CC 5-01 实测)

实测 `ls backend/qm_platform/`:

```
__init__.py
__pycache__/
_types.py
backtest/
backup/
ci/
config/
data/
eval/
factor/
knowledge/
observability/
resource/
risk/
signal/
strategy/
```

**真值**: **13 framework subdirs** (净 13: backtest / backup / ci / config / data / eval / factor / knowledge / observability / resource / risk / signal / strategy)

---

## §2 sprint period sustained sustained "12 Framework + 6 升维" 假设 推翻

### 2.1 sprint period sustained 沉淀

CLAUDE.md sustained sustained:
> **platform/**: ⭐ Wave 1+2+3 Platform 12 Framework + 6 升维 (data / factor / strategy / signal / backtest / eval / observability / config / ci / knowledge / resource / backup)

**真测 enumerate**: data + factor + strategy + signal + backtest + eval + observability + config + ci + knowledge + resource + backup = **12 + 1 (risk)** = 真 **13 framework subdirs**

### 2.2 +1 framework: risk (sprint period sustained 沉淀 漂移)

**真测**: `risk/` subdir 真存 (sustained Wave 3 MVP 3.1 Risk Framework PMSRule 落地路径)

**🔴 finding**:
- **F-D78-184** (替换上 1 编号, 实为 F-D78-185) **[P2]** sprint period sustained CLAUDE.md "12 Framework" 数字漂移 +1, 真 enumerate **13 framework subdirs (含 risk)**, sprint period sustained sustained 沉淀 多次 sustained sustained 但 risk subdir 沉淀 sprint period sustained sustained sustained 0 sync update CLAUDE.md "12" 数字

---

## §3 4 接口契约真测

### 3.1 DataPipeline (铁律 17 sustained)

实测 sprint period sustained sustained:
- 唯一入库通道 sustained sustained
- 例外: subset UPSERT (LL-066 sustained sustained sustained)
- F-D78-58 候选验证: 163 因子 raw 入库 但 0 IC 入库 — DataPipeline enforce partial

### 3.2 SignalComposer + PortfolioBuilder

实测 sprint period sustained sustained:
- sprint period MVP 3.3 PR #116 sustained sustained "PlatformSignalPipeline.generate" 共用
- 真生产 0 active (4-29 PT 暂停, 沿用 risk/02 §1 + end_to_end §2 sustained sustained)
- F-D78-86 候选 sustained 真同一性 实测 verify

### 3.3 RiskEngine

实测 sprint period sustained sustained:
- T1.3 V3 design 5+1 层 D-L0~L5 (PR #181 sustained sustained 沉淀)
- L1 ✅ 已落地 (PMSRule MVP 3.1+3.1b ~10 rules)
- L0/L2/L3/L4/L5 全 ❌ 0 实施
- 真生产: risk_event_log 仅 2 entries 全 audit log (F-D78-61 P0 治理 sustained)

### 3.4 BacktestEngine

实测 sprint period sustained sustained:
- regression max_diff=0 (铁律 15 sustained sustained sustained)
- 真 last-run 0 sustained verify (F-D78-24/84 sustained)
- factor_engine.py 重构 ✅ but engine 层 9 文件含 DB import (F-D78-150 P2)

---

## §4 跨模块边界 真 enforce 度

| 接口 | sprint period sustained | 真测 enforce |
|---|---|---|
| DataPipeline 唯一入库 | sustained 铁律 17 sustained | ⚠️ partial (LL-066 例外 + F-D78-58 163 因子 IC 漏) |
| SignalComposer 共用 | sprint period MVP 3.3 PR #116 | ⚠️ 真生产 0 active 4-29 后 (F-D78-89 P0 治理 sustained) |
| RiskEngine 5+1 层 | T1.3 V3 design sustained | 🔴 1/6 实施 + 真生产 0 enforce (F-D78-21/61 P0 治理 sustained) |
| BacktestEngine 复现 | 铁律 15 sustained | ⚠️ 真 last-run 0 sustained verify (F-D78-24/84) |

**finding**:
- F-D78-186 [P2] 4 接口契约真 enforce 全 partial / vacuum / 0 verify, sprint period sustained sustained sustained 沉淀 sustained vs 真生产 enforce 候选 audit gap

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-185** | **P2** | sprint period CLAUDE.md "12 Framework" 数字漂移 +1, 真 13 framework subdirs (含 risk subdir) |
| F-D78-186 | P2 | 4 接口契约 (DataPipeline/SignalComposer/RiskEngine/BacktestEngine) 真 enforce 全 partial/vacuum/0 verify |

---

**文档结束**.
