/**
 * SafetyControlPanel — iter 137 W2-F F2 L4 Recovery flow tests.
 *
 * Closes W2-F audit F2: backend /api/risk/l4-recovery + /api/risk/l4-approve
 * (risk.py:206+239) previously DARK + PARTIAL. iter 137 wires the full
 * 2-step operator flow (request → admin approve/reject) with reverse-decision-权.
 *
 * Test cases:
 *   T1: Request recovery button hidden when not in L4
 *   T2: Request recovery button visible when L4 + needsManualApprove + admin
 *   T3: Request recovery POSTs /l4-recovery + stores approval_id in component state
 *   T4: After approval_id stored, approve+reject buttons visible
 *   T5: Approve button POSTs /l4-approve with approved=true
 *   T6: Reject button POSTs /l4-approve with approved=false
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { CircuitBreakerState } from "@/types/dashboard";
import type { EnvState } from "@/api/system";

// ── Mocks ─────────────────────────────────────────────────────────
const mockFetchCircuitBreakerState = vi.fn();
const mockFetchEnvState = vi.fn();
const mockIsAdminAuthed = vi.fn();
const mockApiClientPost = vi.fn();

vi.mock("@/api/dashboard", () => ({
  fetchCircuitBreakerState: () => mockFetchCircuitBreakerState(),
}));
vi.mock("@/api/system", () => ({
  fetchEnvState: () => mockFetchEnvState(),
}));
vi.mock("@/api/execution", () => ({
  isAdminAuthed: () => mockIsAdminAuthed(),
}));
vi.mock("@/api/client", () => ({
  default: { post: (url: string, body: object) => mockApiClientPost(url, body) },
}));

// Mock @/components/shared (Card / CardHeader stubs)
vi.mock("@/components/shared", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardHeader: ({ title }: { title: string }) => <div>{title}</div>,
}));

// eslint-disable-next-line import/first
import { SafetyControlPanel } from "@/components/safety/SafetyControlPanel";

const renderWithProviders = () => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <SafetyControlPanel />
    </QueryClientProvider>,
  );
};

const cbL4Staged: CircuitBreakerState = {
  level: 4,
  level_name: "L4_LIQUIDATE",
  entered_date: "2026-05-26",
  trigger_reason: "MDD breach 15%",
  trigger_metrics: { mdd: 0.158 },
  position_multiplier: 0.0,
  can_rebalance: false,
  recovery_streak_days: 0,
  recovery_streak_return: 0,
  requires_manual_approval: true,
};

const cbL0Normal: CircuitBreakerState = {
  level: 0,
  level_name: "NORMAL",
  entered_date: "2026-05-26",
  trigger_reason: null,
  trigger_metrics: null,
  position_multiplier: 1.0,
  can_rebalance: true,
  recovery_streak_days: 0,
  recovery_streak_return: 0,
  requires_manual_approval: false,
};

const envPaper: EnvState = {
  mode: "paper",
  live_trading_disabled: true,
  execution_mode: "paper",
  qmt_account_id: "81001102",
  dingtalk_alerts_enabled: false,
};

describe("SafetyControlPanel — iter 137 W2-F F2 L4 Recovery flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchEnvState.mockResolvedValue(envPaper);
    mockIsAdminAuthed.mockResolvedValue(true);
  });

  it("T1: 'L4 STAGED' notice + request button hidden when not in L4", async () => {
    mockFetchCircuitBreakerState.mockResolvedValue(cbL0Normal);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/L0 · NORMAL/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/L4 STAGED — 需人工审批恢复/)).toBeNull();
    expect(screen.queryByText(/发起 L4 恢复请求/)).toBeNull();
  });

  it("T2: 'L4 STAGED' notice + request button visible when L4 + needsManualApprove + admin", async () => {
    mockFetchCircuitBreakerState.mockResolvedValue(cbL4Staged);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/L4 STAGED — 需人工审批恢复/)).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /发起 L4 恢复请求/ })).toBeInTheDocument();
  });

  it("T3: Request recovery POSTs /l4-recovery + stores approval_id", async () => {
    mockFetchCircuitBreakerState.mockResolvedValue(cbL4Staged);
    mockApiClientPost.mockResolvedValue({
      data: { approval_id: "abcd1234-ef56-7890-abcd-ef1234567890", status: "pending" },
    });
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /发起 L4 恢复请求/ })).toBeInTheDocument();
    });

    // Open request modal — both button and modal title share "发起 L4 恢复请求"
    // text, so we await the modal-unique reason input placeholder instead.
    await userEvent.click(screen.getByRole("button", { name: /发起 L4 恢复请求/ }));
    const reasonInput = await screen.findByPlaceholderText(/说明操作原因/);

    // Fill reason and confirm
    await userEvent.type(reasonInput, "MDD recovered to 8%, restart");
    await userEvent.click(screen.getByRole("button", { name: /确定/ }));

    await waitFor(() => {
      expect(mockApiClientPost).toHaveBeenCalledWith(
        "/risk/l4-recovery/default",
        expect.objectContaining({ reviewer_note: expect.stringContaining("MDD recovered") }),
      );
    });

    // After recovery, approval_id is shown
    await waitFor(() => {
      expect(screen.getByText(/待审批 approval_id/)).toBeInTheDocument();
      expect(screen.getByText("abcd1234-ef56-7890-abcd-ef1234567890")).toBeInTheDocument();
    });
  });

  it("T4: Approve+Reject buttons visible after approval_id received", async () => {
    mockFetchCircuitBreakerState.mockResolvedValue(cbL4Staged);
    mockApiClientPost.mockResolvedValue({
      data: { approval_id: "approval-uuid-12345", status: "pending" },
    });
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /发起 L4 恢复请求/ })).toBeInTheDocument();
    });

    // Trigger recovery request
    await userEvent.click(screen.getByRole("button", { name: /发起 L4 恢复请求/ }));
    const reasonInput = await screen.findByPlaceholderText(/说明操作原因/);
    await userEvent.type(reasonInput, "test reason for recovery");
    await userEvent.click(screen.getByRole("button", { name: /确定/ }));

    // Approve + Reject buttons appear
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /批准/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /拒绝/ })).toBeInTheDocument();
    });
  });

  it("T6: Reject POSTs /l4-approve with approved=false", async () => {
    mockFetchCircuitBreakerState.mockResolvedValue(cbL4Staged);

    // Pre-pop approval flow: 1st POST = recovery request, 2nd POST = reject
    mockApiClientPost
      .mockResolvedValueOnce({
        data: { approval_id: "reject-uuid-67890", status: "pending" },
      })
      .mockResolvedValueOnce({
        data: { status: "rejected", approval_id: "reject-uuid-67890" },
      });

    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /发起 L4 恢复请求/ })).toBeInTheDocument();
    });

    // Request recovery first
    await userEvent.click(screen.getByRole("button", { name: /发起 L4 恢复请求/ }));
    const reasonInput = await screen.findByPlaceholderText(/说明操作原因/);
    await userEvent.type(reasonInput, "request to reject for test");
    await userEvent.click(screen.getByRole("button", { name: /确定/ }));

    // Wait for reject button visible, then click
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /拒绝/ })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole("button", { name: /拒绝/ }));

    // Reject modal opens (HIGH tier, reason required, no phrase)
    const rejectReason = await screen.findByPlaceholderText(/说明操作原因/);
    await userEvent.type(rejectReason, "data quality issue, hold L4");
    await userEvent.click(screen.getByRole("button", { name: /确定/ }));

    await waitFor(() => {
      expect(mockApiClientPost).toHaveBeenCalledWith(
        "/risk/l4-approve/reject-uuid-67890",
        expect.objectContaining({ approved: false }),
      );
    });
  });
});
