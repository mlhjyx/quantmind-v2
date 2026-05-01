# Layer 2.1.7 follow-up A1 — klines/daily_basic 4-29/4-30 backfill 真测真值

**日期**: 2026-05-02
**Scope**: A1 短期 backfill (per Layer 2.1.7 audit §D 候选 A1, `02f916f` sustained)
**触发**: user 授权 A1, anti-pattern v5.2 sustained — cite 是线索, 真值需当下 verify
**main HEAD**: `02f916f` (Layer 2.1.7 RC4 audit 已 merged)

---

## §A `fetch_daily_data` 真签名 + 真调用方式

### A.1 真签名 (实测 `backend/app/services/pt_data_service.py:25`)

```python
def fetch_daily_data(trade_date: date, conn=None, skip_fetch: bool = False) -> dict:
    """并行拉取当日klines+basic+index数据并入库。

    Returns: {"klines_rows": int, "basic_rows": int, "index_rows": int, "elapsed": float}
    """
```

→ 真签名: `(trade_date: date, conn=None, skip_fetch: bool = False) -> dict`. 调用方式: 单 date 单调用, 内部 ThreadPoolExecutor max_workers=3 并行 (klines/basic/index).

> **注 (reviewer MEDIUM 采纳)**: 源码 docstring (line 34) 仅列 4 keys, 但真实 returns 还含 `status_rows` (2026-04-14 新增 stock_status incremental update, line 106 添加, docstring 未同步). §C.1 真输出 5 keys 是真值, §A.1 docstring 引用是源码原文 (stale). 候选: 起 sub-task 修源码 docstring (Layer 2.3+ cleanup, 不紧急).

### A.2 调用环境

```bash
.venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'backend')
from datetime import date
from app.services.pt_data_service import fetch_daily_data
fetch_daily_data(date(2026,4,29))
fetch_daily_data(date(2026,4,30))
"
```

→ 真生产 venv Python, 直接 import + 调用. 0 dry-run mode (真签名 `skip_fetch=False` default 真拉真写). 0 代码改动.

---

## §B Tushare 4-29/4-30 历史 daily 真 available 真测

### B.1 probe 真测 (read-only, 不写 DB)

```python
api = TushareAPI()
df_klines = api.merge_daily_data('20260429')         # 5462 rows
df_basic = api.fetch_daily_basic_by_date('20260429') # 5462 rows
```

→ 4-29 真返回 5462 行 (vs moneyflow 同期 5144 行). Tushare 历史日期真可拉, 0 rate limit, 0 quota fail.

### B.2 预期行数 cross-check

注: 4-29/4-30 列格式 `raw / upserted (rejected)` — raw 是 Tushare 真返回行数, upserted 是 DataPipeline 真入库行数 (扣 reject), 详 §C.3.

| 数据源 | 4-27 | 4-28 | 4-29 (probe) raw / upserted | 4-30 (post-backfill) raw / upserted |
|---|---|---|---|---|
| klines_daily | 5481 | 5474 | 5462 / **5447** (15 rejected) | 5460 / **5444** (16 rejected) |
| daily_basic | 5481 | 5474 | 5462 / **5447** (15 rejected) | 5460 / **5444** (16 rejected) |
| moneyflow_daily | 5177 | 5170 | 5144 | 5142 |

→ klines/daily_basic 真值 ~5444-5447 行, vs moneyflow ~5144 行 (klines ~300 行 higher 是真值, 包含 ST/暂停股 moneyflow 不含). 与历史 pattern 吻合, 反 RC3 (Tushare 无数据) 完全排除.

---

## §C backfill 真跑

### C.1 命令 + 真结果 (实测 2026-05-02 04:06:25-29)

```
=== Backfill 2026-04-29 ===
2026-05-02 04:06:25 [info] Upserted 1 rows to index_daily x3 (000300/000905/000852)
2026-05-02 04:06:25 [info] Loaded 5821 valid codes from symbols
2026-05-02 04:06:25 [error] [pipeline] null_ratio_exceeded (F22 铁律33 fail-loud)
                            column=pe_ttm null_ratio=0.2723 severe (threshold=0.05)
2026-05-02 04:06:25 [error] [pipeline] null_ratio_exceeded (F22 铁律33 fail-loud)
                            column=dv_ttm null_ratio=0.3163 severe
2026-05-02 04:06:26 [info] Upserted 5447 rows to daily_basic
2026-05-02 04:06:26 [warning] daily_basic: 15/5462 rows rejected: {'fk_not_in_symbols': 15}
2026-05-02 04:06:26 [info] Upserted 5447 rows to klines_daily
2026-05-02 04:06:26 [warning] klines_daily: 15/5462 rows rejected:
                              {'pct_change_above_30': 1, 'fk_not_in_symbols': 14}
2026-05-02 04:06:27 [info] Upserted 5447 rows to stock_status_daily
4-29 result: {'klines_rows': 5447, 'basic_rows': 5447, 'index_rows': 3, 'status_rows': 5447, 'elapsed': 2.4}

=== Backfill 2026-04-30 ===
4-30 result: {'klines_rows': 5444, 'basic_rows': 5444, 'index_rows': 3, 'status_rows': 5444, 'elapsed': 1.7}
```

### C.2 真写入数据明细

| 表 | 4-29 写入 | 4-30 写入 | 历史一致性 |
|---|---|---|---|
| `klines_daily` | 5447 | 5444 | ✅ 与 4-27/4-28 (5481/5474) 同量级 |
| `daily_basic` | 5447 | 5444 | ✅ 同 klines |
| `index_daily` | 3 | 3 | ✅ 000300.SH / 000905.SH / 000852.SH |
| `stock_status_daily` | 5447 | 5444 | ✅ klines 后增量更新 (依赖 volume) |

### C.3 真 reject 行数 (DataPipeline 真拒)

| 表 | reject 行数 | 真因 |
|---|---|---|
| daily_basic 4-29 | 15 | fk_not_in_symbols=15 (newly listed, 未入 symbols 表) |
| klines_daily 4-29 | 15 | fk_not_in_symbols=14 + pct_change_above_30=1 (1 IPO 异常) |
| daily_basic 4-30 | 16 | fk_not_in_symbols=16 |
| klines_daily 4-30 | 16 | fk_not_in_symbols=15 + pct_change_above_30=1 |

→ reject 真值 0.27%-0.29%, 与历史 pattern 一致. 不是 backfill 真问题.

---

## §D post-backfill 真状态 verify

### D.1 DB MAX 真值

```
klines_daily:        MAX=2026-04-30, total=11,787,507 (was 11,776,616, +10,891 = 5447+5444)
daily_basic:         MAX=2026-04-30, total=11,692,690 (was 11,681,799, +10,891 = same)
stock_status_daily:  MAX=2026-04-30, total=12,069,611
index_daily:         MAX=2026-04-30, total=55,705
```

→ 4 真表 MAX 全 4-30 ✅. backfill 真完整.

### D.2 schtask 真状态 verify (实跑实测)

#### `health_check.py` (QM-HealthCheck 16:25 schtask 真触发的真脚本)

```
健康预检: 2026-05-02
  OK postgresql_ok: OK
  OK redis_ok: OK (内存3.5MB)
  OK data_fresh: 最新=2026-04-30, 上一交易日=2026-04-30
  OK stock_status_ok: date=2026-04-30, 5444行
  OK factor_nan_ok: date=2026-04-28, CORE4因子neutral_value正常(4因子)
  OK disk_ok: 665.1GB可用
  OK celery_ok: 1个worker在线
  OK config_drift_ok: 6 params aligned (.env/yaml/python)
✅ 全部通过
```

→ **health_check 全 PASS** ✅ (was FAIL data_fresh). schtask LastResult 下次 (5-02 16:25) 自动真生效, 期望 → 0.

⚠️ factor_nan_ok 真测 4-28 (not 4-30) — 因 factor_values 4-29/4-30 真未重算 (依赖 klines, 但 factor compute 是独立 schtask, 见 §E). 不阻塞 health_check.

#### `data_quality_check.py` (QuantMind_DataQualityCheck 18:30 schtask 真触发的真脚本)

```
WARNING 发现 1 项异常:
  - daily_basic.pe_ttm 2026-04-30 NULL比例=27.7% (1510/5444), 阈值5%
[DingTalk] sync发送成功: title='[P1] 数据质量告警 2026-04-30'
exit_code=1
```

→ **data_quality_check 仍 exit_code=1**, 但**真因转移**:
- 旧真因 (5-1 18:30): klines/daily_basic 4-28 stale 滞后 2 trading days (P0)
- 新真因 (5-2 04:07): pe_ttm null_ratio 27.7% > 阈值 5% (P1, 已降级)
- DingTalk push P1 (not P0) → severity 真降, suppress=30min

### D.3 真新 finding (本 backfill 顺手发现)

#### F-A1-1 ⚠️ 4-28 dv_ttm 100% NULL 历史异常

per-date null_ratio 真测:

| trade_date | total | pe_ttm null | pe % | dv_ttm null | dv % |
|---|---|---|---|---|---|
| 2026-04-27 | 5481 | 1460 | 26.64% | 1746 | 31.86% |
| **2026-04-28** | **5474** | 1474 | 26.93% | **5474** | **100.00%** ⚠️ |
| 2026-04-29 | 5447 | 1483 | 27.23% | 1723 | 31.63% |
| 2026-04-30 | 5444 | 1510 | 27.74% | 1723 | 31.65% |

→ **4-28 dv_ttm 全 NULL** (vs 邻近 4-27/4-29/4-30 都 ~31%). 真异常, 与本次 backfill **无关** (4-28 数据是预存在的, 不是本次写). 这是 Layer 2.1 reconnaissance §C 漏掉的真新 finding, 候选 sub-task: dv_ttm 4-28 真因诊断 (Tushare 真返回 NULL? upsert 真覆盖? F22 fail-loud 当时未阻塞?). PT 配置 CORE3+dv_ttm WF PASS 包含 dv_ttm, 4-28 全 NULL 影响 factor_values 计算.

#### F-A1-2 ⚠️ data_quality_check.py pe_ttm 阈值 5% 真过紧

历史 pattern: pe_ttm null_ratio 真值 ~26-27% (亏损股 PE 为负或 NULL 是 A 股正常现象). 阈值 5% 配置真过紧, 持续触发 P1 alert. 反 真问题 (pe_ttm 真有 NULL pattern, 阈值需 holiday-aware OR 调整到 ~30%+OR 排除 pe_ttm). 候选 sub-task: data_quality_check.py 阈值真校准.

→ 这两 finding 不在本 task scope, sediment 留 user 决议起 sub-task.

### D.4 真生产红线 sustained verify

| 红线 | 起末值 |
|---|---|
| `LIVE_TRADING_DISABLED` | true → true ✅ |
| `EXECUTION_MODE` | paper → paper ✅ |
| 真账户 (Redis) | cash=¥993,520.66 / 0 持仓 / 0 drift ✅ |
| schtask 真改动 | 0 (DailySignal/DailyExecute 仍 Disabled, 仅 backfill 数据) ✅ |
| .env / Servy / DB schema | 0 改动 ✅ |
| PT 触碰 | 0 ✅ |

---

## §E factor_values 下游影响 (transparency, 未真测)

backfill 仅写 klines_daily / daily_basic / stock_status_daily / index_daily 4 表. **factor_values 真**未重算** (本 task 不在 scope). factor_values 4-29/4-30 真值仍 0 行 (per Layer 2.1 reconnaissance §C.1 cite "factor_values MAX=4-28").

→ 真 factor backfill 走独立 sub-task (`scripts/fast_ic_recompute.py --start 2026-04-29 --end 2026-04-30 --core` 类似 Layer 1 Week 1 WI 4 pattern). 留 user 决议起手.

---

## §F transparency — 我没真测的

为反 anti-pattern v3.0 (cite 当真值), 列出本 audit **未真测**项目:

1. **factor_values 真重算**: 本 task 仅 backfill 4 张原始表, factor_values 4-29/4-30 仍 0 行. 真 factor pipeline 走独立 schtask (factor_health_daily / fast_ic_recompute) 后续触发或手工跑.
2. **stock_status_daily 增量真完整性**: 5447/5444 行 upsert OK, 但 ST/停牌/新股真状态 vs Tushare 真值未比对 (假设 upsert_klines_daily → stock_status incremental update 真正确, 沿用历史 pattern).
3. **F-A1-1 dv_ttm 4-28 100% NULL 真因**: 本 task 仅发现, 未深查 (Tushare 4-28 真返回 NULL? upsert 真覆盖? 历史 pull script 真 silent fail?). 留 sub-task.
4. **F-A1-2 pe_ttm 阈值 5% 真校准**: 本 task 仅发现 阈值过紧, 未真测调整后真生产影响. 留 sub-task.
5. **schtask LastResult 真生效时机**: QM-HealthCheck 真生效需 5-02 16:25 schtask 真触发后 LastResult 才更新到 0. 本 audit ~04:07 跑 health_check.py 是手工 verify, schtask 真生效是 16:25 (~12 小时后).
6. **A2 架构解耦 (klines/daily_basic 独立 schtask)**: 本 task 仍是 RC4 真因短期补救 (A1), A2 架构层修法 (Layer 2.3+) 仍待 user 决议.

---

## §G 验收 checklist

- [x] §A fetch_daily_data 真签名 + 调用方式 真测 ✅
- [x] §B Tushare 4-29/4-30 历史 probe (5462/5462 真返回, 0 rate limit) ✅
- [x] §C backfill 真跑 (4-29=5447 / 4-30=5444 真 upsert) ✅
- [x] §D post-backfill DB MAX=4-30 + health_check 全 PASS ✅
- [x] §D data_quality_check 真因转移 (klines stale → pe_ttm null_ratio) ✅
- [x] F-A1-1 dv_ttm 4-28 100% NULL 顺手发现 sediment ✅
- [x] F-A1-2 pe_ttm 阈值 5% 过紧 顺手发现 sediment ✅
- [x] §F transparency (6 未真测项) ✅
- [x] 0 修代码 / 0 改 schtask / 0 .env / 0 PT 触碰 / 0 hook bypass sustained ✅
- [x] 真生产红线起末值 sustained ✅

---

## §H 顶层结论

**Layer 2.1.7 follow-up A1 真闭环**:

1. **真因 RC4 短期解决**: klines/daily_basic 4-29 (5447) + 4-30 (5444) 真 backfill, MAX 真值 4-28 → 4-30, 与 moneyflow 同期 4-30 ground truth 对齐. 0 改代码, 0 改 schtask, 0 触碰 PT 链 (DailySignal/DailyExecute 仍 Disabled).

2. **schtask 真状态变化**:
   - QM-HealthCheck: FAIL data_fresh → ALL PASS (真因解决, 5-02 16:25 schtask 自动真生效, 期望 LastResult → 0)
   - QuantMind_DataQualityCheck: P0 (klines stale) → P1 (pe_ttm null_ratio 27.7% > 阈值 5%, 真因转移). 仍 exit_code=1 但 severity 真降, 真因 = 配置过紧 (历史 pe_ttm 26-27% 是 A 股正常)

3. **2 真新 finding** (Layer 2.1 reconnaissance 漏掉):
   - **F-A1-1**: 4-28 dv_ttm 100% NULL 历史异常 (邻近 ~31%), 影响 PT CORE3+dv_ttm 因子计算
   - **F-A1-2**: data_quality_check.py pe_ttm 阈值 5% 过紧 (历史真值 26-27% 是 A 股 NULL pattern)

4. **A2 架构解耦** (klines/daily_basic 独立 schtask) 仍待 Layer 2.3+ sub-task 起手. 本 A1 是 short-term fix, 不解决耦合 anti-pattern.

5. **factor_values 真未重算** — 4-29/4-30 仍 0 行. 真 factor backfill 独立 sub-task (沿用 fast_ic_recompute pattern).

**user 决议候选**:
- (a) 起 F-A1-1 dv_ttm 4-28 100% NULL 真因诊断 sub-task (Layer 2.1.7 follow-up B)
- (b) 起 F-A1-2 data_quality_check 阈值校准 sub-task (修代码, Layer 2.2)
- (c) 起 factor_values 4-29/4-30 真重算 sub-task (沿用 fast_ic_recompute --start 4-29 --end 4-30 --core)
- (d) 起 A2 架构解耦 (Layer 2.3+, 修代码 + 新独立 schtask)
- (e) 接受当前真状态 (4-30 数据真齐, schtask 大部分恢复绿, 留 PT 重启时 ETL coupling 自然解)
