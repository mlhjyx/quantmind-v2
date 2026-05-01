# Risk Review — Position 命名空间漂移真测 deep (sustained F-D78-118)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 8 WI 4 / risk/06
**Date**: 2026-05-01
**Type**: 评判性 + position_snapshot 命名空间漂移真测加深 (sustained risk/03 F-D78-115/118)

---

## §1 真测 (CC 5-01 实测)

实测 SQL:
```sql
SELECT execution_mode, COUNT(*), MAX(trade_date)
FROM position_snapshot
GROUP BY execution_mode;
```

**真值**:

| execution_mode | COUNT | MAX(trade_date) |
|---|---|---|
| **live** | **276** | 2026-04-27 |
| **paper** | **0** | (none) |

**真值**: position_snapshot 真**仅含 'live' 数据 276 行, paper 真 0 行 sustained**

---

## §2 🔴 重大 finding — paper 命名空间完全空 (sustained F-D78-118 加深 verify)

**真根因 5 Why** (sustained risk/03):
1. intraday_risk_check 73 error/7d → trigger PAPER_STRATEGY_ID mode='paper' 查 position_snapshot
2. position_snapshot mode='paper' 真 0 行 sustained
3. **PositionSourceError raise sustained sustained**
4. silent failure cluster sustained (用户 0 通知 F-D78-119 sustained)

**真测验证**: ✅ paper mode 0 行真值 (本审查 5-01 实测)

**🔴 finding**:
- **F-D78-229 [P1]** position_snapshot 真测 per mode: **live=276 / paper=0** sustained, sustained F-D78-118 真根因加深 verify. 真生产 mode/strategy 命名空间漂移 sustained sustained: live 4-day stale (F-D78-4 sustained sustained) + paper 完全空 = 双 mode 全 silent failure cluster

---

## §3 sprint period sustained "EXECUTION_MODE=paper" .env vs 真生产 disconnect

实测真值:
- .env EXECUTION_MODE=paper sustained (E5 sustained sustained)
- intraday_risk_check trigger PAPER_STRATEGY_ID (sustained risk/03 §2.2)
- 但 position_snapshot 真**仅 live 276 行 + paper 0 行**

**真测**: EXECUTION_MODE=paper sustained sustained 但 position_snapshot 真**仅 live 模式**沉淀, paper mode 0 sustained sustained sustained — 真生产 sustained sustained sustained 0 enforce paper mode position 入库

**finding**:
- **F-D78-232 [P1]** EXECUTION_MODE=paper sustained .env vs position_snapshot 真**仅 live 276 行 + paper 0 行** = .env config vs 真生产 enforce disconnect, sustained F-D78-229 sustained 加深: 真生产**0 sustained paper 模式 position 真入库** (sustained sprint period sustained sustained "EXECUTION_MODE=paper" 沉淀 sustained sustained 但 真 paper mode position 0 实测)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-229** | **P1** | position_snapshot 真 live=276 + paper=0, 双 mode 全 silent failure cluster (live 4-day stale + paper 完全空) |
| **F-D78-232** | **P1** | EXECUTION_MODE=paper sustained .env vs position_snapshot 真仅 live 沉淀 = .env config vs 真生产 enforce disconnect |

---

**文档结束**.
