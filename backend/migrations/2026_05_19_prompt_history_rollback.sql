--- Rollback: drop prompt_history table + 2 indexes.

BEGIN;
DROP INDEX IF EXISTS idx_prompt_history_active;
DROP INDEX IF EXISTS idx_prompt_history_agent_created;
DROP TABLE IF EXISTS prompt_history;
COMMIT;
