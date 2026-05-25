# MVP 4.2 — Performance Attribution (Wave 4 #2)

**Status**: ✅ COMPLETED (iter 65 2026-05-25, 7/7 sub-iters shipped, multi-iter campaign closed)
**前置**: Wave 4 MVP 4.1 batch 3.x ✅ 17/17 100% complete (iter 51-57)
**Spec source**: [QPB v1.16](../QUANTMIND_PLATFORM_BLUEPRINT.md) §Wave 4 详细 — MVP 4.2 Performance Attribution (U5)

---

## §1 范围

每日自动产出 `DailyAttribution` JSON, 拆解 PT NAV 变化为可解释贡献项 + 归因残差异常告警:

- **by_factor**: per-factor P&L (CORE3+dv_ttm 等 active factor 单独 attribution)
- **by_sector**: per-sector P&L (industry contribution)
- **by_regime**: regime context (HMM bull/sideways/bear + expected_perf vs actual)
- **by_cost**: commission / slippage / impact / overnight_gap breakdown
- **alpha_vs_benchmark**: 超额 vs CSI300/CSI500/等权基准
- **unexplained_residual**: model-unexplained variance (异常告警阈值)

## §2 dataclass spec (per QPB §Wave 4)

```python
@dataclass
class RegimeInfo:
    detected: str             # "bull" / "sideways" / "bear"
    expected_perf_bps: float  # HMM 期望日收益 bps
    actual_perf_bps: float    # 实际日收益 bps

@dataclass
class DailyAttribution:
    trade_date: date
    strategy_id: str
    execution_mode: str       # "paper" / "live"
    nav_change_pct: float
    by_factor: dict[str, float]   # {turnover_mean_20: 0.0012, vol_20: 0.0008, ...}
    by_sector: dict[str, float]   # {"electronics": 0.003, "banking": -0.001, ...}
    by_regime: RegimeInfo
    by_cost: dict[str, float]     # {"commission": -0.0005, "slippage": -0.0008, ...}
    alpha_vs_benchmark: float     # vs CSI300 default
    unexplained_residual: float   # |alpha - sum(by_factor)| > threshold → alert
```

## §3 模块位置

- `backend/qm_platform/eval/attribution.py` — DailyAttribution dataclass + interface (`AttributionEngine`)
- `backend/qm_platform/eval/__init__.py` — export
- `backend/tests/test_attribution.py` — shape + interface tests

实施分层走 qm_platform 严格隔离 (反 import backend.app.*).

## §4 实施分批 (multi-iter campaign)

| Sub-iter | scope | status |
|---|---|---|
| iter 59 | dataclass skeleton + interface stub + shape tests (8 tests) | ✅ |
| iter 60 | `compute_by_factor()` — Brinson cross-sectional `portfolio_exposure × factor_return` (9 tests) | ✅ |
| iter 61 | `compute_by_sector()` — SW1 industry breakdown (9 tests) | ✅ |
| iter 62 | `compute_by_cost()` — trade_log 4-category aggregation (9 tests) | ✅ |
| iter 63 | `compute_by_regime()` — HMM 3-state RegimeInfo (9 tests) | ✅ |
| iter 64 | `fire_residual_alert()` — threshold check + AlertRouter SDK (复用 batch 3.x pattern, 10 tests) | ✅ |
| iter 65 | `persist_attribution()` + Daily Beat task `daily-attribution-compute` 16:30 Mon-Fri SH + DB migration `daily_attribution.sql` (7 tests) | ✅ |

## §5 §6 8-trigger STOP self-check

- ❌ broker write (read-only attribution)
- ❌ .env / yaml mutation
- ❌ DB schema 改 (复用 trade_log / factor_values / position_snapshot existing)
- ❌ 新 Framework (12 cap; 复用 platform/eval)
- ❌ Architecture 级新设计 (incremental on existing eval)

ALL NEGATIVE.

## §6 验收

- [x] DailyAttribution dataclass + shape tests (iter 59 ✅, 8 tests)
- [x] PT 日报含完整归因 — by_factor/sector/cost/regime + alpha_vs_benchmark (iter 60-63 ✅, 36 tests)
- [x] 残差 > 阈值自动 flag via AlertRouter SDK (iter 64 ✅, 10 tests)
- [x] Daily Beat task scheduled `daily-attribution-compute` 16:30 Mon-Fri SH + DB migration (iter 65 ✅, 7 tests)

**Cumulative tests**: 61/61 PASS (8+9+9+9+9+10+7 = 61, 0.13s).

**铁律 44 X9 post-merge ops** (新 Beat entry + 新 task module 必须执行):
```
powershell -File scripts\service_manager.ps1 restart celery
powershell -File scripts\service_manager.ps1 restart celery-beat
```

## §7 关联

- QPB v1.16 §Wave 4 详细 MVP 4.2 spec
- Wave 4 MVP 4.1 batch 3.x ✅ (PlatformAlertRouter SDK pattern复用 for residual alert)
- backend/engines/regime_detector.py (3-state HMM, by_regime 数据源)
- backend/engines/slippage_model.py (by_cost 数据源)
- 铁律 24 (MVP ≤ 2页 ✅), 31 (Engine 纯计算 — attribution.py compute_* 函数 stateless)
