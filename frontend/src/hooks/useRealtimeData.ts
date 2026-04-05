/**
 * Realtime data hooks — 所有页面共用。
 */
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { queryKeys } from "@/lib/queryKeys";
import { getPortfolioSnapshot, getMarketOverview } from "@/api/realtime";
import type { PortfolioSnapshot, MarketOverview } from "@/api/realtime";

export function usePortfolio() {
  return useQuery<PortfolioSnapshot>({
    queryKey: [...queryKeys.portfolio],
    queryFn: getPortfolioSnapshot,
    refetchInterval: 5_000,
    staleTime: 3_000,
    retry: 1,
    placeholderData: keepPreviousData,  // 刷新时保持旧数据，防止闪烁
  });
}

export function useMarketOverview() {
  return useQuery<MarketOverview>({
    queryKey: [...queryKeys.market],
    queryFn: getMarketOverview,
    refetchInterval: 10_000,
    staleTime: 8_000,
    retry: 1,
    placeholderData: keepPreviousData,
  });
}
