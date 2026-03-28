"""灾备恢复验证脚本测试 — QuantMind V2

测试 scripts/disaster_recovery_verify.py 的核心逻辑。
所有测试在 --skip-restore 或 --dry-run 模式运行，不操作生产DB。
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 将 scripts/ 加入 path，使 disaster_recovery_verify 可导入
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import disaster_recovery_verify as drv  # noqa: E402

# ── 测试1: 备份文件查找逻辑 ──────────────────────────────


class TestFindBackupFile:
    def test_explicit_path_exists(self, tmp_path: Path) -> None:
        backup = tmp_path / "quantmind_v2_20260328.dump"
        backup.write_bytes(b"fake")
        result = drv.find_backup_file(backup)
        assert result == backup

    def test_explicit_path_missing_returns_none(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.dump"
        result = drv.find_backup_file(missing)
        assert result is None

    def test_finds_latest_daily(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        daily = tmp_path / "daily"
        daily.mkdir()
        (daily / "quantmind_v2_20260326.dump").write_bytes(b"old")
        (daily / "quantmind_v2_20260328.dump").write_bytes(b"new")

        monkeypatch.setattr(drv, "DAILY_DIR", daily)
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "monthly")

        result = drv.find_backup_file(None)
        assert result is not None
        assert result.name == "quantmind_v2_20260328.dump"

    def test_falls_back_to_monthly_when_no_daily(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monthly = tmp_path / "monthly"
        monthly.mkdir()
        (monthly / "quantmind_v2_20260301.dump").write_bytes(b"monthly")

        monkeypatch.setattr(drv, "DAILY_DIR", tmp_path / "daily_nonexistent")
        monkeypatch.setattr(drv, "MONTHLY_DIR", monthly)

        result = drv.find_backup_file(None)
        assert result is not None
        assert result.name == "quantmind_v2_20260301.dump"

    def test_returns_none_when_no_backups_anywhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(drv, "DAILY_DIR", tmp_path / "daily_empty")
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "monthly_empty")
        result = drv.find_backup_file(None)
        assert result is None


# ── 测试2: 备份完整性验证（mock pg_restore输出）──────────


class TestVerifyBackupIntegrity:
    PG_RESTORE_OUTPUT_GOOD = """\
; Archive created at 2026-03-28 02:00:00 UTC
;     dbname: quantmind_v2
1001; 2200 16384 TABLE public klines_daily xin
1002; 2200 16385 TABLE public factor_values xin
1003; 2200 16386 TABLE public symbols xin
1004; 2200 16387 TABLE public factor_registry xin
1005; 2200 16388 TABLE public trading_calendar xin
1006; 2200 16389 INDEX public klines_daily_pkey xin
1007; 2200 16390 INDEX public factor_values_idx xin
1008; 2200 16391 TABLE DATA public klines_daily xin
"""

    def _make_fake_dump(self, tmp_path: Path, size_bytes: int = 200 * 1024 * 1024) -> Path:
        f = tmp_path / "quantmind_v2_20260328.dump"
        f.write_bytes(b"x" * size_bytes)
        return f

    def test_passes_with_sufficient_tables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = self._make_fake_dump(tmp_path)

        # Build a list output with 42 TABLE entries (enough to pass threshold 40)
        table_lines = "\n".join(
            f"{1000+i}; 2200 {16384+i} TABLE public table_{i} xin" for i in range(42)
        )
        mock_output = f"; Archive header\n{table_lines}\n"

        monkeypatch.setattr(drv, "PG_RESTORE", Path("/fake/pg_restore"))
        with patch("disaster_recovery_verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            with patch.object(Path, "exists", return_value=True):
                ok, info = drv.verify_backup_integrity(backup)

        assert ok is True
        assert info["tables"] == 42
        assert info["errors"] == []

    def test_fails_when_too_few_tables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = self._make_fake_dump(tmp_path)

        # Only 5 tables — below the 40 threshold
        table_lines = "\n".join(
            f"{1000+i}; 2200 {16384+i} TABLE public table_{i} xin" for i in range(5)
        )
        mock_output = f"; Archive header\n{table_lines}\n"

        monkeypatch.setattr(drv, "PG_RESTORE", Path("/fake/pg_restore"))
        with patch("disaster_recovery_verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            with patch.object(Path, "exists", return_value=True):
                ok, info = drv.verify_backup_integrity(backup)

        assert ok is False
        assert info["tables"] == 5
        assert any("TABLE数量不足" in e for e in info["errors"])

    def test_fails_when_pg_restore_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = self._make_fake_dump(tmp_path)

        monkeypatch.setattr(drv, "PG_RESTORE", Path("/fake/pg_restore"))
        with patch("disaster_recovery_verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="pg_restore: error reading archive"
            )
            with patch.object(Path, "exists", return_value=True):
                ok, info = drv.verify_backup_integrity(backup)

        assert ok is False
        assert len(info["errors"]) > 0

    def test_counts_indexes_correctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backup = self._make_fake_dump(tmp_path)

        table_lines = "\n".join(
            f"{1000+i}; 2200 {16384+i} TABLE public table_{i} xin" for i in range(42)
        )
        index_lines = "\n".join(
            f"{2000+i}; 2200 {17000+i} INDEX public idx_{i} xin" for i in range(10)
        )
        mock_output = f"; header\n{table_lines}\n{index_lines}\n"

        monkeypatch.setattr(drv, "PG_RESTORE", Path("/fake/pg_restore"))
        with patch("disaster_recovery_verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            with patch.object(Path, "exists", return_value=True):
                ok, info = drv.verify_backup_integrity(backup)

        assert ok is True
        assert info["indexes"] == 10


# ── 测试3: 报告格式正确性 ────────────────────────────────


class TestReportFormat:
    def test_dry_run_outputs_expected_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        daily = tmp_path / "daily"
        daily.mkdir()
        backup = daily / "quantmind_v2_20260328.dump"
        backup.write_bytes(b"x" * (200 * 1024 * 1024))

        monkeypatch.setattr(drv, "DAILY_DIR", daily)
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "monthly")

        exit_code = drv.run_verification(
            backup_file_arg=None,
            target_db="quantmind_v2_dr_test",
            dry_run=True,
            skip_restore=False,
        )
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "DR-VERIFY" in captured.out
        assert "灾备恢复验证报告" in captured.out
        assert "DRY-RUN" in captured.out
        assert "quantmind_v2_20260328.dump" in captured.out

    def test_no_backup_file_exits_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(drv, "DAILY_DIR", tmp_path / "empty_daily")
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "empty_monthly")

        exit_code = drv.run_verification(
            backup_file_arg=None,
            target_db="quantmind_v2_dr_test",
            dry_run=False,
            skip_restore=True,
        )
        assert exit_code == 1

    def test_fmt_elapsed_formats_correctly(self) -> None:
        assert drv._fmt_elapsed(45.0) == "45秒"
        assert drv._fmt_elapsed(90.0) == "1分30秒"
        assert drv._fmt_elapsed(512.0) == "8分32秒"
        assert drv._fmt_elapsed(0.0) == "0秒"


# ── 测试4: --skip-restore模式 ────────────────────────────


class TestSkipRestoreMode:
    def test_skip_restore_passes_integrity_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        daily = tmp_path / "daily"
        daily.mkdir()
        backup = daily / "quantmind_v2_20260328.dump"
        backup.write_bytes(b"x" * (200 * 1024 * 1024))

        monkeypatch.setattr(drv, "DAILY_DIR", daily)
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "monthly")
        monkeypatch.setattr(drv, "PG_RESTORE", Path("/fake/pg_restore"))

        # Build valid pg_restore output with 43 tables
        table_lines = "\n".join(
            f"{1000+i}; 2200 {16384+i} TABLE public t_{i} xin" for i in range(43)
        )

        with patch("disaster_recovery_verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=f"; header\n{table_lines}\n",
                stderr="",
            )
            with patch.object(Path, "exists", return_value=True):
                exit_code = drv.run_verification(
                    backup_file_arg=None,
                    target_db="quantmind_v2_dr_test",
                    dry_run=False,
                    skip_restore=True,
                )

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "PASS" in captured.out
        assert "skip-restore" in captured.out.lower() or "跳过" in captured.out

    def test_skip_restore_fails_when_integrity_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        daily = tmp_path / "daily"
        daily.mkdir()
        backup = daily / "quantmind_v2_20260328.dump"
        backup.write_bytes(b"x" * (200 * 1024 * 1024))

        monkeypatch.setattr(drv, "DAILY_DIR", daily)
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "monthly")
        monkeypatch.setattr(drv, "PG_RESTORE", Path("/fake/pg_restore"))

        # Only 3 tables — should fail
        table_lines = "\n".join(
            f"{1000+i}; 2200 {16384+i} TABLE public t_{i} xin" for i in range(3)
        )
        with patch("disaster_recovery_verify.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=f"; header\n{table_lines}\n",
                stderr="",
            )
            with patch.object(Path, "exists", return_value=True):
                exit_code = drv.run_verification(
                    backup_file_arg=None,
                    target_db="quantmind_v2_dr_test",
                    dry_run=False,
                    skip_restore=True,
                )

        assert exit_code == 1


# ── 测试5: 无备份文件时的错误处理 ────────────────────────


class TestNoBackupErrorHandling:
    def test_no_backup_dry_run_returns_nonzero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(drv, "DAILY_DIR", tmp_path / "nonexistent")
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "also_nonexistent")

        exit_code = drv.run_verification(
            backup_file_arg=None,
            target_db="quantmind_v2_dr_test",
            dry_run=True,
            skip_restore=False,
        )
        assert exit_code == 1

    def test_explicit_nonexistent_file_returns_nonzero(self, tmp_path: Path) -> None:
        exit_code = drv.run_verification(
            backup_file_arg=tmp_path / "does_not_exist.dump",
            target_db="quantmind_v2_dr_test",
            dry_run=True,
            skip_restore=False,
        )
        assert exit_code == 1

    def test_find_backup_file_returns_none_for_empty_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        empty_daily = tmp_path / "daily"
        empty_daily.mkdir()
        empty_monthly = tmp_path / "monthly"
        empty_monthly.mkdir()

        monkeypatch.setattr(drv, "DAILY_DIR", empty_daily)
        monkeypatch.setattr(drv, "MONTHLY_DIR", empty_monthly)

        result = drv.find_backup_file(None)
        assert result is None

    def test_error_message_printed_when_no_backup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(drv, "DAILY_DIR", tmp_path / "no_daily")
        monkeypatch.setattr(drv, "MONTHLY_DIR", tmp_path / "no_monthly")

        drv.find_backup_file(None)
        captured = capsys.readouterr()
        assert "ERROR" in captured.out or "未找到" in captured.out
