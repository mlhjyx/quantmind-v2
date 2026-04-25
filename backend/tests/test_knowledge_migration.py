"""MVP 1.4 migration script 解析单测 (纯函数, 不触 DB)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 用 append 保 stdlib `platform` 不被覆盖
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))


def test_parse_frontmatter_yaml() -> None:
    """ADR frontmatter 解析 — 支持标量 / int list / str list."""
    from scripts.knowledge.register_adrs import _parse_frontmatter

    text = """---
adr_id: ADR-001
title: Platform 包名 backend.qm_platform
status: accepted
related_ironlaws: [38, 22]
recorded_at: 2026-04-17
---

## Context

Some context.

## Decision

Use backend.qm_platform.

## Consequences

OK.
"""
    meta, body = _parse_frontmatter(text)
    assert meta["adr_id"] == "ADR-001"
    assert meta["status"] == "accepted"
    assert meta["related_ironlaws"] == [38, 22]
    assert "## Context" in body
    assert "backend.qm_platform" in body


def test_extract_adr_section() -> None:
    """ADR body section 提取 (Context / Decision / Consequences)."""
    from scripts.knowledge.register_adrs import _extract_section

    body = """
## Context

背景内容行 1.
背景内容行 2.

## Decision

决策内容.

## Consequences

正面: xxx.
负面: yyy.
"""
    ctx = _extract_section(body, "Context")
    dec = _extract_section(body, "Decision")
    cons = _extract_section(body, "Consequences")

    assert "背景内容行 1" in ctx
    assert "背景内容行 2" in ctx
    assert "## " not in ctx  # 不应跨 section
    assert "决策内容" in dec
    assert "正面" in cons and "负面" in cons


def test_failed_bullet_extraction() -> None:
    """research-kb/failed 的 `- 失败原因:` bullet 提取."""
    from scripts.knowledge.migrate_research_kb import _extract_bullet

    text = """# 失败方向: 双周调仓
- 日期: 2026-04-02
- 假设: 更频繁调仓可以更快捕捉因子信号
- 结果: Sharpe从0.91降到0.73
- 失败原因: 交易成本翻倍但alpha增量不足以覆盖
- 适用条件: 当前5因子组合
- 不应重复: 在因子池不变的情况下增加调仓频率
"""
    reason = _extract_bullet(text, "失败原因")
    adapt = _extract_bullet(text, "适用条件")
    missing = _extract_bullet(text, "不存在的键")

    assert reason == "交易成本翻倍但alpha增量不足以覆盖"
    assert adapt == "当前5因子组合"
    assert missing is None


def test_tag_inference() -> None:
    """tag 推断 — 关键词匹配."""
    from scripts.knowledge.migrate_research_kb import _infer_tags

    assert "ml" in _infer_tags("LightGBM 17 因子 WF 实验")
    assert "portfolio" in _infer_tags("MVO riskfolio 等权")
    assert "rebalance" in _infer_tags("双周调仓失败")
    assert _infer_tags("完全无关字串 xyz") == ["misc"]


def test_merge_dedupes_by_direction() -> None:
    """merge_failed_entries — 同方向合并, md-sourced 优先."""
    from scripts.knowledge.migrate_research_kb import FailedDirEntry, merge_failed_entries

    claude = FailedDirEntry(
        direction="双周调仓",
        reason="Sharpe降",
        evidence=["CLAUDE.md: G2实验"],
        severity="terminal",
        source="CLAUDE.md",
        tags=["rebalance"],
    )
    md = FailedDirEntry(
        direction="双周调仓",
        reason="交易成本翻倍",
        evidence=["docs/research-kb/failed/biweekly.md"],
        severity="terminal",
        source="docs/research-kb/failed/biweekly.md",
        tags=["rebalance", "portfolio"],
    )
    merged = merge_failed_entries([claude], [md])
    assert len(merged) == 1
    assert merged[0].source.endswith(".md")  # md-sourced 优先
    assert len(merged[0].evidence) == 2
    assert "rebalance" in merged[0].tags and "portfolio" in merged[0].tags
