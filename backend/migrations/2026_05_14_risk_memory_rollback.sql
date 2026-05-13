--- Rollback: 2026_05_14_risk_memory.sql
---
--- 用途: 删除 V3 §5.4 risk_memory table + 3 indexes (TB-3a DDL rollback).
--- 沿用 migrations rollback 体例 (TB-2a market_regime_log / 等).
---
--- Risk: 所有历史 risk_memory rows DELETED. 仅 schema corruption / rollback 时使用.
---
--- 关联: V3 §5.4 + ADR-064/067/068 候选

BEGIN;

DROP TABLE IF EXISTS risk_memory;

COMMIT;
