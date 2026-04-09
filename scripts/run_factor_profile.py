#!/usr/bin/env python3
"""Step 6-F Part 5: 跑 factor_profiler 全量画像.

使用 backend/engines/factor_profiler.profile_all_factors() (programmatic API).

注意: factor_profiler 依赖 cache/*.parquet (precompute_cache 产出),
该缓存当前覆盖 2020-07-01 ~ 2026-06-30 (~5.5 年, 非 12 年).
如需 12 年画像, 需要先修改 scripts/precompute_cache.py 的 START_DATE 重新生成.

输出:
  factor_profile 表 (DB) — 由 _save_profile() 自动写入
  cache/baseline/factor_profiles_summary.json — 汇总报告

用法:
    python scripts/run_factor_profile.py
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logging.disable(logging.DEBUG)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import structlog

structlog.configure(
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.getLogger().setLevel(logging.INFO)

from engines.factor_profiler import profile_all_factors  # noqa: E402

BASELINE_DIR = Path(__file__).resolve().parent.parent / "cache" / "baseline"


def main():
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)

    print("[Profile] 启动 factor_profiler...")
    print("  注意: cache 范围 2020-07 ~ 2026-06 (~5.5 年), 非 12 年")
    print("  如需 12 年画像, 修改 scripts/precompute_cache.py START_DATE=2014-01-01 重建")

    t0 = time.time()
    profiles = profile_all_factors()
    elapsed = time.time() - t0
    print(f"\n[Done] 总耗时: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"[Done] 处理因子数: {len(profiles)}")

    # 汇总
    valid = [p for p in profiles if "error" not in p]
    errored = [p for p in profiles if "error" in p]

    keep_count = sum(1 for p in valid if p.get("keep_recommendation", False))
    drop_count = sum(1 for p in valid if not p.get("keep_recommendation", True))
    fmp_count = sum(1 for p in valid if p.get("fmp_candidate", False))
    redundant_count = sum(1 for p in valid if p.get("redundant_with"))

    template_dist = {}
    for p in valid:
        t = p.get("recommended_template")
        if t is not None:
            template_dist[t] = template_dist.get(t, 0) + 1

    summary = {
        "meta": {
            "total_factors": len(profiles),
            "valid": len(valid),
            "errored": len(errored),
            "elapsed_sec": round(elapsed, 0),
            "cache_range": "2020-07-01 to 2026-06-30 (~5.5 years)",
            "note": "非 12 年画像 — 受 precompute_cache START_DATE 限制",
        },
        "keep_distribution": {
            "keep": keep_count,
            "drop": drop_count,
        },
        "fmp_candidates": fmp_count,
        "redundant_pairs": redundant_count,
        "template_distribution": template_dist,
        "errors": [
            {"factor": p.get("factor_name", "?"), "error": p.get("error")}
            for p in errored
        ],
    }

    out_path = BASELINE_DIR / "factor_profiles_summary.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    print(f"\n[Save] {out_path}")

    print("\n=== Summary ===")
    print(f"  Total: {len(profiles)}")
    print(f"  Valid: {len(valid)}, Errored: {len(errored)}")
    print(f"  Keep: {keep_count}, Drop: {drop_count}")
    print(f"  FMP candidates: {fmp_count}")
    print(f"  Redundant pairs: {redundant_count}")
    print(f"  Template distribution: {template_dist}")


if __name__ == "__main__":
    main()
