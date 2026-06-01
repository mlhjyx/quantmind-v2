import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("dashboard API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("exposes wrapper functions for dashboard secondary panels", async () => {
    const api = await import("@/api/dashboard");

    expect(typeof api.fetchAlerts).toBe("function");
    expect(typeof api.fetchMonthlyReturns).toBe("function");
    expect(typeof api.fetchIndustryDistribution).toBe("function");
    expect(typeof api.fetchDashboardFactorRows).toBe("function");
    expect(typeof api.fetchDashboardPipelineSteps).toBe("function");
  });

  it("fetches dashboard alerts through the API layer", async () => {
    const api = await import("@/api/dashboard");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          level: "P1",
          color: "#f59e0b",
          title: "Risk alert",
          desc: "Drawdown warning",
          time: "09:31",
        },
      ],
    });

    const result = await api.fetchAlerts();

    expect(apiClientMock.get).toHaveBeenCalledWith("/dashboard/alerts", {
      params: { hours: 24 },
    });
    expect(result).toEqual([
      {
        level: "P1",
        color: "#f59e0b",
        title: "Risk alert",
        desc: "Drawdown warning",
        time: "09:31",
      },
    ]);
  });

  it("fetches monthly returns and industry distribution through API wrappers", async () => {
    const api = await import("@/api/dashboard");
    apiClientMock.get
      .mockResolvedValueOnce({ data: { "2026": [0.01, null, -0.02] } })
      .mockResolvedValueOnce({
        data: [{ name: "银行", pct: 12.5, color: "#60a5fa" }],
      });

    await expect(api.fetchMonthlyReturns()).resolves.toEqual({
      "2026": [0.01, null, -0.02],
    });
    await expect(api.fetchIndustryDistribution()).resolves.toEqual([
      { name: "银行", pct: 12.5, color: "#60a5fa" },
    ]);

    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      1,
      "/dashboard/monthly-returns",
      { params: { execution_mode: "live" } },
    );
    expect(apiClientMock.get).toHaveBeenNthCalledWith(
      2,
      "/dashboard/industry-distribution",
      { params: { execution_mode: "live" } },
    );
  });

  it("normalizes factor rows for the dashboard factor panel", async () => {
    const api = await import("@/api/dashboard");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          name: "bp_ratio",
          category: "基本面",
          direction: "positive",
          status: "active",
          ic_mean: 0.031,
          ic_ir: 0.62,
        },
        {
          name: "turnover_mean_20",
          category: null,
          direction: "negative",
          status: "candidate",
          ic_mean: null,
          ic_ir: null,
        },
      ],
    });

    const result = await api.fetchDashboardFactorRows();

    expect(apiClientMock.get).toHaveBeenCalledWith("/factors");
    expect(result).toEqual([
      {
        name: "bp_ratio",
        cat: "基本面",
        ic: 0.031,
        ir: 0.62,
        dir: "正向",
        status: "active",
        trend: [],
      },
      {
        name: "turnover_mean_20",
        cat: "未知",
        ic: 0,
        ir: 0,
        dir: "反向",
        status: "new",
        trend: [],
      },
    ]);
  });

  it("normalizes legacy pipeline status into dashboard steps", async () => {
    const api = await import("@/api/dashboard");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        status: "running",
        current_node: "evaluate",
        node_statuses: {
          fetch: "completed",
          evaluate: "pending",
          archive: "idle",
        },
      },
    });

    const result = await api.fetchDashboardPipelineSteps();

    expect(apiClientMock.get).toHaveBeenCalledWith("/pipeline/status");
    expect(result).toEqual([
      { name: "fetch", status: "done" },
      { name: "evaluate", status: "running" },
      { name: "archive", status: "idle" },
    ]);
  });

  it("keeps DashboardOverview behind src/api wrappers", () => {
    const source = readFileSync("src/pages/Dashboard/index.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });
});
