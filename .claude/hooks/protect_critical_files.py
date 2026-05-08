"""Harness Hook: 关键文件保护 — 防止误改 (v2 2026-05-09 V3 实施期扩展).

触发: PreToolUse[Edit|Write|MultiEdit]
功能 (v1 sustained, sustained user Q1 反向适用 + ADR-022 反 silent overwrite — 混合体例):
  - 完全阻止 (BLOCK exit 2): credentials, .git/, .env.* variants
  - .env Write 完全阻止 BLOCK exit 2 (反整文件覆盖)
  - .env Edit/MultiEdit 走字段级 whitelist (沿用 user 决议精神 #8 + Option E):
    仅允许 News URL fields (ANSPIRE/MARKETAUX/ZHIPU/TAVILY/GDELT/RSSHUB_BASE_URL).
    反 production secret (DEEPSEEK_API_KEY / EXECUTION_MODE / LIVE_TRADING_DISABLED /
    QMT_ACCOUNT_ID / DATABASE_URL / TUSHARE_TOKEN / DINGTALK_* / ADMIN_TOKEN 等).
  - 警告 (WARN ALLOW with hookSpecificOutput): docs/QUANTMIND_V2_DDL_FINAL.sql,
    docs/QUANTMIND_V2_DESIGN_V5.md

功能 (v2 扩展, sustained Constitution v0.2 §L6.2 line 284 候选追加 + skeleton §3.2 line 312):
  - 警告 (WARN ALLOW with hookSpecificOutput): prompts/risk/*.yaml — V3 production LLM
    prompt config (sustained user Q2 (β) + Q2 fresh verify 决议: prompts/risk/news_classifier_v1.yaml
    现存在 4185 bytes 真生产 V3 Sprint 7b.2 PR #241 sediment, 反 future-proof "0 file 现存在
    prerequisite" 假设修正); WARN scope (反 BLOCK) — prompts evolve, legitimate edits expected.

退出码: 0=通过 (含 ALLOW-with-WARN), 2=阻止 (sustained 现 v1 混合体例 反 silent overwrite ADR-022)

scope (Phase 1 narrowed sustained user Q2 (β) + PR #280/#281/#282/#283 四 PR LL-130 候选体例累积):
  - prompts/risk/*.yaml WARN file pattern static 可达 (file pattern matcher 真值 1 file 现存在,
    future-proof for additional yaml prompts)
  - dynamic content protection (e.g. prompt schema validation) deferred to skill
    quantmind-v3-prompt-design-laws SOP active CC invoke

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L6.2 line 284 (候选追加 cite — protect_critical_files 扩 V3 prompts/risk/*.yaml)
- skeleton §3.2 line 312 (现有 hook 扩展真值)
- ADR-DRAFT row 11 candidate (双 source align verify SOP), 真讽刺 #16 sediment 加深
- skill quantmind-v3-prompt-design-laws (PR #275, prompt design 0 hardcode 体例 + schema validation)
- LL-130 候选 (hook regex coverage scope vs full SOP scope governance — Phase 1 narrowed)
- LL-133 候选 (现有 hook v1→v2 lifecycle governance — sustained PR #283 first case + 本 second)
"""

import json
import re
import sys

# 完全禁止 (任 tool, 任 file pattern in BLOCKED_PATTERNS).
# `\.env\.` (any `.env.XXX` variant) 真**广 catch** — `.env.local` / `.env.production` /
# `.env.backup` / `.env.staging` / `.env.test` 全 BLOCKED (P1 reviewer adopt).
BLOCKED_PATTERNS = [
    r"\.env\.",
    r"credentials",
    r"\.git/",
]

# .env: Write 完全 BLOCKED, Edit/MultiEdit 走字段级 whitelist.
# `(^|[/\\])\.env$` 真**path-anchor** — `foo.env` 反 match (P3 reviewer adopt).
ENV_FIELD_GATED = [
    r"(^|[/\\])\.env$",
]

# .env Edit 字段级 whitelist (5-07 sub-PR 8b-pre-hook).
# 任 Edit/MultiEdit old_string/new_string 仅 touch 这些 field, 允许 (反 production
# secret 漂移红线 sustained). 沿用 fetcher SSOT 体例 align 官方 API.
ENV_EDITABLE_FIELDS = {
    "ANSPIRE_BASE_URL",
    "MARKETAUX_BASE_URL",
    "ZHIPU_BASE_URL",
    "TAVILY_BASE_URL",
    "GDELT_BASE_URL",
    "RSSHUB_BASE_URL",
}

# 警告但不阻止的文件 (sys.exit(0) + hookSpecificOutput.additionalContext WARN)
# v2 扩展: 加入 prompts/risk/*.yaml — V3 production LLM prompt config
# (sustained Constitution §L6.2 line 284 候选追加 + skeleton §3.2 line 312 + user Q2 (β)).
WARN_PATTERNS = [
    r"docs/QUANTMIND_V2_DDL_FINAL\.sql",
    r"docs/QUANTMIND_V2_DESIGN_V5\.md",
    r"prompts/risk/.+\.yaml",
]

# .env field 检测 regex (line-anchored, uppercase identifier + `=`).
# Comment lines (# FOO=bar) 不 match — 真`#` 反 letter, anchor `^[A-Z]` rejects.
ENV_FIELD_REGEX = re.compile(r"^\s*([A-Z][A-Z0-9_]+)\s*=", re.MULTILINE)


def _extract_env_fields(text):
    """Parse .env-style text → set of FIELD names appearing as `FIELD=...` lines."""
    if not text:
        return set()
    return set(ENV_FIELD_REGEX.findall(text))


def _check_env_edit(file_path, old_string, new_string):
    """Field-level check for .env Edit. Returns (allow: bool, error_msg: str|None).

    Rule:
      1. old_string + new_string 真**0 field detected** → BLOCKED (反多行匿名 mutation)
      2. touched fields 全 in whitelist → ALLOW (caller emits WARN context)
      3. 任 touched field non-whitelisted → BLOCKED + cite field name + cite whitelist
    """
    touched = _extract_env_fields(old_string) | _extract_env_fields(new_string)
    if not touched:
        return False, (
            f"BLOCKED: {file_path} Edit 真**0 field detected** in old_string/new_string. "
            f"Edit 必触一个 `FIELD=value` 行 (反多行匿名 mutation 真 silent overwrite)."
        )
    non_whitelisted = touched - ENV_EDITABLE_FIELDS
    if non_whitelisted:
        fields_list = ", ".join(sorted(non_whitelisted))
        whitelist = ", ".join(sorted(ENV_EDITABLE_FIELDS))
        return False, (
            f"BLOCKED: {file_path} Edit 触发 non-whitelisted fields: {fields_list}. "
            f"白名单仅含 News URL fields ({whitelist}). "
            f"反 production secret (DEEPSEEK_API_KEY / LIVE_TRADING_DISABLED / "
            f"EXECUTION_MODE / QMT_ACCOUNT_ID / DATABASE_URL 等) 漂移红线 sustained."
        )
    return True, None


def _emit_env_warn_and_exit(file_path, tool_input):
    """Emit ALLOW-with-WARN hookSpecificOutput for .env Edit pass-through, sys.exit(0)."""
    touched = set()
    if tool_input.get("old_string"):
        touched |= _extract_env_fields(tool_input["old_string"])
    if tool_input.get("new_string"):
        touched |= _extract_env_fields(tool_input["new_string"])
    for ed in tool_input.get("edits", []):
        touched |= _extract_env_fields(ed.get("old_string", ""))
        touched |= _extract_env_fields(ed.get("new_string", ""))
    fields_list = ", ".join(sorted(touched)) if touched else "(none)"
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"WARNING: 你正在 Edit {file_path} field {fields_list}. "
                f"沿用 5-07 sub-PR 8b-pre-hook field-level whitelist 体例 sustained. "
                f"反 production secret 漂移. 仅 in-PR 真**News URL drift fix** 体例可走."
            ),
        }
    }
    print(json.dumps(result))
    sys.exit(0)


def main():
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        sys.exit(0)

    normalized = file_path.replace("\\", "/")

    # 1. 完全 BLOCKED (任 tool)
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            print(
                f"BLOCKED: {file_path} 是受保护文件，不允许通过 Claude Code 修改。",
                file=sys.stderr,
            )
            sys.exit(2)

    # 2. .env field-level whitelist 体例
    for pattern in ENV_FIELD_GATED:
        if re.search(pattern, normalized, re.IGNORECASE):
            if tool_name == "Write":
                print(
                    f"BLOCKED: {file_path} 不允许 Write 整文件覆盖 (反 production secret "
                    f"漂移红线). 如需修改 News URL whitelist 字段, 走 Edit 单字段体例.",
                    file=sys.stderr,
                )
                sys.exit(2)
            if tool_name == "Edit":
                allow, err = _check_env_edit(
                    file_path,
                    tool_input.get("old_string", ""),
                    tool_input.get("new_string", ""),
                )
                if not allow:
                    print(err, file=sys.stderr)
                    sys.exit(2)
                _emit_env_warn_and_exit(file_path, tool_input)
            if tool_name == "MultiEdit":
                edits = tool_input.get("edits", [])
                if not edits:
                    print(
                        f"BLOCKED: {file_path} MultiEdit 真**0 edits provided**.",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                for i, ed in enumerate(edits):
                    allow, err = _check_env_edit(
                        file_path,
                        ed.get("old_string", ""),
                        ed.get("new_string", ""),
                    )
                    if not allow:
                        print(f"BLOCKED at edit #{i + 1}: {err}", file=sys.stderr)
                        sys.exit(2)
                _emit_env_warn_and_exit(file_path, tool_input)
            # 其他 tool (e.g. NotebookEdit) → BLOCKED on .env
            print(
                f"BLOCKED: {file_path} tool {tool_name} 不允许 (限 Edit/MultiEdit 走 "
                f"News URL whitelist 体例).",
                file=sys.stderr,
            )
            sys.exit(2)

    # 3. WARN 不阻止
    for pattern in WARN_PATTERNS:
        if re.search(pattern, normalized):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": (
                        f"WARNING: 你正在修改关键文件 {file_path}。确保这是用户明确"
                        f"要求的变更，不要自行决定范围外的改动（工作原则5）。"
                    ),
                }
            }
            print(json.dumps(result))
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
