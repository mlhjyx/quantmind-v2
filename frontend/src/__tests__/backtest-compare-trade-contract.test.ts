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

describe("BacktestCompare trade diff contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches per-run trade pages through the backtest API layer", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.get.mockResolvedValueOnce({
      data: {
        total: 1,
        page: 2,
        page_size: 25,
        items: [
          {
            id: 7,
            signal_date: "2026-01-02",
            exec_date: "2026-01-03",
            stock_code: "000001.SZ",
            side: "buy",
            shares: 100,
            exec_price: 12.34,
          },
        ],
      },
    });

    expect(typeof api.getBacktestTrades).toBe("function");
    await expect(
      api.getBacktestTrades("run-1", { page: 2, pageSize: 25 }),
    ).resolves.toMatchObject({
      total: 1,
      page: 2,
      items: [{ stock_code: "000001.SZ", side: "buy" }],
    });
    expect(apiClientMock.get).toHaveBeenCalledWith("/backtest/run-1/trades", {
      params: { page: 2, page_size: 25 },
    });
  });

  it("normalizes live compare metric strings before the page renders them", async () => {
    const api = await import("@/api/backtest");

    apiClientMock.post.mockResolvedValueOnce({
      data: [
        {
          run_id: "run-1",
          strategy_id: "strategy-1",
          run_name: null,
          status: "completed",
          start_date: "2024-01-01",
          end_date: "2024-12-31",
          annual_return: "0.3557",
          sharpe_ratio: "0.7774",
          max_drawdown: "-0.2276",
          calmar_ratio: "1.5630",
          total_turnover: null,
          win_rate: "0.4250",
          annual_turnover: "6.2993",
          sortino_ratio: "0.9606",
          factor_list: ["turnover_mean_20", "bp_ratio"],
          config_yaml_hash: null,
          git_commit: null,
        },
      ],
    });

    await expect(api.compareBacktests(["run-1"])).resolves.toMatchObject([
      {
        run_id: "run-1",
        annual_return: 0.3557,
        sharpe_ratio: 0.7774,
        max_drawdown: -0.2276,
        annual_turnover: 6.2993,
        sortino_ratio: 0.9606,
        factor_list: ["turnover_mean_20", "bp_ratio"],
      },
    ]);
    expect(apiClientMock.post).toHaveBeenCalledWith("/backtest/compare", {
      run_ids: ["run-1"],
    });
  });

  it("renders BacktestCompare S5 through the trade wrapper", () => {
    const source = readFileSync("src/pages/BacktestCompare.tsx", "utf8");

    expect(source).toContain("getBacktestTrades");
    expect(source).toContain("S5");
    expect(source).toContain("TradeListDiff");
  });
});
