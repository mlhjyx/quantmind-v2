import apiClient from "./client";

// ── Types ──────────────────────────────────────────────────────────────────

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
  await apiClient.post("/params/batch", { params });
}

export async function testNotification(webhook_url: string): Promise<{ success: boolean; message: string }> {
  const { data } = await apiClient.post("/system/test-notification", { webhook_url });
  return data;
}

// ── Mock fallbacks ─────────────────────────────────────────────────────────

export const MOCK_DATASOURCES: DataSource[] = [
  {
    name: "klines_daily",
    display_name: "日K线",
    status: "healthy",
    latest_date: "2026-03-27",
    row_count: 2340000,
    last_updated: "2026-03-27T17:05:00Z",
  },
  {
    name: "factor_values",
    display_name: "因子数据",
    status: "healthy",
    latest_date: "2026-03-27",
    row_count: 138000000,
    last_updated: "2026-03-27T18:00:00Z",
  },
  {
    name: "moneyflow",
    display_name: "资金流向",
    status: "warning",
    latest_date: "2026-03-26",
    row_count: 6140000,
    last_updated: "2026-03-26T17:10:00Z",
    message: "数据延迟1天",
  },
  {
    name: "stock_basic",
    display_name: "股票基础信息",
    status: "healthy",
    latest_date: "2026-03-27",
    row_count: 5200,
    last_updated: "2026-03-27T08:00:00Z",
  },
  {
    name: "index_weights",
    display_name: "指数成分权重",
    status: "healthy",
    latest_date: "2026-03-20",
    row_count: 84000,
    last_updated: "2026-03-20T20:00:00Z",
  },
  {
    name: "fundamentals",
    display_name: "基本面数据",
    status: "error",
    latest_date: null,
    row_count: null,
    last_updated: null,
    message: "连接超时",
  },
];

export const MOCK_SCHEDULER_TASKS: SchedulerTask[] = [
  {
    name: "pt_signal",
    display_name: "PT信号生成",
    schedule: "16:30 工作日",
    last_run: "2026-03-27T16:30:05Z",
    last_status: "success",
    next_run: "2026-03-28T16:30:00Z",
    enabled: true,
  },
  {
    name: "pt_execution",
    display_name: "PT订单执行",
    schedule: "09:00 工作日",
    last_run: "2026-03-28T09:00:12Z",
    last_status: "success",
    next_run: "2026-03-29T09:00:00Z",
    enabled: true,
  },
  {
    name: "gp_weekly",
    display_name: "GP周期演化",
    schedule: "每周日 02:00",
    last_run: "2026-03-23T02:00:30Z",
    last_status: "success",
    next_run: "2026-03-30T02:00:00Z",
    enabled: true,
  },
  {
    name: "data_fetch_daily",
    display_name: "日数据拉取",
    schedule: "17:30 工作日",
    last_run: "2026-03-27T17:30:00Z",
    last_status: "success",
    next_run: "2026-03-28T17:30:00Z",
    enabled: true,
  },
  {
    name: "factor_compute",
    display_name: "因子计算",
    schedule: "18:00 工作日",
    last_run: "2026-03-27T18:02:45Z",
    last_status: "failed",
    next_run: "2026-03-28T18:00:00Z",
    enabled: true,
  },
];

export const MOCK_SYSTEM_HEALTH: SystemHealth = {
  postgres: { status: "ok", latency_ms: 3 },
  redis: { status: "ok", latency_ms: 1 },
  celery: { status: "ok", active_workers: 4 },
  disk: { used_gb: 420, total_gb: 2000, percent: 21 },
  memory: { used_gb: 18.4, total_gb: 32, percent: 57.5 },
  data_freshness: { latest_kline_date: "2026-03-27", days_stale: 0 },
};
