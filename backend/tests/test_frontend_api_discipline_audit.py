"""Tests for the frontend API discipline audit script.

The scanner should catch real raw axios imports while ignoring prose/comment
mentions that made the original audit noisy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.audit import check_frontend_api_discipline as scanner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "audit" / "check_frontend_api_discipline.py"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_current_codebase_is_clean() -> None:
    violations = scanner.scan()
    assert violations == []


def test_comment_only_mentions_are_ignored(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(
        src / "pages" / "Dashboard.tsx",
        """
        // raw axios -> apiClient SSOT, no import should be flagged
        /*
         * axios interceptor note in prose.
         */
        export const Dashboard = () => null;
        """,
    )
    assert scanner.scan(src) == []


def test_allowed_client_import_is_clean(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(
        src / "api" / "client.ts",
        'import axios, { type AxiosResponse } from "axios";\nexport default axios.create();\n',
    )
    assert scanner.scan(src) == []


def test_raw_import_outside_client_blocks(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(src / "pages" / "Bad.tsx", 'import axios from "axios";\n')
    violations = scanner.scan(src)
    assert len(violations) == 1
    assert violations[0].file == "pages/Bad.tsx"
    assert violations[0].kind == "import-from"


def test_require_and_dynamic_import_block(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(
        src / "pages" / "Bad.tsx",
        """
        const axios = require("axios");
        await import("axios");
        """,
    )
    violations = scanner.scan(src)
    assert [v.kind for v in violations] == ["require", "dynamic-import"]


def test_tests_are_excluded_by_default(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(src / "__tests__" / "api.test.ts", 'import axios from "axios";\n')
    assert scanner.scan(src) == []


def test_include_tests_surfaces_test_imports(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(src / "__tests__" / "api.test.ts", 'import axios from "axios";\n')
    violations = scanner.scan(src, include_tests=True)
    assert len(violations) == 1
    assert violations[0].file == "__tests__/api.test.ts"


def test_cli_exit_codes(tmp_path: Path) -> None:
    src = tmp_path / "src"
    _write(src / "pages" / "Bad.tsx", 'import axios from "axios";\n')
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(src)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert "BLOCK" in result.stdout
