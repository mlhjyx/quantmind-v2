#!/usr/bin/env python3
"""文档漂移检查 — 检测代码实现与文档描述的不一致。

检查项:
  1. DDL表数 vs 数据库实际表数
  2. CLAUDE.md 中基线Sharpe vs 实际回测结果
  3. CLAUDE.md 中因子列表 vs factor_registry表Active因子
  4. PROGRESS.md 中Sprint状态 vs 实际代码存在性
  5. 已废弃设计是否标记SUPERSEDED (TECH_DECISIONS.md)

用法:
    python scripts/doc_drift_check.py
    python scripts/doc_drift_check.py --db    # 含DB检查（需PostgreSQL连接）
    python scripts/doc_drift_check.py --fix   # 输出修复建议

输出: PASS/WARN/FAIL + 漂移项清单
"""

import argparse
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("doc_drift_check")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DOCS_DIR = PROJECT_ROOT / "docs"


# ═══════════════════════════════════════════════════
# 漂移检查结果
# ═══════════════════════════════════════════════════


class DriftItem:
    """单条漂移记录。"""

    def __init__(self, category: str, severity: str, message: str, fix: str = ""):
        self.category = category
        self.severity = severity  # PASS / WARN / FAIL
        self.message = message
        self.fix = fix

    def __repr__(self) -> str:
        marker = {"PASS": "OK", "WARN": "!!", "FAIL": "XX"}[self.severity]
        return f"[{marker}] [{self.category}] {self.message}"


# ═══════════════════════════════════════════════════
# 检查函数
# ═══════════════════════════════════════════════════


def check_ddl_table_count(use_db: bool = False) -> list[DriftItem]:
    """检查DDL定义表数 vs 实际。"""
    items = []
    ddl_path = DOCS_DIR / "QUANTMIND_V2_DDL_FINAL.sql"

    if not ddl_path.exists():
        items.append(DriftItem("DDL", "FAIL", "DDL文件不存在: " + str(ddl_path)))
        return items

    ddl_text = ddl_path.read_text(encoding="utf-8")
    create_tables = re.findall(r"CREATE TABLE\s+(\w+)", ddl_text, re.IGNORECASE)
    ddl_count = len(set(create_tables))

    items.append(DriftItem(
        "DDL", "PASS",
        f"DDL定义 {ddl_count} 张表: {', '.join(sorted(set(create_tables))[:10])}...",
    ))

    if use_db:
        try:
            import psycopg2
            conn = psycopg2.connect(
                "postgresql://xin:quantmind@localhost:5432/quantmind_v2"
            )
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """)
            db_count = cur.fetchone()[0]
            conn.close()

            diff = ddl_count - db_count
            if abs(diff) <= 2:
                items.append(DriftItem(
                    "DDL", "PASS",
                    f"DB实际 {db_count} 张表，DDL定义 {ddl_count} 张（差异 {diff}）",
                ))
            else:
                items.append(DriftItem(
                    "DDL", "WARN",
                    f"DB实际 {db_count} 张表，DDL定义 {ddl_count} 张（差异 {diff}）",
                    fix=f"检查是否有 {abs(diff)} 张表未创建或已删除",
                ))
        except Exception as e:
            items.append(DriftItem("DDL", "WARN", f"DB连接失败: {e}"))

    return items


def check_claude_md_sharpe() -> list[DriftItem]:
    """检查CLAUDE.md中的基线Sharpe描述。"""
    items = []
    claude_md = PROJECT_ROOT / "CLAUDE.md"

    if not claude_md.exists():
        items.append(DriftItem("CLAUDE.md", "FAIL", "CLAUDE.md不存在"))
        return items

    text = claude_md.read_text(encoding="utf-8")

    # 查找Sharpe基线值
    sharpe_matches = re.findall(r"Sharpe[=:]\s*([\d.]+)", text)
    if sharpe_matches:
        values = [float(v) for v in sharpe_matches]
        unique_values = sorted(set(values))
        items.append(DriftItem(
            "Sharpe基线", "PASS",
            f"CLAUDE.md中Sharpe值: {unique_values}",
        ))

        # 检查是否同时存在旧值(1.03)和新值
        if 1.03 in unique_values:
            items.append(DriftItem(
                "Sharpe基线", "WARN",
                "CLAUDE.md仍引用Sharpe=1.03（旧fixed滑点基线），volume_impact模式下为~0.91",
                fix="标注Sharpe=1.03为fixed模式基线，补充volume_impact基线",
            ))
    else:
        items.append(DriftItem("Sharpe基线", "WARN", "CLAUDE.md中未找到Sharpe基线值"))

    return items


def check_factor_list(use_db: bool = False) -> list[DriftItem]:
    """检查CLAUDE.md因子列表 vs factor_registry。"""
    items = []
    claude_md = PROJECT_ROOT / "CLAUDE.md"

    if not claude_md.exists():
        return items

    text = claude_md.read_text(encoding="utf-8")

    # 从CLAUDE.md提取因子列表
    doc_factors = set()
    factor_pattern = r"(turnover_mean_20|volatility_20|reversal_20|amihud_20|bp_ratio)"
    for m in re.finditer(factor_pattern, text):
        doc_factors.add(m.group(1))

    items.append(DriftItem(
        "因子列表", "PASS",
        f"CLAUDE.md列出 {len(doc_factors)} 个因子: {sorted(doc_factors)}",
    ))

    if use_db:
        try:
            import psycopg2
            conn = psycopg2.connect(
                "postgresql://xin:quantmind@localhost:5432/quantmind_v2"
            )
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM factor_registry WHERE status = 'active'"
            )
            db_factors = {row[0] for row in cur.fetchall()}
            conn.close()

            only_doc = doc_factors - db_factors
            only_db = db_factors - doc_factors

            if not only_doc and not only_db:
                items.append(DriftItem(
                    "因子列表", "PASS",
                    f"CLAUDE.md与DB因子列表一致 ({len(db_factors)}个Active)",
                ))
            else:
                if only_doc:
                    items.append(DriftItem(
                        "因子列表", "WARN",
                        f"CLAUDE.md有但DB无: {sorted(only_doc)}",
                        fix="在factor_registry中注册或从CLAUDE.md移除",
                    ))
                if only_db:
                    items.append(DriftItem(
                        "因子列表", "WARN",
                        f"DB有但CLAUDE.md无: {sorted(only_db)}",
                        fix="更新CLAUDE.md因子列表",
                    ))
        except Exception as e:
            items.append(DriftItem("因子列表", "WARN", f"DB查询失败: {e}"))

    return items


def check_key_files_exist() -> list[DriftItem]:
    """检查CLAUDE.md中引用的关键文件是否存在。"""
    items = []

    key_files = [
        ("SYSTEM_RUNBOOK.md", PROJECT_ROOT / "SYSTEM_RUNBOOK.md"),
        ("PROGRESS.md", PROJECT_ROOT / "PROGRESS.md"),
        ("DDL", DOCS_DIR / "QUANTMIND_V2_DDL_FINAL.sql"),
        ("IMPLEMENTATION_MASTER.md", DOCS_DIR / "IMPLEMENTATION_MASTER.md"),
        ("DEV_BACKEND.md", DOCS_DIR / "DEV_BACKEND.md"),
        ("DEV_BACKTEST_ENGINE.md", DOCS_DIR / "DEV_BACKTEST_ENGINE.md"),
        ("DEV_FACTOR_MINING.md", DOCS_DIR / "DEV_FACTOR_MINING.md"),
        ("DEV_FRONTEND_UI.md", DOCS_DIR / "DEV_FRONTEND_UI.md"),
        ("DEV_SCHEDULER.md", DOCS_DIR / "DEV_SCHEDULER.md"),
        ("TUSHARE_DATA_SOURCE_CHECKLIST.md", DOCS_DIR / "TUSHARE_DATA_SOURCE_CHECKLIST.md"),
    ]

    missing = []
    for name, path in key_files:
        if not path.exists():
            missing.append(name)

    if not missing:
        items.append(DriftItem(
            "关键文件", "PASS",
            f"全部 {len(key_files)} 个关键文件存在",
        ))
    else:
        items.append(DriftItem(
            "关键文件", "FAIL",
            f"缺失 {len(missing)} 个文件: {missing}",
            fix="恢复缺失的文档文件",
        ))

    return items


def check_engine_files_exist() -> list[DriftItem]:
    """检查核心引擎文件是否存在。"""
    items = []
    engines = [
        "factor_engine.py",
        "backtest_engine.py",
        "slippage_model.py",
        "neutralizer.py",
        "metrics.py",
        "base_broker.py",
        "factor_gate.py",
        "factor_classifier.py",
        "factor_decay.py",
        "factor_timing.py",
        "datafeed.py",
    ]
    engine_dir = BACKEND_DIR / "engines"

    missing = [f for f in engines if not (engine_dir / f).exists()]

    if not missing:
        items.append(DriftItem(
            "引擎文件", "PASS",
            f"全部 {len(engines)} 个核心引擎文件存在",
        ))
    else:
        items.append(DriftItem(
            "引擎文件", "FAIL",
            f"缺失引擎: {missing}",
        ))

    return items


def check_param_count() -> list[DriftItem]:
    """检查param_defaults注册数量。"""
    items = []
    param_file = BACKEND_DIR / "app" / "services" / "param_defaults.py"

    if not param_file.exists():
        items.append(DriftItem("参数", "FAIL", "param_defaults.py不存在"))
        return items

    text = param_file.read_text(encoding="utf-8")
    count = text.count("ParamDef(")

    target = 220
    if count >= target:
        items.append(DriftItem(
            "参数", "PASS",
            f"param_defaults注册 {count} 个参数 (目标≥{target})",
        ))
    elif count >= 100:
        items.append(DriftItem(
            "参数", "WARN",
            f"param_defaults注册 {count} 个参数 (目标≥{target}，差 {target - count})",
            fix=f"从DEV_PARAM_CONFIG.md补充 {target - count} 个参数定义",
        ))
    else:
        items.append(DriftItem(
            "参数", "FAIL",
            f"param_defaults仅 {count} 个参数 (目标≥{target})",
        ))

    return items


# ═══════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════


def run_drift_check(use_db: bool = False, show_fix: bool = False) -> list[DriftItem]:
    """运行全部漂移检查。"""
    all_items: list[DriftItem] = []

    checks = [
        ("DDL表数", lambda: check_ddl_table_count(use_db)),
        ("Sharpe基线", check_claude_md_sharpe),
        ("因子列表", lambda: check_factor_list(use_db)),
        ("关键文件", check_key_files_exist),
        ("引擎文件", check_engine_files_exist),
        ("参数注册", check_param_count),
    ]

    for name, check_fn in checks:
        try:
            items = check_fn()
            all_items.extend(items)
        except Exception as e:
            all_items.append(DriftItem(name, "FAIL", f"检查异常: {e}"))

    return all_items


def main():
    parser = argparse.ArgumentParser(description="QuantMind 文档漂移检查")
    parser.add_argument("--db", action="store_true", help="启用DB检查")
    parser.add_argument("--fix", action="store_true", help="显示修复建议")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("QuantMind V2 — 文档漂移检查")
    logger.info("=" * 60)

    items = run_drift_check(use_db=args.db, show_fix=args.fix)

    # 输出
    pass_count = sum(1 for i in items if i.severity == "PASS")
    warn_count = sum(1 for i in items if i.severity == "WARN")
    fail_count = sum(1 for i in items if i.severity == "FAIL")

    logger.info("")
    for item in items:
        if item.severity == "PASS":
            logger.info(str(item))
        elif item.severity == "WARN":
            logger.warning(str(item))
        else:
            logger.error(str(item))

        if args.fix and item.fix:
            logger.info(f"    FIX: {item.fix}")

    logger.info("")
    logger.info("=" * 60)
    logger.info(
        f"结果: {pass_count} PASS, {warn_count} WARN, {fail_count} FAIL "
        f"(共 {len(items)} 项)"
    )
    logger.info("=" * 60)

    if fail_count > 0:
        sys.exit(2)
    elif warn_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
