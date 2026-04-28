# ADR-014 — Evaluation Gate Contract (G1-G10 + Strategy G1'-G3')

> **状态**: 已采纳 (Session 42, 2026-04-28, MVP 3.5 batch 3)
> **关联**: 铁律 4 / 5 / 12 / 13 / 15 / 18 / 19 / 20
> **取代**: factor onboarding 与 strategy promotion 散落 Gate 逻辑

## Context

MVP 3.5 batch 1+2 落地了 PlatformEvaluationPipeline + 7 因子 Gates concrete (G1/G2/G3/G4/G8/G9/G10) + factor_lifecycle 双路径接入. batch 3 补 Strategy Gates (G1' Sharpe paired bootstrap / G2' Max DD / G3' regression max_diff=0).

下一阶段 (Wave 4+) 可能加 LLM-based G10 V2 / G5/G6/G7 自动化等. **如不锁契约**, 后续修改将破坏 G1-G10 标识 + 阈值的语义稳定性, 导致历史 audit log 不可追溯, 不同时期的 EvaluationReport 无法 cross-compare.

本 ADR 锁定 V1 契约, Wave 4+ 任何 breaking change 须新发 ADR + 升 G\* V2 标识.

## 决策

### 1. Gate 标识 + 阈值锁定 (V1)

| Gate | 名称 | 阈值 | 实现位置 | 依据 |
|---|---|---|---|---|
| **G1** | IC 显著性 | t > 2.5 | `gates/g1_ic_significance.py` | Harvey Liu Zhu 2016 + 铁律 4 |
| **G2** | 相关性过滤 | \|corr\|<0.7 + monthly<0.3 | `gates/g2_corr_filter.py` | 铁律 4 |
| **G3** | Paired bootstrap | p < 0.05 | `gates/g3_paired_bootstrap.py` | 铁律 5 |
| **G4** | WF OOS Sharpe | ≥ baseline | `gates/g4_oos_walkforward.py` | 铁律 8 |
| **G8** | BH-FDR | p ≤ rank/m × 0.05 | `gates/g8_bh_fdr.py` | Harvey Liu Zhu 2016 |
| **G9** | AST Jaccard | < 0.7 | `gates/g9_novelty_ast.py` | AlphaAgent KDD 2025, 铁律 12 |
| **G10** | Hypothesis 长度 | ≥ 20 字 + 非占位符 | `gates/g10_hypothesis.py` | 铁律 13 |
| **G1'** | Strategy Sharpe bootstrap | p < 0.05 | `strategy_gates.py` | 铁律 5 (策略级) |
| **G2'** | Strategy Max DD | ≥ -30% (默认) | `strategy_gates.py` | 风险 budget |
| **G3'** | Strategy regression | max_diff = 0 | `strategy_gates.py` | 铁律 15 (严格) |

**G2' 阈值参数化**: 默认 -0.30, 调用方可通过 `ctx.extra["max_dd_threshold"]` override (e.g. PEAD event-driven 策略可放宽到 -0.40).

**Gate ID 不可变**: `G1_ic_significance` / `G9_novelty_ast` 等 `name` 属性是契约一部分, audit log 直接持久化此 ID. 若未来 V2 升级 (LLM-based G10), 必须新增 `G10_hypothesis_v2` 并行而非替换 V1.

### 2. Pipeline 决策聚合 (V1)

`PlatformEvaluationPipeline.evaluate_full(name)` → `EvaluationReport`:

- **ACCEPT**: 所有 Gate `passed=True`
- **REJECT**: ≥1 hard fail (`passed=False` 且 `details.reason != "data_unavailable"`)
- **WARNING**: ≥1 `data_unavailable`, 无 hard fail (不下定论, 调用方需补数据)

**`gate_internal_error` 归 hard REJECT**: 设计意图 — 基础设施崩溃 (DB timeout / Gate 内部 bug) 时保守 reject, 防 buggy 因子 silently slip 进 active 池. 调用方需 retry 或修 Gate 实现.

### 3. Strategy register() 不 inline wire Gates

**问题**: 设计稿初稿 (Session 42 v2 重构前) 写 "register() wire G1'/G2'/G3' 强制硬门". 实测 G1'/G2'/G3' 需 daily_returns / nav / regression baseline, register() 时只有元数据无法跑.

**决策**: register() 不 inline wire, 通过显式调用流程升 LIVE:

```python
evaluator = PlatformStrategyEvaluator(context_loader=...)
verdict = evaluator.evaluate_strategy(strategy_id, years=5)
if not verdict.passed:
    raise StrategyPromotionBlocked(verdict.blockers, verdict.details)
registry.update_status(strategy_id, StrategyStatus.LIVE, reason="...")
```

**理由**:
- register() 应快速返 (毫秒级 DB upsert), 5min 回测阻塞不可接受
- 全新策略升 LIVE 是低频操作 (单人项目每月 1-2 次), 显式调用清晰
- LIVE 才是真金风险点, DRAFT/BACKTEST/DRY_RUN 不需要 G1'/G2'/G3'

### 4. 全新策略无 baseline 例外

`ctx.extra["no_baseline"] = True` → G3' SKIP (PASS with `reason="no_baseline_first_deployment"`).

**适用场景**: 全新策略首次部署, 无可比 baseline. 后续每次 deploy 必跑 regression (max_diff=0 严格).

### 5. sim_to_real_check (铁律 18)

`PlatformStrategyEvaluator.sim_to_real_check(strategy_id) → Verdict`:
- 阈值 |gap| < 5 bps (basis points, 1 bps = 0.01%)
- 数据来源: ctx.extra["sim_to_real_gap_bps"] (调用方计算回测 vs PT 实盘 NAV 差 → bps)
- 频率: 每季度复核 (CLAUDE.md 铁律 18 已要求)

## 实施状态

- ✅ batch 1 (PR #123): EvaluationPipeline + 7 因子 Gates concrete
- ✅ batch 2 (PR #124): factor_lifecycle 双路径接入, 4 周观察期
- ✅ batch 3 (本 PR): Strategy Gates (G1'/G2'/G3') + StrategyEvaluator + 本 ADR

## V2 路线 (Wave 4+, 不在本 ADR)

- **G5/G6/G7 自动化**: 当前散研究脚本, 留 Wave 4 Observability 升维
- **G10 V2 LLM 一致性检查**: hypothesis ↔ expression 语义对齐 (Claude/DeepSeek API)
- **多因子组合 Gate**: factor portfolio 层评估, 留 MVP 4.x
- **Strategy G4'-G6' 扩展**: regime sensitivity / turnover / 资金容量, 留 Wave 4

任何 V2 升级须新发 ADR + 保 V1 标识不变 (audit 可追溯).

## 风险 + 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 单人项目 Gate 阈值漂移 (e.g. G2' -30% 改 -25%) | 历史 audit 不可比 | 阈值在 ADR 表内锁定, 改动须新发 ADR |
| Wave 4+ 加 G5/G6/G7 触碰 Pipeline 决策聚合逻辑 | breaking change | `_classify_decision` 行为锁定 (本 ADR §2), V2 须新接 method |
| Strategy register() 调用方忘调 evaluate_strategy 直 update_status(LIVE) | 真金未通过硬门 | DBStrategyRegistry 暂不强制 (避免 inline 5min 阻塞), 后续可加 `update_status` 内 check status='evaluating' 先验态 (跨 PR follow-up) |
| Gate ID 重命名 | audit log 不可追溯 | 标识不可变, V2 必新增 (G10 → G10_v2) |

## Follow-up (跨 PR, 不在本 ADR)

1. DBStrategyRegistry.update_status(LIVE) 时强制 check `evaluation_required` 中间态 (MVP 3.5.1)
2. G10 LLM V2 + ADR-014.1 (Wave 4+ Observability LLM 接入后)
3. G5/G6/G7 自动化 + Strategy G4'-G6' 扩展 (Wave 4)
4. `evaluation_log` DB 表持久化 EvaluationReport, audit cross-compare (MVP 4.x)
