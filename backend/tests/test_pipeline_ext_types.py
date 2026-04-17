"""MVP 2.2 · DataPipeline ColumnSpec 扩 UUID + JSONB 类型验证 + 记录准备.

单测不依赖 DB — 只覆盖 `_validate` 逻辑层 + `_is_null` / `_prepare_cell` helper.
DB 端到端 round-trip 留 live smoke (test_mvp_2_2_lineage_live).

铁律:
  - 29 (禁 NaN 写 DB) + 33 (fail-safe 对 invalid input raise 进 reject_reasons 不 silent swallow)
  - 17 (DataPipeline 唯一入库点) + 38 (对齐 MVP 2.2 Blueprint)
"""

from __future__ import annotations

import uuid

import pandas as pd
from psycopg2.extras import Json

from app.data_fetcher.contracts import ColumnSpec, TableContract
from app.data_fetcher.pipeline import DataPipeline, _is_null, _prepare_cell

# ════════════════════════════════════════════════════════════
# Helper: 构造 ad-hoc Contract (仅用于测)
# ════════════════════════════════════════════════════════════


def _uuid_contract() -> TableContract:
    """Contract with uuid PK + nullable jsonb."""
    return TableContract(
        table_name="_test_uuid_tbl",
        pk_columns=("id",),
        columns={
            "id": ColumnSpec("uuid", nullable=False),
            "meta": ColumnSpec("jsonb", nullable=True),
        },
        fk_filter_col=None,
        skip_unit_conversion=True,
    )


def _jsonb_only_contract() -> TableContract:
    return TableContract(
        table_name="_test_jsonb_tbl",
        pk_columns=("id",),
        columns={
            "id": ColumnSpec("int", nullable=False),
            "payload": ColumnSpec("jsonb", nullable=True),
        },
        fk_filter_col=None,
        skip_unit_conversion=True,
    )


# ════════════════════════════════════════════════════════════
# UUID 验证 (5 tests)
# ════════════════════════════════════════════════════════════


def test_uuid_accepts_uuid_instance_preserves_value():
    """输入 uuid.UUID 实例 → 直通, 0 reject."""
    pipe = DataPipeline(conn=None)
    u = uuid.uuid4()
    df = pd.DataFrame([{"id": u, "meta": None}])
    valid_df, rejects = pipe._validate(df, _uuid_contract())
    assert len(valid_df) == 1
    assert rejects == {}
    # normalized 仍为 UUID 实例
    assert isinstance(valid_df["id"].iloc[0], uuid.UUID)
    assert valid_df["id"].iloc[0] == u


def test_uuid_accepts_valid_str_normalizes_to_uuid_instance():
    """输入合法 UUID 字符串 → normalize 为 uuid.UUID 实例, 0 reject."""
    pipe = DataPipeline(conn=None)
    s = "550e8400-e29b-41d4-a716-446655440000"
    df = pd.DataFrame([{"id": s, "meta": None}])
    valid_df, rejects = pipe._validate(df, _uuid_contract())
    assert rejects == {}
    assert isinstance(valid_df["id"].iloc[0], uuid.UUID)
    assert str(valid_df["id"].iloc[0]) == s


def test_uuid_rejects_invalid_str_records_reason():
    """输入非法 UUID 字符串 → reject, reject_reasons 含 invalid_uuid_id."""
    pipe = DataPipeline(conn=None)
    u_ok = uuid.uuid4()
    df = pd.DataFrame(
        [
            {"id": u_ok, "meta": None},
            {"id": "not-a-uuid", "meta": None},
        ]
    )
    valid_df, rejects = pipe._validate(df, _uuid_contract())
    assert len(valid_df) == 1
    assert rejects.get("invalid_uuid_id") == 1
    assert valid_df["id"].iloc[0] == u_ok


def test_uuid_accepts_none_when_nullable_meta():
    """nullable JSONB meta = None → 通过 (PK uuid 合法即可)."""
    pipe = DataPipeline(conn=None)
    u = uuid.uuid4()
    df = pd.DataFrame([{"id": u, "meta": None}])
    valid_df, rejects = pipe._validate(df, _uuid_contract())
    assert len(valid_df) == 1
    assert rejects == {}
    assert valid_df["meta"].iloc[0] is None


def test_uuid_non_nullable_rejects_none_pk():
    """非 null PK uuid 传 None → 被 null_id reject (baseline 逻辑)."""
    pipe = DataPipeline(conn=None)
    df = pd.DataFrame([{"id": None, "meta": None}])
    valid_df, rejects = pipe._validate(df, _uuid_contract())
    assert len(valid_df) == 0
    # null_id 是 baseline null 检测产出 (非 invalid_uuid)
    assert rejects.get("null_id") == 1


# ════════════════════════════════════════════════════════════
# JSONB 验证 (5 tests)
# ════════════════════════════════════════════════════════════


def test_jsonb_accepts_dict_preserves_value():
    """dict 输入 → 通过, 值保持."""
    pipe = DataPipeline(conn=None)
    payload = {"template_scores": {"T1": 0.5, "T2": 0.3}, "tags": ["momentum"]}
    df = pd.DataFrame([{"id": 1, "payload": payload}])
    valid_df, rejects = pipe._validate(df, _jsonb_only_contract())
    assert len(valid_df) == 1
    assert rejects == {}
    assert valid_df["payload"].iloc[0] == payload


def test_jsonb_accepts_list_including_nested():
    """list + 嵌套 dict 都通过."""
    pipe = DataPipeline(conn=None)
    payload = [{"lag": 1, "ic": 0.08}, {"lag": 5, "ic": 0.05}]
    df = pd.DataFrame([{"id": 1, "payload": payload}])
    valid_df, rejects = pipe._validate(df, _jsonb_only_contract())
    assert len(valid_df) == 1
    assert rejects == {}
    assert valid_df["payload"].iloc[0] == payload


def test_jsonb_rejects_scalar_int_records_reason():
    """int 非 dict/list → reject."""
    pipe = DataPipeline(conn=None)
    df = pd.DataFrame(
        [
            {"id": 1, "payload": {"ok": True}},
            {"id": 2, "payload": 42},  # scalar int 非法
        ]
    )
    valid_df, rejects = pipe._validate(df, _jsonb_only_contract())
    assert len(valid_df) == 1
    assert rejects.get("invalid_jsonb_payload") == 1
    assert valid_df["id"].iloc[0] == 1


def test_jsonb_accepts_none_when_nullable():
    """nullable JSONB None → 通过."""
    pipe = DataPipeline(conn=None)
    df = pd.DataFrame([{"id": 1, "payload": None}])
    valid_df, rejects = pipe._validate(df, _jsonb_only_contract())
    assert len(valid_df) == 1
    assert rejects == {}
    assert valid_df["payload"].iloc[0] is None


def test_jsonb_rejects_string_not_auto_parsed():
    """字符串不自动解析为 JSON (防止 json.loads 隐式行为), 明确 reject."""
    pipe = DataPipeline(conn=None)
    df = pd.DataFrame([{"id": 1, "payload": '{"fake": "json_string"}'}])
    valid_df, rejects = pipe._validate(df, _jsonb_only_contract())
    assert len(valid_df) == 0
    assert rejects.get("invalid_jsonb_payload") == 1


# ════════════════════════════════════════════════════════════
# Helpers (2 tests)
# ════════════════════════════════════════════════════════════


def test_is_null_handles_dict_list_uuid_safely():
    """`_is_null` 对 dict/list/UUID 不 TypeError (原 pd.isna 会崩)."""
    assert _is_null(None) is True
    assert _is_null({"k": "v"}) is False
    assert _is_null([]) is False
    assert _is_null([1, 2, 3]) is False
    assert _is_null(uuid.uuid4()) is False
    assert _is_null("some-string") is False
    assert _is_null(float("nan")) is True  # scalar NaN
    assert _is_null(1.5) is False


def test_prepare_cell_json_wraps_jsonb_dtype():
    """`_prepare_cell` jsonb → Json(...); uuid/其他 直通; null → None."""
    # None → None (任何 dtype)
    assert _prepare_cell(None, "jsonb") is None
    assert _prepare_cell(None, "uuid") is None
    assert _prepare_cell(None, "float") is None
    # jsonb dict → Json wrapper
    wrapped = _prepare_cell({"k": "v"}, "jsonb")
    assert isinstance(wrapped, Json)
    # jsonb list → Json wrapper
    wrapped_list = _prepare_cell([1, 2, 3], "jsonb")
    assert isinstance(wrapped_list, Json)
    # uuid 直通 (register_uuid adapter 自动处理)
    u = uuid.uuid4()
    assert _prepare_cell(u, "uuid") is u
    # float 直通
    assert _prepare_cell(1.5, "float") == 1.5
