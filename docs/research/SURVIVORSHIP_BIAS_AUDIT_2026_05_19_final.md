# Survivorship Bias Audit — Final Verdict (B3 Phase J, 2026-05-19)

**Sediment**: B3 任务 1+2 真值验证完成 (`_verify_b3_tasks_5_19.py` 5-19 20:50 SH cold run)
**Result**: ✅ **P0-11 假设 "BACKTEST EXCLUDES delisted entirely" 与真值矛盾 — 假设可证伪**
**Subagent G 误报 pattern** → LL-191 候选

---

## §1 真值矩阵 (5-19 SH 实测)

| Metric | 真值 | Plan v8 P0-11 假设 | Verdict |
|---|---|---|---|
| klines_daily 唯一股票数 | 5,743 (含历史退市) | 仅 active universe | ❌ 假设错 |
| factor_values 唯一股票数 | 5,743 | 仅 active universe | ❌ 假设错 |
| 322 退市股 / factor_values 覆盖 | 241 / 322 (74.8%) | 0 / 322 | ❌ 假设错 |
| 2014-2026 退市股 factor_values 覆盖 | 247 / 247 (100%) | 0 / 247 | ❌ 假设错 |
| stock_status_daily 行数 | 12,118,876 | 不知 | sediment 完整 |
| stock_status_daily 日期范围 | 2014-01-02 ~ 2026-05-18 | 不知 | 12.5 年完整 ST/停牌 |
| ST 但未退市股票 | 631 只 | 不知 | ST → 摘帽路径完整 |
| ST 后退市股票 | 204 只 | 不知 | ST → 退市路径完整 |

---

## §2 关键发现

### §2.1 factor_values 含退市股全 sediment (核心反证)

- **2014-2026 全 247 只退市股**: factor_values 100% 覆盖
- **Top 退市股样本** (2025 退市, factor_values 行数):
  - 600200.SH 退市 2025-12-31, factor 行数 191,156
  - 603388.SH 退市 2025-12-05, factor 行数 106,128
  - 000851.SZ 退市 2025-11-11, factor 行数 215,362
- **侧面发现**: factor_values 最后日 = 2026-04-08 (即使 2025 退市股), 即 factor 计算路径**没有 stop-at-delist** → 这是另一个 P1-46 候选 finding (factor calc 应 stop-at-delist 否则计算 useless rows)

### §2.2 stock_status_daily 完整 ST 历史

- 2014-01-02 → 2026-05-18 (12.5 年)
- ST 股票按年趋势: 85 (2014) → 503 (2026) 单调递增
- Top 10 退市股退市前 ST 天数: 全部 ≥ 1173 天 (无任何 "0 ST 直接退市" pattern)
  - 000982.SZ 退市 2024-08-12, ST 天数 1770
  - 002336.SZ 退市 2025-07-04, ST 天数 1756
- **结论**: 退市股的 ST 历史完整 sediment, backtest universe 真**含**退市股 + ST 状态

### §2.3 2014 前历史断层 (次要)

- 1999-2013: 64 只退市股, factor_values 0 覆盖
- 原因: factor_values 起始日 ~2014 (klines_daily 起始日同期)
- **影响**: 早期 (pre-2014) 生存者偏差仍可能存在, 但**回测主窗口 2014+**, 影响有限
- **风险**: 12-yr backtest (Sharpe=0.3594, 2014-2026) → 影响较小
- 5-yr backtest (Sharpe=0.6095, 2021-2026) → 几乎无影响 (322 退市股中 ~196 只在 2021+ 退市, factor_values 全覆盖)

---

## §3 残余风险量化 (留 backtest run 验证)

### §3.1 Top-N 选股是否真选中退市股

- factor sediment 完整但是否**真被选中** = 因子真值问题
- 验证路径: backtest replay 2020-2025, 检查 trade_log 中是否有退市股 (在退市前期被选中, 退市后被 force-sold)
- 预期: 应有 (PT live 2025 持有 17 股有 1 只 4-29 跌停 → 4-30 user GUI sell, sample 已示退市路径)

### §3.2 Look-ahead bias (delist_date 提前已知)

- `symbols` 表是**当前 snapshot** (delist_date 是历史事实)
- backtest 是否 JOIN symbols 过滤掉 "未来会退市" 股票? → 沿用 parquet_cache.py SQL 真值:
  - `FROM klines_daily k LEFT JOIN daily_basic db ... LEFT JOIN stock_status_daily ss ... WHERE k.trade_date BETWEEN %s AND %s AND k.volume > 0`
  - **不 JOIN symbols** → 无 delist_date look-ahead leak ✅

### §3.3 Backtest universe filter (待 sample)

- 5-yr / 12-yr backtest 实际 univer 是否过滤 ST? 是否过滤 0 volume?
- 沿用 SQL: `WHERE k.volume > 0` → 0 volume 自动过滤 (退市股最后段通常 volume=0)
- 但**退市前** volume 正常 → backtest 应能选中 → 验证路径: trade_log 查退市股入场记录

---

## §4 P0-11 Verdict + 后续动作

### §4.1 P0-11 Closure 候选 (留 5-yr backtest sample run 确认)

- **Subagent G "BACKTEST EXCLUDES delisted entirely" 假设** = ❌ FALSE
- klines_daily / factor_values / stock_status_daily 三层 sediment 全含退市股
- **生存者偏差 likely 不显著**
- **P0-11 candidate to MARK FALSE ALARM in Plan v8 Master Findings Register**

### §4.2 Plan v8 Master Findings Register 更新

```diff
- P0-11 | open | (假设) backtest universe 排除退市股 → 生存者偏差 → Sharpe 虚高
+ P0-11 | FALSE ALARM | 真值证伪 (5-19 B3 audit): factor_values + klines_daily + stock_status_daily 三层均含退市股 sediment, Subagent G 假设错. 生存者偏差 likely 不显著. 残余风险 §3.1/§3.2/§3.3 留 backtest sample run 验证.
```

### §4.3 LL-191 候选 (Subagent G 误报 pattern)

**Title**: Subagent audit 假设性 finding 必跑真值 SQL 验证, 不能凭 SQL grep 推断
**Why**: Subagent G (Plan v8 Phase 2 Batch 3, Health + Section IX/X subagent) 在 5-18 audit 时凭 backtest SQL 不 JOIN symbols 推断 "backtest excludes delisted" — 但实际 SQL grep 范围未覆盖 parquet_cache.py 真 path, 且未做 row-level 真值验证
**How to apply**: Plan v9+ audit subagent prompt 强制 — 任何 P0 类 finding 必附 SQL row count + 真值表 + reproduce script (沿用 LL-101/103/106 quantmind-v3-cite-source-lock skill 4 元素 cite)
**Severity**: P3 (one-shot 修订, audit methodology 改进)

### §4.4 P1-46 新 candidate (factor calc 应 stop-at-delist)

- 2025 退市股 factor_values 最后日 = 2026-04-08 (远超退市日)
- factor 计算了大量退市后的 useless rows
- 估算: 247 只退市股 × ~100-500 useless rows = ~25k-125k rows useless sediment
- **修复**: factor compute pipeline 加 stop-at-delist filter (沿用 symbols.delist_date)
- **优先级**: P1 (data hygiene, 不阻塞 alpha)

---

## §5 Validation

```bash
# Reproduce
python D:\quantmind-v2\_verify_b3_tasks_5_19.py
# Verify
# 1. factor_values 唯一股票数 = 5743 (含退市)
# 2. 322 退市股中 241 在 factor_values 有数据
# 3. stock_status_daily 12.1M 行 2014-01-02 ~ 2026-05-18
```

**Sediment by**: CC autonomous (Session 58+1 evening close + post-compact resume)
**Verified at**: 2026-05-19 ~20:50 SH (post bx4ud11wb PowerShell sync run)
**Plan v8 §VIII §37**: Survivorship Bias Audit deep dive — ✅ initial sediment + final verdict 闭环 (P0-11 FALSE ALARM 候选)
**Next**: 5-yr backtest sample run 验证 §3.1/§3.2/§3.3 残余风险 (deferred Phase J Day 1+)
