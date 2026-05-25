// Frontend Design v3 §4.3 / Audit Finding #10: 2 套 axios 统一 → apiClient SSOT
// (反 bypass apiClient.interceptors 真 401/429/503 toast handler + auth header)
import apiClient from "./client";
import type {
  DashboardSummary,
  NAVPoint,
  NAVPeriod,
  PendingAction,
  Position,
  CircuitBreakerState,
  Trade,
} from "@/types/dashboard";

const api = apiClient;

export async function fetchSummary(): Promise<DashboardSummary> {
  const { data } = await api.get<DashboardSummary>("/dashboard/summary", {
    params: { execution_mode: "live" },
  });
  return data;
}

export async function fetchNAVSeries(
  period: NAVPeriod = "3m",
): Promise<NAVPoint[]> {
  const { data } = await api.get<NAVPoint[]>("/dashboard/nav-series", {
    params: { period, execution_mode: "live" },
  });
  return data;
}

export async function fetchPendingActions(): Promise<PendingAction[]> {
  const { data } = await api.get<PendingAction[]>(
    "/dashboard/pending-actions",
  );
  return data;
}

/** iter 141 W2-F F7 — fetch paper trading trades (D5 wire).
 *  Backend: GET /api/paper-trading/trades?strategy_id=&limit=N (paper_trading.py:243). */
export async function fetchPaperTrades(limit = 50): Promise<Trade[]> {
  const { data } = await api.get<Trade[]>("/paper-trading/trades", {
    params: { limit },
  });
  return data;
}

export async function fetchPositions(): Promise<Position[]> {
  // 优先使用realtime API（QMT实时持仓），fallback到paper-trading
  try {
    interface RtPosition { code: string; shares: number; market_value: number; weight: number; cost_price: number; pnl_pct: number }
    const { data } = await api.get<{ positions: RtPosition[] }>("/realtime/portfolio");
    return (data.positions ?? []).map((p) => ({
      code: p.code,
      quantity: p.shares,
      market_value: p.market_value,
      weight: p.weight / 100,
      avg_cost: p.cost_price,
      unrealized_pnl: p.pnl_pct / 100,
      holding_days: 0,
    }));
  } catch {
    const { data } = await api.get<Position[]>("/paper-trading/positions");
    return data;
  }
}

export interface StrategyOverview {
  id: string;
  name: string;
  status: string;
  market: string | null;
  sharpe: number | null;
  pnl: number | null;
  mdd: number | null;
}

export async function fetchDashboardStrategies(): Promise<StrategyOverview[]> {
  const { data } = await api.get<StrategyOverview[]>("/dashboard/strategies");
  return data;
}

export async function fetchCircuitBreakerState(): Promise<CircuitBreakerState | null> {
  try {
    const { data } = await api.get<CircuitBreakerState>(
      "/risk/state/default",
      { params: { execution_mode: "live" } },
    );
    return data;
  } catch {
    return null;
  }
}
