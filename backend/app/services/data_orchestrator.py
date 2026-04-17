"""DataOrchestrator — 统一数据编排层。

将 fetch → compute → neutralize → evaluate 串成统一管道。
核心能力:
  1. SharedDataPool: 行业/市值/基准加载一次, 多因子多步骤共享
  2. CheckpointTracker: 增量检测, 只处理新数据
  3. QualityValidator: 每步输出后自动检查质量
  4. DataOrchestrator: 编排以上三者, 提供统一入口

设计原则:
  - 复用 factor_repository.load_shared_context (不自己写SQL)
  - 复用 fast_neutralize._mad/_wls/_zscore 纯函数 (不重写中性化逻辑)
  - 保持 fast_neutralize_batch 外部API不变 (6个调用方零改动)
  - 无新依赖, 无DDL变更
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ============================================================
# 数据结构
# ============================================================


@dataclass
class StageResult:
    """单阶段执行结果。"""

    stage: str  # "neutralize" / "evaluate" / ...
    status: str  # "success" / "partial" / "failed" / "skipped"
    rows_in: int = 0
    rows_out: int = 0
    rows_rejected: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None
    quality: dict | None = None

    @property
    def success(self) -> bool:
        return self.status in ("success", "partial")


@dataclass
class PipelineResult:
    """全管道执行结果。"""

    run_id: str
    stages: dict[str, StageResult] = field(default_factory=dict)
    total_elapsed: float = 0.0
    incremental_dates: list = field(default_factory=list)

    @property
    def overall_success(self) -> bool:
        return all(s.success for s in self.stages.values())

    def summary(self) -> str:
        lines = [f"Pipeline {self.run_id}: {'SUCCESS' if self.overall_success else 'FAILED'} ({self.total_elapsed:.1f}s)"]
        for name, sr in self.stages.items():
            lines.append(f"  {name}: {sr.status} ({sr.rows_out} rows, {sr.elapsed_seconds:.1f}s)")
            if sr.quality:
                for k, v in sr.quality.items():
                    lines.append(f"    {k}: {v}")
        return "\n".join(lines)


# ============================================================
# SharedDataPool — 共享数据池
# ============================================================


class SharedDataPool:
    """会话级共享数据池 — 加载一次, 多处复用。

    内部调用 factor_repository.load_shared_context, 不自己写SQL。
    支持惰性加载: 首次访问时加载, 后续复用缓存。
    """

    def __init__(self, start_date: str, end_date: str, conn=None):
        self._start = start_date
        self._end = end_date
        self._conn = conn
        self._ctx: dict | None = None

    def _ensure_loaded(self) -> dict:
        if self._ctx is None:
            from app.services.factor_repository import load_shared_context

            t0 = time.time()
            self._ctx = load_shared_context(
                self._start, self._end, conn=self._conn,
                include_benchmark=True,
            )
            logger.info(
                "SharedDataPool 加载: %d行业, %d市值行 (%.1fs)",
                self._ctx["n_stocks"], self._ctx["n_mv_rows"],
                time.time() - t0,
            )
        return self._ctx

    @property
    def industry_map(self) -> dict[str, str]:
        """行业映射 {code: sw1_industry}。"""
        return self._ensure_loaded()["ind_dict"]

    @property
    def market_cap(self) -> pd.Series:
        """市值 MultiIndex(code, trade_date) → total_mv。"""
        return self._ensure_loaded()["mv_lookup"]

    @property
    def benchmark_df(self) -> pd.DataFrame | None:
        """基准数据 DataFrame(trade_date, close)。"""
        return self._ensure_loaded()["benchmark_df"]

    def as_neutralize_context(self) -> dict:
        """转为 fast_neutralize_batch 的 shared_context 格式。"""
        ctx = self._ensure_loaded()
        return {
            "ind_dict": ctx["ind_dict"],
            "mv_lookup": ctx["mv_lookup"],
            "start_date": ctx["start_date"],
            "end_date": ctx["end_date"],
        }


# ============================================================
# CheckpointTracker — 增量检测
# ============================================================


class CheckpointTracker:
    """增量检测 — 找出需要处理的新日期, 无DDL变更。

    原理: 查 factor_values 中 raw_value IS NOT NULL 但 neutral_value IS NULL 的日期。
    """

    def __init__(self, conn):
        self._conn = conn

    def get_pending_neutralize_dates(
        self, factor_name: str
    ) -> list[date]:
        """找出需要中性化的日期 (有raw_value但没neutral_value)。"""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT trade_date
            FROM factor_values
            WHERE factor_name = %s
              AND raw_value IS NOT NULL
              AND neutral_value IS NULL
            ORDER BY trade_date
            """,
            (factor_name,),
        )
        return [r[0] for r in cur.fetchall()]

    def get_all_dates_with_raw(self, factor_name: str) -> list[date]:
        """获取有 raw_value 的全部日期。"""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT trade_date
            FROM factor_values
            WHERE factor_name = %s AND raw_value IS NOT NULL
            ORDER BY trade_date
            """,
            (factor_name,),
        )
        return [r[0] for r in cur.fetchall()]

    def count_neutral_coverage(self, factor_name: str) -> dict:
        """统计中性化覆盖率。"""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(raw_value) as has_raw,
                COUNT(neutral_value) as has_neutral
            FROM factor_values
            WHERE factor_name = %s
            """,
            (factor_name,),
        )
        row = cur.fetchone()
        total, has_raw, has_neutral = row
        return {
            "total": total,
            "has_raw": has_raw,
            "has_neutral": has_neutral,
            "coverage": has_neutral / has_raw if has_raw > 0 else 0.0,
        }

    # ---- P0-4 新增 ----
    def get_pending_compute_dates(self, factor_name: str) -> list[date]:
        """需要计算 raw_value 的日期 (L1 有数据 - L2 已产出).

        回答: "哪些交易日的行情数据已入库, 但该因子还没算过?"
        """
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT k.trade_date
            FROM klines_daily k
            LEFT JOIN (
                SELECT DISTINCT trade_date FROM factor_values
                WHERE factor_name = %s AND raw_value IS NOT NULL
            ) fv ON fv.trade_date = k.trade_date
            WHERE fv.trade_date IS NULL
            ORDER BY k.trade_date
            """,
            (factor_name,),
        )
        return [r[0] for r in cur.fetchall()]

    def last_success(self, asset_name: str):
        """pipeline_runs 最近一次 status=success 记录 (若表不存在返回 None)。"""
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                SELECT completed_at FROM pipeline_runs
                WHERE asset_name = %s AND status = 'success'
                ORDER BY completed_at DESC LIMIT 1
                """,
                (asset_name,),
            )
            row = cur.fetchone()
            return row[0] if row else None
        except Exception:
            # pipeline_runs 表未建, 降级返回 None
            self._conn.rollback()
            return None

    def mark_success(self, asset_name: str, trade_date: date, row_count: int):
        """记录成功完成 (pipeline_runs 可选, 失败不阻塞)。"""
        cur = self._conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO pipeline_runs (asset_name, trade_date, row_count, status, completed_at)
                VALUES (%s, %s, %s, 'success', NOW())
                """,
                (asset_name, trade_date, row_count),
            )
            self._conn.commit()
        except Exception:
            # silent_ok: pipeline_runs 可能未建, 不阻塞主流程
            self._conn.rollback()


# ============================================================
# QualityValidator — 输出验证
# ============================================================


class QualityValidator:
    """每阶段输出后自动检查质量。"""

    # 阈值
    MAX_NAN_RATE = 0.05  # neutral_value NULL 比例 < 5%
    MIN_COVERAGE = 0.90  # 有值股票 / universe > 90%
    MAX_MEAN_DRIFT = 0.1  # |mean(neutral_value)| < 0.1 (中性化后应≈0)
    MIN_STD = 0.5  # std > 0.5
    MAX_STD = 2.0  # std < 2.0
    MAX_EXTREME_RATE = 0.02  # |value| > 3 的比例 < 2%

    def __init__(self, conn):
        self._conn = conn

    def validate_neutralized(
        self, factor_name: str, sample_dates: list[date] | None = None
    ) -> dict:
        """中性化后质量检查。

        检查项:
          nan_rate: neutral_value IS NULL / total
          mean_drift: |mean(neutral_value)| (应≈0)
          std_range: std(neutral_value) (应≈1)
          extreme_rate: |neutral_value| > 3 的比例
          overall: PASS / WARN / FAIL
        """
        cur = self._conn.cursor()

        # 取最近30天采样 (或指定日期)
        if sample_dates:
            date_clause = "AND trade_date = ANY(%s)"
            params = (factor_name, sample_dates)
        else:
            date_clause = (
                "AND trade_date >= (SELECT MAX(trade_date) - INTERVAL '30 days' "
                "FROM factor_values WHERE factor_name = %s AND raw_value IS NOT NULL)"
            )
            params = (factor_name, factor_name)

        cur.execute(
            f"""
            SELECT
                COUNT(*) as total,
                COUNT(neutral_value) as has_neutral,
                AVG(neutral_value) as mean_val,
                STDDEV(neutral_value) as std_val,
                COUNT(CASE WHEN ABS(neutral_value) > 3 THEN 1 END) as extreme_count
            FROM factor_values
            WHERE factor_name = %s {date_clause}
              AND raw_value IS NOT NULL
            """,
            params,
        )
        row = cur.fetchone()
        if not row or row[0] == 0:
            return {"overall": "NO_DATA", "total": 0}

        total, has_neutral, mean_val, std_val, extreme_count = row
        nan_rate = 1.0 - (has_neutral / total) if total > 0 else 1.0
        mean_val = float(mean_val) if mean_val is not None else 999.0
        std_val = float(std_val) if std_val is not None else 0.0
        extreme_rate = extreme_count / has_neutral if has_neutral > 0 else 0.0

        issues = []
        if nan_rate > self.MAX_NAN_RATE:
            issues.append(f"nan_rate={nan_rate:.3f}>{self.MAX_NAN_RATE}")
        if abs(mean_val) > self.MAX_MEAN_DRIFT:
            issues.append(f"|mean|={abs(mean_val):.3f}>{self.MAX_MEAN_DRIFT}")
        if std_val < self.MIN_STD or std_val > self.MAX_STD:
            issues.append(f"std={std_val:.3f} outside [{self.MIN_STD},{self.MAX_STD}]")
        if extreme_rate > self.MAX_EXTREME_RATE:
            issues.append(f"extreme_rate={extreme_rate:.3f}>{self.MAX_EXTREME_RATE}")

        if not issues:
            overall = "PASS"
        elif len(issues) <= 1:
            overall = "WARN"
        else:
            overall = "FAIL"

        return {
            "overall": overall,
            "nan_rate": round(nan_rate, 4),
            "mean_drift": round(abs(mean_val), 4),
            "std": round(std_val, 4),
            "extreme_rate": round(extreme_rate, 4),
            "total": total,
            "has_neutral": has_neutral,
            "issues": issues,
        }

    # ---- P0-3 新增: L2 raw-level 验证 ----

    def validate_factor_raw(
        self, factor_name: str, sample_dates: list[date] | None = None
    ) -> dict:
        """L2: raw_value 输出校验 (NaN率<5%, coverage>90%, 无Inf)."""
        cur = self._conn.cursor()

        if sample_dates:
            date_clause = "AND trade_date = ANY(%s)"
            params: tuple = (factor_name, sample_dates)
        else:
            date_clause = (
                "AND trade_date >= (SELECT MAX(trade_date) - INTERVAL '30 days' "
                "FROM factor_values WHERE factor_name = %s)"
            )
            params = (factor_name, factor_name)

        cur.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COUNT(raw_value) AS has_raw,
                COUNT(CASE WHEN raw_value IS NOT NULL AND (raw_value = 'Infinity' OR raw_value = '-Infinity')
                           THEN 1 END) AS inf_count
            FROM factor_values
            WHERE factor_name = %s {date_clause}
            """,
            params,
        )
        row = cur.fetchone()
        if not row or row[0] == 0:
            return {"overall": "NO_DATA", "total": 0}

        total, has_raw, inf_count = row
        nan_rate = 1.0 - (has_raw / total) if total > 0 else 1.0
        coverage = has_raw / total if total > 0 else 0.0
        issues = []
        if nan_rate > self.MAX_NAN_RATE:
            issues.append(f"nan_rate={nan_rate:.3f}>{self.MAX_NAN_RATE}")
        if coverage < self.MIN_COVERAGE:
            issues.append(f"coverage={coverage:.3f}<{self.MIN_COVERAGE}")
        if inf_count > 0:
            issues.append(f"inf_count={inf_count}")

        if not issues:
            overall = "PASS"
        elif len(issues) <= 1 and inf_count == 0:
            overall = "WARN"
        else:
            overall = "FAIL"

        return {
            "overall": overall,
            "total": total,
            "has_raw": has_raw,
            "nan_rate": round(nan_rate, 4),
            "coverage": round(coverage, 4),
            "inf_count": inf_count,
            "issues": issues,
        }

    # ---- P0-3 新增: L3 跨源对账 ----

    def reconcile_row_counts(self, trade_date: date, threshold: float = 0.08) -> dict:
        """L3: klines_daily vs daily_basic vs moneyflow_daily 行数差异检查."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT 'klines_daily'    AS tbl, COUNT(*) FROM klines_daily    WHERE trade_date = %s
            UNION ALL
            SELECT 'daily_basic',           COUNT(*) FROM daily_basic      WHERE trade_date = %s
            UNION ALL
            SELECT 'moneyflow_daily',       COUNT(*) FROM moneyflow_daily  WHERE trade_date = %s
            """,
            (trade_date, trade_date, trade_date),
        )
        counts = {r[0]: r[1] for r in cur.fetchall()}
        if not counts or max(counts.values()) == 0:
            return {"overall": "NO_DATA", "counts": counts}

        mx, mn = max(counts.values()), min(counts.values())
        diff_pct = (mx - mn) / mx if mx > 0 else 0.0

        overall = "PASS" if diff_pct < threshold else ("WARN" if diff_pct < threshold * 2 else "FAIL")
        return {
            "overall": overall,
            "trade_date": str(trade_date),
            "counts": counts,
            "diff_pct": round(diff_pct, 4),
            "threshold": threshold,
        }

    def reconcile_date_alignment(
        self, tables: list[str] | None = None
    ) -> dict:
        """L3: 交易表 MAX(trade_date) 对齐检查."""
        tables = tables or ["klines_daily", "daily_basic", "moneyflow_daily"]
        cur = self._conn.cursor()
        max_dates: dict[str, date | None] = {}
        for tbl in tables:
            try:
                cur.execute(f"SELECT MAX(trade_date) FROM {tbl}")
                row = cur.fetchone()
                max_dates[tbl] = row[0] if row else None
            except Exception:
                self._conn.rollback()
                max_dates[tbl] = None

        non_null = [d for d in max_dates.values() if d is not None]
        if not non_null:
            return {"overall": "NO_DATA", "max_dates": max_dates}

        lag_days = (max(non_null) - min(non_null)).days
        overall = "PASS" if lag_days <= 1 else ("WARN" if lag_days <= 3 else "FAIL")
        return {
            "overall": overall,
            "max_dates": {k: str(v) if v else None for k, v in max_dates.items()},
            "lag_days": lag_days,
        }

    def reconcile_factor_coverage(self, factor_name: str, threshold: float = 0.95) -> dict:
        """L3: neutral_value 覆盖率 > raw_value 的 95%."""
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE raw_value IS NOT NULL)     AS raw_count,
                COUNT(*) FILTER (WHERE neutral_value IS NOT NULL) AS neutral_count
            FROM factor_values WHERE factor_name = %s
            """,
            (factor_name,),
        )
        raw_count, neutral_count = cur.fetchone()
        if raw_count == 0:
            return {"overall": "NO_DATA", "ratio": 0.0}
        ratio = neutral_count / raw_count
        overall = "PASS" if ratio >= threshold else ("WARN" if ratio >= threshold * 0.9 else "FAIL")
        return {
            "overall": overall,
            "factor_name": factor_name,
            "raw_count": raw_count,
            "neutral_count": neutral_count,
            "ratio": round(ratio, 4),
            "threshold": threshold,
        }

    # ---- P0-3 聚合 ----

    def daily_report(
        self,
        trade_date: date | None = None,
        factor_names: list[str] | None = None,
    ) -> dict:
        """汇总 L1 + L2 + L3 检查, 输出 §4.4 JSON 格式."""
        if trade_date is None:
            cur = self._conn.cursor()
            cur.execute("SELECT MAX(trade_date) FROM klines_daily")
            row = cur.fetchone()
            trade_date = row[0] if row and row[0] else date.today()

        factor_names = factor_names or []

        report: dict = {
            "trade_date": str(trade_date),
            "overall": "PASS",
            "l1_ingest": {},
            "l2_factor_raw": {},
            "l2_factor_neutral": {},
            "l3_reconcile": {
                "row_counts": self.reconcile_row_counts(trade_date),
                "date_alignment": self.reconcile_date_alignment(),
                "factor_coverage": {},
            },
            "warnings": [],
            "failures": [],
        }

        for fn in factor_names:
            raw_q = self.validate_factor_raw(fn)
            neu_q = self.validate_neutralized(fn)
            cov = self.reconcile_factor_coverage(fn)
            report["l2_factor_raw"][fn] = raw_q
            report["l2_factor_neutral"][fn] = neu_q
            report["l3_reconcile"]["factor_coverage"][fn] = cov
            for label, result in [(f"{fn}.raw", raw_q), (f"{fn}.neutral", neu_q), (f"{fn}.cov", cov)]:
                if result.get("overall") == "WARN":
                    report["warnings"].append(label)
                elif result.get("overall") == "FAIL":
                    report["failures"].append(label)

        for key in ("row_counts", "date_alignment"):
            r = report["l3_reconcile"][key]
            if r.get("overall") == "WARN":
                report["warnings"].append(f"l3.{key}")
            elif r.get("overall") == "FAIL":
                report["failures"].append(f"l3.{key}")

        if report["failures"]:
            report["overall"] = "FAIL"
        elif report["warnings"]:
            report["overall"] = "WARN"

        return report


# ============================================================
# Universe — 标准 A 股过滤 (§3.7 决策 D3)
# ============================================================


class Universe:
    """标准A股universe过滤规则 (铁律7: 数据地基一致)."""

    EXCLUDE_BOARDS = ("bse",)
    EXCLUDE_ST = True
    EXCLUDE_SUSPENDED = True
    EXCLUDE_NEW_LISTED_DAYS = 60
    EXCLUDE_LIMIT_UP_DOWN = False  # 回测时由 strategy 指定

    @classmethod
    def get_valid_codes(cls, trade_date: date, conn) -> set[str]:
        """返回当日 universe 有效的 code 集合."""
        cur = conn.cursor()
        params_list: list = [trade_date, list(cls.EXCLUDE_BOARDS), trade_date]
        sql = """
            SELECT s.code FROM symbols s
            LEFT JOIN stock_status_daily ssd
              ON ssd.code = s.code AND ssd.trade_date = %s
            WHERE s.market = 'astock'
              AND (s.board IS NULL OR s.board != ALL(%s))
        """
        if cls.EXCLUDE_ST:
            sql += " AND (ssd.is_st IS NULL OR ssd.is_st = false)"
        if cls.EXCLUDE_SUSPENDED:
            sql += " AND (ssd.is_suspended IS NULL OR ssd.is_suspended = false)"
        if cls.EXCLUDE_NEW_LISTED_DAYS > 0:
            sql += f" AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL '{cls.EXCLUDE_NEW_LISTED_DAYS} days')"
        else:
            # list_date 为 null 时允许, 否则用占位符平衡参数个数
            sql += " AND (s.list_date IS NULL OR s.list_date <= %s::date)"

        cur.execute(sql, tuple(params_list))
        return {r[0] for r in cur.fetchall()}


# ============================================================
# DataOrchestrator — 统一编排
# ============================================================


class DataOrchestrator:
    """统一数据编排层。

    用法:
        orch = DataOrchestrator('2021-01-01', '2025-12-31')
        result = orch.neutralize_factors(['factor_a', 'factor_b'], incremental=True)
        print(result.summary())
    """

    def __init__(
        self,
        start_date: str,
        end_date: str,
        conn=None,
    ):
        from app.services.db import get_sync_conn

        # FactorCache import path robustness (repo-root vs backend/ cwd)
        try:
            from data.factor_cache import FactorCache
        except ModuleNotFoundError:
            from backend.data.factor_cache import FactorCache

        # 必须在任何可能失败的初始化前先设置 _own_conn (否则 __del__ 崩溃)
        self._own_conn = conn is None
        self._conn = conn or get_sync_conn()
        self._start = start_date
        self._end = end_date
        self._pool = SharedDataPool(start_date, end_date, conn=self._conn)
        self._checkpoint = CheckpointTracker(self._conn)
        self._validator = QualityValidator(self._conn)
        self._cache = FactorCache()

    def __del__(self):
        # 防御: 若 __init__ 早期失败, 属性可能未设置
        try:
            if getattr(self, "_own_conn", False) and getattr(self, "_conn", None):
                conn = self._conn
                if hasattr(conn, "closed") and not conn.closed:
                    conn.close()
        except Exception:
            pass  # silent_ok: __del__ 异常不能传播

    @property
    def shared_pool(self) -> SharedDataPool:
        """获取共享数据池 (供外部IC评估等使用)。"""
        return self._pool

    def neutralize_factors(
        self,
        factor_names: list[str],
        incremental: bool = True,
        validate: bool = True,
    ) -> PipelineResult:
        """中性化多个因子 — 共享数据 + 增量 + 质量验证。

        Args:
            factor_names: 因子列表
            incremental: True=只处理未中性化的日期, False=全量重跑
            validate: 是否在中性化后做质量检查
        """
        from engines.fast_neutralize import fast_neutralize_batch

        run_id = f"neutralize_{int(time.time())}"
        result = PipelineResult(run_id=run_id)
        t_all = time.time()

        # 预加载共享数据 (一次)
        shared_ctx = self._pool.as_neutralize_context()

        for factor_name in factor_names:
            t0 = time.time()

            # 增量检测
            if incremental:
                pending = self._checkpoint.get_pending_neutralize_dates(factor_name)
                if not pending:
                    logger.info("  %s: 无需中性化 (全部已完成)", factor_name)
                    result.stages[factor_name] = StageResult(
                        stage="neutralize", status="skipped",
                    )
                    continue
                # 用增量日期范围
                inc_start = str(min(pending))
                inc_end = str(max(pending))
                logger.info(
                    "  %s: 增量 %d天 (%s ~ %s)",
                    factor_name, len(pending), inc_start, inc_end,
                )
            else:
                inc_start = self._start
                inc_end = self._end

            # 执行中性化 (复用现有 fast_neutralize_batch)
            try:
                n_rows = fast_neutralize_batch(
                    factor_names=[factor_name],
                    start_date=inc_start,
                    end_date=inc_end,
                    conn=self._conn,
                    update_db=True,
                    write_parquet=False,
                    shared_context=shared_ctx,
                )
                status = "success" if n_rows > 0 else "partial"
            except Exception as e:
                logger.error("中性化失败: %s — %s", factor_name, e)
                result.stages[factor_name] = StageResult(
                    stage="neutralize", status="failed",
                    elapsed_seconds=time.time() - t0, error=str(e),
                )
                continue

            # 质量验证
            quality = None
            if validate and n_rows > 0:
                quality = self._validator.validate_neutralized(factor_name)
                if quality["overall"] == "FAIL":
                    logger.warning(
                        "质量检查 FAIL: %s — %s", factor_name, quality["issues"]
                    )

            elapsed = time.time() - t0
            result.stages[factor_name] = StageResult(
                stage="neutralize", status=status,
                rows_out=n_rows, elapsed_seconds=elapsed,
                quality=quality,
            )
            logger.info(
                "  %s: %s, %d行, %.0fs, quality=%s",
                factor_name, status, n_rows, elapsed,
                quality["overall"] if quality else "skip",
            )

        result.total_elapsed = time.time() - t_all
        return result

    # ================================================================
    # P0-4: 读取 / 监控 / 质量聚合 入口
    # ================================================================

    def get_raw_values(
        self,
        factor_name: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """读 raw_value. 走 FactorCache, miss 则 DB+cache."""
        return self._cache.load(
            factor_name, column="raw_value", start=start, end=end, conn=self._conn,
        )

    def get_neutral_values(
        self,
        factor_name: str,
        start: date | None = None,
        end: date | None = None,
    ) -> pd.DataFrame:
        """读 neutral_value. 走 FactorCache, miss 则 DB+cache."""
        return self._cache.load(
            factor_name, column="neutral_value", start=start, end=end, conn=self._conn,
        )

    def check_freshness(self, asset_names: list[str]) -> dict:
        """检查各 asset MAX(trade_date) 是否满足 freshness SLA."""
        cur = self._conn.cursor()
        results = {}
        for asset in asset_names:
            try:
                cur.execute(f"SELECT MAX(trade_date) FROM {asset}")
                row = cur.fetchone()
                max_date = row[0] if row else None
                today = date.today()
                lag_days = (today - max_date).days if max_date else None
                results[asset] = {
                    "max_date": str(max_date) if max_date else None,
                    "lag_days": lag_days,
                    "status": "FRESH" if lag_days is not None and lag_days <= 2 else "STALE",
                }
            except Exception as e:
                self._conn.rollback()
                results[asset] = {"status": "ERROR", "error": str(e)}
        return results

    def run_daily_quality(
        self,
        trade_date: date | None = None,
        factor_names: list[str] | None = None,
    ) -> dict:
        """组合 L1 + L2 + L3 + 返回 §4.4 JSON 格式报告."""
        return self._validator.daily_report(
            trade_date=trade_date, factor_names=factor_names,
        )

    def compute_ic(
        self,
        factor_names: list[str],
        horizon: int = 20,
        universe_filter=Universe,
    ) -> PipelineResult:
        """IC 评估 (铁律 19: 走 ic_calculator 统一口径).

        将结果写入 factor_ic_history (铁律 17: DataPipeline).

        Args:
            factor_names: 因子列表
            horizon: 前瞻天数 (默认 20d)
            universe_filter: Universe 类 (None = 关闭过滤)

        Returns:
            PipelineResult with one stage per factor.
        """
        from engines.ic_calculator import (
            compute_forward_excess_returns,
            compute_ic_series,
            summarize_ic_stats,
        )

        run_id = f"compute_ic_{int(time.time())}"
        result = PipelineResult(run_id=run_id)
        t_all = time.time()

        # 1) 准备 price + benchmark (单次加载)
        ctx = self._pool._ensure_loaded()
        benchmark_df = ctx.get("benchmark_df")
        if benchmark_df is None or benchmark_df.empty:
            raise RuntimeError("compute_ic 需要 benchmark_df, SharedDataPool 未加载")

        # 用 DB 拿 price_wide (复用 factor_repository 后续可提供单独接口, 这里临时写)
        cur = self._conn.cursor()
        cur.execute(
            """
            SELECT code, trade_date, close * COALESCE(adj_factor, 1.0) AS adj_close
            FROM klines_daily
            WHERE trade_date BETWEEN %s AND %s
              AND close IS NOT NULL
            """,
            (self._start, self._end),
        )
        price_rows = cur.fetchall()
        cur.close()
        price_df = pd.DataFrame(price_rows, columns=["code", "trade_date", "adj_close"])
        price_df["trade_date"] = pd.to_datetime(price_df["trade_date"])

        fwd_wide = compute_forward_excess_returns(price_df, benchmark_df, horizon=horizon)

        for factor_name in factor_names:
            t0 = time.time()
            try:
                nv = self.get_neutral_values(factor_name)
                if nv.empty:
                    result.stages[factor_name] = StageResult(
                        stage="compute_ic", status="skipped",
                        error="neutral_value 无数据",
                    )
                    continue
                nv["trade_date"] = pd.to_datetime(nv["trade_date"])
                factor_wide = nv.pivot_table(
                    index="trade_date", columns="code", values="value", aggfunc="last",
                )
                ic_series = compute_ic_series(factor_wide, fwd_wide)
                stats = summarize_ic_stats(ic_series)
                elapsed = time.time() - t0

                result.stages[factor_name] = StageResult(
                    stage="compute_ic", status="success",
                    rows_out=len(ic_series),
                    elapsed_seconds=elapsed,
                    quality={"ic_mean": stats.get("mean"), "ic_ir": stats.get("ir")},
                )
                logger.info(
                    "  %s: IC mean=%.4f IR=%.3f (%d天, %.1fs)",
                    factor_name,
                    stats.get("mean", 0.0),
                    stats.get("ir", 0.0),
                    len(ic_series),
                    elapsed,
                )
            except Exception as e:
                logger.error("compute_ic 失败: %s — %s", factor_name, e)
                result.stages[factor_name] = StageResult(
                    stage="compute_ic", status="failed",
                    elapsed_seconds=time.time() - t0, error=str(e),
                )

        result.total_elapsed = time.time() - t_all
        return result
