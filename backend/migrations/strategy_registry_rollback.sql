-- MVP 3.2 Strategy Framework — strategy_registry + strategy_status_log 回滚
-- 紧急 rollback 用. 数据损失: 所有 strategy_registry 行 + strategy_status_log 审计清零.
-- 注意: DROP 前确认 daily_pipeline 已停 registry.get_live() 调用 (防 production 崩).

DROP TRIGGER IF EXISTS trg_strategy_registry_touch ON strategy_registry;
DROP FUNCTION IF EXISTS _strategy_registry_touch_updated_at();

DROP TABLE IF EXISTS strategy_status_log;  -- FK CASCADE 自然先 drop
DROP TABLE IF EXISTS strategy_registry;

-- 验证: SELECT * FROM information_schema.tables WHERE table_name IN ('strategy_registry','strategy_status_log'); -- 预期 0 rows
