import { Card, CardHeader } from "@/components/shared";
import { C } from "@/theme";
import type { Position } from "@/types/dashboard";

export function HoldingsTable({ positions }: { positions: Position[] }) {
  const rows = positions;

  return (
    <Card className="col-span-4">
      <CardHeader
        title="持仓明细" titleEn="Holdings"
        right={<span style={{ fontSize: 10, color: C.text4 }}>30只 · 85.5%</span>}
      />
      <div className="px-3 pb-2">
        <table className="w-full" style={{ fontSize: 11 }}>
          <thead>
            <tr style={{ color: C.text4 }}>
              <th className="text-left py-1.5 font-normal">代码</th>
              <th className="text-right py-1.5 font-normal">权重</th>
              <th className="text-right py-1.5 font-normal">盈亏</th>
              <th className="text-right py-1.5 font-normal">天</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const wt  = p.weight * 100;
              const pnl = p.unrealized_pnl * 100;
              return (
                <tr key={p.code} className="cursor-pointer" style={{ borderTop: `1px solid ${C.border}` }}>
                  <td className="py-1.5" style={{ color: C.text2, fontFamily: C.mono }}>{p.code}</td>
                  <td className="text-right py-1.5">
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-1 rounded-full" style={{ width: wt * 4, background: C.accent, opacity: 0.5 }} />
                      <span style={{ fontFamily: C.mono, color: C.text2 }}>{wt.toFixed(1)}%</span>
                    </div>
                  </td>
                  <td className="text-right py-1.5" style={{ fontFamily: C.mono, color: pnl >= 0 ? C.up : C.down }}>
                    {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%
                  </td>
                  <td className="text-right py-1.5" style={{ color: C.text4, fontFamily: C.mono }}>{p.holding_days}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
