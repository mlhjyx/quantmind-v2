import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { FactorReport } from "@/api/factors";

interface Props {
  report: FactorReport;
}

const FREQ_MAP: Record<string, string> = {
  "日度": "1-3日IC下降到50%以内",
  "周度": "5-10日IC下降到50%以内",
  "月度": "10-20日IC下降到50%以内",
};

export default function TabICDecay({ report }: Props) {
  const decayOption = useMemo(() => {
    const lags = report.ic_decay.map((d) => d.lag);
    const ics = report.ic_decay.map((d) => d.ic);
    const halfIc = report.ic_mean * 0.5;

    // Find half-life point
    const halfIdx = ics.findIndex((v) => Math.abs(v) <= Math.abs(halfIc));

    const markLines = halfIdx >= 0 ? {
      data: [
        {
          xAxis: lags[halfIdx],
          lineStyle: { color: "#f59e0b", type: "dashed" as const, width: 1.5 },
          label: { formatter: `半衰期 ~${lags[halfIdx]}日`, color: "#f59e0b", fontSize: 10 },
        },
      ],
    } : undefined;

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
        formatter: (params: Array<{ name: number; value: number }>) => {
          const p = params[0];
          if (!p) return "";
          return `滞后 ${p.name} 日<br/>IC: ${Number(p.value).toFixed(4)}`;
        },
      },
      grid: { top: 28, bottom: 32, left: 50, right: 16 },
      xAxis: {
        type: "category" as const,
        name: "滞后天数",
        nameTextStyle: { color: "#64748b", fontSize: 9 },
        data: lags,
        axisLabel: { color: "#475569", fontSize: 9 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "value" as const,
        name: "IC",
        nameTextStyle: { color: "#64748b", fontSize: 9 },
        axisLabel: { color: "#64748b", fontSize: 9, formatter: (v: number) => v.toFixed(3) },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [
        {
          name: "IC衰减",
          type: "line" as const,
          data: ics,
          smooth: false,
          symbol: "circle",
          symbolSize: 5,
          lineStyle: { color: "#38bdf8", width: 2 },
          itemStyle: { color: "#38bdf8" },
          areaStyle: { color: "rgba(56,189,248,0.1)" },
          markLine: markLines,
        },
      ],
    };
  }, [report]);

  const halfLife = report.half_life_days;
  const freq = report.recommended_freq;

  return (
    <div className="space-y-4">
      {/* Key metrics */}
      <div className="grid grid-cols-3 gap-3">
        <GlassCard padding="sm">
          <p className="text-xs text-slate-400 mb-1">IC半衰期</p>
          <p className="text-2xl font-bold text-amber-400 tabular-nums">{halfLife} 日</p>
        </GlassCard>
        <GlassCard padding="sm">
          <p className="text-xs text-slate-400 mb-1">FactorClassifier推荐频率</p>
          <p className="text-xl font-bold text-blue-400">{freq}</p>
        </GlassCard>
        <GlassCard padding="sm">
          <p className="text-xs text-slate-400 mb-1">衰减特征</p>
          <p className="text-xs text-slate-300 mt-1 leading-relaxed">
            {FREQ_MAP[freq] ?? "根据IC衰减曲线推断"}
          </p>
        </GlassCard>
      </div>

      {/* Decay chart */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-2">IC衰减曲线（1-20日滞后）</p>
        <ReactECharts option={decayOption} style={{ height: 220 }} opts={{ renderer: "canvas" }} />
      </GlassCard>

      {/* Interpretation */}
      <GlassCard padding="sm">
        <p className="text-xs font-medium text-slate-400 mb-2">衰减解读</p>
        <div className="grid grid-cols-3 gap-3 text-xs text-slate-300">
          {report.ic_decay.filter((_, i) => [0, 4, 9].includes(i)).map((d) => (
            <div key={d.lag} className="text-center">
              <div className="text-lg font-bold text-blue-400">{d.ic.toFixed(4)}</div>
              <div className="text-slate-400">滞后{d.lag}日IC</div>
              <div className="text-slate-500">
                保留 {((Math.abs(d.ic) / Math.abs(report.ic_mean)) * 100).toFixed(0)}%
              </div>
            </div>
          ))}
        </div>
      </GlassCard>
    </div>
  );
}
