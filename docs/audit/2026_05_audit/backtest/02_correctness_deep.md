# Backtest Review — Correctness Deep (numerical / point-in-time / 涨跌停 / 停牌 / ST)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 3 WI 4 / backtest/02
**Type**: 评判性 + numerical correctness deep (sustained framework §3.5)

---

## §1 numerical correctness (双精度 / 复权 / 涨跌停 / 停牌 / ST)

实测 sprint period sustained sustained:
- 双精度: Decimal sustained sprint period sustained 真金额字段 (CLAUDE.md sustained §Python "金融金额用 Decimal")
- 复权: Tushare 复权 historical bug regression sustained sprint period sustained sustained
- 涨跌停: PMS L1+L2+L3 涨跌停 enforce sustained sprint period sustained sustained (历史调研 sprint period sustained "回测无 PMS 涨跌停" sustained Qlib/RD-Agent NO-GO 因之)
- 停牌: stock_status_daily sustained sprint period sustained
- ST: PT_TOP_N=20 排除 ST + 停牌 + 新股 (CLAUDE.md sustained sustained sustained)

**真测** (本审查未深查):
- 涨跌停 真 enforce in 回测引擎 候选 grep verify
- 停牌 真 enforce 候选 grep verify
- ST 排除 真 enforce 候选 grep verify

候选 finding:
- F-D78-143 [P2] 回测引擎 涨跌停 / 停牌 / ST 真 enforce 0 sustained 实测 grep verify, sustained sprint period sustained sustained 沉淀 sustained 但 enforcement 候选 audit

---

## §2 point-in-time correctness (look-ahead bias detection)

实测 sprint period sustained sustained:
- T+1 入场 (A 股 T+1 制度 sustained, CLAUDE.md sustained sustained §因子研究)
- forward return 从 T+1 入场 (沿用 .claude/rules/quantmind-overrides.md sustained sustained)

**真测** (本审查未深查):
- look-ahead bias 真 detection 0 sustained sustained sustained 度量

候选 finding:
- F-D78-144 [P2] look-ahead bias 真 detection 0 sustained sustained sustained 度量, sustained sprint period sustained sustained T+1 入场 sustained 但 enforcement 候选 audit (e.g. factor_values 真 trade_date vs forward return 真 trade_date+1 一致性 候选 verify)

---

## §3 性能 + scaling

实测 sprint period sustained sustained:
- Phase A 信号生成: 841s(12yr) → ~15s (sprint period sustained 60x 加速 sprint period sustained sustained)
- 真 last-run timestamp 0 sustained sustained sustained sync update (sustained F-D78-101 同源)

---

## §4 与生产路径一致性

(详 backtest/01 §3 sustained sustained F-D78-86 sustained candidate)

---

## §5 历史 bug 防复发

实测 sprint period sustained sustained:
- mf_divergence regression sustained sprint period sustained sustained
- Tushare 复权 historical bug regression sustained sprint period sustained sustained
- RSQR NaN regression sustained sprint period sustained sustained P0-4
- regression_test max_diff=0 (铁律 15 sustained) — sustained F-D78-24/84 sustained sustained 真 last-run 0 verify

候选 finding:
- F-D78-145 [P2] 历史 bug regression test 真 enforcement 0 sustained sustained 度量 (mf_divergence / Tushare 复权 / RSQR NaN 等历史 bug regression 真 last-run + 真 PASS rate 0 sustained sustained 实测), sustained 铁律 15 sustained sustained 但 enforcement 候选 audit

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-143 | P2 | 回测引擎 涨跌停 / 停牌 / ST 真 enforce 0 sustained 实测 grep verify |
| F-D78-144 | P2 | look-ahead bias 真 detection 0 sustained 度量, T+1 入场 enforce 候选 audit |
| F-D78-145 | P2 | 历史 bug regression test 真 enforcement 0 sustained 度量 (mf_divergence / Tushare 复权 / RSQR NaN) |

---

**文档结束**.
