"""Plan v8 P0-16 closure: Celery task wrapper for monthly LLM cost audit.

Beat entry (beat_schedule.py):
  "llm-cost-monthly-audit" — crontab(hour=8, minute=0, day_of_month="1")
  Every month 1st 08:00 SH → call this task.

Why P0-16:
- Plan v8 §VIII #16 audit: LLM monthly cost aggregator missing
- Pre-fix: Beat entry sediment in beat_schedule.py:382 但 task body 不存在
- Beat fire → ModuleNotFoundError (silent skip OR Celery exception)
- LL-190 micro-pattern: sediment-then-forget (Beat entry without task body)

Strategy:
- Subprocess wrapper invokes scripts/llm_cost_monthly_audit.py main()
- Standalone script has its own DB connection (env-driven) + SQL queries + report sediment
- Celery task = thin dispatcher + exit code propagation + log capture

铁律 32: 0 commit (subprocess owns its own DB session).
铁律 33: fail-loud — non-zero exit raises Celery exception (not silent_ok).
铁律 41: Asia/Shanghai timezone via celery_app.py crontab declaration.
铁律 44 X9: Beat schedule wire pre-existing (beat_schedule.py:382); 本 file 解决
  ModuleNotFoundError 真根因, 不需 post-merge Servy restart (Celery 自动 hot-load).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.llm_cost_audit_tasks")

# scripts/ at project root
SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "scripts"
    / "llm_cost_monthly_audit.py"
)


@celery_app.task(name="app.tasks.llm_cost_audit_tasks.monthly_audit", bind=False)
def monthly_audit() -> dict:
    """Plan v8 P0-16 — Monthly LLM cost audit via subprocess wrapper.

    Returns:
        dict with keys: status, exit_code, stdout_tail, stderr_tail, script_path.
        status ∈ {"OK", "FAIL", "SCRIPT_MISSING"}.

    Raises:
        RuntimeError if subprocess fails (Celery retry / DingTalk alert).
    """
    if not SCRIPT_PATH.exists():
        msg = f"[P0-16] LLM cost audit script missing: {SCRIPT_PATH}"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("[P0-16] Starting monthly LLM cost audit: %s", SCRIPT_PATH)

    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
            timeout=600,  # 10min hard cap for monthly aggregate query
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        logger.exception("[P0-16] subprocess timeout >10min")
        raise RuntimeError(f"LLM cost audit timeout: {exc}") from exc

    stdout_tail = (result.stdout or "")[-1000:]
    stderr_tail = (result.stderr or "")[-1000:]

    if result.returncode != 0:
        logger.error(
            "[P0-16] FAILED exit=%d, stderr_tail=%s", result.returncode, stderr_tail
        )
        raise RuntimeError(
            f"LLM cost audit exit={result.returncode}: {stderr_tail[:300]}"
        )

    logger.info("[P0-16] OK exit=0, stdout_tail=%s", stdout_tail[-300:])
    return {
        "status": "OK",
        "exit_code": result.returncode,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "script_path": str(SCRIPT_PATH),
    }
