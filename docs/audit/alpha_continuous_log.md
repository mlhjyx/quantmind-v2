# Alpha Continuous Verify Log

**Document ID**: alpha_continuous_log
**Status**: Phase 4.2 sustained CC implementation skeleton, Week 2 起手 first weekly entry sustained Monday cadence
**Source**: protocol_v1.md §2 Topic 4 E + Topic 4 D (quantitative threshold)
**Created**: 2026-05-01

---

## §1 真核哲学 sustained

**Alpha continuous verify 真目的**: weekly cadence sustained alpha continuous verify 真核 sustained — 真**真生产 alpha 真退化 detect** sustained, 真**0 silent decay** sustained sprint period sustained.

**真核守门 sustained**: 任**1 threshold violate** → STOP + 真根因诊断 + reverse anti-pattern.

---

## §2 SOP weekly cadence (sustained protocol_v1.md §3 Monday 09:30-10:00)

### 2.1 Monday 09:30-10:00 — CC weekly verify

CC 真核走 sustained:

**Step A — regression_test 12yr** (sustained Topic 4 A):
- CC 跑 `python scripts/run_backtest.py --config configs/backtest_12yr.yaml --regression`
- 真**max_diff = 0** sustained (sustained 铁律 15 硬门)
- 真**Sharpe 真值 verify vs baseline** (sustained 12yr Sharpe=0.5309 sustained sprint period sustained 真核 baseline)
- drift > 10% Sharpe → STOP + 真根因

**Step B — factor_ic verify** (sustained Topic 4 B):
- CC 跑 SQL query factor_ic_history MAX trade_date + IC trend (CORE3+dv_ttm 4 因子)
- 真**IC drift > 20% vs sprint period rolling avg** → STOP + 真根因

**Step C — sediment weekly entry** (sustained Topic 4 E):
- CC 真核 sediment 1 entry §3 历史 log section sustained
- 真**真值 cite source + timestamp** sustained per handoff_template.md §3

### 2.2 Monthly walk-forward OOS rolling (sustained Topic 4 C)

**真核 cadence**: monthly first Monday sustained (sustained Week 4+ Layer 2 sprint candidate)

CC 真核走:
- 跑 walk-forward OOS rolling sustained 沿用 sprint state cite "WF OOS Sharpe=0.8659" 真核 baseline
- 真**WF OOS Sharpe drift > 10%** → STOP + 真根因
- sediment monthly entry §4 historical log section

---

## §3 历史 weekly log (cumulative weekly entries)

### Week 1 baseline (sustained 5-01 Phase 4.2 sediment, sustained CC 实测 verify):

| date | regression max_diff | regression Sharpe | factor_ic MAX | factor_ic IC trend | verdict |
|---|---|---|---|---|---|
| 2026-05-01 | TODO (Week 2 first run) | TODO | 2026-04-28 (CC 实测 5-01 SQL verify ✅, sustained PR #192 WI 4) | TODO (Week 2 first IC trend baseline) | sustained (skeleton sediment) |

(Week 2+ weekly entries 真**待 user 显式触发 Monday 09:30 cadence** sustained per protocol_v1.md §3, CC 0 自动 schedule.)

---

## §4 历史 monthly log (cumulative monthly walk-forward entries)

(Monthly entries 真**待 user 显式触发 Week 4+ Layer 2 sprint candidate** sustained per protocol_v1.md §3, CC 0 自动 schedule.)

---

## §5 STOP triggers (sustained protocol_v1.md §4)

任**1 trigger** → STOP + 真根因诊断 + 反问 user:

1. **regression max_diff > 0** → 真核**真根因深查** (sustained 铁律 15 硬门)
2. **regression Sharpe drift > 10%** vs 12yr baseline (Sharpe=0.5309 sustained) → 真根因
3. **factor_ic IC drift > 20%** vs sprint period rolling avg → 真根因
4. **WF OOS Sharpe drift > 10%** vs sprint period baseline (Sharpe=0.8659 sustained) → 真根因 (monthly only)

---

## §6 Anti-pattern 守门 sustained verify

✅ memory #19 凭空数字: 真值 cite source + timestamp sustained per §2 + §3 + handoff_template.md §3
✅ memory #22 静态分析 = 真测: 真**真 run regression_test + factor_ic SQL** sustained, 真**0 grep/log 推断** sustained

---

## §7 关联 ADR + LL sustained

- ADR-021 (IRONLAWS v3) sustained
- ADR-022 (sprint period treadmill 反 anti-pattern) sustained
- 待写 ADR-030 candidate (Layer 4 SOP 沉淀, sustained user (a-iii) # 下移决议体例. ADR-027 真 file = L4 STAGED 5-02 sprint 真已 commit, 沿用 PR #216. 详 [docs/adr/REGISTRY.md](../adr/REGISTRY.md) 案例 2)
- 铁律 15 (回测可复现, max_diff=0 硬门) sustained
- 铁律 11 (IC 唯一入库 factor_ic_history) sustained

---

**Document end**.
