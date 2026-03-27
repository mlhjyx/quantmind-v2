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
  const { data } = await api.get<DashboardSummary>("/dashboard/summary");
  return data;
}

export async function fetchNAVSeries(
  period: NAVPeriod = "3m",
): Promise<NAVPoint[]> {
  const { data } = await api.get<NAVPoint[]>("/dashboard/nav-series", {
    params: { period },
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
  const { data } = await api.get<Position[]>("/paper-trading/positions");
  return data;
}

export async function fetchCircuitBreakerState(): Promise<CircuitBreakerState | null> {
  try {
    const { data } = await api.get<CircuitBreakerState>(
      "/risk/state/default",
      { params: { execution_mode: "paper" } },
    );
    return data;
  } catch {
    return null;
  }
}
