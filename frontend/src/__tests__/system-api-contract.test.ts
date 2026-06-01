import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

import { fetchNotificationParams } from "@/api/system";

describe("system API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes grouped notification params from the backend params endpoint", async () => {
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        modules: ["notification"],
        params: {
          notification: [
            {
              param_name: "notification.dingtalk_enabled",
              param_value: true,
            },
            {
              param_name: "notification.daily_digest_time",
              param_value: "17:30",
            },
          ],
        },
      },
    });

    const params = await fetchNotificationParams();

    expect(apiClientMock.get).toHaveBeenCalledWith("/params", {
      params: { module: "notification" },
    });
    expect(params).toEqual([
      { key: "notification.dingtalk_enabled", value: "true" },
      { key: "notification.daily_digest_time", value: "17:30" },
    ]);
  });
});
