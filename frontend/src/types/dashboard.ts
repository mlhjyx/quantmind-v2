/** Dashboard 7 指标卡数据 */
export interface DashboardSummary {
  nav: number;
  sharpe: number;
  mdd: number;
  position_count: number;
  daily_return: number;
  cumulative_return: number;
  cash_ratio: number;
  trade_date: string | null;
}

/** NAV 时间序列单点 */
export interface NAVPoint {
  trade_date: string;
  nav: number;
  daily_return: number;
  cumulative_return: number;
  drawdown: number;
}

/** 待处理事项 */
export interface PendingAction {
  type: "health" | "circuit_breaker" | "pipeline";
  severity: "critical" | "warning" | "info";
  message: string;
  time: string | null;
}

/** 持仓记录 */
export interface Position {
  code: string;
  quantity: number;
  market_value: number;
  weight: number;
  avg_cost: number;
  unrealized_pnl: number;
  holding_days: number;
}

/** 熔断状态 */
export interface CircuitBreakerState {
  level: number;
  level_name: string;
  entered_date: string;
  trigger_reason: string | null;
  trigger_metrics: Record<string, number> | null;
  position_multiplier: number;
  can_rebalance: boolean;
  recovery_streak_days: number;
  recovery_streak_return: number;
  requires_manual_approval: boolean;
}

/** NAV 时间筛选周期 */
export type NAVPeriod = "1m" | "3m" | "6m" | "1y" | "all";
