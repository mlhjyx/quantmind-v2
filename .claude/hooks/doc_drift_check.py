"""Harness Tool: 文档-代码漂移检测器 — 熵管理层。

不是hook，是独立脚本。可手动运行或通过scheduled task定期执行。
检查设计文档与实际代码的一致性。

用法: python .claude/hooks/doc_drift_check.py
"""

import subprocess
import sys
from pathlib import Path


def check_ddl_vs_db(project_root: Path) -> list[str]:
    """检查DDL_FINAL.sql中定义的表是否都在数据库中存在。"""
    issues = []
    ddl_file = project_root / "docs" / "QUANTMIND_V2_DDL_FINAL.sql"
    if not ddl_file.exists():
        return ["DDL_FINAL.sql not found"]

    content = ddl_file.read_text(encoding="utf-8")
    import re

    # 提取CREATE TABLE语句中的表名
    tables_in_ddl = re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", content, re.IGNORECASE)

    if not tables_in_ddl:
        return ["No CREATE TABLE statements found in DDL"]

    # 检查数据库（需要psql可用）
    try:
        result = subprocess.run(
            [
                "psql",
                "-U",
                "xin",
                "-d",
                "quantmind_v2",
                "-t",
                "-c",
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            db_tables = {t.strip() for t in result.stdout.strip().split("\n") if t.strip()}
            ddl_tables = {t.lower() for t in tables_in_ddl}

            missing_in_db = ddl_tables - db_tables
            if missing_in_db:
                issues.append(f"DDL中定义但DB中缺失的表({len(missing_in_db)}): {', '.join(sorted(missing_in_db))}")

            extra_in_db = db_tables - ddl_tables
            # 过滤系统表
            extra_in_db = {t for t in extra_in_db if not t.startswith("_") and t != "spatial_ref_sys"}
            if extra_in_db:
                issues.append(f"DB中存在但DDL未定义的表({len(extra_in_db)}): {', '.join(sorted(extra_in_db))}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        issues.append("psql不可用，跳过DB schema验证")

    return issues


def check_config_params(project_root: Path) -> list[str]:
    """检查DEV_PARAM_CONFIG中定义的参数是否在config.py中存在。"""
    issues = []
    config_file = project_root / "backend" / "app" / "config.py"
    if not config_file.exists():
        return ["backend/app/config.py not found"]

    config_content = config_file.read_text(encoding="utf-8").lower()

    # 关键参数检查
    critical_params = [
        ("TOP_N", "选股数量"),
        ("REBALANCE", "调仓频率"),
        ("SLIPPAGE", "滑点"),
        ("CASH_BUFFER", "现金缓冲"),
    ]

    for param, desc in critical_params:
        if param.lower() not in config_content:
            issues.append(f"关键参数 {param}({desc}) 未在config.py中定义")

    return issues


def check_service_layer(project_root: Path) -> list[str]:
    """检查DEV_BACKEND.md中设计的Service是否已实现。"""
    issues = []
    services_dir = project_root / "backend" / "app" / "services"
    if not services_dir.exists():
        return ["backend/app/services/ directory not found"]

    existing_services = {f.stem for f in services_dir.glob("*.py") if f.stem != "__init__"}

    # 设计中必须的Service
    required_services = [
        "factor_service",
        "signal_service",
        "performance_service",
        "risk_control_service",
    ]

    for svc in required_services:
        if svc not in existing_services:
            issues.append(f"设计文档要求的 {svc} 未实现")

    return issues


def check_doc_freshness(project_root: Path) -> list[str]:
    """检查关键文档的最后修改时间。"""
    issues = []
    critical_docs = [
        "CLAUDE.md",
        "SYSTEM_STATUS.md",
        "docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md",
    ]

    for doc_path in critical_docs:
        full_path = project_root / doc_path
        if not full_path.exists():
            issues.append(f"{doc_path} 不存在")
            continue

        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ar", "--", doc_path],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                age = result.stdout.strip()
                if "month" in age or "year" in age:
                    issues.append(f"{doc_path} 上次更新: {age} — 可能过时")
        except Exception:
            pass

    return issues


def main():
    project_root = Path(__file__).resolve().parent.parent.parent

    print("=" * 60)
    print("QuantMind V2 — 文档-代码漂移检测器 (Harness熵管理)")
    print("=" * 60)

    all_issues = []

    # 1. DDL vs DB
    print("\n[1/4] DDL vs 数据库 schema...")
    ddl_issues = check_ddl_vs_db(project_root)
    all_issues.extend(ddl_issues)
    print(f"  {'PASS' if not ddl_issues else 'ISSUES: ' + str(len(ddl_issues))}")
    for issue in ddl_issues:
        print(f"  ⚠️ {issue}")

    # 2. 参数配置
    print("\n[2/4] 关键参数配置...")
    param_issues = check_config_params(project_root)
    all_issues.extend(param_issues)
    print(f"  {'PASS' if not param_issues else 'ISSUES: ' + str(len(param_issues))}")
    for issue in param_issues:
        print(f"  ⚠️ {issue}")

    # 3. Service层
    print("\n[3/4] Service层实现...")
    svc_issues = check_service_layer(project_root)
    all_issues.extend(svc_issues)
    print(f"  {'PASS' if not svc_issues else 'ISSUES: ' + str(len(svc_issues))}")
    for issue in svc_issues:
        print(f"  ⚠️ {issue}")

    # 4. 文档新鲜度
    print("\n[4/4] 文档新鲜度...")
    fresh_issues = check_doc_freshness(project_root)
    all_issues.extend(fresh_issues)
    print(f"  {'PASS' if not fresh_issues else 'ISSUES: ' + str(len(fresh_issues))}")
    for issue in fresh_issues:
        print(f"  ⚠️ {issue}")

    # 总结
    print("\n" + "=" * 60)
    if all_issues:
        print(f"DRIFT DETECTED: {len(all_issues)} issues found")
        sys.exit(1)
    else:
        print("ALL CLEAR: No drift detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
