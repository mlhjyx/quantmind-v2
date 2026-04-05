import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader } from "@/components/shared";
import { fetchDashboardStrategies } from "@/api/dashboard";
import { STALE } from "@/api/QueryProvider";
import { C } from "@/theme";

export function StrategiesPanel() {
  const { data: strategies = [], isLoading } = useQuery({
    queryKey: ["dashboard-strategies"],
    queryFn: fetchDashboardStrategies,
    staleTime: STALE.config,
  });

  return (
    <Card className="overflow-hidden">
      <CardHeader title="策略" titleEn="Strategies" />
      <div className="p-3 space-y-2">
        {isLoading ? (
          <div className="h-20 animate-pulse rounded-lg" style={{ background: C.bg3 }} />
        ) : strategies.length === 0 ? (
          <div style={{ fontSize: 11, color: C.text4, textAlign: "center", padding: "12px 0" }}>暂无策略</div>
        ) : (
          strategies.map((s) => {
            const pnlStr = s.pnl != null ? `${s.pnl >= 0 ? "+" : ""}${(s.pnl * 100).toFixed(2)}%` : "—";
            const isActive = s.status !== "inactive" && s.status !== "archived";
            const isUp = (s.pnl ?? 0) >= 0;
            return (
              <div key={s.id} className="flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer" style={{ background: C.bg2, opacity: isActive ? 1 : 0.35 }}>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full" style={{ background: isActive ? (isUp ? C.up : C.down) : C.text4 }} />
                  <span style={{ fontSize: 12, color: C.text1 }}>{s.name}</span>
                  {s.market && <span style={{ fontSize: 10, color: C.text4 }}>{s.market}</span>}
                </div>
                <div className="flex items-center gap-3">
                  <span style={{ fontSize: 10, color: C.text4 }}>SR {s.sharpe != null ? s.sharpe.toFixed(2) : "—"}</span>
                  <span style={{ fontSize: 15, fontFamily: C.mono, fontWeight: 700, color: pnlStr.startsWith("+") ? C.up : pnlStr.startsWith("-") ? C.down : C.text4 }}>
                    {pnlStr}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </Card>
  );
}
