--- V3 §13.2 risk_metrics_daily rollback (paired with 2026_05_13_risk_metrics_daily.sql).
--- 用途: 紧急 rollback 时清表. 保留 DDL 文件用于 re-apply.

BEGIN;
-- DROP TABLE cascades the PK index automatically (no separate DROP INDEX
-- needed since reviewer P2 dropped the redundant idx_risk_metrics_date_desc).
DROP TABLE IF EXISTS risk_metrics_daily;
COMMIT;
