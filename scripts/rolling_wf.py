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
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    from qm_platform.observability import AlertRulesEngine

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# 铁律 10b shadow fix: append 而非 insert(0) 避免 backend/platform/ shadow stdlib
# platform (参考 PR #67 pt_daily_summary 8 天 silent-fail 根因).
# 7th sys.path drift fix (同 PR #377 broker_qmt + PR #378 health_check pattern):
# qm_platform.backtest 内部 `from backend.qm_platform._types import BacktestMode`
# 需要 PROJECT_ROOT 也在 sys.path.
# Canonical order: PROJECT_ROOT first, then BACKEND_DIR
# (matches pt_watchdog.py / data_quality_check.py / services_healthcheck.py).
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

# MVP 4.1 batch 3.6: AlertDispatchError 顶层 import (避免 try-import 包裹掩盖 bug,
# 铁律 33 fail-loud).
from qm_platform.observability import AlertDispatchError  # noqa: E402

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

# DSR (Deflated Sharpe Ratio, DEV_BACKTEST_ENGINE.md §4.12.1) — 多重检验校正.
# n_trials: doc 公式 N = n_windows × param_grid_size. rolling_wf 跑固定
# CORE3+dv_ttm 配置 (param_grid_size=1), n_windows = WF n_splits = 5.
_DSR_N_TRIALS = 5
# DSR < 0.5 = "大概率过拟合" (doc §4.12.1 解读). Sharpe 判定 OK 但 DSR 低于此阈值
# 时升级 OK → WARN, 提示 OOS Sharpe 经多重检验校正后统计上不显著.
_DSR_WARN_THRESHOLD = 0.5


def _load_wf_data():
    """加载 WF 所需的因子/价格/基准数据 (走 Parquet 缓存)。

    P0-2 fix (2026-05-17): `BacktestDataCache` 接口只有 `load(start, end)` 返 dict
    `{"price_data", "factor_data", "benchmark"}`. 旧调用 `load_factor_data()` /
    `load_price_data()` / `load_benchmark_data()` (无参 3 个独立方法) 不存在 → AttributeError.
    走 cache_meta.json 实际 cached range (2014-01-01 ~ 2026-04-15).
    """

    from data.parquet_cache import CACHE_DIR, BacktestDataCache

    cache = BacktestDataCache()
    meta_path = CACHE_DIR / "cache_meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"cache_meta.json 不存在 ({meta_path}). 请先 `python scripts/build_backtest_cache.py`"
        )
    with open(meta_path) as f:
        meta = json.load(f)
    start = meta["start_date"]
    end = meta["end_date"]

    data = cache.load(start, end)
    price_df = data["price_data"]
    factor_df = data["factor_data"]
    bench_df = data["benchmark"]

    # parquet_cache.FACTOR_SQL 把 COALESCE(neutral_value, raw_value) 存为 "raw_value" 列
    # (Step 6-D Fix 1 comment, 历史遗留). 下游 signal_func 期望 "neutral_value", 兼容 rename.
    if "raw_value" in factor_df.columns and "neutral_value" not in factor_df.columns:
        factor_df = factor_df.rename(columns={"raw_value": "neutral_value"})

    # PR #381 reviewer P2: fail-loud (铁律 33) — assert neutral_value column present
    # so downstream signal_func 不在深处抛 opaque KeyError 而是这里清晰报错.
    if "neutral_value" not in factor_df.columns:
        raise ValueError(
            f"factor_df missing 'neutral_value' column; columns present: {list(factor_df.columns)}. "
            f"Likely cache schema drift — check parquet_cache.FACTOR_SQL."
        )

    logger.info(
        "数据加载 (cache %s ~ %s): factors=%d行, prices=%d行, bench=%d行",
        start,
        end,
        len(factor_df),
        len(price_df),
        len(bench_df),
    )
    return factor_df, price_df, bench_df


def _compute_dsr(
    combined_oos_sharpe: float,
    combined_oos_returns: pd.Series | None,
    total_oos_days: int,
) -> tuple[float | None, str]:
    """计算 WF OOS 拼接结果的 Deflated Sharpe Ratio (DEV_BACKTEST_ENGINE §4.12.1).

    观测 Sharpe 取 `combined_oos_sharpe` (OOS 拼接曲线的 Sharpe), 与 skew/kurt
    所基于的 `combined_oos_returns` 同源, 保证口径一致 — 不与各 fold Sharpe 均值
    `chain_sharpe` 混用. n_trials 取 WF n_splits=5 (doc 公式 N = n_windows ×
    param_grid_size, rolling_wf 固定配置 param_grid_size=1).

    pandas `.kurtosis()` 返超额峰度 (正态=0), DSR 引擎要原始峰度 (正态=3), 故 +3
    (对齐 doc §4.12.1 reference 实现 `kurt = ... + 3  # excess→raw`).

    DSR 是补充诊断指标 (非主告警信号): 任何计算失败 (数据不足 / skew·kurt 非有限
    值 / 引擎 ValueError) → 返 `(None, "")` + log warning, 不阻断 WF 主结果.

    Args:
        combined_oos_sharpe: WF OOS 拼接曲线的年化 Sharpe.
        combined_oos_returns: WF OOS 拼接日收益 pandas Series.
        total_oos_days: OOS 拼接总交易日数 (DSR n_observations).

    Returns:
        (dsr, interpretation). dsr 为 None 表示无法计算; 否则 round 到 4 位.
    """
    from engines.dsr import deflated_sharpe_ratio, interpret_dsr

    try:
        # DSR 需有限 skew (3 阶矩) + 有限 kurtosis (4 阶矩); pandas 对 n<4 的
        # .kurtosis() 返 NaN, 故取 4 作数据量下限 (生产 total_oos_days ~1250).
        if total_oos_days < 4 or combined_oos_returns is None or len(combined_oos_returns) < 4:
            logger.warning("[DSR] OOS 数据不足 (<4 点, days=%s), 跳过 DSR 计算", total_oos_days)
            return None, ""
        skew = float(combined_oos_returns.skew())
        kurt = float(combined_oos_returns.kurtosis()) + 3.0  # excess → raw
        if not (np.isfinite(skew) and np.isfinite(kurt)):
            logger.warning(
                "[DSR] skew/kurt 非有限值 (skew=%s, kurt=%s), 跳过 DSR 计算",
                skew,
                kurt,
            )
            return None, ""
        dsr = deflated_sharpe_ratio(
            observed_sharpe=combined_oos_sharpe,
            n_trials=_DSR_N_TRIALS,
            n_observations=total_oos_days,
            skewness=skew,
            kurtosis=kurt,
        )
        return round(dsr, 4), interpret_dsr(dsr)
    except Exception as e:  # noqa: BLE001 — DSR 补充指标, 失败不阻断 WF 主结果 (铁律 33 fail-safe)
        logger.warning("[DSR] 计算失败 (%s: %s), 跳过 DSR", type(e).__name__, e)
        return None, ""


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

    # Size-neutral (P0-2 fix 2026-05-17: API drift — load_ln_mcap_pivot now requires
    # (start_date, end_date, conn=None) signature instead of price_df arg).
    # PR #381 reviewer P1: use get_sync_conn() (env-driven via DATABASE_URL, 铁律 35)
    # instead of hardcoded DSN. Matches engines/backtest/runner.py:131 pattern.
    from app.data_fetcher.data_loader import get_sync_conn

    _start = min(price_df["trade_date"])
    _end = max(price_df["trade_date"])
    _conn_sn = get_sync_conn()
    try:
        ln_mcap_pivot = load_ln_mcap_pivot(_start, _end, conn=_conn_sn)
    finally:
        _conn_sn.close()

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

    # DSR (DEV_BACKTEST_ENGINE §4.12.1): 多重检验校正后的 Sharpe 显著性.
    # observed_sharpe 用 combined_oos_sharpe (拼接曲线 Sharpe) — 与 skew/kurt 所
    # 基于的 combined_oos_returns 同源 (chain_sharpe 是各 fold Sharpe 均值, 口径不同).
    dsr, dsr_interp = _compute_dsr(
        result.combined_oos_sharpe,
        result.combined_oos_returns,
        result.total_oos_days,
    )

    return {
        "chain_sharpe": round(chain_sharpe, 4),
        "combined_oos_sharpe": result.combined_oos_sharpe,
        "total_oos_days": result.total_oos_days,
        "neg_folds": neg_folds,
        "dsr": dsr,
        "dsr_interpretation": dsr_interp,
        "folds": fold_data,
        "elapsed_s": round(elapsed, 1),
        "run_date": str(date.today()),
    }


def _classify_result(wf_result: dict) -> dict:
    """分类告警等级。

    Sharpe / neg_fold 阈值决定基础等级; DSR (DEV_BACKTEST_ENGINE §4.12.1) 作补充
    诊断: 当 Sharpe 判定 OK 但 DSR < _DSR_WARN_THRESHOLD (大概率过拟合) 时升级
    OK → WARN (label=DSR_LOW). DSR 不下调已有的 P1 / WARN 等级。

    `dsr` / `dsr_interpretation` 用 .get() 读取 — 兼容 --skip-wf 加载的旧 result
    JSON (无 DSR 字段时 dsr=None, 不渲染 suffix 也不触发升级)。
    """
    sharpe = wf_result["chain_sharpe"]
    neg_folds = wf_result["neg_folds"]
    dsr = wf_result.get("dsr")
    dsr_interp = wf_result.get("dsr_interpretation", "")
    dsr_suffix = f" | DSR={dsr} ({dsr_interp})" if dsr is not None else ""

    if neg_folds > 0:
        return {
            "level": "P1",
            "label": "NEGATIVE_FOLD",
            "msg": f"WF OOS 有 {neg_folds} 个负 fold! chain_sharpe={sharpe:.4f}{dsr_suffix}",
        }

    if sharpe < BASELINE_SHARPE * ALERT_RATIO:
        return {
            "level": "P1",
            "label": "SHARPE_ALERT",
            "msg": f"WF OOS Sharpe 严重下降: {sharpe:.4f} (基线 {BASELINE_SHARPE}, 下降 {(1 - sharpe / BASELINE_SHARPE) * 100:.0f}%){dsr_suffix}",
        }

    if sharpe < BASELINE_SHARPE * WARN_RATIO:
        return {
            "level": "WARN",
            "label": "SHARPE_WARN",
            "msg": f"WF OOS Sharpe 轻微下降: {sharpe:.4f} (基线 {BASELINE_SHARPE}, 下降 {(1 - sharpe / BASELINE_SHARPE) * 100:.0f}%){dsr_suffix}",
        }

    if dsr is not None and dsr < _DSR_WARN_THRESHOLD:
        return {
            "level": "WARN",
            "label": "DSR_LOW",
            "msg": f"WF OOS Sharpe 稳定 ({sharpe:.4f}) 但 DSR={dsr} < {_DSR_WARN_THRESHOLD} — {dsr_interp} (多重检验校正后不显著)",
        }

    return {
        "level": "OK",
        "label": "STABLE",
        "msg": f"WF OOS Sharpe 稳定: {sharpe:.4f} (基线 {BASELINE_SHARPE}){dsr_suffix}",
    }


@lru_cache(maxsize=1)
def _load_rules_engine_cached():
    """Inner cached loader: only success cached, raises on yaml load failure.

    P1.2 reviewer 采纳: lru_cache 不缓存 exception (Python lang spec). 失败时
    异常向上传播, 不会被 memoize, 下次 call 重试. 防 cold-start yaml 缺失场景下
    永久 silent suppression (None 被缓存 → 进程生命周期内告警全 fail).
    """
    from qm_platform.observability import AlertRulesEngine

    rules_path = PROJECT_ROOT / "configs" / "alert_rules.yaml"
    return AlertRulesEngine.from_yaml(str(rules_path))


def _get_rules_engine() -> AlertRulesEngine | None:
    """AlertRulesEngine 公共 accessor (lru_cache 防 yaml 多次 reload).

    P1.1 reviewer 采纳: 显式 return type, 让 caller `if engine is not None` guard
    可被 mypy 识别.
    P1.2 reviewer 采纳: 失败 None 不缓存 — 下次调用重新尝试 load (yaml 可能恢复).
    """
    try:
        return _load_rules_engine_cached()
    except Exception as e:  # noqa: BLE001
        logger.warning("[Observability] AlertRulesEngine load failed: %s, fallback", e)
        return None


def _send_alert_via_platform_sdk(title: str, content: str, level: str = "P1") -> bool:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.6).

    rolling_wf 月度告警 (1st of month 02:00). level 取自 _classify_result —
    "P1" (ALERT >30% Sharpe 下降) 或 "WARN" (15-30% 下降). Severity 映射:
      P1 → Severity.P1, WARN → Severity.P2 (less severe), 其他 → fallback p1.

    AlertDispatchError 从本 SDK fn 向上传播 (铁律 33 fail-loud). 调用方 (run_rolling_wf)
    catch 后 log+continue (月度非紧急告警, 不阻断 schtask exit code) — code-reviewer
    P1 反馈采纳: SDK 层 fail-loud + 调用方层 graceful 是分层契约, 不是契约违反.

    Returns:
      True 钉钉接受; False channel 返 False (例如 webhook 未配置 + sink_failed).
    """
    # P3.1 reviewer 采纳: UTC + datetime 已 module-top 导入, 不在函数内 redundant import.
    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    # level 映射 → Severity. P2.1 reviewer 模式: unknown level fallback p1.
    level_norm = level.lower() if level else "p1"
    if level_norm == "warn":
        severity = Severity.P2
    elif level_norm in {"p0", "p1", "p2", "info"}:
        severity = Severity(level_norm)
    else:
        severity = Severity.P1

    today_str = str(date.today())
    full_content = f"## 📊 {title}\n\n{content}\n\n> 来源: rolling_wf"
    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="rolling_wf",
        details={
            "trade_date": today_str,
            "level": level,
            "content": full_content,
        },
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    router = get_alert_router()
    engine = _get_rules_engine()
    if engine is not None:
        rule = engine.match(alert)
        dedup_key = rule.format_dedup_key(alert) if rule else f"rolling_wf:summary:{today_str}"
        suppress_minutes = rule.suppress_minutes if rule else 1440
    else:
        dedup_key = f"rolling_wf:summary:{today_str}"
        suppress_minutes = 1440

    result = router.fire(alert, dedup_key=dedup_key, suppress_minutes=suppress_minutes)
    return result == "sent"


def _send_alert_via_legacy_dingtalk(title: str, content: str, level: str = "P1") -> bool:
    """legacy 直接调 send_markdown_sync (保留向后兼容路径)。"""
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


def _send_dingtalk(title: str, content: str, level: str = "P1") -> bool:
    """发送 DingTalk 告警 (MVP 4.1 batch 3.6 dispatch).

    settings.OBSERVABILITY_USE_PLATFORM_SDK 控制路径切换. AlertDispatchError 必传播
    (铁律 33 fail-loud), legacy ImportError/连接失败 仍 swallow 返 False.
    """
    from app.config import settings

    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        return _send_alert_via_platform_sdk(title, content, level)
    return _send_alert_via_legacy_dingtalk(title, content, level)


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
        # batch 3.6 dispatch (P1.1 模式: AlertDispatchError 单 catch, fail-loud).
        try:
            _send_dingtalk(
                f"Rolling WF {classification['label']}",
                content,
                classification["level"],
            )
        except AlertDispatchError as e:
            logger.error(
                "[Observability] AlertDispatchError 月度告警 sink 失败: %s "
                "(rolling_wf 月度任务, 非紧急, 不阻断 schtask)",
                e,
            )

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
