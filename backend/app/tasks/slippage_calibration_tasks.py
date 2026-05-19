"""Plan v8 P0-10 closure: Celery task wrapper for quarterly slippage calibration.

Beat entry (beat_schedule.py):
  "slippage-calibration-quarterly" — crontab(hour=2, minute=0, day_of_month="1", month_of_year="1,4,7,10")
  Every quarter (Q1/Q2/Q3/Q4) 1st 02:00 SH → call this task.

Why P0-10:
- 铁律 18: 回测成本实现必须与实盘对齐 — H0 验证 < 5bps + 季度复核
- Plan v8 audit: 铁律 18 quarterly 0 scheduler (P0-10 finding)
- Pre-fix: Beat entry sediment in beat_schedule.py:~390 但 task body 不存在
- Beat fire → ModuleNotFoundError (silent skip OR Celery exception)
- LL-190 micro-pattern: sediment-then-forget (Beat entry without task body)

Strategy:
- Subprocess wrapper invokes scripts/bayesian_slippage_calibration.py main()
- Standalone script handles: trade_log SELECT + price impact + Bayesian update +
  Y_small/Y_mid/Y_large coefs + alert drift > 30%
- Celery task = thin dispatcher + exit code propagation + log capture

铁律 32: 0 commit (subprocess owns its own DB session).
铁律 33: fail-loud — non-zero exit raises Celery exception (not silent_ok).
铁律 41: Asia/Shanghai timezone via celery_app.py crontab declaration.
铁律 44 X9: Beat schedule wire pre-existing (beat_schedule.py:~390); 本 file 解决
  ModuleNotFoundError 真根因, 不需 post-merge Servy restart (Celery 自动 hot-load).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.slippage_calibration_tasks")

# scripts/ at project root
SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "scripts"
    / "bayesian_slippage_calibration.py"
)


@celery_app.task(
    name="app.tasks.slippage_calibration_tasks.quarterly_recalibrate", bind=False
)
def quarterly_recalibrate() -> dict:
    """Plan v8 P0-10 — Quarterly slippage Bayesian recalibration via subprocess.

    Returns:
        dict with keys: status, exit_code, stdout_tail, stderr_tail, script_path.

    Raises:
        RuntimeError if subprocess fails (Celery retry / DingTalk alert).
    """
    if not SCRIPT_PATH.exists():
        msg = f"[P0-10] Slippage calibration script missing: {SCRIPT_PATH}"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("[P0-10] Starting quarterly slippage recalibration: %s", SCRIPT_PATH)

    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=1800,  # 30min hard cap for quarterly aggregate + Bayesian update
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        logger.exception("[P0-10] subprocess timeout >30min")
        raise RuntimeError(f"Slippage calibration timeout: {exc}") from exc

    stdout_tail = (result.stdout or "")[-1500:]
    stderr_tail = (result.stderr or "")[-1500:]

    if result.returncode != 0:
        logger.error(
            "[P0-10] FAILED exit=%d, stderr_tail=%s", result.returncode, stderr_tail
        )
        raise RuntimeError(
            f"Slippage calibration exit={result.returncode}: {stderr_tail[:300]}"
        )

    logger.info("[P0-10] OK exit=0, stdout_tail=%s", stdout_tail[-300:])
    return {
        "status": "OK",
        "exit_code": result.returncode,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "script_path": str(SCRIPT_PATH),
    }
