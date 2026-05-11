--- V3 §S5 L1 实时化 — risk_event_log schema 回滚 (sub-PR 5a, 2026-05-11)
---
--- 回滚 4 个 S5 扩展列。生产环境回滚前确认无下游依赖。

BEGIN;

ALTER TABLE risk_event_log DROP COLUMN IF EXISTS cadence;
ALTER TABLE risk_event_log DROP COLUMN IF EXISTS priority;
ALTER TABLE risk_event_log DROP COLUMN IF EXISTS realtime_metrics;
ALTER TABLE risk_event_log DROP COLUMN IF EXISTS detection_latency_ms;

COMMIT;
