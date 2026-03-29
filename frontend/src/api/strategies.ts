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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const res = await apiClient.get<any[]>("/strategies");
  return (res.data ?? []).map((d) => ({
    id: d.id ?? "",
    name: d.name ?? "",
    description: d.description,
    factor_ids: d.factor_ids ?? [],
    top_n: d.top_n ?? 15,
    rebalance_freq: d.rebalance_freq ?? "monthly",
    weight_method: d.weight_method ?? "equal",
    industry_cap: d.industry_cap ?? 0.25,
    single_stock_cap: d.single_stock_cap ?? 0.1,
    initial_capital: d.initial_capital ?? 1000000,
    created_at: d.created_at ?? "",
    updated_at: d.updated_at ?? "",
    sharpe: d.sharpe,
    mdd: d.mdd,
  }));
}

export async function getStrategy(id: string): Promise<Strategy> {
  const res = await apiClient.get<Strategy>(`/strategies/${id}`);
  return res.data;
}

export async function createStrategy(payload: StrategyCreatePayload): Promise<Strategy> {
  const res = await apiClient.post<Strategy>("/strategies", payload);
  return res.data;
}

export async function updateStrategy(id: string, payload: StrategyUpdatePayload): Promise<Strategy> {
  const res = await apiClient.put<Strategy>(`/strategies/${id}`, payload);
  return res.data;
}

export async function deleteStrategy(id: string): Promise<void> {
  await apiClient.delete(`/strategies/${id}`);
}
