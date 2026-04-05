import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Link } from "react-router-dom";
import { ChevronRight, Play, Bell } from "lucide-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Card, CardHeader } from "@/components/shared";
import { fetchSummary, fetchPositions, fetchNAVSeries } from "@/api/dashboard";
import { C } from "@/theme";
import type { DashboardSummary, Position } from "@/types/dashboard";
import { usePortfolio } from "@/hooks/useRealtimeData";

import { KPIGrid } from "./KPIGrid";
import { EquityCurve } from "./EquityCurve";
import type { NavChartPoint } from "./EquityCurve";
import { AlertsPanel } from "./AlertsPanel";
import type { Alert } from "./AlertsPanel";
import { StrategiesPanel } from "./StrategiesPanel";
import { HoldingsTable } from "./HoldingsTable";
import { MonthlyHeatmap } from "./MonthlyHeatmap";
import { IndustryAndSystem } from "./IndustryAndSystem";
import type { IndustryItem } from "./IndustryAndSystem";
import { FactorLibraryPanel } from "./FactorLibraryPanel";
import type { FactorRow } from "./FactorLibraryPanel";
import { AIPipelinePanel } from "./AIPipelinePanel";
import type { PipelineStep } from "./AIPipelinePanel";

export default function DashboardOverview() {
  const { data: rtPortfolio } = usePortfolio();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [monthlyData, setMonthlyData] = useState<Record<string, number[]> | null>(null);
  const [industryDist, setIndustryDist] = useState<IndustryItem[] | null>(null);
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
    axios.get<Alert[]>("/api/dashboard/alerts", { params: { execution_mode: "live" } })
      .then((r) => setAlerts(r.data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setAlertsError(`预警数据加载失败: ${msg}`);
        setAlerts([]);
      });

    // Monthly returns
    setMonthlyError(null);
    axios.get<Record<string, number[]>>("/api/dashboard/monthly-returns", { params: { execution_mode: "live" } })
      .then((r) => setMonthlyData(r.data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setMonthlyError(`月度收益加载失败: ${msg}`);
        setMonthlyData({});
      });

    // Industry distribution
    setIndustryError(null);
    axios.get<IndustryItem[]>("/api/dashboard/industry-distribution", { params: { execution_mode: "live" } })
      .then((r) => setIndustryDist(r.data))
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "请求失败";
        setIndustryError(`行业分布加载失败: ${msg}`);
        setIndustryDist([]);
      });

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
    axios.get<{ name: string; category: string; direction: string; status: string; ic_mean: number | null; ic_ir: number | null }[]>("/api/factors")
      .then((r) => {
        const rows: FactorRow[] = r.data.map((f) => ({
          name: f.name,
          cat: f.category ?? "未知",
          ic: f.ic_mean ?? 0,
          ir: f.ic_ir ?? 0,
          dir: f.direction === "positive" ? "正向" : "反向",
          status: f.status === "active" ? "active" : f.status === "candidate" ? "new" : "decay",
          trend: [],
        }));
        setFactorData(rows);
      })
      .catch(() => {
        setFactorData([]);
      });

    // Pipeline status → transform node_statuses to steps array
    axios.get<{ node_statuses: Record<string, string>; current_node: string | null; status: string }>("/api/pipeline/status")
      .then((r) => {
        const nodeMap = r.data.node_statuses ?? {};
        const currentNode = r.data.current_node;
        const pipelineStatus = r.data.status;
        const steps: PipelineStep[] = Object.entries(nodeMap).map(([name, st]) => {
          let status: string;
          if (st === "completed") status = "done";
          else if (name === currentNode && pipelineStatus === "running") status = "running";
          else if (st === "pending") status = "pending";
          else status = st;
          return { name, status };
        });
        setPipelineSteps(steps);
      })
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
          <span style={{ fontSize: 10, color: C.text4 }}>PT Day 3/60</span>
          <ChevronRight size={12} color={C.text4} />
        </Link>
        <Link to="/dashboard/forex" className="flex items-center gap-2 px-3 py-1.5 rounded-lg cursor-pointer" style={{ background: C.bg1, border: `1px solid ${C.border}`, opacity: 0.5 }}>
          <span style={{ fontSize: 12, color: C.text3 }}>外汇策略</span>
          <span style={{ fontSize: 10, color: C.text4 }}>Phase 2</span>
          <ChevronRight size={12} color={C.text4} />
        </Link>
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
