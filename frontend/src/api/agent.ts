import apiClient from "./client";

// ---- Types ----

export type AgentName = "idea" | "factor" | "eval" | "diagnosis";
export type ModelId = "deepseek-r1" | "deepseek-v3" | "qwen3";

export interface AgentConfig {
  name: AgentName;
  display_name: string;
  model: ModelId;
  temperature: number;
  max_tokens: number;
  system_prompt: string;
  ic_threshold: number;
  t_stat_threshold: number;
  auto_archive: boolean;
  auto_reject: boolean;
  max_daily_runs: number;
}

export interface ModelHealth {
  model: ModelId;
  is_online: boolean;
  latency_ms: number | null;
  last_checked_at: string;
  error?: string;
}

export interface TokenUsage {
  date: string;
  agent: AgentName;
  model: ModelId;
  input_tokens: number;
  output_tokens: number;
  cost_cny: number;
}

export interface CostSummary {
  month: string;
  total_cost_cny: number;
  total_input_tokens: number;
  total_output_tokens: number;
  by_agent: Record<AgentName, { cost_cny: number; tokens: number }>;
  by_model: Record<ModelId, { cost_cny: number; tokens: number }>;
  daily_usage: TokenUsage[];
}

export interface AgentLog {
  id: string;
  timestamp: string;
  agent: AgentName;
  level: "info" | "warning" | "error" | "decision";
  content: string;
  run_id?: string;
}

// ---- API calls ----

export async function getAgentConfig(name: AgentName): Promise<AgentConfig> {
  const res = await apiClient.get<AgentConfig>(`/agent/${name}/config`);
  return res.data;
}

export async function updateAgentConfig(name: AgentName, config: Partial<AgentConfig>): Promise<AgentConfig> {
  const res = await apiClient.put<AgentConfig>(`/agent/${name}/config`, config);
  return res.data;
}

export async function getAllAgentConfigs(): Promise<AgentConfig[]> {
  const agents: AgentName[] = ["idea", "factor", "eval", "diagnosis"];
  const results = await Promise.all(agents.map((a) => getAgentConfig(a)));
  return results;
}

export async function getModelHealth(): Promise<ModelHealth[]> {
  const res = await apiClient.get<ModelHealth[]>("/agent/model-health");
  return res.data;
}

export async function getCostSummary(month?: string): Promise<CostSummary> {
  const params = month ? { month } : {};
  const res = await apiClient.get<CostSummary>("/agent/cost-summary", { params });
  return res.data;
}

export async function getAgentLogs(name: AgentName, limit = 50): Promise<AgentLog[]> {
  const res = await apiClient.get<AgentLog[]>(`/agent/${name}/logs`, { params: { limit } });
  return res.data;
}

export async function resetAgentConfig(name: AgentName): Promise<AgentConfig> {
  const res = await apiClient.post<AgentConfig>(`/agent/${name}/config/reset`);
  return res.data;
}
