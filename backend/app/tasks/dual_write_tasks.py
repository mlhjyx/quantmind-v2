"""MVP 2.1c Sub3 dual-write 自动化 Celery task (2026-04-18).

Beat 每工作日 15:20 自动触发 `scripts/dual_write_check.py`, 读取最新 state,
PASS 则 log info, FAIL 则 logger.error + StreamBus 广播 `qm:dual_write:fail_alert`.

设计:
  - subprocess 调 scripts/dual_write_check.py (复用既有代码, 无重复逻辑)
  - 15:20 时点: 老 fetcher (Celery/Servy) 已于 15:10-15:30 完成, 盘后对齐最稳
  - 工作日过滤: Beat `crontab(day_of_week="1-5")`, 周末/节假日 task 内部
    再核对交易日 (trading_calendar) 避免假期误报
  - TUSHARE_TOKEN 缺失: script 返 exit=2, task log warning 不告警 (视为环境问题)
  - FAIL 告警: StreamBus 发 `qm:dual_write:fail_alert` 事件, 前端 / 告警通道统一消费

关联文档:
  - `scripts/dual_write_check.py`: 执行核心
  - `docs/ops/DUAL_WRITE_RUNBOOK.md`: 用户操作手册 (默认自动, 本 task 覆盖)
  - `docs/mvp/MVP_2_3_backtest_parity.md`: MVP 2.3 依赖本窗口完成

铁律: 10 全链路验证 / 17 DataPipeline 唯一入库 / 33 禁 silent failure
  / 36 precondition 核对 / 10b 生产入口真启动 (subprocess 从 project root 启)
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.dual_write_tasks")

# backend/app/tasks → backend/app → backend → project root
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _is_trading_day(td: date) -> bool:
    """查 trading_calendar 判断是否 A 股交易日 (节假日过滤).

    回退: DB 不可达 → 按 weekday 粗判 (周一-周五 True). 节假日 False positive 可容忍
    (task 内部 subprocess 跑 old fetcher 查空, 自动 SKIP/ERROR 不告警).
    """
    try:
        from app.data_fetcher.data_loader import get_sync_conn

        conn = get_sync_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT is_trading_day FROM trading_calendar "
                "WHERE market='astock' AND trade_date=%s",
                (td,),
            )
            row = cur.fetchone()
            cur.close()
            if row is not None:
                return bool(row[0])
        finally:
            conn.close()
    except Exception as e:  # silent_ok: DB 故障回退 weekday 粗判
        logger.warning("[dual_write_check] trading_calendar 查询失败, 回退 weekday: %s", e)
    return td.weekday() < 5  # 0-4 = 周一-周五


@celery_app.task(
    bind=True,
    name="app.tasks.dual_write_tasks.run_dual_write_check",
    acks_late=True,
    max_retries=0,  # FAIL 是信息不是执行错误, 不 retry
    soft_time_limit=300,  # 5 min 软超时 (subprocess 实际 1-2 min)
    time_limit=360,
)
def run_dual_write_check(self) -> dict[str, Any]:
    """Beat 每工作日 15:20 自动跑 dual-write 对齐检查.

    逻辑:
      1. 交易日判断 (非交易日 / 节假日 → 快速退出)
      2. subprocess 调 `scripts/dual_write_check.py`
      3. 读 cache/dual_write_state.json 最新 entry
      4. PASS 日志 info / FAIL 日志 error + StreamBus 广播 / ERROR 日志 warning

    Returns:
      dict with date / status / exit_code / old_rows / new_rows
    """
    today = date.today()
    if not _is_trading_day(today):
        logger.info("[dual_write_check] %s 非交易日, 跳过", today)
        return {"date": today.isoformat(), "status": "SKIP_NON_TRADING_DAY"}

    script_path = _PROJECT_ROOT / "scripts" / "dual_write_check.py"
    logger.info("[dual_write_check] %s 自动跑 %s", today, script_path)

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=280,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        logger.error("[dual_write_check] subprocess 超时 %s", e)
        return {"date": today.isoformat(), "status": "TIMEOUT"}
    except Exception as e:  # silent_ok: subprocess 启动异常不 retry, 记日志
        logger.error("[dual_write_check] subprocess 启动失败: %s", e, exc_info=True)
        return {"date": today.isoformat(), "status": "SUBPROCESS_ERROR", "error": str(e)}

    exit_code = result.returncode

    # 读最新 state entry
    state_file = _PROJECT_ROOT / "cache" / "dual_write_state.json"
    latest: dict[str, Any] = {}
    latest_date: str | None = None
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state:
                latest_date = max(state.keys())  # ISO-format lexical == chronological
                latest = state.get(latest_date, {})
        except Exception as e:  # silent_ok: state 损坏不影响 task
            logger.warning("[dual_write_check] state 读取失败: %s", e)

    status = latest.get("status", "UNKNOWN")

    if exit_code == 0 and status == "PASS":
        logger.info(
            "[dual_write_check] %s PASS old=%s new=%s",
            latest_date,
            latest.get("old_rows"),
            latest.get("new_rows"),
        )
    elif exit_code == 2:
        # ERROR (TUSHARE_TOKEN / old path empty) — 警告但不告警 (环境问题)
        logger.warning(
            "[dual_write_check] %s ERROR exit=2 — 多半 TUSHARE_TOKEN 未配 或 老 fetcher 未跑. "
            "stdout[:500]: %s",
            latest_date,
            result.stdout[:500],
        )
    else:
        # FAIL (exit=1) 或其他异常 — logger.error + StreamBus 告警
        logger.error(
            "[dual_write_check] %s FAIL status=%s exit=%d stdout[:300]=%s stderr[:300]=%s",
            latest_date,
            status,
            exit_code,
            result.stdout[:300],
            result.stderr[:300],
        )
        _publish_fail_alert(latest_date, latest, exit_code, result.stderr[:500])

    return {
        "date": latest_date or today.isoformat(),
        "status": status,
        "exit_code": exit_code,
        "old_rows": latest.get("old_rows"),
        "new_rows": latest.get("new_rows"),
    }


def _publish_fail_alert(
    latest_date: str | None, latest: dict, exit_code: int, stderr_snippet: str
) -> None:
    """StreamBus `qm:dual_write:fail_alert` 广播 FAIL 详情.

    fail-safe: StreamBus 故障不阻塞 task 返回, 走 logger.warning.
    """
    try:
        from app.core.stream_bus import get_stream_bus

        bus = get_stream_bus()
        payload = {
            "date": latest_date,
            "status": latest.get("status"),
            "exit_code": exit_code,
            "old_rows": latest.get("old_rows"),
            "new_rows": latest.get("new_rows"),
            "codes_only_in_old": latest.get("codes_only_in_old"),
            "codes_only_in_new": latest.get("codes_only_in_new"),
            "stderr_snippet": stderr_snippet,
            "runbook": "docs/ops/DUAL_WRITE_RUNBOOK.md",
        }
        bus.publish_sync("qm:dual_write:fail_alert", payload, source="dual_write_tasks")
        logger.info("[dual_write_check] StreamBus 告警已发 qm:dual_write:fail_alert")
    except Exception as e:  # silent_ok: StreamBus 不可用不阻塞主监控
        logger.warning("[dual_write_check] StreamBus publish 失败: %s", e)
