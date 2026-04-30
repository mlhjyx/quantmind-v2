# Data Review — 6 维度 数据质量

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / data/01
**Type**: 评判性 + 数据质量 6 维度 (Accuracy / Completeness / Consistency / Timeliness / Uniqueness / Validity)

---

## §1 6 维度真测 (CC 5-01 实测)

### 1.1 Accuracy (准确性)

(本审查未深查 单表数据准确性 vs source. 候选 finding):
- F-D78-93 [P2] 数据 Accuracy 真测 0 sustained (Tushare / Baostock / QMT 真 vs DB 真 抽样 verify 候选)

### 1.2 Completeness (完整性)

实测真值:
- factor_values 276 distinct factor_name vs factor_ic_history 113 (factors/01 §1.1) — 163 因子 raw 但 0 IC = 不完整 (F-D78-58)
- position_snapshot live max trade_date=4-27 vs 真账户 0 持仓 (snapshot/07 §3) = 不完整 (F-D78-4)
- DB 4-day stale (T0-19 sustained)

### 1.3 Consistency (一致性)

实测真值:
- xtquant ↔ cb_state nav 差 ¥0.50 ✅ 微小 (F-D78-12)
- xtquant ↔ position_snapshot drift 4 days + 19 vs 0 持仓 🔴 (F-D78-4)
- cross_validation/01 §1.1-1.6 跨文档 fact 漂移 broader 70+ (F-D78-46)

### 1.4 Timeliness (及时性)

实测真值:
- DataPipeline 入库 schtask 17:30 daily (DailyMoneyflow / FactorHealthDaily) sustained ✅
- factor_ic_history MAX(trade_date)=4-28 vs 5-01 实测时间 (3 trade days lag) ⚠️
- position_snapshot MAX(trade_date)=4-27 (4 days stale) 🔴

### 1.5 Uniqueness (唯一性)

(本审查未深查 重复行 detection. 候选 finding):
- F-D78-94 [P2] 数据 Uniqueness 真测 0 sustained (重复行 / unique constraint enforce 度 抽样 verify 候选)

### 1.6 Validity (有效性)

(本审查未深查 column constraint 真 enforce 度. 候选 finding):
- F-D78-95 [P2] 数据 Validity 真测 0 sustained (NOT NULL / range / domain 约束真 enforce 度 抽样 verify 候选)
- 沿用 sprint period sustained F22 DataPipeline NULL ratio guard (PR #36 sustained sustained)

---

## §2 跨表 join 一致性

(本审查未深查 跨表 FK + JOIN 一致性 实测. 候选 finding):
- F-D78-96 [P2] 跨表 FK + JOIN 一致性 0 sustained sustained 度量

---

## §3 第三方源 (Tushare 复权 / QMT / Baostock) 真值 verify

(本审查未深查. sprint period sustained sustained:)
- Tushare 复权 historical bug regression sustained
- Baostock 5min K 线 5 年 / 2537 只股票 sustained
- QMT (xtquant) sustained sustained

候选 finding:
- F-D78-97 [P2] 第三方源真值 vs DB 真值 reconciliation 0 sustained (沿用 operations/01 §2 cross-source verify SOP F-D78-50 同源 anti-pattern)

---

## §4 DataContract vs 实测 schema drift

实测 sprint period sustained sustained DataContract sustained 沉淀, 但本审查实测 schema vs sprint state handoff drift 多源:
- F-D78-2 cb_state alias drift (真 circuit_breaker_state)
- F-D78-57 factor_id 字段名 drift (真 factor_name)
- (sustained snapshot/02 §1.5 sustained sustained)

**finding**:
- F-D78-98 [P2] DataContract vs 真 schema vs sprint state handoff 3 维 drift 高发 (F-D78-2/57/9 sustained), DataContract enforce 真 audit 候选

---

## §5 Parquet cache 失效策略

(本审查未深查 Parquet cache 真 staleness + invalidation enforce. sprint period sustained sustained sustained "下一交易日内生效" 铁律 30 sustained sustained.)

候选 finding:
- F-D78-99 [P3] Parquet cache invalidation 真 enforce 度 audit 候选 (sustained 铁律 30 sustained 但本审查未深查)

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-93 | P2 | 数据 Accuracy 真测 0 sustained (Tushare/Baostock/QMT 真值 vs DB 真值 抽样 verify 候选) |
| F-D78-94 | P2 | 数据 Uniqueness 真测 0 sustained (重复行 / unique constraint 抽样 verify 候选) |
| F-D78-95 | P2 | 数据 Validity 真测 0 sustained (NOT NULL / range / domain 约束 抽样 verify 候选) |
| F-D78-96 | P2 | 跨表 FK + JOIN 一致性 0 sustained sustained 度量 |
| F-D78-97 | P2 | 第三方源真值 vs DB 真值 reconciliation 0 sustained (沿用 operations/01 §2 同源) |
| F-D78-98 | P2 | DataContract vs 真 schema vs sprint state handoff 3 维 drift 高发 (F-D78-2/57/9 sustained) |
| F-D78-99 | P3 | Parquet cache invalidation 真 enforce 度 audit 候选 |

---

**文档结束**.
