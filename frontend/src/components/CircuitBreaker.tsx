import type { CircuitBreakerState } from "@/types/dashboard";

interface Props {
  data: CircuitBreakerState | null;
  loading: boolean;
}

interface LevelStyle {
  color: string;
  bg: string;
  ring: string;
  label: string;
}

const LEVEL_STYLES: Record<number, LevelStyle> = {
  0: {
    color: "bg-green-400",
    bg: "bg-green-400/10",
    ring: "ring-green-400/30",
    label: "NORMAL",
  },
  1: {
    color: "bg-yellow-400",
    bg: "bg-yellow-400/10",
    ring: "ring-yellow-400/30",
    label: "L1 - 观察",
  },
  2: {
    color: "bg-orange-400",
    bg: "bg-orange-400/10",
    ring: "ring-orange-400/30",
    label: "L2 - 降仓",
  },
  3: {
    color: "bg-red-500",
    bg: "bg-red-500/10",
    ring: "ring-red-500/30",
    label: "L3 - 停止",
  },
  4: {
    color: "bg-gray-800",
    bg: "bg-gray-800/20",
    ring: "ring-gray-600/30",
    label: "L4 - 锁定",
  },
};

function getStyle(level: number): LevelStyle {
  return (
    LEVEL_STYLES[level] ?? {
      color: "bg-gray-400",
      bg: "bg-gray-400/10",
      ring: "ring-gray-400/30",
      label: `L${level}`,
    }
  );
}

export default function CircuitBreaker({ data, loading }: Props) {
  const level = data?.level ?? 0;
  const style = getStyle(level);

  return (
    <div className="rounded-xl border border-white/10 bg-white/5 backdrop-blur-md p-4">
      <h2 className="text-sm font-medium text-gray-300 mb-3">熔断状态</h2>
      {loading ? (
        <div className="h-20 flex items-center justify-center text-gray-500">
          Loading...
        </div>
      ) : (
        <div className="flex items-center gap-4">
          {/* Indicator light */}
          <div
            className={`relative w-10 h-10 rounded-full ${style.bg} ring-2 ${style.ring} flex items-center justify-center`}
          >
            <div
              className={`w-4 h-4 rounded-full ${style.color} ${level === 0 ? "animate-pulse" : ""}`}
            />
          </div>

          {/* Status text */}
          <div className="flex-1">
            <div className="text-sm font-medium text-gray-200">
              {style.label}
            </div>
            {data && (
              <div className="text-xs text-gray-500 mt-0.5">
                {data.entered_date}
                {data.trigger_reason && ` - ${data.trigger_reason}`}
              </div>
            )}
            {data && level > 0 && (
              <div className="text-xs text-gray-500 mt-0.5">
                仓位乘数: {data.position_multiplier}x | 恢复天数:{" "}
                {data.recovery_streak_days}
              </div>
            )}
          </div>

          {/* Level dots */}
          <div className="flex gap-1.5">
            {[0, 1, 2, 3, 4].map((l) => {
              const s = getStyle(l);
              return (
                <div
                  key={l}
                  className={`w-2.5 h-2.5 rounded-full ${l <= level ? s.color : "bg-gray-700"}`}
                  title={`L${l}`}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
