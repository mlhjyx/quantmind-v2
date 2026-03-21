#!/bin/bash
# Paper Trading crontab安装脚本
#
# 添加每日16:30自动运行Paper Trading管道
# 脚本内部会检查是否交易日，非交易日自动跳过
#
# 用法:
#   bash scripts/install_crontab.sh        # 安装
#   bash scripts/install_crontab.sh remove  # 卸载

PROJECT_DIR="/Users/xin/Documents/quantmind-v2"
PYTHON="/Users/xin/miniconda3/bin/python3"
LOG_DIR="${PROJECT_DIR}/logs"
CRON_TAG="# quantmind-paper-trading"

mkdir -p "${LOG_DIR}"

if [ "$1" = "remove" ]; then
    crontab -l 2>/dev/null | grep -v "${CRON_TAG}" | crontab -
    echo "✅ Paper Trading crontab已移除"
    exit 0
fi

# 检查是否已安装
if crontab -l 2>/dev/null | grep -q "${CRON_TAG}"; then
    echo "⚠️  crontab已存在，跳过安装"
    crontab -l | grep "${CRON_TAG}"
    exit 0
fi

# 添加crontab
# 每个工作日16:30运行（脚本内部判断是否交易日）
CRON_LINE="30 16 * * 1-5 cd ${PROJECT_DIR} && ${PYTHON} scripts/run_paper_trading.py >> ${LOG_DIR}/paper_trading_cron.log 2>&1 ${CRON_TAG}"

(crontab -l 2>/dev/null; echo "${CRON_LINE}") | crontab -

echo "✅ Paper Trading crontab已安装"
echo "   时间: 每个工作日 16:30"
echo "   日志: ${LOG_DIR}/paper_trading_cron.log"
echo ""
echo "当前crontab:"
crontab -l | grep "${CRON_TAG}"
echo ""
echo "手动测试: ${PYTHON} scripts/run_paper_trading.py --dry-run"
