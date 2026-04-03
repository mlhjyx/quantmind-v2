"""Hook: 10条铁律机械执行。

触发: PreToolUse[Edit|Write]
检查: 铁律2(验代码) 4(中性化) 5(回测) 6(策略匹配) 8(ML OOS)
退出码: 0=通过（注入提醒）
"""

import json
import sys


def check_law_2_verify_code(file_path: str, content: str) -> list[str]:
    """铁律2: 下结论前验代码。"""
    if not file_path.endswith(".md"):
        return []
    conclusion_kw = ["结论", "判定", "决策", "PASS", "FAIL", "KEEP", "Reverted"]
    if not any(kw in content[:2000] for kw in conclusion_kw):
        return []
    evidence_kw = ["grep", "git log", "SELECT", "python", "测试结果", "回测结果", "Sharpe=", "IC=", "验证"]
    if any(kw in content for kw in evidence_kw):
        return []
    return ["铁律2: 结论性文档未包含代码/数据验证证据。"]


def check_law_4_neutralize(file_path: str, content: str) -> list[str]:
    """铁律4: 因子验证用生产基线+中性化。"""
    norm = file_path.replace("\\", "/").lower()
    is_factor_test = (
        ("factor" in norm or "ic" in norm)
        and ("test" in norm or "backtest" in norm or "验证" in content[:500])
        and norm.endswith(".py")
    )
    if not is_factor_test:
        return []
    neutral_kw = ["neutralize", "neutral", "中性化", "industry", "market_cap", "residual"]
    if any(kw in content.lower() for kw in neutral_kw):
        return []
    return ["铁律4: 因子测试未包含中性化验证。raw IC和neutralized IC必须并列展示。"]


def check_law_5_backtest(file_path: str, content: str) -> list[str]:
    """铁律5: 因子入组合前回测验证。"""
    norm = file_path.replace("\\", "/").lower()
    if not norm.endswith(".py"):
        return []
    if not (("factor" in norm or "backtest" in norm) and
            any(kw in content[:1000] for kw in ["组合", "portfolio", "入池", "入选", "上线"])):
        return []
    bt_kw = ["backtest", "回测", "paired_bootstrap", "bootstrap", "backtest_engine"]
    if any(kw in content.lower() for kw in bt_kw):
        return []
    return ["铁律5: 因子入组合评估未包含回测验证。需paired bootstrap p<0.05。"]


def check_law_6_strategy_match(file_path: str, content: str) -> list[str]:
    """铁律6: 因子评估前确定匹配策略。"""
    norm = file_path.replace("\\", "/").lower()
    if not norm.endswith(".py"):
        return []
    if not (("factor" in norm or "backtest" in norm) and
            any(kw in content.lower()[:1000] for kw in ["因子", "factor", "alpha", "ic"])):
        return []
    strat_kw = ["strategy", "策略", "ic_decay", "rebalance_freq", "RANKING", "FAST_RANKING",
                "EVENT", "monthly", "weekly", "event_driven"]
    if any(kw in content for kw in strat_kw):
        return []
    return ["铁律6: 因子评估未包含策略匹配。RANKING/FAST_RANKING/EVENT不混用。"]


def check_law_8_ml_oos(file_path: str, content: str) -> list[str]:
    """铁律8: ML实验必须OOS验证。"""
    if not file_path.endswith(".py"):
        return []
    ml_kw = ["lightgbm", "lgbm", "xgboost", "sklearn", "model.fit", "model.train",
             "optuna", "deap", "gp_engine", "torch"]
    if not any(kw in content.lower() for kw in ml_kw):
        return []
    oos_kw = ["oos", "out_of_sample", "out-of-sample", "test_set", "样本外",
              "validation", "walk_forward", "三段"]
    if any(kw in content.lower() for kw in oos_kw):
        return []
    return ["铁律8: ML脚本未包含OOS验证。训练/验证/测试三段分离。"]


def check_law_11_ic_traceable(file_path: str, content: str) -> list[str]:
    """铁律11: IC必须有可追溯的入库记录。"""
    if not file_path.endswith(".py") and not file_path.endswith(".md"):
        return []
    # 检测引用IC数字做决策的模式
    ic_decision_kw = ["IC=", "ic=", "IC_mean", "gate_ic", "优先级", "入池", "入选"]
    factor_kw = ["factor", "因子", "alpha"]
    has_ic_ref = any(kw in content for kw in ic_decision_kw)
    has_factor = any(kw in content.lower() for kw in factor_kw)
    if has_ic_ref and has_factor:
        traceable_kw = ["factor_ic_history", "compute_factor_ic", "compute_ic", "ic_results.csv"]
        if not any(kw in content for kw in traceable_kw):
            return ["铁律11: 引用了因子IC做决策但无可追溯计算来源。factor_ic_history无记录的IC视为不存在。"]
    return []


def check_pt_protection(file_path: str) -> list[str]:
    """PT核心链路文件保护提醒。"""
    norm = file_path.replace("\\", "/").lower()
    pt_files = ["signal_service.py", "execution_service.py", "run_paper_trading.py"]
    if any(f in norm for f in pt_files):
        return ["⚠️ PT核心链路文件，修改前确认不影响线上运行。"]
    return []


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "") or tool_input.get("new_string", "")

    if not file_path:
        sys.exit(0)

    all_issues = []
    if content:
        all_issues.extend(check_law_2_verify_code(file_path, content))
        all_issues.extend(check_law_4_neutralize(file_path, content))
        all_issues.extend(check_law_5_backtest(file_path, content))
        all_issues.extend(check_law_6_strategy_match(file_path, content))
        all_issues.extend(check_law_8_ml_oos(file_path, content))
        all_issues.extend(check_law_11_ic_traceable(file_path, content))
    all_issues.extend(check_pt_protection(file_path))

    if not all_issues:
        sys.exit(0)

    issues_text = "\n".join(f"  - {issue}" for issue in all_issues)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": issues_text,
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
