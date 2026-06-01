import { readFileSync } from "node:fs";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("health API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches QMT health through the health API layer", async () => {
    const api = await import("@/api/system");
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        execution_mode: "paper",
        state: "disabled",
        account_id: null,
        connected_at: null,
        last_error: null,
        is_healthy: true,
      },
    });

    expect(typeof api.fetchQmtHealth).toBe("function");
    await expect(api.fetchQmtHealth()).resolves.toMatchObject({
      execution_mode: "paper",
      state: "disabled",
      is_healthy: true,
    });
    expect(apiClientMock.get).toHaveBeenCalledWith("/health/qmt");
  });

  it("keeps QMTStatusBadge behind src/api wrappers", () => {
    const source = readFileSync("src/components/shared/QMTStatusBadge.tsx", "utf8");

    expect(source).not.toContain('import apiClient from "@/api/client"');
    expect(source).not.toMatch(/\bapiClient\.(get|post|put|delete|patch)\s*\(/);
  });
});
