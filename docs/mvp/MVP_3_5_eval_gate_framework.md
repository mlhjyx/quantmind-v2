# MVP 3.5 Evaluation Gate Framework (因子/策略入池硬门 + G1-G10 自动化)

> **ADR**: Platform Blueprint §4.7 / Framework #4 Eval / 铁律 4/5/12/13/19/20 + G1-G10 Gates
> **Sprint**: Wave 3 5/5 收官 (Session 39+ 起, post MVP 3.4 Event Sourcing merged)
> **前置**: MVP 3.4 Event Sourcing ✅ (event_outbox 提供 evaluation 历史 trace) / FactorRegistry G9/G10 ABC 已存 ✅ / `factor_ic_history` 表 ✅

## Context

**问题**: 当前因子/策略入池**硬门散落** + **决策不留痕**:
- 铁律 4/5/12/13 (G1-G10 Gates) 散落在 `factor_lifecycle.py` / `factor_profiler.py` / 人工评审 中, 无统一 EvaluationPipeline.
- IC 计算走 `ic_calculator.py` 统一 (铁律 19), 但 paired bootstrap p<0.05 + Sharpe vs baseline 等下游 gate 散落各 research script.
- G9 (新颖性 AST jaccard >0.7) / G10 (经济机制可解释性) 当前**人工 review only**, 无自动化拦截.
- `factor_registry.update_status()` 调用方各自决定 active/warning/stale, 无 EvaluationGate 统一拦截.

**Precondition 实测发现** (Session 39+ 开工前需复核, 当前 Session 36 末状态):
- ✅ `factor_registry`: 287 行, 含 status / pool / ic_decay_ratio (MVP 1.3a Wave 1 落地)
- ✅ `factor_ic_history`: 144,795 行 (Session 5 实测), 含 ic_5d/10d/20d/ic_ma20/ic_ma60
- ✅ `factor_lifecycle.py`: 26 tests pass, active/warning/stale 规则已纯函数化
- ❌ **G9 AST Jaccard auto-gate 不存在**: `_default_ast_jaccard` helper 在 registry.py 但 register() 未强制调用
- ❌ **paired bootstrap 自动化不存在**: research script 手工跑 `bootstrap_smoothing_pvalues.py`, 无 EvaluationPipeline 统一入口

## Scope (~3-4 周, 4 批交付, 串行)

### 批 1: EvaluationPipeline + GateResult contract (~1 周)

**交付物**:
1. `backend/qm_platform/eval/pipeline.py` ⭐ 新 ~150 行
   - `PlatformEvaluationPipeline(EvaluationPipeline)` concrete
   - `evaluate(candidate: FactorMeta | StrategyMeta, gates: list[Gate]) -> EvaluationReport`
   - `EvaluationReport` dataclass: candidate_id / passed: bool / gate_results: list[GateResult] / decision: ACCEPT/REJECT/WARNING / timestamp / reasoning
2. `backend/qm_platform/eval/gates/` ⭐ 新 package (~6 file, 10 gate concrete)
   - `g1_ic_significance.py`: IC t > 2.5 (Harvey Liu Zhu 2016)
   - `g2_corr_filter.py`: 与 active 池 |corr| < 0.7 + 选股月收益 corr < 0.3
   - `g3_paired_bootstrap.py`: paired bootstrap p<0.05 vs baseline (调用 ic_calculator)
   - `g4_oos_walkforward.py`: WF 5-fold OOS Sharpe ≥ baseline
   - `g8_bh_fdr.py`: BH-FDR 校正, M = FACTOR_TEST_REGISTRY 累积 84
   - `g9_novelty_ast.py`: AST Jaccard < 0.7 (现有 _default_ast_jaccard helper 升级)
   - `g10_economic_mechanism.py`: 经济机制描述非空 + LLM check (可选)
3. `backend/qm_platform/eval/__init__.py` ⚠️ MODIFY: 导出 PlatformEvaluationPipeline + Gate concretes
4. `backend/tests/test_evaluation_pipeline.py` ⭐ 新 ~250 行 ~20 tests

### 批 2: G9 / G10 自动 wire 进 FactorRegistry.register (~1 周)

**交付物**:
1. `backend/qm_platform/factor/registry.py` ⚠️ MODIFY (~50 行 delta)
   - `DBFactorRegistry.register()` 内部调 `EvaluationPipeline.evaluate(meta, gates=[G9, G10])` 强制
   - G9 reject → ValueError("候选因子与现存 X 相似度 0.8 > 0.7, 拒绝")
   - G10 missing → ValueError("候选因子 economic_mechanism 字段空, 铁律 13 拒绝")
2. `backend/tests/test_factor_registry_g9_g10.py` ⭐ 新 ~150 行 ~10 tests
3. 现有 287 因子 audit: scripts/audit/audit_g9_g10_compliance.py 跑出存量 G10 缺失因子清单 (manual review)

### 批 3: G1-G4 自动 wire 进 factor_lifecycle (~1 周)

**交付物**:
1. `backend/engines/factor_lifecycle.py` ⚠️ MODIFY (~80 行 delta)
   - `evaluate_factor(meta, ic_history) -> LifecycleStatus`: 调 PlatformEvaluationPipeline + G1/G2/G3/G4 集
   - active → warning: G1 t < 2.5 OR G3 paired bootstrap p > 0.05
   - warning → stale: 4 周持续 warning OR G4 WF OOS Sharpe < 0.3 baseline
2. `scripts/factor_lifecycle_monitor.py` ⚠️ MODIFY (~20 行 delta): 走 EvaluationPipeline
3. Celery beat factor-lifecycle-weekly Friday 19:00 仍 weekly, 内部走 evaluation pipeline
4. `backend/tests/test_factor_lifecycle_eval_integration.py` ⭐ 新 ~200 行 ~15 tests

### 批 4: Strategy Eval Gate (S1/S2 onboarding) + ADR-013 (~0.5 周)

**交付物**:
1. `backend/qm_platform/eval/strategy_gates.py` ⭐ 新 ~120 行
   - 策略 G1' (Sharpe vs baseline paired bootstrap p<0.05) / G2' (max drawdown < threshold) / G3' (regression max_diff=0 vs old PT, 铁律 15)
2. `backend/qm_platform/strategy/registry.py` ⚠️ MODIFY (~30 行 delta): register() wire strategy gates
3. `docs/adr/ADR-013-evaluation-gate-contract.md` ⭐ 新 (≤ 3 页)
   - 锁 G1-G10 + Strategy G1'-G3' 契约 (Wave 4+ 不可破坏)
4. `backend/tests/test_strategy_eval_gates.py` ⭐ 新 ~150 行 ~10 tests
5. `backend/tests/smoke/test_mvp_3_5_live.py` ⭐ 新 (铁律 10b)

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

### G10 经济机制描述检查
- V1 (本 MVP): 仅检查 `factor_meta.economic_mechanism` 字段非空 + 长度 > 50 字符
- V2 (Wave 4+): LLM-based "因子表达式 ↔ 经济机制描述" 一致性检查 (Claude/DeepSeek API)
- 理由: 铁律 13 spirit (可解释性) V1 满足, 自动化深度验证留资源充足时

### Strategy Gate G3' 强制 regression max_diff=0
- 选择: 新策略 register() 必跑 `regression_test --years 5` 验证 max_diff=0 vs baseline (铁律 15)
- 理由: 铁律 15 已强制, 本 Gate 是自动化执行
- 例外: 全新策略无 baseline → G3' SKIP (PASS 但 reasoning="no baseline, first deployment")

## LL-059 9 步闭环 (4 批 = 4 PR, 串行)

批 1 `feat/mvp-3-5-batch-1-eval-pipeline` → 批 2 `feat/mvp-3-5-batch-2-g9-g10-wire` → 批 3 `feat/mvp-3-5-batch-3-lifecycle-integration` → 批 4 `feat/mvp-3-5-batch-4-strategy-gates-adr`

## 验证 (硬门, 铁律 10b + 40 + 15)

```bash
# 批 1
pytest backend/tests/test_evaluation_pipeline.py -v  # ~20 PASS

# 批 2 (regression critical, 不能破现有 287 因子)
pytest backend/tests/test_factor_registry_g9_g10.py -v  # ~10 PASS
python scripts/audit/audit_g9_g10_compliance.py  # 存量 G10 缺失清单 (manual fix)

# 批 3
pytest backend/tests/test_factor_lifecycle_eval_integration.py -v  # ~15 PASS
python scripts/factor_lifecycle_monitor.py --dry-run --compare  # 新老规则比对

# 批 4
pytest backend/tests/test_strategy_eval_gates.py -v  # ~10 PASS
pytest -m smoke --timeout=180  # +1 batch_4 smoke 全绿
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

## **Wave 3 完结后总览** (MVP 3.1-3.5 全交付后)

```
MVP 3.1 ✅ Risk Framework (Session 30, 6 PR)
MVP 3.2 ✅ Strategy Framework (Session 33-36, 5 PR)
MVP 3.3 → Signal-Exec Framework (3 PR)
MVP 3.4 → Event Sourcing & Outbox (4 PR)
MVP 3.5 → Eval Gate Framework (4 PR)

Wave 3 总计: 22 PR, ~14-18 周, 完整 Platform Framework SDK + 治理自动化
进入 Wave 4: Observability + Performance Attribution + CI/CD + Backup & DR
```
