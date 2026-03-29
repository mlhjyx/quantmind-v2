import { useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { FactorReport } from "@/api/factors";

interface Props {
  report: FactorReport;
}

const CHART_TOOLTIP = {
  backgroundColor: "rgba(15,23,42,0.9)",
  borderColor: "rgba(255,255,255,0.1)",
  textStyle: { color: "#e2e8f0", fontSize: 11 },
};

function fmt(v: number | null, digits: number): string {
  return v != null ? v.toFixed(digits) : "—";
}

export default function TabICAnalysis({ report }: Props) {
  const hasIC = report.ic_series.length > 0;

  const icSeriesOption = useMemo(() => {
    if (!hasIC) return null;
    const dates = report.ic_series.map((d) => d.date);
    const ics = report.ic_series.map((d) => d.ic);
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const, ...CHART_TOOLTIP },
      legend: { data: ["IC", "累计IC"], textStyle: { color: "#94a3b8", fontSize: 10 }, top: 4, right: 4 },
      grid: { top: 36, bottom: 28, left: 50, right: 12 },
      xAxis: {
        type: "category" as const,
        data: dates,
        axisLabel: { color: "#475569", fontSize: 9, interval: Math.floor(dates.length / 8) },
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
          name: "累计",
          nameTextStyle: { color: "#64748b", fontSize: 9 },
          axisLabel: { color: "#64748b", fontSize: 9, formatter: (v: number) => v.toFixed(2) },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: "IC",
          type: "bar" as const,
          data: ics.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? "#38bdf8" : "#ef4444" } })),
          barMaxWidth: 6,
        },
        {
          name: "累计IC",
          type: "line" as const,
          yAxisIndex: 1,
          data: report.ic_cumsum,
          smooth: true,
          symbol: "none",
          lineStyle: { color: "#a78bfa", width: 2 },
        },
      ],
    };
  }, [report, hasIC]);

  const distOption = useMemo(() => {
    const vals = report.ic_distribution ?? [];
    if (vals.length === 0) return null;
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const bins = 20;
    const step = (max - min) / bins || 1;
    const counts = new Array(bins).fill(0);
    vals.forEach((v) => {
      const i = Math.min(Math.floor((v - min) / step), bins - 1);
      counts[i]++;
    });
    const labels = counts.map((_, i) => Number((min + i * step).toFixed(3)));
    return {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" as const, ...CHART_TOOLTIP },
      grid: { top: 20, bottom: 28, left: 44, right: 12 },
      xAxis: {
        type: "category" as const,
        data: labels,
        axisLabel: { color: "#475569", fontSize: 8 },
        axisLine: { lineStyle: { color: "#1e293b" } },
      },
      yAxis: {
        type: "value" as const,
        axisLabel: { color: "#475569", fontSize: 9 },
        splitLine: { lineStyle: { color: "#1e293b" } },
      },
      series: [{
        type: "bar" as const,
        data: counts,
        itemStyle: { color: "#38bdf8", opacity: 0.8 },
        barMaxWidth: 16,
      }],
    };
  }, [report]);

  const { ic_mean, ic_ir, t_stat, fdr_t_stat, newey_west_t } = report;

  return (
    <div className="space-y-4">
      {/* Metric cards */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { label: "IC均值", value: fmt(ic_mean, 4), ok: ic_mean != null && Math.abs(ic_mean) >= 0.03 },
          { label: "IC_IR", value: fmt(ic_ir, 3), ok: ic_ir != null && ic_ir >= 0.5 },
          { label: "原始t值", value: fmt(t_stat, 3), ok: t_stat != null && t_stat >= 2.5 },
          {
            label: "FDR校正t值",
            value: fmt(fdr_t_stat, 3),
            ok: fdr_t_stat != null && fdr_t_stat >= 2.0,
            warn: fdr_t_stat != null && fdr_t_stat < 2.0,
          },
          {
            label: "Newey-West t",
            value: fmt(newey_west_t, 3),
            ok: newey_west_t != null && newey_west_t >= 2.0,
          },
        ].map((m) => (
          <GlassCard key={m.label} padding="sm">
            <p className="text-xs text-slate-400 mb-1">{m.label}</p>
            <p className={`text-xl font-bold tabular-nums ${
              m.value === "—" ? "text-slate-500" : m.warn ? "text-yellow-400" : m.ok ? "text-green-400" : "text-red-400"
            }`}>
              {m.value}
            </p>
            {m.warn && (
              <p className="text-xs text-yellow-400 mt-0.5">FDR校正后 &lt;2.0</p>
            )}
          </GlassCard>
        ))}
      </div>

      {/* FDR note */}
      {fdr_t_stat != null && fdr_t_stat < 2.0 && (
        <div className="px-3 py-2 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-xs text-yellow-400">
          ⚠️ FDR校正后 t={fdr_t_stat.toFixed(2)} &lt; 2.0，建议结合经济学逻辑审慎评估
        </div>
      )}

      {/* IC time series */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-2">IC时序 + 累计IC</p>
        {icSeriesOption ? (
          <ReactECharts option={icSeriesOption} style={{ height: 200 }} opts={{ renderer: "canvas" }} />
        ) : (
          <div className="py-12 text-center text-slate-500 text-sm">暂无IC时序数据</div>
        )}
      </GlassCard>

      {/* IC distribution + multi-period */}
      <div className="grid grid-cols-2 gap-4">
        <GlassCard>
          <p className="text-xs font-medium text-slate-400 mb-2">IC分布直方图</p>
          {distOption ? (
            <ReactECharts option={distOption} style={{ height: 160 }} opts={{ renderer: "canvas" }} />
          ) : (
            <div className="py-8 text-center text-slate-500 text-sm">暂无分布数据</div>
          )}
        </GlassCard>

        <GlassCard>
          <p className="text-xs font-medium text-slate-400 mb-3">多周期IC对比</p>
          {report.ic_by_period.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-slate-800">
                    <th className="pb-2 text-left text-slate-500 font-medium">周期</th>
                    <th className="pb-2 text-right text-slate-500 font-medium">IC均值</th>
                    <th className="pb-2 text-right text-slate-500 font-medium">IC_IR</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {report.ic_by_period.map((row) => (
                    <tr key={row.period}>
                      <td className="py-2 text-slate-300">{row.period}</td>
                      <td className={`py-2 text-right tabular-nums ${
                        Math.abs(row.ic) >= 0.03 ? "text-green-400" : "text-yellow-400"
                      }`}>{row.ic.toFixed(4)}</td>
                      <td className={`py-2 text-right tabular-nums ${
                        row.ir >= 0.5 ? "text-green-400" : "text-yellow-400"
                      }`}>{row.ir.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-8 text-center text-slate-500 text-sm">暂无多周期数据</div>
          )}
        </GlassCard>
      </div>
    </div>
  );
}
