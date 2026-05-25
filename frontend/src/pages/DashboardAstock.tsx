import { useEffect, useState, useCallback } from "react";
// Frontend Design v3 §4.3: raw axios → apiClient SSOT (Audit Finding #5)
import apiClient from "@/api/client";
import { Link, useNavigate } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { fetchSummary, fetchNAVSeries, fetchPendingActions } from "@/api/dashboard";
import type { DashboardSummary, NAVPoint, PendingAction } from "@/types/dashboard";
import { useQuery } from "@tanstack/react-query";

const MONTHS = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"];

// Strategy selector options — static UI list, not fetched data
const STRATEGIES = [
  { id: "v1.1", label: "动量反转 v1.1" },
  { id: "v1.2", label: "动量反转 v1.2 (测试)" },
];

interface SectorItem { value: number; name: string; }
interface FactorStatusData { active: number; new: number; warning: number; failed: number; }

function pnlColorClass(v: number) {
  if (v > 0) return "text-green-400";
  if (v < 0) return "text-red-400";
  return "text-gray-400";
}
function pnlSign(v: number) {
  return v >= 0 ? "+" : "";
}

// ─────────────────────────────────────────────
// Strategy Selector Dropdown
// ─────────────────────────────────────────────
function StrategySelector({
  selected,
  onChange,
}: {
  selected: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = STRATEGIES.find((s) => s.id === selected) ?? STRATEGIES[0]!;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg bg-white/5 border border-white/10 text-slate-200 hover:bg-white/10 transition-colors"
      >
        <span>{current.label}</span>
        <span className="text-slate-400 text-xs">▾</span>
      </button>
      {open && (
        <div className="absolute left-0 top-9 w-48 rounded-xl border border-white/10 bg-slate-900/95 backdrop-blur-xl shadow-2xl z-20">
          {STRATEGIES.map((s) => (
            <button
              key={s.id}
              onClick={() => { onChange(s.id); setOpen(false); }}
              className={[
                "w-full text-left px-3 py-2 text-sm transition-colors",
                s.id === selected
                  ? "text-blue-300 bg-blue-600/20"
                  : "text-slate-300 hover:bg-white/5",
              ].join(" ")}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────
// Layer 1: 7 KPI Cards
// ─────────────────────────────────────────────
function KPICards({
  summary,
  loading,
}: {
  summary: DashboardSummary | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
        {[...Array(7)].map((_, i) => (
          <GlassCard key={i}>
            <div className="h-3 w-12 bg-white/10 rounded animate-pulse mb-2" />
            <div className="h-5 w-16 bg-white/10 rounded animate-pulse" />
          </GlassCard>
        ))}
      </div>
    );
  }

  if (!summary) return null;

  const metrics = [
    {
      label: "组合净值",
      value: summary.nav.toFixed(4),
      color: pnlColorClass(summary.nav - 1),
    },
    {
      label: "今日盈亏",
      value: `${pnlSign(summary.daily_return)}${(summary.daily_return * 100).toFixed(2)}%`,
      color: pnlColorClass(summary.daily_return),
    },
    {
      label: "累计收益",
      value: `${pnlSign(summary.cumulative_return)}${(summary.cumulative_return * 100).toFixed(2)}%`,
      color: pnlColorClass(summary.cumulative_return),
    },
    {
      label: "Sharpe",
      value: summary.sharpe.toFixed(2),
      color: summary.sharpe >= 1.0 ? "text-green-400" : "text-amber-400",
    },
    {
      label: "最大回撤",
      value: `${(summary.mdd * 100).toFixed(2)}%`,
      color: "text-red-400",
    },
    {
      label: "当前仓位",
      value: `${((1 - summary.cash_ratio) * 100).toFixed(1)}%`,
      color: "text-slate-200",
    },
    {
      label: "超额收益",
      value: `${pnlSign(summary.cumulative_return - 0.012)}${((summary.cumulative_return - 0.012) * 100).toFixed(2)}%`,
      color: pnlColorClass(summary.cumulative_return - 0.012),
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
      {metrics.map((m) => (
        <GlassCard key={m.label}>
          <p className="text-[11px] text-slate-400 mb-1 truncate">{m.label}</p>
          <p className={`text-base font-bold font-mono ${m.color}`}>{m.value}</p>
        </GlassCard>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────
// Layer 2: Full NAV Chart
// ─────────────────────────────────────────────
function NAVChart({ navSeries }: { navSeries: NAVPoint[] }) {
  const dates = navSeries.map((p) => p.trade_date);
  const navValues = navSeries.map((p) => p.nav);

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15,20,45,0.95)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
      formatter: (params: Array<{ value: number; axisValue: string }>) => {
        const p = params[0];
        if (!p) return "";
        const ret = ((p.value - 1) * 100).toFixed(2);
        return `${p.axisValue}<br/>净值: ${p.value.toFixed(4)}<br/>累计: ${ret}%`;
      },
    },
    grid: { top: 16, right: 16, bottom: 36, left: 54 },
    xAxis: {
      type: "category",
      data: dates,
      axisLabel: {
        color: "#64748b",
        fontSize: 10,
        formatter: (v: string) => v.slice(5),
        interval: Math.floor(dates.length / 6),
      },
      axisLine: { lineStyle: { color: "rgba(255,255,255,0.1)" } },
      splitLine: { show: false },
    },
    yAxis: {
      scale: true,
      axisLabel: {
        color: "#64748b",
        fontSize: 10,
        formatter: (v: number) => v.toFixed(3),
      },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
    },
    series: [
      {
        name: "净值",
        type: "line",
        data: navValues,
        smooth: true,
        symbol: "none",
        lineStyle: { color: "#3b82f6", width: 2 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(59,130,246,0.25)" },
              { offset: 1, color: "rgba(59,130,246,0.02)" },
            ],
          },
        },
        markLine: {
          silent: true,
          symbol: "none",
          data: [{ yAxis: 1.0, lineStyle: { color: "rgba(255,255,255,0.15)", type: "dashed" } }],
          label: { show: false },
        },
      },
    ],
  };

  return (
    <GlassCard className="mb-4">
      <h2 className="text-sm font-medium text-slate-300 mb-2">净值走势 (含仓位水位)</h2>
      {navSeries.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-slate-500 text-sm">暂无数据</div>
      ) : (
        <ReactECharts option={option} style={{ height: 220 }} opts={{ renderer: "canvas" }} />
      )}
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Layer 3L: Sector Pie Chart
// ─────────────────────────────────────────────
function SectorPie({ sectors }: { sectors: SectorItem[] }) {
  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: "{b}: {c}%",
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
    legend: {
      orient: "vertical",
      right: "2%",
      top: "center",
      textStyle: { color: "#94a3b8", fontSize: 11 },
      itemWidth: 8,
      itemHeight: 8,
    },
    series: [
      {
        name: "行业分布",
        type: "pie",
        radius: ["38%", "65%"],
        center: ["38%", "50%"],
        avoidLabelOverlap: true,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 12, color: "#e2e8f0" },
        },
        data: sectors,
        color: [
          "#3b82f6","#8b5cf6","#06b6d4","#10b981",
          "#f59e0b","#ef4444","#ec4899","#6366f1","#64748b",
        ],
      },
    ],
  };

  return (
    <GlassCard>
      <h2 className="text-sm font-medium text-slate-300 mb-1">行业分布 (SW1)</h2>
      <ReactECharts option={option} style={{ height: 200 }} opts={{ renderer: "canvas" }} />
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Layer 3R: Factor Library Status
// ─────────────────────────────────────────────
function FactorLibraryStatus({ factorStatus }: { factorStatus: FactorStatusData }) {
  const items = [
    { icon: "✅", label: "Active", count: factorStatus.active, color: "text-green-400" },
    { icon: "🆕", label: "New", count: factorStatus.new, color: "text-blue-400" },
    { icon: "⚠️", label: "Warning", count: factorStatus.warning, color: "text-amber-400" },
    { icon: "❌", label: "Failed", count: factorStatus.failed, color: "text-red-400" },
  ];

  return (
    <GlassCard>
      <h2 className="text-sm font-medium text-slate-300 mb-3">因子库状态</h2>
      <div className="grid grid-cols-2 gap-3 mb-4">
        {items.map((it) => (
          <div
            key={it.label}
            className="flex items-center gap-2 p-2.5 rounded-lg bg-white/4 border border-white/8"
          >
            <span className="text-xl">{it.icon}</span>
            <div>
              <p className={`text-xl font-bold font-mono ${it.color}`}>{it.count}</p>
              <p className="text-[11px] text-slate-500">{it.label}</p>
            </div>
          </div>
        ))}
      </div>
      <div className="text-xs text-slate-500 space-y-1">
        <div className="flex justify-between">
          <span>总因子数</span>
          <span className="text-slate-300 font-mono">
            {factorStatus.active + factorStatus.new + factorStatus.warning + factorStatus.failed}
          </span>
        </div>
        <div className="flex justify-between">
          <span>v1.1 使用中</span>
          <span className="text-slate-300 font-mono">5</span>
        </div>
        <div className="flex justify-between">
          <span>最后更新</span>
          <span className="text-slate-300 font-mono">2026-03-27</span>
        </div>
      </div>
      <Link
        to="/factors"
        className="mt-3 flex items-center justify-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
      >
        查看因子库 →
      </Link>
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Layer 4: Monthly Returns Heatmap (table)
// ─────────────────────────────────────────────
function MonthlyHeatmap({ monthlyData }: { monthlyData: Record<string, (number | null)[]> }) {
  function cellBg(v: number | null): string {
    if (v === null) return "bg-white/3 text-slate-600";
    if (v > 0.03) return "bg-green-500/70 text-white";
    if (v > 0.015) return "bg-green-500/40 text-green-200";
    if (v > 0) return "bg-green-500/20 text-green-300";
    if (v > -0.015) return "bg-red-500/20 text-red-300";
    if (v > -0.03) return "bg-red-500/40 text-red-200";
    return "bg-red-500/70 text-white";
  }

  const years = Object.keys(monthlyData).sort().reverse();

  return (
    <GlassCard className="mb-4">
      <h2 className="text-sm font-medium text-slate-300 mb-3">月度收益矩阵</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="text-left text-slate-500 font-normal pb-2 w-12">年份</th>
              {MONTHS.map((m) => (
                <th key={m} className="text-center text-slate-500 font-normal pb-2 px-0.5">{m}</th>
              ))}
              <th className="text-center text-slate-500 font-normal pb-2 px-1">全年</th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const months = monthlyData[year] ?? [];
              const validMonths = months.filter((v): v is number => v !== null);
              const yearTotal = validMonths.reduce((s, v) => s * (1 + v), 1) - 1;
              return (
                <tr key={year}>
                  <td className="text-slate-400 font-mono pr-2 py-1">{year}</td>
                  {months.map((v, i) => (
                    <td key={i} className="px-0.5 py-0.5">
                      <div
                        className={`text-center rounded py-1 px-0.5 font-mono text-[11px] ${cellBg(v)}`}
                      >
                        {v === null ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`}
                      </div>
                    </td>
                  ))}
                  <td className="px-1 py-0.5">
                    <div
                      className={`text-center rounded py-1 px-1 font-mono text-[11px] font-semibold ${cellBg(validMonths.length > 0 ? yearTotal : null)}`}
                    >
                      {validMonths.length > 0
                        ? `${yearTotal >= 0 ? "+" : ""}${(yearTotal * 100).toFixed(1)}%`
                        : "—"}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Layer 5: AI Closed-loop Status + Quick Actions
// ─────────────────────────────────────────────
function AIStatusAndActions() {
  const navigate = useNavigate();

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <GlassCard>
        <h2 className="text-sm font-medium text-slate-300 mb-3">AI闭环状态</h2>
        <div className="flex items-center gap-3 mb-3">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-400 shrink-0" />
          <span className="text-sm text-slate-200 font-medium">L1 半自动模式</span>
        </div>
        <div className="space-y-1.5 text-xs text-slate-400">
          <div className="flex justify-between">
            <span>上次运行</span>
            <span className="text-slate-200 font-mono">2026-03-18</span>
          </div>
          <div className="flex justify-between">
            <span>下次计划</span>
            <span className="text-slate-200 font-mono">2026-03-24</span>
          </div>
          <div className="flex justify-between">
            <span>待审批因子</span>
            <span className="text-amber-400 font-mono font-semibold">2</span>
          </div>
          <div className="flex justify-between">
            <span>Pipeline 状态</span>
            <span className="text-green-400 font-mono">正常</span>
          </div>
        </div>
        <button
          onClick={() => navigate("/pipeline")}
          className="mt-3 w-full text-xs text-blue-400 hover:text-blue-300 transition-colors text-center"
        >
          查看 AI Pipeline →
        </button>
      </GlassCard>

      <GlassCard>
        <h2 className="text-sm font-medium text-slate-300 mb-3">快捷操作</h2>
        <div className="grid grid-cols-1 gap-2">
          <Button
            variant="primary"
            size="sm"
            className="w-full justify-start"
            onClick={() => navigate("/backtest/config")}
          >
            ▶ 运行回测
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="w-full justify-start"
            onClick={() => navigate("/factors")}
          >
            🔍 因子体检
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="w-full justify-start"
            onClick={() => navigate("/mining")}
          >
            📊 因子挖掘
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="w-full justify-start"
            onClick={() => navigate("/pipeline")}
          >
            🤖 AI Pipeline
          </Button>
        </div>
      </GlassCard>
    </div>
  );
}

// ─────────────────────────────────────────────
// iter 139 W2-F F8 — Pending Actions Panel (D8 wire)
// Backend SSOT: backend/app/api/dashboard.py:67 GET /api/dashboard/pending-actions
// Returns: PendingAction[] {type, severity, message, time} from熔断/健康/管道 sources
// ─────────────────────────────────────────────
export function PendingActionsPanel() {
  const { data, isLoading, error, refetch } = useQuery<PendingAction[]>({
    queryKey: ["dashboard-pending-actions"],
    queryFn: fetchPendingActions,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const severityColor = (sev: PendingAction["severity"]): string => {
    if (sev === "critical") return "#ef4444";
    if (sev === "warning") return "#fb923c";
    return "#22c55e";
  };

  const typeLabel = (t: PendingAction["type"]): string => {
    if (t === "health") return "健康";
    if (t === "circuit_breaker") return "熔断";
    return "管道";
  };

  if (isLoading) {
    return (
      <GlassCard className="mb-4">
        <div className="text-xs text-slate-400 mb-3">待处理事项</div>
        <div className="h-16 bg-white/5 rounded animate-pulse" />
      </GlassCard>
    );
  }

  if (error) {
    return (
      <GlassCard className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs text-slate-400">待处理事项</div>
          <button onClick={() => void refetch()} className="text-xs text-orange-400 hover:text-orange-300">重试</button>
        </div>
        <div className="text-xs text-red-400">加载失败: {error instanceof Error ? error.message : "未知错误"}</div>
      </GlassCard>
    );
  }

  const items = data ?? [];

  return (
    <GlassCard className="mb-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-slate-400">
          待处理事项 <span className="text-slate-500">({items.length})</span>
        </div>
        <button onClick={() => void refetch()} className="text-[10px] text-slate-500 hover:text-slate-300">刷新</button>
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-slate-500 py-4 text-center">✓ 无待处理事项</div>
      ) : (
        <div className="space-y-2">
          {items.map((it, i) => (
            <div
              key={`${it.type}-${i}`}
              className="flex items-start gap-3 px-3 py-2 rounded"
              style={{ background: `${severityColor(it.severity)}10`, border: `1px solid ${severityColor(it.severity)}30` }}
            >
              <span
                className="text-[10px] font-mono px-1.5 py-0.5 rounded shrink-0 mt-0.5"
                style={{ background: severityColor(it.severity), color: "white" }}
              >
                {typeLabel(it.type)}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-xs text-slate-200 break-words">{it.message}</div>
                {it.time && (
                  <div className="text-[10px] text-slate-500 font-mono mt-1">{it.time}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Main DashboardAstock
// ─────────────────────────────────────────────
export default function DashboardAstock() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [navSeries, setNavSeries] = useState<NAVPoint[]>([]);
  const [sectors, setSectors] = useState<SectorItem[] | null>(null);
  const [monthlyData, setMonthlyData] = useState<Record<string, (number | null)[]> | null>(null);
  const [factorStatus, setFactorStatus] = useState<FactorStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [strategy, setStrategy] = useState("v1.1");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, n] = await Promise.all([
        fetchSummary(),
        fetchNAVSeries("6m"),
      ]);
      setSummary(s);
      setNavSeries(n);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "请求失败";
      setError(`核心数据加载失败: ${msg}`);
    } finally {
      setLoading(false);
    }

    // Supplementary data — show empty on error, do not silently hide
    apiClient.get<SectorItem[]>("/portfolio/sector-distribution", { params: { execution_mode: "live" } })
      .then((r) => setSectors(r.data))
      .catch(() => setSectors([]));

    apiClient.get<Record<string, (number | null)[]>>("/dashboard/monthly-returns", { params: { execution_mode: "live" } })
      .then((r) => setMonthlyData(r.data))
      .catch(() => setMonthlyData({}));

    apiClient.get<{ total: number; active: number; candidate: number; warning: number; critical: number; retired: number }>("/factors/stats")
      .then((r) => {
        setFactorStatus({
          active: r.data.active ?? 0,
          new: r.data.candidate ?? 0,
          warning: r.data.warning ?? 0,
          failed: r.data.critical ?? 0,
        });
      })
      .catch(() => setFactorStatus({ active: 0, new: 0, warning: 0, failed: 0 }));
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "总览", path: "/dashboard" },
          { label: "A股详情" },
        ]}
      />

      {/* Error banner */}
      {error && (
        <div className="mb-4">
          <ErrorBanner message={error} onRetry={() => void loadData()} />
        </div>
      )}

      {/* Top bar */}
      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Link
            to="/dashboard"
            className="text-slate-400 hover:text-slate-200 text-sm transition-colors"
          >
            ← 返回总览
          </Link>
          <h1 className="text-2xl font-bold text-white">A股详情</h1>
        </div>
        <div className="flex items-center gap-2">
          <StrategySelector selected={strategy} onChange={setStrategy} />
          <Button variant="secondary" size="sm" onClick={() => void loadData()}>
            {loading ? "加载中..." : "刷新"}
          </Button>
        </div>
      </div>

      {/* Layer 1: 7 KPI cards */}
      <KPICards summary={summary} loading={loading} />

      {/* Layer 2: Full NAV chart */}
      <NAVChart navSeries={navSeries} />

      {/* Layer 3: Sector pie + Factor library status */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        {sectors === null ? (
          <GlassCard>
            <div className="h-3 w-20 bg-white/10 rounded animate-pulse mb-3" />
            <div className="h-48 bg-white/5 rounded animate-pulse" />
          </GlassCard>
        ) : (
          <SectorPie sectors={sectors} />
        )}
        {factorStatus === null ? (
          <GlassCard>
            <div className="h-3 w-20 bg-white/10 rounded animate-pulse mb-3" />
            <div className="grid grid-cols-2 gap-3">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-14 bg-white/5 rounded-lg animate-pulse" />
              ))}
            </div>
          </GlassCard>
        ) : (
          <FactorLibraryStatus factorStatus={factorStatus} />
        )}
      </div>

      {/* Layer 4: Monthly returns heatmap */}
      {monthlyData === null ? (
        <GlassCard className="mb-4">
          <div className="h-3 w-24 bg-white/10 rounded animate-pulse mb-3" />
          <div className="h-32 bg-white/5 rounded animate-pulse" />
        </GlassCard>
      ) : (
        <MonthlyHeatmap monthlyData={monthlyData} />
      )}

      {/* Layer 5: AI status + quick actions */}
      <AIStatusAndActions />

      {/* Layer 6: Pending actions (iter 139 W2-F F8 — D8 wire) */}
      <PendingActionsPanel />

      <p className="text-xs text-slate-600 mt-4 text-center">
        数据来源: /api/paper-trading/positions · /api/dashboard/summary · /api/factors · /api/dashboard/pending-actions
      </p>
    </div>
  );
}
