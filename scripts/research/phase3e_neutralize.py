"""Phase 3E-II Track 2.1: Neutralize 17 PASS microstructure factors.

Uses fast_neutralize_batch with date range 2019-01-01 ~ 2026-04-13.
"""
import sys
import time

sys.path.insert(0, "backend")

from engines.fast_neutralize import fast_neutralize_batch

FACTORS = [
    "intraday_skewness_20", "intraday_kurtosis_20", "high_freq_volatility_20",
    "updown_vol_ratio_20", "max_intraday_drawdown_20", "volume_concentration_20",
    "amihud_intraday_20", "volume_autocorr_20", "smart_money_ratio_20",
    "volume_return_corr_20", "open_drive_20", "close_drive_20",
    "morning_afternoon_ratio_20", "variance_ratio_20", "price_path_efficiency_20",
    "autocorr_5min_20", "weighted_price_contribution_20",
]

# Batch in groups of 3 (memory-friendly)
BATCH_SIZE = 3
t0 = time.time()

for i in range(0, len(FACTORS), BATCH_SIZE):
    batch = FACTORS[i:i + BATCH_SIZE]
    print(f"\n=== Batch {i // BATCH_SIZE + 1}/{(len(FACTORS) + BATCH_SIZE - 1) // BATCH_SIZE}: {batch} ===")
    bt = time.time()
    rows = fast_neutralize_batch(
        factor_names=batch,
        start_date="2019-01-01",
        end_date="2026-04-13",
        update_db=True,
        write_parquet=False,  # Skip parquet, only need DB values for IC
    )
    print(f"  Done: {rows:,} rows in {time.time() - bt:.0f}s")

print(f"\n=== Total: {time.time() - t0:.0f}s for {len(FACTORS)} factors ===")
