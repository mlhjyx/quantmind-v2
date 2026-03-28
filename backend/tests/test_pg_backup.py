"""单元测试 — scripts/pg_backup.py (R6 §6)

测试范围:
  - run_backup: subprocess mock，成功/失败/超时/文件偏小
  - cleanup_old_backups: 文件系统操作（tmp目录）
  - maybe_copy_monthly: 月初/非月初分支
  - export_parquet_snapshots: psycopg2 + pandas mock
  - verify_backup: pg_restore --list mock

运行:
    pytest backend/tests/test_pg_backup.py -v
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

# 将项目根和scripts加入path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import pg_backup  # noqa: E402  (scripts/pg_backup.py)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_backup_dirs(tmp_path):
    """用临时目录替换备份根目录。"""
    daily = tmp_path / "daily"
    monthly = tmp_path / "monthly"
    parquet = tmp_path / "parquet"
    daily.mkdir(parents=True)
    monthly.mkdir(parents=True)
    parquet.mkdir(parents=True)

    with (
        mock.patch.object(pg_backup, "DAILY_DIR", daily),
        mock.patch.object(pg_backup, "MONTHLY_DIR", monthly),
        mock.patch.object(pg_backup, "PARQUET_DIR", parquet),
        mock.patch.object(pg_backup, "LOG_DIR", tmp_path / "logs"),
        mock.patch.object(pg_backup, "BACKUP_ROOT", tmp_path),
    ):
        yield {"daily": daily, "monthly": monthly, "parquet": parquet, "root": tmp_path}


def _make_dump_file(daily_dir: Path, date_str: str, size_bytes: int = 200 * 1024 * 1024) -> Path:
    """创建假备份文件（填充指定大小）。"""
    f = daily_dir / f"quantmind_v2_{date_str}.dump"
    f.write_bytes(b"x" * min(size_bytes, 1024))  # 实际只写1KB，通过stat mock控制大小
    return f


# ---------------------------------------------------------------------------
# run_backup
# ---------------------------------------------------------------------------

class TestRunBackup:

    def test_success(self, tmp_backup_dirs):
        """pg_dump 成功，返回备份路径。"""
        daily = tmp_backup_dirs["daily"]

        def fake_run(cmd, **kwargs):
            # 模拟 pg_dump 创建输出文件
            out_file = Path(cmd[cmd.index("-f") + 1])
            out_file.write_bytes(b"x" * (150 * 1024 * 1024))  # 150MB
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            return r

        with patch("subprocess.run", side_effect=fake_run):
            result = pg_backup.run_backup(dry_run=False)

        assert result is not None
        assert result.exists()
        assert result.parent == daily
        assert result.name.startswith("quantmind_v2_")
        assert result.suffix == ".dump"

    def test_dry_run_returns_none(self, tmp_backup_dirs):
        """dry_run 模式不执行备份，返回 None。"""
        with patch("subprocess.run") as mock_run:
            result = pg_backup.run_backup(dry_run=True)
        mock_run.assert_not_called()
        assert result is None

    def test_pg_dump_failure(self, tmp_backup_dirs):
        """pg_dump 返回非零退出码，返回 None。"""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "FATAL: database not found"

        with patch("subprocess.run", return_value=mock_result), patch.object(pg_backup, "send_alert"):
            result = pg_backup.run_backup(dry_run=False)

        assert result is None

    def test_timeout(self, tmp_backup_dirs):
        """pg_dump 超时，返回 None 并告警。"""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=1800)), \
             patch.object(pg_backup, "send_alert") as mock_alert:
            result = pg_backup.run_backup(dry_run=False)

        assert result is None
        mock_alert.assert_called_once()
        assert "超时" in mock_alert.call_args[0][0]

    def test_file_too_small_warns(self, tmp_backup_dirs):
        """备份文件偏小时发出警告（但仍返回路径）。"""

        def fake_run_small(cmd, **kwargs):
            out_file = Path(cmd[cmd.index("-f") + 1])
            out_file.write_bytes(b"x" * (50 * 1024 * 1024))  # 50MB < MIN(100MB)
            r = MagicMock()
            r.returncode = 0
            r.stderr = ""
            return r

        with patch("subprocess.run", side_effect=fake_run_small), \
             patch.object(pg_backup, "send_alert") as mock_alert:
            result = pg_backup.run_backup(dry_run=False)

        # 应该仍然返回文件路径（告警但不中断）
        assert result is not None
        # 应发出大小警告
        mock_alert.assert_called_once()
        assert "偏小" in mock_alert.call_args[0][0]


# ---------------------------------------------------------------------------
# cleanup_old_backups
# ---------------------------------------------------------------------------

class TestCleanupOldBackups:

    def test_deletes_old_files(self, tmp_backup_dirs):
        """超过7天的备份文件被删除。"""
        daily = tmp_backup_dirs["daily"]

        # 创建9天前的备份
        old_file = daily / "quantmind_v2_20260319.dump"
        old_file.write_bytes(b"old")

        # 设置文件修改时间为9天前
        old_mtime = (datetime.now() - timedelta(days=9)).timestamp()
        os.utime(old_file, (old_mtime, old_mtime))

        # 创建今日备份（不应被删）
        today_str = datetime.now().strftime("%Y%m%d")
        new_file = daily / f"quantmind_v2_{today_str}.dump"
        new_file.write_bytes(b"new")

        deleted = pg_backup.cleanup_old_backups()

        assert deleted == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_keeps_recent_files(self, tmp_backup_dirs):
        """近期备份不被删除。"""
        daily = tmp_backup_dirs["daily"]

        # 创建3天前的备份
        recent_file = daily / "quantmind_v2_20260325.dump"
        recent_file.write_bytes(b"recent")
        recent_mtime = (datetime.now() - timedelta(days=3)).timestamp()
        os.utime(recent_file, (recent_mtime, recent_mtime))

        deleted = pg_backup.cleanup_old_backups()

        assert deleted == 0
        assert recent_file.exists()

    def test_empty_dir(self, tmp_backup_dirs):
        """空目录不报错，返回0。"""
        deleted = pg_backup.cleanup_old_backups()
        assert deleted == 0

    def test_ignores_unrelated_files(self, tmp_backup_dirs):
        """不删除不匹配命名规则的文件。"""
        daily = tmp_backup_dirs["daily"]
        other = daily / "other_backup.dump"
        other.write_bytes(b"other")
        old_mtime = (datetime.now() - timedelta(days=30)).timestamp()
        os.utime(other, (old_mtime, old_mtime))

        deleted = pg_backup.cleanup_old_backups()
        assert deleted == 0
        assert other.exists()


# ---------------------------------------------------------------------------
# maybe_copy_monthly
# ---------------------------------------------------------------------------

class TestMaybeCopyMonthly:

    def test_copies_on_month_start(self, tmp_backup_dirs):
        """月初（1号）时复制到 monthly/。"""
        daily = tmp_backup_dirs["daily"]
        monthly = tmp_backup_dirs["monthly"]

        dump_file = daily / "quantmind_v2_20260301.dump"
        dump_file.write_bytes(b"x" * 1024)

        first_of_month = date(2026, 3, 1)
        result = pg_backup.maybe_copy_monthly(dump_file, today=first_of_month)

        assert result is True
        assert (monthly / "quantmind_v2_20260301.dump").exists()

    def test_skips_non_month_start(self, tmp_backup_dirs):
        """非月初不复制。"""
        daily = tmp_backup_dirs["daily"]

        dump_file = daily / "quantmind_v2_20260315.dump"
        dump_file.write_bytes(b"x" * 1024)

        mid_month = date(2026, 3, 15)
        result = pg_backup.maybe_copy_monthly(dump_file, today=mid_month)

        assert result is False
        assert not (tmp_backup_dirs["monthly"] / "quantmind_v2_20260315.dump").exists()

    def test_no_double_copy(self, tmp_backup_dirs):
        """月度备份已存在时不重复复制。"""
        daily = tmp_backup_dirs["daily"]
        monthly = tmp_backup_dirs["monthly"]

        dump_file = daily / "quantmind_v2_20260401.dump"
        dump_file.write_bytes(b"original")

        monthly_file = monthly / "quantmind_v2_20260401.dump"
        monthly_file.write_bytes(b"existing")

        first_of_month = date(2026, 4, 1)
        result = pg_backup.maybe_copy_monthly(dump_file, today=first_of_month)

        assert result is True
        # 内容没有被覆盖
        assert monthly_file.read_bytes() == b"existing"


# ---------------------------------------------------------------------------
# verify_backup
# ---------------------------------------------------------------------------

class TestVerifyBackup:

    def test_passes_with_sufficient_tables(self, tmp_backup_dirs):
        """pg_restore --list 返回足够的TABLE条目时验证通过。"""
        daily = tmp_backup_dirs["daily"]
        dump_file = daily / "quantmind_v2_20260328.dump"
        dump_file.write_bytes(b"x" * (150 * 1024 * 1024))

        # 构造有43个TABLE条目的 pg_restore --list 输出
        lines = ["; Archive created at 2026-03-28"]
        for i in range(43):
            lines.append(f"{1000+i}; 2200 {16000+i} TABLE public table_{i} xin")
        for i in range(43):
            lines.append(f"{2000+i}; 2200 {17000+i} TABLE DATA public table_{i} xin")
        for i in range(50):
            lines.append(f"{3000+i}; 2200 {18000+i} INDEX public idx_{i} xin")
        mock_output = "\n".join(lines)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            ok = pg_backup.verify_backup()

        assert ok is True

    def test_fails_with_too_few_tables(self, tmp_backup_dirs):
        """TABLE数量不足时验证失败。"""
        daily = tmp_backup_dirs["daily"]
        dump_file = daily / "quantmind_v2_20260328.dump"
        dump_file.write_bytes(b"x" * (150 * 1024 * 1024))

        # 只有20个TABLE
        lines = ["; Archive"]
        for i in range(20):
            lines.append(f"{1000+i}; 2200 {16000+i} TABLE public table_{i} xin")
        mock_output = "\n".join(lines)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_output
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            ok = pg_backup.verify_backup()

        assert ok is False

    def test_fails_when_no_backups(self, tmp_backup_dirs):
        """无备份文件时返回 False。"""
        ok = pg_backup.verify_backup()
        assert ok is False

    def test_fails_on_pg_restore_error(self, tmp_backup_dirs):
        """pg_restore 命令失败时返回 False。"""
        daily = tmp_backup_dirs["daily"]
        dump_file = daily / "quantmind_v2_20260328.dump"
        dump_file.write_bytes(b"x" * (150 * 1024 * 1024))

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "pg_restore: error: invalid archive"

        with patch("subprocess.run", return_value=mock_result):
            ok = pg_backup.verify_backup()

        assert ok is False

    def test_timeout_returns_false(self, tmp_backup_dirs):
        """pg_restore 超时返回 False。"""
        import subprocess

        daily = tmp_backup_dirs["daily"]
        dump_file = daily / "quantmind_v2_20260328.dump"
        dump_file.write_bytes(b"x" * (150 * 1024 * 1024))

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pg_restore", timeout=120)):
            ok = pg_backup.verify_backup()

        assert ok is False


# ---------------------------------------------------------------------------
# export_parquet_snapshots
# ---------------------------------------------------------------------------

class TestExportParquetSnapshots:

    def test_exports_both_tables(self, tmp_backup_dirs):
        """成功导出 klines_daily 和 factor_values。"""
        import pandas as pd

        parquet_dir = tmp_backup_dirs["parquet"]
        mock_conn = MagicMock()
        mock_df_klines = pd.DataFrame({
            "trade_date": ["2026-03-28"] * 100,
            "symbol_id": list(range(100)),
            "close": [10.0] * 100,
        })
        mock_df_fv = pd.DataFrame({
            "trade_date": ["2026-03-28"] * 50,
            "symbol_id": list(range(50)),
            "factor_name": ["turnover_mean_20"] * 50,
            "value": [0.01] * 50,
        })

        def fake_to_parquet(path, **kwargs):
            # 写入stub文件使 stat() 可以成功
            Path(path).write_bytes(b"x" * 1024)

        with (
            patch.dict("sys.modules", {"psycopg2": MagicMock()}),
            patch("psycopg2.connect", return_value=mock_conn),
            patch("pandas.read_sql", side_effect=[mock_df_klines, mock_df_fv]),
            patch.object(pd.DataFrame, "to_parquet", side_effect=fake_to_parquet) as mock_to_parquet,
        ):
            result = pg_backup.export_parquet_snapshots()

        assert result is True
        assert mock_to_parquet.call_count == 2
        # 验证两个parquet文件都已创建
        today_str = date.today().strftime("%Y%m%d")
        assert (parquet_dir / f"klines_daily_{today_str}.parquet").exists()
        assert (parquet_dir / f"factor_values_top5_{today_str}.parquet").exists()

    def test_handles_missing_psycopg2(self, tmp_backup_dirs):
        """缺少 psycopg2 时优雅退出返回 False。"""
        with patch.dict("sys.modules", {"psycopg2": None}), \
             patch("builtins.__import__", side_effect=ImportError("No module named 'psycopg2'")):
            result = pg_backup.export_parquet_snapshots()
        # ImportError 应被捕获，返回 False 不崩溃
        assert result is False

    def test_handles_db_error(self, tmp_backup_dirs):
        """数据库连接失败时返回 False，不抛异常。"""
        with (
            patch.dict("sys.modules", {"psycopg2": MagicMock()}),
            patch("psycopg2.connect", side_effect=Exception("connection refused")),
        ):
            result = pg_backup.export_parquet_snapshots()

        assert result is False
