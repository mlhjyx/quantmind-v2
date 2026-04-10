"""YAML配置加载器 — 统一配置源。

从YAML文件加载策略/回测/执行配置，替代散落在.env/config.py/signal_engine中的参数。
.env保留环境级配置(DB/API token/QMT路径等)，策略级配置全部走YAML。

用法:
    from app.services.config_loader import load_config, to_backtest_config
    cfg = load_config("configs/backtest_5yr.yaml")
    bt_config = to_backtest_config(cfg)
    directions = get_directions(cfg)
"""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml
from engines.backtest.config import BacktestConfig, PMSConfig
from engines.signal_engine import SignalConfig
from engines.slippage_model import SlippageConfig

logger = structlog.get_logger(__name__)


def load_config(yaml_path: str | Path) -> dict:
    """加载YAML配置文件。

    Args:
        yaml_path: YAML文件路径(绝对或相对于项目根目录)

    Returns:
        解析后的配置字典

    Raises:
        FileNotFoundError: 文件不存在
        yaml.YAMLError: YAML格式错误
    """
    path = Path(yaml_path)
    if not path.is_absolute():
        # 相对路径从项目根目录解析
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        path = project_root / path

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"配置文件格式错误(期望dict): {path}")

    logger.info("Loaded config: %s", path.name)
    return config


def to_backtest_config(config: dict) -> BacktestConfig:
    """YAML配置 → BacktestConfig dataclass。"""
    bt = config.get("backtest", {})
    exe = config.get("execution", {})
    costs = exe.get("costs", {})
    slip = exe.get("slippage", {})
    slip_cfg = slip.get("config", {})
    pms_cfg = exe.get("pms", {})
    strategy = config.get("strategy", {})

    # SlippageConfig
    slippage_config = SlippageConfig(
        Y_large=slip_cfg.get("Y_large", 0.8),
        Y_mid=slip_cfg.get("Y_mid", 1.0),
        Y_small=slip_cfg.get("Y_small", 1.5),
        base_bps_large=slip_cfg.get("base_bps_large", 3.0),
        base_bps_mid=slip_cfg.get("base_bps_mid", 5.0),
        base_bps_small=slip_cfg.get("base_bps_small", 8.0),
        sell_penalty=slip_cfg.get("sell_penalty", 1.2),
        gap_penalty_factor=slip_cfg.get("gap_penalty_factor", 0.5),
    )

    # PMSConfig
    pms_tiers = [
        (t["gain"], t["drawdown"]) for t in pms_cfg.get("tiers", [])
    ]
    pms = PMSConfig(
        enabled=pms_cfg.get("enabled", False),
        tiers=pms_tiers or [(0.30, 0.15), (0.20, 0.12), (0.10, 0.10)],
        exec_mode=pms_cfg.get("exec_mode", "next_open"),
    )

    # 印花税
    stamp_tax_mode = costs.get("stamp_tax", "historical")
    historical_stamp_tax = stamp_tax_mode == "historical"

    return BacktestConfig(
        initial_capital=float(bt.get("initial_capital", 1_000_000)),
        top_n=int(strategy.get("top_n", 20)),
        rebalance_freq=strategy.get("rebalance_freq", "monthly"),
        slippage_mode=slip.get("mode", "volume_impact"),
        slippage_config=slippage_config,
        commission_rate=float(costs.get("commission_rate", 0.0000854)),
        stamp_tax_rate=float(costs.get("stamp_tax_rate", 0.0005)),
        historical_stamp_tax=historical_stamp_tax,
        transfer_fee_rate=float(costs.get("transfer_fee_rate", 0.00001)),
        lot_size=int(bt.get("lot_size", 100)),
        turnover_cap=float(strategy.get("turnover_cap", 0.50)),
        benchmark_code=bt.get("benchmark", "000300.SH"),
        volume_cap_pct=float(bt.get("volume_cap_pct", 0.10)),
        pms=pms,
    )


def to_signal_config(config: dict) -> SignalConfig:
    """YAML配置 → SignalConfig dataclass。"""
    strategy = config.get("strategy", {})
    factors = strategy.get("factors", [])

    return SignalConfig(
        factor_names=[f["name"] for f in factors],
        top_n=int(strategy.get("top_n", 20)),
        weight_method=strategy.get("compose", "equal"),
        rebalance_freq=strategy.get("rebalance_freq", "monthly"),
        industry_cap=float(strategy.get("industry_cap", 1.0)),
        turnover_cap=float(strategy.get("turnover_cap", 0.50)),
        cash_buffer=float(strategy.get("cash_buffer", 0.0)),
        size_neutral_beta=float(strategy.get("size_neutral_beta", 0.0)),
    )


def get_directions(config: dict) -> dict[str, int]:
    """从YAML factors列表提取 {factor_name: direction}。"""
    factors = config.get("strategy", {}).get("factors", [])
    return {f["name"]: int(f["direction"]) for f in factors}


def get_data_range(config: dict) -> tuple[str, str]:
    """从YAML获取回测日期范围。"""
    data = config.get("data", {})
    start = data.get("start_date", "2021-01-01")
    end = data.get("end_date", "2025-12-31")
    return start, end


def config_hash(config: dict) -> str:
    """计算配置的SHA256 hash（用于回测可复现性）。"""
    import hashlib

    content = yaml.dump(config, sort_keys=True, default_flow_style=False)
    return hashlib.sha256(content.encode()).hexdigest()[:16]
