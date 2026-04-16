"""Rolling Walk-Forward 月度自动验证 — Sharpe 退化告警 → DingTalk。

Phase 3 自动化 (2026-04-16): 每月 1 号 02:00 由 Task Scheduler 触发。
自动跑 CORE4 当前配置的 5-fold WF, 对比历史基线 Sharpe=0.8659,
如果 OOS Sharpe 显著下降则 DingTalk 告警。

告警规则:
  - OK:   oos_sharpe >= baseline * 0.85   (下降 <15%)
  - WARN: baseline * 0.70 <= oos < baseline * 0.85  (下降 15-30%)
  - ALERT: oos_sharpe < baseline * 0.70   (下降 >30%, DingTalk P1)
  - 负 fold: any fold sharpe < 0          (DingTalk P1)

用法:
    python scripts/rolling_wf.py                 # 正常运行
    python scripts/rolling_wf.py --dry-run        # 不发 DingTalk, 不跑 WF (仅结构检查)
    python scripts/rolling_wf.py --skip-wf        # 跳过 WF, 只检查上次结果
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
CACHE_DIR = PROJECT_ROOT / "cache" / "rolling_wf"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_handlers = [logging.FileHandler(LOG_DIR / "rolling_wf.log", encoding="utf-8")]
import contextlib

with contextlib.suppress(Exception):
    _handlers.insert(0, logging.StreamHandler(sys.stderr))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
    force=True,
)
logger = logging.getLogger("rolling_wf")

# ── 配置 ──────────────────────────────────────────────────
BASELINE_SHARPE = 0.8659  # CORE3+dv_ttm+SN050 WF OOS (2026-04-12)
BASELINE_MDD = -0.1391

CORE_DIRECTIONS = {
    "turnover_mean_20": -1,
    "volatility_20": -1,
    "bp_ratio": +1,
    "dv_ttm": +1,
}
TOP_N = 20
REBALANCE_FREQ = "monthly"
SN_BETA = 0.50

WARN_RATIO = 0.85  # Sharpe 下降 >15% → WARN
ALERT_RATIO = 0.70  # Sharpe 下降 >30% → ALERT


def _load_wf_data():
    """加载 WF 所需的因子/价格/基准数据 (走 Parquet 缓存)。"""

    from data.parquet_cache import BacktestDataCache

    cache = BacktestDataCache()
    factor_df = cache.load_factor_data()
    price_df = cache.load_price_data()
    bench_df = cache.load_benchmark_data()

    logger.info(
        "数据加载: factors=%d行, prices=%d行, bench=%d行",
        len(factor_df),
        len(price_df),
        len(bench_df),
    )
    return factor_df, price_df, bench_df


def _run_wf(factor_df, price_df, bench_df) -> dict:
    """执行 5-fold WF 验证。"""
    from engines.backtest.config import BacktestConfig
    from engines.size_neutral import load_ln_mcap_pivot
    from engines.walk_forward import WalkForwardEngine, WFConfig

    # 与 wf_phase24_validation.py 一致的参数
    wf_config = WFConfig(n_splits=5, train_window=750, gap=5, test_window=250)
    bt_config = BacktestConfig(
        top_n=TOP_N,
        rebalance_freq=REBALANCE_FREQ,
        initial_capital=1_000_000,
    )

    # 因子子集
    cfg_factors = list(CORE_DIRECTIONS.keys())
    cfg_factor_df = factor_df[factor_df["factor_name"].isin(cfg_factors)].copy()

    # Size-neutral
    ln_mcap_pivot = load_ln_mcap_pivot(price_df)

    # 构建 signal function
    from engines.walk_forward import make_equal_weight_signal_func

    signal_func = make_equal_weight_signal_func(
        cfg_factor_df,
        CORE_DIRECTIONS,
        price_df,
        top_n=TOP_N,
        rebalance_freq=REBALANCE_FREQ,
        size_neutral_beta=SN_BETA,
        ln_mcap_pivot=ln_mcap_pivot,
    )

    all_dates = sorted(price_df["trade_date"].unique())
    engine = WalkForwardEngine(wf_config, bt_config)

    logger.info("开始 WF 5-fold (train=750, gap=5, test=250)...")
    t0 = time.time()
    result = engine.run(signal_func, price_df, bench_df, all_dates)
    elapsed = time.time() - t0
    logger.info("WF 完成: %.0fs", elapsed)

    # 提取结果
    fold_data = []
    for fr in result.fold_results:
        fold_data.append(
            {
                "fold": fr.fold_idx,
                "oos_sharpe": round(fr.oos_sharpe, 4),
                "oos_mdd": round(fr.oos_mdd, 4),
                "oos_annual_return": round(fr.oos_annual_return, 4),
                "test_days": fr.test_days,
            }
        )

    oos_sharpes = [f["oos_sharpe"] for f in fold_data]
    chain_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    neg_folds = sum(1 for s in oos_sharpes if s < 0)

    return {
        "chain_sharpe": round(chain_sharpe, 4),
        "neg_folds": neg_folds,
        "folds": fold_data,
        "elapsed_s": round(elapsed, 1),
        "run_date": str(date.today()),
    }


def _classify_result(wf_result: dict) -> dict:
    """分类告警等级。"""
    sharpe = wf_result["chain_sharpe"]
    neg_folds = wf_result["neg_folds"]

    if neg_folds > 0:
        return {
            "level": "P1",
            "label": "NEGATIVE_FOLD",
            "msg": f"WF OOS 有 {neg_folds} 个负 fold! chain_sharpe={sharpe:.4f}",
        }

    if sharpe < BASELINE_SHARPE * ALERT_RATIO:
        return {
            "level": "P1",
            "label": "SHARPE_ALERT",
            "msg": f"WF OOS Sharpe 严重下降: {sharpe:.4f} (基线 {BASELINE_SHARPE}, 下降 {(1 - sharpe / BASELINE_SHARPE) * 100:.0f}%)",
        }

    if sharpe < BASELINE_SHARPE * WARN_RATIO:
        return {
            "level": "WARN",
            "label": "SHARPE_WARN",
            "msg": f"WF OOS Sharpe 轻微下降: {sharpe:.4f} (基线 {BASELINE_SHARPE}, 下降 {(1 - sharpe / BASELINE_SHARPE) * 100:.0f}%)",
        }

    return {
        "level": "OK",
        "label": "STABLE",
        "msg": f"WF OOS Sharpe 稳定: {sharpe:.4f} (基线 {BASELINE_SHARPE})",
    }


def _send_dingtalk(title: str, content: str, level: str = "P1") -> bool:
    """发送 DingTalk 告警。"""
    try:
        from app.config import settings
        from app.services.dispatchers.dingtalk import send_markdown_sync

        webhook = settings.DINGTALK_WEBHOOK_URL
        secret = settings.DINGTALK_SECRET
        if not webhook:
            logger.warning("[DingTalk] webhook 未配置, 跳过")
            return False
        keyword = getattr(settings, "DINGTALK_KEYWORD", "")
        return send_markdown_sync(
            webhook_url=webhook,
            title=f"[{level}] {title}",
            content=content,
            secret=secret,
            keyword=keyword,
        )
    except Exception as e:
        logger.error("[DingTalk] 发送失败: %s", e)
        return False


def run_rolling_wf(dry_run: bool = False, skip_wf: bool = False, force: bool = False) -> dict:
    """执行月度 Rolling WF 验证。

    Task Scheduler 每日 02:00 触发, 但只在每月 1 号真正执行 WF.
    其他日期直接跳过 (除非 --force).
    """
    today = date.today()
    if today.day != 1 and not force and not dry_run:
        logger.info("[Rolling WF] %s 非每月 1 号, 跳过 (用 --force 强制)", today)
        return {"status": "skipped", "reason": "not_1st_of_month"}

    logger.info("=" * 60)
    logger.info("[Rolling WF] 月度策略验证 %s", today)
    logger.info("基线: Sharpe=%.4f, MDD=%.4f", BASELINE_SHARPE, BASELINE_MDD)

    result_file = CACHE_DIR / f"wf_result_{date.today().strftime('%Y%m')}.json"

    if skip_wf and result_file.exists():
        logger.info("--skip-wf: 加载上次结果 %s", result_file)
        with open(result_file) as f:
            wf_result = json.load(f)
    elif dry_run:
        logger.info("[DRY-RUN] 跳过 WF 执行")
        return {"status": "dry_run"}
    else:
        # 加载数据 + 跑 WF
        factor_df, price_df, bench_df = _load_wf_data()
        wf_result = _run_wf(factor_df, price_df, bench_df)

        # 保存结果
        with open(result_file, "w") as f:
            json.dump(wf_result, f, indent=2, ensure_ascii=False)
        logger.info("结果已保存: %s", result_file)

    # 分类
    classification = _classify_result(wf_result)
    logger.info("结论: %s — %s", classification["label"], classification["msg"])

    # 告警
    if classification["level"] in ("P1", "WARN") and not dry_run:
        fold_lines = "\n".join(
            f"  - Fold {f['fold']}: Sharpe={f['oos_sharpe']}, MDD={f['oos_mdd']}"
            for f in wf_result.get("folds", [])
        )
        content = (
            f"### Rolling WF 月度验证 ({date.today()})\n\n"
            f"**{classification['msg']}**\n\n"
            f"配置: CORE3+dv_ttm, Top-{TOP_N}, {REBALANCE_FREQ}, SN={SN_BETA}\n\n"
            f"Fold 详情:\n{fold_lines}\n\n"
            f"> 基线: WF OOS Sharpe={BASELINE_SHARPE} (2026-04-12)"
        )
        _send_dingtalk(f"Rolling WF {classification['label']}", content, classification["level"])

    return {
        "status": "success",
        "wf_result": wf_result,
        "classification": classification,
    }


def main():
    parser = argparse.ArgumentParser(description="Rolling WF 月度策略验证 → DingTalk")
    parser.add_argument("--dry-run", action="store_true", help="不跑 WF, 不发 DingTalk")
    parser.add_argument("--skip-wf", action="store_true", help="跳过 WF, 只检查上次结果")
    parser.add_argument("--force", action="store_true", help="强制执行 (忽略日期检查)")
    args = parser.parse_args()

    result = run_rolling_wf(dry_run=args.dry_run, skip_wf=args.skip_wf, force=args.force)

    classification = result.get("classification", {})
    if classification.get("level") == "P1":
        sys.exit(1)


if __name__ == "__main__":
    main()
