/**
 * Risk API wrappers — MVP 5.4 iter 215 sediment.
 *
 * Adds queries for risk_event_log history with filter + pagination + chain trace
 * (sibling to existing SSE `/api/sse/risk-events` live stream).
 */

import apiClient from "./client";
import type { CircuitBreakerState } from "@/types/dashboard";

export type RiskEventSeverity = "p0" | "p1" | "p2" | "info";

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
