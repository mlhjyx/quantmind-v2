/**
 * PipelineConsole — iter 107 W14 fail-loud render guard tests
 *
 * Closes Frontend Design v3 §6 W14 — EMPTY_STATUS mock removed, UI must
 * fail-loud when getPipelineStatus() throws. Replaces silent fallback that
 * masked backend outage with stale cron "0 20 * * 1-5".
 *
 * Test cases:
 *   T1: Initial loading skeleton (loadingStatus && status == null)
 *   T2: Fail-loud error card when API rejects
 *   T3: Retry button re-invokes getPipelineStatus
 *   T4: Happy path renders main UI tabs when status loads
 *   T5: No EMPTY_STATUS leak — stale "0 20 * * 1-5" cron absent on error
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { PipelineStatus } from "@/api/pipeline";

// ── Mock @/api/pipeline ─────────────────────────────────────────
// Order matters: hoisted vi.mock must come BEFORE import of component-under-test

const mockGetPipelineStatus = vi.fn();
const mockGetPendingApprovals = vi.fn().mockResolvedValue([]);
const mockGetPipelineHistory = vi.fn().mockResolvedValue([]);
const mockGetPipelineLogs = vi.fn().mockResolvedValue([]);
const mockGetPipelineRun = vi.fn().mockResolvedValue({ candidates: [] });
const mockTriggerPipeline = vi.fn().mockResolvedValue({});
const mockPausePipeline = vi.fn().mockResolvedValue({});
const mockApproveItem = vi.fn().mockResolvedValue({});
const mockRejectItem = vi.fn().mockResolvedValue({});
const mockHoldItem = vi.fn().mockResolvedValue({});
const mockApproveFactor = vi.fn().mockResolvedValue({});
const mockRejectFactor = vi.fn().mockResolvedValue({});
const mockSetAutomationLevel = vi.fn().mockResolvedValue({});

vi.mock("@/api/pipeline", () => ({
  getPipelineStatus: () => mockGetPipelineStatus(),
  getPendingApprovals: () => mockGetPendingApprovals(),
  getPipelineHistory: () => mockGetPipelineHistory(),
  getPipelineLogs: () => mockGetPipelineLogs(),
  getPipelineRun: (runId: string) => mockGetPipelineRun(runId),
  triggerPipeline: () => mockTriggerPipeline(),
  pausePipeline: () => mockPausePipeline(),
  approveItem: (id: string, note?: string) => mockApproveItem(id, note),
  rejectItem: (id: string, note?: string) => mockRejectItem(id, note),
  holdItem: (id: string, note?: string) => mockHoldItem(id, note),
  approveFactor: (runId: string, factorId: number) =>
    mockApproveFactor(runId, factorId),
  rejectFactor: (runId: string, factorId: number, reason?: string) =>
    mockRejectFactor(runId, factorId, reason),
  setAutomationLevel: (level: string) => mockSetAutomationLevel(level),
}));

// Heavy child components mocked so tests focus on the guard logic
vi.mock("@/components/pipeline/FlowChart", () => ({
  FlowChart: () => <div data-testid="flow-chart" />,
}));
vi.mock("@/components/pipeline/ApprovalPanel", () => ({
  ApprovalPanel: () => <div data-testid="approval-panel" />,
}));
vi.mock("@/components/pipeline/PipelineHistory", () => ({
  PipelineHistory: () => <div data-testid="pipeline-history" />,
}));
vi.mock("@/components/ai/AssistPanel", () => ({
  AssistPanel: () => <div data-testid="assist-panel" />,
}));

// Component must be imported after vi.mock declarations
// eslint-disable-next-line import/first
import PipelineConsole from "@/pages/PipelineConsole";

const renderWithProviders = () => {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PipelineConsole />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const okStatus: PipelineStatus = {
  run_id: "abc12345-def6-7890",
  automation_level: "L1",
  is_running: false,
  is_paused: false,
  current_node: null,
  nodes: [],
  schedule_cron: "0 9 * * 1-5",
  next_run_at: null,
  last_run_at: null,
};

describe("PipelineConsole — iter 107 W14 fail-loud guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("T1: shows loading skeleton while status not yet loaded", () => {
    // Status promise hangs — initial render must show skeleton
    mockGetPipelineStatus.mockReturnValue(new Promise(() => {}));
    renderWithProviders();
    // Skeleton present, main "Pipeline 状态图" tab content NOT yet rendered
    expect(screen.queryByText(/Pipeline 状态图/)).toBeNull();
    expect(screen.queryByText(/Pipeline 状态加载失败/)).toBeNull();
  });

  it("T2: fails loud with error card when getPipelineStatus rejects", async () => {
    mockGetPipelineStatus.mockRejectedValue(new Error("network down"));
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/Pipeline 状态加载失败/)).toBeInTheDocument();
    });
    // Retry button present
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
  });

  it("T3: retry button re-invokes getPipelineStatus", async () => {
    mockGetPipelineStatus.mockRejectedValue(new Error("first fail"));
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/Pipeline 状态加载失败/)).toBeInTheDocument();
    });
    const initialCalls = mockGetPipelineStatus.mock.calls.length;
    // Setup successful retry
    mockGetPipelineStatus.mockResolvedValueOnce(okStatus);
    await userEvent.click(screen.getByRole("button", { name: /重试/ }));
    await waitFor(() => {
      expect(mockGetPipelineStatus.mock.calls.length).toBeGreaterThan(
        initialCalls,
      );
    });
  });

  it("T4: happy path renders main tabs when status loads", async () => {
    mockGetPipelineStatus.mockResolvedValue(okStatus);
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/Pipeline 状态图/)).toBeInTheDocument();
    });
    // Tab buttons rendered
    expect(
      screen.getByRole("button", { name: /状态流程/ }),
    ).toBeInTheDocument();
    // Error card NOT shown
    expect(screen.queryByText(/Pipeline 状态加载失败/)).toBeNull();
  });

  it("T5: stale '0 20 * * 1-5' EMPTY_STATUS cron does NOT leak on error path", async () => {
    mockGetPipelineStatus.mockRejectedValue(new Error("network down"));
    renderWithProviders();
    await waitFor(() => {
      expect(screen.getByText(/Pipeline 状态加载失败/)).toBeInTheDocument();
    });
    // Confirm previous EMPTY_STATUS mock cron NOT present — iter 107 W14 closure
    expect(screen.queryByText("0 20 * * 1-5")).toBeNull();
  });
});
