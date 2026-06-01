import apiClient from "./client";

export interface MarketIndex {
  code: string;
  name: string;
  close: number;
  pre_close: number;
  pct_change: number;
  volume: number;
  amount: number;
  is_up: boolean;
  trade_date: string | null;
}

export interface MarketSector {
  name: string;
  pct_change: number;
  stock_count: number;
  amount: number;
  is_up: boolean;
}

export interface MarketTopMover {
  code: string;
  name: string;
  industry: string;
  close: number;
  pct_change: number;
}

export type MarketMoverDirection = "up" | "down";

export async function fetchMarketIndices(): Promise<MarketIndex[]> {
  const { data } = await apiClient.get<MarketIndex[]>("/market/indices");
  return data;
}

export async function fetchMarketSectors(): Promise<MarketSector[]> {
  const { data } = await apiClient.get<MarketSector[]>("/market/sectors");
  return data;
}

export async function fetchMarketTopMovers(
  direction: MarketMoverDirection,
  limit = 5,
): Promise<MarketTopMover[]> {
  const { data } = await apiClient.get<MarketTopMover[]>("/market/top-movers", {
    params: { direction, limit },
  });
  return data;
}
