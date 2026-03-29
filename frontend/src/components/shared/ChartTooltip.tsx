import { C } from "@/theme";

interface TooltipPayloadItem {
  name: string;
  value: number | string;
  color: string;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
  formatter?: (value: number | string, name: string) => string;
}

/** Recharts-compatible tooltip. Also works as an ECharts custom tooltip renderer. */
export function ChartTooltip({ active, payload, label, formatter }: ChartTooltipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="rounded-lg px-3 py-2"
      style={{
        background: C.bg2,
        border: `1px solid ${C.borderLight}`,
        boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
        pointerEvents: "none",
      }}
    >
      {label && (
        <div style={{ fontSize: 10, color: C.text3, marginBottom: 4 }}>{label}</div>
      )}
      {payload.map((p, i) => (
        <div key={i} className="flex items-center gap-2" style={{ fontSize: 11 }}>
          <span className="w-2 h-2 rounded-full shrink-0" style={{ background: p.color }} />
          <span style={{ color: C.text2 }}>{p.name}: </span>
          <span style={{ color: C.text1, fontFamily: C.mono, fontWeight: 600 }}>
            {formatter
              ? formatter(p.value, p.name)
              : typeof p.value === "number"
              ? p.value.toFixed(4)
              : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}
