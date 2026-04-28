# MVP 3.5 Evaluation Gate Framework ✅ 完结 (因子/策略入池硬门 + G1-G10 自动化)

> **状态**: ✅ **Wave 3 5/5 完结** (Session 42 2026-04-28, 3 批 PR #123/#124/#125 全 merged)
> **ADR**: Platform Blueprint §4.7 / Framework #4 Eval / 铁律 4/5/12/13/19/20 + G1-G10 Gates / **ADR-014 锁契约**
> **Sprint**: Wave 3 5/5 完结 (Session 42 2026-04-28 一日完成 3 批)
> **前置**: MVP 3.4 Event Sourcing ✅ / MVP 1.3c FactorRegistry G9/G10 ✅ / `factor_ic_history` 表 ✅ / `engines/factor_gate.py` G1-G8 ✅ / `engines/ic_calculator.py` ✅
> **进度**:
> - ✅ **批 1** PR #123 merged main `543c283`: PlatformEvaluationPipeline + 7 Gates (G1/G2/G3/G4/G8/G9/G10) + utils + 33 unit/1 smoke
> - ✅ **批 2** PR #124 merged main `039c497`: factor_lifecycle 双路径接入 + 4 周观察期 + 16 unit/1 smoke
> - ✅ **批 3** PR #125 merged main `977e56a`: Strategy Gates (G1'/G2'/G3') + PlatformStrategyEvaluator + ADR-014 + 17 unit/1 smoke

## Context

**问题**: 当前因子/策略入池**硬门散落** + **决策不留痕**:
- 铁律 4/5/12/13 (G1-G10 Gates) 散落在 `factor_lifecycle.py` / `factor_profiler.py` / 人工评审 中, 无统一 EvaluationPipeline.
- IC 计算走 `ic_calculator.py` 统一 (铁律 19), 但 paired bootstrap p<0.05 + Sharpe vs baseline 等下游 gate 散落各 research script.
- G9 (新颖性 AST jaccard >0.7) / G10 (经济机制可解释性) 当前**人工 review only**, 无自动化拦截.
- `factor_registry.update_status()` 调用方各自决定 active/warning/stale, 无 EvaluationGate 统一拦截.

**Precondition 实测发现** (Session 42 2026-04-28 开工前复核, 较设计初稿有 3 个漂移修正):
- ✅ `factor_registry`: 287 行, 含 status / pool / ic_decay_ratio (MVP 1.3a Wave 1 落地)
- ✅ `factor_ic_history`: 144,795 行 (Session 5 实测), 含 ic_5d/10d/20d/ic_ma20/ic_ma60
- ✅ `factor_lifecycle.py`: 26 tests pass, active/warning/stale 规则已纯函数化 (engines/factor_lifecycle.py 142 行 纯规则, 铁律 31)
- ✅ **G9 AST Jaccard auto-gate 已存** (Session 42 实测修正): `qm_platform/factor/registry.py:87 _default_ast_jaccard` + L215-230 `novelty_check` + L260-265 `register()` 内部已强制调用并 raise `OnboardingBlocked`. 即 MVP 1.3c 已 wire G9 硬门, 本 MVP 仅需 Platform Gate concrete 包装 + 暴露 EvaluationPipeline API.
- ✅ **G10 hypothesis 字段硬门已存** (Session 42 实测修正): `qm_platform/factor/registry.py:242-253 register()` 内部已校验 `spec.hypothesis` 长度 ≥ G10_HYPOTHESIS_MIN_LEN + 禁占位符前缀 + raise `OnboardingBlocked`. **DDL 字段名是 `hypothesis` 不是 `economic_mechanism`** (DDL 第 252 行).
- ❌ **paired bootstrap 自动化不存在**: 仅 `engines/metrics.py:378 bootstrap_sharpe_ci` (单 Sharpe CI), 缺 paired bootstrap p<0.05 vs baseline. 需新建 helper.
- ⚠️ **现有 `engines/factor_gate.py`** (非 batch_gate.py / batch_gate_v2.py, **本设计稿/eval interface 之前误引用**): 含 G1-G8 阈值 + GateStatus + BH-FDR `get_cumulative_test_count`. 本 MVP 把它升维到 Platform pipeline.

## Scope (~2-3 周, **3 批交付**, 串行)

> **v2 重构 (Session 42 2026-04-28)**: 原 4 批合并为 3 批 — Precondition 复核发现 MVP 1.3c 已 wire G9/G10 硬门进 register() (raise OnboardingBlocked), 故原 "批 2 G9/G10 wire" 仅剩 Platform Gate concrete 包装, 合并入批 1.

### 批 1: EvaluationPipeline + GateResult contract + 7 Gates concrete (~1-1.5 周)

**交付物**:
1. `backend/qm_platform/eval/pipeline.py` ⭐ 新 ~180 行
   - `PlatformEvaluationPipeline(EvaluationPipeline)` concrete
   - `evaluate(candidate, gates) -> EvaluationReport` (factor_name 入口, 返 Verdict)
   - `EvaluationReport` dataclass: candidate_id / passed: bool / gate_results: list[GateResult] / decision: ACCEPT/REJECT/WARNING / timestamp / reasoning
2. `backend/qm_platform/eval/gates/` ⭐ 新 package (7 gate concrete, ~80 行/each)
   - `g1_ic_significance.py`: IC t > 2.5 (Harvey Liu Zhu 2016, 调 ic_calculator + scipy.stats)
   - `g2_corr_filter.py`: 与 active 池 |corr| < 0.7 + 选股月收益 corr < 0.3
   - `g3_paired_bootstrap.py`: **新建 helper** paired bootstrap p<0.05 vs baseline (Sharpe / Sortino)
   - `g4_oos_walkforward.py`: WF 5-fold OOS Sharpe ≥ baseline (Wave 3 暂只读已存 cache, 不实跑回测)
   - `g8_bh_fdr.py`: BH-FDR 校正, M 调 `engines/config_guard.get_cumulative_test_count`
   - `g9_novelty_ast.py`: **包装** `qm_platform/factor/registry.py:_default_ast_jaccard` + 调 `novelty_check()` (复用 MVP 1.3c)
   - `g10_hypothesis.py`: **包装** registry.py L242-253 hypothesis 校验逻辑 (字段名 `hypothesis`, 不是 economic_mechanism)
3. `backend/qm_platform/eval/__init__.py` ⚠️ MODIFY: 导出 PlatformEvaluationPipeline + 7 Gate concretes
4. `backend/qm_platform/eval/interface.py` ⚠️ MODIFY: docstring 修正 `batch_gate.py / batch_gate_v2.py` → `engines/factor_gate.py` (实际文件名)
5. `backend/tests/test_evaluation_pipeline.py` ⭐ 新 ~280 行 ~22 tests
6. `backend/tests/smoke/test_mvp_3_5_batch_1_live.py` ⭐ 新 (铁律 10b)

### 批 2: G1-G4 自动 wire 进 factor_lifecycle (双路径并存 4 周) (~0.7 周)

**交付物**:
1. `backend/engines/factor_lifecycle.py` ⚠️ MODIFY (~80 行 delta, 不破老 evaluate_transition)
   - 新增 `evaluate_factor_full(meta, ic_history) -> EvaluationReport`: 调 PlatformEvaluationPipeline + G1/G2/G3/G4 集
   - 老 `evaluate_transition()` 保留, 双路径并存 4 周观察
   - active → warning: G1 t < 2.5 OR G3 paired bootstrap p > 0.05 (新规则) || ratio < 0.8 (老规则)
   - warning → critical: G4 WF OOS Sharpe < 0.3 baseline (新规则) || 持续 ratio < 0.5 20 天 (老规则)
2. `scripts/factor_lifecycle_monitor.py` ⚠️ MODIFY (~30 行 delta): 双路径调用 + 比对告警
3. Celery beat factor-lifecycle-weekly Friday 19:00 仍 weekly, 内部走 evaluation pipeline
4. `backend/tests/test_factor_lifecycle_eval_integration.py` ⭐ 新 ~200 行 ~15 tests

### 批 3: Strategy Eval Gate (S1/S2 onboarding) + ADR-013 (~0.5 周)

**交付物**:
1. `backend/qm_platform/eval/strategy_gates.py` ⭐ 新 ~120 行
   - 策略 G1' (Sharpe vs baseline paired bootstrap p<0.05) / G2' (max drawdown < threshold) / G3' (regression max_diff=0 vs old PT, 铁律 15)
2. `backend/qm_platform/strategy/registry.py` ⚠️ MODIFY (~30 行 delta): register() wire strategy gates (类似 MVP 1.3c 因子 register)
3. `docs/adr/ADR-013-evaluation-gate-contract.md` ⭐ 新 (≤ 3 页)
   - 锁 G1-G10 + Strategy G1'-G3' 契约 (Wave 4+ 不可破坏)
4. `backend/tests/test_strategy_eval_gates.py` ⭐ 新 ~150 行 ~10 tests
5. `backend/tests/smoke/test_mvp_3_5_batch_3_live.py` ⭐ 新 (铁律 10b)

## Out-of-scope (明确排除, 铁律 23)

- ❌ **G5/G6/G7 实施** (G5 G6 G7 在 ADR 但研究层 only, 自动化 gate 留 Wave 4+)
- ❌ **LLM-based G10 LLM 自动验证** (经济机制描述 LLM check, 当前仅检查非空, LLM 留 Wave 4+)
- ❌ **Eval pipeline 历史 replay / regression suite** (留 Wave 4 Observability)
- ❌ **Multi-factor portfolio gate** (因子组合层 gate, 留 MVP 4.x)
- ❌ **真金前 Stage 4.2 dry-run 自动化** (S2 LIVE 升级 dry-run 路径, 独立 PR)
- ❌ **退役 factor_lifecycle.py 散规则** (本 MVP 双路径并存, 退役留 MVP 3.5.1 Sunset Gate)

## 关键架构决策 (铁律 39 显式)

### Gates 是 pure function, 不 raise
- 选择: 每个 Gate `evaluate(meta, ctx) -> GateResult` 返 PASS/FAIL/WARN + reasoning, **不抛**
- 理由: Pipeline 顺序跑全部 Gate 收集所有 result, 用户看到完整 picture (而非首 fail 抛中断)
- Pipeline 顶层根据 gates 集体 decision: ACCEPT (全 PASS) / WARNING (FAIL 但允许 override) / REJECT (FAIL 必拒)

### G9 AST Jaccard 复用现有 helper
- 选择: G9 Gate 内部调 `_default_ast_jaccard` (registry.py 已存)
- 理由: 不重复造轮子, 现有 helper 已通过 26 tests
- 升级: helper 提到 platform/eval/utils.py 共享, registry import 路径调整

### 双路径退役 (factor_lifecycle 老规则 vs 新 pipeline)
- 选择: 批 3 双路径并存, 老 factor_lifecycle 直接判定 + 新 EvaluationPipeline 也跑, 比对一致后 sunset 老路径
- 理由: 老路径 26 tests pass + 真生产 Friday 19:00 跑过, 切换需观察 4 周避免误降级
- 退役条件: 4 周新老 lifecycle judgment match rate > 95% + 0 P1 mismatches

### G10 经济机制描述检查 (字段名: `hypothesis`)
- V1 (本 MVP): MVP 1.3c 已落地 — 检查 `FactorSpec.hypothesis` 非空 + 长度 ≥ `G10_HYPOTHESIS_MIN_LEN` + 不以占位符前缀开头 (qm_platform/factor/registry.py L242-253). 本 MVP 仅 Platform `g10_hypothesis.py` Gate concrete 包装该逻辑, 暴露 `EvaluationPipeline.evaluate()` API 对称 G1-G9.
- V2 (Wave 4+): LLM-based "因子表达式 ↔ hypothesis 描述" 一致性检查 (Claude/DeepSeek API)
- 理由: 铁律 13 spirit (可解释性) V1 满足, 自动化深度验证留资源充足时
- DDL 字段名: `factor_registry.hypothesis TEXT` (DDL 第 252 行) — 设计稿初稿误用 `economic_mechanism`, 已修正

### Strategy Gate G3' 强制 regression max_diff=0
- 选择: 新策略 register() 必跑 `regression_test --years 5` 验证 max_diff=0 vs baseline (铁律 15)
- 理由: 铁律 15 已强制, 本 Gate 是自动化执行
- 例外: 全新策略无 baseline → G3' SKIP (PASS 但 reasoning="no baseline, first deployment")

## LL-059 9 步闭环 (**3 批 = 3 PR**, 串行)

批 1 `feat/mvp-3-5-batch-1-eval-pipeline` → 批 2 `feat/mvp-3-5-batch-2-lifecycle-integration` → 批 3 `feat/mvp-3-5-batch-3-strategy-gates-adr`

> **v2 重构去除原批 2 (G9/G10 wire)** — Precondition 复核发现已在 MVP 1.3c register() 落地, 无需重复实施.

## 验证 (硬门, 铁律 10b + 40 + 15)

```bash
# 批 1
pytest backend/tests/test_evaluation_pipeline.py -v  # ~22 PASS
pytest -m smoke --timeout=180  # +1 batch_1 smoke 全绿

# 批 2
pytest backend/tests/test_factor_lifecycle_eval_integration.py -v  # ~15 PASS
python scripts/factor_lifecycle_monitor.py --dry-run --compare  # 新老规则比对

# 批 3
pytest backend/tests/test_strategy_eval_gates.py -v  # ~10 PASS
pytest -m smoke --timeout=180  # +1 batch_3 smoke 全绿
python scripts/regression_test.py --years 5  # max_diff=0 (铁律 15)
```

## 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| G9 AST Jaccard 太严, 拒掉合理变体因子 | 阻塞研究 pipeline | threshold 0.7 是已验证 (AlphaAgent KDD 2025), warn-only mode 1 周观察后切 reject |
| 存量 287 因子 G10 缺失大批量 | 全因子重新审 | audit 脚本生成清单, 分批补 economic_mechanism 字段 + warn-only mode 不阻塞老因子 |
| 批 3 新老 lifecycle judgment mismatch | active/warning 抖动 | 双路径 4 周比对 + alert mismatch + manual review |
| Strategy G3' regression 跑得慢 (12 年 5min) | register() 阻塞 | async background task + status='evaluating' 中间态 + 完成 callback 改 LIVE |
| LLM-based G10 V2 阻塞本 MVP | 设计漂移 | V1 仅长度检查, V2 留 Wave 4+, ADR-013 显式 V1 契约 |

## Follow-up (跨 PR, 不在本 plan)

1. G5/G6/G7 自动化 (Wave 4)
2. LLM-based G10 V2 (Wave 4 Observability LLM 接入后)
3. Multi-factor portfolio gate (MVP 4.x)
4. ADR-013 Eval Gate 契约 V2 (含 G5/G6/G7 + LLM)
5. Sunset 老 factor_lifecycle 散规则 (4 周双路径 PASS 后, MVP 3.5.1)

---

## **Wave 3 完结后总览** (MVP 3.1-3.5 全交付后, Session 41 实测刷新)

```
MVP 3.1 ✅ Risk Framework (Session 28-30, 6 PR + 1 spike #54)
MVP 3.2 ✅ Strategy Framework (Session 33-36, ~5 PR)
MVP 3.3 ✅ Signal-Exec Framework (Session 37-40, ~13 PR 累计含 stage 3.0)
MVP 3.4 ✅ Event Sourcing & Outbox (Session 41, 4 PR #119/#120/#121/#122)
MVP 3.5 → Eval Gate Framework (3 PR, Session 42+)

Wave 3 总计: ~28+ PR (累计含 stage cutover), 完整 Platform Framework SDK + 治理自动化
进入 Wave 4: Observability + Performance Attribution + CI/CD + Backup & DR
```
