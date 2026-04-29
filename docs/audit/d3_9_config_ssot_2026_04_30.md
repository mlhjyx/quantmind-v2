# D3.9 配置 SSOT 审计 — 2026-04-30

**Scope**: .env / Settings / runtime os.environ override / SSOT 漂移
**铁律**: 34 (config single source of truth) / X1-X7 (v3.0 新铁律)
**0 改动**: 纯诊断

---

## 1. Q9.1 .env 全字段清单 (实测)

```bash
grep -E "^[A-Z_]+=" backend/.env | awk -F'=' '{print $1}' | sort
```

**20 字段**: ADMIN_TOKEN / DATABASE_URL / DEEPSEEK_API_KEY / DINGTALK_KEYWORD / DINGTALK_SECRET / DINGTALK_WEBHOOK_URL / EXECUTION_MODE / LOG_LEVEL / LOG_MAX_FILES / PAPER_INITIAL_CAPITAL / PAPER_STRATEGY_ID / PT_INDUSTRY_CAP / PT_SIZE_NEUTRAL_BETA / PT_TOP_N / QMT_ACCOUNT_ID / QMT_ALWAYS_CONNECT / QMT_EXE_PATH / QMT_PATH / REDIS_URL / TUSHARE_TOKEN

---

## 2. Q9.2 Settings 类 vs .env 双向同步

```bash
.venv/Scripts/python.exe -c "from app.config import Settings; print('\n'.join(sorted(Settings.model_fields.keys())))"
```

**32 Settings 字段** (vs .env 20). **12 在 Settings 但 .env 没设, 用 default**:
- API_HOST / API_PORT (默认 localhost:8000)
- LIVE_TRADING_DISABLED (默认 True ✅ fail-secure)
- OBSERVABILITY_USE_PLATFORM_SDK (默认 True 🔴 触发 D3.1 F-D3A-1 真金风险)
- PMS_ENABLED + PMS_LEVEL{1,2,3}_DRAWDOWN + PMS_LEVEL{1,2,3}_GAIN (7 字段, ADR-010 PMS 已 deprecate 但 Settings 保留)
- REMOTE_API_KEY (用途待 D3-B 调查, test 中 mock 出现 "secret-key-123")

**.env 字段全部在 Settings 中**: ✅ 0 漂移.

### 历史 SSOT 漂移 (D2.2 sticky)

- `SKIP_NAMESPACE_ASSERT` Machine env (D2.3 临时 setx) — 不在 Settings, 不在 .env, 直读 `os.environ`. 已知, 待批 2 P3 改 settings.SKIP_NAMESPACE_ASSERT 后撤回.

---

## 3. Q9.3 Runtime os.environ override (扩 D2 Finding A)

```bash
grep -rn "os\.environ\[" backend/ scripts/ -t py
```

**实测 5 hits**:

| 路径 | 命令 | 已知? | 状态 |
|---|---|---|---|
| `scripts/intraday_monitor.py:141` | `os.environ["EXECUTION_MODE"] = "live"` | D2 Finding A 已识别 | T0-4 batch 2 P2 待删 |
| **`scripts/daily_reconciliation.py:70`** | `os.environ["EXECUTION_MODE"] = "live"` | **🔴 D2 Finding A 漏报** | **新发现, 应加批 2 P2 scope** |
| `scripts/audit/audit_orphan_factors.py:57` | read-only (`os.environ["DATABASE_URL"]`) | — | 合规 |
| `scripts/archive/fetch_*.py` | `pro = ts.pro_api(os.environ["TUSHARE_TOKEN"])` | archive 历史代码 | 合规 (archive 不 active) |

**os.environ.setdefault**: 5 hits 全在 `backend/tests/` (`test_execution_mode_isolation.py:55`, `test_load_universe.py:45`, `test_pt_audit.py:45`, `test_pt_qmt_state.py:43`, `test_restore_snapshot_20260417.py:46`) — test fixture, 合规模式.

### F-D3A-5 (P2 NEW) — D2 Finding A 漏报 1 处

`scripts/daily_reconciliation.py:70` `os.environ["EXECUTION_MODE"] = "live"` 与 `scripts/intraday_monitor.py:141` 同模式. **批 2 P2 scope 应扩**:

```python
# scripts/daily_reconciliation.py:70 (待删, 批 2 P2)
os.environ["EXECUTION_MODE"] = "live"
```

D2 Finding A 列举 1 处, 实测 2 处. **LL "假设必实测纠错" 第 6 次同质** (D2 audit 一阶概括失误).

---

## 4. Q9.3 字段名漂移 (新发现 P2)

```bash
grep -rn "DINGTALK_WEBHOOK\b" --include="*.py" .
```

| 文件:行 | 读取键 | .env 字段 | 漂移? |
|---|---|---|---|
| `backend/app/tasks/mining_tasks.py:130` | `DINGTALK_WEBHOOK_URL` | `DINGTALK_WEBHOOK_URL` | ✅ 对齐 |
| `scripts/run_gp_pipeline.py:319` | `DINGTALK_WEBHOOK_URL` | 同上 | ✅ |
| **`scripts/monitor_mvp_3_1_sunset.py:93`** | **`DINGTALK_WEBHOOK`** (无 _URL) | `DINGTALK_WEBHOOK_URL` | **🔴 字段名漂移** |

### F-D3A-7 (P2 NEW) — DINGTALK_WEBHOOK 字段名漂移

```python
# scripts/monitor_mvp_3_1_sunset.py:93
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")  # 永远 None — silent failure
```

`monitor_mvp_3_1_sunset.py` 设计是 Sunset Gate A+B+C 周日 04:00 监控, 触发条件不达时发钉钉. **此字段名漂移导致 alert 永远 silent**. 修法: `os.environ.get("DINGTALK_WEBHOOK_URL")` 或走 `settings.DINGTALK_WEBHOOK_URL`.

铁律 33 fail-loud 违反 — 字段读不到应 raise 而非返 None 走默认.

---

## 5. Q9.3 直读 os.environ.get DATABASE_URL (P3 — Settings 应有 SSOT)

7+ 脚本 `os.environ.get("DATABASE_URL")` 直读, 不走 `settings.DATABASE_URL`:

- `scripts/diag/f19_trade_log_backfill_2026-04-17.py:157`
- `backend/app/services/factor_onboarding.py:92`
- `backend/scripts/compute_factor_ic.py:70`
- `scripts/repair/restore_snapshot_20260417.py:89`
- `scripts/pt_graduation_assessment.py:51`
- `scripts/pt_audit.py:120`
- `scripts/research/investigate_pt_drawdown.py:29`

### F-D3A-8 (P3) — DATABASE_URL 直读非 Settings

铁律 34 SSOT 弱违反: 应统一走 `from app.config import settings; settings.DATABASE_URL`. 当前 7+ 脚本直读 `os.environ`, 缺少 .env 加载时会 fail (虽然 Pydantic Settings 启动时已加载 .env). **批 2 P3 scope 候选** (低优先级, 不影响当前生产).

---

## 6. SKIP_NAMESPACE_ASSERT 注释漂移 (P3)

```python
# backend/app/services/startup_assertions.py:40-41
# QuantMind-FastAPI MaxRestartAttempts=5 重启循环. 用法: 终端 `setx SKIP_NAMESPACE_ASSERT 1`
# (Windows User env, schtask/Servy spawn 自动继承), 漂移修完后撤 (`setx SKIP_NAMESPACE_ASSERT ""`).
```

### F-D3A-6 (P3) — startup_assertions.py 注释 stale

D2.3 实测发现 Servy LocalSystem 服务 **不继承 User env**, 必须 Machine env (`setx /M`). 注释 L40-41 说"User env 自动继承"是错误描述.

修法 (批 2 P3): 改用 `settings.SKIP_NAMESPACE_ASSERT` 后, 注释整段删除 (env-based 修法不再需要).

---

## 7. Findings 汇总 (P0/P1/P2/P3 分级)

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3A-5 | `daily_reconciliation.py:70` 强制 EXECUTION_MODE='live' (D2 Finding A 漏 1 处) | P2 |
| F-D3A-7 | `monitor_mvp_3_1_sunset.py:93` reads DINGTALK_WEBHOOK (无 _URL), silent failure | P2 |
| F-D3A-6 | `startup_assertions.py:40-41` 注释 stale (D2.3 已证 setx User scope 不继承 Servy) | P3 |
| F-D3A-8 | 7+ scripts 直读 `os.environ.get("DATABASE_URL")`, 应统一走 settings | P3 |

---

## 8. 关联

- **D2 Finding A** (intraday_monitor:141) — 本审计扩 1 处 (daily_reconciliation:70)
- **D2.2 SKIP_NAMESPACE_ASSERT scope** — 注释漂移 (本 F-D3A-6)
- **LL-068 同质** — D2 audit 1 阶概括, 实测 2 处 (LL 第 6 次同质)
- **铁律 33 fail-loud** — F-D3A-7 字段名漂移 silent (违反)
- **铁律 34 SSOT** — F-D3A-8 多脚本直读 os.environ (弱违反)
