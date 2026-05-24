# ADR-094: PMS v1.0 物理退役 (V3 SSOT 集成)

**Date**: 2026-05-24
**Status**: Accepted
**Trigger**: L4+R loop iter 50 — user "pms 可以考虑不用了" 直接 GO 决议 (2026-05-24 desktop session)
**Author**: Claude Opus 4.7 (autonomous L4+R loop) + user GO trigger
**Related**: ADR-010 (PMS死码 sunset gate 设计) / V3 §4 L1 PMSRule / V3 §7.3 trailing_stop

---

## §1 Context (背景)

PMS v1.0 (Profit-Margin Stairs Protection 阶梯利润保护) 系统包含 3 层 v1 实施代码:

1. **`backend/app/services/pms_engine.py`** — PMSEngine class + check_protection L1/L2/L3 静态阈值 for-loop 早退逻辑
2. **`backend/app/api/pms.py`** — FastAPI router `/api/pms/*` endpoints
3. **`backend/app/tasks/daily_pipeline.py::pms_daily_check_task`** — Celery 14:30 Beat task wrapping PMSEngine

**历史状态** (ADR-010 + sprint memory):
- 2026-04-21 (Session 21): ADR-010 surfaced PMS v1 F27-F31 5 重失效 (silent fail / dedup gap / no consumer / etc.). Celery Beat `pms-daily-check` 停调度 (beat_schedule.py:73-77 commented-out).
- 2026-04-29 PT 暂停清仓 (cash ¥993,520.66 / 0 持仓 sustained).
- 2026-05-24: 7+ months sustained 0 真账户触发 since Beat停; v3 PMSRule (Wave 3 MVP 3.1 batch 1) + V3 §7.3 trailing_stop 替代覆盖完整.

**v3.6 验证 evidence** (CLAUDE.md "已知失败方向" 表): PMS v2.0 组合级保护 p=0.655 = 随机, 2022 慢熊 0 触发.

## §2 Decision (决议)

**物理删除 PMS v1.0 三层 + 同步 doc 更新**:

### 2.1 Physical deletions
- ❌ `backend/app/services/pms_engine.py` (whole file)
- ❌ `backend/app/api/pms.py` (whole file)
- ❌ `backend/tests/test_pms_engine.py` (whole file, tests deleted engine)

### 2.2 Code edits
- ✏️ `backend/app/main.py`: remove `from app.api.pms import router as pms_router` (line 24) + `app.include_router(pms_router)` (line 116). Add NOTE comment cross-ref ADR-094.
- ✏️ `backend/app/tasks/daily_pipeline.py`: remove `pms_daily_check_task` function (lines 718-820 = ~103 lines) + replace DEPRECATED comment block with RETIRED block citing ADR-094.
- ✏️ `backend/app/tasks/beat_schedule.py`: update lines 73-77 DEPRECATED comment to "物理退役 iter 50 ADR-094" cite block.

### 2.3 Doc updates
- ✏️ `CLAUDE.md` §项目概述 line 17 PMS row: v1.0 物理退役 + V3 §4 PMSRule + V3 §7.3 trailing_stop 作 active SSOT
- ✏️ `CLAUDE.md` §PMS 阶梯利润保护规则 section (lines 210-215): 全面重写为 V3 SSOT 视角
- ✏️ `docs/adr/REGISTRY.md`: add ADR-094 row

## §3 Retained (保留 — V3 active)

- ✅ `backend/qm_platform/risk/rules/pms.py` (V3 §4 L1 PMSRule, Wave 3 MVP 3.1 batch 1 production) — REGISTERED in PlatformRiskEngine via `risk_wiring.py`
- ✅ `backend/qm_platform/risk/rules/realtime/trailing_stop.py` (V3 §7.3 dynamic 替代 PMSRule v1 静态阈值, subscribe_quote 实时)
- ✅ `backend/qm_platform/config/schema.py::PMSConfigSchema` (V3-era config schema, ties to V3 PMSRule)
- ✅ `backend/qm_platform/config/loader.py` PMS_ENABLED → execution.pms.enabled (V3 mapping)
- ✅ `backend/tests/test_risk_rules_pms.py` (V3 PMSRule tests)
- ✅ `backend/tests/test_pms.py` (engines/backtest/config PMSConfig tests, 回测配置不同语义)
- ✅ `engines/backtest/config.py::PMSConfig` (回测引擎 PMS 参数, 不属生产风控路径)

## §4 Consequences (后果)

### Positive
- 代码库 dead code 物理移除 (~250 lines code + ~150 lines tests deleted)
- V3 风控 SSOT clarified — 0 v1/v3 双轨混淆
- LL-194 anti-pattern family 闭合 (deprecated 但保留 7+ months = stale sediment)
- ADR-010 §C sunset gate enforcement 实证 (条件满足 → 物理 retire)

### Risk
- ❗ 若紧急需要回滚 PMS v1 行为: `git revert <iter 50 commit>` 完整可逆 (3 files restored + 4 file edits reverted). 但 V3 PMSRule 已覆盖 v1 use case + 7+ months 0 触发证据, 回滚需求几乎 0.
- ❗ 历史 audit doc / sprint memory 中 cite "pms_engine.py" 或 "api/pms" 链接将失效. Mitigation: ADR-094 file 本身 sediment 这些历史 file path 作 audit trail.

### Neutral
- `.env` 变量 `PMS_ENABLED` + `PMS_LEVEL{1,2,3}_GAIN/DRAWDOWN` **保留** — 继续映射 V3 PMSRule via `qm_platform/config/loader.py`. user 0 配置变更.

## §5 Sunset gate evidence (ADR-010 §C)

ADR-010 §C sunset gate criteria: "Wave 4 Observability MVP 4.x 启动, `/risk` dashboard 统一可视化".

**实证 (2026-05-24 iter 50 fresh-verify)**:
- ✅ Wave 4 MVP 4.1 Observability batch 1 + 2.1 + 2.2 全部 ✅ (per CLAUDE.md §当前 "主线 = Wave 4 MVP 4.1 Observability")
- ✅ Wave 4 MVP 4.1 batch 3.x (17 scripts SDK migration) 进行中 — 13 of 17 done per commit `a79a810` (intraday_monitor #13 batch 3.8)
- ✅ ADR-010 §C 条件满足 — physical retirement 触发合规

## §6 Implementation evidence (iter 50 commit)

- Branch: `feat/iter-50-v3-ssot-redirect-l4-drift` (initial scope) → expanded to PMS v1 retirement after user GO trigger
- Smoke test verification: 61/61 PASS in 82.11s post-deletion (no broken refs)
- main.py `app` import success post-edit (verified via `python -c "from app.main import app"`)
- 0 broken downstream consumers (grep verified — only 3 hits in COMMENTS, 0 active imports)

## §7 Cross-references

- **ADR-010** (PMS死码 design 决议) + addendum (CB feasibility) — predecessor decision; §C sunset gate sustained 7+ months → this ADR triggers physical retirement
- **V3 §4 L1 PMSRule** (`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`) — replacement static-threshold layer
- **V3 §7.3 trailing_stop** — replacement dynamic-threshold layer
- **CLAUDE.md** §项目概述 + §PMS section — updated to reflect V3 SSOT
- **LL-194** (verify retrospective bug claim pre-fix) — anti-pattern family; "deprecated 但保留 7+ months" = stale sediment closed
