"""QuantMind Core Platform (QCP) — 共享数据类型.

本模块定义 12 Framework 之间共享的值对象 (Value Object) 与枚举.
所有类型均为 frozen dataclass / Enum, 天然不可变, 线程安全, 序列化友好.

禁忌 (铁律 31 / 34):
  - 不引入 runtime 依赖 (pydantic / sqlalchemy / attrs)
  - 不嵌入业务判断 (e.g. 不在此模块判定 "is_pt_production")
  - 不含 IO (纯数据容器)

实施时机:
  - Signal/Order: MVP 1.4 (Factor) / MVP 3.2 (Signal/Exec) 消费
  - Verdict: MVP 3.4 (Eval Gate)
  - BacktestMode: MVP 2.3 (Backtest)
  - Severity: MVP 4.1 (Observability)
  - ResourceProfile/Priority: MVP 3.0 (Resource, U6)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Signal:
    """策略产出的目标仓位信号.

    Args:
      strategy_id: 策略唯一标识 (e.g. "S1_monthly_ranking")
      code: 证券代码 (带市场后缀, e.g. "600519.SH")
      target_weight: 目标权重 [0.0, 1.0]
      score: 原始打分 (策略内部, 未归一化)
      trade_date: 信号生成日 (交易日, 非自然日)
      metadata: 扩展字段 (如 factor 分解, regime 标签)
    """

    strategy_id: str
    code: str
    target_weight: float
    score: float
    trade_date: date
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Order:
    """信号下游的订单抽象 (pre-execution).

    Args:
      order_id: 订单唯一 ID (幂等键)
      strategy_id: 归属策略
      code: 证券代码
      side: 方向 ("BUY" / "SELL")
      quantity: 整手股数 (A 股 100 股倍数)
      trade_date: 下单交易日
    """

    order_id: str
    strategy_id: str
    code: str
    side: str
    quantity: int
    trade_date: date


@dataclass(frozen=True)
class Verdict:
    """Evaluation Gate / Strategy 评估统一输出.

    Args:
      subject: 被评估对象 (factor_name 或 strategy_id)
      passed: 是否通过所有 Gate
      p_value: paired bootstrap p 值 (可为空, 若非统计类评估)
      blockers: 未通过的 Gate 清单 (e.g. ["G9_novelty", "G10_economic"])
      details: 详细指标 (ic_mean / decay / corr 等)
    """

    subject: str
    passed: bool
    p_value: float | None
    blockers: list[str]
    details: dict[str, Any]


class BacktestMode(Enum):
    """BacktestRunner 支持的运行模式.

    - QUICK_1Y: 简化成本的快速回测 (AI 闭环内循环淘汰用)
    - FULL_5Y: 标准 5 年全量回测
    - FULL_12Y: 12 年长周期回测 (含多个 regime)
    - WF_5FOLD: 5-fold Walk-Forward 严格 OOS 验证 (铁律 8)
    """

    QUICK_1Y = "quick_1y"
    FULL_5Y = "full_5y"
    FULL_12Y = "full_12y"
    WF_5FOLD = "wf_5fold"


class Severity(Enum):
    """告警 / 事件严重程度.

    P0 事故需立即处理 (e.g. PT 熔断, DB 崩溃).
    P1 告警需当日响应 (e.g. factor IC 衰减).
    P2 信息记录 (e.g. universe 轮换完成).
    INFO 普通事件 (e.g. 调度启动).
    """

    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    INFO = "info"


@dataclass(frozen=True)
class ResourceProfile:
    """资源声明 (Framework #11 ResourceManager 用).

    Args:
      ram_gb: 预计峰值内存 (GB)
      cpu_cores: CPU 核数需求 (默认 1)
      gpu_vram_gb: GPU 显存需求 (GB, 0 表示不用 GPU)
      exclusive_pools: 需独占的资源池名集合 (如 "heavy_data", "db_heavy")
      db_connections: 预计 DB 连接数 (0 表示不访问 DB)

    铁律 9: 资源密集任务必须经 ResourceManager 仲裁, 禁止裸并发.
    """

    ram_gb: float
    cpu_cores: int = 1
    gpu_vram_gb: float = 0.0
    exclusive_pools: tuple[str, ...] = ()
    db_connections: int = 0


class Priority(Enum):
    """调度优先级 (高 → 低).

    PT_PRODUCTION: 生产交易信号 / 下单, 最高优先级
    GP_MINING: 因子挖掘任务
    RESEARCH_ACTIVE: 活跃研究 (用户正在看)
    RESEARCH_BATCH: 批量研究 (过夜跑)
    BACKGROUND: 后台任务 (monitor / cleanup)
    """

    PT_PRODUCTION = "pt_production"
    GP_MINING = "gp_mining"
    RESEARCH_ACTIVE = "research_active"
    RESEARCH_BATCH = "research_batch"
    BACKGROUND = "background"
