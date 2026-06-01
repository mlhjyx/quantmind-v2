import apiClient from "./client";

export type PortfolioExecutionMode = "live" | "paper";

export interface PortfolioHolding {
  code: string;
  name?: string;
  industry?: string;
  quantity?: number;
  avg_cost?: number;
  market_value?: number;
  weight?: number;
  unrealized_pnl?: number;
  holding_days?: number | null;
  trade_date?: string | null;
}

interface RawSectorItem {
  name: string;
  pct?: number | null;
  value?: number | null;
  color?: string | null;
}

export interface PortfolioSectorItem {
  name: string;
  value: number;
  pct: number;
  marketValue: number;
  color: string;
}

export interface PortfolioDailyPnl {
  trade_date: string;
  nav: number;
  daily_return: number;
  cumulative_return: number;
  drawdown: number;
  position_count?: number;
  turnover?: number;
}

const SECTOR_COLORS = [
  "#3b82f6",
  "#8b5cf6",
  "#06b6d4",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#ec4899",
  "#6366f1",
  "#64748b",
];

function numberOrZero(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

export async function fetchPortfolioSectorDistribution(
  executionMode: PortfolioExecutionMode = "live",
): Promise<PortfolioSectorItem[]> {
  const { data } = await apiClient.get<RawSectorItem[]>(
    "/portfolio/sector-distribution",
    { params: { execution_mode: executionMode } },
  );
  return data.map((row, index) => {
    const pct = numberOrZero(row.pct);
    return {
      name: row.name,
      value: pct,
      pct,
      marketValue: numberOrZero(row.value),
      color: row.color ?? SECTOR_COLORS[index % SECTOR_COLORS.length]!,
    };
  });
}

export async function fetchPortfolioDailyPnl(
  days = 20,
  executionMode: PortfolioExecutionMode = "live",
): Promise<PortfolioDailyPnl[]> {
  const { data } = await apiClient.get<PortfolioDailyPnl[]>(
    "/portfolio/daily-pnl",
    { params: { days, execution_mode: executionMode } },
  );
  return data;
}

export async function fetchPortfolioHoldings(
  executionMode: PortfolioExecutionMode = "live",
): Promise<PortfolioHolding[]> {
  const { data } = await apiClient.get<PortfolioHolding[]>(
    "/portfolio/holdings",
    { params: { execution_mode: executionMode } },
  );
  return data;
}

export async function fetchHoldingDaysMap(
  executionMode: PortfolioExecutionMode = "live",
): Promise<Record<string, number>> {
  const holdings = await fetchPortfolioHoldings(executionMode);
  return holdings.reduce<Record<string, number>>((acc, row) => {
    if (row.code && typeof row.holding_days === "number") {
      acc[row.code] = row.holding_days;
    }
    return acc;
  }, {});
}
