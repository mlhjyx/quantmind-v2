/**
 * Execution Operations API — QMT交互操作前端接口。
 */
import apiClient from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QMTStatus {
  execution_mode: string;
  state: string;
  account_id: string | null;
  qmt_path: string | null;
  connected_at: string | null;
  last_error: string | null;
  is_healthy: boolean;
  account_asset?: {
    total_asset: number;
    cash: number;
    market_value: number;
  };
  probe_error?: string;
}

export interface Position {
  code: string;
  name?: string;
  volume: number;
  can_use_volume: number;
  avg_price: number;
  market_value: number;
  frozen_volume: number;
}

export interface Asset {
  total_asset: number;
  cash: number;
  frozen_cash: number;
  market_value: number;
  source: string;
}

export interface Order {
  order_id: number;
  code: string;
  order_type: number;
  volume: number;
  price: number;
  traded_volume: number;
  traded_price: number;
  status: number;
  remark: string;
}

export interface Trade {
  order_id: number;
  code: string;
  price: number;
  volume: number;
  amount: number;
  order_type: number;
}

export interface DriftItem {
  code: string;
  name: string;
  target_weight: number;
  target_value: number;
  actual_volume: number;
  can_use_volume: number;
  actual_value: number;
  deviation_pct: number;
  status: "normal" | "overbought" | "missing" | "underweight";
}

export interface FundingAnalysis {
  overbought_release: number;
  missing_need: number;
  total_available_after_sell: number;
  missing_count: number;
  can_buy_count: number;
  funding_gap: number;
}

export interface DriftResult {
  signal_date: string | null;
  total_asset: number;
  available_cash: number;
  items: DriftItem[];
  funding_analysis: FundingAnalysis;
  summary: {
    total: number;
    normal: number;
    overbought: number;
    missing: number;
    underweight: number;
  };
}

export interface DriftFixPreview {
  sell_plan: Array<{
    code: string;
    name: string;
    action: string;
    volume: number;
    estimated_amount: number;
    reason: string;
  }>;
  buy_plan: Array<{
    code: string;
    name: string;
    action: string;
    target_value: number;
    reason: string;
  }>;
  sell_total_release: number;
  buy_total_need: number;
  funding: FundingAnalysis;
  feasible: boolean;
}

export interface AuditLogItem {
  id: number;
  timestamp: string | null;
  action: string;
  params: Record<string, unknown> | null;
  result: string;
  detail: string;
  ip: string;
}

// ---------------------------------------------------------------------------
// Admin token helper
// ---------------------------------------------------------------------------

const ADMIN_TOKEN_KEY = "admin_token";

export function getAdminToken(): string {
  return localStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
}

export function setAdminToken(token: string): void {
  localStorage.setItem(ADMIN_TOKEN_KEY, token);
}

function authHeaders(): Record<string, string> {
  const token = getAdminToken();
  return token ? { "X-Admin-Token": token } : {};
}

// ---------------------------------------------------------------------------
// GET endpoints
// ---------------------------------------------------------------------------

export async function getQMTStatus(): Promise<QMTStatus> {
  const { data } = await apiClient.get<QMTStatus>("/execution/qmt-status");
  return data;
}

export async function getPositions(): Promise<Position[]> {
  const { data } = await apiClient.get<Position[]>("/execution/positions");
  return data;
}

export async function getAsset(): Promise<Asset> {
  const { data } = await apiClient.get<Asset>("/execution/asset");
  return data;
}

export async function getOrders(): Promise<Order[]> {
  const { data } = await apiClient.get<Order[]>("/execution/orders");
  return data;
}

export async function getTrades(): Promise<Trade[]> {
  const { data } = await apiClient.get<Trade[]>("/execution/trades");
  return data;
}

export async function getDrift(): Promise<DriftResult> {
  const { data } = await apiClient.get<DriftResult>("/execution/drift");
  return data;
}

export async function getTradingPaused(): Promise<boolean> {
  const { data } = await apiClient.get<{ paused: boolean }>("/execution/trading-paused");
  return data.paused;
}

export async function getAuditLog(limit = 50): Promise<AuditLogItem[]> {
  const { data } = await apiClient.get<AuditLogItem[]>("/execution/audit-log", {
    params: { limit },
  });
  return data;
}

// ---------------------------------------------------------------------------
// POST endpoints (require admin token)
// ---------------------------------------------------------------------------

export async function cancelAllOrders(): Promise<{ cancelled: number; total_pending: number }> {
  const { data } = await apiClient.post("/execution/cancel-all", null, {
    headers: authHeaders(),
  });
  return data;
}

export async function cancelOrder(orderId: number): Promise<{ order_id: number; result: string }> {
  const { data } = await apiClient.post(`/execution/cancel/${orderId}`, null, {
    headers: authHeaders(),
  });
  return data;
}

export async function fixDriftPreview(): Promise<DriftFixPreview> {
  const { data } = await apiClient.post("/execution/fix-drift/preview", null, {
    headers: authHeaders(),
  });
  return data;
}

export async function fixDriftExecute(
  sellCodes?: string[],
  buyCodes?: string[],
): Promise<{ results: Array<Record<string, unknown>>; sell_count: number; buy_count: number }> {
  const { data } = await apiClient.post(
    "/execution/fix-drift/execute",
    { confirmation: "CONFIRM", sell_codes: sellCodes ?? [], buy_codes: buyCodes ?? [] },
    { headers: authHeaders() },
  );
  return data;
}

export async function triggerRebalance(): Promise<{ status: string; message: string }> {
  const { data } = await apiClient.post("/execution/trigger-rebalance", null, {
    headers: authHeaders(),
  });
  return data;
}

export async function emergencyLiquidate(): Promise<{
  results: Array<Record<string, unknown>>;
  position_count: number;
}> {
  const { data } = await apiClient.post(
    "/execution/emergency-liquidate",
    { confirmation: "CONFIRM" },
    { headers: authHeaders() },
  );
  return data;
}

export async function pauseTrading(): Promise<{ paused: boolean }> {
  const { data } = await apiClient.post("/execution/pause-trading", null, {
    headers: authHeaders(),
  });
  return data;
}

export async function resumeTrading(): Promise<{ paused: boolean }> {
  const { data } = await apiClient.post("/execution/resume-trading", null, {
    headers: authHeaders(),
  });
  return data;
}
