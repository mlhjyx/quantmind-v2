import { GlassCard } from "@/components/ui/GlassCard";
import type { FactorReport } from "@/api/factors";

interface Props {
  report: FactorReport;
}

function CellColor({ v, thresholds }: { v: number; thresholds: [number, number] }) {
  const cls =
    v >= thresholds[1]
      ? "text-green-400"
      : v >= thresholds[0]
      ? "text-slate-200"
      : v >= 0
      ? "text-yellow-400"
      : "text-red-400";
  return <span className={`tabular-nums font-medium ${cls}`}>{v.toFixed(4)}</span>;
}

function PctCell({ v }: { v: number }) {
  const cls = v >= 0.6 ? "text-green-400" : v >= 0.5 ? "text-slate-200" : "text-yellow-400";
  return <span className={`tabular-nums font-medium ${cls}`}>{(v * 100).toFixed(1)}%</span>;
}

export default function TabAnnual({ report }: Props) {
  const stats = report.annual_stats ?? [];

  if (stats.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500 text-sm">
        暂无分年度数据
      </div>
    );
  }

  const avgIC = stats.reduce((s, r) => s + r.ic, 0) / stats.length;
  const avgIR = stats.reduce((s, r) => s + r.ir, 0) / stats.length;
  const avgLS = stats.reduce((s, r) => s + r.longshort, 0) / stats.length;
  const avgWin = stats.reduce((s, r) => s + r.win_rate, 0) / stats.length;
  const positiveYears = stats.filter((r) => r.ic > 0).length;

  return (
    <div className="space-y-4">
      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: "平均IC", value: avgIC.toFixed(4), ok: Math.abs(avgIC) >= 0.03 },
          { label: "平均IR", value: avgIR.toFixed(3), ok: avgIR >= 0.4 },
          { label: "平均多空收益", value: (avgLS * 100).toFixed(1) + "%", ok: avgLS > 0.08 },
          { label: "IC正年份", value: `${positiveYears}/${stats.length}`, ok: positiveYears >= stats.length * 0.6 },
        ].map((m) => (
          <GlassCard key={m.label} padding="sm">
            <p className="text-xs text-slate-400 mb-1">{m.label}</p>
            <p className={`text-xl font-bold tabular-nums ${m.ok ? "text-green-400" : "text-yellow-400"}`}>
              {m.value}
            </p>
          </GlassCard>
        ))}
      </div>

      {/* Annual table */}
      <GlassCard>
        <p className="text-xs font-medium text-slate-400 mb-3">分年度统计</p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-700">
                <th className="pb-2 text-left text-slate-500 font-medium">年份</th>
                <th className="pb-2 text-right text-slate-500 font-medium">IC均值</th>
                <th className="pb-2 text-right text-slate-500 font-medium">IC_IR</th>
                <th className="pb-2 text-right text-slate-500 font-medium">多空年化</th>
                <th className="pb-2 text-right text-slate-500 font-medium">胜率</th>
                <th className="pb-2 text-right text-slate-500 font-medium">评级</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {stats.map((row) => {
                const rating =
                  row.ic >= 0.04 && row.ir >= 0.5
                    ? { label: "优", cls: "text-green-400 bg-green-500/10" }
                    : row.ic >= 0.02 && row.ir >= 0.3
                    ? { label: "良", cls: "text-blue-400 bg-blue-500/10" }
                    : row.ic >= 0
                    ? { label: "一般", cls: "text-yellow-400 bg-yellow-500/10" }
                    : { label: "差", cls: "text-red-400 bg-red-500/10" };
                return (
                  <tr key={row.year} className="hover:bg-white/3">
                    <td className="py-2.5 text-slate-200 font-medium">{row.year}</td>
                    <td className="py-2.5 text-right">
                      <CellColor v={row.ic} thresholds={[0.02, 0.04]} />
                    </td>
                    <td className="py-2.5 text-right">
                      <CellColor v={row.ir} thresholds={[0.3, 0.5]} />
                    </td>
                    <td className="py-2.5 text-right">
                      <CellColor v={row.longshort} thresholds={[0.05, 0.12]} />
                    </td>
                    <td className="py-2.5 text-right">
                      <PctCell v={row.win_rate} />
                    </td>
                    <td className="py-2.5 text-right">
                      <span className={`px-2 py-0.5 rounded text-xs border ${rating.cls}`}>
                        {rating.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot className="border-t border-slate-700">
              <tr>
                <td className="pt-2.5 text-slate-400 text-xs font-medium">均值</td>
                <td className="pt-2.5 text-right">
                  <CellColor v={avgIC} thresholds={[0.02, 0.04]} />
                </td>
                <td className="pt-2.5 text-right">
                  <CellColor v={avgIR} thresholds={[0.3, 0.5]} />
                </td>
                <td className="pt-2.5 text-right">
                  <CellColor v={avgLS} thresholds={[0.05, 0.12]} />
                </td>
                <td className="pt-2.5 text-right">
                  <PctCell v={avgWin} />
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </GlassCard>

      {/* Stability note */}
      <GlassCard padding="sm">
        <p className="text-xs font-medium text-slate-400 mb-1">稳定性评估</p>
        <p className="text-xs text-slate-300">
          IC正年份占比 {((positiveYears / stats.length) * 100).toFixed(0)}%
          {positiveYears / stats.length >= 0.8
            ? " · 表现稳健，各年份IC方向一致。"
            : positiveYears / stats.length >= 0.6
            ? " · 表现较稳定，少数年份出现IC转负。"
            : " · 稳定性不足，需关注因子失效风险。"}
        </p>
      </GlassCard>
    </div>
  );
}
