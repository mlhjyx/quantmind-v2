# MVP 2.1c · Data Framework — DAL 扩展 + 写路径合规 + 老 fetcher 退役

> **Wave**: 2 第 3 步 (MVP 2.1 拆分 3/3, Wave 2 数据基建收尾)
> **耗时实测**: ~10 天 (Sub1 ~3d + Sub2 ~2d + Sub3-prep ~1d + dual-write 窗口 5d + Sub3 main ~2d, 含 dual-write 等待窗口)
> **风险**: 高 (Sub3 main 删老 fetcher 是不可逆操作 + Celery daily_pipeline 链路重接)
> **前置 MVP 2.1b ✅**: 3 concrete DataSource (Tushare/Baostock/QMT) 上线, dual-write 期保老代码 0 改动
> **状态**: Sub1 ✅ Sub2 ✅ Sub3-prep ✅ dual-write 自动化 ✅ / **Sub3 main ⏳ 阻塞 dual-write 窗口 2026-04-25**
> **铁律**: 10 / 10b / 14 / 17 / 22 / 23 / 24 / 25 / 30 / 31 / 33 / 36 / 37 / 38 / 40

---

## 目标 (3 项)

1. **DAL 完整版扩展** — `PlatformDataAccessLayer` read_* 方法 4 → 11, Engine α 清理 (signal_engine 等). 闭环 MVP 2.1a 留下的 "13 处直连 SQL" 主体 (实测降级到 async DAL 专项推 MVP 2.2)
2. **写路径合规** — 2 写路径 (shadow_portfolio + stock_status_daily 2 处) 迁 `DataPipeline.ingest`, 闭环铁律 17 "数据入库必须通过 DataPipeline" 在 PT 路径的最后欠账
3. **老 3 fetcher 退役** — `fetch_base_data.py` (598 行) + `fetch_minute_bars.py` (~400 行) 删除, `qmt_data_service.py` 保留壳改调 QMTDataSource. dual-write 窗口 5/5 PASS + regression × 3 max_diff=0 双硬门保下线安全

## 非目标 (明确推后续)

- ❌ **async DAL 扩展** (mining/pipeline_utils + market.py + market_data_repository.py + factor_repository_repo + daily_pipeline 全是 async SQLAlchemy) → MVP 2.2 async DAL 专项 (Sub1 实测降级)
- ❌ **D 级 SQL 迁移** (fast_neutralize.py DDL+UPDATE JOIN / factor_analyzer.py WINDOW+JOIN subquery / pms 业务表) → 留 MVP 2.2 / Wave 3 (DAL 当前不支持)
- ❌ **ColumnSpec 扩 array/json/uuid** (backtest_tasks 写 backtest_run / factor_profiler 写 factor_profile 56 字段) → MVP 2.2 ColumnSpec 扩展专项 (实测后定位)
- ❌ **FactorCacheProtocol 落地 factor_cache.py** → 留 MVP 2.2 (与 Lineage 同 PR)
- ❌ **Sub3 main 不重写计算逻辑** — 仅删老 fetcher + 入口改调 DataSource, 数据语义 0 变更

---

## 实施结构 (4 sub-commit, 串行交付)

```
Sub1 (✅ commit 0a68618, ~630 行): DAL 扩能力
├── backend/platform/data/access_layer.py   ⚠️ +298 行 (4 → 11 read_* 方法)
│   ├── read_calendar(start, end) → list[date]
│   ├── read_universe(as_of) → list[str]   # astock 有效 + 未退市
│   ├── read_stock_status(codes, as_of) → DataFrame   # is_st/is_suspended/is_new_stock/board
│   ├── read_factor_names(source='registry'|'values') → list[str]
│   ├── read_freshness(tables) → dict[table, max_date]   # 白名单 7 表
│   ├── read_reconcile_counts(tables, as_of) → dict[table, count]
│   └── read_pead_announcements(trade_date, lookback_days=7) → DataFrame
├── backend/engines/signal_engine.py         ⚠️ get_rebalance_dates 走 DAL.read_calendar
├── backend/tests/test_dal_extended.py       ⭐ NEW 21 unit (sqlite mock)
└── backend/tests/smoke/test_mvp_2_1c_dal_live.py   ⭐ NEW 1 live smoke (PG)

Sub2 (✅ commit e8249361, ~300 行): 写路径合规 (铁律 17)
├── backend/app/data_fetcher/contracts.py    ⚠️ +SHADOW_PORTFOLIO TableContract (CONTRACT_REGISTRY 11→12)
├── backend/app/services/shadow_portfolio.py ⚠️ _write_shadow_portfolio: for-loop INSERT → DataPipeline.ingest
├── backend/app/services/pt_data_service.py  ⚠️ 2 处 execute_values INSERT stock_status_daily → _ingest_stock_status helper
├── backend/tests/test_pipeline_new_contracts.py  ⭐ NEW 9 unit (Contract 结构 + SQL 生成)
└── backend/tests/smoke/test_mvp_2_1c_c_level_live.py  ⭐ NEW 1 live smoke (subprocess + ON CONFLICT)

Sub3-prep (✅ commit cf86447 + 后续 b825cc2, ~310 行): KLINES_DAILY 扩 3 字段 + dual-write 自动化
├── backend/platform/data/sources/tushare_source.py  ⚠️ +130/-20
│   ├── KLINES_DAILY_DATA_CONTRACT v1→v2: schema +3 字段 (adj_factor / up_limit / down_limit)
│   ├── _fetch_klines_merged: 按日迭代 3 API (daily + adj_factor + stk_limit) + left merge + fallback
│   ├── _check_nan_ratio override (_NAN_TOLERANT_COLS 白名单 up/down_limit)
│   └── _check_value_ranges +adj_factor <= 0 / up/down_limit < 0
├── backend/tests/test_tushare_source.py     ⚠️ +6 new unit (29 total)
└── backend/tests/smoke/test_mvp_2_1b_tushare_live.py  ⚠️ +18/-5 (3 字段硬门)

dual-write 自动化 (✅ commits a2f3629 + edfae2f + b825cc2, ~500 行): Sub3 main 启动硬门
├── scripts/dual_write_check.py              ⭐ NEW 356 行 (load_old/new + compare 12 列 + state JSON)
├── backend/app/tasks/dual_write_tasks.py    ⭐ NEW ~140 行 (Celery task + StreamBus FAIL 告警)
├── backend/app/tasks/beat_schedule.py       ⚠️ +crontab(15:20, 周一-周五)
├── docs/ops/DUAL_WRITE_RUNBOOK.md           ⭐ NEW 319 行 (用户/诊断/紧急回滚 SOP)
└── cache/dual_write_state.json              ⭐ runtime (5 日窗口进度追踪)

Sub3 main (⏳ 等 2026-04-25 窗口验收): 老 fetcher 退役
├── backend/app/data_fetcher/fetch_base_data.py    ❌ DELETE (598 行)
├── scripts/fetch_minute_bars.py                   ❌ DELETE (~400 行)
├── scripts/qmt_data_service.py                    ⚠️ 保留壳 (Servy entrypoint), 内部改调 QMTDataSource.fetch
├── backend/app/tasks/daily_pipeline.py            ⚠️ 老 import 清理 + 改调 TushareDataSource
└── (硬门: smoke + regression × 3 + 全量 pytest baseline ≤ 24)
```

**规模合计**: ~1740 行实施 + ~310 行 docs/runbook + ~400 行 tests ≈ 2450 行 / 4 sub-commits

---

## 关键设计 (D1-D6)

### D1. DAL 扩 7 方法 — A 级 SQL 迁移现场重评估 8 → 0 (Sub1)

Explore agent 原报告的 8 A 级文件实测后:
- **6 文件 async SQLAlchemy** (market / market_data_repository / daily_pipeline / factor_repository_repo / fast_neutralize 含 DDL / factor_analyzer 含 WINDOW): DAL 当前 **sync only**, 推 MVP 2.2 async DAL 专项
- **2 文件不在 Platform 范围**: pms_engine (业务表 position_snapshot/trade_log 非白名单) / pms.py (0 裸 SQL, 仅调 Service 已合规)

**Sub1 实际迁移 = signal_engine.get_rebalance_dates 1 处** (sync 路径). conn 参数保留向后兼容 30+ 调用方签名不变, 内部改由 DAL 管理连接.

**教训** (LL-053 入册待考虑): 不做盲目迁移 (避免 IS NOT NULL 过滤等破坏 coverage 统计). 铁律 25 "代码变更前必读当前代码验证" 让 Sub1 没把语义漂移送上生产.

### D2. 写路径 4 → 2 文件实测降级 (Sub2)

| 文件 | Sub2 处理 | 推延理由 |
|---|---|---|
| `shadow_portfolio.py` | ✅ 迁 | 简单 8 字段动态建表, SHADOW_PORTFOLIO Contract 新增 |
| `pt_data_service.py` (2 处) | ✅ 迁 | STOCK_STATUS_DAILY Contract MVP 1.1 已存, 仅迁调用方 |
| `backtest_tasks.py` | ⏸ MVP 2.2 | backtest_run 表含 UUID + JSONB + TEXT[] + 20+ DECIMAL, ColumnSpec 当前无 array/json/uuid 类型 |
| `factor_profiler.py` | ⏸ MVP 2.2 | factor_profile 56 字段 (ic_1d/5d/10d/20d/60d/120d + regime + monotonicity), 工程量超 sub-commit 边界 (铁律 24) |

铁律 24 "MVP ≤ 2 页设计稿" 强制 Sub2 收紧到能干净落地的 2 文件, 剩下 2 文件升级 MVP 2.2 ColumnSpec 专项.

### D3. Sub3 拆 prep + main — 设计环根因 + 解决方案 (Sub3-prep)

**设计环 (Session 4 handoff 隐藏 bug)**:
- Sub3 启动硬门: "连续 5 交易日 dual-write 新老 100% md5 对齐"
- Sub3 实施清单 (Session 4 原文): "扩 3 API" + "删老 fetcher" 合一步
- **矛盾**: 扩字段 (adj_factor/up_limit/down_limit) 是硬门 precondition (不扩→day 1 md5 全 fail), 不是 result. 合一步 → 死循环

**解法** (cf86447): 拆出 Sub3-prep 只扩字段, 保老 fetcher 0 改动. Sub3-main (删老) 等 04-25 窗口验收后做.

**Sub3-prep 内部** (`_fetch_klines_merged` 仿老 fetcher pattern):
- 按日迭代 3 API: `ts.daily` + `ts.adj_factor` + `ts.stk_limit`
- left merge + fallback (adj_factor 空 → 1.0, stk_limit 空 → None)
- `_NAN_TOLERANT_COLS` 白名单跳 up/down_limit 的 `_check_nan_ratio` (fallback 100% NaN 合法)
- 统一 `raise RuntimeError("查询 trade_date=... 失败")` 保老测试 regex 兼容

### D4. dual-write 窗口契约 (Sub3 启动硬门)

**3 硬门** (全部满足才启动 Sub3 main):
1. 连续 5 交易日 dual-write 新老 100% md5 对齐 (`scripts/dual_write_check.py --status` 显示 5/5 PASS)
2. `regression --years 5` max_diff=0 × 3 次连续 (用户每天盘后跑一次)
3. 任一 fail → 窗口重置 (state json 自动记录, 修 diff 源头后重跑)

**自动化** (默认运行, edfae2f commit):
- Celery Beat `crontab(hour=15, minute=20, day_of_week="1-5")` 触发
- task `app.tasks.dual_write_tasks.run_dual_write_check` subprocess 调 `scripts/dual_write_check.py`
- task 内 `_is_trading_day()` 查 `trading_calendar` 自动跳节假日
- FAIL → StreamBus 广播 `qm:dual_write:fail_alert`
- ERROR (TUSHARE_TOKEN 缺) → `logger.warning` 不告警 (环境问题)

**TUSHARE_TOKEN 必走 pydantic-settings** (LL-053 教训, b825cc2 commit): `from app.config import settings; settings.TUSHARE_TOKEN`. `os.environ.get("TUSHARE_TOKEN")` 在生产代码禁用 (pydantic 读 .env 不 push os.environ).

### D5. Sub3 main 实施清单 (待 04-25 后)

```bash
# 1. 删老入库脚本 (~1000 行)
rm backend/app/data_fetcher/fetch_base_data.py     # 598 行
rm scripts/fetch_minute_bars.py                    # ~400 行

# 2. qmt_data_service.py 保留壳改调 (不动 Servy 配置)
# from app.platform.data.sources.qmt_source import QMTDataSource
# QMTDataService.run() 内部 60s loop 改调 source.fetch()

# 3. daily_pipeline.py 老 import 清理
# 删: from app.data_fetcher.fetch_base_data import BaseDataFetcher
# 加: from app.platform.data.sources.tushare_source import TushareDataSource
# Celery task 改用 source.fetch() + DataPipeline.ingest()

# 4. 硬门验证 (3 道)
pytest -m smoke --tb=short           # 25 PASS / 0 fail
python scripts/regression_test.py --years 5   # max_diff=0.0 × 3 次跑
pytest                                # full ≤ 24 fail (铁律 40 baseline)

# 5. Servy 重启 + 健康检查
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-Celery"
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-CeleryBeat"
D:\tools\Servy\servy-cli.exe restart --name="QuantMind-QMTData"
python scripts/health_check.py
```

### D6. 紧急回滚 (Sub3 main 出错时)

DUAL_WRITE_RUNBOOK §🚨 已记录 3 方案:
- **方案 A**: `git revert cf86447` (回滚 Sub3-prep)
- **方案 B**: 仅回 KLINES_DAILY schema 保留扩 3 API, fallback 全 None 再跑对比
- **方案 C**: 停用 dual-write 监控 (窗口暂停, Sub3 main 推后)

**回滚不影响** (老 fetcher Sub3 main 前 0 改动): PT / 研究脚本 / MVP 2.2 Lineage.

---

## 验收标准

### Sub1+Sub2+Sub3-prep+dual-write (✅ 已验收, Session 5 末)

| # | 项 | 实测 |
|---|---|---|
| 1 | DAL read_* 方法 4 → 11 | ✅ 21 unit + 1 live smoke PASS |
| 2 | SHADOW_PORTFOLIO + STOCK_STATUS_DAILY 2 写路径走 DataPipeline | ✅ 9 unit + 1 live smoke PASS |
| 3 | KLINES_DAILY +3 字段 (adj_factor/up_limit/down_limit) | ✅ 6 new unit + smoke 改 + Tushare live smoke 含 3 字段硬门 |
| 4 | dual-write 监控脚本 + Celery Beat 自动化 + FAIL StreamBus 告警 | ✅ 356 行脚本 + 140 行 task + RUNBOOK 319 行 |
| 5 | regression --years 5 max_diff=0 | ✅ Sharpe=0.6095 (Sub1/Sub2/Sub3-prep 各跑) |
| 6 | 全量 pytest fail | ≤ 24 (铁律 40, Session 5 末 24 fail / 2691 pass) |
| 7 | smoke 全集 | ✅ 25 PASS + 1 deselected (live_tushare, no token CI 跳过) |
| 8 | ruff clean 全新代码 | ✅ |
| 9 | 老 3 fetcher git diff (Sub3 main 前) | **0 改动** (dual-write) |
| 10 | Celery daily_pipeline / Servy QMTData 生产链路 | ✅ Running, 无 drift |

### Sub3 main (⏳ 待 04-25 后验收)

| # | 项 | 目标 |
|---|---|---|
| 11 | dual-write 窗口 | 5/5 PASS (cache/dual_write_state.json) |
| 12 | regression × 3 | max_diff=0 连续 3 次 |
| 13 | `git ls-files` 含 `fetch_base_data.py` | **0 hit** |
| 14 | `git ls-files` 含 `scripts/fetch_minute_bars.py` | **0 hit** |
| 15 | qmt_data_service.py | 保留 (壳, 内部改调 QMTDataSource) |
| 16 | daily_pipeline.py | import 改 TushareDataSource, 0 BaseDataFetcher 引用 |
| 17 | smoke + regression × 3 + 全量 pytest baseline | 全绿 |
| 18 | Servy 4 服务重启 + health_check.py | 全绿 |

---

## 开工协议 (铁律 36 precondition)

### Sub1+Sub2+Sub3-prep+dual-write 已开工时 (✅ Session 5 末满足)

- ✅ MVP 2.1a `BaseDataSource` 可用
- ✅ MVP 2.1b 3 concrete DataSource 上线 + 老 3 fetcher 0 改动
- ✅ MVP 1.1 `DataPipeline.ingest` 生产 work
- ✅ MVP 1.2 PlatformConfigLoader 可注入

### Sub3 main 开工时 (⏳ 等 2026-04-25 检查)

- ⏳ `python scripts/dual_write_check.py --status` 显示 **5/5 PASS** (硬门 #1)
- ⏳ `cache/baseline/regression_result_5yr.json` 最近 3 次 max_diff=0 (硬门 #2)
- ✅ `backend/platform/data/sources/tushare_source.py` 扩 3 字段已上线 (Sub3-prep)
- ✅ DUAL_WRITE_RUNBOOK §紧急回滚 readback (Sub3 main 出错时方案)
- ✅ Servy 4 服务 Running (CeleryBeat / Celery / FastAPI / QMTData)
- ⏳ 备份当前 prod DB (`scripts/pg_backup.py`) — Sub3 main 前一次性

---

## 禁做 (铁律)

- ❌ 不动 `backend/app/data_fetcher/contracts.py` 的 KLINES_DAILY 已扩 3 字段后 schema (Sub3-prep 锁)
- ❌ 不动 `backend/platform/data/sources/*.py` Template method 实现 (MVP 2.1a 锁)
- ❌ 不在 Sub3 main 重写计算逻辑 — 仅删老 fetcher + 入口改调 DataSource
- ❌ 不在 Sub3 main 同步迁 async 路径 (mining/market 等 6 文件) — 留 MVP 2.2 async DAL
- ❌ 不在 Sub3 main 同步加 ColumnSpec 扩展 (backtest_tasks/factor_profiler) — 留 MVP 2.2
- ❌ 不动 Servy QMTData 服务配置 (qmt_data_service.py 仅改内部, entrypoint 不动)
- ❌ 不删 dual-write 监控脚本 (Sub3 main 后保留作历史归档参考)
- ❌ Sub3 main FAIL 不重试到 max_diff > 0 — 必查根因 (DUAL_WRITE_RUNBOOK §🔍 常见 FAIL 诊断)

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | Sub3 main 删老 fetcher 后 Celery daily_pipeline 链路断 | 高 | daily_pipeline.py 同步迁 (D5 步 3) + Servy 重启后 health_check + 当晚 Celery log 监控 |
| R2 | qmt_data_service.py 改壳后 Servy entrypoint 行为变 | 中 | 保留 main loop 不动, 仅替换 60s sync 内部实现, Servy 配置 0 改动 |
| R3 | dual-write 窗口 04-20 ~ 04-25 中途出现 FAIL | 中 | RUNBOOK §🔍 6 种症状诊断, 失败重置窗口延期, 不强行 Sub3 main |
| R4 | Sub3 main 后 regression max_diff > 0 (新老路径数据语义漂移) | 低 (Sub3-prep 已对齐 schema) | 即刻 `git revert` 删除老 fetcher 的 commit, 老 fetcher 文件回写 |
| R5 | TUSHARE_TOKEN pydantic 与 os.environ 双命名空间陷阱 (LL-053) | 低 (b825cc2 已修) | 生产代码全走 `settings.TUSHARE_TOKEN`, 研究/归档脚本 3 处 `os.environ` 不影响生产 |
| R6 | Servy 重启后 QMT 实时链路恢复延迟 | 低 | qmt_data_service.py 60s loop 容忍 5 次失败再 raise, Redis fallback Hash 数据保留 90s TTL |
| R7 | 删老 fetcher 后历史问题难复现 | 低 | git log 永久保留, 必要时 `git checkout <SHA> -- backend/app/data_fetcher/fetch_base_data.py` 临时取回 |
| R8 | 测试债增长 (铁律 40) | 低 | Sub3 main 前后全量 pytest 对比, fail > 24 阻断 commit |

---

## 关联 ADR / 决策

- **ADR-006** (MVP 2.1a docs/adr/, BaseDataSource Template method 入库): 不需 supersede, 本 MVP 是 2.1a 的下游消费.
- **ADR-0009** (MVP 2.2 docs/adr/, ColumnSpec UUID/JSONB 扩展): 触发 Sub2 实测降级 backtest_tasks/factor_profiler 推迟决策依据. **编号 typo** (应是 ADR-007), Wave 2 完结 Blueprint v1.5 bump 时统一整理 (sprint_state L99).
- **Sub3 拆 prep + main 决策** (cf86447 commit msg): 设计环根因 (硬门 precondition 与 result 合一步死循环) + 解法 (拆 2 步). 不单独写 ADR, 入本设计稿 D3 即可 (铁律 24 设计稿层级聚焦).

---

## 下一步 (MVP 2.1c Sub3 main 后)

- **MVP 2.2 Data Lineage** (✅ Sub1+Sub2 已交付 Session 5): backtest_run 用 lineage_id 追溯
- **MVP 2.3 Backtest Framework + U1 Parity** (3-4 周, ⏳ 等 Sub3 main 完成): backtest_run DB 表 + BacktestMode + research/PT bit-identical
- **MVP 2.2 ColumnSpec 扩展专项** (估 1-1.5 周): backtest_tasks + factor_profiler 走 DataPipeline (Sub2 推延的 2 文件)
- **MVP 2.2 async DAL 扩展** (估 1-1.5 周): mining/market/factor_repository_repo/daily_pipeline 6 async 文件迁 (Sub1 推延)

---

## 变更记录

- 2026-04-18 Session 5 末 v1.0 落盘 (planning gap closure, sprint_state L98 发现 MVP 2.1c 缺设计稿).
  覆盖 4 commits: 0a68618 (Sub1) + e8249361 (Sub2) + cf86447 (Sub3-prep) + a2f3629/edfae2f/b825cc2 (dual-write 自动化).
  Sub3 main 等 2026-04-25 dual-write 窗口验收后 Session 6+ 实施.
- 2026-04-18 Session 6 中段 v1.1 update (backfill 诊断 + tolerance fix + 窗口压缩成功):
  - **Backfill 过去 19 交易日 (2026-03-20 ~ 04-16)** 诊断发现 Sub3-prep 暴露 3 类 drift:
    (1) volume 精度 (Tushare `vol` float, 老 fetcher int cast, dual_write_check 脚本层没模拟)
    (2) up/down_limit 304 行 BJ 股 `only_old_nan` (新路径补老 DB 历史缺失, **feature 非 bug**)
    (3) codes_only_in_new ≤ 9 行 (FK 过滤噪音, MVP 2.1b L173 L设计意图)
  - **根因**: `scripts/dual_write_check.py` 判定太严, 不符合 MVP 2.1b 设计的 noise tolerance 设定
  - **修复**: per-col tolerance (价格 1e-6 / volume 100 股 / amount 10 元) + historical_gap_filled 接受 + codes_only_in_new ≤ 50 接受 + 非交易日 SKIP
  - **验证**: 19/19 交易日 PASS + 0 FAIL + 9 SKIP 非交易日 + 11/11 unit test PASS
  - **硬门 #1 达成**: 19 > 5 要求, 证据更强 (含除权除息 / 月末 / 清明假期前后多场景)
  - **Sub3 main precondition 满足**: 下周一 2026-04-20 可启动 (不需等 Celery Beat 04-25)
  - 本次修复 commits + PR: 详 LL-056 + 本 MVP 对应 feature branch PR

- 2026-04-18 Session 6 末 v1.2 update (Sub3 main 真实范围实测修正 — 防 LL-055 同源凭印象):
  - **Session 6 末 grep 实测发现** Sub3 main 原计划 "Sub3.1 daily_pipeline.py 改 import + 调 TushareDataSource" **基于错误假设**:
    - `daily_pipeline.py` 全文 0 matches for `fetch_base_data` / `BaseDataFetcher` / `fetch_minute_bars` (实测 grep)
    - daily_pipeline 的 6 task (health_check / pms_check / signal / execute / data_quality / factor_lifecycle) 全不 import 老 fetcher
  - **真实生产数据流揭晓** (SYSTEM_RUNBOOK + DEV_BACKEND + SCHEDULING_LAYOUT 三处对齐):
    - **每日 16:15 Windows Task** → `pt_data_service.fetch_daily_data()` 并行 klines/basic/index 拉取走 DataPipeline ✅ **已合规, 不动**
    - **每日 16:35 Windows Task QuantMind_DailyMoneyflow** → `scripts/pull_moneyflow.py` (独立, **不在 Sub3 main 范围**)
    - 老 `fetch_base_data.py` 是**一次性历史 bootstrap** (docstring L12 "cd backend && python -m app.data_fetcher.fetch_base_data"), **0 生产引用**
    - `scripts/fetch_minute_bars.py` 是**手动周/月跑** (实测 minute_bars 最新 04-13, 落后 3 天), 不日更
    - `scripts/qmt_data_service.py` Servy 常驻, xtdata 调用点 L173-175
  - **修正后 Sub3 main 5 sub-step**:
    1. **Sub3.1**: ~~daily_pipeline.py 改 import~~ → **删除此步** (无 import 关系)
    2. **Sub3.2**: `rm backend/app/data_fetcher/fetch_base_data.py` (598 行, 安全, 无生产引用)
    3. **Sub3.3**: `rm scripts/fetch_minute_bars.py` (280 行) + **文档化** BaostockDataSource SDK 替代命令 (用户后续手动用 SDK 拉 minute_bars, 保守不新建 schedule)
    4. **Sub3.4**: `scripts/qmt_data_service.py` 保留壳 (Servy entrypoint), L173-175 改调 `QMTDataSource.fetch` (其他业务逻辑不动)
    5. **Sub3.5**: 退役 dual_write 自动化 (`rm backend/app/tasks/dual_write_tasks.py` + remove `beat_schedule.py` dual_write_check 条目 + RUNBOOK 标历史归档)
    6. **Sub3.6**: 更新 5+ docs 引用 (CLAUDE.md / SYSTEM_STATUS / SYSTEM_RUNBOOK / MVP_2_1b / DUAL_WRITE_RUNBOOK 提到老 3 fetcher 的地方)
  - **完全不动**: `pt_data_service.py` (生产路径已合规) + `scripts/pull_moneyflow.py` (独立 Windows Task)
  - **minute_bars 决策**: 保守不新建每日 schedule. 现有手动周/月模式延续, 用 BaostockDataSource SDK 替代脚本. 未来 Wave 3 PEAD 等需要 minute 数据时再决定 daily schedule (避免提前优化, YAGNI)
  - **教训 (LL-055 同源)**: handoff 实施清单写之前必 grep 验证 import 关系, 不凭印象抄.

- 2026-04-18 Session 6 末 v1.3 update (Task Scheduler 实测全列表 — head 截断教训 LL-057):
  - **首轮 grep 8 个 Task 是 head -25 截断结果**, 实测全部 **18 个 Task** 注册:
    - QM-* prefix 7 个 (DailyBackup/HealthCheck/ICMonitor/LogRotate/PTDailySummary/RollingWF/SmokeTest-Disabled)
    - QuantMind_* prefix 11 个 (DailySignal/DailyExecute/DailyExecuteAfterData/DailyMoneyflow/DataQualityCheck/DailyReconciliation/FactorHealthDaily/IntradayMonitor/PT_Watchdog/MiniQMT_AutoStart-Running/CancelStaleOrders-Disabled)
    - 唯一缺: QuantMind_GPPipeline (设计但未注册)
  - **修正 v1.2 错误断言**: ~~"setup_task_scheduler 设计 13 / 实际 8 / 9 missing"~~ → 实际 12/13 都在, 仅缺 GPPipeline
  - **真实 PT 自动化生产链路** (实测 18 Task + Get-ScheduledTaskInfo LastRun):
    * 16:30 QuantMind_DailySignal → `run_paper_trading.py signal` (内部 Step 1 调 pt_data_service.fetch_daily_data 走 DataPipeline ✅)
    * 16:35 QuantMind_DailyMoneyflow → `pull_moneyflow.py`
    * 16:40 QuantMind_DataQualityCheck
    * 17:05 QuantMind_DailyExecuteAfterData → SimBroker 模式
    * 17:30 QuantMind_FactorHealthDaily
    * 17:35 QM-PTDailySummary
    * 20:00 QuantMind_PT_Watchdog (实测 04-18 20:00:01 Result=1, 你钉钉告警源头)
    * 09:31 QuantMind_DailyExecute (T+1 QMT 模式)
  - **`pt_data_service.py` 实测 337 行** (CLAUDE.md L83 "104 行"是过期数字, 同步修)
  - **Sub3 main 决策不变**: 老 fetcher 全孤立 (0 import + 0 Task 触发) → 删 = 0 影响
  - **新发现 (Session 7 待办, 与 Sub3 main 解耦)**: 04-17 周五 signal Task LastRunResult=0 但 signals 表 0 records (仅 04-14/15/16 各 20 行) — silent failure. app.log 04-17 16:30:21~25 显示 5 个进程同时启动 + 反复 "日志系统已配置" + QMT 连接失败. 怀疑 acquire_lock 抢锁失败 silent skip. 不阻塞 Sub3 main, Session 7 调查 scheduler_task_log + acquire_lock 实现.
  - **教训 (LL-057)**: head/tail truncate 隐藏关键 evidence, 多步实测必查全输出. 与 LL-055 (handoff 凭印象) 同源.
