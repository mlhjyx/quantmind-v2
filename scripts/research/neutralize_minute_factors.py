"""批量中性化10个minute因子 — 逐因子逐年执行, 避免OOM。

DEPRECATED (P2-1, DATA_SYSTEM_V1 2026-04-17): 改用 DataOrchestrator:
    from app.services.data_orchestrator import DataOrchestrator
    orch = DataOrchestrator('2021-01-01', '2025-12-31')
    orch.neutralize_factors(['high_freq_volatility_20', ...], incremental=True)

或直接跑新统一批量脚本:
    python scripts/data/neutralize_minute_batch.py

本脚本保留为兼容, 不再被 pipeline 引用.
"""
import sys
import time

sys.stdout.reconfigure(line_buffering=True)
sys.path.append(str(__import__('pathlib').Path(__file__).resolve().parents[2] / "backend"))

from engines.fast_neutralize import fast_neutralize_batch

FACTORS = [
    'high_freq_volatility_20', 'volume_concentration_20', 'volume_autocorr_20',
    'smart_money_ratio_20', 'opening_volume_share_20', 'closing_trend_strength_20',
    'vwap_deviation_20', 'order_flow_imbalance_20', 'intraday_momentum_20',
    'volume_price_divergence_20',
]
YEARS = [(2021, 2021), (2022, 2022), (2023, 2023), (2024, 2024), (2025, 2025)]

grand_total = 0
t_all = time.time()
for i, f in enumerate(FACTORS):
    for y_start, y_end in YEARS:
        sd, ed = f"{y_start}-01-01", f"{y_end}-12-31"
        print(f"[{i+1}/10] {f} ({y_start})...", end="", flush=True)
        t0 = time.time()
        n = fast_neutralize_batch([f], sd, ed, update_db=True, write_parquet=False)
        print(f" {n:,} rows, {time.time()-t0:.0f}s", flush=True)
        grand_total += n

elapsed = time.time() - t_all
print(f"\nTotal neutralized: {grand_total:,} rows in {elapsed/60:.1f} min")
