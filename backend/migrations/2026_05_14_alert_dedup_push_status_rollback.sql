-- Rollback for 2026_05_14_alert_dedup_push_status.sql (HC-1b3)
-- 幂等 (DROP COLUMN IF EXISTS). 仅在需回滚 DingTalk push-status 持久化时执行.
-- 注: 回滚后 meta_monitor._collect_dingtalk 会 fail-loud (列不存在) — 须同步回滚
--   dingtalk_alert.py + meta_monitor_service.py HC-1b3 代码 (反 schema/code 漂移).

BEGIN;

ALTER TABLE alert_dedup DROP COLUMN IF EXISTS last_push_ok;
ALTER TABLE alert_dedup DROP COLUMN IF EXISTS last_push_status;

COMMIT;
