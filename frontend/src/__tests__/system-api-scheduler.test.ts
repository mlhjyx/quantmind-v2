import { beforeEach, describe, expect, it, type Mock, vi } from "vitest";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import { fetchSchedulerTasks } from "@/api/system";

const get = apiClient.get as unknown as Mock;

describe("fetchSchedulerTasks", () => {
  beforeEach(() => vi.clearAllMocks());

  it("preserves disabled task state and IC monitor alert semantics", async () => {
    get.mockResolvedValue({
      data: {
        platform: "Windows",
        task_count: 2,
        tasks: [
          {
            task_name: "QM-SmokeTest",
            schedule: "",
            last_run: "2026-04-06 20:05:01",
            next_run: "2026-05-28 04:05:00",
            task_state: "Disabled",
            enabled: false,
            status: "disabled",
            last_result_code: 3221225786,
          },
          {
            task_name: "QM-ICMonitor",
            schedule: "",
            last_run: "2026-05-24 20:00:00",
            next_run: "2026-05-31 20:00:00",
            task_state: "Ready",
            enabled: true,
            status: "alert",
            last_result_code: 1,
          },
        ],
      },
    });

    const result = await fetchSchedulerTasks();

    expect(get).toHaveBeenCalledWith("/system/scheduler");
    expect(result[0]).toMatchObject({
      name: "QM-SmokeTest",
      enabled: false,
      task_state: "Disabled",
      last_status: "disabled",
      last_result_code: 3221225786,
    });
    expect(result[1]).toMatchObject({
      name: "QM-ICMonitor",
      enabled: true,
      task_state: "Ready",
      last_status: "alert",
      last_result_code: 1,
    });
  });

  it("normalizes backend never_run to UI never status", async () => {
    get.mockResolvedValue({
      data: {
        platform: "Windows",
        task_count: 1,
        tasks: [
          {
            task_name: "QM-NewTask",
            schedule: "",
            last_run: "",
            next_run: "",
            task_state: "Ready",
            enabled: true,
            status: "never_run",
            last_result_code: 267011,
          },
        ],
      },
    });

    const result = await fetchSchedulerTasks();

    expect(result[0]?.last_status).toBe("never");
  });
});
