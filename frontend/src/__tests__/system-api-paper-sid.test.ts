/**
 * Tests for getPaperStrategyId wrapper (iter 39).
 *
 * Covers iter 39 frontend api/system.ts addition closing the iter 35
 * DEFAULT_STRATEGY_ID placeholder gap.
 *
 * Mirrors pipeline-api.test.ts + reports-api.test.ts mock pattern.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";

vi.mock("@/api/client", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import apiClient from "@/api/client";
import { getPaperStrategyId, type PaperStrategyIdResponse } from "@/api/system";

const get = apiClient.get as unknown as Mock;

describe("getPaperStrategyId", () => {
  beforeEach(() => vi.clearAllMocks());

  it("GETs /system/settings/paper-strategy-id", async () => {
    const resp: PaperStrategyIdResponse = {
      paper_strategy_id: "abc-123-uuid",
      configured: true,
      source: "settings.PAPER_STRATEGY_ID",
    };
    get.mockResolvedValue({ data: resp });

    const result = await getPaperStrategyId();

    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/system/settings/paper-strategy-id");
    expect(result.paper_strategy_id).toBe("abc-123-uuid");
    expect(result.configured).toBe(true);
    expect(result.source).toBe("settings.PAPER_STRATEGY_ID");
  });

  it("handles unconfigured response (settings.PAPER_STRATEGY_ID empty)", async () => {
    const resp: PaperStrategyIdResponse = {
      paper_strategy_id: "",
      configured: false,
      source: "settings.PAPER_STRATEGY_ID",
    };
    get.mockResolvedValue({ data: resp });

    const result = await getPaperStrategyId();

    expect(result.paper_strategy_id).toBe("");
    expect(result.configured).toBe(false);
    // Caller (ReportCenter.tsx) should fall back to PLACEHOLDER_STRATEGY_ID
    // when configured=false — verified at integration via separate test
  });

  it("type narrows source to literal 'settings.PAPER_STRATEGY_ID'", async () => {
    get.mockResolvedValue({
      data: { paper_strategy_id: "sid-x", configured: true, source: "settings.PAPER_STRATEGY_ID" },
    });

    const result = await getPaperStrategyId();

    // TypeScript type check: source is a literal type, not a free string
    const sourceLiteral: "settings.PAPER_STRATEGY_ID" = result.source;
    expect(sourceLiteral).toBe("settings.PAPER_STRATEGY_ID");
  });
});
