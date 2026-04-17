> **文档状态: PARTIALLY_IMPLEMENTED (2026-04-16 更新)**
> 实现状态: ~35% — notification_service+templates+throttler已实现。后端5个API端点已有(list/unread-count/read/detail/test)。notifications表已建(541行数据)。
> **前端**: DEV_FRONTEND_UI.md §十三 定义了 Toast/铃铛/通知中心/分级/偏好, 前端页面待审计数据绑定状态。
> 未实现: 邮件/微信推送、告警升级链、WebSocket实时推送(/ws/notifications)
> 唯一设计真相源: **docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md §13**

# QuantMind V2 — 通知告警详细开发文档

> 文档级别：实现级（供 Claude Code 执行）
> 创建日期：2026-03-20
> 关联文档：DEV_FRONTEND_UI.md §十三(前端设计), DEV_SCHEDULER.md
> 前端设计已完成：Toast/铃铛/通知中心/分级/偏好，详见 DEV_FRONTEND_UI.md

---

## 一、架构

```
通知产生源(调度/风控/AI/交易/系统)
    ↓ 调用统一接口
NotificationService
    ├── 写入notifications表(P0-P2)
    ├── WebSocket推送 /ws/notifications
    └── NotificationDispatcher → 钉钉Webhook / 微信(Phase 3) / 邮件(Phase 4)
```

防洪泛: NotificationThrottler(Redis TTL, 同类通知最小间隔)

---

## 二、NotificationService

统一入口: `send(level, category, market, title, content, link)`

流程:
1. P3 → 仅WS推送Toast(不存库)
2. P0-P2 → 存库 + WS推送 + 外发检查
3. 外发检查: P0始终发(无视静默), P1受静默限制, P2看偏好
4. 防洪泛: 同类通知在TTL内不重复

---

## 三、NotificationDispatcher

### 3.1 钉钉Webhook

POST `https://oapi.dingtalk.com/robot/send?access_token=xxx`
消息类型: markdown
格式: emoji+级别+市场+标题+内容+时间戳
超时10秒, 失败不影响主流程(仅日志)

### 3.2 微信推送(Phase 3)

预留接口, Phase 3实现

### 3.3 邮件(Phase 4)

预留接口

---

## 四、通知模板(25+预定义)

### 4.1 风控类(7个)

| 模板key | 级别 | 标题模式 |
|---------|------|---------|
| risk.drawdown_warning | P1 | {market}账户回撤达{drawdown}% |
| risk.drawdown_pause | P0 | {market}回撤达{drawdown}%，已暂停新开仓 |
| risk.drawdown_emergency | P0 | 🚨{market}紧急平仓! |
| risk.margin_warning | P1 | 外汇保证金使用率{margin_pct}% |
| risk.margin_call | P0 | 🚨Margin Call! 已强平{symbol} |
| risk.consecutive_loss | P1 | {market}连续亏损{count}次 |
| risk.daily_loss | P1 | {market}今日亏损{loss_pct}% |

### 4.2 交易类(6个)

| 模板key | 级别 | 标题模式 |
|---------|------|---------|
| trade.forex_open | P2 | {symbol}做{direction}{lot}手已成交 |
| trade.forex_close | P2 | {symbol}已平仓 +/-{pnl_pips}pip |
| trade.forex_sl_modified | P3 | {symbol}止损已移至{new_sl} |
| trade.friday_close | P2 | 周五减仓: 已平{count}笔 |
| trade.astock_rebalance | P2 | A股调仓完成 |
| trade.event_protection | P1 | 经济事件保护: {event_name} |

### 4.3 因子类(2个)

| 模板key | 级别 | 标题模式 |
|---------|------|---------|
| factor.degraded | P1 | 因子{factor_name}衰退预警 |
| factor.new_candidate | P2 | {count}个新因子待审批 |

### 4.4 回测类(2个)

| 模板key | 级别 | 标题模式 |
|---------|------|---------|
| backtest.complete | P2 | 回测完成: Sharpe:{sharpe} |
| backtest.failed | P1 | 回测失败: {error} |

### 4.5 AI闭环类(2个)

| 模板key | 级别 | 标题模式 |
|---------|------|---------|
| pipeline.complete | P2 | AI闭环第{round}轮完成 |
| pipeline.approval_needed | P2 | {count}项待审批 |

### 4.6 系统类(6个)

| 模板key | 级别 | 标题模式 |
|---------|------|---------|
| system.data_update_failed | P0 | {market}数据更新失败 |
| system.mt5_disconnect | P0 | MT5连接丢失 |
| system.mt5_reconnected | P3 | MT5已重连 |
| system.db_connection_lost | P0 | 数据库连接丢失 |
| system.disk_space_low | P1 | 磁盘空间不足 |
| system.scheduler_task_delayed | P1 | 调度任务延迟 |
| system.param_cooldown_expired | P2 | 参数冷却期到期 |

模板渲染: render_template(key, **kwargs) → {level, category, title, content, link}

---

## 五、防洪泛(Throttler)

Redis TTL机制, 同类通知在间隔内不重复发送:

| 模板 | 最小间隔 |
|------|---------|
| risk.drawdown_warning | 5min |
| risk.margin_warning | 10min |
| risk.consecutive_loss | 1h |
| risk.daily_loss | 24h |
| system.mt5_disconnect | 1min |
| system.disk_space_low | 1h |
| trade.forex_sl_modified | 1min |

---

## 六、通知生命周期

创建→未读→已读→已处理(审批类)→归档
清理: 已读+已处理30天删除, P0保留90天, 未读不删除
清理任务: 系统维护(每周日03:00)

---

## 七、数据库表(2张)

```sql
-- notifications表(已在DEV_FRONTEND_UI.md §13.9定义)
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level           VARCHAR(2) NOT NULL,
    category        VARCHAR(20) NOT NULL,
    market          VARCHAR(10) DEFAULT 'system',
    title           VARCHAR(100) NOT NULL,
    content         TEXT,
    link            VARCHAR(200),
    is_read         BOOLEAN DEFAULT FALSE,
    is_acted        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notifications_unread ON notifications(is_read, created_at DESC);

-- notification_preferences表
CREATE TABLE notification_preferences (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    toast_p0 BOOLEAN DEFAULT TRUE, toast_p1 BOOLEAN DEFAULT TRUE,
    toast_p2 BOOLEAN DEFAULT TRUE, toast_p3 BOOLEAN DEFAULT TRUE,
    center_p0 BOOLEAN DEFAULT TRUE, center_p1 BOOLEAN DEFAULT TRUE, center_p2 BOOLEAN DEFAULT TRUE,
    sound_p0 BOOLEAN DEFAULT TRUE, sound_other BOOLEAN DEFAULT FALSE,
    dingtalk_enabled BOOLEAN DEFAULT FALSE, dingtalk_webhook VARCHAR(500),
    dingtalk_verified BOOLEAN DEFAULT FALSE,
    dispatch_p0 BOOLEAN DEFAULT TRUE, dispatch_p1 BOOLEAN DEFAULT TRUE, dispatch_p2 BOOLEAN DEFAULT FALSE,
    quiet_enabled BOOLEAN DEFAULT TRUE, quiet_start SMALLINT DEFAULT 23, quiet_end SMALLINT DEFAULT 7,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 八、后端API

| 端点 | 方法 | 功能 |
|------|------|------|
| /api/notifications | GET | 列表(分页,筛选level/category/is_read) |
| /api/notifications/unread-count | GET | 未读计数(铃铛数字) |
| /api/notifications/{id}/read | PUT | 标记已读 |
| /api/notifications/read-all | PUT | 全部已读 |
| /api/notifications/preferences | GET | 获取偏好 |
| /api/notifications/preferences | PUT | 更新偏好 |
| /api/notifications/test-dingtalk | POST | 测试钉钉发送 |
| /api/notifications/clear-old | DELETE | 清理旧通知 |
| /ws/notifications | WS | 实时推送 |

---

## ⚠️ Review补丁（2026-03-20）

### P1. 新增通知模板（追加到 §四）

| 模板key | 级别 | 标题模式 | 触发场景 |
|---------|------|---------|---------|
| system.health_precheck_failed | P0 | 健康预检失败: {failed_items} | 每日T0预检不通过 |
| factor.active_count_low | P1 | 活跃因子仅剩{count}个(<12) | 因子生命周期退休过多 |
| ai.change_approved | P2 | AI变更#{id}已审批通过 | 变更三步流程第3步 |
| ai.change_rejected | P2 | AI变更#{id}自动拒绝: {reason} | 快速回测验证不通过 |
| ai.diagnosis_triggered | P2 | AI诊断已触发: {trigger_reason} | 绩效衰退>阈值 |
| paper.milestone | P2 | Paper Trading已运行{days}/60天 | 每10天里程碑 |
| paper.graduation_ready | P1 | Paper Trading达标！可转实盘 | 5项毕业标准全部达标 |

### P2. 防洪泛追加

| 模板 | 最小间隔 |
|------|---------|
| system.health_precheck_failed | 10min |
| factor.active_count_low | 24h |
| ai.diagnosis_triggered | 1h |
