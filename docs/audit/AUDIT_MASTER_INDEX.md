# QuantMind V2 全面审计索引

> **目的**: 6-Session 全面审计的总索引 + 跨 session 发现计数 + P0 行动看板
> **启动**: 2026-04-15
> **当前 Session**: S4 完成，待 S3 / S5

---

## 📅 Session 进度

| # | 主题 | 状态 | 启动 | 完成 | 报告 |
|---|---|---|---|---|---|
| **S1** | 三角对齐（文档 / 代码 / DB） | ✅ 完成 | 2026-04-15 | 2026-04-15 | [S1_three_way_alignment.md](S1_three_way_alignment.md) |
| **S2** | 一致性专项（PT ↔ 回测 ↔ 研究） | ✅ 静态完成 | 2026-04-15 | 2026-04-15 | [S2_consistency.md](S2_consistency.md) |
| **S2b** | factor_onboarding 彻底重构 (async→sync + DataPipeline + ic_calculator) | ✅ 完成 | 2026-04-15 | 2026-04-15 | (本 session) |
| **S3** | 韧性与抗断（静默失败 / 错误恢复 / 监控） | ✅ 静态完成 | 2026-04-15 | 2026-04-15 | [S3_resilience.md](S3_resilience.md) |
| **S4** | 动态基线验证（regression / pytest / diagnosis） | ✅ 完成 | 2026-04-15 | 2026-04-15 | [S4_baseline.md](S4_baseline.md) |
| **铁律扩展** | 30→35 条铁律 (新增工程基础设施类 31-35, 扩展 8/22) | ✅ 完成 | 2026-04-15 | 2026-04-15 | CLAUDE.md §铁律 |
| **Phase B M1** | F86 pre-commit hook 全闭环 (铁律 17 代码级护栏) | ✅ 完成 | 2026-04-15 | 2026-04-15 | commit `0608879` |
| **Phase B M2** | F75 全闭环 + regression_test --years 12 + 12yr aggregated parquets | ✅ 完成 | 2026-04-15 | 2026-04-15 | commit `7f54613` |
| **Phase B M3** | F45 全闭环 (`check_config_alignment` + ConfigDriftError, 铁律 34 第一次实战落地) | ✅ 完成 | 2026-04-15 | 2026-04-15 | (本 session) |
| **Phase C C0** | F31 金标快照冻结 — 8 因子 × 12yr factor_values → cache/phase_c_baseline/ | ✅ 完成 | 2026-04-16 | 2026-04-16 | (本 session) |
| **Phase C C1** | F31 拆分 milestone 1 — calculators + preprocess + alpha158 + _constants 移出 package | ✅ 完成 | 2026-04-16 | 2026-04-16 | (本 session) |
| **Phase C C2** | F31 拆分 milestone 2 — load_* → factor_repository + PEAD 纯化 | ✅ 完成 | 2026-04-16 | 2026-04-16 | (本 session) |
| Phase C C3 | F31 拆分 milestone 3 — compute_service + F86 factor_engine known_debt 闭环 | ⬜ 待开始 | — | — | — |
| S5 | 边界 + 血缘（时区 / QMT / 并发 / 生命周期） | ⬜ 待开始 | — | — | — |
| S6 | 方法论固化（不变量 / 契约 / 差分 / 金标） | ⬜ 待开始 | — | — | — |

---

## 📊 累计发现计数

| 分级 | S1 | S2 新增 | S4 新增 | S3 新增 | 总计 | 已处理 | 未处理 |
|---|---|---|---|---|---|---|---|
| 🔴 P0 | 6 | 3 (F51/F60/F62) | 1 (F72) | 2 (F76/F77) | **12** | **12** (+F45 Phase B M3 关闭) | **0** |
| 🟠 P1 | 10 | 8 (F50/F52/F54/F55/F57/F58/F63/F65) | 3 (F66/F71/F74) | 4 (F78/F82/F85/F86) | **25** | **13** (+F86 factor_onboarding 根治) | **12** |
| 🟡 P2 | 6 | 2 (F56/F64) | 6 (F67/F68/F69/F70/F73/F75) | 3 (F79/F80/F81) | **17** | **5** (+F79/F81) | **12** |
| ✅ 关闭/修正 | — | F17 部分关闭 + F64 PASS | F66/F72/F73 闭环 | F76/F77/F78/F79/F81/F82/F86 short-term 闭环 | — | — | — |
| **S2b 根治** | — | — | — | — | — | **F17/F51/F53/F60/F86 (factor_onboarding 部分) — 5 条** | — |
| **Phase B M1-M3** | — | — | — | — | — | **F86 (hook) + F75 (12yr) + F45 (config_guard) — 3 条** | — |
| **合计** | **22** | **13** | **10** | **9** | **54** | **30** | **24** |

> S1 静态广扫 + S1 cleanup pass + S2 一致性专项（静态 + 4 快修）+ S4 动态基线验证 + S3 韧性静态审计 + **S2b factor_onboarding 彻底重构** + **Phase B M1-M3 (F86/F75/F45)** 已完成。counter 维度的 "P0 未处理" 从 1→0 (F45 关闭). 看板维度的 F16 (Service .commit 20+ 处) / F31 (factor_engine 2034 行巨石) / F63 (前端 API 契约缺口) 仍 ⬜, 均为规模化重构类工程债, 非短期根治范畴, 建议 Phase C 统一处理.

**S2b 根治 (2026-04-15 夜, 继 S3 tail fix / 铁律扩展 / commit dfcb473 之后)**:
- ✅ **F17 (P0)**: factor_onboarding 2 条生产 INSERT → DataPipeline.ingest + FACTOR_VALUES/FACTOR_IC_HISTORY contracts (新增 FACTOR_IC_HISTORY Contract, DB schema 100% 对齐验证)
- ✅ **F51 (P0)**: factor_onboarding `_compute_ic_series` DEPRECATED 函数**彻底删除**, 新 `_compute_ic_multi_horizon` 直接调 `ic_calculator.compute_ic_series` (铁律 19 真正落地, 不再是 warning)
- ✅ **F53 (P0)**: factor_onboarding IC 写入已走统一口径 (T+1 / CSI300 超额 / Spearman), 不再有"双口径 IC 写入 factor_ic_history"风险
- ✅ **F60 (P0)**: `_compute_forward_returns` raw return 函数**彻底删除**, 前瞻收益改用 `ic_calculator.compute_forward_excess_returns` (含 T+1 入场 + CSI300 超额)
- ✅ **F86 (P1) factor_onboarding 部分**: `check_insert_bypass.py` 扫描结果 5 → 3 (factor_onboarding 2 条违规消失, 剩余 fetch_base_data ×2 + factor_engine ×1 转长期重构)
- ✅ **F86 (P1) 全闭环 Phase B M1 (2026-04-15 夜)**: `check_insert_bypass.py --baseline` + `scripts/audit/insert_bypass_baseline.json` (3 条已知债务冻结) + `scripts/git_hooks/pre-commit` 安装到 `.git/hooks/pre-commit` + `scripts/install_git_hooks.sh` 入库安装器。**实测拦截**: 故意加一个 `INSERT INTO factor_values` 到 `_test_hook_fake.py`, `git commit` 被拒 (exit 1), 错误消息含铁律 17 来源 + 修复方案 + `--no-verify` 紧急绕过。F86 从 "短期闭环" 升级为 "代码级强制护栏"
- ✅ **F18 部分 (async 遗留)**: factor_onboarding / onboarding_tasks / test_factor_onboarding 全转 sync psycopg2, 剩余 mining/backtest_service 独立处理

**S2b 规模**:
- 重写 `services/factor_onboarding.py`: 868 → 661 lines, **0 async / 14 sync methods**, 删除 `_safe_float` / `_compute_forward_returns` / 旧 `_compute_ic_series`
- 更新 `tasks/onboarding_tasks.py`: 140 → 129 lines, 去掉 asyncio.run 包装层
- 新增 `data_fetcher/contracts.py::FACTOR_IC_HISTORY` Contract (+30 行, pk+11 列, DB schema 实测对齐)
- 重写 `tests/test_factor_onboarding.py`: 801 → 877 lines, **28/28 PASS in 1.60s**, 0 AsyncMock / 0 pytest.mark.asyncio
- 新增 `TestUpsertDelegatesToPipeline` 测试类 (4 tests) — S2b 独有护栏

**S2b 验证结果**:
- ✅ **pytest test_factor_onboarding**: **28/28 PASS** (首次运行零失败)
- ✅ **check_insert_bypass**: factor_onboarding 0 违规 (从 2 条 → 0)
- ✅ **regression_test 5yr**: `max_diff=0.0`, Sharpe 0.6095=0.6095 (铁律 15 PASS, 重构未污染回测引擎)
- ✅ **system_diagnosis**: 38 PASS / 6 WARN / 0 FAIL, 所有 WARN 都是预存在问题 (F67/F68/F71 等, 非 S2b 引入)
- ✅ **factor_health_check CORE 4**: 4/4 HEALTHY, 0 warning / 0 error, 11.71M 行/因子, neutral_value 99.2% 有效 (铁律 29 CORE PASS, 重构未污染已入库数据)

**S3 韧性静态审计关键发现** (2026-04-15 夜):
- 🔴 **F76 (P0)**: `qmt_execution_adapter.py:85-94 _get_realtime_tick` xtdata 异常 silent swallow → `_check_buy_protection` 可能 silently bypass 涨停保护 → 实盘风险
- 🔴 **F77 (P0)**: `qmt_execution_adapter.py:669-680` 撤单确认 query_orders 异常 silent pass → "查询失败" 被归类成 "撤单超时", 监控无法区分
- 🟠 **F78 (P1)**: `daily_pipeline.py:91-92` health_check stream publish silent (无 logger.warning)
- 🟠 **F82 (P1)**: Celery 配置漂移 — `celery_app.py:47 worker_concurrency=4` (Mac prefork 遗留) vs Windows `--pool=solo --concurrency=1` 实际运行
- 🟠 **F85 (P1)**: Rollback 覆盖率 15% — 20+ commit 只有 3 个 service 有 rollback, 异常时 partial state 悬挂
- 🟠 **F86 (P1)**: **F66 防复发缺失** — 4 条生产 INSERT 路径绕过 DataPipeline (factor_onboarding:544/756 + fetch_base_data:327/412), 铁律 17 仅文档级, 无代码强制
- 🟡 F79/F80/F81 (P2): pms/realtime/factors 三处 API silent fallback

**S3 积极发现** (反面证据, 作为良好基线):
- ✅ 熔断 L1-L4 实际落地 — `execution_service.py:92-115` 对 cb_level ∈ {2,3,4} 有真实分支, 非文档玩具
- ✅ execution_service StreamBus publish 有正确的 try/except + logger.warning(exc_info=True) — 可作全项目 publish 模板
- ✅ DataPipeline 本身合规 — `pipeline.py` 做完整的 rename→列对齐→单位转换→值域验证→FK→Upsert→fillna(None)

**S3 未做的动态部分** (建议转 S3b/S5 故障注入):
- Redis 断线时 PT 链路实际行为, PG 连接池耗尽, Celery worker kill -9 + beat 重启

**S3 tail fixes — 7 条 finding 单 session 闭环** (2026-04-15):
- ✅ **F76 (P0)**: `_get_realtime_tick` 加 logger.error + `_check_buy_protection` 改 fail-safe (无 tick→拒单). 验证: test_qmt_execution_adapter 14/14 PASS (was 11/3), test 加 autouse fixture 注入健康 tick mock
- ✅ **F77 (P0)**: 撤单确认 `query_orders` 异常加 logger.error 区分 "查询失败" vs "真实超时"
- ✅ **F78 (P1)**: daily_pipeline health_check stream publish 加 logger.warning(exc_info=True)
- ✅ **F82 (P1)**: celery_app.py worker_concurrency=4→1 + docstring 顶部加 Windows 生产 `--pool=solo` 警告
- ✅ **F86 (P1) short-term**: 新建 `scripts/audit/check_insert_bypass.py` 铁律 17 lint 脚本 (实测扫出 5 处生产违规 + 12 处研究软豁免). **中期重构 4 条生产路径转 S2b** (fetch_base_data ×2 + factor_onboarding ×2)
- ✅ **F79 (P2)**: pms.py stream publish 加 logger.warning
- ✅ **F81 (P2)**: factors.py API 2 处 silent fallback 加 logger.warning

S3b 未做但已识别: F80 (realtime_data_service nav=0 fallback, 需前端协议) / F85 (rollback 覆盖率 15%, 规模化重构). 转 S5 或长期重构队列。

**S4 基线验证关键结果** (2026-04-15 夜):
- ✅ **regression_test 5yr PASS**: max_diff=0.0, Sharpe 0.6095=0.6095, MDD -50.75%=-50.75%, 1212 days (铁律 15 验证, F66 前后两次独立复测完全一致)
- ⚠️ regression 12yr 不支持: 脚本仅 5yr 入口, 12yr 仅静态 metrics_12yr.json (F75)
- ✅ **factor_health 4 因子全 HEALTHY**: CORE3+dv_ttm 各 11.71M 行, neutral_value 99.2% 有效, 0 float NaN (铁律 29 CORE PASS)
- ✅ **system_diagnosis 37 PASS / 7 WARN / 0 FAIL** → S4 tail fix 后 Layer 1 复测 **17/17 PASS / 0 WARN** (F66 关闭后)
- ⚠️ **pytest 2057 pass / 32 fail / 9 error** → S4 tail fix 后 **2066 pass / 32 fail / 0 error** (F72 关闭后), 98.4% pass 率, 无 CORE 路径回归

**S4 tail fixes — 3 条 finding 单 session 闭环**:
- ✅ **F72 (P0)**: test_opening_gap_check import 从 `run_paper_trading._check_opening_gap` → `pt_monitor_service.check_opening_gap` → 9/9 pass in 0.05s
- ✅ **F66 (P1)**: 扩展扫描发现 12 个非 CORE 因子 1665 行 + 初始 28 行 = **1693 行 float NaN**, 一次 UPDATE → NULL, system_diag Layer 1 WARN→PASS, regression 5yr 复测 max_diff=0.0
- ✅ **F73 (P2)**: CLAUDE.md line 561 "2115 tests" → "2100 tests collected / 2066 pass / 32 fail / pass 率 98.4%"

**S4 未处理转 S3/S5/S6** (7 条):
- 🟠 **F71 (P1)**: 因子列表硬编码在 parquet_cache + health_check (对应 S1 F45 config drift) → S5
- 🟠 **F74 (P1)**: 11 个"未知"pytest 失败需逐一排查 (总 2-3 小时) → S5
- 🟡 F67/F68/F69/F70: Redis/Stream/execution 血缘 → S3 韧性 session
- 🟡 F75: regression_test 12yr 入口 → **Phase B M2 (2026-04-15) 已关闭** (见下)

**Phase B M2 F75 full closure (2026-04-15 夜)**:
- ✅ **F75 (P2) full closure**: `scripts/regression_test.py --years {5,12}` + `scripts/build_12yr_baseline.py` 扩展保存 aggregated parquets (factor_data_12yr / price_data_12yr / benchmark_12yr)
- ✅ **铁律 15 12yr 验证**: regression_test --years 12 --twice → Run1 vs baseline max_diff=0, Run1 vs Run2 max_diff=0, Deterministic YES ✅ (19s/run)
- ⚠️ **附带发现 (铁律 28 报告)**: 新 12yr baseline Sharpe=**0.3594** (vs Step 6-D 2026-04-09 记录的 0.5309, -32%). 根因: `cache/backtest/YEAR/*.parquet` 于 2026-04-15 15:20 被 `build_backtest_cache.py` 重建 (今天下午, 不在当前 session), Step 6-D 时代的 cache 快照被覆盖不可复现. 5yr baseline 因有独立冻结的 `factor_data_5yr.parquet` (278MB, Apr 9 11:33) 不受影响 max_diff=0. M2 恰好补上 12yr aggregated 冻结缺口 — 今后 cache 再变, 12yr regression 依然稳定.
- ✅ **铁律 22 数字同步**: CLAUDE.md 12yr 基线段更新 (Sharpe 0.5309→0.3594, MDD -56.37%→-63.44%, Annual 13.06%→6.28%, NAV 4.48M→2.11M), 附漂移 rationale.

**Phase B M3 F45 full closure — 铁律 34 第一次实战落地 (2026-04-15 夜)**:
- ✅ **F45 (P0) full closure**: `backend/engines/config_guard.py` 新增 `ConfigDriftError` + `check_config_alignment()` — 校验 6 个参数三源对齐:
  - 三源 (`.env` / `pt_live.yaml` / `PAPER_TRADING_CONFIG`): `top_n` / `industry_cap` / `size_neutral_beta`
  - 双源 (`pt_live.yaml` / `PAPER_TRADING_CONFIG`): `turnover_cap` / `rebalance_freq` / `factor_list` (set 比较, 顺序无关)
  - 浮点容差 1e-9 (避免 0.50 vs 0.5 假漂移)
  - 任何漂移 → RAISE `ConfigDriftError` (不允许 warning, 铁律 34)
  - 错误消息含全部漂移项 + 三源当前值 + 修复指引 (哪处应该改)
- ✅ **PT 启动集成**: `scripts/run_paper_trading.py` Step 0.5 扩展 — 先 `check_config_alignment()` 硬校验, 失败写 `scheduler_task_log` + `sys.exit(1)`, 再跑 legacy `assert_baseline_config()` (兼容性双层)
- ✅ **health_check 集成**: `scripts/health_check.py` 新增 `check_config_drift()` 函数 + 注册到 checks 列表 (`config_drift_ok`), 日常体检也跑这一项
- ✅ **单元测试**: `backend/tests/test_config_guard.py` 新增 `TestCheckConfigAlignment` (14 个用例):
  - happy path / 每个参数单独漂移 (top_n/industry_cap/sn_beta/turnover_cap/rebalance_freq) / factor_list 多出或缺少 / 多项漂移同时触发 / yaml 文件缺失 / yaml 损坏 / 浮点容差 / 真实三源对齐
  - 使用 dataclass fakes 注入 (`_FakeSettings` / `_FakePythonConfig`) + `tmp_path` 临时 yaml, 0 monkeypatch, 不污染 test env
  - **24/24 PASS** (10 existing + 14 new, 0.10s)
- ✅ **5 把尺子全绿 (验收标准)**:
  1. `pytest test_config_guard` → **24/24 PASS** (0.10s)
  2. `pytest test_factor_onboarding` → **28/28 PASS** (1.60s, S2b 不回归)
  3. `regression_test --years 5` → **max_diff=0.0**, Sharpe 0.6095=0.6095 (铁律 15 PASS, 不污染回测)
  4. `check_insert_bypass --baseline` → **3 known_debt 不变** (pre-commit hook 通过)
  5. 故意 drift 验证 → **RAISE** 双路径: `PT_TOP_N=13 python -c check_config_alignment()` 抛 `ConfigDriftError: 1 项漂移 - top_n: .env=13; pt_live.yaml=20; python=20`, `health_check check_config_drift()` 同步返回 `ok=False` + 单行 msg 含 `industry_cap: .env=0.25; pt_live.yaml=1.0; python=0.25` (fail-loud 双重验证)
- ✅ **防复发**: F45 (config_guard 缺检查) / F62 (SN default 0.0 静默降级) / F40 (SignalConfig 默认漂移) 三条历史漂移源同时落护栏. 测试 `test_size_neutral_beta_yaml_drift_raises` 专门针对 F62 场景.
- ✅ **铁律 34 状态**: CLAUDE.md §铁律 34 追加 "已落地 (2026-04-15 Phase B M3)" 注脚 — 铁律 34 从"纸面硬约束"升级为"代码级 fail-loud 护栏", F45 关闭.
- ⏸ **未做 (建议 Phase C)**: F16 (Service 层 .commit 20+ 处) / F31 (factor_engine 2034 行 Engine 读写 DB) / F63 (前端 API 契约缺口) — 均为规模化重构, 单 session 不能根治.

**Phase C C0 + C1 — factor_engine.py 拆分首跑 (2026-04-16)**:
- ✅ **C0 (金标冻结)**: 新建 `scripts/audit/phase_c_freeze_baseline.py`, 冻结 8 因子 (CORE 4: turnover_mean_20/volatility_20/bp_ratio/dv_ttm + PASS 4: amihud_20/reversal_20/maxret_20/ln_market_cap) × [2014-01-01, 2026-04-14] factor_values 快照到 `cache/phase_c_baseline/*.parquet`, 生成 `freeze_manifest.json` (含 sha256 + git HEAD). 每因子 11.72M rows (maxret_20 10.38M), 总计 91.5M rows. 作为 C1/C2/C3 max_diff=0 验证的金标基准.
- ✅ **C1 (纯计算 + preprocess 搬家)**: `backend/engines/factor_engine.py` (2049 行) → `backend/engines/factor_engine/` package:
  - `_constants.py` (4.1 KB) — direction 字典 / FUNDAMENTAL_*_META / LGBM_V2_BASELINE_FACTORS (pure data, 无函数引用)
  - `calculators.py` (14.4 KB) — 30 个 calc_* 纯函数 (lines 24-431 原文, 仅 import numpy/pandas)
  - `alpha158.py` (5.8 KB) — `_alpha158_rolling` + `calc_high_vol_price_ratio_wide` + `calc_alpha158_simple_four` + `calc_alpha158_rsqr_resi`
  - `preprocess.py` (7.0 KB) — preprocess_mad/fill/neutralize/zscore/pipeline + calc_ic (legacy, 铁律 19 统一走 ic_calculator)
  - `__init__.py` (47.4 KB) — shim re-export 上述符号 + 未迁移 IO (load_*/save_*/compute_*/calc_pead_q1/load_fundamental_pit_data/lambda 因子注册表, C2/C3 处理)
  - 删除原 `factor_engine.py` (Python 不允许 file + package 同名共存)
- ✅ **新建 `scripts/audit/phase_c_verify_split.py`** — `max_diff=0` 验证脚本, 支持 `--sample N` / `--factor <name>` 灵活验证. C1 无法跑 recompute 对比 (compute_batch_factors 跑 12yr 过慢), 但 DB 读路径未动, regression 5yr 已充分证明回测引擎看到的因子值无漂移.
- ✅ **5 把尺子全绿 (验收标准)**:
  1. `pytest test_factor_engine_unit` → **72/72 PASS** (0.12s, 所有纯 calc_* + preprocess 单测通过)
  2. `pytest test_factor_determinism` → **2/2 PASS** (3.5 min, 真 DB 数据两次独立跑, bit-level 一致)
  3. `pytest test_factor_onboarding` → **28/28 PASS** (2.11s, S2b 重构不回归)
  4. `regression_test --years 5` → **max_diff=0.0**, Sharpe 0.6095=0.6095 (铁律 15, 回测引擎 0 污染)
  5. `check_insert_bypass --baseline` → **3 known_debt** 不变, baseline 更新为新路径 `backend/engines/factor_engine/__init__.py:1276`
- ✅ **无回归副作用**: 跨文件运行 `test_a4_a6 + test_pead_factor + test_turnover_stability + test_vwap_rsrs + test_vwap_rsrs_pipeline + test_wls_neutralize_and_clip` → **15 failed / 56 passed**. 同一命令在原 HEAD (stash 后) 跑出**完全相同的 15/56** 分布, 证明失败全为 S4 审计记录的 32 条历史 pre-existing debt, C1 refactor 引入 **0 回归**.
- ✅ **baseline 路径更新**: `scripts/audit/insert_bypass_baseline.json` version 2, 原 `backend/engines/factor_engine.py:2016` entry 替换为 `backend/engines/factor_engine/__init__.py:1276` (compute_batch_factors embedded SQL — C3 改 DataPipeline 后删除, known_debt 3→2).
- ✅ **文档同步 (铁律 22(a))**: CLAUDE.md §目录结构 / 铁律 31 注脚同步更新 (single commit, 无 NO_DOC_IMPACT).
- ✅ **C2 已完成 (同 session, 见下段)**

**Phase C C2 — 数据加载搬家 + PEAD 纯化 (2026-04-16, 同 session 连跑)**:
- ✅ **新建 `backend/app/services/factor_repository.py`** (约 530 行):
  - `load_daily_data` / `load_forward_returns` (原单日数据加载)
  - `load_bulk_data` / `load_bulk_moneyflow` / `load_index_returns` / `load_bulk_data_with_extras` (原区间批量加载)
  - `load_fundamental_pit_data` (PIT 基本面 delta 计算, 跨 package 引用 `engines.factor_engine._constants.FUNDAMENTAL_ALL_FEATURES`)
  - **新增 `load_pead_announcements(conn, trade_date, lookback_days=7)`** — 从 `calc_pead_q1` 拆出的 DB 读取部分
  - 所有 SQL 字符串 100% 原样保留, signature 保留 `conn=None` 自动建连
- ✅ **新建 `backend/engines/factor_engine/pead.py`** (约 55 行):
  - `calc_pead_q1_from_announcements(ann_df: pd.DataFrame) -> pd.Series` — 纯函数, 无 IO
  - 输入已排序的 announcements DataFrame, 输出 factor Series (同股最新一条聚合)
- ✅ **`factor_engine/__init__.py` 瘦身** 1276 → 815 行 (−461 行):
  - 删除 `load_daily_data` / `load_forward_returns` / `load_bulk_data` / `load_bulk_moneyflow` / `load_index_returns` / `load_bulk_data_with_extras` / `load_fundamental_pit_data` / `calc_pead_q1` 8 个函数体
  - 添加 `from app.services.factor_repository import (load_bulk_data, load_bulk_data_with_extras, load_bulk_moneyflow, load_daily_data, load_forward_returns, load_fundamental_pit_data, load_index_returns, load_pead_announcements)` — **25 调用方零改动**
  - 添加 `from engines.factor_engine.pead import calc_pead_q1_from_announcements` (re-export)
  - 保留 `calc_pead_q1(trade_date, conn=None)` wrapper: 内部调 `load_pead_announcements` + `calc_pead_q1_from_announcements` (兼容层)
- ✅ **铁律 19 ic_calculator 警告**: `load_forward_returns` 函数体 docstring 添加 "[Legacy] 铁律 19 要求新路径走 engines/ic_calculator" 提示
- ✅ **5 把尺子全绿 (C2 独立验收)**:
  1. `pytest test_factor_engine_unit` → **72/72 PASS** (0.11s)
  2. `pytest test_factor_determinism` → **2/2 PASS** (97s, 真 DB 双跑 bit-level 一致)
  3. `pytest test_factor_onboarding` → **28/28 PASS** (2.3s)
  4. `regression_test --years 5` → **max_diff=0.0**, Sharpe 0.6095=0.6095 (铁律 15)
  5. `phase_c_verify_split --sample 5` → **8/8 factors max_diff=0.0** (156,304 行对比)
- ✅ **test_pead_factor 独立验证**: **2 failed / 4 passed** — 完全匹配 pre-refactor baseline (`KeyError: '000001'`), 是 S4 审计记录的 pre-existing debt, C2 拆分不影响 PEAD 调用契约
- ✅ **check_insert_bypass --baseline**: **3 known_debt** 不变, 行号漂到 `__init__.py:798` (原 `:1276`), baseline v3 同步更新
- ✅ **跨文件 pytest 回归检查**: test_a4_a6 + test_pead_factor + test_turnover_stability + test_vwap_rsrs + test_vwap_rsrs_pipeline + test_wls_neutralize_and_clip → **15 failed / 56 passed** 完全匹配 C1 基线 → 0 C2 回归
- ✅ **ruff check + format** 全绿 (factor_repository + pead + __init__)
- ✅ **文档同步 (铁律 22(a))**: CLAUDE.md §services 段新增 factor_repository.py + §铁律 31 注脚追加 C2 条目 + 目录结构段新增 pead.py
- ⏳ **下一 session (C3)**: 搬家 `save_daily_factors` / `compute_daily_factors` / `compute_batch_factors` → `backend/app/services/factor_compute_service.py`, 同时 `compute_batch_factors` 内部 `INSERT INTO factor_values` + `conn.commit()` 改走 `DataPipeline.ingest(df, FACTOR_VALUES)` — 这是 F86 剩余最后 1 条 factor_engine known_debt 闭环. 验收: 金标 max_diff=0 + `check_insert_bypass --baseline` 减到 2 条.

**S1 cleanup pass 处理** (2026-04-15 夜):
- ✅ F32 (token leak): 5 源码位置清洗 + 用户 rotate 所有 key (含 ZHIPU revoke)
- ✅ F41 (V12_CONFIG): 已删除 + 加 tombstone 注释
- ✅ F38 (stale comment "基线5因子"): 随 V12_CONFIG 删除一并解决
- ✅ F1 (DEV_FOREX/NOTIFICATIONS 索引补齐)
- ✅ F10 (测试数 2076/90 → 98 test files)
- ✅ F14 (表数 45/17/62 → 47/26/73)
- ✅ F28 (factor_values 590M → 816M)
- ✅ F29 (minute_bars 139M → 191M)
- ✅ F18 注释补充 (async 遗留在 mining/backtest_service)
- ✅ F2 (archive 131 → 126)

**S2 快修 pass 处理** (2026-04-15 夜):
- ✅ F62 (PT_SIZE_NEUTRAL_BETA default 0.0 → 0.50)
- ✅ F15/F65 (硬编码 DB 密码 fallback 改为 placeholder + raise)
- ✅ F40 (SignalConfig default 对齐 PT CORE3+dv_ttm + monthly + SN=0.50)
- ✅ F52 (compute_batch_factors DeprecationWarning + 注释)
- ✅ F51/F60 (factor_onboarding IC 函数 DEPRECATED warning + 注释, 中期重构留给 S2b)
- ✅ F17 部分关闭 (PT 生产路径 save_daily_factors 走 DataPipeline, factor_engine:2001 是 dead code)
- ✅ F64 (成本模型 backtest/pt_live/broker 三处对齐 PASS 验证)

---

## 🚨 P0 开放行动看板（按严重性降序）

| ID | 主题 | 负责人 | 状态 | Source |
|---|---|---|---|---|
| **F32** | API Token 泄漏 | 用户 | ✅ **全线关闭** 2026-04-15 | S1 |
| **F41** | `V12_CONFIG` 含 INVALIDATED 因子 | — | ✅ **2026-04-15 已删除** | S1 |
| **F62** | `PT_SIZE_NEUTRAL_BETA` default=0.0 静默降级 | — | ✅ **2026-04-15 default→0.50** | S2 |
| **F72** | test_opening_gap_check 9 errors (Step 6-A refactor 遗留) | — | ✅ **2026-04-15 机械修复** | S4 |
| **F76** | `_get_realtime_tick` silent swallow → 涨停保护可能 bypass | — | ✅ **2026-04-15 S3b fail-safe, 14/14 test PASS** | S3 |
| **F77** | 撤单确认 silent swallow → "查询失败" 归类成 "超时" | — | ✅ **2026-04-15 S3b logger.error 区分** | S3 |
| **F16** | Service 层 20+ 处 `.commit()` 违反铁律 | — | ⬜ 待修（S3 F85 配对扫出, 铁律 32 已建立硬约束）| S1 |
| **F17** | factor_onboarding 绕过 DataPipeline + 中性化不完整 | — | ✅ **S2b 2026-04-15 根治** (DataPipeline + FACTOR_IC_HISTORY Contract) | S1/S2 |
| **F31** | `factor_engine.py` Engine 层读写 DB（2034 行巨石） | — | ⬜ 长期重构（F43 一起, 铁律 31 已建立硬约束） | S1/S2 |
| **F45** | `config_guard` 不检查 SN/top_n/industry_cap | — | ✅ **Phase B M3 2026-04-15 关闭** (`check_config_alignment()` + `ConfigDriftError`, PT+health_check 双集成, 24 单测, 5 把尺子全绿) | S1 |
| **F51/F53/F60** | factor_onboarding IC 违反铁律 19 + 前瞻偏差 | — | ✅ **S2b 2026-04-15 根治** (删除 DEPRECATED 函数, 改 ic_calculator) | S2 |
| **F63** | 前端 API 覆盖缺口（12 vs 21） | — | ⬜ S5 前端契约深扫 | S2 |

---

## 📂 长期工件路线图

S6 产出（尚未开始）：
```
scripts/audit/
├── invariant_check.py       # 每日自动跑的不变量检查
├── pt_vs_backtest_diff.py   # 回测 vs PT 差分对比
├── golden_factor_set.py     # 金标因子值集
├── contract_lock.py         # 前后端契约 snapshot
└── config_drift_check.py    # 三处配置漂移检测
```

---

## 🔗 相关文档

- `CLAUDE.md` — 项目入口 + 35 条铁律 (S1-S4 审计后新增 31-35 工程基础设施类)
- `SYSTEM_STATUS.md` — 系统现状全景
- `FACTOR_TEST_REGISTRY.md` — 因子测试注册表（累积测试数 M）
- `LESSONS_LEARNED.md` — 49 条经验教训
- `docs/audit/` — 本审计系列（你正在看的）
