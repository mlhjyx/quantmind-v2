# PT暂停记录 — 2026-04-09

> 重构前暂停Paper Trading，确保QMT不会自动交易。

## 1. Task Scheduler禁用记录

| 任务名 | 禁用前状态 | 上次运行 | 下次运行 | 禁用结果 |
|--------|-----------|---------|---------|---------|
| QM-DailyBackup | Ready | 2026-04-08 02:00 | 2026-04-09 02:00 | ⚠️ 需管理员权限手动禁用 |
| QM-HealthCheck | Ready | 2026-04-08 16:25 | 2026-04-09 16:25 | ⚠️ 需管理员权限手动禁用 |
| QM-LogRotate | Ready | 2026-04-08 06:00 | 2026-04-09 06:00 | ✅ Disabled |
| QM-SmokeTest | Disabled | 2026-04-06 20:05 | - | ✅ 已是Disabled |
| QuantMind_CancelStaleOrders | Ready | 2026-04-02 09:05 | - | ✅ Disabled |
| QuantMind_DailyBackup | Ready | 2026-04-08 02:00 | 2026-04-09 02:00 | ✅ Disabled |
| QuantMind_DailyExecute | Ready | 2026-04-08 09:31 | 2026-04-09 09:31 | ✅ Disabled |
| QuantMind_DailyExecuteAfterData | Disabled | 2026-04-01 17:05 | - | ✅ 已是Disabled |
| QuantMind_DailyMoneyflow | Ready | 2026-04-08 17:00 | 2026-04-09 17:00 | ✅ Disabled |
| QuantMind_DailyReconciliation | Ready | 2026-04-08 15:10 | 2026-04-09 15:10 | ✅ Disabled |
| QuantMind_DailySignal | Ready | 2026-04-08 17:15 | 2026-04-09 17:15 | ✅ Disabled |
| QuantMind_DataQualityCheck | Ready | 2026-04-08 16:40 | 2026-04-09 16:40 | ✅ Disabled |
| QuantMind_FactorHealthDaily | Ready | 2026-04-08 17:30 | 2026-04-09 17:30 | ✅ Disabled |
| QuantMind_IntradayMonitor | Ready | - | - | ✅ Disabled |
| QuantMind_MiniQMT_AutoStart | Ready | 2026-04-06 17:43 | - | ✅ Disabled |
| QuantMind_PTWatchdog | Ready | 2026-04-08 20:00 | 2026-04-09 20:00 | ✅ Disabled |

> ⚠️ QM-DailyBackup和QM-HealthCheck需要用户以管理员身份运行PowerShell执行:
> `Disable-ScheduledTask -TaskName 'QM-DailyBackup'`
> `Disable-ScheduledTask -TaskName 'QM-HealthCheck'`
> 这两个任务不会触发交易（只是备份和健康检查），但为完整性应一并禁用。

## 2. CeleryBeat状态

CeleryBeat服务(QuantMind-CeleryBeat): **Stopped**（已确认）
无需额外操作。PMS 14:30检查、GP周日触发等Beat调度任务不会执行。

## 3. QMT交易确认

- Redis `qmt:connection_status`: **connected**
- QMT仍处于连接状态，但：
  - QuantMind_DailyExecute已禁用 → 不会触发09:31自动执行
  - QuantMind_MiniQMT_AutoStart已禁用 → QMT不会自动重启
  - 无其他进程会触发交易（run_paper_trading.py只通过Task Scheduler调用）
- **结论**: QMT连接但无触发源，不会自动交易 ✅

## 4. PT状态快照

**基本信息**:
- PT起始日期: 2026-03-23
- 最新数据日期: 2026-04-08
- 已运行: 12个交易日
- 最新NAV: ¥999,794.12
- 日收益: +3.21%
- Redis NAV: total_value=¥999,801.60, cash=¥5,400.12, 17只持仓

**当前持仓(17只, 按市值降序)**:

| code | 数量 | 成本价 | 市值 | 浮盈亏 | 模式 |
|------|------|--------|------|--------|------|
| 920819 | 24,900 | 3.60 | 88,395 | -1,313 | live |
| 688570 | 5,100 | 17.73 | 87,618 | -2,805 | live |
| 688211 | 2,800 | 31.34 | 86,520 | -1,232 | live |
| 920701 | 4,200 | 15.28 | 63,336 | -840 | live |
| 920608 | 3,100 | 16.65 | 50,499 | -1,106 | live |
| 920519 | 4,400 | 11.51 | 50,116 | -528 | live |
| 920807 | 4,400 | 11.47 | 50,116 | -363 | live |
| 688057 | 4,200 | 12.17 | 50,022 | -1,092 | live |
| 920175 | 5,200 | 9.82 | 49,660 | -1,395 | live |
| 600707 | 8,900 | 5.56 | 49,573 | +89 | live |
| 920950 | 3,200 | 15.61 | 49,568 | -384 | live |
| 688121 | 4,600 | 11.06 | 49,404 | -1,472 | live |
| 920703 | 3,700 | 13.75 | 49,395 | -1,480 | live |
| 688132 | 3,000 | 16.77 | 48,990 | -1,320 | live |
| 920245 | 2,100 | 23.82 | 48,552 | -1,465 | live |
| 920212 | 4,160 | 11.54 | 46,717 | -1,274 | live |
| 688606 | 700 | 63.18 | 42,595 | -1,631 | live |

> 注意: 17只中有10只是920xxx(BJ北交所)。这验证了PROJECT_ANATOMY.md的发现——
> BJ股被因子选中进入PT持仓。

**最近5笔交易**:

| 日期 | 方向 | code | 数量 | 成交价 | 佣金 |
|------|------|------|------|--------|------|
| 2026-04-08 | buy | 920245 | 100 | 23.79 | 5.00 |
| 2026-04-08 | sell | 688132 | 200 | 16.75 | 5.00 |
| 2026-04-08 | buy | 920519 | 1,717 | 11.51 | 5.00 |
| 2026-04-08 | buy | 920703 | 100 | 13.69 | 5.00 |
| 2026-04-08 | sell | 688570 | 200 | 17.32 | 5.00 |

## 5. 恢复步骤（重构完成后）

```powershell
# 以管理员身份运行
Get-ScheduledTask | Where-Object {$_.TaskName -like 'QM-*' -or $_.TaskName -like 'QuantMind*'} | Enable-ScheduledTask
# 然后重启CeleryBeat
D:\tools\Servy\servy-cli.exe start --name="QuantMind-CeleryBeat"
```
