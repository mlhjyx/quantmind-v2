# Layer 2.1.7 reconnaissance — klines/daily_basic pull pipeline 4-29+4-30 silent stop 真因诊断

**日期**: 2026-05-02
**Scope**: read-only 真测真值 + 真因诊断 + 候选 action 推荐, 0 修代码 / 0 backfill / 0 改 schtask
**触发**: Layer 2.1 reconnaissance §I (cold-start prompt sediment), user 决议 Path B 后 2.1.7 起手
**main HEAD**: `c0dac99` (Layer 2.1 reconnaissance 已 merged 进 main)
**反 anti-pattern**: v5.2 sustained — cite 是线索, 实测才是真值, 不预设 framing

---

## §A klines/daily_basic pull schtask 真状态

### A.1 真测命令 (PowerShell `Get-ScheduledTask`)

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like '*QuantMind*' -or $_.TaskName -like '*QM-*' } |
  Select-Object TaskName, State, LastRunTime, LastTaskResult, NextRunTime
```

### A.2 真值 — 23 真 QuantMind/QM- schtasks (实测 2026-05-02 ~03:30, `Sqm-Tasks` Microsoft system task 排除)

**Ready (真活)** — 17 个:

| TaskName | LastRun | LastResult | NextRun | 备注 |
|---|---|---|---|---|
| `QM-DailyBackup` | 2026-05-02 02:00 | 3221225786 (`STATUS_CONTROL_C_EXIT`) | 2026-05-03 02:00 | 5-2 02:00 user pause 留下, 已知 |
| `QM-HealthCheck` | 2026-05-01 16:25 | **1** | 2026-05-02 16:25 | data_fresh fail (klines<4-30) |
| `QM-ICMonitor` | 2026-04-26 20:00 | 0 | 2026-05-03 20:00 | weekly Sunday |
| `QM-LogRotate` | 2026-05-01 06:00 | 0 | 2026-05-02 06:00 | daily |
| `QM-PTDailySummary` | 2026-05-01 17:35 | 0 | 2026-05-02 17:35 | daily |
| `QM-RollingWF` | 2026-05-02 02:00 | 0 | 2026-05-03 02:00 | daily |
| `QuantMind_DailyIC` | 2026-05-01 18:00 | 0 | 2026-05-04 18:00 | Mon-Fri (next=Mon, holiday skip) |
| **`QuantMind_DailyMoneyflow`** | **2026-05-01 17:30** | **0** | 2026-05-02 17:30 | **moneyflow daily 真活** ✅ |
| `QuantMind_DataQualityCheck` | 2026-05-01 18:30 | **1** | 2026-05-02 18:30 | klines/daily_basic 4-29/4-30 stale fail |
| `QuantMind_FactorHealthDaily` | 2026-05-01 17:30 | 0 | 2026-05-02 17:30 | daily |
| `QuantMind_IcRolling` | 2026-05-01 18:15 | 0 | 2026-05-04 18:15 | Mon-Fri |
| `QuantMind_MiniQMT_AutoStart` | 2026-04-29 14:07 | 0 | — | on-demand |
| `QuantMind_MVP31SunsetMonitor` | 2026-04-26 04:00 | 0 | 2026-05-03 04:00 | weekly |
| `QuantMind_PTAudit` | 2026-05-01 17:35 | 0 | 2026-05-02 17:35 | daily |
| `QuantMind_PT_Watchdog` | 2026-05-01 20:00 | **1** | 2026-05-02 20:00 | PT 0 持仓 expected normal |
| `QuantMind_RiskFrameworkHealth` | 2026-05-01 18:45 | 0 | 2026-05-04 18:45 | Mon-Fri |
| `QuantMind_ServicesHealthCheck` | 2026-05-02 03:15 | 0 | 2026-05-02 03:30 | every 15 min |

**Disabled (4-29 user 决议影响)** — 6 个:

| TaskName | LastRun | LastResult | 备注 |
|---|---|---|---|
| `QM-SmokeTest` | 2026-04-06 20:05 | 3221225786 | 旧, 不参与 PT 链 |
| `QuantMind_CancelStaleOrders` | 2026-04-02 09:05 | 0 | PT 链 (cancel orders) |
| `QuantMind_DailyExecute` | 2026-04-19 09:31 | 0 | **PT 链 (execute, run_paper_trading.py exec_phase)** |
| `QuantMind_DailyReconciliation` | 2026-04-28 15:40 | 0 | PT 链 (reconciliation) |
| **`QuantMind_DailySignal`** | **2026-04-28 16:30** | **0** | **PT 链 (signal generation, run_paper_trading.py signal_phase, 含 Step 1 ETL)** |
| `QuantMind_IntradayMonitor` | 2026-04-29 10:25 | 0 | PT 链 (intraday monitor) |

### A.3 关键 finding

- **0 schtask 真名匹配 `klines` / `daily_basic` / `pull_klines` / `update_klines_daily`**. klines/daily_basic 真**不是独立 schtask** (反 cite memory 候选 "QuantMind_DailyKlines" 不存在).
- moneyflow 是独立 schtask `QuantMind_DailyMoneyflow` 17:30, 真活 (LastResult=0 5-1 17:30, 与 DB 真值 4-29=5144 / 4-30=5142 一致).
- PT 链 4 schtask 全 Disabled: `DailySignal` (4-28 LastRun) / `DailyExecute` (4-19 LastRun) / `DailyReconciliation` (4-28 LastRun) / `IntradayMonitor` (4-29 10:25 LastRun, 当日 emergency_close 之前最后跑一次).

→ **klines/daily_basic 4-29+4-30 silent stop 真因关联**: PT 链 schtask 全 Disabled, 与 klines/daily_basic 4-29/4-30 真停 时序一致 (DailySignal LastRun=4-28 16:30, klines/daily_basic MAX=4-28).

---

## §B pull script 真生产路径

### B.1 grep + read 真测

`scripts/` 下 daily 拉取相关 script:
- `scripts/pull_moneyflow.py` ✅ (独立 daily script, schtask `QuantMind_DailyMoneyflow` 17:30)
- `scripts/compute_daily_ic.py` (factor IC 计算)
- `scripts/factor_health_daily.py` (factor health)
- 0 `scripts/pull_klines.py` / `scripts/pull_daily_basic.py` / `scripts/update_klines_daily.py`

→ klines/daily_basic 真**不是** independent daily script, 真生产 ETL 路径**内嵌**于 PT pipeline.

### B.2 PT pipeline 真 ETL 入口

`backend/app/services/pt_data_service.py:25-100+` — `fetch_daily_data(trade_date, conn, skip_fetch)`:

```python
# pt_data_service.py:25-96 (节选, 省略 index pipeline DataPipeline.ingest 细节 + stock_status 增量更新)
def fetch_daily_data(trade_date: date, conn=None, skip_fetch: bool = False) -> dict:
    """并行拉取当日klines+basic+index数据并入库。"""
    api = TushareAPI()
    def _fetch_klines():
        df = api.merge_daily_data(td_str)
        return upsert_klines_daily(df, conn)  # ← klines_daily 真 upsert
    def _fetch_basic():
        df = api.fetch_daily_basic_by_date(td_str)
        return upsert_daily_basic(df, conn)   # ← daily_basic 真 upsert
    def _fetch_index():
        # 拉取 000300.SH / 000905.SH / 000852.SH
        ...
    with ThreadPoolExecutor(max_workers=3) as executor:
        # 并行 3 thread (klines / basic / index)
        ...
```

### B.3 真生产 caller chain

`scripts/run_paper_trading.py` 真 import + 真调用:

| line | 用途 | 触发 schtask |
|---|---|---|
| `:45` | `from app.services.pt_data_service import fetch_daily_data` | — |
| `:211` (含 `:210` 注释 `# Step 1: 数据拉取`) | Step 1 (signal_phase): `fetch_result = fetch_daily_data(trade_date, skip_fetch=skip_fetch)` | **`QuantMind_DailySignal` 16:30** |
| `:401` | Step 5.5 (execute_phase): `fetch_daily_data(exec_date, skip_fetch=False)` | **`QuantMind_DailyExecute` 09:31** |

→ klines/daily_basic 真 daily ETL 触发依赖 PT 2 个 schtask (DailySignal + DailyExecute) 真活. **2 schtask 全 Disabled 4-28/4-29 起 → 真 0 触发, 真不拉**.

### B.4 vs moneyflow 真生产路径对比

| 维度 | moneyflow_daily | klines_daily / daily_basic |
|---|---|---|
| pull script | `scripts/pull_moneyflow.py` (独立) | `backend/app/services/pt_data_service.fetch_daily_data` (PT 内嵌) |
| schtask | `QuantMind_DailyMoneyflow` (独立, 17:30 daily) | **0 独立**, 由 `QuantMind_DailySignal` 16:30 + `DailyExecute` 09:31 触发 |
| schtask 真状态 (5-2 实测) | Ready, LastResult=0, daily run | **全 Disabled 4-28/4-29 起** |
| 4-29/4-30 真值 | 5144 + 5142 行 (真拉了) | 0 + 0 行 (真没拉) |
| coupling | 与 PT 链解耦 | 与 PT 链强耦合 |

**真因可视化**:
```
moneyflow:   [Tushare API] → pull_moneyflow.py → moneyflow_daily ✅ (独立 schtask 真活)
                              ↑ DailyMoneyflow 17:30

klines:      [Tushare API] → fetch_daily_data → klines_daily ❌ (内嵌 PT, schtask Disabled)
daily_basic:                    ↑ DailySignal 16:30 (Disabled) + DailyExecute 09:31 (Disabled)
```

---

## §C 4-29 user 决议链 cross-check

### C.1 docs/audit/ 4-29 真存在文档 (实测 `ls`)

```
link_paused_2026_04_29.md       ← 4-29 链路停止 PR 真清单
SHUTDOWN_NOTICE_2026_04_30.md   ← PT 重启 gate prerequisite
STATUS_REPORT_2026_04_29_link_pause.md
STATUS_REPORT_2026_04_30_D3_*  (multiple)
PT_restart_gate_cleanup_2026_04_30.md
```

→ `link_paused_2026_04_29.md` 真存在 (反 Layer 2.1 §I.2.C v1 cite "可能不存在", 真是 grep 路径不一致导致 false negative). reviewer P2-2 fix 已生效.

### C.2 link_paused_2026_04_29.md 真改动范围 (实测 Read)

4 件 pause 项 (`§A` ~ `§D`):

| § | 改动 | 文件 | 关联 PT 链 |
|---|---|---|---|
| A | LIVE_TRADING_DISABLED 真金硬开关 | 6 文件 (config/exceptions/guard/broker_qmt) | 真金 trade 路径 |
| B | Beat `risk-daily-check` (14:30 工作日) 注释 | `backend/app/tasks/beat_schedule.py:59-70` | Risk Framework Beat |
| C | Beat `intraday-risk-check` (`*/5` 9-14) 注释 | `backend/app/tasks/beat_schedule.py:71-83` | Risk Framework Beat |
| D | 2 smoke skip (mvp_3_1 risk imports) | `backend/tests/smoke/*` | Smoke test |

**关键 cite**:
> 数据链 (`scripts/qmt_data_service.py` / `realtime_data_service.py`) **保留** — 数据继续刷, 持仓快照仍记录.

→ link_paused 4-29 决议**明确保留数据链**, 但: 这里"数据链"指 **qmt_data_service** (Redis A-lite cache 实时数据) + **realtime_data_service** (实时刷新), **NOT** 包含 daily ETL `fetch_daily_data` (klines/daily_basic).

### C.3 schtask Disabled 真状态 vs link_paused 真改动

link_paused 4-29 PR 真改动 (4 项 §A~§D) **0 处直接 disable schtask**. PT 链 schtask Disabled (DailySignal / DailyExecute / DailyReconciliation / IntradayMonitor) 是**另一独立 user 决策** (cite memory: 4-29 user 决议清仓暂停 PT, 走 manual schtasks /change /tn ... /disable).

→ user 决议链真**包含** disable PT 链 schtask, 但**不直接 target** klines/daily_basic. PT 链 schtask 包含 ETL 触发 (DailySignal Step 1) → user 决议**间接**带掉 ETL.

→ **真因 RC 明确**: PT 暂停决议 → DailySignal 4-28 起 Disabled → ETL 4-29 起 0 触发 → klines/daily_basic 真 stale.

### C.4 PT 重启 gate prerequisite (cite SHUTDOWN_NOTICE_2026_04_30.md)

> Memory cite: SHUTDOWN_NOTICE §9 "PT 重启 gate prerequisite": ① DB 4-28 stale snapshot 清 ② paper-mode 5d dry-run ③ .env paper→live 用户授权.

→ PT 重启 gate enable DailySignal 是 prerequisite 之一, 真 enable 后 ETL 自动恢复. **不需独立修 klines/daily_basic schtask** (因为本来就没独立 schtask).

---

## §D 候选 root cause + 候选 action

### D.1 RC 排查结果

| 候选 RC (§I.2.D 标的) | 排查 | 结论 |
|---|---|---|
| RC1: schtask 真 disabled (4-29 user 决议链顺手关) | DailySignal 真 Disabled 4-28 起, IntradayMonitor 4-29 10:25 LastRun (emergency_close 当日最后跑) | **部分对**: user 决议 disable 是 PT 链, 不是直接 target klines schtask (因为 0 独立 klines schtask) |
| RC2: schtask 真活但 script silent fail | DailySignal Disabled, 0 schtask 触发 → 0 script run | ❌ 排除 |
| RC3: schtask 真活但 Tushare 4-29/4-30 真没数据 | trading_calendar 4-29/4-30=True + moneyflow 同期真拉 5144/5142 行 | ❌ 排除 (4-29/4-30 真是 trading_day, Tushare 真有数据) |
| **RC4 (新发现)** ⭐: klines/daily_basic ETL 与 PT 链架构耦合 | run_paper_trading.py:210/401 真唯一 daily ETL 入口, 通过 DailySignal/DailyExecute schtask 触发. moneyflow 走独立 pull_moneyflow.py 解耦. | ✅ **真因** |

### D.2 真因诊断 (RC4 完整 chain)

```
设计选择 (历史):
  klines/daily_basic ETL 内嵌于 PT pipeline (run_paper_trading.py Step 1 / Step 5.5)
  fetch_daily_data 是唯一 daily 入口
  触发 schtask: QuantMind_DailySignal (16:30) + QuantMind_DailyExecute (09:31)

4-29 user 决议清仓暂停 PT:
  → 手工 schtasks /change /disable QuantMind_DailySignal (LastRun 4-28 16:30)
  → 手工 schtasks /change /disable QuantMind_DailyExecute (LastRun 4-19 09:31, 4-19 后已停)
  → 手工 schtasks /change /disable QuantMind_DailyReconciliation
  → 手工 schtasks /change /disable QuantMind_IntradayMonitor

间接后果 (architecture coupling):
  → DailySignal Disabled 4-29 起 → run_paper_trading.py 0 触发 → fetch_daily_data 0 调用
  → klines/daily_basic 4-29/4-30 真没拉 (silent stop)
  → moneyflow_daily 解耦, 走独立 schtask, 真拉 (4-29=5144 / 4-30=5142)

5-01 起观测到症状:
  → QM-HealthCheck data_fresh check fail (klines<4-30)
  → QuantMind_DataQualityCheck fail (klines/daily_basic 滞后 2 trading days)
  → schtask LastResult=1 持续 (本 reconnaissance 起手时观测的真症状)
```

### D.3 候选 action (推荐 + 风险评估)

| Action | scope | 风险 | 推荐 |
|---|---|---|---|
| **A1 短期 backfill 4-29+4-30 数据** | 手工跑 `python -c "from app.services.pt_data_service import fetch_daily_data; fetch_daily_data(date(2026,4,29)); fetch_daily_data(date(2026,4,30))"` (0 改代码) | 低 (Tushare API 真有数据, 4-29/4-30 trading_day, 不是 fabricate). 影响 factor_values 历史 (依赖 klines), 可能触发下游因子重算 | ✅ **推荐起手 (Layer 2.2 sub-task 候选)** — 0 修代码, 解决真症状 |
| **A2 架构解耦 (长期)** | 把 klines/daily_basic 真 ETL 从 PT pipeline 解出, 建独立 `pull_daily.py` + 独立 schtask `QuantMind_DailyKlines` (沿用 pull_moneyflow pattern). 修代码 + 新 schtask | 中 (修代码必走 PR + reviewer; 新 schtask 注册需 user 配合 admin 权限) | ⚠️ 留 Layer 2.3+ (修代码 ≠ reconnaissance scope, 也不紧急 — PT 重启时 enable DailySignal 自动恢复) |
| **A3 接受 stale 待 PT 重启** | 0 改 / 0 backfill, 等 PT 重启 gate 通过后 enable DailySignal | 高 (4-29/4-30 数据永久缺失, factor_ic_history MAX 卡 4-28, 影响 Layer 1 fast_ic_recompute MAX cite 一致性) | ❌ **不推荐** (非紧急但永久债务) |
| **A4 混合: A1 + A2** | 短期 backfill (A1) + 长期解耦 (A2) | 综合 | ⭐ **首选**: 立即解决真症状 + 长期消除架构耦合 |

### D.4 推荐起手次序

1. **首推 A1** (短期 backfill 2 trading days 数据): 0 修代码, 由 user 决议是否手工跑 `fetch_daily_data(2026-04-29)` + `(2026-04-30)`. 风险低, 立即解决真症状.
2. **次推 A2** (架构解耦): Layer 2.3+ sub-task 单独 plan + reviewer + AI self-merge. 不紧急, 留 PT 重启后再起手 (避免与 PT 重启窗口冲突).
3. **不推荐 A3** (接受 stale): 永久数据债务, 影响下游 factor 链一致性.

---

## §E 关联 finding (本 reconnaissance 顺手发现)

### E.1 health_check.py data_fresh tolerance 真深读 (反 Layer 2.1 §F.3 transparency)

`scripts/health_check.py:39-66` `check_data_freshness`:

```python
def check_data_freshness(conn, trade_date: date) -> tuple[bool, str]:
    cur.execute(
        """SELECT MAX(trade_date) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date < %s""",
        (trade_date,),
    )
    prev_trading_day = cur.fetchone()[0]
    cur.execute("SELECT MAX(trade_date) FROM klines_daily")
    max_klines_date = cur.fetchone()[0]
    if max_klines_date >= prev_trading_day:
        return True, ...
    else:
        return False, f"数据过期: klines最新={max_klines_date}, 期望>={prev_trading_day}"
```

→ 真**已走 trading_calendar 真 holiday-aware**, tolerance 阈值真精确 (期望 = `MAX(trade_date) WHERE is_trading_day=TRUE AND trade_date < today`). **0 hardcoded 阈值** — 反 Layer 2.1 §F.3 v1 提问"是 today / today-2 / today-N 计算?", 真值: **直接走 trading_calendar 真 prev_trading_day**, 与 5-01~5-05 holiday window 完美对齐. 反 Layer 2.1 v1 framing "tolerance 未对齐" 完全错框架.

### E.2 数据链耦合架构债务 (LL 候选)

| 历史 design 选择 | 真状态 | 候选 LL |
|---|---|---|
| klines/daily_basic ETL 内嵌 PT pipeline (run_paper_trading.py Step 1) | PT 暂停 → ETL silent stop → 真生产数据 stale | LL 候选: **关键基础数据 ETL 不应耦合于业务 pipeline**, 应独立 schtask + 解耦 |
| moneyflow_daily 独立 schtask (pull_moneyflow.py + QuantMind_DailyMoneyflow) | PT 暂停期间真活, 数据持续真新 | 真生产正确 pattern |

→ **候选 LL-101**: 关键基础数据 (klines/daily_basic/moneyflow 等) ETL 必走独立 schtask + script, 不耦合于业务 pipeline (回测 / PT / GP), 防业务暂停 → 数据 silent stop. (待 user 决议 promote.)

---

## §F transparency — 我没真测的

为反 anti-pattern v3.0 (cite 当真值), 列出本 audit **未真测**项目:

1. **factor_values 4-29/4-30 真值**: 本 audit 未真查 factor_values 4-29/4-30 真行数 (cite Layer 2.1 §C.1 `factor_values MAX = 4-28`). klines stale → factor stale 推断真但未直接 verify.
2. **`scripts/factor_health_daily.py` 4-29/4-30 真状态**: cite memory FactorHealthDaily 5-1 17:30 LastResult=0 真活, 但 4-29/4-30 真触发输出未 read 验证 (FactorHealthDaily 是否报 klines stale).
3. **`backend/app/data_fetcher/data_loader.py` upsert_klines_daily / upsert_daily_basic 真实现**: 本 audit 未深读, 仅依赖 pt_data_service.py:20 import 推断. 假设这两 upsert 真生效 (反 silent fail RC2 已排除, 不需深查).
4. **A1 backfill action 真可行性**: 本 audit 未真试跑 `fetch_daily_data(date(2026,4,29))` (reconnaissance 0 改 / 0 数据 sustained). 真试跑留下一 sub-task 决议起手.
5. **schtasks /change /disable 真触发命令记录**: cite memory "user 4-29 决议清仓暂停 PT" 但 user 真用什么命令 disable 4 个 schtask 未真考据 (manual schtasks /change OR PowerShell Disable-ScheduledTask). 不影响 RC4 真因诊断.

---

## §G 验收 checklist

- [x] §A schtask 真状态 24 schtasks 真测 (Ready 17 / Disabled 6 + 1 dummy) ✅
- [x] §B pull script 真生产路径 (pt_data_service.fetch_daily_data + run_paper_trading.py:210/401 真 caller) ✅
- [x] §C 4-29 user 决议链 cross-check (link_paused 4-29 PR 4 项真改动 + schtask Disabled 真状态 + 真因 chain) ✅
- [x] §D 候选 RC + action (RC1/RC2/RC3 排查 + RC4 真因 + A1/A2/A3/A4 推荐) ✅
- [x] §E 顺手发现 (health_check tolerance 真深读 + LL-101 候选) ✅
- [x] §F transparency (5 未真测项) ✅
- [x] 0 修代码 / 0 backfill / 0 改 schtask sustained ✅
- [x] 0 PT 触碰 / 0 .env 改动 / 0 hook bypass sustained ✅

---

## §H 顶层结论

**Layer 2.1.7 真测真值锁定**:

1. **真因 RC4** (新发现, 不在 §I.2.D v1 候选 RC1/RC2/RC3): klines/daily_basic ETL 内嵌 PT pipeline (`run_paper_trading.py:210` Step 1 → `pt_data_service.fetch_daily_data`), 触发依赖 `QuantMind_DailySignal` (16:30) + `QuantMind_DailyExecute` (09:31). 4-29 user 决议清仓暂停 PT → 手工 disable PT 链 4 schtask → ETL 4-29 起 0 触发 → klines/daily_basic silent stop.

2. **真因 NOT** holiday tolerance / silent fail / Tushare 无数据 (RC1/RC2/RC3 全排除).

3. **moneyflow_daily 真活** 因走独立 schtask `QuantMind_DailyMoneyflow` + `pull_moneyflow.py`, 与 PT 链解耦. 这是真生产正确 pattern, klines/daily_basic 是耦合 anti-pattern.

4. **PT 重启 gate enable DailySignal 后, ETL 自动恢复** — 不需独立修 klines/daily_basic schtask (因为本来就没独立 schtask).

5. **候选 action**:
   - ⭐ **A1** 短期 backfill 4-29/4-30 数据 (0 改代码, user 手工跑 fetch_daily_data, 风险低)
   - **A2** 架构解耦 (Layer 2.3+ 修代码, 不紧急)
   - ❌ A3 接受 stale (永久数据债务, 不推荐)
   - **A4 混合 (A1 + A2)** = 首选

6. **顺手 finding**:
   - `health_check.py` data_fresh tolerance 真已走 trading_calendar holiday-aware (反 Layer 2.1 §F.3 v1 提问 "是否硬编码", 真值: 0 硬编码, 走 trading_calendar 真 holiday-aware).
   - **候选 LL-101**: 关键基础数据 ETL 不应耦合于业务 pipeline (回测 / PT / GP), 必走独立 schtask + script. 待 user 决议 promote.

7. **user 决议 candidates**:
   - 起 A1 backfill (Layer 2.2 sub-task)?
   - 起 A2 解耦 (Layer 2.3+ sub-task, 必走 PR + reviewer)?
   - promote LL-101 (LESSONS_LEARNED.md)?
   - 接受 RC4 真因 + 留 PT 重启时 ETL 自动恢复?
