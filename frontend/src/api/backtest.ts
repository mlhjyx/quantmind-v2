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
  start_date: string;
  end_date: string;
  initial_capital?: number;
  benchmark?: string;
  universe_preset?: string;
  rebalance_freq?: "daily" | "weekly" | "biweekly" | "monthly";
  slippage_model?: "fixed" | "volume_impact";
  cost_multiplier?: number;
  extra_config?: Record<string, unknown>;
}

export interface BacktestConfigFormPayload {
  strategy_id?: string;
  initial_capital?: number;
  market: {
    market: string;
    universe: string;
    industries: string[];
    custom_stocks: string;
  };
  time_range: {
    start_date: string;
    end_date: string;
    preset: string;
    exclude_2015: boolean;
    exclude_2020: boolean;
    exclude_custom: string;
    market_regime_analysis: boolean;
    regime_method: string;
  };
  execution: {
    fill_price: string;
    rebalance_freq: "daily" | "weekly" | "monthly" | "custom";
    signal_day: string;
    holding_count: number;
    weight_method: string;
  };
  cost_model: {
    commission_rate: number;
    stamp_tax: number;
    transfer_fee: number;
    slippage_model: "fixed" | "volume_impact" | "none";
    slippage_bps: number;
    volume_impact_coeff: number;
    max_volume_pct: number;
  };
  risk_advanced: object;
  dynamic_position: object;
}

export interface RunBacktestResponse {
  run_id: string;
  status: BacktestStatus;
  message?: string;
}

export function buildRunBacktestPayload(form: BacktestConfigFormPayload): RunBacktestPayload {
  const rebalanceFreq =
    form.execution.rebalance_freq === "custom" ? "monthly" : form.execution.rebalance_freq;
  const slippageModel =
    form.cost_model.slippage_model === "none" ? "fixed" : form.cost_model.slippage_model;

  return {
    strategy_id: form.strategy_id || "manual_ui_backtest",
    start_date: form.time_range.start_date,
    end_date: form.time_range.end_date,
    initial_capital: form.initial_capital ?? 1_000_000,
    benchmark: "000300.SH",
    universe_preset: form.market.universe,
    rebalance_freq: rebalanceFreq,
    slippage_model: slippageModel,
    cost_multiplier: 1,
    extra_config: {
      market: form.market.market,
      industries: form.market.industries,
      custom_stocks: form.market.custom_stocks,
      time_range: form.time_range,
      fill_price: form.execution.fill_price,
      holding_count: form.execution.holding_count,
      top_n: form.execution.holding_count,
      weight_method: form.execution.weight_method,
      custom_rebalance_rule:
        form.execution.rebalance_freq === "custom" ? form.execution.signal_day : undefined,
      commission_rate: form.cost_model.commission_rate,
      stamp_tax: form.cost_model.stamp_tax,
      transfer_fee: form.cost_model.transfer_fee,
      slippage_bps: form.cost_model.slippage_bps,
      volume_impact_coeff: form.cost_model.volume_impact_coeff,
      max_volume_pct: form.cost_model.max_volume_pct,
      slippage_disabled: form.cost_model.slippage_model === "none",
      risk_advanced: form.risk_advanced,
      dynamic_position: form.dynamic_position,
    },
  };
}

// ---- API Functions ----

export async function runBacktest(payload: RunBacktestPayload): Promise<RunBacktestResponse> {
  const res = await apiClient.post<RunBacktestResponse>("/backtest/run", payload);
  return res.data;
}

export async function getBacktestProgress(runId: string): Promise<BacktestProgress> {
  // F63-P2-1: /backtest/{id}/progress → adapt from /backtest/{id} (BacktestStatusResponse)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const res = await apiClient.get<any>(`/backtest/${runId}`);
  const d = res.data;
  return {
    run_id: d.run_id,
    status: d.status,
    progress: d.progress != null ? d.progress * 100 : (d.status === "completed" ? 100 : 0),
    elapsed_seconds: 0,
    estimated_remaining_seconds: null,
    current_window: undefined,
    logs: [],
  };
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

// ── iter 207 MVP 5.3 C2: BacktestCompare page wrappers ──────────────────────

/**
 * Single run summary from POST /api/backtest/compare (iter 206 PR #516 extended).
 *
 * Includes reproducibility seal (config_yaml_hash + git_commit per 铁律 15) +
 * factor_list + annual_turnover + sortino_ratio.
 */
export interface CompareRunSummary {
  run_id: string;
  strategy_id: string | null;
  run_name: string | null;
  status: string;
  start_date: string;
  end_date: string;
  annual_return: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  calmar_ratio: number | null;
  total_turnover: number | null;
  win_rate: number | null;
  // iter 206 PR #516 additions
  annual_turnover: number | null;
  sortino_ratio: number | null;
  factor_list: string[];
  config_yaml_hash: string | null;
  git_commit: string | null;
}

/**
 * Fetch side-by-side summary for 2-3 backtest runs.
 *
 * iter 206 PR #516: backend returns plain list (not wrapped). Wrapper returns
 * normalized typed list for BacktestCompare page consumption.
 */
export async function compareBacktests(runIds: string[]): Promise<CompareRunSummary[]> {
  const res = await apiClient.post<CompareRunSummary[]>("/backtest/compare", {
    run_ids: runIds,
  });
  return res.data;
}

export interface BacktestNavPoint {
  trade_date: string;
  nav: number;
  cash: number;
  market_value: number;
  daily_return: number | null;
  benchmark_nav: number | null;
  excess_return: number | null;
  drawdown: number | null;
}

/** Fetch full NAV series for a single backtest run (used by BacktestCompare S3/S4). */
export async function getNavSeries(runId: string): Promise<BacktestNavPoint[]> {
  const res = await apiClient.get<BacktestNavPoint[]>(
    `/backtest/${runId}/nav`,
  );
  return res.data;
}
