import { create } from "zustand";

export type BacktestStatus = "idle" | "running" | "completed" | "failed" | "cancelled";

export interface BacktestRun {
  runId: string;
  strategyId: string;
  strategyName: string;
  status: BacktestStatus;
  progress: number; // 0-100
  startedAt: string;
  completedAt?: string;
  sharpe?: number;
  mdd?: number;
}

interface BacktestState {
  activeRunId: string | null;
  runs: Record<string, BacktestRun>;
  setActiveRun: (runId: string | null) => void;
  upsertRun: (run: BacktestRun) => void;
  updateProgress: (runId: string, progress: number) => void;
  setStatus: (runId: string, status: BacktestStatus) => void;
}

export const useBacktestStore = create<BacktestState>((set) => ({
  activeRunId: null,
  runs: {},
  setActiveRun: (runId) => set({ activeRunId: runId }),
  upsertRun: (run) =>
    set((state) => ({ runs: { ...state.runs, [run.runId]: run } })),
  updateProgress: (runId, progress) =>
    set((state) => {
      const existing = state.runs[runId];
      if (!existing) return state;
      return { runs: { ...state.runs, [runId]: { ...existing, progress } } };
    }),
  setStatus: (runId, status) =>
    set((state) => {
      const existing = state.runs[runId];
      if (!existing) return state;
      return { runs: { ...state.runs, [runId]: { ...existing, status } } };
    }),
}));
