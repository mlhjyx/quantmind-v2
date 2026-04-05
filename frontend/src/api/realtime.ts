/**
 * Realtime API — 统一实时数据源。
 */
import apiClient from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AccountSnapshot {
  total_asset: number;
  market_value: number;
  available_cash: number;
  frozen_cash: number;
  total_pnl: number;
  total_pnl_pct: number;
  daily_pnl: number;
}

export interface PositionItem {
  code: string;
  name: string;
  shares: number;
  available: number;
  cost_price: number;
  last_price: number;
  prev_close: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
  daily_return: number;
  weight: number;
  target_shares: number;
  drift_pct: number;
  drift_status: "normal" | "overweight" | "missing" | "underweight";
  industry: string;
}

export interface MissingItem {
  code: string;
  name: string;
  target_shares: number;
  estimated_cost: number;
  drift_status: "missing";
}

export interface PortfolioSnapshot {
  timestamp: string;
  qmt_connected: boolean;
  data_source: string;
  is_market_open: boolean;
  account: AccountSnapshot;
  positions: PositionItem[];
  missing: MissingItem[];
  summary: {
    total_stocks: number;
    target_stocks: number;
    overweight_count: number;
    missing_count: number;
    max_single_weight: number;
  };
  industry_allocation: Record<string, number>;
}

export interface IndexData {
  name: string;
  price: number;
  prev_close: number;
  change_pct: number;
  amount: number;
}

export interface MarketOverview {
  timestamp: string;
  is_market_open: boolean;
  indices: Record<string, IndexData>;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function getPortfolioSnapshot(): Promise<PortfolioSnapshot> {
  const { data } = await apiClient.get<PortfolioSnapshot>("/realtime/portfolio");
  return data;
}

export async function getMarketOverview(): Promise<MarketOverview> {
  const { data } = await apiClient.get<MarketOverview>("/realtime/market");
  return data;
}
