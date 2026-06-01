# MVP 4.3 — CI/CD Orchestration (Wave 4 #3)

**Status**: ✅ COMPLETED (iter 72 2026-05-25, 7/7 sub-iters shipped in single-day campaign)
**前置**: Wave 4 MVP 4.2 Performance Attribution ✅ 7/7 = 100% (iter 59-65 完结)
**Spec source**: [QPB v1.17](../QUANTMIND_PLATFORM_BLUEPRINT.md) §Wave 4 详细 — MVP 4.3 CI/CD Orchestration (iter 77 v1.16→v1.17 Wave 4 closure bump)

---

## §1 范围

将 git pre-commit / pre-push hooks + GitHub Actions CI + 回归基线门 + reviewer 自动化整合到统一 orchestrator:

- **pre-commit phase**: ruff check / format / pytest collection / check_llm_imports (S2 PR-219 allowlist) / frontend API discipline raw-axios scanner
- **pre-push phase**: smoke (铁律 10b) / X10 cutover-bias scan / DataPipeline-only guard (铁律 17)
- **ci-matrix phase**: multi-version Python + PostgreSQL compat
- **regression phase**: max_diff=0 baseline gate (铁律 15, 5yr + 12yr regression)
- **review phase**: reviewer agent findings → PR comments (沿用 OMC code-reviewer agent)

## §2 dataclass spec (per QPB §Wave 4)

```python
class CIPhase(StrEnum):
    PRE_COMMIT = "pre_commit"
    PRE_PUSH = "pre_push"
    CI_MATRIX = "ci_matrix"
    REGRESSION = "regression"
    REVIEW = "review"

@dataclass(frozen=True)
class CIResult:
    phase: CIPhase
    passed: bool
    duration_ms: int
    details: dict[str, str]  # phase-specific output (e.g. {"pytest_summary": "61 PASS 0 FAIL"})

class CIOrchestrator(Protocol):
    def run_phase(self, phase: CIPhase) -> CIResult: ...
    def run_all(self) -> list[CIResult]: ...
```

## §3 模块位置

- `backend/qm_platform/ci/orchestrator.py` — CIPhase enum + CIResult dataclass + CIOrchestrator Protocol
- `backend/qm_platform/ci/__init__.py` — export
- `backend/tests/test_qm_platform_ci_orchestrator.py` — shape + structural typing tests

实施分层走 qm_platform 严格隔离 (反 import backend.app.*). 沿用 MVP 4.1/4.2 体例 — 入口 stateless data classes + Protocol, sub-iter 2+ 才入 subprocess wrapping (本身是 build-time tooling, runtime hooks 走 `config/hooks/` 现有 shell glue).

## §4 实施分批 (multi-iter campaign)

| Sub-iter | scope | status |
|---|---|---|
| iter 66 | dataclass + Protocol + entry tests (14 tests) | ✅ |
| iter 67 | pre-commit orchestrator (ruff + ruff format + pytest collect + check_llm_imports merged, 15 tests) | ✅ |
| iter 68 | pre-push orchestrator (X10 cutover-bias scan + smoke + DataPipeline guard merged, 16 tests) | ✅ |
| iter 69 | CI matrix runner (multi-version Python × PostgreSQL cell iteration, 13 tests) | ✅ |
| iter 70 | Regression baseline gate (max_diff=0 per 铁律 15, 17 tests with compute_max_diff helper) | ✅ |
| iter 71 | PR review automation (reviewer findings → gh PR comments, severity gating P0/P1 block, 17 tests) | ✅ |
| iter 72 | GitHub Actions yaml (`.github/workflows/ci.yml`) + entry script (`scripts/ci_run_phase.py`) + 8 dispatcher tests | ✅ |

## §5 §6 8-trigger STOP self-check

- ❌ broker write (build-time tooling, 0 production write)
- ❌ .env / yaml mutation (CI yaml 是 .github/workflows/, sub-iter 7 才入)
- ❌ DB schema 改
- ❌ 新 Framework (CI 是 build/release support, 不计入 12 Framework cap)
- ❌ Architecture 级新设计 (incremental, integrate existing hooks)

ALL NEGATIVE.

## §6 验收

- [x] CIPhase enum + CIResult dataclass + Protocol skeleton (iter 66 ✅, 14 tests)
- [x] pre-commit + pre-push orchestrator (iter 67-68 ✅, 15+16 = 31 tests)
- [x] CI matrix + regression gate (iter 69-70 ✅, 13+17 = 30 tests)
- [x] Reviewer automation + GH Actions wire (iter 71-72 ✅, 17+8 = 25 tests)

**Cumulative tests**: 100/100 PASS (14+15+16+13+17+17+8 = 100, 单日 multi-iter campaign).

**MVP 4.3 closeout (iter 72)**:
- `.github/workflows/ci.yml` 4 jobs (pre_commit / pre_push / regression / ci_matrix)
- `scripts/ci_run_phase.py` single CLI dispatcher (lazy-imports per phase)
- regression + ci_matrix jobs run `scripts/ci_run_phase.py` as blocking GitHub
  checks; regression validates committed `cache/baseline/regression_result_*.json`
  artifacts with recorded `max_diff=0` evidence.
- `ci_matrix` local smoke execution uses `pytest backend/tests/ -m "smoke and not
  live_tushare" --tb=line -q --timeout=60`; GitHub-hosted matrix sets
  `QM_CI_SMOKE_COLLECT_ONLY=1` for the blocking collect/wiring contract until
  self-hosted runtime services are available.
- `pre_commit` now includes `scripts/audit/check_frontend_api_discipline.py`, a
  comment-aware raw axios scanner that keeps `frontend/src/api/client.ts` as the
  production axios SSOT without flagging tests or prose.

## §7 关联

- QPB v1.16 §Wave 4 详细 MVP 4.3 spec
- 铁律 10b smoke (pre-push 入口已 wire `config/hooks/pre-push`)
- 铁律 15 regression max_diff=0 (`cache/baseline/` 锚点)
- 铁律 17 DataPipeline 入库 (pre-push 现有扫描, LL-066 例外 sanctioned)
- 铁律 24 (MVP ≤ 2 页 ✅), 31 (Engine 纯计算 — orchestrator skeleton stateless)
- MVP 4.1 PlatformAlertRouter SDK pattern (沿用 dispatch 套路 to CI failure notifications)
- MVP 4.2 attribution.py 体例 (Protocol + frozen dataclass + Platform 严格隔离)
