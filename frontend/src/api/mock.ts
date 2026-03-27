/**
 * Mock 数据 — API 未连通时 fallback。
 */
import type {
  DashboardSummary,
  NAVPoint,
  PendingAction,
  Position,
  CircuitBreakerState,
} from "@/types/dashboard";

export const MOCK_SUMMARY: DashboardSummary = {
  nav: 1.0312,
  sharpe: 0.87,
  mdd: -0.0523,
  position_count: 15,
  daily_return: 0.0034,
  cumulative_return: 0.0312,
  cash_ratio: 0.042,
  trade_date: "2026-03-25",
};

function generateMockNAV(days: number): NAVPoint[] {
  const points: NAVPoint[] = [];
  let nav = 1.0;
  const now = new Date();
  for (let i = days; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dailyReturn = (Math.random() - 0.48) * 0.02;
    nav *= 1 + dailyReturn;
    const cumReturn = nav - 1;
    const peak = Math.max(nav, ...points.map((p) => p.nav), 1);
    const drawdown = (nav - peak) / peak;
    points.push({
      trade_date: d.toISOString().slice(0, 10),
      nav: Number(nav.toFixed(4)),
      daily_return: Number(dailyReturn.toFixed(6)),
      cumulative_return: Number(cumReturn.toFixed(6)),
      drawdown: Number(drawdown.toFixed(6)),
    });
  }
  return points;
}

export const MOCK_NAV_SERIES: NAVPoint[] = generateMockNAV(60);

export const MOCK_POSITIONS: Position[] = [
  { code: "600519", quantity: 100, market_value: 168500, weight: 0.068, avg_cost: 1650.0, unrealized_pnl: 3500, holding_days: 12 },
  { code: "000858", quantity: 300, market_value: 45900, weight: 0.065, avg_cost: 148.0, unrealized_pnl: 1500, holding_days: 12 },
  { code: "601318", quantity: 400, market_value: 24800, weight: 0.064, avg_cost: 60.5, unrealized_pnl: -600, holding_days: 8 },
  { code: "000001", quantity: 1000, market_value: 12500, weight: 0.063, avg_cost: 12.2, unrealized_pnl: 300, holding_days: 12 },
  { code: "600036", quantity: 500, market_value: 20000, weight: 0.062, avg_cost: 39.0, unrealized_pnl: 1000, holding_days: 5 },
  { code: "000333", quantity: 200, market_value: 13600, weight: 0.061, avg_cost: 66.0, unrealized_pnl: 1600, holding_days: 12 },
  { code: "002714", quantity: 200, market_value: 9800, weight: 0.06, avg_cost: 47.5, unrealized_pnl: 1300, holding_days: 3 },
  { code: "601166", quantity: 800, market_value: 12000, weight: 0.059, avg_cost: 14.8, unrealized_pnl: 200, holding_days: 12 },
  { code: "600276", quantity: 100, market_value: 7500, weight: 0.058, avg_cost: 73.0, unrealized_pnl: 2000, holding_days: 12 },
  { code: "000568", quantity: 300, market_value: 8700, weight: 0.057, avg_cost: 28.0, unrealized_pnl: 300, holding_days: 12 },
  { code: "601888", quantity: 100, market_value: 8200, weight: 0.056, avg_cost: 80.0, unrealized_pnl: 200, holding_days: 12 },
  { code: "002594", quantity: 100, market_value: 25800, weight: 0.055, avg_cost: 252.0, unrealized_pnl: 6000, holding_days: 12 },
  { code: "600900", quantity: 300, market_value: 7200, weight: 0.054, avg_cost: 23.5, unrealized_pnl: 150, holding_days: 12 },
  { code: "601012", quantity: 200, market_value: 6400, weight: 0.053, avg_cost: 31.0, unrealized_pnl: 400, holding_days: 12 },
  { code: "300750", quantity: 100, market_value: 17800, weight: 0.052, avg_cost: 172.0, unrealized_pnl: 6000, holding_days: 8 },
];

export const MOCK_PENDING_ACTIONS: PendingAction[] = [];

export const MOCK_CIRCUIT_BREAKER: CircuitBreakerState = {
  level: 0,
  level_name: "NORMAL",
  entered_date: "2026-03-23",
  trigger_reason: null,
  trigger_metrics: null,
  position_multiplier: 1.0,
  can_rebalance: true,
  recovery_streak_days: 0,
  recovery_streak_return: 0,
  requires_manual_approval: false,
};
