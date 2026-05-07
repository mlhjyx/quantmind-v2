---
id: ADR-011
title: QMT/xtquant API 利用规划 + F19 根因定案
status: Accepted
date: 2026-04-21
owners: Session 21 加时 Part 3
related: ADR-008 (execution_mode namespace), ADR-010 (PMS→Risk Framework), QPB v1.6
---

# ADR-011: QMT/xtquant API 利用规划 + F19 根因定案

## 1. 背景

**F19 调查演化路径 (Session 20 → Session 21 加时 Part 3)**:
- Session 20 17:35 pt_audit: `db_drift expected=24 vs snapshot=19` (5 phantom 码)
- Session 21 加时 Part 1: F19 "phantom DELETE" 撤销, 留 4 候选根因
- Session 21 加时 Part 3 (本 ADR): 完全定案 = **QMT 部分成交回调聚合 bug**

过程中发现 QMT/xtquant SDK **无历史成交查询 API** (`xttrader.query_stock_trades` 仅当日), 但 `qmt-data-stderr.log` 记录全部 callback 原始流水, 足以替代. 顺势全面盘点 QMT API 可用范围 → 本 ADR.

## 2. F19 根因 (最终定案)

### 2.1 证据链

`scripts/diag/f19_fill_reconciler.py` 对比 `qmt-data-stderr.log` vs `trade_log` (4-17 live mode):

```
QMT orders: 25 | DB rows: 20
Total volume loss (QMT > DB): 9663 股
Codes with discrepancy: 6 / 23
  [DB_LEAKS_QMT] 002441.SZ  QMT= 4800 (2 fills) DB= 1200 (1 rows) diff=+3600
  [DB_LEAKS_QMT] 300833.SZ  QMT= 1400 (2 fills) DB=  500 (1 rows) diff=+900
  [DB_LEAKS_QMT] 688121.SH  QMT= 4500 (3 fills) DB=   33 (1 rows) diff=+4467  ← buy
  [DB_LEAKS_QMT] 688739.SH  QMT= 1900 (3 fills) DB= 1329 (1 rows) diff=+571
  [DB_LEAKS_QMT] 920212.BJ  QMT=   60 (1 fills) DB=    0 (0 rows) diff=+60
  [DB_LEAKS_QMT] 920950.BJ  QMT=   65 (1 fills) DB=    0 (0 rows) diff=+65
```

**关键**: 丢失跨 buy (688121 +4467) 和 sell (其他 5 码), 证明 bug 是**全方向**聚合问题, 非 sell-only.

完整 JSON: `docs/audit/f19_reconciliation_2026-04-17.json`

### 2.2 根因代码

`backend/engines/qmt_execution_adapter.py:70`:

```python
QMT_STATUS: dict[int, tuple[str, str]] = {
    48: ("pending", "未报"),
    49: ("pending", "待报"),
    50: ("pending", "已报"),
    51: ("pending", "已报待撤"),
    52: ("pending", "部成待撤"),
    53: ("final", "部撤"),
    54: ("final", "已撤"),
    55: ("final", "部成"),   # ❌ BUG: 应为 pending
    56: ("final", "已成"),
    57: ("final", "废单"),
}
```

**QMT 官方文档** (`dict.thinktrader.net/nativeApi/xttrader.html` 经 Session 21 加时 Part 3 WebFetch 确认):

> 48 未报 | 49 待报 | 50 已报 | 51 已报待撤 | 52 部分成交待撤 | 53 部分撤 | 54 已撤 | **55 部分成交** (仍可继续成交) | 56 已成 | 57 废单 | 255 未知

**55 是 pending 状态** (部分成交中, 订单仍 active 可继续成交), 错误标记为 final 导致 `is_final_status(55)=True` → event 提前触发.

### 2.3 Bug 流程

1. 下单 order_id=1090520685 sell 4800 股 002441.SZ
2. QMT 回调 `on_trade`: traded_volume=1200 @ 10.15 → `filled_volume += 1200 = 1200`
3. QMT 回调 `on_order`: status=**55** (部成) → `is_final_status(55) = True` **(错)** → `event.set()`
4. `execute_single_order`: `event.wait()` 返回, 读 `filled_volume=1200` → 构建 `Fill(shares=1200)`
5. 写 trade_log 1 行 quantity=1200
6. QMT 继续发后续: `on_trade` volume=3600 @ 10.14 → `tracker.filled_volume += 3600 = 4800` — 但 tracker 已 done, 不再被读, **丢 3600 股**
7. QMT 最终 `on_order`: status=56 (全成) → 再次 `event.set()` (但 event 已 set, 无效果)

### 2.4 修复方案 (Session 22+ PR)

**最小修复 (1 字节)**: L70 `"final"` → `"pending"`
```python
55: ("pending", "部成"),  # 部分成交仍 active, 等 56/53/54
```

**但需同步保证**:
- `_FillCollector.on_trade` L290: `if tracker.filled_volume >= tracker.volume: event.set()` — 已有, 处理"填满后即终止"
- `timeout` 足够长以等 56/53: 查 `execute_single_order` 默认 timeout (需 ≥ T+20~30 秒安全)
- 回归测试: mock QMT 推多个 55 trade callback + 最终 56, 断言 `filled_volume` 正确累加

**补录 4-17 缺失 trade_log** (9663 股丢失记录): 独立 script 从 reconciler JSON 自动生成 INSERT SQL.

### 2.5 跨 Session 影响

- F20 "trade_log 完整性" = F19 同源, **合并关闭**
- performance_series/daily_return 基于残缺 trade_log 计算, **NAV 可能偏差** (688121 少记 4467 × 10.88 ≈ 4.86 万买入) — Session 22+ 重算
- position_snapshot reconstruct 基于残缺 trade_log → `pt_audit db_drift` 误报的根源
- ADR-008 D2-c `restore_snapshot_20260417.py` 基于错 baseline 产出, 应重跑

## 3. QMT/xtquant API 全面盘点

### 3.1 双环境区分 (关键架构决策)

| 环境 | API 面 | QuantMind 现状 | 改造成本 |
|---|---|---|---|
| **外部 xtquant SDK** (pip 安装, `backend/engines/broker_qmt.py` import) | **仅当日** query + 全部下单/撤单/回调 | ✅ 已用 | 无需改 |
| **QMT client 内置 Python** (策略脚本 .py 加载进 QMT) | **历史** 查询 (`get_history_trade_detail_data`) + 算法下单 (`algo_passorder`) + 完整回调 | ❌ 未接入 | 中 (加策略脚本架构) |

**决策**: 以 xtquant SDK 为主干 (现状), 必要时 (如 F19 定案) 用 `qmt-data-stderr.log` 替代 SDK 不支持的历史查询. 内置 Python 环境作为**选项**, 仅当 ROI 明确时接入.

### 3.2 优先级矩阵

#### 🔴 立即可用 (高 ROI)

| # | API | 价值 | 落地 |
|---|---|---|---|
| A1 | **`get_history_trade_detail_data`** (内置 Python) | F19 最终验证工具 | **备案**: 现有 `qmt-data-stderr.log` 已足够, 不必引入内置 Python 环境 |
| A2 | **`get_value_by_order_id`** (内置 Python) | 按 order_id 反查成交明细 | **备案**: 同上 |
| A3 | **`qmt-data-stderr.log` 分析** (现有) | QMT 回调原始流水, 粒度更细 | ✅ 本 ADR 已用 (`f19_fill_reconciler.py`) |

#### 🟡 中期可用 (Wave 3 结合)

| # | API | 价值 | 落地时机 |
|---|---|---|---|
| B1 | **`subscribe_quote` + tick 订阅** | 实时 tick (替代 Baostock 5min) → 盘中风控即时性 | Wave 3 MVP 3.1 Risk Framework 实施时评估 |
| B2 | **`position_callback` / `account_callback`** (内置 Python) | 持仓变化 0 延迟推送 (vs 现 `qmt_data_service` 60s 轮询) | Wave 3 MVP 3.1 — "事件驱动 vs 轮询" 架构切换 |
| B3 | **`algo_passorder (VWAP/TWAP)`** | 20 笔同刻下单 → VWAP 拆单降冲击成本 10-30bps | PT live 稳定后 Session 25+ |
| B4 | **`orderError_callback`** | 下单失败即时告警 (补 dingtalk) | 下次 broker_qmt 重构时搭便车 |

#### 🟢 长期参考

| # | API | 用途 | 备注 |
|---|---|---|---|
| C1 | **`passorder` IPO/ETF 下单** | 新收益源 (IPO 打新 alpha 7-10%/年) | Forex 完成后评估 |
| C2 | **`query_credit_account`** | 融资融券 | 暂不做空 |
| C3 | **`export_data` / `query_data`** | 按日期导出对账 | 审计工具 |
| C4 | **`run_time`** | QMT 原生定时任务 | 不紧急 |

### 3.3 status 码权威表 (经 QMT 文档确认)

```
48 未报 (pending)
49 待报 (pending)
50 已报 (pending)
51 已报待撤 (pending)
52 部分成交待撤 (pending)
53 部分撤 (final)
54 已撤 (final)
55 部分成交 (pending, 非 final!)  ← Session 21 加时 Part 3 发现
56 已成 (final)
57 废单 (final)
255 未知 (final, error fallback)
```

**项目锚点**: 本 ADR 后, `qmt_execution_adapter.py:QMT_STATUS` 必须与此表对齐, 偏离即事故.

## 4. Session 22+ Action Items

### 4.1 F19/F20 收尾 (P0, Session 22)

1. **PR: QMT_STATUS[55] fix** (`qmt_execution_adapter.py:70` final → pending)
 - 附回归 test: mock 3 trade callback (1200 + 3600 + 0) + 最终 56 → 断言 `filled_volume=4800`
 - 关联: 铁律 40 baseline 不增 + smoke 29 PASS
2. **补录 4-17 缺失 trade_log 9663 股** (script 生成 9 行 INSERT, 手工 review 后 apply)
3. **重算 performance_series 4-17 ~ 4-21 NAV** (基于完整 trade_log)
4. **重跑 position_snapshot reconstruct** (基于完整 trade_log) → 验证 `pt_audit db_drift` 消除
5. 关闭 F19/F20, findings 25 → 23 (F18/F19/F20 撤或合)

### 4.2 QMT API 中期落地 (P1, Session 23+)

1. **B1/B2 实时 tick + callback**: Wave 3 MVP 3.1 Risk Framework 实施时评估"事件驱动"重构 (ADR-010 参考)
2. **B3 VWAP 拆单**: PT live 首月稳定后启动 (最早 Session 30+)

### 4.3 长期 (P2, 未明 session)

1. **C1 IPO 打新策略设计**: Forex 完成后评估
2. **内置 Python 环境接入**: 仅当需要 `get_history_trade_detail_data` / `algo_passorder` 时才引入 — 当前需求**不触发**

## 5. Consequences

### Positive

- F19/F20 双 finding 根因定案, 0 猜测
- 首次深度盘点 QMT API, 建 cross-session 架构视野
- `qmt-data-stderr.log` 作为 "QMT 原始流水" 数据源被确认 (未来类似分析直接用它)
- status 码 55=pending 的错误认知修正, 可能波及其他模块

### Negative / Risks

- **历史 4-17 → 4-21 每日 snapshot/nav 都可能有偏差** (需 Session 22 backfill 重算)
- Reviewer 确认 bug fix PR 前 (Session 22), PT 执行仍走有 bug 的代码 — 但 4-22 后 DailyExecute 仍 disabled, 影响面低
- 内置 Python 环境未接入 = 历史成交查询永远靠 log 分析 (可接受)

## 6. 相关文件

- `docs/audit/f19_reconciliation_2026-04-17.json` — 数据报告
- `docs/audit/F19_position_vanishing_root_cause.md` — Session 21 加时 Part 1 初版 (被本 ADR 覆盖)
- `scripts/diag/f19_fill_reconciler.py` — 复现工具
- `backend/engines/qmt_execution_adapter.py:70` — bug 源
- `logs/qmt-data-stderr.log` — 原始 QMT 回调流水 (93K 行, Session 20 起)

## 7. References

- QMT 开发文档: `https://dict.thinktrader.net/` (user 提供)
- xtquant SDK doc: `D:/quantmind-v2/.venv/Lib/site-packages/Lib/site-packages/xtquant/doc/xttrader.pdf`
- ADR-008 (execution_mode namespace) — 相关因为 trade_log 污染也是 ADR-008 讨论过的 execution_mode 问题的延伸
- LL-065 (AI summary 数字必须反向验证) — 本 ADR 演化过程也是 LL-065 的再次验证 (F19 原 "phantom DELETE" 判断数字来自 summary, 经逐层深挖才定因)
