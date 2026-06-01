import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BacktestResults from "@/pages/BacktestResults";

const apiMocks = vi.hoisted(() => ({
  getBacktestAnnualRiskMetrics: vi.fn(),
  getBacktestAttribution: vi.fn(),
  getBacktestCostSensitivity: vi.fn(),
  getBacktestLatestHoldings: vi.fn(),
  getBacktestLiveCompare: vi.fn(),
  getBacktestMarketState: vi.fn(),
  getBacktestMonthlyReturns: vi.fn(),
  getBacktestReportUrl: vi.fn(),
  getBacktestResult: vi.fn(),
  getBacktestTradesForResult: vi.fn(),
}));

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="chart" />,
}));

vi.mock("@/api/backtest", async () => {
  const actual = await vi.importActual<typeof import("@/api/backtest")>("@/api/backtest");
  return {
    ...actual,
    ...apiMocks,
  };
});

function renderBacktestResults() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/backtest/run-1/results"]}>
        <Routes>
          <Route path="/backtest/:runId/results" element={<BacktestResults />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BacktestResults detail tabs render", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getBacktestResult.mockResolvedValue({
      run_id: "run-1",
      strategy_id: "strategy-1",
      strategy_name: "CORE3",
      status: "completed",
      created_at: "2026-01-01T00:00:00",
      completed_at: "2026-01-04T00:00:00",
      metrics: {
        annual_return: 0.12,
        sharpe: 1.1,
        dsr: 0.8,
        mdd: -0.1,
        calmar: 1.2,
        annual_turnover: 1.5,
        net_return_after_cost: 0.11,
        wf_oos_sharpe: null,
      },
      nav: [{ date: "2026-01-01", strategy: 1, benchmark: 1, excess: 0, drawdown: 0 }],
      monthly_returns: [],
      holdings: [],
      trades: [],
      risk_metrics: [],
      factor_contributions: [],
      wf_windows: null,
      config_snapshot: {},
    });
    apiMocks.getBacktestMonthlyReturns.mockResolvedValue([
      { year: 2026, month: 1, return: 0.02 },
    ]);
    apiMocks.getBacktestLatestHoldings.mockResolvedValue([
      { symbol: "600000", name: "600000", industry: "bank", weight: 0.2, return: 0.01 },
    ]);
    apiMocks.getBacktestTradesForResult.mockResolvedValue([
      {
        date: "2026-01-03",
        symbol: "600000",
        name: "600000",
        direction: "buy",
        price: 10.5,
        quantity: 100,
        amount: 1050,
        commission: 4,
        slippage: 2.5,
        pnl: null,
      },
    ]);
    apiMocks.getBacktestAnnualRiskMetrics.mockResolvedValue([
      { label: "年度收益", value: 0.12, unit: "%" },
    ]);
    apiMocks.getBacktestAttribution.mockResolvedValue({
      run_id: "run-1",
      method: "brinson",
      note: null,
      industries: [{ industry: "bank", stock_count: 3, total_weight: 0.4, avg_pnl: 12.5 }],
    });
    apiMocks.getBacktestCostSensitivity.mockResolvedValue({
      run_id: "run-1",
      total_cost_base: 4,
      trade_count: 1,
      rows: [{ cost_multiplier: 1, label: "基准", annual_return: 0.1, sharpe_ratio: 0.9, max_drawdown: -0.1, calmar_ratio: 1 }],
      warning: null,
    });
    apiMocks.getBacktestMarketState.mockResolvedValue({
      run_id: "run-1",
      method: "MA120",
      states: [{ market_state: "bull", trading_days: 120, avg_daily_return: 0.001, std_daily_return: 0.01, cumulative_return: 0.12, worst_day: -0.02, best_day: 0.03, sharpe_estimate: 1.1 }],
    });
    apiMocks.getBacktestLiveCompare.mockResolvedValue({
      run_id: "run-1",
      backtest: { annual_return: 0.1, sharpe_ratio: 0.9, max_drawdown: -0.1 },
      live: null,
      note: "暂无实盘数据",
    });
    apiMocks.getBacktestReportUrl.mockReturnValue("/api/backtest/run-1/report");
  });

  it("loads detail wrappers and switches through newly wired tabs", async () => {
    renderBacktestResults();

    expect(await screen.findByText("回测结果分析")).toBeInTheDocument();
    await waitFor(() => {
      expect(apiMocks.getBacktestMonthlyReturns).toHaveBeenCalledWith("run-1");
      expect(apiMocks.getBacktestAttribution).toHaveBeenCalledWith("run-1");
      expect(apiMocks.getBacktestLiveCompare).toHaveBeenCalledWith("run-1");
    });

    for (const tab of ["行业归因", "成本敏感性", "市场状态", "实盘对比"]) {
      expect(screen.getByRole("button", { name: tab })).toBeInTheDocument();
    }

    await userEvent.click(screen.getByRole("button", { name: "行业归因" }));
    expect(await screen.findByText("bank")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "成本敏感性" }));
    expect(await screen.findByText("基准")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "市场状态" }));
    expect(await screen.findByText("bull")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "实盘对比" }));
    expect(await screen.findByText("暂无实盘数据")).toBeInTheDocument();
  });
});
