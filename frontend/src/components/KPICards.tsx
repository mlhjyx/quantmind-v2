import type { DashboardSummary } from "@/types/dashboard";

interface Props {
  data: DashboardSummary | null;
  runningDays: number;
  loading: boolean;
}

interface CardDef {
  label: string;
  key: keyof DashboardSummary | "running_days";
  format: (v: number) => string;
  colorBySign?: boolean;
}

const cards: CardDef[] = [
  {
    label: "NAV",
    key: "nav",
    format: (v) => v.toFixed(4),
  },
  {
    label: "日收益率",
    key: "daily_return",
    format: (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%",
    colorBySign: true,
  },
  {
    label: "累计收益",
    key: "cumulative_return",
    format: (v) => (v >= 0 ? "+" : "") + (v * 100).toFixed(2) + "%",
    colorBySign: true,
  },
  {
    label: "Sharpe (60d)",
    key: "sharpe",
    format: (v) => v.toFixed(2),
  },
  {
    label: "MDD",
    key: "mdd",
    format: (v) => (v * 100).toFixed(2) + "%",
    colorBySign: true,
  },
  {
    label: "持仓数",
    key: "position_count",
    format: (v) => String(v),
  },
  {
    label: "运行天数",
    key: "running_days",
    format: (v) => `${v} / 60`,
  },
];

function valueColor(v: number, colorBySign: boolean): string {
  if (!colorBySign) return "text-white";
  if (v > 0) return "text-green-400";
  if (v < 0) return "text-red-400";
  return "text-gray-400";
}

export default function KPICards({ data, runningDays, loading }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
      {cards.map((c) => {
        const raw =
          c.key === "running_days"
            ? runningDays
            : data
              ? (data[c.key] as number)
              : 0;
        const display = loading ? "--" : c.format(raw);
        return (
          <div
            key={c.key}
            className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-md px-4 py-3"
          >
            <div className="text-xs text-gray-400 mb-1">{c.label}</div>
            <div
              className={`text-lg font-semibold ${loading ? "text-gray-500" : valueColor(raw, !!c.colorBySign)}`}
            >
              {display}
            </div>
          </div>
        );
      })}
    </div>
  );
}
