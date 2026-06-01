/**
 * Mining UI transport contract tests.
 *
 * Backend mining APIs document polling through /api/mining/tasks/{task_id};
 * there is no /ws/factor-mine/{id} Socket.IO namespace or native route.
 */

import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type SocketHandler = (...args: unknown[]) => void;

const mockSocket = {
  connected: false,
  disconnect: vi.fn(),
  emit: vi.fn(),
  off: vi.fn(),
  on: vi.fn((_event: string, _handler: SocketHandler) => mockSocket),
};
const mockIo = vi.fn(() => mockSocket);

vi.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));

const miningStoreState = vi.hoisted(() => ({
  activeTaskId: null as string | null,
  tasks: {} as Record<string, unknown>,
  setActiveTask: vi.fn(),
  upsertTask: vi.fn(),
  updateTask: vi.fn(),
}));

vi.mock("@/store/miningStore", () => ({
  useMiningStore: () => miningStoreState,
}));

const miningApiMocks = vi.hoisted(() => ({
  archiveMiningTask: vi.fn(),
  cancelMiningTask: vi.fn(),
  getEngineStats: vi.fn(),
  getMiningTaskDetail: vi.fn(),
  getMiningTasks: vi.fn(),
  pauseMiningTask: vi.fn(),
  retryMiningTask: vi.fn(),
  startBruteForceMining: vi.fn(),
  startGPMining: vi.fn(),
  startLLMMining: vi.fn(),
  submitCandidatesToGate: vi.fn(),
}));

vi.mock("@/api/mining", () => miningApiMocks);

vi.mock("@/components/mining/GPPanel", () => ({
  GPPanel: () => <div data-testid="gp-panel" />,
}));
vi.mock("@/components/mining/LLMPanel", () => ({
  LLMPanel: () => <div data-testid="llm-panel" />,
}));
vi.mock("@/components/mining/BruteForcePanel", () => ({
  BruteForcePanel: () => <div data-testid="bruteforce-panel" />,
}));
vi.mock("@/components/mining/CandidateTable", () => ({
  CandidateTable: () => <div data-testid="candidate-table" />,
}));
vi.mock("@/components/ai/AssistPanel", () => ({
  AssistPanel: () => <div data-testid="assist-panel" />,
}));
vi.mock("recharts", () => ({
  Bar: () => null,
  BarChart: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  CartesianGrid: () => null,
  Legend: () => null,
  Line: () => null,
  LineChart: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

// eslint-disable-next-line import/first
import FactorLab from "@/pages/FactorLab";
// eslint-disable-next-line import/first
import MiningTaskCenter from "@/pages/MiningTaskCenter";

function renderRoute(ui: React.ReactElement, path = "/mining") {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

const runningTask = {
  task_id: "task-running-1",
  engine: "gp",
  status: "running",
  progress: 25,
  generation: 5,
  total_generations: 20,
  best_fitness: 0.12,
  discovered: 3,
  passed: 1,
  archived: 0,
  started_at: "2026-06-01T04:00:00Z",
  completed_at: undefined,
};

describe("mining websocket contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSocket.connected = false;
    miningStoreState.activeTaskId = null;
    miningStoreState.tasks = {};
    miningApiMocks.getEngineStats.mockResolvedValue([]);
    miningApiMocks.getMiningTaskDetail.mockResolvedValue({
      ...runningTask,
      task_id: "task-running-1",
      config: {},
      candidates: [],
      evolution_history: [],
    });
    miningApiMocks.getMiningTasks.mockResolvedValue([runningTask]);
  });

  afterEach(() => {
    cleanup();
  });

  it("FactorLab polls task detail without opening unsupported /ws/factor-mine", async () => {
    miningStoreState.activeTaskId = "task-running-1";
    miningStoreState.tasks = {
      "task-running-1": {
        taskId: "task-running-1",
        engine: "gp",
        status: "running",
        progress: 25,
        discovered: 3,
        passed: 1,
        startedAt: "2026-06-01T04:00:00Z",
      },
    };

    renderRoute(<FactorLab />);

    await waitFor(() => {
      expect(miningApiMocks.getMiningTaskDetail).toHaveBeenCalledWith("task-running-1");
    });

    expect(mockIo).not.toHaveBeenCalledWith(
      expect.stringContaining("/ws/factor-mine"),
      expect.anything(),
    );
  });

  it("MiningTaskCenter uses the tasks polling endpoint without opening /ws/factor-mine", async () => {
    renderRoute(<MiningTaskCenter />, "/mining/tasks");

    await waitFor(() => {
      expect(screen.getByText("task-run...")).toBeInTheDocument();
    });

    expect(miningApiMocks.getMiningTasks).toHaveBeenCalled();
    expect(mockIo).not.toHaveBeenCalledWith(
      expect.stringContaining("/ws/factor-mine"),
      expect.anything(),
    );
  });
});
