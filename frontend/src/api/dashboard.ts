import axios from "axios";
import type {
  DashboardSummary,
  NAVPoint,
  NAVPeriod,
  PendingAction,
  Position,
  CircuitBreakerState,
} from "@/types/dashboard";

const api = axios.create({ baseURL: "/api" });

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
