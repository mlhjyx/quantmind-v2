import psycopg2

c = psycopg2.connect(dbname='quantmind_v2', user='xin', password='quantmind', host='localhost')
cur = c.cursor()
cur.execute("SELECT pid, state, query_start, left(query, 80) FROM pg_stat_activity WHERE datname = 'quantmind_v2' ORDER BY query_start")
for r in cur.fetchall():
    print(r)
print("---")
cur.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
print(f"blocked locks: {cur.fetchone()[0]}")
c.close()
