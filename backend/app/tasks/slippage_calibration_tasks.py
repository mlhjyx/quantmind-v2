"""季度滑点参数校准 — Celery task (铁律 18 季度复核 → Plan v10 wire 闭环).

将 `scripts/bayesian_slippage_calibration.py` CLI 逻辑包装为 Celery task,
每季度 (1/4/7/10 月) 1 日 02:00 Asia/Shanghai 触发.

Beat schedule: `slippage-calibration-quarterly` (crontab `0 2 1 1,4,7,10 *`).

闭环的 gap (Plan v10 — orphaned task module 真根因):
    与 llm_cost_audit_tasks 同源 —— 本模块在 Plan v8 P0-10 closure 时**已创建**,
    但**从未注册到** `celery_app.py` 的 `imports=[...]` list. Celery worker
    启动时不 import 本模块 → `@celery_app.task` 装饰器从不执行 → task 从不注册.
    Beat 每季度 fire `slippage-calibration-quarterly` → `Received unregistered
    task`. Plan v9 matrix §3.3 标记, §8.2 误标 closed. Plan v10 真闭环:
    注册到 imports list + 单测 + smoke.

设计 — subprocess wrapper (沿用 llm_cost_audit_tasks 体例):
    以隔离子进程运行校准脚本. 脚本读 trade_log (只读 —— paper 执行记录),
    跑 scipy MLE / PyMC 校准, 打印报告. 数据不足 (<30 条) 时优雅降级 ——
    打印 R4 手工推荐值而非 crash. 因此 returncode 0 可靠表示校准运行已完成
    (无论产出拟合结果 OR 数据不足提示). 脚本无 DB 写入.

铁律 18: 回测成本实现必须与实盘对齐 — H0 验证 < 5bps + 季度复核. 本 task
    即「季度复核」cadence 的 enforcement.
铁律 33: fail-loud — 非 0 returncode (脚本未捕获异常) 抛 RuntimeError → retry.
铁律 44 X9: post-merge ops `Servy restart QuantMind-CeleryBeat AND
    QuantMind-Celery` —— celery_app imports list 变更**必须重启 worker** 才注册
    (Celery 无 task hot-load 机制).

关联: Plan v8 Master P0-10 / Plan v9 matrix §3.3 / 铁律 18 季度复核.
作者: CC autonomous (Plan v10 implementation phase, 2026-05-20 SH).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.tasks.celery_app import celery_app

logger = logging.getLogger("celery.slippage_calibration")

# backend/app/tasks/slippage_calibration_tasks.py → parents[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "bayesian_slippage_calibration.py"

# 子进程超时: scipy MLE (小数据集 L-BFGS-B) 通常 <10s; PyMC MCMC (若安装)
# 可能数分钟. 1800s 给足余量 (沿用旧版 cap).
_SUBPROCESS_TIMEOUT_S = 1800


@celery_app.task(
    name="app.tasks.slippage_calibration_tasks.quarterly_recalibrate",
    soft_time_limit=1840,  # > 子进程 timeout 1800s
    time_limit=1880,  # 硬 kill (反卡死子进程阻塞 Beat)
)
def quarterly_recalibrate() -> dict[str, Any]:
    """以隔离子进程运行季度滑点校准脚本.

    Beat schedule: `slippage-calibration-quarterly` (crontab `0 2 1 1,4,7,10 *`
    Asia/Shanghai —— 每季度首月 1 日 02:00).

    Returns:
        dict, 含:
            "ok" (bool): 校准是否运行到完成.
            "returncode" (int): 0 = 完成 (拟合 OR 数据不足降级).
            "stdout_tail" (str): 末尾 ~2000 字符 (供 Celery worker log 捕获).

    Raises:
        FileNotFoundError: 校准脚本缺失 (部署完整性失败).
        RuntimeError: 非 0 returncode (脚本未捕获异常) — 铁律 33 fail-loud.
        subprocess.TimeoutExpired: 校准超出 _SUBPROCESS_TIMEOUT_S.
    """
    if not _SCRIPT.exists():
        raise FileNotFoundError(f"slippage calibration script missing: {_SCRIPT} (部署完整性失败)")

    logger.info("[slippage-calibration-quarterly] 启动子进程: %s", _SCRIPT)
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT),
        timeout=_SUBPROCESS_TIMEOUT_S,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    # 铁律 33 fail-loud: 脚本对 DB 失败/数据不足优雅降级 (returncode 仍 0);
    # 非 0 returncode = 未捕获异常 = 抛错让 Celery retry.
    if result.returncode != 0:
        raise RuntimeError(
            f"slippage calibration 失败 (rc={result.returncode}) — "
            f"脚本未捕获异常. STDERR tail:\n{stderr[-1000:]}"
        )

    logger.info("[slippage-calibration-quarterly] 校准完成 rc=0")
    return {
        "ok": True,
        "returncode": result.returncode,
        "stdout_tail": stdout[-2000:],
    }


__all__ = ["quarterly_recalibrate"]
