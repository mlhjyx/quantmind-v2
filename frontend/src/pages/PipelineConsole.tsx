import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

const LEVELS = ["L0", "L1", "L2", "L3"] as const;

export default function PipelineConsole() {
  return (
    <div>
      <Breadcrumb items={[{ label: "AI闭环" }, { label: "Pipeline控制台" }]} />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">AI Pipeline 控制台</h1>
          <p className="text-sm text-slate-400 mt-0.5">自动化级别 · 待审批队列 · 运行历史</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">暂停</Button>
          <Button size="sm">手动触发 Pipeline</Button>
        </div>
      </div>

      {/* Automation level selector placeholder */}
      <div className="flex gap-2 mb-4">
        {LEVELS.map((l, i) => (
          <button
            key={l}
            className={[
              "px-4 py-1.5 text-xs font-semibold rounded-lg border transition-colors",
              i === 1
                ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                : "bg-transparent border-white/10 text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {l}
          </button>
        ))}
        <span className="text-xs text-slate-500 self-center ml-1">当前: L1 半自动</span>
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">🤖</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">AI Pipeline 控制台</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示：8节点Pipeline状态流程图（发现→评估→入库→构建→回测→诊断→风控→部署）、待审批队列（因子/策略批准/拒绝）、调度配置、运行历史、AI决策日志。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/pipeline/status · GET /api/pipeline/pending · WebSocket: /ws/pipeline/{"{runId}"}
        </p>
      </GlassCard>
    </div>
  );
}
