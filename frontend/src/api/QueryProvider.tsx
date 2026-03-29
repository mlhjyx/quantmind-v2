import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// ── staleTime constants ──────────────────────────────────────────────────
// Use these in useQuery({ staleTime: STALE.factor }) to override per category:
//   STALE.price  → 30s   dashboard summary, positions, NAV, PT state
//   STALE.factor → 5min  factor reports, IC trends, correlation, backtest results
//   STALE.config → 30min strategy params, system settings, agent config
export const STALE = {
  price:  30_000,
  factor: 5 * 60_000,
  config: 30 * 60_000,
} as const;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: STALE.price,   // default: price-class data (30s)
      gcTime: 10 * 60_000,      // 10min in-memory cache after unmount
      retry: 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 15_000),
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 0,
    },
  },
});

interface QueryProviderProps {
  children: ReactNode;
}

export function QueryProvider({ children }: QueryProviderProps) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

export { queryClient };
