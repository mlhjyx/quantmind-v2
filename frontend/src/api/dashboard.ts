// Frontend Design v3 §4.3 / Audit Finding #10: 2 套 axios 统一 → apiClient SSOT
// (反 bypass apiClient.interceptors 真 401/429/503 toast handler + auth header)
import apiClient from "./client";
import type {
  Alert,
  DashboardSummary,
  FactorRow,
  IndustryItem,
  MarketTickerItem,
  MonthlyReturns,
  NAVPoint,
  NAVPeriod,
  PendingAction,
  PipelineStep,
  Position,
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

export async function fetchAlerts(hours = 24): Promise<Alert[]> {
  const { data } = await api.get<Alert[]>("/dashboard/alerts", {
    params: { hours },
  });
  return data;
}

export async function fetchMonthlyReturns(): Promise<MonthlyReturns> {
  const { data } = await api.get<MonthlyReturns>("/dashboard/monthly-returns", {
    params: { execution_mode: "live" },
  });
  return data;
}

export async function fetchIndustryDistribution(): Promise<IndustryItem[]> {
  const { data } = await api.get<IndustryItem[]>(
    "/dashboard/industry-distribution",
    { params: { execution_mode: "live" } },
  );
  return data;
}

export async function fetchMarketTicker(): Promise<MarketTickerItem[]> {
  const { data } = await api.get<MarketTickerItem[]>("/dashboard/market-ticker");
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

export interface PaperTradingStatus {
  nav: number;
  position_count: number;
  running_days: number;
  sharpe: number;
  mdd: number;
  total_return: number;
  trade_date: string | null;
  graduation_ready: boolean;
}

export async function fetchPaperTradingStatus(
  strategyId = "",
): Promise<PaperTradingStatus> {
  const config = strategyId
    ? { params: { strategy_id: strategyId } }
    : undefined;
  const { data } = await api.get<PaperTradingStatus>("/paper-trading/status", config);
  return data;
}

export type PaperTradingExecutionMode = "paper" | "live" | string;

export interface PaperGraduationCriterion {
  id?: string;
  name: string;
  target: string;
  actual: string;
  passed: boolean;
  current?: number | string;
  progress?: number;
  status?: "pass" | "warn" | "fail" | "observe";
  unit?: string;
  description?: string;
}

export interface PaperGraduationStatus {
  days_running: number;
  sharpe: number;
  mdd: number;
  slippage_deviation: number;
  graduate_ready: boolean;
  overall_status?: "on_track" | "at_risk" | "failing";
  criteria: PaperGraduationCriterion[];
}

export async function fetchPaperGraduationStatus(
  executionMode: PaperTradingExecutionMode = "live",
): Promise<PaperGraduationStatus> {
  const { data } = await api.get<PaperGraduationStatus>(
    "/paper-trading/graduation-status",
    { params: { execution_mode: executionMode } },
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

interface DashboardFactorRaw {
  name: string;
  category: string | null;
  direction: string;
  status: string;
  ic_mean: number | null;
  ic_ir: number | null;
}

export async function fetchDashboardFactorRows(): Promise<FactorRow[]> {
  const { data } = await api.get<DashboardFactorRaw[]>("/factors");
  return data.map((factor) => ({
    name: factor.name,
    cat: factor.category ?? "未知",
    ic: factor.ic_mean ?? 0,
    ir: factor.ic_ir ?? 0,
    dir: factor.direction === "positive" ? "正向" : "反向",
    status:
      factor.status === "active"
        ? "active"
        : factor.status === "candidate"
          ? "new"
          : "decay",
    trend: [],
  }));
}

interface PipelineStatusRaw {
  status?: string;
  current_node?: string | null;
  node_statuses?: Record<string, string>;
  nodes?: Array<{ id?: string; name?: string; status: string }>;
}

function toDashboardStepStatus(
  name: string,
  status: string,
  currentNode?: string | null,
  pipelineStatus?: string,
): string {
  if (status === "completed") return "done";
  if (name === currentNode && pipelineStatus === "running") return "running";
  return status;
}

export async function fetchDashboardPipelineSteps(): Promise<PipelineStep[]> {
  const { data } = await api.get<PipelineStatusRaw>("/pipeline/status");
  if (data.nodes && data.nodes.length > 0) {
    return data.nodes.map((node) => {
      const name = node.name ?? node.id ?? "";
      return {
        name,
        status: toDashboardStepStatus(
          node.id ?? name,
          node.status,
          data.current_node,
          data.status,
        ),
      };
    });
  }

  return Object.entries(data.node_statuses ?? {}).map(([name, status]) => ({
    name,
    status: toDashboardStepStatus(name, status, data.current_node, data.status),
  }));
}
