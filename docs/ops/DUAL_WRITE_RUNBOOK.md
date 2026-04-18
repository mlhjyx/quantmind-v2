# Dual-write 窗口操作手册 (MVP 2.1c Sub3 启动硬门自动化)

> **适用**: 2026-04-20 (周一) ~ 2026-04-25 (周五) 5 交易日 dual-write 窗口
> **目标**: 确认新 `TushareDataSource` (cf86447 扩 3 API) 与老 `fetch_base_data.py` 产出 100% 一致, 满足 MVP 2.1c Sub3 main (删老 fetcher) 启动 3 硬门之一
> **执行模式**: 🤖 **默认 Celery Beat 自动跑** (每工作日 15:20, `app.tasks.dual_write_tasks.run_dual_write_check`), 用户仅需: (a) Step 0 一次性配 TUSHARE_TOKEN, (b) 周五 04-25 查 `--status` 确认 5/5 PASS. 手动运行命令仅诊断时使用.
> **耗时**: 配置一次 5min + 每周五查一次 --status 1min (原日跑 2min × 5 改为 0min)

---

## 🎯 窗口硬门 (3 项全满足才启动 Sub3 main)

| # | 硬门 | 本 runbook 覆盖 | 如何验证 |
|---|---|---|---|
| 1 | **连续 5 交易日 dual-write 新老 100% 对齐** (行数 + 12 关键列 md5 一致) | ✅ | `scripts/dual_write_check.py --status` 显示 5/5 PASS |
| 2 | **regression --years 5 max_diff=0 × 3 次** | ❌ (用户每天盘后跑一次, 3 次取最近 3 个交易日即可) | `python scripts/regression_test.py --years 5` 看 max_diff |
| 3 | **任一 fail → 窗口重置** (重新累积 5 天) | ✅ | state json 自动记录, FAIL 需手修后重跑 |

---

## 🤖 自动化架构 (默认, 已激活)

| 组件 | 内容 |
|---|---|
| 触发 | Celery Beat `crontab(hour=15, minute=20, day_of_week="1-5")` |
| 执行 | `app.tasks.dual_write_tasks.run_dual_write_check` Celery task |
| 内部 | subprocess 调 `scripts/dual_write_check.py` (复用既有代码, 无重复) |
| 交易日过滤 | task 内 `_is_trading_day()` 查 `trading_calendar` 表, 节假日自动跳过 |
| PASS 日志 | `logger.info "[dual_write_check] 2026-04-20 PASS old=5490 new=5490"` |
| FAIL 日志 | `logger.error "[dual_write_check] 2026-04-20 FAIL ..."` |
| FAIL 告警 | StreamBus 广播 `qm:dual_write:fail_alert` 事件 (payload 含 date/status/exit/codes_only_in_X/stderr_snippet) |
| ERROR (TOKEN 缺) | `logger.warning` 不告警 (环境问题, 非数据问题) |

**查看自动执行日志**:
```powershell
# Celery worker 日志 (Servy 管理)
Get-Content D:\quantmind-v2\logs\celery-stdout.log -Tail 50 | Select-String "dual_write"
```

**查看 StreamBus FAIL 告警**:
```powershell
& "D:\Redis\redis-cli.exe" XRANGE qm:dual_write:fail_alert - + COUNT 10
```

**服务依赖** (Servy 管理, 自动运行):
- ✅ `QuantMind-CeleryBeat` — 调度触发 (15:20)
- ✅ `QuantMind-Celery` — worker 执行
- ✅ Redis (broker/backend)

---

## 📅 用户操作 (极简版)

### Step 0: 确认 backend/.env TUSHARE_TOKEN 已配 (应已存在)

TUSHARE_TOKEN 通过 **pydantic-settings 从 `backend/.env` 读**, 不走 `os.environ`.
如果之前 PT / Tushare 能跑, 说明 token 已配好.

```powershell
cd D:\quantmind-v2

# 1. 验证 settings 能读到 token (权威检查)
.\.venv\Scripts\python.exe -c "
from app.config import settings
assert settings.TUSHARE_TOKEN, 'backend/.env TUSHARE_TOKEN 未配或为空'
print(f'OK settings.TUSHARE_TOKEN len={len(settings.TUSHARE_TOKEN)}')"

# 2. 验证真 Tushare API 可调 (ping)
.\.venv\Scripts\python.exe -c "
from app.data_fetcher.tushare_api import TushareAPI
df = TushareAPI().query('trade_cal', start_date='20260401', end_date='20260401')
print('Tushare OK, 交易日:', len(df), '条')"
```

**如果你之前没手动配** `$env:TUSHARE_TOKEN` (PowerShell 环境变量), **没关系** — pydantic
读 `backend/.env` 即可. 系统 env 变量仅在覆盖场景用.

### Step 1: 确认 Celery Beat 服务运行 (一次性)

```powershell
# Servy CLI 要求 --name 参数, 逐个检查
D:\tools\Servy\servy-cli.exe status --name="QuantMind-CeleryBeat" --quiet
D:\tools\Servy\servy-cli.exe status --name="QuantMind-Celery" --quiet
D:\tools\Servy\servy-cli.exe status --name="QuantMind-FastAPI" --quiet
D:\tools\Servy\servy-cli.exe status --name="QuantMind-QMTData" --quiet

# 每条期待: "Service status: Running"
# 若 Stopped, 启动: ... start --name="..."
```

### Step 2: 每周/窗口结束查 5 日进度 (推荐做法)

```powershell
cd D:\quantmind-v2
.\.venv\Scripts\python.exe scripts\dual_write_check.py --status

# 期待输出 (04-25 周五收盘后):
# Dual-write 窗口进度 (state: cache/dual_write_state.json):
#   2026-04-20 ✅ PASS  old=5491 new=5491 checked=2026-04-20T15:22:03
#   2026-04-21 ✅ PASS  old=5489 new=5489 checked=2026-04-21T15:18:47
#   2026-04-22 ✅ PASS  old=5490 new=5490 checked=2026-04-22T15:25:11
#   2026-04-23 ✅ PASS  old=5488 new=5488 checked=2026-04-23T15:21:34
#   2026-04-25 ✅ PASS  old=5492 new=5492 checked=2026-04-25T15:20:55
#
# 窗口合格天数: 5 / 5 (MVP 2.1c Sub3 启动硬门之一)
```

### Step 3: 跑 regression (硬门 #2, 每天 1 次累积, 手动)

```powershell
.\.venv\Scripts\python.exe scripts\regression_test.py --years 5

# 期待输出:
# [Run 1] Running 5yr backtest...
#   max_diff: 0.0
#   Sharpe: baseline=0.6095, current=0.6095
# 只要 max_diff=0 即 PASS, 累积 3 天 = 硬门 #2 达标
```

---

## 🔧 手动命令 (诊断 / 补跑, 非日常)

**何时手动**: 自动跑 FAIL / Celery 宕机 / 补跑某历史日期 / 凭证诊断.

```powershell
cd D:\quantmind-v2

# A. 手动触发今日对齐 (自动跑一次, 相当于 task 内部 subprocess)
.\.venv\Scripts\python.exe scripts\dual_write_check.py

# B. 指定日期补跑
.\.venv\Scripts\python.exe scripts\dual_write_check.py --date 2026-04-21

# C. 回溯整个窗口 (便于观察连续变化)
.\.venv\Scripts\python.exe scripts\dual_write_check.py --backfill 2026-04-20 2026-04-25

# exit code: 0=PASS / 1=FAIL / 2=ERROR
```

**输出 JSON 示例 (PASS)**:
```
{
  "status": "PASS",
  "old_rows": 5491,
  "new_rows": 5491,
  "row_count_match": true,
  "codes_only_in_old": 0,
  "codes_only_in_new": 0,
  "all_columns_match": true,
  "columns": {...}
}
```

---

## 📊 报告位置

| 文件 | 内容 | 用途 |
|---|---|---|
| `cache/dual_write_state.json` | 5 日进度 (机器可读) | `--status` 命令读 |
| `docs/reports/dual_write/<date>.md` | 当日对齐详情 (12 列 diff 明细) | FAIL 时定位问题 |
| `cache/baseline/regression_result_5yr.json` | regression 最近一次结果 | 硬门 #2 PASS 追踪 |

---

## 🔍 常见 FAIL 诊断 (按症状找根因)

### 症状 A: `old_rows ≠ new_rows`

**可能根因**:
1. **老 fetcher 当日未跑**: `old_rows = 0` → 等 Servy Celery 拉取完成 (通常 15:00-15:30), 稍后重跑
2. **新路径 Tushare 返空**: `new_rows = 0` → 检查 `codes_only_in_old > 0`, 可能 Tushare API 某日未更新 (跨交易所假期?)
3. **老 fetcher FK 过滤**: 老 fetcher 过滤 symbols 表不存在的 code, 新路径不过滤 (MVP 2.1b 策略). 差异 ≤ 50 行算正常噪音

**诊断**:
```powershell
# 看 old 独有 code
$env:PGPASSWORD = "..."
& "D:\pgsql\bin\psql.exe" -h localhost -p 5432 -U xin -d quantmind_v2 -c "
SELECT code FROM klines_daily WHERE trade_date='2026-04-22'
EXCEPT
SELECT code FROM klines_daily WHERE trade_date='2026-04-21'
LIMIT 20"
```

### 症状 B: `adj_factor` 列 only_old_nan > 0 或 mismatch

**可能根因**:
1. **老 fetcher fallback 1.0, 新 fetcher 也 fallback 1.0, 但存在 NaN 边缘**: 检查 `docs/reports/dual_write/<date>.md` 看 only_old_nan vs only_new_nan
2. **Tushare `adj_factor` API 改字段名**: Tushare 偶尔变字段, 需检查 response. 读 `D:\quantmind-v2\backend\platform\data\sources\tushare_source.py::_fetch_klines_merged` 的 `_CONTRACT_API_MAP` 比对

**诊断**:
```powershell
# 抽 1 个差异 code, 分别查新老
& "D:\pgsql\bin\psql.exe" -h localhost -p 5432 -U xin -d quantmind_v2 -c "
SELECT code, adj_factor FROM klines_daily WHERE trade_date='2026-04-22' AND code='600519.SH'"
# 对比:
.\.venv\Scripts\python.exe -c "
from datetime import date
from app.data_fetcher.tushare_api import TushareAPI
df = TushareAPI().query('adj_factor', trade_date='20260422', fields='ts_code,adj_factor')
print(df[df['ts_code']=='600519.SH'])"
```

### 症状 C: `up_limit` / `down_limit` 列 mismatch

**可能根因**:
1. **老 fetcher stk_limit 当日空, 新 fetcher 当日也空** — 新旧都 None, 不 fail (on both_nan skip)
2. **老 fetcher stk_limit 某 code 缺, 新 fetcher 也缺** — 同上
3. **老 fetcher 有值, 新 fetcher 无值** — stk_limit API 有时延迟几分钟, 稍后重跑

**诊断**: 读 `docs/reports/dual_write/<date>.md` `up_limit` 行的 `only_old_nan` vs `only_new_nan`. 如两者接近, 说明有时差, 重跑. 如严重偏向一方, 说明 API pattern 差异.

### 症状 D: `amount` 列有大 diff (> 1000)

**可能根因**:
1. **单位转换错位**: 新路径 RAW = 千元 (Tushare), DB = 元 (老 fetcher 转换). 脚本已 `* 1000.0`, 但可能未触发.
2. **精度 overflow**: amount 很大 (10^9 元级别), 检查脚本 `to_numeric` 是否转 float64

**诊断**:
```python
# 抽检几行对比
.\.venv\Scripts\python.exe -c "
from app.data_fetcher.data_loader import get_sync_conn
from app.data_fetcher.tushare_api import TushareAPI
from datetime import date
conn = get_sync_conn()
cur = conn.cursor()
cur.execute(\"SELECT code, amount FROM klines_daily WHERE trade_date='2026-04-22' AND code='600519.SH'\")
print('DB 老:', cur.fetchone())
df = TushareAPI().query('daily', trade_date='20260422', fields='ts_code,amount')
row = df[df['ts_code']=='600519.SH'].iloc[0]
print(f'Tushare RAW 新 (千元): {row[\"amount\"]}, 转元: {row[\"amount\"]*1000}')
"
```

### 症状 E: `status: ERROR, error: TUSHARE_TOKEN not set`

- `$env:TUSHARE_TOKEN` 当前 shell 未设, 或永久环境变量读不到.
- 重开 PowerShell / 配置永久环境变量 (sysdm.cpl)

### 症状 F: `status: ERROR, error: old path empty`

- 老 fetcher 当日未跑, 或 Celery Beat 被 Servy 停了
- 查 Servy: `D:\tools\Servy\servy-cli.exe status | findstr QuantMind`
- 手动触发: `cd backend && ..\.venv\Scripts\python.exe -m app.data_fetcher.fetch_base_data`

---

## 🚨 紧急回滚 (如窗口 FAIL 且难修)

**场景**: 新 TushareDataSource 扩 3 API 有隐性 bug, 无法短期修复, 需回滚到 Sub3-prep 之前

```powershell
# 查看 Sub3-prep commit
cd D:\quantmind-v2
git log --oneline | findstr "Sub3-prep"
# 期待: cf86447 feat(platform): MVP 2.1c Sub3-prep ...

# 回滚方案 A: revert (保留历史)
git revert cf86447

# 方案 B: 仅回 schema 保留扩 3 API (让新路径 fallback 全 None 再跑对比)
# 编辑 backend/platform/data/sources/tushare_source.py 回 v1 schema

# 方案 C: 停用 dual-write 监控 (窗口暂停)
# 不再调 scripts/dual_write_check.py, Sub3 main 推后再评估

# 回滚后重跑硬门
.\.venv\Scripts\python.exe -m pytest backend/tests -m smoke --tb=short -q
.\.venv\Scripts\python.exe scripts/regression_test.py --years 5
```

**回滚不会影响**:
- 老 fetcher 继续正常写 klines_daily (cf86447 未改老 fetcher)
- PT / 研究脚本 (都走 DB 读数据)
- MVP 2.2 Lineage (独立 feature)

---

## 📝 5/5 PASS 后下一步 (2026-04-25 后, Session 6 开工)

```powershell
# 1. 最终确认
.\.venv\Scripts\python.exe scripts\dual_write_check.py --status
# 期待: "窗口合格天数: 5 / 5"

# 2. 最近 3 次 regression 查
git log -10 --oneline cache/baseline/regression_result_5yr.json
# 或看 cache/baseline/regression_result_5yr.json 里 max_diff=0 连续 3 次

# 3. 告知 Claude Session 6 开工
# 示例 prompt:
# "dual-write 窗口 5/5 PASS, regression 3 次 max_diff=0, MVP 2.1c Sub3 main 开工"
```

**Session 6 Sub3 main 实施清单** (Claude 会做):
1. `rm backend/app/data_fetcher/fetch_base_data.py` (598 行)
2. `rm scripts/fetch_minute_bars.py` (~400 行, 改用 BaostockDataSource)
3. `scripts/qmt_data_service.py` 保留壳 (Servy entrypoint), 内部改调 `QMTDataSource.fetch`
4. `backend/app/tasks/daily_pipeline.py` 老 import 清理 + 改调 TushareDataSource
5. 硬门: `pytest -m smoke` + `regression max_diff=0 × 3` + 全量 pytest baseline ≤ 24
6. Servy 重启所有服务 + 健康检查

---

## 关联文档

- **设计**: `docs/mvp/MVP_2_3_backtest_parity.md` (MVP 2.3 开工前置, 本 dual-write 窗口完成后才启动)
- **调研**: `docs/research-kb/findings/mvp_2_3_opensource_eval.md` (MVP 2.3 前置调研)
- **Sprint 状态**: `memory/project_sprint_state.md` (Session 5 末 handoff)
- **Blueprint**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` §Part 4 MVP 2.1c
- **CLAUDE.md**: 铁律 10 (基础设施改动后全链路验证) / 17 (DataPipeline 唯一入库) / 36 (precondition 核对)

---

## 变更记录

- 2026-04-18 Session 5 末 v1.0 落盘 (cf86447 Sub3-prep + a2f3629 监控脚本 后). 用户周一 04-20 开始用.
