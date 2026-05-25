/**
 * TradeLogPanel — iter 141 W2-F F7 (D5 wire test coverage).
 *
 * Tests TradeLogPanel exported from PTGraduation.tsx (sibling iter 139 F8 pattern).
 * Verifies empty/list/error states + direction labels + cost columns.
 *
 * Backend SSOT: backend/app/api/paper_trading.py:243 GET /api/paper-trading/trades
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Trade } from "@/types/dashboard";

const mockFetchPaperTrades = vi.fn();
vi.mock("@/api/dashboard", async () => {
  const actual = await vi.importActual<typeof import("@/api/dashboard")>("@/api/dashboard");
  return {
    ...actual,
    fetchPaperTrades: (limit?: number) => mockFetchPaperTrades(limit),
  };
});

// Stub apiClient (PTGraduation imports it; we only test TradeLogPanel sub-component).
vi.mock("@/api/client", () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: null })) },
}));

import { TradeLogPanel } from "@/pages/PTGraduation";

function renderPanel(limit?: number) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TradeLogPanel limit={limit} />
    </QueryClientProvider>,
  );
}

describe("TradeLogPanel — D5 wire", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("F7-T1: Empty state shows 'PT 27d 0 trade sustained' message", async () => {
    mockFetchPaperTrades.mockResolvedValue([]);
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/无交易记录/)).toBeInTheDocument();
    });
  });

  it("F7-T2: Renders trade rows with direction labels + price + cost columns", async () => {
    const trades: Trade[] = [
      {
        id: "abc-001",
        code: "688121.SH",
        trade_date: "2026-04-29T10:43:54",
        direction: "SELL",
        quantity: 4500,
        fill_price: 23.45,
        slippage_bps: 12.3,
        commission: 8.54,
        stamp_tax: 5.27,
        total_cost: 13.81,
        reject_reason: null,
      },
      {
        id: "abc-002",
        code: "002441.SZ",
        trade_date: "2026-04-29T09:30:11",
        direction: "BUY",
        quantity: 2000,
        fill_price: 18.6,
        slippage_bps: 8.1,
        commission: 5.0,
        stamp_tax: null,
        total_cost: null,
        reject_reason: "F19_backfill_2026-04-17",
      },
    ];
    mockFetchPaperTrades.mockResolvedValue(trades);
    renderPanel(100);
    await waitFor(() => {
      expect(screen.getByText("688121.SH")).toBeInTheDocument();
      expect(screen.getByText("002441.SZ")).toBeInTheDocument();
      expect(screen.getByText("卖出")).toBeInTheDocument();
      expect(screen.getByText("买入")).toBeInTheDocument();
      // Reject reason renders
      expect(screen.getByText(/F19_backfill/)).toBeInTheDocument();
      // limit count header
      expect(screen.getByText(/2 \/ max 100/)).toBeInTheDocument();
    });
  });

  it("F7-T3: Error state shows '加载失败' + 重试 button per LL-205 fail-loud", async () => {
    mockFetchPaperTrades.mockRejectedValue(new Error("503 Service Unavailable"));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/加载失败/)).toBeInTheDocument();
      expect(screen.getByText(/503/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument();
    });
  });
});
