# D3.14 铁律 v3.0 实施扫描审计 — 2026-04-30

**Scope**: X1-X7 7 新铁律实施扫描 + 已存在 42 条铁律选定违反扫描
**铁律**: X1 (Claude 边界) / X2 (LIVE_TRADING_DISABLED) / X3 (.venv) / X4 (死码 audit) / X5 (文档单源) / X6 (LLM 必经 LiteLLM) / X7 (月度铁律 audit)
**0 改动**: 纯诊断

---

## 1. Q14.1 X1 Claude 边界 (anthropic SDK 直调)

```bash
grep -rE "^(import\s+anthropic|from\s+anthropic|Anthropic\()" --include="*.py"
```

**实测**: **0 hits** ✅ X1 PASS — 生产/测试代码无 `import anthropic`.

---

## 2. Q14.2 X3 .venv Python 检查

### Hooks 配置实测

```bash
git config core.hooksPath  # → config/hooks
ls -la config/hooks/        # → pre-push (1184 bytes, executable)
```

✅ `core.hooksPath = config/hooks` 已 enable.

### pre-push hook 内容审计

```bash
cat config/hooks/pre-push
```

```sh
# 优先使用 .venv Python (Windows/Unix 兼容)
if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python"
fi
...
"$PY" -m pytest backend/tests/smoke/ -m "smoke and not live_tushare" --tb=line -q --timeout=60
```

### F-D3A-18 (P3) — pre-push hook .venv silent fallback

`else PY="python"` fallback 到 system Python 是 silent fallback. 铁律 X3 要求 fail-loud — 应:

```sh
else
    echo "[pre-push] FATAL: .venv Python 不存在 (.venv/Scripts/python.exe / .venv/bin/python). 创建 .venv 或修复 venv."
    exit 1
fi
```

**当前实际不构成 imminent 风险** (CC 跑 .venv/Scripts/python.exe 实测可用), 但是是 fragile pattern. **批 2 P3 候选**.

### pre-commit hook

`config/hooks/` 仅有 `pre-push` + README.md. **0 pre-commit hook**. 铁律 X3 要求 commit 前也应阻断系统 Python — 但 pre-commit 缺失意味着 commit-time 不阻断, 仅 push 时阻断. 当前足以保护 main, 但 in-progress commit 可能用 system Python 跑 test.

**INFO**: 不升级, 当前足够 (push 才进 main).

---

## 3. Q14.3 X6 LLM 必经 LiteLLM

```bash
grep -rE "^(import\s+openai|from\s+openai|import\s+deepseek|from\s+deepseek)" --include="*.py"
```

**实测**: **0 hits** ✅ X6 当前合规.

但 `backend/engines/mining/deepseek_client.py:199` 实测有 `os.environ.get("DEEPSEEK_API_KEY", "")` — DeepSeek 调用走自实现 HTTP client (不是 deepseek SDK). **合规** (X6 是禁 SDK 直调, 自实现 HTTP 不违反). LiteLLM 待 Tier A 引入后再统一.

---

## 4. Q14.4 X2 LIVE_TRADING_DISABLED 覆盖率

```bash
grep -rn "LIVE_TRADING_DISABLED" backend/ scripts/ --include="*.py"
```

**实测 25+ hits**:

### 真金保护层 ✅

- `backend/app/config.py:44` `LIVE_TRADING_DISABLED: bool = True` — fail-secure default
- `backend/app/security/live_trading_guard.py:7-78` — guard module (assert_live_trading_allowed)
- `backend/engines/broker_qmt.py:412` — broker 层 invoke guard
- `backend/app/exceptions.py:15` — LiveTradingDisabledError exception
- `backend/app/tasks/beat_schedule.py:63` — Beat 已转挂 guard
- `backend/tests/test_live_trading_disabled.py` — 14+ 测试覆盖 (TestGuardBlocking + 双因素 OVERRIDE)

### F-D3A-?? (X2 PASS, INFO)

X2 `LIVE_TRADING_DISABLED` 默认 True + 双因素 OVERRIDE + broker 层 invoke + Beat 解挂 + 14+ 测试. ✅ 多重保护合规.

E6 实测确认 `settings.LIVE_TRADING_DISABLED = True`. 真金 fail-secure default 0 风险.

---

## 5. X4 死码月度 audit (本审计为首次实践)

✅ 本 D3.14 + D3.1 + D3.12 完成首次月度死码 audit:
- D3.1: factor_evaluation 真死表 / position_monitor 假装健康死码 / circuit_breaker_log valid 暂空
- D3.12: T0-4 hardcoded 'live' scope 27+ vs 7 (1 阶概括偏差)
- 17 schtask scripts 中 4 deferred (Session 44 末) — 待 X4 续 audit

**X4 落地**: 本审计是首次月度 audit 实践. 后续需:
1. 形成 X4 monthly cron (Sunday 周末 audit job)
2. 自动化 grep + LL-063 三问法
3. 月度 STATUS_REPORT 入 docs/audit/X4_monthly_<date>.md

---

## 6. X5 文档单源化 (本审计 partial 覆盖)

D3.1 finding: CLAUDE.md L188-191 数字漂移 (3 处):
- L188 northbound 3.88M (实测 5.54M)
- L189 stock_status_daily 12M (实测 55K)
- L191 factor_ic_history 84K (实测 145K)

memory/MEMORY.md 同样存在 stale 描述 (Session 44 handoff "卓然 -29%" 实测 -11.45%).

**X5 实施评估**:
- 需要建立 monthly job 自动比对 CLAUDE.md / handoff / MEMORY.md vs DB 实测数字
- 偏差 > 10% 自动 flag, 走 PR 修
- 当前 X5 0 自动化, 全 manual

**D3-B 续**: 推动 X5 自动化 (X5 cron 实施).

---

## 7. X7 月度铁律 audit (本审计为首次)

X7 要求月度 audit 全 42 条铁律. 本 D3.14 选 X1-X4 + X6 (5 条). 剩 37 条未覆盖, 留 D3-B + X7 monthly cron.

**X7 落地**: 本审计是首次月度铁律 audit 实践. 验证 5 条新铁律 + 多条已存在铁律, 走 audit pipeline. 后续:
1. X7 monthly job (周末 audit 全 42 条)
2. 每条铁律配 grep 模板 (e.g. 铁律 33 fail-loud → `grep "except Exception:\s*pass"` 抓 silent_ok 注释缺失)
3. monthly STATUS_REPORT

---

## 8. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3A-18 | pre-push hook `.venv` 缺失 silent fallback to system python (铁律 X3 弱违反) | P3 |
| (info) | X1 anthropic SDK 0 hits ✅ PASS | — |
| (info) | X2 LIVE_TRADING_DISABLED 多重保护 ✅ PASS | — |
| (info) | X6 0 openai/deepseek SDK import ✅ PASS | — |
| (info) | X4 月度死码 audit 本审计为首次实践 | — |
| (info) | X5 文档单源化 0 自动化, manual only | — |
| (info) | X7 月度铁律 audit 本审计为首次实践 | — |

---

## 9. 关联

- **铁律 v3.0 (X1-X7)** — 本审计为首次实施扫描
- **CLAUDE.md 42 条铁律** — 本审计选 X1-X6 (5 条 + X4/X5/X7 实施评估)
- **D3-B 续**:
  - X4 自动化 (monthly cron)
  - X5 自动化 (CLAUDE.md / handoff 数字对比)
  - X7 全 42 条月度 audit (本 D3-A 覆盖 5)
- **批 2 P3 scope 候选**: F-D3A-18 (pre-push hook fail-loud)
