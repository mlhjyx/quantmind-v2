import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import type {
  DashboardSummary,
  NAVPoint,
  NAVPeriod,
  Position,
  CircuitBreakerState,
} from "@/types/dashboard";
import {
  fetchSummary,
  fetchNAVSeries,
  fetchPositions,
  fetchCircuitBreakerState,
} from "@/api/dashboard";
import {
  MOCK_SUMMARY,
  MOCK_NAV_SERIES,
  MOCK_POSITIONS,
  MOCK_CIRCUIT_BREAKER,
} from "@/api/mock";
import KPICards from "@/components/KPICards";
import NAVChart from "@/components/NAVChart";
import PositionTable from "@/components/PositionTable";
import CircuitBreaker from "@/components/CircuitBreaker";

// ── Notification types for T2 ──────────────────────────────────────────────

type NotifLevel = "P0" | "P1" | "P2";
type NotifIcon = "review" | "warning" | "success" | "cooldown";

interface Notification {
  id: string;
  icon: NotifIcon;
  title: string;
  level: NotifLevel;
  created_at: string;
  target_path: string;
}

const ICON_MAP: Record<NotifIcon, string> = {
  review: "🔍",
  warning: "⚠️",
  success: "✅",
  cooldown: "⏱️",
};

const LEVEL_STYLE: Record<NotifLevel, string> = {
  P0: "bg-red-500/10 border-red-500/20 text-red-300",
  P1: "bg-amber-500/10 border-amber-500/20 text-amber-300",
  P2: "bg-sky-500/10 border-sky-500/20 text-sky-300",
};

const MOCK_NOTIFICATIONS: Notification[] = [
  {
    id: "n1",
    icon: "review",
    title: "因子审批待处理: reversal_20_v2",
    level: "P1",
    created_at: "2小时前",
    target_path: "/pipeline",
  },
  {
    id: "n2",
    icon: "warning",
    title: "MDD预警: 已达-12.3%，接近-15%线",
    level: "P1",
    created_at: "30分钟前",
    target_path: "/dashboard",
  },
  {
    id: "n3",
    icon: "success",
    title: "回测完成: backtest_20260328_001",
    level: "P2",
    created_at: "1小时前",
    target_path: "/backtest/backtest_20260328_001/result",
  },
];

async function fetchNotifications(): Promise<Notification[]> {
  const { default: axios } = await import("axios");
  const { data } = await axios.get<Notification[]>(
    "/api/notifications?unacted=true&limit=5",
  );
  return data;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [navSeries, setNavSeries] = useState<NAVPoint[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [breaker, setBreaker] = useState<CircuitBreakerState | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>(MOCK_NOTIFICATIONS);
  const [period, setPeriod] = useState<NAVPeriod>("3m");
  const [loading, setLoading] = useState(true);
  const [useMock, setUseMock] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, n, p, b] = await Promise.all([
        fetchSummary(),
        fetchNAVSeries(period),
        fetchPositions(),
        fetchCircuitBreakerState(),
      ]);
      setSummary(s);
      setNavSeries(n);
      setPositions(p);
      setBreaker(b);
      setUseMock(false);
    } catch {
      // Fallback to mock data
      setSummary(MOCK_SUMMARY);
      setNavSeries(MOCK_NAV_SERIES);
      setPositions(MOCK_POSITIONS);
      setBreaker(MOCK_CIRCUIT_BREAKER);
      setUseMock(true);
      setError("API 未连通，使用 Mock 数据");
    } finally {
      setLoading(false);
    }

    // Load notifications independently (non-blocking)
    try {
      const notifs = await fetchNotifications();
      setNotifications(notifs);
    } catch {
      setNotifications(MOCK_NOTIFICATIONS);
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
          {notifications.length > 0 && (
            <span className="px-2 py-0.5 text-xs rounded bg-red-500/20 text-red-400 border border-red-500/30">
              {notifications.length} 待处理
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
        <div className="lg:col-span-1 flex flex-col gap-4">
          <CircuitBreaker data={breaker} loading={loading} />

          {/* Notifications / 待处理事项 */}
          <div className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium text-gray-300">待处理事项</h2>
              {notifications.length > 0 && (
                <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-red-500/20 text-red-400 border border-red-500/30 font-bold">
                  {notifications.length}
                </span>
              )}
            </div>

            {notifications.length === 0 ? (
              <p className="text-xs text-gray-500 text-center py-3">
                暂无待处理事项
              </p>
            ) : (
              <div className="space-y-2">
                {notifications.slice(0, 5).map((n) => (
                  <div
                    key={n.id}
                    className={`rounded-lg border px-2.5 py-2 ${LEVEL_STYLE[n.level]}`}
                  >
                    <div className="flex items-start gap-2">
                      <span className="text-sm shrink-0 mt-0.5">
                        {ICON_MAP[n.icon]}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium leading-snug line-clamp-2">
                          {n.title}
                        </p>
                        <div className="flex items-center justify-between mt-1.5 gap-2">
                          <span className="text-[10px] text-gray-500 shrink-0">
                            {n.created_at}
                          </span>
                          <button
                            onClick={() => navigate(n.target_path)}
                            className="text-[10px] px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 text-gray-300 transition-colors shrink-0"
                          >
                            处理
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Position Table */}
      <PositionTable data={positions} loading={loading} />
    </div>
  );
}
