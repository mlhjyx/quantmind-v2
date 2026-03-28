import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import ReactECharts from "echarts-for-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { fetchSummary, fetchNAVSeries, fetchPositions } from "@/api/dashboard";
import {
  MOCK_SUMMARY,
  MOCK_NAV_SERIES,
  MOCK_POSITIONS,
} from "@/api/mock";
import type { DashboardSummary, NAVPoint, Position } from "@/types/dashboard";

// ── Market snapshot mock (real endpoint: /api/dashboard/summary) ──
const MOCK_MARKET = [
  { name: "上证指数", code: "000001.SH", change: 0.0043, amount: 3421.5 },
  { name: "深证成指", code: "399001.SZ", change: -0.0012, amount: 4823.1 },
  { name: "创业板指", code: "399006.SZ", change: 0.0081, amount: 1234.7 },
];

// ── Sector distribution mock (real: /api/paper-trading/positions) ──
const MOCK_SECTORS = [
  { value: 14.2, name: "食品饮料" },
  { value: 12.1, name: "医药生物" },
  { value: 11.5, name: "银行" },
  { value: 10.3, name: "电力设备" },
  { value: 9.8, name: "电子" },
  { value: 8.4, name: "汽车" },
  { value: 7.6, name: "家用电器" },
  { value: 6.9, name: "非银金融" },
  { value: 19.2, name: "其他" },
];

function pnlColorClass(v: number) {
  if (v > 0) return "text-green-400";
  if (v < 0) return "text-red-400";
  return "text-gray-400";
}

function pnlSign(v: number) {
  return v >= 0 ? "+" : "";
}

// ─────────────────────────────────────────────
// Market Snapshot Card
// ─────────────────────────────────────────────
function MarketSnapshot() {
  return (
    <GlassCard>
      <h2 className="text-sm font-medium text-slate-300 mb-3">市场快照</h2>
      <div className="space-y-2">
        {MOCK_MARKET.map((m) => (
          <div key={m.code} className="flex items-center justify-between">
            <div>
              <span className="text-sm text-slate-200">{m.name}</span>
              <span className="ml-2 text-xs text-slate-500">{m.code}</span>
            </div>
            <div className="text-right">
              <div className={`text-sm font-mono font-semibold ${pnlColorClass(m.change)}`}>
                {pnlSign(m.change)}{(m.change * 100).toFixed(2)}%
              </div>
              <div className="text-xs text-slate-500">
                {m.amount.toFixed(1)}亿
              </div>
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-600 mt-3">数据来源: /api/dashboard/summary</p>
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Sector Distribution Pie Chart
// ─────────────────────────────────────────────
function SectorPieChart({ positions }: { positions: Position[] }) {
  // In production: compute from positions.sector field
  // Using mock sectors for now
  void positions;

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      formatter: "{b}: {c}% ({d}%)",
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
    legend: {
      orient: "vertical",
      right: "2%",
      top: "center",
      textStyle: { color: "#94a3b8", fontSize: 11 },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        name: "行业分布",
        type: "pie",
        radius: ["40%", "68%"],
        center: ["38%", "50%"],
        avoidLabelOverlap: true,
        label: { show: false },
        emphasis: {
          label: { show: true, fontSize: 12, fontWeight: "bold", color: "#e2e8f0" },
        },
        data: MOCK_SECTORS,
        color: [
          "#3b82f6", "#8b5cf6", "#06b6d4", "#10b981",
          "#f59e0b", "#ef4444", "#ec4899", "#6366f1", "#64748b",
        ],
      },
    ],
  };

  return (
    <GlassCard>
      <h2 className="text-sm font-medium text-slate-300 mb-2">行业分布 (SW1)</h2>
      <ReactECharts
        option={option}
        style={{ height: 200 }}
        opts={{ renderer: "canvas" }}
      />
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Monthly Returns Heatmap
// ─────────────────────────────────────────────
function MonthlyHeatmap({ navSeries }: { navSeries: NAVPoint[] }) {
  // Build calendar heatmap data from navSeries
  const heatData = navSeries.map((p) => [p.trade_date, p.daily_return]);

  const minDate = navSeries[0]?.trade_date ?? "2026-01-01";
  const maxDate = navSeries[navSeries.length - 1]?.trade_date ?? "2026-12-31";
  const year = new Date(minDate).getFullYear();

  const option = {
    backgroundColor: "transparent",
    tooltip: {
      formatter: (params: { value: [string, number] }) => {
        const [date, ret] = params.value;
        return `${date}<br/>${ret >= 0 ? "+" : ""}${(ret * 100).toFixed(2)}%`;
      },
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
    visualMap: {
      min: -0.03,
      max: 0.03,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      inRange: {
        color: ["#ef4444", "#1e293b", "#22c55e"],
      },
      text: ["+3%", "-3%"],
      textStyle: { color: "#94a3b8", fontSize: 10 },
      itemWidth: 100,
      itemHeight: 8,
    },
    calendar: {
      top: 20,
      left: 30,
      right: 30,
      cellSize: ["auto", 14],
      range: [minDate.slice(0, 7), maxDate.slice(0, 7)],
      yearLabel: { show: false },
      monthLabel: {
        nameMap: ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"],
        color: "#94a3b8",
        fontSize: 11,
      },
      dayLabel: {
        firstDay: 1,
        nameMap: ["日","一","二","三","四","五","六"],
        color: "#64748b",
        fontSize: 10,
      },
      itemStyle: {
        borderColor: "rgba(255,255,255,0.05)",
        borderWidth: 1,
      },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } },
    },
    series: [
      {
        type: "heatmap",
        coordinateSystem: "calendar",
        data: heatData,
        label: { show: false },
      },
    ],
  };

  return (
    <GlassCard>
      <h2 className="text-sm font-medium text-slate-300 mb-1">
        月度收益热力图 ({year})
      </h2>
      {navSeries.length === 0 ? (
        <div className="h-32 flex items-center justify-center text-slate-500 text-sm">
          暂无数据
        </div>
      ) : (
        <ReactECharts
          option={option}
          style={{ height: 160 }}
          opts={{ renderer: "canvas" }}
        />
      )}
    </GlassCard>
  );
}

// ─────────────────────────────────────────────
// Portfolio KPI Summary row
// ─────────────────────────────────────────────
function PortfolioKPIRow({ summary, loading }: { summary: DashboardSummary | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {[...Array(4)].map((_, i) => (
          <GlassCard key={i}>
            <div className="h-4 w-16 bg-white/10 rounded animate-pulse mb-2" />
            <div className="h-6 w-24 bg-white/10 rounded animate-pulse" />
          </GlassCard>
        ))}
      </div>
    );
  }

  const metrics = summary
    ? [
        {
          label: "组合净值",
          value: summary.nav.toFixed(4),
          sub: `累计 ${pnlSign(summary.cumulative_return)}${(summary.cumulative_return * 100).toFixed(2)}%`,
          color: pnlColorClass(summary.cumulative_return),
        },
        {
          label: "今日收益",
          value: `${pnlSign(summary.daily_return)}${(summary.daily_return * 100).toFixed(2)}%`,
          sub: `持仓 ${summary.position_count} 只`,
          color: pnlColorClass(summary.daily_return),
        },
        {
          label: "Sharpe",
          value: summary.sharpe.toFixed(2),
          sub: "年化",
          color: summary.sharpe >= 1.0 ? "text-green-400" : "text-amber-400",
        },
        {
          label: "最大回撤",
          value: `${(summary.mdd * 100).toFixed(2)}%`,
          sub: `现金比 ${(summary.cash_ratio * 100).toFixed(1)}%`,
          color: "text-red-400",
        },
      ]
    : [];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
      {metrics.map((m) => (
        <GlassCard key={m.label}>
          <p className="text-xs text-slate-400 mb-1">{m.label}</p>
          <p className={`text-lg font-bold font-mono ${m.color}`}>{m.value}</p>
          <p className="text-xs text-slate-500 mt-0.5">{m.sub}</p>
        </GlassCard>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────
// Main DashboardOverview
// ─────────────────────────────────────────────
export default function DashboardOverview() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [navSeries, setNavSeries] = useState<NAVPoint[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [useMock, setUseMock] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [s, n, p] = await Promise.all([
        fetchSummary(),
        fetchNAVSeries("6m"),
        fetchPositions(),
      ]);
      setSummary(s);
      setNavSeries(n);
      setPositions(p);
      setUseMock(false);
    } catch {
      setSummary(MOCK_SUMMARY);
      setNavSeries(MOCK_NAV_SERIES);
      setPositions(MOCK_POSITIONS);
      setUseMock(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  return (
    <div>
      <Breadcrumb />
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">总览</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            总组合 · v1.1配置
            {summary?.trade_date && (
              <span className="ml-2 text-slate-500">
                {summary.trade_date}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {useMock && (
            <span className="px-2 py-0.5 text-xs rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">
              MOCK
            </span>
          )}
          <Button variant="secondary" size="sm" onClick={() => void loadData()}>
            {loading ? "加载中..." : "刷新"}
          </Button>
          <Button variant="secondary" size="sm">运行回测</Button>
          <Button variant="secondary" size="sm">因子体检</Button>
        </div>
      </div>

      {/* KPI row */}
      <PortfolioKPIRow summary={summary} loading={loading} />

      {/* Sub-market links */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-5">
        <Link to="/dashboard/astock">
          <GlassCard variant="clickable" className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-200">A股策略 v1.1</p>
              <p className="text-xs text-slate-400 mt-0.5">
                Top-15 月度调仓 · PT Day 3/60
              </p>
            </div>
            <span className="text-slate-400 text-lg">→</span>
          </GlassCard>
        </Link>
        <Link to="/dashboard/forex">
          <GlassCard variant="clickable" className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-400">外汇策略</p>
              <p className="text-xs text-slate-500 mt-0.5">Phase 2 · 未启动</p>
            </div>
            <span className="text-slate-600 text-lg">→</span>
          </GlassCard>
        </Link>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
        <div className="lg:col-span-1">
          <MarketSnapshot />
        </div>
        <div className="lg:col-span-1">
          <SectorPieChart positions={positions} />
        </div>
        <div className="lg:col-span-1">
          <MonthlyHeatmap navSeries={navSeries} />
        </div>
      </div>
    </div>
  );
}
