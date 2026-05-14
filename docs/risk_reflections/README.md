# docs/risk_reflections/ — V3 §8 L5 RiskReflector 沉淀 dir

> **用途**: V3 §8.2 line 939-942 — RiskReflector V4-Pro 5 维反思 markdown report 沉淀.
> **写入方**: `backend/app/tasks/risk_reflector_tasks.py` Celery Beat 3 cadence (TB-4b sediment).
> **关联**: V3 §8 (L5 反思闭环层) / ADR-069 候选 (TB-4 closure) / Plan v0.2 §A TB-4 row.

## 目录结构 (V3 §8.2 line 939-942 1:1)

```
docs/risk_reflections/
├── README.md               # 本文件
├── YYYY_WW.md              # 周复盘 (Sunday 19:00 Beat — risk-reflector-weekly)
├── YYYY_MM.md              # 月复盘 (月 1 日 09:00 Beat — risk-reflector-monthly)
├── event/                  # 事件后反思 (event-triggered 24h post-event)
│   └── YYYY-MM-DD_<event_summary>.md
├── replay/                 # TB-1c replay 真测 reflection (历史沉淀, 非 Beat 写)
│   ├── 2024_replay_2024Q1_quant_crash.md
│   └── 2025_replay_2025_04_07_tariff_shock.md
└── disaster_drill/          # V3 §14.1 灾备演练 synthetic injection sediment (HC-2c, 非 Beat 写)
    └── YYYY-MM-DD.md        # 每 round: per-mode result + gap finding + enforcement matrix cross-ref
```

> **注**: `disaster_drill/` 沉淀 V3 §14.1 灾备演练 (失败模式 synthetic injection drill) —
> 跟 RiskReflector V4-Pro 反思 (§8, 上述 weekly/monthly/event/replay) 不同体系. drill
> = pytest synthetic injection (instant, 0 wall-clock wait, 反日历式观察期), 写入方 =
> 横切层 HC-2c sub-PR (非 Beat). 详 `backend/tests/test_v3_hc_2c_disaster_drill.py` +
> Plan v0.3 §A HC-2c + §D 真测期 SOP.

## Cadence (V3 §8.1 line 918-921)

| Beat entry | crontab (Asia/Shanghai) | 输出文件 | 用途 |
|---|---|---|---|
| `risk-reflector-weekly` | `0 19 * * 0` (Sunday 19:00) | `YYYY_WW.md` | 周复盘 |
| `risk-reflector-monthly` | `0 9 1 * *` (月 1 日 09:00) | `YYYY_MM.md` | 月复盘 |
| (event-triggered, 无 Beat) | L1 event dispatch 24h post-event | `event/YYYY-MM-DD_<summary>.md` | 重大事件后反思 |

事件触发条件 (V3 §8.1 line 921): 单日 portfolio < -5% / N 股同时跌停 / STAGED cancel 率异常.
event_reflection task 由 L1 event detection dispatch (TB-4c+ wire), 非 Beat schedule.

## 5 维反思框架 (V3 §8.1 line 927-933)

每份 report 含 5 维: Detection / Threshold / Action / Context / Strategy.
prompt template: `prompts/risk/reflector_v1.yaml` (TB-4a sediment).

## DingTalk push 摘要 (V3 §8.2 line 945-957)

每份 report 生成后 push DingTalk 摘要 (overall_summary + 5 维 candidates count),
完整 markdown 走本 dir 沉淀. push 走 `app.services.dingtalk_alert.send_with_dedup`
(双锁 + alert_dedup 去重, DINGTALK_ALERTS_ENABLED default-off).

## lesson→risk_memory 闭环 (留 TB-4c)

每份 report 的 overall_summary + 5 维 findings → V4-Flash 1024-dim embedding →
INSERT risk_memory (走 DataPipeline 铁律 17). 下次相似事件 RAG retrieval 命中.

## 参数候选 → user approve (留 TB-4d)

5 维 candidates (e.g. "RT_RAPID_DROP_5MIN 5% → 5.5%") → DingTalk push 含 approve
button → user reply approve → CC 自动 generate PR → user 显式 merge (sustained
ADR-022 反 silent .env mutation + 双层 redline enforce).
