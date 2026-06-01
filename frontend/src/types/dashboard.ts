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

/** Dashboard 预警面板行 */
export interface Alert {
  level: string;
  color: string;
  title: string;
  desc: string;
  time: string;
}

/** Dashboard 月度收益矩阵，后端无数据月份返回 null。 */
export type MonthlyReturns = Record<string, Array<number | null>>;

/** Dashboard 行业分布行 */
export interface IndustryItem {
  name: string;
  pct: number;
  color: string;
}

/** Dashboard 因子库行 */
export interface FactorRow {
  name: string;
  cat: string;
  ic: number;
  ir: number;
  dir: string;
  status: string;
  trend: number[];
}

/** Dashboard AI pipeline step */
export interface PipelineStep {
  name: string;
  status: string;
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

/** iter 141 W2-F F7 — paper trade record (D5 wire).
 *  Backend SSOT: backend/app/repositories/trade_repository.py:14 get_trades + api/paper_trading.py:243 */
export interface Trade {
  id: string;
  code: string;
  trade_date: string; // ISO date
  direction: "BUY" | "SELL" | string;
  quantity: number;
  fill_price: number;
  slippage_bps: number;
  commission: number;
  stamp_tax: number | null;
  total_cost: number | null;
  reject_reason: string | null;
}
