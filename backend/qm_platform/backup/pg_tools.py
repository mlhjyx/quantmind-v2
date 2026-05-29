"""PostgreSQL CLI resolution helpers for backup orchestrators."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _pg_bin_candidates() -> tuple[str | None, ...]:
    return (
        os.environ.get("PG_BIN"),
        r"D:\pgsql\bin",
        r"C:\Program Files\PostgreSQL\16\bin",
    )


def resolve_pg_binary(name: str) -> str:
    """Resolve a PostgreSQL CLI executable to a concrete path when possible."""
    executable = name if name.lower().endswith(".exe") else f"{name}.exe"
    for candidate in _pg_bin_candidates():
        if not candidate:
            continue
        path = Path(candidate) / executable
        if path.exists():
            return str(path)

    found = shutil.which(executable) or shutil.which(name)
    return found or executable


def pg_subprocess_env() -> dict[str, str]:
    """Return subprocess env with PGPASSWORD loaded from backend/.env if needed."""
    env = os.environ.copy()
    if env.get("PGPASSWORD"):
        return env

    env_file = PROJECT_ROOT / "backend" / ".env"
    if not env_file.exists():
        return env

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("PGPASSWORD="):
            env["PGPASSWORD"] = stripped.split("=", 1)[1].strip().strip("\"'")
            break
        if stripped.startswith("DATABASE_URL="):
            raw = stripped.split("=", 1)[1].strip().strip("\"'")
            parsed = urlparse(raw)
            if parsed.password:
                env["PGPASSWORD"] = unquote(parsed.password)
                break

    return env


__all__ = ["pg_subprocess_env", "resolve_pg_binary"]
