"""清理PG锁：终止所有卡住的ALTER TABLE和idle in transaction连接。"""
import psycopg2

c = psycopg2.connect(dbname='quantmind_v2', user='xin', password='quantmind', host='localhost')
c.autocommit = True
cur = c.cursor()

# 终止所有ALTER TABLE卡住的连接
cur.execute("""
    SELECT pid, query_start, left(query, 60)
    FROM pg_stat_activity
    WHERE datname = 'quantmind_v2'
    AND query LIKE 'ALTER TABLE%'
    AND pid != pg_backend_pid()
""")
alter_pids = cur.fetchall()
print(f"卡住的ALTER TABLE: {len(alter_pids)}个")
for pid, ts, q in alter_pids:
    print(f"  终止 PID {pid} ({ts}): {q}")
    cur.execute("SELECT pg_terminate_backend(%s)", (pid,))

# 终止idle in transaction > 1小时的
cur.execute("""
    SELECT pid, query_start, left(query, 60)
    FROM pg_stat_activity
    WHERE datname = 'quantmind_v2'
    AND state = 'idle in transaction'
    AND query_start < NOW() - INTERVAL '1 hour'
    AND pid != pg_backend_pid()
""")
idle_pids = cur.fetchall()
print(f"\n长时间idle in transaction: {len(idle_pids)}个")
for pid, ts, q in idle_pids:
    print(f"  终止 PID {pid} ({ts}): {q}")
    cur.execute("SELECT pg_terminate_backend(%s)", (pid,))

# 也终止profiler的旧读取
cur.execute("""
    SELECT pid, query_start, left(query, 60)
    FROM pg_stat_activity
    WHERE datname = 'quantmind_v2'
    AND query LIKE '%industry_sw1%'
    AND state = 'active'
    AND query_start < NOW() - INTERVAL '30 minutes'
    AND pid != pg_backend_pid()
""")
old_pids = cur.fetchall()
print(f"\n旧profiler查询: {len(old_pids)}个")
for pid, ts, q in old_pids:
    print(f"  终止 PID {pid} ({ts}): {q}")
    cur.execute("SELECT pg_terminate_backend(%s)", (pid,))

# 验证
cur.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
print(f"\n清理后blocked locks: {cur.fetchone()[0]}")

c.close()
print("Done")
