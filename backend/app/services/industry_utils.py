"""行业分类统一查询模块。

提供申万一级/二级行业的统一查询接口。
所有需要行业数据的模块统一调用本模块，不再各自查不同的表。

数据源:
  - symbols.industry_sw1: 申万二级行业(~111个)
  - symbols.industry_sw_l1: 申万一级行业(~31个)，从Tushare映射生成
  - sw_industry_mapping: 二级→一级映射表

用法:
    from app.services.industry_utils import get_industry_l1_map, get_industry_l2_map

    # 全量映射
    l1_map = get_industry_l1_map(conn)   # {code: '食品饮料', ...}
    l2_map = get_industry_l2_map(conn)   # {code: '白酒', ...}

    # 单只查询
    ind = get_industry_l1('600519', conn)  # '食品饮料'
"""

from __future__ import annotations

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


def get_industry_l1(code: str, conn) -> str | None:
    """获取股票的申万一级行业。

    Args:
        code: 股票代码(6位纯数字，如'600519')
        conn: psycopg2连接

    Returns:
        一级行业名称，或None(未找到)
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT industry_sw_l1 FROM symbols WHERE code = %s AND market = 'astock'",
        (code,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def get_industry_l2(code: str, conn) -> str | None:
    """获取股票的申万二级行业。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT industry_sw1 FROM symbols WHERE code = %s AND market = 'astock'",
        (code,),
    )
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def get_industry_l1_map(conn) -> dict[str, str]:
    """返回全量 {code: sw_l1_name} 映射。

    用于因子中性化、画像行业中性IC等批量操作。
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT code, industry_sw_l1 FROM symbols "
        "WHERE market = 'astock' AND industry_sw_l1 IS NOT NULL"
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def get_industry_l2_map(conn) -> dict[str, str]:
    """返回全量 {code: sw_l2_name} 映射（申万二级）。"""
    cur = conn.cursor()
    cur.execute(
        "SELECT code, industry_sw1 FROM symbols "
        "WHERE market = 'astock' AND industry_sw1 IS NOT NULL"
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def get_industry_l1_series(conn) -> pd.Series:
    """返回 pd.Series(index=code, values=sw_l1_name)。

    与factor_profiler._load_shared_data()的industry_map格式对齐。
    """
    mapping = get_industry_l1_map(conn)
    return pd.Series(mapping, name="industry_sw_l1")


def get_industry_l2_series(conn) -> pd.Series:
    """返回 pd.Series(index=code, values=sw_l2_name)。"""
    mapping = get_industry_l2_map(conn)
    return pd.Series(mapping, name="industry_sw1")


def get_l2_to_l1_map(conn) -> dict[str, str]:
    """返回 {sw_l2_name: sw_l1_name} 映射。

    从sw_industry_mapping表读取（如果存在），
    否则从symbols表推断。
    """
    cur = conn.cursor()
    try:
        cur.execute("SELECT sw_l2_name, sw_l1_name FROM sw_industry_mapping")
        return {r[0]: r[1] for r in cur.fetchall()}
    except Exception:
        # fallback: 从symbols表推断
        cur.execute(
            "SELECT DISTINCT industry_sw1, industry_sw_l1 FROM symbols "
            "WHERE market = 'astock' AND industry_sw1 IS NOT NULL "
            "AND industry_sw_l1 IS NOT NULL"
        )
        return {r[0]: r[1] for r in cur.fetchall()}
