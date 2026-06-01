/**
 * Risk API wrappers — MVP 5.4 iter 215 sediment.
 *
 * Adds queries for risk_event_log history with filter + pagination + chain trace
 * (sibling to existing SSE `/api/sse/risk-events` live stream).
 */

import apiClient from "./client";
import type { CircuitBreakerState } from "@/types/dashboard";

export type RiskExecutionMode = "paper" | "live" | string;
export type RiskEventSeverity = "p0" | "p1" | "p2" | "info";

export interface RiskQueryParams {
  strategy_id?: string;
  execution_mode?: RiskExecutionMode;
}

export interface RiskTransition {
  trade_date: string;
  prev_level: number;
  new_level: number;
  transition_type: string;
  reason: string | null;
  metrics: Record<string, unknown> | null;
}

export interface RiskHistoryOptions {
  execution_mode?: RiskExecutionMode;
  limit?: number;
}

export interface RiskSummaryResponse {
  current_level?: number;
  current_level_name?: string;
  days_in_current_state?: number;
  total_escalations?: number;
  total_recoveries?: number;
  last_transition_date?: string | null;
  max_level_30d?: number;
  [k: string]: unknown;
}

export interface OverviewMetric {
  label: string;
  value: string;
  color?: string;
}

export interface VarPoint {
  date: string;
  var95: number;
  var99: number;
  limit: number;
}

export interface ExposureItem {
  factor: string;
  exposure: number;
  limit: number;
  color: string;
}

export interface RawRiskOverview {
  var_95?: number | null;
  cvar_95?: number | null;
  beta?: number | null;
  volatility_annualized?: number | null;
  sharpe_60d?: number | null;
  max_drawdown?: number | null;
  circuit_level?: number | null;
  position_multiplier?: number | null;
  data_days?: number | null;
  data_sufficient?: boolean | null;
  [k: string]: unknown;
}

export interface RiskOverviewDisplay {
  metrics: OverviewMetric[];
  var_series: VarPoint[];
  exposure: ExposureItem[];
}

export type RiskLimitStatus = "ok" | "warn" | "critical";

export interface RawRiskLimit {
  name: string;
  current: number;
  limit: number;
  usage_pct: number;
  unit: string;
  status: string;
}

export interface RiskLimit {
  name: string;
  current: string;
  limit: string;
  usage: number;
  status: RiskLimitStatus;
}

export interface RawStressTest {
  scenario: string;
  period: string;
  market_drop: number;
  estimated_loss: number;
  estimated_nav: number;
  description: string;
  beta_used: number;
}

export interface StressTest {
  scenario: string;
  impact: number;
  probability: string;
  recovery: string;
}

export interface RiskEventChainPlan {
  plan_id: string | null;
  status: string | null;
  action: string | null;
  qty: number | null;
  user_decision: string | null;
  broker_order_id: string | null;
}

export interface RiskEvent {
  id: number;
  strategy_id: string;
  rule_id: string;
  severity: RiskEventSeverity | string;
  triggered_at: string;
  code: string | null;
  shares: number | null;
  reason: string;
  action_taken: string | null;
  cadence: string | null;
  priority: string | null;
  detection_latency_ms: number | null;
  chain?: RiskEventChainPlan | null;
}

export interface RiskEventsResponse {
  events: RiskEvent[];
  total_count: number;
}

export interface RiskEventsFilter {
  severity?: RiskEventSeverity | string;
  rule_id?: string;
  hours?: number;
  limit?: number;
  offset?: number;
  include_chain?: boolean;
}

export async function fetchCircuitBreakerState(
  strategyId: string,
  executionMode = "paper",
): Promise<CircuitBreakerState> {
  const { data } = await apiClient.get<CircuitBreakerState>(
    `/risk/state/${strategyId}`,
    { params: { execution_mode: executionMode } },
  );
  return data;
}

export async function forceResetCircuitBreaker(
  strategyId: string,
  reason: string,
  executionMode = "paper",
): Promise<CircuitBreakerState> {
  const { data } = await apiClient.post<CircuitBreakerState>(
    `/risk/force-reset/${strategyId}`,
    { reason },
    { params: { execution_mode: executionMode } },
  );
  return data;
}

export async function fetchRiskHistory(
  strategyId: string,
  options: RiskHistoryOptions = {},
): Promise<RiskTransition[]> {
  const { data } = await apiClient.get<RiskTransition[]>(
    `/risk/history/${strategyId}`,
    {
      params: {
        execution_mode: options.execution_mode ?? "paper",
        limit: options.limit ?? 50,
      },
    },
  );
  return data;
}

export async function fetchRiskSummary(
  strategyId: string,
  executionMode: RiskExecutionMode = "paper",
): Promise<RiskSummaryResponse> {
  const { data } = await apiClient.get<RiskSummaryResponse>(
    `/risk/summary/${strategyId}`,
    { params: { execution_mode: executionMode } },
  );
  return data;
}

export async function fetchRiskOverview(
  params: RiskQueryParams = {},
): Promise<RawRiskOverview> {
  const { data } = await apiClient.get<RawRiskOverview>("/risk/overview", {
    params: withRiskParams(params),
  });
  return data;
}

export async function fetchRiskOverviewDisplay(
  params: RiskQueryParams = {},
): Promise<RiskOverviewDisplay> {
  const raw = await fetchRiskOverview(params);
  return normalizeRiskOverview(raw);
}

export async function fetchRiskLimits(
  params: RiskQueryParams = {},
): Promise<RiskLimit[]> {
  const { data } = await apiClient.get<RawRiskLimit[]>("/risk/limits", {
    params: withRiskParams(params),
  });
  return data.map(normalizeRiskLimit);
}

export async function fetchStressTests(
  params: RiskQueryParams = {},
): Promise<StressTest[]> {
  const { data } = await apiClient.get<RawStressTest[]>("/risk/stress-tests", {
    params: withRiskParams(params),
  });
  return data.map(normalizeStressTest);
}

/**
 * Fetch filtered + paginated risk_event_log history.
 *
 * MVP 5.4 C1 (PR #520 iter 214) + C2 (this wrapper iter 215).
 */
export async function fetchRiskEvents(
  filter: RiskEventsFilter = {},
): Promise<RiskEventsResponse> {
  const params: Record<string, string | number | boolean> = {
    hours: filter.hours ?? 24,
    limit: filter.limit ?? 50,
    offset: filter.offset ?? 0,
    include_chain: filter.include_chain ?? false,
  };
  if (filter.severity) params.severity = filter.severity;
  if (filter.rule_id) params.rule_id = filter.rule_id;

  const { data } = await apiClient.get<RiskEventsResponse>("/risk/events", {
    params,
  });
  return data;
}

export interface RuleIdsResponse {
  rule_ids: string[];
  total_count: number;
}

/**
 * Fetch distinct rule_ids (90d window) for filter dropdown discovery.
 *
 * Avoids hardcoding 20+ rule_ids (PMS / CB / intraday / 10 realtime / etc).
 */
export async function fetchRuleIds(): Promise<RuleIdsResponse> {
  const { data } = await apiClient.get<RuleIdsResponse>(
    "/risk/events/rule-ids",
  );
  return data;
}

function withRiskParams(params: RiskQueryParams): Record<string, string> {
  const query: Record<string, string> = {
    execution_mode: params.execution_mode ?? "paper",
  };
  if (params.strategy_id) query.strategy_id = params.strategy_id;
  return query;
}

function normalizeRiskOverview(raw: RawRiskOverview): RiskOverviewDisplay {
  const dataDays = raw.data_days ?? 0;
  if (dataDays <= 0) {
    return {
      metrics: [],
      var_series: [],
      exposure: [],
    };
  }

  return {
    metrics: [
      { label: "VaR 95%", value: formatRatioPercent(raw.var_95) },
      { label: "CVaR 95%", value: formatRatioPercent(raw.cvar_95) },
      { label: "Beta", value: formatNumber(raw.beta) },
      {
        label: "年化波动",
        value: formatRatioPercent(raw.volatility_annualized),
      },
      { label: "60日夏普", value: formatNumber(raw.sharpe_60d) },
      { label: "最大回撤", value: formatRatioPercent(raw.max_drawdown) },
    ],
    var_series: [],
    exposure: [],
  };
}

function normalizeRiskLimit(item: RawRiskLimit): RiskLimit {
  return {
    name: item.name,
    current: formatLimitValue(item.current, item.unit),
    limit: formatLimitValue(item.limit, item.unit),
    usage: item.usage_pct,
    status: normalizeRiskLimitStatus(item.status, item.usage_pct),
  };
}

function normalizeStressTest(item: RawStressTest): StressTest {
  return {
    scenario: item.scenario,
    impact: item.estimated_loss,
    probability: "历史",
    recovery: item.period,
  };
}

function normalizeRiskLimitStatus(
  status: string,
  usagePct: number,
): RiskLimitStatus {
  if (status === "danger") return "critical";
  if (status === "warning") return "warn";
  if (status === "normal") return "ok";
  if (usagePct >= 90) return "critical";
  if (usagePct >= 70) return "warn";
  return "ok";
}

function formatLimitValue(value: number, unit: string): string {
  if (unit === "比例") return formatRatioPercent(value);
  return formatNumber(value);
}

function formatRatioPercent(value: number | null | undefined): string {
  return `${((value ?? 0) * 100).toFixed(2)}%`;
}

function formatNumber(value: number | null | undefined): string {
  if (value == null) return "0";
  if (Number.isInteger(value)) return value.toString();
  return value.toFixed(2);
}
