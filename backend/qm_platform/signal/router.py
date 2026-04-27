"""Framework #6 Signal — PlatformOrderRouter concrete (MVP 3.3 batch 2 Step 1).

铁律 16 唯一信号路径: 内部沿用 `paper_broker` / `qmt_execution_adapter` 的整手逻辑
(`int(target_value / price / LOT_SIZE) * LOT_SIZE`), **不重写**. 本类是 SDK 公共
入口 wrapper, 为 Step 2 `execution_service` signal-side 拆迁 + Step 3
`daily_pipeline` multi-strategy wire 铺路.

## 切片 (本批 batch 2 Step 1)

- ✅ Step 1: PlatformOrderRouter SDK concrete (本 PR, 不动生产入口, 铁律 23)
- 🟡 Step 2: execution_service.py signal-side 拆迁 (regression 真硬门, 下 PR)
- 🟡 Step 3: daily_pipeline.py multi-strategy wire (production 切换, 下下 PR)

## API 语义

`route(signals, current_positions, capital_allocation, turnover_cap=0.5) -> list[Order]`:
- 每 Signal 必有 `metadata["price"]: float` (caller 注入当日价, e.g. close 或实时 last)
- `target_shares = int(capital * target_weight / price / lot_size) * lot_size`
- diff: `shares_delta = target_shares - current_positions.get(code, 0)`
  - `delta > 0` → BUY Order
  - `delta < 0` → SELL Order
  - `delta == 0` → 跳过 (不生成 0 量单)
- `order_id` 幂等键: `sha256(json([strategy_id, trade_date, code, side, target_shares]))[:16]`
- `turnover_cap`: 总 buy_value / sum(capital_allocation) ≤ cap, 否则 raise

`cancel_stale(cutoff_seconds=300) -> list[str]`:
- Step 1 stub: 必传 `cancel_callable` DI, 否则 NotImplementedError
- Step 2 wire QMT `cancel_stale_orders.py` 路径

## 架构决策 (铁律 39 显式)

- **不动生产入口**: `execution_service.py` 仍直走 paper_broker / qmt_adapter,
  Step 2 才切换. 本 Step 1 regression max_diff=0 trivially 通过 (production caller 不动).
- **prices 走 Signal.metadata["price"]**: caller 预加载注入, 对齐 S1MonthlyRanking
  metadata pattern (industry/factor_pool 已在那). 不引 DAL 读 DB (铁律 31 纯计算).
- **lot_size DI**: 默认 100 (A 股), 测试可注入 1 简化场景.
- **cancel_callable DI**: 默认 None → cancel_stale raise NotImplementedError. Step 2
  wire 时注入 QMTConnectionManager.broker.cancel_pending_orders.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from decimal import Decimal
from typing import TYPE_CHECKING

from .._types import Order
from .interface import OrderRouter

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from .._types import Signal

_logger = logging.getLogger(__name__)

# A 股 board lot — round-down 到 100 股倍数.
DEFAULT_LOT_SIZE = 100

# order_id sha256 截位 — 16 位足够防碰撞 (16^16 ≈ 1.8e19, 远大于日 order 量级).
_ORDER_ID_HEX_LEN = 16


class IdempotencyViolation(RuntimeError):  # noqa: N818 — 语义优先 (对齐项目 FlagNotFound 惯例)
    """同 order_id 在 route() 一次返回内重复出现 (理论不该发生, fail-loud 防 silent dup 下单)."""


class InsufficientCapital(RuntimeError):  # noqa: N818
    """总 BUY value 超 sum(capital_allocation), 现金不足 (caller 应 pre-check signals)."""


class TurnoverCapExceeded(RuntimeError):  # noqa: N818
    """总 BUY value 占 capital 比例超 turnover_cap (e.g. 50% 月度调仓硬上限).

    Step 1 抛此异常让 caller 显式决策 (削单 / 跳调仓 / 报警). Step 2+ 可加自动削单.
    """


class PlatformOrderRouter(OrderRouter):
    """SDK OrderRouter concrete — signals → Order list with idempotency + turnover cap.

    Args:
      lot_size: A 股整手 (默认 100). 测试可注入 1 简化场景.
      cancel_callable: 撤单 DI (Step 2 wire QMT). None → cancel_stale raise NotImplemented.

    Usage:
      >>> router = PlatformOrderRouter()
      >>> orders = router.route(signals, current_positions, capital_allocation)
      >>> for order in orders:
      ...     # Step 2 wire: execution_service 真下单 + audit
      ...     pass
    """

    def __init__(
        self,
        lot_size: int = DEFAULT_LOT_SIZE,
        cancel_callable: Callable[[int], list[str]] | None = None,
    ) -> None:
        if lot_size < 1:
            raise ValueError(f"lot_size 必须 ≥ 1, got {lot_size}")
        self._lot_size = lot_size
        self._cancel_callable = cancel_callable

    @property
    def lot_size(self) -> int:
        """Read-only access to lot_size (test 用)."""
        return self._lot_size

    # ─── route: signals → orders ────────────────────────────────────

    def route(
        self,
        signals: list[Signal],
        current_positions: dict[str, int],
        capital_allocation: dict[str, Decimal],
        turnover_cap: float = 0.5,
    ) -> list[Order]:
        """计算目标持仓 vs 当前持仓的 diff, 产生订单 list.

        Args:
          signals: target portfolio signals (sum target_weight ≤ 1.0 per strategy).
          current_positions: code → 当前持仓 quantity (整手).
          capital_allocation: strategy_id → 分配资本.
          turnover_cap: 总 BUY value / sum(capital) 比例上限 (默认 0.5).

        Returns:
          Order 列表, 每 entry 含 (order_id idempotent / strategy_id / code / side / quantity / trade_date).

        Raises:
          KeyError: signal.metadata 缺 'price' 字段.
          ValueError: signal.metadata['price'] ≤ 0 / target_weight < 0.
          IdempotencyViolation: 同 order_id 在返回列表中重复 (invariant 防御, 理论不发生).
          TurnoverCapExceeded: 总 BUY value 占 capital 比例超 turnover_cap.
          InsufficientCapital: 信号未匹配 capital_allocation 中的 strategy_id.
        """
        if not signals:
            _logger.info("route: empty signals -> empty orders")
            return []

        orders: list[Order] = []
        seen_order_ids: set[str] = set()
        total_buy_value: Decimal = Decimal("0")
        # P2 python-reviewer (PR #108) 采纳: sum() 直接接 .values(), 删冗余生成器.
        total_capital: Decimal = sum(
            capital_allocation.values(),
            start=Decimal("0"),
        )

        # P1 reviewer (PR #108) 采纳: 检测 orphan positions (current_positions 中
        # 的 code 未在 signals) 并 warn. caller 契约: 必为 exit 持仓显式发 weight=0
        # signal, 否则 router 不会自动生成 SELL 订单 (避免 orphan 的 strategy_id 推断歧义).
        # Step 3 daily_pipeline wire 时由 multi-strategy diff prev_holdings 路径补齐.
        signal_codes = {sig.code for sig in signals}
        orphan_positions = {
            code: qty for code, qty in current_positions.items()
            if code not in signal_codes and qty > 0
        }
        if orphan_positions:
            _logger.warning(
                "route: %d orphan positions in current_positions but not in signals "
                "(no SELL orders will be generated for them). "
                "caller MUST emit target_weight=0 signals for exits. orphans=%s",
                len(orphan_positions),
                sorted(orphan_positions.keys())[:10],  # 限 10 个防 log 爆
            )

        for sig in signals:
            # ─── Validate signal.metadata ──────────────────────
            if "price" not in sig.metadata:
                raise KeyError(
                    f"PlatformOrderRouter.route: signal.metadata 缺 'price' "
                    f"(strategy_id={sig.strategy_id} code={sig.code}). "
                    "caller 必预注入当日价 (close / 实时 last)."
                )
            # P1 reviewer (PR #108) code+python 采纳: 拆 type guard vs value guard,
            # 拓宽到 (int, float, Decimal, np.floating-duck-type), 加 NaN/inf 防御.
            # 原 isinstance(price, (int, float)) 拒 np.float64 (Step 2 wire DAL price 必炸).
            price_raw = sig.metadata["price"]
            try:
                price = float(price_raw)
            except (TypeError, ValueError) as e:
                raise TypeError(
                    f"signal.metadata['price'] 必须可 float() 转换, got {type(price_raw).__name__}: "
                    f"{price_raw!r} (strategy_id={sig.strategy_id} code={sig.code})."
                ) from e
            if math.isnan(price) or math.isinf(price):
                raise ValueError(
                    f"signal.metadata['price'] 不能 NaN/inf, got {price_raw!r} "
                    f"(strategy_id={sig.strategy_id} code={sig.code})."
                )
            if price <= 0:
                raise ValueError(
                    f"signal.metadata['price'] 必须 > 0, got {price_raw!r} "
                    f"(strategy_id={sig.strategy_id} code={sig.code})."
                )
            if sig.target_weight < 0:
                raise ValueError(
                    f"target_weight 不能 < 0, got {sig.target_weight} "
                    f"(strategy_id={sig.strategy_id} code={sig.code})."
                )

            # ─── Lookup capital ──────────────────────────────
            if sig.strategy_id not in capital_allocation:
                raise InsufficientCapital(
                    f"signal.strategy_id={sig.strategy_id!r} 不在 capital_allocation "
                    f"keys={list(capital_allocation.keys())}. caller 应 pre-allocate."
                )
            capital = capital_allocation[sig.strategy_id]

            # ─── Compute target_shares (整手 round-down, 对齐 paper_broker:359) ─
            # P1 code-reviewer (PR #108) 采纳: 保 Decimal 精度直到最终 int() 截位.
            # 原 float(capital) × float(weight) 违反 CLAUDE.md "金融金额用 Decimal" 规则.
            # price 来自 metadata float — 不可 Decimal 化, 仅在 / price 时桥到 float.
            target_value_d = capital * Decimal(str(sig.target_weight))
            raw_shares = float(target_value_d) / price
            target_shares = int(raw_shares / self._lot_size) * self._lot_size

            # ─── Compute delta vs current ─────────────────────
            curr_shares = current_positions.get(sig.code, 0)
            delta = target_shares - curr_shares
            if delta == 0:
                continue  # 不生成 0 量单

            side = "BUY" if delta > 0 else "SELL"
            quantity = abs(delta)

            # ─── Generate idempotent order_id ─────────────────
            order_id = self._compute_order_id(
                sig.strategy_id, sig.trade_date, sig.code, side, target_shares
            )
            if order_id in seen_order_ids:
                # invariant 违反 — 同 (strategy_id, trade_date, code, side, target_shares)
                # 在 signals list 中重复出现, caller 应去重
                raise IdempotencyViolation(
                    f"order_id={order_id} 重复 (strategy_id={sig.strategy_id} code={sig.code}). "
                    "caller signal list 含重复 (strategy/code/trade_date) entry."
                )
            seen_order_ids.add(order_id)

            # ─── Track total BUY value for turnover_cap check ─
            if side == "BUY":
                total_buy_value += Decimal(str(quantity)) * Decimal(str(price))

            orders.append(
                Order(
                    order_id=order_id,
                    strategy_id=sig.strategy_id,
                    code=sig.code,
                    side=side,
                    quantity=quantity,
                    trade_date=sig.trade_date,
                )
            )

        # ─── turnover_cap 全局检查 (放循环外, 防误中止) ──────────
        # P2 reviewer (PR #108) 采纳: total_capital==0 时显式 warn (铁律 33 fail-loud
        # 观测性), 非静默跳过. Step 2+ 评估是否 raise.
        if total_capital == 0:
            _logger.warning(
                "route: total_capital=0 (capital_allocation 全 0 或空), "
                "turnover_cap 检查跳过. orders=%d total_buy_value=%s",
                len(orders),
                total_buy_value,
            )
        elif total_buy_value > total_capital * Decimal(str(turnover_cap)):
            raise TurnoverCapExceeded(
                f"总 BUY value {total_buy_value} 超 turnover_cap {turnover_cap} × "
                f"sum(capital) {total_capital} = {total_capital * Decimal(str(turnover_cap))}. "
                "caller 应削单或跳本次调仓."
            )

        _logger.info(
            "route: signals=%d -> orders=%d total_buy_value=%s capital=%s turnover=%.2f%%",
            len(signals),
            len(orders),
            total_buy_value,
            total_capital,
            float(total_buy_value / total_capital * 100) if total_capital > 0 else 0,
        )
        return orders

    # ─── cancel_stale: stub for Step 1 ──────────────────────────────

    def cancel_stale(self, cutoff_seconds: int = 300) -> list[str]:
        """撤销超时未成交订单 — Step 1 是 DI stub.

        Args:
          cutoff_seconds: 超时阈值 (秒, 默认 300 = 5min).

        Returns:
          已撤 order_id 列表.

        Raises:
          NotImplementedError: 未提供 cancel_callable DI (Step 1 默认状态).
            Step 2 PR 会注入 QMT cancel callable.
        """
        if self._cancel_callable is None:
            raise NotImplementedError(
                "PlatformOrderRouter.cancel_stale: 需 DI `cancel_callable` 才能撤单. "
                "Step 1 SDK 不接生产 QMT, 由 Step 2 PR wire `execution_service` cancel 路径."
            )
        return self._cancel_callable(cutoff_seconds)

    # ─── helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _compute_order_id(
        strategy_id: str,
        trade_date: date,
        code: str,
        side: str,
        target_shares: int,
    ) -> str:
        """sha256(json([strategy_id, trade_date, code, side, target_shares]))[:16] 幂等键.

        target_shares 而非 quantity 入 hash: 同 target_shares 对应同 order 语义,
        即便 caller 拆分多次 route() (curr_shares 不同 → quantity 不同), order_id 仍稳定.

        P1 python-reviewer (PR #108) 采纳: 用 json.dumps 替代 `|` 分隔 f-string, 防
        用户可控 strategy_id 含 `|` 造碰撞 (e.g. 'strat|v2' + '|date' vs 'strat' +
        'v2|date'). json 自然 escape 引号防混淆. ensure_ascii=False 保中文 strategy_id.
        """
        material = json.dumps(
            [strategy_id, trade_date.isoformat(), code, side, target_shares],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_ORDER_ID_HEX_LEN]
