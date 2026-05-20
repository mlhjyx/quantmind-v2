"""铁律 35 enforcement guard — production schtask ops scripts use the DB-conn SSOT.

Plan v10 self-set goal: `scripts/daily_reconciliation.py` + `scripts/intraday_monitor.py`
(the 2 production schtask-driven ops scripts that touch the real DB) were routed to
the canonical `app.services.db.get_sync_conn` (derives connection from
`settings.DATABASE_URL` — no inline secret literal, + connection-leak tracking).

These tests are the self-enforcing acceptance artifact: they FAIL if an inline
DB secret literal is re-introduced, or if a script stops using the canonical
config-SSOT connection helper.

关联铁律: 35 (secrets 环境变量唯一, 0 fallback 默认值) — T1.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# Production schtask-driven ops scripts that connect to the real production DB.
_GUARDED_SCRIPTS = [
    _REPO / "scripts" / "daily_reconciliation.py",
    _REPO / "scripts" / "intraday_monitor.py",
]

# An inline DB secret literal — `password="..."` / `password='...'` with a
# value char. Does NOT match `password=os.environ[...]` / `password=None`.
_INLINE_SECRET = re.compile(r"""password\s*=\s*["'][^"']""")


@pytest.mark.parametrize("script", _GUARDED_SCRIPTS, ids=lambda p: p.name)
def test_no_inline_db_secret(script: Path) -> None:
    """生产 ops 脚本不得内联 DB 密码字面量 (铁律 35 — secrets via env/config SSOT)."""
    assert script.exists(), f"guarded script missing: {script}"
    hits = [
        line
        for line in script.read_text(encoding="utf-8").splitlines()
        if _INLINE_SECRET.search(line) and not line.lstrip().startswith("#")
    ]
    assert not hits, f"{script.name} 含内联 DB 密码字面量 (铁律 35 违规): {hits}"


@pytest.mark.parametrize("script", _GUARDED_SCRIPTS, ids=lambda p: p.name)
def test_uses_canonical_get_sync_conn(script: Path) -> None:
    """生产 ops 脚本 DB 连接走 app.services.db.get_sync_conn (config-SSOT 单一来源)."""
    text = script.read_text(encoding="utf-8")
    assert "from app.services.db import get_sync_conn" in text, (
        f"{script.name} 应 import canonical get_sync_conn (反 re-implement 硬编码连接)"
    )


def test_no_inline_psycopg2_connect_in_guarded_scripts() -> None:
    """生产 ops 脚本不得内联 psycopg2.connect (走 canonical helper, 反硬编码连接参数)."""
    for script in _GUARDED_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert "psycopg2.connect(" not in text, (
            f"{script.name} 含内联 psycopg2.connect — 应走 get_sync_conn"
        )
