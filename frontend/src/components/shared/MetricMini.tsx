import { C } from "@/theme";
import { Sparkline } from "./Sparkline";

interface MetricMiniProps {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
  /** Optional sparkline data */
  sparkData?: number[];
  sparkColor?: string;
}

export function MetricMini({
  label,
  value,
  sub,
  valueColor,
  sparkData,
  sparkColor,
}: MetricMiniProps) {
  return (
    <div
      className="rounded-lg p-2.5 flex items-center justify-between gap-2"
      style={{ background: C.bg2 }}
    >
      <div className="min-w-0">
        <div style={{ fontSize: 9, color: C.text4 }}>{label}</div>
        <div
          style={{
            fontSize: 14,
            color: valueColor ?? C.text1,
            fontFamily: C.mono,
            fontWeight: 600,
            lineHeight: 1.2,
          }}
        >
          {value}
        </div>
        {sub && <div style={{ fontSize: 9, color: C.text3 }}>{sub}</div>}
      </div>
      {sparkData && sparkData.length >= 2 && (
        <Sparkline data={sparkData} color={sparkColor ?? (valueColor ?? C.accent)} />
      )}
    </div>
  );
}
