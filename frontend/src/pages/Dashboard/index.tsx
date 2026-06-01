import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { ChevronRight, Play, Bell } from "lucide-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Card, CardHeader } from "@/components/shared";
import {
  fetchAlerts,
  fetchDashboardFactorRows,
  fetchDashboardPipelineSteps,
  fetchIndustryDistribution,
  fetchMarketTicker,
  fetchMonthlyReturns,
  fetchNAVSeries,
  fetchPendingActions,
  fetchPositions,
  fetchSummary,
} from "@/api/dashboard";
import { fetchEnvState, fetchCalendarInfo, type EnvState, type CalendarInfo } from "@/api/system";
import { C } from "@/theme";
import type {
  Alert,
  DashboardSummary,
  FactorRow,
  IndustryItem,
  MarketTickerItem,
  MonthlyReturns,
  PendingAction,
  PipelineStep,
  Position,
} from "@/types/dashboard";
import { usePortfolio } from "@/hooks/useRealtimeData";
import { ShutdownBanner } from "@/components/safety/ShutdownBanner";

import { KPIGrid } from "./KPIGrid";
import { EquityCurve } from "./EquityCurve";
import type { NavChartPoint } from "./EquityCurve";
import { AlertsPanel } from "./AlertsPanel";
import { PendingActionsPanel } from "./PendingActionsPanel";
import { AttributionPanel } from "./AttributionPanel";  // iter 147 W2-F F6
import { StrategiesPanel } from "./StrategiesPanel";
import { HoldingsTable } from "./HoldingsTable";
import { MonthlyHeatmap } from "./MonthlyHeatmap";
import { IndustryAndSystem } from "./IndustryAndSystem";
import { FactorLibraryPanel } from "./FactorLibraryPanel";
import { AIPipelinePanel } from "./AIPipelinePanel";

export default function DashboardOverview() {
  const { data: rtPortfolio } = usePortfolio();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [envState, setEnvState] = useState<EnvState | null>(null);
  const [calendarInfo, setCalendarInfo] = useState<CalendarInfo | null>(null);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  // iter 139 W2-F F8 closure — pending actions widget (熔断/健康/管道)
  const [pendingActions, setPendingActions] = useState<PendingAction[] | null>(null);
  const [monthlyData, setMonthlyData] = useState<MonthlyReturns | null>(null);
  const [industryDist, setIndustryDist] = useState<IndustryItem[] | null>(null);
  const [marketTicker, setMarketTicker] = useState<MarketTickerItem[]>([]);
  const [navChartData, setNavChartData] = useState<NavChartPoint[]>([]);
  const [factorData, setFactorData] = useState<FactorRow[]>([]);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [monthlyError, setMonthlyError] = useState<string | null>(null);
  const [industryError, setIndustryError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, p] = await Promise.all([
        fetchSummary(),
        fetchPositions(),
      ]);
      setSummary(s);
      setPositions(p);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "加载失败";
      setError(`核心数据加载失败: ${msg}`);
    } finally {
      setLoading(false);
    }

    // Alerts
    setAlertsError(null);
    fetchAlerts()
      .then(setAlerts)
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setAlertsError(`预警数据加载失败: ${msg}`);
        setAlerts([]);
      });

    // iter 139 W2-F F8 — pending actions (熔断/健康/管道 events).
    // Backend: GET /api/dashboard/pending-actions (dashboard.py:67).
    // Fail-soft: on error fall back to empty array (sibling alerts pattern).
    fetchPendingActions()
      .then(setPendingActions)
      .catch(() => setPendingActions([]));

    // Monthly returns
    setMonthlyError(null);
    fetchMonthlyReturns()
      .then(setMonthlyData)
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setMonthlyError(`月度收益加载失败: ${msg}`);
        setMonthlyData({});
      });

    // Industry distribution
    setIndustryError(null);
    fetchIndustryDistribution()
      .then(setIndustryDist)
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setIndustryError(`行业分布加载失败: ${msg}`);
        setIndustryDist([]);
      });

    fetchMarketTicker()
      .then(setMarketTicker)
      .catch(() => setMarketTicker([]));

    // NAV series → transform to chart format
    fetchNAVSeries("all")
      .then((pts) => {
        const chartPts = pts.map((pt) => ({
          date: pt.trade_date.slice(5),  // "MM-DD"
          strategy: pt.nav,
          benchmark: 1.0,               // benchmark not in API; keep flat
          excess: +(pt.cumulative_return * 100).toFixed(2),
        }));
        setNavChartData(chartPts);
      })
      .catch(() => {
        setNavChartData([]);
      });

    // Factors list
    fetchDashboardFactorRows()
      .then(setFactorData)
      .catch(() => {
        setFactorData([]);
      });

    // Env state for ShutdownBanner condition (LL-183 prevention sibling)
    fetchEnvState()
      .then(setEnvState)
      .catch(() => setEnvState(null));

    // Calendar SSOT (Audit Section X §39 — PT Day X/Y 替 hardcoded)
    fetchCalendarInfo()
      .then(setCalendarInfo)
      .catch(() => setCalendarInfo(null));

    // Pipeline status → transform node_statuses to steps array
    fetchDashboardPipelineSteps()
      .then(setPipelineSteps)
      .catch(() => {
        setPipelineSteps([]);
      });
  }, []);

  useEffect(() => {
    void loadData();
    const id = setInterval(() => void loadData(), 30_000);
    return () => clearInterval(id);
  }, [loadData]);

  return (
    <div style={{ background: C.bg0, minHeight: "100vh", fontFamily: "'Inter', -apple-system, 'Noto Sans SC', sans-serif" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-2.5 shrink-0" style={{ borderBottom: `1px solid ${C.border}` }}>
        <Breadcrumb />
        <div className="flex items-center gap-3">
          <h1 style={{ fontSize: 18, fontWeight: 700, color: C.text1 }}>驾驶舱</h1>
          <span className="px-2 py-0.5 rounded-full" style={{ fontSize: 10, background: rtPortfolio?.qmt_connected ? `${C.down}15` : `${C.up}15`, color: rtPortfolio?.qmt_connected ? C.down : C.up, fontWeight: 500 }}>● {rtPortfolio?.qmt_connected ? "实盘" : "模拟盘"}</span>
          <span style={{ fontSize: 12, color: C.text4 }}>
            {summary?.trade_date ? `v1.1 · ${summary.trade_date}` : "动量反转 v3 · A股"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative w-8 h-8 rounded-lg flex items-center justify-center cursor-pointer" style={{ background: C.bg1, border: `1px solid ${C.border}` }}>
            <Bell size={15} color={C.text3} />
            <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center" style={{ background: C.down, fontSize: 9, color: "#fff", fontWeight: 600 }}>
              {alerts?.length ?? 0}
            </div>
          </div>
          <button
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg cursor-pointer"
            style={{ background: C.accentSoft, border: `1px solid ${C.accent}40` }}
            onClick={() => void loadData()}
          >
            <Play size={12} color={C.accent} fill={C.accent} />
            <span style={{ fontSize: 12, color: "#a5b4fc" }}>{loading ? "加载中..." : "运行回测"}</span>
          </button>
          <Button variant="secondary" size="sm" onClick={() => void loadData()}>
            {loading ? "..." : "刷新"}
          </Button>
        </div>
      </div>

      {/* Maintenance/shutdown banner — only renders when 0 持仓 + cash > 95 万 + LIVE_TRADING_DISABLED */}
      {envState && summary && (
        <div className="px-5 pt-3">
          <ShutdownBanner
            positionsCount={summary.position_count}
            cashAmount={
              rtPortfolio?.account?.available_cash ??
              summary.nav * (summary.cash_ratio ?? 0)
            }
            liveTradingDisabled={envState.live_trading_disabled}
          />
        </div>
      )}

      {/* Error banners */}
      {error && (
        <div className="px-5 pt-3">
          <ErrorBanner message={error} onRetry={() => void loadData()} />
        </div>
      )}
      {alertsError && (
        <div className="px-5 pt-2">
          <ErrorBanner message={alertsError} onRetry={() => void loadData()} />
        </div>
      )}
      {monthlyError && (
        <div className="px-5 pt-2">
          <ErrorBanner message={monthlyError} onRetry={() => void loadData()} />
        </div>
      )}
      {industryError && (
        <div className="px-5 pt-2">
          <ErrorBanner message={industryError} onRetry={() => void loadData()} />
        </div>
      )}

      {/* Sub-market nav links */}
      <div className="flex items-center gap-3 px-5 py-2" style={{ borderBottom: `1px solid ${C.border}` }}>
        <Link to="/dashboard/astock" className="flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer" style={{ background: C.bg1, border: `1px solid ${C.border}` }}>
          <span style={{ fontSize: 12, color: C.text1 }}>A股策略 v1.1</span>
          <span style={{ fontSize: 10, color: C.text4 }} title={calendarInfo?.pt_day_counter ? `start=${calendarInfo.pt_day_counter.start_date} today=${calendarInfo.pt_day_counter.today}` : "calendar SSOT 未连接"}>
            {calendarInfo?.pt_day_counter?.label ?? "PT Day —/—"}
          </span>
          <ChevronRight size={12} color={C.text4} />
        </Link>
        {/* 外汇策略 link 已移除 (DEV_FOREX DEFERRED, Phase H Week 6 cleanup) */}
        {marketTicker.length > 0 && (
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto">
            {marketTicker.map((item) => (
              <div
                key={item.code || item.label}
                className="flex shrink-0 items-center gap-2 rounded-lg px-2.5 py-1.5"
                style={{ background: C.bg1, border: `1px solid ${C.border}` }}
              >
                <span style={{ fontSize: 11, color: C.text3 }}>{item.label}</span>
                <span style={{ fontSize: 12, color: C.text1, fontVariantNumeric: "tabular-nums" }}>
                  {Number(item.value).toFixed(2)}
                </span>
                <span
                  style={{
                    fontSize: 11,
                    color: item.is_up ? C.down : C.up,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {item.change_pct >= 0 ? "+" : ""}
                  {Number(item.change_pct).toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-3 pt-3">
        {/* ROW 1: 2×4 KPI cards */}
        {loading ? (
          <div className="grid grid-cols-4 gap-3">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="rounded-xl p-3.5" style={{ minHeight: 92, background: C.bg1, border: `1px solid ${C.border}` }}>
                <div className="h-3 w-16 rounded mb-2 animate-pulse" style={{ background: C.bg3 }} />
                <div className="h-6 w-24 rounded animate-pulse" style={{ background: C.bg3 }} />
              </div>
            ))}
          </div>
        ) : (
          <KPIGrid summary={summary} rtAccount={rtPortfolio?.account} />
        )}

        {/* ROW 2: Equity curve (8 cols) + Alerts+Strategies (4 cols) */}
        <div className="grid grid-cols-12 gap-3">
          <EquityCurve navChartData={navChartData} />
          <div className="col-span-4 flex flex-col gap-3">
            {/* iter 139 W2-F F8 — Pending Actions widget (熔断/健康/管道). */}
            {pendingActions === null ? (
              <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 200 }}>
                <div className="p-4 space-y-2">
                  {[...Array(2)].map((_, i) => (
                    <div key={i} className="h-12 rounded-lg animate-pulse" style={{ background: C.bg2 }} />
                  ))}
                </div>
              </Card>
            ) : (
              <PendingActionsPanel actions={pendingActions} />
            )}
            {/* iter 147 W2-F F6 — Attribution panel (daily_attribution table). */}
            <AttributionPanel />
            {alerts === null ? (
              <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 320 }}>
                <div className="p-4 space-y-2">
                  {[...Array(4)].map((_, i) => (
                    <div key={i} className="h-12 rounded-lg animate-pulse" style={{ background: C.bg2 }} />
                  ))}
                </div>
              </Card>
            ) : (
              <AlertsPanel alerts={alerts} />
            )}
            <StrategiesPanel />
          </div>
        </div>

        {/* ROW 3: Holdings (4) + Monthly heatmap (4) + Industry+System (4) */}
        <div className="grid grid-cols-12 gap-3">
          <HoldingsTable positions={rtPortfolio ? rtPortfolio.positions.map(p => ({
            code: p.code, quantity: p.shares, market_value: p.market_value,
            weight: p.weight / 100, avg_cost: p.cost_price,
            unrealized_pnl: p.pnl_pct / 100, holding_days: 0,
          })) : positions} />
          {monthlyData === null ? (
            <Card className="col-span-4">
              <CardHeader title="月度收益" titleEn="Monthly %" />
              <div className="p-3 space-y-2">
                {[...Array(3)].map((_, i) => (
                  <div key={i} className="h-8 rounded animate-pulse" style={{ background: C.bg2 }} />
                ))}
              </div>
            </Card>
          ) : (
            <MonthlyHeatmap monthlyData={monthlyData} />
          )}
          {industryDist === null ? (
            <div className="col-span-4 flex flex-col gap-3">
              <Card className="flex-1">
                <CardHeader title="行业分布" titleEn="Industry" />
                <div className="p-3 space-y-2">
                  {[...Array(6)].map((_, i) => (
                    <div key={i} className="h-5 rounded animate-pulse" style={{ background: C.bg2 }} />
                  ))}
                </div>
              </Card>
            </div>
          ) : (
            <IndustryAndSystem industryDist={rtPortfolio ? (() => {
              const colors = ["#5470c6", "#91cc75", "#fac858", "#ee6666", "#73c0de", "#3ba272", "#fc8452", "#9a60b4"];
              return Object.entries(rtPortfolio.industry_allocation)
                .sort(([,a], [,b]) => (b as number) - (a as number))
                .map(([name, weight], i) => ({ name, pct: Math.round((weight as number) * 100) / 100, color: colors[i % colors.length]! }));
            })() : industryDist} />
          )}
        </div>

        {/* ROW 4: Factor library (7) + AI Pipeline (5) */}
        <div className="grid grid-cols-12 gap-3">
          <FactorLibraryPanel factorData={factorData} />
          <AIPipelinePanel pipelineSteps={pipelineSteps} />
        </div>
      </div>
    </div>
  );
}
