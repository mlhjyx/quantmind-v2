"""Fix float NaN in factor_values (铁律29).

Uses date-partitioned approach for TimescaleDB partition pruning.
"""
import psycopg2

conn = psycopg2.connect('postgresql://xin:quantmind@localhost:5432/quantmind_v2')
cur = conn.cursor()

# First find which dates have NaN (fast with partition pruning)
cur.execute("""
    SELECT DISTINCT trade_date::text
    FROM factor_values
    WHERE trade_date >= '2020-01-01'
      AND (neutral_value = 'NaN'::float OR raw_value = 'NaN'::float)
    ORDER BY trade_date
""")
dates = [r[0] for r in cur.fetchall()]
print(f"Found NaN on {len(dates)} dates: {dates[:5]}...{dates[-5:]}" if len(dates) > 10 else f"Found NaN on {len(dates)} dates: {dates}")

total_fixed = 0
for d in dates:
    cur.execute("""
        UPDATE factor_values SET neutral_value = NULL
        WHERE trade_date = %s AND neutral_value = 'NaN'::float
    """, (d,))
    n1 = cur.rowcount
    cur.execute("""
        UPDATE factor_values SET raw_value = NULL
        WHERE trade_date = %s AND raw_value = 'NaN'::float
    """, (d,))
    n2 = cur.rowcount
    total_fixed += n1 + n2
    if n1 + n2 > 0:
        print(f"  {d}: {n1} neutral + {n2} raw fixed")

conn.commit()
print(f"\nTotal fixed: {total_fixed} rows")

# Verify
cur.execute("""
    SELECT COUNT(*) FROM factor_values
    WHERE trade_date >= '2020-01-01'
      AND (neutral_value = 'NaN'::float OR raw_value = 'NaN'::float)
""")
remaining = cur.fetchone()[0]
print(f"Remaining NaN (post-2020): {remaining}")
conn.close()
