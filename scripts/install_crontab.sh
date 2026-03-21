#!/bin/bash
# Paper Trading 两阶段crontab安装脚本
#
# Phase 1 (signal): 工作日 16:30 — 生成信号
# Phase 2 (execute): 工作日 09:00 — 读信号用T+1 open执行
#
# 用法:
#   bash scripts/install_crontab.sh        # 安装
#   bash scripts/install_crontab.sh remove  # 卸载

PROJECT_DIR="/Users/xin/Documents/quantmind-v2"
PYTHON="/Users/xin/miniconda3/bin/python3"
LOG_DIR="${PROJECT_DIR}/logs"
CRON_TAG_SIGNAL="# quantmind-signal"
CRON_TAG_EXECUTE="# quantmind-execute"

mkdir -p "${LOG_DIR}"

if [ "$1" = "remove" ]; then
    crontab -l 2>/dev/null | grep -v "quantmind-" | crontab -
    echo "✅ Paper Trading crontab已移除"
    exit 0
fi

# 检查是否已安装
if crontab -l 2>/dev/null | grep -q "quantmind-signal"; then
    echo "⚠️  crontab已存在:"
    crontab -l | grep "quantmind-"
    exit 0
fi

# 两行crontab
SIGNAL_LINE="30 16 * * 1-5 cd ${PROJECT_DIR} && ${PYTHON} scripts/run_paper_trading.py signal >> ${LOG_DIR}/paper_signal.log 2>&1 ${CRON_TAG_SIGNAL}"
EXECUTE_LINE="0 9 * * 1-5 cd ${PROJECT_DIR} && ${PYTHON} scripts/run_paper_trading.py execute >> ${LOG_DIR}/paper_execute.log 2>&1 ${CRON_TAG_EXECUTE}"

(crontab -l 2>/dev/null; echo "${SIGNAL_LINE}"; echo "${EXECUTE_LINE}") | crontab -

echo "✅ Paper Trading 两阶段crontab已安装"
echo "   信号阶段: 工作日 16:30 (T日盘后)"
echo "   执行阶段: 工作日 09:00 (T+1日盘前)"
echo ""
echo "当前crontab:"
crontab -l | grep "quantmind-"
echo ""
echo "手动测试:"
echo "  ${PYTHON} scripts/run_paper_trading.py signal --date YYYY-MM-DD --dry-run"
echo "  ${PYTHON} scripts/run_paper_trading.py execute --date YYYY-MM-DD --dry-run"
