import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

describe("approval API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("maps approval queue reads through src/api/approval", async () => {
    const api = await import("@/api/approval");

    apiClientMock.get.mockResolvedValueOnce({ data: [{ id: 42 }] });
    await expect(api.getApprovalQueue(25)).resolves.toEqual([{ id: 42 }]);
    expect(apiClientMock.get).toHaveBeenCalledWith("/approval/queue", {
      params: { limit: 25 },
    });

    apiClientMock.get.mockResolvedValueOnce({
      data: { id: 42, gate_report: { G1: { passed: true } } },
    });
    await expect(api.getApprovalDetail(42)).resolves.toMatchObject({
      id: 42,
      gate_report: { G1: { passed: true } },
    });
    expect(apiClientMock.get).toHaveBeenCalledWith("/approval/queue/42");

    apiClientMock.get.mockResolvedValueOnce({
      data: { total: 1, limit: 20, offset: 40, items: [{ id: 7 }] },
    });
    await expect(
      api.getApprovalHistory({ status: "approved", limit: 20, offset: 40 }),
    ).resolves.toMatchObject({ total: 1, items: [{ id: 7 }] });
    expect(apiClientMock.get).toHaveBeenCalledWith("/approval/history", {
      params: { status: "approved", limit: 20, offset: 40 },
    });
  });

  it("maps approval queue admin actions through src/api/approval", async () => {
    const api = await import("@/api/approval");

    apiClientMock.post.mockResolvedValueOnce({ data: { id: 42, status: "approved" } });
    await expect(
      api.approveQueueItem(42, { reviewer_notes: "reviewed" }),
    ).resolves.toMatchObject({ id: 42, status: "approved" });
    expect(apiClientMock.post).toHaveBeenCalledWith("/approval/queue/42/approve", {
      reviewed_by: "user",
      reviewer_notes: "reviewed",
    });

    apiClientMock.post.mockResolvedValueOnce({ data: { id: 42, status: "rejected" } });
    await expect(
      api.rejectQueueItem(42, {
        rejection_reason: "weak evidence",
        reviewer_notes: "needs stronger IC",
      }),
    ).resolves.toMatchObject({ id: 42, status: "rejected" });
    expect(apiClientMock.post).toHaveBeenCalledWith("/approval/queue/42/reject", {
      reviewed_by: "user",
      rejection_reason: "weak evidence",
      reviewer_notes: "needs stronger IC",
    });

    apiClientMock.post.mockResolvedValueOnce({ data: { id: 42, status: "hold" } });
    await expect(
      api.holdQueueItem(42, { reviewer_notes: "wait for OOS window" }),
    ).resolves.toMatchObject({ id: 42, status: "hold" });
    expect(apiClientMock.post).toHaveBeenCalledWith("/approval/queue/42/hold", {
      reviewed_by: "user",
      reviewer_notes: "wait for OOS window",
    });
  });
});
