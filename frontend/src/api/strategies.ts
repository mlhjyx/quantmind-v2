import apiClient from "./client";

export interface Factor {
  id: string;
  name: string;
  category: string;
  ic: number;
  ir: number;
  direction: 1 | -1;
  recommended_freq: string;
  description?: string;
}

export interface Strategy {
  id: string;
  name: string;
  description?: string;
  factor_ids: string[];
  top_n: number;
  rebalance_freq: "daily" | "weekly" | "monthly";
  weight_method: "equal" | "ic_weighted" | "custom";
  industry_cap: number;
  single_stock_cap: number;
  initial_capital: number;
  created_at: string;
  updated_at: string;
  sharpe?: number;
  mdd?: number;
}

export interface StrategyCreatePayload {
  name: string;
  description?: string;
  factor_ids: string[];
  top_n: number;
  rebalance_freq: "daily" | "weekly" | "monthly";
  weight_method: "equal" | "ic_weighted" | "custom";
  industry_cap: number;
  single_stock_cap: number;
  initial_capital: number;
}

export type StrategyUpdatePayload = Partial<StrategyCreatePayload>;

export async function listStrategies(): Promise<Strategy[]> {
  const res = await apiClient.get<Strategy[]>("/strategy");
  return res.data;
}

export async function getStrategy(id: string): Promise<Strategy> {
  const res = await apiClient.get<Strategy>(`/strategy/${id}`);
  return res.data;
}

export async function createStrategy(payload: StrategyCreatePayload): Promise<Strategy> {
  const res = await apiClient.post<Strategy>("/strategy", payload);
  return res.data;
}

export async function updateStrategy(id: string, payload: StrategyUpdatePayload): Promise<Strategy> {
  const res = await apiClient.put<Strategy>(`/strategy/${id}`, payload);
  return res.data;
}

export async function deleteStrategy(id: string): Promise<void> {
  await apiClient.delete(`/strategy/${id}`);
}
