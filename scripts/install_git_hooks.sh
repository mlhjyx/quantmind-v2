#!/usr/bin/env bash
# 安装 QuantMind V2 git hooks 到 .git/hooks/
#
# 用法:
#   bash scripts/install_git_hooks.sh        # 安装 (覆盖现有 hooks)
#   bash scripts/install_git_hooks.sh --check # 仅检查, 不安装
#
# Windows 提示: .git/hooks/ 下的脚本需要 Git Bash / MSYS 环境 (Git for Windows 自带)
#
# 不入 .pre-commit-config.yaml 的理由:
#   - 项目零 pre-commit framework 依赖
#   - 直接写 .git/hooks/pre-commit 零依赖 + 立即生效
#   - 本 installer 把 scripts/git_hooks/* 复制到 .git/hooks/, 做到"入库可跟"

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_TARGET="$REPO_ROOT/.git/hooks"
HOOKS_SOURCE="$REPO_ROOT/scripts/git_hooks"

if [ ! -d "$HOOKS_SOURCE" ]; then
    echo "错误: $HOOKS_SOURCE 不存在"
    exit 1
fi

CHECK_ONLY=0
if [ "$1" = "--check" ]; then
    CHECK_ONLY=1
fi

echo "QuantMind V2 git hooks installer"
echo "  source: $HOOKS_SOURCE"
echo "  target: $HOOKS_TARGET"
echo ""

installed=0
for hook in "$HOOKS_SOURCE"/*; do
    [ -f "$hook" ] || continue
    name=$(basename "$hook")
    # 跳过 README / 说明文件
    case "$name" in
        README*|*.md|*.txt) continue ;;
    esac

    target="$HOOKS_TARGET/$name"

    if [ $CHECK_ONLY -eq 1 ]; then
        if [ -f "$target" ] && diff -q "$hook" "$target" > /dev/null 2>&1; then
            echo "  ✅ $name (已安装, 最新)"
        elif [ -f "$target" ]; then
            echo "  ⚠️  $name (已安装但与源文件不一致, 请重装)"
        else
            echo "  ❌ $name (未安装)"
        fi
    else
        cp "$hook" "$target"
        chmod +x "$target"
        echo "  ✅ 已安装: $name"
        installed=$((installed + 1))
    fi
done

if [ $CHECK_ONLY -eq 0 ]; then
    echo ""
    echo "✅ 完成: $installed 个 hook 已安装到 $HOOKS_TARGET"
    echo ""
    echo "下次 'git commit' 会自动运行铁律 17 检查."
    echo "紧急绕过: git commit --no-verify"
fi
