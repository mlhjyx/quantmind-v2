#!/bin/sh
# scripts/check_llm_imports.sh
#
# S6 (V3 Sprint 1): backend/ + scripts/ 禁直接 import anthropic / openai.
# only path = LiteLLMRouter (V3 §5.5 cite, S2 sub-task 待 sediment).
# 沿用 ADR-022 反 silent overwrite + N×N 同步漂移防御 + LL-098 X10.
#
# scope: backend/ + scripts/ Python files.
# 排除:
#   - **/tests/* (mock cite 合法, e.g. unittest.mock.patch("openai..."))
#   - config/hooks/ (hook 自身)
#   - scripts/check_llm_imports.sh (本 script 自身)
#
# mode:
#   --staged: pre-commit, scan staged Python files only
#   --full:   pre-push, scan full backend/ + scripts/
#
# allowlist 机制 (legacy 临时豁免, 不是 routine bypass):
#   行内含 `# llm-import-allow:<reason>` 注释的违反行 skip BLOCK,
#   但仍 log "ALLOWLIST_HIT: <file>:<line> <marker>" 到 stderr (透明 + 可审计).
#   每个 allowlist 必须有对应 issue/PR cite + 计划清除时间点.
#   月度 audit 检查过期未清除的 (沿用 docs/LLM_IMPORT_POLICY.md §9).
#
# 紧急绕过 (违反 SOP, 需 commit message 声明原因):
#   git commit --no-verify   /   git push --no-verify
set -e

cd "$(git rev-parse --show-toplevel)"

# Pattern matches both top-level and inline lazy imports
# 沿用 LL-106 sediment 候选: `^[[:space:]]*` 前缀 cover 任意缩进
PATTERN='^[[:space:]]*(import (anthropic|openai)([[:space:]]|$)|from (anthropic|openai)([[:space:]\.]|$))'

ALLOWLIST_MARKER='# llm-import-allow:'

MODE="${1:---staged}"

case "$MODE" in
    --staged|staged)
        TARGETS=$(git diff --cached --name-only --diff-filter=ACM \
                    | grep -E '^(backend|scripts)/.*\.py$' \
                    | grep -v '/tests/' \
                    | grep -v '^scripts/check_llm_imports\.sh$' \
                    || true)
        ;;
    --full|full)
        TARGETS=$(find backend scripts -name "*.py" -not -path "*/tests/*" 2>/dev/null || true)
        ;;
    *)
        echo "[check_llm_imports] usage: $0 [--staged|--full]" >&2
        exit 2
        ;;
esac

if [ -z "$TARGETS" ]; then
    echo "[check_llm_imports] 0 target files (scope: backend/ + scripts/, mode: $MODE), skip."
    exit 0
fi

HITS=""
ALLOWLIST_LOG=""

for f in $TARGETS; do
    if [ -f "$f" ]; then
        # 找所有匹配行 (line:content 格式)
        MATCH=$(grep -nE "$PATTERN" "$f" 2>/dev/null || true)
        if [ -n "$MATCH" ]; then
            # 逐行检查是否有 allowlist marker
            FILTERED=""
            while IFS= read -r line; do
                if [ -z "$line" ]; then
                    continue
                fi
                # 匹配行格式: "<line_num>:<content>"
                LINE_NUM=$(echo "$line" | cut -d: -f1)
                LINE_CONTENT=$(echo "$line" | cut -d: -f2-)
                # 检查行内是否含 allowlist marker
                case "$LINE_CONTENT" in
                    *"$ALLOWLIST_MARKER"*)
                        # 提取 marker 文字 (从 "# llm-import-allow:" 开始到行尾或下个空格)
                        MARKER_TEXT=$(echo "$LINE_CONTENT" | sed -n 's/.*\(# llm-import-allow:[^[:space:]]*\).*/\1/p')
                        ALLOWLIST_LOG="${ALLOWLIST_LOG}ALLOWLIST_HIT: ${f}:${LINE_NUM} ${MARKER_TEXT}
"
                        ;;
                    *)
                        # 没 marker, 是真违反
                        FILTERED="${FILTERED}${line}
"
                        ;;
                esac
            done <<EOF
$MATCH
EOF
            if [ -n "$FILTERED" ]; then
                HITS="${HITS}${f}:
${FILTERED}
"
            fi
        fi
    fi
done

# 输出 allowlist log 到 stderr (透明 + 可审计)
if [ -n "$ALLOWLIST_LOG" ]; then
    printf "%s" "$ALLOWLIST_LOG" >&2
fi

if [ -n "$HITS" ]; then
    echo ""
    echo "[check_llm_imports] BLOCK: 发现禁止的 LLM SDK 直接 import"
    echo "[check_llm_imports] scope: backend/ + scripts/ (排除 tests/, mode: $MODE)"
    echo ""
    printf "%s" "$HITS"
    echo "[check_llm_imports] 原因: V3 §5.5 + ADR-020 — LiteLLMRouter 是 only path"
    echo "[check_llm_imports] 修复: 改用 LiteLLMRouter (S2 sub-task scope, 待 sediment)"
    echo "[check_llm_imports] 背景: ADR-022 反 silent overwrite + N×N 同步漂移防御"
    echo "[check_llm_imports] 详情: docs/LLM_IMPORT_POLICY.md"
    echo "[check_llm_imports] 临时豁免 (legacy only): 行内加 \`# llm-import-allow:<reason-or-issue-ref>\` (详 §9)"
    echo "[check_llm_imports] 紧急绕过 (违反 SOP, 需 commit message 声明原因): git commit --no-verify"
    exit 1
fi

if [ -n "$ALLOWLIST_LOG" ]; then
    echo "[check_llm_imports] 0 unauthorized import 命中, mode=$MODE, 放行 (含 allowlist legacy 见 stderr)."
else
    echo "[check_llm_imports] 0 forbidden import 命中, mode=$MODE, 放行."
fi
exit 0
