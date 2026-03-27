import { GlassCard } from "./GlassCard";

type MetricStatus = "normal" | "warning" | "alert" | "good";

interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  change?: number;       // % change vs yesterday, positive = up
  status?: MetricStatus;
  subtitle?: string;
  className?: string;
}

const statusColors: Record<MetricStatus, string> = {
  good: "text-green-400",
  normal: "text-slate-200",
  warning: "text-yellow-400",
  alert: "text-red-400",
};

export function MetricCard({
  label,
  value,
  unit,
  change,
  status = "normal",
  subtitle,
  className = "",
}: MetricCardProps) {
  const changePositive = change !== undefined && change > 0;
  const changeNegative = change !== undefined && change < 0;

  return (
    <GlassCard className={className}>
      <p className="text-xs text-slate-400 mb-1 truncate">{label}</p>
      <div className="flex items-baseline gap-1">
        <span className={`text-2xl font-semibold tabular-nums ${statusColors[status]}`}>
          {value}
        </span>
        {unit && <span className="text-sm text-slate-400">{unit}</span>}
      </div>
      <div className="flex items-center gap-2 mt-1">
        {change !== undefined && (
          <span
            className={`text-xs font-medium ${
              changePositive
                ? "text-red-400"   // A股惯例: 涨=红
                : changeNegative
                ? "text-green-400" // 跌=绿
                : "text-slate-400"
            }`}
          >
            {changePositive ? "↑" : changeNegative ? "↓" : "→"}
            {Math.abs(change).toFixed(2)}%
          </span>
        )}
        {subtitle && (
          <span className="text-xs text-slate-500 truncate">{subtitle}</span>
        )}
      </div>
    </GlassCard>
  );
}
