#!/usr/bin/env python3
"""Paper Trading一次性初始化 — 创建策略行+初始状态。

运行一次即可，会:
1. INSERT strategy 行
2. INSERT strategy_configs 版本1
3. 打印strategy_id → 用户需加入.env

用法:
    python scripts/setup_paper_trading.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn

LOCKED_CONFIG = {
    "factors": [
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
    ],
    "weight_method": "equal",
    "top_n": 20,
    "rebalance_freq": "monthly",
    "industry_cap": 0.25,
    "turnover_cap": 0.50,
    "beta_hedge": {
        "enabled": True,
        "method": "rolling_60d",
        "threshold": 0.3,
        "min_scale": 0.5,
    },
    "initial_capital": 1_000_000,
    "slippage_bps": 10.0,
    "commission_rate": 0.00015,
    "stamp_tax_rate": 0.0005,
}


def main():
    conn = _get_sync_conn()
    cur = conn.cursor()

    # 检查是否已存在
    cur.execute(
        "SELECT id FROM strategy WHERE name = 'Phase0_PaperTrading' LIMIT 1"
    )
    existing = cur.fetchone()
    if existing:
        print(f"⚠️  策略已存在: {existing[0]}")
        print(f"   如需重建，请先删除: DELETE FROM strategy WHERE id = '{existing[0]}';")
        conn.close()
        return

    # 创建策略
    cur.execute(
        """INSERT INTO strategy
           (name, market, mode, factor_config, backtest_config, status)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (
            "Phase0_PaperTrading",
            "astock",
            "visual",
            json.dumps(LOCKED_CONFIG),
            json.dumps({
                "initial_capital": 1_000_000,
                "benchmark": "000300.SH",
                "start_date": "2026-03-21",
            }),
            "paper",
        ),
    )
    strategy_id = cur.fetchone()[0]

    # 创建配置版本1
    cur.execute(
        """INSERT INTO strategy_configs (strategy_id, version, config, changelog)
           VALUES (%s, 1, %s, %s)""",
        (
            strategy_id,
            json.dumps(LOCKED_CONFIG),
            "Route A 锁定配置: 5因子等权 Top20 月频 IndCap=25% + Beta对冲",
        ),
    )

    conn.commit()
    conn.close()

    print("=" * 60)
    print("✅ Paper Trading 策略已创建")
    print(f"   strategy_id = {strategy_id}")
    print("=" * 60)
    print()
    print("请将以下行添加到 backend/.env:")
    print(f"   PAPER_STRATEGY_ID={strategy_id}")
    print()
    print("然后运行:")
    print("   python scripts/run_paper_trading.py --date 2026-03-21")


if __name__ == "__main__":
    main()
