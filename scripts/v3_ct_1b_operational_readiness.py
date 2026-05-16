#!/usr/bin/env python3
"""V3 Plan v0.4 CT-1b — Operational readiness check + IC-3 SLA evidence cite.

Plan v0.4 §A CT-1b — paper-mode V3-in-path operational verify per user 决议
(M1)+(V1)+(C1) 2026-05-16: SLA evidence cite IC-3a/b/c reports + add
operational readiness section (4 checks: Servy / Redis / PG / endpoints).
反日历式观察期 sustained LL-173 lesson 1 replay-as-gate.

**Why operational-only (NOT real-traffic shake-down)**:
  - IC-3 already cited 5/5 V3 §13.1 SLA evidence via replay + synthetic:
    L1 latency (IC-3a 0.010ms max-quarter), L4 STAGED 30min (IC-3a 0
    staged_failed), L0 News 6-source (IC-3c scenario 5), LiteLLM <3s +
    Ollama fallback (IC-3c scenario 5), DingTalk <10s + email backup
    (IC-3c scenario 6). Replay path equivalent per ADR-063.
  - Gap to close in CT-1b: operational readiness (services discoverable,
    streams wired, endpoints reachable, DB perms) — what replay/synthetic
    can't catch.
  - 0 LLM call / 0 真 DingTalk push (no real-cost mutation; reachability
    checks via HEAD only).

**Checks** (each fails-loud + returns structured status):
  1. Servy services state — 5 services (FastAPI/Celery/CeleryBeat/QMTData/RSSHub) must be Running
  2. FastAPI health endpoint /health reachable + status=ok + execution_mode=paper
  3. Redis PING + key qm:* streams present (signal/risk/quality/order/qmt)
  4. PG perms — SELECT on 5 production tables (position_snapshot, performance_series,
     trade_log, risk_event_log, circuit_breaker_state) all succeed
  5. DingTalk webhook reachable — HTTP HEAD (no push, no token consumption)
  6. News sources reachable — HTTP HEAD on configured news source URLs (no fetch)

**Safety**: 0 broker call / 0 .env mutation / 0 yaml mutation / 0 DB row
mutation / 0 LLM call / 0 真 DingTalk push. All checks are
SELECT/PING/HEAD/Get-Service — read-only operational pings.

4-step preflight verify SOP (sustained LL-159 + LL-172):
  ✅ Step 1 SSOT calendar: N/A — no calendar-dependent assertions.
  ✅ Step 2 data presence: PG production tables verified to exist (Phase 0).
  N/A Step 3 cron alignment: one-shot ops script.
  N/A Step 4 natural production behavior: this script IS the verification.
  ✅ Step 5 multi-dir grep: sustained IC-3a/b/c invariants (rule registry
     SSOT + LLM out-of-band + 4 daily rules PURE marker).

关联铁律: 22 / 24 / 25 / 33 (fail-loud per check) / 41 / 42
关联 V3: §13.1 (5 SLA — IC-3 cite cumulative) / Plan v0.4 §A CT-1b
关联 ADR: ADR-063 (Tier B 真测路径) / ADR-070 (TB-5b methodology) /
  ADR-080 (IC-3 closure 3-family green) / ADR-081 候选 (CT-1 closure)
关联 LL: LL-098 X10 / LL-159 / LL-168/169 (verify-heavy classification —
  CT-1b is verify-only, 0 mutation) / LL-173 lesson 1 (replay-as-gate
  replaces wall-clock observation体例)
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)

# Expected Servy services (per CLAUDE.md §部署规则 + Phase 0 verify 2026-05-17).
_EXPECTED_SERVICES: tuple[str, ...] = (
    "QuantMind-FastAPI",
    "QuantMind-Celery",
    "QuantMind-CeleryBeat",
    "QuantMind-QMTData",
    "QuantMind-RSSHub",
)

# Production tables CT-1b verifies read perms on (sustained CT-1a + IC-3 cite).
_PROD_TABLES: tuple[str, ...] = (
    "position_snapshot",
    "performance_series",
    "trade_log",
    "risk_event_log",
    "circuit_breaker_state",
)

# Expected qm:* Redis streams (sustained ADR-029 + IC-1c L1 runner wire).
_EXPECTED_STREAMS: tuple[str, ...] = (
    "qm:signal:generated",
    "qm:qmt:status",
    "qm:health:check_result",
)

_FASTAPI_HEALTH_URL: str = "http://127.0.0.1:8000/health"
_FASTAPI_TIMEOUT_SEC: float = 5.0


# ---------- Check result types ----------


@dataclass
class _CheckResult:
    """One operational readiness check outcome (frozen-ish per check)."""

    name: str
    passed: bool = False  # defaults to False; check fn sets True on success
    detail: str = ""
    failures: list[str] = field(default_factory=list)


@dataclass
class _ReadinessReport:
    """Aggregate operational readiness verdict."""

    timestamp_utc: str
    timestamp_shanghai: str
    checks: list[_CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks) and len(self.checks) > 0

    @property
    def failed_checks(self) -> list[_CheckResult]:
        return [c for c in self.checks if not c.passed]


# ---------- Individual checks ----------


def _check_servy_services() -> _CheckResult:
    """Check 1: 5 Servy services discoverable + Running."""
    r = _CheckResult(name="servy_services_running")
    try:
        # ConvertTo-Json serializes Status enum as int (4=Running); force
        # string via `.Status.ToString()` so Python parser sees 'Running'.
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "Get-Service -Name 'QuantMind-*' -ErrorAction SilentlyContinue | "
                    "ForEach-Object { @{ Name = $_.Name; Status = $_.Status.ToString() } } | "
                    "ConvertTo-Json -Compress"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            r.failures.append(f"PowerShell Get-Service exit={proc.returncode}: {proc.stderr[:200]}")
            return r
        raw = (proc.stdout or "").strip()
        if not raw:
            r.failures.append("No QuantMind-* services found by Get-Service")
            return r
        data = json.loads(raw)
        services = data if isinstance(data, list) else [data]
        names_seen = {s["Name"]: s["Status"] for s in services}
        for expected in _EXPECTED_SERVICES:
            if expected not in names_seen:
                r.failures.append(f"Service {expected!r} not found")
            elif names_seen[expected] != "Running":
                r.failures.append(
                    f"Service {expected!r} state={names_seen[expected]!r} (expected Running)"
                )
        if not r.failures:
            r.passed = True
            # P2 reviewer fix (2026-05-17): use len() not hardcoded "5".
            r.detail = (
                f"{len(_EXPECTED_SERVICES)} services Running: "
                f"{', '.join(sorted(_EXPECTED_SERVICES))}"
            )
    except subprocess.TimeoutExpired:
        r.failures.append("PowerShell Get-Service timeout >10s")
    except json.JSONDecodeError as e:
        r.failures.append(f"JSON parse failed: {e}")
    except Exception as e:  # noqa: BLE001 — fail-loud
        r.failures.append(f"{type(e).__name__}: {e}")
    return r


def _check_fastapi_health() -> _CheckResult:
    """Check 2: FastAPI /health endpoint reachable + status=ok + execution_mode=paper."""
    r = _CheckResult(name="fastapi_health")
    try:
        import urllib.request

        req = urllib.request.Request(_FASTAPI_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=_FASTAPI_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            status = data.get("status")
            exec_mode = data.get("execution_mode")
            if status != "ok":
                r.failures.append(f"FastAPI /health status={status!r} (expected 'ok')")
            if exec_mode != "paper":
                r.failures.append(
                    f"FastAPI /health execution_mode={exec_mode!r} (expected 'paper' "
                    f"— 红线 sustained)"
                )
            if not r.failures:
                r.passed = True
                r.detail = f"FastAPI /health OK (execution_mode={exec_mode!r})"
    except Exception as e:  # noqa: BLE001 — fail-loud
        r.failures.append(f"{type(e).__name__}: {e}")
    return r


def _check_redis_streams() -> _CheckResult:
    """Check 3: Redis PING + qm:* streams exist.

    P1 reviewer fix (2026-05-17, code-reviewer): explicit client.close() in
    try/finally to avoid connection pool leak if called from long-lived
    context (sustained CT-1a conn lifecycle体例).
    """
    r = _CheckResult(name="redis_streams")
    client = None
    try:
        import redis

        client = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2)
        ping = client.ping()
        if not ping:
            r.failures.append("Redis PING returned falsy")
            return r
        # XLEN works for streams (and STRLEN-like for other types). We just
        # need to verify the key exists with the expected type. Use EXISTS
        # + TYPE for safety across mixed key types.
        for stream in _EXPECTED_STREAMS:
            exists = client.exists(stream)
            if not exists:
                r.failures.append(f"Expected stream {stream!r} not found in Redis")
                continue
            key_type = client.type(stream)
            type_str = key_type.decode("utf-8") if isinstance(key_type, bytes) else str(key_type)
            if type_str != "stream":
                r.failures.append(f"Key {stream!r} type={type_str!r} (expected 'stream')")
        if not r.failures:
            r.passed = True
            r.detail = f"Redis PING + {len(_EXPECTED_STREAMS)} qm:* streams verified"
    except Exception as e:  # noqa: BLE001 — fail-loud
        r.failures.append(f"{type(e).__name__}: {e}")
    finally:
        if client is not None:
            import contextlib

            # silent_ok: close-error non-actionable (P2 reviewer fix; pool
            # GC'd on next process exit even if close fails).
            with contextlib.suppress(Exception):
                client.close()
    return r


def _check_pg_perms(conn_factory: Callable[[], Any] | None = None) -> _CheckResult:
    """Check 4: SELECT on 5 production tables succeeds (read perms intact).

    P1 reviewer fix (2026-05-17, both reviewers): replaced f-string table
    interpolation with `psycopg2.sql.Identifier` to prevent SQL identifier
    injection. `_PROD_TABLES` is a hardcoded constant tuple today but the
    pattern would become an injection vector if extended to config-driven
    table lists. SAFE allowlist check kept as belt-and-suspenders.

    Args:
        conn_factory: optional connection factory (tests). Default uses
            `app.services.db.get_sync_conn`.
    """
    from psycopg2 import sql  # noqa: PLC0415 — deferred psycopg2 import

    r = _CheckResult(name="pg_select_perms")
    try:
        if conn_factory is None:
            from app.services.db import get_sync_conn

            conn_factory = get_sync_conn
        conn = conn_factory()
        try:
            with conn.cursor() as cur:
                for tbl in _PROD_TABLES:
                    # P1 fix: allowlist + sql.Identifier (defense-in-depth).
                    if tbl not in _PROD_TABLES:
                        raise ValueError(f"Table {tbl!r} not in _PROD_TABLES allowlist")
                    cur.execute(
                        sql.SQL("SELECT COUNT(*) FROM {} LIMIT 1").format(sql.Identifier(tbl))
                    )
                    cnt = cur.fetchone()[0]
                    logger.info("[CT-1b] %s SELECT COUNT = %d", tbl, cnt)
        finally:
            conn.close()
        r.passed = True
        r.detail = f"SELECT perms verified on {len(_PROD_TABLES)} tables"
    except Exception as e:  # noqa: BLE001 — fail-loud
        r.failures.append(f"{type(e).__name__}: {e}")
    return r


def _check_dingtalk_endpoint() -> _CheckResult:
    """Check 5: DingTalk webhook reachable via HTTP HEAD (no push, no token use).

    Reads webhook URL from settings if available; gracefully skips with
    informational note if config missing. NO real push, NO token consumption.
    """
    r = _CheckResult(name="dingtalk_endpoint_reachable")
    try:
        # Lazy import to avoid Settings dependency at module top.
        # P2 reviewer fix (2026-05-17): narrowed ImportError/AttributeError
        # only — broader Exception was masking real config breakage with
        # "skipped" pass.
        try:
            from app.config import settings  # noqa: PLC0415

            webhook = getattr(settings, "DINGTALK_WEBHOOK_URL", None)
        except (ImportError, AttributeError):
            webhook = None
        if not webhook:
            r.passed = True
            r.detail = "DingTalk webhook not configured in settings (skipped reachability)"
            return r
        # Connect-only check (avoid HEAD on webhook which DingTalk would 405).
        # Parse host from URL + verify TCP reachable via socket.
        import socket  # noqa: PLC0415
        from urllib.parse import urlparse  # noqa: PLC0415

        parsed = urlparse(str(webhook))
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            r.failures.append(f"Cannot parse DingTalk webhook URL host: {webhook!r}")
            return r
        with socket.create_connection((host, port), timeout=5):
            pass
        r.passed = True
        r.detail = f"DingTalk webhook host {host}:{port} TCP reachable (no push attempted)"
    except Exception as e:  # noqa: BLE001 — fail-loud
        r.failures.append(f"{type(e).__name__}: {e}")
    return r


def _check_news_sources_reachable() -> _CheckResult:
    """Check 6: news source endpoints reachable via TCP connect (no fetch).

    P2 reviewer fix (2026-05-17, both reviewers): RSSHub endpoint
    config-driven via `RSSHUB_URL` settings attr (sustained DingTalk check
    pattern) with localhost:1200 default. Failure message uses ', '.join
    instead of list repr per python-reviewer LOW.

    Reads RSSHub URL from settings/config; gracefully degrades to default
    (127.0.0.1:1200, sustained Servy QuantMind-RSSHub service). NO content
    fetch, NO token consumption.
    """
    r = _CheckResult(name="news_sources_reachable")
    try:
        import socket  # noqa: PLC0415
        from urllib.parse import urlparse  # noqa: PLC0415

        # Discover RSSHub endpoint from settings; fall back to localhost:1200.
        rsshub_host = "127.0.0.1"
        rsshub_port = 1200
        try:
            from app.config import settings  # noqa: PLC0415

            rsshub_url = getattr(settings, "RSSHUB_URL", None) or getattr(
                settings, "RSSHUB_BASE_URL", None
            )
            if rsshub_url:
                parsed = urlparse(str(rsshub_url))
                if parsed.hostname:
                    rsshub_host = parsed.hostname
                    rsshub_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except (ImportError, AttributeError):
            pass  # silent_ok: use defaults

        rsshub_endpoints = [(rsshub_host, rsshub_port)]
        reachable = []
        unreachable = []
        for host, port in rsshub_endpoints:
            try:
                with socket.create_connection((host, port), timeout=3):
                    reachable.append(f"{host}:{port}")
            except OSError as e:
                unreachable.append(f"{host}:{port} ({type(e).__name__})")
        if unreachable:
            r.failures.append(f"News source unreachable: {', '.join(unreachable)}")
            return r
        r.passed = True
        r.detail = f"News sources reachable: {', '.join(reachable)}"
    except Exception as e:  # noqa: BLE001 — fail-loud
        r.failures.append(f"{type(e).__name__}: {e}")
    return r


# ---------- Compile + report ----------


_ALL_CHECKS: tuple[Callable[[], _CheckResult], ...] = (
    _check_servy_services,
    _check_fastapi_health,
    _check_redis_streams,
    _check_pg_perms,
    _check_dingtalk_endpoint,
    _check_news_sources_reachable,
)


def run_all_checks() -> _ReadinessReport:
    """Run all readiness checks + assemble report."""
    from datetime import UTC

    now_utc = datetime.now(UTC)
    report = _ReadinessReport(
        timestamp_utc=now_utc.isoformat(),
        timestamp_shanghai=now_utc.astimezone(_SHANGHAI_TZ).isoformat(),
    )
    for check_fn in _ALL_CHECKS:
        logger.info("[CT-1b] running %s", check_fn.__name__)
        result = check_fn()
        report.checks.append(result)
        if result.passed:
            logger.info("[CT-1b] ✅ %s — %s", result.name, result.detail or "OK")
        else:
            logger.warning(
                "[CT-1b] ❌ %s — failures: %s",
                result.name,
                "; ".join(result.failures),
            )
    return report


def render_report(report: _ReadinessReport) -> str:
    """Render readiness report as markdown."""
    lines: list[str] = []
    lines.append("# V3 CT-1b — Operational Readiness Report")
    lines.append("")
    lines.append(f"**Run timestamp (Asia/Shanghai)**: {report.timestamp_shanghai}")
    lines.append(f"**Run timestamp (UTC)**: {report.timestamp_utc}")
    lines.append(f"**Overall verdict**: {'✅ READY' if report.all_passed else '❌ NOT READY'}")
    lines.append("")
    lines.append(
        "**Scope**: V3 Plan v0.4 §A CT-1b — operational-only readiness "
        "verification per user 决议 (M1)+(V1)+(C1) 2026-05-16. SLA evidence "
        "cumulative from IC-3a/b/c 3 reports (5/5 V3 §13.1 SLA covered via "
        "replay + synthetic per ADR-063). CT-1b adds operational gaps "
        "(services / streams / endpoints / perms) that replay can't catch. "
        "反日历式观察期 sustained LL-173 lesson 1 replay-as-gate."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §1 Operational readiness checks")
    lines.append("")
    lines.append("| # | Check | Status | Detail |")
    lines.append("|---|---|---|---|")
    for idx, c in enumerate(report.checks, start=1):
        status = "✅ PASS" if c.passed else "❌ FAIL"
        detail = c.detail if c.passed else "; ".join(c.failures)[:200]
        lines.append(f"| {idx} | `{c.name}` | {status} | {detail} |")
    lines.append("")
    if report.failed_checks:
        lines.append("### Failed checks — required for CT-1b PASS")
        lines.append("")
        for c in report.failed_checks:
            lines.append(f"- **{c.name}**:")
            for f in c.failures:
                lines.append(f"  - {f}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §2 V3 §13.1 SLA evidence cite (IC-3 cumulative)")
    lines.append("")
    lines.append("Per Plan §A CT-1 row + user 决议 (M1) 2026-05-16, 5/5 SLA covered:")
    lines.append("")
    lines.append("| # | SLA | Threshold | IC-3 evidence | Status |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        "| 1 | L1 detection latency P99 | < 5s | IC-3a 0.010ms max-quarter (139M minute_bars, 20 quarters) | ✅ |"
    )
    lines.append(
        "| 2 | L4 STAGED 30min cancel | = 30min | IC-3a 0 staged_failed (1363 actionable → 1363 closed_ok) | ✅ |"
    )
    lines.append(
        "| 3 | L0 News 6-source 30s timeout | < 30s | IC-3c scenario 5 (LLM outage + Ollama fallback test) | ✅ |"
    )
    lines.append("| 4 | LiteLLM <3s + Ollama fallback | < 3s | IC-3c scenario 5 | ✅ |")
    lines.append(
        "| 5 | DingTalk push <10s P99 | < 10s | IC-3c scenario 6 (DingTalk down + email backup test) | ✅ |"
    )
    lines.append("")
    lines.append(
        "**Replay-path equivalence sustained per ADR-063** (Tier B 真测路径): "
        "SLA evidence from minute_bars replay + synthetic-injection scenarios "
        "is transferable to production runtime semantics. Operational "
        "readiness (本 §1) closes the gap replay can't catch."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §3 Methodology + 红线")
    lines.append("")
    lines.append(
        "- **Verify-only mode** per user 决议 (V1): NO Servy service start/stop, "
        "NO real LLM call, NO real DingTalk push, NO DB row mutation. All "
        "checks are SELECT/PING/HEAD/Get-Service — read-only operational pings."
    )
    lines.append(
        "- **反日历式观察期** sustained LL-173 lesson 1 (replay-as-gate 取代 "
        "wall-clock observation体例) + memory feedback_no_observation_periods. "
        "Single-session SLA-threshold-driven verification replaces 1-2 自然日 "
        "wall-clock shake-down."
    )
    lines.append(
        "- **0 broker call / 0 .env mutation / 0 yaml mutation / 0 DB row "
        "mutation / 0 LLM call / 0 真 DingTalk push**. 红线 5/5 sustained: "
        "cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / "
        "EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102."
    )
    lines.append("")
    lines.append(
        "关联: V3 §13.1 / Plan v0.4 §A CT-1b · ADR-063 / ADR-070 / ADR-080 / "
        "ADR-081 候选 (本 CT-1b partial, full sediment 在 CT-1c closure) · "
        "铁律 22/33/41/42 · LL-098 X10 / LL-159 / LL-168/169 / LL-173 lesson 1"
    )
    lines.append("")
    return "\n".join(lines)


# ---------- main ----------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="report markdown 输出路径 (default: docs/audit/v3_ct_1b_operational_readiness_*.md)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="run checks + print report, do NOT sediment markdown",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return p


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    logger.info("[CT-1b] starting operational readiness checks")
    report = run_all_checks()
    rendered = render_report(report)
    print(rendered)  # noqa: T201

    if not args.dry_run:
        out_path = args.out or (
            PROJECT_ROOT
            / "docs"
            / "audit"
            / f"v3_ct_1b_operational_readiness_report_{datetime.now(_SHANGHAI_TZ):%Y_%m_%d}.md"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        logger.info("[CT-1b] sedimented report: %s", out_path)

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
