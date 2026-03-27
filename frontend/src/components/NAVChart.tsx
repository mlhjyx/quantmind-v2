import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import type { NAVPoint, NAVPeriod } from "@/types/dashboard";

interface Props {
  data: NAVPoint[];
  period: NAVPeriod;
  onPeriodChange: (p: NAVPeriod) => void;
  loading: boolean;
}

const PERIODS: { label: string; value: NAVPeriod }[] = [
  { label: "1月", value: "1m" },
  { label: "3月", value: "3m" },
  { label: "6月", value: "6m" },
  { label: "1年", value: "1y" },
  { label: "全部", value: "all" },
];

export default function NAVChart({
  data,
  period,
  onPeriodChange,
  loading,
}: Props) {
  const option = useMemo(() => {
    const dates = data.map((d) => d.trade_date);
    const navs = data.map((d) => d.nav);
    const drawdowns = data.map((d) => d.drawdown);

    return {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "axis" as const,
        backgroundColor: "rgba(15,23,42,0.9)",
        borderColor: "rgba(255,255,255,0.1)",
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        formatter: (params: Array<{ name: string; value: number; seriesName: string }>) => {
          const date = params[0]?.name ?? "";
          const lines = params.map((p) => {
            const val =
              p.seriesName === "NAV"
                ? p.value.toFixed(4)
                : (p.value * 100).toFixed(2) + "%";
            return `${p.seriesName}: ${val}`;
          });
          return `${date}<br/>${lines.join("<br/>")}`;
        },
      },
      legend: {
        data: ["NAV", "回撤"],
        textStyle: { color: "#94a3b8" },
        top: 4,
        right: 10,
      },
      grid: { top: 36, bottom: 30, left: 55, right: 55 },
      xAxis: {
        type: "category" as const,
        data: dates,
        axisLabel: { color: "#64748b", fontSize: 10 },
        axisLine: { lineStyle: { color: "#334155" } },
      },
      yAxis: [
        {
          type: "value" as const,
          name: "NAV",
          nameTextStyle: { color: "#64748b" },
          axisLabel: {
            color: "#64748b",
            formatter: (v: number) => v.toFixed(2),
          },
          splitLine: { lineStyle: { color: "#1e293b" } },
        },
        {
          type: "value" as const,
          name: "回撤",
          nameTextStyle: { color: "#64748b" },
          axisLabel: {
            color: "#64748b",
            formatter: (v: number) => (v * 100).toFixed(1) + "%",
          },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "NAV",
          type: "line",
          data: navs,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#38bdf8", width: 2 },
          areaStyle: {
            color: {
              type: "linear" as const,
              x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(56,189,248,0.25)" },
                { offset: 1, color: "rgba(56,189,248,0)" },
              ],
            },
          },
        },
        {
          name: "回撤",
          type: "line",
          yAxisIndex: 1,
          data: drawdowns,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#ef4444", width: 1 },
          areaStyle: {
            color: "rgba(239,68,68,0.15)",
          },
        },
      ],
    };
  }, [data]);

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-medium text-gray-300">NAV 曲线</h2>
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => onPeriodChange(p.value)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                period === p.value
                  ? "bg-sky-500/20 text-sky-400 border border-sky-500/30"
                  : "text-gray-400 hover:text-gray-300 hover:bg-white/5"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>
      {loading ? (
        <div className="h-[320px] flex items-center justify-center text-gray-500">
          Loading...
        </div>
      ) : data.length === 0 ? (
        <div className="h-[320px] flex items-center justify-center text-gray-500">
          暂无数据
        </div>
      ) : (
        <ReactECharts
          option={option}
          style={{ height: 320 }}
          opts={{ renderer: "canvas" }}
        />
      )}
    </div>
  );
}
