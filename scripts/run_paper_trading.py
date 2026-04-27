#!/usr/bin/env python3
"""Paper Trading 两阶段管道 — V3编排器。

Step 6-A重构: 从1734行缩减为编排器。
具体逻辑在:
  - app.services.pt_data_service: 并行数据拉取
  - app.services.pt_monitor_service: 开盘跳空+风险检测
  - app.services.pt_qmt_state: QMT↔DB状态同步
  - app.services.shadow_portfolio: LightGBM影子选股

用法:
  python scripts/run_paper_trading.py signal --date 2026-04-08
  python scripts/run_paper_trading.py execute --date 2026-04-09
  python scripts/run_paper_trading.py signal --date 2026-04-08 --dry-run
"""

import argparse
import contextlib
import json
import logging
import os
import sys
import time
import traceback
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from engines.factor_engine import compute_daily_factors, save_daily_factors
from engines.signal_engine import PAPER_TRADING_CONFIG
from health_check import run_health_check
from run_backtest import load_factor_values, load_industry, load_universe

from app.config import settings
from app.core.qmt_client import QMTClient
from app.services.db import get_sync_conn
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.pt_data_service import fetch_daily_data
from app.services.pt_monitor_service import check_opening_gap
from app.services.pt_qmt_state import QMTEmptyPositionsError, save_qmt_state
from app.services.risk_control_service import check_circuit_breaker_sync
from app.services.shadow_portfolio import (
    generate_shadow_lgbm_inertia,
    generate_shadow_lgbm_signals,
)
from app.services.signal_service import SignalService
from app.services.trading_calendar import (
    acquire_lock,
    get_prev_trading_day,
    is_trading_day,
)

# ── 日志配置 ──
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
_log_handlers = [logging.FileHandler(LOG_DIR / "paper_trading.log", encoding="utf-8")]
if sys.stdout and not getattr(sys.stdout, "closed", True):
    with contextlib.suppress(Exception):
        _log_handlers.insert(0, logging.StreamHandler(sys.stderr))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
    force=True,
)
logger = logging.getLogger("paper_trading")


def log_step(conn, task_name: str, status: str, error: str = None, result: dict = None):
    """写入 scheduler_task_log。schedule_time 用 now() 代替 (实际执行时间)。"""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO scheduler_task_log "
        "(task_name, status, error_message, result_json, schedule_time, start_time, end_time, market) "
        "VALUES (%s, %s, %s, %s, NOW(), NOW(), NOW(), 'astock')",
        (task_name, status, error, json.dumps(result) if result else None),
    )
    conn.commit()


def load_today_prices(trade_date: date, conn) -> pd.DataFrame:
    """加载当日价格数据。"""
    return pd.read_sql(
        """SELECT k.code, k.trade_date, k.open, k.high, k.low, k.close, k.pre_close, k.volume, k.amount,
                  db.turnover_rate
           FROM klines_daily k
           LEFT JOIN daily_basic db ON k.code = db.code AND k.trade_date = db.trade_date
           WHERE k.trade_date = %s AND k.volume > 0
           ORDER BY k.code""",
        conn,
        params=(trade_date,),
    )


def get_benchmark_close(trade_date: date, conn) -> float:
    """获取CSI300当日收盘价。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT close FROM index_daily WHERE index_code='000300.SH' AND trade_date=%s",
        (trade_date,),
    )
    r = cur.fetchone()
    return float(r[0]) if r else 0.0


def _get_notif_service() -> NotificationService:
    return NotificationService(session=None)


_HEARTBEAT_FILE = Path(__file__).resolve().parent.parent / "logs" / "pt_heartbeat.json"


def _write_heartbeat(trade_date: date, phase: str) -> None:
    """写入心跳文件供 pt_watchdog 检测。Step 6-A 拆分时遗漏, 2026-04-16 补回。"""
    try:
        _HEARTBEAT_FILE.write_text(
            json.dumps({
                "trade_date": str(trade_date),
                "completed_at": datetime.now().isoformat(),
                "phase": phase,
                "status": "ok",
            }),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("[Heartbeat] 写入失败: %s", e)


# ════════════════════════════════════════════════════════════
# MVP 3.3 batch 2 Step 2 — SDK Parity Dual-Run (Session 39 末, 2026-04-27)
# ════════════════════════════════════════════════════════════
# 目的: signal_phase 调 PlatformSignalPipeline.generate(s1, ctx) parallel run
# 跟现产 signal_service.generate_signals 比对, 验证 SDK 在 production env 等价.
# 风险 L: 全 try/except 包裹, 失败仅 logger.warning, 0 production 行为变化.
# 价值 H: 1 周 0 parity diff 后 → Step 2c (真 cut over) 数据驱动决策.
# 跟 MVP 2.1c Sub3 dual-write 同模式 (parity-validated migration).


def _build_sdk_strategy_context(
    trade_date: "date",
    factor_df: "pd.DataFrame",
    universe: "set[str]",
    industry: "pd.Series | dict[str, str]",
    capital: "Decimal",
    ln_mcap: "pd.Series | None" = None,
    prev_holdings: "dict[str, float] | None" = None,
):
    """构造 SDK StrategyContext for parity dual-run (返 backend.qm_platform.strategy.interface.StrategyContext).

    本函数纯计算 (无 IO), 测试可注入 mock data. ln_mcap / prev_holdings 由调用方加载,
    本函数仅组装. P1 reviewer (PR #110) 采纳: prev_holdings 必传, 否则 PortfolioBuilder
    turnover_cap 不生效, 致 guaranteed parity diff (legacy 路径加载, SDK 路径默认 None).

    Args:
      trade_date: 交易日
      factor_df: 因子宽表 columns=[code, factor_name, neutral_value]
      universe: 可交易股票池 set[str]
      industry: pd.Series 或 dict (code → industry_sw1). pd.Series NaN 自动 dropna 防污染.
      capital: Decimal 分配资本 (PT 1M). 注意: S1MonthlyRanking 不读 ctx.capital,
        本字段是 StrategyContext 必填字段, S1 用 PortfolioBuilder 内部 weights (相对值, 非绝对).
      ln_mcap: pd.Series (code → ln(mcap)), None 表示 SN beta=0 不需
      prev_holdings: dict (code → weight), None 表示无前期持仓 (但应避免, parity 失真).
        legacy `signal_service._load_prev_weights` 加载 position_snapshot 同源.

    Returns:
      backend.qm_platform.strategy.interface.StrategyContext

    Raises:
      ImportError: SDK module 缺 (production env 应不发生, 走 caller try/except 兜底)
      TypeError: industry 非 pd.Series 也非 dict (P2 reviewer 严格类型守卫)
    """
    import pandas as pd  # noqa: PLC0415 — string forward ref, deferred 防 circular

    from backend.qm_platform.strategy.interface import StrategyContext

    # P2 reviewer (PR #110) 采纳: 严格类型守卫, 非 Series 非 dict 必 raise (防 DataFrame 误传).
    # P2 reviewer NaN guard: pd.Series.to_dict() 会保 NaN, 必 dropna 防污染 industry_map.
    if isinstance(industry, pd.Series):
        industry_map = industry.dropna().to_dict()
    elif isinstance(industry, dict):
        industry_map = {k: v for k, v in industry.items() if v is not None and not (isinstance(v, float) and pd.isna(v))}
    else:
        raise TypeError(
            f"industry 必须是 pd.Series 或 dict, got {type(industry).__name__}"
        )

    return StrategyContext(
        trade_date=trade_date,
        capital=capital,
        universe=list(universe),
        regime="default",
        metadata={
            "factor_df": factor_df,
            "industry_map": industry_map,
            "ln_mcap": ln_mcap,
            "prev_holdings": prev_holdings,
            # exclude / vol_regime_scale / volatility_map 留 None — S1 内部 default
        },
    )


class SignalPathDriftError(RuntimeError):
    """SDK signal path drift from legacy — STRICT 模式必 raise (production cut-over rollout 守门).

    Stage 2.5 (本批): 默认 warn-only (env SDK_PARITY_STRICT=false), Tuesday 4-28
    16:30 production parity 确认后 flip true. Stage 3.0 真切换 (删 legacy) 留独立 PR.
    """


# Stage 2.5 STRICT 触发值 (case-insensitive). pydantic-settings 路径留 Stage 3.0
# 配合 signal_service refactor 时统一升级 (铁律 34, 当前 raw env 兼容部署最便利).
_STRICT_TRUTHY = frozenset({"true", "1", "yes", "on"})


def _is_sdk_parity_strict() -> bool:
    """Read SDK_PARITY_STRICT env (truthy: true/1/yes/on, case-insensitive). Default False."""
    return os.environ.get("SDK_PARITY_STRICT", "").strip().lower() in _STRICT_TRUTHY


def _run_sdk_parity_dryrun(
    trade_date: "date",
    factor_df: "pd.DataFrame",
    universe: "set[str]",
    industry: "pd.Series",
    legacy_target_weights: dict,
    conn,
) -> None:
    """Parallel 调 PlatformSignalPipeline.generate(s1, ctx) + log 比对 vs legacy.

    全 try/except 兜底, 失败仅 logger.warning. 不动 signal_result / 不写 DB.
    1 周 0 parity diff 后 Step 2c 真 cut over 决策依据.

    P1 reviewer (PR #110) 采纳: prev_holdings 加载 via signal_service._load_prev_weights
    (跟 legacy 路径同源), 防 PortfolioBuilder turnover_cap 不一致致 guaranteed diff.
    P1 reviewer 采纳: import path 统一用 backend.* (跟其他 SDK imports 一致).
    P2 reviewer 采纳: parity 加 weight diff check (codes 一致后看 weight 数值).
    P2 reviewer 采纳: ImportError 不吞 (false-negative parity 防御), 单独 catch.
    """
    # SDK module imports — ImportError 必触发外层 except 全 traceback (false-negative 防御)
    try:
        from app.services.signal_service import SignalService
        from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking
        from backend.qm_platform.signal.pipeline import PlatformSignalPipeline
    except ImportError as e:
        logger.warning(
            "[Step3-SDK-parity] SDK not available, skip dual-run (trade_date=%s): %s",
            trade_date, e,
        )
        return

    try:
        # ln_mcap 加载 (镜像 signal_service:145-148, 失败让外层 except 暴露真 bug)
        ln_mcap = None
        if PAPER_TRADING_CONFIG.size_neutral_beta > 0:
            from engines.size_neutral import load_ln_mcap_for_date  # noqa: PLC0415
            ln_mcap = load_ln_mcap_for_date(trade_date, conn)

        # P1 reviewer 采纳: prev_holdings 加载 via legacy path 防 turnover_cap drift
        prev_holdings = SignalService()._load_prev_weights(  # noqa: SLF001 — 镜像 legacy 同源
            conn, settings.PAPER_STRATEGY_ID,
        )

        ctx = _build_sdk_strategy_context(
            trade_date=trade_date,
            factor_df=factor_df,
            universe=universe,
            industry=industry,
            # P2 reviewer 采纳: capital 注 settings.PAPER_INITIAL_CAPITAL, S1 不读但
            # StrategyContext 必填. settings 是 float 1M 整数, Decimal 路径精度安全.
            capital=Decimal(str(settings.PAPER_INITIAL_CAPITAL)),
            ln_mcap=ln_mcap,
            prev_holdings=prev_holdings,
        )
        pipe = PlatformSignalPipeline()
        s1 = S1MonthlyRanking()
        sdk_signals = pipe.generate(s1, ctx)

        # 比对 codes 集合 + weight 数值 (P2 reviewer 采纳: codes 一致不等于真 parity)
        sdk_weight_map = {s.code: s.target_weight for s in sdk_signals}
        sdk_codes = set(sdk_weight_map.keys())
        legacy_codes = set(legacy_target_weights.keys())
        parity_diff = sdk_codes.symmetric_difference(legacy_codes)

        sdk_total_w = sum(sdk_weight_map.values())
        legacy_total_w = sum(legacy_target_weights.values())

        # Stage 2.5 STRICT mode (env SDK_PARITY_STRICT truthy) — DIFF raise SignalPathDriftError
        # (Tuesday 16:30 production parity 确认后 flip env → next 16:30 SDK regression 立即被 production 检测).
        # 默认 false (warn-only) 兼容当前行为. once-per-day 频率, env 每次现读不缓存
        # (test 用 monkeypatch.setenv 切换需 fresh read).
        strict_mode = _is_sdk_parity_strict()

        if parity_diff:
            diff_sample = sorted(parity_diff)[:10]
            if strict_mode:
                # 仅 strict 路径打 strict=True 标 (warn-only 路径不带, 避免日志噪声)
                msg = (
                    f"[Step3-SDK-parity] DIFF trade_date={trade_date} {len(parity_diff)} codes: "
                    f"sdk={len(sdk_codes)} legacy={len(legacy_codes)} "
                    f"total_w_sdk={sdk_total_w:.4f} total_w_legacy={legacy_total_w:.4f} "
                    f"diff_sample={diff_sample} strict=True"
                )
                logger.error(msg)
                raise SignalPathDriftError(msg)
            # warn-only 路径走 %-format (lazy formatting, ruff G004 兼容)
            logger.warning(
                "[Step3-SDK-parity] DIFF trade_date=%s %d codes: sdk=%d legacy=%d "
                "total_w_sdk=%.4f total_w_legacy=%.4f diff_sample=%s",
                trade_date,
                len(parity_diff),
                len(sdk_codes),
                len(legacy_codes),
                sdk_total_w,
                legacy_total_w,
                diff_sample,
            )
        else:
            # P2 reviewer 采纳: codes 一致后再算 weight 数值 max diff
            common_codes = sdk_codes & legacy_codes
            weight_diffs = [
                abs(sdk_weight_map[code] - legacy_target_weights[code])
                for code in common_codes
            ]
            max_w_diff = max(weight_diffs) if weight_diffs else 0.0
            if max_w_diff > 1e-6:
                if strict_mode:
                    msg = (
                        f"[Step3-SDK-parity] codes match but WEIGHT DIFF trade_date={trade_date} "
                        f"codes={len(common_codes)} max_diff={max_w_diff:.6f} "
                        f"total_w_sdk={sdk_total_w:.4f} total_w_legacy={legacy_total_w:.4f} "
                        f"strict=True"
                    )
                    logger.error(msg)
                    raise SignalPathDriftError(msg)
                logger.warning(
                    "[Step3-SDK-parity] codes match but WEIGHT DIFF trade_date=%s "
                    "codes=%d max_diff=%.6f total_w_sdk=%.4f total_w_legacy=%.4f",
                    trade_date,
                    len(common_codes),
                    max_w_diff,
                    sdk_total_w,
                    legacy_total_w,
                )
            else:
                logger.info(
                    "[Step3-SDK-parity] OK trade_date=%s codes=%d max_w_diff=%.6f "
                    "total_w_sdk=%.4f total_w_legacy=%.4f",
                    trade_date,
                    len(sdk_codes),
                    max_w_diff,
                    sdk_total_w,
                    legacy_total_w,
                )
    except SignalPathDriftError:
        # STRICT mode: parity drift 必透传给 caller (signal_phase fail → 钉钉).
        # 不被外层 except Exception 吞 (Stage 2.5 守门核心机制).
        raise
    except Exception as e:  # noqa: BLE001 — read-only parity, production 不阻塞
        logger.warning(
            "[Step3-SDK-parity] dual-run failed (production 不影响): %s",
            e,
            exc_info=True,
        )


# ════════════════════════════════════════════════════════════
# Signal Phase — T日盘后 16:30
# ════════════════════════════════════════════════════════════


def run_signal_phase(
    trade_date: date,
    dry_run: bool,
    skip_fetch: bool,
    skip_factors: bool,
    force_rebalance: bool = False,
):
    """T日信号生成编排: 健康检查→拉数据→NAV→风控→因子→信号→影子→通知。"""
    logger.info("=" * 60)
    logger.info("[SIGNAL PHASE] T日=%s", trade_date)
    conn = get_sync_conn()
    # 铁律 32 (Phase D D2b 2026-04-16): 顶层脚本设 autocommit=True, 让 Service 函数
    # 不需要显式 commit. 每条 SQL 自成事务, log_step()/其他显式 commit() 在 autocommit
    # 模式下变为 no-op, 行为兼容. 与 factor_onboarding.py 已建立的 conn.autocommit=True
    # 模式保持一致.
    conn.autocommit = True
    t_total = time.time()

    try:
        if not acquire_lock(conn) or not is_trading_day(conn, trade_date):
            logger.info("%s 非交易日或锁冲突，退出", trade_date)
            return

        notif_svc = _get_notif_service()  # noqa: F841

        # Step 0: 健康预检
        health = run_health_check(trade_date, conn, write_db=not dry_run)
        if not health["all_pass"]:
            logger.error("[Step0] 预检失败")
            if not dry_run:
                log_step(conn, "signal_phase", "failed", "健康预检失败")
            sys.exit(1)

        # Step 0.5: 配置守卫 (铁律 34)
        # 先硬校验 .env / pt_live.yaml / PAPER_TRADING_CONFIG 三源对齐,
        # 任何漂移 RAISE ConfigDriftError (不允许静默降级, 防复发 F45/F62/F40)
        from engines.config_guard import (
            ConfigDriftError,
            assert_baseline_config,
            assert_execution_mode_integrity,
            check_config_alignment,
        )

        try:
            check_config_alignment()
        except ConfigDriftError as e:
            logger.error("[Step0.5] ConfigDriftError (铁律 34 违反):\n%s", e)
            if not dry_run:
                log_step(conn, "signal_phase", "failed", f"ConfigDriftError: {e}")
            sys.exit(1)

        # Session 21 Fix B (F17 防重演): EXECUTION_MODE 语义完整性校验
        # mode='paper' 但近 7 天有 live trade_log → WARN (可能 .env 僵尸)
        # mode 非法值 → RAISE. 不 coupling QMT/schtasks (降低 blast radius)
        try:
            assert_execution_mode_integrity(conn=conn)
        except ConfigDriftError as e:
            logger.error("[Step0.5] EXECUTION_MODE 校验失败:\n%s", e)
            if not dry_run:
                log_step(conn, "signal_phase", "failed", f"EXECUTION_MODE drift: {e}")
            sys.exit(1)

        # 兼容性: 保留旧的 factor-only 校验 (warning-level, 防止 factors 被外部脚本篡改)
        if not assert_baseline_config(PAPER_TRADING_CONFIG.factor_names, "run_paper_trading.py"):
            logger.error("[Step0.5] 因子集漂移!")
            sys.exit(1)

        # Step 1: 数据拉取(委托pt_data_service)
        fetch_result = fetch_daily_data(trade_date, skip_fetch=skip_fetch)
        logger.info(
            "[Step1] 数据: klines=%d, basic=%d (%.1fs)",
            fetch_result["klines_rows"],
            fetch_result["basic_rows"],
            fetch_result["elapsed"],
        )

        # Step 1.5: NAV更新(QMT→DB)
        try:
            qmt = QMTClient()
            qmt_positions = qmt.get_positions() or {}
            qmt_nav_data = qmt.get_nav()
            price_data_t = load_today_prices(trade_date, conn)
            today_close = (
                dict(zip(price_data_t["code"], price_data_t["close"], strict=False))
                if not price_data_t.empty
                else {}
            )

            nav = qmt_nav_data.get("total_value", 0) if qmt_nav_data else 0
            if nav <= 0:
                nav = sum(qty * today_close.get(code, 0) for code, qty in qmt_positions.items())
                nav += qmt_nav_data.get("cash", 0) if qmt_nav_data else 0

            cur = conn.cursor()
            # ADR-008 D2: performance_series 读按 settings.EXECUTION_MODE 动态
            # (Session 10 P1-c 根因: live 模式此处读 'paper' 永远 empty → prev_nav
            #  fallback 到 PAPER_INITIAL_CAPITAL → NAV daily_return/drawdown 字段全错)
            # Session 21 P1-c 二段根因 (2026-04-21): 缺 `AND trade_date < %s` 过滤,
            # 16:30 signal_phase 跑时 15:40 reconciliation 已写当日行, LIMIT 1 读到今日 self
            # → prev_nav = nav → daily_return = (nav/nav - 1) = 0. 修复: 明确排除今日.
            cur.execute(
                "SELECT nav FROM performance_series "
                "WHERE execution_mode=%s AND strategy_id=%s AND trade_date < %s "
                "ORDER BY trade_date DESC LIMIT 1",
                (settings.EXECUTION_MODE, settings.PAPER_STRATEGY_ID, trade_date),
            )
            r = cur.fetchone()
            prev_nav = float(r[0]) if r else settings.PAPER_INITIAL_CAPITAL

            benchmark_close = get_benchmark_close(trade_date, conn)
            if not dry_run and nav > 0:
                save_qmt_state(
                    conn,
                    trade_date,
                    qmt_positions,
                    today_close,
                    nav,
                    prev_nav,
                    qmt_nav_data,
                    benchmark_close,
                )
        except QMTEmptyPositionsError:
            # D2-a: fail-loud 不被"不影响信号"吞, 上浮到 L316 outer except → log_step + sys.exit(1)
            logger.error("[Step1.5] FAIL-LOUD: QMT 持仓蒸发检测触发, 中止 signal_phase")
            raise
        except Exception as e:
            logger.warning("[Step1.5] NAV更新失败(不影响信号): %s", e)

        # Step 1.6: 风控评估
        cb = check_circuit_breaker_sync(
            conn=conn,
            strategy_id=settings.PAPER_STRATEGY_ID,
            exec_date=trade_date,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        logger.info("[Step1.6] 熔断: L%s - %s", cb.get("level", 0), cb.get("reason", ""))

        # Step 2: 因子计算
        if not skip_factors:
            logger.info("[Step2] 因子计算...")
            factor_df = compute_daily_factors(trade_date, factor_set="full", conn=conn)
            save_daily_factors(trade_date, factor_df, conn=conn)

        # Step 3: 信号生成
        fv = load_factor_values(trade_date, conn)
        universe = load_universe(trade_date, conn)
        industry = load_industry(conn)

        signal_svc = SignalService()
        signal_result = signal_svc.generate_signals(
            conn=conn,
            strategy_id=settings.PAPER_STRATEGY_ID,
            trade_date=trade_date,
            factor_df=fv,
            universe=universe,
            industry=industry,
            config=PAPER_TRADING_CONFIG,
            dry_run=dry_run,
        )
        if force_rebalance and not signal_result.is_rebalance:
            signal_result.is_rebalance = True
            if not dry_run:
                cur = conn.cursor()
                # ADR-008 D3-KEEP: signals 表跨模式共享, UPDATE WHERE 固定 'paper'
                cur.execute(
                    "UPDATE signals SET action='rebalance' "
                    "WHERE trade_date=%s AND strategy_id=%s AND execution_mode='paper'",
                    (trade_date, settings.PAPER_STRATEGY_ID),
                )
                conn.commit()
                logger.info("[Step3] --force-rebalance: 已更新%d条信号为rebalance", cur.rowcount)
            else:
                logger.info("[Step3] --force-rebalance: dry-run模式，跳过DB更新")
        logger.info(
            "[Step3] 信号: %d只目标, rebalance=%s",
            len(signal_result.target_weights),
            signal_result.is_rebalance,
        )

        # MVP 3.3 batch 2 Step 2 SDK parity dual-run (read-only, 失败不阻塞).
        # 验证 PlatformSignalPipeline.generate(s1, ctx) 跟 legacy signal_svc 等价.
        # 1 周 0 parity diff 后 Step 2c 真 cut over.
        _run_sdk_parity_dryrun(
            trade_date=trade_date,
            factor_df=fv,
            universe=universe,
            industry=industry,
            legacy_target_weights=signal_result.target_weights,
            conn=conn,
        )

        # Step 3.5: 影子选股(可选,失败不阻塞)
        if signal_result.is_rebalance:
            for shadow_fn in [generate_shadow_lgbm_signals, generate_shadow_lgbm_inertia]:
                try:
                    shadow_fn(trade_date, conn, dry_run)
                except Exception as e:
                    logger.warning("[Shadow] %s失败: %s", shadow_fn.__name__, e)

        # Step 5: 收尾
        if not dry_run:
            log_step(conn, "signal_phase", "success")
            _write_heartbeat(trade_date, "signal")

        elapsed = time.time() - t_total
        logger.info("[SIGNAL PHASE] 完成: %.0fs", elapsed)

    except Exception as e:
        logger.error("[SIGNAL PHASE] 失败: %s\n%s", e, traceback.format_exc())
        if not dry_run:
            log_step(conn, "signal_phase", "failed", str(e))
        sys.exit(1)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# Execute Phase — T+1日 09:31
# ════════════════════════════════════════════════════════════


def run_execute_phase(
    exec_date: date, dry_run: bool, skip_fetch: bool, execution_mode: str = "paper"
):
    """T+1日执行编排: QMT连接→读信号→风控→执行→对账→通知。"""
    logger.info("=" * 60)
    logger.info("[EXECUTE PHASE] exec_date=%s, mode=%s", exec_date, execution_mode)
    exec_mode = execution_mode

    # Live模式: 启动QMT
    if exec_mode == "live":
        settings.EXECUTION_MODE = "live"
        try:
            from app.services.qmt_connection_manager import qmt_manager

            qmt_manager.startup()
        except Exception as e:
            logger.error("[Execute] QMT启动失败: %s", e)

    conn = get_sync_conn()
    # 铁律 32 (Phase D D2b 2026-04-16): 顶层脚本设 autocommit=True, 与 run_signal_phase 一致.
    conn.autocommit = True
    t_total = time.time()

    try:
        if not acquire_lock(conn) or not is_trading_day(conn, exec_date):
            return

        notif_svc = _get_notif_service()

        # Step 5: 读信号
        signal_svc = SignalService()
        signal_date = get_prev_trading_day(conn, exec_date)
        signals_list = signal_svc.get_latest_signals(
            conn=conn, strategy_id=settings.PAPER_STRATEGY_ID, signal_date=signal_date
        )
        hedged_target = {s["code"]: s["target_weight"] for s in signals_list}
        is_rebalance = (
            any(s["action"] == "rebalance" for s in signals_list) if signals_list else False
        )
        logger.info(
            "[Step5] 信号日=%s, 目标=%d只, rebalance=%s",
            signal_date,
            len(hedged_target),
            is_rebalance,
        )

        # Step 5.5: 数据拉取(如需)
        if not skip_fetch:
            fetch_daily_data(exec_date, skip_fetch=False)

        # Step 5.7: QMT drift检测(live模式)
        if exec_mode == "live" and hedged_target:
            try:
                from app.services.qmt_connection_manager import qmt_manager

                qmt_pos = qmt_manager.broker.query_positions() if qmt_manager.broker else []
                actual_holdings = {
                    p.get("stock_code", ""): p["volume"]
                    for p in qmt_pos
                    if p.get("market_value", 0) > 1000
                }
                target_count = len(hedged_target)
                if len(actual_holdings) < target_count * 0.5:
                    is_rebalance = True
                    logger.info(
                        "[Step5.7] 首次建仓检测: actual=%d < target×0.5=%d",
                        len(actual_holdings),
                        target_count * 0.5,
                    )
            except Exception as e:
                logger.warning("[Step5.7] Drift检测失败: %s", e)

        # Step 5.8: 开盘跳空预检
        price_data_t = load_today_prices(exec_date, conn)

        # Step 5.8.1: 价格数据校验 (2026-04-14新增)
        if price_data_t.empty:
            if exec_mode == "live":
                logger.warning("[Step5.8] price_data为空，live模式继续(依赖QMT实时价)")
            else:
                logger.error("[Step5.8] price_data为空，paper模式中止执行")
                if not dry_run:
                    log_step(conn, f"execute_phase_{exec_mode}", "failed", "price_data为空")
                return

        check_opening_gap(exec_date, price_data_t, conn, notif_svc, dry_run)

        # Step 5.9: 熔断检查
        cb = check_circuit_breaker_sync(
            conn=conn,
            strategy_id=settings.PAPER_STRATEGY_ID,
            exec_date=exec_date,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        logger.info("[Step5.9] 熔断: L%s", cb.get("level", 0))

        # Step 6: 执行调仓
        exec_svc = ExecutionService()
        exec_result = None

        if is_rebalance and hedged_target:
            exec_svc.process_pending_orders(
                conn=conn,
                strategy_id=settings.PAPER_STRATEGY_ID,
                exec_date=exec_date,
                price_data=price_data_t,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                cb_level=cb.get("level", 0),
            )
            exec_result = exec_svc.execute_rebalance(
                conn=conn,
                strategy_id=settings.PAPER_STRATEGY_ID,
                exec_date=exec_date,
                target_weights=hedged_target,
                cb_level=cb.get("level", 0),
                position_multiplier=0.5,
                price_data=price_data_t,
                initial_capital=settings.PAPER_INITIAL_CAPITAL,
                signal_date=signal_date,
                execution_mode=exec_mode,
            )
            fill_count = (
                len(exec_result.fills) if exec_result and hasattr(exec_result, "fills") else 0
            )
            logger.info("[Step6] 执行: %d笔成交", fill_count)
        else:
            logger.info("[Step6] 无调仓")

        if not dry_run:
            log_step(conn, f"execute_phase_{exec_mode}", "success")
            _write_heartbeat(exec_date, "execute")

        elapsed = time.time() - t_total
        logger.info("[EXECUTE PHASE] 完成: %.0fs", elapsed)

    except Exception as e:
        logger.error("[EXECUTE PHASE] 失败: %s\n%s", e, traceback.format_exc())
        if not dry_run:
            log_step(conn, f"execute_phase_{exec_mode}", "failed", str(e))
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════
# CLI入口
# ════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="QuantMind Paper Trading 两阶段管道")
    parser.add_argument("phase", choices=["signal", "execute"])
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-factors", action="store_true")
    parser.add_argument(
        "--force-rebalance", action="store_true", help="Force rebalance regardless of schedule"
    )
    parser.add_argument("--execution-mode", choices=["paper", "live"], default=None)
    args = parser.parse_args()

    # MVP 1.3b wiring: Platform DBFactorRegistry + DBFeatureFlag → signal_engine.
    # 幂等 + fail-safe (失败自动回 Layer 0 hardcoded, 3 层 fallback 保底).
    from app.core.platform_bootstrap import bootstrap_platform_deps

    bootstrap_platform_deps()

    if not settings.PAPER_STRATEGY_ID:
        logger.error("PAPER_STRATEGY_ID未配置!")
        sys.exit(1)

    trade_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()

    if args.phase == "signal":
        run_signal_phase(
            trade_date, args.dry_run, args.skip_fetch, args.skip_factors, args.force_rebalance
        )
    elif args.phase == "execute":
        exec_mode = args.execution_mode or settings.EXECUTION_MODE
        run_execute_phase(trade_date, args.dry_run, args.skip_fetch, execution_mode=exec_mode)


if __name__ == "__main__":
    main()
