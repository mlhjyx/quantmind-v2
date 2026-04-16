#!/usr/bin/env python3
"""全链路端到端系统诊断脚本。

6层诊断: 数据层→信号链路→执行链路→调度与基础设施→配置一致性→静默失败。
每项检查返回 PASS / WARN / FAIL + detail。

用法:
    python scripts/system_diagnosis.py                 # 全量诊断
    python scripts/system_diagnosis.py --layer data    # 只跑数据层
    python scripts/system_diagnosis.py --json          # 输出JSON报告
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.services.price_utils import _get_sync_conn

# ════════════════════════════════════════════════════════════
# Result collector
# ════════════════════════════════════════════════════════════


class DiagResult:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, layer: str, name: str, status: str, detail: str):
        """status: PASS / WARN / FAIL"""
        self.checks.append(
            {
                "layer": layer,
                "name": name,
                "status": status,
                "detail": detail,
            }
        )
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status, "?")
        print(f"  {icon} [{layer}] {name}: {detail}", flush=True)

    def summary(self) -> dict:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        warned = sum(1 for c in self.checks if c["status"] == "WARN")
        failed = sum(1 for c in self.checks if c["status"] == "FAIL")
        return {"total": total, "passed": passed, "warned": warned, "failed": failed}

    def to_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "checks": self.checks,
            "timestamp": datetime.now().isoformat(),
        }


# ════════════════════════════════════════════════════════════
# Layer 1: Data Integrity
# ════════════════════════════════════════════════════════════


def diag_data(conn, result: DiagResult, trade_date: date):
    layer = "data"

    cur = conn.cursor()

    # 1.1 klines vs stock_status coverage (recent 10 trading days)
    cur.execute(
        """
        SELECT k.trade_date,
               COUNT(DISTINCT k.code) as klines_codes,
               COUNT(DISTINCT ss.code) as status_codes
        FROM klines_daily k
        LEFT JOIN stock_status_daily ss ON k.code=ss.code AND k.trade_date=ss.trade_date
        WHERE k.trade_date >= %s - INTERVAL '14 days'
          AND k.volume > 0
        GROUP BY k.trade_date
        ORDER BY k.trade_date DESC
        LIMIT 10
    """,
        (trade_date,),
    )
    gaps = []
    for td, kc, sc in cur.fetchall():
        ratio = sc / kc if kc > 0 else 0
        if ratio < 0.95:
            gaps.append(f"{td}: {sc}/{kc}={ratio:.1%}")
    if gaps:
        result.add(
            layer,
            "klines_vs_status_coverage",
            "FAIL",
            f"{len(gaps)}天覆盖率<95%: {'; '.join(gaps[:3])}",
        )
    else:
        result.add(layer, "klines_vs_status_coverage", "PASS", "最近10天全部>=95%")

    # 1.2 Data freshness (multiple tables)
    cur.execute(
        """
        SELECT MAX(trade_date) FROM trading_calendar
        WHERE market = 'astock' AND is_trading_day = TRUE AND trade_date < %s
    """,
        (trade_date,),
    )
    prev_td = cur.fetchone()[0]

    tables_to_check = [
        ("klines_daily", "SELECT MAX(trade_date) FROM klines_daily"),
        ("daily_basic", "SELECT MAX(trade_date) FROM daily_basic"),
        ("stock_status_daily", "SELECT MAX(trade_date) FROM stock_status_daily"),
        ("index_daily_300", "SELECT MAX(trade_date) FROM index_daily WHERE index_code='000300.SH'"),
    ]
    for tbl_name, sql in tables_to_check:
        cur.execute(sql)
        max_dt = cur.fetchone()[0]
        if max_dt is None:
            result.add(layer, f"freshness_{tbl_name}", "FAIL", "表为空")
        elif prev_td and max_dt < prev_td:
            result.add(layer, f"freshness_{tbl_name}", "FAIL", f"最新={max_dt}, 期望>={prev_td}")
        else:
            result.add(layer, f"freshness_{tbl_name}", "PASS", f"最新={max_dt}")

    # 1.3 CORE4 factor freshness
    # F71 fix (Phase E 2026-04-16): 从 PAPER_TRADING_CONFIG 读取, 不再硬编码
    from engines.signal_engine import PAPER_TRADING_CONFIG

    core4 = tuple(PAPER_TRADING_CONFIG.factor_names)
    for fname in core4:
        cur.execute(
            """
            SELECT MAX(trade_date) FROM factor_values
            WHERE factor_name = %s AND trade_date <= %s
        """,
            (fname, trade_date),
        )
        fdt = cur.fetchone()[0]
        if fdt is None:
            result.add(layer, f"factor_fresh_{fname}", "FAIL", "无数据")
        elif prev_td and fdt < prev_td:
            result.add(layer, f"factor_fresh_{fname}", "FAIL", f"最新={fdt}, 期望>={prev_td}")
        else:
            result.add(layer, f"factor_fresh_{fname}", "PASS", f"最新={fdt}")

    # 1.4 Float NaN detection (铁律29)
    cur.execute("""
        SELECT factor_name, COUNT(*) FROM factor_values
        WHERE neutral_value = 'NaN'::float OR raw_value = 'NaN'::float
        GROUP BY factor_name
    """)
    nan_rows = cur.fetchall()
    if nan_rows:
        # CORE4 NaN = FAIL, 其他因子 = WARN
        core4_nan = [(fn, cnt) for fn, cnt in nan_rows if fn in core4]
        other_nan = [(fn, cnt) for fn, cnt in nan_rows if fn not in core4]
        if core4_nan:
            detail = "; ".join(f"{fn}:{cnt}" for fn, cnt in core4_nan)
            result.add(layer, "float_nan_core4", "FAIL", f"CORE4 float NaN: {detail}")
        if other_nan:
            detail = "; ".join(f"{fn}:{cnt}" for fn, cnt in other_nan[:5])
            result.add(layer, "float_nan_others", "WARN", f"非CORE因子float NaN(少量): {detail}")
        if not core4_nan and not other_nan:
            result.add(layer, "float_nan_check", "PASS", "无float NaN")
    else:
        result.add(layer, "float_nan_check", "PASS", "无float NaN")

    # 1.5 adj_factor=0 (除零风险)
    cur.execute("""
        SELECT COUNT(DISTINCT code) FROM (
            SELECT DISTINCT ON (code) code, adj_factor
            FROM klines_daily WHERE adj_factor IS NOT NULL
            ORDER BY code, trade_date DESC
        ) t WHERE adj_factor = 0
    """)
    zero_adj = cur.fetchone()[0]
    if zero_adj > 0:
        result.add(
            layer, "adj_factor_zero", "FAIL", f"{zero_adj}个code的latest_adj_factor=0(除零风险)"
        )
    else:
        result.add(layer, "adj_factor_zero", "PASS", "无adj_factor=0")

    # 1.6 Parquet cache consistency
    cache_meta_path = Path("cache/backtest/cache_meta.json")
    if cache_meta_path.exists():
        with open(cache_meta_path) as f:
            meta = json.load(f)
        cache_build = meta.get("build_date", "")[:10]
        cache_factors = set(meta.get("factors", []))
        yaml_factors = set(core4)

        if cache_factors != yaml_factors:
            result.add(
                layer,
                "parquet_cache_factors",
                "FAIL",
                f"缓存因子={cache_factors}, YAML因子={yaml_factors}",
            )
        else:
            result.add(layer, "parquet_cache_factors", "PASS", f"因子一致: {cache_factors}")

        # Compare build_date vs DB latest factor update
        if prev_td and cache_build < str(prev_td):
            result.add(
                layer,
                "parquet_cache_freshness",
                "WARN",
                f"缓存build={cache_build}, DB最新交易日={prev_td}",
            )
        else:
            result.add(layer, "parquet_cache_freshness", "PASS", f"build={cache_build}")
    else:
        result.add(layer, "parquet_cache_factors", "FAIL", "cache_meta.json不存在")
        result.add(layer, "parquet_cache_freshness", "FAIL", "cache_meta.json不存在")

    # 1.7 CORE4 factor coverage on latest date
    cur.execute(
        """
        SELECT fv.factor_name, COUNT(*) as fv_count
        FROM factor_values fv
        WHERE fv.factor_name IN %s AND fv.trade_date = %s
          AND fv.neutral_value IS NOT NULL
        GROUP BY fv.factor_name
    """,
        (core4, prev_td or trade_date),
    )
    fv_counts = {row[0]: row[1] for row in cur.fetchall()}
    for fname in core4:
        cnt = fv_counts.get(fname, 0)
        if cnt < 3000:
            result.add(
                layer,
                f"factor_coverage_{fname}",
                "FAIL",
                f"date={prev_td}, neutral_value仅{cnt}行(<3000)",
            )
        else:
            result.add(layer, f"factor_coverage_{fname}", "PASS", f"date={prev_td}, {cnt}行")


# ════════════════════════════════════════════════════════════
# Layer 2: Signal Path
# ════════════════════════════════════════════════════════════


def diag_signal(conn, result: DiagResult, trade_date: date):
    layer = "signal"
    cur = conn.cursor()
    try:
        strategy_id = str(settings.PAPER_STRATEGY_ID)
    except Exception:
        strategy_id = None

    # 2.1 Universe filter verification (INNER JOIN check via code)
    # Import load_universe from run_backtest (script, not package)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_backtest", Path(__file__).parent / "run_backtest.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    load_universe = mod.load_universe
    universe = load_universe(trade_date, conn)
    u_size = len(universe)
    if u_size == 0:
        result.add(layer, "universe_size", "FAIL", f"空universe (date={trade_date})")
    elif u_size < 4000:
        result.add(layer, "universe_size", "WARN", f"{u_size}只(<4000, 可能数据不全)")
    else:
        result.add(layer, "universe_size", "PASS", f"{u_size}只")

    # 2.2 No BJ stocks in universe
    bj_in = [c for c in universe if c.endswith(".BJ")]
    if bj_in:
        result.add(layer, "no_bj_in_universe", "FAIL", f"{len(bj_in)}只BJ股: {bj_in[:3]}")
    else:
        result.add(layer, "no_bj_in_universe", "PASS", "无BJ股")

    # 2.3 No ST stocks in universe
    if universe:
        cur.execute(
            """
            SELECT MAX(trade_date) FROM stock_status_daily WHERE trade_date <= %s
        """,
            (trade_date,),
        )
        status_dt = cur.fetchone()[0]
        if status_dt:
            codes_tuple = tuple(universe)
            cur.execute(
                """
                SELECT code FROM stock_status_daily
                WHERE trade_date = %s AND code IN %s AND is_st = TRUE
            """,
                (status_dt, codes_tuple),
            )
            st_in = [r[0] for r in cur.fetchall()]
            if st_in:
                result.add(layer, "no_st_in_universe", "FAIL", f"{len(st_in)}只ST股: {st_in[:5]}")
            else:
                result.add(layer, "no_st_in_universe", "PASS", "无ST股")
        else:
            result.add(layer, "no_st_in_universe", "WARN", "无stock_status数据可验证")
    else:
        result.add(layer, "no_st_in_universe", "WARN", "universe为空, 跳过")

    # 2.4 Config consistency: pt_live.yaml vs PAPER_TRADING_CONFIG
    try:
        import yaml

        yaml_path = Path("configs/pt_live.yaml")
        if yaml_path.exists():
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
            yaml_factors = {item["name"] for item in cfg["strategy"]["factors"]}

            from engines.signal_engine import PAPER_TRADING_CONFIG

            code_factors = set(PAPER_TRADING_CONFIG.factor_names)

            if yaml_factors != code_factors:
                result.add(
                    layer,
                    "config_factors_match",
                    "FAIL",
                    f"YAML={yaml_factors}, CODE={code_factors}",
                )
            else:
                result.add(layer, "config_factors_match", "PASS", f"一致: {yaml_factors}")
        else:
            result.add(layer, "config_factors_match", "WARN", "pt_live.yaml不存在")
    except Exception as e:
        result.add(layer, "config_factors_match", "WARN", f"检查异常: {e}")

    # 2.5 Latest signals sanity check
    sig_query_params = ()
    if strategy_id:
        sig_sql = """
            SELECT trade_date, COUNT(*), COUNT(DISTINCT code)
            FROM signals WHERE strategy_id = %s
            GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1
        """
        sig_query_params = (strategy_id,)
    else:
        sig_sql = """
            SELECT trade_date, COUNT(*), COUNT(DISTINCT code)
            FROM signals
            GROUP BY trade_date ORDER BY trade_date DESC LIMIT 1
        """
    cur.execute(sig_sql, sig_query_params)
    sig_row = cur.fetchone()
    if sig_row:
        sig_dt, sig_cnt, sig_codes = sig_row
        if sig_codes < 5:
            result.add(layer, "latest_signals", "WARN", f"date={sig_dt}, 仅{sig_codes}只(过少)")
        else:
            result.add(layer, "latest_signals", "PASS", f"date={sig_dt}, {sig_codes}只")
    else:
        result.add(layer, "latest_signals", "WARN", "signals表为空")


# ════════════════════════════════════════════════════════════
# Layer 3: Execution Path
# ════════════════════════════════════════════════════════════


def diag_execution(conn, result: DiagResult, trade_date: date):
    layer = "execution"
    cur = conn.cursor()

    # Get strategy_id from settings
    try:
        strategy_id = str(settings.PAPER_STRATEGY_ID)
    except Exception:
        strategy_id = None

    # 3.1 Position snapshot integrity
    try:
        if strategy_id:
            cur.execute(
                """
                SELECT trade_date, COUNT(*), SUM(weight)
                FROM position_snapshot
                WHERE strategy_id = %s
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 1
            """,
                (strategy_id,),
            )
        else:
            cur.execute("""
                SELECT trade_date, COUNT(*), SUM(weight)
                FROM position_snapshot
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT 1
            """)
        ps_row = cur.fetchone()
        if ps_row:
            ps_dt, ps_cnt, ps_wsum = ps_row
            ps_wsum = float(ps_wsum) if ps_wsum else 0
            if ps_cnt == 0:
                result.add(layer, "position_snapshot", "FAIL", f"date={ps_dt}, 空快照")
            elif ps_wsum > 1.1:
                result.add(
                    layer,
                    "position_snapshot",
                    "WARN",
                    f"date={ps_dt}, {ps_cnt}只, 权重和={ps_wsum:.3f}(>1.1)",
                )
            else:
                result.add(
                    layer,
                    "position_snapshot",
                    "PASS",
                    f"date={ps_dt}, {ps_cnt}只, 权重和={ps_wsum:.3f}",
                )
        else:
            result.add(layer, "position_snapshot", "WARN", "position_snapshot为空")
    except Exception as e:
        conn.rollback()
        result.add(layer, "position_snapshot", "WARN", f"查询异常: {e}")

    # 3.2 Orphaned pending orders
    try:
        cur.execute("""
            SELECT COUNT(*) FROM pending_orders
            WHERE status = 'pending' AND created_at < NOW() - INTERVAL '2 days'
        """)
        orphaned = cur.fetchone()[0]
        if orphaned > 0:
            result.add(
                layer, "orphaned_pending_orders", "WARN", f"{orphaned}个过期pending订单(>2天)"
            )
        else:
            result.add(layer, "orphaned_pending_orders", "PASS", "无过期pending订单")
    except Exception as e:
        conn.rollback()
        result.add(layer, "orphaned_pending_orders", "WARN", f"查询异常(表可能不存在): {e}")

    # 3.3 Performance series continuity
    try:
        if strategy_id:
            cur.execute(
                """
                SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
                FROM performance_series
                WHERE strategy_id = %s
            """,
                (strategy_id,),
            )
        else:
            cur.execute("""
                SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
                FROM performance_series
            """)
        perf_row = cur.fetchone()
        if perf_row and perf_row[0] > 0:
            perf_cnt, perf_min, perf_max = perf_row
            result.add(layer, "performance_series", "PASS", f"{perf_cnt}天, {perf_min}~{perf_max}")
        else:
            result.add(layer, "performance_series", "WARN", "performance_series为空")
    except Exception as e:
        conn.rollback()
        result.add(layer, "performance_series", "WARN", f"查询异常: {e}")

    # 3.4 Risk control state
    try:
        cur.execute("""
            SELECT current_level, updated_at FROM circuit_breaker_state
            ORDER BY updated_at DESC LIMIT 1
        """)
        cb_row = cur.fetchone()
        if cb_row:
            cb_level, cb_updated = cb_row
            if cb_level >= 3:
                result.add(layer, "circuit_breaker", "WARN", f"L{cb_level} (updated={cb_updated})")
            else:
                result.add(layer, "circuit_breaker", "PASS", f"L{cb_level} (updated={cb_updated})")
        else:
            result.add(layer, "circuit_breaker", "PASS", "无熔断记录(正常)")
    except Exception as e:
        conn.rollback()
        result.add(layer, "circuit_breaker", "WARN", f"查询异常: {e}")


# ════════════════════════════════════════════════════════════
# Layer 4: Scheduling & Infrastructure
# ════════════════════════════════════════════════════════════


def diag_infra(conn, result: DiagResult):
    layer = "infra"

    # 4.1 Redis connectivity
    try:
        import redis

        r = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=3,
        )
        r.ping()
        used_mb = r.info("memory").get("used_memory", 0) / (1024 * 1024)
        result.add(layer, "redis", "PASS", f"连接正常, 内存{used_mb:.1f}MB")

        # 4.1.1 portfolio:current TTL check
        ttl = r.ttl("portfolio:current")
        ptype = r.type("portfolio:current").decode()
        if ptype == "none":
            result.add(layer, "redis_portfolio_ttl", "WARN", "portfolio:current不存在")
        elif ttl == -1:
            result.add(
                layer,
                "redis_portfolio_ttl",
                "WARN",
                "portfolio:current无TTL(QMT停止后数据永不过期)",
            )
        else:
            result.add(layer, "redis_portfolio_ttl", "PASS", f"TTL={ttl}s")

        # 4.1.2 StreamBus events check
        streams = ["qm:signal:generated", "qm:execution:completed"]
        for stream in streams:
            slen = r.xlen(stream) if r.exists(stream) else 0
            if slen == 0:
                result.add(
                    layer,
                    f"stream_{stream.split(':')[-1]}",
                    "WARN",
                    f"{stream} 长度=0(可能从未发送)",
                )
            else:
                result.add(
                    layer, f"stream_{stream.split(':')[-1]}", "PASS", f"{stream} 长度={slen}"
                )

    except ImportError:
        result.add(layer, "redis", "WARN", "redis包未安装")
    except Exception as e:
        result.add(layer, "redis", "FAIL", str(e))

    # 4.2 Disk space
    import shutil

    usage = shutil.disk_usage("D:\\")
    free_gb = usage.free / (1024**3)
    if free_gb < 10:
        result.add(layer, "disk_space", "FAIL", f"{free_gb:.1f}GB(<10GB)")
    elif free_gb < 50:
        result.add(layer, "disk_space", "WARN", f"{free_gb:.1f}GB(<50GB)")
    else:
        result.add(layer, "disk_space", "PASS", f"{free_gb:.1f}GB")

    # 4.3 Log freshness
    log_dir = Path("logs")
    if log_dir.exists():
        for log_name in ["fastapi-stdout.log", "celery-stdout.log"]:
            log_path = log_dir / log_name
            if log_path.exists():
                age_sec = time.time() - log_path.stat().st_mtime
                age_min = age_sec / 60
                if age_min > 60:
                    result.add(
                        layer, f"log_{log_name}", "WARN", f"最后更新{age_min:.0f}分钟前(>1小时)"
                    )
                else:
                    result.add(layer, f"log_{log_name}", "PASS", f"最后更新{age_min:.0f}分钟前")
            else:
                result.add(layer, f"log_{log_name}", "WARN", "文件不存在")
    else:
        result.add(layer, "log_dir", "WARN", "logs/目录不存在")

    # 4.4 PostgreSQL connection pool
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = 'quantmind_v2'")
    active_conns = cur.fetchone()[0]
    if active_conns > 20:
        result.add(layer, "pg_connections", "WARN", f"{active_conns}个活跃连接(>20)")
    else:
        result.add(layer, "pg_connections", "PASS", f"{active_conns}个活跃连接")


# ════════════════════════════════════════════════════════════
# Layer 5: Config Consistency
# ════════════════════════════════════════════════════════════


def diag_config(result: DiagResult):
    layer = "config"

    # 5.1 .env key parameters
    from dotenv import dotenv_values

    env = dotenv_values(Path("backend/.env"))
    if not env:
        env = dotenv_values(Path(".env"))

    required_keys = {
        "PT_TOP_N": "20",
        "PT_SIZE_NEUTRAL_BETA": "0.50",
    }
    for key, expected in required_keys.items():
        val = env.get(key) or os.environ.get(key)
        if val is None:
            result.add(layer, f"env_{key}", "WARN", f"{key}未设置(将使用代码默认值)")
        elif val != expected:
            result.add(layer, f"env_{key}", "WARN", f"{key}={val}, 期望={expected}")
        else:
            result.add(layer, f"env_{key}", "PASS", f"{key}={val}")

    # 5.2 pt_live.yaml schema validation
    try:
        import yaml

        with open("configs/pt_live.yaml") as f:
            cfg = yaml.safe_load(f)
        required_sections = ["strategy", "execution", "universe", "backtest"]
        missing = [s for s in required_sections if s not in cfg]
        if missing:
            result.add(layer, "yaml_schema", "FAIL", f"缺失section: {missing}")
        else:
            result.add(layer, "yaml_schema", "PASS", "所有必须section存在")

        # Validate factor directions
        factors = cfg.get("strategy", {}).get("factors", [])
        bad_dirs = [f["name"] for f in factors if f.get("direction") not in (1, -1)]
        if bad_dirs:
            result.add(layer, "yaml_factor_directions", "FAIL", f"无效direction: {bad_dirs}")
        else:
            result.add(
                layer, "yaml_factor_directions", "PASS", f"{len(factors)}个因子direction均为±1"
            )
    except Exception as e:
        result.add(layer, "yaml_schema", "FAIL", str(e))

    # 5.3 CORE_FACTORS hardcoding scatter check
    hardcoded_files = []
    search_patterns = [
        ("backend/data/parquet_cache.py", ["CORE_FACTORS", "turnover_mean_20"]),
        ("scripts/health_check.py", ["CORE_FACTORS", "turnover_mean_20"]),
    ]
    for fpath, patterns in search_patterns:
        p = Path(fpath)
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                if pat in content:
                    hardcoded_files.append(fpath)
                    break
    if hardcoded_files:
        result.add(layer, "hardcoded_factors", "WARN", f"因子列表硬编码在: {hardcoded_files}")
    else:
        result.add(layer, "hardcoded_factors", "PASS", "无硬编码因子列表")


# ════════════════════════════════════════════════════════════
# Layer 6: Silent Failures & Monitoring Gaps
# ════════════════════════════════════════════════════════════


def diag_silent(conn, result: DiagResult):
    layer = "silent"
    cur = conn.cursor()

    # 6.1 Health check history
    cur.execute("""
        SELECT check_date, all_pass, failed_items
        FROM health_checks
        ORDER BY check_date DESC LIMIT 5
    """)
    hc_rows = cur.fetchall()
    if hc_rows:
        failed_recent = [r for r in hc_rows if not r[1]]
        if failed_recent:
            dates = [str(r[0]) for r in failed_recent]
            result.add(
                layer,
                "recent_health_fails",
                "WARN",
                f"最近5次中{len(failed_recent)}次失败: {dates}",
            )
        else:
            result.add(layer, "recent_health_fails", "PASS", "最近5次健康检查全PASS")
    else:
        result.add(layer, "recent_health_fails", "WARN", "无健康检查记录")

    # 6.2 Notification delivery
    cur.execute("""
        SELECT COUNT(*) FROM notifications
        WHERE created_at > NOW() - INTERVAL '7 days'
    """)
    notif_cnt = cur.fetchone()[0]
    result.add(
        layer,
        "recent_notifications",
        "PASS" if notif_cnt >= 0 else "WARN",
        f"最近7天{notif_cnt}条通知",
    )

    # 6.3 Code-level silent failure audit (static check)
    silent_patterns = []

    # Check StreamBus exception swallowing
    service_files = [
        "backend/app/services/execution_service.py",
        "backend/app/services/signal_service.py",
        "backend/app/services/risk_control_service.py",
    ]
    for fpath in service_files:
        p = Path(fpath)
        if p.exists():
            content = p.read_text(encoding="utf-8", errors="ignore")
            # Count "except Exception: pass" or "except Exception:\n            pass"
            import re

            swallowed = len(re.findall(r"except\s+Exception.*?:\s*\n\s*pass", content))
            if swallowed > 0:
                silent_patterns.append(f"{Path(fpath).name}: {swallowed}处except-pass")

    if silent_patterns:
        result.add(layer, "exception_swallowing", "WARN", "; ".join(silent_patterns))
    else:
        result.add(layer, "exception_swallowing", "PASS", "无发现")

    # 6.4 position_snapshot atomicity check (code audit)
    qmt_state_path = Path("backend/app/services/pt_qmt_state.py")
    if qmt_state_path.exists():
        content = qmt_state_path.read_text(encoding="utf-8", errors="ignore")
        has_delete = "DELETE FROM position_snapshot" in content
        has_begin = (
            "BEGIN" in content.upper()
            or "conn.autocommit" in content
            or "SAVEPOINT" in content.upper()
        )
        if has_delete and not has_begin:
            result.add(
                layer,
                "snapshot_atomicity",
                "WARN",
                "position_snapshot DELETE非事务包裹(crash可丢数据)",
            )
        else:
            result.add(layer, "snapshot_atomicity", "PASS", "OK")
    else:
        result.add(layer, "snapshot_atomicity", "WARN", "文件不存在")

    # 6.5 rolling_20d threshold check (verify P0 fix)
    rc_path = Path("backend/app/services/risk_control_service.py")
    if rc_path.exists():
        content = rc_path.read_text(encoding="utf-8", errors="ignore")
        import re

        # Find the rolling_20d block
        match = re.search(r"rolling_20d_loss.*?\n\s+if len\(rows\) >= (\d+):", content)
        if match:
            threshold = int(match.group(1))
            if threshold < 20:
                result.add(
                    layer,
                    "rolling_20d_threshold",
                    "FAIL",
                    f"阈值={threshold}(<20), 20日回撤会用{threshold}天数据计算",
                )
            else:
                result.add(layer, "rolling_20d_threshold", "PASS", f"阈值={threshold}")
        else:
            result.add(layer, "rolling_20d_threshold", "WARN", "未找到rolling_20d代码块")
    else:
        result.add(layer, "rolling_20d_threshold", "WARN", "文件不存在")


# ════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="QuantMind V2 全链路系统诊断")
    parser.add_argument(
        "--layer",
        choices=["data", "signal", "execution", "infra", "config", "silent"],
        help="只运行指定层",
    )
    parser.add_argument("--json", action="store_true", help="输出JSON报告到cache/")
    parser.add_argument("--date", type=str, help="诊断日期 YYYY-MM-DD")
    args = parser.parse_args()

    td = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
    conn = _get_sync_conn()
    result = DiagResult()

    print(f"\n{'=' * 60}")
    print(f"QuantMind V2 全链路诊断 — {td}")
    print(f"{'=' * 60}\n")

    t0 = time.time()

    layers = {
        "data": lambda: diag_data(conn, result, td),
        "signal": lambda: diag_signal(conn, result, td),
        "execution": lambda: diag_execution(conn, result, td),
        "infra": lambda: diag_infra(conn, result),
        "config": lambda: diag_config(result),
        "silent": lambda: diag_silent(conn, result),
    }

    for name, func in layers.items():
        if args.layer and args.layer != name:
            continue
        print(f"[Layer: {name}]")
        try:
            func()
        except Exception as e:
            result.add(name, "layer_error", "FAIL", f"层级异常: {e}")
        # Recover transaction state between layers (prevent cascade abort)
        try:
            conn.rollback()
        except Exception:
            pass
        print()

    # Summary
    s = result.summary()
    elapsed = time.time() - t0
    print(f"{'=' * 60}")
    print(
        f"诊断完成: {s['total']}项 — {s['passed']} PASS, {s['warned']} WARN, {s['failed']} FAIL ({elapsed:.1f}s)"
    )
    if s["failed"] > 0:
        print("\n❌ FAIL项:")
        for c in result.checks:
            if c["status"] == "FAIL":
                print(f"  - [{c['layer']}] {c['name']}: {c['detail']}")
    print(f"{'=' * 60}")

    # JSON output
    if args.json:
        out_path = Path("cache/diagnosis_report.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2, default=str)
        print(f"\n报告已保存: {out_path}")

    conn.close()
    sys.exit(1 if s["failed"] > 0 else 0)


if __name__ == "__main__":
    main()
