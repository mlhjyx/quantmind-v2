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

type RawObject = Record<string, unknown>;

function asObject(value: unknown): RawObject {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as RawObject) : {};
}

function firstDefined(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined && value !== null);
}

function toStringValue(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function toOptionalString(value: unknown): string | undefined {
  const text = toStringValue(value).trim();
  return text.length > 0 ? text : undefined;
}

function toNumberValue(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function toOptionalNumber(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

function normalizeEngine(value: unknown): MiningEngine {
  const engine = toStringValue(value).toLowerCase();
  if (engine === "gp" || engine === "llm" || engine === "bruteforce") return engine;
  return "gp";
}

function normalizeTaskStatus(value: unknown): TaskStatus {
  const status = toStringValue(value).toLowerCase();
  if (
    status === "idle" ||
    status === "running" ||
    status === "paused" ||
    status === "completed" ||
    status === "failed" ||
    status === "cancelled"
  ) {
    return status;
  }
  if (status === "timeout" || status === "error") return "failed";
  return "idle";
}

function normalizeGateStatus(value: unknown): GateStatus {
  const status = toStringValue(value).toLowerCase();
  if (["passed", "pass", "approved", "accepted", "archived"].includes(status)) return "passed";
  if (["failed", "fail", "rejected", "reject", "invalid"].includes(status)) return "failed";
  return "pending";
}

function gateData(gates: RawObject, gateName: string): RawObject {
  return asObject(asObject(gates[gateName]).data);
}

function gateMetric(gates: RawObject, gateName: string, ...keys: string[]): unknown {
  const gate = asObject(gates[gateName]);
  const data = asObject(gate.data);
  const candidates = keys.flatMap((key) => [data[key], gate[key]]);
  return firstDefined(...candidates, gate.metric_value);
}

function normalizeProgress(value: unknown, generation?: number, totalGenerations?: number): number {
  let progress = toOptionalNumber(value);
  if (progress === undefined && generation !== undefined && totalGenerations && totalGenerations > 0) {
    progress = (generation / totalGenerations) * 100;
  }
  if (progress === undefined) return 0;
  const percent = progress > 0 && progress <= 1 ? progress * 100 : progress;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function normalizeTaskSummary(rawValue: unknown): MiningTaskSummary {
  const raw = asObject(rawValue);
  const stats = asObject(firstDefined(raw.stats, raw.result_summary));
  const config = asObject(raw.config);
  const generation = toOptionalNumber(
    firstDefined(raw.generation, stats.generation, stats.current_generation, stats.n_generations_completed)
  );
  const totalGenerations = toOptionalNumber(
    firstDefined(raw.total_generations, stats.total_generations, stats.max_generations, config.max_generations, config.generations)
  );

  return {
    task_id: toStringValue(firstDefined(raw.task_id, raw.run_id)),
    engine: normalizeEngine(firstDefined(raw.engine, raw.engine_type)),
    status: normalizeTaskStatus(raw.status),
    progress: normalizeProgress(firstDefined(raw.progress, stats.progress, stats.progress_pct), generation, totalGenerations),
    generation,
    total_generations: totalGenerations,
    best_fitness: toOptionalNumber(firstDefined(raw.best_fitness, stats.best_fitness, stats.best_ic_ir)),
    discovered: toNumberValue(firstDefined(raw.discovered, stats.discovered, stats.n_candidates, stats.candidates), 0),
    passed: toNumberValue(firstDefined(raw.passed, stats.passed, stats.n_passed, stats.passed_count), 0),
    archived: toNumberValue(firstDefined(raw.archived, stats.archived, stats.n_archived, stats.archived_count), 0),
    started_at: toStringValue(raw.started_at),
    completed_at: toOptionalString(firstDefined(raw.completed_at, raw.finished_at)),
  };
}

function normalizeEvolutionHistory(value: unknown): MiningTaskDetail["evolution_history"] {
  if (!Array.isArray(value)) return undefined;
  return value.map((entry) => {
    const raw = asObject(entry);
    return {
      generation: toNumberValue(raw.generation, 0),
      best_fitness: toNumberValue(raw.best_fitness, 0),
      avg_fitness: toNumberValue(raw.avg_fitness, 0),
    };
  });
}

function normalizeCandidate(rawValue: unknown, task: MiningTaskSummary): CandidateFactor {
  const raw = asObject(rawValue);
  const gateReport = asObject(raw.gate_report);
  const gates = asObject(firstDefined(gateReport.gates, gateReport.gate_results));
  const metrics = asObject(gateReport.metrics);
  const summary = asObject(gateReport.summary);
  const g1Data = gateData(gates, "G1");
  const g2Data = gateData(gates, "G2");
  const g6Data = gateData(gates, "G6");
  const g3Data = gateData(gates, "G3");
  const id = toStringValue(firstDefined(raw.id, raw.candidate_id, raw.factor_id, raw.factor_name));
  const name = toStringValue(firstDefined(raw.name, raw.factor_name, raw.factorName), id);
  const gateScore = toOptionalNumber(firstDefined(raw.gate_score, gateReport.gate_score, gateReport.score));

  return {
    id,
    name,
    expression: toStringValue(firstDefined(raw.expression, raw.expr, raw.factor_expr, raw.factorExpression)),
    engine: normalizeEngine(firstDefined(raw.engine, task.engine)),
    task_id: toStringValue(firstDefined(raw.task_id, raw.run_id), task.task_id),
    ic_mean: toNumberValue(firstDefined(raw.ic_mean, gateReport.ic_mean, metrics.ic_mean, summary.ic_mean, g1Data.ic_mean, gateMetric(gates, "G1", "ic_mean")), 0),
    t_stat: toNumberValue(
      firstDefined(
        raw.t_stat,
        gateReport.t_stat,
        metrics.t_stat,
        summary.t_stat,
        g6Data.raw_t_stat,
        g6Data.t_stat_newey_west,
        g3Data.raw_t_stat,
        g3Data.t_stat_newey_west,
        gateMetric(gates, "G6", "raw_t_stat", "t_stat", "t_stat_newey_west"),
        gateMetric(gates, "G3", "raw_t_stat", "t_stat", "t_stat_newey_west")
      ),
      0
    ),
    fdr_t_stat: toNumberValue(
      firstDefined(raw.fdr_t_stat, gateReport.fdr_t_stat, metrics.fdr_t_stat, g6Data.fdr_t_stat, g3Data.fdr_t_stat),
      0
    ),
    ic_ir: toNumberValue(firstDefined(raw.ic_ir, gateReport.ic_ir, metrics.ic_ir, summary.ic_ir, g2Data.ic_ir, gateMetric(gates, "G2", "ic_ir")), 0),
    coverage: toNumberValue(firstDefined(raw.coverage, gateReport.coverage, metrics.coverage, summary.coverage, g1Data.coverage, g1Data.coverage_rate), 0),
    gate_status: normalizeGateStatus(firstDefined(raw.gate_status, raw.status, gateReport.status)),
    ...(gateScore !== undefined ? { gate_score: gateScore } : {}),
    created_at: toStringValue(raw.created_at),
  };
}

function normalizeTaskDetail(rawValue: unknown): MiningTaskDetail {
  const raw = asObject(rawValue);
  const summary = normalizeTaskSummary(raw);
  const candidatesValue = raw.candidates;
  const evolutionHistory = normalizeEvolutionHistory(firstDefined(raw.evolution_history, asObject(raw.stats).evolution_history));

  return {
    ...summary,
    config: asObject(raw.config) as unknown as GPConfig | LLMConfig | BruteForceConfig,
    candidates: Array.isArray(candidatesValue)
      ? candidatesValue.map((candidate) => normalizeCandidate(candidate, summary))
      : [],
    ...(evolutionHistory ? { evolution_history: evolutionHistory } : {}),
  };
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
  const res = await apiClient.get<unknown[]>("/mining/tasks");
  return Array.isArray(res.data) ? res.data.map(normalizeTaskSummary) : [];
}

export async function getMiningTaskDetail(taskId: string): Promise<MiningTaskDetail> {
  const res = await apiClient.get<unknown>(`/mining/tasks/${taskId}`);
  return normalizeTaskDetail(res.data);
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

export function buildCandidateGatePayloads(
  candidateIds: string[],
  candidates: CandidateFactor[]
): { expr: string; name?: string }[] {
  const candidatesById = new Map(candidates.map((candidate) => [candidate.id, candidate]));
  return candidateIds.map((id) => {
    const candidate = candidatesById.get(id);
    if (!candidate?.expression?.trim()) {
      throw new Error(`Missing candidate expression for ${id}; refresh task detail before Gate submission.`);
    }
    return { expr: candidate.expression, name: candidate.name || undefined };
  });
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
