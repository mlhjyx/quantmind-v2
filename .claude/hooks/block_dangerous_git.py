"""Harness Hook: block dangerous git commands — layer 2 defense (PreToolUse Bash).

触发: PreToolUse[Bash]
功能: 真**Bash tool 调用前** intercept dangerous git commands — 反 silent destructive
ops 沿用真红线 sustained 5/5.
退出码: 0=通过, 2=阻止

沿用 mattpocock-git-guardrails skill bundled `block-dangerous-git.sh` 真**patterns**真值
+ sub-PR 8a-followup-pre 5-07 hook governance 修订真生效:

体例修订 (5-07 sub-PR 8a-followup-pre, ADR-DRAFT row 7 sediment):
- ❌ block sustained: reset --hard / clean -fd / clean -f / branch -D / checkout . /
                      restore .
- ❌ block sustained (refined): force push (--force / -f / --force-with-lease) /
                                push to main / push to master direct
- ✅ allow NEW: git push <feature-branch> (pattern: 非 main / 非 master)
- ✅ allow NEW: gh pr create / gh pr * (gh CLI 真生产 PR creation 路径 sustained)
- ❌ block sustained: 0 mass-deletion command-level detect (hard to detect from
                     command string alone, defer to pre-push hook 真**diff size 检查**
                     sub-PR 8a-followup-pre defer to sub-PR 8a-followup-A+B batch 候选)

真讽刺案例 #11 候选 sediment (5-07 sub-PR 8a-followup-pre 触发):
- 5-07 sub-PR 8a 真生产 first verify 触发 hook governance 修订真**首次起手**
- 沿用 5-07 候选 #7+#8+#9 真讽刺案例体例 (governance 真**未起手** 沉淀直到 first
  production verify 触发) — 真**4 days production 0 catch hook governance 真过严** 沉淀

关联铁律: 33 (fail-loud, parse error 沿用 protect_critical_files.py 体例 fail-soft
              sys.exit(0) 反 break tool 调用) /
          35 (Secrets env var 唯一, 反 hardcode credentials 沿用) /
          42 (PR 分级审查制 — backend/** 必走 PR + reviewer + AI 自 merge sustained
              sub-PR 8a-followup-pre 真**hook governance** unblock CC 自 push 体例)
"""

import json
import re
import sys

# 沿用 mattpocock-git-guardrails block-dangerous-git.sh patterns sediment cite source
# 锁定真值 (sub-PR 8a-followup-pre 5-07 修订: 反 "git push" 全局 BLOCK 体例).
#
# 真生效 patterns (sustained 5-07 修订后):
DANGEROUS_PATTERNS = [
    r"git reset --hard",
    r"git clean -fd",
    r"git clean -f",
    r"git branch -D",
    r"git checkout \.",
    r"git restore \.",
    r"reset --hard",  # legacy redundant pattern sustained 沿用
]

# 真**git push specific** dangerous variants (sub-PR 8a-followup-pre 5-07 修订 NEW):
# 反 "git push" 全局 BLOCK 体例, 改 fine-grained 检测 force / main / master.
PUSH_DANGEROUS_PATTERNS = [
    # force push (任 variant): --force / -f / --force-with-lease
    r"git push\b.*--force\b",
    r"git push\b.*--force-with-lease\b",
    r"git push\b.*\s-f\b",  # -f flag (反 -force-with-lease 真 -fwl pattern 真 0)
    # push to main / master direct (任 variant)
    r"git push\b.*\borigin\s+main\b",
    r"git push\b.*\borigin\s+master\b",
    r"git push\b.*\smain\b\s*$",  # push 真**末尾参数** main
    r"git push\b.*\smaster\b\s*$",  # push 真**末尾参数** master
    # standalone "git push" (no args, current branch HEAD push) 真**ambiguous case**
    # 真允许 (沿用 feature-branch 体例 — caller 真**已 checkout feature-branch** 体例
    # sustained sub-PR 8a-followup workflow). user 真**显式想 push main** 必走 explicit
    # `git push origin main` 真 BLOCK (反 standalone 真**当前 branch** 真隐式).
]


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # 沿用 protect_critical_files.py:33 体例 fail-soft (反 break Bash tool 调用)
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    # 沿用 dangerous patterns 全局 check (reset --hard / clean / branch -D / checkout .)
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            print(
                f"BLOCKED: '{command}' matches dangerous pattern '{pattern}'. "
                f"The user has prevented you from doing this.",
                file=sys.stderr,
            )
            sys.exit(2)

    # 沿用 git push specific check (5-07 修订 — fine-grained, 反 全局 BLOCK)
    for pattern in PUSH_DANGEROUS_PATTERNS:
        if re.search(pattern, command):
            print(
                f"BLOCKED: '{command}' matches push-dangerous pattern '{pattern}'. "
                f"沿用 sub-PR 8a-followup-pre 5-07 hook governance: "
                f"force push / push to main / push to master 沿用红线 sustained. "
                f"feature-branch push 真生效 (反 main/master direct push).",
                file=sys.stderr,
            )
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
