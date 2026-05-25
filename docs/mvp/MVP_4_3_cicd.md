# MVP 4.3 — CI/CD Orchestration (Wave 4 #3)

**Status**: 🚧 启动 (iter 66 2026-05-25, entry skeleton shipped, multi-iter 1-2 周 campaign)
**前置**: Wave 4 MVP 4.2 Performance Attribution ✅ 7/7 = 100% (iter 59-65 完结)
**Spec source**: [QPB v1.16](../QUANTMIND_PLATFORM_BLUEPRINT.md) §Wave 4 详细 — MVP 4.3 CI/CD Orchestration

---

## §1 范围

将 git pre-commit / pre-push hooks + GitHub Actions CI + 回归基线门 + reviewer 自动化整合到统一 orchestrator:

- **pre-commit phase**: ruff check / format / pytest collection / check_llm_imports (S2 PR-219 allowlist)
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
| iter 71+ | PR review automation (reviewer findings → PR comments via gh) | pending |
| iter 72+ | GitHub Actions yaml + .github/workflows/ wire | pending |

## §5 §6 8-trigger STOP self-check

- ❌ broker write (build-time tooling, 0 production write)
- ❌ .env / yaml mutation (CI yaml 是 .github/workflows/, sub-iter 7 才入)
- ❌ DB schema 改
- ❌ 新 Framework (CI 是 build/release support, 不计入 12 Framework cap)
- ❌ Architecture 级新设计 (incremental, integrate existing hooks)

ALL NEGATIVE.

## §6 验收

- [ ] CIPhase enum + CIResult dataclass + Protocol skeleton (iter 66 ✅)
- [ ] pre-commit + pre-push orchestrator (iter 67-68)
- [ ] CI matrix + regression gate (iter 69-70)
- [ ] Reviewer automation + GH Actions wire (iter 71-72)

## §7 关联

- QPB v1.16 §Wave 4 详细 MVP 4.3 spec
- 铁律 10b smoke (pre-push 入口已 wire `config/hooks/pre-push`)
- 铁律 15 regression max_diff=0 (`cache/baseline/` 锚点)
- 铁律 17 DataPipeline 入库 (pre-push 现有扫描, LL-066 例外 sanctioned)
- 铁律 24 (MVP ≤ 2 页 ✅), 31 (Engine 纯计算 — orchestrator skeleton stateless)
- MVP 4.1 PlatformAlertRouter SDK pattern (沿用 dispatch 套路 to CI failure notifications)
- MVP 4.2 attribution.py 体例 (Protocol + frozen dataclass + Platform 严格隔离)
