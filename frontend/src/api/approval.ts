/**
 * Approval Queue API — gp_approval_queue domain 12.
 *
 * iter 136 W2-F F1 closure — V3 §S5/§S6/§S7/§S8 backend approval surface
 * frontend-side typed wrapper. Sibling pipeline.ts uses ApprovalItem type
 * mismatched with backend schema (string id + flat IC stats), retained for
 * existing PipelineConsole/ApprovalPanel consumer (domain 11 approval_queue
 * via /pipeline/runs/{run_id} endpoints — different table, different flow).
 *
 * Backend SSOT: backend/app/api/approval.py (file:line cite at iter 136 audit)
 * - GET  /api/approval/queue                  (list_pending_queue, line 205)
 * - GET  /api/approval/queue/{item_id}        (get_queue_item, line 234)
 * - POST /api/approval/queue/{item_id}/approve (line 259)
 * - POST /api/approval/queue/{item_id}/reject  (line 290)
 * - POST /api/approval/queue/{item_id}/hold    (line 321)
 * - GET  /api/approval/history                 (line 352)
 *
 * Backend model: backend/app/models/approval_queue.py::GPApprovalQueue
 * DB table: gp_approval_queue (domain 12, V3 §S5+S6+S7+S8)
 */

import apiClient from "./client";

// ─────────────────────────────────────────────────────────
// Types — match backend Pydantic schemas in approval.py:81-130
// ─────────────────────────────────────────────────────────

export type ApprovalStatus = "pending" | "approved" | "rejected" | "hold";

/** Queue list item (omits gate_report for transfer size).
 *  Backend: approval.py:81-108 ApprovalQueueItem */
export interface ApprovalQueueItem {
  id: number;
  run_id: string;
  factor_name: string;
  factor_expr: string;
  ast_hash: string;
  status: ApprovalStatus;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  reviewer_notes: string | null;
}

/** Detail with G1-G8 gate_report JSONB.
 *  Backend: approval.py:111-130 ApprovalQueueDetail */
export interface ApprovalQueueDetail extends ApprovalQueueItem {
  gate_report: Record<string, unknown>;
}

/** History response with pagination.
 *  Backend: approval.py:399-404 */
export interface ApprovalHistoryResponse {
  total: number;
  limit: number;
  offset: number;
  items: ApprovalQueueDetail[];
}

/** Action result (approve/reject/hold).
 *  Backend: approval.py:190-197 */
export interface ApprovalActionResult {
  id: number;
  factor_name: string;
  status: ApprovalStatus;
  reviewed_at: string;
  reviewed_by: string;
  reviewer_notes: string | null;
}

/** Request body for approve/reject/hold.
 *  Backend: approval.py:61-78 ApprovalActionRequest */
export interface ApprovalActionBody {
  reviewer_notes?: string | null;
  rejection_reason?: string | null;
  reviewed_by?: string;
}

// ─────────────────────────────────────────────────────────
// API wrappers (axios via apiClient SSOT, LL-187 sediment)
// ─────────────────────────────────────────────────────────

/** GET /api/approval/queue?limit=N — pending list ascending created_at. */
export async function getApprovalQueue(limit = 50): Promise<ApprovalQueueItem[]> {
  const res = await apiClient.get<ApprovalQueueItem[]>("/approval/queue", {
    params: { limit },
  });
  return res.data;
}

/** GET /api/approval/queue/{id} — full detail with gate_report. */
export async function getApprovalDetail(itemId: number): Promise<ApprovalQueueDetail> {
  const res = await apiClient.get<ApprovalQueueDetail>(`/approval/queue/${itemId}`);
  return res.data;
}

/** POST /api/approval/queue/{id}/approve — admin token required. */
export async function approveQueueItem(
  itemId: number,
  body: ApprovalActionBody = {},
): Promise<ApprovalActionResult> {
  const res = await apiClient.post<ApprovalActionResult>(
    `/approval/queue/${itemId}/approve`,
    { reviewed_by: "user", ...body },
  );
  return res.data;
}

/** POST /api/approval/queue/{id}/reject — rejection_reason recommended ≥5 chars. */
export async function rejectQueueItem(
  itemId: number,
  body: ApprovalActionBody = {},
): Promise<ApprovalActionResult> {
  const res = await apiClient.post<ApprovalActionResult>(
    `/approval/queue/${itemId}/reject`,
    { reviewed_by: "user", ...body },
  );
  return res.data;
}

/** POST /api/approval/queue/{id}/hold — reviewer_notes explains hold reason. */
export async function holdQueueItem(
  itemId: number,
  body: ApprovalActionBody = {},
): Promise<ApprovalActionResult> {
  const res = await apiClient.post<ApprovalActionResult>(
    `/approval/queue/${itemId}/hold`,
    { reviewed_by: "user", ...body },
  );
  return res.data;
}

/** GET /api/approval/history?status=&limit=&offset= — non-pending history. */
export async function getApprovalHistory(params: {
  status?: ApprovalStatus | "";
  limit?: number;
  offset?: number;
} = {}): Promise<ApprovalHistoryResponse> {
  const res = await apiClient.get<ApprovalHistoryResponse>("/approval/history", {
    params: {
      status: params.status ?? "",
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  });
  return res.data;
}
