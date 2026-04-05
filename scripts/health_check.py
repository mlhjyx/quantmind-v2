#!/usr/bin/env python3
"""健康预检脚本 — Paper Trading日链路第一步。

CLAUDE.md要求: 任何一项失败 → P0告警 + 暂停当日链路。
检查项:
  ✓ PostgreSQL连接
  ✓ Redis连接
  ✓ 昨日数据已更新
  ✓ 因子计算无NaN（抽样）
  ✓ 磁盘空间 > 10GB
  ✓ Celery worker在线（可选）
"""

import os
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

# Windows UTF-8 输出修复（兼容Git Bash管道模式）
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn


def check_postgresql(conn) -> tuple[bool, str]:
    """PostgreSQL连接测试。"""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        return True, "OK"
    except Exception as e:
        return False, str(e)


def check_data_freshness(conn, trade_date: date) -> tuple[bool, str]:
    """数据新鲜度: klines_daily最新日期 == 上一交易日。"""
    try:
        cur = conn.cursor()
        # 获取trade_date之前的最近交易日
        cur.execute(
            """SELECT MAX(trade_date) FROM trading_calendar
               WHERE market = 'astock' AND is_trading_day = TRUE
                 AND trade_date < %s""",
            (trade_date,),
        )
        prev_trading_day = cur.fetchone()[0]

        cur.execute("SELECT MAX(trade_date) FROM klines_daily")
        max_klines_date = cur.fetchone()[0]

        if max_klines_date is None:
            return False, "klines_daily表为空"

        if max_klines_date >= prev_trading_day:
            return True, f"最新={max_klines_date}, 上一交易日={prev_trading_day}"
        else:
            return (
                False,
                f"数据过期: klines最新={max_klines_date}, 期望>={prev_trading_day}",
            )
    except Exception as e:
        return False, str(e)


def check_factor_nan(conn, trade_date: date) -> tuple[bool, str]:
    """因子NaN抽样检查: 最近一日10只股票。"""
    try:
        cur = conn.cursor()
        # 找最近有因子数据的日期
        cur.execute(
            """SELECT MAX(trade_date) FROM factor_values
               WHERE trade_date <= %s""",
            (trade_date,),
        )
        latest_factor_date = cur.fetchone()[0]
        if latest_factor_date is None:
            return False, "factor_values表为空"

        # 抽样10只
        cur.execute(
            """SELECT code, factor_name, zscore
               FROM factor_values
               WHERE trade_date = %s
               ORDER BY RANDOM() LIMIT 50""",
            (latest_factor_date,),
        )
        rows = cur.fetchall()
        nan_count = sum(1 for r in rows if r[2] is None)

        if nan_count == 0:
            return True, f"date={latest_factor_date}, 抽样50行无NaN"
        elif nan_count < 5:
            return True, f"date={latest_factor_date}, {nan_count}/50 NaN(可接受)"
        else:
            return False, f"date={latest_factor_date}, {nan_count}/50 NaN(过多)"
    except Exception as e:
        return False, str(e)


def check_disk_space() -> tuple[bool, str]:
    """磁盘空间 > 10GB。"""
    try:
        usage = shutil.disk_usage("D:\\")
        free_gb = usage.free / (1024**3)
        if free_gb >= 10:
            return True, f"{free_gb:.1f}GB可用"
        else:
            return False, f"仅{free_gb:.1f}GB可用(<10GB)"
    except Exception as e:
        return False, str(e)


def check_redis() -> tuple[bool, str]:
    """Redis连接测试。"""
    try:
        import redis
        r = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=3,
        )
        r.ping()
        info = r.info("memory")
        used_mb = info.get("used_memory", 0) / (1024 * 1024)
        return True, f"OK (内存{used_mb:.1f}MB)"
    except ImportError:
        return True, "SKIP(redis包未安装，不阻断)"
    except Exception as e:
        return False, str(e)


def check_celery() -> tuple[bool, str]:
    """检查Celery worker是否在线（可选，未启动不阻断）。"""
    try:
        from app.tasks.celery_app import celery_app
        inspector = celery_app.control.inspect(timeout=3)
        active = inspector.active_queues()
        if active:
            worker_count = len(active)
            return True, f"{worker_count}个worker在线"
        else:
            return True, "SKIP(无worker在线，不阻断)"
    except Exception as e:
        return True, f"SKIP(Celery检查异常: {e})"


def check_qmt_connection() -> tuple[bool, str]:
    """miniQMT连接检查（仅EXECUTION_MODE=live时调用）。"""
    try:
        from app.services.qmt_connection_manager import qmt_manager

        health = qmt_manager.health_check()
        if health.get("is_healthy"):
            asset = health.get("account_asset", {})
            total = asset.get("total_asset", 0)
            return True, f"已连接, 总资产={total:.0f}"
        else:
            return False, f"状态={health['state']}, error={health.get('last_error', '')}"
    except Exception as e:
        return False, f"QMT检查异常: {e}"


def run_health_check(
    trade_date: date | None = None,
    conn=None,
    write_db: bool = True,
) -> dict[str, bool]:
    """执行全部健康检查。

    Args:
        trade_date: 检查日期（默认今天）
        conn: psycopg2连接
        write_db: 是否写入health_checks表

    Returns:
        {check_name: passed} 字典
    """
    if trade_date is None:
        trade_date = date.today()

    own_conn = conn is None
    if own_conn:
        conn = _get_sync_conn()

    results = {}
    failed_items = []

    # 执行各项检查
    checks = [
        ("postgresql_ok", check_postgresql, (conn,)),
        ("redis_ok", check_redis, ()),
        ("data_fresh", check_data_freshness, (conn, trade_date)),
        ("factor_nan_ok", check_factor_nan, (conn, trade_date)),
        ("disk_ok", check_disk_space, ()),
        ("celery_ok", check_celery, ()),
    ]

    for name, func, args in checks:
        ok, msg = func(*args)
        results[name] = ok
        status = "OK" if ok else "FAIL"
        print(f"  {status} {name}: {msg}", flush=True)
        if not ok:
            failed_items.append(f"{name}: {msg}")

    # QMT连接检查（仅EXECUTION_MODE=live时）
    try:
        from app.config import settings
        if settings.EXECUTION_MODE == "live":
            qmt_ok, qmt_msg = check_qmt_connection()
            results["qmt_ok"] = qmt_ok
            status = "OK" if qmt_ok else "FAIL"
            print(f"  {status} qmt_ok: {qmt_msg}", flush=True)
            if not qmt_ok:
                failed_items.append(f"qmt_ok: {qmt_msg}")
        else:
            results["qmt_ok"] = True  # paper模式跳过
    except Exception as e:
        results["qmt_ok"] = True  # 导入失败不阻断（paper模式兼容）
        print(f"  SKIP qmt_ok: 导入失败({e})", flush=True)

    all_pass = all(results.values())
    results["all_pass"] = all_pass

    # 写入DB
    if write_db:
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO health_checks
                   (check_date, postgresql_ok, redis_ok, data_fresh,
                    factor_nan_ok, disk_ok, celery_ok, all_pass, failed_items)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    trade_date,
                    results["postgresql_ok"],
                    results["redis_ok"],
                    results["data_fresh"],
                    results["factor_nan_ok"],
                    results["disk_ok"],
                    results["celery_ok"],
                    all_pass,
                    failed_items if failed_items else None,
                ),
            )
            conn.commit()
        except Exception as e:
            print(f"  ⚠ 写入health_checks失败: {e}", flush=True)
            conn.rollback()

    if own_conn:
        conn.close()

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="QuantMind Paper Trading 健康预检")
    parser.add_argument("--date", type=str, help="检查日期 (YYYY-MM-DD)")
    args = parser.parse_args()

    td = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    print(f"健康预检: {td}", flush=True)

    results = run_health_check(td)
    if results["all_pass"]:
        print("\n✅ 全部通过", flush=True)
        sys.exit(0)
    else:
        print("\n❌ 预检失败，链路暂停", flush=True)
        sys.exit(1)
