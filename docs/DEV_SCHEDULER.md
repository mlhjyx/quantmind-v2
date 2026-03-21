# QuantMind V2 — 调度与运维详细开发文档

> 文档级别：实现级（供 Claude Code 执行）
> 创建日期：2026-03-20
> 关联文档：DEV_AI_EVOLUTION.md, DEV_FOREX.md, DEV_NOTIFICATIONS.md

---

## 一、调度框架

Celery Beat(定时) + Celery Worker(执行) + Redis(Broker)。统一框架，不引入APScheduler/crontab。

---

## 二、A股每日调度时序（北京时间）

### 盘前（06:00-09:30）

| 时间 | 任务ID | 名称 | 依赖 | 超时 | 失败级别 |
|------|--------|------|------|------|---------|
| 06:00 | T1 | 数据更新(akshare/tushare→klines) | — | 30min | P0 |
| 06:35 | T2 | 数据质量检查(>3000股/无NULL/价格范围/复权一致性) | T1 | 10min | P1+暂停后续 |
| 06:50 | T3 | Universe构建(8层过滤) | T2 | 5min | P1 |
| 07:00 | T4 | 因子计算(34+因子×universe) | T3 | 15min | P1 |
| 07:20 | T5 | 因子体检(周一,近60日IC/IR/衰退) | T4 | 10min | P2 |
| 07:35 | T6 | ML预测(LightGBM,启用时) | T4 | 5min | P1 |
| 07:45 | T7 | 信号生成(IC加权或ML→Top-N+风控) | T4/T6 | 5min | P0 |
| 08:00 | T8 | 调仓决策(当前vs新信号→指令) | T7 | 5min | P0 |
| 08:30 | T9 | 盘前报告→通知推送 | T8 | 5min | P2 |

关键路径: T1→T2→T3→T4→T7→T8 = 75min, 07:15前完成信号

### 盘中（09:30-15:00）

| 时间 | 任务ID | 名称 |
|------|--------|------|
| 09:30 | T10 | 开盘执行(miniQMT TWAP/VWAP) |
| 11:30 | T11 | 午间成交检查(可选) |
| 15:00 | T12 | 收盘确认(订单状态/成交价/滑点) |

### 盘后（15:00-18:00）

| 时间 | 任务ID | 名称 | 依赖 |
|------|--------|------|------|
| 15:30 | T13 | 盘后数据更新(完整行情+持仓市值) | — |
| 16:00 | T14 | 绩效计算(收益/Sharpe/MDD/实盘对比) | T13 |
| 16:30 | T15 | 日报生成→通知推送 | T14 |

### 夜间

| 时间 | 任务ID | 名称 | 频率 |
|------|--------|------|------|
| 22:00 | T16 | AI闭环Pipeline | 每周日 |
| 03:00 | T17 | 数据库维护(VACUUM/清理/备份) | 每周日 |

---

## 三、外汇每日调度时序（UTC）

### D1 Bar Close后（22:00 UTC = 北京06:00）

| 时间UTC | 任务ID | 名称 | 依赖 | 超时 |
|---------|--------|------|------|------|
| 22:05 | FX1 | MT5数据增量(D1/H4/H1→forex_bars) | — | 15min |
| 22:20 | FX2 | 经济日历更新(→forex_events) | — | 5min |
| 22:25 | FX3 | Swap费率记录(→forex_swap_rates) | — | 3min |
| 22:30 | FX4 | 数据质量检查 | FX1 | 5min |
| 22:35 | FX5 | 宏观因子更新(周一或数据发布后) | — | 5min |
| 22:40 | FX6 | 技术因子计算(14品种×15因子) | FX4 | 5min |
| 22:45 | FX7 | ML预测(LightGBM→confidence) | FX6 | 5min |
| 22:50 | FX8 | 信号生成(宏观+技术+ML合成) | FX5+FX6+FX7 | 5min |
| 22:55 | FX9 | 持仓管理(出场/移动止损/新仓风控) | FX8 | 5min |
| 23:00 | FX10 | 交易执行(MT5 Adapter) | FX9 | 10min |
| 23:10 | FX11 | 日报生成→通知推送 | FX10 | 5min |

关键路径: FX1→FX4→FX6→FX8→FX9→FX10 = 55min

### 持续运行

| 间隔 | 任务 | 方式 |
|------|------|------|
| 30秒 | MT5心跳 | 独立asyncio循环 |
| 60秒 | 持仓同步(MT5→PG) | 独立asyncio循环 |
| 3600秒 | 经济事件前风控检查 | 独立asyncio循环 |

### 周特殊

| 时间 | 任务 |
|------|------|
| 周五 08:00 UTC | 周五减仓检查+执行 |
| 周一 01:00 UTC | 品种相关性矩阵更新 |
| 周一 01:10 UTC | MT5合约规格验证 |

---

## 四、Celery Beat配置

完整crontab配置见对话记录(§5)。关键配置:

队列设计(8个): astock_data / astock_compute / astock_trade / forex_data / forex_compute / forex_trade / ai_pipeline / system

Worker分配(Phase 0单机):
- Worker 1: data队列(IO密集)
- Worker 2: compute队列(CPU密集)
- Worker 3: trade队列(低延迟优先)
- Worker 4: ai_pipeline(长任务独立)

---

## 五、任务依赖管理

通过Redis状态键实现: `task_status:{date}:{task_name}` = success/failed/running, TTL 24h

前置任务检查: 全部success→执行, 任一failed→跳过+告警, running→等待(最多30min), 不存在→告警

---

## 六、交易日历

A股: 周一至周五(排除中国法定节假日), 数据源akshare交易日历
外汇: 周一至周五(排除圣诞12/25和元旦1/1)
AI/系统: 不受交易日限制

---

## 七、异常处理与重试

| 任务类型 | 最大重试 | 间隔 | 失败处理 |
|---------|---------|------|---------|
| 数据拉取 | 3次 | 1/5/15min | P0告警 |
| 计算 | 2次 | 30s/2min | P1告警 |
| 交易执行 | 2次 | 10s/30s | P0告警 |
| 报告 | 1次 | 1min | P2告警 |

超时后处理: 数据→用前日数据+P0; 因子→用缓存+P1; 交易→取消+P0

---

## 八、监控

每日完成度: 任务总数/成功/失败, 关键路径耗时
延迟检测: 超预期+10min黄色, +30min红色
前端展示: 系统设置→调度Tab(任务链时间线+历史执行记录)

---

## 九、数据库表

```sql
CREATE TABLE scheduler_task_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name       VARCHAR(50) NOT NULL,
    market          VARCHAR(10),
    schedule_time   TIMESTAMPTZ NOT NULL,
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    duration_sec    INT,
    status          VARCHAR(10) NOT NULL,
    error_message   TEXT,
    retry_count     INT DEFAULT 0,
    result_json     JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_scheduler_log_date ON scheduler_task_log(schedule_time DESC);
CREATE INDEX idx_scheduler_log_status ON scheduler_task_log(status, market);
```

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. A股调度时序重大修正（覆盖 §二 全部内容）

原方案（T+1日凌晨06:00计算）**不可行** — Tushare/AKShare数据在T日16:00-17:00才完整可用。

**修正方案: T日盘后计算，T+1日盘前确认执行**

#### T日盘后（15:00-18:00）— 核心计算全部在这里完成

| 时间 | 任务ID | 名称 | 依赖 | 超时 | 失败级别 |
|------|--------|------|------|------|---------|
| 16:00 | T0 | **全链路健康预检** | — | 2min | P0(任一失败暂停全链路) |
| 16:30 | T1 | 数据更新(tushare/akshare→klines等) | T0 | 30min | P0 |
| 17:00 | T2 | 数据质量检查 | T1 | 10min | P1+暂停后续 |
| 17:05 | T3 | Universe构建(8层过滤) | T2 | 5min | P1 |
| 17:10 | T4 | 因子计算(全因子×universe) | T3 | 15min | P1 |
| 17:25 | T5 | 因子体检(周一,近60日IC/IR/衰退) | T4 | 10min | P2 |
| 17:35 | T6 | ML预测(LightGBM,启用时) | T4 | 5min | P1 |
| 17:40 | T7 | 信号生成(等权/IC加权→Top-N+风控) | T4/T6 | 5min | P0 |
| 17:45 | T8 | 调仓决策(当前vs新信号→指令存库) | T7 | 5min | P0 |
| 17:50 | T9 | 盘后报告→通知推送(含明日调仓明细) | T8 | 5min | P2 |

关键路径: T0→T1→T2→T3→T4→T7→T8 = 约105min，18:00前完成

#### T+1日盘前（08:00-09:30）— 仅确认和执行

| 时间 | 任务ID | 名称 | 依赖 |
|------|--------|------|------|
| 08:30 | T10 | 读取昨日存库的调仓指令 → 确认无异常 | — |
| 09:30 | T11 | 开盘执行(miniQMT TWAP/VWAP 或 SimBroker) | T10 |
| 11:30 | T12 | 午间成交检查(可选) | T11 |
| 15:00 | T13 | 收盘确认(订单状态/成交价/滑点) | T11 |
| 15:30 | T14 | 盘后数据更新+绩效计算 | T13 |
| 16:00 | 回到T0 | 今日盘后链路开始 | T14 |

#### 夜间（不变）
| 时间 | 任务ID | 名称 | 频率 |
|------|--------|------|------|
| 22:00 | T16 | AI闭环Pipeline | 每周日 |
| 03:00 | T17 | 数据库维护(VACUUM/清理/备份) | 每周日 |

### P2. 全链路健康预检（新任务T0，每日调度第一步）

T0预检内容（任何一项失败 → P0告警 + 暂停当日全链路）：
```python
async def health_precheck() -> dict[str, bool]:
    checks = {
        'postgresql': await check_pg_connection(),
        'redis': await check_redis_connection(),
        'data_freshness': await check_latest_kline_date() == last_trading_day(),
        'factor_nan': await check_factor_nan_sample(n=10),  # 抽样10只
        'disk_space': get_disk_free_gb() > 10,
        'celery_workers': await check_celery_workers_online(),
    }
    # Phase 1 追加:
    # 'miniQMT': check_qmt_connection() if EXECUTION_MODE == 'live'
    # Phase 2 追加:
    # 'mt5': check_mt5_connection() if forex_enabled
    
    all_pass = all(checks.values())
    if not all_pass:
        failed = [k for k, v in checks.items() if not v]
        await notification_service.send(level='P0', title=f'健康预检失败: {failed}')
    return checks
```
预检结果写入`health_checks`表，并与调度链路绑定。

### P3. 数据库备份（补充 §九 运维）

- 每日 `pg_dump` 到外部存储（外部硬盘或NAS）
- 关键表（klines_daily, factor_values）额外导出Parquet作为二级备份
- `scripts/verify_backup.sh` 定期验证备份可恢复
- TimescaleDB hypertable备份需加 `--format=directory`

### P4. 日志管理

- 开发阶段用DEBUG，Paper Trading及之后用**INFO级别**
- 因子计算详细日志走单独文件（`logs/factor_calc.log`），定期归档
- 加 `LOG_MAX_FILES` 配置，限制总日志大小

### P5. 优雅停机与状态恢复

- 因子计算用**事务写入**: 要么全部因子写成功，要么全部回滚
- 或每个因子独立写入 + **完成标记**，重启后检查标记只重算未完成的
- Celery task加 `acks_late=True`，crash后自动重试
