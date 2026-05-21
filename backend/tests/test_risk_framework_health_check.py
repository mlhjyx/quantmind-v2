"""Tests for scripts/risk_framework_health_check.py (Phase 0a, Session 44).

覆盖 _check_task 纯逻辑 (DB 用 mock psycopg2 cursor):
  1. Missing — 窗口 0 runs → P0 finding
  2. Errored — error/retry rows → P1 finding
  3. Stale — last success > max_gap → P1 finding
  4. Under-count — runs < min_per_day → P1 finding
  5. All-green — 期望 row 数 + 全 success + last_success 新鲜 → 0 findings

不测 DingTalk send / argparse / main entrypoint (dry-run 已端到端验证).

注: `risk_framework_health_check.EXPECTED_SCHEDULE` 在 2026-05-19 被清空
(V3 L1 RealtimeRiskEngine 直接订阅 xtquant tick, 取代 Celery-Beat polling;
清空以止住 P0 false-positive 级联, 详 script 内注释 + LL-187). `_check_task`
仍是 live code (schtask 调用), 故本测试用独立的 spec fixture (_DAILY_SPEC /
_INTRADAY_SPEC) 验证其逻辑 — 不依赖 EXPECTED_SCHEDULE 是否已 re-populate,
解除 test ↔ 易变 dict 的脆弱耦合 (此前 9 个 test 因 KeyError 全 fail).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from risk_framework_health_check import (  # noqa: E402
    _check_task,
)

# ── 固定时钟 — 盘后 16:00 CST (08:00 UTC), 避开 earliest_check_utc_hour 误判 ──
# 全部 test 用固定 now_utc + 相对它派生 last_success, 杜绝 datetime.now() 引入的
# wall-clock flake (此前 test_under_count 在 00:00-02:00 UTC 跑会因 too_early
# 跳过 under_count 检查而误 fail).
_AFTER_MARKET = datetime(2026, 4, 29, 8, 0, tzinfo=UTC)  # 16:00 CST

# ── spec fixture — 复刻 EXPECTED_SCHEDULE 清空前的 2 条 entry 形状 ──
# _check_task 读取的键: severity_on_missing / trigger_time / max_gap_minutes
# (必填) + earliest_check_utc_hour / min_per_day / expected_per_day (选填).
_DAILY_SPEC = {
    "severity_on_missing": "P0",
    "trigger_time": "14:30 CST daily",
    "max_gap_minutes": 1500,  # 25h — daily 节奏宽松
    "min_per_day": 1,
    "expected_per_day": 1,
    # earliest_check_utc_hour 故意不设 — daily 盘后检查无 "Beat 首发前早跑" 风险
}
_INTRADAY_SPEC = {
    "severity_on_missing": "P0",
    "trigger_time": "*/5 9-14 CST",
    "max_gap_minutes": 30,
    "min_per_day": 60,
    "expected_per_day": 72,
    "earliest_check_utc_hour": 2,  # 10:00 CST — Beat 首发前不报 missing
}


def _mk_conn(status_counts: dict, last_success: datetime | None):
    """构造 mock psycopg2 conn: cursor.fetchall 返 status counts, fetchone 返 last_success."""
    conn = MagicMock()
    cur = MagicMock()
    # __enter__/__exit__ for cursor context manager (not used in script — uses conn.cursor())
    conn.cursor.return_value = cur

    # 第一次 fetchall (status counts) + 第二次 fetchone (last_success)
    cur.fetchall.return_value = list(status_counts.items())
    cur.fetchone.return_value = (last_success,)
    cur.execute = MagicMock()
    cur.close = MagicMock()
    return conn


def test_missing_returns_p0_finding():
    """窗口 0 runs → P0 missing finding (固定 now at 盘后 16:00 CST = 08:00 UTC,
    避开 earliest_check_utc_hour 误判)."""
    conn = _mk_conn({}, last_success=None)
    findings = _check_task(
        conn,
        "risk_daily_check",
        _DAILY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    assert len(findings) == 1
    assert findings[0].severity == "P0"
    assert findings[0].kind == "missing"
    assert findings[0].task_name == "risk_daily_check"


def test_errored_returns_p1_finding():
    """status in (error, retry) → P1 errored finding."""
    last_ok = _AFTER_MARKET - timedelta(minutes=10)
    conn = _mk_conn(
        {"success": 1, "error": 2, "retry": 1},
        last_success=last_ok,
    )
    findings = _check_task(
        conn,
        "risk_daily_check",
        _DAILY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    # missing 不报 (有 4 runs), errored 报 P1
    assert any(f.severity == "P1" and f.kind == "errored" for f in findings)


def test_stale_returns_p1_finding():
    """last success 早于 max_gap → P1 stale finding."""
    very_old = _AFTER_MARKET - timedelta(hours=2)  # gap 120min > max_gap 30min
    conn = _mk_conn(
        {"success": 60},  # min_per_day satisfied
        last_success=very_old,
    )
    findings = _check_task(
        conn,
        "intraday_risk_check",
        _INTRADAY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    assert any(f.severity == "P1" and f.kind == "stale" for f in findings)


def test_under_count_returns_p1_finding():
    """intraday runs < min_per_day=60 → P1 under_count.

    用固定 _AFTER_MARKET (08:00 UTC > earliest_check_utc_hour=2) 而非
    datetime.now() — 否则 00:00-02:00 UTC 跑时 too_early 会跳过 under_count
    检查导致误 fail (历史 wall-clock flake 根因)."""
    last_ok = _AFTER_MARKET - timedelta(minutes=5)
    conn = _mk_conn(
        {"success": 30},  # 30 < 60
        last_success=last_ok,
    )
    findings = _check_task(
        conn,
        "intraday_risk_check",
        _INTRADAY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    assert any(f.severity == "P1" and f.kind == "under_count" for f in findings)


def test_all_green_returns_no_findings():
    """期望 row 数 + 全 success + 新鲜 → 0 findings."""
    last_ok = _AFTER_MARKET - timedelta(minutes=5)  # 新鲜
    conn = _mk_conn(
        {"success": 1},  # daily 期望 1
        last_success=last_ok,
    )
    findings = _check_task(
        conn,
        "risk_daily_check",
        _DAILY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    assert findings == []


def test_intraday_all_green_returns_no_findings():
    """intraday 60+ runs + 全 success + 新鲜 → 0 findings."""
    last_ok = _AFTER_MARKET - timedelta(minutes=5)
    conn = _mk_conn(
        {"success": 70, "skipped": 2},  # 72 ≥ 60 min
        last_success=last_ok,
    )
    findings = _check_task(
        conn,
        "intraday_risk_check",
        _INTRADAY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    assert findings == []


def test_naive_last_success_handled():
    """last_success 无 tzinfo 时, 内部应补 UTC 不 raise."""
    naive = (_AFTER_MARKET - timedelta(minutes=5)).replace(tzinfo=None)  # no tzinfo
    conn = _mk_conn({"success": 1}, last_success=naive)
    # 不应 raise (内部 if last_success.tzinfo is None: 补 UTC)
    findings = _check_task(
        conn,
        "risk_daily_check",
        _DAILY_SPEC,
        _AFTER_MARKET,
        window_hours=24,
    )
    # 期望不 raise + 结果合理 (1 success / 5min ago, max_gap 25h → 不 stale)
    assert all(f.kind != "stale" for f in findings)


def test_too_early_skip_missing_intraday():
    """P2 reviewer 采纳 (PR #145): now_utc 早于 earliest_check_utc_hour 时,
    intraday 0 runs 不应误报 P0 missing.

    intraday earliest_check_utc_hour=2 (10:00 CST). now=01:00 UTC = 09:00 CST,
    Beat 09:00 刚启, 0 row 是正常的 — 不应报 missing.
    """
    early_now = datetime(2026, 4, 29, 1, 0, tzinfo=UTC)  # 01:00 UTC
    conn = _mk_conn({}, last_success=None)
    findings = _check_task(
        conn,
        "intraday_risk_check",
        _INTRADAY_SPEC,
        early_now,
        window_hours=24,
    )
    # 不应报 missing (too_early), 也不应 under_count (total=0 + too_early)
    assert not any(f.kind == "missing" for f in findings)
    assert not any(f.kind == "under_count" for f in findings)


def test_normal_hour_reports_missing_intraday():
    """too_early guard 不阻碍正常时段的 missing 检测."""
    conn = _mk_conn({}, last_success=None)
    findings = _check_task(
        conn,
        "intraday_risk_check",
        _INTRADAY_SPEC,
        _AFTER_MARKET,  # 08:00 UTC = 16:00 CST, 盘后 (> earliest_check 2)
        window_hours=24,
    )
    # 期望: 正常时段 0 row → P0 missing 应报
    assert any(f.severity == "P0" and f.kind == "missing" for f in findings)
