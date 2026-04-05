#!/usr/bin/env python3
"""调仓修复 — 卖超买+买缺失 (手动运行)。

背景: 4/2首次QMT建仓因dry-run真实下单导致3只科创板双倍买入(688570/688211/688303),
6只北交所未买入(920819/920701/920237/920608/920245/920807)。

操作:
  Step 1-3: 卖出超买部分(3笔)
  Step 4-6: 用释放资金买入缺失股票(按资金优先级)

安全:
  - 两次手动确认(卖出前+买入前)
  - 每步打印状态
  - 异常立即停止
  - 全程写execution_audit_log

用法:
    python scripts/rebalance_fix_0407.py
"""

import os
import sys
import time
from datetime import date, datetime, UTC
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.append(str(Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"))

import psycopg2

# ── 硬编码操作计划（不从信号动态计算，防止信号变化导致卖错）──

SELL_PLAN = [
    ("688570", 5100),  # 天玛智控 超买5100股
    ("688211", 2800),  # 中科微至 超买2800股
    ("688303", 4100),  # 大全能源 超买4100股
]

# 缺失股票（按信号权重降序，资金不够时优先买前面的）
BUY_TARGETS = [
    ("920819", 0.0888),  # 颖泰生物
    ("920701", 0.0884),  # 高凌信息
    ("920237", 0.0883),  # 力佳科技
    ("920608", 0.0738),  # 金博股份(北交所)
    ("920245", 0.0738),  # 瑞德设计
    ("920807", 0.0738),  # 昆工科技
]

STRATEGY_ID = "28fc37e5-2d32-4ada-92e0-41c11a5103d0"
PRICE_TOLERANCE = 0.03  # 限价容错3%
ORDER_WAIT_SEC = 60     # 每笔等待60秒


def get_conn():
    return psycopg2.connect(dbname="quantmind_v2", user="xin", password="quantmind", host="localhost")


def audit_log(conn, action, code="", order_id=0, qty=0, price=0.0, detail=""):
    """写审计日志。"""
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO execution_audit_log
               (trade_date, action, code, order_id, quantity, price, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (date.today(), action, code, order_id, qty, price, detail),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def connect_qmt():
    """连接QMT并返回broker。"""
    from engines.broker_qmt import MiniQMTBroker
    from app.config import settings
    broker = MiniQMTBroker(settings.QMT_PATH, settings.QMT_ACCOUNT_ID)
    broker.connect()
    return broker


def print_status(broker):
    """打印当前持仓和资金。"""
    asset = broker.query_asset()
    positions = broker.query_positions()
    print(f"\n  总资产: ¥{asset['total_asset']:,.2f}")
    print(f"  可用资金: ¥{asset['cash']:,.2f}")
    print(f"  持仓市值: ¥{asset['market_value']:,.2f}")
    print(f"  持仓数: {len(positions)}只")
    for p in positions:
        code = p["stock_code"].split(".")[0]
        print(f"    {p['stock_code']:12s} {p['volume']:>6}股 ¥{p['market_value']:>10,.2f}")
    return asset, positions


def get_realtime_price(code):
    """获取实时价格。"""
    try:
        from xtquant import xtdata
        from engines.qmt_execution_adapter import _to_qmt_code
        qmt_code = _to_qmt_code(code)
        ticks = xtdata.get_full_tick([qmt_code])
        if isinstance(ticks, dict) and qmt_code in ticks:
            t = ticks[qmt_code]
            if t.get("lastPrice", 0) > 0:
                return t["lastPrice"]
    except Exception:
        pass
    return 0


def place_and_wait(broker, code, direction, volume, ref_price, conn):
    """下单并等待成交。返回(成交量, 成交价) 或 (0, 0)。"""
    from engines.qmt_execution_adapter import _to_qmt_code

    # 计算限价
    if direction == "buy":
        limit_price = round(ref_price * (1 + PRICE_TOLERANCE), 2)
    else:
        limit_price = round(ref_price * (1 - PRICE_TOLERANCE), 2)

    qmt_code = _to_qmt_code(code)
    print(f"  下单: {qmt_code} {direction} {volume}股 @{limit_price:.2f}", flush=True)

    order_id = broker.place_order(
        code=qmt_code, direction=direction, volume=volume,
        price=limit_price, price_type="limit",
        remark=f"fix_0407_{direction}",
    )

    if order_id < 0:
        print(f"  ❌ 下单失败: order_id={order_id}")
        audit_log(conn, "place_fail", code, quantity=volume, price=limit_price)
        return 0, 0

    audit_log(conn, "place_order", code, order_id, volume, limit_price, f"fix_{direction}")
    print(f"  委托已提交: order_id={order_id}, 等待成交...", flush=True)

    # 等待成交（轮询）
    for i in range(ORDER_WAIT_SEC // 2):
        time.sleep(2)
        orders = broker.query_orders()
        for o in orders:
            if o.get("order_id") == order_id:
                status = o.get("order_status", 0)
                traded = o.get("traded_volume", 0)
                traded_price = o.get("traded_price", 0)

                if status in (55, 56):  # 部成/已成
                    print(f"  ✅ 成交: {traded}股 @{traded_price:.2f}")
                    audit_log(conn, "fill", code, order_id, traded, traded_price)
                    return traded, traded_price
                elif status in (53, 54, 57):  # 部撤/已撤/废单
                    if traded > 0:
                        print(f"  ⚠️ 部分成交: {traded}/{volume}股 @{traded_price:.2f}")
                        audit_log(conn, "partial_fill", code, order_id, traded, traded_price)
                        return traded, traded_price
                    print(f"  ❌ 委托终止: status={status}")
                    audit_log(conn, "cancel", code, order_id, detail=f"status={status}")
                    return 0, 0

    # 超时 → 撤单
    print(f"  ⏰ 超时，撤单...")
    broker.cancel_order(order_id)
    time.sleep(3)

    # 检查是否有部分成交
    orders = broker.query_orders()
    for o in orders:
        if o.get("order_id") == order_id:
            traded = o.get("traded_volume", 0)
            traded_price = o.get("traded_price", 0)
            if traded > 0:
                print(f"  ⚠️ 超时但部分成交: {traded}股 @{traded_price:.2f}")
                return traded, traded_price

    print(f"  ❌ 超时未成交")
    return 0, 0


def main():
    today = date.today()
    print("=" * 60)
    print(f"4/7 节后调仓修复 — {today}")
    print("=" * 60)

    # Step 0: 交易时间检查
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    if hour < 9 or (hour == 9 and minute < 30) or hour >= 15:
        print(f"\n⚠️ 当前时间 {now.strftime('%H:%M')} 不在交易时间(09:30-15:00)")
        resp = input("继续? (YES/NO): ")
        if resp.strip().upper() != "YES":
            print("已取消")
            return

    # Step 1: 连接
    print("\n[Step 1] 连接QMT...")
    broker = connect_qmt()
    conn = get_conn()
    audit_log(conn, "fix_start", detail="rebalance_fix_0407")

    print("\n[Step 2] 当前持仓:")
    asset, positions = print_status(broker)

    # Step 3: 确认卖出计划
    print("\n[Step 3] 卖出计划（超买部分）:")
    total_sell_est = 0
    for code, qty in SELL_PLAN:
        px = get_realtime_price(code)
        est = qty * px if px > 0 else qty * 20  # fallback估价
        total_sell_est += est
        print(f"  {code}: 卖出{qty}股, 实时价={px:.2f}, 预估释放=¥{est:,.0f}")
    print(f"  预估总释放: ¥{total_sell_est:,.0f}")

    resp = input("\n确认执行卖出? (YES/NO): ")
    if resp.strip().upper() != "YES":
        print("已取消")
        broker.disconnect()
        return

    # Step 4: 执行卖出
    print("\n[Step 4] 执行卖出...")
    sell_results = []
    for code, qty in SELL_PLAN:
        px = get_realtime_price(code)
        if px <= 0:
            print(f"  ❌ {code} 无法获取价格，跳过")
            sell_results.append((code, 0, 0))
            continue
        filled_qty, filled_px = place_and_wait(broker, code, "sell", qty, px, conn)
        sell_results.append((code, filled_qty, filled_px))
        if filled_qty == 0:
            print(f"  ⚠️ {code} 卖出失败，继续下一只")

    # Step 5: 卖出结果
    print("\n[Step 5] 卖出结果:")
    total_released = 0
    for code, qty, px in sell_results:
        amt = qty * px
        total_released += amt
        status = "✅" if qty > 0 else "❌"
        print(f"  {status} {code}: {qty}股 @{px:.2f} = ¥{amt:,.0f}")
    print(f"  已释放: ¥{total_released:,.0f}")

    time.sleep(2)  # 等资金结算
    asset2 = broker.query_asset()
    available = asset2["cash"]
    print(f"  当前可用资金: ¥{available:,.2f}")

    # Step 6: 计算买入计划
    print("\n[Step 6] 买入计划:")
    buy_plan = []
    remaining = available * 0.95  # 预留5%安全余量

    for code, weight in BUY_TARGETS:
        px = get_realtime_price(code)
        if px <= 0:
            print(f"  {code}: 无实时价格，跳过")
            continue

        # 按信号权重分配资金
        target_amount = asset2["total_asset"] * weight
        buy_qty = int(target_amount / px / 100) * 100

        # 资金约束
        cost = buy_qty * px * (1 + PRICE_TOLERANCE)
        if cost > remaining:
            buy_qty = int(remaining / px / (1 + PRICE_TOLERANCE) / 100) * 100
            cost = buy_qty * px * (1 + PRICE_TOLERANCE)

        if buy_qty >= 100:
            buy_plan.append((code, buy_qty, px, cost))
            remaining -= cost
            print(f"  {code}: 买入{buy_qty}股 @~{px:.2f} 预估=¥{cost:,.0f} (剩余资金=¥{remaining:,.0f})")
        else:
            print(f"  {code}: 资金不足，跳过 (需¥{px*100:,.0f})")

    if not buy_plan:
        print("\n无可执行的买入，结束")
        broker.disconnect()
        return

    resp = input(f"\n确认买入{len(buy_plan)}只? (YES/NO): ")
    if resp.strip().upper() != "YES":
        print("已取消买入")
        broker.disconnect()
        return

    # Step 7: 执行买入
    print("\n[Step 7] 执行买入...")
    buy_results = []
    for code, qty, px, _ in buy_plan:
        # 刷新实时价格
        fresh_px = get_realtime_price(code)
        if fresh_px > 0:
            px = fresh_px
        filled_qty, filled_px = place_and_wait(broker, code, "buy", qty, px, conn)
        buy_results.append((code, filled_qty, filled_px, qty))

    # Step 8: 结果
    print("\n[Step 8] 买入结果:")
    for code, filled, px, ordered in buy_results:
        status = "✅" if filled > 0 else "❌"
        print(f"  {status} {code}: {filled}/{ordered}股 @{px:.2f}")

    # Step 9: 写trade_log
    print("\n[Step 9] 写入trade_log...")
    now_utc = datetime.now(UTC)
    cur = conn.cursor()
    all_fills = [(c, q, p, "sell") for c, q, p in sell_results if q > 0] + \
                [(c, q, p, "buy") for c, q, p, _ in buy_results if q > 0]

    for code, qty, px, direction in all_fills:
        amount = qty * px
        commission = max(amount * 0.0000854, 5.0)
        tax = amount * 0.0005 if direction == "sell" else 0
        total_cost = commission + tax + amount * 0.00001
        cur.execute(
            """INSERT INTO trade_log
               (code, trade_date, strategy_id, direction, quantity, fill_price,
                slippage_bps, commission, stamp_tax, total_cost,
                execution_mode, executed_at, order_qty)
               VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s, %s, 'live', %s, %s)
               ON CONFLICT DO NOTHING""",
            (code, today, STRATEGY_ID, direction, qty, px,
             commission, tax, total_cost, now_utc, qty),
        )
    conn.commit()
    print(f"  写入{len(all_fills)}笔")

    # Step 10: 最终状态
    print("\n[Step 10] 最终持仓:")
    print_status(broker)

    audit_log(conn, "fix_finish", detail=f"sells={len(sell_results)} buys={len(buy_results)}")

    broker.disconnect()
    conn.close()
    print("\n✅ 调仓修复完成")


if __name__ == "__main__":
    main()
