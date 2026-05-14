-- HC-1b3: alert_dedup +2 columns — DingTalk push outcome 持久化 (V3 §13.3 元告警)
--
-- 目标: meta_monitor._collect_dingtalk 读最近一次真 POST DingTalk 的结果, 喂
--   evaluate_dingtalk_push rule (HC-1a). 此前 alert_dedup 只追踪 fire_count /
--   last_fired_at, 无 success/failure — DingTalk push-status collector 只能 no-signal.
--
-- 设计:
--   - last_push_ok BOOLEAN — NULL = 该 dedup_key 从未真 POST (alerts_disabled /
--     no_webhook / dedup_suppressed 路径); true = 200; false = POST 失败.
--   - last_push_status TEXT — 状态文本 (e.g. "200" / "HTTPError" / "timeout"), 审计 + detail 用.
--   - send_with_dedup (dingtalk_alert.py) 在 Step 4 真 POST 成功/失败后 UPDATE 本 2 列.
--
-- 幂等 (ADD COLUMN IF NOT EXISTS) + rollback 配对 (2026_05_14_alert_dedup_push_status_rollback.sql).
-- 关联铁律: 22 (doc 跟随代码) / 33 (Phase 2 fail-loud guard 验列存在性)

BEGIN;

ALTER TABLE alert_dedup ADD COLUMN IF NOT EXISTS last_push_ok BOOLEAN;
ALTER TABLE alert_dedup ADD COLUMN IF NOT EXISTS last_push_status TEXT;

COMMENT ON COLUMN alert_dedup.last_push_ok IS
    'HC-1b3 V3 §13.3: 最近一次真 POST DingTalk 的结果 (true=收到 200 / false=POST 失败). '
    'NULL = 该 dedup_key 从未真 POST (alerts_disabled / no_webhook / dedup_suppressed 路径). '
    'meta_monitor._collect_dingtalk 读 WHERE last_push_ok IS NOT NULL ORDER BY last_fired_at DESC.';
COMMENT ON COLUMN alert_dedup.last_push_status IS
    'HC-1b3: 最近一次真 POST 的状态文本 (e.g. "200" / "HTTPError" / "timeout"). 审计 + DingTalkPushSnapshot.last_push_status detail 用.';

COMMIT;

-- Phase 2: fail-loud guard (铁律 33, 沿用 alert_dedup.sql / llm_call_log.sql Phase 4 体例)
DO $$
DECLARE
    col_count INT;
BEGIN
    SELECT COUNT(*) INTO col_count
    FROM information_schema.columns
    WHERE table_name = 'alert_dedup'
      AND column_name IN ('last_push_ok', 'last_push_status');
    IF col_count < 2 THEN
        RAISE EXCEPTION 'alert_dedup push-status migration incomplete: only % of 2 required columns', col_count;
    END IF;
END $$;
