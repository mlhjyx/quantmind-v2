"""通知模板 -- 预定义通知模板(第1批10个核心模板)。

每个模板包含: title_template, content_template, default_level, category。
模板变量用 {var} 占位，调用时传入 kwargs 渲染。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationTemplate:
    """通知模板定义。

    Attributes:
        key: 模板唯一标识，如 'health_check_failed'。
        title_template: 标题模板，支持 {var} 占位。
        content_template: 内容模板(Markdown)，支持 {var} 占位。
        default_level: 默认级别 P0/P1/P2/P3。
        category: 通知分类。
        market: 默认市场，None表示由调用方指定。
    """

    key: str
    title_template: str
    content_template: str
    default_level: str
    category: str
    market: str | None = None

    def render(self, **kwargs: object) -> tuple[str, str, str]:
        """渲染模板，返回 (title, content, level)。

        Args:
            **kwargs: 模板变量，用于填充 {var} 占位符。
                可包含 'level' 覆盖默认级别。

        Returns:
            (title, content, level) 三元组。
        """
        level = str(kwargs.pop("level", self.default_level))
        title = self.title_template.format(**kwargs)
        content = self.content_template.format(**kwargs)
        return title, content, level


# ---------------------------------------------------------------------------
# 第1批: 10个核心模板
# ---------------------------------------------------------------------------

HEALTH_CHECK_FAILED = NotificationTemplate(
    key="health_check_failed",
    title_template="健康预检失败: {failed_items}",
    content_template=(
        "### 健康预检失败\n\n"
        "**检查时间**: {check_time}\n\n"
        "**失败项目**: {failed_items}\n\n"
        "当日调度链路已暂停，请排查后手动恢复。"
    ),
    default_level="P0",
    category="system",
    market="system",
)

CIRCUIT_BREAKER_TRIGGERED = NotificationTemplate(
    key="circuit_breaker_triggered",
    title_template="{market}回撤熔断触发: {state}",
    content_template=(
        "### 回撤熔断触发\n\n"
        "**市场**: {market}\n\n"
        "**当前状态**: {state}\n\n"
        "**当前回撤**: {drawdown}%\n\n"
        "**触发条件**: {trigger_reason}\n\n"
        "请关注后续恢复条件。"
    ),
    default_level="P0",
    category="risk",
)

DAILY_SIGNAL_COMPLETE = NotificationTemplate(
    key="daily_signal_complete",
    title_template="T日信号生成完成 ({signal_count}个信号)",
    content_template=(
        "### 信号生成完成\n\n"
        "**交易日**: {trade_date}\n\n"
        "**信号数量**: {signal_count}\n\n"
        "**买入**: {buy_count} | **卖出**: {sell_count} | **持有**: {hold_count}\n\n"
        "调仓指令已存库，等待T+1确认执行。"
    ),
    default_level="P2",
    category="pipeline",
    market="astock",
)

DAILY_EXECUTE_COMPLETE = NotificationTemplate(
    key="daily_execute_complete",
    title_template="{market}执行完成 (成交{filled}/{total})",
    content_template=(
        "### 执行完成\n\n"
        "**市场**: {market}\n\n"
        "**成交**: {filled}/{total}\n\n"
        "**拒绝/部分成交**: {rejected}\n\n"
        "**预估滑点**: {slippage_bps}bps"
    ),
    default_level="P2",
    category="strategy",
)

REBALANCE_SUMMARY = NotificationTemplate(
    key="rebalance_summary",
    title_template="{market}调仓汇总 (买{buy_count}卖{sell_count})",
    content_template=(
        "### 调仓汇总\n\n"
        "**交易日**: {trade_date}\n\n"
        "**买入**: {buy_count}只 | **卖出**: {sell_count}只\n\n"
        "**换手率**: {turnover:.1f}%\n\n"
        "**买入标的**: {buy_list}\n\n"
        "**卖出标的**: {sell_list}"
    ),
    default_level="P2",
    category="strategy",
)

PAPER_TRADING_DAILY_REPORT = NotificationTemplate(
    key="paper_trading_daily_report",
    title_template="Paper Trading {trade_date} {daily_return}",
    content_template=(
        "### Paper Trading 日报\n\n"
        "| 指标 | 数值 |\n"
        "|------|------|\n"
        "| 日期 | {trade_date} |\n"
        "| NAV | {nav} |\n"
        "| 日收益 | {daily_return} |\n"
        "| 累计收益 | {cum_return} |\n"
        "| 持仓数 | {position_count} |\n"
        "| Beta | {beta} |"
    ),
    default_level="P2",
    category="strategy",
    market="astock",
)

FACTOR_IC_DECAY = NotificationTemplate(
    key="factor_ic_decay",
    title_template="因子{factor_name}衰退预警 (IC={ic_current:.4f})",
    content_template=(
        "### 因子衰退预警\n\n"
        "**因子**: {factor_name}\n\n"
        "**当前IC**: {ic_current:.4f}\n\n"
        "**基准IC**: {ic_baseline:.4f}\n\n"
        "**衰退幅度**: {decay_pct:.1f}%\n\n"
        "建议关注因子生命周期状态，必要时启动替补挖掘。"
    ),
    default_level="P1",
    category="factor",
)

PARAMETER_CHANGED = NotificationTemplate(
    key="parameter_changed",
    title_template="参数变更: {param_name}",
    content_template=(
        "### 参数变更通知\n\n"
        "**参数**: {param_name}\n\n"
        "**旧值**: {old_value}\n\n"
        "**新值**: {new_value}\n\n"
        "**变更人**: {changed_by}\n\n"
        "变更已生效，请关注后续表现。"
    ),
    default_level="P1",
    category="system",
)

PIPELINE_ERROR = NotificationTemplate(
    key="pipeline_error",
    title_template="管道异常: {task_name}",
    content_template=(
        "### 管道任务异常\n\n"
        "**任务**: {task_name}\n\n"
        "**阶段**: {stage}\n\n"
        "**错误**: {error_message}\n\n"
        "**影响**: {impact}\n\n"
        "请尽快排查修复。"
    ),
    default_level="P0",
    category="pipeline",
)

FACTOR_COVERAGE_LOW = NotificationTemplate(
    key="factor_coverage_low",
    title_template="P0 因子覆盖率严重不足: {factor_name} ({count}只)",
    content_template=(
        "### 因子截面覆盖率严重不足\n\n"
        "**交易日**: {trade_date}\n\n"
        "**因子**: {factor_name}\n\n"
        "**覆盖股票数**: {count}只 (阈值: 1000)\n\n"
        "**影响**: 信号生成已阻塞，当日管道停止。\n\n"
        "可能原因: 数据源故障、拉取异常、因子计算报错。请排查后手动恢复。"
    ),
    default_level="P0",
    category="pipeline",
    market="astock",
)

FACTOR_COVERAGE_WARNING = NotificationTemplate(
    key="factor_coverage_warning",
    title_template="因子覆盖率偏低: {factor_name} ({count}只)",
    content_template=(
        "### 因子截面覆盖率偏低\n\n"
        "**交易日**: {trade_date}\n\n"
        "**因子**: {factor_name}\n\n"
        "**覆盖股票数**: {count}只 (正常应>3000)\n\n"
        "**影响**: 信号生成继续，但截面覆盖不足可能导致排名偏差。\n\n"
        "请排查数据完整性，关注当日信号质量。"
    ),
    default_level="P1",
    category="pipeline",
    market="astock",
)

INDUSTRY_CONCENTRATION_HIGH = NotificationTemplate(
    key="industry_concentration_high",
    title_template="行业集中度超标: {max_industry} ({max_weight})",
    content_template=(
        "### Top20持仓行业集中度超标\n\n"
        "**交易日**: {trade_date}\n\n"
        "**最大行业**: {max_industry}\n\n"
        "**行业权重**: {max_weight} (阈值: 25%)\n\n"
        "**Top5行业分布**: {industry_distribution}\n\n"
        "行业过于集中会增大尾部风险，建议检查因子是否对特定行业有系统性偏好。"
    ),
    default_level="P1",
    category="strategy",
    market="astock",
)

HIGH_TURNOVER_ALERT = NotificationTemplate(
    key="high_turnover_alert",
    title_template="持仓换手剧烈: 重合度{overlap_ratio}",
    content_template=(
        "### 持仓重合度过低\n\n"
        "**交易日**: {trade_date}\n\n"
        "**重合度**: {overlap_ratio} (阈值: 30%)\n\n"
        "**重合数量**: {overlap_count}/{prev_count}\n\n"
        "**新进标的**: {new_codes}\n\n"
        "**退出标的**: {exit_codes}\n\n"
        "重合度低于30%意味着大幅换仓，可能导致高额交易成本和执行滑点。"
        "建议人工确认信号合理性后再执行。"
    ),
    default_level="P1",
    category="strategy",
    market="astock",
)

SYSTEM_DISK_WARNING = NotificationTemplate(
    key="system_disk_warning",
    title_template="磁盘空间不足: 剩余{free_gb:.1f}GB",
    content_template=(
        "### 磁盘空间警告\n\n"
        "**剩余空间**: {free_gb:.1f}GB\n\n"
        "**阈值**: {threshold_gb}GB\n\n"
        "**最大目录**: {largest_dir}\n\n"
        "建议清理日志或归档历史数据。"
    ),
    default_level="P1",
    category="system",
    market="system",
)


# ---------------------------------------------------------------------------
# 模板注册表 -- 按key索引
# ---------------------------------------------------------------------------

TEMPLATE_REGISTRY: dict[str, NotificationTemplate] = {
    t.key: t
    for t in [
        HEALTH_CHECK_FAILED,
        CIRCUIT_BREAKER_TRIGGERED,
        DAILY_SIGNAL_COMPLETE,
        DAILY_EXECUTE_COMPLETE,
        REBALANCE_SUMMARY,
        PAPER_TRADING_DAILY_REPORT,
        FACTOR_IC_DECAY,
        PARAMETER_CHANGED,
        PIPELINE_ERROR,
        FACTOR_COVERAGE_LOW,
        FACTOR_COVERAGE_WARNING,
        INDUSTRY_CONCENTRATION_HIGH,
        HIGH_TURNOVER_ALERT,
        SYSTEM_DISK_WARNING,
    ]
}


def get_template(key: str) -> NotificationTemplate:
    """按key获取模板。

    Args:
        key: 模板唯一标识。

    Returns:
        对应的 NotificationTemplate。

    Raises:
        KeyError: 模板不存在。
    """
    if key not in TEMPLATE_REGISTRY:
        raise KeyError(f"通知模板 '{key}' 不存在，可用模板: {list(TEMPLATE_REGISTRY.keys())}")
    return TEMPLATE_REGISTRY[key]
