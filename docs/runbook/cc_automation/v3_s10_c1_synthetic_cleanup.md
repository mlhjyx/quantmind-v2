# V3 S10 C1 Synthetic 5d Test Data — Cleanup Runbook

> **Purpose**: 清理 2026-05-13 5d operational kickoff 1:1 simulation 期间用
> `scripts/v3_s10_c1_inject_synthetic_5d.py` 注入的合成测试数据,恢复
> `risk_event_log` / `execution_plans` / `risk_metrics_daily` 至生产真值。
>
> **Trigger**: 5d 自然 fire 窗口 (5-14 → 5-20) 完成 + verify 报告 sediment 后,
> 或 user 指示提前清理。
>
> **Risk**: 0 broker / 0 真账户. 仅 DELETE 测试 row + UPDATE risk_metrics_daily.
> 红线 5/5 sustained.

## 注入清单 (2026-05-13 注入)

- `risk_event_log`: 18 行 (5-7..5-13, 5 days × 2-6 rows)
  - rule_id 前缀: `c1_synthetic_`
  - severity 分布: 5 P0 / 8 P1 / 5 P2
- `execution_plans`: 10 行 (5-7..5-13)
  - risk_reason 前缀: `c1_synthetic_`
  - mode 分布: 9 STAGED + 1 AUTO
  - status 分布: 5 EXECUTED / 2 CANCELLED / 2 TIMEOUT_EXECUTED / 1 EXECUTED (AUTO)

## 清理 SQL (运行顺序)

```sql
-- 1. 删除合成 risk_event_log
DELETE FROM risk_event_log WHERE rule_id LIKE 'c1_synthetic_%';
-- 预期: DELETE 18

-- 2. 删除合成 execution_plans
DELETE FROM execution_plans WHERE risk_reason LIKE 'c1_synthetic_%';
-- 预期: DELETE 10

-- 3. 重置 risk_metrics_daily 5-7..5-13 行 (重新聚合就会回归 0)
-- 选项 (a) — 完整删除让下次 Beat 自然 fire 重建:
DELETE FROM risk_metrics_daily WHERE date BETWEEN '2026-05-07' AND '2026-05-13';

-- 选项 (b) — 不删除, 直接重跑 aggregator (UPSERT 会更新为 0):
-- (留给 user 决议哪种更适合 audit chain)
```

## 清理验证

```sql
-- 应返回 0
SELECT COUNT(*) FROM risk_event_log WHERE rule_id LIKE 'c1_synthetic_%';
SELECT COUNT(*) FROM execution_plans WHERE risk_reason LIKE 'c1_synthetic_%';
```

## 清理后重跑 aggregator (选项 b)

```bash
.venv/Scripts/python.exe -c "
from datetime import date
from app.services.db import get_sync_conn
from backend.qm_platform.risk.metrics import aggregate_daily_metrics, upsert_daily_metrics

dates = [date(2026, 5, 7), date(2026, 5, 8), date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 13)]
conn = get_sync_conn()
try:
    for d in dates:
        result = aggregate_daily_metrics(conn, d)
        upsert_daily_metrics(conn, result)
        conn.commit()
        print(f'{d.isoformat()}: P0/P1/P2={result.alerts_p0_count}/{result.alerts_p1_count}/{result.alerts_p2_count}')
finally:
    conn.close()
"
```

## C1 测试结果 (2026-05-13, post-injection)

V3 §15.4 verify report (`docs/audit/v3_tier_a_paper_mode_5d_2026_05_13_c1.md`):

| # | Item | Result |
|---|---|---|
| 1 | P0 alert 误报率 < 30% | ✅ 0.00% (0/2) |
| 2 | L1 detection latency P99 < 5s | ❌ <no data> — `detection_latency_p99_ms` 列 deferred per aggregator docstring |
| 3 | L4 STAGED FAILED = 0 | ✅ 0 |
| 4 | 元告警 P0 = 0 | ✅ 0 |

**Verdict**: 3/4 PASS + 1 deferred (latency instrumentation 待 S5 sub-PR 或 Tier B 落地)。
端到端链路 (Celery Beat → Worker → aggregator → DB → verify CLI) 全部 1:1 验证通过。

## 关联

- PR #320: aggregator SQL column-name + severity case bug fix
- 注入 script: `scripts/v3_s10_c1_inject_synthetic_5d.py`
- Verify report (synthetic): `docs/audit/v3_tier_a_paper_mode_5d_2026_05_13_c1.md`
- ADR-062 (S10 setup) + LL-156 + 5d operational kickoff (Session 53+4 2026-05-13)
