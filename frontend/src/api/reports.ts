/**
 * Reports API wrapper (iter 35 — consumes iter 30/31/32 backend lifecycle).
 *
 * Closes the gap where ReportCenter.tsx fired POST /reports/generate but ignored
 * the response (no task_id capture, no feedback) AND did not consume the new
 * GET /api/reports/{sid}/latest + /list endpoints from iter 30+32.
 *
 * 5 wrappers covering report page + iter 30/31/32 backend reports lifecycle:
 *   - listReportHistory: GET /api/reports/list -> backtest_run report rows
 *   - fetchReportQuickStats: GET /api/reports/quick-stats -> period aggregate stats
 *   - generateReport: POST /api/reports/generate -> AsyncResult.id from iter 30 dispatch
 *   - getLatestReport: GET /api/reports/{sid}/latest -> single most-recent JSON artifact
 *   - listStrategyReports: GET /api/reports/{sid}/list -> historical artifacts metadata
 *
 * Types mirror backend JSON shape per ADR-091/092/093 sediment.
 */

import apiClient from "./client";

// ---- Types ----

export type ReportExecutionMode = "paper" | "live";

export interface ReportHistoryItem {
  run_id: string;
  name: string;
  status: string;
  annual_return: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  total_trades: number | null;
  start_date: string | null;
  end_date: string | null;
  created_at: string | null;
}

export interface ReportPeriodStats {
  return: number;
  trade_days: number;
  avg_turnover: number;
}

export interface ReportQuickStats {
  today: ReportPeriodStats;
  week: ReportPeriodStats;
  month: ReportPeriodStats;
  year: ReportPeriodStats;
  latest_position_count: number;
  as_of: string;
}

export interface ReportQueryOptions {
  strategy_id?: string;
  execution_mode?: ReportExecutionMode;
  limit?: number;
}

export interface ReportSummary {
  days: number;
  sharpe: number;
  mdd: number;
  total_return: number;
  latest_nav: number;
}

export interface ReportLatestNav {
  trade_date: string | null;
  nav: number;
  daily_return: number;
  cumulative_return: number;
  drawdown: number;
  cash_ratio: number;
  cash: number;
  position_count: number;
  turnover: number;
  benchmark_nav: number;
}

export interface ReportTradeRow {
  trade_date: string | null;
  code: string;
  direction: string;
  quantity: number;
  fill_price: number | null;
  signal_price: number | null;
  reject_reason: string | null;
}

/** Full JSON artifact body written by `generate_performance_report` Celery task (iter 30 ADR-091). */
export interface ReportArtifact {
  schema_version: string;
  strategy_id: string;
  execution_mode: ReportExecutionMode;
  target_date_shanghai: string;
  generated_at_utc: string;
  data_available: boolean;
  summary: ReportSummary | null;
  latest_nav: ReportLatestNav | null;
  recent_trades: ReportTradeRow[];
  trades_count: number;
  /** Injected by GET /latest endpoint (NOT in task body). */
  _artifact_path?: string;
}

/** Listing row from GET /api/reports/{sid}/list (iter 32 ADR-093). */
export interface ReportListingRow {
  strategy_id: string;
  execution_mode: ReportExecutionMode;
  target_date: string;
  artifact_path: string;
  mtime_utc: string;
  summary: ReportSummary | null;
  _corrupt: boolean;
  _corrupt_reason?: string;
}

/** Response from POST /api/reports/generate (iter 30 — real Celery dispatch). */
export interface GenerateReportResponse {
  task_id: string;
  status: "dispatched";
  message: string;
  strategy_id: string;
  execution_mode: ReportExecutionMode;
}

// ---- Wrappers ----

function buildReportParams(options?: ReportQueryOptions): Record<string, string | number> {
  const params: Record<string, string | number> = {};
  if (options?.strategy_id) {
    params.strategy_id = options.strategy_id;
  }
  if (options?.execution_mode) {
    params.execution_mode = options.execution_mode;
  }
  if (options?.limit !== undefined) {
    params.limit = options.limit;
  }
  return params;
}

export async function listReportHistory(options?: ReportQueryOptions): Promise<ReportHistoryItem[]> {
  const r = await apiClient.get<ReportHistoryItem[]>("/reports/list", {
    params: buildReportParams(options),
  });
  return r.data;
}

export async function fetchReportQuickStats(options?: ReportQueryOptions): Promise<ReportQuickStats> {
  const r = await apiClient.get<ReportQuickStats>("/reports/quick-stats", {
    params: buildReportParams(options),
  });
  return r.data;
}

/**
 * Dispatch a strategy performance report Celery task.
 * Returns the real Celery AsyncResult.id (NOT a random uuid4 stub like pre-iter-30).
 */
export async function generateReport(
  strategy_id?: string,
  execution_mode: ReportExecutionMode = "paper",
): Promise<GenerateReportResponse> {
  const params: Record<string, string> = { execution_mode };
  if (strategy_id) {
    params.strategy_id = strategy_id;
  }
  const r = await apiClient.post<GenerateReportResponse>("/reports/generate", null, {
    params,
  });
  return r.data;
}

/**
 * Fetch the most-recent report artifact for a strategy.
 * 404 if no artifact exists (caller should dispatch POST /generate first).
 */
export async function getLatestReport(
  strategy_id: string,
  execution_mode: ReportExecutionMode = "paper",
): Promise<ReportArtifact> {
  const r = await apiClient.get<ReportArtifact>(`/reports/${strategy_id}/latest`, {
    params: { execution_mode },
  });
  return r.data;
}

/**
 * Enumerate historical report artifacts for a strategy.
 * Empty list 200 (not 404) when no artifacts exist.
 * Corrupt JSON entries INCLUDED with _corrupt=true marker (反 silent skip per ironlaw 33).
 */
export async function listStrategyReports(
  strategy_id: string,
  options?: { execution_mode?: ReportExecutionMode; limit?: number },
): Promise<ReportListingRow[]> {
  const params: Record<string, string | number> = {};
  if (options?.execution_mode) {
    params.execution_mode = options.execution_mode;
  }
  if (options?.limit !== undefined) {
    params.limit = options.limit;
  }
  const r = await apiClient.get<ReportListingRow[]>(`/reports/${strategy_id}/list`, {
    params,
  });
  return r.data;
}
