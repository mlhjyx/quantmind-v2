import { useEffect, useState, useCallback } from "react";
import type {
  DashboardSummary,
  NAVPoint,
  NAVPeriod,
  Position,
  CircuitBreakerState,
  PendingAction,
} from "@/types/dashboard";
import {
  fetchSummary,
  fetchNAVSeries,
  fetchPositions,
  fetchCircuitBreakerState,
  fetchPendingActions,
} from "@/api/dashboard";
import {
  MOCK_SUMMARY,
  MOCK_NAV_SERIES,
  MOCK_POSITIONS,
  MOCK_CIRCUIT_BREAKER,
  MOCK_PENDING_ACTIONS,
} from "@/api/mock";
import KPICards from "@/components/KPICards";
import NAVChart from "@/components/NAVChart";
import PositionTable from "@/components/PositionTable";
import CircuitBreaker from "@/components/CircuitBreaker";

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [navSeries, setNavSeries] = useState<NAVPoint[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [breaker, setBreaker] = useState<CircuitBreakerState | null>(null);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [period, setPeriod] = useState<NAVPeriod>("3m");
  const [loading, setLoading] = useState(true);
  const [useMock, setUseMock] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, n, p, b, a] = await Promise.all([
        fetchSummary(),
        fetchNAVSeries(period),
        fetchPositions(),
        fetchCircuitBreakerState(),
        fetchPendingActions(),
      ]);
      setSummary(s);
      setNavSeries(n);
      setPositions(p);
      setBreaker(b);
      setPendingActions(a);
      setUseMock(false);
    } catch {
      // Fallback to mock data
      setSummary(MOCK_SUMMARY);
      setNavSeries(MOCK_NAV_SERIES);
      setPositions(MOCK_POSITIONS);
      setBreaker(MOCK_CIRCUIT_BREAKER);
      setPendingActions(MOCK_PENDING_ACTIONS);
      setUseMock(true);
      setError("API 未连通，使用 Mock 数据");
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Auto-refresh every 60s
  useEffect(() => {
    const timer = setInterval(() => void loadData(), 60_000);
    return () => clearInterval(timer);
  }, [loadData]);

  // Calculate running days from first NAV point
  const runningDays = navSeries.length > 0 ? navSeries.length : 0;

  return (
    <div className="min-h-screen bg-[#0f172a] text-white p-4 lg:p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-bold text-gray-100">
            QuantMind V2
            <span className="ml-2 text-sm font-normal text-gray-400">
              Paper Trading v1.1
            </span>
          </h1>
          {summary?.trade_date && (
            <p className="text-xs text-gray-500 mt-0.5">
              最新数据: {summary.trade_date}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          {useMock && (
            <span className="px-2 py-0.5 text-xs rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">
              MOCK
            </span>
          )}
          {pendingActions.length > 0 && (
            <span className="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400 border border-red-500/30">
              {pendingActions.length} 待处理
            </span>
          )}
          <button
            onClick={() => void loadData()}
            disabled={loading}
            className="px-3 py-1.5 text-xs rounded-lg bg-white/5 border border-white/10 text-gray-300 hover:bg-white/10 transition-colors disabled:opacity-50"
          >
            {loading ? "刷新中..." : "刷新"}
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div className="mb-5">
        <KPICards data={summary} runningDays={runningDays} loading={loading} />
      </div>

      {/* NAV Chart + Circuit Breaker */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-5">
        <div className="lg:col-span-3">
          <NAVChart
            data={navSeries}
            period={period}
            onPeriodChange={setPeriod}
            loading={loading}
          />
        </div>
        <div className="lg:col-span-1">
          <CircuitBreaker data={breaker} loading={loading} />
          {/* Pending actions below circuit breaker */}
          {pendingActions.length > 0 && (
            <div className="mt-4 rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4">
              <h2 className="text-sm font-medium text-gray-300 mb-2">
                待处理
              </h2>
              <div className="space-y-2">
                {pendingActions.map((a, i) => (
                  <div
                    key={i}
                    className={`text-xs px-2 py-1.5 rounded border ${
                      a.severity === "critical"
                        ? "bg-red-500/10 border-red-500/20 text-red-400"
                        : a.severity === "warning"
                          ? "bg-amber-500/10 border-amber-500/20 text-amber-400"
                          : "bg-sky-500/10 border-sky-500/20 text-sky-400"
                    }`}
                  >
                    {a.message}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Position Table */}
      <PositionTable data={positions} loading={loading} />
    </div>
  );
}
