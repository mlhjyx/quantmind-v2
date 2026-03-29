import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ReactECharts from "echarts-for-react";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { getBacktestResult, type BacktestResult, type NavPoint, type MonthlyReturn } from "@/api/backtest";
import { EmptyState } from "@/components/ui/EmptyState";
import { STALE } from "@/api/QueryProvider";

// ---- Shared helpers ----

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function fmtNum(v: number | null | undefined, digits = 3): string {
  if (v == null) return "—";
  return v.toFixed(digits);
}

function metricColor(label: string, value: number | null | undefined): string {
  if (value == null) return "text-slate-300";
  const thresholds: Record<string, { green: number; red: number; higher: boolean }> = {
    sharpe:         { green: 1.0, red: 0.5,  higher: true },
    annual_return:  { green: 0.15, red: 0.0, higher: true },
    mdd:            { green: -0.15, red: -0.35, higher: true },
    calmar:         { green: 0.5, red: 0.2,  higher: true },
    dsr:            { green: 0.8, red: 0.4,  higher: true },
  };
  const cfg = thresholds[label];
  if (!cfg) return "text-slate-300";
  if (cfg.higher) {
    if (value >= cfg.green) return "text-green-400";
    if (value <= cfg.red) return "text-red-400";
    return "text-yellow-400";
  } else {
    if (value <= cfg.green) return "text-green-400";
    if (value >= cfg.red) return "text-red-400";
    return "text-yellow-400";
  }
}

// ---- Tab: NAV Curve ----

function TabNavCurve({ nav }: { nav: NavPoint[] }) {
  if (!nav || nav.length === 0) {
    return <EmptyState title="净值曲线数据不可用" />;
  }

  const option = {
    backgroundColor: "transparent",
    legend: {
      data: ["策略", "基准", "超额"],
      textStyle: { color: "#94a3b8", fontSize: 12 },
      top: 0,
    },
    grid: { left: 60, right: 20, top: 40, bottom: 60 },
    xAxis: {
      type: "category",
      data: nav.map((d) => d.date),
      axisLine: { lineStyle: { color: "#334155" } },
      axisLabel: { color: "#94a3b8", fontSize: 11, rotate: 30 },
    },
    yAxis: [
      {
        type: "value",
        name: "净值",
        axisLine: { lineStyle: { color: "#334155" } },
        splitLine: { lineStyle: { color: "#1e293b" } },
        axisLabel: { color: "#94a3b8", fontSize: 11 },
      },
      {
        type: "value",
        name: "回撤",
        min: -1,
        max: 0,
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#94a3b8", fontSize: 11, formatter: (v: number) => fmtPct(v, 0) },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "策略",
        type: "line",
        data: nav.map((d) => d.strategy),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#60a5fa", width: 2 },
      },
      {
        name: "基准",
        type: "line",
        data: nav.map((d) => d.benchmark),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#94a3b8", width: 1.5, type: "dashed" },
      },
      {
        name: "超额",
        type: "line",
        data: nav.map((d) => d.excess),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#34d399", width: 1.5 },
      },
      {
        name: "回撤",
        type: "line",
        yAxisIndex: 1,
        data: nav.map((d) => d.drawdown),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: "#f87171", width: 1 },
        areaStyle: { color: "rgba(248,113,113,0.15)" },
      },
    ],
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "#334155",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0 },
      { type: "slider", xAxisIndex: 0, bottom: 10, height: 20, borderColor: "#334155", fillerColor: "rgba(96,165,250,0.15)", textStyle: { color: "#94a3b8" } },
    ],
  };

  return (
    <ReactECharts option={option} style={{ height: 420, width: "100%" }} notMerge lazyUpdate />
  );
}

// ---- Tab: Monthly Attribution ----

function TabMonthlyAttribution({ monthly }: { monthly: MonthlyReturn[] }) {
  if (!monthly || monthly.length === 0) return <EmptyState title="月度归因数据不可用" />;

  const years = [...new Set(monthly.map((d) => d.year))].sort();
  const months = [1,2,3,4,5,6,7,8,9,10,11,12];

  // Build heatmap matrix: [yearIdx, monthIdx, value]
  const data: [number, number, number][] = [];
  monthly.forEach((d) => {
    const yi = years.indexOf(d.year);
    const mi = d.month - 1;
    data.push([mi, yi, d.return]);
  });

  const option = {
    backgroundColor: "transparent",
    grid: { left: 60, right: 20, top: 40, bottom: 20 },
    xAxis: {
      type: "category",
      data: months.map((m) => `${m}月`),
      axisLine: { lineStyle: { color: "#334155" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
      splitArea: { show: true, areaStyle: { color: ["rgba(255,255,255,0.02)", "rgba(255,255,255,0)"] } },
    },
    yAxis: {
      type: "category",
      data: years.map(String),
      axisLine: { lineStyle: { color: "#334155" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
      splitArea: { show: true, areaStyle: { color: ["rgba(255,255,255,0.02)", "rgba(255,255,255,0)"] } },
    },
    visualMap: {
      min: -0.15,
      max: 0.15,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 5,
      textStyle: { color: "#94a3b8", fontSize: 10 },
      inRange: { color: ["#ef4444", "#1e293b", "#22c55e"] },
    },
    series: [{
      type: "heatmap",
      data,
      label: {
        show: true,
        formatter: (params: { value: [number, number, number] }) =>
          `${(params.value[2] * 100).toFixed(1)}%`,
        fontSize: 10,
        color: "#e2e8f0",
      },
    }],
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "#334155",
      formatter: (params: { value: [number, number, number] }) =>
        `${years[params.value[1]]}年 ${params.value[0]+1}月<br/>收益率: ${fmtPct(params.value[2])}`,
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
  };

  return <ReactECharts option={option} style={{ height: 420, width: "100%" }} notMerge lazyUpdate />;
}

// ---- Tab: Holdings ----

function TabHoldings({ holdings }: { holdings: BacktestResult["holdings"] }) {
  if (!holdings || holdings.length === 0) return <EmptyState title="持仓数据不可用" />;

  // Industry distribution
  const industryMap: Record<string, number> = {};
  holdings.forEach((h) => {
    industryMap[h.industry] = (industryMap[h.industry] ?? 0) + h.weight;
  });
  const pieData = Object.entries(industryMap)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({ name, value: parseFloat((value * 100).toFixed(2)) }));

  const pieOption = {
    backgroundColor: "transparent",
    tooltip: { trigger: "item", formatter: "{b}: {c}%", backgroundColor: "rgba(15,20,45,0.9)", borderColor: "#334155", textStyle: { color: "#e2e8f0" } },
    legend: { orient: "vertical", right: 10, top: "center", textStyle: { color: "#94a3b8", fontSize: 11 } },
    series: [{
      type: "pie",
      radius: ["40%", "70%"],
      center: ["35%", "50%"],
      data: pieData,
      label: { show: false },
      itemStyle: { borderRadius: 4, borderColor: "rgba(15,20,45,0.8)", borderWidth: 2 },
    }],
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <GlassCard>
          <p className="text-sm font-medium text-slate-300 mb-2">行业分布</p>
          <ReactECharts option={pieOption} style={{ height: 280 }} notMerge lazyUpdate />
        </GlassCard>
        <GlassCard>
          <p className="text-sm font-medium text-slate-300 mb-2">个股权重 Top 20</p>
          <div className="overflow-y-auto h-64 space-y-1.5 pr-1">
            {holdings.slice(0, 20).map((h) => (
              <div key={h.symbol} className="flex items-center gap-2 text-xs">
                <span className="text-slate-400 w-16 shrink-0">{h.symbol}</span>
                <span className="text-slate-300 w-20 shrink-0 truncate">{h.name}</span>
                <div className="flex-1 h-1.5 bg-slate-700/60 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 rounded-full"
                    style={{ width: `${Math.min(h.weight * 100 * 5, 100)}%` }}
                  />
                </div>
                <span className="text-slate-300 w-10 text-right shrink-0">{fmtPct(h.weight)}</span>
              </div>
            ))}
          </div>
        </GlassCard>
      </div>
    </div>
  );
}

// ---- Tab: Trades ----

type SortKey = "date" | "symbol" | "pnl" | "amount";

function TabTrades({ trades }: { trades: BacktestResult["trades"] }) {
  const [filter, setFilter] = useState<"all" | "buy" | "sell">("all");
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [sortAsc, setSortAsc] = useState(false);
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  if (!trades || trades.length === 0) return <EmptyState title="交易明细不可用" />;

  const filtered = trades.filter((t) => filter === "all" || t.direction === filter);
  const sorted = [...filtered].sort((a, b) => {
    let av: string | number, bv: string | number;
    if (sortKey === "date") { av = a.date; bv = b.date; }
    else if (sortKey === "symbol") { av = a.symbol; bv = b.symbol; }
    else if (sortKey === "pnl") { av = a.pnl ?? -Infinity; bv = b.pnl ?? -Infinity; }
    else { av = a.amount; bv = b.amount; }
    if (av < bv) return sortAsc ? -1 : 1;
    if (av > bv) return sortAsc ? 1 : -1;
    return 0;
  });

  const pageData = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
    setPage(0);
  };

  const SortIcon = ({ k }: { k: SortKey }) =>
    sortKey === k ? <span className="ml-0.5">{sortAsc ? "↑" : "↓"}</span> : null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        {(["all", "buy", "sell"] as const).map((f) => (
          <button
            key={f}
            onClick={() => { setFilter(f); setPage(0); }}
            className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
              filter === f
                ? "bg-blue-600 text-white"
                : "bg-slate-700/60 text-slate-400 hover:text-slate-200"
            }`}
          >
            {f === "all" ? "全部" : f === "buy" ? "买入" : "卖出"}
          </button>
        ))}
        <span className="text-xs text-slate-500 ml-auto">{sorted.length} 笔交易</span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            const csv = [
              ["日期","代码","名称","方向","价格","数量","金额","手续费","滑点","盈亏"].join(","),
              ...trades.map((t) =>
                [t.date,t.symbol,t.name,t.direction,t.price,t.quantity,t.amount,t.commission,t.slippage,t.pnl ?? ""].join(",")
              ),
            ].join("\n");
            const blob = new Blob([csv], { type: "text/csv" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "trades.csv";
            a.click();
          }}
        >
          导出CSV
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs text-slate-300">
          <thead>
            <tr className="border-b border-slate-700/60">
              {(["日期","代码","名称","方向","价格","数量","金额","手续费","盈亏"] as const).map((label, i) => {
                const keyMap: Record<string, SortKey | null> = {
                  "日期": "date", "代码": "symbol", "金额": "amount", "盈亏": "pnl",
                };
                const k = keyMap[label];
                return (
                  <th
                    key={i}
                    className={`py-2 px-2 text-left text-slate-400 font-medium ${k ? "cursor-pointer hover:text-slate-200" : ""}`}
                    onClick={() => k && toggleSort(k)}
                  >
                    {label}{k && <SortIcon k={k} />}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {pageData.map((t, i) => (
              <tr key={i} className="border-b border-slate-700/30 hover:bg-white/5 transition-colors">
                <td className="py-1.5 px-2">{t.date}</td>
                <td className="py-1.5 px-2 text-blue-400">{t.symbol}</td>
                <td className="py-1.5 px-2">{t.name}</td>
                <td className={`py-1.5 px-2 font-medium ${t.direction === "buy" ? "text-red-400" : "text-green-400"}`}>
                  {t.direction === "buy" ? "买入" : "卖出"}
                </td>
                <td className="py-1.5 px-2">{t.price.toFixed(2)}</td>
                <td className="py-1.5 px-2">{t.quantity}</td>
                <td className="py-1.5 px-2">{t.amount.toFixed(0)}</td>
                <td className="py-1.5 px-2 text-slate-500">{t.commission.toFixed(2)}</td>
                <td className={`py-1.5 px-2 font-medium ${(t.pnl ?? 0) >= 0 ? "text-red-400" : "text-green-400"}`}>
                  {t.pnl != null ? t.pnl.toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)}>上一页</Button>
          <span className="text-xs text-slate-400">{page + 1} / {totalPages}</span>
          <Button variant="ghost" size="sm" disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}>下一页</Button>
        </div>
      )}
    </div>
  );
}

// ---- Tab: Risk Metrics ----

function TabRisk({ riskMetrics }: { riskMetrics: BacktestResult["risk_metrics"] }) {
  if (!riskMetrics || riskMetrics.length === 0) return <EmptyState title="风险指标数据不可用" />;

  const option = {
    backgroundColor: "transparent",
    grid: { left: 120, right: 40, top: 20, bottom: 20 },
    xAxis: { type: "value", axisLabel: { color: "#94a3b8", fontSize: 11 }, splitLine: { lineStyle: { color: "#1e293b" } }, axisLine: { lineStyle: { color: "#334155" } } },
    yAxis: {
      type: "category",
      data: riskMetrics.map((r) => r.label),
      axisLabel: { color: "#94a3b8", fontSize: 11 },
      axisLine: { lineStyle: { color: "#334155" } },
    },
    series: [{
      type: "bar",
      data: riskMetrics.map((r) => r.value),
      itemStyle: { color: "#60a5fa", borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: "#94a3b8", fontSize: 11, formatter: (p: { value: number }) => p.value.toFixed(3) },
    }],
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(15,20,45,0.9)",
      borderColor: "#334155",
      textStyle: { color: "#e2e8f0", fontSize: 12 },
    },
  };

  return (
    <div className="space-y-4">
      <ReactECharts option={option} style={{ height: 320, width: "100%" }} notMerge lazyUpdate />
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {riskMetrics.map((r) => (
          <GlassCard key={r.label} padding="sm">
            <p className="text-xs text-slate-400 mb-1">{r.label}</p>
            <p className="text-lg font-bold text-white">{r.value.toFixed(3)}<span className="text-xs text-slate-500 ml-1">{r.unit}</span></p>
          </GlassCard>
        ))}
      </div>
    </div>
  );
}

// ---- Tab: Factor Contributions ----

function TabFactorContributions({ contributions }: { contributions: BacktestResult["factor_contributions"] }) {
  if (!contributions || contributions.length === 0) return <EmptyState title="因子贡献数据不可用" />;

  const option = {
    backgroundColor: "transparent",
    legend: { data: ["IC值", "权重", "贡献度"], textStyle: { color: "#94a3b8", fontSize: 11 }, top: 0 },
    grid: { left: 100, right: 20, top: 40, bottom: 20 },
    xAxis: { type: "value", axisLabel: { color: "#94a3b8", fontSize: 11 }, splitLine: { lineStyle: { color: "#1e293b" } }, axisLine: { lineStyle: { color: "#334155" } } },
    yAxis: {
      type: "category",
      data: contributions.map((c) => c.factor_name),
      axisLabel: { color: "#94a3b8", fontSize: 11 },
      axisLine: { lineStyle: { color: "#334155" } },
    },
    series: [
      { name: "IC值", type: "bar", data: contributions.map((c) => c.ic), itemStyle: { color: "#60a5fa" }, barWidth: 8 },
      { name: "贡献度", type: "bar", data: contributions.map((c) => c.contribution), itemStyle: { color: "#34d399" }, barWidth: 8 },
    ],
    tooltip: { trigger: "axis", backgroundColor: "rgba(15,20,45,0.9)", borderColor: "#334155", textStyle: { color: "#e2e8f0", fontSize: 12 } },
  };

  return (
    <div className="space-y-4">
      <ReactECharts option={option} style={{ height: 300, width: "100%" }} notMerge lazyUpdate />
      <div className="overflow-x-auto">
        <table className="w-full text-xs text-slate-300">
          <thead>
            <tr className="border-b border-slate-700/60">
              <th className="py-2 px-3 text-left text-slate-400 font-medium">因子名称</th>
              <th className="py-2 px-3 text-right text-slate-400 font-medium">IC</th>
              <th className="py-2 px-3 text-right text-slate-400 font-medium">权重</th>
              <th className="py-2 px-3 text-right text-slate-400 font-medium">贡献度</th>
            </tr>
          </thead>
          <tbody>
            {contributions.map((c, i) => (
              <tr key={i} className="border-b border-slate-700/30 hover:bg-white/5">
                <td className="py-1.5 px-3 font-medium text-blue-300">{c.factor_name}</td>
                <td className={`py-1.5 px-3 text-right ${c.ic > 0 ? "text-green-400" : "text-red-400"}`}>{c.ic.toFixed(4)}</td>
                <td className="py-1.5 px-3 text-right">{fmtPct(c.weight)}</td>
                <td className={`py-1.5 px-3 text-right font-medium ${c.contribution > 0 ? "text-green-400" : "text-red-400"}`}>{fmtPct(c.contribution)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---- Tab: WF Analysis ----

function TabWFAnalysis({ windows }: { windows: BacktestResult["wf_windows"] }) {
  if (!windows || windows.length === 0) return <EmptyState title="Walk-Forward分析数据不可用（未启用WF模式）" />;

  const option = {
    backgroundColor: "transparent",
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: "category",
      data: windows.map((w) => `W${w.window_id}`),
      axisLine: { lineStyle: { color: "#334155" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: "#334155" } },
      splitLine: { lineStyle: { color: "#1e293b" } },
      axisLabel: { color: "#94a3b8", fontSize: 11 },
    },
    series: [
      {
        name: "OOS Sharpe",
        type: "bar",
        data: windows.map((w) => w.oos_sharpe),
        itemStyle: { color: (p: { value: number }) => p.value >= 0.72 ? "#22c55e" : p.value >= 0.3 ? "#eab308" : "#ef4444", borderRadius: [4, 4, 0, 0] },
        label: { show: true, position: "top", color: "#94a3b8", fontSize: 10, formatter: (p: { value: number }) => p.value.toFixed(2) },
      },
    ],
    tooltip: { trigger: "axis", backgroundColor: "rgba(15,20,45,0.9)", borderColor: "#334155", textStyle: { color: "#e2e8f0", fontSize: 12 } },
    markLine: { data: [{ yAxis: 0.72, lineStyle: { color: "#22c55e", type: "dashed" }, label: { formatter: "毕业线 0.72", color: "#22c55e" } }] },
  };

  const avgOOS = windows.reduce((s, w) => s + w.oos_sharpe, 0) / windows.length;
  const stableCount = windows.filter((w) => w.oos_sharpe >= 0.72).length;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <GlassCard padding="sm">
          <p className="text-xs text-slate-400 mb-1">平均OOS Sharpe</p>
          <p className={`text-xl font-bold ${avgOOS >= 0.72 ? "text-green-400" : "text-yellow-400"}`}>{avgOOS.toFixed(3)}</p>
        </GlassCard>
        <GlassCard padding="sm">
          <p className="text-xs text-slate-400 mb-1">达标窗口</p>
          <p className="text-xl font-bold text-white">{stableCount} / {windows.length}</p>
        </GlassCard>
        <GlassCard padding="sm">
          <p className="text-xs text-slate-400 mb-1">过拟合风险</p>
          <p className={`text-xl font-bold ${stableCount / windows.length >= 0.6 ? "text-green-400" : "text-red-400"}`}>
            {stableCount / windows.length >= 0.6 ? "低" : stableCount / windows.length >= 0.4 ? "中" : "高"}
          </p>
        </GlassCard>
      </div>
      <ReactECharts option={option} style={{ height: 300, width: "100%" }} notMerge lazyUpdate />
    </div>
  );
}

// ---- Tab: Compare Mode ----

function TabCompare({ currentRunId }: { currentRunId: string }) {
  const [compareRunId, setCompareRunId] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const { data: compareResult } = useQuery({
    queryKey: ["backtest-result", compareRunId],
    queryFn: () => getBacktestResult(compareRunId),
    enabled: submitted && !!compareRunId,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <label className="text-xs text-slate-400 block mb-1">输入对比回测 Run ID</label>
          <input
            type="text"
            value={compareRunId}
            onChange={(e) => { setCompareRunId(e.target.value); setSubmitted(false); }}
            placeholder="例: bt_20260101_abc123"
            className="w-full bg-slate-700/50 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
        </div>
        <Button size="sm" className="mt-4" onClick={() => setSubmitted(true)} disabled={!compareRunId}>
          加载对比
        </Button>
      </div>

      {submitted && compareResult && (
        <div className="grid grid-cols-2 gap-4">
          {[
            { label: "当前回测", runId: currentRunId },
            { label: "对比回测", runId: compareRunId },
          ].map((side, i) => {
            const result = i === 1 ? compareResult : null;
            return (
              <GlassCard key={side.runId}>
                <p className="text-xs text-slate-400 mb-1">{side.label}</p>
                <p className="text-sm font-medium text-white mb-3">{side.runId}</p>
                {result && (
                  <div className="space-y-2">
                    {[
                      { label: "年化收益", value: fmtPct(result.metrics.annual_return) },
                      { label: "Sharpe", value: fmtNum(result.metrics.sharpe) },
                      { label: "MDD", value: fmtPct(result.metrics.mdd) },
                      { label: "Calmar", value: fmtNum(result.metrics.calmar) },
                    ].map((m) => (
                      <div key={m.label} className="flex justify-between text-xs">
                        <span className="text-slate-400">{m.label}</span>
                        <span className="text-white font-medium">{m.value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </GlassCard>
            );
          })}
        </div>
      )}
    </div>
  );
}

// EmptyState is imported from @/components/ui/EmptyState

// ---- Top Metric Cards ----

const METRICS_CONFIG = [
  { key: "annual_return" as const, label: "年化收益", fmt: (v: number) => fmtPct(v), thresholdKey: "annual_return" },
  { key: "sharpe" as const, label: "Sharpe", fmt: (v: number) => fmtNum(v, 3), thresholdKey: "sharpe" },
  { key: "dsr" as const, label: "DSR", fmt: (v: number) => fmtNum(v, 3), thresholdKey: "dsr" },
  { key: "mdd" as const, label: "MDD", fmt: (v: number) => fmtPct(v), thresholdKey: "mdd" },
  { key: "calmar" as const, label: "Calmar", fmt: (v: number) => fmtNum(v, 2), thresholdKey: "calmar" },
  { key: "annual_turnover" as const, label: "年换手率", fmt: (v: number) => fmtPct(v, 0), thresholdKey: null },
  { key: "net_return_after_cost" as const, label: "扣费收益", fmt: (v: number) => fmtPct(v), thresholdKey: "annual_return" },
  { key: "wf_oos_sharpe" as const, label: "WF-OOS Sharpe", fmt: (v: number | null) => v != null ? fmtNum(v, 3) : "—", thresholdKey: "sharpe" },
];

// ---- Tabs definition ----

const TABS = [
  { key: "nav", label: "净值曲线" },
  { key: "monthly", label: "月度归因" },
  { key: "holdings", label: "持仓分析" },
  { key: "trades", label: "交易明细" },
  { key: "wf", label: "WF分析" },
  { key: "risk", label: "风险指标" },
  { key: "factors", label: "因子贡献" },
  { key: "compare", label: "对比模式" },
];

// ---- Main Page ----

export default function BacktestResults() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("nav");

  const { data: result, isLoading, error } = useQuery({
    queryKey: ["backtest-result", runId],
    queryFn: () => getBacktestResult(runId!),
    enabled: !!runId,
    retry: 2,
    staleTime: STALE.factor,
  });

  return (
    <div>
      <Breadcrumb
        items={[
          { label: "回测分析", path: "/backtest/config" },
          { label: `运行 #${runId ?? "…"}`, path: `/backtest/${runId}` },
          { label: "结果分析" },
        ]}
      />

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">回测结果分析</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {result ? `${result.strategy_name} · 完成于 ${result.completed_at?.slice(0, 10) ?? "—"}` : `Run ID: ${runId ?? "—"}`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm" onClick={() => navigate("/backtest/config")}>修改重跑</Button>
          <Button variant="secondary" size="sm">复制策略</Button>
          <Button variant="secondary" size="sm">导出PDF</Button>
          <Button size="sm" onClick={() => navigate("/dashboard")}>部署到模拟盘</Button>
        </div>
      </div>

      {isLoading && (
        <GlassCard className="flex items-center justify-center py-16">
          <div className="flex items-center gap-3 text-slate-400">
            <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span>加载回测结果...</span>
          </div>
        </GlassCard>
      )}

      {error && (
        <GlassCard className="flex items-center justify-center py-16 text-red-400 text-sm">
          加载失败: {error instanceof Error ? error.message : "未知错误"}
        </GlassCard>
      )}

      {result && (
        <>
          {/* Top metric cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 mb-5">
            {METRICS_CONFIG.map((m) => {
              const raw = result.metrics[m.key];
              const value = typeof raw === "number" ? raw : null;
              const color = m.thresholdKey ? metricColor(m.thresholdKey, value) : "text-slate-300";
              return (
                <GlassCard key={m.key} padding="sm" className="text-center">
                  <p className="text-[10px] text-slate-400 mb-1">{m.label}</p>
                  <p className={`text-base font-bold ${color}`}>{m.fmt(raw as number & null)}</p>
                </GlassCard>
              );
            })}
          </div>

          {/* Tabs */}
          <GlassCard>
            <div className="flex gap-1 mb-5 overflow-x-auto border-b border-slate-700/60 pb-0">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                    activeTab === tab.key
                      ? "text-white border-blue-500"
                      : "text-slate-400 border-transparent hover:text-slate-200"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="min-h-64">
              {activeTab === "nav" && <TabNavCurve nav={result.nav} />}
              {activeTab === "monthly" && <TabMonthlyAttribution monthly={result.monthly_returns} />}
              {activeTab === "holdings" && <TabHoldings holdings={result.holdings} />}
              {activeTab === "trades" && <TabTrades trades={result.trades} />}
              {activeTab === "wf" && <TabWFAnalysis windows={result.wf_windows} />}
              {activeTab === "risk" && <TabRisk riskMetrics={result.risk_metrics} />}
              {activeTab === "factors" && <TabFactorContributions contributions={result.factor_contributions} />}
              {activeTab === "compare" && <TabCompare currentRunId={runId!} />}
            </div>
          </GlassCard>
        </>
      )}
    </div>
  );
}
