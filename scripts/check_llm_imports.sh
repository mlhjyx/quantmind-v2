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

# S4 PR #226 sediment (ADR-032): 反 caller code 真 _internal/ 直接 import bypass factory.
# scope 排除 backend/qm_platform/llm/ 自身 (bootstrap.py + _internal/ 内部互引合法).
S4_INTERNAL_PATTERN='^[[:space:]]*from[[:space:]]+backend\.qm_platform\.llm\._internal'

ALLOWLIST_MARKER='# llm-import-allow:'
# S4 allowlist: test 真**file-level marker** (顶部注释), 沿用 PR #219 行内 marker 体例
S4_INTERNAL_ALLOWLIST_MARKER='# llm-internal-allow:'

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

# ─────────────────────────────────────────────────────────────
# S4 PR #226 第 2 轮 scan: caller code (backend/app/, backend/engines/, scripts/)
# 反 _internal/ 直接 import bypass factory.
#
# scope 跟第 1 轮 (anthropic/openai) 真**不同**:
# - 排除 backend/qm_platform/llm/ 自身 (bootstrap.py + _internal/ 内部互引合法)
# - 排除 backend/tests/* (mock 体例真依赖, 沿用 PR #219)
# - 排除 config/hooks/, scripts/check_llm_imports.sh
# ─────────────────────────────────────────────────────────────

case "$MODE" in
    --staged|staged)
        # 沿用 reviewer Chunk B P2 修订: scripts/check_llm_imports.sh 真**.sh 文件**,
        # `.py$` filter 真已自动排除, sustained `grep -v '^scripts/check_llm_imports\.sh$'`
        # 真**defensive consistency** 跟第 1 轮 anthropic/openai scan 体例对齐 (反未来
        # 加 .py wrapper script 真 silent miss).
        S4_TARGETS=$(git diff --cached --name-only --diff-filter=ACM \
                    | grep -E '^(backend|scripts)/.*\.py$' \
                    | grep -v '/tests/' \
                    | grep -v '^backend/qm_platform/llm/' \
                    | grep -v '^scripts/check_llm_imports\.sh$' \
                    || true)
        ;;
    --full|full)
        # 沿用 grep filter 体例 (find -not -path 真**前导 */ 漏 relative path** 真已实测).
        S4_TARGETS=$(find backend scripts -name "*.py" \
                    -not -path "*/tests/*" \
                    2>/dev/null \
                    | grep -v '^backend/qm_platform/llm/' \
                    || true)
        ;;
esac

S4_HITS=""
S4_ALLOWLIST_LOG=""

if [ -n "$S4_TARGETS" ]; then
    for f in $S4_TARGETS; do
        if [ -f "$f" ]; then
            MATCH=$(grep -nE "$S4_INTERNAL_PATTERN" "$f" 2>/dev/null || true)
            if [ -n "$MATCH" ]; then
                FILTERED=""
                while IFS= read -r line; do
                    if [ -z "$line" ]; then
                        continue
                    fi
                    LINE_NUM=$(echo "$line" | cut -d: -f1)
                    LINE_CONTENT=$(echo "$line" | cut -d: -f2-)
                    case "$LINE_CONTENT" in
                        *"$S4_INTERNAL_ALLOWLIST_MARKER"*)
                            MARKER_TEXT=$(echo "$LINE_CONTENT" | sed -n 's/.*\(# llm-internal-allow:[^[:space:]]*\).*/\1/p')
                            S4_ALLOWLIST_LOG="${S4_ALLOWLIST_LOG}S4_ALLOWLIST_HIT: ${f}:${LINE_NUM} ${MARKER_TEXT}
"
                            ;;
                        *)
                            FILTERED="${FILTERED}${line}
"
                            ;;
                    esac
                done <<EOF
$MATCH
EOF
                if [ -n "$FILTERED" ]; then
                    S4_HITS="${S4_HITS}${f}:
${FILTERED}
"
                fi
            fi
        fi
    done
fi

if [ -n "$S4_ALLOWLIST_LOG" ]; then
    printf "%s" "$S4_ALLOWLIST_LOG" >&2
fi

if [ -n "$S4_HITS" ]; then
    echo ""
    echo "[check_llm_imports] BLOCK (S4): caller code 走 _internal/ 直接 import bypass factory"
    echo "[check_llm_imports] scope: backend/app/ + backend/engines/ + scripts/ (排除 llm/ + tests/, mode: $MODE)"
    echo ""
    printf "%s" "$S4_HITS"
    echo "[check_llm_imports] 原因: ADR-032 — caller 必走 get_llm_router() factory (反 naked LiteLLMRouter)"
    echo "[check_llm_imports] 修复: 改 \`from backend.qm_platform.llm import get_llm_router\` (factory)"
    echo "[check_llm_imports] 详情: docs/LLM_IMPORT_POLICY.md §10.9"
    echo "[check_llm_imports] 临时豁免 (非 routine): 行内加 \`# llm-internal-allow:<reason-or-issue-ref>\`"
    exit 1
fi

if [ -n "$ALLOWLIST_LOG" ] || [ -n "$S4_ALLOWLIST_LOG" ]; then
    echo "[check_llm_imports] 0 unauthorized import 命中, mode=$MODE, 放行 (含 allowlist legacy 见 stderr)."
else
    echo "[check_llm_imports] 0 forbidden import 命中, mode=$MODE, 放行."
fi
exit 0
