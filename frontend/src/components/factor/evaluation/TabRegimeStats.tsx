import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { FactorReport } from "@/api/factors";

interface Props {
  report: FactorReport;
}

const REGIME_LABELS: Record<string, string> = {
  bull: "牛市",
  bear: "熊市",
  sideways: "震荡",
};

const REGIME_COLORS: Record<string, string> = {
  bull: "#22c55e",
  bear: "#ef4444",
  sideways: "#f59e0b",
};

export default function TabRegimeStats({ report }: Props) {
  const barOption = useMemo(() => {
    const regimes = report.regime_stats;
    const labels = regimes.map((r) => REGIME_LABELS[r.regime] ?? r.regime);
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 11 },
      },
      legend: {
        data: ["IC均值", "IC_IR"],
        textStyle: { color: "#94a3b8", fontSize: 10 },
        top: 4,
        right: 4,
      },
      grid: { top: 36, bottom: 28, left: 44, right: 12 },
      xAxis: {
        type: "category" as const,
        data: labels,
        axisLabel: { color: "#94a3b8", fontSize: 11 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: [
        {
          type: "value" as const,
          name: "IC",
          nameTextStyle: { color: "#64748b", fontSize: 9 },
          axisLabel: { color: "#64748b", fontSize: 9, formatter: (v: number) => v.toFixed(3) },
          splitLine: { lineStyle: { color: "#1e293b" } },
        },
        {
          type: "value" as const,
          name: "IR",
          nameTextStyle: { color: "#64748b", fontSize: 9 },
          axisLabel: { color: "#64748b", fontSize: 9, formatter: (v: number) => v.toFixed(2) },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "IC均值",
          type: "bar" as const,
          data: regimes.map((r) => ({
            value: r.ic,
            itemStyle: { color: REGIME_COLORS[r.regime] ?? "#64748b" },
          })),
          barMaxWidth: 40,
          label: {
            show: true,
            position: "top" as const,
            formatter: (p: { value: number }) => p.value.toFixed(4),
            color: "#94a3b8",
            fontSize: 9,
          },
        },
        {
          name: "IC_IR",
          type: "line" as const,
          yAxisIndex: 1,
          data: regimes.map((r) => r.ir),
          symbol: "circle",
          symbolSize: 8,
          lineStyle: { color: "#a78bfa", width: 2 },
          itemStyle: { color: "#a78bfa" },
        },
      ],
    };
  }, [report]);

  const best = report.regime_stats.reduce((a, b) => (a.ic > b.ic ? a : b));
  const worst = report.regime_stats.reduce((a, b) => (a.ic < b.ic ? a : b));

  return (
    <div className="space-y-4">
      {/* Regime cards */}
      <div className="grid grid-cols-3 gap-3">
        {report.regime_stats.map((r) => (
          <GlassCard key={r.regime} padding="sm">
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ background: REGIME_COLORS[r.regime] ?? "#64748b" }}
              />
              <p className="text-sm font-medium text-slate-200">{REGIME_LABELS[r.regime]}</p>
              <span className="ml-auto text-xs text-slate-500">{r.n_periods}期</span>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">IC均值</span>
                <span className={r.ic >= report.ic_mean ? "text-green-400" : "text-yellow-400"}>
                  {r.ic.toFixed(4)}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">IC_IR</span>
                <span className="text-slate-300">{r.ir.toFixed(3)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-slate-400">vs全期IC</span>
                <span className={r.ic >= report.ic_mean ? "text-green-400" : "text-red-400"}>
                  {r.ic >= report.ic_mean ? "+" : ""}{((r.ic - report.ic_mean) / Math.abs(report.ic_mean) * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          </GlassCard>
        ))}
      </div>

      {/* Comparison chart */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-2">三市场状态IC + IR对比</p>
        <ReactECharts option={barOption} style={{ height: 220 }} opts={{ renderer: "canvas" }} />
      </GlassCard>

      {/* Regime insight */}
      <GlassCard padding="sm">
        <p className="text-xs font-medium text-slate-400 mb-2">市场状态解读</p>
        <div className="space-y-1.5 text-xs text-slate-300">
          <p>
            最佳市场状态：
            <span className="font-medium" style={{ color: REGIME_COLORS[best.regime] }}>
              {REGIME_LABELS[best.regime]}
            </span>
            （IC={best.ic.toFixed(4)}）
          </p>
          <p>
            最差市场状态：
            <span className="font-medium" style={{ color: REGIME_COLORS[worst.regime] }}>
              {REGIME_LABELS[worst.regime]}
            </span>
            （IC={worst.ic.toFixed(4)}）
          </p>
          {worst.ic < 0 && (
            <p className="text-yellow-400">
              ⚠️ {REGIME_LABELS[worst.regime]}状态IC转负，建议配合RegimeModifier降低该状态下权重
            </p>
          )}
        </div>
      </GlassCard>
    </div>
  );
}
