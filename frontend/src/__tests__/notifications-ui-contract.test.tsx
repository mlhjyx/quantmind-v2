import React from "react";
import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

const notificationsApiMock = vi.hoisted(() => ({
  fetchNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
}));

vi.mock("@/api/notifications", () => notificationsApiMock);

vi.mock("@/hooks/useRealtimeData", () => ({
  useMarketOverview: () => ({ data: undefined }),
}));

vi.mock("@/components/layout/Sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

vi.mock("@/components/safety/EnvStateBanner", () => ({
  EnvStateBanner: () => null,
}));

vi.mock("@/components/ai/AssistPanel", () => ({
  FloatingAssistLauncher: () => null,
}));

import { Layout } from "@/components/layout/Layout";
import { NotificationPanel } from "@/components/ui/NotificationPanel";
import { NotificationProvider } from "@/contexts/NotificationContext";

const apiNotification = {
  id: "api-1",
  level: "P1" as const,
  category: "risk",
  title: "Backend risk alert",
  content: "Loaded from backend",
  link: undefined,
  is_read: false,
  created_at: "2026-06-01T09:00:00+08:00",
};

function mockLoadedNotifications(items = [apiNotification]) {
  notificationsApiMock.fetchNotifications.mockResolvedValue({
    items,
    limit: 50,
    offset: 0,
    unread_count: items.filter((item) => !item.is_read).length,
  });
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <NotificationProvider>
        <NotificationPanel />
      </NotificationProvider>
    </MemoryRouter>,
  );
}

describe("NotificationPanel backend contract", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLoadedNotifications();
    notificationsApiMock.markNotificationRead.mockResolvedValue({
      success: true,
      id: "api-1",
    });
    notificationsApiMock.markAllNotificationsRead.mockResolvedValue({
      success: true,
      updated_count: 1,
    });
  });

  it("loads backend notifications instead of seeded mock rows", async () => {
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => {
      expect(notificationsApiMock.fetchNotifications).toHaveBeenCalledWith({
        limit: 50,
        offset: 0,
      });
    });

    await user.click(screen.getByRole("button", { name: "通知中心" }));

    expect(await screen.findByText("Backend risk alert")).toBeInTheDocument();
    expect(screen.queryByText("熔断告警: L2触发")).not.toBeInTheDocument();
  });

  it("shows a loading state while notifications are loading", async () => {
    notificationsApiMock.fetchNotifications.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("button", { name: "通知中心" }));

    expect(screen.getByText("加载中")).toBeInTheDocument();
  });

  it("shows an empty state for an empty backend response", async () => {
    mockLoadedNotifications([]);
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => {
      expect(notificationsApiMock.fetchNotifications).toHaveBeenCalled();
    });
    await user.click(screen.getByRole("button", { name: "通知中心" }));

    expect(screen.getByText("暂无通知")).toBeInTheDocument();
    expect(screen.queryByText("熔断告警: L2触发")).not.toBeInTheDocument();
  });

  it("shows an error state when the backend request fails", async () => {
    notificationsApiMock.fetchNotifications.mockRejectedValueOnce(new Error("offline"));
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => {
      expect(notificationsApiMock.fetchNotifications).toHaveBeenCalled();
    });
    await user.click(screen.getByRole("button", { name: "通知中心" }));

    expect(await screen.findByText("通知加载失败")).toBeInTheDocument();
  });

  it("marks all loaded notifications as read through the backend", async () => {
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => {
      expect(notificationsApiMock.fetchNotifications).toHaveBeenCalled();
    });
    await user.click(screen.getByRole("button", { name: "通知中心" }));
    await user.click(screen.getByRole("button", { name: "全部已读" }));

    expect(notificationsApiMock.markAllNotificationsRead).toHaveBeenCalledTimes(1);
  });

  it("does not call the mark-read endpoint for already-read rows", async () => {
    mockLoadedNotifications([{ ...apiNotification, is_read: true }]);
    const user = userEvent.setup();
    renderPanel();

    await waitFor(() => {
      expect(notificationsApiMock.fetchNotifications).toHaveBeenCalled();
    });
    await user.click(screen.getByRole("button", { name: "通知中心" }));
    await user.click(await screen.findByText("Backend risk alert"));

    expect(notificationsApiMock.markNotificationRead).not.toHaveBeenCalled();
  });
});

describe("notification app shell wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockLoadedNotifications();
  });

  it("mounts one API-backed notification provider for the app shell", async () => {
    render(
      <MemoryRouter>
        <NotificationProvider>
          <Layout />
        </NotificationProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(notificationsApiMock.fetchNotifications).toHaveBeenCalledTimes(1);
    });
  });
});
