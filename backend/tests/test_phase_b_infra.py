"""Phase B 基础设施测试 — B4 DDL对齐 / B5 备份 / B6 健康预检。"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


# ═══════════════════════════════════════════════════
# B4: DDL对齐 — 所有45张DDL表存在于数据库
# ═══════════════════════════════════════════════════

# DDL中定义的45张表
DDL_TABLES = [
    "symbols", "klines_daily", "forex_bars", "daily_basic", "trading_calendar",
    "moneyflow_daily", "northbound_holdings", "margin_data", "chip_distribution",
    "financial_indicators", "index_daily", "index_components",
    "factor_registry", "factor_values", "factor_ic_history",
    "universe_daily", "signals",
    "trade_log", "position_snapshot", "performance_series",
    "model_registry", "ai_parameters", "experiments",
    "strategy", "strategy_configs", "notifications", "notification_preferences",
    "health_checks", "scheduler_task_log",
    "forex_swap_rates", "forex_events",
    "backtest_run", "backtest_daily_nav", "backtest_trades",
    "backtest_holdings", "backtest_wf_windows",
    "factor_evaluation", "factor_mining_task", "mining_knowledge",
    "pipeline_run", "agent_decision_log", "approval_queue", "param_change_log",
    "pipeline_runs", "gp_approval_queue",
]


@pytest.fixture(scope="module")
def db_conn():
    """获取sync psycopg2连接。"""
    from app.services.db import get_sync_conn
    conn = get_sync_conn()
    yield conn
    conn.close()


def test_all_ddl_tables_exist(db_conn):
    """B4: 验证DDL中定义的45张表全部存在于数据库。"""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    db_tables = {row[0] for row in cur.fetchall()}

    missing = [t for t in DDL_TABLES if t not in db_tables]
    assert not missing, f"数据库缺失表: {missing}"
    assert len(DDL_TABLES) == 45, f"DDL表数量不符: {len(DDL_TABLES)} != 45"


def test_mining_knowledge_has_required_columns(db_conn):
    """B4: mining_knowledge表应有Sprint 1.18扩展的所有列。"""
    cur = db_conn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'mining_knowledge'"
    )
    columns = {row[0] for row in cur.fetchall()}
    required = {"factor_hash", "ic_stats", "failure_node", "failure_mode", "run_id", "tags"}
    missing = required - columns
    assert not missing, f"mining_knowledge缺失列: {missing}"


# ═══════════════════════════════════════════════════
# B5: 备份脚本逻辑测试
# ═══════════════════════════════════════════════════

class TestBackupScript:
    """B5: pg_backup.py 逻辑测试（不执行真实pg_dump）。"""

    def test_backup_creates_file(self, tmp_path):
        """mock pg_dump验证文件创建逻辑。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

        # 动态导入避免模块级副作用
        import importlib

        import scripts.pg_backup as backup_mod
        backup_mod = importlib.reload(backup_mod)

        # 覆盖目录到tmp
        backup_mod.DAILY_DIR = tmp_path / "daily"
        backup_mod.MONTHLY_DIR = tmp_path / "monthly"
        backup_mod.PARQUET_DIR = tmp_path / "parquet"
        backup_mod.LOG_DIR = tmp_path / "logs"
        backup_mod.MIN_BACKUP_SIZE_MB = 0  # 测试不检查最小大小

        def fake_run(cmd, **kwargs):
            # 模拟pg_dump: 创建文件
            for i, arg in enumerate(cmd):
                if arg == "-f" and i + 1 < len(cmd):
                    Path(cmd[i + 1]).write_bytes(b"FAKE_DUMP_DATA")
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            result = backup_mod.run_backup(dry_run=False)

        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0
        assert "quantmind_v2_" in result.name

    def test_backup_cleanup_7days(self, tmp_path):
        """验证7天前文件被删除。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import importlib

        import scripts.pg_backup as backup_mod
        backup_mod = importlib.reload(backup_mod)

        daily_dir = tmp_path / "daily"
        daily_dir.mkdir()
        backup_mod.DAILY_DIR = daily_dir
        backup_mod.RETENTION_DAYS = 7

        # 创建10天的备份文件
        today = datetime.now()
        for i in range(10):
            d = today - timedelta(days=i)
            f = daily_dir / f"quantmind_v2_{d.strftime('%Y%m%d')}.dump"
            f.write_bytes(b"data")

        deleted = backup_mod.cleanup_old_backups()

        remaining = list(daily_dir.glob("*.dump"))
        # cutoff = now - 7days, 文件日期 < cutoff 被删除
        # 0-6天前的7个文件保留，7-9天前的3个被删除
        assert len(remaining) == 7
        assert deleted == 3

    def test_monthly_copy_on_first(self, tmp_path):
        """每月1号应复制到monthly目录。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import importlib

        import scripts.pg_backup as backup_mod
        backup_mod = importlib.reload(backup_mod)

        backup_mod.MONTHLY_DIR = tmp_path / "monthly"
        daily_file = tmp_path / "quantmind_v2_20260401.dump"
        daily_file.write_bytes(b"backup_data")

        result = backup_mod.maybe_copy_monthly(daily_file, today=date(2026, 4, 1))
        assert result is True
        assert (tmp_path / "monthly" / "quantmind_v2_20260401.dump").exists()

    def test_monthly_skip_non_first(self, tmp_path):
        """非1号不复制。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import importlib

        import scripts.pg_backup as backup_mod
        backup_mod = importlib.reload(backup_mod)

        backup_mod.MONTHLY_DIR = tmp_path / "monthly"
        daily_file = tmp_path / "quantmind_v2_20260415.dump"
        daily_file.write_bytes(b"backup_data")

        result = backup_mod.maybe_copy_monthly(daily_file, today=date(2026, 4, 15))
        assert result is False


# ═══════════════════════════════════════════════════
# B6: 健康预检测试
# ═══════════════════════════════════════════════════

class TestHealthCheck:
    """B6: health_check.py 逻辑测试。"""

    def test_health_check_all_pass(self):
        """mock全部正常返回all_pass=True。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # check_postgresql only calls execute("SELECT 1"), no fetchone
        # data_freshness: fetchone for prev_trading_day, fetchone for max klines
        # factor_nan: fetchone for max factor date
        mock_cursor.fetchone.side_effect = [
            (date(2026, 3, 27),),          # prev trading day
            (date(2026, 3, 27),),          # max klines date
            (date(2026, 3, 27),),          # max factor date
        ]
        mock_cursor.fetchall.return_value = [
            ("000001", "turnover_mean_20", 0.5),
            ("000002", "volatility_20", -0.3),
        ]

        from scripts.health_check import run_health_check
        with patch("scripts.health_check.check_redis", return_value=(True, "OK")), \
             patch("scripts.health_check.check_celery", return_value=(True, "SKIP")), \
             patch("scripts.health_check.check_disk_space", return_value=(True, "500GB可用")):
            results = run_health_check(
                trade_date=date(2026, 3, 28),
                conn=mock_conn,
                write_db=False,
            )

        assert results["all_pass"] is True
        assert results["postgresql_ok"] is True
        assert results["data_fresh"] is True
        assert results["factor_nan_ok"] is True

    def test_health_check_pg_fail(self):
        """mock PG断连返回all_pass=False。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("connection refused")

        from scripts.health_check import run_health_check
        with patch("scripts.health_check.check_redis", return_value=(True, "OK")), \
             patch("scripts.health_check.check_celery", return_value=(True, "SKIP")), \
             patch("scripts.health_check.check_disk_space", return_value=(True, "500GB可用")), \
             patch("scripts.health_check.check_data_freshness", return_value=(True, "OK")), \
             patch("scripts.health_check.check_factor_nan", return_value=(True, "OK")):
            results = run_health_check(
                trade_date=date(2026, 3, 28),
                conn=mock_conn,
                write_db=False,
            )

        assert results["all_pass"] is False
        assert results["postgresql_ok"] is False

    def test_health_check_redis_fail(self):
        """Redis断连应导致all_pass=False。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (date(2026, 3, 27),),
            (date(2026, 3, 27),),
            (date(2026, 3, 27),),
        ]
        mock_cursor.fetchall.return_value = [
            ("000001", "turnover_mean_20", 0.5),
        ]

        from scripts.health_check import run_health_check
        with patch("scripts.health_check.check_redis", return_value=(False, "Connection refused")), \
             patch("scripts.health_check.check_celery", return_value=(True, "SKIP")), \
             patch("scripts.health_check.check_disk_space", return_value=(True, "500GB可用")):
            results = run_health_check(
                trade_date=date(2026, 3, 28),
                conn=mock_conn,
                write_db=False,
            )

        assert results["all_pass"] is False
        assert results["redis_ok"] is False

    def test_health_check_writes_to_db(self):
        """验证结果写入health_checks表。"""
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [
            (date(2026, 3, 27),),
            (date(2026, 3, 27),),
            (date(2026, 3, 27),),
        ]
        mock_cursor.fetchall.return_value = [
            ("000001", "turnover_mean_20", 0.5),
        ]

        from scripts.health_check import run_health_check
        with patch("scripts.health_check.check_redis", return_value=(True, "OK")), \
             patch("scripts.health_check.check_celery", return_value=(True, "SKIP")), \
             patch("scripts.health_check.check_disk_space", return_value=(True, "500GB可用")):
            run_health_check(
                trade_date=date(2026, 3, 28),
                conn=mock_conn,
                write_db=True,
            )

        # 验证INSERT被调用
        insert_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "INSERT INTO health_checks" in str(c)
        ]
        assert len(insert_calls) == 1
        mock_conn.commit.assert_called_once()
