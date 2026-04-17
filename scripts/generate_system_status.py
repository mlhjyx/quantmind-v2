"""SYSTEM_STATUS.md 量化章节自动生成器。

Step 6-B 新增 (2026-04-09): 从 DB/git/代码统计自动生成 SYSTEM_STATUS.md 的以下章节:
- §1 系统环境 (服务版本, 不自动改, 只输出当前检测到的值)
- §2 数据库 (表清单 + 行数 + 时间范围)
- §3 代码状态 (git + 文件计数 + 测试数 + ruff lint)
- §7 性能基准 (从 cache/baseline/regression_result.json)

用法:
    python scripts/generate_system_status.py                    # 打印到 stdout
    python scripts/generate_system_status.py --dry-run          # 只 diff, 不写
    python scripts/generate_system_status.py --inplace          # 原地更新 SYSTEM_STATUS.md 的标记区段

设计原则: 只覆盖统计章节 (§1/§2/§3/§7), 深度章节 (§4 模块依赖 / §5 PT 调用链) 人工维护。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATUS_MD = PROJECT_ROOT / "SYSTEM_STATUS.md"
BASELINE_JSON = PROJECT_ROOT / "cache" / "baseline" / "regression_result.json"


# ── §2 数据库统计 ──

def gather_db_stats() -> dict:
    """从 DB 拉表行数 + 时间范围 + 大小。"""
    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    cur = conn.cursor()

    # 获取 hypertables 列表 (TimescaleDB 父表 pg_stat_user_tables.n_live_tup=0)
    hypertables: set[str] = set()
    try:
        cur.execute("SELECT hypertable_name FROM timescaledb_information.hypertables")
        hypertables = {r[0] for r in cur.fetchall()}
    except Exception:
        pass

    # Hypertable 实际行数 (从 _timescaledb_catalog 或直接 COUNT)
    hypertable_rows: dict[str, int] = {}
    for h in hypertables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {h}")
            hypertable_rows[h] = cur.fetchone()[0]
        except Exception:
            pass

    # 有数据的表按行数降序 (排除 TimescaleDB 内部 chunks 和目录表)
    cur.execute("""
        SELECT relname AS table_name, n_live_tup AS rows, schemaname
        FROM pg_stat_user_tables
        WHERE n_live_tup > 0
          AND schemaname = 'public'
          AND relname NOT LIKE '\\_hyper\\_%' ESCAPE '\\'
          AND relname NOT LIKE '\\_compressed\\_%' ESCAPE '\\'
        ORDER BY n_live_tup DESC
        LIMIT 40
    """)
    tables = [{"name": r[0], "rows": r[1]} for r in cur.fetchall()]

    # 把 hypertables 加回去, 用真实 COUNT(*)
    for h, cnt in hypertable_rows.items():
        if cnt > 0 and not any(t["name"] == h for t in tables):
            tables.append({"name": h, "rows": cnt})
    tables.sort(key=lambda t: t["rows"], reverse=True)
    tables = tables[:40]

    # 核心表时间范围
    ranges = {}
    for tbl in ["klines_daily", "daily_basic", "moneyflow_daily",
                "factor_values", "northbound_holdings", "minute_bars"]:
        try:
            col = "trade_date"
            if tbl == "minute_bars":
                col = "trade_date"
            cur.execute(f"SELECT MIN({col}), MAX({col}) FROM {tbl}")
            r = cur.fetchone()
            if r and r[0]:
                ranges[tbl] = (r[0].isoformat(), r[1].isoformat())
        except Exception as e:
            ranges[tbl] = (None, str(e)[:50])

    # 空表清单 (排除 hypertables + TimescaleDB 目录表)
    cur.execute("""
        SELECT relname FROM pg_stat_user_tables
        WHERE n_live_tup = 0
          AND schemaname = 'public'
          AND relname NOT LIKE '\\_hyper\\_%' ESCAPE '\\'
        ORDER BY relname
    """)
    empty_tables = [r[0] for r in cur.fetchall() if r[0] not in hypertables]

    # code 格式验证 (铁律 17 监控)
    suffix_status = {}
    for tbl, col in [
        ("klines_daily", "code"),
        ("daily_basic", "code"),
        ("moneyflow_daily", "code"),
        ("factor_values", "code"),
        ("minute_bars", "code"),
    ]:
        try:
            cur.execute(
                f"SELECT COUNT(*) FILTER (WHERE {col} NOT LIKE '%.%') FROM {tbl}"
            )
            suffix_status[tbl] = cur.fetchone()[0]
        except Exception:
            suffix_status[tbl] = None

    conn.close()
    return {
        "tables": tables,
        "ranges": ranges,
        "empty_tables": empty_tables,
        "no_suffix_count": suffix_status,
    }


# ── §3 代码状态 ──

def gather_code_stats() -> dict:
    """代码文件计数 + git + ruff + pytest 收集。"""
    def _count(glob_pattern: str, exclude: list[str] | None = None) -> int:
        cmd = ["git", "ls-files", glob_pattern]
        try:
            r = subprocess.run(
                cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=10
            )
            files = [f for f in r.stdout.splitlines() if f]
            if exclude:
                files = [f for f in files if not any(e in f for e in exclude)]
            return len(files)
        except Exception:
            return -1

    try:
        commit = subprocess.run(
            ["git", "log", "-1", "--format=%H %s"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        commit = "unknown"

    try:
        total_commits = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        total_commits = "?"

    # ruff 错误数 (运行可能较慢, 2s 超时后跳过)
    ruff_errors = "?"
    try:
        r = subprocess.run(
            ["ruff", "check", "backend/", "scripts/"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=30,
        )
        out = r.stdout + r.stderr
        # 解析 "Found N errors"
        import re

        m = re.search(r"Found\s+(\d+)\s+error", out)
        ruff_errors = m.group(1) if m else "0"
    except Exception as e:
        ruff_errors = f"skip ({e.__class__.__name__})"

    # 测试数 (pytest --collect-only -q 比跑测试快)
    test_count = "?"
    try:
        r = subprocess.run(
            ["pytest", "--collect-only", "-q", "backend/tests/"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60,
        )
        import re

        m = re.search(r"(\d+)\s+tests?\s+collected", r.stdout + r.stderr)
        test_count = m.group(1) if m else "?"
    except Exception:
        test_count = "skip"

    return {
        "backend_py": _count("backend/**/*.py"),
        "scripts_py": _count("scripts/**/*.py", exclude=["archive/"]),
        "frontend_ts": _count("frontend/src/**/*.ts") + _count("frontend/src/**/*.tsx"),
        "test_files": _count("backend/tests/test_*.py"),
        "total_commits": total_commits,
        "latest_commit": commit,
        "ruff_errors": ruff_errors,
        "test_count": test_count,
    }


# ── §7 基线数据 ──

def gather_baseline() -> dict:
    """从 cache/baseline/regression_result.json 读基线。"""
    if not BASELINE_JSON.exists():
        return {"error": f"{BASELINE_JSON} not found"}
    try:
        return json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}


# ── 输出 ──

def render_markdown(db: dict, code: dict, baseline: dict) -> str:
    """生成可插入 SYSTEM_STATUS.md 的 Markdown 段落。"""
    lines = [
        "<!-- generated by scripts/generate_system_status.py -->",
        f"<!-- generated_at: {datetime.now().isoformat(timespec='seconds')} -->",
        "",
        "## §2 数据库 (自动生成)",
        "",
        "### 表清单 (n_live_tup 降序, Top 40)",
        "",
        "| 表 | 行数 |",
        "|----|------|",
    ]
    for t in db["tables"]:
        lines.append(f"| {t['name']} | {t['rows']:,} |")

    lines.extend([
        "",
        "### 核心表时间范围",
        "",
        "| 表 | 起始 | 截止 |",
        "|----|------|------|",
    ])
    for tbl, (start, end) in db["ranges"].items():
        lines.append(f"| {tbl} | {start or '-'} | {end or '-'} |")

    lines.extend([
        "",
        "### code 格式验证 (铁律 1 + 6-B, 应全部为 0)",
        "",
        "| 表 | 无后缀行数 |",
        "|----|----------|",
    ])
    for tbl, cnt in db["no_suffix_count"].items():
        flag = "✅" if cnt == 0 else ("❌" if cnt and cnt > 0 else "?")
        lines.append(f"| {tbl} | {cnt if cnt is not None else '?'} {flag} |")

    lines.extend([
        "",
        f"### 空表 ({len(db['empty_tables'])} 张)",
        "",
        ", ".join(db["empty_tables"]) or "(无)",
        "",
        "## §3 代码状态 (自动生成)",
        "",
        f"- Git commits: {code['total_commits']}",
        f"- 最新 commit: `{code['latest_commit']}`",
        f"- backend/ Python: {code['backend_py']}",
        f"- scripts/ Python (非 archive): {code['scripts_py']}",
        f"- frontend/src TS/TSX: {code['frontend_ts']}",
        f"- 测试文件: {code['test_files']}",
        f"- 测试数 (pytest collect): {code['test_count']}",
        f"- ruff errors: {code['ruff_errors']}",
        "",
        "## §7 基线回测 (自动生成)",
        "",
    ])
    if "error" in baseline:
        lines.append(f"⚠️ {baseline['error']}")
    else:
        b = baseline.get("run1", {})
        lines.extend([
            f"- timestamp: {baseline.get('timestamp', '-')}",
            f"- baseline_file: `{baseline.get('baseline_file', '-')}`",
            f"- days: {b.get('common_days', '-')}",
            f"- Sharpe: {b.get('sharpe_current', '-')}",
            f"- MDD: {b.get('mdd_current', '-')}%",
            f"- max_diff: {b.get('max_diff', '-')}",
            f"- elapsed: {baseline.get('elapsed_sec', '-')}s",
        ])

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只输出 diff, 不写")
    parser.add_argument("--inplace", action="store_true",
                        help="(未实现) 原地替换 SYSTEM_STATUS.md 标记区段")
    parser.add_argument("--output", type=str, help="写到指定文件 (默认 stdout)")
    args = parser.parse_args()

    print("# Gathering DB stats...", file=sys.stderr)
    db = gather_db_stats()
    print("# Gathering code stats...", file=sys.stderr)
    code = gather_code_stats()
    print("# Gathering baseline...", file=sys.stderr)
    baseline = gather_baseline()

    md = render_markdown(db, code, baseline)

    if args.inplace:
        print("--inplace 尚未实现。请复制输出手工粘贴。", file=sys.stderr)
        sys.exit(1)

    if args.output:
        out_path = Path(args.output)
        if args.dry_run:
            print(f"# Would write {len(md)} chars to {out_path}", file=sys.stderr)
            print(md)
        else:
            out_path.write_text(md, encoding="utf-8")
            print(f"# Wrote {len(md)} chars to {out_path}", file=sys.stderr)
    else:
        print(md)


if __name__ == "__main__":
    main()
