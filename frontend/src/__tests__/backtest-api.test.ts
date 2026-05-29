/**
 * Backtest API contract tests.
 *
 * Guards the UI submit payload against backend BacktestRunRequest drift.
 */

import { describe, expect, it, vi, beforeEach, type Mock } from "vitest";

vi.mock("@/api/client", () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import { buildRunBacktestPayload, runBacktest, type BacktestConfigFormPayload } from "@/api/backtest";

const post = apiClient.post as unknown as Mock;

function sampleForm(overrides: Partial<BacktestConfigFormPayload> = {}): BacktestConfigFormPayload {
  return {
    strategy_id: "strategy-123",
    market: {
      market: "astock",
      universe: "hs300",
      industries: ["银行"],
      custom_stocks: "",
    },
    time_range: {
      start_date: "2023-01-01",
      end_date: "2023-12-31",
      preset: "1y",
      exclude_2015: false,
      exclude_2020: false,
      exclude_custom: "",
      market_regime_analysis: false,
      regime_method: "ma",
    },
    execution: {
      fill_price: "next_open",
      rebalance_freq: "weekly",
      signal_day: "",
      holding_count: 20,
      weight_method: "equal",
    },
    cost_model: {
      commission_rate: 0.0003,
      stamp_tax: 0.001,
      transfer_fee: 0.00002,
      slippage_model: "volume_impact",
      slippage_bps: 5,
      volume_impact_coeff: 0.1,
      max_volume_pct: 10,
    },
    risk_advanced: { walk_forward: false },
    dynamic_position: { enabled: false },
    ...overrides,
  };
}

describe("buildRunBacktestPayload", () => {
  it("builds the backend /backtest/run schema from the UI form", () => {
    const payload = buildRunBacktestPayload(sampleForm());

    expect(payload).toMatchObject({
      strategy_id: "strategy-123",
      start_date: "2023-01-01",
      end_date: "2023-12-31",
      initial_capital: 1_000_000,
      benchmark: "000300.SH",
      universe_preset: "hs300",
      rebalance_freq: "weekly",
      slippage_model: "volume_impact",
    });
    expect(payload).not.toHaveProperty("config");
    expect(payload.extra_config).toMatchObject({
      holding_count: 20,
      top_n: 20,
      weight_method: "equal",
      commission_rate: 0.0003,
      risk_advanced: { walk_forward: false },
    });
  });

  it("normalizes UI-only options before sending them to the backend", () => {
    const payload = buildRunBacktestPayload(
      sampleForm({
        strategy_id: undefined,
        execution: {
          fill_price: "next_vwap",
          rebalance_freq: "custom",
          signal_day: "0 9 1 * *",
          holding_count: 12,
          weight_method: "ic_weighted",
        },
        cost_model: {
          commission_rate: 0.0003,
          stamp_tax: 0.001,
          transfer_fee: 0.00002,
          slippage_model: "none",
          slippage_bps: 0,
          volume_impact_coeff: 0,
          max_volume_pct: 10,
        },
      }),
    );

    expect(payload.strategy_id).toBe("manual_ui_backtest");
    expect(payload.rebalance_freq).toBe("monthly");
    expect(payload.slippage_model).toBe("fixed");
    expect(payload.extra_config).toMatchObject({
      custom_rebalance_rule: "0 9 1 * *",
      slippage_disabled: true,
    });
  });
});

describe("runBacktest", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs the normalized body to /backtest/run", async () => {
    post.mockResolvedValue({ data: { run_id: "run-1", status: "running" } });
    const payload = buildRunBacktestPayload(sampleForm());

    const res = await runBacktest(payload);

    expect(post).toHaveBeenCalledWith("/backtest/run", payload);
    expect(res).toEqual({ run_id: "run-1", status: "running" });
  });
});
