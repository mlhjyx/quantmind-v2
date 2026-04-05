/**
 * Unified query key registry.
 *
 * All useQuery/useMutation should reference keys from here
 * so invalidation cascades work across pages.
 */

export const queryKeys = {
  // ── Realtime (global, 5s refresh) ──
  portfolio: ["realtime", "portfolio"] as const,
  market: ["realtime", "market"] as const,

  // ── Execution ──
  qmtStatus: ["qmt-status"] as const,
  executionAsset: ["execution-asset"] as const,
  executionOrders: ["execution-orders"] as const,
  executionTrades: ["execution-trades"] as const,
  executionDrift: ["execution-drift"] as const,
  executionAuditLog: ["execution-audit-log"] as const,
  tradingPaused: ["trading-paused"] as const,

  // ── Strategies ──
  strategies: ["strategies"] as const,
  strategyDetail: (id: string) => ["strategies", id] as const,

  // ── Backtests ──
  backtestHistory: ["backtest-history"] as const,
  backtestResult: (id: string) => ["backtest-result", id] as const,

  // ── Factors ──
  factorLibrary: ["factor-library"] as const,
  factorStats: ["factor-library-stats"] as const,
  factorCorrelation: ["factor-correlation"] as const,
  factorICTrends: ["factor-ic-trends"] as const,
  factorsSummary: ["factors", "summary"] as const,
  factorReport: (name: string) => ["factor-report", name] as const,

  // ── Dashboard (historical) ──
  dashboardStrategies: ["dashboard-strategies"] as const,
  navSeries: ["dashboard", "nav-series"] as const,
  monthlyReturns: ["dashboard", "monthly-returns"] as const,
  alerts: ["dashboard", "alerts"] as const,
  systemHealthDash: ["system-health-dash"] as const,

  // ── PT ──
  ptGraduation: ["pt", "graduation"] as const,

  // ── Market ──
  marketIndices: ["market-indices"] as const,
  marketSectors: ["market-sectors"] as const,

  // ── Reports ──
  reportsList: ["reports-list"] as const,
  reportsQuickStats: ["reports-quick-stats"] as const,

  // ── System ──
  systemHealth: ["system", "health"] as const,
  dataSources: ["system", "data-sources"] as const,

  // ── Pipeline/Agent ──
  pipelineStatus: ["pipeline", "status"] as const,
  agentConfig: ["agent", "config"] as const,
} as const;
