import { GlassCard } from "@/components/ui/GlassCard";
import type { PipelineRun } from "@/api/pipeline";

const statusLabel: Record<PipelineRun["status"], { text: string; color: string }> = {
  running:   { text: "运行中", color: "text-blue-300 bg-blue-500/15 border-blue-500/30" },
  completed: { text: "完成",   color: "text-green-300 bg-green-500/15 border-green-500/30" },
  failed:    { text: "失败",   color: "text-red-300 bg-red-500/15 border-red-500/30" },
  paused:    { text: "已暂停", color: "text-yellow-300 bg-yellow-500/15 border-yellow-500/30" },
};

interface PipelineHistoryProps {
  runs: PipelineRun[];
  loading?: boolean;
}

function formatDuration(start: string, end?: string): string {
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const seconds = Math.floor((e - s) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m${seconds % 60}s`;
}

function SharpeArrow({ before, after }: { before?: number; after?: number }) {
  if (before == null || after == null) return <span className="text-slate-500">—</span>;
  const diff = after - before;
  const color = diff > 0 ? "text-green-400" : diff < 0 ? "text-red-400" : "text-slate-400";
  const arrow = diff > 0 ? "↑" : diff < 0 ? "↓" : "→";
  return (
    <span className={`text-xs font-medium tabular-nums ${color}`}>
      {before.toFixed(2)} {arrow} {after.toFixed(2)}
    </span>
  );
}

export function PipelineHistory({ runs, loading }: PipelineHistoryProps) {
  if (loading) {
    return (
      <GlassCard>
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-10 rounded-lg bg-slate-800/40 animate-pulse" />
          ))}
        </div>
      </GlassCard>
    );
  }

  if (runs.length === 0) {
    return (
      <GlassCard className="flex flex-col items-center justify-center py-10 text-center">
        <span className="text-3xl mb-2">📋</span>
        <p className="text-sm text-slate-300 font-medium">暂无运行记录</p>
        <p className="text-xs text-slate-500 mt-1">手动触发或等待调度自动运行</p>
      </GlassCard>
    );
  }

  return (
    <GlassCard padding="sm">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 border-b border-white/5">
              <th className="text-left py-2 px-3 font-medium">运行ID</th>
              <th className="text-left py-2 px-3 font-medium">状态</th>
              <th className="text-left py-2 px-3 font-medium">引擎</th>
              <th className="text-right py-2 px-3 font-medium">发现</th>
              <th className="text-right py-2 px-3 font-medium">Gate通过</th>
              <th className="text-right py-2 px-3 font-medium">入库</th>
              <th className="text-left py-2 px-3 font-medium">Sharpe变化</th>
              <th className="text-left py-2 px-3 font-medium">耗时</th>
              <th className="text-left py-2 px-3 font-medium">触发</th>
              <th className="text-left py-2 px-3 font-medium">时间</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const st = statusLabel[run.status];
              return (
                <tr
                  key={run.run_id}
                  className="border-b border-white/5 hover:bg-white/[0.03] transition-colors"
                >
                  <td className="py-2.5 px-3 font-mono text-slate-400 text-[11px]">
                    {run.run_id.slice(0, 8)}...
                  </td>
                  <td className="py-2.5 px-3">
                    <span className={`px-1.5 py-0.5 rounded border text-[10px] font-semibold ${st.color}`}>
                      {st.text}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-slate-300">{run.engine}</td>
                  <td className="py-2.5 px-3 text-right text-slate-200 tabular-nums">{run.discovered}</td>
                  <td className="py-2.5 px-3 text-right text-slate-200 tabular-nums">{run.gate_passed}</td>
                  <td className="py-2.5 px-3 text-right text-slate-200 tabular-nums">{run.archived}</td>
                  <td className="py-2.5 px-3">
                    <SharpeArrow before={run.sharpe_before} after={run.sharpe_after} />
                  </td>
                  <td className="py-2.5 px-3 text-slate-400">
                    {formatDuration(run.started_at, run.completed_at)}
                  </td>
                  <td className="py-2.5 px-3">
                    <span className={`text-[10px] ${run.triggered_by === "manual" ? "text-blue-400" : "text-slate-500"}`}>
                      {run.triggered_by === "manual" ? "手动" : "定时"}
                    </span>
                  </td>
                  <td className="py-2.5 px-3 text-slate-500">
                    {new Date(run.started_at).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </GlassCard>
  );
}
