import type { PipelineNode, PipelineNodeStatus } from "@/api/pipeline";

const NODE_DEFS = [
  { id: "discover",  label: "发现",   icon: "⛏️" },
  { id: "evaluate",  label: "评估",   icon: "🔬" },
  { id: "archive",   label: "入库",   icon: "📦" },
  { id: "build",     label: "构建",   icon: "⚡" },
  { id: "backtest",  label: "回测",   icon: "📊" },
  { id: "diagnose",  label: "诊断",   icon: "🩺" },
  { id: "risk",      label: "风控",   icon: "🛡️" },
  { id: "deploy",    label: "部署",   icon: "🚀" },
] as const;

const statusStyles: Record<PipelineNodeStatus, { ring: string; bg: string; text: string; dot: string }> = {
  idle:      { ring: "border-white/10",         bg: "bg-slate-800/60",       text: "text-slate-400", dot: "bg-slate-600" },
  running:   { ring: "border-blue-400/60",      bg: "bg-blue-900/40",        text: "text-blue-300",  dot: "bg-blue-400 animate-pulse" },
  completed: { ring: "border-green-400/40",     bg: "bg-green-900/30",       text: "text-green-400", dot: "bg-green-400" },
  failed:    { ring: "border-red-400/50",       bg: "bg-red-900/30",         text: "text-red-400",   dot: "bg-red-400" },
  skipped:   { ring: "border-slate-600/30",     bg: "bg-slate-800/30",       text: "text-slate-500", dot: "bg-slate-700" },
};

interface FlowChartProps {
  nodes: PipelineNode[];
  currentNode: string | null;
}

function getNodeData(nodes: PipelineNode[], id: string): PipelineNode | undefined {
  return nodes.find((n) => n.id === id);
}

function ConnectorArrow({ active }: { active: boolean }) {
  return (
    <div className="flex items-center px-1">
      <div className={`h-px w-6 transition-colors duration-300 ${active ? "bg-blue-400/60" : "bg-white/10"}`} />
      <div className={`w-0 h-0 border-t-[4px] border-b-[4px] border-l-[6px] border-t-transparent border-b-transparent transition-colors duration-300 ${active ? "border-l-blue-400/60" : "border-l-white/10"}`} />
    </div>
  );
}

export function FlowChart({ nodes, currentNode }: FlowChartProps) {
  return (
    <div className="w-full overflow-x-auto pb-2">
      <div className="flex items-center min-w-max">
        {NODE_DEFS.map((def, idx) => {
          const node = getNodeData(nodes, def.id);
          const status: PipelineNodeStatus = node?.status ?? "idle";
          const styles = statusStyles[status];
          const isCurrent = currentNode === def.id;

          return (
            <div key={def.id} className="flex items-center">
              <div
                className={[
                  "relative flex flex-col items-center w-20 rounded-xl border px-2 py-3 transition-all duration-300",
                  styles.ring,
                  styles.bg,
                  isCurrent ? "shadow-[0_0_16px_rgba(96,165,250,0.35)]" : "",
                ].join(" ")}
              >
                {/* status dot */}
                <span className={`absolute top-1.5 right-1.5 w-2 h-2 rounded-full ${styles.dot}`} />
                <span className="text-xl mb-1">{def.icon}</span>
                <span className={`text-xs font-medium ${styles.text}`}>{def.label}</span>
                {node?.duration_seconds != null && (
                  <span className="text-[10px] text-slate-500 mt-0.5">{node.duration_seconds}s</span>
                )}
                {node?.output_count != null && (
                  <span className="text-[10px] text-slate-500">{node.output_count}个</span>
                )}
                {status === "running" && (
                  <div className="mt-1.5 w-12 h-1 rounded-full bg-slate-700 overflow-hidden">
                    <div className="h-full bg-blue-400 rounded-full animate-[progress_1.5s_ease-in-out_infinite]" style={{ width: "60%" }} />
                  </div>
                )}
              </div>
              {idx < NODE_DEFS.length - 1 && (
                <ConnectorArrow active={status === "completed" || status === "running"} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
