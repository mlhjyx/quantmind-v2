"""权重/仓位调节器包。

R3架构：核心策略 + Modifier链叠加。
Modifier不独立选股，只调节核心策略的目标权重。

组件:
- ModifierBase: 调节器抽象基类
- RegimeModifier: 基于HMM/Vol状态的仓位缩放
- VwapModifier: 基于vwap_bias的个股权重调节（Phase 1）
- EventModifier: 基于事件信号的个股权重调节（Phase 1）
"""

from engines.modifiers.base import ModifierBase
from engines.modifiers.regime_modifier import RegimeModifier

__all__ = ["ModifierBase", "RegimeModifier"]
