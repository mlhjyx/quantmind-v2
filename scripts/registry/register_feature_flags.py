"""MVP 1.3c — 注册 use_db_direction Feature Flag (切 True 激活 signal_engine DB 路径).

当前 DB 状态 (2026-04-18 实测): `feature_flags` 表空, 无 `use_db_direction` 注册,
所以 MVP 1.3b 的 3 层 fallback 实际走 Layer 3 hardcoded (FlagNotFound 被 silent_ok
fallback 吞). 本脚本 apply 后:
  1. `feature_flags` 表新增 `use_db_direction` 行 (enabled=True, removal_date=2026-06-01)
  2. PT 重启 (`service_manager.ps1 restart all`) 使 signal_engine 走 Layer 1 DB 路径
  3. 观察 3 天 (MVP 1.3b 30/30 hardcoded↔DB 等价数学证明保证 max_diff=0)

MVP 1.3d 稳定后 + 老 `FACTOR_DIRECTION` dict 清理时, 本 flag 走 removal_date 强制退休.

Usage:
    python scripts/registry/register_feature_flags.py                  # dry-run
    python scripts/registry/register_feature_flags.py --apply          # 真写 DB
    python scripts/registry/register_feature_flags.py --list           # 列现有 flag
    python scripts/registry/register_feature_flags.py --apply --disable  # enabled=False 回滚

铁律:
  - 32: Service 不 commit — 本脚本是 orchestration, commit 由 DBFeatureFlag.register 处理
  - 33: 禁 silent failure — 所有异常向上 raise
  - 34: 配置 SSOT — feature_flags 表为权威, 本脚本仅 seed 新 flag
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# 用 append 而非 insert(0) — 避免 backend/platform/ 覆盖 stdlib `platform`
# (MVP 1.2 踩坑记录: pandas `import platform; platform.python_implementation()` 会崩)
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("register_feature_flags")


# ---------- MVP 1.3c 要注册的 flags ----------

FLAGS_TO_REGISTER: list[dict] = [
    {
        "name": "use_db_direction",
        "default": True,
        "removal_date": "2026-06-01",
        "description": (
            "MVP 1.3c: signal_engine._get_direction() Layer 1 DB 路径. "
            "走 DBFactorRegistry + TTL cache 替代 FACTOR_DIRECTION hardcoded dict. "
            "MVP 1.3b 已数学证明 30/30 hardcoded↔DB 100% 对齐, regression max_diff=0. "
            "MVP 1.3d 删 _constants.py direction dicts 后本 flag 走 removal_date 退休."
        ),
    },
]


def _get_conn():
    from app.services.db import get_sync_conn

    return get_sync_conn()


def cmd_list() -> None:
    """列 feature_flags 当前所有行."""
    from backend.qm_platform.config.feature_flag import DBFeatureFlag

    flag_db = DBFeatureFlag(_get_conn)
    rows = flag_db.list_all()
    if not rows:
        logger.info("feature_flags 表为空.")
        return
    logger.info("feature_flags 当前 %d 行:", len(rows))
    for row in rows:
        logger.info(
            "  - %s: enabled=%s, removal_date=%s, desc=%s",
            row["name"], row["enabled"], row["removal_date"],
            row["description"][:60] + "..." if len(row["description"] or "") > 60 else row["description"],
        )


def cmd_apply(dry_run: bool, disable: bool) -> None:
    """注册 MVP 1.3c flags. dry_run=True 时只打印不写 DB."""
    from backend.qm_platform.config.feature_flag import DBFeatureFlag

    if dry_run:
        logger.info("[DRY-RUN] 将注册 %d flags:", len(FLAGS_TO_REGISTER))
        for cfg in FLAGS_TO_REGISTER:
            effective = (not cfg["default"]) if disable else cfg["default"]
            logger.info(
                "  - %s → enabled=%s, removal_date=%s",
                cfg["name"], effective, cfg["removal_date"],
            )
        logger.info("[DRY-RUN] 结束. 加 --apply 真写 DB.")
        return

    flag_db = DBFeatureFlag(_get_conn)
    for cfg in FLAGS_TO_REGISTER:
        effective = (not cfg["default"]) if disable else cfg["default"]
        logger.info(
            "register: %s → enabled=%s, removal_date=%s",
            cfg["name"], effective, cfg["removal_date"],
        )
        flag_db.register(
            name=cfg["name"],
            default=effective,
            removal_date=cfg["removal_date"],
            description=cfg["description"],
        )
    logger.info("✅ 注册完成. 请重启 PT 服务使 signal_engine 感知新路径:")
    logger.info("    powershell -File scripts/service_manager.ps1 restart all")


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP 1.3c — register use_db_direction feature flag")
    parser.add_argument("--apply", action="store_true", help="真写 DB (默认 dry-run)")
    parser.add_argument("--list", action="store_true", help="列现有 feature_flags")
    parser.add_argument(
        "--disable",
        action="store_true",
        help="注册为 enabled=False (rollback 用, 配合 --apply)",
    )
    args = parser.parse_args()

    if args.list:
        cmd_list()
        return
    cmd_apply(dry_run=not args.apply, disable=args.disable)


if __name__ == "__main__":
    main()
