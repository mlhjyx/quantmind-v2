# PYTEST_BASELINE_DRIFT — Session 9 (24 fail) → Session 35 (40 fail) 完整调查

**作者**: Session 35 (2026-04-25 15:30 ~ 16:30, 周六加时, AI auto mode)
**关联**: 铁律 40 (测试债务不得增长) + 铁律 22 (文档跟代码) + LL-074 (本 session 触发)
**状态**: ✅ 调查完成 — 40/40 fail 全部分类 + 1 REAL_BUG (DORMANT) 发现 + 1 HIGH 跨进程 platform shadow 待修

---

## 1. TL;DR (1 屏)

40 fail 全部分类完成. **0 阻塞 Monday 4-27 09:00 PT 首次生产触发**.

| 类别 | 计数 | Monday 影响 | 修复策略 | 备注 |
|------|-----|----------|---------|-----|
| **MISSING_DEP** | 21 | 0 | quarantine via skip-if-not-installed | shap (19) + DEAP (2), venv 缺包 |
| **REAL_BUG_DORMANT** | 4 | 0 (调用方未激活) | 修代码 / 标 deprecated | **factor_onboarding.py:517 dsl.parse()** 不存在 |
| **CONTRACT_DRIFT** | 4 | 0 | 修测试 mock | 4 处生产代码进步, 测试没跟 |
| **STALENESS** | 4 | 0 | 删测试 | turnover_stability_20 已 DEPRECATED |
| **SUBPROCESS_SHADOW** | 3 | **🟡 GP Sun 22:00 broken** | 修 backend/platform/ shadow | LL-070 跨进程变体 |
| **TEST_MOCK** | 2 | 0 | 修测试 | composite_strategy MagicMock format |
| **FLAKY** | 2 | 0 | 修测试 fixture 隔离 | 单跑 PASS, 全套 FAIL |

🔴 **真 bug 发现**: `factor_onboarding.py:517 dsl.parse(factor_expr)` 调用不存在的方法 (FactorDSL 没 `parse`, 应该用 `string_to_expr()` 或 `_DSLParser(...).parse()`). **当前未触发** (onboarding_tasks 未在 Beat schedule), 但 GP pipeline 若进入 onboarding 流程会爆.

🟡 **跨进程 shadow 影响 GP**: GP weekly mining (Sun 22:00 Beat 激活) 调 `FactorSandbox.execute_safely()` → multiprocessing subprocess → 子进程 import pandas → numpy 触发 stdlib `platform` → 被 `backend/platform/__init__.py` shadow → AttributeError → **subprocess exitcode=1 silent 失败**. GP 跑完产出 0 mined factor.

---

## 2. Baseline Anchor

### Session 9 末 (2026-04-19, Sub2 PR #20 post-merge)
- **Commit**: `add41bb` (Sub2 PR) → `808cbc5` (CLAUDE.md doc sync)
- **Pytest**: **24 fail / 2864 pass / X skipped**
- **来源**: `memory/project_sprint_state.md` Session 9 末 frontmatter

### Session 35 (2026-04-25)
- **Commit**: `b9a8c31` (LL-074 docs)
- **Pytest**: **40 fail / 3269 pass / 44 skipped in 11:46**
- **来源**: 本 session bkxz36zxl (`/tmp/pytest_full_session35.log` 262 行)

### Δ
- **+405 pass**: Sessions 10-34 多 PR 加 1700+ 新测试 (实际 +405 pass 因部分测试运行时间被 skipped)
- **+16 fail**: 见下完整矩阵
- **+44 skipped**: 新加 marker (smoke / live_tushare 等), 不计债务

---

## 3. 完整 40 fail 分类矩阵

### 3.1 MISSING_DEP (21) — venv 缺包

#### 3.1.1 shap not installed (19)

| Test ID | 类 |
|---------|---|
| `test_ml_explainer.py::TestSHAPEdgeCases::test_explain_global_single_feature` | EdgeCases |
| `test_ml_explainer.py::TestSHAPEdgeCases::test_explain_local_multi_row_raises_on_wrong_shape` | EdgeCases |
| `test_ml_explainer.py::TestSHAPEdgeCases::test_explain_temporal_single_period` | EdgeCases |
| `test_ml_explainer.py::TestSHAPEdgeCases::test_global_importance_sum_positive` | EdgeCases |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_all_values_nonnegative` | Global |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_feat0_is_top` | Global |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_numpy_input` | Global |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_returns_correct_types` | Global |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_sampling_limit` | Global |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_sorted_descending` | Global |
| `test_ml_explainer.py::TestSHAPExplainerGlobal::test_to_echarts_bar_format` | Global |
| `test_ml_explainer.py::TestSHAPExplainerLocal::test_1d_numpy_input` | Local |
| `test_ml_explainer.py::TestSHAPExplainerLocal::test_base_value_plus_shap_equals_prediction` | Local |
| `test_ml_explainer.py::TestSHAPExplainerLocal::test_correct_number_of_features` | Local |
| `test_ml_explainer.py::TestSHAPExplainerLocal::test_to_echarts_waterfall_format` | Local |
| `test_ml_explainer.py::TestSHAPExplainerTemporal::test_drift_scores_length` | Temporal |
| `test_ml_explainer.py::TestSHAPExplainerTemporal::test_importance_matrix_shape` | Temporal |
| `test_ml_explainer.py::TestSHAPExplainerTemporal::test_returns_correct_periods` | Temporal |
| `test_ml_explainer.py::TestSHAPExplainerTemporal::test_to_echarts_heatmap_format` | Temporal |

**根因**: `engines/ml_explainer.py:192 import shap` → ModuleNotFoundError. shap 不在 `pyproject.toml` 也不在 venv.

**生产影响**: 0. ML 闭环 Phase 3D (2026-04-14) 已 NO-GO, ML predictor 层 CLOSED. SHAP 可解释性是 ML 子模块, 不在 PT 信号路径.

**修复策略**: Quarantine — 在 test_ml_explainer.py 顶部加 `pytest.importorskip("shap")` 或 `@pytest.mark.skipif(not has_shap, reason="ML closed Phase 3D, shap optional")`.

#### 3.1.2 DEAP not installed (2)

| Test ID | 备注 |
|---------|-----|
| `test_pipeline_orchestrator.py::TestBlacklistSeedFactors::test_blacklisted_seed_not_added_in_step1` | GP DSL pipeline |
| `test_pipeline_orchestrator.py::TestBlacklistSeedFactors::test_non_blacklisted_seed_included` | 同上 |

**根因**: `engines/mining/gp_engine.py:597 import deap` 触发 `RuntimeError("DEAP未安装")`. DEAP 不在 venv.

**生产影响**: 🟡 GP weekly mining (Sun 22:00 Beat 激活) 会因为 DEAP 缺失而启动失败. 但当前 GP 任务**完全没用** — 自 Session 16 已废为研究路径, Phase 3D ML synthesis 也 NO-GO. **不影响 PT**.

**修复策略**: Quarantine + spawn task — 评估是否真要恢复 GP. 若是, `pip install deap` + 重审 `gp-weekly-mining` 调度.

---

### 3.2 REAL_BUG_DORMANT (4) — 真生产 bug, 当前调用方未激活

| Test ID | 错误 |
|---------|------|
| `test_factor_onboarding.py::TestNeutralizeWithIndustry::test_zscore_neutralization_industry_mean_near_zero` | `AttributeError: 'FactorDSL' object has no attribute 'parse'` |
| `test_factor_onboarding.py::TestNeutralizeWithIndustry::test_zscore_neutralization_cross_section_std_near_one` | 同上 |
| `test_factor_onboarding.py::TestNeutralizeWithIndustry::test_zscore_neutralization_mean_near_zero` | 同上 |
| `test_factor_onboarding.py::TestBoundaryConditions::test_compute_factor_values_below_min_stocks_skips_date` | 同上 |

**根因**: `backend/app/services/factor_onboarding.py:517` 调 `dsl.parse(factor_expr)`:
```python
dsl = FactorDSL()
expr_node = dsl.parse(factor_expr)  # ❌ FactorDSL has no parse()
```

`FactorDSL` 类 (line 679 of `factor_dsl.py`) 没 `parse` 方法. 真正的 parse 入口:
- `_DSLParser(line 1276).parse()` 内部 parser
- `string_to_expr(expr_str)` 公开 helper at line 1417

**正确写法应该是** `expr_node = string_to_expr(factor_expr)`.

**生产影响**: ⚠️ DORMANT.
- `_compute_factor_values` 唯一调用方: `FactorOnboardingService.onboard_factor()` 自身
- `FactorOnboardingService` 唯一外部调用方: `app/tasks/onboarding_tasks.py` Celery task
- `onboarding_tasks` **不在 Beat schedule** (grep 确认)
- 但若手动调或 GP pipeline 走入 onboarding 流程 → 立即爆

**修复优先级**: **MEDIUM** — Monday 09:00 不触发, 但本 sprint 应该独立 PR 修. ~5 min 改动.

**修复**: 把 line 517 `expr_node = dsl.parse(factor_expr)` 改为 `expr_node = string_to_expr(factor_expr)` + `from engines.mining.factor_dsl import string_to_expr` import.

---

### 3.3 CONTRACT_DRIFT (4) — 生产代码进步, 测试 mock 没跟

| Test ID | 漂移点 | 引入 PR (推测) |
|---------|--------|--------------|
| `test_phase_b_infra.py::TestHealthCheck::test_health_check_all_pass` | `health_check.py` 新增 stock_status_ok / factor_nan_ok / qmt_ok / config_drift_ok / redis_ok 5+ 检查项, mock 仅设原 4 项 | 多 sprint 累积 |
| `test_can_trade_board.py::TestCanTradeST::test_st_5pct_limit_up` | broker.can_trade 签名: `(code, direction, row, **price_limit DataFrame**)` → `(code, direction, row, symbols_info=None)`, ST 检测改走 symbols_info 而非 price_limit | Session 14 ADR-008 PR-B (ST race condition fix) |
| `test_opening_gap_check.py::TestOpeningGapCheck::test_p0_commits_transaction` | 测试 assert `conn.commit()` 被调, 但 Service 层不允许 commit (铁律 32) | 铁律 32 强制后该测试逻辑反了 |
| `test_execution_mode_isolation.py::test_d2_run_paper_trading_prev_nav_parametric` | 测试 regex 锚 `WHERE.{0,100}?execution_mode\s*=\s*%s`, 但 prev_nav SQL 已 + `AND trade_date < %s` 顺序变 | Session 21 PR #33 P1-c prev_nav fix |

**生产影响**: 0. 4 处生产代码都是**正向进步** (新检查 / ST race fix / 铁律 32 合规 / prev_nav LIMIT bug 修).

**修复策略**: 修测试 (4 独立 commit OR 1 PR):
- TestHealthCheck: 加 5 mock entries
- TestCanTradeST: 改 `price_limit=...` → `symbols_info=...`
- TestOpeningGapCheck::test_p0_commits_transaction: 反转 assertion (`assert not commit_called`) 或删除
- D2 prev_nav regex: 更新 regex 容许 `AND trade_date < %s` 在 execution_mode 之前/之后

---

### 3.4 STALENESS (4) — DEPRECATED 因子残留测试

| Test ID |
|---------|
| `test_turnover_stability.py::TestTurnoverStabilityRegistration::test_registered_in_reserve_factors` |
| `test_turnover_stability.py::TestTurnoverStabilityRegistration::test_direction_is_negative_one` |
| `test_turnover_stability.py::TestTurnoverStabilityRegistration::test_reserve_lambda_callable` |
| `test_turnover_stability.py::TestTurnoverStabilityIntegration::test_reserve_lambda_with_dataframe` |

**根因**: `turnover_stability_20` 已从 `RESERVE_FACTORS` 移除, `__init__.py:214` 注释:
```python
# turnover_stability_20: corr(turnover_mean_20)=0.904, 高度冗余
```

测试期望 factor 在注册表, 实际只剩 `rsrs_raw_18 + vwap_bias_1d`.

**生产影响**: 0. CORE3+dv_ttm 不含 turnover_stability_20.

**修复**: 删除 `test_turnover_stability.py` 整个文件 (因子已 DEPRECATED, 不再需要测).

---

### 3.5 SUBPROCESS_SHADOW (3) — LL-070 跨进程变体, 🟡 GP 影响

| Test ID | 错误 |
|---------|------|
| `test_mining_engine.py::TestFactorSandboxSecurity::test_execute_safely_returns_series` | `子进程异常退出 (exitcode=1)` |
| `test_mining_engines.py::TestFactorSandboxExecution::test_simple_execution` | 同上 |
| `test_mining_engines.py::TestFactorSandboxExecution::test_timeout_kills_process` | 同上 |

**根因 traceback** (从 multiprocessing.spawn child):
```
File "D:\quantmind-v2\backend\engines\mining\__init__.py" → import ast_dedup
  → ast_dedup.py: import pandas
    → pandas/__init__.py imports numpy
      → numpy: import platform   ← stdlib
        → SHADOWED by D:\quantmind-v2\backend\platform\__init__.py
          → platform/__init__.py imports backtest
            → loaders.py imports data.parquet_cache
              → parquet_cache.py imports engines.signal_engine
                → signal_engine.py uses pd.DataFrame annotation
                  → pandas not yet fully initialized
                    → AttributeError: partially initialized module 'pandas' has no attribute 'DataFrame'
```

**LL-070 (Session 32)** 已识别 `backend/platform/` shadow stdlib 问题, 修复用 `append + guard` 替代 `insert(0)` + 6 scripts hardening (PR #67/#68). 但**未覆盖 multiprocessing.spawn 子进程** — spawn 重新初始化 Python 解释器, 用项目根目录的 .pth 文件 (`.venv/Lib/site-packages/quantmind.pth`) 注入 `backend/` 到 sys.path, 子进程从干净环境开始, 同样的 shadow 又发生.

**生产影响**: 🟡 **GP weekly mining (Sun 22:00 Beat 激活) 完全 broken**.
- `pipeline_orchestrator.py:1046 FactorSandbox(timeout=10)` 在 GP pipeline 中调用
- `FactorSandbox.execute_safely(...)` → `multiprocessing.Process(...)`
- 子进程立刻 platform shadow 死亡, 返 exitcode=1
- 父进程捕获 → ExecutionResult(success=False, error='子进程异常退出')
- GP 跑数百候选 factor 全 fail, 产出 0 mined factor (silent)
- **不影响 Monday PT** (PT 不调 FactorSandbox)

**修复策略 (HIGH)**: Session 36+ 独立 PR 修复:
1. **方案 A (推荐)**: `backend/platform/` 改为 `backend/qm_platform/` (重命名, 彻底解 shadow). 涉及多 import 路径更新.
2. **方案 B**: `FactorSandbox.execute_safely()` 调 `multiprocessing.Process` 时显式 `os.environ["PYTHONNOUSERSITE"] = "1"` + 改 sys.path 清理 (子进程内部预防 shadow). 局部修复.
3. **方案 C**: GP weekly mining 暂时 disable (Beat schedule 注释 `gp-weekly-mining`), 等彻底重构.

---

### 3.6 TEST_MOCK (2) — Mock setup 过期

| Test ID | 错误 |
|---------|------|
| `test_composite_strategy.py::TestRegimeModifierFallback::test_hmm_success_risk_on` | `TypeError: unsupported format string passed to MagicMock.__format__` |
| `test_composite_strategy.py::TestRegimeModifierFallback::test_hmm_success_risk_off` | 同上 |

**根因**: 生产代码 (`composite_strategy.py` 或 modifier) 添加新的字符串格式化 (e.g., `f"value={hmm_score:.2f}"`), 但测试 mock `MagicMock()` 没设 `__format__` 行为, 调用 `format(MagicMock(), ".2f")` raises TypeError.

**生产影响**: 0. 生产代码进步, 测试 mock 没跟.

**修复**: 测试 fixture 用 `MagicMock(spec=float)` 或显式设 `mock.__format__ = lambda fmt: "0.5"`.

---

### 3.7 FLAKY (2) — 单跑 PASS, 全套 FAIL (state leak)

| Test ID | 单跑结果 |
|---------|---------|
| `test_composite_strategy.py::TestCompositeDecisionCompleteness::test_satellites_logged_but_not_used` | ✅ PASS |
| `test_deepseek_client.py::TestDeepSeekClientMock::test_mock_mode_activates_without_api_key` | ✅ PASS |

**根因**: 测试间状态泄漏 (env var / 模块缓存 / global state). 单独跑 OK, 与某个其他测试同跑 FAIL.

**生产影响**: 0.

**修复策略 (LOW, defer)**: 二分搜索找污染源, 或加 `@pytest.fixture(autouse=True)` 重置. 不紧急.

---

## 4. 类别小结

| 类别 | 总数 | 修复难度 | 优先级 | 预期 PR 数 |
|------|------|---------|--------|----------|
| MISSING_DEP | 21 | 🟢 LOW (1 文件 skipif) | LOW | 1 (PR-A) |
| REAL_BUG_DORMANT | 4 | 🟢 LOW (1 行改 import) | **MEDIUM** | 1 (PR-B 真 bug 修) |
| CONTRACT_DRIFT | 4 | 🟡 MED (4 mock 各自更新) | LOW | 1 (PR-C) |
| STALENESS | 4 | 🟢 LOW (删 1 文件) | LOW | 1 (PR-D, 可合 PR-C) |
| SUBPROCESS_SHADOW | 3 | 🔴 HIGH (重命名 package OR subprocess fix) | **MEDIUM** | 1 (PR-E spike + 实施) |
| TEST_MOCK | 2 | 🟡 MED | LOW | 同 PR-C |
| FLAKY | 2 | 🟡 MED (debug 二分) | LOW | defer |

---

## 5. 修复 PR 计划 (Session 36+, 不 Monday block)

### PR-B (优先) `fix(factor-onboarding): replace dsl.parse() with string_to_expr()`
- 1 line 改: `factor_onboarding.py:517 dsl.parse(factor_expr)` → `string_to_expr(factor_expr)`
- import 加: `from engines.mining.factor_dsl import string_to_expr`
- 测试 4/4 PASS
- 反映 dormant bug: 若 onboarding 流程激活 (Phase 3F+ 后续 GP 闭环) 立即爆

### PR-A `chore(deps): quarantine ML/GP tests requiring optional packages`
- 加 `pytest.importorskip` 或 `@pytest.mark.skipif`
- shap 19 + DEAP 2 = 21 test skip
- 不装包 (project 决议 ML closed Phase 3D, GP 待重审)

### PR-C `fix(tests): update mock contracts (health_check, ST broker, opening_gap commit, prev_nav SQL, MagicMock format)`
- 4 contract drift + 2 mock issues = 6 修
- 单 PR + 6 commits

### PR-D `chore(tests): delete deprecated turnover_stability tests`
- 删 `test_turnover_stability.py` (4 test)
- 因子已 DEPRECATED 注释 `__init__.py:214`

### PR-E (HIGH 难度) `fix(platform): rename backend/platform → backend/qm_platform to eliminate stdlib shadow`
- 修 GP weekly mining 跨进程崩溃
- Spike 评估: 重命名 vs subprocess sys.path 局部修
- 涉及大量 import 路径更新 (估 30-50 文件)
- Session 36+ 单独 plan + 实施

### 预期消化结果
- PR-A merge → 21 fail 转 skip (40 → 19 fail)
- PR-B merge → 4 fail 修 (19 → 15 fail)
- PR-C merge → 6 fail 修 (15 → 9 fail)
- PR-D merge → 4 fail 删 (9 → 5 fail)
- PR-E merge → 3 fail 修 + GP unblock (5 → 2 fail)
- 剩 2 FLAKY → 加 fixture 隔离 → 0 fail OR keep 2 known-flaky

**目标**: 4-7 个独立 PR, 1-2 weeks 内 baseline 回到 ≤ 5 fail.

---

## 6. 真 bug 风险评估 — Monday 4-27 09:00 决策

✅ **0 fail 影响 Monday 4-27 09:00 PT 首次生产触发**.

证据:
- MISSING_DEP (21): venv config, 不触 PT
- REAL_BUG_DORMANT (4): factor_onboarding 调用方未激活 (Beat 不调)
- CONTRACT_DRIFT (4): 生产代码正向进步, 测试落后
- STALENESS (4): DEPRECATED 因子, 不在 CORE3+dv_ttm
- SUBPROCESS_SHADOW (3): GP Sun 22:00 broken, 但 GP 不影响 PT 信号生成 (PT 用 CORE3+dv_ttm 静态因子)
- TEST_MOCK (2): mock 过期, 生产对
- FLAKY (2): 单跑 PASS

**Monday 决策**: 不阻塞. Session 36+ 启动修复 PR-A → PR-E.

---

## 7. 候选铁律 (Session 36+ 沉淀)

### 候选 LL-075: pytest 输出用 `tee` 不用 `tail`

Session 35 上半段 bxb8vwf8l Bash 任务输出被 `| tail -10` 截断, 31 行 FAILED 丢失, 导致 categorization 阻塞. **铁律建议**:

> 调试性 pytest 全套测试时, 必用 `tee` 或重定向到文件 (`> /tmp/pytest_session_*.log`), 不用 `| tail -N` 一次性截断. tail 仅在已知输出大小可控时使用 (e.g. `pytest --tb=no -q | tail -50`, 因为 `-q` 已最小化).

### 候选铁律 44: 生产关键链路监控不依赖被监控对象 (LL-074)

承前 LL-074 ServicesHealthCheck 不开 PG conn 设计哲学:
> "生产关键链路 (PT 信号 / 风控 / 资金) 监控 schtask **频次 ≤ 30min**, 且**不允许依赖被监控对象** (e.g. 监控 PG 不依赖 PG, 监控 Beat 不依赖 Beat task)."

### 候选铁律 45: 生产 multiprocessing 子进程必须 isolated sys.path

承前 LL-070 的多进程变体:
> "生产代码若用 `multiprocessing.Process` 启 subprocess, 子进程必须**预清理 sys.path 防 shadow** (e.g., 移除项目根目录, 或用专用 worker entry script)."

---

## 8. 附录 A: 130 commits since baseline (摘要)

完整 timeline: `git log --oneline 808cbc5..HEAD --pretty=format:"%h %s"` 或本调查附属 LOG.

主要 PR 群 (与 fail 关联):
- Session 14 (ADR-008 stage 2 PR-B): ST race condition fix → broker.can_trade signature drift
- Session 17 PR #29 Stage 4: PTAudit + signal_service execution_mode → opening_gap_check + execution_mode_isolation drift
- Session 21 PR #33 P1-c prev_nav fix → execution_mode_isolation regex drift
- Session 28-30 MVP 3.1 PR #55-#61: Risk Framework new tests (全 PASS, 不在 fail 列)
- Session 33 PR #69-#72 MVP 3.2: Strategy Framework new tests (全 PASS)
- Session 35 PR #74 ServicesHealthCheck: 44 new test PASS
- Sessions 16-32 Phase C C1+C2+C3 + Phase 3 lifecycle + 多次 health_check 升级 → test_phase_b_infra mock 漂移

---

## 9. 附录 B: 完整 40 fail 名单 (alphabetical)

```
test_can_trade_board.py::TestCanTradeST::test_st_5pct_limit_up
test_composite_strategy.py::TestCompositeDecisionCompleteness::test_satellites_logged_but_not_used
test_composite_strategy.py::TestRegimeModifierFallback::test_hmm_success_risk_off
test_composite_strategy.py::TestRegimeModifierFallback::test_hmm_success_risk_on
test_deepseek_client.py::TestDeepSeekClientMock::test_mock_mode_activates_without_api_key
test_execution_mode_isolation.py::test_d2_run_paper_trading_prev_nav_parametric
test_factor_onboarding.py::TestBoundaryConditions::test_compute_factor_values_below_min_stocks_skips_date
test_factor_onboarding.py::TestNeutralizeWithIndustry::test_zscore_neutralization_cross_section_std_near_one
test_factor_onboarding.py::TestNeutralizeWithIndustry::test_zscore_neutralization_industry_mean_near_zero
test_factor_onboarding.py::TestNeutralizeWithIndustry::test_zscore_neutralization_mean_near_zero
test_mining_engine.py::TestFactorSandboxSecurity::test_execute_safely_returns_series
test_mining_engines.py::TestFactorSandboxExecution::test_simple_execution
test_mining_engines.py::TestFactorSandboxExecution::test_timeout_kills_process
test_ml_explainer.py::TestSHAPEdgeCases::test_explain_global_single_feature
test_ml_explainer.py::TestSHAPEdgeCases::test_explain_local_multi_row_raises_on_wrong_shape
test_ml_explainer.py::TestSHAPEdgeCases::test_explain_temporal_single_period
test_ml_explainer.py::TestSHAPEdgeCases::test_global_importance_sum_positive
test_ml_explainer.py::TestSHAPExplainerGlobal::test_all_values_nonnegative
test_ml_explainer.py::TestSHAPExplainerGlobal::test_feat0_is_top
test_ml_explainer.py::TestSHAPExplainerGlobal::test_numpy_input
test_ml_explainer.py::TestSHAPExplainerGlobal::test_returns_correct_types
test_ml_explainer.py::TestSHAPExplainerGlobal::test_sampling_limit
test_ml_explainer.py::TestSHAPExplainerGlobal::test_sorted_descending
test_ml_explainer.py::TestSHAPExplainerGlobal::test_to_echarts_bar_format
test_ml_explainer.py::TestSHAPExplainerLocal::test_1d_numpy_input
test_ml_explainer.py::TestSHAPExplainerLocal::test_base_value_plus_shap_equals_prediction
test_ml_explainer.py::TestSHAPExplainerLocal::test_correct_number_of_features
test_ml_explainer.py::TestSHAPExplainerLocal::test_to_echarts_waterfall_format
test_ml_explainer.py::TestSHAPExplainerTemporal::test_drift_scores_length
test_ml_explainer.py::TestSHAPExplainerTemporal::test_importance_matrix_shape
test_ml_explainer.py::TestSHAPExplainerTemporal::test_returns_correct_periods
test_ml_explainer.py::TestSHAPExplainerTemporal::test_to_echarts_heatmap_format
test_opening_gap_check.py::TestOpeningGapCheck::test_p0_commits_transaction
test_phase_b_infra.py::TestHealthCheck::test_health_check_all_pass
test_pipeline_orchestrator.py::TestBlacklistSeedFactors::test_blacklisted_seed_not_added_in_step1
test_pipeline_orchestrator.py::TestBlacklistSeedFactors::test_non_blacklisted_seed_included
test_turnover_stability.py::TestTurnoverStabilityIntegration::test_reserve_lambda_with_dataframe
test_turnover_stability.py::TestTurnoverStabilityRegistration::test_direction_is_negative_one
test_turnover_stability.py::TestTurnoverStabilityRegistration::test_registered_in_reserve_factors
test_turnover_stability.py::TestTurnoverStabilityRegistration::test_reserve_lambda_callable
```

---

## 10. 后续 Session 36+ 验证清单

- [ ] PR-B (REAL_BUG_DORMANT, 优先): 1 line fix factor_onboarding.py:517
- [ ] PR-A (MISSING_DEP, low): pytest.importorskip 21 test
- [ ] PR-C (CONTRACT_DRIFT + TEST_MOCK): 6 mock 修
- [ ] PR-D (STALENESS): 删 test_turnover_stability.py
- [ ] PR-E (SUBPROCESS_SHADOW, HIGH): 单独 spike + plan + 实施 (1-2 weeks)
- [ ] FLAKY 2 个 binary search 找污染
- [ ] 重跑 full pytest, 新 baseline ≤ 5 fail (target)
- [ ] 更新 `memory/project_sprint_state.md` baseline 数字
- [ ] 更新 `CLAUDE.md` 铁律 40 baseline (24→<=5)
- [ ] 候选铁律 44/45 + LL-075 入册

---

## 11. 关联文件

- 原始 pytest 输出: `/tmp/pytest_full_session35.log` (262 行)
- Baseline anchor commit: `808cbc5` (Session 9 末)
- Investigation commit: `b9a8c31` (LL-074 docs, Session 35 末)
- LL-070 (相关): `LESSONS_LEARNED.md` line 1715 (backend/platform shadow)
- LL-074 (本 session): `LESSONS_LEARNED.md` line 1779+ (CeleryBeat silent death)
