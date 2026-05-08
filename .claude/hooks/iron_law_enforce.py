"""Hook: 铁律机械执行 (v2 2026-05-09 V3 实施期扩展).

触发: PreToolUse[Edit|Write]
检查 (v1 sustained): 铁律 2 (验代码) / 4 (中性化) / 5 (回测) / 6 (策略匹配) / 8 (ML OOS) /
                    11 (IC 可追溯) + check_pt_protection PT 核心链路保护
检查 (v2 扩展, sustained Constitution v0.2 §L6.2 line 280-282 决议 + skeleton §3.2 line 304):
  - V3 §11 12 模块 fail-open detect (production code edit 时 fail_open=True / silent_ok 缺失 detect)
  - 铁律 44 X9 Beat schedule 注释 ≠ 停服 detect (configs/*.yaml + backend/app/celery_beat.py)
  - memory #19/#20 prompt 设计 0 数字 path command detect (prompts/risk/*.yaml)

退出码: 始终 0 (sustained user Q1 (α) 决议 — v1 WARN-only sys.exit(0) sustained 反 silent overwrite
ADR-022; 沿用 PR #280/#281/#282/#283 四 PR WARN ALLOW + hookSpecificOutput cite 体例累积一致;
反 BLOCK exit 2 体例)

scope (Phase 1 narrowed sustained user Q3 (β) + PR #280/#281/#282/#283 四 PR LL-130 候选体例累积):
  - 真账户红线 deferred to redline_pretool_block.py (PR #276) 0 重叠扩展 (sustained Q3 (β) 1/4 类)
  - 3/4 类 hook 静态可达 (V3 §11 fail-open + Beat 注释 + prompt 设计) 沿用 ADR-022 反 abstraction
    premature; full SOP 走 quantmind-v3-anti-pattern-guard skill SOP active CC invoke

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L6.2 line 280 (anti-prompt-design-violation-pretool 合并到 iron_law_enforce 决议)
- Constitution §L6.2 line 282 (4 全新 + 4 现有扩展, 沿用 ADR-022 反 silent overwrite)
- skeleton §3.2 line 304 (现有 hook 扩展真值)
- 铁律 44 X9 (Beat schedule 注释 ≠ 停服)
- memory #19/#20 (prompt 设计 0 hardcoded 数字 path command, broader 47/53+ enforcement)
- skill quantmind-v3-anti-pattern-guard (PR #275, full SOP knowledge layer)
- skill quantmind-v3-prompt-design-laws (PR #275, prompt design 0 hardcode 体例)
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance — Phase 1 narrowed)
- LL-133 候选 (现有 hook v1→v2 lifecycle governance — sustained PR #283 first case + 本 second)
"""

import json
import re
import sys

# v2 扩展: V3 §11 12 模块 production code path fragments (sustained Q3 (β) 1/3 类静态可达).
# 沿用 V3 §11 12 模块: alert / metric / reflector / broker_health / feature_dq / factor_dq /
# rule_engine / risk_decision / signal_gate / position_check / order_check / capital_check.
# Detect on production engines path 才触发 (反 false positive on test files / docs).
V3_MODULE_PATH_FRAGMENTS = [
    "backend/engines/risk",
    "backend/engines/alert",
    "backend/engines/metric",
    "backend/engines/reflector",
    "backend/engines/broker_health",
    "backend/engines/feature_dq",
    "backend/engines/factor_dq",
    "backend/engines/rule_engine",
    "backend/engines/risk_decision",
    "backend/engines/signal_gate",
    "backend/engines/position_check",
    "backend/engines/order_check",
    "backend/engines/capital_check",
]

# v2 扩展: fail-open anti-pattern (V3 §11 module 反 silent fail-open 红线).
# 4 类 reject pattern: fail_open=True literal / except: pass / except Exception: pass / 缺 raise.
# 沿用 # silent_ok 注释 whitelist (铁律 33 同体例).
FAIL_OPEN_PATTERNS = [
    re.compile(r"\bfail_open\s*=\s*True\b"),
    re.compile(r"^\s*except\s*:\s*$\s*^\s*pass\s*$", re.MULTILINE),
    re.compile(r"^\s*except\s+Exception\s*:\s*$\s*^\s*pass\s*$", re.MULTILINE),
]

# v2 扩展: Beat schedule 注释 detect (铁律 44 X9, sustained Q3 (β) 2/3 类静态可达).
# Detect on celery_beat.py / configs/beat_*.yaml / 任 *beat*.py path.
# 注释 schedule entry pattern: `# 'task_name': {` OR `# "task_name": {`.
BEAT_PATH_FRAGMENTS = ["celery_beat", "beat_schedule", "tasks_beat", "beat.py"]
BEAT_COMMENT_PATTERN = re.compile(
    r"^\s*#\s*['\"][\w_\-]+['\"]\s*:\s*\{",
    re.MULTILINE,
)

# v2 扩展: prompt 设计 0 数字 path command (memory #19/#20, sustained Q3 (β) 3/3 类静态可达).
# Detect on prompts/risk/*.yaml only (Phase 1 narrowed scope; .claude/CLAUDE.md 等可能含合法
# example, 反 silent narrow false positive 体例).
PROMPT_PATH_FRAGMENTS = ["prompts/risk/"]
# Hardcoded shell command pattern: `python ...` / `bash ...` / `git ...` / `pytest ...` 等.
PROMPT_COMMAND_PATTERN = re.compile(
    r"`(python|bash|git|pytest|npm|gh|cd|ruff|pip)\s+[\w\-\./]",
)


def check_law_2_verify_code(file_path: str, content: str) -> list[str]:
    """铁律 2: 下结论前验代码 (v1 sustained)."""
    if not file_path.endswith(".md"):
        return []
    conclusion_kw = ["结论", "判定", "决策", "PASS", "FAIL", "KEEP", "Reverted"]
    if not any(kw in content[:2000] for kw in conclusion_kw):
        return []
    evidence_kw = ["grep", "git log", "SELECT", "python", "测试结果", "回测结果", "Sharpe=", "IC=", "验证"]
    if any(kw in content for kw in evidence_kw):
        return []
    return ["铁律 2: 结论性文档未包含代码/数据验证证据."]


def check_law_4_neutralize(file_path: str, content: str) -> list[str]:
    """铁律 4: 因子验证用生产基线+中性化 (v1 sustained)."""
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
    return ["铁律 4: 因子测试未包含中性化验证. raw IC 和 neutralized IC 必须并列展示."]


def check_law_5_backtest(file_path: str, content: str) -> list[str]:
    """铁律 5: 因子入组合前回测验证 (v1 sustained)."""
    norm = file_path.replace("\\", "/").lower()
    if not norm.endswith(".py"):
        return []
    if not (("factor" in norm or "backtest" in norm) and
            any(kw in content[:1000] for kw in ["组合", "portfolio", "入池", "入选", "上线"])):
        return []
    bt_kw = ["backtest", "回测", "paired_bootstrap", "bootstrap", "backtest_engine"]
    if any(kw in content.lower() for kw in bt_kw):
        return []
    return ["铁律 5: 因子入组合评估未包含回测验证. 需 paired bootstrap p<0.05."]


def check_law_6_strategy_match(file_path: str, content: str) -> list[str]:
    """铁律 6: 因子评估前确定匹配策略 (v1 sustained)."""
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
    return ["铁律 6: 因子评估未包含策略匹配. RANKING/FAST_RANKING/EVENT 不混用."]


def check_law_8_ml_oos(file_path: str, content: str) -> list[str]:
    """铁律 8: ML 实验必须 OOS 验证 (v1 sustained)."""
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
    return ["铁律 8: ML 脚本未包含 OOS 验证. 训练/验证/测试三段分离."]


def check_law_11_ic_traceable(file_path: str, content: str) -> list[str]:
    """铁律 11: IC 必须有可追溯的入库记录 (v1 sustained)."""
    if not file_path.endswith(".py") and not file_path.endswith(".md"):
        return []
    ic_decision_kw = ["IC=", "ic=", "IC_mean", "gate_ic", "优先级", "入池", "入选"]
    factor_kw = ["factor", "因子", "alpha"]
    has_ic_ref = any(kw in content for kw in ic_decision_kw)
    has_factor = any(kw in content.lower() for kw in factor_kw)
    if has_ic_ref and has_factor:
        traceable_kw = ["factor_ic_history", "compute_factor_ic", "compute_ic", "ic_results.csv"]
        if not any(kw in content for kw in traceable_kw):
            return ["铁律 11: 引用了因子 IC 做决策但无可追溯计算来源. factor_ic_history 无记录的 IC 视为不存在."]
    return []


def check_pt_protection(file_path: str) -> list[str]:
    """PT 核心链路文件保护提醒 (v1 sustained)."""
    norm = file_path.replace("\\", "/").lower()
    pt_files = ["signal_service.py", "execution_service.py", "run_paper_trading.py"]
    if any(f in norm for f in pt_files):
        return ["⚠️ PT 核心链路文件, 修改前确认不影响线上运行."]
    return []


def check_v3_module_fail_open(file_path: str, content: str) -> list[str]:
    """v2 扩展: V3 §11 12 模块 fail-open detect (sustained Q3 (β) 1/3 类静态可达).

    沿用 V3 §11 fail-loud 红线 + skill quantmind-v3-anti-pattern-guard SOP. fail-open
    pattern 必带 # silent_ok 注释 whitelist (沿用铁律 33 同体例). Phase 1 hook 静态 detect
    fail_open=True literal + 裸 except: pass; full SOP deferred to skill SOP active CC invoke.
    """
    norm = file_path.replace("\\", "/").lower()
    if not norm.endswith(".py"):
        return []
    is_v3_module = any(frag in norm for frag in V3_MODULE_PATH_FRAGMENTS)
    if not is_v3_module:
        return []
    issues = []
    for pat in FAIL_OPEN_PATTERNS:
        match = pat.search(content)
        if match:
            # whitelist: # silent_ok 注释 (沿用铁律 33).
            # Check 5 lines around match for silent_ok comment.
            start = max(0, content.rfind("\n", 0, match.start()))
            end = content.find("\n\n", match.end())
            if end == -1:
                end = min(len(content), match.end() + 200)
            ctx = content[start:end]
            if "silent_ok" in ctx:
                continue
            issues.append(
                f"V3 §11 12 模块 fail-open detect: {file_path} 含 fail-open pattern "
                f"({match.group()!r}) 但缺 `# silent_ok` 注释 (沿用铁律 33 + V3 §11 fail-loud 红线; "
                f"full SOP 走 quantmind-v3-anti-pattern-guard skill SOP active CC invoke)."
            )
    return issues


def check_beat_schedule_comment(file_path: str, content: str) -> list[str]:
    """v2 扩展: Beat schedule 注释 ≠ 停服 (铁律 44 X9, sustained Q3 (β) 2/3 类静态可达).

    沿用 LL-097 Beat schedule comment ≠ 停服 + 铁律 44 X9. Phase 1 hook 静态 detect 注释
    schedule entry pattern; full ops checklist (post-merge restart 提醒) deferred to PR
    description SOP active CC invoke.
    """
    norm = file_path.replace("\\", "/").lower()
    is_beat = any(frag in norm for frag in BEAT_PATH_FRAGMENTS)
    if not is_beat:
        return []
    matches = BEAT_COMMENT_PATTERN.findall(content)
    if matches:
        return [
            f"铁律 44 X9: {file_path} 含 Beat schedule 注释 (matched {len(matches)} entries). "
            f"注释 ≠ 停服 — schedule 类 PR 必含 post-merge ops checklist (显式 restart Servy "
            f"QuantMind-CeleryBeat 服务). 沿用 LL-097 体例."
        ]
    return []


def check_prompt_design_no_hardcode(file_path: str, content: str) -> list[str]:
    """v2 扩展: prompt 设计 0 hardcoded 数字 path command (memory #19/#20, Q3 (β) 3/3 类静态可达).

    沿用 memory #19/#20 broader 47/53+ enforcement layer + skill quantmind-v3-prompt-design-laws
    SOP. Phase 1 hook 静态 detect hardcoded shell command pattern (prompts/risk/*.yaml only,
    反 false positive on .claude/CLAUDE.md 等含合法 example doc); full SOP (数字/path
    detection) deferred to skill SOP active CC invoke.
    """
    norm = file_path.replace("\\", "/").lower()
    is_prompt = any(frag in norm for frag in PROMPT_PATH_FRAGMENTS) and norm.endswith(".yaml")
    if not is_prompt:
        return []
    matches = PROMPT_COMMAND_PATTERN.findall(content)
    if matches:
        unique = sorted(set(matches))[:5]
        return [
            f"memory #19/#20: {file_path} 含 hardcoded shell command pattern ({unique!r}). "
            f"prompt 设计 0 数字/path/command 体例 — Claude.ai 走 reference / cite source "
            f"替代 hardcode. 沿用 quantmind-v3-prompt-design-laws skill SOP active CC invoke "
            f"(Phase 1 hook = static command detect only, full SOP 数字/path detect deferred)."
        ]
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
        # v1 sustained checks
        all_issues.extend(check_law_2_verify_code(file_path, content))
        all_issues.extend(check_law_4_neutralize(file_path, content))
        all_issues.extend(check_law_5_backtest(file_path, content))
        all_issues.extend(check_law_6_strategy_match(file_path, content))
        all_issues.extend(check_law_8_ml_oos(file_path, content))
        all_issues.extend(check_law_11_ic_traceable(file_path, content))
        # v2 扩展 checks (sustained user Q3 (β) 3/3 类静态可达)
        all_issues.extend(check_v3_module_fail_open(file_path, content))
        all_issues.extend(check_beat_schedule_comment(file_path, content))
        all_issues.extend(check_prompt_design_no_hardcode(file_path, content))
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
