"""因子健康检查脚本 — 检测NaN/NULL/异常值/覆盖率/缓存一致性。

用法:
    python scripts/factor_health_check.py                    # 全量检查
    python scripts/factor_health_check.py RSQR_20 dv_ttm     # 指定因子
    python scripts/factor_health_check.py --year 2024         # 指定年份

输出: 每个因子的健康状态 (✅/❌/⚠️) + 问题明细
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

import numpy as np
import pandas as pd
import psycopg2


def get_conn():
    return psycopg2.connect(
        host="localhost", port=5432,
        dbname="quantmind_v2", user="xin",
        password=os.getenv("PG_PASSWORD", "quantmind"),
    )


def check_factor(cur, factor_name: str, year: int | None = None) -> dict:
    """对单个因子做健康检查。

    Returns:
        dict with keys: factor_name, status (✅/❌/⚠️), issues list, stats
    """
    issues = []
    stats = {}

    # 确定日期范围
    if year:
        date_start, date_end = f"{year}-01-01", f"{year}-12-31"
        label = f"{year}"
    else:
        date_start, date_end = "2014-01-01", "2026-12-31"
        label = "全量"

    # 1. 基本统计
    cur.execute("""
        SELECT COUNT(*) as total,
            MIN(trade_date) as min_date,
            MAX(trade_date) as max_date,
            COUNT(DISTINCT code) as n_stocks,
            COUNT(DISTINCT trade_date) as n_dates,
            SUM(CASE WHEN raw_value IS NULL THEN 1 ELSE 0 END) as rv_null,
            SUM(CASE WHEN raw_value IS NOT NULL AND raw_value::text = 'NaN' THEN 1 ELSE 0 END) as rv_nan,
            SUM(CASE WHEN neutral_value IS NULL THEN 1 ELSE 0 END) as nv_null,
            SUM(CASE WHEN neutral_value IS NOT NULL AND neutral_value::text = 'NaN' THEN 1 ELSE 0 END) as nv_nan,
            SUM(CASE WHEN neutral_value IS NOT NULL AND neutral_value::text != 'NaN' THEN 1 ELSE 0 END) as nv_valid
        FROM factor_values
        WHERE factor_name = %s AND trade_date BETWEEN %s AND %s
    """, (factor_name, date_start, date_end))
    r = cur.fetchone()

    total, min_date, max_date, n_stocks, n_dates = r[0], r[1], r[2], r[3], r[4]
    rv_null, rv_nan, nv_null, nv_nan, nv_valid = r[5], r[6], r[7], r[8], r[9]

    if total == 0:
        return {
            "factor_name": factor_name, "status": "❌",
            "issues": [f"无数据 ({label})"], "stats": {},
        }

    stats = {
        "total": total, "min_date": str(min_date), "max_date": str(max_date),
        "n_stocks": n_stocks, "n_dates": n_dates,
        "rv_null": rv_null, "rv_nan": rv_nan,
        "nv_null": nv_null, "nv_nan": nv_nan, "nv_valid": nv_valid,
    }

    # 2. 检查 raw_value NaN (不应存在, float NaN != SQL NULL)
    if rv_nan > 0:
        pct = rv_nan / total * 100
        issues.append(f"raw_value含float NaN: {rv_nan:,}行 ({pct:.1f}%)")

    # 3. 检查 neutral_value NaN (P0级问题)
    if nv_nan > 0:
        pct = nv_nan / total * 100
        if pct > 50:
            issues.append(f"❌ neutral_value全部NaN: {nv_nan:,}行 ({pct:.1f}%) — 中性化失败!")
        else:
            issues.append(f"neutral_value含float NaN: {nv_nan:,}行 ({pct:.1f}%)")

    # 4. 检查 neutral_value NULL (可能是北向因子未中性化)
    nv_null_pct = nv_null / total * 100
    if nv_null_pct > 90:
        issues.append(f"neutral_value全部NULL: {nv_null:,}行 ({nv_null_pct:.1f}%) — 未中性化")
    elif nv_null_pct > 10:
        issues.append(f"neutral_value部分NULL: {nv_null:,}行 ({nv_null_pct:.1f}%)")

    # 5. 检查数值范围 (neutral_value应该在z-score范围内)
    if nv_valid > 0:
        cur.execute("""
            SELECT MIN(neutral_value::float), MAX(neutral_value::float),
                   AVG(neutral_value::float), STDDEV(neutral_value::float)
            FROM factor_values
            WHERE factor_name = %s AND trade_date BETWEEN %s AND %s
              AND neutral_value IS NOT NULL AND neutral_value::text != 'NaN'
        """, (factor_name, date_start, date_end))
        vmin, vmax, vmean, vstd = cur.fetchone()
        stats["nv_min"] = round(float(vmin), 4) if vmin else None
        stats["nv_max"] = round(float(vmax), 4) if vmax else None
        stats["nv_mean"] = round(float(vmean), 4) if vmean else None
        stats["nv_std"] = round(float(vstd), 4) if vstd else None

        if vmin is not None and float(vmin) < -10:
            issues.append(f"neutral_value最小值异常: {float(vmin):.2f} (< -10)")
        if vmax is not None and float(vmax) > 10:
            issues.append(f"neutral_value最大值异常: {float(vmax):.2f} (> 10)")
        if vstd is not None and float(vstd) < 0.01:
            issues.append(f"neutral_value标准差过小: {float(vstd):.4f} (可能是常数)")

    # 6. 检查数据覆盖率 (最近交易日是否有数据)
    cur.execute("""
        SELECT MAX(trade_date) FROM factor_values
        WHERE factor_name = %s AND raw_value IS NOT NULL
    """, (factor_name,))
    latest_date = cur.fetchone()[0]
    stats["latest_data_date"] = str(latest_date) if latest_date else None

    # 7. 检查Parquet缓存是否包含此因子
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache", "backtest")
    if year:
        pq_path = os.path.join(cache_dir, str(year), "factor_data.parquet")
    else:
        pq_path = os.path.join(cache_dir, "2024", "factor_data.parquet")

    if os.path.exists(pq_path):
        try:
            pq_df = pd.read_parquet(pq_path, columns=["factor_name"])
            in_parquet = factor_name in pq_df["factor_name"].unique()
            stats["in_parquet"] = in_parquet
            if not in_parquet:
                issues.append("不在Parquet缓存中")
        except Exception:
            stats["in_parquet"] = "error"
    else:
        stats["in_parquet"] = "no_cache"

    # 判定状态
    has_critical = any("❌" in i for i in issues)
    has_warning = len(issues) > 0

    if has_critical or nv_nan > total * 0.5:
        status = "❌"
    elif has_warning:
        status = "⚠️"
    else:
        status = "✅"

    return {
        "factor_name": factor_name,
        "status": status,
        "issues": issues,
        "stats": stats,
    }


def check_parquet_db_consistency(cur, factor_name: str, year: int = 2024) -> dict:
    """检查Parquet缓存与DB的一致性（抽样）。"""
    cache_dir = os.path.join(os.path.dirname(__file__), "..", "cache", "backtest")
    pq_path = os.path.join(cache_dir, str(year), "factor_data.parquet")

    if not os.path.exists(pq_path):
        return {"consistent": None, "reason": "Parquet不存在"}

    pq_df = pd.read_parquet(pq_path)
    pq_df = pq_df[pq_df["factor_name"] == factor_name]
    if len(pq_df) == 0:
        return {"consistent": None, "reason": "因子不在Parquet中"}

    # 抽样10个日期
    sample_dates = sorted(pq_df["trade_date"].unique())
    if len(sample_dates) > 10:
        step = len(sample_dates) // 10
        sample_dates = sample_dates[::step][:10]

    mismatches = 0
    total_checked = 0

    for dt in sample_dates:
        pq_sub = pq_df[pq_df["trade_date"] == dt].set_index("code")["raw_value"]
        # DB查询
        cur.execute("""
            SELECT code, COALESCE(neutral_value, raw_value)::float
            FROM factor_values
            WHERE factor_name = %s AND trade_date = %s
              AND (neutral_value IS NOT NULL OR raw_value IS NOT NULL)
        """, (factor_name, str(dt)))
        db_dict = {r[0]: r[1] for r in cur.fetchall()}

        for code in pq_sub.index[:20]:  # 每日抽20只
            if code in db_dict:
                pq_val = float(pq_sub[code])
                db_val = db_dict[code]
                if not (np.isnan(pq_val) and np.isnan(db_val)):
                    if abs(pq_val - db_val) > 0.001:
                        mismatches += 1
                total_checked += 1

    if total_checked == 0:
        return {"consistent": None, "reason": "无重叠数据"}

    match_pct = (total_checked - mismatches) / total_checked * 100
    return {
        "consistent": match_pct > 99,
        "match_pct": round(match_pct, 1),
        "checked": total_checked,
        "mismatches": mismatches,
    }


def main():
    parser = argparse.ArgumentParser(description="因子健康检查")
    parser.add_argument("factors", nargs="*", help="指定因子名(不指定=全量)")
    parser.add_argument("--year", type=int, default=None, help="指定检查年份(默认全量)")
    parser.add_argument("--check-parquet", action="store_true", help="检查Parquet一致性(慢)")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细统计")
    args = parser.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # 获取因子列表
    if args.factors:
        factors = args.factors
    else:
        year_filter = args.year or 2024
        cur.execute(
            "SELECT DISTINCT factor_name FROM factor_values WHERE trade_date BETWEEN %s AND %s ORDER BY factor_name",
            (f"{year_filter}-01-01", f"{year_filter}-12-31"),
        )
        factors = [r[0] for r in cur.fetchall()]

    print(f"检查 {len(factors)} 个因子" + (f" ({args.year}年)" if args.year else " (全量)"))
    print("=" * 80)

    results = {"ok": [], "warn": [], "fail": []}
    t_start = time.time()

    for i, f in enumerate(factors):
        result = check_factor(cur, f, args.year)
        status = result["status"]

        # 分类
        if status == "✅":
            results["ok"].append(result)
        elif status == "⚠️":
            results["warn"].append(result)
        else:
            results["fail"].append(result)

        # 输出
        s = result["stats"]
        line = f"  {status} {f:<35}"
        if s:
            line += f" rows={s.get('total',0):>10,}"
            if s.get("nv_valid"):
                line += f"  nv_valid={s['nv_valid']:>10,}"
            if s.get("nv_nan"):
                line += f"  nv_NaN={s['nv_nan']:>8,}"
            if s.get("nv_null") and s["nv_null"] > s.get("total", 1) * 0.5:
                line += f"  nv_NULL={s['nv_null']:>8,}"
        print(line)

        if result["issues"] and (args.verbose or status == "❌"):
            for issue in result["issues"]:
                print(f"      → {issue}")

        # Parquet一致性检查
        if args.check_parquet and status == "✅":
            pq_check = check_parquet_db_consistency(cur, f, args.year or 2024)
            if pq_check.get("consistent") is False:
                print(f"      → ⚠️ Parquet不一致: {pq_check['match_pct']}% match ({pq_check['mismatches']} mismatches)")
            elif pq_check.get("consistent") is True:
                if args.verbose:
                    print(f"      → Parquet一致 ({pq_check['match_pct']}%, {pq_check['checked']}个样本)")

    # 汇总
    elapsed = time.time() - t_start
    print("\n" + "=" * 80)
    print(f"检查完成 ({elapsed:.1f}s)")
    print(f"  ✅ 健康: {len(results['ok'])}")
    print(f"  ⚠️ 警告: {len(results['warn'])}")
    print(f"  ❌ 异常: {len(results['fail'])}")

    if results["fail"]:
        print("\n❌ 异常因子详情:")
        for r in results["fail"]:
            print(f"  {r['factor_name']}: {'; '.join(r['issues'])}")

    if results["warn"]:
        print("\n⚠️ 警告因子:")
        for r in results["warn"]:
            print(f"  {r['factor_name']}: {'; '.join(r['issues'])}")

    conn.close()
    return 0 if not results["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())
