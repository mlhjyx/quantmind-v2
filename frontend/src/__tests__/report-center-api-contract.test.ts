import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("report center API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches report history through the reports API layer", async () => {
    const api = await import("@/api/reports");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          run_id: "run-1",
          name: "回测报告",
          status: "completed",
          annual_return: 0.12,
          sharpe_ratio: 1.1,
          max_drawdown: -0.08,
          total_trades: 42,
          start_date: "2026-01-01",
          end_date: "2026-05-29",
          created_at: "2026-05-29T16:00:00",
        },
      ],
    });

    expect(typeof api.listReportHistory).toBe("function");
    await expect(api.listReportHistory()).resolves.toEqual([
      {
        run_id: "run-1",
        name: "回测报告",
        status: "completed",
        annual_return: 0.12,
        sharpe_ratio: 1.1,
        max_drawdown: -0.08,
        total_trades: 42,
        start_date: "2026-01-01",
        end_date: "2026-05-29",
        created_at: "2026-05-29T16:00:00",
      },
    ]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/reports/list", {
      params: {},
    });
  });

  it("fetches report quick stats with explicit strategy params", async () => {
    const api = await import("@/api/reports");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        today: { return: 0.01, trade_days: 1, avg_turnover: 0.2 },
        week: { return: 0.02, trade_days: 5, avg_turnover: 0.18 },
        month: { return: 0.03, trade_days: 20, avg_turnover: 0.16 },
        year: { return: 0.04, trade_days: 100, avg_turnover: 0.14 },
        latest_position_count: 5,
        as_of: "2026-05-29",
      },
    });

    expect(typeof api.fetchReportQuickStats).toBe("function");
    const result = await api.fetchReportQuickStats({
      strategy_id: "11111111-1111-1111-1111-111111111111",
      execution_mode: "paper",
    });

    expect(result.latest_position_count).toBe(5);
    expect(result.year.trade_days).toBe(100);
    expect(apiClientMock.get).toHaveBeenCalledWith("/reports/quick-stats", {
      params: {
        strategy_id: "11111111-1111-1111-1111-111111111111",
        execution_mode: "paper",
      },
    });
  });

  it("keeps ReportCenter behind src/api wrappers", () => {
    const source = readFileSync("src/pages/ReportCenter.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });
});
