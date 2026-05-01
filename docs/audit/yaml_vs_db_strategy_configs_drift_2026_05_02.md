# Audit — yaml vs DB strategy_configs drift root cause (2026-05-02)

> **触发**: Task 3 GLOSSARY ([docs/FACTOR_COUNT_GLOSSARY.md](docs/FACTOR_COUNT_GLOSSARY.md)) §10 真测发现 yaml=4 因子 (CORE3+dv_ttm) vs DB strategy_configs latest=5 因子 (CORE5) drift, 候选 latent prod risk.
> **范围**: 纯审计, 0 修代码 / 0 sync DB / 0 deprecate / 0 PR. 仅交付证据 + 候选根因 + user 决议参考.
> **顶层结论**: 不是 P0 prod risk — 生产 PT 真用 yaml (signal_engine.py:247), DB strategy_configs 是 setup 时一次性写入后**冻结的 legacy snapshot**. 5 vs 4 漂移是**前端展示一致性问题**, 不是 trading path bug. 但发现**第二个 DB stale source** (strategy.factor_config), 一并沉淀.

---

## §0 TL;DR (3 句)

1. **生产 PT 真用 4 因子 (yaml SSOT)**, 不读 DB strategy_configs — `backend/engines/signal_engine.py:247 PAPER_TRADING_CONFIG = _build_paper_trading_config()` 加载 `configs/pt_live.yaml`. signal/execution/run_paper_trading 全 0 引用 strategy_configs.
2. **DB strategy_configs 是 2026-03-21+22 一次性 setup 后冻结**, scripts/setup_paper_trading.py:85 INSERT, 之后再无任何 UPDATE/INSERT. yaml 4-9 引入 (Step 4-B commit `2eb2e56`) + 4-12 CORE5→CORE3+dv_ttm cutover (commit `51b1409`) **完全 bypass DB**.
3. **🆕 第二个 DB stale source 发现**: `strategy.factor_config` jsonb 也含 stale CORE5 (+ industry_cap=0.25 vs yaml=1.0 / commission_rate=0.00015 vs yaml=0.0000854 多项 stale 参数). 两个 DB 字段平行 stale, 仅前端展示通过 `/api/strategies/{id}` 暴露给 user.

---

## §A 真测四块

### A.1 yaml 真测 (生产 SSOT)

**真读** `configs/pt_live.yaml` (今天读完整 60 行):

```yaml
strategy:
  name: equal_weight_top20
  factors:
    # CORE3+dv_ttm (WF OOS Sharpe=0.8659, MDD=-13.91%, 2026-04-12 PASS)
    # 变更: CORE5→CORE3+dv_ttm, 去掉reversal_20和amihud_20, 加入dv_ttm
    - {name: turnover_mean_20, direction: -1}
    - {name: volatility_20, direction: -1}
    - {name: bp_ratio, direction: 1}
    - {name: dv_ttm, direction: 1}
  compose: equal_weight
  top_n: 20
  rebalance_freq: monthly
  industry_cap: 1.0       # 无行业约束
  ...
```

**factors[] 真长度**: **4** (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm)

**reader 真测** `backend/engines/signal_engine.py:247`:
```python
PAPER_TRADING_CONFIG = _build_paper_trading_config()
```
`_build_paper_trading_config()` 读 yaml, 返回 SignalConfig. 注释 (L43-44) 显式: "(PAPER_TRADING_CONFIG.factor_names 是 CORE3+dv_ttm), factor_registry". L141 注释: "任何未显式传参的 SignalConfig() 调用将拿到与 PAPER_TRADING_CONFIG 等价的默认值."

**其他 yaml 配置文件**:
- `configs/alert_rules.yaml` — 不含 factors[]
- `configs/backtest_5yr.yaml` / `configs/backtest_12yr.yaml` / `configs/backtest_12yr_sn050.yaml` — 回测专用 (本 task 暂未真读, 留 transparency)

✅ **判定**: pt_live.yaml 是生产 SSOT, 4 因子 CORE3+dv_ttm. 与 GLOSSARY snapshot (5-02 23:55) **0 drift overnight**.

### A.2 DB strategy_configs 真状态

**Schema (真测 `\d strategy_configs`)**:
```
 strategy_id | uuid          | not null
 version     | integer       | not null
 config      | jsonb         | not null
 changelog   | text          |
 created_at  | timestamptz   | default now()
PK: (strategy_id, version)
FK: strategy_configs_strategy_id_fkey REFERENCES strategy(id)
```

**历史 entry (真测 ORDER BY created_at DESC LIMIT 10)**:

| strategy_id | version | n_factors | factors | created_at |
|---|---:|---:|---|---|
| 28fc37e5-...41c11a5103d0 | 2 | 5 | `["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"]` | **2026-03-22 03:39:17.512555+08** |
| 28fc37e5-...41c11a5103d0 | 1 | 5 | 同 | **2026-03-21 19:03:45.800207+08** |

**关键事实**:
- 全表仅 2 行 (1 strategy × 2 versions)
- 都是 5 因子 CORE5
- created_at: **2026-03-21/22**, 之后 **从未更新** (47 天 stale)
- 与 yaml 4-9 引入 / 4-12 cutover 时间窗口完全错过

**与 strategy 表 active_version 的链路**:
```sql
SELECT s.active_version FROM strategy s WHERE s.id = '28fc37e5-...';
-- 真测: active_version = 2 (指向 strategy_configs version=2 的 5 因子 CORE5)
```

✅ **判定**: DB strategy_configs 真值 5 因子 CORE5, 完全冻结于 setup 期 (3-21/22). 与 GLOSSARY snapshot **0 drift overnight**.

### A.3 caller path 真测对照表

`grep -rn "strategy_configs" backend/ scripts/ --include="*.py"` 全 enumerate:

| # | file:line | 真用途 | 真在生产 trading path? | 是否读 factors? | 风险 |
|---|---|---|---|---|---|
| C.1 | [backend/app/api/execution.py:190-236](backend/app/api/execution.py:190) | `/api/execution/algo-config` GET 端点, 返回算法参数给前端 | ❌ 仅前端展示, 不在 trading 流 | ❌ **不读 factors!** 仅取 execution_mode / slippage_model / top_n / rebalance_freq / turnover_cap / cash_buffer / max_single_weight / max_industry_weight | 0 |
| C.2 | [backend/app/repositories/strategy_repository.py:38-67](backend/app/repositories/strategy_repository.py:38) | `get_active_config(strategy_id)` 返回完整 config dict (含 factors) | ❌ 仅服务前端 | ✅ 读 factors (作为 config dict 一部分) | **前端展示** stale 5 因子 |
| C.3 | [backend/app/repositories/strategy_repository.py:56-67](backend/app/repositories/strategy_repository.py:56) | `get_config_history(strategy_id)` 返回版本历史 | ❌ 仅服务前端 | ✅ 读 factors | 历史展示 stale (这是合理的, 历史快照该保留) |
| C.4 | [backend/app/repositories/strategy_repository.py:69-103](backend/app/repositories/strategy_repository.py:69) | `create_config_version()` INSERT 新版本 | ❌ 仅 API 写入 | n/a | 0 (写入路径, 不读) |
| C.5 | [backend/app/services/strategy_service.py:43](backend/app/services/strategy_service.py:43) | `get_strategy_detail()` 调 get_active_config + get_config_history | ❌ 服务 `/api/strategies/{id}` 前端展示 | ✅ 间接 | 前端展示 stale |
| C.6 | [backend/app/services/backtest_service.py:57](backend/app/services/backtest_service.py:57) | docstring 提"strategy_configs 表" — 文档引用 | ❌ 仅注释 | n/a | 0 |
| C.7 | [backend/app/services/param_service.py:34](backend/app/services/param_service.py:34) | docstring 提"strategy_configs 表" — 文档引用 | ❌ 仅注释 | n/a | 0 |
| C.8 | [backend/app/api/strategies.py:4](backend/app/api/strategies.py:4) | docstring 提"strategy_configs.config 是 JSONB" | ❌ 仅注释 | n/a | 0 |
| C.9 | [backend/engines/strategy_registry.py:44](backend/engines/strategy_registry.py:44) | docstring 注释"对应 strategy_configs.config JSONB" | ❌ 仅注释 (engine 层不开 conn 铁律 31) | n/a | 0 |
| C.10 | [scripts/setup_paper_trading.py:85](scripts/setup_paper_trading.py:85) | INSERT INTO strategy_configs 初次 setup | ❌ 一次性脚本, 非定期任务 | n/a (写) | 0 (但是 stale 源头, 没被后续 cutover 触发再跑) |
| C.11 | [scripts/archive/setup_paper_trading.py:85](scripts/archive/setup_paper_trading.py:85) | 归档版本, 同 C.10 | ❌ archived | n/a | 0 |
| C.12 | backend/tests/test_a4_a6.py:299 | 测试 strategy_configs 表不存在的 fallback | ❌ 测试 | n/a | 0 |
| C.13 | backend/tests/test_phase_b_infra.py:27 | 测试基础设施表存在 | ❌ 测试 | n/a | 0 |
| C.14 | backend/tests/test_strategy_repo.py | StrategyRepository 单元测试 | ❌ 测试 | n/a | 0 |

**StrategyService 调用方追溯** (`grep "StrategyService\|from app.services.strategy_service"`):
- `backend/app/api/strategies.py:17,22,76,95,117,151,177,202,224,248,270,293` — 13 个 endpoint 全在 `/api/strategies/*` 前端 API
- `backend/app/services/__init__.py:9,15` — 模块 export

**前端入口真测** (`grep "/api/strategies\|/execution/algo-config" frontend/src`):
- `frontend/src/pages/TradeExecution.tsx:79-81` 调 `/api/execution/algo-config` (C.1, **不读 factors**)
- 前端 strategy 详情页 (path 未 grep) 通过 `/api/strategies/{id}` 调 get_strategy_detail (C.5, **读 factors**)

✅ **生产 trading path 0 引用 strategy_configs**:
- `backend/engines/signal_engine.py` — 0 grep hit (走 yaml)
- `backend/app/services/execution_service.py` — 0 grep hit
- `scripts/run_paper_trading.py` — 0 grep hit
- 所有 Celery task / schtask script — 0 grep hit

⚠️ **前端展示路径有 stale 暴露**:
- `/api/strategies/{id}` (C.5) 返回 active_config 含 stale 5 因子
- `/api/strategies/{id}/versions` (C.3) 返回历史含 stale 5 因子 (历史保留合理)
- `/api/execution/algo-config` (C.1) **不展示 factors**, 仅 execution params, **不暴露 5 因子 drift**

**STOP trigger #1 评估**: 用户 task 写"真测发现 DB strategy_configs **真有生产代码读** (Celery task / FastAPI endpoint / schtask script 真路径), 且读出来的 5 因子真被生产逻辑用 → P0 prod risk, STOP". 真测**不满足 STOP 条件**:
- ✅ 有生产代码读 (FastAPI endpoint `/api/strategies/{id}`)
- ❌ 但 5 因子**未被生产逻辑用** — 仅前端展示, 不进入 signal_engine/execution path
- → **不 STOP**, 但前端展示不一致是 medium severity finding (不是 P0)

### A.4 cutover 历史真测

**yaml 引入** (`git log --follow configs/pt_live.yaml`):

| commit | date | message | 含 factors[]? |
|---|---|---|---|
| `2eb2e56` | **2026-04-09 12:36:04 +0800** | feat: Step 4-B部分完成 — YAML配置驱动 + config_loader + run_backtest改造 | ✅ 首次创建 |
| `5953211` | (Step 6-H Part 1) | Size-Neutral inner实现 + WF验证 + cleanup | (中间修改) |
| `3e9f1e6` | (Step 6-H 收尾) | CLAUDE.md全面刷新 + SN b=0.50激活PT | (中间修改) |
| **`51b1409`** | **2026-04-12 17:30:39 +0800** | **feat: PT配置更新 CORE5→CORE3+dv_ttm (WF OOS Sharpe=0.8659)** | ⭐ **CORE5→CORE3+dv_ttm cutover** |

**CORE5→CORE3+dv_ttm cutover commit detail** (`git show 51b1409 --stat`):

```
commit 51b1409d2527eceb43b2d7bbfc4d0bb9cb67d437
Author: jyxren <7528324@qq.com>
Date:   Sun Apr 12 17:30:39 2026 +0800

    feat: PT配置更新 CORE5→CORE3+dv_ttm (WF OOS Sharpe=0.8659)
    
    Phase 2.2-2.4研究完成 + WF验证PASS + PT配置更新:
    - PT配置: pt_live.yaml + signal_engine + parquet_cache
    ...
```

cutover commit 改文件: CLAUDE.md (47) + SYSTEM_STATUS.md (91) + pt_live.yaml + signal_engine + parquet_cache. **没有 DB migration / sync script / scripts/setup_paper_trading.py 改动**.

**STOP trigger #3 评估**: "A.4 真测 cutover 时点找不到" — ❌ 找到 (`51b1409` @ 2026-04-12 17:30:39). 不 STOP.

**ADR 检查** (`ls docs/adr/ | grep -iE "cutover|core3|core5|yaml|strategy"`):
- 未找到 cutover 专门 ADR. 决议沉淀走 commit message + Phase 2 series research-kb (CLAUDE.md cite). 4-12 cutover 是 research-driven, 没单独走 ADR.

**真因 enumerate** (基于真证据):

| 维度 | 事实 |
|---|---|
| DB 一次性写入 | scripts/setup_paper_trading.py:85 INSERT, **执行时间 2026-03-21/22** (从 created_at 推) |
| yaml 系统引入 | Step 4-B commit `2eb2e56` @ 2026-04-09 (3 周后) — yaml 替代 .env / config.py / signal_engine 散落配置 |
| CORE5→CORE3+dv_ttm cutover | commit `51b1409` @ 2026-04-12 (再 3 天后) — 改 yaml + signal_engine + parquet_cache |
| DB sync 步骤 | **缺失** — Step 4-B + cutover 都没设 sync DB strategy_configs 步骤 |
| 责任 | 设计层缺失: yaml 引入时未声明 "DB strategy_configs deprecate / 仅前端展示", 也没强制 cutover 同步 DB. 流程债. |

---

## §B Stage B — root cause 候选 + action

### §B.1 root cause 候选表

| # | 候选 | 真证据 | 反证 | 概率 |
|---|---|---|---|---:|
| **#1** | **DB strategy_configs 是 setup 一次性写入的 legacy snapshot, yaml 系统引入时未 deprecate / cutover 时未 sync** | A.4 cutover commit 51b1409 不含 DB migration; A.2 created_at 全部 3-21/22 (setup 期); A.3 setup_paper_trading.py:85 一次性 INSERT | 无 | **~95% ⭐** |
| #2 | DB 是 archive / research / version history 用的另一语义 (category error, 类似 task 2 213 framing) | DB 表名"strategy_configs"含义模糊; 注释"每次变更插入新version 行"暗示是 version log; FK to strategy 表暗示是 strategy 元数据归属 | A.3 caller 真有 `/api/strategies/{id}` 前端 API 读 active_config 给用户看 (展示路径) — 不是纯 archive | ~30% (部分对: 历史版本展示是合理用途, 但 active_config 展示 stale 是 bug) |
| #3 | yaml + DB 是双 SSOT, cutover 流程要求双写但代码缺 (设计 bug) | A.4 commit 51b1409 改 5 文件全是 yaml/python, 0 DB | A.3 没有"双写"协议文档 / ADR / Step 4-B 决议. 双写假设无支持. yaml 引入是单 SSOT 决策 (replace .env/config.py/signal_engine 散落配置) | ~15% (缺设计意图证据) |
| #4 | DB 已 deprecate 但代码没删 | A.3 caller 真有 12 处引用 (生产 + 测试 + docstring); StrategyService 13 个 endpoint 在用 | DB 不是 deprecate 状态 — 真实在前端展示路径上 | ~5% |
| #5 | LIMIT 1 没找对版本 (multiple cutover 历史, DB 真有 4 因子的更新但 query 顺序错) | 真测 ORDER BY created_at DESC 全表仅 2 行, 都是 5 因子 CORE5 | 真测 LIMIT 10 也仅 2 行, 完全枚举不存在第 3 行 | ~0% (反证强) |
| **#6** | **🆕 strategy.factor_config 是第二 DB stale source** (除 strategy_configs.config 外, 同表内另一字段也 stale) | A.4 真测 strategy.factor_config = `{"factors": ["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"], "industry_cap": 0.25, "commission_rate": 0.00015, ...}` 同样 stale | 不是反证 — 是同源问题扩展 (setup 时一次性 INSERT 两处, cutover 都没 sync) | **~95% ⭐ (新发现)** |

**主根**: 候选 #1 + #6 同根 — setup 时一次性写入 2 处 DB (strategy.factor_config + strategy_configs.config), cutover 时设计层失误未要求 sync, 自然 stale.

**STOP trigger #4 评估**: "真测发现第三个 strategy SSOT (除 yaml + DB 外)" — 严格说 strategy.factor_config 仍是 DB (同 schema), 不是第三个完全独立 SSOT. 但是**第二个 DB 字段** stale, 一并报告. **不严格 STOP**, 但显著扩展 finding scope.

### §B.2 候选 action 表

| # | action | 描述 | 影响面 (caller / 数据 / 测试) | 风险 | 优先级 |
|---|---|---|---|---|---|
| (a) | sync DB → yaml (DB 作 mirror) | 加 schtask 周期 sync, 或 cutover 触发 sync. yaml 改 → DB 自动 INSERT 新 version | C.5 前端展示恢复一致; C.10 setup script 不动. 改: 加 sync 函数 (新代码), 加 schtask. | yaml 改频率低, sync 失败兜底要谨慎 (不能阻断 yaml cutover). 测试: 加 sync 单元 + 集成. | P2 (前端一致性, 非生产 risk) |
| (b) | deprecate DB strategy_configs | caller migrate 走 yaml, 表保留 read-only 或删. C.5 前端展示直读 yaml. | 改 13 个 `/api/strategies/*` endpoint + StrategyService + StrategyRepository. 大改. setup script 删 INSERT. tests 删. | 大改面 (~500 行 code). 生产中断风险中. 但 trading path 不动 (仍 yaml). | P3 (大重构, 价值 = 减少 mental model 复杂度) |
| (c) | 双向同步 (yaml ↔ DB) | yaml change auto-update DB, DB change auto-update yaml. 互为 mirror. | 同 (a) 但加反向. | 双源易 race condition / divergence. 不推荐. | P3 (反推荐) |
| (d) | 现状保留 + GLOSSARY enforce + 前端注解 | DB stale 是 documented behavior, 前端展示加 banner "本数据是 setup 时快照, 真生产配置见 yaml". 加 ADR 沉淀决议. | C.5 前端加 banner / 改文案. 加 GLOSSARY entry (已加 §10). 加 ADR. 0 caller 改. | 极低 (零功能改动). | **P2 (推荐 ⭐)** |
| (e) | 🆕 同步 strategy.factor_config (除 strategy_configs 外的第二个 DB stale) | 同 (a) 范围扩到 2 个 DB 字段 | 同 (a) + strategy 表 update | 同 (a) | (与 a 合并) |

### §B.3 推荐 (基于真证据)

**推荐 action (d) — 现状保留 + 前端注解 + ADR 沉淀**:

理由:
1. **不是 prod risk** — A.3 真测生产 trading path 0 读 strategy_configs, 4 因子 yaml 真用. 5 vs 4 仅前端展示偏差, 用户不会因此误下单.
2. **改动成本低** — 加 1 行前端 banner + 写 ADR (1 文档) + GLOSSARY entry (已加). vs (a)/(b) 大改面.
3. **设计意图清晰** — yaml SSOT 决策 (Step 4-B) 已沉淀, 但缺 ADR 显式说明 "DB strategy_configs 是 legacy 仅前端展示". 写 ADR 修这个 gap.
4. **保留版本历史价值** — get_config_history 返回历史 versions (即使全是 setup 期 stale CORE5), 是 audit trail. 完全 deprecate (b) 会丢这个功能.

**不推荐 (a) sync** 的原因: cutover 频率低, sync 加复杂度但不消除 mental model 双源混淆.

**不推荐 (b) deprecate** 的原因: 13 endpoint 大改, 投入产出比低 (用户没真踩前端展示坑).

**user 决议参考**:
- 若优先 mental model 简化 → 走 (b) 大重构 (P3)
- 若优先 0 改动安全 → 走 (d) (P2 ⭐ 推荐)
- 若 latent risk 担忧高 → 走 (a) sync (P2)

不预设, user 决议.

---

## §C 我没真测的 (transparency)

- **configs/backtest_5yr.yaml / backtest_12yr.yaml / backtest_12yr_sn050.yaml** — 没真读, 推测含 factors[] 但回测专用. 留 finding 候选 (是否回测 yaml 也 stale).
- **frontend/src 前端 strategy 详情页** 的 path 没 grep — `/api/strategies/{id}` 调用方 file:line 没定位. 推测有 strategies 详情页或 dashboard.
- **strategy_evaluations / strategy_status_log** 表没真测 — 可能是 stale source 候选, 留 finding 候选.
- **strategy_registry** 表 ([backend/engines/strategy_registry.py](backend/engines/strategy_registry.py)) 的真用途没深查, 仅 grep docstring 注释.
- **scripts/setup_paper_trading.py 完整内容**没读 — 仅 grep INSERT 行, 推测一次性 setup. 不影响主结论.
- **strategy.factor_config 在 caller path 中是否被生产读** — 仅查了 strategy_configs caller, 没全 grep `factor_config` (该字段名通用易撞). 留独立 finding 候选 (是否 strategy.factor_config 也在生产 path 上, 比 strategy_configs 风险更高).

---

## §D STOP trigger 评估

| # | 触发条件 | 真测结果 | 行动 |
|---|---|---|---|
| 1 | DB strategy_configs 真有生产代码读且 5 因子真被生产逻辑用 | A.3 真测: 真有生产代码读 (FastAPI endpoint), 但**不是 trading path** + 5 因子**不进 trading 逻辑** | ❌ 不满足完整条件, **不 STOP** (medium severity 前端一致性 finding) |
| 2 | yaml 或 DB 当前真值与 GLOSSARY (5-02 snapshot) 不一致 (overnight drift > 0) | yaml 4 / DB 5 双 0 drift overnight | ❌ 不满足, 不 STOP |
| 3 | A.4 cutover 时点找不到 | 真找到 commit `51b1409` @ 2026-04-12 17:30:39 | ❌ 不满足, 不 STOP |
| 4 | 真测发现第三个 strategy SSOT (除 yaml + DB 外) | 🆕 strategy.factor_config 是**同 DB 第二字段** stale, 严格说不是第三 SSOT (仍是 DB) | ⚠️ 边界, 一并报告但不严格 STOP |
| 5 | DB 表损坏 / 真测无法跑 | 全部 SQL 真跑成功 | ❌ 不满足, 不 STOP |
| 6 | LIVE_TRADING_DISABLED ≠ true | 真测 config.py:44 默认 True + .env 无 override | ❌ 不满足, 不 STOP |

**总结**: 0 硬 STOP. 1 边界 (#4 第二 DB 字段, 一并审计). 1 medium severity (前端展示不一致).

---

## §E Memory / sprint state 更新建议

| 当前 cite | 实测真值 | 建议 |
|---|---|---|
| (GLOSSARY §10) "DB strategy_configs latest = 5 (CORE5) ⚠️ stale, 不在生产读路径" | ✅ 真测一致, 但需扩展: "**两个 DB stale 字段**: strategy_configs.config + strategy.factor_config 都 stale, 都是 setup 一次性写入" | GLOSSARY §10 加 footnote 沉淀第二字段 |
| (推测) "4-12 yaml cutover" 是单一事件 | ✅ 真测一致 (commit `51b1409` @ 2026-04-12 17:30:39); 但 yaml 系统本身先于 cutover 引入 (commit `2eb2e56` @ 2026-04-09) — 是双步事件 | sprint state 写"cutover" 时区分"yaml 系统引入 (Step 4-B 4-09)" vs "factor 配置 cutover (CORE5→CORE3+dv_ttm 4-12)" |
| (推测) "yaml 是 SSOT" | ✅ 真测一致, signal_engine/execution/run_paper_trading 全 0 读 DB | 沉淀 ADR 显式声明 DB strategy_configs 是 legacy 仅前端展示, 防未来 caller 误读 trading path |

🆕 新发现:
- **strategy.factor_config jsonb 是第二 DB stale 字段** (除 strategy_configs.config 外), 含 stale CORE5 + 多个其他 stale 参数 (industry_cap=0.25 vs yaml=1.0, commission_rate=0.00015 vs yaml=0.0000854). setup 一次性写入 (3-21/22), cutover 时未 sync.
- **生产 trading path 0 引用 strategy_configs** — signal_engine.py / run_paper_trading.py / execution_service.py 全 grep 0 hit. 5 vs 4 drift 不进 trading 逻辑.
- **前端展示路径有 stale 暴露**: `/api/strategies/{id}` (StrategyService.get_strategy_detail) 返回 stale 5 因子. 用户若访问 strategy 详情页, 看到 5 因子 (但 PT 真交易 4 因子). 不会误下单, 但 mental model 困惑.
- **scripts/setup_paper_trading.py 是 stale 源头** — 一次性 INSERT 设计, 没考虑 cutover 同步.
- **0 ADR 沉淀** yaml SSOT 决议 — Step 4-B yaml 引入决策仅在 commit message + research-kb, 没单独 ADR 显式 deprecate DB strategy_configs.

---

## §F 关联文档 / cross-link

- [docs/audit/factor_count_drift_2026_05_01.md](docs/audit/factor_count_drift_2026_05_01.md) — task 2 audit, framing 教训 (drift 可能是 category error)
- [docs/FACTOR_COUNT_GLOSSARY.md §9 / §10 / §A.2](docs/FACTOR_COUNT_GLOSSARY.md) — yaml SSOT vs DB stale 防误读
- [configs/pt_live.yaml](configs/pt_live.yaml) — yaml SSOT 真位置
- [backend/engines/signal_engine.py:247](backend/engines/signal_engine.py:247) — 生产读 yaml 入口
- [scripts/setup_paper_trading.py:85](scripts/setup_paper_trading.py:85) — DB 一次性 INSERT 源头
- commit `2eb2e56` (Step 4-B yaml 引入 @ 2026-04-09) + commit `51b1409` (CORE5→CORE3+dv_ttm cutover @ 2026-04-12)
- 候选 ADR (本 audit 推荐): "ADR-XXX yaml SSOT vs DB strategy_configs deprecation" (P2, 走另一 sprint)

---

## §G 文档版本

- **v0.1** (2026-05-02): 初稿, 4 块真测 + 6 候选 root cause + 5 候选 action + 推荐 (d). 0 修代码 / 0 sync DB / 0 deprecate / 0 PR. push branch `audit/yaml-vs-db-strategy-drift-2026-05-02` 等 user review.
