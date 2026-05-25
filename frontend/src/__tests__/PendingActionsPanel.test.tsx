/**
 * PendingActionsPanel — iter 139 W2-F F8 (D8 wire test coverage).
 *
 * Tests sub-component inside DashboardAstock.tsx via direct import path.
 * Mocks fetchPendingActions; verifies empty/list/error states.
 *
 * Backend SSOT: backend/app/api/dashboard.py:67 GET /api/dashboard/pending-actions
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PendingAction } from "@/types/dashboard";

// Mock dashboard.ts BEFORE import of DashboardAstock (hoisted by vitest).
const mockFetchPendingActions = vi.fn();
vi.mock("@/api/dashboard", async () => {
  const actual = await vi.importActual<typeof import("@/api/dashboard")>("@/api/dashboard");
  return {
    ...actual,
    fetchPendingActions: () => mockFetchPendingActions(),
  };
});

// Import PendingActionsPanel directly — exported as named export from DashboardAstock
// to enable isolated unit testing (avoids NAVChart/SectorPie/etc init in same render).
import { PendingActionsPanel } from "@/pages/DashboardAstock";

function renderDashboard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PendingActionsPanel />
    </QueryClientProvider>,
  );
}

describe("PendingActionsPanel — D8 wire", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("F8-T1: Empty state shows '✓ 无待处理事项' when list is []", async () => {
    mockFetchPendingActions.mockResolvedValue([]);
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/无待处理事项/)).toBeInTheDocument();
    });
  });

  it("F8-T2: Renders pending items with severity badge + message + type label", async () => {
    const items: PendingAction[] = [
      { type: "circuit_breaker", severity: "critical", message: "L2_REDUCE 触发, 仓位倍数 0.5", time: "2026-05-26 02:30" },
      { type: "health", severity: "warning", message: "Redis 心跳超时 60s", time: null },
      { type: "pipeline", severity: "info", message: "GP run 完成", time: "2026-05-26 02:00" },
    ];
    mockFetchPendingActions.mockResolvedValue(items);
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/L2_REDUCE 触发/)).toBeInTheDocument();
      expect(screen.getByText(/Redis 心跳超时 60s/)).toBeInTheDocument();
      expect(screen.getByText(/GP run 完成/)).toBeInTheDocument();
      // Type labels render (one per item)
      expect(screen.getByText("熔断")).toBeInTheDocument();
      expect(screen.getByText("健康")).toBeInTheDocument();
      expect(screen.getByText("管道")).toBeInTheDocument();
    });
  });

  it("F8-T3: Error state shows '加载失败' + 重试 button per LL-205 fail-loud", async () => {
    mockFetchPendingActions.mockRejectedValue(new Error("503 Service Unavailable"));
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByText(/加载失败/)).toBeInTheDocument();
      expect(screen.getByText(/503 Service Unavailable/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    });
  });
});
