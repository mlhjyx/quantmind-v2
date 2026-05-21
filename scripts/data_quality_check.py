#!/usr/bin/env python3
"""数据质量自动巡检脚本。

每日由 Task Scheduler 触发 (默认 18:30, 见 scripts/setup_task_scheduler.ps1),
检查当日 klines_daily / daily_basic / moneyflow_daily 数据完整性。异常时通过
钉钉发送 P1 告警 + 写 notifications 表留底。

检查项:
  1. 行数一致性: klines_daily / daily_basic / moneyflow_daily 当日行数互相比对
  2. NULL 比例: 关键字段 NULL>5% 告警
  3. 最新日期: 各表最新 trade_date 是否 = 最近交易日（漏拉检测）
  4. 脏数据守护: MAX(trade_date) > today+7 视为未来日期脏数据 (P0)
  5. factor_values 巡检 (Plan E, Blueprint §10.5): 计算因子表新鲜度 / active 因子
     覆盖缺失 / neutral_value NULL率 / 字面 NaN (铁律 29) / 越界值

铁律 33 fail-loud:
  - PG `statement_timeout=60s` (防 cold-cache COUNT 长挂, 4-22/4-23 hang 根因)
  - `connect_timeout=30s` (防 socket 建立慢)
  - main() top-level try/except → stderr + exit(2), schtask LastResult 非零可告警
  - logger FileHandler `delay=True` 防 Windows 文件锁竞争 (4-23 log 0 行根因)

用法:
    python scripts/data_quality_check.py              # 自动检测最近交易日
    python scripts/data_quality_check.py --date 2026-03-25  # 指定日期
    python scripts/data_quality_check.py --dry-run    # 只打印不发钉钉
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import logging
import sys
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg2

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# PROJECT_ROOT needed for `from backend.qm_platform._types` transitive import
# via qm_platform/__init__.py → backtest/__init__.py → memory_registry.py.
# Phase 0 Finding #9/#32/#33 cumulative — sys.path drift pattern recurrence
# (3rd 实证 per LL-175 lesson 2); same fix as services_healthcheck.py.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "backend"))

# Platform SDK lazy import (top-level for static analysis + reviewer P3 DX, batch 3.1).
# AlertDispatchError 必 top-level 暴露给 run_checks except 子句静态可见.
from qm_platform.observability import AlertDispatchError  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.dispatchers import dingtalk  # noqa: E402

# ── 日志 ──
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "data_quality_check.log"

# FileHandler delay=True: lazy open, 防 Windows 多 process zombie 文件锁
# (4-23 log 0 行事故根因 — 4-22 hang process 被 schtask 5min kill, 但 Windows
# 文件锁延迟释放, 4-23 冷启动 FileHandler open 失败 silent swallow).
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8", delay=True)
_stream_handler = logging.StreamHandler()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_stream_handler, _file_handler],
)
logger = logging.getLogger(__name__)


# ── 配置 ──
ROW_TOLERANCE = 0.08  # 行数偏差容差 ±8%（moneyflow 天然少于 klines 约 5-6%）
NULL_THRESHOLD = 0.05  # NULL 比例告警阈值 5%
MAX_DATE_LAG = 1  # 最大允许滞后交易日数
FUTURE_DATE_GUARD_DAYS = 7  # MAX(trade_date) > today + N 天视为脏数据

# PG 连接硬超时 (铁律 33 fail-loud)
STATEMENT_TIMEOUT_MS = 60_000  # 单 SQL 60s (cold scan 17s × safety 3x)
CONNECT_TIMEOUT_S = 30  # socket 建立 30s

# 各表关键字段（用于 NULL 检查）
NULL_CHECK_FIELDS = {
    "klines_daily": ["close", "volume", "amount"],
    "daily_basic": ["total_mv", "turnover_rate", "pe_ttm"],
    "moneyflow_daily": ["buy_sm_amount", "sell_sm_amount", "net_mf_amount"],
}

# factor_values 巡检阈值 (Plan E, Blueprint §10.5)
# active 因子 neutral_value NULL 比例阈值: 中性化对缺行业/市值/新股天然有少量
# NULL, 0.30 = 系统性故障级 (非细粒度劣化, 首版保守防钉钉误报刷屏)
FACTOR_NULL_THRESHOLD = 0.30
# neutral_value 绝对值上限: 预处理设计 clip ±3, >10 必为量纲错/污染 (零误报阈值)
FACTOR_VALUE_ABS_LIMIT = 10.0


def get_connection(
    statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    connect_timeout_s: int = CONNECT_TIMEOUT_S,
) -> psycopg2.extensions.connection:
    """从 settings 解析连接参数，返回带 statement_timeout 的 psycopg2 同步连接。

    铁律 33: PG `statement_timeout` 硬超时, 防 cold-cache / table lock 无限
    等待. 超时后 PG raise QueryCanceled, Python 抛 exception, main() 捕获
    退出 exit_code=2.
    """
    url = settings.DATABASE_URL
    # 去掉 async driver 前缀
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(
        url,
        connect_timeout=connect_timeout_s,
        options=f"-c statement_timeout={statement_timeout_ms}",
    )


def get_latest_trading_day(cur: psycopg2.extensions.cursor, ref_date: date | None = None) -> date:
    """获取 <= ref_date 的最近交易日."""
    if ref_date is None:
        ref_date = date.today()
    cur.execute(
        """SELECT trade_date FROM trading_calendar
           WHERE is_trading_day = true AND market = 'astock' AND trade_date <= %s
           ORDER BY trade_date DESC LIMIT 1""",
        (ref_date,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"找不到 <= {ref_date} 的交易日，请检查 trading_calendar 表")
    return row[0]


def check_future_dates(cur: psycopg2.extensions.cursor, today: date) -> list[str]:
    """检测任何表的 MAX(trade_date) > today+N 天 (脏数据/未来日期守护).

    背景: 2026-04-20 至今, klines_daily 有 1 row `TA010.SH @ 2099-04-30`
    (OHLC=10/vol=1000 测试 sentinel), 导致 check_latest_dates 的 MAX 返回
    2099 → `最新日期=2099-04-30 OK` 误报, 掩盖 4-20+ klines 真实滞后.
    """
    alerts: list[str] = []
    cutoff = today + timedelta(days=FUTURE_DATE_GUARD_DAYS)

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        cur.execute(
            f"SELECT trade_date, COUNT(*) FROM {table} WHERE trade_date > %s "
            "GROUP BY trade_date ORDER BY trade_date",
            (cutoff,),
        )
        rows = cur.fetchall()
        if rows:
            detail = ", ".join(f"{d}×{n}" for d, n in rows)
            alerts.append(
                f"[P0] {table} 发现未来日期脏数据 (>today+{FUTURE_DATE_GUARD_DAYS}d): {detail}"
            )
            logger.error("%s 未来日期: %s", table, detail)
    return alerts


def check_row_counts(cur: psycopg2.extensions.cursor, trade_date: date) -> list[str]:
    """检查各表当日行数一致性. 返回告警消息列表."""
    alerts: list[str] = []
    counts: dict[str, int] = {}

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        logger.debug("count %s @ %s...", table, trade_date)
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE trade_date = %s",
            (trade_date,),
        )
        counts[table] = cur.fetchone()[0]

    logger.info(
        "行数统计 %s: klines=%d, daily_basic=%d, moneyflow=%d",
        trade_date,
        counts["klines_daily"],
        counts["daily_basic"],
        counts["moneyflow_daily"],
    )

    # 以 klines_daily 为基准
    base = counts["klines_daily"]
    if base == 0:
        alerts.append(f"klines_daily {trade_date} 行数=0，可能未拉取数据")
        return alerts

    for table in ["daily_basic", "moneyflow_daily"]:
        cnt = counts[table]
        if cnt == 0:
            alerts.append(f"{table} {trade_date} 行数=0，数据完全缺失")
            continue
        ratio = abs(cnt - base) / base
        if ratio > ROW_TOLERANCE:
            alerts.append(
                f"{table} {trade_date} 行数偏差过大: "
                f"{cnt} vs klines {base} (偏差{ratio:.1%}, 阈值{ROW_TOLERANCE:.0%})"
            )

    return alerts


def check_null_ratios(cur: psycopg2.extensions.cursor, trade_date: date) -> list[str]:
    """检查关键字段 NULL 比例. 返回告警消息列表."""
    alerts: list[str] = []

    for table, fields in NULL_CHECK_FIELDS.items():
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE trade_date = %s",
            (trade_date,),
        )
        total = cur.fetchone()[0]
        if total == 0:
            continue  # 行数检查已覆盖

        for field in fields:
            cur.execute(
                f"SELECT COUNT(*) FROM {table} WHERE trade_date = %s AND {field} IS NULL",
                (trade_date,),
            )
            null_count = cur.fetchone()[0]
            null_ratio = null_count / total
            if null_ratio > NULL_THRESHOLD:
                alerts.append(
                    f"{table}.{field} {trade_date} NULL比例={null_ratio:.1%} "
                    f"({null_count}/{total}), 阈值{NULL_THRESHOLD:.0%}"
                )
            else:
                logger.debug(
                    "%s.%s NULL比例=%.2f%% (%d/%d) OK",
                    table,
                    field,
                    null_ratio * 100,
                    null_count,
                    total,
                )

    return alerts


def check_latest_dates(
    cur: psycopg2.extensions.cursor, expected_date: date, today: date
) -> list[str]:
    """检查各表最新日期是否为预期交易日.

    使用 effective_max (排除 > today+N 天的脏数据) 做滞后判断, 避免未来日期
    sentinel 掩盖真实滞后. 未来日期 alert 由 check_future_dates 单独负责.
    """
    alerts: list[str] = []
    cutoff = today + timedelta(days=FUTURE_DATE_GUARD_DAYS)

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        # 只取"有效"范围的 MAX, 排除脏数据 sentinel
        cur.execute(
            f"SELECT MAX(trade_date) FROM {table} WHERE trade_date <= %s",
            (cutoff,),
        )
        max_date = cur.fetchone()[0]
        if max_date is None:
            alerts.append(f"{table} 表为空，无任何数据")
            continue

        if max_date < expected_date:
            # 计算滞后了几个交易日
            cur.execute(
                """SELECT COUNT(*) FROM trading_calendar
                   WHERE is_trading_day = true AND market = 'astock'
                   AND trade_date > %s AND trade_date <= %s""",
                (max_date, expected_date),
            )
            lag = cur.fetchone()[0]
            level = "P0" if lag > MAX_DATE_LAG else "P1"
            alerts.append(
                f"[{level}] {table} 最新日期={max_date}，预期={expected_date}，滞后{lag}个交易日"
            )
        else:
            logger.info("%s 最新日期=%s OK", table, max_date)

    return alerts


def _summarize_factor_issue(level: str, issue: str, factors: list[str], d: date) -> str:
    """汇总同类 factor_values 告警为单条 (防 N 因子异常 → N 条告警刷屏)。"""
    n = len(factors)
    shown = ", ".join(factors[:8])
    suffix = " ..." if n > 8 else ""  # n 已在主文本 "{n} 个", suffix 仅标列表截断
    return f"[{level}] factor_values {d} {n} 个 active 因子 {issue}: {shown}{suffix}"


def check_factor_values(
    cur: psycopg2.extensions.cursor, expected_date: date, today: date
) -> list[str]:
    """检查 factor_values (计算因子表) 数据质量 (Plan E, Blueprint §10.5).

    factor_values (816M 行 hypertable) 喂养全部信号/回测/IC — 但旧巡检只覆盖
    klines/daily_basic/moneyflow 原始行情, 不查计算因子。本步骤补上 5 项:
      1. 新鲜度: factor_values MAX(trade_date) 滞后 expected_date → 因子未计算
      2. 覆盖缺失: active 因子在最新因子日 0 行 → P0 (该因子当日未算出)
      3. NULL 率: neutral_value NULL 比例 > FACTOR_NULL_THRESHOLD → P1
      4. 字面 NaN: neutral_value = 'NaN' → P0 (铁律 29 — NaN 不得入库)
      5. 越界值: |neutral_value| > FACTOR_VALUE_ABS_LIMIT → P1 (预处理设计 clip ±3)

    查询 scoped 到 active 因子 (factor_registry.status='active') + 单一最新因子日,
    走 idx_fv_date_factor (trade_date, factor_name) 索引 (铁律 9: 只读有界查询,
    statement_timeout 兜底)。同类告警汇总为单条防刷屏。
    """
    alerts: list[str] = []

    # 1. active 因子集
    cur.execute("SELECT name FROM factor_registry WHERE status = 'active'")
    active_factors = [r[0] for r in cur.fetchall()]
    if not active_factors:
        logger.info("factor_registry 无 active 因子, 跳过 factor_values 巡检")
        return alerts

    # 2. factor_values 最新日 (scoped active 因子, 排除未来日期脏数据 sentinel)。
    # MAX(trade_date) 走 idx_fv_date_factor (trade_date, factor_name) 反向扫描 —
    # 最新交易日含全部 active 因子, 反向扫到首个匹配行即得 MAX (扫描有界);
    # statement_timeout=60s 兜底极端情形 (铁律 9)。
    cutoff = today + timedelta(days=FUTURE_DATE_GUARD_DAYS)
    cur.execute(
        "SELECT MAX(trade_date) FROM factor_values "
        "WHERE factor_name = ANY(%s) AND trade_date <= %s",
        (active_factors, cutoff),
    )
    factor_max_date = cur.fetchone()[0]
    if factor_max_date is None:
        alerts.append(
            f"[P0] factor_values 无 active 因子数据 (检查了 {len(active_factors)} 个 active 因子)"
        )
        return alerts

    # 新鲜度: factor_values 最新日滞后于 expected_date
    if factor_max_date < expected_date:
        cur.execute(
            """SELECT COUNT(*) FROM trading_calendar
               WHERE is_trading_day = true AND market = 'astock'
               AND trade_date > %s AND trade_date <= %s""",
            (factor_max_date, expected_date),
        )
        lag = cur.fetchone()[0]
        level = "P0" if lag > MAX_DATE_LAG else "P1"
        alerts.append(
            f"[{level}] factor_values 最新日={factor_max_date}, 预期={expected_date}, "
            f"滞后{lag}个交易日 (因子未计算 → 信号 stale)"
        )
    else:
        logger.info("factor_values 最新日=%s OK", factor_max_date)

    # 3-5. 逐 active 因子在最新因子日的健康度 (单次 GROUP BY 聚合)
    cur.execute(
        """SELECT factor_name,
                  COUNT(*) AS total,
                  COUNT(*) FILTER (WHERE neutral_value IS NULL) AS null_cnt,
                  COUNT(*) FILTER (WHERE neutral_value = CAST('NaN' AS numeric)) AS nan_cnt,
                  COUNT(*) FILTER (WHERE neutral_value <> CAST('NaN' AS numeric)
                                   AND (neutral_value > %s OR neutral_value < %s)) AS oor_cnt
           FROM factor_values
           WHERE trade_date = %s AND factor_name = ANY(%s)
           GROUP BY factor_name""",
        (
            FACTOR_VALUE_ABS_LIMIT,
            -FACTOR_VALUE_ABS_LIMIT,
            factor_max_date,
            active_factors,
        ),
    )
    stats = {row[0]: row[1:] for row in cur.fetchall()}

    missing = [f for f in active_factors if f not in stats]
    nan_bad: list[str] = []
    null_bad: list[str] = []
    oor_bad: list[str] = []
    for fname, (total, null_cnt, nan_cnt, oor_cnt) in stats.items():
        if nan_cnt > 0:
            nan_bad.append(f"{fname}({nan_cnt})")
        if total > 0 and null_cnt / total > FACTOR_NULL_THRESHOLD:
            null_bad.append(f"{fname}({null_cnt}/{total})")
        if oor_cnt > 0:
            oor_bad.append(f"{fname}({oor_cnt})")

    if missing:
        alerts.append(
            _summarize_factor_issue("P0", "覆盖缺失 (0 行, 当日未计算)", missing, factor_max_date)
        )
    if nan_bad:
        alerts.append(
            _summarize_factor_issue("P0", "含字面 NaN (铁律 29)", nan_bad, factor_max_date)
        )
    if null_bad:
        alerts.append(
            _summarize_factor_issue(
                "P1",
                f"neutral_value NULL率>{FACTOR_NULL_THRESHOLD:.0%}",
                null_bad,
                factor_max_date,
            )
        )
    if oor_bad:
        alerts.append(
            _summarize_factor_issue(
                "P1",
                f"neutral_value 越界 |值|>{FACTOR_VALUE_ABS_LIMIT:.0f}",
                oor_bad,
                factor_max_date,
            )
        )

    return alerts


def _max_severity(alerts: list[str]) -> str:
    """从 alert 字符串列表提取最高 severity (p0 > p1 > p2). 默认 p1.

    reviewer P2 采纳: 显式 reject 空列表 (caller 应预筛, 空列表语义不清).
    """
    if not alerts:
        raise ValueError("_max_severity called with empty alerts list")
    if any(a.startswith("[P0]") for a in alerts):
        return "p0"
    if any(a.startswith("[P1]") for a in alerts):
        return "p1"
    if any(a.startswith("[P2]") for a in alerts):
        return "p2"
    return "p1"  # 无前缀兜底 P1 (现状默认行为)


@functools.lru_cache(maxsize=1)
def _get_rules_engine():
    """Cached AlertRulesEngine load (reviewer P2 采纳: 防 17 scripts 每次 fire 重复 I/O).

    Process-level cache. yaml 加载失败返 None 不 raise (告警比 rules 重要, fail-loud
    交给 router.fire).
    """
    from qm_platform.observability import AlertRulesEngine

    try:
        return AlertRulesEngine.from_yaml(PROJECT_ROOT / "configs" / "alert_rules.yaml")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Observability] AlertRulesEngine load failed: %s, 用默认 dedup_key", e)
        return None


def send_dingtalk_alert(alerts: list[str], trade_date: date, dry_run: bool = False) -> None:
    """通过钉钉发送告警.

    MVP 4.1 batch 3.1 (2026-04-29): 默认走 Platform SDK (PostgresAlertRouter +
    AlertRulesEngine cross-process PG dedup), 旧 dingtalk.send_markdown_sync 直调
    保留作 fallback (settings.OBSERVABILITY_USE_PLATFORM_SDK=False 时切回, 紧急回滚用).

    行为对齐: 1 钉钉 per script run (不变, dedup 防同日多次 schtask 空跑风暴).
    severity 自动从 alerts 文本前缀 "[P0]"/"[P1]"/"[P2]" 提取最高级.
    """
    if dry_run:
        # dry-run 同时 dump 双 path payload 便于静态比对 (迁移信心)
        title = f"[{_max_severity(alerts).upper()}] 数据质量告警 {trade_date}"
        content = _build_alert_content(alerts, trade_date)
        logger.info(
            "[DRY-RUN] 钉钉消息 (sdk_flag=%s):\nTITLE: %s\nCONTENT:\n%s",
            settings.OBSERVABILITY_USE_PLATFORM_SDK,
            title,
            content,
        )
        return

    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        _send_alert_via_platform_sdk(alerts, trade_date)
    else:
        _send_alert_via_legacy_dingtalk(alerts, trade_date)


def _build_alert_content(alerts: list[str], trade_date: date) -> str:
    """构造钉钉 Markdown 内容 (新旧 path 共享, 行为一致).

    reviewer P2 采纳: datetime.now() naive 改为 UTC tz-aware (铁律 41).
    Display 层显式标 ' UTC' 防 caller 误以为本地时间.
    """
    lines = [f"### 数据质量巡检告警 {trade_date}", ""]
    lines.extend(f"{i}. {alert}" for i, alert in enumerate(alerts, 1))
    lines.append("")
    lines.append(f"---\n*巡检时间: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')} UTC*")
    return "\n".join(lines)


def _send_alert_via_platform_sdk(alerts: list[str], trade_date: date) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine yaml-driven dedup (MVP 4.1 batch 3.1).

    dedup_key=`data_quality:summary:{trade_date}` (同日多次 schtask 空跑 dedup, 5min P0
    / 30min P1 窗口 — alert_rules.yaml 控制).
    """
    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    severity_value = _max_severity(alerts)
    severity = Severity(severity_value)
    title = f"[{severity_value.upper()}] 数据质量告警 {trade_date}"
    content = _build_alert_content(alerts, trade_date)
    trade_date_str = str(trade_date)

    # Platform SDK Alert (details 含 trade_date 给 dedup_key_template 用)
    alert = Alert(
        title=title,
        severity=severity,
        source="data_quality_check",
        details={
            "trade_date": trade_date_str,
            "issue_count": str(len(alerts)),
            "content": content,
        },
        trade_date=trade_date_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    # reviewer P2 采纳: 用 cached engine 防多次 I/O (17 scripts 共享 process-level cache)
    engine = _get_rules_engine()
    rule = engine.match(alert) if engine else None
    if rule:
        dedup_key = rule.format_dedup_key(alert)
        suppress_minutes = rule.suppress_minutes
    else:
        # fallback: severity 默认 (router _DEFAULT_SUPPRESS_MINUTES) + 通用 dedup_key
        dedup_key = f"data_quality:summary:{trade_date_str}"
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
        # 全 channel failed — fail-loud (铁律 33). caller (run_checks) 必 except
        # AlertDispatchError 显式分类 (vs 通用 Exception, 防 exit_code 语义混淆)
        logger.error("[Observability] AlertRouter sink_failed: %s", e)
        raise


def _send_alert_via_legacy_dingtalk(alerts: list[str], trade_date: date) -> None:
    """旧 path: dingtalk.send_markdown_sync 直调 (fallback, settings flag=False 时走).

    保留作紧急回滚用. 完全行为等价 batch 3.1 前实现 (无 dedup, 每次 fire).

    reviewer P1 采纳: 旧版 hardcode `[P1]` 实为 bug (P0 alerts silent 标 P1 屏蔽运维),
    legacy path 也用 _max_severity 自动提取 (与 SDK path 行为一致, 防 flag 回滚后 P0
    被错标 P1).
    """
    webhook_url = settings.DINGTALK_WEBHOOK_URL
    if not webhook_url:
        logger.warning("DINGTALK_WEBHOOK_URL 未配置，跳过钉钉通知")
        return

    severity_value = _max_severity(alerts)
    title = f"[{severity_value.upper()}] 数据质量告警 {trade_date}"
    content = _build_alert_content(alerts, trade_date)

    ok = dingtalk.send_markdown_sync(
        webhook_url=webhook_url,
        title=title,
        content=content,
        secret=settings.DINGTALK_SECRET or "",
        keyword=settings.DINGTALK_KEYWORD or "",
    )
    if ok:
        logger.info("钉钉告警发送成功 (legacy path)")
    else:
        logger.error("钉钉告警发送失败 (legacy path)")


def write_db_alert(
    conn: psycopg2.extensions.connection, alerts: list[str], trade_date: date
) -> None:
    """将告警写入 notifications 表. Script 级事务管理 (铁律 32 例外 — 非 service).

    reviewer P2-2: cursor 用 with 块自动 close, 防异常路径泄漏.
    """
    try:
        with conn.cursor() as cur:
            content = "\n".join(f"- {a}" for a in alerts)
            cur.execute(
                """INSERT INTO notifications (level, category, market, title, content)
                   VALUES (%s, %s, %s, %s, %s)""",
                ("P1", "pipeline", "astock", f"数据质量告警 {trade_date}", content),
            )
        conn.commit()
        logger.info("告警已写入 notifications 表")
    except Exception as e:
        logger.error("写入 notifications 失败: %s", e)
        conn.rollback()


def run_checks(args: argparse.Namespace) -> int:
    """主检查流程. 返回 exit_code (0=OK, 1=发现异常, 2=脚本异常)."""
    logger.info("=" * 60)
    logger.info("数据质量巡检开始 (statement_timeout=%ds)", STATEMENT_TIMEOUT_MS // 1000)

    # reviewer P1-3: 连接/游标/exit_code 在 try 外 init, 防 get_connection / cursor
    # raise 时 finally 里 close() 触发 NameError (铁律 33 fail-loud 反面教训)
    conn: psycopg2.extensions.connection | None = None
    cur: psycopg2.extensions.cursor | None = None
    exit_code = 2  # 默认异常退出码, normal 路径会覆盖为 0 / 1
    today = date.today()

    try:
        conn = get_connection()
        cur = conn.cursor()
        # 确定检查日期
        check_date = (
            date.fromisoformat(args.date) if args.date else get_latest_trading_day(cur, today)
        )
        logger.info("检查日期: %s (today=%s)", check_date, today)

        # 执行所有检查 (每步独立 try, 单步失败不阻塞后续)
        all_alerts: list[str] = []

        for step_name, step_fn in (
            ("future_dates", lambda: check_future_dates(cur, today)),
            ("row_counts", lambda: check_row_counts(cur, check_date)),
            ("null_ratios", lambda: check_null_ratios(cur, check_date)),
            ("latest_dates", lambda: check_latest_dates(cur, check_date, today)),
            ("factor_values", lambda: check_factor_values(cur, check_date, today)),
        ):
            logger.info("→ %s 开始", step_name)
            try:
                step_alerts = step_fn()
                all_alerts.extend(step_alerts)
                logger.info("← %s 完成, %d 项告警", step_name, len(step_alerts))
            except Exception as e:
                logger.error("✗ %s 异常: %s", step_name, e, exc_info=True)
                all_alerts.append(f"[P0] 检查步骤 {step_name} 异常: {e}")

        # 输出结果
        if all_alerts:
            logger.warning("发现 %d 项异常:", len(all_alerts))
            for alert in all_alerts:
                logger.warning("  - %s", alert)

            # 发送钉钉告警 — reviewer P1.1 采纳: AlertDispatchError 单独 catch, 防与
            # check 逻辑异常 (exit_code=2) 混淆. 即便 sink 全 fail, 仍走 write_db_alert
            # (审计留底) + exit_code=1 (语义: 发现 issue). schtask LastResult=1 正确反映
            # "数据有 issue 但脚本本身正常", 与 LastResult=2 (脚本异常) 区分.
            try:
                send_dingtalk_alert(all_alerts, check_date, dry_run=args.dry_run)
            except AlertDispatchError as e:
                logger.error(
                    "[Observability] AlertDispatchError — alert 未送达, 写 DB 留底: %s",
                    e,
                )

            # 写 DB (无论 alert 是否送达, 审计必留)
            if not args.dry_run:
                write_db_alert(conn, all_alerts, check_date)

            exit_code = 1
        else:
            logger.info("所有检查通过，数据质量正常")
            exit_code = 0

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()

    logger.info("数据质量巡检完成 exit_code=%d", exit_code)
    logger.info("=" * 60)
    return exit_code


def main() -> int:
    """CLI entrypoint. 铁律 33 fail-loud: 顶层 try/except → stderr + exit(2)."""
    # Fail-loud 早期探针 (schtask stderr 捕获最早的启动证据).
    # reviewer P1-2: 移到 main() 首行而非 module-level, 防 import 副作用污染测试.
    print(
        f"[data_quality_check] boot {datetime.now().isoformat()} pid={__import__('os').getpid()}",
        flush=True,
        file=sys.stderr,
    )
    parser = argparse.ArgumentParser(description="数据质量自动巡检")
    parser.add_argument("--date", type=str, help="指定检查日期 YYYY-MM-DD（默认最近交易日）")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不发钉钉不写 DB")
    args = parser.parse_args()

    try:
        return run_checks(args)
    except Exception as e:
        # 最后兜底: logger 可能未初始化成功, stderr 必 print
        msg = f"[data_quality_check] FATAL: {type(e).__name__}: {e}"
        print(msg, flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # silent_ok: 最外层兜底, logger 可能未初始化成功, stderr 已打印
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
