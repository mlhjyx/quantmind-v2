import apiClient from "./client";

// ---- Types ----

export type MiningEngine = "gp" | "llm" | "bruteforce";
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

// ---- Backend RunMiningRequest schema ----
// engine: "gp" | "bruteforce" | "llm"
// generations: int (1-500, GP only)
// population: int (10-1000, GP only)
// islands: int (1-8, GP only)
// time_budget_minutes: float (1-360)
// extra_config: dict (JSONB, engine-specific overrides)

export interface RunMiningPayload {
  engine: MiningEngine;
  generations?: number;
  population?: number;
  islands?: number;
  time_budget_minutes?: number;
  extra_config?: Record<string, unknown>;
}

// ---- Backend EvaluateFactorRequest schema ----
// factor_expr: string (DSL expression)
// factor_name?: string
// run_quick_only?: boolean

export interface EvaluateFactorPayload {
  factor_expr: string;
  factor_name?: string;
  run_quick_only?: boolean;
}

// ---- API calls ----

export async function startGPMining(config: GPConfig): Promise<{ task_id: string }> {
  const payload: RunMiningPayload = {
    engine: "gp",
    generations: config.max_generations,
    population: config.population_size,
    islands: config.n_islands,
    extra_config: {
      warm_start: config.warm_start,
      warm_start_task_id: config.warm_start_task_id,
      mutation_rate: config.mutation_rate,
      crossover_rate: config.crossover_rate,
      tournament_size: config.tournament_size,
      max_depth: config.max_depth,
    },
  };
  const res = await apiClient.post<{ task_id: string }>("/mining/run", payload);
  return res.data;
}

export async function startLLMMining(config: LLMConfig): Promise<{ task_id: string }> {
  const payload: RunMiningPayload = {
    engine: "llm",
    extra_config: { ...config },
  };
  const res = await apiClient.post<{ task_id: string }>("/mining/run", payload);
  return res.data;
}

export async function startBruteForceMining(config: BruteForceConfig): Promise<{ task_id: string }> {
  const payload: RunMiningPayload = {
    engine: "bruteforce",
    extra_config: { ...config },
  };
  const res = await apiClient.post<{ task_id: string }>("/mining/run", payload);
  return res.data;
}

export async function getMiningTasks(): Promise<MiningTaskSummary[]> {
  const res = await apiClient.get<MiningTaskSummary[]>("/mining/tasks");
  return res.data;
}

export async function getMiningTaskDetail(taskId: string): Promise<MiningTaskDetail> {
  const res = await apiClient.get<MiningTaskDetail>(`/mining/tasks/${taskId}`);
  return res.data;
}

/** 后端只有cancel端点，pause语义通过cancel实现 */
export async function pauseMiningTask(taskId: string): Promise<void> {
  await apiClient.post(`/mining/tasks/${taskId}/cancel`);
}

export async function cancelMiningTask(taskId: string): Promise<void> {
  await apiClient.post(`/mining/tasks/${taskId}/cancel`);
}

/** 重试=用相同engine重新启动 */
export async function retryMiningTask(engine: MiningEngine): Promise<{ task_id: string }> {
  const res = await apiClient.post<{ task_id: string }>("/mining/run", { engine });
  return res.data;
}

/** 后端无archive端点，用cancel替代 */
export async function archiveMiningTask(taskId: string): Promise<void> {
  await apiClient.post(`/mining/tasks/${taskId}/cancel`);
}

/** 提交单个候选因子到Gate评估 */
export async function submitCandidateToGate(factorExpr: string, factorName?: string): Promise<void> {
  const payload: EvaluateFactorPayload = { factor_expr: factorExpr, factor_name: factorName };
  await apiClient.post("/mining/evaluate", payload);
}

/** 批量提交：逐个调用evaluate */
export async function submitCandidatesToGate(candidates: { expr: string; name?: string }[]): Promise<void> {
  await Promise.all(
    candidates.map((c) =>
      apiClient.post("/mining/evaluate", { factor_expr: c.expr, factor_name: c.name } satisfies EvaluateFactorPayload)
    )
  );
}

/** 引擎统计需从task列表聚合计算（后端无专用端点） */
export async function getEngineStats(): Promise<EngineStats[]> {
  const tasks = await getMiningTasks();
  const map = new Map<MiningEngine, EngineStats>();
  for (const t of tasks) {
    let s = map.get(t.engine);
    if (!s) {
      s = { engine: t.engine, total_tasks: 0, total_discovered: 0, total_passed: 0, total_archived: 0, pass_rate: 0, archive_rate: 0 };
      map.set(t.engine, s);
    }
    s.total_tasks++;
    s.total_discovered += t.discovered;
    s.total_passed += t.passed;
    s.total_archived += t.archived;
  }
  for (const s of map.values()) {
    s.pass_rate = s.total_discovered > 0 ? s.total_passed / s.total_discovered : 0;
    s.archive_rate = s.total_passed > 0 ? s.total_archived / s.total_passed : 0;
  }
  return Array.from(map.values());
}

/** BruteForce模板列表（后端无专用端点，返回静态列表） */
export async function getAvailableBruteTemplates(): Promise<string[]> {
  // 模板列表定义在 backend/engines/mining/bruteforce_engine.py
  // 后端无API暴露，前端维护静态列表
  return [
    "ts_mean", "ts_std", "ts_delta", "ts_rank", "ts_max", "ts_min",
    "cs_rank", "cs_zscore", "cs_percentile",
    "ts_corr", "ts_cov", "ts_regression_resid",
  ];
}
