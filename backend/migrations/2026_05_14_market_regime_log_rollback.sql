--- Rollback: 2026_05_14_market_regime_log.sql
---
--- 用途: 删除 V3 §5.3 market_regime_log table (TB-2a DDL rollback).
--- 沿用 migrations rollback 体例 (PR #315 risk_metrics_daily / PR #313 reentry / 等).
---
--- 关联: V3 §5.3 + ADR-029/036/064/066

BEGIN;

DROP TABLE IF EXISTS market_regime_log;

COMMIT;
