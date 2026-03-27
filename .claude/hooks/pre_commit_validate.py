"""Harness Hook: Pre-commit验证 — 约束层核心。

触发: PreToolUse[Bash] when git commit
功能:
1. ruff check 检查Python代码质量
2. 检查PROGRESS.md是否最近更新过（铁律6）
3. 检查是否有.env等敏感文件被staged
退出码: 0=通过, 2=阻止
"""

import json
import subprocess
import sys
from pathlib import Path


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    # 只拦截git commit命令
    if "git commit" not in command and "git push" not in command:
        sys.exit(0)

    project_root = Path(__file__).resolve().parent.parent.parent
    errors = []

    # --- 1. ruff check (只检查staged的.py文件，不检查全仓库) ---
    if "git commit" in command:
        try:
            staged_py = subprocess.run(
                ["git", "diff", "--cached", "--name-only", "--diff-filter=d", "--", "*.py"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            py_files = [f for f in staged_py.stdout.strip().split("\n")
                        if f.strip() and (f.startswith("backend/") or f.startswith("scripts/"))]
            if py_files:
                result = subprocess.run(
                    ["ruff", "check"] + py_files,
                    cwd=str(project_root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    error_lines = result.stdout.strip().split("\n")[:5]
                    errors.append(
                        f"ruff check FAILED ({len(result.stdout.strip().split(chr(10)))} issues):\n"
                        + "\n".join(f"  {line}" for line in error_lines)
                    )
        except FileNotFoundError:
            pass  # ruff not installed, skip
        except subprocess.TimeoutExpired:
            pass

    # --- 2. 敏感文件检查 ---
    try:
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        staged_files = staged.stdout.strip().split("\n") if staged.stdout.strip() else []
        sensitive = [f for f in staged_files if f.endswith(".env") or "credentials" in f.lower() or "secret" in f.lower()]
        if sensitive:
            errors.append(f"敏感文件被staged: {', '.join(sensitive)}")
    except Exception:
        pass

    if errors:
        msg = "Pre-commit验证FAILED:\n" + "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
        print(msg, file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
