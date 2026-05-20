"""月度 LLM 成本审计 — Celery task (Plan v8 Master P0-16 → Plan v10 wire 闭环).

将 `scripts/llm_cost_monthly_audit.py` CLI 逻辑包装为 Celery task, 每月 1 日
08:00 Asia/Shanghai 触发 (月初, 上月数据已完整).

Beat schedule: `llm-cost-monthly-audit` (crontab `0 8 1 * *`).

闭环的 gap (Plan v10 — orphaned task module 真根因):
    本模块在 Plan v8 P0-16 closure 时**已创建**, 但**从未注册到** `celery_app.py`
    的 `imports=[...]` list. Celery worker 启动时只 import imports list 内的模块
    —— 本模块被遗漏 → `@celery_app.task` 装饰器从不执行 → task 从不注册.
    Beat 每月 1 日 fire `llm-cost-monthly-audit` → `Received unregistered task
    of type 'app.tasks.llm_cost_audit_tasks.monthly_audit'`.
    Plan v9 matrix §3.3 标记 gap, §8.2 误标 closed (仅改 beat 注释未注册模块).
    Plan v10 真闭环: 注册到 imports list + 修正 CAP_EXCEEDED 语义 + 单测 + smoke.

设计 — subprocess wrapper (反 import 耦合):
    以隔离子进程运行 `scripts/llm_cost_monthly_audit.py`. 脚本自管 .env 解析 +
    psycopg2 连接生命周期 + exit code. 子进程隔离意味着脚本内的 `SystemExit` /
    crash 不会杀死 Celery worker. 月度 cadence 使解释器启动开销 (~1-2s) 可忽略.
    脚本本身只跑只读 SELECT (llm_call_log), 无 DB 写入.

    脚本 exit code (沿用 scripts/llm_cost_monthly_audit.py + budget.py 状态机):
        0 — OK 或 WARN (审计完成, 预算内 OR 80%+ 警告 —— WARN 仍 exit 0)
        1 — CAP_EXCEEDED (审计完成, MTD 成本 >= 100% 预算 → Ollama fallback)
    exit 0 和 1 都表示审计**已完成** —— returncode 1 是一个发现 (预算超标),
    不是 task 失败. 旧版 wrapper 对 `returncode != 0` 一律 raise RuntimeError →
    每月预算超标会触发 Celery retry 风暴 + 掩盖合法发现. 本版修正: 只要 stdout
    含 completion marker 即视为审计成功, returncode 1 作为 status 返回不 raise.
    仅 completion marker 缺失 (脚本 crash) OR 子进程超时才 raise → Celery retry.

铁律 33: fail-loud — completion marker 缺失抛 RuntimeError.
铁律 41: Asia/Shanghai cadence (Beat crontab); 脚本自管时区.
铁律 44 X9: post-merge ops `Servy restart QuantMind-CeleryBeat AND
    QuantMind-Celery` —— celery_app imports list 变更**必须重启 worker** 才注册
    (Celery 无 task hot-load 机制; 旧版 docstring 误称"自动 hot-load 不需重启").

关联: Plan v8 Master P0-16 / Plan v9 matrix §3.3 / V3 §20.1 #6 预算上限.
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

logger = logging.getLogger("celery.llm_cost_audit")

# backend/app/tasks/llm_cost_audit_tasks.py → parents[3] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "llm_cost_monthly_audit.py"

# 子进程超时: llm_call_log 上的 SELECT 通常 <30s; 600s 给足余量 (沿用旧版 cap).
_SUBPROCESS_TIMEOUT_S = 600
# scripts/llm_cost_monthly_audit.py:203 print(f"=== Audit COMPLETE — status={status} ===")
# marker 仅取 ASCII 前缀, 不依赖 em-dash (反 Windows 控制台编码漂移).
_COMPLETION_MARKER = "=== Audit COMPLETE"


def _parse_status(stdout: str) -> str:
    """从脚本的 completion marker 行解析审计状态.

    脚本打印 `=== Audit COMPLETE — status={status} ===` (status ∈
    {OK, WARN, CAP_EXCEEDED}). 解析只依赖 ASCII 子串 `status=`, 因此即使
    Windows 控制台编码把 em-dash 弄乱也不受影响.

    Args:
        stdout: 审计脚本的完整 stdout 捕获.

    Returns:
        解析出的状态字符串 (OK / WARN / CAP_EXCEEDED), 解析失败返回 "UNKNOWN".
    """
    for line in stdout.splitlines():
        if _COMPLETION_MARKER in line and "status=" in line:
            parts = line.split("status=", 1)[1].split()
            if parts:
                return parts[0].strip()
    return "UNKNOWN"


@celery_app.task(
    name="app.tasks.llm_cost_audit_tasks.monthly_audit",
    soft_time_limit=640,  # > 子进程 timeout 600s
    time_limit=680,  # 硬 kill (反卡死子进程阻塞 Beat 下次触发)
)
def monthly_audit() -> dict[str, Any]:
    """以隔离子进程运行月度 LLM 成本审计脚本.

    Beat schedule: `llm-cost-monthly-audit` (crontab `0 8 1 * *` Asia/Shanghai
    —— 每月 1 日 08:00, 月初触发使上月数据完整).

    Returns:
        dict, 含:
            "ok" (bool): 审计是否运行到完成 (无论预算状态).
            "returncode" (int): 0=OK/WARN, 1=CAP_EXCEEDED.
            "status" (str): OK | WARN | CAP_EXCEEDED | UNKNOWN.
            "stdout_tail" (str): 末尾 ~2000 字符 (供 Celery worker log 捕获).

    Raises:
        FileNotFoundError: 审计脚本缺失 (部署完整性失败).
        RuntimeError: 子进程无 completion marker (脚本中途 crash) — 铁律 33.
        subprocess.TimeoutExpired: 审计超出 _SUBPROCESS_TIMEOUT_S.
    """
    if not _SCRIPT.exists():
        raise FileNotFoundError(f"llm cost audit script missing: {_SCRIPT} (部署完整性失败)")

    logger.info("[llm-cost-monthly-audit] 启动子进程: %s", _SCRIPT)
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

    # 铁律 33 fail-loud: completion marker 缺失 = 脚本中途 crash = 抛错让 Celery retry.
    if _COMPLETION_MARKER not in stdout:
        raise RuntimeError(
            f"llm cost audit 无 completion marker (rc={result.returncode}) — "
            f"脚本疑似 crash. STDERR tail:\n{stderr[-1000:]}"
        )

    status = _parse_status(stdout)
    if status == "CAP_EXCEEDED":
        logger.warning(
            "[llm-cost-monthly-audit] CAP EXCEEDED — MTD 成本 >= 100% 月度预算. "
            "复查 llm_call_log + 考虑 Ollama fallback (ADR-028 §3.3)."
        )
    elif status == "WARN":
        logger.warning("[llm-cost-monthly-audit] WARN — MTD 成本 >= 80% 月度预算.")
    else:
        logger.info("[llm-cost-monthly-audit] 审计完成 status=%s", status)

    return {
        "ok": True,
        "returncode": result.returncode,
        "status": status,
        "stdout_tail": stdout[-2000:],
    }


__all__ = ["monthly_audit"]
