import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

const AGENTS = ["因子发现", "策略构建", "诊断优化", "风控监督"] as const;

export default function AgentConfig() {
  return (
    <div>
      <Breadcrumb
        items={[
          { label: "AI闭环", path: "/pipeline" },
          { label: "Agent配置" },
        ]}
      />
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Agent 配置</h1>
          <p className="text-sm text-slate-400 mt-0.5">4个 Agent 决策规则与阈值</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" size="sm">恢复默认</Button>
          <Button size="sm">保存配置</Button>
        </div>
      </div>

      {/* Agent tabs placeholder */}
      <div className="flex gap-1 mb-4">
        {AGENTS.map((a, i) => (
          <button
            key={a}
            className={[
              "px-3 py-1.5 text-xs rounded-lg border transition-colors",
              i === 0
                ? "bg-blue-600/20 border-blue-500/40 text-blue-300"
                : "bg-transparent border-white/10 text-slate-400 hover:text-slate-200",
            ].join(" ")}
          >
            {a}
          </button>
        ))}
      </div>

      <GlassCard className="flex flex-col items-center justify-center py-20 text-center">
        <div className="text-5xl mb-4">⚙️</div>
        <h2 className="text-lg font-semibold text-slate-200 mb-2">Agent 配置</h2>
        <p className="text-sm text-slate-400 max-w-md">
          将显示4个Agent Tab（因子发现/策略构建/诊断优化/风控监督），每个含：决策规则阈值、LLM/GP配置、入库/风控阈值、自动修复权限开关。
        </p>
        <p className="text-xs text-slate-500 mt-4">
          API: GET /api/agent/{"{name}"}/config · PUT /api/agent/{"{name}"}/config
        </p>
      </GlassCard>
    </div>
  );
}
