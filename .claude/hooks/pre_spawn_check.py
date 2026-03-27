"""Harness Hook: Agent spawn前质量+路由检查 — 约束层。

触发: PreToolUse[Agent]
功能:
1. 宪法完整性: spawn prompt必须包含角色定义+Sprint上下文+铁律
2. 任务-角色路由: 检测任务描述关键词，提醒应使用的自定义agent角色
3. OMC白名单: 插件内部agent(Explore/Plan等)直接放行
退出码: 0=通过（可能注入提醒）
"""

import json
import sys


# ===== 宪法完整性检查关键词 =====
ROLE_KEYWORDS = [
    "职责", "你是QuantMind", "你的职责", "核心职能", "角色",
    "_charter_context", "charter_context", "宪法",
]
CONTEXT_KEYWORDS = [
    "Sprint", "Paper Trading", "当前状态", "PROGRESS",
    "IMPLEMENTATION_MASTER", "实施总纲",
]
CONSTRAINT_KEYWORDS = [
    "铁律", "中性化", "SimBroker", "OOS", "PROGRESS.md",
    "交叉审查", "因子审批", "ic_decay", "paired bootstrap",
]

# ===== 任务→角色路由表 (来自CLAUDE.md/宪法§1.1) =====
TASK_ROLE_ROUTING = [
    {
        "keywords": ["service", "api", "fastapi", "celery", "backend", "引擎",
                      "broker", "composite", "nssm", "调度", "scheduler"],
        "role": "arch",
        "desc": "后端编码/架构/引擎",
    },
    {
        "keywords": ["test", "测试", "qa", "pytest", "验证", "破坏", "边界"],
        "role": "qa-tester",
        "desc": "测试/质量/验证",
    },
    {
        "keywords": ["ic", "sharpe", "统计", "t值", "bootstrap", "过拟合",
                      "gate", "bh-fdr", "harvey"],
        "role": "quant-reviewer",
        "desc": "量化逻辑/统计审查",
    },
    {
        "keywords": ["因子研究", "经济学假设", "alpha158", "因子分类",
                      "生命周期", "ic_decay"],
        "role": "factor-researcher",
        "desc": "因子研究/经济学假设",
    },
    {
        "keywords": ["策略设计", "strategy", "modifier", "composite",
                      "classifier", "调仓频率", "匹配策略", "归因"],
        "role": "strategy-designer",
        "desc": "策略设计/因子匹配/Modifier",
    },
    {
        "keywords": ["风险", "risk", "熔断", "mdd", "压力测试", "drawdown",
                      "止损", "风控"],
        "role": "risk-guardian",
        "desc": "风险评估/熔断/压力测试",
    },
    {
        "keywords": ["数据拉取", "tushare", "akshare", "备份", "pg_dump",
                      "单位", "数据质量"],
        "role": "data-engineer",
        "desc": "数据拉取/质量/备份",
    },
    {
        "keywords": ["因子挖掘", "mining", "pipeline", "暴力", "brute",
                      "sandbox", "ast去重"],
        "role": "alpha-miner",
        "desc": "因子挖掘/Pipeline",
    },
    {
        "keywords": ["lightgbm", "lgbm", "gp引擎", "deap", "deepseek",
                      "optuna", "ml", "模型训练"],
        "role": "ml-engineer",
        "desc": "ML训练/GP引擎/DeepSeek",
    },
    {
        "keywords": ["react", "frontend", "前端", "页面", "tsx", "组件",
                      "tailwind", "echarts", "zustand"],
        "role": "frontend-dev",
        "desc": "React前端/页面开发",
    },
]

# OMC内部agent类型 — 不需要宪法上下文
OMC_AGENT_TYPES = {
    "oh-my-claudecode:", "omc-", "code-reviewer", "code-simplifier",
    "Explore", "Plan", "general-purpose", "claude-code-guide",
    "feature-dev:", "hookify:", "superpowers:", "statusline-setup",
}

SHORT_PROMPT_THRESHOLD = 100


def is_omc_internal(tool_input: dict) -> bool:
    """判断是否是OMC插件内部的agent调用。"""
    subagent_type = tool_input.get("subagent_type", "")
    description = tool_input.get("description", "")
    prompt = tool_input.get("prompt", "")

    for omc_type in OMC_AGENT_TYPES:
        if subagent_type.startswith(omc_type) or subagent_type == omc_type.rstrip(":"):
            return True

    omc_desc_keywords = ["omc", "hook", "skill", "plugin", "setup"]
    combined = (description + " " + prompt).lower()
    if any(kw in combined for kw in omc_desc_keywords):
        return True

    return False


def check_spawn_quality(prompt: str) -> list[str]:
    """检查spawn prompt宪法完整性。"""
    missing = []

    if not any(kw in prompt for kw in ROLE_KEYWORDS):
        missing.append("角色定义（引用_charter_context.md或明确职责）")

    if not any(kw in prompt for kw in CONTEXT_KEYWORDS):
        missing.append("Sprint上下文（当前Sprint编号/Paper Trading状态）")

    if not any(kw in prompt for kw in CONSTRAINT_KEYWORDS):
        missing.append("约束条件（至少一条铁律或关键工作原则）")

    return missing


def check_role_routing(tool_input: dict) -> str | None:
    """检测任务描述，建议应使用的自定义agent角色。"""
    subagent_type = tool_input.get("subagent_type", "")
    description = tool_input.get("description", "")
    prompt = tool_input.get("prompt", "")
    combined = (description + " " + prompt).lower()

    # 已经指定了我们的自定义角色 → 不需要提醒
    our_roles = {
        "arch", "qa-tester", "quant-reviewer", "factor-researcher",
        "strategy-designer", "risk-guardian", "data-engineer",
        "alpha-miner", "ml-engineer", "frontend-dev",
    }
    if subagent_type in our_roles:
        return None

    # 检测任务关键词匹配
    matched_roles = []
    for route in TASK_ROLE_ROUTING:
        score = sum(1 for kw in route["keywords"] if kw in combined)
        if score >= 2:  # 至少匹配2个关键词才算
            matched_roles.append((score, route["role"], route["desc"]))

    if matched_roles:
        matched_roles.sort(reverse=True)
        best = matched_roles[0]
        return (
            f"Agent路由建议: 任务匹配 '{best[2]}' → 应使用自定义角色 '{best[1]}'。\n"
            f"  宪法§1.1要求: 领域任务必须分配给对应领域角色。\n"
            f"  角色定义: .claude/agents/{best[1]}.md\n"
            f"  如果当前spawn是正确的（通用查询/跨领域任务），可以忽略此提醒。"
        )

    return None


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    prompt = tool_input.get("prompt", "")

    # OMC内部agent直接放行
    if is_omc_internal(tool_input):
        sys.exit(0)

    # 短prompt直接放行
    if len(prompt) < SHORT_PROMPT_THRESHOLD:
        sys.exit(0)

    issues = []

    # 检查1: 宪法完整性
    missing = check_spawn_quality(prompt)
    if missing:
        missing_str = "\n".join(f"  - {m}" for m in missing)
        issues.append(f"宪法上下文缺失:\n{missing_str}")

    # 检查2: 角色路由
    routing_hint = check_role_routing(tool_input)
    if routing_hint:
        issues.append(routing_hint)

    if not issues:
        sys.exit(0)

    issues_text = "\n\n".join(issues)
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"⚠️ SPAWN检查 ({len(issues)} issues):\n\n"
                f"{issues_text}\n\n"
                "修复: 引用.claude/agents/_charter_context.md + 指定正确角色类型\n"
                "参考: TEAM_CHARTER_V3.3.md §1.1-1.3"
            ),
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
