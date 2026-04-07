# scripts/archive/

> 归档脚本目录。2026-04-07整理，经131+文件全量审计。

## 归档原则

- 一次性研究/实验脚本（IC计算、回测对比、ML实验）
- 功能已被其他模块替代的脚本
- 已完成的数据修复/迁移脚本

## 仍在scripts/根目录的生产脚本（18个）

| 脚本 | 用途 | 调度方式 |
|------|------|---------|
| run_paper_trading.py | PT主脚本(信号+执行) | Task Scheduler |
| health_check.py | 盘前健康检查 | Task Scheduler |
| pg_backup.py | 数据库备份 | Task Scheduler |
| pull_moneyflow.py | 资金流拉取 | Task Scheduler |
| data_quality_check.py | 数据巡检 | Task Scheduler |
| monitor_factor_ic.py | 因子IC监控 | Task Scheduler |
| pt_watchdog.py | PT心跳监控 | Task Scheduler |
| qmt_data_service.py | QMT数据同步 | Servy常驻 |
| run_backtest.py | 回测脚本(PT依赖) | 手动 |
| precompute_cache.py | Parquet缓存导出 | PT Step5调用 |
| approve_l4.py | L4熔断恢复CLI | 手动(紧急) |
| cancel_stale_orders.py | QMT紧急撤单 | 手动(紧急) |
| log_rotate.py | 日志轮转 | 待注册Task |
| setup_paper_trading.py | PT策略初始化 | 手动 |
| check_graduation.py | PT毕业快检 | 手动 |
| paper_trading_stats.py | PT统计报告 | 手动 |
| paper_trading_status.py | PT状态查询 | 手动 |
| setup_task_scheduler.ps1 | Task Scheduler注册 | 手动 |

## KEEP_REF脚本（19个，方法论有参考价值）

数据拉取类（将来增量更新需要）:
- pull_full_data.py / pull_balancesheet.py / pull_cashflow.py / pull_financial_data.py
- pull_stk_holdernumber.py / pull_sw_index.py / fetch_earnings.py / fetch_northbound.py
- fetch_minute_bars.py（分钟数据拉取~36%未完成）/ refresh_symbols.py

工具/验证类:
- calc_factors.py / recalc_factors_fast.py / build_industry_l1_mapping.py
- compare_simbroker_qmt.py / pt_signal_replay.py / doc_drift_check.py
- slippage_decompose.py / factor_health_report_v2.py / risk_threshold_scan.py

## 注意事项

- `ruff check`和pre-commit hook已配置排除本目录
- 恢复脚本: `cp scripts/archive/xxx.py scripts/xxx.py`
- 恢复前检查依赖: `grep -rn "xxx" --include="*.py" | grep -v archive/`
