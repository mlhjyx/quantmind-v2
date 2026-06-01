import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  defaults: { baseURL: "/api" },
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("BacktestResults detail endpoint contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("maps monthly detail rows into BacktestResults heatmap data", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.get.mockResolvedValueOnce({
      data: [{ year: 2026, month: 1, monthly_return: "0.0345", trading_days: 20 }],
    });

    await expect(api.getBacktestMonthlyReturns("run-1")).resolves.toEqual([
      { year: 2026, month: 1, return: 0.0345 },
    ]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/backtest/run-1/monthly");
  });

  it("loads latest holdings by first reading the holdings summary date", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.get
      .mockResolvedValueOnce({
        data: [
          { trade_date: "2026-01-02", holding_count: 2, total_market_value: "1000" },
          { trade_date: "2026-01-03", holding_count: 2, total_market_value: "1200" },
        ],
      })
      .mockResolvedValueOnce({
        data: [
          {
            trade_date: "2026-01-03",
            stock_code: "600000",
            shares: 100,
            cost_basis: "10.00",
            market_price: "10.50",
            market_value: "1050.00",
            weight: "0.1234",
            pnl: "50.00",
            industry_code: "bank",
          },
        ],
      });

    await expect(api.getBacktestLatestHoldings("run-1")).resolves.toMatchObject([
      {
        symbol: "600000",
        name: "600000",
        industry: "bank",
        weight: 0.1234,
        return: 50 / 1050,
      },
    ]);
    expect(apiClientMock.get).toHaveBeenNthCalledWith(1, "/backtest/run-1/holdings");
    expect(apiClientMock.get).toHaveBeenNthCalledWith(2, "/backtest/run-1/holdings", {
      params: { trade_date: "2026-01-03" },
    });
  });

  it("maps paged trade rows into BacktestResults trade table data", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.get.mockResolvedValueOnce({
      data: {
        total: 1,
        page: 1,
        page_size: 1000,
        items: [
          {
            id: "trade-1",
            signal_date: "2026-01-02",
            exec_date: "2026-01-03",
            stock_code: "600000",
            side: "buy",
            shares: 100,
            exec_price: "10.50",
            commission: "3.00",
            stamp_tax: "1.00",
            transfer_fee: null,
            slippage_bps: "2.50",
            total_cost: "4.00",
          },
        ],
      },
    });

    await expect(api.getBacktestTradesForResult("run-1")).resolves.toMatchObject([
      {
        date: "2026-01-03",
        symbol: "600000",
        direction: "buy",
        price: 10.5,
        quantity: 100,
        amount: 1050,
        commission: 4,
        slippage: 2.5,
        pnl: null,
      },
    ]);
  });

  it("maps annual rows into risk metric cards", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          year: 2026,
          annual_return: "0.1234",
          sharpe_ratio: "1.2345",
          trading_days: 80,
          worst_day: "-0.0456",
        },
      ],
    });

    await expect(api.getBacktestAnnualRiskMetrics("run-1")).resolves.toMatchObject([
      { label: "年度收益", value: 0.1234 },
      { label: "年度Sharpe", value: 1.2345 },
      { label: "最差单日", value: -0.0456 },
      { label: "交易日", value: 80 },
    ]);
  });

  it("exposes attribution, cost, market-state, live-compare, and report endpoints", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.get
      .mockResolvedValueOnce({
        data: {
          method: "brinson",
          industries: [{ industry: "bank", stock_count: 3, total_weight: "0.4", avg_pnl: "12.5" }],
        },
      })
      .mockResolvedValueOnce({ data: { rows: [{ cost_multiplier: 1, annual_return: "0.1" }] } })
      .mockResolvedValueOnce({ data: { states: [{ market_state: "bull", sharpe_estimate: "0.9" }] } })
      .mockResolvedValueOnce({ data: { backtest: { annual_return: "0.1" }, live: null } });

    await expect(api.getBacktestAttribution("run-1")).resolves.toMatchObject({
      method: "brinson",
      industries: [{ industry: "bank", stock_count: 3, total_weight: 0.4, avg_pnl: 12.5 }],
    });
    await expect(api.getBacktestCostSensitivity("run-1")).resolves.toMatchObject({
      rows: [{ cost_multiplier: 1, annual_return: 0.1 }],
    });
    await expect(api.getBacktestMarketState("run-1")).resolves.toMatchObject({
      states: [{ market_state: "bull", sharpe_estimate: 0.9 }],
    });
    await expect(api.getBacktestLiveCompare("run-1")).resolves.toMatchObject({
      backtest: { annual_return: 0.1 },
      live: null,
    });
    expect(api.getBacktestReportUrl("run-1")).toBe("/api/backtest/run-1/report");
  });

  it("renders BacktestResults through detail wrappers instead of sparse /result only", () => {
    const source = readFileSync("src/pages/BacktestResults.tsx", "utf8");

    expect(source).toContain("getBacktestMonthlyReturns");
    expect(source).toContain("getBacktestLatestHoldings");
    expect(source).toContain("getBacktestTradesForResult");
    expect(source).toContain("getBacktestAnnualRiskMetrics");
    expect(source).toContain("getBacktestAttribution");
    expect(source).toContain("getBacktestCostSensitivity");
    expect(source).toContain("getBacktestMarketState");
    expect(source).toContain("getBacktestLiveCompare");
    expect(source).toContain("getBacktestReportUrl");
    expect(source).toContain('activeTab === "attribution"');
    expect(source).toContain('activeTab === "cost"');
    expect(source).toContain('activeTab === "market"');
    expect(source).toContain('activeTab === "live"');
  });
});
