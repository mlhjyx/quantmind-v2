"""IC 监控 — CORE4 因子月度 Rolling IC 趋势 + 衰减告警 → DingTalk。

Phase 3 自动化 (2026-04-16): 每周日 20:00 由 Task Scheduler 触发。
检测 CORE4 因子最近 3 个月 vs 历史全量 IC 是否显著下降。

告警规则:
  - L0 正常: recent_ic / baseline_ic > 0.70  (下降 <30%)
  - L1 观察: 0.50 < ratio <= 0.70             (下降 30-50%)
  - L2 告警: ratio <= 0.50                    (下降 >50%, DingTalk P1 推送)
  - 方向反转: sign(recent) != sign(baseline)   (DingTalk P0 推送)

用法:
    python scripts/ic_monitor.py                    # 正常运行
    python scripts/ic_monitor.py --dry-run           # 不发 DingTalk
    python scripts/ic_monitor.py --months 6          # 看最近 6 个月 (默认 3)
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# 铁律 10b shadow fix: append 而非 insert(0) 避免 backend/platform/ shadow stdlib
# platform (参考 PR #67 pt_daily_summary 8 天 silent-fail 根因).
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

# Platform SDK 顶层 import (batch 3.1/3.2 模式延续, 防 import-in-try NameError).
from dotenv import load_dotenv
from qm_platform.observability import AlertDispatchError  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
_handlers = [logging.FileHandler(LOG_DIR / "ic_monitor.log", encoding="utf-8")]
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
logger = logging.getLogger("ic_monitor")

# ── 配置 ──────────────────────────────────────────────────
# F71 fix (Phase E 2026-04-16): 从 PAPER_TRADING_CONFIG + FACTOR_DIRECTION 读取, 不再硬编码
from engines.signal_engine import FACTOR_DIRECTION, PAPER_TRADING_CONFIG

CORE_FACTORS = list(PAPER_TRADING_CONFIG.factor_names)
CORE_DIRECTIONS = {f: FACTOR_DIRECTION.get(f, 1) for f in CORE_FACTORS}

# 告警阈值
L1_RATIO = 0.70  # recent/baseline < 0.70 → L1 观察
L2_RATIO = 0.50  # recent/baseline < 0.50 → L2 告警


def _get_conn():
    """获取 psycopg2 连接。"""
    from app.services.db import get_sync_conn

    return get_sync_conn()


def _load_ic_history(conn, factor_name: str) -> list[dict]:
    """从 factor_ic_history 加载 IC 记录 (ic_5d 列, Rank IC horizon=5)。"""
    import pandas as pd

    df = pd.read_sql(
        """SELECT trade_date, ic_5d AS ic_value
           FROM factor_ic_history
           WHERE factor_name = %s
             AND ic_5d IS NOT NULL
           ORDER BY trade_date""",
        conn,
        params=(factor_name,),
    )
    return df.to_dict("records") if not df.empty else []


def _compute_rolling_stats(records: list[dict], recent_months: int = 3) -> dict:
    """计算全量基线 IC 和最近 N 月 IC。"""
    if not records:
        return {"baseline_ic": None, "recent_ic": None, "n_total": 0, "n_recent": 0}

    all_ic = [r["ic_value"] for r in records if r["ic_value"] is not None]
    if not all_ic:
        return {"baseline_ic": None, "recent_ic": None, "n_total": 0, "n_recent": 0}

    cutoff = date.today() - timedelta(days=recent_months * 30)
    recent_ic = [
        r["ic_value"] for r in records if r["ic_value"] is not None and r["trade_date"] >= cutoff
    ]

    baseline = float(np.mean(all_ic))
    recent = float(np.mean(recent_ic)) if recent_ic else None

    return {
        "baseline_ic": baseline,
        "recent_ic": recent,
        "n_total": len(all_ic),
        "n_recent": len(recent_ic),
    }


def _classify_level(factor_name: str, baseline_ic: float, recent_ic: float, direction: int) -> dict:
    """分类告警等级。"""
    # 方向反转检测 (P0)
    if np.sign(recent_ic) != np.sign(baseline_ic) and abs(recent_ic) > 0.005:
        return {
            "level": "P0",
            "label": "DIRECTION_REVERSAL",
            "msg": f"{factor_name}: IC 方向反转! baseline={baseline_ic:.4f} → recent={recent_ic:.4f}",
        }

    # 衰减比例
    ratio = abs(recent_ic) / abs(baseline_ic) if abs(baseline_ic) > 1e-6 else 1.0

    if ratio <= L2_RATIO:
        return {
            "level": "P1",
            "label": "L2_DECAY",
            "msg": f"{factor_name}: IC 衰减 {(1 - ratio) * 100:.0f}% (baseline={baseline_ic:.4f}, recent={recent_ic:.4f})",
        }
    elif ratio <= L1_RATIO:
        return {
            "level": "INFO",
            "label": "L1_WATCH",
            "msg": f"{factor_name}: IC 轻微下降 {(1 - ratio) * 100:.0f}% (在观察范围)",
        }
    else:
        return {
            "level": "OK",
            "label": "L0_NORMAL",
            "msg": f"{factor_name}: IC 稳定 (ratio={ratio:.2f})",
        }


@functools.lru_cache(maxsize=1)
def _get_rules_engine():
    """Cached AlertRulesEngine load (batch 3.1/3.2 pattern)."""
    from qm_platform.observability import AlertRulesEngine

    project_root = Path(__file__).resolve().parent.parent
    try:
        return AlertRulesEngine.from_yaml(project_root / "configs" / "alert_rules.yaml")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[Observability] AlertRulesEngine load failed: %s, 用默认 dedup_key", e
        )
        return None


def _send_alert_via_platform_sdk(
    title: str, content: str, level: str, alerts: list[dict]
) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.3)."""
    from datetime import UTC, datetime

    from qm_platform._types import Severity
    from qm_platform.observability import (
        Alert,
        AlertDispatchError,
        get_alert_router,
    )

    severity_value = level.lower()
    severity = Severity(severity_value)
    today_str = str(date.today())

    factors_str = ",".join(sorted({a.get("factor", "") for a in alerts if a.get("factor")}))
    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="ic_monitor",
        details={
            "trade_date": today_str,
            "alert_count": str(len(alerts)),
            "factors": factors_str,
            "content": content,
        },
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    engine = _get_rules_engine()
    rule = engine.match(alert) if engine else None
    if rule:
        dedup_key = rule.format_dedup_key(alert)
        suppress_minutes = rule.suppress_minutes
    else:
        dedup_key = f"ic_monitor:summary:{today_str}"
        suppress_minutes = None

    router = get_alert_router()
    try:
        result = router.fire(
            alert,
            dedup_key=dedup_key,
            suppress_minutes=suppress_minutes,
        )
        logger.info(
            "[Observability] AlertRouter.fire result=%s key=%s severity=%s",
            result,
            dedup_key,
            severity_value,
        )
    except AlertDispatchError as e:
        logger.error("[Observability] AlertRouter sink_failed: %s", e)
        raise


def _send_alert_via_legacy_dingtalk(title: str, content: str, level: str) -> bool:
    """旧 path: dingtalk dispatcher 直调 (fallback, settings flag=False 时走)."""
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


def _send_dingtalk(
    title: str, content: str, level: str = "P1", alerts: list[dict] | None = None
) -> bool:
    """发送告警 (MVP 4.1 batch 3.3 dispatch).

    默认走 PlatformAlertRouter (settings.OBSERVABILITY_USE_PLATFORM_SDK=True),
    旧 dingtalk 直调路径保留作 fallback. AlertDispatchError 必传播.
    """
    from app.config import settings

    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        _send_alert_via_platform_sdk(title, content, level, alerts or [])
        return True
    return _send_alert_via_legacy_dingtalk(title, content, level)


def run_ic_monitor(recent_months: int = 3, dry_run: bool = False) -> dict:
    """执行 IC 监控主逻辑。"""
    logger.info("=" * 60)
    logger.info("[IC Monitor] 开始检查 CORE4 因子 IC 趋势 (最近 %d 月)", recent_months)

    conn = _get_conn()
    results = {}
    alerts = []

    try:
        for factor in CORE_FACTORS:
            records = _load_ic_history(conn, factor)
            stats = _compute_rolling_stats(records, recent_months)

            direction = CORE_DIRECTIONS[factor]
            factor_result = {
                "factor": factor,
                "direction": direction,
                **stats,
            }

            if stats["baseline_ic"] is not None and stats["recent_ic"] is not None:
                classification = _classify_level(
                    factor, stats["baseline_ic"], stats["recent_ic"], direction
                )
                factor_result.update(classification)

                if classification["level"] in ("P0", "P1"):
                    alerts.append(classification)

                logger.info(
                    "  %s: baseline=%.4f, recent(%dm)=%.4f, %s",
                    factor,
                    stats["baseline_ic"],
                    recent_months,
                    stats["recent_ic"],
                    classification["label"],
                )
            else:
                factor_result["level"] = "SKIP"
                factor_result["label"] = "NO_DATA"
                logger.warning("  %s: IC 数据不足, 跳过", factor)

            results[factor] = factor_result

        # ── 告警汇总 ──
        if alerts and not dry_run:
            max_level = "P0" if any(a["level"] == "P0" for a in alerts) else "P1"
            alert_lines = [a["msg"] for a in alerts]
            content = (
                f"### IC 监控告警 ({date.today()})\n\n"
                + "\n".join(f"- {line}" for line in alert_lines)
                + f"\n\n> 检查范围: 最近 {recent_months} 个月 vs 全量基线"
            )
            # batch 3.3 (P1.1 batch 3.1 模式延续): AlertDispatchError 单独 catch
            try:
                _send_dingtalk(
                    f"IC 衰减告警 {date.today()}", content, max_level, alerts=alerts
                )
                logger.info("[Alert] 发送 %s 告警: %d 条", max_level, len(alerts))
            except AlertDispatchError as e:
                logger.error(
                    "[Observability] AlertDispatchError — 告警未送达, 主流程继续: %s", e
                )
        elif alerts:
            logger.info("[DRY-RUN] 有 %d 条告警, 但 dry-run 不发送", len(alerts))
        else:
            logger.info("[IC Monitor] CORE4 全部正常, 无告警")

    finally:
        conn.close()

    return {"date": str(date.today()), "factors": results, "alerts": alerts}


def main():
    parser = argparse.ArgumentParser(description="IC 监控 — CORE4 因子 IC 趋势告警")
    parser.add_argument("--months", type=int, default=3, help="最近 N 个月 (默认 3)")
    parser.add_argument("--dry-run", action="store_true", help="不发 DingTalk")
    args = parser.parse_args()

    result = run_ic_monitor(recent_months=args.months, dry_run=args.dry_run)

    # 打印摘要
    n_alerts = len(result.get("alerts", []))
    if n_alerts > 0:
        logger.info("结果: %d 条告警", n_alerts)
        sys.exit(1)  # 非零退出让 Task Scheduler 标记失败
    else:
        logger.info("结果: CORE4 全部正常")


if __name__ == "__main__":
    main()
