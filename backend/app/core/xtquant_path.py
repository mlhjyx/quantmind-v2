"""xtquant 路径管理 — 统一入口。

xtquant（miniQMT的Python SDK）不在标准pip环境中，安装在特殊路径:
  .venv/Lib/site-packages/Lib/site-packages

所有需要 import xtquant 的模块必须先调用 ensure_xtquant_path()。
使用 append（不是insert）避免旧numpy覆盖项目numpy。
"""

import sys
from pathlib import Path

_added = False


def ensure_xtquant_path() -> None:
    """确保 xtquant 路径在 sys.path 中（幂等）。"""
    global _added
    if _added:
        return

    # 从项目根目录推算: backend/app/core/xtquant_path.py → 上3层 → 项目根
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    xt_path = project_root / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"

    if xt_path.exists() and str(xt_path) not in sys.path:
        sys.path.append(str(xt_path))  # append不是insert，避免旧numpy覆盖

    _added = True
