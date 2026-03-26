#!/usr/bin/env python3
"""Create factor_lifecycle table and insert initial data for v1.1 active factors.

Sprint 1.5 - Factor Lifecycle Management Infrastructure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn


def main():
    conn = _get_sync_conn()
    conn.autocommit = True
    cur = conn.cursor()

    # --- Create table ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS factor_lifecycle (
            factor_name VARCHAR(50) PRIMARY KEY,
            status VARCHAR(20) NOT NULL DEFAULT 'candidate'
                CHECK (status IN ('candidate', 'active', 'monitoring', 'warning', 'retired')),
            entry_date DATE,
            entry_ic DECIMAL(8,4),
            entry_t_stat DECIMAL(8,4),
            rolling_ic_12m DECIMAL(8,4),
            rolling_ic_updated DATE,
            warning_date DATE,
            retired_date DATE,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("Table factor_lifecycle created (or already exists).")

    # --- Comments ---
    comments = [
        ("TABLE factor_lifecycle", "Factor lifecycle management - Sprint 1.5"),
        ("COLUMN factor_lifecycle.status", "Status: candidate/active/monitoring/warning/retired"),
        ("COLUMN factor_lifecycle.entry_ic", "IC at entry (Spearman rank correlation)"),
        ("COLUMN factor_lifecycle.entry_t_stat", "IC t-statistic at entry"),
        ("COLUMN factor_lifecycle.rolling_ic_12m", "Rolling 12-month average IC"),
        ("COLUMN factor_lifecycle.rolling_ic_updated", "Last update date of rolling IC"),
        ("COLUMN factor_lifecycle.warning_date", "Date entered warning status"),
        ("COLUMN factor_lifecycle.retired_date", "Date retired"),
    ]
    for target, comment in comments:
        cur.execute(f"COMMENT ON {target} IS %s", (comment,))

    # --- Insert 5 Active factors (v1.1 baseline) ---
    factors = [
        ("turnover_mean_20", "active", "2026-03-20", -0.0643, -7.31,
         "v1.1 Active, IR=-0.73, 7/7 year consistent"),
        ("volatility_20", "active", "2026-03-20", -0.0690, -6.37,
         "v1.1 Active, |IC| largest, 7/7 year consistent"),
        ("reversal_20", "active", "2026-03-20", 0.0386, 3.50,
         "v1.1 Active, 6/7 year consistent"),
        ("amihud_20", "active", "2026-03-20", 0.0215, 2.69,
         "v1.1 Active, liquidity factor"),
        ("bp_ratio", "active", "2026-03-20", 0.0523, 6.02,
         "v1.1 Active, strongest value factor"),
    ]

    cur.executemany("""
        INSERT INTO factor_lifecycle (factor_name, status, entry_date, entry_ic, entry_t_stat, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (factor_name) DO UPDATE SET
            status = EXCLUDED.status,
            entry_date = EXCLUDED.entry_date,
            entry_ic = EXCLUDED.entry_ic,
            entry_t_stat = EXCLUDED.entry_t_stat,
            notes = EXCLUDED.notes,
            updated_at = CURRENT_TIMESTAMP
    """, factors)
    print(f"Inserted/updated {len(factors)} active factors.")

    # --- Verify ---
    cur.execute("""
        SELECT factor_name, status, entry_ic, entry_t_stat
        FROM factor_lifecycle ORDER BY factor_name
    """)
    print("\nCurrent factor_lifecycle contents:")
    print(f"  {'Factor':<25s} {'Status':<10s} {'IC':>8s} {'t-stat':>8s}")
    print(f"  {'-'*25} {'-'*10} {'-'*8} {'-'*8}")
    for row in cur.fetchall():
        print(f"  {row[0]:<25s} {row[1]:<10s} {row[2]:+8.4f} {row[3]:+8.2f}")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
