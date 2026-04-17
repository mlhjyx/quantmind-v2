"""P1-2: 每日数据质量报告 (DATA_SYSTEM_V1 §7.1 / §8.1).

触发: Celery Beat 每日 17:40 (run_daily_quality_report task)
输出: logs/quality_report_{date}.json + StreamBus 告警 (WARN/FAIL)

包含:
- L1 ingest sanity (klines/daily_basic/moneyflow/minute_bars/index_daily)
- L2 factor_raw 质量 (active 因子 NaN/Inf 率)
- L2 factor_neutral 质量
- L3 reconcile (row_counts / date_alignment / factor_coverage)
- Freshness SLA (各 L1 表 lag_days)

可独立跑: python scripts/data_quality_report.py [--date YYYY-MM-DD] [--factors f1,f2,...]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("quality_report")

# 默认监控的 active 因子 (CORE3+dv_ttm + 10 minute)
DEFAULT_FACTORS = [
    "turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm",
    "high_freq_volatility_20", "volume_concentration_20", "volume_autocorr_20",
    "smart_money_ratio_20", "opening_volume_share_20", "closing_trend_strength_20",
    "vwap_deviation_20", "order_flow_imbalance_20", "intraday_momentum_20",
    "volume_price_divergence_20",
]

DEFAULT_L1_ASSETS = [
    "klines_daily", "daily_basic", "moneyflow_daily",
    "minute_bars", "index_daily", "symbols",
]


def broadcast_alert(level: str, report: dict):
    """通过 StreamBus 广播告警 (best-effort, 失败不阻塞)."""
    try:
        from app.core.stream_bus import get_stream_bus

        bus = get_stream_bus()
        event_data = {
            "level": level,  # WARN | FAIL
            "date": report.get("trade_date"),
            "failures": report.get("failures", []),
            "warnings": report.get("warnings", []),
            "overall": report.get("overall"),
        }
        bus.publish_sync("qm:quality:alert", event_data, source="data_quality_report")
        logger.info(f"[alert] StreamBus qm:quality:alert level={level}")
    except Exception as e:  # silent_ok: 告警失败不阻塞报告
        logger.warning(f"[alert] StreamBus 广播失败 (非阻塞): {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="trade_date YYYY-MM-DD, 默认 MAX(klines_daily)")
    parser.add_argument("--factors", type=str, default=None, help="逗号分隔, 默认 14 active")
    parser.add_argument("--output-dir", type=str, default=str(REPO_ROOT / "logs"))
    parser.add_argument("--alert", action="store_true", help="启用 StreamBus 告警广播")
    args = parser.parse_args()

    from app.services.data_orchestrator import DataOrchestrator

    # date 解析
    if args.date:
        trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        trade_date = None  # orch 内部取 MAX(klines_daily)

    factors = DEFAULT_FACTORS
    if args.factors:
        factors = [f.strip() for f in args.factors.split(",") if f.strip()]

    # 使用短期 window (仅最近 30d 用于 validate)
    orch = DataOrchestrator(
        start_date="2021-01-01", end_date="2025-12-31",
    )

    t0 = time.time()
    logger.info(f"[report] trade_date={trade_date or 'auto'} factors={len(factors)}")
    report = orch.run_daily_quality(trade_date=trade_date, factor_names=factors)

    # 补充 freshness 检查
    report["freshness"] = orch.check_freshness(DEFAULT_L1_ASSETS)

    report["elapsed_sec"] = round(time.time() - t0, 1)

    # 写文件
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    td_str = report["trade_date"] if isinstance(report["trade_date"], str) else str(trade_date or "today")
    out_path = out_dir / f"quality_report_{td_str}.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info(f"[report] {out_path} overall={report['overall']}")

    # 告警
    if args.alert and report["overall"] in ("WARN", "FAIL"):
        broadcast_alert(report["overall"], report)

    # 对齐 stdout (供 Celery beat log)
    print(json.dumps(
        {
            "trade_date": report["trade_date"],
            "overall": report["overall"],
            "warnings": report["warnings"],
            "failures": report["failures"],
            "elapsed_sec": report["elapsed_sec"],
            "output": str(out_path),
        },
        indent=2, default=str,
    ))

    # 退出码: FAIL=2, WARN=1, PASS=0
    if report["overall"] == "FAIL":
        sys.exit(2)
    elif report["overall"] == "WARN":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
