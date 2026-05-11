--- V3 §S5 L1 实时化 — risk_event_log schema 扩展 (sub-PR 5a, 2026-05-11)
---
--- 用途: 实时风控事件日志新增字段, L1 detection latency 跟踪
---
--- 变更:
---   1. cadence VARCHAR(10): tick/5min/15min/daily
---   2. priority VARCHAR(4): P0/P1/P2
---   3. realtime_metrics JSONB: tick/vol at trigger moment
---   4. detection_latency_ms INT: tick → INSERT latency
---
--- Rollback: 2026_05_11_risk_event_log_realtime_rollback.sql
---
--- 关联铁律: 22 (文档跟随代码) / 24 (单一职责) / 33 (fail-loud migration)

BEGIN;

ALTER TABLE risk_event_log
  ADD COLUMN IF NOT EXISTS cadence VARCHAR(10)
    CHECK (cadence IN ('tick', '5min', '15min', 'daily'));

ALTER TABLE risk_event_log
  ADD COLUMN IF NOT EXISTS priority VARCHAR(4)
    CHECK (priority IN ('P0', 'P1', 'P2'));

ALTER TABLE risk_event_log
  ADD COLUMN IF NOT EXISTS realtime_metrics JSONB;

ALTER TABLE risk_event_log
  ADD COLUMN IF NOT EXISTS detection_latency_ms INT
    CHECK (detection_latency_ms IS NULL OR detection_latency_ms >= 0);

COMMIT;

COMMENT ON COLUMN risk_event_log.cadence IS 'S5 L1 实时化: 触发 cadence (tick/5min/15min/daily)';
COMMENT ON COLUMN risk_event_log.priority IS 'S5 L1 实时化: 告警优先级 (P0 秒级/P1 分钟级/P2 日终)';
COMMENT ON COLUMN risk_event_log.realtime_metrics IS 'S5 L1 实时化: 触发时刻 tick/vol 快照 JSON';
COMMENT ON COLUMN risk_event_log.detection_latency_ms IS 'S5 L1 实时化: tick → INSERT 延迟 (ms), SLA P99 < 5000ms';
