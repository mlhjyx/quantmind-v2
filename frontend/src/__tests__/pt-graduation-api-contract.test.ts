import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("PT graduation API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches graduation status through the dashboard API layer", async () => {
    const api = await import("@/api/dashboard");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        days_running: 30,
        sharpe: 0.8,
        mdd: -0.12,
        slippage_deviation: 0.2,
        graduate_ready: false,
        criteria: [
          {
            name: "Sharpe",
            target: ">= 0.72",
            actual: "0.800",
            passed: true,
          },
        ],
      },
    });

    expect(typeof api.fetchPaperGraduationStatus).toBe("function");
    await expect(api.fetchPaperGraduationStatus("live")).resolves.toMatchObject({
      days_running: 30,
      sharpe: 0.8,
      criteria: [{ name: "Sharpe", passed: true }],
    });
    expect(apiClientMock.get).toHaveBeenCalledWith(
      "/paper-trading/graduation-status",
      { params: { execution_mode: "live" } },
    );
  });

  it("keeps PTGraduation behind src/api wrappers", () => {
    const source = readFileSync("src/pages/PTGraduation.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });

  it("fetches paper trading status through the dashboard API layer", async () => {
    const api = await import("@/api/dashboard");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        nav: 1_020_000,
        position_count: 5,
        running_days: 42,
        sharpe: 0.74,
        mdd: -0.08,
        total_return: 0.02,
        trade_date: "2026-06-01",
        graduation_ready: false,
      },
    });

    expect(typeof api.fetchPaperTradingStatus).toBe("function");
    await expect(api.fetchPaperTradingStatus("strategy-1")).resolves.toMatchObject({
      nav: 1_020_000,
      running_days: 42,
      graduation_ready: false,
    });
    expect(apiClientMock.get).toHaveBeenCalledWith(
      "/paper-trading/status",
      { params: { strategy_id: "strategy-1" } },
    );
  });

  it("keeps PtStatus behind the paper trading status wrapper", () => {
    const source = readFileSync("src/pages/PtStatus.tsx", "utf8");

    expect(source).toContain("fetchPaperTradingStatus");
    expect(source).toContain("paper-trading-status");
    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });
});
