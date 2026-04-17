"""P0-5: 通过 DataOrchestrator 中性化 10 个 minute 因子.

验收 (DATA_SYSTEM_V1 §5.2):
- 总耗时 < 10 分钟
- 10 因子 neutral_value 覆盖率 ≥ 95%
- 原 27 测试 (fast_neutralize + FactorCache) 全 PASS

用法:
    cd D:/quantmind-v2/backend && python ../scripts/data/neutralize_minute_batch.py
或
    cd D:/quantmind-v2 && PYTHONPATH=backend python scripts/data/neutralize_minute_batch.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# 确保 app 可导入
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("p0_neutralize_minute")

# 10 minute factors (from backend/engines/minute_feature_engine.py MINUTE_FEATURES)
MINUTE_FACTORS = [
    "high_freq_volatility_20",
    "volume_concentration_20",
    "volume_autocorr_20",
    "smart_money_ratio_20",
    "opening_volume_share_20",
    "closing_trend_strength_20",
    "vwap_deviation_20",
    "order_flow_imbalance_20",
    "intraday_momentum_20",
    "volume_price_divergence_20",
]

# 日期范围: minute_bars 5年 (2021-2025)
START_DATE = "2021-01-01"
END_DATE = "2025-12-31"


def precheck(orch, factors):
    """确认每个因子都有 raw_value."""
    missing = []
    for f in factors:
        cov = orch._checkpoint.count_neutral_coverage(f)
        logger.info(
            f"  precheck {f:<38s} raw={cov['has_raw']:>10,} "
            f"neutral={cov['has_neutral']:>10,} (coverage={cov['coverage']:.2%})"
        )
        if cov["has_raw"] == 0:
            missing.append(f)
    if missing:
        logger.error(f"[FAIL] 以下因子无 raw_value, 先跑 compute_minute_features.py: {missing}")
        sys.exit(2)


def main():
    from app.services.data_orchestrator import DataOrchestrator

    t_all = time.time()
    logger.info(f"[P0-5] 10 minute factor neutralization  {START_DATE}..{END_DATE}")
    logger.info(f"  factors: {MINUTE_FACTORS}")

    orch = DataOrchestrator(START_DATE, END_DATE)
    precheck(orch, MINUTE_FACTORS)

    # 执行 (D2 严格串行, 共享 SharedDataPool)
    logger.info("[build] 开始中性化 ...")
    result = orch.neutralize_factors(
        MINUTE_FACTORS, incremental=True, validate=True,
    )
    logger.info("[build done]")
    print(result.summary())

    # 验收
    logger.info("[verify] 覆盖率检查 ...")
    failures = []
    quality_summary: dict = {}
    for f in MINUTE_FACTORS:
        cov = orch._validator.reconcile_factor_coverage(f, threshold=0.95)
        val = orch._validator.validate_neutralized(f)
        quality_summary[f] = {"coverage": cov, "neutral_quality": val}
        logger.info(
            f"  {f:<38s} coverage_ratio={cov['ratio']:.2%} overall={cov['overall']} "
            f"neutral_quality={val['overall']}"
        )
        if cov["overall"] == "FAIL":
            failures.append(f)

    # 刷新 Parquet 缓存 (neutral_value)
    logger.info("[cache] 刷新 FactorCache neutral_value Parquet ...")
    cache_stats = {}
    for f in MINUTE_FACTORS:
        try:
            n = orch._cache.refresh(f, "neutral_value", orch._conn)
            cache_stats[f] = {"refreshed_rows": n}
        except Exception as e:
            logger.warning(f"  cache refresh {f}: {e}")
            cache_stats[f] = {"error": str(e)}

    elapsed = time.time() - t_all

    # 结果 JSON
    report = {
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "factors": MINUTE_FACTORS,
        "total_elapsed_sec": round(elapsed, 1),
        "pipeline": {k: vars(v) for k, v in result.stages.items()},
        "quality": quality_summary,
        "cache": cache_stats,
        "failures": failures,
    }
    report_dir = REPO_ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"p0_neutralize_minute_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info(f"[report] {report_path}")

    logger.info(f"[P0-5] 总耗时 {elapsed/60:.2f} min")
    if failures:
        logger.error(f"[FAIL] 覆盖率不达标: {failures}")
        sys.exit(3)
    if elapsed > 600:
        logger.warning(f"[WARN] 超过 10min 目标 ({elapsed/60:.2f} min > 10 min)")

    logger.info("[P0-5] ✅ 验收通过")


if __name__ == "__main__":
    main()
