import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { FactorCorrelationMatrix } from "@/api/factors";
import { GlassCard } from "@/components/ui/GlassCard";

interface Props {
  data: FactorCorrelationMatrix;
  loading?: boolean;
}

export default function CorrelationHeatmap({ data, loading }: Props) {
  const option = useMemo(() => {
    const { factors, matrix } = data;
    const heatData: [number, number, number][] = [];
    for (let i = 0; i < factors.length; i++) {
      for (let j = 0; j < factors.length; j++) {
        heatData.push([j, i, Number((matrix[i]?.[j] ?? 0).toFixed(3))]);
      }
    }

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
        formatter: (params: { value: [number, number, number] }) => {
          const [xi, yi, v] = params.value;
          return `${factors[yi] ?? ""} × ${factors[xi] ?? ""}<br/>相关系数: <b>${v.toFixed(3)}</b>`;
        },
      },
      grid: { top: 16, bottom: 60, left: 120, right: 16 },
      xAxis: {
        type: "category" as const,
        data: factors,
        splitArea: { show: true, areaStyle: { color: ["transparent"] } },
        axisLabel: { color: "#64748b", fontSize: 9, rotate: 30 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "category" as const,
        data: factors,
        splitArea: { show: true, areaStyle: { color: ["transparent"] } },
        axisLabel: { color: "#64748b", fontSize: 9 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: "horizontal" as const,
        left: "center",
        bottom: 0,
        textStyle: { color: "#64748b", fontSize: 9 },
        inRange: {
          color: ["#22c55e", "#f8fafc", "#ef4444"],
        },
        itemHeight: 100,
        itemWidth: 12,
      },
      series: [
        {
          name: "相关系数",
          type: "heatmap" as const,
          data: heatData,
          label: {
            show: true,
            fontSize: 9,
            color: "#1e293b",
            formatter: (params: { value: [number, number, number] }) =>
              params.value[2].toFixed(2),
          },
          emphasis: {
            itemStyle: { shadowBlur: 6, shadowColor: "rgba(0,0,0,0.5)" },
          },
        },
      ],
    };
  }, [data]);

  const highCorrPairs: { a: string; b: string; corr: number }[] = [];
  for (let i = 0; i < data.factors.length; i++) {
    for (let j = i + 1; j < data.factors.length; j++) {
      const c = data.matrix[i]?.[j] ?? 0;
      const fa = data.factors[i] ?? "";
      const fb = data.factors[j] ?? "";
      if (Math.abs(c) > 0.7) {
        highCorrPairs.push({ a: fa, b: fb, corr: c });
      }
    }
  }

  if (loading) {
    return <GlassCard className="h-64 animate-pulse bg-slate-800/40">{null}</GlassCard>;
  }

  return (
    <GlassCard>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-slate-400">因子相关性矩阵</p>
        {highCorrPairs.length > 0 && (
          <span className="text-xs text-yellow-400 bg-yellow-500/10 border border-yellow-500/20 px-2 py-0.5 rounded-full">
            ⚠️ {highCorrPairs.length} 对高相关 (&gt;0.7)
          </span>
        )}
      </div>

      <ReactECharts option={option} style={{ height: 280 }} opts={{ renderer: "canvas" }} />

      {highCorrPairs.length > 0 && (
        <div className="mt-3 space-y-1">
          {highCorrPairs.map((p) => (
            <div
              key={`${p.a}-${p.b}`}
              className="flex items-center justify-between px-3 py-1.5 rounded-lg bg-yellow-500/8 border border-yellow-500/15"
            >
              <span className="text-xs text-slate-300 font-mono">
                {p.a} × {p.b}
              </span>
              <span className="text-xs text-yellow-400 font-medium">{p.corr.toFixed(3)}</span>
            </div>
          ))}
        </div>
      )}
    </GlassCard>
  );
}
