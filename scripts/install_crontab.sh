#!/bin/bash
# Paper Trading 调度安装脚本 (Windows Task Scheduler版)
#
# Phase 1 (signal): 工作日 16:30 — 生成信号
# Phase 2 (execute): 工作日 09:00 — 读信号用T+1 open执行
#
# 用法 (需要在PowerShell中运行):
#   powershell -File scripts/install_scheduler.ps1        # 安装
#   powershell -File scripts/install_scheduler.ps1 remove # 卸载
#
# 或直接用schtasks:
#   schtasks /Create /TN "QuantMind_DailySignal" /TR "D:\quantmind-v2\.venv\Scripts\python.exe D:\quantmind-v2\scripts\run_paper_trading.py signal" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 16:30 /F
#   schtasks /Create /TN "QuantMind_DailyExecute" /TR "D:\quantmind-v2\.venv\Scripts\python.exe D:\quantmind-v2\scripts\run_paper_trading.py execute" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 09:00 /F
#
# 查看:
#   schtasks /Query /TN "QuantMind_DailySignal" /FO LIST
#   schtasks /Query /TN "QuantMind_DailyExecute" /FO LIST
#
# 删除:
#   schtasks /Delete /TN "QuantMind_DailySignal" /F
#   schtasks /Delete /TN "QuantMind_DailyExecute" /F
#
# 注意: 此脚本保留为文档参考，实际调度已迁移到Windows Task Scheduler。
# Mac crontab已不再使用。

echo "此脚本已迁移到Windows Task Scheduler。"
echo "请使用上方注释中的schtasks命令管理调度任务。"
