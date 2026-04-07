#!/usr/bin/env python3
"""紧急撤单脚本 — 撤销所有非终态QMT委托。"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.append(str(Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"))

def main():
    print(f"[{time.strftime('%H:%M:%S')}] 撤单脚本启动", flush=True)

    # 1. 检查QMT进程
    try:
        r = subprocess.run(["tasklist"], capture_output=True, timeout=10, encoding="gbk", errors="ignore")
        if "XtMiniQmt.exe" not in (r.stdout or ""):
            print("QMT未运行，尝试启动...", flush=True)
            from app.config import settings
            exe = getattr(settings, "QMT_EXE_PATH", "")
            if exe:
                subprocess.Popen([exe], cwd=str(Path(exe).parent))
                time.sleep(15)
    except Exception as e:
        print(f"进程检查失败: {e}", flush=True)

    # 2. 连接QMT
    from engines.broker_qmt import MiniQMTBroker

    from app.config import settings
    broker = MiniQMTBroker(settings.QMT_PATH, settings.QMT_ACCOUNT_ID)
    broker.connect()
    print(f"[{time.strftime('%H:%M:%S')}] QMT已连接", flush=True)

    # 3. 查询并撤单
    orders = broker.query_orders()
    pending_statuses = (48, 49, 50, 51, 52)  # 待报/已报/部成等非终态
    to_cancel = [o for o in orders if o.get("order_status", 0) in pending_statuses]
    print(f"非终态委托: {len(to_cancel)}笔", flush=True)

    for o in to_cancel:
        oid = o["order_id"]
        code = o.get("stock_code", "?")
        broker.cancel_order(oid)
        print(f"  撤单: {code} order_id={oid}", flush=True)

    if to_cancel:
        time.sleep(5)

    # 4. 确认
    asset = broker.query_asset()
    print(f"[{time.strftime('%H:%M:%S')}] 撤单后: 总资产=¥{asset['total_asset']:,.2f}, 可用=¥{asset['cash']:,.2f}, 冻结=¥{asset['frozen_cash']:,.2f}", flush=True)

    # 5. 二次检查
    orders2 = broker.query_orders()
    still = [o for o in orders2 if o.get("order_status", 0) in pending_statuses]
    if still:
        print(f"⚠️ 仍有{len(still)}笔未撤！再次撤单...", flush=True)
        for o in still:
            broker.cancel_order(o["order_id"])
        time.sleep(5)
        asset2 = broker.query_asset()
        print(f"二次撤单后: 可用=¥{asset2['cash']:,.2f}, 冻结=¥{asset2['frozen_cash']:,.2f}", flush=True)

    broker.disconnect()
    print(f"[{time.strftime('%H:%M:%S')}] 完成", flush=True)

if __name__ == "__main__":
    main()
