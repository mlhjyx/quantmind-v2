import apiClient from "./client";

// ---- Types ----

export type PipelineNodeStatus = "idle" | "running" | "completed" | "failed" | "skipped";
export type AutomationLevel = "L0" | "L1" | "L2" | "L3";
export type ApprovalItemType = "factor" | "strategy";
export type ApprovalDecision = "approved" | "rejected" | "hold";
export type CandidateStatus = "pending" | "approved" | "rejected";
export type MiningEngine = "gp" | "bruteforce" | "llm";

/** 单条候选因子（来自 approval_queue 表，由 GET /runs/{run_id} 返回）。 */
export interface CandidateItem {
  id: number;
  factor_name: string;
  factor_expr: string;
  ast_hash: string;
  gate_result: Record<string, unknown> | null;
  sharpe_1y: number | null;
  sharpe_5y: number | null;
  backtest_report: Record<string, unknown> | null;
  status: CandidateStatus;
  decision_by: string | null;
  decision_reason: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface PipelineNode {
  id: string;
  name: string;
  status: PipelineNodeStatus;
  started_at?: string;
  completed_at?: string;
  duration_seconds?: number;
  output_count?: number;
}

export interface PipelineStatus {
  run_id: string | null;
  automation_level: AutomationLevel;
  is_running: boolean;
  is_paused: boolean;
  current_node: string | null;
  nodes: PipelineNode[];
  schedule_cron: string;
  next_run_at: string | null;
  last_run_at: string | null;
  /** D1 O3 (PN-003 iter 12) — pause state, gate-at-entry semantics.
   *  NULL = active; non-null = paused since ISO8601 timestamp. */
  paused_at?: string | null;
  paused_reason?: string | null;
}

/** D1 O3 (PN-003 iter 12) — pause / resume response payload. */
export interface PauseStatus {
  paused_at: string | null;
  paused_reason: string | null;
}

export interface ApprovalItem {
  id: string;
  type: ApprovalItemType;
  name: string;
  description: string;
  ic_mean?: number;
  t_stat?: number;
  fdr_t_stat?: number;
  sharpe?: number;
  mdd?: number;
  engine?: string;
  created_at: string;
  decision?: ApprovalDecision;
  decided_at?: string;
  decided_by?: string;
  note?: string;
}

export interface PipelineRun {
  run_id: string;
  started_at: string;
  completed_at?: string;
  status: "running" | "completed" | "failed" | "paused";
  automation_level: AutomationLevel;
  engine: string;
  discovered: number;
  gate_passed: number;
  archived: number;
  strategy_updated: boolean;
  sharpe_before?: number;
  sharpe_after?: number;
  triggered_by: "schedule" | "manual";
}

export interface PipelineLogEntry {
  id: string;
  run_id: string;
  timestamp: string;
  agent: string;
  level: "info" | "warning" | "error" | "decision";
  content: string;
}

/** POST /api/pipeline/trigger 的响应（backend TriggerPipelineResponse）。 */
export interface TriggerPipelineResult {
  run_id: string;
  task_id: string;
  engine: MiningEngine;
  status: string;
}

// ---- API calls ----

export async function getPipelineStatus(): Promise<PipelineStatus> {
  const res = await apiClient.get<PipelineStatus>("/pipeline/status");
  return res.data;
}

export async function triggerPipeline(
  engine: MiningEngine = "gp",
  config: Record<string, unknown> = {},
): Promise<TriggerPipelineResult> {
  // Backend endpoint: POST /api/pipeline/trigger (backend/app/api/pipeline.py::trigger_pipeline).
  // It requires a TriggerPipelineRequest body {engine, config}; an empty body 422s.
  const res = await apiClient.post<TriggerPipelineResult>("/pipeline/trigger", {
    engine,
    config,
  });
  return res.data;
}

/** D1 O3 (PN-003 iter 12) — Pause pipeline gate-at-entry.
 *  Backend: POST /api/pipeline/pause (idempotent no-overwrite when already paused).
 *  Optional `reason` (≤500 chars) is surfaced in /status response for UI display.
 *  Returns the resulting pause state (paused_at + paused_reason). */
export async function pausePipeline(reason?: string): Promise<PauseStatus> {
  const body = reason !== undefined ? { reason } : {};
  const res = await apiClient.post<PauseStatus>("/pipeline/pause", body);
  return res.data;
}

/** D1 O3 (PN-003 iter 12) — Resume pipeline (clear pause state).
 *  Backend: POST /api/pipeline/resume (idempotent — always returns null state). */
export async function resumePipeline(): Promise<PauseStatus> {
  const res = await apiClient.post<PauseStatus>("/pipeline/resume");
  return res.data;
}

export async function getPipelineHistory(): Promise<PipelineRun[]> {
  // F63-P2-9: /pipeline/history → /pipeline/runs (backend endpoint)
  const res = await apiClient.get<PipelineRun[]>("/pipeline/runs");
  return res.data;
}

export async function getPendingApprovals(): Promise<ApprovalItem[]> {
  // F63-P2-10: /pipeline/pending → /approval/queue (backend endpoint)
  const res = await apiClient.get<ApprovalItem[]>("/approval/queue");
  return res.data;
}

export async function approveItem(id: string, note?: string): Promise<void> {
  // Phase K fix: was /pipeline/approve/${id} (404). Backend route is POST /api/approval/queue/{id}/approve.
  // Body field aligned: backend expects reviewer_notes (ApprovalActionRequest), not note.
  await apiClient.post(`/approval/queue/${id}/approve`, { reviewer_notes: note ?? null });
}

export async function rejectItem(id: string, note?: string): Promise<void> {
  // Phase K fix: was /pipeline/reject/${id} (404). Backend route is POST /api/approval/queue/{id}/reject.
  await apiClient.post(`/approval/queue/${id}/reject`, { reviewer_notes: note ?? null });
}

export async function holdItem(id: string, note?: string): Promise<void> {
  // Phase K fix: was /pipeline/hold/${id} (404). Backend route is POST /api/approval/queue/{id}/hold.
  await apiClient.post(`/approval/queue/${id}/hold`, { reviewer_notes: note ?? null });
}

export async function getPipelineLogs(runId: string): Promise<PipelineLogEntry[]> {
  // NOTE: No backend endpoint exists yet. GET /api/pipeline/{run_id}/logs is not
  // implemented in backend/app/api/pipeline.py. Will return 404 until added.
  const res = await apiClient.get<PipelineLogEntry[]>(`/pipeline/${runId}/logs`);
  return res.data;
}

export async function setAutomationLevel(level: AutomationLevel): Promise<void> {
  // Backend wired by D1 O8 (PN-001 iter 10, 2026-05-23):
  // PUT /api/pipeline/automation-level → singleton pipeline_settings UPSERT.
  await apiClient.put("/pipeline/automation-level", { level });
}

/** Read persisted pipeline automation_level from backend (D1 O8 GET consumer).
 *  Backend returns defensive default `{level:"L0"}` when no row exists.
 */
export async function getAutomationLevel(): Promise<{ level: AutomationLevel }> {
  const res = await apiClient.get<{ level: AutomationLevel }>("/pipeline/automation-level");
  return res.data;
}

/** 查询单次 Pipeline 运行详情，含 candidates（approval_queue）列表。 */
export async function getPipelineRun(runId: string): Promise<{
  run_id: string;
  engine: string;
  status: string;
  candidates: CandidateItem[];
  candidates_count: { total: number; pending: number; approved: number; rejected: number };
}> {
  const res = await apiClient.get(`/pipeline/runs/${runId}`);
  return res.data;
}

/** 审批通过候选因子（写 approval_queue.status='approved'）。 */
export async function approveFactor(
  runId: string,
  factorId: number,
  decisionReason?: string,
): Promise<void> {
  await apiClient.post(`/pipeline/runs/${runId}/approve/${factorId}`, {
    decision_reason: decisionReason ?? null,
  });
}

/** 审批拒绝候选因子（拒绝理由必填 ≥5 字，写入 mining_knowledge 供 GP 学习）。 */
export async function rejectFactor(
  runId: string,
  factorId: number,
  decisionReason: string,
): Promise<void> {
  await apiClient.post(`/pipeline/runs/${runId}/reject/${factorId}`, {
    decision_reason: decisionReason,
  });
}
