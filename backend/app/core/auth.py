"""共享 admin auth dependency — 单一来源, 防 DRY 违规.

2026-04-30 治理债清理 batch 1.7 reviewer P1 (HIGH) 采纳:
- 原 _verify_admin_token 在 risk.py / approval.py / execution_ops.py 复制 3 份,
  批 2 P2 secrets.compare_digest 修需触 3 文件 (shotgun surgery anti-pattern)
- 提取到本模块, 全 router 用 `from app.core.auth import verify_admin_token`
- 批 2 P2 secrets.compare_digest 单点修复 = 1 文件改动

return None (而非 token 值): reviewer P1 (HIGH) 采纳, 不向 endpoint 泄 secret 值.
endpoint signature 用 `_: None = Depends(verify_admin_token)` 显式 discard.

Note:
- execution_ops.py 暂保留独立 _verify_admin_token (本 PR scope 不动, 留批 2 一并迁)
- 沿用 plain `!=` compare (D2.2 Finding 标 P2 timing attack), 留批 2 P2 单独修
  (改 secrets.compare_digest), 本批不改实现.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import settings


def verify_admin_token(
    x_admin_token: str = Header(alias="X-Admin-Token", default=""),
) -> None:
    """验证 X-Admin-Token header.

    Raises:
        HTTPException 500: settings.ADMIN_TOKEN 未配置 (生产前置必须配)
        HTTPException 401: token 不匹配
    """
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN未配置")
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="无效的Admin Token")
