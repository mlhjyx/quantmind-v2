import apiClient from "./client";

// ---- Types ----

export type AgentName = "idea" | "factor" | "eval" | "diagnosis";
// L7 fix (2026-05-19): expanded to include sub-PR 8a-followup-A V4 aliases (5-07 切换)
// Legacy names kept for back-compat with existing cost log + UI labels.
export type ModelId =
  | "deepseek-r1"
  | "deepseek-v3"
  | "qwen3"
  | "deepseek-v4-flash"  // V4 chat (replaces deepseek-chat alias)
  | "deepseek-v4-pro"    // V4 reasoner (replaces deepseek-reasoner alias)
  | "qwen3-local";       // ollama fallback

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

// ---- AssistPanel chat (Frontend Design v3 §2.3) ----

export type AssistDomain =
  | "dashboard"
  | "risk"
  | "factor"
  | "execution"
  | "strategy"
  | "backtest"
  | "pipeline"
  | "general";

export interface AssistContext {
  page: AssistDomain;
  entity_id?: string;
  data_snapshot?: Record<string, unknown>;
}

export interface ChatMessageDto {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ChatRequest {
  messages: ChatMessageDto[];
  context: AssistContext;
}

export interface ChatResponse {
  reply: string;
  mode: "stub" | "live";
  cost_usd: number;
  tokens_in: number;
  tokens_out: number;
  timestamp: string;
}

export interface ChatStatus {
  enabled: boolean;
  mode: "stub" | "live";
  blocked_ops: string[];
  compose_only_ops: string[];
  direct_ops: string[];
}

export async function postChat(req: ChatRequest): Promise<ChatResponse> {
  const res = await apiClient.post<ChatResponse>("/agent/chat", req);
  return res.data;
}

export async function getChatStatus(): Promise<ChatStatus> {
  const res = await apiClient.get<ChatStatus>("/agent/chat/status");
  return res.data;
}
