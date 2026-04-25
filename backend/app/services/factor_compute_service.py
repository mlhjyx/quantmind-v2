"""Factor compute service — 因子计算编排层 (Service 层).

Phase C C3 (2026-04-16) 从 `backend/engines/factor_engine/__init__.py` 搬家到此,
完成 铁律 31 Engine 纯计算分层的最终 milestone.

职责:
    * `save_daily_factors`    — 单日因子批量入库 (走 DataPipeline, 原已合规)
    * `compute_daily_factors` — 单日因子计算编排 (调 repository + engine + preprocess)
    * `compute_batch_factors` — 区间批量计算 + 逐日入库
      **Phase C C3 关键改动**: 原 `execute_values(cur, INSERT INTO factor_values...)`
      + `conn.commit()` 改走 `DataPipeline.ingest(df, FACTOR_VALUES)`, 关闭 F86 最后
      一条 factor_engine known_debt (铁律 17).

设计原则:
    - 纯计算部分 (calc_* / preprocess) 永远不读 DB, 走 engines.factor_engine.* submodules
    - 数据加载部分 (load_*) 走 app.services.factor_repository
    - 因子注册表 (PHASE0_* / ML_* / ALPHA158_*) 通过**函数内 lazy import** 避免循环
      (因为 engines.factor_engine.__init__.py re-export 本模块的 compute_*)

注意事项:
    - DataPipeline.ingest 自动 fillna(None) + 列对齐 + FK 过滤 + upsert, 单事务
    - 逐日调 ingest, 与原代码的逐日 INSERT+commit 语义等价
    - day_rows 内部仍用 `_safe()` 预过滤 NaN/inf, 与 DataPipeline fillna 双重保险

见: docs/audit/PHASE_C_F31_PREP.md §Milestones C3
"""

from __future__ import annotations

import time
import warnings
from datetime import date

import numpy as np
import pandas as pd
import structlog

from app.data_fetcher.contracts import FACTOR_VALUES
from app.data_fetcher.pipeline import DataPipeline
from app.services.factor_repository import (
    load_bulk_data,
    load_bulk_data_with_extras,
    load_daily_data,
    load_fundamental_pit_data,
)

# NOTE: `from engines.factor_engine.preprocess import preprocess_pipeline` 不能
# 放在模块级. 原因: engines.factor_engine.__init__ re-export 本模块的 compute_*,
# 如果用户先 `from app.services.factor_compute_service import X`, Python 会在
# 加载 preprocess 子模块前先执行 engines.factor_engine.__init__, 此时本模块还
# 没定义 compute_*, 引发 ImportError. 所以 preprocess_pipeline 也走 lazy import
# 和因子注册表一致.

logger = structlog.get_logger(__name__)


# ============================================================
# 因子写入 (原 save_daily_factors, 已合规走 DataPipeline)
# ============================================================


def save_daily_factors(
    trade_date: date,
    factor_df: pd.DataFrame,
    conn=None,
    *,
    with_lineage: bool = True,
) -> int:
    """按日期批量写入因子值(通过 DataPipeline, 单事务).

    CLAUDE.md 强制要求: 一次事务写入当日全部股票 × 全部因子.
    Pipeline 自动处理: inf/NaN→None + 验证 + upsert.
    factor_values 跳过单位转换 (skip_unit_conversion=True).

    [MVP 2.2 Sub2] `with_lineage=True` 时自动构 Lineage (code=当前 HEAD commit +
    module, params 含 factor_name distinct + compute_version map), DataPipeline.ingest
    自动补 outputs + write_lineage. 失败降级为纯 upsert, 主流程不受影响.

    Args:
        trade_date: 交易日期
        factor_df: DataFrame with columns [code, factor_name, raw_value, neutral_value, zscore]
        conn: psycopg2 连接
        with_lineage: 是否记录血缘 (默认 True, 测试场景可 False 跳过)

    Returns:
        写入行数
    """
    from app.services.price_utils import _get_sync_conn

    close_conn = conn is None
    if conn is None:
        conn = _get_sync_conn()

    try:
        # 确保 trade_date 列存在
        df = factor_df.copy()
        if "trade_date" not in df.columns:
            df["trade_date"] = trade_date

        pipeline = DataPipeline(conn)
        lineage = _build_factor_lineage(df, trade_date, conn) if with_lineage else None
        result = pipeline.ingest(df, FACTOR_VALUES, lineage=lineage)

        if result.rejected_rows > 0:
            logger.warning(
                "[%s] factor_values: %d/%d rejected: %s",
                trade_date,
                result.rejected_rows,
                result.total_rows,
                result.reject_reasons,
            )

        logger.info(
            "[%s] 写入因子 %d 行%s",
            trade_date,
            result.upserted_rows,
            f" lineage={result.lineage_id}" if result.lineage_id else "",
        )
        return result.upserted_rows
    except Exception:
        conn.rollback()
        raise
    finally:
        if close_conn:
            conn.close()


def _build_factor_lineage(df: pd.DataFrame, trade_date: date, conn):
    """构造本批 factor_values 写入的 Lineage (MVP 2.2 Sub2).

    策略:
      - code.git_commit: 查多数 factor 在 factor_compute_version 的 active compute_commit;
        找不到 → 为空字符串 "" (不 raise, 埋点失败降级)
      - params.factor_versions: {factor_name: version} map (复用 factor_compute_version 表)
      - inputs: 不展开 (单日全 universe 源引用量太大), 仅挂一条 placeholder,
        后续 MVP 2.3 Parity 扩展到逐因子源追溯
      - outputs: 由 DataPipeline._record_lineage 自动补 (df PK distinct)

    Returns:
        Lineage | None (失败返 None, 上层 with_lineage=True 但失败时不 raise)
    """
    try:
        from backend.qm_platform.data.lineage import CodeRef, Lineage, LineageRef

        factor_names = df["factor_name"].dropna().astype(str).unique().tolist()
        version_map: dict[str, int] = {}
        commit_counter: dict[str, int] = {}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT factor_name, version, compute_commit "
                "FROM factor_compute_version "
                "WHERE factor_name = ANY(%s) AND compute_end IS NULL",
                (factor_names,),
            )
            for fname, ver, commit in cur.fetchall():
                version_map[fname] = int(ver)
                key = (commit or "").strip()
                if key:
                    commit_counter[key] = commit_counter.get(key, 0) + 1

        # 多数票 commit (同 batch 多因子共用时代表 commit; 若不一致取最多票)
        majority_commit = ""
        if commit_counter:
            majority_commit = max(commit_counter.items(), key=lambda kv: kv[1])[0]

        code = CodeRef(
            git_commit=majority_commit,
            module="backend.app.services.factor_compute_service",
            function="save_daily_factors",
        )
        # source placeholder: trade_date 上游 klines_daily/daily_basic (不逐因子展开)
        inputs = [
            LineageRef(
                table="klines_daily",
                pk_values={"trade_date": trade_date.isoformat()},
            )
        ]
        return Lineage(
            inputs=inputs,
            code=code,
            params={
                "trade_date": trade_date.isoformat(),
                "factor_count": len(factor_names),
                "factor_versions": version_map,
            },
        )
    except Exception as e:  # silent_ok: lineage 构造失败不阻塞主入库
        logger.warning("lineage 构造失败, 本批跳过埋点: %s", e)
        return None


# ============================================================
# 主流程: 单日因子计算
# ============================================================


def compute_daily_factors(
    trade_date: date,
    factor_set: str = "core",
    conn=None,
    include_reserve: bool = True,
) -> pd.DataFrame:
    """计算单日全部因子.

    Args:
        trade_date: 交易日期
        factor_set: 'core'(5因子) / 'full'(不含deprecated) / 'all'(含deprecated, 向后兼容)
        conn: 可选连接
        include_reserve: 是否包含 Reserve 池因子 (默认 True, 日常管道计算)

    Returns:
        DataFrame [code, factor_name, raw_value, neutral_value, zscore]
    """
    # Lazy import 避免循环 (engines.factor_engine re-export 本模块)
    from engines.factor_engine import (
        ALPHA158_FACTORS,
        PHASE0_ALL_FACTORS,
        PHASE0_CORE_FACTORS,
        PHASE0_FULL_FACTORS,
        RESERVE_FACTORS,
    )
    from engines.factor_engine.preprocess import preprocess_pipeline

    if factor_set == "core":
        factors = dict(PHASE0_CORE_FACTORS)
    elif factor_set == "all":
        logger.warning("factor_set='all' 包含 deprecated 因子, 仅用于历史分析/对比")
        factors = dict(PHASE0_ALL_FACTORS)
    else:
        factors = dict(PHASE0_FULL_FACTORS)

    # Reserve 池因子随日常管道一起计算 (不入 v1.1 等权组合, 仅写入 factor_values 供监控)
    if include_reserve:
        factors.update(RESERVE_FACTORS)
        factors.update(ALPHA158_FACTORS)

    # 1. 加载数据
    logger.info(f"[{trade_date}] 加载行情数据...")
    df = load_daily_data(trade_date, lookback_days=120, conn=conn)

    if df.empty:
        logger.warning(f"[{trade_date}] 无数据, 跳过")
        return pd.DataFrame()

    # 取当日截面
    today_mask = df["trade_date"] == trade_date
    if today_mask.sum() == 0:
        logger.warning(f"[{trade_date}] 当日无数据, 跳过")
        return pd.DataFrame()

    today_codes = df.loc[today_mask, "code"].values
    today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
    today_industry.index = today_codes
    today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
    today_ln_mcap.index = today_codes

    # 2. 计算每个因子
    all_results = []

    for factor_name, calc_fn in factors.items():
        try:
            logger.debug(f"[{trade_date}] 计算因子: {factor_name}")

            # 计算原始值
            raw_series = calc_fn(df)

            # 取当日截面
            raw_today = raw_series[today_mask].copy()
            raw_today.index = today_codes

            # 预处理
            raw_val, neutral_val = preprocess_pipeline(raw_today, today_ln_mcap, today_industry)

            # 组装结果
            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                all_results.append(
                    {
                        "code": code,
                        "factor_name": factor_name,
                        "raw_value": rv,
                        "neutral_value": nv,
                        "zscore": nv,  # neutral_value 已经是 zscore
                    }
                )
        except Exception as e:
            logger.error(f"[{trade_date}] 因子 {factor_name} 计算失败: {e}")
            continue

    result_df = pd.DataFrame(all_results)
    logger.info(
        f"[{trade_date}] 计算完成: {len(factors)}因子 × {len(today_codes)}股 = {len(result_df)}行"
    )
    return result_df


# ============================================================
# 批量计算: 一次加载全量数据, 逐日计算+写入 (DataPipeline 路径)
# Phase C C3 (2026-04-16): 从 factor_engine/__init__.py 搬家, 同时把原
# execute_values(INSERT INTO factor_values) + conn.commit() 改走 DataPipeline.ingest.
# 关闭 F86 最后一条 factor_engine known_debt (铁律 17).
# ============================================================


def _safe(v):
    """将 NaN/inf 转为 None (与 DataPipeline fillna 双重保险)."""
    if pd.isna(v):
        return None
    fv = float(v)
    return None if not np.isfinite(fv) else fv


def compute_batch_factors(
    start_date: date,
    end_date: date,
    factor_set: str = "core",
    conn=None,
    write: bool = True,
    factor_names: list[str] | None = None,
) -> dict:
    """批量计算因子并逐日写入 (走 DataPipeline, 铁律 17 合规).

    [Phase C C3 2026-04-16] 原函数 INSERT INTO 违规已关闭, 现走 DataPipeline.ingest
    (见 commit 历史). 依然保留 DeprecationWarning — 推荐主路径用
    `compute_daily_factors()` + `save_daily_factors()` 组合, 本函数仅供历史回算使用.

    高效模式: 一次加载全量数据 → 计算滚动因子 → 逐日预处理+写入 (per-day Pipeline.ingest).

    Args:
        start_date: 开始日期
        end_date: 结束日期
        factor_set: 'core'/'full'/'all'/'ml'/'lgbm'/'fundamental'(8 个 PIT 因子)/'lgbm_v2'(5 基线+8 基本面=13 个)
        conn: 可选连接
        write: 是否写入数据库
        factor_names: 可选, 只计算指定因子列表. None=计算全部.

    Returns:
        dict with stats (total_rows, elapsed, etc.)
    """
    warnings.warn(
        "compute_batch_factors 是 S2 F52 DEPRECATED 路径. Phase C C3 (2026-04-16) "
        "已改走 DataPipeline.ingest 合规铁律 17, 但主路径仍建议用 "
        "compute_daily_factors() + save_daily_factors() 组合. "
        "见 docs/audit/S2_consistency.md F52 + PHASE_C_F31_PREP.md §C3.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Lazy import 避免循环 (engines.factor_engine re-export 本模块)
    from engines.factor_engine import (
        FUNDAMENTAL_ALL_FEATURES,
        LGBM_V2_BASELINE_FACTORS,
        LIGHTGBM_FEATURE_SET,
        ML_FEATURES,
        ML_FEATURES_INDEX,
        ML_FEATURES_MONEYFLOW,
        PHASE0_ALL_FACTORS,
        PHASE0_CORE_FACTORS,
        PHASE0_FULL_FACTORS,
        RESERVE_FACTORS,
    )
    from engines.factor_engine.preprocess import preprocess_pipeline

    from app.services.price_utils import _get_sync_conn

    use_extras = False  # 是否需要加载 moneyflow+index 数据
    use_fundamental = False  # 是否需要加载 PIT 财务数据
    include_reserve = False  # Reserve 池因子是否加入
    if factor_set == "core":
        factors = dict(PHASE0_CORE_FACTORS)
        include_reserve = True
    elif factor_set == "all":
        logger.warning("factor_set='all' 包含 deprecated 因子, 仅用于历史分析/对比")
        factors = dict(PHASE0_ALL_FACTORS)
        include_reserve = True
    elif factor_set == "ml":
        factors = dict(ML_FEATURES)
        use_extras = True
    elif factor_set == "lgbm":
        factors = dict(LIGHTGBM_FEATURE_SET)
        use_extras = True
    elif factor_set == "fundamental":
        # 仅计算 8 个基本面+时间因子 (不需要 kline 滚动因子)
        factors = {}
        use_fundamental = True
    elif factor_set == "lgbm_v2":
        # 5 基线 + 6 delta + 2 时间 = 13 个
        factors = {k: v for k, v in PHASE0_CORE_FACTORS.items() if k in LGBM_V2_BASELINE_FACTORS}
        # reversal_20 在 PHASE0_FULL_FACTORS 中
        if "reversal_20" not in factors:
            factors["reversal_20"] = PHASE0_FULL_FACTORS.get("reversal_20")
        use_fundamental = True
    else:
        factors = dict(PHASE0_FULL_FACTORS)
        include_reserve = True

    # Reserve 池因子随日常管道一起计算 (不入 v1.1 等权组合)
    if include_reserve:
        factors.update(RESERVE_FACTORS)
    if factor_names:
        factors = {k: v for k, v in factors.items() if k in factor_names}
        if not factors:
            logger.warning(f"指定的因子名 {factor_names} 在 {factor_set} 集中均未找到")
            return {
                "total_rows": 0,
                "elapsed": 0,
                "dates": 0,
                "load_time": 0,
                "calc_time": 0,
                "total_time": 0,
            }
        # 仅当实际需要 moneyflow/index 因子时才加载额外数据
        _mf_and_idx = set(ML_FEATURES_MONEYFLOW) | set(ML_FEATURES_INDEX)
        use_extras = use_extras and bool(set(factors) & _mf_and_idx)

    # 字符串 → date 转换 (命令行调用时传入 str)
    if isinstance(start_date, str):
        from datetime import datetime as _dt

        start_date = _dt.strptime(start_date, "%Y-%m-%d").date()
    if isinstance(end_date, str):
        from datetime import datetime as _dt

        end_date = _dt.strptime(end_date, "%Y-%m-%d").date()

    if conn is None:
        conn = _get_sync_conn()

    t0 = time.time()

    # 1. 一次性加载全量数据 (kline 因子需要)
    if factors:
        if use_extras:
            df = load_bulk_data_with_extras(start_date, end_date, conn=conn)
        else:
            df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return {
                "total_rows": 0,
                "elapsed": 0,
                "dates": 0,
                "load_time": 0,
                "calc_time": 0,
                "total_time": 0,
            }
    else:
        # fundamental-only 模式: 仍需 kline 数据获取交易日列表和截面信息
        df = load_bulk_data(start_date, end_date, conn=conn)
        if df.empty:
            return {
                "total_rows": 0,
                "elapsed": 0,
                "dates": 0,
                "load_time": 0,
                "calc_time": 0,
                "total_time": 0,
            }

    t_load = time.time() - t0

    # 2. 一次性计算所有 kline 因子的滚动值
    logger.info(f"计算 {len(factors)} 个 kline 因子的滚动值...")
    factor_raw = {}
    for fname, calc_fn in factors.items():
        try:
            factor_raw[fname] = calc_fn(df)
        except Exception as e:
            logger.error(f"因子 {fname} 计算失败: {e}")

    t_calc = time.time() - t0 - t_load

    # 3. 获取计算范围内的交易日
    all_dates = sorted(
        df.loc[
            (df["trade_date"] >= start_date) & (df["trade_date"] <= end_date), "trade_date"
        ].unique()
    )

    n_fund = len(FUNDAMENTAL_ALL_FEATURES) if use_fundamental else 0
    logger.info(
        f"逐日预处理+写入 (DataPipeline): {len(all_dates)} 个交易日"
        f"{f' (含 {n_fund} 个基本面因子)' if use_fundamental else ''}"
    )

    total_rows = 0
    for i, td in enumerate(all_dates):
        td_date = td.date() if hasattr(td, "date") else td

        # 取当日截面
        today_mask = df["trade_date"] == td
        if today_mask.sum() == 0:
            continue

        today_codes = df.loc[today_mask, "code"].values
        today_industry = df.loc[today_mask, "industry_sw1"].fillna("其他")
        today_industry.index = today_codes
        today_ln_mcap = df.loc[today_mask, "total_mv"].apply(lambda x: np.log(x + 1e-12))
        today_ln_mcap.index = today_codes

        # 逐因子预处理 (kline 因子)
        day_rows = []
        for fname in factor_raw:
            raw_today = factor_raw[fname][today_mask].copy()
            raw_today.index = today_codes

            raw_val, neutral_val = preprocess_pipeline(raw_today, today_ln_mcap, today_industry)

            for code in today_codes:
                rv = raw_val.get(code, np.nan)
                nv = neutral_val.get(code, np.nan)
                day_rows.append(
                    (
                        code,
                        td_date,
                        fname,
                        _safe(rv),
                        _safe(nv),
                        _safe(nv),
                    )
                )

        # 基本面 delta 因子 (PIT 加载, 逐日计算)
        if use_fundamental:
            try:
                fund_data = load_fundamental_pit_data(td_date, conn)
                for fname, raw_series in fund_data.items():
                    if raw_series.empty:
                        continue
                    # 对齐到当日截面的 code 集合
                    raw_aligned = raw_series.reindex(today_codes)

                    raw_val, neutral_val = preprocess_pipeline(
                        raw_aligned, today_ln_mcap, today_industry
                    )

                    for code in today_codes:
                        rv = raw_val.get(code, np.nan)
                        nv = neutral_val.get(code, np.nan)
                        day_rows.append(
                            (
                                code,
                                td_date,
                                fname,
                                _safe(rv),
                                _safe(nv),
                                _safe(nv),
                            )
                        )
            except Exception as e:
                logger.error(f"[{td_date}] 基本面因子计算失败: {e}")

        # 写入当日所有因子 (Phase C C3 铁律 17: 走 DataPipeline.ingest)
        if write and day_rows:
            day_df = pd.DataFrame(
                day_rows,
                columns=[
                    "code",
                    "trade_date",
                    "factor_name",
                    "raw_value",
                    "neutral_value",
                    "zscore",
                ],
            )
            pipeline = DataPipeline(conn)
            try:
                result = pipeline.ingest(day_df, FACTOR_VALUES)
            except Exception:
                conn.rollback()
                raise

            if result.rejected_rows > 0:
                logger.warning(
                    "[%s] factor_values: %d/%d rejected: %s",
                    td_date,
                    result.rejected_rows,
                    result.total_rows,
                    result.reject_reasons,
                )
            total_rows += result.upserted_rows
        else:
            total_rows += len(day_rows)

        if (i + 1) % 50 == 0 or i == 0 or i == len(all_dates) - 1:
            elapsed = time.time() - t0
            logger.info(
                f"  [{i + 1}/{len(all_dates)}] {td_date} | "
                f"{len(day_rows)}行 | 累计{total_rows}行 | "
                f"{elapsed:.0f}s"
            )

    elapsed = time.time() - t0
    stats = {
        "total_rows": total_rows,
        "dates": len(all_dates),
        "load_time": round(t_load, 1),
        "calc_time": round(t_calc, 1),
        "total_time": round(elapsed, 1),
    }
    logger.info(
        f"批量因子计算完成: {stats['dates']}天, {total_rows}行, "
        f"加载{t_load:.0f}s + 计算{t_calc:.0f}s + 总计{elapsed:.0f}s"
    )
    return stats
