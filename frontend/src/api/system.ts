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
  last_status: "success" | "failed" | "running" | "never" | "disabled" | "alert" | null;
  next_run: string | null;
  enabled: boolean;
  task_state?: string;
  last_result_code?: number | null;
}

/**
 * iter 198 §v9.49 finding: TYPE DRIFT — backend `system.py:get_system_health` returns
 * keys `pg/redis/celery/disk/memory` with `ok: boolean` shape (lines 324-331), but
 * legacy frontend type used `postgres/redis/celery` with `status: "ok"|"error"`.
 * Existing callers (SystemSettings.tsx:434-436, IndustryAndSystem.tsx:16) used
 * `health.postgres ?? { ok: false }` fallback — silent bug showing "always down".
 *
 * Extended interface adds actual backend keys (`pg/redis/celery/disk/memory` with
 * `ok: boolean`) alongside legacy `postgres/redis/celery` aliases for backward
 * compat. Future iter: deprecate legacy aliases + update SystemSettings + IndustryAndSystem.
 *
 * 关联: 铁律 25 (改什么读什么 — actual backend response shape vs type definition).
 */
export interface SystemHealth {
  // Backend actual response shape (iter 198 fix). status?: optional legacy field for
  // callers (IndustryAndSystem.tsx:26-27 + SystemSettings.tsx:458-462) — never populated
  // by backend but kept for type-compat until separate cleanup iter.
  pg?: { ok: boolean; status?: "ok" | "error"; latency_ms?: number | null; message?: string };
  redis?: { ok: boolean; status?: "ok" | "error"; latency_ms?: number | null; message?: string };
  celery?: { ok: boolean; status?: "ok" | "error"; active_workers?: number; message?: string };
  disk?: { ok: boolean; used_gb?: number; total_gb?: number; percent: number; message?: string };
  memory?: { ok: boolean; used_gb?: number; total_gb?: number; percent: number; message?: string };
  overall_status?: "ok" | "degraded" | "critical";
  // Legacy aliases (DEPRECATED — sustained for SystemSettings.tsx + IndustryAndSystem.tsx
  // until separate cleanup iter)
  postgres?: { ok?: boolean; status?: "ok" | "error"; latency_ms: number | null; message?: string };
  data_freshness?: { latest_kline_date: string | null; days_stale: number };
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

/**
 * iter 210 MVP 5.5 C1 §v9.49 finding #11 fix: backend returns
 * `{platform, task_count, tasks: [...]}` object, NOT a plain array.
 * Previous wrapper typed as `SchedulerTask[]` directly → SystemSettings
 * SchedulerTab silently rendered empty (Array.isArray(object) = false).
 *
 * Sibling iter 198 SystemHealth type drift pattern.
 */
interface SchedulerResponseRaw {
  platform: string;
  task_count: number;
  tasks: Array<{
    task_name: string;
    schedule: string;
    last_run: string | null;
    next_run: string | null;
    status: string;
    task_state?: string;
    enabled?: boolean;
    last_result_code: number | null;
  }>;
}

function normalizeSchedulerStatus(status: string): SchedulerTask["last_status"] {
  if (status === "never_run") return "never";
  if (["success", "failed", "running", "never", "disabled", "alert"].includes(status)) {
    return status as SchedulerTask["last_status"];
  }
  return null;
}

export async function fetchSchedulerTasks(): Promise<SchedulerTask[]> {
  const { data } = await apiClient.get<SchedulerResponseRaw>("/system/scheduler");
  // Map raw backend shape to SchedulerTask interface
  return (data?.tasks ?? []).map((t) => ({
    name: t.task_name,
    display_name: t.task_name.replace(/^QM-?/, ""), // strip QM- prefix for display
    schedule: t.schedule || "",
    last_run: t.last_run,
    last_status: normalizeSchedulerStatus(t.status),
    next_run: t.next_run,
    enabled: t.enabled ?? t.task_state?.toLowerCase() !== "disabled",
    task_state: t.task_state,
    last_result_code: t.last_result_code,
  }));
}

// ── iter 210 MVP 5.5 C1: Celery Beat schedule introspection ────────────────

export interface BeatScheduleEntry {
  beat_key: string;
  task_name: string;
  schedule_display: string;
  expires_sec: number | null;
  queue: string | null;
  last_fire_time: string | null;
  last_fire_status: string | null;
}

export interface BeatScheduleResponse {
  entries: BeatScheduleEntry[];
  total_count: number;
}

export async function fetchBeatSchedule(): Promise<BeatScheduleResponse> {
  const { data } = await apiClient.get<BeatScheduleResponse>("/system/beat-schedule");
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

// ── iter 198 MVP 5.1 C4: scheduler_task_log API wrapper ────────────────────

/** Single scheduler_task_log row (matches backend system.py:get_scheduler_task_log). */
export interface SchedulerTaskLogEntry {
  id: string;
  task_name: string;
  status: "success" | "failed" | "running" | "skipped";
  schedule_time: string;
  start_time: string | null;
  end_time: string | null;
  duration_sec: number | null;
  error_message: string | null;
}

export interface SchedulerTaskLogResponse {
  tasks: SchedulerTaskLogEntry[];
  total_count: number;
}

/**
 * Fetch recent scheduler_task_log rows for PtStatus page S5 section.
 *
 * MVP 5.1 C1 (PR #511 iter 197) + C4 (this wrapper iter 198).
 * Index-optimized via idx_scheduler_log_date (schedule_time DESC).
 *
 * @param limit max rows (default 20, backend clamps to [1, 100])
 * @param taskName optional exact-match filter
 */
export async function fetchSchedulerTaskLog(
  limit = 20,
  taskName?: string,
): Promise<SchedulerTaskLogResponse> {
  const params: Record<string, string | number> = { limit };
  if (taskName) params.task_name = taskName;
  const { data } = await apiClient.get<SchedulerTaskLogResponse>(
    "/system/scheduler-task-log",
    { params },
  );
  return data;
}

