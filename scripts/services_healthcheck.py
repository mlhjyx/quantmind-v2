"""ServicesHealthCheck — 4 Servy 服务 + CeleryBeat 心跳 15min 频次监控 (LL-074 fix).

Session 34 (2026-04-25 02:20 UTC) 抓出 CeleryBeat 在 04-24 19:26 → 04-25 02:20
**静默死亡 ~7h 0 stderr 0 Event 0 检测**, 若 Monday 4-27 09:00 首次生产触发前
再次发生, MVP 3.1 Risk Framework intraday-risk-check `*/5 9-14 * * 1-5` 72/日 +
risk-daily-check 14:30 全 missed → 真金 ¥1M 0 熔断保护.

PT_Watchdog 1/日 (20:00) 检测频次远不够 (Beat 凌晨死亡 → 20:00 = 17h 静默 gap).

## 检查项

| # | 项目 | 阈值 | 失败行为 |
|---|------|------|---------|
| 1 | QuantMind-FastAPI 服务 | RUNNING | fail (告警) |
| 2 | QuantMind-Celery 服务 | RUNNING | fail (告警) |
| 3 | QuantMind-CeleryBeat 服务 | RUNNING | fail (P0 告警, 阻断 Risk Framework) |
| 4 | QuantMind-QMTData 服务 | RUNNING | fail (告警) |
| 5 | celerybeat-schedule.dat 心跳新鲜度 | ≤ 10min | fail (Beat zombie 进程未真跑 schedule) |

## 调度 (LL-074 fix)

- **schtask `QuantMind_ServicesHealthCheck`**: 每 15min, 24/7
- 触发: `New-ScheduledTaskTrigger -Once + RepetitionInterval 15min RepetitionDuration unlimited`
- 96 次/日, 每次 < 1s (subprocess + file stat), 0 PG conn 占用

## 告警去重 (file-based, 不依赖 PG)

- 状态文件: `logs/services_healthcheck_state.json`
- 仅在 **状态转移 (ok→degraded) OR failures set 变化** 时发钉钉
- 1h 内重复 failures 集合 silent (防 spam, schtask 96/日 × 钉钉无配额)
- 注意: PG 挂时本脚本仍能告警 (核心 LL-074 修复价值)

## Exit code (铁律 43 d)

- 0: 全 ok
- 1: warn (degraded 但 dedup window 内)
- 2: error (top-level except OR fatal)

## 关联铁律

- 铁律 33 fail-loud: 顶层 except → stderr + exit 2 (silent_ok 仅 logger 兜底)
- 铁律 42: scripts/** 必 PR (本 PR 走 LL-059 9 步闭环)
- 铁律 43 (a) PG statement_timeout — **N/A** 本脚本不开 PG conn (核心设计: PG 挂时仍告警)
  (b) FileHandler delay=True ✓
  (c) boot stderr probe ✓
  (d) main() 顶层 try/except → stderr + exit 2 ✓

## LL-074

CeleryBeat silent death 0 logs detection gap. 本脚本是 Monday 4-27 首次真生产触发
前的最后一道防线 — 1h 内 SLA 检测窗口对比之前 17h.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# 铁律 41: 内部存储 UTC, 展示层转 Asia/Shanghai. 用于 DingTalk 告警显示.
# PR #91 reviewer LOW 采纳: Windows 系统 IANA tz 数据缺失时 ZoneInfo 会 raise
# ZoneInfoNotFoundError 在 module load 时炸. 兜底改用 fixed UTC+8 offset (Asia/Shanghai
# 全年无 DST, fixed offset 等价于 ZoneInfo 数据). 防 future 部署 Windows 无 tzdata
# pip install (LL-074 健康监控不可在依赖 tzdata 上 hang 整脚本).
try:
    _CST_TZ: Any = ZoneInfo("Asia/Shanghai")
except ZoneInfoNotFoundError:
    _CST_TZ = timezone(timedelta(hours=8), name="CST")  # fixed UTC+8 fallback


def _to_cst_display(utc_iso: str | None) -> str:
    """Convert UTC ISO timestamp to Asia/Shanghai display format.

    Args:
        utc_iso: UTC ISO 8601 string (e.g. "2026-04-25T14:45:02.315821+00:00") or None

    Returns:
        Asia/Shanghai display format "YYYY-MM-DD HH:MM:SS CST" or "N/A" for None.

    铁律 41: 时间与时区统一 — 内部 UTC, 展示层 Asia/Shanghai.
    Session 36 末 user 反馈 LL-074 钉钉告警显示 UTC 不友好, 改 CST.
    """
    if not utc_iso:
        return "N/A"
    try:
        dt_utc = datetime.fromisoformat(utc_iso)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=UTC)
        dt_cst = dt_utc.astimezone(_CST_TZ)
        return dt_cst.strftime("%Y-%m-%d %H:%M:%S CST")
    except (ValueError, TypeError):
        return utc_iso  # fallback raw 防 alert 完全 broken

# ─── sys.path + .env bootstrap (对齐 monitor_mvp_3_1_sunset.py PR #73 模式) ──
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

# ─── Constants ──────────────────────────────────────────────────────────────

SERVY_SERVICES: tuple[str, ...] = (
    "QuantMind-FastAPI",
    "QuantMind-Celery",
    "QuantMind-CeleryBeat",
    "QuantMind-QMTData",
)

# CeleryBeat PersistentScheduler dump file. 5min cycle 默认, 10min = 2x cycle 阈值.
BEAT_SCHEDULE_FILE = PROJECT_ROOT / "celerybeat-schedule.dat"
BEAT_HEARTBEAT_MAX_AGE_SECONDS = 10 * 60  # 10 min

# LL-081 PR-X3 (2026-04-27 真生产首日 zombie 4h17m 教训): Redis 应用层 freshness probe.
# Servy `status=Running` 是必要不充分条件 — service hang 后进程仍在跑 + Servy 看不到,
# 必看 Redis 关键 key updated_at 跟 stream last event time. 三层任一 stale = zombie.
PORTFOLIO_NAV_MAX_AGE_SECONDS = 5 * 60  # 5 min, 5x QMTData sync_loop 60s buffer
# reviewer code HIGH-2 采纳 (2026-04-27): 实际 PR-X1 SETEX TTL=180s < 300s, 即 zombie
# 后 180s 时 r.get() 已返 None → found=False → stale, 比 age 阈值更早触发. 阈值 300s
# 对 found=True 的 age 计算才生效. 两层兜底: TTL expire (主) + age threshold (副).
QMT_STATUS_STREAM_MAX_AGE_SECONDS = 30 * 60  # 30 min, connect 边沿 publish 长 buffer (zombie 期 21h+ 跨 night 仍能捕获)
REDIS_PROBE_TIMEOUT_SECONDS = 3  # 短超时, 防 health check 自己 hang on Redis

# 服务 state 文件 (告警 dedup, 1h 窗口)
STATE_FILE = PROJECT_ROOT / "logs" / "services_healthcheck_state.json"
DEDUP_WINDOW_SECONDS = 60 * 60  # 1h

# 子进程超时 (sc query 通常 < 100ms, 5s 充裕)
SC_QUERY_TIMEOUT_SECONDS = 5

# 钉钉 category (匹配 monitor_mvp_3_1_sunset.py 模式, 留 future PG dedup hook)
DINGTALK_CATEGORY = "services_healthcheck"

# ─── Logger ─────────────────────────────────────────────────────────────────

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "services_healthcheck.log"

# 铁律 43 b: FileHandler delay=True 防 Windows zombie 文件锁 (LL-068 pattern)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8", delay=True),
    ],
)
logger = logging.getLogger(__name__)


# ─── Data classes ───────────────────────────────────────────────────────────


@dataclass
class ServiceCheck:
    """Single Servy service status (sc query output 解析)."""

    name: str
    running: bool
    state_text: str  # "RUNNING" | "STOPPED" | "UNKNOWN" | "ERROR: <reason>"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BeatHeartbeatCheck:
    """CeleryBeat PersistentScheduler dump file freshness."""

    file_exists: bool
    age_seconds: float | None
    last_write_iso: str | None
    fresh: bool  # age <= BEAT_HEARTBEAT_MAX_AGE_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RedisFreshnessCheck:
    """Redis 应用层 key freshness probe (LL-081 PR-X3 zombie 兜底防御).

    - portfolio:nav: JSON {updated_at: ISO 8601 UTC}, sync_loop 60s 写
    - qm:qmt:status: stream, connect 边沿 publish, last event time
    """

    key: str
    found: bool  # key 存在
    age_seconds: float | None  # None = parse 失败 / 不存在
    threshold_seconds: int
    reason: str  # 详细描述, 钉钉 markdown 用
    # PR-X3 reviewer code MEDIUM-2 follow-up (2026-04-27): 非交易时段 stream stale 是 expected
    # (connect 边沿事件不持续), 应 INFO 不入 failures 防噪声告警.
    # default True 保留 fail-loud 默认行为, check_redis_freshness 显式 set False 降级.
    is_failure_alertable: bool = True

    @property
    def stale(self) -> bool:
        """stale = key 不存在 OR parse 失败 OR age > threshold (fail-loud)."""
        if not self.found or self.age_seconds is None:
            return True
        return self.age_seconds > self.threshold_seconds

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "stale": self.stale}


def _is_trading_hours_now() -> bool:
    """A 股交易时段判断 (周一-五 09:30-11:30 + 13:00-15:00, Asia/Shanghai).

    follow-up to PR-X3 reviewer code MEDIUM-2: 非交易时段 stream connect 边沿事件
    必然 stale, 不应触发告警噪声. 不依赖 PG conn (services_healthcheck 核心设计:
    PG 挂时仍能告警 LL-074), 用静态 weekday + hour/minute 检查.

    **不含节假日 list** (硬编码 list 跨年脆弱). 法定节假日 weekday 误报风险接受 — 1h
    dedup window 抑制 spam, 1 次告警可手动检查后 ack.

    Returns:
        True 仅当 周一-五 + (09:30-11:30 OR 13:00-15:00) 上海时间.
    """
    now_cst = datetime.now(_CST_TZ)
    if now_cst.weekday() >= 5:  # Sat=5, Sun=6
        return False
    hm = now_cst.hour * 60 + now_cst.minute
    morning_open = 9 * 60 + 30
    morning_close = 11 * 60 + 30
    afternoon_open = 13 * 60
    afternoon_close = 15 * 60
    in_morning = morning_open <= hm < morning_close
    in_afternoon = afternoon_open <= hm < afternoon_close
    return in_morning or in_afternoon


@dataclass
class HealthReport:
    """聚合健康报告."""

    timestamp_utc: str
    services: list[ServiceCheck] = field(default_factory=list)
    beat_heartbeat: BeatHeartbeatCheck | None = None
    redis_freshness: list[RedisFreshnessCheck] = field(default_factory=list)  # LL-081 PR-X3
    failures: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "ok" if not self.failures else "degraded"

    def to_dict(self) -> dict[str, Any]:
        d = {
            "timestamp_utc": self.timestamp_utc,
            "status": self.status,
            "services": [s.to_dict() for s in self.services],
            "beat_heartbeat": (self.beat_heartbeat.to_dict() if self.beat_heartbeat else None),
            "redis_freshness": [c.to_dict() for c in self.redis_freshness],
            "failures": self.failures,
        }
        return d


# ─── Service status check ──────────────────────────────────────────────────


def query_service_state(name: str) -> ServiceCheck:
    """调 Windows ``sc query <name>`` 解析服务状态.

    Args:
        name: Servy 服务名 (e.g., "QuantMind-CeleryBeat")

    Returns:
        ServiceCheck dataclass. ``running`` True 仅当 sc query 返 "STATE : 4 RUNNING".

    Note:
        - 不 raise: subprocess 失败 / timeout / 未安装均归类 ERROR (铁律 33 fail-loud
          上层报告, 但本函数对单服务不阻断其他检查)
        - 返回 state_text 包含原始 stdout 末段供 debug
    """
    # 用 Popen 而非 subprocess.run, 因为 Windows 的 subprocess.run(timeout=...) 抛
    # TimeoutExpired 后**不杀子进程** — sc.exe 会变成 orphan 累积 (reviewer P2 fix).
    proc = None
    try:
        proc = subprocess.Popen(  # noqa: S603 (name 来自 SERVY_SERVICES 常量, shell=False)
            ["sc", "query", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=SC_QUERY_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.communicate(timeout=2)  # silent_ok: drain after kill, 仅清理 pipe
            return ServiceCheck(name=name, running=False, state_text="ERROR: sc query timeout")
        returncode = proc.returncode
    except OSError as e:  # FileNotFoundError if sc.exe missing
        return ServiceCheck(name=name, running=False, state_text=f"ERROR: {e}")

    if returncode != 0:
        # sc query exits non-zero if service unknown OR access denied
        stderr_tail = (stderr or "").strip()[-100:] or "(empty stderr)"
        return ServiceCheck(
            name=name,
            running=False,
            state_text=f"ERROR: rc={returncode} stderr={stderr_tail}",
        )

    # 按行解析 STATE 字段 (reviewer P1 fix): 原 substring 全文匹配会被
    # ``TYPE : 10  WIN32_OWN_PROCESS`` 行内 ": 10" → ": 1" 子串误命中 STOPPED 分支,
    # 真实 sc query 输出格式包含 SERVICE_NAME / TYPE / STATE / WIN32_EXIT_CODE 4+ 行.
    # sc query 数字态稳定 (中英 locale 不影响数字, 但 RUNNING/STOPPED 字符串中文是
    # "正在运行"/"已停止" — 故仅靠数字 ": 4" / ": 1" 不够, 需要 STATE 字段+数字组合).
    stdout_text = stdout or ""
    for line in stdout_text.splitlines():
        if "STATE" not in line:
            continue
        # 只在 STATE 行里判 ": 4" / ": 1" 数字态 (locale-stable):
        # `STATE              : 4  RUNNING` / `STATE              : 1  STOPPED`
        if ": 4" in line:
            return ServiceCheck(name=name, running=True, state_text="RUNNING")
        if ": 1" in line:
            return ServiceCheck(name=name, running=False, state_text="STOPPED")
        # Pause / Start pending / etc. — 状态码非 1/4
        return ServiceCheck(name=name, running=False, state_text=f"UNKNOWN: {line.strip()[-80:]}")
    # 完全没找到 STATE 行 (sc 输出异常)
    return ServiceCheck(
        name=name, running=False, state_text=f"UNKNOWN: {stdout_text.strip()[-80:]}"
    )


# ─── Beat heartbeat check ──────────────────────────────────────────────────


def check_beat_heartbeat() -> BeatHeartbeatCheck:
    """检查 ``celerybeat-schedule.dat`` 文件 LastWriteTime 是否 < 10min stale.

    PersistentScheduler 默认 5min cycle, 10min = 2x cycle 容忍 (Windows fs flush
    + Beat 偶发 cycle 抖动). > 10min stale 视为 zombie/dead 进程, 即使服务 RUNNING.

    Why dual check: Windows service 状态可能假阳性 — Beat 进程崩溃后 Servy 自动
    restart 可能成功但 Beat scheduler thread 死锁不写 .dat 文件. 真正的 alive
    判定需要 .dat freshness.

    Returns:
        BeatHeartbeatCheck. ``fresh`` False 即 Beat 实质死亡.
    """
    if not BEAT_SCHEDULE_FILE.exists():
        return BeatHeartbeatCheck(
            file_exists=False, age_seconds=None, last_write_iso=None, fresh=False
        )

    try:
        stat = BEAT_SCHEDULE_FILE.stat()
    except OSError as e:
        logger.warning("无法 stat %s: %s", BEAT_SCHEDULE_FILE, e)
        return BeatHeartbeatCheck(
            file_exists=True, age_seconds=None, last_write_iso=None, fresh=False
        )

    last_write = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    now = datetime.now(UTC)
    age = (now - last_write).total_seconds()
    return BeatHeartbeatCheck(
        file_exists=True,
        age_seconds=age,
        last_write_iso=last_write.isoformat(),
        fresh=age <= BEAT_HEARTBEAT_MAX_AGE_SECONDS,
    )


# ─── Report build ──────────────────────────────────────────────────────────


def check_redis_freshness() -> list[RedisFreshnessCheck]:
    """LL-081 PR-X3: Redis 应用层 freshness probe (zombie 模式兜底).

    检查 2 关键 keys:
      1. portfolio:nav (JSON, updated_at 字段) — QMTData sync_loop 60s 写, > 5min 视为 stale
      2. qm:qmt:status (stream, last event ms timestamp) — connect 边沿 publish, > 30min stale

    Redis 不可达时全 stale (fail-loud). socket_timeout 防本 health check 自己 hang.
    跟 PR-X1 SETEX heartbeat 协同: PR-X1 修 root cause (TTL), 本 probe 兜底 defense-in-depth.
    """
    checks: list[RedisFreshnessCheck] = []
    # reviewer code LOW + python P2-1 采纳: ImportError 跟 ConnectionError 区分 +
    # sys.path BACKEND_DIR 已 module-top 加 (line 108-109), 函数内 redundant 移除.
    # ImportError 单独 catch, log 不同消息防误导排查 (Redis 不可达 vs redis-py 缺失).
    try:
        import redis  # noqa: PLC0415

        from app.config import settings  # noqa: PLC0415
    except ImportError as e:
        logger.warning("redis-py 或 app.config 导入失败 (非 Redis 不可达): %s", e)
        for key, threshold in (
            ("portfolio:nav", PORTFOLIO_NAV_MAX_AGE_SECONDS),
            ("qm:qmt:status", QMT_STATUS_STREAM_MAX_AGE_SECONDS),
        ):
            checks.append(
                RedisFreshnessCheck(
                    key=key,
                    found=False,
                    age_seconds=None,
                    threshold_seconds=threshold,
                    reason=f"import 失败: {e!s:.80s}",
                )
            )
        return checks

    try:
        r = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=REDIS_PROBE_TIMEOUT_SECONDS,
            # reviewer code HIGH-1 采纳: socket_connect_timeout 必设 (socket_timeout 仅
            # 命令读写超时, 连接建立默认 20-75s, 防 health check 自己 hang on TCP SYN).
            socket_connect_timeout=REDIS_PROBE_TIMEOUT_SECONDS,
        )

        # Check 1: portfolio:nav updated_at
        try:
            nav_raw = r.get("portfolio:nav")
            if not nav_raw:
                checks.append(
                    RedisFreshnessCheck(
                        key="portfolio:nav",
                        found=False,
                        age_seconds=None,
                        threshold_seconds=PORTFOLIO_NAV_MAX_AGE_SECONDS,
                        reason="key 不存在 (QMTData 未运行 OR LL-081 SETEX expire)",
                    )
                )
            else:
                nav_data = json.loads(nav_raw)
                updated_at = nav_data.get("updated_at")
                if not updated_at:
                    checks.append(
                        RedisFreshnessCheck(
                            key="portfolio:nav",
                            found=True,
                            age_seconds=None,
                            threshold_seconds=PORTFOLIO_NAV_MAX_AGE_SECONDS,
                            reason="updated_at 字段缺失 (schema 异常)",
                        )
                    )
                else:
                    dt = datetime.fromisoformat(updated_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    age = (datetime.now(UTC) - dt).total_seconds()
                    age_min = age / 60.0
                    is_stale = age > PORTFOLIO_NAV_MAX_AGE_SECONDS
                    checks.append(
                        RedisFreshnessCheck(
                            key="portfolio:nav",
                            found=True,
                            age_seconds=age,
                            threshold_seconds=PORTFOLIO_NAV_MAX_AGE_SECONDS,
                            reason=(
                                f"age {age_min:.1f}min "
                                + ("STALE (zombie 风险)" if is_stale else "ok")
                            ),
                        )
                    )
        except Exception as e:  # noqa: BLE001
            checks.append(
                RedisFreshnessCheck(
                    key="portfolio:nav",
                    found=False,
                    age_seconds=None,
                    threshold_seconds=PORTFOLIO_NAV_MAX_AGE_SECONDS,
                    reason=f"probe 异常: {e!s:.80s}",
                )
            )

        # Check 2: qm:qmt:status stream last event
        # PR-X3 reviewer MEDIUM-2 follow-up: 非交易时段 stream stale 是 expected (connect 边沿事件
        # 不持续), 降级 is_failure_alertable=False 防钉钉噪声 (zombie 仅在交易时段实际危险).
        is_trading = _is_trading_hours_now()
        try:
            events = r.xrevrange("qm:qmt:status", count=1)
            if not events:
                checks.append(
                    RedisFreshnessCheck(
                        key="qm:qmt:status",
                        found=False,
                        age_seconds=None,
                        threshold_seconds=QMT_STATUS_STREAM_MAX_AGE_SECONDS,
                        reason="stream 空 (QMT 从未连接)",
                        is_failure_alertable=is_trading,
                    )
                )
            else:
                event_id = events[0][0]  # "<ms>-<seq>"
                ms_str = event_id.split("-")[0]
                ms = int(ms_str)
                age = max(0.0, time.time() - ms / 1000)
                age_min = age / 60.0
                is_stale = age > QMT_STATUS_STREAM_MAX_AGE_SECONDS
                trading_suffix = "" if is_trading else " [非交易时段, INFO only]"
                checks.append(
                    RedisFreshnessCheck(
                        key="qm:qmt:status",
                        found=True,
                        age_seconds=age,
                        threshold_seconds=QMT_STATUS_STREAM_MAX_AGE_SECONDS,
                        reason=(
                            f"last event {age_min:.1f}min ago "
                            + ("STALE (zombie 风险)" if is_stale else "ok")
                            + trading_suffix
                        ),
                        is_failure_alertable=is_trading,
                    )
                )
        except Exception as e:  # noqa: BLE001
            checks.append(
                RedisFreshnessCheck(
                    key="qm:qmt:status",
                    found=False,
                    age_seconds=None,
                    threshold_seconds=QMT_STATUS_STREAM_MAX_AGE_SECONDS,
                    reason=f"probe 异常: {e!s:.80s}",
                    is_failure_alertable=is_trading,
                )
            )

    except Exception as e:  # noqa: BLE001 — Redis 完全不可达 (fail-loud)
        logger.warning("Redis 完全不可达, freshness probe 全 stale: %s", e)
        for key, threshold in (
            ("portfolio:nav", PORTFOLIO_NAV_MAX_AGE_SECONDS),
            ("qm:qmt:status", QMT_STATUS_STREAM_MAX_AGE_SECONDS),
        ):
            checks.append(
                RedisFreshnessCheck(
                    key=key,
                    found=False,
                    age_seconds=None,
                    threshold_seconds=threshold,
                    reason=f"Redis 不可达: {e!s:.80s}",
                )
            )

    return checks


def build_report() -> HealthReport:
    """运行全部 checks 聚合 HealthReport."""
    services = [query_service_state(name) for name in SERVY_SERVICES]
    beat = check_beat_heartbeat()
    redis_checks = check_redis_freshness()  # LL-081 PR-X3 兜底

    failures: list[str] = []
    for svc in services:
        if not svc.running:
            failures.append(f"service:{svc.name}={svc.state_text}")

    if not beat.file_exists:
        failures.append(f"beat:schedule.dat missing at {BEAT_SCHEDULE_FILE}")
    elif not beat.fresh:
        age_min = (beat.age_seconds or 0) / 60.0
        failures.append(
            f"beat:heartbeat stale {age_min:.1f}min "
            f"(threshold {BEAT_HEARTBEAT_MAX_AGE_SECONDS / 60:.0f}min)"
        )

    # LL-081 PR-X3: Redis freshness probe (zombie 模式应用层兜底)
    # PR-X3 reviewer MEDIUM-2 follow-up: 仅 alertable stale 入 failures, 非交易时段
    # stream stale (is_failure_alertable=False) 仍 visible in redis_freshness 但不告警.
    for rc in redis_checks:
        if rc.stale and rc.is_failure_alertable:
            failures.append(f"redis:{rc.key} STALE ({rc.reason})")

    return HealthReport(
        timestamp_utc=datetime.now(UTC).isoformat(),
        services=services,
        beat_heartbeat=beat,
        redis_freshness=redis_checks,
        failures=failures,
    )


# ─── Dedup state ───────────────────────────────────────────────────────────


def load_state() -> dict[str, Any]:
    """读 state 文件. 不存在或损坏返 {}, 不 raise (首次 run 必须能跑)."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("state 文件读取失败 (将视为首次 run): %s", e)
        return {}


def save_state(state: dict[str, Any]) -> None:
    """写 state 文件. 失败仅 log warn 不 raise (告警是核心, dedup 是 nice-to-have)."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as e:  # silent_ok: dedup state 丢失可接受, 告警是 critical path
        # (next run 不知 dedup, 1 次 false-positive 告警 vs 永久失去 dedup ratchet
        # 选前者). reviewer python-P2 标注 fix.
        logger.warning("state 文件写入失败 (告警仍发, dedup 失效): %s", e)


def should_alert(report: HealthReport, state: dict[str, Any]) -> tuple[bool, str]:
    """判定是否发钉钉.

    规则:
    - 当前 ok: 不发. 但若上次是 degraded → 发 "recovery" 通知 (one-shot)
    - 当前 degraded:
      - 上次 ok → 发 (transition ok→degraded)
      - 上次也 degraded:
        - failures set 变化 → 发 (escalation/change)
        - failures 相同:
          - 距上次发送 > 1h → 发 (re-alert, 防首条 miss)
          - 距上次 ≤ 1h → silent (dedup)

    Returns:
        (should_send, reason): bool + 触发原因 (用于 log + 钉钉 body context)
    """
    last_status = state.get("last_status")
    last_failures = sorted(state.get("last_failures") or [])
    last_alert_iso = state.get("last_alert_time")
    current_failures = sorted(report.failures)

    # Recovery transition
    if report.status == "ok":
        if last_status == "degraded":
            return True, "recovery (degraded → ok)"
        return False, "still ok"

    # Currently degraded
    if last_status != "degraded":
        return True, "transition (ok → degraded)"

    if current_failures != last_failures:
        return True, "failures changed (escalation)"

    # Same failures, check dedup window
    if last_alert_iso is None:
        return True, "no prior alert timestamp"

    try:
        last_alert = datetime.fromisoformat(last_alert_iso)
    except ValueError:
        return True, "prior alert timestamp unparseable"

    if last_alert.tzinfo is None:
        last_alert = last_alert.replace(tzinfo=UTC)

    elapsed = (datetime.now(UTC) - last_alert).total_seconds()
    if elapsed > DEDUP_WINDOW_SECONDS:
        return True, f"re-alert after {elapsed / 60:.0f}min (>1h dedup window)"

    return False, f"dedup ({elapsed / 60:.0f}min < 60min, same failures)"


def update_state(report: HealthReport, sent_alert: bool) -> dict[str, Any]:
    """构造下一次的 state dict (caller 调 save_state 持久化)."""
    state: dict[str, Any] = {
        "last_status": report.status,
        "last_failures": list(report.failures),
        "last_check_time": report.timestamp_utc,
    }
    if sent_alert:
        state["last_alert_time"] = report.timestamp_utc
    return state


# ─── Alert ─────────────────────────────────────────────────────────────────


def send_alert(report: HealthReport, reason: str) -> bool:
    """发钉钉 P0 告警.

    Returns:
        True 钉钉返成功, False 失败 (但不 raise — 告警失败不阻断脚本退出码)
    """
    try:
        from app.config import settings
        from app.services.dispatchers.dingtalk import send_markdown_sync
    except ImportError as e:
        logger.error("无法导入钉钉模块: %s (可能 backend 未在 sys.path)", e)
        return False

    if not settings.DINGTALK_WEBHOOK_URL:
        logger.warning("DINGTALK_WEBHOOK_URL 未配置, 仅 log 不发送")
        return False

    # 构造 markdown body
    if report.status == "ok":
        title = "✅ Services Recovered"
        emoji = "✅"
    else:
        title = "🚨 Services Health DEGRADED (LL-074)"
        emoji = "🚨"

    services_lines = []
    for svc in report.services:
        ok_mark = "✅" if svc.running else "❌"
        services_lines.append(f"- {ok_mark} **{svc.name}**: {svc.state_text}")

    beat = report.beat_heartbeat
    if beat:
        if beat.fresh:
            beat_line = (
                f"- ✅ **CeleryBeat heartbeat**: "
                f"{(beat.age_seconds or 0) / 60:.1f}min ago (last write: "
                f"{_to_cst_display(beat.last_write_iso)})"
            )
        elif not beat.file_exists:
            beat_line = "- ❌ **CeleryBeat heartbeat**: schedule.dat MISSING"
        else:
            beat_line = (
                f"- ❌ **CeleryBeat heartbeat**: STALE "
                f"{(beat.age_seconds or 0) / 60:.1f}min "
                f"(threshold {BEAT_HEARTBEAT_MAX_AGE_SECONDS / 60:.0f}min, "
                f"last write: {_to_cst_display(beat.last_write_iso)})"
            )
    else:
        beat_line = "- ⚠️ **CeleryBeat heartbeat**: not checked"

    # LL-081 PR-X3: Redis 应用层 freshness probe (zombie 模式兜底告警)
    redis_lines = []
    for rc in report.redis_freshness:
        ok_mark = "✅" if not rc.stale else "❌"
        redis_lines.append(f"- {ok_mark} **redis:{rc.key}**: {rc.reason}")
    redis_block = "\n".join(redis_lines) if redis_lines else "- ⚠️ Redis probe 未执行"

    failures_text = "\n".join(f"- {f}" for f in report.failures) if report.failures else "无"

    content = (
        f"## {emoji} {title}\n\n"
        f"**触发原因**: {reason}\n\n"
        f"**时间**: {_to_cst_display(report.timestamp_utc)}\n\n"
        f"### 服务状态\n{chr(10).join(services_lines)}\n\n"
        f"### Beat 心跳\n{beat_line}\n\n"
        f"### Redis Freshness (LL-081 PR-X3)\n{redis_block}\n\n"
        f"### 失败项 ({len(report.failures)})\n{failures_text}\n\n"
        f"> 来源: services_healthcheck (LL-074 + LL-081, Session 38)\n"
        f"> Monday 4-27 真生产首日 zombie 4h17m 教训, 加 Redis 应用层 freshness probe"
    )

    try:
        ok = send_markdown_sync(
            webhook_url=settings.DINGTALK_WEBHOOK_URL,
            title=f"[P0] {title}",
            content=content,
            secret=settings.DINGTALK_SECRET,
            keyword=settings.DINGTALK_KEYWORD,
        )
    except Exception as e:  # silent_ok: alert send failure 不阻断 schtask exit-code
        # 路径 — logger.error 持久化原因, 下次 run 仍重试 (见 should_alert dedup
        # window: last_alert_time 仅在 sent=True 时写入, send 失败下次仍命中
        # "no prior alert timestamp" 路径强制重试)
        logger.error("钉钉发送异常: %s", e)
        return False

    if ok:
        logger.info("钉钉告警发送成功: %s", title)
    else:
        logger.warning("钉钉发送返回失败 (webhook 可能未配置或被限流)")
    return bool(ok)


# ─── Main flow ─────────────────────────────────────────────────────────────


def _run() -> int:
    """主 logic. 顶层 try/except 由 main() 包裹.

    Returns:
        0: 全部 ok (recovery transition 已发送时仍返 0 因为目前状态是 ok)
        1: degraded (含 alert 已发 + dedup window 内 silent 两种, schtask 见非 0)
        2: 仅 main() 顶层 except 路径返回 — 未捕获 fatal exception (铁律 43 d)

    Note:
        原 docstring 误标 "2 = degraded + alert sent" 与代码 `return 1` 实现冲突
        (reviewer python-P1 fix Session 35). 实际 schtask LastResult 任意非 0 都
        触发钉钉告警链, 故 1 vs 2 区分仅给上层包装脚本判断 "可恢复 vs unrecoverable".
    """
    logger.info("=" * 60)
    logger.info("ServicesHealthCheck 启动 (LL-074, Session 35)")
    logger.info("=" * 60)

    report = build_report()

    # Log report summary
    logger.info("Status: %s", report.status)
    for svc in report.services:
        level = logging.INFO if svc.running else logging.ERROR
        logger.log(level, "  %s: %s", svc.name, svc.state_text)
    if report.beat_heartbeat:
        b = report.beat_heartbeat
        if b.file_exists and b.fresh:
            logger.info("  Beat heartbeat: %.1fmin ago (fresh)", (b.age_seconds or 0) / 60)
        elif b.file_exists:
            logger.error("  Beat heartbeat: %.1fmin ago (STALE)", (b.age_seconds or 0) / 60)
        else:
            logger.error("  Beat heartbeat: schedule.dat MISSING")

    state = load_state()
    should_send, reason = should_alert(report, state)
    logger.info("Alert decision: send=%s reason=%s", should_send, reason)

    sent = False
    if should_send:
        sent = send_alert(report, reason)

    new_state = update_state(report, sent_alert=sent)
    save_state(new_state)

    if report.status == "ok":
        logger.info("ServicesHealthCheck: ALL OK")
        return 0
    if not should_send:
        logger.warning("ServicesHealthCheck: DEGRADED (silent dedup): %s", report.failures)
        return 1
    logger.error("ServicesHealthCheck: DEGRADED + ALERTED: %s", report.failures)
    return 1  # not 2: 2 is reserved for fatal exceptions (铁律 43 d)


def main() -> int:
    """CLI entrypoint. 铁律 43 (b)(c)(d):
    - boot stderr probe (schtask 最早启动证据)
    - 顶层 try/except → stderr FATAL + exit(2) 触发 schtask 钉钉告警链
    """
    print(
        f"[services_healthcheck] boot {datetime.now().isoformat()} pid={os.getpid()}",
        flush=True,
        file=sys.stderr,
    )
    try:
        return _run()
    except Exception as e:
        msg = f"[services_healthcheck] FATAL: {type(e).__name__}: {e}"
        print(msg, flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # silent_ok: 最外层兜底, logger 可能未初始化成功
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
