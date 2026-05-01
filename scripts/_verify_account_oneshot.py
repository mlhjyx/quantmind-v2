"""WI 0.5 — 1 次性 read-only verify 真账户 ground truth (Week 1 prerequisite).

用法: python scripts/_verify_account_oneshot.py

真核 task:
  - ensure_xtquant_path() (沿用 backend/app/core/xtquant_path.py)
  - MiniQMTBroker.connect() (真生产 path, 沿用 scripts/qmt_data_service.py:90-115)
  - query_asset() + query_positions() (真 read-only, 0 写入)
  - disconnect immediately (避免 second session 常驻)
  - print 真值 stdout
  - 0 INSERT 任何 DB / Redis

真核 cross-check sprint state cite (4-30 14:54):
  - cash=¥993,520.16 / 持仓=0 / nav=993520.16

drift > 0.01% (cash > ¥99.35 偏离) → STOP + 真根因深查.
drift = 0 → ground truth verify ✅ → continue Week 1.

本脚本 1 次性, 用完即删 (沿用 user 决议反问 5 d).
"""
from __future__ import annotations

import sys
from pathlib import Path

# 项目路径 (沿用 qmt_data_service.py:28-30)
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root / "backend"))

from app.config import settings  # noqa: E402
from app.core.xtquant_path import ensure_xtquant_path  # noqa: E402


def main() -> int:
    print(f"[WI 0.5] QMT_PATH={settings.QMT_PATH}")
    print(f"[WI 0.5] QMT_ACCOUNT_ID={settings.QMT_ACCOUNT_ID}")
    ensure_xtquant_path()

    try:
        from engines.broker_qmt import MiniQMTBroker
    except ImportError as exc:
        print(f"[WI 0.5 STOP] MiniQMTBroker import failed: {exc}")
        return 2

    broker = MiniQMTBroker(settings.QMT_PATH, settings.QMT_ACCOUNT_ID)

    try:
        broker.connect()
    except RuntimeError as exc:
        print(f"[WI 0.5 STOP] broker.connect() failed: {exc}")
        return 3
    except Exception as exc:
        print(f"[WI 0.5 STOP] broker.connect() unexpected error: {type(exc).__name__}: {exc}")
        return 3

    try:
        asset = broker.query_asset()
        print(f"[WI 0.5] asset={asset}")
    except Exception as exc:
        print(f"[WI 0.5 STOP] query_asset failed: {type(exc).__name__}: {exc}")
        broker.disconnect()
        return 4

    try:
        positions = broker.query_positions()
        print(f"[WI 0.5] positions count={len(positions)}")
        if positions:
            for p in positions[:5]:
                print(f"  {p}")
    except Exception as exc:
        print(f"[WI 0.5 STOP] query_positions failed: {type(exc).__name__}: {exc}")
        broker.disconnect()
        return 5

    broker.disconnect()
    print("[WI 0.5] disconnect OK, oneshot done.")

    sprint_state_cash = 993520.16
    sprint_state_positions = 0
    actual_cash = float(asset.get("cash", 0)) if isinstance(asset, dict) else 0
    actual_positions = len(positions)
    cash_drift_pct = abs(actual_cash - sprint_state_cash) / sprint_state_cash * 100 if sprint_state_cash else 0

    print("=" * 60)
    print("[WI 0.5 cross-check sprint state 4-30 14:54]")
    print(f"  cash:       sprint={sprint_state_cash:.2f}  actual={actual_cash:.2f}  drift={cash_drift_pct:.4f}%")
    print(f"  positions:  sprint={sprint_state_positions}  actual={actual_positions}")
    print("=" * 60)

    if cash_drift_pct > 0.01:
        print(f"[WI 0.5 STOP] cash drift {cash_drift_pct:.4f}% > 0.01% threshold")
        return 6
    if actual_positions != sprint_state_positions:
        print(f"[WI 0.5 STOP] positions count mismatch: sprint={sprint_state_positions} actual={actual_positions}")
        return 7

    print("[WI 0.5 ✅] ground truth verify PASS (drift < 0.01%, positions match)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
