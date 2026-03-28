import { GlassCard } from "@/components/ui/GlassCard";
import type { ModelHealth as ModelHealthType } from "@/api/agent";

const MODEL_LABELS: Record<string, string> = {
  "deepseek-r1": "DeepSeek-R1",
  "deepseek-v3": "DeepSeek-V3.2",
  "qwen3":       "Qwen3",
};

interface ModelHealthProps {
  models: ModelHealthType[];
  loading?: boolean;
}

function LatencyBar({ ms }: { ms: number }) {
  const pct = Math.min(100, (ms / 3000) * 100);
  const color = ms < 500 ? "bg-green-400" : ms < 1500 ? "bg-yellow-400" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-slate-700 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] tabular-nums text-slate-400 w-12 text-right">{ms}ms</span>
    </div>
  );
}

export function ModelHealth({ models, loading }: ModelHealthProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-2xl bg-slate-800/40 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {models.map((m) => (
        <GlassCard key={m.model} className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-200">
              {MODEL_LABELS[m.model] ?? m.model}
            </span>
            <span
              className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                m.is_online
                  ? "text-green-300 bg-green-500/15 border-green-500/30"
                  : "text-red-300 bg-red-500/15 border-red-500/30"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${m.is_online ? "bg-green-400 animate-pulse" : "bg-red-400"}`} />
              {m.is_online ? "在线" : "离线"}
            </span>
          </div>

          {m.latency_ms != null && m.is_online && (
            <div>
              <div className="text-[10px] text-slate-500 mb-1">响应延迟</div>
              <LatencyBar ms={m.latency_ms} />
            </div>
          )}

          {m.error && (
            <p className="text-[10px] text-red-400 truncate" title={m.error}>{m.error}</p>
          )}

          <p className="text-[10px] text-slate-600">
            检测于 {new Date(m.last_checked_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
          </p>
        </GlassCard>
      ))}
    </div>
  );
}
