---
name: quantmind-v3-redline-verify
description: V3 实施期任 broker / .env / yaml / DB row mutation / production code 改动前 5/5 红线 query + 5 condition 严核. 反 silent breach (沿用 SOP-5 LL-103 Part 2 + 真账户 0 risk 体例).
trigger: broker|.env|yaml|production code|DB row|mutation|order_stock|red line|红线|5/5|cash|LIVE_TRADING_DISABLED|EXECUTION_MODE|QMT_ACCOUNT_ID|paper→live|.env paper|sell 单
---

# QuantMind V3 Redline Verify SOP

## §1 触发条件

任 高风险 mutation 操作前必 invoke (反 silent breach):

- broker call 前 (xtquant `order_stock` / cancel / sell / buy 任一 mutation API)
- `.env` 改动前 (LIVE_TRADING_DISABLED / EXECUTION_MODE / DINGTALK_ALERTS_ENABLED / L4_AUTO_MODE_ENABLED 任一)
- yaml 改动前 (configs/pt_live.yaml / config/litellm_router.yaml / 任 production yaml)
- DB row mutation 前 (任 INSERT / UPDATE / DELETE 真生产表)
- production code 改动前 (backend/app/, backend/engines/, scripts/run_paper_trading*.py 任一)

## §2 5/5 红线 query (沿用 IRONLAWS + SHUTDOWN_NOTICE_2026_04_30 SSOT)

每次 invoke 必 verify 全 5 项 (任一漂移 → STOP + 反问 user):

| # | 红线 | 真值锚点 |
|---|---|---|
| (1) | cash | xtquant `query_asset()` 真值 (sustained ¥993,520 post-4-30 user 决议清仓) |
| (2) | positions | xtquant `query_stock_positions()` 真值 (sustained 0 持仓 post-4-30) |
| (3) | LIVE_TRADING_DISABLED | `.env` 字段 (sustained `true`) |
| (4) | EXECUTION_MODE | `.env` 字段 (sustained `paper`) |
| (5) | QMT_ACCOUNT_ID | `.env` 字段 (sustained `81001102`, 反 silent re-bind) |

verify SOP: `python scripts/_verify_account_oneshot.py` (沿用 Constitution §L0.3 step 5).

## §3 5 condition 严核 (沿用 SOP-5 LL-103 Part 2)

任 mutation 必 verify 全 5 condition (反 silent skip):

| # | condition | 例 |
|---|---|---|
| (1) | mutation **scope 与 sub-PR 声明 100% match** | sub-PR 声明 doc-only → 0 mutation 触发, 任 mutation 即 scope creep |
| (2) | mutation **PR 前置 reviewer agent verify** | LL-067 reviewer agent 必预先 verify, 反 self-approve |
| (3) | mutation **rollback path 真值 exists** | INSERT 配 DELETE 同 PR / .env paper→live 配 live→paper rollback |
| (4) | mutation **真账户 0 risk verify** | broker mock vs real / paper vs live / sandbox vs production cite |
| (5) | mutation **user 显式触发 + 红线 unlock** | sustained `redline-pretool-block` hook 阻断, user 显式 push merge |

## §4 user 介入 3 类 enforcement (沿用 Constitution §L8.1)

任 (b) 真生产红线触发类 mutation → CC 不可自决, 必 push user (skill 知识层 → hook 机制层 + push):

- LIVE_TRADING_DISABLED / EXECUTION_MODE / DB row mutation / 真生产 .env / yaml 改动 / default flag 改动 / 启 PT 信号链 / broker call

## §5 跟 hook 互补 (反替代)

| 层 | 机制 |
|---|---|
| `.claude/hooks/protect_critical_files.py` (PreToolUse[Edit\|Write] auto fire) | 现 wired — `.env` / yaml / production code path pattern auto block |
| `.claude/hooks/redline_pretool_block.py` (V3 期 全新 hook, 沿用 Constitution §L6.2 全新 hook 决议) | 待 sediment — broker / DB row mutation 5/5 红线 query + 5 condition 严核 enforce |
| 本 skill (CC 主动 invoke 知识层) | 任 mutation 前 CC 主动 cite SOP + 5/5 + 5 condition verify (反仅依赖 hook auto block) |

→ skill 是知识层, hook 是机制层. **互补不替代** (沿用 Constitution §L6.2 redline-verify 决议).

## §6 实证 cite

| 实证 | scope |
|---|---|
| 2026-04-30 user 决议清仓 (SHUTDOWN_NOTICE_2026_04_30) | 17 股 emergency_close + 1 股 user GUI sell, 真账户 0 risk |
| PR #270 audit 5/5 sustained verify (5-08) | doc-only audit, 0 mutation, 红线 cite source SSOT 锚点 |
| 5-07 sub-PR 8a-followup-pre 真生产 first verify (LL-109) | hook governance 4 days production 0 catch reverse case |
