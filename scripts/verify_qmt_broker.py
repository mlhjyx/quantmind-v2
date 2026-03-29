"""miniQMT Broker全链路验证脚本。

验证流程:
1. 连接miniQMT模拟账户
2. 查询账户资产
3. 买入100股平安银行(000001.SZ)
4. 等待成交确认
5. 查询持仓确认
6. 卖出100股
7. 等待成交确认
8. 查询最终资产

用法:
    python scripts/verify_qmt_broker.py                    # 完整测试
    python scripts/verify_qmt_broker.py --query-only       # 仅查询(不下单)
    python scripts/verify_qmt_broker.py --dry-run          # 离线逻辑验证(不连接miniQMT)
    python scripts/verify_qmt_broker.py --code 600519.SH   # 指定标的

前置条件:
    - miniQMT客户端已启动并登录模拟账户81001102
    - 市场交易时间内(9:30-11:30, 13:00-15:00)
    - --dry-run 模式不需要miniQMT运行（非交易日/周末可用）
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# 项目根目录加入sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
# xtquant嵌套路径修复（双层site-packages）
sys.path.insert(0, str(PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"))

from engines.broker_qmt import MiniQMTBroker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("verify_qmt")


def step(n: int, desc: str) -> None:
    """打印步骤标题。"""
    print(f"\n{'='*60}")
    print(f"  Step {n}: {desc}")
    print(f"{'='*60}")


def verify_query(broker: MiniQMTBroker) -> None:
    """验证查询功能。"""
    step(1, "查询账户资产")
    asset = broker.query_asset()
    print(f"  可用资金: {asset['cash']:,.2f}")
    print(f"  冻结资金: {asset['frozen_cash']:,.2f}")
    print(f"  持仓市值: {asset['market_value']:,.2f}")
    print(f"  总资产:   {asset['total_asset']:,.2f}")

    step(2, "查询当前持仓")
    positions = broker.query_positions()
    if not positions:
        print("  (无持仓)")
    else:
        print(f"  {'代码':<12} {'数量':>8} {'可卖':>8} {'成本':>10} {'市值':>12}")
        print(f"  {'-'*52}")
        for p in positions:
            print(
                f"  {p['stock_code']:<12} "
                f"{p['volume']:>8} "
                f"{p['can_use_volume']:>8} "
                f"{p['avg_price']:>10.3f} "
                f"{p['market_value']:>12,.2f}"
            )

    step(3, "查询当日委托")
    orders = broker.query_orders()
    print(f"  当日委托数: {len(orders)}")
    for o in orders[:5]:  # 最多显示5条
        print(
            f"  order_id={o['order_id']}, {o['stock_code']}, "
            f"status={o['order_status']}, "
            f"traded={o['traded_volume']}/{o['order_volume']}"
        )

    step(4, "查询当日成交")
    trades = broker.query_trades()
    print(f"  当日成交数: {len(trades)}")
    for t in trades[:5]:
        print(
            f"  {t['stock_code']}, price={t['traded_price']:.3f}, "
            f"volume={t['traded_volume']}, amount={t['traded_amount']:,.2f}"
        )


def verify_full_cycle(broker: MiniQMTBroker, code: str, volume: int) -> None:
    """验证完整买卖周期。"""
    # 先做查询验证
    verify_query(broker)

    # 获取当前资产作为基准
    asset_before = broker.query_asset()

    # --- 买入 ---
    step(5, f"买入 {volume}股 {code} (市价单)")
    buy_order_id = broker.place_order(
        code=code,
        direction="buy",
        volume=volume,
        price_type="market",
        remark="verify_buy",
    )

    if buy_order_id < 0:
        print("  *** 买入下单失败! ***")
        print("  可能原因: 非交易时间 / 资金不足 / QMT未登录")
        return

    print(f"  买入委托已提交: order_id={buy_order_id}")

    # 等待成交
    print("  等待成交...")
    for i in range(30):  # 最多等30秒
        time.sleep(1)
        orders = broker.query_orders()
        buy_order = next((o for o in orders if o["order_id"] == buy_order_id), None)
        if buy_order is None:
            continue
        status = buy_order["order_status"]
        traded = buy_order["traded_volume"]
        print(f"  [{i+1}s] status={status}, traded={traded}/{volume}")
        if status == 56:  # ORDER_SUCCEEDED
            print(f"  *** 买入成交! 均价={buy_order['traded_price']:.3f} ***")
            break
        elif status in (54, 57):  # CANCELED or JUNK
            print(f"  *** 买入被拒绝/撤销: {buy_order.get('order_remark', '')} ***")
            return
    else:
        print("  *** 超时未成交，尝试撤单 ***")
        broker.cancel_order(buy_order_id)
        return

    # --- 确认持仓 ---
    step(6, f"确认 {code} 持仓")
    time.sleep(1)
    positions = broker.query_positions()
    target_pos = next((p for p in positions if p["stock_code"] == code), None)
    if target_pos:
        print(f"  持仓确认: {target_pos['volume']}股, 成本={target_pos['avg_price']:.3f}")
    else:
        print(f"  *** 未找到 {code} 持仓! ***")

    # --- 卖出 ---
    step(7, f"卖出 {volume}股 {code} (市价单)")

    # T+1限制: 当日买入无法卖出(模拟盘可能不限制，视券商设置)
    if target_pos and target_pos["can_use_volume"] < volume:
        print(f"  可卖数量={target_pos['can_use_volume']}，不足{volume}股")
        print("  T+1限制: 当日买入股票次日才能卖出")
        print("  请明日重新运行: python scripts/verify_qmt_broker.py --sell-only --code " + code)
        return

    sell_order_id = broker.place_order(
        code=code,
        direction="sell",
        volume=volume,
        price_type="market",
        remark="verify_sell",
    )

    if sell_order_id < 0:
        print("  *** 卖出下单失败! ***")
        return

    print(f"  卖出委托已提交: order_id={sell_order_id}")

    # 等待成交
    print("  等待成交...")
    for i in range(30):
        time.sleep(1)
        orders = broker.query_orders()
        sell_order = next((o for o in orders if o["order_id"] == sell_order_id), None)
        if sell_order is None:
            continue
        status = sell_order["order_status"]
        traded = sell_order["traded_volume"]
        print(f"  [{i+1}s] status={status}, traded={traded}/{volume}")
        if status == 56:
            print(f"  *** 卖出成交! 均价={sell_order['traded_price']:.3f} ***")
            break
        elif status in (54, 57):
            print("  *** 卖出被拒绝/撤销 ***")
            return
    else:
        print("  *** 超时未成交，尝试撤单 ***")
        broker.cancel_order(sell_order_id)
        return

    # --- 最终确认 ---
    step(8, "最终资产对比")
    time.sleep(1)
    asset_after = broker.query_asset()
    diff = asset_after["total_asset"] - asset_before["total_asset"]
    print(f"  交易前总资产: {asset_before['total_asset']:,.2f}")
    print(f"  交易后总资产: {asset_after['total_asset']:,.2f}")
    print(f"  差异: {diff:+,.2f} (含手续费+滑点)")

    print(f"\n{'='*60}")
    print("  全链路验证完成!")
    print(f"{'='*60}")


def verify_dry_run(qmt_path: str, account: str, code: str) -> None:
    """离线逻辑验证：检查环境配置是否正确，不连接miniQMT。

    适用场景：周末/非交易时段快速确认配置路径和导入是否正常。
    """
    import importlib
    import importlib.util

    step(0, "离线逻辑验证 (--dry-run 模式)")
    print("  注意: 本模式不连接miniQMT，仅验证环境配置")
    print()

    all_ok = True

    # 1. 检查 qmt_path 目录
    from pathlib import Path
    qmt_path_obj = Path(qmt_path)
    if qmt_path_obj.exists():
        print(f"  [OK] QMT路径存在: {qmt_path}")
    else:
        print(f"  [WARN] QMT路径不存在: {qmt_path}")
        print("         miniQMT未启动或路径错误，实盘前请确认")
        all_ok = False

    # 2. 检查 xtquant 可导入
    xtquant_spec = importlib.util.find_spec("xtquant")
    if xtquant_spec is not None:
        print("  [OK] xtquant 模块可导入")
        try:
            import xtquant  # noqa: F401
            print("  [OK] xtquant import 成功")
        except Exception as e:
            print(f"  [WARN] xtquant import 异常: {e}")
            all_ok = False
    else:
        print("  [WARN] xtquant 模块未找到")
        print("         请确认 .venv 路径或 xtquant_path.pth 配置")
        all_ok = False

    # 3. 检查 MiniQMTBroker 可实例化（不连接）
    try:
        broker = MiniQMTBroker(qmt_path=qmt_path, account_id=account)
        print(f"  [OK] MiniQMTBroker 实例化成功 (account={account})")
        del broker
    except Exception as e:
        print(f"  [FAIL] MiniQMTBroker 实例化失败: {e}")
        all_ok = False

    # 4. 检查合约格式
    if "." in code and code.split(".")[-1] in ("SZ", "SH", "BJ"):
        print(f"  [OK] 合约代码格式正确: {code}")
    else:
        print(f"  [WARN] 合约代码格式可能有误: {code} (期望如 000001.SZ)")
        all_ok = False

    print()
    status = "通过" if all_ok else "部分检查未通过（见 WARN/FAIL）"
    print(f"  干跑验证结果: {status}")
    print("  实盘前请确保 miniQMT 客户端启动并登录模拟账户")


def main() -> None:
    """主入口。"""
    parser = argparse.ArgumentParser(description="miniQMT Broker全链路验证")
    parser.add_argument("--query-only", action="store_true", help="仅查询不下单")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="离线逻辑验证（不连接miniQMT，周末/非交易时段可用）",
    )
    parser.add_argument("--code", default="000001.SZ", help="测试标的(默认: 000001.SZ 平安银行)")
    parser.add_argument("--volume", type=int, default=100, help="测试数量(默认: 100股)")
    parser.add_argument(
        "--qmt-path", default=r"E:\国金QMT交易端模拟\userdata_mini",
        help="miniQMT userdata_mini路径",
    )
    parser.add_argument("--account", default="81001102", help="资金账号")
    args = parser.parse_args()

    print("miniQMT Broker 验证脚本")
    print(f"QMT路径: {args.qmt_path}")
    print(f"账号: {args.account}")
    print(f"标的: {args.code}")
    print(f"数量: {args.volume}股")
    if args.dry_run:
        print("模式: 离线干跑验证")
    elif args.query_only:
        print("模式: 仅查询")
    else:
        print("模式: 完整买卖周期")

    # --dry-run: 不需要 miniQMT 运行
    if args.dry_run:
        verify_dry_run(args.qmt_path, args.account, args.code)
        return

    broker = MiniQMTBroker(
        qmt_path=args.qmt_path,
        account_id=args.account,
    )

    try:
        step(0, "连接miniQMT")
        broker.connect()
        print("  连接成功!")

        if args.query_only:
            verify_query(broker)
        else:
            verify_full_cycle(broker, args.code, args.volume)

    except RuntimeError as e:
        print(f"\n*** 错误: {e} ***")
        print("请确认:")
        print("  1. miniQMT客户端已启动并登录")
        print("  2. 模拟账户81001102已就绪")
        print(f"  3. 路径存在: {args.qmt_path}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        broker.disconnect()
        print("\n已断开连接")


if __name__ == "__main__":
    main()
