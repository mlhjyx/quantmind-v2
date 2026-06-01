import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("portfolio API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes portfolio sector distribution for percentage charts", async () => {
    const api = await import("@/api/portfolio");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        { name: "银行", pct: 12.5, value: 2_500_000 },
        { name: "医药", pct: null, value: null },
      ],
    });

    const result = await api.fetchPortfolioSectorDistribution();

    expect(apiClientMock.get).toHaveBeenCalledWith(
      "/portfolio/sector-distribution",
      { params: { execution_mode: "live" } },
    );
    expect(result).toEqual([
      {
        name: "银行",
        value: 12.5,
        pct: 12.5,
        marketValue: 2_500_000,
        color: expect.any(String),
      },
      {
        name: "医药",
        value: 0,
        pct: 0,
        marketValue: 0,
        color: expect.any(String),
      },
    ]);
  });

  it("fetches daily pnl with explicit days and live execution mode", async () => {
    const api = await import("@/api/portfolio");
    apiClientMock.get.mockResolvedValueOnce({
      data: [{ trade_date: "2026-05-29", daily_return: 0.01 }],
    });

    await expect(api.fetchPortfolioDailyPnl(10)).resolves.toEqual([
      { trade_date: "2026-05-29", daily_return: 0.01 },
    ]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/portfolio/daily-pnl", {
      params: { days: 10, execution_mode: "live" },
    });
  });

  it("builds a holding-days lookup from portfolio holdings", async () => {
    const api = await import("@/api/portfolio");
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        { code: "000001.SZ", holding_days: 7 },
        { code: "600000.SH", holding_days: null },
        { code: "", holding_days: 3 },
      ],
    });

    await expect(api.fetchHoldingDaysMap()).resolves.toEqual({
      "000001.SZ": 7,
    });
    expect(apiClientMock.get).toHaveBeenCalledWith("/portfolio/holdings", {
      params: { execution_mode: "live" },
    });
  });

  it("keeps portfolio pages behind src/api wrappers", () => {
    for (const path of [
      "src/pages/Portfolio.tsx",
      "src/pages/DashboardAstock.tsx",
    ]) {
      const source = readFileSync(path, "utf8");

      expect(source).not.toContain('import apiClient from "@/api/client"');
      expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
    }
  });
});
