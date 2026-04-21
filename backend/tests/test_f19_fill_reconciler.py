"""F19 Fill Reconciler regression.

Session 21 加时 Part 3 (2026-04-21): 修 `qmt_execution_adapter.py:70 QMT_STATUS[55]=final`
bug 后的补录工具. 本 tests 验证纯函数行为 (正则解析 + 对比输出结构), 不跑真 DB.

实测产出对比详见 `docs/adr/ADR-011-qmt-api-utilization-roadmap.md` + JSON `docs/audit/f19_reconciliation_2026-04-17.json`.
"""
from __future__ import annotations

import io
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIAG_DIR = PROJECT_ROOT / "scripts" / "diag"
if str(DIAG_DIR) not in sys.path:
    sys.path.insert(0, str(DIAG_DIR))

import f19_fill_reconciler as fr  # noqa: E402


class TestFillRegex:
    """成交回报 & 委托回报正则解析."""

    def test_fill_line_parsed(self):
        line = (
            "2026-04-17 09:31:10,369 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=1090520685, code=002441.SZ, price=10.15, volume=1200\n"
        )
        m = fr.FILL_PATTERN.search(line)
        assert m is not None
        assert m.group("order_id") == "1090520685"
        assert m.group("code") == "002441.SZ"
        assert m.group("price") == "10.15"
        assert m.group("volume") == "1200"

    def test_order_status_line_parsed(self):
        line = (
            "2026-04-17 09:31:10,415 [qmt_broker] INFO [QMT] 委托回报: "
            "order_id=1090520685, code=002441.SZ, status=56, traded=4800/4800\n"
        )
        m = fr.ORDER_STATUS_PATTERN.search(line)
        assert m is not None
        assert m.group("status") == "56"
        assert m.group("traded") == "4800"
        assert m.group("total") == "4800"

    def test_non_qmt_line_no_match(self):
        line = "2026-04-17 09:31:10 [other] some unrelated log\n"
        assert fr.FILL_PATTERN.search(line) is None
        assert fr.ORDER_STATUS_PATTERN.search(line) is None


class TestParseQmtFills:
    """parse_qmt_fills 聚合 order_id 行为."""

    def test_multiple_fills_same_order_aggregated(self, tmp_path):
        """同 order_id 多 fill → total_volume 累加 + avg_price 加权平均."""
        log = tmp_path / "qmt.log"
        log.write_text(
            "2026-04-17 09:31:10,369 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=1090520685, code=002441.SZ, price=10.15, volume=1200\n"
            "2026-04-17 09:31:10,415 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=1090520685, code=002441.SZ, price=10.14, volume=3600\n"
            "2026-04-17 09:31:10,415 [qmt_broker] INFO [QMT] 委托回报: "
            "order_id=1090520685, code=002441.SZ, status=56, traded=4800/4800\n",
            encoding="utf-8",
        )
        result = fr.parse_qmt_fills(log, date(2026, 4, 17))
        assert "1090520685" in result
        entry = result["1090520685"]
        assert entry["code"] == "002441.SZ"
        assert entry["fill_count"] == 2
        assert entry["total_volume"] == 4800
        # avg_price = (10.15*1200 + 10.14*3600) / 4800 = 10.1425
        assert abs(entry["avg_price"] - 10.1425) < 0.0001
        assert entry["final_status"] == 56

    def test_date_filter(self, tmp_path):
        """不同日期只保留 target_date."""
        log = tmp_path / "qmt.log"
        log.write_text(
            "2026-04-16 09:31:00,000 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=999, code=X.SZ, price=1.0, volume=100\n"
            "2026-04-17 09:31:00,000 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=1000, code=Y.SZ, price=2.0, volume=200\n",
            encoding="utf-8",
        )
        result = fr.parse_qmt_fills(log, date(2026, 4, 17))
        assert "999" not in result
        assert "1000" in result

    def test_empty_log(self, tmp_path):
        log = tmp_path / "empty.log"
        log.write_text("", encoding="utf-8")
        assert fr.parse_qmt_fills(log, date(2026, 4, 17)) == {}

    def test_missing_log_raises(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            fr.parse_qmt_fills(tmp_path / "nonexistent.log", date(2026, 4, 17))


class TestReconcileOutput:
    """reconcile 输出 JSON 结构 + verdict 分类."""

    def test_output_schema(self, tmp_path, monkeypatch):
        """输出含必须字段, verdict ∈ {EQUAL, DB_LEAKS_QMT, DB_EXCESS_QMT}."""
        # Mock QMT stderr log with one fill
        log = tmp_path / "qmt-data-stderr.log"
        log.write_text(
            "2026-04-17 09:31:10,369 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=1, code=TEST.SZ, price=1.0, volume=100\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(fr, "QMT_STDERR_LOG", log)

        # Mock DB: no rows (DB_LEAKS_QMT scenario — QMT 100 vs DB 0)
        fake_conn = MagicMock()
        fake_cur = MagicMock()
        fake_cur.fetchall.return_value = []
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        monkeypatch.setattr(fr, "get_sync_conn", lambda: fake_conn)

        output_json = tmp_path / "out.json"
        report = fr.reconcile(date(2026, 4, 17), output_json)

        # Schema
        assert report["trade_date"] == "2026-04-17"
        assert report["total_qmt_orders"] == 1
        assert report["total_db_rows"] == 0
        assert report["total_volume_loss_qmt_minus_db"] == 100
        # 当仅有 1 个 code 且 QMT 有而 DB 无 → DB_LEAKS_QMT
        verdicts = {c["verdict"] for c in report["code_diff"]}
        assert "DB_LEAKS_QMT" in verdicts

        # JSON 文件写入
        assert output_json.exists()
        data = json.loads(output_json.read_text(encoding="utf-8"))
        assert data["trade_date"] == "2026-04-17"

    def test_equal_verdict(self, tmp_path, monkeypatch):
        """QMT vol = DB vol → verdict=EQUAL."""
        log = tmp_path / "qmt.log"
        log.write_text(
            "2026-04-17 09:31:10,000 [qmt_broker] INFO [QMT] 成交回报: "
            "order_id=1, code=MATCH.SZ, price=1.0, volume=100\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(fr, "QMT_STDERR_LOG", log)

        fake_conn = MagicMock()
        fake_cur = MagicMock()
        fake_cur.fetchall.return_value = [
            ("MATCH.SZ", "sell", 100, 100, 1.0, None),
        ]
        fake_conn.cursor.return_value.__enter__.return_value = fake_cur
        monkeypatch.setattr(fr, "get_sync_conn", lambda: fake_conn)

        # redirect stdout to avoid noise
        monkeypatch.setattr("sys.stdout", io.StringIO())

        report = fr.reconcile(date(2026, 4, 17), None)
        assert report["total_volume_loss_qmt_minus_db"] == 0
        assert report["codes_with_discrepancy"] == 0
        for c in report["code_diff"]:
            assert c["verdict"] == "EQUAL"
