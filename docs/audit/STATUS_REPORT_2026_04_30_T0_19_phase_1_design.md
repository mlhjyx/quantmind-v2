# STATUS_REPORT — T0-19 Phase 1 Design + Finding (2026-04-30)

**Date**: 2026-04-30 ~17:30+
**Branch**: chore/t0-19-phase1-design
**Base**: main @ ba2680c (PR #166 D3-A Step 4 narrative v3 修订 merged)
**Scope**: T0-19 修法 design (无业务代码改) + 10-Q finding + 3 audit scripts + Phase 2 prompt 草稿
**0 业务代码 / 0 .env / 0 Servy / 0 DML / 0 实战 sell**

---

## §0 环境前置 + STOP gate

| 项 | 实测 | 结论 |
|---|---|---|
| E1 git status | main @ `ba2680c` (PR #166), 8 D2 untracked | ✅ |
| E2 PG | 0 stuck (沿用 D3-C E2) | ✅ |
| E3 Servy 4 服务 | ALL Running (沿用) | ✅ |
| E4 Python | 3.11.9 | ✅ |
| E5 LIVE_TRADING_DISABLED | True (default config.py:44) + EXECUTION_MODE=paper (.env) | ✅ 双锁 |
| E6 真账户 ground truth | 沿用 PR #166 v3 narrative (4-30 14:54 实测 0 持仓 + ¥993,520.16) | ✅ |

10-Q investigation **0 hard STOP** (prompt 询问类问题, 非断言推翻). 全部 finding 报告 §1.

---

## §1 10-Q Finding (实测证据)

### Q1 — emergency_close_all_positions.py dry-run 是否真短路 broker?

**实测** (`scripts/emergency_close_all_positions.py` L243-329):

```python
# L266-271: 无条件 connect + query (即使 dry-run)
positions, broker = _resolve_positions_via_qmt()
# L279-283: 默认 dry-run path 在 _execute_sells 调用前 return 0
if not args.execute:
    print("ℹ️  DRY-RUN mode. No orders placed.")
    return 0
# L306: 仅 --execute 路径 reach _execute_sells
summary = _execute_sells(broker, sellable)
```

**结论**: ✅ **dry-run 真短路 broker.place_order**, 但**无条件**连 QMT + query_positions (read-only).

**Phase 1 测试影响**: 验证脚本可调 `python scripts/emergency_close_all_positions.py` 不带 `--execute`, 0 真金风险, 仅触发 QMT query (LIVE_TRADING_DISABLED=true 进一步 broker 层硬阻 sell, 双锁 fail-secure).

---

### Q2 — trade_log schema (timestamp / is_backfilled / source)

**实测** (`information_schema.columns`):

```
id           uuid (PK, gen_random_uuid())
code         varchar (NOT NULL)
trade_date   date (NOT NULL)
strategy_id  uuid (NULL)
direction    varchar (NOT NULL, 'sell'/'buy')
quantity     int (NOT NULL)
fill_price   numeric (NULL)
commission   numeric (NULL)
stamp_tax    numeric (NULL)
total_cost   numeric (NULL)
execution_mode varchar (default 'paper')
reject_reason  varchar (NULL)  ← LL-059/PR #41 backfill marker 模式
created_at     timestamptz (default now())
executed_at    timestamptz (NULL, 真实成交时点)
signal_price   numeric (NULL)
order_qty      int (NULL)
... 其他 5 列 (target_price/slippage_bps/swap_cost/market)
```

**关键发现**:
- ❌ **NO `is_backfilled` 字段** — Phase 2 backfill 必须用 `reject_reason='T0_19_backfill_<ISO8601>'` 沿用 LL-059 / PR #41 模式 (sentinel column)
- ✅ `executed_at` (timestamptz, NULL) — 可写 4-29 真实 fill 时点 (10:43:54.xxx)
- ✅ `created_at` 默认 now() — 写入时记录 backfill 时点 (与 executed_at 区分)

**Phase 2 backfill design**:
```python
INSERT INTO trade_log (
    code, trade_date, strategy_id, direction, quantity,
    fill_price, executed_at, execution_mode, reject_reason
) VALUES (
    %s, '2026-04-29', '28fc37e5...', 'sell', %s,
    %s, %s::timestamptz, 'live',
    'T0_19_backfill_2026-04-29_emergency_close'
);
```

---

### Q3 — risk_event_log CHECK constraint allowed values

**实测** (`pg_get_constraintdef`):

```
risk_event_log_action_taken_check:
  CHECK (action_taken IN ('sell', 'alert_only', 'bypass'))
risk_event_log_severity_check:
  CHECK (severity IN ('p0', 'p1', 'p2', 'info'))
risk_event_log_execution_mode_check:
  CHECK (execution_mode IN ('paper', 'live'))
risk_event_log_shares_check:
  CHECK (shares >= 0)
```

**结论**: ✅ **`'sell'` 是合法 action_taken value**, T0-19 audit row 用 `'sell'` 最贴 emergency_close 真清仓语义 (区别于 PR #161 `id=67beea84` 用的 `'alert_only'`, 那是 silent drift audit 仅 alert 不 action).

**LL-24 候选 (PR #166 SHUTDOWN_NOTICE §7 保留)**: ✅ **实测确认** — risk_event_log CHECK enum 必先 `pg_get_constraintdef` 实测, 不假设. 沿用 LL #24 复用规则.

**Phase 2 audit row** schema 决议:
```python
{
    'rule_id': 't0_19_emergency_close_audit_2026_04_29',
    'severity': 'p1',  # T0-19 是 P1 (audit 缺失) 不是 P0 (silent drift)
    'execution_mode': 'live',
    'action_taken': 'sell',  # ← 真清仓语义, 非 alert_only
    'shares': 18,            # 总股数枚举 (18 sell orders)
    ...
}
```

---

### Q4 — cb_state 表结构 + live 当前值 + reset 真值取法

**实测**:

```
2 表:
- cb_state (transition log, append-only)
- circuit_breaker_state (current state, upsert)

circuit_breaker_state live 当前行 (id=116bd790):
  current_level: 0
  trigger_reason: '正常'
  trigger_metrics: {'nav': 1011714.08, 'rolling_5d': -0.001458, 'rolling_20d': null,
                    'daily_return': -0.002432, 'cumulative_return': 0.011714}
  updated_at: 2026-04-28 16:30:21+08  ← 4-28 schtask 最后写, 自此无更新
```

**关键漂移**: trigger_metrics.nav=¥1,011,714.08 是 DB 4-28 stale 快照 (vs xtquant 4-30 14:54 实测 ¥993,520.16, diff -¥18,194).

**reset 真值取法决议**:

| 选项 | 风险 | 推荐 |
|---|---|---|
| (a) hardcoded ¥993,520.16 (4-30 14:54 实测时点) | 5-1+ 后 nav 漂移 (cash 利息 / 等), 但本系统 cash 0 利息 (国金 modest) → diff 极小 | ✅ **推荐** |
| (b) 实时 trader.query_stock_asset (真金风险: 需 trader.connect, broker 层硬阻保证 read-only) | 需 LIVE_TRADING_DISABLED=true 二级硬开关验证 + xtquant query 不触 sell/buy | ⚠️ 备选 (Phase 2 user 决议) |

**Phase 2 design**: 默认 (a), 但加 `--realtime` flag 触发 (b) 由 user 决议. Phase 1 不 reset (留 PT 重启 gate).

---

### Q5 — position_snapshot DELETE FK cascade?

**实测** (`pg_constraint` confrelid='position_snapshot'):

```
(empty result)
```

**结论**: ✅ **NO FK refs to position_snapshot** — DELETE 4-28 19 行 0 cascade 风险.

**仍留 PT 重启 gate (SHUTDOWN_NOTICE §9)**: 真 DELETE 留 user 授权时点, Phase 2 hook **仅写 snapshot 0 行 for trade_date=2026-04-30 + execution_mode=live** (清仓后真状态), DB 4-28 stale 由 PT 重启 gate 一次性 DELETE.

---

### Q6 — context_snapshot 字段类型 + chat_authorization signature schema

**实测**: `context_snapshot jsonb` (沿用 PR #161 audit row id=67beea84 已用 jsonb).

**chat_authorization signature schema design** (jsonb 嵌套):

```jsonc
{
  "auth": {
    "timestamp": "2026-04-29T10:40:00+08:00",  // user chat 授权时点 (估算, ±15min)
    "mode": "chat-driven",                      // 来源标记
    "claude_session": "session-44-cleanup",     // 关联 Claude session
    "prompt_excerpt": "全清仓暂停 PT + 加固风控",  // user 指令原文 (handoff 引用)
    "delegate": "Claude (claude-opus-4-7)",      // 谁执行
    "boundary_check": {
      "live_trading_disabled": false,            // 4-29 时 .env 仍 paper→live
      "execution_mode": "live"
    }
  },
  "execution": {
    "script": "scripts/emergency_close_all_positions.py",
    "args": ["--execute", "--confirm-yes"],
    "started_at": "2026-04-29T10:43:54.921+08:00",
    "completed_at": "2026-04-29T10:44:00+08:00",
    "log_file": "logs/emergency_close_20260429_104354.log",
    "exit_code": 0,
    "broker_session_id": 104354766151
  },
  "fills": [
    {
      "code": "600028.SH", "volume": 8600, "fill_price": 5.39,
      "order_id": 1090551138, "executed_at": "2026-04-29T10:43:55.153+08:00",
      "status": 56, "partial_fills": []
    },
    // ... 17 more
  ],
  "summary": {
    "total_orders": 18, "total_fills": 28,  // partial fills 多次
    "total_value_estimated": 901090.00,      // pre-fill DB 4-28 mv
    "total_value_actual": 882896.00,         // post-fill (NAV diff back-calc)
    "diff_pct": -2.02                         // slippage / market move
  },
  "audit_trail": {
    "phase_2_backfill_pr": "<待 Phase 2 PR 号>",
    "phase_2_run_at": "<Phase 2 run timestamp>",
    "phase_1_design_pr": "<本 PR 号>"
  }
}
```

---

### Q7 — Idempotency 算法 (重入检测)

**实测 emergency_close 现状**: 0 idempotency guard (每次 run 创建新 log file with timestamp suffix, 无 lockfile, 无 trade_log 重入检测).

**设计选项**:

| 选项 | 描述 | 优劣 |
|---|---|---|
| (a) Lockfile + atomic | `LOG_DIR/emergency_close.lock` PID + start_at, 启动检 + atexit 清 | 简单, but crash + manual cleanup |
| (b) trade_log 重入检测 | 启动时 SELECT count from trade_log WHERE reject_reason LIKE 'T0_19_backfill_%' AND trade_date=today | 无 lockfile, 复用 trade_log 真表 |
| (c) Hook flag file | hook 完成后写 `LOG_DIR/emergency_close_<ts>_DONE.flag`, 重入检 sibling .log 无 .DONE 视为 incomplete | 文件系统层面 idempotent |
| (d) 数据库 advisory lock | `pg_advisory_lock(<emergency_close_session_44>)` 启动时 try, 退出释 | DB 层 idempotent, crash 后自动释 |

**推荐**: **(c) Hook flag file + (b) trade_log 重入检测 双保险**:
- (c) Phase 2 hook 完成最后一步 (写 risk_event_log audit) 后 touch flag → audit chain 完整性证据
- (b) Phase 2 启动 + Phase 1 验证脚本均 grep `trade_log.reject_reason='T0_19_backfill_<date>'` 看是否已 backfill, 阻 double-write

**重入场景决议**:
- Crash mid-fill (e.g. 18 股 sell 第 10 股后 Python OOM): emergency_close 重跑会再 sell 已卖股 → ground truth 丢失. Phase 2 hook 加 `--continue-from-log <log>` flag, 解析 last completed fill, 跳过. 但**这是 Phase 2 设计**, 不在本 phase scope.
- Hook 重入 (Phase 2 PR merged 后误跑): trade_log 重入检测 raise + skip with WARNING.

---

### Q8 — emergency_close_all_positions.py 文件结构 + hook 插入点

**实测** (336 行):

```
L29-43:  imports + path setup
L45-57:  logging config
L60-86:  _resolve_positions_via_qmt() — connect + query
L89-97:  _classify_market(code)
L100-116: _fetch_market_price(code)
L119-177: _print_plan(positions) → (sellable, skipped)
L180-196: _confirm_execute() interactive prompt
L199-240: _execute_sells(broker, sellable) → summary
L243-324: main()
  L266-271: connect + query
  L273:    _print_plan
  L275-277: empty sellable → exit 0
  L279-283: dry-run path → exit 0
  L285-294: --execute confirm
  L295-305: AUDIT log
  L306:    summary = _execute_sells(broker, sellable)  ← T0-19 hook 候选 1
  L308-322: print summary
  L324:    return 0/3
L327-336: __name__ == "__main__" wrap (try/except sys.exit)
```

**Hook 插入点决议**:

| 候选 | 位置 | 优劣 |
|---|---|---|
| **(a) After _execute_sells L306** | summary dict 已就位, broker 仍连, 直接 hook | ✅ **推荐** — 单点修改, 同步路径 |
| (b) atexit handler | crash 也会跑 (除 SIGKILL), 但需 global state | 备选, crash recovery 更鲁棒 |
| (c) Per-fill in _execute_sells L227 | 每股 sell 后立 audit | 太碎, 18 次 DB write 性能差 |

**推荐**: **(a) After L306, before L308**, 加 try/except 包裹 (hook 失败不影响 sells 完成):

```python
# T0-19 修法插入点 (Phase 2)
try:
    from app.services.t0_19_audit import write_post_close_audit
    write_post_close_audit(
        broker=broker,
        sells_summary=summary,
        log_file=LOG_FILE,
        chat_authorization=_collect_chat_authorization(args),
    )
except Exception as hook_err:
    # 铁律 33 fail-loud: hook 失败 stderr + log, 不阻 sells 完成
    logger.error("[T0-19 hook] FAILED: %s", hook_err, exc_info=True)
    print(f"\n⚠️  T0-19 audit hook FAILED: {hook_err}", file=sys.stderr)
```

---

### Q9 — --confirm-yes flag 实现 + audit signature 触发条件

**实测** (`scripts/emergency_close_all_positions.py` L252-256):

```python
parser.add_argument(
    "--confirm-yes",
    action="store_true",
    help="跳过交互式 'YES SELL ALL' 确认 (audit trail 保留, 用于 chat-driven 授权)",
)
```

**audit signature 触发条件**:
- L286-289: `if args.confirm_yes: logger.warning("[Confirm] --confirm-yes flag bypass interactive prompt (chat-driven 授权)")`
- L299-305: 无条件 stderr `[AUDIT] _execute_sells invoked at <ts> pid=<pid> sellable_count=<N> confirm_yes=<bool>` (PR #139 reviewer fix)

**Phase 2 design**: chat_authorization signature 写入 **无条件** (不仅 --confirm-yes 触发) — 真清仓事件**任**何启动方式都需 audit. 这是治理升级.

---

### Q10 — log fields 完整性 (backfill viability)

**实测** (`logs/emergency_close_20260429_104354.log`):

```bash
grep -cE "成交回报" logs/emergency_close_20260429_104354.log
# 28  ← 28 fill events for 18 stocks (partial fills 多次)
grep -oE "code=[0-9]{6}\.(SH|SZ), price=[0-9.]+, volume=[0-9]+" \
     logs/emergency_close_20260429_104354.log | head -10
# code=600028.SH, price=5.39, volume=8600
# code=600900.SH, price=26.63, volume=1800
# code=600938.SH, price=39.62, volume=1300
# ...
```

**Per-fill 字段完整性**:
- ✅ code (e.g. `600028.SH`)
- ✅ price (e.g. `5.39`, 单位元/股)
- ✅ volume (e.g. `8600`, 整数股)
- ✅ order_id (相邻行, e.g. `1090551138`)
- ✅ timestamp (logging 行前缀, e.g. `2026-04-29 10:43:55,153`)
- ✅ status code (50/55/56, 56=全成交, 55=部分成交)

**Backfill 算法** (Phase 2):
```python
# 每股 (code, order_id) 聚合 partial fills:
fills_by_order = {}
for line in log_lines:
    if "成交回报" in line:
        # parse code, price, volume, order_id, timestamp
        key = (code, order_id)
        fills_by_order.setdefault(key, []).append({...})

# 18 trade_log rows (per order_id):
for (code, order_id), fills in fills_by_order.items():
    total_qty = sum(f.volume for f in fills)
    weighted_avg_price = sum(f.price * f.volume for f in fills) / total_qty
    earliest_ts = min(f.timestamp for f in fills)  # 第一次部分成交时点
    INSERT trade_log (code=code, direction='sell', quantity=total_qty,
                      fill_price=weighted_avg_price, executed_at=earliest_ts,
                      reject_reason='T0_19_backfill_2026-04-29_emergency_close',
                      execution_mode='live', strategy_id='28fc37e5...')
```

**Backfill 完整性验证**: 18 trade_log rows × volume 累计应等于 user 4-29 上午 18 股清仓量. 用 (a) DB 4-28 position_snapshot.quantity ↔ trade_log backfill quantity 对账 + (b) NAV diff -¥18,194 ↔ trade_log fill_price × quantity - commission - stamp_tax 对账.

---

## §2 T0-19 修法 Design Draft (4 项)

### 2.1 Phase 2 修法范围 (4 项, 无第 5 项必要)

CC 反驳 prompt "应加第 5 项" — 经 Phase 1 实测分析, 4 项已 cover audit 完整性闭环:

| # | 修法项 | 关联表 | 触发时点 |
|---|---|---|---|
| 1 | **trade_log backfill × 18 rows** | trade_log | post-execution hook (after _execute_sells return) |
| 2 | **risk_event_log P1 audit row** | risk_event_log | 同 hook (写完 trade_log 后) |
| 3 | **performance_series 当日 row** | performance_series | 同 hook (写完 audit 后) |
| 4 | **position_snapshot 当日 0 行 + cb_state reset** | position_snapshot / circuit_breaker_state | 同 hook (final step) |

**为何无第 5 项**:
- ❌ 钉钉 notify: T0-19 是 audit 后置, 不需实时告警 (PR #150 钉钉静音 verified)
- ❌ 钉钉静音解除: PT 重启 gate 时 user 决议, 不在 emergency_close hook scope
- ❌ slack/email/etc: 项目无 slack/email channel
- ❌ Servy restart: 0 业务进程依赖 emergency_close (broker 是 short-lived)

---

### 2.2 函数签名

```python
# backend/app/services/t0_19_audit.py (Phase 2 新增)

from typing import Any
from datetime import datetime
from pathlib import Path

def write_post_close_audit(
    broker: Any,                    # MiniQMTBroker connected instance
    sells_summary: dict[str, Any],  # _execute_sells() return
    log_file: Path,                 # emergency_close log path
    chat_authorization: dict[str, Any],  # signature schema (Q6)
    *,
    realtime_cb_reset: bool = False,  # Q4 (b) flag, default (a)
    dry_run_audit: bool = False,    # Phase 2 self-test
) -> dict[str, Any]:
    """T0-19 修法: emergency_close post-execution audit + DB sync.

    4 项修法 (顺序硬性, 任 1 失败 raise + 已写 row 不 rollback):
      1. trade_log backfill × N (per order_id, weighted avg fill_price)
      2. risk_event_log P1 audit row (action_taken='sell', shares=18)
      3. performance_series 当日 row (post-fill nav)
      4. position_snapshot 当日 0 行 + circuit_breaker_state reset

    Args:
        broker: 已连接 broker (用于 query_stock_asset 取 post-fill nav, 若 realtime_cb_reset=True)
        sells_summary: _execute_sells return dict (含 submitted/failed)
        log_file: emergency_close log path (用于 fill detail backfill)
        chat_authorization: chat-driven 授权 signature (Q6 schema)
        realtime_cb_reset: True=trader.query_stock_asset 取 post-fill nav, False=hardcoded ¥993,520
        dry_run_audit: True=不真写 DB, 仅打印 SQL (self-test 模式)

    Returns:
        dict: {
            'trade_log_inserted': int,
            'risk_event_log_id': uuid,
            'performance_series_id': uuid,
            'position_snapshot_cleared': int,
            'cb_state_reset_to_nav': float,
            'idempotency_flag_path': Path,
        }

    Raises:
        T0_19_AlreadyBackfilledError: 重入检测命中 (trade_log 已有 reject_reason='T0_19_backfill_<date>')
        T0_19_AuditCheckError: CHECK constraint 拒 (沿用 LL #24 复用规则)
        T0_19_LogParseError: log_file 解析 fill detail 失败

    See:
        docs/audit/STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md (本文档 §2)
        scripts/audit/check_t0_19_implementation.py (Phase 2 merged 后立验)
    """
    ...


def _collect_chat_authorization(args: argparse.Namespace) -> dict[str, Any]:
    """收集 chat-driven 授权 signature (Q6 schema).

    若 args.confirm_yes=True → mode='chat-driven', else 'interactive'.
    """
    ...
```

---

### 2.3 Idempotency 算法 (Q7)

```python
# Step 0: 重入检测 (Phase 2 hook 启动时)
def _check_idempotency(trade_date: str, log_file: Path) -> None:
    # (b) trade_log 重入检测
    sql = """
        SELECT COUNT(*) FROM trade_log
        WHERE trade_date = %s
          AND execution_mode = 'live'
          AND reject_reason LIKE 't0_19_backfill_%%'
    """
    count = db.fetch_scalar(sql, (trade_date,))
    if count > 0:
        raise T0_19_AlreadyBackfilledError(
            f"trade_log 已有 {count} 行 reject_reason='t0_19_backfill_*' "
            f"for trade_date={trade_date}. 重入检测命中, skip."
        )

    # (c) Hook flag 文件
    flag_path = log_file.with_suffix('.DONE.flag')
    if flag_path.exists():
        raise T0_19_AlreadyBackfilledError(
            f"Hook flag 已存在: {flag_path}. 完整性证据存在, skip."
        )


# Step 5: 写 flag (final step)
def _write_idempotency_flag(log_file: Path, summary: dict) -> Path:
    flag_path = log_file.with_suffix('.DONE.flag')
    flag_path.write_text(json.dumps({
        'completed_at': datetime.now().isoformat(),
        'trade_log_inserted': summary['trade_log_inserted'],
        'risk_event_log_id': str(summary['risk_event_log_id']),
        'audit_chain_complete': True,
    }))
    return flag_path
```

---

### 2.4 Dry-run 测试方案 (Phase 2 self-test)

```bash
# 1. Mock data: emergency_close_20260429_104354.log 真 log 不动 (4-29 ground truth)
# 2. write_post_close_audit(..., dry_run_audit=True) 模式: 不真 INSERT, 仅打印 SQL
# 3. 验证脚本: scripts/audit/check_t0_19_implementation.py
#    - grep 'def write_post_close_audit' backend/app/services/t0_19_audit.py
#    - grep 'T0_19_AlreadyBackfilledError' backend/app/exceptions.py
#    - dry_run_audit=True 真跑一次, verify 输出 18 INSERT trade_log SQL + 1 risk_event_log SQL + 1 performance_series SQL + 1 position_snapshot SQL + 1 cb_state UPDATE SQL
#    - 验证 LIVE_TRADING_DISABLED=true + dry_run_audit=True 双锁 (任 1 false 即 raise, fail-secure)
# 4. CI 集成: pre-push smoke 加 t0_19_audit dry-run subprocess test
```

---

## §3 Phase 2 CC Prompt 草稿 (基于 Phase 1 finding 反推)

```markdown
# CC 任务: T0-19 修法 Phase 2 (业务代码 + 4 项修法落地)

## ① 背景上下文

- Phase 1 已完结 (PR #<phase 1 PR 号>): docs/STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md
  + scripts/audit/check_t0_19_implementation.py
- 真账户 ground truth: 0 持仓 + ¥993,520.16 cash + LIVE_TRADING_DISABLED=true 双锁 fail-secure
- 4-29 emergency_close 真 log: logs/emergency_close_20260429_104354.log (28 fill events / 18 stocks)
- DB stale: position_snapshot 4-28 19 行 + circuit_breaker_state.live nav=¥1,011,714.08
- Phase 1 design draft 4 项修法 (trade_log backfill / risk_event_log audit /
  performance_series row / position_snapshot + cb_state reset)
- LL #24 (CHECK constraint allowed values 必先实测) + LL-093 (forensic 5 类源)

## ② 强制全面思考 (8 题, 任 1 答案与 Phase 1 design 不符 → STOP)

题 1: backend/app/services/t0_19_audit.py 是新文件 vs 加入 existing module?
题 2: T0_19_AlreadyBackfilledError + 2 其他 exception 加 backend/app/exceptions.py?
题 3: 4 项写 DB 顺序硬性是 (1)→(2)→(3)→(4) 还是有依赖? (e.g. trade_log 必先于 risk_event_log audit)
题 4: hook 失败如何处理已写 row? (transaction 包裹 vs 各 step 独立 commit)
题 5: scripts/emergency_close_all_positions.py L306 后插 hook code 真合并?
题 6: dry_run_audit=True 模式如何 mock DB connection (psycopg2 不允许 dry-run)?
题 7: chat_authorization 时间戳 ±15min 估算是否够精确? (audit chain 法律级 vs ops 级)
题 8: backfill 18 trade_log 后 weighted_avg_price 是否需 commission/stamp_tax 估算填入?

## ③ 主动发现 / ④ 挑战 Phase 1 假设 / ⑤ 硬执行边界

(沿用 Phase 1 prompt 模板, 0 实战 sell, 仅业务代码改 + DB DML 必经 user 决议)

## ⑥ 输出 (5 deliverable)

(a) backend/app/services/t0_19_audit.py (新, ~250 行)
(b) backend/app/exceptions.py 加 3 exception classes
(c) scripts/emergency_close_all_positions.py L306 插 hook (~10 行)
(d) backend/tests/test_t0_19_audit.py (新, ~150 行 unit + integration)
(e) docs/audit/STATUS_REPORT_T0_19_phase_2_implementation.md

## ⑦ Phase 2 完结 trigger event-driven 验证

PR merged 后立刻跑:
  - python scripts/audit/check_t0_19_implementation.py
  - 期望 exit 0 + 5/5 项 ✅
若 1 项 ✗ → 回 Phase 2 修.
```

---

## §4 验证脚本 (3 个 + README)

见 `scripts/audit/check_alembic_sync.py` + `check_t0_19_implementation.py` + `check_pt_restart_gate.py` + `scripts/audit/README.md`.

**event-driven trigger 时点**:
- `check_alembic_sync.py`: 任何 backend/migrations/*.sql 加 / apply 后立刻跑 (期望 alert_dedup / platform_metrics / strategy_evaluations 3 表存在)
- `check_t0_19_implementation.py`: T0-19 Phase 2 PR merged 后立刻跑 (期望 5/5 项 ✅)
- `check_pt_restart_gate.py`: 批 2 P0 修启动前 / 完结后跑 (期望 7/7 项 ✅ 才允许 PT 重启)

---

## §5 Tier 0 债 + LL 不变

- Tier 0 债 16 项不变 (本 phase 1 不改)
- LL 累计 27 不变 (本 phase 1 不加新 LL, Phase 2 可能加 LL-094 idempotency 重入设计)

---

## §6 硬门验证

| 硬门 | 结果 |
|---|---|
| 0 业务代码改 | ✅ |
| 0 .env / configs/ 改 | ✅ |
| 0 服务重启 | ✅ |
| 0 DML | ✅ |
| 0 实战 sell | ✅ (10-Q 仅 read-only DB query + grep + view) |
| 0 alembic upgrade | ✅ (本 phase 不 revision, 留 Phase 2 / 批 2 处理 F-D3A-1) |
| 0 触 LLM SDK / 钉钉 | ✅ |
| 0 merge PR | ✅ (draft mode, 等 user review) |

---

## §7 关联

- T0-19 来源: PR #166 SHUTDOWN_NOTICE_2026_04_30 §6 + STATUS_REPORT_D3_C F-D3C-13 + F-D3C-25
- 4-29 真 log: logs/emergency_close_20260429_104354.log (PR #166 §4 已收录 18 股完整清单)
- LL-24 候选 (CHECK constraint 实测): SHUTDOWN_NOTICE §7
- LL-093 (forensic 5 类源): LESSONS_LEARNED.md
- LL #24 (CHECK constraint 必实测): 沿用复用规则
- F-D3A-1 P0 阻塞: 3 missing migrations (alert_dedup / platform_metrics / strategy_evaluations) — 与 T0-19 独立, 但批 2 一起修

---

## §8 下一步

User review Phase 1 PR (本 PR draft mode):
- Phase 1 design 4 项修法 user 接受?
- 反驳 / 加第 5 项?
- Phase 2 prompt 草稿 user 调整?
- 验证脚本 event-driven 时点 user 接受 (vs cron schedule)?

User 决议后:
- Phase 2 启动 (CC 接 Phase 2 prompt 草稿 + Phase 1 finding 跑业务代码)
- 或 D3 整合 PR (CLAUDE.md narrative 同步) 优先
- 或 批 2 P0 修启动 (T0-15/16/18 + F-D3A-1 4 PR 串行)

---

## §9 PR 结构

**branch**: `chore/t0-19-phase1-design`
**files (5)**:
- `docs/audit/STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md` (本文档)
- `scripts/audit/check_alembic_sync.py`
- `scripts/audit/check_t0_19_implementation.py`
- `scripts/audit/check_pt_restart_gate.py`
- `scripts/audit/README.md` (扩 existing 5 scripts + 新 3 scripts 用法)

**PR title 候选 3 个**:
1. `chore(audit): T0-19 phase 1 design + 3 audit scripts (event-driven trigger, no business code)`
2. `docs(t0-19): phase 1 design + finding (10-Q investigation) + audit scripts trio`
3. `chore(t0-19): phase 1 — design draft + verification scripts (alembic / t0_19 / pt_gate)`

**PR mode**: **draft** (等 user review 后转 ready-for-review + merge).
