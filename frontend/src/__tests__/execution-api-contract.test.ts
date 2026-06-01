import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
}));

import { getExecutionLog, getPendingOrders } from "@/api/execution";

describe("execution API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads DB pending orders through the legacy read-only endpoint", async () => {
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          id: "trade-1",
          code: "600519.SH",
          name: "贵州茅台",
          direction: "buy",
          quantity: 100,
          target_price: 1680,
          trade_date: "2026-06-01",
          status: "pending",
          created_at: "2026-06-01T09:30:00+08:00",
        },
      ],
    });

    const result = await getPendingOrders({
      strategy_id: "sid-1",
      execution_mode: "paper",
    });

    expect(apiClientMock.get).toHaveBeenCalledWith("/execution/pending-orders", {
      params: { strategy_id: "sid-1", execution_mode: "paper" },
    });
    expect(result[0]).toMatchObject({
      id: "trade-1",
      code: "600519.SH",
      status: "pending",
    });
  });

  it("loads DB execution log rows with date and limit params", async () => {
    apiClientMock.get.mockResolvedValueOnce({
      data: [
        {
          id: "trade-2",
          code: "000001.SZ",
          name: "平安银行",
          direction: "sell",
          quantity: 200,
          fill_price: 11.5,
          total_cost: 3.6,
          trade_date: "2026-06-01",
          status: "executed",
          executed_at: "2026-06-01T09:45:00+08:00",
        },
      ],
    });

    const result = await getExecutionLog({
      date: "2026-06-01",
      limit: 20,
    });

    expect(apiClientMock.get).toHaveBeenCalledWith("/execution/log", {
      params: { date: "2026-06-01", limit: 20 },
    });
    expect(result[0]).toMatchObject({
      id: "trade-2",
      code: "000001.SZ",
      status: "executed",
    });
  });

  it("keeps Execution page wired to DB pending/log wrappers", () => {
    const source = readFileSync("src/pages/Execution/index.tsx", "utf8");

    expect(source).toContain("getPendingOrders");
    expect(source).toContain("getExecutionLog");
    expect(source).toContain("executionPendingOrders");
    expect(source).toContain("executionLog");
  });
});
