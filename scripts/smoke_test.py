#!/usr/bin/env python3
"""全站API冒烟测试 — 自动发现所有GET端点并逐个测试。

每小时运行一次（Task Scheduler），失败时DingTalk告警。
非交易日也运行（后端服务任何时候都应该健康）。

用法:
    python scripts/smoke_test.py              # 正常运行
    python scripts/smoke_test.py --verbose    # 详细输出
    python scripts/smoke_test.py --auto-restart  # 失败时自动重启NSSM
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 项目路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

import requests

BASE_URL = "http://localhost:8000"
TIMEOUT = 10  # 秒
SLOW_THRESHOLD = 8  # 秒，超过视为慢
LOG_DIR = PROJECT_ROOT / "logs"

# 跳过的路径（非JSON端点）
SKIP_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
# 跳过带参数的路径
SKIP_PARAM_PATTERNS = ["{"]


def discover_get_endpoints() -> list[str]:
    """从FastAPI app自动发现所有GET端点。"""
    try:
        from app.main import app

        endpoints = []
        for route in app.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                if "GET" in route.methods:
                    path = route.path
                    if path in SKIP_PATHS:
                        continue
                    if any(p in path for p in SKIP_PARAM_PATTERNS):
                        continue
                    endpoints.append(path)
        return sorted(endpoints)
    except Exception as e:
        print(f"[ERROR] 无法从FastAPI发现端点: {e}")
        return []


def test_endpoint(path: str) -> dict:
    """测试单个端点，返回结果dict。"""
    url = f"{BASE_URL}{path}"
    try:
        t0 = time.time()
        r = requests.get(url, timeout=TIMEOUT)
        elapsed = time.time() - t0

        status = ("slow" if elapsed > SLOW_THRESHOLD else "ok") if r.status_code == 200 else "fail"

        # 尝试计算响应条目数
        items = "?"
        try:
            body = r.json()
            if isinstance(body, list):
                items = str(len(body))
            elif isinstance(body, dict):
                items = "dict"
        except Exception:
            pass  # silent_ok: smoke test partial failure surfaced via summary, not abort

        return {
            "path": path,
            "status": status,
            "code": r.status_code,
            "elapsed": round(elapsed, 2),
            "items": items,
        }
    except requests.Timeout:
        return {"path": path, "status": "timeout", "code": 0, "elapsed": TIMEOUT, "items": "-"}
    except requests.ConnectionError:
        return {"path": path, "status": "connection_error", "code": 0, "elapsed": 0, "items": "-"}
    except Exception as e:
        return {"path": path, "status": "error", "code": 0, "elapsed": 0, "items": str(e)[:50]}


# ════════════════════════════════════════════════════════════
# MVP 4.1 batch 3.12 LAST: Platform SDK migration (iter 57 2026-05-25)
# 沿用 batch 3.8/3.9/3.10/3.11 体例. smoke_test 5 call sites (line 187/192/195/
# 235/245), 同一 3-arg signature (level, title, content), kind-aware dispatch
# (smoke_failure / backend_no_response / smoke_pass / etc).
# 完成后 Wave 4 MVP 4.1 batch 3.x = 17/17 = 100% milestone.
# ════════════════════════════════════════════════════════════


def _send_alert_via_platform_sdk(
    level: str,
    title: str,
    content: str,
    kind: str = "smoke_test",
    details_extra: dict[str, object] | None = None,
) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.12, iter 57).

    smoke_test 5 call sites — kind-aware dispatch via title 字符串匹配:
      - kind="backend_down": "后端无响应" / "NSSM重启失败" 失败 P0
      - kind="smoke_fail": "冒烟测试失败" partial fail P1
      - kind="smoke_pass": "冒烟测试通过" P2
      - kind="generic": fallback

    dedup_key = "smoke_test:{kind}:{trade_date}"; suppress_minutes=30
    (cron 频次 5-10min, 30min dedup 防同窗 retry 风暴).
    """
    from datetime import UTC, date, datetime

    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    today_str = str(date.today())
    severity = (
        Severity(level.lower()) if level.lower() in {"p0", "p1", "p2", "info"} else Severity.P1
    )
    details: dict[str, str] = {"trade_date": today_str, "kind": kind, "content": content}
    if details_extra:
        for k, v in details_extra.items():
            details[k] = str(v) if not isinstance(v, str) else v
    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="smoke_test",
        details=details,
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )
    router = get_alert_router()
    dedup_key = f"smoke_test:{kind}:{today_str}"
    suppress_minutes = 30  # smoke test 高频, 30min dedup
    router.fire(alert, dedup_key=dedup_key, suppress_minutes=suppress_minutes)


def _legacy_send_dingtalk_alert(level: str, title: str, content: str) -> None:
    """Legacy DingTalk push (保留 pre-batch-3.12 体例)."""
    try:
        from app.config import settings

        webhook = settings.DINGTALK_WEBHOOK_URL
        if not webhook:
            print("[WARN] DINGTALK_WEBHOOK_URL未配置，跳过告警")
            return
        keyword = settings.DINGTALK_KEYWORD or ""
        text = f"[{level}] {title}\n{content}"
        if keyword and keyword not in text:
            text = f"{keyword} {text}"
        requests.post(
            webhook,
            json={"msgtype": "text", "text": {"content": text}},
            timeout=10,
        )
        print(f"[DingTalk] {level} 告警已发送")
    except Exception as e:
        print(f"[DingTalk] 发送失败: {e}")


def send_dingtalk_alert(level: str, title: str, content: str) -> None:
    """smoke_test 告警 dispatch (MVP 4.1 batch 3.12 LAST, iter 57).

    settings.OBSERVABILITY_USE_PLATFORM_SDK 控制路径切换:
      True  → _send_alert_via_platform_sdk (PlatformAlertRouter SDK)
      False → _legacy_send_dingtalk_alert (inline requests.post)

    Signature 沿用原 3-arg (level, title, content); 5 call sites unchanged.
    铁律 33 fail-soft (smoke_test 是 monitoring 旁路, dispatch 失败不阻断主流程).
    """
    try:
        from qm_platform.observability import AlertDispatchError

        from app.config import settings

        use_sdk = getattr(settings, "OBSERVABILITY_USE_PLATFORM_SDK", False)
    except Exception:
        # settings/SDK import 失败 → legacy fallback
        _legacy_send_dingtalk_alert(level, title, content)
        return

    # kind-aware: title 字符串匹配 dispatch
    if "后端无响应" in title or "NSSM重启失败" in title or "backend" in title.lower():
        kind = "backend_down"
    elif "失败" in title or "fail" in title.lower():
        kind = "smoke_fail"
    elif "通过" in title or "pass" in title.lower():
        kind = "smoke_pass"
    else:
        kind = "generic"

    try:
        if use_sdk:
            _send_alert_via_platform_sdk(level, title, content, kind=kind)
        else:
            _legacy_send_dingtalk_alert(level, title, content)
    except AlertDispatchError as e:
        print(f"[Observability] AlertDispatchError sink failed: {e} (fail-soft)")
    except Exception as e:  # noqa: BLE001
        print(f"[Observability] 告警 dispatch 失败 (fail-soft): {e}")


def auto_restart_nssm() -> bool:
    """尝试重启NSSM FastAPI服务。"""
    nssm = r"D:\tools\nssm\win64\nssm.exe"
    if not Path(nssm).exists():
        print("[WARN] nssm不存在，无法自动重启")
        return False
    try:
        subprocess.run([nssm, "restart", "QuantMind-FastAPI"], timeout=30, check=True)
        print("[INFO] NSSM FastAPI服务已重启")
        time.sleep(10)  # 等待启动
        return True
    except Exception as e:
        print(f"[ERROR] NSSM重启失败: {e}")
        return False


def write_log(results: list[dict], log_path: Path) -> None:
    """写入日志文件。"""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Smoke Test Report - {datetime.now().isoformat()}\n\n")
        ok_count = sum(1 for r in results if r["status"] == "ok")
        slow_count = sum(1 for r in results if r["status"] == "slow")
        fail_count = sum(1 for r in results if r["status"] not in ("ok", "slow"))
        f.write(
            f"Total: {len(results)} | OK: {ok_count} | Slow: {slow_count} | Fail: {fail_count}\n\n"
        )

        for r in results:
            icon = {
                "ok": "✅",
                "slow": "⚠️",
                "fail": "❌",
                "timeout": "💀",
                "connection_error": "🔌",
                "error": "❌",
            }
            f.write(
                f"{icon.get(r['status'], '?')} {r['code']:>3} {r['elapsed']:>5.1f}s items={r['items']:>6}  {r['path']}\n"
            )


def main():
    parser = argparse.ArgumentParser(description="全站API冒烟测试")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--auto-restart", action="store_true", help="后端不响应时自动重启NSSM")
    args = parser.parse_args()

    now = datetime.now()
    print(f"[Smoke Test] 开始 {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 检查后端是否存活
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        if r.status_code != 200:
            raise Exception(f"health返回{r.status_code}")
        print("[Health] OK")
    except Exception as e:
        print(f"[Health] 后端无响应: {e}")
        if args.auto_restart:
            print("[Action] 尝试自动重启NSSM...")
            if auto_restart_nssm():
                # 重启后重试
                try:
                    r = requests.get(f"{BASE_URL}/health", timeout=5)
                    if r.status_code == 200:
                        print("[Health] 重启后恢复正常")
                    else:
                        raise Exception("重启后仍无响应")
                except Exception:
                    send_dingtalk_alert(
                        "P0", "冒烟测试: 后端无响应", f"自动重启NSSM后仍无法连接\n时间: {now}"
                    )
                    sys.exit(1)
            else:
                send_dingtalk_alert("P0", "冒烟测试: 后端无响应", f"NSSM重启失败\n时间: {now}")
                sys.exit(1)
        else:
            send_dingtalk_alert(
                "P0",
                "冒烟测试: 后端无响应",
                f"FastAPI服务不响应\n时间: {now}\n建议: nssm restart QuantMind-FastAPI",
            )
            sys.exit(1)

    # 2. 发现端点
    endpoints = discover_get_endpoints()
    if not endpoints:
        print("[ERROR] 未发现任何GET端点")
        sys.exit(1)
    print(f"[Discovery] 发现 {len(endpoints)} 个GET端点")

    # 3. 逐个测试
    results: list[dict] = []
    for i, path in enumerate(endpoints):
        result = test_endpoint(path)
        results.append(result)
        if args.verbose:
            icon = {"ok": "✅", "slow": "⚠️"}.get(result["status"], "❌")
            print(
                f"  {icon} [{i + 1}/{len(endpoints)}] {result['code']:>3} {result['elapsed']:>5.1f}s {path}"
            )

    # 4. 汇总
    ok_list = [r for r in results if r["status"] == "ok"]
    slow_list = [r for r in results if r["status"] == "slow"]
    fail_list = [r for r in results if r["status"] not in ("ok", "slow")]

    print(
        f"\n[Result] ✅ {len(ok_list)} | ⚠️ {len(slow_list)} | ❌ {len(fail_list)} / {len(results)} total"
    )

    # 5. 告警
    if fail_list:
        fail_detail = "\n".join(
            f"  {r['status'].upper()} {r['path']} (code={r['code']}, {r['elapsed']}s)"
            for r in fail_list
        )
        send_dingtalk_alert(
            "P0",
            f"冒烟测试失败: {len(fail_list)}个端点异常",
            f"时间: {now.strftime('%H:%M')}\n总计: {len(results)} 端点\n失败:\n{fail_detail}",
        )
        if args.auto_restart and any(r["status"] == "connection_error" for r in fail_list):
            print("[Action] 检测到连接错误，尝试重启...")
            auto_restart_nssm()
    elif slow_list:
        slow_detail = "\n".join(f"  {r['path']} ({r['elapsed']}s)" for r in slow_list)
        send_dingtalk_alert(
            "P2",
            f"冒烟测试: {len(slow_list)}个端点响应慢",
            f"时间: {now.strftime('%H:%M')}\n慢端点(>{SLOW_THRESHOLD}s):\n{slow_detail}",
        )
    else:
        if args.verbose:
            print("[OK] 全部通过，无需告警")

    # 6. 写日志
    log_path = LOG_DIR / f"smoke_test_{now.strftime('%Y%m%d_%H%M')}.log"
    write_log(results, log_path)
    print(f"[Log] {log_path}")

    # 返回码: 有失败返回1
    sys.exit(1 if fail_list else 0)


if __name__ == "__main__":
    main()
