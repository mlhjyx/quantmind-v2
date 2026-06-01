import { existsSync, readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

const marketApiPath = "src/api/market.ts";

async function importMarketApi() {
  expect(existsSync(marketApiPath), `${marketApiPath} should define market API wrappers`).toBe(true);

  const modulePath = "../api/" + "market";
  return import(modulePath);
}

describe("market API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches market indices through the API layer", async () => {
    const api = await importMarketApi();
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          code: "000300.SH",
          name: "沪深300",
          close: 3600,
          pre_close: 3580,
          pct_change: 0.56,
          volume: 123,
          amount: 456,
          is_up: true,
          trade_date: "2026-05-29",
        },
      ],
    });

    await expect(api.fetchMarketIndices()).resolves.toEqual([
      {
        code: "000300.SH",
        name: "沪深300",
        close: 3600,
        pre_close: 3580,
        pct_change: 0.56,
        volume: 123,
        amount: 456,
        is_up: true,
        trade_date: "2026-05-29",
      },
    ]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/market/indices");
  });

  it("fetches sectors and top movers with explicit query params", async () => {
    const api = await importMarketApi();
    apiClientMock.get
      .mockResolvedValueOnce({
        data: [{ name: "银行", pct_change: 1.2, stock_count: 42, amount: 1_000, is_up: true }],
      })
      .mockResolvedValueOnce({
        data: [{ code: "600000.SH", name: "浦发银行", industry: "银行", close: 10, pct_change: 5 }],
      });

    await expect(api.fetchMarketSectors()).resolves.toEqual([
      { name: "银行", pct_change: 1.2, stock_count: 42, amount: 1_000, is_up: true },
    ]);
    await expect(api.fetchMarketTopMovers("up", 5)).resolves.toEqual([
      { code: "600000.SH", name: "浦发银行", industry: "银行", close: 10, pct_change: 5 },
    ]);

    expect(apiClientMock.get).toHaveBeenNthCalledWith(1, "/market/sectors");
    expect(apiClientMock.get).toHaveBeenNthCalledWith(2, "/market/top-movers", {
      params: { direction: "up", limit: 5 },
    });
  });

  it("keeps MarketData behind src/api wrappers", () => {
    const source = readFileSync("src/pages/MarketData.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });
});
