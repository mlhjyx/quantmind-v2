# PN-002 — Factor Correlation Prune (D1 O10)

> **Loop iteration**: iter 11 (L4+R Inner-loop-B, spec §10 step 3 design)
> **Trigger**: Frontend `triggerCorrelationPrune()` (`frontend/src/api/factors.ts:206`) POSTs to non-existent `/factors/correlation-prune` → 404 today。`FactorLibrary.tsx:76` 已用 `try/catch` graceful fallback,UI 不 panic,但功能不可用(user 看到 "操作失败" toast)。
> **Severity**: Feature-level — §6 8-trigger STOP self-check NEGATIVE(详 §4)
> **§7 重蹈 defense**: PASS — 0 permanent-dead / conditional-fail precedent on UI factor correlation pruning(LL hits 全是 RealtimeRisk CorrelatedDrop;research-kb 都是 factor characterization phase 研究,非 NO-GO 方向)
> **复用 existing infra**:`factor_analyzer.factor_correlation_matrix()` (cross-sectional) + `factors.py:148 GET /correlation` (IC-series Spearman) + `factor_ic_history` mean|IC| + CLAUDE.md doctrine `|corr| > 0.85 → 标记 keep_recommendation=drop, IC较低者`。

## §1 Background

`FactorLibrary.tsx:76` 的 "相关性裁剪" 按钮调用 `triggerCorrelationPrune()` POST `/factors/correlation-prune`(无 body)。Backend 该 endpoint 0,return 404。Frontend `try/catch` graceful fallback,UI 不 panic,但 user 见 toast "操作失败",功能缺失。

**CLAUDE.md §因子审批硬标准 doctrine**:
> 与现有Active因子 corr < 0.7
> `|corr| > 0.85` 的因子对中, IC较低者标记 `keep_recommendation=drop`

## §2 Design choice

### §2.1 Algorithm

1. 取 `factor_registry` status='active' 的全部因子(沿用 `factors.py:180 get_factor_list` 体例)
2. 复用 `factors.py:148 GET /correlation` 的 IC-series Spearman correlation 算法(语义对齐 factor pruning —— 同 IC 时序 ≈ 信号冗余;cross-sectional values 同向 ≠ IC 同向,后者更符合 doctrine 意图)
3. 枚举 pairs `(factor_a, factor_b)` where `|correlation| >= threshold`(默认 0.85,沿用 doctrine)
4. 每个 pair query `factor_ic_history` 取最近窗口的 mean(|ic_1d|)—— IC 较低者 = `drop_recommendation`
5. 返回 report:pairs + drop_recommendations,**0 DB mutation**(dry_run-only this iter)

### §2.2 Endpoint contract

| Method | Path | Body | Response | Status |
|---|---|---|---|---|
| POST | `/api/factors/correlation-prune` | `{ threshold?: float = 0.85, lookback_days?: int = 365, dry_run?: bool = true }` 全部 optional | `{ threshold_used, lookback_days_used, pairs: [...], dropped_count, total_pairs_above_threshold, computed_at }` | 200 / 422 |

- **Auth**:unguarded(沿用 `factors.py:/{name}/archive` sibling POST 体例;localhost-bound 单 user;0 trading-path 触碰)
- **Validation**:
  - `threshold` ∈ `[0.0, 1.0]`(Pydantic `Field(ge=0, le=1)`)
  - `lookback_days` ∈ `[30, 1825]`(5-year max,30-day min)
  - `dry_run` 必须为 `true`(本 iter scope);`dry_run=false` → 422 显式 out-of-scope(反 user 误操作 mutate `factor_registry`)
- **Frontend 0 change**:`factors.ts:206` 已 wired,POST 无 body → 全 default 应用 → 200 with report

### §2.3 Pair structure

```json
{
  "factor_a": "turnover_mean_20",
  "factor_b": "amihud_20",
  "correlation": 0.87,
  "ic_a_mean_abs": 0.024,
  "ic_b_mean_abs": 0.019,
  "drop_recommendation": "factor_b",
  "reason": "|corr|=0.87 > threshold=0.85; ic_b_mean_abs (0.019) < ic_a_mean_abs (0.024) — recommend drop factor_b"
}
```

### §2.4 Edge cases

- **0 active factors**:返回 `{pairs: [], dropped_count: 0, total_pairs_above_threshold: 0}`,不 panic
- **All IC NaN**:correlation matrix 退化 → 返回 0 pairs(defensive,沿用 `factors.py:179-187` try/except 体例)
- **Single active factor**:matrix.shape < (2,2) → 返回 0 pairs
- **Identical IC values**(tied):稳定排序 by factor_name alphabetical,确定性

## §3 Implementation steps(Inner-loop-A,本 design 通过后执行)

1. **Schemas**:`backend/app/schemas/factors.py`(若已有;否则 inline in `api/factors.py`)—— `CorrelationPruneRequest` + `CorrelationPruneResponse` + `CorrelationPair` Pydantic models
2. **Endpoint**:`backend/app/api/factors.py` 末尾追加 `POST /correlation-prune` handler(`async def`,reuse `_get_factor_service` Depends 体例)
3. **Service method**:`backend/app/services/factor_service.py` 加 `analyze_correlation_prune(threshold, lookback_days, dry_run)`(reuse `get_factor_list` + IC-series correlation 算法 + factor_ic_history mean|IC| query)
4. **Tests**:`backend/tests/test_factor_correlation_prune.py` 至少 5 tests:
   - 默认 dry-run 行为(空 body POST → 200 + report)
   - 显式 threshold/lookback_days 覆盖默认值
   - `dry_run=false` → 422
   - 0 active factors edge case
   - threshold/lookback_days 边界值验证(422 on invalid range)
5. **Doc sync**:`docs/API_COVERAGE.md` §6.1 append "O10 resolved iter 11 PR #..."
6. **ADR-DRAFT row 12**:candidate → ADR-088 promote target on merge

## §4 §6 8-trigger STOP self-check —— NEGATIVE

| # | 触发器 | 命中? | 理由 |
|---|---|---|---|
| ① | 真账户 LIVE / broker / 真发单 | ❌ | analysis endpoint,0 trading-path 触碰 |
| ② | 新 trading strategy / risk threshold / factor mining 方法 | ❌ | factor pool ANALYSIS(read + recommend),非 mining 方法 / strategy / risk threshold;`bruteforce_engine._check_correlation` 是 mining 内部独立逻辑,本 endpoint 不复用之 |
| ③ | 修改 5+1 层架构 / Tier A/B / 横切层 边界 | ❌ | 普通 read endpoint |
| ④ | 新增 Framework(12 封顶) | ❌ | 0 framework |
| ⑤ | 新增 governance SSOT 新概念 | ❌ | 0 governance |
| ⑥ | 引入新 DB 表影响交易/风控 | ❌ | 0 新表,纯 read-only analysis |
| ⑦ | 改 risk rule 触发逻辑 | ❌ | 0 risk rule 触碰 |
| ⑧ | 修改 L4R loop 自身安全机制(§1/§4/§5/§6/§9/§14) | ❌ | 0 spec safety touch |

→ **Feature 级**。Proceed to ADR-DRAFT(spec §10 step 4)+ Inner-loop-A implement(step 5)。

## §5 Acceptance criteria

- 默认 `dry_run=true`,response 含 pairs + drop_recommendation 字段齐全
- `threshold=0.85` 时,Active 因子中 `|corr| ≥ 0.85` 的 pair 全部 surface(枚举完整性)
- IC 较低者(lower mean `|ic_1d|`)= `drop_recommendation`(reproducible: 同输入同输出)
- `dry_run=false` → 422 with detail "out of scope this iter"
- 0 active factors → 返回空 pairs(不 panic)
- 0 active factors / single-factor / all-NaN edge cases 不 raise(defensive)
- 5+ backend tests 全绿 + ruff clean + pre-push smoke 61/61
- 0 frontend code change(`factors.ts:206` 已 wired,默认 POST 无 body 即 200)
- 0 红线触碰(self-verify pre-push)

## §6 Out of scope(本 iter,显式 defer)

- **`dry_run=false` 真实 mutation `factor_registry.keep_recommendation`** → defer 到独立 PR + user 显式 approve flow(因为 mutation factor pool 是 governance-level 决议,不应被一次 endpoint click 触发)
- **Frontend UI 整合**(显示 pairs report)→ defer 到独立 frontend PR;当前 `FactorLibrary.tsx:76` try/catch 已 graceful 处理,后续 PR 可改成 toast notification 显示 pairs count
- **Cross-sectional correlation alternative**(用 `factor_analyzer.factor_correlation_matrix` 而非 IC-series)→ defer 评估,本 iter 选 IC-series 因 doctrine alignment 更强

## §7 Risk + rollback

- **Risk 1**:`factor_ic_history` sparse / NaN-heavy → correlation 退化 → 返回 0 pairs。Defensive `try/except` 沿用 factors.py:179-187 体例。
- **Risk 2**:`get_factor_list` 表不存在(早期环境)→ 沿用 existing fallback 返回空列表 → 报告显示 "0 active factors"。
- **Risk 3**:大量 factors(N≈100+)→ O(N²) pair 枚举。Active 因子当前 ~5(CORE3+dv_ttm+1),N² 微观,无性能 concern。
- **Rollback**:删除 endpoint + 测试文件 + service method 即可(0 DDL / 0 migration / 0 frontend change / 0 PR-other-file touch)。

## §8 ScheduleWakeup cadence note(loop infrastructure)

本 design 完成 = iter 11 step 3 闭。step 4 (ADR-DRAFT row 12) + step 5 (Inner-loop-A impl + PR + reviewer + merge) 由下一 turn auto-wake(60s ScheduleWakeup)续做。
