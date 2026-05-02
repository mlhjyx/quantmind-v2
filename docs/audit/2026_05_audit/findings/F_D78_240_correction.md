# F-D78-240 真值订正 — emergency_close + GUI sell 真笔数 (5-02 sprint)

> **订正日期**: 2026-05-02
> **订正主体**: F-D78-240 (P0 治理) — trade_log 真 4-17 后 0 行 14 day, emergency_close + user GUI sell 真笔数
> **订正类型**: cite 真值订正 (35 → 18, 漂移 48.6% (= (35-18)/35))
> **订正源**: 5-02 sprint 双合并调查 (SQL 真测 + log 真读 + PR cross-cite)
> **关联铁律**: 25 (改什么读什么) / 26 (验证不可跳过) / 27 (不 fabricate) / 36 (precondition)
> **触发 LL**: LL-101 候选 ("audit cite 数字必 SQL/git/log 真测 verify before 复用")
> **0 prod 代码改 / 0 SQL 写 / 0 schtask / 0 hook bypass**

---

## §1 cite 漂移真值表 (5-02 真测)

| 来源 | cite 值 | 真值 | 漂移 |
|---|---|---|---|
| [F-D78-240 audit (5-01)](../operations/09_emergency_close_real.md#L102) "17 trades + GUI 18 trades 0 入库" | **35 (17+18)** | **18 (17+1)** | **-48.6%** |
| [EXECUTIVE_SUMMARY_FINAL_v2.md:64](../EXECUTIVE_SUMMARY_FINAL_v2.md#L64) "emergency_close 17 trades + GUI 18 trades 0 入库" | 35 | 18 | -48.6% |
| [STATUS_REPORT_2026_05_01_week1.md:206](../STATUS_REPORT_2026_05_01_week1.md#L206) "emergency_close 17 trades + GUI 18 trades audit reconstruction" | 35 | 18 | -48.6% |
| [risk/08_risk_event_log_real_2_entries.md:40,82](../risk/08_risk_event_log_real_2_entries.md#L40) "user 4-30 GUI 手工 sell **18 股**" | 18 (歧义) | 1 笔 (清 18 持仓中的 1 只) | 歧义 source |
| [PR #169 narrative v4](https://github.com/mlhjyx/quantmind-v2/pull/169) "17 CC + 1 user GUI" | **18 (17+1)** ✅ | 18 ✅ | **0 ✅ 真值 source** |
| [PROJECT_TRUE_STATE_SNAPSHOT_2026_04_30.md:11](../../PROJECT_TRUE_STATE_SNAPSHOT_2026_04_30.md#L11) "PR #169 v4 hybrid (17 CC + 1 user GUI)" | 18 | 18 | 0 ✅ |
| 5-02 双合并调查上轮 CC §1.3 推断 | "+35" | 18 | -48.6% (CC 推断未 SQL verify) |
| 5-02 [Claude.ai](http://Claude.ai) chat cite 沿用 | "35" | 18 | -48.6% (沿用错值) |

→ **真值订正**: F-D78-240 cite 真笔数 = **18 (17 emergency_close fills + 1 GUI sell)**, NOT 35.

---

## §2 真值订正 (CC 5-02 真测 verify)

### 2.1 4-29 emergency_close 真发笔数

**真测 source 1** ([emergency_close_20260429_104354.log](../../../../logs/emergency_close_20260429_104354.log) 真读 13992 bytes):

| 项 | 真值 |
|---|---|
| 18 orders placed | 真 (sequential) |
| 17 fills (status=56) | 真 (16 SH + 全部 SZ + 1 京沪退出) |
| 1 FAILED (status=57) | **688121.SH 卓然新能 4500 股, error_id=-61, error_msg "证券可用数量不足"** (4-29 跌停无成交) |

**真测 source 2** ([PR #168 body](https://github.com/mlhjyx/quantmind-v2/pull/168) cite):
- title: "feat(t0-19): phase 2 — 4 项修法落地 + 21 tests + **1 实测发现 (17 fills NOT 18)**"
- body: "18 orders placed, 17 fills (status=56), 1 FAILED"

**真测 source 3** ([09_emergency_close_real.md:87](../operations/09_emergency_close_real.md#L87) 真自身):
- "**18 持仓 emergency_close**: ✅ 18 query + **17 filled + 1 cancel**" — line 87 真值 17 fills, **与 line 102 cite "GUI 18 trades" 自相矛盾** (真新发现).

→ 真**emergency_close fills = 17 笔** (688121 跌停 1 fail 不算 fill).

### 2.2 4-29 4 个 abort log 真因 (5-02 双合并调查上轮 CC §1.3 真值)

| log file | 真值 (head 真读) |
|---|---|
| [emergency_close_20260429_103825.log](../../../../logs/emergency_close_20260429_103825.log) (669 B) | **ImportError**: `cannot import name 'QMTBroker' from 'engines.broker_qmt'` (PR #168 后已修) |
| [emergency_close_20260429_103936.log](../../../../logs/emergency_close_20260429_103936.log) (644 B) | **ImportError**: `No module named 'xtquant'` (xtquant_path 未 ensure) |
| [emergency_close_20260429_104022.log](../../../../logs/emergency_close_20260429_104022.log) (317 B) | 仅 query 18 持仓, **未下任何 order** (script abort) |
| [emergency_close_20260429_104114.log](../../../../logs/emergency_close_20260429_104114.log) (317 B) | 同上, 仅 query 18 持仓, **未下 order** |
| [emergency_close_20260429_104354.log](../../../../logs/emergency_close_20260429_104354.log) (13992 B) | ✅ **真 success run** (18 orders / 17 fills / 1 failed) |

→ 真**仅 104354.log 是 success run, 其他 4 abort log 真 0 fill**. trade_log backfill 时必只解析 104354.log.

### 2.3 4-30 GUI sell 真发笔数 — 反 prompt cite "18"

**真测 source** (3 audit md cross-verify):

| source | cite 真解读 |
|---|---|
| [risk/08:40,82](../risk/08_risk_event_log_real_2_entries.md#L40) "user 4-30 GUI 手工 sell **18 股**" | "18 股"在中文歧义 = **18 个持仓** vs **18 股票笔数**. 真值: 18 持仓中**清最后 1 只** (688121 4-29 跌停 cancel → 4-30 GUI sell). |
| [business/02_decision_authority.md:47](../business/02_decision_authority.md#L47) "4-30 user GUI sell 卓然新能 **4500 股清**" | **真 1 笔 trade** ✅ (清 1 stock 4500 股) |
| [PROJECT_TRUE_STATE_SNAPSHOT_2026_04_30.md:11](../../PROJECT_TRUE_STATE_SNAPSHOT_2026_04_30.md#L11) "PR #169 v4 hybrid (17 CC + **1 user GUI**)" | **真 1 笔** ✅ |
| [SHUTDOWN_NOTICE_2026_04_30.md:4](../../SHUTDOWN_NOTICE_2026_04_30.md#L4) narrative v3 | "实测推翻 v1+v2 narrative, 真因 4-29 上午 emergency_close 已 18 股清仓, **不是 4-30 GUI sell**" — 真"4-30 GUI sell"仅清 4-29 cancel 漏的 1 只 |

→ 真**4-30 GUI sell = 1 笔** (688121.SH 卓然新能 4500 股, 跌停 cancel 隔夜后 4-30 GUI 手工 sell).

### 2.4 真合计 backfill scope (订正后)

| 真 trade | 笔数 | source |
|---|---|---|
| 4-29 emergency_close fills | 17 | log 104354.log + PR #168 + 09_emergency_close_real.md:87 自身 cite |
| 4-30 GUI sell | 1 | business/02 + PR #169 v4 + PROJECT_TRUE_STATE_SNAPSHOT |
| **真总数** | **18** | 真 SQL/log/PR 三源 cross-verify ✅ |

订正前 cite "35" → 真值 **18**. 漂移 -48.6%.

---

## §3 真根因 — N×N 同步漂移 textbook 案例

### 3.1 cite 漂移 chain

```
risk/08:40,82 cite "user 4-30 GUI 手工 sell 18 股"
   (歧义 "18 股": 持仓数 vs trade 笔数, 真值 = 18 持仓中清 1 只)
        ↓
F-D78-240 finding (09_emergency_close_real.md:102)
   推断 "GUI 18 trades" (将"18 股"误读为"18 笔 trade")
        ↓
EXECUTIVE_SUMMARY_FINAL_v2.md:64 + STATUS_REPORT_2026_05_01_week1.md:206
   沿用错值 cite "GUI 18 trades 0 入库"
        ↓
5-02 [Claude.ai](http://Claude.ai) chat session cite "35 trades" (= 17+18)
   沿用 EXECUTIVE_SUMMARY 错值
        ↓
5-02 上轮 CC §1.3 推断 "+35"
   沿用 chat cite, 未 SQL/log verify
        ↓
5-02 user prompt 沿用 "35" (本订正 trigger 反向探测)
```

### 3.2 真根因 (3 层)

1. **歧义 source** (risk/08:40,82): 中文 "18 股" 歧义 (持仓数 vs trade 笔数), audit Phase 1 写 sub-md 时**未明确单位**.
2. **下游沿用未 verify** (F-D78-240 → EXECUTIVE_SUMMARY → STATUS_REPORT_week1 → chat → CC): 沿用错值 cite, 真 SQL/log 0 verify before 复用.
3. **N×N 同步漂移** (5-01 user 修正命题真证据加深): 多文档同 cite 错值 sustain, 1 错传 N. Sprint 4-26 4-29 5-01 5-02 真**无独立 SQL/log 反向 verify** until 本订正.

### 3.3 真证据加深 (5-01 user 修正命题)

5-01 sprint 末 user 提出 "audit cite 数字必交叉 verify" 命题, 5-02 双合并调查 SQL 真测**真证据加深** — F-D78-240 cite "35" 真值 18 = 真**N×N 同步漂移 textbook 案例**.

---

## §4 真 sub-task 2.1.1 backfill scope (订正后)

### 4.1 真 backfill 笔数

```
真 sub-task 2.1.1 trade_log backfill scope:
  - 17 笔 (4-29 emergency_close fills) ← log 104354.log
  - 1 笔 (4-30 GUI sell, 688121 4500 股) ← xtquant query_history_trades 真值 input
  ─────────────────────
  真总数 = 18 笔 (NOT 35)
```

### 4.2 真 path 决议 (混合)

| 真 trade | _backfill_trade_log hook 适用? | path |
|---|---|---|
| 17 笔 (4-29 emergency_close fills) | ✅ **直接复用** | [t0_19_audit.py:178](../../../../backend/app/services/t0_19_audit.py#L178) `_backfill_trade_log` (FILL_EVENT_REGEX L53-60 真匹配 104354.log) |
| 1 笔 (4-30 GUI sell) | ❌ **不可复用** | GUI sell 不走 emergency_close_all_positions.py, **0 emergency_close log file 4-30** (logs/ ls 真 verify), `FILL_EVENT_REGEX` 真无 source 解析. 需 (a) xtquant query_history_trades 真值 input + 手工 SQL INSERT, 或 (b) 新写 hook 接 xtquant 历史成交 query. |

→ **真 path 决议**: sub-task 2.1.1 实施时**真混合 path**, 17 fills 走 hook + 1 GUI sell 走手工/新 path. **NOT 单一 hook 复用**.

---

## §5 关联文档真 cite (CC 5-02 verify file:line)

| 文件 | 真 cite |
|---|---|
| [PR #168](https://github.com/mlhjyx/quantmind-v2/pull/168) | _backfill_trade_log hook 真接口 source (MERGED 2026-04-30T10:31:50Z) |
| [PR #169](https://github.com/mlhjyx/quantmind-v2/pull/169) | narrative v4 "17 CC + 1 user GUI" 真值 source |
| [backend/app/services/t0_19_audit.py:178](../../../../backend/app/services/t0_19_audit.py#L178) | `_backfill_trade_log` 真签名 + 真接口 |
| [logs/emergency_close_20260429_104354.log](../../../../logs/emergency_close_20260429_104354.log) | 4-29 success run 真 13992 bytes (17 fills + 1 failed) |
| [docs/audit/2026_05_audit/operations/09_emergency_close_real.md](../operations/09_emergency_close_real.md) | F-D78-240 主定义 (本订正主对象) |
| [docs/audit/2026_05_audit/EXECUTIVE_SUMMARY_FINAL_v2.md:64](../EXECUTIVE_SUMMARY_FINAL_v2.md) | F-D78-240 简表 cite (本订正次对象) |
| [docs/audit/2026_05_audit/risk/08_risk_event_log_real_2_entries.md](../risk/08_risk_event_log_real_2_entries.md) | "18 股" 歧义 source (本订正副对象) |
| [docs/audit/SHUTDOWN_NOTICE_2026_04_30.md](../../SHUTDOWN_NOTICE_2026_04_30.md) | narrative v3 真值 source (反 v1+v2) |
| [docs/audit/PROJECT_TRUE_STATE_SNAPSHOT_2026_04_30.md:11](../../PROJECT_TRUE_STATE_SNAPSHOT_2026_04_30.md) | "17 CC + 1 user GUI" 简明 cite |
| [LESSONS_LEARNED.md LL-101](../../../../LESSONS_LEARNED.md) | 本 finding 触发 LL sediment ("audit cite 数字必 SQL/git/log 真测 verify") |

---

## §6 SQL 真测 verify (5-02 spot-check + 全测)

### 6.1 5-02 全测 (双合并调查上轮 CC)

| Query | 真值 | source |
|---|---|---|
| `SELECT COUNT(*), MAX(trade_date), MIN(trade_date) FROM trade_log` | 88 / 2026-04-17 / 2026-04-14 | SQL Q1 |
| `SELECT trade_date, execution_mode, COUNT(*) FROM trade_log WHERE trade_date >= '2026-04-15' GROUP BY ...` | 4-15 live=8 / 4-16 paper=20 / 4-17 live=24 / 后续全 0 | SQL Q2 |
| `... WHERE trade_date IN ('2026-04-29', '2026-04-30')` | **0 行 (各)** | SQL Q3 |
| `SELECT trade_date, execution_mode, COUNT(*) FROM position_snapshot WHERE trade_date >= '2026-04-25' GROUP BY ...` | 4-27 live=19 / 4-28~5-02 全 0 (silent drift) | SQL Q4 |
| `SELECT triggered_at::date, execution_mode, severity, COUNT(*) FROM risk_event_log WHERE triggered_at::date >= '2026-04-25' GROUP BY ...` | 4-29 live p0=1 / 4-30 live info=1 | SQL Q5 |

### 6.2 5-02 spot-check (本订正前)

| Query | 真值 | sustained? |
|---|---|---|
| `SELECT MAX(trade_date) AS max_date, COUNT(*) AS total FROM trade_log` | 2026-04-17 / 88 | ✅ sustained (上轮 SQL Q1 一致) |

---

## §7 真新 finding 候选

### F-D78-291 [P3 治理] — 09_emergency_close_real.md 自相矛盾

**触发**: line 87 cite "17 filled + 1 cancel" vs line 102 cite "GUI 18 trades" — 同文件**真自相矛盾**.

**真根因**: 同 §3 真根因 chain — line 102 沿用 risk/08:40 "18 股" 歧义 cite, line 87 真值 17 fills 直接 log verify. 同 sub-md 内部真 0 cross-check.

**修法**: line 102 + line 111 in-place edit (本订正不改, 加 reference; future PR 决议 in-place 修).

### LL-101 候选 ("audit cite 数字必 SQL/git/log 真测 verify before 复用")

详 [LESSONS_LEARNED.md LL-101](../../../../LESSONS_LEARNED.md). 沿用 LL-100 邻位.

---

## §8 验收 checklist

- [x] §1 cite 漂移真值表 (8 source, cross-verify)
- [x] §2 真值订正 (4-29 fills / 4 abort log / 4-30 GUI / 真合计)
- [x] §3 真根因 (歧义 source / 下游沿用 / N×N 漂移 chain 真 trace)
- [x] §4 真 sub-task 2.1.1 backfill scope (订正后, 混合 path)
- [x] §5 关联文档真 cite (CC verify file:line, 10 source)
- [x] §6 SQL 真测 verify (上轮全测 + 本订正 spot-check)
- [x] §7 真新 finding 候选 (F-D78-291 + LL-101)
- [x] **0 prod 改 / 0 SQL 写 / 0 schtask / 0 .env 改 / 0 hook bypass** sustained ✅

---

**文档结束**.
