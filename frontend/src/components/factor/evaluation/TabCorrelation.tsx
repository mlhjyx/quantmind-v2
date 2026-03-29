import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { FactorReport } from "@/api/factors";

interface Props {
  report: FactorReport;
}

export default function TabCorrelation({ report }: Props) {
  const corrBarOption = useMemo(() => {
    const sorted = [...(report.correlations ?? [])].sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr));
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
      },
      grid: { top: 12, bottom: 28, left: 120, right: 40 },
      xAxis: {
        type: "value" as const,
        min: -1,
        max: 1,
        axisLabel: { color: "#64748b", fontSize: 9 },
        splitLine: { lineStyle: { color: "#1e293b" } },
        axisLine: { lineStyle: { color: "#334155" } },
      },
      yAxis: {
        type: "category" as const,
        data: sorted.map((c) => c.name),
        axisLabel: { color: "#94a3b8", fontSize: 9 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [{
        type: "bar" as const,
        data: sorted.map((c) => ({
          value: c.corr,
          itemStyle: {
            color: Math.abs(c.corr) > 0.7
              ? "#ef4444"
              : Math.abs(c.corr) > 0.4
              ? "#f59e0b"
              : "#38bdf8",
          },
        })),
        barMaxWidth: 20,
        label: {
          show: true,
          position: (p: { value: number }) => (p.value >= 0 ? "right" : "left"),
          formatter: (p: { value: number }) => p.value.toFixed(3),
          color: "#94a3b8",
          fontSize: 9,
        },
      }],
    };
  }, [report]);

  const industryHeatOption = useMemo(() => {
    const sorted = [...(report.industry_ic ?? [])].sort((a, b) => b.ic - a.ic);
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
      },
      grid: { top: 12, bottom: 28, left: 80, right: 40 },
      xAxis: {
        type: "value" as const,
        axisLabel: { color: "#64748b", fontSize: 9 },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "category" as const,
        data: sorted.map((d) => d.industry),
        axisLabel: { color: "#94a3b8", fontSize: 9 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [{
        type: "bar" as const,
        data: sorted.map((d) => ({
          value: d.ic,
          itemStyle: {
            color: d.ic >= 0.04 ? "#22c55e" : d.ic >= 0.02 ? "#38bdf8" : d.ic >= 0 ? "#64748b" : "#ef4444",
          },
        })),
        barMaxWidth: 16,
        label: {
          show: true,
          position: "right" as const,
          formatter: (p: { value: number }) => p.value.toFixed(4),
          color: "#94a3b8",
          fontSize: 9,
        },
      }],
    };
  }, [report]);

  const correlations = report.correlations ?? [];
  const industryIc = report.industry_ic ?? [];
  const highCorrCount = correlations.filter((c) => Math.abs(c.corr) > 0.7).length;

  if (correlations.length === 0 && industryIc.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500 text-sm">
        暂无相关性数据
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {highCorrCount > 0 && (
        <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-400">
          ⚠️ 与 {highCorrCount} 个Active因子相关系数 &gt; 0.7，建议执行相关性裁剪
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        <GlassCard>
          <p className="text-xs font-medium text-slate-400 mb-2">与Active因子相关性</p>
          <ReactECharts
            option={corrBarOption}
            style={{ height: Math.max(140, correlations.length * 28 + 60) }}
            opts={{ renderer: "canvas" }}
          />
          <div className="flex gap-3 mt-2 text-xs text-slate-500">
            <span><span className="text-red-400">■</span> &gt;0.7 高相关</span>
            <span><span className="text-yellow-400">■</span> 0.4-0.7 中相关</span>
            <span><span className="text-blue-400">■</span> &lt;0.4 低相关</span>
          </div>
        </GlassCard>

        <GlassCard>
          <p className="text-xs font-medium text-slate-400 mb-2">行业IC分布</p>
          <ReactECharts
            option={industryHeatOption}
            style={{ height: Math.max(140, industryIc.length * 22 + 60) }}
            opts={{ renderer: "canvas" }}
          />
        </GlassCard>
      </div>
    </div>
  );
}
