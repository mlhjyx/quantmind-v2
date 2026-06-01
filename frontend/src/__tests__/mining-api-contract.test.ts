import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
}));

import * as miningApi from "@/api/mining";
import type { CandidateFactor } from "@/api/mining";

describe("mining API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes backend task-detail candidates for frontend rendering", async () => {
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        task_id: "task-1",
        run_id: "gp_20260601_abc123",
        engine: "gp",
        status: "running",
        started_at: "2026-06-01T09:00:00+08:00",
        finished_at: null,
        config: { generations: 10 },
        stats: {
          n_generations_completed: 4,
          n_candidates: 1,
          n_passed: 0,
          best_fitness: 0.42,
        },
        candidates: [
          {
            id: "cand-1",
            factor_name: "alpha_one",
            factor_expr: "ts_mean(close, 20)",
            status: "pending",
            created_at: "2026-06-01T09:05:00+08:00",
            gate_report: {
              gates: {
                G1: { data: { ic_mean: 0.034, coverage: 0.91 } },
                G2: { data: { ic_ir: 0.41 } },
                G6: { data: { raw_t_stat: 2.71, fdr_t_stat: 2.55 } },
              },
            },
          },
        ],
      },
    });

    const detail = await miningApi.getMiningTaskDetail("task-1");

    expect(apiClientMock.get).toHaveBeenCalledWith("/mining/tasks/task-1");
    expect(detail).toMatchObject({
      task_id: "task-1",
      engine: "gp",
      status: "running",
      progress: 40,
      generation: 4,
      total_generations: 10,
      best_fitness: 0.42,
      discovered: 1,
      passed: 0,
      archived: 0,
      completed_at: undefined,
    });
    expect(detail.candidates[0]).toMatchObject({
      id: "cand-1",
      name: "alpha_one",
      expression: "ts_mean(close, 20)",
      engine: "gp",
      task_id: "task-1",
      ic_mean: 0.034,
      t_stat: 2.71,
      fdr_t_stat: 2.55,
      ic_ir: 0.41,
      coverage: 0.91,
      gate_status: "pending",
    });
  });

  it("builds Gate payloads from candidate expressions instead of selected ids", () => {
    expect(typeof miningApi.buildCandidateGatePayloads).toBe("function");

    const candidate: CandidateFactor = {
      id: "cand-1",
      name: "alpha_one",
      expression: "ts_mean(close, 20)",
      engine: "gp",
      task_id: "task-1",
      ic_mean: 0.034,
      t_stat: 2.71,
      fdr_t_stat: 2.55,
      ic_ir: 0.41,
      coverage: 0.91,
      gate_status: "pending",
      created_at: "2026-06-01T09:05:00+08:00",
    };

    const payloads = miningApi.buildCandidateGatePayloads(["cand-1"], [candidate]);

    expect(payloads).toEqual([{ expr: "ts_mean(close, 20)", name: "alpha_one" }]);
  });

  it("fails loudly when a selected candidate expression is missing", () => {
    const candidate: CandidateFactor = {
      id: "cand-1",
      name: "alpha_one",
      expression: "",
      engine: "gp",
      task_id: "task-1",
      ic_mean: 0,
      t_stat: 0,
      fdr_t_stat: 0,
      ic_ir: 0,
      coverage: 0,
      gate_status: "pending",
      created_at: "2026-06-01T09:05:00+08:00",
    };

    expect(() => miningApi.buildCandidateGatePayloads(["cand-1"], [candidate])).toThrow(
      /Missing candidate expression/
    );
  });
});
