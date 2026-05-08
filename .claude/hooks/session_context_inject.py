"""Hook: Session 启动上下文恢复 (v3 2026-05-09 V3 实施期 doc 扩展).

根因 (v1 → v2): v1 (至 2026-04-17) 只提 18 条铁律 + 已归档 ROADMAP_V3, **完全没提 Blueprint + memory
handoff**. 导致连续 session (3/4) 开场铁律 38 违规 — 未读顶层设计文档直接开工.

v3 扩展 (V3 step 4 sub-PR 5, sustained Constitution v0.2 §L0.3 step (3) 决议 + §L1.1 8 doc fresh
read SOP + §L6.2 line 277 fresh-read-sessionstart 合并到 session_context_inject.py 现有扩展决议):
  - 扩 V3 实施期 doc fresh read trigger: V3_IMPLEMENTATION_CONSTITUTION.md (Constitution v0.2) +
    V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md (skeleton v0.1) + QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md
    (V3 spec authoritative source) + docs/adr/REGISTRY.md (ADR # SSOT, LL-105 SOP-6) 4 doc 加入
    inject scope (沿用 ADR-022 反 abstraction premature — 反 silent 全新 fresh-read-sessionstart
    hook 创建)
  - 反 silent 沿用 v2 inject scope (Phase 1 narrowed scope sustained PR #280/#281/#282 LL-130
    候选体例累积; full 8 doc dynamic content extraction deferred to skill SOP)

v2 目标 (sustained):
  1. 硬性"新 session 必读"指令 (不是软性"关键路径")
  2. Blueprint + memory handoff 置顶, 新铁律 (38/39/25/36/40) 速查
  3. 动态提 memory/project_sprint_state.md frontmatter description (最强实时状态)
  4. 动态提 Blueprint 版本 + Wave 位置
  5. 保留 audit log + SYSTEM_STATUS 解析 fallback

触发: SessionStart

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L0.3 step (3) SessionStart hook fire 决议 (V3 doc fresh read trigger)
- Constitution §L1.1 8 doc fresh read SOP
- Constitution §L6.2 line 277 fresh-read-sessionstart 合并决议
- skeleton §3.2 现有 hook 扩展真值
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance — Phase 1 narrowed scope)
- 铁律 45 (4 doc fresh read SOP enforcement)
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path


def _safe_read(path: Path, limit: int = 4000) -> str | None:
    """安全读文本, 失败返 None 不 raise (hook 不能 block session)."""
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except Exception:
        return None


def get_sprint_description(memory_root: Path) -> str:
    """从 memory/project_sprint_state.md frontmatter 提 description 字段."""
    f = memory_root / "project_sprint_state.md"
    content = _safe_read(f, limit=2000)
    if not content:
        return "memory handoff 未找到 — 新环境? 读 docs/SETUP_DEV.md bootstrap"
    # frontmatter description 字段
    m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else "frontmatter 无 description — 检查 memory 文件"


def get_sprint_latest_session(memory_root: Path) -> str:
    """提 memory 顶部最新 Session N Handoff 标题."""
    f = memory_root / "project_sprint_state.md"
    content = _safe_read(f, limit=3000)
    if not content:
        return "(memory 未读到)"
    m = re.search(r"^## 🚀\s*(.+)$", content, re.MULTILINE)
    return m.group(1).strip() if m else "(未找到 🚀 当前 handoff)"


def get_blueprint_version(project_root: Path) -> str:
    """从 QUANTMIND_PLATFORM_BLUEPRINT.md H1 提版本号."""
    f = project_root / "docs" / "QUANTMIND_PLATFORM_BLUEPRINT.md"
    content = _safe_read(f, limit=500)
    if not content:
        return "(Blueprint 未找到)"
    m = re.search(r"^#\s*QuantMind Platform Blueprint\s*\(([^)]+)\)", content, re.MULTILINE)
    return m.group(1).strip() if m else "(版本解析失败)"


def get_current_state(project_root: Path) -> str:
    """从 SYSTEM_STATUS.md §0 提当前 Step + Sharpe (v1 逻辑保留, fallback)."""
    status = project_root / "SYSTEM_STATUS.md"
    content = _safe_read(status)
    if not content:
        return "SYSTEM_STATUS.md 未找到"
    step_match = re.search(r"Step\s+[0-9a-zA-Z\-→\s]+(?=重构|完成|窗口|进行)", content)
    step = step_match.group(0).strip() if step_match else "Step?"
    sharpe_match = re.search(r"Sharpe[=:\s]*(\d+\.\d+)", content)
    sharpe = f"Sharpe={sharpe_match.group(1)}" if sharpe_match else ""
    return f"{step}, {sharpe}".strip().rstrip(",")


def get_v3_doc_status(project_root: Path) -> str:
    """v3 扩展 (V3 step 4 sub-PR 5): 检 V3 实施期 4 doc 存在性 + cite SSOT 锚点.

    沿用 Constitution §L0.3 step (3) + §L1.1 8 doc fresh read SOP + §L6.2 line 277 决议.
    Phase 1 narrowed scope (sustained PR #280/#281/#282 LL-130 候选体例累积):
    - 仅 cite path + 存在 status (静态可达)
    - dynamic content extraction (e.g. Constitution v0.2 frontmatter) deferred to skill SOP
    """
    v3_docs = [
        ("Constitution v0.2", "docs/V3_IMPLEMENTATION_CONSTITUTION.md"),
        ("Skeleton v0.1", "docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md"),
        ("V3 Design (spec authoritative source)", "docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md"),
        ("ADR REGISTRY (LL-105 SOP-6 SSOT)", "docs/adr/REGISTRY.md"),
    ]
    lines = []
    for label, rel_path in v3_docs:
        f = project_root / rel_path
        status = "✅ exists" if f.exists() else "⚠️ NOT FOUND"
        lines.append(f"  - {label}: `{rel_path}` ({status})")
    return "\n".join(lines)


def build_context(project_root: Path) -> str:
    """组装注入 context."""
    memory_root = Path.home() / ".claude" / "projects" / "D--quantmind-v2" / "memory"

    sprint_desc = get_sprint_description(memory_root)
    sprint_session = get_sprint_latest_session(memory_root)
    blueprint_ver = get_blueprint_version(project_root)
    legacy_state = get_current_state(project_root)
    v3_doc_status = get_v3_doc_status(project_root)

    return f"""SESSION START CONTEXT (hook v3, 2026-05-09 V3 实施期 doc 扩展):

⭐ 当前 Sprint 状态 (memory/project_sprint_state.md frontmatter):
{sprint_desc}

⭐ 最新 Handoff (memory 顶部):
{sprint_session}

⭐ Blueprint: docs/QUANTMIND_PLATFORM_BLUEPRINT.md  |  版本: {blueprint_ver}

🔴 新 Session 冷启动必读 (铁律 38, 违反即事故):
  1. docs/QUANTMIND_PLATFORM_BLUEPRINT.md  §Part 0 + §Quickstart (L14-145, ≤130 行)
  2. memory/project_sprint_state.md  顶部 Session 当前 handoff (全文)
  3. 本 MVP 对应 docs/mvp/MVP_X_Y_*.md 设计稿 (若存在)
  4. CLAUDE.md §铁律 (40 条) + §当前进度

🔑 关键路径 (按用途):
  - 代码变更前: CLAUDE.md (40 条铁律) + 目标代码当前内容 (铁律 25)
  - 新 MVP 启动: Blueprint Part 4 对应 MVP 定义 + Part 2 Framework
  - 建表: docs/QUANTMIND_V2_DDL_FINAL.sql (唯一来源)
  - 已决议不重开讨论: memory/project_platform_decisions.md (4+4 项)
  - 新机器/新 clone: docs/SETUP_DEV.md (.pth + hooks + Servy bootstrap)

⚠️ 铁律速查 TOP 12 (新架构时代核心):
  25. 代码变更前必读当前代码验证 (改什么读什么, 不凭印象)
  36. 代码变更前必核 precondition (依赖/锚点/数据)
  37. Session 关闭前必写 handoff (memory/project_sprint_state.md)
  38. Blueprint (QPB) 是唯一长期架构记忆, 跨 session 实施漂移禁止
  39. 架构模式 vs 实施模式切换必显式声明
  40. 测试债务不得增长 (新增 fail 禁合入, baseline 24)
  17. DataPipeline 入库 (禁裸 INSERT)
  22. 文档跟随代码 (commit 同步或 NO_DOC_IMPACT 声明)
  15. 回测可复现 (regression max_diff=0 硬门)
  10b. 生产入口真启动验证 (smoke test subprocess 从生产路径真启动)
  33. 禁 silent failure (except: pass 必带 # silent_ok 注释)
  34. 配置 single source of truth (config_guard 启动硬 raise)

🗂️ Legacy 状态 (SYSTEM_STATUS.md §0, 参考): {legacy_state}

🆕 V3 实施期 doc fresh read SOP (沿用 Constitution v0.2 §L0.3 step (3) + §L1.1 8 doc + 铁律 45):
{v3_doc_status}
  → V3 sub-PR 起手必 fresh re-read 4 doc + 任 cite section anchor 必走 §0.3 scope declaration
    verify (沿用 PR #281 §L7 + PR #282 §L9 reverse cite finding 体例累积)
"""


def main():
    project_root = Path(__file__).resolve().parent.parent.parent
    context = build_context(project_root)

    # Audit log (best-effort, 失败不 block)
    audit_log = project_root / ".claude" / "hooks" / "audit.log"
    try:
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | SESSION_START (hook v2)\n")
    except Exception:
        pass

    result = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
