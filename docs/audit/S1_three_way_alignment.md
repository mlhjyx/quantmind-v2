# S1 审计报告 — 三角对齐（文档 / 代码 / DB）

> **范围**: 静态只读审计。对比 CLAUDE.md / SYSTEM_STATUS.md / 设计文档 声称的系统状态 vs 实际 `backend/**/*.py` / DDL / 数据库。
> **方法**: grep + 文件 Read + psycopg2 查询 + git ls-files。全程无副作用（只读）。
> **时间**: 2026-04-15 夜
> **覆盖铁律**: 11 / 13 / 14 / 17 / 22 / 25-28 / 29（部分）；**未覆盖**: 1 / 2 / 3 / 4 / 5 / 6 / 7 / 8 / 9 / 10 / 12 / 15 / 16 / 18 / 19 / 20 / 21 / 23 / 24 / 30（留给 S2-S5）

---

## 📋 执行摘要

| 分级 | 数量 |
|---|---|
| 🔴 P0 | **6** |
| 🟠 P1 | **10** |
| 🟡 P2 | **6** |
| **合计** | **22** |

**最严重的 3 条**（按对业务/合规的冲击排序）：

1. **F32 – 真实 API Token 泄漏到 git** 🔥 — Tushare token / DeepSeek API key / 钉钉 webhook 全部在 `backend/.env.example` 和 `docs/QUANTMIND_HERMES_DEPLOYMENT.md` 里。git 历史也已污染。
2. **F16/F17/F31 – 核心铁律被大量违反** — Service 层 20+ 处 `.commit()`；Engine 层在写 DB；factor_onboarding/factor_engine 绕过 DataPipeline 直接 INSERT。这些正是铁律 17/22 要防的技术债回潮。
3. **F41 – 已 INVALIDATED 的因子仍在生产代码的 config 里** — `V12_CONFIG` 含 `mf_momentum_divergence`，注释还写 "IC=9.1%"（铁律 11 明确其 IC=-2.27%，应删除），说明死代码清理不彻底。

---

## 🔴 P0 发现（Critical — 影响安全 / 铁律 / 正确性）

### F32 – 真实 API Token 提交到 git 🚨 SECRET LEAK（已清理）

**状态**: 2026-04-15 已清理。用户手动 rotate 了所有 token，我批量脱敏了 5 处源码位置。

**位置**（共 5 个真实泄漏点 + 1 个我自己写审计时引入）:
- `backend/.env.example` (git tracked) — TUSHARE + DEEPSEEK 真 key
- `docs/QUANTMIND_HERMES_DEPLOYMENT.md:169` — DEEPSEEK 另一真 key
- `docs/QUANTMIND_HERMES_DEPLOYMENT.md:170` — **ZHIPU_API_KEY 真 key**（初扫漏掉, 第二轮 grep 发现）
- `scripts/research/phase3b_data_fetch.py:47` — 硬编码 Python 字符串 Tushare token
- `scripts/archive/test_forecast_factors.py:89` — 硬编码 Python 字符串 Tushare token
- `docs/audit/S1_three_way_alignment.md`（此报告）— 我引证时也写了真 key, 已脱敏为 `<redacted>`
- `docs/DEV_BACKEND.md:834-852`（此处是占位符 `sk-xxx`, 未泄漏, 仅作对照）

**Rotate 状态**:
| Token | 初报告范围 | 实际需要 rotate | 状态 |
|---|---|---|---|
| TUSHARE_TOKEN | ✓ | ✓ | ✅ Done |
| DEEPSEEK_API_KEY (#1) | ✓ | ✓ | ✅ Done |
| DEEPSEEK_API_KEY (#2) | ✓ | ✓ | ✅ Done |
| DINGTALK webhook | ✓ | ✓ | ✅ Done |
| **ZHIPU_API_KEY** | ❌ 初报告漏 | ✓ | ⚠️ **需用户补做 rotate**（见 https://open.bigmodel.cn/usercenter/apikeys）|

**证据**（已脱敏 — 真 token 已于 2026-04-15 全部 rotate 并从源码清除）:
```
backend/.env.example:
  TUSHARE_TOKEN=<redacted — Tushare Pro 真 API token>
  DEEPSEEK_API_KEY=<redacted — DeepSeek 真 API key>

docs/QUANTMIND_HERMES_DEPLOYMENT.md:169-170:
  DEEPSEEK_API_KEY=<redacted — 第二个 DeepSeek 真 key (与 .env.example 中不同)>
  ZHIPU_API_KEY=<redacted — 智谱 GLM-5 真 API key>

scripts/research/phase3b_data_fetch.py:47:
  TUSHARE_TOKEN = "<redacted — 硬编码 Python 字符串, 与 .env.example 同一个 key>"

scripts/archive/test_forecast_factors.py:89:
  ts.pro_api("<redacted — 同一个 Tushare token 硬编码>")

backend/.env (not tracked, 仅本地):
  原始包含真 token, 已由用户 rotate 替换为新值
```

**注意**: `backend/.env` 原始 `DINGTALK_WEBHOOK_URL` 含真 `access_token=<redacted>`（个人机器人 webhook），已随 rotate 更换。

**根因**:
1. 开发者把 `.env` 直接 copy 成 `.env.example` 而不是手工脱敏
2. `.gitignore` 只屏蔽 `.env`，不屏蔽 `.env.example`
3. 文档里写部署实例时也贴了真 key

**影响**:
- **Tushare quota 可被他人消耗**（对 PT 首日拉取影响最大）
- **DeepSeek 余额可被他人烧**
- **钉钉机器人**可被他人冒名推送消息到你的群
- 即使现在删文件，**git 历史已污染**

**建议**:
1. **立即** rotate 三套 token（Tushare / DeepSeek / 钉钉）— **用户必须手动执行**
2. `.env.example` 改占位：
   ```
   TUSHARE_TOKEN=your_tushare_token_here
   DEEPSEEK_API_KEY=sk-xxx
   ```
3. `docs/QUANTMIND_HERMES_DEPLOYMENT.md` 清洗所有真 key，统一 `sk-xxx` 占位
4. `pyproject.toml` 或 `.pre-commit-config.yaml` 加 `detect-secrets` hook（长期防御）
5. 可选：`git filter-repo --replace-text` 清洗 git 历史（破坏性高，评估后再做）

**工作量**: 用户 rotate token ≈ 15 min；文档/代码清洗 ≈ 30 min；git 历史清洗 ≈ 60 min + 风险评估。

---

### F16 – Service 层 20+ 处 `.commit()` 违反铁律

**铁律原文**（CLAUDE.md 编码规则）: *"sync psycopg2, Service内部不commit, 调用方管理事务"*

**位置**（grep `\.commit\(\)` 在 `backend/app/services/`）:

| 文件 | 行号 | 类型 |
|---|---|---|
| `risk_control_service.py` | 1196, 1376, 1554, 1615 | sync psycopg2 |
| `pt_data_service.py` | 235, 309 | sync psycopg2 |
| `pt_monitor_service.py` | 88 | sync psycopg2 |
| `pt_qmt_state.py` | 120 | sync psycopg2 |
| `shadow_portfolio.py` | 43, 183 | sync psycopg2 |
| `notification_service.py` | 575, 670 | sync psycopg2 |
| `mining_service.py` | 115, 146, 338 | **async SQLAlchemy** |
| `backtest_service.py` | 84, 102, 116, 317 | **async SQLAlchemy** |

**根因**: 铁律没有被代码强制执行，开发过程中为了"简单"在 Service 内部直接提交，逐步累积。

**影响**:
- 事务边界不明确，无法从 Router 层统一做 rollback-on-error
- 多个 Service 相互调用时一个 commit 把另一个的 partial 状态也提交
- 违反依赖倒置（Router 应该拥有事务，Service 不应该）

**建议**:
1. **规模大，修复不在 S1 范围**。先记录清单，S3 韧性 session 做一次系统修复
2. 临时措施：`.pre-commit-config.yaml` 加 grep hook 阻断 `.commit()` 出现在 `services/*.py` 的新增代码（不阻断现有）
3. 长期：Router 层引入 `@transactional` 装饰器，Service 只 `flush` 不 `commit`

**工作量**: 全项目系统修复 ≈ 2-3 天（20+ 处改动 + 测试）。加 hook ≈ 15 min。

---

### F17 – 直接 INSERT 绕过 DataPipeline（违反铁律 17）

**铁律原文**: *"17. 数据入库必须通过 DataPipeline — 禁止直接 INSERT INTO 生产表"*

**真实违规**（grep `INSERT INTO factor_values|klines_daily|daily_basic|minute_bars|moneyflow_daily|factor_ic_history`）:

| 文件 | 行号 | 严重度 |
|---|---|---|
| **`backend/app/services/factor_onboarding.py`** | 538 | 🔥 P0 — 名字叫 onboarding pipeline 但自己绕过 DataPipeline |
| **`backend/engines/factor_engine.py`** | 2001 | 🔥 P0 — 额外违反"Engine 无 IO"（见 F31） |
| `backend/app/data_fetcher/fetch_base_data.py` | — | P1 — 数据拉取侧绕过 |
| `backend/scripts/compute_factor_ic.py` | — | P1 — 计算后写 IC 绕过 |
| `scripts/research/phase3a_*.py` (4 files) | — | P2 — 研究脚本可接受但不优雅 |
| `scripts/research/phase3b_factor_characteristics.py` | — | P2 |
| `scripts/research/phase3e_minute_factors.py` | — | P2 — **2026-04-15 今天才写** |
| `scripts/research/phase12_*.py` (2 files) | — | P2 |
| `scripts/archive/**` (4 files) | — | — 无生产引用可忽略 |
| `scripts/fast_ic_recompute.py` | — | P1 |
| `backend/tests/test_e2e_full_chain.py` | — | P3 — 测试可接受 |

**合规**:
- `backend/app/data_fetcher/pipeline.py:243` `sql = f"INSERT INTO {contract.table_name} ..."` — **这是 DataPipeline 本身**，合规。

**细节证据**:
```python
# factor_onboarding.py:536-546 (asyncpg 走的)
await conn.executemany(
    """
    INSERT INTO factor_values
        (factor_name, code, trade_date, raw_value, neutral_value)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (factor_name, code, trade_date) DO UPDATE ...
    """,
    batch,
)

# factor_engine.py:1998-2011 (sync psycopg2 走的)
execute_values(
    cur,
    """INSERT INTO factor_values
       (code, trade_date, factor_name, raw_value, neutral_value, zscore)
       VALUES %s ON CONFLICT ...""",
    day_rows,
    page_size=5000,
)
conn.commit()  # ← 同时触发 F16
```

**根因**: 铁律 17 是 Step 6-B（2026-04-09）引入的，但**前向修复**没做 — 早于 Step 6-B 的代码仍在直接 INSERT，新增研究脚本继续沿袭旧模式。

**建议**:
1. **P0 生产路径必须修复**: `factor_onboarding.py` / `factor_engine.py` / `fetch_base_data.py` 改为 `DataPipeline.ingest(df, Contract)`
2. **研究脚本**：建议加 `scripts/research/README.md` 说明"研究脚本可以短路，但不能写 factor_values；如果必须持久化要走 DataPipeline"
3. **Lint 增强**: `.pre-commit-config.yaml` 加 grep 规则：生产代码（`backend/**/*.py`）禁止 `INSERT INTO factor_values`，例外 `data_fetcher/pipeline.py`

**工作量**: 生产路径修复 ≈ 1 天；lint 加固 ≈ 1 小时。

---

### F31 – Engine 层读写 DB（违反"Engine = 纯计算无 IO"）

**铁律原文**（CLAUDE.md §架构分层）: *"Engine层 = 纯计算(无IO无DB), 输入/输出DataFrame/dict"*

**位置**: `backend/engines/factor_engine.py`

**证据**:
```python
# factor_engine.py:1975 加载 fundamental data — load from conn
fund_data = load_fundamental_pit_data(td_date, conn)

# factor_engine.py:1998-2011 写入 factor_values — execute_values
with conn.cursor() as cur:
    execute_values(cur, "INSERT INTO factor_values ...", day_rows)
    conn.commit()
```

同时该文件 **2034 行**，包含：
- 因子计算函数（正确的 Engine 职责）
- PIT 数据加载（应在 Service / Data 层）
- 批量 orchestration（应在 Task / Service 层）
- DB 写入（应在 Service / Pipeline 层）
- 事务 commit（违反 F16）

**根因**: 历史上 Engine 和 Service 边界没有早期确立。Step 6-H 之后虽然有分层意识，但 `factor_engine.py` 2k 行巨石未被拆分。

**影响**:
- 测试困难（无法纯 DataFrame 输入输出测试因子计算）
- 职责不清 — 新因子开发者不知道该 extend 还是 wrap
- 违反 F16 和 F17 双重铁律

**建议**（中期）:
```
backend/engines/factor/           # 纯计算
├── turnover_factors.py
├── volatility_factors.py
├── ...
└── preprocess_pipeline.py       # MAD → fill → WLS → zscore

backend/app/services/factor_calculation_service.py  # orchestration + DB IO
```

**工作量**: 重构 ≈ 3-5 天 + 测试迁移。短期可先标记 TODO 不动。

---

### F41 – 已 INVALIDATED 因子仍在生产 config

**位置**: `backend/engines/signal_engine.py:113-132`

**证据**:
```python
# v1.2候选配置: 6因子 = 基线5 + mf_momentum_divergence (资金流维度)
# 不替换v1.1(PAPER_TRADING_CONFIG)，v1.1继续Paper Trading跑
# mf_momentum_divergence IC=9.1%，与基线5因子正交（资金流-价格背离维度）
V12_CONFIG = SignalConfig(
    factor_names=[
        # 基线5因子（与PAPER_TRADING_CONFIG一致）
        "turnover_mean_20",
        "volatility_20",
        "reversal_20",    # ← 已从 Active 移除
        "amihud_20",      # ← 已从 Active 移除
        "bp_ratio",
        # v1.2新增: 资金流维度
        "mf_momentum_divergence",  # ← 已 INVALIDATED (IC=-2.27%)
    ],
    top_n=15,
    ...
)
```

**CLAUDE.md 的反证**（失败方向表）:
> *mf_divergence独立策略 | IC=-2.27%(非9.1%), 14组回测全负 | GA2证伪*
> *`| INVALIDATED | 1 | mf_divergence (IC=-2.27%, 非9.1%, v3.4证伪)`*

**影响**:
- 有人 `from signal_engine import V12_CONFIG` 就会拿到**基于虚假 IC 数据的配置**
- 注释写 "IC=9.1%" 本身就是 stale doc，违反铁律 22
- `V12_CONFIG` 不在 PT 使用链路上（PT 用 `PAPER_TRADING_CONFIG`），但**grep 它谁在用** 是 S2 的任务

**建议**:
1. 删除整个 `V12_CONFIG` block（如果没被引用）
2. 如果被某个研究脚本引用，研究脚本跟着删 / 迁移到新 config

**工作量**: 删除 ≈ 15 min；grep 引用 ≈ 5 min；若有引用再评估。

---

### F45 – config_guard 对 SN 双写 P0 事故防御缺失

**位置**: `backend/engines/config_guard.py:67-122`

**证据**: `assert_baseline_config(factor_names, config_source)` 只对比 `factor_names` 集合：
```python
def assert_baseline_config(factor_names, config_source="unknown"):
    baseline = set(PAPER_TRADING_CONFIG.factor_names)
    current = set(factor_names)
    if baseline == current:
        return True
    # ... 只检查因子集差异
```

**缺失**:
- ❌ `size_neutral_beta` (P0 SN 双写: `.env PT_SIZE_NEUTRAL_BETA` ↔ `pt_live.yaml size_neutral_beta`)
- ❌ `top_n` (P0: `.env PT_TOP_N` ↔ `pt_live.yaml top_n` ↔ `SignalConfig.top_n` default)
- ❌ `industry_cap` (P0: 同上)
- ❌ `rebalance_freq` (`SignalConfig` default='biweekly' vs PT='monthly' vs yaml='monthly'）
- ❌ `turnover_cap`
- ❌ `commission_rate` / `stamp_tax` (关键成本参数，回测 vs PT 对齐风险)

**对照 CLAUDE.md 铁律 25-28**:
> *"不靠记忆靠代码" / "验证不可跳过不可敷衍" / "结论必须明确" / "发现即报告不选择性遗漏"*
> 以及明确提到 *"P0 SN 双写是典型隐患"*

**影响**: 如果 `.env` 与 `pt_live.yaml` 的 `size_neutral_beta` 被误改成不一致，config_guard 不会告警，PT 和回测会用不同值 → **回测 Sharpe vs 实盘 Sharpe 出现不可复现的偏差**（恰好是铁律 15 要防的事故）。

**建议**: S2 的时候**写**一个 `scripts/audit/config_drift_check.py`：
```python
def check_config_drift() -> list[dict]:
    env = load_dotenv("backend/.env")
    yaml = load_yaml("configs/pt_live.yaml")
    py = SignalConfig()  # default values

    pairs = [
        ("top_n", env["PT_TOP_N"], yaml["strategy"]["top_n"]),
        ("industry_cap", env["PT_INDUSTRY_CAP"], yaml["strategy"]["industry_cap"]),
        ("size_neutral_beta", env["PT_SIZE_NEUTRAL_BETA"], yaml["strategy"]["size_neutral_beta"]),
        # ...
    ]
    drifts = [p for p in pairs if p[1] != p[2]]
    return drifts
```
且 `assert_baseline_config` 扩展签名：`assert_baseline_config(factor_names, top_n, industry_cap, size_neutral_beta, rebalance_freq, config_source)`。

**工作量**: 扩展 `config_guard` + 编写 drift check ≈ 3 小时；S2/S6 合并做。

---

## 🟠 P1 发现（严重文档漂移 / 技术债）

### F14 – DDL / 动态 / DB 三方表数全错

| 层 | CLAUDE.md 声称 | 实际 |
|---|---|---|
| DDL (`QUANTMIND_V2_DDL_FINAL.sql`) | **45 张** | **47 张** (`grep -c "CREATE TABLE"`) |
| 代码动态建表 | **17 张** | **26 张** |
| DB 实际 (`pg_tables`) | **62 张** | **73 张** |

**26 个"DB 中有但 DDL 无"的动态建表清单**（这本身违反"DDL 是唯一建表源"）:
```
balance_sheet, bs_balance_data, bs_cash_flow_data, bs_dupont_data,
bs_growth_data, bs_operation_data, cash_flow, circuit_breaker_log,
circuit_breaker_state, earnings_announcements, execution_audit_log,
express, factor_health_log, factor_lifecycle, factor_profile,
fina_indicator, forecast, holder_number, intraday_monitor_log,
margin_detail, modifier_signals, operation_audit_log, position_monitor,
shadow_portfolio, sw_industry_mapping, top_list
```

其中关键业务表（CLAUDE.md 反复引用但 DDL 不存在）:
- `position_monitor` — PMS 触发记录表（CLAUDE.md §PMS 规则明确写入）
- `shadow_portfolio` — LightGBM 影子选股表
- `circuit_breaker_state` — L1-L4 熔断状态机
- `factor_profile` / `factor_lifecycle` — 因子生命周期
- `sw_industry_mapping` — SW 一级行业映射（Phase 1.2 迁移用）

**建议**: S2/S5 做一次**正向迁移**：把这 26 张动态表的 schema **反向**写入 DDL 文件，恢复"DDL = 唯一真相源"。

**工作量**: 每张表 ≈ 15 min（读代码中的 `CREATE TABLE IF NOT EXISTS` 或 ORM 定义），共 ≈ 1 天。

---

### F40 – `signal_engine.py` 含三个相互不一致的 SignalConfig

**位置**: `backend/engines/signal_engine.py`

| Config | 定义位置 | `top_n` | `rebalance_freq` | `industry_cap` | 因子 | 问题 |
|---|---|---|---|---|---|---|
| `SignalConfig` (dataclass default) | line 56-84 | 20 | `'biweekly'` | 0.25 | 8（含 `ln_market_cap` / `ep_ratio` / `ln_market_cap` / `turnover_std_20` 等 deprecated） | Default 值过期 |
| `PAPER_TRADING_CONFIG` | line 89-110 | `settings.PT_TOP_N` | `'monthly'` | `settings.PT_INDUSTRY_CAP` | CORE3+dv_ttm (4) | ✅ 正确 |
| `V12_CONFIG` | line 116-132 | 15 | `'monthly'` | 0.25 | 5 + **INVALIDATED mf_momentum_divergence** | F41（P0） |

**影响**:
- 任何代码写 `SignalConfig()` 不加参数 → 拿到 **8 因子 biweekly 25% 行业上限**的错误配置
- 即使 `config_guard` 检查因子集，也无法发现 `top_n/rebalance_freq` 默认值的漂移

**建议**:
1. `SignalConfig` 的 dataclass default 改成**报错**：
   ```python
   factor_names: list[str] = field(default_factory=list)  # 空列表
   def __post_init__(self):
       if not self.factor_names:
           raise ValueError("factor_names required; use PAPER_TRADING_CONFIG or build via _build_paper_trading_config()")
   ```
2. 删除 `V12_CONFIG`
3. `SignalConfig.top_n/industry_cap/rebalance_freq` 的 default 也改成 `None` + `__post_init__` 检查

**工作量**: 修 + 跑测试 ≈ 2 小时。

---

### F18 – sync / async 技术栈混用（CLAUDE.md 只承认 sync）

**CLAUDE.md 声称**: *"后端 | FastAPI + **sync psycopg2** + Celery + Redis"*

**实际**:
- **sync psycopg2**: `risk_control_service`, `pt_*`, `notification_service`, `shadow_portfolio`, 大部分 services/
- **async SQLAlchemy + asyncpg**: `mining_service.py`, `backtest_service.py`, `factor_onboarding.py` (asyncpg conn)
- `backend/app/config.py:22` DATABASE_URL 默认值用 `postgresql+asyncpg://` (asyncpg driver)
- `backend/app/services/db.py:18-23` 运行时把 asyncpg URL 转成 psycopg2 URL（桥接层）

**影响**:
- 两个并存风格，新人不知道该用哪个
- `factor_onboarding.py` 用 asyncpg connection 直接 INSERT（F17）
- 生态混用 → 测试 fixture / mock 策略也不一致

**建议**:
1. **文档跟代码对齐**：CLAUDE.md 改为 "sync psycopg2 为主，遗留 async SQLAlchemy 在 `mining_service` / `backtest_service`，计划收敛"
2. **中期**：把 `mining_service` / `backtest_service` 改写成 sync psycopg2，或彻底迁到 async（二选一，不再并存）
3. `factor_onboarding` 里的 asyncpg connection 要么走 DataPipeline（同步），要么明确 async 路径

**工作量**: 文档修 ≈ 30 min；代码收敛 ≈ 1 周。

---

### F43 – `factor_engine.py` 2034 行巨石文件

**位置**: `backend/engines/factor_engine.py` (2034 lines)

| 对比 | 行数 |
|---|---|
| `factor_engine.py` | **2034** |
| `config_guard.py` | 324 |
| `signal_engine.py` | 455 |
| `SYSTEM_STATUS.md` | 835 |
| `CLAUDE.md` | 593 |

**职责混杂**（见 F31）。

**建议**: 见 F31（中期拆分）。短期：文件顶部加 TODO 标记 + 禁止新增代码。

---

### F44 – `parquet_cache.py:65-68` raw_value 列名歧义遗留

**位置**: `backend/data/parquet_cache.py:65-68`

**证据**（代码注释坦承）:
```python
# NOTE (Step 6-D, Fix 1): "raw_value" 列名是历史遗留 —
# 实际内容是 COALESCE(neutral_value, raw_value), 即 **WLS 中性化后的值**
# (中性化列 NULL 时才回退到真正的原始值)。run_hybrid_backtest() 在 runner.py
# 里靠 `df.rename(columns={"raw_value": "neutral_value"})` 兼容这一命名。
# 直接读 Parquet 的代码请参考 cache/backtest/SCHEMA.md 避免误解。
# 不改列名是为了保持 regression_test 基线 Parquet 的 hash 稳定。
```

**铁律 19 原文**: *"IC 定义全项目统一... raw_value 的 IC 只作参考对比, 不作入池/淘汰依据"*

**影响**:
- 任何直读 Parquet 的研究脚本如果 trust `raw_value` 字面名，会把**已中性化**的值当 raw 来分析
- 回归测试基线 Parquet hash 被锁死，无法重命名

**建议**:
1. **短期**: 在 Parquet 写入时加一列 `_neutral_value_actual`（冗余但安全）
2. **中期**: Step 6-D 的基线 Parquet 重新生成一次（成本：重跑 regression_test，能接受），列名改正
3. **长期**: `cache/backtest/SCHEMA.md` 写明字段真实含义（文档跟代码对齐）

**工作量**: 短期 ≈ 1 小时；中期 ≈ 半天（含重跑 regression）；长期文档 ≈ 30 min。

---

### F10 – CLAUDE.md 测试数同文件三处矛盾

**证据**（`grep -n "2076\|2115\|904" CLAUDE.md`）:
```
168:└── backend/tests/               # 2076+个测试（90个test文件）
484:- ✅ Phase A-F全部完成（185新测试, 904全量通过, 0回归）
557:📊 测试: 2115 tests / 98 test files (Step 5新增48测试)
```

**实际**: `find backend/tests -name "test_*.py" | wc -l` = **98** ✅ 只有 line 557 对。line 168 的 "90 个" 错了。

**真实测试数需要 S4 跑 pytest 才知道**。

**建议**: CLAUDE.md line 168 的 "2076+ 90 files" 统一到 "2115+ 98 files"（或 S4 跑完 pytest 用真实数）。

**工作量**: 1 行改 ≈ 1 min。

---

### F28 / F29 – 数据量数字严重过期

| 字段 | CLAUDE.md | 实际 `count(*)` | Delta |
|---|---|---|---|
| `factor_values` | ~590M 行 | **816,408,002** | +38% |
| `minute_bars` | 139M 行 | **190,885,634** | +37% |
| `klines_daily` | 未声称 | 11,721,768 | — |
| `daily_basic` | 未声称 | ~11.5M (estimate) | — |
| `factor_ic_history` | 未声称 | 133,125 | — |
| `trade_log` | 未声称 | 44 | — |
| `position_snapshot` | 未声称 | 116 | — |

**建议**: CLAUDE.md 更新数字。或者**更好的做法**：删掉数字，改为引用 `SYSTEM_STATUS.md` 的自动化体检（S6 产出 invariant script 可以每日刷新）。

---

### F1 – 文档索引漏列 DEV_FOREX / DEV_NOTIFICATIONS

**CLAUDE.md §目录结构** 只列 7 个 DEV_*.md：
- DEV_BACKEND / DEV_BACKTEST_ENGINE / DEV_FACTOR_MINING / DEV_FRONTEND_UI / DEV_SCHEDULER / DEV_PARAM_CONFIG / DEV_AI_EVOLUTION

**实际 `ls docs/DEV_*.md`**: 9 个（漏列 `DEV_FOREX.md` / `DEV_NOTIFICATIONS.md`）

**建议**: CLAUDE.md §目录结构 补两行（1 min）。

---

### F15 – `config.py:22` 硬编码默认数据库密码

**证据**:
```python
# backend/app/config.py:22
DATABASE_URL: str = "postgresql+asyncpg://xin:quantmind@localhost:5432/quantmind_v2"
```

- 用户名 `xin` / 密码 `quantmind` 明文写死
- 如果 `.env` 缺失或加载失败，默认值会被用来连接 → 就是 S1 调试期间发生的情况（psql 没 password 超时，切到 psycopg2 我用了 `password='quantmind'` 就通了）

**建议**: 默认值改为 `None` + `__post_init__` raise，强制必须提供 `.env`：
```python
DATABASE_URL: str = Field(..., description="required via .env")
```

**工作量**: 15 min + 测试所有启动路径。

---

### F34 / F35 – `execution_mode` 三义命名冲突

| 位置 | 含义 | 值 |
|---|---|---|
| `.env:EXECUTION_MODE` | 全局 PT 模式 | `paper` |
| `configs/pt_live.yaml:execution.mode` | 执行层模式 | `paper` |
| `position_snapshot.execution_mode` (DB col) | Position 记账口径 | `live`（PMS 修复后） |

**影响**: PMS Bug (2026-04-15) 的根因之一就是**同名不同义**。position_snapshot 的 `execution_mode='live'` 意思是"真实成交（非 dry-run）"，但容易被误解为"LIVE trading 模式"（对应 `.env` 的 `live` 值）。

**建议**:
1. DB 列改名：`position_snapshot.execution_mode` → `booking_mode`（paper_simulated / live_filled）
2. 或者保留名字，加详细注释 + 单元测试锁定含义

**工作量**: DB schema 迁移 ≈ 3 小时（含 ORM 更新）。

---

## 🟡 P2 发现（可清理 / 可优化）

### F2 – `scripts/archive/` 脚本数过期 (131 → 126)
CLAUDE.md 声称 "131 个归档脚本"，实际 `find -name "*.py" | wc -l` = **126**。5 个被清理但文档未更新。

### F13 – archive 无生产引用，可永久删除
`grep -r "from scripts.archive"` 返回空。`scripts/archive/` 可以**整个删除**或转到独立 branch / tag 保留。

### F19 / F20（作废）+ 学习点：pg_class.reltuples 对 hypertable 失效
`factor_values` 和 `klines_daily` 是 TimescaleDB hypertable，父表 `reltuples=0` 是正常的（数据在 chunks 里）。需要用 `hypertable_size()` 或 `timescaledb_information.hypertables`。**写入 S1 lessons**，S6 的 `invariant_check.py` 避坑。

### F8 – ORM 覆盖仅 17 / 47 DDL = 36%
ORM models 只覆盖 17 张表，其余 30 张表走 raw SQL text()。这是**设计选择**（与 CLAUDE.md "sync psycopg2" 一致），不是 bug，但**新开发者会困惑**。

**建议**: 文档说明："ORM 只用于复杂查询/关系；数据层统一 raw SQL text() + DataPipeline"。

### F5 – `docs/archive/` 堆积 5 个历史 ROADMAP 版本
`QUANTMIND_V2_FIX_UPGRADE_ROADMAP.md` / `ROADMAP_V2.md` / `ROADMAP_V3.md` / `ROADMAP_V3.2.md` / `ROADMAP_V3.3.md` / `ROADMAP_V3.4.md` / `ROADMAP_V3.5.md` 共 **7 个**历史版本堆在 `docs/archive/`，当前正在用 V3.8（在 `docs/` 根）。

**建议**: `docs/archive/roadmap-history/` 子目录归类，一行索引说明每版的里程碑。

### F38 – Stale comment 在生产代码
`signal_engine.py:118` 注释 "基线5因子（与PAPER_TRADING_CONFIG一致）" — PT 现在是 4 因子（CORE3+dv_ttm）。违反铁律 22。

---

## 📊 三方表对齐 Diff（ORM / DDL / DB）

### DDL 47 张 ∩ DB 73 张 = 47 张对齐

### DB 中有但 DDL 无的 26 张（"代码动态建表"）
见 F14。这 26 张表违反"DDL 是唯一真相源"。

### ORM 覆盖明细

**ORM 有的 17 张表**:
```
FactorRegistry      -> factor_registry
FactorValue         -> factor_values
FactorICHistory     -> factor_ic_history
PipelineRun         -> pipeline_runs
MiningKnowledge     -> mining_knowledge
Symbol              -> symbols
KlineDaily          -> klines_daily
DailyBasic          -> daily_basic
TradingCalendar     -> trading_calendar
IndexDaily          -> index_daily
TradeLog            -> trade_log
PositionSnapshot    -> position_snapshot
PerformanceSeries   -> performance_series
BacktestRun         -> backtest_run
BacktestTrade       -> backtest_trades
UniverseDaily       -> universe_daily
Signal              -> signals
GPApprovalQueue     -> gp_approval_queue
```

**DDL 有但 ORM 无的 30 张关键表**（节选）:
```
forex_bars, forex_events, forex_swap_rates  (Forex 外汇模块)
ai_parameters, experiments, model_registry  (AI 闭环)
notifications, notification_preferences     (通知)
health_checks, scheduler_task_log            (运维)
backtest_daily_nav, backtest_holdings, backtest_wf_windows (Backtest 子表)
factor_evaluation, factor_mining_task        (因子挖掘)
minute_bars                                  (分钟数据)
stock_status_daily                           (ST/停牌/新股状态)
moneyflow_daily, northbound_holdings, margin_data  (资金流)
chip_distribution, financial_indicators      (基本面)
index_components                             (指数成分)
agent_decision_log, approval_queue, param_change_log  (审计/治理)
strategy, strategy_configs                   (策略)
pipeline_run                                 (跟 pipeline_runs 两个表！)
```

**注意**: DDL 定义了 `pipeline_run`（L726）**和** `pipeline_runs`（L792）两个表名（s 和非 s 都存在）→ **F8a 潜在问题**：需要 S2 确认两表用途不冲突。

---

## ⚖ 铁律合规评分（S1 覆盖的部分）

| # | 铁律 | 状态 | 证据 |
|---|---|---|---|
| 11 | IC 必须有可追溯入库记录 | ✅ PASS | `factor_ic_history` 133,125 行 |
| 13 | 市场逻辑可解释性（G10）| ⚠️ 无代码断言 | 仅靠人工评审 |
| 14 | 回测引擎不做数据清洗 | ⚠️ 部分违反 | `parquet_cache.py` 在 SQL 里做 `COALESCE(neutral_value, raw_value)`（F44），勉强算数据清洗 |
| 17 | DataPipeline 唯一入库 | ❌ **FAIL** | F17 多处绕过 |
| 22 | 文档跟随代码 | ❌ **FAIL** | F14/F28/F29/F10/F1/F38/F41 大面积 stale doc |
| 25 | 不靠记忆靠代码 | N/A | 元规则 |
| 26 | 验证不可跳过 | N/A | 元规则 |
| 27 | 结论必须明确 | N/A | 元规则 |
| 28 | 发现即报告不遗漏 | N/A | 元规则 |
| 29 | 禁止 float NaN 入 DB | ✅ PASS | Active 4 因子 94K NaN 全是 SQL NULL |

**S1 未覆盖铁律**（留给 S2-S5）: 1 2 3 4 5 6 7 8 9 10 12 15 16 18 19 20 21 23 24 30

---

## 📎 附录 A：真实数据体量 snapshot (2026-04-15)

```
factor_values      816,408,002 行  155 GB (TimescaleDB hypertable, 151 chunks)
minute_bars        190,885,634 行   21 GB
klines_daily        11,721,768 行  4 GB (TimescaleDB hypertable, 51 chunks)
daily_basic         11,507,171 行  3 GB
factor_ic_history      133,125 行  18 MB
factor_profile              53 行
factor_registry              5 行
position_snapshot          116 行 (PMS 修复后)
trade_log                   44 行 (PT 清仓后)
```

**Active 4 因子 factor_values 覆盖**（每个因子）:
```
turnover_mean_20  11,711,423 行 (neutral NaN: 94,105 = 0.80%)
volatility_20     11,711,423 行 (neutral NaN: 94,048 = 0.80%)
bp_ratio          11,711,423 行 (neutral NaN: 94,624 = 0.81%)
dv_ttm            11,711,423 行 (neutral NaN: 94,624 = 0.81%)
```
一致性 ✅（NaN 率接近说明同一批股票因数据缺失被标记）。

---

## 📎 附录 B：S1 未覆盖项（转 S2-S5）

1. **铁律 16 (信号路径唯一)** — S2 做：grep 是否有独立简化信号生成
2. **铁律 19 (IC 口径统一)** — S2 做：grep `spearmanr|rank_ic|factor_ic` 看是否都走 `ic_calculator`
3. **铁律 22 (文档跟代码)** 全量扫描 — S5 做：逐一核查 DEV_*.md 的实现率
4. **铁律 15 (回测可复现)** — S4 做：跑 regression_test
5. **铁律 30 (中性化后重建缓存)** — S2 做：查 Parquet mtime vs factor_values mtime
6. **前端 ↔ 后端契约** — S2 做：35 页面的 api 调用 vs FastAPI 路由
7. **静默失败巡查** — S3 做：grep `except.*pass|except.*return None`
8. **并发安全** — S3 做：审 Celery worker pool + PG 连接池

---

## 📌 S1 下一步（P0 优先）

**用户必须手动处理** 🔥:
- [ ] F32: Rotate Tushare / DeepSeek / 钉钉 token
- [ ] F32: `.env.example` 改占位符
- [ ] F32: `docs/QUANTMIND_HERMES_DEPLOYMENT.md` 清洗真 key

**代码修复（S1 范围外，登记到 Todo）**:
- [ ] F41: 删除 `V12_CONFIG`（最快修，15 min）
- [ ] F38: stale comment 清理（5 min）
- [ ] F1: CLAUDE.md 索引补 DEV_FOREX / DEV_NOTIFICATIONS（2 min）
- [ ] F14: CLAUDE.md 表数 45/17/62 → 47/26/73（2 min）
- [ ] F28/F29: CLAUDE.md 数据量 590M/139M → 816M/191M（2 min）
- [ ] F10: CLAUDE.md 测试数统一到 98 files（1 min）

**S2/S3/S5 纳入清单**:
- [ ] F16: Service 20+ commit 清理（S3）
- [ ] F17: 生产路径 3 文件迁到 DataPipeline（S2）
- [ ] F31: factor_engine.py 拆分（长期）
- [ ] F40: SignalConfig 三配置收敛（S2）
- [ ] F43: factor_engine.py 2034 行拆分（长期）
- [ ] F44: parquet_cache raw_value 列名修复（S2）
- [ ] F45: config_guard 扩展检查字段（S6 配合 config_drift_check.py）
- [ ] F14: 26 张动态表反向写入 DDL（S5）
- [ ] F18: async/sync 技术栈收敛（长期）
- [ ] F34/F35: execution_mode 命名冲突（S5）

---

**报告结束**。S1 完成度：**约 70%**（核心发现已定稿，铁律 16/19/22 的代码证据收集留给 S2）。

下一 Session: **S2 一致性专项**（PT ↔ 回测 ↔ 研究 → 前端 ↔ 后端）。
