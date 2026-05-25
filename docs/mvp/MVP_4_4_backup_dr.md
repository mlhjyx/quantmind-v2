# MVP 4.4 — Backup & Disaster Recovery (Wave 4 #4, final)

**Status**: 🚧 启动 (iter 73 2026-05-25, entry skeleton shipped, multi-iter single-day campaign target)
**前置**: Wave 4 MVP 4.3 CI/CD ✅ 7/7 = 100% (iter 66-72 完结, 100 cumulative tests)
**Spec source**: [QPB v1.16](../QUANTMIND_PLATFORM_BLUEPRINT.md) §Wave 4 — MVP 4.4 + Framework #12 ROF

---

## §1 范围

最后 1 层生产就绪 — 一致性备份 + 演练过的恢复路径 (不是"有 pg_dump 就够了"):

- **DB**: pg_dump 165GB (TimescaleDB hypertable + 普通表) + WAL archive
- **Filesystem**: parquet cache 43GB + cache/baseline/* + reports/* 关键 artifact
- **Config**: .env (encrypted at rest) + configs/*.yaml + config/hooks/* + Servy 服务定义
- **Restore verification**: 周期性 sample restore + 数据完整性 SQL 校验 + Tier B 风控配置回放
- **RPO/RTO measurement**: 监控备份新鲜度 + 模拟恢复用时, alert via PlatformAlertRouter

## §2 dataclass spec (per QPB §Wave 4 + Framework #12 ROF)

```python
class BackupTarget(StrEnum):
    DB = "db"
    FILESYSTEM = "filesystem"
    CONFIG = "config"

@dataclass(frozen=True)
class BackupTargetResult:
    target: BackupTarget
    passed: bool
    duration_ms: int
    bytes_written: int
    details: dict[str, str]  # e.g. {"artifact_path": "...", "checksum": "..."}

class BackupOrchestrator(Protocol):
    def run_target(self, target: BackupTarget) -> BackupTargetResult: ...
    def run_all(self) -> list[BackupTargetResult]: ...
```

**Distinct from legacy `interface.py` `BackupResult`** (which carries
`backup_id` + `checksum` + `started_at` for cross-run audit). The new
orchestrator dataclass `BackupTargetResult` mirrors `CIResult` shape for
consistency with Wave 4 MVP 4.3 体例.

## §3 模块位置

- `backend/qm_platform/backup/orchestrator.py` — BackupTarget enum + BackupTargetResult + BackupOrchestrator Protocol (NEW)
- `backend/qm_platform/backup/__init__.py` — re-export alongside existing BackupManager / BackupResult / RestoreResult / DisasterRecoveryRunner
- `backend/tests/test_qm_platform_backup_orchestrator.py` — shape + structural typing tests (NEW)

实施分层 sustained: qm_platform 严格隔离 (反 import backend.app.*). 沿用 MVP 4.3 ci/ 体例.

## §4 实施分批 (multi-iter campaign — target single-day per MVP 4.3 precedent)

| Sub-iter | scope | status |
|---|---|---|
| iter 73 (本) | enum + dataclass + Protocol + entry tests | 🚧 |
| iter 74+ | DB backup orchestrator (pg_dump wrapper + retention policy) | pending |
| iter 75+ | filesystem backup orchestrator (parquet + cache/baseline snapshot) | pending |
| iter 76+ | config backup (.env encrypted + configs/*.yaml + hooks settings) | pending |
| iter 77+ | restore verification orchestrator (sample restore + integrity SQL) | pending |
| iter 78+ | RPO/RTO measurement + alert (PlatformAlertRouter dispatch) | pending |
| iter 79+ | Beat schedule wire — daily backup 02:00 SH + weekly verification | pending |

## §5 §6 8-trigger STOP self-check

- ❌ broker write (read-only backup operations)
- ❌ .env mutation (config backup READS .env, does not write)
- ❌ DB schema 改 (backup uses pg_dump, no schema change)
- ❌ 新 Framework (extends existing Framework #12; not counting toward 12 cap)
- ❌ Architecture 级新设计 (incremental orchestrator pattern from MVP 4.3)

ALL NEGATIVE.

## §6 验收

- [ ] BackupTarget enum + BackupTargetResult + Protocol skeleton (iter 73 ✅)
- [ ] DB + Filesystem + Config orchestrators (iter 74-76)
- [ ] Restore verification + RPO/RTO measurement (iter 77-78)
- [ ] Beat schedule wire — daily backup + weekly verification (iter 79)

## §7 关联

- QPB v1.16 §Wave 4 详细 MVP 4.4 spec + Framework #12 ROF
- 铁律 24 (MVP ≤ 2 页 ✅), 31 (Engine 纯计算 — orchestrator skeleton stateless)
- 铁律 33 fail-soft 2-tier (沿用 MVP 4.3 ci/ pattern)
- 铁律 29 (NaN 校验 in restore verification), 30 (cache 一致性 in restore verification)
- MVP 4.1 PlatformAlertRouter SDK (沿用 dispatch for RPO/RTO alerts)
- MVP 4.3 CI orchestrator pattern (CIPhase + CIResult + Protocol — direct precedent)
- Legacy backup/interface.py `BackupManager` + `RestoreResult` + `DisasterRecoveryRunner` 保留 (跨 audit run 沉淀)
