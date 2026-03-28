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
  const res = await apiClient.get<BacktestResult>(`/backtest/${runId}/result`);
  return res.data;
}

export async function cancelBacktest(runId: string): Promise<void> {
  await apiClient.post(`/backtest/${runId}/cancel`);
}

export async function listBacktestHistory(strategyId?: string): Promise<BacktestHistoryItem[]> {
  const params = strategyId ? { strategy_id: strategyId } : {};
  const res = await apiClient.get<BacktestHistoryItem[]>("/backtest/history", { params });
  return res.data;
}

export async function compareBacktests(runIds: string[]): Promise<{ results: BacktestResult[] }> {
  const res = await apiClient.post<{ results: BacktestResult[] }>("/backtest/compare", { run_ids: runIds });
  return res.data;
}
