"""Smoke test — MVP 2.2 Sub2 Data Lineage live PG 端到端 (铁律 10b).

subprocess 启动 + live PG + 真跑 DataPipeline.ingest(lineage=...) 路径:
  1. 构 Lineage (inputs=[klines_daily placeholder], code=CodeRef(git_commit, module)).
  2. ingest 1 条 factor_values (code='SMOKE_TEST_600519.SH', trade_date=1900-01-01,
     factor_name='_smoke_lineage').
  3. 验证 IngestResult.lineage_id 非空.
  4. get_lineage_for_row 反查 factor_values 目标 PK → 返非空 Lineage list.
  5. Lineage 含 git_commit (CodeRef.git_commit 字段).
  6. 清理 factor_values 行 + data_lineage 行.

失败意味: Lineage 存储 / JSONB @> containment / pipeline 埋点任一环断.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
from datetime import date

import pandas as pd

from app.data_fetcher.contracts import FACTOR_VALUES
from app.data_fetcher.pipeline import DataPipeline
from app.services.db import get_sync_conn
from backend.platform.data.lineage import (
    CodeRef,
    Lineage,
    LineageRef,
    get_lineage_for_row,
)

SMOKE_CODE = '999999.SH'  # 9 字符, varchar(10) 安全, 非真实上市代码
SMOKE_DATE = date(1900, 1, 1)
SMOKE_FACTOR = '_smoke_lineage'

conn = get_sync_conn()
recorded_lid = None
try:
    # 清理残留
    cur = conn.cursor()
    cur.execute(
        'DELETE FROM factor_values WHERE code = %s AND trade_date = %s AND factor_name = %s',
        (SMOKE_CODE, SMOKE_DATE, SMOKE_FACTOR),
    )
    conn.commit()
    cur.close()

    # 构 Lineage 含真 git commit (取当前 HEAD)
    import subprocess as _sp
    head = _sp.run(
        ['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=False
    ).stdout.strip() or 'HEAD_UNKNOWN'

    lineage = Lineage(
        inputs=[LineageRef(
            table='klines_daily',
            pk_values={'code': SMOKE_CODE, 'trade_date': SMOKE_DATE.isoformat()},
        )],
        code=CodeRef(
            git_commit=head,
            module='backend.tests.smoke.test_mvp_2_2_lineage_live',
            function='smoke_main',
        ),
        params={'smoke_batch': '2026-04-19', 'factor_name': SMOKE_FACTOR},
    )

    pipeline = DataPipeline(conn)
    df = pd.DataFrame([{
        'code': SMOKE_CODE,
        'trade_date': SMOKE_DATE,
        'factor_name': SMOKE_FACTOR,
        'raw_value': 0.123,
        'neutral_value': 0.099,
        'zscore': 0.099,
    }])
    result = pipeline.ingest(df, FACTOR_VALUES, lineage=lineage)
    assert result.upserted_rows == 1, f'upsert failed {result.upserted_rows} reject={result.reject_reasons}'
    assert result.lineage_id is not None, 'lineage_id not populated'
    assert result.lineage_id == lineage.lineage_id, 'lineage_id mismatch'
    recorded_lid = result.lineage_id

    # 反查: get_lineage_for_row 通过 GIN + @> containment 找回 Lineage
    fetched = get_lineage_for_row(
        'factor_values',
        {'code': SMOKE_CODE, 'trade_date': SMOKE_DATE.isoformat(), 'factor_name': SMOKE_FACTOR},
        conn,
    )
    assert len(fetched) >= 1, f'get_lineage_for_row empty for {SMOKE_CODE}/{SMOKE_DATE}'
    matching = [x for x in fetched if x.lineage_id == recorded_lid]
    assert len(matching) == 1, f'exact lineage not found in {len(fetched)} results'
    l = matching[0]
    assert l.code is not None, 'CodeRef missing'
    assert l.code.git_commit == head, f'git_commit mismatch: {l.code.git_commit} vs {head}'
    assert l.inputs[0].table == 'klines_daily'
    assert l.params.get('smoke_batch') == '2026-04-19'
    # outputs 自动补了 factor_values PK
    assert any(
        o.table == 'factor_values'
        and o.pk_values.get('code') == SMOKE_CODE
        and o.pk_values.get('factor_name') == SMOKE_FACTOR
        for o in l.outputs
    ), f'auto-outputs not merged: {[o.pk_values for o in l.outputs]}'

    print(f'OK 2.2 lineage live: lineage_id={recorded_lid} git={head[:8]}')
finally:
    cur = conn.cursor()
    cur.execute(
        'DELETE FROM factor_values WHERE code = %s AND trade_date = %s AND factor_name = %s',
        (SMOKE_CODE, SMOKE_DATE, SMOKE_FACTOR),
    )
    if recorded_lid is not None:
        cur.execute('DELETE FROM data_lineage WHERE lineage_id = %s', (str(recorded_lid),))
    conn.commit()
    cur.close()
    conn.close()
"""


@pytest.mark.smoke
def test_mvp_2_2_lineage_live_ingest_and_reverse_lookup() -> None:
    """DataPipeline.ingest(lineage=...) + get_lineage_for_row 端到端 (铁律 10b)."""
    result = subprocess.run(
        [sys.executable, "-c", _SMOKE_CODE],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"MVP 2.2 lineage live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 2.2 lineage live" in result.stdout, result.stdout
