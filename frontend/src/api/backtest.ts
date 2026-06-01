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

function nullableNumber(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function numberOrZero(value: unknown): number {
  return nullableNumber(value) ?? 0;
}

function stringOrEmpty(value: unknown): string {
  return value == null ? "" : String(value);
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
    sharpe: nullableNumber(r.sharpe ?? r.sharpe_ratio),
    mdd: nullableNumber(r.mdd ?? r.max_drawdown),
    annual_return: nullableNumber(r.annual_return),
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
  const res = await apiClient.post<unknown[]>("/backtest/compare", {
    run_ids: runIds,
  });
  const rows = Array.isArray(res.data) ? res.data : [];
  return rows.map((row) => {
    const r = row as Record<string, unknown>;
    const factorList = r.factor_list;
    return {
      run_id: String(r.run_id ?? ""),
      strategy_id: r.strategy_id == null ? null : String(r.strategy_id),
      run_name: r.run_name == null ? null : String(r.run_name),
      status: String(r.status ?? ""),
      start_date: String(r.start_date ?? ""),
      end_date: String(r.end_date ?? ""),
      annual_return: nullableNumber(r.annual_return),
      sharpe_ratio: nullableNumber(r.sharpe_ratio),
      max_drawdown: nullableNumber(r.max_drawdown),
      calmar_ratio: nullableNumber(r.calmar_ratio),
      total_turnover: nullableNumber(r.total_turnover),
      win_rate: nullableNumber(r.win_rate),
      annual_turnover: nullableNumber(r.annual_turnover),
      sortino_ratio: nullableNumber(r.sortino_ratio),
      factor_list: Array.isArray(factorList)
        ? factorList.map(String)
        : typeof factorList === "string"
          ? factorList.split(",").map((v) => v.trim()).filter(Boolean)
          : [],
      config_yaml_hash: r.config_yaml_hash == null ? null : String(r.config_yaml_hash),
      git_commit: r.git_commit == null ? null : String(r.git_commit),
    };
  });
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

export type BacktestTradeSide = "buy" | "sell" | string;

export interface BacktestTradeRow {
  id: string | number;
  signal_date: string | null;
  exec_date: string | null;
  stock_code: string;
  side: BacktestTradeSide;
  shares: number;
  target_price: number | null;
  exec_price: number | null;
  slippage_bps: number | null;
  commission: number | null;
  stamp_tax: number | null;
  transfer_fee: number | null;
  total_cost: number | null;
  reject_reason: string | null;
}

export interface BacktestTradesResponse {
  total: number;
  page: number;
  page_size: number;
  items: BacktestTradeRow[];
}

export interface BacktestTradesParams {
  page?: number;
  pageSize?: number;
  stockCode?: string;
  side?: BacktestTradeSide;
}

export interface BacktestAnnualRow {
  year: number;
  annual_return: number | null;
  sharpe_ratio: number | null;
  trading_days: number;
  worst_day: number | null;
}

export interface BacktestHoldingSummaryRow {
  trade_date: string;
  holding_count: number;
  total_market_value: number | null;
}

export interface BacktestHoldingDetailRow {
  trade_date: string;
  stock_code: string;
  shares: number;
  cost_basis: number | null;
  market_price: number | null;
  market_value: number | null;
  weight: number | null;
  pnl: number | null;
  buy_date: string | null;
  industry_code: string | null;
}

export interface BacktestAttributionIndustry {
  industry: string;
  stock_count: number;
  total_weight: number | null;
  avg_pnl: number | null;
}

export interface BacktestAttributionResponse {
  run_id: string | null;
  method: string;
  note: string | null;
  industries: BacktestAttributionIndustry[];
}

export interface BacktestMarketStateRow {
  market_state: string;
  trading_days: number;
  avg_daily_return: number | null;
  std_daily_return: number | null;
  cumulative_return: number | null;
  worst_day: number | null;
  best_day: number | null;
  sharpe_estimate: number | null;
}

export interface BacktestMarketStateResponse {
  run_id: string | null;
  method: string;
  states: BacktestMarketStateRow[];
}

export interface BacktestCostSensitivityRow {
  cost_multiplier: number;
  label: string | null;
  annual_return: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  calmar_ratio: number | null;
}

export interface BacktestCostSensitivityResponse {
  run_id: string | null;
  total_cost_base: number | null;
  trade_count: number;
  rows: BacktestCostSensitivityRow[];
  warning: string | null;
}

export interface BacktestLiveCompareMetrics {
  annual_return: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
}

export interface BacktestLiveCompareResponse {
  run_id: string | null;
  backtest: BacktestLiveCompareMetrics;
  live: BacktestLiveCompareMetrics | null;
  note: string | null;
}

/** Fetch full NAV series for a single backtest run (used by BacktestCompare S3/S4). */
export async function getNavSeries(runId: string): Promise<BacktestNavPoint[]> {
  const res = await apiClient.get<BacktestNavPoint[]>(
    `/backtest/${runId}/nav`,
  );
  return res.data;
}

/** Fetch paged trade rows for a single backtest run (used by BacktestCompare S5). */
export async function getBacktestTrades(
  runId: string,
  params: BacktestTradesParams = {},
): Promise<BacktestTradesResponse> {
  const requestParams: Record<string, string | number> = {
    page: params.page ?? 1,
    page_size: params.pageSize ?? 100,
  };
  if (params.stockCode) requestParams.stock_code = params.stockCode;
  if (params.side) requestParams.side = params.side;

  const res = await apiClient.get<BacktestTradesResponse>(
    `/backtest/${runId}/trades`,
    { params: requestParams },
  );
  return res.data;
}

export async function getBacktestMonthlyReturns(runId: string): Promise<MonthlyReturn[]> {
  const res = await apiClient.get<unknown[]>(`/backtest/${runId}/monthly`);
  return (Array.isArray(res.data) ? res.data : []).map((row) => {
    const r = row as Record<string, unknown>;
    return {
      year: Number(r.year),
      month: Number(r.month),
      return: numberOrZero(r.monthly_return),
    };
  });
}

export async function getBacktestHoldingSummary(
  runId: string,
): Promise<BacktestHoldingSummaryRow[]> {
  const res = await apiClient.get<unknown[]>(`/backtest/${runId}/holdings`);
  return (Array.isArray(res.data) ? res.data : []).map((row) => {
    const r = row as Record<string, unknown>;
    return {
      trade_date: stringOrEmpty(r.trade_date),
      holding_count: Number(r.holding_count ?? 0),
      total_market_value: nullableNumber(r.total_market_value),
    };
  });
}

export async function getBacktestHoldingDetails(
  runId: string,
  tradeDate: string,
): Promise<BacktestHoldingDetailRow[]> {
  const res = await apiClient.get<unknown[]>(`/backtest/${runId}/holdings`, {
    params: { trade_date: tradeDate },
  });
  return (Array.isArray(res.data) ? res.data : []).map((row) => {
    const r = row as Record<string, unknown>;
    return {
      trade_date: stringOrEmpty(r.trade_date),
      stock_code: stringOrEmpty(r.stock_code),
      shares: numberOrZero(r.shares),
      cost_basis: nullableNumber(r.cost_basis),
      market_price: nullableNumber(r.market_price),
      market_value: nullableNumber(r.market_value),
      weight: nullableNumber(r.weight),
      pnl: nullableNumber(r.pnl),
      buy_date: r.buy_date == null ? null : String(r.buy_date),
      industry_code: r.industry_code == null ? null : String(r.industry_code),
    };
  });
}

export async function getBacktestLatestHoldings(runId: string): Promise<Holding[]> {
  const summary = await getBacktestHoldingSummary(runId);
  const latestDate = summary.reduce<string | null>((latest, row) => {
    if (!row.trade_date) return latest;
    return latest == null || row.trade_date > latest ? row.trade_date : latest;
  }, null);
  if (!latestDate) return [];

  const details = await getBacktestHoldingDetails(runId, latestDate);
  return details.map((row) => {
    const marketValue = row.market_value ?? 0;
    const pnl = row.pnl ?? 0;
    return {
      symbol: row.stock_code,
      name: row.stock_code,
      industry: row.industry_code ?? "unknown",
      weight: row.weight ?? 0,
      return: marketValue !== 0 ? pnl / Math.abs(marketValue) : 0,
    };
  });
}

export async function getBacktestTradesForResult(runId: string): Promise<Trade[]> {
  const response = await getBacktestTrades(runId, { page: 1, pageSize: 1000 });
  return response.items.map((row) => {
    const price = nullableNumber(row.exec_price) ?? nullableNumber(row.target_price) ?? 0;
    const quantity = numberOrZero(row.shares);
    const commission =
      nullableNumber(row.total_cost) ??
      (numberOrZero(row.commission) + numberOrZero(row.stamp_tax) + numberOrZero(row.transfer_fee));
    return {
      date: row.exec_date ?? row.signal_date ?? "",
      symbol: row.stock_code,
      name: row.stock_code,
      direction: row.side === "sell" ? "sell" : "buy",
      price,
      quantity,
      amount: price * quantity,
      commission,
      slippage: numberOrZero(row.slippage_bps),
      pnl: null,
    };
  });
}

export async function getBacktestAnnualRows(runId: string): Promise<BacktestAnnualRow[]> {
  const res = await apiClient.get<unknown[]>(`/backtest/${runId}/annual`);
  return (Array.isArray(res.data) ? res.data : []).map((row) => {
    const r = row as Record<string, unknown>;
    return {
      year: Number(r.year),
      annual_return: nullableNumber(r.annual_return),
      sharpe_ratio: nullableNumber(r.sharpe_ratio),
      trading_days: Number(r.trading_days ?? 0),
      worst_day: nullableNumber(r.worst_day),
    };
  });
}

export async function getBacktestAnnualRiskMetrics(runId: string): Promise<RiskMetric[]> {
  const rows = await getBacktestAnnualRows(runId);
  return rows.flatMap((row) => [
    { label: "年度收益", value: row.annual_return ?? 0, unit: "%" },
    { label: "年度Sharpe", value: row.sharpe_ratio ?? 0, unit: "" },
    { label: "最差单日", value: row.worst_day ?? 0, unit: "%" },
    { label: "交易日", value: row.trading_days, unit: "日" },
  ]);
}

export async function getBacktestAttribution(
  runId: string,
): Promise<BacktestAttributionResponse> {
  const res = await apiClient.get<Record<string, unknown>>(`/backtest/${runId}/attribution`);
  const data = res.data ?? {};
  const industries = Array.isArray(data.industries) ? data.industries : [];
  return {
    run_id: data.run_id == null ? null : String(data.run_id),
    method: String(data.method ?? ""),
    note: data.note == null ? null : String(data.note),
    industries: industries.map((row) => {
      const r = row as Record<string, unknown>;
      return {
        industry: String(r.industry ?? "unknown"),
        stock_count: Number(r.stock_count ?? 0),
        total_weight: nullableNumber(r.total_weight),
        avg_pnl: nullableNumber(r.avg_pnl),
      };
    }),
  };
}

export async function getBacktestCostSensitivity(
  runId: string,
): Promise<BacktestCostSensitivityResponse> {
  const res = await apiClient.get<Record<string, unknown>>(`/backtest/${runId}/cost-sensitivity`);
  const data = res.data ?? {};
  const rows = Array.isArray(data.rows) ? data.rows : [];
  return {
    run_id: data.run_id == null ? null : String(data.run_id),
    total_cost_base: nullableNumber(data.total_cost_base),
    trade_count: Number(data.trade_count ?? 0),
    rows: rows.map((row) => {
      const r = row as Record<string, unknown>;
      return {
        cost_multiplier: numberOrZero(r.cost_multiplier),
        label: r.label == null ? null : String(r.label),
        annual_return: nullableNumber(r.annual_return),
        sharpe_ratio: nullableNumber(r.sharpe_ratio),
        max_drawdown: nullableNumber(r.max_drawdown),
        calmar_ratio: nullableNumber(r.calmar_ratio),
      };
    }),
    warning: data.warning == null ? null : String(data.warning),
  };
}

export async function getBacktestMarketState(
  runId: string,
): Promise<BacktestMarketStateResponse> {
  const res = await apiClient.get<Record<string, unknown>>(`/backtest/${runId}/market-state`);
  const data = res.data ?? {};
  const states = Array.isArray(data.states) ? data.states : [];
  return {
    run_id: data.run_id == null ? null : String(data.run_id),
    method: String(data.method ?? ""),
    states: states.map((row) => {
      const r = row as Record<string, unknown>;
      return {
        market_state: String(r.market_state ?? "unknown"),
        trading_days: Number(r.trading_days ?? 0),
        avg_daily_return: nullableNumber(r.avg_daily_return),
        std_daily_return: nullableNumber(r.std_daily_return),
        cumulative_return: nullableNumber(r.cumulative_return),
        worst_day: nullableNumber(r.worst_day),
        best_day: nullableNumber(r.best_day),
        sharpe_estimate: nullableNumber(r.sharpe_estimate),
      };
    }),
  };
}

function normalizeLiveMetrics(value: unknown): BacktestLiveCompareMetrics | null {
  if (value == null || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  return {
    annual_return: nullableNumber(row.annual_return),
    sharpe_ratio: nullableNumber(row.sharpe_ratio),
    max_drawdown: nullableNumber(row.max_drawdown),
  };
}

export async function getBacktestLiveCompare(
  runId: string,
): Promise<BacktestLiveCompareResponse> {
  const res = await apiClient.get<Record<string, unknown>>(`/backtest/${runId}/live-compare`);
  const data = res.data ?? {};
  return {
    run_id: data.run_id == null ? null : String(data.run_id),
    backtest: normalizeLiveMetrics(data.backtest) ?? {
      annual_return: null,
      sharpe_ratio: null,
      max_drawdown: null,
    },
    live: normalizeLiveMetrics(data.live),
    note: data.note == null ? null : String(data.note),
  };
}

export function getBacktestReportUrl(runId: string): string {
  const baseURL = String(apiClient.defaults.baseURL ?? "/api").replace(/\/$/, "");
  return `${baseURL}/backtest/${runId}/report`;
}
