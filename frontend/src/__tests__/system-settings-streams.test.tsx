import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import SystemSettings from "@/pages/SystemSettings";

const systemApiMock = vi.hoisted(() => ({
  fetchDataSources: vi.fn(),
  fetchSchedulerTasks: vi.fn(),
  fetchSystemHealth: vi.fn(),
  fetchSystemStreams: vi.fn(),
  fetchNotificationParams: vi.fn(),
  saveNotificationParams: vi.fn(),
  testNotification: vi.fn(),
}));

vi.mock("@/api/system", () => ({
  ...systemApiMock,
}));

function renderHealthTab() {
  return render(
    <MemoryRouter initialEntries={["/settings/health"]}>
      <Routes>
        <Route path="/settings/:tab" element={<SystemSettings />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SystemSettings Redis Streams panel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    systemApiMock.fetchSystemHealth.mockResolvedValue({
      overall_status: "ok",
      pg: { ok: true, latency_ms: 4 },
      redis: { ok: true, latency_ms: 2 },
      celery: { ok: true, active_workers: 1 },
      disk: { ok: true, used_gb: 120, total_gb: 500, percent: 24 },
      memory: { ok: true, used_gb: 8, total_gb: 32, percent: 25 },
      data_freshness: { latest_kline_date: "2026-05-29", days_stale: 0 },
    });
    systemApiMock.fetchSystemStreams.mockResolvedValue({
      streams: [
        {
          stream: "qm:health:check_result",
          length: 12,
          last_published_at: "2026-06-01T09:30:00+08:00",
        },
        {
          stream: "qm:qmt:status",
          length: 0,
          last_published_at: null,
        },
      ],
    });
  });

  it("loads and renders Redis Streams status from the system API wrapper", async () => {
    renderHealthTab();

    expect(await screen.findByText("Redis Streams")).toBeInTheDocument();
    expect(await screen.findByText("qm:health:check_result")).toBeInTheDocument();
    expect(await screen.findByText("qm:qmt:status")).toBeInTheDocument();
    expect(screen.getByText("注册 Streams")).toBeInTheDocument();

    await waitFor(() => {
      expect(systemApiMock.fetchSystemStreams).toHaveBeenCalledTimes(1);
    });
  });
});
