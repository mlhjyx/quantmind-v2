import { beforeEach, describe, expect, it, vi } from "vitest";

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
}));

vi.mock("@/api/client", () => ({
  default: apiClientMock,
  apiClient: apiClientMock,
}));

import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
} from "@/api/notifications";

describe("notifications API contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads backend notifications through the unified API client", async () => {
    apiClientMock.get.mockResolvedValueOnce({
      data: {
        items: [
          {
            id: "api-1",
            level: "P1",
            category: "risk",
            title: "Backend risk alert",
            content: null,
            link: null,
            is_read: false,
            created_at: "2026-06-01T09:00:00+08:00",
          },
        ],
        limit: 20,
        offset: 0,
        unread_count: 1,
      },
    });

    const result = await fetchNotifications({
      limit: 20,
      offset: 0,
      is_read: false,
    });

    expect(apiClientMock.get).toHaveBeenCalledWith("/notifications", {
      params: { limit: 20, offset: 0, is_read: false },
    });
    expect(result).toEqual({
      items: [
        {
          id: "api-1",
          level: "P1",
          category: "risk",
          title: "Backend risk alert",
          content: undefined,
          link: undefined,
          is_read: false,
          created_at: "2026-06-01T09:00:00+08:00",
        },
      ],
      limit: 20,
      offset: 0,
      unread_count: 1,
    });
  });

  it("marks one notification as read through the backend endpoint", async () => {
    apiClientMock.put.mockResolvedValueOnce({ data: { success: true, id: "api-1" } });

    await markNotificationRead("api-1");

    expect(apiClientMock.put).toHaveBeenCalledWith("/notifications/api-1/read");
  });

  it("marks all notifications as read through the backend endpoint", async () => {
    apiClientMock.put.mockResolvedValueOnce({
      data: { success: true, updated_count: 3 },
    });

    await markAllNotificationsRead();

    expect(apiClientMock.put).toHaveBeenCalledWith("/notifications/read-all");
  });
});
