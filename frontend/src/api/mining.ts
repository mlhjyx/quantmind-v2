import apiClient from "./client";

// ---- Types ----

export type MiningEngine = "gp" | "llm" | "brute";
export type TaskStatus = "idle" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type GateStatus = "pending" | "passed" | "failed";

export interface GPConfig {
  population_size: number;
  max_generations: number;
  n_islands: number;
  warm_start: boolean;
  warm_start_task_id?: string;
  mutation_rate: number;
  crossover_rate: number;
  tournament_size: number;
  max_depth: number;
}

export interface LLMConfig {
  model: "deepseek-r1" | "deepseek-v3" | "qwen3";
  mode: "free" | "directed" | "improve";
  hypothesis: string;
  n_candidates: number;
  temperature: number;
  base_factor_id?: string; // for "improve" mode
}

export interface BruteForceConfig {
  template: string;
  fields: string[];
  windows: number[];
  functions: string[];
  max_combinations: number;
}

export interface CandidateFactor {
  id: string;
  name: string;
  expression: string;
  engine: MiningEngine;
  task_id: string;
  ic_mean: number;
  t_stat: number;
  fdr_t_stat: number;
  ic_ir: number;
  coverage: number;
  gate_status: GateStatus;
  gate_score?: number;
  created_at: string;
}

export interface MiningTaskDetail {
  task_id: string;
  engine: MiningEngine;
  status: TaskStatus;
  progress: number;
  generation?: number;
  total_generations?: number;
  best_fitness?: number;
  discovered: number;
  passed: number;
  archived: number;
  started_at: string;
  completed_at?: string;
  config: GPConfig | LLMConfig | BruteForceConfig;
  candidates: CandidateFactor[];
  evolution_history?: { generation: number; best_fitness: number; avg_fitness: number }[];
}

export interface MiningTaskSummary {
  task_id: string;
  engine: MiningEngine;
  status: TaskStatus;
  progress: number;
  generation?: number;
  total_generations?: number;
  best_fitness?: number;
  discovered: number;
  passed: number;
  archived: number;
  started_at: string;
  completed_at?: string;
}

export interface EngineStats {
  engine: MiningEngine;
  total_tasks: number;
  total_discovered: number;
  total_passed: number;
  total_archived: number;
  pass_rate: number;
  archive_rate: number;
}

// ---- API calls ----

export async function startGPMining(config: GPConfig): Promise<{ task_id: string }> {
  const res = await apiClient.post<{ task_id: string }>("/factor/mine/gp", config);
  return res.data;
}

export async function startLLMMining(config: LLMConfig): Promise<{ task_id: string }> {
  const res = await apiClient.post<{ task_id: string }>("/factor/mine/llm", config);
  return res.data;
}

export async function startBruteForceMining(config: BruteForceConfig): Promise<{ task_id: string }> {
  const res = await apiClient.post<{ task_id: string }>("/factor/mine/brute", config);
  return res.data;
}

export async function getMiningTasks(): Promise<MiningTaskSummary[]> {
  const res = await apiClient.get<MiningTaskSummary[]>("/factor/tasks");
  return res.data;
}

export async function getMiningTaskDetail(taskId: string): Promise<MiningTaskDetail> {
  const res = await apiClient.get<MiningTaskDetail>(`/factor/tasks/${taskId}`);
  return res.data;
}

export async function pauseMiningTask(taskId: string): Promise<void> {
  await apiClient.post(`/factor/tasks/${taskId}/pause`);
}

export async function cancelMiningTask(taskId: string): Promise<void> {
  await apiClient.delete(`/factor/tasks/${taskId}`);
}

export async function retryMiningTask(taskId: string): Promise<{ task_id: string }> {
  const res = await apiClient.post<{ task_id: string }>(`/factor/tasks/${taskId}/retry`);
  return res.data;
}

export async function archiveMiningTask(taskId: string): Promise<void> {
  await apiClient.post(`/factor/tasks/${taskId}/archive`);
}

export async function submitCandidateToGate(candidateId: string): Promise<void> {
  await apiClient.post("/factor/evaluate/batch", { candidate_ids: [candidateId] });
}

export async function submitCandidatesToGate(candidateIds: string[]): Promise<void> {
  await apiClient.post("/factor/evaluate/batch", { candidate_ids: candidateIds });
}

export async function getEngineStats(): Promise<EngineStats[]> {
  const res = await apiClient.get<EngineStats[]>("/factor/tasks/stats");
  return res.data;
}

export async function getAvailableBruteTemplates(): Promise<string[]> {
  const res = await apiClient.get<string[]>("/factor/mine/brute/templates");
  return res.data;
}
