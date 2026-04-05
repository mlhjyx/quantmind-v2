import { Card, CardHeader } from "@/components/shared";
import { C } from "@/theme";

export function MonthlyHeatmap({ monthlyData }: { monthlyData: Record<string, number[]> }) {
  return (
    <Card className="col-span-4">
      <CardHeader title="月度收益" titleEn="Monthly %" />
      <div className="px-3 pb-3 pt-1.5">
        <div className="flex gap-[3px] mb-[3px]">
          <div style={{ width: 28 }} />
          {Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="flex-1 text-center" style={{ fontSize: 9, color: C.text4 }}>{i + 1}</div>
          ))}
          <div className="text-center" style={{ width: 40, fontSize: 9, color: C.text4, fontWeight: 600 }}>YTD</div>
        </div>
        {Object.entries(monthlyData).map(([year, vals]) => {
          const safeVals = vals.map(v => v ?? 0);
          const ytd = safeVals.filter(v => v !== 0).reduce((a, b) => a + b, 0);
          return (
            <div key={year} className="flex gap-[3px] mb-[3px]">
              <div style={{ width: 28, fontSize: 11, color: C.text3, lineHeight: "30px", fontWeight: 500 }}>{year.slice(2)}</div>
              {safeVals.map((v, i) => {
                const isEmpty = year === "2026" && i >= 3;
                if (isEmpty) return <div key={i} className="flex-1 rounded" style={{ height: 30, background: C.bg2 }} />;
                const intensity = Math.min(Math.abs(v) / 5, 1);
                const bgColor = v >= 0 ? C.up : C.down;
                return (
                  <div key={i} className="flex-1 rounded flex items-center justify-center cursor-pointer"
                    style={{
                      height: 30,
                      background: `${bgColor}${Math.round(intensity * 40 + 10).toString(16).padStart(2, "0")}`,
                      fontSize: 10, color: v >= 0 ? C.up : C.down, fontFamily: C.mono,
                    }}>
                    {v !== 0 ? v.toFixed(1) : ""}
                  </div>
                );
              })}
              <div className="rounded flex items-center justify-center" style={{
                height: 30, width: 40,
                background: ytd >= 0 ? `${C.up}20` : `${C.down}20`,
                fontSize: 11, color: ytd >= 0 ? C.up : C.down, fontWeight: 700, fontFamily: C.mono,
              }}>
                {ytd.toFixed(1)}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
