import apiClient from "./client";

// ── Types ──────────────────────────────────────────────────────────────────

/**
 * Frontend Design v3 §2.1 EnvStateBanner backing.
 *
 * 来自 GET /api/system/env-state. LL-183 silent NOT-GATING UI 化, 覆盖 35 pages.
 */
export interface EnvState {
  mode: "paper" | "live";
  live_trading_disabled: boolean;
  qmt_account_id: string;
  pt_top_n: number;
  dingtalk_enabled: boolean;
  l4_auto_enabled: boolean;
  last_updated: string;
}

export interface DataSource {
  name: string;
  display_name: string;
  status: "healthy" | "warning" | "error" | "unknown";
  latest_date: string | null;
  row_count: number | null;
  last_updated: string | null;
  message?: string;
}

export interface SchedulerTask {
  name: string;
  display_name: string;
  schedule: string;
  last_run: string | null;
  last_status: "success" | "failed" | "running" | "never" | null;
  next_run: string | null;
  enabled: boolean;
}

export interface SystemHealth {
  postgres: { status: "ok" | "error"; latency_ms: number | null; message?: string };
  redis: { status: "ok" | "error"; latency_ms: number | null; message?: string };
  celery: { status: "ok" | "error"; active_workers: number; message?: string };
  disk: { used_gb: number; total_gb: number; percent: number };
  memory: { used_gb: number; total_gb: number; percent: number };
  data_freshness: { latest_kline_date: string | null; days_stale: number };
}

export interface NotificationParam {
  key: string;
  value: string;
}

// ── API calls ──────────────────────────────────────────────────────────────

export async function fetchDataSources(): Promise<DataSource[]> {
  const { data } = await apiClient.get<DataSource[]>("/system/datasources");
  return data;
}

export async function fetchSchedulerTasks(): Promise<SchedulerTask[]> {
  const { data } = await apiClient.get<SchedulerTask[]>("/system/scheduler");
  return data;
}

export async function fetchSystemHealth(): Promise<SystemHealth> {
  const { data } = await apiClient.get<SystemHealth>("/system/health");
  return data;
}

export async function fetchNotificationParams(): Promise<NotificationParam[]> {
  const { data } = await apiClient.get<NotificationParam[]>("/params", {
    params: { category: "notification" },
  });
  return data;
}

export async function saveNotificationParams(
  params: NotificationParam[],
): Promise<void> {
  // F63 fix (Phase D D3b 2026-04-16): backend has no /params/batch.
  // Loop PUT /params/{key} sequentially using existing /api/params/{key:path} endpoint.
  // 注: backend params.py:115 PUT 接受 UpdateParamRequest { value, reason, changed_by? }
  for (const p of params) {
    await apiClient.put(`/params/${p.key}`, {
      value: p.value,
      reason: "notification settings update from /system page",
    });
  }
}

export async function testNotification(webhook_url: string): Promise<{ success: boolean; message: string }> {
  const { data } = await apiClient.post("/system/test-notification", { webhook_url });
  return data;
}

/**
 * Fetch current .env critical state for top banner (LL-183 prevention).
 *
 * 5s refetch recommended (env 变化 immediate visibility).
 */
export async function fetchEnvState(): Promise<EnvState> {
  const { data } = await apiClient.get<EnvState>("/system/env-state");
  return data;
}

/**
 * Calendar info (Audit Section X §39 SSOT + Finding #7 hardcoded "PT Day X/Y" 修复).
 */
export interface PTDayCounter {
  current_day: number;
  total_days: number;
  start_date: string;
  today: string;
  completion_pct: number;
  label: string;
}

export interface CalendarInfo {
  today: string;
  today_is_trading_day: boolean | null;
  today_reason?: string;
  next_trading_day?: string;
  prev_trading_day?: string;
  pt_day_counter: PTDayCounter | null;
  error?: string;
}

export async function fetchCalendarInfo(): Promise<CalendarInfo> {
  const { data } = await apiClient.get<CalendarInfo>("/system/calendar-info");
  return data;
}

// ── Iter 39: paper_strategy_id exposure (closes iter 35 DEFAULT_STRATEGY_ID gap) ──

/** Response from GET /api/system/settings/paper-strategy-id (iter 39). */
export interface PaperStrategyIdResponse {
  paper_strategy_id: string;
  configured: boolean;
  source: "settings.PAPER_STRATEGY_ID";
}

/**
 * Fetch the backend-configured Paper Trading strategy_id.
 *
 * Closes iter 35 frontend DEFAULT_STRATEGY_ID="default-strategy" placeholder
 * gap: ReportCenter.tsx now fetches the real value on mount via this wrapper +
 * react-query cache. If configured=false, caller should handle the "no
 * default configured" case (e.g. show prompt or fall back to placeholder).
 */
export async function getPaperStrategyId(): Promise<PaperStrategyIdResponse> {
  const { data } = await apiClient.get<PaperStrategyIdResponse>(
    "/system/settings/paper-strategy-id",
  );
  return data;
}

