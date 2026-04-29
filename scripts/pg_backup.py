"""pg_dump 自动备份脚本 — 每日凌晨 Task Scheduler 调用。

备份策略 (R6 §6.1):
- 每日全量: pg_dump -Fc → D:/quantmind-v2/backups/daily/quantmind_v2_YYYYMMDD.dump
- 7天滚动: 自动删除7天前的daily备份
- 月度永久: 每月1号额外复制到 backups/monthly/（永久保留）
- Parquet快照: klines_daily + factor_values(前5因子) → backups/parquet/
- 验证: pg_restore --list 检查对象完整性（不真正恢复）
- 日志: logs/backup.log
- 失败时写错误日志 + 钉钉告警（尽力而为）

用法:
    python scripts/pg_backup.py              # 正常备份 + Parquet快照
    python scripts/pg_backup.py --dry-run    # 仅打印命令不执行
    python scripts/pg_backup.py --verify     # 验证最新备份可恢复
    python scripts/pg_backup.py --parquet-only  # 只导出Parquet快照
    python scripts/pg_backup.py --skip-parquet  # 跳过Parquet快照
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

# 项目根目录加入sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

# MVP 4.1 batch 3.7: AlertDispatchError 顶层 import (铁律 33 fail-loud).
from qm_platform.observability import AlertDispatchError  # noqa: E402

if TYPE_CHECKING:
    from qm_platform.observability import AlertRulesEngine

# ── 配置（可通过环境变量覆盖）────────────────────────────
BACKUP_ROOT = PROJECT_ROOT / "backups"
DAILY_DIR = BACKUP_ROOT / "daily"
MONTHLY_DIR = BACKUP_ROOT / "monthly"
PARQUET_DIR = BACKUP_ROOT / "parquet"
LOG_DIR = PROJECT_ROOT / "logs"

PG_BIN = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\16\bin"))
PG_DUMP = PG_BIN / "pg_dump.exe"
PG_RESTORE = PG_BIN / "pg_restore.exe"

DB_NAME = os.environ.get("PG_DBNAME", "quantmind_v2")
DB_USER = os.environ.get("PG_USER", "xin")
DB_HOST = os.environ.get("PG_HOST", "localhost")
DB_PORT = os.environ.get("PG_PORT", "5432")

RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "7"))
# 备份文件最小合法大小: 当前数据~2.8GB，-Fc压缩后预计>100MB
MIN_BACKUP_SIZE_MB = float(os.environ.get("MIN_BACKUP_SIZE_MB", "100"))


# ── 日志 ──────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _logger = logging.getLogger("pg_backup")
    _logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_DIR / "backup.log", encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)
    _logger.addHandler(fh)
    _logger.addHandler(ch)
    return _logger


logger = setup_logging()


# ── 工具 ──────────────────────────────────────────────
def _ensure_dirs() -> None:
    for d in (DAILY_DIR, MONTHLY_DIR, PARQUET_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _pg_env() -> dict:
    env = os.environ.copy()
    # 优先用环境变量PGPASSWORD，其次读.env文件中的密码
    if "PGPASSWORD" not in env:
        env_file = PROJECT_ROOT / "backend" / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATABASE_URL=") or line.startswith("PGPASSWORD="):
                    # 从 postgresql://xin:PASSWORD@localhost/db 提取密码
                    if "://" in line and "@" in line:
                        try:
                            creds = line.split("://")[1].split("@")[0]
                            if ":" in creds:
                                env["PGPASSWORD"] = creds.split(":")[1]
                        except Exception:
                            pass
                    elif line.startswith("PGPASSWORD="):
                        env["PGPASSWORD"] = line.split("=", 1)[1].strip()
    return env


@lru_cache(maxsize=1)
def _load_rules_engine_cached() -> AlertRulesEngine:
    """Inner cached loader: only success cached, raises on yaml load failure.

    P1.2 pattern (batch 3.6 reviewer 沉淀): lru_cache 不缓存 exception, 失败下次
    call 重试. 防 cold-start yaml 缺失场景永久 silent suppression.

    PR #141 P1.1 reviewer 采纳: 显式 return type AlertRulesEngine (success-only,
    failure 路径走 _get_rules_engine 包裹的 None).
    """
    from qm_platform.observability import AlertRulesEngine

    rules_path = PROJECT_ROOT / "configs" / "alert_rules.yaml"
    return AlertRulesEngine.from_yaml(str(rules_path))


def _get_rules_engine() -> AlertRulesEngine | None:
    """AlertRulesEngine 公共 accessor (lru_cache 防 yaml 多次 reload).

    P1.1 pattern: 显式 return type, 让 caller `if engine is not None` 被 mypy 识别.
    P1.2 pattern: 失败 None 不缓存 — 下次调用重新尝试 load.
    """
    try:
        return _load_rules_engine_cached()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Observability] AlertRulesEngine load failed: {e}, fallback")
        return None


def _send_alert_via_platform_sdk(title: str, content: str) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.7).

    pg_backup P0 告警 (备份失败 = DR 链路异常). AlertDispatchError 必传播
    (铁律 33). 调用方 send_alert 包裹.
    """
    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    today_str = str(date.today())
    alert = Alert(
        title=f"[P0] {title}",
        severity=Severity.P0,  # pg_backup 全 P0 (备份失败 = DR 链路风险)
        source="pg_backup",
        details={
            "trade_date": today_str,
            "content": content,
        },
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    router = get_alert_router()
    engine = _get_rules_engine()
    if engine is not None:
        rule = engine.match(alert)
        dedup_key = (
            rule.format_dedup_key(alert)
            if rule
            else f"pg_backup:summary:{today_str}"
        )
        suppress_minutes = rule.suppress_minutes if rule else 5
    else:
        dedup_key = f"pg_backup:summary:{today_str}"
        suppress_minutes = 5

    router.fire(alert, dedup_key=dedup_key, suppress_minutes=suppress_minutes)


def _send_alert_via_legacy_notification(title: str, content: str) -> None:
    """legacy 走 notification_service.send_alert (写 notifications 表).

    向后兼容路径, OBSERVABILITY_USE_PLATFORM_SDK=False 时走此分支.
    """
    from app.services.notification_service import send_alert as _send

    _send("P0", title, content, category="system")


def send_alert(title: str, content: str) -> None:
    """尽力而为的告警，不因告警失败阻塞备份流程 (MVP 4.1 batch 3.7 dispatch).

    settings.OBSERVABILITY_USE_PLATFORM_SDK 控制路径切换. AlertDispatchError 单
    catch (P0 sink failure log+continue, 备份流程不阻塞), 其他 except 仍兜底.
    """
    from app.config import settings

    try:
        if settings.OBSERVABILITY_USE_PLATFORM_SDK:
            _send_alert_via_platform_sdk(title, content)
        else:
            _send_alert_via_legacy_notification(title, content)
    except AlertDispatchError as e:
        # P0 sink failed — log+continue (备份脚本不能因告警失败而中断)
        logger.warning(f"[Observability] AlertDispatchError P0 sink failed: {e}")
    except Exception as e:
        # 其他 (legacy notification_service / DB / 网络) 失败 silent_ok
        logger.warning(f"告警发送失败(不影响备份): {e}")


# ── Step 1: pg_dump 全量备份 ───────────────────────────
def run_backup(dry_run: bool = False) -> Path | None:
    """执行 pg_dump -Fc 全量备份。

    Returns:
        备份文件路径，失败返回 None。
    """
    _ensure_dirs()
    date_str = datetime.now().strftime("%Y%m%d")
    backup_file = DAILY_DIR / f"quantmind_v2_{date_str}.dump"

    cmd = [
        str(PG_DUMP),
        "-h", DB_HOST,
        "-p", DB_PORT,
        "-U", DB_USER,
        "-d", DB_NAME,
        "-Fc",        # 自定义压缩格式（内置压缩，支持 pg_restore 选择性恢复）
        "-Z", "5",    # 压缩级别5（平衡速度和大小）
        "-f", str(backup_file),
    ]
    logger.info(f"备份命令: {' '.join(cmd)}")

    if dry_run:
        logger.info("[DRY-RUN] 跳过实际执行")
        return None

    start = datetime.now()
    try:
        result = subprocess.run(
            cmd, env=_pg_env(), capture_output=True, text=True, timeout=1800,
        )
    except subprocess.TimeoutExpired:
        logger.error("pg_dump 超时(>30分钟)，已终止")
        send_alert("pg_dump备份超时", "pg_dump执行超过30分钟，已终止。请检查数据库状态。")
        return None

    elapsed = (datetime.now() - start).total_seconds()

    if result.returncode != 0:
        logger.error(f"pg_dump 失败(exit={result.returncode}): {result.stderr}")
        send_alert("pg_dump备份失败", f"exit={result.returncode}\n{result.stderr[:500]}")
        return None

    if not backup_file.exists():
        logger.error("备份文件不存在（命令成功但无输出）")
        send_alert("pg_dump备份失败", "备份命令返回0但文件不存在")
        return None

    size_mb = backup_file.stat().st_size / (1024 * 1024)
    logger.info(f"pg_dump 完成: {backup_file.name} ({size_mb:.1f}MB, {elapsed:.0f}秒)")

    if size_mb < MIN_BACKUP_SIZE_MB:
        logger.warning(f"备份文件偏小({size_mb:.1f}MB < {MIN_BACKUP_SIZE_MB}MB)，可能不完整")
        send_alert(
            "pg_dump备份文件偏小",
            f"文件: {backup_file.name}\n大小: {size_mb:.1f}MB (预期>{MIN_BACKUP_SIZE_MB}MB)",
        )

    return backup_file


# ── Step 2: 7天滚动清理 ────────────────────────────────
def cleanup_old_backups() -> int:
    """清理超过保留期的旧备份，返回删除文件数。"""
    if not DAILY_DIR.exists():
        return 0
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    deleted = 0
    for f in sorted(DAILY_DIR.glob("quantmind_v2_*.dump")):
        try:
            date_str = f.stem.split("_")[-1]  # quantmind_v2_20260326 → 20260326
            file_date = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            continue
        if file_date < cutoff:
            f.unlink()
            logger.info(f"已删除过期备份: {f.name}")
            deleted += 1
    if deleted:
        logger.info(f"共删除 {deleted} 个过期备份（保留最近 {RETENTION_DAYS} 天）")
    else:
        logger.info("无过期备份需要清理")
    return deleted


# ── Step 3: 月度永久备份 ───────────────────────────────
def maybe_copy_monthly(daily_path: Path, today: date | None = None) -> bool:
    """如果今天是月初第1天，复制到 monthly/ 目录永久保留。"""
    if today is None:
        today = date.today()
    if today.day != 1:
        return False
    MONTHLY_DIR.mkdir(parents=True, exist_ok=True)
    target = MONTHLY_DIR / daily_path.name
    if target.exists():
        logger.info(f"月度备份已存在，跳过: {target.name}")
        return True
    shutil.copy2(str(daily_path), str(target))
    size_mb = target.stat().st_size / (1024 * 1024)
    logger.info(f"月度备份完成: {target.name} ({size_mb:.1f}MB)")
    return True


# ── Step 4: Parquet 快照 ──────────────────────────────
def export_parquet_snapshots() -> bool:
    """导出 klines_daily 和 factor_values（前5因子，近90天）到 Parquet。"""
    try:
        import pandas as pd
        import psycopg2
    except ImportError as e:
        logger.warning(f"跳过 Parquet 导出（缺少依赖: {e}）")
        return False

    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    today_str = date.today().strftime("%Y%m%d")

    dsn_parts = f"dbname={DB_NAME} user={DB_USER} host={DB_HOST} port={DB_PORT}"
    pg_password = _pg_env().get("PGPASSWORD", "")
    if pg_password:
        dsn_parts += f" password={pg_password}"

    conn = None
    try:
        conn = psycopg2.connect(dsn_parts)
        logger.info("Parquet 快照开始...")

        # klines_daily（全量，最重要的基础数据）
        klines_file = PARQUET_DIR / f"klines_daily_{today_str}.parquet"
        logger.info("导出 klines_daily...")
        df_klines = pd.read_sql(
            "SELECT trade_date, symbol_id, open, high, low, close, volume, amount,"
            " adj_factor, adj_close FROM klines_daily ORDER BY trade_date DESC, symbol_id",
            conn,
        )
        df_klines.to_parquet(klines_file, compression="zstd", index=False)
        logger.info(
            f"klines_daily: {len(df_klines):,} 行 → {klines_file.name}"
            f" ({klines_file.stat().st_size / (1024*1024):.1f}MB)"
        )

        # factor_values（前5个因子，近90天）
        fv_file = PARQUET_DIR / f"factor_values_top5_{today_str}.parquet"
        logger.info("导出 factor_values（前5因子，近90天）...")
        df_fv = pd.read_sql(
            """
            SELECT trade_date, symbol_id, factor_name, value
            FROM factor_values
            WHERE factor_name IN (
                SELECT factor_name FROM factor_values
                GROUP BY factor_name ORDER BY COUNT(*) DESC LIMIT 5
            )
            AND trade_date >= CURRENT_DATE - INTERVAL '90 days'
            ORDER BY trade_date DESC, factor_name, symbol_id
            """,
            conn,
        )
        df_fv.to_parquet(fv_file, compression="zstd", index=False)
        logger.info(
            f"factor_values: {len(df_fv):,} 行 → {fv_file.name}"
            f" ({fv_file.stat().st_size / (1024*1024):.1f}MB)"
        )

        logger.info("Parquet 快照完成")
        return True

    except Exception as exc:
        logger.error(f"Parquet 导出失败: {exc}", exc_info=True)
        return False
    finally:
        if conn:
            conn.close()


# ── Step 5: 恢复验证（仅 --list，不真正恢复）───────────
def verify_backup() -> bool:
    """验证最新备份文件可被 pg_restore 读取（--list 模式）。

    Returns:
        True=验证通过。
    """
    backups = sorted(DAILY_DIR.glob("quantmind_v2_*.dump")) if DAILY_DIR.exists() else []
    if not backups:
        logger.error("无备份文件可验证")
        return False

    latest = backups[-1]
    logger.info(f"验证备份: {latest}")

    try:
        result = subprocess.run(
            [str(PG_RESTORE), "--list", str(latest)],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.error("pg_restore --list 超时(>2分钟)")
        return False

    if result.returncode != 0:
        logger.error(f"备份验证失败: {result.stderr}")
        return False

    table_count = sum(1 for line in result.stdout.splitlines() if " TABLE " in line)
    total_objects = len([ln for ln in result.stdout.splitlines() if ln.strip() and not ln.startswith(";")])
    logger.info(f"验证通过: {latest.name} — {table_count} 个TABLE，{total_objects} 个总对象")

    if table_count < 40:  # 当前43张表，低于40说明有遗漏
        logger.warning(f"TABLE数量偏少({table_count} < 40)，可能有表遗漏")
        return False

    return True


# ── 主流程 ─────────────────────────────────────────────
def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="QuantMind V2 PostgreSQL备份 (R6 §6)")
    parser.add_argument("--dry-run", action="store_true", help="仅打印命令不执行")
    parser.add_argument("--verify", action="store_true", help="验证最新备份")
    parser.add_argument("--parquet-only", action="store_true", help="只导出Parquet快照")
    parser.add_argument("--skip-parquet", action="store_true", help="跳过Parquet快照")
    args = parser.parse_args()

    if args.verify:
        ok = verify_backup()
        sys.exit(0 if ok else 1)

    if args.parquet_only:
        _ensure_dirs()
        ok = export_parquet_snapshots()
        sys.exit(0 if ok else 1)

    logger.info("=" * 60)
    logger.info(f"QuantMind V2 每日备份开始: {date.today().isoformat()}")
    logger.info("=" * 60)

    start_time = datetime.now()

    # Step 1: pg_dump
    backup_file = run_backup(dry_run=args.dry_run)
    if not args.dry_run and backup_file is None:
        logger.error("核心备份失败，流程中止")
        sys.exit(1)

    if backup_file:
        # Step 2: 7天滚动清理
        cleanup_old_backups()

        # Step 3: 月度永久备份
        maybe_copy_monthly(backup_file)

    # Step 4: Parquet 快照
    if not args.dry_run and not args.skip_parquet:
        export_parquet_snapshots()

    # 汇总
    elapsed = (datetime.now() - start_time).total_seconds()
    if backup_file:
        size_mb = backup_file.stat().st_size / (1024 * 1024)
        logger.info(f"备份流程完成: {size_mb:.1f}MB, 总耗时 {elapsed:.0f}秒")
    else:
        logger.info(f"备份流程完成(dry-run), 总耗时 {elapsed:.0f}秒")

    # 列出当前所有daily备份
    if DAILY_DIR.exists():
        backups = sorted(DAILY_DIR.glob("quantmind_v2_*.dump"))
        logger.info(f"当前daily备份({len(backups)}个):")
        for f in backups:
            size_mb = f.stat().st_size / (1024 * 1024)
            logger.info(f"  {f.name} ({size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
