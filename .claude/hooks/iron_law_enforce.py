"""Harness Hook: 八条铁律+工作原则机械执行 — 约束层核心。

触发: PreToolUse[Edit|Write]
功能: 在文件写入前，根据文件路径和内容检查是否违反铁律
- 铁律2: 因子测试必须包含中性化
- 铁律3: 因子入组合评估必须包含SimBroker/backtest
- 铁律5: 结论性文档必须包含验证证据
- 铁律7: ML脚本必须包含OOS验证
- 铁律8: 因子评估必须包含strategy匹配
- 工作原则7: 编码目录→对应设计文档提醒
退出码: 0=通过（注入提醒）
"""

import json
import sys


def check_iron_law_2(file_path: str, content: str) -> list[str]:
    """铁律2: 因子验证用生产基线+中性化。"""
    violations = []
    normalized = file_path.replace("\\", "/").lower()

    is_factor_test = (
        ("factor" in normalized or "ic" in normalized)
        and ("test" in normalized or "backtest" in normalized
             or "验证" in content[:500] or "validate" in content[:500])
        and normalized.endswith(".py")
    )

    if is_factor_test:
        neutralize_keywords = [
            "neutralize", "neutral", "中性化", "cross_section",
            "industry", "market_cap", "行业中性", "市值中性",
            "regress", "residual",
        ]
        if not any(kw in content.lower() for kw in neutralize_keywords):
            violations.append(
                "铁律2: 因子测试文件未包含中性化验证。"
                "必须同时展示原始IC和中性化后IC（LL-014）。"
            )
    return violations


def check_iron_law_3(file_path: str, content: str) -> list[str]:
    """铁律3: 因子入组合前SimBroker回测。"""
    violations = []
    normalized = file_path.replace("\\", "/").lower()

    is_factor_portfolio = (
        normalized.endswith(".py")
        and ("factor" in normalized or "backtest" in normalized)
        and any(kw in content[:1000] for kw in [
            "组合", "portfolio", "入池", "入选", "加入", "上线",
        ])
    )

    if is_factor_portfolio:
        simbroker_keywords = [
            "simbroker", "sim_broker", "backtest", "回测",
            "paired_bootstrap", "bootstrap", "backtest_engine",
        ]
        if not any(kw in content.lower() for kw in simbroker_keywords):
            violations.append(
                "铁律3: 因子入组合评估未包含SimBroker回测。"
                "必须paired bootstrap p<0.05才能入池。"
            )
    return violations


def check_iron_law_5(file_path: str, content: str) -> list[str]:
    """铁律5: 下结论前验代码——结论性文档必须有验证证据。"""
    violations = []

    is_conclusion_doc = (
        file_path.endswith(".md")
        and any(kw in content[:2000] for kw in [
            "结论", "判定", "决策", "PASS", "FAIL",
            "NOT JUSTIFIED", "KEEP", "Reverted", "方向关闭",
        ])
    )

    if is_conclusion_doc:
        evidence_keywords = [
            "grep", "git log", "git diff", "查询结果", "验证",
            "SELECT", "python", "运行结果", "输出", "代码确认",
            "实际值", "测试结果", "回测结果", "Sharpe=", "IC=",
        ]
        if not any(kw in content for kw in evidence_keywords):
            violations.append(
                "铁律5: 结论性文档未包含代码/数据验证证据。"
                "下结论前必须验代码——grep/read验证，不信文档（LL-019）。"
            )
    return violations


def check_iron_law_7(file_path: str, content: str) -> list[str]:
    """铁律7: ML实验必须OOS验证。"""
    violations = []

    is_ml_script = (
        file_path.endswith(".py")
        and any(kw in content.lower() for kw in [
            "lightgbm", "lgbm", "xgboost", "sklearn",
            "model.fit", "model.train", "optuna", "deap",
            "gp_engine", "neural", "torch",
        ])
    )

    if is_ml_script:
        oos_keywords = [
            "oos", "out_of_sample", "out-of-sample", "test_set",
            "样本外", "测试集", "validation", "walk_forward",
            "rolling", "test_period", "test_start", "三段",
        ]
        if not any(kw in content.lower() for kw in oos_keywords):
            violations.append(
                "铁律7: ML脚本未包含OOS(样本外)验证。"
                "训练/验证/测试三段分离是强制要求。"
            )
    return violations


def check_iron_law_8(file_path: str, content: str) -> list[str]:
    """铁律8: 因子评估前strategy必须确定匹配策略。"""
    violations = []
    normalized = file_path.replace("\\", "/").lower()

    is_factor_eval = (
        normalized.endswith(".py")
        and ("factor" in normalized or "backtest" in normalized)
        and any(kw in content.lower()[:1000] for kw in [
            "因子", "factor", "alpha", "ic",
        ])
    )

    if is_factor_eval:
        strategy_keywords = [
            "strategy", "策略", "匹配策略", "ic_decay", "调仓频率",
            "rebalance_freq", "factor_classifier", "signal_type",
            "排序型", "过滤型", "事件型", "调节型",
            "weekly", "monthly", "daily", "event_driven",
        ]
        if not any(kw in content.lower() for kw in strategy_keywords):
            violations.append(
                "铁律8: 因子评估未包含策略匹配信息。"
                "ic_decay→调仓频率/权重/选股方式（LL-027）。"
                "不是所有因子都用等权Top15月度。"
            )
    return violations


def check_design_doc_reference(file_path: str, content: str) -> list[str]:
    """工作原则7: 编码前对照设计文档提醒。"""
    warnings = []
    normalized = file_path.replace("\\", "/").lower()

    if not any(normalized.endswith(ext) for ext in (".py", ".tsx", ".ts")):
        return warnings

    # 目录→对应设计文档映射
    dir_doc_map = [
        ("backend/app/services/", "DEV_BACKEND.md"),
        ("backend/app/api/", "DEV_BACKEND.md"),
        ("backend/engines/mining/", "DEV_FACTOR_MINING.md"),
        ("backend/engines/", "DEV_BACKTEST_ENGINE.md"),
        ("backend/app/tasks/", "DEV_SCHEDULER.md"),
        ("backend/integrations/", "DEV_AI_EVOLUTION.md"),
        ("frontend/src/", "DEV_FRONTEND_UI.md"),
    ]

    for dir_pattern, doc_name in dir_doc_map:
        if dir_pattern in normalized:
            warnings.append(
                f"工作原则7: 正在写入 {dir_pattern} 目录，"
                f"对应设计文档: docs/{doc_name}。"
                f"编码前请先阅读确认功能规格（宪法§9.7）。"
            )
            break

    return warnings


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "")

    # Edit工具没有content字段，只有new_string
    if not content:
        content = tool_input.get("new_string", "")

    if not file_path or not content:
        sys.exit(0)

    # 运行所有检查
    all_issues = []
    all_issues.extend(check_iron_law_2(file_path, content))
    all_issues.extend(check_iron_law_3(file_path, content))
    all_issues.extend(check_iron_law_5(file_path, content))
    all_issues.extend(check_iron_law_7(file_path, content))
    all_issues.extend(check_iron_law_8(file_path, content))
    all_issues.extend(check_design_doc_reference(file_path, content))

    if not all_issues:
        sys.exit(0)

    issues_text = "\n".join(f"  - {issue}" for issue in all_issues)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"IRON LAW CHECK ({len(all_issues)} issues):\n"
                f"{issues_text}\n\n"
                "这些是TEAM_CHARTER_V3.3 §2不可协商规则。"
                "如果检测不适用，可以忽略；如果确实违反，请立即修正。"
            ),
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
