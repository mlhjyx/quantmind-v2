#!/bin/bash
# 团队成员实时监控 - tmux多pane
# 用法: 在MSYS2终端中运行 bash scripts/team_monitor.sh

TASK_DIR="$LOCALAPPDATA/Temp/claude"

# 找到最新的session目录
SESSION_DIR=$(find "$TASK_DIR" -maxdepth 2 -name "tasks" -type d 2>/dev/null | head -1)

if [ -z "$SESSION_DIR" ]; then
    echo "未找到活跃的Claude session任务目录"
    echo "请确认有agent在运行"
    exit 1
fi

echo "监控目录: $SESSION_DIR"
echo ""

# 列出所有任务文件（按时间倒序）
echo "=== 活跃任务 ==="
ls -lt "$SESSION_DIR"/*.output 2>/dev/null | head -20

echo ""
echo "按Ctrl+C退出"
echo ""

# 监控所有output文件的实时变化
# 使用tail -f跟踪最新的几个文件
LATEST_FILES=$(ls -t "$SESSION_DIR"/*.output 2>/dev/null | head -5)

if [ -z "$LATEST_FILES" ]; then
    echo "无活跃任务输出文件"
    exit 0
fi

echo "正在监控最新5个任务输出..."
echo "=========================================="
tail -f $LATEST_FILES
