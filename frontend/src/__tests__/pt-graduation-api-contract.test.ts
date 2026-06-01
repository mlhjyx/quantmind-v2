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
});
