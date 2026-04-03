"""Hook: 量化铁律机械执行（6条精简版）。

触发: PreToolUse[Edit|Write]
检查: 铁律1(中性化) 2(回测) 3(验代码) 4(ML OOS) 5(策略匹配) 6(更新文档)
退出码: 0=通过（注入提醒）
"""

import json
import sys


def check_law_1_neutralize(file_path: str, content: str) -> list[str]:
    """铁律1: 因子验证用生产基线+中性化。"""
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
                "铁律1: 因子测试文件未包含中性化验证。"
                "必须同时展示原始IC和中性化后IC。"
            )
    return violations


def check_law_2_backtest(file_path: str, content: str) -> list[str]:
    """铁律2: 因子入组合前回测验证。"""
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
        backtest_keywords = [
            "simbroker", "sim_broker", "backtest", "回测",
            "paired_bootstrap", "bootstrap", "backtest_engine",
        ]
        if not any(kw in content.lower() for kw in backtest_keywords):
            violations.append(
                "铁律2: 因子入组合评估未包含回测验证。"
                "必须paired bootstrap p<0.05。"
            )
    return violations


def check_law_3_verify_code(file_path: str, content: str) -> list[str]:
    """铁律3: 下结论前验代码。"""
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
                "铁律3: 结论性文档未包含代码/数据验证证据。"
            )
    return violations


def check_law_4_ml_oos(file_path: str, content: str) -> list[str]:
    """铁律4: ML实验必须OOS验证。"""
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
                "铁律4: ML脚本未包含OOS(样本外)验证。"
            )
    return violations


def check_law_5_strategy_match(file_path: str, content: str) -> list[str]:
    """铁律5: 因子评估前确定匹配策略。"""
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
            "RANKING", "FAST_RANKING", "EVENT",
        ]
        if not any(kw in content.lower() for kw in strategy_keywords):
            violations.append(
                "铁律5: 因子评估未包含策略匹配信息。"
                "ic_decay→调仓频率，RANKING/FAST_RANKING/EVENT不混用。"
            )
    return violations


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "") or tool_input.get("new_string", "")

    if not file_path or not content:
        sys.exit(0)

    all_issues = []
    all_issues.extend(check_law_1_neutralize(file_path, content))
    all_issues.extend(check_law_2_backtest(file_path, content))
    all_issues.extend(check_law_3_verify_code(file_path, content))
    all_issues.extend(check_law_4_ml_oos(file_path, content))
    all_issues.extend(check_law_5_strategy_match(file_path, content))

    if not all_issues:
        sys.exit(0)

    issues_text = "\n".join(f"  - {issue}" for issue in all_issues)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"IRON LAW CHECK ({len(all_issues)} issues):\n"
                f"{issues_text}\n\n"
                "如果检测不适用可以忽略；如果确实违反请立即修正。"
            ),
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
