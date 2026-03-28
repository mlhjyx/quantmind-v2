import apiClient from "./client";

// ---- Types ----

export type PipelineNodeStatus = "idle" | "running" | "completed" | "failed" | "skipped";
export type AutomationLevel = "L0" | "L1" | "L2" | "L3";
export type ApprovalItemType = "factor" | "strategy";
export type ApprovalDecision = "approved" | "rejected" | "hold";

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

// ---- API calls ----

export async function getPipelineStatus(): Promise<PipelineStatus> {
  const res = await apiClient.get<PipelineStatus>("/pipeline/status");
  return res.data;
}

export async function triggerPipeline(): Promise<{ run_id: string }> {
  const res = await apiClient.post<{ run_id: string }>("/pipeline/trigger");
  return res.data;
}

export async function pausePipeline(): Promise<void> {
  await apiClient.post("/pipeline/pause");
}

export async function getPipelineHistory(): Promise<PipelineRun[]> {
  const res = await apiClient.get<PipelineRun[]>("/pipeline/history");
  return res.data;
}

export async function getPendingApprovals(): Promise<ApprovalItem[]> {
  const res = await apiClient.get<ApprovalItem[]>("/pipeline/pending");
  return res.data;
}

export async function approveItem(id: string, note?: string): Promise<void> {
  await apiClient.post(`/pipeline/approve/${id}`, { note });
}

export async function rejectItem(id: string, note?: string): Promise<void> {
  await apiClient.post(`/pipeline/reject/${id}`, { note });
}

export async function holdItem(id: string, note?: string): Promise<void> {
  await apiClient.post(`/pipeline/hold/${id}`, { note });
}

export async function getPipelineLogs(runId: string): Promise<PipelineLogEntry[]> {
  const res = await apiClient.get<PipelineLogEntry[]>(`/pipeline/${runId}/logs`);
  return res.data;
}

export async function setAutomationLevel(level: AutomationLevel): Promise<void> {
  await apiClient.put("/pipeline/automation-level", { level });
}
