"""E2E测试: 完整链路 数据查询 → 因子计算 → 信号生成 → NAV写库。

链路:
  FactorService.get_factor_values()   → factor_values 表查询
  FactorService.get_factor_list()     → factor_registry 表查询
  FactorService.get_factor_stats()    → factor_ic_history 统计
  SignalService.generate_signals()    → 信号合成 + 写 signals 表（dry_run）
  PaperTradingService.update_nav_sync → position_snapshot + performance_series 写库

设计决策:
- FactorService 使用 AsyncSession (SQLAlchemy async)
- SignalService 使用 psycopg2 同步连接（干运行 dry_run=True 不写 DB）
- PaperTradingService.update_nav_sync 使用 psycopg2 同步连接
- 所有 DB 写操作测试结束后 ROLLBACK，不污染数据

铁律5: 所有函数签名已通过 grep/read 验证，不信文档。
"""

import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# 确保 backend/ 和项目根在路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─────────────────────────────────────────────────────────────
# 导入守卫：缺少依赖时跳过整个模块
# ─────────────────────────────────────────────────────────────
pytest_asyncio = pytest.importorskip("pytest_asyncio")
asyncpg = pytest.importorskip("asyncpg")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.services.factor_service import FactorService  # noqa: E402
from app.services.paper_trading_service import PaperTradingService  # noqa: E402
from app.services.signal_service import SignalService  # noqa: E402

DATABASE_URL = "postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2"

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """独立 AsyncSession + 事务 ROLLBACK，不污染生产数据。"""
    engine = create_async_engine(DATABASE_URL, echo=False, pool_size=1, max_overflow=0)
    async with engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await txn.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_factor_values(db_session: AsyncSession):
    """向 factor_values 插入 3000 行测试数据（5 因子 × 600 只股票）。

    使用真实 A 股代码前缀，符合 code 字段格式约束。
    事务结束后 ROLLBACK，不影响生产数据。
    """
    factor_names = [
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",
        "amihud_20",
        "bp_ratio",
    ]
    trade_date = date(2024, 1, 15)
    codes = [f"{i:06d}.SZ" for i in range(1, 601)]

    rows = []
    for factor in factor_names:
        for i, code in enumerate(codes):
            raw_val = float(i) / 600.0
            neutral_val = raw_val - 0.5
            rows.append(
                {
                    "code": code,
                    "trade_date": trade_date,
                    "factor_name": factor,
                    "raw_value": raw_val,
                    "neutral_value": neutral_val,
                    "zscore": neutral_val * 2.0,
                }
            )

    # 批量插入（幂等：ON CONFLICT DO NOTHING）
    for row in rows:
        await db_session.execute(
            text(
                """
                INSERT INTO factor_values
                    (code, trade_date, factor_name, raw_value, neutral_value, zscore)
                VALUES
                    (:code, :trade_date, :factor_name, :raw_value, :neutral_value, :zscore)
                ON CONFLICT DO NOTHING
                """
            ),
            row,
        )

    return {"factor_names": factor_names, "trade_date": trade_date, "codes": codes}


# ─────────────────────────────────────────────────────────────
# T1: FactorService — get_factor_values
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_factor_service_get_values_returns_dataframe(
    db_session: AsyncSession, seeded_factor_values
):
    """get_factor_values 返回 DataFrame，列名正确，行数与插入量匹配。"""
    svc = FactorService(db_session)
    trade_date = seeded_factor_values["trade_date"]

    df = await svc.get_factor_values("turnover_mean_20", trade_date, neutralized=True)

    assert isinstance(df, pd.DataFrame), "应返回 DataFrame"
    assert list(df.columns) == ["code", "factor_name", "value"], "列名不匹配"
    # DB 已有生产数据，结果 >= 插入的 600 行
    assert len(df) >= 600, f"期望至少 600 行，实际 {len(df)} 行"
    assert df["factor_name"].iloc[0] == "turnover_mean_20"
    # 确认插入的测试 codes 均在结果中
    returned_codes = set(df["code"].tolist())
    test_codes = {f"{i:06d}.SZ" for i in range(1, 601)}
    assert test_codes.issubset(returned_codes), "测试插入的 600 只股票未全部出现在结果中"


@pytest.mark.asyncio
async def test_factor_service_get_values_with_code_filter(
    db_session: AsyncSession, seeded_factor_values
):
    """code 过滤参数正确缩减结果集。"""
    svc = FactorService(db_session)
    trade_date = seeded_factor_values["trade_date"]
    subset = seeded_factor_values["codes"][:10]

    df = await svc.get_factor_values("turnover_mean_20", trade_date, codes=subset)

    assert len(df) == 10, f"期望 10 行（过滤后），实际 {len(df)} 行"
    returned_codes = set(df["code"].tolist())
    assert returned_codes == set(subset)


@pytest.mark.asyncio
async def test_factor_service_get_values_missing_returns_empty(
    db_session: AsyncSession,
):
    """查询不存在的因子返回空 DataFrame，不抛出异常。"""
    svc = FactorService(db_session)
    df = await svc.get_factor_values(
        "nonexistent_factor_xyz", date(2000, 1, 1), neutralized=True
    )

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    assert list(df.columns) == ["code", "factor_name", "value"]


@pytest.mark.asyncio
async def test_factor_service_raw_vs_neutral(
    db_session: AsyncSession, seeded_factor_values
):
    """raw_value 和 neutral_value 返回不同数值（验证列选择逻辑正确）。"""
    svc = FactorService(db_session)
    trade_date = seeded_factor_values["trade_date"]
    codes_10 = seeded_factor_values["codes"][:10]

    df_raw = await svc.get_factor_values(
        "turnover_mean_20", trade_date, codes=codes_10, neutralized=False
    )
    df_neutral = await svc.get_factor_values(
        "turnover_mean_20", trade_date, codes=codes_10, neutralized=True
    )

    # raw_value ∈ [0, 1)，neutral_value ∈ [-0.5, 0.5)，两者不相等
    assert not df_raw["value"].equals(df_neutral["value"]), (
        "raw 和 neutral 值不应相同"
    )


# ─────────────────────────────────────────────────────────────
# T2: FactorService — get_factor_list
# ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_factor_registry(db_session: AsyncSession):
    """向 factor_registry 插入测试因子。"""
    test_name = f"test_factor_{uuid.uuid4().hex[:8]}"
    await db_session.execute(
        text(
            """
            INSERT INTO factor_registry
                (name, category, direction, status, hypothesis)
            VALUES
                (:name, 'momentum', 1, 'active', 'test hypothesis')
            ON CONFLICT DO NOTHING
            """
        ),
        {"name": test_name},
    )
    return test_name


@pytest.mark.asyncio
async def test_factor_service_get_factor_list(
    db_session: AsyncSession, seeded_factor_registry  # noqa: F811
):
    """get_factor_list 返回列表，每项含必需字段。"""
    svc = FactorService(db_session)
    factors = await svc.get_factor_list()

    assert isinstance(factors, list)
    assert len(factors) >= 1
    required_keys = {"factor_name", "category", "direction", "status"}
    for f in factors:
        assert required_keys.issubset(f.keys()), f"缺少字段: {required_keys - f.keys()}"


@pytest.mark.asyncio
async def test_factor_service_get_factor_list_status_filter(
    db_session: AsyncSession, seeded_factor_registry  # noqa: F811
):
    """status 过滤返回正确子集。"""
    svc = FactorService(db_session)
    active = await svc.get_factor_list(status="active")
    deprecated = await svc.get_factor_list(status="deprecated")

    assert all(f["status"] == "active" for f in active), "active 过滤含非 active 项"
    assert all(f["status"] == "deprecated" for f in deprecated), (
        "deprecated 过滤含非 deprecated 项"
    )


# ─────────────────────────────────────────────────────────────
# T3: FactorService — get_factor_stats
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_factor_service_get_factor_stats_no_data(db_session: AsyncSession):
    """无数据时 get_factor_stats 返回 None 值，不抛出异常。"""
    svc = FactorService(db_session)
    stats = await svc.get_factor_stats(
        "nonexistent_xyz", date(2020, 1, 1), date(2020, 12, 31)
    )

    assert isinstance(stats, dict)
    assert stats["data_points"] == 0
    assert stats["ic_mean"] is None


@pytest_asyncio.fixture
async def seeded_ic_history(db_session: AsyncSession):
    """向 factor_ic_history 插入 20 天 IC 数据。"""
    factor_name = "_test_ic_factor"
    base_date = date(2024, 1, 1)
    for i in range(20):
        d = base_date + timedelta(days=i)
        await db_session.execute(
            text(
                """
                INSERT INTO factor_ic_history
                    (factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d)
                VALUES
                    (:factor_name, :trade_date, :ic_1d, :ic_5d, :ic_10d, :ic_20d)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "factor_name": factor_name,
                "trade_date": d,
                "ic_1d": 0.02 + i * 0.001,
                "ic_5d": 0.03 + i * 0.001,
                "ic_10d": 0.035 + i * 0.001,
                "ic_20d": 0.04 + i * 0.001,
            },
        )
    return {"factor_name": factor_name, "start": base_date, "end": base_date + timedelta(days=19)}


@pytest.mark.asyncio
async def test_factor_service_get_factor_stats_with_data(
    db_session: AsyncSession, seeded_ic_history
):
    """有数据时 get_factor_stats 返回合理数值。"""
    svc = FactorService(db_session)
    d = seeded_ic_history
    stats = await svc.get_factor_stats(d["factor_name"], d["start"], d["end"])

    assert stats["data_points"] == 20
    assert stats["ic_mean"] is not None
    assert 0.03 < stats["ic_mean"] < 0.06, f"ic_mean={stats['ic_mean']} 不在合理范围"
    assert stats["ic_ir"] is not None
    assert stats["ic_std"] is not None


# ─────────────────────────────────────────────────────────────
# T4: SignalService — generate_signals (dry_run=True)
# ─────────────────────────────────────────────────────────────


def _build_factor_df(codes: list[str], factor_names: list[str]) -> pd.DataFrame:
    """构造 factor_df 宽表（long format: code/factor_name/neutral_value）。"""
    rows = []
    for code in codes:
        for _, fname in enumerate(factor_names):
            rows.append({
                "code": code,
                "factor_name": fname,
                "neutral_value": float(hash(code + fname) % 1000) / 1000.0 - 0.5,
            })
    return pd.DataFrame(rows)


def _mock_psycopg2_conn(_strategy_id: str) -> MagicMock:
    """返回一个行为正确的 psycopg2 连接 mock。

    mock 要点:
    - cursor().fetchall() 返回空列表（无历史持仓）
    - cursor().fetchone() 返回 None
    """
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_cur.fetchone.return_value = None
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn


@pytest.mark.asyncio
async def test_signal_service_dry_run_returns_result():
    """SignalService.generate_signals dry_run=True 不写 DB，返回 SignalResult。"""
    from engines.signal_engine import SignalConfig

    from app.services.signal_service import SignalResult

    factor_names = ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]
    # 需要 >= 1000 只股票，否则 SignalService 截面覆盖率检查会抛 ValueError
    codes = [f"{i:06d}.SZ" for i in range(1, 1201)]
    factor_df = _build_factor_df(codes, factor_names)
    universe = set(codes)
    industry = pd.Series({c: f"ind_{int(c[:6]) % 10}" for c in codes})

    config = SignalConfig(
        factor_names=factor_names,
        top_n=15,
        rebalance_freq="monthly",
        industry_cap=0.25,
        cash_buffer=0.03,
    )

    strategy_id = "test_strategy_e2e"
    mock_conn = _mock_psycopg2_conn(strategy_id)

    svc = SignalService()

    # PaperBroker.load_state 和 needs_rebalance 需要 mock（无真实 DB 连接）
    with (
        patch("engines.paper_broker.PaperBroker.load_state"),
        patch("engines.paper_broker.PaperBroker.needs_rebalance", return_value=True),
        patch("engines.beta_hedge.calc_portfolio_beta", return_value=0.95),
    ):
        result = svc.generate_signals(
            conn=mock_conn,
            strategy_id=strategy_id,
            trade_date=date(2024, 1, 15),
            factor_df=factor_df,
            universe=universe,
            industry=industry,
            config=config,
            dry_run=True,
        )

    assert isinstance(result, SignalResult), "应返回 SignalResult"
    assert len(result.target_weights) == 15, (
        f"Top-15 策略应选 15 只，实际 {len(result.target_weights)}"
    )
    total_weight = sum(result.target_weights.values())
    assert abs(total_weight - 1.0) < 0.05, (
        f"权重合计={total_weight:.4f}，期望接近 1.0（cash_buffer 3%）"
    )
    assert len(result.signals_list) == 15
    assert result.is_rebalance is True


@pytest.mark.asyncio
async def test_signal_service_raises_on_missing_factor():
    """因子缺失时 generate_signals 抛出 ValueError，不静默降级。"""
    from engines.signal_engine import SignalConfig

    factor_names = ["turnover_mean_20", "volatility_20"]
    # factor_df 只有一个因子，缺少另一个
    partial_df = pd.DataFrame([
        {"code": "000001.SZ", "factor_name": "turnover_mean_20", "neutral_value": 0.1}
    ])
    config = SignalConfig(
        factor_names=factor_names,
        top_n=15,
        rebalance_freq="monthly",
        industry_cap=0.25,
        cash_buffer=0.03,
    )

    svc = SignalService()
    mock_conn = _mock_psycopg2_conn("test")

    with pytest.raises(ValueError, match="因子缺失"):
        svc.generate_signals(
            conn=mock_conn,
            strategy_id="test",
            trade_date=date(2024, 1, 15),
            factor_df=partial_df,
            universe={"000001.SZ"},
            industry=pd.Series({"000001.SZ": "金融"}),
            config=config,
            dry_run=True,
        )


@pytest.mark.asyncio
async def test_signal_service_raises_on_low_coverage():
    """因子截面覆盖率 < 1000 时抛出 ValueError。"""
    from engines.signal_engine import SignalConfig

    factor_names = ["turnover_mean_20"]
    # 只有 5 只股票，远低于 1000 的最低门槛
    small_codes = [f"{i:06d}.SZ" for i in range(1, 6)]
    small_df = pd.DataFrame([
        {"code": c, "factor_name": "turnover_mean_20", "neutral_value": 0.1}
        for c in small_codes
    ])
    config = SignalConfig(
        factor_names=factor_names,
        top_n=15,
        rebalance_freq="monthly",
        industry_cap=0.25,
        cash_buffer=0.03,
    )

    svc = SignalService()
    mock_conn = _mock_psycopg2_conn("test")

    with pytest.raises(ValueError, match="截面覆盖率严重不足"):
        svc.generate_signals(
            conn=mock_conn,
            strategy_id="test",
            trade_date=date(2024, 1, 15),
            factor_df=small_df,
            universe=set(small_codes),
            industry=pd.Series({c: "金融" for c in small_codes}),
            config=config,
            dry_run=True,
        )


# ─────────────────────────────────────────────────────────────
# T5: PaperTradingService — update_nav_sync (写库验证)
# ─────────────────────────────────────────────────────────────


def _psycopg2_sync_conn():
    """建立真实 psycopg2 同步连接（用于 update_nav_sync 写库测试）。"""
    import psycopg2  # type: ignore

    return psycopg2.connect(
        host="localhost",
        port=5432,
        dbname="quantmind_v2",
        user="xin",
        password="quantmind",
    )


@pytest.mark.asyncio
async def test_paper_trading_update_nav_sync_writes_db():
    """update_nav_sync 写入 performance_series + position_snapshot，ROLLBACK 后清理。

    此测试使用真实 psycopg2 连接并手动管理事务（ROLLBACK）。
    """
    pytest.importorskip("psycopg2")

    strategy_id = str(uuid.uuid4())
    trade_date = date(2024, 3, 15)
    holdings = {"000001.SZ": 1000, "600519.SH": 100}
    prices = {"000001.SZ": 12.50, "600519.SH": 1600.00}
    cash = 100_000.0
    initial_capital = 1_000_000.0

    conn = _psycopg2_sync_conn()
    conn.autocommit = False
    try:
        result = PaperTradingService.update_nav_sync(
            conn=conn,
            strategy_id=strategy_id,
            trade_date=trade_date,
            holdings=holdings,
            prices=prices,
            cash=cash,
            initial_capital=initial_capital,
        )

        # 验证返回值结构
        assert result is not None
        assert "nav" in result
        assert "daily_return" in result
        assert result["position_count"] == 2

        # 验证 NAV 计算正确
        expected_nav = 1000 * 12.50 + 100 * 1600.00 + 100_000.0
        assert abs(result["nav"] - expected_nav) < 0.01, (
            f"NAV={result['nav']:.2f}, 期望 {expected_nav:.2f}"
        )

        # 验证写入 performance_series 表
        cur = conn.cursor()
        cur.execute(
            "SELECT nav FROM performance_series WHERE strategy_id=%s AND trade_date=%s AND execution_mode='paper'",
            (strategy_id, trade_date),
        )
        row = cur.fetchone()
        assert row is not None, "performance_series 未写入"
        assert abs(float(row[0]) - expected_nav) < 0.01

        # 验证写入 position_snapshot 表
        cur.execute(
            "SELECT COUNT(*) FROM position_snapshot WHERE strategy_id=%s AND trade_date=%s AND execution_mode='paper'",
            (strategy_id, trade_date),
        )
        row_count = cur.fetchone()
        assert row_count is not None
        count = row_count[0]
        assert count == 2, f"position_snapshot 应有 2 条持仓，实际 {count}"

    finally:
        conn.rollback()
        conn.close()


# ─────────────────────────────────────────────────────────────
# T6: PaperTradingService — get_status (async, mock repo)
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_paper_trading_get_status_no_data(db_session: AsyncSession):
    """无数据时 get_status 返回默认零值，不抛出异常。"""
    svc = PaperTradingService(db_session)
    # strategy_id 列类型为 UUID，必须传合法 UUID 字符串
    nonexistent_uuid = str(uuid.uuid4())
    status = await svc.get_status(nonexistent_uuid)

    assert isinstance(status, dict)
    assert status["nav"] == 0
    assert status["running_days"] == 0
    assert status["graduation_ready"] is False


# ─────────────────────────────────────────────────────────────
# T7: 全链路集成 — factor查询 → 信号生成（dry_run）
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_chain_factor_to_signal(
    db_session: AsyncSession, seeded_factor_values
):
    """全链路: FactorService 查询 → 构建宽表 → SignalService 信号合成（dry_run）。

    验证两个 service 的数据格式兼容性。
    """
    from engines.signal_engine import SignalConfig

    from app.services.signal_service import SignalResult

    factor_svc = FactorService(db_session)
    trade_date = seeded_factor_values["trade_date"]
    factor_names = seeded_factor_values["factor_names"]

    # Step1: 查询全部 5 因子的截面数据
    frames = []
    for fname in factor_names:
        df = await factor_svc.get_factor_values(fname, trade_date, neutralized=True)
        frames.append(df)

    factor_df = pd.concat(frames, ignore_index=True)
    # DB 已有生产数据，结果 >= 插入的 3000 行（5因子×600股）
    assert len(factor_df) >= 3000, f"期望至少 3000 行，实际 {len(factor_df)}"
    # FactorService 返回列名 'value'，SignalComposer.compose() 期望 'neutral_value'
    # 全链路调用方须做此重命名；DB 返回 Decimal 类型，需转为 float 供 pandas 计算
    factor_df = factor_df.rename(columns={"value": "neutral_value"})
    factor_df["neutral_value"] = factor_df["neutral_value"].astype(float)

    # Step2: 构建 universe 和 industry
    universe = set(seeded_factor_values["codes"])
    industry = pd.Series({c: f"ind_{int(c[:6]) % 10}" for c in universe})

    # Step3: 信号生成（dry_run）
    config = SignalConfig(
        factor_names=factor_names,
        top_n=15,
        rebalance_freq="monthly",
        industry_cap=0.25,
        cash_buffer=0.03,
    )
    mock_conn = _mock_psycopg2_conn("test_full_chain")
    signal_svc = SignalService()

    with (
        patch("engines.paper_broker.PaperBroker.load_state"),
        patch("engines.paper_broker.PaperBroker.needs_rebalance", return_value=True),
        patch("engines.beta_hedge.calc_portfolio_beta", return_value=0.90),
    ):
        result = signal_svc.generate_signals(
            conn=mock_conn,
            strategy_id="test_full_chain",
            trade_date=trade_date,
            factor_df=factor_df,
            universe=universe,
            industry=industry,
            config=config,
            dry_run=True,
        )

    assert isinstance(result, SignalResult)
    assert len(result.target_weights) == 15
    # 所有选出的股票必须在 universe 内
    for code in result.target_weights:
        assert code in universe, f"{code} 不在 universe 内"
    # 权重合计接近 1（cash_buffer 3% 允许一定偏差）
    total = sum(result.target_weights.values())
    assert 0.90 <= total <= 1.05, f"总权重 {total:.4f} 超出合理范围"
