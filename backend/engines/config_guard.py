"""配置一致性守卫 — 防止分析脚本使用与Paper Trading不一致的因子集。

背景（LL-010 + LL-013）:
- LL-010: run_backtest.py默认8因子 vs Paper Trading 5因子，导致Sharpe误诊
- LL-013: IC分析用错误基线因子集，导致v1.2升级被错误推荐

铁律 34 落地 (2026-04-15 Phase B M3):
- `check_config_alignment()` 在 PT 启动前校验 .env / pt_live.yaml / PAPER_TRADING_CONFIG
  三处关键参数对齐, 任何漂移 RAISE `ConfigDriftError` (不允许只报 warning)
- 配对项: top_n / industry_cap / size_neutral_beta / turnover_cap / factor_list /
  rebalance_freq. `.env` 不覆盖 factor_list / freq / turnover_cap 时仅做 yaml↔python 对比
- F45 / F62 / F40 / F82 防复发

BH-FDR校正（研究报告#2）:
- 累积测试总数M从FACTOR_TEST_REGISTRY.md自动读取
- 校正后阈值 = alpha * k / M（Benjamini-Hochberg步进法）

用法:
    from engines.config_guard import (
        assert_baseline_config, print_config_header, check_config_alignment,
        ConfigDriftError, get_cumulative_test_count, bh_fdr_adjusted_threshold,
    )

    # 脚本开头打印当前配置（人工核对）
    print_config_header()

    # 如果脚本自定义了因子列表，检查是否与基线一致
    assert_baseline_config(my_factor_list, config_source="my_script.py")

    # PT 启动前三源对齐硬校验 (铁律 34)
    check_config_alignment()  # 不一致 → RAISE

    # BH-FDR校正
    M = get_cumulative_test_count()  # 从FACTOR_TEST_REGISTRY.md读取
    threshold = bh_fdr_adjusted_threshold(alpha=0.05)
"""

from pathlib import Path
from typing import Any

import structlog

from engines.signal_engine import PAPER_TRADING_CONFIG

logger = structlog.get_logger(__name__)

# ANSI颜色码
_YELLOW = "\033[93m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def print_config_header() -> None:
    """打印当前PAPER_TRADING_CONFIG的完整配置。

    用于脚本开头强制输出，让人一眼看到在用什么配置。
    """
    cfg = PAPER_TRADING_CONFIG
    factors_str = ", ".join(cfg.factor_names)
    n_factors = len(cfg.factor_names)

    print(f"\n{_BOLD}{'=' * 60}{_RESET}")
    print(
        f"{_BOLD}{_CYAN}  PAPER_TRADING_CONFIG (.env驱动, WLS中性化+涨跌停板块+volume_cap+zscore clip+mergesort){_RESET}"
    )
    print(f"{'=' * 60}")
    print(f"  因子数量:   {n_factors}")
    print(f"  因子列表:   [{factors_str}]")
    print(f"  Top-N:      {cfg.top_n}  {_YELLOW}(.env PT_TOP_N){_RESET}")
    print(f"  调仓频率:   {cfg.rebalance_freq}")
    print(f"  权重方法:   {cfg.weight_method}")
    print(f"  行业上限:   {cfg.industry_cap:.0%}  {_YELLOW}(.env PT_INDUSTRY_CAP){_RESET}")
    print(f"  换手上限:   {cfg.turnover_cap:.0%}")
    sn_status = f"{cfg.size_neutral_beta:.2f}" if cfg.size_neutral_beta > 0 else "OFF"
    print(f"  Size-Neutral: {sn_status}  {_YELLOW}(.env PT_SIZE_NEUTRAL_BETA){_RESET}")
    print(f"{'=' * 60}\n")


def assert_baseline_config(
    factor_names: list[str],
    config_source: str = "unknown",
) -> bool:
    """检查传入的factor_names是否与PAPER_TRADING_CONFIG一致。

    Args:
        factor_names: 待检查的因子名称列表。
        config_source: 调用来源（脚本名），用于日志定位。

    Returns:
        True 如果一致，False 如果不一致。

    不一致时打印WARNING + 详细差异（多了哪些、少了哪些），
    并打印当前配置供人工确认。不会raise异常（脚本可选择继续执行）。
    """
    baseline = set(PAPER_TRADING_CONFIG.factor_names)
    current = set(factor_names)

    if baseline == current:
        logger.info(
            "[config_guard] %s: 因子集与PAPER_TRADING_CONFIG一致 (%d因子)",
            config_source,
            len(baseline),
        )
        return True

    # ---- 不一致：打印详细差异 ----
    extra = sorted(current - baseline)
    missing = sorted(baseline - current)

    print(f"\n{_BOLD}{_RED}{'!' * 60}{_RESET}")
    print(f"{_BOLD}{_RED}  WARNING: 因子集与PAPER_TRADING_CONFIG不一致!{_RESET}")
    print(f"{_RED}  来源: {config_source}{_RESET}")
    print(f"{'!' * 60}")

    if extra:
        print(f"  {_YELLOW}多出的因子 (不在基线中): {extra}{_RESET}")
    if missing:
        print(f"  {_YELLOW}缺少的因子 (基线中有):   {missing}{_RESET}")

    print(f"\n  当前传入 ({len(factor_names)}因子): {sorted(factor_names)}")
    print(
        f"  基线配置 ({len(PAPER_TRADING_CONFIG.factor_names)}因子): "
        f"{sorted(PAPER_TRADING_CONFIG.factor_names)}"
    )
    print(f"{'!' * 60}\n")

    # 同时打印完整配置供人工核对
    print_config_header()

    logger.warning(
        "[config_guard] %s: 因子集不一致! 多出=%s, 缺少=%s",
        config_source,
        extra,
        missing,
    )
    return False


# ---------------------------------------------------------------------------
# 三源配置对齐硬校验 (铁律 34, Phase B M3)
# ---------------------------------------------------------------------------

# pt_live.yaml 相对项目根目录的默认路径
_DEFAULT_PT_YAML = "configs/pt_live.yaml"

# 浮点比较容差 (避免 0.50 vs 0.5 等表示差异导致假漂移)
_FLOAT_TOL = 1e-9


# ConfigDriftError 已迁移到 backend.qm_platform.config.auditor (MVP 1.2 Config Management).
# 本 alias 保 老 API 兼容 (test_config_guard / run_paper_trading 等 51 处 import).
from backend.qm_platform.config.auditor import ConfigDriftError  # noqa: E402, F401


def _values_equal(a: Any, b: Any) -> bool:
    """通用相等比较, 数值走浮点容差, 其他走 `==`."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < _FLOAT_TOL
    return a == b


def _load_pt_yaml(yaml_path: Path | str) -> dict[str, Any]:
    """加载 pt_live.yaml 并抽出策略段 (strategy).

    Raises:
        FileNotFoundError: yaml 文件不存在.
        ValueError: yaml 文件格式不是 dict 或缺少 strategy 段.
    """
    import yaml

    path = Path(yaml_path)
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parent.parent.parent
        path = project_root / path

    if not path.exists():
        raise FileNotFoundError(
            f"pt_live.yaml 未找到: {path}. check_config_alignment 需要 YAML 作为权威源."
        )

    with path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError(f"pt_live.yaml 顶层不是 dict: {path}")

    strategy = config.get("strategy")
    if not isinstance(strategy, dict):
        raise ValueError(f"pt_live.yaml 缺少 'strategy' 段: {path}")

    return strategy


def check_config_alignment(
    *,
    yaml_path: Path | str | None = None,
    env_settings: Any | None = None,
    python_config: Any | None = None,
) -> None:
    """校验 .env / pt_live.yaml / PAPER_TRADING_CONFIG 三源参数对齐 (铁律 34).

    **MVP 1.2 shim**: 函数签名和 raise 行为保 API 兼容, 实际逻辑走
    `backend.qm_platform.config.auditor.PlatformConfigAuditor.check_alignment()`.
    扩展新参数只需改 Platform auditor `_TRIPLE_SOURCE_FIELDS`, 不再改这里.

    Args:
        yaml_path: pt_live.yaml 路径. None 走默认 `configs/pt_live.yaml`.
        env_settings: 注入的 pydantic Settings (测试用). None 时 `from app.config import settings`.
        python_config: 注入的 SignalConfig. None 时 `engines.signal_engine.PAPER_TRADING_CONFIG`.

    Raises:
        ConfigDriftError: 任何一项三源不一致 (strict=True).
        FileNotFoundError: pt_live.yaml 不存在.
    """
    from backend.qm_platform.config.auditor import PlatformConfigAuditor

    if env_settings is None:
        from app.config import settings as env_settings  # type: ignore[no-redef]

    # Settings 对象 → env dict (仅需 Platform auditor 识别的 3 key)
    env_dict: dict[str, str] = {}
    for env_key in ("PT_TOP_N", "PT_INDUSTRY_CAP", "PT_SIZE_NEUTRAL_BETA"):
        val = getattr(env_settings, env_key, None)
        if val is not None:
            env_dict[env_key] = str(val)

    if python_config is None:
        python_config = PAPER_TRADING_CONFIG

    PlatformConfigAuditor().check_alignment(
        yaml_path=yaml_path,
        env=env_dict,
        python_config=python_config,
        strict=True,
    )
    logger.info("[config_guard] check_config_alignment PASS (via Platform auditor)")


# ---------------------------------------------------------------------------
# EXECUTION_MODE 语义完整性校验 (铁律 34 延伸, 防 F17 17 天僵尸配置重演)
# ---------------------------------------------------------------------------


def assert_execution_mode_integrity(
    *,
    mode: str | None = None,
    conn: Any | None = None,
    recent_days: int = 7,
) -> None:
    """EXECUTION_MODE 语义完整性校验 (铁律 34 延伸, 防 F17 重演).

    背景 (F17 2026-04-20 Session 19~20): `.env` EXECUTION_MODE=paper 17 天
    未切 live, 致 settings.EXECUTION_MODE='paper' → risk_control 等动态读写全走
    paper namespace, cb_state live 0 行. 根因: triple-source config_guard 不
    覆盖此单源字段, PR-A 合入后无启动守门.

    本函数在 PT 启动前校验 (run_paper_trading Step 0.5 集成):
    1. mode 必须为 'paper' 或 'live' (Pydantic 已拦, 此处兜底)
    2. mode='paper' 时, 若 trade_log 最近 N 天存在 live 行 → WARN (可能误切 paper)
    3. 不 coupling QMT 连接/schtasks 状态 (运维层独立, 避免 blast radius)

    Args:
        mode: 显式传入 (测试用). None 时走 `settings.EXECUTION_MODE`.
        conn: psycopg2 连接 (测试注入). None 时走 get_sync_conn().
        recent_days: 检测 live trade_log 的回溯天数 (默认 7).

    Raises:
        ConfigDriftError: mode 非 'paper'/'live' (bad config).
    """
    if mode is None:
        from app.config import settings

        mode = settings.EXECUTION_MODE

    if mode not in ("paper", "live"):
        # ConfigDriftError 签名: list[dict[{param, sources}]] (MVP 1.2 Platform auditor)
        raise ConfigDriftError(
            [
                {
                    "param": "EXECUTION_MODE",
                    "sources": {
                        ".env:EXECUTION_MODE": mode,
                        "allowed": "'paper' or 'live'",
                    },
                }
            ]
        )

    if mode == "paper":
        from datetime import date, timedelta

        cutoff = date.today() - timedelta(days=recent_days)
        own_conn = False
        if conn is None:
            try:
                from app.services.db import get_sync_conn

                conn = get_sync_conn()
                own_conn = True
            except Exception as e:
                logger.warning(
                    "[config_guard.EXECUTION_MODE] DB 连接失败, 跳过 live trade_log 交叉检测: %s",
                    e,
                )
                return

        try:
            # review MEDIUM 采纳: cursor 走 context manager, 防 fetch error 时 cur 泄漏
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*), MAX(trade_date) FROM trade_log "
                    "WHERE execution_mode = 'live' AND trade_date >= %s",
                    (cutoff,),
                )
                row = cur.fetchone()
            cnt = int(row[0]) if row else 0
            max_d = row[1] if row else None
            if cnt > 0:
                logger.warning(
                    "[config_guard.EXECUTION_MODE] mode='paper' 但最近 %d 日内有 %d 条 live trade_log "
                    "(最新 %s). 疑似 F17 误切 paper — 若实际应 live, 改 .env:EXECUTION_MODE=live.",
                    recent_days,
                    cnt,
                    max_d,
                )
            else:
                logger.info(
                    "[config_guard.EXECUTION_MODE] mode='paper' 校验通过 (近 %d 日无 live trade_log)",
                    recent_days,
                )
        except Exception as e:
            logger.warning(
                "[config_guard.EXECUTION_MODE] live trade_log 交叉检测异常 (非阻塞): %s",
                e,
            )
        finally:
            if own_conn and conn is not None:
                import contextlib

                with contextlib.suppress(Exception):
                    conn.close()  # silent_ok: close 失败不影响校验结果
    else:
        # mode == 'live'
        logger.info(
            "[config_guard.EXECUTION_MODE] mode='live' — 真金模式, "
            "若 schtasks QuantMind_DailyExecute Enabled, 09:31 将真实下单. "
            "请确认 QMT 连接 + 资金就位.",
        )


# ---------------------------------------------------------------------------
# LIVE_TRADING_DISABLED 双锁完整性校验 (V3 §14 mode 15, HC-2b G6)
# ---------------------------------------------------------------------------


def assert_live_trading_lock_integrity(
    *,
    execution_mode: str | None = None,
    live_trading_disabled: bool | None = None,
) -> None:
    """LIVE_TRADING_DISABLED 双锁完整性校验 (V3 §14 mode 15, HC-2b G6).

    背景 (HC-2a §14 enforcement matrix G6 finding): V3 §14 mode 15
    "LIVE_TRADING_DISABLED 双锁失效" — .env 误改致双锁不一致. config_guard /
    PlatformConfigAuditor 校验 EXECUTION_MODE (`assert_execution_mode_integrity`)
    但 **0 校验 LIVE_TRADING_DISABLED** — 双锁第 2 锁缺 startup gate, 此前仅靠
    call-time `live_trading_guard.assert_live_trading_allowed` 一层. 本函数补
    startup gate (双层 defense — startup + call-time).

    双锁 = EXECUTION_MODE + LIVE_TRADING_DISABLED. 一致性约束:
      - EXECUTION_MODE=paper → LIVE_TRADING_DISABLED 必 True (paper 模式真金必锁).
        违反 = 双锁不一致 (一锁说 paper, 另一锁放行真金) → RAISE ConfigDriftError.
      - EXECUTION_MODE=live + LIVE_TRADING_DISABLED=True = fail-secure 安全态
        (live 模式但交易仍被 call-time guard 锁) → INFO log, NOT raise (保守方向
        不阻断启动).

    本函数在 PT 启动前校验 (run_paper_trading Step 0.5, `assert_execution_mode_integrity`
    之后调用 — 故 execution_mode 此时已被前者校验为 'paper'/'live').

    Args:
        execution_mode: 显式传入 (测试用). None → `settings.EXECUTION_MODE`.
        live_trading_disabled: 显式传入 (测试用). None → `settings.LIVE_TRADING_DISABLED`.

    Raises:
        ConfigDriftError: EXECUTION_MODE=paper 但 LIVE_TRADING_DISABLED 非 True
            (双锁不一致 — V3 §14 mode 15 双锁失效).
    """
    if execution_mode is None or live_trading_disabled is None:
        from app.config import settings

        if execution_mode is None:
            execution_mode = settings.EXECUTION_MODE
        if live_trading_disabled is None:
            live_trading_disabled = settings.LIVE_TRADING_DISABLED

    if execution_mode == "paper":
        if not live_trading_disabled:
            # ConfigDriftError 签名: list[dict[{param, sources}]] (MVP 1.2 Platform auditor)
            raise ConfigDriftError(
                [
                    {
                        "param": "LIVE_TRADING_DISABLED",
                        "sources": {
                            ".env:EXECUTION_MODE": execution_mode,
                            ".env:LIVE_TRADING_DISABLED": str(live_trading_disabled),
                            "expected": (
                                "EXECUTION_MODE=paper 要求 LIVE_TRADING_DISABLED=true "
                                "(双锁一致性, V3 §14 mode 15)"
                            ),
                        },
                    }
                ]
            )
        logger.info(
            "[config_guard.LIVE_TRADING] 双锁一致性校验通过 "
            "(EXECUTION_MODE=paper + LIVE_TRADING_DISABLED=true)",
        )
    elif execution_mode == "live":
        if live_trading_disabled:
            logger.info(
                "[config_guard.LIVE_TRADING] mode='live' 但 LIVE_TRADING_DISABLED=true "
                "— fail-secure 安全态 (live 模式真金交易仍被 call-time guard 阻断). "
                "若实际应放行真金, 改 .env:LIVE_TRADING_DISABLED=false + 双因素 OVERRIDE.",
            )
        else:
            logger.info(
                "[config_guard.LIVE_TRADING] mode='live' + LIVE_TRADING_DISABLED=false "
                "— 真金放行态, 请确认 QMT 连接 + 资金就位.",
            )
    # else: unknown mode — assert_execution_mode_integrity 已 raise, 本函数不重复校验


# ---------------------------------------------------------------------------
# BH-FDR 多重检验校正
# ---------------------------------------------------------------------------

# FACTOR_TEST_REGISTRY.md的默认路径（项目根目录）
_REGISTRY_PATH: Path | None = None


def _resolve_registry_path() -> Path:
    """解析FACTOR_TEST_REGISTRY.md路径。

    搜索顺序:
    1. 显式设置的 _REGISTRY_PATH（测试注入用）
    2. 从当前文件向上查找项目根目录下的 FACTOR_TEST_REGISTRY.md
    """
    if _REGISTRY_PATH is not None:
        return _REGISTRY_PATH

    # 从 backend/engines/config_guard.py 向上两层到项目根
    project_root = Path(__file__).resolve().parent.parent.parent
    return project_root / "FACTOR_TEST_REGISTRY.md"


def set_registry_path(path: Path | str | None) -> None:
    """显式设置FACTOR_TEST_REGISTRY.md路径（主要用于测试注入）。

    Args:
        path: 注册表文件路径。传None恢复默认行为。
    """
    global _REGISTRY_PATH
    _REGISTRY_PATH = Path(path) if path is not None else None


def get_cumulative_test_count(registry_path: Path | str | None = None) -> int:
    """从FACTOR_TEST_REGISTRY.md读取累积测试总数M。

    解析Markdown表格，统计数据行数（排除header行和分隔符行）。
    排除标注为"重复验证"的条目（原因列含"重复验证"或"不计入"）。

    Args:
        registry_path: 注册表文件路径。None则使用默认路径。

    Returns:
        累积测试总数M（正整数）。

    Raises:
        FileNotFoundError: 注册表文件不存在。
        ValueError: 文件中未找到有效的因子测试记录。
    """
    path = Path(registry_path) if registry_path is not None else _resolve_registry_path()

    if not path.exists():
        raise FileNotFoundError(f"FACTOR_TEST_REGISTRY.md 未找到: {path}\n请先创建因子测试注册表。")

    content = path.read_text(encoding="utf-8")

    count = 0

    for line in content.splitlines():
        line = line.strip()
        # 跳过非表格行
        if not line.startswith("|"):
            continue
        # 跳过 header 和分隔符
        if "因子名" in line or "---" in line:
            continue
        # 检查是否是数据行（第一列是数字）
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if not cells:
            continue
        try:
            int(cells[0])  # 第一列是序号
        except ValueError:
            continue

        # 排除标注为"重复验证"或"不计入独立测试"的条目
        row_text = line.lower()
        if "重复验证" in row_text or "不计入" in row_text:
            continue

        count += 1

    if count == 0:
        raise ValueError(f"FACTOR_TEST_REGISTRY.md 中未找到有效的因子测试记录: {path}")

    logger.info("[config_guard] 累积因子测试总数 M = %d", count)
    return count


def bh_fdr_adjusted_threshold(
    alpha: float = 0.05,
    rank: int = 1,
    registry_path: Path | str | None = None,
) -> float:
    """计算BH-FDR校正后的显著性阈值。

    Benjamini-Hochberg步进法: 对第k个因子(按p-value排序),
    校正阈值 = alpha * k / M

    当rank=1时，返回最严格的阈值（最小p-value需要通过的门槛）。
    这是"新因子要通过FDR校正至少需要多显著"的保守估计。

    Args:
        alpha: 目标FDR水平，默认0.05。
        rank: 该因子在所有p-value中的排名(1=最小)。
            默认1，返回最严格的阈值。
        registry_path: 注册表文件路径。None则使用默认路径。

    Returns:
        BH-FDR校正后的显著性阈值。

    Raises:
        ValueError: alpha不在(0,1)范围或rank<1。
    """
    if not 0 < alpha < 1:
        raise ValueError(f"alpha必须在(0,1)范围内，收到: {alpha}")
    if rank < 1:
        raise ValueError(f"rank必须>=1，收到: {rank}")

    m = get_cumulative_test_count(registry_path=registry_path)

    if rank > m:
        raise ValueError(f"rank({rank})不能超过累积测试总数M({m})")

    threshold = alpha * rank / m

    logger.info(
        "[config_guard] BH-FDR阈值: alpha=%.3f, rank=%d, M=%d → threshold=%.6f",
        alpha,
        rank,
        m,
        threshold,
    )
    return threshold


def bh_fdr_check_significance(
    p_values: dict[str, float],
    alpha: float = 0.05,
    registry_path: Path | str | None = None,
) -> dict[str, bool]:
    """对一组因子的p-value做BH-FDR校正，返回每个因子是否显著。

    BH步进法:
    1. 对M个p-value排序: p_(1) <= p_(2) <= ... <= p_(M_batch)
    2. 对第k个(在全局排名中), 阈值 = alpha * k / M_total
    3. 找到最大的k使得 p_(k) <= alpha * k / M_total
    4. 所有排名 <= k 的因子通过

    注意: M_total是累积测试总数（含历史所有测试），不是当前批次的N。

    Args:
        p_values: {因子名: p-value} 字典。
        alpha: 目标FDR水平。
        registry_path: 注册表文件路径。

    Returns:
        {因子名: True/False} 字典，True表示通过FDR校正。
    """
    if not p_values:
        return {}

    m_total = get_cumulative_test_count(registry_path=registry_path)

    # 按p-value排序
    sorted_factors = sorted(p_values.items(), key=lambda x: x[1])

    # BH步进法: 从最大的rank开始，找到第一个通过的
    results: dict[str, bool] = {}
    max_passing_rank = 0

    for rank_in_batch, (_name, pval) in enumerate(sorted_factors, start=1):
        # 使用全局M（累积测试总数），rank用批内排名
        # 保守做法: rank从1开始在当前批次内
        bh_threshold = alpha * rank_in_batch / m_total
        if pval <= bh_threshold:
            max_passing_rank = rank_in_batch

    # 所有排名 <= max_passing_rank 的因子通过
    for rank_in_batch, (name, _pval) in enumerate(sorted_factors, start=1):
        results[name] = rank_in_batch <= max_passing_rank

    # 日志
    n_pass = sum(1 for v in results.values() if v)
    logger.info(
        "[config_guard] BH-FDR校正: %d/%d因子通过 (alpha=%.3f, M=%d)",
        n_pass,
        len(p_values),
        alpha,
        m_total,
    )

    return results
