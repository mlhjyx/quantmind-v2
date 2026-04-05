---
name: quantmind-db-safety
description: QuantMind数据库操作安全规则。防止DB锁、OOM、数据丢失。
trigger: ALTER TABLE|DELETE FROM|DROP|TRUNCATE|大批量|写入|migrate
---

# QuantMind DB Safety Skill

## ALTER TABLE前必须检查

```sql
SELECT pid, state, left(query, 80), now() - query_start AS duration
FROM pg_stat_activity
WHERE datname = 'quantmind_v2' AND state != 'idle'
AND pid != pg_backend_pid();
```

如果有活跃连接在读目标表 -> 等它完成或先停FastAPI服务。
2026-04-05教训: 7个ALTER TABLE级联阻塞，18个blocked locks。

## 并发控制（铁律9）
- 重数据任务最多2个Python进程并发
- 每进程估计3-4GB（加载7M行price_data）
- PG shared_buffers=2GB是固定开销
- 违反 -> PG OOM崩溃（Windows error 1455）

## 大批量写入
- 用psycopg2.extras.execute_values，每批5000行
- 不用逐行INSERT
- 大事务每10万行commit一次
- ON CONFLICT DO UPDATE处理幂等性

## 备份
- ALTER TABLE或DROP前先确认数据可恢复
- pg_dump路径: D:\pgsql\bin\pg_dump.exe
- 数据目录: D:\pgdata16

## 连接参数
- dbname=quantmind_v2, user=xin, password=quantmind, host=localhost
- sync psycopg2（不用asyncpg）
