/**
 * Attribution API wrapper (iter 147 W2-F F6 closure).
 *
 * Backend SSOT: backend/app/api/attribution.py (created iter 147 2026-05-26)
 *   GET /api/attribution/latest?strategy_id=&execution_mode=
 *   GET /api/attribution/history?strategy_id=&execution_mode=&days=N
 *
 * Backed by DB table `daily_attribution` (migration applied iter 146).
 * Engine: backend/qm_platform/eval/attribution.py (DailyAttribution dataclass).
 * Beat task: backend/app/tasks/attribution_tasks.py (daily-attribution-compute,
 *   Mon-Fri 16:30 SH; iter 132 audit envelope wrapped + 134 double-conn fix).
 */

import apiClient from "./client";

// ─────────────────────────────────────────────────────────
// Types (mirror backend attribution.py _row_to_dict)
// ─────────────────────────────────────────────────────────

export interface RegimeInfo {
  regime_name?: string;
  probability?: number;
  expected_perf_bps?: number;
  actual_perf_bps?: number;
  [k: string]: unknown;
}

export interface AttributionRow {
  id: number;
  trade_date: string | null;
  strategy_id: string;
  execution_mode: string;
  nav_change_pct: number;
  nav_change_bps: number;
  by_factor: Record<string, number>;
  by_sector: Record<string, number>;
  by_regime: RegimeInfo | null;
  by_cost: Record<string, number>;
  alpha_vs_benchmark: number;
  alpha_vs_benchmark_bps: number;
  unexplained_residual: number;
  unexplained_residual_bps: number;
  created_at: string | null;
}

// ─────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────

/** GET /api/attribution/latest — returns most recent row OR null if no data. */
export async function getLatestAttribution(
  executionMode: "paper" | "live" = "paper",
): Promise<AttributionRow | null> {
  const { data } = await apiClient.get<AttributionRow | null>("/attribution/latest", {
    params: { execution_mode: executionMode },
  });
  return data;
}

/** GET /api/attribution/history — last N days. */
export async function getAttributionHistory(
  days = 30,
  executionMode: "paper" | "live" = "paper",
): Promise<AttributionRow[]> {
  const { data } = await apiClient.get<AttributionRow[]>("/attribution/history", {
    params: { days, execution_mode: executionMode },
  });
  return data;
}
