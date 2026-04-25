# MVP 2.1b · Data Framework — 3 Concrete Fetcher 上线 (Tushare / Baostock / QMT)

> **Wave**: 2 第 2 步 (MVP 2.1 拆分 2/3, 生产 fetcher 合约化)
> **耗时**: 5-7 天 (Tushare 重构 3 天 + Baostock 包装 1.5 天 + QMT 包装 1.5 天 + smoke + commit 1 天)
> **风险**: 中 (Tushare 是生产 PT 路径, 老代码 dual-write 期保护)
> **前置 MVP 2.1a ✅**: BaseDataSource 抽 Template method + ContractViolation + validation helpers 可用
> **铁律**: 10b / 17 / 22 / 24 / 30 / 31 / 33 / 36 / 37 / 38 / 40

---

## 目标 (最小切片 3 项)

1. **`TushareDataSource(BaseDataSource)`** — `backend/app/data_fetcher/fetch_base_data.py` 598 行重构为 Platform DataSource (生产 PT 路径, dual-write 期保老代码)
2. **`BaostockDataSource(BaseDataSource)`** — `scripts/fetch_minute_bars.py` 280 行包装 (minute_bars 190M 行路径)
3. **`QMTDataSource(BaseDataSource)`** — `scripts/qmt_data_service.py` 274 行包装 (Redis→QMT 实时链路)

## 非目标 (明确留后续 sub-MVP)

- ❌ DAL 完整版扩展 (read 路径新方法) — 留 MVP 2.1c
- ❌ 16 处直连 SQL 迁移 (engines / services / api / repositories / tasks) — 留 MVP 2.1c (工程量主体)
- ❌ `backend/data/factor_cache.py` 实现 `FactorCacheProtocol` — 留 MVP 2.1c
- ❌ 老 `fetch_base_data.py` / `fetch_minute_bars.py` / `qmt_data_service.py` 删除 — dual-write 期保底到 MVP 2.1c 结束
- ❌ Data Lineage / pgvector / Redis pub-sub — 留 MVP 2.2 / Wave 3

---

## 实施结构

```
backend/platform/data/
├── interface.py                ⚠️ MVP 1.1 锁定, 不动
├── base_source.py              ⚠️ MVP 2.1a, 不动 (消费方)
├── cache_coherency.py          ⚠️ MVP 2.1a, 不动
├── sources/                    ⭐ NEW 目录
│   ├── __init__.py             ⭐ 统一导出 3 concrete
│   ├── tushare_source.py       ⭐ NEW ~300 行 TushareDataSource (重构 fetch_base_data 核心)
│   ├── baostock_source.py      ⭐ NEW ~180 行 BaostockDataSource (包装 fetch_minute_bars 核心)
│   └── qmt_source.py           ⭐ NEW ~180 行 QMTDataSource (包装 qmt_data_service 核心)
└── ...

backend/tests/
├── test_tushare_source.py      ⭐ NEW ~12 tests (mock ts API + validate + ContractViolation)
├── test_baostock_source.py     ⭐ NEW ~8 tests (mock baostock + PK + NaN + 单位)
└── test_qmt_source.py          ⭐ NEW ~8 tests (mock xtquant + validate + Redis stub)

backend/tests/smoke/            ⭐ 铁律 10b 硬门 3 个 retrospective live smoke
├── test_mvp_2_1b_tushare_live.py    ⭐ NEW (live Tushare API, needs TUSHARE_TOKEN, 可 skip CI)
├── test_mvp_2_1b_baostock_live.py   ⭐ NEW (live Baostock, 无 token 需网络)
└── test_mvp_2_1b_qmt_live.py        ⭐ NEW (live xtquant path + Redis)

scripts/                        ⚠️ 老脚本 dual-write 期保留, 不删
├── fetch_minute_bars.py        (MVP 2.1c 后删)
└── qmt_data_service.py         (MVP 2.1c 后删, QMTData Servy 服务配置同步迁)
backend/app/data_fetcher/
└── fetch_base_data.py          (MVP 2.1c 后删, Celery daily_pipeline 同步迁)

docs/mvp/
└── MVP_2_1b_concrete_fetchers.md   ⭐ 本文
```

**规模**: ~660 Platform 代码 + ~400 测试 + 3 smoke ≈ 1100 行. 生产老代码 **0 改动** (dual-write).

---

## 关键设计

### D1. Tushare 重构 (生产路径, dual-write)

`fetch_base_data.py::BaseDataFetcher` 598 行内部有: 多 endpoint 并发 (klines_daily / daily_basic / moneyflow) + 单位归一 (万元→元) + board 识别 (bse/sh/sz) + 涨跌停计算 + FK 过滤.

**拆分**:
- **纯 fetch**: `TushareDataSource._fetch_raw(contract, since)` 只返 DataFrame (列名与 contract.schema 对齐, 单位归一完成)
- **validate**: 用 BaseDataSource 公共 helpers, override `_check_value_ranges` 加 close > 0 / volume ≥ 0
- **入库**: **不做** — `TushareDataSource.fetch()` 只返干净 DataFrame, 调用方 (Celery task) 交给 `DataPipeline.ingest` 入库 (铁律 17 / 铁律 31)
- **老 `BaseDataFetcher` 保留**: 作 dual-write 期回退, MVP 2.1c 结束再删

**契约选择**: Tushare 同时供 klines_daily / daily_basic / moneyflow 3 个 Contract, `TushareDataSource` 用 `contract.name` dispatch 到对应 `_fetch_klines_daily` / `_fetch_daily_basic` / `_fetch_moneyflow` 内部方法.

### D2. Baostock 包装 (minute_bars 路径)

`fetch_minute_bars.py::fetch_stock` 280 行做 bs→db code 转换 + incremental 拉取 + Pipeline ingest.

**策略**: 不重构逻辑, 只把 `_query_baostock` 核心包装成 `BaostockDataSource._fetch_raw`. `fetch_stock` 函数保留作 CLI 入口, 内部改调 `BaostockDataSource.fetch` (dual-write 过渡).

**契约**: 只服务 `minute_bars` Contract. DataContract.unit 标注 "price=元, volume=股" (Baostock 原生).

### D3. QMT 包装 (实时 Redis 路径)

`qmt_data_service.py::QMTDataService` 274 行常驻 daemon, 每 60s sync QMT → Redis. **特殊**: 不走 DataPipeline.ingest (目标是 Redis 不是 PG), 但仍遵守 DataSource 契约 validation.

**策略**: `QMTDataSource._fetch_raw` 包装 `xtdata.get_*` 调用, `validate` 检查 schema. 入 Redis 的逻辑保留在 `QMTDataService` daemon (不动 Servy 服务配置).

**契约**: 服务 `qmt_positions` / `qmt_assets` / `qmt_ticks` 3 个 Contract (MVP 2.1c 时加入 contract registry).

### D4. Smoke 与铁律 10b 执行

3 个 live smoke (subprocess + 网络/QMT path) 按 `backend/tests/smoke/test_mvp_1_3b_layer1_live.py` 同 pattern:
- `test_mvp_2_1b_tushare_live.py`: 查 1 日 klines_daily (需 TUSHARE_TOKEN env, 无则 `pytest.skip`)
- `test_mvp_2_1b_baostock_live.py`: 查 1 支股 5min bars (无 token, 需网络)
- `test_mvp_2_1b_qmt_live.py`: `QMTClient` 读 `portfolio:current` Redis key (依赖 QMTData 服务 running)

CI 无网络时 baostock/tushare smoke 走 mark skip. QMT smoke 只在 Servy QMTData 状态下跑.

### D5. Dual-write 退出条件 (MVP 2.1c 前置)

- 新 `TushareDataSource.fetch + DataPipeline.ingest` 跑满 5 个交易日无 drift vs 老 `BaseDataFetcher.run`
- `regression_test --years 5` max_diff=0 连续 3 次
- 新老路径数据 diff `SELECT * FROM klines_daily WHERE trade_date >= ...` 100% 对齐

满足后 MVP 2.1c 删老代码.

---

## 验收标准

| # | 项 | 目标 |
|---|---|---|
| 1 | `backend/platform/data/sources/*.py` (3 concrete, ~660 行) | ✅ 存在 |
| 2 | 3 unit test 文件 (~28 tests total) | ✅ PASS |
| 3 | 3 live smoke 文件 | ✅ PASS (或 skip 环境缺) |
| 4 | MVP 1.1-2.1a 锚点 (365 tests + 20 smoke) | ✅ 不回归 |
| 5 | `regression_test --years 5` | ✅ max_diff=0.0 |
| 6 | ruff clean 全部新代码 | ✅ |
| 7 | 全量 pytest fail | ≤ 24 (铁律 40 baseline 不增) |
| 8 | 老 `fetch_base_data.py` / `fetch_minute_bars.py` / `qmt_data_service.py` git diff | **0 改动** (dual-write) |
| 9 | Celery daily_pipeline / Servy QMTData 生产链路 | ✅ Running, 无 drift |
| 10 | ADR-006 (MVP 2.1a 入库) 被本 MVP 实施印证 | ✅ 不需 supersede |

---

## 开工协议 (铁律 36 precondition)

- ✅ MVP 2.1a `BaseDataSource` Template method + `ContractViolation` 可用
- ✅ MVP 1.1 `DataContract` 9 张表 schema 已定义 (`backend/app/data_fetcher/contracts.py`)
- ✅ MVP 1.1 `DataPipeline.ingest` 生产 work (铁律 17)
- ✅ 3 老 fetcher 生产中 (BaseDataFetcher / fetch_minute_bars / QMTDataService)
- ✅ Platform stdlib shadow 根治 (MVP 1.1b), 本 MVP 可 safely `import backend.qm_platform.data.sources.*`
- ✅ 铁律 10b pre-push hook 启用, 新 smoke 自动守门 (配 `git config core.hooksPath config/hooks`)

---

## 禁做 (铁律)

- ❌ 不动 `backend/app/data_fetcher/contracts.py` (MVP 1.1 锁, 新 Contract 留 3.0a)
- ❌ 不动 `backend/platform/data/interface.py` (MVP 1.1 锁 ABC 签名)
- ❌ 不动 `backend/platform/data/base_source.py` (MVP 2.1a 锁 Template method)
- ❌ 不扩 DAL 方法 (MVP 2.1c)
- ❌ 不迁直连 SQL (MVP 2.1c)
- ❌ 不删老 3 fetcher (dual-write 期到 MVP 2.1c 结束)
- ❌ 不动 Servy QMTData 服务配置 (保 production running)

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | Tushare 重构破坏生产 PT (最大风险) | 中 | dual-write + regression max_diff=0 连续 3 次门槛, 失败回滚 commit 即可 |
| R2 | `_check_value_ranges` 在 3 fetcher 分别 override 出现规则漂移 | 中 | ADR-006 附录记录每 fetcher 的 override 规则, 代码 review 对齐 |
| R3 | QMT xtquant path shadow 复发 (backend.qm_platform 组名问题) | 低 | MVP 1.1b 已根治 + smoke 守门, xtquant path `ensure_xtquant_path()` 用 append 非 insert |
| R4 | live smoke 在 CI/新机器环境因 token/网络 false negative | 中 | pytest.skip with 明确 env var check, CI 只跑不依赖外部 token 的 smoke |
| R5 | 铁律 40 新增 fail (3 unit test 文件出错) | 低 | TDD: 先写 1 fetcher 跑通再写下一个, 每次 anchor pytest |
| R6 | Contract dispatch logic 在 TushareDataSource 过度复杂 | 中 | D1 明确: contract.name str match, 3 内部 method, 不搞 registry pattern (YAGNI) |

---

## 下一步 (MVP 2.1c 预告)

- Wave 2 MVP 2.1c (5-7 天): DAL 完整版扩展 + `FactorCacheProtocol` 落地 `factor_cache.py` + 16 处直连 SQL 迁移 (engines/services/api/repositories/tasks) + 老 3 fetcher 删除
- MVP 2.2 (1 周): Data Lineage 表 + DataPipeline 自动记录, 追溯每行数据来源
- MVP 2.3 (3-4 周): Backtest Framework + U1 Parity (sim-to-real 对齐)

---

## 变更记录

- 2026-04-18 v1.0 设计稿落盘, 等下 session plan 模式 approval + 实施.
