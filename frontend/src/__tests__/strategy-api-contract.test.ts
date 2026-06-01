import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
}));

import {
  createStrategy,
  getStrategy,
  getStrategyDetail,
  getStrategyFactors,
  getStrategyVersions,
  updateStrategy,
} from "@/api/strategies";

describe("strategy API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes backend strategy detail into the editor strategy model", async () => {
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        strategy: {
          id: "strategy-1",
          name: "CORE3",
          market: "astock",
          factor_config: {
            factor_names: ["turnover_mean_20", "bp_ratio"],
            top_n: 5,
            rebalance_freq: "weekly",
            weight_method: "ic_weighted",
            industry_cap: 0.3,
            single_stock_cap: 0.12,
            initial_capital: 880000,
          },
          backtest_config: {},
          active_version: 2,
          status: "active",
          created_at: "2026-06-01T09:30:00+08:00",
        },
        active_config: {
          version: 2,
          config: { top_n: 7, rebalance_freq: "monthly" },
          changelog: "raise top_n",
          created_at: "2026-06-01T10:00:00+08:00",
        },
        version_history: [],
      },
    });

    const strategy = await getStrategy("strategy-1");

    expect(apiClientMock.get).toHaveBeenCalledWith("/strategies/strategy-1");
    expect(strategy).toMatchObject({
      id: "strategy-1",
      name: "CORE3",
      factor_ids: ["turnover_mean_20", "bp_ratio"],
      top_n: 7,
      rebalance_freq: "monthly",
      weight_method: "ic_weighted",
      industry_cap: 0.3,
      single_stock_cap: 0.12,
      initial_capital: 880000,
      active_version: 2,
      status: "active",
    });
  });

  it("wraps read-only strategy version and factor endpoints", async () => {
    apiClientMock.get
      .mockResolvedValueOnce({
        data: {
          strategy: { id: "strategy-1", name: "CORE3" },
          active_config: null,
          version_history: [],
        },
      })
      .mockResolvedValueOnce({
        data: [{ version: 2, config: { top_n: 5 }, changelog: "tune", created_at: "now" }],
      })
      .mockResolvedValueOnce({
        data: {
          strategy_id: "strategy-1",
          factor_names: ["bp_ratio"],
          factors: [
            {
              name: "bp_ratio",
              category: "fundamental",
              direction: 1,
              ic_decay_halflife: 42,
            },
          ],
        },
      });

    await expect(getStrategyDetail("strategy-1")).resolves.toHaveProperty(
      "strategy.id",
      "strategy-1",
    );
    const versions = await getStrategyVersions("strategy-1");
    const factors = await getStrategyFactors("strategy-1");

    expect(apiClientMock.get).toHaveBeenNthCalledWith(1, "/strategies/strategy-1");
    expect(apiClientMock.get).toHaveBeenNthCalledWith(2, "/strategies/strategy-1/versions");
    expect(apiClientMock.get).toHaveBeenNthCalledWith(3, "/strategies/strategy-1/factors");
    expect(versions[0]).toMatchObject({ version: 2, changelog: "tune" });
    expect(factors.factors[0]).toMatchObject({ name: "bp_ratio", direction: 1 });
  });

  it("adapts editor create/update payloads to backend strategy request bodies", async () => {
    apiClientMock.post.mockResolvedValueOnce({
      data: { strategy_id: "strategy-2", name: "new strategy", market: "astock", status: "draft" },
    });
    apiClientMock.put.mockResolvedValueOnce({
      data: { strategy_id: "strategy-2", updated: true },
    });

    const payload = {
      name: "new strategy",
      description: "demo",
      factor_ids: ["bp_ratio"],
      top_n: 5,
      rebalance_freq: "monthly" as const,
      weight_method: "equal" as const,
      industry_cap: 0.25,
      single_stock_cap: 0.1,
      initial_capital: 1000000,
    };

    const created = await createStrategy(payload);
    const updated = await updateStrategy("strategy-2", payload);

    expect(apiClientMock.post).toHaveBeenCalledWith("/strategies", {
      name: "new strategy",
      market: "astock",
      config: expect.objectContaining({ top_n: 5, rebalance_freq: "monthly" }),
      factor_names: ["bp_ratio"],
    });
    expect(apiClientMock.put).toHaveBeenCalledWith("/strategies/strategy-2", {
      name: "new strategy",
      factor_config: expect.objectContaining({
        factor_names: ["bp_ratio"],
        top_n: 5,
      }),
      backtest_config: expect.objectContaining({
        initial_capital: 1000000,
      }),
    });
    expect(created.id).toBe("strategy-2");
    expect(updated.id).toBe("strategy-2");
  });

  it("does not send empty config blocks for name-only updates", async () => {
    apiClientMock.put.mockResolvedValueOnce({
      data: { strategy_id: "strategy-3", updated: true },
    });

    await updateStrategy("strategy-3", { name: "renamed strategy" });

    expect(apiClientMock.put).toHaveBeenCalledWith("/strategies/strategy-3", {
      name: "renamed strategy",
    });
  });

  it("keeps StrategyWorkspace wired to edit-route detail, versions, and factors", () => {
    const source = readFileSync("src/pages/StrategyWorkspace.tsx", "utf8");

    expect(source).toContain("useParams");
    expect(source).toContain("getStrategy");
    expect(source).toContain("getStrategyVersions");
    expect(source).toContain("getStrategyFactors");
    expect(source).toContain("strategy_id=");
  });
});
