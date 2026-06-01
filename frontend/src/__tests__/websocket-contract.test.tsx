/**
 * Frontend WebSocket contract tests.
 *
 * Guards browser callers against drifting from backend/app/websocket/manager.py:
 * FastAPI mounts Socket.IO at /ws/socket.io and backtest rooms are joined with
 * the join_backtest event. Pipeline has no native /ws/pipeline route.
 */

import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

type SocketHandler = (...args: unknown[]) => void;

const socketHandlers = new Map<string, SocketHandler>();
const mockSocket = {
  connected: false,
  disconnect: vi.fn(),
  emit: vi.fn(),
  off: vi.fn(),
  on: vi.fn((event: string, handler: SocketHandler) => {
    socketHandlers.set(event, handler);
    return mockSocket;
  }),
};
const mockIo = vi.fn(() => mockSocket);

vi.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));

const mockGetBacktestProgress = vi.fn();
vi.mock("@/api/backtest", () => ({
  getBacktestProgress: (runId: string) => mockGetBacktestProgress(runId),
}));

const mockGetPipelineStatus = vi.fn();
vi.mock("@/api/pipeline", () => ({
  getPipelineStatus: () => mockGetPipelineStatus(),
  getPendingApprovals: vi.fn().mockResolvedValue([]),
  getPipelineHistory: vi.fn().mockResolvedValue([]),
  getPipelineLogs: vi.fn().mockResolvedValue([]),
  getPipelineRun: vi.fn().mockResolvedValue({ candidates: [] }),
  triggerPipeline: vi.fn().mockResolvedValue({}),
  pausePipeline: vi.fn().mockResolvedValue({}),
  resumePipeline: vi.fn().mockResolvedValue({}),
  cancelPipeline: vi.fn().mockResolvedValue({}),
  approveItem: vi.fn().mockResolvedValue({}),
  rejectItem: vi.fn().mockResolvedValue({}),
  holdItem: vi.fn().mockResolvedValue({}),
  approveFactor: vi.fn().mockResolvedValue({}),
  rejectFactor: vi.fn().mockResolvedValue({}),
  setAutomationLevel: vi.fn().mockResolvedValue({}),
}));

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

// eslint-disable-next-line import/first
import { useBacktestProgress } from "@/hooks/useBacktestProgress";
// eslint-disable-next-line import/first
import PipelineConsole from "@/pages/PipelineConsole";

function BacktestProgressHarness({ runId }: { runId?: string }) {
  const state = useBacktestProgress({ runId, enabled: !!runId });
  return <div data-testid="connection">{state.isConnected ? "connected" : "offline"}</div>;
}

function renderPipeline() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <PipelineConsole />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("frontend websocket contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    socketHandlers.clear();
    mockSocket.connected = false;
  });

  it("connects backtest progress to the backend Socket.IO path and joins the run room", () => {
    render(<BacktestProgressHarness runId="run-abc" />);

    expect(mockIo).toHaveBeenCalledWith(
      "",
      expect.objectContaining({
        path: "/ws/socket.io",
      }),
    );

    act(() => {
      mockSocket.connected = true;
      socketHandlers.get("connect")?.();
    });

    expect(mockSocket.emit).toHaveBeenCalledWith("join_backtest", { run_id: "run-abc" });
    expect(screen.getByTestId("connection")).toHaveTextContent("connected");
  });

  it("does not open an unsupported native /ws/pipeline connection", async () => {
    const websocketCtor = vi.fn();
    vi.stubGlobal("WebSocket", websocketCtor);
    mockGetPipelineStatus.mockResolvedValue({
      run_id: "pipeline-run-1",
      automation_level: "L1",
      is_running: true,
      is_paused: false,
      current_node: null,
      nodes: [],
      schedule_cron: "0 9 * * 1-5",
      next_run_at: null,
      last_run_at: null,
    });

    renderPipeline();

    await waitFor(() => {
      expect(screen.getByText(/Pipeline 状态图/)).toBeInTheDocument();
    });
    expect(websocketCtor).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
