"""LLM Cost Monthly Audit — P0-16 closure (Plan v8 Master).

沿用 Plan v8 Master P0-16 (No Monthly LLM Cost Audit Aggregator) Alt 1:
    `scripts/llm_cost_monthly_audit.py` + Beat `crontab(day_of_month=1, hour=8)`
    aggregates `llm_call_log WHERE triggered_at BETWEEN last_month_start AND last_month_end`.

Designed to run:
    1. Monthly via Celery Beat `llm-cost-monthly-audit` (新 entry, batch 6)
    2. Ad-hoc via direct python invocation

Outputs:
    1. stdout: per-month + per-call_type aggregated cost
    2. Comparison vs $50 budget (sustained V3 §20.1 #6, .env LLM_MONTHLY_BUDGET_USD)
    3. DingTalk push if cost > 80% threshold OR > 100% (沿用 budget.py state machine)

Sustained:
    - 铁律 9 (并发限制基础, 单一 process 仅查询)
    - 铁律 33 (fail-loud — exit code != 0 if DB fail)
    - 铁律 35 (secrets via env — DATABASE_URL from backend/.env, 0 fallback)
    - 铁律 41 (Asia/Shanghai timezone)
    - LL-105 SOP-6 SSOT (cite source priority)
    - LL-190 (sediment-then-forget, 本 script 是 enforcement layer)

Author: CC autonomous Session 58+1 (continuous mode, P0-16 closure batch 6).
Date: 2026-05-19 evening SH.
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

# Asia/Shanghai timezone (铁律 41)
SH_TZ = timezone(timedelta(hours=8))
NOW = datetime.now(SH_TZ)

# Threshold (沿用 V3 §20.1 #6 budget cap, sustained backend/.env LLM_MONTHLY_BUDGET_USD=50)
DEFAULT_MONTHLY_BUDGET_USD = 50.0
WARN_RATIO = 0.80  # 80% warn
CAP_RATIO = 1.00  # 100% cap (Ollama fallback trigger)


def _parse_env_file(env_path: Path) -> dict[str, str]:
    """Parse .env file, return field→value dict (反 fallback per 铁律 35)."""
    if not env_path.exists():
        raise SystemExit(f"FAIL: {env_path} not found (铁律 35 secrets via env required)")
    fields: dict[str, str] = {}
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        fields[k.strip()] = v.strip()
    return fields


def _parse_database_url(url: str) -> dict[str, str]:
    """Parse postgresql+asyncpg://user:pass@host:port/db → connection dict."""
    # postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2
    m = re.match(r"postgresql\+?(?:asyncpg)?://([^:]+):([^@]+)@([^:]+):(\d+)/(\S+)", url)
    if not m:
        # Security-review M1 (PR #392): 不回显 url —— DATABASE_URL 含 DB 密码,
        # url[:50] 会泄露明文密码到 stderr → Celery wrapper 捕获并传播.
        raise SystemExit(
            "FAIL: DATABASE_URL parse failed "
            "(expected postgresql://user:pass@host:port/db) — value redacted"
        )
    return {
        "user": m.group(1),
        "password": m.group(2),
        "host": m.group(3),
        "port": m.group(4),
        "dbname": m.group(5),
    }


# ════════════════════════════════════════════════════════════
# MVP 4.1 batch 3.9: Platform SDK migration (iter 51 2026-05-25)
# 沿用 batch 3.8 intraday_monitor 体例 (commit a79a810):
#   - send_alert(level, title, content, kind, details_extra) — top-level dispatch
#   - _send_alert_via_platform_sdk — SDK path (PlatformAlertRouter + Alert + dedup)
#   - _send_alert_via_legacy_dingtalk — legacy fallback (HMAC signing preserved)
#   - settings.OBSERVABILITY_USE_PLATFORM_SDK toggle
# 铁律 33 fail-soft: 顶层 send_alert catch AlertDispatchError + Exception
#   (审计已完成, 告警 dispatch 失败不改 exit code / 不抛错).
# ════════════════════════════════════════════════════════════

# MVP 4.1 batch 3.9: AlertDispatchError 顶层 import (铁律 33 fail-loud at SDK layer,
# fail-soft at top-level dispatch — 与 intraday_monitor batch 3.8 体例一致).
from qm_platform.observability import AlertDispatchError  # noqa: E402


def _send_alert_via_platform_sdk(
    level: str,
    title: str,
    content: str,
    kind: str = "llm_cost_monthly_audit",
    details_extra: dict[str, object] | None = None,
) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.9, iter 51).

    llm_cost_monthly_audit 1 call site (vs intraday_monitor batch 3.8 5 call sites):
    monthly cadence, status ∈ {WARN, CAP_EXCEEDED} only triggers push.

    kind-aware dedup_key 构造在代码端 (yaml 仅提供 suppress_minutes, 沿用 batch 3.8
    设计避免 yaml format_dedup_key cb_level placeholder 缺失 raise):
      dedup_key = "llm_cost_monthly:{status}:{year_month}"

    Monthly cadence: suppress_minutes=1440 (24h, 防同月重复 push).

    AlertDispatchError 必传播 (铁律 33). 调用方 (顶层 send_alert) try/except 包裹.
    """
    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    today_str = str(date.today())
    severity = (
        Severity(level.lower()) if level.lower() in {"p0", "p1", "p2", "info"} else Severity.P1
    )

    details: dict[str, str] = {
        "trade_date": today_str,
        "kind": kind,
        "content": content,
    }
    if details_extra:
        for k, v in details_extra.items():
            details[k] = str(v) if not isinstance(v, str) else v

    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="llm_cost_monthly_audit",
        details=details,
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    router = get_alert_router()

    # kind-aware dedup: monthly cadence, 按 (status, year_month) 去重
    year_month = NOW.strftime("%Y-%m")
    status_str = str(details.get("status", "unknown"))
    dedup_key = f"llm_cost_monthly:{status_str}:{year_month}"

    # Monthly cadence: 24h suppress (1440min, 防同月重复 push).
    suppress_minutes = 1440

    router.fire(alert, dedup_key=dedup_key, suppress_minutes=suppress_minutes)


def _send_alert_via_legacy_dingtalk(
    env: dict[str, str],
    status: str,
    mtd_total: float,
    budget: float,
    mtd_ratio: float,
    mom_change: float | None,
) -> None:
    """Legacy 直接 httpx.post + HMAC 签名 (保留向后兼容路径, sustained pre-batch-3.9 体例).

    沿用 scripts/daily_reconciliation.py 的 plain-post 体例 —— 读 .env 的
    DINGTALK_WEBHOOK_URL, httpx.post text 消息. 若 .env 含 DINGTALK_SECRET 则
    附加 DingTalk 加签 (timestamp + HMAC-SHA256 sign), 否则 plain post
    (HMAC secret 配置见 Plan v9 matrix §5 user touchpoint).

    铁律 33 fail-soft —— 审计已完成 (exit code 已定), 告警推送是 best-effort 旁路.
    """
    webhook = env.get("DINGTALK_WEBHOOK_URL", "").strip()
    if not webhook:
        print("[DingTalk] DINGTALK_WEBHOOK_URL 未配置 — 跳过成本告警推送")
        return

    mom_str = f"{mom_change:+.1f}%" if mom_change is not None else "N/A"
    tail = (
        "CAP 超标 → 触发 Ollama fallback (ADR-028 §3.3)"
        if status == "CAP_EXCEEDED"
        else "接近月度预算上限, 请复查 llm_call_log"
    )
    text = (
        f"[LLM 成本告警 {status}] {NOW.strftime('%Y-%m')}\n"
        f"MTD 成本: ${mtd_total:.4f} / 预算 ${budget:.2f} ({mtd_ratio * 100:.1f}%)\n"
        f"月环比 (MoM): {mom_str}\n"
        f"{tail}"
    )

    try:
        import httpx

        url = webhook
        secret = env.get("DINGTALK_SECRET", "").strip()
        if secret:
            import base64
            import hashlib
            import hmac
            import time
            import urllib.parse

            ts = str(round(time.time() * 1000))
            hmac_code = hmac.new(
                secret.encode("utf-8"),
                f"{ts}\n{secret}".encode(),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
            url = f"{webhook}&timestamp={ts}&sign={sign}"

        resp = httpx.post(
            url,
            json={"msgtype": "text", "text": {"content": text}},
            timeout=10,
        )
        print(f"[DingTalk] 成本告警已推送 status={status} http={resp.status_code}")
    except Exception as e:
        # 铁律 33 fail-soft: 审计已完成, 告警旁路失败不改变 exit code / 不抛错.
        print(f"[DingTalk] 成本告警推送失败 (fail-soft, 审计结果不受影响): {e}")


def send_alert(
    env: dict[str, str],
    status: str,
    mtd_total: float,
    budget: float,
    mtd_ratio: float,
    mom_change: float | None,
) -> None:
    """LLM 成本告警 dispatch (MVP 4.1 batch 3.9, iter 51 2026-05-25).

    `settings.OBSERVABILITY_USE_PLATFORM_SDK` 控制路径切换:
      - True  → `_send_alert_via_platform_sdk` (PlatformAlertRouter SDK)
      - False → `_send_alert_via_legacy_dingtalk` (httpx + HMAC fallback)

    铁律 33 fail-soft (审计已完成, dispatch 失败不阻塞 exit code):
      - SDK path AlertDispatchError → log + continue (不抛 / 不改 exit code)
      - Legacy path 内部已 try/except
      - 顶层 catch generic Exception (settings/import 等错误)

    沿用 batch 3.8 intraday_monitor 体例 (commit a79a810). Signature 保持 env-based
    (domain-specific args), 不改 caller call site contract.
    """
    # Settings import scoped (反 module-level circular)
    try:
        from app.config import settings

        use_sdk = getattr(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False)
    except Exception:
        # settings unavailable (test / standalone) → legacy fallback
        use_sdk = False

    # Build title/content shared by SDK path (legacy path 内部自建)
    mom_str = f"{mom_change:+.1f}%" if mom_change is not None else "N/A"
    tail = (
        "CAP 超标 → 触发 Ollama fallback (ADR-028 §3.3)"
        if status == "CAP_EXCEEDED"
        else "接近月度预算上限, 请复查 llm_call_log"
    )
    level = "P0" if status == "CAP_EXCEEDED" else "P1"
    title = f"LLM 成本告警 {status} {NOW.strftime('%Y-%m')}"
    content = (
        f"MTD 成本: ${mtd_total:.4f} / 预算 ${budget:.2f} ({mtd_ratio * 100:.1f}%)\n"
        f"月环比 (MoM): {mom_str}\n"
        f"{tail}"
    )
    details_extra: dict[str, object] = {
        "status": status,
        "mtd_total": f"{mtd_total:.4f}",
        "budget": f"{budget:.2f}",
        "mtd_ratio": f"{mtd_ratio:.4f}",
        "mom_change": f"{mom_change:.4f}" if mom_change is not None else "null",
    }

    try:
        if use_sdk:
            _send_alert_via_platform_sdk(
                level, title, content, "llm_cost_monthly_audit", details_extra
            )
        else:
            _send_alert_via_legacy_dingtalk(env, status, mtd_total, budget, mtd_ratio, mom_change)
    except AlertDispatchError as e:
        # SDK path P0/P1 sink failed — log + continue (审计 exit code 不变).
        print(f"[Observability] AlertDispatchError sink failed: {e} (fail-soft, 审计结果不受影响)")
    except Exception as e:
        # 顶层 catch: settings/import / 配置错 等剩余路径 (legacy 已自带 except).
        # 铁律 33 fail-soft 沿用 — 审计已完成.
        print(f"[Observability] 告警 dispatch 失败 (fail-soft, 审计结果不受影响): {e}")


# Backward-compat alias: 沿用 _push_dingtalk 旧名供潜在 caller (此 script 内仅 main()
# 调一处, 但留 alias 防隐藏 caller surface 后 silent break).
_push_dingtalk = send_alert


def main() -> int:
    """Run monthly audit, push DingTalk if cost > 80% threshold, exit 0/1."""
    print(f"=== LLM Cost Monthly Audit {NOW.isoformat()} ===")
    print("Sustained: 铁律 9/33/35/41 + V3 §20.1 #6 + LL-190 sediment-then-forget enforcement")
    print()

    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / "backend" / ".env"
    env = _parse_env_file(env_path)

    db_url = env.get("DATABASE_URL", "")
    if not db_url:
        raise SystemExit("FAIL: DATABASE_URL not set in .env (铁律 35)")

    db_conn = _parse_database_url(db_url)

    budget_str = env.get("LLM_MONTHLY_BUDGET_USD", str(DEFAULT_MONTHLY_BUDGET_USD))
    try:
        budget = float(budget_str)
    except ValueError:
        budget = DEFAULT_MONTHLY_BUDGET_USD

    print(f"[Config] Monthly budget: ${budget:.2f}")
    print(f"[Config] Warn threshold: {WARN_RATIO * 100:.0f}% = ${budget * WARN_RATIO:.2f}")
    print(f"[Config] Cap threshold:  {CAP_RATIO * 100:.0f}% = ${budget * CAP_RATIO:.2f}")
    print()

    # Connect DB
    try:
        import psycopg2  # noqa: F401
    except ImportError as err:
        raise SystemExit("FAIL: psycopg2 not installed (沿用 backend/.venv 体例)") from err

    import psycopg2

    conn = psycopg2.connect(
        host=db_conn["host"],
        port=db_conn["port"],
        dbname=db_conn["dbname"],
        user=db_conn["user"],
        password=db_conn["password"],
        connect_timeout=10,
    )
    try:
        cur = conn.cursor()
        # Per-month aggregation (last 6 months)
        cur.execute(
            """
            SELECT
                to_char(triggered_at, 'YYYY-MM') as month_bucket,
                task as call_type,
                COUNT(*) as call_count,
                ROUND(SUM(cost_usd)::numeric, 4) as total_cost_usd,
                ROUND(AVG(cost_usd)::numeric, 6) as avg_cost_per_call
            FROM llm_call_log
            WHERE triggered_at >= date_trunc('month', NOW()) - INTERVAL '6 months'
            GROUP BY month_bucket, task
            ORDER BY month_bucket DESC, total_cost_usd DESC NULLS LAST;
            """
        )
        rows = cur.fetchall()
        print(f"[Query] llm_call_log last 6 months, {len(rows)} groups:")
        print()
        print(f"  {'Month':<10} {'CallType':<25} {'Count':>8} {'Total$':>10} {'Avg$':>10}")
        print(f"  {'-' * 10} {'-' * 25} {'-' * 8} {'-' * 10} {'-' * 10}")
        current_month = NOW.strftime("%Y-%m")
        mtd_total = 0.0
        for row in rows:
            month, call_type, count, total, avg = row
            total_f = float(total) if total else 0.0
            avg_f = float(avg) if avg else 0.0
            print(f"  {month:<10} {call_type:<25} {count:>8} {total_f:>10.4f} {avg_f:>10.6f}")
            if month == current_month:
                mtd_total += total_f
        print()

        # MTD summary
        print(f"[MTD {current_month}] total cost: ${mtd_total:.4f}")
        mtd_ratio = mtd_total / budget if budget > 0 else 0
        print(f"[MTD {current_month}] ratio: {mtd_ratio * 100:.1f}% of budget")

        # Threshold evaluation
        if mtd_ratio >= CAP_RATIO:
            print("[ALERT] CAP THRESHOLD EXCEEDED: trigger Ollama fallback per ADR-028 §3.3")
            status = "CAP_EXCEEDED"
            exit_code = 1
        elif mtd_ratio >= WARN_RATIO:
            print("[WARN] WARN THRESHOLD EXCEEDED: cost approaching $50 monthly budget")
            status = "WARN"
            exit_code = 0  # Warning still exit 0 (沿用 budget.py state machine — warning, not fail)
        else:
            print("[OK] within budget")
            status = "OK"
            exit_code = 0

        # Last month comparison (反 month-over-month drift detection)
        last_month_dt = (NOW.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        cur.execute(
            """
            SELECT ROUND(SUM(cost_usd)::numeric, 4)
            FROM llm_call_log
            WHERE to_char(triggered_at, 'YYYY-MM') = %s
            """,
            (last_month_dt,),
        )
        last_month_total = cur.fetchone()[0]
        mom_change: float | None = None
        if last_month_total is not None:
            last_month_f = float(last_month_total)
            mom_change = (mtd_total - last_month_f) / last_month_f * 100 if last_month_f > 0 else 0
            print(f"[Compare] Last month ({last_month_dt}): ${last_month_f:.4f}")
            print(f"[Compare] MoM change: {mom_change:+.1f}%")

        cur.close()

        # DingTalk 推送 (Plan v10 — 关闭原 TODO + Beat `llm-cost-monthly-audit`
        # 设计 "Push DingTalk if MoM change > 50% OR MTD > 80% budget").
        # status != OK 已含 MTD >= 80% (WARN) / >= 100% (CAP); 另加 MoM 漂移 > 50%.
        mom_alert = mom_change is not None and abs(mom_change) > 50.0
        if status != "OK" or mom_alert:
            _push_dingtalk(env, status, mtd_total, budget, mtd_ratio, mom_change)

        print()
        print(f"=== Audit COMPLETE — status={status} ===")
        return exit_code
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
