# R6: 个人量化系统生产架构研究报告

> QuantMind V2 开发蓝图研究维度 R6
> 日期: 2026-03-28
> 核心问题: 个人量化系统如何稳定运行？调度/监控/容错/灾备如何设计？

---

## 目录

1. [问题定义：当前运维缺失项](#1-问题定义当前运维缺失项)
2. [开源项目运维方案对比](#2-开源项目运维方案对比)
3. [Windows 原生运维方案](#3-windows-原生运维方案)
4. [调度系统设计（可靠性保证）](#4-调度系统设计可靠性保证)
5. [监控告警体系](#5-监控告警体系)
6. [数据备份与灾备](#6-数据备份与灾备)
7. [日志管理](#7-日志管理)
8. [故障恢复 SOP](#8-故障恢复-sop)
9. [安全性](#9-安全性)
10. [成本估算](#10-成本估算)
11. [落地计划（按优先级排序）](#11-落地计划按优先级排序)
12. [参考文献](#12-参考文献)

---

## 1. 问题定义：当前运维缺失项

### 1.1 现状盘点（44% 完成）

| 模块 | 状态 | 说明 |
|------|------|------|
| 健康预检 | **已完成** | `scripts/health_check.py` — PG/数据新鲜度/因子NaN/磁盘 |
| PT心跳watchdog | **已完成** | `scripts/pt_watchdog.py` — Task Scheduler 20:00触发 |
| 钉钉告警 | **已完成** | `NotificationService` — P0/P1分级推送 |
| config_guard | **已完成** | Step 0.5配置一致性检查 |
| Celery Beat定时任务 | **缺失** | 当前仅Task Scheduler，无Celery Beat编排 |
| 日志聚合 | **缺失** | 散落在各脚本logging，无统一格式/轮转/聚合 |
| 数据备份自动化 | **缺失** | CLAUDE.md规定了pg_dump+Parquet双备份，未实现自动化 |
| 灾备恢复流程 | **缺失** | 无SOP、无恢复验证 |
| 监控仪表盘 | **缺失** | 无可视化系统状态面板 |

### 1.2 风险评级

| 风险 | 概率 | 影响 | 优先级 |
|------|------|------|--------|
| 调度链路静默失败（无人发现） | 中 | 极高 — 漏交易 | **P0** |
| 数据库损坏/数据丢失 | 低 | 极高 — 全部历史丢失 | **P0** |
| 磁盘爆满（日志/备份） | 中 | 高 — 系统停摆 | **P1** |
| miniQMT连接断开 | 中 | 高 — 执行失败 | **P1** |
| 系统崩溃后无法快速恢复 | 低 | 高 — 停摆数天 | **P1** |
| API密钥泄露 | 低 | 高 — 资金风险 | **P2** |

### 1.3 一人运维的核心矛盾

个人量化系统最大的敌人不是技术复杂度，而是**注意力枯竭**。系统必须满足：

1. **零巡检假设** — 正常运行时不需要人看任何东西
2. **故障主动推送** — 出问题钉钉/微信第一时间通知
3. **快速恢复** — 从零恢复到可运行 < 2小时（有SOP+备份）
4. **防劣化** — 日志/备份/临时文件不能悄悄吃光磁盘

---

## 2. 开源项目运维方案对比

### 2.1 Qlib（微软研究院）

- **定位**: AI量化研究平台，非生产交易基础设施
- **部署模式**: 离线（本地数据）或在线（共享数据服务），支持Azure CLI脚本自动部署
- **生产能力**: `OnlineManager` 提供在线服务和生产更新编排，研究代码和配置可直接部署到生产环境
- **容错**: 未明确提供生产级容错机制
- **对QuantMind的启示**: Qlib的YAML工作流定义(`qrun`)值得借鉴——用声明式配置定义调度链路，而非硬编码脚本

### 2.2 vnpy/VeighNa

- **定位**: 全功能量化交易平台框架
- **架构特点**: 事件驱动引擎(`vnpy_evo.event`) + RPC分布式通信
- **数据库支持**: TimescaleDB / MongoDB / InfluxDB / TDengine 多种后端
- **容错**: CTA策略模块支持精细订单管理，但运维监控能力文档较少
- **对QuantMind的启示**: vnpy的事件驱动模型适合实时交易，但QuantMind的T日盘后计算→T+1执行模式更适合批处理调度

### 2.3 QuantConnect LEAN

- **定位**: 开源算法交易引擎（C#/Python）
- **架构**: 高度模块化——`IDataFeed`/`ITransactionHandler`/`IRealTimeHandler`可插拔
- **部署**: 支持本地和云端双模式，LEAN CLI统一管理
- **容错**: 模块化设计本身就是容错基础——数据源故障可切换，交易处理器可替换
- **对QuantMind的启示**: LEAN的接口抽象层（如`BaseBroker`模式）QuantMind已采用；其本地+云端双模式可作为远程监控参考

### 2.4 对比总结

| 维度 | Qlib | vnpy | LEAN | QuantMind现状 |
|------|------|------|------|---------------|
| 调度 | YAML workflow | 事件驱动 | 引擎内置 | Task Scheduler |
| 监控 | 无 | 基础日志 | 引擎回调 | health_check+watchdog |
| 容错 | 无 | RPC重连 | 模块切换 | 手动恢复 |
| 灾备 | 数据版本化 | 无 | 云端备份 | 无自动化 |
| 适合个人 | 研究可以 | 可以 | 学习曲线高 | **需补齐5项** |

**关键结论**: 三个项目都不是"个人运维"场景的典范。个人系统需要的是**轻量+自愈+主动告警**，而非分布式高可用。

---

## 3. Windows 原生运维方案

### 3.1 进程管理：NSSM（推荐）

**NSSM (Non-Sucking Service Manager)** 是Windows上将任意可执行文件封装为Windows Service的标准工具。

核心能力：
- 将Python脚本注册为Windows Service（开机自启、崩溃自动重启）
- 捕获stdout/stderr重定向到日志文件
- 支持配置启动延迟、重启间隔、依赖关系
- 单文件部署（`nssm.exe`，无需安装）

**QuantMind推荐的NSSM服务清单**:

```
# 1. Redis（已是Windows服务，不需要NSSM）

# 2. Celery Worker（关键——当前最大运维隐患）
nssm install QM-CeleryWorker "D:\quantmind-v2\.venv\Scripts\python.exe"
nssm set QM-CeleryWorker AppParameters "-m celery -A app.tasks worker --pool=solo --concurrency=1 -Q default"
nssm set QM-CeleryWorker AppDirectory "D:\quantmind-v2\backend"
nssm set QM-CeleryWorker AppStdout "D:\quantmind-v2\logs\celery-worker.log"
nssm set QM-CeleryWorker AppStderr "D:\quantmind-v2\logs\celery-worker-err.log"
nssm set QM-CeleryWorker AppRestartDelay 5000

# 3. FastAPI（如需常驻）
nssm install QM-FastAPI "D:\quantmind-v2\.venv\Scripts\python.exe"
nssm set QM-FastAPI AppParameters "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
nssm set QM-FastAPI AppDirectory "D:\quantmind-v2\backend"
```

### 3.2 Celery on Windows：已知问题与方案

**核心问题**: Celery 4.x+ 官方不支持Windows，prefork池无法使用（Windows不支持fork）。

**可行方案**（按推荐顺序）:

| 方案 | 适用场景 | 说明 |
|------|---------|------|
| `--pool=solo` | CPU密集型（因子计算） | 单进程单任务，启动多个worker实例获得并发 |
| `--pool=threads` | I/O密集型（数据拉取） | 线程池，适合网络I/O |
| `--pool=gevent` | 高并发I/O | 协程，需安装gevent |

**QuantMind推荐配置**:
```bash
# Worker 1: 因子计算（CPU密集）
celery -A app.tasks worker --pool=solo -Q factor_calc -n worker-factor@%h

# Worker 2: 数据拉取（I/O密集）
celery -A app.tasks worker --pool=threads --concurrency=4 -Q data_fetch -n worker-data@%h

# Worker 3: 通用任务
celery -A app.tasks worker --pool=solo -Q default -n worker-default@%h
```

**必须安装**: `pip install pywin32`（Windows Celery依赖）

### 3.3 Task Scheduler 高级用法

Task Scheduler 是当前调度的主力。以下是加固措施：

```powershell
# 创建任务时启用关键可靠性选项
$action = New-ScheduledTaskAction -Execute "D:\quantmind-v2\.venv\Scripts\python.exe" `
    -Argument "D:\quantmind-v2\scripts\daily_signal.py" `
    -WorkingDirectory "D:\quantmind-v2"

$trigger = New-ScheduledTaskTrigger -Daily -At "4:30PM"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `                  # 错过时间则启动时补执行
    -RestartCount 3 `                      # 失败重试3次
    -RestartInterval (New-TimeSpan -Minutes 5) ` # 重试间隔5分钟
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) ` # 超时30分钟强杀
    -AllowStartIfOnBatteries `             # UPS供电时也执行
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew           # 禁止重复实例

Register-ScheduledTask -TaskName "QM-DailySignal" `
    -Action $action -Trigger $trigger -Settings $settings `
    -User "xin" -RunLevel Highest
```

**关键设置**:
- `StartWhenAvailable` — 系统关机期间错过的任务，开机后立即补执行
- `RestartCount + RestartInterval` — 内置重试，无需在脚本中实现
- `ExecutionTimeLimit` — 防止僵死进程永远占用

---

## 4. 调度系统设计（可靠性保证）

### 4.1 Task Scheduler vs Celery Beat vs APScheduler

| 维度 | Task Scheduler | Celery Beat | APScheduler |
|------|---------------|-------------|-------------|
| **可靠性** | 高（OS级别，开机补执行） | 中（需额外保活，Windows不稳定） | 中（进程内，崩溃即停） |
| **Windows支持** | 原生 | 官方不支持 | 完全支持 |
| **任务依赖** | 无 | 无（需自行编排） | 无 |
| **动态调度** | 需PowerShell脚本 | 代码动态增删 | 代码动态增删 |
| **错过补偿** | StartWhenAvailable | 无内置 | coalesce+misfire_grace_time |
| **监控** | Event Viewer | Flower | 回调函数 |
| **外部依赖** | 无 | Redis/RabbitMQ | 无（可选DB持久化） |
| **适合场景** | 固定时间批处理 | 分布式异步任务 | 进程内灵活调度 |

### 4.2 推荐方案：双层调度架构

```
层1: Task Scheduler（主调度器）
  ├── 16:30 daily_pipeline.py    — 数据拉取→因子计算→信号生成
  ├── 09:00 execution_pipeline.py — 读指令→执行
  ├── 20:00 pt_watchdog.py        — 心跳检测
  ├── 02:00 backup_pipeline.py    — 数据库备份
  └── 06:00 log_rotate.py         — 日志轮转清理

层2: APScheduler（进程内子调度，嵌入FastAPI）
  ├── 每5分钟 system_health_check  — PG/Redis/磁盘/内存
  ├── 每1小时 factor_freshness     — 因子数据时效检查
  └── 交易日判断                    — 非交易日跳过所有任务
```

**设计理由**:
1. **Task Scheduler 做主调度** — OS级可靠性，开机补执行，不依赖Python进程存活
2. **APScheduler 做辅助** — 嵌入FastAPI进程，负责高频健康检查，无需额外依赖
3. **不用Celery Beat** — Windows上Celery本身就是隐患，Beat更是单点故障。Celery Worker只做任务执行，调度权交给Task Scheduler

### 4.3 任务失败重试策略

```python
# daily_pipeline.py 重试模式
RETRY_CONFIG = {
    "data_fetch": {
        "max_retries": 3,
        "intervals": [60, 300, 900],     # 1分钟→5分钟→15分钟
        "on_final_fail": "P0_ALERT",      # 最终失败→P0告警
    },
    "factor_calc": {
        "max_retries": 2,
        "intervals": [30, 120],
        "on_final_fail": "P0_ALERT_SKIP_SIGNAL",  # 跳过当日信号
    },
    "signal_gen": {
        "max_retries": 1,
        "intervals": [60],
        "on_final_fail": "P0_ALERT_HOLD_POSITION",  # 维持现有持仓
    },
    "execution": {
        "max_retries": 2,
        "intervals": [30, 60],
        "on_final_fail": "P0_ALERT_MANUAL",  # 人工介入
    },
}
```

**最终失败策略核心原则**: 宁可不交易，不可错交易。

- 数据拉取失败 → 用前一日数据生成保守信号（或跳过当日）
- 因子计算失败 → 维持现有持仓不动
- 信号生成失败 → 维持现有持仓不动
- 执行失败 → P0告警 + 钉钉推送手动操作指令

### 4.4 交易日历与节假日处理

当前方案（`trading_calendar` 表 + Tushare导入）**已经够用**，需要补充：

```python
# 调度入口统一门卫
def should_run_today() -> bool:
    """每个调度任务的第一行调用此函数。"""
    conn = get_sync_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT is_trading_day FROM trading_calendar "
            "WHERE market = 'astock' AND trade_date = CURRENT_DATE"
        )
        row = cur.fetchone()
        if row is None:
            # 日历数据缺失 → P1告警 + 默认不执行
            send_alert("P1", "交易日历缺失", f"今日 {date.today()} 无日历数据")
            return False
        return row[0]
    finally:
        conn.close()
```

**年度维护**: 每年1月第一个工作日，从Tushare拉取当年完整交易日历并验证。

---

## 5. 监控告警体系

### 5.1 Prometheus + Grafana vs 自建轻量方案

| 维度 | Prometheus + Grafana | 自建轻量方案 |
|------|---------------------|-------------|
| 功能完整度 | 极高 | 够用即可 |
| 安装运维成本 | 高（3个服务: Prometheus + Node Exporter + Grafana） | 低（1个脚本 + 1张PG表） |
| 内存占用 | ~500MB-1GB | <50MB |
| 学习曲线 | PromQL + Dashboard配置 | 纯Python |
| 可视化 | 专业Dashboard | 前端React页面 / 钉钉文本 |
| 适合规模 | 10+ 服务器 | 1台机器 |
| 长期价值 | 有，可扩展 | 足够个人使用 |

**推荐**: **自建轻量方案**，理由：
1. 只有1台机器，Prometheus体系是杀鸡用牛刀
2. 已有PG + FastAPI + 钉钉，组合即可成监控体系
3. 内存节省~1GB，对32GB系统是有意义的（已有PG+Redis+Celery+Python吃~16GB）
4. 如果前端React仪表盘做出来，监控页面是其中一个页面

### 5.2 监控指标清单

```python
MONITOR_METRICS = {
    # --- 系统级（每5分钟采集） ---
    "system": {
        "cpu_percent": {"warn": 80, "crit": 95, "unit": "%"},
        "memory_percent": {"warn": 75, "crit": 90, "unit": "%"},
        "disk_free_gb": {"warn": 100, "crit": 50, "unit": "GB"},
        "disk_free_percent": {"warn": 10, "crit": 5, "unit": "%"},
    },
    # --- 数据库级（每5分钟采集） ---
    "database": {
        "pg_connections_active": {"warn": 80, "crit": 95, "unit": "个"},
        "pg_connections_idle": {"warn": 50, "crit": None, "unit": "个"},
        "pg_database_size_gb": {"warn": 8, "crit": 10, "unit": "GB"},
        "redis_memory_mb": {"warn": 400, "crit": 480, "unit": "MB"},
        "redis_connected_clients": {"warn": 50, "crit": None, "unit": "个"},
    },
    # --- 业务级（事件驱动采集） ---
    "business": {
        "data_freshness_hours": {"warn": 2, "crit": 24, "unit": "小时"},
        "factor_nan_ratio": {"warn": 0.05, "crit": 0.10, "unit": "比例"},
        "signal_generated": {"warn": None, "crit": "missing", "unit": "bool"},
        "execution_fill_rate": {"warn": 0.95, "crit": 0.90, "unit": "比例"},
        "pt_heartbeat_age_hours": {"warn": 20, "crit": 28, "unit": "小时"},
    },
    # --- 进程级（每5分钟采集） ---
    "process": {
        "celery_workers_alive": {"warn": 2, "crit": 0, "unit": "个"},
        "fastapi_alive": {"warn": None, "crit": False, "unit": "bool"},
        "miniQMT_connected": {"warn": None, "crit": False, "unit": "bool"},
    },
}
```

### 5.3 告警分级标准

| 级别 | 响应时间 | 通知渠道 | 标准 | 示例 |
|------|---------|---------|------|------|
| **P0** | 立即 | 钉钉+短信/电话 | 影响交易执行或数据安全 | 调度链路失败 / PG崩溃 / miniQMT断连(执行日) / 磁盘<50GB |
| **P1** | 当日 | 钉钉 | 影响下一次交易或数据质量 | 因子NaN>5% / 数据过期>24h / Celery worker<2 / 内存>90% |
| **P2** | 周末 | 钉钉(汇总) | 预防性/趋势性 | 磁盘<100GB / PG膨胀 / 日志累积>10GB / 备份>7天未验证 |

### 5.4 实现架构

```
scripts/system_monitor.py（APScheduler每5分钟）
  ├── collect_system_metrics()    # psutil
  ├── collect_db_metrics()        # PG/Redis
  ├── collect_process_metrics()   # 检查进程存活
  └── evaluate_and_alert()        # 对比阈值→写入health_checks表→触发告警

health_checks 表（已在DDL中设计）
  ├── check_time, check_type, status, detail
  └── 保留30天，自动清理

告警去重:
  ├── 同一告警1小时内不重复发送
  ├── P0连续失败升级为"持续告警"（每30分钟重发）
  └── P2汇总为每周五17:00一条消息
```

---

## 6. 数据备份与灾备

### 6.1 备份策略

| 数据 | 大小 | 备份方式 | 频率 | 保留 |
|------|------|---------|------|------|
| PG全库 | ~5GB | `pg_dump -Fc` (自定义压缩格式) | 每日02:00 | 7天滚动 + 每月1号永久 |
| factor_values | ~15GB(1.38亿行) | TimescaleDB chunk级导出 | 每周日增量 | 4周滚动 |
| klines_daily | ~2GB | Parquet快照 | 每周日 | 4份滚动 |
| strategy_configs | <1MB | `pg_dump -t strategy_configs` | 每次变更 | 全部保留 |
| 参数变更日志 | <10MB | 随PG全库备份 | 每日 | 同PG |
| 代码仓库 | ~500MB | git push remote | 每次commit | 全部 |
| .env + 配置 | <1KB | 加密备份到外置硬盘 | 每次变更 | 全部 |

### 6.2 实现方案

```powershell
# scripts/backup_pipeline.ps1 — Task Scheduler每日02:00执行

$BACKUP_DIR = "E:\quantmind-backups"  # 外置硬盘或第二块NVMe
$DATE = Get-Date -Format "yyyy-MM-dd"
$PG_BIN = "C:\Program Files\PostgreSQL\16\bin"

# Step 1: PG全库压缩备份
& "$PG_BIN\pg_dump" -U xin -Fc quantmind > "$BACKUP_DIR\daily\quantmind_$DATE.dump"

# Step 2: 清理7天前的每日备份
Get-ChildItem "$BACKUP_DIR\daily\*.dump" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item

# Step 3: 每月1号额外保存到monthly目录
if ((Get-Date).Day -eq 1) {
    Copy-Item "$BACKUP_DIR\daily\quantmind_$DATE.dump" "$BACKUP_DIR\monthly\"
}

# Step 4: 备份大小验证（过小说明备份失败）
$size = (Get-Item "$BACKUP_DIR\daily\quantmind_$DATE.dump").Length / 1MB
if ($size -lt 100) {  # <100MB说明异常
    # 触发P0告警
    python D:\quantmind-v2\scripts\send_alert.py "P0" "备份异常" "备份文件仅${size}MB"
}
```

### 6.3 factor_values 大表备份策略

**不推荐增量备份**，理由：
1. TimescaleDB hypertable按月分chunk，`pg_dump`已经很高效
2. WAL归档（增量）配置复杂，个人系统维护成本不值得
3. 1.38亿行 `pg_dump -Fc` 压缩后约3-5GB，NVMe写入<5分钟

**推荐方案**: 全量 `pg_dump` + Parquet关键表快照双保险

```python
# 每周日额外导出Parquet（二级备份，可独立于PG恢复）
import pandas as pd

query = """
SELECT trade_date, symbol_id, factor_name, value
FROM factor_values
WHERE trade_date >= CURRENT_DATE - INTERVAL '90 days'
"""
df = pd.read_sql(query, conn)
df.to_parquet(f"E:/quantmind-backups/parquet/factor_values_{date}.parquet",
              compression="zstd", index=False)
```

### 6.4 备份验证自动化

```python
# scripts/verify_backup.py — 每周日03:00（备份完成1小时后）
def verify_latest_backup():
    """恢复到临时数据库，验证关键表行数。"""
    backup_file = get_latest_backup()

    # 1. 恢复到临时数据库
    subprocess.run([
        "pg_restore", "-U", "xin", "-d", "quantmind_verify",
        "--no-owner", "--clean", "--if-exists",
        str(backup_file)
    ], check=True)

    # 2. 验证关键表
    conn = psycopg2.connect(dbname="quantmind_verify", user="xin")
    checks = {
        "klines_daily": ("SELECT COUNT(*) FROM klines_daily", 5_000_000),
        "factor_values": ("SELECT COUNT(*) FROM factor_values", 100_000_000),
        "symbols": ("SELECT COUNT(*) FROM symbols", 5000),
        "trading_calendar": ("SELECT COUNT(*) FROM trading_calendar", 1000),
    }
    for table, (sql, min_rows) in checks.items():
        count = conn.execute(sql).fetchone()[0]
        if count < min_rows:
            send_alert("P1", f"备份验证失败: {table}",
                      f"行数{count} < 预期最低{min_rows}")
            return False

    # 3. 清理临时数据库
    conn.close()
    subprocess.run(["dropdb", "-U", "xin", "quantmind_verify"])
    return True
```

### 6.5 灾备级别定义

| 级别 | 场景 | RTO(恢复时间) | RPO(数据丢失) |
|------|------|-------------|-------------|
| L1 | 进程崩溃 | 5分钟 | 0（NSSM自动重启） |
| L2 | 系统重启/蓝屏 | 15分钟 | 0（Task Scheduler补执行） |
| L3 | 数据库损坏 | 1小时 | <24小时（每日备份） |
| L4 | 硬盘损坏 | 2小时 | <24小时（外置硬盘备份） |
| L5 | 系统全毁 | 4小时 | <24小时 |

---

## 7. 日志管理

### 7.1 结构化日志方案：structlog

**推荐**: `structlog` — 生产级结构化日志库，支持JSON输出、异步、上下文绑定。

```python
# backend/app/logging_config.py
import structlog
import logging
from logging.handlers import RotatingFileHandler

def setup_logging(env: str = "production"):
    """统一日志配置。"""

    # 处理器链
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if env == "development":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    # 文件Handler（带轮转）
    handler = RotatingFileHandler(
        "D:/quantmind-v2/logs/quantmind.log",
        maxBytes=50 * 1024 * 1024,  # 50MB per file
        backupCount=10,              # 保留10个文件 = 500MB上限
        encoding="utf-8",
    )
    logging.root.addHandler(handler)
    logging.root.setLevel(logging.INFO)
```

**输出示例**（JSON格式，一行一条，方便grep/jq）:
```json
{"event":"signal_generated","level":"info","timestamp":"2026-03-28T17:20:15Z","strategy":"v1.1","stock_count":15,"elapsed_sec":12.3}
{"event":"execution_submit","level":"info","timestamp":"2026-03-29T09:30:01Z","order_id":"ORD-20260329-001","symbol":"600519","side":"buy","qty":100}
{"event":"factor_calc_failed","level":"error","timestamp":"2026-03-28T17:05:22Z","factor":"amihud_20","error":"division by zero","symbol_count":12}
```

### 7.2 日志分类与轮转

| 日志文件 | 内容 | 最大大小 | 保留 |
|---------|------|---------|------|
| `quantmind.log` | 主日志（全业务） | 50MB x 10 = 500MB | 10天 |
| `factor_calc.log` | 因子计算详细 | 50MB x 5 = 250MB | 5天 |
| `celery-worker.log` | Celery输出 | 50MB x 5 = 250MB | 5天 |
| `execution.log` | 交易执行审计 | 10MB x 20 = 200MB | 永久(外置硬盘归档) |
| `backup.log` | 备份操作 | 10MB x 5 = 50MB | 30天 |
| **总计** | | **~1.25GB** | |

### 7.3 审计日志（关键操作追踪）

```python
# 审计日志写入专用表，不依赖文件
# DDL: audit_log表（补充到DDL_FINAL.sql）
"""
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event_time TIMESTAMPTZ DEFAULT NOW(),
    actor VARCHAR(50) NOT NULL,       -- 'system'/'user'/'celery'
    action VARCHAR(100) NOT NULL,     -- 'param_change'/'strategy_switch'/'manual_trade'
    target VARCHAR(200),              -- 被操作对象
    old_value JSONB,
    new_value JSONB,
    ip_address INET
);
CREATE INDEX idx_audit_log_time ON audit_log (event_time DESC);
```

**必须审计的操作**:
- 策略参数变更（strategy_configs版本变化）
- 手动覆盖信号（跳过/强制执行）
- 风控阈值修改
- 数据修补/重算
- PT毕业标准降低

### 7.4 日志清理自动化

```python
# scripts/log_rotate.py — Task Scheduler每日06:00
import glob
import os
from datetime import datetime, timedelta

LOG_DIR = "D:/quantmind-v2/logs"
ARCHIVE_DIR = "E:/quantmind-backups/logs"

def rotate_logs():
    """清理过期日志，归档执行日志。"""
    now = datetime.now()

    # 1. 清理超过30天的普通日志
    for f in glob.glob(f"{LOG_DIR}/*.log.*"):
        age = now - datetime.fromtimestamp(os.path.getmtime(f))
        if age > timedelta(days=30):
            os.remove(f)

    # 2. 归档执行日志到外置硬盘
    for f in glob.glob(f"{LOG_DIR}/execution.log.*"):
        if os.path.getmtime(f) < (now - timedelta(days=7)).timestamp():
            dest = f"{ARCHIVE_DIR}/{os.path.basename(f)}"
            shutil.move(f, dest)

    # 3. 检查总日志大小
    total_mb = sum(os.path.getsize(f) for f in glob.glob(f"{LOG_DIR}/*")) / 1024 / 1024
    if total_mb > 2000:  # > 2GB
        send_alert("P2", "日志空间告警", f"日志目录 {total_mb:.0f}MB")
```

---

## 8. 故障恢复 SOP

### 8.1 L1: 进程崩溃（RTO < 5分钟）

```
自动恢复（NSSM处理）:
1. NSSM检测进程退出 → 等待5秒 → 自动重启
2. 重启成功 → 记录日志 → 正常运行
3. 连续3次重启失败 → P0告警 → 人工介入

人工操作:
1. 查看日志: type D:\quantmind-v2\logs\celery-worker-err.log
2. 常见原因: 内存不足/PG连接满/Redis宕机
3. 修复后: nssm restart QM-CeleryWorker
```

### 8.2 L2: 系统重启/蓝屏（RTO < 15分钟）

```
自动恢复:
1. Windows启动 → PG/Redis Windows服务自动启动
2. NSSM注册的服务自动启动（Celery/FastAPI）
3. Task Scheduler StartWhenAvailable → 补执行错过的任务

验证清单（开机后人工检查，或由开机脚本自动检查）:
□ PG连接正常: psql -U xin -c "SELECT 1" quantmind
□ Redis连接正常: redis-cli ping
□ Celery Worker存活: celery -A app.tasks inspect ping
□ 最新数据日期: psql -c "SELECT MAX(trade_date) FROM klines_daily"
□ 上次信号生成时间: psql -c "SELECT MAX(created_at) FROM signals"
```

### 8.3 L3: 数据库损坏（RTO < 1小时）

```
诊断:
1. 尝试启动PG: net start postgresql-x64-16
2. 查看PG日志: type "D:\pgdata16\log\postgresql-*.log"
3. 如果corruption → 执行恢复

恢复步骤:
1. 停止所有依赖PG的服务
   net stop postgresql-x64-16

2. 备份当前损坏数据目录（保留现场）
   robocopy D:\pgdata16 E:\pgdata16-corrupted /MIR

3. 清理数据目录
   rd /s /q D:\pgdata16

4. 初始化新PG实例
   initdb -D D:\pgdata16 -U xin -E UTF8

5. 启动PG
   net start postgresql-x64-16

6. 恢复最近备份
   pg_restore -U xin -d quantmind --clean --if-exists E:\quantmind-backups\daily\quantmind_latest.dump

7. 验证关键表行数
   psql -U xin -d quantmind -c "SELECT 'klines_daily', COUNT(*) FROM klines_daily
   UNION ALL SELECT 'factor_values', COUNT(*) FROM factor_values
   UNION ALL SELECT 'symbols', COUNT(*) FROM symbols"

8. 补拉缺失数据（如果备份比当前晚1天）
   python scripts/fetch_daily_data.py --start-date 2026-03-27

9. 重启所有服务
   nssm restart QM-CeleryWorker
   nssm restart QM-FastAPI
```

### 8.4 L4: 硬盘损坏（RTO < 2小时）

```
前提: 外置硬盘 E: 有完整备份

1. 更换硬盘，安装Windows（或从系统镜像恢复）
2. 安装PG16 + Redis + Python 3.11+
3. git clone 代码仓库
4. 恢复.env配置（从加密备份）
5. 执行L3步骤4-9恢复数据库
6. pip install -r requirements.txt
7. 注册NSSM服务 + Task Scheduler任务
8. 运行完整健康检查: python scripts/health_check.py
```

### 8.5 miniQMT 连接断开自动重连

```python
# backend/app/services/qmt_broker.py

class MiniQMTBroker(BaseBroker):
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_INTERVALS = [5, 15, 30, 60, 120]  # 秒

    async def _ensure_connected(self):
        """每次操作前检查连接，断开则自动重连。"""
        if self._is_connected():
            return

        for attempt, wait in enumerate(self.RECONNECT_INTERVALS):
            try:
                logger.warning(f"miniQMT断连，第{attempt+1}次重连...")
                await self._connect()
                logger.info("miniQMT重连成功")
                return
            except Exception as e:
                logger.error(f"重连失败: {e}")
                if attempt < len(self.RECONNECT_INTERVALS) - 1:
                    await asyncio.sleep(wait)

        # 全部重连失败
        send_p0_alert("miniQMT连接失败",
                      f"连续{self.MAX_RECONNECT_ATTEMPTS}次重连失败，需人工介入")
        raise ConnectionError("miniQMT连接不可恢复")

    async def submit_order(self, order):
        await self._ensure_connected()
        # ... 执行逻辑
```

---

## 9. 安全性

### 9.1 API密钥管理

| 方案 | 安全等级 | 适合场景 |
|------|---------|---------|
| `.env` 文件 | 中 | 个人单机（当前方案） |
| Windows Credential Manager | 高 | 需要OS级别保护 |
| HashiCorp Vault | 极高 | 团队/多机（过度工程） |
| 环境变量（不落盘） | 中高 | 敏感密钥加一层保护 |

**当前方案(.env)加固措施**:
```
1. .env 加入 .gitignore（已做）
2. .env 文件权限限制为当前用户只读
   icacls D:\quantmind-v2\backend\.env /inheritance:r /grant:r "xin:R"
3. 敏感密钥（miniQMT凭证）不存.env，用Windows Credential Manager
4. .env.example 保留结构但不含真实值
```

### 9.2 miniQMT凭证保护

```python
# 使用 Windows Credential Manager (keyring库)
import keyring

# 存储（首次手动执行一次）
keyring.set_password("quantmind", "qmt_account", "实际账号")
keyring.set_password("quantmind", "qmt_password", "实际密码")

# 读取（代码中使用）
account = keyring.get_password("quantmind", "qmt_account")
password = keyring.get_password("quantmind", "qmt_password")
```

### 9.3 远程访问方案

**需求**: 出门在外查看系统状态、处理告警

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| 钉钉机器人 | 零成本、已有 | 只能接收告警、不能操作 | **必须有** |
| Tailscale VPN | 免费、零配置NAT穿越 | 需安装客户端 | **推荐** |
| 向日葵/ToDesk远程桌面 | 可完全操作 | 延迟高、需要屏幕 | 备用 |
| Cloudflare Tunnel | 暴露FastAPI到公网 | 安全风险 | 不推荐 |

**推荐组合**:
1. **钉钉告警**（被动接收）— 已有
2. **Tailscale + SSH/RDP**（主动操作）— 免费个人版支持100设备
3. **FastAPI状态API**（程序化查询）— 通过Tailscale内网访问

```python
# 极简状态API（通过Tailscale VPN在外网查询）
@router.get("/api/v1/system/status")
async def system_status():
    return {
        "pt_day": get_pt_day_count(),
        "nav": get_latest_nav(),
        "last_signal": get_last_signal_time(),
        "pg_ok": check_pg(),
        "redis_ok": check_redis(),
        "celery_workers": get_worker_count(),
        "disk_free_gb": get_disk_free(),
        "alerts_today": get_today_alerts(),
    }
```

---

## 10. 成本估算

### 10.1 月度运维成本

| 项目 | 月费 | 说明 |
|------|------|------|
| 电费 | ~150元 | 9900X3D + 5070 TDP ~300W，7x24运行 |
| Tushare Pro | ~167元 | 8000积分年费 ~2000元/12 |
| 钉钉机器人 | 0元 | 免费 |
| Tailscale | 0元 | 个人免费版 |
| 外置硬盘（分摊） | ~15元 | 2TB ~500元/3年 |
| NVMe磨损（分摊） | ~30元 | 2TB ~1200元/3年，日写入~50GB |
| **总计** | **~360元/月** | |

### 10.2 一次性投入

| 项目 | 费用 | 说明 |
|------|------|------|
| UPS不间断电源 | 500-1000元 | 保护断电场景，延迟10-15分钟安全关机 |
| 外置备份硬盘 | 500元 | 2TB便携硬盘 |
| 软件 | 0元 | 全部开源 |

---

## 11. 落地计划（按优先级排序）

### Phase A: 紧急加固（1-2天，P0风险消除）

| # | 任务 | 预计时间 | 说明 |
|---|------|---------|------|
| A1 | NSSM注册Celery Worker为Windows Service | 2小时 | 崩溃自动重启，消除最大单点故障 |
| A2 | 备份脚本 + Task Scheduler注册 | 3小时 | `pg_dump` 每日02:00 + 大小验证 |
| A3 | 日志轮转配置 | 1小时 | RotatingFileHandler防磁盘爆满 |
| A4 | 调度入口交易日门卫 | 1小时 | `should_run_today()` 统一检查 |

### Phase B: 监控体系（2-3天）

| # | 任务 | 预计时间 | 说明 |
|---|------|---------|------|
| B1 | `system_monitor.py` 系统指标采集 | 3小时 | psutil + PG连接 + Redis |
| B2 | 告警去重与分级逻辑 | 2小时 | 1小时去重 + P0/P1/P2分发 |
| B3 | 备份验证脚本 | 2小时 | 每周恢复到临时库验证 |
| B4 | `daily_pipeline.py` 重试编排 | 3小时 | 失败重试 + 最终失败策略 |

### Phase C: 生产加固（3-5天）

| # | 任务 | 预计时间 | 说明 |
|---|------|---------|------|
| C1 | structlog统一日志改造 | 4小时 | 替换现有logging配置 |
| C2 | 审计日志表 + 关键操作追踪 | 3小时 | DDL + 参数变更审计 |
| C3 | miniQMT自动重连 | 3小时 | 退避重试 + P0告警 |
| C4 | 开机自检脚本 | 2小时 | 系统重启后自动验证所有服务 |
| C5 | Tailscale远程访问 | 1小时 | 安装 + FastAPI状态API |
| C6 | keyring凭证迁移 | 1小时 | .env敏感字段→Windows Credential Manager |
| C7 | 灾备SOP文档化 + 演练 | 2小时 | 打印纸质SOP + 执行一次L3恢复演练 |

### Phase D: 前端监控面板（随React前端开发）

| # | 任务 | 预计时间 | 说明 |
|---|------|---------|------|
| D1 | 监控Dashboard页面 | 8小时 | health_checks表可视化 |
| D2 | PT日报自动生成页面 | 4小时 | NAV曲线 + 9项毕业指标 |

**总工时估算**: Phase A-C约30小时（4-5个工作日），Phase D随前端进度。

---

## 12. 参考文献

### 开源项目与架构
- [Qlib - 微软AI量化投资平台 (DeepWiki)](https://deepwiki.com/microsoft/qlib)
- [Qlib GitHub](https://github.com/microsoft/qlib)
- [vnpy/VeighNa 量化交易平台](https://github.com/vnpy/vnpy/blob/master/README_ENG.md)
- [QuantConnect LEAN引擎](https://github.com/QuantConnect/Lean)
- [Quant Trading Systems: Architecture & Infrastructure](https://mbrenndoerfer.com/writing/quant-trading-system-architecture-infrastructure)

### Windows运维
- [NSSM - Non-Sucking Service Manager](https://nssm.cc/)
- [Running Celery on Windows](https://celery.school/celery-on-windows)
- [Running Celery 5 on Windows - Simple Thread](https://www.simplethread.com/running-celery-5-on-windows/)
- [如何选择量化交易服务器 - 博客园](https://www.cnblogs.com/sljsz/p/17649740.html)

### 调度方案
- [APScheduler vs Celery Beat 对比 (Leapcell)](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-vs-celery-beat)
- [Celery Beat Periodic Tasks 文档](https://docs.celeryq.dev/en/main/userguide/periodic-tasks.html)
- [Celery Task Resilience: Advanced Strategies (GitGuardian)](https://blog.gitguardian.com/celery-tasks-retries-errors/)

### 数据库备份
- [TimescaleDB备份方案 (OneUptime)](https://oneuptime.com/blog/post/2026-01-27-timescaledb-backup/view)
- [pgBackRest用于PG和TimescaleDB (Severalnines)](https://severalnines.com/blog/how-use-pgbackrest-backup-postgresql-and-timescaledb/)
- [PostgreSQL 2025最佳实践 (Instaclustr)](https://www.instaclustr.com/education/postgresql/top-10-postgresql-best-practices-for-2025/)
- [PG备份与灾难恢复 (Tiger Data)](https://www.tigerdata.com/blog/database-backups-and-disaster-recovery-in-postgresql-your-questions-answered)

### 监控方案
- [Prometheus替代方案 2026 (Dash0)](https://www.dash0.com/comparisons/best-prometheus-alternatives)
- [开源监控工具Top10 (OpenObserve)](https://openobserve.ai/blog/top-10-open-source-monitoring-tools/)

### 日志管理
- [structlog - Python结构化日志](https://www.structlog.org/)
- [structlog生产最佳实践 (Better Stack)](https://betterstack.com/community/guides/logging/structlog/)
- [高性能Python日志优化 (Johal.in)](https://johal.in/optimizing-python-logging-for-high-performance-applications-with-structlog-and-json-13/)

### Celery生产经验
- [Celery生产两年Bug修复 (SquadStack)](https://medium.com/squad-engineering/two-years-with-celery-in-production-bug-fix-edition-22238669601d)
- [Celery生产三年修复 (Ayush Shanker)](https://ayushshanker.com/posts/celery-in-production-bugfixes/)
- [Celery Windows Issue #5738](https://github.com/celery/celery/issues/5738)

---

## 附录A: 关键决策总结

| 决策 | 选择 | 理由 |
|------|------|------|
| 主调度器 | Task Scheduler | OS级可靠性、开机补执行、Windows原生 |
| 辅助调度 | APScheduler(嵌入FastAPI) | 高频健康检查，无外部依赖 |
| Celery Beat | **不用** | Windows不稳定，调度权交给Task Scheduler |
| Celery Worker池 | solo/threads | Windows不支持prefork，solo做计算、threads做I/O |
| 进程管理 | NSSM | 崩溃自动重启，Windows Service封装 |
| 监控 | 自建(PG表+钉钉) | 单机场景，Prometheus过度工程 |
| 日志 | structlog JSON | 结构化+轮转+低CPU开销 |
| 备份 | pg_dump全量+Parquet | 简单可靠，不搞增量复杂度 |
| 凭证管理 | keyring + .env | 敏感字段走OS凭证管理器 |
| 远程访问 | Tailscale + 钉钉 | 免费、安全、零配置 |

## 附录B: QuantMind完整调度时序（设计态）

```
每日时序:
  02:00  backup_pipeline      → pg_dump + 清理旧备份
  06:00  log_rotate            → 日志轮转清理
  08:30  execution_pipeline    → 读指令 → 预检 → 确认执行
  09:30  [miniQMT执行]         → 开盘执行
  16:30  daily_pipeline        → 数据拉取 → 因子计算 → 信号生成
  17:30  [钉钉推送调仓明细]
  20:00  pt_watchdog            → 心跳检测

每5分钟（APScheduler）:
  system_health_check → PG/Redis/磁盘/内存/进程

每周日 03:00:
  verify_backup       → 恢复到临时库验证
  parquet_export      → 关键表Parquet快照

每月1号:
  monthly_backup      → 永久归档
  calendar_verify     → 交易日历完整性检查
```
