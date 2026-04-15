#!/usr/bin/env python3
"""审计: 检查生产代码绕过 DataPipeline 直接 INSERT 生产表 (铁律 17)。

用法:
    python scripts/audit/check_insert_bypass.py          # 仅扫描 backend/app + backend/engines
    python scripts/audit/check_insert_bypass.py --all    # 含 scripts/ 和 backend/scripts/
    python scripts/audit/check_insert_bypass.py --json   # JSON 输出
    python scripts/audit/check_insert_bypass.py --baseline scripts/audit/insert_bypass_baseline.json
                                                          # pre-commit 模式: 只拒新增违规,
                                                          # baseline 中的已知债务不阻断

铁律 17 原文:
    "数据入库必须通过 DataPipeline — 禁止直接 INSERT INTO 生产表.
     DataPipeline.ingest(df, Contract) 负责 rename → 列对齐 → 单位转换 →
     值域验证 → FK 过滤 → Upsert. 违反→重新引入单位混乱/code 格式不一致等历史技术债."

S3 F86 背景:
    S4 发现 factor_values 有 1665 行 float NaN (违反铁律 29), 根因是 4 条
    生产 INSERT 路径绕过 DataPipeline 的 fillna(None). S3 要求此脚本作为
    pre-commit 或 CI 门禁, 防止 F66 类问题复发.

Phase B M1 (2026-04-15) 接入 pre-commit:
    `scripts/git_hooks/pre-commit` 调用本脚本 `--baseline insert_bypass_baseline.json`.
    baseline 冻结 3 条已知债务 (fetch_base_data ×2 + factor_engine 文档字符串误报 ×1),
    新增违规 → 阻断 commit. 安装: `bash scripts/install_git_hooks.sh`.

退出码:
    0 = 无违规, 或仅有 baseline 已知债务
    1 = 有新增违规 (阻断 commit)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 受保护的生产表 (在 factor_values 之外, 铁律 17 覆盖所有核心数据表)
PRODUCTION_TABLES = [
    "factor_values",
    "factor_ic_history",
    "klines_daily",
    "daily_basic",
    "minute_bars",
    "moneyflow_daily",
]

# 默认扫描路径 (生产代码)
PROD_SCAN_PATHS = [
    Path("backend/app"),
    Path("backend/engines"),
]

# 扩展扫描路径 (scripts, 研究脚本可接受但需登记)
EXT_SCAN_PATHS = [
    Path("scripts"),
    Path("backend/scripts"),
]

# 白名单: 以下文件允许直接 INSERT (DataPipeline 本身 + 测试)
WHITELIST = [
    "backend/app/data_fetcher/pipeline.py",  # DataPipeline 本身
    "backend/tests/",  # 测试层可直接构造数据
    "scripts/archive/",  # 归档脚本不纳入治理
]

# 研究脚本豁免 (研究可接受但需在报告中列出, 便于追踪)
RESEARCH_SOFT_WHITELIST = [
    "scripts/research/",
]


def _is_whitelisted(rel_path: str) -> bool:
    """判断是否在硬白名单。"""
    return any(rel_path.endswith(w) or w in rel_path for w in WHITELIST)


def _is_research(rel_path: str) -> bool:
    """判断是否是研究脚本 (软豁免)。"""
    return any(w in rel_path for w in RESEARCH_SOFT_WHITELIST)


def _load_baseline(path: Path) -> list[dict]:
    """加载 baseline JSON, 返回已知债务 entry 列表。

    Baseline 格式:
        {
          "version": 1,
          "generated_at": "YYYY-MM-DD",
          "known_debt": [
            {
              "file": "backend/app/.../xxx.py",
              "code_prefix": "INSERT INTO ...",  # 匹配 code.strip() 前缀
              "ticket": "F86 long-term refactor",
              "rationale": "..."
            },
            ...
          ]
        }

    匹配规则: violation.file == entry.file AND violation.code.strip().startswith(entry.code_prefix)
    行号不参与匹配 (代码编辑会导致行号漂移)。
    """
    if not path.exists():
        print(
            f"[warning] baseline 文件不存在: {path} (将视为空 baseline)",
            file=sys.stderr,
        )
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("known_debt", [])
    except Exception as e:
        print(f"[warning] baseline 加载失败: {e}", file=sys.stderr)
        return []


def _is_baselined(violation: dict, baseline: list[dict]) -> bool:
    """判断违规是否匹配 baseline 中的已知债务 entry。"""
    v_file = violation["file"]
    v_code_stripped = violation["code"].strip()
    for entry in baseline:
        if entry.get("file") != v_file:
            continue
        prefix = entry.get("code_prefix", "")
        if not prefix:
            continue
        if v_code_stripped.startswith(prefix):
            return True
    return False


def scan_file(py_path: Path, pattern: re.Pattern) -> list[tuple[int, str]]:
    """扫描单个 .py 文件, 返回 [(line_num, code), ...]。"""
    violations: list[tuple[int, str]] = []
    try:
        text = py_path.read_text(encoding="utf-8")
    except Exception:
        return violations
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        # 跳过注释和文档字符串内的 "INSERT INTO" 字面量
        if stripped.startswith("#"):
            continue
        if pattern.search(line):
            violations.append((i, line.strip()))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all",
        action="store_true",
        help="含 scripts/ 和 backend/scripts/ (默认仅扫生产代码)",
    )
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="baseline JSON 文件, 忽略其中登记的已知债务 (pre-commit 模式)",
    )
    args = parser.parse_args()

    tables_alt = "|".join(PRODUCTION_TABLES)
    # 匹配行起始 INSERT (SQL 块格式), 不匹配行中间的散文引用.
    # 接受模式: `^    INSERT INTO` (缩进 SQL) 或 `^    """INSERT INTO` (紧跟三引号)
    # 拒绝模式: `^    ⚠️ ... 直接 INSERT INTO ...` (散文中的引用)
    pattern = re.compile(
        rf"""^\s*(['"]+\s*)?INSERT\s+INTO\s+({tables_alt})\b""",
        re.IGNORECASE,
    )

    scan_paths = PROD_SCAN_PATHS + (EXT_SCAN_PATHS if args.all else [])
    prod_violations: list[dict] = []
    research_hits: list[dict] = []

    for base in scan_paths:
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            rel = str(py.as_posix())
            if _is_whitelisted(rel):
                continue
            hits = scan_file(py, pattern)
            if not hits:
                continue
            for line_num, code in hits:
                item = {"file": rel, "line": line_num, "code": code[:100]}
                if _is_research(rel):
                    research_hits.append(item)
                else:
                    prod_violations.append(item)

    # Baseline 拆分: 已知债务 vs 新增违规
    baseline = _load_baseline(args.baseline) if args.baseline else []
    new_violations: list[dict] = []
    known_debt: list[dict] = []
    for v in prod_violations:
        if _is_baselined(v, baseline):
            known_debt.append(v)
        else:
            new_violations.append(v)

    if args.json:
        print(
            json.dumps(
                {
                    "new_violations": new_violations,
                    "known_debt": known_debt,
                    "research_soft_hits": research_hits,
                    "exit_code": 1 if new_violations else 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if new_violations:
            print(
                f"❌ 铁律 17 新增违规 (阻断 commit): {len(new_violations)} 处",
                flush=True,
            )
            for v in new_violations:
                print(f"  {v['file']}:{v['line']}  {v['code']}")
            print(
                "\n修复: 使用 DataPipeline.ingest(df, Contract) 替代。\n"
                "见 backend/app/data_fetcher/pipeline.py + contracts.py。\n"
                "参考 CLAUDE.md 铁律 17 + S1 F17 + S3 F86。\n"
                "紧急绕过: git commit --no-verify (仅在你确定违规是误报时)。"
            )
        elif known_debt:
            print(
                f"✅ 无新增违规 (baseline 中有 {len(known_debt)} 条已知债务, 不阻断 commit)"
            )
            for v in known_debt:
                print(f"  [known_debt] {v['file']}:{v['line']}  {v['code'][:80]}")
        else:
            print("✅ 生产代码无违规: 所有 INSERT 生产表都走 DataPipeline。")

        if research_hits:
            print(
                f"\n⚠️  研究脚本软豁免 (登记但不阻断): {len(research_hits)} 处"
            )
            for v in research_hits[:10]:
                print(f"  {v['file']}:{v['line']}  {v['code'][:80]}")
            if len(research_hits) > 10:
                print(f"  ... 共 {len(research_hits)} 处, 使用 --json 查看完整列表")

    return 1 if new_violations else 0


if __name__ == "__main__":
    sys.exit(main())
