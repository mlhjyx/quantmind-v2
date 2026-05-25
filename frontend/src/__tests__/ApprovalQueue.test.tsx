/**
 * ApprovalQueue — iter 136 W2-F F1 fail-loud render guard tests.
 *
 * Sibling pattern to PipelineConsole.test.tsx (iter 107 W14 LL-205 sediment).
 * Closes gp_approval_queue (domain 12) backend → frontend wire gap.
 *
 * Test cases:
 *   T1: Loading skeleton while pending fetch hangs
 *   T2: Fail-loud error card when getApprovalQueue rejects
 *   T3: Retry button re-invokes getApprovalQueue
 *   T4: Empty state when 0 items
 *   T5: Happy path renders items + action buttons
 *   T6: History tab fail-loud on error
 *   T7: Detail drawer renders gate_report (G1-G8) JSON
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ApprovalQueueItem, ApprovalQueueDetail } from "@/api/approval";

// ── Mock @/api/approval ─────────────────────────────────────────
const mockGetApprovalQueue = vi.fn();
const mockGetApprovalDetail = vi.fn();
const mockGetApprovalHistory = vi.fn();
const mockApproveQueueItem = vi.fn().mockResolvedValue({});
const mockRejectQueueItem = vi.fn().mockResolvedValue({});
const mockHoldQueueItem = vi.fn().mockResolvedValue({});

vi.mock("@/api/approval", () => ({
  getApprovalQueue: () => mockGetApprovalQueue(),
  getApprovalDetail: (id: number) => mockGetApprovalDetail(id),
  getApprovalHistory: (params: object) => mockGetApprovalHistory(params),
  approveQueueItem: (id: number, body: object) => mockApproveQueueItem(id, body),
  rejectQueueItem: (id: number, body: object) => mockRejectQueueItem(id, body),
  holdQueueItem: (id: number, body: object) => mockHoldQueueItem(id, body),
}));

// Mock notification store (avoid Zustand setup overhead)
vi.mock("@/store/notificationStore", () => ({
  useNotificationStore: vi.fn(() => vi.fn()),
}));

// eslint-disable-next-line import/first
import ApprovalQueue from "@/pages/ApprovalQueue";

const renderWithProviders = () => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ApprovalQueue />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const sampleItem: ApprovalQueueItem = {
  id: 42,
  run_id: "abcd1234-ef56-7890-abcd-ef1234567890",
  factor_name: "test_factor_alpha",
  factor_expr: "rank((close - delay(close, 5)) / delay(close, 5))",
  ast_hash: "0123456789abcdef0123456789abcdef",
  status: "pending",
  created_at: "2026-05-26T01:30:00+00:00",
  reviewed_at: null,
  reviewed_by: null,
  reviewer_notes: null,
};

const sampleDetail: ApprovalQueueDetail = {
  ...sampleItem,
  gate_report: {
    G1_novelty: { passed: true, ast_similarity_max: 0.42 },
    G2_correlation: { passed: true, max_corr: 0.31 },
    G3_significance: { passed: true, t_stat: 3.2, fdr_t_stat: 2.8 },
  },
};

describe("ApprovalQueue — iter 136 W2-F F1 fail-loud guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetApprovalHistory.mockResolvedValue({ total: 0, limit: 20, offset: 0, items: [] });
  });

  it("T1: shows loading skeleton while getApprovalQueue hangs", () => {
    mockGetApprovalQueue.mockReturnValue(new Promise(() => {}));
    renderWithProviders();
    // Skeleton renders, no error card, no items
    expect(screen.queryByText(/审批队列加载失败/)).toBeNull();
    expect(screen.queryByText(/审批队列已清空/)).toBeNull();
  });

  it("T2: fails loud with error card when getApprovalQueue rejects", async () => {
    mockGetApprovalQueue.mockRejectedValue(new Error("network down"));
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/审批队列加载失败/)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    // No silent EMPTY_STATUS fallback
    expect(screen.queryByText(/审批队列已清空/)).toBeNull();
  });

  it("T3: retry button re-invokes getApprovalQueue", async () => {
    mockGetApprovalQueue.mockRejectedValue(new Error("first fail"));
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/审批队列加载失败/)).toBeInTheDocument();
    });
    const initialCalls = mockGetApprovalQueue.mock.calls.length;
    mockGetApprovalQueue.mockResolvedValueOnce([]);
    await userEvent.click(screen.getByRole("button", { name: /重试/ }));
    await waitFor(() => {
      expect(mockGetApprovalQueue.mock.calls.length).toBeGreaterThan(initialCalls);
    });
  });

  it("T4: empty state when 0 pending items", async () => {
    mockGetApprovalQueue.mockResolvedValue([]);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/审批队列已清空/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/审批队列加载失败/)).toBeNull();
  });

  it("T5: happy path renders item + action buttons", async () => {
    mockGetApprovalQueue.mockResolvedValue([sampleItem]);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText("test_factor_alpha")).toBeInTheDocument();
    });
    // 3 action buttons per item
    expect(screen.getByRole("button", { name: /批准/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /暂缓/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /拒绝/ })).toBeInTheDocument();
    // ID surfaced
    expect(screen.getByText(/id=42/)).toBeInTheDocument();
  });

  it("T6: history tab fail-loud when getApprovalHistory rejects", async () => {
    mockGetApprovalQueue.mockResolvedValue([]);
    mockGetApprovalHistory.mockRejectedValue(new Error("history backend down"));
    renderWithProviders();
    // Switch to history tab
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /历史/ })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: /历史/ }));
    await waitFor(() => {
      expect(screen.getByText(/历史加载失败/)).toBeInTheDocument();
    });
  });

  it("T7: detail drawer renders gate_report keys when item clicked", async () => {
    mockGetApprovalQueue.mockResolvedValue([sampleItem]);
    mockGetApprovalDetail.mockResolvedValue(sampleDetail);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText("test_factor_alpha")).toBeInTheDocument();
    });
    // Click the expression preview (triggers detail load)
    const expr = screen.getByTitle(/点击查看完整详情/);
    await userEvent.click(expr);
    await waitFor(() => {
      // Gate report section titles render
      expect(screen.getByText("G1_novelty")).toBeInTheDocument();
      expect(screen.getByText("G2_correlation")).toBeInTheDocument();
      expect(screen.getByText("G3_significance")).toBeInTheDocument();
    });
  });
});
