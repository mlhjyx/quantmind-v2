import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { FactorReport } from "@/api/factors";

interface Props {
  report: FactorReport;
}

const GROUP_COLORS = ["#64748b", "#38bdf8", "#a78bfa", "#fb923c", "#22c55e"];
const LS_COLOR = "#f43f5e";

const CHART_TOOLTIP = {
  backgroundColor: "rgba(15,23,42,0.9)",
  borderColor: "rgba(255,255,255,0.1)",
  textStyle: { color: "#e2e8f0", fontSize: 11 },
};

export default function TabGroupReturns({ report }: Props) {
  const groupNavOption = useMemo(() => {
    const dates = report.group_nav[0]?.dates ?? [];
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const, ...CHART_TOOLTIP },
      legend: {
        data: [...report.group_nav.map((g) => g.group), "多空"],
        textStyle: { color: "#94a3b8", fontSize: 10 },
        top: 4,
        right: 4,
      },
      grid: { top: 36, bottom: 28, left: 50, right: 12 },
      xAxis: {
        type: "category" as const,
        data: dates,
        axisLabel: { color: "#475569", fontSize: 9, interval: Math.floor(dates.length / 6) },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: { color: "#64748b", fontSize: 9, formatter: (v: number) => v.toFixed(2) },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [
        ...report.group_nav.map((g, i) => ({
          name: g.group,
          type: "line" as const,
          data: g.nav,
          smooth: true,
          symbol: "none",
          lineStyle: { color: GROUP_COLORS[i] ?? "#64748b", width: 1.5 },
        })),
        {
          name: "多空",
          type: "line" as const,
          data: report.longshort_nav.nav,
          smooth: true,
          symbol: "none",
          lineStyle: { color: LS_COLOR, width: 2, type: "dashed" as const },
        },
      ],
    };
  }, [report]);

  const monthlyHeatOption = useMemo(() => {
    const months = report.group_monthly.map(
      (r) => `${r.year}-${String(r.month).padStart(2, "0")}`
    );
    const groups = ["G1", "G2", "G3", "G4", "G5", "多空"];
    const data: [number, number, number][] = [];
    report.group_monthly.forEach((row, mi) => {
      const vals = [row.g1, row.g2, row.g3, row.g4, row.g5, row.ls];
      vals.forEach((v, gi) => data.push([mi, gi, Number((v * 100).toFixed(2))]));
    });
    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item" as const,
        ...CHART_TOOLTIP,
        formatter: (p: { value: [number, number, number] }) =>
          `${months[p.value[0]]} ${groups[p.value[1]]}<br/>收益: ${p.value[2].toFixed(2)}%`,
      },
      grid: { top: 16, bottom: 60, left: 56, right: 16 },
      xAxis: {
        type: "category" as const,
        data: months,
        axisLabel: { color: "#475569", fontSize: 8, rotate: 45 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "category" as const,
        data: groups,
        axisLabel: { color: "#64748b", fontSize: 9 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      visualMap: {
        min: -3,
        max: 3,
        calculable: true,
        orient: "horizontal" as const,
        left: "center",
        bottom: 0,
        textStyle: { color: "#64748b", fontSize: 9 },
        inRange: { color: ["#22c55e", "#f8fafc", "#ef4444"] },
        itemHeight: 80,
        itemWidth: 10,
      },
      series: [{
        type: "heatmap" as const,
        data,
        label: {
          show: true,
          fontSize: 8,
          color: "#1e293b",
          formatter: (p: { value: [number, number, number] }) => `${p.value[2].toFixed(1)}%`,
        },
      }],
    };
  }, [report]);

  return (
    <div className="space-y-4">
      {/* Group NAV curves */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-2">5分组净值曲线 + 多空组合</p>
        <ReactECharts option={groupNavOption} style={{ height: 220 }} opts={{ renderer: "canvas" }} />
      </GlassCard>

      {/* Monthly heatmap */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-2">分组月度热力图（收益%）</p>
        <ReactECharts option={monthlyHeatOption} style={{ height: 200 }} opts={{ renderer: "canvas" }} />
      </GlassCard>

      {/* Group annual returns bar */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-3">分组年化收益（估算）</p>
        <div className="flex items-end gap-2 h-24">
          {report.group_nav.map((g, i) => {
            const finalNav = g.nav[g.nav.length - 1] ?? 1;
            const years = g.nav.length / 12;
            const annualized = (Math.pow(finalNav, 1 / years) - 1) * 100;
            const barH = Math.max(4, Math.min(96, Math.abs(annualized) * 3));
            return (
              <div key={g.group} className="flex flex-col items-center gap-1 flex-1">
                <span className="text-xs text-slate-300 tabular-nums">{annualized.toFixed(1)}%</span>
                <div
                  className="w-full rounded-t"
                  style={{ height: barH, background: GROUP_COLORS[i] ?? "#64748b" }}
                />
                <span className="text-xs text-slate-400">{g.group}</span>
              </div>
            );
          })}
        </div>
      </GlassCard>
    </div>
  );
}
