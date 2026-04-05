import { Card, CardHeader, Sparkline } from "@/components/shared";
import { C } from "@/theme";

export type FactorRow = { name: string; cat: string; ic: number; ir: number; dir: string; status: string; trend: number[] };

export function FactorLibraryPanel({ factorData }: { factorData: FactorRow[] }) {
  const activeCount = factorData.filter((f) => f.status === "active").length;
  const newCount = factorData.filter((f) => f.status === "new").length;
  const decayCount = factorData.filter((f) => f.status === "decay").length;
  return (
    <Card className="col-span-7">
      <CardHeader
        title="因子库" titleEn="Factor Library"
        right={
          <div className="flex items-center gap-3" style={{ fontSize: 10 }}>
            <span style={{ color: C.up }}>● {activeCount} 活跃</span>
            <span style={{ color: C.accent }}>● {newCount} 新入</span>
            <span style={{ color: C.warn }}>● {decayCount} 衰退</span>
          </div>
        }
      />
      <div className="px-3 pb-2">
        <table className="w-full" style={{ fontSize: 11 }}>
          <thead>
            <tr style={{ color: C.text4 }}>
              <th className="text-left py-1.5 font-normal">因子名</th>
              <th className="text-left py-1.5 font-normal">类别</th>
              <th className="text-right py-1.5 font-normal">IC</th>
              <th className="text-right py-1.5 font-normal">IR</th>
              <th className="text-center py-1.5 font-normal">方向</th>
              <th className="text-center py-1.5 font-normal">趋势</th>
              <th className="text-center py-1.5 font-normal">状态</th>
            </tr>
          </thead>
          <tbody>
            {factorData.map((f) => (
              <tr key={f.name} className="cursor-pointer" style={{ borderTop: `1px solid ${C.border}` }}>
                <td className="py-1.5" style={{ color: C.text2, fontFamily: C.mono }}>{f.name}</td>
                <td className="py-1.5">
                  <span className="px-1.5 py-0.5 rounded" style={{ fontSize: 10, color: C.text3, background: C.bg2 }}>{f.cat}</span>
                </td>
                <td className="text-right py-1.5" style={{ fontFamily: C.mono, fontWeight: 600, color: Math.abs(f.ic) < 0.02 ? C.text4 : f.ic > 0 ? C.up : "#f59e0b" }}>
                  {f.ic > 0 ? "+" : ""}{f.ic.toFixed(3)}
                </td>
                <td className="text-right py-1.5" style={{ fontFamily: C.mono, color: C.text2 }}>{f.ir.toFixed(2)}</td>
                <td className="text-center py-1.5">
                  <span className="px-1.5 py-0.5 rounded" style={{
                    fontSize: 9, fontWeight: 500,
                    color: f.dir === "正向" ? C.up : "#f59e0b",
                    background: f.dir === "正向" ? `${C.up}10` : "#f59e0b10",
                  }}>
                    {f.dir === "正向" ? "↑ 正向" : "↓ 反向"}
                  </span>
                </td>
                <td className="text-center py-1.5">
                  <div className="flex justify-center">
                    <Sparkline data={f.trend} color={f.status === "decay" ? C.warn : C.accent} width={44} height={16} />
                  </div>
                </td>
                <td className="text-center py-1.5">
                  <span className="px-1.5 py-0.5 rounded-full" style={{
                    fontSize: 9,
                    color:      f.status === "active" ? C.up : f.status === "new" ? C.accent : C.warn,
                    background: f.status === "active" ? `${C.up}10` : f.status === "new" ? C.accentSoft : `${C.warn}10`,
                  }}>
                    {f.status === "active" ? "Active" : f.status === "new" ? "New" : "Decay"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
