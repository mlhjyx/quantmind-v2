/**
 * 关键页面渲染测试
 *
 * 覆盖:
 * - Dashboard: 挂载不崩溃，关键元素存在
 * - FactorLibrary: 挂载不崩溃
 * - BacktestConfig: 挂载不崩溃
 *
 * 使用 vi.mock 隔离 API 调用，测试纯渲染行为。
 * 铁律5: Dashboard.tsx 已通过 read 验证，使用 fetchSummary/fetchNAVSeries/fetchPositions/fetchCircuitBreakerState
 */

import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Mock API 层（防止真实 HTTP 请求）──────────────────────────

vi.mock("@/api/dashboard", () => ({
  fetchSummary: vi.fn().mockResolvedValue({
    nav: 1050000,
    daily_return: 0.005,
    total_return: 0.05,
    sharpe: 1.2,
    mdd: -0.08,
    position_count: 15,
    strategy_name: "v1.1",
    trade_date: "2024-01-15",
  }),
  fetchNAVSeries: vi.fn().mockResolvedValue([]),
  fetchPositions: vi.fn().mockResolvedValue([]),
  fetchCircuitBreakerState: vi.fn().mockResolvedValue(null),
  fetchPendingActions: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/api/factors", () => ({
  getFactorLibrary: vi.fn().mockResolvedValue([]),
  getFactorLibraryStats: vi.fn().mockResolvedValue({
    active: 5,
    new: 0,
    degraded: 0,
    retired: 0,
  }),
  getFactorCorrelation: vi.fn().mockResolvedValue({ factors: [], matrix: [] }),
  getFactorICTrends: vi.fn().mockResolvedValue([]),
  groupFactorsByCategory: vi.fn().mockReturnValue({}),
}));

vi.mock("@/api/backtest", () => ({
  getBacktestRuns: vi.fn().mockResolvedValue([]),
  getStrategies: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/api/strategies", () => ({
  getStrategies: vi.fn().mockResolvedValue([]),
  getStrategyDetail: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  useWebSocket: vi.fn().mockReturnValue({ connected: false, lastMessage: null }),
}));

// Mock ECharts（防止 canvas 相关报错）
vi.mock("echarts-for-react", () => ({
  default: () => null,
}));

vi.mock("recharts", () => ({
  LineChart: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => children,
  AreaChart: () => null,
  Area: () => null,
}));

// Mock 子组件（防止深层依赖报错）
vi.mock("@/components/KPICards", () => ({
  default: () => <div data-testid="kpi-cards">KPICards</div>,
}));
vi.mock("@/components/NAVChart", () => ({
  default: () => <div data-testid="nav-chart">NAVChart</div>,
}));
vi.mock("@/components/PositionTable", () => ({
  default: () => <div data-testid="position-table">PositionTable</div>,
}));
vi.mock("@/components/CircuitBreaker", () => ({
  default: () => <div data-testid="circuit-breaker">CircuitBreaker</div>,
}));

// ─────────────────────────────────────────────────────────────
// Dashboard
// ─────────────────────────────────────────────────────────────

import Dashboard from "@/pages/Dashboard";

function renderWithRouter(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Dashboard 页面", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("挂载不崩溃", () => {
    expect(() => renderWithRouter(<Dashboard />)).not.toThrow();
  });

  it("渲染 KPICards 子组件", () => {
    renderWithRouter(<Dashboard />);
    expect(screen.getByTestId("kpi-cards")).toBeInTheDocument();
  });

  it("渲染 NAVChart 子组件", () => {
    renderWithRouter(<Dashboard />);
    expect(screen.getByTestId("nav-chart")).toBeInTheDocument();
  });

  it("渲染 PositionTable 子组件", () => {
    renderWithRouter(<Dashboard />);
    expect(screen.getByTestId("position-table")).toBeInTheDocument();
  });
});

// ─────────────────────────────────────────────────────────────
// FactorLibrary
// ─────────────────────────────────────────────────────────────

import FactorLibrary from "@/pages/FactorLibrary";

describe("FactorLibrary 页面", () => {
  it("挂载不崩溃", () => {
    expect(() => renderWithRouter(<FactorLibrary />)).not.toThrow();
  });

  it("渲染页面容器", () => {
    const { container } = renderWithRouter(<FactorLibrary />);
    expect(container.firstChild).not.toBeNull();
  });
});

// ─────────────────────────────────────────────────────────────
// BacktestConfig
// ─────────────────────────────────────────────────────────────

import BacktestConfig from "@/pages/BacktestConfig";

describe("BacktestConfig 页面", () => {
  it("挂载不崩溃", () => {
    expect(() => renderWithRouter(<BacktestConfig />)).not.toThrow();
  });

  it("渲染页面容器", () => {
    const { container } = renderWithRouter(<BacktestConfig />);
    expect(container.firstChild).not.toBeNull();
  });
});
