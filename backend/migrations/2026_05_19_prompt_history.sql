--- AgentConfig prompt_history table — Phase H W5 + ISSUES_PENDING_REGISTRY §7 P2 真闭环.
---
--- 用途: AgentConfig PUT 用户改动持久化 + version diff/rollback 真支持 (反 LL-183
---       silent UI lie sustained pattern, H1 真闭环).
---
--- 变更:
---   1. NEW TABLE prompt_history (单 agent 多 version 累积)
---   2. UNIQUE INDEX (agent_name, version) — 反 dup version 写
---   3. INDEX (agent_name, created_at DESC) — last/active version 快 query
---
--- 关联:
---   - ISSUES_PENDING_REGISTRY §4 A4 / §7 P2 / §9 H1 (真闭环 H1 LL-183 silent UI lie)
---   - LL-187 Phase H W5 sediment
---   - DEV_AI_EVOLUTION.md §3 Agent Config (4 agents)
---
--- Rollback: 2026_05_19_prompt_history_rollback.sql
---
--- 铁律 17 (DataPipeline 入库) / 22 (doc 跟随代码) / 41 (timezone TIMESTAMPTZ)

BEGIN;

CREATE TABLE IF NOT EXISTS prompt_history (
    history_id BIGSERIAL PRIMARY KEY,
    agent_name VARCHAR(50) NOT NULL,
    version INT NOT NULL,
    display_name VARCHAR(100),
    model VARCHAR(50) NOT NULL,
    temperature REAL NOT NULL CHECK (temperature >= 0.0 AND temperature <= 2.0),
    max_tokens INT NOT NULL CHECK (max_tokens > 0),
    system_prompt TEXT NOT NULL,
    ic_threshold REAL NOT NULL DEFAULT 0.02,
    t_stat_threshold REAL NOT NULL DEFAULT 2.0,
    auto_archive BOOLEAN NOT NULL DEFAULT FALSE,
    auto_reject BOOLEAN NOT NULL DEFAULT FALSE,
    max_daily_runs INT NOT NULL DEFAULT 10 CHECK (max_daily_runs > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(50) NOT NULL DEFAULT 'system',
    CONSTRAINT chk_agent_name CHECK (agent_name IN ('idea', 'factor', 'eval', 'diagnosis')),
    CONSTRAINT chk_model CHECK (model IN (
        'deepseek-v4-flash', 'deepseek-v4-pro', 'qwen3-local',
        -- Legacy aliases pre-5-07 切换 (back-compat for historical rows)
        'deepseek-r1', 'deepseek-v3', 'qwen3'
    )),
    CONSTRAINT uq_agent_version UNIQUE (agent_name, version)
);

-- Latest version query (history view UI / fetch active config)
CREATE INDEX IF NOT EXISTS idx_prompt_history_agent_created
    ON prompt_history (agent_name, created_at DESC);

-- Active version filter (current production prompt per agent)
CREATE INDEX IF NOT EXISTS idx_prompt_history_active
    ON prompt_history (agent_name, is_active)
    WHERE is_active = TRUE;

COMMIT;
