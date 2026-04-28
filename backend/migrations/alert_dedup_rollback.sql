-- MVP 4.1 Observability Framework — batch 1 alert_dedup rollback
-- Emergency rollback: 仅在 PostgresAlertRouter 部署后发现重大缺陷需回退时执行.
-- 注意: 回退后 17 scripts 散落 dedup 状态恢复 (Redis/file/none 三态并存), Application 路径
--       要从 alert_router.fire() 恢复直调 dingtalk.send_markdown_sync.

DROP INDEX IF EXISTS idx_alert_dedup_source_fired;
DROP INDEX IF EXISTS idx_alert_dedup_suppress_until;
DROP TABLE IF EXISTS alert_dedup;
