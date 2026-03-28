# SOP — 灾备恢复操作手册

> QuantMind V2 灾备恢复标准操作程序 (R6 §8)
> 版本: 1.0 | 日期: 2026-03-28
> 目标RTO: <2小时（L3/L4级别故障，含数据库恢复）

---

## 目录

1. [灾难场景分类](#1-灾难场景分类)
2. [恢复决策树](#2-恢复决策树)
3. [逐步恢复流程](#3-逐步恢复流程)
4. [恢复后验证清单](#4-恢复后验证清单)
5. [联系方式和升级路径](#5-联系方式和升级路径)
6. [定期演练计划](#6-定期演练计划)
7. [附录：常用命令速查](#7-附录常用命令速查)

---

## 1. 灾难场景分类

| 级别 | 场景 | RTO目标 | RPO（数据丢失上限） | 自动恢复 |
|------|------|---------|-------------------|---------|
| **L1** | 进程崩溃（Celery/FastAPI/uvicorn） | <5分钟 | 0 | 是（NSSM自动重启） |
| **L2** | 系统重启 / Windows蓝屏 | <15分钟 | 0 | 是（NSSM服务+Task Scheduler补执行） |
| **L3** | PostgreSQL数据库损坏 / 数据误删 | <1小时 | <24小时 |  否（需手工恢复） |
| **L4** | 主磁盘硬件故障 | <2小时 | <24小时 | 否（需从外置备份恢复） |
| **L5** | 完整硬件故障 / Windows系统全毁 | <4小时 | <24小时 | 否（需重装+完整恢复） |

**备份文件位置**:
- 每日备份: `D:/quantmind-v2/backups/daily/quantmind_v2_YYYYMMDD.dump`
- 月度永久备份: `D:/quantmind-v2/backups/monthly/quantmind_v2_YYYYMMDD.dump`
- Parquet快照: `D:/quantmind-v2/backups/parquet/`

---

## 2. 恢复决策树

```
故障发生
│
├─ 应用进程崩溃（PG/Redis正常）？
│   └─ L1: 检查NSSM是否已自动重启 → 查日志 → 手工重启服务
│
├─ 系统重启/蓝屏后无法正常运行？
│   └─ L2: 检查Windows服务 → 检查任务计划补执行 → 验证数据时效
│
├─ PG报错 / 数据异常 / 表损坏？
│   ├─ 能连接PG但数据错误？
│   │   └─ L3-A: 从最新daily备份恢复（pg_restore → quantmind_v2）
│   └─ PG服务无法启动？
│       └─ L3-B: 重装PG → 从备份恢复
│
├─ D盘报I/O错误 / 磁盘无法挂载？
│   └─ L4: 换新磁盘 → 从外置备份或其他位置恢复
│
└─ 主机完全损坏 / 需换机？
    └─ L5: 新机器安装环境 → 从备份全量恢复
```

---

## 3. 逐步恢复流程

### 3.1 L1: 进程崩溃（RTO <5分钟）

**触发条件**: 应用进程意外退出，PG/Redis正常，无数据丢失。

**Step 1** — 确认NSSM自动重启状态:
```powershell
# 检查服务状态
Get-Service "QM-CeleryWorker" | Select-Object Status
Get-Service "QM-FastAPI" | Select-Object Status
```

**Step 2** — 如未自动重启，手工启动:
```powershell
nssm restart QM-CeleryWorker
nssm restart QM-FastAPI
```

**Step 3** — 查日志确认原因:
```powershell
type D:\quantmind-v2\logs\celery-worker-err.log | Select-Object -Last 50
```

**Step 4** — 验证服务恢复:
```bash
# 测试Celery
cd D:\quantmind-v2\backend
..\.venv\Scripts\python.exe -m celery -A app.tasks inspect ping

# 测试FastAPI
curl http://localhost:8000/health
```

---

### 3.2 L2: 系统重启/蓝屏（RTO <15分钟）

**触发条件**: Windows重启或蓝屏后，需确认所有服务恢复。

**Step 1** — 检查PG和Redis（应自动启动）:
```powershell
Get-Service "postgresql-x64-16" | Select-Object Status
Get-Service "Redis" | Select-Object Status
```

如未启动:
```powershell
Start-Service "postgresql-x64-16"
Start-Service "Redis"
```

**Step 2** — 检查PG连接:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U xin -c "SELECT 1" quantmind_v2
```

**Step 3** — 确认数据时效（确保调度任务已补执行）:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U xin -c "SELECT MAX(trade_date) FROM klines_daily" quantmind_v2
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U xin -c "SELECT MAX(created_at) FROM signals" quantmind_v2
```

**Step 4** — 如调度任务错过，手工补执行:
```powershell
# 在任务计划中手工运行
schtasks /run /tn "QM-DailyPipeline"
```

---

### 3.3 L3: PostgreSQL数据库损坏（RTO <1小时）

**触发条件**: 数据误删、表损坏、PG数据目录故障。

#### 3.3-A: PG可连接但数据异常（误删/逻辑损坏）

**Step 1** — 停止所有写入（防止覆盖更多数据）:
```powershell
nssm stop QM-CeleryWorker
nssm stop QM-FastAPI
# 同时在任务计划中禁用所有QM-*任务
schtasks /change /tn "QM-DailyPipeline" /disable
```

**Step 2** — 查找最新有效备份:
```powershell
dir D:\quantmind-v2\backups\daily\*.dump | Sort-Object LastWriteTime -Descending
```

**Step 3** — 验证备份完整性:
```powershell
cd D:\quantmind-v2
.\.venv\Scripts\python.exe scripts\verify_backup.py
```

**Step 4** — 重命名损坏的DB（保留现场，以防需要取证）:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U xin -c "ALTER DATABASE quantmind_v2 RENAME TO quantmind_v2_corrupted" postgres
```

**Step 5** — 新建目标DB:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\createdb.exe" -U xin quantmind_v2
```

**Step 6** — 从备份恢复（替换 YYYYMMDD 为实际日期）:
```powershell
$BACKUP = "D:\quantmind-v2\backups\daily\quantmind_v2_YYYYMMDD.dump"
& "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" `
    -h localhost -p 5432 -U xin `
    -d quantmind_v2 `
    --no-owner --no-privileges `
    --clean --if-exists `
    $BACKUP
```

预计耗时: 10-30分钟（取决于数据量）。

**Step 7** — 验证恢复结果:
```powershell
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py --skip-restore
```

**Step 8** — 重启所有服务并恢复调度:
```powershell
nssm start QM-CeleryWorker
nssm start QM-FastAPI
schtasks /change /tn "QM-DailyPipeline" /enable
```

#### 3.3-B: PG服务无法启动（数据目录损坏）

**Step 1** — 检查PG日志:
```powershell
type D:\pgdata16\pg_log\*.log | Select-Object -Last 100
```

**Step 2** — 尝试PG修复（如损坏轻微）:
```powershell
& "C:\Program Files\PostgreSQL\16\bin\pg_resetwal.exe" -f D:\pgdata16
```

**Step 3** — 如无法修复，清空数据目录后重新initdb:
```powershell
# 先备份现有数据目录（以防pg_resetwal后可恢复）
Rename-Item D:\pgdata16 D:\pgdata16_broken

# 重新初始化
& "C:\Program Files\PostgreSQL\16\bin\initdb.exe" -D D:\pgdata16 -U xin -E UTF8 --locale=C
Start-Service "postgresql-x64-16"
```

**Step 4** — 继续执行 3.3-A 的 Step 5-8（从备份恢复）。

---

### 3.4 L4: 主磁盘硬件故障（RTO <2小时）

**触发条件**: D盘报I/O错误或无法挂载，需换盘后恢复。

**前提**: 备份文件已存储在其他磁盘（建议外置硬盘或第二块NVMe）。

**Step 1** — 换新磁盘，重新格式化为D盘。

**Step 2** — 安装PostgreSQL 16:
```powershell
# 下载并安装 PostgreSQL 16 Windows版
# 安装路径: C:\Program Files\PostgreSQL\16
# 数据目录: D:\pgdata16
# 用户: xin
```

**Step 3** — 安装Redis（Windows版）并注册为服务。

**Step 4** — 克隆代码仓库:
```powershell
git clone <repo-url> D:\quantmind-v2
```

**Step 5** — 恢复Python环境:
```powershell
cd D:\quantmind-v2\backend
python -m venv ..\.venv
..\.venv\Scripts\pip install -e ".[dev]"
```

**Step 6** — 从外置备份恢复PG数据（同 3.3-A Step 5-7）。

**Step 7** — 恢复.env配置文件（从加密备份）。

**Step 8** — 注册NSSM服务和Task Scheduler任务（参见 `docs/DEV_SCHEDULER.md`）。

---

### 3.5 L5: 完整硬件故障/换机（RTO <4小时）

**触发条件**: 主机完全损坏，需要全新机器。

执行 L4 的所有步骤，额外注意：

- Windows系统激活和驱动安装 (~30分钟)
- miniQMT重新安装和账户绑定（参见 `docs/reference_miniqmt.md`）
- 重新配置Task Scheduler所有定时任务
- 验证钉钉告警配置（DINGTALK_TOKEN等环境变量）

---

## 4. 恢复后验证清单

完成任何L3以上级别恢复后，必须逐项确认：

```
□ 1. PG连接正常
     psql -U xin -c "SELECT version()" quantmind_v2

□ 2. Redis连接正常
     redis-cli ping  → 应返回 PONG

□ 3. 关键表行数符合预期
     python scripts/disaster_recovery_verify.py --skip-restore

□ 4. 最新数据日期（≤1个交易日前）
     psql -U xin -c "SELECT MAX(trade_date) FROM klines_daily" quantmind_v2

□ 5. 因子数据时效（最新factor_values日期）
     psql -U xin -c "SELECT MAX(trade_date) FROM factor_values" quantmind_v2

□ 6. v1.1策略配置完整（5个因子）
     psql -U xin -c "SELECT factor_name FROM strategy_configs WHERE version='v1.1'" quantmind_v2

□ 7. Paper Trading心跳正常（watchdog最近一次运行）
     psql -U xin -c "SELECT MAX(check_time) FROM health_checks WHERE check_type='pt_heartbeat'" quantmind_v2

□ 8. 系统健康检查通过
     python scripts/health_check.py

□ 9. Celery Worker存活（至少1个worker响应）
     cd backend && python -m celery -A app.tasks inspect ping

□ 10. 钉钉告警测试（确认告警链路正常）
      python scripts/test_dingtalk.py
```

---

## 5. 联系方式和升级路径

本系统为个人量化系统，无外部团队。

| 场景 | 处理方式 |
|------|---------|
| L1/L2 自动恢复失败 | 查日志 → 自行修复 → 参考本SOP |
| L3 数据损坏 | 立即停止所有写入 → 按3.3流程恢复 → 恢复后做10项验证 |
| L4/L5 硬件故障 | 备份文件在外置存储 → 换硬件 → 按3.4/3.5恢复 |
| 备份文件也损坏 | 从Parquet快照恢复klines_daily+factor_values → 补算因子 |
| 交易日发生L3+ | Paper Trading期间: 当日持仓不变，次日再操作；实盘期间: 联系券商冻结账户 |

**备份文件应存储位置**（重要，决定L4的RTO）:
- 主备份: `D:/quantmind-v2/backups/` (同盘，防PG损坏)
- 外置备份: 外置硬盘或第二块NVMe（防主盘故障）
- 月度备份建议额外保存一份到云存储（阿里云OSS/百度网盘等）

---

## 6. 定期演练计划

### 6.1 每月演练（第一个周日，手动执行）

```powershell
# 每月第一个周日执行灾备演练
cd D:\quantmind-v2

# 运行完整验证（含实际恢复到测试DB）
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py

# 记录结果到演练日志
```

演练通过标准:
- 整体状态: PASS
- 所有关键表行数达标
- 恢复耗时 < 30分钟（对应100GB以内数据量）

### 6.2 每周快速验证（每周日 03:00，Task Scheduler自动）

```powershell
# 仅验证备份完整性，不做实际恢复（快速，<2分钟）
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py --skip-restore
```

### 6.3 演练记录表

| 日期 | 演练类型 | 恢复耗时 | 通过/失败 | 发现的问题 |
|------|---------|---------|---------|-----------|
| 2026-04-05 | 月度演练（首次） | — | — | — |
| 2026-05-03 | 月度演练 | — | — | — |

---

## 7. 附录：常用命令速查

### PostgreSQL命令
```powershell
$PG = "C:\Program Files\PostgreSQL\16\bin"

# 连接DB
& "$PG\psql.exe" -U xin -d quantmind_v2

# 备份
& "$PG\pg_dump.exe" -U xin -Fc -Z5 -f backup.dump quantmind_v2

# 恢复
& "$PG\pg_restore.exe" -U xin -d quantmind_v2 --no-owner --no-privileges backup.dump

# 验证备份内容
& "$PG\pg_restore.exe" --list backup.dump | Select-String "TABLE "

# 创建/删除DB
& "$PG\createdb.exe" -U xin quantmind_v2_dr_test
& "$PG\dropdb.exe" -U xin --if-exists quantmind_v2_dr_test
```

### 验证脚本
```powershell
cd D:\quantmind-v2

# 备份完整性验证（快速，不恢复）
.\.venv\Scripts\python.exe scripts\verify_backup.py

# 灾备恢复完整验证
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py

# 跳过实际恢复（只验证完整性）
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py --skip-restore

# 仅检查文件存在
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py --dry-run

# 指定备份文件
.\.venv\Scripts\python.exe scripts\disaster_recovery_verify.py --backup-file D:\quantmind-v2\backups\daily\quantmind_v2_20260328.dump
```

### NSSM服务管理
```powershell
nssm status QM-CeleryWorker
nssm start QM-CeleryWorker
nssm stop QM-CeleryWorker
nssm restart QM-CeleryWorker
```

### 健康检查
```powershell
cd D:\quantmind-v2
.\.venv\Scripts\python.exe scripts\health_check.py
```
