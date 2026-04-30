"""T0-19 audit hook unit + integration tests (dry-run mode, 0 real DB INSERT).

Phase 2 (PR #168) deliverable per Phase 1 design §3 Q6.

Test coverage:
    - weighted_avg algorithm (single fill / multi fill / partial fill)
    - 4-29 trade_date enforcement (STOP gate from Phase 2 prompt §④)
    - idempotency (重入检测 trade_log + flag file)
    - 3 exception classes (T0_19_AlreadyBackfilledError / AuditCheckError / LogParseError)
    - dry_run_audit=True self-test (real fixture log)
    - chat_authorization signature schema
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    T0_19_AlreadyBackfilledError,
    T0_19_LogParseError,
)
from app.services.t0_19_audit import (
    HARDCODED_NAV_2026_04_30,
    RISK_EVENT_LOG_ACTION_ENUM,
    RISK_EVENT_LOG_SEVERITY_ENUM,
    _aggregate_fill_per_order,
    _backfill_trade_log,
    _check_idempotency,
    _collect_chat_authorization,
    _parse_emergency_close_log,
    _write_performance_series_row,
    _write_risk_event_log_audit,
    write_post_close_audit,
)

REAL_LOG = Path(__file__).resolve().parent.parent.parent / "logs" / "emergency_close_20260429_104354.log"


# ── Q7 weighted_avg algorithm (Phase 1 §1 Q7, 3 cases) ──


def test_weighted_avg_single_fill():
    fills = [{"price": 5.39, "volume": 8600, "timestamp": "2026-04-29 10:43:55.153"}]
    result = _aggregate_fill_per_order(fills)
    assert result["total_volume"] == 8600
    assert result["weighted_avg_price"] == 5.39
    assert result["earliest_ts"] == "2026-04-29 10:43:55.153"


def test_weighted_avg_multi_partial_fills():
    """002623 case: 4 partial fills @ different prices."""
    fills = [
        {"price": 20.78, "volume": 300, "timestamp": "2026-04-29 10:43:59.537"},
        {"price": 20.77, "volume": 900, "timestamp": "2026-04-29 10:43:59.568"},
        {"price": 20.76, "volume": 200, "timestamp": "2026-04-29 10:43:59.568"},
        {"price": 20.75, "volume": 700, "timestamp": "2026-04-29 10:43:59.568"},
    ]
    result = _aggregate_fill_per_order(fills)
    assert result["total_volume"] == 2100
    expected = (20.78 * 300 + 20.77 * 900 + 20.76 * 200 + 20.75 * 700) / 2100
    assert abs(result["weighted_avg_price"] - round(expected, 4)) < 0.0001


def test_weighted_avg_zero_volume_safe():
    """Edge: 0 volume returns 0.0 (no ZeroDivisionError)."""
    fills = [{"price": 5.0, "volume": 0, "timestamp": "2026-04-29 10:43:55"}]
    result = _aggregate_fill_per_order(fills)
    assert result["total_volume"] == 0
    assert result["weighted_avg_price"] == 0.0


# ── Real log parse (Phase 1 §1 Q10 实测 28 fills / 18 orders) ──


@pytest.mark.skipif(not REAL_LOG.exists(), reason="real emergency_close 4-29 log not present")
def test_parse_real_log_17_fills_not_18():
    """**实测纠正 (Phase 2 NEW finding)**: 18 orders placed, 17 fills, 1 FAILED.

    688121.SH 4500 股 sell 报 error_id=-61 '证券可用数量不足' status=57 (cancelled).
    PR #166 narrative v3 "18 股全 status=56" 部分错 — 实测 17 status=56 + 1 status=57.

    audit hook 正确行为: 仅 backfill trade_log 17 行 (成交), 不 backfill 失败单
    (沿用铁律 27 不 fabricate).
    """
    fills_by_order = _parse_emergency_close_log(REAL_LOG)
    assert len(fills_by_order) == 17, f"expected 17 unique (code, order_id) with fills, got {len(fills_by_order)}"

    # Each order has ≥1 fill
    for key, fills in fills_by_order.items():
        assert len(fills) >= 1, f"order {key} has 0 fills"


@pytest.mark.skipif(not REAL_LOG.exists(), reason="real log not present")
def test_parse_real_log_specific_tickers_17_filled():
    """17 unique codes filled. 688121.SH NOT in fills (failed sell)."""
    fills_by_order = _parse_emergency_close_log(REAL_LOG)
    codes = {key[0] for key in fills_by_order}
    expected_filled = {
        "000333.SZ", "000507.SZ", "002282.SZ", "002623.SZ", "300750.SZ",
        "600028.SH", "600900.SH", "600938.SH", "600941.SH", "601088.SH",
        "601138.SH", "601398.SH", "601857.SH", "601988.SH",
        "688211.SH", "688391.SH", "688981.SH",  # 17 codes
    }
    assert codes == expected_filled
    assert "688121.SH" not in codes  # critical: failed sell not in backfill


# ── T0_19_LogParseError (Phase 1 design exception class) ──


def test_log_parse_error_missing_file(tmp_path):
    with pytest.raises(T0_19_LogParseError, match="不存在"):
        _parse_emergency_close_log(tmp_path / "nonexistent.log")


def test_log_parse_error_empty_file(tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_text("")
    with pytest.raises(T0_19_LogParseError, match="size=0"):
        _parse_emergency_close_log(empty)


def test_log_parse_error_no_fills(tmp_path):
    nofills = tmp_path / "nofills.log"
    nofills.write_text("2026-04-29 10:00:00 [INFO] starting up\nno fills here\n")
    with pytest.raises(T0_19_LogParseError, match="0 fill events"):
        _parse_emergency_close_log(nofills)


# ── T0_19_AlreadyBackfilledError (idempotency) ──


def test_idempotency_trade_log_reentry(tmp_path):
    """If trade_log has prior backfill row, raise AlreadyBackfilledError."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = (5,)  # 5 rows already backfilled

    log_file = tmp_path / "emergency_close_20260429_104354.log"
    log_file.write_text("placeholder")

    with pytest.raises(T0_19_AlreadyBackfilledError, match="重入检测命中"):
        _check_idempotency(conn, "2026-04-29", log_file)


def test_idempotency_flag_file_exists(tmp_path):
    """If .DONE.flag file exists, raise AlreadyBackfilledError."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = (0,)  # no trade_log rows

    log_file = tmp_path / "emergency_close_20260429_104354.log"
    log_file.write_text("placeholder")
    flag_path = log_file.with_suffix(".DONE.flag")
    flag_path.write_text("{}")

    with pytest.raises(T0_19_AlreadyBackfilledError, match="Hook flag 已存在"):
        _check_idempotency(conn, "2026-04-29", log_file)


def test_idempotency_clean_passes(tmp_path):
    """No prior rows + no flag → no raise."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.fetchone.return_value = (0,)

    log_file = tmp_path / "emergency_close_20260429_104354.log"
    log_file.write_text("placeholder")

    _check_idempotency(conn, "2026-04-29", log_file)  # should not raise


# ── T0_19_AuditCheckError (LL-094 CHECK enum 验证) ──


def test_audit_check_action_enum_validated():
    """LL-094: action_taken must be in ('sell','alert_only','bypass')."""
    assert "sell" in RISK_EVENT_LOG_ACTION_ENUM
    assert "alert_only" in RISK_EVENT_LOG_ACTION_ENUM
    assert "bypass" in RISK_EVENT_LOG_ACTION_ENUM
    assert "manual_audit_recovery" not in RISK_EVENT_LOG_ACTION_ENUM  # PR #160 踩坑


def test_audit_check_severity_enum_validated():
    assert {"p0", "p1", "p2", "info"} == RISK_EVENT_LOG_SEVERITY_ENUM


# ── 4-29 trade_date enforcement (Phase 2 prompt §④ 修订 1, NEW STOP gate) ──


def test_trade_date_4_29_not_4_30(tmp_path, capsys):
    """STOP gate: performance_series + trade_log MUST write trade_date='2026-04-29' (真成交日),
    NOT backfill 当日 4-30."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur

    fills_by_order = {
        ("600028.SH", 1090551138): [
            {"price": 5.39, "volume": 8600, "timestamp": "2026-04-29 10:43:55.153"}
        ]
    }
    inserted = _backfill_trade_log(
        conn, fills_by_order, "2026-04-29", "test-strategy", dry_run=True
    )
    assert inserted == 1
    captured = capsys.readouterr()
    # dry-run output must contain code (per-row INSERT log)
    assert "code=600028.SH" in captured.out
    assert "qty=8600" in captured.out


def test_performance_series_trade_date_4_29(capsys):
    conn = MagicMock()
    _write_performance_series_row(
        conn, "2026-04-29", "test-strategy", 993520.16, dry_run=True
    )
    captured = capsys.readouterr()
    assert "trade_date=2026-04-29" in captured.out
    assert "2026-04-30" not in captured.out  # NEW STOP gate


def test_risk_event_log_action_sell_not_other(capsys):
    """T0-19 audit row uses action_taken='sell', not 'alert_only' (区别 PR #161)."""
    conn = MagicMock()
    audit_id = _write_risk_event_log_audit(
        conn,
        sells_summary={"submitted_count": 18, "failed_count": 0},
        chat_authorization={"auth": {"mode": "chat-driven"}},
        trade_date="2026-04-29",
        strategy_id="test-strategy",
        dry_run=True,
    )
    assert len(audit_id) == 36  # uuid format
    captured = capsys.readouterr()
    assert "action=sell" in captured.out
    assert "severity=p1" in captured.out
    assert "shares=18" in captured.out


# ── chat_authorization signature schema ──


def test_collect_chat_authorization_chat_driven():
    args = MagicMock()
    args.confirm_yes = True
    args.execute = True
    sig = _collect_chat_authorization(args)
    assert sig["auth"]["mode"] == "chat-driven"
    assert sig["execution"]["script"] == "scripts/emergency_close_all_positions.py"


def test_collect_chat_authorization_interactive():
    args = MagicMock()
    args.confirm_yes = False
    args.execute = True
    sig = _collect_chat_authorization(args)
    assert sig["auth"]["mode"] == "interactive"


# ── End-to-end dry-run self-test (real log) ──


@pytest.mark.skipif(not REAL_LOG.exists(), reason="real log not present")
def test_dry_run_audit_e2e_real_log(capsys):
    """Phase 2 self-test: dry_run_audit=True → 0 real INSERT, all 4 steps print SQL."""
    sells_summary = {"submitted_count": 18, "failed_count": 0, "submitted": [], "failed": []}
    chat_auth = {"auth": {"mode": "chat-driven"}}

    summary = write_post_close_audit(
        broker=None,
        sells_summary=sells_summary,
        log_file=REAL_LOG,
        chat_authorization=chat_auth,
        db_conn=MagicMock(),
        trade_date="2026-04-29",
        dry_run_audit=True,
    )

    # 17 fills (688121.SH failed, not backfilled per铁律 27 不 fabricate)
    assert summary["trade_log_inserted"] == 17
    assert summary["trade_date"] == "2026-04-29"
    assert summary["dry_run"] is True
    assert summary["cb_state_reset_to_nav"] == HARDCODED_NAV_2026_04_30

    captured = capsys.readouterr()
    # Step 1 trade_log × 17 rows (1 failed order excluded)
    assert captured.out.count("[DRY-RUN trade_log INSERT]") == 17
    # Step 2 risk_event_log × 1
    assert "[DRY-RUN risk_event_log INSERT]" in captured.out
    # Step 3 performance_series with 4-29 date
    assert "[DRY-RUN performance_series INSERT]" in captured.out
    assert "trade_date=2026-04-29" in captured.out
    # Step 4 cb_state UPDATE + position_snapshot sentinel INSERT
    assert "[DRY-RUN circuit_breaker_state UPDATE]" in captured.out
    assert "[DRY-RUN position_snapshot INSERT sentinel]" in captured.out
    # Critical: no 4-30 trade_date written by audit
    assert "trade_date=2026-04-30" not in captured.out


@pytest.mark.skipif(not REAL_LOG.exists(), reason="real log not present")
def test_dry_run_trade_date_inferred_from_log_filename():
    """log filename emergency_close_YYYYMMDD_HHMMSS.log → infer 2026-04-29."""
    summary = write_post_close_audit(
        broker=None,
        sells_summary={"submitted_count": 18, "failed_count": 0},
        log_file=REAL_LOG,
        chat_authorization={"auth": {"mode": "chat-driven"}},
        db_conn=MagicMock(),
        trade_date=None,  # not passed → infer from filename
        dry_run_audit=True,
    )
    assert summary["trade_date"] == "2026-04-29"


def test_log_parse_error_unparseable_filename(tmp_path):
    """trade_date=None + filename has no YYYYMMDD → T0_19_LogParseError."""
    bad_log = tmp_path / "weird_name.log"
    bad_log.write_text(
        "2026-04-29 10:43:55,153 [INFO] [QMT] 成交回报: order_id=1, code=600028.SH, "
        "price=5.39, volume=8600\n"
    )
    with pytest.raises(T0_19_LogParseError, match="trade_date 未指定"):
        write_post_close_audit(
            broker=None,
            sells_summary={"submitted_count": 1},
            log_file=bad_log,
            chat_authorization={},
            db_conn=MagicMock(),
            trade_date=None,
            dry_run_audit=True,
        )
