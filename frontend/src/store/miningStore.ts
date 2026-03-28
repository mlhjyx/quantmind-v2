import { create } from "zustand";

export type MiningEngine = "gp" | "llm" | "brute";
export type MiningStatus = "idle" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface MiningTask {
  taskId: string;
  engine: MiningEngine;
  status: MiningStatus;
  progress: number; // 0-100
  generation?: number; // GP current generation
  totalGenerations?: number;
  discovered: number;  // factors discovered so far
  passed: number;      // passed IC gate
  startedAt: string;
  completedAt?: string;
}

interface MiningState {
  activeTaskId: string | null;
  tasks: Record<string, MiningTask>;
  setActiveTask: (taskId: string | null) => void;
  upsertTask: (task: MiningTask) => void;
  updateTask: (taskId: string, patch: Partial<MiningTask>) => void;
}

export const useMiningStore = create<MiningState>((set) => ({
  activeTaskId: null,
  tasks: {},
  setActiveTask: (taskId) => set({ activeTaskId: taskId }),
  upsertTask: (task) =>
    set((state) => ({ tasks: { ...state.tasks, [task.taskId]: task } })),
  updateTask: (taskId, patch) =>
    set((state) => {
      const existing = state.tasks[taskId];
      if (!existing) return state;
      return { tasks: { ...state.tasks, [taskId]: { ...existing, ...patch } } };
    }),
}));
