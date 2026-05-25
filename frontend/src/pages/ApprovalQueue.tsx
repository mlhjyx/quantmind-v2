/**
 * ApprovalQueue — gp_approval_queue (domain 12) operator UI.
 *
 * iter 136 W2-F F1 closure — V3 §S5/§S6/§S7/§S8 backend approval surface
 * exposed to operator UI. Closes 6/6 DARK endpoints from W2-F audit.
 *
 * Backend SSOT (cite source):
 * - backend/app/api/approval.py (6 endpoints, lines 205+234+259+290+321+352)
 * - DB table: gp_approval_queue (DDL domain 12, V3 §S5+§S6+§S7+§S8)
 *
 * Frontend Design v3 patterns sustained:
 * - LL-187: axios via apiClient SSOT (no raw axios)
 * - LL-205: fail-loud render guard (no EMPTY_STATUS mock fallback)
 * - LL-035: null-safe `?.` defensive
 * - ConfirmModal 4-tier safety (LOW approve / MED hold / HIGH reject)
 * - Glassmorphism C tokens + Glass.card
 *
 * Page sections:
 * 1. Tab switcher 待审批 | 历史
 * 2. Pending list (table view, polling 30s)
 * 3. History list (paginated, status filter)
 * 4. Detail drawer (G1-G8 gate_report JSONB collapsible viewer)
 * 5. Action modal (ConfirmModal tier per action)
 */

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  XCircle,
  PauseCircle,
  RefreshCw,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  ClipboardList,
} from "lucide-react";
import { C, Glass } from "@/theme";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import {
  getApprovalQueue,
  getApprovalDetail,
  getApprovalHistory,
  approveQueueItem,
  rejectQueueItem,
  holdQueueItem,
  type ApprovalQueueItem,
  type ApprovalQueueDetail,
  type ApprovalStatus,
} from "@/api/approval";
import { useNotificationStore } from "@/store/notificationStore";

type TabKey = "pending" | "history";
type ActionKind = "approve" | "reject" | "hold";

interface PendingActionState {
  item: ApprovalQueueItem;
  action: ActionKind;
}

// ─────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ApprovalStatus }) {
  const map: Record<ApprovalStatus, { color: string; label: string }> = {
    pending: { color: C.warn, label: "待审批" },
    approved: { color: C.down, label: "已批准" }, // A股惯例 绿=down=approved positive
    rejected: { color: C.up, label: "已拒绝" },
    hold: { color: C.info, label: "已暂缓" },
  };
  const cfg = map[status] ?? map.pending;
  return (
    <span
      className="px-2 py-0.5 rounded inline-flex items-center"
      style={{
        fontSize: 10,
        color: cfg.color,
        background: `${cfg.color}15`,
        border: `1px solid ${cfg.color}40`,
      }}
    >
      {cfg.label}
    </span>
  );
}

function truncate(text: string, maxLen = 60): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + "…";
}

function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

// ─────────────────────────────────────────────────────────
// Detail Drawer (G1-G8 gate_report viewer)
// ─────────────────────────────────────────────────────────

function GateReportSection({
  title,
  data,
}: {
  title: string;
  data: unknown;
}) {
  const [expanded, setExpanded] = useState(false);
  if (data === undefined || data === null) return null;

  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <div className="mb-2" style={{ border: `1px solid ${C.border}`, borderRadius: 8 }}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 cursor-pointer"
        style={{ background: C.bg3, borderRadius: expanded ? "8px 8px 0 0" : 8, fontSize: 12, color: C.text2 }}
      >
        <Icon size={14} color={C.text3} />
        <span style={{ fontWeight: 600 }}>{title}</span>
      </button>
      {expanded && (
        <pre
          className="px-3 py-2 overflow-x-auto"
          style={{
            background: C.bg2,
            color: C.text2,
            fontSize: 10,
            fontFamily: C.mono,
            margin: 0,
            borderRadius: "0 0 8px 8px",
            maxHeight: 240,
            overflowY: "auto",
          }}
        >
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </div>
  );
}

function DetailDrawer({
  detail,
  onClose,
}: {
  detail: ApprovalQueueDetail;
  onClose: () => void;
}) {
  const gateReport = detail.gate_report ?? {};

  // iter 136c PR #485 reviewer M2 fix — Escape key dismissal (a11y standard
  // for role="dialog"). Sibling ConfirmModal handles its own Escape; this
  // drawer was missing the listener despite identical aria-modal contract.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="detail-drawer-title"
    >
      <div
        className="h-full overflow-y-auto p-6"
        style={{
          width: 560,
          ...Glass.modal,
          borderLeft: `1px solid ${C.borderLight}`,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <div>
            <div id="detail-drawer-title" style={{ fontSize: 16, color: C.text1, fontWeight: 600 }}>
              {detail.factor_name}
            </div>
            <div style={{ fontSize: 10, color: C.text4, fontFamily: C.mono, marginTop: 4 }}>
              id={detail.id} · run={detail.run_id.slice(0, 8)}
            </div>
          </div>
          <StatusBadge status={detail.status} />
        </div>

        <div className="mb-4">
          <div style={{ fontSize: 11, color: C.text3, marginBottom: 4 }}>因子表达式</div>
          <pre
            className="p-3 overflow-x-auto"
            style={{
              background: C.bg3,
              color: C.text2,
              fontSize: 11,
              fontFamily: C.mono,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              margin: 0,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {detail.factor_expr}
          </pre>
          <div style={{ fontSize: 10, color: C.text4, marginTop: 4, fontFamily: C.mono }}>
            ast_hash: {detail.ast_hash}
          </div>
        </div>

        <div className="mb-4">
          <div style={{ fontSize: 11, color: C.text3, marginBottom: 6 }}>Gate Report (G1-G8)</div>
          {Object.keys(gateReport).length === 0 ? (
            <div style={{ fontSize: 11, color: C.text4, fontStyle: "italic" }}>暂无 gate_report 数据</div>
          ) : (
            Object.entries(gateReport).map(([key, value]) => (
              <GateReportSection key={key} title={key} data={value} />
            ))
          )}
        </div>

        {detail.reviewed_at && (
          <div className="mb-4" style={{ fontSize: 11, color: C.text3 }}>
            <div>审批时间: <span style={{ color: C.text2 }}>{formatTimestamp(detail.reviewed_at)}</span></div>
            <div>审批人: <span style={{ color: C.text2 }}>{detail.reviewed_by ?? "—"}</span></div>
            {detail.reviewer_notes && (
              <div style={{ marginTop: 8 }}>
                <div style={{ marginBottom: 4 }}>备注:</div>
                <div
                  className="p-2"
                  style={{
                    background: C.bg3,
                    border: `1px solid ${C.border}`,
                    borderRadius: 6,
                    fontSize: 11,
                    color: C.text2,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {detail.reviewer_notes}
                </div>
              </div>
            )}
          </div>
        )}

        <button
          onClick={onClose}
          className="w-full mt-4 px-4 py-2 rounded-lg cursor-pointer"
          style={{ fontSize: 12, background: C.bg3, color: C.text2 }}
        >
          关闭
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Pending Tab
// ─────────────────────────────────────────────────────────

function PendingTab({
  onSelectDetail,
  onAction,
}: {
  onSelectDetail: (id: number) => void;
  onAction: (state: PendingActionState) => void;
}) {
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["approval-queue", "pending"],
    queryFn: () => getApprovalQueue(50),
    refetchInterval: 30_000, // 30s polling for near-real-time
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="rounded-xl"
            style={{ height: 80, background: C.bg2, opacity: 0.5 }}
          />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div
        className="rounded-xl p-6 text-center"
        style={{ ...Glass.card, border: `1px solid ${C.up}40` }}
      >
        <AlertTriangle size={32} color={C.up} className="mx-auto mb-3" />
        <div style={{ fontSize: 14, color: C.up, fontWeight: 600, marginBottom: 4 }}>
          审批队列加载失败
        </div>
        <div style={{ fontSize: 11, color: C.text3, marginBottom: 12 }}>
          {error instanceof Error ? error.message : "未知错误"}
        </div>
        <button
          onClick={() => refetch()}
          className="px-4 py-1.5 rounded-lg cursor-pointer inline-flex items-center gap-2"
          style={{ fontSize: 12, background: C.accent, color: "#fff" }}
        >
          <RefreshCw size={12} />
          重试
        </button>
      </div>
    );
  }

  const items = data ?? [];

  if (items.length === 0) {
    return (
      <div
        className="rounded-xl p-8 text-center"
        style={Glass.card}
      >
        <CheckCircle2 size={32} color={C.down} className="mx-auto mb-3" />
        <div style={{ fontSize: 14, color: C.text2, fontWeight: 500 }}>审批队列已清空</div>
        <div style={{ fontSize: 11, color: C.text3, marginTop: 4 }}>暂无待处理项目</div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between" style={{ fontSize: 11, color: C.text3 }}>
        <span>
          待审批 <span style={{ color: C.text1, fontWeight: 600 }}>{items.length}</span> 项
        </span>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded cursor-pointer"
          style={{ fontSize: 10, color: C.text3, background: C.bg3 }}
        >
          <RefreshCw size={10} className={isFetching ? "animate-spin" : ""} />
          {isFetching ? "刷新中" : "刷新"}
        </button>
      </div>

      {items.map((item) => (
        <div
          key={item.id}
          className="rounded-xl p-3"
          style={Glass.card}
        >
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span style={{ fontSize: 13, color: C.text1, fontWeight: 500 }}>
                  {item.factor_name}
                </span>
                <span style={{ fontSize: 9, color: C.text4, fontFamily: C.mono }}>
                  id={item.id}
                </span>
              </div>
              <pre
                className="cursor-pointer"
                onClick={() => onSelectDetail(item.id)}
                style={{
                  fontSize: 10,
                  fontFamily: C.mono,
                  color: C.text3,
                  margin: 0,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title="点击查看完整详情"
              >
                {truncate(item.factor_expr, 80)}
              </pre>
              <div className="flex items-center gap-3 mt-1.5" style={{ fontSize: 10, color: C.text4 }}>
                <span>提交: {formatTimestamp(item.created_at)}</span>
                <span style={{ fontFamily: C.mono }}>{item.ast_hash.slice(0, 12)}…</span>
              </div>
            </div>
            <div className="flex gap-1.5 shrink-0">
              <button
                onClick={() => onAction({ item, action: "approve" })}
                className="px-3 py-1.5 rounded-lg cursor-pointer inline-flex items-center gap-1"
                style={{
                  fontSize: 11,
                  color: C.down,
                  background: `${C.down}15`,
                  border: `1px solid ${C.down}40`,
                }}
              >
                <CheckCircle2 size={12} />
                批准
              </button>
              <button
                onClick={() => onAction({ item, action: "hold" })}
                className="px-3 py-1.5 rounded-lg cursor-pointer inline-flex items-center gap-1"
                style={{
                  fontSize: 11,
                  color: C.info,
                  background: `${C.info}15`,
                  border: `1px solid ${C.info}40`,
                }}
              >
                <PauseCircle size={12} />
                暂缓
              </button>
              <button
                onClick={() => onAction({ item, action: "reject" })}
                className="px-3 py-1.5 rounded-lg cursor-pointer inline-flex items-center gap-1"
                style={{
                  fontSize: 11,
                  color: C.up,
                  background: `${C.up}15`,
                  border: `1px solid ${C.up}40`,
                }}
              >
                <XCircle size={12} />
                拒绝
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// History Tab
// ─────────────────────────────────────────────────────────

function HistoryTab({ onSelectDetail }: { onSelectDetail: (id: number) => void }) {
  const [statusFilter, setStatusFilter] = useState<ApprovalStatus | "">("");
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["approval-queue", "history", statusFilter, offset],
    queryFn: () => getApprovalHistory({ status: statusFilter, limit, offset }),
  });

  return (
    <div className="space-y-3">
      {/* Filter bar */}
      <div className="flex items-center gap-2" style={{ fontSize: 11, color: C.text3 }}>
        <span>筛选:</span>
        {(["", "approved", "rejected", "hold"] as const).map((s) => (
          <button
            key={s || "all"}
            onClick={() => {
              setStatusFilter(s);
              setOffset(0);
            }}
            className="px-2.5 py-1 rounded cursor-pointer"
            style={{
              fontSize: 11,
              color: statusFilter === s ? C.text1 : C.text3,
              background: statusFilter === s ? C.accentSoft : C.bg3,
              border: `1px solid ${statusFilter === s ? C.accent : C.border}`,
            }}
          >
            {s === "" ? "全部" : s === "approved" ? "已批准" : s === "rejected" ? "已拒绝" : "已暂缓"}
          </button>
        ))}
      </div>

      {/* Body */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-xl"
              style={{ height: 70, background: C.bg2, opacity: 0.5 }}
            />
          ))}
        </div>
      ) : isError ? (
        <div
          className="rounded-xl p-6 text-center"
          style={{ ...Glass.card, border: `1px solid ${C.up}40` }}
        >
          <AlertTriangle size={28} color={C.up} className="mx-auto mb-2" />
          <div style={{ fontSize: 13, color: C.up, fontWeight: 600 }}>历史加载失败</div>
          <div style={{ fontSize: 11, color: C.text3, marginBottom: 12, marginTop: 4 }}>
            {error instanceof Error ? error.message : "未知错误"}
          </div>
          <button
            onClick={() => refetch()}
            className="px-3 py-1 rounded-lg cursor-pointer inline-flex items-center gap-1.5"
            style={{ fontSize: 11, background: C.accent, color: "#fff" }}
          >
            <RefreshCw size={11} />
            重试
          </button>
        </div>
      ) : (
        <>
          <div style={{ fontSize: 11, color: C.text3 }}>
            共 <span style={{ color: C.text1, fontWeight: 600 }}>{data?.total ?? 0}</span> 条历史
            {/* iter 136c PR #485 reviewer L1 fix — hide "当前 1 - 0" range when total=0. */}
            {(data?.total ?? 0) > 0 && (
              <> · 当前 {offset + 1} - {Math.min(offset + limit, data?.total ?? 0)}</>
            )}
          </div>

          {(data?.items ?? []).length === 0 ? (
            <div className="rounded-xl p-8 text-center" style={Glass.card}>
              <div style={{ fontSize: 12, color: C.text3 }}>暂无历史记录</div>
            </div>
          ) : (
            <div className="space-y-2">
              {(data?.items ?? []).map((row) => (
                <div
                  key={row.id}
                  onClick={() => onSelectDetail(row.id)}
                  className="rounded-xl p-3 cursor-pointer"
                  style={Glass.card}
                >
                  <div className="flex items-start justify-between gap-3 mb-1.5">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <span style={{ fontSize: 12, color: C.text1, fontWeight: 500 }}>
                        {row.factor_name}
                      </span>
                      <span style={{ fontSize: 9, color: C.text4, fontFamily: C.mono }}>
                        id={row.id}
                      </span>
                    </div>
                    <StatusBadge status={row.status} />
                  </div>
                  <div className="flex items-center gap-3" style={{ fontSize: 10, color: C.text4 }}>
                    <span>审批: {formatTimestamp(row.reviewed_at)}</span>
                    <span>审批人: {row.reviewed_by ?? "—"}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          {(data?.total ?? 0) > limit && (
            <div className="flex items-center justify-center gap-2 pt-2" style={{ fontSize: 11 }}>
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="px-3 py-1 rounded cursor-pointer"
                style={{
                  background: C.bg3,
                  color: offset === 0 ? C.text4 : C.text2,
                  border: `1px solid ${C.border}`,
                  cursor: offset === 0 ? "not-allowed" : "pointer",
                }}
              >
                上一页
              </button>
              <button
                disabled={offset + limit >= (data?.total ?? 0)}
                onClick={() => setOffset(offset + limit)}
                className="px-3 py-1 rounded cursor-pointer"
                style={{
                  background: C.bg3,
                  color: offset + limit >= (data?.total ?? 0) ? C.text4 : C.text2,
                  border: `1px solid ${C.border}`,
                  cursor: offset + limit >= (data?.total ?? 0) ? "not-allowed" : "pointer",
                }}
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────────────

export default function ApprovalQueue() {
  const [tab, setTab] = useState<TabKey>("pending");
  const [detailId, setDetailId] = useState<number | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingActionState | null>(null);
  const notify = useNotificationStore((s) => s.add);
  const qc = useQueryClient();

  const detailQuery = useQuery({
    queryKey: ["approval-detail", detailId],
    queryFn: () => getApprovalDetail(detailId!),
    enabled: detailId != null,
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, notes }: { id: number; notes?: string }) =>
      approveQueueItem(id, { reviewer_notes: notes }),
    onSuccess: (data) => {
      notify({ type: "success", title: "已批准", message: `${data.factor_name} 进入因子库` });
      qc.invalidateQueries({ queryKey: ["approval-queue"] });
    },
    onError: (err) => {
      notify({ type: "error", title: "批准失败", message: err instanceof Error ? err.message : "未知错误" });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, reason, notes }: { id: number; reason: string; notes?: string }) =>
      rejectQueueItem(id, { rejection_reason: reason, reviewer_notes: notes }),
    onSuccess: (data) => {
      notify({ type: "success", title: "已拒绝", message: `${data.factor_name} 已记录拒绝` });
      qc.invalidateQueries({ queryKey: ["approval-queue"] });
    },
    onError: (err) => {
      notify({ type: "error", title: "拒绝失败", message: err instanceof Error ? err.message : "未知错误" });
    },
  });

  const holdMutation = useMutation({
    mutationFn: ({ id, notes }: { id: number; notes?: string }) =>
      holdQueueItem(id, { reviewer_notes: notes }),
    onSuccess: (data) => {
      notify({ type: "success", title: "已暂缓", message: `${data.factor_name} 进入暂缓状态` });
      qc.invalidateQueries({ queryKey: ["approval-queue"] });
    },
    onError: (err) => {
      notify({ type: "error", title: "暂缓失败", message: err instanceof Error ? err.message : "未知错误" });
    },
  });

  const handleConfirm = async (meta: { reason?: string }) => {
    if (!pendingAction) return;
    const { item, action } = pendingAction;
    // iter 136c PR #485 reviewer M1 fix — wrap mutateAsync in try/catch so the
    // modal stays open on failure (preserves user-entered reason text, avoids
    // UX regression where modal closes on 409 conflict / network error after
    // mutation onError notification already fired). On success, close modal.
    try {
      if (action === "approve") {
        await approveMutation.mutateAsync({ id: item.id, notes: meta.reason });
      } else if (action === "reject") {
        await rejectMutation.mutateAsync({
          id: item.id,
          reason: meta.reason ?? "未填写原因",
          notes: meta.reason,
        });
      } else if (action === "hold") {
        await holdMutation.mutateAsync({ id: item.id, notes: meta.reason });
      }
      setPendingAction(null);
    } catch {
      // silent_ok: onError on each mutation already fires user notification.
      // Keep modal open so user can adjust reason and retry without losing input.
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ClipboardList size={20} color={C.accent} />
        <div>
          <h1 style={{ fontSize: 18, color: C.text1, fontWeight: 600 }}>
            因子审批队列
          </h1>
          <div style={{ fontSize: 11, color: C.text3, marginTop: 2 }}>
            GP / BruteForce / LLM 引擎产出的因子需经人工审批后进入因子库
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1" style={{ borderBottom: `1px solid ${C.border}` }}>
        {(["pending", "history"] as const).map((k) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className="px-4 py-2 cursor-pointer"
            style={{
              fontSize: 12,
              color: tab === k ? C.text1 : C.text3,
              fontWeight: tab === k ? 600 : 400,
              borderBottom: tab === k ? `2px solid ${C.accent}` : "2px solid transparent",
              marginBottom: -1,
            }}
          >
            {k === "pending" ? "待审批" : "历史"}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "pending" ? (
        <PendingTab
          onSelectDetail={(id) => setDetailId(id)}
          onAction={(s) => setPendingAction(s)}
        />
      ) : (
        <HistoryTab onSelectDetail={(id) => setDetailId(id)} />
      )}

      {/* Detail drawer */}
      {detailId != null && detailQuery.data && (
        <DetailDrawer detail={detailQuery.data} onClose={() => setDetailId(null)} />
      )}
      {detailId != null && detailQuery.isLoading && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.5)" }}
        >
          <div className="rounded-xl p-4" style={Glass.card}>
            <div className="flex items-center gap-2" style={{ fontSize: 12, color: C.text2 }}>
              <RefreshCw size={14} className="animate-spin" />
              加载详情中...
            </div>
          </div>
        </div>
      )}
      {detailId != null && detailQuery.isError && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.5)" }}
          onClick={() => setDetailId(null)}
        >
          <div className="rounded-xl p-6" style={{ ...Glass.card, border: `1px solid ${C.up}40` }} onClick={(e) => e.stopPropagation()}>
            <div style={{ fontSize: 13, color: C.up, fontWeight: 600, marginBottom: 8 }}>详情加载失败</div>
            <div style={{ fontSize: 11, color: C.text3, marginBottom: 12 }}>
              {detailQuery.error instanceof Error ? detailQuery.error.message : "未知错误"}
            </div>
            <button
              onClick={() => setDetailId(null)}
              className="px-3 py-1 rounded-lg cursor-pointer"
              style={{ fontSize: 11, background: C.bg3, color: C.text2 }}
            >
              关闭
            </button>
          </div>
        </div>
      )}

      {/* Action ConfirmModal */}
      {pendingAction && (
        <ConfirmModal
          title={
            pendingAction.action === "approve"
              ? `批准: ${pendingAction.item.factor_name}`
              : pendingAction.action === "hold"
              ? `暂缓: ${pendingAction.item.factor_name}`
              : `拒绝: ${pendingAction.item.factor_name}`
          }
          message={
            pendingAction.action === "approve"
              ? `批准后, 因子 ${pendingAction.item.factor_name} 将进入 factor_registry 候选库. 备注可选.`
              : pendingAction.action === "hold"
              ? `暂缓表示需要更多数据或分析后再决定. 请填写暂缓原因 (≥5 字符).`
              : `拒绝后, 因子不会进入因子库但保留在历史. 拒绝原因将写入 mining_knowledge 供 GP 学习, 请填写 (≥5 字符).`
          }
          safetyTier={
            pendingAction.action === "approve"
              ? "LOW"
              : pendingAction.action === "hold"
              ? "MED"
              : "HIGH"
          }
          requiredReason={pendingAction.action !== "approve"}
          reasonMinLength={5}
          onConfirm={handleConfirm}
          onCancel={() => setPendingAction(null)}
        />
      )}
    </div>
  );
}
