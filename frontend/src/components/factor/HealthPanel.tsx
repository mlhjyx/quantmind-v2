import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { FactorICTrend, FactorLibraryStats } from "@/api/factors";
import { GlassCard } from "@/components/ui/GlassCard";

interface Props {
  stats: FactorLibraryStats;
  icTrends: FactorICTrend[];
  loading?: boolean;
}

const STATUS_COLORS = {
  active:   "#22c55e",
  new:      "#38bdf8",
  degraded: "#f59e0b",
  retired:  "#ef4444",
};

const STATUS_LABELS = {
  active:   "活跃",
  new:      "新入库",
  degraded: "衰退",
  retired:  "淘汰",
};

export default function HealthPanel({ stats, icTrends, loading }: Props) {
  const pieData = [
    { name: STATUS_LABELS.active,   value: stats.active,   itemStyle: { color: STATUS_COLORS.active } },
    { name: STATUS_LABELS.new,      value: stats.new,      itemStyle: { color: STATUS_COLORS.new } },
    { name: STATUS_LABELS.degraded, value: stats.degraded, itemStyle: { color: STATUS_COLORS.degraded } },
    { name: STATUS_LABELS.retired,  value: stats.retired,  itemStyle: { color: STATUS_COLORS.retired } },
  ].filter((d) => d.value > 0);

  const pieOption = useMemo(() => ({
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item" as const,
      backgroundColor: "rgba(15,23,42,0.9)",
      borderColor: "rgba(255,255,255,0.1)",
      textStyle: { color: "#e2e8f0", fontSize: 11 },
      formatter: "{b}: {c} ({d}%)",
    },
    series: [{
      type: "pie" as const,
      radius: ["40%", "65%"],
      center: ["50%", "50%"],
      data: pieData,
      label: { show: false },
      emphasis: { label: { show: false } },
    }],
  }), [pieData]);

  const icTrendOption = useMemo(() => {
    if (!icTrends.length) return {};
    const dates = icTrends[0]?.dates ?? [];
    const series = icTrends.map((t) => ({
      name: t.factor_name,
      type: "line" as const,
      data: t.ic_values,
      smooth: true,
      symbol: "none",
      lineStyle: { width: 1.5 },
    }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
      },
      legend: {
        data: icTrends.map((t) => t.factor_name),
        textStyle: { color: "#94a3b8", fontSize: 10 },
        top: 4,
        right: 4,
        type: "scroll" as const,
      },
      grid: { top: 36, bottom: 24, left: 44, right: 8 },
      xAxis: {
        type: "category" as const,
        data: dates,
        axisLabel: { color: "#475569", fontSize: 9 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: { color: "#475569", fontSize: 9, formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series,
    };
  }, [icTrends]);

  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-4">
        {[0, 1].map((i) => (
          <GlassCard key={i} className="h-40 animate-pulse bg-slate-800/40">{null}</GlassCard>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {/* Donut chart — factor status distribution */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-3">因子状态分布</p>
        <ReactECharts option={pieOption} style={{ height: 160 }} opts={{ renderer: "canvas" }} />
        <div className="grid grid-cols-2 gap-1 mt-1">
          {pieData.map((d) => (
            <div key={d.name} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full shrink-0" style={{ background: d.itemStyle.color }} />
              <span className="text-xs text-slate-400">{d.name}: {d.value}</span>
            </div>
          ))}
        </div>
      </GlassCard>

      {/* IC trend chart — span 2 cols */}
      <GlassCard className="lg:col-span-2">
        <p className="text-xs font-medium text-slate-400 mb-2">Active因子IC趋势（月度）</p>
        {icTrends.length > 0 ? (
          <ReactECharts option={icTrendOption} style={{ height: 180 }} opts={{ renderer: "canvas" }} />
        ) : (
          <div className="h-[180px] flex items-center justify-center text-slate-500 text-xs">
            暂无IC趋势数据
          </div>
        )}
        {icTrends.some((t) => {
          const recent = t.ic_values.slice(-3);
          const avg = recent.reduce((a, b) => a + b, 0) / (recent.length || 1);
          return avg < 0.02;
        }) && (
          <div className="mt-2 px-3 py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-xs text-yellow-400">
            ⚠️ 部分因子近期IC低于0.02，建议执行因子体检
          </div>
        )}
      </GlassCard>
    </div>
  );
}
