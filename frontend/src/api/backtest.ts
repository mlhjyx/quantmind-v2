import apiClient from "./client";

// ---- Types ----

export type BacktestStatus = "waiting" | "running" | "completed" | "failed" | "cancelled";

export interface BacktestProgress {
  run_id: string;
  status: BacktestStatus;
  progress: number; // 0-100
  elapsed_seconds: number;
  estimated_remaining_seconds: number | null;
  current_window?: string; // WF mode: "2/5"
  current_date?: string;
  sharpe_realtime?: number;
  mdd_realtime?: number;
  nav_realtime?: Array<{ date: string; nav: number }>;
  logs: Array<{ ts: string; level: "info" | "warn" | "error"; msg: string }>;
}

export interface BacktestMetrics {
  annual_return: number;
  sharpe: number;
  dsr: number; // Deflated Sharpe Ratio
  mdd: number;
  calmar: number;
  annual_turnover: number;
  net_return_after_cost: number;
  wf_oos_sharpe: number | null;
}

export interface NavPoint {
  date: string;
  strategy: number;
  benchmark: number;
  excess: number;
  drawdown: number;
}

export interface MonthlyReturn {
  year: number;
  month: number;
  return: number;
}

export interface Holding {
  symbol: string;
  name: string;
  industry: string;
  weight: number;
  return: number;
}

export interface Trade {
  date: string;
  symbol: string;
  name: string;
  direction: "buy" | "sell";
  price: number;
  quantity: number;
  amount: number;
  commission: number;
  slippage: number;
  pnl: number | null;
}

export interface RiskMetric {
  label: string;
  value: number;
  unit: string;
}

export interface FactorContribution {
  factor_name: string;
  ic: number;
  weight: number;
  contribution: number;
}

export interface WFWindow {
  window_id: number;
  train_start: string;
  train_end: string;
  oos_start: string;
  oos_end: string;
  oos_sharpe: number;
  oos_mdd: number;
}

export interface BacktestResult {
  run_id: string;
  strategy_id: string;
  strategy_name: string;
  status: BacktestStatus;
  created_at: string;
  completed_at: string | null;
  metrics: BacktestMetrics;
  nav: NavPoint[];
  monthly_returns: MonthlyReturn[];
  holdings: Holding[];
  trades: Trade[];
  risk_metrics: RiskMetric[];
  factor_contributions: FactorContribution[];
  wf_windows: WFWindow[] | null;
  config_snapshot: Record<string, unknown>;
}

export interface BacktestHistoryItem {
  run_id: string;
  strategy_id: string;
  strategy_name: string;
  status: BacktestStatus;
  created_at: string;
  completed_at: string | null;
  sharpe: number | null;
  mdd: number | null;
  annual_return: number | null;
}

export interface RunBacktestPayload {
  strategy_id: string;
  config: Record<string, unknown>;
}

// ---- API Functions ----

export async function runBacktest(payload: RunBacktestPayload): Promise<{ run_id: string }> {
  const res = await apiClient.post<{ run_id: string }>("/backtest/run", payload);
  return res.data;
}

export async function getBacktestProgress(runId: string): Promise<BacktestProgress> {
  const res = await apiClient.get<BacktestProgress>(`/backtest/${runId}/progress`);
  return res.data;
}

export async function getBacktestResult(runId: string): Promise<BacktestResult> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const res = await apiClient.get<any>(`/backtest/${runId}/result`);
  const d = res.data;
  const raw = d.metrics ?? {};
  const num = (v: unknown): number => (v != null ? Number(v) : 0);
  return {
    run_id: d.run_id ?? runId,
    strategy_id: d.strategy_id ?? "",
    strategy_name: d.run_name ?? d.strategy_name ?? `回测_${runId.slice(0, 8)}`,
    status: d.status ?? "completed",
    created_at: d.created_at ?? "",
    completed_at: d.finished_at ?? d.completed_at ?? null,
    metrics: {
      annual_return: num(raw.annual_return),
      sharpe: num(raw.sharpe ?? raw.sharpe_ratio),
      dsr: num(raw.dsr ?? raw.deflated_sharpe),
      mdd: num(raw.mdd ?? raw.max_drawdown),
      calmar: num(raw.calmar ?? raw.calmar_ratio),
      annual_turnover: num(raw.annual_turnover ?? raw.total_turnover),
      net_return_after_cost: num(raw.net_return_after_cost),
      wf_oos_sharpe: raw.wf_oos_sharpe != null ? num(raw.wf_oos_sharpe) : null,
    },
    nav: d.nav ?? d.nav_series ?? [],
    monthly_returns: d.monthly_returns ?? [],
    holdings: d.holdings ?? [],
    trades: d.trades ?? d.trade_log ?? [],
    risk_metrics: d.risk_metrics ?? [],
    factor_contributions: d.factor_contributions ?? [],
    wf_windows: d.wf_windows ?? null,
    config_snapshot: d.config ?? {},
  };
}

export async function cancelBacktest(runId: string): Promise<void> {
  await apiClient.post(`/backtest/${runId}/cancel`);
}

export async function listBacktestHistory(strategyId?: string): Promise<BacktestHistoryItem[]> {
  const params = strategyId ? { strategy_id: strategyId } : {};
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const res = await apiClient.get<any>("/backtest/history", { params });
  const raw = res.data;
  const items: unknown[] = Array.isArray(raw) ? raw : raw?.items ?? [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return items.map((r: any) => ({
    run_id: r.run_id,
    strategy_id: r.strategy_id,
    strategy_name: r.run_name ?? r.strategy_name ?? "",
    status: r.status,
    created_at: r.created_at,
    completed_at: r.completed_at ?? r.finished_at ?? null,
    sharpe: r.sharpe ?? (r.sharpe_ratio != null ? Number(r.sharpe_ratio) : null),
    mdd: r.mdd ?? (r.max_drawdown != null ? Number(r.max_drawdown) : null),
    annual_return: r.annual_return != null ? Number(r.annual_return) : null,
  }));
}

export async function compareBacktests(runIds: string[]): Promise<{ results: BacktestResult[] }> {
  const res = await apiClient.post<{ results: BacktestResult[] }>("/backtest/compare", { run_ids: runIds });
  return res.data;
}
